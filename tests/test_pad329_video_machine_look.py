"""PAD-329: As on the machine on the Video tab's players.  The service hands
each player its colour steps (core/colour_profile.py filter_step), which the
page turns into an SVG filter on the <video>: no clip is re-encoded."""

import pytest

from pinball_decryptor.core import colour_profile as cp

np = pytest.importorskip("numpy")

RECOMMENDED = dict(cp.PRESETS)["recommended"]


def _apply_step(step, rgb):
    """What a browser does with one filter_step, in sRGB: the matrix, then each
    channel's gamma transfer, each clamped to 0..1."""
    x = rgb.astype(np.float64) / 255.0
    if step["m"]:
        m = np.asarray(step["m"], np.float64).reshape(4, 5)[:3, :3]
        x = np.clip(x @ m.T, 0.0, 1.0)
    out = np.empty_like(x)
    for c, (amp, exp, off) in enumerate(step["f"]):
        out[..., c] = np.clip(amp * np.power(x[..., c], exp) + off, 0.0, 1.0)
    return out * 255.0


@pytest.mark.parametrize("prof", [
    RECOMMENDED,
    cp.Profile(gamma=(1.0, 1.0, 0.6), gain=(1.2, 0.8, 1.0), lift=(0.05, 0.05, 0.05)),
    cp.Profile(saturation=0.0),
    dict(cp.SCREEN_PRESETS)["screen_recommended"],
])
def test_the_filter_draws_the_profiles_own_curve(prof):
    rng = np.random.default_rng(3)
    rgb = rng.integers(0, 256, (1, 3000, 3)).astype(np.uint8)
    got = _apply_step(cp.filter_step(prof), rgb)
    want = prof.apply_array(rgb).astype(np.float64)
    # the profile rounds to whole levels between its mix and its curve; a
    # browser keeps the fraction, so a mixed colour can land a level or two off
    d = np.abs(got - want)
    assert d.max() <= 2.5 and d.mean() < 0.6


def test_no_change_is_no_step():
    assert cp.filter_step(None) is None
    assert cp.filter_step(cp.Profile(name="No change")) is None


def test_the_players_follow_the_switch_and_the_setting(tmp_path):
    d = str(tmp_path)
    over = cp.Profile(name="Less red", gain=(0.5, 1.0, 1.0))
    cp.store(d, over)
    cp.store_screen_profile(d, cp.Profile(name="Black and white", saturation=0.0))
    o, s = cp.filter_step(over), cp.filter_step(cp.screen_profile(d))
    files = cp.filter_step(cp.asset_profile(d))                  # Recommended
    look = cp.video_look(d, None, True)
    assert look["orig"] == [o, s] and look["rep"] == [o, s]      # no switch: like stock
    assert cp.video_look(d, True, True)["rep"] == [files, o, s]  # on: baked, then the rest
    assert cp.video_look(d, False, True)["rep"] == [o]           # off: overlay only
    assert cp.video_look(d, False, False)["rep"] == [o, s]       # setting unticked
    cp.store(d, None)
    cp.store_screen_profile(d, cp.Profile(name="No change"))
    assert cp.video_look(d, None, True) == {"orig": [], "rep": []}


def test_the_video_tab_publishes_the_look_and_its_tick(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "video")
        w.drain()
        look = w.state("video")["look"]
        assert look["offered"] is True and look["on"] is True
        assert look["orig"] == [cp.filter_step(cp.screen_shown(str(proj))[0])]
        assert w.call("video.set_machine_look", False)
        w.drain()
        look = w.state("video")["look"]
        assert look["on"] is False and look["orig"] == [] and look["rep"] == []


def test_the_tick_is_spike2_only(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "video")
        w.drain()
        assert w.state("video")["look"]["offered"] is False
