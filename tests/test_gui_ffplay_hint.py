"""GUI guards for the no-ffplay preview dead end (PAD-92).

A Windows user with only the app's bundled ffmpeg pressed ▶ on the Audio tab,
was told to click "Install Missing" above the tabs and to drop ffplay.exe next
to ffmpeg.exe -- and could do neither: the prerequisite strip hides itself when
every probe is green (ffplay is nobody's probe), the ⚙ menu's installer entry
was greyed out for the same reason, and the folder holding "ffmpeg.exe" was the
throwaway temp copy the startup shim makes.
"""

import tkinter as tk

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

import pinball_decryptor.gui.main_window as mw
from pinball_decryptor.core import audio as _audio


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

FAKE_DIR = r"C:\Program Files\Pinball Asset Decryptor\python\Lib" \
           r"\site-packages\imageio_ffmpeg\binaries"


def _pick(app, key="stern"):
    mfr = next(m for m in app._manufacturers if m.key == key)
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


def _install_entry(w):
    """(label, state) of the ⚙ > Prerequisites > Install… entry."""
    menu = w._build_settings_menu()
    sub = None
    for i in range(menu.index(tk.END) + 1):
        if (menu.type(i) == "cascade"
                and "Prerequisites" in menu.entrycget(i, "label")):
            sub = menu.nametowidget(menu.entrycget(i, "menu"))
    assert sub is not None, "no Prerequisites cascade in the gear menu"
    for i in range(sub.index(tk.END) + 1):
        label = sub.entrycget(i, "label")
        if label.startswith("Install"):
            return label, str(sub.entrycget(i, "state"))
    raise AssertionError("no Install entry in the Prerequisites submenu")


def test_installer_entry_stays_live_when_everything_is_green(app):
    """The regression: all probes green greyed the entry out, and the strip's
    button is hidden then too -- so the user needing the full ffmpeg build
    (which no probe checks for) had no way to start the installer."""
    w = _pick(app)
    for name in list(w._prereq_indicators):
        w.set_prereq_result(name, True, "ok")
    label, state = _install_entry(w)
    assert state == "normal"
    assert label == "Install / repair prerequisites…"


def test_installer_entry_still_says_missing_when_something_is(app):
    w = _pick(app)
    names = list(w._prereq_indicators)
    for name in names:
        w.set_prereq_result(name, True, "ok")
    w.set_prereq_result(names[0], False, "gone")
    label, state = _install_entry(w)
    assert state == "normal"
    assert label == "Install missing prerequisites…"


def test_no_ffplay_dialog_names_the_folder_and_offers_the_installer(
        app, monkeypatch):
    w = _pick(app)
    monkeypatch.setattr(_audio, "ffmpeg_sibling_dirs", lambda: [FAKE_DIR])
    seen = {}

    def _fake_askyesno(title, msg):
        seen["title"], seen["msg"] = title, msg
        return False

    monkeypatch.setattr(mw.messagebox, "askyesno", _fake_askyesno)
    launched = []
    w._on_install_prereqs = lambda: launched.append(1)

    w._no_ffplay_dialog()

    assert seen["title"] == "Can't Preview"
    msg = seen["msg"]
    assert FAKE_DIR in msg                    # the folder that IS searched
    assert "Install Missing" not in msg       # the button that isn't there
    assert "where ffmpeg" not in msg          # points at the shim's temp dir
    assert "Preview is optional" in msg       # unchanged reassurance
    assert not launched                       # the fake answered "no"


def test_no_ffplay_dialog_yes_runs_the_installer(app, monkeypatch):
    w = _pick(app)
    monkeypatch.setattr(_audio, "ffmpeg_sibling_dirs", lambda: [FAKE_DIR])
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a, **k: True)
    launched = []
    w._on_install_prereqs = lambda: launched.append(1)
    w._no_ffplay_dialog()
    assert launched == [1]


def test_preview_failure_raises_that_dialog(app, monkeypatch):
    """The Audio tab's ▶ with no player at all is what puts it up."""
    w = _pick(app)
    monkeypatch.setattr(_audio, "play_audio_file", lambda *a, **k: None)
    shown = []
    monkeypatch.setattr(w, "_no_ffplay_dialog", lambda: shown.append(1))
    pane = w._audio_pane_orig
    assert pane is not None
    pane.start_playback(0.0)
    assert shown == [1]
    assert not pane.playing
