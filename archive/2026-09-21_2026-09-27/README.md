# hopper_monitor

Archived weekly snapshot: **2026-09-21 to 2026-09-27**. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

[Back to the live dashboard](../../README.md)

Samples: 333 queue snapshots, 333 GPU snapshots

## Headline

- **73.1%** of the cluster's 60 GPUs allocated, averaged across all samples
- **20.4%** average observed `nvidia-smi` utilization *when* a GPU is allocated to a job
- **82.2%** average cgroup CPU utilization *when* a CPU is allocated to a job

## Per lab / per user

<table>
<tr><th>Lab</th><th>User</th><th align='right'>GPU-hours allocated</th><th align='right'>GPU utilization</th></tr>
<tr style='background-color:#deebf4'><td>zhuang-lab</td><td>user-0db9ced0</td><td align='right'>3593.6</td><td align='right'>23%</td></tr>
<tr style='background-color:#d8efef'><td>witter-lab</td><td>user-554c620c</td><td align='right'>2627.4</td><td align='right'>15%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-7eb22d7c</td><td align='right'>992.4</td><td align='right'>0%</td></tr>
<tr style='background-color:#deebf4'><td>zhuang-lab</td><td>user-e67a8f7c</td><td align='right'>62.5</td><td align='right'>53%</td></tr>
<tr style='background-color:#deebf4'><td>zhuang-lab</td><td>user-7d156b54</td><td align='right'>9.5</td><td align='right'>17%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-b12dc074</td><td align='right'>3.0</td><td align='right'>55%</td></tr>
<tr style='background-color:#e3e1f1'><td>nerenberg-lab</td><td>user-fedb5feb</td><td align='right'>2.0</td><td align='right'>16%</td></tr>
<tr style='background-color:#fce8e0'><td>enkavi-lab</td><td>user-c21bdaa4</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#fbebf1'><td>gillen-lab</td><td>user-b89a87ef</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>ibarragarciapadilla-lab</td><td>user-3cfc41a3</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>ibarragarciapadilla-lab</td><td>user-40b4d372</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#d8ecd8'><td>ibarragarciapadilla-lab</td><td>user-eec7ffae</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#ede5e4'><td>ritz-lab</td><td>user-4a771e4a</td><td align='right'>0.0</td><td align='right'>—</td></tr>
<tr style='background-color:#ede5e4'><td>ritz-lab</td><td>user-938729e2</td><td align='right'>0.0</td><td align='right'>—</td></tr>
</table>

## Usage over time

Charts below cover this week: **2026-09-21 00:00 to 2026-09-28 00:00** (UTC-07:00).

![CPU allocation over time](cpu_alloc.png)

![GPU allocation over time](gpu_alloc_util.png)

Each named lab has its own color. Solid = utilized by lab, hatched = allocated but idle or unmeasured, gray = usage not traceable to a lab, dashed line = cluster capacity. Zero-usage legend entries are omitted.

Attribution combines `nvidia-smi`'s process listing with Slurm's GPU-to-job binding record; the latter caught **1169** readings the former missed.
Allocation counts include all nodes of each job, including corrected historical totals. Before October 2, 2026, utilization sampling could skip nodes in compressed hostlists; those missing readings cannot be reconstructed and do not establish that the GPUs were idle.
GPU-hour estimates credit at most one 30-minute interval per sample; collector outages are not extrapolated. CPU utilization is weighted by the allocated cores of jobs with observed counters.

## Queue

![Queue wait time](queue_wait.png)

"Pending" here means Slurm is actively scoring the job (has a `sprio` priority) - excludes jobs blocked on a dependency or array-task throttle.

## CPU usage vs. GPU usage

![CPU usage vs GPU usage, decayed](cpu_gpu_usage.png)

One point per user per snapshot (n=681), usage decayed on Slurm's ~7-day fairshare half-life.

**GPU usage doesn't count toward priority on this cluster** (`TRESBillingWeights`/`PriorityWeightTRES` unset) - watch the **upper-left**: low CPU usage (high priority) with high GPU usage.

