#!/bin/bash
# PAD-1476: run the show reel on the builds of a reel_list.py list, in WSL:
#   wsl -d Ubuntu -e bash tools/spike2_emu/modes/show_reel/go.sh <list (WSL path)> [rigs] [out dir]
# then reel_verdict.py <out dir>/<key> --write for each build. Builds the runtime from this worktree; keeps rig
# slot 2 parked while it runs (its stale ballfeed.off starves every game of balls); waits for a free slot (1, 3-5).
set -e
KIT=$(cd "$(dirname "$0")" && pwd)
WT=$(cd "$KIT/../../../.." && pwd)
SDK=$WT/tools/spike2_emu/modes/sdk
LIST=${1:?list}
N=${2:-1}
export REEL_OUT=${3:-/tmp/show_reel}
rm -rf "$REEL_OUT/rb"     # PAD-1475: its own rigbatch folder (a shared one handed an earlier run's cards out)
mkdir -p "$REEL_OUT/stage"
( cd "$SDK" && bash build_mode.sh -o "$REEL_OUT/stage/pad_mode.so" mode_file.c ) > "$REEL_OUT/build.txt" 2>&1
tr -d '\r' < "$KIT/reel_job.sh" > /tmp/show_reel_job.sh
tr -d '\r' < "$LIST" | sed "s#\$# WT=$WT KIT=$KIT REEL_OUT=$REEL_OUT#" > /tmp/show_reel_list.txt
DONE=/tmp/show_reel_done; rm -f $DONE
( while [ ! -e $DONE ]; do bash "$WT/tools/spike2_emu/riglock.sh" use 2 park-ballfeed "stale ballfeed.off: parked" > /dev/null 2>&1; sleep 45; done ) &
for i in $(seq 1 270); do
    bash "$WT/tools/spike2_emu/riglock.sh" list 2>/dev/null | awk '$1 ~ /^[1345]$/ && $2 == "(free)"' | grep -q . && break
    sleep 10
done
set +e
bash "$WT/tools/spike2_emu/rigbatch.sh" -n "$N" --speed 1 --who "$(basename "$WT")" --job-cap 1200 --out "$REEL_OUT/rb" /tmp/show_reel_list.txt -- bash /tmp/show_reel_job.sh > "$REEL_OUT/batch.log" 2>&1 < /dev/null
rc=$?
touch $DONE; sleep 1
bash "$WT/tools/spike2_emu/riglock.sh" release 2 park-ballfeed > /dev/null 2>&1 || true
echo "done rc=$rc" >> "$REEL_OUT/batch.log"
