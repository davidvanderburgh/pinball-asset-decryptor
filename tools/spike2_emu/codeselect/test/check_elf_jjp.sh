#!/bin/bash
# check_elf_jjp.sh BIN [JJPROOT] - the ceiling the JJP card's loader imposes
# on jjpselect (Ubuntu 21.10 rootfs, glibc 2.34, x86-64):
#   max GLIBC_ version node <= 2.34
#   NEEDED only libX11.so.6 libasound.so.2 libc.so.6 libm.so.6 libgcc_s.so.1
#     (+ libpthread.so.0 / libdl.so.2 when linked against a 2.34 image, where
#     they are still separate libraries; a 2.39 host folds them into libc)
#     - never libEGL / libGLESv2: egl_x11.c dlopens those so a box without
#     Mesa still gets a menu through XPutImage
#   interpreter /lib64/ld-linux-x86-64.so.2
# and, when a mounted card image (JJPROOT) is given, EVERY undefined symbol
# resolves against that image's own libraries - the check build.sh learned
# to make: a too-new redirect (__isoc23_strtol) carries no version tag, so a
# version-node ceiling alone once said OK over a binary that died before
# main().
set -e
BIN=$1
JJPROOT=${2:-}
[ -f "$BIN" ] || { echo "check_elf_jjp: no $BIN"; exit 1; }

max=$(readelf --dyn-syms -W "$BIN" | grep -oE 'GLIBC_[0-9.]+' | sort -uV | tail -1)
top=$(printf '%s\nGLIBC_2.34\n' "$max" | sort -V | tail -1)
if [ "$top" != "GLIBC_2.34" ]; then
    echo "check_elf_jjp: FAIL max GLIBC node $max > GLIBC_2.34"
    readelf --dyn-syms -W "$BIN" | grep -E 'GLIBC_2\.(3[5-9]|[4-9][0-9])' || true
    exit 1
fi
if readelf --dyn-syms -W "$BIN" | grep -q '__isoc23_'; then
    echo "check_elf_jjp: FAIL an __isoc23_ redirect got in (jjp_glibc.h is not being force-included)"
    readelf --dyn-syms -W "$BIN" | grep '__isoc23_'
    exit 1
fi

bad=0
needed=$(readelf -d "$BIN" | grep NEEDED | sed 's/.*\[\(.*\)\]/\1/')
for n in $needed; do
    case "$n" in
        libX11.so.6|libasound.so.2|libpthread.so.0|libdl.so.2|libc.so.6|libm.so.6|libgcc_s.so.1) ;;
        *) echo "check_elf_jjp: FAIL unexpected NEEDED $n"; bad=1 ;;
    esac
done
[ $bad -eq 0 ] || exit 1

interp=$(readelf -l "$BIN" | grep -o 'interpreter: [^]]*' | cut -d' ' -f2)
if [ "$interp" != "/lib64/ld-linux-x86-64.so.2" ]; then
    echo "check_elf_jjp: FAIL interpreter '$interp'"
    exit 1
fi

if [ -n "$JJPROOT" ]; then
    LIBDIR="$JJPROOT/usr/lib/x86_64-linux-gnu"
    [ -d "$LIBDIR" ] || { echo "check_elf_jjp: FAIL no $LIBDIR (is the card image mounted?)"; exit 1; }
    # readelf columns: Num Value Size Type Bind Vis Ndx Name - the same for a
    # weak and a strong symbol, which objdump -T's are NOT (its *UND* column
    # shifts with the flags, and an awk on it only ever saw the weak ones).
    # WEAK undefined symbols (__gmon_start__, _ITM_*, __cxa_finalize) are
    # what every glibc executable carries and the loader is allowed to leave
    # unresolved; only a STRONG one dies before main().
    syms=$(mktemp)
    for lib in "$LIBDIR"/libc.so.6 "$LIBDIR"/libm.so.6 "$LIBDIR"/libpthread.so.0 "$LIBDIR"/libdl.so.2 \
               "$LIBDIR"/libgcc_s.so.1 "$LIBDIR"/libX11.so.6 "$LIBDIR"/libasound.so.2; do
        [ -f "$lib" ] && readelf --dyn-syms -W "$lib" 2>/dev/null | awk 'NF>=8 && $7!="UND" {print $8}'
    done | sed 's/@.*//' | sort -u > "$syms"
    missing=""
    strong=0
    for s in $(readelf --dyn-syms -W "$BIN" | awk 'NF>=8 && $7=="UND" && $5!="WEAK" {print $8}' | sed 's/@.*//' | sort -u); do
        strong=$((strong + 1))
        grep -qxF "$s" "$syms" || missing="$missing $s"
    done
    rm -f "$syms"
    [ "$strong" -gt 20 ] || { echo "check_elf_jjp: FAIL only $strong undefined symbols counted - the parse is wrong"; exit 1; }
    if [ -n "$missing" ]; then
        echo "check_elf_jjp: FAIL not in the card's libraries:$missing"
        exit 1
    fi
    echo "check_elf_jjp: all $strong undefined symbols resolve against $LIBDIR"
fi

type=$(readelf -h "$BIN" | grep 'Type:' | awk '{print $2}')
echo "check_elf_jjp: OK  max node $max, NEEDED [$(echo $needed)], interp $interp, type $type, $(stat -c %s "$BIN") bytes"
