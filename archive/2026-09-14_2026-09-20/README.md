# hopper_monitor

Archived weekly snapshot: **2026-09-14 to 2026-09-20**. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

[Back to the live dashboard](../../README.md)

Samples: 336 queue snapshots, 293 GPU snapshots

## Headline

- **33.0%** of the cluster's 60 GPUs allocated, averaged across all samples
- **26.0%** average `nvidia-smi` utilization *when* a GPU is allocated to a job
- **96.2%** average cgroup CPU utilization *when* a CPU is allocated to a job

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours allocated</th><th align='right'>GPU utilization</th></tr>
<tr style='background-color:#fbebf1'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>2267.0</td><td align='right'>21%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>571.0</td><td align='right'>39%</td></tr>
<tr style='background-color:#fcf0d8'><td>nerenberg-lab</td><td>user-7eb22d7c</td><td align='right'>388.5</td><td align='right'>42%</td></tr>
<tr style='background-color:#fcf0d8'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>82.5</td><td align='right'>68%</td></tr>
<tr style='background-color:#fbebf1'><td>zhuang-lab</td><td>user-7d156b54</td><td align='right'>15.5</td><td align='right'>48%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-d58f5a15</td><td align='right'>4.5</td><td align='right'>23%</td></tr>
<tr style='background-color:#fcf0d8'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>1.0</td><td align='right'>45%</td></tr>
<tr style='background-color:#fbebf1'><td>zhuang-lab</td><td>user-e67a8f7c</td><td align='right'>1.0</td><td align='right'>49%</td></tr>
<tr style='background-color:#fce8e0'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>ibarragarciapadilla-lab</td><td>user-40b4d372</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#dfeaf8'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#fce8e0'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>—</td></tr>
</table>

## Usage over time

Charts below cover this week: **2026-09-14 00:00 to 2026-09-21 00:00** (UTC-07:00).

![CPU allocation over time](cpu_alloc.png)

![GPU allocation over time](gpu_alloc_util.png)

Solid = utilized by lab, hatched = allocated but idle, gray = usage not traceable to a lab, dashed line = cluster capacity.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **686** readings the former missed.

## Queue

![Queue wait time](queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](cpu_gpu_usage.png)

One point per user per snapshot (n=1493), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

