"""PAD-325: with As on the machine ticked, a picture whose colour switch is
off (red in the Layers list) passes the machine screen by and shows its own
colours, so it can be seen against the game's own art; the gear menu's
"Scenes: switched-off files in their own colors" turns that off."""

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

ID = (1.0, 0.0, 0.0, 1.0)


def _draw(rel, x, alpha=1.0):
    return {"kind": "bitmap", "image": rel, "mul": (1.0, 1.0, 1.0, alpha),
            "add": (0, 0, 0, 0), "m": ID + (float(x), 0.0)}


def _grey(rgb):
    """A black-and-white screen."""
    g = (rgb.astype(np.float32) @ np.asarray([0.299, 0.587, 0.114], np.float32))
    return np.repeat(np.clip(g + 0.5, 0, 255).astype(np.uint8)[..., None], 3, axis=-1)


def _project(tmp_path):
    proj = tmp_path / "proj"
    tex = proj / "images" / "scene_textures"
    tex.mkdir(parents=True)
    PIL.new("RGBA", (8, 8), (0, 0, 0, 255)).save(str(tex / "mine.png"))
    PIL.new("RGBA", (8, 8), (40, 200, 40, 255)).save(str(tex / "stock.png"))
    red = tmp_path / "red.png"
    PIL.new("RGBA", (8, 8), (220, 30, 30, 255)).save(str(red))
    staged_changes.save(str(proj), {"image": {"images/scene_textures/mine.png": str(red)}})
    return str(proj)


def _render(proj, draws, as_made, split=None):
    from pinball_decryptor.plugins.stern import scene_render as R
    return R.render_tree(proj, {"stage": [16, 8, 30]}, draws=draws,
                         pictures=R.pending_pictures(proj), sizes={}, view=_grey,
                         as_made=as_made, split=split)


def test_a_switched_off_pick_is_marked_and_a_switched_on_one_is_not(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as R
    proj = _project(tmp_path)
    assert R.pending_pictures(proj)["scene_textures/mine.png"]["skip"] is True
    cp.set_asset_all(proj, "images", True)
    assert R.pending_pictures(proj)["scene_textures/mine.png"]["skip"] is False
    data = staged_changes.load(proj)
    data[cp.IMAGE_SLOTS_KEY] = {"images/scene_textures/mine.png": False}
    staged_changes.save(proj, data)
    assert R.pending_pictures(proj)["scene_textures/mine.png"]["skip"] is True


def test_a_switched_off_pick_keeps_its_colours_and_stock_art_is_viewed(tmp_path):
    proj = _project(tmp_path)
    draws = [_draw("scene_textures/stock.png", 0), _draw("scene_textures/mine.png", 8)]
    img = np.asarray(_render(proj, draws, as_made=True))
    assert tuple(img[4, 2]) == tuple(_grey(np.asarray([[[40, 200, 40]]], np.uint8))[0, 0])
    assert tuple(img[4, 12]) == (220, 30, 30)                 # red: its own colours
    # the setting off: every picture through the screen, as before
    img = np.asarray(_render(proj, draws, as_made=False))
    assert img[4, 12, 0] == img[4, 12, 1] == img[4, 12, 2]


def test_what_covers_a_skipped_pick_still_covers_it(tmp_path):
    proj = _project(tmp_path)
    draws = [_draw("scene_textures/mine.png", 0), _draw("scene_textures/stock.png", 0, 0.5)]
    img = np.asarray(_render(proj, draws, as_made=True)).astype(int)
    # half the red, kept as it is, and half the green, viewed grey
    g = int(_grey(np.asarray([[[40, 200, 40]]], np.uint8))[0, 0, 0])
    want = (110 + g // 2, 15 + g // 2, 15 + g // 2)
    assert np.abs(img[4, 2] - np.asarray(want)).max() <= 2
    # fully covered by a stock picture: nothing of it shows
    draws = [_draw("scene_textures/mine.png", 0), _draw("scene_textures/stock.png", 0)]
    img = np.asarray(_render(proj, draws, as_made=True))
    assert img[4, 2, 0] == img[4, 2, 1] == img[4, 2, 2]


def test_nothing_skipped_draws_exactly_as_before(tmp_path):
    proj = _project(tmp_path)
    cp.set_asset_all(proj, "images", True)
    draws = [_draw("scene_textures/stock.png", 0), _draw("scene_textures/mine.png", 8)]
    a = np.asarray(_render(proj, draws, as_made=True))
    b = np.asarray(_render(proj, draws, as_made=False))
    assert a.tobytes() == b.tobytes()


def test_the_editors_layers_keep_it_too(tmp_path):
    proj = _project(tmp_path)
    draws = [_draw("scene_textures/stock.png", 0), _draw("scene_textures/mine.png", 8)]
    got = _render(proj, draws, as_made=True, split={1})
    assert tuple(np.asarray(got["full"])[4, 12]) == (220, 30, 30)
    sel = np.asarray(got["sel"])
    assert tuple(sel[4, 12]) == (220, 30, 30, 255) and sel[4, 2, 3] == 0
    under = np.asarray(got["under"])
    assert under[4, 2, 0] == under[4, 2, 1] == under[4, 2, 2]


def test_the_gear_menu_turns_it_off_and_on_and_scenes_follows(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="stern") as w:
        items = w.state("shell")["settings_items"]
        it = next(i for i in items if i.get("id") == "toggle_scenes_own_colours")
        assert it["checked"] is True
        svc = w.window.service("text").scenes
        assert w.run(svc._as_made) is True
        w.call("ui.settings_action", "toggle_scenes_own_colours")
        w.drain()
        it = next(i for i in w.state("shell")["settings_items"]
                  if i.get("id") == "toggle_scenes_own_colours")
        assert it["checked"] is False
        assert w.run(svc._as_made) is False
        w.call("ui.settings_action", "toggle_scenes_own_colours")
        w.drain()
        assert w.run(svc._as_made) is True
