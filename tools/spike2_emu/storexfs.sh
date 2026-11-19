#!/bin/bash
# storexfs.sh - the XFS tools the card store needs, without installing anything (PAD-1453).
#
#   storexfs.sh tools          fetch xfsprogs (+ libinih, liburcu) into $XFS_PREFIX once; prints mkfs.xfs's path
#   storexfs.sh mkfs <dev>     format <dev> XFS with reflink (what lets two files share blocks), label "cards"
#   storexfs.sh busy           prints every process using the store (open file, cwd, a card mounted from it)
#
# Run as root. The packages are this distro's own, fetched with `apt-get download` and unpacked with dpkg-deb -x
# into a private folder - the way cardmount.sh brings fuse2fs - so no package is installed and nothing in the system
# changes. mkfs.xfs is the only one of them the store ever runs; the kernel's XFS driver is built into WSL's.
set -u
XFS_PREFIX=${XFS_PREFIX:-/var/lib/pad_xfstools}
STORE=${STORE:-/mnt/wsl/cards}
LD_LIBRARY_PATH="$XFS_PREFIX/lib/x86_64-linux-gnu:$XFS_PREFIX/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export LD_LIBRARY_PATH

die() { echo "[storexfs] $*" >&2; exit 1; }

mkfs_path() {
    local m
    for m in "$XFS_PREFIX/sbin/mkfs.xfs" "$XFS_PREFIX/usr/sbin/mkfs.xfs"; do
        [ -x "$m" ] && "$m" -V >/dev/null 2>&1 && { echo "$m"; return 0; }
    done
    return 1
}

tools() {
    mkfs_path && return 0
    echo "[storexfs] fetching xfsprogs into $XFS_PREFIX (once)" >&2
    local d p got=0
    d=$(mktemp -d /var/tmp/storexfs.XXXXXX) || die "no temp folder"
    chmod 755 "$d"
    # the urcu library was renamed for the 64-bit time_t move (24.04: liburcu8t64); either serves
    for p in xfsprogs libinih1 "liburcu8t64 liburcu8"; do
        got=0
        for x in $p; do
            ( cd "$d" && apt-get download "$x" >/dev/null 2>&1 ) && { got=1; break; }
        done
        [ "$got" = 1 ] || { rm -rf "$d"; die "could not download $p (apt-get download)"; }
    done
    mkdir -p "$XFS_PREFIX"
    for p in "$d"/*.deb; do dpkg-deb -x "$p" "$XFS_PREFIX" || { rm -rf "$d"; die "could not unpack $p"; }; done
    rm -rf "$d"
    mkfs_path || die "unpacked xfsprogs, and mkfs.xfs does not run (ldd: $(ldd "$XFS_PREFIX/sbin/mkfs.xfs" 2>&1 | grep 'not found' | tr '\n' ' '))"
}

busy() {
    # a card mounted from the store (fuse2fs has the image's path as an argument), a file open, a cwd inside it
    local q a
    for q in /proc/[0-9]*; do
        [ "${q#/proc/}" = "$$" ] && continue
        if readlink "$q/cwd" "$q"/fd/* 2>/dev/null | grep -q "^$STORE/"; then
            echo "${q#/proc/} $(cat "$q/comm" 2>/dev/null)"; continue
        fi
        while IFS= read -r -d '' a; do
            case $a in "$STORE"/*) echo "${q#/proc/} $(cat "$q/comm" 2>/dev/null)"; break ;; esac
        done < "$q/cmdline" 2>/dev/null
    done
    true
}

case ${1:-} in
    tools) tools ;;
    mkfs)
        dev=${2:-}; [ -b "$dev" ] || die "usage: storexfs.sh mkfs <block device>"
        m=$(tools) || exit 1
        # reflink=1: files may share blocks (FIDEDUPERANGE, cp --reflink); crc=1 is the default it needs
        "$m" -q -f -m reflink=1,crc=1 -L cards "$dev" && echo formatted ;;
    busy) busy ;;
    *) die "usage: storexfs.sh tools | mkfs <dev> | busy" ;;
esac
