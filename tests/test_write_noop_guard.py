"""The Write flow must not silently ship an UNMODIFIED image when the user
assigned replacements that couldn't be applied.

A CGC AFM user assigned audio replacements, the build emitted a byte-for-byte
copy of the stock image (every convert had failed / nothing was staged), and
it reported success -- they flashed it and saw none of their changes.  The
guard in ``App._run_pipeline_with_audio`` turns that into a loud failure
(when NOTHING staged) or a post-build warning (when SOME staged).
"""
import queue

import pytest

from pinball_decryptor import app as appmod
from pinball_decryptor.core.messages import DoneMsg


class _FakePipeline:
    def __init__(self):
        self.ran = False

    def run(self):
        self.ran = True


def _make_app():
    a = appmod.App.__new__(appmod.App)   # skip Tk/window construction
    a.msg_queue = queue.Queue()
    a._staging_failures = []
    a.pipeline = _FakePipeline()
    return a


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _set_staging(monkeypatch, a, audio, video=(0, 0, []), image=(0, 0, [])):
    monkeypatch.setattr(a, "_stage_pending_audio", lambda d: audio)
    monkeypatch.setattr(a, "_stage_pending_video", lambda d: video)
    monkeypatch.setattr(a, "_stage_pending_image", lambda d: image)


def test_all_staging_failed_aborts_without_building(monkeypatch):
    a = _make_app()
    _set_staging(monkeypatch, a, audio=(
        2, 0, [("audio: a.wav", "need ffmpeg"),
               ("audio: b.wav", "need ffmpeg")]))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is False, "must NOT build an unmodified image"
    dones = [m for m in _drain(a.msg_queue) if isinstance(m, DoneMsg)]
    assert dones and dones[0].success is False
    assert "NOT built" in dones[0].summary
    assert "a.wav" in dones[0].summary  # names the offending file


def test_partial_staging_builds_and_records_failures(monkeypatch):
    a = _make_app()
    _set_staging(monkeypatch, a, audio=(3, 2, [("audio: c.wav", "bad header")]))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is True            # the 2 good ones still ship
    assert len(a._staging_failures) == 1     # remembered for the warn dialog
    assert a._staging_failures[0][0] == "audio: c.wav"


def test_clean_run_builds_with_no_failures(monkeypatch):
    a = _make_app()
    _set_staging(monkeypatch, a, audio=(4, 4, []))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is True
    assert a._staging_failures == []


def test_no_assignments_builds_normally(monkeypatch):
    # Hand-edited-files workflow: nothing assigned -> nothing staged -> the
    # pipeline still runs (the diff picks up the on-disk edits).
    a = _make_app()
    _set_staging(monkeypatch, a, audio=(0, 0, []))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is True
    assert a._staging_failures == []


def test_mixed_surfaces_some_staged_runs(monkeypatch):
    # audio all-fail but a video staged -> overall something staged -> build.
    a = _make_app()
    _set_staging(monkeypatch, a,
                 audio=(1, 0, [("audio: x.wav", "need ffmpeg")]),
                 video=(1, 1, []))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is True
    assert len(a._staging_failures) == 1


# --- replacement_folder_mismatches (the "assigned for another folder") guard ---

from pinball_decryptor.gui.main_window import MainWindow


def _make_window(scan_dir, assignments, slots):
    w = MainWindow.__new__(MainWindow)
    w._audio_assignments = assignments
    w._audio_slots_by_rel = slots
    w._audio_scan_dir = scan_dir
    w._video_assignments = {}
    w._video_slots_by_rel = {}
    w._video_scan_dir = ""
    w._image_assignments = {}
    w._image_slots_by_rel = {}
    w._image_scan_dir = ""
    return w


def test_folder_mismatch_flagged():
    w = _make_window(r"C:\extract\A", {"snd/x.wav": r"C:\rep.wav"},
                     {"snd/x.wav": object()})
    out = w.replacement_folder_mismatches(r"C:\extract\B")
    assert out == [("audio", 1, r"C:\extract\A")]


def test_same_folder_not_flagged():
    # Path differs only by case/separators -> normcase/normpath must match.
    w = _make_window(r"C:\extract\A", {"snd/x.wav": r"C:\rep.wav"},
                     {"snd/x.wav": object()})
    assert w.replacement_folder_mismatches("c:/extract/A") == []


def test_no_assignments_not_flagged():
    w = _make_window(r"C:\extract\A", {}, {})
    assert w.replacement_folder_mismatches(r"C:\extract\B") == []


def test_assignment_without_matching_slot_not_flagged():
    # A stale assignment whose rel isn't in the current slots isn't "live".
    w = _make_window(r"C:\extract\A", {"snd/gone.wav": r"C:\rep.wav"}, {})
    assert w.replacement_folder_mismatches(r"C:\extract\B") == []
