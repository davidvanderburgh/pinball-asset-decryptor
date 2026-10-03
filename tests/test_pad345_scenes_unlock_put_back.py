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
