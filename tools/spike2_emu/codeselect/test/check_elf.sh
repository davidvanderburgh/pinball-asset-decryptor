#!/bin/bash
# check_elf.sh CROSS BIN - the readelf ceiling the card's loader imposes:
#   max GLIBC_ version node <= 2.18 (rootfs libc is 2.21, nodes up to 2.18)
#   NEEDED only libEGL.so.1 libGLESv2.so.2 libasound.so.2 libc.so.6 libm.so.6 libgcc_s.so.1
#   interpreter /lib/ld-linux-armhf.so.3
set -e
CROSS=$1
BIN=$2
[ -f "$BIN" ] || { echo "check_elf: no $BIN"; exit 1; }

max=$("${CROSS}readelf" --dyn-syms -W "$BIN" | grep -oE 'GLIBC_[0-9.]+' | sort -uV | tail -1)
top=$(printf '%s\nGLIBC_2.18\n' "$max" | sort -V | tail -1)
if [ "$top" != "GLIBC_2.18" ]; then
    echo "check_elf: FAIL max GLIBC node $max > GLIBC_2.18"
    "${CROSS}readelf" --dyn-syms -W "$BIN" | grep -E 'GLIBC_2\.(19|[2-9][0-9])' || true
    exit 1
fi

bad=0
needed=$("${CROSS}readelf" -d "$BIN" | grep NEEDED | sed 's/.*\[\(.*\)\]/\1/')
for n in $needed; do
    case "$n" in
        libEGL.so.1|libGLESv2.so.2|libasound.so.2|libc.so.6|libm.so.6|libgcc_s.so.1) ;;
        *) echo "check_elf: FAIL unexpected NEEDED $n"; bad=1 ;;
    esac
done
[ $bad -eq 0 ] || exit 1

interp=$("${CROSS}readelf" -l "$BIN" | grep -o 'interpreter: [^]]*' | cut -d' ' -f2)
if [ "$interp" != "/lib/ld-linux-armhf.so.3" ]; then
    echo "check_elf: FAIL interpreter '$interp'"
    exit 1
fi

type=$("${CROSS}readelf" -h "$BIN" | grep 'Type:' | awk '{print $2}')
echo "check_elf: OK  max node $max, NEEDED [$(echo $needed)], interp $interp, type $type, $(stat -c %s "$BIN") bytes"
