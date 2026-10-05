"""PAD-389 (DragonRR): the Emulate tab can draw the game through the Machine
screen, so the emulator on a PC shows what the machine's own screen will
(the Scenes preview's view).  Emulate only: a Write never carries it."""

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import shader_profile as sp
from tests.test_pad343_profile_extras_everywhere import ES1, ES3, TUNED, _pixels, _render

np = pytest.importorskip("numpy")

OVERLAY = cp.Profile(name="Warm", gain=(1.1, 1.0, 0.9), gamma=(0.9, 1.0, 1.1),
                     saturation=0.9,
                     ranges=((200.0, 60.0, 20.0, 10.0, 1.2, 1.0, 0.15),))


def _project(tmp_path, data=None):
    d = tmp_path / "proj"
    d.mkdir()
    staged_changes.save(str(d), data or {})
    return str(d)


def test_the_screen_is_held_off_unless_an_emulate_run_asks(tmp_path):
    proj = _project(tmp_path)
    assert cp.emulated_screen(proj) is None
    plain = cp.signature(proj)
    with cp.through_screen(True):
        screen = cp.emulated_screen(proj)
        assert screen is not None
        assert screen.key() == cp.screen_shown(proj)[0].key()
        # a set built through the screen is never reused without it
        assert cp.signature(proj) != plain
    assert cp.emulated_screen(proj) is None
    assert cp.signature(proj) == plain


def test_the_engine_hands_the_shader_the_overlay_then_the_screen(tmp_path):
    from pinball_decryptor.plugins.stern import engine
    proj = _project(tmp_path)
    assert engine._shader_colour_profile(proj) is None
    with cp.through_screen(True):
        got = engine._shader_colour_profile(proj)
    assert isinstance(got, sp.Shown) and got.prof is None
    assert "Machine screen" in got.label()
    cp.store(proj, OVERLAY)
    with cp.through_screen(True):
        got = engine._shader_colour_profile(proj)
    assert got.prof.key() == OVERLAY.key()
    # Stock colors leaves the overlay out but keeps the screen
    with cp.forced(False), cp.through_screen(True):
        got = engine._shader_colour_profile(proj)
    assert isinstance(got, sp.Shown) and got.prof is None


def test_the_overlay_alone_builds_the_shader_it_always_did():
    fs = sp.patch_source(ES1, OVERLAY)
    assert "pad_sx" not in fs
    # one set of tunable slots: what the multi-boot menu rewrites on a card
    assert len(sp._FUNC_RE.findall(fs.encode())) == 1
    assert sp.tunable_in(fs.encode())[0].gain == OVERLAY.folded().gain


def test_both_profiles_share_one_range_function():
    fs = sp.patch_source(ES1, sp.Shown(OVERLAY, TUNED))
    assert fs.count("vec3 pad_cr(") == 1
    assert "vec3 pad_cx(" in fs and "vec3 pad_sx(" in fs
    body = fs[fs.index("vec4 pad_cp("):]
    assert body.index("c=pad_cx(c);") < body.index("c=pad_sx(c);")
    # no overlay: identity terms, then the screen
    fs = sp.patch_source(ES3, sp.Shown(None, TUNED))
    assert fs.count("vec3 pad_cr(") == 1 and "pad_cx" not in fs


def test_the_shader_draws_the_overlay_then_the_screen():
    """Compiles the patched ES 1.00 and ES 3.00 shaders in a real browser's
    WebGL and compares every pixel with numpy: overlay, then screen."""
    sync_api = pytest.importorskip("playwright.sync_api")
    a = _pixels()
    want = TUNED.apply_array(OVERLAY.apply_array(a)).astype(int)
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:                              # noqa: BLE001
        pytest.skip("no playwright: %s" % e)
    try:
        browser = None
        for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                browser = pw.chromium.launch(**kw)
                break
            except Exception:                           # noqa: BLE001
                continue
        if browser is None:
            pytest.skip("no browser")
        page = browser.new_page()
        for src, es3 in ((ES1, False), (ES3, True)):
            fs = sp.patch_source(src, sp.Shown(OVERLAY, TUNED))
            got = _render(page, fs, a, es3).astype(int)
            err = np.abs(got - want)
            assert err.max() <= 6 and np.percentile(err, 99) <= 2, (
                es3, err.max(), np.percentile(err, 99))
        browser.close()
    finally:
        pw.stop()


def test_the_emulate_tick_is_a_per_project_field():
    from pinball_decryptor import app
    keys = {k: w for k, w, _kind, _d in app.PROJECT_FIELDS}
    assert keys["emulate_machine_screen"] == "emulate.emulate_machine_screen_var"


def test_the_tick_holds_the_screen_on_for_the_runs_preparation(tmp_path, monkeypatch):
    """Ticked, the override set is prepared through the Machine screen; the
    game running says it takes at the next Start; unticked, nothing is."""
    from tests.webui_harness import web_app
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        seen = []
        monkeypatch.setattr(emu, "_prepare_overrides_inner",
                            lambda card, assets, selector=False: seen.append(
                                cp.emulated_screen(assets) is not None))
        emu._prepare_overrides("card.raw", proj)
        w.call("ui.set", "emulate", "overrides", True)
        emu._live_set = {"assets": proj, "out": str(tmp_path / "o")}
        emu._colour_src = ("card.raw", "card.raw")
        emu._last_up = True
        w.call("ui.set", "emulate", "machine_screen", True)
        w.drain()
        assert "Start the game again" in w.state("emulate").get("colour_live", "")
        emu._prepare_overrides("card.raw", proj)
        assert seen == [False, True]
        assert cp.emulated_screen(proj) is None
