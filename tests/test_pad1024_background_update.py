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
           "dir": dl}

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
