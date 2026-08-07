#!/bin/bash
# imgcheck.sh - is the extracted rootfs actually from THIS card image?
#
# The rootfs says "SPIKE v2.7.0" and is dated Sep 2022, while the game is
# Godzilla Pro 1.15.0. If the rootfs came from a different card, a system/game
# mismatch is a live candidate for GAME VALIDATION ERROR #2/#3 - and it is a rig
# integrity problem either way.
. "$(dirname "$0")/padpath.sh"
set -u
# The card to check, as an argument or PAD_CARD. It used to default to one
# image on one machine's D: drive, which is not a default any other checkout
# can use.
IMG=${1:-${PAD_CARD:-}}
[ -n "$IMG" ] || { echo "usage: imgcheck.sh <card.raw>   (or set PAD_CARD)"; exit 1; }
[ -f "$IMG" ] || { echo "image not found: $IMG"; exit 1; }
T=/var/tmp/imgcheck; rm -rf $T; mkdir -p $T

echo "=== partition table ==="
fdisk -l "$IMG" 2>/dev/null | tail -12

echo
echo "=== VERSION.txt from the image's rootfs (p2 @ 12582912) ==="
debugfs -R 'dump /usr/local/spike/VERSION.txt /var/tmp/imgcheck/VERSION.img.txt' "$IMG?offset=12582912" 2>/dev/null
cat $T/VERSION.img.txt 2>/dev/null || echo "(dump failed)"
echo "=== VERSION.txt in the extracted rootfs ==="
cat $ROOT/usr/local/spike/VERSION.txt

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
    B=$(sha1sum "$ROOT$f" 2>/dev/null | cut -c1-12)
    printf '%-40s image=%s extracted=%s %s\n' "$f" "${A:-none}" "${B:-none}" \
        "$([ "$A" = "$B" ] && echo SAME || echo DIFFER)"
done
rm -rf $T
