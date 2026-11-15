#!/bin/bash
# build_mode.sh - compile one or more modes into the mode.so a machine preloads (item 134).
#
#   build_mode.sh -o mode.so my_mode.c [another_mode.c ...]
#   build_mode.sh -p -o probe.so call_probe.c      a porting instrument: no runtime
#
# Every mode on a card goes into ONE object with the runtime: it installs each hook once
# and keeps our modes to one at a time. Needs only arm-linux-gnueabihf-gcc (the app's
# PAD-Runtime distro has it). Nothing is linked against a libc: the handful of libc calls
# the runtime makes resolve from the game's own libc when the object loads.
set -euo pipefail
SDK=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=
ARCH=arm
RUNTIME=$SDK/pad_mode_runtime.c
while getopts "o:pa:" opt; do
    case $opt in
        o) OUT=$OPTARG ;;
        p) RUNTIME= ;;
        a) ARCH=$OPTARG ;;
        *) echo "usage: build_mode.sh [-a arm|a64] -o mode.so mode.c [mode.c ...]" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ -n "$OUT" ] && [ $# -ge 1 ] || { echo "usage: build_mode.sh [-a arm|a64] -o mode.so mode.c [mode.c ...]" >&2; exit 2; }
# PAD-1269: the object is built for the machine's CPU. Spike 2 is 32-bit ARM (the default:
# arm-linux-gnueabihf-gcc, hard-float); Spike 3 is 64-bit ARM (-a a64: aarch64-linux-gnu-gcc,
# which tools/spike3_emu/xgcc.sh unpacks from its pinned kit, CC overriding this default). The arm branch's gcc
# command is token-for-token what it always was, so its object stays byte-identical.
# PAD-1273: the runtime prints a 64-bit address through PMA ("lx" on a64), so a64 builds with
# -Werror=format: a log line that would cut an address to 32 bits fails the build.
# PAD-1295: a64 with no CC takes the pinned aarch64 kit tools/spike3_emu/xgcc.sh unpacks (once)
if [ "$ARCH" = a64 ] && [ -z "${CC:-}" ] && [ -f "$SDK/../../../spike3_emu/xgcc.sh" ]; then
    CC=$(bash "$SDK/../../../spike3_emu/xgcc.sh") || { echo "build_mode.sh: no aarch64 compiler (xgcc.sh, above)" >&2; exit 1; }
fi
case $ARCH in
    arm) CC=${CC:-arm-linux-gnueabihf-gcc}; ARCHFLAGS="-marm -mfloat-abi=hard"; ARCHWARN=""; NM=${NM:-${CC%gcc}nm} ;;
    a64) CC=${CC:-aarch64-linux-gnu-gcc};   ARCHFLAGS="";                       ARCHWARN="-Werror=format"
         # PAD-1295: the pinned kit's s3cc has its nm beside it (s3nm); a system cross gcc its prefix's
         if [ -z "${NM:-}" ]; then
             case $CC in */s3cc) NM=${CC%s3cc}s3nm ;; *gcc*) NM=${CC%gcc*}nm ;; *) NM=aarch64-linux-gnu-nm ;; esac
         fi ;;
    *)   echo "build_mode.sh: unknown -a $ARCH (arm or a64)" >&2; exit 2 ;;
esac
command -v "$CC" >/dev/null || { echo "build_mode.sh: $CC not found" >&2; exit 1; }
# -funwind-tables (PAD-381): the game ENDS a process by throwing a C++ exception through its stack
# (do_stack_unwind_exception_t), at a tilt or the end of a ball. A frame of ours on that stack - the
# runtime's magnet grab runs as a game process - must carry unwind tables, or the unwind stops there
# and the game aborts ("terminate called ..."). They cost a few bytes a function and change no code.
"$CC" -std=gnu17 $ARCHFLAGS -fno-stack-protector -fPIC -fvisibility=hidden -shared -O2 -nostdlib -funwind-tables \
    -Wall -Wextra -Wno-unused-parameter -Werror=implicit-function-declaration $ARCHWARN \
    -I"$SDK" -Wl,-soname,mode.so \
    -o "$OUT" ${RUNTIME:+"$RUNTIME"} "$@" -lgcc
# Undefined symbols are resolved from the game's libc when the object loads - so a
# misspelt pm_ call would only fail on the machine. Refuse that here, and refuse the libc
# calls that break the rules (MODE_SDK.md, rule 2): allocation, threads, sleeping, stdio,
# processes. Plain string and memory calls (strlen, memcpy...) are fine - gcc emits some
# on its own - and resolve from the game's libc.
# (NM is set per machine above: Spike 2's is ${CC%gcc}nm, as it always was)
if command -v "$NM" >/dev/null; then
    undefined=$("$NM" -D --undefined-only "$OUT" | awk '{print $NF}' | sed 's/@.*//')
    missing=$(echo "$undefined" | grep -E '^pm_' || true)
    # PAD-1295: the 64-bit runtime allocates the game's C++ strings itself (std_string, PAD-1284),
    # so on a64 the rule is checked on the modes' own code: each source compiled alone, the
    # runtime left out. The missing-pm_ check still reads the whole object.
    ruled=$undefined
    if [ "$ARCH" = a64 ]; then
        objs=$(mktemp -d)
        k=0
        for src in "$@"; do
            k=$((k + 1))
            "$CC" -std=gnu17 -fno-stack-protector -fPIC -fvisibility=hidden -O2 -funwind-tables -w                 -I"$SDK" -c -o "$objs/$k.o" "$src"
        done
        ruled=$("$NM" --undefined-only "$objs"/*.o | awk 'NF {print $NF}' | grep -v ':$' | sed 's/@.*//' | sort -u)
        rm -rf "$objs"
    fi
    banned=$(echo "$ruled" | grep -E '^(malloc|calloc|realloc|free|posix_memalign|memalign|valloc|_Zn[wa]|_Zd[la]|pthread_|sleep|usleep|nanosleep|select|poll|epoll_|f?printf|puts|fopen|fread|fwrite|fclose|system|popen|fork|exec|wait|signal|sigaction)' || true)
    if [ -n "$missing" ] || [ -n "$banned" ]; then
        rm -f "$OUT"
        [ -n "$missing" ] && echo "build_mode.sh: these pad_mode calls do not exist: $(echo $missing)" >&2
        [ -n "$banned" ] && echo "build_mode.sh: a mode may not call these inside the game (MODE_SDK.md rule 2): $(echo $banned)" >&2
        exit 1
    fi
    echo "libc calls it will resolve from the game: $(echo $undefined)"
fi
echo "built $OUT ($(stat -c %s "$OUT") bytes) from: $*"
