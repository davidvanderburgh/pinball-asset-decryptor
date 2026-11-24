#!/bin/bash
# motorcheck.sh <key> <card> - boot, start a game, count a board motor's moves.
#
# The rigbatch job PAD-237 was proven with (bootcheck.sh is the template it
# follows): boot to attract in THIS rig slot (PAD_SLOT), latch the switches
# MOTOR_HOLD names ("77:1 84:0" - id:level), start a game with plunge.py, and
# count what node MOTOR_NODE (default 9) was sent for MOTOR_SAMPLE seconds
# (default 40) after Start. The last line is
#
#   VERDICT <key> pass c53=<n> c54=<n> c40=<n> [env...]
#
# c53/c54 are the motor's move commands - the count that was 35/31 while
# nothing answered john_wick_le's car and every send was a tyre screech, and
# is 0 now. c40 is coil fires on the same node and c40i the same split by coil
# index - on john_wick_le 06/08 are the drop target's TRIP/RESET, 139 in 40 s
# with nothing answering it and 2 with the feeder's model (PAD-248,
# docs/plans/node_board_motor.md). It always passes
# when the run starts; the counts are the result. Knobs the sweeps varied
# (PAD_NB_CREPLY, PAD_NB_CFILL, PAD_NB_MOTOR, PAD_MOTOR_MS) are passed in the
# list's ENV and echoed on the verdict line so a results.tsv reads alone.
#
#   rigbatch.sh --who PAD-n <list> -- bash $RIG/motorcheck.sh
#
# A still of the game FBO at the end of the sample goes to
# $PAD_LOGDIR/motorcheck.<key>.png.
. "$(dirname "$0")/padpath.sh"
. "$(dirname "$0")/gamestate.sh"   # gs_wait_show (PAD-1541)
set -u
KEY=${1:?usage: motorcheck.sh <key> <card>}
CARD=${2:?usage: motorcheck.sh <key> <card>}
SAMPLE=${MOTOR_SAMPLE:-40}
NODE=${MOTOR_NODE:-9}
MOTOR_HOLD=${MOTOR_HOLD:-}
export PAD_CARD=$CARD PAD_CARD_CACHE=${PAD_CARD_CACHE:-0} PAD_AUDIO=${PAD_AUDIO:-0}
export PAD_PLAYFIELD=${PAD_PLAYFIELD:-0} PAD_HIDDEN=${PAD_HIDDEN:-1} PAD_NB_TRACE=1
OUT=$PAD_LOGDIR/motorcheck.$KEY.watch.out
GZ=$PAD_LOGDIR/gzwatch.log
mkdir -p "$PAD_LOGDIR"

stop() { bash "$RIG/killgame.sh" > /dev/null 2>&1 < /dev/null; }
field() { sed -n "s/^$1=//p" <<<"$2" | head -1; }

[ "$(bash "$RIG/alive.sh" --total 2>/dev/null < /dev/null)" = 0 ] || stop
t0=$(date +%s)
setsid bash "$RIG/watch.sh" 12 > "$OUT" 2>&1 < /dev/null &
WPID=$!
disown "$WPID"

while :; do
    sleep 3
    st=$(field state "$(bash "$RIG/status.sh" 2>/dev/null < /dev/null)")
    case "$st" in attract|running) break ;; esac
    if ! kill -0 "$WPID" 2>/dev/null; then
        echo "VERDICT $KEY fail the run ended before attract"
        exit 1
    fi
    if [ $(( $(date +%s) - t0 )) -ge 400 ]; then
        stop
        echo "VERDICT $KEY fail no attract in 400 s"
        exit 1
    fi
done
# Let attract settle before touching it. MOTOR_SETTLE (default 8 s) is a knob
# because "attract" in status.sh is the first picture, and on a slow boot (a
# card staged cold, three rigs at once) john_wick_le was still putting up its
# STANDARD GAME MODE card 40 s later and ignored the Start press (PAD-248).
gs_wait_show "$PAD_LOGDIR/gzwatch.log"   # PAD-1541: the attract scene loaded, not just its lamps
sleep "${MOTOR_SETTLE:-8}"
for kv in ${MOTOR_HOLD//,/ }; do          # "77:1 84:0" or "77:1,84:0"
    python3 "$RIG/swhold.py" "${kv%%:*}" "${kv##*:}" > /dev/null
done
L0=$(wc -l < "$GZ")
BL=$PAD_LOGDIR/padball.log
B0=$(wc -l < "$BL" 2>/dev/null || echo 0)
python3 "$RIG/plunge.py" game > /dev/null 2>&1
# DID A GAME START? (PAD-248) A Start pressed during a title's boot cards is
# ignored, and a run that never started reads as a clean 0 - the first sweep
# of this ticket did exactly that. The feeder serving a ball (the game's own
# trough eject, answered) is the proof; without one, Start again, twice more.
started=no
for try in 1 2 3; do
    for _ in 1 2 3 4 5 6 7 8; do
        tail -n +"$((B0 + 1))" "$BL" 2>/dev/null | grep -q '(ball out)' && { started=$try; break 2; }
        sleep 1
    done
    [ "$try" = 3 ] && break
    python3 "$RIG/plunge.py" start > /dev/null 2>&1
    sleep 6
    python3 "$RIG/plunge.py" plunge > /dev/null 2>&1
done
sleep "$SAMPLE"
S=$(tail -n +"$L0" "$GZ" | grep -a "^\[nbts\].*node=$NODE ")
c53=$(grep -c 'cmd=53 ' <<<"$S")
c54=$(grep -c 'cmd=54 ' <<<"$S")
c40=$(grep -c 'cmd=40 ' <<<"$S")
# ...and per coil index (byte 3 of the frame, `88 0b 40 <IDX> ...`), which on
# john_wick_le tells DROP TRIP (06) from DROP RESET (08) - PAD-248.
c40i=$(grep 'cmd=40 ' <<<"$S" | awk '{print substr($NF, 7, 2)}' | sort | uniq -c |
       awk '{printf "%s%s:%s", (n++ ? "," : ""), $2, $1}')
# Every coil on every node, by name, busiest first (PAD-248): a device the
# game keeps retrying from Start stands out by its count alone.
# PAD-256: the SHORT cmd 40 (`8N 03 40 <IDX> ..`, 6 bytes; c40 and c40i count
# it too) runs a coil under its cmd 41 rule until a switch closes - jaws_le's
# shark motor, a run every 12.5 s from Start (10 s of motor each) while
# nothing answered it. Split by coil index like c40i.
c40r=$(grep 'cmd=40 len=6 ' <<<"$S" | awk '{print substr($NF, 7, 2)}' | sort | uniq -c |
       awk '{printf "%s%s:%s", (n++ ? "," : ""), $2, $1}')
# ...and the same runs on EVERY node over the whole run, boot and attract
# included (runs=node:idx:count): jurassic_park_le, led_zeppelin_le,
# metallica_spike and rush_le run theirs in attract, on nodes 9, 11 and 12.
runs=$(grep -a '^\[nbts\].* cmd=40 len=6 ' "$GZ" | awk '{sub("node=", "", $3); print $3 ":" substr($NF, 7, 2)}' |
       sort | uniq -c | awk '{printf "%s%s:%s", (n++ ? "," : ""), $2, $1}')
coils=$(tail -n +"$L0" "$GZ" | grep -a '^\[nbts\]' | python3 "$RIG/coilcount.py" --min 3)
bash "$RIG/glshot.sh" "$PAD_LOGDIR/motorcheck.$KEY.png" > /dev/null 2>&1
# The model's own account, into this build's log (rigbatch keeps the job's
# output per build; the rig's game log is the next build's by the time anyone
# reads it). The move frames themselves, first and last few, for the timing.
grep -a '^\[motor\]' "$GZ" | head -40
grep -E 'cmd=5[34] ' <<<"$S" | head -5
grep -E 'cmd=5[34] ' <<<"$S" | tail -3
grep -a -i 'drop t' "$PAD_LOGDIR/padball.log" 2>/dev/null | head -20     # PAD-248
# a run that never started: the feeder's own last word, and the switch edges
[ "$started" = no ] && { tail -15 "$BL" 2>/dev/null; grep -a '^\[sw\] [0-9]* ms' "$GZ" | tail -25; }
stop
kill "$WPID" 2>/dev/null
env=""
for v in MOTOR_HOLD MOTOR_SETTLE PAD_NB_CREPLY PAD_NB_CFILL PAD_NB_MOTOR PAD_MOTOR_MS PAD_DROP_TARGET PAD_DROP_DOWN PAD_COIL_MOTOR; do
    [ -n "${!v:-}" ] && env="$env $v=${!v}"
done
echo "VERDICT $KEY pass started=$started c53=$c53 c54=$c54 c40=$c40 c40i=${c40i:--} c40r=${c40r:--} runs=${runs:--} coils=$coils$env"
