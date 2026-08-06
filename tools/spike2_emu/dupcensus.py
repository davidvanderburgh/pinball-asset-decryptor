#!/usr/bin/env python3
"""dupcensus.py <video> [more videos...] - how often does a video REPEAT a
frame it already showed? The held-frame rate, with no alignment anywhere.

    py dupcensus.py "Recording.mp4" gz\\video\\MechaGodzilla_Loop.mp4

RUN ON WINDOWS. This is item 11's fourth instrument and the first one that
survives its own calibration, so the three it replaces are worth naming:

  * freezedetect on a screen capture: phase-ambiguous at 30-on-30, reported
    300 freezes before a fix and 306 after, both meaningless.
  * a change-interval histogram: read 25% of a PRISTINE extract as stalls,
    because this footage has genuinely near-duplicate frames.
  * ground-truth frame MATCHING against David's pure extracts
    (framematch.py): correct in principle, and it failed in practice on real
    captures - the game bakes score/text overlays into the picture, the
    capture and the extract therefore have differently-shaped moving
    regions, and the crops never framed the same content. Its margin
    collapsed to 0.05 and it claimed 40 loop wraps inside 21.8 s of a 66 s
    clip. Impossible, therefore discarded. Do NOT revive it without solving
    the alignment properly.

WHAT THIS MEASURES INSTEAD: the mean absolute difference between each pair
of consecutive frames, over the region that moves. A frame the pipeline held
is a pair with a difference of ~0. No source frame needs to be identified,
so overlays, scaling, letterboxing and window geometry cannot corrupt it -
they are identical in both frames of a pair and subtract away.

IT IS ONLY MEANINGFUL AGAINST ITS CONTROL, which is why it takes several
files. Run the pristine extract of the same clip alongside the capture: the
extract's own duplicate rate is the floor this content can produce, and only
the EXCESS above that floor is the emulator dropping frames. A capture whose
rate matches its extract is delivering everything.

One honest limit: a 30 fps recording of a 30 fps source has clock beat, so a
few percent of duplicates are the recorder's, not the emulator's. Compare
runs, and prefer a 60 fps capture when the absolute number matters.
"""
import subprocess
import sys

import numpy as np

PROBE_N = 400
# A REPEATED frame differs only by codec noise, so its delta is ~0 - NOT
# "small". 0.35 was a guess and it was wrong: on a low-motion clip the real
# motion itself sits at 0.19, so the guess swallowed the entire distribution
# and reported 96.7% repeats for a capture whose true rate was 1.8%. Read off
# the measured distributions instead: a genuinely repeated frame lands under
# 0.10 with a clear GAP above it (David's capture: 22.4% under 0.10, next
# mode at 1.8), and this threshold gives the same answer anywhere from 0.1 to
# 1.0 on content that has a gap at all.
EPS = 0.10
# If the deltas are NOT bimodal there is no repeat/motion boundary to find,
# and any number here would be the threshold talking rather than the video.
# Say so instead of printing it.
GAP_MIN = 4.0       # motion mode must be this many x the repeat threshold


def probe_size(path):
    # FIRST video stream only: an mkv with more than one stream entry made
    # ffprobe print several lines, and splitting the lot on "," fed a
    # width into the frame-rate parse.
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip().splitlines()[0].split(",")
    num, den = out[2].split("/")
    return int(out[0]), int(out[1]), float(num) / float(den)


def read_gray(path, crop=None, scale=None):
    vf = []
    if crop:
        vf.append("crop=%d:%d:%d:%d" % crop)
    if scale:
        vf.append("scale=%d:%d" % scale)
    cmd = ["ffmpeg", "-v", "error", "-i", path]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-pix_fmt", "gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    ow, oh = scale
    n = len(raw) // (ow * oh)
    return np.frombuffer(raw[:n * ow * oh], np.uint8).reshape(n, oh, ow)


def moving_region(path):
    w, h, _ = probe_size(path)
    sw, sh = w // 8 - (w // 8) % 2, h // 8 - (h // 8) % 2
    f = read_gray(path, scale=(sw, sh))[:PROBE_N].astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(0)
    thr = max(0.6, d.max() * 0.30)
    ys, xs = np.nonzero(d > thr)
    if not len(xs):
        return 0, 0, w, h
    fx, fy = w / sw, h / sh
    x0, x1 = int(xs.min() * fx), int((xs.max() + 1) * fx)
    y0, y1 = int(ys.min() * fy), int((ys.max() + 1) * fy)
    cw, ch = x1 - x0, y1 - y0
    return cw - cw % 2, ch - ch % 2, x0, y0


def census(path):
    w, h, fps = probe_size(path)
    crop = moving_region(path)
    f = read_gray(path, crop=crop, scale=(160, 90)).astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean((1, 2))
    n = len(d)
    dup = d < EPS
    # runs of consecutive duplicates = one held frame each, length = how long
    runs, j = [], None
    for i, v in enumerate(dup):
        if v and j is None:
            j = i
        elif not v and j is not None:
            runs.append(i - j)
            j = None
    if j is not None:
        runs.append(n - j)
    dur = n / fps
    print("%-46s %5d frames @ %.0f fps, moving region %dx%d"
          % (path.split("\\")[-1][:46], n + 1, fps, crop[0], crop[1]))
    moving = d[~dup]
    med_motion = float(np.median(moving)) if len(moving) else 0.0
    if med_motion < EPS * GAP_MIN:
        print("      ** NOT JUDGED: the deltas are not bimodal (motion median"
              " %.2f vs repeat threshold %.2f)." % (med_motion, EPS))
        print("      ** This clip barely moves, so 'repeat' and 'slight"
              " change' are the same number here. Point it at a scene with"
              " real motion, or the answer is the threshold talking.")
        return -1.0
    print("      repeated frames: %5d of %d pairs = %5.1f%%   (%.2f per second)"
          % (int(dup.sum()), n, 100.0 * dup.sum() / n, dup.sum() / dur))
    if runs:
        print("      held-frame events: %d, longest hold %d extra frames "
              "(%.0f ms)" % (len(runs), max(runs), max(runs) * 1000.0 / fps))
    print("      motion when it DOES move: median %.2f" %
          float(np.median(d[~dup])) if (~dup).any() else "")
    return 100.0 * dup.sum() / n


def main():
    rates = []
    for p in sys.argv[1:]:
        rates.append((p, census(p)))
        print()
    if len(rates) >= 2:
        base = rates[-1][1]
        print("== against the last file as the control (%.1f%%) =="
              % base)
        for p, r in rates[:-1]:
            print("   %-40s %+.1f points of EXCESS repeats"
                  % (p.split("\\")[-1][:40], r - base))


if __name__ == "__main__":
    main()
