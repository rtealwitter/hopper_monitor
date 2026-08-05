# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-08-05T07:00:16-07:00
Samples: 23 queue snapshots, 23 GPU snapshots

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **83.2%** of the cluster's 60 GPUs allocated, averaged across all samples
- **56.5%** average `nvidia-smi` utilization *when* a GPU is allocated to a job

## Per lab / per user

| Lab | User | GPU-hours allocated | CPU-hours allocated | GPU utilization |
|---|---|---:|---:|---:|
| witter-lab | user-d58f5a15 | 304.3 | 2434.3 | 9% |
| zhuang-lab | user-0db9ced0 | 134.7 | 135.2 | 50% |
| witter-lab | user-554c620c | 50.7 | 393.8 | 91% |
| nerenberg-lab | user-6bb5f332 | 19.0 | 95.0 | 78% |
| ibarragarciapadilla-lab | user-eec7ffae | 0.0 | 30.9 | — |
| ibarragarciapadilla-lab | user-3cfc41a3 | 0.0 | 1234.8 | — |

## Usage over time

![CPUs allocated over time](assets/cpu_alloc.png)

![GPUs allocated over time](assets/gpu_alloc.png)

![GPU utilization over time](assets/gpu_util.png)

The third chart is GPU-hardware-utilization weighted by allocation (Σ util% across allocated GPUs), stacked by lab, with the dashed line showing how many GPUs were allocated at that moment. The gap between the stack and the dashed line is allocated-but-idle capacity.

## Queue

![Queue wait time](assets/queue_wait.png)

## Priority vs. usage

![Priority vs GPU/CPU usage](assets/priority_scatter.png)

Each point is one user on one day (n=6): that day's allocated GPU/CPU-hours against their mean Slurm priority that same day, for everyone who ran something that day. Not a lifetime total per user - that would only grow and would mix together usage from weeks ago with today's priority.

**GPU usage does not currently affect priority, confirmed directly from the Slurm config**, not just inferred from the chart shape: `PriorityWeightTRES` is unset (a job's own GPU/CPU mix carries no weight), and partition `main` has no `TRESBillingWeights` configured, so fairshare usage accounting bills by CPU count alone - a job holding 4 GPUs and 8 CPUs accrues the same usage debt as an 8-CPU, no-GPU job. If the two panels above look similarly shaped, that's this setting in action, not a coincidence.

## Allocated but idle (top 10)

Users holding a GPU allocation with `nvidia-smi` utilization ≤10% the longest, cumulatively:

| User | Lab | Idle GPU-hours |
|---|---|---:|
| user-0db9ced0 | zhuang-lab | 24.6 |
| user-d58f5a15 | witter-lab | 15.1 |
| user-6bb5f332 | nerenberg-lab | 4.5 |
| user-554c620c | witter-lab | 2.0 |

## Recommendations

1. **Make GPU usage count toward priority.** It structurally can't today - see the confirmation above. Fix by setting `TRESBillingWeights` on the `main` partition to give GPUs a nonzero weight (e.g. `scontrol update partition=main TRESBillingWeights=CPU=1.0,GRES/gpu=<weight>`) and/or giving `PriorityWeightTRES` a GPU component, then restarting `slurmctld`. The weight value is a policy call (how many CPUs one GPU should be "worth") - not something to pick from monitoring data alone.

2. **Act on sustained low utilization, not just report it.** The idle leaderboard above already identifies who's holding GPUs allocated-but-idle the longest. Two escalating steps on top of it: email a reminder once a user crosses an idle-hours threshold, and if utilization stays low after the reminder, taper their priority (QOS demotion or a fairshare penalty) rather than leaving it honor-system. Not implemented here - needs a policy decision first (threshold, grace period, who gets cc'd, and mail delivery from this host) before it's safe to automate.

