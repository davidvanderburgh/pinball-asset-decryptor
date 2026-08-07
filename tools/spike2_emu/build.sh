#!/bin/bash
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT
# The staging directory the sources are copied into. Created here: it
# was simply assumed to exist, which is fine on the machine where it was
# made by hand once and is a `cp: No such file or directory` on any
# other. Compiling from /mnt/c is what it avoids - drvfs is slow enough
# to matter over a few thousand lines of C.
mkdir -p "$HOME/emusrc"
# Sync EVERY source this build compiles, and COMPILE THE SAME LIST. alsastub.c
# used to be missing from the copy list while still being on the compile line,
# so an edit to the Windows copy was silently never built - and the build still
# said "built ok". It only surfaced as `undefined symbol` at guest start, one
# full run later. Both halves now come from PAD_SHIM_SRCS (padpath.sh), so the
# two cannot disagree again, and watch.sh's staleness check reads the same list.
CC_SRCS=()
for f in $PAD_SHIM_SRCS; do
    cp "$RIG/$f" "$HOME/emusrc/$f"
    case $f in *.c) CC_SRCS+=("$HOME/emusrc/$f") ;; esac
done
arm-linux-gnueabihf-gcc -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Wl,-soname,hwshim.so -o "$R/lib/hwshim.so" \
  "${CC_SRCS[@]}" \
  -L"$R/lib" -l:libdl.so.2 -l:libc.so.6
# WHAT WAS COMPILED, recorded beside what came out of it. This is the whole
# input to watch.sh's decision to rebuild; see pad_shim_hash() for why it is a
# digest of the bytes and not a comparison of file times. Written only after a
# successful compile (set -e), so a failed build never claims to be current.
pad_shim_hash "$RIG" > "$PAD_SHIM_STAMP"
echo "built ok: $(ls -l "$R/lib/hwshim.so" | awk '{print $5}') bytes"
