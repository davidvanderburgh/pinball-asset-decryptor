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
        # round 3: what lands elsewhere, by name, in a report in the project's logs
        logs = list((mine / "logs").glob("Load his scenes *.txt"))
        assert len(logs) == 1 and str(logs[0]) in cap, cap
        report = logs[0].read_text(encoding="utf-8")
        assert "1 starting out otherwise here" in report, report
        assert "node 53 Title: off by -300.0,+0.0 px" in report, report

        _open(w, same)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_load") == [CARD]
        cap = w.state("text_scenes")["caption_full"]
        assert "start out" not in cap, cap


# ---------------------------------------------------------------------------------------------
# round 2: "no area has the color profile attached visually" - a project folder extracted
# again from another card keeps the first card's pictures, so the file's picture names were all
# "here", and every color profile went to a leftover no scene draws
# ---------------------------------------------------------------------------------------------
SCARD = "/godzilla_le/assets/lcd/auto_loaded/abc/scene.radium"
OTHER = "/godzilla_le/assets/lcd/auto_loaded/def/scene.radium"


def _folder(tmp_path):
    from PIL import Image
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    for name in ("now.png", "left_over.png", "shared.png"):
        Image.new("RGB", (4, 4), (200, 40, 40)).save(str(tex / name))
    return str(tmp_path), {
        SCARD: {"objects": {"1": {"kind": "Bitmap", "image": "scene_textures/now.png"}}},
        OTHER: {"objects": {"2": {"kind": "Bitmap", "image": "scene_textures/shared.png"}}}}


def test_a_leftover_of_another_card_does_not_take_the_profile(tmp_path):
    from pinball_decryptor.plugins.stern import scene_share
    a, trees = _folder(tmp_path)
    extras = {"pictures": {}, "colored": {
        "images/scene_textures/left_over.png": {"profile": None, "drawn": [[SCARD, "1"]]}}}
    got = scene_share.localise(a, extras, trees)
    assert sorted(got["colored"]) == ["images/scene_textures/now.png"]


def test_a_picture_a_scene_here_draws_keeps_its_name(tmp_path):
    from pinball_decryptor.plugins.stern import scene_share
    a, trees = _folder(tmp_path)
    extras = {"pictures": {}, "colored": {
        "images/scene_textures/shared.png": {"profile": None, "drawn": [[SCARD, "1"]]},
        "images/scene_textures/left_over.png": {"profile": None}}}
    got = scene_share.localise(a, extras, trees)
    # drawn here by another scene, or carrying no nodes to look it up by: as before
    assert sorted(got["colored"]) == ["images/scene_textures/left_over.png",
                                      "images/scene_textures/shared.png"]


def test_start_differences_name_the_node_and_how_far():
    his = _built(_man(), EARLIER)
    st = X.states_of(his, MOVES)
    got = X.start_differences(_man(), MOVES, st)
    assert got == [{"node": 53, "name": "Title", "what": "off by -300.0,+0.0 px"}]
    assert X.start_differences(his, MOVES, st) == []
    assert X.start_differences(_man(), MOVES, None) == []


# ---------------------------------------------------------------------------------------------
# round 4 (computer B): B's project is of the stock card with B's own edits; A's project is of
# the card B wrote from them, and A's file holds only what A changed since.  Loaded on B it
# replaced B's edits, so B's banner, hidden text and moves were gone: it goes after them now
# ---------------------------------------------------------------------------------------------
def test_edits_made_on_top_of_mine_go_after_mine():
    st = X.states_of(_built(_man(), EARLIER), MOVES)
    assert X.on_top_of(_man(), EARLIER, MOVES, st) == MOVES
    # loaded again: nothing more to add
    assert X.on_top_of(_man(), EARLIER + MOVES, MOVES, st) == []
    assert X.on_top_of(_man(), EARLIER + MOVES[:1], MOVES, st) == MOVES[1:]
    # other edits of mine, or a file made on the stock card, or no states: not on top of mine
    other = [{"op": "move", "node": 53, "dx": 0.0, "dy": 77.0}]
    assert X.on_top_of(_man(), other, MOVES, st) is None
    assert X.on_top_of(_man(), EARLIER, MOVES, X.states_of(_man(), MOVES)) is None
    assert X.on_top_of(_man(), EARLIER, MOVES, None) is None


def test_an_add_of_theirs_gets_an_id_mine_does_not_use():
    mine = [{"op": "shadow", "node": 53, "id": X.FIRST_ADDED_ID + 1, "dx": 4.0, "dy": 4.0,
             "mul": [0.0, 0.0, 0.0, 0.6]}]
    theirs = [dict(mine[0], node=50), {"op": "move", "node": X.FIRST_ADDED_ID + 1,
                                       "dx": 1.0, "dy": 0.0}]
    got = X._renumbered(theirs, mine)
    assert got[0]["id"] != X.FIRST_ADDED_ID + 1 and got[1]["node"] == got[0]["id"]


def test_the_page_puts_them_after_mine(tmp_path):
    from tests.test_gui_scene_editor import CARD, _open, _seed
    from tests.webui_harness import web_app
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        _seed(d)
    # A's project is of the card B wrote with EARLIER
    tree = a / "images" / "scene_textures" / "scene_tree.json"
    trees = json.loads(tree.read_text(encoding="utf-8"))
    trees[CARD] = _built(trees[CARD], EARLIER)
    tree.write_text(json.dumps(trees), encoding="utf-8")
    X.save(str(a), {CARD: MOVES})
    zip_path = str(tmp_path / "a scenes.zip")
    assert X.export_edits(str(a), zip_path) == 1
    X.save(str(b), {CARD: EARLIER})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, b)
        for _round in range(2):                       # the second load adds nothing
            w.answers.append(zip_path)
            assert w.call("text_scenes.edits_load") == [CARD]
            assert X.ops_for(str(b), CARD) == EARLIER + MOVES
            cap = w.state("text_scenes")["caption_full"]
            assert "start out" not in cap, cap
            assert "after your own edits" in cap, cap
            if not _round:
                # the first load's report (by mtime: the names are only to the
                # second, and a later load's says it added nothing more)
                report = max((b / "logs").glob("Load a scenes *.txt"),
                             key=lambda p: p.stat().st_mtime_ns).read_text(
                    encoding="utf-8")
        assert "added after your own 1 edit" in report, report


def test_a_picture_the_write_put_on_the_card_is_my_added_one(tmp_path):
    from PIL import Image
    from pinball_decryptor.plugins.stern import scene_share
    tex = tmp_path / "images" / "scene_textures" / "added"
    tex.mkdir(parents=True)
    Image.new("RGB", (4, 4), (200, 40, 40)).save(str(tex / "Logo_1.png"))
    X.save(str(tmp_path), {SCARD: [{"op": "add_picture", "id": X.FIRST_ADDED_ID + 1,
                                    "name": "PAD_Logo", "image": "scene_textures/added/Logo_1.png",
                                    "parent": 1, "index": 1, "w": 4, "h": 4, "x": 0, "y": 0}]})
    rel = "images/scene_textures/radimg_PAD_Logo_2048x683_abe91f0e.png"
    extras = {"pictures": {}, "colored": {rel: {"profile": None, "drawn": [[SCARD, "1246"]]}}}
    moved = {}
    got = scene_share.localise(str(tmp_path), extras, {SCARD: {"objects": {}}}, moved=moved)
    assert sorted(got["colored"]) == ["images/scene_textures/added/Logo_1.png"]
    assert moved == {rel: ["images/scene_textures/added/Logo_1.png"]}


# ---------------------------------------------------------------------------------------------
# round 5 (DoomWalrus666 on computer B): the battle scene got no color profile - every picture
# of it B replaced (its own art, which the card A saved from shows as the game's) was left out
# ---------------------------------------------------------------------------------------------
def _replaced_project(tmp_path):
    from PIL import Image
    from pinball_decryptor.core import staged_changes
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    Image.new("RGB", (4, 4), (200, 40, 40)).save(str(tex / "body.png"))
    art = tmp_path / "my art.png"
    Image.new("RGB", (4, 4), (10, 200, 10)).save(str(art))
    staged_changes.save(str(tmp_path), {"image": {"images/scene_textures/body.png": str(art)}})
    zp = tmp_path / "file.zip"
    import zipfile
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("pad_scene_edits.json", json.dumps({"format": 1, "kind": "pad-scene-edits",
                                                       "scenes": {}}))
    return str(tmp_path), str(zp)


def test_a_replaced_picture_takes_the_files_profile_when_the_card_was_built_from_here(tmp_path):
    from pinball_decryptor.core import colour_profile as cp, staged_changes
    from pinball_decryptor.plugins.stern import scene_share
    a, zp = _replaced_project(tmp_path)
    red = {"name": "Red", "gain": [4.0, 1.0, 1.0], "gamma": [1.0, 1.0, 1.0],
           "lift": [0.0, 0.0, 0.0], "saturation": 0.0}
    extras = {"pictures": {}, "added": {}, "overlay": None, "lines": {},
              "colored": {"images/scene_textures/body.png": {"profile": red}}}
    out = {}
    scene_share.import_extras(a, zp, extras, replaced_out=out)
    data = staged_changes.load(a)
    assert not (data.get(cp.IMAGE_SLOTS_KEY) or {}).get("images/scene_textures/body.png")
    assert out == {"given": [], "kept": ["images/scene_textures/body.png"]}
    out = {}
    scene_share.import_extras(a, zp, extras, replaced_too=True, replaced_out=out)
    data = staged_changes.load(a)
    assert data[cp.IMAGE_SLOTS_KEY]["images/scene_textures/body.png"] is True
    assert cp._own_dicts(data, "images")["images/scene_textures/body.png"] == red
    assert out == {"given": ["images/scene_textures/body.png"], "kept": []}
    # the pick itself is mine still
    assert data["image"]["images/scene_textures/body.png"].endswith("my art.png")
