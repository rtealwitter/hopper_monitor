# hopper_monitor

Automated GPU/CPU/queue utilization tracker for `hopper.cluster`, updated every 30 minutes by cron. Usernames are anonymized to a stable per-account pseudonym; lab names are real.

Last updated: 2026-08-04T22:30:15-07:00
Samples: 6 queue snapshots, 6 GPU snapshots

## Resources

`hopper.cluster` currently reports **60 GPUs** and **2176 CPUs** total:

| Nodes | Count | CPUs/node | RAM/node | GPUs/node |
|---|---:|---:|---:|---|
| `gpu01`-`gpu15` | 15 | 128 | 750 GB | 4× NVIDIA L40S (48 GB VRAM) |
| `himem01`-`himem02` | 2 | 128 | 3000 GB | none |

## Headline

- **82.8%** of the cluster's 60 GPUs allocated, averaged across all samples
- **41.6%** average `nvidia-smi` utilization *when* a GPU is allocated to a job

## Per lab / per user

| Lab | User | GPU-hours allocated | CPU-hours allocated | GPU utilization |
|---|---|---:|---:|---:|
| witter-lab | user-d58f5a15 | 45.4 | 363.4 | 8% |
| zhuang-lab | user-0db9ced0 | 19.6 | 19.6 | 56% |
| witter-lab | user-554c620c | 4.0 | 21.9 | 91% |
| nerenberg-lab | user-6bb5f332 | 1.4 | 6.8 | 78% |
| ibarragarciapadilla-lab | user-eec7ffae | 0.0 | 4.4 | — |
| ibarragarciapadilla-lab | user-3cfc41a3 | 0.0 | 176.0 | — |

## Usage over time

![CPUs allocated over time](assets/cpu_alloc.png)

![GPUs allocated over time](assets/gpu_alloc.png)

![GPU utilization over time](assets/gpu_util.png)

The third chart is GPU-hardware-utilization weighted by allocation (Σ util% across allocated GPUs), stacked by lab, with the dashed line showing how many GPUs were allocated at that moment. The gap between the stack and the dashed line is allocated-but-idle capacity.

## Queue

![Queue wait time](assets/queue_wait.png)

## Priority vs. usage

![Priority vs GPU/CPU usage](assets/priority_scatter.png)

This cluster's Slurm priority is computed from fairshare + age + job size (`PriorityWeightTRES` is unset), so it does not weight GPU-heavy usage any differently from CPU-heavy usage. If these two panels look similarly shaped, that confirms it in practice.

## Allocated but idle (top 10)

Users holding a GPU allocation with `nvidia-smi` utilization ≤10% the longest, cumulatively:

| User | Lab | Idle GPU-hours |
|---|---|---:|
| user-d58f5a15 | witter-lab | 5.9 |
| user-0db9ced0 | zhuang-lab | 3.8 |
| user-6bb5f332 | nerenberg-lab | 0.2 |

