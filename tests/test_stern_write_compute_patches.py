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
        "disk_f", "parts", "assets_dir", "log", "progress", "cancel", "phase"]


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
