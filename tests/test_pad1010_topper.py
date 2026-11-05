"""Topper-gated features without the topper (PAD-1010): plugins.stern.topper.

The synthetic program below carries the shape the module reads - a
``device_usable(index)`` accessor, the ``get_board`` tail it reaches (so the
device table can be found), a device table whose record names one device
"Topper", and two thin ``device_usable(idx)`` wrappers (one for the topper, one
for a playfield board).  Only the topper wrapper must be rewritten.  The real
builds run where the card library is (David's PC); the emulator proof that the
patch unlocks Venom's Ghost Rider host is in the ticket.
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import topper as T

TEXT_VA, TEXT_OFF, TEXT_SIZE = 0x8000, 0x1000, 0x1000
DATA_VA, DATA_OFF = 0x100000, 0x2000

DEVICE_USABLE, BOARD_CHECK, GET_BOARD = 0x8000, 0x8080, 0x80C0
WRAP_TOPPER, WRAP_PLAYFIELD = 0x8100, 0x8120
COUNT_VAR, TBLPTR_VAR = DATA_VA + 0x00, DATA_VA + 0x10
TABLE = DATA_VA + 0x100
TOPPER_IDX, PLAYFIELD_IDX = 3, 1


def _movw(rd, va):
    v = va & 0xFFFF
    return 0xE3000000 | (v >> 12) << 16 | rd << 12 | (v & 0xFFF)


def _movt(rd, va):
    v = va >> 16
    return 0xE3400000 | (v >> 12) << 16 | rd << 12 | (v & 0xFFF)


def _b(at, to, link=False):
    return (0xE << 28) | ((0xB if link else 0xA) << 24) | (((to - (at + 8)) >> 2) & 0xFFFFFF)


class _Prog:
    def __init__(self):
        self.text = bytearray(b"\x00\x00\xa0\xe1" * (TEXT_SIZE // 4))     # mov r0, r0
        self.data = bytearray(0x400)

    def put(self, va, *words):
        for k, w in enumerate(words):
            struct.pack_into("<I", self.text, va - TEXT_VA + 4 * k, w)

    def d32(self, va, val):
        struct.pack_into("<I", self.data, va - DATA_VA, val)

    def name(self, rec_idx, name_va, text):
        """Record *rec_idx*'s name cell -> *name_va* -> *text*."""
        cell = TABLE + 0x200 + rec_idx * 8
        self.d32(TABLE + 16 * rec_idx + 8, cell)        # record+8 = name cell ptr
        self.d32(cell, name_va)                         # cell[0] = English string ptr
        self.data[name_va - DATA_VA:name_va - DATA_VA + len(text) + 1] = text.encode() + b"\0"

    def elf(self):
        hdr = bytearray(0x34)
        hdr[:4] = b"\x7fELF"
        struct.pack_into("<I", hdr, 0x1C, 0x34)
        struct.pack_into("<HH", hdr, 0x2A, 32, 2)
        ph = struct.pack("<8I", 1, TEXT_OFF, TEXT_VA, TEXT_VA, TEXT_SIZE, TEXT_SIZE, 5, 0x1000)
        ph += struct.pack("<8I", 1, DATA_OFF, DATA_VA, DATA_VA, len(self.data), len(self.data), 6, 0x1000)
        out = bytearray(DATA_OFF + len(self.data))
        out[:0x34] = hdr
        out[0x34:0x34 + len(ph)] = ph
        out[TEXT_OFF:TEXT_OFF + TEXT_SIZE] = self.text
        out[DATA_OFF:] = self.data
        return bytes(out)


def _prog():
    p = _Prog()
    # device_usable(index): shape the finder matches, ending in b BOARD_CHECK
    p.put(DEVICE_USABLE,
          0xE2502000,                       # subs r2, r0, #0
          (_b(DEVICE_USABLE + 4, DEVICE_USABLE + 0x1C) & 0x0FFFFFFF) | 0x0A000000,   # beq out-of-range
          _movw(3, COUNT_VAR), _movt(3, COUNT_VAR),
          0xE5933000,                       # ldr r3, [r3]
          0xE1520003,                       # cmp r2, r3
          _b(DEVICE_USABLE + 0x18, BOARD_CHECK),         # blo check  (cond overwritten below)
          0xE3A00000,                       # mov r0, #0
          0xE12FFF1E,                       # bx lr
          _b(DEVICE_USABLE + 0x24, BOARD_CHECK))         # b BOARD_CHECK
    # make the blo at +0x18 carry cond LO
    p.put(DEVICE_USABLE + 0x18, (_b(DEVICE_USABLE + 0x18, BOARD_CHECK) & 0x0FFFFFFF) | 0x3A000000)
    # BOARD_CHECK: bl GET_BOARD within reach
    p.put(BOARD_CHECK, 0xE92D4010, _b(BOARD_CHECK + 4, GET_BOARD, link=True), 0xE8BD8010)
    # GET_BOARD tail: movw/movt table ptr; ldr r3,[r3]; add r0,r3,r0,lsl#4; bx lr
    p.put(GET_BOARD, _movw(3, TBLPTR_VAR), _movt(3, TBLPTR_VAR), 0xE5933000, 0xE0830200, 0xE12FFF1E)
    # wrappers: mov r0,#idx; mov r1,#0; b DEVICE_USABLE
    p.put(WRAP_TOPPER, 0xE3A00000 | TOPPER_IDX, 0xE3A01000, _b(WRAP_TOPPER + 8, DEVICE_USABLE))
    p.put(WRAP_PLAYFIELD, 0xE3A00000 | PLAYFIELD_IDX, 0xE3A01000, _b(WRAP_PLAYFIELD + 8, DEVICE_USABLE))
    # data: count, table pointer, device names, node bytes
    p.d32(COUNT_VAR, 8)
    p.d32(TBLPTR_VAR, TABLE)
    p.name(TOPPER_IDX, DATA_VA + 0x340, "Topper")
    p.name(PLAYFIELD_IDX, DATA_VA + 0x350, "UPPER PLAYFIELD")
    p.data[TABLE + 16 * TOPPER_IDX + 0xe - DATA_VA] = 12          # topper node
    p.data[TABLE + 16 * PLAYFIELD_IDX + 0xe - DATA_VA] = 9
    return p.elf()


def _word_at(elf, va):
    return struct.unpack_from("<I", elf, TEXT_OFF + va - TEXT_VA)[0]


def test_finds_and_patches_only_the_topper_wrapper():
    elf = _prog()
    p = T.plan(elf)
    assert p is not None
    assert {s[0] for s in p["sites"]} == {WRAP_TOPPER, WRAP_TOPPER + 4}
    assert p["devices"] == ["Topper"]
    out = T.patched_bytes(elf, p)
    assert len(out) == len(elf)
    assert _word_at(out, WRAP_TOPPER) == 0xE3A00001          # mov r0, #1
    assert _word_at(out, WRAP_TOPPER + 4) == 0xE12FFF1E      # bx lr
    # the playfield wrapper is untouched
    assert _word_at(out, WRAP_PLAYFIELD) == (0xE3A00000 | PLAYFIELD_IDX)
    # idempotent: the rewritten wrapper is no longer the gate shape
    assert T.plan(out) is None


def test_not_an_elf():
    assert T.plan(b"nope") is None


def test_no_gate_when_no_device_usable():
    p = _Prog()
    p.put(WRAP_TOPPER, 0xE3A00003, 0xE3A01000, _b(WRAP_TOPPER + 8, DEVICE_USABLE))
    assert T.plan(p.elf()) is None


def test_patch_rejects_moved_site():
    elf = _prog()
    p = T.plan(elf)
    bad = bytearray(elf)
    struct.pack_into("<I", bad, TEXT_OFF + WRAP_TOPPER - TEXT_VA, 0xE3A00005)   # different word
    with pytest.raises(ValueError):
        T.patched_bytes(bytes(bad), p)


# ---- real builds (run where the card library is) --------------------------

_LIB = "D:/Pinball/images/Stern/spike2"
#: {card: sorted set of main-topper-board device names the gate is found on, or None}
_EXPECT = {
    "venom_le-1_07_0.Release.8G.sdcard.raw": ["TOPPER"],
    "venom_pro-1_07_0.Release.8G.sdcard.raw": ["TOPPER"],
    "jaws_le-1_02_0.Release.16G.sdcard.raw": ["Topper"],
    "jurassic_park_le-1_16_0.Release.8G.sdcard.raw": ["Topper 1"],
    "king_kong_le-0_97_0.Release.16G.sdcard.raw": ["Topper"],
    "star_wars_elg-1_10_0_spike2.Release.8G.sdcard.raw": ["R2-D2 Topper"],
    # titles with no main-topper-board device_usable gate (their topper gate, if any, is elsewhere)
    "mando_le-1_45_0.Release.8G.sdcard.raw": None,
    "john_wick_le-1_02_0.Release.16G.sdcard.raw": None,
    "iron_maiden_le-1_18_0.Release.8G.sdcard.raw": None,
    "batman-1_14_0.Release.8G.sdcard.raw": None,
}


def _program(card):
    from pinball_decryptor.plugins.stern.explorer import CardImage
    c = CardImage(card)
    _t, part, path = c.adjustment_table()
    return c.read_firmware(part, path)


@pytest.mark.parametrize("card", sorted(_EXPECT))
def test_every_build(card):
    path = os.path.join(_LIB, card)
    if not os.path.isfile(path):
        pytest.skip("the card library is not on this machine")
    elf = bytes(_program(path))
    p = T.plan(elf)
    want = _EXPECT[card]
    if want is None:
        assert p is None
        return
    assert p is not None
    assert sorted(set(p["devices"])) == sorted(want)
    out = T.patched_bytes(elf, p)
    assert len(out) == len(elf)
    for va, old, new in p["sites"]:
        assert new in (0xE3A00001, 0xE12FFF1E)
    assert T.plan(out) is None
