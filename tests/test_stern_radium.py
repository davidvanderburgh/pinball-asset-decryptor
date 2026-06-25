"""Tests for the Stern Spike 2 display-text (.radium) Extract + Replace path.

Pure, deterministic pieces only — the radium string enumerator/classifier, the
``text/strings.tsv`` extract manifest, the diff of edited rows, and the
size-neutral in-place patch of every occurrence (driven by a fake ext4 reader
whose file offsets map 1:1 to disk offsets).  No real card needed.

The synthetic radium buffers below reproduce the framing observed on real TMNT /
Metallica cards (verified with the format prototype against
``turtles_pro-1_58_0.Release.8G.sdcard.raw``): a display-text Variant value is
``<f32 x><f32 y><u64 len><body><trailer>`` and is NOT preceded/followed by a
``0x80`` node handle, which is what separates it from named handles.
"""

import struct

from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern import radium


# --------------------------------------------------------------------------
# synthetic radium framing (matches the real on-card layout)
# --------------------------------------------------------------------------
def _variant_str(text):
    """A display-text Variant value: two float32 anchor coords, then the
    8-byte LE length + body, then a plain (non-0x80) trailer."""
    body = text.encode("latin1")
    return (struct.pack("<ff", 2.0, 0.0)            # anchor coords (not 0x80)
            + struct.pack("<Q", len(body)) + body
            + struct.pack("<I", 2))                  # trailer (top byte != 0x80)


def _named_handle(text):
    """A named handle (element/instance id): the 4 bytes immediately before the
    length prefix are a node handle whose top byte is 0x80 -> NOT display text."""
    body = text.encode("latin1")
    return (struct.pack("<I", 0x8000_0001)          # handle, top byte 0x80
            + struct.pack("<Q", len(body)) + body
            + struct.pack("<I", 0))


def _make_radium(display, n_occ):
    """A radium-like buffer: a named handle, then ``n_occ`` copies of a
    display-text Variant value, with filler between so offsets differ."""
    buf = bytearray()
    buf += b"\x00\x00\x00\x80" + struct.pack("<Q", 4) + b"Text"  # element handle
    buf += _named_handle("credits_text")
    for i in range(n_occ):
        buf += b"\x00" * 4                 # filler so each body is at a new offset
        buf += _variant_str(display)
    buf += b"\x00" * 8
    return bytes(buf)


# --------------------------------------------------------------------------
# fake ext4 reader: file offset == disk offset (identity), so a patched copy of
# the buffer can be re-read at the same offsets.
# --------------------------------------------------------------------------
class _FakeReader:
    def __init__(self, files):
        # files: {card_path: bytes}
        self._files = files

    def iter_regular_files(self, min_size=1, max_depth=None):
        for i, (path, data) in enumerate(self._files.items()):
            if len(data) >= min_size:
                yield path, i + 11, {"size": len(data), "_path": path,
                                     "i_block": path.encode()}

    def read_file_bytes(self, node):
        return self._files[node["_path"]]

    def disk_ranges(self, node, file_off, length):
        # identity map (single contiguous run) so the test can patch a bytearray
        # copy at the same offsets and read the value straight back.
        return [(file_off, length)]


# --------------------------------------------------------------------------
# enumerate / classify
# --------------------------------------------------------------------------
def test_enumerate_finds_display_text_and_ignores_handles():
    buf = _make_radium("CLOCK NOT SET", 3)
    ents = radium.enumerate_strings(buf)
    dts = [e for e in ents if e["kind"] == "display-text"]
    assert [e["text"] for e in dts] == ["CLOCK NOT SET"] * 3
    # the named handle is NOT classified display-text
    assert "credits_text" not in [e["text"] for e in dts]
    assert all(e["length"] == len(b"CLOCK NOT SET") for e in dts)
    # offsets are distinct and point at the body bytes
    offs = [e["offset"] for e in dts]
    assert len(set(offs)) == 3
    for off in offs:
        assert buf[off:off + 13] == b"CLOCK NOT SET"


def test_display_texts_helper_filters_kind():
    buf = _make_radium("SHOOT LEFT RAMP", 2)
    dts = radium.display_texts(buf)
    assert len(dts) == 2
    assert all(e["kind"] == "display-text" for e in dts)


# --------------------------------------------------------------------------
# extract manifest: text/strings.tsv (dedup by value)
# --------------------------------------------------------------------------
def test_extract_radium_text_writes_deduped_manifest(tmp_path):
    reader = _FakeReader({
        "/g/scene/a.radium": _make_radium("CLOCK NOT SET", 5),
        "/g/scene/b.radium": _make_radium("PLAYER 1", 2),
        "/g/scene/empty.bin": b"\x00" * 64,         # not a radium -> ignored
    })
    n = engine.extract_radium_text(reader, str(tmp_path))
    assert n == 2                                    # 2 unique strings total

    tsv = tmp_path / "text" / "strings.tsv"
    assert tsv.is_file()
    rows = [ln for ln in tsv.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("#")]
    # one row per (radium, unique string); replacement column left BLANK
    parsed = [ln.split("\t") for ln in rows]
    assert ["/g/scene/a.radium", "CLOCK NOT SET", ""] in parsed
    assert ["/g/scene/b.radium", "PLAYER 1", ""] in parsed
    assert len(parsed) == 2


def test_extract_radium_text_no_radiums_writes_nothing(tmp_path):
    reader = _FakeReader({"/g/x.bin": b"\x00" * 32})
    assert engine.extract_radium_text(reader, str(tmp_path)) == 0
    assert not (tmp_path / "text").exists()


# --------------------------------------------------------------------------
# diff: only edited rows
# --------------------------------------------------------------------------
def _write_tsv(tmp_path, rows):
    d = tmp_path / "text"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["# radium_card_path\toriginal\treplacement"]
    lines += ["\t".join(r) for r in rows]
    (d / "strings.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_changed_radium_text_returns_only_edits(tmp_path):
    _write_tsv(tmp_path, [
        ("/g/a.radium", "CLOCK NOT SET", "GAME OVER MAN"),   # edited (shorter)
        ("/g/a.radium", "PLAYER 1", "PLAYER 1"),             # unchanged
        ("/g/b.radium", "REPLAY", "BONUS"),                  # edited
    ])
    edits = engine._changed_radium_text(str(tmp_path))
    assert edits == {
        "/g/a.radium": [("CLOCK NOT SET", "GAME OVER MAN")],
        "/g/b.radium": [("REPLAY", "BONUS")],
    }


def test_changed_radium_text_no_manifest_is_empty(tmp_path):
    assert engine._changed_radium_text(str(tmp_path)) == {}


# --------------------------------------------------------------------------
# patch builder: size-neutral, all occurrences, reject over-length
# --------------------------------------------------------------------------
def _apply(buf, writes):
    out = bytearray(buf)
    for off, b in writes:
        out[off:off + len(b)] = b
    return bytes(out)


def test_replace_patches_all_occurrences_size_neutral(tmp_path):
    original = "CLOCK NOT SET"
    buf = _make_radium(original, 4)
    reader = _FakeReader({"/g/a.radium": buf})
    _write_tsv(tmp_path, [("/g/a.radium", original, "OK")])

    writes, n, _ov = engine._radium_text_writes(
        reader, str(tmp_path), log=lambda *a, **k: None, cancel=lambda: False)
    assert n == 1
    # one write per occurrence (4), each exactly the original byte length
    assert len(writes) == 4
    assert all(len(b) == len(original) for _o, b in writes)

    patched = _apply(buf, writes)
    assert len(patched) == len(buf)                  # byte-identical length

    # every occurrence now reads back the space-padded replacement
    dts = radium.display_texts(patched)
    assert [e["text"] for e in dts] == ["OK" + " " * (len(original) - 2)] * 4


def test_replace_rejects_over_length(tmp_path):
    original = "REPLAY"
    buf = _make_radium(original, 2)
    reader = _FakeReader({"/g/a.radium": buf})
    _write_tsv(tmp_path, [("/g/a.radium", original, "EXTRA BALL LIT")])  # longer

    msgs = []
    writes, n, _ov = engine._radium_text_writes(
        reader, str(tmp_path),
        log=lambda m, lvl=None: msgs.append((lvl, m)), cancel=lambda: False)
    assert writes == []
    assert n == 0
    assert any(lvl == "warning" for lvl, _m in msgs)
    # buffer untouched -> original still enumerates
    assert [e["text"] for e in radium.display_texts(buf)] == [original] * 2


def test_replace_round_trip_reenumerate_reads_new_value(tmp_path):
    original = "SHOOT LEFT RAMP"
    buf = _make_radium(original, 3)
    reader = _FakeReader({"/g/a.radium": buf})
    _write_tsv(tmp_path, [("/g/a.radium", original, "SHOOT RIGHT")])

    writes, n, _ov = engine._radium_text_writes(
        reader, str(tmp_path), log=lambda *a, **k: None, cancel=lambda: False)
    assert n == 1
    patched = _apply(buf, writes)

    # re-enumerate the patched buffer at the SAME offsets and read back
    new = radium.display_texts(patched)
    expect = "SHOOT RIGHT".ljust(len(original))
    assert [e["text"] for e in new] == [expect] * 3
    # and the original offsets are preserved (size-neutral)
    assert [e["offset"] for e in new] == \
        [e["offset"] for e in radium.display_texts(buf)]


def test_replace_skips_missing_radium(tmp_path):
    reader = _FakeReader({"/g/present.radium": _make_radium("HELLO WORLD", 1)})
    _write_tsv(tmp_path, [("/g/missing.radium", "HELLO WORLD", "BYE WORLD")])
    msgs = []
    writes, n, _ov = engine._radium_text_writes(
        reader, str(tmp_path),
        log=lambda m, lvl=None: msgs.append((lvl, m)), cancel=lambda: False)
    assert writes == [] and n == 0
    assert any(lvl == "warning" for lvl, _m in msgs)


def test_radium_text_writes_emit_digest_overlays(tmp_path):
    """The overlays a text edit returns carry the file-relative new bytes the
    .sidx refresh needs to recompute the radium's digest."""
    original = "CLOCK NOT SET"
    buf = _make_radium(original, 3)
    reader = _FakeReader({"/g/a.radium": buf})
    _write_tsv(tmp_path, [("/g/a.radium", original, "OK")])
    writes, n, ov = engine._radium_text_writes(
        reader, str(tmp_path), log=lambda *a, **k: None, cancel=lambda: False)
    assert n == 1
    # one overlay entry per patched inode (i_block keyed), with one file-offset
    # entry per occurrence — and applying them reproduces the flat disk writes
    # (identity offset map in the fake reader).
    assert set(ov) == {b"/g/a.radium"}
    _node, off_map = ov[b"/g/a.radium"]
    assert len(off_map) == 3
    expect = "OK".encode().ljust(len(original), b" ")
    assert all(v == expect for v in off_map.values())
    assert {off for off, _b in writes} == set(off_map)


def test_compute_sidx_writes_refreshes_radium_record():
    """End-to-end: a scene.radium overlay rewrites that file's .sidx record with
    the HMAC-SHA1 + MD5 of the PATCHED content (covers the radium gap + FINF)."""
    import io
    from pinball_decryptor.plugins.stern import sidx

    radium_content = b"RADIUM-ORIGINAL-CONTENT-" + b"\x00" * 100
    radium_ib, sidx_ib = b"radium-ib", b"sidx-ib"

    # Minimal FINF .sidx: one record for "g/scene.radium".
    paths = b"g/scene.radium\x00"
    body = b"STRS" + struct.pack("<I", len(paths)) + paths
    body += b"FINF" + struct.pack("<I", 60) + bytes(60)
    hdr = bytearray(0x48); hdr[0:4] = b"SIDX"
    struct.pack_into("<I", hdr, 0x34, 0xffffffff)
    sidx_content = bytes(hdr) + body

    R, X = 0, 0x10000                       # disk layout: radium @0, sidx @64K
    disk = io.BytesIO(b"\x00" * (X + len(sidx_content) + 16))
    disk.seek(R); disk.write(radium_content)
    disk.seek(X); disk.write(sidx_content)
    radium_node = {"size": len(radium_content), "i_block": radium_ib, "_b": R}
    sidx_node = {"size": len(sidx_content), "i_block": sidx_ib, "_b": X}

    class FakeReader:
        def iter_regular_files(self, min_size=1, max_depth=None):
            yield "/g/scene.radium", 11, radium_node
            yield "/spk/index/title.sidx", 12, sidx_node
        def read_file_bytes(self, node):
            return disk.getvalue()[node["_b"]:node["_b"] + node["size"]]
        def disk_ranges(self, node, off, length):
            return [(node["_b"] + off, length)]

    new = b"PATCHED!"
    overlay = {radium_ib: (radium_node, {0: new})}
    writes = engine._compute_sidx_writes(
        FakeReader(), disk, None, {}, [], [], overlay, lambda *a, **k: None)
    assert writes, "expected the radium record to be refreshed"

    # Apply the writes and confirm the record now holds the PATCHED digest.
    patched = bytearray(radium_content); patched[0:len(new)] = new
    exp_h, exp_m = sidx.digests(bytes(patched))
    recs, _crc, fmt = sidx.parse_records(sidx_content)
    po = recs["g/scene.radium"]
    buf = bytearray(disk.getvalue())
    for d, b in writes:
        buf[d:d + len(b)] = b
    rec = bytes(buf[X + po:X + po + 60])
    assert fmt == "FINF"
    assert rec[21:41] == exp_h
    assert rec[41:57] == exp_m
