#!/bin/bash
# Build padtrace.so - the TRACE-ONLY tap for the real machine (item 43).
# Same recipe as build.sh (hwshim): armhf, -nostdlib, linked against the CARD'S
# OWN libc/libdl/librt so its glibc-2.21 symbol versions match the machine.
# Output: $ROOT/lib/padtrace.so, and a copy at $OUT for packaging onto a card.
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT
OUT="${1:-$HOME/padtrace.so}"
mkdir -p "$HOME/emusrc"
cp "$RIG/padtrace.c" "$HOME/emusrc/padtrace.c"
arm-linux-gnueabihf-gcc -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Werror=implicit-function-declaration \
  -Wl,-soname,padtrace.so -o "$R/lib/padtrace.so" \
  "$HOME/emusrc/padtrace.c" \
  -L"$R/lib" -l:libdl.so.2 -l:libc.so.6 -l:librt.so.1
cp "$R/lib/padtrace.so" "$OUT"
echo "built ok: $(ls -l "$R/lib/padtrace.so" | awk '{print $5}') bytes -> $OUT"
echo "=== NEEDED (must all resolve on the machine's glibc 2.21) ==="
arm-linux-gnueabihf-objdump -p "$R/lib/padtrace.so" | grep -aE "NEEDED|GLIBC_2\.[0-9]+" | sort -u
