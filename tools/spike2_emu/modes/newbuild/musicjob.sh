#!/bin/bash
# musicjob.sh <key> <card> - MUSIC MODE and EDITION in a new build's operator menu (PAD-1555; PAD-724's sweep, re-made:
# menu_settings.PROVEN's evidence).
#
#   SET=<dir>      a Write-built override set (engine.write_overrides with sound_modes slots + editions, both ticked on
#                  the Service menu tab; `<dir>-modes` beside it): the slot a 500 Hz tone, its mode 2 file 1000 Hz
#   SO=<object>    built with modes/sdk/sound_fire_mode.c
#   REQ=<request>  the request that plays the slot (alone)
#   STEPS="..."    the presses from attract to MUSIC MODE's row (service_menu.walk: 25 select, 26 plus/down, w<s>)
#   STEPSFILE=<f>  ... or a file holding them (a rigbatch list line cannot carry a value with spaces)
#   EDROW=<n>      rows from MUSIC MODE down to EDITION (default 1)
#   GAP=<s>        game seconds between fires (default 5)
#
# In attract REQ is fired twice (marks.txt); the walk to MUSIC MODE, Select / Plus / Select (2), EDROW downs to
# EDITION, Select / Plus / Select (2), shots of both (music.png, edition.png), BACK out to attract; REQ fired twice
# more; the capture, the log and the NVM store copied out. musiccheck: the first two fires 500 Hz, the last two 1000
# Hz (turncheck.py's measure) and the store holding both at 2 (nvread).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: musicjob.sh <key> <card>}" "${2:?usage: musicjob.sh <key> <card>}"
MODES=$RIG/modes
[ -z "${STEPS:-}" ] && [ -f "${STEPSFILE:-}" ] && STEPS=$(cat "$STEPSFILE")
[ -d "${SET:-}" ] && [ -d "$SET-modes" ] && [ -f "${SO:-}" ] && [ -n "${REQ:-}" ] && [ -n "${STEPS:-}" ] \
    || job_fail "needs SET, SO, REQ and STEPS"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SET-modes/"* "$S/" && cp "$SO" "$S/pad_mode.so" || job_fail "could not stage"
sed -i '/^only$/d' "$S/sounds.cfg"
printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
rm -f "$DUMP/sound.fire" "$DUMP/sound.active" "$DUMP/sound.stop"
export PAD_MODE_SO=/lib/pad_mode.so PAD_OVERRIDE_DIR=$SET
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
A=$DUMP/audio.raw
job_wait_log "$log" 'soundfire\] ready' 30 || true
job_sleep 5
fire() { stat -c %s "$A" >> "$JOB_OUT/marks.txt" 2>/dev/null || echo 0 >> "$JOB_OUT/marks.txt"
         printf '%s' "$REQ" > "$DUMP/sound.fire"; job_sleep "${GAP:-5}"; }
walk() { local s; for s in "$@"; do case "$s" in w*) job_sleep "${s#w}" ;; *) job_press "$s" 200; job_sleep 0.6 ;; esac; done; }
: > "$JOB_OUT/marks.txt"
fire; fire
walk $STEPS
walk 25 w1 26 w1 25 w1.5
job_shot "$JOB_OUT/music.png"
for ((k = 0; k < ${EDROW:-1}; k++)); do walk 26 w0.5; done
walk 25 w1 26 w1 25 w1.5
job_shot "$JOB_OUT/edition.png"
walk 28 w1 28 w1 28 w1 28 w1 28 w1 28 w2
job_sleep 6
job_shot "$JOB_OUT/after.png"
fire; fire
cp "$A" "$JOB_OUT/audio.raw" 2>/dev/null
cp "$log" "$JOB_OUT/mode.log"
nvd=$(dirname "$ROOT")/upper/data/nv/$GAME/NVM      # the store: a directory of generations, the newest the live one
nv=$( [ -d "$nvd" ] && ls -t "$nvd" | grep -v '\.crc32$' | head -1)
[ -n "$nv" ] && cp "$nvd/$nv" "$JOB_OUT/NVM"
fired=$(grep -a -c "soundfire\] fire $REQ" "$log")
[ "$fired" -ge 4 ] || job_fail "$fired fire line(s)"
job_pass "attract=${JOB_ATTRACT_S}s fired $fired; NVM ${nv:+copied}; judge with musiccheck"
