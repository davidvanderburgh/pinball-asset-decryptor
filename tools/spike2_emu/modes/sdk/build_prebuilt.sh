#!/bin/bash
# build_prebuilt.sh - rebuild the PINNED runtime object the app ships (item 127).
#
#   build_prebuilt.sh              rebuild prebuilt/mode.so and prebuilt/SOURCES.sha256
#   build_prebuilt.sh -o DIR       build into DIR instead (the reproducibility test uses this)
#
# The Modes tab plays and writes a mode FILE with no compiler anywhere: the object that
# reads mode files (the runtime + mode_file.c) is built once, here, and committed. No user
# ever builds it (the app's pinned-payloads rule). Run this after ANY change to
# pad_mode.h, pad_mode_runtime.c, mode_file.c or build_mode.sh, and commit both outputs;
# tests/test_stern_mode_runtime.py fails, naming this script, while the object is stale.
#
# Needs arm-linux-gnueabihf-gcc (the app's PAD-Runtime WSL distro has it):
#   wsl.exe -d PAD-Runtime -e bash tools/spike2_emu/modes/sdk/build_prebuilt.sh
#
# The object is REPRODUCIBLE: the sources are copied, CRs stripped, into a scratch folder
# and compiled there by build_mode.sh (so the flags are exactly a hand build's). Only the
# basenames reach the object's symbol table, never the checkout's path, so the same sources
# and the same compiler give the same bytes from any checkout, CRLF or LF.
set -euo pipefail
SDK=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT_DIR=$SDK/prebuilt
while getopts "o:" opt; do
    case $opt in
        o) OUT_DIR=$OPTARG ;;
        *) echo "usage: build_prebuilt.sh [-o DIR]" >&2; exit 2 ;;
    esac
done
CC=${CC:-arm-linux-gnueabihf-gcc}
command -v "$CC" >/dev/null || { echo "build_prebuilt.sh: $CC not found (run it in the PAD-Runtime distro)" >&2; exit 1; }
# the files the object is made from, in the order SOURCES.sha256 lists them
SOURCES="pad_mode.h pad_mode_runtime.c mode_file.c build_mode.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for f in $SOURCES; do
    tr -d '\r' < "$SDK/$f" > "$work/$f"
done
(cd "$work" && CC="$CC" bash build_mode.sh -o mode.so mode_file.c)
mkdir -p "$OUT_DIR"
cp "$work/mode.so" "$OUT_DIR/mode.so.tmp"
mv -f "$OUT_DIR/mode.so.tmp" "$OUT_DIR/mode.so"
{
    echo "# prebuilt/mode.so was built by build_prebuilt.sh from these files (CRs stripped before"
    echo "# hashing and compiling). tests/test_stern_mode_runtime.py compares them with the SDK."
    for f in $SOURCES; do
        echo "$(sha256sum "$work/$f" | cut -d' ' -f1)  $f"
    done
    echo "$(sha256sum "$OUT_DIR/mode.so" | cut -d' ' -f1)  mode.so"
    echo "compiler $("$CC" --version | head -1)"
} > "$OUT_DIR/SOURCES.sha256.tmp"
mv -f "$OUT_DIR/SOURCES.sha256.tmp" "$OUT_DIR/SOURCES.sha256"
echo "pinned $OUT_DIR/mode.so ($(stat -c %s "$OUT_DIR/mode.so") bytes) and SOURCES.sha256"
