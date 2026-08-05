#!/usr/bin/env python3
"""
Reads data/gpu_samples.jsonl (nvidia-smi, via ssh to GPU nodes) and
data/queue_samples.jsonl (squeue + sprio, login node only) and writes
assets/*.png + README.md. Runs on a compute node via `sbatch --wait` from
run.sh - never on the login node (no numpy/matplotlib there).

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

DIR = Path(__file__).resolve().parent
ASSETS = DIR / "assets"
ASSETS.mkdir(exist_ok=True)

IDLE_THRESHOLD = 10.0  # util_gpu <= this counts as idle

# Categorical palette (fixed order, validated for CVD/contrast on the stacked-
# area "adjacent" pairlist - see the dataviz skill). Extra labs beyond 8 fold
# into "Other" (muted gray) rather than generating a 9th hue.
LAB_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#898781"
# "Allocated but idle" band: a hatched, tone-on-tone gray (not a categorical
# hue) so it can never be mistaken for a lab, including the "Other" bucket -
# distinguished by texture as well as tone.
IDLE_FILL = "#c3c2b7"
IDLE_LINE = "#898781"
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


def lab_palette(labs):
    """Fixed-order hue assignment; labs beyond 8 fold into 'Other'."""
    ranked = sorted(labs)
    colors = {}
    shown = ranked[:8]
    for lab, color in zip(shown, LAB_COLORS):
        colors[lab] = color
    for lab in ranked[8:]:
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


def stacked_area(path, title, ylabel, x_by_lab, y_by_lab, colors, shown,
                  overlay_x=None, overlay_y=None, overlay_label=None,
                  extra_layer=None):
    """extra_layer, if given: (label, y_values, facecolor, edgecolor, hatch) -
    one more series stacked on top of the per-lab ones, styled off the
    categorical palette (e.g. a textured gray "idle" band) so it reads as a
    different kind of thing, not another lab."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    labs = sorted(y_by_lab, key=lambda l: -sum(y_by_lab[l]))
    single_point = len(x_by_lab) < 2
    if labs or extra_layer:
        if single_point:
            # stackplot needs >=2 x points to draw a visible fill (zero width
            # otherwise) - render the one sample as a stacked bar instead.
            bottom = 0
            for l in labs:
                v = y_by_lab[l][0]
                ax.bar(x_by_lab[0], v, bottom=bottom, width=0.01,
                       color=colors[l], label=bucket_label(l, shown))
                bottom += v
            if extra_layer:
                label, y_vals, fc, ec, hatch = extra_layer
                ax.bar(x_by_lab[0], y_vals[0], bottom=bottom, width=0.01,
                       color=fc, edgecolor=ec, hatch=hatch, label=label)
        else:
            all_y = [y_by_lab[l] for l in labs]
            all_labels = [bucket_label(l, shown) for l in labs]
            all_colors = [colors[l] for l in labs]
            if extra_layer:
                label, y_vals, fc, ec, hatch = extra_layer
                all_y.append(y_vals)
                all_labels.append(label)
                all_colors.append(fc)
            # thin surface-colored edge between stacked segments reads as a
            # gap rather than a hard seam
            polys = ax.stackplot(x_by_lab, *all_y, labels=all_labels,
                                  colors=all_colors, edgecolor=SURFACE,
                                  linewidth=1)
            if extra_layer:
                polys[-1].set_edgecolor(ec)
                polys[-1].set_hatch(hatch)
                polys[-1].set_linewidth(0.6)
    if overlay_x is not None and overlay_y:
        if len(overlay_x) < 2:
            ax.scatter(overlay_x, overlay_y, color=INK_MUTED, marker="_", s=300,
                        linewidth=1.5, label=overlay_label)
        else:
            ax.plot(overlay_x, overlay_y, color=INK_MUTED, linewidth=1.5,
                     linestyle="--", label=overlay_label)
    # explicit x-limits - matplotlib's date autoscale degenerates to a huge
    # bogus range (e.g. year 1 CE) when there are fewer than 2 x points.
    all_x = list(x_by_lab) + (list(overlay_x) if overlay_x else [])
    if all_x:
        lo, hi = min(all_x), max(all_x)
        pad = timedelta(minutes=30) if lo == hi else (hi - lo) * 0.05
        ax.set_xlim(lo - pad, hi + pad)
    ax.set_title(title, color=INK, fontsize=12, loc="left")
    ax.set_ylabel(ylabel)
    tz = all_x[0].tzinfo if all_x else None
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=tz))
    fig.autofmt_xdate()
    if labs or overlay_x is not None:
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False,
                   fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    gpu_rows = load_jsonl(DIR / "data" / "gpu_samples.jsonl")
    queue_rows_all = load_jsonl(DIR / "data" / "queue_samples.jsonl")
    queue_rows = [r for r in queue_rows_all if r.get("kind") != "totals"]
    totals_rows = [r for r in queue_rows_all if r.get("kind") == "totals"]

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
    user_lab = {}
    for r in running:
        key = (r["user"] or "unknown", r["lab"] or "unknown")
        h = intervals.get(parse_ts(r["ts"]), 0.5)
        gpu_hours[key] += r["gpus"] * h
        cpu_hours[key] += r["cpus"] * h
        user_lab[key] = key

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

    # ================= chart 1 & 2: CPU / GPU allocated over time, stacked by lab =================
    def alloc_series(field, totals_key, fallback_total):
        by_ts_lab = defaultdict(lambda: defaultdict(int))
        for r in running:
            by_ts_lab[r["ts"]][r["lab"] or "unknown"] += r[field]
        ts_sorted = sorted(by_ts_lab, key=parse_ts)
        x = [parse_ts(t) for t in ts_sorted]
        y_by_lab = defaultdict(list)
        labs_here = {lab for v in by_ts_lab.values() for lab in v}
        for t in ts_sorted:
            for lab in labs_here:
                y_by_lab[lab].append(by_ts_lab[t].get(lab, 0))
        total_y = [by_ts_totals.get(t, {}).get(totals_key) or fallback_total
                   for t in ts_sorted]
        return x, y_by_lab, total_y

    x_cpu, y_cpu, total_cpu = alloc_series("cpus", "cpus_total", cpus_total)
    stacked_area(ASSETS / "cpu_alloc.png", "CPUs allocated over time (by lab)",
                 "CPUs allocated", x_cpu, y_cpu, colors, shown,
                 x_cpu, total_cpu, "cluster capacity")

    # ================= chart 2: GPU allocation vs. utilization, stacked by lab,
    #                    with a textured gray band for allocated-but-idle =================
    # One chart, not two: the colored stack is who's actually computing (by
    # lab, from nvidia-smi util - Σ util% x allocated GPUs), the hatched gray
    # band on top is the rest of what's allocated (from squeue) but doing
    # nothing, and the dashed line is total cluster capacity - headroom above
    # it is unallocated.
    by_ts_lab_util = defaultdict(lambda: defaultdict(float))
    for r in gpu_dedup:
        if r.get("job") and r.get("lab"):
            by_ts_lab_util[r["ts"]][r["lab"]] += r["util_gpu"] / 100.0
    ts_sorted2 = sorted(by_ts_lab_util, key=parse_ts)
    x2 = [parse_ts(t) for t in ts_sorted2]
    labs2 = {lab for v in by_ts_lab_util.values() for lab in v}
    y2 = defaultdict(list)
    for t in ts_sorted2:
        for lab in labs2:
            y2[lab].append(by_ts_lab_util[t].get(lab, 0.0))
    computing_total = {t: sum(by_ts_lab_util[t].values()) for t in ts_sorted2}
    idle_y = [max(0.0, gpus_alloc_by_ts.get(t, 0) - computing_total[t]) for t in ts_sorted2]
    cap_y = [by_ts_totals.get(t, {}).get("gpus_total") or gpus_total for t in ts_sorted2]

    stacked_area(ASSETS / "gpu_alloc_util.png",
                 "GPU allocation vs. utilization over time (by lab)",
                 "GPUs", x2, y2, colors, shown, x2, cap_y, "cluster capacity",
                 extra_layer=("allocated, idle", idle_y, IDLE_FILL, IDLE_LINE, "///"))

    # ================= bonus: queue wait time trend =================
    pending = [r for r in queue_rows if r["state"] == "PENDING" and r["wait_seconds"] is not None]
    by_ts_wait = defaultdict(list)
    for r in pending:
        by_ts_wait[r["ts"]].append(r["wait_seconds"] / 3600.0)
    if by_ts_wait:
        ts_sorted4 = sorted(by_ts_wait, key=parse_ts)
        x4 = [parse_ts(t) for t in ts_sorted4]
        med = [stats.median(by_ts_wait[t]) for t in ts_sorted4]
        p90 = [sorted(by_ts_wait[t])[int(0.9 * (len(by_ts_wait[t]) - 1))] for t in ts_sorted4]
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(x4, med, color=LAB_COLORS[0], linewidth=2, marker="o", markersize=4,
                 label="median wait")
        ax.plot(x4, p90, color=LAB_COLORS[1], linewidth=1.5, linestyle="--",
                 marker="o", markersize=4, label="p90 wait")
        lo, hi = min(x4), max(x4)
        pad = timedelta(minutes=30) if lo == hi else (hi - lo) * 0.05
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_title("Queue wait time (currently-pending jobs)", loc="left")
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

    # ================= bonus: priority vs GPU/CPU usage scatter =================
    # One point per (user, day) who actually ran something that day - not a lifetime
    # cumulative total, which would keep growing forever and drift out of sync with
    # Slurm's own fairshare usage (which decays with a 7-day half-life, not a hard
    # reset - see PriorityDecayHalfLife in `scontrol show config`).
    def day_of(ts_str):
        return parse_ts(ts_str).date()

    gpu_hours_by_user_day = defaultdict(float)
    cpu_hours_by_user_day = defaultdict(float)
    for r in running:
        key = (r["user"] or "unknown", day_of(r["ts"]))
        h = intervals.get(parse_ts(r["ts"]), 0.5)
        gpu_hours_by_user_day[key] += r["gpus"] * h
        cpu_hours_by_user_day[key] += r["cpus"] * h

    prio_by_user_day = defaultdict(list)
    for r in queue_rows:
        if r.get("priority") is not None and r.get("user"):
            prio_by_user_day[(r["user"], day_of(r["ts"]))].append(r["priority"])

    usage_days = set(gpu_hours_by_user_day) | set(cpu_hours_by_user_day)
    scatter_rows = []
    for key in usage_days:
        gh_val = gpu_hours_by_user_day.get(key, 0.0)
        ch_val = cpu_hours_by_user_day.get(key, 0.0)
        if gh_val <= 0 and ch_val <= 0:
            continue
        prios = prio_by_user_day.get(key)
        if prios:
            scatter_rows.append((gh_val, ch_val, stats.mean(prios)))
    if scatter_rows:
        gh = [s[0] for s in scatter_rows]
        ch = [s[1] for s in scatter_rows]
        pr = [s[2] for s in scatter_rows]
        fig, axes = plt.subplots(1, 2, figsize=(9, 4))
        axes[0].scatter(gh, pr, color=LAB_COLORS[0], s=40, edgecolor=SURFACE, linewidth=0.5)
        axes[0].set_xlabel("GPU-hours allocated"); axes[0].set_ylabel("mean priority")
        axes[0].set_title("Priority vs. GPU usage", loc="left", fontsize=11)
        axes[1].scatter(ch, pr, color=LAB_COLORS[1], s=40, edgecolor=SURFACE, linewidth=0.5)
        axes[1].set_xlabel("CPU-hours allocated"); axes[1].set_ylabel("mean priority")
        axes[1].set_title("Priority vs. CPU usage", loc="left", fontsize=11)
        fig.tight_layout()
        fig.savefig(ASSETS / "priority_scatter.png", dpi=150)
        plt.close(fig)
        have_scatter = True
    else:
        have_scatter = False

    # ================= bonus: allocated-but-idle leaderboard =================
    idle_hours = defaultdict(float)
    for r in gpu_dedup:
        if r.get("job") and r.get("user") and r["util_gpu"] <= IDLE_THRESHOLD:
            h = intervals.get(parse_ts(r["ts"]), 0.5)
            idle_hours[(r["user"], r.get("lab") or "unknown")] += h
    idle_leaderboard = sorted(idle_hours.items(), key=lambda kv: -kv[1])[:10]

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
    lines.append("| Lab | User | GPU-hours allocated | CPU-hours allocated | GPU utilization |")
    lines.append("|---|---|---:|---:|---:|")
    for row in table_rows:
        util = f"{row['util_pct']:.0f}%" if row["util_pct"] is not None else "—"
        lines.append(f"| {row['lab']} | {row['user']} | {row['gpu_hours']:.1f} | "
                     f"{row['cpu_hours']:.1f} | {util} |")
    lines.append("")
    lines.append("## Usage over time")
    lines.append("")
    lines.append("![CPUs allocated over time](assets/cpu_alloc.png)")
    lines.append("")
    lines.append("![GPU allocation vs utilization over time](assets/gpu_alloc_util.png)")
    lines.append("")
    lines.append("The GPU chart layers three things at once: solid color is GPU-hardware "
                 "utilization by lab (Σ util% across that lab's allocated GPUs), the "
                 "hatched gray band on top is allocated-but-idle - GPUs a job is holding "
                 "but not using - and the dashed line is total cluster GPU capacity, so "
                 "any gap above the dashed line is unallocated headroom.")
    lines.append("")
    if have_queue_wait:
        lines.append("## Queue")
        lines.append("")
        lines.append("![Queue wait time](assets/queue_wait.png)")
        lines.append("")
    if have_scatter:
        lines.append("## Priority vs. usage")
        lines.append("")
        lines.append("![Priority vs GPU/CPU usage](assets/priority_scatter.png)")
        lines.append("")
        lines.append(f"Each point is one user on one day (n={len(scatter_rows)}): that "
                     "day's allocated GPU/CPU-hours against their mean Slurm priority "
                     "that same day, for everyone who ran something that day. Not a "
                     "lifetime total per user - that would only grow and would mix "
                     "together usage from weeks ago with today's priority.")
        lines.append("")
        lines.append("**GPU usage does not currently affect priority, confirmed directly "
                     "from the Slurm config**, not just inferred from the chart shape: "
                     "`PriorityWeightTRES` is unset (a job's own GPU/CPU mix carries no "
                     "weight), and partition `main` has no `TRESBillingWeights` configured, "
                     "so fairshare usage accounting bills by CPU count alone - a job holding "
                     "4 GPUs and 8 CPUs accrues the same usage debt as an 8-CPU, no-GPU job. "
                     "If the two panels above look similarly shaped, that's this setting in "
                     "action, not a coincidence.")
        lines.append("")
    if idle_leaderboard:
        lines.append("## Allocated but idle (top 10)")
        lines.append("")
        lines.append(f"Users holding a GPU allocation with `nvidia-smi` utilization "
                     f"≤{IDLE_THRESHOLD:.0f}% the longest, cumulatively:")
        lines.append("")
        lines.append("| User | Lab | Idle GPU-hours |")
        lines.append("|---|---|---:|")
        for (user, lab), h in idle_leaderboard:
            lines.append(f"| {user} | {lab} | {h:.1f} |")
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
    lines.append("2. **Act on sustained low utilization, not just report it.** The idle "
                 "leaderboard above already identifies who's holding GPUs allocated-but-idle "
                 "the longest. Two escalating steps on top of it: email a reminder once a "
                 "user crosses an idle-hours threshold, and if utilization stays low after "
                 "the reminder, taper their priority (QOS demotion or a fairshare penalty) "
                 "rather than leaving it honor-system. Not implemented here - needs a policy "
                 "decision first (threshold, grace period, who gets cc'd, and mail delivery "
                 "from this host) before it's safe to automate.")
    lines.append("")

    (DIR / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
