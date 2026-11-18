"""A theme's own colour profiles (Simon, 2026-11-18: "every single image can be colour profiled", per theme, "not fixed
between sets (so completely configurable)"): kept under theme keys beside theme 1's, inherited from theme 1 until set,
moved with their theme, and baked in by the Write."""
import os

from pinball_decryptor.core import colour_profile as cp, staged_changes
from pinball_decryptor.plugins.stern import scene_variants as SV

from tests.test_image_sets_pictures import CARD, REL, _png, _project, _scene

TREL = "images/" + REL                                  # the Images tab's name for the picture
DARK = cp.Profile(name="Dark", brightness=0.5)
RED = cp.Profile(name="Red", gain=(1.0, 0.3, 0.3))


def test_theme_keys():
    assert SV.theme_key(1, TREL) == TREL
    assert SV.theme_key(3, TREL) == "@3:" + TREL
    assert SV.split_theme_key("@3:" + TREL) == (3, TREL)
    assert SV.split_theme_key(TREL) == (1, TREL)


def test_a_theme_inherits_theme_1_until_it_has_its_own(tmp_path):
    p = str(tmp_path)
    SV.set_themes_on(p, True)
    SV.add_set(p, "Dark")
    cp.set_asset_slot(p, "images", TREL, True)
    cp.store_own_profile(p, "images", TREL, RED)
    on, prof = SV.theme_colour(p, 2, TREL)
    assert on and prof.name == "Red"                   # theme 1's switch and profile
    cp.store_own_profile(p, "images", SV.theme_key(2, TREL), DARK)
    cp.set_asset_slot(p, "images", SV.theme_key(2, TREL), True)
    on, prof = SV.theme_colour(p, 2, TREL)
    assert on and prof.name == "Dark"
    assert cp.own_profile(p, "images", TREL).name == "Red"   # theme 1 untouched
    cp.set_asset_slot(p, "images", SV.theme_key(2, TREL), False)
    assert SV.theme_colour(p, 2, TREL)[0] is False      # off in theme 2 while on in theme 1


def test_a_colour_only_theme_is_a_variant(tmp_path):
    p = str(tmp_path)
    SV.set_themes_on(p, True)
    SV.add_set(p, "Dark")
    assert SV.load(p) is None
    cp.store_own_profile(p, "images", SV.theme_key(2, TREL), DARK)
    got = SV.load(p)
    assert got["colour"] == {2: {TREL}} and got["names"] == ["Standard", "Dark"]


def test_removing_or_moving_a_theme_takes_its_colours(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.add_set(p, "Red")
    cp.store_own_profile(p, "images", SV.theme_key(3, TREL), RED)
    cp.set_asset_slot(p, "images", SV.theme_key(3, TREL), True)
    SV.move_set(p, 3, 2)
    assert cp.own_profile(p, "images", SV.theme_key(2, TREL)).name == "Red"
    assert cp.asset_settings(p)["images"] == {SV.theme_key(2, TREL): True}
    SV.remove_set(p, 2)
    side = staged_changes.load(p)
    assert not side.get(cp.IMAGE_SLOTS_KEY) and not side.get(cp.FILE_PROFILES_KEY["images"])


def test_the_write_bakes_a_themes_profile_into_theme_1s_picture(tmp_path):
    data, off = _scene()
    p = _project(tmp_path, off)
    # theme 1's picture: the project's file, as the Extract left it
    os.makedirs(os.path.join(p, "images", "scene_textures"), exist_ok=True)
    _png(os.path.join(p, *TREL.split("/")), (200, 200, 200, 255))
    SV.set_themes_on(p, True)
    SV.add_set(p, "Dark")
    cp.store_own_profile(p, "images", SV.theme_key(2, TREL), DARK)
    cp.set_asset_slot(p, "images", SV.theme_key(2, TREL), True)
    said = []
    got = SV.picture_variants(p, SV.load(p), lambda card: data if card == CARD else None, str(tmp_path / "work"),
                              lambda m, *a: said.append(m))
    src = got["scenes"][CARD][2]["file"]
    with open(src, "rb") as f:
        assert f.read() != data
    assert any("colour profiled" in m for m in said)
    # the picture baked: a darker copy of theme 1's, beside the scene
    from PIL import Image
    coloured = [f for f in os.listdir(str(tmp_path / "work")) if f.startswith("colour2_")]
    assert coloured
    px = Image.open(os.path.join(str(tmp_path / "work"), coloured[0])).convert("RGB").getpixel((0, 0))
    assert px[0] < 200
