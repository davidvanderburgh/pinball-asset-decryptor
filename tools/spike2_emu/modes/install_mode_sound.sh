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
    # ALREADY-INSTALLED IS CHECKED FIRST, and the order is the whole point: once the
    # grown bank is installed it IS image.bin and there is no image.grown.bin any
    # more, so asking for that file first reports "run grow_mode_sound.sh" about a
    # bank that is already live - and under `set -e` that aborts the caller's staging
    # and the run never starts.
    if [ -f "$D/image.stock.bin" ]; then echo "already installed (image.stock.bin exists)"; exit 0; fi
    [ -f "$D/image.grown.bin" ] || { echo "no $D/image.grown.bin - run grow_mode_sound.sh" >&2; exit 1; }
    mv "$D/image.bin" "$D/image.stock.bin"
    mv "$D/image.grown.bin" "$D/image.bin"
    echo "grown bank installed; stock kept as image.stock.bin"
    ;;
  off)
    [ -f "$D/image.stock.bin" ] || { echo "no stock bank put aside; nothing to undo"; exit 0; }
    # REFUSE rather than clobber. This used to `mv image.bin image.grown.bin`
    # unconditionally, which silently destroyed an existing grown bank the first time
    # a SECOND one was built (2026-09-16: the idx-1369 bank was overwritten by the
    # re-pointed idx-1560 bank, and nothing said so). Banks cost ninety seconds to
    # rebuild, but a tool that deletes a file without mentioning it is worse than one
    # that stops.
    keep=$D/image.grown.bin
    if [ -e "$keep" ]; then
        n=1
        while [ -e "$D/image.grown.$n.bin" ]; do n=$((n + 1)); done
        keep=$D/image.grown.$n.bin
        echo "image.grown.bin already exists; keeping this one as $(basename "$keep")"
    fi
    mv "$D/image.bin" "$keep"
    mv "$D/image.stock.bin" "$D/image.bin"
    echo "stock bank restored; the bank that was live is kept as $(basename "$keep")"
    ;;
esac
ls -l "$D"/image*.bin 2>/dev/null | awk '{ printf "  %-22s %s\n", $NF, $5 }'
[ -f "$D/image.stock.bin" ] && echo "INSTALLED: the grown bank is live" \
                            || echo "INSTALLED: the stock bank is live"
