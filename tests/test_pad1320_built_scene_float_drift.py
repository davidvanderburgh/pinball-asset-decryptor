"""PAD-1320 (DragonRR): a fresh extract of the card his Battle Select file was written to, the
file loaded again, got all 136 edits a second time (cards and grid at 198 %).  One node of the
72 sat 0.02 px off the file's fingerprint (32-bit floats on the card, a scale kept to 3
decimals times a pivot hundreds of pixels away), past the old tolerance, so the scene read as
built with none of them.  Positions now match to well under a pixel; a project whose finding
was made with the old tolerance looks again once."""
import json
import os

from pinball_decryptor.plugins.stern import scene_edit as X
from tests.test_pad403_edits_already_on_card import (                          # noqa: E402
    CARD, MOVED, TITLE, _built, _man, _project)

# a move and a big scale about a far pivot, as his file does to the grid (node 1083)
GROW = [{"op": "move", "node": 50, "dx": -9.133, "dy": -299.851},
        {"op": "scale", "node": 50, "s": 1.978297, "px": 0.0, "py": 188.06}]


def _nudged(man, node, dx, dy):
    """*man* with *node*'s position off by (dx, dy): what the card's floats give back."""
    man = json.loads(json.dumps(man))
    n = X._man_index(man)[node][0]
    n["tr"] = [[f, m[:4] + [m[4] + dx, m[5] + dy]] for f, m in n["tr"]]
    return man


def test_a_hundredth_of_a_pixel_off_is_still_the_built_scene(tmp_path):
    mine = _project(tmp_path / "mine", {MOVED: GROW}, {MOVED: _man()})
    zp = str(tmp_path / "grow.zip")
    X.export_edits(mine, zp)
    states = X.read_states(zp)
    built = _built(GROW)
    # his card: 0.023 px off where the file says
    drift = _nudged(built, 50, 0.0, 0.023)
    assert X.shown_count(X._Base.of_manifest(drift), GROW, states[MOVED]) == len(GROW)
    theirs = _project(tmp_path / "theirs", {}, {MOVED: drift})
    X.import_edits(theirs, zp, [MOVED])
    assert X.note_shown(theirs, {MOVED: drift}, states=states) == {MOVED: len(GROW)}
    assert X.to_apply(theirs, MOVED, drift) == []


def test_a_pixel_off_is_still_told_apart(tmp_path):
    mine = _project(tmp_path / "mine", {MOVED: GROW}, {MOVED: _man()})
    zp = str(tmp_path / "grow.zip")
    X.export_edits(mine, zp)
    states = X.read_states(zp)[MOVED]
    built = _built(GROW)
    assert X.shown_count(X._Base.of_manifest(_nudged(built, 50, 1.0, 0.0)), GROW, states) == 0
    # a one-pixel nudge applied twice is not taken as built
    nudge = [{"op": "move", "node": 50, "dx": 1.0, "dy": 0.0}]
    a = X.states_of(_man(), nudge)
    twice = _built(nudge + nudge)
    assert X.shown_count(X._Base.of_manifest(twice), nudge, a) == 0
    assert X.shown_count(X._Base.of_manifest(_built(nudge)), nudge, a) == 1


def _stale(tmp_path, ops):
    """A project of the card built with *ops* whose finding (made before PAD-1320) says the
    scene shows none of them."""
    built = _built(ops)
    a = _project(tmp_path, {CARD: ops}, {CARD: built})
    fps, names = X._base_info(X._Base.of_manifest(built), ops)
    stamp = X._trees_stamp(a)
    with open(os.path.join(a, *X.RELDIR, X.CARRIED_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"carried": {CARD: {"ops": [], "base": fps, "names": names}},
                   "states": {}, "trees": stamp}, f)
    return a, built


def test_a_finding_of_the_old_tolerance_is_made_again(tmp_path):
    a, built = _stale(tmp_path, TITLE)
    assert X.to_apply(a, CARD, built) == []
    data = json.load(open(os.path.join(a, *X.RELDIR, X.CARRIED_FILENAME), encoding="utf-8"))
    assert data["rev"] == X.CARRIED_REV and data["carried"][CARD]["ops"] == TITLE


def test_the_write_makes_an_old_finding_again_too(tmp_path):
    from pinball_decryptor.plugins.stern import scene_tree as T
    from tests.test_stern_scene_tree import scene
    sc = T.parse(scene())
    X.apply_scene(sc, TITLE, names=X.names_of(_man()))
    a, _built_man = _stale(tmp_path, TITLE)
    assert X.to_apply_on_card(a, CARD, sc, TITLE) == []
