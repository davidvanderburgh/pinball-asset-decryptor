#!/bin/bash
# swlayout.sh - prove the THREE copies of the switch block's layout agree.
#
# WHY THIS EXISTS. padsw.h is the definition, and there are two hand-written
# copies of it that the compiler cannot check:
#
#   - hwshim.c builds -nostdlib and cannot include the header at all, so it
#     carries its own `struct padsw_shm` and its own comment saying "a field
#     added there has to be added here as well";
#   - padsw.py carries the same struct as a list of byte offsets, because the
#     helpers are Python and mmap has no idea what a struct is.
#
# A drift between them is SILENT and it is not a crash: it is a script writing
# switch 59 into the middle of the merged array, or the guest reading a
# generation counter out of somebody's switch. This rig's non-negotiables
# already say "never let two scripts define the same fact", and this is the one
# place where the fact is defined three times because it genuinely has to be.
# So check it instead of trusting it, in a second, at any time.
#
#   bash swlayout.sh          # prints every field, three columns, and a verdict
#
# Exits non-zero on drift, so it can go in front of a build.
set -u
S=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# The hwshim mirror below is a VERBATIM copy of the struct in hwshim.c. Copying
# it is the point: this file is asking "does that text still describe the same
# layout as the header", and paraphrasing it would answer a different question.
cat > "$T/swoff.c" <<'EOF'
#include <stddef.h>
#include <stdio.h>
#include "padsw.h"

struct shim_mirror {
    unsigned magic; unsigned gen; unsigned char held[256];
    unsigned tap_gen; unsigned tap_id; unsigned tap_reads;
    unsigned scr_gen; unsigned char scr_held[256];
    unsigned mrg_gen; unsigned char mrg[256];
    unsigned kbd_src; unsigned scr_src; unsigned guest_t0_ms;
};

#define P(f) printf("%s %zu %zu\n", #f, offsetof(struct padsw_shm, f), \
                    offsetof(struct shim_mirror, f))

int main(void)
{
    P(magic); P(gen); P(held); P(tap_gen); P(tap_id); P(tap_reads);
    P(scr_gen); P(scr_held); P(mrg_gen); P(mrg);
    P(kbd_src); P(scr_src); P(guest_t0_ms);
    printf("SIZE %zu %zu\n", sizeof(struct padsw_shm), sizeof(struct shim_mirror));
    printf("BYTES %d %d\n", PADSW_BYTES, PADSW_BYTES);
    return 0;
}
EOF

gcc -I"$S" -o "$T/swoff" "$T/swoff.c" || {
    echo "[swlayout] could not build the offset probe" >&2; exit 2; }
"$T/swoff" > "$T/off.txt" || exit 2

# grep the hwshim.c struct out of the real file too, so a mirror edited here and
# not there (or the other way round) is caught rather than papered over.
sed -n '/^struct padsw_shm {/,/^};/p' "$S/hwshim.c" > "$T/real.txt"
sed -n '/^struct shim_mirror {/,/^};/p' "$T/swoff.c" \
    | sed 's/shim_mirror/padsw_shm/' > "$T/copy.txt"
if ! diff -q "$T/real.txt" "$T/copy.txt" >/dev/null; then
    echo "[swlayout] *** the mirror in this script no longer matches hwshim.c ***"
    diff "$T/real.txt" "$T/copy.txt" || true
    echo "[swlayout] update the struct inside swlayout.sh, then run it again."
    exit 1
fi

# PYTHONPYCACHEPREFIX POINTS AT AN EMPTY TEMP DIR, and it is not tidiness.
# Python decides a cached .pyc is current by comparing the source mtime it
# recorded, TO THE SECOND. Editing padsw.py and re-running this inside the same
# second reads the OLD bytecode and prints the OLD offsets - which is a checker
# that says whatever it said last time, and it was caught doing exactly that
# while this script was being written. An empty cache directory has nothing to
# reuse, so the source is always recompiled.
PYTHONPATH="$S" PYTHONPYCACHEPREFIX="$T/pyc" python3 - "$T/off.txt" <<'EOF'
import sys
import padsw as p

WANT = [("magic", p.OFF_MAGIC), ("gen", p.OFF_GEN), ("held", p.OFF_HELD),
        ("tap_gen", p.OFF_TAP_GEN), ("tap_id", p.OFF_TAP_ID),
        ("tap_reads", p.OFF_TAP_READS), ("scr_gen", p.OFF_SCR_GEN),
        ("scr_held", p.OFF_SCR_HELD), ("mrg_gen", p.OFF_MRG_GEN),
        ("mrg", p.OFF_MRG), ("kbd_src", p.OFF_KBD_SRC),
        ("scr_src", p.OFF_SCR_SRC), ("guest_t0_ms", p.OFF_GUEST_T0),
        ("SIZE", p.SIZE)]

got = {}
for line in open(sys.argv[1]):
    f = line.split()
    got[f[0]] = (int(f[1]), int(f[2]))

bad = 0
print("field         padsw.h  hwshim.c  padsw.py")
for name, off in WANT:
    h, m = got[name]
    ok = h == m == off
    bad += not ok
    print("%-12s  %7d  %8d  %8d  %s"
          % (name, h, m, off, "" if ok else "*** DRIFT ***"))

block = got["BYTES"][0]
if p.SIZE > block:
    print("*** the struct is %d bytes and the block is %d ***" % (p.SIZE, block))
    bad += 1

print()
if bad:
    print("%d FIELD(S) DRIFTED - fix before running anything." % bad)
    sys.exit(1)
print("all three copies agree, and %d bytes fit in the %d-byte block."
      % (p.SIZE, block))
EOF
