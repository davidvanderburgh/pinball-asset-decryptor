#!/bin/bash
# The Barrels of Fun menu program, INSTALLED where mkbofmulti.py --selector-dir looks -
# built when it is missing or this checkout's sources are newer (PAD-342, the BOF twin
# of tools/jjp_emu/ensurejjpselect.sh).
#
#   ensurebofselect.sh [--preview] [<primary .fun>] [selector dir]
#
# bofselect is the same code selector the Stern card and the JJP machine carry, built
# natively for x86-64 as ONE STATIC binary (`make PLATFORM=bof`): a BOF machine runs Arch
# Linux with whatever glibc its last system image had, and a static binary does not care.
# So, unlike the JJP menu, nothing of the machine is needed to build it - no root, no
# sysroot, no mount - and the .fun argument is accepted (the tab passes it) and unused.
#
# Installed flat, the layout mkbofmulti.py copies into the update's padselect/ folder:
#
#     <dir>/bofselect        the menu
#     <dir>/paddelta         the install step's program rebuilder
#     <dir>/padselect.sh     the boot hook ~/.bash_profile runs
#     <dir>/pad_install.sh   the install step update/update.sh runs
#     <dir>/font.ttf         DejaVuSans-Bold (when this Linux has it)
#
# Prints, on success, the two lines the Multi-boot tab reads:
#     [selector] menu program: <dir>
#     [preview] selector: <dir>/bofselect
# and `[selector] error: <why>` (exit 1) otherwise.  --preview never builds when an
# installed menu is there, even an out-of-date one: the preview draws on every redraw.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../spike2_emu/codeselect" && pwd)
PREVIEW=0
if [ "${1:-}" = "--preview" ]; then PREVIEW=1; shift; fi
SEL=${2:-${BOF_SELECTOR_DIR:-/var/tmp/bofselect}}
BUILD=${BOF_SELECTOR_BUILD:-/var/tmp/bofselect_build}
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
FILES="bofselect paddelta padselect.sh pad_install.sh"

ok() {
    if [ ! -f "$SEL/font.ttf" ] && [ -f "$DEJAVU" ]; then
        cp "$DEJAVU" "$SEL/font.ttf" && chmod 644 "$SEL/font.ttf"
    fi
    echo "[selector] menu program: $SEL"
    echo "[preview] selector: $SEL/bofselect"
    exit 0
}
fail() { echo "[selector] error: $*"; exit 1; }

installed=1
for f in $FILES; do [ -f "$SEL/$f" ] || installed=0; done
if [ "$installed" = 1 ]; then
    [ "$PREVIEW" = 1 ] && ok
    stale=0
    for f in "$SRC"/*.c "$SRC"/*.h "$SRC"/Makefile "$SRC"/padselect_bof.sh "$SRC"/pad_install_bof.sh "$SRC"/themes.json; do
        [ -e "$f" ] || continue
        [ "$f" -nt "$SEL/bofselect" ] && { stale=1; break; }
    done
    [ "$stale" = 0 ] && ok
    echo "[selector] out of date: the sources are newer than $SEL/bofselect"
fi

command -v gcc >/dev/null 2>&1 || fail "no gcc in this Linux to build the menu program with"
command -v make >/dev/null 2>&1 || fail "no make in this Linux to build the menu program with"
mkdir -p "$BUILD" "$SEL" || fail "cannot create $BUILD or $SEL"
log=$BUILD/make.log
if ! make -C "$SRC" PLATFORM=bof BUILD="$BUILD" all >"$log" 2>&1; then
    tail -15 "$log" | sed 's/^/[selector]   /'
    if [ "$installed" = 1 ]; then
        echo "[selector] the rebuild failed; the installed menu program is used"
        ok
    fi
    fail "the menu program did not build (make PLATFORM=bof; the log is $log)"
fi
install -m 755 "$BUILD/bofselect" "$SEL/bofselect.new" && mv -f "$SEL/bofselect.new" "$SEL/bofselect" \
    && install -m 755 "$BUILD/paddelta" "$SEL/paddelta" \
    && install -m 755 "$SRC/padselect_bof.sh" "$SEL/padselect.sh" \
    && install -m 755 "$SRC/pad_install_bof.sh" "$SEL/pad_install.sh" \
    || fail "cannot install into $SEL"
ok
