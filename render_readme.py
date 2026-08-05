#!/usr/bin/env python3
"""
Reads data/gpu_samples.jsonl (nvidia-smi, via ssh to GPU nodes) and
data/queue_samples.jsonl (squeue + sprio + scontrol, login node only) and
writes assets/*.png + README.md. Runs on a compute node via `sbatch --wait`
from run.sh - never on the login node (no numpy/matplotlib there).

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
import matplotlib.dates as mdates
import matplotlib.patches as mpatches

DIR = Path(__file__).resolve().parent
ASSETS = DIR / "assets"
ASSETS.mkdir(exist_ok=True)

# Slurm's own usage decay (`scontrol show config` -> PriorityDecayHalfLife on
# this cluster). Used to compute "usage with a half-life" the same way Slurm's
# fairshare accounting does, rather than a lifetime-cumulative total.
HALF_LIFE_HOURS = 168.0

# Categorical palette (fixed order, validated for CVD/contrast on the stacked-
# area "adjacent" pairlist - see the dataviz skill; re-validated with this
# exact teal via scripts/validate_palette.js after swapping it in - all
# checks pass in this order). witter-lab is pinned to a true teal (#008080
# reads as too gray - chroma 0.093, below the validator's floor - #009999 is
# the nearest fully-saturated teal that still clears it) specifically by
# request; other labs take the remaining 7 colors in fixed order by name.
# Extra labs beyond 8 total fold into "Other" (muted gray) rather than
# generating a 9th hue.
WITTER_LAB = "witter-lab"
WITTER_COLOR = "#009999"
LAB_COLORS = ["#2a78d6", "#eb6834", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#898781"
# "Computing, unattributed" band: real nvidia-smi utilization that couldn't be
# joined to a job/lab (the ssh-based PID lookup misses some processes - see
# README note). Not lab-colored since we don't know which lab it belongs to.
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
    """Linear-interpolation percentile (the "linear" method numpy/Excel use
    by default). Monotonic in p by construction - p90 can never fall below
    p50 for the same data, unlike `sorted_vals[int(p/100 * (n-1))]`, which at
    small n rounds toward the wrong end: for n=2 it's `int(0.9*1)=0`, i.e.
    "p90" silently becomes the *smaller* of the two values."""
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
    """series_by_lab: {lab: (utilized_list, idle_list)}. idle_list may be
    None for a lab/chart with no utilization concept (CPU: allocation only,
    drawn solid, no hatch). For each lab (sorted by total descending): a
    solid segment in that lab's own color (utilized, or total allocation if
    idle_list is None), then, if given, a translucent hatched segment in the
    SAME color stacked directly on top (allocated but idle) - idle capacity
    stays visually anchored to the lab holding it, not lumped into one
    undifferentiated gray band. unattrib_y, if given, is one more neutral
    gray band on top (real usage that couldn't be traced to any lab).
    overlay_y, if given, is a dashed reference line (e.g. cluster capacity)."""
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
    tz = all_x[0].tzinfo if all_x else None
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=tz))
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


def main():
    gpu_rows = load_jsonl(DIR / "data" / "gpu_samples.jsonl")
    queue_rows_all = load_jsonl(DIR / "data" / "queue_samples.jsonl")
    queue_rows = [r for r in queue_rows_all if r.get("kind") not in ("totals", "gpu_bind")]
    totals_rows = [r for r in queue_rows_all if r.get("kind") == "totals"]
    gpu_bind_rows = [r for r in queue_rows_all if r.get("kind") == "gpu_bind"]

    if not gpu_rows and not queue_rows:
        (DIR / "README.md").write_text(
            "# hopper_monitor\n\nNo samples recorded yet - check back after "
            "the next 30-minute cron tick.\n"
        )
        return

    # ---- dedupe GPU readings to one row per (ts, node, gpu_idx) ----
    by_key = {}
    for r in gpu_rows:
        key = (r["ts"], r["node"], r["gpu_idx"])
        # prefer the row that carries an attributed job, if any duplicate exists
        if key not in by_key or (r.get("job") and not by_key[key].get("job")):
            by_key[key] = r
    gpu_dedup = list(by_key.values())

    # ---- backfill job/user/lab using Slurm's own GPU binding record, for
    # readings the ssh-based PID lookup in run.sh couldn't attribute (misses
    # containerized/namespaced processes - nvidia-smi's process query just
    # doesn't see them, even though the GPU is genuinely busy). scontrol
    # always knows which (node, GPU index) it handed to which job, so this
    # doesn't depend on process visibility at all - see sample_queue.py's
    # gpu_bindings(). Only fills gaps; an existing PID-based attribution is
    # left as-is. ----
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

    all_labs = {r["lab"] for r in gpu_dedup if r.get("lab")} | \
               {r["lab"] for r in queue_rows if r.get("lab")}
    colors, shown = lab_palette(all_labs)

    # ================= headline stats =================
    latest_totals = totals_rows[-1] if totals_rows else {"cpus_total": 0, "gpus_total": 0}
    gpus_total = latest_totals["gpus_total"] or 1
    cpus_total = latest_totals["cpus_total"] or 1

    by_ts_totals = defaultdict(lambda: {"cpus_total": 0, "gpus_total": 0})
    for r in totals_rows:
        by_ts_totals[r["ts"]] = r

    running = [r for r in queue_rows if r["state"] == "RUNNING"]
    gpus_alloc_by_ts = defaultdict(int)
    cpus_alloc_by_ts = defaultdict(int)
    for r in running:
        gpus_alloc_by_ts[r["ts"]] += r["gpus"]
        cpus_alloc_by_ts[r["ts"]] += r["cpus"]

    pct_gpu_alloc_samples = []
    for ts, g in gpus_alloc_by_ts.items():
        tot = by_ts_totals.get(ts, {}).get("gpus_total") or gpus_total
        pct_gpu_alloc_samples.append(100 * g / tot)
    pct_gpu_alloc = stats.mean(pct_gpu_alloc_samples) if pct_gpu_alloc_samples else 0.0

    allocated_gpu_readings = [r for r in gpu_dedup if r.get("job")]
    pct_util_when_alloc = (stats.mean(r["util_gpu"] for r in allocated_gpu_readings)
                            if allocated_gpu_readings else 0.0)

    # ================= per-user / per-lab table =================
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

    # ================= chart 1 & 2: CPU / GPU allocation over time, by lab,
    #                    standardized: same title pattern, same "GPUs"/"CPUs"
    #                    axis convention, same cluster-capacity dashed
    #                    overlay, same usage_chart() code path for both. =================
    # CPU has no idle/utilized split - Slurm doesn't give per-job CPU
    # utilization on this cluster (checked: `sstat` returns no CPU fields for
    # running jobs here), only what's allocated. GPU does, from nvidia-smi.
    alloc_by_ts_lab_gpu = defaultdict(lambda: defaultdict(int))
    alloc_by_ts_lab_cpu = defaultdict(lambda: defaultdict(int))
    for r in running:
        lab = r["lab"] or "unknown"
        alloc_by_ts_lab_gpu[r["ts"]][lab] += r["gpus"]
        alloc_by_ts_lab_cpu[r["ts"]][lab] += r["cpus"]

    ts_sorted_cpu = sorted({r["ts"] for r in running}, key=parse_ts)
    x_cpu = [parse_ts(t) for t in ts_sorted_cpu]
    labs_cpu = {lab for v in alloc_by_ts_lab_cpu.values() for lab in v}
    series_cpu = {lab: ([alloc_by_ts_lab_cpu[t].get(lab, 0) for t in ts_sorted_cpu], None)
                  for lab in labs_cpu}
    cap_cpu = [by_ts_totals.get(t, {}).get("cpus_total") or cpus_total for t in ts_sorted_cpu]
    usage_chart(ASSETS / "cpu_alloc.png", "CPU allocation over time (by lab)",
                "CPUs", x_cpu, series_cpu, colors, shown, overlay_y=cap_cpu)

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

    usage_chart(ASSETS / "gpu_alloc_util.png", "GPU allocation over time (by lab)",
                "GPUs", x_gpu, series_gpu, colors, shown,
                unattrib_y=unattrib_y, unattrib_label="computing, unattributed",
                overlay_y=cap_gpu)

    # ================= bonus: queue wait time trend =================
    # Only jobs sprio actually scores - i.e. eligible to run right now, not
    # blocked on an unmet dependency or array-task throttle. sprio doesn't
    # assign a priority at all to a dependency-blocked job (confirmed against
    # live data: reasons "Dependency"/"DependencyNeverSatisfied"/
    # "JobArrayTaskLimit" never carry a priority value; "Resources"/QOS-limit
    # reasons do) - so "has a priority" is Slurm's own signal of "in the
    # scheduling queue for real," and is a more robust filter than hand-
    # maintaining a reason-string allowlist.
    pending = [r for r in queue_rows if r["state"] == "PENDING"
               and r["wait_seconds"] is not None and r.get("priority") is not None]
    by_ts_wait = defaultdict(list)
    for r in pending:
        by_ts_wait[r["ts"]].append(r["wait_seconds"] / 3600.0)
    if by_ts_wait:
        ts_sorted4 = sorted(by_ts_wait, key=parse_ts)
        x4 = [parse_ts(t) for t in ts_sorted4]
        med = [percentile(sorted(by_ts_wait[t]), 50) for t in ts_sorted4]
        p90 = [percentile(sorted(by_ts_wait[t]), 90) for t in ts_sorted4]
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
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=x4[0].tzinfo))
        fig.autofmt_xdate()
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(ASSETS / "queue_wait.png", dpi=150)
        plt.close(fig)
        have_queue_wait = True
    else:
        have_queue_wait = False

    # ================= bonus: CPU usage vs. GPU usage, decayed with a half-life =================
    # "Usage" here mirrors how Slurm's own fairshare accounting works
    # (PriorityDecayHalfLife=7-00:00:00, confirmed via `scontrol show
    # config`): usage decays continuously with a 7-day half-life rather than
    # resetting or accumulating forever, so recent usage counts far more than
    # usage from a week ago. CPU usage computed this way is essentially what
    # drives today's fairshare priority on this cluster - the thing that
    # actually earns priority. GPU usage computed the identical way is what
    # Slurm *could* weight the same way but doesn't (TRESBillingWeights is
    # unset on partition `main` - see the note below). One point per (user,
    # snapshot), not averaged over days - the point is to see a user's
    # position drift over time, not collapse it to one number. Not colored by
    # lab (this is about individual usage, not lab totals), and drawn
    # translucent so density, not just position, is visible when many points
    # overlap.
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
        fig.savefig(ASSETS / "cpu_gpu_usage.png", dpi=150)
        plt.close(fig)
        have_usage_scatter = True
    else:
        have_usage_scatter = False

    # ================= write README =================
    lines = []
    lines.append("# hopper_monitor")
    lines.append("")
    lines.append("Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, "
                 "updated every 30 minutes by cron. Usernames are anonymized to a "
                 "stable per-account pseudonym; lab names are real.")
    lines.append("")
    lines.append(f"Last updated: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"Samples: {len(distinct_ts)} queue snapshots, "
                 f"{len({r['ts'] for r in gpu_dedup})} GPU snapshots")
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
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- **{pct_gpu_alloc:.1f}%** of the cluster's {gpus_total} GPUs allocated, "
                 f"averaged across all samples")
    lines.append(f"- **{pct_util_when_alloc:.1f}%** average `nvidia-smi` utilization "
                 f"*when* a GPU is allocated to a job")
    lines.append("")
    lines.append("## Per lab / per user")
    lines.append("")
    lines.append("<table>")
    lines.append("<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours allocated</th>"
                 "<th align='right'>CPU-hours allocated</th><th align='right'>GPU utilization</th></tr>")
    for row in table_rows:
        util = f"{row['util_pct']:.0f}%" if row["util_pct"] is not None else "—"
        color = colors.get(row["lab"], OTHER_COLOR)
        bg = lighten(color)
        lines.append(f"<tr style='background-color:{bg}'>"
                     f"<td>{row['lab']}</td><td>{row['user']}</td>"
                     f"<td align='right'>{row['gpu_hours']:.1f}</td>"
                     f"<td align='right'>{row['cpu_hours']:.1f}</td>"
                     f"<td align='right'>{util}</td></tr>")
    lines.append("</table>")
    lines.append("")
    lines.append("(Row background is each lab's chart color, lightened, matching the charts "
                 "above - GitHub strips the inline CSS that carries it (confirmed against the "
                 "live rendered page), so on github.com this table renders plain; the tint "
                 "shows in renderers that keep inline styles, e.g. an editor's local Markdown "
                 "preview.)")
    lines.append("")
    lines.append("## Usage over time")
    lines.append("")
    lines.append("![CPU allocation over time](assets/cpu_alloc.png)")
    lines.append("")
    lines.append("![GPU allocation over time](assets/gpu_alloc_util.png)")
    lines.append("")
    lines.append("Both charts share the same layout: solid color is allocation by lab, "
                 "and the dashed line is total cluster capacity, so any gap above it is "
                 "unallocated headroom. The GPU chart additionally splits each lab's solid "
                 "region into *utilized* (solid) vs *allocated but idle* (same color, "
                 "translucent + hatched) - idle capacity stays attributed to the lab "
                 "holding it rather than one undifferentiated gray band. Solid gray on top "
                 "is real `nvidia-smi` utilization that couldn't be traced to a job or lab. "
                 "The CPU chart has no idle split - this cluster doesn't expose per-job CPU "
                 "utilization (checked: `sstat` returns no CPU-time data for running jobs "
                 "here), only what's allocated, so CPU shows allocation only. Say the word "
                 "if you'd like real CPU-utilization telemetry added - it would need a new "
                 "sampling step, most likely ssh + `/proc/stat` per node, similar to how "
                 "GPU utilization is collected today.")
    lines.append("")
    lines.append("Attribution is cross-referenced two ways: `nvidia-smi`'s own process "
                 "listing (misses containerized/namespaced processes - it just can't see "
                 "those PIDs), backfilled from Slurm's own GPU-to-job binding record "
                 "(`scontrol show job -dd`, which doesn't depend on process visibility at "
                 "all - it's the scheduler's own allocation, not an inference from what a "
                 "node will show over ssh). "
                 + (f"The scontrol fallback attributed **{backfilled}** GPU readings this "
                    "run that the process-listing path missed." if backfilled else
                    "No readings needed the fallback this run - process-listing "
                    "attribution covered everything."))
    lines.append("")
    if have_queue_wait:
        lines.append("## Queue")
        lines.append("")
        lines.append("![Queue wait time](assets/queue_wait.png)")
        lines.append("")
        lines.append("Only jobs Slurm is actively scoring for scheduling (has a `sprio` "
                     "priority) count as \"pending\" here - a job blocked on an unmet "
                     "dependency or an array-task throttle isn't competing for resources "
                     "yet, so its wait time reflects pipeline design, not cluster "
                     "congestion, and would otherwise inflate this chart with something "
                     "unrelated to scheduler load.")
        lines.append("")
    if have_usage_scatter:
        lines.append("## CPU usage vs. GPU usage")
        lines.append("")
        lines.append("![CPU usage vs GPU usage, decayed](assets/cpu_gpu_usage.png)")
        lines.append("")
        lines.append(f"Each point is one user at one snapshot (n={len(decay_points)}), not "
                     "averaged over time - the point is to see how a user's position moves, "
                     "not collapse it to a single number. Both axes are usage decayed with "
                     "Slurm's own ~7-day fairshare half-life (`PriorityDecayHalfLife` on "
                     "this cluster), not a lifetime total or a per-day average, so this is "
                     "close to what Slurm itself is actually tracking at each moment.")
        lines.append("")
        lines.append("**CPU usage (x-axis) is essentially what earns priority here; GPU "
                     "usage (y-axis) is what Slurm could weight the same way but doesn't**, "
                     "confirmed directly from the Slurm config: `PriorityWeightTRES` is "
                     "unset, and partition `main` has no `TRESBillingWeights` configured, "
                     "so fairshare usage accounting bills by CPU count alone - a job "
                     "holding 4 GPUs and 8 CPUs accrues the same usage debt as an 8-CPU, "
                     "no-GPU job. The users worth a second look are in the **upper-left**: "
                     "low decayed CPU usage (so a high, unpenalized fairshare priority) "
                     "paired with high decayed GPU usage.")
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    lines.append("1. **Make GPU usage count toward priority.** It structurally can't "
                 "today - see the confirmation above. Fix by setting `TRESBillingWeights` "
                 "on the `main` partition to give GPUs a nonzero weight (e.g. "
                 "`scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>`) "
                 "and/or giving `PriorityWeightTRES` a GPU component, then restarting "
                 "`slurmctld`. The weight value is a policy call (how many CPUs one GPU "
                 "should be \"worth\") - not something to pick from monitoring data alone.")
    lines.append("")
    lines.append("2. **Act on sustained low utilization, not just report it.** The per "
                 "lab/user table above already shows GPU utilization by user - the CPU vs. "
                 "GPU usage chart above is a more direct way to spot it (upper-left "
                 "quadrant). Two escalating steps on top of that: email a reminder once a "
                 "user's utilization stays low for a sustained stretch, and if it doesn't "
                 "improve after the reminder, taper their priority (QOS demotion or a "
                 "fairshare penalty) rather than leaving it honor-system. Not implemented "
                 "here - needs a policy decision first (threshold, grace period, who gets "
                 "cc'd, and mail delivery from this host) before it's safe to automate.")
    lines.append("")

    (DIR / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
