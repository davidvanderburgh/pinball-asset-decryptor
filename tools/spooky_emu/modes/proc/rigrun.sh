#!/bin/bash
# rigrun.sh <game-code .pkg> <out dir> [--pad <folder>] [--port] [--switches "<name> ..."] [--hold <s>]
#           [--shots "<name>:<when> ..."]
#
# Rick and Morty (a Spooky P-ROC title) on a P-ROC rig of its own, hidden and muted, with PAD's
# mode runtime (PAD-1420, padmodes_proc.py): boots <pkg> (proc/watch.sh: prepare.py + run_game.sh),
# waits for the runtime (pad/padmodes.log "PadModes joined the game"), coins up, starts a game,
# launches the ball, taps each switch (by the machine yaml's name, sw.sh) 2.5 s apart, waits
# --hold seconds (default 6), takes a picture of the screen and stops the game.
#
#   --pad <folder>  the runtime and modes as the Modes tab's Try it hands them over
#                   (padmodes_proc.py, modes/) - SPK_PAD_OVERLAY; without it the .pkg itself must
#                   load the runtime (a PAD-written one: its pad/ and its config.yaml line)
#   --port          have the runtime write the title's port report (padmodes_port.json)
#   --switches      switch names to tap, 2.5 s apart; "drain" drains the ball (sw.sh drain),
#                   "wait:<s>" waits
#   --shots "<name>:<when> ..."  take a picture <when> s after switch <name> was tapped (once)
#
# Out: padmodes.log, padmodes_port.json (--port), shot.png, shot_<name>.png, run.out, game_tail.txt.
# As root in the rig's distro.  Takes a rig with riglock.sh (any free slot) and lets it go.
set -u
M=$(cd "$(dirname "$0")" && pwd)
P=$(cd "$M/../../proc" && pwd)
PKG=${1:?usage: rigrun.sh <pkg> <out dir> [...]}; OUT=${2:?out dir}; shift 2
PAD=""; PORT=0; SWS=""; HOLD=6; SHOTS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --pad) PAD=$2; shift ;;
        --port) PORT=1 ;;
        --switches) SWS=$2; shift ;;
        --hold) HOLD=$2; shift ;;
        --shots) SHOTS=$2; shift ;;
        *) echo "rigrun.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
mkdir -p "$OUT"
L=$M/../../../spike2_emu/riglock.sh
WHO=${PAD_LABEL:-PAD-1420}
S=
for k in $(seq 1 240); do
    S=$(bash "$L" take --any "$WHO" "Spooky P-ROC modes" 2>/dev/null | sed -n 's/^slot=//p')
    [ -n "$S" ] && break; sleep 15
done
[ -n "$S" ] || { echo "rigrun: no free rig"; exit 1; }
echo "rigrun: slot $S"
export PAD_SLOT=$S PAD_LABEL=$WHO PAD_HIDDEN=1 PAD_VISIBLE=0 PAD_AUDIO=0
[ -n "$PAD" ] && export SPK_PAD_OVERLAY=$PAD
[ "$PORT" = 1 ] && export SPK_PADMODES_PORT=1
. "$P/sppath.sh"
rm -f "$OUT"/padmodes.log "$OUT"/padmodes_port.json "$OUT"/shot*.png
# the rig's lease lapses 5 minutes after its last use: keep it while this runs
( while sleep 60; do bash "$L" use "$S" "$WHO" "Spooky P-ROC modes" >/dev/null 2>&1 || true; done ) &
KEEP=$!
timeout 900 bash "$P/watch.sh" "$PKG" > "$OUT/run.out" 2>&1
echo "rigrun: watch.sh rc=$?"
DIR=$(case "$(cat "$SPP_RIG/title" 2>/dev/null)" in ac) echo code ;; *) echo RickAndMorty ;; esac)
LOG=$SPP_RIG/game/$DIR/pad/padmodes.log
case "$(cat "$SPP_RIG/title" 2>/dev/null)" in
    ac) LAUNCH=launchBallButton ;;
    *) LAUNCH=launchBall ;;
esac
ok=0
for i in $(seq 1 60); do
    grep -q 'PadModes joined the game' "$LOG" 2>/dev/null && { ok=1; break; }
    spp_alive game || break
    sleep 2
done
if [ $ok = 1 ]; then
    echo "rigrun: the runtime joined the game"
    sleep 8
    bash "$P/sw.sh" tap coin1 150; sleep 2
    bash "$P/sw.sh" tap startButton 200; sleep 8
    bash "$P/sw.sh" tap "$LAUNCH" 200; sleep 5
    for n in $SWS; do
        case "$n" in
            drain) bash "$P/sw.sh" drain ;;
            wait:*) sleep "${n#wait:}" ;;
            *) bash "$P/sw.sh" tap "$n" 150 ;;
        esac
        for sh in $SHOTS; do
            [ "${sh%%:*}" = "$n" ] || continue
            sleep "${sh#*:}"; bash "$P/shot.sh" "$OUT/shot_$n.png" >/dev/null 2>&1
            SHOTS=$(echo " $SHOTS " | sed "s| $sh | |")
        done
        case "$n" in wait:*) ;; *) sleep 2.5 ;; esac
    done
    sleep "$HOLD"
    bash "$P/shot.sh" "$OUT/shot.png" >/dev/null 2>&1
else
    echo "rigrun: the runtime never joined (see run.out, game_tail.txt)"
fi
cp "$LOG" "$OUT/padmodes.log" 2>/dev/null
cp "$SPP_RIG/padmodes_port.json" "$OUT/" 2>/dev/null
tail -40 "$SPP_RIG/game.out" > "$OUT/game_tail.txt" 2>/dev/null
grep -a -E "Traceback|Error|padmodes" "$SPP_RIG/game.out" 2>/dev/null | tail -20 > "$OUT/game_errors.txt"
bash "$P/killgame.sh" >/dev/null 2>&1
kill $KEEP 2>/dev/null
bash "$L" release "$S" "$WHO" >/dev/null 2>&1
echo "rigrun: done (slot $S)"
[ $ok = 1 ]
