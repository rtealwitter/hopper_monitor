"""Shared, side-effect-free joins for dashboard statistics and charts."""
from collections import defaultdict
from datetime import datetime


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def attribute_gpus(gpu_rows, queue_rows):
    """Count each physical GPU once, resolving owners from the same snapshot.

    Slurm bindings are authoritative for allocation. Cgroup raw IDs are a
    fallback when bindings are absent. Never guess ownership from memory use
    or borrow a binding from another timestamp.
    """
    jobs = {(r["ts"], r["job_id"]): r for r in queue_rows if "state" in r}
    raw_ids = {(r["ts"], r["raw_id"]): r["job_id"] for r in queue_rows
               if r.get("kind") == "job_id_map"}
    bindings = defaultdict(set)
    for r in queue_rows:
        if r.get("kind") == "gpu_bind":
            bindings[(r["ts"], r["node"], r["gpu_idx"])].add(r["job_id"])

    readings = {}
    owners = defaultdict(set)
    for source in gpu_rows:
        r = dict(source)
        key = (r["ts"], r["node"], r["gpu_idx"])
        bound = bindings.get(key, set())
        raw = (r.get("job") or "").removeprefix("job_")
        job_id = next(iter(bound)) if len(bound) == 1 else raw_ids.get((r["ts"], raw), raw)
        owner = jobs.get((r["ts"], job_id))
        if owner and owner["state"] == "RUNNING":
            r.update(job=job_id, user=owner.get("user"), lab=owner.get("lab"))
        if r.get("job") and r.get("lab"):
            owners[key].add((r["job"], r.get("user"), r["lab"]))
        # Prefer complete ownership if legacy shared-device rows are repeated.
        score = lambda row: (bool(row.get("job") and row.get("lab")), bool(row.get("user")))
        if key not in readings or score(r) > score(readings[key][0]):
            readings[key] = (r, not (source.get("job") and source.get("lab"))
                            and bool(r.get("job") and r.get("lab")))
    for key, (r, _) in list(readings.items()):
        if len(bindings.get(key, ())) > 1 or len(owners[key]) > 1:
            # A device-wide utilization percentage cannot be split among jobs.
            r.update(job=None, user=None, lab=None)
            readings[key] = (r, False)
    recovered = sum(fixed for _, fixed in readings.values())
    return [r for r, _ in readings.values()], recovered


def cpu_rates(cpu_rows, queue_rows):
    """CPU equivalents by (timestamp, display job ID), summed across nodes.

    Dedupe counters before differencing; skip resets. Non-array IDs already
    match the queue and do not require a redundant job_id_map record.
    """
    raw_ids = {(r["ts"], r["raw_id"]): r["job_id"] for r in queue_rows
               if r.get("kind") == "job_id_map"}
    samples = defaultdict(dict)
    for r in cpu_rows:
        samples[(r["node"], r["job_id"])][r["ts"]] = r["cpu_usage_usec"]
    rates = defaultdict(float)
    for (_, raw_id), counters in samples.items():
        ordered = sorted(counters, key=parse_ts)
        for before, after in zip(ordered, ordered[1:]):
            seconds = (parse_ts(after) - parse_ts(before)).total_seconds()
            delta = counters[after] - counters[before]
            if seconds > 0 and delta >= 0:
                job_id = raw_ids.get((after, raw_id), raw_id)
                rates[(after, job_id)] += delta / seconds / 1_000_000
    return rates
