"""Guards for the no-player preview dead end (PAD-92).

A Windows user with only the app's bundled ffmpeg pressed ▶ on the Audio tab,
was told to click "Install Missing" above the tabs and to drop ffplay.exe next
to ffmpeg.exe -- and could do neither: the prerequisite strip hides itself when
every probe is green (ffplay is nobody's probe), the ⚙ menu's installer entry
was greyed out for the same reason, and the folder holding "ffmpeg.exe" was the
throwaway temp copy the startup shim makes.

On the web UI the page plays the preview itself and asks
``audio.cant_preview`` when it can't (webui/tabs/audio.py); the ⚙ menu is
``shell.settings_items`` (webui/tabs/shell_extras.py).
"""

import sys

import pytest

from pinball_decryptor.core import audio as _audio
from tests.webui_harness import web_app

CLIP = r"C:\proj\audio\idx0001.ogg"


# The ⚙ menu's install entry and the dialog's Yes button are Windows/Linux
# only: a frozen macOS bundle ships its prerequisites and can't pip-install, so
# the menu deliberately never adds that entry there.
no_installer = pytest.mark.skipif(sys.platform == "darwin",
                                  reason="no auto-installer on macOS")


def _install_entry(w):
    """The ⚙ > Prerequisites > Install… entry."""
    top = w.state("shell")["settings_items"]
    sub = next((it["submenu"] for it in top
                if it.get("submenu") is not None
                and "Prerequisites" in (it.get("label") or "")), None)
    assert sub is not None, "no Prerequisites cascade in the gear menu"
    for it in sub:
        if (it.get("label") or "").startswith("Install"):
            return it
    raise AssertionError("no Install entry in the Prerequisites submenu")


def _probe_all(w, ok=True):
    win = w.window

    def _do():
        mfr = win.current_mfr
        win.reset_prereqs(mfr.prerequisites)
        names = [p.name for p in mfr.prerequisites]
        for name in names:
            win.set_prereq_result(name, ok, "ok")
        return names
    return w.run(_do)


def _no_ffmpeg(monkeypatch, w, installer):
    monkeypatch.setattr(_audio, "find_ffmpeg", lambda *a, **k: None)
    launched = []
    w.window.cb["on_install_prereqs"] = (
        (lambda: launched.append(1)) if installer else None)
    return launched


@no_installer
def test_installer_entry_stays_live_when_everything_is_green(tmp_path):
    """The regression: all probes green greyed the entry out, and the strip's
    button is hidden then too -- so the user needing the full ffmpeg build
    (which no probe checks for) had no way to start the installer."""
    with web_app(tmp_path, mfr="stern") as w:
        _probe_all(w)
        entry = _install_entry(w)
        assert not any(k.startswith("needs_") or k == "disabled"
                       for k in entry)
        assert entry["label"] == "Install / repair prerequisites…"
        assert all(r["state"] == "ok" for r in w.state("shell")["prereqs"])


@no_installer
def test_installer_entry_still_says_missing_when_something_is(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        names = _probe_all(w)
        w.run(w.window.set_prereq_result, names[0], False, "gone")
        entry = _install_entry(w)
        assert not any(k.startswith("needs_") or k == "disabled"
                       for k in entry)
        # the page shows label_missing while any probe is missing
        assert entry["label_missing"] == "Install missing prerequisites…"
        assert [r["state"] for r in w.state("shell")["prereqs"]].count(
            "missing") == 1


def test_no_ffplay_dialog_names_the_folder_and_offers_the_installer(
        tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        launched = _no_ffmpeg(monkeypatch, w, installer=True)

        assert w.call("audio.cant_preview", CLIP) is True

        spec = w.asked[-1]
        assert spec["title"] == "Can't Preview"
        msg = spec["message"]
        assert CLIP in msg                        # the file it couldn't play
        assert "Install Missing" not in msg       # the button that isn't there
        assert "where ffmpeg" not in msg          # points at the shim's temp dir
        assert "Preview is optional" in msg       # unchanged reassurance
        assert not launched                       # nothing answered "yes"


@no_installer
def test_no_ffplay_dialog_yes_runs_the_installer(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        launched = _no_ffmpeg(monkeypatch, w, installer=True)
        w.answers.append("yes")
        w.call("audio.cant_preview", CLIP)
        assert launched == [1]


def test_no_ffplay_dialog_without_an_installer_just_says_what_to_do(
        tmp_path, monkeypatch):
    """Where the app can't run the installer for you -- macOS, or any build
    with no installer wired up -- the dialog is a plain warning with no Yes
    button, and it still names the file.  This branch had no test, which is
    how it reached CI: the macOS job opened the real box and hung."""
    with web_app(tmp_path, mfr="stern") as w:
        _no_ffmpeg(monkeypatch, w, installer=False)

        w.call("audio.cant_preview", CLIP)

        spec = w.asked[-1]
        assert spec["title"] == "Can't Preview"
        assert [b["id"] for b in spec["buttons"]] == ["ok"]
        assert CLIP in spec["message"]
        assert "Press Yes" not in spec["message"]
        assert "Preview is optional" in spec["message"]
