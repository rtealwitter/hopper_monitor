# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-08-08T12:30:11-07:00
Samples: 141 queue snapshots, 141 GPU snapshots

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **44.6%** of the cluster's 60 GPUs allocated, averaged across all samples
- **46.8%** average `nvidia-smi` utilization *when* a GPU is allocated to a job
- **88.3%** average cgroup CPU utilization *when* a CPU is allocated to a job

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours allocated</th><th align='right'>CPU-hours allocated</th><th align='right'>GPU utilization</th></tr>
<tr style='background-color:#d8ecd8'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>864.5</td><td align='right'>864.5</td><td align='right'>44%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>493.5</td><td align='right'>1019.0</td><td align='right'>68%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-d58f5a15</td><td align='right'>467.5</td><td align='right'>3740.0</td><td align='right'>9%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-6bb5f332</td><td align='right'>40.0</td><td align='right'>200.0</td><td align='right'>71%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>22.5</td><td align='right'>54.0</td><td align='right'>67%</td></tr>
<tr style='background-color:#fbebf1'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>0.0</td><td align='right'>16.0</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>426.5</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>3982.5</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>744.0</td><td align='right'>—</td></tr>
<tr style='background-color:#dfeaf8'><td>enkavi-lab</td><td>user-c21bdaa4</td><td align='right'>0.0</td><td align='right'>179.0</td><td align='right'>—</td></tr>
<tr style='background-color:#fcf0d8'><td>ibarragarciapadilla-lab</td><td>user-dad71a72</td><td align='right'>0.0</td><td align='right'>6.0</td><td align='right'>—</td></tr>
</table>

## Usage over time

![CPU allocation over time](assets/cpu_alloc.png)

![GPU allocation over time](assets/gpu_alloc_util.png)

Solid = utilized by lab, hatched = allocated but idle, gray = usage not traceable to a lab, dashed line = cluster capacity.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **2706** readings the former missed.

## Queue

![Queue wait time](assets/queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](assets/cpu_gpu_usage.png)

One point per user per snapshot (n=678), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

## Recommendations

1. **Weight GPU usage in fairshare.** `TRESBillingWeights` and `PriorityWeightTRES` are both unset right now, so Slurm's fairshare score only sees CPU-seconds - a job holding 4 idle L40S GPUs costs nothing in priority as long as it isn't also holding CPUs. That's the exact failure mode the scatter above is built to catch (upper-left: low CPU usage, high GPU usage). Fix: `scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>` (or set `PriorityWeightTRES` cluster-wide), then `scontrol reconfigure` - a full `slurmctld` restart also works but drops in-flight priority state. A reasonable starting point for `<weight>` is the CPUs-per-GPU ratio on a GPU node (128 CPUs / 4 GPUs = 32), so one GPU costs as much fairshare as the CPU share it displaces; tune from there against next week's headline numbers (44.6% allocated, 46.8% utilized when allocated, as of this snapshot). The weight value itself is a policy call - loop in whoever owns cluster allocation policy before changing it.

2. **Escalate on sustained low utilization** (see table and scatter above). Right now the clearest candidate is `user-d58f5a15` in `witter-lab`: 467.5 GPU-hours allocated at 9% average utilization, i.e. roughly 424 GPU-hours that sat idle instead of going to someone in the queue. Turning that into an automated escalation needs two decisions made up front: a utilization threshold (something like under 20% mean utilization over at least 50 allocated GPU-hours is a defensible starting bar - loose enough to skip short debugging runs, tight enough to catch parked allocations) and a grace period (how many consecutive low-utilization snapshots before it counts as "sustained" rather than a momentary lull between batches). Once those are set, the mechanism can be either soft (a bot that reads `data/gpu_samples.jsonl` and reminds the user/lab by email or Slack) or hard (a Slurm-side QOS penalty, e.g. `sacctmgr modify qos <qos> set Priority-=<n>`, applied after N consecutive offending snapshots). Neither exists yet - today the table and scatter above are a read-only signal, not an enforced policy.

