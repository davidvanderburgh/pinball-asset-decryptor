"""turncheck.py <job out dir> - the tones after each fire of turnjob.sh against the files the runtime says it played
(PAD-1555, TURN_PROVEN's evidence). $DUMP/audio.raw is s16le stereo at 44.1 kHz (it grows 176,400 bytes a second; read
at 48 kHz the tones come out x1.088); each mark in marks.txt is cut for 1.6 s and the strongest of 500 / 1000 / 2000 Hz
taken (the slot's own sound replaced by 500 Hz, its files 2 and 3 in turn 1000 / 2000 Hz). The runtime's `sounds in
turn: ... - file N of 3` lines, the last one per mark, give the order it played. Exit 0 when every mark's tone is its
file's."""
import os
import re
import sys

import numpy as np

RATE, FRAME = 44100, 4
TONE = {1: 500, 2: 1000, 3: 2000}


def main(d):
    raw = np.fromfile(os.path.join(d, 'audio.raw'), dtype='<i2').astype(np.float32) / 32768.0
    left = raw[0::2]
    marks = [int(x) // FRAME for x in open(os.path.join(d, 'marks.txt')).read().split()]
    log = open(os.path.join(d, 'mode.log'), encoding='utf-8', errors='replace').read()
    files = [int(x) for x in re.findall(r'sounds in turn: \w+ (?:played|looked up) \(\d+ time\(s\)\) - file (\d+) of 3',
                                        log)][-len(marks):]
    ok = len(files) == len(marks)
    for k, m in enumerate(marks):
        seg = left[m:m + int(1.6 * RATE)]
        n = np.arange(len(seg))
        mags = {hz: float(np.abs(np.dot(seg, np.exp(-2j * np.pi * hz * n / RATE)))) / max(len(seg), 1)
                for hz in (500, 1000, 2000)}
        best = max(mags, key=mags.get)
        want = TONE.get(files[k]) if k < len(files) else None
        good = best == want and mags[best] > 0.005
        ok = ok and good
        print("fire %d: file %s -> heard %d Hz (%s) %s" % (k + 1, files[k] if k < len(files) else "?", best,
                                                        " ".join("%d %.4f" % kv for kv in sorted(mags.items())),
                                                        "ok" if good else "WRONG"))
    print("pass" if ok else "fail")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
