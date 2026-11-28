#!/bin/bash
# PAD-1647: the author's own install-bluez5-bond-retention.sh run on the real Fallout LE 0.82 S40bluetoothd (a staged
# copy, the way his docs say to patch an image), against what the app's s3_keep_bonds_text makes of the same file.
set -u
W=/var/tmp/pad1647s40; rm -rf "$W"; mkdir -p "$W/his/init.d" "$W/x"
REPO=$1
debugfs -R "dump /etc/init.d/S40bluetoothd $W/S40.orig" /mnt/c/tmp/PAD-1647/s3/rootfs.img 2>/dev/null
debugfs -R "stat /etc/init.d/S40bluetoothd" /mnt/c/tmp/PAD-1647/s3/rootfs.img 2>/dev/null | head -3
tar xzf /mnt/c/tmp/PAD-1647/rel/spike-pinball-bluetooth-arm64.tar.gz -C "$W/x"
cp "$W/S40.orig" "$W/his/init.d/S40bluetoothd"
sh "$W/x/install-bluez5-bond-retention.sh" "$W/his/init.d/S40bluetoothd"; echo "his installer exit $?"
ls -la "$W/his/init.d" "$W/his/init.d/.spikebt-originals"
cd "$REPO" && python3 - "$W" <<'EOF'
import sys
from pinball_decryptor.core import bluetooth_card as BT
W = sys.argv[1]
orig = open(W + '/S40.orig', 'rb').read()
rule = BT.keep_bonds_rule(open(W + '/x/install-bluez5-bond-retention.sh', 'rb').read())
mine = BT.s3_keep_bonds_text(orig, rule).encode()
his = open(W + '/his/init.d/S40bluetoothd', 'rb').read()
kept = open(W + '/his/init.d/.spikebt-originals/S40bluetoothd', 'rb').read()
print('VERDICT the app makes the same S40bluetoothd as his installer, byte for byte:', 'PASS' if mine == his else 'FAIL')
print('VERDICT the copy kept is the script as it was:', 'PASS' if kept == orig else 'FAIL')
print('VERDICT taken back out equals the original:', 'PASS' if BT.s3_forget_bonds_text(mine, kept).encode() == orig
      and BT.s3_forget_bonds_text(mine).encode() == orig else 'FAIL')
print('VERDICT a second pass changes nothing:', 'PASS' if BT.s3_keep_bonds_text(mine, rule) is None else 'FAIL')
EOF
diff "$W/S40.orig" "$W/his/init.d/S40bluetoothd"
