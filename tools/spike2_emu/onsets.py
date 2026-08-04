#!/usr/bin/env python3
"""onsets.py <file.raw> [rate] [channels] - COUNT THE CLICKS in captured PCM.

    wsl -e bash -c 'python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/onsets.py \\
        /home/david/spike2root/dump/audio.raw'

PAD_AUDIO_OUT writes raw interleaved s16le straight out of snd_pcm_writei.
pcmstat.py already answers "is this audio at all"; this answers the different
question "how many separate sounds are in it, and when", which is what you need
when the complaint is that something is firing repeatedly.

Method: 5 ms RMS envelope, then an onset wherever the envelope crosses UP
through a threshold derived from the recording's own loud level, with a refractory
gap so one sound with a bumpy attack is not counted several times. Deliberately
crude - the question is "one press or a hundred", not transcription.

The refractory gap matters more than the threshold. Without it a single 200 ms
menu tick with tremolo counts as a dozen onsets, which would "confirm" exactly
the thing being investigated. Default 80 ms; pass it if the sound being counted
is faster than that.
"""
import array
import sys

path = sys.argv[1]
rate = int(sys.argv[2]) if len(sys.argv) > 2 else 44100
ch = int(sys.argv[3]) if len(sys.argv) > 3 else 2
refractory_ms = int(sys.argv[4]) if len(sys.argv) > 4 else 80

a = array.array('h')
with open(path, 'rb') as f:
    data = f.read()
a.frombytes(data[:len(data) // 2 * 2])
if sys.byteorder == 'big':
    a.byteswap()

frames = len(a) // ch
secs = frames / float(rate)
print("%s: %d frames, %.1f s, %d ch @ %d Hz" % (path, frames, secs, ch, rate))
if not frames:
    sys.exit(0)

win = max(1, rate // 200)                      # 5 ms
env = []
for start in range(0, frames - win, win):
    acc = 0
    for i in range(start * ch, (start + win) * ch, ch):
        v = a[i]
        acc += v * v
    env.append((acc / win) ** 0.5)

peak = max(env)
if peak <= 0:
    print("silent")
    sys.exit(0)

# Threshold from the recording's own dynamics: a click has to be well above the
# ambient bed, not merely non-zero. 25% of peak is low enough to catch a quiet
# tick over music and high enough to ignore the noise floor.
thr = peak * 0.25
gap_wins = max(1, (refractory_ms * rate // 1000) // win)

onsets = []
last = -10 ** 9
above = False
for i, v in enumerate(env):
    if v >= thr and not above:
        above = True
        if i - last >= gap_wins:
            onsets.append(i * win / float(rate))
            last = i
    elif v < thr * 0.6:
        above = False

print("peak rms %.0f, threshold %.0f, refractory %d ms" % (peak, thr, refractory_ms))
print("ONSETS: %d" % len(onsets))
if onsets:
    print("first 40 (s): " + " ".join("%.2f" % t for t in onsets[:40]))
    if len(onsets) > 1:
        gaps = [onsets[i + 1] - onsets[i] for i in range(len(onsets) - 1)]
        gaps.sort()
        print("median gap %.3f s, min %.3f s, max %.3f s"
              % (gaps[len(gaps) // 2], gaps[0], gaps[-1]))
    # Where they bunch up, one line per second of the recording.
    per_sec = {}
    for t in onsets:
        per_sec[int(t)] = per_sec.get(int(t), 0) + 1
    busy = sorted(per_sec.items(), key=lambda kv: -kv[1])[:10]
    print("busiest seconds (second: onsets): "
          + " ".join("%d:%d" % (s, n) for s, n in busy))
