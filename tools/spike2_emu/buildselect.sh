#!/bin/bash
# buildselect.sh - build the boot selector (item 90) and install it into the
# guest rootfs, exactly where a multi-image card carries it:
#
#   $ROOT/usr/local/codeselect/codeselect    the ARM program
#   $ROOT/usr/local/codeselect/font.ttf      DejaVu Sans Bold, when this host has it
#   $ROOT/usr/local/codeselect/select.sh     the machine-side hook (not run here)
#
# run_game.sh chroots into $ROOT and runs the program before the game on a
# PAD_SELECT run; on the machine mkmulticard.py injects the same files into
# p2. ensurebuild.sh's pad_ensure_select() calls this when the binary is
# missing or its sources have moved on; by hand it is just `buildselect.sh`.
#
# THE COMPILE IS THE MAKEFILE'S, NOT THIS SCRIPT'S. The selector is an ARM
# EXECUTABLE (the shim and the bridge are shared objects) linked against the
# card's glibc 2.21, and Ubuntu's cross gcc quietly builds a GLIBC_2.34
# binary unless the rootfs is used as the sysroot BY HAND - -nostdinc and
# -nostdlib with the rootfs's own headers, crt objects and libraries, and
# --sysroot is silently ineffective (its tooldir is searched first). That
# recipe lives in codeselect/Makefile, once; this script only stages the
# sources, calls it with the two paths it takes, and lays the stamp down:
#
#   ROOT    = the rootfs used as the sysroot (headers, crt1.o, libc, libEGL)
#   DESTDIR = where /usr/local/codeselect/ is created (the same rootfs here)
#   BUILD   = where the objects go (never inside the rig: it is read-only
#             once installed under Program Files)
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT

if [ ! -f "$RIG/codeselect/Makefile" ]; then
    echo "no $RIG/codeselect/Makefile - the boot selector's sources are not in this rig" >&2
    exit 1
fi
# The rootfs IS the sysroot: without its headers and GL libraries there is
# nothing to compile against, and the error make would give names a header.
if [ ! -f "$R/usr/include/stdio.h" ] || [ ! -f "$R/usr/lib/libEGL.so.1" ]; then
    echo "no guest rootfs at $R (needs its /usr/include and /usr/lib/libEGL.so.1):" >&2
    echo "the selector is linked against the card's own glibc and GL libraries" >&2
    exit 1
fi

# The staging directory the sources are copied into, for the reason build.sh
# records: compiling from /mnt/c is slow, and Program Files is read-only.
# EVERY source on the list, and ONLY the list - PAD_SELECT_SRCS (padpath.sh)
# is also what ensurebuild.sh digests, so a file missing from it is a file
# whose edits never trigger a rebuild. A missing one stops the build here
# with its name, rather than as an `#include` error inside make.
STAGE=$HOME/emusrc
mkdir -p "$STAGE/codeselect/third_party"
for f in $PAD_SELECT_SRCS; do
    if [ ! -f "$RIG/$f" ]; then
        echo "missing source: $RIG/$f (PAD_SELECT_SRCS names it)" >&2
        exit 1
    fi
    cp "$RIG/$f" "$STAGE/$f"
done

make -C "$STAGE/codeselect" ROOT="$R" BUILD="$STAGE/codeselect/build" DESTDIR="$R" install

# The menu font. The Makefile's install copies it when the host has it; this
# is the belt to that brace, so a Makefile that leaves fonts to the installer
# still lands one. Optional: the selector falls back to the card's own
# /usr/local/spike/VeraMono.ttf, which every card carries.
DEJAVU=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
if [ ! -f "$R/usr/local/codeselect/font.ttf" ] && [ -f "$DEJAVU" ]; then
    cp "$DEJAVU" "$R/usr/local/codeselect/font.ttf"
fi

if [ ! -x "$PAD_SELECT_BIN" ]; then
    echo "make install finished but $PAD_SELECT_BIN is not there - the Makefile's install target does not put it where the rig looks" >&2
    exit 1
fi
# WHAT WAS COMPILED, recorded beside what came out of it, and only after a
# successful build (set -e) so a failed build never claims to be current.
pad_select_hash "$RIG" > "$PAD_SELECT_STAMP"
echo "built ok: $(stat -c%s "$PAD_SELECT_BIN") bytes at $PAD_SELECT_BIN"
[ -f "$R/usr/local/codeselect/font.ttf" ] && echo "font: $R/usr/local/codeselect/font.ttf" \
    || echo "font: none installed (the selector falls back to the card's VeraMono.ttf)"
