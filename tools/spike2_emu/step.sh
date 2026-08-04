#!/bin/bash
# step.sh <switch-id> [ms] [label] - press one switch through the shared-memory
# keyboard channel, wait for the next host frame dump, and repack it for viewing.
#
# The wait is on a NEW FILE APPEARING, not on a fixed sleep: PAD_GL_FRAME_EVERY
# counts swaps, so the wall-clock gap between dumps drifts. Reading the previous
# frame as if it were the result of the press is exactly the "check the dump
# directory's mtimes before believing a frame is from this run" trap.
set -u
ID=${1:?switch id}
MS=${2:-300}
OUT=${3:-/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/now.png}
D=/home/david/shots
BEFORE=$(ls -t $D/*.png 2>/dev/null | head -1)
python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/swpoke.py "$ID" "$MS"
for i in $(seq 1 120); do
    F=$(ls -t $D/*.png 2>/dev/null | head -1)
    [ -n "$F" ] && [ "$F" != "$BEFORE" ] && break
    sleep 0.25
done
# one more, so the frame is comfortably after the press rather than straddling it
BEFORE=$F
for i in $(seq 1 120); do
    F=$(ls -t $D/*.png 2>/dev/null | head -1)
    [ -n "$F" ] && [ "$F" != "$BEFORE" ] && break
    sleep 0.25
done
echo "frame: $F"
python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/repack.py "$F" "$OUT" 1
