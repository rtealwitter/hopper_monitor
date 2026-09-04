# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-09-04T05:00:07-07:00
Samples: 1397 queue snapshots total (336 in the last 7 days), 1255 GPU snapshots total (268 in the last 7 days)

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **30.7%** (last 7 days) vs **37.9%** (all time) of the cluster's 60 GPUs allocated, averaged across samples
- **64.9%** (last 7 days) vs **54.0%** (all time) average `nvidia-smi` utilization *when* a GPU is allocated to a job
- **71.4%** (last 7 days) vs **74.0%** (all time) average cgroup CPU utilization *when* a CPU is allocated to a job

## Most open times

Based on 31 days of history so far, `hopper.cluster` has historically been most open on **Saturdays** (25.8% of GPUs allocated on average) and around **08:00-09:00** (31.0% of GPUs allocated on average). Recomputed from all-time data on every cron tick, so it sharpens as more history accumulates.

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours (last 7d)</th><th align='right'>GPU-hours (all time)</th><th align='right'>GPU util (last 7d)</th><th align='right'>GPU util (all time)</th></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>3064.0</td><td align='right'>11481.0</td><td align='right'>65%</td><td align='right'>64%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-f5bf0d80</td><td align='right'>19.5</td><td align='right'>52.0</td><td align='right'>18%</td><td align='right'>34%</td></tr>
<tr style='background-color:#ededec'><td>zhuang-lab</td><td>user-7d156b54</td><td align='right'>8.0</td><td align='right'>10.5</td><td align='right'>44%</td><td align='right'>44%</td></tr>
<tr style='background-color:#ededec'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>0.0</td><td align='right'>3205.0</td><td align='right'>—</td><td align='right'>31%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-d58f5a15</td><td align='right'>0.0</td><td align='right'>1023.5</td><td align='right'>—</td><td align='right'>7%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>0.0</td><td align='right'>67.5</td><td align='right'>—</td><td align='right'>58%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-6bb5f332</td><td align='right'>0.0</td><td align='right'>40.0</td><td align='right'>—</td><td align='right'>71%</td></tr>
<tr style='background-color:#fcf0d8'><td>gillen-lab</td><td>user-d21e03f5</td><td align='right'>0.0</td><td align='right'>5.0</td><td align='right'>—</td><td align='right'>72%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-87cc74d1</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>ibarragarciapadilla-lab</td><td>user-dad71a72</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>kao-lab</td><td>user-964f71b2</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#dfeaf8'><td>batta-lab</td><td>user-58bad794</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fae3e3'><td>ritz-lab</td><td>user-37f252dd</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>ibarragarciapadilla-lab</td><td>user-40b4d372</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>enkavi-lab</td><td>user-c21bdaa4</td><td align='right'>0.0</td><td align='right'>0.0</td><td align='right'>—</td><td align='right'>—</td></tr>
</table>

## Usage over time

Charts below cover the trailing 7 days: **2026-08-28 05:00 to 2026-09-04 05:00** (PDT).

![CPU allocation over time](assets/cpu_alloc.png)

![GPU allocation over time](assets/gpu_alloc_util.png)

Solid = utilized by lab, hatched = allocated but idle, gray = usage not traceable to a lab, dashed line = cluster capacity.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **739** readings the former missed.

## Queue

![Queue wait time](assets/queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](assets/cpu_gpu_usage.png)

One point per user per snapshot (n=987), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

## Weekly archives

Dated snapshots of this dashboard, one per fully-elapsed calendar week:

- [2026-08-24_2026-08-30](archive/2026-08-24_2026-08-30/README.md)
- [2026-08-17_2026-08-23](archive/2026-08-17_2026-08-23/README.md)
- [2026-08-10_2026-08-16](archive/2026-08-10_2026-08-16/README.md)
- [2026-08-03_2026-08-09](archive/2026-08-03_2026-08-09/README.md)

## Recommendations

1. **Weight GPU usage in fairshare.** `TRESBillingWeights`/`PriorityWeightTRES` are unset, so idle GPUs cost nothing in priority - the failure mode the scatter above flags (upper-left: low CPU usage, high GPU usage). Fix: `scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>` then `scontrol reconfigure`. Start `<weight>` near the CPUs-per-GPU ratio (128/4=32) and tune against this week's numbers (30.7% allocated, 64.9% utilized when allocated) - a policy call, so loop in whoever owns cluster allocation.
2. **Escalate on sustained low utilization** (see table and scatter above). Current top candidate (most idle GPU-hours over the last 7d): `user-554c620c` in `witter-lab` - 1059 idle of 3064.0 GPU-hours allocated (65% utilization). Needs a utilization threshold (e.g. <20% mean over 50+ GPU-hours) and a grace period, then either a soft nudge (Slack/email) or a hard QOS penalty (`sacctmgr modify qos ... set Priority-=<n>`). Neither exists yet - this is read-only signal, not enforced policy.

