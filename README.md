# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-08-14T20:00:15-07:00
Samples: 444 queue snapshots total (336 in the last 7 days), 444 GPU snapshots total (336 in the last 7 days)

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **55.0%** (last 7 days) vs **53.8%** (all time) of the cluster's 60 GPUs allocated, averaged across samples
- **55.2%** (last 7 days) vs **53.1%** (all time) average `nvidia-smi` utilization *when* a GPU is allocated to a job
- **79.3%** (last 7 days) vs **81.3%** (all time) average cgroup CPU utilization *when* a CPU is allocated to a job

## Most open times

Based on 10 days of history so far, `hopper.cluster` has historically been most open on **Saturdays** (29.6% of GPUs allocated on average) and around **01:00-02:00** (45.9% of GPUs allocated on average). Recomputed from all-time data on every cron tick, so it sharpens as more history accumulates.

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours (last 7d)</th><th align='right'>GPU-hours (all time)</th><th align='right'>GPU util (last 7d)</th><th align='right'>GPU util (all time)</th></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>3456.5</td><td align='right'>3841.0</td><td align='right'>71%</td><td align='right'>70%</td></tr>
<tr style='background-color:#e3e1f1'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>2024.5</td><td align='right'>2746.5</td><td align='right'>27%</td><td align='right'>33%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>35.0</td><td align='right'>45.0</td><td align='right'>70%</td><td align='right'>66%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-d58f5a15</td><td align='right'>16.0</td><td align='right'>483.5</td><td align='right'>10%</td><td align='right'>9%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-f5bf0d80</td><td align='right'>15.0</td><td align='right'>15.0</td><td align='right'>50%</td><td align='right'>50%</td></tr>
<tr style='background-color:#fce8e0'><td>gillen-lab</td><td>user-d21e03f5</td><td align='right'>1.0</td><td align='right'>1.0</td><td align='right'>47%</td><td align='right'>47%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-6bb5f332</td><td align='right'>0.0</td><td align='right'>40.0</td><td align='right'>—</td><td align='right'>71%</td></tr>
<tr style='background-color:#dfeaf8'><td>enkavi-lab</td><td>user-c21bdaa4</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-dad71a72</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>ritz-lab</td><td>user-37f252dd</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
</table>

## Usage over time

Charts below cover the trailing 7 days: **2026-08-07 20:00 to 2026-08-14 20:00** (PDT).

![CPU allocation over time](assets/cpu_alloc.png)

![GPU allocation over time](assets/gpu_alloc_util.png)

Solid = utilized by lab, hatched = allocated but idle, gray = usage not traceable to a lab, dashed line = cluster capacity.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **7162** readings the former missed.

## Queue

![Queue wait time](assets/queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](assets/cpu_gpu_usage.png)

One point per user per snapshot (n=1531), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

## Weekly archives

Dated snapshots of this dashboard, one per fully-elapsed calendar week:

- [2026-08-03_2026-08-09](archive/2026-08-03_2026-08-09/README.md)

## Recommendations

1. **Weight GPU usage in fairshare.** `TRESBillingWeights` and `PriorityWeightTRES` are both unset right now, so Slurm's fairshare score only sees CPU-seconds - a job holding 4 idle L40S GPUs costs nothing in priority as long as it isn't also holding CPUs. That's the exact failure mode the scatter above is built to catch (upper-left: low CPU usage, high GPU usage). Fix: `scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>` (or set `PriorityWeightTRES` cluster-wide), then `scontrol reconfigure` - a full `slurmctld` restart also works but drops in-flight priority state. A reasonable starting point for `<weight>` is the CPUs-per-GPU ratio on a GPU node (128 CPUs / 4 GPUs = 32), so one GPU costs as much fairshare as the CPU share it displaces; tune from there against this week's headline numbers (55.0% allocated, 55.2% utilized when allocated, over the last 7 days). The weight value itself is a policy call - loop in whoever owns cluster allocation policy before changing it.

2. **Escalate on sustained low utilization** (see table and scatter above). Right now the clearest candidate is `user-0db9ced0` in `zhuang-lab`: 2024.5 GPU-hours allocated at 27% average utilization, i.e. roughly 1477 GPU-hours that sat idle instead of going to someone in the queue. Turning that into an automated escalation needs two decisions made up front: a utilization threshold (something like under 20% mean utilization over at least 50 allocated GPU-hours is a defensible starting bar - loose enough to skip short debugging runs, tight enough to catch parked allocations) and a grace period (how many consecutive low-utilization snapshots before it counts as "sustained" rather than a momentary lull between batches). Once those are set, the mechanism can be either soft (a bot that reads `data/gpu_samples.jsonl` and reminds the user/lab by email or Slack) or hard (a Slurm-side QOS penalty, e.g. `sacctmgr modify qos <qos> set Priority-=<n>`, applied after N consecutive offending snapshots). Neither exists yet - today the table and scatter above are a read-only signal, not an enforced policy.

