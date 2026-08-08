#!/bin/bash
# buildbridge.sh [--host|--guest] - build the GL bridge: guest encoder (ARM) +
# host renderer (x86-64).
#
# The guest library REPLACES glraster.c as libGLESv2.so.2. eglshim.c is
# unchanged and links against whichever backend is installed, because both
# export pad_present / pad_fb_width / pad_fb_height / pad_readback_counts,
# and now pad_gl_proc as well - eglGetProcAddress asks the live backend for
# extension entry points by name, and only the bridge has any.
#
# THE TWO HALVES CAN BE BUILT SEPARATELY, and that is not a convenience.
# Everything below used to be one `set -e` run with the two ARM compiles FIRST
# and the native `padglhost` link LAST, so a box without
# arm-linux-gnueabihf-gcc died before reaching the one binary it was perfectly
# able to build - and left exactly the state that produced
# `env: './padglhost': No such file or directory` at the next start. ensurebuild.sh
# asks for the half it needs; by hand, no argument still builds both.
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT
S=$RIG

WHICH=${1:-both}
case "$WHICH" in
    --host)  WHICH=host ;;
    --guest) WHICH=guest ;;
    both|"") WHICH=both ;;
    *) echo "usage: buildbridge.sh [--host|--guest]" >&2; exit 2 ;;
esac

# The staging directory the sources are copied into. Created here: it
# was simply assumed to exist, which is fine on the machine where it was
# made by hand once and is a `cp: No such file or directory` on any
# other. Compiling from /mnt/c is what it avoids - drvfs is slow enough
# to matter over a few thousand lines of C.
mkdir -p "$HOME/emusrc"
# ONE LIST PER HALF, from padpath.sh, and the same list decides whether a
# rebuild is needed - so the copy list and the compile line cannot drift apart.
# build.sh's own comment records what that costs: alsastub.c was on the compile
# line and missing from the copy list, an edit was silently never built, and the
# build still said "built ok".
for f in $PAD_GLHOST_SRCS $PAD_GLGUEST_SRCS; do
    cp "$S/$f" "$HOME/emusrc/$f"
done

# -Werror=implicit-function-declaration for the reason build.sh records at
# length: it is a warning up to GCC 13 and an error from GCC 14 on, so without
# it a build breaks on newer distros than this rig is developed on and cannot
# be made to break here. Both halves of the bridge, because both are compiled
# on the user's machine.
CFLAGS="-fno-stack-protector -shared -fPIC -O2 -nostdlib -Wall \
-Werror=implicit-function-declaration -I$HOME/emusrc"

if [ "$WHICH" != host ]; then
    arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libGLESv2.so.2 \
      -o "$R/usr/lib/libGLESv2.so.2" "$HOME/emusrc/glbridge.c" \
      -L"$R/lib" -l:libc.so.6

    arm-linux-gnueabihf-gcc $CFLAGS -Wl,-soname,libEGL.so.1 \
      -o "$R/usr/lib/libEGL.so.1" "$HOME/emusrc/eglshim.c" \
      -L"$R/lib" -L"$R/usr/lib" -l:libGLESv2.so.2 -l:libc.so.6

    # WHAT WAS COMPILED, recorded beside what came out of it, and only after a
    # successful compile (set -e) so a failed build never claims to be current.
    pad_glguest_hash "$S" > "$PAD_GLGUEST_STAMP"
    echo "guest libGLESv2.so.2 : $(stat -c%s "$R/usr/lib/libGLESv2.so.2") bytes (bridge encoder)"
    echo "guest libEGL.so.1    : $(stat -c%s "$R/usr/lib/libEGL.so.1") bytes"
fi

if [ "$WHICH" != guest ]; then
    # -l: form is required for BOTH libraries: this box has libEGL.so.1 and
    # libX11.so.6 but no dev symlinks (no libEGL.so, no libX11.so), so plain
    # -lEGL / -lX11 fail to link. libxcb comes in via libX11's DT_NEEDED.
    # padglhost.c declares every EGL/GLES/X11 entry point it uses itself, so
    # this needs the runtime libraries and no -dev packages at all.
    gcc -O2 -Wall -Werror=implicit-function-declaration -I$HOME/emusrc \
      -o "$PAD_GLHOST_BIN" \
      "$HOME/emusrc/padglhost.c" -l:libEGL.so.1 -l:libX11.so.6

    pad_glhost_hash "$S" > "$PAD_GLHOST_STAMP"
    echo "host  padglhost      : $(stat -c%s "$PAD_GLHOST_BIN") bytes"
fi
