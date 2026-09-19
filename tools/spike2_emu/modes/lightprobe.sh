#!/bin/bash
# lightprobe.sh <item>... - does a light CANDIDATE change the playfield LEDs? (item 125)
#
#   item = <show_id>          show_start(id), then show_kill(id)     (padmode.show)
#        = fx:<n>:<a>:<b>     0x185e9c(n, a, b)                      (padmode.fx)
#
# ledact.py's validated measure (MODE_API.md): two back-to-back windows with nothing
# fired give the NOISE distance; then, per item, a fresh PRE window right before it,
# the item fired through the probe, and a window after. A light candidate is real only
# if pre->after sits well outside the noise, fires fade shapes the pre window did not,
# AND does it again on a repeat - run 4's first show 96 window looked like a show (10
# new fade shapes) and its repeats did not (716 and 2766 mean-L1 against a noise of
# 2095, 4 and 0 new shapes), and the control show 231 moved more than either.
# Needs a run with PAD_TRACE_SO=/lib/padmode.so and a game up; a rig action.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
M=$RIG/modes
W=/var/tmp/lightprobe
SECS=${LIGHTPROBE_SECS:-6}
mkdir -p "$W"
python3 "$M/ledact.py" "$SECS" 250 --save "$W/noise1.json" > /dev/null
python3 "$M/ledact.py" "$SECS" 250 --save "$W/noise2.json" > /dev/null
echo "=== noise (two windows, nothing fired)"
python3 "$M/ledact.py" --compare "$W/noise1.json" "$W/noise2.json" | tail -1
n=0
for item in "$@"; do
  n=$((n + 1))
  tag="$n-${item//:/_}"
  echo "=== $item"
  python3 "$M/ledact.py" "$SECS" 250 --save "$W/pre$tag.json" > /dev/null
  case "$item" in
    fx:*) IFS=: read -r _ fn fa fb <<< "$item"
          echo "$fn ${fa:-0} ${fb:-0}" > "$D/padmode.fx" ;;
    *)    echo "$item" > "$D/padmode.show" ;;
  esac
  sleep 0.8
  python3 "$M/ledact.py" "$SECS" 250 --save "$W/post$tag.json" > /dev/null
  case "$item" in
    fx:*) ;;
    *)    echo "$item" > "$D/padmode.showkill"; sleep 1 ;;
  esac
  grep -a "\[trigger\] \(fx\|show\)" "$D/padmode.log" | tail -2
  python3 "$M/ledact.py" --compare "$W/pre$tag.json" "$W/post$tag.json" | tail -1
  python3 "$M/ledact.py" --footprint "$W/post$tag.json" "$W/pre$tag.json" | head -8
done
