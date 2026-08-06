#!/usr/bin/env python3
"""framematch.py <capture> <extract> [extract2 ...] - match every captured
frame to its GROUND-TRUTH source frame, and report DELIVERY, not motion.

    py framematch.py "Recording.mp4" gz\video\MechaGodzilla_Loop.mp4

RUN ON WINDOWS. Item 11's referee, and it exists because three cheaper
instruments lied in a row:

  * freezedetect on a 30 fps capture of a 30 fps source is phase-ambiguous -
    it reported 300 "freezes" before a fix and 306 after, both meaningless.
  * change detection of any kind measures the CONTENT: run it on a PRISTINE
    extract and 25% of the intervals read as 67 ms stalls, because this
    footage genuinely has near-duplicate consecutive frames.
  * every in-guest counter read perfectly clean through a stutter David
    could see plainly.

Matching content against the real source has none of those failure modes: a
duplicated frame and a skipped frame are facts about WHICH source frame was
on screen, and near-duplicate source frames cannot manufacture one.

WHAT IT PRINTS, and how to read it at 30-on-30:
    healthy      every source index appears exactly ONCE, ascending by 1
    HELD frame   an index appearing 2+ times  (the hitch you see)
    DROPPED      the index jumping ahead by 2+ (motion skips forward)
Both are counted per second so two runs can be compared directly.

THE PICTURE RECT IS FOUND, NOT ASSUMED. Window geometry differs between
captures (David's recorder, screenrec.py, different window sizes), and a
hardcoded crop silently compares the wrong pixels. A per-pixel standard
deviation over sampled frames lights up exactly the region that carries
video; its bounding box is the picture. Chrome, title bar and the static
player panel have near-zero variance and fall outside it.
"""
import re
import subprocess
import sys

import numpy as np

TH_W, TH_H = 64, 32           # thumbnail size the match runs on
PROBE_N = 240                 # frames sampled to find the moving region


def probe_size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def read_gray(path, w, h, crop=None, scale=None, limit=None):
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
    ow, oh = (scale if scale else (crop[0], crop[1]) if crop else (w, h))
    n = len(raw) // (ow * oh)
    if limit:
        n = min(n, limit)
    return np.frombuffer(raw[:n * ow * oh], np.uint8).reshape(n, oh, ow)


def motion_rect(path):
    """Bounding box of the region that actually MOVES, in this file's pixels.

    THE POINT IS THAT IT IS COMPUTED THE SAME WAY ON BOTH SIDES, so the
    capture's crop and the extract's crop frame the same content without
    anyone knowing the window geometry, the title-bar height, or how the
    1360x768 picture was letterboxed into the client area. A hardcoded rect
    was wrong the moment a second capture tool was used - David's recorder
    and screenrec.py produce different sizes - and a silently misaligned
    crop compares the wrong pixels while still printing confident numbers.

    Motion rather than variance: static chrome has zero of both, but a score
    readout has high variance and low inter-frame motion outside the moments
    it ticks, so motion keeps the box on the video.
    """
    w, h = probe_size(path)
    sw, sh = w // 8 - (w // 8) % 2, h // 8 - (h // 8) % 2
    f = read_gray(path, w, h, scale=(sw, sh),
                  limit=PROBE_N).astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(0)
    thr = max(0.6, d.max() * 0.30)
    ys, xs = np.nonzero(d > thr)
    if not len(xs):
        return 0, 0, w, h
    fx, fy = w / sw, h / sh
    x0, x1 = int(xs.min() * fx), int((xs.max() + 1) * fx)
    y0, y1 = int(ys.min() * fy), int((ys.max() + 1) * fy)
    return x0, y0, x1 - x0, y1 - y0


def interior(rect, fx0=0.0, fy0=0.0, fx1=1.0, fy1=1.0):
    """The rect itself, as an even-sized ffmpeg crop tuple."""
    x, y, w, h = rect
    cx, cy = int(x + w * fx0), int(y + h * fy0)
    cw, ch = int(w * (fx1 - fx0)), int(h * (fy1 - fy0))
    return cw - cw % 2, ch - ch % 2, cx, cy


def main():
    cap_path = sys.argv[1]
    ref_paths = sys.argv[2:]

    cw, ch = probe_size(cap_path)
    crect = motion_rect(cap_path)
    print("capture %dx%d, moving region %s" % (cw, ch, crect))
    C = read_gray(cap_path, cw, ch, crop=interior(crect),
                  scale=(TH_W, TH_H)).astype(np.int16)
    C = C.reshape(len(C), -1)
    print("capture frames: %d" % len(C))

    refs, mats = [], []
    for ci, rp in enumerate(ref_paths):
        rw, rh = probe_size(rp)
        rrect = motion_rect(rp)
        f = read_gray(rp, rw, rh, crop=interior(rrect),
                      scale=(TH_W, TH_H)).astype(np.int16)
        mats.append(f.reshape(len(f), -1))
        refs += [(ci, i) for i in range(len(f))]
        print("ref %d: %s  %d frames, moving region %s"
              % (ci, rp.split("\\")[-1], len(f), rrect))
    R = np.concatenate(mats)

    best = np.empty(len(C), np.int32)
    sad0 = np.empty(len(C), np.float32)
    marg = np.empty(len(C), np.float32)
    for i in range(0, len(C), 48):
        d = np.abs(C[i:i + 48, None, :].astype(np.int32)
                   - R[None, :, :].astype(np.int32)).mean(2)
        best[i:i + 48] = d.argmin(1)
        s = np.sort(d, 1)
        sad0[i:i + 48] = s[:, 0]
        marg[i:i + 48] = s[:, 1] - s[:, 0]

    ref_of = np.array(refs)
    seq = ref_of[best, 1]
    clip = ref_of[best, 0]
    print("match quality: median SAD %.2f (0 = identical), median margin %.2f"
          % (float(np.median(sad0)), float(np.median(marg))))
    if np.median(sad0) > 25:
        print("** SAD is high - the capture may not be showing this clip.")

    runs = []
    j = 0
    for i in range(1, len(best) + 1):
        if i == len(best) or best[i] != best[j]:
            runs.append((int(clip[j]), int(seq[j]), i - j))
            j = i
    lens = np.array([r[2] for r in runs])
    fps = 30.0
    dur = len(C) / fps
    print()
    print("== delivery census over %.1f s ==" % dur)
    print("   (30 fps capture of a 30 fps source: healthy = every run is 1)")
    for L in sorted(set(lens.tolist())):
        n = int((lens == L).sum())
        print("   source frame shown %dx : %4d  (%.1f%%)"
              % (L, n, 100.0 * n / len(runs)))
    held = int((lens >= 2).sum())
    print("   HELD frames (a visible hitch): %d = %.2f/s" % (held, held / dur))
    drops = 0
    dropped_at = []
    for (c0, f0, _), (c1, f1, _) in zip(runs, runs[1:]):
        if c0 == c1 and 2 <= f1 - f0 <= 8:
            drops += f1 - f0 - 1
            dropped_at.append((f0, f1))
    print("   DROPPED frames (motion skips ahead): %d = %.2f/s"
          % (drops, drops / dur))
    if dropped_at:
        print("   first drops (source idx before -> after):",
              "  ".join("%d->%d" % (a, b) for a, b in dropped_at[:12]))
    # A loop should walk 0..N-1 and wrap; count wraps to sanity-check.
    wraps = sum(1 for (c0, f0, _), (c1, f1, _) in zip(runs, runs[1:])
                if c0 == c1 and f1 < f0 - 5)
    print("   loop wraps seen: %d" % wraps)


if __name__ == "__main__":
    main()
