"""PAD-312: a second colour profile for CHOSEN FILES, baked into the replaced
pictures and videos (and pictures added in Scenes) that are switched on, next
to the display-wide one (core/colour_profile.py ``asset_*``), its switches on
the Images, Video and Scenes layers, and the Color profile tab's two modes."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

RECOMMENDED = dict(cp.PRESETS)["recommended"]
BW = dict(cp.PRESETS)["bw"]


def _ramp(mode="RGB"):
    im = PIL.new(mode, (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            v = x * 4
            px[x, y] = ((v, v // 2, 255 - v, 255) if mode == "RGBA"
                        else (v, v // 2, 255 - v))
    return im


def _image_slot(tmp_path, name):
    from pinball_decryptor.core.image_slots import ImageSlot
    from pinball_decryptor.core.image import detect_image_info
    slot_file = tmp_path / name
    PIL.new("RGB", (64, 4), (0, 0, 0)).save(slot_file)
    return slot_file, ImageSlot(rel_path=name, abs_path=str(slot_file),
                                ext=".png",
                                info=detect_image_info(str(slot_file)),
                                size=os.path.getsize(slot_file), probed=True)


# -- the model -----------------------------------------------------------------

def test_the_chosen_files_profile_starts_from_recommended_and_nothing_is_on(tmp_path):
    d = str(tmp_path)
    assert cp.asset_profile(d) == RECOMMENDED
    assert cp.asset_stored(d) is False
    assert cp.asset_active(d) == RECOMMENDED
    assert cp.asset_settings(d) == {"all_images": False, "all_videos": False,
                                    "images": {}, "videos": {}}
    assert cp.asset_map(d, "images", ["a.png"]) == {}
    # the default profile changes something, so it has a signature even
    # with no switch on; a switch moving is a change the Write tab sees
    sig = cp.asset_signature(d)
    assert sig
    cp.set_asset_all(d, "images", True)
    assert cp.asset_signature(d) != sig
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.asset_signature(d) == ""


def test_switches_a_box_per_kind_and_a_files_own_switch_wins(tmp_path):
    d = str(tmp_path)
    cp.set_asset_all(d, "images", True)
    cp.set_asset_slot(d, "images", "b.png", False)
    cp.set_asset_slot(d, "videos", "v.mp4", True)
    st = cp.asset_settings(d)
    assert st["all_images"] and not st["all_videos"]
    assert cp.asset_applies(st, "images", "a.png")          # follows the box
    assert not cp.asset_applies(st, "images", "b.png")      # its own switch
    assert cp.asset_applies(st, "videos", "v.mp4")
    assert not cp.asset_applies(st, "videos", "w.mp4")
    assert cp.asset_map(d, "images", ["a.png", "b.png"]) == {"a.png": RECOMMENDED}
    assert cp.asset_map(d, "videos", ["v.mp4", "w.mp4"]) == {"v.mp4": RECOMMENDED}
    # back to the box
    cp.set_asset_slot(d, "images", "b.png", None)
    assert cp.asset_applies(cp.asset_settings(d), "images", "b.png")
    assert cp.IMAGE_SLOTS_KEY not in staged_changes.load(d)
    # the profile itself: stored as set, No change included
    cp.store_asset_profile(d, BW)
    assert cp.asset_profile(d) == BW and cp.asset_stored(d)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.asset_active(d) is None and cp.asset_map(d, "images", ["a.png"]) == {}
    with pytest.raises(ValueError):
        cp.set_asset_all(d, "audio", True)


def test_counts_name_what_the_profile_reaches(tmp_path):
    d = str(tmp_path)
    data = {"image": {"images/a.png": "x", "images/b.png": "y"},
            "video": {"v.mp4": "z"}}
    staged_changes.save(d, data)
    assert cp.asset_counts(d) == {"images": 0, "videos": 0, "added": 0}
    cp.set_asset_all(d, "images", True)
    cp.set_asset_slot(d, "videos", "v.mp4", True)
    cp.set_asset_slot(d, "images", "images/b.png", False)
    assert cp.asset_counts(d) == {"images": 1, "videos": 1, "added": 0}
    from pinball_decryptor.plugins.stern import scene_edit
    scene_edit.add(d, "/g/s/scene.radium", {
        "op": "add_picture", "parent": 1, "id": 900, "name": "PAD_x",
        "image": "scene_textures/added/x_1.png", "w": 4, "h": 4, "x": 0, "y": 0})
    scene_edit.add(d, "/g/s/scene.radium", {
        "op": "add_picture", "parent": 1, "id": 901, "name": "PAD_y", "color": False,
        "image": "scene_textures/added/y_1.png", "w": 4, "h": 4, "x": 0, "y": 0})
    assert cp.asset_counts(d)["added"] == 1       # x follows the box, y is off
    assert scene_edit.describe({"op": "add_picture", "image": "a/b.png", "color": True}) \
        == "added picture b.png (colors corrected)"


# -- staging -----------------------------------------------------------------

def test_image_staging_bakes_the_profile_into_switched_on_pictures_only(tmp_path):
    """Spike 2: the display-wide profile is held off at staging (the shaders
    carry it), and the chosen-files profile reaches exactly the pictures
    that are on - fresh from the user's file each build, never twice."""
    from pinball_decryptor.core.image_slots import stage_replacements
    proj = tmp_path / "proj"
    proj.mkdir()
    on_file, on_slot = _image_slot(proj, "on.png")
    off_file, off_slot = _image_slot(proj, "off.png")
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    cp.store(str(proj), RECOMMENDED)                   # display-wide, held off
    cp.set_asset_all(str(proj), "images", True)
    cp.set_asset_slot(str(proj), "images", "off.png", False)
    want = RECOMMENDED.apply_image(_ramp()).tobytes()
    for _ in range(2):
        with cp.forced(False):
            n, fails = stage_replacements(
                {"on.png": on_slot, "off.png": off_slot},
                {"on.png": str(rep), "off.png": str(rep)}, assets_dir=str(proj))
        assert n == 2 and not fails
        assert PIL.open(on_file).convert("RGB").tobytes() == want
        assert PIL.open(off_file).convert("RGB").tobytes() == _ramp().tobytes()
    assert PIL.open(rep).convert("RGB").tobytes() == _ramp().tobytes()
    # No change on the chosen files: the switch is on, nothing is baked
    cp.store_asset_profile(str(proj), cp.Profile(name="No change"))
    with cp.forced(False):
        stage_replacements({"on.png": on_slot}, {"on.png": str(rep)},
                           assets_dir=str(proj))
    assert PIL.open(on_file).convert("RGB").tobytes() == _ramp().tobytes()


def test_where_the_display_profile_corrects_the_files_it_wins(tmp_path):
    """Off Spike 2 the display-wide profile IS a file correction of every
    replacement; a chosen-files switch does not add a second one."""
    from pinball_decryptor.core.image_slots import stage_replacements
    proj = tmp_path / "proj"
    proj.mkdir()
    slot_file, slot = _image_slot(proj, "a.png")
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    cp.store(str(proj), BW)
    cp.store_asset_profile(str(proj), RECOMMENDED)
    cp.set_asset_all(str(proj), "images", True)
    stage_replacements({"a.png": slot}, {"a.png": str(rep)}, assets_dir=str(proj))
    assert PIL.open(slot_file).convert("RGB").tobytes() == \
        BW.apply_image(_ramp()).tobytes()


def test_video_staging_hands_the_profile_to_the_clips_that_are_on(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots
    proj = tmp_path / "proj"
    proj.mkdir()
    seen = {}

    def fake_stage(slot, rep, **kw):
        seen[slot.rel_path] = kw.get("colour")
        with open(slot.abs_path, "wb") as f:
            f.write(b"x")
        return True, "ok"

    monkeypatch.setattr(video_slots, "stage_replacement", fake_stage)
    monkeypatch.setattr(video_slots, "_clip_bitrate", lambda p: None)
    monkeypatch.setattr(video_slots, "_slot_keyint", lambda p: 0)
    slots = {}
    for name in ("on.mp4", "off.mp4"):
        f = proj / name
        f.write_bytes(b"old")
        slots[name] = video_slots.VideoSlot(
            rel_path=name, abs_path=str(f), ext=".mp4", info=None, size=3,
            probed=False)
    rep = tmp_path / "mine.mp4"
    rep.write_bytes(b"new")
    cp.set_asset_slot(str(proj), "videos", "on.mp4", True)
    with cp.forced(False):
        n, fails = video_slots.stage_replacements(
            slots, {"on.mp4": str(rep), "off.mp4": str(rep)},
            assets_dir=str(proj))
    assert n == 2 and not fails
    assert seen == {"on.mp4": RECOMMENDED, "off.mp4": None}
    # the converted-clip cache names the profile: a switch moving re-converts
    cache = video_slots.StagedCache(str(proj))
    r_on = cache.recipe(slots["on.mp4"], str(rep), None, colour="x")
    r_off = cache.recipe(slots["on.mp4"], str(rep), None)
    assert r_on != r_off


def test_a_picture_added_in_scenes_is_baked_when_its_switch_is_on(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit
    p = tmp_path / "pic.png"
    _ramp("RGBA").save(p)
    plain = scene_edit._texture_from_png(str(p))
    baked = scene_edit._texture_from_png(str(p), colour=RECOMMENDED)
    assert plain[:3] == baked[:3] and plain[3] != baked[3]
    d = str(tmp_path)
    op = {"op": "add_picture", "image": "scene_textures/added/pic_1.png"}
    assert cp.added_picture_colour(d, op) is None              # box off
    cp.set_asset_all(d, "images", True)
    assert cp.added_picture_colour(d, op) == RECOMMENDED
    assert cp.added_picture_colour(d, dict(op, color=False)) is None
    cp.set_asset_all(d, "images", False)
    assert cp.added_picture_colour(d, dict(op, color=True)) == RECOMMENDED


def test_the_scene_preview_draws_a_switched_on_pick_the_way_it_is_written(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as R
    proj = tmp_path / "proj"
    (proj / "images" / "scene_textures" / "added").mkdir(parents=True)
    rel = "scene_textures/pic.png"
    PIL.new("RGBA", (64, 4), (0, 0, 0, 255)).save(str(proj / "images" / rel))
    mine = tmp_path / "mine.png"
    _ramp("RGBA").convert("RGBA").save(mine)
    # opaque, so premultiplying changes nothing and the correction is all
    opaque = _ramp("RGBA")
    opaque.putalpha(255)
    opaque.save(mine)
    staged_changes.save(str(proj), {"image": {"images/" + rel: str(mine)}})
    pics = R.pending_pictures(str(proj))
    assert pics[rel]["colour"] is None
    got = R._picture(str(proj), rel, {}, pics, {})
    assert got.convert("RGB").tobytes() == opaque.convert("RGB").tobytes()
    cp.set_asset_all(str(proj), "images", True)
    pics = R.pending_pictures(str(proj))
    assert pics[rel]["colour"] == RECOMMENDED
    got = R._picture(str(proj), rel, {}, pics, {})
    assert got.convert("RGB").tobytes() == \
        RECOMMENDED.apply_image(opaque).convert("RGB").tobytes()
    # a picture added in Scenes, switched on by the box, is listed for its colour
    added = "scene_textures/added/x_1.png"
    opaque.save(str(proj / "images" / added))
    from pinball_decryptor.plugins.stern import scene_edit
    scene_edit.add(str(proj), "/g/s/scene.radium", {
        "op": "add_picture", "parent": 1, "id": 900, "name": "PAD_x", "image": added,
        "w": 64, "h": 4, "x": 0, "y": 0})
    pics = R.pending_pictures(str(proj))
    assert pics[added]["colour"] == RECOMMENDED and pics[added]["keep"] is True
    got = R._picture(str(proj), added, {}, pics, {})
    assert got.convert("RGB").tobytes() == \
        RECOMMENDED.apply_image(opaque).convert("RGB").tobytes()


# -- the Write tab ---------------------------------------------------------------

def test_write_lists_the_chosen_files_as_pending_and_its_fingerprint_moves(tmp_path):
    from pinball_decryptor.webui import write_scan
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    proj = tmp_path / "proj"
    proj.mkdir()
    mfr = SternManufacturer()
    staged_changes.save(str(proj), {"image": {"images/a.png": "x", "images/b.png": "y"},
                                    "video": {"v.mp4": "z"}})
    assert write_scan.chosen_files_rows(mfr, str(proj)) == []
    before = write_scan.fingerprint(None, str(proj), 0, True)
    cp.set_asset_all(str(proj), "images", True)
    cp.set_asset_slot(str(proj), "videos", "v.mp4", True)
    assert write_scan.fingerprint(None, str(proj), 0, True) != before
    assert write_scan.chosen_files_rows(mfr, str(proj)) == [(
        "color profile on individual files  —  Recommended, baked into 2 replaced "
        "pictures, 1 replaced video", "color", "Pending (color profile)",
        "pending")]
    cp.store_asset_profile(str(proj), cp.Profile(name="No change"))
    assert write_scan.chosen_files_rows(mfr, str(proj)) == []


# -- the Color profile tab -----------------------------------------------------

def test_color_tab_has_a_chosen_files_mode_with_its_own_profile_and_boxes(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    staged_changes.save(str(proj), {"image": {"images/a.png": "x"}})
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        s = w.state("color")
        assert s["per_file"] is True and s["mode"] == "display"
        assert s["active"] is False and s["name"] == "No change"
        rev = s["rev"]
        assert w.call("color.set_mode", "assets") == "assets"
        w.drain()
        s = w.state("color")
        assert s["mode"] == "assets" and s["rev"] > rev
        assert s["name"] == "Recommended" and s["gamma"] == [1.1, 1.2, 1.35]
        assert s["asset_active"] is True and s["active"] is False
        assert s["asset_counts"] == {"images": 0, "videos": 0, "added": 0}
        assert w.call("color.set_all", "images", True)
        w.drain()
        s = w.state("color")
        assert s["all_images"] is True and s["asset_counts"]["images"] == 1
        assert s["active"] is True
        assert cp.asset_settings(str(proj))["all_images"] is True
        # the sliders move the chosen-files profile, not the whole-screen one
        w.call("color.set_params", {"gamma": [1.5, 1.0, 1.0]})
        w.drain()
        assert cp.asset_profile(str(proj)).gamma == (1.5, 1.0, 1.0)
        assert cp.for_project(str(proj)) is None
        w.call("color.preset", "none")
        w.drain()
        s = w.state("color")
        assert s["asset_active"] is False and s["active"] is False
        assert cp.asset_profile(str(proj)).is_identity()
        assert w.call("color.set_mode", "display") == "display"
        w.drain()
        s = w.state("color")
        assert s["name"] == "No change" and s["active"] is False
        w.call("color.preset", "bw")
        w.drain()
        assert cp.for_project(str(proj)) == BW
        assert cp.asset_profile(str(proj)).is_identity()      # untouched
        # Revert all takes both profiles and the boxes away
        w.window.clear_replace_assignments(str(proj))
        w.drain()
        assert cp.for_project(str(proj)) is None
        assert cp.asset_stored(str(proj)) is False
        assert cp.asset_settings(str(proj))["all_images"] is False


def test_the_mode_is_not_offered_where_the_display_profile_corrects_the_files(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        s = w.state("color")
        assert s["per_file"] is False
        assert w.call("color.set_mode", "assets") == "display"


# -- the Images tab and the Scenes layers -----------------------------------------

def test_images_tab_offers_a_color_box_per_replaced_picture(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import (_project, _set_folder, _wait, _settled,
                                         _by_rel, BANNER, PLAIN)
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        st = _wait(w, _settled)
        assert st["cols"]["color"] is True           # locks on the game's own (PAD-335)
        assert _by_rel(st)[BANNER]["cl"] is True
        rep = os.path.join(reps, "SpaceGodzilla.png")
        w.answers = [rep]
        assert w.call("images.choose", BANNER) == BANNER
        st = w.state("images")
        assert st["cols"]["color"] is True
        row = _by_rel(st)[BANNER]
        assert row["c"] is False and row["co"] is False
        assert _by_rel(st)[PLAIN]["c"] is None       # the game's own picture
        assert _by_rel(st)[PLAIN]["cl"] is True and row["cl"] is False
        w.call("images.select", BANNER)
        p = w.state("images")["preview"]
        assert p["color"] == {"on": False, "own": False, "all": False,
                              "name": "Recommended", "stock": False}
        assert w.call("images.set_color", BANNER, True)
        row = _by_rel(w.state("images"))[BANNER]
        assert row["c"] is True and row["co"] is True
        assert w.state("images")["preview"]["color"]["on"] is True
        assert staged_changes.load(assets)["image_color_slots"] == {BANNER: True}
        labels = [i.get("label") for i in w.call("images.menu", BANNER, [BANNER])]
        assert "Keep its own colors" in labels
        assert "Colors: follow the Color profile tab's box again" in labels
        # the Color profile tab counts it
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.state("color")["asset_counts"]["images"] == 1
        # back to the box, and the box reaches it
        assert w.call("images.act", "color_box", BANNER, [BANNER])
        assert "image_color_slots" not in staged_changes.load(assets)
        assert _by_rel(w.state("images"))[BANNER]["c"] is False
        assert w.call("color.set_all", "images", True)
        w.drain()
        assert _by_rel(w.state("images"))[BANNER]["c"] is True
        assert w.state("images")["preview"]["color"]["all"] is True
        # a settings file carries the switch (PAD-300)
        from pinball_decryptor.core import tab_settings
        assert "image_color_slots" in tab_settings.SECTIONS["images"]
        assert "color_all_images" in tab_settings.SECTIONS["images"]
        # the game's own picture has no switch
        assert w.call("images.set_color", PLAIN, True) is False
        # clearing the pick drops its switch
        assert w.call("images.set_color", BANNER, False)
        w.call("images.clear_one", BANNER)
        w.drain()
        assert "image_color_slots" not in staged_changes.load(assets)


def test_scene_layers_carry_a_colour_switch_for_pictures(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open, _tv, _wait, CARD
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    art = next(o for o in man["objects"].values()
               if o.get("kind") == "Bitmap" and o.get("image"))
    rel = "images/" + art["image"]
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        pics = [l for l in _tv(w)["layers"]
                if l["kind"] == "Bitmap" and l["pics"] == [rel]]
        assert pics and pics[0]["color"] == {"locked": True}   # Stern's own picture
        assert not any(l["color"] for l in _tv(w)["layers"] if l["kind"] == "Text")
        nid = pics[0]["id"]
        # a replacement picked on the Images tab unlocks it
        mine = tmp_path / "mine.png"
        PIL.new("RGBA", (8, 8), (20, 220, 40, 255)).save(str(mine))
        data = staged_changes.load(str(folder))
        data["image"] = {rel: str(mine)}
        staged_changes.save(str(folder), data)
        w.run(svc.pictures_changed)

        def _layer():
            return next((l for l in _tv(w)["layers"] if l["id"] == nid), {})
        assert _wait(w, lambda: _layer().get("color") == {"on": False, "own": False,
                                                           "rel": rel})
        assert w.call("text_scenes.tree_color", nid, True)
        assert _wait(w, lambda: _layer().get("color") == {"on": True, "own": True,
                                                           "rel": rel})
        assert staged_changes.load(str(folder))["image_color_slots"] == {rel: True}
        # a picture added in Scenes has its own switch, kept in its edit
        added_src = tmp_path / "added.png"
        PIL.new("RGBA", (6, 6), (200, 200, 20, 255)).save(str(added_src))
        w.answers = [str(added_src)]
        assert w.call("text_scenes.tree_add_picture")
        assert _wait(w, lambda: any(l["added"] for l in _tv(w)["layers"]))
        added = next(l for l in _tv(w)["layers"] if l["added"])
        assert added["color"] == {"on": False, "own": False, "added": True}
        assert w.call("text_scenes.tree_color", added["id"], True)
        assert _wait(w, lambda: next((l for l in _tv(w)["layers"] if l["added"]),
                                     {}).get("color") == {"on": True, "own": True,
                                                          "added": True})
        op = next(o for o in scene_edit.ops_for(str(folder), CARD)
                  if o["op"] == "add_picture")
        assert op["color"] is True
        assert "colors corrected" in next(
            l for l in _tv(w)["layers"] if l["added"])["edits"]
        w.call("text_scenes.close")


# -- round two (DragonRR on v1.65.0): the machine's look, and the Scenes refresh -----------

def test_the_machine_view_undoes_the_profile_and_the_overlay_cancels_it():
    rgb = np.zeros((1, 256, 3), np.uint8)
    rgb[0, :, 0] = np.arange(256)
    rgb[0, :, 1] = np.arange(256)[::-1]
    rgb[0, :, 2] = (np.arange(256) * 3) % 256
    corrected = RECOMMENDED.apply_array(rgb)
    assert corrected.tobytes() == np.asarray(
        RECOMMENDED.apply_image(PIL.fromarray(rgb, "RGB"))).tobytes()
    back = RECOMMENDED.undo_array(corrected)
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 3
    # the screen alone brightens the mids; a Black and white profile is not undone
    screen = RECOMMENDED.undo_array(rgb)
    assert screen[0, 128, 2] > 128
    assert BW.undo_array(rgb).tobytes() == rgb.tobytes()


def test_machine_view_follows_both_profiles(tmp_path):
    d = str(tmp_path)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.machine_view(d) is None                 # nothing to show
    cp.store_asset_profile(d, None)                   # Recommended again
    rgb = np.full((2, 2, 3), 128, np.uint8)
    view = cp.machine_view(d)
    assert view(rgb)[0, 0, 2] > 128                   # the screen, bluer and brighter
    cp.store(d, RECOMMENDED)                          # the overlay corrects for that screen
    view = cp.machine_view(d)
    assert np.abs(view(rgb).astype(int) - 128).max() <= 3


def test_the_scene_frame_is_viewed_before_the_backdrop(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as R
    canvas = np.zeros((2, 2, 4), np.uint8)
    canvas[0, 0] = (128, 128, 128, 255)               # opaque mid grey
    canvas[0, 1] = (64, 64, 64, 128)                  # half-covered mid grey, premultiplied
    seen = R.viewed(canvas, lambda rgb: np.clip(rgb.astype(int) * 2, 0, 255).astype(np.uint8))
    assert tuple(seen[0, 0]) == (255, 255, 255, 255)
    assert tuple(seen[0, 1, :3]) == (128, 128, 128) and seen[0, 1, 3] == 128
    assert R.viewed(canvas, None) is canvas


def test_scenes_editor_draws_as_on_the_machine_and_can_be_told_not_to(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        assert w.state("text_scenes")["machine_look"] is True
        assert w.run(svc._machine_view) is not None   # Recommended by default
        rev = w.state("text_scenes")["tree_img_rev"]
        assert w.call("text_scenes.set_machine_look", False)
        assert w.state("text_scenes")["machine_look"] is False
        assert w.run(svc._machine_view) is None
        assert _wait(w, lambda: w.state("text_scenes")["tree_img_rev"] != rev
                     or w.state("text_scenes")["tree_busy"] is False)
        w.call("text_scenes.close")


def test_a_switch_moved_on_the_images_tab_reaches_the_scenes_editor(tmp_path):
    """DragonRR on v1.65.0: in Scenes the palette and the picture only changed after a
    tab switch - the Images tab's hook looked the editor up under a name the window
    never registers.  It goes through the Text tab now."""
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, BANNER
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        calls = []
        scenes = w.window.service("text").scenes
        scenes.pictures_changed = lambda: calls.append("drawn")
        assert w.call("images.set_color", BANNER, True)
        w.drain()
        assert calls == ["drawn"]
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.call("color.set_mode", "assets") == "assets"
        assert w.call("color.set_all", "images", False)
        w.drain()
        assert calls == ["drawn", "drawn"]
        s = w.state("color")
        assert s["display_active"] is False and s["asset_name"] == "Recommended"
