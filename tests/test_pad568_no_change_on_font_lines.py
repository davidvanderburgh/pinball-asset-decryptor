"""PAD-568 (DragonRR): "Applying NO CHANGE to all lines of text doesn't affect the text in at
least several cases ... selecting no change on this target should revert the text to its
original card colours and it doesn't do anything.  RECOMMENDED DOES work".

The line (Godzilla's JET FIGHTER COLLECTED!) is in GameFont_Secondary, whose letters carry
their colours in the font's pictures, and Black and white on every image had those pictures
switched on.  A line's own profile that changes nothing resolved to "nothing to do", so the
line kept the font every line shares and stayed grey; and Apply to all lines of text left
every line in that font out ("its font's pictures correct it already").  Now No change on such
a line gives it its own copy of the font as the game has it (PAD-451's copy, made from the
pristine pictures), and Apply to all counts a line in when its font's pictures give it
another profile than the one applied.
"""
import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import (
    font_copy as FC, scene_edit as X, scene_tree as T, text_colour as TC)
from tests.test_pad451_line_own_font import (
    ART, BW, CARD, MINE, ORANGE, OTHER, P1, P2, SIZE, _atlases, _gf, _man, _seed_font,
    _texts, font_scene)

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

NONE = dict(cp.PRESETS)["none"]


def _bw_font(a, own=None, slots=(MINE,)):
    """Black and white on the files, the font's pictures switched on (All images), *slots*
    switched on with *own* as their own profile."""
    side = {cp.STOCK_IMAGES_KEY: True, cp.ASSET_KEY: cp._profile_dict(BW),
            cp.IMAGE_SLOTS_KEY: {"images/" + P1: True, "images/" + P2: True},
            cp.TEXT_SLOTS_KEY: {cp.text_rel(CARD, n): True for n in slots}}
    if own is not None:
        side[cp.FILE_PROFILES_KEY["text"]] = {
            cp.text_rel(CARD, n): cp._profile_dict(own) for n in slots}
    staged_changes.save(a, side)


def test_no_change_on_a_line_in_a_corrected_font_gives_it_the_font_as_the_game_has_it(tmp_path):
    a = str(tmp_path)
    _atlases(tmp_path)
    fonts = {"gf": _gf()}
    _bw_font(a, own=NONE)
    ops, written = TC.line_ops(a, CARD, _man(), fonts=fonts)
    assert ops == [{"op": "line_font", "node": MINE, "profile": cp._profile_dict(NONE),
                    "mul": None, "art": ART}]
    assert written == {MINE: {"font": True}}
    # the Individual files preview switch off: every line in its font's colours, no copy
    assert TC.line_ops(a, CARD, _man(), fonts=fonts, bake=False)[0] == []
    # the font's pictures left as the game has them: nothing to undo, no copy
    staged_changes.save(a, dict(staged_changes.load(a), **{cp.IMAGE_SLOTS_KEY: {}}))
    assert TC.line_ops(a, CARD, _man(), fonts=fonts)[0] == []
    # ... nor with them switched on at No change
    _bw_font(a, own=NONE)
    staged_changes.save(a, dict(staged_changes.load(a), **{cp.ASSET_KEY: cp._profile_dict(NONE)}))
    assert TC.line_ops(a, CARD, _man(), fonts=fonts)[0] == []


def test_font_looks_says_what_each_picture_carries(tmp_path):
    a = str(tmp_path)
    _atlases(tmp_path)
    _bw_font(a)
    data = staged_changes.peek(a)
    sw = {"font_pictures": [P1, P2]}
    looks = TC.font_looks(sw, data, cp.asset_resolver(a, data))
    assert [p.key() for p in looks] == [BW.key(), BW.key()]
    staged_changes.save(a, dict(data, **{cp.IMAGE_SLOTS_KEY: {"images/" + P1: True}}))
    data = staged_changes.peek(a)
    looks = TC.font_looks(sw, data, cp.asset_resolver(a, data))
    assert looks[0].key() == BW.key() and looks[1] is None


def test_the_preview_draws_it_from_the_font_as_it_was(tmp_path):
    from pinball_decryptor.plugins.stern import scene_eval as E
    a = str(tmp_path)
    _atlases(tmp_path)
    _bw_font(a, own=NONE)
    man = _man()
    ops, _w = TC.line_ops(a, CARD, man, fonts={"gf": _gf()})
    drawn = X.apply_manifest(man, ops)[0]
    by = {d["text"]: d for d in E.draw_list(drawn, 1) if d["kind"] == "text"}
    assert by["AB"]["art"] == {"profile": cp._profile_dict(NONE), "mul": None}
    assert by["BA"]["art"] is None                    # the shared, Black and white font


def test_the_write_gives_it_a_copy_in_the_games_colours(tmp_path):
    from pinball_decryptor.plugins.stern import dds, engine
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)
    a = str(folder)
    _bw_font(a, own=NONE)
    engine._LINES_SAID.v = {}
    new, n = engine._apply_tree_ops(font_scene(), CARD, [], X.names_of(_man()), a,
                                    lambda m, lvl="info": None)
    assert n >= 1
    sc = T.parse(new)
    fonts = FC.fonts_of(sc)
    assert len(fonts) == 2
    t = _texts(sc)
    assert t[51]["font"] != SIZE and t[53]["font"] == SIZE
    mine = fonts[1][1]
    assert mine.pages
    for _tid, (w, h, _fmt, _name, blob) in mine.pages.items():
        got = dds.decode_bc3(blob, w, h)[..., :3].reshape(-1, 3).astype(int)
        assert np.abs(got - np.asarray(ORANGE)).max() <= 8      # orange, not grey


# ---------------------------------------------------------------------------------------------
# the app: Apply to all lines of text
# ---------------------------------------------------------------------------------------------
def test_apply_no_change_to_all_lines_reaches_the_lines_in_a_corrected_font(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _wait
    from tests.test_pad471_all_text_lines import _layer, _on_line, _rel
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)
    a = str(folder)
    _bw_font(a, own=NONE)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert _wait(w, lambda: (_layer(w, OTHER).get("color") or {}).get("font_on") is True)
        _on_line(w, MINE)
        assert w.state("color")["file"]["kind"] == "text"
        w.answers.append("yes")
        assert w.call("color.apply_to_all", "all") is True
        q = w.asked[-1]
        assert "all 2 of them" in q["message"] and "left as" not in q["message"]
        assert w.window.service("color")._lines.left_out == 0
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE), _rel(OTHER)}
        assert cp.own_profile_names(a)["text"] == {_rel(MINE): "No change",
                                                   _rel(OTHER): "No change"}
        # and both lines get their own copy as the game has it
        ops, _w = TC.line_ops(a, CARD, _man(), fonts={"gf": _gf()})
        assert sorted(op["node"] for op in ops if op["op"] == "line_font") == [MINE, OTHER]
