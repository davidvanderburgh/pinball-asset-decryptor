#!/bin/bash
# storexfs.sh - the XFS tools the card store needs, without installing anything (PAD-1453).
#
#   storexfs.sh tools          fetch xfsprogs (+ libinih, liburcu) into $XFS_PREFIX once; prints mkfs.xfs's path
#   storexfs.sh mkfs <dev> [label]  format <dev> XFS with reflink (what lets two files share blocks), label "cards"
#   storexfs.sh busy           prints every process using the store (open file, cwd, a card mounted from it)
#
# Run as root. The packages are this distro's own, fetched with `apt-get download` and unpacked with dpkg-deb -x
# into a private folder - the way cardmount.sh brings fuse2fs - so no package is installed and nothing in the system
# changes. mkfs.xfs is the only one of them the store ever runs; the kernel's XFS driver is built into WSL's.
#
# PINNED FOR USERS (PAD-1459). A user's card cache is made XFS by the app (rigdata.ensure_cache_disk), so this runs
# on machines we cannot see - and no user ever resolves a dependency. On PAD-Runtime (Ubuntu 24.04 "noble", its
# apt pointed at one fixed snapshot) the three packages are fetched by URL from that same snapshot and checked
# against the SHA-512 below before anything is unpacked: the exact bytes this was proven with, or nothing. Only a
# distro of another release (a developer's own) falls back to `apt-get download`. A mkfs.xfs the system already
# has (xfsprogs installed) wins over both.
XFS_PINNED_BASE=${XFS_PINNED_BASE:-https://snapshot.ubuntu.com/ubuntu/20260801T000000Z/pool/main}
XFS_PINNED="
x/xfsprogs/xfsprogs_6.6.0-1ubuntu2.1_amd64.deb 7cfe18cddb6f1fc4b63797faf340e8f9a8f315e54fb4e253e6e0c7606ef3fba72417b3dd399331e1b9a1a9763a51458fbf6ea3d0288f567f2dfc32313537b02e
libi/libinih/libinih1_55-1ubuntu2_amd64.deb 1b51c1e86dd65e999761494dfa99514636ffbd496231eaa0d545d68b566abcb94884ff3b9bee59fd438787a7e8420dd7b915bc1753a65fc1f02acdb3d710984b
libu/liburcu/liburcu8t64_0.14.0-3.1build1_amd64.deb a7906dd2781707be9ac7ce6807d84a50c36d499bd0f833a0e6a4a25708daaacb307c20fab274dc6440bbafe2bef1f628a523fb1ead8eb8870e4d0fc2bbb4ca5e
"
set -u
XFS_PREFIX=${XFS_PREFIX:-/var/lib/pad_xfstools}
STORE=${STORE:-/mnt/wsl/cards}
LD_LIBRARY_PATH="$XFS_PREFIX/lib/x86_64-linux-gnu:$XFS_PREFIX/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export LD_LIBRARY_PATH

die() { echo "[storexfs] $*" >&2; exit 1; }

mkfs_path() {
    local m
    for m in /usr/sbin/mkfs.xfs /sbin/mkfs.xfs "$XFS_PREFIX/sbin/mkfs.xfs" "$XFS_PREFIX/usr/sbin/mkfs.xfs"; do
        [ -x "$m" ] && "$m" -V >/dev/null 2>&1 && { echo "$m"; return 0; }
    done
    return 1
}

fetch_url() {   # <url> <file>
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 2 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        python3 -c 'import sys, urllib.request; open(sys.argv[2], "wb").write(urllib.request.urlopen(sys.argv[1], timeout=120).read())' "$1" "$2"
    fi
}

pinned() {   # <dir>: the pinned packages into <dir>, every one hash-checked; 1 when this is not the pinned release
    local rel arch rest sum f
    rel=$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-}")
    arch=$(dpkg --print-architecture 2>/dev/null)
    [ "$rel" = noble ] && [ "$arch" = amd64 ] || return 1
    while read -r rest sum; do
        [ -n "$rest" ] || continue
        f="$1/${rest##*/}"
        fetch_url "$XFS_PINNED_BASE/$rest" "$f" || { echo "[storexfs] could not download $XFS_PINNED_BASE/$rest" >&2; return 2; }
        [ "$(sha512sum "$f" | cut -d' ' -f1)" = "$sum" ] || { echo "[storexfs] ${rest##*/} is not the pinned file (SHA-512 differs) - refused" >&2; rm -f "$f"; return 2; }
    done <<< "$XFS_PINNED"
}

tools() {
    mkfs_path && return 0
    echo "[storexfs] fetching xfsprogs into $XFS_PREFIX (once)" >&2
    local d p x rc got=0
    d=$(mktemp -d /var/tmp/storexfs.XXXXXX) || die "no temp folder"
    chmod 755 "$d"
    pinned "$d"; rc=$?
    [ "$rc" = 2 ] && { rm -rf "$d"; die "the pinned xfsprogs could not be fetched"; }
    [ "$rc" = 0 ] ||     # the urcu library was renamed for the 64-bit time_t move (24.04: liburcu8t64); either serves
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
        "$m" -q -f -m reflink=1,crc=1 -L "${3:-cards}" "$dev" && echo formatted ;;
    busy) busy ;;
    *) die "usage: storexfs.sh tools | mkfs <dev> [label] | busy" ;;
esac
