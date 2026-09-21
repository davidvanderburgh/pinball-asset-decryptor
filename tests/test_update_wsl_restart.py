"""PAD-150: an in-app update shuts WSL down as the app closes.

A tester pressed Restart WSL after every in-app update, because the
emulator's game window came up with no picture until he did.  His log from the
first run after one had the VM up 2 minutes - started before the updated app
opened, so carried over from the old one - and the renderer drawing.  The
update now does his restart for him, so the updated app starts a fresh VM.

These run with no WSL and no Tk: the distro listing, the registry and the
shutdown are stood in for.
"""

from pinball_decryptor import app as app_mod
from pinball_decryptor.core import updater, wsl_disk


def _wsl(monkeypatch, running, default="Ubuntu", shutdown_error=None):
    calls = []

    def _shutdown():
        calls.append("shutdown")
        if shutdown_error is not None:
            raise shutdown_error

    monkeypatch.setattr(wsl_disk, "running_distros", lambda: list(running))
    monkeypatch.setattr(wsl_disk, "default_distro_name", lambda: default)
    monkeypatch.setattr(updater, "_wsl_shutdown", _shutdown)
    return calls


# ---------------------------------------------------------------------------
# restart_wsl_for_update
# ---------------------------------------------------------------------------

def test_the_app_distro_alone_is_shut_down(monkeypatch):
    """His machine: Ubuntu is the default and the only thing running."""
    calls = _wsl(monkeypatch, ["Ubuntu"])
    line = updater.restart_wsl_for_update(platform="win32")
    assert calls == ["shutdown"]
    assert line.startswith("Shut WSL down for the update")


def test_our_runtime_counts_as_ours(monkeypatch):
    calls = _wsl(monkeypatch, ["PAD-Runtime", "Ubuntu"])
    updater.restart_wsl_for_update(platform="win32")
    assert calls == ["shutdown"]


def test_distro_names_compare_without_case(monkeypatch):
    """WSL treats distro names case-insensitively; so must this, or a
    lower-cased listing would read as somebody else's Linux."""
    calls = _wsl(monkeypatch, ["ubuntu", "pad-runtime"], default="Ubuntu")
    updater.restart_wsl_for_update(platform="win32")
    assert calls == ["shutdown"]


def test_someone_elses_distro_keeps_wsl_running(monkeypatch):
    """`wsl --shutdown` stops every distro.  Docker Desktop's is not ours to
    stop, so WSL is left alone and the line says how to do it by hand."""
    calls = _wsl(monkeypatch, ["Ubuntu", "docker-desktop"])
    line = updater.restart_wsl_for_update(platform="win32")
    assert calls == []
    assert "docker-desktop is running" in line
    assert "Restart WSL" in line


def test_nothing_running_is_nothing_to_restart(monkeypatch):
    calls = _wsl(monkeypatch, [])
    assert updater.restart_wsl_for_update(platform="win32") is None
    assert calls == []


def test_a_failed_shutdown_says_so_and_how_to_do_it(monkeypatch):
    calls = _wsl(monkeypatch, ["Ubuntu"],
                 shutdown_error=OSError("wsl.exe not found"))
    line = updater.restart_wsl_for_update(platform="win32")
    assert calls == ["shutdown"]
    assert "wsl.exe not found" in line and "Restart WSL" in line


def test_nothing_happens_off_windows(monkeypatch):
    asked = []
    monkeypatch.setattr(wsl_disk, "running_distros",
                        lambda: asked.append(1) or ["Ubuntu"])
    monkeypatch.setattr(updater, "_wsl_shutdown", lambda: asked.append(2))
    assert updater.restart_wsl_for_update(platform="linux") is None
    assert asked == []


# ---------------------------------------------------------------------------
# wsl_disk.running_distros
# ---------------------------------------------------------------------------

class _Proc:
    def __init__(self, text, returncode=0):
        self.stdout = text.encode("utf-16-le")
        self.returncode = returncode


def _listing(monkeypatch, text, returncode=0, known=None):
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)
    monkeypatch.setattr(wsl_disk.subprocess, "run",
                        lambda *a, **k: _Proc(text, returncode))
    monkeypatch.setattr(wsl_disk, "_lxss_names", lambda: known)


def test_running_distros_reads_the_utf16_listing(monkeypatch):
    _listing(monkeypatch, "\ufeffUbuntu\r\ndocker-desktop\r\n",
             known={"ubuntu", "docker-desktop", "pad-runtime"})
    assert wsl_disk.running_distros() == ["Ubuntu", "docker-desktop"]


def test_the_nothing_running_sentence_is_not_a_distro(monkeypatch):
    """Otherwise it names somebody else's Linux, and the update would leave
    WSL running because a distro called "There are no running..." was up."""
    _listing(monkeypatch, "There are no running distributions.\r\n",
             known={"ubuntu"})
    assert wsl_disk.running_distros() == []


def test_without_the_registry_a_failed_listing_is_empty(monkeypatch):
    _listing(monkeypatch, "There are no running distributions.\r\n",
             returncode=0xFFFFFFFF, known=None)
    assert wsl_disk.running_distros() == []


# ---------------------------------------------------------------------------
# The app: the update asks for it, and the quit does it last
# ---------------------------------------------------------------------------

class _Window:
    def __init__(self, order):
        self.order = order
        self.log = []

    def stop_all_preview_playback(self):
        pass

    def emulate_shutdown(self):
        self.order.append("emulators")

    def append_log(self, text, level="info"):
        self.log.append((level, text))


class _Root:
    def __init__(self, order):
        self.order = order

    def destroy(self):
        self.order.append("destroy")


class _App:
    _on_close = app_mod.App._on_close
    _save_session_state = app_mod.App._save_session_state
    _launch_downloaded_installer = app_mod.App._launch_downloaded_installer
    _restart_wsl_for_update = app_mod.App._restart_wsl_for_update

    def __init__(self):
        self.order = []
        self.window = _Window(self.order)
        self.root = _Root(self.order)
        self._project_path = None

    def _save_settings(self):
        self.order.append("settings")


class _Dialog:
    def close(self):
        pass


def test_installing_an_update_restarts_wsl_after_the_emulators(monkeypatch):
    """After, because the emulators stop through wsl.exe and a stop after the
    shutdown would boot the VM straight back up.

    The two saves in front of it are PAD-188: one before the installer is
    handed the exe at all, and the quit's own - which now leads rather than
    waits behind the shutdown, because the installer force-closes this process
    while that runs."""
    monkeypatch.setattr(app_mod, "launch_installer_windows", lambda p: True)
    monkeypatch.setattr(app_mod, "restart_wsl_for_update",
                        lambda: app.order.append("wsl") or "the WSL line")
    app = _App()
    app._launch_downloaded_installer(_Dialog(), "C:\\Temp\\setup.exe", "9.0.0")
    assert app.order == ["settings", "settings", "emulators", "wsl", "destroy"]
    assert ("info", "the WSL line") in app.window.log


def test_an_ordinary_quit_leaves_wsl_alone(monkeypatch):
    monkeypatch.setattr(app_mod, "restart_wsl_for_update",
                        lambda: app.order.append("wsl"))
    app = _App()
    app._on_close()
    assert "wsl" not in app.order


def test_an_installer_that_will_not_start_restarts_nothing(monkeypatch):
    monkeypatch.setattr(app_mod, "launch_installer_windows", lambda p: False)
    monkeypatch.setattr(app_mod.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "restart_wsl_for_update",
                        lambda: app.order.append("wsl"))
    app = _App()
    app._launch_downloaded_installer(_Dialog(), "C:\\Temp\\setup.exe", "9.0.0")
    # The save in front of the launch stands whether or not the launch works
    # (PAD-188); nothing else in the quit happened, which is the point here.
    assert app.order == ["settings"]
    assert not getattr(app, "_restart_wsl_on_close", False)


def test_a_restart_that_raises_does_not_stop_the_quit(monkeypatch):
    def _boom():
        raise RuntimeError("no")

    monkeypatch.setattr(app_mod, "restart_wsl_for_update", _boom)
    app = _App()
    app._restart_wsl_on_close = True
    app._on_close()
    assert app.order[-1] == "destroy"
