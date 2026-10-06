"""PAD-408 (DragonRR): "Show it through the machine's screen" is drawn by the
emulator's own window renderer (tools/spike2_emu/padglhost.c), so it works
without "Apply my replaced assets" and on a card PAD already wrote, whose
game program has no room for the screen (PAD-406)."""

import os
import re

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import shader_profile as sp

np = pytest.importorskip("numpy")

from tests.test_pad343_profile_extras_everywhere import (  # noqa: E402
    TUNED, _pixels, _render)

HOST = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu",
                    "padglhost.c")


def _project(tmp_path, data=None):
    d = tmp_path / "proj"
    d.mkdir()
    staged_changes.save(str(d), data or {})
    return str(d)


def _c_string(src, name):
    """The C string constant *name* in padglhost.c, as the compiler joins it."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    m = re.search(r"static const char \*%s =((?:\s*\"(?:[^\"\\]|\\.)*\")+)\s*;"
                  % name, src)
    assert m, name
    parts = re.findall(r"\"((?:[^\"\\]|\\.)*)\"", m.group(1))
    return "".join(parts).encode().decode("unicode_escape")


def _blit_fs(func, scr):
    """The game window's fragment shader exactly as padglhost's blit_link
    builds it (with the Machine screen when *func*), for the browser test
    harness: its varying is ``v`` and it sets no uniforms, so ``u_scr`` is
    pinned to *scr*."""
    with open(HOST, encoding="utf-8") as f:
        src = f.read()
    pre = _c_string(src, "BLIT_FS_SCREEN" if func else "BLIT_FS_PLAIN")
    fs = "%s%s%s\n%s" % (_c_string(src, "BLIT_FS_HEAD"), pre, func,
                         _c_string(src, "BLIT_FS"))
    fs = fs.replace("uniform float u_scr;", "const float u_scr = %.1f;" % scr)
    return re.sub(r"\bv_uv\b", "v", fs)


def test_the_screen_glsl_is_the_screen_alone():
    assert sp.screen_glsl(cp.Profile()) == ""
    g = sp.screen_glsl(TUNED)
    assert "vec3 pad_cx(" in g and "pad_cp" not in g
    assert g.count("vec3 pad_cr(") == 1


def test_the_tick_hands_the_renderer_the_screen_without_assets(tmp_path):
    """No override set needed: Start's environment carries the screen when
    ticked, nothing when not, and the set is never prepared through it."""
    from tests.webui_harness import web_app
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        emu._assets = lambda: proj
        assert emu._screen_env() == []
        w.call("ui.set", "emulate", "machine_screen", True)
        w.drain()
        assert not emu.emulate_overrides_var.get()
        env = emu._screen_env()
        assert len(env) == 1 and env[0].startswith("PAD_SCREEN_GLSL=")
        from pinball_decryptor.core import config
        path = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                            "machine_screen.glsl")
        with open(path, encoding="ascii") as f:
            assert f.read() == sp.screen_glsl(cp.screen_shown(proj)[0])
        assert "PAD_SCREEN_GLSL" in " ".join(emu._launch_env(["PAD_CARD=x"]))
        # the override set's game program no longer draws it too
        seen = []
        emu._prepare_overrides_inner = (
            lambda card, assets, selector=False:
            seen.append(cp.emulated_screen(assets)))
        emu._prepare_overrides("card.raw", proj)
        assert seen == [None]
        # flipped while a game runs: the next Start takes it
        emu._last_up = True
        w.call("ui.set", "emulate", "machine_screen", False)
        w.drain()
        assert "Start the game again" in w.state("emulate").get("screen_live", "")


def test_no_project_runs_the_card_as_it_is(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        emu._assets = lambda: ""
        w.call("ui.set", "emulate", "machine_screen", True)
        w.drain()
        assert emu._screen_env() == []


def test_the_window_draws_the_frame_through_the_screen():
    """Compiles the game window's own blit shader, built from padglhost.c's
    strings, in a real browser's WebGL2 and compares every pixel with the
    Machine screen through numpy; the topper (u_scr 0) and a run without the
    tick draw the frame as it is."""
    sync_api = pytest.importorskip("playwright.sync_api")
    a = _pixels()
    want = TUNED.apply_array(a).astype(int)
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
        got = _render(page, _blit_fs(sp.screen_glsl(TUNED), 1.0), a,
                      True).astype(int)
        err = np.abs(got - want)
        assert err.max() <= 6 and np.percentile(err, 99) <= 2, (
            err.max(), np.percentile(err, 99))
        for fs in (_blit_fs(sp.screen_glsl(TUNED), 0.0), _blit_fs("", 1.0)):
            got = _render(page, fs, a, True).astype(int)
            assert np.abs(got - a.astype(int)).max() <= 1
        browser.close()
    finally:
        pw.stop()
