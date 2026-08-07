#!/bin/bash
# rootfs.sh <card.raw> - build the guest rootfs that every run chroots into.
#
#   wsl -e bash <rig>/rootfs.sh /mnt/d/.../godzilla_pro-1_15_0....sdcard.raw
#
# THIS IS THE ONE STEP A FRESH CHECKOUT COULD NOT DO. `run_game.sh` chroots into
# $PAD_ROOT and nothing in the repository created it: the recipe lived in a
# gitignored planning document, so cloning this rig gave you every script and no
# filesystem to run them against.
#
# It needs NO ROOT. `debugfs` reads the ext4 image directly - no loop device, no
# mount, no sudo - and the boot partition is walked in Python by getboot.sh.
#
# WHAT GOES WRONG IF YOU DO THIS THE OBVIOUS WAY, both learned the hard way:
#
#   * **Extracting to a Windows path silently drops every symlink.** `/mnt/c`
#     is drvfs and cannot hold them, so `ld-linux.so.3` simply vanishes and
#     nothing in the guest links. The destination must be on the WSL ext4 disk,
#     which is why $PAD_ROOT defaults under $HOME and why this refuses a /mnt
#     path outright rather than producing a rootfs that fails later and
#     elsewhere.
#   * **`rdump /` of the OS partition is not the whole job.** The kernel the
#     game validates lives on the BOOT partition (FAT), which `rdump` of the OS
#     partition obviously never touches; without it the game raises GAME
#     VALIDATION ERROR #3. getboot.sh is therefore part of this script and not
#     an optional extra.
#
# THE TITLE ITSELF IS NOT EXTRACTED HERE, on purpose. `PAD_CARD=<image>
# watch.sh` runs a title straight off the card through a read-only FUSE mount
# (cardmount.sh) in about a second, where extracting one copies 3-6 GB. So this
# builds the OS and stops; pass --game <name> if you want a title on the WSL
# disk as well, which is worth it only for a title you run constantly.
set -u
. "$(dirname "$0")/padpath.sh"

IMG=""
WANT_GAME=""
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --game) WANT_GAME=${2:-}; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
        *) IMG=$1; shift ;;
    esac
done
IMG=${IMG:-${PAD_CARD:-}}

[ -n "$IMG" ] || {
    echo "usage: rootfs.sh <card.raw> [--game <title>] [--force]" >&2
    echo "       PAD_ROOT=<dir> to build somewhere other than $ROOT" >&2
    exit 1
}
[ -f "$IMG" ] || { echo "[rootfs] no card image at $IMG" >&2; exit 1; }

case "$ROOT" in
    /mnt/*) echo "[rootfs] REFUSING: $ROOT is a Windows drive (drvfs), which" >&2
            echo "[rootfs] cannot hold symlinks - ld-linux.so.3 would vanish" >&2
            echo "[rootfs] and nothing in the guest would link. Put PAD_ROOT" >&2
            echo "[rootfs] on the WSL disk." >&2
            exit 1 ;;
esac

command -v debugfs >/dev/null 2>&1 || {
    echo "[rootfs] debugfs is not installed: apt-get install e2fsprogs" >&2
    exit 1
}

if [ -d "$ROOT/lib" ] && [ "$FORCE" = 0 ]; then
    echo "[rootfs] $ROOT already looks populated - pass --force to rebuild"
    exit 0
fi

echo "[rootfs] card   : $IMG"
echo "[rootfs] rootfs : $ROOT"
python3 "$RIG/parts.py" "$IMG" | sed 's/^/[rootfs]   /'

OFF=$(python3 "$RIG/parts.py" --rootfs "$IMG") || {
    echo "[rootfs] could not identify the OS partition" >&2; exit 1; }

mkdir -p "$ROOT"
echo "[rootfs] extracting the OS partition (offset $OFF) - several minutes"
debugfs -R "rdump / $ROOT" "$IMG?offset=$OFF" 2>&1 | grep -v '^debugfs' | head -5

# rdump lands the tree under a directory named after the source root on some
# e2fsprogs versions and directly otherwise; normalise rather than assume.
if [ ! -d "$ROOT/lib" ] && [ -d "$ROOT/$(basename "$ROOT")" ]; then
    mv "$ROOT/$(basename "$ROOT")"/* "$ROOT/" 2>/dev/null || true
    rmdir "$ROOT/$(basename "$ROOT")" 2>/dev/null || true
fi

[ -d "$ROOT/lib" ] || {
    echo "[rootfs] extraction produced no /lib - wrong partition?" >&2; exit 1; }

# The dynamic loader is the one file whose absence turns every later failure
# into a confusing one, so it is checked BY NAME rather than by counting files.
if [ ! -e "$ROOT/lib/ld-linux.so.3" ] && [ ! -L "$ROOT/lib/ld-linux.so.3" ]; then
    echo "[rootfs] WARNING: lib/ld-linux.so.3 is missing. If you extracted to" >&2
    echo "[rootfs] a /mnt path, symlinks were dropped; see the header." >&2
fi

# The kernel the game hashes. Second half of the recipe, and the half that was
# missing for long enough to cost a GAME VALIDATION ERROR #3 investigation.
bash "$RIG/getboot.sh" "$IMG" "$ROOT" || {
    echo "[rootfs] getboot.sh failed - the game will raise VALIDATION ERROR #3" >&2
}

# The shared area every run publishes into: the GL ring, the switch block, the
# LED block, the audio FIFO, and the derived playfield tables.
mkdir -p "$ROOT/dump" "$ROOT/games" "$ROOT/data" "$ROOT/tmp" "$ROOT/run" \
         "$ROOT/dev" "$ROOT/proc" "$ROOT/sys"

if [ -n "$WANT_GAME" ]; then
    GOFF=$(python3 "$RIG/parts.py" --games "$IMG") || {
        echo "[rootfs] could not identify the games partition" >&2; exit 1; }
    echo "[rootfs] extracting title $WANT_GAME (offset $GOFF) - 3-6 GB, minutes"
    mkdir -p "$ROOT/games/$WANT_GAME"
    debugfs -R "rdump /$WANT_GAME "$ROOT/games"" "$IMG?offset=$GOFF" 2>&1 \
        | grep -v '^debugfs' | head -5
    # The node firmware images and conagent are LOOSE files beside the binary,
    # under neither assets/ nor data/, and the original recipe missed all 18.
    # Without them every node board sits on "Runtime Info".
    bash "$RIG/gethex.sh" "$IMG" "$ROOT/games/$WANT_GAME" || true
    debugfs -R "rdump /spk "$ROOT/games"" "$IMG?offset=$GOFF" 2>/dev/null | head -2
fi

echo
echo "[rootfs] done. Next:"
echo "[rootfs]   bash "$RIG/build.sh"          # the ARM hardware shim"
echo "[rootfs]   bash "$RIG/buildbridge.sh"    # the GL backend"
echo "[rootfs]   PAD_CARD=$IMG bash "$RIG/watch.sh""
