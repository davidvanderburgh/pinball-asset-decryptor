"""PAD-451 (DragonRR): "when I click a piece of text to change its colour ALL text of the same
type changes colour ... IF possible make it so that we can change each text layer
individually".

A font whose letters carry their own colours (Godzilla's orange GameFont_Secondary) has them
in its pictures, which every line drawn in it shares, in every scene (PAD-438).  A line of it
switched on now gets its OWN copy of the font size it is drawn at, the profile baked into the
copy's pictures (:mod:`font_copy`): the preview draws it so, the Write adds the copy to the
scene and points the line at it, and every other line keeps the font as it was.  A card built
with copies, read again, is never copied twice, and a line switched off gets the game's font
back.

Also here: a font's letters can fill several pictures (GameFont_Secondary: A-F on one, G, H, K
and M-Z on the next), and the preview draws each letter through ITS picture's profile when the
Images tab switches them apart.
"""
import json
import os
import struct

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import (
    font_copy as FC, scene_edit as X, scene_eval as E, scene_tree as T, text_colour as TC)
from tests.test_stern_scene_tree import FLAG, cls, fs, node, s, sprite, u8, u32, u64

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

ORANGE = (220, 130, 20)
P1, P2 = "scene_textures/gf_1.png", "scene_textures/gf_2.png"
ART = {str(ord("A")): P1, str(ord("B")): P2}
BW = dict(cp.PRESETS)["bw"]
DARK = cp.Profile(name="Darker mids", gamma=(2.0, 2.0, 2.0))
CARD = "/g/scene1/scene.radium"
MINE, OTHER = 50, 52                     # the nodes drawing "AB" and "BA" in the font
SIZE = 5                                 # the font size they draw with


# ---------------------------------------------------------------------------------------------
# a scene with a game font: one variant, one size, its letters on two pictures
# ---------------------------------------------------------------------------------------------
def _bc3(rgb, w=8, h=8):
    from pinball_decryptor.plugins.stern import dds
    arr = np.zeros((h, w, 4), np.uint8)
    arr[...] = tuple(rgb) + (255,)
    return dds.encode_bc3(arr)


def _glyph(ch, gid, page):
    return (struct.pack("<H", ord(ch)) + u32(FLAG | gid) + fs(*([1.0] * 7)) + u8(0)
            + fs(0, 0, 1, 1) + page + u64(0))


def _page(tid, blob):
    return u32(FLAG | tid) + u32(8) + u32(8) + u32(5) + s("") + u32(len(blob)) + blob


def _font_entry(key=3):
    size = (u32(1400) + u32(FLAG | SIZE) + u32(key) + fs(30, 24, 6) + u8(1) + u64(2)
            + _glyph("A", 6, _page(7, _bc3(ORANGE))) + _glyph("B", 8, _page(9, _bc3(ORANGE))))
    return (u32(key) + cls(1, "Font") + u32(FLAG | 4) + u32(key) + s("") + s("FACE")
            + u8(0) + u8(0) + u64(2) + struct.pack("<2H", 65, 66)
            + u64(0) + u64(1) + s("GameFont_Secondary") + u64(1) + size)


def _text(string):
    return (u32(3) + s("") + fs(-2, -2, 200, 40) + fs(1, 1, 1, 1) + u8(1) + u8(1) + u32(1)
            + fs(2, 0) + s(string) + u32(SIZE) + u64(1) + s("GameFont_Secondary") + u32(SIZE)
            + u64(1) + u32(SIZE) + u8(0) + u32(0))


def font_scene():
    kids = [node(MINE, "Mine", [u32(1) + cls(2, "Text") + u32(FLAG | 51) + _text("AB")]),
            node(OTHER, "Other", [u32(1) + cls(2) + u32(FLAG | 53) + _text("BA")])]
    return (u8(1) + u64(1) + _font_entry() + u64(0) + u32(1360) + u32(768) + fs(30.0)
            + fs(0, 0, 0, 1) + sprite(10, "", 1, kids))


def _atlases(folder, colour=ORANGE, size=8):
    tex = folder / "images" / "scene_textures"
    tex.mkdir(parents=True, exist_ok=True)
    for rel in (P1, P2):
        PIL.new("RGBA", (size, size), tuple(colour) + (255,)).save(
            str(folder / "images" / rel))
    return tex


def _gf(**kw):
    f = {"key": "gf", "name": "GameFont_Secondary", "atlas_rels": [P1, P2],
         "glyphs": {65: {"atlas_rel": P1}, 66: {"atlas_rel": P2}}}
    f.update(kw)
    return f


def _man(data=None):
    return E.manifest(T.parse(data or font_scene()), font_of={SIZE: ("gf", 0)})


def _texts(sc):
    return {o.id: o.body for o in sc.objects.values() if o.kind == "Text"}


def _op(node=MINE, prof=BW, mul=None):
    return {"op": "line_font", "node": node, "profile": cp._profile_dict(prof), "mul": mul,
            "art": ART}


def _grey(prof, rgb=ORANGE):
    return np.asarray(prof.apply_array(np.asarray([[rgb]], np.uint8))[0, 0], int)


# ---------------------------------------------------------------------------------------------
# the copy (plugins.stern.font_copy, through scene_edit.apply_scene)
# ---------------------------------------------------------------------------------------------
def test_a_line_gets_its_own_copy_of_its_font_size_with_the_profile_in_it(tmp_path):
    from pinball_decryptor.plugins.stern import dds
    _atlases(tmp_path)
    data = font_scene()
    sc = T.parse(data)
    assert T.serialize(sc) == data
    assert X.apply_scene(sc, [_op()], str(tmp_path), {}) == (1, [])
    new = T.serialize(sc)
    back = T.parse(new)                                   # the grown scene walks
    fonts = FC.fonts_of(back)
    assert [i for i, _f in fonts] == [0, 1]               # right after the font it copies
    game, mine = fonts[0][1], fonts[1][1]
    # known by its shape: the game finds fonts by name, so a copy keeps every one of them
    # (emulator: a copy named apart crashed Godzilla as its screen came up)
    assert game.copied_from is None and mine.copied_from == SIZE
    assert (mine.name, mine.face) == (game.name, game.face) == (b"", b"FACE")
    (variant, size), = mine.sizes
    assert variant == b"GameFont_Secondary"
    texts = _texts(back)
    assert texts[51]["font"] == size.id and texts[51]["used"] == [size.id]
    assert texts[51]["fonts"] == [(variant.decode(), size.id)]
    assert texts[53]["font"] == SIZE                      # the other line keeps the game's
    assert min(mine.ids()) > 53                           # fresh ids, past every one in use
    # its pictures: the profile in them; the game's own are untouched
    want = _grey(BW)
    for tid, (w, h, fmt, name, blob) in mine.pages.items():
        assert name == b"" and fmt == 5
        got = dds.decode_bc3(blob, w, h)[..., :3].reshape(-1, 3).astype(int)
        assert np.abs(got - want).max() <= 5               # BC3's 5:6:5 end points
    for tid, (w, h, fmt, name, blob) in game.pages.items():
        assert np.abs(dds.decode_bc3(blob, w, h)[..., :3].astype(int)
                      - np.asarray(ORANGE)).max() <= 5


def test_lines_with_one_look_share_a_copy_and_a_built_card_is_never_copied_twice(tmp_path):
    _atlases(tmp_path)
    a = str(tmp_path)
    sc = T.parse(font_scene())
    assert X.apply_scene(sc, [_op(MINE), _op(OTHER)], a, {})[0] == 2
    assert len(FC.fonts_of(sc)) == 2                      # one copy for both
    t = _texts(sc)
    assert t[51]["font"] == t[53]["font"] != SIZE
    built = T.serialize(sc)
    # the card built with it, read again: the line is copied from the GAME's size again, the
    # other gets the game's back, and the old copy goes
    sc = T.parse(built)
    X.apply_scene(sc, [_op(MINE, DARK), {"op": "line_font", "node": OTHER, "off": True}],
                  a, {})
    fonts = FC.fonts_of(sc)
    assert len(fonts) == 2 and fonts[1][1].copied_from == SIZE
    from pinball_decryptor.plugins.stern import dds
    w, h, _fmt, _n, blob = next(iter(fonts[1][1].pages.values()))
    got = dds.decode_bc3(blob, w, h)[..., :3].reshape(-1, 3).astype(int)
    assert np.abs(got - _grey(DARK)).max() <= 5           # from the game's orange, not grey
    t = _texts(sc)
    assert t[53]["font"] == SIZE and t[53]["fonts"] == [("GameFont_Secondary", SIZE)]
    # every line off: the scene is the game's again, byte for byte
    sc = T.parse(T.serialize(sc))
    X.apply_scene(sc, [{"op": "line_font", "node": n, "off": True} for n in (MINE, OTHER)],
                  a, {})
    assert T.serialize(sc) == font_scene()


def test_a_picture_missing_from_the_project_is_copied_from_the_scenes_own(tmp_path):
    from pinball_decryptor.plugins.stern import dds
    sc = T.parse(font_scene())                            # no PNGs in the project at all
    assert X.apply_scene(sc, [_op()], str(tmp_path), {}) == (1, [])
    mine = FC.fonts_of(sc)[1][1]
    for tid, (w, h, fmt, name, blob) in mine.pages.items():
        got = dds.decode_bc3(blob, w, h)[..., :3].reshape(-1, 3).astype(int)
        assert np.abs(got - _grey(BW)).max() <= 8          # BC3 twice (decoded, re-encoded)


# ---------------------------------------------------------------------------------------------
# the switch and the edits (plugins.stern.text_colour)
# ---------------------------------------------------------------------------------------------
def _project(tmp_path, slots=(MINE,), prof=BW):
    a = str(tmp_path)
    _atlases(tmp_path)
    side = {cp.STOCK_IMAGES_KEY: True, cp.ASSET_KEY: cp._profile_dict(prof),
            cp.TEXT_SLOTS_KEY: {cp.text_rel(CARD, n): True for n in slots}}
    staged_changes.save(a, side)
    return a


def test_a_line_in_a_coloured_font_has_a_switch_of_its_own(tmp_path):
    a = _project(tmp_path)
    man = _man()
    fonts = {"gf": _gf()}
    mine = X._man_index(man)[MINE][0]
    assert TC.line_switch(a, CARD, man, mine, (), None, fonts) == {
        "line": True, "on": True, "own": True, "rel": cp.text_rel(CARD, MINE), "stock": True,
        "art": True, "font": "GameFont_Secondary", "font_pictures": [P1, P2]}
    ops, written = TC.line_ops(a, CARD, man, fonts=fonts)
    assert ops == [{"op": "line_font", "node": MINE, "profile": cp._profile_dict(BW),
                    "mul": None, "art": ART}]
    assert written == {MINE: {"font": True}}
    # a tinted line: its tint is baked into its copy with the profile, its track set white
    tint = [{"op": "tint", "node": MINE, "mul": [0.5, 1.0, 1.0, 1.0]}]
    man = X.apply_manifest(_man(), tint)[0]
    ops, _w = TC.line_ops(a, CARD, man, tint, fonts=fonts)
    by = {op["op"]: op for op in ops}
    assert by["line_font"]["mul"] == [0.5, 1.0, 1.0]
    assert by["line_colour"]["col"][0][1] == [1.0, 1.0, 1.0, 1.0]
    # off, after a Write gave it its own font: the game's font back
    staged_changes.save(a, dict(staged_changes.load(a), **{cp.TEXT_SLOTS_KEY: {}}))
    TC.remember(a, CARD, {MINE: {"font": True}})
    assert TC.line_ops(a, CARD, _man(), fonts=fonts)[0] == [
        {"op": "line_font", "node": MINE, "off": True}]


def test_the_preview_draws_the_line_through_its_own_copy(tmp_path):
    a = _project(tmp_path)
    man = _man()
    ops, _w = TC.line_ops(a, CARD, man, fonts={"gf": _gf()})
    drawn = X.apply_manifest(man, ops)[0]
    t = [d for d in E.draw_list(drawn, 1) if d["kind"] == "text"]
    by = {d["text"]: d for d in t}
    assert by["AB"]["art"] == {"profile": cp._profile_dict(BW), "mul": None}
    assert by["BA"]["art"] is None


# ---------------------------------------------------------------------------------------------
# the preview (plugins.stern.scene_render)
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def paged(monkeypatch):
    """A font whose A is cut from P1 and B from P2, each a solid ORANGE block; render_text
    sets the letters side by side through its slice_loader, as the real one does."""
    from pinball_decryptor.plugins.stern import fontrender as fr
    metrics = {"lw": 3, "lh": 4, "bx": 0.0, "by": 4.0, "adv": 3.0, "kern": {}}
    glyphs = {ord("A"): dict(metrics, char=ord("A"), atlas_rel=P1),
              ord("B"): dict(metrics, char=ord("B"), atlas_rel=P2)}
    font = {"key": "gf", "ascent": 4, "descent": 0, "atlas_rels": [P1, P2],
            "glyphs": glyphs}
    monkeypatch.setattr(fr, "font_at_size", lambda f, px: f)
    monkeypatch.setattr(fr, "font_fmt", lambda f: 0)
    monkeypatch.setattr(fr, "load_slice", lambda g: PIL.new("RGBA", (3, 4), ORANGE + (255,)))

    def render_text(f, s, slice_loader=None, **k):
        out = PIL.new("RGBA", (3 * len(s), 4), (0, 0, 0, 0))
        for i, ch in enumerate(s):
            g = f["glyphs"][ord(ch)]
            out.paste((slice_loader or fr.load_slice)(g), (3 * i, 0))
        return out, set()
    monkeypatch.setattr(fr, "render_text", render_text)
    return [font]


def _draw(**kw):
    d = {"kind": "text", "text": "AB", "font": "gf", "font_px": 4, "rgba": (1, 1, 1, 1),
         "rect": (0, 0, 16, 8), "align": 0, "mul": (1.0, 1.0, 1.0, 1.0),
         "add": (0, 0, 0, 0), "m": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)}
    d.update(kw)
    return d


def _colours(img):
    return {tuple(c) for c in np.asarray(img).astype(int)[..., :3].reshape(-1, 3)}


def _on(prof):
    return {"path": None, "colour": prof, "stock": True}


def _render(a, fonts, **kw):
    from pinball_decryptor.plugins.stern import scene_render as R
    pictures = kw.pop("pictures", {})
    return R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw(**kw)], fonts=fonts,
                         pictures=pictures, sizes={})


def test_a_line_with_its_own_font_is_drawn_through_it(tmp_path, paged):
    a = str(tmp_path)
    img = _render(a, paged, art={"profile": cp._profile_dict(BW), "mul": None})
    assert tuple(_grey(BW)) in _colours(img) and ORANGE not in _colours(img)
    # its own colour is baked in with the profile
    half = (110, 130, 20)
    img = _render(a, paged, art={"profile": cp._profile_dict(BW), "mul": [0.5, 1.0, 1.0]})
    assert tuple(_grey(BW, half)) in _colours(img)
    # the font's pictures switched on (Images tab) do not reach it: it is drawn from the
    # font as it was, as its copy is made
    img = _render(a, paged, art={"profile": cp._profile_dict(BW), "mul": None},
                  pictures={P1: _on(DARK), P2: _on(DARK)})
    assert tuple(_grey(BW)) in _colours(img) and tuple(_grey(DARK)) not in _colours(img)


def test_a_letter_takes_its_own_pictures_profile_in_the_preview(tmp_path, paged):
    a = str(tmp_path)
    # only B's picture switched on (the Images tab): A stays orange, B is corrected
    img = _render(a, paged, pictures={P2: _on(BW)})
    assert ORANGE in _colours(img) and tuple(_grey(BW)) in _colours(img)
    # each picture its own profile: each letter its own
    img = _render(a, paged, pictures={P1: _on(DARK), P2: _on(BW)})
    assert {tuple(_grey(DARK)), tuple(_grey(BW))} <= _colours(img)
    assert ORANGE not in _colours(img)
    # the font switched on as one: every letter through it
    img = _render(a, paged, pictures={P1: _on(BW), P2: _on(BW)})
    assert tuple(_grey(BW)) in _colours(img) and ORANGE not in _colours(img)


# ---------------------------------------------------------------------------------------------
# the font's pictures (plugins.stern.text_colour)
# ---------------------------------------------------------------------------------------------
def test_a_coloured_fonts_pictures_and_how_far_they_reach(tmp_path):
    tex = _atlases(tmp_path)
    a = str(tmp_path)
    assert TC.font_pictures(a, _gf()) == [P1, P2]
    assert TC.font_picture(a, _gf()) == P1
    # a size drawn from a picture of its own is one of them too
    assert TC.font_pictures(a, _gf(atlas_rels=[P1], sizes={7: {"atlas_rels": [P2]}})) == \
        [P1, P2]
    PIL.new("RGBA", (8, 8), (255, 255, 255, 255)).save(str(tex / "white.png"))
    assert TC.font_pictures(a, {"atlas_rels": ["scene_textures/white.png"]}) == []
    assert TC.art_map(_gf()) == ART
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\n"
        "%s\t/g/a/scene.radium\n%s\t/g/b/scene.radium\n%s\t/g/a/scene.radium\n"
        "%s\t/g/c/scene.radium\nscene_textures/other.png\t/g/d/scene.radium\n"
        % (P1, P1, P2, P2), encoding="utf-8")
    assert TC.font_scenes(a, [P1]) == 2
    assert TC.font_scenes(a, [P1, P2]) == 3               # a, b and c, each once
    assert TC.font_scenes(str(tmp_path / "none"), [P1]) == 0


# ---------------------------------------------------------------------------------------------
# the Write (plugins.stern.engine)
# ---------------------------------------------------------------------------------------------
def _seed_font(folder):
    """The scene editor's project holding font_scene(): its manifest, the font's glyph rows
    and its two pictures."""
    from tests.test_gui_scene_editor import _seed
    _seed(folder, font_scene())
    tex = _atlases(folder)
    rows = []
    for ch, page in (("A", P1), ("B", P2)):
        g = "scene_textures/glyphs/gf/U+%04X_%s.png" % (ord(ch), ch)
        os.makedirs(os.path.dirname(str(folder / "images" / g)), exist_ok=True)
        PIL.new("RGBA", (3, 4), ORANGE + (255,)).save(str(folder / "images" / g))
        rows.append("%s\t%s\t0x%x\t0\t0\t3\t4\tGameFont_Secondary" % (g, page, ord(ch)))
    (tex / "glyph_images.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tex / "scene_tree.json").write_text(json.dumps({CARD: _man()}), encoding="utf-8")
    # the scene is listed by the pictures it draws: its font's
    with open(str(tex / "radium_images.txt"), "a", encoding="utf-8") as f:
        for i, rel in enumerate((P1, P2)):
            f.write("%s\t%s\t%d\t64\t8\t8\t5\n" % (rel, CARD, 1000 + 100 * i))


def test_the_write_adds_the_copy_and_points_the_line_at_it(tmp_path):
    from pinball_decryptor.plugins.stern import engine
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)
    a = str(folder)
    staged_changes.save(a, {cp.STOCK_IMAGES_KEY: True, cp.ASSET_KEY: cp._profile_dict(BW),
                            cp.TEXT_SLOTS_KEY: {cp.text_rel(CARD, MINE): True}})
    engine._LINES_SAID.v = {}
    msgs = []
    new, n = engine._apply_tree_ops(font_scene(), CARD, [], X.names_of(_man()), a,
                                    lambda m, lvl="info": msgs.append((lvl, m)))
    assert n >= 1 and len(new) > len(font_scene())        # it grows: an image build
    sc = T.parse(new)
    assert len(FC.fonts_of(sc)) == 2
    t = _texts(sc)
    assert t[51]["font"] != SIZE and t[53]["font"] == SIZE
    assert any("goes into 1 line(s)" in m for _l, m in msgs), msgs
    assert TC.load_record(a)[CARD][str(MINE)]["font"] is True


# ---------------------------------------------------------------------------------------------
# the app: the Layers palette is the line's own
# ---------------------------------------------------------------------------------------------
def test_the_scenes_palette_of_a_coloured_font_line_is_its_own(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _tv, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)
    d = str(folder)
    cp.store_asset_profile(d, BW)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)

        def _layer(nid=MINE):
            return next((l for l in _tv(w)["layers"] if l["id"] == nid), {})
        assert _wait(w, lambda: (_layer().get("color") or {}).get("locked") is True)
        assert _layer()["color"]["art"] is True
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is False)
        c = _layer()["color"]
        assert c["kind"] == "text" and c["rel"] == cp.text_rel(CARD, MINE)
        assert c["font"] == "GameFont_Secondary" and c["font_on"] is False
        assert c["font_pictures"] == ["images/" + P1, "images/" + P2]
        assert w.call("text_scenes.tree_color", MINE, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        # its own switch, not its font's pictures: the other line stays off
        assert cp.text_lines_on(d) == {cp.text_rel(CARD, MINE)}
        assert not (staged_changes.load(d).get("image_color_slots") or {})
        assert (_layer(OTHER).get("color") or {}).get("on") is False
        # the preview draws it through its own copy
        man = w.window.service("text").scenes._tman
        o = TC._text_of(man, X._man_index(man)[MINE][0])[1]
        assert o["art"]["profile"] == cp._profile_dict(BW)
        assert "art" not in TC._text_of(man, X._man_index(man)[OTHER][0])[1]


def test_the_page_says_what_a_coloured_font_lines_palette_does():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "pinball_decryptor", "webui", "static", "js", "tabs",
                           "text_scenes.js"), encoding="utf-8") as f:
        src = f.read()
    assert "this line gets its own copy of that font" in src
    assert "attach the profile to ${pics} on the Images tab" in src
    assert 'l.color.font_on && "via-font"' in src and 'name="link" cls="ly-share"' in src
