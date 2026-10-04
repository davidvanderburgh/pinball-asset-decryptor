"""PAD-330: the preview's three colour switches (overlay, individual files,
machine screen) replace the single As on the machine tick, the same row on
Scenes and the Video tab.  Each switch leaves out its own step and nothing
else, and none of them changes what is staged for the card."""

import json
import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

np = pytest.importorskip("numpy")

OVER = cp.Profile(name="Less red", gain=(0.5, 1.0, 1.0))
BW = cp.Profile(name="Black and white", saturation=0.0)


def _setup(d):
    cp.store(d, OVER)
    cp.store_screen_profile(d, BW)
    # a black and white screen cannot be undone, so its Recommended files
    # profile changes nothing (PAD-346): set the measured one
    cp.store_asset_profile(d, dict(cp.PRESETS)["recommended"])


def test_machine_view_leaves_out_only_the_switched_off_step(tmp_path):
    d = str(tmp_path)
    _setup(d)
    rgb = np.asarray([[[200, 40, 40]]], np.uint8)
    both = cp.machine_view(d)(rgb)
    over_only = cp.machine_view(d, screen_on=False)(rgb)
    screen_only = cp.machine_view(d, overlay_on=False)(rgb)
    assert over_only.tobytes() == OVER.apply_array(rgb).tobytes()
    assert screen_only.tobytes() == BW.apply_array(rgb).tobytes()
    assert both.tobytes() == BW.apply_array(OVER.apply_array(rgb)).tobytes()
    assert cp.machine_view(d, overlay_on=False, screen_on=False) is None
    assert cp.machine_view(d, screen_on=False).overlay is not None
    assert cp.machine_view(d, overlay_on=False).overlay is None


def test_video_look_leaves_out_only_the_switched_off_step(tmp_path):
    d = str(tmp_path)
    _setup(d)
    o, s = cp.filter_step(OVER), cp.filter_step(BW)
    f = cp.filter_step(cp.asset_profile(d))
    assert cp.video_look(d, True, True)["rep"] == [f, o, s]
    assert cp.video_look(d, True, True, overlay_on=False)["rep"] == [f, s]
    assert cp.video_look(d, True, True, files_on=False)["rep"] == [o, s]
    assert cp.video_look(d, True, True, screen_on=False)["rep"] == [f, o]
    assert cp.video_look(d, None, True, screen_on=False)["orig"] == [o]


def test_the_scene_preview_leaves_the_bake_out_with_files_off(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as R
    proj = tmp_path / "proj"
    (proj / "images" / "scene_textures").mkdir(parents=True)
    mine = tmp_path / "mine.png"
    from PIL import Image
    Image.new("RGBA", (4, 4), (200, 100, 50, 255)).save(mine)
    staged_changes.save(str(proj), {"image": {"images/scene_textures/a.png": str(mine)}})
    cp.set_asset_all(str(proj), "images", True)
    assert R.pending_pictures(str(proj))["scene_textures/a.png"]["colour"] is not None
    pics = R.pending_pictures(str(proj), bake=False)
    assert pics["scene_textures/a.png"]["colour"] is None
    assert pics["scene_textures/a.png"]["skip"] is False


def test_preview_parts_name_what_each_switch_does(tmp_path):
    d = str(tmp_path)
    p = cp.preview_parts(d)
    assert p["overlay"] == {"name": "", "set": False}
    assert p["files"]["set"] is False and p["files"]["count"] == 0
    assert p["screen"] == {"name": "Recommended screen", "set": True, "stored": False}
    _setup(d)
    staged_changes.save(d, dict(staged_changes.load(d),
                                image={"images/x.png": __file__}))
    cp.set_asset_all(d, "images", True)
    p = cp.preview_parts(d)
    assert p["overlay"] == {"name": "Less red", "set": True}
    assert p["files"] == {"name": "Recommended", "set": True, "count": 1,
                          "by_overlay": False}
    assert p["screen"]["name"] == "Black and white" and p["screen"]["stored"] is True


def test_the_video_tab_switches_change_the_players_only(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    _setup(str(proj))
    side = os.path.join(str(proj), staged_changes.SIDE_CAR)
    before = open(side, encoding="utf-8").read()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "video")
        w.drain()
        look = w.state("video")["look"]
        assert look["sw"] == {"overlay": True, "files": True, "screen": True}
        assert look["parts"]["overlay"]["name"] == "Less red"
        assert look["orig"] == [cp.filter_step(OVER), cp.filter_step(BW)]
        assert w.call("video.set_look_part", "overlay", False)
        w.drain()
        look = w.state("video")["look"]
        assert look["sw"]["overlay"] is False and look["orig"] == [cp.filter_step(BW)]
        assert w.call("video.set_look_part", "screen", False)
        w.drain()
        assert w.state("video")["look"]["orig"] == []
        assert w.call("video.set_look_part", "nonsense", False) is False
        assert w.call("video.set_machine_look", True)
        w.drain()
        assert all(w.state("video")["look"]["sw"].values())
    assert json.loads(open(side, encoding="utf-8").read()) == json.loads(before)


def test_the_scenes_switches_change_the_preview_only(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    _setup(str(folder))
    side = os.path.join(str(folder), staged_changes.SIDE_CAR)
    before = json.loads(open(side, encoding="utf-8").read())
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        look = w.state("text_scenes")["look"]
        assert look["sw"] == {"overlay": True, "files": True, "screen": True}
        assert look["parts"]["screen"]["name"] == "Black and white"
        assert w.call("text_scenes.set_look_part", "screen", False)
        view = w.run(svc._machine_view)
        rgb = np.asarray([[[200, 40, 40]]], np.uint8)
        assert view(rgb).tobytes() == OVER.apply_array(rgb).tobytes()
        assert w.call("text_scenes.set_look_part", "overlay", False)
        assert w.run(svc._machine_view) is None
        assert w.state("text_scenes")["machine_look"] is True    # files still on
        assert w.call("text_scenes.set_look_part", "files", False)
        assert w.state("text_scenes")["machine_look"] is False
        w.call("text_scenes.close")
    assert json.loads(open(side, encoding="utf-8").read()) == before


def test_the_switches_come_back_as_they_were_left(tmp_path):
    """PAD-348 (DragonRR): opening PAD switched every overlay back on; the
    Scenes and Video switches are now remembered, each on their own."""
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    _setup(str(folder))
    settings = tmp_path / "cfg" / "settings.json"
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.set_look_part", "overlay", False)
        assert w.call("text_scenes.set_look_part", "screen", False)
        assert w.call("video.set_look_part", "files", False)
        w.call("text_scenes.close")
    saved = json.loads(settings.read_text(encoding="utf-8"))["look_switches"]
    with web_app(tmp_path, mfr="stern", settings={"look_switches": saved}) as w:
        _open(w, folder)
        assert w.state("text_scenes")["look"]["sw"] == {
            "overlay": False, "files": True, "screen": False}
        assert w.state("text_scenes")["machine_look"] is True
        w.call("ui.select_tab", "video")
        w.drain()
        assert w.state("video")["look"]["sw"] == {
            "overlay": True, "files": False, "screen": True}
        assert w.call("text_scenes.set_machine_look", True)
        w.call("text_scenes.close")
    saved = json.loads(settings.read_text(encoding="utf-8"))["look_switches"]
    assert all(saved["scenes"].values())
    assert saved["video"]["files"] is False
