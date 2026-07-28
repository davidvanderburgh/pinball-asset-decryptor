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


# ---------------------------------------------------------------------------
# Dongle-decrypt mode (advanced): run the game under a HASP dongle so it
# decrypts its own assets — the escape hatch for a title whose cipher isn't
# reverse-engineered yet (e.g. Sonic).  These test the wiring, not a live run.
# ---------------------------------------------------------------------------

def test_jjp_dongle_extract_capability_and_phases(manufacturers_by_key):
    jjp = manufacturers_by_key["jjp"]
    assert jjp.capabilities.dongle_extract is True
    # The dongle flow uses the full dongle-bearing phase list.
    from pinball_decryptor.plugins.jjp import config
    assert jjp.dongle_extract_phases == tuple(config.PHASES)
    assert "Dongle" in jjp.dongle_extract_phases
    assert "Compile" in jjp.dongle_extract_phases


def test_jjp_make_dongle_extract_pipeline(manufacturers_by_key):
    jjp = manufacturers_by_key["jjp"]
    noop = lambda *a, **k: None
    p = jjp.make_dongle_extract_pipeline(
        r"C:\game.iso", r"C:\out", noop, noop, noop, noop, dev_capture=True)
    # It's the dongle-bearing DecryptionPipeline (not the standalone one), and
    # the dev-capture flag rode through.
    from pinball_decryptor.plugins.jjp.pipeline import DecryptionPipeline
    assert isinstance(p, DecryptionPipeline)
    assert p.dev_capture is True
    assert callable(p.run)
    # dev_capture defaults off when not requested
    p2 = jjp.make_dongle_extract_pipeline(
        r"C:\game.iso", r"C:\out", noop, noop, noop, noop)
    assert p2.dev_capture is False


def test_jjp_dev_capture_shim_is_game_independent():
    """The developer-capture shim must resolve the game's OWN crypto functions
    by their mangled names via dlsym (so it works for any title, including one
    whose cipher changed) and read memory under a fault guard."""
    from pinball_decryptor.plugins.jjp.pipeline import DEV_CAPTURE_C_SOURCE
    for sym in ("_Z13jcrypt_rand64v",
                "_Z27jcrypt_set_seeds_for_cryptoPKc",
                "_Z21dongle_decrypt_bufferPvj"):
        assert sym in DEV_CAPTURE_C_SOURCE, sym
    # reads guarded against running off the end of .text
    assert "sigsetjmp" in DEV_CAPTURE_C_SOURCE
    assert "JJP_DEV_CAPTURE_DIR" in DEV_CAPTURE_C_SOURCE
    # It overrides al_install_system (early init hook) like the decrypt shim.
    assert "al_install_system" in DEV_CAPTURE_C_SOURCE


# The single Allegro hook (al_install_system) is dead on titles rebuilt off
# Allegro (JJP Sonic runs on libX11/libpulse/libfreetype/libvorbis, no
# liballegro), so the shim would never fire and a one-shot dongle session would
# be wasted.  Both shims must ALSO interpose the new engines' first-init calls.
_ENGINE_AGNOSTIC_HOOKS = (
    "al_install_system",   # Allegro (old titles)
    "XOpenDisplay",        # libX11
    "FT_Init_FreeType",    # libfreetype
    "pa_simple_new",       # libpulse
    "pa_context_new",      # libpulse
    "ov_fopen",            # libvorbisfile
    "ov_open_callbacks",   # libvorbisfile
)


def test_jjp_decrypt_shim_hooks_every_engine():
    """The decrypt shim must fire on non-Allegro titles too (Sonic), and drop a
    diagnostic breadcrumb so a hook that fires but can't resolve the crypto
    still yields intel instead of a silent no-op.

    resources.py DECRYPT_C_SOURCE is pinned byte-verbatim to upstream (it only
    hooks Allegro); the engine-agnostic hooks are appended from pipeline.py's
    DECRYPT_ENGINE_HOOKS_C at compile time.  Verify the *combined* source that
    _phase_compile actually builds."""
    from pinball_decryptor.plugins.jjp.pipeline import (
        DECRYPT_ENGINE_HOOKS_C, combined_decrypt_source)
    combined = combined_decrypt_source()
    for hook in _ENGINE_AGNOSTIC_HOOKS:
        assert hook in combined, hook
    # the appended snippet must hand off to the upstream Allegro entry, so we
    # never duplicate the 300-line resolve/decrypt body
    assert "al_install_system(0, 0)" in DECRYPT_ENGINE_HOOKS_C
    # diagnostics: a hook that fires without resolving crypto dumps maps + ptrs
    assert "jjp_hook_diag.txt" in DECRYPT_ENGINE_HOOKS_C
    assert "/proc/self/maps" in DECRYPT_ENGINE_HOOKS_C
    # one-shot guard so the first engine hook to fire wins the race
    assert "__sync_lock_test_and_set" in DECRYPT_ENGINE_HOOKS_C


def test_jjp_dev_capture_shim_hooks_every_engine():
    """Same engine-agnostic coverage for the crypto-capture shim, plus a maps
    dump so a nil-symbol capture still records the module layout."""
    from pinball_decryptor.plugins.jjp.pipeline import DEV_CAPTURE_C_SOURCE
    for hook in _ENGINE_AGNOSTIC_HOOKS:
        assert hook in DEV_CAPTURE_C_SOURCE, hook
    assert "proc_self_maps.txt" in DEV_CAPTURE_C_SOURCE
    assert "__sync_lock_test_and_set" in DEV_CAPTURE_C_SOURCE


# On Sonic the hooks fire (HW-confirmed: "engine hook fired via XOpenDisplay",
# so the dongle unlocked the LDK-10 envelope) but all four crypto lookups came
# back nil — the rebuilt engine does not export them under the old mangled
# names.  The shim must therefore try harder than one dlsym, and when there is
# genuinely nothing to find it must hand back everything a developer needs
# rather than burning a rare dongle session on a bare error.

def test_jjp_shim_resolver_wraps_the_pinned_dlsym():
    """Upstream does its own dlsym and exits when it fails, and resources.py is
    pinned byte-verbatim — so the prefix reroutes dlsym for that whole
    translation unit instead of editing it."""
    from pinball_decryptor.plugins.jjp.resources import DECRYPT_C_SOURCE
    from pinball_decryptor.plugins.jjp.pipeline import (
        DECRYPT_PREFIX_C, combined_decrypt_source)
    assert "#define dlsym jjp_dlsym" in DECRYPT_PREFIX_C
    # the pinned source itself stays clean; the reroute is purely additive
    assert "jjp_dlsym" not in DECRYPT_C_SOURCE
    combined = combined_decrypt_source()
    assert combined.index("#define dlsym") < combined.index("dlsym(h,")
    # ...and the resolver un-defines it so it can still reach the real dlsym
    assert "#undef dlsym" in combined
    # old titles must be unaffected: the real dlsym is tried first, and a hit
    # returns immediately without any of the fallback machinery
    assert "p = dlsym(h, name);" in combined
    assert "if (p) return p;" in combined


def test_jjp_shim_falls_back_to_a_symbol_census():
    """A crypto function that was merely renamed must still be found: walk every
    loaded object's dynamic symbols and match on the meaningful part of the
    name."""
    combined = _combined()
    assert "dl_iterate_phdr" in combined
    assert "jjp_symbols.txt" in combined
    for tok in ("rand64", "set_seeds_for_crypto", "dongle_decrypt_buffer",
                "process_filelist"):
        assert tok in combined, tok
    # both hash-table flavours, or the census silently finds nothing
    assert "DT_GNU_HASH" in combined and "DT_HASH" in combined
    # a corrupt/absent table must not kill the game process
    assert "sigsetjmp" in combined and "SIGSEGV" in combined


def test_jjp_shim_deep_diagnostic_captures_the_decrypted_game():
    """When nothing resolves, the crypto is internal to the envelope and only
    exists decrypted inside this process — so dump it for offline RE instead of
    just exiting."""
    combined = _combined()
    assert "jjp_report.txt" in combined
    assert "/proc/self/mem" in combined
    assert "proc_self_maps.txt" in combined
    # scans for the known jcrypt LCG multiplier (crypto.py LCG_MULT) so the
    # report says outright whether the asset cipher changed
    assert "0x9BAFFBEDu" in combined
    from pinball_decryptor.plugins.jjp.crypto import LCG_MULT
    assert LCG_MULT == 0x19BAFFBED  # the constant the shim looks for
    # bounded, or a runaway dump fills the user's disk
    assert "JJP_DUMP_CAP" in combined
    # and it must not report its own copy of the needle as a find
    assert "g_self_lo" in combined


def test_jjp_shim_writes_diagnostics_outside_the_asset_dir():
    """Diagnostics go to JJP_DIAG_DIR, not the asset output dir, so a normal
    successful extract's output stays clean."""
    from pinball_decryptor.plugins.jjp import pipeline as P
    assert "JJP_DIAG_DIR" in _combined()
    assert P._DIAG_DIR and P._DIAG_DIR != "/tmp/jjp_decrypted"


def _combined():
    from pinball_decryptor.plugins.jjp.pipeline import combined_decrypt_source
    return combined_decrypt_source()


def _rescue_pipe(tmp_out=r"C:\out", diag_present=True):
    """A DecryptionPipeline wired to a recording fake executor."""
    from pinball_decryptor.plugins.jjp import pipeline as P
    pipe = object.__new__(P.DecryptionPipeline)
    pipe.mount_point = "/mnt/jjp_x"
    pipe.output_path = tmp_out
    pipe.game_name = "Sonic"
    pipe.logs = []
    pipe.log = lambda msg, lvl="info": pipe.logs.append((msg, lvl))
    cmds = []

    def run(cmd, timeout=None):
        cmds.append(cmd)
        if cmd.startswith("test -s") and not diag_present:
            raise P.CommandError(cmd, 1, "no archive")
        return ""

    pipe.executor = type("E", (), {
        "run": staticmethod(run),
        "to_exec_path": staticmethod(lambda p: "/mnt/c/out"),
    })()
    return pipe, cmds


def test_jjp_rescue_diagnostics_tars_into_the_output_folder():
    """Cleanup unmounts the chroot, so the dump has to be pulled out before the
    run ends — a dongle session is too expensive to lose it."""
    pipe, cmds = _rescue_pipe()
    arc = pipe.rescue_diagnostics()
    assert arc == "jjp_diagnostics_Sonic.tar.gz"
    joined = " ".join(cmds)
    assert "tar czf" in joined and "jjp_diagnostics_Sonic.tar.gz" in joined
    assert "/mnt/jjp_x/tmp/jjp_diag" in joined
    # the user is told where it landed
    assert any("jjp_diagnostics_Sonic.tar.gz" in m for m, _ in pipe.logs)
    # second call is a no-op (the archive is built once)
    before = len(cmds)
    assert pipe.rescue_diagnostics() == arc
    assert len(cmds) == before


def test_jjp_archive_guards_avoid_shell_substitution():
    """WslExecutor commands cross an extra wsl.exe parse that expands $... away
    to nothing, so an `if [ -n "$(ls -A dir)" ]` guard is ALWAYS false and the
    archive never gets built — silently costing a dongle session its artifact.
    Both archive paths must guard without a substitution."""
    import inspect
    from pinball_decryptor.plugins.jjp import pipeline as P
    for fn in (P.DecryptionPipeline.rescue_diagnostics,
               P.DecryptionPipeline._phase_dev_capture):
        code = [ln for ln in inspect.getsource(fn).splitlines()
                if not ln.lstrip().startswith("#")]
        src = "\n".join(code)
        assert "tar czf" in src
        assert "$(" not in src, fn.__name__
    pipe, cmds = _rescue_pipe()
    pipe.rescue_diagnostics()
    assert any("find " in c and "grep -q ." in c for c in cmds)


def test_jjp_rescue_diagnostics_is_best_effort():
    """It must never turn into the reason a run fails."""
    pipe, _ = _rescue_pipe(diag_present=False)
    assert pipe.rescue_diagnostics() is None
    pipe2 = object.__new__(
        __import__("pinball_decryptor.plugins.jjp.pipeline",
                   fromlist=["x"]).DecryptionPipeline)
    pipe2.mount_point = None
    assert pipe2.rescue_diagnostics() is None


def test_jjp_missing_symbols_message_blames_the_right_thing():
    """'Check that the correct dongle is connected' is wrong and wastes the
    user's time when the game plainly ran: the dongle worked, the build simply
    doesn't export the crypto."""
    pipe, _ = _rescue_pipe()
    msg = pipe._missing_symbols_help()
    assert "dongle unlocked it" in msg
    assert "not a problem with your dongle" in msg
    assert "retrying will not change it" in msg.lower()
    assert "jjp_diagnostics_Sonic.tar.gz" in msg


def test_jjp_dev_capture_noop_when_not_requested():
    """_phase_dev_capture must do nothing (and never touch the executor) when
    dev_capture is off — the normal decrypt path is unaffected."""
    from pinball_decryptor.plugins.jjp import pipeline as P
    pipe = object.__new__(P.DecryptionPipeline)
    pipe.dev_capture = False
    called = []
    pipe.executor = type("E", (), {"run": lambda *a, **k: called.append(1)})()
    pipe.log = lambda *a, **k: None
    pipe._phase_dev_capture()  # must return immediately
    assert not called


# --- dongle visibility probe -------------------------------------------------

def _dongle_probe_pipe(out):
    """A DecryptionPipeline whose executor replays `out` for the probe."""
    from pinball_decryptor.plugins.jjp import pipeline as P
    pipe = object.__new__(P.DecryptionPipeline)
    seen = []

    def run(cmd, timeout=None):
        seen.append(cmd)
        return out

    pipe.executor = type("E", (), {"run": staticmethod(run)})()
    return pipe, seen


_SYSFS = (
    "/sys/bus/usb/devices/1-1/idVendor:{v}\n"
    "/sys/bus/usb/devices/2-1/idVendor:0489\n"
    "/sys/bus/usb/devices/1-1/idProduct:{p}\n"
    "/sys/bus/usb/devices/2-1/idProduct:e10d\n"
)


def test_jjp_dongle_visible_from_sysfs_without_lsusb():
    """The dongle must be detectable with NO lsusb output at all.

    `lsusb` lives in the `usbutils` package, which a stock Ubuntu WSL does not
    install — the old lsusb-only probe cried "Dongle not visible in lsusb"
    on a perfectly good attach and sent users chasing a phantom.
    """
    pipe, _ = _dongle_probe_pipe(_SYSFS.format(v="0529", p="0001"))
    assert pipe._dongle_visible() is True


def test_jjp_dongle_not_visible_when_ids_belong_to_other_devices():
    """Vendor and product must match on the SAME device, not just appear
    somewhere in the dump."""
    pipe, _ = _dongle_probe_pipe(
        "/sys/bus/usb/devices/1-1/idVendor:0529\n"
        "/sys/bus/usb/devices/1-1/idProduct:e10d\n"
        "/sys/bus/usb/devices/2-1/idVendor:0489\n"
        "/sys/bus/usb/devices/2-1/idProduct:0001\n"
    )
    assert pipe._dongle_visible() is False


def test_jjp_dongle_visible_from_lsusb_fallback():
    """Where usbutils *is* installed, the lsusb line still counts."""
    pipe, _ = _dongle_probe_pipe(
        "Bus 001 Device 004: ID 0529:0001 Aladdin Knowledge Systems HASP\n")
    assert pipe._dongle_visible() is True


def test_jjp_dongle_visible_empty_output_is_false():
    pipe, _ = _dongle_probe_pipe("")
    assert pipe._dongle_visible() is False


def test_jjp_dongle_probe_uses_no_shell_variables():
    """Commands handed to executor.run() cross an extra wsl.exe parse that
    eats `$var` expansions (globs survive, variables do not) — a probe written
    with a shell loop silently evaluates to empty and never matches."""
    pipe, seen = _dongle_probe_pipe("")
    pipe._dongle_visible()
    assert seen, "probe never ran"
    assert "$" not in seen[0], seen[0]
