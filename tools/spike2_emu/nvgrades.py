#!/usr/bin/env python3
r"""nvgrades.py - read the PERSISTED game-validation grades out of every title's
emulated EEPROM, and optionally clear a stale failure.

    nvgrades.py                 # census: which titles carry a stored F or E
    nvgrades.py --fix <title>   # zero the validation area for one title
    nvgrades.py --fix-all       # ...for every title carrying an F or E

WHY THIS EXISTS. `GAME VALIDATION ERROR #3` on the Tech Alerts screen is not
necessarily about the boot you are looking at. The validation module PERSISTS
its three track grades and RESTORES them over its own globals at start-up,
initialising only when that restore fails. So the banner can be a fossil: a
failure recorded by some earlier run, replayed forever.

On a normal card that self-heals, because the state machine re-grades the tracks
during boot. On a card whose validation tick has been patched out - the upscaled
turtles_pro card and the Heisei custom godzilla_le image both are, see
valtick.py - nothing is left alive to re-grade it, and the banner is PERMANENT
and UNCLEARABLE. That is the whole fault, proven 2026-08-23 by three controlled
boots of the Heisei image.

THE LAYOUT, found by searching the EEPROM for the live struct's own bytes rather
than guessing from file sizes:

    /data/nvram.bin  offset 0x214   area-80 blob, 532 bytes (0x214 long)
                     0x214          slot A   grades at +42 (GE) +43 (CE) +44 (ZK)
                     0x244          slot B   same layout
                     state values   0 "S"  1 "P" passed  2 "F" fail  3 "E" error

The game selects slot B when the build stamp at +34 does not match the running
build's, which is why a title can look clean in slot A and still show the banner.

WHY IT ZEROES RATHER THAN SETTING "P". An invalid blob makes the restore fail,
which sends the module down its normal initialise path - the game's own code
choosing its own defaults. Writing a "pass" ourselves would be the emulator
forging a validation result, which is a different and much worse thing.

Zeroing touches ONLY the module's own 532 bytes. Identity, settings, audits and
high scores live elsewhere in the 64 KB and are why `rm nvram.bin` is the wrong
fix.
"""
import glob
import os
import shutil
import sys

BLOB = 0x214                  # area-80 blob base in the EEPROM image
BLOB_LEN = 532
SLOT_A, SLOT_B = 0x214, 0x244
GE, CE, ZK = 42, 43, 44
NAMES = {0: "S", 1: "P", 2: "F", 3: "E"}
BAD = (2, 3)                  # what the alert provider raises on

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath


def nvram_dir():
    r = padpath.root()
    return os.path.join(r, "data") if r else None


def grades(d, slot):
    return tuple(d[slot + k] for k in (GE, CE, ZK))


def fmt(g):
    return "/".join(NAMES.get(x, "?") for x in g)


def stuck(d):
    return any(x in BAD for x in grades(d, SLOT_A) + grades(d, SLOT_B))


def load(p):
    with open(p, "rb") as f:
        d = f.read()
    return d if len(d) >= SLOT_B + 48 else None


def census(paths):
    rows = []
    print("%-34s  %-9s  %-9s  %s" % ("nvram", "slot A", "slot B", ""))
    for p in paths:
        d = load(p)
        if d is None:
            continue
        s = stuck(d)
        rows.append((p, s))
        print("%-34s  %-9s  %-9s  %s"
              % (os.path.basename(p), fmt(grades(d, SLOT_A)), fmt(grades(d, SLOT_B)),
                 "STUCK - shows the banner on a nopped card" if s else ""))
    n = sum(1 for _p, s in rows if s)
    print("\n%d of %d carry a stored F or E" % (n, len(rows)))
    if n:
        print("On a card with a healthy validation tick these clear themselves on the\n"
              "next boot. On a nopped card they never do - check with valtick.py.")
    return rows


def fix(p):
    d = load(p)
    if d is None:
        print("%-34s  too small, skipped" % os.path.basename(p))
        return False
    before = fmt(grades(d, SLOT_B))
    shutil.copy2(p, p + ".bak-prevalfix")
    b = bytearray(d)
    b[BLOB:BLOB + BLOB_LEN] = b"\x00" * BLOB_LEN
    with open(p, "wb") as f:
        f.write(bytes(b))
    print("%-34s  slot B %s -> %s   (0x%x..0x%x zeroed, backup .bak-prevalfix)"
          % (os.path.basename(p), before, fmt(grades(bytes(b), SLOT_B)),
             BLOB, BLOB + BLOB_LEN - 1))
    return True


def main():
    d = nvram_dir()
    if not d or not os.path.isdir(d):
        raise SystemExit("nvgrades.py: no rootfs data directory (is PAD_ROOT set?)")
    paths = sorted(glob.glob(os.path.join(d, "nvram*.bin")))
    if not paths:
        raise SystemExit("nvgrades.py: no nvram images under %s" % d)

    argv = sys.argv[1:]
    if not argv:
        census(paths)
        return 0
    if argv[0] == "--fix-all":
        n = sum(1 for p in paths if load(p) and stuck(load(p)) and fix(p))
        print("\nfixed %d file(s)" % n)
        return 0
    if argv[0] == "--fix":
        if len(argv) < 2:
            raise SystemExit("nvgrades.py: --fix needs a title")
        want = os.path.join(d, "nvram-%s.bin" % argv[1])
        if not os.path.exists(want):
            raise SystemExit("nvgrades.py: no such file: %s" % want)
        fix(want)
        return 0
    raise SystemExit("usage: nvgrades.py [--fix <title> | --fix-all]")


if __name__ == "__main__":
    sys.exit(main())
