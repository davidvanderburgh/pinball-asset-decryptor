#!/usr/bin/env python3
"""lcdart.py <game> <id> - extract one VILLAIN VISION display id's artwork.

Item 83. The lcdnode's display-id frames (padlcd.h) name WHICH stored clip
each LCD insert shows; the clips themselves are QuickTime H.264 assets on the
card - batman ships 3,069 of them, all 240x180, in the villain-TV scene store.
This extracts one id's art to the title's table dir, where the playfield's
LCD panel picks it up - TWO artifacts per id, cheap-first:

    <PAD_TABLES>/<game>/lcd/<id>.png    first frame, ~200 ms, instant paint
    <PAD_TABLES>/<game>/lcd/<id>.gif    looping 10 fps excerpt (<= 15 s) -
                                        the MOTION (David's 2026-08-24 ask:
                                        the real TVs play the clips, stills
                                        were item 83's admitted residual)

The GIF is 10 fps ON PURPOSE: the panel advances one frame per poll and
polls at 10 Hz, so encode rate = display rate with no timer arithmetic on
the Tk side. It is written to a .tmp and os.replace()d so the panel's
frame-by-frame decoder can NEVER see a half-written file - a partial GIF
would decode its early frames fine and then miscount the clip's length.
Rebuilds whichever artifact is missing, so caches extracted before the GIF
stage existed upgrade on the next sighting.

Called LAZILY by the panel the first time it sees an id with no cached art -
3,069 assets x ffmpeg up front would be minutes of mktables time for art most
runs never display; one short extraction per first-seen id is invisible.

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
    png = os.path.join(out_dir, "%s.png" % disp)
    gif = os.path.join(out_dir, "%s.gif" % disp)
    if os.path.isfile(png) and os.path.isfile(gif):
        print(png)
        return 0

    hits = glob.glob(STORE_GLOB % (game, disp))
    if not hits:
        print("no store (card not mounted, or id %s not in it)" % disp)
        return 1
    os.makedirs(out_dir, exist_ok=True)

    # THE STILL FIRST - it is the cheap one and the panel paints it the
    # moment it lands, while the GIF is still encoding behind it.
    if not os.path.isfile(png):
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", hits[0],
                            "-frames:v", "1", png],
                           capture_output=True, timeout=30)
        if r.returncode != 0 or not os.path.isfile(png):
            print("ffmpeg failed: %s"
                  % r.stderr.decode("utf8", "replace")[:200])
            return 1

    if not os.path.isfile(gif):
        tmp = gif + ".tmp"
        # -gifflags -offsetting-transdiff: FULL frames, no delta encoding.
        # The panel decodes with Tk's "gif -index N", which renders each
        # frame STANDALONE - it never composites a frame onto its
        # predecessor - so ffmpeg's default delta frames (changed pixels
        # only, transparent elsewhere) draw as speckle over black. Bigger
        # files, correct pixels.
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-t", "15", "-i", hits[0],
             "-filter_complex",
             "[0:v]fps=10[s];[s]split[a][b];"
             "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse",
             "-gifflags", "-offsetting-transdiff",
             "-loop", "0", "-f", "gif", tmp],
            capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, gif)        # atomic: whole clip or no clip
        else:
            # The still already landed, so a failed GIF degrades to the
            # pre-motion behaviour rather than to a broken cell.
            if os.path.isfile(tmp):
                os.unlink(tmp)
            print("gif stage failed (still kept): %s"
                  % r.stderr.decode("utf8", "replace")[:200])
    print(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
