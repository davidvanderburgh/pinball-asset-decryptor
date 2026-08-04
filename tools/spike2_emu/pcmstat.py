#!/usr/bin/env python3
"""pcmstat.py <file.raw> [rate] [channels] - is the captured PCM actually audio?

PAD_AUDIO_OUT writes raw interleaved s16le straight out of snd_pcm_writei. A
non-zero file size proves only that the call happened; this says whether the
samples carry anything, and where in the timeline they do, so "the game writes
no PCM" and "the game writes SILENT PCM" cannot be confused again.
"""
import array
import sys

path = sys.argv[1]
rate = int(sys.argv[2]) if len(sys.argv) > 2 else 44100
ch = int(sys.argv[3]) if len(sys.argv) > 3 else 2

a = array.array('h')
with open(path, 'rb') as f:
    data = f.read()
a.frombytes(data[:len(data) // 2 * 2])
if sys.byteorder == 'big':
    a.byteswap()

frames = len(a) // ch
print('%s: %d bytes, %d frames, %.2f s at %d Hz x %d ch'
      % (path, len(data), frames, frames / float(rate), rate, ch))

nz = sum(1 for x in a if x)
peak = max((abs(x) for x in a), default=0)
rms = (sum(float(x) * x for x in a) / len(a)) ** 0.5 if a else 0.0
print('non-zero samples %d / %d (%.2f%%)   peak %d   rms %.1f'
      % (nz, len(a), 100.0 * nz / len(a) if a else 0, peak, rms))

# per-second peak, so a burst in the middle of silence is visible
print('per-second peak:')
line = []
for s in range(0, frames // rate + 1):
    lo, hi = s * rate * ch, min((s + 1) * rate * ch, len(a))
    if lo >= hi:
        break
    p = max((abs(x) for x in a[lo:hi]), default=0)
    line.append('%3ds:%-6d' % (s, p))
    if len(line) == 8:
        print('  ' + ' '.join(line))
        line = []
if line:
    print('  ' + ' '.join(line))
