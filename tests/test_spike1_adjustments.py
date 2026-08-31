"""Spike 1 operator-adjustment decoder + default patcher.

Built against a hand-assembled minimal ELF32 fixture so the test runs anywhere;
the same decoder is verified against the real Game of Thrones / Ghostbusters /
KISS / WWE game ELFs by hand (all four decode sane — see the module docstring).
"""
import struct

import pytest

from pinball_decryptor.plugins.stern.spike1_adjustments import (
    Spike1AdjustmentError, Spike1Adjustments, _label_from_name)


# --- a minimal ELF32-LE with a symbol table and two PROGBITS sections --------
# Layout (file offsets == virtual addresses for simplicity):
#   .rodata @ 0x1000: count (u32) + name strings + name-pointer arrays
#   .data   @ 0x2000: the 32-byte adjustment entries
#   symtab + strtab hold `adjustment_table_data` and the count symbol.

_EHDR = struct.Struct("<16sHHIIIIIHHHHHH")
_SHDR = struct.Struct("<IIIIIIIIII")
_SYM = struct.Struct("<IIIBBH")

TABLE_VA = 0x2000
COUNT_VA = 0x1000
NAMES = ["INVALID", "FREE PLAY", "REPLAY LEVEL", "GI BRIGHTNESS"]


def _build_elf():
    count = len(NAMES)
    # .rodata: count word, then for each id a name string + a 4x char* array
    rodata = bytearray()
    rodata += struct.pack("<I", count)                 # @0x1000 count
    str_va = {}
    for i, nm in enumerate(NAMES):
        str_va[i] = COUNT_VA + len(rodata)
        rodata += nm.encode() + b"\x00"
    while len(rodata) % 4:
        rodata += b"\x00"
    arr_va = {}
    for i in range(count):
        arr_va[i] = COUNT_VA + len(rodata)
        rodata += struct.pack("<4I", *([str_va[i]] * 4))   # EN/DE/FR/ES

    # .data: 32-byte entries. fields (default, min, max, step) + name ptr @0x18
    entries = [
        (0, 0, 0, 0, 0),                       # id0 INVALID
        (1, 0, 1, 1, 0x10005),                 # FREE PLAY toggle
        (30_000_000, 10_000_000, 1_000_000_000, 10_000_000, 0x1e),  # REPLAY
        (100, 25, 100, 1, 5),                  # GI BRIGHTNESS
    ]
    data_sec = bytearray()
    for i, (dflt, mn, mx, step, typ) in enumerate(entries):
        e = bytearray(32)
        struct.pack_into("<i", e, 0x04, dflt)
        struct.pack_into("<i", e, 0x08, mn)
        struct.pack_into("<i", e, 0x0C, mx)
        struct.pack_into("<i", e, 0x10, step)
        struct.pack_into("<I", e, 0x18, arr_va[i])
        struct.pack_into("<I", e, 0x1C, typ)
        data_sec += e

    # strtab for symbols
    strtab = b"\x00adjustment_table_data\x00ADJUSTMENT_TABLE_DATA_ENTRY_COUNT\x00"
    n1 = strtab.index(b"adjustment_table_data")
    n2 = strtab.index(b"ADJUSTMENT_TABLE_DATA_ENTRY_COUNT")
    symtab = _SYM.pack(0, 0, 0, 0, 0, 0)                # null sym
    symtab += _SYM.pack(n1, TABLE_VA, 0, 0, 0, 2)       # adjustment_table_data
    symtab += _SYM.pack(n2, COUNT_VA, 0, 0, 0, 1)       # count

    # assemble the file: EHDR, then sections laid out at fixed file offsets.
    ehdr_sz = _EHDR.size
    shoff = 0x400
    sh_rodata_off = 0x1000
    sh_data_off = 0x2000
    sh_strtab_off = 0x3000
    sh_symtab_off = 0x3400

    total = max(sh_symtab_off + len(symtab), sh_data_off + len(data_sec),
                sh_rodata_off + len(rodata)) + 0x40
    buf = bytearray(total)
    # e_ident + header; shnum=5, shstrndx irrelevant (we don't read section names)
    _EHDR.pack_into(
        buf, 0, b"\x7fELF\x01\x01\x01" + b"\x00" * 9, 2, 40, 1, 0, 0,
        shoff, 0, ehdr_sz, 0, 0, _SHDR.size, 5, 0)
    buf[sh_rodata_off:sh_rodata_off + len(rodata)] = rodata
    buf[sh_data_off:sh_data_off + len(data_sec)] = data_sec
    buf[sh_strtab_off:sh_strtab_off + len(strtab)] = strtab
    buf[sh_symtab_off:sh_symtab_off + len(symtab)] = symtab

    # section headers: [0]=null, [1]=.rodata PROGBITS, [2]=.data PROGBITS,
    # [3]=.strtab STRTAB, [4]=.symtab SYMTAB(link=3)
    def shdr(typ, addr, off, size, link=0, entsize=0):
        return _SHDR.pack(0, typ, 0, addr, off, size, link, 0, 1, entsize)
    sh = b""
    sh += shdr(0, 0, 0, 0)
    sh += shdr(1, COUNT_VA, sh_rodata_off, len(rodata))          # .rodata
    sh += shdr(1, TABLE_VA, sh_data_off, len(data_sec))          # .data
    sh += shdr(3, 0, sh_strtab_off, len(strtab))                 # .strtab
    sh += shdr(2, 0, sh_symtab_off, len(symtab), link=3,
               entsize=_SYM.size)                                # .symtab
    buf[shoff:shoff + len(sh)] = sh
    return bytes(buf)


@pytest.fixture(scope="module")
def adj():
    return Spike1Adjustments(_build_elf())


def test_count_and_named_rows(adj):
    assert adj.count == 4
    rows = adj.rows()
    assert len(rows) == 3            # INVALID (id0) is skipped
    assert [r["id"] for r in rows] == [1, 2, 3]


def test_entry_fields(adj):
    e = adj.entry(2)
    assert e["name"] == "REPLAY LEVEL"
    assert e["default"] == 30_000_000
    assert e["min"] == 10_000_000
    assert e["max"] == 1_000_000_000
    assert e["step"] == 10_000_000


def test_row_shape_matches_the_settings_tab(adj):
    r = next(r for r in adj.rows() if r["id"] == 1)
    assert set(r) == {"id", "name", "label", "default", "min", "max",
                      "step", "labels", "status"}
    assert r["name"] == "AD_1"               # stable synthetic key
    assert r["label"] == "Free Play"
    assert r["min"] == 0 and r["max"] == 1   # the tab renders this as off/on


def test_sane(adj):
    assert adj.sane() is True


def test_patch_is_size_neutral_and_roundtrips(adj):
    patched = adj.patched_bytes({2: 50_000_000})
    assert len(patched) == len(adj.elf.data)
    reparsed = Spike1Adjustments(patched)
    assert reparsed.entry(2)["default"] == 50_000_000
    # only the one 4-byte field changed
    diff = sum(1 for x, y in zip(adj.elf.data, patched) if x != y)
    assert 1 <= diff <= 4


def test_patch_rejects_out_of_range(adj):
    with pytest.raises(Spike1AdjustmentError):
        adj.patched_bytes({1: 5})            # FREE PLAY max is 1


def test_missing_symbol_is_an_error():
    with pytest.raises(Spike1AdjustmentError):
        Spike1Adjustments(b"\x7fELF\x01\x01\x01" + b"\x00" * 200)


def test_label_from_name():
    assert _label_from_name("REPLAY LEVEL #3") == "Replay Level #3"
    assert _label_from_name("GI LED BRIGHTNESS") == "GI Led Brightness"
    assert _label_from_name("") == ""


# --- write-back round-trip against a real card (skipped if absent) -----------

import os as _os
import shutil as _shutil

_CARD = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "images", "Stern", "spike1", "ghostbusters_le-1_17.iso")


@pytest.mark.skipif(not _os.path.isfile(_CARD),
                    reason="Spike 1 sample card not present")
def test_write_game_elf_defaults_roundtrips_on_a_card(tmp_path):
    from pinball_decryptor.plugins.stern import spike1
    from pinball_decryptor.plugins.stern.formats import spike1_linux_partitions

    card = str(tmp_path / "card.iso")
    _shutil.copy(_CARD, card)
    parts = spike1_linux_partitions(card)
    before = Spike1Adjustments(spike1.read_game_elf(card, parts))
    # pick a numeric (non-toggle) adjustment and move it within range
    idx = next(r["id"] for r in before.rows()
               if r["max"] - r["min"] >= 2 and r["step"] >= 1)
    e = before.entry(idx)
    newv = e["min"] + e["step"]
    if newv == e["default"]:
        newv = min(e["max"], e["default"] + e["step"])

    n = spike1.write_game_elf_defaults(card, {idx: newv})
    assert n == 1
    after = Spike1Adjustments(spike1.read_game_elf(card, parts))
    assert after.entry(idx)["default"] == newv

    # the card's own .sidx now validates the patched firmware
    from pinball_decryptor.plugins.stern import sidx as sidx_mod
    import hashlib
    with open(card, "rb") as f:
        reader, game_dir, _img, _sp, sidx_node = spike1.locate_assets(f, parts)
        node = spike1._find_game_elf_node(reader, game_dir)
        elf_live = reader.read_file_bytes(node)
        recs, _crc, _fmt = sidx_mod.parse_records(
            reader.read_file_bytes(sidx_node))
    rec = recs["%s/game" % game_dir]
    stored = rec["md5"] if isinstance(rec, dict) and "md5" in rec else None
    if stored is not None:
        assert hashlib.md5(elf_live).hexdigest() == stored
