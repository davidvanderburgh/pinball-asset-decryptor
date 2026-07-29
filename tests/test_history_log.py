"""Tests for core.history_log — the per-project append-only change record
(batch 24: "changed on disk" months later should still say what a slot was
changed with, and from where)."""

import re

from pinball_decryptor.core import history_log


def test_record_appends_timestamped_lines(tmp_path):
    history_log.record(str(tmp_path), "video  a.mov  replacement picked: x")
    history_log.record(str(tmp_path), ["second line", "third line"])
    text = (tmp_path / history_log.FILE_NAME).read_text(encoding="utf-8")
    lines = text.strip().splitlines()
    assert len(lines) == 3
    for ln in lines:
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  ", ln)
    assert lines[0].endswith("video  a.mov  replacement picked: x")


def test_file_is_a_dotfile_so_every_scanner_skips_it():
    assert history_log.FILE_NAME.startswith(".")


def test_record_nothing_writes_nothing(tmp_path):
    history_log.record(str(tmp_path), [])
    history_log.record(str(tmp_path), None)
    history_log.record(str(tmp_path), [None, ""])
    history_log.record("", "orphan")
    assert not (tmp_path / history_log.FILE_NAME).exists()


def test_record_survives_unwritable_dir(tmp_path):
    # Best-effort: a history line must never fail the action it describes.
    history_log.record(str(tmp_path / "does_not_exist"), "event")


def test_diff_assignments_pick_change_clear():
    old = {"a.mov": "/src/one.mp4", "b.mov": "/src/keep.mp4",
           "c.mov": "/src/old.mp4"}
    new = {"a.mov": "/src/two.mp4", "b.mov": "/src/keep.mp4",
           "d.mov": "/src/new.mp4"}
    events = history_log.diff_assignments("video", old, new)
    joined = "\n".join(events)
    assert "a.mov  replacement changed to: /src/two.mp4  (was: /src/one.mp4)" \
        in joined
    assert "c.mov  replacement cleared  (was: /src/old.mp4)" in joined
    assert "d.mov  replacement picked: /src/new.mp4" in joined
    assert "keep.mp4" not in joined                 # unchanged = no event
    assert all(e.startswith("video  ") for e in events)


def test_diff_assignments_tolerates_missing_maps():
    assert history_log.diff_assignments("audio", None, {}) == []
    assert history_log.diff_assignments("audio", "junk", None) == []
    # First-ever save records the initial picks.
    events = history_log.diff_assignments("audio", None, {"a.wav": "/x.mp3"})
    assert events == ["audio  a.wav  replacement picked: /x.mp3"]


def test_diff_scalar_only_reports_real_changes():
    assert history_log.diff_scalar("opt", None, True) is None   # first save
    assert history_log.diff_scalar("opt", True, True) is None   # unchanged
    assert history_log.diff_scalar("opt", False, True) == "opt: off -> on"
    assert history_log.diff_scalar("n", 3, 5) == "n: 3 -> 5"
