"""Tests for recolouring a scene's display text (a tester's "turtle green").

The colour a line of text is drawn in is a property of the SCENE, not of the
font: the glyph atlas is white ink so the scene can multiply it by an RGBA it
carries per line.  Changing a text colour is therefore a size-neutral patch of
four floats inside ``scene.radium`` — the same shape as a display-text edit,
on different bytes of the same file.

Three things have to hold and each has a test here:

* the manifest is the model (Write re-reads it), and picking the colour a line
  already has records nothing;
* the RGBA offsets come from the same keyframe scan the preview reads, so what
  Build patches is what the Scenes window showed;
* a string drawn TWICE — a black outline instance under a coloured fill, which
  is how Stern draws every title — only has the instance the user picked from
  repainted.  Repainting both is how you silently delete the outline.
"""

import struct

import pytest

pytest.importorskip("numpy")
import numpy as np                                    # noqa: E402

from pinball_decryptor.plugins.stern import (         # noqa: E402
    engine, radium, scene_layout, text_colors)


# ---------------------------------------------------------------------------
# a synthetic scene.radium: one inline image, then keyframes, stage, instances
# ---------------------------------------------------------------------------

def _s(text):
    b = text.encode("latin1")
    return struct.pack("<Q", len(b)) + b


def _keyframe(seq, text, rgba=(1.0, 1.0, 1.0, 1.0),
              rect=(0.0, 0.0, 1360.0, 120.0), align=1):
    return (struct.pack("<II", 0x80000001 | (seq << 8), seq)
            + struct.pack("<Q", 0)
            + struct.pack("<4f", *rect) + struct.pack("<4f", *rgba)
            + struct.pack("<H", 0) + struct.pack("<I", align)
            + struct.pack("<f", 0.0) + struct.pack("<I", 0)
            + _s(text) + bytes([2]) + b"\x00" * 24)


def _track(x=0.0, y=0.0):
    return (struct.pack("<I", 0x80000000) + struct.pack("<2f", 1.0, 0.0)
            + struct.pack("<2f", x, y))


def _stage(w=1360, h=768, fps=60.0, root_kids=2):
    return (b"\x00" * 8 + struct.pack("<2I", w, h) + struct.pack("<f", fps)
            + b"\x00" * 12 + struct.pack("<f", 1.0) + b"\x00" * 12
            + struct.pack("<3I", 1, root_kids, 0))


def _instance(name, x, y, seq):
    return (_s(name) + struct.pack("<9I", *([1] * 9))
            + _track() + _track() + _track(x, y) + _keyframe(seq, ""))


def _image_block(tex_w=16, tex_h=16, junk=8):
    """One inline BC3 image — the node graph only starts past the decoded
    regions, so a scene without art has no readable tail."""
    from pinball_decryptor.plugins.stern import dds
    pw, ph = ((tex_w + 3) // 4) * 4, ((tex_h + 3) // 4) * 4
    arr = np.empty((ph, pw, 4), dtype=np.uint8)
    arr[:] = (20, 200, 90, 255)
    raw = dds.encode_bc3(arr)
    return (b"\x7f" * junk
            + struct.pack("<II", tex_w, tex_h)
            + struct.pack("<I", 0x80000003)
            + struct.pack("<II", tex_w, tex_h)
            + struct.pack("<I", 5) + struct.pack("<II", 0, 0)
            + struct.pack("<I", len(raw)) + raw)


def _scene(lines):
    """*lines* = ``[(name, text, rgba)]``; each gets a keyframe and an
    instance.  Repeat a text with two colours to model an outline under a
    fill."""
    out = bytearray(_image_block())
    for i, (_n, text, rgba) in enumerate(lines):
        out += _keyframe(i + 1, text, rgba=rgba)
    out += _stage(root_kids=len(lines))
    for i, (name, _t, _c) in enumerate(lines):
        out += _instance(name, 10.0 * (i + 1), 100.0 * (i + 1), i + 1)
    return bytes(out)


class _FakeReader:
    """File offset == disk offset, so a patched copy of the buffer reads back
    at the same offsets."""

    def __init__(self, files):
        self._files = files

    def iter_regular_files(self, min_size=1, max_depth=None):
        for i, (path, data) in enumerate(self._files.items()):
            if len(data) >= min_size:
                yield path, i + 11, {"size": len(data), "_path": path,
                                     "i_block": path.encode()}

    def read_file_bytes(self, node):
        return self._files[node["_path"]]

    def disk_ranges(self, node, file_off, length):
        return [(file_off, length)]


def _offsets(buf):
    imgs = engine.parse_radium_images(buf)
    tables = radium.parse_glyph_tables(buf, imgs) if imgs else []
    return scene_layout.text_color_offsets(buf, imgs, tables)


def _apply(buf, writes):
    out = bytearray(buf)
    for off, payload in writes:
        out[off:off + len(payload)] = payload
    return bytes(out)


# ---------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------

def test_manifest_round_trips_and_drops_a_no_op_pick(tmp_path):
    a = str(tmp_path)
    text_colors.set_color(a, "/g/a.radium", "BALL 1", (255, 255, 255),
                          (51, 204, 51))
    assert text_colors.load(a) == {
        "/g/a.radium": {"BALL 1": ((255, 255, 255), (51, 204, 51))}}
    assert text_colors.colors_for(a, "/g/a.radium") == {"BALL 1": (51, 204, 51)}
    assert text_colors.count(a) == 1

    # picking the colour it already has is not an edit — a no-op row would make
    # the project look modified and give Build nothing to do.
    text_colors.set_color(a, "/g/a.radium", "BALL 1", (255, 255, 255),
                          (255, 255, 255))
    assert text_colors.load(a) == {}
    assert not text_colors.manifest_path(a) or \
        text_colors.count(a) == 0


def test_manifest_survives_a_string_with_a_tab(tmp_path):
    a = str(tmp_path)
    text_colors.set_color(a, "/g/a.radium", "A\tB", (0, 0, 0), (1, 2, 3))
    # the tab is flattened so the row stays one row with four columns
    assert list(text_colors.load(a)["/g/a.radium"]) == ["A B"]


def test_clear_all_removes_every_edit(tmp_path):
    a = str(tmp_path)
    text_colors.set_color(a, "/g/a.radium", "X", (0, 0, 0), (9, 9, 9))
    text_colors.set_color(a, "/g/b.radium", "Y", (0, 0, 0), (8, 8, 8))
    assert text_colors.clear_all(a) == 2
    assert text_colors.load(a) == {}


def test_hex_helpers_round_trip():
    assert text_colors.to_hex((51, 204, 51)) == "#33cc33"
    assert text_colors.parse_hex("#33CC33") == (51, 204, 51)
    assert text_colors.parse_hex("nonsense") is None
    assert text_colors.from_floats((1.0, 0.0, 0.5, 1.0)) == (255, 0, 128)


# ---------------------------------------------------------------------------
# finding the bytes
# ---------------------------------------------------------------------------

def test_offsets_point_at_each_line_s_rgba():
    buf = _scene([("Line1", "CLOCK NOT SET", (1.0, 1.0, 1.0, 1.0)),
                  ("Line2", "APR. 15", (0.0, 0.8, 0.2, 1.0))])
    found = _offsets(buf)
    assert set(found) == {"CLOCK NOT SET", "APR. 15"}
    for text, hits in found.items():
        for off, rgba in hits:
            # the recorded offset really is where those floats live
            assert struct.unpack_from("<4f", buf, off) == pytest.approx(
                tuple(rgba))


def test_offsets_keep_an_outline_keyframe_apart_from_its_fill():
    """TMNT's AWARD popup draws "AWARD" twice — a pure-black outline instance
    under the coloured fill.  Both keyframes carry the same string, so the
    colour is the only thing telling them apart."""
    buf = _scene([("Outline", "AWARD", (0.0, 0.0, 0.0, 1.0)),
                  ("Fill", "AWARD", (1.0, 0.4, 0.2, 1.0))])
    hits = _offsets(buf)["AWARD"]
    assert len(hits) == 2
    colors = sorted(tuple(round(c, 2) for c in rgba[:3]) for _o, rgba in hits)
    assert colors == [(0.0, 0.0, 0.0), (1.0, 0.4, 0.2)]


def test_offsets_never_raise_on_junk():
    assert scene_layout.text_color_offsets(b"\x00" * 4096, []) == {}
    assert scene_layout.text_color_offsets(b"", None) == {}


# ---------------------------------------------------------------------------
# the write
# ---------------------------------------------------------------------------

def test_write_repaints_the_line_and_keeps_its_alpha(tmp_path):
    """Alpha is what fades a line in; only the RGB is rewritten."""
    buf = _scene([("Line1", "CLOCK NOT SET", (1.0, 1.0, 1.0, 0.5))])
    reader = _FakeReader({"/g/a.radium": buf})
    text_colors.set_color(str(tmp_path), "/g/a.radium", "CLOCK NOT SET",
                          (255, 255, 255), (51, 204, 51))
    writes, n, overlays = engine._radium_color_writes(
        reader, str(tmp_path), lambda *a, **k: None, lambda: False)
    assert n == 1 and writes and overlays

    patched = _apply(buf, writes)
    assert len(patched) == len(buf)              # size-neutral, always
    (off, _rgba), = _offsets(buf)["CLOCK NOT SET"]
    r, g, b, alpha = struct.unpack_from("<4f", patched, off)
    assert (round(r, 3), round(g, 3), round(b, 3)) == (0.2, 0.8, 0.2)
    assert alpha == pytest.approx(0.5)           # the fade survives


def test_write_leaves_the_outline_instance_black(tmp_path):
    """The whole point of keying on the colour picked FROM: recolouring the
    fill must not repaint the black outline drawn under it."""
    buf = _scene([("Outline", "AWARD", (0.0, 0.0, 0.0, 1.0)),
                  ("Fill", "AWARD", (1.0, 0.4, 0.2, 1.0))])
    reader = _FakeReader({"/g/a.radium": buf})
    # the user picked from the fill's colour, which is what the preview showed
    text_colors.set_color(str(tmp_path), "/g/a.radium", "AWARD",
                          (255, 102, 51), (51, 204, 51))
    writes, n, _ov = engine._radium_color_writes(
        reader, str(tmp_path), lambda *a, **k: None, lambda: False)
    assert n == 1

    after = {}
    for off, rgba in _offsets(_apply(buf, writes))["AWARD"]:
        after[off] = tuple(round(c, 2) for c in rgba[:3])
    assert sorted(after.values()) == [(0.0, 0.0, 0.0), (0.2, 0.8, 0.2)]


def test_write_warns_and_skips_when_the_colour_moved_on(tmp_path):
    """A stale row (the card no longer draws that line in the colour the edit
    was made from) is reported, not applied to whatever is there now."""
    buf = _scene([("Line1", "REPLAY", (1.0, 1.0, 1.0, 1.0))])
    reader = _FakeReader({"/g/a.radium": buf})
    text_colors.set_color(str(tmp_path), "/g/a.radium", "REPLAY",
                          (0, 0, 255), (51, 204, 51))
    msgs = []
    writes, n, _ov = engine._radium_color_writes(
        reader, str(tmp_path), lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False)
    assert (writes, n) == ([], 0)
    assert any(lvl == "warning" and "left alone" in m for lvl, m in msgs)


def test_write_reports_a_scene_that_is_not_on_the_card(tmp_path):
    reader = _FakeReader({"/g/other.radium": _scene(
        [("Line1", "X", (1.0, 1.0, 1.0, 1.0))])})
    text_colors.set_color(str(tmp_path), "/g/missing.radium", "X",
                          (255, 255, 255), (0, 255, 0))
    msgs = []
    writes, n, _ov = engine._radium_color_writes(
        reader, str(tmp_path), lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False)
    assert (writes, n) == ([], 0)
    assert any(lvl == "warning" for lvl, _m in msgs)


def test_no_manifest_is_not_a_write(tmp_path):
    reader = _FakeReader({"/g/a.radium": _scene(
        [("Line1", "X", (1.0, 1.0, 1.0, 1.0))])})
    assert engine._radium_color_writes(
        reader, str(tmp_path), lambda *a, **k: None, lambda: False) == (
            [], 0, {})
