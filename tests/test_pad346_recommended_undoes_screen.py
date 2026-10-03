"""PAD-346: on Spike 2 the whole screen overlay's and the individual files'
Recommended is the Machine screen undone, built from the sliders, colour
ranges and curves every profile has, and it follows that screen."""

import pytest

from pinball_decryptor.core import colour_profile as cp

np = pytest.importorskip("numpy")

SCREEN = dict(cp.SCREEN_PRESETS)["screen_recommended"]
MEASURED = dict(cp.PRESETS)["recommended"]
GREYS = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, 1)[None]


def _grey_miss(screen, prof):
    back = screen.apply_array(prof.apply_array(GREYS)).astype(int)
    return int(np.abs(back - GREYS).max())


def test_the_recommended_screen_comes_back_as_made():
    rec = cp.undo_screen(SCREEN)
    assert rec.name == "Recommended"
    probe = cp._probe(15)
    miss = cp._round_trip(SCREEN, rec, probe)
    assert miss < 6.0
    # far closer than nothing, or the old measured Recommended
    assert miss * 4 < cp._round_trip(SCREEN, cp.Profile(), probe)
    assert miss * 4 < cp._round_trip(SCREEN, MEASURED, probe)
    # greys stay grey up to the screen's 8-bit steps (red tops out at 252)
    assert _grey_miss(SCREEN, rec) <= 4


def test_it_is_made_of_the_controls_a_user_can_move():
    rec = cp.undo_screen(SCREEN)
    # same as a profile the page or a file could give
    assert cp.parse(cp.to_text(rec))[0] == rec
    assert len(rec.ranges) == len(SCREEN.ranges)
    for rng in rec.ranges:
        assert cp.clean_range(rng) == rng
    for _ch, pts in rec.curves:
        assert cp.clean_points(pts) == pts and len(pts) <= cp.MAX_POINTS
        tab = cp.curve_table(pts)
        assert tab == sorted(tab)                        # never folds back


def test_a_screen_of_sliders_alone_is_undone_by_curves():
    screen = cp.Profile(name="Mine", gamma=(0.8, 0.75, 0.6), saturation=1.25,
                        brightness=1.1)
    rec = cp.undo_screen(screen)
    assert rec.ranges == () and rec.saturation == 0.8
    back = screen.apply_array(rec.apply_array(GREYS)).astype(int)
    miss = np.abs(back - GREYS).max(-1)[0]
    # below 40 this screen jumps several levels per 8-bit step: unreachable
    assert miss[40:].max() <= 3
    assert cp._round_trip(screen, rec, cp._probe(15)) < 4.0


def test_nothing_to_undo_is_no_change():
    assert cp.undo_screen(cp.Profile(name="No change")).is_identity()
    # black and white cannot be undone
    assert cp.undo_screen(cp.Profile(saturation=0.0)).is_identity()


def test_it_follows_the_machine_screen(tmp_path):
    d = str(tmp_path)
    assert cp.asset_profile(d) == cp.undo_screen(SCREEN)
    mine = cp.Profile(name="Mine", gamma=(0.8, 0.8, 0.7))
    cp.store_screen_profile(d, mine)
    assert cp.asset_profile(d) == cp.undo_screen(mine)
    assert cp.asset_stored(d) is False
    # "Same as individual files" cannot follow back: the measured one
    cp.store_screen_profile(d, None, follow=True)
    assert cp.asset_profile(d) == MEASURED


def test_the_overlay_follows_too_and_the_files_then_change_nothing(tmp_path):
    d = str(tmp_path)
    cp.store(d, None, follow=True)
    assert cp.follows_screen(d)
    assert cp.for_project(d) == cp.active(d) == cp.undo_screen(SCREEN)
    # the overlay already undoes the screen for the files
    assert cp.asset_profile(d).is_identity() and cp.asset_active(d) is None
    mine = cp.Profile(name="Mine", gamma=(0.8, 0.8, 0.7))
    cp.store_screen_profile(d, mine)
    assert cp.for_project(d) == cp.undo_screen(mine)
    assert cp.signature(d) == cp.undo_screen(mine).key()
    cp.store(d, None)
    assert cp.for_project(d) is None and not cp.follows_screen(d)
    assert cp.asset_profile(d) == cp.undo_screen(mine)


def test_the_tab_offers_it_follows_and_lets_go_on_a_slider(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", d)
        w.call("ui.select_tab", "color")
        w.drain()
        tips = {p["key"]: p["tip"] for p in w.state("color")["presets"]}
        assert "Undoes the Machine screen" in tips["recommended"]
        assert w.call("color.preset", "recommended")
        w.drain()
        s = w.state("color")
        assert s["follows_screen"] is True and s["active"] is True
        assert s["ranges"] == [list(r) for r in cp.undo_screen(SCREEN).ranges]

        # a new Machine screen: the overlay follows it
        w.call("color.set_mode", "screen")
        w.drain()
        w.call("color.set_params", {"gamma": [0.8, 0.8, 0.7]})
        w.drain()
        screen = cp.screen_profile(d)
        assert cp.for_project(d) == cp.undo_screen(screen)

        # a slider on the overlay keeps its numbers from there
        w.call("color.set_mode", "display")
        w.drain()
        before = cp.for_project(d)
        w.call("color.set_params", {"saturation": 0.9})
        w.drain()
        prof = cp.for_project(d)
        assert not cp.follows_screen(d) and prof.name == "My profile"
        assert prof.curves == before.curves and prof.saturation == 0.9
        assert w.state("color")["follows_screen"] is False

        # the files' Recommended: unstored, following
        w.call("color.set_mode", "assets")
        w.drain()
        w.call("color.set_params", {"saturation": 0.8})
        w.drain()
        assert cp.asset_stored(d)
        assert w.call("color.preset", "recommended")
        w.drain()
        assert not cp.asset_stored(d)
        assert cp.asset_profile(d) == cp.undo_screen(screen)
