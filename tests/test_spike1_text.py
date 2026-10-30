"""PAD-869: Spike 1 display text — the game program's lines in
text/strings.tsv on Extract, patched into the card's game ELF on Write
(in place when it fits, else mapped from the ELF's unused .debug_frame into
the text/data hole, the file keeping its size), with the card's .sidx record
for the program refreshed."""

import hashlib
import hmac
import os
import struct

from pinball_decryptor.core import checksums, text_manifest
from pinball_decryptor.plugins.stern import progreloc, sidx as sidx_mod
from pinball_decryptor.plugins.stern import spike1, spike1_text
from pinball_decryptor.plugins.stern.formats import spike1_linux_partitions
from tests import synthetic


def _cstr(raw, va):
    """The C string at *va* in the ELF *raw*, through its PT_LOADs."""
    for v, off, fs, _ms, _fl in progreloc.load_segments(raw):
        if v <= va < v + fs:
            o = off + va - v
            return raw[o:raw.index(b"\0", o)].decode("latin1")
    return None


def _group(raw, i):
    """The five pointers of lang_text group *i* (synthetic layout)."""
    return struct.unpack_from("<5I", raw, 0x1000 + 24 * i)


def _apply(raw, writes):
    buf = bytearray(raw)
    for off, b in writes:
        buf[off:off + len(b)] = b
    assert len(buf) == len(raw)
    return bytes(buf)


def test_scan_offers_growable_lines():
    raw, _vas = synthetic.make_spike1_game_elf()
    rows = {r["original"]: r for r in spike1_text.scan(raw)}
    assert set(rows) == {"SELECT SONG", "BLACK DIAMOND"}
    assert all(r.get("grow") and r["budget"] == 96 for r in rows.values())


def test_scan_without_spare_section_is_in_place_only():
    raw, _vas = synthetic.make_spike1_game_elf(spare=False)
    reloc, _new, why = spike1_text.segment_plan(raw)
    assert reloc is None and "unused section" in why
    rows = {r["original"]: r for r in spike1_text.scan(raw)}
    assert rows["BLACK DIAMOND"].get("fixed")
    assert rows["BLACK DIAMOND"]["budget"] == len("BLACK DIAMOND")


def test_plan_in_place_and_longer_keeps_file_size():
    raw, vas = synthetic.make_spike1_game_elf()
    writes, n = spike1_text.plan(raw, {"SELECT SONG": "PICK",
                                       "BLACK DIAMOND": "A LONGER SONG TITLE"})
    assert n == 2
    new = _apply(raw, writes)
    # in place: same address, new text
    assert set(_group(new, 0)) == {vas["SELECT SONG"]}
    assert _cstr(new, vas["SELECT SONG"]) == "PICK"
    # longer: every language pointer moved into the new segment
    ext = progreloc.extension_segment(new)
    assert ext is not None and ext["seg_off"] == 0x2000
    moved = set(_group(new, 1))
    assert len(moved) == 1
    va = moved.pop()
    assert ext["base_va"] <= va < ext["base_va"] + ext["capacity"]
    assert _cstr(new, va) == "A LONGER SONG TITLE"
    # the segment sits in the text/data hole, read-only, mapped whole
    seg = [s for s in progreloc.load_segments(new) if s[0] == ext["base_va"]]
    assert seg == [(0x9000, 0x2000, ext["capacity"], ext["capacity"], 4)]
    # a second build appends after the first one's text
    again = _apply(new, spike1_text.plan(new, {"PICK": "A SECOND LONGER LINE"})[0])
    ext2 = progreloc.extension_segment(again)
    assert ext2["seg_off"] == ext["seg_off"] and ext2["used"] > ext["used"]
    assert _cstr(again, _group(again, 0)[0]) == "A SECOND LONGER LINE"
    assert _cstr(again, va) == "A LONGER SONG TITLE"


def test_card_extract_and_write_text(tmp_path):
    elf, _vas = synthetic.make_spike1_game_elf()
    card = str(tmp_path / "synth.iso")
    synthetic.make_spike1_card(card, game_elf=elf)
    out_dir = str(tmp_path / "extract")
    os.makedirs(out_dir)
    spike1.extract_all(card, spike1_linux_partitions(card), out_dir)
    checksums.generate_checksums(out_dir)
    rows = text_manifest.load(out_dir)
    assert {r["original"] for r in rows} == {"SELECT SONG", "BLACK DIAMOND"}
    assert {r["path"] for r in rows} == {"/GAME_LE/game"}
    # the Text tab never goes looking for a Spike 2 card behind it
    from pinball_decryptor.plugins.stern import engine
    assert not engine.program_text_needs_refresh(out_dir, rows)

    for r in rows:
        if r["original"] == "BLACK DIAMOND":
            r["replacement"] = "STRUTTER (CUSTOM SONG)"
    text_manifest.save(out_dir, rows)
    out_card = str(tmp_path / "out.iso")
    res = spike1.write_image(card, out_dir, out_card)
    assert res["text"] == 1 and res["audio"] == 0

    with open(out_card, "rb") as f:
        reader, game_dir, _n, _sp, sn = spike1.locate_assets(
            f, spike1_linux_partitions(out_card))
        node = spike1._find_game_elf_node(reader, game_dir)
        new = reader.read_file_bytes(node)
        sdata = reader.read_file_bytes(sn)
    assert len(new) == len(elf)
    assert _cstr(new, _group(new, 1)[0]) == "STRUTTER (CUSTOM SONG)"
    # the card's own validation record covers the patched program
    recs, _crc, _fmt = sidx_mod.parse_records(sdata)
    po = recs["%s/game" % game_dir]
    assert sdata[po + 21:po + 41] == hmac.new(
        sidx_mod.SIDX_KEY, new, hashlib.sha1).digest()
    assert sdata[po + 41:po + 57] == hashlib.md5(new).digest()

    # a re-extract of the built card lists the live line and keeps the edit
    spike1.extract_all(out_card, spike1_linux_partitions(out_card), out_dir)
    rows = {r["original"]: r for r in text_manifest.load(out_dir)}
    assert "STRUTTER (CUSTOM SONG)" in rows
    assert rows["BLACK DIAMOND"]["replacement"] == "STRUTTER (CUSTOM SONG)"


def test_grow_option_off_keeps_longer_text_out(monkeypatch):
    raw, vas = synthetic.make_spike1_game_elf()
    monkeypatch.setenv("PAD_STERN_TEXT_GROW", "0")
    lines = []
    writes, n = spike1_text.plan(raw, {"BLACK DIAMOND": "A LONGER SONG TITLE",
                                       "SELECT SONG": "PICK"},
                                 lambda m, *a: lines.append(m))
    new = _apply(raw, writes)
    assert n == 1 and progreloc.extension_segment(new) is None
    assert _cstr(new, vas["BLACK DIAMOND"]) == "BLACK DIAMOND"
    assert any("option to grow" in m for m in lines)
