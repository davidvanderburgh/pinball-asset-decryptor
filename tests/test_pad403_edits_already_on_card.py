"""PAD-403 (DragonRR): a scene's edits put on a scene that already shows them.

His "Heisei 1.95 EXTRACTED" project is extracted from a card a Write built with his scene
edits, and the same edits are in the project (his own file loaded into it, or kept from before
the card was read again).  Every edit is relative - a move adds dx, a resize scales - so the
preview and the next Write applied them on top of the card's already-moved text: his title,
centered yesterday, came back 300 px to the right and 8.5% bigger.

What has to hold:

* a scene that shows none of its edits (as shipped) gets all of them, as before;
* a scene that already shows its edits gets none again, in the preview and in the Write;
  one more edit after them (a later file, a drag now) is applied, and only that;
* a save (and a Write) keeps what each edit leaves its node looking like, so a scene whose
  edits are moves alone is told exactly; a file saved before that tells by the text boxes
  and added pictures it has, and a scene of moves alone goes with the rest of its project.
"""
import json
import os

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    engine, scene_edit as X, scene_eval as E, scene_tree as T)
from tests.test_stern_scene_tree import scene                                  # noqa: E402

CARD = "/godzilla_le/assets/lcd/demand_loaded/abc/scene.radium"
MOVED = "/godzilla_le/assets/lcd/demand_loaded/def/scene.radium"
# DragonRR's title edits, on the fixture's Title text (53) and Art (50)
TITLE = [{"op": "move", "node": 53, "dx": 2.0, "dy": -2.0},
         {"op": "text_rect", "node": 53, "rect": [-20.5, -2.0, 60.25, 30.0]},
         {"op": "scale", "node": 53, "s": 1.085478, "px": 20.0, "py": 14.0},
         {"op": "move", "node": 53, "dx": 31.0, "dy": 2.0}]
MOVES = [{"op": "move", "node": 50, "dx": 12.0, "dy": 0.0},
         {"op": "move", "node": 53, "dx": -4.0, "dy": 9.0}]


def _man():
    return E.manifest(T.parse(scene()))


def _built(ops):
    man, notes = X.apply_manifest(_man(), ops)
    assert notes == []
    return man


def _project(tmp_path, edits, trees):
    a = str(tmp_path)
    (tmp_path / "images" / "scene_textures").mkdir(parents=True, exist_ok=True)
    X.save(a, edits)
    (tmp_path / "images" / "scene_textures" / "scene_tree.json").write_text(
        json.dumps(trees), encoding="utf-8")
    return a


def _title(man):
    d = [d for d in E.draw_list(man, 1) if d["path"][-1] == "Title"][0]
    return tuple(round(v, 3) for v in d["m"])


def test_a_scene_as_shipped_gets_every_edit(tmp_path):
    a = _project(tmp_path, {CARD: TITLE}, {CARD: _man()})
    assert X.to_apply(a, CARD, _man()) == TITLE


def test_a_scene_built_with_its_edits_gets_none_again(tmp_path):
    built = _built(TITLE)
    a = _project(tmp_path, {CARD: TITLE}, {CARD: built})
    assert X.to_apply(a, CARD, built) == []
    # the preview draws the title where the card has it, not moved and grown twice
    shown, _n = X.apply_manifest(built, X.to_apply(a, CARD, built))
    assert _title(shown) == _title(built)
    assert _title(X.apply_manifest(built, TITLE)[0]) != _title(built)


def test_an_edit_after_them_is_applied_and_only_that(tmp_path):
    built = _built(TITLE)
    later = TITLE + [{"op": "text_rect", "node": 53, "rect": [-40.0, -2.0, 80.0, 20.0],
                      "wrap": True}]
    a = _project(tmp_path, {CARD: later}, {CARD: built})
    assert X.to_apply(a, CARD, built) == later[-1:]
    # a drag now: its own step, never folded into the move the card already has
    a = _project(tmp_path, {CARD: TITLE}, {CARD: built})
    assert X.to_apply(a, CARD, built) == []
    X.add(a, CARD, {"op": "move", "node": 53, "dx": -10.0, "dy": 0.0})
    assert X.ops_for(a, CARD)[:len(TITLE)] == TITLE
    assert X.to_apply(a, CARD, built) == [{"op": "move", "node": 53, "dx": -10.0, "dy": 0.0}]


def test_moves_alone_go_with_the_rest_of_the_project(tmp_path):
    """No states (a file saved before PAD-403): the title's text box tells its scene is built,
    so the other scene, moved only, is taken as built with it."""
    a = _project(tmp_path, {CARD: TITLE, MOVED: MOVES},
                 {CARD: _built(TITLE), MOVED: _built(MOVES)})
    assert X.to_apply(a, MOVED, _built(MOVES)) == []
    assert X.to_apply(a, CARD, _built(TITLE)) == []
    # in a project as shipped both get theirs
    b = _project(tmp_path / "x", {CARD: TITLE, MOVED: MOVES}, {CARD: _man(), MOVED: _man()}) \
        if (tmp_path / "x" / "images" / "scene_textures").mkdir(parents=True) is None else None
    assert X.to_apply(b, MOVED, _man()) == MOVES
    assert X.to_apply(b, CARD, _man()) == TITLE


def test_a_save_carries_what_each_edit_leaves_so_moves_alone_are_told(tmp_path):
    mine = _project(tmp_path / "mine", {MOVED: MOVES}, {MOVED: _man()})
    zp = str(tmp_path / "moves.zip")
    X.export_edits(mine, zp)
    states = X.read_states(zp)
    assert len(states[MOVED]["after"]) == len(MOVES)
    # loaded into the project of the card built from it: nothing applied twice
    theirs = _project(tmp_path / "theirs", {}, {MOVED: _built(MOVES)})
    got, _missing = X.import_edits(theirs, zp, [MOVED])
    assert X.note_shown(theirs, {MOVED: _built(MOVES)}, states=states) == {MOVED: 2}
    assert X.to_apply(theirs, MOVED, _built(MOVES)) == []
    # and into a project as shipped: all of them
    os.remove(os.path.join(theirs, *X.RELDIR, X.CARRIED_FILENAME))
    assert X.note_shown(theirs, {MOVED: _man()}, states=states) == {MOVED: 0}
    assert X.to_apply(theirs, MOVED, _man()) == MOVES


def test_a_project_read_again_off_the_card_its_write_built(tmp_path):
    a = _project(tmp_path, {MOVED: MOVES}, {MOVED: _man()})
    assert X.to_apply(a, MOVED, _man()) == MOVES
    assert X.mark_built(a)
    # Extract / Re-read from card of the card that Write built
    tp = tmp_path / "images" / "scene_textures" / "scene_tree.json"
    tp.write_text(json.dumps({MOVED: _built(MOVES)}), encoding="utf-8")
    os.utime(tp, ns=(1, 1))
    assert X.to_apply(a, MOVED, _built(MOVES)) == []


def test_the_write_leaves_out_what_the_card_already_shows(tmp_path):
    data = scene()
    sc = T.parse(data)
    assert X.apply_scene(sc, TITLE, names=X.names_of(_man()))[0] == len(TITLE)
    built = T.serialize(sc)
    a = _project(tmp_path, {CARD: TITLE}, {CARD: _man()})
    logs = []
    log = lambda m, lvl="info": logs.append(m)                                  # noqa: E731
    _new, n = engine._apply_tree_ops(data, CARD, TITLE, X.names_of(_man()), a, log)
    assert n == len(TITLE)                     # a card as shipped gets them all
    again, n = engine._apply_tree_ops(built, CARD, TITLE, X.names_of(_man()), a, log)
    assert (n, again) == (0, built)            # the card built with them: none again
    assert "already on this card" in logs[-1]
