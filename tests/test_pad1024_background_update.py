"""PAD-1024: updates download in the background, then one click restarts.

daveyvandy: "One button push to restart the app and it quickly loads the new
version.  Background downloads / installs to speed things up.  Opt-out
controls for the nerds who don't want this amazingness."

The install was already one silent step; the wait was the download window in
front of it.  Now the check fetches the update as soon as it finds one, the
banner says so while it runs, and its one button is Restart to update, which
goes straight to the install.  ⚙ Updates > Download updates in the background
switches it off, and the update then waits for Install update as before.

Nothing here touches the network or runs an installer: the download and the
launch are stand-ins, and the files land in ``tmp_path``.
"""

import hashlib
import json
import os
import time

import pytest

from pinball_decryptor.core import old_versions as ov
from pinball_decryptor.core import updater
from tests.webui_harness import web_app

WIN = "Pinball_Asset_Decryptor_v%s_Windows.exe"
PAYLOAD = b"new version " * 1000
URL = "https://example.invalid/s.exe"


def _installer(**extra):
    inst = {"name": WIN % "9.9.9", "url": "https://example.invalid/s.exe",
            "size": len(PAYLOAD),
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "kind": "windows-installer"}
    inst.update(extra)
    return inst


class _Resp:
    def __init__(self, data):
        self._data, self._pos = data, 0

    def read(self, n=-1):
        chunk = self._data[self._pos:self._pos + (n if n > 0 else None or
                                                  len(self._data))]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ------------------------------------------------------------ core/updater
def test_download_lands_whole_or_not_at_all(tmp_path):
    """The bytes go to <dest>.part and only a verified file takes the real
    name: an app closed mid-download leaves nothing that looks finished."""
    dest = tmp_path / (WIN % "9.9.9")
    seen = []

    def _progress(done):
        seen.append((done, dest.exists(),
                     os.path.exists(str(dest) + updater.PART_SUFFIX)))
    updater.download_installer(URL, dest, progress_cb=_progress,
                               opener=lambda req, timeout: _Resp(PAYLOAD))
    assert dest.read_bytes() == PAYLOAD
    assert not os.path.exists(str(dest) + updater.PART_SUFFIX)
    assert seen and all(not final and part for _d, final, part in seen)

    bad = tmp_path / "bad.exe"
    with pytest.raises(ValueError):
        updater.download_installer(URL, bad, expected_sha256="0" * 64,
                                   opener=lambda req, timeout: _Resp(PAYLOAD))
    assert not bad.exists()
    assert not os.path.exists(str(bad) + updater.PART_SUFFIX)


def test_staged_update_ok_checks_size_and_digest(tmp_path):
    p = tmp_path / (WIN % "9.9.9")
    assert not updater.staged_update_ok(str(p), _installer())
    p.write_bytes(PAYLOAD)
    assert updater.staged_update_ok(str(p), _installer())
    p.write_bytes(PAYLOAD[:-1] + b"X")              # same size, other bytes
    assert not updater.staged_update_ok(str(p), _installer())
    assert updater.staged_update_ok(str(p), _installer(), check_digest=False)
    p.write_bytes(PAYLOAD[:10])
    assert not updater.staged_update_ok(str(p), _installer(),
                                        check_digest=False)
    # nothing published to check against: the file being there is enough
    assert updater.staged_update_ok(str(p), _installer(size=0, sha256=None))


def test_old_partial_downloads_are_pruned(tmp_path):
    for n in (WIN % "1.0.0" + ".part", WIN % "9.9.9" + ".part",
              WIN % "1.0.0"):
        (tmp_path / n).write_bytes(b"x")
    deleted, failed = ov.prune_old_installers("2.0.0", folder=str(tmp_path))
    assert not failed
    assert sorted(os.path.basename(p) for p in deleted) == sorted(
        [WIN % "1.0.0" + ".part", WIN % "1.0.0"])
    assert os.listdir(tmp_path) == [WIN % "9.9.9" + ".part"]


# ------------------------------------------------------------ the app
def _until(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _banner(w):
    return {b["id"]: b for b in w.state("shell")["banners"]}.get("update")


def _rows(w):
    for it in w.state("shell")["settings_items"]:
        if it.get("label") == "Updates":
            return it["submenu"]
    raise AssertionError("no Updates submenu")


def _toggle_row(w):
    return [r for r in _rows(w)
            if r.get("id") == "toggle_update_auto_download"][0]


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Downloads into tmp_path/dl through a stand-in, held until released;
    the install hand-off and the quit only record."""
    import threading
    from pinball_decryptor import app as app_mod
    dl = tmp_path / "dl"
    dl.mkdir()
    gate = threading.Event()
    rec = {"downloads": [], "launched": [], "closed": 0, "gate": gate,
           "dir": dl, "checks": [], "feed": None, "publishing": None}

    def _download(url, dest, expected_sha256=None, progress_cb=None,
                  cancel_cb=None, opener=None):
        rec["downloads"].append(str(dest))
        if progress_cb:
            progress_cb(len(PAYLOAD) // 2)
        while not gate.wait(0.05):
            if cancel_cb and cancel_cb():
                raise InterruptedError("download canceled")
        with open(dest, "wb") as f:
            f.write(PAYLOAD)
        return len(PAYLOAD)

    monkeypatch.setattr(app_mod, "download_installer", _download)
    monkeypatch.setattr(app_mod, "launch_installer_windows",
                        lambda path: rec["launched"].append(str(path)) or True)
    monkeypatch.setattr(app_mod.App, "_update_download_dir",
                        lambda self, inst: str(dl))

    def _close(self):
        rec["closed"] += 1
    monkeypatch.setattr(app_mod.App, "_on_close", _close)

    def _no_recheck(self, version, installer):
        raise AssertionError("Restart to update must not re-check")
    monkeypatch.setattr(app_mod.App, "_freshest_update", _no_recheck)

    def _check(current, repo=None, not_ready_cb=None):
        """The release feed Restart to update asks: rec["feed"] (a result,
        an exception, or None), and rec["publishing"] still uploading."""
        rec["checks"].append(current)
        if isinstance(rec["feed"], Exception):
            raise rec["feed"]
        if rec["publishing"] and not_ready_cb:
            not_ready_cb(rec["publishing"])
        return rec["feed"]
    monkeypatch.setattr(app_mod, "check_for_update", _check)
    return rec


def test_found_update_downloads_then_restart_installs_it(tmp_path, staged):
    with web_app(tmp_path, mfr="stern") as w:
        assert _toggle_row(w)["checked"]              # on by default
        w.run(w.app._handle_update_check_result,
              ("9.9.9", "https://example.invalid/r", "notes", _installer()),
              False)
        assert _until(w, lambda: staged["downloads"])
        assert _until(w, lambda: "50%" in (_banner(w) or {}).get("text", ""))
        b = _banner(w)
        assert "downloading in the background (50%)" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Release notes"]
        assert w.state("shell")["update"]["label"] == "Downloading v9.9.9… 50%"
        # pressing the chip mid-download does nothing yet
        w.call("ui.settings_action", "install_update")
        assert not staged["launched"]

        staged["gate"].set()
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get("text", ""))
        b = _banner(w)
        assert "v9.9.9 is ready" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Restart to update",
                                                      "Release notes"]
        assert w.state("shell")["update"]["label"] == "Restart to update"
        top = w.state("shell")["settings_items"][0]
        assert top["label"] == "Restart to update to v9.9.9"

        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: staged["closed"])
        dest = str(staged["dir"] / (WIN % "9.9.9"))
        assert staged["launched"] == [dest]
        assert staged["downloads"] == [dest]          # fetched once only
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Downloading v9.9.9 in the background" in t for t in texts)
        assert any("Restarting to update to v9.9.9" in t for t in texts)


def test_a_copy_from_an_earlier_run_is_reused(tmp_path, staged):
    """Quit instead of restarting: the next run finds the whole file and
    offers Restart to update without fetching it again."""
    (staged["dir"] / (WIN % "9.9.9")).write_bytes(PAYLOAD)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get("text", ""))
        assert staged["downloads"] == []
        texts = [e["text"] for e in w.window.log_history()]
        assert any("already downloaded" in t for t in texts)


def test_a_damaged_copy_is_fetched_again(tmp_path, staged):
    (staged["dir"] / (WIN % "9.9.9")).write_bytes(b"half")
    staged["gate"].set()
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get("text", ""))
        assert len(staged["downloads"]) == 1


def test_switched_off_the_update_waits_for_install(tmp_path, staged):
    with web_app(tmp_path, mfr="stern",
                 settings={"update_auto_download": False}) as w:
        assert not _toggle_row(w)["checked"]
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        w.drain()
        b = _banner(w)
        assert [a["label"] for a in b["actions"]] == ["Install update",
                                                      "Release notes"]
        time.sleep(0.3)
        assert staged["downloads"] == []
        # switching it on starts the download for the update on offer
        w.call("ui.settings_action", "toggle_update_auto_download")
        cfg = json.loads((tmp_path / "cfg" / "settings.json").read_text(
            encoding="utf-8"))
        assert cfg["update_auto_download"] is True
        assert _toggle_row(w)["checked"]
        assert _until(w, lambda: staged["downloads"])
        assert "downloading" in _banner(w)["text"]
        # and off again stops it, back to Install update
        w.call("ui.settings_action", "toggle_update_auto_download")
        w.drain()
        cfg = json.loads((tmp_path / "cfg" / "settings.json").read_text(
            encoding="utf-8"))
        assert cfg["update_auto_download"] is False
        assert [a["label"] for a in _banner(w)["actions"]] == [
            "Install update", "Release notes"]
        time.sleep(0.3)
        assert not (staged["dir"] / (WIN % "9.9.9")).exists()


def test_a_failed_download_falls_back_to_install(tmp_path, staged,
                                                 monkeypatch):
    from pinball_decryptor import app as app_mod

    def _fails(*a, **k):
        raise OSError("connection reset")
    monkeypatch.setattr(app_mod, "download_installer", _fails)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "Install update" in [
            a["label"] for a in (_banner(w) or {}).get("actions", [])])
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Couldn't download v9.9.9 in the background" in t
                   and "connection reset" in t for t in texts)


def test_a_newer_release_replaces_the_one_downloading(tmp_path, staged):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: len(staged["downloads"]) == 1)
        newer = _installer(name=WIN % "9.9.10")
        w.run(w.app._offer_update, "9.9.10", "u2", newer)
        assert _until(w, lambda: len(staged["downloads"]) == 2)
        # the same version found again by the repeating check starts nothing
        w.run(w.app._offer_update, "9.9.10", "u2", newer)
        staged["gate"].set()
        assert _until(w, lambda: "v9.9.10 is ready" in (
            _banner(w) or {}).get("text", ""))
        assert len(staged["downloads"]) == 2


# ------------------------------------------------------------ blue-green
# The real setup exe and swap helper are proven end to end by
# scripts/e2e_pad1024_blue_green.py (it needs Inno Setup and a built Python
# bundle); these pin the pieces that need neither.
from pinball_decryptor.core import update_slots as us   # noqa: E402


def _tree(root, version, site=(), extra=()):
    """A stand-in install: the files a whole one has, plus *site* entries
    in site-packages and *extra* top-level files."""
    for rel in ("python/pythonw.exe", "python/python.exe", "launcher.vbs",
                "Pinball Asset Decryptor.pyw"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    init = root / "pinball_decryptor" / "__init__.py"
    init.parent.mkdir(parents=True, exist_ok=True)
    init.write_text('__version__ = "%s"\n' % version, encoding="utf-8")
    sp = root / "python" / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    for name in site:
        (sp / name).mkdir()
        (sp / name / "f.py").write_text("x", encoding="utf-8")
    for name in extra:
        (root / name).write_bytes(b"u")
    return root


def test_installed_app_dir_only_for_a_real_install(tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0")
    exe = str(app / "python" / "pythonw.exe")
    assert us.installed_app_dir(exe, platform="win32") is None   # no unins
    (app / "unins000.exe").write_bytes(b"u")
    assert us.installed_app_dir(exe, platform="win32") == str(app)
    assert us.installed_app_dir(exe, platform="darwin") is None
    # a source checkout's interpreter is not under <app>\python
    assert us.installed_app_dir(str(tmp_path / "Python314" / "pythonw.exe"),
                                platform="win32") is None


def test_carry_over_keeps_what_pip_added_and_never_downgrades(tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0",
                site=("faster_whisper", "faster_whisper-1.0.dist-info",
                      "numpy", "numpy-1.0.dist-info"),
                extra=("unins000.exe", "unins000.dat"))
    (app / "python" / "Scripts").mkdir()
    (app / "python" / "Scripts" / "ct2.exe").write_bytes(b"s")
    new = _tree(tmp_path / "PAD.next", "9.9.9",
                site=("numpy", "numpy-2.0.dist-info"))
    (new / "python" / "Scripts").mkdir()
    got = sorted(us.carry_over(str(app), str(new)))
    sp = os.path.join("python", "Lib", "site-packages")
    assert got == sorted([
        "unins000.dat", "unins000.exe",
        os.path.join(sp, "faster_whisper"),
        os.path.join(sp, "faster_whisper-1.0.dist-info"),
        os.path.join("python", "Scripts", "ct2.exe")])
    # the bundle's newer numpy stands; the old dist-info is not added to it
    left = sorted(os.listdir(new / "python" / "Lib" / "site-packages"))
    assert "numpy-1.0.dist-info" not in left and "numpy-2.0.dist-info" in left


def test_staged_install_needs_the_marker_and_the_version(tmp_path):
    app = str(tmp_path / "PAD")
    nxt = _tree(tmp_path / "PAD.next", "9.9.9")
    assert not us.staged_install_ok(app, "9.9.9")          # no marker yet
    (nxt / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    assert us.staged_install_ok(app, "9.9.9")
    assert not us.staged_install_ok(app, "9.9.10")
    (nxt / "launcher.vbs").unlink()
    assert not us.staged_install_ok(app, "9.9.9")


class _Run:
    def __init__(self, code=0, make=None, raises=None):
        self.code, self.make, self.raises, self.calls = code, make, raises, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.raises:
            raise self.raises
        if self.make and isinstance(cmd, str) and "/STAGED=1" in cmd:
            self.make()
        return type("R", (), {"returncode": self.code})()


def _elevation_error():
    e = OSError("The requested operation requires elevation")
    e.winerror = 740
    return e


def test_stage_install_runs_the_setup_staged_and_carries(tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0", site=("extra",),
                extra=("unins000.exe",))
    run = _Run(make=lambda: _tree(tmp_path / "PAD.next", "9.9.9"))
    ok, carried = us.stage_install("C:/dl/setup.exe", str(app), "9.9.9",
                                   run=run)
    assert ok, carried
    setup_cmd = run.calls[0]
    assert setup_cmd.startswith('"C:/dl/setup.exe" ')
    assert "/STAGED=1" in setup_cmd and "/VERYSILENT" in setup_cmd
    assert '/DIR="%s"' % us.next_dir(str(app)) in setup_cmd
    assert "!runprereqs" in setup_cmd and "!desktopicon" in setup_cmd
    assert any("icacls" in str(c) for c in run.calls[1:])     # ACL repair
    assert "unins000.exe" in carried
    assert us.staged_install_ok(str(app), "9.9.9")


@pytest.mark.parametrize("run, says", [
    (_Run(code=2), "code 2"),
    (_Run(raises=_elevation_error()), "administrator"),
    (_Run(), "no "),                       # exit 0 but nothing installed
])
def test_a_failed_stage_leaves_nothing(tmp_path, run, says):
    app = _tree(tmp_path / "PAD", "1.0.0")
    ok, why = us.stage_install("s.exe", str(app), "9.9.9", run=run)
    assert not ok and says in why
    assert not os.path.exists(us.next_dir(str(app)))


def test_the_wrong_version_staged_is_refused(tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0")
    run = _Run(make=lambda: _tree(tmp_path / "PAD.next", "9.9.8"))
    ok, why = us.stage_install("s.exe", str(app), "9.9.9", run=run)
    assert not ok and "v9.9.8" in why
    assert not os.path.exists(us.next_dir(str(app)))


def test_clear_leftovers(tmp_path):
    app = str(tmp_path / "PAD")
    _tree(tmp_path / "PAD.old", "0.9.0")
    nxt = _tree(tmp_path / "PAD.next", "1.0.0")
    (nxt / us.MARKER).write_text('{"version": "1.0.0"}', encoding="utf-8")
    deleted, failed = us.clear_leftovers(app, "1.0.0")
    assert not failed
    assert sorted(deleted) == sorted([us.old_dir(app), us.next_dir(app)])
    # a staged NEWER version is kept for Restart to update
    nxt = _tree(tmp_path / "PAD.next", "2.0.0")
    (nxt / us.MARKER).write_text('{"version": "2.0.0"}', encoding="utf-8")
    assert us.clear_leftovers(app, "1.0.0") == ([], [])


def test_swap_script_says_what_it_does():
    s = us.swap_script("C:\\Program Files\\Pinball Asset Decryptor", "9.9.9",
                       "C:\\Temp\\it's setup.exe", 1234, "C:\\Temp\\swap.log")
    assert "Wait-Process -Id 1234" in s
    assert "'C:\\Program Files\\Pinball Asset Decryptor.next'" in s
    assert "'C:\\Program Files\\Pinball Asset Decryptor.old'" in s
    assert "'C:\\Temp\\it''s setup.exe'" in s           # quoted for PS
    assert "/FORCECLOSEAPPLICATIONS" in s and "/RELAUNCH=1" in s
    assert "InstallLocation" in s                       # only its own entry
    assert "if ($true) {" in s and "launcher.vbs" in s
    quiet = us.swap_script("C:\\a", "9.9.9", "", 1, "l", launch=False,
                           register=False)
    assert "if ($true)" not in quiet


# ------------------------------------------------------------ app: staging
@pytest.fixture
def slots(tmp_path, staged, monkeypatch):
    """The ``staged`` stand-ins plus an installed copy whose background
    install and swap only record."""
    from pinball_decryptor import app as app_mod
    app_dir = str(tmp_path / "PAD")
    rec = dict(staged, stages=[], swaps=[], stage_ok=True, saved=0)
    rec["gate"].set()
    monkeypatch.setattr(us, "installed_app_dir", lambda *a, **k: app_dir)

    def _stage(setup, app, version, run=None, cancel_cb=None,
               progress_cb=None):
        rec["stages"].append((setup, app, version))
        if not rec["stage_ok"]:
            return False, "the installer stopped with code 5"
        nxt = _tree(tmp_path / "PAD.next", version)
        (nxt / us.MARKER).write_text('{"version": "%s"}' % version,
                                     encoding="utf-8")
        return True, []
    monkeypatch.setattr(us, "stage_install", _stage)

    def _swap(app, version, setup, **k):
        rec["swaps"].append((app, version, setup))
        return True, "log"
    monkeypatch.setattr(us, "start_swap", _swap)
    real_save = app_mod.App._save_session_state

    def _save(self):
        rec["saved"] += 1
        return real_save(self)
    monkeypatch.setattr(app_mod.App, "_save_session_state", _save)
    # the dict copy shares the lists, but the counters must be read here
    staged_close = app_mod.App._on_close

    def _close(self):
        rec["closed"] += 1
        return staged_close(self)
    monkeypatch.setattr(app_mod.App, "_on_close", _close)
    return rec


def _ready(w):
    return "is ready" in (_banner(w) or {}).get("text", "")


def test_installed_copy_installs_in_background_then_swaps(tmp_path, slots):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: _ready(w))
        dest = str(slots["dir"] / (WIN % "9.9.9"))
        assert slots["stages"] == [(dest, str(tmp_path / "PAD"), "9.9.9")]
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Installing v9.9.9 in the background" in t for t in texts)
        assert any("Update v9.9.9 is installed" in t for t in texts)
        saved = slots["saved"]
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        assert slots["swaps"] == [(str(tmp_path / "PAD"), "9.9.9", dest)]
        assert slots["launched"] == []          # no installer: just the swap
        assert slots["saved"] > saved           # state written before it
        assert w.app._restart_wsl_on_close


def test_the_installing_banner(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.window.cb["on_install_update"] = lambda v, inst: None
        w.run(lambda: w.window.show_update_banner(
            "9.9.9", "u", installer=_installer(), stage="installing"))
        b = _banner(w)
        assert "installing in the background" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Release notes"]
        assert w.state("shell")["update"]["label"] == "Installing v9.9.9…"
        top = w.state("shell")["settings_items"][0]
        assert top["disabled"] and "Installing update v9.9.9" in top["label"]


def test_a_failed_background_install_restarts_through_the_installer(
        tmp_path, slots):
    slots["stage_ok"] = False
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: _ready(w))
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Couldn't install v9.9.9 in the background" in t
                   and "code 5" in t for t in texts)
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        assert slots["swaps"] == []
        assert slots["launched"] == [str(slots["dir"] / (WIN % "9.9.9"))]


def test_a_staged_copy_from_an_earlier_run_is_reused(tmp_path, slots):
    (slots["dir"] / (WIN % "9.9.9")).write_bytes(PAYLOAD)
    nxt = _tree(tmp_path / "PAD.next", "9.9.9")
    (nxt / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: _ready(w))
        assert slots["downloads"] == [] and slots["stages"] == []


# ------------------------------------------------------------ several releases
# David: "if I deploy multiple updates, and the user has the app open while
# they are releasing, what happens when they restart? they should get the
# LATEST one, not have to restart multiple times."

def _newer():
    return _installer(name=WIN % "9.9.10")


def _ready_v999(w, staged):
    staged["gate"].set()
    w.run(w.app._offer_update, "9.9.9", "u", _installer())
    assert _until(w, lambda: "v9.9.9 is ready" in (_banner(w) or {}).get(
        "text", ""))


def test_restart_gets_a_release_published_since(tmp_path, staged):
    """9.9.9 is ready, 9.9.10 came out after: one click, one restart, and it
    is into 9.9.10."""
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["feed"] = ("9.9.10", "u2", "notes", _newer())
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: staged["closed"])
        assert staged["closed"] == 1
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.10"))]
        assert staged["downloads"][-1].endswith(WIN % "9.9.10")
        # asked at the click, and again once 9.9.10 was ready
        assert len(staged["checks"]) == 2
        texts = [e["text"] for e in w.window.log_history()]
        assert any("v9.9.10 has been released since v9.9.9" in t
                   for t in texts)


def test_while_the_newer_one_gets_ready_the_banner_says_so(tmp_path, staged):
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["gate"].clear()                  # hold 9.9.10's download
        staged["feed"] = ("9.9.10", "u2", "notes", _newer())
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: "restarts into it by itself" in (
            _banner(w) or {}).get("text", ""))
        b = _banner(w)
        assert "v9.9.10 is downloading" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Don't restart"]
        # Don't restart: it still gets ready, but waits for the click
        w.call("ui.banner_action", "update", "not_now")
        staged["gate"].set()
        assert _until(w, lambda: "v9.9.10 is ready" in (_banner(w) or {}).get(
            "text", ""))
        time.sleep(0.3)
        w.drain()
        assert staged["closed"] == 0 and staged["launched"] == []
        assert [a["label"] for a in _banner(w)["actions"]] == [
            "Restart to update", "Release notes"]


def test_nothing_newer_restarts_into_the_ready_one(tmp_path, staged):
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["feed"] = ("9.9.9", "u", "notes", _installer())
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: staged["closed"])
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.9"))]
        assert len(staged["downloads"]) == 1


def test_offline_at_the_click_still_restarts(tmp_path, staged):
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["feed"] = OSError("no route to host")
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: staged["closed"])
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.9"))]
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Couldn't check for a newer release" in t
                   and "no route to host" in t for t in texts)


def test_a_release_still_being_published_is_waited_for(tmp_path, staged,
                                                       monkeypatch):
    from pinball_decryptor import app as app_mod
    monkeypatch.setattr(app_mod.App, "PUBLISHING_POLL_MS", 200)
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["publishing"] = "9.9.10"         # installers still uploading
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: "still being published" in (
            _banner(w) or {}).get("text", ""))
        assert [a["label"] for a in _banner(w)["actions"]] == [
            "Restart with v9.9.9 now", "Don't restart"]
        assert staged["closed"] == 0
        # its installers land: the next look gets it, then restarts into it
        staged["publishing"] = None
        staged["feed"] = ("9.9.10", "u2", "notes", _newer())
        assert _until(w, lambda: staged["closed"], timeout=15)
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.10"))]


def test_restart_now_skips_the_wait(tmp_path, staged, monkeypatch):
    from pinball_decryptor import app as app_mod
    monkeypatch.setattr(app_mod.App, "PUBLISHING_POLL_MS", 60000)
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["publishing"] = "9.9.10"
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: "still being published" in (
            _banner(w) or {}).get("text", ""))
        w.call("ui.banner_action", "update", "restart_now")
        assert _until(w, lambda: staged["closed"])
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.9"))]


def test_the_publishing_wait_gives_up(tmp_path, staged, monkeypatch):
    from pinball_decryptor import app as app_mod
    monkeypatch.setattr(app_mod.App, "PUBLISHING_POLL_MS", 100)
    monkeypatch.setattr(app_mod.App, "PUBLISHING_WAIT_S", 0.5)
    with web_app(tmp_path, mfr="stern") as w:
        _ready_v999(w, staged)
        staged["publishing"] = "9.9.10"
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: staged["closed"], timeout=15)
        assert staged["launched"] == [str(staged["dir"] / (WIN % "9.9.9"))]
        texts = [e["text"] for e in w.window.log_history()]
        assert any("still being published after" in t for t in texts)
