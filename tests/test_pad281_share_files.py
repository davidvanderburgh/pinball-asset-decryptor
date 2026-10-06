"""PAD-281: modes and scene edits saved to a file, to keep or to share, and loaded back."""
import json
import os
import zipfile

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import scene_edit


# ---- modes ---------------------------------------------------------------------------------
def _card(tmp_path, name, card="godzilla_pro-1_15_0.raw"):
    project = str(tmp_path / name)
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def test_modes_round_trip_through_a_file(tmp_path):
    src = _card(tmp_path, "mine")
    slug, spec = MP.new_mode(src, spec=MP.ModeSpec(name="TARGET RUSH",
                                                   title=MP.GODZILLA_PRO_1_15.key))
    with open(os.path.join(MP.mode_folder(src, slug), "art.png"), "wb") as f:
        f.write(b"png")
    MP.new_mode(src, spec=MP.ModeSpec(name="OTHER", title=MP.GODZILLA_PRO_1_15.key))
    code = os.path.join(MP.modes_dir(src), "laser_show")
    os.makedirs(code)
    with open(os.path.join(code, "laser_show.c"), "w", encoding="utf-8") as f:
        f.write('#define MODE_NAME "LASER SHOW"\n')

    one = str(tmp_path / "one.zip")
    assert MP.export_modes(src, one, [slug]) == [slug]
    with zipfile.ZipFile(one) as z:
        assert sorted(z.namelist()) == sorted([
            MP.SHARE_MANIFEST, "modes/target_rush/mode.json", "modes/target_rush/art.png"])
    every = str(tmp_path / "all.zip")
    assert MP.export_modes(src, every) == ["other", "target_rush", "laser_show"]

    # a friend's project of the same card takes them as they are
    friend = _card(tmp_path, "friend")
    r = MP.import_modes(one, friend)
    assert [(m.slug, m.state, m.new_slug) for m in r.modes] == [
        (slug, MP.COPY_CARRIED, slug)]
    got = MP.load(os.path.join(MP.mode_folder(friend, slug), MP.MODE_FILE))
    assert got.name == "TARGET RUSH"
    with open(os.path.join(MP.mode_folder(friend, slug), "art.png"), "rb") as f:
        assert f.read() == b"png"
    # loaded again (a backup put back): a name of its own beside the first
    r = MP.import_modes(every, friend)
    assert [m.new_slug for m in r.modes] == ["other", "target_rush_2", "laser_show"]
    assert os.path.isfile(os.path.join(MP.modes_dir(friend), "laser_show", "laser_show.c"))


def test_a_modes_file_is_checked_before_anything_is_written(tmp_path):
    project = _card(tmp_path, "p")
    with pytest.raises(MP.ModeProjectError, match="no modes to save"):
        MP.export_modes(project, str(tmp_path / "x.zip"))
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(MP.ModeProjectError, match="not a file of modes"):
        MP.import_modes(str(junk), project)
    other = str(tmp_path / "other.zip")
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(MP.ModeProjectError, match="not a file of modes"):
        MP.import_modes(other, project)
    # a path that climbs out of the modes folder is never written
    evil = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr(MP.SHARE_MANIFEST, json.dumps({"kind": MP.SHARE_KIND, "modes": ["m"]}))
        z.writestr("modes/m/mode.json", json.dumps(
            MP.ModeSpec(name="M", title=MP.GODZILLA_PRO_1_15.key).to_json()))
        z.writestr("modes/m/../../../escaped.txt", "x")
    MP.import_modes(evil, project)
    assert not os.path.exists(tmp_path / "escaped.txt")
    assert not os.path.exists(os.path.join(project, "escaped.txt"))
    assert os.listdir(MP.modes_dir(project)) == ["m"]


# ---- scene edits ---------------------------------------------------------------------------
LE = "/godzilla_le/assets/lcd/auto_loaded/aaa/scene.radium"
LE2 = "/godzilla_le/assets/lcd/auto_loaded/bbb/scene.radium"
PRO = "/godzilla_pro/assets/lcd/auto_loaded/aaa/scene.radium"


def _picture(assets, rel, data):
    path = os.path.join(assets, "images", *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_scene_edits_round_trip_with_their_pictures(tmp_path):
    mine = str(tmp_path / "mine")
    pic = {"op": "add_picture", "parent": None, "index": 1, "id": 0x7F000000, "name": "PAD_logo",
           "image": "scene_textures/added/logo_1.png", "w": 4, "h": 4, "x": 0, "y": 0}
    scene_edit.save(mine, {LE: [{"op": "move", "node": 5, "dx": 1, "dy": 2}, pic],
                           LE2: [{"op": "visible", "node": 7, "on": False}]})
    _picture(mine, pic["image"], b"LOGO")

    one = str(tmp_path / "one.zip")
    assert scene_edit.export_edits(mine, one, [LE]) == 1
    with zipfile.ZipFile(one) as z:
        assert sorted(z.namelist()) == [
            "images/scene_textures/added/logo_1.png", scene_edit.SHARE_MANIFEST]
    every = str(tmp_path / "all.zip")
    assert scene_edit.export_edits(mine, every) == 2

    # a Pro project: the same scene under its own game folder; bbb is not on that card
    friend = str(tmp_path / "friend")
    _picture(friend, pic["image"], b"SOMETHING ELSE")        # a picture of the same name
    scene_edit.save(friend, {PRO: [{"op": "move", "node": 1, "dx": 9, "dy": 9}]})
    got, missing = scene_edit.import_edits(friend, every, [PRO])
    assert sorted(got) == [PRO] and missing == [LE2]
    ops = scene_edit.load(friend)[PRO]
    assert ops[0] == {"op": "move", "node": 5, "dx": 1, "dy": 2}   # the file's, in place of its own
    assert ops[1]["image"] == "scene_textures/added/logo_1_2.png"
    with open(os.path.join(friend, "images", "scene_textures", "added", "logo_1_2.png"),
              "rb") as f:
        assert f.read() == b"LOGO"
    with open(os.path.join(friend, "images", "scene_textures", "added", "logo_1.png"),
              "rb") as f:
        assert f.read() == b"SOMETHING ELSE"
    # loaded again: the picture already here is the same one, so no third copy
    scene_edit.import_edits(friend, every, [PRO])
    assert sorted(os.listdir(os.path.join(friend, "images", "scene_textures", "added"))) == [
        "logo_1.png", "logo_1_2.png"]


def test_a_scene_edits_file_is_checked(tmp_path):
    assets = str(tmp_path / "p")
    with pytest.raises(scene_edit.SceneEditError, match="no scene edits"):
        scene_edit.export_edits(assets, str(tmp_path / "x.zip"))
    other = str(tmp_path / "other.zip")
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(scene_edit.SceneEditError, match="not a file of scene edits"):
        scene_edit.read_share(other)
    evil = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr(scene_edit.SHARE_MANIFEST, json.dumps({
            "kind": scene_edit.SHARE_KIND, "scenes": {LE: [
                {"op": "add_picture", "image": "../../escaped.png"}]}}))
        z.writestr("images/../../escaped.png", "x")
    scene_edit.import_edits(assets, evil)
    assert not os.path.exists(tmp_path / "escaped.png")


# ---- the tabs' calls -----------------------------------------------------------------------
def test_modes_tab_saves_and_loads_a_file(tmp_path, monkeypatch):
    from pinball_decryptor.core import preview
    from tests.test_webui_modes import _card_project, _modes_on_disk, _project
    from tests.webui_harness import web_app
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    src = _card_project(tmp_path / "mine", "godzilla_le-1_16_0.raw")
    dest = _card_project(tmp_path / "friend", "godzilla_pro-1_16_0.raw")
    zip_path = str(tmp_path / "KAIJU RUSH.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, src, card=None)
        assert w.call("modes.example", "KAIJU RUSH") == "kaiju_rush"
        w.answers.append(zip_path)
        assert w.call("modes.save_file", "this") == zip_path
        assert w.asked[-1]["title"] == "Save this mode to a file"
        assert os.path.isfile(zip_path)
        _project(w, dest, card=None)
        assert _modes_on_disk(dest) == []
        w.answers.append(zip_path)
        r = w.call("modes.load_file")
        assert [(m["state"], m["new_slug"]) for m in r["modes"]] == [("carried", "kaiju_rush")]
        assert _modes_on_disk(dest) == ["kaiju_rush"]
        assert w.asked[-1]["title"] == "Load modes"
        assert w.asked[-1]["message"].startswith("Loaded 1 mode from KAIJU RUSH.zip.")
        # cancelled: nothing
        w.answers.append("")
        assert w.call("modes.load_file") is None
        assert _modes_on_disk(dest) == ["kaiju_rush"]


def test_scenes_tab_saves_and_loads_a_file(tmp_path):
    from tests.test_gui_scene_editor import CARD, _open, _seed, _wait
    from tests.webui_harness import web_app
    mine, friend = tmp_path / "mine", tmp_path / "friend"
    _seed(mine)
    _seed(friend)
    zip_path = str(tmp_path / "edits.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, mine)
        scene_edit.save(str(mine), {CARD: [{"op": "move", "node": 5, "dx": 3, "dy": 4}]})
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "this") == zip_path
        assert os.path.isfile(zip_path)
        _open(w, friend)
        scene_edit.save(str(friend), {CARD: [{"op": "move", "node": 9, "dx": 1, "dy": 1}]})
        w.answers.append(zip_path)
        w.answers.append("cancel")               # PAD-402: "... you edited yourself" Cancel
        assert w.call("text_scenes.edits_load") is None
        assert w.asked[-1]["kind"] == "conflicts"
        assert scene_edit.ops_for(str(friend), CARD)[0]["node"] == 9
        w.answers.extend([zip_path, {"choice": "replace", "backup": False}])
        got = w.call("text_scenes.edits_load")
        assert got == [CARD], w.asked[-3:]
        assert scene_edit.ops_for(str(friend), CARD) == [
            {"op": "move", "node": 5, "dx": 3, "dy": 4}]
        assert _wait(w, lambda: w.state("text_scenes")["tree_view"]["all_edits"] == 1)
