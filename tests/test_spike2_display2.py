"""The second display's size is READ OUT OF THE GAME, not typed into a table.

WHAT THIS GUARDS. `display2.py` finds the two static framebuffer timing records
a Spike 2 game hands its FB_SetTiming for `/dev/fb0` (backbox) and `/dev/fb2`
(the second display), by resolving the movw/movt pairs that build the path and
record addresses beside each other. mando_le 1.44.0 measured 2026-09-05: fb0
1360x768, fb2 1280x800 - and with the shim answering 1360x768 for the topper,
the game composed an empty topper scene for three runs (item 67). Item 65 had
already ruled that a hand-typed per-title size table is worse than none; this
is the derivation it asked for.

The tests build a synthetic code blob with real A32 movw/movt encodings, in
the interleaved order the mando binary uses, and a dict-backed address reader,
so no card, no ELF and no rig are needed.

FAST AND SYNTHETIC like the rest of the rig's tests.
"""
import os
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


@pytest.fixture()
def display2():
    import display2 as mod
    return mod


def movw(reg, imm16):
    return 0xE3000000 | ((imm16 & 0xF000) << 4) | (reg << 12) | (imm16 & 0xFFF)


def movt(reg, imm16):
    return 0xE3400000 | ((imm16 & 0xF000) << 4) | (reg << 12) | (imm16 & 0xFFF)


NOP = 0xE1A00000            # mov r0, r0
BL = 0xEB000000             # a call, any target


def record(xres, yres, bpp=16):
    fields = [12500, 97, 100, 95, xres, 9, 20, 9, yres, bpp, 0]
    return struct.pack("<11I", *fields)


def build(rx_va=0x8000, with_fb2=True):
    """A code segment: two FB_SetTiming call sites in mando's interleaved
    order, the two path strings, and the two records; returns (rx_bytes,
    rx_va, read_va)."""
    str0_va = rx_va + 0x400
    str2_va = rx_va + 0x410
    rec0_va = rx_va + 0x500
    rec2_va = rx_va + 0x52c
    code = []

    def site(str_va, rec_va):
        code.extend([movw(0, str_va & 0xFFFF), movw(1, rec_va & 0xFFFF),
                     movt(0, str_va >> 16), movt(1, rec_va >> 16), BL, NOP])

    site(str2_va, rec2_va)
    site(str0_va, rec0_va)
    blob = bytearray(struct.pack("<%dI" % len(code), *code))
    blob += b"\0" * (0x400 - len(blob))
    blob += b"/dev/fb0\0" + b"\0" * 7
    blob += b"/dev/fb2\0" + b"\0" * 7
    blob += b"\0" * (0x500 - len(blob))
    blob += record(1360, 768)
    blob += record(1280, 800) if with_fb2 else b"\0" * 44
    if not with_fb2:
        # a single-display game has no /dev/fb2 string at all
        i = blob.find(b"/dev/fb2")
        blob[i:i + 8] = b"\0" * 8
    blob = bytes(blob)

    def read_va(va, n):
        off = va - rx_va
        if 0 <= off <= len(blob) - n:
            return blob[off:off + n]
        return None

    return blob, rx_va, read_va


def test_movw_movt_pairs_resolve_interleaved_registers(display2):
    blob, rx_va, _ = build()
    pairs = list(display2.movw_movt_pairs(blob, rx_va))
    values = {(reg, val) for _i, reg, val in pairs}
    assert (0, rx_va + 0x410) in values          # /dev/fb2 into r0
    assert (1, rx_va + 0x52c) in values          # its record into r1
    assert (0, rx_va + 0x400) in values
    assert (1, rx_va + 0x500) in values


def test_both_records_are_found_and_decoded(display2):
    blob, rx_va, read_va = build()
    geo = display2.find_records(blob, rx_va, read_va)
    assert geo["fb0"][:3] == (1360, 768, 16)
    assert geo["fb2"][:3] == (1280, 800, 16)
    assert geo["fb2"][3] == rx_va + 0x52c


def test_a_single_display_game_yields_no_fb2(display2):
    blob, rx_va, read_va = build(with_fb2=False)
    geo = display2.find_records(blob, rx_va, read_va)
    assert "fb2" not in geo
    assert geo["fb0"][:2] == (1360, 768)


def test_shell_output_names_only_the_second_display(display2, monkeypatch, capsys):
    monkeypatch.setattr(display2, "fb_geometry",
                        lambda path: {"fb0": (1360, 768, 16, 1),
                                      "fb2": (1280, 800, 16, 2)})
    assert display2.main(["display2.py", "--shell", "x"]) == 0
    assert capsys.readouterr().out.strip() == "PAD_GL2_W=1280 PAD_GL2_H=800"
    monkeypatch.setattr(display2, "fb_geometry",
                        lambda path: {"fb0": (1360, 768, 16, 1)})
    assert display2.main(["display2.py", "--shell", "x"]) == 1
    assert capsys.readouterr().out.strip() == ""
