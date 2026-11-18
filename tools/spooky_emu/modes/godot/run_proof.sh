#!/bin/bash
W=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1387
L=$W/tools/spike2_emu/riglock.sh
S=
for k in $(seq 1 40); do
    S=$(bash $L take --any PAD-1387 "Spooky Godot mode proof" 2>/dev/null | sed -n 's/^slot=//p')
    [ -n "$S" ] && break; sleep 15
done
[ -n "$S" ] || { echo "no free rig"; exit 1; }
echo "slot=$S"
export PAD_SLOT=$S PAD_LABEL=PAD-1387 PAD_HIDDEN=1
timeout 900 bash $W/tools/spooky_emu/modes/godot/probe.sh /mnt/d/Pinball/images/Spooky/2025.10.08.looney 2>&1 | grep -v Escape | tail -60
. $W/tools/spooky_emu/spkpath.sh
grep -a 'bash command\|shell' $SPK_RIG/player.log 2>/dev/null | tail -3
bash $W/tools/spooky_emu/killgame.sh >/dev/null 2>&1; echo done
