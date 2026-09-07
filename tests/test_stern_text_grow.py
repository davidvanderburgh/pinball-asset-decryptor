"""Tests for delivering LONGER display text than the original: a grown game
ELF (program strings placed in an appended read-only PT_LOAD) and a grown
``scene.radium`` (re-serialised at the new length).

``plans/spike2_longer_program_text.md`` proved the ELF mechanism under qemu;
what is under test here is the CARD side, ``engine``:

* the extension-segment allocator generalised from the blip-free cave stays
  byte-identical for the cave and gives program text a read-only segment in
  the text/data hole only (never above .bss);
* the ``PADTXT01`` header names the segment for a later Write, which EXTENDS
  it (used grows, no second program header spent);
* a text-only Write with a too-long edit yields a staged 0755 firmware whose
  repurposed PT_GNU_STACK is a PT_LOAD(R) in the hole, the grow job LAST,
  the ``.sidx`` record carrying the new length, and NO in-place firmware
  write (the validator bypass is baked into the staged file);
* when the cave already spent PT_GNU_STACK the text takes PT_NOTE;
* Direct-SD and ``PAD_STERN_TEXT_GROW=0`` degrade to today's in-place rule
  with one line saying why, same-length edits still landing;
* a radium whose text outgrew its slot is re-serialised (its other in-place
  edits folded in first), staged whole, its ``.sidx`` size refreshed, and
  its in-place writes dropped; the repo's parsers agree the grown scene is
  the stock one shifted.
"""

import hashlib
import hmac
import io
import os
import struct

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.core import ext4_grow, text_manifest       # noqa: E402
from pinball_decryptor.plugins.stern import (                     # noqa: E402
    engine, progreloc, radium, radium_grow, sidx)
from pinball_decryptor.plugins.stern.explorer import S_IFREG      # noqa: E402
from tests.test_stern_radium import _make_radium                  # noqa: E402
from tests.test_stern_valpatch import _stub_sidx                  # noqa: E402

PAGE = 0x1000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x8000, 0x1000, 0x1000
HOLE = 0x3000                                  # 3 free pages after .text
DATA_VA, DATA_OFF, DATA_SZ = TEXT_VA + TEXT_SZ + HOLE, 0x2000, 0x1000
DATA_MEMSZ = 0x1800                            # .bss after the file bytes
PT_GNU_STACK = engine._PT_GNU_STACK
PT_NOTE = engine._PT_NOTE

TITLE = "GODZILLA VS EBIRAH"                    # 5-group at +0, tail group +12
AWARD = "JACKPOT AWARD!"                        # one lone pointer word
PRESS = "PRESS START"                           # no reference at all

FW_PATH = "/gz/game"
RAD_PATH = "/gz/assets/a/scene.radium"
SIDX_PATH = "/spk/index/a.sidx"


def _grow_elf(with_note=True):
    """A minimal ARM ET_EXEC: a NOP ``.text`` LOAD, a data LOAD one hole
    away holding the strings and their pointers, PT_GNU_STACK (and PT_NOTE),
    a section table naming ``.text`` (what the validator finder reads) and a
    20-byte trailer after it, as the real firmwares carry.  Returns
    ``(raw, offsets)``."""
    phdrs = [(1, TEXT_OFF, TEXT_VA, TEXT_SZ, TEXT_SZ, 5),
             (1, DATA_OFF, DATA_VA, DATA_SZ, DATA_MEMSZ, 6),
             (PT_GNU_STACK, 0, 0, 0, 0, 7)]
    if with_note:
        phdrs.append((PT_NOTE, 0x148, TEXT_VA + 0x148, 0x44, 0x44, 4))
    raw = bytearray(DATA_OFF + DATA_SZ)
    raw[0:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", raw, 0x10, 2)              # ET_EXEC
    struct.pack_into("<H", raw, 0x12, 40)             # EM_ARM
    struct.pack_into("<I", raw, 0x1c, 0x34)           # e_phoff
    struct.pack_into("<H", raw, 0x2a, 32)             # e_phentsize
    struct.pack_into("<H", raw, 0x2c, len(phdrs))     # e_phnum
    for i, (t, off, va, fz, mz, fl) in enumerate(phdrs):
        struct.pack_into("<8I", raw, 0x34 + i * 32, t, off, va, va, fz, mz,
                         fl, PAGE)
    # .text: NOPs
    for o in range(TEXT_OFF, TEXT_OFF + TEXT_SZ, 4):
        struct.pack_into("<I", raw, o, 0xE1A00000)
    # data: strings then the pointer words
    body = bytearray(b"\x00")
    offs = {}
    for s in (TITLE, AWARD, PRESS):
        offs[s] = DATA_OFF + len(body)
        body += s.encode() + b"\x00"
    while len(body) % 4:
        body += b"\x00"

    def va(s, d=0):
        return DATA_VA + (offs[s] - DATA_OFF) + d

    offs["grp_title"] = DATA_OFF + len(body)
    body += struct.pack("<5I", *([va(TITLE)] * 5)) + b"\x00" * 4
    offs["grp_tail"] = DATA_OFF + len(body)
    body += struct.pack("<5I", *([va(TITLE, 12)] * 5)) + b"\x00" * 4
    offs["lone_award"] = DATA_OFF + len(body)
    body += struct.pack("<I", va(AWARD)) + b"\x00" * 4
    raw[DATA_OFF:DATA_OFF + len(body)] = body
    # section table + trailer after every LOAD's bytes
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = len(raw)
    raw += shstr
    sh_off = len(raw)
    struct.pack_into("<I", raw, 0x20, sh_off)         # e_shoff
    struct.pack_into("<H", raw, 0x2e, 40)             # e_shentsize
    struct.pack_into("<H", raw, 0x30, 3)              # e_shnum
    struct.pack_into("<H", raw, 0x32, 2)              # e_shstrndx

    def sh(name, addr, off, size):
        return struct.pack("<10I", name, 1, 0, addr, off, size, 0, 0, 4, 0)

    raw += (sh(0, 0, 0, 0) + sh(1, TEXT_VA, TEXT_OFF, TEXT_SZ)
            + sh(7, 0, shstr_off, len(shstr)))
    raw += b"T" * 20                                  # the trailer
    offs["va"] = va
    return bytes(raw), offs


def _phdrs(raw):
    return progreloc.iter_phdrs(raw)


def _loads(raw):
    return [p for p in _phdrs(raw) if p[1] == 1]


def _word(raw, off):
    return struct.unpack_from("<I", raw, off)[0]


class _CardReader:
    """The slice of Ext4Reader the text path touches: a firmware, a .sidx
    manifest and (optionally) one scene, each mapped 1:1 onto a flat disk."""

    base = 0
    FW_DISK, SIDX_DISK, RAD_DISK = 0x10000, 0x80000, 0x100000

    def __init__(self, elf, sidx_blob, radium_bytes=None):
        def node(data, disk, ib):
            return {"i_block": ib, "size": len(data), "mode": S_IFREG,
                    "_data": data, "_disk": disk}
        self.fw_node = node(elf, self.FW_DISK, b"\x01" * 60)
        self.sidx_node = node(sidx_blob, self.SIDX_DISK, b"\x02" * 60)
        self.rad_node = (node(radium_bytes, self.RAD_DISK, b"\x03" * 60)
                         if radium_bytes is not None else None)

    def find_spike_assets(self):
        return 2, 3

    def read_inode(self, ino):
        return {3: self.fw_node, 4: self.sidx_node, 5: self.rad_node}[ino]

    def read_file_bytes(self, node):
        return node["_data"]

    def peek(self, node, n=16):
        return node["_data"][:n]

    def disk_ranges(self, node, off, length):
        if off + length > node["size"]:
            raise ValueError("past the end of the file")
        return [(node["_disk"] + off, length)]

    def iter_regular_files(self, min_size=1, max_depth=20):
        yield FW_PATH, 3, self.fw_node
        yield SIDX_PATH, 4, self.sidx_node
        if self.rad_node is not None:
            yield RAD_PATH, 5, self.rad_node

    def is_arm_elf(self, node):
        return node is self.fw_node

    def extract_file(self, node, out_path, progress=None):
        with open(out_path, "wb") as f:
            f.write(node["_data"])


def _card(monkeypatch, reader):
    """Point the orchestrator at *reader*: no real card, a host that CAN
    grow ext4 files, chmod calls recorded."""
    monkeypatch.setattr(engine, "_locate",
                        lambda f, p: (reader, reader.fw_node, None))
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 1 << 30)])
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    chmods = []
    real_chmod = os.chmod

    def rec(path, mode, *a, **k):
        chmods.append((os.path.basename(path), mode))
        return real_chmod(path, mode, *a, **k)
    monkeypatch.setattr(os, "chmod", rec)
    return chmods


def _manifest(assets, rows):
    text_manifest.save(str(assets), [
        {"path": p, "original": o, "replacement": r, "budget": 96, "grow": True}
        for p, o, r in rows])


def _capture():
    msgs = []
    return msgs, lambda m, lvl="info": msgs.append((lvl, m))


def _compute(assets, log, dest_is_device=False):
    return engine._compute_patches(
        io.BytesIO(b""), [], str(assets), log=log, progress=None,
        cancel=lambda: False, dest_is_device=dest_is_device)


def _sidx_record(blob, writes, path, disk_base):
    """The record for *path* after the .sidx writes in *writes* land."""
    recs, _crc, fmt = sidx.parse_records(blob)
    buf = bytearray(blob)
    for d, b in writes:
        if disk_base <= d < disk_base + len(blob):
            buf[d - disk_base:d - disk_base + len(b)] = b
    po = recs[path]
    packfmt, o1, o2 = sidx._SIZE_FIELDS[fmt]
    return {"size": struct.unpack_from(packfmt, buf, po + o1)[0],
            "size2": struct.unpack_from(packfmt, buf, po + o2)[0],
            "hmac": bytes(buf[po + 21:po + 41]) if fmt == "FINF"
            else bytes(buf[po + 32:po + 52]),
            "fmt": fmt, "buf": bytes(buf), "po": po}


def _writes_in(writes, lo, size):
    return [(d, b) for d, b in writes if lo <= d < lo + size]


# ---------------------------------------------------------------------------
# the allocator
# ---------------------------------------------------------------------------

def test_cave_placement_is_byte_identical_to_before():
    """The cave is the generalised allocator with its old arguments: same
    bytes, same VA, same entry-branch reach."""
    from tests.test_stern_audio_tail import _fake_elf
    a, _te, _dv = _fake_elf()
    b = bytearray(a)
    cave = engine._append_cave_segment(a, 1195, fn=0x9000)
    gen = engine._append_extension_segment(b, 1195, 7, near_fn=0x9000,
                                           allow_above=True, what="cave")
    assert cave == gen
    assert bytes(a) == bytes(b)


def test_text_segment_is_read_only_and_hole_only():
    raw, _offs = _grow_elf()
    buf = bytearray(raw)
    va, off, gap = engine._append_extension_segment(
        buf, 100, 4, near_fn=None, allow_above=False,
        slots=(PT_GNU_STACK, PT_NOTE))
    assert va == TEXT_VA + TEXT_SZ                  # the first hole page
    assert gap == HOLE
    assert off % PAGE == 0 and off + PAGE == len(buf)
    ours = [p for p in _loads(buf) if p[3] == va]
    assert len(ours) == 1
    _o, _t, p_off, _va, fz, mz, fl, _al = ours[0]
    assert (p_off, fz, mz, fl) == (off, PAGE, PAGE, 4)
    # PT_GNU_STACK was the slot spent; PT_NOTE is untouched.
    assert not any(p[1] == PT_GNU_STACK for p in _phdrs(buf))
    assert any(p[1] == PT_NOTE for p in _phdrs(buf))
    # A need the hole can't hold is refused rather than placed above .bss,
    # where the cave would have gone.
    with pytest.raises(RuntimeError, match="fits a"):
        engine._append_extension_segment(bytearray(raw), HOLE + 1, 4,
                                         allow_above=False)
    engine._append_extension_segment(bytearray(raw), HOLE + 1, 7,
                                     allow_above=True)     # the cave may


def test_find_and_extend_the_text_segment():
    raw, _offs = _grow_elf()
    assert engine._find_extension_segment(raw) is None
    cave = bytearray(raw)
    engine._append_cave_segment(cave, 500, fn=TEXT_VA)
    assert engine._find_extension_segment(cave) is None    # no header: cave only

    buf = bytearray(raw)
    va, off, _gap = engine._append_extension_segment(
        buf, 12 + 20, 4, allow_above=False)
    buf[off:off + 12] = progreloc.extension_header(12 + 20)
    buf[off + 12:off + 32] = b"A" * 20
    assert engine._find_extension_segment(buf) == (va, off, PAGE, 32)
    # Extending within the page changes nothing; past it grows the segment
    # in place (still at EOF, p_filesz == p_memsz) and the header is kept.
    assert engine._extend_extension_segment(buf, 100) == (va, off, PAGE, 32)
    va2, off2, size2, used2 = engine._extend_extension_segment(buf, PAGE)
    assert (va2, off2, size2, used2) == (va, off, 2 * PAGE, 32)
    assert len(buf) == off + 2 * PAGE
    seg = [p for p in _loads(buf) if p[3] == va][0]
    assert seg[4] == seg[5] == 2 * PAGE
    assert engine._find_extension_segment(buf) == (va, off, 2 * PAGE, 32)
    # ...but never into the data segment's address space.
    with pytest.raises(RuntimeError, match="in the way"):
        engine._extend_extension_segment(buf, HOLE)


# ---------------------------------------------------------------------------
# the Write: a grown game ELF
# ---------------------------------------------------------------------------

def test_text_only_write_stages_a_grown_firmware(tmp_path, monkeypatch):
    raw, offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    reader = _CardReader(raw, blob)
    chmods = _card(monkeypatch, reader)
    assets = tmp_path / "assets"
    new_title = "GODZILLA VS BIOLLANTE"
    _manifest(assets, [(FW_PATH, TITLE, new_title),
                       (FW_PATH, "EBIRAH", "BIOLLANTE")])
    msgs, log = _capture()

    writes, counts, grow_plan, _audio, valpatch_mode = _compute(assets, log)

    assert counts == (0, 0, 0, 2)                 # the line and its tail
    # The firmware grow job, and it is the last (here the only) job.
    assert grow_plan is not None
    assert [rel for rel, _src in grow_plan["jobs"]] == ["gz/game"]
    staged = grow_plan["jobs"][-1][1]
    assert os.path.isfile(staged)
    assert grow_plan["cleanup"] and staged.startswith(grow_plan["cleanup"])
    assert ("game_text_grown", 0o755) in chmods
    grown = open(staged, "rb").read()
    assert len(grown) > len(raw) and grown[:len(raw) - 20] != raw[:len(raw) - 20]

    # phdr[2] (the PT_GNU_STACK slot) is now a PT_LOAD, R, in the hole,
    # backing a page-aligned payload at EOF that starts with the header.
    ph = _phdrs(grown)
    assert not any(p[1] == PT_GNU_STACK for p in ph)
    assert any(p[1] == PT_NOTE for p in ph)                  # not spent
    _o, t, p_off, p_va, fz, mz, fl, _al = ph[2]
    assert t == 1 and fl == 4 and fz == mz == PAGE
    assert TEXT_VA + TEXT_SZ <= p_va < DATA_VA and p_va % PAGE == 0
    assert p_off % PAGE == 0 and p_off + fz == len(grown)
    seg = engine._find_extension_segment(grown)
    assert seg == (p_va, p_off, PAGE, 12 + len(new_title) + 1)
    payload = grown[p_off + 12:p_off + seg[3]]
    assert payload == new_title.encode() + b"\x00"
    # The original bytes stay; every reference now points at the copy.
    assert grown[offs[TITLE]:offs[TITLE] + len(TITLE)] == TITLE.encode()
    copy_va = p_va + 12
    for k in range(5):
        assert _word(grown, offs["grp_title"] + 4 * k) == copy_va
        assert _word(grown, offs["grp_tail"] + 4 * k) == copy_va + 12
    assert _word(grown, offs["lone_award"]) == offs["va"](AWARD)  # untouched
    # The section table and trailer are intact where they were.
    assert grown[len(raw) - 20:len(raw)] == b"T" * 20

    # No in-place write touches the firmware: not the strings (relocated),
    # not the validator bypass (baked into the staged file).
    assert _writes_in(writes, reader.FW_DISK, len(raw)) == []
    assert valpatch_mode is not None
    # The .sidx record describes the staged file: its length and digests.
    rec = _sidx_record(blob, writes, "gz/game", reader.SIDX_DISK)
    assert rec["size"] == rec["size2"] == len(grown)
    want_h = hmac.new(sidx.SIDX_KEY, grown, hashlib.sha1).digest()
    want_m = hashlib.md5(grown).digest()
    by_disk = dict(writes)
    recs, _crc, fmt = sidx.parse_records(blob)
    for foff, b in sidx.record_field_writes(recs["gz/game"], want_h, want_m,
                                            fmt, size=len(grown)):
        assert by_disk[reader.SIDX_DISK + foff] == b
    assert any("placed in new space" in m or "extension segment" in m
               for _l, m in msgs)


def test_second_write_extends_the_segment(tmp_path, monkeypatch):
    """A Write onto an already-grown ELF appends after its used part: the
    header's count grows, the segment stays the one PT_LOAD, PT_NOTE is not
    spent."""
    raw, offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    _card(monkeypatch, _CardReader(raw, blob))
    assets = tmp_path / "assets"
    _manifest(assets, [(FW_PATH, TITLE, "GODZILLA VS BIOLLANTE"),
                       (FW_PATH, "EBIRAH", "BIOLLANTE")])
    _m, log = _capture()
    _w, _c, plan1, _a, _v = _compute(assets, log)
    first = open(plan1["jobs"][-1][1], "rb").read()
    seg1 = engine._find_extension_segment(first)
    assert seg1 is not None

    # Second Write: the card now carries the grown ELF; another long edit.
    reader2 = _CardReader(first, blob)
    _card(monkeypatch, reader2)
    assets2 = tmp_path / "assets2"
    new_award = "SUPER JACKPOT AWARD!"
    _manifest(assets2, [(FW_PATH, AWARD, new_award)])
    _m2, log2 = _capture()
    writes2, counts2, plan2, _a2, _v2 = _compute(assets2, log2)
    assert counts2 == (0, 0, 0, 1)
    second = open(plan2["jobs"][-1][1], "rb").read()
    seg2 = engine._find_extension_segment(second)
    assert seg2[:2] == seg1[:2]                              # same segment
    assert seg2[3] > seg1[3]                                 # used grew
    assert len([p for p in _loads(second)]) == len(_loads(first)) == 3
    assert any(p[1] == PT_NOTE for p in _phdrs(second))
    assert progreloc.extension_segment(second)["used"] == seg2[3]
    # the second string sits after the first, 4-aligned, and is referenced
    va, off, _size, used = seg2
    tail = second[off + seg1[3]:off + used]
    assert tail.lstrip(b"\x00") == new_award.encode() + b"\x00"
    copy_va = va + used - len(new_award) - 1
    assert _word(second, offs["lone_award"]) == copy_va
    assert second[offs[AWARD]:offs[AWARD] + len(AWARD)] == AWARD.encode()
    # the first string's copy and its pointers survived the second write
    assert second[off + 12:off + 12 + len("GODZILLA VS BIOLLANTE")] == \
        b"GODZILLA VS BIOLLANTE"
    assert _word(second, offs["grp_title"]) == va + 12
    rec = _sidx_record(blob, writes2, "gz/game", reader2.SIDX_DISK)
    assert rec["size"] == len(second)


def test_direct_sd_degrades_and_same_length_edits_still_land(tmp_path,
                                                             monkeypatch):
    raw, offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    reader = _CardReader(raw, blob)
    _card(monkeypatch, reader)
    assets = tmp_path / "assets"
    same = "PUSH  START"                                     # 11 == 11
    _manifest(assets, [(FW_PATH, TITLE, "GODZILLA VS BIOLLANTE"),
                       (FW_PATH, "EBIRAH", "BIOLLANTE"),
                       (FW_PATH, PRESS, same)])
    msgs, log = _capture()
    writes, counts, grow_plan, _a, _v = _compute(assets, log,
                                                 dest_is_device=True)
    assert grow_plan is None
    assert counts == (0, 0, 0, 1)
    assert any(l == "warning" and "direct-SD" in m for l, m in msgs)
    assert any(l == "warning" and "BIOLLANTE" in m and "skipped" in m
               for l, m in msgs)
    fw_writes = _writes_in(writes, reader.FW_DISK, len(raw))
    assert (reader.FW_DISK + offs[PRESS],
            same.encode().ljust(len(PRESS), b"\x00")) in fw_writes
    assert not os.environ.get("PAD_STERN_TEXT_GROW") == "0"


def test_kill_switch_degrades_with_its_name(tmp_path, monkeypatch):
    raw, _offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    _card(monkeypatch, _CardReader(raw, blob))
    monkeypatch.setenv("PAD_STERN_TEXT_GROW", "0")
    assets = tmp_path / "assets"
    _manifest(assets, [(FW_PATH, TITLE, "GODZILLA VS BIOLLANTE"),
                       (FW_PATH, "EBIRAH", "BIOLLANTE"),
                       (FW_PATH, PRESS, "PUSH  START")])
    msgs, log = _capture()
    _w, counts, grow_plan, _a, _v = _compute(assets, log)
    assert grow_plan is None and counts == (0, 0, 0, 1)
    assert any("PAD_STERN_TEXT_GROW=0" in m for _l, m in msgs)


def test_gate_is_not_probed_for_same_length_edits(tmp_path, monkeypatch):
    """A write of fitting edits never reaches for the ext4 probe (WSL)."""
    raw, _offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    _card(monkeypatch, _CardReader(raw, blob))

    def boom():
        raise AssertionError("ext4_grow.available() must not be called")
    monkeypatch.setattr(ext4_grow, "available", boom)
    assets = tmp_path / "assets"
    _manifest(assets, [(FW_PATH, PRESS, "PUSH  START")])
    _m, log = _capture()
    _w, counts, grow_plan, _a, _v = _compute(assets, log)
    assert grow_plan is None and counts == (0, 0, 0, 1)


def test_with_the_cave_present_the_text_takes_pt_note(tmp_path, monkeypatch):
    """The cave spent PT_GNU_STACK; the strings get a segment of their own
    through PT_NOTE, in the hole, and the cave's bytes are untouched."""
    raw, offs = _grow_elf()
    cave = bytearray(raw)
    cave_va, cave_off, _gap = engine._append_cave_segment(cave, 500,
                                                          fn=TEXT_VA)
    cave[cave_off:cave_off + 500] = b"C" * 500
    staged = tmp_path / "game_real_pathA"
    staged.write_bytes(bytes(cave))
    _card(monkeypatch, _CardReader(raw, _stub_sidx(["gz/game"])))
    msgs, log = _capture()
    grow = {"ok": True, "why": "", "dir": str(tmp_path)}
    writes, n, ov, grown = engine._program_text_writes(
        None, {"i_block": b"\x01" * 60, "size": len(raw)}, FW_PATH,
        [(TITLE, "GODZILLA VS BIOLLANTE"), ("EBIRAH", "BIOLLANTE")],
        str(staged), log, grow=grow)
    assert writes == [] and ov == {} and n == 2
    assert grown["path"] == str(staged) and grown["new"] is False
    assert grown["valpatch_mode"] is None            # the cave's build owns it
    out = staged.read_bytes()
    ph = _phdrs(out)
    assert not any(p[1] in (PT_GNU_STACK, PT_NOTE) for p in ph)
    loads = _loads(out)
    assert len(loads) == 4
    text_seg = engine._find_extension_segment(out)
    assert text_seg is not None
    va, off, size, used = text_seg
    assert TEXT_VA + TEXT_SZ <= va < DATA_VA and va != cave_va
    assert [p for p in loads if p[3] == va][0][6] == 4
    assert out[cave_off:cave_off + 500] == b"C" * 500
    cave_seg = [p for p in loads if p[3] == cave_va][0]
    assert cave_seg[6] == 7
    assert off + size == len(out)
    assert _word(out, offs["grp_title"]) == va + 12


# ---------------------------------------------------------------------------
# the Write: a grown scene.radium
# ---------------------------------------------------------------------------

def test_radium_grow_reserialises_and_parsers_agree():
    buf = _make_radium("REPLAY", 3)
    new, occ, shift = radium_grow.grow(buf, {"REPLAY": "EXTRA BALL LIT"})
    assert occ == {"REPLAY": 3}
    assert len(new) == len(buf) + 3 * (len("EXTRA BALL LIT") - len("REPLAY"))
    assert [e["text"] for e in radium.display_texts(new)] == \
        ["EXTRA BALL LIT"] * 3
    old = radium.display_texts(buf)
    assert [shift(e["prefix_offset"]) for e in old] == \
        [e["prefix_offset"] for e in radium.display_texts(new)]
    bad, _stats = radium_grow.agree(buf, new, {"REPLAY": "EXTRA BALL LIT"},
                                    shift)
    assert bad == []


def test_radium_grow_agrees_on_a_scene_with_fonts_and_layout():
    from tests.test_stern_scene_layout_edits import AWARD as LINES, _scene
    buf = _scene(LINES)
    edits = {"AWARD": "AWARD GROWN LONGER"}
    new, occ, shift = radium_grow.grow(buf, edits)
    assert occ == {"AWARD": 2}
    bad, stats = radium_grow.agree(buf, new, edits, shift)
    assert bad == []
    assert stats["layout_texts"] == 2


def test_write_grows_a_radium_and_the_firmware_goes_last(tmp_path,
                                                          monkeypatch):
    raw, _offs = _grow_elf()
    rad = _make_radium("REPLAY", 2)
    blob = _stub_sidx(["gz/game", "gz/assets/a/scene.radium",
                       "spk/index/a.sidx"])
    reader = _CardReader(raw, blob, rad)
    _card(monkeypatch, reader)
    assets = tmp_path / "assets"
    _manifest(assets, [(RAD_PATH, "REPLAY", "EXTRA BALL LIT"),
                       (FW_PATH, TITLE, "GODZILLA VS BIOLLANTE"),
                       (FW_PATH, "EBIRAH", "BIOLLANTE")])
    msgs, log = _capture()
    writes, counts, grow_plan, _a, _v = _compute(assets, log)
    assert counts == (0, 0, 0, 3)
    rels = [rel for rel, _s in grow_plan["jobs"]]
    assert rels == ["gz/assets/a/scene.radium", "gz/game"]   # firmware LAST
    assert grow_plan["n_video"] == 0
    staged = grow_plan["jobs"][0][1]
    shipped = open(staged, "rb").read()
    want, _occ, _shift = radium_grow.grow(rad, {"REPLAY": "EXTRA BALL LIT"})
    assert shipped == want
    assert [e["text"] for e in radium.display_texts(shipped)] == \
        ["EXTRA BALL LIT"] * 2
    # Nothing patched the scene in place, and its record carries the length.
    assert _writes_in(writes, reader.RAD_DISK, len(rad)) == []
    rec = _sidx_record(blob, writes, "gz/assets/a/scene.radium",
                       reader.SIDX_DISK)
    assert rec["size"] == rec["size2"] == len(shipped)
    assert any("re-serialised" in m for _l, m in msgs)


def test_grown_radium_folds_in_its_colour_edit(tmp_path, monkeypatch):
    """A scene that both grows and is recoloured ships ONE file: the colour
    bytes (computed at stock offsets) go in before the text is grown."""
    from pinball_decryptor.plugins.stern import scene_layout, text_colors
    from tests.test_stern_scene_layout_edits import AWARD as LINES, _scene
    raw, _offs = _grow_elf()
    scene = _scene(LINES)
    blob = _stub_sidx(["gz/game", "gz/assets/a/scene.radium",
                       "spk/index/a.sidx"])
    reader = _CardReader(raw, blob, scene)
    _card(monkeypatch, reader)
    assets = tmp_path / "assets"
    _manifest(assets, [(RAD_PATH, "AWARD", "AWARD GROWN LONGER")])
    imgs = engine.parse_radium_images(scene)
    tables = radium.parse_glyph_tables(scene, imgs)
    stock = scene_layout.text_color_offsets(scene, imgs, tables)["AWARD"]
    from_rgb = tuple(int(round(c * 255)) for c in stock[0][1][:3])
    to_rgb = (12, 34, 56)
    assert from_rgb != to_rgb
    text_colors.set_color(str(assets), RAD_PATH, "AWARD", from_rgb, to_rgb)
    msgs, log = _capture()
    writes, counts, grow_plan, _a, _v = _compute(assets, log)
    assert counts[3] == 2                                   # text + colour
    assert [rel for rel, _s in grow_plan["jobs"]] == ["gz/assets/a/scene.radium"]
    shipped = open(grow_plan["jobs"][0][1], "rb").read()
    imgs2 = engine.parse_radium_images(shipped)
    tables2 = radium.parse_glyph_tables(shipped, imgs2)
    got = scene_layout.text_color_offsets(shipped, imgs2, tables2)
    assert "AWARD GROWN LONGER" in got and "AWARD" not in got
    assert all(tuple(int(round(c * 255)) for c in rgba[:3]) == to_rgb
               for _off, rgba in got["AWARD GROWN LONGER"])
    assert _writes_in(writes, reader.RAD_DISK, len(scene)) == []


def test_radium_too_long_without_growth_is_the_old_warning(tmp_path,
                                                            monkeypatch):
    raw, _offs = _grow_elf()
    rad = _make_radium("REPLAY", 2)
    blob = _stub_sidx(["gz/game", "gz/assets/a/scene.radium",
                       "spk/index/a.sidx"])
    _card(monkeypatch, _CardReader(raw, blob, rad))
    assets = tmp_path / "assets"
    _manifest(assets, [(RAD_PATH, "REPLAY", "EXTRA BALL LIT"),
                       (RAD_PATH, "REPLAY", "REPLAY")])
    msgs, log = _capture()
    with pytest.raises(RuntimeError, match="Nothing could be written"):
        _compute(assets, log, dest_is_device=True)
    assert any(l == "warning" and "direct-SD" in m for l, m in msgs)
    assert any(l == "warning" and "only 6" in m for l, m in msgs)


# ---------------------------------------------------------------------------
# write_overrides carries the grown files whole
# ---------------------------------------------------------------------------

def test_write_overrides_ships_the_grown_firmware_whole(tmp_path, monkeypatch):
    from tests._ext4_fake import make_mbr
    raw, offs = _grow_elf()
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    reader = _CardReader(raw, blob)
    _card(monkeypatch, reader)
    img = tmp_path / "card.raw"
    img.write_bytes(make_mbr([(0x83, 64, 4096)]) + b"\x00" * (0x90000))
    assets = tmp_path / "assets"
    _manifest(assets, [(FW_PATH, TITLE, "GODZILLA VS BIOLLANTE"),
                       (FW_PATH, "EBIRAH", "BIOLLANTE")])
    out = tmp_path / "ovr"
    counts, _mode, _val, files = engine.write_overrides(
        str(img), str(assets), str(out))
    assert counts == (0, 0, 0, 2)
    names = dict(files)
    assert FW_PATH in names and SIDX_PATH in names
    shipped = (out / "gz" / "game").read_bytes()
    assert names[FW_PATH] == len(shipped) > len(raw)
    assert engine._find_extension_segment(shipped) is not None
    assert _word(shipped, offs["grp_title"]) != offs["va"](TITLE)
