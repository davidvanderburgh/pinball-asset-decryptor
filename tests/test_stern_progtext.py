"""Tests for the Spike 2 game-program display strings (plugins.stern.progtext).

Everything runs on a tiny synthetic 32-bit ELF: one PT_LOAD segment mapping
the whole file at VBASE, a NUL-separated string table, and five-identical-dword
"name groups" (the five-UI-language pointer shape) — including one that points
INTO a longer string, the substring trick Godzilla uses for its battle names
("GODZILLA VS EBIRAH" + 12 is the standalone EBIRAH the battle intro shows).
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import progtext

VBASE = 0x10000
BODY_OFF = 0x100          # strings/pointers live after the headers


def _elf(body):
    """A minimal 32-bit LE ELF: header + one PT_LOAD covering the file."""
    total = BODY_OFF + len(body)
    hdr = bytearray(52)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1                                    # ELFCLASS32
    hdr[5] = 1                                    # little-endian
    struct.pack_into("<H", hdr, 0x12, 40)         # e_machine = EM_ARM
    struct.pack_into("<I", hdr, 0x1c, 52)         # e_phoff
    struct.pack_into("<H", hdr, 0x2a, 32)         # e_phentsize
    struct.pack_into("<H", hdr, 0x2c, 1)          # e_phnum
    ph = bytearray(32)
    struct.pack_into("<I", ph, 0, 1)              # PT_LOAD
    struct.pack_into("<I", ph, 4, 0)              # p_offset
    struct.pack_into("<I", ph, 8, VBASE)          # p_vaddr
    struct.pack_into("<I", ph, 16, total)         # p_filesz
    struct.pack_into("<I", ph, 20, total)         # p_memsz
    raw = bytes(hdr) + bytes(ph) + b"\x00" * (BODY_OFF - 52 - 32) + body
    return raw


def _build():
    """The fixture ELF: returns (raw, offsets dict)."""
    strings = [
        ("title", "GODZILLA VS EBIRAH"),
        ("mega", "GODZILLA VS MEGALON"),
        ("plain", "JACKPOT AWARD!"),
        ("ident", "AUD_MODE_BATTLE_STARTED"),      # excluded: identifier
        ("sound", "SE GZ VO KAIJUBATTLE 1"),       # excluded: sound event
        ("fmt", "%d MONSTERS LEFT"),
        ("multi", "GODZILLA, MOTHRA\nVS.\nKING GHIDORAH"),
    ]
    body = bytearray(b"\x00")                      # leading NUL: span anchors
    offs = {}
    for key, s in strings:
        offs[key] = BODY_OFF + len(body)
        body += s.encode() + b"\x00"
    # align to 4 for the pointer tables
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"
    va = lambda k, d=0: VBASE + offs[k] + d
    # 5-language group pointing INTO title (+12 -> "EBIRAH")
    offs["grp_tail"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("title", 12)] * 5)) + b"\x00" * 4
    # 5-language group pointing INTO mega (+12 -> "MEGALON")
    offs["grp_mega"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("mega", 12)] * 5)) + b"\x00" * 4
    # tail of multi: "KING GHIDORAH" at +21
    offs["grp_multi"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("multi", 21)] * 5)) + b"\x00" * 4
    # a LONE word that happens to equal title+12 — must never be patched
    offs["lone"] = BODY_OFF + len(body)
    body += struct.pack("<I", va("title", 12))
    return _elf(bytes(body)), offs


@pytest.fixture()
def fixture_elf():
    return _build()


def _logs():
    msgs = []
    return msgs, lambda m, lvl="info": msgs.append((lvl, m))


def test_enumerate_rows(fixture_elf):
    raw, offs = fixture_elf
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(raw)}
    assert rows["GODZILLA VS EBIRAH"]["tail_of"] is None
    assert rows["GODZILLA VS EBIRAH"]["budget"] == 18
    # the substring name is its own row, budgeted by the HOST length
    assert rows["EBIRAH"]["tail_of"] == "GODZILLA VS EBIRAH"
    assert rows["EBIRAH"]["budget"] == 18
    assert rows["MEGALON"]["tail_of"] == "GODZILLA VS MEGALON"
    # multiline title round-trips with visible \n escapes
    multi = "GODZILLA, MOTHRA\\nVS.\\nKING GHIDORAH"
    assert multi in rows
    assert rows["KING GHIDORAH"]["tail_of"] == multi
    assert rows["JACKPOT AWARD!"]["budget"] == 14
    # exclusions
    assert "AUD_MODE_BATTLE_STARTED" not in rows
    assert "SE GZ VO KAIJUBATTLE 1" not in rows


def test_full_plus_tail_edit_moves_pointers(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(
        raw, {"GODZILLA VS EBIRAH": "GZ VS BIOLLANTE",
              "EBIRAH": "BIOLLANTE"}, log)
    assert n == 2
    by_off = dict(writes)
    # the string write: NUL-padded to the original 18 bytes
    assert by_off[offs["title"]] == b"GZ VS BIOLLANTE\x00\x00\x00"
    # all five group words move to +6 ("GZ VS " prefix), the lone word doesn't
    new_ptr = struct.pack("<I", VBASE + offs["title"] + 6)
    for i in range(5):
        assert by_off[offs["grp_tail"] + 4 * i] == new_ptr
    assert offs["lone"] not in by_off
    # applying the writes yields the new strings on a rescan
    buf = bytearray(raw)
    for o, b in writes:
        buf[o:o + len(b)] = b
    rows = {r["text"]: r for r in
            progtext.enumerate_program_strings(bytes(buf))}
    assert rows["BIOLLANTE"]["tail_of"] == "GZ VS BIOLLANTE"


def test_tail_only_edit_that_fits(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(raw, {"EBIRAH": "ORGA"}, log)
    assert n == 1
    by_off = dict(writes)
    assert by_off[offs["title"]] == b"GODZILLA VS ORGA\x00\x00"
    # delta unchanged -> no pointer rewrites
    assert all(o == offs["title"] for o in by_off)


def test_tail_only_edit_too_long_is_skipped(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(raw, {"EBIRAH": "BIOLLANTE"}, log)
    assert writes == [] and n == 0
    assert any("Edit the full line too" in m for _l, m in msgs)


def test_full_edit_that_breaks_the_tail_is_skipped(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(
        raw, {"GODZILLA VS EBIRAH": "GZ VS BIOLLANTE"}, log)
    assert writes == [] and n == 0
    assert any("shown on its own" in m for _l, m in msgs)


def test_multiline_tail_edit(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(raw, {"KING GHIDORAH": "MECHAGHIDORA"},
                                     log)
    assert n == 1
    by_off = dict(writes)
    want = "GODZILLA, MOTHRA\nVS.\nMECHAGHIDORA".encode()
    orig_len = len("GODZILLA, MOTHRA\nVS.\nKING GHIDORAH")
    assert by_off[offs["multi"]] == want.ljust(orig_len, b"\x00")


def test_percent_tokens_guarded(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(raw, {"%d MONSTERS LEFT": "NO KAIJU"},
                                     log)
    assert writes == [] and n == 0
    assert any("placeholders" in m for _l, m in msgs)
    # keeping the token is fine
    writes, n = progtext.plan_writes(raw, {"%d MONSTERS LEFT": "%d KAIJU"},
                                     log)
    assert n == 1


def test_unknown_edit_warns(fixture_elf):
    raw, _offs = fixture_elf
    msgs, log = _logs()
    writes, n = progtext.plan_writes(raw, {"NOT PRESENT": "X"}, log)
    assert writes == [] and n == 0
    assert any("wasn't found" in m for _l, m in msgs)


def test_not_an_elf_yields_nothing():
    assert progtext.enumerate_program_strings(b"garbage" * 100) == []
    msgs, log = _logs()
    writes, n = progtext.plan_writes(b"garbage" * 100, {"A B": "C"}, log)
    assert writes == [] and n == 0
