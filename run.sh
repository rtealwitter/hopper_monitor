#!/bin/bash
# hopper_monitor - one sampling pass. Invoked by cron every INTERVAL_MIN, forever
# (no self-expiry - this is an ongoing public tracker, not a fixed-length experiment).
set -euo pipefail

DIR="$HOME/hopper_monitor"
CONFIG="$DIR/config"
DATA="$DIR/data"
LOG="$DIR/monitor.log"

# shellcheck source=/dev/null
source "$CONFIG"   # sets MODE (anon_users|named), INTERVAL_MIN, SALT
case "$MODE" in anon_users|named) ;; *) echo "Invalid monitor MODE" >&2; exit 1;; esac

exec 200>"$DIR/.run.lock"
flock -n 200 || { echo "[$(date -Iseconds)] previous run still in progress, skipping" >> "$LOG"; exit 0; }

TS=$(date -Iseconds)
echo "[$TS] run start (mode=$MODE)" >> "$LOG"

# Do not publish a partial or false-empty queue snapshot after a Slurm failure.
STAGE=$(mktemp -d) || exit 1
trap 'rm -rf "$STAGE"' EXIT
python3 "$DIR/sample_queue.py" "$TS" "$MODE" "$SALT" > "$STAGE/queue.jsonl" 2>>"$LOG" \
  || { echo "[$TS] queue sampling FAILED" >> "$LOG"; exit 1; }

# Start another part after 32 MiB instead of growing a file indefinitely.
GPU_DATA=$(python3 "$DIR/data_store.py" gpu_samples) || exit 1
CPU_DATA=$(python3 "$DIR/data_store.py" cpu_samples) || exit 1
QUEUE_DATA=$(python3 "$DIR/data_store.py" queue_samples) || exit 1

# ---- GPU sampler: ssh to every node currently running a GPU job, read nvidia-smi ----
# Expand every allocated hostlist: a multi-node job has no separate rows
# for its individual nodes. GPU-capable active nodes are sampled even when
# the job requests GPUs per job/task instead of through squeue's %b field.
ALL_NODES=$(timeout 60s squeue --state=RUNNING -a -h -o "%N" 2>>"$LOG" |
  while IFS= read -r nodes; do timeout 60s scontrol show hostnames "$nodes" || exit 1; done | sort -u) || exit 1
GPU_CAPACITY=$(timeout 60s sinfo -N -a -h -o "%N|%G" 2>>"$LOG") || exit 1
GPU_NODES=$(comm -12 <(printf '%s\n' "$ALL_NODES") \
  <(printf '%s\n' "$GPU_CAPACITY" | awk -F'|' '$2 ~ /gpu:/ {print $1}' | sort -u))

if [ -z "$GPU_NODES" ]; then
  echo "[$TS] no GPU jobs running cluster-wide right now" >> "$LOG"
fi

for n in $GPU_NODES; do
  if timeout 45s ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$n" '
    set -e
    echo "--GPU--"
    nvidia-smi --query-gpu=index,uuid,utilization.gpu,utilization.memory,memory.used,memory.total --format=csv,noheader,nounits
    echo "--PROC--"
    nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null
    echo "--CGROUP--"
    for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
      job=$(cat /proc/$p/cgroup 2>/dev/null | grep -oE "job_[0-9_]+" | head -1)
      user=$(ps -o user= -p "$p" 2>/dev/null | tr -d " ")
      lab=$(id -Gn "$user" 2>/dev/null | tr " " "\n" | grep -- "-lab$" | head -1)
      printf "PIDMAP %s %s %s %s\n" "$p" "${user:--}" "${job:--}" "${lab:-unknown}"
    done
  ' > "$STAGE/gpu.txt" 2>>"$LOG"; then
    python3 "$DIR/sample_gpu.py" "$TS" "$n" "$MODE" "$SALT" < "$STAGE/gpu.txt" >> "$GPU_DATA" 2>>"$LOG"
  else
    echo "[$TS] GPU sample incomplete for $n; discarded" >> "$LOG"
  fi
done

# ---- CPU sampler: ssh to every node running ANY job (GPU or not - includes
# himem, which never shows up in GPU_NODES), read per-job cgroup CPU
# accounting straight from cgroup v2. No process-visibility dependence, same
# as the GPU binding cross-reference below - just cat a file the kernel
# already maintains. ----
for n in $ALL_NODES; do
  if timeout 45s ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$n" '
    set -e
    for d in /sys/fs/cgroup/system.slice/slurmstepd.scope/job_*/; do
      [ -d "$d" ] || continue
      job=$(basename "$d"); job=${job#job_}
      usage=$(awk "/^usage_usec/{print \$2}" "$d/cpu.stat" 2>/dev/null)
      if [ -n "$usage" ]; then echo "CPUJOB $job $usage"; fi
    done
  ' > "$STAGE/cpu.txt" 2>>"$LOG"; then
    python3 "$DIR/sample_cpu.py" "$TS" "$n" < "$STAGE/cpu.txt" >> "$CPU_DATA" 2>>"$LOG"
  else
    echo "[$TS] CPU sample incomplete for $n; discarded" >> "$LOG"
  fi
done

# ---- queue sampler: squeue + sprio + scontrol, straight from the login node, no ssh ----
cat "$STAGE/queue.jsonl" >> "$QUEUE_DATA" || exit 1

# ---- render README + charts on a compute node (never matplotlib on the login node) ----
if sbatch --wait --partition=debug --time=5 --cpus-per-task=1 --mem=2G \
    --job-name=hopper_monitor_render --output="$DIR/render.out" --error="$DIR/render.out" \
    --wrap="cd $DIR && .venv/bin/python3 render_readme.py" >> "$LOG" 2>&1; then
  echo "[$TS] render complete" >> "$LOG"
else
  echo "[$TS] render FAILED - skipping commit this cycle" >> "$LOG"
  exit 1
fi

# ---- commit + push ----
cd "$DIR"
git add -A -- README.md assets data archive >> "$LOG" 2>&1 || exit 1
if ! git diff --cached --quiet; then
  git commit -q -m "update $TS" >> "$LOG" 2>&1 \
    || { echo "[$TS] git commit FAILED" >> "$LOG"; exit 1; }
else
  echo "[$TS] no data changes to commit" >> "$LOG"
fi

# Retry pending commits even when this cycle produced no data changes.
git push -q >> "$LOG" 2>&1 \
  || { echo "[$TS] git push FAILED" >> "$LOG"; exit 1; }

echo "[$TS] run complete" >> "$LOG"
