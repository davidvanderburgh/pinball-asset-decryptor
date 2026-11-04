#!/bin/bash
# The Spooky Pinball menu programs, INSTALLED where mkspkmulti.py --selector-dir looks - built
# when they are missing or this checkout's sources are newer (PAD-980, the Spooky twin of
# tools/dp_emu/ensuredpselect.sh).
#
#   ensurespkselect.sh [--preview] [<primary zip>] [selector dir]
#
# spkselect is the same code selector the Stern card, JJP and BOF machines carry, built
# natively as ONE STATIC binary (`make PLATFORM=spk`), drawing on the X server; spksw is
# its button reader on the playfield board's tty, static too.  Nothing of the machine is
# needed to build them; the update argument is accepted (the tab passes it) and unused.  Installed flat, the layout mkspkmulti.py copies into the update's pad/ folder:
#
#     <dir>/spkselect      the menu
#     <dir>/spksw          the button reader
#     <dir>/padselect.sh   the launcher, uptest/main.x86_64 on the machine
#     <dir>/dpprocsw, <dir>/padselect_proc.sh   the P-ROC titles' reader and launcher
#     <dir>/font.ttf       DejaVuSans-Bold (when this Linux has it)
#
# Prints, on success, the two lines the Multi-boot tab reads:
#     [selector] menu program: <dir>
#     [preview] selector: <dir>/spkselect
# and `[selector] error: <why>` (exit 1) otherwise.  --preview never builds when an
# installed menu is there, even an out-of-date one: the preview draws on every redraw.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
PREVIEW=0
if [ "${1:-}" = "--preview" ]; then PREVIEW=1; shift; fi
SEL=${2:-${SPK_SELECTOR_DIR:-/var/tmp/spkselect}}
BUILD=${SPK_SELECTOR_BUILD:-/var/tmp/spkselect_build}
# a build folder another user made (a rig run as root) is not ours to write the log into
if [ -e "$BUILD" ] && [ ! -w "$BUILD" ]; then BUILD=$BUILD.$(id -u); fi
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
FILES="spkselect spksw padselect.sh dpprocsw padselect_proc.sh"

ok() {
    if [ ! -f "$SEL/font.ttf" ] && [ -f "$DEJAVU" ]; then
        cp "$DEJAVU" "$SEL/font.ttf" && chmod 644 "$SEL/font.ttf"
    fi
    echo "[selector] menu program: $SEL"
    echo "[preview] selector: $SEL/spkselect"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }

installed=1
for f in $FILES; do [ -f "$SEL/$f" ] || installed=0; done
if [ "$installed" = 1 ]; then
    [ "$PREVIEW" = 1 ] && ok
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect_spk.sh "$SRC"/padselect_proc.sh "$SRC"/themes.json; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$SEL/spkselect" ] && { stale=1; break; }
    done
    [ "$stale" = 0 ] && ok
    echo "[selector] out of date: the sources are newer than $SEL/spkselect"
fi

command -v gcc >/dev/null 2>&1 || fail "no gcc in this Linux to build the menu program with"
command -v make >/dev/null 2>&1 || fail "no make in this Linux to build the menu program with"
mkdir -p "$BUILD" "$SEL" || fail "cannot create $BUILD or $SEL"
log=$BUILD/make.log
if ! make -C "$SRC" PLATFORM=spk BUILD="$BUILD" all >"$log" 2>&1; then
    tail -15 "$log" | sed 's/^/[selector]   /'
    if [ "$installed" = 1 ]; then
        echo "[selector] the rebuild failed; the installed menu program is used"
        ok
    fi
    fail "the menu program did not build (make PLATFORM=spk; the log is $log)"
fi
install -m 755 "$BUILD/spkselect" "$SEL/spkselect.new" && mv -f "$SEL/spkselect.new" "$SEL/spkselect" \
    && install -m 755 "$BUILD/spksw" "$SEL/spksw" \
    && install -m 755 "$SRC/padselect_spk.sh" "$SEL/padselect.sh" \
    && install -m 755 "$BUILD/dpprocsw" "$SEL/dpprocsw" \
    && install -m 755 "$SRC/padselect_proc.sh" "$SEL/padselect_proc.sh" \
    || fail "cannot install into $SEL"
ok
