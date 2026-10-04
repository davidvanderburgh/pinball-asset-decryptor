"""PAD-344: the Scenes Layers list gets the advanced "Unlock the game's own pictures"
box (the Images tab's PAD-335 setting), so a game picture's blue lock turns into a
red / green colour switch there too, and the preview draws a switched-on one corrected."""

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")

#: the individual files profile a project starts with: the Recommended screen,
#: undone (PAD-346)
RECOMMENDED = cp.undo_screen(cp.SCREEN_PRESETS[0][1])


def _ramp():
    im = PIL.new("RGBA", (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            v = x * 4
            px[x, y] = (v, v // 2, 255 - v, 255)
    return im


def test_the_preview_draws_an_unlocked_game_picture_from_its_original(tmp_path):
    from pinball_decryptor.core import staged_originals
    from pinball_decryptor.plugins.stern import scene_render as R
    proj = tmp_path / "proj"
    (proj / "images" / "scene_textures").mkdir(parents=True)
    rel = "scene_textures/stock.png"
    f = proj / "images" / rel
    _ramp().save(str(f))
    d = str(proj)
    cp.set_asset_slot(d, "images", "images/" + rel, True)
    assert rel not in R.pending_pictures(d)                # locked: drawn as it is
    data = staged_changes.load(d)
    data[cp.STOCK_IMAGES_KEY] = True
    staged_changes.save(d, data)
    pics = R.pending_pictures(d)
    assert pics[rel]["colour"] == RECOMMENDED and pics[rel]["stock"]
    want = RECOMMENDED.apply_image(_ramp()).convert("RGB").tobytes()
    assert R._picture(d, rel, {}, pics, {}).convert("RGB").tobytes() == want
    # a build already corrected the project's file: the preview starts from the snapshot
    staged_originals.snapshot(d, "images/" + rel, None)
    RECOMMENDED.apply_image(_ramp()).save(str(f))
    pics = R.pending_pictures(d)
    assert R._picture(d, rel, {}, pics, {}).convert("RGB").tobytes() == want
    assert R.pending_pictures(d, bake=False)[rel]["colour"] is None


def test_scenes_layers_unlock_the_game_pictures(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open, _tv, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    art = next(o for o in man["objects"].values()
               if o.get("kind") == "Bitmap" and o.get("image"))
    rel = "images/" + art["image"]
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        nid = next(l["id"] for l in _tv(w)["layers"]
                   if l["kind"] == "Bitmap" and l["pics"] == [rel])

        def _layer():
            return next((l for l in _tv(w)["layers"] if l["id"] == nid), {})
        assert _layer()["color"] == {"locked": True}
        assert _tv(w)["color_unlock"] == {"offered": True, "on": False}
        assert not w.call("text_scenes.tree_color", nid, True)   # a lock has no switch
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert staged_changes.load(str(folder))[cp.STOCK_IMAGES_KEY] is True
        assert _wait(w, lambda: _layer().get("color") == {
            "on": False, "own": True, "rel": rel, "stock": True})
        assert _tv(w)["color_unlock"]["on"] is True
        assert w.call("text_scenes.tree_color", nid, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        assert staged_changes.load(str(folder))[cp.IMAGE_SLOTS_KEY] == {rel: True}
        assert cp.stock_image_rels(str(folder)) == [rel]
        # red again is no switch at all; the Every replaced picture box never reaches it
        assert w.call("text_scenes.tree_color", nid, False)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is False)
        assert not staged_changes.load(str(folder)).get(cp.IMAGE_SLOTS_KEY)
        assert w.call("text_scenes.tree_color", nid, True)
        assert _wait(w, lambda: (_layer().get("color") or {}).get("on") is True)
        # locked again: the switches go and the blue lock is back
        assert w.call("text_scenes.tree_color_unlocked", False)
        assert _wait(w, lambda: _layer().get("color") == {"locked": True})
        data = staged_changes.load(str(folder))
        assert not data.get(cp.STOCK_IMAGES_KEY) and not data.get(cp.IMAGE_SLOTS_KEY)
        w.call("text_scenes.close")


def test_scenes_unlock_is_offered_on_a_scene_with_no_pictures(tmp_path):
    """PAD-349 (DragonRR): the box sits beside Preview colors now, on every scene, so
    it no longer vanishes on a scene that draws no extracted image."""
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open, _tv
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    for png in (folder / "images" / "scene_textures").glob("*.png"):
        png.unlink()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert not any(l["color"] for l in _tv(w)["layers"])
        assert _tv(w)["color_unlock"] == {"offered": True, "on": False}
        w.call("text_scenes.close")
