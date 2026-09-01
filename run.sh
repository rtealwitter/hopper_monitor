#!/bin/bash
# hopper_monitor - one sampling pass. Invoked by cron every INTERVAL_MIN, forever
# (no self-expiry - this is an ongoing public tracker, not a fixed-length experiment).
set -uo pipefail

DIR="$HOME/hopper_monitor"
CONFIG="$DIR/config"
DATA="$DIR/data"
LOG="$DIR/monitor.log"

# shellcheck source=/dev/null
source "$CONFIG"   # sets MODE (anon_users|named), INTERVAL_MIN, SALT

exec 200>"$DIR/.run.lock"
flock -n 200 || { echo "[$(date -Iseconds)] previous run still in progress, skipping" >> "$LOG"; exit 0; }

TS=$(date -Iseconds)
echo "[$TS] run start (mode=$MODE)" >> "$LOG"

# ---- GPU sampler: ssh to every node currently running a GPU job, read nvidia-smi ----
# (drop bracket-hostlist entries like "gpu[10-14]" - squeue emits those for
# multi-node jobs alongside the already-expanded individual node names, so
# they're redundant and would just fail to resolve as a hostname)
GPU_NODES=$(squeue --state=RUNNING -h -o "%b %N" 2>>"$LOG" | awk '$1 ~ /gres\/gpu/ {print $NF}' | grep -v '\[' | sort -u)
ALL_NODES=$(squeue --state=RUNNING -h -o "%N" 2>>"$LOG" | grep -v '\[' | sort -u)

if [ -z "$GPU_NODES" ]; then
  echo "[$TS] no GPU jobs running cluster-wide right now" >> "$LOG"
fi

for n in $GPU_NODES; do
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$n" '
    echo "--GPU--"
    nvidia-smi --query-gpu=index,uuid,utilization.gpu,utilization.memory,memory.used,memory.total --format=csv,noheader,nounits
    echo "--PROC--"
    nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null
    echo "--CGROUP--"
    for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
      job=$(cat /proc/$p/cgroup 2>/dev/null | grep -oE "job_[0-9_]+" | head -1)
      user=$(ps -o user= -p "$p" 2>/dev/null | tr -d " ")
      lab=$(id -Gn "$user" 2>/dev/null | tr " " "\n" | grep -- "-lab$" | head -1)
      echo "PIDMAP $p $user $job ${lab:-unknown}"
    done
  ' 2>>"$LOG" | python3 "$DIR/sample_gpu.py" "$TS" "$n" "$MODE" "$SALT" >> "$DATA/gpu_samples.jsonl" 2>>"$LOG"
done

# ---- CPU sampler: ssh to every node running ANY job (GPU or not - includes
# himem, which never shows up in GPU_NODES), read per-job cgroup CPU
# accounting straight from cgroup v2. No process-visibility dependence, same
# as the GPU binding cross-reference below - just cat a file the kernel
# already maintains. ----
for n in $ALL_NODES; do
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$n" '
    for d in /sys/fs/cgroup/system.slice/slurmstepd.scope/job_*/; do
      [ -d "$d" ] || continue
      job=$(basename "$d"); job=${job#job_}
      usage=$(awk "/^usage_usec/{print \$2}" "$d/cpu.stat" 2>/dev/null)
      [ -n "$usage" ] && echo "CPUJOB $job $usage"
    done
  ' 2>>"$LOG" | python3 "$DIR/sample_cpu.py" "$TS" "$n" >> "$DATA/cpu_samples.jsonl" 2>>"$LOG"
done

# ---- queue sampler: squeue + sprio + scontrol, straight from the login node, no ssh ----
python3 "$DIR/sample_queue.py" "$TS" "$MODE" "$SALT" >> "$DATA/queue_samples.jsonl" 2>>"$LOG"

# ---- render README + charts on a compute node (never matplotlib on the login node) ----
if sbatch --wait --partition=debug --time=5 --cpus-per-task=1 --mem=2G \
    --job-name=hopper_monitor_render --output="$DIR/render.out" --error="$DIR/render.out" \
    --wrap="cd $DIR && .venv/bin/python3 render_readme.py" >> "$LOG" 2>&1; then
  echo "[$TS] render complete" >> "$LOG"
else
  echo "[$TS] render FAILED - skipping commit this cycle" >> "$LOG"
  exit 0
fi

# ---- commit + push ----
cd "$DIR"
git add -A -- README.md assets data archive >> "$LOG" 2>&1
if ! git diff --cached --quiet; then
  git commit -q -m "update $TS" >> "$LOG" 2>&1 && git push -q >> "$LOG" 2>&1 \
    || echo "[$TS] git commit/push FAILED" >> "$LOG"
else
  echo "[$TS] no data changes to commit" >> "$LOG"
fi

echo "[$TS] run complete" >> "$LOG"
