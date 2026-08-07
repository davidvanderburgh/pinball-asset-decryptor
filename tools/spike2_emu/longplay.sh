#!/bin/bash
# longplay.sh <gamelog> [minutes] [WxH] - PLAY THE GAME, UNATTENDED, FOR A LONG
# TIME, and shout the moment a video of size WxH starts streaming.
#
#   bash longplay.sh $HOME/gz6.log 25 520x294
#
# WHY THIS EXISTS. Item 6 (the TV inset draws pink/green noise) has a validated
# instrument and no way to point it at anything: the inset is the Planet X
# Controller TAUNT, and five earlier runs fired it ONCE in about 25 scripted
# attempts. Every one of those attempts was a short burst of switches followed
# by a restart, because they were hunting a TRIGGER SWITCH.
#
# THE SWITCH HUNT IS THE THING THIS SCRIPT GIVES UP ON, deliberately. The
# handoff already records that full sweeps of 46-86, the scoop held like a real
# ball device, the shield targets, the maser, the spinners, the action button
# and cadences from 0.3 s to 1.6 s all failed. A taunt is not a shot award; the
# far more likely shape is "somewhere in a ball that has been in play a while,
# with enough progress made". That is not a switch to find, it is TIME AND
# VARIETY to accumulate - so this keeps ONE ball alive and keeps making
# different shots, for as long as it is given.
#
# KEEPING THE BALL ALIVE IS FREE HERE, and that is the whole trick. There is no
# physics: a ball drains only because something pokes a drain switch. So the
# outlanes (55, 58) and the trough (66-72) are simply never poked, and a ball
# plunged in the first ten seconds is still in play half an hour later. A real
# player cannot do that. Nor is TILT reachable - 38 and 45 are excluded for the
# same reason, and a tilt would end the ball this is trying to preserve.
#
# WHAT IT DOES ON A HIT: says so on stdout, waits 2 s so padglhost's automatic
# "new video size" burst (20 frames) has been written, then grabs the real
# Windows-side window with shotwin.py. It keeps playing afterwards rather than
# stopping, because a second sighting is worth more than a first.
#
# IT DOES NOT START OR STOP THE GAME. Run watch.sh separately and give this its
# log; that keeps the "never run two measurement runs at once" rule enforceable
# by looking at one thing. It exits by itself when the guest goes away.
set -u

S=$(cd "$(dirname "$0")" && pwd)
. "$S/gamestate.sh"

LOG=${1:-$HOME/gzwatch.log}
MINS=${2:-25}
WANT=${3:-520x294}
OUTDIR=${LONGPLAY_OUT:-/tmp/longplay}
mkdir -p "$OUTDIR"

say() { printf '[longplay] %s\n' "$*"; }

# THE SHOT SETS. Names from the playfield map in the handoff (PAD_SW_DUMP).
# Grouped by what they mean to the game, because a random walk over all of them
# looks nothing like play: real balls come back to a flipper between shots.
RAMPS=(73 81 82 74 75 77 76 53)      # L/R ramp, big loop in/out, building, Godzilla tgt, scoop
TARGETS=(78 79 80 85 86 48)          # Powerline L/C/R, shield L/R, maser
SPINNERS=(47 83 84)
JOSTLE=(49 63 64)                    # pop bumper, right/left slingshot
RETURNS=(56 57 46 50 51)             # return lanes, skill shot, mecha exits
# DELIBERATELY ABSENT: 55/58 outlanes and 66-72 trough (they drain the ball),
# 38/45 tilt (they end it), 33 coin door (it must stay shut or 48V drops out),
# 62 shooter lane and 36 start (plunge.py owns those).

pick() { local -n arr=$1; echo "${arr[$((RANDOM % ${#arr[@]}))]}"; }

# PAD_SW_SRC=g tags every shot this script makes as UNATTENDED GAMEPLAY in the
# guest's [sw] log, so a replay can tell it from a human at the keyboard and
# from the rig's own boot press. See padsw.h; swreplay.py --list groups by it.
poke() { PAD_SW_SRC=g python3 "$S/swpoke.py" "$1" "${2:-90}" >/dev/null 2>&1; }

# The same union as padpath.sh's pad_guest_up (this script sources only
# gamestate.sh): comm=game on every platform measured; the interpreter names
# are platform details - arm-binfmt is WSL's, qemu-arm a container's.
guest_up() { pgrep -x game >/dev/null 2>&1 || pgrep -f 'arm-binfmt|qemu-arm' >/dev/null 2>&1; }

# One ball into play. plunge.py takes the lowest trough ball still held, so a
# `reset` first is what makes this repeatable across blocks.
#
# `game` AND NOT `start`, AND THIS IS THE WHOLE REASON THIS SCRIPT USED TO PLAY
# TO AN EMPTY ROOM. A machine with no credits ignores the Start button
# SILENTLY: the switch genuinely reaches the game (+36/-36 logged at the
# asked-for duration) and no game begins. Every instrument the rig owns reports
# the press as delivered, so "the press worked" and "a game started" look like
# one claim. Three Start presses over ten minutes once left a run in attract
# mode while ~1300 scripted switch pokes landed on an attract screen, and the
# scene this script exists to provoke cannot appear when there is no game.
# `plunge.py game` puts a coin in first.
newball() {
    python3 "$S/plunge.py" reset >/dev/null 2>&1; sleep 1
    python3 "$S/plunge.py" game  >/dev/null 2>&1; sleep 2
}

# COUNT the sightings, never test for presence. The line stays in the log for
# the rest of the run, so a `grep -q` would report the first hit and then be
# permanently true - which reads as "still happening" and hides every later
# sighting. Later sightings are the valuable ones: they are what turns a lucky
# reproduction into a repeatable one.
SEEN=0
hit_check() {
    local n
    n=$(grep -ac "streaming $WANT" "$LOG" 2>/dev/null); n=${n:-0}
    [ "$n" -gt "$SEEN" ] || return 1
    SEEN=$n
    say "*** $WANT IS STREAMING - sighting $SEEN at $(date +%H:%M:%S) ***"
    # padglhost bursts 20 frames by itself the first time a new size appears;
    # give it a moment to have done so before grabbing the composited window.
    sleep 2
    local png="$OUTDIR/hit${SEEN}_$(date +%H%M%S).png"
    if command -v python.exe >/dev/null 2>&1; then
        python.exe "$(wslpath -w "$S/shotwin.py")" "Spike 2 emulator" \
            "$(wslpath -w "$png")" 2>&1 | sed 's/^/[longplay]   /'
    else
        say "  no python.exe on PATH - no window grab (the PNG burst is on disk)"
    fi
    return 0
}

say "log=$LOG  cap=${MINS}m  watching for '$WANT'  out=$OUTDIR"

# Wait for the game to be past Tech Alerts. autoattract.sh does the pressing;
# this only waits for its result, using the ONE definition of that state.
for _ in $(seq 1 600); do
    guest_up || { say "the guest is not running - nothing to play"; exit 1; }
    gs_past_alerts "$LOG" && break
    sleep 1
done
gs_past_alerts "$LOG" || { say "never reached attract; giving up"; exit 1; }
say "attract reached; starting to play"

DEADLINE=$((SECONDS + MINS * 60))
BLOCK=0
while [ "$SECONDS" -lt "$DEADLINE" ] && guest_up; do
    BLOCK=$((BLOCK + 1))
    say "block $BLOCK: new ball ($(( (DEADLINE - SECONDS) / 60 ))m left)"
    newball
    # Five minutes of continuous, varied shot-making on one ball.
    BLOCK_END=$((SECONDS + 300))
    while [ "$SECONDS" -lt "$BLOCK_END" ] && [ "$SECONDS" -lt "$DEADLINE" ] \
          && guest_up; do
        # A shot, then the ball coming back to a flipper, then some jostle.
        poke "$(pick RAMPS)" 150
        sleep 0.5
        poke "$(pick RETURNS)" 80
        sleep 0.4
        case $((RANDOM % 4)) in
            0) poke "$(pick TARGETS)" 70 ;;
            1) poke "$(pick SPINNERS)" 60; sleep 0.15
               poke "$(pick SPINNERS)" 60 ;;
            2) poke "$(pick JOSTLE)" 60 ;;
            3) poke "$(pick RAMPS)" 150 ;;
        esac
        sleep 0.6
        hit_check || true
    done
done

say "done: ${BLOCK} block(s), $SEEN sighting(s) of $WANT"
[ "$SEEN" -gt 0 ] && say "captures in $OUTDIR"
exit 0
