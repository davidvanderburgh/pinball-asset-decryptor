"""Batch 19 — folder-scoped projects: core model tests.

Covers the format-2 project file + folder anchors (project_file), the
known-projects registry (project_registry), and the folder operations
(project_ops: sizes / fork copy / archive / hydrate).  All on tiny
synthetic folders — no real extractions.
"""

import json
import os

import pytest

from pinball_decryptor.core import project_file, project_ops, project_registry
from pinball_decryptor.core.checksums import generate_checksums


# ----------------------------------------------------------------------
# project_file — format 2 + anchors
# ----------------------------------------------------------------------

def _save_minimal(path, **kw):
    args = dict(
        manufacturer_key="stern",
        paths={"extract_input": "C:/stock/game.raw",
               "extract_output": "C:/proj"},
        extract_options={"audio": True},
        app_version="0.75.0",
    )
    args.update(kw)
    project_file.save(path, **args)


def test_format2_round_trip(tmp_path):
    p = tmp_path / "game.pinproj"
    _save_minimal(str(p), notes="fork for upscale tests",
                  build_dir="D:/fastdisk/build", write_filename="game.raw")
    data = project_file.load(str(p))
    assert data["format"] == 2
    assert data["manufacturer"] == "stern"
    assert data["stock_image"] == "C:/stock/game.raw"   # derived from paths
    assert data["notes"] == "fork for upscale tests"
    assert data["build_dir"] == "D:/fastdisk/build"
    assert data["archived"] is False
    # Format 2 still writes the five format-1 path fields for older apps.
    assert set(data["paths"]) == set(project_file.PATH_FIELDS)


def test_format1_file_still_loads(tmp_path):
    p = tmp_path / "old.pinproj"
    legacy = {
        "kind": "pinball-asset-decryptor-project",
        "format": 1,
        "manufacturer": "jjp",
        "paths": {"extract_input": "", "write_original": "C:/img/game.iso",
                  "extract_output": "C:/work", "write_assets": "C:/work",
                  "write_output": "C:/out"},
        "extract_options": {},
    }
    p.write_text(json.dumps(legacy), encoding="utf-8")
    data = project_file.load(str(p))
    # stock_image falls back to write_original when extract_input is empty.
    assert data["stock_image"] == "C:/img/game.iso"
    assert data["notes"] == "" and data["build_dir"] == ""
    assert data["archived"] is False


def test_not_a_project_file(tmp_path):
    p = tmp_path / "junk.pinproj"
    p.write_text("{\"kind\": \"nope\"}", encoding="utf-8")
    with pytest.raises(ValueError):
        project_file.load(str(p))


def test_anchor_write_load_and_hidden_rewrite(tmp_path):
    folder = str(tmp_path)
    assert not project_file.has_anchor(folder)
    _save_minimal(project_file.anchor_path(folder))
    assert project_file.has_anchor(folder)
    # The Windows hidden-attribute trap: a second write over an existing
    # (now hidden) anchor must not raise PermissionError.
    _save_minimal(project_file.anchor_path(folder), notes="second write")
    assert project_file.load_anchor(folder)["notes"] == "second write"


def test_update_anchor_preserves_unknown_keys(tmp_path):
    folder = str(tmp_path)
    _save_minimal(project_file.anchor_path(folder))
    # Simulate a NEWER app having added a field this app doesn't know.
    path = project_file.anchor_path(folder)
    data = json.loads(open(path, encoding="utf-8").read())
    data["from_the_future"] = {"x": 1}
    project_file._write_maybe_hidden(path, data)
    assert project_file.update_anchor(folder, archived=True, notes="hi")
    data = project_file.load_anchor(folder)
    assert data["archived"] is True and data["notes"] == "hi"
    assert data["from_the_future"] == {"x": 1}


def test_update_anchor_no_anchor_is_noop(tmp_path):
    assert project_file.update_anchor(str(tmp_path), archived=True) is False


def test_project_build_dir_default_and_override(tmp_path):
    folder = str(tmp_path)
    _save_minimal(project_file.anchor_path(folder))
    assert (project_file.project_build_dir(folder)
            == os.path.join(folder, "build"))
    project_file.update_anchor(folder, build_dir="D:/elsewhere/build")
    assert project_file.project_build_dir(folder) == "D:/elsewhere/build"


# ----------------------------------------------------------------------
# project_registry
# ----------------------------------------------------------------------

def test_registry_touch_dedup_and_order():
    s = {}
    project_registry.touch(s, r"C:\p\one", manufacturer="stern", stamp="t1")
    project_registry.touch(s, r"C:\p\two", manufacturer="jjp", stamp="t2")
    # Re-touch the first entry — dedups, moves to head, keeps its
    # manufacturer.  Dedup is normcase-based, so the case-variant spelling
    # only folds together on Windows (POSIX paths are case-sensitive and
    # normcase is rightly a no-op there — CI caught this on macOS/Linux).
    variant = r"c:\P\ONE" if os.name == "nt" else r"C:\p\one"
    project_registry.touch(s, variant, stamp="t3")
    ents = project_registry.entries(s)
    assert [e["folder"] for e in ents] == [variant, r"C:\p\two"]
    assert ents[0]["manufacturer"] == "stern"
    assert ents[0]["last_opened"] == "t3"


def test_registry_remove_and_relocate():
    s = {}
    project_registry.touch(s, r"C:\p\one", stamp="t1")
    project_registry.touch(s, r"C:\p\two", stamp="t2")
    variant = r"C:\P\ONE" if os.name == "nt" else r"C:\p\one"
    assert project_registry.remove(s, variant) is True
    assert [e["folder"] for e in project_registry.entries(s)] == [r"C:\p\two"]
    assert project_registry.relocate(s, r"C:\p\two", r"D:\moved\two") is True
    assert project_registry.entries(s)[0]["folder"] == r"D:\moved\two"
    assert project_registry.remove(s, r"C:\nope") is False


def test_registry_cap_and_recent():
    s = {}
    for i in range(project_registry.MAX_ENTRIES + 10):
        project_registry.touch(s, rf"C:\p\{i}", stamp=f"t{i}")
    assert len(project_registry.entries(s)) == project_registry.MAX_ENTRIES
    rec = project_registry.recent(s, 3)
    assert [e["folder"] for e in rec] == [
        rf"C:\p\{project_registry.MAX_ENTRIES + 9 - i}" for i in range(3)]


# ----------------------------------------------------------------------
# project_ops — on a tiny synthetic project
# ----------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    """A miniature project: two pristine assets, one edited asset (with its
    .orig snapshot), a build output, sidecars, and a baseline."""
    folder = tmp_path / "proj"
    (folder / "audio").mkdir(parents=True)
    (folder / "videos").mkdir()
    (folder / "audio" / "idx0001.wav").write_bytes(b"pristine-audio")
    (folder / "audio" / "idx0002.wav").write_bytes(b"will-be-edited")
    (folder / "videos" / "attract.mp4").write_bytes(b"pristine-video")
    generate_checksums(str(folder))
    # Edit one file post-baseline, snapshot-style.
    (folder / ".orig" / "audio").mkdir(parents=True)
    (folder / ".orig" / "audio" / "idx0002.wav").write_bytes(b"will-be-edited")
    (folder / "audio" / "idx0002.wav").write_bytes(b"EDITED-CONTENT!")
    (folder / ".staged_changes.json").write_text("{}", encoding="utf-8")
    (folder / "build").mkdir()
    (folder / "build" / "game.raw").write_bytes(b"B" * 512)
    _save_minimal(project_file.anchor_path(str(folder)))
    return str(folder)


def test_project_sizes(project):
    sizes = project_ops.project_sizes(project)
    assert sizes["build"] == 512
    assert sizes["mods"] == len(b"will-be-edited")
    expected_assets = (len(b"pristine-audio") + len(b"EDITED-CONTENT!")
                       + len(b"pristine-video"))
    assert sizes["assets"] == expected_assets


def test_fork_copy_excludes_build_keeps_state(project, tmp_path):
    dest = str(tmp_path / "fork")
    size = project_ops.fork_size(project)
    copied, nbytes, cancelled = project_ops.fork_copy(project, dest)
    assert not cancelled and copied > 0 and nbytes == size
    # Working state came along: edited bytes, snapshot, sidecar, anchor.
    assert (open(os.path.join(dest, "audio", "idx0002.wav"), "rb").read()
            == b"EDITED-CONTENT!")
    assert os.path.isfile(os.path.join(dest, ".orig", "audio", "idx0002.wav"))
    assert os.path.isfile(os.path.join(dest, ".staged_changes.json"))
    assert project_file.has_anchor(dest)
    # The build output did NOT.
    assert not os.path.isdir(os.path.join(dest, "build"))


def test_archive_deletes_pristine_only(project):
    deleted, freed, cancelled = project_ops.archive(project)
    assert not cancelled
    assert deleted == 2                       # the two pristine assets
    assert freed >= len(b"pristine-audio") + len(b"pristine-video") + 512
    # Edited file + dot state survive; build and emptied dirs are gone.
    assert os.path.isfile(os.path.join(project, "audio", "idx0002.wav"))
    assert os.path.isfile(
        os.path.join(project, ".orig", "audio", "idx0002.wav"))
    assert not os.path.isdir(os.path.join(project, "build"))
    assert not os.path.isdir(os.path.join(project, "videos"))
    assert project_file.load_anchor(project)["archived"] is True


def test_archive_cancel_marks_archived_deletes_nothing_unverified(project):
    deleted, _freed, cancelled = project_ops.archive(
        project, cancel=lambda: True)
    assert cancelled and deleted == 0
    # Safety property: even a fully-cancelled archive reads as archived.
    assert project_file.load_anchor(project)["archived"] is True
    # And nothing was deleted without verification.
    assert os.path.isfile(os.path.join(project, "audio", "idx0001.wav"))


def test_hydrate_round_trip(project):
    project_ops.archive(project)
    moved = project_ops.pre_hydrate(project)
    assert moved >= 1                          # the edited file stepped aside
    assert not os.path.isfile(os.path.join(project, "audio", "idx0002.wav"))
    # "Re-extract" refills pristine content (simulated).
    os.makedirs(os.path.join(project, "audio"), exist_ok=True)
    for rel, content in (("audio/idx0001.wav", b"pristine-audio"),
                         ("audio/idx0002.wav", b"will-be-edited"),
                         ("videos/attract.mp4", b"pristine-video")):
        p = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(content)
    restored = project_ops.post_hydrate(project)
    assert restored >= 1
    # Edits are back over the fresh extraction; archived flag cleared.
    assert (open(os.path.join(project, "audio", "idx0002.wav"), "rb").read()
            == b"EDITED-CONTENT!")
    assert project_file.load_anchor(project)["archived"] is False
    assert not os.path.isdir(os.path.join(project, project_ops.HYDRATE_DIR))


def test_pre_hydrate_first_move_wins(project):
    project_ops.archive(project)
    project_ops.pre_hydrate(project)
    # A partial re-extract wrote PRISTINE bytes where the edit used to be,
    # then the hydrate was interrupted and re-run.
    p = os.path.join(project, "audio", "idx0002.wav")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"will-be-edited")
    project_ops.pre_hydrate(project)
    # The TRUE edited copy in .hydrate/ was not clobbered by the pristine one.
    aside = os.path.join(project, project_ops.HYDRATE_DIR,
                         "audio", "idx0002.wav")
    assert open(aside, "rb").read() == b"EDITED-CONTENT!"
