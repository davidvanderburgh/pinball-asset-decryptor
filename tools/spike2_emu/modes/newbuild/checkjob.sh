#!/bin/bash
# checkjob.sh <key> <card> - the Modes tab's Check this game as a rigbatch job (PAD-1555): a new build's port,
# drafted by the app (port_derive) and not yet run, is run in the emulator the way the app runs it on a person's
# PC - the pinned mode object, the port and gamecheck.on staged through tryit.sh install, then gamecheck.sh play
# <game> [full] - and the log lines the app reads are kept beside the verdict for game_check.read.
#
#   PORT=<port file>   the port to check (default: modes/sdk/ports/<key>.port)
#   FULL=1             gamecheck's full play (a tilted ball 2 and a ball 3 to the game's end: proves the events)
#
# Writes $JOB_OUT/check.txt (gamecheck.sh play's own lines), $JOB_OUT/mode.log (the object's log), and the
# verdict: pass when gamecheck.sh play exits 0 (the runtime hooked the game, a game started, a drain ended a ball).
# Run through rigbatch.sh: rigbatch.sh --who PAD-n <list> -- bash .../modes/newbuild/checkjob.sh
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: checkjob.sh <key> <card>}" "${2:?usage: checkjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf "the Modes tab's Check this game\n" > "$S/gamecheck.on"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
job_sleep 5
full=""; [ "${FULL:-1}" = 1 ] && full=full
bash "$MODES/gamecheck.sh" play "$GAME" $full > "$JOB_OUT/check.txt" 2>&1 < /dev/null
rc=$?
cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null
job_shot "$JOB_OUT/end.png"
case $rc in
    0) job_pass "attract=${JOB_ATTRACT_S}s check passed: $(grep -c '^\[check\]' "$JOB_OUT/check.txt") check lines" ;;
    1) job_fail "the check could not play: $(tail -1 "$JOB_OUT/check.txt")" ;;
    2) job_fail "no drain ended a ball: $(tail -1 "$JOB_OUT/check.txt")" ;;
    3) job_fail "the runtime refused the port: $(grep -m1 'PORT' "$JOB_OUT/mode.log")" ;;
    *) job_fail "gamecheck.sh exit $rc" ;;
esac
