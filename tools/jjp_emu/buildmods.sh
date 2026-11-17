#!/bin/bash
# Build the custom-modes library (jjpmodes.c, PAD-1335) the way build.sh builds
# the hardware shim: against the IMAGE's glibc (-nostdlib + the jail's libc),
# so it loads into a game on Ubuntu 21.10 whatever this WSL distro runs.
#   bash buildmods.sh            -> /var/tmp/jjpmodes.so  (JJP_MODS_SO)
# Then launch with JJP_MODS_SO=/var/tmp/jjpmodes.so (run_game.sh copies it in).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
# JJP_MODS_LIBDIR=<dir with libc.so.6 [libpthread.so.0 libdl.so.2]>: link against
# those instead of the mounted title's.  The library that goes on every title's
# ISO is linked against an image glibc (every JJP image in the library has 2.34, MODES.md "Titles"); a newer one would need the OLDEST image: symbols
# keep their old versions on a newer glibc, never the other way round.
if [ -n "${JJP_MODS_LIBDIR:-}" ]; then
    CHROOT_LIB=$JJP_MODS_LIBDIR
else
    mountpoint -q "$JJP_JAIL" || { echo "buildmods.sh: jail not mounted; run jail.sh (or set JJP_MODS_LIBDIR)" >&2; exit 3; }
fi
OUT=${JJP_MODS_SO:-/var/tmp/jjpmodes.so}
OBJ="${OUT%.so}.o"   # beside OUT: tickets building at once each keep their own
CHROOT_LIB=${CHROOT_LIB:-"$JJP_JAIL/lib/x86_64-linux-gnu"}
# A running game maps the copy run_game.sh put in the jail, never $OUT, so a
# rebuild here cannot SIGBUS it.  -std=gnu11 keeps glibc 2.38+ headers from
# redirecting strtol to __isoc23_strtol, which the image's glibc lacks.
gcc -c -fPIC -O2 -std=gnu11 -Wall -Wextra -Werror=implicit-function-declaration -D_FORTIFY_SOURCE=0 -fno-stack-protector \
    -o "$OBJ" "$HERE/jjpmodes.c" || exit 1
LIBS="$CHROOT_LIB/libc.so.6"
for extra in libdl.so.2 libpthread.so.0; do
    [ -f "$CHROOT_LIB/$extra" ] && LIBS="$LIBS $CHROOT_LIB/$extra"
done
gcc -shared -nostdlib -o "$OUT" "$OBJ" $LIBS -lgcc || exit 1
BADVER=$(objdump -T "$OUT" 2>/dev/null | grep -oE 'GLIBC_2\.3[5-9]|GLIBC_2\.[4-9][0-9]' | sort -u)
[ -z "$BADVER" ] || { echo "FAIL: needs glibc newer than the image's: $BADVER" >&2; exit 5; }
# glibc 2.38+ headers route strtol & co to __isoc23_* (unversioned when linked
# against the image's libc, so the check above misses them): the game then
# dies at load with "undefined symbol: __isoc23_strtol".
C23=$(nm -D --undefined-only "$OUT" 2>/dev/null | grep -o '__isoc23_[a-z]*' | sort -u)
[ -z "$C23" ] || { echo "FAIL: imports the image's glibc lacks: $C23" >&2; exit 5; }
echo "built $OUT ($(stat -c%s "$OUT") bytes)"
