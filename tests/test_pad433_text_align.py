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
