#!/bin/bash
# PAD-1643 stand-in proof (root, WSL Ubuntu): make the card, boot it as a machine, and run the app's own
# "put it on the machine" code against it over SSH.  Then the card's system partition is checked as a filesystem
# and read with the app's own card inspector.
set -u
export HOME=/home/david
W=/var/tmp/pad1643
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1643
S=/mnt/c/tmp/PAD-1643/standin
STOCK=/mnt/d/Pinball/images/Stern/spike2/godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw
find "$W" -mindepth 1 -maxdepth 1 ! -name py -exec rm -rf {} +
cd "$W"
# the release as it is installed on this PC, copied: the proof never writes the real store
mkdir -p "$W/plugins"
cp -r "/mnt/c/Users/david/AppData/Roaming/pinball_decryptor/plugins/bluetooth" "$W/plugins/"
export PAD_PLUGIN_DIR=$W/plugins PAD_E2FSPROGS_DIR=/sbin
PYTHONPATH=$W/py:$REPO python3 "$S/make_card.py" "$REPO" "$W" "$STOCK" 2>&1 | tee "$W/make.log"
read -r OFF SIZE < <(grep '^P2 offset/size' "$W/make.log" | awk '{print $3, $4}')
unshare -n -m -p -f bash "$S/boot.sh" "$OFF" "$SIZE" "$REPO"
echo "proof.py exit: $?"
# the card after it all (plugin on, through a linked game_monitor): a clean filesystem, and what the app reads
dd if="$W/machine.raw" of="$W/p2.img" bs=1M iflag=skip_bytes,count_bytes skip="$OFF" count="$SIZE" status=none
e2fsck -fn "$W/p2.img" > "$W/fsck.log" 2>&1; echo "VERDICT the card's system partition is a clean filesystem afterwards: $([ $? = 0 ] && echo PASS || echo FAIL)  ($(tail -1 "$W/fsck.log"))"
rm -f "$W/p2.img"
PYTHONPATH=$W/py:$REPO python3 - <<EOF
from pinball_decryptor.core import bluetooth_card as BT
st = BT.inspect_image('$W/machine.raw')
ok = st['supported'] and st['enabled'] and st['release'] == 'v0.3.0'
print("VERDICT the app's card inspector reads the machine's card as carrying the plugin: %s  (%s)" % (
    'PASS' if ok else 'FAIL', BT.describe(st) or st['reason']))
EOF
