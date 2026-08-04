#!/bin/bash
set -e
R=/home/david/spike2root
# Sync EVERY source this build compiles. alsastub.c used to be missing from this
# list while still being on the compile line below, so an edit to the Windows
# copy was silently never built - and the build still said "built ok". It only
# surfaced as `undefined symbol` at guest start, one full run later.
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/hwshim.c    /home/david/emusrc/hwshim.c
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/alsastub.c  /home/david/emusrc/alsastub.c
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/gststub.c    /home/david/emusrc/gststub.c
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/gstvid.c     /home/david/emusrc/gstvid.c
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/padvid.h     /home/david/emusrc/padvid.h
cp /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/padsw.h     /home/david/emusrc/padsw.h
arm-linux-gnueabihf-gcc -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Wl,-soname,hwshim.so -o $R/lib/hwshim.so \
  /home/david/emusrc/hwshim.c /home/david/emusrc/alsastub.c \
  /home/david/emusrc/gststub.c /home/david/emusrc/gstvid.c \
  -L$R/lib -l:libdl.so.2 -l:libc.so.6
echo "built ok: $(ls -l $R/lib/hwshim.so | awk '{print $5}') bytes"
