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


def test_jjp_iso_write_not_blocked_by_missing_native_debugfs():
    """Regression guard — macOS ISO Write dies at Scan with
    "Missing prerequisites: debugfs" (tonyscoots report, v0.57.0).

    On macOS check_prerequisites reports debugfs against the NATIVE
    Homebrew binary, which only enables the Direct-SSD no-copy path.
    The ISO Write runs entirely inside the Docker container (whose
    image ships e2fsprogs), so a missing native debugfs must not block
    it — while genuine container failures still must.
    """
    from pinball_decryptor.plugins.jjp.executor import DockerExecutor
    from pinball_decryptor.plugins.jjp.pipeline import _mod_blocking_prereqs

    docker = DockerExecutor()

    macos_results = [
        ("Docker", True, "Available"),
        ("partclone", True, "Available (in container)"),
        ("xorriso", True, "Available (in container)"),
        ("debugfs", False,
         "Not installed. Run: brew install e2fsprogs\n"
         "  (enables direct SSD access without copying)"),
    ]
    assert _mod_blocking_prereqs(docker, macos_results) == [], (
        "A missing native (Homebrew) debugfs must not block the macOS "
        "ISO Write — the Docker image carries its own debugfs.")

    container_broken = [
        ("Docker", True, "Available"),
        ("partclone", False, "Container check failed: boom"),
        ("xorriso", False, "Container check failed: boom"),
        ("debugfs", False, "Not installed."),
    ]
    blocked = [n for n, _ in _mod_blocking_prereqs(docker, container_broken)]
    assert blocked == ["partclone", "xorriso"]


def test_jjp_wsl_write_still_requires_debugfs():
    """On Windows/Linux the Write edits ext4 through the executor's own
    debugfs, so a missing debugfs there must still block the run."""
    from pinball_decryptor.plugins.jjp.pipeline import _mod_blocking_prereqs

    results = [
        ("WSL2", True, "Available"),
        ("debugfs", False,
         "Not installed. Run: wsl -u root -- apt install e2fsprogs"),
    ]
    blocked = _mod_blocking_prereqs(object(), results)
    assert [n for n, _ in blocked] == ["debugfs"]


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


def test_jjp_enospc_errors_point_at_the_disk_dialog(monkeypatch):
    """"No space left on device" comes from WSL/Docker's own capped virtual
    disk while the user's real drive shows hundreds of GB free, so the raw
    error reads as nonsense.  Any ENOSPC pipeline error must carry the path
    to the actual knob: ⚙ settings → Manage disk space → Resize WSL disk
    (Windows) / Docker Desktop's disk limit (macOS)."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    msg = ("mkdir: cannot create directory '/mnt/jjp_0ae5a6a0': "
           "No space left on device")

    monkeypatch.setattr(P.sys, "platform", "win32")
    hinted = P._with_disk_full_hint(msg)
    assert hinted.startswith(msg)
    assert "Manage disk space" in hinted
    assert "Resize WSL disk" in hinted

    monkeypatch.setattr(P.sys, "platform", "darwin")
    hinted = P._with_disk_full_hint(msg)
    assert "Docker Desktop" in hinted

    # Unrelated failures must pass through untouched.
    other = "mount: wrong fs type, bad option, bad superblock"
    assert P._with_disk_full_hint(other) == other


def test_jjp_mount_enospc_fails_fast_with_resize_hint(monkeypatch):
    """Regression guard — Sonic extract, 2026-07-21.  With WSL's disk full,
    the first mount failure took the "cached image may be corrupt" branch:
    it deleted the image, re-extracted for minutes into the SAME full disk,
    then died anyway on a bare mkdir ENOSPC with no guidance.  An
    out-of-space mount failure must skip the re-extract and point at the
    resize dialog immediately."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    class _FullDiskExecutor:
        def run(self, cmd, timeout=None):
            if cmd.startswith("mkdir -p "):
                raise P.CommandError(cmd, 1,
                    "mkdir: cannot create directory "
                    "'/mnt/jjp_0ae5a6a0': No space left on device")
            return ""  # stale-mount/loop-device cleanup probes

    monkeypatch.setattr(P.sys, "platform", "win32")
    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = _FullDiskExecutor()
    pipe.log = lambda *a, **k: None
    pipe.on_phase = lambda *a, **k: None
    pipe._raw_img_path = "/var/tmp/jjp_raw_fake.img"
    pipe._is_iso = lambda: True
    reextracted = []
    pipe._phase_extract = lambda: reextracted.append(True)

    with pytest.raises(P.PipelineError) as exc:
        pipe._phase_mount()
    assert "Resize WSL disk" in str(exc.value)
    assert not reextracted, (
        "ENOSPC must not trigger the delete-and-re-extract retry — "
        "re-extracting into the same full disk cannot succeed.")


def test_jjp_partclone_short_restore_is_fatal():
    """Regression guard — Sonic extract, 2026-07-21.  ``cat | gunzip |
    partclone.restore`` reported the *last* stage's status only, so a source
    that died mid-stream just looked like EOF: partclone stopped at 60%,
    exited 0, and the pipeline mounted a filesystem missing most of its
    files (the decrypt then walked 2352 of 16207 assets and called it a
    day).  A restore that never reaches ~100% must fail loudly."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    class _ShortExecutor:
        def stream(self, cmd, timeout=None):
            assert "pipefail" in cmd, (
                "the restore pipeline must run under pipefail, or a failing "
                "cat/gunzip stays invisible behind partclone's exit status")
            yield "Starting to restore image (-) to device (/var/tmp/x.img)"
            for pct in (10, 30, 60):
                yield f"Elapsed: 00:00:08, Completed:  {pct}.00%,"

        def run(self, cmd, timeout=None):
            return ""

    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = _ShortExecutor()
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.cancelled = False
    pipe._raw_img_path = "/var/tmp/jjp_raw_fake.img"

    with pytest.raises(P.PipelineError) as exc:
        pipe._extract_with_partclone(["/iso/sda3.ext4-ptcl-img.gz.aa"])
    assert "60%" in str(exc.value)


def test_jjp_partclone_full_restore_passes():
    """The completeness guard must not fire on a healthy restore."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    class _GoodExecutor:
        def stream(self, cmd, timeout=None):
            for pct in (10, 50, 100):
                yield f"Elapsed: 00:00:08, Completed:  {pct}.00%,"

        def run(self, cmd, timeout=None):
            # dumpe2fs / stat probes — empty output exercises the
            # "can't read the superblock, skip the extend" path.
            return ""

    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = _GoodExecutor()
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.cancelled = False
    pipe._raw_img_path = "/var/tmp/jjp_raw_fake.img"

    pipe._extract_with_partclone(["/iso/sda3.ext4-ptcl-img.gz.aa"])  # no raise


def _decrypt_pipe(tmp_path, script_output, **attrs):
    """A StandaloneDecryptPipeline wired to a canned decrypt-script run."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    class _ScriptExecutor:
        def to_exec_path(self, p):
            return "/mnt/out"

        def run(self, cmd, timeout=None):
            return ""

        def stream(self, cmd, timeout=None):
            for line in script_output:
                yield line

    pipe = object.__new__(P.StandaloneDecryptPipeline)
    pipe.executor = _ScriptExecutor()
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.cancelled = False
    pipe.mount_point = "/mnt/jjp_x"
    pipe.output_path = str(tmp_path)
    pipe.game_name = "Sonic"
    pipe.fl_dat_path = None
    pipe.extract_graphics = True
    pipe.extract_sounds = True
    for k, v in attrs.items():
        setattr(pipe, k, v)
    return pipe


def test_jjp_zero_decrypted_assets_is_a_failure(tmp_path):
    """Regression guard — Sonic v00.925, 2026-07-21.  Its assets use an
    encryption the filler-size probe doesn't recognise, so every file was
    rejected: the run walked 2352 files, wrote none, and still finished with
    "Decryption complete!" over an empty output folder."""
    from pinball_decryptor.plugins.jjp import pipeline as P

    pipe = _decrypt_pipe(tmp_path, [
        "Scanning edata directory...",
        "TOTAL_FILES=2352",
        "Scan complete: 0 files found",
        "BATCH COMPLETE",
        "Total: 0  OK: 0  Failed: 0  Skipped: 0",
    ])

    with pytest.raises(P.PipelineError) as exc:
        pipe._phase_decrypt_standalone()
    msg = str(exc.value)
    assert "2352" in msg
    assert "File System" in msg, (
        "the error should point at the one thing that still works")


def test_jjp_zero_decrypted_ok_when_no_asset_categories_wanted(tmp_path):
    """Unticking both Graphics and Sounds legitimately decrypts nothing —
    that must stay a success, not trip the new guard."""
    pipe = _decrypt_pipe(tmp_path, [
        "TOTAL_FILES=2352",
        "Scan complete: 2352 files found",
        "Filtered to 0/2352 files by category selection",
        "Total: 0  OK: 0  Failed: 0  Skipped: 0",
    ], extract_graphics=False, extract_sounds=False)

    pipe._phase_decrypt_standalone()  # no raise


def test_jjp_partial_decrypt_still_succeeds(tmp_path):
    """A run that decrypts *some* files is a success — the guard is only for
    the all-or-nothing case."""
    pipe = _decrypt_pipe(tmp_path, [
        "TOTAL_FILES=100",
        "Scan complete: 100 files found",
        "Total: 100  OK: 98  Failed: 2  Skipped: 0",
    ])

    pipe._phase_decrypt_standalone()  # no raise
