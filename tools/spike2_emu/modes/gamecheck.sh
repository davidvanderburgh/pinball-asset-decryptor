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
#   gamecheck.sh play <game> full   the same, then a tilted ball 2 and a ball 3 played to the
#                              game's end (about three minutes more): for proving a port's events
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

#: the rig's ball feeder answers the game's trough eject; on a title whose device table has no
#: eject coil (Batman 66) nothing does, so the check serves each ball by hand (plunge.py serve:
#: trough -> shooter lane -> launched). Never both: a served ball on a fed title is a second ball
nofeed() { grep -aq "eject coil NOT IN THE DEVICE TABLE\|nothing to do on this title" "$PAD_HOME/padball.log" 2>/dev/null; }
launch_ball() {
    if nofeed; then
        python3 "$RIG/plunge.py" serve > /dev/null 2>&1 || say "plunge.py serve said no"
    else
        python3 "$RIG/plunge.py" plunge > /dev/null 2>&1
    fi
}
#: coins, Start, and the ball served by hand on a title with no feeder. A card not on free play
#: wants credits: a dollar a game is four coins (Batman 66), so eight go in (spares do no harm)
start_game() {
    python3 "$RIG/plunge.py" coin 8 > /dev/null 2>&1 || say "plunge.py coin said no"
    python3 "$RIG/plunge.py" game > /dev/null 2>&1
    nofeed && { say "no ball feeder on this title: serving the ball by hand"; sleep 2; launch_ball; }
}
#: Guided Setup (a first boot's menu): walk its red row down with SERVICE PLUS until the last row,
#: Save & Exit, is the red one (menurow.py reads a glshot.sh frame), then SERVICE SELECT. Measured
#: on Avengers LE 1.09, 2026-09-24. 1 when the screen is not that menu.
#: guided_setup <backs>: a row's EDITOR (Start or Select opened it: the language list, its title
#: previewing each language as PLUS walks it) is not the menu; up to <backs> SERVICE BACKs close it,
#: leaving the setting as it was, and the walk goes on from the menu
guided_setup() {
    local plus sel back k state shot backs=${1:-0}
    plus=$(awk '!/^#/ && toupper($0) ~ /SERVICE PLUS/ {print $1; exit}' "$LIST")
    sel=$(awk '!/^#/ && toupper($0) ~ /SERVICE SELECT/ {print $1; exit}' "$LIST")
    back=$(awk '!/^#/ && toupper($0) ~ /SERVICE BACK/ {print $1; exit}' "$LIST")
    [ -n "$plus" ] && [ -n "$sel" ] || return 1
    shot=$(mktemp "${TMPDIR:-/tmp}/gamecheck.XXXXXX.png")
    for k in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
        (cd "$RIG" && bash glshot.sh "$shot" > /dev/null 2>&1) || break
        state=$(python3 "$RIG/menurow.py" "$shot" 2>/dev/null)
        case "$state" in
            "menu last=yes")
                python3 "$RIG/swpoke.py" "$sel" 300 > /dev/null 2>&1
                sleep 4
                rm -f "$shot"
                return 0 ;;
            "menu last=no")
                python3 "$RIG/swpoke.py" "$plus" 300 > /dev/null 2>&1
                sleep 1.2 ;;
            *)
                if [ "$backs" -gt 0 ] && [ -n "$back" ]; then
                    backs=$((backs - 1))
                    python3 "$RIG/swpoke.py" "$back" 300 > /dev/null 2>&1
                    sleep 1.5
                    continue
                fi
                cp "$shot" "$DUMP/gamecheck.png" 2>/dev/null   # the frame it judged, for a person
                break ;;
        esac
    done
    rm -f "$shot"
    return 1
}
#: drain until the object logs one more end of ball: 0 when one did. A drain inside the ball saver
#: comes back as a new ball, and a ball drained before any playfield switch since its launch is given
#: back every time (John Wick, Venom), so after a saved drain three switches are hit and the saver
#: is waited out before the next one
drain_until_end() {
    local before n end id
    echo drain > "$DUMP/census.mark"
    sleep 0.6
    before=$(count "check ball end")
    for n in 1 2 3 4 5; do
        game_up || return 1
        say "drain $n"
        python3 "$RIG/plunge.py" drain > /dev/null 2>&1
        end=$(( $(date +%s) + 7 ))
        while [ "$(date +%s)" -lt "$end" ]; do
            [ "$(count "check ball end")" -gt "$before" ] && return 0
            sleep 0.5
        done
        [ "$n" -ge 2 ] || continue
        say "the ball saver gave it back: playing past it"
        for id in "${ids[@]:0:3}"; do press "$id"; done
        sleep 15
        echo drain > "$DUMP/census.mark"
    done
    return 1
}

cmd=${1:-}
case "$cmd" in
    play)
        GAME=${2:-}
        FULL=${3:-}
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
        # a title's FIRST boot on this rig: mktables writes its switch list a minute or so in
        # (from the shim's dump, or read out of the program by swelf.py)
        wait_for 150 "" "$LIST" || [ -f "$LIST" ] || die "the rig has no switch list for $GAME ($LIST)"
        sleep 3
        # a first boot opens Guided Setup: leave it BEFORE Start, which there opens a row's editor
        guided_setup 0 && { say "first boot: left Guided Setup by Save & Exit"; sleep 3; }
        # a Start the game ignores (a service screen the rig's autoattract opened for a moment, a
        # menu a first boot left up) is tried again, up to three times, leaving any menu first
        started=""
        for attempt in 1 2 3; do
            say "starting a game"
            start_game
            wait_for 12 "in_game 0 -> 1" "$LOG" && { started=1; break; }
            if guided_setup 2; then
                say "left Guided Setup by Save & Exit"
                sleep 3
            else
                say "no game yet (try $attempt)"
                sleep 8
            fi
        done
        [ -n "$started" ] || die "no game started after three tries, and the screen is not a menu the check can leave"
        sleep 2
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
        drain_until_end || { say "no drain ended a ball"; exit 2; }
        say "a ball ended"
        # the bonus (its end is an event on most builds), and the next ball's start
        wait_for 20 "check event bonus_end" "$LOG" || true
        sleep 2
        if [ "$FULL" = full ]; then
            # ball 2: a tilt (three pendulum hits, 4.5 s apart), then its drain; ball 3: played
            # past the ball saver and drained, which ends the game
            TILT=$(awk '!/^#/ && toupper($0) ~ /TILT/ && toupper($0) !~ /SLAM/ {print $1; exit}' "$LIST")
            wait_for 25 "check event ball_start" "$LOG" || true
            launch_ball
            sleep 2
            for id in "${ids[@]:0:10}"; do press "$id"; done
            if [ -n "$TILT" ]; then
                say "tilting ball 2 (switch $TILT)"
                for k in 1 2 3; do echo "tilt$k" > "$DUMP/census.mark"; sleep 0.45
                    python3 "$RIG/swpoke.py" "$TILT" 150 > /dev/null 2>&1; sleep 4; done
                sleep 4
            fi
            drain_until_end || say "no drain ended ball 2"
            say "ball 2 ended"
            sleep 20
            launch_ball
            sleep 2
            say "ball 3: playing past the ball saver"
            for id in "${ids[@]}"; do game_up || break; press "$id"; done
            drain_until_end || say "no drain ended ball 3"
            wait_for 45 "check event game_over" "$LOG" && say "the game ended"                 || say "(no game_over event after ball 3)"
        fi
        say "done"
        exit 0
        ;;
    log)
        [ -f "$LOG" ] || die "no mode.log yet"
        grep -a "check \|armed: \|NOT THIS GAME\|\[pad\] port \|\[pad\] events: " "$LOG"
        ;;
    *)
        die "usage: gamecheck.sh play <game> [full] | log"
        ;;
esac
