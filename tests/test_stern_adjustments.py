"""Spike 2 adjustment-default decoder/patcher (plugins.stern.adjustments).

Uses a synthetic little-endian 32-bit ARM ELF carrying the same shapes the RE
found on real firmware (packed AD_ names[], a section record
{live, table, count, elem, node}, and a descriptor array with
default@+4/min@+8/max@+12) so the logic is covered without a 69 MB game_real.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern.adjustments import (AdjustmentTable,
                                                         curated_rows)

BASE = 0x10000
ELEM = 44


def make_elf(specs, node=b"SYS\x00"):
    """specs = [(name, default, min, max), ...] -> ELF bytes.  One PT_LOAD maps
    file offset f to vaddr BASE+f, so va(f)=f+BASE."""
    # Layout: [52 hdr][32 phdr][strings][names[]][descriptors][node][record]
    body = bytearray()

    def va(off):
        return BASE + off

    hdr_len = 52 + 32
    strings_off = hdr_len
    blob = bytearray()
    name_va = []
    for name, _d, _mn, _mx in specs:
        name_va.append(va(strings_off + len(blob)))
        blob += name.encode() + b"\x00"
    node_rel = len(blob)
    blob += node
    # names[] array
    names_off = strings_off + len(blob)
    names_arr = b"".join(struct.pack("<I", v) for v in name_va)
    # descriptors
    desc_off = names_off + len(names_arr)
    desc = bytearray()
    for _n, d, mn, mx in specs:
        e = bytearray(ELEM)
        struct.pack_into("<iii", e, 0x04, d, mn, mx)   # default,min,max
        struct.pack_into("<i", e, 0x10, 1)             # step
        # a rodata-ish pointer at +0x18 (points at a name string)
        struct.pack_into("<I", e, 0x18, name_va[0])
        desc += e
    # section record {live, table, count, elem, node}
    rec_off = desc_off + len(desc)
    record = struct.pack("<IIIII", 0, va(desc_off), len(specs), ELEM,
                         va(strings_off + node_rel))

    payload = bytearray()
    payload += blob
    payload += names_arr
    payload += desc
    payload += record
    total = hdr_len + len(payload)

    eh = bytearray(52)
    eh[0:4] = b"\x7fELF"
    eh[4] = 1          # 32-bit
    eh[5] = 1          # little-endian
    eh[6] = 1          # version
    struct.pack_into("<H", eh, 0x10, 2)      # e_type EXEC
    struct.pack_into("<H", eh, 0x12, 40)     # e_machine ARM
    struct.pack_into("<I", eh, 0x14, 1)      # e_version
    struct.pack_into("<I", eh, 0x1c, 52)     # e_phoff
    struct.pack_into("<H", eh, 0x28, 52)     # e_ehsize
    struct.pack_into("<H", eh, 0x2a, 32)     # e_phentsize
    struct.pack_into("<H", eh, 0x2c, 1)      # e_phnum
    ph = struct.pack("<IIIIIIII", 1, 0, BASE, BASE, total, total, 5, 0x1000)
    return bytes(eh + ph + payload)


SPECS = [
    ("AD_INVALID", 0, 0, 0),
    ("AD_FREE_PLAY", 0, 0, 1),
    ("AD_GAME_PRICING", 69, 0, 72),
    ("AD_SOUND_MASTER_VOLUME_SETTING", 64, 0, 64),
    ("AD_CREDIT_LIMIT", 30, 4, 50),
    ("AD_EXTERNAL_VOLUME_KNOB_FUNCTION", 0, 0, 2),
    ("AD_LANGUAGE", 0, 0, 4),
]


def test_decode_reads_defaults():
    t = AdjustmentTable(make_elf(SPECS))
    assert t.count == len(SPECS) and t.elem == ELEM and t.node == "SYS"
    e = t.get("AD_FREE_PLAY")
    assert (e["default"], e["min"], e["max"], e["step"]) == (0, 0, 1, 1)
    assert t.get("AD_GAME_PRICING")["default"] == 69
    assert t.get("AD_SOUND_MASTER_VOLUME_SETTING")["max"] == 64
    assert t.sane()


def test_curated_rows_display_units_and_labels():
    rows = {r["name"]: r for r in curated_rows(AdjustmentTable(make_elf(SPECS)))}
    # Free play is an on/off toggle.
    assert rows["AD_FREE_PLAY"]["kind"] == "toggle"
    assert rows["AD_FREE_PLAY"]["labels"] == {0: "Off", 1: "On"}
    # Master volume is shown on the machine's 0-16 scale (internal 0-64 / 4).
    mv = rows["AD_SOUND_MASTER_VOLUME_SETTING"]
    assert mv["scale"] == 4
    assert (mv["default"], mv["min"], mv["max"]) == (16, 0, 16)
    # Plain numeric is 1:1.
    cl = rows["AD_CREDIT_LIMIT"]
    assert cl["scale"] == 1 and (cl["default"], cl["min"], cl["max"]) == (30, 4,
                                                                          50)
    # Language is an enum with labels; index 0 = English.
    lang = rows["AD_LANGUAGE"]
    assert lang["kind"] == "enum" and lang["labels"][0] == "English"
    # Game Pricing / External Volume Knob are deferred (labels not RE'd) —
    # not shown as raw numbers.
    assert "AD_GAME_PRICING" not in rows
    assert "AD_EXTERNAL_VOLUME_KNOB_FUNCTION" not in rows


def test_patch_is_surgical_and_validated():
    elf = make_elf(SPECS)
    t = AdjustmentTable(elf)
    patched = t.patched_bytes({"AD_FREE_PLAY": 1,
                               "AD_SOUND_MASTER_VOLUME_SETTING": 40})
    assert len(patched) == len(elf)
    assert sum(1 for a, b in zip(elf, patched) if a != b) == 2  # two low bytes
    t2 = AdjustmentTable(patched)
    assert t2.get("AD_FREE_PLAY")["default"] == 1
    assert t2.get("AD_SOUND_MASTER_VOLUME_SETTING")["default"] == 40
    # untouched settings unchanged
    assert t2.get("AD_GAME_PRICING")["default"] == 69


def test_patch_rejects_out_of_range_and_unknown():
    t = AdjustmentTable(make_elf(SPECS))
    with pytest.raises(ValueError, match="out of range"):
        t.patched_bytes({"AD_FREE_PLAY": 5})
    with pytest.raises(ValueError, match="unknown"):
        t.patched_bytes({"AD_NOT_A_THING": 1})


def test_non_elf_rejected():
    with pytest.raises(ValueError):
        AdjustmentTable(b"not an elf at all" * 8)
