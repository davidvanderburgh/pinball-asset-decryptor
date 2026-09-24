#!/bin/bash
# gamecheck.sh - the rig side of the Modes tab's Check this game.
#
#   gamecheck.sh play <game>   in the RUNNING game, started with the pinned mode object and a
#                              staged gamecheck.on (tryit.sh install): wait for the object's
#                              "check ready", start a game, press each playfield switch of
#                              <game>'s switch list once, with a mark before each (the object
#                              logs the marks, the shots, the events and the end of ball), then
#                              drain until a ball ends. Prints "[check] ..." lines as it goes.
#                              Exit 0 when a ball ended, 1 when it could not play, 2 when no
#                              drain ended a ball, 3 when the runtime refused the port
#   gamecheck.sh log           the lines of this run's $ROOT/dump/mode.log the app reads
#
# It only presses switches and reads the log: nothing is installed or removed here. What a
# press is, and a drain, are swpoke.py's and plunge.py's (the same shared switch block the
# keyboard uses). Left out of the presses: the cabinet (coin, start, service, tilt, volume), the
# trough, flippers, the shooter lane, outlanes, ball locks and mechanism positions - a press
# there changes the ball count or the machine, not a shot.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RIG=$(cd "$HERE/.." && pwd)
. "$RIG/padpath.sh"
DUMP=$ROOT/dump
LOG=$DUMP/mode.log
AUTO=$PAD_HOME/padauto.log

say() { echo "[check] $*"; }
die() { say "$*"; exit 1; }
game_up() { pgrep -x game > /dev/null; }
count() { grep -ac -- "$1" "$LOG" 2>/dev/null || true; }
# wait_for <seconds> <extended regex> <file>: 0 when a line matches, 1 at the time limit or
# when the game is gone
wait_for() {
    local end=$(( $(date +%s) + $1 ))
    while [ "$(date +%s)" -lt "$end" ]; do
        grep -aEq -- "$2" "$3" 2>/dev/null && return 0
        game_up || return 1
        sleep 0.5
    done
    return 1
}
press() {   # press <id>: a mark the object logs, then a 150 ms press
    echo "$1" > "$DUMP/census.mark"
    sleep 0.45
    python3 "$RIG/swpoke.py" "$1" 150 > /dev/null 2>&1 || say "swpoke $1 failed"
    sleep 1.1
}
#: a switch the check leaves alone, by its name in the switch list
skipped() {
    echo "$1" | grep -qiE 'TROUGH|FLIPPER|SHOOTER|COIN|SERVICE|^DIP|START|TILT|DOOR|VOLUME|HEADPHONE|ENCODER|QR SCANNER|MOTOR|LOCKDOWN|LOCK [0-9]|TICKET|OUTLANE|OUT LANE|EOS|DETECT|BUTTON|POSITION|HOME|INTERLOCK|OPTO BOARD|JAM'
}

cmd=${1:-}
case "$cmd" in
    play)
        GAME=${2:-}
        case "$GAME" in ""|*[!abcdefghijklmnopqrstuvwxyz0123456789_]*) die "a game is [a-z0-9_] only, not '$GAME'" ;; esac
        LIST=$DUMP/tables/$GAME/switch_list.txt
        # the app calls this once the Emulate tab's run is up, which is before the rig has
        # mounted the card and started the game: wait for the game, and fail only on a game
        # that was up and went away (tryit.sh install cleared the last run's mode.log)
        say "waiting for the game to boot"
        end=$(( $(date +%s) + 240 ))
        seen=""
        while :; do
            if grep -aq "NOT THIS GAME'S PORT" "$LOG" 2>/dev/null; then
                say "$(grep -a "NOT THIS GAME'S PORT" "$LOG" | tail -n 1)"
                exit 3
            fi
            grep -aq "check ready" "$LOG" 2>/dev/null && break
            if game_up; then
                seen=1
            elif [ -n "$seen" ]; then
                die "the game stopped while it booted"
            fi
            [ "$(date +%s)" -lt "$end" ] || die "the game did not say it was ready in 4 minutes (is the check object in?)"
            sleep 0.5
        done
        grep -a "armed: " "$LOG" | tail -n 1 | sed -E 's/^ *[0-9]* *(\[pad\] )?/[check] /'
        # the attract loop: the rig's autoattract clears the Tech Alerts first; a Start before
        # then is ignored
        wait_for 90 "past Tech Alerts|standing down|did not clear|gave up|already past" "$AUTO" \
            || say "(the rig never said the Tech Alerts were cleared; starting anyway)"
        game_up || die "the game stopped before a game could start"
        sleep 3
        [ -f "$LIST" ] || die "the rig has no switch list for $GAME ($LIST)"
        say "starting a game"
        python3 "$RIG/plunge.py" game > /dev/null 2>&1 || say "plunge.py game said no"
        sleep 3
        ids=()
        while read -r id _num _node _bit name; do
            case "$id" in ""|\#*|*[!0-9]*) continue ;; esac
            skipped "$name" && continue
            ids+=("$id")
            say "switch $id $name"
        done < "$LIST"
        [ "${#ids[@]}" -gt 0 ] || die "no playfield switch in $LIST"
        [ "${#ids[@]}" -le 90 ] || ids=("${ids[@]:0:90}")
        say "pressing ${#ids[@]} playfield switches, one at a time"
        k=0
        for id in "${ids[@]}"; do
            game_up || die "the game stopped during the presses"
            press "$id"
            k=$((k + 1))
            [ $((k % 10)) -eq 0 ] && say "pressed $k of ${#ids[@]}"
        done
        # the ball saver can give the first drain back (and then the rig counts two balls in
        # play), so drain until the object logs an end of ball
        echo drain > "$DUMP/census.mark"
        sleep 0.6
        before=$(count "check ball end")
        for n in 1 2 3 4; do
            game_up || die "the game stopped before a ball could drain"
            say "drain $n"
            python3 "$RIG/plunge.py" drain > /dev/null 2>&1
            end=$(( $(date +%s) + 7 ))
            while [ "$(date +%s)" -lt "$end" ]; do
                if [ "$(count "check ball end")" -gt "$before" ]; then
                    say "a ball ended"
                    # the bonus (its end is an event on most builds), and the next ball's start
                    wait_for 20 "check event bonus_end" "$LOG" || true
                    sleep 2
                    say "done"
                    exit 0
                fi
                sleep 0.5
            done
        done
        say "no drain ended a ball"
        exit 2
        ;;
    log)
        [ -f "$LOG" ] || die "no mode.log yet"
        grep -a "check \|armed: \|NOT THIS GAME\|\[pad\] port \|\[pad\] events: " "$LOG"
        ;;
    *)
        die "usage: gamecheck.sh play <game> | log"
        ;;
esac
