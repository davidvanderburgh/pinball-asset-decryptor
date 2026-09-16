#!/bin/bash
# padmode_drive.sh <switch_id>... - poke switches in a LIVE padmode.so run (item 125)
# and print what each caused: the shot dispatch (mode 0's copy carries the mask - the
# other 26 modes get the same call), tesla strike's own lines, scores, awards, mode
# starts/stops. How the switch -> shot bit map in MODE_API.md was read. Rig action.
. "$(dirname "$0")/../padpath.sh"
LOG=$ROOT/dump/padmode.log
for sw in "$@"; do
  n=$(wc -l < "$LOG")
  python3 "$RIG/swpoke.py" "$sw" 150 > /dev/null 2>&1 || echo "swpoke $sw failed"
  sleep 1.5
  echo "== switch $sw: $(grep -E "^$sw " "$TABLES/${PAD_GAME:-godzilla_pro}/switch_list.txt" | cut -c 23-)"
  tail -n +$((n + 1)) "$LOG" | grep -E 'dispatch|tesla|\[(score|award|mode|trigger|callout|ball)\]' | head -24
  if [ -f "$ROOT/dump/mode.log" ]; then
    # [mode] since item 126: the mode's name is data now, so the object's lines are
    # not KAIJU RUSH's. Anything still grepping [rush] matches nothing.
    tail -n 3 "$ROOT/dump/mode.log" | grep -E "^ *[0-9]+ \[mode\]" | tail -2
  fi
done
