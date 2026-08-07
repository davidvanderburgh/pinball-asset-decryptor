#!/bin/bash
. "$(dirname "$0")/padpath.sh"
R=$ROOT
echo "=== /dump contents ==="
ls -la $R/dump/ 2>/dev/null | head
echo
echo "=== debug_log.txt (last 40 lines) ==="
tail -40 $R/dump/debug_log.txt 2>/dev/null
echo
echo "=== does it mention 260 / 0x104 ? ==="
grep -n '260' $R/dump/debug_log.txt 2>/dev/null | head
