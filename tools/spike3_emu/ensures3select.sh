#!/bin/bash
# ensures3select.sh [--preview] [SRC_IGNORED] [DIR] - the Spike 3 boot menu
# (PAD-1263) built and installed into DIR (default $S3_SELECTOR_DIR or
# /var/tmp/s3select): s3select (aarch64, `make PLATFORM=s3`, linked against
# stubs of the card's display libraries, so no card is needed), the hook
# padselect.sh and font.ttf. Rebuilt only when a source is newer than the
# installed menu. The cross gcc comes from xgcc.sh (downloaded once, no
# package installed). MULTIBOOT.md.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
PREVIEW=0
if [ "${1:-}" = "--preview" ]; then PREVIEW=1; shift; fi
SEL=${2:-${S3_SELECTOR_DIR:-/var/tmp/s3select}}
BUILD=${S3_SELECTOR_BUILD:-/var/tmp/s3select_build}
if [ -e "$BUILD" ] && [ ! -w "$BUILD" ]; then BUILD=$BUILD.$(id -u); fi
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
FILES="s3select padselect.sh"
ok() {
    if [ ! -f "$SEL/font.ttf" ] && [ -f "$DEJAVU" ]; then
        cp "$DEJAVU" "$SEL/font.ttf" && chmod 644 "$SEL/font.ttf"
    fi
    echo "[selector] menu program: $SEL"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }
installed=1
for f in $FILES; do [ -f "$SEL/$f" ] || installed=0; done
if [ "$installed" = 1 ]; then
    [ "$PREVIEW" = 1 ] && ok
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect_s3.sh "$SRC"/s3_stublibs.sh "$SRC"/themes.json; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$SEL/s3select" ] && { stale=1; break; }
    done
    [ "$stale" = 0 ] && ok
    echo "[selector] out of date: the sources are newer than $SEL/s3select"
fi
command -v make >/dev/null 2>&1 || fail "no make in this Linux to build the menu program with"
mkdir -p "$BUILD" "$SEL" || fail "cannot create $BUILD or $SEL"
# the log inside BUILD: a file of another user's straight in sticky /var/tmp
# is one root itself may not reopen (fs.protected_regular)
CC=$(bash "$HERE/xgcc.sh" 2>"$BUILD/xgcc.log") || fail "no aarch64 cross gcc ($(tail -1 "$BUILD/xgcc.log" 2>/dev/null))"
log=$BUILD/make.log
if ! make -C "$SRC" PLATFORM=s3 S3CC="$CC" BUILD="$BUILD" all >"$log" 2>&1; then
    tail -15 "$log" | sed 's/^/[selector]   /'
    if [ "$installed" = 1 ]; then
        echo "[selector] the rebuild failed; the installed menu program is used"
        ok
    fi
    fail "the menu program did not build (make PLATFORM=s3; the log is $log)"
fi
install -m 755 "$BUILD/s3select" "$SEL/s3select.new" && mv -f "$SEL/s3select.new" "$SEL/s3select" \
    && install -m 755 "$SRC/padselect_s3.sh" "$SEL/padselect.sh" \
    || fail "cannot install into $SEL"
ok
