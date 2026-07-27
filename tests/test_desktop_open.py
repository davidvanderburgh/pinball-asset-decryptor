"""Guards for core.desktop -- handing URLs/paths to the desktop.

The bug these exist for: aly's Ubuntu AppImage, where the update
banner's Download button did nothing at all.  A frozen bundle points
LD_LIBRARY_PATH/PATH/PYTHONHOME at itself, any browser started with that
environment dies loading our bundled libs, and ``webbrowser.open``
reports success anyway because Popen returned.  So the two things worth
pinning down are: the child env has the bundle scrubbed out of it, and a
failed launch comes back as False instead of a silent no-op.
"""

import os
import subprocess
import sys

import pytest

from pinball_decryptor.core import desktop


# --- environment scrubbing ---------------------------------------------

def test_orig_value_wins():
    """PyInstaller's own <VAR>_ORIG stash is the pre-freeze truth."""
    env = desktop.desktop_env(
        {"LD_LIBRARY_PATH": "/tmp/.mount_pad/usr/bin",
         "LD_LIBRARY_PATH_ORIG": "/usr/lib/systemd"},
        bundle_dirs=["/tmp/.mount_pad"])
    assert env["LD_LIBRARY_PATH"] == "/usr/lib/systemd"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_empty_orig_removes_the_variable():
    """The var didn't exist before freezing -- it mustn't exist after."""
    env = desktop.desktop_env(
        {"PYTHONHOME": "/tmp/.mount_pad/usr/bin", "PYTHONHOME_ORIG": ""},
        bundle_dirs=["/tmp/.mount_pad"])
    assert "PYTHONHOME" not in env


def test_bundle_entries_dropped_from_path(tmp_path):
    bundle = tmp_path / "mount" / "usr" / "bin"
    bundle.mkdir(parents=True)
    env = desktop.desktop_env(
        {"PATH": os.pathsep.join([str(bundle), "/usr/bin", "/bin"])},
        bundle_dirs=[str(tmp_path / "mount")])
    parts = env["PATH"].split(os.pathsep)
    assert str(bundle) not in parts
    assert "/usr/bin" in parts and "/bin" in parts


def test_bundle_only_variable_is_removed(tmp_path):
    bundle = tmp_path / "mount"
    bundle.mkdir()
    env = desktop.desktop_env(
        {"GDK_PIXBUF_MODULE_FILE": str(bundle / "loaders.cache")},
        bundle_dirs=[str(bundle)])
    assert "GDK_PIXBUF_MODULE_FILE" not in env


def test_path_never_ends_up_empty(tmp_path):
    """Stripping the last PATH entry must not leave a child unable to
    find /usr/bin/xdg-open."""
    bundle = tmp_path / "mount"
    bundle.mkdir()
    env = desktop.desktop_env({"PATH": str(bundle)},
                              bundle_dirs=[str(bundle)])
    assert env["PATH"] == os.defpath


def test_frozen_exe_dir_counts_only_when_frozen(monkeypatch, tmp_path):
    """AppRun prepends AppDir/usr/bin to PATH, so that folder has to be
    scrubbed -- but unfrozen the same expression is the system python's
    /usr/bin, which must survive."""
    exe = tmp_path / "usr" / "bin" / "pinball-decryptor"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("APPDIR", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert str(exe.parent) in desktop._bundle_dirs()

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert desktop._bundle_dirs() == []


def test_session_variables_are_left_alone():
    """Anything that never pointed at the bundle is the user's desktop
    session talking -- don't touch it."""
    src = {"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
           "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
    env = desktop.desktop_env(dict(src), bundle_dirs=["/tmp/.mount_pad"])
    for k, v in src.items():
        assert env[k] == v


# --- launch outcome ----------------------------------------------------

class _Proc:
    def __init__(self, rc=0, err=b"", hang=False):
        self.returncode = rc
        self._err = err
        self._hang = hang

    def communicate(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired("cmd", timeout)
        return b"", self._err


def _fake_popen(results, seen):
    """Popen stub driving one outcome per launched program name."""
    def _popen(argv, **kw):
        seen.append(list(argv))
        outcome = results.get(argv[0], _Proc())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return _popen


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop, "_which", lambda prog, env: "/usr/bin/" + prog)


def test_first_working_opener_wins(linux, monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "Popen", _fake_popen({}, seen))
    ok, err = desktop.open_url("https://example.invalid/r")
    assert ok and err == ""
    assert seen == [["xdg-open", "https://example.invalid/r"]]


def test_still_running_counts_as_opened(linux, monkeypatch):
    """xdg-open's generic path blocks for as long as the browser lives."""
    monkeypatch.setattr(subprocess, "Popen",
                        _fake_popen({"xdg-open": _Proc(hang=True)}, []))
    assert desktop.open_url("https://example.invalid/r")[0] is True


def test_failing_opener_falls_through_to_the_next(linux, monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(
        {"xdg-open": _Proc(rc=3, err=b"gio: no application registered")},
        seen))
    ok, _err = desktop.open_url("https://example.invalid/r")
    assert ok is True
    assert [a[0] for a in seen[:2]] == ["xdg-open", "gio"]


def test_every_opener_failing_reports_false(linux, monkeypatch):
    """The whole point: the GUI has to be able to tell it didn't work."""
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(
        {p: _Proc(rc=1, err=b"nope") for p in
         ("xdg-open", "gio", "gvfs-open", "gnome-open", "kde-open5",
          "kde-open", "x-www-browser", "sensible-browser", "firefox",
          "chromium", "chromium-browser", "google-chrome")}, []))
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: False)
    ok, err = desktop.open_url("https://example.invalid/r")
    assert ok is False
    assert err                      # a reason the user can be shown


def test_no_opener_installed_reports_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop, "_which", lambda prog, env: None)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: False)
    ok, err = desktop.open_url("https://example.invalid/r")
    assert ok is False and "opener" in err


def test_stdlib_webbrowser_is_the_last_resort(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop, "_which", lambda prog, env: None)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: True)
    assert desktop.open_url("https://example.invalid/r") == (True, "")


def test_empty_url_is_a_noop(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: pytest.fail("launched for no URL"))
    assert desktop.open_url("")[0] is False
    assert desktop.open_path("")[0] is False


def test_launch_uses_the_scrubbed_env(linux, monkeypatch, tmp_path):
    bundle = tmp_path / "mount"
    bundle.mkdir()
    monkeypatch.setattr(desktop, "_bundle_dirs", lambda: [str(bundle)])
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/x86_64-linux-gnu")
    captured = {}

    def _popen(argv, **kw):
        captured.update(kw.get("env") or {})
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", _popen)
    desktop.open_url("https://example.invalid/r")
    assert captured["LD_LIBRARY_PATH"] == "/usr/lib/x86_64-linux-gnu"


def test_path_opener_list_excludes_browsers(linux, monkeypatch, tmp_path):
    """Handing a folder to firefox isn't a useful fallback."""
    seen = []
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(
        {p: _Proc(rc=1) for p in ("xdg-open", "gio", "gvfs-open",
                                  "gnome-open", "kde-open5", "kde-open",
                                  "nautilus", "dolphin", "thunar", "nemo")},
        seen))
    desktop.open_path(str(tmp_path))
    assert not {"firefox", "chromium", "google-chrome"} & {a[0] for a in seen}


# ---------------------------------------------------------------------------
# run_detached — starting the freshly downloaded AppImage
# ---------------------------------------------------------------------------

def test_run_detached_reports_a_program_that_died(monkeypatch):
    """The whole reason this returns a boolean.  ``webbrowser.open``-style
    optimism is what made the update button look dead for four releases;
    a new AppImage that exits immediately must not read as 'started'."""
    monkeypatch.setattr(subprocess, "Popen",
                        _fake_popen({"/tmp/new.AppImage":
                                     _Proc(rc=127, err=b"no FUSE")}, []))
    ok, err = desktop.run_detached(["/tmp/new.AppImage"])
    assert ok is False and "no FUSE" in err


def test_run_detached_still_running_is_success(monkeypatch):
    """A GUI app that's still alive after the grace period is the app
    running — that IS the success case here, not a hang."""
    monkeypatch.setattr(subprocess, "Popen",
                        _fake_popen({"/tmp/new.AppImage": _Proc(hang=True)},
                                    []))
    assert desktop.run_detached(["/tmp/new.AppImage"]) == (True, "")


def test_run_detached_scrubs_the_bundle_env(monkeypatch, tmp_path):
    """The one program launched this way is the NEW AppImage: handing it
    our PYTHONHOME/LD_LIBRARY_PATH would point the new app at the old
    bundle's interpreter — this module's own failure, self-inflicted."""
    bundle = tmp_path / "mount"
    bundle.mkdir()
    monkeypatch.setattr(desktop, "_bundle_dirs", lambda: [str(bundle)])
    monkeypatch.setenv("PYTHONHOME", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    captured = {}

    def _popen(argv, **kw):
        captured.update({"env": kw.get("env") or {},
                         "session": kw.get("start_new_session")})
        return _Proc(hang=True)

    monkeypatch.setattr(subprocess, "Popen", _popen)
    assert desktop.run_detached(["/tmp/new.AppImage"])[0] is True
    assert "PYTHONHOME" not in captured["env"]
    assert captured["env"]["LD_LIBRARY_PATH"] == "/usr/lib"
    # Detached, or the new app dies with the old one that started it.
    assert captured["session"] is True


def test_run_detached_with_nothing_to_run(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: pytest.fail("launched nothing"))
    assert desktop.run_detached([])[0] is False
