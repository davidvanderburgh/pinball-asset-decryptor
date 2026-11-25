#!/bin/bash
# mediajob.sh <key> <card> - our screen and clip on the glass on a new build (PAD-1555; PAD-420's media/proof_job2.sh,
# re-made).
#
#   SET=<dir>   the Try it set mediabuild.py built (its `set` and `set-modes`), as a /mnt path
#   PICK=1      press START twice after the plunge: a title that holds ball 1 on a pick screen (D&D's PLAYER 1 SELECT A
#               CHARACTER) shows nothing of the game until it is taken
#
# The set's stage installed (the shipped port, the mode file), its rewritten title files bound (PAD_OVERRIDE_DIR); in a
# game MEDIA TEST is started: its 4 s magenta title clip at its start, then its magenta screen while it runs. Frames
# (glshot) before it, 1 s and 2.5 s in (the clip), 7 s and 12 s in (the screen) and after it ends, kept in $JOB_OUT
# for mediacheck.py. Pass here: the runtime's `clip ... played` and `own screen ... found` lines and the frames.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: mediajob.sh <key> <card>}" "${2:?usage: mediajob.sh <key> <card>}"
MODES=$RIG/modes
[ -d "${SET:-}/set-modes" ] && [ -d "$SET/set" ] || job_fail "needs SET (a mediabuild.py output)"
bash "$MODES/tryit.sh" install "$SET/set-modes" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_OVERRIDE_DIR=$SET/set
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
if [ "${PICK:-0}" = 1 ]; then
    st=$(awk '$1 ~ /^[0-9]+$/ && toupper($0) ~ / START BUTTON *$/ {print $1; exit}' "$DUMP/tables/$GAME/switch_list.txt")
    for k in 1 2; do job_sleep 4; job_press "$st" 300; done
    python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
fi
job_sleep 12
job_shot "$JOB_OUT/f0_before.png"
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'MEDIA TEST START' 10 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the mode did not start"; }
job_sleep 1;   job_shot "$JOB_OUT/f1_clip1s.png"
job_sleep 1.5; job_shot "$JOB_OUT/f2_clip2s.png"
job_sleep 4.5; job_shot "$JOB_OUT/f3_screen7s.png"
job_sleep 5;   job_shot "$JOB_OUT/f4_screen12s.png"
bash "$MODES/tryit.sh" stop > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'MEDIA TEST END' 15 || true
job_sleep 8;   job_shot "$JOB_OUT/f5_after.png"
cp "$log" "$JOB_OUT/mode.log"
clip=$(grep -a -m1 -Eo 'clip "[^"]*" (NOT )?played[^;]{0,60}' "$log")
scr=$(grep -a -m1 -Eo 'own screen ("[^"]*" found[^;]{0,40}|not found[^;]{0,60})' "$log")
echo "$clip" | grep -q " played" && ! echo "$clip" | grep -q "NOT played" || job_fail "clip: ${clip:-no clip line}; screen: ${scr:-no screen line}"
echo "$scr" | grep -q " found" || job_fail "clip: $clip; screen: ${scr:-no screen line}"
job_pass "attract=${JOB_ATTRACT_S}s $clip; $scr; frames kept"
