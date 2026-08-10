#!/bin/bash
# buildgl.sh - build the SOFTWARE RASTERISER as libGLESv2.so.2 and the EGL
# shim as libEGL.so.1. They are SEPARATE translation units on purpose: the
# framebuffer and all GL state must exist exactly once, and libEGL links
# against libGLESv2 to reach it.
#
# THIS REPLACES THE GL BRIDGE, AND THAT IS A TRAP (item 27, 2026-08-10).
# buildbridge.sh installs the bridge encoder over the SAME libGLESv2.so.2,
# and normal windowed runs need the bridge - the raster's pad_gl_proc
# returns 0 for every name, so the VIV upload procs resolve to NO-OP and
# padglhost never receives a single command: the game plays into a black
# window while every other counter reads healthy. Two full Jaws runs were
# lost to a casual "rebuild padglhost" call here before anything named it.
# ensurebuild.sh now detects the raster backend (no glTexDirectVIV string in
# the file) and rebuilds the bridge at the next start, and this script says
# what it just did - but if you only wanted the HOST renderer rebuilt, the
# command you wanted was:  buildbridge.sh --host
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT
S=$RIG
# The staging directory the sources are copied into. Created here: it
# was simply assumed to exist, which is fine on the machine where it was
# made by hand once and is a `cp: No such file or directory` on any
# other. Compiling from /mnt/c is what it avoids - drvfs is slow enough
# to matter over a few thousand lines of C.
mkdir -p "$HOME/emusrc"
cp "$S/glraster.c" "$S/eglshim.c" "$HOME/emusrc/"

CFLAGS="-fno-stack-protector -shared -fPIC -O2 -nostdlib -Wall"

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libGLESv2.so.2 \
  -o "$R/usr/lib/libGLESv2.so.2" "$HOME/emusrc/glraster.c" \
  -L"$R/lib" -l:libc.so.6

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libEGL.so.1 \
  -o "$R/usr/lib/libEGL.so.1" "$HOME/emusrc/eglshim.c" \
  -L"$R/lib" -L"$R/usr/lib" -l:libGLESv2.so.2 -l:libc.so.6

echo "libGLESv2.so.2 : $(stat -c%s "$R/usr/lib/libGLESv2.so.2") bytes (RASTER - see header)"
echo "libEGL.so.1    : $(stat -c%s "$R/usr/lib/libEGL.so.1") bytes"
echo "NOTE: the RASTER backend is now installed over the GL bridge. Windowed"
echo "NOTE: runs need the bridge back:  buildbridge.sh --guest"
echo "--- libEGL needs ---"
arm-linux-gnueabihf-objdump -p "$R/usr/lib/libEGL.so.1" | grep NEEDED
echo "--- undefined symbols left in libEGL (should be libc + pad_*) ---"
arm-linux-gnueabihf-objdump -T "$R/usr/lib/libEGL.so.1" | awk '$4=="*UND*"{print "   ", $NF}'
