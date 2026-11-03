"""Incremental, rebuildable accounting over the original JSONL samples.

SQLite stores byte ranges, CPU counter state, and small running totals, not
copies of the telemetry. Initial indexing and accounting process one snapshot
at a time. Later runs read appended bytes and replay the last queue snapshot
so its integration interval can be corrected when the next sample arrives.
"""
import calendar
from collections import defaultdict
import copy
import json
import os
from pathlib import Path
import sqlite3

from accounting import attribute_gpus, parse_ts
from data_store import sample_files, shared_json_decoder
from sample_queue import normalize_gpu_allocations

# Bump when accounting rules or the cache schema change.
VERSION = 1
STREAMS = ("gpu", "cpu", "queue")
SPECIAL = {"totals", "gpu_bind", "job_id_map", "priority_config"}


def empty_summary():
    return dict(gpus_total=0, cpus_total=0, alloc_sum=0., alloc_missing=0.,
                alloc_count=0, gpu_util_sum=0., gpu_util_count=0,
                cpu_busy=0., cpu_measured=0., n_queue_snapshots=0,
                n_gpu_snapshots=0, users={}, labs=[], hours={}, weekdays={})


class History:
    def __init__(self, root, *, rebuild=False):
        self.root = Path(root)
        self.db = sqlite3.connect(self.root / ".history.sqlite3")
        self.db.execute("PRAGMA cache_size=-8192")
        self.db.execute("PRAGMA temp_store=FILE")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if rebuild or version != VERSION:
            self.reset()

    def reset(self):
        with self.db:
            self.db.execute("BEGIN")
            for table in ("files", "ranges", "counters", "rates", "state"):
                self.db.execute(f"DROP TABLE IF EXISTS {table}")
            schema = """
                CREATE TABLE files (path TEXT PRIMARY KEY, offset INTEGER, size INTEGER, mtime INTEGER);
                CREATE TABLE ranges (stream TEXT, path TEXT, start INTEGER, stop INTEGER,
                                     ts TEXT, epoch REAL);
                CREATE INDEX ranges_time ON ranges(epoch, ts);
                CREATE INDEX ranges_stream_time ON ranges(stream, epoch, ts);
                CREATE TABLE counters (node TEXT, job TEXT, ts TEXT, value INTEGER,
                                       PRIMARY KEY(node, job));
                CREATE TABLE rates (epoch REAL, ts TEXT, job TEXT, value REAL,
                                    PRIMARY KEY(ts, job));
                CREATE INDEX rates_time ON rates(epoch);
                CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    self.db.execute(statement)
            self.db.execute(f"PRAGMA user_version={VERSION}")

    def close(self):
        self.db.close()

    def _get(self, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)",
                        (key, json.dumps(value)))

    def update(self):
        paths = {str(p.relative_to(self.root)): stream for stream in STREAMS
                 for p in sample_files(self.root / "data" / f"{stream}_samples.jsonl")}
        known = {p: (offset, size, mtime) for p, offset, size, mtime in
                 self.db.execute("SELECT * FROM files")}
        # Opening revalidates NFS attributes after another node appends data;
        # a bare stat can still report the preceding run's file size.
        stats = {}
        for name in paths:
            with (self.root / name).open("rb") as source:
                stats[name] = os.fstat(source.fileno())
        # Rewrites/removals invalidate offsets and derived accounting. An
        # explicit rebuild also handles intentional changes to old accounting.
        for name, (offset, size, mtime) in known.items():
            stat = stats.get(name)
            if stat is None or stat.st_size < size or (
                    stat.st_size == size and stat.st_mtime_ns != mtime):
                self.reset()
                known = {}
                break
        changed = None
        with self.db:
            for name, stream in paths.items():
                path = self.root / name
                stat = stats[name]
                offset, old_size, _ = known.get(name, (0, 0, 0))
                if name in known and stat.st_size == old_size:
                    continue
                with path.open("rb") as source:
                    source.seek(offset)
                    group = None
                    while True:
                        start = source.tell()
                        line = source.readline()
                        if not line or not line.endswith(b"\n"):
                            offset = start  # retry an unfinished append next time
                            break
                        offset = source.tell()
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = row["ts"]
                        epoch = parse_ts(ts).timestamp()
                        changed = epoch if changed is None else min(changed, epoch)
                        if group is not None and group[4] == ts:
                            group[3] = offset
                        else:
                            if group is not None:
                                self.db.execute("INSERT INTO ranges VALUES (?, ?, ?, ?, ?, ?)", group)
                            group = [stream, name, start, offset, ts, epoch]
                    if group is not None:
                        self.db.execute("INSERT INTO ranges VALUES (?, ?, ?, ?, ?, ?)", group)
                self.db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
                                (name, offset, stat.st_size, stat.st_mtime_ns))
            if changed is not None:
                self._account(changed)
        return changed is not None

    def rows(self, stream, start, end, *, timestamp=None):
        decoder = shared_json_decoder()
        query = "SELECT path, start, stop FROM ranges WHERE stream=? AND epoch>=? AND epoch<?"
        params = [stream, start, end]
        if timestamp is not None:
            query += " AND ts=?"
            params.append(timestamp)
        query += " ORDER BY path, start"
        # Hold at most one source file open. A range can cross many JSONL rows,
        # but only a snapshot (accounting) or a week (charts) is retained.
        handle = None
        current_path = None
        try:
            for name, first, stop in self.db.execute(query, params):
                if name != current_path:
                    if handle is not None:
                        handle.close()
                    handle = (self.root / name).open("rb")
                    current_path = name
                handle.seek(first)
                while handle.tell() < stop:
                    try:
                        yield decoder.decode(handle.readline().decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
        finally:
            if handle is not None:
                handle.close()

    def _account(self, changed):
        replay = self._get("replay")
        if replay is None or changed < replay:
            summary = empty_summary()
            self.db.execute("DELETE FROM counters")
            self.db.execute("DELETE FROM rates")
            start = float("-inf")
        else:
            summary = self._get("before_replay")
            for node, job, previous in self._get("undo", []):
                if previous is None:
                    self.db.execute("DELETE FROM counters WHERE node=? AND job=?", (node, job))
                else:
                    self.db.execute("INSERT OR REPLACE INTO counters VALUES (?, ?, ?, ?)",
                                    (node, job, *previous))
            self.db.execute("DELETE FROM rates WHERE epoch>=?", (replay,))
            start = replay
        next_replay = self.db.execute(
            "SELECT MAX(epoch) FROM ranges WHERE stream='queue'").fetchone()[0]
        if next_replay is None:
            next_replay = self.db.execute("SELECT MAX(epoch) FROM ranges").fetchone()[0]
        undo = {}
        before = None
        for epoch, ts in self.db.execute(
                "SELECT DISTINCT epoch, ts FROM ranges WHERE epoch>=? ORDER BY epoch, ts", (start,)):
            if epoch >= next_replay and before is None:
                before = copy.deepcopy(summary)
            queue = normalize_gpu_allocations(list(self.rows("queue", epoch, epoch + .0001, timestamp=ts)))
            gpu, _ = attribute_gpus(list(self.rows("gpu", epoch, epoch + .0001, timestamp=ts)), queue)
            cpu = {(r["node"], r["job_id"]): r for r in
                   self.rows("cpu", epoch, epoch + .0001, timestamp=ts)}
            raw_ids = {r["raw_id"]: r["job_id"] for r in queue if r.get("kind") == "job_id_map"}
            rates = defaultdict(float)
            for (node, job), row in cpu.items():
                previous = self.db.execute("SELECT ts, value FROM counters WHERE node=? AND job=?",
                                           (node, job)).fetchone()
                if epoch >= next_replay and (node, job) not in undo:
                    undo[(node, job)] = previous
                if previous is not None:
                    seconds = (parse_ts(ts) - parse_ts(previous[0])).total_seconds()
                    delta = row["cpu_usage_usec"] - previous[1]
                    if seconds > 0 and delta >= 0:
                        rates[raw_ids.get(job, job)] += delta / seconds / 1_000_000
                self.db.execute("INSERT OR REPLACE INTO counters VALUES (?, ?, ?, ?)",
                                (node, job, ts, row["cpu_usage_usec"]))
            self.db.executemany("INSERT OR REPLACE INTO rates VALUES (?, ?, ?, ?)",
                                [(epoch, ts, job, value) for job, value in rates.items()])
            following = self.db.execute(
                "SELECT MIN(epoch) FROM ranges WHERE stream='queue' AND epoch>?", (epoch,)).fetchone()[0]
            hours = min((following - epoch) / 3600, .5) if following is not None and queue else .5
            self._accumulate(summary, ts, queue, gpu, rates, hours)
        self._set("summary", summary)
        self._set("before_replay", before)
        self._set("replay", next_replay)
        self._set("undo", [[node, job, previous] for (node, job), previous in undo.items()])

    @staticmethod
    def _accumulate(s, ts, queue, gpu, rates, hours):
        jobs = [r for r in queue if r.get("kind") not in SPECIAL]
        totals = [r for r in queue if r.get("kind") == "totals"]
        running = [r for r in jobs if r["state"] == "RUNNING"]
        capacity = totals[-1].get("gpus_total", 0) if totals else 0
        if totals:
            s.update(gpus_total=totals[-1]["gpus_total"], cpus_total=totals[-1]["cpus_total"])
        allocated = sum(r["gpus"] for r in running)
        known_pct = 100 * allocated / capacity if capacity else 0.
        missing = 100 * allocated if not capacity else 0.
        if jobs or totals:
            s["alloc_sum"] += known_pct
            s["alloc_missing"] += missing
            s["alloc_count"] += 1
        if queue:
            s["n_queue_snapshots"] += 1
            dt = parse_ts(ts)
            for field, key in (("hours", str(dt.hour)), ("weekdays", str(dt.weekday()))):
                bucket = s[field].setdefault(key, [0., 0., 0])
                bucket[0] += known_pct
                bucket[1] += missing
                bucket[2] += 1
        if gpu:
            s["n_gpu_snapshots"] += 1
        for r in gpu:
            if r.get("job"):
                s["gpu_util_sum"] += r["util_gpu"]
                s["gpu_util_count"] += 1
        for r in running:
            cores = r["cpus"]
            if cores and r["job_id"] in rates:
                s["cpu_busy"] += min(cores, rates[r["job_id"]])
                s["cpu_measured"] += cores
        for row in [*jobs, *gpu]:
            if row.get("lab") and row["lab"] not in s["labs"]:
                s["labs"].append(row["lab"])

        def user_entry(user, lab):
            key = json.dumps([user or "unknown", lab or "unknown"])
            return s["users"].setdefault(key, dict(user=user or "unknown", lab=lab or "unknown",
                gpu_hours=0., cpu_hours=0., util_sum=0., util_count=0,
                measured_gpu_hours=0., idle_gpu_hours=0.))

        for r in running:
            entry = user_entry(r.get("user"), r.get("lab"))
            entry["gpu_hours"] += r["gpus"] * hours
            entry["cpu_hours"] += r["cpus"] * hours
        for r in gpu:
            if r.get("user"):
                entry = user_entry(r["user"], r.get("lab"))
                entry["util_sum"] += r["util_gpu"]
                entry["util_count"] += 1
                if r.get("job"):
                    entry["measured_gpu_hours"] += hours
                    entry["idle_gpu_hours"] += hours * (1 - r["util_gpu"] / 100)

    def headline(self, palette):
        s = self._get("summary", empty_summary())
        rows = []
        for original in s["users"].values():
            row = dict(original)
            count, total = row.pop("util_count"), row.pop("util_sum")
            row["util_pct"] = total / count if count else None
            if not row["measured_gpu_hours"]:
                row["idle_gpu_hours"] = None
            rows.append(row)
        rows.sort(key=lambda r: (-r["gpu_hours"], r["lab"], r["user"]))
        candidates = [r for r in rows if r["measured_gpu_hours"] >= 50]
        return dict(gpus_total=s["gpus_total"] or 1, cpus_total=s["cpus_total"] or 1,
            pct_gpu_alloc=(s["alloc_sum"] + s["alloc_missing"] / (s["gpus_total"] or 1)) / (s["alloc_count"] or 1),
            pct_util_when_alloc=s["gpu_util_sum"] / (s["gpu_util_count"] or 1),
            pct_cpu_util_when_alloc=100 * s["cpu_busy"] / (s["cpu_measured"] or 1),
            table_rows=rows, colors=palette(s["labs"]), escalation_min_gpu_hours=50.,
            worst_offender=max(candidates, key=lambda r: r["idle_gpu_hours"]) if candidates else None,
            n_queue_snapshots=s["n_queue_snapshots"], n_gpu_snapshots=s["n_gpu_snapshots"])

    def open_times(self):
        s = self._get("summary", empty_summary())
        if not s["hours"]:
            return None
        def means(field):
            return {int(key): (total + missing / (s["gpus_total"] or 1)) / count
                    for key, (total, missing, count) in s[field].items()}
        hours, days = means("hours"), means("weekdays")
        hour, day = min(hours, key=hours.get), min(days, key=days.get)
        n_days = self.db.execute(
            "SELECT COUNT(DISTINCT substr(ts, 1, 10)) FROM ranges WHERE stream='queue'").fetchone()[0]
        return dict(best_hour=hour, best_hour_pct=hours[hour], best_weekday=calendar.day_name[day],
                    best_weekday_pct=days[day], n_days=n_days)

    def window(self, start, end):
        lo, hi = start.timestamp(), end.timestamp()
        gpu = list(self.rows("gpu", lo, hi))
        queue = list(self.rows("queue", lo, hi))
        rates = {(ts, job): value for ts, job, value in self.db.execute(
            "SELECT ts, job, value FROM rates WHERE epoch>=? AND epoch<?", (lo, hi))}
        return gpu, queue, rates

    def first_timestamp(self):
        row = self.db.execute("SELECT ts FROM ranges ORDER BY epoch LIMIT 1").fetchone()
        return parse_ts(row[0]) if row else None

    def has_samples(self, start, end):
        return self.db.execute("SELECT 1 FROM ranges WHERE epoch>=? AND epoch<? LIMIT 1",
                               (start.timestamp(), end.timestamp())).fetchone() is not None
