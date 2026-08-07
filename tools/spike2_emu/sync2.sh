#!/bin/bash
cd $HOME
L=${1:-gz56.log}
echo "=== [sync] events by call site ==="
grep '\[sync\]' "$L" | awk '{print $2, $4}' | sort | uniq -c | sort -rn | head -30
echo
echo "=== waits/posts with a return address inside the SceneCache code (0x44xxxx) ==="
grep '\[sync\]' "$L" | grep -E 'from=0x44[0-9a-f]{4}' | head -30
echo
echo "=== first 25 sync events in order ==="
grep '\[sync\]' "$L" | head -25
