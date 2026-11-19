#!/bin/bash
# rigrun.sh <update> <out dir> [--pad <folder>] [--port] [--switches "<n> <n> ..."] [--hold <s>]
#
# Scooby-Doo (any Spooky Unity title) or Looney Tunes (Godot, PAD-1419) on a Spooky rig of its
# own, hidden and muted, with PAD's mode runtime (PAD-1417): boots <update>, waits for the
# runtime (padunity.log "PadRuntime added", or pad_modes.log "PadModes joined") to join the game's
# modes, coins up, starts a game, plunges, pulses each switch (by number, sw.py) 2.5 s apart,
# waits --hold seconds (default 6), takes a picture of the screen and stops the game.
#
#   --pad <folder>  the runtime and modes as the Modes tab's Try it hands them over
#                   (padunity.so, PadModes.dll, modes/; Godot: pad_modes.gd, modes/) -
#                   SPK_PAD_OVERLAY; without it the update itself must load the runtime (a
#                   PAD-written update: its launch line, or its override.cfg)
#   --port          have the runtime write the title's port report (padmodes_port.json)
#   --no-runtime    a stock update (no runtime to wait for): go on once the game is in attract
#   --switches      switch numbers to pulse, 2.5 s apart; "drain" drains the ball (sw.py drain)
#   --shots "<n>:<when> ..."  take a picture <when> s after switch <n> was pulsed (once)
#
# Out: padunity.log or pad_modes.log, padmodes_port.json (--port), shot.png, shot_<n>.png, run.out.  As root in
# the rig's distro (PAD-Runtime).  Takes a rig with riglock.sh (any free slot) and lets it go.
set -u
T=$(cd "$(dirname "$0")/../.." && pwd)
UPD=${1:?usage: rigrun.sh <update> <out dir> [...]}; OUT=${2:?out dir}; shift 2
PAD=""; PORT=0; SWS=""; HOLD=6; SHOTS=""; NORT=0
while [ $# -gt 0 ]; do
    case "$1" in
        --pad) PAD=$2; shift ;;
        --port) PORT=1 ;;
        --no-runtime) NORT=1 ;;
        --switches) SWS=$2; shift ;;
        --hold) HOLD=$2; shift ;;
        --shots) SHOTS=$2; shift ;;
        *) echo "rigrun.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
mkdir -p "$OUT"
L=$T/../spike2_emu/riglock.sh
WHO=${PAD_LABEL:-PAD-1417}
S=
for k in $(seq 1 240); do      # up to an hour: a library sweep holds every rig for a while
    S=$(bash "$L" take --any "$WHO" "Spooky modes" 2>/dev/null | sed -n 's/^slot=//p')
    [ -n "$S" ] && break; sleep 15
done
[ -n "$S" ] || { echo "rigrun: no free rig"; exit 1; }
echo "rigrun: slot $S"
export PAD_SLOT=$S PAD_LABEL=$WHO PAD_HIDDEN=1 PAD_VISIBLE=0 PAD_AUDIO=0
[ -n "$PAD" ] && export SPK_PAD_OVERLAY=$PAD
[ "$PORT" = 1 ] && export SPK_PADMODES_PORT=1
. "$T/spkpath.sh"
rm -f "$OUT"/padunity.log "$OUT"/pad_modes.log "$OUT"/padmodes_port.json "$OUT"/shot*.png
# the last run on this slot left its log: a wait on it would end at once
rm -f "$SPK_RIG/logs/padunity.log" "$SPK_RIG/tmp/pad_modes.log"
timeout 900 bash "$T/watch.sh" "$UPD" > "$OUT/run.out" 2>&1 &
W=$!
LOG=$SPK_RIG/logs/padunity.log
GLOG=$SPK_RIG/tmp/pad_modes.log       # the Godot runtime's (/game/tmp/pad_modes.log)
ok=0
for i in $(seq 1 200); do
    grep -q 'PadRuntime added' "$LOG" 2>/dev/null && { ok=1; break; }
    grep -q 'PadModes joined the game' "$GLOG" 2>/dev/null && { ok=1; break; }
    [ $NORT = 1 ] && grep -q '^attract=1' "$OUT/run.out" 2>/dev/null && { ok=1; break; }
    kill -0 $W 2>/dev/null || [ -f "$LOG" ] || [ -f "$GLOG" ] || { [ $i -gt 40 ] && break; }
    sleep 3
done
if [ $ok = 1 ]; then
    echo "rigrun: the runtime joined the game's modes"
    sleep 15
    cd "$T"
    python3 sw.py coin; sleep 2; python3 sw.py start; sleep 10
    python3 sw.py plunge; sleep 6
    for n in $SWS; do
        if [ "$n" = drain ]; then python3 sw.py drain; else python3 sw.py "$n" pulse 200; fi
        for sh in $SHOTS; do
            [ "${sh%%:*}" = "$n" ] || continue
            sleep "${sh#*:}"; bash "$T/shot.sh" "$OUT/shot_$n.png" >/dev/null 2>&1
            SHOTS=$(echo " $SHOTS " | sed "s| $sh | |")
        done
        sleep 2.5
    done
    sleep "$HOLD"
    bash "$T/shot.sh" "$OUT/shot.png" >/dev/null 2>&1
else
    echo "rigrun: the runtime never joined (see run.out, padunity.log / pad_modes.log)"
fi
cp "$LOG" "$OUT/padunity.log" 2>/dev/null
cp "$GLOG" "$OUT/pad_modes.log" 2>/dev/null
cp "$SPK_RIG/logs/padmodes_port.json" "$OUT/" 2>/dev/null
grep -a -i -E 'padmodes|exception|SCRIPT ERROR|pad_modes.gd' "$SPK_RIG/player.log" 2>/dev/null | tail -20 > "$OUT/player_errors.txt"
bash "$T/killgame.sh" >/dev/null 2>&1
kill $W 2>/dev/null
bash "$L" release "$S" "$WHO" >/dev/null 2>&1
echo "rigrun: done (slot $S)"
[ $ok = 1 ]
