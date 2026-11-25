#!/bin/bash
# turnjob.sh <key> <card> - a sound's files in turn on a new build (PAD-1555; PAD-565's sweep, re-made: TURN_PROVEN's
# evidence).
#
#   SET=<dir>      a Write-built override set (engine.write_overrides; its `<dir>-modes` beside it holds sounds.cfg,
#                  game.port): the slot replaced by a 500 Hz tone, its files in turn 1000 / 2000 Hz
#   SO=<object>    built with modes/sdk/sound_fire_mode.c (build_mode.sh -o fire.so mode_file.c sound_fire_mode.c)
#   REQ=<request>  the request that plays the slot (alone)
#   GAP=<s>        game seconds between fires (default 2; longer than the slot's own sound - Foo Fighters LE's idx 450
#                  runs 3.45 s, and a fire while it still plays starts nothing)
#
# The set bound (PAD_OVERRIDE_DIR), its modes' files staged with the fire instrument as the runtime; in attract REQ is
# fired six times, 2 s apart, the size of $DUMP/audio.raw (s16le, 44.1 kHz, stereo) kept before each (marks.txt) and
# the capture copied out; turncheck.py reads the half second after each fire. Pass here: six `[soundfire] fire` lines
# and the runtime's `sounds in turn:` lines; the tones are turncheck.py's.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: turnjob.sh <key> <card>}" "${2:?usage: turnjob.sh <key> <card>}"
MODES=$RIG/modes
[ -d "${SET:-}" ] && [ -d "$SET-modes" ] && [ -f "${SO:-}" ] && [ -n "${REQ:-}" ] || job_fail "needs SET, SO and REQ"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SET-modes/"* "$S/" && cp "$SO" "$S/pad_mode.so" || job_fail "could not stage"
# the set's sounds.cfg says `only` (no modes of a card's); the fire instrument is one, so the line goes
sed -i '/^only$/d' "$S/sounds.cfg"
printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
rm -f "$DUMP/sound.fire" "$DUMP/sound.active" "$DUMP/sound.stop"     # a run that died left its trigger
export PAD_MODE_SO=/lib/pad_mode.so PAD_OVERRIDE_DIR=$SET
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
A=$DUMP/audio.raw
job_wait_log "$log" 'soundfire\] ready' 30 || true
job_sleep 5
: > "$JOB_OUT/marks.txt"
for k in 1 2 3 4 5 6; do
    stat -c %s "$A" >> "$JOB_OUT/marks.txt" 2>/dev/null || echo 0 >> "$JOB_OUT/marks.txt"
    printf '%s' "$REQ" > "$DUMP/sound.fire"
    job_sleep "${GAP:-2}"
done
job_sleep 2
cp "$A" "$JOB_OUT/audio.raw" 2>/dev/null
cp "$log" "$JOB_OUT/mode.log"
fired=$(grep -a -c "soundfire\] fire $REQ" "$log")
turns=$(grep -a -Eo 'sounds in turn: [0-9a-f]{16} (looked up|played) \([0-9]+ time\(s\)\) - file [0-9]+ of [0-9]+' "$log" | sed -E 's/.* - file ([0-9]+) of.*/\1/' | tr '\n' ' ')
armed=$(grep -a -m1 -Eo 'sounds in turn: [0-9]+ sound\(s\) play their files in turn[^;]{0,40}|sounds in turn: off[^;]{0,100}' "$log")
[ -f "$JOB_OUT/audio.raw" ] || job_fail "no audio.raw"
[ "$fired" -ge 6 ] || job_fail "$fired fire line(s); ${armed:-nothing of the turns}"
job_pass "attract=${JOB_ATTRACT_S}s $armed; fired $fired; files in turn: ${turns:-none logged}"
