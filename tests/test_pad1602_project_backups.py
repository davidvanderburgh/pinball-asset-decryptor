"""PAD-1602: the project's Backups folder keeps the last few and skips identical ones.

A Modes or Scenes load over the user's own edits saves them first (PAD-402).  A backup the same
as the newest one is not written twice, only the newest N (10 unless the user picks another in
the load dialog) stay, and a backup the user renamed or a file they put there is never removed.
"""

import json
import os
import time
import zipfile

from pinball_decryptor.core import project_backups as PB
from pinball_decryptor.plugins.stern import mode_project as MP

_STATIC = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                       "webui", "static")


def _zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def _auto(folder, stamp, files, n=None):
    name = "Before loading sam modes %s%s.zip" % (stamp, " (%d)" % n if n else "")
    return _zip(os.path.join(str(folder), name), files)


def test_a_backup_the_same_as_the_newest_is_not_kept(tmp_path):
    first = _auto(tmp_path, "2026-11-20 10.00.00", {"m/a.json": b"1", "m/clip.mp4": b"x" * 500})
    again = _auto(tmp_path, "2026-11-25 09.00.00", {"m/a.json": b"1", "m/clip.mp4": b"x" * 500})
    got = PB.settle(again, keep=10)
    assert got == {"path": first, "same": True, "pruned": []}
    assert not os.path.exists(again) and os.path.exists(first)
    # other contents: kept beside it
    other = _auto(tmp_path, "2026-11-25 09.00.01", {"m/a.json": b"2", "m/clip.mp4": b"x" * 500})
    assert PB.settle(other, keep=10) == {"path": other, "same": False, "pruned": []}
    # the same as an OLDER one only: still kept (the newest is what it is compared with)
    back = _auto(tmp_path, "2026-11-25 09.00.02", {"m/a.json": b"1", "m/clip.mp4": b"x" * 500})
    assert PB.settle(back, keep=10)["same"] is False and os.path.exists(back)


def test_only_the_newest_are_kept_and_never_a_renamed_or_own_file(tmp_path):
    made = [_auto(tmp_path, "2026-11-%02d 12.00.00" % d, {"a": str(d).encode()}) for d in range(1, 13)]
    twin = _auto(tmp_path, "2026-11-12 12.00.00", {"a": b"x"}, n=2)     # same second, " (2)"
    renamed = _zip(str(tmp_path / "Before the big rework.zip"), {"a": b"r"})
    own = _zip(str(tmp_path / "my modes.zip"), {"a": b"o"})
    note = tmp_path / "Before loading notes.txt"
    note.write_text("mine")
    got = PB.settle(twin, keep=3)
    assert got["path"] == twin and not got["same"]
    assert sorted(got["pruned"]) == sorted(os.path.basename(p) for p in made[:10])
    left = sorted(os.listdir(str(tmp_path)))
    assert left == sorted(["Before loading notes.txt", "Before the big rework.zip", "my modes.zip",
                           os.path.basename(made[10]), os.path.basename(made[11]),
                           os.path.basename(twin)])
    assert PB.automatic(str(tmp_path))[0] == twin            # (2) of the same second is newer
    assert os.path.exists(renamed) and os.path.exists(own)


def test_keep_count_setting(tmp_path):
    assert PB.keep_of({}) == PB.KEEP_DEFAULT == 10
    assert PB.keep_of({PB.KEEP_KEY: 3}) == 3
    assert PB.keep_of({PB.KEEP_KEY: 0}) == 1 and PB.keep_of({PB.KEEP_KEY: 999}) == PB.KEEP_MAX
    assert PB.keep_of({PB.KEEP_KEY: "x"}) == PB.KEEP_DEFAULT
    assert PB.is_automatic(os.path.basename(MP.backup_path(str(tmp_path), "sam modes.zip")))
    assert not PB.is_automatic("Before loading a.zip")


def _backups(project):
    d = os.path.join(str(project), MP.BACKUP_DIR)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_modes_loading_over_the_same_edits_again_keeps_one_backup(tmp_path, monkeypatch):
    from pinball_decryptor.core import preview
    from tests.test_webui_modes import _card_project, _project
    from tests.webui_harness import web_app
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    friend = _card_project(tmp_path / "friend", "godzilla_le-1_16_0.raw")
    mine = _card_project(tmp_path / "mine", "godzilla_le-1_16_0.raw")
    zip_path = str(tmp_path / "sam modes.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, friend, card=None)
        assert w.call("modes.example", "TARGET RUSH") == "target_rush"
        w.answers.append(zip_path)
        assert w.call("modes.save_file", "all") == zip_path
        _project(w, mine, card=None)
        w.answers.append(zip_path)
        w.call("modes.load_file")

        def my_edit(seconds, keep=None):
            spec = dict(MP.list_modes(mine)[0])["target_rush"]
            spec.seconds = seconds
            MP.save(mine, "target_rush", spec)
            w.answers.extend([zip_path, dict({"choice": "replace", "backup": True},
                                             **({"keep": keep} if keep else {}))])
            w.call("modes.load_file")
            return w.asked[-2], w.asked[-1]["message"]

        ask, said = my_edit(45)
        assert ask["kind"] == "conflicts" and ask["keep"] == 10 and 10 in ask["keep_choices"]
        (first,) = _backups(mine)
        assert first in said
        # the same edits again, five times over: still the one backup, and the load names it
        for _ in range(5):
            time.sleep(1.05)                      # a new name each time, as a real reload has
            _ask, said = my_edit(45)
            assert _backups(mine) == [first] and first in said
        # other edits: a second one
        time.sleep(1.05)
        my_edit(50)
        assert len(_backups(mine)) == 2
        # keep 1 picked in the dialog: saved, and the folder is down to the newest
        time.sleep(1.05)
        _ask, said = my_edit(55, keep=1)
        (last,) = _backups(mine)
        assert last != first and last in said
        with zipfile.ZipFile(os.path.join(str(mine), MP.BACKUP_DIR, last)) as z:
            assert json.loads(z.read("modes/target_rush/mode.json"))["seconds"] == 55
        assert w.app._settings[PB.KEEP_KEY] == 1
        ask, _said = my_edit(60)
        assert ask["keep"] == 1


def test_scene_backups_skip_twins_and_keep_the_newest(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import scene_share
    project = tmp_path / "p"
    project.mkdir()
    seen = []

    def fake_export(assets_dir, path, cards, trees):
        _zip(path, {"pad_scene_edits.json": json.dumps({"scenes": trees}).encode()})
        seen.append(path)
    monkeypatch.setattr(scene_share, "export_all", fake_export)
    a = scene_share.backup(str(project), "sam scenes.zip", {"x": 1})
    time.sleep(1.05)
    assert scene_share.backup(str(project), "sam scenes.zip", {"x": 1}) == a
    assert _backups(project) == [os.path.basename(a)] and len(seen) == 2
    time.sleep(1.05)
    b = scene_share.backup(str(project), "sam scenes.zip", {"x": 2}, keep=1)
    assert _backups(project) == [os.path.basename(b)]


def test_the_dialog_offers_the_keep_count():
    with open(os.path.join(_STATIC, "js", "core", "dialogs.js"), encoding="utf-8") as f:
        js = f.read()
    assert "spec.keep_choices" in js and '"keep " + n' in js and "...(keep ? { keep } : {})" in js
