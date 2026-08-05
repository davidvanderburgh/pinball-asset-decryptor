#!/bin/bash
# cardmount.sh <card.raw> [--umount] - mount a Spike 2 card's games partition,
# READ ONLY, WITHOUT ROOT, so a title can be run without extracting 6 GB first.
#
#   cardmount.sh .../jaws_le-1_02_0.Release.16G.sdcard.raw
#   -> /home/david/card/jaws_le-1_02_0   (and prints the title directory)
#
# WHY THIS IS POSSIBLE AT ALL. The obvious `mount -o loop,offset=` needs real
# root, and this rig has no sudo. Two things make it work anyway:
#
#   * fuse2fs, e2fsprogs' own read-only-capable ext4 driver in USERSPACE. It is
#     not installed and does not need to be: `apt-get download` works as an
#     ordinary user, and `dpkg-deb -x` into a private prefix gives a working
#     binary with no package manager and no privilege. See ensure_fuse2fs().
#   * fusermount3 is setuid, so an unprivileged user may create a FUSE mount -
#     and FUSE is one of the few filesystem types the kernel permits inside a
#     user namespace, which is where run_game.sh does its work.
#
# The partition is mounted `ro`. Nothing here can write to a card image, which
# is the right guarantee to have when the images are the only copies.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
PREFIX=/home/david/local
CARDS=/home/david/card
FUSE2FS="$PREFIX/usr/bin/fuse2fs"
export LD_LIBRARY_PATH="$PREFIX/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"

die() { echo "[card] $*" >&2; exit 1; }

# fuse2fs and libfuse2, unpacked into a private prefix. Downloaded once; after
# that this is offline. Ubuntu splits them into two packages and fuse2fs links
# libfuse.so.2 (not the libfuse3 the distro ships), hence both.
ensure_fuse2fs() {
    [ -x "$FUSE2FS" ] && [ -e "$PREFIX/lib/x86_64-linux-gnu/libfuse.so.2" ] && return 0
    echo "[card] fetching fuse2fs into $PREFIX (once)"
    mkdir -p "$PREFIX" /tmp/cardpkg || return 1
    ( cd /tmp/cardpkg && apt-get download fuse2fs libfuse2t64 >/dev/null 2>&1 ) || {
        echo "[card] apt-get download failed - no network?" >&2; return 1; }
    for d in /tmp/cardpkg/*.deb; do dpkg-deb -x "$d" "$PREFIX" || return 1; done
    [ -x "$FUSE2FS" ] || return 1
    return 0
}

# The games partition. It is p3 on every Spike 2 card seen - 8 GB and 16 GB,
# 2019 titles and 2024 ones - but the start sector is read rather than assumed,
# because a wrong offset does not fail, it mounts something else.
games_offset() {
    /sbin/fdisk -l "$1" 2>/dev/null | awk -v img="$1" '
        $1 ~ /3$/ && $0 ~ img && $NF == "Linux" { print $2 * 512; exit }'
}

# The title directory inside the partition: the one holding a `game` ELF. The
# card also has spk/ and the three symlinks the machine itself uses.
title_dir() {
    local m="$1" d
    for d in "$m"/*; do
        [ -f "$d/game" ] && [ ! -L "$d" ] && { basename "$d"; return 0; }
    done
    return 1
}

IMG=${1:-}
[ -n "$IMG" ] || die "usage: cardmount.sh <card.raw> [--umount]"
[ -f "$IMG" ] || die "no image at $IMG"
LABEL=$(basename "$IMG"); LABEL=${LABEL%%.Release*}; LABEL=${LABEL%%.raw}
MNT="$CARDS/$LABEL"

if [ "${2:-}" = "--umount" ]; then
    fusermount -u "$MNT" 2>/dev/null || fusermount3 -u "$MNT" 2>/dev/null
    rmdir "$MNT" 2>/dev/null
    echo "[card] unmounted $MNT"
    exit 0
fi

# Already mounted and healthy? Then say so and stop - remounting a live card
# under a running game is not something to do by accident.
if [ -d "$MNT" ] && mountpoint -q "$MNT" 2>/dev/null; then
    T=$(title_dir "$MNT") || die "$MNT is mounted but holds no game"
    echo "[card] already mounted: $MNT"
    echo "$MNT/$T"
    exit 0
fi

ensure_fuse2fs || die "could not get fuse2fs"
OFF=$(games_offset "$IMG")
[ -n "$OFF" ] || die "no third Linux partition in $(basename "$IMG")"
mkdir -p "$MNT" || die "cannot create $MNT"

echo "[card] mounting $(basename "$IMG") p3 at offset $OFF (read only)"
"$FUSE2FS" -o ro,offset="$OFF" "$IMG" "$MNT" >/dev/null 2>&1 \
    || die "fuse2fs refused $(basename "$IMG")"

T=$(title_dir "$MNT") || {
    fusermount -u "$MNT" 2>/dev/null
    die "mounted, but no directory in it holds a game ELF"
}
echo "[card] title: $T"
echo "$MNT/$T"
