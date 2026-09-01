#!/usr/bin/env python3
"""
Reads one node's sectioned nvidia-smi output from stdin (as produced by run.sh's
ssh command: --GPU--, --PROC--, --CGROUP-- sections) and appends one JSON line per
physical GPU to stdout (redirected to data/gpu_samples.jsonl by the caller).

"lab" is the user's Unix group ending in "-lab" (e.g. witter-lab,
ibarragarciapadilla-lab) - this cluster has no per-lab restriction on squeue or
on /proc process visibility (verified: PrivateData=none, and ps/nvidia-smi on a
node show every user's processes regardless of group), so this reflects real
cross-lab usage, not just the operator's own lab.

If MODE=anon_users, the user field is replaced with a salted hash (user-XXXXXXXX)
so the same real user maps to the same pseudonym for the life of the salt, without
the real username ever being written to disk. The lab field is always left real -
lab-level usage is the actionable signal for a public tracker; individual identity
is not.
"""
import sys
import json
from anon import pseudonym

def main():
    ts, node, mode, salt = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    section = None
    gpus = {}       # index -> dict
    procs = []      # list of (gpu_uuid_or_none, pid, mem)
    pidmap = {}     # pid -> (user, job, lab)

    for line in sys.stdin:
        line = line.rstrip("\n")
        if line == "--GPU--":
            section = "gpu"; continue
        if line == "--PROC--":
            section = "proc"; continue
        if line == "--CGROUP--":
            section = "cgroup"; continue
        if not line.strip():
            continue
        if section == "gpu":
            parts = [p.strip() for p in line.split(",")]
            # UUID is the exact process-to-device join key. Accept the legacy
            # five-column format as well so saved fixtures/old callers fail
            # soft during upgrades.
            if len(parts) == 6:
                idx, gpu_uuid, ugpu, umem, memused, memtot = parts
            elif len(parts) == 5:
                idx, ugpu, umem, memused, memtot = parts
                gpu_uuid = None
            else:
                continue
            try:
                gpus[int(idx)] = {
                    "gpu_uuid": gpu_uuid,
                    "util_gpu": float(ugpu), "util_mem": float(umem),
                    "mem_used": float(memused), "mem_tot": float(memtot),
                }
            except ValueError:
                continue
        elif section == "proc":
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                gpu_uuid, pid, mem = parts
            elif len(parts) == 2:
                pid, mem = parts
                gpu_uuid = None
            else:
                continue
            try:
                procs.append((gpu_uuid, pid, float(mem)))
            except ValueError:
                continue
        elif section == "cgroup":
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "PIDMAP":
                pid = parts[1]
                user = parts[2] if len(parts) > 2 else ""
                job = parts[3] if len(parts) > 3 else ""
                lab = parts[4] if len(parts) > 4 else "unknown"
                pidmap[pid] = (user, job, lab)

    # Join on NVIDIA's device UUID. The former memory-footprint heuristic sent
    # every process of a symmetric tensor-parallel job to GPU 0 because all
    # cards/processes used the same amount of memory. Keep that heuristic only
    # as a compatibility fallback for legacy five/two-column input.
    gpu_users = {idx: [] for idx in gpus}
    uuid_to_idx = {g.get("gpu_uuid"): idx for idx, g in gpus.items()
                   if g.get("gpu_uuid")}
    for gpu_uuid, pid, mem in procs:
        if not gpus:
            continue
        best_idx = uuid_to_idx.get(gpu_uuid)
        if best_idx is None:
            best_idx = min(gpus, key=lambda i: abs(gpus[i]["mem_used"] - mem))
        user, job, lab = pidmap.get(pid, ("", "", ""))
        gpu_users[best_idx].append((user, job, lab))

    for idx, g in sorted(gpus.items()):
        owners = gpu_users.get(idx, [])
        if owners:
            # one row per distinct (user, job) pair sharing this physical GPU
            for user, job, lab in dict.fromkeys(owners):
                uf = pseudonym(user, salt) if mode == "anon_users" else (user or None)
                row = {
                    "ts": ts, "node": node, "gpu_idx": idx,
                    "gpu_uuid": g.get("gpu_uuid"),
                    "util_gpu": g["util_gpu"], "util_mem": g["util_mem"],
                    "mem_used": g["mem_used"], "mem_tot": g["mem_tot"],
                    "user": uf, "lab": lab or None, "job": job or None,
                    "n_procs": len(owners),
                }
                print(json.dumps(row))
        else:
            row = {
                "ts": ts, "node": node, "gpu_idx": idx,
                "gpu_uuid": g.get("gpu_uuid"),
                "util_gpu": g["util_gpu"], "util_mem": g["util_mem"],
                "mem_used": g["mem_used"], "mem_tot": g["mem_tot"],
                "user": None, "lab": None, "job": None, "n_procs": 0,
            }
            print(json.dumps(row))

if __name__ == "__main__":
    main()
