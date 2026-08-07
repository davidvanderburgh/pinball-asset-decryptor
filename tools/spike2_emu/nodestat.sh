#!/bin/bash
# nodestat.sh - the %s of "Check Node Board %d : %s". The Tech Alerts screen
# shows these live and they change (Invalid -> Not Initialized), so the set of
# possible values names every node-board state the game can be in.
. "$(dirname "$0")/padpath.sh"
cd "$ROOT/games/godzilla_pro"
echo "=== 'Not Initialized' and neighbours ==="
strings -td game | grep -nE 'Not Initialized|Not Detected|Not Responding|Wrong Type|Bad Firmware' | head -20
echo
echo "=== window around the Check Node Board format ==="
strings -td game | awk '$1 > 6248400 && $1 < 6249100' | head -60
