"""PAD-452: a line of text's font, size and spacing, set on the Scenes tab's Font bar
(DragonRR: "font sizes, kerning, font type... and any other FEASIBLE normal font controls
given how fonts are made on the Stern system ... make sure that bounding boxes still work").

How Stern makes them (census of Godzilla LE 1.16's 194 scenes, 2,541 lines): a scene carries
its fonts in its library, each baked at fixed SIZES (one glyph table per size; a style -
GameFont_Primary - is a named variant of a typeface).  A Text names one size by id, lists a
styled size once per line of its text and a plain one not at all, and carries its own
LineSpacing and LetterSpacing.  It has no size of its own: the game scales a line as it scales
its node.  So a new font is another size the scene carries, a new size is the nearest baked
one with the node scaled the rest of the way (its rect shrunk by as much, so the box stays on
the glass), and spacing, wrapping and shrink-to-fit are the Text's own fields."""

import math
import struct

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    scene_edit as X, scene_eval as E, scene_render as R, scene_tree as T)
from tests.test_stern_scene_tree import (                                      # noqa: E402
    FLAG, bitmap, cls, fs, mat, node, s, sprite, texture, u8, u32, u64)


# ---------------------------------------------------------------------------------------------
# a scene with a font: STERN_Test plain at 40 (size 101), its GameFont_Primary style at 30
# (102) and 60 (103); "KAI / JU" in 102 (its outline drawn by a second node sharing the
# Text, as the game's outline and fill pairs are), "PLAIN" in 101 inside a node scaled 2x,
# and a picture
# ---------------------------------------------------------------------------------------------
def _glyph(ch, gid, page):
    return struct.pack("<H", ch) + u32(FLAG | gid) + fs(*range(7)) + b"\0" + fs(0, 0, 1, 1) \
        + page + u64(0)


def _font_entry(key=1):
    page = u32(FLAG | 120) + u32(4) + u32(4) + u32(5) + s("") + u32(16) + b"\x07" * 16

    def size(sid, line, asc, desc, gid, pg):
        return (u32(900) + u32(FLAG | sid) + u32(key) + fs(line, asc, desc) + b"\0" + u64(1)
                + _glyph(0x41, gid, pg))
    body = (u32(key) + s("") + s("STERN_Test") + b"\0\0" + u64(1) + struct.pack("<H", 0x41)
            + u64(1) + size(101, 40, 32, 8, 110, page)
            + u64(1) + s("GameFont_Primary") + u64(2)
            + size(102, 30, 24, 6, 111, u32(120)) + size(103, 60, 48, 12, 112, u32(120)))
    return u32(key) + u32(FLAG | 9) + s("Font") + u32(FLAG | 100) + body


def _text(sym, string, font, fonts=(), used=(), rect=(-2, -2, 200, 40), flags=(1, 0),
          spacing=(2, 0), tail=(0, 0)):
    return (u32(sym) + s("") + fs(*rect) + fs(1, 1, 1, 1) + u8(flags[0]) + u8(flags[1]) + u32(1)
            + fs(*spacing) + s(string) + u32(font)
            + u64(len(fonts)) + b"".join(s(n) + u32(i) for n, i in fonts)
            + u64(len(used)) + b"".join(u32(x) for x in used) + u8(tail[0]) + u32(tail[1]))


def font_scene():
    kids = [
        node(50, "Title", [u32(1) + cls(3, "Text") + u32(FLAG | 13)
                           + _text(5, "KAI\nJU", 102, [("GameFont_Primary", 102)], [102, 102])],
             tracks=((1, mat(1.0, 100, 50)),)),
        node(51, "Title_Outline", [u32(1) + cls(3) + u32(13)], tracks=((1, mat(1.0, 103, 53)),)),
        node(52, "Plain", [u32(1) + cls(3) + u32(FLAG | 14) + _text(5, "PLAIN", 101)],
             tracks=((1, mat(2.0, 300, 300)),)),
        # a picture, so the project lists the scene
        node(53, "Art", [u32(1) + cls(4, "Bitmap") + u32(FLAG | 15)
                         + bitmap(6, 16, 8, texture(21, 16, 8))]),
    ]
    return (u8(1) + u64(1) + _font_entry() + u64(0) + u32(1360) + u32(768) + fs(30.0)
            + fs(0, 0, 0, 1) + sprite(2, "", 1, kids))


TITLE, OUTLINE, PLAIN = 50, 51, 52


def _man():
    return E.manifest(T.parse(font_scene()))


def _texts(man, nid):
    n = X._man_index(man)[nid][0]
    return [man["objects"][str(oid)] for _s, oid in n["comps"]
            if man["objects"][str(oid)].get("kind") == "Text"]


def _glass_box(man, nid):
    d = next(d for d in E.draw_list(man, 1) if d["node"] == nid)
    L, T_, R_, B = d["rect"]
    a, b, c, dd, tx, ty = d["m"]
    return [round(v, 3) for v in (a * L + c * T_ + tx, b * L + dd * T_ + ty,
                                  a * R_ + c * B + tx, b * R_ + dd * B + ty)]


def _card_texts(sc):
    return {n.id: c.obj.body for n, _p, _d in sc.walk() for c in n.components
            if c.obj.kind == "Text"}


# ---------------------------------------------------------------------------------------------
def test_a_scene_names_its_fonts_and_comes_back_byte_for_byte():
    data = font_scene()
    sc = T.parse(data)
    assert T.serialize(sc) == data
    assert {sid: (i["variant"], i["face"], i["line"]) for sid, i in sc.font_sizes.items()} == {
        101: ("", "STERN_Test", 40.0), 102: ("GameFont_Primary", "STERN_Test", 30.0),
        103: ("GameFont_Primary", "STERN_Test", 60.0)}
    man = E.manifest(sc)
    assert {k: (f["variant"], f["face"], f["line"]) for k, f in man["fonts"].items()} == {
        "101": ("", "STERN_Test", 40.0), "102": ("GameFont_Primary", "STERN_Test", 30.0),
        "103": ("GameFont_Primary", "STERN_Test", 60.0)}
    assert sorted(X.font_table(man)) == [101, 102, 103]
    # a manifest from before the table: the sizes its lines are drawn in
    old = dict(man)
    del old["fonts"]
    table = X.font_table(old)
    assert sorted(table) == [101, 102] and table[102]["variant"] == "GameFont_Primary"
    assert table[101]["variant"] == ""


def test_a_new_size_keeps_the_box_where_it_is_on_the_glass():
    man = _man()
    boxes = {n: _glass_box(man, n) for n in (TITLE, OUTLINE, PLAIN)}
    op = {"op": "text_font", "node": TITLE, "font": 103, "s": 0.75}
    got, notes = X.apply_manifest(man, [op])
    assert notes == []
    o = _texts(got, TITLE)[0]
    assert (o["font_id"], o["line"], o["ascent"], o["styled"], o["font_name"]) == \
        (103, 60.0, 48.0, True, "GameFont_Primary")
    assert o["rect"] == [-2.0, -2.0, round(-2 + 202 / 0.75, 3), round(-2 + 42 / 0.75, 3)]
    # the words are 60 * 0.75 = 45 px tall on the glass; the box has not moved
    d = next(d for d in E.draw_list(got, 1) if d["node"] == TITLE)
    assert abs(d["line"] * math.hypot(d["m"][2], d["m"][3]) - 45.0) < 1e-6
    for n in (TITLE, OUTLINE, PLAIN):
        assert _glass_box(got, n) == boxes[n]
    # the outline drawing the same Text grew with it, so the two stay together
    t = X._man_index(got)
    assert t[OUTLINE][0]["tr"][0][1][0] == 0.75 and t[TITLE][0]["tr"][0][1][0] == 0.75
    assert t[PLAIN][0]["tr"][0][1][0] == 2.0


def test_write_puts_the_same_font_and_size_on_the_card():
    man = _man()
    ops = [{"op": "text_font", "node": TITLE, "font": 103, "s": 0.75},
           {"op": "text_font", "node": PLAIN, "font": 102, "s": 1.25}]
    want, notes = X.apply_manifest(man, ops)
    assert notes == []
    sc = T.parse(font_scene())
    assert X.apply_scene(sc, ops, names=X.names_of(man)) == (2, [])
    back = T.parse(T.serialize(sc))
    got = E.manifest(back)
    for nid in (TITLE, OUTLINE, PLAIN):
        assert _glass_box(got, nid) == _glass_box(want, nid)
        g, w = _texts(got, nid)[0], _texts(want, nid)[0]
        assert (g["font_id"], g["rect"], g["styled"]) == (w["font_id"], w["rect"], w["styled"])
    body = _card_texts(back)
    # a styled size: named by its style, listed once per line of the text, as the game's are
    assert body[TITLE]["fonts"] == [("GameFont_Primary", 103)] and body[TITLE]["used"] == [103, 103]
    assert body[PLAIN]["fonts"] == [("GameFont_Primary", 102)] and body[PLAIN]["used"] == [102]


def test_a_plain_size_is_named_by_neither_list():
    sc = T.parse(font_scene())
    ops = [{"op": "text_font", "node": TITLE, "font": 101, "s": 1.0}]
    assert X.apply_scene(sc, ops) == (1, [])
    body = _card_texts(T.parse(T.serialize(sc)))
    assert (body[TITLE]["font"], body[TITLE]["fonts"], body[TITLE]["used"]) == (101, [], [])
    got, _n = X.apply_manifest(_man(), ops)
    o = _texts(got, TITLE)[0]
    assert (o["font_id"], o["styled"], o["font_name"]) == (101, False, "")


def test_a_size_the_card_does_not_carry_leaves_the_line_alone():
    data = font_scene()
    sc = T.parse(data)
    op = {"op": "text_font", "node": TITLE, "font": 999, "s": 2.0}
    n, notes = X.apply_scene(sc, [op])
    assert n == 0 and "no font size 999" in notes[0]
    assert T.serialize(sc) == data
    got, notes = X.apply_manifest(_man(), [op])
    assert notes and _glass_box(got, TITLE) == _glass_box(_man(), TITLE)
    assert _texts(got, TITLE)[0]["font_id"] == 102


def test_spacing_and_wrapping_set_the_texts_own_numbers():
    ops = [{"op": "text_spacing", "node": TITLE, "letter": 7.5, "line": -3.0},
           {"op": "text_flow", "node": TITLE, "multiline": False, "wrap": True, "fit": True}]
    got, notes = X.apply_manifest(_man(), ops)
    assert notes == []
    o = _texts(got, TITLE)[0]
    assert (o["spacing"], o["flags"], o["fit"]) == ([-3.0, 7.5], [0, 1], 1)
    sc = T.parse(font_scene())
    assert X.apply_scene(sc, ops) == (2, [])
    data = T.serialize(sc)
    assert len(data) == len(font_scene())                 # patched in place
    b = _card_texts(T.parse(data))[TITLE]
    assert (list(b["spacing"]), b["flags"], b["tail"]) == ([-3.0, 7.5], (0, 1), (1, 0))
    # one field alone leaves the other as it is
    got, _n = X.apply_manifest(_man(), [{"op": "text_spacing", "node": TITLE, "letter": 4}])
    assert _texts(got, TITLE)[0]["spacing"] == [2.0, 4.0]


def test_a_line_the_game_lays_out_keeps_shrinking_to_fit():
    man = _man()
    o = _texts(man, TITLE)[0]
    o.update(game_layout=True, fit=1, valign=1)
    got, _n = X.apply_manifest(man, [{"op": "text_flow", "node": TITLE, "fit": False}])
    assert _texts(got, TITLE)[0]["fit"] == 1


def test_font_edits_fold_into_one_and_say_what_they_did(tmp_path):
    a = str(tmp_path)
    X.add(a, "/c", {"op": "text_spacing", "node": TITLE, "letter": 3})
    X.add(a, "/c", {"op": "text_spacing", "node": TITLE, "line": 5})
    X.add(a, "/c", {"op": "text_font", "node": TITLE, "font": 103, "s": 0.5, "style": "A"})
    X.add(a, "/c", {"op": "text_font", "node": TITLE, "font": None, "s": 3.0, "px": 90})
    ops = X.ops_for(a, "/c")
    assert ops == [{"op": "text_spacing", "node": TITLE, "letter": 3, "line": 5},
                   {"op": "text_font", "node": TITLE, "font": 103, "s": 1.5, "style": "A",
                    "px": 90}]
    assert X.describe(ops[0]) == "letter spacing 3 px, line spacing 5 px"
    assert X.describe(ops[1]) == "font A, 90 px"
    assert X.describe({"op": "text_spacing", "node": 1, "letter": 3.917, "letter_px": 6}) ==         "letter spacing 6 px"
    assert X.describe({"op": "text_flow", "node": 1, "wrap": True, "fit": False}) == \
        "wraps in its box, does not shrink to fit"
    # folded, the two sizes are the one size: the same box on the glass either way
    one, _n = X.apply_manifest(_man(), ops[1:])
    two, _n = X.apply_manifest(_man(), [{"op": "text_font", "node": TITLE, "font": 103, "s": 0.5},
                                        {"op": "text_font", "node": TITLE, "font": None, "s": 3.0}])
    assert _glass_box(one, TITLE) == _glass_box(two, TITLE) == _glass_box(_man(), TITLE)
    assert _texts(one, TITLE)[0]["rect"] == _texts(two, TITLE)[0]["rect"]


# ---------------------------------------------------------------------------------------------
# the preview draws LetterSpacing: the pen moves on that much more after every letter (Stern's
# own initials entry sets it so W and _ of other sizes step alike: 71 + 22 = 93 ~ 82 + 11.75)
# ---------------------------------------------------------------------------------------------
def _font(adv=10.0, lw=8.0):
    g = {"adv": adv, "bx": 0.0, "by": 8.0, "lw": lw, "lh": 10.0, "kern": {}}
    return {"glyphs": {ord("A"): dict(g), 0x20: dict(g, lw=0.0, lh=0.0)}, "has_metrics": True,
            "ascent": 8, "descent": 2}


def test_letter_spacing_moves_each_letter_on():
    f = _font()
    assert R._metrics(f, "AAA")[0] == 28.0
    assert R._metrics(f, "AAA", 5.0)[0] == 38.0
    assert R._metrics(f, "A A", 5.0)[0] == 38.0                 # a space is spaced too
    assert R.letter_spacing({"spacing": [2, 7.5]}) == 7.5
    assert R.letter_spacing({}) == 0.0
    # wider letters wrap sooner in the same box
    measure = R._measure(f, None, 0.0)
    assert R.text_lines("AAA AAA", 75, True, measure) == ["AAA AAA"]
    assert R.text_lines("AAA AAA", 75, True, R._measure(f, None, 5.0)) == ["AAA", "AAA"]


def test_each_letter_spacing_draws_its_own_letters():
    f = _font()
    a = R.ink_maker(f, {"font": "k", "font_px": 30, "spacing": [2, 0]}, {})
    b = R.ink_maker(f, {"font": "k", "font_px": 30, "spacing": [2, 6]}, {})
    assert a.key != b.key and b.key[2] == 6.0


# ---------------------------------------------------------------------------------------------
# the Font bar's calls, on a project holding the scene
# ---------------------------------------------------------------------------------------------
def test_the_font_bar_sets_font_size_and_spacing(tmp_path):
    from tests.test_gui_scene_editor import _seed, _open, _tv, _ops
    from tests.webui_harness import web_app
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, font_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", TITLE)
        f = _tv(w)["props"]["font"]
        assert (f["style"], f["size"], f["letter"], f["line"]) == ("GameFont_Primary", 30.0, 0.0, 2.0)
        assert [(st["value"], st["sizes"]) for st in f["styles"]] == [
            ("GameFont_Primary", [30.0, 60.0]), ("STERN_Test", [40.0])]
        assert (f["multiline"], f["wrap"], f["fit"], f["edited"]) == (True, False, False, False)
        # 45 px: the 60 px size, drawn at three quarters
        assert w.call("text_scenes.tree_text_size", TITLE, 45)
        assert _ops(folder)[-1] == {"op": "text_font", "node": TITLE, "font": 103, "s": 0.75,
                                    "px": 45.0}
        f = _tv(w)["props"]["font"]
        assert (f["style"], f["size"], f["edited"]) == ("GameFont_Primary", 45.0, True)
        # the sizes the scene's fonts were made at are still those
        assert [st["sizes"] for st in f["styles"]] == [[30.0, 60.0], [40.0]]
        # another font keeps the size: STERN_Test's 40 px drawn at 45
        assert w.call("text_scenes.tree_text_font", TITLE, "STERN_Test")
        f = _tv(w)["props"]["font"]
        assert (f["style"], f["size"]) == ("STERN_Test", 45.0)
        assert [st["sizes"] for st in f["styles"]] == [[30.0, 60.0], [40.0]]
        assert [o.get("style") for o in _ops(folder)] == ["STERN_Test"]      # one size edit
        assert not w.call("text_scenes.tree_text_font", TITLE, "STERN_Test")
        # spacing in screen pixels: the Text's own number is that over its scale
        assert w.call("text_scenes.tree_text_spacing", TITLE, 9, None)
        assert abs(_ops(folder)[-1]["letter"] - 9 / (0.75 * 1.5)) < 1e-3
        assert _ops(folder)[-1]["letter_px"] == 9.0
        assert _tv(w)["props"]["font"]["letter"] == 9.0
        assert w.call("text_scenes.tree_text_flow", TITLE, None, True, True)
        f = _tv(w)["props"]["font"]
        assert (f["wrap"], f["fit"]) == (True, True)
        assert not w.call("text_scenes.tree_text_flow", TITLE, None, True, True)
        # Font as shipped: all of it off in one step
        assert w.call("text_scenes.tree_text_font_reset", TITLE)
        assert _ops(folder) == []
        f = _tv(w)["props"]["font"]
        assert (f["style"], f["size"], f["letter"], f["edited"]) == ("GameFont_Primary", 30.0, 0.0, False)
        # the line in the node scaled 2x: its size is what the glass shows
        assert w.call("text_scenes.tree_select", PLAIN)
        assert _tv(w)["props"]["font"]["size"] == 80.0
        w.call("text_scenes.close")


def test_a_shorter_line_is_padded_where_its_new_layout_hides_it():
    """The Write pads a shorter replacement where the line's layout hides the spaces (PAD-412):
    a line that keeps its breaks takes them as a line of spaces under the words; with its
    breaks turned off on the Font bar the game would run that line on after the words, so
    it is padded on both sides instead, as any centred line is."""
    from pinball_decryptor.plugins.stern import engine
    data = font_scene()
    looks = engine._radium_text_looks(data)["KAI\nJU"]
    assert engine._padded_text(b"A\nB", 7, looks) == b"A\nB\n   "
    off = [{"op": "text_flow", "node": TITLE, "multiline": False}]
    looks = engine._radium_text_looks(data, off)["KAI\nJU"]
    assert engine._padded_text(b"A\nB", 7, looks) == b"  A\nB  "


def test_a_line_is_as_wide_as_its_letters_reach_not_its_last_spacing():
    """Emulator (Godzilla LE 1.16, language screen): "December 19, 1965" centred with
    LetterSpacing 20 grew by 20 px per GAP between its 17 letters (320 px), not per letter:
    the game centres it where its letters reach.  Drawn so, the preview put every letter
    where the game did, within the 2 px an unedited line shows."""
    from PIL import Image
    from pinball_decryptor.plugins.stern import fontrender as fr
    g = {"adv": 10.0, "bx": 0.0, "by": 8.0, "lw": 10.0, "lh": 10.0, "kern": {}, "rot": 0}
    font = {"glyphs": {ord("A"): g}, "has_metrics": True, "ascent": 8, "descent": 2}
    cell = lambda _g: Image.new("RGBA", (10, 10), (255, 255, 255, 255))      # noqa: E731
    w0 = fr.render_text(font, "AAA", slice_loader=cell)[0].size[0]
    w5 = fr.render_text(font, "AAA", slice_loader=cell, tracking=5)[0].size[0]
    assert (w0, w5) == (30, 40)                                  # two gaps, not three letters
