#!/bin/bash
# The Big Lebowski menu programs, INSTALLED where mkdpmulti.py --selector-dir looks - built
# when they are missing or this checkout's sources are newer (PAD-853, the DP twin of
# tools/bof_emu/ensurebofselect.sh).
#
#   ensuredpselect.sh [--preview] [<primary zip>] [selector dir]
#
# dpselect is the same code selector the Stern card, JJP and BOF machines carry, built
# natively as ONE STATIC binary (`make PLATFORM=dp`), drawing on the X server; dpprocsw is
# its button reader, linked to the game's own libpinproc.so.2.0 by name.  Nothing of the
# machine is needed to build them; the zip argument is accepted (the tab passes it) and
# unused.  Installed flat, the layout mkdpmulti.py copies into the update's pad/ folder:
#
#     <dir>/dpselect       the menu
#     <dir>/dpprocsw       the button reader
#     <dir>/padselect.sh   the launcher, <V>/start on the machine
#     <dir>/font.ttf       DejaVuSans-Bold (when this Linux has it)
#
# Prints, on success, the two lines the Multi-boot tab reads:
#     [selector] menu program: <dir>
#     [preview] selector: <dir>/dpselect
# and `[selector] error: <why>` (exit 1) otherwise.  --preview never builds when an
# installed menu is there, even an out-of-date one: the preview draws on every redraw.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
PREVIEW=0
if [ "${1:-}" = "--preview" ]; then PREVIEW=1; shift; fi
SEL=${2:-${DP_SELECTOR_DIR:-/var/tmp/dpselect}}
BUILD=${DP_SELECTOR_BUILD:-/var/tmp/dpselect_build}
# a build folder another user made (a rig run as root) is not ours to write the log into
if [ -e "$BUILD" ] && [ ! -w "$BUILD" ]; then BUILD=$BUILD.$(id -u); fi
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
FILES="dpselect dpprocsw padselect.sh"

ok() {
    if [ ! -f "$SEL/font.ttf" ] && [ -f "$DEJAVU" ]; then
        cp "$DEJAVU" "$SEL/font.ttf" && chmod 644 "$SEL/font.ttf"
    fi
    echo "[selector] menu program: $SEL"
    echo "[preview] selector: $SEL/dpselect"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }

installed=1
for f in $FILES; do [ -f "$SEL/$f" ] || installed=0; done
if [ "$installed" = 1 ]; then
    [ "$PREVIEW" = 1 ] && ok
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect_dp.sh "$SRC"/themes.json; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$SEL/dpselect" ] && { stale=1; break; }
    done
    [ "$stale" = 0 ] && ok
    echo "[selector] out of date: the sources are newer than $SEL/dpselect"
fi

command -v gcc >/dev/null 2>&1 || fail "no gcc in this Linux to build the menu program with"
command -v make >/dev/null 2>&1 || fail "no make in this Linux to build the menu program with"
mkdir -p "$BUILD" "$SEL" || fail "cannot create $BUILD or $SEL"
log=$BUILD/make.log
if ! make -C "$SRC" PLATFORM=dp BUILD="$BUILD" all >"$log" 2>&1; then
    tail -15 "$log" | sed 's/^/[selector]   /'
    if [ "$installed" = 1 ]; then
        echo "[selector] the rebuild failed; the installed menu program is used"
        ok
    fi
    fail "the menu program did not build (make PLATFORM=dp; the log is $log)"
fi
install -m 755 "$BUILD/dpselect" "$SEL/dpselect.new" && mv -f "$SEL/dpselect.new" "$SEL/dpselect" \
    && install -m 755 "$BUILD/dpprocsw" "$SEL/dpprocsw" \
    && install -m 755 "$SRC/padselect_dp.sh" "$SEL/padselect.sh" \
    || fail "cannot install into $SEL"
ok
