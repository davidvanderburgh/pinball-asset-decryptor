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
import pkgutil
import shutil

import pytest

JJP_PKG = "pinball_decryptor.plugins.jjp"


def test_jjp_extract_pipeline_start_is_attr_safe():
    """Regression guard — JJP Extract "hangs forever" (phantom running UI).

    ``app.py`` starts every extract with::

        if hasattr(self.pipeline, "set_log_line_cb"):
            self.pipeline.set_log_line_cb(...)
        threading.Thread(target=self.pipeline.run).start()

    The JJP pipelines are ported standalone classes that do NOT inherit
    ``BasePipeline``, so they lack ``set_log_line_cb``.  Before the guard,
    calling it unconditionally raised ``AttributeError`` on the main thread
    *before* the worker thread was started — the extract never ran, no log
    appeared, and the UI sat in a phantom "running" state forever.

    This builds the real extract pipeline and asserts the guarded start
    sequence completes without raising (whether or not the hook exists).
    """
    from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer

    noop = lambda *a, **k: None
    pipeline = JJPManufacturer().make_extract_pipeline(
        r"C:\fake.iso", r"C:\out", noop, noop, noop, noop,
        extract_graphics=True, extract_sounds=True, full_dump=False)

    # The exact guarded pattern app.py uses — must not raise.
    if hasattr(pipeline, "set_log_line_cb"):
        pipeline.set_log_line_cb(noop)
    # And the worker entry point the GUI threads must exist.
    assert callable(pipeline.run)


def test_jjp_decrypt_modules_loadable_via_get_data():
    """Regression guard — macOS "a bytes-like object is required, not
    'NoneType'" (TonyScoots report).

    The standalone decrypt phase deploys crypto.py + filelist.py into the
    macOS Docker container by reading their source with
    ``pkgutil.get_data(<package>, <module>)``.  It used the old standalone
    repo's package name ("jjp_decryptor"), which doesn't exist in the
    unified app — so get_data returned None (it doesn't raise) and the
    pipeline crashed writing None to a file, at the very end of an Extract.

    These resources MUST be loadable via the real package name.
    """
    for module in ("crypto.py", "filelist.py"):
        data = pkgutil.get_data(JJP_PKG, module)
        assert data, (
            f"pkgutil.get_data({JJP_PKG!r}, {module!r}) returned "
            f"{data!r} — the decrypt phase can't deploy it into the "
            f"macOS container and Extract will crash with a NoneType "
            f"write error.")


def test_jjp_pipeline_has_no_dead_jjp_decryptor_package():
    """The unified plugin must not reference the old standalone
    "jjp_decryptor" package name in a get_data/import — that name
    resolves to nothing here and silently returns None."""
    import pinball_decryptor.plugins.jjp.pipeline as _p
    src = open(_p.__file__, encoding="utf-8").read()
    assert 'get_data("jjp_decryptor"' not in src, (
        "pipeline.py still reads from the dead 'jjp_decryptor' package "
        "via pkgutil.get_data — use __package__ / "
        "'pinball_decryptor.plugins.jjp' instead (get_data returns None "
        "for the missing package and the write crashes).")


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
