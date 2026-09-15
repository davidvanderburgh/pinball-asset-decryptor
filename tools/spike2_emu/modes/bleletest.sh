#!/bin/bash
# bleletest.sh [cases_file] - does a blele light command change the playfield LEDs? (item 125)
#
# Each non-comment line of the cases file is "<owner> <command>", handed to the game's
# own light runner through the probe (padmode.blele -> 0x1c3454(owner, empty group,
# command, 0)). ledact.py's validated measure judges it: the two-window NOISE first,
# then per line a fresh PRE window, the command, a POST window, and the pre->post
# distance plus the fade shapes POST fired that PRE never did. A command is a light
# only if that repeats on the second copy of the same line; a --remove line is the
# "off" when its POST looks like the PRE before the command it follows.
# Needs a run with PAD_TRACE_SO=/lib/padmode.so and a game up; a rig action.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
M=$RIG/modes
CASES=${1:-$M/blele_cases.txt}
W=/var/tmp/bleletest
SECS=${BLELE_SECS:-6}
mkdir -p "$W"
measure() { python3 "$M/ledact.py" "$SECS" 250 --save "$W/$1.json" > /dev/null; }
measure noise1
measure noise2
echo "=== noise (two windows, nothing fired)"
python3 "$M/ledact.py" --compare "$W/noise1.json" "$W/noise2.json" | tail -1
n=0
grep -vE '^[[:space:]]*(#|$)' "$CASES" | while IFS= read -r line; do
  n=$((n + 1))
  echo "=== [$n] $line"
  measure "pre$n"
  printf '%s\n' "$line" > "$D/padmode.blele"
  sleep 0.8
  grep -a '\[trigger\] blele' "$D/padmode.log" | tail -1
  measure "post$n"
  python3 "$M/ledact.py" --compare "$W/pre$n.json" "$W/post$n.json" | tail -1
  python3 "$M/ledact.py" --footprint "$W/post$n.json" "$W/pre$n.json" | head -10
done
