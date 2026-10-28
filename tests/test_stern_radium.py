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

    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
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
    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
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

    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
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
    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
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
    writes, n, ov, _fw, _grown = engine._radium_text_writes(
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


def test_re_extract_keeps_the_edits_already_in_the_manifest(tmp_path):
    """David (2026-09-07): his Godzilla LE manifest predates the 'grows'
    budgets and needs a Text re-extract to pick them up -- which used to
    blank every replacement.  A re-extract now rewrites budgets and flags
    from the card but carries the typed replacements over by (scene,
    original); a row no longer on the card drops out."""
    from pinball_decryptor.core import text_manifest
    reader = _FakeReader({
        "/g/scene/a.radium": _make_radium("CLOCK NOT SET", 5),
        "/g/scene/b.radium": _make_radium("PLAYER 1", 2),
    })
    assert engine.extract_radium_text(reader, str(tmp_path)) == 2
    rows = text_manifest.load(str(tmp_path))
    for r in rows:
        if r["original"] == "CLOCK NOT SET":
            r["replacement"] = "CLOCK IS NOT SET YET"
    rows.append({"path": "/g/scene/gone.radium", "original": "OLD",
                 "replacement": "NEW"})
    text_manifest.save(str(tmp_path), rows)

    assert engine.extract_radium_text(reader, str(tmp_path)) == 2
    again = {(r["path"], r["original"]): r["replacement"]
             for r in text_manifest.load(str(tmp_path))}
    assert again[("/g/scene/a.radium", "CLOCK NOT SET")] ==         "CLOCK IS NOT SET YET"
    assert again[("/g/scene/b.radium", "PLAYER 1")] == ""
    assert ("/g/scene/gone.radium", "OLD") not in again


def test_replace_finds_a_line_broken_original_flattened_in_the_manifest(tmp_path):
    """PAD-382 (DragonRR): strings.tsv holds "A B\nC D" as "A B C D"; Write
    still finds it and keeps the break where the words around it stayed."""
    original = "JET JAGUAR\nVS. GIGAN"
    buf = _make_radium(original, 2)
    reader = _FakeReader({"/g/a.radium": buf})
    _write_tsv(tmp_path, [("/g/a.radium", "JET JAGUAR VS. GIGAN", "JET JAGUAR VS. OMEGA")])
    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
        reader, str(tmp_path), log=lambda *a, **k: None, cancel=lambda: False)
    assert n == 1 and len(writes) == 2
    dts = radium.display_texts(_apply(buf, writes))
    assert [e["text"] for e in dts] == ["JET JAGUAR\nVS. OMEGA"] * 2


# --------------------------------------------------------------------------
# PAD-795: the anchored find_strings returns exactly what the byte-at-a-time
# scan did
# --------------------------------------------------------------------------
def _find_strings_per_byte(data):
    """find_strings as it was before PAD-795: every offset tried in turn."""
    n = len(data)
    out = []
    i = 0
    while i + 8 <= n:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 1 <= ln <= radium.MAXLEN and i + 8 + ln <= n:
            body = data[i + 8:i + 8 + ln]
            if all(32 <= b < 127 or b in (9, 10, 13) for b in body):
                out.append((i, i + 8, ln, body))
                i += 8 + ln
                continue
        i += 1
    return out


def _lp(text, ln=None):
    body = text if isinstance(text, bytes) else text.encode("latin1")
    return struct.pack("<Q", len(body) if ln is None else ln) + body


def test_find_strings_matches_the_per_byte_scan_on_crafted_data():
    cases = [
        b"",
        b"\x00" * 7,
        b"\x00" * 8,
        b"\x00" * 300,
        _lp("hello"),
        _lp("hello") + b"\x00" * 3,
        # a hit whose body holds another candidate prefix (skipped past)
        _lp(_lp("inner").decode("latin1").replace("\x00", " ").encode("latin1")),
        _lp("abc" + "\x00" * 0) + _lp("x"),
        # overlapping candidates: a long zero run then text, lengths 0 / 1
        b"\x00" * 20 + _lp("A", 1) + _lp("", 0) + b"zz",
        # lengths at and past the limit
        _lp("Q" * radium.MAXLEN),
        _lp("Q" * (radium.MAXLEN + 1)),
        _lp("Q" * 10, 8193),
        # a length that runs past the end of the data
        _lp("short", 9),
        # a string at the very end, and a prefix cut off by the end
        b"\x01\x02\x03" + _lp("end"),
        b"junk" + struct.pack("<Q", 3) + b"ab",
        struct.pack("<Q", 3),
        # the high length byte comes from the last byte of a zero run
        b"\x00" * 40 + b"\x01" + b"\x00" * 6 + b"B" * 256 + b"tail",
        b"\x00" * 40 + b"\x01" + b"\x00" * 6 + b"B" * 255 + b"\x80",
        # a zero run that is also the leading zeros of a real prefix
        b"\x00" * 9 + b"\x05\x00" + b"\x00" * 6 + b"12345",
        # non-printable bodies next to printable ones
        _lp(b"ok\x00no") + _lp("yes") + _lp(b"\x7f") + _lp("\t\n\r ~"),
        # a 0x80 handle between two values, as the real framing has it
        struct.pack("<I", 0x80000001) + _lp("Text") + struct.pack("<ff", 1.0, 2.0)
        + _lp("Shoot Left Ramp") + struct.pack("<I", 2),
    ]
    for data in cases:
        assert radium.find_strings(data) == _find_strings_per_byte(data), data[:40]
        assert radium.find_strings(bytearray(data)) == _find_strings_per_byte(bytearray(data))


def test_find_strings_matches_the_per_byte_scan_on_random_bytes():
    import random
    rng = random.Random(795)
    for trial in range(40):
        n = rng.randrange(0, 3000)
        # byte values skewed towards zeros and printable ascii so that
        # candidates, zero runs and near-misses are all common
        pool = [0] * 40 + list(range(32, 127)) + [9, 10, 13, 0x80, 0xff, 1, 2, 3]
        buf = bytearray(rng.choice(pool) for _ in range(n))
        for _ in range(rng.randrange(0, 6)):             # planted strings
            ln = rng.choice([1, 2, 7, 8, 9, 100, radium.MAXLEN, radium.MAXLEN + 1])
            s = bytes(rng.choice(b"AZ az09\t\n\r~") for _ in range(ln))
            at = rng.randrange(0, max(1, n))
            buf[at:at + 8 + ln] = _lp(s)
        data = bytes(buf)
        assert radium.find_strings(data) == _find_strings_per_byte(data), trial
