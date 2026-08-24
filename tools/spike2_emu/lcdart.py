#!/usr/bin/env python3
"""lcdart.py <game> <id> - extract one VILLAIN VISION display id's artwork.

Item 83. The lcdnode's display-id frames (padlcd.h) name WHICH stored clip
each LCD insert shows; the clips themselves are QuickTime H.264 assets on the
card - batman ships 3,069 of them, all 240x180, in the villain-TV scene store.
This extracts one id's FIRST FRAME to the title's table dir, where the
playfield's LCD panel picks it up:

    <PAD_TABLES>/<game>/lcd/<id>.png

Called LAZILY by the panel the first time it sees an id with no cached art -
3,069 assets x ffmpeg up front would be minutes of mktables time for art most
runs never display; one ~200 ms extraction per first-seen id is invisible.

THE STORE PATH. `137.asset` is the villain-TV bundle's number inside
batman's auto_loaded scene store (radium label "VillainTvsCombo") - the ONLY
lcdnode title known, so the number is a constant with this comment rather
than a per-title table nobody else has a row for. The id-to-asset mapping is
EYEBALL-VERIFIED (2026-08-24): id 54 = Robin in the Batmobile (the steady
attract id), id 919 = a wall-climb cameo (game-start trio), 3047+ = the
per-villain portraits the radium names. A second lcdnode title is the cue to
derive the store per title instead.

Needs the card MOUNTED (any run has it); prints 'no store' otherwise and the
panel simply retries on a later sighting.
"""
import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

STORE_GLOB = os.path.expanduser(
    "~/card/*/%s/assets/lcd/auto_loaded/*/scene.assets/137.asset/%s.asset")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: lcdart.py <game> <id>")
    game, disp = sys.argv[1], sys.argv[2]
    if not disp.isdigit():
        raise SystemExit("lcdart.py: id must be a number")

    out_dir = os.path.join(padpath.tables() or "", game, "lcd")
    out = os.path.join(out_dir, "%s.png" % disp)
    if os.path.isfile(out):
        print(out)
        return 0

    hits = glob.glob(STORE_GLOB % (game, disp))
    if not hits:
        print("no store (card not mounted, or id %s not in it)" % disp)
        return 1
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", hits[0],
                        "-frames:v", "1", out],
                       capture_output=True, timeout=30)
    if r.returncode != 0 or not os.path.isfile(out):
        print("ffmpeg failed: %s" % r.stderr.decode("utf8", "replace")[:200])
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
