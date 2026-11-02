"""PAD-937: old versions of the app that updates leave behind.

A Linux update saves the new AppImage beside the old one and keeps the old
one, so they piled up one per release; Settings > Updates > Old versions now
picks how many to keep.  Windows setup exes and macOS disk images in the temp
folder are throwaway and go at startup without asking.  Never the running
AppImage, never anything newer than the running version, never a file that
isn't named like a release asset.
"""

import json
import os
import time

import pytest

from pinball_decryptor.core import old_versions as ov
from tests.webui_harness import web_app

LINUX = "Pinball_Asset_Decryptor_v%s_Linux_x86_64.AppImage"
WIN = "Pinball_Asset_Decryptor_v%s_Windows.exe"
MAC = "Pinball_Asset_Decryptor_v%s_macOS_AppleSilicon.dmg"


def _make(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"x")
    return folder


def _left(folder):
    return sorted(os.listdir(folder))


@pytest.mark.parametrize("stored, want", [
    (None, -1), ("", -1), ("all", -1), (7, -1), (2, -1),
    (-1, -1), (0, 0), ("0", 0), (1, 1), (3, 3)])
def test_the_stored_pick_normalises(stored, want):
    assert ov.normalize_old_versions(stored) == want
    assert ov.OLD_VERSIONS_DEFAULT in dict(ov.OLD_VERSIONS_CHOICES)


@pytest.mark.parametrize("keep, kept", [
    (-1, ["1.300.0", "1.310.0", "1.315.2"]),
    (3, ["1.300.0", "1.310.0", "1.315.2"]),
    (1, ["1.315.2"]),
    (0, []),
])
def test_appimages_beyond_the_pick_go(tmp_path, keep, kept):
    old = ["1.300.0", "1.310.0", "1.315.2"]
    d = _make(tmp_path / "apps", *[LINUX % v for v in old],
              LINUX % "1.316.5", LINUX % "1.317.0", "notes.txt",
              "Pinball_Asset_Decryptor_v1.200.0_Windows.exe")
    cur = str(d / (LINUX % "1.316.5"))
    deleted, failed = ov.prune_old_appimages(cur, "1.316.5", keep,
                                             folders=[str(d)])
    assert not failed
    assert len(deleted) == len(old) - len(kept)
    # the running one, a newer download and other files always stay
    assert _left(d) == sorted([LINUX % v for v in kept] + [
        LINUX % "1.316.5", LINUX % "1.317.0", "notes.txt",
        "Pinball_Asset_Decryptor_v1.200.0_Windows.exe"])


def test_versions_sort_as_numbers_not_text(tmp_path):
    d = _make(tmp_path, LINUX % "1.99.0", LINUX % "1.100.0",
              LINUX % "1.316.5")
    cur = str(d / (LINUX % "1.316.5"))
    ov.prune_old_appimages(cur, "1.316.5", 1, folders=[str(d)])
    assert _left(d) == [LINUX % "1.100.0", LINUX % "1.316.5"]


def test_keep_counts_across_the_update_folders(tmp_path):
    """An update lands beside the running AppImage, else in ~/Downloads or
    ~ (App._update_download_dir), so all three are looked in and the keep
    count is over them together."""
    home = tmp_path / "home"
    apps = _make(home / "Apps", LINUX % "1.316.5", LINUX % "1.310.0")
    _make(home / "Downloads", LINUX % "1.315.0", LINUX % "1.200.0")
    _make(home, LINUX % "1.250.0")
    cur = str(apps / (LINUX % "1.316.5"))
    folders = ov.appimage_folders(cur, home=str(home))
    assert folders == [str(apps), str(home / "Downloads"), str(home)]
    deleted, _ = ov.prune_old_appimages(cur, "1.316.5", 1, folders=folders)
    assert sorted(os.path.basename(p) for p in deleted) == sorted(
        [LINUX % "1.310.0", LINUX % "1.200.0", LINUX % "1.250.0"])
    assert _left(home / "Downloads") == [LINUX % "1.315.0"]


def test_not_an_appimage_keeps_everything(tmp_path):
    d = _make(tmp_path, LINUX % "1.0.0")
    assert ov.prune_old_appimages("", "1.316.5", 0,
                                  folders=[str(d)]) == ([], [])
    assert _left(d) == [LINUX % "1.0.0"]
    assert ov.running_appimage({}) == ""
    assert ov.running_appimage({"APPIMAGE": "/a/b.AppImage"}) == \
        "/a/b.AppImage"


def test_old_installers_in_temp_go(tmp_path):
    d = _make(tmp_path, WIN % "1.268.0", WIN % "1.316.4", WIN % "1.316.5",
              WIN % "1.317.0", MAC % "1.300.0", LINUX % "1.300.0",
              "something_else.exe")
    deleted, failed = ov.prune_old_installers("1.316.5", folder=str(d))
    assert not failed
    assert sorted(os.path.basename(p) for p in deleted) == sorted(
        [WIN % "1.268.0", WIN % "1.316.4", MAC % "1.300.0"])
    assert _left(d) == sorted([WIN % "1.316.5", WIN % "1.317.0",
                               LINUX % "1.300.0", "something_else.exe"])


def test_an_unreadable_version_touches_nothing(tmp_path):
    d = _make(tmp_path, WIN % "1.0.0")
    assert ov.prune_old_installers("dev", folder=str(d)) == ([], [])
    assert _left(d) == [WIN % "1.0.0"]


# ------------------------------------------------------------ the gear menu
def _rows(w):
    for it in w.state("shell")["settings_items"]:
        if it.get("label") == "Updates":
            return it["submenu"]
    raise AssertionError("no Updates submenu")


def test_the_menu_asks_only_an_appimage(tmp_path, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    with web_app(tmp_path, mfr="stern") as w:
        assert not [r for r in _rows(w) if r.get("id") == "old_versions"]
        assert {"header": "Old versions"} not in _rows(w)


def test_picking_saves_and_clears_now(tmp_path, monkeypatch):
    from pinball_decryptor import __version__
    apps = _make(tmp_path / "apps", LINUX % "1.0.0", LINUX % "1.0.1",
                 LINUX % __version__)
    cur = str(apps / (LINUX % __version__))
    monkeypatch.setenv("APPIMAGE", cur)
    monkeypatch.setattr(ov, "appimage_folders", lambda c, home=None: [
        str(apps)])
    with web_app(tmp_path, mfr="stern") as w:
        rows = [r for r in _rows(w) if r.get("id") == "old_versions"]
        assert [r["label"] for r in rows] == [
            label for _k, label in ov.OLD_VERSIONS_CHOICES]
        assert [r["args"] for r in rows if r["checked"]] == [[-1]]
        assert all(r["radio"] and r["title"] == ov.OLD_VERSIONS_TIP
                   for r in rows)
        w.call("ui.settings_action", "old_versions", 0)
        assert w.window.old_versions_var.get() == 0
        cfg = json.loads((tmp_path / "cfg" / "settings.json").read_text(
            encoding="utf-8"))
        assert cfg["old_versions_keep"] == 0
        assert [r["args"] for r in _rows(w)
                if r.get("id") == "old_versions" and r["checked"]] == [[0]]
        end = time.time() + 10
        while time.time() < end and len(os.listdir(apps)) > 1:
            time.sleep(0.05)
        assert _left(apps) == [LINUX % __version__]
        texts = []
        while time.time() < end:
            w.drain()
            texts = [e["text"] for e in w.window.log_history()]
            if sum("Deleted an old version of PAD" in t for t in texts) == 2:
                break
            time.sleep(0.05)
        assert "Old versions of PAD: delete them." in texts
        assert sum("Deleted an old version of PAD" in t for t in texts) == 2


def test_a_saved_pick_comes_back(tmp_path, monkeypatch):
    monkeypatch.setenv("APPIMAGE", str(tmp_path / (LINUX % "9.9.9")))
    with web_app(tmp_path, mfr="stern",
                 settings={"old_versions_keep": 1}) as w:
        assert w.window.old_versions_var.get() == 1
        assert [r["args"] for r in _rows(w)
                if r.get("id") == "old_versions" and r["checked"]] == [[1]]
