#!/bin/bash
# PAD-1387 Unity proof: Scooby-Doo with PAD's managed mode runtime preloaded.
set -u
W=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1387
T=$W/tools/spooky_emu
L=$W/tools/spike2_emu/riglock.sh
S=
for k in $(seq 1 40); do
    S=$(bash $L take --any PAD-1387 "Spooky Unity mode proof" 2>/dev/null | sed -n 's/^slot=//p')
    [ -n "$S" ] && break; sleep 15
done
[ -n "$S" ] || { echo "no free rig"; exit 1; }
echo "slot=$S"
install -d -m 755 /var/tmp/pad_spooky/padunity
install -m 755 /mnt/c/tmp/PAD-1387/unity/out/padunity.so /var/tmp/pad_spooky/padunity/padunity.so
install -m 644 /mnt/c/tmp/PAD-1387/unity/out/PadModes.dll /var/tmp/pad_spooky/padunity/PadModes.dll
export PAD_SLOT=$S PAD_LABEL=PAD-1387 PAD_HIDDEN=1 PAD_VISIBLE=0 PAD_AUDIO=0
export SPK_MENU_SO=/var/tmp/pad_spooky/padunity/padunity.so SPK_MENU_PROTO=warden SPK_MENU_SWITCH=250
export PADUNITY_LOG=/tmp/padunity.log
timeout 600 bash $T/watch.sh /mnt/d/Pinball/images/Spooky/v2025.12.01.09.scooby > /mnt/c/tmp/PAD-1387/unity/watch.out 2>&1 &
. $T/spkpath.sh
sleep 20; . $T/spkpath.sh
for i in $(seq 1 100); do grep -q 'registered ProbeMode' $SPK_RIG/logs/padunity.log 2>/dev/null && break; sleep 3; done
echo "mode registered after ~$((20+i*3)) s"; sleep 15
cd $T
python3 sw.py coin; sleep 2; python3 sw.py start; sleep 10
python3 sw.py plunge; sleep 5
for n in 20 21 22 23 30 31; do python3 sw.py $n pulse 200; sleep 2; done
sleep 4
bash $T/shot.sh /mnt/c/tmp/PAD-1387/unity/proof.png >/dev/null 2>&1
echo "--- padunity log"
LOGF=$(find /tmp $SPK_ROOT/nv$S /var/tmp/pad_spooky/rig$S -name padunity.log 2>/dev/null | head -1)
echo "log at: $LOGF"; cat "$LOGF" 2>/dev/null | cut -c1-260 | tail -60
grep -a -i -E 'padmodes|padunity|exception' $SPK_RIG/player.log | tail -10 | cut -c1-220
bash $T/killgame.sh >/dev/null 2>&1
echo done
