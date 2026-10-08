"""PAD-451 (DragonRR): "when I click a piece of text to change its colour ALL text of the same
type changes colour ... IF possible make it so that we can change each text layer
individually. If that isn't possible then we need to make this clear to the user".

A font whose letters carry their own colours (Godzilla's orange GameFont_Secondary) has them
in its pictures, which every line in that font shares, in every scene (PAD-438), so one line
cannot be corrected apart from the others.  Its palette says so: marked shared, with the
font's name, how many lines here and scenes in all it reaches, and the lines that share it
lit up.  And it is the palette of EVERY picture of the font: GameFont_Secondary's letters
fill three (A-F on one, G, H, K and M-Z on the next), and switching only the first left half
of KAIJU BATTLE SELECT uncorrected on the card while the preview showed it all corrected.
"""
import json
import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_edit as X, text_colour as TC

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

ORANGE = (220, 130, 20)
P1, P2 = "scene_textures/gf_1.png", "scene_textures/gf_2.png"
BW = dict(cp.PRESETS)["bw"]
DARK = cp.Profile(name="Darker mids", gamma=(2.0, 2.0, 2.0))


def _atlases(tmp_path, colour=ORANGE):
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True, exist_ok=True)
    for rel in (P1, P2):
        im = PIL.new("RGBA", (32, 32), (0, 0, 0, 0))
        im.paste(colour + (255,), (4, 4, 28, 28))
        im.save(str(tmp_path / "images" / rel))
    return tex


def _font(**kw):
    f = {"key": "gf", "name": "GameFont_Secondary", "atlas_rels": [P1, P2]}
    f.update(kw)
    return f


# ---------------------------------------------------------------------------------------------
# the font's pictures and its reach (plugins.stern.text_colour)
# ---------------------------------------------------------------------------------------------
def test_a_coloured_fonts_switch_is_every_picture_its_letters_are_cut_from(tmp_path):
    _atlases(tmp_path)
    a = str(tmp_path)
    assert TC.font_pictures(a, _font()) == [P1, P2]
    assert TC.font_picture(a, _font()) == P1
    # a size drawn from a picture of its own is one of them too
    small = _font(atlas_rels=[P1], sizes={7: {"atlas_rels": [P2]}})
    assert TC.font_pictures(a, small) == [P1, P2]
    white = tmp_path / "images" / "scene_textures" / "white.png"
    PIL.new("RGBA", (32, 32), (255, 255, 255, 255)).save(str(white))
    assert TC.font_pictures(a, {"atlas_rels": ["scene_textures/white.png"]}) == []


def test_how_many_scenes_a_fonts_pictures_reach(tmp_path):
    tex = _atlases(tmp_path)
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\n"
        "%s\t/g/a/scene.radium\n%s\t/g/b/scene.radium\n%s\t/g/a/scene.radium\n"
        "%s\t/g/c/scene.radium\nscene_textures/other.png\t/g/d/scene.radium\n"
        % (P1, P1, P2, P2), encoding="utf-8")
    a = str(tmp_path)
    assert TC.font_scenes(a, [P1]) == 2
    assert TC.font_scenes(a, [P1, P2]) == 3                  # a, b and c, each once
    assert TC.font_scenes(str(tmp_path / "none"), [P1]) == 0


def test_a_line_in_a_coloured_font_names_all_its_pictures(tmp_path):
    from tests.test_pad438_text_colour_profile import _man, TITLE
    _atlases(tmp_path)
    a = str(tmp_path)
    man = _man()
    n = X._man_index(man)[TITLE][0]
    TC._text_of(man, n)[1]["font"] = "gf"
    assert TC.line_switch(a, "/g/a/scene.radium", man, n, (), {}, {"gf": _font()}) == {
        "font_picture": P1, "font_pictures": [P1, P2], "font": "GameFont_Secondary"}


# ---------------------------------------------------------------------------------------------
# the Layers list's switch (webui.text_scenes_tree._text_switch)
# ---------------------------------------------------------------------------------------------
def test_the_layers_switch_is_shared_and_on_only_with_every_picture(tmp_path):
    from pinball_decryptor.webui.text_scenes_tree import _text_switch
    from tests.test_pad438_text_colour_profile import _man, TITLE
    tex = _atlases(tmp_path)
    (tex / "radium_images.txt").write_text(
        "%s\t/g/a/scene.radium\n%s\t/g/b/scene.radium\n" % (P1, P2), encoding="utf-8")
    a = str(tmp_path)
    man = _man()
    n = X._man_index(man)[TITLE][0]
    TC._text_of(man, n)[1]["font"] = "gf"
    fonts = {"gf": _font()}

    def sw(slots, unlocked=True):
        return _text_switch(a, "/g/a/scene.radium", man, n, (), {}, fonts, {},
                            {"images": slots}, unlocked, ())
    off = sw({})
    assert off == {"on": False, "own": True, "rel": "images/" + P1, "stock": True,
                   "font": "GameFont_Secondary", "kind": "images", "shared": True,
                   "pages": ["images/" + P1, "images/" + P2], "scenes": 2}
    # the first picture alone is not the font: the line is not corrected yet
    half = sw({"images/" + P1: True})
    assert half["on"] is False and half["part"] == 1
    both = sw({"images/" + P1: True, "images/" + P2: True})
    assert both["on"] is True and "part" not in both
    # locked: a blue lock that still says it is the font's
    locked = sw({}, unlocked=False)
    assert locked["locked"] is True and locked["shared"] is True and "on" not in locked


# ---------------------------------------------------------------------------------------------
# the preview: each letter through its own picture's profile
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


def _draw():
    return {"kind": "text", "text": "AB", "font": "gf", "font_px": 4, "rgba": (1, 1, 1, 1),
            "rect": (0, 0, 16, 8), "align": 0, "mul": (1.0, 1.0, 1.0, 1.0),
            "add": (0, 0, 0, 0), "m": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)}


def _colours(img):
    return {tuple(c) for c in np.asarray(img).astype(int)[..., :3].reshape(-1, 3)}


def _grey(prof):
    return tuple(int(v) for v in prof.apply_array(np.asarray([[ORANGE]], np.uint8))[0, 0])


def test_a_letter_takes_its_own_pictures_profile_in_the_preview(tmp_path, paged):
    from pinball_decryptor.plugins.stern import scene_render as R
    a = str(tmp_path)
    on = lambda prof: {"path": None, "colour": prof, "stock": True}  # noqa: E731
    # only B's picture switched on (the Images tab): A stays orange, B is corrected
    inks = {}
    img = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=paged,
                        pictures={P2: on(BW)}, sizes={}, inks=inks)
    assert ORANGE in _colours(img) and _grey(BW) in _colours(img)
    assert any(len(k) == 4 and k[2] == "cp" for k in inks)      # kept for the next frame
    # every picture with its own profile: each letter its own
    img = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=paged,
                        pictures={P1: on(DARK), P2: on(BW)}, sizes={})
    assert {_grey(DARK), _grey(BW)} <= _colours(img) and ORANGE not in _colours(img)
    # the font switched on as one (the Scenes palette): every letter through it
    img = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=paged,
                        pictures={P1: on(BW), P2: on(BW)}, sizes={})
    assert _grey(BW) in _colours(img) and ORANGE not in _colours(img)


# ---------------------------------------------------------------------------------------------
# the app: the palette switches every picture, the Colors bar profiles them all
# ---------------------------------------------------------------------------------------------
def _seed_font(folder):
    """The scene editor's synthetic project with its line drawn in a two-picture coloured
    font: the glyph manifest names it and the scene's Text uses it."""
    from tests.test_gui_scene_editor import CARD, _seed
    from tests.test_pad438_text_colour_profile import TITLE
    _seed(folder)
    tex = _atlases(folder)
    rows = []
    for ch, page in (("A", P1), ("B", P2)):
        g = "scene_textures/glyphs/gf/U+%04X_%s.png" % (ord(ch), ch)
        os.makedirs(os.path.dirname(str(folder / "images" / g)), exist_ok=True)
        PIL.new("RGBA", (3, 4), ORANGE + (255,)).save(str(folder / "images" / g))
        rows.append("%s\t%s\t0x%x\t0\t0\t3\t4\tGameFont_Secondary" % (g, page, ord(ch)))
    (tex / "glyph_images.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    with open(str(tex / "radium_images.txt"), "a", encoding="utf-8") as f:
        f.write("%s\t%s\n%s\t%s\n%s\t/g/scene2/scene.radium\n" % (P1, CARD, P2, CARD, P2))
    tree = json.loads((tex / "scene_tree.json").read_text(encoding="utf-8"))
    man = tree[CARD]
    n = X._man_index(man)[TITLE][0]
    TC._text_of(man, n)[1]["font"] = "gf"
    (tex / "scene_tree.json").write_text(json.dumps(tree), encoding="utf-8")
    return CARD, TITLE


def test_the_scenes_palette_of_a_shared_font_switches_all_its_pictures(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _tv, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _card, title = _seed_font(folder)
    d = str(folder)
    cp.store_asset_profile(d, BW)
    pages = ["images/" + P1, "images/" + P2]
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)

        def _layer():
            return next((l for l in _tv(w)["layers"] if l["id"] == title), {})
        assert _wait(w, lambda: (_layer().get("color") or {}).get("locked") is True)
        c = _layer()["color"]
        assert c["shared"] is True and c["font"] == "GameFont_Secondary"
        assert c["pages"] == pages and c["scenes"] == 2 and c["lines"] == 1
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is False)
        assert w.call("text_scenes.tree_color", title, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        slots = staged_changes.load(d).get("image_color_slots") or {}
        assert all(slots.get(p) is True for p in pages), slots
        # the Colors bar on it: a profile of its own goes on both pictures, Undo takes both
        assert w.call("color.panel_open")
        assert w.call("color.set_file", "images", pages[0], "GameFont_Secondary", True,
                      {"ns": "scenes", "node": title}, "GameFont_Secondary", pages)
        w.drain()
        f = w.state("color")["file"]
        assert f["font"] == "GameFont_Secondary" and f["pages"] == 2
        w.call("color.set_params", {"name": "Font red", "gain": [1.3, 0.9, 0.9]})
        w.drain()
        assert [cp.own_profile(d, "images", p).name for p in pages] == ["Font red"] * 2
        assert w.call("color.undo")
        assert [cp.own_profile(d, "images", p) for p in pages] == [None, None]
        assert w.call("color.preset", "bw")
        assert all(cp.own_profile(d, "images", p) is not None for p in pages)
        assert w.call("color.file_shared")
        assert [cp.own_profile(d, "images", p) for p in pages] == [None, None]
        # off again: every picture
        assert w.call("text_scenes.tree_color", title, False)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is False)
        slots = staged_changes.load(d).get("image_color_slots") or {}
        assert not any(slots.get(p) for p in pages), slots


def test_the_page_marks_and_says_a_shared_palette():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = os.path.join(here, "pinball_decryptor", "webui", "static", "js")

    def src(*p):
        with open(os.path.join(js, *p), encoding="utf-8") as f:
            return f.read()
    scenes = src("tabs", "text_scenes.js")
    assert 'l.color.shared && "shared"' in scenes
    assert 'name="link" cls="ly-share"' in scenes
    assert '"ly-font-hot"' in scenes and "setHotFont(l.color.pages[0])" in scenes
    assert "A line in this font cannot have a color profile of its own." in scenes
    assert "  link: " in src("core", "ui.js")
    pane = src("tabs", "color_pane.js")
    assert '"This font"' in pane and "file.font || null, file.pages || null" in pane
    assert "pages: c.shared ? c.pages || null : null" in src("tabs", "scenes.js")
