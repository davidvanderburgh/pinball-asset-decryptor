#!/bin/bash
# build_prebuilt.sh - rebuild the PINNED runtime object the app ships (item 127).
#
#   build_prebuilt.sh              rebuild prebuilt/mode.so and prebuilt/SOURCES.sha256
#   build_prebuilt.sh -o DIR       build into DIR instead (the reproducibility test uses this)
#
# The Modes tab plays and writes a mode FILE with no compiler anywhere: the object that
# reads mode files (the runtime + mode_file.c) is built once, here, and committed. No user
# ever builds it (the app's pinned-payloads rule). Run this after ANY change to
# pad_mode.h, pad_stock.h, pad_mode_runtime.c, mode_file.c or build_mode.sh, and commit both outputs;
# tests/test_stern_mode_runtime.py fails, naming this script, while the object is stale.
#
# Needs arm-linux-gnueabihf-gcc (the app's PAD-Runtime WSL distro has it):
#   wsl.exe -d PAD-Runtime -e bash tools/spike2_emu/modes/sdk/build_prebuilt.sh
#
# The object is REPRODUCIBLE: the sources are copied, CRs stripped, into a scratch folder
# and compiled there by build_mode.sh (so the flags are exactly a hand build's). Only the
# basenames reach the object's symbol table, never the checkout's path, so the same sources
# and the same compiler give the same bytes from any checkout, CRLF or LF.
#
# PAD-1269: -a a64 pins the 64-bit ARM object the Spike 3 machine loads (prebuilt/mode64.so,
# recorded in prebuilt/SOURCES64.sha256), built with the rig's aarch64 cross gcc from xgcc.sh.
# Its source set adds hook_a64.h (the 64-bit hook layer pad_mode_runtime.c includes there). The
# default, arm, is unchanged, so prebuilt/mode.so stays byte-for-byte what it always was.
#   wsl.exe -e bash -c 'CC=$(bash .../xgcc.sh) bash .../build_prebuilt.sh -a a64'
set -euo pipefail
SDK=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT_DIR=$SDK/prebuilt
ARCH=arm
while getopts "o:a:" opt; do
    case $opt in
        o) OUT_DIR=$OPTARG ;;
        a) ARCH=$OPTARG ;;
        *) echo "usage: build_prebuilt.sh [-a arm|a64] [-o DIR]" >&2; exit 2 ;;
    esac
done
# the files the object is made from, in the order the SOURCES file lists them, and the object's name
case $ARCH in
    arm) CC=${CC:-arm-linux-gnueabihf-gcc}
         SOURCES="pad_mode.h pad_stock.h pad_mode_runtime.c mode_file.c build_mode.sh"
         OBJ=mode.so; SUMS=SOURCES.sha256 ;;
    a64) CC=${CC:-$(bash "$SDK/../../../spike3_emu/xgcc.sh")}
         SOURCES="pad_mode.h pad_stock.h hook_a64.h pad_mode_runtime.c mode_file.c build_mode.sh"
         OBJ=mode64.so; SUMS=SOURCES64.sha256 ;;
    *)   echo "build_prebuilt.sh: unknown -a $ARCH (arm or a64)" >&2; exit 2 ;;
esac
command -v "$CC" >/dev/null || { echo "build_prebuilt.sh: $CC not found (run it in the PAD-Runtime distro, or with CC from xgcc.sh for a64)" >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for f in $SOURCES; do
    tr -d '\r' < "$SDK/$f" > "$work/$f"
done
(cd "$work" && CC="$CC" bash build_mode.sh -a "$ARCH" -o "$OBJ" mode_file.c)
mkdir -p "$OUT_DIR"
cp "$work/$OBJ" "$OUT_DIR/$OBJ.tmp"
mv -f "$OUT_DIR/$OBJ.tmp" "$OUT_DIR/$OBJ"
{
    echo "# prebuilt/$OBJ was built by build_prebuilt.sh from these files (CRs stripped before"
    echo "# hashing and compiling). tests/test_stern_mode_runtime.py compares them with the SDK."
    for f in $SOURCES; do
        echo "$(sha256sum "$work/$f" | cut -d' ' -f1)  $f"
    done
    echo "$(sha256sum "$OUT_DIR/$OBJ" | cut -d' ' -f1)  $OBJ"
    echo "compiler $("$CC" --version | head -1)"
} > "$OUT_DIR/$SUMS.tmp"
mv -f "$OUT_DIR/$SUMS.tmp" "$OUT_DIR/$SUMS"
echo "pinned $OUT_DIR/$OBJ ($(stat -c %s "$OUT_DIR/$OBJ") bytes) and $SUMS"
