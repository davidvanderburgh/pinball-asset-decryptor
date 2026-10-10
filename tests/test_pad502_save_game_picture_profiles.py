"""PAD-502 (DragonRR): Scenes' "Save every scene with pictures, text and color profiles" left out
the color profiles of the game's own pictures.

He colored the 70th Anniversary look without replacing a picture: the game's own pictures
unlocked and switched on, the individual files profile on them, two lines of text with profiles
of their own.  The file came out at 683 bytes, holding only the two lines, and loading it showed
nothing: the lines are game lines, which count only with the unlock box ticked, and the box was
not in the file either.

Now the file carries every game picture switched on (its own profile, or none when it follows
the individual files profile, which the file carries once), and loading it switches them on,
ticks the unlock box so they and the lines count, and asks first when it would change a look
of the user's own.
"""

import json
import os
import zipfile

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_edit, scene_share

PIL = pytest.importorskip("PIL.Image")

CARD = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"
OTHER = "/godzilla_le/assets/lcd/auto_loaded/0123456789abcdef/scene.radium"
HERO = "scene_textures/radimg_530x726_90dbdeb2.png"       # drawn by the battle scene
BACK = "scene_textures/radimg_62x90_1c1433fb.png"         # drawn by the battle scene
LOGO = "boot_screen/SternLogo.png"                         # drawn by no scene
ELSE = "scene_textures/radimg_8x8_77777777.png"            # drawn by the other scene
BW = cp._profile_dict(cp.Profile(name="Black and white", saturation=0.0))
SEPIA = cp._profile_dict(cp.Profile(name="Sepia", gain=(1.2, 1.0, 0.8), saturation=0.3))
YELLOW = {"name": "Yellow", "gain": [3.19, 3.17, 0.14], "gamma": [0.22, 0.22, 3.85],
          "lift": [0.0, 0.0, 0.0], "saturation": 1.0}
LINES = (1239, 1241)


def _trees():
    return {CARD: {"objects": {"1": {"kind": "Bitmap", "image": HERO},
                               "2": {"kind": "Bitmap", "image": BACK},
                               "1239": {"kind": "Text"}, "1241": {"kind": "Text"}}},
            OTHER: {"objects": {"5": {"kind": "Bitmap", "image": ELSE}}}}


def _project(root, name, side=None):
    d = root / name
    for pic in (HERO, BACK, LOGO, ELSE):
        p = d / "images" / pic
        p.parent.mkdir(parents=True, exist_ok=True)
        PIL.new("RGB", (8, 8), (200, 40, 40)).save(p)
    (d / "images" / "scene_textures" / "scene_tree.json").write_text(
        json.dumps(_trees()), encoding="utf-8")
    staged_changes.save(str(d), dict(side or {}))
    return str(d)


def _seventieth(root):
    """His project: the game's pictures unlocked and switched on, Black and white on them all
    but the hero, which has a profile of its own; two lines of the battle scene profiled."""
    return _project(root, "seventieth", {
        cp.STOCK_IMAGES_KEY: True,
        cp.ASSET_KEY: BW,
        cp.IMAGE_SLOTS_KEY: {"images/" + p: True for p in (HERO, BACK, LOGO, ELSE)},
        cp.FILE_PROFILES_KEY["images"]: {"images/" + HERO: SEPIA},
        cp.TEXT_SLOTS_KEY: {cp.text_rel(CARD, n): True for n in LINES},
        cp.FILE_PROFILES_KEY["text"]: {cp.text_rel(CARD, 1239): YELLOW}})


def _doc(path):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(scene_edit.SHARE_MANIFEST))


def _load(project, path, files_profile=True, drop=()):
    extras = scene_share.localise(project, scene_share.read_extras(path), _trees())
    extras = dict(extras, colored={r: p for r, p in extras["colored"].items() if r not in drop})
    counts = {}
    got = scene_share.import_extras(project, path, extras, cards_here=_trees().keys(),
                                    files_profile=files_profile, counts=counts)
    return got, counts


def test_the_save_carries_the_game_pictures_switched_on(tmp_path):
    a = _seventieth(tmp_path)
    out = str(tmp_path / "Godzilla scenes with pictures.zip")
    counts = {}
    assert scene_share.export_all(a, out, None, _trees(), counts=counts) == (0, 0, 0)
    assert counts == {"colored": 4, "lines": 2}
    doc = _doc(out)
    assert doc["colored"] == {
        "images/" + HERO: {"profile": SEPIA, "drawn": [[CARD, "1"]]},
        "images/" + BACK: {"profile": None, "drawn": [[CARD, "2"]]},
        "images/" + LOGO: {"profile": None},
        "images/" + ELSE: {"profile": None, "drawn": [[OTHER, "5"]]}}
    assert doc["files_profile"] == BW
    assert sorted(doc["lines"][CARD]) == ["1239", "1241"]
    # one scene saved alone: the game pictures it draws
    scene_share.export_all(a, out, [CARD], _trees())
    assert sorted(_doc(out)["colored"]) == sorted(["images/" + BACK, "images/" + HERO])
    # an own profile on every one: no individual files profile to carry
    data = staged_changes.load(a)
    data[cp.IMAGE_SLOTS_KEY] = {"images/" + HERO: True}
    staged_changes.save(a, data)
    scene_share.export_all(a, out, None, _trees())
    assert "files_profile" not in _doc(out)
    # with the box unticked a game picture's switch does not count: nothing of it is saved
    data.pop(cp.STOCK_IMAGES_KEY)
    staged_changes.save(a, data)
    with pytest.raises(scene_edit.SceneEditError):
        scene_share.export_all(a, out, None, _trees())


def test_a_file_of_only_color_profiles_is_saved(tmp_path):
    """Nothing but the lines' profiles: before, "there are no scene edits ... to save"."""
    a = _project(tmp_path, "lines", {cp.STOCK_IMAGES_KEY: True,
                                     cp.TEXT_SLOTS_KEY: {cp.text_rel(CARD, 1239): True}})
    out = str(tmp_path / "s.zip")
    counts = {}
    assert scene_share.export_all(a, out, None, _trees(), counts=counts) == (0, 0, 0)
    assert counts == {"colored": 0, "lines": 1} and list(_doc(out)["lines"]) == [CARD]


def test_loading_switches_them_on_and_ticks_the_unlock_box(tmp_path):
    a = _seventieth(tmp_path)
    out = str(tmp_path / "s.zip")
    scene_share.export_all(a, out, None, _trees())
    # a stock project: the box never ticked, a game switch and a line left from long ago
    b = _project(tmp_path, "stock", {
        cp.IMAGE_SLOTS_KEY: {"images/scene_textures/old.png": True},
        cp.TEXT_SLOTS_KEY: {cp.text_rel(OTHER, 7): True}})
    extras = scene_share.localise(b, scene_share.read_extras(out), _trees())
    assert scene_share.has_extras(extras)
    assert scene_share.clashes(b, extras) == {"pictures": [], "overlay": False, "colored": [],
                                              "files_profile": False}
    (pics, gone), counts = _load(b, out)
    assert (pics, gone) == ([], [])
    assert counts == {"colored": 4, "lines": 2, "colored_missing": 0}
    assert cp.stock_images_unlocked(b)
    assert cp.stock_image_rels(b) == sorted("images/" + p for p in (BACK, LOGO, HERO, ELSE))
    # the hero keeps its own profile, the rest follow Black and white, which is this project's
    assert cp.own_profile(b, "images", "images/" + HERO).name == "Sepia"
    assert cp.own_profile(b, "images", "images/" + BACK) is None
    assert cp.asset_profile(b).name == "Black and white"
    assert cp.text_lines_on(b) == {cp.text_rel(CARD, n) for n in LINES}
    assert cp.own_profile(b, "text", cp.text_rel(CARD, 1239)).name == "Yellow"
    # nothing left from before the box was ticked woke up with it
    side = staged_changes.load(b)
    assert "images/scene_textures/old.png" not in side[cp.IMAGE_SLOTS_KEY]
    assert cp.text_rel(OTHER, 7) not in side[cp.TEXT_SLOTS_KEY]
    # loaded again: the same, nothing to ask
    extras = scene_share.localise(b, scene_share.read_extras(out), _trees())
    assert scene_share.clashes(b, extras)["colored"] == []
    assert _load(b, out)[1]["colored"] == 4


def test_his_own_file_shows_its_lines_once_loaded(tmp_path):
    """DragonRR's file as he sent it (683 bytes: two lines, two shadows) loaded into a project
    with the box unticked: the lines are switched on AND counted now."""
    out = str(tmp_path / "Godzilla_scenes_with_pictures.zip")
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(scene_edit.SHARE_MANIFEST, json.dumps({
            "format": 1, "kind": scene_edit.SHARE_KIND, "added": {}, "pictures": {},
            "lines": {CARD: {"1239": {"color": True, "profile": YELLOW},
                             "1241": {"color": True, "profile": dict(YELLOW, name="My profile")}}},
            "scenes": {CARD: [{"dx": 4.0, "dy": 4.0, "id": 2130706433, "mul": [0, 0, 0, 0.6],
                               "node": 1241, "op": "shadow"}]}}))
    b = _project(tmp_path, "stock")
    scene_edit.import_edits(b, out, _trees().keys())
    (_pics, _gone), counts = _load(b, out)
    assert counts == {"colored": 0, "lines": 2, "colored_missing": 0}
    assert cp.text_lines_on(b) == {cp.text_rel(CARD, n) for n in LINES}
    assert cp.own_profile(b, "text", cp.text_rel(CARD, 1241)).name == "My profile"


def test_a_look_of_my_own_is_asked_about_first(tmp_path):
    a = _seventieth(tmp_path)
    out = str(tmp_path / "s.zip")
    scene_share.export_all(a, out, None, _trees())
    # mine: Sepia as my individual files profile, my back picture switched on following it,
    # my logo with a profile of its own, the hero as the file has it
    b = _project(tmp_path, "mine", {
        cp.STOCK_IMAGES_KEY: True, cp.ASSET_KEY: SEPIA,
        cp.IMAGE_SLOTS_KEY: {"images/" + p: True for p in (BACK, LOGO, HERO)},
        cp.FILE_PROFILES_KEY["images"]: {"images/" + LOGO: YELLOW, "images/" + HERO: SEPIA}})
    extras = scene_share.localise(b, scene_share.read_extras(out), _trees())
    clash = scene_share.clashes(b, extras)
    # the back picture follows the individual files profile both here and in the file: the
    # files profile's own row asks about it
    assert clash["colored"] == ["images/" + LOGO] and clash["files_profile"] is True
    rows = {i["id"]: i for i in scene_share.conflict_items(b, {}, extras, clash, [])}
    assert (rows["files_profile"]["what"], rows["files_profile"]["mine"],
            rows["files_profile"]["theirs"]) == (
        "Individual files color profile", "Sepia", "Black and white")
    assert (rows["colored"]["what"], rows["colored"]["mine"], rows["colored"]["theirs"]) == (
        "Color profile of 1 game picture", "Yellow", "Black and white")

    # both kept: my profile and my logo stay mine, my back picture still follows mine, and
    # the file's other picture gets the file's look as a copy
    (_p, _g), counts = _load(b, out, files_profile=False, drop=set(clash["colored"]))
    assert counts["colored"] == 2                                   # the hero and ELSE
    assert cp.asset_profile(b).name == "Sepia"
    assert cp.own_profile(b, "images", "images/" + LOGO).name == "Yellow"
    assert cp.own_profile(b, "images", "images/" + BACK) is None
    assert cp.own_profile(b, "images", "images/" + ELSE).name == "Black and white"
    assert cp.stock_image_rels(b) == sorted("images/" + p for p in (BACK, LOGO, HERO, ELSE))

    # both replaced: the file's individual files profile becomes mine and they follow it
    (_p, _g), counts = _load(b, out)
    assert counts["colored"] == 4
    assert cp.asset_profile(b).name == "Black and white"
    assert cp.own_profile(b, "images", "images/" + LOGO) is None
    assert cp.own_profile(b, "images", "images/" + BACK) is None


def test_a_files_profile_nothing_here_uses_is_not_asked_about(tmp_path):
    """The default (no profile picked) is asked about only when something here follows it."""
    a = _seventieth(tmp_path)
    out = str(tmp_path / "s.zip")
    scene_share.export_all(a, out, None, _trees())
    b = _project(tmp_path, "fresh")
    extras = scene_share.localise(b, scene_share.read_extras(out), _trees())
    assert scene_share.clashes(b, extras)["files_profile"] is False
    c = _project(tmp_path, "attached", {cp.ALL_IMAGES_KEY: True})
    assert scene_share.clashes(c, extras)["files_profile"] is True


def test_a_picture_replaced_or_missing_here_is_left_out(tmp_path):
    a = _seventieth(tmp_path)
    out = str(tmp_path / "s.zip")
    scene_share.export_all(a, out, None, _trees())
    b = _project(tmp_path, "mine")
    os.remove(os.path.join(b, "images", *ELSE.split("/")))
    mine = tmp_path / "my_hero.png"
    PIL.new("RGB", (8, 8), (1, 2, 3)).save(mine)
    data = staged_changes.load(b)
    data["image"] = {"images/" + HERO: str(mine)}
    staged_changes.save(b, data)
    (_p, _g), counts = _load(b, out)
    assert counts == {"colored": 2, "lines": 2, "colored_missing": 1}
    slots = staged_changes.load(b)[cp.IMAGE_SLOTS_KEY]
    assert "images/" + HERO not in slots and "images/" + ELSE not in slots
    assert cp.own_profile(b, "images", "images/" + HERO) is None


def test_a_game_picture_named_otherwise_here_is_found_by_its_nodes(tmp_path):
    """PAD-385's lookup: a project extracted from a card built with changes names the
    battle scene's portrait by other bytes."""
    a = _seventieth(tmp_path)
    out = str(tmp_path / "s.zip")
    scene_share.export_all(a, out, None, _trees())
    b = _project(tmp_path, "built")
    here = "scene_textures/radimg_530x726_10a34f06.png"
    os.rename(os.path.join(b, "images", *HERO.split("/")), os.path.join(b, "images", *here.split("/")))
    trees = _trees()
    trees[CARD]["objects"]["1"]["image"] = here
    extras = scene_share.localise(b, scene_share.read_extras(out), trees)
    assert "images/" + here in extras["colored"] and "images/" + HERO not in extras["colored"]
    scene_share.import_extras(b, out, extras, cards_here=trees.keys())
    assert cp.own_profile(b, "images", "images/" + here).name == "Sepia"


def test_the_scenes_page_saves_and_loads_them(tmp_path):
    from tests.test_gui_scene_editor import CARD as GCARD, _open, _seed, _wait
    from tests.webui_harness import web_app
    friend, mine = tmp_path / "friend", tmp_path / "mine"
    man = _seed(friend)
    _seed(mine)
    pics = sorted({"images/" + o["image"] for o in man["objects"].values()
                   if isinstance(o, dict) and o.get("kind") == "Bitmap" and o.get("image")})
    assert pics
    staged_changes.save(str(friend), {cp.STOCK_IMAGES_KEY: True, cp.ASSET_KEY: BW,
                                      cp.IMAGE_SLOTS_KEY: {r: True for r in pics}})
    zip_path = str(tmp_path / "friend scenes with pictures.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, friend)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "all", True) == zip_path
        cap = w.state("text_scenes")["caption_full"]
        assert "the color profiles of %d game picture" % len(pics) in cap, cap
        assert sorted(_doc(zip_path)["colored"]) == pics

        _open(w, mine)
        w.answers.append(zip_path)
        w.call("text_scenes.edits_load")
        cap = w.state("text_scenes")["caption_full"]
        assert "and the color profiles of %d game picture" % len(pics) in cap, cap
        assert cp.stock_images_unlocked(str(mine))
        assert cp.stock_image_rels(str(mine)) == pics
        assert cp.asset_profile(str(mine)).name == "Black and white"
        # the Layers list shows them switched on, not locked
        assert _wait(w, lambda: any(
            (l.get("color") or {}).get("on") for l in
            (w.state("text_scenes").get("tree_view") or {}).get("layers") or ()))
        assert scene_edit.ops_for(str(mine), GCARD) == []


# ---------------------------------------------------------------------------------------------
# his two shadows: "already built in" on a scene that had neither (PAD-403's check)
# ---------------------------------------------------------------------------------------------
# A shadow is a new node, a tint the colour track: neither changed the fingerprint PAD-403 tells
# a scene by (tracks, text box, hidden), so a scene as shipped looked like one built with them.
# Loading his file said "1 scene on this card already has some or all of the file's edits
# built in", and the preview and the Write left both shadows out.
TCARD = "/godzilla_le/assets/lcd/demand_loaded/abc/scene.radium"
SHADOW_TINT = [{"op": "shadow", "node": 53, "id": 2130706433, "dx": 4.0, "dy": 4.0,
                "mul": [0.0, 0.0, 0.0, 0.6]},
               {"op": "tint", "node": 50, "mul": [1.0, 0.5, 0.5, 1.0]}]


def _man():
    from pinball_decryptor.plugins.stern import scene_eval as E, scene_tree as T
    from tests.test_stern_scene_tree import scene
    return E.manifest(T.parse(scene()))


def _built(ops):
    man, notes = scene_edit.apply_manifest(_man(), ops)
    assert notes == []
    return man


def _edits_project(path, edits, trees):
    (path / "images" / "scene_textures").mkdir(parents=True, exist_ok=True)
    scene_edit.save(str(path), edits)
    (path / "images" / "scene_textures" / "scene_tree.json").write_text(
        json.dumps(trees), encoding="utf-8")
    return str(path)


def test_shadows_and_tints_load_onto_a_scene_as_shipped(tmp_path):
    mine = _edits_project(tmp_path / "mine", {TCARD: SHADOW_TINT}, {TCARD: _man()})
    zp = str(tmp_path / "s.zip")
    scene_edit.export_edits(mine, zp)
    states = scene_edit.read_states(zp)
    theirs = _edits_project(tmp_path / "theirs", {}, {TCARD: _man()})
    scene_edit.import_edits(theirs, zp, [TCARD])
    assert scene_edit.note_shown(theirs, {TCARD: _man()}, states=states) == {TCARD: 0}
    assert scene_edit.to_apply(theirs, TCARD, _man()) == SHADOW_TINT
    # his own file loaded back into his own project: still drawn
    scene_edit.import_edits(mine, zp, [TCARD])
    assert scene_edit.note_shown(mine, {TCARD: _man()}, states=states) == {TCARD: 0}
    assert scene_edit.to_apply(mine, TCARD, _man()) == SHADOW_TINT


def test_a_card_built_with_them_still_gets_neither_twice(tmp_path):
    mine = _edits_project(tmp_path / "mine", {TCARD: SHADOW_TINT}, {TCARD: _man()})
    zp = str(tmp_path / "s.zip")
    scene_edit.export_edits(mine, zp)
    built = _built(SHADOW_TINT)
    theirs = _edits_project(tmp_path / "theirs", {}, {TCARD: built})
    scene_edit.import_edits(theirs, zp, [TCARD])
    assert scene_edit.note_shown(theirs, {TCARD: built},
                                 states=scene_edit.read_states(zp)) == {TCARD: 2}
    assert scene_edit.to_apply(theirs, TCARD, built) == []
    # the shadow alone built: the tint after it is still to apply
    half = _built(SHADOW_TINT[:1])
    os.remove(os.path.join(theirs, *scene_edit.RELDIR, scene_edit.CARRIED_FILENAME))
    assert scene_edit.note_shown(theirs, {TCARD: half},
                                 states=scene_edit.read_states(zp)) == {TCARD: 1}


def test_his_file_saved_before_the_fix_draws_its_shadows(tmp_path):
    """His file's states: each shadow's node looking the same before and after it."""
    states = scene_edit.states_of(_man(), SHADOW_TINT[:1])
    for fp in list(states["before"].values()) + states["after"]:
        fp.pop("c", None)
        fp.pop("s", None)
    assert states["after"][0] == states["before"]["53"]
    a = _edits_project(tmp_path, {TCARD: SHADOW_TINT[:1]}, {TCARD: _man()})
    assert scene_edit.note_shown(a, {TCARD: _man()}, states={TCARD: states}) == {TCARD: 0}
    assert scene_edit.to_apply(a, TCARD, _man()) == SHADOW_TINT[:1]


def test_a_moved_line_a_profile_recolored_on_the_card_is_still_told_by_its_move(tmp_path):
    """The colour track counts only for a node a tint edits: PAD-438 writes a profiled line's
    colour into it, and a moved line must not then look unmoved and be moved twice."""
    moves = [{"op": "move", "node": 53, "dx": 30.0, "dy": 0.0}]
    mine = _edits_project(tmp_path / "mine", {TCARD: moves}, {TCARD: _man()})
    zp = str(tmp_path / "m.zip")
    scene_edit.export_edits(mine, zp)
    built = _built(moves)
    for n, _sibs in scene_edit._man_index(built).values():
        if n["id"] == 53:
            n["col"] = [[1, [0.5, 0.5, 0.5, 1.0], [0.0, 0.0, 0.0, 0.0]]]
    theirs = _edits_project(tmp_path / "theirs", {}, {TCARD: built})
    scene_edit.import_edits(theirs, zp, [TCARD])
    assert scene_edit.note_shown(theirs, {TCARD: built},
                                 states=scene_edit.read_states(zp)) == {TCARD: 1}
