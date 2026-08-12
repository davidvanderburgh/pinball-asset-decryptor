#!/usr/bin/env python3
"""Differential scan of two GAME STATES, from guestmem.py snapshots.

  python3 memdiff.py --a dots_*.bin --b band_*.bin

Keeps a word only if it is STEADY across every snapshot of state A, STEADY
across every snapshot of state B, and DIFFERENT between them. The steadiness
test is the whole instrument: without it a 983 KB window is mostly animation
counters, and every one of them differs.

TAKE SEVERAL SNAPSHOTS PER STATE, seconds apart, and MATCH THE CONFIGURATIONS.
Learned the expensive way on 2026-08-12: a first pass diffed a pinned run
against a door-gate run and produced eight beautiful boolean flips, all of which
turned out to be differences between the two BUILDS rather than between the two
PICTURES - the give-away was poking them in a live run and finding they already
held the "other" value. Re-run with the two configs identical except for the one
thing under test and the survivor count drops by a quarter and the noise by more.

Output is clustered, because a real decision variable usually sits in a struct
with its neighbours rather than alone in the middle of nothing, and split into
small values (flags, enums, counters - things you can poke) and pointers (things
you cannot transplant between processes, but whose PRESENCE is itself the
finding: a table that is null in one state and full in the other is an object
list that only exists in the other).
"""
import glob
import struct
import sys

LO = 0x5F8000


def load(patterns):
    files = []
    for p in patterns:
        files += sorted(glob.glob(p))
    return [open(f, "rb").read() for f in files], files


def main():
    argv = sys.argv[1:]
    if "--a" not in argv or "--b" not in argv:
        print(__doc__)
        return 2
    ai, bi = argv.index("--a"), argv.index("--b")
    if ai < bi:
        ap, bp = argv[ai + 1:bi], argv[bi + 1:]
    else:
        bp, ap = argv[bi + 1:ai], argv[ai + 1:]
    A, af = load(ap)
    B, bf = load(bp)
    if not A or not B:
        print("need at least one snapshot per state")
        return 2
    n = min(min(len(x) for x in A), min(len(x) for x in B))
    print(f"state A: {len(A)} snapshots {af[0]}...")
    print(f"state B: {len(B)} snapshots {bf[0]}...")

    hits = []
    for off in range(0, n - 3, 4):
        av = struct.unpack_from("<I", A[0], off)[0]
        if any(struct.unpack_from("<I", x, off)[0] != av for x in A[1:]):
            continue
        bv = struct.unpack_from("<I", B[0], off)[0]
        if bv == av:
            continue
        if any(struct.unpack_from("<I", x, off)[0] != bv for x in B[1:]):
            continue
        hits.append((LO + off, av, bv))

    small = [h for h in hits if h[1] < 0x100000 and h[2] < 0x100000]
    ptr = [h for h in hits if h not in small]
    print(f"\n{len(hits)} words steady in both states and different between "
          f"them: {len(small)} small-valued, {len(ptr)} pointer-ish\n")

    print("=== SMALL-VALUED (pokeable with guestmem.py poke)")
    for a, av, bv in small:
        tag = ""
        if {av, bv} <= {0, 1}:
            tag = "   <<< BOOLEAN"
        if a == 0x650744:
            tag = "   (app mode - poking it ejects you from the menu)"
        if a == 0x663958:
            tag = "   (in-service-menu)"
        print(f"  0x{a:x}  A={av:<10} B={bv:<10}{tag}")

    print("\n=== POINTER-ISH, clustered (presence is the finding)")
    clusters, cur = [], []
    for h in ptr:
        if cur and h[0] - cur[-1][0] <= 64:
            cur.append(h)
        else:
            if cur:
                clusters.append(cur)
            cur = [h]
    if cur:
        clusters.append(cur)
    clusters.sort(key=len, reverse=True)
    for c in clusters[:12]:
        nulls_a = sum(1 for _, av, _ in c if av == 0)
        nulls_b = sum(1 for _, _, bv in c if bv == 0)
        note = ""
        if nulls_a == len(c) and nulls_b == 0:
            note = "  <<< NULL in A, populated in B - an object list A never built"
        if nulls_b == len(c) and nulls_a == 0:
            note = "  <<< NULL in B, populated in A"
        print(f"  {len(c)} words at 0x{c[0][0]:x}..0x{c[-1][0]:x}{note}")
    return 0


sys.exit(main())
