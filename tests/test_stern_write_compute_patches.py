"""Regression guard for Stern Write's patch orchestrator, ``_compute_patches``.

The v0.16.0 "edit in-scene DDS images" refactor inserted ``_radium_image_writes``
directly ahead of ``_compute_patches`` and dropped the latter's ``def`` line,
leaving its whole body as unreachable dead code after a ``return``.  Both
``write_image`` and ``write_device`` kept calling ``_compute_patches(...)``, so
every GUI "Build update" died with ``NameError: name '_compute_patches' is not
defined`` -- and it shipped that way in v0.16.0 - v0.18.0 because nothing
exercised the Write orchestrator end to end (the encode tests all call
lower-level helpers like ``_select_changed_idx_wavs`` / ``_encode_cat0_sounds``).

A second latent ``NameError`` lurked in the same dead body: the v0.18.0
parallel-encode refactor replaced the inline ``all_wavs`` / ``base_by_idx`` diff
with ``_select_changed_idx_wavs`` but left the "Found N edited sound(s)" log line
referencing the now-deleted names, so it would re-raise the moment any sound was
replaced.  These tests drive the orchestrator far enough to catch both.
"""

import inspect
import io

import pytest

from pinball_decryptor.plugins.stern import engine


def _log(*_a, **_k):
    pass


def test_compute_patches_is_defined_with_expected_signature():
    # The primary bug: the function itself went missing.  A bare definition
    # check (no card image needed) is enough to catch it.
    assert callable(getattr(engine, "_compute_patches", None))
    params = list(inspect.signature(engine._compute_patches).parameters)
    assert params == [
        "disk_f", "parts", "assets_dir", "log", "progress", "cancel", "phase",
        "label", "dest_is_device"]


def test_empty_assets_dir_raises_filenotfound_not_nameerror(tmp_path):
    # No edits under the folder -> the orchestrator must run the full diff and
    # reach its "nothing to write" guard.  Before the fix the *call* NameError'd.
    with pytest.raises(FileNotFoundError):
        engine._compute_patches(
            io.BytesIO(b""), [], str(tmp_path),
            log=_log, progress=None, cancel=lambda: False)


def test_audio_edit_log_branch_has_no_dangling_names(tmp_path, monkeypatch):
    # One changed sound with no baseline -> ``audio_edits`` is non-empty, which
    # exercises the previously-broken "Found N edited sound(s)" log branch (the
    # old ``base_by_idx`` / ``all_wavs`` NameError).  We stub ``_extract_inputs``
    # to a sentinel so the test stops right after that branch without needing a
    # real card image / emulator boot: reaching the sentinel proves the audio
    # branch ran clean instead of raising NameError before it.
    (tmp_path / "idx0001.wav").write_bytes(b"\x00\x01\x02\x03")

    class _Reached(Exception):
        pass

    def _sentinel(*_a, **_k):
        raise _Reached()

    monkeypatch.setattr(engine, "_extract_inputs", _sentinel)
    with pytest.raises(_Reached):
        engine._compute_patches(
            io.BytesIO(b""), [], str(tmp_path),
            log=_log, progress=None, cancel=lambda: False)


@pytest.mark.parametrize("raw,expect_line", [
    (True, False),    # RAW pinned by the app = THE standard build; no log line
    (False, True),    # env cleared by hand = experimental shaping; warn loudly
])
def test_audio_edit_logs_shaping_mode(tmp_path, monkeypatch, raw, expect_line):
    # Raw encode is the only GUI behavior now (the match-to-callouts shaper
    # was retired — batch 20), so the standard build logs nothing about
    # shaping; only the unusual hand-cleared-env case leaves a warning
    # fingerprint (a card built during an experiment must be identifiable
    # after the fact — a tester's 2026-07 click A/B).
    (tmp_path / "idx0001.wav").write_bytes(b"\x00\x01\x02\x03")
    if raw:
        monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
    else:
        monkeypatch.delenv("PAD_STERN_AUDIO_RAW", raising=False)

    lines = []

    def _cap_log(msg, lvl="info", *a, **k):
        lines.append((msg, lvl))

    class _Reached(Exception):
        pass

    def _sentinel(*_a, **_k):
        raise _Reached()

    monkeypatch.setattr(engine, "_extract_inputs", _sentinel)
    with pytest.raises(_Reached):
        engine._compute_patches(
            io.BytesIO(b""), [], str(tmp_path),
            log=_cap_log, progress=None, cancel=lambda: False)
    hits = [(m, l) for m, l in lines if m.startswith("Audio shaping")]
    if expect_line:
        assert len(hits) == 1
        assert "Audio shaping ON" in hits[0][0]
        assert hits[0][1] == "warning"
    else:
        assert not hits


# --- write_image: background-copy / patch overlap orchestration --------------
# (the copy of the unpatched card runs in a thread while patches are computed;
# joined before any patch byte is written.  These stub the heavy compute so they
# exercise the orchestration -- copy, join, apply, and the cancel/failure cleanup
# -- without a real card image.)

def _tiny_card(tmp_path):
    src = tmp_path / "card.raw"
    src.write_bytes(b"ORIGINAL-CARD-BYTES" * 64)
    return src


def test_write_image_copies_then_applies_patches(tmp_path, monkeypatch):
    src = _tiny_card(tmp_path)
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])

    def fake_compute(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None, label=None, dest_is_device=False):
        # (writes, counts, grow_plan, audio_mode) — no oversized videos, so
        # grow_plan=None; the cave applied, so the mode is blip-free
        return ({19: b"PATCHED!"}, (3, 0, 0, 0), None,   # 3 sounds, off 19
                ("blip-free", ""))
    monkeypatch.setattr(engine, "_compute_patches", fake_compute)

    seen = {}

    def fake_apply(out_f, writes):
        seen["writes"] = dict(writes)
        for off, b in writes.items():
            out_f.seek(off)
            out_f.write(b)
    monkeypatch.setattr(engine, "_apply_writes", fake_apply)

    n, mode = engine.write_image(str(src), str(tmp_path), str(out), log=_log)
    assert n == (3, 0, 0, 0)          # per-type breakdown (audio, video, image, text)
    assert mode == ("blip-free", "")  # the engine's mode passes through intact
    assert out.exists()
    assert seen["writes"] == {19: b"PATCHED!"}
    data = out.read_bytes()
    assert data[:19] == b"ORIGINAL-CARD-BYTES"      # background copy happened
    assert data[19:27] == b"PATCHED!"               # then patched in place


def test_write_image_cancel_discards_output(tmp_path, monkeypatch):
    src = _tiny_card(tmp_path)
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: (None, None, None, None))  # cancelled mid-compute
    monkeypatch.setattr(engine, "_apply_writes",
                        lambda *a, **k: pytest.fail("must not patch on cancel"))
    assert (engine.write_image(str(src), str(tmp_path), str(out), log=_log)
            == ((0, 0, 0, 0), None))
    assert not out.exists()                                # pristine copy discarded


def test_write_image_compute_error_discards_output(tmp_path, monkeypatch):
    src = _tiny_card(tmp_path)
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])

    def boom(*_a, **_k):
        raise RuntimeError("Master-directory integrity check FAILED")
    monkeypatch.setattr(engine, "_compute_patches", boom)
    monkeypatch.setattr(engine, "_apply_writes",
                        lambda *a, **k: pytest.fail("must not patch on error"))
    with pytest.raises(RuntimeError, match="integrity"):
        engine.write_image(str(src), str(tmp_path), str(out), log=_log)
    assert not out.exists()                                # half-prepared output cleaned


def test_write_image_copy_failure_surfaces(tmp_path, monkeypatch):
    import shutil
    src = _tiny_card(tmp_path)
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: ({0: b"X"}, (1, 0, 0, 0), None, None))
    monkeypatch.setattr(engine, "_apply_writes",
                        lambda *a, **k: pytest.fail("must not patch when copy failed"))

    def bad_copy(_s, _d):
        raise OSError("disk full")
    monkeypatch.setattr(shutil, "copyfile", bad_copy)
    with pytest.raises(OSError, match="disk full"):
        engine.write_image(str(src), str(tmp_path), str(out), log=_log)


def test_write_image_waits_for_slow_copy_before_patching(tmp_path, monkeypatch):
    # The patch must never be applied until the background copy has fully
    # finished (else apply would race the still-running copy).  A slow copy +
    # an instant compute would expose a missing join(); the assert proves the
    # full original landed before the patch went in.
    import shutil
    import time
    src = _tiny_card(tmp_path)
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: ({19: b"PATCHED!"}, (1, 0, 0, 0),
                                         None, None))

    real_copy = shutil.copyfile

    def slow_copy(s, d):
        time.sleep(0.15)            # finishes well after compute returns
        return real_copy(s, d)
    monkeypatch.setattr(shutil, "copyfile", slow_copy)

    def fake_apply(out_f, writes):
        for off, b in writes.items():
            out_f.seek(off)
            out_f.write(b)
    monkeypatch.setattr(engine, "_apply_writes", fake_apply)

    engine.write_image(str(src), str(tmp_path), str(out), log=_log)
    data = out.read_bytes()
    assert data[:19] == b"ORIGINAL-CARD-BYTES"   # the slow copy completed first
    assert data[19:27] == b"PATCHED!"            # then the patch was applied
    assert len(data) == len(src.read_bytes())    # full image, not a truncated race


# --- completion-dialog wording: name the types that actually changed ---------
# The engine returns a (audio, video, image, text) breakdown; the pipeline must
# label the write by what it touched, not always say "sound(s)" (flippermeister:
# two replaced images were reported as two replaced sounds).

def test_write_summary_names_the_changed_type():
    from pinball_decryptor.plugins.stern.pipeline import _write_summary
    # flippermeister's exact case: image-only write must not say "sound(s)".
    assert _write_summary((0, 0, 2, 0)) == "2 image(s)"
    assert _write_summary((3, 0, 0, 0)) == "3 sound(s)"
    assert _write_summary((0, 5, 0, 0)) == "5 video(s)"
    assert _write_summary((0, 0, 0, 4)) == "4 display string(s)"


def test_write_summary_joins_multiple_types_and_handles_empty():
    from pinball_decryptor.plugins.stern.pipeline import _write_summary
    assert _write_summary((1, 0, 2, 0)) == "1 sound(s) and 2 image(s)"
    assert (_write_summary((1, 2, 3, 4))
            == "1 sound(s), 2 video(s), 3 image(s) and 4 display string(s)")
    assert _write_summary((0, 0, 0, 0)) == "no changes"  # cancelled / nothing edited


# --- completion-dialog audio-mode note: say whether the card is blip-free ----
# A build whose blip-free patch silently fell back (e.g. a Windows host without
# WSL2) used to look identical to a blip-free build everywhere but a mid-build
# log warning; a tester (Elvira, 2026-07-30) burned two hardware tests on a
# fallback card he believed was blip-free, reporting its two window scraps as a
# "two stage click" that survived the v0.94.0 fix.  The dialog must name the
# build mode so a report can be tied to what the card actually carries.

def test_audio_mode_note_names_the_fallback_and_its_symptom():
    from pinball_decryptor.plugins.stern.pipeline import _audio_mode_note
    note = _audio_mode_note(("standard", "this system can't grow files "
                             "inside an ext4 image (WSL2 not available)"))
    assert "NOT applied" in note
    assert "WSL2 not available" in note        # the reason reaches the user
    assert "scrap" in note                     # and so does what it sounds like
    assert "double click" in note


def test_audio_mode_note_confirms_blip_free_and_skips_non_audio():
    from pinball_decryptor.plugins.stern.pipeline import _audio_mode_note
    assert "applied" in _audio_mode_note(("blip-free", ""))
    assert "NOT" not in _audio_mode_note(("blip-free", ""))
    # A video/image-only write has no cat-0 audio: nothing to report.
    assert _audio_mode_note(None) == ""


def test_write_pipeline_summary_carries_the_mode(tmp_path, monkeypatch):
    # End-to-end through SternWritePipeline._run: the dialog string handed to
    # done_cb must carry the engine's mode, not just the counts.
    from pinball_decryptor.plugins.stern import pipeline as pl
    monkeypatch.setattr(pl, "detect_game", lambda p: "spike2")
    monkeypatch.setattr(pl, "display_for_key", lambda k, p: "Test Game")
    monkeypatch.setattr(pl, "_require_engine", lambda: None)
    monkeypatch.setattr(
        pl.engine, "write_image",
        lambda *a, **k: ((2, 0, 0, 0), ("standard", "turned off for this "
                                        "build")))
    got = {}
    p = pl.SternWritePipeline(
        str(tmp_path / "in.img"), str(tmp_path), str(tmp_path / "out.img"),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=None,
        done_cb=lambda ok, summary: got.update(ok=ok, summary=summary))
    p._run()
    assert got["ok"]
    assert "2 sound(s)" in got["summary"]
    assert "Blip-free callouts: NOT applied" in got["summary"]
    assert "turned off for this build" in got["summary"]
