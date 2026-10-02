"""PAD-324: the machine's screen as its own profile.  The Scenes preview's
"As on the machine" draws through it (forwards, after the whole screen
overlay); until one is stored it is the individual files profile, undone.
Preview only: nothing pending, nothing on the card, Revert all leaves it."""

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

np = pytest.importorskip("numpy")

RECOMMENDED = dict(cp.PRESETS)["recommended"]
SCREEN = dict(cp.SCREEN_PRESETS)


def _rgb():
    rgb = np.zeros((1, 256, 3), np.uint8)
    rgb[0, :, 0] = np.arange(256)
    rgb[0, :, 1] = np.arange(256)[::-1]
    rgb[0, :, 2] = (np.arange(256) * 3) % 256
    return rgb


def test_the_inverse_runs_the_correction_backwards():
    inv = RECOMMENDED.inverse()
    # greys are exact: the saturation mix does nothing to them
    grey = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, 2)
    assert np.abs(inv.apply_array(grey).astype(int)
                  - RECOMMENDED.undo_array(grey).astype(int)).max() <= 2
    back = inv.apply_array(RECOMMENDED.apply_array(grey))
    assert np.abs(back.astype(int) - grey.astype(int)).max() <= 3
    # colours are close: the mix runs before the shades, not after
    x = np.random.default_rng(1).integers(0, 256, (1, 4000, 3)).astype(np.uint8)
    d = np.abs(inv.apply_array(x).astype(int)
               - RECOMMENDED.undo_array(x).astype(int))
    assert d.mean() < 2 and np.percentile(d, 99) <= 12
    k = cp.Profile(gamma=(1.2, 1.0, 1.0), gain=(0.8, 1.0, 1.0))
    rgb = _rgb()
    back = k.inverse().apply_array(k.apply_array(rgb))
    assert np.abs(back[0, :180, 0].astype(int)
                  - rgb[0, :180, 0].astype(int)).max() <= 3
    # Black and white has no inverse: full colour back
    assert cp.Profile(saturation=0.0).inverse().is_identity()


def test_with_no_screen_stored_scenes_looks_as_it_did(tmp_path):
    d = str(tmp_path)
    assert cp.screen_profile(d) is None
    shown, stored = cp.screen_shown(d)
    assert stored is False and shown.name == "Recommended screen"
    assert shown.gamma == SCREEN["screen_recommended"].gamma
    rgb = _rgb()
    assert cp.machine_view(d)(rgb).tobytes() == \
        RECOMMENDED.undo_array(rgb).tobytes()


def test_a_stored_screen_is_what_scenes_draws_through(tmp_path):
    d = str(tmp_path)
    grey = np.full((2, 2, 3), 128, np.uint8)
    bluer = cp.Profile(name="Bluer", gamma=(1.0, 1.0, 0.6))
    cp.store_screen_profile(d, bluer)
    assert cp.screen_profile(d) == bluer
    out = cp.machine_view(d)(grey)
    assert out[0, 0, 2] > 160 and out[0, 0, 0] == 128
    # it no longer follows the individual files profile
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.machine_view(d)(grey).tobytes() == out.tobytes()
    # the overlay is drawn first, the screen last
    cp.store(d, cp.Profile(gamma=(1.0, 1.0, 1.0 / 0.6)))
    assert np.abs(cp.machine_view(d)(grey).astype(int) - 128).max() <= 2


def test_a_black_and_white_screen_greys_the_games_own_art(tmp_path):
    """The case undoing a profile could never show: a monochrome screen."""
    d = str(tmp_path)
    rgb = _rgb()
    cp.store_asset_profile(d, dict(cp.PRESETS)["bw"])
    assert cp.machine_view(d)(rgb).tobytes() == rgb.tobytes()   # B&W undone: nothing
    cp.store_screen_profile(d, SCREEN["bw"])
    out = cp.machine_view(d)(rgb)
    assert (out[..., 0] == out[..., 1]).all() and (out[..., 1] == out[..., 2]).all()


def test_no_change_screen_shows_the_pc_colors_and_none_follows_again(tmp_path):
    d = str(tmp_path)
    cp.store_screen_profile(d, SCREEN["none"])
    assert cp.screen_shown(d)[1] is True
    assert cp.machine_view(d) is None
    cp.store_screen_profile(d, None)
    assert cp.screen_profile(d) is None
    assert cp.machine_view(d) is not None             # Recommended, undone


def test_color_tab_has_a_machine_screen_mode(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    staged_changes.save(str(proj), {"image": {"images/a.png": "x"}})
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.call("color.set_mode", "screen") == "screen"
        w.drain()
        s = w.state("color")
        assert s["mode"] == "screen" and s["screen_stored"] is False
        assert s["active"] is False and s["name"] == "Recommended screen"
        assert [p["key"] for p in s["presets"]] == [
            "screen_recommended", "none", "bw", "follow"]
        w.call("color.set_params", {"gamma": [0.9, 0.8, 0.6]})
        w.drain()
        s = w.state("color")
        assert s["screen_stored"] is True and s["active"] is True
        assert cp.screen_profile(str(proj)).gamma == (0.9, 0.8, 0.6)
        # only the screen moved: both corrections are as they were
        assert cp.for_project(str(proj)) is None
        assert cp.asset_stored(str(proj)) is False
        w.call("color.preset", "bw")
        w.drain()
        assert cp.screen_profile(str(proj)).saturation == 0.0
        # Revert all leaves the machine's screen
        w.window.clear_replace_assignments(str(proj))
        w.drain()
        assert cp.screen_profile(str(proj)) is not None
        w.call("color.preset", "follow")
        w.drain()
        s = w.state("color")
        assert cp.screen_profile(str(proj)) is None
        assert s["screen_stored"] is False and s["name"] == "Recommended screen"
        # the other modes keep their own presets
        assert w.call("color.set_mode", "assets") == "assets"
        w.drain()
        assert [p["key"] for p in w.state("color")["presets"]] == [
            "recommended", "none", "bw"]


def test_the_screen_mode_is_spike2_only(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.call("color.set_mode", "screen") == "display"


def test_the_screen_is_never_a_pending_change(tmp_path):
    from pinball_decryptor.webui import write_scan
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    d = str(tmp_path)
    mfr = SternManufacturer()
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    before = (write_scan.colour_rows(mfr, d), write_scan.chosen_files_rows(mfr, d))
    cp.store_screen_profile(d, SCREEN["bw"])
    assert (write_scan.colour_rows(mfr, d),
            write_scan.chosen_files_rows(mfr, d)) == before == ([], [])


def test_revert_all_keeps_the_screen_and_the_stock_modes_record():
    from pinball_decryptor.plugins.stern import stock_modes
    scr = {"name": "Mine", "gamma": [1, 1, 0.7], "gain": [1, 1, 1],
           "lift": [0, 0, 0], "saturation": 1.0}
    data = {cp.SCREEN_KEY: scr, cp.KEY: {"name": "x"}, "image": {"a": "b"}}
    assert stock_modes.kept_by_revert_all(data) == {cp.SCREEN_KEY: scr}
    assert stock_modes.kept_by_revert_all({"image": {}}) == {}
