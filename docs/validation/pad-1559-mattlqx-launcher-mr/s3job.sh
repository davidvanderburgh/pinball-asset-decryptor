#!/bin/bash
# PAD-1559 Spike 3 proof (root, WSL Ubuntu): Fallout LE 0.82, mattlqx's v0.3.0 arm64 files in the guest.
#  1. cases3.sh: his run-live.sh from main and the patched one, same cases, a stand-in game.
#  2. the REAL game started by the patched run-live.sh (SPIKEBT_BACKEND=bluez5, the rig's own preloads handed in
#     through SPIKEBT_PRELOAD, the helper on its demo backend since the rig has no BlueZ); then the service menu.
set -u
export HOME=/home/david
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1559
ORIG=/mnt/d/Pinball/images/Stern/spike3/fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw
OUT=/mnt/c/tmp/PAD-1559/rig/out_s3; S=/mnt/c/tmp/PAD-1559/rig
SLOT=${SLOT:-59}; SD=/var/tmp/pad-s3/slot$SLOT
pgrep -f "slot[ =]$SLOT( |$)" >/dev/null && { echo "slot $SLOT is busy"; exit 3; }
rm -rf "$OUT" "$SD"; mkdir -p "$OUT"
mkdir -p "$SD/root.up/usr/local/spikebt" "$SD/connectivity.up/dump/pad1559"
tar xzf /home/david/pad1554/store/bluetooth/spike-pinball-bluetooth-arm64.tar.gz -C "$SD/root.up/usr/local/spikebt"
: > "$SD/root.up/usr/local/spikebt/enabled"
P=$SD/connectivity.up/dump/pad1559
cp "$S/run-live.before.sh" "$S/run-live.after.sh" "$S/cases3.sh" "$P/"
cat > "$P/pre.sh" <<'EOF'
#!/bin/sh
D=/connectivity/dump/pad1559
B=/usr/local/spikebt
RIGPRE=$LD_PRELOAD
echo "rig preloads: $RIGPRE" > $D/rigpre.txt
PADEX=$RIGPRE /bin/sh $D/cases3.sh $D fallback5 unknown s3exit1 s3exit3 s3exit6 s3exit2
# the real game, through the patched launcher, the way a card's game_monitor would start it
mv $B/spikebt $B/spikebt.real
printf '#!/bin/sh\nexec %s --backend=demo "$2" "${3%%/*}/demo-state.json"\n' "$B/spikebt.real" > $B/spikebt
chmod 755 $B/spikebt
rm -rf /dump/spikebt
unset LD_PRELOAD
SPIKEBT_PRELOAD=$RIGPRE SPIKEBT_BACKEND=bluez5
export SPIKEBT_PRELOAD SPIKEBT_BACKEND
exec /bin/sh $D/run-live.after.sh /games/game
EOF
chmod 755 "$P"/*
cd "$REPO/tools/spike3_emu"
( env PAD_LABEL=PAD-1559 PAD_HIDDEN=1 PAD_S3_PIVOT=0 bash s3run.sh "$ORIG" --slot "$SLOT" --bus --bridge \
    --secs "${SECS:-480}" --prog /connectivity/dump/pad1559/pre.sh > "$OUT/run.out" 2>&1; echo "run exit $?" >> "$OUT/run.out" ) &
RUN=$!
shot() { python3 - "$SLOT" "$OUT/$1.png" <<'PY'
import shutil, sys
sys.path.insert(0, '.')
import s3press
f = s3press.newest_frame(int(sys.argv[1]))
print('frame', f)
if f: shutil.copyfile(f, sys.argv[2])
PY
}
press() { python3 s3press.py press "$SLOT" "$1" "${2:-300}" > /dev/null 2>&1; sleep "${3:-3}"; }
# the cases take up to ~2 minutes before the game starts
sleep "${BOOT_WAIT:-240}"
shot s3_boot
python3 -c 'import sys; sys.path.insert(0,"."); import s3press; s3press.autoguide(int(sys.argv[1]), secs=60)' "$SLOT" > "$OUT/guide.out" 2>&1
sleep 20
shot s3_attract
for m in /proc/[0-9]*/maps; do
    grep -q 'spikebt/menu.so' "$m" 2>/dev/null && echo "pid ${m%/maps} $(tr '\0' ' ' < ${m%/maps}/cmdline | cut -c1-90): $(grep -o '/[^ ]*\.so[^ ]*' "$m" | sort -u | grep -v '^/lib/\|^/usr/lib/' | tr '\n' ' ')"
    p=${m%/maps}; grep -q 'spikebt/menu.so' "$m" 2>/dev/null && tr '\0' '\n' < $p/environ 2>/dev/null | grep -E '^(LD_PRELOAD|SPIKEBT_)' | sed 's/^/    /'
done > "$OUT/game_maps.txt" 2>&1
press 0 300 5; shot s3_svc_a
press 0 300 5; shot s3_svc_b
press 2 300 3; shot s3_svc_prev
press 0 300 5; shot s3_bt_menu
press 3 300 3
cp "$P"/*.txt "$SD/connectivity.up/dump/spikebt/live/helper.log" "$OUT/" 2>/dev/null
bash s3launch.sh --stop "$SLOT" > /dev/null 2>&1 || pkill -f "s3run.sh.*--slot $SLOT"
wait $RUN 2>/dev/null
tail -5 "$OUT/run.out"
