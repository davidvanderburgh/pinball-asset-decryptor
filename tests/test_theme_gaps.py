"""A picture changed in some themes only (Simon, 2026-11-19: "Are we catering for an image that is in theme 3, 7, 8
but not in the in between themes or theme 1?"): eight themes, the picture the game's own in theme 1 and picked in
themes 3, 7 and 8 - those three get their own picture and their own color, the others show theme 1's, and the Write
makes a scene of its own for 3, 7 and 8 only."""
import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.plugins.stern import scene_variants as SV

from tests.test_image_sets_pictures import CARD, REL, _png, _project, _scene

pytest.importorskip("PIL.Image")

TREL = "images/" + REL
PICKED = (3, 7, 8)


def _eight(tmp_path):
    data, off = _scene()
    p = _project(tmp_path, off)
    SV.set_themes_on(p, True)
    for i in range(2, 9):
        assert SV.add_set(p, "T%d" % i) == i
    for n in PICKED:
        SV.set_picture(p, n, TREL, _png(tmp_path / ("t%d.png" % n), (40 * n % 255, 80, 120, 255)))
    return p, data


def test_only_the_themes_that_picked_it_have_it(tmp_path):
    p, _data = _eight(tmp_path)
    for n in range(2, 9):
        assert SV.theme_falls_back(p, n, TREL) is (n not in PICKED), n
    assert SV.load(p)["images"].keys() == set(PICKED)


def test_each_picked_theme_has_its_own_color(tmp_path):
    p, _data = _eight(tmp_path)
    red = cp.Profile(name="Red", gain=(1.0, 0.3, 0.3))
    cp.store_own_profile(p, "images", SV.theme_key(7, TREL), red)
    cp.set_asset_slot(p, "images", SV.theme_key(7, TREL), True)
    on, prof = SV.theme_colour(p, 7, TREL)
    assert on and prof.name == "Red"
    for n in (3, 8):                                        # raw until given one
        assert SV.theme_colour(p, n, TREL)[0] is False
    for n in (2, 4, 5, 6):                                  # theme 1's: the game's own, no profile
        assert SV.theme_colour(p, n, TREL)[0] is False


def test_the_write_makes_scenes_for_those_themes_only(tmp_path):
    p, data = _eight(tmp_path)
    got = SV.picture_variants(p, SV.load(p), lambda card: data if card == CARD else None, str(tmp_path / "work"))
    assert set(got["scenes"][CARD]) == set(PICKED)
