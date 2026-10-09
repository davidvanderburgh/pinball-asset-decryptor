"""PAD-368 (DragonRR): one color profile per file.  Each replaced picture, clip or picture
added in Scenes can have an individual files profile of its own (core/colour_profile.py
``store_own_profile``); one without gets the project's, as before.  The Color profiles bar
turns to the clicked file's profile, and the Images, Video and Scenes tooltips name it."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")
pytest.importorskip("numpy")

FILES = cp.undo_screen(cp.SCREEN_PRESETS[0][1])
RED = cp.Profile(name="Custom red", gain=(1.3, 0.9, 0.9))
BRIGHT = cp.Profile(name="Brighter", brightness=1.2, contrast=1.1)

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def _src(name):
    return open(os.path.join(_TABS, name), encoding="utf-8").read()


def _ramp():
    im = PIL.new("RGB", (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            px[x, y] = (x * 4, x * 2, 255 - x * 4)
    return im


# -- the model -----------------------------------------------------------------

def test_a_files_own_profile_wins_over_the_projects(tmp_path):
    d = str(tmp_path)
    cp.set_asset_all(d, "images", True)
    rels = ["portrait.png", "tv.png", "grey.png"]
    assert cp.asset_map(d, "images", rels) == {r: FILES for r in rels}
    sig = cp.asset_signature(d)
    cp.store_own_profile(d, "images", "tv.png", RED)
    cp.store_own_profile(d, "images", "grey.png", BRIGHT)
    assert cp.asset_signature(d) != sig
    got = cp.asset_map(d, "images", rels)
    assert got["portrait.png"] == FILES
    assert got["tv.png"].key() == RED.key() and got["tv.png"].name == "Custom red"
    assert got["grey.png"].key() == BRIGHT.key()
    assert cp.file_profile(d, "images", "portrait.png") == FILES
    assert cp.own_profile(d, "images", "portrait.png") is None
    assert cp.own_profile_names(d) == {"images": {"tv.png": "Custom red",
                                                  "grey.png": "Brighter"},
                                       "videos": {}, "text": {}}
    # the switch still decides: off is off, whatever profile it has
    cp.set_asset_slot(d, "images", "tv.png", False)
    assert "tv.png" not in cp.asset_map(d, "images", rels)
    # back to the project's
    cp.store_own_profile(d, "images", "grey.png", None)
    assert cp.asset_map(d, "images", rels)["grey.png"] == FILES
    assert "grey.png" not in cp.own_profile_names(d)["images"]


def test_no_change_on_the_project_but_one_file_corrected(tmp_path):
    d = str(tmp_path)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    cp.set_asset_all(d, "videos", True)
    assert cp.asset_active(d) is None and cp.any_asset_active(d) is False
    assert cp.asset_signature(d) == ""
    cp.store_own_profile(d, "videos", "clip.mp4", RED)
    assert cp.any_asset_active(d) is True
    assert cp.asset_signature(d)
    got = cp.asset_map(d, "videos", ["clip.mp4", "other.mp4"])
    assert list(got) == ["clip.mp4"]
    # an own No change sends that file as it is, the others keep theirs
    cp.store_asset_profile(d, None)
    cp.store_own_profile(d, "videos", "clip.mp4", cp.Profile(name="No change"))
    assert list(cp.asset_map(d, "videos", ["clip.mp4", "other.mp4"])) == ["other.mp4"]


def test_an_own_recommended_follows_the_machine_screen(tmp_path):
    d = str(tmp_path)
    cp.store_asset_profile(d, RED)
    cp.store_own_profile(d, "images", "a.png", None, follow=True)
    assert cp.own_follows_screen(d, "images", "a.png")
    assert cp.file_profile(d, "images", "a.png") == FILES
    cp.store_screen_profile(d, cp.Profile(name="Mine", gamma=(1.2, 1.2, 1.2)))
    assert cp.file_profile(d, "images", "a.png") == cp.recommended(d, files=True)
    assert cp.file_profile(d, "images", "a.png") != FILES


def test_an_added_picture_and_a_video_player_use_their_own(tmp_path):
    d = str(tmp_path)
    op = {"op": "add_picture", "image": "scene_textures/added/pic_1.png", "color": True}
    assert cp.added_picture_colour(d, op) == FILES
    cp.store_own_profile(d, "images", op["image"], RED)
    assert cp.added_picture_colour(d, op).key() == RED.key()
    assert cp.added_picture_colour(d, dict(op, color=False)) is None
    cp.store_own_profile(d, "videos", "clip.mp4", RED)
    own = cp.video_look(d, True, False, overlay_on=False, screen_on=False, rel="clip.mp4")
    other = cp.video_look(d, True, False, overlay_on=False, screen_on=False, rel="b.mp4")
    assert own["rep"] == [cp.filter_step(RED)]
    assert other["rep"] == [cp.filter_step(FILES)]


def test_staging_bakes_each_pictures_own_profile(tmp_path):
    from pinball_decryptor.core.image_slots import ImageSlot, stage_replacements
    from pinball_decryptor.core.image import detect_image_info
    proj = tmp_path / "proj"
    proj.mkdir()
    slots = {}
    for name in ("portrait.png", "tv.png"):
        f = proj / name
        PIL.new("RGB", (64, 4), (0, 0, 0)).save(f)
        slots[name] = ImageSlot(rel_path=name, abs_path=str(f), ext=".png",
                                info=detect_image_info(str(f)),
                                size=os.path.getsize(f), probed=True)
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    cp.set_asset_all(str(proj), "images", True)
    cp.store_own_profile(str(proj), "images", "tv.png", RED)
    with cp.forced(False):
        n, fails = stage_replacements(slots, {r: str(rep) for r in slots},
                                      assets_dir=str(proj))
    assert n == 2 and not fails
    got = lambda r: PIL.open(proj / r).convert("RGB").tobytes()   # noqa: E731
    assert got("portrait.png") == FILES.apply_image(_ramp()).tobytes()
    assert got("tv.png") == RED.apply_image(_ramp()).tobytes()


def test_the_scene_preview_draws_each_pictures_own_profile(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as R
    proj = tmp_path / "proj"
    (proj / "images" / "scene_textures").mkdir(parents=True)
    mine = tmp_path / "mine.png"
    _ramp().save(mine)
    picks = {}
    for name in ("a.png", "b.png"):
        PIL.new("RGBA", (64, 4), (0, 0, 0, 255)).save(
            str(proj / "images" / "scene_textures" / name))
        picks["images/scene_textures/" + name] = str(mine)
    staged_changes.save(str(proj), {"image": picks})
    cp.set_asset_all(str(proj), "images", True)
    cp.store_own_profile(str(proj), "images", "images/scene_textures/b.png", RED)
    pics = R.pending_pictures(str(proj))
    assert pics["scene_textures/a.png"]["colour"] == FILES
    assert pics["scene_textures/b.png"]["colour"].key() == RED.key()


def test_write_lists_the_own_profiles_and_revert_all_drops_them(tmp_path):
    from pinball_decryptor.webui.write_scan import chosen_files_rows

    class Mfr:
        def colour_profile_on_display(self):
            return True
    d = str(tmp_path)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    staged_changes.save(d, dict(staged_changes.load(d), image={"a.png": "x.png"}))
    cp.set_asset_all(d, "images", True)
    assert chosen_files_rows(Mfr(), d) == []
    cp.store_own_profile(d, "images", "a.png", RED)
    (row,) = chosen_files_rows(Mfr(), d)
    assert "1 file with its own" in row[0]
    from pinball_decryptor.core import tab_settings
    assert "image_color_profiles" in tab_settings.SECTIONS["images"]
    assert "video_color_profiles" in tab_settings.SECTIONS["video"]


# -- the Color profiles bar ------------------------------------------------------

def test_the_bar_on_a_clicked_file_changes_that_files_profile_only(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, BANNER
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        w.drain()
        w.call("images.select", BANNER)
        assert w.call("color.panel_open")
        # clicking the picture turns the bar to Files on it, showing what it gets now
        assert w.call("color.set_file", "images", BANNER, "SpaceGodzilla.png", False,
                      {"ns": "images"})
        w.drain()
        s = w.state("color")
        assert s["mode"] == "assets"
        assert s["file"] == {"kind": "images", "rel": BANNER, "label": "SpaceGodzilla.png",
                             "on": False, "own": False, "count": 1, "own_n": 0}
        assert s["name"] == "Recommended"
        # a change is the file's own, and attaches it (its switch was off)
        w.call("color.set_params", {"name": "Custom red", "gain": [1.3, 0.9, 0.9]})
        w.drain()
        assert cp.own_profile(assets, "images", BANNER).gain == (1.3, 0.9, 0.9)
        assert cp.asset_stored(assets) is False            # the project's is untouched
        assert staged_changes.load(assets)["image_color_slots"] == {BANNER: True}
        s = w.state("color")
        assert s["file"]["own"] is True and s["file"]["on"] is True
        assert s["own_names"]["images"] == {BANNER: "Custom red"}
        # the Images preview's line under its switch names it
        assert w.state("images")["preview"]["color"]["name"] == "Custom red"
        # Undo puts back what it was: no profile of its own
        assert w.call("color.undo")
        assert cp.own_profile(assets, "images", BANNER) is None
        assert w.call("color.undo", True)
        assert cp.own_profile(assets, "images", BANNER).name == "Custom red"
        # Recommended on one file follows the screen
        assert w.call("color.preset", "recommended")
        assert cp.own_follows_screen(assets, "images", BANNER)
        assert w.state("color")["preset_on"] == "recommended"
        # Same as the other files
        assert w.call("color.file_shared")
        assert cp.own_profile(assets, "images", BANNER) is None
        assert w.state("color")["file"]["own"] is False
        # no file: the bar is the project's profile again
        cp.store_own_profile(assets, "images", BANNER, RED)
        w.call("color.set_file")
        w.drain()
        assert w.state("color")["file"] is None
        w.call("color.set_params", {"name": "Project", "gamma": [1.1, 1.1, 1.1]})
        w.drain()
        assert cp.asset_profile(assets).name == "Project"
        assert cp.own_profile(assets, "images", BANNER).name == "Custom red"
        # the Color profile tab itself is never one file's; Revert all drops them
        w.call("color.set_file", "images", BANNER, "x", True, None)
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.state("color")["file"] is None
        w.window.service("color").clear_replace_assignments(assets)
        assert cp.own_profile_names(assets)["images"] == {}


def test_the_bar_and_the_tooltips_are_wired_in_the_pages():
    pane = _src("color_pane.js")
    assert 'call("color.set_file", file.kind, file.rel' in pane
    assert "Same as the other files" in pane
    for name, host in (("images.js", 'host="images"'), ("video.js", 'host="video"'),
                       ("scenes.js", 'host="scenes"')):
        src = _src(name)
        bar = src[src.index("<${ColorBar} " + host):]
        assert "file=${" in bar[:400], name
    for name in ("images.js", "video.js"):
        src = _src(name)
        # PAD-369: a {profile} line, drawn in its own color by core/ui.js
        assert "{ profile: " in src and '{ profile: "None" }' in src, name
    ts = _src("text_scenes.js")
    tip = ts[ts.index("const rowTip"):]
    assert tip.index("layerProfile(l, cs)") < tip.index('["Click"'), \
        "the Scenes layer tooltip names the profile above Click"
