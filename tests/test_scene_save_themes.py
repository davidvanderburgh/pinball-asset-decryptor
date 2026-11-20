"""Scenes' "Save ... with pictures, text and color profiles" carries the themes (Simon, 2026-11-20).

Simon: "if a scene has multiple theme use then any graphics that go with the scene should be saved including if they are
in other themes and that makes me think we would need to save Themes too without asking the user". The file carries
the theme names and, for the pictures saved, each theme's own picture (its file and Keep size tick) and its own color
switch and profile; loading finds each theme by name (or adds it), switches themes on, copies the pictures into the
Shared pictures folder and asks first where a theme here already has its own.
"""
import os
import zipfile

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_edit, scene_share, scene_variants as SV
from tests.test_pad502_save_game_picture_profiles import (BACK, CARD, ELSE, HERO, SEPIA, _doc, _project,
                                                          _trees)

PIL = pytest.importorskip("PIL.Image")


def _png(root, name, colour):
    p = root / name
    PIL.new("RGB", (8, 8), colour).save(p)
    return str(p)


def _themed(root):
    """Standard, DARK and LIGHT: DARK picks its own hero (Keep size ticked) and its own picture for the other scene's
    ELSE; LIGHT colors the battle scene's BACK with a profile of its own (no picture of its own)."""
    p = _project(root, "themed")
    SV.set_themes_on(p, True)
    assert SV.add_set(p, "DARK") == 2 and SV.add_set(p, "LIGHT") == 3
    SV.set_picture(p, 2, "images/" + HERO, _png(root, "dark hero.png", (10, 10, 10)))
    SV.set_keep_size(p, 2, "images/" + HERO, True)
    SV.set_picture(p, 2, "images/" + ELSE, _png(root, "dark else.png", (20, 20, 20)))
    side = staged_changes.load(p)
    side[cp.IMAGE_SLOTS_KEY] = {SV.theme_key(3, "images/" + BACK): True}
    side[cp.FILE_PROFILES_KEY["images"]] = {SV.theme_key(3, "images/" + BACK): SEPIA}
    staged_changes.save(p, side)
    return p


def _load(project, path, skip=()):
    extras = scene_share.localise(project, scene_share.read_extras(path), _trees())
    report = {}
    n = scene_share.import_themes(project, path, extras["themes"], skip=skip, report=report)
    return n, report


def test_every_scene_saved_carries_the_themes_and_they_load(tmp_path):
    src = _themed(tmp_path)
    path = str(tmp_path / "all.zip")
    counts = {}
    scene_share.export_all(src, path, None, _trees(), counts=counts)
    assert counts["themes"] == 3
    doc = _doc(path)
    assert doc["themes"]["names"] == ["Standard", "DARK", "LIGHT"]
    hero = doc["themes"]["pictures"]["images/" + HERO]["themes"]["2"]
    assert hero["keep"] is True and hero["name"] == "dark hero.png"
    with zipfile.ZipFile(path) as z:
        assert hero["file"] in z.namelist()
    back = doc["themes"]["pictures"]["images/" + BACK]["themes"]["3"]
    assert back == {"keep": False, "color": True, "profile": SEPIA}            # a color of its own, no picture

    dest = _project(tmp_path, "fresh")
    assert not SV.themes_on(dest)
    n, report = _load(dest, path)
    assert n == 3 and report["switched_on"] and report["added"] == ["DARK", "LIGHT"]
    assert SV.themes_on(dest) and SV.set_names(dest) == ["Standard", "DARK", "LIGHT"]
    picks = SV.set_pictures(dest, 2)
    assert os.path.dirname(picks["images/" + HERO]).startswith(os.path.join(dest, scene_share.SHARED_DIR))
    with open(picks["images/" + HERO], "rb") as f, open(str(tmp_path / "dark hero.png"), "rb") as g:
        assert f.read() == g.read()
    assert SV.keeps_size(dest, 2, "images/" + HERO) is True
    assert "images/" + ELSE in picks
    side = staged_changes.load(dest)
    key = SV.theme_key(3, "images/" + BACK)
    assert side[cp.IMAGE_SLOTS_KEY][key] is True and side[cp.FILE_PROFILES_KEY["images"]][key] == SEPIA


def test_this_scene_saved_carries_only_its_pictures_themes(tmp_path):
    src = _themed(tmp_path)
    path = str(tmp_path / "battle.zip")
    scene_share.export_all(src, path, [CARD], _trees())
    pics = _doc(path)["themes"]["pictures"]
    assert set(pics) == {"images/" + HERO, "images/" + BACK}                  # not the other scene's ELSE
    assert pics["images/" + HERO]["drawn"]                                    # found by its nodes elsewhere


def test_a_scene_with_no_theme_of_its_own_saves_none(tmp_path):
    p = _project(tmp_path, "plain")
    side = staged_changes.load(p)
    side["image"] = {"images/" + HERO: _png(tmp_path, "mine.png", (1, 2, 3))}
    staged_changes.save(p, side)
    path = str(tmp_path / "plain.zip")
    scene_share.export_all(p, path, [CARD], _trees())
    assert "themes" not in _doc(path)
    assert scene_share.read_extras(path)["themes"] is None


def test_a_theme_is_found_here_by_its_name(tmp_path):
    src = _themed(tmp_path)
    path = str(tmp_path / "all.zip")
    scene_share.export_all(src, path, None, _trees())
    dest = _project(tmp_path, "mine")
    SV.set_themes_on(dest, True)
    assert SV.add_set(dest, "light") == 2                                    # the file's LIGHT, any case
    _n, report = _load(dest, path)
    assert report["added"] == ["DARK"] and not report["switched_on"]
    assert SV.set_names(dest) == ["Standard", "light", "DARK"]
    assert "images/" + HERO in SV.set_pictures(dest, 3)                       # DARK's, at 3 here
    key = SV.theme_key(2, "images/" + BACK)                                   # LIGHT's color, at 2 here
    assert staged_changes.load(dest)[cp.FILE_PROFILES_KEY["images"]][key] == SEPIA


def test_a_theme_here_with_its_own_is_asked_about_and_can_be_kept(tmp_path):
    src = _themed(tmp_path)
    path = str(tmp_path / "all.zip")
    scene_share.export_all(src, path, None, _trees())
    dest = _project(tmp_path, "mine")
    SV.set_themes_on(dest, True)
    SV.add_set(dest, "DARK")
    mine = _png(tmp_path, "my dark hero.png", (90, 0, 0))
    SV.set_picture(dest, 2, "images/" + HERO, mine)
    extras = scene_share.localise(dest, scene_share.read_extras(path), _trees())
    clash = scene_share.clashes(dest, extras)
    assert clash["themes"] == [("DARK", "images/" + HERO)]
    items = scene_share.conflict_items(dest, {}, extras, clash, [])
    assert [it["id"] for it in items] == ["themes"] and "DARK" in items[0]["what"]
    _load(dest, path, skip=clash["themes"])
    assert SV.set_pictures(dest, 2)["images/" + HERO] == mine                 # kept
    assert "images/" + ELSE in SV.set_pictures(dest, 2)                        # the rest came


def test_a_file_saved_before_themes_loads_as_before(tmp_path):
    p = _project(tmp_path, "old")
    path = str(tmp_path / "old.zip")
    scene_edit.save(p, {CARD: [{"op": "move", "node": 1, "dx": 1.0, "dy": 0.0}]})
    scene_edit.export_edits(p, path)
    extras = scene_share.read_extras(path)
    assert extras["themes"] is None and not scene_share.has_extras(extras)
    assert scene_share.import_themes(p, path, None) == 0
    assert not SV.themes_on(p)


def test_the_scenes_page_saves_and_loads_the_themes(tmp_path):
    """Through the Scenes page: Save every scene with pictures, then Load into a project whose DARK theme has its own
    picture for it - asked, replaced, and the caption says so."""
    from tests.test_gui_scene_editor import _open, _seed, _wait
    from tests.webui_harness import web_app
    mine, friend = tmp_path / "mine", tmp_path / "friend"
    man = _seed(mine)
    _seed(friend)
    rel = "images/" + next(o for o in man["objects"].values() if o.get("kind") == "Bitmap" and o.get("image"))["image"]
    SV.set_themes_on(str(mine), True)
    SV.add_set(str(mine), "DARK")
    theirs = _png(tmp_path, "their dark.png", (0, 0, 90))
    SV.set_picture(str(mine), 2, rel, theirs)
    SV.set_themes_on(str(friend), True)
    SV.add_set(str(friend), "dark")
    SV.set_picture(str(friend), 2, rel, _png(tmp_path, "my dark.png", (90, 0, 0)))
    zip_path = str(tmp_path / "look.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, mine)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "all", True) == zip_path
        assert "1 theme picture or color" in w.state("text_scenes").get("caption_full", w.state(
            "text_scenes").get("caption", ""))
        _open(w, friend)
        w.answers.extend([zip_path, {"choice": "replace", "backup": False}])
        w.call("text_scenes.edits_load")
        assert any(i["id"] == "themes" for i in w.asked[-1]["items"])
        assert _wait(w, lambda: os.path.basename(SV.set_pictures(str(friend), 2).get(rel, "")) == "their dark.png")
        cap = w.state("text_scenes").get("caption_full", "")
        assert "1 theme picture or color loaded." in cap, cap


def test_a_scene_load_leaves_the_service_menu_alone(tmp_path):
    """Simon (2026-11-20): "a scene save shouldn't touch that" - the Service menu tab's rows are neither saved nor
    changed by a load."""
    from pinball_decryptor.plugins.stern import service_menu
    src = _themed(tmp_path)
    side = staged_changes.load(src)
    side[service_menu.STAGED_KEY] = {"on": ["IMAGE_SET"]}
    staged_changes.save(src, side)
    path = str(tmp_path / "all.zip")
    scene_share.export_all(src, path, None, _trees())
    assert service_menu.STAGED_KEY not in _doc(path)
    dest = _project(tmp_path, "mine")
    mine = {"on": ["COOP"], "order": ["COOP"]}
    side = staged_changes.load(dest)
    side[service_menu.STAGED_KEY] = mine
    staged_changes.save(dest, side)
    extras = scene_share.localise(dest, scene_share.read_extras(path), _trees())
    scene_share.import_extras(dest, path, extras)
    _load(dest, path)
    assert staged_changes.load(dest)[service_menu.STAGED_KEY] == mine
