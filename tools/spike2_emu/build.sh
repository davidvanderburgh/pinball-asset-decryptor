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
# Sync EVERY source this build compiles. alsastub.c used to be missing from this
# list while still being on the compile line below, so an edit to the Windows
# copy was silently never built - and the build still said "built ok". It only
# surfaced as `undefined symbol` at guest start, one full run later.
cp "$RIG/hwshim.c"    "$HOME/emusrc/hwshim.c"
cp "$RIG/alsastub.c"  "$HOME/emusrc/alsastub.c"
cp "$RIG/gststub.c"    "$HOME/emusrc/gststub.c"
cp "$RIG/gstvid.c"     "$HOME/emusrc/gstvid.c"
cp "$RIG/padvid.h"     "$HOME/emusrc/padvid.h"
cp "$RIG/padsw.h"     "$HOME/emusrc/padsw.h"
arm-linux-gnueabihf-gcc -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Wl,-soname,hwshim.so -o "$R/lib/hwshim.so" \
  "$HOME/emusrc/hwshim.c" "$HOME/emusrc/alsastub.c" \
  "$HOME/emusrc/gststub.c" "$HOME/emusrc/gstvid.c" \
  -L"$R/lib" -l:libdl.so.2 -l:libc.so.6
echo "built ok: $(ls -l "$R/lib/hwshim.so" | awk '{print $5}') bytes"
