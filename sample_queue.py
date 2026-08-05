#!/usr/bin/env python3
"""
Samples the Slurm queue directly on the login node - no ssh needed, this is the
same class of read as `squeue --user $USER`. Appends one JSON line per job (pending
or running) plus one "totals" line for cluster-wide CPU/GPU capacity, to stdout
(redirected to data/queue_samples.jsonl by the caller).

Two Slurm CLIs, joined by job id:
  squeue - per-job user/state/cpus/gpus/node/submit-and-start times
  sprio  - per-job priority and its age/fairshare/jobsize/partition components
           (PriorityWeightTRES is unset on this cluster, so none of these
           components are GPU-aware - see README for what that means in practice)

Lab is resolved the same way as sample_gpu.py: the caller's Unix group ending in
"-lab", via `id -Gn` (works fine from the login node, no ssh required). If
MODE=anon_users, the user field is hashed into a stable pseudonym; lab stays real.
"""
import sys
import json
import subprocess
from datetime import datetime, timezone
from anon import pseudonym

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout

def parse_gpus(gres_field):
    if "gpu" not in gres_field:
        return 0
    last = gres_field.rsplit(":", 1)[-1]
    return int(last) if last.isdigit() else 0

def to_epoch(ts):
    if not ts or ts in ("N/A", "Unknown"):
        return None
    try:
        return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").timestamp())
    except ValueError:
        return None

_lab_cache = {}
def lab_of(user):
    if user not in _lab_cache:
        groups = run(["id", "-Gn", user]).split()
        _lab_cache[user] = next((g for g in groups if g.endswith("-lab")), None)
    return _lab_cache[user]

def main():
    ts, mode, salt = sys.argv[1], sys.argv[2], sys.argv[3]
    now = int(datetime.now(timezone.utc).timestamp())

    sprio_out = run(["sprio", "-h", "-o", "%i|%Y|%A|%F|%J|%P"])
    prio = {}
    for line in sprio_out.splitlines():
        parts = line.split("|")
        if len(parts) != 6:
            continue
        jobid, y, a, f, j, _partition_prio = parts
        prio[jobid] = {"priority": int(y), "age": int(a), "fairshare": int(f),
                        "jobsize": int(j)}

    squeue_out = run(["squeue", "-h", "-a",
                       "-o", "%i|%u|%T|%C|%b|%N|%V|%S|%r"])
    for line in squeue_out.splitlines():
        parts = line.split("|")
        if len(parts) != 9:
            continue
        jobid, user, state, cpus, gres, node, submit, start, reason = parts
        submit_ep = to_epoch(submit)
        start_ep = to_epoch(start)
        if state == "RUNNING" and start_ep:
            wait_seconds = start_ep - submit_ep if submit_ep else None
        elif submit_ep:
            wait_seconds = now - submit_ep
        else:
            wait_seconds = None

        lab = lab_of(user)
        uf = pseudonym(user, salt) if mode == "anon_users" else user
        # sprio reports priority against the base job id; array tasks like
        # "258364_412" or "258364_[413-831%40]" need that prefix stripped to join.
        p = prio.get(jobid.split("_")[0], {})
        row = {
            "ts": ts, "job_id": jobid, "user": uf, "lab": lab, "state": state,
            "cpus": int(cpus) if cpus.isdigit() else 0,
            "gpus": parse_gpus(gres), "node": node or None,
            "wait_seconds": wait_seconds, "reason": reason or None,
            "priority": p.get("priority"), "age": p.get("age"),
            "fairshare": p.get("fairshare"), "jobsize": p.get("jobsize"),
        }
        print(json.dumps(row))

    sinfo_out = run(["sinfo", "-h", "-o", "%D|%C|%G", "-p", "main"])
    cpus_total = gpus_total = 0
    for line in sinfo_out.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        nnodes, cpu_field, gres = parts
        nnodes = int(nnodes)
        # %C is "alloc/idle/other/total" per the node-state group this line covers
        c_total = int(cpu_field.split("/")[-1])
        cpus_total += c_total
        if "gpu" in gres:
            last = gres.rsplit(":", 1)[-1]
            if last.isdigit():
                gpus_total += int(last) * nnodes
    print(json.dumps({"kind": "totals", "ts": ts, "cpus_total": cpus_total,
                       "gpus_total": gpus_total}))

if __name__ == "__main__":
    main()
