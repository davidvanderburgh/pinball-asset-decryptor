#!/bin/bash
# Build a JJP mode's own C++ (PAD-1384): <name>.cpp -> <name>.so beside it, for
# the runtime (jjpmodes.so) to load where the mode file says `code = <name>`.
#   bash build_code.sh <dir>/<name>.cpp [<out>.so]
# Needs g++ (x86-64, any version that has C++20). The library links NOTHING: its
# libc calls (memcpy, snprintf...) and the runtime's jm_* bind inside the game's
# process when the runtime loads it, so one build loads on every JJP image
# whatever glibc this Linux has. What it may not need is checked after the link.
set -u
SRC=${1:?usage: build_code.sh <name>.cpp [out.so]}
OUT=${2:-"${SRC%.*}.so"}
HERE=$(cd "$(dirname "$0")" && pwd)
CXX=${CXX:-g++}
command -v "$CXX" >/dev/null 2>&1 || { echo "build_code.sh: no $CXX here (apt-get install g++)" >&2; exit 4; }
TMP="$OUT.tmp.$$"
# -std=gnu++20: designated initializers for JM_REGISTER. No exceptions, RTTI,
# thread-safe statics or stack protector: each would pull in a runtime library.
# -D_FORTIFY_SOURCE=0 keeps a new glibc's headers from naming
# functions the machine's glibc lacks (__*_chk, __isoc23_strtol).
"$CXX" -shared -fPIC -O2 -std=gnu++20 -Wall -Wextra -Wno-missing-field-initializers -Werror=return-type \
    -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-stack-protector -fno-asynchronous-unwind-tables \
    -fvisibility=hidden -D_FORTIFY_SOURCE=0 -U_FORTIFY_SOURCE -I"$HERE" \
    -nostdlib -o "$TMP" "$SRC" -lgcc || { rm -f "$TMP"; exit 1; }
# what it needs from outside: the runtime's jm_*, and plain C library calls
BAD=$(nm -D --undefined-only "$TMP" 2>/dev/null | awk '{print $NF}' | sed 's/@.*//' \
    | grep -vE '^(jm_[a-z_]+|mem(cpy|set|move|cmp)|str(len|cmp|ncmp|chr|rchr|str|cpy|ncpy|cat)|v?s?n?printf|abs|labs|llabs|rand|srand|__cxa_finalize|_ITM_[A-Za-z]+|__gmon_start__)$' | sort -u)
if [ -n "$BAD" ]; then
    echo "build_code.sh: $(basename "$SRC") uses what a mode cannot have on the machine:" >&2
    for b in $BAD; do
        case $b in
            _Zn[wa]*|_Zd[la]*) echo "  $b - new/delete: keep state in statics" >&2 ;;
            __cxa_atexit) echo "  $b - a static object with a destructor (a std:: type?): keep plain data in statics" >&2 ;;
            __cxa_*|_Unwind_*|__gxx_*) echo "  $b - C++ exceptions or RTTI" >&2 ;;
            _ZSt*|_ZNSt*|_ZNKSt*) echo "  $b - the C++ standard library (std::)" >&2 ;;
            __isoc23_*|__*_chk) echo "  $b - a newer glibc's function" >&2 ;;
            *) echo "  $b" >&2 ;;
        esac
    done
    rm -f "$TMP"; exit 5
fi
nm -D --defined-only "$TMP" 2>/dev/null | grep -q ' jm_mode_def$' \
    || { echo "build_code.sh: $(basename "$SRC") has no JM_REGISTER(...)" >&2; rm -f "$TMP"; exit 6; }
mv -f "$TMP" "$OUT"
echo "built $OUT ($(stat -c%s "$OUT") bytes)"
