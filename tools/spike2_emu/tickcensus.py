#!/usr/bin/env python3
"""tickcensus.py <capture.mkv> - measure on-screen video holds WITHOUT the
screen grabber's jitter in the number.

    (run the emulator with PAD_GL_TICK=1, capture at 60 fps, then)
    py tickcensus.py c:\\tmp\\spike2_item11\\tick60.mkv

RUN ON WINDOWS. This is item 11's FIFTH instrument, and it exists because the
fourth had a hole that invalidated a day of numbers.

WHAT WENT WRONG BEFORE: dupcensus.py compared a CAPTURE against a pristine
FILE. The file carries no capture jitter; the capture carries plenty - the
per-swap tick measured gdigrab double-sampling 36.8% of frames and skipping
another 30.3%, netting to exactly 1.0 swap per captured frame. So its "22.7%
excess repeats" was a real fault PLUS the recorder's jitter, inseparably.

HOW THIS FIXES IT: padglhost stamps every swap with a counter (PAD_GL_TICK).
Decode it per captured frame and keep ONLY the pairs where the tick advanced
by exactly 1 - i.e. this captured frame and the last are genuinely adjacent
SWAPS, with nothing missed and nothing sampled twice. Every jittered pair is
discarded rather than believed.

READING THE ANSWER. Video is 30 fps and the renderer swaps at 60, so across
two adjacent swaps the video content should be identical exactly HALF the
time (the frame's second showing) and different the other half.

    ~50%   perfect delivery
    >50%   video frames occupying 3+ swaps - the hold, and the stutter
    <50%   video advancing faster than 30 fps, which would be its own bug

The baseline is 50 and NOT 0, which is the trap in reading it: a naive
"repeats are bad" reading calls a perfectly healthy pipeline 50% broken.
"""
import subprocess
import sys

import numpy as np

TICK_CROP = (176, 24, 0, 848)      # w,h,x,y - GL origin is BOTTOM-left
CONTENT_CROP = (1442, 624, 30, 150)
EPS = 0.10


def read(path, crop, scale):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", "crop=%d:%d:%d:%d,scale=%d:%d" % (crop + scale),
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    w, h = scale
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w)


def main():
    path = sys.argv[1]
    t = read(path, TICK_CROP, TICK_CROP[:2])
    vals = []
    for i in range(len(t)):
        v = 0
        for b in range(8):
            x = 8 + b * 20
            if t[i, 8:20, x + 2:x + 14].mean() > 110:
                v |= 1 << b
        vals.append(v)
    vals = np.array(vals)
    if len(set(vals.tolist())) < 8:
        print("** the tick did not decode - was PAD_GL_TICK=1 set?")
        return 1
    d = np.diff(vals.astype(np.int32)) & 0xff

    c = read(path, CONTENT_CROP, (192, 108)).astype(np.float32)
    n = min(len(c), len(vals))
    delta = np.abs(np.diff(c[:n], axis=0)).mean((1, 2))
    d = d[:n - 1]

    keep = d == 1
    if keep.sum() < 50:
        print("** too few clean pairs (%d) to judge" % int(keep.sum()))
        return 1
    same = delta[keep] < EPS
    moving = delta[keep][~same]
    print("captured %d frames; %d adjacent-swap pairs kept, %d discarded as"
          " grabber jitter (%.1f%%)"
          % (n, int(keep.sum()), int((~keep).sum()),
             100.0 * (~keep).sum() / len(d)))
    if len(moving) and float(np.median(moving)) < EPS * 4:
        print("** NOT JUDGED: content barely moves (motion median %.2f)."
              % float(np.median(moving)))
        return 1
    pct = 100.0 * same.mean()
    print("identical content across adjacent swaps: %.1f%%" % pct)
    print("   50%% = perfect 30-on-60 delivery; higher = frames held longer")
    print("   excess over the 50%% baseline: %+.1f points" % (pct - 50.0))
    # Holds, in frames-per-second terms, from the excess only.
    swaps_per_s = 60.0
    print("   implied holds: %.2f/s (excess pairs x swap rate)"
          % ((pct - 50.0) / 100.0 * swaps_per_s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
