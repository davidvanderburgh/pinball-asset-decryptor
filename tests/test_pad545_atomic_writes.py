"""PAD-545: the project anchor and settings.json are written atomically.

PAD-541 saves both every few minutes, so a crash or a full disk in the middle
of a write is no longer a one-in-a-quit event.  Writing in place truncated the
file first, so a write that died half-way left a cut-off .pinproj (the folder
stops being a project) or settings.json (every setting gone, the disclaimer
again).  Now the new text goes to a temp file beside it and replaces the old
one only when complete.
"""

import errno
import json
import os
import sys

import pytest

from pinball_decryptor.core import project_file
from tests.webui_harness import web_app


def _disk_full_mid_write(monkeypatch):
    """json.dump writes half the text, then the disk fills up."""
    real = json.dump

    def dump(obj, fh, **kw):
        text = json.dumps(obj, **kw)
        fh.write(text[:len(text) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(json, "dump", dump)
    return real


def _save(folder, notes):
    project_file.save(project_file.anchor_path(folder),
                      manufacturer_key="stern",
                      paths={"extract_output": folder}, extract_options={},
                      notes=notes)


def test_a_write_that_dies_leaves_the_anchor_whole(tmp_path, monkeypatch):
    folder = str(tmp_path)
    _save(folder, "before")
    _disk_full_mid_write(monkeypatch)
    with pytest.raises(OSError):
        _save(folder, "after " * 500)
    assert not project_file.update_anchor(folder, notes="after")
    monkeypatch.undo()
    assert project_file.load_anchor(folder)["notes"] == "before"
    assert os.listdir(folder) == [project_file.ANCHOR_NAME]   # no temp left


def test_the_anchor_is_replaced_and_stays_hidden(tmp_path):
    folder = str(tmp_path)
    _save(folder, "one")
    assert project_file.update_anchor(folder, notes="two", newer_key=1)
    data = project_file.load_anchor(folder)
    assert (data["notes"], data["newer_key"]) == ("two", 1)
    assert os.listdir(folder) == [project_file.ANCHOR_NAME]
    if sys.platform == "win32":
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(
            project_file.anchor_path(folder))
        assert attrs != -1 and attrs & 0x2


def test_a_project_file_elsewhere_is_not_hidden(tmp_path):
    path = str(tmp_path / "game.pinproj")
    project_file.save(path, manufacturer_key="stern", paths={},
                      extract_options={})
    assert project_file.load(path)["manufacturer"] == "stern"
    if sys.platform == "win32":
        import ctypes
        assert not ctypes.windll.kernel32.GetFileAttributesW(path) & 0x2


def test_a_settings_write_that_dies_leaves_settings_whole(tmp_path,
                                                          monkeypatch):
    with web_app(tmp_path, mfr="stern",
                 settings={"autosave_minutes": 15}) as w:
        settings_file = tmp_path / "cfg" / "settings.json"
        w.run(w.app._save_settings)
        before = json.loads(settings_file.read_text(encoding="utf-8"))
        assert before["autosave_minutes"] == 15
        _disk_full_mid_write(monkeypatch)
        w.app._settings["autosave_minutes"] = 30
        w.run(w.app._save_settings)          # swallowed, as it always was
        monkeypatch.undo()
        assert json.loads(settings_file.read_text(encoding="utf-8")) == before
        assert sorted(os.listdir(settings_file.parent)).count(
            "settings.json") == 1
        assert not [n for n in os.listdir(settings_file.parent)
                    if n.startswith("settings.json.")]
        w.run(w.app._save_settings)          # and the next save lands
        assert json.loads(settings_file.read_text(
            encoding="utf-8"))["autosave_minutes"] == 30


def test_a_staging_write_that_dies_keeps_the_picks(tmp_path, monkeypatch):
    from pinball_decryptor.core import atomic_file, staged_changes
    folder = str(tmp_path)
    staged_changes.save(folder, {"audio": {"a.wav": "C:/x.wav"}})

    def half(fh, text):
        fh.write(text[:len(text) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")
    real = atomic_file._write
    monkeypatch.setattr(
        atomic_file, "_write",
        lambda path, fill: real(path, lambda fh: half(fh, "x" * 100)))
    staged_changes.save(folder, {"audio": {}})        # best-effort, quiet
    monkeypatch.undo()
    assert staged_changes.load(folder) == {"audio": {"a.wav": "C:/x.wav"}}
    assert os.listdir(folder) == [staged_changes.SIDE_CAR]
    staged_changes.save(folder, {"audio": {}})
    assert staged_changes.load(folder) == {"audio": {}}


def test_card_edits_and_tag_library_survive_a_dying_write(tmp_path,
                                                          monkeypatch):
    from pinball_decryptor.core import card_edits, tag_library
    for mod, name in ((card_edits, "CARD_EDITS_FILE"),
                      (tag_library, "LIBRARY_FILE")):
        path = str(tmp_path / (name + ".json"))
        monkeypatch.setattr(mod, name, path)
        mod._save({"keep": 1})
        _disk_full_mid_write(monkeypatch)
        mod._save({"keep": 2, "pad": "x" * 500})      # swallowed
        monkeypatch.setattr(json, "dump", _REAL_DUMP)
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"keep": 1}
    assert sorted(os.listdir(tmp_path)) == ["CARD_EDITS_FILE.json",
                                            "LIBRARY_FILE.json"]


def test_the_written_text_is_what_json_dump_writes(tmp_path):
    from pinball_decryptor.core import atomic_file
    path = str(tmp_path / "s.json")
    data = {"b": [1, 2], "a": "é"}
    atomic_file.write_json_atomic(path, data, sort_keys=True)
    with open(path, encoding="utf-8") as f:
        assert f.read() == json.dumps(data, indent=2, sort_keys=True)


_REAL_DUMP = json.dump


def test_a_rename_that_never_lands_still_saves(tmp_path, monkeypatch):
    """A folder where the rename is refused (a NAS, a file held open) keeps
    saving in place, hidden anchor and all, and leaves no temp file."""
    from pinball_decryptor.core import atomic_file
    folder = str(tmp_path)
    _save(folder, "one")

    def refuse(src, dst):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(atomic_file.os, "replace", refuse)
    monkeypatch.setattr(atomic_file.time, "sleep", lambda s: None)
    assert project_file.update_anchor(folder, notes="two")
    monkeypatch.undo()
    assert project_file.load_anchor(folder)["notes"] == "two"
    assert os.listdir(folder) == [project_file.ANCHOR_NAME]
