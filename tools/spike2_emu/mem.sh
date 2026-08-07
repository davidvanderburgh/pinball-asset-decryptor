#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
echo "=== meminfo-related strings in the game ==="
strings -a -t x $G | grep -iE 'meminfo|MemTotal|MemFree|MemAvailable|Cached|SwapTotal' | head -20
echo
echo "=== host /proc/meminfo as the game would see it ==="
head -6 /proc/meminfo
echo
echo "=== what the game read from /proc/meminfo (from the strace) ==="
grep -n 'meminfo' "$HOME/gz52.strace" | head -5
echo
echo "=== scene cache / budget related strings ==="
strings -a -t x $G | grep -iE 'SceneCache|budget|cache size|too large|out of memory|no room' | head -25
