#!/bin/bash
# install_mode_sound.sh on|off|status - swap the grown sound bank in or out.
#
# By RENAME, never by overwrite: the stock image.bin's inode carries more than one
# link (the extraction shares its blocks), so writing over it in place would silently
# change the other copy too. Renaming touches only this directory.
#
#   on      image.bin -> image.stock.bin, image.grown.bin -> image.bin
#   off     put the stock bank back
#   status  say which bank is installed, by size
#
# A rig action: take the lock, and do it with no guest running (alive.sh 0).
. "$(dirname "$0")/../padpath.sh"
set -e
D=$ROOT/games/${PAD_GAME:-godzilla_pro}
case "${1:-status}" in
  on)
    [ -f "$D/image.grown.bin" ] || { echo "no $D/image.grown.bin - run grow_mode_sound.sh" >&2; exit 1; }
    if [ -f "$D/image.stock.bin" ]; then echo "already installed (image.stock.bin exists)"; exit 0; fi
    mv "$D/image.bin" "$D/image.stock.bin"
    mv "$D/image.grown.bin" "$D/image.bin"
    echo "grown bank installed; stock kept as image.stock.bin"
    ;;
  off)
    [ -f "$D/image.stock.bin" ] || { echo "no stock bank put aside; nothing to undo"; exit 0; }
    mv "$D/image.bin" "$D/image.grown.bin"
    mv "$D/image.stock.bin" "$D/image.bin"
    echo "stock bank restored; grown bank kept as image.grown.bin"
    ;;
esac
ls -l "$D"/image*.bin 2>/dev/null | awk '{ printf "  %-22s %s\n", $NF, $5 }'
[ -f "$D/image.stock.bin" ] && echo "INSTALLED: the grown bank is live" \
                            || echo "INSTALLED: the stock bank is live"
