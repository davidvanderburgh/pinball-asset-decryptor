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
# THE OFFSET IS READ OFF THE PARTITION TABLE, not written down. It was
# 364904448 on the 8 GB Godzilla card this was built against - LBA 712704 * 512 -
# and that number is a property of that image and no other. parts.py identifies
# the games partition structurally; see there for why the partition NUMBER is
# not a safe answer either.
set -eu
. "$(dirname "$0")/padpath.sh"

IMG=${1:-${PAD_CARD:-}}
DEST=${2:-}
OFF=${3:-}

[ -n "$IMG" ] || { echo "usage: gethex.sh <card.raw> [dest-dir] [offset]" >&2; exit 1; }
[ -f "$IMG" ] || { echo "no such image: $IMG" >&2; exit 1; }
[ -n "$DEST" ] || DEST=$ROOT/games/$(python3 "$RIG/gameinfo.py" --game)
[ -d "$DEST" ] || { echo "no such dir: $DEST" >&2; exit 1; }
[ -n "$OFF" ] || OFF=$(python3 "$RIG/parts.py" --games "$IMG")
[ -n "$OFF" ] || { echo "could not find the games partition in $IMG" >&2; exit 1; }

# The title directory ON THE CARD is named for the title, and the destination
# is named for the same title, so one is derived from the other rather than
# both being written out.
TITLE=$(basename "$DEST")

echo "image : $IMG"
echo "dest  : $DEST"
echo

# debugfs 'ls -l' on the game dir, so we can see what is actually there rather
# than trusting the manifest.
echo "--- loose files in /$TITLE on the card ---"
debugfs -R "ls -l /$TITLE" "$IMG?offset=$OFF" 2>/dev/null \
  | awk '{ for (i=1;i<=NF;i++) if ($i ~ /\.hex$|^conagent$/) print "  ", $i, "(" $(i-1) " bytes)" }'
echo

n=0
for f in $(debugfs -R "ls -p /$TITLE" "$IMG?offset=$OFF" 2>/dev/null \
           | cut -d/ -f6 | grep -E '\.hex$|^conagent$'); do
    debugfs -R "dump /$TITLE/$f $DEST/$f" "$IMG?offset=$OFF" 2>/dev/null
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
