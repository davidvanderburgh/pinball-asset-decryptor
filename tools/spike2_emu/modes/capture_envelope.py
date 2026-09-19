#!/usr/bin/env python3
"""Did the game READ our bytes and decode them wrong, or never read them at all?

The probe proved request 1295 reached the worker and its sid list is [1998], the node
patched to our appended record. So the binding was exercised. The prediction, if the
codec parameters come from the per-sid DESCRIPTOR rather than the tree node: the game
read our body with sid 1998's parameters (scale 1 against our record's scale 13) and
emitted NOISE - loud, ~4 s, at the moment of the callout, and uncorrelated with the
clip. If instead nothing was read, that stretch is ordinary game audio.

Those two look completely different in an envelope, so this measures rather than
argues. The callout fired ~4-5 s before the capture window ends.

  tail130.py <capture.raw> <source.wav> [rate] [chan] [tail_seconds]
"""
import sys
import wave

import numpy as np

CAP, SRC = sys.argv[1], sys.argv[2]
RATE = int(sys.argv[3]) if len(sys.argv) > 3 else 48000
CH = int(sys.argv[4]) if len(sys.argv) > 4 else 2
TAIL = float(sys.argv[5]) if len(sys.argv) > 5 else 12.0

cap = np.frombuffer(open(CAP, "rb").read(), dtype="<i2").astype(np.float64)
if CH > 1:
    cap = cap[:len(cap) // CH * CH].reshape(-1, CH).mean(axis=1)
total = len(cap) / float(RATE)
tail = cap[-int(TAIL * RATE):]
print("capture %.2f s total; looking at the last %.2f s" % (total, len(tail) / float(RATE)))

# envelope, 100 ms frames
fr = RATE // 10
env = np.array([np.abs(tail[i:i + fr]).mean() for i in range(0, len(tail) - fr, fr)])
print("\nenvelope of the tail, 100 ms per column (rms of |x|):")
for s in range(0, len(env), 10):
    row = env[s:s + 10]
    print("  t-%4.1fs  %s" % (TAIL - s / 10.0,
                              " ".join("%6.0f" % v for v in row)))

print("\npeak in tail %.0f, mean %.0f" % (tail.max() if len(tail) else 0,
                                          np.abs(tail).mean() if len(tail) else 0))

with wave.open(SRC, "rb") as w:
    srate, sch = w.getframerate(), w.getnchannels()
    src = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
if sch > 1:
    src = src[:len(src) // sch * sch].reshape(-1, sch).mean(axis=1)
n_out = int(len(src) * RATE / float(srate))
src_r = np.interp(np.linspace(0, len(src) - 1, n_out), np.arange(len(src)), src)

# best correlation inside the tail only
a = src_r - src_r.mean()
a /= (np.linalg.norm(a) or 1.0)
best, off = -2.0, -1
if len(tail) >= len(a):
    step = max(1, RATE // 400)
    for o in range(0, len(tail) - len(a) + 1, step):
        b = tail[o:o + len(a)]
        b = b - b.mean()
        nb = np.linalg.norm(b)
        if nb < 1e-9:
            continue
        c = float(a @ b / nb)
        if c > best:
            best, off = c, o
print("best correlation IN THE TAIL: %.4f at t-%.2fs"
      % (best, TAIL - off / float(RATE)))

# spectral flatness: noise is flat, a three-tone figure is not
def flatness(x):
    x = np.asarray(x, float)
    if len(x) < 256 or x.std() < 1e-6:
        return float("nan")
    n = 1 << int(np.floor(np.log2(len(x))))
    X = np.abs(np.fft.rfft((x[:n] - x[:n].mean()) * np.hanning(n)))[1:]
    X = np.maximum(X, 1e-9)
    return float(np.exp(np.mean(np.log(X))) / np.mean(X))

print("\nspectral flatness (noise ~0.8+, tonal < 0.45):")
print("  our clip          %.3f" % flatness(src_r))
for k in range(int(TAIL) - 4, int(TAIL)):
    seg = tail[k * RATE:(k + 1) * RATE]
    if len(seg) > 256:
        print("  tail second t-%-4.1fs %.3f" % (TAIL - k, flatness(seg)))
