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

    def fake_compute(disk_f, parts, assets_dir, log, progress, cancel, phase=None):
        return ({19: b"PATCHED!"}, (3, 0, 0, 0))   # 3 sounds, off 19
    monkeypatch.setattr(engine, "_compute_patches", fake_compute)

    seen = {}

    def fake_apply(out_f, writes):
        seen["writes"] = dict(writes)
        for off, b in writes.items():
            out_f.seek(off)
            out_f.write(b)
    monkeypatch.setattr(engine, "_apply_writes", fake_apply)

    n = engine.write_image(str(src), str(tmp_path), str(out), log=_log)
    assert n == 3
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
                        lambda *a, **k: (None, None))      # cancelled mid-compute
    monkeypatch.setattr(engine, "_apply_writes",
                        lambda *a, **k: pytest.fail("must not patch on cancel"))
    assert engine.write_image(str(src), str(tmp_path), str(out), log=_log) == 0
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
                        lambda *a, **k: ({0: b"X"}, (1, 0, 0, 0)))
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
                        lambda *a, **k: ({19: b"PATCHED!"}, (1, 0, 0, 0)))

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
