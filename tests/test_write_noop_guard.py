"""The Write flow must not silently ship an UNMODIFIED image when the user
assigned replacements that couldn't be applied.

A CGC AFM user assigned audio replacements, the build emitted a byte-for-byte
copy of the stock image (every convert had failed / nothing was staged), and
it reported success -- they flashed it and saw none of their changes.  The
guard in ``App._run_pipeline_with_audio`` turns that into a loud failure
(when NOTHING staged) or a post-build warning (when SOME staged).
"""
import os
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
    a._cancel_requested = False
    a.pipeline = _FakePipeline()
    return a


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _set_staging(monkeypatch, a, audio, video=(0, 0, []), image=(0, 0, [])):
    monkeypatch.setattr(a, "_stage_pending_audio", lambda d: audio)
    monkeypatch.setattr(a, "_stage_pending_video",
                        lambda d, cancel_cb=None: video)
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


def test_cancel_during_staging_skips_build_and_error_dialog(monkeypatch):
    # User pressed Cancel while a (long) replacement was still staging: the
    # run must end as a plain "Cancelled." — no build, and no scary "none of
    # your replacements could be applied" dialog for a deliberate stop.
    a = _make_app()
    a._cancel_requested = True
    _set_staging(monkeypatch, a, audio=(1, 0, [("video: x.webm", "cancelled")]))
    a._run_pipeline_with_audio("ASSETS")

    assert a.pipeline.ran is False
    dones = [m for m in _drain(a.msg_queue) if isinstance(m, DoneMsg)]
    assert dones and dones[0].success is False
    assert "NOT built" not in dones[0].summary
    assert "Cancelled" in dones[0].summary


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


_DIR_A = os.path.join("x", "extract", "A")
_DIR_B = os.path.join("x", "extract", "B")


def test_folder_mismatch_flagged():
    w = _make_window(_DIR_A, {"snd/x.wav": "rep.wav"},
                     {"snd/x.wav": object()})
    out = w.replacement_folder_mismatches(_DIR_B)
    assert out == [("audio", 1, _DIR_A)]


def test_same_folder_not_flagged():
    # The same folder expressed with a redundant '.' segment must still match
    # (os.path.normpath collapses it on every OS — POSIX and Windows).
    redundant = os.path.join("x", "extract", ".", "A")
    w = _make_window(_DIR_A, {"snd/x.wav": "rep.wav"}, {"snd/x.wav": object()})
    assert w.replacement_folder_mismatches(redundant) == []


def test_no_assignments_not_flagged():
    w = _make_window(_DIR_A, {}, {})
    assert w.replacement_folder_mismatches(_DIR_B) == []


def test_assignment_without_matching_slot_not_flagged():
    # A stale assignment whose rel isn't in the current slots isn't "live".
    w = _make_window(_DIR_A, {"snd/gone.wav": "rep.wav"}, {})
    assert w.replacement_folder_mismatches(_DIR_B) == []


# --- the warning's own text (PAD-89: a user could not act on this dialog) ---

def _msg(assets_dir=_DIR_B, mismatches=None, recorded=None, action="build"):
    return appmod.replacement_mismatch_message(
        assets_dir,
        mismatches if mismatches is not None else [("video", 527, _DIR_A)],
        recorded or {}, action=action)


def test_message_names_the_folder_being_built():
    # The old dialog named ONLY the folder the assignments belong to, so the
    # two paths could not be compared -- which is the whole point of it.
    body = _msg()
    assert _DIR_B in body
    assert _DIR_A in body


def test_message_points_at_the_field_that_exists():
    # "point the assets folder at the path above" named no real control: every
    # tab's row is a read-only mirror of the Extract tab's Project Folder.
    body = _msg()
    assert '"Project Folder" on the Extract tab' in body
    assert "assets folder" not in body


def test_recorded_replacements_are_not_called_missing():
    # The build falls back to the built folder's own sidecar, so claiming an
    # image "WITHOUT those changes" is false whenever that folder has some.
    body = _msg(recorded={"video": 512})
    assert "WITHOUT" not in body
    assert "512 video" in body
    assert "the build applies those" in body


def test_no_recorded_replacements_still_warns_plainly():
    body = _msg(recorded={})
    assert "produces an image WITHOUT those changes" in body


def test_recorded_count_for_another_kind_does_not_soften_the_warning():
    # Only the kinds that actually mismatch count: audio recorded in the
    # target says nothing about the dropped video assignments.
    body = _msg(mismatches=[("video", 5, _DIR_A)], recorded={"audio": 3})
    assert "produces an image WITHOUT those changes" in body


def test_export_wording():
    body = _msg(action="export", recorded={"video": 512})
    assert "the export includes those" in body
    assert "are not included" in body
    assert body.endswith("Export anyway?")


def test_export_wording_without_recorded():
    body = _msg(action="export")
    assert "produces a mod pack WITHOUT those changes" in body


def test_two_mismatched_folders_read_as_plural():
    body = _msg(mismatches=[("audio", 3, _DIR_A), ("video", 5, _DIR_B)])
    assert "one of those folders" in body


def test_recorded_replacement_counts_reads_the_sidecar(tmp_path):
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(tmp_path), {
        "video": {"v/1.mov": "a.mov", "v/2.mov": "b.mov", "v/3.mov": ""},
        "audio": {"s/1.wav": "x.wav"},
        "image": {},
    })
    counts = appmod.recorded_replacement_counts(
        str(tmp_path), ["video", "audio", "image"])
    # The empty value isn't a replacement, and a kind with none is left out.
    assert counts == {"video": 2, "audio": 1}


def test_recorded_replacement_counts_without_a_sidecar(tmp_path):
    assert appmod.recorded_replacement_counts(str(tmp_path), ["video"]) == {}
