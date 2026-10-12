"""PAD-552 (DragonRR): a file of scene edits loaded into a project of another card.

His main PC's project is extracted from his own built card, so its scenes start out with
everything his earlier Writes put on them; the file holds only the edits made since.  On his
other PC, in a project of another card, the same relative edits (a move adds dx, a resize
scales) landed in other places, and nothing said why.

What has to hold:

* a scene here that looks as it did where the file was saved, or that already shows some or
  all of its edits, starts out the same;
* one that looks like neither starts out elsewhere, and the load says so;
* a file saved before PAD-403 (no states) cannot tell, and says nothing.
"""
import json

from pinball_decryptor.plugins.stern import scene_edit as X, scene_eval as E, scene_tree as T
from tests.test_stern_scene_tree import scene

MOVES = [{"op": "move", "node": 50, "dx": 12.0, "dy": 0.0},
         {"op": "move", "node": 53, "dx": -4.0, "dy": 9.0}]
# what an earlier Write of his put on the card his project is of
EARLIER = [{"op": "move", "node": 53, "dx": 300.0, "dy": 0.0}]


def _man():
    return E.manifest(T.parse(scene()))


def _built(man, ops):
    out, notes = X.apply_manifest(man, ops)
    assert notes == []
    return out


def test_the_scene_the_edits_were_made_on_starts_the_same():
    st = X.states_of(_man(), MOVES)
    assert not X.starts_elsewhere(_man(), MOVES, st)
    # built with them, or with the first of them
    assert not X.starts_elsewhere(_built(_man(), MOVES), MOVES, st)
    assert not X.starts_elsewhere(_built(_man(), MOVES[:1]), MOVES, st)


def test_a_scene_of_another_card_starts_elsewhere():
    his = _built(_man(), EARLIER)
    st = X.states_of(his, MOVES)
    assert X.starts_elsewhere(_man(), MOVES, st)
    assert not X.starts_elsewhere(his, MOVES, st)


def test_a_file_without_states_cannot_tell():
    assert not X.starts_elsewhere(_man(), MOVES, None)
    assert not X.starts_elsewhere(None, MOVES, X.states_of(_man(), MOVES))


def test_the_page_says_so_when_it_loads_them(tmp_path):
    from tests.test_gui_scene_editor import CARD, _open, _seed
    from tests.webui_harness import web_app
    his, mine, same = tmp_path / "his", tmp_path / "mine", tmp_path / "same"
    for d in (his, mine, same):
        _seed(d)
    # his project and "same" are of his built card; "mine" of the stock one
    for d in (his, same):
        tree = d / "images" / "scene_textures" / "scene_tree.json"
        trees = json.loads(tree.read_text(encoding="utf-8"))
        trees[CARD] = _built(trees[CARD], EARLIER)
        tree.write_text(json.dumps(trees), encoding="utf-8")
    X.save(str(his), {CARD: MOVES})
    zip_path = str(tmp_path / "his scenes.zip")
    assert X.export_edits(str(his), zip_path) == 1
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, mine)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_load") == [CARD]
        cap = w.state("text_scenes")["caption_full"]
        assert "1 scene here does not start out the way it did" in cap, cap
        assert "extract this project from the same card" in cap, cap

        _open(w, same)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_load") == [CARD]
        cap = w.state("text_scenes")["caption_full"]
        assert "start out" not in cap, cap
