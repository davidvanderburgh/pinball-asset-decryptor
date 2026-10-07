"""PAD-433: a line of text's alignment in its box, set on the Scenes tab (DragonRR: "basic
text controls - left and right, top and bottom and centre ... reflected the same in PAD
output and in game").  One edit sets the Text's alignment word and its VerticalAlignment
(PAD-412: the record's last u32, 0 top, 1 middle, 2 bottom), so the preview and the card
read the same two values."""

import pytest

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    engine, scene_edit as X, scene_eval as E, scene_tree as T)
from tests.test_stern_scene_tree import scene                                  # noqa: E402

OP = {"op": "text_align", "node": 53, "align": 2, "valign": 1}


def _texts(sc):
    return [o for o in sc.objects.values() if o.kind == "Text"]


def test_the_preview_draws_with_the_new_alignment():
    man = E.manifest(T.parse(scene()))
    got, notes = X.apply_manifest(man, [OP])
    assert notes == []
    draws = [d for d in E.draw_list(got, 1) if d["kind"] == "text" and d["node"] == 53]
    assert draws and all((d["align"], d["valign"]) == (2, 1) for d in draws)


def test_write_puts_the_same_alignment_on_the_card():
    man = E.manifest(T.parse(scene()))
    sc = T.parse(scene())
    fit_before = {o.id: o.body["tail"][0] for o in _texts(sc)}
    assert X.apply_scene(sc, [OP], names=X.names_of(man)) == (1, [])
    back = T.parse(T.serialize(sc))
    man2 = E.manifest(back)
    node_texts = [d for d in E.draw_list(man2, 1) if d["kind"] == "text" and d["node"] == 53]
    assert node_texts and all((d["align"], d["valign"]) == (2, 1) for d in node_texts)
    # ScaleToBounds, the byte before VerticalAlignment, is left as it was
    assert all(o.body["tail"][0] == fit_before[o.id] for o in _texts(back))
    # the same length: an alignment is patched in place, like a move
    assert len(T.serialize(sc)) == len(scene())


def test_picking_again_is_one_edit(tmp_path):
    a = str(tmp_path)
    X.add(a, "/c", dict(OP))
    X.add(a, "/c", dict(OP, align=0, valign=2))
    assert X.ops_for(a, "/c") == [dict(OP, align=0, valign=2)]
    assert X.describe(X.ops_for(a, "/c")[0]) == "aligned bottom left"


def test_padding_follows_the_alignment_the_same_write_sets():
    """A shorter replacement's padding goes where the alignment hides it (PAD-412); with a new
    alignment pending, it goes where the NEW one hides it."""
    data = scene()
    text = _texts(T.parse(data))[0].body["text"].decode("latin1")
    node = next(n.id for n, _p, _d in T.parse(data).walk()
                if any(c.obj.kind == "Text" for c in n.components))
    right = [{"op": "text_align", "node": node, "align": 2, "valign": 0}]
    assert {a for a, _m, _t, _f in engine._radium_text_looks(data, right)[text]} == {2}
    left = [{"op": "text_align", "node": node, "align": 0, "valign": 0}]
    assert engine._padded_text(b"AB", 5, engine._radium_text_looks(data, left)[text]) \
        == b"AB   "


@pytest.mark.parametrize("v", ["top", "middle", "bottom"])
def test_alignment_names_are_the_values(v):
    assert X.VALIGN_NAMES.index(v) == {"top": 0, "middle": 1, "bottom": 2}[v]


def test_the_scenes_buttons_set_the_alignment_and_show_it(tmp_path):
    from tests.test_gui_scene_editor import _seed, _open, _tv, _ops
    from tests.webui_harness import web_app
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_select", title)
        p = _tv(w)["props"]
        assert p["align"] in X.ALIGN_NAMES and p["valign"] == "top"
        assert w.call("text_scenes.tree_text_align", title, None, "bottom")
        assert _tv(w)["props"]["valign"] == "bottom" and _tv(w)["props"]["align"] == p["align"]
        assert w.call("text_scenes.tree_text_align", title, "left", None)
        q = _tv(w)["props"]
        assert (q["align"], q["valign"]) == ("left", "bottom")
        assert [o["op"] for o in _ops(folder)] == ["text_align"]
        assert (_ops(folder)[0]["align"], _ops(folder)[0]["valign"]) == (0, 2)
        # the same again changes nothing
        assert not w.call("text_scenes.tree_text_align", title, "left", "bottom")
        w.call("text_scenes.close")


# ---------------------------------------------------------------------------------------------
# round 2: the game lays some lines out itself. Godzilla's BDL elements wrap every Text on their
# list in a FlashyText, which sets VerticalAlignment middle and ScaleToBounds; emulator (LE
# 1.16): the Gigan intro's BATTLE FOR TOKYO drew at the same rows stored top, middle and bottom
# ---------------------------------------------------------------------------------------------
import json  # noqa: E402
import os  # noqa: E402

from pinball_decryptor.plugins.stern import game_text_layout as G  # noqa: E402

GIGAN = ("/godzilla_le/assets/lcd/auto_loaded/a248977badd032e625ee2480e8cc6d0b2f645d1f/"
         "e5793bce06a18e840f98aca8e14dbdbd0547ab60/scene.radium")
#: a Godzilla LE 1.16 extract's project folder (the PAD-412 rig's): skipped without it
PROJ = r"C:\tmp\pad412\v4\gz"


def _paths(man):
    out = {}

    def walk(kids, prefix):
        for n in kids or ():
            path = prefix + [n["name"]]
            for _s, oid in n["comps"]:
                o = man["objects"].get(str(oid)) or {}
                if o.get("kind") == "Text":
                    out[".".join(path)] = n["id"]
                if o.get("kind") in ("Sprite", "StreamingFlipbook"):
                    walk(o.get("kids"), path)
    walk(man["root"]["kids"], [])
    return out


def test_the_table_names_scenes_and_node_paths():
    assert len(G.GAME_LAID_OUT) >= 40
    for key, paths in G.GAME_LAID_OUT.items():
        a, b = key.split("/")
        assert len(a) == len(b) == 40 and paths
    assert G.scene_key(GIGAN) == ("a248977badd032e625ee2480e8cc6d0b2f645d1f/"
                                  "e5793bce06a18e840f98aca8e14dbdbd0547ab60")
    assert "Lines_Textbox.Line1_Instance" in G.paths_for(GIGAN)
    assert G.paths_for("/g/scene1/scene.radium") == ()


def test_the_editor_draws_a_game_laid_out_line_in_the_middle(tmp_path, monkeypatch):
    from tests.test_gui_scene_editor import _seed, _open, _tv
    from tests.webui_harness import web_app
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    monkeypatch.setitem(G.GAME_LAID_OUT, "g/scene1",
                        tuple(p for p in _paths(man) if p.endswith("Title")))
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_select", title)
        p = _tv(w)["props"]
        assert p["game_layout"] and p["valign"] == "middle"
        # the game would put it in the middle anyway: Top and Bottom are refused
        assert not w.call("text_scenes.tree_text_align", title, None, "top")
        assert not w.call("text_scenes.tree_text_align", title, None, "bottom")
        # across is the card's own: that still sets
        assert w.call("text_scenes.tree_text_align", title, "right", None)
        q = _tv(w)["props"]
        assert (q["align"], q["valign"]) == ("right", "middle")
        w.call("text_scenes.close")


def test_a_line_the_game_lays_out_stays_in_the_middle_whatever_the_edit_says():
    man = E.manifest(T.parse(scene()))
    G.mark(man, "/x/y/scene.radium")                       # not in the table: unchanged
    nid = 53
    ops = [{"op": "text_align", "node": nid, "align": 0, "valign": 2}]
    for o in man["objects"].values():
        if o.get("kind") == "Text":
            o["game_layout"], o["valign"], o["fit"] = True, 1, 1
    got, _n = X.apply_manifest(man, ops)
    d = [d for d in E.draw_list(got, 1) if d["kind"] == "text" and d["node"] == nid]
    assert d and all((x["align"], x["valign"], x["fit"]) == (0, 1, 1) for x in d)


def test_write_pads_a_game_laid_out_line_as_the_game_lays_it_out(monkeypatch):
    """A line the game puts in the middle takes no line of padding under it (that form is
    only for a line the game keeps at the top of its box): it would lift the words."""
    data = scene()
    sc = T.parse(data)
    text = _texts(sc)[0].body["text"].decode("latin1")
    path = next(p for p, _n in _paths(E.manifest(sc)).items())
    monkeypatch.setitem(G.GAME_LAID_OUT, "x/y", (path,))
    plain = engine._radium_text_looks(data)[text]
    laid = engine._radium_text_looks(data, (), "/x/y/scene.radium")[text]
    assert any(t for _a, _m, t, _f in plain) or plain
    assert all(not t and f for _a, _m, t, f in laid)
    assert engine._padded_text(b"A\nB", 7, laid) != b"A\nB" + b"\n" + b" " * 3


def test_the_preview_draws_the_gigan_intro_where_the_emulator_did():
    """Emulator (LE 1.16, PAD-433 runs v1-v3): BATTLE FOR TOKYO in a 340 x 220 box, wrapped
    to two lines, drew its orange ink at rows 586-616 and 648-678 of the 1360 x 768 glass
    whether the card said top, middle or bottom."""
    np = pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import fontrender, scene_render as R
    path = os.path.join(PROJ, "images", "scene_textures", "scene_tree.json")
    if not os.path.isfile(path):
        pytest.skip("needs a Godzilla LE 1.16 project")
    trees = json.load(open(path, encoding="utf-8"))
    card = next(c for c in trees if "e5793bce" in c)
    fonts = fontrender.load_fonts(PROJ)
    for valign in (0, 1, 2):
        man = G.mark(json.loads(json.dumps(trees[card])), card)
        ops = [{"op": "text_rect", "node": 330, "rect": [184.1, -2.0, 524.1, 218.0],
                "wrap": True},
               {"op": "text_align", "node": 330, "align": 1, "valign": valign}]
        got, notes = X.apply_manifest(man, ops)
        assert notes == []
        d = next(x for x in E.draw_list(got, 200) if x["node"] == 330)
        a = np.asarray(R.render_tree(PROJ, got, draws=[d], fonts=fonts).convert("RGB")).astype(int)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        m = (r > 200) & (g > 90) & (g < 215) & (b < 90) & (r - b > 150)
        rows = np.nonzero(m.sum(1) >= 6)[0]
        runs = [(x[0], x[-1]) for x in np.split(rows, np.where(np.diff(rows) > 3)[0] + 1)]
        assert len(runs) == 2, runs
        for (top, bot), (want_top, want_bot) in zip(runs, [(586, 616), (648, 678)]):
            assert abs(top - want_top) <= 3 and abs(bot - want_bot) <= 4, (valign, runs)


ELFS = [os.path.join(os.environ.get("PAD433_ELF_DIR", r"C:\tmp\pad433\elf"), n)
        for n in ("gz_le_116_stock.elf", "gz_pro_116_stock.elf")]


def test_the_table_is_what_the_game_programs_say():
    """tools/spike2_emu/bdl_texts.py over the stock Godzilla 1.16 programs gives this table
    (skipped without them: they are the card's, never in the repo)."""
    if not all(os.path.isfile(p) for p in ELFS):
        pytest.skip("needs the stock Godzilla LE and Pro 1.16 game programs")
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu"))
    import bdl_texts
    table = {}
    for p in ELFS:
        for scene_, _cls, names, reaches in bdl_texts.elements(bdl_texts.Elf(p)):
            if reaches and names:
                assert table.get(scene_, names) == names
                table[scene_] = names
    assert {k: tuple(v) for k, v in table.items()} == G.GAME_LAID_OUT
