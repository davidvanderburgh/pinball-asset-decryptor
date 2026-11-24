"""PAD-1548: Restart to update starts the new version BEFORE it registers the
Visual Pinball controller (that registration boots WSL, which the app has
just shut down), and a stored preview code for features every copy has now is
dropped at start instead of being reported at every one."""

import json

from pinball_decryptor.core import preview as P
from pinball_decryptor.core import update_slots
from tests.test_preview_switch import KEYS, TEST_PUB, TODAY, make_code
from tests.webui_harness import web_app


# ---- the swap helper ---------------------------------------------------------
def _script(**kw):
    return update_slots.swap_script(
        r"C:\Program Files\Pinball Asset Decryptor", "1.2.3",
        r"C:\tmp\setup.exe", 4242, r"C:\tmp\swap.log", **kw)


def test_the_new_version_is_started_before_the_controller_is_registered():
    text = _script()
    launch = text.index("Say 'started the new version'")
    register = text.index("padvpx.py")
    assert launch < register
    # ...and the users' own files are still carried over before the launch
    assert text.index("$stuck = KeepUsers $old $app") < launch


def test_the_helper_does_not_wait_for_the_registration():
    line = next(ln for ln in _script().splitlines()
                if "register')" in ln and "Start-Process" in ln)
    assert "-Wait" not in line
    # not from inside the app's folder: a working directory there holds the
    # folder open against the next update's rename
    assert "-WorkingDirectory $env:TEMP" in line


def test_no_registration_when_it_is_not_asked_for():
    def guard(text):
        lines = text.splitlines()
        at = next(i for i, ln in enumerate(lines) if "padvpx.py" in ln)
        return next(ln for ln in reversed(lines[:at]) if ln.startswith("if ("))
    assert guard(_script(register=True)) == "if ($true) {"
    assert guard(_script(register=False)) == "if ($false) {"


# ---- spent preview codes -----------------------------------------------------
def test_a_code_for_released_features_only_is_spent():
    released = sorted(P.RELEASED)
    spent = make_code(features=(released[0],), issued=TODAY, code_id="aa0001")
    both = make_code(features=tuple(released), issued=TODAY, code_id="aa0002")
    mixed = make_code(features=(released[0], "something-new"), issued=TODAY,
                      code_id="aa0003")
    unknown = make_code(features=("something-new",), issued=TODAY,
                        code_id="aa0004")
    codes = [spent, "not a code", mixed, both, unknown]
    assert P.without_spent(codes, KEYS) == ["not a code", mixed, unknown]
    assert P.without_spent([], KEYS) == [] and P.without_spent(None, KEYS) == []


def test_a_spent_code_signed_with_another_key_is_kept():
    """Only a code that checks out is dropped: anything else keeps its line
    in the log, the one word its holder gets."""
    code = make_code(features=(sorted(P.RELEASED)[0],), issued=TODAY)
    assert P.without_spent([code], public_keys=("00" * 32,)) == [code]


def test_a_start_drops_spent_codes_and_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PUBLIC_KEYS", (TEST_PUB,))
    released = sorted(P.RELEASED)
    codes = [make_code(features=(f,), issued=P.utc_today(),
                       code_id="bb%04d" % i)
             for i, f in enumerate(released)]
    with web_app(tmp_path, mfr="stern",
                 settings={P.SETTINGS_KEY: codes}) as w:
        assert P.SETTINGS_KEY not in w.app._settings
        said = [e["text"] for e in w.window.log_history()]
        assert not any("Preview features" in t for t in said), said
        # every released feature is on all the same
        assert all(P.enabled(f) for f in released)
    saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(
        encoding="utf-8"))
    assert P.SETTINGS_KEY not in saved


def test_a_start_keeps_a_code_it_cannot_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PUBLIC_KEYS", (TEST_PUB,))
    spent = make_code(features=(sorted(P.RELEASED)[0],),
                      issued=P.utc_today(), code_id="cc0001")
    other = make_code(features=("something-new",), issued=P.utc_today(),
                      code_id="cc0002")
    with web_app(tmp_path, mfr="stern",
                 settings={P.SETTINGS_KEY: [spent, other]}) as w:
        assert w.app._settings[P.SETTINGS_KEY] == [other]
        said = [e["text"] for e in w.window.log_history()]
        assert any("something-new: not in this version of the app" in t
                   for t in said), said
        assert any("1 code(s) checked in" in t for t in said), said
