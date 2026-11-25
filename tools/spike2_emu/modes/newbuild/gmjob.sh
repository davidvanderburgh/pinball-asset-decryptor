#!/bin/bash
# gmjob.sh <key> <card> - a mode held off by / in the place of / after / with one of the game's own modes on a new
# build (PAD-1555; PAD-420's stack, PAD-710's place, PAD-747's done and PAD-1537's with proofs, in one game).
#
#   ID=<mode>       the game's mode number (the earlier build's proof's: King Kombos 27, Super Reactor 19, ...)
#   SO=<object>     built with modes/sdk/gamemode_test_mode.c (build_mode.sh -o gm.so mode_file.c gamemode_test_mode.c)
#   PLAIN=1         a plain-C title (PAD_TEST_PLAIN_START: its start takes no object)
#   PORT=<port>     the port (default: modes/sdk/ports/<key>.port)
#   PHASES="..."    which of stack, place, with, in that order (default all three: stack first, on a mode the ball
#                   has not played yet)
#   STACK_ID=<mode> the game's battle or multiball for the stack phase (a `stack no` mode waits only for those;
#                   default ID)
#   WITH_WAIT=<s>   game seconds for the game's mode to stop in the with phase (default 40; a plain-C mode's own clock)
#
# stack: `stack no`; the game's start of STACK_ID, then the mode asked for. Pass: STACK TEST not started (...): ... is
#   running.
# place + done: `in_place_of <ID>` (8 s) and `starts_on completed 1`; the game's start of ID (gm.start). Pass: the
#   place line, `done: player 1 completed the game's ...`, and DONE TEST START.
# with: `starts_on with_game <ID>`; the game's start, then its stop (gm.stop; a plain-C mode's own clock). Pass: WITH
#   TEST START (the game's ... started) and WITH TEST END.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: gmjob.sh <key> <card>}" "${2:?usage: gmjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${SO:-}" ] && [ -n "${ID:-}" ] || job_fail "needs PORT, SO and ID"
PHASES=${PHASES:-stack place with}
cfg() { printf 'name %s\ngame_modes stack\nseconds %s\ntrigger 0x1 99\nshots 0xffffffff\naward 100\n%s\n' "$1" "$2" "$3"; }
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SO" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
cfg "IDLE TEST" 5 "" > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
[ "${PLAIN:-0}" = 1 ] && export PAD_TEST_PLAIN_START=1
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 20
# the ball scores first: until the player's score moves (and 2 s on) a mode of the game's that starts is its base play,
# never counted by `stack no` (pad_mode_runtime.c stock_base_until) - D&D's and Foo Fighters' balls score nothing alone
pat=$(grep -o "grep -qiE '[^']*'" "$MODES/gamecheck.sh" | head -1 | sed "s/^grep -qiE '//; s/'\$//")
while read -r sw _num _node _bit name; do
    case "$sw" in ""|\#*|*[!0-9]*) continue ;; esac
    echo "$name" | grep -qiE "$pat" && continue
    job_press "$sw"; job_sleep 0.5
    n=$((${n:-0} + 1)); [ "$n" -ge 6 ] && break
done < "$DUMP/tables/$GAME/switch_list.txt"
job_sleep 4
place= done_= dstart= wstart= wend= stack=
case " $PHASES " in *" stack "*)
    cfg "STACK TEST" 10 "stack no" > "$DUMP/mode.cfg"
    job_sleep 3
    # asked once with nothing of the game's running: the runtime's first walk of the game's modes takes what runs then
    # as base play (D&D's, Foo Fighters' modes seen first only after their start read as base play), as PAD-420's did
    bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
    job_sleep 3
    bash "$MODES/tryit.sh" stop > /dev/null 2>&1 < /dev/null
    job_sleep 3
    printf '%s' "${STACK_ID:-$ID}" > "$DUMP/gm.start"
    job_sleep 2
    mark=$(grep -c "" "$log")
    bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
    job_sleep 4
    stack=$(tail -n +"$((mark + 1))" "$log" | grep -a -m1 -Eo 'STACK TEST (not started \([^)]*\): .* is running|START \([^)]*\))')
    job_sleep 12
    ;;
esac
case " $PHASES " in *" place "*)
    cfg "PLACE TEST" 8 "in_place_of $ID" > "$DUMP/mode.cfg"
    cfg "DONE TEST" 5 "starts_on completed 1" > "$DUMP/mode1.cfg"
    job_sleep 3
    printf '%s' "$ID" > "$DUMP/gm.start"
    job_wait_log "$log" 'DONE TEST START' 30 || true
    job_sleep 6
    place=$(grep -a -m1 -Eo 'PLACE TEST: the game started its .* \(mode [0-9]+\) - this starts now in its place' "$log")
    done_=$(grep -a -m1 -Eo 'done: player [0-9]+ completed the game.s [^(]*\(mode [0-9]+' "$log")
    dstart=$(grep -a -m1 -Eo 'DONE TEST START \([^)]*\)' "$log")
    rm -f "$DUMP/mode1.cfg"
    ;;
esac
case " $PHASES " in *" with "*)
    cfg "WITH TEST" 300 "starts_on with_game $ID" > "$DUMP/mode.cfg"
    job_sleep 3
    printf '%s' "$ID" > "$DUMP/gm.start"
    job_wait_log "$log" 'WITH TEST START' 15 || true
    job_sleep 3
    [ "${PLAIN:-0}" = 1 ] || printf '%s' "$ID" > "$DUMP/gm.stop"
    job_wait_log "$log" 'WITH TEST END' "${WITH_WAIT:-40}" || true
    wstart=$(grep -a -m1 -Eo 'WITH TEST START \([^)]*\)' "$log")
    wend=$(grep -a -m1 -Eo 'WITH TEST END \([^)]*\)' "$log")
    ;;
esac
cp "$log" "$JOB_OUT/mode.log"
printf 'stack: %s\nplace: %s\ndone: %s | %s\nwith: %s | %s\n' "$stack" "$place" "$done_" "$dstart" "$wstart" "$wend" > "$JOB_OUT/verdicts.txt"
bad=""
case " $PHASES " in *" stack "*) echo "$stack" | grep -q "not started" || bad="$bad stack";; esac
case " $PHASES " in *" place "*) [ -n "$place" ] || bad="$bad place"; [ -n "$done_" ] && [ -n "$dstart" ] || bad="$bad done";; esac
case " $PHASES " in *" with "*) [ -n "$wstart" ] && [ -n "$wend" ] || bad="$bad with";; esac
[ -z "$bad" ] || job_fail "not proven:$bad - $(tr '\n' ';' < "$JOB_OUT/verdicts.txt" | cut -c1-300)"
job_pass "attract=${JOB_ATTRACT_S}s $PHASES: $(tr '\n' ';' < "$JOB_OUT/verdicts.txt" | cut -c1-400)"
