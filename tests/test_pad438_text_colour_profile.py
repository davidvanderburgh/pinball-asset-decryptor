"""PAD-438 (DragonRR): "colour profile text ... make it work exactly like images. Same
pallets, locks, and so on".

A line of text is its font's letters times the colours the scene gives it.  For a font of
white letters the colour is the line's own, so a switched-on line gets the individual files
profile in that colour (the Text's, or its node's colour track for a styled font, whose Text
colour the game ignores); a font whose letters carry their own colours has them in its atlas
picture, so the line's switch is that picture's.  Game lines are locked until the unlock box
is ticked; an added line has its own switch; each can have a profile of its own.
"""
import json

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import (
    engine, scene_edit as X, scene_eval as E, scene_tree as T, text_colour as TC)
from tests.test_stern_scene_tree import scene
from tests.test_stern_text_colors import _FakeReader

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

CARD = "/godzilla_le/assets/lcd/demand_loaded/abc/scene.radium"
TITLE = 53                                     # the synthetic scene's line of text
GREEN = [0.37, 0.94, 0.15]
#: a profile that is not its own repeat (black and white is: grey stays grey)
DARK = cp.Profile(name="Darker mids", gamma=(2.0, 2.0, 2.0))
BW = dict(cp.PRESETS)["bw"]


def _data(rgb=GREEN):
    """The synthetic scene with its line of text drawn in *rgb*."""
    sc = T.parse(scene())
    for n, _p, _d in sc.walk():
        if n.id == TITLE:
            n.components[0].obj.body["rgba"] = list(rgb) + [1.0]
    return T.serialize(sc)


def _man(data=None):
    return E.manifest(T.parse(data or _data()))


def _project(tmp_path, ops=(), prof=DARK, unlocked=True, slots=(TITLE,), data=None):
    a = str(tmp_path)
    if ops:
        X.save(a, {CARD: list(ops)})
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True, exist_ok=True)
    (tex / "scene_tree.json").write_text(json.dumps({CARD: _man(data)}), encoding="utf-8")
    side = {}
    if unlocked:
        side[cp.STOCK_IMAGES_KEY] = True
    if prof is not None:
        side[cp.ASSET_KEY] = cp._profile_dict(prof)
    if slots:
        side[cp.TEXT_SLOTS_KEY] = {cp.text_rel(CARD, n): True for n in slots}
    staged_changes.save(a, side)
    return a


def _text(man, nid=TITLE):
    n = X._man_index(man)[nid][0]
    return n, TC._text_of(man, n)[1]


def _drawn(man, name="Title"):
    return [d for d in E.draw_list(man, 1) if d["kind"] == "text"
            and d["path"][-1] == name][0]


# ---------------------------------------------------------------------------------------------
# the switches and the profiles (core.colour_profile)
# ---------------------------------------------------------------------------------------------
def test_a_line_has_switches_counts_and_a_profile_of_its_own(tmp_path):
    a = str(tmp_path)
    rel = cp.text_rel(CARD, TITLE)
    assert rel == CARD + "#53"
    cp.set_text_slot(a, rel, True)
    assert cp.asset_settings(a)["text"] == {rel: True}
    assert cp.text_lines_on(a) == set()                   # a game line needs the unlock
    data = staged_changes.load(a)
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(a, data)
    assert cp.text_lines_on(a) == {rel}
    X.save(a, {CARD: [{"op": "add_text", "id": X.FIRST_ADDED_ID, "color": True},
                      {"op": "add_text", "id": X.FIRST_ADDED_ID + 1}]})
    assert cp.asset_counts(a)["text"] == 2                # one game line, one added line
    sig = cp.asset_signature(a)
    cp.store_own_profile(a, "text", rel, DARK)
    assert cp.own_profile(a, "text", rel) == DARK
    assert cp.own_profile_names(a)["text"] == {rel: "Darker mids"}
    assert cp.asset_resolver(a)("text", rel) == DARK
    assert cp.asset_signature(a) != sig
    cp.drop_text_slots(a)
    assert cp.asset_settings(a)["text"] == {}


def test_a_font_with_colours_of_its_own_is_told_apart(tmp_path):
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    white = PIL.new("RGBA", (32, 32), (0, 0, 0, 0))
    white.paste((255, 255, 255, 255), (4, 4, 28, 28))
    white.paste((0, 0, 0, 255), (4, 4, 28, 8))            # a black outline is no colour
    white.save(str(tex / "white.png"))
    orange = PIL.new("RGBA", (32, 32), (0, 0, 0, 0))
    orange.paste((220, 130, 20, 255), (4, 4, 28, 28))
    orange.save(str(tex / "orange.png"))
    a = str(tmp_path)
    assert TC.font_picture(a, {"atlas_rels": ["scene_textures/white.png"]}) is None
    assert TC.font_picture(a, {"atlas_rels": ["scene_textures/orange.png"]}) == \
        "scene_textures/orange.png"


# ---------------------------------------------------------------------------------------------
# the line's colour (plugins.stern.text_colour)
# ---------------------------------------------------------------------------------------------
def test_a_plain_lines_own_colour_gets_the_profile_on_both_sides(tmp_path):
    a = _project(tmp_path)
    man = _man()
    ops, written = TC.line_ops(a, CARD, man)
    want = TC.corrected(DARK, GREEN)
    assert ops == [{"op": "line_colour", "node": TITLE, "rgb": want}]
    assert written[TITLE]["base_rgb"] == pytest.approx(GREEN, abs=1e-4)
    preview = X.apply_manifest(man, ops)[0]
    assert _drawn(preview)["rgba"][:3] == pytest.approx(want)
    assert _drawn(preview)["profiled"]                   # a Text tab recolour is in it
    sc = T.parse(_data())
    n, notes = X.apply_scene(sc, ops, names=X.names_of(man))
    assert (n, notes) == (1, [])
    card = E.manifest(T.parse(T.serialize(sc)))
    assert _drawn(card)["rgba"][:3] == pytest.approx(want, abs=1e-5)
    assert len(T.serialize(sc)) == len(_data())           # size-neutral: patched in place


def test_a_styled_lines_colour_is_its_track(tmp_path):
    """A styled game font draws its letters' own colours times the node's colour track (the
    Text's colour ignored): a line tinted green gets the profile in its track."""
    a = _project(tmp_path, prof=BW)
    tint = [{"op": "tint", "node": TITLE, "mul": GREEN + [1.0]}]
    man = X.apply_manifest(_man(_data((1, 1, 1))), tint)[0]
    _n, o = _text(man)
    o["styled"] = True
    ops, _w = TC.line_ops(a, CARD, man, tint)
    (op,) = ops
    assert "rgb" not in op
    grey = TC.corrected(BW, GREEN)
    assert grey[0] == pytest.approx(grey[1]) == pytest.approx(grey[2])
    assert op["col"][0][1] == pytest.approx(grey + [1.0])
    drawn = _drawn(X.apply_manifest(man, ops)[0])
    assert drawn["mul"][:3] == pytest.approx(grey)
    # white letters on a white track stay white: nothing to write
    plain = _man(_data((1, 1, 1)))
    _text(plain)[1]["styled"] = True
    assert TC.line_ops(a, CARD, plain)[0] == []


def test_a_shared_text_moves_its_colour_into_the_track(tmp_path):
    """A drop shadow draws the same Text: the line's colours go into its track (the Text
    white), and the shadow keeps its own look."""
    a = _project(tmp_path)
    shadow = [{"op": "shadow", "node": TITLE, "id": X.FIRST_ADDED_ID, "dx": 4, "dy": 4,
               "mul": [0, 0, 0, 0.6]}]
    man = X.apply_manifest(_man(), shadow)[0]
    before = _drawn(man, "Title_Shadow")
    ops, _w = TC.line_ops(a, CARD, man, shadow)
    by = {op["node"]: op for op in ops}
    assert by[TITLE]["rgb"] == [1.0, 1.0, 1.0]
    assert by[TITLE]["col"][0][1][:3] == pytest.approx(TC.corrected(DARK, GREEN))
    after = X.apply_manifest(man, ops)[0]
    line = _drawn(after)
    assert [line["rgba"][i] * line["mul"][i] for i in range(3)] == pytest.approx(
        TC.corrected(DARK, GREEN))
    sh = _drawn(after, "Title_Shadow")
    assert [sh["rgba"][i] * sh["mul"][i] for i in range(4)] == pytest.approx(
        [before["rgba"][i] * before["mul"][i] for i in range(4)], abs=1e-4)


def test_game_lines_are_locked_until_unlocked_and_added_lines_have_their_own(tmp_path):
    a = _project(tmp_path, unlocked=False)
    man = _man()
    n, _o = _text(man)
    assert TC.line_switch(a, CARD, man, n) == {"locked": True, "line": True}
    assert TC.line_ops(a, CARD, man)[0] == []
    add = {"op": "add_text", "parent": None, "index": 99, "id": X.FIRST_ADDED_ID,
           "name": "Mine", "text": "MINE", "x": 0, "y": 0, "like": TITLE,
           "rgba": [0.2, 0.9, 0.2, 1.0]}
    man = X.apply_manifest(_man(), [add])[0]
    mine = X._man_index(man)[X.FIRST_ADDED_ID][0]
    assert TC.line_switch(a, CARD, man, mine, [add]) == {
        "line": True, "on": False, "own": False, "added": True,
        "rel": cp.text_rel(CARD, X.FIRST_ADDED_ID)}
    on = dict(add, color=True)
    assert TC.line_switch(a, CARD, man, mine, [on])["on"] is True
    ops, _w = TC.line_ops(a, CARD, man, [on])
    assert ops == [{"op": "line_colour", "node": X.FIRST_ADDED_ID,
                    "rgb": TC.corrected(DARK, [0.2, 0.9, 0.2])}]
    # its own profile wins over the project's
    cp.store_own_profile(a, "text", cp.text_rel(CARD, X.FIRST_ADDED_ID), BW)
    assert TC.line_ops(a, CARD, man, [on])[0][0]["rgb"] == TC.corrected(BW, [0.2, 0.9, 0.2])
    # a shadow takes its line's colour: no switch of its own
    sh = X.apply_manifest(_man(), [{"op": "shadow", "node": TITLE, "id": 9, "dx": 1,
                                    "dy": 1, "mul": [0, 0, 0, 1]}])[0]
    assert TC.line_switch(a, CARD, sh, X._man_index(sh)[9][0]) is None


def test_a_line_read_back_from_a_built_card_is_never_corrected_twice(tmp_path):
    a = _project(tmp_path)
    ops, written = TC.line_ops(a, CARD, _man())
    TC.remember(a, CARD, written)
    built = _man(_data(ops[0]["rgb"]))                     # the project read off that card
    again, _w = TC.line_ops(a, CARD, built)
    assert again[0]["rgb"] == ops[0]["rgb"]
    # switched off: the line gets its own colour back
    cp.set_text_slot(a, cp.text_rel(CARD, TITLE), None)
    back, _w = TC.line_ops(a, CARD, built)
    assert back == [{"op": "line_colour", "node": TITLE,
                     "rgb": pytest.approx(GREEN, abs=1e-4)}]
    # the preview's Individual files switch off draws it in its own colours too
    cp.set_text_slot(a, cp.text_rel(CARD, TITLE), True)
    assert TC.line_ops(a, CARD, built, bake=False)[0][0]["rgb"] == pytest.approx(
        GREEN, abs=1e-4)


# ---------------------------------------------------------------------------------------------
# the Write
# ---------------------------------------------------------------------------------------------
def test_the_write_corrects_a_switched_on_line_in_place(tmp_path):
    """A scene whose only change is a switched-on line is written, in place."""
    a = _project(tmp_path)
    data = _data()
    engine._LINES_SAID.v = {}                  # said once per Write, not once per process
    ov, msgs = {}, []
    writes, n, whole = engine._scene_tree_plan(
        _FakeReader({CARD: data}), a, lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False, False, ov)
    assert (n, whole) == (1, {}) and writes
    new = bytearray(data)
    for off, b in writes:                      # the fake reader maps file offset == disk
        new[off:off + len(b)] = b
    back = E.manifest(T.parse(bytes(new)))
    assert _drawn(back)["rgba"][:3] == pytest.approx(TC.corrected(DARK, GREEN), abs=1e-5)
    assert any("color profile goes into 1 line" in m for _l, m in msgs)
    assert TC.load_record(a)[CARD][str(TITLE)]["rgb"] == TC.corrected(DARK, GREEN)
    # nothing switched on and nothing written before: no scene to write
    cp.drop_text_slots(a)
    (tmp_path / "images" / "scene_textures" / "text_colours_written.json").unlink()
    assert engine._scene_tree_plan(_FakeReader({CARD: data}), a, lambda *x, **k: None,
                                   lambda: False, False, {})[:2] == ([], 0)


# ---------------------------------------------------------------------------------------------
# the preview
# ---------------------------------------------------------------------------------------------
INK = (220, 130, 20)
ID = (1.0, 0.0, 0.0, 1.0)


@pytest.fixture
def fonts(monkeypatch):
    """One fake font whose every line is a solid INK block, cut from atlas.png."""
    from pinball_decryptor.plugins.stern import fontrender as fr
    font = {"key": "f", "ascent": 4, "descent": 0,
            "atlas_rels": ["scene_textures/atlas.png"]}
    monkeypatch.setattr(fr, "font_at_size", lambda f, px: f)
    monkeypatch.setattr(fr, "font_fmt", lambda f: 0)
    monkeypatch.setattr(fr, "render_text",
                        lambda f, s, **k: (PIL.new("RGBA", (6, 4), INK + (255,)), []))
    return [font]


def _draw(**kw):
    d = {"kind": "text", "text": "HI", "font": "f", "font_px": 4, "rgba": (1, 1, 1, 1),
         "rect": (0, 0, 16, 8), "align": 0, "mul": (1.0, 1.0, 1.0, 1.0),
         "add": (0, 0, 0, 0), "m": ID + (0.0, 0.0)}
    d.update(kw)
    return d


def _colours(img):
    a = np.asarray(img).astype(int)[..., :3].reshape(-1, 3)
    return {tuple(c) for c in a}


def test_a_coloured_font_is_drawn_through_its_pictures_profile(tmp_path, fonts):
    from pinball_decryptor.plugins.stern import scene_render as R
    a = str(tmp_path)
    plain = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=fonts,
                          pictures={}, sizes={})
    assert INK in _colours(plain)
    pics = {"scene_textures/atlas.png": {"path": None, "colour": BW, "stock": True}}
    inks = {}
    grey = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=fonts,
                         pictures=pics, sizes={}, inks=inks)
    g = tuple(BW.apply_array(np.asarray([[INK]], np.uint8))[0, 0])
    assert g in _colours(grey) and INK not in _colours(grey)
    assert any(len(k) == 4 and k[2] == "cp" for k in inks)  # kept for the next frame


def test_a_corrected_line_is_not_recoloured_by_its_text_tab_colour(tmp_path, fonts,
                                                                    monkeypatch):
    from pinball_decryptor.plugins.stern import fontrender as fr, scene_render as R
    a = str(tmp_path)
    ink = PIL.new("RGBA", (6, 4), (255, 255, 255, 255))
    monkeypatch.setattr(fr, "render_text", lambda f, s, **k: (ink, []))
    picked = R.render_tree(a, {"stage": [16, 16, 30]}, draws=[_draw()], fonts=fonts,
                           pictures={}, sizes={}, colors={"HI": (255, 0, 0)})
    assert (255, 0, 0) in _colours(picked)
    mine = R.render_tree(a, {"stage": [16, 16, 30]},
                         draws=[_draw(rgba=(0, 0.5, 0, 1), profiled=True)], fonts=fonts,
                         pictures={}, sizes={}, colors={"HI": (255, 0, 0)})
    assert (255, 0, 0) not in _colours(mine)
    assert any(r == 0 and 126 <= g <= 128 and b == 0 for r, g, b in _colours(mine))


# ---------------------------------------------------------------------------------------------
# the Layers list
# ---------------------------------------------------------------------------------------------
def test_scenes_layers_give_a_line_of_text_a_palette(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import CARD as SCENE, _seed, _open, _tv, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _data())
    d = str(folder)
    cp.store_asset_profile(d, DARK)
    rel = cp.text_rel(SCENE, TITLE)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)

        def _layer():
            return next((l for l in _tv(w)["layers"] if l["id"] == TITLE), {})
        assert _layer()["color"] == {"locked": True, "line": True, "kind": "text"}
        assert not w.call("text_scenes.tree_color", TITLE, True)  # a lock has no switch
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert _wait(w, lambda: _layer().get("color") == {
            "line": True, "on": False, "own": True, "rel": rel, "stock": True,
            "kind": "text"})
        assert w.call("text_scenes.tree_color", TITLE, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        assert cp.text_lines_on(d) == {rel}
        assert cp.asset_counts(d)["text"] == 1
        # the preview draws it corrected
        assert _wait(w, lambda: [round(v, 3) for v in
                                 _drawn(w.window.service("text").scenes._tman)["rgba"][:3]]
                     == [round(v, 3) for v in TC.corrected(DARK, GREEN)])
        # the Colors bar can give it a profile of its own
        assert w.call("color.set_file", "text", rel, "Title", True,
                      {"ns": "scenes", "node": TITLE})
        assert w.window.service("color")._file["kind"] == "text"
        # locked again: the switch goes with the box
        assert w.call("text_scenes.tree_color_unlocked", False)
        assert _wait(w, lambda: _layer().get("color") == {
            "locked": True, "line": True, "kind": "text"})
        assert cp.asset_settings(d)["text"] == {}


# ---------------------------------------------------------------------------------------------
# save / load edits (PAD-369's file carries the lines too)
# ---------------------------------------------------------------------------------------------
def test_a_saved_file_carries_the_lines_switches_and_profiles(tmp_path):
    import zipfile
    from pinball_decryptor.plugins.stern import scene_share
    add = {"op": "add_text", "parent": None, "index": 99, "id": X.FIRST_ADDED_ID,
           "name": "Mine", "text": "MINE", "x": 0, "y": 0, "like": TITLE, "color": True}
    a = _project(tmp_path / "a", ops=[add])
    mine = cp.text_rel(CARD, X.FIRST_ADDED_ID)
    cp.store_own_profile(a, "text", mine, BW)
    out = str(tmp_path / "lines.zip")
    assert scene_share.export_all(a, out, [CARD], {CARD: _man()})[0] == 1
    with zipfile.ZipFile(out) as z:
        doc = json.loads(z.read(X.SHARE_MANIFEST))
    assert doc["lines"] == {CARD: {
        str(TITLE): {"color": True, "profile": cp._profile_dict(DARK)},
        str(X.FIRST_ADDED_ID): {"color": True, "profile": cp._profile_dict(BW)}}}
    # loaded into another project: the game line's switch waits for the unlock box there,
    # the added line's rides in its edit, and each keeps the profile the file gave it
    b = _project(tmp_path / "b", prof=None, unlocked=False, slots=())
    extras = scene_share.read_extras(out)
    assert scene_share.has_extras(extras)
    X.import_edits(b, out, [CARD])
    assert scene_share.import_extras(b, out, extras, cards_here=[CARD]) == ([], [])
    assert cp.asset_settings(b)["text"] == {cp.text_rel(CARD, TITLE): True}
    assert cp.text_lines_on(b) == set()
    assert cp.own_profile(b, "text", cp.text_rel(CARD, TITLE)) == DARK
    assert cp.own_profile(b, "text", mine) == BW
    assert X.ops_for(b, CARD)[0]["color"] is True
    # a scene the project does not have is left out
    c = _project(tmp_path / "c", prof=None, unlocked=False, slots=())
    scene_share.import_extras(c, out, extras, cards_here=["/other/scene.radium"])
    assert cp.asset_settings(c)["text"] == {}
