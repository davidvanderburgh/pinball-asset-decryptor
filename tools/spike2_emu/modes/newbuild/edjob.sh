#!/bin/bash
# edjob.sh <key> <card> - EDITION alone in a new build's operator menu (PAD-1555): for a build whose MUSIC MODE files
# have no room (D&D: image.bin and its own bank fill the machine's memory, sound_modes.BANK_SONG_NO_ROOM).
#
#   SET=<dir>       a Write-built override set with editions, EDITION ticked on the Service menu tab
#   STEPSFILE=<f>   the presses from attract to EDITION's row (service_menu.walk)
#
# The set bound; in attract the walk to EDITION, Select / Plus / Select (2), a shot (edition.png), BACK out; the
# settings store copied (NVM). Pass here: the walk ran; musiccheck.py's store reading says EDITION = 2.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: edjob.sh <key> <card>}" "${2:?usage: edjob.sh <key> <card>}"
MODES=$RIG/modes
STEPS=$(cat "${STEPSFILE:-/dev/null}" 2>/dev/null)
[ -d "${SET:-}" ] && [ -n "$STEPS" ] || job_fail "needs SET and STEPSFILE"
if [ -d "$SET-modes" ]; then                # a set with modes' files: the runtime staged with them
    S=$JOB_OUT/stage
    mkdir -p "$S"
    cp "$SET-modes/"* "$S/" || job_fail "could not stage"
    [ -f "$S/sounds.cfg" ] && sed -i '/^only$/d' "$S/sounds.cfg"
    printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
    bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
    export PAD_MODE_SO=/lib/pad_mode.so
fi                                          # EDITION alone is the grown game program's: no runtime needed
export PAD_OVERRIDE_DIR=$SET
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
job_sleep 5
walk() { local s; for s in "$@"; do case "$s" in w*) job_sleep "${s#w}" ;; *) job_press "$s" 200; job_sleep 0.6 ;; esac; done; }
walk $STEPS
walk 25 w1 26 w1 25 w1.5
job_shot "$JOB_OUT/edition.png"
walk 28 w1 28 w1 28 w1 28 w1 28 w1 28 w2
job_sleep 6
nvd=$(dirname "$ROOT")/upper/data/nv/$GAME/NVM
nv=$( [ -d "$nvd" ] && ls -t "$nvd" | grep -v '\.crc32$' | head -1)
[ -n "$nv" ] && cp "$nvd/$nv" "$JOB_OUT/NVM"
cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null
[ -n "$nv" ] || job_fail "no settings store copied"
job_pass "attract=${JOB_ATTRACT_S}s EDITION walked and set; NVM copied"
