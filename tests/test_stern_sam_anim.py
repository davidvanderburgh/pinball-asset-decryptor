"""Stern S.A.M. DMD animations (PAD-584): the graphics table's frame
formats decoded, encoded back in their shortest exact form, and edited
frames written into a copy of the code update through Extract / Write /
Revert.

The tests graft a small graphics table (the real record layout and the
four code literals that locate it) onto the synthetic SAM image of the
sound tests.  The format itself was proven on the real titles by hand:
every compressed record of all 19 titles that have them run through the
title's own decompressors under an ARM emulator (0 of 88,143 differ), and
edited animations seen playing exactly as written in PinMAME on TRON,
Indiana Jones and Mustang (docs/plans/sam_compatibility.md).
"""

import os
import random
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from pinball_decryptor.plugins.pinmame_classic import sam, sam_sound
from pinball_decryptor.plugins.pinmame_classic import sam_anim as A
from pinball_decryptor.plugins.pinmame_classic.sam_games import SAM_GAME_DB
from pinball_decryptor.plugins.stern import sam_anim_assets as assets
from pinball_decryptor.plugins.stern.pipeline import (
    SamExtractPipeline, SamRevertPipeline, SamWritePipeline)
from tests.test_stern_sam_audio import BASE, M32, _log, _run, _sums_ok, \
    make_image

LITERALS = 0x100            # where the four code literals go


def _picture(w, h, seed, levels=16):
    """A frame with runs in it (blocks of shade), like DMD art."""
    rng = np.random.default_rng(seed)
    bw = max(1, w // 4)
    cols = rng.integers(0, levels, size=(h, (w + bw - 1) // bw))
    f = np.repeat(cols, bw, axis=1)[:, :w].astype(np.uint8)
    f[rng.random((h, w)) < 0.05] = rng.integers(0, 16)
    return f


def _record(rid, flags, frame, fmt, base=None):
    h, w = frame.shape
    head = struct.pack("<IIhhB", rid, flags, w, h, fmt)
    kind, col = A._KINDS[fmt]
    if kind == "raw":
        body = frame.tobytes()
    elif kind == "nib":
        px = frame.reshape(-1)
        if len(px) & 1:
            px = np.append(px, 0)
        body = (px[0::2] | (px[1::2] << 4)).astype(np.uint8).tobytes()
    elif kind == "rle":
        body = A.rle_encode(A._to_scan(frame, col))
    else:
        body = A.delta_encode(A._to_scan(base, col), A._to_scan(frame, col))
    return head + body


def _anim(seed, n, w=24, h=8):
    """n frames of one moving picture: each a small change on the last."""
    rng = np.random.default_rng(seed)
    f = _picture(w, h, seed)
    out = [f]
    for _ in range(n - 1):
        f = f.copy()
        y, x = rng.integers(0, h - 2), rng.integers(0, w - 4)
        f[y:y + 2, x:x + 4] = rng.integers(0, 16)
        out.append(f)
    return out


def art_records():
    """``[(id, flags, frame, fmt)]`` with every format and frame-cache case
    in it; ids consecutive (the cache matches id - 1)."""
    recs = []
    still = _picture(17, 23, 1)
    recs.append((0x2000, 0, still, 0))                     # a plain picture
    clear = _picture(9, 12, 2)
    clear[0, :] = A.TRANSPARENT
    recs.append((0x2001, 0, clear, 0))                     # with clear pixels
    recs.append((0x2002, 0, _picture(10, 7, 3), 12))       # 4-bit picture
    a = _anim(4, 6)
    recs.append((0x20003, 4, a[0], 1))                     # keyframe, cached
    recs.append((0x20004, 5, a[1], 3))                     # deltas follow...
    recs.append((0x20005, 5, a[2], 9))
    recs.append((0x20006, 5, a[3], 3))
    recs.append((0x20007, 5, a[4], 9))
    recs.append((0x20008, 1, a[5], 3))                     # ...the last one
    for i, s in enumerate((5, 6, 7)):                      # whole frames
        recs.append((0x20009 + i, 0, _picture(24, 8, s), 7 if i & 1 else 1))
    b = _anim(8, 3)
    recs.append((0x2000C, 4, b[0], 12))                    # 4-bit keyframe
    recs.append((0x2000D, 5, b[1], 9))
    recs.append((0x2000E, 1, b[2], 9))
    c = _anim(9, 2)
    recs.append((0x2000F, 4, c[0], 0))                     # raw keyframe
    recs.append((0x20010, 3, c[1], 3))                     # flags 2: kept
    return recs


def graft(data, recs, trailer=True, old_header=False):
    """*data* (a synthetic SAM image) with a font table, graphics table and
    *recs* appended and the code literals pointing at them; checksums
    recomputed."""
    body = bytearray(data[:-4] if trailer else data)
    body += bytes(-len(body) % 16)
    font_at = len(body)
    body += bytes(40)                                       # two fonts
    gfx_at = len(body)
    body += bytes(4 * len(recs))
    offs = []
    frames = []
    prev = None
    for rid, fl, frame, fmt in recs:
        body += bytes(-len(body) % 4)
        offs.append(len(body))
        if old_header:
            h, w = frame.shape
            body += struct.pack("<hhB", w, h, 0) + frame.tobytes()
        else:
            body += _record(rid, fl, frame, fmt, prev)
        prev = frame
        frames.append(frame)
    body += bytes(-len(body) % 4)
    for i, o in enumerate(offs):
        struct.pack_into("<I", body, gfx_at + 4 * i, sam_sound.bank_pointer(o))
    struct.pack_into("<4I", body, LITERALS, 2, sam_sound.bank_pointer(font_at),
                     len(recs), sam_sound.bank_pointer(gfx_at))
    body += b"\x00" * 8 + (b"\x00" * 4 if trailer else b"")
    end1 = len(body) - (4 if trailer else 0) - 1
    a = np.frombuffer(bytes(body), np.uint8)
    for k, (s, e) in enumerate([(0, BASE - 1), (BASE + 0x48, end1)]):
        c = (~int(a[s:e + 1].sum(dtype=np.uint64))) & M32
        struct.pack_into("<3I", body, BASE + 12 * k, s, e, c)
    if trailer:
        n = len(body) - 4
        struct.pack_into("<I", body, n,
                         (~int(np.frombuffer(bytes(body), np.uint8, count=n)
                               .sum(dtype=np.uint64))) & M32)
    return bytes(body), frames


@pytest.fixture
def art():
    data, _ = make_image()
    data, frames = graft(data, art_records())
    return data, frames


def _register(tmp_path, monkeypatch, data, name="MT999LE.BIN"):
    crc = zlib.crc32(data) & M32
    db = {k: dict(v) for k, v in SAM_GAME_DB.items()}
    db["mustang"]["romsets"] = dict(
        db["mustang"]["romsets"],
        mt_999h=("mt_999h.bin", crc, len(data),
                 "Mustang Limited Edition (V9.99)"))
    monkeypatch.setattr(sam, "SAM_GAME_DB", db)
    monkeypatch.setitem(sam._BY_CRC, (crc, len(data)), ("mustang", "mt_999h"))
    monkeypatch.setitem(sam._BY_SIZE, len(data), {("mustang", "mt_999h")})
    monkeypatch.setattr(sam, "MIN_BIN_SIZE", 1)
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ---------------------------------------------------------------------------
# The formats, as the game's renderer reads them
# ---------------------------------------------------------------------------

def _hand(fmt, w, h, payload, rid=0x10, flags=0):
    off = 0x40
    data = bytes(off) + struct.pack("<IIhhB", rid, flags, w, h, fmt) + \
        payload + bytes(16)
    n = A._rec_length(data, off, w, h, fmt)
    return data, A.Record(0, off, rid, flags, w, h, fmt, n)


def test_run_length_grammar_by_hand():
    # 2 zeros, 2 x 0x0F, 5 repeated twice, literal 1 2, end
    stream = bytes([2 << 2 | 1, 2 << 2 | 2, 2 << 2 | 3, 5, 2 << 2, 1, 2, 0])
    data, rec = _hand(7, 4, 2, stream)
    assert rec.length == 13 + len(stream)
    assert A.decode_record(data, rec).tolist() == [[0, 0, 15, 15],
                                                   [5, 5, 1, 2]]
    # format 1 is the same stream down the columns
    data, rec = _hand(1, 4, 2, stream)
    assert A.decode_record(data, rec).tolist() == [[0, 15, 5, 1],
                                                   [0, 15, 5, 2]]
    # the 2008-2010 engines call the row-order one 8
    data, rec = _hand(8, 4, 2, stream)
    assert A.decode_record(data, rec).tolist() == [[0, 0, 15, 15],
                                                   [5, 5, 1, 2]]


def test_delta_grammar_by_hand():
    base = np.array([[1, 2, 3], [4, 5, 6]], np.uint8)
    # skip 2, write 1 literal (7), skip 1, write 2 (8 9), end
    stream = bytes([256 - 2, 1, 7, 256 - 1, 2, 8, 9, 0])
    data, rec = _hand(9, 3, 2, stream)
    assert A.decode_record(data, rec, base).tolist() == [[1, 2, 7],
                                                         [4, 8, 9]]
    # format 3: the same positions counted down the columns
    data, rec = _hand(3, 3, 2, stream)
    assert A.decode_record(data, rec, base).tolist() == [[1, 7, 8],
                                                         [4, 5, 9]]
    # and 10 = 9 on the older engines
    data, rec = _hand(10, 3, 2, stream)
    assert A.decode_record(data, rec, base).tolist() == [[1, 2, 7],
                                                         [4, 8, 9]]


def test_raw_and_four_bit_by_hand():
    data, rec = _hand(0, 3, 1, bytes([1, 0xFF, 15]))
    assert A.decode_record(data, rec).tolist() == [[1, 255, 15]]
    data, rec = _hand(12, 3, 1, bytes([0x21, 0x03]))     # low nibble first
    assert A.decode_record(data, rec).tolist() == [[1, 2, 3]]
    assert rec.length == 13 + 2


def test_a_bad_stream_is_refused():
    data, rec = _hand(7, 4, 2, bytes([3 << 2 | 1, 0]))   # 3 pixels, not 8
    with pytest.raises(A.SamAnimError):
        A.decode_record(data, rec)
    data, rec = _hand(9, 2, 1, bytes([5, 1, 2, 3, 4, 5, 0]))
    with pytest.raises(A.SamAnimError):                   # past the frame
        A.decode_record(data, rec, np.zeros((1, 2), np.uint8))
    with pytest.raises(A.SamAnimError):                   # no base
        A.decode_record(data, rec)


# ---------------------------------------------------------------------------
# The encoders: exact, and never longer than any other stream
# ---------------------------------------------------------------------------

def _brute_rle(lin):
    n = len(lin)
    cost = [0] * (n + 1)
    cost[n] = 1
    for i in range(n - 1, -1, -1):
        best = 1 << 30
        k = 0
        while i + k < n and lin[i + k] == lin[i] and k < 63:
            k += 1
            best = min(best, (1 if lin[i] in (0, 15) else 2) + cost[i + k])
        for k in range(1, min(63, n - i) + 1):
            best = min(best, 1 + k + cost[i + k])
        cost[i] = best
    return cost[0]


def _brute_delta(base, lin):
    last = len(lin)
    while last and base[last - 1] == lin[last - 1]:
        last -= 1
    cost = [0] * (last + 1)
    cost[last] = 1
    for i in range(last - 1, -1, -1):
        best = 1 << 30
        k = 0
        while i + k < last and base[i + k] == lin[i + k] and k < 128:
            k += 1
            best = min(best, 1 + cost[i + k])
        for k in range(1, min(127, last - i) + 1):
            best = min(best, 1 + k + cost[i + k])
        cost[i] = best
    return cost[0]


def _decode_rle(stream, n):
    return bytes(A._rle_decode(stream, 0, n))


def _runny(rng, n):
    out = []
    while len(out) < n:
        v = rng.choice([0, 15, 255, rng.randrange(16)])
        out += [v] * rng.choice([1, 1, 2, 3, 7, 40, 70, 200])
    return out[:n]


def test_rle_encoder_is_exact_and_shortest():
    rng = random.Random(584)
    for trial in range(120):
        n = rng.choice([1, 2, 5, 63, 64, 65, 130, 300])
        lin = _runny(rng, n)
        s = A.rle_encode(lin)
        assert _decode_rle(s, n) == bytes(lin)
        assert len(s) == _brute_rle(lin), (trial, lin)


def test_delta_encoder_is_exact_and_shortest():
    rng = random.Random(1584)
    for trial in range(120):
        n = rng.choice([1, 3, 64, 127, 128, 129, 300, 700])
        base = _runny(rng, n)
        lin = list(base)
        for _ in range(rng.randrange(0, 12)):
            i = rng.randrange(n)
            k = rng.choice([1, 1, 2, 5, 130])
            for j in range(i, min(n, i + k)):
                lin[j] = rng.randrange(16)
        s = A.delta_encode(base, lin)
        buf = bytearray(base)
        A._delta_apply(buf, s, 0)
        assert bytes(buf) == bytes(lin)
        assert len(s) == _brute_delta(base, lin), trial
    # nothing changed is just the end byte; a change at the very end
    # needs no skip past it
    assert A.delta_encode([1, 2, 3], [1, 2, 3]) == b"\x00"
    assert A.delta_encode([1, 2, 3], [1, 2, 9]) == bytes([254, 1, 9, 0])


# ---------------------------------------------------------------------------
# The graphics table
# ---------------------------------------------------------------------------

def test_read_table_decodes_every_record(art):
    data, frames = art
    t = A.read_table(data)
    assert len(t.records) == len(frames)
    assert t.literals == LITERALS
    assert (t.row_rle, t.row_delta, t.has_nibble) == (7, 9, True)
    got = A.decode_all(data, t)
    for n, f in enumerate(frames):
        assert np.array_equal(got[n], f), n
    assert all(t.movable.values())


def test_older_engine_numbering():
    recs = [(0x10, 4, _picture(24, 8, 1), 8),
            (0x11, 1, _picture(24, 8, 2), 10)]
    data, frames = graft(make_image()[0], recs)
    t = A.read_table(data)
    assert (t.row_rle, t.row_delta, t.has_nibble) == (8, 10, False)
    got = A.decode_all(data, t)
    assert np.array_equal(got[1], frames[1])
    assert A.allowed_formats(t, t.records[0]) == [8]      # what it uses
    assert set(A.allowed_formats(t, t.records[1])) <= {3, 8, 10}


def test_read_table_refuses_the_first_titles():
    # WPT / Pirates / Family Guy / WOF: raw pictures with a 5-byte header
    recs = [(0, 0, _picture(17, 23, 1), 0), (0, 0, _picture(9, 12, 2), 0)]
    data, _ = graft(make_image()[0], recs, old_header=True)
    with pytest.raises(A.SamAnimError):
        A.read_table(data)
    with pytest.raises(A.SamAnimError):
        A.read_table(make_image()[0])           # no table at all


def test_bases_follow_the_frame_cache(art):
    data, _ = art
    b = A.bases(A.read_table(data))
    assert [b[n] for n in range(4, 9)] == [3, 4, 5, 6, 7]
    assert b[13] == 12 and b[14] == 13
    assert b[16] == 15


def test_stills_and_frames_split(art):
    data, _ = art
    t = A.read_table(data)
    # plain raw / 4-bit pictures are the Replace Images side's; a raw or
    # 4-bit keyframe a delta builds on is an animation frame
    assert A.still_numbers(data, t) == {0, 1, 2}
    assert A.animation_numbers(data, t) == set(range(3, 17))


def test_a_picture_before_a_format_8_frame_is_a_still():
    # the 2008-2010 engine's 8 is a whole run-length frame (format 7's
    # code), not a delta: the picture before it is a plain still, and the
    # one before its 10 (a delta) is an animation frame
    recs = [(0x100 + i, 0, _picture(9, 12, 20 + i), 0) for i in range(16)]
    recs += [(0x110, 0, _picture(24, 8, 40), 8),
             (0x111, 4, _picture(24, 8, 41), 0),
             (0x112, 1, _picture(24, 8, 42), 10)]
    data, _ = graft(make_image()[0], recs)
    t = A.read_table(data)
    stills = A.still_numbers(data, t)
    frames = A.animation_numbers(data, t)
    assert 15 in stills                  # its next record is a format 8
    assert 17 in frames                  # a delta builds on it
    assert {16, 18} <= frames
    assert stills | frames == set(range(len(recs))) and not stills & frames


def test_allowed_formats_keep_the_cache_behaving(art):
    data, _ = art
    t = A.read_table(data)
    r = t.records
    assert A.allowed_formats(t, r[0]) == [0]               # raw stays raw
    assert A.allowed_formats(t, r[12]) == [12]
    assert A.allowed_formats(t, r[3]) == [1, 7, 12]        # keyframe
    # a delta that keeps the frame cached (4) or ends it (no 2/4) may be
    # a whole frame; flags 2 alone must stay a delta
    assert A.allowed_formats(t, r[4]) == [3, 9, 1, 7, 12]
    assert A.allowed_formats(t, r[8]) == [3, 9, 1, 7, 12]
    assert A.allowed_formats(t, r[16]) == [3, 9]


# ---------------------------------------------------------------------------
# Planning a write
# ---------------------------------------------------------------------------

def _apply(data, t, frames, edits):
    plan = A.plan_write(data, t, frames, edits,
                        A.animation_numbers(data, t))
    img = bytearray(data)
    A.apply_plan(img, t, plan)
    img = bytes(img)
    t2 = A.read_table(img)
    return plan, img, A.decode_all(img, t2)


def test_an_edited_animation_is_written_exactly(art):
    data, _ = art
    t = A.read_table(data)
    frames = A.decode_all(data, t)
    edits = {n: np.where(frames[n] <= 15, 15 - frames[n],
                         frames[n]).astype(np.uint8) for n in range(3, 9)}
    plan, img, got = _apply(data, t, frames, edits)
    assert all(plan.how[n] == "exact" for n in edits)
    for n in range(len(t.records)):
        want = edits.get(n, frames[n])
        assert np.array_equal(got[n], want), n
    assert len(img) == len(data)


def test_frames_after_an_edit_still_show_their_own_picture(art):
    data, _ = art
    t = A.read_table(data)
    frames = A.decode_all(data, t)
    edit = frames[3].copy()
    edit[:, :6] = 0
    plan, img, got = _apply(data, t, frames, {3: edit})
    # the deltas after it were re-encoded on the new keyframe
    assert set(plan.written) >= {3, 4, 5, 6, 7, 8}
    assert np.array_equal(got[3], edit)
    for n in range(4, 9):
        assert np.array_equal(got[n], frames[n]), n


def test_freed_bytes_let_a_richer_frame_in(art):
    data, _ = art
    t = A.read_table(data)
    frames = A.decode_all(data, t)
    blank = np.zeros_like(frames[9])
    rich = _picture(24, 8, 99, levels=16)
    rich ^= (np.arange(24) % 3).astype(np.uint8)          # fewer runs
    rich &= 15
    # alone the rich frame doesn't fit its own bytes
    alone, _img, _got = _apply(data, t, frames, {10: rich})
    assert alone.how[10] != "exact"
    plan, img, got = _apply(data, t, frames, {9: blank, 10: rich})
    assert plan.how == {9: "exact", 10: "exact"}
    assert np.array_equal(got[10], rich)
    assert plan.moved                                      # the run moved up
    t2 = A.read_table(img)
    for n in plan.moved:
        assert t2.records[n].offset == plan.moved[n]
    # everything else still decodes to its own picture
    for n in range(len(t.records)):
        if n not in (9, 10):
            assert np.array_equal(got[n], frames[n]), n


def test_a_frame_too_detailed_to_fit_is_simplified_or_kept(art):
    data, _ = art
    t = A.read_table(data)
    frames = A.decode_all(data, t)
    rng = np.random.default_rng(5)
    noise = rng.integers(0, 16, frames[10].shape).astype(np.uint8)
    plan, img, got = _apply(data, t, frames, {10: noise})
    how = plan.how[10]
    assert how != "exact"
    if how == "original":
        assert np.array_equal(got[10], frames[10])
    else:
        assert np.array_equal(got[10], plan.frames[10])
        assert len(np.unique(got[10])) <= int(how.split()[0])
    for n in range(len(t.records)):
        if n != 10:
            assert np.array_equal(got[n], frames[n]), n


def test_a_record_something_else_points_at_stays_put(art):
    data, _ = art
    t = A.read_table(data)
    ptr = struct.unpack_from("<I", data, t.table + 4 * 9)[0]
    img = bytearray(data)
    struct.pack_into("<I", img, LITERALS + 0x40, ptr)      # a glyph array
    img = bytes(img)
    t = A.read_table(img)
    assert not t.movable[9] and t.movable[10]
    frames = A.decode_all(img, t)
    plan, out, got = _apply(img, t, frames, {9: np.zeros_like(frames[9])})
    assert 9 not in plan.moved
    assert A.read_table(out).records[9].offset == t.records[9].offset


def test_simplify_keeps_black_white_and_clear():
    f = np.array([[0, 7, 15, 255, 8]], np.uint8)
    s = A.simplify(f, 2)
    assert s.tolist() == [[0, 0, 15, 255, 15]]
    base = np.array([[0, 6, 15, 255, 1]], np.uint8)
    assert A.simplify(f, 8, base)[0, 1] == 6               # near the base


# ---------------------------------------------------------------------------
# Extract / Write / Revert
# ---------------------------------------------------------------------------

def _extract(path, tmp_path):
    out_dir = str(tmp_path / "proj")
    res = _run(SamExtractPipeline(path, out_dir, lambda *a, **k: None,
                                  lambda i: None, lambda *a: None, None))
    assert res["ok"], res
    return out_dir, res


def _png(path):
    return assets.from_image(Image.open(path))


def test_extract_writes_every_animation_frame(art, tmp_path, monkeypatch):
    data, frames = art
    path = _register(tmp_path, monkeypatch, data)
    out_dir, res = _extract(path, tmp_path)
    assert "And 14 DMD animation frame(s), in animations/." in res["msg"]
    names = sorted(os.listdir(os.path.join(out_dir, "animations")))
    assert names == ["img%04d.png" % n for n in range(3, 17)]
    for n in range(3, 17):
        im = Image.open(os.path.join(out_dir, "animations",
                                     "img%04d.png" % n))
        assert im.mode == "LA"
        assert np.array_equal(assets.from_image(im), frames[n])
    sums = open(os.path.join(out_dir, ".checksums.md5")).read()
    assert "animations/img0003.png" in sums
    assert SamExtractPipeline.PHASES[3] == "Decode animations"


def test_extract_of_a_title_without_animations(tmp_path, monkeypatch):
    data, _ = make_image()
    path = _register(tmp_path, monkeypatch, data)
    lines, log = _log()
    out_dir = str(tmp_path / "proj")
    res = _run(SamExtractPipeline(path, out_dir, log, lambda i: None,
                                  lambda *a: None, None))
    assert res["ok"] and "animation" not in res["msg"]
    assert not os.path.exists(os.path.join(out_dir, "animations"))
    assert any("No animation frames" in x for x in lines)


def test_png_shades_round_trip():
    f = np.array([[0, 1, 7, 15, 255]], np.uint8)
    la = assets.to_la(f)
    assert la[0, :, 0].tolist() == [0, 17, 119, 255, 0]
    assert la[0, :, 1].tolist() == [255, 255, 255, 255, 0]
    assert np.array_equal(assets.from_image(Image.fromarray(la, "LA")), f)
    # an RGB edit is read as grey, to the nearest shade
    rgb = Image.fromarray(np.full((1, 2, 3), 120, np.uint8), "RGB")
    assert assets.from_image(rgb).tolist() == [[7, 7]]


def test_write_puts_the_edited_frames_in(art, tmp_path, monkeypatch):
    data, frames = art
    path = _register(tmp_path, monkeypatch, data)
    out_dir, _ = _extract(path, tmp_path)
    anim = os.path.join(out_dir, "animations")
    edits = {}
    for n in range(3, 9):
        f = np.where(frames[n] <= 15, 15 - frames[n], frames[n])
        f = f.astype(np.uint8)
        Image.fromarray(assets.to_la(f), "LA").save(
            os.path.join(anim, "img%04d.png" % n))
        edits[n] = f
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 6 animation frame(s)" in res["msg"]
    built = open(out, "rb").read()
    assert len(built) == len(data)
    assert all(_sums_ok(built)) and sam_sound.has_trailer(built)
    t = A.read_table(built)
    got = A.decode_all(built, t)
    for n in range(len(frames)):
        assert np.array_equal(got[n], edits.get(n, frames[n])), n
    assert any("img0003.png: 24x8" in x for x in lines)
    # the sounds are untouched
    assert sam_sound.read_bank(built).samples == \
        sam_sound.read_bank(data).samples


def test_write_skips_a_frame_of_the_wrong_size(art, tmp_path, monkeypatch):
    data, frames = art
    path = _register(tmp_path, monkeypatch, data)
    out_dir, _ = _extract(path, tmp_path)
    anim = os.path.join(out_dir, "animations")
    Image.new("L", (5, 5), 255).save(os.path.join(anim, "img0004.png"))
    Image.new("L", (5, 5), 255).save(os.path.join(anim, "img0999.png"))
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"]
    assert "No changed audio, pictures or animations" in res["msg"]
    assert "(2 skipped" in res["msg"]
    assert any("img0004.png is 5x5; this frame is 24x8" in x for x in lines)
    assert any("img0999.png: no such animation frame" in x for x in lines)
    assert open(out, "rb").read() == data


def test_revert_restores_an_animation_frame(art, tmp_path, monkeypatch):
    data, frames = art
    path = _register(tmp_path, monkeypatch, data)
    out_dir, _ = _extract(path, tmp_path)
    png = os.path.join(out_dir, "animations", "img0005.png")
    Image.new("L", (24, 8), 0).save(png)
    res = _run(SamRevertPipeline(path, out_dir, ["animations/img0005.png",
                                                 "animations/img0001.png"],
                                 lambda *a, **k: None, lambda i: None,
                                 lambda *a: None, None))
    assert res["ok"] and "Restored 1 original file(s)" in res["msg"]
    assert "1 could not be restored" in res["msg"]
    assert np.array_equal(_png(png), frames[5])


def test_sam_era_offers_replace_images(manufacturers_by_key, art, tmp_path,
                                       monkeypatch):
    data, _ = art
    path = _register(tmp_path, monkeypatch, data)
    stern = manufacturers_by_key["stern"]
    try:
        assert stern.detect(path).era == "sam"
        stern.set_era("sam")
        assert stern.capabilities.replace_image
        assert "animation" in stern.capture_basic_label
        assert "animations/" in stern.capture_help_text(True, False)
    finally:
        stern.set_era("")
