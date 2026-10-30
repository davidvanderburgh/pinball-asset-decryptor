#!/bin/bash
# Rebuild the tiny ELFs tests/test_cgc_mods.py reads (PAD-877).  Needs
# gcc-arm-linux-gnueabihf and gcc (PAD-Runtime has both).
#
#   card_libc.so.6   a stand-in for the machine's glibc 2.13 libc.so.6: the
#                    soname and symbol versions GLIBC_2.4 .. GLIBC_2.13, no code
#   modern.so        a dlsym hook as any recent gcc builds it: dlsym@GLIBC_2.34
#   old.so           the same hook asking only for GLIBC_2.4 (linked against
#                    card_libc.so.6, which is all the card offers)
#   x86.so           the hook built for the PC
set -eu
cd "$(dirname "$0")"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
CC=arm-linux-gnueabihf-gcc

cat > "$T/libc.map" <<'MAP'
GLIBC_2.4 { global: dlsym; snprintf; write; local: *; };
GLIBC_2.13 { global: pad_newest; } GLIBC_2.4;
MAP
cat > "$T/libc.c" <<'C'
void *dlsym(void *h, const char *n) { (void)h; (void)n; return 0; }
int snprintf(char *b, unsigned long n, const char *f, ...) { (void)b; (void)n; (void)f; return 0; }
long write(int fd, const void *b, unsigned long n) { (void)fd; (void)b; return (long)n; }
int pad_newest(void) { return 13; }
C
$CC -shared -fPIC -nostdlib -Wl,-soname,libc.so.6 -Wl,--version-script="$T/libc.map" \
    -o card_libc.so.6 "$T/libc.c"

cat > "$T/hook.c" <<'C'
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>
static void __attribute__((constructor)) hello(void) {
    char buf[64];
    int n = snprintf(buf, sizeof buf, "%p\n", dlsym(RTLD_DEFAULT, "printf"));
    if (write(2, buf, n) < 0) return;
}
C
$CC -shared -fPIC -O2 -o modern.so "$T/hook.c" -ldl
$CC -shared -fPIC -O2 -U_FORTIFY_SOURCE -fno-stack-protector -nodefaultlibs \
    -o old.so "$T/hook.c" card_libc.so.6
gcc -shared -fPIC -O2 -o x86.so "$T/hook.c"
arm-linux-gnueabihf-strip modern.so old.so card_libc.so.6
strip x86.so
ls -l card_libc.so.6 modern.so old.so x86.so
