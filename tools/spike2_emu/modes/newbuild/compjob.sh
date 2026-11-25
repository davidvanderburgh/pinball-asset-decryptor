#!/bin/bash
# compjob.sh <key> <card> - Prolonged Competition on a new build's start menu (PAD-1555; PAD-1041's job, re-made).
#
#   COMP=<comp.cfg>  the card's comp.cfg, as the Modes tab writes it (prolonged_comp.cfg_text; newbuild/compcfg.py)
#   PORT=<port>      the port (default: modes/sdk/ports/<key>.port)
#   STEPS=<n>        right-flipper steps at most to reach the entry (default 16)
#
# Run with rigbatch --speed 1 (a menu walk at 4x missed flipper steps, PAD-1449). The runtime arms on the card's comp.cfg
# alone; both flipper buttons held in attract show the start menu (PAD-619), the right flipper walks it until the runtime says the entry is picked, START takes
# it. Pass: `prolonged competition: armed`, `on the start menu as entry N of N`, `... picked on the menu` and
# `ON until the machine is switched off - game 1 plays as Competition`.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: compjob.sh <key> <card>}" "${2:?usage: compjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${COMP:-}" ] || job_fail "needs PORT and COMP"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" && cp "$COMP" "$S/comp.cfg" \
    || job_fail "could not stage"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
cp "$COMP" "$DUMP/comp.cfg"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_wait_log "$log" 'prolonged competition: (armed|off)' 30 || true
armed=$(grep -a -m1 -Eo 'prolonged competition: (armed - on the start menu at 0x[0-9a-f]+|off - .*)' "$log" | cut -c1-160)
case "$armed" in *armed*) ;; *) cp "$log" "$JOB_OUT/mode.log"; job_fail "${armed:-the runtime said nothing of prolonged competition}";; esac
LIST=$DUMP/tables/$GAME/switch_list.txt
sw() { awk -v p="$1" '$1 ~ /^[0-9]+$/ { n = ""; for (i = 5; i <= NF; i++) n = n " " $i; if (toupper(n) ~ p) { print $1; exit } }' "$LIST"; }
START=$(sw 'START BUTTON'); LEFT=$(sw '^ (L|LEFT) FLIPPER BUTTON$'); RIGHT=$(sw '^ (R|RIGHT) FLIPPER BUTTON$')   # never UP LEFT FLIPPER EOS
[ -n "$START" ] && [ -n "$LEFT" ] && [ -n "$RIGHT" ] || job_fail "no START ($START) or flippers ($LEFT $RIGHT) in the switch list"
job_sleep 5
# CHOOSE YOUR MODE OF PLAY: both flipper buttons held in attract (PAD-619)
for try in 1 2 3; do
    job_press "$LEFT" 2500 & job_press "$RIGHT" 2500; wait
    job_wait_log "$log" 'prolonged competition: on the start menu as entry' 8 && break
done
grep -aq 'prolonged competition: on the start menu as entry' "$log" \
    || { cp "$log" "$JOB_OUT/mode.log"; job_fail "both flippers held showed no menu with the entry: $(grep -a 'prolonged competition' "$log" | tail -1 | cut -c1-160)"; }
entry=$(grep -a -m1 -Eo 'prolonged competition: on the start menu as entry [0-9]+ of [0-9]+[^)]*\)?' "$log" | cut -c1-160)
if [ "${STD:-0}" = 1 ]; then
    # the control: START on the menu's first entry (the game's own STANDARD) - a game that starts as the menu picked
    job_sleep 1.5; job_shot "$JOB_OUT/std.png"; job_press "$START" 400
    job_wait_log "$log" 'prolonged competition: game [0-9]+ starts' 20 || true
    job_sleep 2; job_shot "$JOB_OUT/std_after.png"; cp "$log" "$JOB_OUT/mode.log"
    std=$(grep -a -m1 -Eo 'prolonged competition: game [0-9]+ starts \(prolonged is off\)' "$log")
    [ -n "$std" ] || job_fail "$entry; STANDARD: START started no game either"
    job_pass "$entry; STANDARD: $std"
fi
# the entry is the menu's last: one left step wraps the cursor onto it (a right-flipper walk of up to 11 steps, at 1.2 s
# each, outlasted the menu's patience on King Kong LE 0.97 / 1.01: picked, then START took nothing); the walk is kept
# for a menu that does not wrap
job_press "$LEFT"; job_sleep 1.2; k=1
for ((; k < ${STEPS:-16}; k++)); do
    grep -aq 'prolonged competition: .* picked on the menu' "$log" && break
    job_press "$RIGHT"; job_sleep 1.2
done
picked=$(grep -a -m1 -Eo 'prolonged competition: [A-Z ]+ picked on the menu' "$log")
[ -n "$picked" ] || { cp "$log" "$JOB_OUT/mode.log"; job_fail "$entry; ${STEPS:-16} flipper steps never reached it"; }
job_shot "$JOB_OUT/picked.png"
job_press "$START" 400
job_sleep 3; job_shot "$JOB_OUT/after_start.png"
job_wait_log "$log" 'prolonged competition: ON until' 30 || true
job_sleep 3
cp "$log" "$JOB_OUT/mode.log"
on=$(grep -a -m1 -Eo 'prolonged competition: ON until the machine is switched off - game [0-9]+ plays as Competition \(flag [0-9]+ was -?[0-9]+\)' "$log")
[ -n "$on" ] || job_fail "$entry; $picked; START took it but: $(grep -a 'prolonged competition' "$log" | tail -1 | cut -c1-160)"
job_pass "attract=${JOB_ATTRACT_S}s $armed; $entry; $picked after $k step(s); $on"
