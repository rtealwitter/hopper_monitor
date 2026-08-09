#!/usr/bin/env python3
"""
Reads data/gpu_samples.jsonl (nvidia-smi, via ssh to GPU nodes) and
data/queue_samples.jsonl (squeue + sprio + scontrol, login node only) and
writes assets/*.png + README.md (rolling last 7 days), plus one archived
snapshot per fully-elapsed calendar week under archive/<mon>_<sun>/. Runs on
a compute node via `sbatch --wait` from run.sh - never on the login node (no
numpy/matplotlib there).

No pandas - stdlib json/statistics/collections only, matching the rest of this
repo's minimalism.
"""
import json
import statistics as stats
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DIR = Path(__file__).resolve().parent
ASSETS = DIR / "assets"
ASSETS.mkdir(exist_ok=True)
ARCHIVE = DIR / "archive"
ARCHIVE.mkdir(exist_ok=True)

ROLLING_WINDOW_DAYS = 7

# Matches Slurm's own PriorityDecayHalfLife, so "decayed usage" here tracks
# fairshare accounting rather than a lifetime-cumulative total.
HALF_LIFE_HOURS = 168.0

# Fixed-order categorical palette; witter-lab pinned to teal, other labs take
# the rest in order, extras fold into "Other" (muted gray).
WITTER_LAB = "witter-lab"
WITTER_COLOR = "#009999"
LAB_COLORS = ["#2a78d6", "#eb6834", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#898781"
# GPU utilization real but not attributable to any job/lab.
UNATTRIB_FILL = "#898781"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": INK_MUTED, "axes.labelcolor": INK_SECONDARY,
    "text.color": INK, "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
    "grid.color": GRID, "font.size": 10, "axes.grid": True,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
})


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def monday_of(dt):
    """00:00 on the Monday of dt's calendar week, same tz as dt."""
    monday_date = (dt - timedelta(days=dt.weekday())).date()
    return datetime.combine(monday_date, datetime.min.time(), tzinfo=dt.tzinfo)


def rgba(hexcolor, alpha):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (r, g, b, alpha)


def lighten(hexcolor, amount=0.85):
    """Blend hexcolor toward white by `amount` (0=no change, 1=white) - a
    soft pastel tint for a table-row background behind black text."""
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def lab_palette(labs):
    """Fixed-order hue assignment; witter-lab is always teal. Labs beyond
    the remaining 7 slots fold into 'Other'."""
    ranked = sorted(l for l in labs if l != WITTER_LAB)
    colors = {}
    shown = []
    if WITTER_LAB in labs:
        colors[WITTER_LAB] = WITTER_COLOR
        shown.append(WITTER_LAB)
    for lab, color in zip(ranked, LAB_COLORS):
        colors[lab] = color
        shown.append(lab)
    for lab in ranked[len(LAB_COLORS):]:
        colors[lab] = OTHER_COLOR
    return colors, set(shown)


def bucket_label(lab, shown):
    return lab if lab in shown else "Other"


def interval_hours(sorted_distinct_ts):
    """Wall-clock hours each sample timestamp represents, for GPU/CPU-hour
    integration - the gap to the next sample, falling back to the median gap
    for the final (still-open) sample."""
    if not sorted_distinct_ts:
        return {}
    deltas = []
    intervals = {}
    for i in range(len(sorted_distinct_ts) - 1):
        d = (sorted_distinct_ts[i + 1] - sorted_distinct_ts[i]).total_seconds() / 3600
        deltas.append(d)
        intervals[sorted_distinct_ts[i]] = d
    intervals[sorted_distinct_ts[-1]] = stats.median(deltas) if deltas else 0.5
    return intervals


def percentile(sorted_vals, p):
    """Linear-interpolation percentile (numpy/Excel default)."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def usage_chart(path, title, ylabel, x, series_by_lab, colors, shown,
                 unattrib_y=None, unattrib_label="usage, unattributed",
                 overlay_y=None, overlay_label="cluster capacity"):
    """series_by_lab: {lab: (utilized_list, idle_list)}, idle_list None if
    the chart has no utilization concept (CPU: allocation only). Stacks each
    lab's utilized (solid) + idle (hatched, same color), then unattrib_y
    (gray) and overlay_y (dashed reference line) on top."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    labs = sorted(series_by_lab, key=lambda l: -sum(series_by_lab[l][0]))
    single_point = len(x) < 2
    has_idle = any(idle is not None for _, idle in series_by_lab.values())

    entries = []  # (label_or_None, values, facecolor, edgecolor, hatch)
    for l in labs:
        util_vals, idle_vals = series_by_lab[l]
        entries.append((bucket_label(l, shown), util_vals, colors[l], "none", None))
        if idle_vals is not None:
            entries.append((None, idle_vals, rgba(colors[l], 0.35), colors[l], "///"))
    if unattrib_y is not None:
        entries.append((unattrib_label, unattrib_y, UNATTRIB_FILL, UNATTRIB_FILL, None))

    if entries:
        if single_point:
            bottom = 0
            for label, vals, fc, ec, hatch in entries:
                v = vals[0]
                ax.bar(x[0], v, bottom=bottom, width=0.01, color=fc,
                       edgecolor=(fc if ec == "none" else ec), hatch=hatch, label=label)
                bottom += v
        else:
            all_y = [e[1] for e in entries]
            all_colors = [e[2] for e in entries]
            polys = ax.stackplot(x, *all_y, colors=all_colors, edgecolor=SURFACE, linewidth=1)
            for poly, (label, vals, fc, ec, hatch) in zip(polys, entries):
                if hatch:
                    poly.set_hatch(hatch)
                    poly.set_edgecolor(ec)
                    poly.set_linewidth(0.6)
                if label:
                    poly.set_label(label)
    if overlay_y is not None:
        if len(x) < 2:
            ax.scatter(x, overlay_y, color=INK_MUTED, marker="_", s=300,
                       linewidth=1.5, label=overlay_label)
        else:
            ax.plot(x, overlay_y, color=INK_MUTED, linewidth=1.5,
                     linestyle="--", label=overlay_label)
    all_x = list(x)
    if all_x:
        lo, hi = min(all_x), max(all_x)
        pad = timedelta(minutes=30) if lo == hi else (hi - lo) * 0.05
        ax.set_xlim(lo - pad, hi + pad)
    ax.set_title(title, color=INK, fontsize=12, loc="left")
    ax.set_ylabel(ylabel)
    fig.autofmt_xdate()
    handles, labels_ = ax.get_legend_handles_labels()
    if has_idle:
        handles.append(mpatches.Patch(facecolor=rgba(INK_MUTED, 0.35), edgecolor=INK_MUTED,
                                       hatch="///", label="allocated, idle (per lab)"))
    if handles:
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1),
                   frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def compute_headline(gpu_rows, cpu_util_rows, queue_rows_all):
    """Headline percentages + per-lab/user table from a given sample set -
    caller decides the time window (or none) by what rows it passes in.
    Self-contained (redoes the same dedupe/backfill/CPU-equivalent work
    render() does for its charts) so it can be run once over all-time data
    and once over a windowed slice without the two runs interfering."""
    queue_rows = [r for r in queue_rows_all
                  if r.get("kind") not in ("totals", "gpu_bind", "job_id_map")]
    totals_rows = [r for r in queue_rows_all if r.get("kind") == "totals"]
    gpu_bind_rows = [r for r in queue_rows_all if r.get("kind") == "gpu_bind"]

    # dict(r): copy, not reference - gpu_rows may be the same row objects
    # render() (or another compute_headline() call) is also backfilling;
    # mutating shared dicts here would make the other pass's own backfilled
    # count silently undercount.
    by_key = {}
    for r in gpu_rows:
        key = (r["ts"], r["node"], r["gpu_idx"])
        if key not in by_key or (r.get("job") and not by_key[key].get("job")):
            by_key[key] = dict(r)
    gpu_dedup = list(by_key.values())

    bind_job_by_key = {(r["ts"], r["node"], r["gpu_idx"]): r["job_id"] for r in gpu_bind_rows}
    owner_by_ts_job = {(r["ts"], r["job_id"]): (r.get("user"), r.get("lab"))
                        for r in queue_rows if r.get("job_id")}
    for r in gpu_dedup:
        if r.get("job"):
            continue
        job_id = bind_job_by_key.get((r["ts"], r["node"], r["gpu_idx"]))
        owner = owner_by_ts_job.get((r["ts"], job_id)) if job_id else None
        if owner:
            r["job"], r["user"], r["lab"] = job_id, owner[0], owner[1]

    raw_to_display_by_ts = defaultdict(dict)
    for r in queue_rows_all:
        if r.get("kind") == "job_id_map":
            raw_to_display_by_ts[r["ts"]][r["raw_id"]] = r["job_id"]

    cpu_by_node_job = defaultdict(list)
    for r in cpu_util_rows:
        cpu_by_node_job[(r["node"], r["job_id"])].append((r["ts"], r["cpu_usage_usec"]))

    cpu_equiv_by_ts_job = defaultdict(float)
    for (node, raw_id), samples in cpu_by_node_job.items():
        samples.sort(key=lambda s: parse_ts(s[0]))
        for (t_prev, u_prev), (t_cur, u_cur) in zip(samples, samples[1:]):
            wall_seconds = (parse_ts(t_cur) - parse_ts(t_prev)).total_seconds()
            delta_usec = u_cur - u_prev
            if wall_seconds <= 0 or delta_usec < 0:
                continue
            display_id = raw_to_display_by_ts.get(t_cur, {}).get(raw_id)
            if not display_id:
                continue
            cpu_equiv_by_ts_job[(t_cur, display_id)] += delta_usec / wall_seconds / 1_000_000.0

    latest_totals = totals_rows[-1] if totals_rows else {"cpus_total": 0, "gpus_total": 0}
    gpus_total = latest_totals["gpus_total"] or 1
    cpus_total = latest_totals["cpus_total"] or 1

    by_ts_totals = defaultdict(lambda: {"cpus_total": 0, "gpus_total": 0})
    for r in totals_rows:
        by_ts_totals[r["ts"]] = r

    running = [r for r in queue_rows if r["state"] == "RUNNING"]
    gpus_alloc_by_ts = defaultdict(int)
    for r in running:
        gpus_alloc_by_ts[r["ts"]] += r["gpus"]

    pct_gpu_alloc_samples = []
    for ts, g in gpus_alloc_by_ts.items():
        tot = by_ts_totals.get(ts, {}).get("gpus_total") or gpus_total
        pct_gpu_alloc_samples.append(100 * g / tot)
    pct_gpu_alloc = stats.mean(pct_gpu_alloc_samples) if pct_gpu_alloc_samples else 0.0

    allocated_gpu_readings = [r for r in gpu_dedup if r.get("job")]
    pct_util_when_alloc = (stats.mean(r["util_gpu"] for r in allocated_gpu_readings)
                            if allocated_gpu_readings else 0.0)

    cpus_alloc_by_ts_job = {(r["ts"], r["job_id"]): r["cpus"] for r in running}
    cpu_util_fractions = []
    for (t, job_id), equiv in cpu_equiv_by_ts_job.items():
        cores = cpus_alloc_by_ts_job.get((t, job_id))
        if cores:
            cpu_util_fractions.append(100 * min(1.0, equiv / cores))
    pct_cpu_util_when_alloc = stats.mean(cpu_util_fractions) if cpu_util_fractions else 0.0

    distinct_ts = sorted({parse_ts(r["ts"]) for r in queue_rows})
    intervals = interval_hours(distinct_ts)

    gpu_hours = defaultdict(float)
    cpu_hours = defaultdict(float)
    for r in running:
        key = (r["user"] or "unknown", r["lab"] or "unknown")
        h = intervals.get(parse_ts(r["ts"]), 0.5)
        gpu_hours[key] += r["gpus"] * h
        cpu_hours[key] += r["cpus"] * h

    util_by_user = defaultdict(list)
    for r in gpu_dedup:
        if r.get("user"):
            util_by_user[(r["user"], r.get("lab") or "unknown")].append(r["util_gpu"])

    table_keys = set(gpu_hours) | set(cpu_hours) | set(util_by_user)
    table_rows = []
    for key in table_keys:
        user, lab = key
        table_rows.append({
            "lab": lab, "user": user,
            "gpu_hours": gpu_hours.get(key, 0.0),
            "cpu_hours": cpu_hours.get(key, 0.0),
            "util_pct": stats.mean(util_by_user[key]) if util_by_user.get(key) else None,
        })
    table_rows.sort(key=lambda r: (-r["gpu_hours"]))

    # ---- worst-case escalation candidate: biggest allocation sitting on the
    # lowest utilization, gated on a minimum GPU-hour floor so a user with a
    # couple of idle hours doesn't outrank someone hoarding hundreds. ----
    escalation_min_gpu_hours = 50.0
    escalation_candidates = [r for r in table_rows
                              if r["util_pct"] is not None
                              and r["gpu_hours"] >= escalation_min_gpu_hours]
    worst_offender = (min(escalation_candidates, key=lambda r: r["util_pct"])
                       if escalation_candidates else None)

    all_labs = {r["lab"] for r in gpu_dedup if r.get("lab")} | \
               {r["lab"] for r in queue_rows if r.get("lab")}
    colors, shown = lab_palette(all_labs)

    return {
        "gpus_total": gpus_total, "cpus_total": cpus_total,
        "pct_gpu_alloc": pct_gpu_alloc, "pct_util_when_alloc": pct_util_when_alloc,
        "pct_cpu_util_when_alloc": pct_cpu_util_when_alloc,
        "table_rows": table_rows, "colors": colors, "shown": shown,
        "worst_offender": worst_offender,
        "escalation_min_gpu_hours": escalation_min_gpu_hours,
        "n_queue_snapshots": len(distinct_ts),
        "n_gpu_snapshots": len({r["ts"] for r in gpu_dedup}),
    }


def render(gpu_rows_all, cpu_util_rows_all, queue_rows_all_unfiltered,
           assets_dir, readme_path, window_start, window_end, img_prefix,
           live, back_link=None, archive_links=None):
    """Builds one full report (charts + README.md) from samples in
    [window_start, window_end). Used both for the live rolling-7-day
    dashboard (assets_dir=assets/, img_prefix="assets/") and for a single
    archived calendar week (assets_dir=readme_path.parent, img_prefix="")."""
    assets_dir.mkdir(parents=True, exist_ok=True)

    def in_window(r):
        return window_start <= parse_ts(r["ts"]) < window_end

    gpu_rows = [r for r in gpu_rows_all if in_window(r)]
    cpu_util_rows = [r for r in cpu_util_rows_all if in_window(r)]
    queue_rows_all = [r for r in queue_rows_all_unfiltered if in_window(r)]
    queue_rows = [r for r in queue_rows_all
                  if r.get("kind") not in ("totals", "gpu_bind", "job_id_map")]
    totals_rows = [r for r in queue_rows_all if r.get("kind") == "totals"]
    gpu_bind_rows = [r for r in queue_rows_all if r.get("kind") == "gpu_bind"]
    job_id_map_rows = [r for r in queue_rows_all if r.get("kind") == "job_id_map"]

    if not gpu_rows and not queue_rows:
        lines = ["# hopper_monitor", "",
                  f"No samples between {window_start:%Y-%m-%d} and "
                  f"{window_end:%Y-%m-%d}."]
        if archive_links:
            lines += ["", "## Weekly archives", ""]
            lines += [f"- [{label}]({link})" for label, link in archive_links]
        readme_path.write_text("\n".join(lines) + "\n")
        return

    # ---- headline stats + per-lab/user table: on the live dashboard, once
    # over all-time data and once over just this window; archived weeks only
    # ever cover their own window, so there's no separate "all time" cut. ----
    headline_week = compute_headline(gpu_rows, cpu_util_rows, queue_rows_all)
    headline_all = (compute_headline(gpu_rows_all, cpu_util_rows_all, queue_rows_all_unfiltered)
                     if live else None)

    # ---- dedupe GPU readings to one row per (ts, node, gpu_idx). dict(r):
    # copy, not reference - main() reuses the same loaded row objects across
    # multiple render() calls (each archived week, plus the live dashboard),
    # and mutating them here for backfill would make a later call's own
    # backfilled count silently undercount. ----
    by_key = {}
    for r in gpu_rows:
        key = (r["ts"], r["node"], r["gpu_idx"])
        # prefer the row that carries an attributed job, if any duplicate exists
        if key not in by_key or (r.get("job") and not by_key[key].get("job")):
            by_key[key] = dict(r)
    gpu_dedup = list(by_key.values())

    # ---- backfill job/user/lab from Slurm's GPU binding record (scontrol),
    # for readings the PID-based lookup in run.sh missed (e.g. containerized
    # processes). Only fills gaps. ----
    bind_job_by_key = {(r["ts"], r["node"], r["gpu_idx"]): r["job_id"] for r in gpu_bind_rows}
    owner_by_ts_job = {(r["ts"], r["job_id"]): (r.get("user"), r.get("lab"))
                        for r in queue_rows if r.get("job_id")}
    backfilled = 0
    for r in gpu_dedup:
        if r.get("job"):
            continue
        job_id = bind_job_by_key.get((r["ts"], r["node"], r["gpu_idx"]))
        owner = owner_by_ts_job.get((r["ts"], job_id)) if job_id else None
        if not owner:
            continue
        r["job"], r["user"], r["lab"] = job_id, owner[0], owner[1]
        backfilled += 1

    # ---- CPU utilization from cgroup accounting: delta of cumulative
    # usage_usec between consecutive samples, divided by wall-clock seconds,
    # gives CPU-equivalents busy. job_id_map translates raw cgroup ids to
    # the display job id everything else joins on.
    raw_to_display_by_ts = defaultdict(dict)
    for r in job_id_map_rows:
        raw_to_display_by_ts[r["ts"]][r["raw_id"]] = r["job_id"]

    cpu_by_node_job = defaultdict(list)
    for r in cpu_util_rows:
        cpu_by_node_job[(r["node"], r["job_id"])].append((r["ts"], r["cpu_usage_usec"]))

    cpu_equiv_by_ts_job = defaultdict(float)  # (ts, display_job_id) -> CPU-equivalents
    for (node, raw_id), samples in cpu_by_node_job.items():
        samples.sort(key=lambda s: parse_ts(s[0]))
        for (t_prev, u_prev), (t_cur, u_cur) in zip(samples, samples[1:]):
            wall_seconds = (parse_ts(t_cur) - parse_ts(t_prev)).total_seconds()
            delta_usec = u_cur - u_prev
            if wall_seconds <= 0 or delta_usec < 0:
                continue  # non-positive gap, or a cgroup reset/restart - no meaningful rate
            display_id = raw_to_display_by_ts.get(t_cur, {}).get(raw_id)
            if not display_id:
                continue
            cpu_equiv_by_ts_job[(t_cur, display_id)] += delta_usec / wall_seconds / 1_000_000.0

    by_ts_lab_cpu_util = defaultdict(lambda: defaultdict(float))
    by_ts_total_cpu_util = defaultdict(float)
    for (t, job_id), equiv in cpu_equiv_by_ts_job.items():
        by_ts_total_cpu_util[t] += equiv
        owner = owner_by_ts_job.get((t, job_id))
        if owner and owner[1]:
            by_ts_lab_cpu_util[t][owner[1]] += equiv

    all_labs = {r["lab"] for r in gpu_dedup if r.get("lab")} | \
               {r["lab"] for r in queue_rows if r.get("lab")}
    colors, shown = lab_palette(all_labs)

    # ================= chart-only derived data (headline stats above cover
    #                    the percentages/table; charts still need per-ts,
    #                    per-lab series and cluster-capacity overlays) =================
    latest_totals = totals_rows[-1] if totals_rows else {"cpus_total": 0, "gpus_total": 0}
    gpus_total = latest_totals["gpus_total"] or 1
    cpus_total = latest_totals["cpus_total"] or 1

    by_ts_totals = defaultdict(lambda: {"cpus_total": 0, "gpus_total": 0})
    for r in totals_rows:
        by_ts_totals[r["ts"]] = r

    running = [r for r in queue_rows if r["state"] == "RUNNING"]

    distinct_ts = sorted({parse_ts(r["ts"]) for r in queue_rows})
    intervals = interval_hours(distinct_ts)

    # ================= chart 1 & 2: CPU / GPU allocation over time, by lab -
    #                    standardized: same title pattern, same "GPUs"/"CPUs"
    #                    axis convention, same cluster-capacity dashed
    #                    overlay, same usage_chart() code path, same
    #                    utilized(solid)/idle(hatched)/unattributed(gray)
    #                    structure, for both. =================
    alloc_by_ts_lab_gpu = defaultdict(lambda: defaultdict(int))
    alloc_by_ts_lab_cpu = defaultdict(lambda: defaultdict(int))
    for r in running:
        lab = r["lab"] or "unknown"
        alloc_by_ts_lab_gpu[r["ts"]][lab] += r["gpus"]
        alloc_by_ts_lab_cpu[r["ts"]][lab] += r["cpus"]

    ts_sorted_cpu = sorted({r["ts"] for r in running} | set(by_ts_total_cpu_util), key=parse_ts)
    x_cpu = [parse_ts(t) for t in ts_sorted_cpu]
    labs_cpu = {lab for v in alloc_by_ts_lab_cpu.values() for lab in v} | \
               {lab for v in by_ts_lab_cpu_util.values() for lab in v}
    series_cpu = {}
    for lab in labs_cpu:
        util_list = [by_ts_lab_cpu_util[t].get(lab, 0.0) for t in ts_sorted_cpu]
        alloc_list = [alloc_by_ts_lab_cpu.get(t, {}).get(lab, 0) for t in ts_sorted_cpu]
        idle_list = [max(0.0, a - u) for a, u in zip(alloc_list, util_list)]
        series_cpu[lab] = (util_list, idle_list)
    attributed_cpu_total = {t: sum(by_ts_lab_cpu_util[t].values()) for t in ts_sorted_cpu}
    unattrib_cpu_y = [max(0.0, by_ts_total_cpu_util.get(t, 0.0) - attributed_cpu_total[t])
                       for t in ts_sorted_cpu]
    cap_cpu = [by_ts_totals.get(t, {}).get("cpus_total") or cpus_total for t in ts_sorted_cpu]
    usage_chart(assets_dir / "cpu_alloc.png", "CPU allocation over time (by lab)",
                "CPUs", x_cpu, series_cpu, colors, shown,
                unattrib_y=unattrib_cpu_y, unattrib_label="computing, unattributed",
                overlay_y=cap_cpu)

    by_ts_lab_util = defaultdict(lambda: defaultdict(float))
    by_ts_total_util = defaultdict(float)
    for r in gpu_dedup:
        by_ts_total_util[r["ts"]] += r["util_gpu"] / 100.0
        if r.get("job") and r.get("lab"):
            by_ts_lab_util[r["ts"]][r["lab"]] += r["util_gpu"] / 100.0

    ts_sorted_gpu = sorted({r["ts"] for r in gpu_dedup}, key=parse_ts)
    x_gpu = [parse_ts(t) for t in ts_sorted_gpu]
    labs_gpu = {lab for v in by_ts_lab_util.values() for lab in v} | \
               {lab for v in alloc_by_ts_lab_gpu.values() for lab in v}
    series_gpu = {}
    for lab in labs_gpu:
        util_list = [by_ts_lab_util[t].get(lab, 0.0) for t in ts_sorted_gpu]
        alloc_list = [alloc_by_ts_lab_gpu.get(t, {}).get(lab, 0) for t in ts_sorted_gpu]
        idle_list = [max(0.0, a - u) for a, u in zip(alloc_list, util_list)]
        series_gpu[lab] = (util_list, idle_list)
    attributed_total = {t: sum(by_ts_lab_util[t].values()) for t in ts_sorted_gpu}
    unattrib_y = [max(0.0, by_ts_total_util[t] - attributed_total[t]) for t in ts_sorted_gpu]
    cap_gpu = [by_ts_totals.get(t, {}).get("gpus_total") or gpus_total for t in ts_sorted_gpu]

    usage_chart(assets_dir / "gpu_alloc_util.png", "GPU allocation over time (by lab)",
                "GPUs", x_gpu, series_gpu, colors, shown,
                unattrib_y=unattrib_y, unattrib_label="computing, unattributed",
                overlay_y=cap_gpu)

    # ================= bonus: queue wait time trend =================
    # Only jobs sprio actually scores (has a priority) - excludes jobs
    # blocked on a dependency or array-task throttle, not eligible to run yet.
    # x-axis is every queue snapshot (same timestamps as the alloc charts
    # above), not just the ones with an eligible pending job - a snapshot
    # with nothing eligible to wait genuinely had a 0-hour queue, not a
    # missing data point.
    pending = [r for r in queue_rows if r["state"] == "PENDING"
               and r["wait_seconds"] is not None and r.get("priority") is not None]
    by_ts_wait = defaultdict(list)
    for r in pending:
        by_ts_wait[r["ts"]].append(r["wait_seconds"] / 3600.0)
    if queue_rows:
        ts_sorted4 = sorted({r["ts"] for r in queue_rows}, key=parse_ts)
        x4 = [parse_ts(t) for t in ts_sorted4]
        med = [percentile(sorted(by_ts_wait[t]), 50) if t in by_ts_wait else 0.0
               for t in ts_sorted4]
        p90 = [percentile(sorted(by_ts_wait[t]), 90) if t in by_ts_wait else 0.0
               for t in ts_sorted4]
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(x4, med, color=LAB_COLORS[0], linewidth=2, marker="o", markersize=4,
                 label="median wait")
        ax.plot(x4, p90, color=LAB_COLORS[1], linewidth=1.5, linestyle="--",
                 marker="o", markersize=4, label="p90 wait")
        lo, hi = min(x4), max(x4)
        pad = timedelta(minutes=30) if lo == hi else (hi - lo) * 0.05
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_title("Queue wait time (eligible pending jobs)", loc="left")
        ax.set_ylabel("hours waited so far")
        fig.autofmt_xdate()
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(assets_dir / "queue_wait.png", dpi=150)
        plt.close(fig)
        have_queue_wait = True
    else:
        have_queue_wait = False

    # ================= bonus: CPU usage vs. GPU usage, decayed with a half-life =================
    # Usage decayed on Slurm's own fairshare half-life; one point per (user,
    # snapshot) to show drift over time rather than one collapsed number.
    cpu_raw_by_user = defaultdict(dict)
    gpu_raw_by_user = defaultdict(dict)
    for r in running:
        u = r["user"] or "unknown"
        cpu_raw_by_user[u][r["ts"]] = cpu_raw_by_user[u].get(r["ts"], 0) + r["cpus"]
        gpu_raw_by_user[u][r["ts"]] = gpu_raw_by_user[u].get(r["ts"], 0) + r["gpus"]

    user_snapshots = defaultdict(set)
    for r in queue_rows:
        if r.get("user"):
            user_snapshots[r["user"]].add(r["ts"])

    ts_sorted_all = sorted({r["ts"] for r in queue_rows}, key=parse_ts)
    decay_points = []  # (cpu_decayed, gpu_decayed)
    for u, snaps in user_snapshots.items():
        cpu_d = gpu_d = 0.0
        prev_dt = None
        cpu_raw = cpu_raw_by_user.get(u, {})
        gpu_raw = gpu_raw_by_user.get(u, {})
        for ts_str in ts_sorted_all:
            dt = parse_ts(ts_str)
            if prev_dt is not None:
                factor = 0.5 ** ((dt - prev_dt).total_seconds() / 3600.0 / HALF_LIFE_HOURS)
                cpu_d *= factor
                gpu_d *= factor
            h = intervals.get(dt, 0.5)
            cpu_d += cpu_raw.get(ts_str, 0.0) * h
            gpu_d += gpu_raw.get(ts_str, 0.0) * h
            if ts_str in snaps:
                decay_points.append((cpu_d, gpu_d))
            prev_dt = dt

    if decay_points:
        cpu_vals = [p[0] for p in decay_points]
        gpu_vals = [p[1] for p in decay_points]
        fig, ax = plt.subplots(figsize=(7.5, 6))
        ax.scatter(cpu_vals, gpu_vals, color=INK, alpha=0.12, s=26, linewidth=0)
        ax.set_xlabel("decayed CPU usage (CPU-hours, ~7-day half-life)")
        ax.set_ylabel("decayed GPU usage (GPU-hours, ~7-day half-life)")
        ax.set_title("CPU usage vs. GPU usage (decayed)", loc="left", fontsize=12)
        ax.text(0.02, 0.97, "low CPU usage (→ high priority),\nhigh GPU usage",
                transform=ax.transAxes, ha="left", va="top", fontsize=8,
                color=INK_SECONDARY, style="italic")
        fig.tight_layout()
        fig.savefig(assets_dir / "cpu_gpu_usage.png", dpi=150)
        plt.close(fig)
        have_usage_scatter = True
    else:
        have_usage_scatter = False

    # ================= write README =================
    def headline_block(heading_suffix, h):
        block = [f"## Headline{heading_suffix}", ""]
        block.append(f"- **{h['pct_gpu_alloc']:.1f}%** of the cluster's {h['gpus_total']} GPUs "
                      f"allocated, averaged across all samples")
        block.append(f"- **{h['pct_util_when_alloc']:.1f}%** average `nvidia-smi` utilization "
                      f"*when* a GPU is allocated to a job")
        block.append(f"- **{h['pct_cpu_util_when_alloc']:.1f}%** average cgroup CPU utilization "
                      f"*when* a CPU is allocated to a job")
        block.append("")
        return block

    def table_block(heading_suffix, h):
        block = [f"## Per lab / per user{heading_suffix}", "", "<table>",
                  "<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours allocated</th>"
                  "<th align='right'>CPU-hours allocated</th><th align='right'>GPU utilization</th></tr>"]
        for row in h["table_rows"]:
            util = f"{row['util_pct']:.0f}%" if row["util_pct"] is not None else "—"
            color = h["colors"].get(row["lab"], OTHER_COLOR)
            bg = lighten(color)
            block.append(f"<tr style='background-color:{bg}'>"
                          f"<td>{row['lab']}</td><td>{row['user']}</td>"
                          f"<td align='right'>{row['gpu_hours']:.1f}</td>"
                          f"<td align='right'>{row['cpu_hours']:.1f}</td>"
                          f"<td align='right'>{util}</td></tr>")
        block.append("</table>")
        block.append("")
        return block

    lines = []
    lines.append("# hopper_monitor")
    lines.append("")
    if live:
        lines.append("Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, "
                     "updated every 30 minutes by cron. Usernames are anonymized to a "
                     "stable per-account pseudonym; lab names are real.")
        lines.append("")
        lines.append(f"Last updated: {window_end.isoformat(timespec='seconds')}")
        lines.append(f"Samples: {headline_all['n_queue_snapshots']} queue snapshots total "
                     f"({headline_week['n_queue_snapshots']} in the last {ROLLING_WINDOW_DAYS} "
                     f"days), {headline_all['n_gpu_snapshots']} GPU snapshots total "
                     f"({headline_week['n_gpu_snapshots']} in the last {ROLLING_WINDOW_DAYS} days)")
        lines.append("")
        lines.append("## Resources")
        lines.append("")
        lines.append(f"`hopper.cluster` currently reports **{gpus_total} GPUs** and "
                     f"**{cpus_total} CPUs** total:")
        lines.append("")
        lines.append("| Nodes | Count | CPUs/node | RAM/node | GPUs/node |")
        lines.append("|---|---:|---:|---:|---|")
        lines.append("| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |")
        lines.append("| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |")
        lines.append("")
        lines += headline_block(" (all time)", headline_all)
        lines += table_block(" (all time)", headline_all)
        lines += headline_block(f" (last {ROLLING_WINDOW_DAYS} days)", headline_week)
        lines += table_block(f" (last {ROLLING_WINDOW_DAYS} days)", headline_week)
    else:
        lines.append(f"Archived weekly snapshot: **{window_start:%Y-%m-%d} to "
                     f"{(window_end - timedelta(days=1)):%Y-%m-%d}**. Usernames are "
                     "anonymized to a stable per-account pseudonym; lab names are real.")
        lines.append("")
        if back_link:
            lines.append(f"[Back to the live dashboard]({back_link})")
            lines.append("")
        lines.append(f"Samples: {headline_week['n_queue_snapshots']} queue snapshots, "
                     f"{headline_week['n_gpu_snapshots']} GPU snapshots")
        lines.append("")
        lines += headline_block("", headline_week)
        lines += table_block("", headline_week)

    lines.append("## Usage over time")
    lines.append("")
    window_desc = f"the trailing {ROLLING_WINDOW_DAYS} days" if live else "this week"
    lines.append(f"Charts below cover {window_desc}: "
                 f"**{window_start:%Y-%m-%d %H:%M} to {window_end:%Y-%m-%d %H:%M}** "
                 f"({window_end.strftime('%Z') or 'local time'}).")
    lines.append("")
    lines.append(f"![CPU allocation over time]({img_prefix}cpu_alloc.png)")
    lines.append("")
    lines.append(f"![GPU allocation over time]({img_prefix}gpu_alloc_util.png)")
    lines.append("")
    lines.append("Solid = utilized by lab, hatched = allocated but idle, gray = usage not "
                 "traceable to a lab, dashed line = cluster capacity.")
    lines.append("")
    lines.append("Attribution combines `nvidia-smi`'s process listing with Slurm's "
                 "GPU-to-job binding record" +
                 (f"; the latter caught **{backfilled}** readings the former missed."
                  if backfilled else "."))
    lines.append("")
    if have_queue_wait:
        lines.append("## Queue")
        lines.append("")
        lines.append(f"![Queue wait time]({img_prefix}queue_wait.png)")
        lines.append("")
        lines.append("\"Pending\" here means Slurm is actively scoring the job (has a "
                     "`sprio` priority) - excludes jobs blocked on a dependency or "
                     "array-task throttle.")
        lines.append("")
    if have_usage_scatter:
        lines.append("## CPU usage vs. GPU usage")
        lines.append("")
        lines.append(f"![CPU usage vs GPU usage, decayed]({img_prefix}cpu_gpu_usage.png)")
        lines.append("")
        lines.append(f"One point per user per snapshot (n={len(decay_points)}), usage "
                     "decayed on Slurm's ~7-day fairshare half-life.")
        lines.append("")
        lines.append("**GPU usage doesn't count toward priority on this cluster** "
                     "(`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the "
                     "**upper-left**: low CPU usage (high priority) with high GPU usage.")
        lines.append("")

    if live and archive_links:
        lines.append("## Weekly archives")
        lines.append("")
        lines.append("Dated snapshots of this dashboard, one per fully-elapsed calendar week:")
        lines.append("")
        for label, link in archive_links:
            lines.append(f"- [{label}]({link})")
        lines.append("")

    if live:
        lines.append("## Recommendations")
        lines.append("")
        lines.append("1. **Weight GPU usage in fairshare.** `TRESBillingWeights` and "
                     "`PriorityWeightTRES` are both unset right now, so Slurm's fairshare "
                     "score only sees CPU-seconds - a job holding 4 idle L40S GPUs costs "
                     "nothing in priority as long as it isn't also holding CPUs. That's the "
                     "exact failure mode the scatter above is built to catch (upper-left: low "
                     "CPU usage, high GPU usage). Fix: "
                     "`scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>` "
                     "(or set `PriorityWeightTRES` cluster-wide), then `scontrol reconfigure` - "
                     "a full `slurmctld` restart also works but drops in-flight priority state. "
                     "A reasonable starting point for `<weight>` is the CPUs-per-GPU ratio on a "
                     "GPU node (128 CPUs / 4 GPUs = 32), so one GPU costs as much fairshare as "
                     f"the CPU share it displaces; tune from there against this week's headline "
                     f"numbers ({headline_week['pct_gpu_alloc']:.1f}% allocated, "
                     f"{headline_week['pct_util_when_alloc']:.1f}% utilized when allocated, over "
                     f"the last {ROLLING_WINDOW_DAYS} days). The weight value itself is "
                     "a policy call - loop in whoever owns cluster allocation policy before "
                     "changing it.")
        lines.append("")
        worst_offender = headline_week["worst_offender"]
        esc_line = ("2. **Escalate on sustained low utilization** (see table and scatter above). ")
        if worst_offender:
            esc_line += (
                f"Right now the clearest candidate is `{worst_offender['user']}` in "
                f"`{worst_offender['lab']}`: {worst_offender['gpu_hours']:.1f} GPU-hours "
                f"allocated at {worst_offender['util_pct']:.0f}% average utilization, i.e. "
                f"roughly {worst_offender['gpu_hours'] * (1 - worst_offender['util_pct'] / 100):.0f} "
                "GPU-hours that sat idle instead of going to someone in the queue. ")
        esc_line += (
            "Turning that into an automated escalation needs two decisions made up front: a "
            "utilization threshold (something like under 20% mean utilization over at least "
            f"{headline_week['escalation_min_gpu_hours']:.0f} allocated GPU-hours is a defensible starting bar - "
            "loose enough to skip short debugging runs, tight enough to catch parked "
            "allocations) and a grace period (how many consecutive low-utilization snapshots "
            "before it counts as \"sustained\" rather than a momentary lull between batches). "
            "Once those are set, the mechanism can be either soft (a bot that reads "
            "`data/gpu_samples.jsonl` and reminds the user/lab by email or Slack) or hard (a "
            "Slurm-side QOS penalty, e.g. `sacctmgr modify qos <qos> set Priority-=<n>`, applied "
            "after N consecutive offending snapshots). Neither exists yet - today the table and "
            "scatter above are a read-only signal, not an enforced policy.")
        lines.append(esc_line)
        lines.append("")

    readme_path.write_text("\n".join(lines) + "\n")


def main():
    gpu_rows = load_jsonl(DIR / "data" / "gpu_samples.jsonl")
    cpu_util_rows = load_jsonl(DIR / "data" / "cpu_samples.jsonl")
    queue_rows_all = load_jsonl(DIR / "data" / "queue_samples.jsonl")
    queue_rows_only = [r for r in queue_rows_all
                        if r.get("kind") not in ("totals", "gpu_bind", "job_id_map")]

    if not gpu_rows and not queue_rows_only:
        (DIR / "README.md").write_text(
            "# hopper_monitor\n\nNo samples recorded yet - check back after "
            "the next 30-minute cron tick.\n"
        )
        return

    now = datetime.now().astimezone()

    # ================= weekly archive catch-up =================
    # One dated snapshot per fully-elapsed calendar week (Monday-Sunday).
    # Idempotent: a week's folder, once created, is never regenerated - each
    # archive is a frozen record of that week, not a rolling one.
    all_ts = sorted({parse_ts(r["ts"]) for r in gpu_rows} |
                     {parse_ts(r["ts"]) for r in queue_rows_only} |
                     {parse_ts(r["ts"]) for r in cpu_util_rows})
    if all_ts:
        week_start = monday_of(all_ts[0])
        while week_start + timedelta(days=7) <= now:
            week_end = week_start + timedelta(days=7)
            has_data = any(week_start <= t < week_end for t in all_ts)
            if has_data:
                label = f"{week_start:%Y-%m-%d}_{(week_end - timedelta(days=1)):%Y-%m-%d}"
                week_dir = ARCHIVE / label
                if not week_dir.exists():
                    render(gpu_rows, cpu_util_rows, queue_rows_all,
                           week_dir, week_dir / "README.md",
                           week_start, week_end, img_prefix="", live=False,
                           back_link="../../README.md")
            week_start += timedelta(days=7)

    archive_links = sorted(
        ((p.name, f"archive/{p.name}/README.md") for p in ARCHIVE.iterdir() if p.is_dir()),
        reverse=True,
    )

    # ================= live rolling-window dashboard =================
    render(gpu_rows, cpu_util_rows, queue_rows_all, ASSETS, DIR / "README.md",
           now - timedelta(days=ROLLING_WINDOW_DAYS), now, img_prefix="assets/",
           live=True, archive_links=archive_links)


if __name__ == "__main__":
    main()
