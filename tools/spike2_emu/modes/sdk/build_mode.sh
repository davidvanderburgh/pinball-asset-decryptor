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
RUNTIME=$SDK/pad_mode_runtime.c
while getopts "o:p" opt; do
    case $opt in
        o) OUT=$OPTARG ;;
        p) RUNTIME= ;;
        *) echo "usage: build_mode.sh -o mode.so mode.c [mode.c ...]" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ -n "$OUT" ] && [ $# -ge 1 ] || { echo "usage: build_mode.sh -o mode.so mode.c [mode.c ...]" >&2; exit 2; }
CC=${CC:-arm-linux-gnueabihf-gcc}
command -v "$CC" >/dev/null || { echo "build_mode.sh: $CC not found" >&2; exit 1; }
"$CC" -std=gnu17 -marm -mfloat-abi=hard -fno-stack-protector -fPIC -fvisibility=hidden -shared -O2 -nostdlib \
    -Wall -Wextra -Wno-unused-parameter -Werror=implicit-function-declaration \
    -I"$SDK" -Wl,-soname,mode.so \
    -o "$OUT" ${RUNTIME:+"$RUNTIME"} "$@" -lgcc
# Undefined symbols are resolved from the game's libc when the object loads - so a
# misspelt pm_ call would only fail on the machine. Refuse that here, and refuse the libc
# calls that break the rules (MODE_SDK.md, rule 2): allocation, threads, sleeping, stdio,
# processes. Plain string and memory calls (strlen, memcpy...) are fine - gcc emits some
# on its own - and resolve from the game's libc.
NM=${CC%gcc}nm
if command -v "$NM" >/dev/null; then
    undefined=$("$NM" -D --undefined-only "$OUT" | awk '{print $NF}' | sed 's/@.*//')
    missing=$(echo "$undefined" | grep -E '^pm_' || true)
    banned=$(echo "$undefined" | grep -E '^(malloc|calloc|realloc|free|posix_memalign|memalign|valloc|_Zn[wa]|_Zd[la]|pthread_|sleep|usleep|nanosleep|select|poll|epoll_|f?printf|puts|fopen|fread|fwrite|fclose|system|popen|fork|exec|wait|signal|sigaction)' || true)
    if [ -n "$missing" ] || [ -n "$banned" ]; then
        rm -f "$OUT"
        [ -n "$missing" ] && echo "build_mode.sh: these pad_mode calls do not exist: $(echo $missing)" >&2
        [ -n "$banned" ] && echo "build_mode.sh: a mode may not call these inside the game (MODE_SDK.md rule 2): $(echo $banned)" >&2
        exit 1
    fi
    echo "libc calls it will resolve from the game: $(echo $undefined)"
fi
echo "built $OUT ($(stat -c %s "$OUT") bytes) from: $*"
