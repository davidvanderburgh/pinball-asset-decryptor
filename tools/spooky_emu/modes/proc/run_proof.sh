#!/bin/bash
W=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1387
L=$W/tools/spike2_emu/riglock.sh; P=$W/tools/spooky_emu/proc
S=
for k in $(seq 1 40); do
    S=$(bash $L take --any PAD-1387 "Spooky P-ROC mode proof" 2>/dev/null | sed -n 's/^slot=//p')
    [ -n "$S" ] && break; sleep 15
done
[ -n "$S" ] || { echo "no free rig"; exit 1; }
echo "slot=$S"
export PAD_SLOT=$S PAD_LABEL=PAD-1387 PAD_HIDDEN=1
B=/var/tmp/pad1387_build/rm_pad
bash $W/tools/spooky_emu/modes/proc/mkprobe.sh rm_20220902 $B || exit 1
timeout 400 bash $P/run_game.sh $B > /mnt/c/tmp/PAD-1387/proc/run_game.out 2>&1
echo "run_game rc=$?"
. $P/sppath.sh
LOG=$(ls $SPP_RIG/game/RickAndMorty/padmodes.log 2>/dev/null || find /var/tmp/pad_spkproc/rig$S -name padmodes.log 2>/dev/null | head -1)
echo "log: $LOG"
for i in $(seq 1 60); do grep -q -i -E 'made|added|attract' "$LOG" 2>/dev/null && break; sleep 3; done
sleep 40
bash $P/sw.sh tap coin1 150; sleep 2; bash $P/sw.sh tap startButton 200; sleep 6
bash $P/sw.sh tap launchBall 200; sleep 5
for i in 1 2 3; do bash $P/sw.sh tap slingRight 150; sleep 3; done
bash $P/shot.sh /mnt/c/tmp/PAD-1387/proc/rm_mode.png || echo "shot failed"
echo "--- padmodes.log"; cat "$LOG" | cut -c1-240 | tail -40
tail -3 $SPP_RIG/shell.log 2>/dev/null
bash $P/killgame.sh >/dev/null 2>&1; echo done
