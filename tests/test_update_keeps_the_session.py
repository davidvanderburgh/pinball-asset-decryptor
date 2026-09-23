"""PAD-188: an in-app update does not cost you the session that ran it.

BEN, Discord @ben01434: "I add a random image as one of my images in a
multiboot collection.  I then see a notification that there is an update and I
use the built in updater.  When it restarts, the original single images are
still there but the random one is gone."

The singles he still had were the LAST CLEAN QUIT'S.  Nothing from the session
that pressed Update was ever written: the Multi-boot tab's whole form has
exactly one save-point - the quit - and that save sat BEHIND
``emulate_shutdown()``, which is blocking, runs through wsl.exe and is bounded
in tens of seconds.  Meanwhile the installer was already running with
/FORCECLOSEAPPLICATIONS, and on Linux the successor AppImage was already up and
reading settings.json.  Whoever got there first won, and it was not the save.

So the state is written FIRST - before the hand-off on every path that has one,
and before anything in the quit that can block.

These run with no Tk, no WSL and no installer: ``settings.json`` is a real file
in ``tmp_path``, and the force-close is a BaseException raised out of the
emulator shutdown, which is what being killed mid-quit looks like from here
(the close's own ``except Exception`` would swallow anything less).
"""

import json
import types

import pytest

from pinball_decryptor import app as app_mod
from pinball_decryptor.webui import multiboot_core as mb
from pinball_decryptor.webui.multiboot_core import (ImageRow, MemberRow, is_group,
                                                 rows_from_state)


class _ForceClosed(BaseException):
    """The installer ending this process mid-quit."""


class _Window:
    def __init__(self, order, kill_at=None):
        self.order = order
        self.kill_at = kill_at
        self.log = []

    def _maybe_die(self, where):
        self.order.append(where)
        if self.kill_at == where:
            raise _ForceClosed(where)

    def stop_all_preview_playback(self):
        self._maybe_die("preview")

    def emulate_shutdown(self):
        self._maybe_die("emulators")

    def append_log(self, text, level="info"):
        self.log.append((level, text))

    def close(self):
        self.order.append("close")


class _Dialogs:
    def __init__(self, order):
        self.order = order

    def cancel_all(self):
        self.order.append("cancel")


class _App:
    """The real close and the real update hand-offs, over a stub window.

    ``_save_settings`` is the real one's multiboot line plus a JSON write:
    everything else in it is beside the point here, and the point is
    which side of the hand-off the file lands on.
    """

    _save_session_state = app_mod.App._save_session_state
    _on_close = app_mod.App._on_close
    _launch_downloaded_installer = app_mod.App._launch_downloaded_installer
    _finish_appimage_update = app_mod.App._finish_appimage_update

    def __init__(self, settings_file, kill_at=None, state=None, boom=False):
        self.order = []
        self.window = _Window(self.order, kill_at)
        self.ctx = types.SimpleNamespace(dialogs=_Dialogs(self.order))
        self._project_path = None
        self._settings = {}
        self._settings_file = str(settings_file)
        self._state = state or {}
        self._boom = boom

    def _capture_run(self):
        return False

    def multiboot_state(self):
        return self._state

    def _save_settings(self):
        self.order.append("settings")
        if self._boom:
            raise RuntimeError("the settings file is on a NAS that went away")
        multi = self.multiboot_state()
        if multi:
            self._settings["multiboot_state"] = multi
        with open(self._settings_file, "w", encoding="utf-8") as f:
            json.dump(self._settings, f)

    def _restart_wsl_for_update(self):
        self.order.append("wsl")


class _Dialog:
    def close(self):
        pass


def _his_form():
    """What he had on the tab: two single images, and a random card over them.

    The state document the tab actually writes (``MultibootPanel.state``), so
    the assertion below is about the row he lost and not about a shape invented
    for the test."""
    rows = [ImageRow(path="godzilla_le.raw", title="GODZILLA"),
            ImageRow(path="jaws_le.raw", title="JAWS"),
            ImageRow(path="", title="RANDOM", keep=True,
                     members=[MemberRow(path="godzilla_le.raw"),
                              MemberRow(path="jaws_le.raw")])]
    return {"v": mb.STATE_VERSION, "card": "E:\\multiboot.raw",
            "images": [mb.asdict(r) for r in rows], "menu": {}}


def _restored(settings_file):
    """The image list the updated app comes back with."""
    doc = json.loads(open(settings_file, encoding="utf-8").read())
    return rows_from_state((doc.get("multiboot_state") or {}).get("images"))


# ---------------------------------------------------------------------------
# Windows: the silent installer
# ---------------------------------------------------------------------------

def test_the_session_is_on_disk_before_the_installer_is_started(monkeypatch,
                                                                tmp_path):
    """The installer force-closes this process as soon as its copy starts, so
    "we exit cleanly and that saves settings" is a race unless the save is
    already done when it is handed the exe."""
    app = _App(tmp_path / "settings.json", state=_his_form())
    monkeypatch.setattr(app_mod, "launch_installer_windows",
                        lambda p: app.order.append("installer") or True)
    app._launch_downloaded_installer(_Dialog(), "C:\\Temp\\setup.exe", "9.0.0")
    assert app.order.index("settings") < app.order.index("installer")


@pytest.mark.parametrize("kill_at", ["preview", "emulators"])
def test_a_force_closed_update_still_has_his_random_card(monkeypatch, tmp_path,
                                                         kill_at):
    """His report, end to end: the updated app reads back all three rows.

    Killed at either of the two steps the old quit did BEFORE it saved - the
    ffplay stop, and the wsl.exe emulator shutdown that can take tens of
    seconds."""
    settings = tmp_path / "settings.json"
    app = _App(settings, kill_at=kill_at, state=_his_form())
    monkeypatch.setattr(app_mod, "launch_installer_windows", lambda p: True)
    with pytest.raises(_ForceClosed):
        app._launch_downloaded_installer(
            _Dialog(), "C:\\Temp\\setup.exe", "9.0.0")
    rows = _restored(settings)
    assert [r.title for r in rows] == ["GODZILLA", "JAWS", "RANDOM"]
    assert is_group(rows[2]) and len(rows[2].members) == 2


def test_an_installer_that_will_not_start_has_still_saved(monkeypatch,
                                                          tmp_path):
    """Nothing is lost by saving early when the update then does not happen:
    the app stays open and this is an ordinary write of the same state."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(app_mod, "launch_installer_windows", lambda p: False)
    monkeypatch.setattr(app_mod.messagebox, "showerror", lambda *a, **k: None)
    app = _App(settings, state=_his_form())
    app._launch_downloaded_installer(_Dialog(), "C:\\Temp\\setup.exe", "9.0.0")
    assert app.order == ["settings"]
    assert [r.title for r in _restored(settings)] == \
        ["GODZILLA", "JAWS", "RANDOM"]


# ---------------------------------------------------------------------------
# Every quit
# ---------------------------------------------------------------------------

def test_an_ordinary_quit_writes_the_state_before_the_shutdown(tmp_path):
    """Not only the update's quit.  Nothing the shutdown does changes what the
    save writes, so there is no reason for the save to wait behind it."""
    app = _App(tmp_path / "settings.json", state=_his_form())
    app._on_close()
    assert app.order == ["settings", "preview", "emulators", "close", "cancel"]


def test_a_state_write_that_raises_does_not_stop_the_close(tmp_path):
    """A NAS hiccup on the way out must not leave the window standing - and
    now that this runs FIRST, it must not stop the emulators being taken down
    either."""
    app = _App(tmp_path / "settings.json", boom=True)
    app._on_close()
    assert app.order == ["settings", "preview", "emulators", "close", "cancel"]


# ---------------------------------------------------------------------------
# Linux: the successor AppImage
# ---------------------------------------------------------------------------

def test_the_appimage_successor_starts_after_the_state_is_written(monkeypatch,
                                                                  tmp_path):
    """The Linux update is the same race from the other end: nothing kills
    this process, but the new AppImage reads settings.json the moment it opens
    - while this one is still taking the emulators down."""
    path = tmp_path / "PAD_v9.0.0_Linux_x86_64.AppImage"
    path.write_bytes(b"not really an AppImage")
    settings = tmp_path / "settings.json"
    app = _App(settings, state=_his_form())
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(app_mod.os, "chmod", lambda p, mode: None)
    monkeypatch.setattr(
        app_mod.desktop, "run_detached",
        lambda argv: (app.order.append("successor"), (True, ""))[1])
    app._finish_appimage_update(_Dialog(), str(path), "9.0.0")
    assert app.order.index("settings") < app.order.index("successor")
    assert [r.title for r in _restored(settings)] == \
        ["GODZILLA", "JAWS", "RANDOM"]


def test_declining_the_appimage_writes_nothing_and_starts_nothing(monkeypatch,
                                                                  tmp_path):
    """'Not now' is not a hand-off, so it is not a save-point either."""
    path = tmp_path / "PAD_v9.0.0_Linux_x86_64.AppImage"
    path.write_bytes(b"x")
    app = _App(tmp_path / "settings.json", state=_his_form())
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(app_mod.os, "chmod", lambda p, mode: None)
    monkeypatch.setattr(app_mod.desktop, "run_detached",
                        lambda argv: (True, ""))
    app._finish_appimage_update(_Dialog(), str(path), "9.0.0")
    assert app.order == []
