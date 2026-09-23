"""Guards for feedback batch 18, on the web UI.

Covers: the Audio-category gate on the chained Auto-name steps (video-only
extract must not run transcribe / music-ID against an output with no WAVs),
the build->flash chain behind the two-section Build / flash dialog, the
previous-session log seed, and the project-file load.
"""

import os
import time

import pytest

from tests.test_webui_write import (fake_drives, make_project, point_at,
                                    recorder, wait_for)
from tests.webui_harness import web_app

# Shared fake paths, OS-native so nothing depends on the runner's platform.
# _on_build_flash_request parses the build path with os.path.split, so a
# drive-letter literal like "D:\..." reads as one flat name on POSIX CI and
# the folder push-back looks empty (the bug this file's build-flash test hit).
# FAKE_DEVICE is an opaque physical-device handle, passed straight through to
# a stubbed flash, never touched as a filesystem path, so its Windows-style
# spelling is fine; it only ever has to ride through a call unchanged.
FAKE_BUILD = os.path.join(os.sep + "builds", "game-modified.raw")
FAKE_IMG = os.path.join(os.sep + "imgs", "image.raw")
FAKE_DEVICE = r"\\.\PHYSICALDRIVE9"


# ---- Audio category off => no chained auto-name steps ---------------------

def test_autoname_chain_skipped_when_audio_category_off(tmp_path):
    """a tester: a video-only extract (Audio unchecked) still chained
    Auto-transcribe + Music-ID, which then errored on \"No .wav files\".
    The wrappers must return the done_cb untouched when the run won't
    produce audio."""
    with web_app(tmp_path, mfr="stern") as w:
        app, win = w.app, w.window
        assert app._current_mfr.capabilities.transcribe
        assert app._current_mfr.capabilities.music_id
        assert "audio" in win._extract_category_vars

        def sentinel(s, m):
            return None

        def _check(audio):
            win.transcribe_var.set(True)
            win.music_id_var.set(True)
            win._extract_category_vars["audio"].set(audio)
            return (app._maybe_wrap_done_for_transcribe(sentinel, "X"),
                    app._maybe_wrap_done_for_music_id(sentinel, "X"))

        assert w.run(_check, False) == (sentinel, sentinel)
        t, m = w.run(_check, True)
        assert t is not sentinel and m is not sentinel


def test_plugins_without_audio_category_still_chain(tmp_path):
    """The gate must only ever SKIP for plugins exposing an Audio category
    checkbox; everyone else keeps the old behaviour."""
    with web_app(tmp_path, mfr="stern") as w:
        w.window.service("extract")._extract_category_vars = {}
        assert w.run(w.app._extract_will_produce_audio)


# ---- Build -> flash chain -------------------------------------------------

def _chain_run(w, monkeypatch, mode, success, summary):
    import pinball_decryptor.app as app_mod
    app = w.app
    flashed = []
    monkeypatch.setattr(app, "_start_flash_image",
                        lambda img, dev: flashed.append((img, dev)))
    # A chained build must NOT pop the "Write Complete" modal in between.
    monkeypatch.setattr(
        app_mod.messagebox, "showinfo",
        lambda *a, **k: pytest.fail("no modal between build and flash"))
    monkeypatch.setattr(app_mod.messagebox, "showerror",
                        lambda *a, **k: None)

    def _go():
        app._active_mode = mode
        app._chain_flash_after_build = (FAKE_DEVICE, FAKE_IMG)
        app._on_done(success, summary)
    w.run(_go)
    return flashed


def _settle(w, pred=lambda: False, timeout=2.0):
    """Let the after(0, ...) hand-off fire."""
    end = time.time() + timeout
    while time.time() < end and not pred():
        w.drain()
        time.sleep(0.05)
    w.drain()


def test_build_success_chains_flash(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        flashed = _chain_run(w, monkeypatch, "write", True, "built.")
        _settle(w, lambda: flashed)
        assert flashed == [(FAKE_IMG, FAKE_DEVICE)]
        assert w.app._chain_flash_after_build is None


def test_failed_build_drops_the_chained_flash(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        flashed = _chain_run(w, monkeypatch, "write", False, "boom")
        _settle(w)
        assert flashed == [], "a failed build must never flash the card"
        assert w.app._chain_flash_after_build is None


def test_unrelated_success_never_fires_a_stale_chain(tmp_path, monkeypatch):
    """The chain is consumed on ANY _on_done: an extract finishing after a
    cancelled build must not flash the card."""
    with web_app(tmp_path, mfr="stern") as w:
        flashed = _chain_run(w, monkeypatch, "extract", True, "extract done")
        _settle(w)
        assert flashed == []
        assert w.app._chain_flash_after_build is None


# ---- A flash on a brand with no menu-only write (PAD-138) -----------------

@pytest.mark.parametrize("key, module, name", [
    ("jjp", "pinball_decryptor.plugins.jjp.usbstick",
     "UsbStickPreparePipeline"),
    ("cgc", "pinball_decryptor.plugins.cgc.manufacturer",
     "FlashImagePipeline"),
])
def test_a_flash_starts_on_a_brand_with_no_menu_only_write(
        tmp_path, monkeypatch, key, module, name):
    """The menu-only write taught Stern's flash factory a ``menu_only``
    keyword and the app handed it to EVERY brand's: a JJP USB stick died with
    "make_flash_pipeline() got an unexpected keyword argument 'menu_only'"
    before it began.  This is the dialog's own call, on the real factory."""
    import importlib
    made = []

    class _Pipe:
        def __init__(self, *args, **kwargs):
            made.append((args[:2], kwargs))

        def run(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(importlib.import_module(module), name, _Pipe)
    with web_app(tmp_path, mfr=key) as w:
        try:
            w.run(lambda: w.app._start_flash_image(FAKE_IMG, FAKE_DEVICE,
                                                   menu_only=False))
            assert made == [((FAKE_IMG, FAKE_DEVICE), {})]
        finally:
            def _reset():
                w.app._active_mode = None
                w.window.set_running(False, mode="write")
            w.run(_reset)


def test_a_flash_that_cannot_start_hands_the_window_back(
        tmp_path, monkeypatch):
    """The TypeError above came AFTER the run state was armed, so the window
    sat on a live Cancel with nothing behind it, and pressing that only greyed
    it out ("the application locks up").  Nothing started means nothing will
    ever call done_cb - the start itself has to put the window back."""
    with web_app(tmp_path, mfr="jjp") as w:
        app = w.app

        def _boom(*_a, **_k):
            raise RuntimeError("no pipeline")

        monkeypatch.setattr(app._current_mfr, "make_flash_pipeline", _boom)
        with pytest.raises(RuntimeError):
            w.run(lambda: app._start_flash_image(FAKE_IMG, FAKE_DEVICE))
        assert w.window._running is False
        assert app._active_mode is None
        assert app.pipeline is None, "a Cancel must not reach a stale pipeline"
        assert w.state("write")["cancel"] is False


# ---- The two-section Build / flash dialog ---------------------------------

def _open_dialog(w, tmp_path, monkeypatch, changed=True):
    """The Write tab's Build / flash dialog on a Stern project, drives
    faked.  Returns the recorder of the dialog's build hand-off."""
    fake_drives(monkeypatch)
    proj = make_project(tmp_path, changed=changed)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 4096)
    point_at(w, orig, proj)
    w.call("ui.select_tab", "write")
    assert wait_for(w, lambda: not w.state("write")["scanning"]
                    and w.state("write")["count"] == (1 if changed else 0))
    builds = recorder(w, "on_build_flash")
    w.call("write.primary")
    assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                    .get("drives"))
    return builds


def test_dialog_defaults_build_and_flash_when_changes_pending(
        tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        _open_dialog(w, tmp_path, monkeypatch)
        f = w.state("write")["flash_dlg"]
        assert f["build"] and f["write"]
        assert f["start_label"] == "Build + flash"
        # The flash box mirrors the build output while building.
        assert f["image_path"] == f["build_path"]
        # Build unticked => plain flash (the old dialog).
        w.call("write.flash_set", "build", False)
        assert w.state("write")["flash_dlg"]["start_label"] == "Flash image"
        # Flash unticked too => nothing to do; Start is disabled.
        w.call("write.flash_set", "write", False)
        assert w.state("write")["flash_dlg"]["start_enabled"] is False
        w.call("write.flash_close")


def test_late_drive_enumeration_after_close_is_dropped(tmp_path, monkeypatch):
    """The drive enumeration runs on a worker thread for seconds
    (PowerShell); clicking Start/Cancel first closes the dialog, and the
    late hand-off must not bring the closed dialog back."""
    with web_app(tmp_path, mfr="stern") as w:
        _open_dialog(w, tmp_path, monkeypatch)
        dlg = w.window.service("write")._flash
        w.call("write.flash_close")
        # Exactly what the worker's post runs after the close.
        w.run(dlg._apply_drives, dlg._enum_id, [], (None, None, None))
        assert w.state("write")["flash_dlg"] is None
        assert dlg.drives, "the closed dialog's drive list is left alone"


def test_diagnose_late_drive_enumeration_after_close_is_dropped(
        tmp_path, monkeypatch):
    """The card diagnostics dialog shares the worker-thread pattern: same
    race, same guard."""
    fake_drives(monkeypatch)
    with web_app(tmp_path, mfr="cgc") as w:
        assert w.call("write.diag_open") is True
        assert wait_for(w, lambda: (w.state("write")["diag"] or {})
                        .get("drives"))
        dlg = w.window.service("write")._diag
        w.call("write.diag_close")
        w.run(dlg._apply_drives, dlg._enum_id, [], (None, None, None))
        assert w.state("write")["diag"] is None
        assert dlg.drives, "the closed dialog's drive list is left alone"


def test_dialog_build_only_hands_off_without_confirm(tmp_path, monkeypatch):
    """Build-only (write section unticked) needs no erase confirm and hands
    (build_path, None) to the app."""
    with web_app(tmp_path, mfr="stern") as w:
        builds = _open_dialog(w, tmp_path, monkeypatch)
        build_path = w.state("write")["flash_dlg"]["build_path"]
        w.call("write.flash_set", "write", False)
        asked = len(w.asked)
        assert w.call("write.flash_start") is True
        assert len(w.asked) == asked, "build-only must not ask anything"
        assert builds == [((build_path, None), {})]


def test_on_build_flash_request_writes_back_and_arms_chain(
        tmp_path, monkeypatch):
    """The dialog's Build-to box pushes back into Output Folder + File Name,
    and the device rides into _start_write's chain parameter."""
    with web_app(tmp_path, mfr="stern") as w:
        seen = {}
        monkeypatch.setattr(
            w.app, "_start_write",
            lambda chain_flash_device=None: seen.update(
                device=chain_flash_device))
        build_path = os.path.join(os.sep + "builds", "lz-test.raw")
        expected_folder, expected_name = os.path.split(build_path)
        w.run(lambda: w.app._on_build_flash_request(build_path, FAKE_DEVICE))
        assert w.window.write_output_var.get() == expected_folder
        assert w.window.write_filename_var.get() == expected_name == \
            "lz-test.raw"
        assert seen["device"] == FAKE_DEVICE


def test_dialog_build_warns_when_nothing_modified(tmp_path, monkeypatch):
    """The standalone Build button's nothing-modified guard lives in the
    dialog too: building with no pending changes asks first, and declining
    runs nothing."""
    with web_app(tmp_path, mfr="stern") as w:
        builds = _open_dialog(w, tmp_path, monkeypatch, changed=False)
        w.call("write.flash_set", "build", True)
        w.call("write.flash_set", "write", False)
        w.answers.append("no")
        assert w.call("write.flash_start") is False
        assert w.asked[-1]["title"] == "Nothing modified", \
            "must warn before building an unmodified copy"
        assert builds == [], "declining the warning must not build"
        w.call("write.flash_close")


# ---- Previous-session log seeded into the pane ----------------------------

def _fabricate_history(tmp_path):
    """An earlier session in the log file the harness points the app at."""
    from pinball_decryptor.core import session_log as sl
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "session.log").write_text(
        sl.BANNER_PREFIX + "0.0.1 - session started "
        "2026-01-01 00:00:00 =====\n"
        "[2026-01-01 00:00:05] line from last time\n", encoding="utf-8")


def test_no_history_means_no_cut_line(tmp_path):
    """A first-ever session (no earlier banner in the file) seeds nothing:
    no stray cut line over an empty pane."""
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("shellx")["log_seed"] is None


def test_history_disabled_skips_seeding_new_panes(tmp_path):
    """With the toggle off, the pane starts clean (no history, no cut
    line)."""
    _fabricate_history(tmp_path)
    with web_app(tmp_path, mfr="stern",
                 settings={"show_log_history": False}) as w:
        assert w.state("shellx")["log_seed"] is None


# ---- Project files --------------------------------------------------------

def test_project_apply_restores_everything(tmp_path):
    from pinball_decryptor.core import project_file as pf

    p = str(tmp_path / "lz-2.10.pinproj")
    pf.save(p, manufacturer_key="stern",
            paths={"extract_input": str(tmp_path / "in.raw"),
                   "extract_output": str(tmp_path / "out"),
                   "write_original": str(tmp_path / "in.raw"),
                   "write_assets": str(tmp_path / "out"),
                   "write_output": str(tmp_path / "builds")},
            extract_options={
                "auto_name_callouts": True,
                "categories": {"audio": False, "video": True,
                               "images": True, "text": True}},
            write_filename="lz-test.raw", app_version="0.0.0")

    # Start somewhere that is NOT the project's manufacturer.
    with web_app(tmp_path, mfr="jjp") as w:
        app = w.app
        w.run(lambda: app._apply_project_file(p))
        w.drain()
        win = w.window

        assert app._current_mfr.key == "stern", "project switches manufacturer"
        assert win.extract_input_var.get() == str(tmp_path / "in.raw")
        assert win.extract_output_var.get() == str(tmp_path / "out")
        assert win.write_output_var.get() == str(tmp_path / "builds")
        assert win.write_assets_var.get() == str(tmp_path / "out")
        assert win.transcribe_var.get() is True
        assert win._extract_category_vars["audio"].get() is False
        assert win.write_filename_var.get() == "lz-test.raw"
        # Batch 19: a project's identity is its FOLDER (loose batch-18 files
        # load under the collapsed field model), so the title shows the
        # project folder's basename, not the .pinproj file name.
        assert "out" in app.root.title()


def test_project_load_rejects_unknown_manufacturer(tmp_path):
    from pinball_decryptor.core import project_file as pf
    p = str(tmp_path / "weird.pinproj")
    pf.save(p, manufacturer_key="not-a-real-plugin", paths={},
            extract_options={})
    with web_app(tmp_path, mfr="stern") as w:
        with pytest.raises(ValueError):
            w.run(lambda: w.app._apply_project_file(p))
