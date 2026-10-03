"""PAD-345 (DragonRR): with the Images tab not on the folder, the Scenes Layers list's
"Unlock the game's own pictures" box and a game picture's switch only edited the sidecar.
A build had already corrected the project's file, so unticking the box (or switching the
picture off) left the corrected picture in the preview and on the next card.  Both now put
the pristine copy back, ticking the box never wakes a switch left from an old pick, and a
Scenes switch is recorded for the Scenes folder even when the Images tab has another
project scanned."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes, staged_originals

PIL = pytest.importorskip("PIL.Image")


def _setup(tmp_path):
    from tests.test_gui_scene_editor import _seed
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    art = next(o for o in man["objects"].values()
               if o.get("kind") == "Bitmap" and o.get("image"))
    return folder, "images/" + art["image"]


def _built(folder, rel):
    """The project as a build with *rel* switched on behind the unlock leaves it."""
    d = str(folder)
    path = os.path.join(d, *rel.split("/"))
    pristine = open(path, "rb").read()
    assert staged_originals.snapshot(d, rel, None)
    PIL.new("RGBA", PIL.open(path).size, (200, 200, 200, 255)).save(path)
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    data[cp.IMAGE_SLOTS_KEY] = {rel: True}
    staged_changes.save(d, data)
    return path, pristine


def _layer_id(w, rel):
    from tests.test_gui_scene_editor import _tv
    return next(l["id"] for l in _tv(w)["layers"]
                if l["kind"] == "Bitmap" and l["pics"] == [rel])


def test_unticking_puts_back_a_built_game_picture(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    folder, rel = _setup(tmp_path)
    path, pristine = _built(folder, rel)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", False)
        assert open(path, "rb").read() == pristine
        assert not staged_originals.has_snapshot(str(folder), rel)
        data = staged_changes.load(str(folder))
        assert not data.get(cp.STOCK_IMAGES_KEY) and not data.get(cp.IMAGE_SLOTS_KEY)
        w.call("text_scenes.close")


def test_switching_off_puts_back_a_built_game_picture(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    folder, rel = _setup(tmp_path)
    path, pristine = _built(folder, rel)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color", _layer_id(w, rel), False)
        assert open(path, "rb").read() == pristine
        assert cp.stock_image_rels(str(folder)) == []
        assert cp.stock_images_unlocked(str(folder))       # the box itself stays ticked
        w.call("text_scenes.close")


def test_ticking_does_not_wake_an_old_switch(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    folder, rel = _setup(tmp_path)
    cp.set_asset_slot(str(folder), "images", rel, True)    # left from a pick since cleared
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert cp.stock_images_unlocked(str(folder))
        assert cp.stock_image_rels(str(folder)) == []
        w.call("text_scenes.close")


def test_a_scenes_switch_stays_in_its_own_folder(tmp_path):
    """The Images tab on another project of the same game knows the same picture names;
    the switch is still this folder's."""
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open
    folder, rel = _setup(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        images = w.window.service("images")

        def _other():
            images._scan_dir = str(other)
            images._by_rel = {rel: object()}
            images._color_unlocked = True
        w.run(_other)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert w.call("text_scenes.tree_color", _layer_id(w, rel), True)
        assert cp.stock_image_rels(str(folder)) == [rel]
        assert w.run(lambda: dict(images._color)) == {}
        assert os.listdir(str(other)) == []                # nothing written to the other
        w.run(lambda: setattr(images, "_scan_dir", ""))
        w.call("text_scenes.close")


# -- round two: the user's own pictures built earlier, pick gone ------------------------

RECOMMENDED = dict(cp.PRESETS)["recommended"]
BUILT = "images/scene_textures/mine.png"


def _ramp(size=(64, 4)):
    im = PIL.new("RGB", size)
    px = im.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = (x * 4 % 256, x * 2 % 256, 255 - x * 4 % 256)
    return im


def _built_project(tmp_path):
    """A project where a build put the user's picture over Stern's and the pick is gone:
    .orig/ holds Stern's picture, the sidecar still names the user's file."""
    from pinball_decryptor.core.image import detect_image_info
    from pinball_decryptor.core.image_slots import ImageSlot
    proj = tmp_path / "proj"
    f = proj / BUILT
    f.parent.mkdir(parents=True)
    PIL.new("RGB", (64, 4), (10, 200, 30)).save(f)             # Stern's
    d = str(proj)
    assert staged_originals.snapshot(d, BUILT, None)
    _ramp((72, 6)).save(f)                                      # the user's, grown
    data = staged_changes.load(d)
    data["replacement_names"] = {BUILT: "Mine v7.png"}
    staged_changes.save(d, data)
    slot = ImageSlot(rel_path=BUILT, abs_path=str(f), ext=".png",
                     info=detect_image_info(str(f)), size=os.path.getsize(f), probed=True)
    return d, f, slot


def test_a_built_picture_is_not_the_games_own(tmp_path):
    d, _f, _slot = _built_project(tmp_path)
    assert cp.built_image_rels(d) == {BUILT}
    cp.set_asset_slot(d, "images", BUILT, True)
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(d, data)
    assert cp.stock_image_rels(d) == []          # never rebuilt from Stern's .orig/
    assert cp.built_image_on(d) == [BUILT]
    cp.set_asset_slot(d, "images", BUILT, None)
    cp.set_asset_all(d, "images", True)
    assert cp.built_image_on(d) == []            # the tab-wide box never reaches it


def test_staging_corrects_a_built_picture_from_its_own_copy_once(tmp_path):
    from pinball_decryptor.core.image_slots import stage_replacements
    d, f, slot = _built_project(tmp_path)
    cp.set_asset_slot(d, "images", BUILT, True)
    want = RECOMMENDED.apply_image(_ramp((72, 6))).tobytes()
    for _ in range(2):                                  # never corrected twice
        n, fails = stage_replacements({BUILT: slot}, {}, assets_dir=d)
        assert n == 1 and not fails
        got = PIL.open(f)
        assert got.size == (72, 6)                     # its own size, not Stern's
        assert got.convert("RGB").tobytes() == want
    assert PIL.open(cp.uncorrected_path(d, BUILT)).convert("RGB").tobytes() == \
        _ramp((72, 6)).tobytes()
    # off: the user's uncorrected picture goes back (not Stern's)
    assert cp.put_back_uncorrected(d, BUILT)
    assert PIL.open(f).convert("RGB").tobytes() == _ramp((72, 6)).tobytes()
    assert cp.uncorrected_path(d, BUILT) is None
    assert not os.path.isdir(os.path.join(d, cp.UNCORRECTED_DIR))


def test_the_preview_draws_a_built_picture_from_its_own_copy(tmp_path):
    from pinball_decryptor.core.image_slots import stage_replacements
    from pinball_decryptor.plugins.stern import scene_render as R
    d, f, slot = _built_project(tmp_path)
    key = BUILT[len("images/"):]
    assert key not in R.pending_pictures(d)            # off: the project's file as it is
    cp.set_asset_slot(d, "images", BUILT, True)
    pic = R.pending_pictures(d)[key]
    assert pic["built"] and pic["colour"] == RECOMMENDED
    stage_replacements({BUILT: slot}, {}, assets_dir=d)
    pic = R.pending_pictures(d)[key]
    assert pic["path"] == cp.uncorrected_path(d, BUILT)  # after a build: not corrected twice


def test_scenes_gives_a_built_picture_a_switch_and_puts_it_back(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _tv, _wait
    folder, rel = _setup(tmp_path)
    d = str(folder)
    path = os.path.join(d, *rel.split("/"))
    assert staged_originals.snapshot(d, rel, None)
    stern = open(path, "rb").read()
    PIL.new("RGBA", PIL.open(path).size, (90, 20, 200, 255)).save(path)   # the user's
    mine = open(path, "rb").read()
    data = staged_changes.load(d)
    data["replacement_names"] = {rel: "Mine.png"}
    staged_changes.save(d, data)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        nid = _layer_id(w, rel)

        def _layer():
            return next((l for l in _tv(w)["layers"] if l["id"] == nid), {})
        assert _layer()["color"] == {"on": False, "own": True, "rel": rel, "built": True}
        assert w.call("text_scenes.tree_color", nid, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        # a build corrects it; off puts the user's picture back, never Stern's
        assert cp.keep_uncorrected(d, rel)
        PIL.new("RGBA", PIL.open(path).size, (1, 2, 3, 255)).save(path)
        assert w.call("text_scenes.tree_color", nid, False)
        assert open(path, "rb").read() == mine != stern
        # the unlock box never touches it
        assert w.call("text_scenes.tree_color", nid, True)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert w.call("text_scenes.tree_color_unlocked", False)
        assert staged_changes.load(d)[cp.IMAGE_SLOTS_KEY] == {rel: True}
        assert open(path, "rb").read() == mine
        w.call("text_scenes.close")


def test_images_tab_does_not_lock_a_built_picture(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import (_project, _set_folder, _wait, _settled,
                                         _by_rel, PLAIN)
    from pinball_decryptor.core.image_slots import scan_image_slots, stage_replacements
    assets, _reps = _project(tmp_path)
    path = os.path.join(assets, PLAIN)
    assert staged_originals.snapshot(assets, PLAIN, None)
    stern = PIL.open(path).convert("RGB").tobytes()
    im = PIL.open(path).convert("RGB")
    PIL.new("RGB", im.size, (90, 20, 200)).save(path)            # the user's, built
    mine = PIL.open(path).convert("RGB").tobytes()
    data = staged_changes.load(assets)
    data["replacement_names"] = {PLAIN: "Mine.png"}
    staged_changes.save(assets, data)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        st = _wait(w, _settled)
        if not w.run(lambda: w.window.service("images")._per_file_colour()):
            pytest.skip("this manufacturer corrects the files on the display")
        row = _by_rel(st)[PLAIN]
        assert row["cl"] is False and row["c"] is False            # a switch, no lock
        assert w.call("images.set_color", PLAIN, True)
        w.call("images.select", PLAIN)
        assert w.state("images")["preview"]["color"]["built"] is True
        slots = {s.rel_path: s for s in scan_image_slots(assets)}
        n, fails = stage_replacements(slots, {}, assets_dir=assets)
        assert n == 1 and not fails
        assert PIL.open(path).convert("RGB").tobytes() not in (mine, stern)
        # the unlock box never touches it
        assert w.call("images.set_color_unlocked", True)
        assert w.call("images.set_color_unlocked", False)
        assert staged_changes.load(assets)["image_color_slots"] == {PLAIN: True}
        # off: the user's picture comes back, not Stern's
        assert w.call("images.set_color", PLAIN, False)
        w.drain()
        assert PIL.open(path).convert("RGB").tobytes() == mine
        assert _by_rel(w.state("images"))[PLAIN]["c"] is False
