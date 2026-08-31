#!/bin/bash
# Bounded run of emu_root.sh (root device-model boot): group-kill after LIMIT
# seconds, then clean up CUSE daemons AND restore the system binfmt (the
# Spike 2 rig relies on the stock qemu-arm registration, so we must put it
# back).  Log -> $S1_LOG.  Run as root: wsl -u root -- bash run_root.sh [secs]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LIMIT="${1:-10}"
: "${S1_LOG:=$HERE/emu.log}"
BF=/proc/sys/fs/binfmt_misc

restore_binfmt() {
  [ -e "$BF/qemu-arm-pad" ] && echo -1 > "$BF/qemu-arm-pad" 2>/dev/null || true
  [ -e "$BF/qemu-arm" ] && echo 1 > "$BF/qemu-arm" 2>/dev/null || true
}

: > "$S1_LOG"
setsid bash -c "exec bash '$HERE/emu_root.sh'" >"$S1_LOG" 2>&1 &
PG=$!
steps=$((LIMIT * 4)); i=0
while [ "$i" -lt "$steps" ]; do
  kill -0 "$PG" 2>/dev/null || { echo "[exited on its own ~$((i/4))s]"; break; }
  sleep 0.25; i=$((i+1))
done
kill -0 "$PG" 2>/dev/null && { echo "[bounded kill at ${LIMIT}s]"; kill -KILL -"$PG" 2>/dev/null; }
pkill -KILL -f 'emu_root.sh' 2>/dev/null
pkill -KILL -f 's1hwshim' 2>/dev/null
pkill -KILL -f 'qemu-arm-pad' 2>/dev/null
pkill -KILL -f '/games/.*/game' 2>/dev/null
wait "$PG" 2>/dev/null
restore_binfmt
echo "=== $S1_LOG: $(wc -l < "$S1_LOG") lines ==="
