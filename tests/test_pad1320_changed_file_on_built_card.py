"""PAD-1320 round 2 (DragonRR, "no change at all"): his Heisei 2.3 card was built with his
Battle Select file; he then dragged the map on in his working project (the drag folds into the
file's last edit, so it still has 136) and loaded that file into a fresh extract of the 2.3
card.  The card shows no run of the file's edits from its first, so all 136 went on a second
time, the grid and cards doubled in place and size.  Now each node is looked at on its own:
what the card already shows is left out, and a node it shows in another place or size gets
the move and resize to where the file leaves it."""
import json
import os

from pinball_decryptor.plugins.stern import scene_edit as X
from tests.test_pad403_edits_already_on_card import _built, _man, _project

CARD = "/godzilla_le/assets/lcd/demand_loaded/def/scene.radium"
# the file as the card was built with it
OLD = [{"op": "move", "node": 50, "dx": 12.0, "dy": 0.0},
       {"op": "scale", "node": 50, "s": 1.5, "px": 0.0, "py": 188.06},
       {"op": "move", "node": 53, "dx": -4.0, "dy": 9.0}]
# ... and after his map was dragged on 40 px: the drag folded into the last edit
DRAGGED = OLD[:2] + [{"op": "move", "node": 53, "dx": 36.0, "dy": 9.0}]
# ... or with a resize in the middle changed
RESIZED = [OLD[0], dict(OLD[1], s=1.6), OLD[2]]


def _look(man, nodes=(50, 53)):
    b = X._Base.of_manifest(man)
    return {n: b.fp(n) for n in nodes}


def _same(a, b):
    return all(X._close(a[n], b[n]) for n in a)


def test_a_dragged_on_file_on_the_card_built_before_gets_the_drag_only():
    built = _built(OLD)
    st = X.states_of(_man(), DRAGGED)
    # what went wrong: no run of the file's edits shows, so all of them went on again
    assert X.shown_count(X._Base.of_manifest(built), DRAGGED, st) == 0
    assert X.starts_elsewhere(built, DRAGGED, st)
    assert not _same(_look(X.apply_manifest(built, DRAGGED)[0]), _look(_built(DRAGGED)))
    ops = X.rebased(built, DRAGGED, st)
    assert ops == [{"op": "move", "node": 53, "dx": 40.0, "dy": 0.0}]
    assert _same(_look(X.apply_manifest(built, ops)[0]), _look(_built(DRAGGED)))


def test_a_resize_changed_in_the_middle_gets_a_resize_and_a_move():
    built = _built(OLD)
    st = X.states_of(_man(), RESIZED)
    assert X.shown_count(X._Base.of_manifest(built), RESIZED, st) == 0
    ops = X.rebased(built, RESIZED, st)
    assert ops and {op["node"] for op in ops} == {50}       # node 53 is as the file has it
    assert _same(_look(X.apply_manifest(built, ops)[0]), _look(_built(RESIZED)))


def test_a_card_that_shows_none_of_it_is_left_as_it_was():
    st = X.states_of(_man(), DRAGGED)
    # the stock scene: it is where the file starts, nothing to look again at
    assert X.rebased(_man(), DRAGGED, st) is None
    # another card (PAD-552): its nodes elsewhere, none as the file's edits leave them
    other = _built([{"op": "move", "node": 50, "dx": -300.0, "dy": 0.0},
                    {"op": "move", "node": 53, "dx": 0.0, "dy": 77.0}])
    assert X.rebased(other, DRAGGED, st) is None
    # a file that only starts where this card's edits leave off is PAD-552's on_top_of
    assert X.rebased(_built(OLD), OLD, X.states_of(_man(), OLD)) == []


def test_a_project_it_doubled_heals_itself_when_opened(tmp_path):
    built = _built(OLD)
    a = _project(tmp_path, {CARD: DRAGGED}, {CARD: built})
    # as a load before the fix left it: all the file's edits, its states, nothing shown
    fps, names = X._base_info(X._Base.of_manifest(built), DRAGGED)
    with open(os.path.join(a, *X.RELDIR, X.CARRIED_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"carried": {CARD: {"ops": [], "base": fps, "names": names}},
                   "states": {CARD: X.states_of(_man(), DRAGGED)},
                   "trees": X._trees_stamp(a), "rev": 2}, f)
    ops = X.to_apply(a, CARD, built)
    assert ops == [{"op": "move", "node": 53, "dx": 40.0, "dy": 0.0}]
    assert X.ops_for(a, CARD) == ops
    assert _same(_look(X.apply_manifest(built, ops)[0]), _look(_built(DRAGGED)))
    assert X.to_apply(a, CARD, built) == ops                  # once, and it stays


def test_the_page_loads_only_what_the_card_lacks(tmp_path):
    from tests.test_gui_scene_editor import CARD as GCARD, _open, _seed
    from tests.webui_harness import web_app
    src, card = tmp_path / "src", tmp_path / "card"
    for d in (src, card):
        _seed(d)
    tree = card / "images" / "scene_textures" / "scene_tree.json"
    trees = json.loads(tree.read_text(encoding="utf-8"))
    stock = trees[GCARD]
    trees[GCARD] = X.apply_manifest(stock, OLD)[0]           # the card built with OLD
    tree.write_text(json.dumps(trees), encoding="utf-8")
    X.save(str(src), {GCARD: DRAGGED})                         # his working project
    zip_path = str(tmp_path / "battle select tweaked.zip")
    assert X.export_edits(str(src), zip_path) == 1
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, card)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_load") == [GCARD]
        cap = w.state("text_scenes")["caption_full"]
        assert "start out" not in cap, cap
        assert "already has some or all of the file's edits built in" in cap, cap
        ops = X.ops_for(str(card), GCARD)
        assert ops == [{"op": "move", "node": 53, "dx": 40.0, "dy": 0.0}], ops
        after = X.apply_manifest(trees[GCARD], X.to_apply(str(card), GCARD, trees[GCARD]))[0]
        assert _same(_look(after), _look(X.apply_manifest(stock, DRAGGED)[0]))
