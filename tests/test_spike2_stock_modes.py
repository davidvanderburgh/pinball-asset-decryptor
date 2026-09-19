"""Tests for tools/spike2_emu/modes/sdk/stock_modes.py (item 144): where a stock mode's numbers live.

The classifier is checked on synthetic ARM words wrapped in a minimal ELF - how each instruction
shape decodes, which values `mov #imm` can hold, and that the tracker names the kind of every
constant a call receives (movw+movt, rotated immediate, literal-pool word, a value built by code).
Against the real Godzilla Pro 1.15 game ELF (game data outside the repo; skipped without it) the
report must reproduce what the emulator proved: tesla strike's start award 250,000 as the
movw/movt pair at 0x10c228/0x10c234, jet fighter attack's 20 s timer as one `mov` at 0xb75c0,
and the battles' timers as operator adjustments; plus the lit-shot mask a start takes and the
battle selector's table of mode ids. Desk only.
"""
import importlib.util
import io
import os
import pathlib
import struct

import pytest

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
PRO_ELFS = (r"C:\tmp\pad_parallel\item144\pro115\game", r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game",
            "/mnt/c/tmp/pad_parallel/item144/pro115/game", "/mnt/c/tmp/radium_scene_re/godzilla_pro_1_15/game")


def _tool():
    spec = importlib.util.spec_from_file_location("stock_modes", SDK / "stock_modes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _elf(code_words, va=0x10000):
    """A minimal little-endian ELF32 with one R+X PT_LOAD holding code_words at va."""
    code = struct.pack("<%dI" % len(code_words), *code_words)
    off = 0x100
    hdr = bytearray(52)
    hdr[0:4] = b"\x7fELF"
    hdr[4], hdr[5], hdr[6] = 1, 1, 1
    struct.pack_into("<HHIIIIIHHHHHH", hdr, 16, 2, 40, 1, va, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    ph = struct.pack("<8I", 1, off, va, va, len(code), len(code), 5, 0x1000)
    body = bytes(hdr) + ph
    return body + b"\0" * (off - len(body)) + code


def test_decode_shapes():
    t = _tool()
    assert t.decode(0xE30D2090, 0)[:3] == ("movw", 2, 0xD090)
    assert t.decode(0xE3402003, 0)[:3] == ("movt", 2, 3)
    assert t.decode(0xE3A00014, 0)[:3] == ("mov", 0, 20)
    assert t.decode(0x03A0101E, 0)[:4] == ("mov", 1, 30, 0x0)          # moveq r1, #30: condition kept
    assert t.decode(0xE3A00E53, 0)[:3] == ("mov", 0, 0x530)            # a rotated immediate: 1328
    assert t.decode(0xE59F0000, 0x1000)[:3] == ("ldrlit", 0, 0x1008)
    assert t.decode(0xE51F0004, 0x1000)[:3] == ("ldrlit", 0, 0x1000 + 8 - 4)
    assert t.decode(0xEB000000, 0x1000)[:2] == ("bl", 0x1008)
    assert t.decode(0xE12FFF1E, 0)[0] == "bxlr"
    assert t.decode(0xE8BD8010, 0)[0] == "poppc"
    assert t.decode(0xE92D4010, 0)[0] == "pushlr"
    assert t.decode(0xE58D5000, 0)[:3] == ("strsp", 5, 0)
    assert t.decode(0xE5933030, 0)[:4] == ("ldri", 3, 3, 0x30)         # a vtable slot load: slot 12


def test_encodable_imm8():
    t = _tool()
    for v in (0, 20, 30, 255, 256, 0x530, 0x700000, 0xFF000000, 0x48):
        assert t.encodable_imm8(v), hex(v)
    for v in (0x1FF, 250000, 1250000, 0x101):
        assert not t.encodable_imm8(v), hex(v)


def test_tracker_names_each_kind():
    t = _tool()
    base = 0x10000
    callee = base + 0x40
    words = [
        0xE92D4010,                                 # 00 push {r4, lr}
        0xE30D2090,                                 # 04 movw r2, #0xd090
        0xE3A05000,                                 # 08 mov r5, #0
        0xE3402003,                                 # 0c movt r2, #3        -> 250000, movwt
        0xE3A03000,                                 # 10 mov r3, #0
        0xE58D5000,                                 # 14 str r5, [sp]
        0xEB000000 | ((callee - (base + 0x18) - 8) // 4) & 0xFFFFFF,   # 18 bl callee
        0xE59F0010,                                 # 1c ldr r0, [pc, #16]  -> literal at 0x34
        0xE3A01E53,                                 # 20 mov r1, #0x530     -> imm 1328
        0xEB000000 | ((callee - (base + 0x24) - 8) // 4) & 0xFFFFFF,   # 24 bl callee
        0xE0800001,                                 # 28 add r0, r0, r1     -> code: r0 unknown
        0xE3A01000,                                 # 2c mov r1, #0
        0xE8BD8010,                                 # 30 pop {r4, pc}
        0x0003D090,                                 # 34 the literal: 250000
        0xE3A00000,                                 # 38 (unused)
        0xE12FFF1E,                                 # 3c
        0xE3A00014,                                 # 40 callee: mov r0, #20
        0xE12FFF1E,                                 # 44 bx lr
    ]
    img = t.Image(_elf(words, base))
    calls, _vcalls, _strings, end = t.track(img, base, {callee: "caward_add"})
    assert end == base + 0x34
    first, second = calls[0], calls[1]
    assert first["name"] == "caward_add" and first["va"] == base + 0x18
    k, w = t.kind_of(first["args"]["r2"])
    assert first["args"]["r2"].v == 250000 and k == ("movwt", base + 0x04, base + 0x0C) and w == ["e30d2090", "e3402003"]
    assert first["args"]["sp0"].v == 0 and t.kind_of(first["args"]["sp0"])[0] == ("imm", base + 0x08)
    k, w = t.kind_of(second["args"]["r0"])
    assert second["args"]["r0"].v == 250000 and k == ("lit", base + 0x34) and w == ["0003d090"]
    assert t.kind_of(second["args"]["r1"])[0] == ("imm", base + 0x20) and second["args"]["r1"].v == 1328
    assert "r2" not in second["args"]                     # clobbered by the first call
    assert t.const_return(img, callee)[:2] == (20, ("imm", callee))
    assert t.fmt_kind(("movwt", 0x10C228, 0x10C234)) == "movwt 0x10c228 0x10c234"


def test_a_value_merged_from_two_paths_is_unknown():
    t = _tool()
    base = 0x20000
    words = [
        0xE92D4010,                                 # 00 push {r4, lr}
        0xE3500000,                                 # 04 cmp r0, #0
        0x0A000001,                                 # 08 beq 0x14
        0xE3A01005,                                 # 0c mov r1, #5
        0xEA000000,                                 # 10 b 0x18
        0xE3A01007,                                 # 14 mov r1, #7
        0xE3A02009,                                 # 18 mov r2, #9     (both paths)
        0xEB000001,                                 # 1c bl 0x28
        0xE8BD8010,                                 # 20 pop {r4, pc}
        0xE1A00000,                                 # 24 nop
        0xE12FFF1E,                                 # 28 callee: bx lr
    ]
    img = t.Image(_elf(words, base))
    calls, _v, _s, _e = t.track(img, base, {base + 0x28: "callout_play"})
    args = calls[0]["args"]
    assert "r1" not in args                               # 5 on one path, 7 on the other: not a guess
    assert args["r2"].v == 9


def test_a_64_bit_mask_return_and_its_words():
    t = _tool()
    base = 0x30000
    words = [
        0xE3A00B02,                                 # 00 mov r0, #0x800
        0xE3A01058,                                 # 04 mov r1, #0x58
        0xE3400070,                                 # 08 movt r0, #0x70   -> lo 0x00700800
        0xE12FFF1E,                                 # 0c bx lr
        0xE3A00000,                                 # 10 mov r0, #0
        0xE3A01020,                                 # 14 mov r1, #0x20
        0xEA000000,                                 # 18 b 0x20           (a tail call)
        0xE12FFF1E,                                 # 1c
        0xE3500000,                                 # 20 cmp r0, #0       (not a constant return)
        0x03A00001,                                 # 24 moveq r0, #1
        0xE12FFF1E,                                 # 28 bx lr
    ]
    img = t.Image(_elf(words, base))
    val, sites, tail = t.const_return64(img, base)
    assert (val[1] << 32 | val[0]) == 0x5800700800 and tail is None
    assert t.half_kind(sites[0]) == (("movwt", base, base + 8), ["e3a00b02", "e3400070"])
    assert t.half_kind(sites[1]) == (("imm", base + 4), ["e3a01058"])
    val, sites, tail = t.const_return64(img, base + 0x10)
    assert (val[1] << 32 | val[0]) == 0x2000000000 and tail == base + 0x20
    assert t.const_return64(img, base + 0x20) is None
    assert t.mask_names(0x300000, t.SHOT_BITS_GODZILLA) == "left ramp, right ramp"
    assert t.mask_names(0x14, {}) == "bit 2, bit 4"


def test_a_selector_table_of_mode_ids():
    t = _tool()
    base = 0x40000
    table = [0, 12, 0, 1, 13, 0, 2, 6, 0, 3, 99, 0]         # the 4th id is not a mode: three slots
    words = [0xE12FFF1E, 0xDEADBEEF] + table + [0, 21, 0, 1, 21, 0]   # a repeated id is not a selector
    img = t.Image(_elf(words, base))
    assert t.selector_tables(img, range(1, 27)) == [(base + 8, [12, 13, 6])]


def _pro_elf():
    for p in PRO_ELFS:
        if os.path.exists(p):
            return p
    pytest.skip("Godzilla Pro 1.15 game program not present")


def test_the_pro_115_report_matches_what_the_emulator_proved():
    path = _pro_elf()
    t = _tool()
    data = open(path, "rb").read()
    img = t.Image(data)
    if img.sha1 != t.PRO115_SHA1:
        pytest.skip("not the Godzilla Pro 1.15 build")
    model = t.rt.build_model(data)
    out = io.StringIO()
    rep = t.report(img, model, t.ENGINE_PRO115, "godzilla_pro", "1.15", out=out)
    text = out.getvalue()
    modes = {m["id"]: m for m in rep["modes"]}
    assert sorted(modes) == list(range(1, 27))
    assert modes[23]["class"] == "cmode_tesla_strike" and modes[23]["object"] == 0x7A2878
    assert modes[23]["ctor_args"][:3] == [0, 30, 9]
    assert "number 23 start.caward_add 250000 movwt 0x10c228 0x10c234 e30d2090,e3402003 word" in text
    assert "number 21 timer.seconds 20 imm 0xb75c0 e3a00014 word" in text
    assert "number 12 timer.seconds 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212" in text
    assert "number 23 title_msg 3242 movw 0x1101a4" in text
    assert "start 23 start: cmode_manager_get(23)" in text and "fn 0x1666fc" in text
    # the battle select screen's table (0x631f44) is the only start path of 6, 16 and 17
    assert "number 16 select.slot4.mode_id 16 data 0x631f78 00000010 word" in text
    assert "number 6 select.slot5.mode_id 6 data 0x631f84 00000006 word" in text
    assert "shots 18 0x300000 v[44] 0x100714" in text
    assert "number 18 initial_mask.lo 3145728 imm 0x100714 e3a00603 word" in text
    # every word the report quotes is the ELF's own
    for m in rep["modes"]:
        for n in m["numbers"]:
            k = n["kind"]
            if k[0] in ("imm", "movw"):
                assert "%08x" % img.word(k[1]) == n["words"][0]
            elif k[0] == "movwt":
                assert ["%08x" % img.word(k[1]), "%08x" % img.word(k[2])] == n["words"]
            elif k[0] == "lit":
                assert "%08x" % img.word(k[1]) == n["words"][0]
