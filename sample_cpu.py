#!/usr/bin/env python3
"""
Reads one node's per-job cgroup CPU accounting from stdin, as produced by
run.sh's ssh command scanning cgroup v2's
/sys/fs/cgroup/system.slice/slurmstepd.scope/job_*/cpu.stat - one
"CPUJOB <raw_job_id> <usage_usec>" line per job on that node. Appends one
JSON line per job to stdout (redirected to data/cpu_samples.jsonl by the
caller).

usage_usec is cgroup v2's cumulative CPU time (summed across all cores the
job is using) since the job's cgroup was created - a running counter, not a
percentage, same shape as GPU-hour integration elsewhere in this repo:
render_readme.py computes utilization from the delta between consecutive
samples of the same job.

No user/lab/anonymization here - job_id (the cgroup's raw per-task id) is
enough to join against queue_samples.jsonl's "job_id_map" rows (from
sample_queue.py), which is where user/lab already live.
"""
import sys
import json

def main():
    ts, node = sys.argv[1], sys.argv[2]
    for line in sys.stdin:
        parts = line.split()
        if len(parts) != 3 or parts[0] != "CPUJOB":
            continue
        _, job_id, usage_usec = parts
        if not usage_usec.isdigit():
            continue
        print(json.dumps({"ts": ts, "node": node, "job_id": job_id,
                           "cpu_usage_usec": int(usage_usec)}))

if __name__ == "__main__":
    main()
