"""Contract + light-touch tests for JJP.

JJP's full Extract pipeline is the most demanding of the four plugins —
it needs WSL2 or Docker, partclone, debugfs, xorriso, and a real game
ISO (gigabytes).  None of that fits in a test fixture, so we limit
these tests to:
  - Filename detection (covered also in test_detection.py)
  - Pipeline construction (covered in test_plugins.py)
  - Output-rename wrapper correctness (the post-write _move_output hook
    we added in v0.1.3 - testable without running the real pipeline).
"""

import os
import shutil

import pytest


def test_jjp_write_wrapper_moves_output(manufacturers_by_key, tmp_path):
    """_WriteWrapper post-intercept moves the produced ISO to the
    user's chosen output_path.  Verify by staging a fake produced ISO
    + calling the intercept directly (without running the pipeline)."""
    jjp = manufacturers_by_key["jjp"]

    iso_basename = "Wonka-v03.03"
    fake_original = tmp_path / f"{iso_basename}.iso"
    fake_original.write_bytes(b"\x00")

    assets_dir = tmp_path / "assets"; assets_dir.mkdir()
    out_dir = tmp_path / "out"; out_dir.mkdir()
    target = out_dir / "user_chosen.iso"

    # Stage what the upstream pipeline would produce
    produced = assets_dir / f"{iso_basename}_modified.iso"
    produced.write_bytes(b"FAKE_PRODUCED_ISO_" + os.urandom(64))
    produced_size = produced.stat().st_size

    seen = {}
    wrapper = jjp.make_write_pipeline(
        str(fake_original), str(assets_dir), str(target),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda success, summary: seen.update(success=success,
                                                       summary=summary))

    # Fire the post-pipeline intercept directly
    wrapper._intercept_done(True, "Repack complete (fake).")

    assert not produced.exists(), \
        "Produced ISO should have been MOVED, not copied"
    assert target.exists(), "Target ISO not present after move"
    assert target.stat().st_size == produced_size
    assert seen["success"] is True
    assert "Final output:" in seen["summary"]


def test_jjp_write_wrapper_finds_fl_dat_in_assets(manufacturers_by_key, tmp_path):
    """The ISO Write flow must locate fl_decrypted.dat in the assets folder.

    Regression for v0.13.2: _WriteWrapper hardcoded fl_dat_path=None, so the
    standalone Encrypt pass always bailed with "no fl_decrypted.dat is
    available" even when the Decrypt phase had written one right next to the
    user's modified assets.  Verify the wrapper now picks it up (mirrors the
    Direct-SSD write path)."""
    jjp = manufacturers_by_key["jjp"]

    fake_original = tmp_path / "EltonJohn-v02.03.iso"
    fake_original.write_bytes(b"\x00")
    assets_dir = tmp_path / "assets"; assets_dir.mkdir()
    fl_dat = assets_dir / "fl_decrypted.dat"
    fl_dat.write_bytes(b"FL_DAT")

    wrapper = jjp.make_write_pipeline(
        str(fake_original), str(assets_dir), str(tmp_path / "out.iso"),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)

    assert wrapper.fl_dat_path is not None, \
        "Write pipeline ignored fl_decrypted.dat in the assets folder"
    assert os.path.normpath(wrapper.fl_dat_path) == os.path.normpath(str(fl_dat))


def test_jjp_write_wrapper_fl_dat_absent_is_none(manufacturers_by_key, tmp_path):
    """No fl_decrypted.dat in the assets folder -> fl_dat_path stays None
    (the Encrypt pass then surfaces its actionable 'run Decrypt first' error)."""
    jjp = manufacturers_by_key["jjp"]

    fake_original = tmp_path / "EltonJohn-v02.03.iso"
    fake_original.write_bytes(b"\x00")
    assets_dir = tmp_path / "assets"; assets_dir.mkdir()

    wrapper = jjp.make_write_pipeline(
        str(fake_original), str(assets_dir), str(tmp_path / "out.iso"),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)

    assert wrapper.fl_dat_path is None


def test_jjp_capabilities_match_expected(manufacturers_by_key):
    jjp = manufacturers_by_key["jjp"]
    caps = jjp.capabilities
    # JJP supports extract + write + modpack via the standalone pipeline.
    # Apply-delta isn't applicable (no delta concept in JJP's flow).
    assert caps.extract is True
    assert caps.write is True
    assert caps.modpack is True
    assert caps.apply_delta is False
    assert caps.iso is True
