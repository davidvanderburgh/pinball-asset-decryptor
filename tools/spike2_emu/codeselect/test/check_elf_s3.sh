#!/bin/bash
# check_elf_s3.sh BIN S3ROOT - the Spike 3 menu (PAD-1263) against a card's
# own rootfs: aarch64, every NEEDED library present on the card, every symbol
# it imports defined by one of them, and no glibc symbol version newer than
# the card's libc carries.
set -eu
BIN=$1; R=$2
NM=$(command -v aarch64-linux-gnu-nm || echo nm)
RE=$(command -v aarch64-linux-gnu-readelf || echo readelf)
fail() { echo "check_elf_s3: $*"; exit 1; }
"$RE" -h "$BIN" | grep -q "AArch64" || fail "$BIN is not an aarch64 program"
libs=()
for so in $("$RE" -d "$BIN" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'); do
    p=""
    for d in "$R/usr/lib" "$R/lib"; do [ -e "$d/$so" ] && { p=$d/$so; break; }; done
    [ -n "$p" ] || fail "the card has no $so"
    libs+=("$p")
done
defined=$(for l in "${libs[@]}"; do "$NM" -D --defined-only "$(readlink -f "$l")" | awk '{print $NF}'; done | sed 's/@.*//' | sort -u)
missing=0
for s in $("$NM" -D --undefined-only "$BIN" | awk '{print $NF}' | sed 's/@.*//' | sort -u); do
    case "$s" in __gmon_start__|_ITM_*|__cxa_finalize) continue ;; esac
    grep -qx "$s" <<<"$defined" || { echo "check_elf_s3: $s is defined by none of the card's libraries"; missing=1; }
done
[ "$missing" = 0 ] || exit 1
have=$("$NM" -D "$(readlink -f "$R/lib/libc.so.6")" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)
need=$("$RE" -V "$BIN" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)
[ "$(printf '%s\n%s\n' "$need" "$have" | sort -V | tail -1)" = "$have" ] || fail "needs $need, the card's libc has $have"
echo "check_elf_s3: OK (${#libs[@]} libraries, needs $need, the card has $have)"
