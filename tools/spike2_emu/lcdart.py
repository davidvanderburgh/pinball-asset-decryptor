#!/usr/bin/env python3
"""lcdart.py <game> <id> - extract one VILLAIN VISION display id's artwork.

Item 83. The lcdnode's display-id frames (padlcd.h) name WHICH stored clip
each LCD insert shows; the clips themselves are QuickTime H.264 assets on the
card - batman ships 3,069 of them, all 240x180, in the villain-TV scene store.
This extracts one id's art to the title's table dir, where the playfield's
LCD panel picks it up - TWO artifacts per id, cheap-first:

    <PAD_TABLES>/<game>/lcd/<id>.png    first frame, ~200 ms, instant paint
    <PAD_TABLES>/<game>/lcd/<id>.webp   looping 10 fps excerpt (<= 15 s) -
                                        the MOTION (David's 2026-08-24 ask:
                                        the real TVs play the clips, stills
                                        were item 83's admitted residual)

10 fps ON PURPOSE: the panel advances one frame per poll and polls at 10 Hz,
so encode rate = display rate with no timer arithmetic on the Tk side. Each
artifact is written to a .tmp and os.replace()d so the panel's frame-by-frame
decoder can NEVER see a half-written file. Rebuilds whichever artifact is
missing, so older caches upgrade themselves on the next sighting.

LOSSLESS WEBP, NOT GIF, AND `-pix_fmt bgra` IS LOAD-BEARING (David, live,
2026-08-24: "the gif color looks off somehow (like it's not rendering the
correct bit depth)"). He was reading it exactly right: GIF is 8-bit
PALETTE, and a 256-colour palette plus error-diffusion dithering scatters
bright confetti over dark 1966 footage. Measured against true-colour
reference frames of a real clip (id 3004, 30 frames):

    format                        size   MAE   PSNR  pixels off by >30
    gif palettegen+dither (was)  981 KB  2.88  34.6  0.167%
    gif full palette, no dither  896 KB  2.40  36.2  0.088%
    apng (true colour)          2436 KB  0.00  99.0  0.000%
    webp lossless (no pix_fmt)  1461 KB  1.56  39.3  0.042%
    webp lossless -pix_fmt bgra 1233 KB  0.00  99.0  0.000%   <-- this

So this is now BIT-EXACT, at 1.2 MB per 3 s and 1.0 ms/frame to decode
(faster than the GIF it replaces, and most clips are 1-4 s: sampled
durations run 0.7-3.8 s with a couple near 13 s). Without the explicit
`-pix_fmt bgra`, "lossless" still lands 1.56 MAE - libwebp takes ffmpeg's
default yuv420p and the YUV->RGB round trip is the loss, which is exactly
the kind of silent-but-visible defect the number above is here to pin.

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

Needs the card MOUNTED (any run has it); reports 'no store' otherwise and
the panel re-asks with a ~60 s backoff while either artifact is missing, so
a store that mounts later heals in-session. BOTH artifacts are written
atomically (.tmp + os.replace): every validity check in this pipeline is
os.path.isfile, so a torn write would otherwise poison the id for ever -
nothing ever rewrites an existing file.

FAILURES ALSO LAND IN <out_dir>/lcdart.log. The panel launches this through
run_script, which captures and DISCARDS stdout - without the log, a failed
encode is indistinguishable from one still running. Exit codes: 0 = all
artifacts present, 1 = nothing produced, 2 = still kept but the clip stage
failed (the panel ignores codes; a batch caller must not count 2 as done).
"""
import glob
import os
import subprocess
import sys
import time

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
    clip = os.path.join(out_dir, "%s.webp" % disp)
    if os.path.isfile(png) and os.path.isfile(clip):
        print(png)
        return 0
    os.makedirs(out_dir, exist_ok=True)

    def log(msg):
        # stdout is captured and thrown away by run_script - this file is
        # the only trace a failure leaves. Best-effort on purpose.
        print(msg)
        try:
            with open(os.path.join(out_dir, "lcdart.log"), "a") as f:
                f.write("%s id %s: %s\n"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"), disp, msg))
        except OSError:
            pass

    hits = glob.glob(STORE_GLOB % (game, disp))
    if not hits:
        log("no store (card not mounted, or id %s not in it)" % disp)
        return 1

    # THE STILL FIRST - it is the cheap one and the panel paints it the
    # moment it lands, while the clip is still encoding behind it. Through a
    # .tmp: a torn png would pass every isfile check in the pipeline for
    # ever (nothing rewrites an existing file), showing a permanent
    # placeholder over a perfectly good clip.
    if not os.path.isfile(png):
        tmp = png + ".tmp"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", hits[0],
                            "-frames:v", "1", "-c:v", "png", "-f", "image2",
                            tmp],
                           capture_output=True, timeout=30)
        if r.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, png)
        else:
            if os.path.isfile(tmp):
                os.unlink(tmp)
            log("png stage failed: %s"
                % r.stderr.decode("utf8", "replace")[:200])
            return 1

    if not os.path.isfile(clip):
        tmp = clip + ".tmp"
        # `-pix_fmt bgra` is not decoration: without it libwebp takes
        # ffmpeg's default yuv420p and "lossless" still costs 1.56 MAE on
        # the YUV->RGB round trip. With it the frames are bit-exact. See
        # the module docstring's measured table.
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-t", "15", "-i", hits[0],
             "-vf", "fps=10", "-c:v", "libwebp", "-lossless", "1",
             "-pix_fmt", "bgra", "-loop", "0", "-f", "webp", tmp],
            capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, clip)       # atomic: whole clip or no clip
        else:
            # The still already landed, so a failed clip degrades to the
            # pre-motion behaviour rather than to a broken cell - but say
            # so with exit 2, not a lying 0: a batch pre-warm that counted
            # this as done would never come back for the motion.
            if os.path.isfile(tmp):
                os.unlink(tmp)
            log("clip stage failed (still kept): %s"
                % r.stderr.decode("utf8", "replace")[:200])
            print(png)
            return 2
    # The palette era's artifact, if this id predates the switch: it is
    # dead weight now (the panel only reads .webp) and each one is ~1 MB.
    stale = os.path.join(out_dir, "%s.gif" % disp)
    if os.path.isfile(stale):
        try:
            os.unlink(stale)
        except OSError:
            pass
    print(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
