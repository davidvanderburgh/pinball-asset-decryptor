#!/usr/bin/env python3
"""
image_sound.py - decode a Stern "Spike 3" image.bin sound container to per-sound WAVs.

Pure Python, stdlib only (struct + wave). NO keys and NO machine required: the
sound container inside an already-extracted image.bin is plaintext, so once the
games partition has been decrypted and image.bin pulled out (see luks_otp.py and
the SD/.spk extract path), the audio drops straight out.

------------------------------------------------------------------------------
THE CONTAINER (identical master-directory geometry to Spike 2)
------------------------------------------------------------------------------
image.bin is a flat asset container. Its 128-byte header carries, little-endian:

    hdr[0x40] : u64  md_off   - byte offset of the sound master directory
    hdr[0x60] : u32  count    - number of sound records

and the whole file satisfies the Spike 2/3 invariant

    filesize == md_off + align16(24 * count) + 8

(the trailing 8 bytes hold a seed word that the directory does NOT need - the
directory is plaintext here, unlike Spike 2 where it was AES-wrapped).

The directory is `count` records of 24 bytes each at md_off, little-endian:

    off  size  field
    0x00  u64  offset      byte offset of this sound's PCM body in image.bin
    0x08  u32  flags_lo    low 16 bits reserved; bit 0x0002_0000 = STEREO,
                           i.e. channel count lives in the HIGH half (>>16)
    0x0c  u32  param       per-record value (crc/id); not needed to decode
    0x10  u32  frames      sample frames (per channel)
    0x14  u32  param2      per-record value; not needed to decode

The body is raw interleaved signed-16-bit little-endian PCM:

    channels   = 2 if (flags_lo >> 16) & 0x0002 else 1
    body_bytes = frames * channels * 2
    sample rate = 44100 Hz   (the game's ALSA mixer runs 44100/S16_LE/stereo and
                              feeds these sources without resampling; both flag
                              groups measure the same spectral centroid at 44100)

So each record decodes to a WAV with no codec and no decryption. The bodies tile
the file contiguously from the first record's offset up to md_off.

------------------------------------------------------------------------------
Usage
------------------------------------------------------------------------------
    python image_sound.py info    <image.bin>
    python image_sound.py list    <image.bin> [--limit N]
    python image_sound.py extract <image.bin> --out <dir> [--limit N]
    python image_sound.py selftest

`extract` writes <dir>/idxNNNN.wav (zero-padded to the directory width).
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import wave
from dataclasses import dataclass

HEADER_SIZE = 0x80
MD_OFF_FIELD = 0x40          # u64
COUNT_FIELD = 0x60           # u32
RECORD_SIZE = 24
STEREO_FLAG = 0x0002         # tested in the high half of flags_lo (<< 16)
SAMPLE_RATE = 44100
SAMPLE_WIDTH = 2             # bytes (signed 16-bit)


def _align16(n: int) -> int:
    return (n + 15) & ~15


@dataclass
class SoundRecord:
    index: int
    offset: int
    channels: int
    frames: int
    flags_lo: int
    param: int
    param2: int

    @property
    def body_bytes(self) -> int:
        return self.frames * self.channels * SAMPLE_WIDTH

    @property
    def duration_s(self) -> float:
        return self.frames / SAMPLE_RATE


class ImageSound:
    """Parsed view of an image.bin sound container."""

    def __init__(self, path: str):
        self.path = path
        self.filesize = os.path.getsize(path)
        with open(path, "rb") as fh:
            hdr = fh.read(HEADER_SIZE)
            if len(hdr) < HEADER_SIZE:
                raise ValueError("file too small to be an image.bin container")
            self.md_off = struct.unpack_from("<Q", hdr, MD_OFF_FIELD)[0]
            self.count = struct.unpack_from("<I", hdr, COUNT_FIELD)[0]
            self._check_invariant()
            fh.seek(self.md_off)
            dir_bytes = fh.read(RECORD_SIZE * self.count)
        if len(dir_bytes) < RECORD_SIZE * self.count:
            raise ValueError("directory truncated: wanted %d bytes, got %d"
                             % (RECORD_SIZE * self.count, len(dir_bytes)))
        self.records = self._parse_directory(dir_bytes)

    def _check_invariant(self) -> None:
        expect = self.md_off + _align16(RECORD_SIZE * self.count) + 8
        if expect != self.filesize:
            raise ValueError(
                "not a Spike 3 sound container: filesize %d != md_off %d + "
                "align16(24*%d) + 8 = %d"
                % (self.filesize, self.md_off, self.count, expect))

    def _parse_directory(self, dir_bytes: bytes) -> list:
        recs = []
        for i in range(self.count):
            off, flags_lo, param, frames, param2 = struct.unpack_from(
                "<QIIII", dir_bytes, i * RECORD_SIZE)
            channels = 2 if (flags_lo >> 16) & STEREO_FLAG else 1
            recs.append(SoundRecord(
                index=i, offset=off, channels=channels, frames=frames,
                flags_lo=flags_lo, param=param, param2=param2))
        return recs

    def validate(self) -> None:
        """Raise if any record points outside the body region."""
        for r in self.records:
            if r.offset < HEADER_SIZE or r.offset >= self.md_off:
                raise ValueError("record %d offset 0x%x outside body region"
                                 % (r.index, r.offset))
            end = r.offset + r.body_bytes
            if end > self.md_off:
                raise ValueError("record %d body [0x%x,0x%x) overruns directory"
                                 % (r.index, r.offset, end))

    def read_body(self, rec: SoundRecord) -> bytes:
        with open(self.path, "rb") as fh:
            fh.seek(rec.offset)
            data = fh.read(rec.body_bytes)
        if len(data) != rec.body_bytes:
            raise ValueError("record %d: short read (%d of %d bytes)"
                             % (rec.index, len(data), rec.body_bytes))
        return data

    def write_wav(self, rec: SoundRecord, path: str, rate: int = SAMPLE_RATE) -> None:
        pcm = self.read_body(rec)
        with wave.open(path, "wb") as w:
            w.setnchannels(rec.channels)
            w.setsampwidth(SAMPLE_WIDTH)
            w.setframerate(rate)
            w.writeframes(pcm)

    @property
    def name_width(self) -> int:
        return max(4, len(str(self.count - 1)))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _cmd_info(args) -> int:
    img = ImageSound(args.image)
    mono = sum(1 for r in img.records if r.channels == 1)
    stereo = img.count - mono
    total_s = sum(r.duration_s for r in img.records)
    print("image.bin     : %s" % img.path)
    print("file size     : %d bytes" % img.filesize)
    print("directory off : 0x%x" % img.md_off)
    print("sounds        : %d  (mono %d, stereo %d)" % (img.count, mono, stereo))
    print("sample rate   : %d Hz, signed 16-bit PCM" % SAMPLE_RATE)
    print("total audio   : %.1f s" % total_s)
    img.validate()
    print("integrity     : OK (invariant holds, all bodies in range)")
    return 0


def _cmd_list(args) -> int:
    img = ImageSound(args.image)
    n = img.count if args.limit is None else min(args.limit, img.count)
    for r in img.records[:n]:
        print("idx%0*d  off=0x%09x  ch=%d  frames=%-7d  %.3fs"
              % (img.name_width, r.index, r.offset, r.channels, r.frames, r.duration_s))
    return 0


def _cmd_extract(args) -> int:
    img = ImageSound(args.image)
    img.validate()
    os.makedirs(args.out, exist_ok=True)
    n = img.count if args.limit is None else min(args.limit, img.count)
    w = img.name_width
    written = 0
    for r in img.records[:n]:
        out = os.path.join(args.out, "idx%0*d.wav" % (w, r.index))
        img.write_wav(r, out, rate=args.rate)
        written += 1
    print("wrote %d WAV(s) to %s" % (written, args.out))
    return 0


def _synth_container(path: str) -> None:
    """Build a tiny valid container for selftest: two sounds (mono + stereo)."""
    import math
    # mono: 100 frames, stereo: 50 frames
    mono = b"".join(struct.pack("<h", int(3000 * math.sin(i / 4.0)))
                    for i in range(100))
    stereo = b"".join(struct.pack("<hh", int(2000 * math.sin(i / 3.0)),
                                  int(-2000 * math.sin(i / 3.0)))
                      for i in range(50))
    bodies = mono + stereo
    md_off = HEADER_SIZE + len(bodies)
    count = 2
    hdr = bytearray(HEADER_SIZE)
    struct.pack_into("<Q", hdr, MD_OFF_FIELD, md_off)
    struct.pack_into("<I", hdr, COUNT_FIELD, count)
    directory = b"".join([
        struct.pack("<QIIII", HEADER_SIZE, 0, 0, 100, 0),                 # mono
        struct.pack("<QIIII", HEADER_SIZE + len(mono),
                    STEREO_FLAG << 16, 0, 50, 0),                          # stereo
    ])
    pad = _align16(len(directory)) - len(directory)
    seed = struct.pack("<Q", 0x0123456789abcdef)
    with open(path, "wb") as fh:
        fh.write(bytes(hdr))
        fh.write(bodies)
        fh.write(directory)
        fh.write(b"\x00" * pad)
        fh.write(seed)


def _cmd_selftest(args) -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="image_sound_selftest_")
    cpath = os.path.join(tmp, "image.bin")
    _synth_container(cpath)
    img = ImageSound(cpath)
    assert img.count == 2, img.count
    img.validate()
    assert img.records[0].channels == 1 and img.records[0].frames == 100
    assert img.records[1].channels == 2 and img.records[1].frames == 50
    outdir = os.path.join(tmp, "out")
    os.makedirs(outdir)
    for r in img.records:
        p = os.path.join(outdir, "idx%04d.wav" % r.index)
        img.write_wav(r, p)
        with wave.open(p, "rb") as w:
            assert w.getframerate() == SAMPLE_RATE
            assert w.getsampwidth() == SAMPLE_WIDTH
            assert w.getnchannels() == r.channels
            assert w.getnframes() == r.frames
    print("selftest OK (parse, invariant, validate, mono+stereo WAV round-trip)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Decode a Spike 3 image.bin to WAVs")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("info", help="print container summary")
    pi.add_argument("image")
    pi.set_defaults(func=_cmd_info)

    pl = sub.add_parser("list", help="list sound records")
    pl.add_argument("image")
    pl.add_argument("--limit", type=int, default=None)
    pl.set_defaults(func=_cmd_list)

    pe = sub.add_parser("extract", help="write per-sound WAVs")
    pe.add_argument("image")
    pe.add_argument("--out", required=True)
    pe.add_argument("--limit", type=int, default=None)
    pe.add_argument("--rate", type=int, default=SAMPLE_RATE)
    pe.set_defaults(func=_cmd_extract)

    ps = sub.add_parser("selftest", help="run a self-contained round-trip test")
    ps.set_defaults(func=_cmd_selftest)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
