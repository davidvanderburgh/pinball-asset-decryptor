#!/bin/bash
# buildgl.sh - build the software rasteriser as libGLESv2.so.2 and the EGL
# shim as libEGL.so.1. They are SEPARATE translation units on purpose: the
# framebuffer and all GL state must exist exactly once, and libEGL links
# against libGLESv2 to reach it.
set -e
R=/home/david/spike2root
S=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu
cp $S/glraster.c $S/eglshim.c /home/david/emusrc/

CFLAGS="-fno-stack-protector -shared -fPIC -O2 -nostdlib -Wall"

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libGLESv2.so.2 \
  -o $R/usr/lib/libGLESv2.so.2 /home/david/emusrc/glraster.c \
  -L$R/lib -l:libc.so.6

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libEGL.so.1 \
  -o $R/usr/lib/libEGL.so.1 /home/david/emusrc/eglshim.c \
  -L$R/lib -L$R/usr/lib -l:libGLESv2.so.2 -l:libc.so.6

echo "libGLESv2.so.2 : $(stat -c%s $R/usr/lib/libGLESv2.so.2) bytes"
echo "libEGL.so.1    : $(stat -c%s $R/usr/lib/libEGL.so.1) bytes"
echo "--- libEGL needs ---"
arm-linux-gnueabihf-objdump -p $R/usr/lib/libEGL.so.1 | grep NEEDED
echo "--- undefined symbols left in libEGL (should be libc + pad_*) ---"
arm-linux-gnueabihf-objdump -T $R/usr/lib/libEGL.so.1 | awk '$4=="*UND*"{print "   ", $NF}'
