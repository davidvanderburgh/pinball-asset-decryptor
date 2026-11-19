#!/bin/bash
# build.sh - PAD-1435: rebuild the machine's piece helper (padpieces.c) for both card platforms, static:
#   armv7/padpieces    Spike 2 (i.MX6, kernel 3.14): the PAD Runtime's arm-linux-gnueabihf-gcc
#   aarch64/padpieces  Spike 3: tools/spike3_emu/xgcc.sh's pinned aarch64 gcc
# Run in the PAD Runtime:  wsl.exe -d PAD-Runtime -e bash pinball_decryptor/resources/pieces/build.sh
# Then put the printed sha256 lines in remote_send.PIECES_SHA256 (the Send refuses a helper that differs).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
SRC=$(mktemp -d)
trap 'rm -rf "$SRC"' EXIT
tr -d '\r' < "$HERE/padpieces.c" > "$SRC/padpieces.c"
FLAGS="-static -O2 -s -Wall -Wextra -Wno-unused-result"
mkdir -p "$HERE/armv7" "$HERE/aarch64"
arm-linux-gnueabihf-gcc $FLAGS -o "$HERE/armv7/padpieces" "$SRC/padpieces.c"
XCC=$(bash "$ROOT/tools/spike3_emu/xgcc.sh" | tail -n 1)
"$XCC" $FLAGS -o "$HERE/aarch64/padpieces" "$SRC/padpieces.c"
cd "$HERE"
sha256sum armv7/padpieces aarch64/padpieces
