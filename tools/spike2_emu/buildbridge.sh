#!/bin/bash
# buildbridge.sh - build the GL bridge: guest encoder (ARM) + host renderer (x86-64).
#
# The guest library REPLACES glraster.c as libGLESv2.so.2. eglshim.c is
# unchanged and links against whichever backend is installed, because both
# export pad_present / pad_fb_width / pad_fb_height / pad_readback_counts,
# and now pad_gl_proc as well - eglGetProcAddress asks the live backend for
# extension entry points by name, and only the bridge has any.
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
# padvid.h is on this list because padglhost.c now opens the VIDEO block too:
# the guest sends an offset into it rather than 1.5 MB of pixels per frame.
cp "$S/glbridge.c" "$S/eglshim.c" "$S/padgl.h" "$S/padsw.h" "$S/padvid.h" "$S/i420.h" "$S/padglhost.c" "$HOME/emusrc/"

CFLAGS="-fno-stack-protector -shared -fPIC -O2 -nostdlib -Wall -I$HOME/emusrc"

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libGLESv2.so.2 \
  -o "$R/usr/lib/libGLESv2.so.2" "$HOME/emusrc/glbridge.c" \
  -L"$R/lib" -l:libc.so.6

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libEGL.so.1 \
  -o "$R/usr/lib/libEGL.so.1" "$HOME/emusrc/eglshim.c" \
  -L"$R/lib" -L"$R/usr/lib" -l:libGLESv2.so.2 -l:libc.so.6

# -l: form is required for BOTH libraries: this box has libEGL.so.1 and
# libX11.so.6 but no dev symlinks (no libEGL.so, no libX11.so), so plain
# -lEGL / -lX11 fail to link. libxcb comes in via libX11's DT_NEEDED.
gcc -O2 -Wall -I$HOME/emusrc -o "$HOME/padglhost" \
  "$HOME/emusrc/padglhost.c" -l:libEGL.so.1 -l:libX11.so.6

echo "guest libGLESv2.so.2 : $(stat -c%s "$R/usr/lib/libGLESv2.so.2") bytes (bridge encoder)"
echo "guest libEGL.so.1    : $(stat -c%s "$R/usr/lib/libEGL.so.1") bytes"
echo "host  padglhost      : $(stat -c%s "$HOME/padglhost") bytes"
