#!/bin/bash
# chaljob.sh <key> <card> - a challenge of a mode's own on a new build's start menu of game-mode indices (PAD-1555;
# PAD-1504's PAD CHALLENGE proof on Pokemon 0.87, made for Spike 2).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# Run with rigbatch --speed 1. A mode file `challenge new` (PAD CHALLENGE, 30 s); credits dropped, both flipper
# buttons held in attract (the start menu), one left step wraps the cursor onto the appended MODE CHALLENGE entry,
# START. Pass: `MODE CHALLENGE appended`, `... picked on the start menu`, and `PAD CHALLENGE START (challenge pick)` at
# the ball's start - the evidence CHALLENGE_MENU_FRAME_PROVEN records.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: chaljob.sh <key> <card>}" "${2:?usage: chaljob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name PAD CHALLENGE\ngame_modes stack\nseconds 30\nchallenge new\nshots 0xffffffff\naward 1000\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
LIST=$DUMP/tables/$GAME/switch_list.txt
sw() { awk -v p="$1" '$1 ~ /^[0-9]+$/ { n = ""; for (i = 5; i <= NF; i++) n = n " " $i; if (toupper(n) ~ p) { print $1; exit } }' "$LIST"; }
START=$(sw 'START BUTTON'); LEFT=$(sw '^ (L|LEFT) FLIPPER BUTTON$'); RIGHT=$(sw '^ (R|RIGHT) FLIPPER BUTTON$')
[ -n "$START" ] && [ -n "$LEFT" ] && [ -n "$RIGHT" ] || job_fail "no START ($START) or flippers ($LEFT $RIGHT) in the switch list"
job_sleep 5
python3 "$RIG/plunge.py" coin 4 > /dev/null 2>&1 < /dev/null
job_sleep 2
for try in 1 2 3; do
    job_press "$LEFT" 2500 & job_press "$RIGHT" 2500; wait
    job_wait_log "$log" 'challenge menu: MODE CHALLENGE appended' 8 && break
done
app=$(grep -a -m1 -Eo 'challenge menu: MODE CHALLENGE appended \([^)]*\)' "$log")
[ -n "$app" ] || { cp "$log" "$JOB_OUT/mode.log"; job_fail "no MODE CHALLENGE on the menu: $(grep -a 'challenge' "$log" | tail -1 | cut -c1-160)"; }
job_press "$LEFT"; job_sleep 1.5
job_shot "$JOB_OUT/on_entry.png"
job_press "$START" 400
job_wait_log "$log" 'PAD CHALLENGE START \(challenge pick\)' 40 || true
job_sleep 3
job_shot "$JOB_OUT/after_start.png"
cp "$log" "$JOB_OUT/mode.log"
picked=$(grep -a -m1 -Eo 'challenge [0-9]+ \(PAD CHALLENGE\) picked on the start menu[^;]{0,60}' "$log")
start=$(grep -a -m1 -Eo 'PAD CHALLENGE START \(challenge pick\)[^;]{0,60}' "$log")
[ -n "$start" ] || job_fail "$app; ${picked:-not picked}; no START (challenge pick): $(grep -a -E 'challenge|PAD CHALLENGE' "$log" | tail -1 | cut -c1-140)"
job_pass "attract=${JOB_ATTRACT_S}s $app; ${picked:-pick line not seen}; $start"
