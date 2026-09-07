"""Tests for editing a scene's text LAYOUT: move, alignment, font size.

Where a line of text sits, how it is aligned and how big it draws are all
properties of the SCENE: the keyframe block carries the rect and a u32
alignment, and the size is the scene's own glyph table for the line's font
(each scene bakes its tables at the sizes it uses; the atlas is the master
art, fitted to each glyph's metrics box).  So every one of these edits is a
size-neutral rewrite of ``scene.radium`` -- the same shape as a text colour
edit, on different bytes of the same file.

What has to hold, and is tested here:

* the offsets come from the same keyframe scan the preview reads, and each
  one really is where that field lives;
* a move shifts EVERY keyframe of the string (the outline instance under the
  fill included) by exactly dx, dy; an alignment rewrites the u32;
* a size scales the five metric floats of every glyph in each table the
  string's keyframes name -- once per table -- plus the kerning adjusts and
  each keyframe's line spacing, and leaves the atlas bytes alone;
* one table gets one size: a second string asking a different size of a
  table already scaled is skipped with a note, an unknown string is a note
  and no patch, and junk never raises.
"""

import struct

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import (         # noqa: E402
    engine, radium, scene_layout)
from tests.test_stern_glyphs import (                 # noqa: E402
    _atlas_raw, _font_blob, _glyph_record)
from tests.test_stern_text_colors import (            # noqa: E402
    _instance, _s, _stage)


# ---------------------------------------------------------------------------
# a synthetic scene.radium: glyph tables (with their inline atlases), then
# keyframes that NAME their font, the stage, and the instances
# ---------------------------------------------------------------------------

FILL_METRICS = (10.0, 12.0, 1.0, 10.0, 11.0)          # -> 12 px
OUTLINE_METRICS = (12.0, 14.0, 0.0, 12.0, 13.0)       # -> 14 px


def _font(name, handle_base, metrics, kern=()):
    """A named font: space (no bitmap), 'A' (inline atlas, optional kerning
    against 'B'), 'B' (back-reference)."""
    raw, _rgba = _atlas_raw(16, 16)
    recs = [
        (0x20, _glyph_record(0x20, handle_base, (0.0, 0.0, 0.0, 0.0),
                             tex=0, metrics=(1.0, 1.0, 0.0, 0.0, 5.0))),
        (0x41, _glyph_record(0x41, handle_base + 1, (0.25, 0.25, 0.5, 0.5),
                             tex=handle_base + 2, inline=(raw, 16, 16, 5),
                             metrics=metrics, kern=kern)),
        (0x42, _glyph_record(0x42, handle_base + 3, (0.5, 0.5, 0.75, 1.0),
                             tex=handle_base + 2, metrics=metrics)),
    ]
    return _font_blob(recs, name=name)


def _keyframe(seq, text, font, rect=(0.0, 0.0, 1360.0, 120.0), align=1,
              spacing=2.0):
    """A text keyframe whose display string is followed, 12 bytes on, by the
    font name it draws with (``scene_layout._font_name_after``)."""
    return (struct.pack("<II", 0x80000001 | (seq << 8), seq)
            + struct.pack("<Q", 0)
            + struct.pack("<4f", *rect)
            + struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)
            + struct.pack("<H", 0) + struct.pack("<I", align)
            + struct.pack("<f", spacing) + struct.pack("<I", 0)
            + _s(text) + bytes([2]) + b"\x00" * 11 + _s(font)
            + b"\x00" * 16)


def _scene(lines, fonts=None):
    """*lines* = ``[(text, font, rect, align, spacing)]``; *fonts* =
    ``[(name, handle_base, metrics, kern)]`` (default: a fill font and an
    outline font, the outline kerning-free)."""
    if fonts is None:
        fonts = [("FillFont", 3, FILL_METRICS, ((0x42, -4.0),)),
                 ("OutlineFont", 13, OUTLINE_METRICS, ())]
    out = bytearray()
    for name, base, metrics, kern in fonts:
        out += _font(name, base, metrics, kern)
    for i, (text, font, rect, align, spacing) in enumerate(lines):
        out += _keyframe(i + 1, text, font, rect, align, spacing)
    out += _stage(root_kids=len(lines))
    for i, _line in enumerate(lines):
        out += _instance("Line%d" % (i + 1), 10.0 * (i + 1),
                         100.0 * (i + 1), i + 1)
    return bytes(out)


AWARD = [("AWARD", "FillFont", (100.0, 50.0, 400.0, 90.0), 1, 2.0),
         ("AWARD", "OutlineFont", (100.0, 50.0, 400.0, 90.0), 1, 2.0)]


def _parse(buf):
    imgs = engine.parse_radium_images(buf)
    tables = radium.parse_glyph_tables(buf, imgs)
    return imgs, tables


def _apply(buf, patches):
    out = bytearray(buf)
    for off, payload in patches:
        assert len(payload) == len(out[off:off + len(payload)])
        out[off:off + len(payload)] = payload
    return bytes(out)


def _by_name(tables):
    return {t["name"]: t for t in tables}


# ---------------------------------------------------------------------------
# radium: the glyph dicts say where their editable floats are
# ---------------------------------------------------------------------------

def test_glyph_dicts_carry_metrics_and_kerning_offsets():
    buf = _scene(AWARD)
    _imgs, tables = _parse(buf)
    assert sorted(_by_name(tables)) == ["FillFont", "OutlineFont"]
    for t in tables:
        for g in t["glyphs"]:
            # the offset really is where those five floats live
            assert struct.unpack_from("<5f", buf, g["metrics_off"]) == \
                g["metrics"]
            if g["kern"]:
                assert set(g["kern_offs"]) == set(g["kern"])
                for ch, off in g["kern_offs"].items():
                    assert struct.unpack_from("<f", buf, off)[0] == \
                        g["kern"][ch]
            else:
                # a kerning-free glyph is dict-for-dict what it always was
                assert "kern_offs" not in g
    fill = _by_name(tables)["FillFont"]
    a = {g["char"]: g for g in fill["glyphs"]}[0x41]
    assert a["kern"] == {0x42: -4.0} and list(a["kern_offs"]) == [0x42]
    assert radium.table_size_px(fill) == 12
    assert radium.table_size_px(_by_name(tables)["OutlineFont"]) == 14


# ---------------------------------------------------------------------------
# finding the bytes
# ---------------------------------------------------------------------------

def test_offsets_land_on_each_keyframe_s_fields():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    found = scene_layout.text_layout_offsets(buf, imgs, tables)
    assert list(found) == ["AWARD"]
    kfs = found["AWARD"]
    assert len(kfs) == 2                          # fill + outline
    for kf in kfs:
        assert kf["rect_off"] == kf["off"] + 16
        assert kf["align_off"] == kf["off"] + 50
        assert kf["spacing_off"] == kf["off"] + 54
        assert struct.unpack_from("<4f", buf, kf["rect_off"]) == \
            pytest.approx(tuple(kf["rect"]))
        assert kf["rect"] == [100.0, 50.0, 400.0, 90.0]
        assert struct.unpack_from("<I", buf, kf["align_off"])[0] == \
            kf["align"] == 1
        assert struct.unpack_from("<f", buf, kf["spacing_off"])[0] == \
            kf["spacing"] == 2.0
    # each keyframe resolves ITS OWN font's table in this scene
    assert [(kf["font_name"], kf["table"]["name"]) for kf in kfs] == [
        ("FillFont", "FillFont"), ("OutlineFont", "OutlineFont")]
    assert kfs[0]["table"] is _by_name(tables)["FillFont"]


def test_offsets_leave_an_ambiguous_font_unresolved():
    """One name baked at two sizes in one scene: which glyphs the line draws
    with cannot be told, so the table is None rather than a guess."""
    fonts = [("FillFont", 3, FILL_METRICS, ()),
             ("FillFont", 13, OUTLINE_METRICS, ())]
    buf = _scene([("AWARD", "FillFont", (0.0, 0.0, 300.0, 40.0), 0, 2.0)],
                 fonts)
    imgs, tables = _parse(buf)
    assert len(tables) == 2
    (kf,) = scene_layout.text_layout_offsets(buf, imgs, tables)["AWARD"]
    assert kf["font_name"] == "FillFont" and kf["table"] is None


def test_offsets_never_raise_on_junk():
    assert scene_layout.text_layout_offsets(b"\x00" * 4096, []) == {}
    assert scene_layout.text_layout_offsets(b"", None) == {}
    assert scene_layout.text_layout_offsets(b"\x80" * 200, [{"data_off": 0,
                                                             "length": 8}],
                                            None) == {}


# ---------------------------------------------------------------------------
# the patches
# ---------------------------------------------------------------------------

def test_move_shifts_every_keyframe_rect_exactly():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"dx": 10.0, "dy": -4.0}})
    assert n == 1 and notes == []
    before = scene_layout.text_layout_offsets(buf, imgs, tables)["AWARD"]
    assert sorted(off for off, _p in patches) == \
        sorted(kf["rect_off"] for kf in before)
    patched = _apply(buf, patches)
    assert len(patched) == len(buf)                # size-neutral, always
    after = scene_layout.text_layout_offsets(patched, imgs, tables)["AWARD"]
    for kf in after:
        assert kf["rect"] == [110.0, 46.0, 410.0, 86.0]
        assert kf["align"] == 1 and kf["spacing"] == 2.0   # untouched
    # nothing outside the two rects changed
    diff = [i for i in range(len(buf)) if buf[i] != patched[i]]
    assert all(any(kf["rect_off"] <= i < kf["rect_off"] + 16
                   for kf in before) for i in diff)


def test_align_rewrites_the_u32_on_both_keyframes():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"align": "right"}})
    assert n == 1 and notes == [] and len(patches) == 2
    for off, payload in patches:
        assert payload == struct.pack("<I", 2)
    after = scene_layout.text_layout_offsets(
        _apply(buf, patches), imgs, tables)["AWARD"]
    assert [kf["align"] for kf in after] == [2, 2]
    assert [kf["rect"] for kf in after] == [[100.0, 50.0, 400.0, 90.0]] * 2
    # the code form works too (what a manifest may hand back)
    patches2, _n, _notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"align": 0}})
    assert [p for _o, p in patches2] == [struct.pack("<I", 0)] * 2


def test_a_field_set_to_what_the_scene_has_is_not_a_write():
    """Centred text asked to be centred, a 100 % size, a zero move: nothing
    to write and no line counted, so a no-op row cannot make Build claim a
    change."""
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    assert scene_layout.text_layout_patches(
        buf, imgs, tables,
        {"AWARD": {"dx": 0, "dy": "", "align": "center", "size": 100}}
    ) == ([], 0, [])
    assert scene_layout.text_layout_patches(buf, imgs, tables, {}) == (
        [], 0, [])


def test_size_scales_each_table_once_plus_kerning_and_spacing():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"size": 150}})
    assert n == 1 and notes == []
    by = _by_name(tables)
    metric_offs = {g["metrics_off"] for t in by.values()
                   for g in t["glyphs"]}
    kern_offs = {o for t in by.values() for g in t["glyphs"]
                 for o in g.get("kern_offs", {}).values()}
    kfs = scene_layout.text_layout_offsets(buf, imgs, tables)["AWARD"]
    spacing_offs = {kf["spacing_off"] for kf in kfs}
    offs = [off for off, _p in patches]
    # every glyph of BOTH tables exactly once, one kerning adjust, and the
    # spacing of both keyframes -- and nothing else
    assert sorted(offs) == sorted(metric_offs | kern_offs | spacing_offs)
    assert len(offs) == len(set(offs)) == 6 + 1 + 2

    patched = _apply(buf, patches)
    assert len(patched) == len(buf)
    imgs2, tables2 = _parse(patched)
    by2 = _by_name(tables2)
    assert radium.table_size_px(by2["FillFont"]) == 18        # 12 * 1.5
    assert radium.table_size_px(by2["OutlineFont"]) == 21     # 14 * 1.5
    a = {g["char"]: g for g in by2["FillFont"]["glyphs"]}[0x41]
    assert a["metrics"] == pytest.approx(
        tuple(v * 1.5 for v in FILL_METRICS))
    assert a["kern"] == {0x42: pytest.approx(-6.0)}
    assert [kf["spacing"] for kf in
            scene_layout.text_layout_offsets(patched, imgs2, tables2)["AWARD"]
            ] == [3.0, 3.0]
    # the atlas art is the MASTER and is never touched by a resize
    for im in imgs:
        a0, a1 = im["data_off"], im["data_off"] + im["length"]
        assert patched[a0:a1] == buf[a0:a1]
    # the atlas rects (UVs) are untouched too: the glyph slices stay put
    for name in by:
        assert [g["rect"] for g in by[name]["glyphs"]] == \
            [g["rect"] for g in by2[name]["glyphs"]]


def test_all_three_edits_together_touch_disjoint_bytes():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables,
        {"AWARD": {"dx": 5.0, "dy": 5.0, "align": "left", "size": 200}})
    assert n == 1 and notes == []
    offs = [off for off, _p in patches]
    assert len(offs) == len(set(offs))
    after = scene_layout.text_layout_offsets(
        _apply(buf, patches), imgs, tables)["AWARD"]
    for kf in after:
        assert kf["rect"] == [105.0, 55.0, 405.0, 95.0]
        assert kf["align"] == 0 and kf["spacing"] == 4.0


def test_a_shared_table_takes_one_size_and_the_conflict_is_noted():
    """Two strings drawn with the same font: the first edit's size wins the
    table; the other line's size is skipped, with a note saying so.  The
    same size asked twice is not a conflict, and the collateral is named."""
    lines = [("AWARD", "FillFont", (100.0, 50.0, 400.0, 90.0), 1, 2.0),
             ("BONUS", "FillFont", (100.0, 150.0, 400.0, 190.0), 1, 2.0),
             ("REPLAY", "OutlineFont", (0.0, 0.0, 300.0, 40.0), 0, 1.0)]
    buf = _scene(lines)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"size": 150}, "BONUS": {"size": 200}})
    assert n == 1
    fill = _by_name(tables)["FillFont"]
    metric_offs = {g["metrics_off"] for g in fill["glyphs"]}
    # the fill table is scaled once, at AWARD's 150 %
    hits = [p for off, p in patches if off in metric_offs]
    assert len(hits) == 3
    a = {g["char"]: g for g in fill["glyphs"]}[0x41]
    assert struct.unpack("<5f", dict(patches)[a["metrics_off"]]) == \
        pytest.approx(tuple(v * 1.5 for v in FILL_METRICS))
    # BONUS got nothing, not even its spacing (no half-scaled line)
    kfs = scene_layout.text_layout_offsets(buf, imgs, tables)
    assert kfs["BONUS"][0]["spacing_off"] not in dict(patches)
    assert kfs["AWARD"][0]["spacing_off"] in dict(patches)
    assert any("BONUS" in m and "skipped" in m and "150" in m for m in notes)
    assert any("AWARD" in m and "also resizes 1 other line" in m
               and "FillFont" in m and "12 px" in m and "'BONUS'" in m
               for m in notes)
    assert not any("REPLAY" in m for m in notes)

    # the same size twice is one resize, both lines counted, no conflict
    patches2, n2, notes2 = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"size": 150}, "BONUS": {"size": 150}})
    assert n2 == 2
    assert len([p for off, p in patches2 if off in metric_offs]) == 3
    assert not any("skipped" in m for m in notes2)
    # notes also reach the caller's log as they arise
    seen = []
    scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"size": 150}, "BONUS": {"size": 200}},
        log=seen.append)
    assert seen == notes


def test_an_ambiguous_font_is_noted_and_its_size_left_alone():
    fonts = [("FillFont", 3, FILL_METRICS, ()),
             ("FillFont", 13, OUTLINE_METRICS, ())]
    buf = _scene([("AWARD", "FillFont", (0.0, 0.0, 300.0, 40.0), 0, 2.0)],
                 fonts)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"size": 150, "dx": 1.0}})
    # the move still lands; the size does not, and says why
    assert n == 1 and len(patches) == 1
    assert any("several sizes" in m and "AWARD" in m for m in notes)


def test_an_unknown_string_is_a_note_and_no_patch():
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"NOT HERE": {"dx": 3.0, "size": 120}})
    assert (patches, n) == ([], 0)
    assert notes and "NOT HERE" in notes[0] and "left alone" in notes[0]


def test_junk_never_raises():
    assert scene_layout.text_layout_patches(
        b"\x00" * 4096, [], [], {"X": {"dx": 1.0}}) == ([], 0, [])
    assert scene_layout.text_layout_patches(
        b"", None, None, {"X": {"size": 120}}) == ([], 0, [])
    # a readable scene with junk in the edit row: the junk is ignored
    buf = _scene(AWARD)
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"AWARD": {"dx": "abc", "align": "sideways",
                                      "size": "huge"}, "X": None})
    assert (patches, n) == ([], 0)
    assert any("'X'" in m for m in notes)


# ---------------------------------------------------------------------------
# keyframes AFTER the stage header are found too (Godzilla's score HUD keeps
# 10 of its 16 lines there; the scans used to stop at the stage)
# ---------------------------------------------------------------------------

def _scene_with_late_keyframe():
    """AWARD before the stage as usual, plus a LATE instance keyframe that
    carries its own text after the instances — the shape of a HUD line."""
    out = bytearray(_scene(AWARD[:1]))
    # A real instance is followed by its tracks and the next instance's name;
    # the synthetic one is bare, and its tail bytes happen to parse as a
    # keyframe that would run into the block appended here.  Pad the gap the
    # way the real data does.
    out += b"\x00" * 64
    out += LATE_KEYFRAME
    return bytes(out)


LATE_KEYFRAME = _keyframe(9, "LATE", "FillFont",
                          rect=(10.0, 20.0, 300.0, 60.0), align=0,
                          spacing=2.0)


def test_offsets_reach_keyframes_after_the_stage():
    buf = _scene_with_late_keyframe()
    imgs, tables = _parse(buf)
    late_off = buf.index(LATE_KEYFRAME)
    lo = scene_layout.text_layout_offsets(buf, imgs, tables)
    assert set(lo) == {"AWARD", "LATE"}
    (kf,) = lo["LATE"]
    assert kf["off"] == late_off
    assert kf["align"] == 0 and kf["rect"] == [10.0, 20.0, 300.0, 60.0]
    assert kf["table"]["name"] == "FillFont"
    co = scene_layout.text_color_offsets(buf, imgs, tables)
    assert set(co) == {"AWARD", "LATE"}
    assert co["LATE"] == [(late_off + 32, [1.0, 1.0, 1.0, 1.0])]


def test_patches_move_a_keyframe_after_the_stage():
    buf = _scene_with_late_keyframe()
    imgs, tables = _parse(buf)
    patches, n, notes = scene_layout.text_layout_patches(
        buf, imgs, tables, {"LATE": {"dx": 5, "dy": -5, "align": "center"}})
    assert n == 1 and notes == []
    out = _apply(buf, patches)
    assert len(out) == len(buf)
    lo = scene_layout.text_layout_offsets(out, *_parse(out))
    (kf,) = lo["LATE"]
    assert kf["rect"] == [15.0, 15.0, 305.0, 55.0] and kf["align"] == 1
