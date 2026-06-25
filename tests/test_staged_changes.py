"""Tests for core.staged_changes — the sidecar that persists the GUI's pending
Replace-Audio/Video/Image assignments across app sessions."""

import json
import os

from pinball_decryptor.core import staged_changes
from pinball_decryptor.core.staged_changes import SIDE_CAR


def test_load_missing_is_empty(tmp_path):
    # A folder that was never edited (no sidecar) loads as {}.
    assert staged_changes.load(str(tmp_path)) == {}


def test_load_empty_path_is_empty():
    assert staged_changes.load("") == {}


def test_save_load_roundtrip(tmp_path):
    payload = {
        "audio": {"audio/idx0001.wav": r"C:\repl\song.mp3"},
        "audio_loop": {"audio/idx0001.wav": True},
        "audio_trim": True,
        "video": {"video/intro.mov": r"C:\repl\intro.mp4"},
        "video_trim": False,
        "image": {"images/logo.png": r"C:\repl\logo.png"},
    }
    staged_changes.save(str(tmp_path), payload)
    assert os.path.isfile(tmp_path / SIDE_CAR)
    assert staged_changes.load(str(tmp_path)) == payload


def test_sidecar_is_a_dotfile(tmp_path):
    # Dotfile so the audio/video/image slot scanners (which skip dot-entries)
    # never mistake it for an asset.
    assert SIDE_CAR.startswith(".")
    staged_changes.save(str(tmp_path), {"audio": {}})
    assert (tmp_path / SIDE_CAR).read_text(encoding="utf-8").strip()


def test_save_no_dir_is_noop(tmp_path):
    missing = tmp_path / "does_not_exist"
    staged_changes.save(str(missing), {"audio": {}})
    assert not missing.exists()


def test_corrupt_sidecar_loads_empty(tmp_path):
    with open(tmp_path / SIDE_CAR, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert staged_changes.load(str(tmp_path)) == {}


def test_non_dict_sidecar_loads_empty(tmp_path):
    with open(tmp_path / SIDE_CAR, "w", encoding="utf-8") as f:
        json.dump(["not", "a", "dict"], f)
    assert staged_changes.load(str(tmp_path)) == {}


def test_live_assignments_drops_vanished_slot(tmp_path):
    rep = tmp_path / "rep.wav"
    rep.write_bytes(b"\x00" * 16)
    saved = {"audio/keep.wav": str(rep), "audio/gone.wav": str(rep)}
    slots = {"audio/keep.wav": object()}            # "gone" no longer scanned
    out = staged_changes.live_assignments(saved, slots)
    assert out == {"audio/keep.wav": str(rep)}


def test_live_assignments_drops_missing_replacement(tmp_path):
    present = tmp_path / "present.wav"
    present.write_bytes(b"\x00" * 16)
    saved = {
        "a.wav": str(present),
        "b.wav": str(tmp_path / "deleted.wav"),     # replacement file gone
    }
    slots = {"a.wav": object(), "b.wav": object()}
    out = staged_changes.live_assignments(saved, slots)
    assert out == {"a.wav": str(present)}


def test_live_assignments_handles_none():
    assert staged_changes.live_assignments(None, {}) == {}
