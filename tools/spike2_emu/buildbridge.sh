#!/bin/bash
# buildbridge.sh - build the GL bridge: guest encoder (ARM) + host renderer (x86-64).
#
# The guest library REPLACES glraster.c as libGLESv2.so.2. eglshim.c is
# unchanged and links against whichever backend is installed, because both
# export pad_present / pad_fb_width / pad_fb_height / pad_readback_counts,
# and now pad_gl_proc as well - eglGetProcAddress asks the live backend for
# extension entry points by name, and only the bridge has any.
set -e
R=/home/david/spike2root
S=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu
# padvid.h is on this list because padglhost.c now opens the VIDEO block too:
# the guest sends an offset into it rather than 1.5 MB of pixels per frame.
cp $S/glbridge.c $S/eglshim.c $S/padgl.h $S/padsw.h $S/padvid.h $S/padglhost.c /home/david/emusrc/

CFLAGS="-fno-stack-protector -shared -fPIC -O2 -nostdlib -Wall -I/home/david/emusrc"

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libGLESv2.so.2 \
  -o $R/usr/lib/libGLESv2.so.2 /home/david/emusrc/glbridge.c \
  -L$R/lib -l:libc.so.6

arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libEGL.so.1 \
  -o $R/usr/lib/libEGL.so.1 /home/david/emusrc/eglshim.c \
  -L$R/lib -L$R/usr/lib -l:libGLESv2.so.2 -l:libc.so.6

# -l: form is required for BOTH libraries: this box has libEGL.so.1 and
# libX11.so.6 but no dev symlinks (no libEGL.so, no libX11.so), so plain
# -lEGL / -lX11 fail to link. libxcb comes in via libX11's DT_NEEDED.
gcc -O2 -Wall -I/home/david/emusrc -o /home/david/padglhost \
  /home/david/emusrc/padglhost.c -l:libEGL.so.1 -l:libX11.so.6

echo "guest libGLESv2.so.2 : $(stat -c%s $R/usr/lib/libGLESv2.so.2) bytes (bridge encoder)"
echo "guest libEGL.so.1    : $(stat -c%s $R/usr/lib/libEGL.so.1) bytes"
echo "host  padglhost      : $(stat -c%s /home/david/padglhost) bytes"
