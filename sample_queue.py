#!/usr/bin/env python3
"""
Samples the Slurm queue directly on the login node - no ssh needed, this is the
same class of read as `squeue --user $USER`. Appends one JSON line per job (pending
or running) plus one "totals" line for cluster-wide CPU/GPU capacity, to stdout
(redirected to data/queue_samples.jsonl by the caller).

Three Slurm CLIs, joined by job id:
  squeue   - per-job user/state/cpus/gpus/node/submit-and-start times
  sprio    - per-job priority and its age/fairshare/jobsize/partition components
             (PriorityWeightTRES is unset on this cluster, so none of these
             components are GPU-aware - see README for what that means in practice)
  scontrol - per-job physical GPU binding (node + device index), emitted as
             separate "gpu_bind" rows and cross-referenced against
             gpu_samples.jsonl in render_readme.py, since nvidia-smi's own
             process listing (used by sample_gpu.py) misses containerized/
             namespaced processes and can't attribute them on its own.

Lab is resolved the same way as sample_gpu.py: the caller's Unix group ending in
"-lab", via `id -Gn` (works fine from the login node, no ssh required). If
MODE=anon_users, the user field is hashed into a stable pseudonym; lab stays real.
"""
import re
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

def expand_idx(idx_expr):
    """'0-1,3' -> [0, 1, 3]"""
    out = []
    for part in idx_expr.split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out

def gpu_bindings(scontrol_json):
    """Yields (job_id, node, gpu_idx) for every physical GPU every RUNNING
    job holds, parsed from `scontrol show job -dd --json`'s gres_detail
    (one entry per node, e.g. "gpu:l40s:2(IDX:0-1)"), zipped against
    job_resources.allocated_nodes (same order). job_id matches the format
    squeue/sprio use for array tasks ("<array_job_id>_<array_task_id>")."""
    try:
        jobs = json.loads(scontrol_json).get("jobs", []) if scontrol_json.strip() else []
    except json.JSONDecodeError:
        jobs = []
    for j in jobs:
        if "RUNNING" not in (j.get("job_state") or []):
            continue
        gres_detail = j.get("gres_detail") or []
        nodes = (j.get("job_resources") or {}).get("allocated_nodes") or []
        if not gres_detail or len(gres_detail) != len(nodes):
            continue
        array_task_id = j.get("array_task_id") or {}
        if array_task_id.get("set"):
            job_id = f"{j['array_job_id']['number']}_{array_task_id['number']}"
        else:
            job_id = str(j["job_id"])
        for node_info, gres in zip(nodes, gres_detail):
            node = node_info.get("nodename")
            m = re.search(r"IDX:([0-9,\-]+)", gres)
            if not node or not m:
                continue
            for idx in expand_idx(m.group(1)):
                yield job_id, node, idx

def job_id_map(scontrol_json):
    """Yields (raw_job_id, display_job_id) for every RUNNING job. The cgroup
    layer (job_<raw_id>/ under slurmstepd.scope - see sample_cpu.py) and
    scontrol's own `job_id` field use the raw per-task integer id; squeue/
    sprio (and everywhere else in this repo) use the array-expanded display
    id ("<array_job_id>_<array_task_id>"). Used to translate sample_cpu.py's
    cgroup-sourced job ids so they join against the rest of the data."""
    try:
        jobs = json.loads(scontrol_json).get("jobs", []) if scontrol_json.strip() else []
    except json.JSONDecodeError:
        jobs = []
    for j in jobs:
        if "RUNNING" not in (j.get("job_state") or []):
            continue
        array_task_id = j.get("array_task_id") or {}
        if array_task_id.get("set"):
            display_id = f"{j['array_job_id']['number']}_{array_task_id['number']}"
        else:
            display_id = str(j["job_id"])
        yield str(j["job_id"]), display_id

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

    scontrol_out = run(["scontrol", "show", "job", "-dd", "--json"])

    # ---- GPU device binding: which physical (node, GPU index) each running
    # job holds, straight from Slurm's own allocation record - no ssh, and no
    # dependence on nvidia-smi seeing the job's PID (which it doesn't for
    # containerized/namespaced processes - the gap the "computing,
    # unattributed" band in the README exists to catch). Cross-referencing
    # this against gpu_samples.jsonl's (node, gpu_idx) readings in
    # render_readme.py lets those readings be attributed even when the
    # ssh-side PID lookup in run.sh comes up empty.
    for job_id, node, gpu_idx in gpu_bindings(scontrol_out):
        print(json.dumps({"kind": "gpu_bind", "ts": ts, "job_id": job_id,
                           "node": node, "gpu_idx": gpu_idx}))

    # ---- raw <-> display job id translation, for joining sample_cpu.py's
    # cgroup-sourced CPU accounting (see job_id_map() above).
    for raw_id, display_id in job_id_map(scontrol_out):
        print(json.dumps({"kind": "job_id_map", "ts": ts, "raw_id": raw_id,
                           "job_id": display_id}))

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
