#!/usr/bin/env python3
"""s3leds.py - a Spike 3 run's lamps and coils, published for the virtual
playfield window (PAD-1090).

On Spike 2 the guest shim decodes the node bus and fills dump/padled
(padled.h). On Spike 3 the node bus already ends in s3bridge.py, in Python,
with every frame unmasked into Spike 2's own `cmd body... ck` - so the bridge
hands each one here and this fills the same block, at padled.h's offsets, for
the same reader (playfield.py). Only what the wire says: a lamp's level from
the lamp builder's frames (leddecode.wide_decode_any, the swelf-generation
grammar Spike 3 speaks - its commands are 0x80..0xbf), a coil's fire count and
drive byte from `40 IDX power...`.

    PadLed(path).frame(node, plain)     one unmasked node frame
"""
import mmap
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "spike2_emu"))
import leddecode  # noqa: E402

# VERSION 6: the `hi` plane is published (a board's channels past its first
# 96). The version-5 drive table between `seen` and `hi` stays zero: a reader
# times a drive from `until` changing, and zero never changes.
MAGIC, VERSION, BYTES = 0x44454C50, 6, 16384
NODES, IDX, COILS = 16, 96, 16
GEN, DECODED, SKIPPED = 8, 12, 16
VAL = 20                                    # val[16][96]
COIL = VAL + NODES * IDX                    # 1556: coil[16][16] fire count
LVL = COIL + NODES * COILS                  # last drive byte
COIL_GEN = LVL + NODES * COILS              # 2068
COIL_DECODED = COIL_GEN + 4
FADE_HEAD = COIL_DECODED + 4                # 2076, fade ring (unused here)
SEEN = FADE_HEAD + 4 + 96 * 12              # 3232: seen[16][96]
WIDE_DECODED = SEEN + NODES * IDX           # 4768
WIDE_SKIPPED = WIDE_DECODED + 4
HI = 7356                                   # hi[16][4 * 96], padled.h v6
HI_BANKS = 4


class PadLed:
    def __init__(self, path):
        self.path = path
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o644)
        os.ftruncate(fd, BYTES)
        self.m = mmap.mmap(fd, BYTES)
        os.close(fd)
        os.chmod(path, 0o644)
        struct.pack_into("<II", self.m, 0, MAGIC, VERSION)
        self.lamps = self.wide = self.wide_bad = self.fires = self.hi = 0

    def _bump(self, off, n=1):
        v = struct.unpack_from("<I", self.m, off)[0]
        struct.pack_into("<I", self.m, off, (v + n) & 0xFFFFFFFF)

    def fire(self, node, idx, power):
        """One coil fire: a `40 IDX power` from the game, or a coil the BOARD
        fired by its rule (s3rules, PAD-1134) - counted alike, so the
        playfield window flashes both."""
        if 0 <= node < NODES and 0 <= idx < COILS:
            o = node * COILS + idx
            self.m[COIL + o] = (self.m[COIL + o] + 1) & 0xFF
            self.m[LVL + o] = power & 0xFF
            self._bump(COIL_DECODED)
            self._bump(COIL_GEN)
            self.fires += 1

    def frame(self, node, plain):
        """One node frame, unmasked: `cmd body... ck`."""
        if not plain or not 0 <= node < NODES:
            return
        cmd = plain[0]
        if cmd == 0x40 and len(plain) >= 4:
            self.fire(node, plain[1], plain[2])
            return
        if cmd & 0xC0 != 0x80:
            return
        # leddecode reads Spike 2's [addr][len][cmd][body][ck][pad]
        b = bytes([0x80 | node, len(plain)]) + bytes(plain) + b"\x00"
        try:
            d = leddecode.wide_decode_any(b)
        except Exception:                                  # noqa: BLE001
            d = None
        if not d:
            self._bump(WIDE_SKIPPED)
            self.wide_bad += 1
            return
        bank, idxs, vals = d
        self._bump(WIDE_DECODED)
        self.wide += 1
        if bank:
            # PAD-1152: a board's channels past its first 96 - the cabinet's
            # light strips (node 2: 288 or 432 channels), the speaker panel
            # (120), the topper (276/285) - arrive in banks of 96 and were
            # dropped here, so the window's cabinet views lit only their first
            # 96. padled v6's `hi` plane, as Spike 2's shim fills it (led_hi):
            # levels only, so `seen`, `decoded` and `gen` read as before.
            if 1 <= bank <= HI_BANKS:
                base = HI + node * HI_BANKS * IDX + (bank - 1) * IDX
                for i, v in zip(idxs, vals):
                    if 0 <= i < IDX:
                        self.m[base + i] = v & 0xFF
                self.hi += 1
            return
        n = 0
        for i, v in zip(idxs, vals):
            if 0 <= i < IDX:
                self.m[VAL + node * IDX + i] = v & 0xFF
                self.m[SEEN + node * IDX + i] = 1
                n += 1
        if n:
            self._bump(DECODED, n)
            self._bump(GEN)
            self.lamps += n

    def close(self):
        try:
            self.m.close()
            os.unlink(self.path)      # gone = the run ended (playfield.py)
        except OSError:
            pass
