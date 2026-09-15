#!/bin/bash
# The JJP menu program, INSTALLED where mkjjpmulti.py --selector-dir looks -
# built when it is missing or this checkout's sources are newer (item 118, the
# JJP twin of tools/spike2_emu/ensureselect.sh).
#
#   ensurejjpselect.sh [--preview] <install ISO> [selector dir]
#
# jjpselect is the same code selector the Stern card carries, compiled natively
# for x86-64 against a JJP root's OWN glibc 2.34 and libraries (item 114:
# `make PLATFORM=jjp JJPROOT=<root>`).  The link reads nothing of that root but
# the libraries the Makefile names and what those need in turn, so they are
# copied ONCE into a small sysroot ($SYSROOT, a few MB) and every build links
# against that: seconds, nothing mounted, nothing restored.
#
# WHERE THE SYSROOT COMES FROM, cheapest first:
#   1. a JJP root already mounted (the emulator's /var/tmp/jjp_<slug>/root)
#   2. a root already restored (/var/tmp/jjp_<slug>/sda3.raw, the given ISO's
#      own first), loop-mounted read-only at a private mount point for the copy
#   3. a writing run only: the given ISO's root partition ALONE, restored into
#      the rig's cache by `mount.sh --root-only` - no sda5/sda2/sda4, and no
#      switch of the emulator's current image
#
# --PREVIEW is the Multi-boot tab's load and every redraw, and it NEVER
# restores.  This step used to hand a loaded multi-boot ISO to mount.sh whole:
# sda3, sda5, sda2 and sda4 of a 13 GB ISO restored with the output thrown
# away, the tab sitting on "rendering..." for ten minutes, to compile a program
# the ISO already carries (David, 2026-09-15: "it should just be touching the
# multi-boot menu portion, not the whole entire image").  When 1 and 2 find
# nothing, the preview draws with a menu program that is already here: the
# ISO's own /jjp/padselect/jjpselect (read off the ISO by xorriso, a few
# hundred KB), else the installed one even when the sources have moved on.
# Only the preview's line is printed then, so a writing run still builds.
#
# The result is installed as `make install` lays it out - the card's own
# layout, which mkjjpmulti.py accepts as a --selector-dir:
#
#     <dir>/jjpe/gen1/padselect/jjpselect     the menu program
#     <dir>/jjpe/gen1/padselect/font.ttf      DejaVuSans-Bold (the card's own)
#     <dir>/jjpe/gen1/scripts/padselect.sh    the hook rungame.sh runs
#
# Prints, on success, the two lines the Multi-boot tab reads:
#     [selector] menu program: <dir>
#     [preview] selector: <dir>/jjpe/gen1/padselect/jjpselect
# and `[selector] error: <why>` (exit 1) otherwise.  Root (the loop mounts).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
PREVIEW=0
if [ "${1:-}" = "--preview" ]; then PREVIEW=1; shift; fi
ISO=${1:-}
SEL=${2:-${JJP_SELECTOR_DIR:-/var/tmp/jjpselect}}
BUILD=${JJP_SELECTOR_BUILD:-/var/tmp/jjpselect_build}
SYSROOT=${JJP_SELECTOR_SYSROOT:-/var/tmp/jjpselect_sysroot}
PVDIR=${JJP_SELECTOR_PREVIEW:-/var/tmp/jjpselect_preview}
#: the rig's restore caches (padpath.sh's JJP_BASE, one per ISO)
CACHES=${JJP_SELECTOR_CACHES:-/var/tmp/jjp_*}
BIN=$SEL/jjpe/gen1/padselect/jjpselect
HOOK=$SEL/jjpe/gen1/scripts/padselect.sh
FONT=$SEL/jjpe/gen1/padselect/font.ttf
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
LIB=usr/lib/x86_64-linux-gnu
MNT=""

say() { echo "[selector] $*"; }
ok() {
    echo "[selector] menu program: $SEL"
    echo "[preview] selector: $BIN"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }
cleanup() {
    if [ -n "$MNT" ]; then
        umount "$MNT" 2>/dev/null || umount -l "$MNT" 2>/dev/null
        rmdir "$MNT" 2>/dev/null
    fi
    rm -rf "$SYSROOT.tmp.$$"
}
trap cleanup EXIT

[ "$(id -u)" = "0" ] || fail "must run as root (wsl -u root): the menu program is built against a JJP root, which is loop-mounted"

# Up to date: every source, the hook and the Makefile older than the binary.
if [ -x "$BIN" ] && [ -f "$HOOK" ]; then
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect.sh; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$BIN" ] && { stale=1; break; }
    done
    [ "$stale" = "0" ] && ok
    say "out of date: the sources are newer than $BIN"
fi

export JJP_ISO=$ISO
. "$HERE/padpath.sh"

# THE LIBRARIES, read off the Makefile's JJPROOT link line rather than listed
# a second time here.
LINKED=$(awk '/^ifneq \(\$\(JJPROOT\),\)/ { f = 1; next } f && /^else/ { exit } f' "$SRC/Makefile" \
    | grep -oE -e '-l:[^ ]+' | sed 's/^-l://' | tr '\n' ' ')
[ -n "${LINKED// /}" ] || fail "no -l: libraries found in the JJPROOT link line of $SRC/Makefile"

sysroot_ok() { [ -f "$SYSROOT/.complete" ] && [ -f "$SYSROOT/$LIB/libc.so.6" ]; }

# A path inside ROOT with its symlinks followed INSIDE the root: an absolute
# link (/lib64/ld-linux-x86-64.so.2) would otherwise resolve on this host.
in_root() {
    local root=$1 p=$2 t i=0
    while [ -L "$root/$p" ] && [ $i -lt 20 ]; do
        t=$(readlink "$root/$p")
        case "$t" in
            /*) p=${t#/} ;;
            *) p=$(dirname "$p")/$t ;;
        esac
        i=$((i + 1))
    done
    [ -f "$root/$p" ] && [ ! -L "$root/$p" ] && printf '%s\n' "$root/$p"
}

# A mounted root -> $SYSROOT: the linked libraries and everything they NEED,
# under the two directories the Makefile points -L and -rpath-link at.
seed_sysroot() {
    local root=$1 from=$2 tmp="$SYSROOT.tmp.$$" queue n f sub dst seen=" "
    [ -e "$root/$LIB/libc.so.6" ] || return 1
    rm -rf "$tmp"
    mkdir -p "$tmp/$LIB/pulseaudio" || return 1
    queue=$LINKED
    while [ -n "${queue// /}" ]; do
        set -- $queue
        n=$1; shift; queue="$*"
        case "$seen" in *" $n "*) continue ;; esac
        seen="$seen$n "
        f=""
        for sub in "$LIB" "$LIB/pulseaudio"; do
            f=$(in_root "$root" "$sub/$n") && { dst=$tmp/$sub/$n; break; }
        done
        if [ -z "$f" ]; then
            # the loader is libc's own NEEDED; the link finds it without a copy
            case "$n" in ld-linux*) continue ;; esac
            say "$from has no $n - not a root to build against"
            rm -rf "$tmp"; return 1
        fi
        # a torn restore reads back as zeroes: take nothing that is not an ELF
        if ! readelf -h "$f" >/dev/null 2>&1; then
            say "$from: $n is not a readable ELF - not a root to build against"
            rm -rf "$tmp"; return 1
        fi
        cp "$f" "$dst" || { rm -rf "$tmp"; return 1; }
        queue="$queue $(readelf -d "$f" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | tr '\n' ' ')"
    done
    echo "$from" > "$tmp/.complete"
    rm -rf "$SYSROOT" && mv "$tmp" "$SYSROOT" || return 1
    say "sysroot: $(find "$SYSROOT/$LIB" -type f -name '*.so*' | wc -l) libraries copied once from $from into $SYSROOT"
}

# A restored root image, loop-mounted read-only at a PRIVATE mount point (never
# the rig's own, which a game may be running on) for the copy, then let go.
seed_from_raw() {
    local raw=$1 rc=1
    MNT=$(mktemp -d /var/tmp/jjpselect_mnt.XXXXXX) || return 1
    if mount -o ro,loop,noload "$raw" "$MNT" 2>/dev/null || mount -o ro,loop "$raw" "$MNT" 2>/dev/null; then
        seed_sysroot "$MNT" "$raw"; rc=$?
        umount "$MNT" 2>/dev/null || umount -l "$MNT" 2>/dev/null
    fi
    rmdir "$MNT" 2>/dev/null
    MNT=""
    return $rc
}

# 1 and 2 above: a root this PC already has, and no restore.
sysroot_from_disk() {
    local d raw
    for d in $CACHES; do
        [ -d "$d/root" ] && mountpoint -q "$d/root" || continue
        seed_sysroot "$d/root" "$d/root" && return 0
    done
    for raw in "$JJP_BASE/sda3.raw" $CACHES/sda3.raw; do
        [ -s "$raw" ] || continue
        # still being written (an older rig restored in place, not to .part)
        [ -n "$(find "$raw" -mmin -1 2>/dev/null)" ] && continue
        seed_from_raw "$raw" && return 0
    done
    return 1
}

build() {
    mkdir -p "$BUILD" "$SEL" || return 1
    if ! make -C "$SRC" PLATFORM=jjp BUILD="$BUILD" JJPROOT="$SYSROOT" all >"$BUILD/make.log" 2>&1 \
        || ! make -C "$SRC" PLATFORM=jjp BUILD="$BUILD" JJPROOT="$SYSROOT" DESTDIR="$SEL" install >>"$BUILD/make.log" 2>&1; then
        tail -n 12 "$BUILD/make.log"
        return 1
    fi
    [ -x "$BIN" ] && [ -f "$HOOK" ]
}

# --preview with nothing to build against: a menu program that is already here.
preview_without_a_build() {
    local iso d stamp src
    iso=$(jjp_norm_path "$ISO")
    if [ -n "$ISO" ] && [ -f "$iso" ]; then
        d=$PVDIR/$(jjp_slug "$iso")
        stamp="$iso $(stat -c '%s %Y' "$iso")"
        if [ ! -x "$d/jjpselect" ] || [ "$(cat "$d/.from" 2>/dev/null)" != "$stamp" ]; then
            rm -rf "$d.tmp"
            mkdir -p "$d.tmp"
            if xorriso -report_about SORRY -osirrox on -indev "$iso" \
                    -extract /jjp/padselect/jjpselect "$d.tmp/jjpselect" -- >/dev/null 2>&1 \
                    && [ -s "$d.tmp/jjpselect" ]; then
                xorriso -report_about SORRY -osirrox on -indev "$iso" \
                    -extract /jjp/padselect/font.ttf "$d.tmp/font.ttf" -- >/dev/null 2>&1
                chmod 755 "$d.tmp/jjpselect"
                echo "$stamp" > "$d.tmp/.from"
                rm -rf "$d" && mv "$d.tmp" "$d"
            else
                rm -rf "$d.tmp"
            fi
        fi
        if [ -x "$d/jjpselect" ]; then
            # the conf the tab writes names the installed font
            if [ ! -f "$FONT" ]; then
                src=$DEJAVU
                [ -s "$d/font.ttf" ] && src=$d/font.ttf
                install -D -m 644 "$src" "$FONT" 2>/dev/null
            fi
            say "the preview draws with the menu program $(basename "$iso") carries: no JJP root is on this PC to build a current one against, and a load restores nothing (a build does, once)"
            echo "[preview] selector: $d/jjpselect"
            exit 0
        fi
    fi
    if [ -x "$BIN" ]; then
        say "the preview draws with the installed menu program, which is older than the sources: a build makes a current one"
        echo "[preview] selector: $BIN"
        exit 0
    fi
    fail "there is no menu program to draw the preview with yet: this ISO carries none, none is installed, and no JJP root is on this PC to build one against without restoring an image. Build makes one (it restores the first ISO's root partition, once)."
}

sysroot_ok || sysroot_from_disk
if ! sysroot_ok && [ "$PREVIEW" = "0" ]; then
    [ -n "$ISO" ] || fail "no install ISO given, and no JJP root is on this PC: the menu program is built against the ISO's own libraries"
    [ -f "$(jjp_norm_path "$ISO")" ] || fail "no such ISO: $ISO"
    say "no JJP root is on this PC yet: restoring the root partition of $(basename "$(jjp_norm_path "$ISO")") alone, to build against (minutes, once)"
    bash "$HERE/mount.sh" --root-only "$ISO" 2>&1 | sed -u 's/^/[selector] /'
    [ "${PIPESTATUS[0]}" = "0" ] || fail "restoring the root partition of $ISO failed - see the lines above"
    seed_from_raw "$JJP_BASE/sda3.raw" || fail "$JJP_BASE/sda3.raw is not a JJP root the menu program can be built against - see the lines above"
fi
if sysroot_ok; then
    build && ok
    [ "$PREVIEW" = "1" ] || fail "building jjpselect failed (see $BUILD/make.log)"
    say "building jjpselect failed (see $BUILD/make.log)"
fi
preview_without_a_build
