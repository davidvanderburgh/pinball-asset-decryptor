#!/bin/bash
# replayrun.sh - play a recorded run back on a rig of its own, exactly (PAD-764).
#
#   wsl -u root -e env HOME=<rig owner's home> bash replayrun.sh <recording> [--slot N] [--after S] [--out DIR]
#                                                               [--who LABEL] [--keep-nvram] [-- <swreplay.py options>]
#
#   <recording>   a folder runrec.py made: <logdir>/runs/<when>-<title> (`runrec.py list <logdir>` names them;
#                 the Emulate tab's are under the rig owner's home, ~/runs)
#   --slot N      the rig to replay on (default: any free one; never rig 0, whose NVRAM is the player's own)
#   --after S     how long the game goes on after the last recorded change before it is stopped (default 10 s)
#   --out DIR     where the replay's log, glass shots and the game's own logs go (default /var/tmp/replay-<name>)
#   --who LABEL   the rig board's name for the run (default PAD-replay); PAD_LABEL wins
#   --keep-nvram  replay on the rig's own NVRAM instead of the recording's: what PAD-733's replay did, and how far
#                 the game goes the same before the machine's memory makes it differ
#
# WHAT IT DOES. The recording holds the title's NVRAM as the game found it when the run began, the launch's own
# modes, its settings and the switch log (runrec.py). So: take a free rig, put that NVRAM in its place of the
# title's, install the modes, boot the same card with the same settings - hidden, muted, the ball feeder and
# autoattract OFF, because every edge they made is in the record - and hand the game every switch at the game time
# it happened (swreplay.py). The rig is stopped and given back after --after seconds, with a shot of the glass at
# the end and the game's logs in --out.
#
# Run it in the distro the recording names (run.json "host"): the card and edits paths are that distro's. It warns
# when the card or the project's edits have changed since the run, which an exact replay cannot survive.
set -u
RIG=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REC=${1:?usage: replayrun.sh <recording> [--slot N] [--after S] [--out DIR]}
shift
REC=${REC%/}
WANT="" AFTER=10 OUT="" WHO=${PAD_LABEL:-PAD-replay} XOPT=() KEEPNV=""
while [ $# -gt 0 ]; do
    case "$1" in
        --slot) WANT=$2; shift 2 ;;
        --after) AFTER=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        --who) WHO=$2; shift 2 ;;
        --keep-nvram) KEEPNV=1; shift ;;
        --) shift; XOPT=("$@"); break ;;
        *) echo "replayrun: unknown option $1" >&2; exit 2 ;;
    esac
done
[ -f "$REC/run.json" ] || { echo "replayrun: $REC is not a recording (no run.json)" >&2; exit 2; }
[ -f "$REC/switches.log" ] || { echo "replayrun: $REC has no switch log yet (is that run still going?)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "replayrun: run it as root (wsl -u root), like every rig job" >&2; exit 2; }
[ "$WANT" = 0 ] && { echo "replayrun: not on rig 0 - its NVRAM is the player's own, and a replay replaces it" >&2; exit 2; }
NAME=$(basename "$REC")
OUT=${OUT:-/var/tmp/replay-$NAME}
mkdir -p "$OUT"
T0=$(date +%s%3N); ts() { echo "[replay $(( $(date +%s%3N) - T0 )) ms] $*" | tee -a "$OUT/replay_steps.txt"; }

ENVS=$(python3 "$RIG/runrec.py" env "$REC" 2> "$OUT/notes.txt") || { cat "$OUT/notes.txt"; exit 1; }
sed 's/^/  /' "$OUT/notes.txt"

if [ -n "$WANT" ]; then out=$(bash "$RIG/riglock.sh" take --slot "$WANT" "$WHO" "replay $NAME" 2>&1)
else out=$(bash "$RIG/riglock.sh" take --any "$WHO" "replay $NAME" 2>&1); fi
SLOT=$(printf '%s\n' "$out" | grep -o 'slot=[0-9]*' | head -1 | cut -d= -f2)
if [ -z "$SLOT" ] || [ "$SLOT" = 0 ]; then echo "$out"; echo "replayrun: no rig of its own (slot '$SLOT')" >&2; exit 1; fi
release() { bash "$RIG/riglock.sh" release "$SLOT" "$WHO" > /dev/null 2>&1; }
unset PAD_ROOT PAD_TABLES PAD_LOGDIR PAD_CARDS PAD_PATHS_SLOT
export PAD_SLOT=$SLOT PAD_LABEL=$WHO
bash "$RIG/slot.sh" up "$SLOT" > "$OUT/slot.txt" 2>&1 || { cat "$OUT/slot.txt"; release; exit 1; }
. "$RIG/padpath.sh"
eval "$ENVS"
# hidden and muted, always (a replay is nobody's to watch or hear by surprise); the helpers whose edges the record
# carries are off; PAD_RECORD=0 so the replay does not push the player's own recordings out of this slot's list
export PAD_HIDDEN=1 PAD_AUDIO=0 PAD_PLAYFIELD=0 PAD_BALL_FEED=0 PAD_AUTO_ATTRACT=0 PAD_RECORD=0
ts "rig $SLOT ($ROOT): replaying $NAME - $(python3 -c 'import json,sys; i=json.load(open(sys.argv[1])); print(i["game"], i.get("started_text",""), (i.get("card") or {}).get("path",""))' "$REC/run.json")"

bash "$RIG/killgame.sh" > /dev/null 2>&1
if [ -n "$KEEPNV" ]; then
    ts "--keep-nvram: the rig's own NVRAM, NOT the recording's"
else
    python3 "$RIG/runrec.py" restore "$REC" "$ROOT" | tee -a "$OUT/replay_steps.txt"
fi
if [ -d "$REC/modes" ]; then
    bash "$RIG/modes/tryit.sh" install "$REC/modes" > "$OUT/modes.txt" 2>&1 \
        || { cat "$OUT/modes.txt"; release; exit 1; }
    ts "the run's own modes installed: $(ls "$REC/modes" | tr '\n' ' ')"
fi

# THE LAST RUN'S CLOCK GOES FIRST. The switch block outlives a run (padglhost maps it again), and with it the guest
# clock origin the last guest published - so "a clock is there" read as "the game is up" the moment this started,
# and the whole record went in at once against a game still booting (the first replay here: 143 changes in 5 s).
# The guest is stopped (killgame above); the new one publishes its own origin on its first switch scan.
[ -f "$ROOT/dump/padsw" ] && PAD_SW_FILE=$ROOT/dump/padsw python3 -c '
import struct, sys; sys.path.insert(0, sys.argv[1]); import padsw
m = padsw.open_block()
if m is not None:
    struct.pack_into("<I", m, padsw.OFF_GUEST_T0, 0); m.flush()' "$RIG" > /dev/null 2>&1
setsid bash "$RIG/watch.sh" 120 > "$OUT/watch.out" 2>&1 < /dev/null & disown
for i in $(seq 1 600); do
    [ -f "$ROOT/dump/padsw" ] && PAD_SW_FILE=$ROOT/dump/padsw python3 -c '
import sys; sys.path.insert(0, sys.argv[1]); import padsw
m = padsw.open_block(); sys.exit(0 if m is not None and padsw.guest_ms(m) is not None else 1)' "$RIG" > /dev/null 2>&1 && break
    grep -aq "^\[watch\] REFUSING\|the game exited" "$OUT/watch.out" && { ts "the run did not start"; tail -20 "$OUT/watch.out"; release; exit 1; }
    sleep 0.2
done
ts "the game is up; handing it the record"
OUT=$OUT PAD_SW_FILE=$ROOT/dump/padsw python3 -u "$RIG/swreplay.py" "$REC" ${XOPT[@]+"${XOPT[@]}"} > "$OUT/replay.txt" 2>&1
RC=$?
ts "$(tail -1 "$OUT/replay.txt")"
sleep "$AFTER"
bash "$RIG/glshot.sh" "$OUT/end.png" > /dev/null 2>&1 && ts "the glass at the end: $OUT/end.png"
for f in game.out mode.log debug_log.txt; do cp "$ROOT/dump/$f" "$OUT/" 2>/dev/null; done
cp "$PAD_LOGDIR/gzwatch.log" "$OUT/" 2>/dev/null
bash "$RIG/killgame.sh" > /dev/null 2>&1
release
ts "done (rig $SLOT given back); everything is in $OUT"
exit $RC
