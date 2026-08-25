# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-08-24T22:00:09-07:00
Samples: 907 queue snapshots total (313 in the last 7 days), 854 GPU snapshots total (266 in the last 7 days)

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **22.4%** (last 7 days) vs **39.4%** (all time) of the cluster's 60 GPUs allocated, averaged across samples
- **38.9%** (last 7 days) vs **49.2%** (all time) average `nvidia-smi` utilization *when* a GPU is allocated to a job
- **69.0%** (last 7 days) vs **78.4%** (all time) average cgroup CPU utilization *when* a CPU is allocated to a job

## Most open times

Based on 20 days of history so far, `hopper.cluster` has historically been most open on **Saturdays** (26.9% of GPUs allocated on average) and around **08:00-09:00** (33.6% of GPUs allocated on average). Recomputed from all-time data on every cron tick, so it sharpens as more history accumulates.

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours (last 7d)</th><th align='right'>GPU-hours (all time)</th><th align='right'>GPU util (last 7d)</th><th align='right'>GPU util (all time)</th></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>1621.0</td><td align='right'>6351.5</td><td align='right'>46%</td><td align='right'>63%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-d58f5a15</td><td align='right'>344.0</td><td align='right'>1023.5</td><td align='right'>5%</td><td align='right'>7%</td></tr>
<tr style='background-color:#e3e1f1'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>162.5</td><td align='right'>3205.0</td><td align='right'>19%</td><td align='right'>31%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>22.5</td><td align='right'>67.5</td><td align='right'>45%</td><td align='right'>58%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-f5bf0d80</td><td align='right'>17.5</td><td align='right'>32.5</td><td align='right'>40%</td><td align='right'>45%</td></tr>
<tr style='background-color:#fce8e0'><td>gillen-lab</td><td>user-d21e03f5</td><td align='right'>3.5</td><td align='right'>5.0</td><td align='right'>82%</td><td align='right'>72%</td></tr>
<tr style='background-color:#e3e1f1'><td>zhuang-lab</td><td>user-7d156b54</td><td align='right'>1.5</td><td align='right'>1.5</td><td align='right'>45%</td><td align='right'>45%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-6bb5f332</td><td align='right'>0.0</td><td align='right'>40.0</td><td align='right'>—</td><td align='right'>71%</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#dfeaf8'><td>enkavi-lab</td><td>user-c21bdaa4</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-dad71a72</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>ritz-lab</td><td>user-37f252dd</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
</table>

## Usage over time

Charts below cover the trailing 7 days: **2026-08-17 22:00 to 2026-08-24 22:00** (PDT).

![CPU allocation over time](assets/cpu_alloc.png)

![GPU allocation over time](assets/gpu_alloc_util.png)

Solid = utilized by lab, hatched = allocated but idle, gray = usage not traceable to a lab, dashed line = cluster capacity.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **2188** readings the former missed.

## Queue

![Queue wait time](assets/queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](assets/cpu_gpu_usage.png)

One point per user per snapshot (n=819), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

## Weekly archives

Dated snapshots of this dashboard, one per fully-elapsed calendar week:

- [2026-08-17_2026-08-23](archive/2026-08-17_2026-08-23/README.md)
- [2026-08-10_2026-08-16](archive/2026-08-10_2026-08-16/README.md)
- [2026-08-03_2026-08-09](archive/2026-08-03_2026-08-09/README.md)

## Recommendations

1. **Weight GPU usage in fairshare.** `TRESBillingWeights`/`PriorityWeightTRES` are unset, so idle GPUs cost nothing in priority - the failure mode the scatter above flags (upper-left: low CPU usage, high GPU usage). Fix: `scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>` then `scontrol reconfigure`. Start `<weight>` near the CPUs-per-GPU ratio (128/4=32) and tune against this week's numbers (22.4% allocated, 38.9% utilized when allocated) - a policy call, so loop in whoever owns cluster allocation.
2. **Escalate on sustained low utilization** (see table and scatter above). Current top candidate (most idle GPU-hours over the last 7d): `user-554c620c` in `witter-lab` - 875 idle of 1621.0 GPU-hours allocated (46% utilization). Needs a utilization threshold (e.g. <20% mean over 50+ GPU-hours) and a grace period, then either a soft nudge (Slack/email) or a hard QOS penalty (`sacctmgr modify qos ... set Priority-=<n>`). Neither exists yet - this is read-only signal, not enforced policy.

