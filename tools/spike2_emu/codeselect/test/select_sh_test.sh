#!/bin/bash
# select_sh_test.sh [QEMU ROOT] - select.sh's images.conf lookup against
# images.conf.example, with the host awk and, when QEMU/ROOT are given (or
# found), with the card's own busybox awk run under qemu-arm-static.
# QEMU is taken from the environment when not given (the Makefile exports it;
# an argv naming qemu is what a rig teardown's pkill matches).
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
QEMU=${1:-${QEMU:-qemu-arm-static}}
ROOT=${2:-/home/david/spike2root}
cd "$HERE"

check() {   # check LABEL IDX EXPECTED
    local got
    got=$(sh select.sh --lookup "$2" images.conf.example)
    [ "$got" = "$3" ] || { echo "select_sh_test: FAIL ($1) index $2 -> '$got', expected '$3'"; exit 1; }
}

sh -n select.sh
bash -n select.sh
check host 0 /dev/mmcblk0p3
check host 1 /dev/mmcblk0p7
check host 2 ""
# a conf with spaces, a comment and a title containing '='
tmp=$(mktemp)
printf '# x\n  image = /dev/mmcblk0p3 | STOCK | a=b \nimage=/dev/mmcblk0p7|X|y\ndefault=1\n' > "$tmp"
got=$(sh select.sh --lookup 0 "$tmp"); [ "$got" = /dev/mmcblk0p3 ] || { echo "select_sh_test: FAIL spaced conf -> '$got'"; exit 1; }
got=$(sh select.sh --lookup 1 "$tmp"); [ "$got" = /dev/mmcblk0p7 ] || { echo "select_sh_test: FAIL spaced conf 1 -> '$got'"; exit 1; }
rm -f "$tmp"

if command -v "$QEMU" >/dev/null 2>&1 && [ -x "$ROOT/bin/busybox.nosuid" ]; then
    export AWK="$QEMU -L $ROOT $ROOT/bin/busybox.nosuid awk"
    check busybox 0 /dev/mmcblk0p3
    check busybox 1 /dev/mmcblk0p7
    check busybox 2 ""
    echo "select_sh_test: OK (host awk and the card's busybox awk under qemu)"
else
    echo "select_sh_test: OK (host awk only)"
fi
