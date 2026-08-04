#!/bin/bash
# imgcheck.sh - is the extracted rootfs actually from THIS card image?
#
# The rootfs says "SPIKE v2.7.0" and is dated Sep 2022, while the game is
# Godzilla Pro 1.15.0. If the rootfs came from a different card, a system/game
# mismatch is a live candidate for GAME VALIDATION ERROR #2/#3 - and it is a rig
# integrity problem either way.
set -u
IMG="/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/images/Stern/spike2/godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"
[ -f "$IMG" ] || { echo "image not found: $IMG"; exit 1; }
T=/var/tmp/imgcheck; rm -rf $T; mkdir -p $T

echo "=== partition table ==="
fdisk -l "$IMG" 2>/dev/null | tail -12

echo
echo "=== VERSION.txt from the image's rootfs (p2 @ 12582912) ==="
debugfs -R 'dump /usr/local/spike/VERSION.txt /var/tmp/imgcheck/VERSION.img.txt' "$IMG?offset=12582912" 2>/dev/null
cat $T/VERSION.img.txt 2>/dev/null || echo "(dump failed)"
echo "=== VERSION.txt in the extracted rootfs ==="
cat /home/david/spike2root/usr/local/spike/VERSION.txt

echo
echo "=== /spk on the image's game partition (p5 @ 364904448) ==="
debugfs -R 'ls -l /spk' "$IMG?offset=364904448" 2>/dev/null | head -10
echo "--- /spk/index ---"
debugfs -R 'ls -l /spk/index' "$IMG?offset=364904448" 2>/dev/null | head -10

echo
echo "=== a few rootfs files: image vs extracted ==="
for f in /etc/init.d/game /usr/local/bin/spk /usr/local/spike/spike_menu/game; do
    debugfs -R "dump $f /var/tmp/imgcheck/x" "$IMG?offset=12582912" 2>/dev/null
    A=$(sha1sum $T/x 2>/dev/null | cut -c1-12)
    B=$(sha1sum "/home/david/spike2root$f" 2>/dev/null | cut -c1-12)
    printf '%-40s image=%s extracted=%s %s\n' "$f" "${A:-none}" "${B:-none}" \
        "$([ "$A" = "$B" ] && echo SAME || echo DIFFER)"
done
rm -rf $T
