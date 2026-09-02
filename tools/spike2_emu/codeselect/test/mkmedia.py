#!/usr/bin/env python3
"""mkmedia.py make DIR        - write the test media set into DIR
   mkmedia.py pix PPM X Y [RRGGBB [TOL]]  - print (or assert) one pixel of a P6 PPM
   mkmedia.py band PPM X0 Y0 X1 Y1 RRGGBB [TOL]  - assert the rectangle (inclusive)
                              holds at least one pixel within TOL of RRGGBB (text
                              in a known colour is somewhere on its baseline)

The media set (no PIL needed: a zlib PNG writer, a hand-rolled GIF89a
encoder and the wave module):
    art0.png      300x169 solid C03040          (card 0's still)
    art1.png      400x225 solid 2060C0          (card 1's still)
    anim1.gif     4 frames 200x112, 100 ms each: FF0000 00C000 0000FF FFFF00
    move.wav      0.2 s 1 kHz stereo            (sound_move)
    confirm.wav   1.0 s 440 Hz stereo           (the menu-wide sound_confirm)
    confirm1.wav  2.5 s 660 Hz stereo           (card 1's OWN confirm sound - long
                                                 enough that its 2.5 s hold cannot
                                                 be confused with confirm.wav's 1.0 s)
    music0.wav    0.5 s 220 Hz mono             (card 0's loop; mono -> duplicated)
    bad.wav       0.1 s 22050 Hz                (refused with a log line)
"""
import math
import os
import struct
import sys
import wave
import zlib

ART0 = (0xC0, 0x30, 0x40)
ART1 = (0x20, 0x60, 0xC0)
ANIM1 = [(0xFF, 0x00, 0x00), (0x00, 0xC0, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0xFF, 0x00)]


def png_solid(path, w, h, rgb):
    row = b"\x00" + bytes(rgb) * w
    raw = row * h

    def chunk(tag, body):
        c = tag + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def gif_solid_frames(path, w, h, colors, delay_cs=10):
    """GIF89a, one solid frame per colour: a 128-entry global palette (min
    code size 7 => 8-bit LZW codes, so the stream is plain bytes) with a
    CLEAR every 125 literals so the code width never grows."""
    pal = list(colors) + [(0, 0, 0)] * (128 - len(colors))
    out = bytearray(b"GIF89a" + struct.pack("<HHBBB", w, h, 0xF6, 0, 0))
    for r, g, b in pal:
        out += bytes((r, g, b))
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for k in range(len(colors)):
        out += b"\x21\xf9\x04\x04" + struct.pack("<H", delay_cs) + b"\x00\x00"   # GCE: keep, delay
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, w, h, 0) + b"\x07"
        codes = bytearray([128])
        n = 0
        for _ in range(w * h):
            if n == 125:
                codes.append(128)
                n = 0
            codes.append(k)
            n += 1
        codes.append(129)
        for i in range(0, len(codes), 255):
            part = codes[i:i + 255]
            out += bytes([len(part)]) + part
        out += b"\x00"
    out += b"\x3b"
    with open(path, "wb") as f:
        f.write(bytes(out))


def wav_tone(path, seconds, hz, channels=2, rate=44100, amp=0.5):
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * hz * i / rate))
        frames += struct.pack("<h", v) * channels
    with wave.open(path, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(bytes(frames))


def make(d):
    os.makedirs(d, exist_ok=True)
    png_solid(os.path.join(d, "art0.png"), 300, 169, ART0)
    png_solid(os.path.join(d, "art1.png"), 400, 225, ART1)
    gif_solid_frames(os.path.join(d, "anim1.gif"), 200, 112, ANIM1)
    wav_tone(os.path.join(d, "move.wav"), 0.2, 1000)
    wav_tone(os.path.join(d, "confirm.wav"), 1.0, 440)
    wav_tone(os.path.join(d, "confirm1.wav"), 2.5, 660)
    wav_tone(os.path.join(d, "music0.wav"), 0.5, 220, channels=1)
    wav_tone(os.path.join(d, "bad.wav"), 0.1, 440, rate=22050)


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    parts = []
    pos = 0
    while len(parts) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        parts.append(data[start:pos])
    pos += 1
    w, h = int(parts[1]), int(parts[2])
    return w, h, data[pos:pos + w * h * 3]


def pix(args):
    path, x, y = args[0], int(args[1]), int(args[2])
    w, h, px = read_ppm(path)
    if not (0 <= x < w and 0 <= y < h):
        raise SystemExit("mkmedia pix: (%d,%d) outside %dx%d" % (x, y, w, h))
    o = (y * w + x) * 3
    r, g, b = px[o], px[o + 1], px[o + 2]
    got = "%02X%02X%02X" % (r, g, b)
    if len(args) > 3:
        want = args[3].upper()
        tol = int(args[4]) if len(args) > 4 else 2
        wr, wg, wb = int(want[0:2], 16), int(want[2:4], 16), int(want[4:6], 16)
        if max(abs(r - wr), abs(g - wg), abs(b - wb)) > tol:
            raise SystemExit("mkmedia pix: %s (%d,%d) is %s, expected %s" % (path, x, y, got, want))
        print("mkmedia pix: %s (%d,%d) = %s ok" % (os.path.basename(path), x, y, got))
    else:
        print(got)


def band(args):
    path = args[0]
    x0, y0, x1, y1 = (int(a) for a in args[1:5])
    want = args[5].upper()
    tol = int(args[6]) if len(args) > 6 else 8
    wr, wg, wb = int(want[0:2], 16), int(want[2:4], 16), int(want[4:6], 16)
    w, h, px = read_ppm(path)
    n = 0
    for y in range(max(0, y0), min(h - 1, y1) + 1):
        row = y * w * 3
        for x in range(max(0, x0), min(w - 1, x1) + 1):
            o = row + x * 3
            if max(abs(px[o] - wr), abs(px[o + 1] - wg), abs(px[o + 2] - wb)) <= tol:
                n += 1
    where = "[%d,%d]..[%d,%d]" % (x0, y0, x1, y1)
    if n == 0:
        raise SystemExit("mkmedia band: %s has no %s pixel in %s" % (path, want, where))
    print("mkmedia band: %s %s holds %d px of %s ok" % (os.path.basename(path), where, n, want))


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "make":
        make(sys.argv[2])
    elif len(sys.argv) >= 5 and sys.argv[1] == "pix":
        pix(sys.argv[2:])
    elif len(sys.argv) >= 8 and sys.argv[1] == "band":
        band(sys.argv[2:])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
