"""PAD-251: edits to a scene's tree - recorded per project, drawn by the preview, written to
the card - and the Write path that carries them.

EMULATOR-PROVEN on Godzilla LE 1.16's language screen (2026-09-28, hidden run, framebuffer
grabs): a scene carrying a move, a 1.6x resize, a hidden line, an added picture, four added
lines of text and three tints loaded and drew exactly where the preview put them, and the
game went on into play.  Also measured there: a Text's own rgba is ignored by a styled game
font whatever its flags; the node colour track tints text and pictures alike.

What has to hold, and is tested here:

* the file keeps one list per scene, folds a drag into one move, and can drop / undo / reset;
* the preview (manifest) and the card (scene tree) apply the same ops to the same result;
* a node the card does not have (or has under another name) is left alone and reported;
* the Write patches a same-size edit IN PLACE (writes + overlay, fine for a direct SD write)
  and hands a scene that grows to the whole-file path, which a direct SD write refuses.
"""
import pytest

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    engine, scene_edit as X, scene_eval as E, scene_tree as T)
from tests.test_stern_scene_tree import scene                                  # noqa: E402
from tests.test_stern_text_colors import _FakeReader                           # noqa: E402

CARD = "/godzilla_le/assets/lcd/demand_loaded/abc/scene.radium"


def _man():
    return E.manifest(T.parse(scene()))


def _draws(man, frame=1):
    return [(tuple(round(v, 3) for v in d["m"]), d["kind"], d.get("text"),
             tuple(round(v, 3) for v in d["mul"])) for d in E.draw_list(man, frame)]


OPS = [
    {"op": "move", "node": 50, "dx": 7, "dy": -3},
    {"op": "scale", "node": 50, "s": 1.5, "px": 8, "py": 4},
    {"op": "tint", "node": 51, "mul": [1, 0, 0, 0.5]},
    {"op": "visible", "node": 54, "on": False},
    {"op": "order", "node": 53, "index": 0},
    {"op": "add_text", "parent": None, "index": 99, "id": X.FIRST_ADDED_ID, "name": "New",
     "text": "HELLO", "x": 20, "y": 30, "like": 53},
]


def test_the_file_folds_a_drag_and_can_drop_undo_and_reset(tmp_path):
    a = str(tmp_path)
    X.add(a, CARD, {"op": "move", "node": 5, "dx": 1, "dy": 2})
    X.add(a, CARD, {"op": "move", "node": 5, "dx": 3, "dy": -2})
    assert X.ops_for(a, CARD) == [{"op": "move", "node": 5, "dx": 4, "dy": 0}]
    X.add(a, CARD, {"op": "move", "node": 5, "dx": -4, "dy": 0})
    assert X.ops_for(a, CARD) == []                     # a drag back to where it was
    X.add(a, CARD, {"op": "visible", "node": 6, "on": False})
    X.add(a, CARD, {"op": "scale", "node": 6, "s": 2, "px": 0, "py": 0})
    X.drop(a, CARD, 6, "visible")
    assert [op["op"] for op in X.ops_for(a, CARD)] == ["scale"]
    X.undo(a, CARD)
    assert X.load(a) == {}
    X.add(a, CARD, {"op": "tint", "node": 7, "mul": [1, 1, 1, 1]})
    X.reset_node(a, CARD, 7)
    assert X.count(a) == 0


def test_preview_and_card_apply_the_same_edits_to_the_same_result():
    man = _man()
    preview, notes = X.apply_manifest(man, OPS)
    assert notes == []
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, OPS, names=X.names_of(man))
    assert (n, notes) == (6, [])
    card = E.manifest(T.parse(T.serialize(sc)))
    assert _draws(preview) == _draws(card)
    names = [d["path"][-1] for d in E.draw_list(card, 1)]
    assert names[0] == "Title" and names[-1] == "New" and "Box" not in names


def test_what_each_edit_does_to_the_drawing():
    man = _man()
    before = {d["path"][-1]: d for d in E.draw_list(man, 1)}
    after = {d["path"][-1]: d for d in E.draw_list(X.apply_manifest(man, OPS)[0], 1)}
    b, a = before["Art"]["m"], after["Art"]["m"]
    assert a[0] == pytest.approx(b[0] * 1.5)
    # scaled about the local point (8, 4): that point stays put (after the move)
    px = (b[0] * 8 + b[2] * 4 + b[4] + 7, b[1] * 8 + b[3] * 4 + b[5] - 3)
    qx = (a[0] * 8 + a[2] * 4 + a[4], a[1] * 8 + a[3] * 4 + a[5])
    assert qx == pytest.approx(px)
    tinted = [d for d in E.draw_list(X.apply_manifest(man, OPS)[0], 1)
              if d["path"] == ["Tile_1", "Frame_Art"]][0]
    assert tinted["mul"] == pytest.approx((1, 0, 0, 0.5))                # a tint reaches kids
    assert after["New"]["text"] == "HELLO"


def test_a_node_the_card_lacks_or_names_differently_is_left_alone():
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, [{"op": "move", "node": 9999, "dx": 1, "dy": 1},
                                  {"op": "move", "node": 50, "dx": 1, "dy": 1}],
                             names={9999: "Gone", 50: "NotArt"})
    assert n == 0 and len(notes) == 2 and all("left alone" in x for x in notes)
    assert T.serialize(sc) == scene()


def test_a_stock_node_is_hidden_not_removed():
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, [{"op": "remove", "node": 50}])
    assert "Art" in [k.name for k in sc.root["kids"]]
    assert sc.root["kids"][0].keyframes == [(1, 0)] and notes


# ---------------------------------------------------------------------------------------------
# the Write
# ---------------------------------------------------------------------------------------------
def _project(tmp_path, ops):
    import json
    a = str(tmp_path)
    X.save(a, {CARD: ops})
    tex = tmp_path / "images" / "scene_textures"
    (tex / "scene_tree.json").write_text(json.dumps({CARD: _man()}), encoding="utf-8")
    return a


def test_a_same_size_edit_is_patched_in_place(tmp_path):
    data = scene()
    a = _project(tmp_path, [{"op": "move", "node": 50, "dx": 5, "dy": 5},
                            {"op": "visible", "node": 54, "on": False}])
    ov, msgs = {}, []
    writes, n, whole = engine._scene_tree_plan(
        _FakeReader({CARD: data}), a, lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False, False, ov)
    assert (n, whole) == (2, {})
    new = bytearray(data)
    for off, b in writes:                      # the fake reader maps file offset == disk
        new[off:off + len(b)] = b
    back = E.manifest(T.parse(bytes(new)))
    art = [d for d in E.draw_list(back, 1) if d["path"][-1] == "Art"][0]
    assert art["m"][4] == pytest.approx(105.0)
    (_ib, (_node, patch)), = ov.items()
    assert sorted(patch) == sorted(off for off, _b in writes)


def test_a_project_whose_only_change_is_a_same_size_scene_edit_is_written(
        tmp_path, monkeypatch):
    """_compute_patches refused a project whose ONLY change was a same-size Scenes edit
    ("Nothing could be written"): its last check counted every kind of write but the Scenes
    window's in-place ones, so neither Write nor Emulate could run it.  Found on the real
    Godzilla LE 1.16 card (PAD-305: five edits planned, then refused)."""
    from tests._ext4_fake import FakeExt4Reader, materialize_files
    from pinball_decryptor.plugins.stern import valpatch

    class _Card(FakeExt4Reader):
        base = 0

    data = scene()
    tree = {"godzilla_le": {"assets": {"lcd": {"demand_loaded": {"abc": {
        "scene.radium": data}}}}}}
    reader = _Card(tree)
    img = tmp_path / "card.raw"
    img.write_bytes(bytes(4096))
    materialize_files(str(img), tree)
    monkeypatch.setattr(engine, "_locate", lambda f, p: (reader, None, None))
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 1 << 30)])
    monkeypatch.setattr(engine, "_compute_sidx_writes", lambda *a, **k: [])
    monkeypatch.setattr(valpatch, "compute_writes", lambda *a, **k: ([], None))
    proj = tmp_path / "project"
    proj.mkdir()
    a = _project(proj, [{"op": "move", "node": 50, "dx": 5, "dy": 5}])
    out = tmp_path / "ovr"
    _counts, _mode, _val, files = engine.write_overrides(str(img), a, str(out))
    assert [p for p, _n in files] == [CARD]
    shipped = (out / CARD.lstrip("/")).read_bytes()
    assert len(shipped) == len(data) and shipped != data      # in place, same size
    art = [d for d in E.draw_list(E.manifest(T.parse(shipped)), 1) if d["path"][-1] == "Art"][0]
    assert art["m"][4] == pytest.approx(105.0)


@pytest.mark.parametrize("device", [False, True])
def test_a_scene_that_grows_goes_whole_and_not_to_a_card_directly(tmp_path, device):
    a = _project(tmp_path, [{"op": "add_text", "parent": None, "index": 0,
                             "id": X.FIRST_ADDED_ID, "name": "New", "text": "HI",
                             "x": 0, "y": 0, "like": 53}])
    msgs = []
    writes, n, whole = engine._scene_tree_plan(
        _FakeReader({CARD: scene()}), a, lambda m, lvl="info": msgs.append((lvl, m)),
        lambda: False, device, {})
    assert writes == []
    if device:
        assert (n, whole) == (0, {})
        assert any("image build" in m for _l, m in msgs)
    else:
        assert n == 1 and list(whole) == [CARD]


def test_a_stretch_scales_width_and_height_apart_and_both_sides_agree():
    """PAD-251 follow-up: a picture's width and height set on their own."""
    op = [{"op": "scale", "node": 50, "s": 2.0, "sy": 0.5, "px": 8, "py": 4}]
    man = _man()
    before = [d for d in E.draw_list(man, 1) if d["path"][-1] == "Art"][0]["m"]
    preview = X.apply_manifest(man, op)[0]
    after = [d for d in E.draw_list(preview, 1) if d["path"][-1] == "Art"][0]["m"]
    assert after[0] == pytest.approx(before[0] * 2.0)
    assert after[3] == pytest.approx(before[3] * 0.5)
    sc = T.parse(scene())
    X.apply_scene(sc, op, names=X.names_of(man))
    assert _draws(preview) == _draws(E.manifest(T.parse(T.serialize(sc))))
    assert X.describe(op[0]) == "200 x 50 %"


def test_stretches_fold_into_one_op(tmp_path):
    a = str(tmp_path)
    X.add(a, CARD, {"op": "scale", "node": 5, "s": 2.0, "px": 0, "py": 0})
    X.add(a, CARD, {"op": "scale", "node": 5, "s": 1.0, "sy": 3.0, "px": 0, "py": 0})
    assert X.ops_for(a, CARD) == [{"op": "scale", "node": 5, "s": 2.0, "sy": 6.0,
                                   "px": 0, "py": 0}]


def test_the_last_write_is_a_state_a_scene_can_go_back_to(tmp_path):
    """DragonRR: undo is not enough after many edits on many scenes; he wants "the last saved
    state" as well as factory.  Edits are kept as they are made, so the saved state is what
    the last successful Write built: mark_built records it, restore_built puts one scene back."""
    from pinball_decryptor.plugins.stern import scene_edit as E
    a = str(tmp_path)
    assert E.mark_built(a) is False and E.built_ops(a, "c1") is None   # nothing yet
    E.add(a, "c1", {"op": "move", "node": 1, "dx": 5, "dy": 0})
    E.add(a, "c2", {"op": "visible", "node": 2, "on": False})
    assert E.mark_built(a) is True
    E.add(a, "c1", {"op": "tint", "node": 1, "mul": [1, 0, 0, 1]})
    E.add(a, "c2", {"op": "move", "node": 3, "dx": 1, "dy": 1})
    assert E.restore_built(a, "c1") is True
    assert E.ops_for(a, "c1") == [{"op": "move", "node": 1, "dx": 5, "dy": 0}]
    assert len(E.ops_for(a, "c2")) == 2                                 # other scenes untouched
    assert E.built_ops(a, "c3") == [] and E.restore_built(a, "c3") is True
    E.clear(a)
    assert E.mark_built(a) is True and E.built_ops(a, "c1") == []       # an empty Write counts



def test_a_running_game_gets_its_scene_rebuilt_from_the_sets_base(tmp_path):
    """PAD-251 "on the fly": write_overrides keeps each tree-edited scene as it was before its
    tree edits BESIDE the set; scene_live_bytes rebuilds that one scene with the project's
    CURRENT edits, from the base (or the set's own copy), and says None for a scene the set
    does not hold (nothing is bound over it in the running game)."""
    import json
    from pinball_decryptor.plugins.stern import engine, scene_eval, scene_tree
    from pinball_decryptor.plugins.stern import scene_edit as E
    from tests.test_stern_scene_tree import scene
    card = "/g/demand_loaded/s1/scene.radium"
    data = scene()
    sc = scene_tree.parse(data)
    assets = tmp_path / "proj"
    tex = assets / "images" / "scene_textures"
    tex.mkdir(parents=True)
    man = scene_eval.manifest(sc, {})
    (tex / "scene_tree.json").write_text(json.dumps({card: man}), encoding="utf-8")
    node = next(n["id"] for n, _p in [(n, None) for n in man["root"]["kids"]])
    out = tmp_path / "spike2_overrides"
    engine._write_scene_bases(str(out), {card: data})
    assert (tmp_path / "spike2_overrides-scenes" / "g" / "demand_loaded" / "s1"
            / "scene.radium").read_bytes() == data
    # not in the set: nothing to hand over
    assert engine.scene_live_bytes(str(out), str(assets), card) is None
    in_set = out / "g" / "demand_loaded" / "s1" / "scene.radium"
    in_set.parent.mkdir(parents=True)
    in_set.write_bytes(b"what the set was built with")
    # no edits now: the base itself
    assert engine.scene_live_bytes(str(out), str(assets), card) == data
    E.add(str(assets), card, {"op": "move", "node": node, "dx": 12, "dy": 0})
    got = engine.scene_live_bytes(str(out), str(assets), card)
    want, n = engine._apply_tree_ops(data, card, E.ops_for(str(assets), card),
                                     E.names_of(man), str(assets), lambda *a, **k: None)
    assert n == 1 and got == want and got != data
    assert engine.scene_loads_on_demand(card)
    assert not engine.scene_loads_on_demand("/godzilla_le/assets/lcd/auto_loaded/x/scene.radium")


def test_each_scene_says_whether_its_edits_are_on_a_card_yet(tmp_path):
    """DragonRR: colour the scene list by what is changed and not written yet (orange) and
    what the last Write put on the card (green)."""
    from pinball_decryptor.plugins.stern import scene_edit as E
    a = str(tmp_path)
    E.add(a, "c1", {"op": "move", "node": 1, "dx": 5, "dy": 0})
    assert E.scene_states(a) == {"c1": "edited"}                      # no Write yet
    E.mark_built(a)
    assert E.scene_states(a) == {"c1": "written"}
    E.add(a, "c2", {"op": "visible", "node": 2, "on": False})
    assert E.scene_states(a) == {"c1": "written", "c2": "edited"}
    E.clear(a, "c1")                                                   # back as shipped...
    assert E.scene_states(a)["c1"] == "edited"                        # ...not on the card yet
    E.mark_built(a)
    assert E.scene_states(a) == {"c2": "written"}


def test_a_turn_rotates_about_the_middle_and_both_sides_agree():
    """DragonRR: "graphics can be rotated".  90 degrees clockwise about its own point: the
    point stays put on the glass, and the card draws what the preview draws."""
    man = _man()
    art = lambda m: [d for d in E.draw_list(m, 1) if d["path"][-1] == "Art"][0]["m"]
    before = art(man)
    op = [{"op": "rotate", "node": 50, "deg": 90, "px": 8, "py": 4}]
    preview = X.apply_manifest(man, op)[0]
    after = art(preview)
    # the linear part is the old one turned a quarter
    assert after[0] == pytest.approx(before[2]) and after[1] == pytest.approx(before[3])
    assert after[2] == pytest.approx(-before[0]) and after[3] == pytest.approx(-before[1])
    # the pivot stays where it was on the glass
    assert E.apply(after, 8, 4) == pytest.approx(E.apply(before, 8, 4))
    sc = T.parse(scene())
    X.apply_scene(sc, op, names=X.names_of(man))
    assert _draws(preview) == _draws(E.manifest(T.parse(T.serialize(sc))))
    assert X.describe(op[0]) == "turned +90°"


def test_turns_fold_into_one_op_and_a_full_turn_is_none(tmp_path):
    a = str(tmp_path)
    X.add(a, CARD, {"op": "rotate", "node": 5, "deg": 30, "px": 1, "py": 2})
    X.add(a, CARD, {"op": "rotate", "node": 5, "deg": 15, "px": 1, "py": 2})
    assert X.ops_for(a, CARD) == [{"op": "rotate", "node": 5, "deg": 45, "px": 1, "py": 2}]
    X.add(a, CARD, {"op": "rotate", "node": 5, "deg": -45, "px": 1, "py": 2})
    assert X.ops_for(a, CARD) == []


def test_a_drop_shadow_is_a_dark_copy_of_the_text_just_beneath_it():
    """DragonRR: "can text have drop shadows?".  A Text has no shadow setting; the game draws
    outlines as a second node on the SAME Text object beneath the first, so a shadow is that:
    the copy draws the same words, moved, darkened, one layer below.  The card agrees, keeps
    ONE Text object for both, and a later move or remove of the shadow reaches it."""
    man = _man()
    sid = X.FIRST_ADDED_ID
    ops = [{"op": "shadow", "node": 53, "id": sid, "dx": 4, "dy": 4, "mul": [0, 0, 0, 0.6]}]
    preview = X.apply_manifest(man, ops)[0]
    texts = [d for d in E.draw_list(preview, 1) if d["kind"] == "text"]
    assert [d["path"][-1] for d in texts] == ["Title_Shadow", "Title"]
    sh, ti = texts
    assert sh["text"] == ti["text"]
    assert (sh["m"][4] - ti["m"][4], sh["m"][5] - ti["m"][5]) == pytest.approx((4, 4))
    assert sh["m"][:4] == pytest.approx(ti["m"][:4])
    assert sh["mul"][:3] == pytest.approx([0, 0, 0]) and sh["mul"][3] == pytest.approx(0.6 * ti["mul"][3])
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, ops, names=X.names_of(man))
    assert n == 1 and notes == []
    data = T.serialize(sc)
    card = E.manifest(T.parse(data))
    assert _draws(preview) == _draws(card)
    title = [c.obj for nd, *_ in T.parse(data).walk() if nd.name in ("Title", "Title_Shadow")
             for c in nd.components]
    assert len(title) == 2 and title[0].id == title[1].id
    # the shadow is a layer like any other: moved, then removed, on both sides
    more = ops + [{"op": "move", "node": sid, "dx": 2, "dy": 0}]
    sc = T.parse(scene())
    X.apply_scene(sc, more, names=X.names_of(man))
    assert _draws(X.apply_manifest(man, more)[0]) == _draws(E.manifest(T.parse(T.serialize(sc))))
    gone = ops + [{"op": "remove", "node": sid}]
    sc = T.parse(scene())
    X.apply_scene(sc, gone, names=X.names_of(man))
    assert T.serialize(sc) == scene()
    assert X.describe(ops[0]) == "added a drop shadow"


def test_an_added_node_goes_into_a_group_where_it_was_and_both_sides_agree():
    """PAD-391 (DragonRR): a layer dragged in Layers onto another group goes into it.  Its
    tracks are multiplied by the old group's drawing then the new one's undone, so it is drawn
    where it was; the game's own nodes stay put (its code finds them by their path)."""
    man = _man()
    add = {"op": "add_text", "parent": None, "index": 99, "id": X.FIRST_ADDED_ID,
           "name": "New", "text": "HELLO", "x": 20, "y": 30, "like": 53}
    into = {"op": "parent", "node": X.FIRST_ADDED_ID, "parent": 51, "index": 9,
            "m": [1, 0, 0, 1, -10, -10]}                # Tile_1 draws at (10, 10)
    stock = {"op": "parent", "node": 53, "parent": 51, "index": 0, "m": [1, 0, 0, 1, 0, 0]}
    ops = [add, into, stock]
    preview, notes = X.apply_manifest(man, ops)
    assert len(notes) == 1 and "53" in notes[0]
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, ops, names=X.names_of(man))
    assert n == 2 and len(notes) == 1 and "left where it was" in notes[0]
    card = E.manifest(T.parse(T.serialize(sc)))
    assert _draws(preview) == _draws(card)
    at = {tuple(d["path"]): d["m"] for d in E.draw_list(card, 1)}
    # Tile_1 and Tile_2 share one sprite: it is in both, Tile_1's where it was
    assert at[("Tile_1", "New")][4:] == pytest.approx((20, 30))
    assert at[("Tile_2", "New")][4:] == pytest.approx((20, 220))
    assert ("New",) not in at and ("Title",) in at
    assert X.describe(into) == "put in another group"
