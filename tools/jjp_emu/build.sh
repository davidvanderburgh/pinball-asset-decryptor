#!/bin/bash
# Build the hardware shim.
#
# THE GLIBC TRAP.  The obvious `gcc -shared -o shim.so shim.c -ldl -lrt` builds
# against the WSL HOST's glibc (2.39 on Ubuntu 24.04) and the resulting .so is
# then refused by the game, whose image is Ubuntu 21.10 with glibc 2.34:
#
#     ./game: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
#             (required by /tmp/jjphwshim.so)
#
# glibc 2.38 introduced the __isoc23_* redirects (strtol and friends), so even
# trivial C picks up a too-new symbol version.  The fix is the one PAD's own
# decrypt pipeline already uses (plugins/jjp/pipeline.py::_phase_compile):
# compile with the host compiler, then link -nostdlib directly against the
# CHROOT's libc.so.6, which pins every symbol to the image's versions.
#
# NEVER rebuild while a run is live: overwriting a .so under a mapped process
# can kill it with SIGBUS.  We ask first and refuse rather than risk it - the
# Spike 2 rig learned that one the expensive way.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

LIVE=$(pgrep -c -x game 2>/dev/null); LIVE=${LIVE:-0}
if [ "$LIVE" != "0" ] && [ "${1:-}" != "--force" ]; then
    echo "build.sh: $LIVE game process(es) live - refusing to rebuild." >&2
    echo "  Overwriting a mapped .so can SIGBUS the game.  Stop it first:" >&2
    echo "    bash $HERE/killgame.sh" >&2
    exit 2
fi

mountpoint -q "$JJP_JAIL" || { echo "build.sh: jail not mounted; run jail.sh" >&2; exit 3; }
command -v gcc >/dev/null || { echo "build.sh: no gcc.  apt-get install -y build-essential" >&2; exit 4; }

OUT=${JJP_SHIM_SO:-/var/tmp/jjphwshim.so}
OBJ=/var/tmp/jjphwshim.o
CHROOT_LIB="$JJP_JAIL/lib/x86_64-linux-gnu"

gcc -c -fPIC -O2 -std=gnu11 -Wall -Wextra \
    -D_FORTIFY_SOURCE=0 -fno-stack-protector \
    -I"$HERE" -o "$OBJ" "$HERE/jjphwshim.c" || exit 1

# Link against the IMAGE's libraries, not the host's.
LIBS="$CHROOT_LIB/libc.so.6"
for extra in libdl.so.2 librt.so.1 libpthread.so.0; do
    [ -f "$CHROOT_LIB/$extra" ] && LIBS="$LIBS $CHROOT_LIB/$extra"
done
# shellcheck disable=SC2086
gcc -shared -nostdlib -o "$OUT" "$OBJ" $LIBS -lgcc || exit 1

echo "built $OUT ($(stat -c%s "$OUT") bytes)"

# Prove the pinning worked rather than assuming it.
#
# Checking only for too-new GLIBC_2.xx *version tags* is NOT enough and gave a
# false OK once already: the real failure was
#     ./game: symbol lookup error: jjphwshim.so: undefined symbol: __isoc23_strtol
# and __isoc23_strtol carries no version tag at all - the host's headers simply
# redirect strtol to a symbol the image's glibc 2.34 does not export.  So
# resolve EVERY undefined symbol against the image's own libraries instead.
BADVER=$(objdump -T "$OUT" 2>/dev/null | grep -oE 'GLIBC_2\.3[5-9]|GLIBC_2\.[4-9][0-9]' | sort -u)
if [ -n "$BADVER" ]; then
    echo "FAIL: shim wants symbol versions newer than the image's glibc:" >&2
    echo "$BADVER" >&2
    exit 5
fi

IMAGE_SYMS=$(mktemp)
for lib in "$CHROOT_LIB"/*.so.*; do
    objdump -T "$lib" 2>/dev/null | awk '$4=="*UND*"{next} {print $NF}'
done | sed 's/@.*//' | sort -u > "$IMAGE_SYMS"

MISSING=""
for sym in $(objdump -T "$OUT" 2>/dev/null | awk '$4=="*UND*"{print $NF}' | sed 's/@.*//' | sort -u); do
    grep -qxF "$sym" "$IMAGE_SYMS" || MISSING="$MISSING $sym"
done
rm -f "$IMAGE_SYMS"

if [ -n "$MISSING" ]; then
    echo "FAIL: these symbols do not exist in the game image's libraries:" >&2
    for m in $MISSING; do echo "    $m" >&2; done
    echo "  The game would die with 'symbol lookup error' before main()." >&2
    echo "  Usually a newer-glibc redirect (strtol -> __isoc23_strtol etc);" >&2
    echo "  hand-roll the call instead of using the libc one." >&2
    exit 6
fi
echo "symbol check OK: every undefined symbol resolves against the image's libs"
