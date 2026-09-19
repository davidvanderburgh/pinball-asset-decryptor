#!/usr/bin/env python3
"""Did the game play OUR sound? Score /dump/audio.raw against the clip we encoded.

The capture is headerless s16le 48 kHz STEREO (alsastub's PAD_AUDIO_OUT); the source
is 44.1 kHz MONO. So this resamples the source to the capture's rate, slides it over
the capture, and reports the best normalised correlation and where it landed.

Correlation alone is not the whole claim, which is why the clip is a three-tone
figure with gaps: ONSETS are counted independently. Four seconds at three tones a
second is twelve onsets, and a stock Godzilla callout has nothing like that shape.

  score130.py <capture.raw> <source.wav> [capture_rate] [capture_channels]
"""
import sys
import wave

import numpy as np

CAP, SRC = sys.argv[1], sys.argv[2]
CRATE = int(sys.argv[3]) if len(sys.argv) > 3 else 48000
CCH = int(sys.argv[4]) if len(sys.argv) > 4 else 2

cap = np.frombuffer(open(CAP, "rb").read(), dtype="<i2").astype(np.float64)
if CCH > 1:
    cap = cap[:len(cap) // CCH * CCH].reshape(-1, CCH).mean(axis=1)
print("capture %s: %d samples, %.2f s at %d Hz, peak %d, rms %.0f"
      % (CAP, len(cap), len(cap) / float(CRATE), CRATE,
         int(np.abs(cap).max()) if len(cap) else 0,
         cap.std() if len(cap) else 0))

with wave.open(SRC, "rb") as w:
    srate, sch = w.getframerate(), w.getnchannels()
    src = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
if sch > 1:
    src = src[:len(src) // sch * sch].reshape(-1, sch).mean(axis=1)
print("source  %s: %d samples, %.2f s at %d Hz" % (SRC, len(src), len(src) / float(srate), srate))

# DO NOT RESAMPLE. The engine plays a 44.1 kHz record's samples out at 48 kHz, so
# the capture carries them one-for-one and resampling the reference to "match" the
# capture rate pitch-shifts it by 8.8% - which a correlation cannot survive. This
# produced SIX false negatives in item 130 before a stock-record control caught it:
# resampled 44.1->48 a known-good sound scores 0.03, taken as-is it scores 0.9925.
# PAD_SCORE_RESAMPLE=1 restores the old behaviour for a capture that really is
# rate-converted.
import os  # noqa: E402
if os.environ.get("PAD_SCORE_RESAMPLE") == "1":
    n_out = int(len(src) * CRATE / float(srate))
    src_r = np.interp(np.linspace(0, len(src) - 1, n_out), np.arange(len(src)), src)
    print("(resampling %d -> %d; PAD_SCORE_RESAMPLE=1)" % (srate, CRATE))
else:
    src_r = src

if len(cap) < len(src_r):
    print("capture is SHORTER than the source: nothing to align")
    raise SystemExit(1)

# normalised cross-correlation, coarse then fine
a = src_r - src_r.mean()
a /= (np.linalg.norm(a) or 1.0)
best, best_off = -2.0, -1
step = max(1, CRATE // 200)
for off in range(0, len(cap) - len(a) + 1, step):
    b = cap[off:off + len(a)]
    b = b - b.mean()
    nb = np.linalg.norm(b)
    if nb < 1e-9:
        continue
    c = float(a @ b / nb)
    if c > best:
        best, best_off = c, off
for off in range(max(0, best_off - step), min(len(cap) - len(a) + 1, best_off + step)):
    b = cap[off:off + len(a)]
    b = b - b.mean()
    nb = np.linalg.norm(b)
    if nb < 1e-9:
        continue
    c = float(a @ b / nb)
    if c > best:
        best, best_off = c, off

print("best correlation %.4f at %.2f s into the capture" % (best, best_off / float(CRATE)))

# onsets in the matched window, counted the way a person would: energy rising
# through a threshold after a gap.
win = cap[best_off:best_off + len(a)]
frame = CRATE // 100
env = np.array([np.abs(win[i:i + frame]).mean() for i in range(0, len(win) - frame, frame)])
if len(env):
    thr = 0.25 * env.max()
    above = env > thr
    onsets = int(np.sum(above[1:] & ~above[:-1])) + (1 if len(above) and above[0] else 0)
    print("onsets in the matched window: %d (the clip is 3 a second)" % onsets)
print("VERDICT: %s" % ("our sound is in the capture" if best > 0.5
                       else "NOT found - correlation too low"))
