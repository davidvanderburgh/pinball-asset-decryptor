#!/bin/bash
# gethex.sh - recover the node board firmware images the rootfs rebuild missed.
#
# The rebuild recipe in the handoff dumps only game, image.bin, assets/, data/
# and spk/ out of the card's games partition. But /godzilla_pro/ ALSO contains
# 17 loose <nodetype>-<CPUCLASS>-1_35_0.hex files and the conagent binary, and
# those were never copied. The card's own SIDX manifest
# (games/spk/index/godzilla_pro-1_15_0.sidx) lists them as its first 18 entries,
# which is how the gap was spotted.
#
# This is exactly what keeps every node board on "Runtime Info": the game globs
# ./<nodetype>-<CPUCLASS>-1_35_[0-9]*.hex in its own directory (0x448558), and
# with no match it registers nothing, so board[+88] and the registry head at
# 0x7e1b98 both stay 0 and the status gate at 0x1d56cc can never pass.
#
# The games partition is partition 3 of the card: start LBA 712704 * 512 =
# 364904448, which is the same ?offset= the handoff already uses.
set -eu

IMG=${1:-/mnt/d/Pinball/images/Stern/spike2/godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw}
DEST=${2:-/home/david/spike2root/games/godzilla_pro}
OFF=364904448

[ -f "$IMG" ] || { echo "no such image: $IMG" >&2; exit 1; }
[ -d "$DEST" ] || { echo "no such dir: $DEST" >&2; exit 1; }

echo "image : $IMG"
echo "dest  : $DEST"
echo

# debugfs 'ls -l' on the game dir, so we can see what is actually there rather
# than trusting the manifest.
echo "--- loose files in /godzilla_pro on the card ---"
debugfs -R 'ls -l /godzilla_pro' "$IMG?offset=$OFF" 2>/dev/null \
  | awk '{ for (i=1;i<=NF;i++) if ($i ~ /\.hex$|^conagent$/) print "  ", $i, "(" $(i-1) " bytes)" }'
echo

n=0
for f in $(debugfs -R 'ls -p /godzilla_pro' "$IMG?offset=$OFF" 2>/dev/null \
           | cut -d/ -f6 | grep -E '\.hex$|^conagent$'); do
    debugfs -R "dump /godzilla_pro/$f $DEST/$f" "$IMG?offset=$OFF" 2>/dev/null
    if [ -s "$DEST/$f" ]; then
        n=$((n + 1))
        printf '  recovered %-44s %8s bytes\n' "$f" "$(stat -c%s "$DEST/$f")"
    else
        echo "  FAILED    $f" >&2
    fi
done

echo
echo "recovered $n files into $DEST"
echo "--- what the game will now glob for (first pattern) ---"
ls "$DEST"/*.hex 2>/dev/null | head -20
