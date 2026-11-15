#!/bin/bash
# Build the custom-modes library (jjpmodes.c, PAD-1335) the way build.sh builds
# the hardware shim: against the IMAGE's glibc (-nostdlib + the jail's libc),
# so it loads into a game on Ubuntu 21.10 whatever this WSL distro runs.
#   bash buildmods.sh            -> /var/tmp/jjpmodes.so  (JJP_MODS_SO)
# Then launch with JJP_MODS_SO=/var/tmp/jjpmodes.so (run_game.sh copies it in).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
mountpoint -q "$JJP_JAIL" || { echo "buildmods.sh: jail not mounted; run jail.sh" >&2; exit 3; }
OUT=${JJP_MODS_SO:-/var/tmp/jjpmodes.so}
OBJ=/var/tmp/jjpmodes.o
CHROOT_LIB="$JJP_JAIL/lib/x86_64-linux-gnu"
# A running game maps the copy run_game.sh put in the jail, never $OUT, so a
# rebuild here cannot SIGBUS it.  -std=gnu11 keeps glibc 2.38+ headers from
# redirecting strtol to __isoc23_strtol, which the image's glibc lacks.
gcc -c -fPIC -O2 -std=gnu11 -Wall -Wextra -D_FORTIFY_SOURCE=0 -fno-stack-protector \
    -o "$OBJ" "$HERE/jjpmodes.c" || exit 1
LIBS="$CHROOT_LIB/libc.so.6"
for extra in libdl.so.2 libpthread.so.0; do
    [ -f "$CHROOT_LIB/$extra" ] && LIBS="$LIBS $CHROOT_LIB/$extra"
done
gcc -shared -nostdlib -o "$OUT" "$OBJ" $LIBS -lgcc || exit 1
BADVER=$(objdump -T "$OUT" 2>/dev/null | grep -oE 'GLIBC_2\.3[5-9]|GLIBC_2\.[4-9][0-9]' | sort -u)
[ -z "$BADVER" ] || { echo "FAIL: needs glibc newer than the image's: $BADVER" >&2; exit 5; }
echo "built $OUT ($(stat -c%s "$OUT") bytes)"
