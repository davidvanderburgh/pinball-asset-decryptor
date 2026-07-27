"""Linux in-app update: the AppImage download and what happens after it.

aly ran v0.85 through v0.88 and reported the same thing every time --
the update banner's Download button did nothing, no error, nothing.  It
went through the desktop's URL opener, which from inside an AppImage
inherits a bundle environment it can't run in.  v0.86.1 made that
failure honest and it still did nothing, so Linux stopped using a
browser at all: the app fetches the .AppImage itself, marks it
executable and offers to start it.

These run unbound with a stub ``self`` -- no Tk, no network.
"""

import os

import pytest

from pinball_decryptor import app as app_mod


class _Dialog:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Window:
    def __init__(self):
        self.log = []

    def append_log(self, text, level="info"):
        self.log.append((level, text))


class _App:
    _update_download_dir = app_mod.App._update_download_dir
    _update_downloaded = app_mod.App._update_downloaded
    _finish_appimage_update = app_mod.App._finish_appimage_update

    def __init__(self):
        self.window = _Window()
        self.closed = False

    def _on_close(self):
        self.closed = True

    def _launch_downloaded_installer(self, dialog, path, version):
        self.launched_installer = (path, version)


APPIMAGE = {"kind": "appimage", "name": "PAD_v9.0.0_Linux_x86_64.AppImage"}
WINDOWS = {"kind": "windows-installer", "name": "PAD_v9.0.0_Windows.exe"}


# ---------------------------------------------------------------------------
# Where the download lands
# ---------------------------------------------------------------------------

def test_appimage_lands_next_to_the_one_being_run(monkeypatch, tmp_path):
    """That directory is where the user chose to keep the app, so the new
    version turns up beside the old one rather than somewhere they have
    to be told about."""
    here = tmp_path / "apps"
    here.mkdir()
    monkeypatch.setenv("APPIMAGE", str(here / "PAD_v0.86.1_Linux_x86_64.AppImage"))
    assert _App()._update_download_dir(APPIMAGE) == str(here)


def test_appimage_falls_back_to_downloads_when_read_only(monkeypatch, tmp_path):
    """/opt and /usr/local are normal places to keep an AppImage and are
    not writable -- a failed write there must not sink the update."""
    downloads = tmp_path / "home" / "Downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setenv("APPIMAGE", "/opt/pad/PAD.AppImage")
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(tmp_path / "home") if p == "~" else p)
    assert _App()._update_download_dir(APPIMAGE) == str(downloads)


def test_appimage_falls_back_to_home_without_a_downloads_dir(monkeypatch,
                                                             tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(home) if p == "~" else p)
    assert _App()._update_download_dir(APPIMAGE) == str(home)


def test_download_never_lands_on_the_running_appimage(monkeypatch, tmp_path):
    """Only reachable if the user renamed theirs to the incoming name --
    but the download would then truncate the app that is running it."""
    here = tmp_path / "apps"
    here.mkdir()
    downloads = tmp_path / "home" / "Downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setenv("APPIMAGE", str(here / APPIMAGE["name"]))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(tmp_path / "home") if p == "~" else p)
    assert _App()._update_download_dir(APPIMAGE) == str(downloads)


def test_windows_installer_still_goes_to_temp():
    """The setup exe installs itself over the top and is never wanted
    again; keeping it beside the app would just be litter."""
    import tempfile
    assert _App()._update_download_dir(WINDOWS) == tempfile.gettempdir()


def test_missing_kind_is_treated_as_the_windows_installer():
    """Belt and braces for an installer dict from before ``kind`` existed."""
    import tempfile
    assert _App()._update_download_dir({}) == tempfile.gettempdir()


# ---------------------------------------------------------------------------
# After the download
# ---------------------------------------------------------------------------

def _finish(monkeypatch, tmp_path, *, answer=True, launch=(True, "")):
    path = tmp_path / "PAD_v9.0.0_Linux_x86_64.AppImage"
    path.write_bytes(b"not really an AppImage")
    errors = []
    monkeypatch.setattr(app_mod.messagebox, "askyesno",
                        lambda *a, **k: answer)
    monkeypatch.setattr(app_mod.messagebox, "showerror",
                        lambda t, m, **k: errors.append((t, m)))
    monkeypatch.setattr(app_mod.desktop, "run_detached", lambda argv: launch)
    app, dialog = _App(), _Dialog()
    app._finish_appimage_update(dialog, str(path), "9.0.0")
    return app, dialog, path, errors


def test_download_is_made_executable(monkeypatch, tmp_path):
    """An AppImage without the execute bit does nothing when you
    double-click it -- which is the exact complaint being fixed.

    Asserts the chmod call, not the resulting st_mode: this suite runs on
    the Windows dev box too, where os.chmod cannot set an execute bit and
    a mode check would pass vacuously (or fail forever)."""
    chmods = []
    monkeypatch.setattr(app_mod.os, "chmod",
                        lambda p, mode: chmods.append((p, mode)))
    _app, _dialog, path, _errors = _finish(monkeypatch, tmp_path, answer=False)
    assert chmods == [(str(path), 0o755)]


def test_declining_leaves_the_running_app_alone(monkeypatch, tmp_path):
    """'Not now' means not now -- the file is on disk and this window
    keeps working."""
    app, dialog, path, errors = _finish(monkeypatch, tmp_path, answer=False)
    assert dialog.closed and not app.closed and not errors
    assert any(str(path) in text for _lvl, text in app.window.log), (
        "the user is never told where the download went")


def test_accepting_starts_the_new_one_and_closes_this_one(monkeypatch,
                                                          tmp_path):
    launched = []
    monkeypatch.setattr(app_mod.desktop, "run_detached",
                        lambda argv: (launched.append(argv), (True, ""))[1])
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: True)
    path = tmp_path / "new.AppImage"
    path.write_bytes(b"x")
    app = _App()
    app._finish_appimage_update(_Dialog(), str(path), "9.0.0")
    assert launched == [[str(path)]]
    assert app.closed, "the old version stayed open next to the new one"


def test_a_new_version_that_wont_start_says_so(monkeypatch, tmp_path):
    """Failing loudly here is the point -- the silent version of this is
    the bug being fixed."""
    app, _dialog, path, errors = _finish(
        monkeypatch, tmp_path, launch=(False, "exited 127: no FUSE"))
    assert not app.closed, "closed the working app after the new one failed"
    assert errors and "no FUSE" in errors[0][1]
    assert str(path) in errors[0][1], "no path to run it from by hand"


def test_an_unwritable_download_still_offers_to_run(monkeypatch, tmp_path):
    """chmod can fail on a noexec/FAT volume.  Say so, but a file the user
    can still chmod themselves beats aborting the update."""
    path = tmp_path / "new.AppImage"
    path.write_bytes(b"x")

    def _boom(*a, **k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(app_mod.os, "chmod", _boom)
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(app_mod.desktop, "run_detached", lambda argv: (True, ""))
    app = _App()
    app._finish_appimage_update(_Dialog(), str(path), "9.0.0")
    assert any(lvl == "warning" and "chmod" in text
               for lvl, text in app.window.log)
    assert app.closed


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["windows-installer", None])
def test_non_appimage_downloads_go_to_the_installer_path(monkeypatch, kind):
    app = _App()
    app._update_downloaded(_Dialog(), "C:\\Temp\\setup.exe", "9.0.0", kind)
    assert app.launched_installer == ("C:\\Temp\\setup.exe", "9.0.0")
