"""PAD-335: the Images tab's Color column is on every row, a blue lock on the
game's own pictures like Video and Scenes, and an advanced "Unlock the game's
own pictures" box gives those a switch of their own, baked in from their
pristine bytes as they are staged."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")

#: the individual files profile a project starts with: the Recommended screen,
#: undone (PAD-346)
RECOMMENDED = cp.undo_screen(cp.SCREEN_PRESETS[0][1])


def _ramp():
    im = PIL.new("RGB", (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            v = x * 4
            px[x, y] = (v, v // 2, 255 - v)
    return im


def _slot(proj, name):
    from pinball_decryptor.core.image import detect_image_info
    from pinball_decryptor.core.image_slots import ImageSlot
    f = proj / name
    _ramp().save(f)
    return f, ImageSlot(rel_path=name, abs_path=str(f), ext=".png",
                        info=detect_image_info(str(f)),
                        size=os.path.getsize(f), probed=True)


def test_only_an_unlocked_game_pictures_own_switch_counts(tmp_path):
    d = str(tmp_path)
    cp.set_asset_all(d, "images", True)
    cp.set_asset_slot(d, "images", "stock.png", True)
    cp.set_asset_slot(d, "images", "off.png", False)
    assert cp.stock_image_rels(d) == []                # locked
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(d, data)
    assert cp.stock_image_rels(d) == ["stock.png"]     # the box never reaches it
    assert cp.stock_image_rels(d, {"stock.png"}) == []  # a replaced one is not stock
    assert cp.asset_counts(d)["images"] == 1
    assert cp.asset_signature(d).endswith("|unlocked")


def test_staging_corrects_an_unlocked_game_picture_once(tmp_path):
    from pinball_decryptor.core import staged_originals
    from pinball_decryptor.core.image_slots import stage_replacements
    proj = tmp_path / "proj"
    proj.mkdir()
    f, slot = _slot(proj, "stock.png")
    cp.set_asset_slot(str(proj), "images", "stock.png", True)
    # locked: nothing happens to the game's own picture
    n, fails = stage_replacements({"stock.png": slot}, {}, assets_dir=str(proj))
    assert (n, fails) == (0, [])
    assert PIL.open(f).convert("RGB").tobytes() == _ramp().tobytes()
    data = staged_changes.load(str(proj))
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(str(proj), data)
    want = RECOMMENDED.apply_image(_ramp()).tobytes()
    for _ in range(2):                                  # never corrected twice
        n, fails = stage_replacements({"stock.png": slot}, {},
                                      assets_dir=str(proj))
        assert n == 1 and not fails
        assert PIL.open(f).convert("RGB").tobytes() == want
    snap = staged_originals.snapshot_path(str(proj), "stock.png")
    assert PIL.open(snap).convert("RGB").tobytes() == _ramp().tobytes()


def test_images_tab_locks_game_pictures_and_the_advanced_box_unlocks_them(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import (_project, _set_folder, _wait, _settled,
                                         _by_rel, PLAIN)
    from pinball_decryptor.core.image_slots import scan_image_slots, stage_replacements
    assets, _reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        st = _wait(w, _settled)
        if not w.run(lambda: w.window.service("images")._per_file_colour()):
            pytest.skip("this manufacturer corrects the files on the display")
        assert st["cols"]["color"] is True
        assert st["color_unlock"] == {"offered": True, "on": False}
        row = _by_rel(st)[PLAIN]
        assert row["cl"] is True and row["c"] is None
        assert w.call("images.set_color", PLAIN, True) is False
        # unlocked: a red switch, its own only
        assert w.call("images.set_color_unlocked", True)
        st = w.state("images")
        assert st["color_unlock"]["on"] is True
        assert staged_changes.load(assets)[cp.STOCK_IMAGES_KEY] is True
        row = _by_rel(st)[PLAIN]
        assert row["cl"] is False and row["c"] is False and row["cg"] is True
        assert w.call("images.set_color", PLAIN, True)
        assert _by_rel(w.state("images"))[PLAIN]["c"] is True
        assert staged_changes.load(assets)["image_color_slots"] == {PLAIN: True}
        w.call("images.select", PLAIN)
        assert w.state("images")["preview"]["color"]["stock"] is True
        labels = [i.get("label") for i in w.call("images.menu", PLAIN, [PLAIN])]
        assert "Keep its own colors" in labels
        assert "Colors: follow the Color profile tab's box again" not in labels
        # a build stages it from its original
        slots = {s.rel_path: s for s in scan_image_slots(assets)}
        before = PIL.open(os.path.join(assets, PLAIN)).convert("RGB").tobytes()
        n, fails = stage_replacements(slots, {}, assets_dir=assets)
        assert n == 1 and not fails
        assert PIL.open(os.path.join(assets, PLAIN)).convert("RGB").tobytes() != before
        # locked again: the switch goes and the original is back
        assert w.call("images.set_color_unlocked", False)
        w.drain()
        data = staged_changes.load(assets)
        assert cp.STOCK_IMAGES_KEY not in data
        assert "image_color_slots" not in data
        assert PIL.open(os.path.join(assets, PLAIN)).convert("RGB").tobytes() == before
        assert _by_rel(w.state("images"))[PLAIN]["cl"] is True
