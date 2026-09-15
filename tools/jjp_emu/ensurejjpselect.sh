#!/bin/bash
# The JJP menu program, INSTALLED where mkjjpmulti.py --selector-dir looks -
# built when it is missing or this checkout's sources are newer (item 118, the
# JJP twin of tools/spike2_emu/ensureselect.sh).
#
#   ensurejjpselect.sh <install ISO> [selector dir]
#
# jjpselect is the same code selector the Stern card carries, compiled natively
# for x86-64 against the JJP root's OWN glibc 2.34 and libraries (item 114:
# `make PLATFORM=jjp JJPROOT=<mounted root>`), so a root has to be mounted to
# build it: mount.sh restores and mounts the ISO the way the emulator does
# (cached under /var/tmp/jjp_<slug>, shared with the builder and the rig).
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
# and `[selector] error: <why>` (exit 1) otherwise.  Root (the mount).
#
# A LIVE RIG IS NEVER DISTURBED: mount.sh switches the emulator's current
# image, so when a game is running on a DIFFERENT image this refuses with a
# sentence rather than pulling the root out from under it.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
ISO=${1:-}
SEL=${2:-${JJP_SELECTOR_DIR:-/var/tmp/jjpselect}}
BUILD=${JJP_SELECTOR_BUILD:-/var/tmp/jjpselect_build}
BIN=$SEL/jjpe/gen1/padselect/jjpselect
HOOK=$SEL/jjpe/gen1/scripts/padselect.sh

ok() {
    echo "[selector] menu program: $SEL"
    echo "[preview] selector: $BIN"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }

[ -n "$ISO" ] || fail "no install ISO given: the menu program is built against the ISO's own root"
[ "$(id -u)" = "0" ] || fail "must run as root (wsl -u root): building the menu program mounts the ISO's root"

# Up to date: every source, the hook and the Makefile older than the binary.
if [ -x "$BIN" ] && [ -f "$HOOK" ]; then
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect.sh; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$BIN" ] && { stale=1; break; }
    done
    [ "$stale" = "0" ] && ok
    echo "[selector] rebuilding: the sources are newer than $BIN"
fi

export JJP_ISO=$ISO
. "$HERE/padpath.sh"
[ -f "$(jjp_norm_path "$ISO")" ] || fail "no such ISO: $ISO"

# A game on ANOTHER image: mount.sh would switch it away.  Refuse.
if [ "$(jjp_game_count)" != "0" ] && [ -r "$JJP_CURRENT" ] && [ "$(cat "$JJP_CURRENT")" != "$JJP_BASE" ]; then
    fail "a JJP game is running on another image ($(cat "$JJP_CURRENT")); stop it first, or build the menu program later"
fi

mountpoint -q "$JJP_ROOT" || bash "$HERE/mount.sh" "$ISO" >/dev/null || fail "mount.sh could not restore and mount $ISO"
[ -d "$JJP_ROOT/usr/lib/x86_64-linux-gnu" ] || fail "$JJP_ROOT is not a JJP root (no usr/lib/x86_64-linux-gnu)"

mkdir -p "$BUILD" "$SEL"
if ! make -C "$SRC" PLATFORM=jjp BUILD="$BUILD" JJPROOT="$JJP_ROOT" all >"$BUILD/make.log" 2>&1; then
    tail -n 12 "$BUILD/make.log"
    fail "building jjpselect failed (see $BUILD/make.log)"
fi
if ! make -C "$SRC" PLATFORM=jjp BUILD="$BUILD" JJPROOT="$JJP_ROOT" DESTDIR="$SEL" install >>"$BUILD/make.log" 2>&1; then
    tail -n 12 "$BUILD/make.log"
    fail "installing jjpselect into $SEL failed (see $BUILD/make.log)"
fi
[ -x "$BIN" ] || fail "the install left no $BIN"
[ -f "$HOOK" ] || fail "the install left no $HOOK"
ok
