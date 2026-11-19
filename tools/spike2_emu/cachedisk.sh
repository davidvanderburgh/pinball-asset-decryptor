#!/bin/bash
# cachedisk.sh - a user's Spike 2 card cache on a disk of its own, XFS with shared blocks (PAD-1459). Run as root.
#
#   cachedisk.sh mkfs <dev>     put XFS with reflink on the freshly made disk (storexfs.sh: the pinned mkfs.xfs)
#   cachedisk.sh move           once: the old cache ($PAD_HOME/cardcache) into <disk>/cardcache, sharing blocks
#                               as it lands; prints `moved <files> <kb>`. Exit 3: the old cache is in use - nothing
#                               switched, and the next run carries on where this one stopped
#
# WHY. A user has no card store (cardstore.ps1 is David's), so their cards were cached inside a Linux disk that only
# ever grows on C: - and the cache is mostly the same blocks over and over: a custom build is the stock card with a
# few files changed, an LE card shares 73-80% with its Pro (PAD-1453 measured David's: 101 GiB of cache held 28.8
# GiB unique). The app makes pad-cardcache.vhdx (core/rigdata.py ensure_cache_disk), attached by name at
# /mnt/wsl/padcache in every distro; cardmount.sh caches there once <disk>/cardcache exists and shares each new
# copy's blocks after it lands (storededupe.py dedupe), and its limit counts the disk's real use, so the same 64 GB
# holds about twice the builds.
#
# THE MOVE IS SAFE TO STOP ANYWHERE. It copies into <disk>/cardcache.moving (storededupe.py ingest: a file already
# there with the same size and mtime is skipped, so a second run only catches up), byte-compares every file, and
# only then, with nothing using the old cache (no card mounted from it, no copier writing into it), renames the copy
# into place and deletes the old one. Until that rename cardmount.sh keeps using the old cache exactly as before.
# A cache that is a link (a developer's, pointing at the store) is never touched.
set -u
SELF=$(cd "$(dirname "$0")" && pwd)
MNT=${PAD_CACHE_DISK_MOUNT:-/mnt/wsl/padcache}
. "$SELF/padpath.sh"

die() { echo "[cachedisk] $2" >&2; exit "$1"; }

in_use() {   # <dir>: anything holding the old cache - a fuse2fs on one of its cards, a copier, an open file
    local p pid rest
    for p in "$1" "$(readlink -f "$1" 2>/dev/null)"; do
        [ -n "$p" ] || continue
        while read -r pid rest; do
            [ -n "$pid" ] || continue
            tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q cachedisk.sh && continue   # this move itself
            return 0
        done < <(STORE=$p bash "$SELF/storexfs.sh" busy 2>/dev/null)
    done
    return 1
}

case ${1:-} in
mkfs)
    dev=${2:-}
    [ -b "$dev" ] || die 2 "usage: cachedisk.sh mkfs <block device>"
    bash "$SELF/storexfs.sh" mkfs "$dev" padcache ;;
move)
    mountpoint -q "$MNT" || die 2 "the cache disk is not mounted at $MNT"
    NEW=$MNT/cardcache
    MOVING=$MNT/cardcache.moving
    # the old cache by environment, never as an argument: the busy check reads every process's arguments
    OLD=${PAD_OLD_CARD_CACHE:-$PAD_HOME/cardcache}
    # one move at a time, and never two passes of the same move
    exec 9>"$MNT/.move.lock"
    flock -n 9 || { echo "busy another move is running"; exit 3; }
    # what the empty filesystem takes, so cardmount.sh's limit counts only cards (cache_used_kb)
    if [ ! -f "$MNT/.base_kb" ] && [ ! -e "$NEW" ] && [ ! -e "$MOVING" ]; then
        df -k --output=used "$MNT" | tail -1 | tr -d " " > "$MNT/.base_kb"
    fi
    owner=$(stat -c %u:%g "$PAD_HOME" 2>/dev/null || echo 0:0)
    if [ -d "$NEW" ]; then
        echo "moved 0 0 (the cache is on the disk already)"; exit 0
    fi
    if [ -L "$OLD" ] || [ ! -d "$OLD" ] || [ -z "$(ls -A "$OLD" 2>/dev/null)" ]; then
        # nothing to bring (or a link someone made on purpose): the disk's cache starts empty
        rm -rf "$MOVING"
        mkdir -p "$NEW" && chown "$owner" "$NEW"
        [ -d "$OLD" ] && [ ! -L "$OLD" ] && rmdir "$OLD" 2>/dev/null
        echo "moved 0 0"; exit 0
    fi
    mkdir -p "$MOVING"
    host=""
    [ -n "${PAD_HOST_DRIVE:-}" ] && host=$PAD_HOST_DRIVE
    echo "[cachedisk] moving the card cache ($(du -sh "$OLD" 2>/dev/null | cut -f1)) onto its own disk, sharing identical blocks"
    nice -n 10 python3 "$SELF/storededupe.py" ingest --delete ${host:+--host "$host"} \
        --host-min-gb "${PAD_HOST_KEEP_FREE_GB:-4}" "$OLD" "$MOVING" | tail -2
    rc=${PIPESTATUS[0]}
    [ "$rc" = 0 ] || die "$rc" "the copy stopped (exit $rc); the old cache is untouched and the next run carries on"
    in_use "$OLD" && { echo "busy the old cache is in use; copied, switching at the next run"; exit 3; }
    python3 "$SELF/storededupe.py" verify "$OLD" "$MOVING" | grep -q $'^verify\t[0-9]*\t0$' \
        || die 1 "the copy does not match the old cache; nothing switched"
    in_use "$OLD" && { echo "busy the old cache is in use; copied, switching at the next run"; exit 3; }
    n=$(find "$MOVING" -type f -name '*.raw' | wc -l)
    kb=$(du -sk "$OLD" | cut -f1)
    mv "$MOVING" "$NEW" && chown "$owner" "$NEW" || die 1 "could not put the moved cache in place"
    rm -rf "$OLD"
    echo "moved $n $kb" ;;
*)
    die 2 "usage: cachedisk.sh mkfs <dev> | move" ;;
esac
