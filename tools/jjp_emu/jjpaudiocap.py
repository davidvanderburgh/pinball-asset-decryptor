#!/usr/bin/env python3
"""jjpaudiocap.py - what a MUTED JJP rig plays, measured, never heard (PAD-1352).

audio.sh with PAD_AUDIO=0 and JJP_AUDIO_CAPTURE=<path in the jail> points ALSA's
default PCM at the file plugin over the null device: the game stays silent and
everything it plays is written to that path as a WAV stream.  The null device
takes audio as fast as it is given, so a plain file grows hundreds of MB a
minute and its timing is meaningless.  Make the path a FIFO and run this on it
instead: it reads the stream at the stream's own byte rate, which paces the
game's mixer to the wall clock, and writes one line per 100 ms:

    <unix time> <rms> <level at each --tone Hz> ...

(levels: Goertzel magnitude, normalised to 0..1 of full scale).  So a proof run
can say "880 Hz rose when the mode started, 330 Hz while it ran, gone after".

    jjpaudiocap.py --fifo /var/tmp/jjp_run/jjpe/temp/pad_audio.fifo --out cap.txt --tone 330 --tone 880

Root, on the WSL host.  Make the FIFO (mkfifo) before the game starts; every
client that opens the default PCM (the game, a boot script's aplay) is a new
WAV stream on it, so this reopens it at each end.  Stops on SIGTERM.
"""
import argparse
import math
import os
import struct
import sys
import time


def goertzel(samples, rate, freq):
    """Magnitude of `freq` in `samples` (floats, -1..1), 0..1 of a full-scale sine."""
    n = len(samples)
    if not n:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return 2.0 * math.sqrt(max(power, 0.0)) / n


def parse_header(fh):
    """A WAV header off a stream -> (format, channels, rate, bits) or None at EOF."""
    riff = fh.read(12)
    if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
        return None
    fmt = None
    while True:
        hd = fh.read(8)
        if len(hd) < 8:
            return None
        cid, size = hd[:4], struct.unpack("<I", hd[4:])[0]
        if cid == b"fmt ":
            body = fh.read(size)
            tag, ch, rate, _br, _ba, bits = struct.unpack("<HHIIHH", body[:16])
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            return fmt
        else:
            fh.read(size)


def decode(buf, tag, ch, bits):
    """Interleaved frames -> mono floats."""
    if tag == 3 and bits == 32:
        vals = struct.unpack("<%df" % (len(buf) // 4), buf[:len(buf) // 4 * 4])
    elif bits == 16:
        vals = [v / 32768.0 for v in struct.unpack("<%dh" % (len(buf) // 2), buf[:len(buf) // 2 * 2])]
    elif bits == 32:
        vals = [v / 2147483648.0 for v in struct.unpack("<%di" % (len(buf) // 4), buf[:len(buf) // 4 * 4])]
    else:
        return []
    return [sum(vals[i:i + ch]) / ch for i in range(0, len(vals) - ch + 1, ch)]


def run(fifo, out, tones, step=0.1):
    with open(out, "a", buffering=1) as log:
        while True:
            with open(fifo, "rb") as fh:
                fmt = parse_header(fh)
                if not fmt:
                    continue
                tag, ch, rate, bits = fmt
                log.write("# stream %s: format %d, %d ch, %d Hz, %d bit\n" % (time.strftime("%H:%M:%S"), tag, ch, rate, bits))
                chunk = int(rate * step) * ch * bits // 8
                t_next = time.time()
                while True:
                    buf = fh.read(chunk)
                    if not buf:
                        break
                    mono = decode(buf, tag, ch, bits)
                    rms = math.sqrt(sum(x * x for x in mono) / len(mono)) if mono else 0.0
                    lv = " ".join("%.4f" % goertzel(mono, rate, f) for f in tones)
                    log.write("%.2f %.4f %s\n" % (time.time(), rms, lv))
                    t_next += step
                    delay = t_next - time.time()
                    if delay > 0:
                        time.sleep(delay)
                    elif delay < -1:
                        t_next = time.time()      # fell behind (a busy host): keep real time from here


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fifo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tone", type=float, action="append", default=[])
    a = ap.parse_args(argv)
    if not os.path.exists(a.fifo):
        os.mkfifo(a.fifo)
    try:
        run(a.fifo, a.out, a.tone)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
