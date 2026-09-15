#!/bin/bash
# check_elf_jjp_selftest.sh T - prove check_elf_jjp.sh can say no.
#
# A ceiling test that has never refused anything is a test nobody has watched
# work.  This builds the smallest program that carries a too-new symbol the
# way a careless jjpselect link would - fmod, which glibc 2.38 gave a new
# version - against the HOST's libm, and requires the check to FAIL on it
# naming GLIBC_2.38.  On a host whose libm predates 2.38 the control cannot
# be built and the case is SKIPPED out loud, never passed vacuously.
set -e
T=$1
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T"
cat > "$T/toonew.c" <<'EOF'
#include <math.h>
#include <stdlib.h>
int main(int argc, char **argv) { (void)argv; return (int)fmod((double)argc, 2.0); }
EOF
gcc -O0 -fno-builtin -o "$T/toonew" "$T/toonew.c" -lm
if ! readelf --dyn-syms -W "$T/toonew" | grep -q 'fmod@GLIBC_2.38'; then
    echo "check_elf_jjp_selftest: SKIP (this host's libm has no fmod@GLIBC_2.38 to refuse)"
    exit 0
fi
if bash "$HERE/check_elf_jjp.sh" "$T/toonew" > "$T/toonew.out" 2>&1; then
    echo "check_elf_jjp_selftest: FAIL the ceiling accepted a binary needing fmod@GLIBC_2.38"
    cat "$T/toonew.out"
    exit 1
fi
grep -q 'FAIL max GLIBC node GLIBC_2.38' "$T/toonew.out" || {
    echo "check_elf_jjp_selftest: FAIL refused, but not for the right reason:"; cat "$T/toonew.out"; exit 1; }
echo "check_elf_jjp_selftest: OK (a binary needing fmod@GLIBC_2.38 is refused)"
