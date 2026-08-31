#!/bin/bash
# Bounded run of launch.sh: kill the whole namespace process group after
# LIMIT seconds (the `timeout` tool leaks qemu children — the Spike 2 rig hit
# this too, so we group-kill instead).  Log -> $S1_LOG (default emu.log here).
#   run.sh [LIMIT_SECONDS]      env S1_STRACE=1 for a guest syscall trace
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LIMIT="${1:-8}"
: "${S1_LOG:=$HERE/emu.log}"
: > "$S1_LOG"
setsid bash -c "exec bash '$HERE/launch.sh'" >"$S1_LOG" 2>&1 &
PG=$!
steps=$((LIMIT * 4)); i=0
while [ "$i" -lt "$steps" ]; do
  kill -0 "$PG" 2>/dev/null || { echo "[exited on its own ~$((i/4))s]"; break; }
  sleep 0.25; i=$((i+1))
done
if kill -0 "$PG" 2>/dev/null; then
  echo "[still running at ${LIMIT}s — killing process group]"
  kill -KILL -"$PG" 2>/dev/null
fi
pkill -KILL -f 'launch.sh --inner' 2>/dev/null
pkill -KILL -f 'qemu-arm-static ./game' 2>/dev/null
pkill -KILL -f '/game' 2>/dev/null
wait "$PG" 2>/dev/null
echo "=== $S1_LOG: $(wc -l < "$S1_LOG") lines ==="
