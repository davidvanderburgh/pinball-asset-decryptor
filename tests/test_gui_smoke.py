"""GUI construction smoke tests.

These exercise the picker -> mfr-view navigation flow and per-mfr log
swapping without actually running pipelines.  Skipped when Tk can't
open a display (typical for headless Linux CI without xvfb).
"""

import pytest

from tests.conftest import HAS_DISPLAY


pytestmark = pytest.mark.skipif(
    not HAS_DISPLAY, reason="no Tk display available")


import tkinter as _tk_mod


def _make_invisible(win):
    """Make a toplevel effectively headless on Windows: fully transparent,
    parked off-screen, and no taskbar button.  It's still *mapped*, so every
    winfo_ismapped()/geometry assertion behaves exactly as with a visible
    window — the developer just doesn't watch 30 windows strobe by."""
    try:
        win.attributes("-alpha", 0.0)
        win.geometry("+10000+10000")
        win.attributes("-toolwindow", True)
    except _tk_mod.TclError:
        pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Build an App() instance + tear it down cleanly per-test.

    Settings are sandboxed to a per-test temp file — App() otherwise reads
    AND WRITES the developer's real settings.json (last manufacturer, theme,
    extract options, …) on every _save_settings() a test triggers.

    Every root + Toplevel the test creates is made invisible (see
    ``_make_invisible``) so a local run doesn't flash windows at whoever is
    working on the machine."""
    import pinball_decryptor.app as app_mod
    monkeypatch.setattr(app_mod, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"))
    # Don't fire the real prerequisite probes: every mfr selection would
    # spawn a background thread + a storm of subprocess probes that outlive
    # the (sub-second) test and churn against the next Tk create.  Tests
    # that care about indicator state drive set_prereq_result() directly.
    monkeypatch.setattr(app_mod.App, "_kick_off_prereq_check",
                        lambda self, mfr: None)

    real_tk, real_toplevel = _tk_mod.Tk, _tk_mod.Toplevel

    class _InvisibleTk(real_tk):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            _make_invisible(self)

    class _InvisibleToplevel(real_toplevel):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            _make_invisible(self)

    monkeypatch.setattr(_tk_mod, "Tk", _InvisibleTk)
    monkeypatch.setattr(_tk_mod, "Toplevel", _InvisibleToplevel)

    from pinball_decryptor.app import App
    # NOTE: tk.Tk() can intermittently fail here on Windows with "couldn't
    # read file .../init.tcl" (antivirus/indexer briefly locking the Tcl
    # runtime scripts).  Don't retry in-process — a failed create leaves a
    # zombie Tcl interpreter that poisons every Tk instance created after
    # it in the same run.  Just re-run the suite.
    a = App()
    a.root.update()
    yield a
    # Cancel every pending after() callback before destroying so the
    # _poll_queue / _check_for_update closures don't fire against a
    # freed Tk interpreter (otherwise we get noisy
    # 'invalid command name "...poll_queue"' stderr at test teardown).
    # _poll_queue reschedules itself every 100ms, so a single sweep
    # can race against the next reschedule -- loop until nothing
    # pending remains.  Note: tk.call("after", "info") returns a TUPLE
    # of strings on most Tk builds (and an empty string on some), so
    # accept either.
    for _ in range(20):
        try:
            pending = a.root.tk.call("after", "info")
        except Exception:
            break
        if not pending:
            break
        if isinstance(pending, str):
            ids = pending.split()
        else:
            ids = list(pending)
        for after_id in ids:
            try:
                a.root.after_cancel(after_id)
            except Exception:
                pass
    a.root.destroy()


def _mfr_view_visible(window):
    """Return True iff the manufacturer working view is currently shown.

    v0.7.11 wrapped ``_mfr_view`` inside a Canvas (for the
    scrollable working-view introduced for the macOS FDA-banner-
    plus-log layout).  Tk's ``winfo_ismapped()`` on a canvas-item
    widget returns 1 the moment the widget is registered via
    ``create_window``, regardless of whether the canvas itself is
    currently visible — so ``_mfr_view.winfo_ismapped()`` is no
    longer a reliable visibility signal.  ``_mfr_view_wrapper``
    is the directly-packed widget and is what actually reflects
    user-visible state.
    """
    return bool(window._mfr_view_wrapper.winfo_ismapped())


def test_app_starts_on_picker(app):
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)
    assert app._current_mfr is None


def test_picker_has_all_manufacturer_cards(app):
    """The picker should have one card per registered manufacturer."""
    picker = app.window._picker_view
    assert len(picker._cards) == len(app._manufacturers)


def test_mfr_select_switches_to_mfr_view(app, manufacturers_by_key):
    spooky = manufacturers_by_key["spooky"]
    app._on_manufacturer_change(spooky)
    app.root.update(); app.root.update()
    assert app._current_mfr.key == "spooky"
    assert _mfr_view_visible(app.window)
    assert not app.window._picker_view.winfo_ismapped()


def test_transfer_panel_autofills_base_image_and_versions(
        app, manufacturers_by_key, tmp_path):
    """The redesigned transfer panel parses a version hint from each extract's
    recorded source filename, auto-fills the build's base image from the NEW
    extract's .extract_source.json (so it can't drift to the old version), and
    previews the output filename."""
    import os
    from pinball_decryptor.core import extract_source

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    w = app.window

    old = tmp_path / "old158"
    new = tmp_path / "new159"
    old.mkdir(); new.mkdir()
    # A real (empty) file standing in for the new version's card image.
    base_img = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    base_img.write_bytes(b"")
    old_img = _touch(tmp_path / "turtles_pro-1_58_1.1987.8G.sdcard.raw")
    extract_source.write_extract_source(str(old), old_img)
    extract_source.write_extract_source(str(new), str(base_img))

    w.transfer_src_var.set(str(old))
    w.transfer_dst_var.set(str(new))
    app.root.update()

    # Version hints parsed from the recorded source filenames.
    assert "1.58.1 (1987)" in w.transfer_src_ver_var.get()
    assert "1.59.0 (Release)" in w.transfer_dst_ver_var.get()
    # Base image auto-filled from the NEW extract's recorded source...
    assert os.path.normcase(w.transfer_newimg_var.get()) == os.path.normcase(
        str(base_img))
    assert "1.59.0 (Release)" in w.transfer_img_ver_var.get()
    # ...and the output-name preview reflects it (Stern's -modified suffix).
    assert "turtles_pro-1_59_0.Release.8G.sdcard-modified.raw" in \
        w.transfer_output_var.get()

    # A user-typed base image is never overwritten by the auto-fill.
    other = tmp_path / "turtles_pro-1_60_0.Release.8G.sdcard.raw"
    other.write_bytes(b"")
    w.transfer_newimg_var.set(str(other))
    w.transfer_dst_var.set(str(new))          # retrigger refresh
    app.root.update()
    assert os.path.normcase(w.transfer_newimg_var.get()) == os.path.normcase(
        str(other))


def _touch(p):
    p.write_bytes(b"")
    return str(p)


def test_sidecar_pending_fallback_without_tab_scan(app, manufacturers_by_key,
                                                   tmp_path):
    """Assignments recorded in a folder's .staged_changes.json must reach the
    Write staging path even when no Replace tab has scanned that folder this
    session (mods just transferred in, or the app reopened straight onto
    Write) — without the sidecar fallback the build silently dropped them."""
    from pinball_decryptor.core import staged_changes

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()

    assets = tmp_path / "extract159"
    (assets / "images").mkdir(parents=True)
    (assets / "images" / "backglass.png").write_bytes(b"STOCK")
    repl = tmp_path / "modded" / "backglass.png"
    repl.parent.mkdir(parents=True)
    repl.write_bytes(b"1987-ART")
    staged_changes.save(str(assets), {
        "image": {"images/backglass.png": str(repl)}})

    # No Replace tab has scanned this folder: the in-memory getter is empty...
    assert app.window.pending_image_assignments(str(assets)) is None
    # ...but the sidecar fallback rebuilds the pending tuple for the build.
    pend = app._sidecar_pending(str(assets), "image")
    assert pend is not None
    slots_by_rel, assignments = pend
    assert assignments == {"images/backglass.png": str(repl)}
    assert "images/backglass.png" in slots_by_rel


def test_back_returns_to_picker(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    app._on_back_to_picker()
    app.root.update()
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)


def test_cgc_trim_lock_engages_only_for_pf_extract(app, manufacturers_by_key,
                                                   tmp_path):
    """Selecting CGC leaves the Trim/pad checkbox a free toggle; scanning a
    Pulp Fiction extract (fixed-length bank slots) forces it on + disabled;
    scanning a WPC-remake extract (loose WAVs) unlocks it again."""
    import tkinter as tk
    cgc = manufacturers_by_key["cgc"]
    app._on_manufacturer_change(cgc)
    app.root.update()
    win = app.window

    # At manufacturer-select (no extract yet) the toggle is free.
    assert str(win._audio_trim_cb.cget("state")) != "disabled"

    # A Pulp Fiction extract (has data/*.bnk) forces the lock on.
    pf = tmp_path / "pf"
    (pf / "data").mkdir(parents=True)
    (pf / "data" / "pfmusic.bnk").write_bytes(b"")
    win._apply_audio_trim_lock(cgc, str(pf))
    assert str(win._audio_trim_cb.cget("state")) == "disabled"
    assert win.audio_trim_var.get() is True

    # A WPC-remake extract (loose WAVs, no bank) unlocks it again, and the
    # saved preference is restored rather than force-set.
    afm = tmp_path / "afm"
    (afm / "afmdata").mkdir(parents=True)
    (afm / "afmdata" / "s1.wav").write_bytes(b"")
    win._apply_audio_trim_lock(cgc, str(afm), persisted_trim=False)
    assert str(win._audio_trim_cb.cget("state")) != "disabled"
    assert win.audio_trim_var.get() is False


def test_audio_preview_limit_caps_trimmed_replacement(app,
                                                      manufacturers_by_key):
    """When Trim/pad is on and a replacement is longer than its slot, the
    preview stops at the slot length (matching the machine); the original
    always previews in full, and a shorter replacement isn't capped."""
    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update()
    win = app.window

    class _Slot:
        duration = 46.0

    rel = "data/pfmusic/pfmusic_sound_000.wav"
    win._audio_slots_by_rel = {rel: _Slot()}
    win._audio_current_rel = rel
    win._audio_assignments = {rel: "C:/rep.wav"}
    win._audio_keep_full_flags = {}
    win.audio_trim_var.set(True)
    win._audio_preview_dur = 61.8    # replacement longer than the 46s slot

    # Replacement + trim on + longer -> capped at the slot length.
    win.audio_source_var.set("rep")
    assert win._audio_compute_preview_limit() == 46.0

    # The original always plays in full -> no cap.
    win.audio_source_var.set("orig")
    assert win._audio_compute_preview_limit() is None

    # Trim off -> no cap even for the replacement.
    win.audio_source_var.set("rep")
    win.audio_trim_var.set(False)
    assert win._audio_compute_preview_limit() is None

    # A slot exempted via the per-slot "Full" flag -> no cap.
    win.audio_trim_var.set(True)
    win._audio_keep_full_flags = {rel: True}
    assert win._audio_compute_preview_limit() is None

    # Replacement SHORTER than the slot -> no cap (padding is silent).
    win._audio_keep_full_flags = {}
    win._audio_preview_dur = 30.0
    assert win._audio_compute_preview_limit() is None


def test_per_mfr_log_persists_across_switches(app, manufacturers_by_key):
    """Each mfr keeps its own Text widget; logs survive Back + re-pick."""
    spooky = manufacturers_by_key["spooky"]
    jjp = manufacturers_by_key["jjp"]

    app._on_manufacturer_change(spooky)
    app.root.update()
    app.window.append_log("spooky-test-line", "info")

    app._on_back_to_picker()
    app._on_manufacturer_change(jjp)
    app.root.update()
    app.window.append_log("jjp-test-line", "info")

    # Spooky's log still has its content cached
    spooky_log = app.window._log_widgets["spooky"]["text"].get("1.0", "end-1c")
    jjp_log = app.window._log_widgets["jjp"]["text"].get("1.0", "end-1c")
    assert "spooky-test-line" in spooky_log
    assert "spooky-test-line" not in jjp_log
    assert "jjp-test-line" in jjp_log
    assert "jjp-test-line" not in spooky_log


def test_prereq_indicators_render_for_current_mfr(app, manufacturers_by_key):
    """When a mfr is selected, its prereqs get [?] placeholder labels."""
    spooky = manufacturers_by_key["spooky"]
    app._on_manufacturer_change(spooky)
    app.root.update()
    # Indicator names should match the manufacturer's declared prereqs
    expected_names = {p.name for p in spooky.prerequisites}
    rendered_names = set(app.window._prereq_indicators.keys())
    assert rendered_names == expected_names


def test_manufacturer_picker_alphabetical_order(app):
    displays = [m.display for m in app._manufacturers]
    assert displays == sorted(displays, key=str.lower)


# ---------------------------------------------------------------------------
# BOF update-version date field (capabilities.write_version_date)
# ---------------------------------------------------------------------------

def _seed_bof_assets(tmp_path):
    marker = "# Update check string\n"
    (tmp_path / "updated_bash_profile").write_text(
        marker + "# 2025.06.23 \n", encoding="utf-8")
    (tmp_path / "updated_updatecode").write_text(
        marker + "# 2025.06.20 \n", encoding="utf-8")
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path)


def test_version_field_shown_for_bof_hidden_otherwise(
        app, manufacturers_by_key):
    # winfo_manager() == "pack" means the row is laid out on the Write tab
    # (winfo_ismapped() would read 0 unless that tab is the raised one).
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    assert app.window._write_version_frame.winfo_manager() == "pack"

    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assert app.window._write_version_frame.winfo_manager() == ""


def test_version_field_auto_shows_concrete_date(
        app, manufacturers_by_key, tmp_path):
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    w.write_assets_var.set(_seed_bof_assets(tmp_path))
    app.root.update()
    # Auto on by default → entry shows baseline+1, read-only, no override.
    assert w.write_version_auto_var.get() is True
    assert w.write_version_date_var.get() == "2025.06.24"
    assert w.write_version_override() is None
    assert w.write_version_validation_error() is None


def test_version_field_manual_override_and_validation(
        app, manufacturers_by_key, tmp_path):
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    w.write_assets_var.set(_seed_bof_assets(tmp_path))
    app.root.update()

    # Uncheck Auto → manual mode; a too-old date is rejected.
    w.write_version_auto_var.set(False)
    w._on_write_version_auto_toggle()
    w.write_version_date_var.set("2025.06.10")  # older than installed 06.23
    assert w.write_version_validation_error() is not None

    # A newer explicit date validates and is returned as the override.
    w.write_version_date_var.set("2026.01.15")
    assert w.write_version_validation_error() is None
    assert w.write_version_override() == "2026.01.15"

    # Garbage is rejected.
    w.write_version_date_var.set("not-a-date")
    assert w.write_version_validation_error() is not None


# ---------------------------------------------------------------------------
# Flash-image action (capabilities.flash_image — Stern Spike 2)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Staged-changes persistence (.staged_changes.json — pending Replace
# assignments survive quitting + re-opening the app)
# ---------------------------------------------------------------------------

def _seed_audio_assets(tmp_path):
    """An assets folder with two .wav slots + a .checksums.md5 baseline."""
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "idx0001.wav").write_bytes(b"RIFF\x00\x00\x00\x00")
    (tmp_path / "audio" / "idx0002.wav").write_bytes(b"RIFF\x00\x00\x00\x00")
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path)


def _scan_audio(window, assets_dir):
    """Synchronously scan + populate the audio tab for *assets_dir* (bypasses
    the worker thread so the test is deterministic)."""
    from pinball_decryptor.core.audio_slots import scan_audio_slots
    slots = scan_audio_slots(assets_dir)
    window._audio_scan_id += 1
    window._populate_audio_after_scan(slots, window._audio_scan_id, assets_dir)
    return slots


def test_audio_assignment_persists_across_relaunch(
        app, manufacturers_by_key, tmp_path):
    """Assigning a replacement writes the sidecar, and a fresh scan of the same
    folder (simulating a quit + re-open) restores the assignment."""
    from pinball_decryptor.core import staged_changes
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_audio_assets(tmp_path)
    rep = tmp_path / "new_song.wav"
    rep.write_bytes(b"RIFF\x00\x00\x00\x00")

    w.write_assets_var.set(assets)
    _scan_audio(w, assets)
    # Assign as the GUI handler does, then persist.
    w._audio_assignments["audio/idx0001.wav"] = str(rep)
    w._save_staged_changes()

    saved = staged_changes.load(assets)
    assert saved["audio"]["audio/idx0001.wav"] == str(rep)

    # Simulate a relaunch: blow away in-memory state, re-scan the folder.
    w._audio_assignments = {}
    w._audio_scan_dir = ""
    _scan_audio(w, assets)
    assert w._audio_assignments == {"audio/idx0001.wav": str(rep)}


def test_missing_replacement_not_restored(
        app, manufacturers_by_key, tmp_path):
    """A persisted replacement whose source file was deleted is dropped on
    restore (not surfaced as a broken assignment)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_audio_assets(tmp_path)
    rep = tmp_path / "gone.wav"
    rep.write_bytes(b"RIFF\x00\x00\x00\x00")
    w.write_assets_var.set(assets)
    _scan_audio(w, assets)
    w._audio_assignments["audio/idx0001.wav"] = str(rep)
    w._save_staged_changes()

    rep.unlink()                      # user deleted the replacement file
    w._audio_assignments = {}
    w._audio_scan_dir = ""
    _scan_audio(w, assets)
    assert w._audio_assignments == {}


def test_save_preserves_other_tabs_sections(
        app, manufacturers_by_key, tmp_path):
    """Saving from the audio tab must not clobber a video section persisted
    while the video tab was scanned for the same folder."""
    from pinball_decryptor.core import staged_changes
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_audio_assets(tmp_path)
    w.write_assets_var.set(assets)
    # Pre-seed a video section (as if the video tab had saved earlier).
    staged_changes.save(assets, {"video": {"video/intro.mov": "C:/x.mp4"}})

    _scan_audio(w, assets)            # only the audio tab is live for this folder
    w._audio_assignments["audio/idx0002.wav"] = str(tmp_path / "audio"
                                                     / "idx0001.wav")
    w._save_staged_changes()

    saved = staged_changes.load(assets)
    assert saved["video"] == {"video/intro.mov": "C:/x.mp4"}   # untouched
    assert "audio/idx0002.wav" in saved["audio"]


# ---------------------------------------------------------------------------
# monkeybug UI batch: Scan/Browse busy state, column-width persistence,
# responsive intro-text wrapping
# ---------------------------------------------------------------------------

def test_scan_buttons_built_for_every_replace_tab(app):
    # All four Replace tabs are built at construction, so their Scan/Browse
    # buttons register up front (independent of the selected manufacturer).
    for key in ("audio", "video", "image", "text"):
        assert key in app.window._scan_buttons
        assert key in app.window._browse_buttons


def test_set_tab_scanning_toggles_button_state(app):
    w = app.window
    scan = w._scan_buttons["audio"]
    browse = w._browse_buttons["audio"]

    w._set_tab_scanning("audio", True)
    assert "Scanning" in scan.cget("text")
    assert str(scan.cget("state")) == "disabled"
    assert str(browse.cget("state")) == "disabled"

    w._set_tab_scanning("audio", False)
    assert scan.cget("text") == "Scan"
    assert str(scan.cget("state")) == "normal"
    assert str(browse.cget("state")) == "normal"


def test_set_tab_scanning_tolerates_unknown_tab(app):
    app.window._set_tab_scanning("nope", True)   # no raise


def test_column_width_change_persists_and_is_idempotent(app):
    w = app.window
    captured = []
    w._on_column_widths_change = lambda widths: captured.append(widths)
    cols = ("#0", "len", "fmt", "rep", "loop")

    w._audio_tree.column("fmt", width=137)
    w._save_tree_columns(w._audio_tree, "audio", cols)
    assert captured and captured[-1]["audio"]["fmt"] == 137

    # No real change → no second callback.
    n = len(captured)
    w._save_tree_columns(w._audio_tree, "audio", cols)
    assert len(captured) == n


def test_saved_column_widths_restored_on_persist(app):
    w = app.window
    w._saved_column_widths["video"] = {"res": 222}
    w._persist_tree_columns(
        w._video_tree, "video", ("#0", "len", "res", "fmt", "rep"))
    assert int(w._video_tree.column("res", "width")) == 222


def test_register_responsive_wrap_applies_current_width(app):
    import tkinter as tk
    w = app.window
    app.root.update()
    lbl = tk.Label(app.root, text="x", wraplength=50)
    w._register_responsive_wrap(lbl, margin=40, minimum=100)
    cw = w._mfr_view_canvas.winfo_width()
    if cw > 1:                                    # canvas has been laid out
        assert int(str(lbl.cget("wraplength"))) == max(100, cw - 40)
    # The four Replace-tab intros are registered.
    assert len(w._responsive_wrap_labels) >= 4


def test_flash_frame_shown_for_stern_hidden_otherwise(
        app, manufacturers_by_key):
    # winfo_manager() == "pack" means the Flash-image frame is laid out on the
    # Write tab (winfo_ismapped() reads 0 unless that tab is raised).
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    # Pin the Spike 2 era: a saved Whitestar MAME-zip Extract input would flip
    # the era during the badge refresh (flashing is a Spike-2-only capability,
    # correctly hidden for the capture-only Whitestar era — see below).  Clear
    # the input + force the era so the assertion is deterministic.
    app.window.extract_input_var.set("")
    stern.set_era("spike2")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    assert app.window._flash_frame.winfo_manager() == "pack"

    # Whitestar (MAME capture) era has no flash capability → frame hidden.
    stern.set_era("whitestar")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    assert app.window._flash_frame.winfo_manager() == ""

    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assert app.window._flash_frame.winfo_manager() == ""


def test_write_build_button_folds_cancel_and_lives_in_toolbar(
        app, manufacturers_by_key):
    """monkeybug Write-tab rework: Build/Revert moved into the Modified Files
    toolbar, the standalone Cancel widget is gone (Build doubles as a live
    Cancel), and the redundant "Output: <full path>" line is gone for
    SD-card-image plugins — it shows only the distinct build name when the
    plugin renames its builds (write_output_suffix), else nothing."""
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.window.extract_input_var.set("")
    stern.set_era("spike2")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    w = app.window
    try:
        # The separate Cancel widget is gone.
        assert not hasattr(w, "_write_cancel_btn")
        # Build button is a descendant of the preview frame (its toolbar).
        assert str(w._write_btn).startswith(str(w._write_preview_frame) + ".")
        # Redundant "Output: <full path>" line suppressed for flash_image
        # plugins; with an original picked, Stern's -modified suffix shows
        # as a bare "Builds: <name>" instead.
        w.write_upd_var.set("")
        w._update_write_filename()
        assert w._write_filename_lbl.cget("text") == ""
        w.write_upd_var.set("C:/cards/game-1_0_0.sdcard.raw")
        w._update_write_filename()
        assert (str(w._write_filename_lbl.cget("text"))
                == "Builds: game-1_0_0.sdcard-modified.raw")
        w.write_upd_var.set("")
        # Build ⇄ Cancel fold: flips to a live Cancel mid-run, restores after.
        idle = w._write_btn.cget("text")
        assert idle != "Cancel"
        w.set_running(True, mode="write")
        assert w._write_btn.cget("text") == "Cancel"
        w.set_running(False, mode="write")
        assert w._write_btn.cget("text") == idle
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_capture_help_line_removed_for_noncapture_plugin(
        app, manufacturers_by_key):
    """The capture-help line is fully unpacked (not just blanked) for a
    non-capture plugin, so it can't reserve an empty line between the
    Output-folder warning and the Extract row and skew the 3-step spacing
    (monkeybug Extract #1).  winfo_manager() == "" means not managed."""
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    stern.set_era("spike2")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    try:
        assert app.window._capture_help.winfo_manager() == ""
        # A capture plugin (Williams) re-packs the help line — the other side
        # of the toggle, so forgetting it for Stern can't leave it gone.
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["williams"])
        app.root.update()
        assert app.window._capture_help.winfo_manager() == "pack"
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_whitestar_detect_badge_notes_extract_only(
        app, manufacturers_by_key, tmp_path):
    # Neither the picker card nor the era switcher conveys a *file's* per-era
    # capability, so the working view flags a capture/extract-only file via its
    # detect badge.  A Whitestar MAME ROM should pick up the "(extract only)"
    # note; a full Spike-2 era never does.
    from tests.test_pinmame_classic import _make_rom_zip, _a_whitestar_key
    from pinball_decryptor.plugins.pinmame_classic.games import GAME_DB
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    try:
        info = GAME_DB[_a_whitestar_key()]
        z = _make_rom_zip(tmp_path / f"{info['family']}.zip",
                          info["game_roms"], info["sound_roms"],
                          dmd_roms=info["dmd_roms"])
        app.window.extract_input_var.set(str(z))
        app.window._update_extract_badge()
        app.root.update()
        txt = app.window._extract_badge.cget("text")
        assert "extract only" in txt.lower(), txt
    finally:
        # Restore the shared singleton's era and leave the app on a clean
        # (non-capture) view so the fixture teardown destroys cleanly.
        stern.set_era("spike2")
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_era_switcher_pills_flip_era_and_input_label(app, manufacturers_by_key):
    # The header era switcher (multi-era plugins only) flips the active era +
    # the era-specific input label, and clears the now-wrong input.  Single-era
    # plugins show no pills.
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    win = app.window
    try:
        # Force a known starting state: a restored Whitestar input path from an
        # earlier test would otherwise auto-switch the era out from under us.
        win.extract_input_var.set("")
        stern.set_era("spike2")
        win.apply_manufacturer(stern, reset_era=False)
        app.root.update()
        assert set(win._era_badge_widgets) == {"spike2", "whitestar"}
        assert stern.current_era == "spike2"
        assert win._extract_input_lbl.cget("text") == "Card image:"

        win.extract_input_var.set("dummy.img")
        # Switching era must re-run the prereq probes (the new era has its own),
        # not leave them greyed — spy on the App's probe worker to prove it.
        kicked = []
        orig_kick = app._kick_off_prereq_check
        app._kick_off_prereq_check = lambda m: kicked.append(m)
        try:
            win._on_era_badge_click("whitestar")
            app.root.update()
        finally:
            app._kick_off_prereq_check = orig_kick
        assert stern.current_era == "whitestar"
        assert win._extract_input_lbl.cget("text") == "ROM zip:"
        assert win.extract_input_var.get() == ""   # cleared on era switch
        assert kicked and kicked[-1].current_era == "whitestar"  # check re-run

        # A single-era plugin surfaces no pills.
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["jjp"])
        app.root.update()
        assert win._era_badge_widgets == {}
    finally:
        stern.set_era("spike2")
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_path_history_records_dedupes_and_caps(app, manufacturers_by_key):
    """Path boxes keep a per-manufacturer recent-paths history (monkeybug):
    recorded at run start, most recent first, deduped case-insensitively,
    capped, and pushed into the window for the comboboxes' dropdowns."""
    import copy
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    before = copy.deepcopy(app._settings.get("path_history", {}))
    try:
        for i in range(8):
            app._record_path_history(extract_input=f"C:/imgs/card{i}.raw")
        hist = app._settings["path_history"]["stern"]["extract_input"]
        assert len(hist) == app._PATH_HISTORY_MAX
        assert hist[0].endswith("card7.raw")
        # Re-recording an older path moves it to the front without
        # duplicating (case-insensitive on purpose — Windows paths).
        app._record_path_history(extract_input="C:/IMGS/CARD5.RAW")
        hist = app._settings["path_history"]["stern"]["extract_input"]
        assert len(hist) == app._PATH_HISTORY_MAX
        assert hist[0] == "C:/IMGS/CARD5.RAW"
        assert sum("card5" in p.lower() for p in hist) == 1
        # The window sees the same lists (the dropdowns read _path_history).
        assert app.window._path_history["extract_input"] == hist
    finally:
        # Restore the on-disk-backed history before anything can save it.
        app._settings["path_history"] = before
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_path_boxes_are_history_comboboxes(app, manufacturers_by_key):
    """The path fields are editable comboboxes whose dropdown lists the
    recent paths for their field, refreshed on every open (postcommand),
    while typing still round-trips through the shared textvariable."""
    from tkinter import ttk as _ttk
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    w = app.window
    try:
        combos = [c for c in w._extract_input_row.winfo_children()
                  if isinstance(c, _ttk.Combobox)]
        assert len(combos) == 1
        combo = combos[0]
        w.set_path_history({"extract_input": ["C:/one.raw", "C:/two.raw"]})
        # Run what opening the dropdown runs.
        w.root.tk.call(str(combo.cget("postcommand")))
        assert list(combo.cget("values")) == ["C:/one.raw", "C:/two.raw"]
        w.extract_input_var.set("typed.raw")
        assert combo.get() == "typed.raw"
    finally:
        w.extract_input_var.set("")
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_help_button_and_per_tab_content(app, manufacturers_by_key):
    """The header "?" opens the per-tab tips modal (monkeybug): shown only
    in the working view, and every notebook tab caption has help content so
    no tab opens an empty modal."""
    from pinball_decryptor.gui.help_dialog import HELP_CONTENT, show_tab_help
    w = app.window
    assert w._help_btn.winfo_manager() == ""      # hidden on the picker
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    try:
        assert w._help_btn.winfo_manager() == "pack"
        for tab_id in w._notebook.tabs():
            caption = w._notebook.tab(tab_id, "text").strip()
            assert caption in HELP_CONTENT, caption
        dlg = show_tab_help(app.root, "Write", w._current_theme)
        try:
            assert "Write" in dlg.title()
        finally:
            dlg.destroy()
        app._on_back_to_picker()
        app.root.update()
        assert w._help_btn.winfo_manager() == ""  # hidden again on Back
    finally:
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_settings_gear_and_prereq_strip_autohide(app, manufacturers_by_key):
    """The header ⚙ replaces the old button row (monkeybug: settings live in
    a dropdown, not permanent top-bar clutter), and the Prerequisites strip
    tucks itself away once every probe comes back green — reappearing the
    moment anything is missing."""
    w = app.window
    assert w._gear_btn.winfo_manager() == "pack"  # visible on the picker too
    label, missing = w._prereq_menu_summary()     # no mfr yet -> "none"
    assert "none" in label and not missing
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    try:
        names = list(w._prereq_indicators)
        assert names                              # stern has prereqs
        assert w._prereqs_frame.winfo_manager() == "pack"
        assert "checking" in w._prereq_menu_summary()[0]
        # All green -> strip hides; menu summary says ready.
        for name in names:
            w.set_prereq_result(name, True, "ok")
        assert w._prereqs_frame.winfo_manager() == ""
        label, missing = w._prereq_menu_summary()
        assert "ready" in label and not missing
        # One goes missing -> strip comes back; Install entry re-arms.
        w.set_prereq_result(names[0], False, "gone")
        assert w._prereqs_frame.winfo_manager() == "pack"
        label, missing = w._prereq_menu_summary()
        assert "1 missing" in label and missing
        # Update-check busy state is just a flag now (menu built per click).
        w.set_update_check_running(True)
        assert w._update_check_busy
        w.set_update_check_running(False)
        assert not w._update_check_busy
        # A found update puts a ● on the gear, a Download entry at the top
        # of the menu, and the outcome in the log (David).
        app._handle_update_check_result(
            ("99.0.0", "https://example.com/release", ""), False)
        assert "●" in w._gear_btn.cget("text")
        upd_menu = w._build_settings_menu()
        assert "Download update v99.0.0" in upd_menu.entrycget(0, "label")
        assert "Update available: v99.0.0" in w._log_text.get("1.0", "end-1c")
        # The dropdown itself builds (this is the code a real ⚙ click runs —
        # nothing else exercises it) and carries the expected entries.
        menu = w._build_settings_menu()
        labels = [menu.entrycget(i, "label")
                  for i in range(menu.index("end") + 1)
                  if menu.type(i) not in ("separator", "tearoff")]
        joined = "\n".join(labels)
        # Theme entry is a dynamic verb ("Switch to dark/light theme") whose
        # direction follows the OS default detected at startup.
        assert "Switch to dark theme" in joined or \
            "Switch to light theme" in joined
        assert "Check for updates" in joined
        assert "Voice recognition quality" in joined
        # Prerequisites are a cascade now (monkeybug): the cascade label IS
        # the status summary; the actions live in its submenu.
        assert "1 missing" in joined
        prereq_i = next(
            i for i in range(menu.index("end") + 1)
            if menu.type(i) == "cascade"
            and "Prerequisites" in menu.entrycget(i, "label"))
        sub = menu.nametowidget(menu.entrycget(prereq_i, "menu"))
        sub_labels = [sub.entrycget(i, "label")
                      for i in range(sub.index("end") + 1)
                      if sub.type(i) not in ("separator", "tearoff")]
        assert "Re-check prerequisites" in "\n".join(sub_labels)
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_help_window_singleton_and_tab_refresh(app, manufacturers_by_key):
    """"?" re-uses one tips window instead of stacking new ones, and a
    notebook tab switch re-renders the open window (monkeybug round 2)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    try:
        w._open_tab_help()
        dlg = w._help_window._dlg
        assert dlg is not None and dlg.winfo_exists()
        assert "Extract" in dlg.title()
        w._open_tab_help()                        # second click: same window
        assert w._help_window._dlg is dlg
        w._notebook.select(w._tab_write)          # tab switch: auto-refresh
        app.root.update()
        assert "Write" in dlg.title()
        w._help_window.close()
        assert not w._help_window.is_open()
        w._open_tab_help()                        # reopens cleanly after close
        assert w._help_window.is_open()
        w._help_window.close()
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_extract_options_persist_per_manufacturer(app, manufacturers_by_key):
    """Auto-name + extract-category checkboxes stick across a leave-and-return
    (the same settings.json round trip a restart does) and stay per-mfr
    (monkeybug: 'do not stick between sessions')."""
    w = app.window
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.root.update()
    try:
        assert w._extract_category_vars           # stern advertises categories
        cat0 = next(iter(w._extract_category_vars))
        w.transcribe_var.set(True)
        w.music_id_var.set(True)
        w._extract_category_vars[cat0].set(False)
        # Leave for another mfr: spooky starts from ITS clean defaults...
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()
        assert not w.transcribe_var.get()
        assert not w.music_id_var.get()
        # ...and returning to stern restores the saved ticks.
        app._on_manufacturer_change(stern)
        app.root.update()
        assert w.transcribe_var.get()
        assert w.music_id_var.get()
        assert not w._extract_category_vars[cat0].get()
        # The other categories kept their default-on state.
        others = [k for k in w._extract_category_vars if k != cat0]
        assert all(w._extract_category_vars[k].get() for k in others)
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_picker_time_log_lines_flush_into_first_log(app, manufacturers_by_key):
    """Lines logged while the picker is showing (the startup update check)
    aren't dropped — they flush into the first manufacturer log that opens,
    links included."""
    w = app.window
    w.append_log("startup-buffered-line", "info")
    w.append_log_link("startup-buffered-link", "https://example.com/x")
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    try:
        log = w._log_text.get("1.0", "end-1c")
        assert "startup-buffered-line" in log
        assert "startup-buffered-link" in log
        assert not w._pending_log                 # buffer drained
    finally:
        app._on_back_to_picker()
        app.root.update()

# ---------------------------------------------------------------------------
# Replace Image: "Group by scene" / "Changed only" list modes + group actions
# ---------------------------------------------------------------------------

def _seed_image_assets(tmp_path):
    """An assets folder with three radium-frame PNGs (one animation), one
    loose PNG, the extractor manifests describing them, and a baseline."""
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    frames = ["radimg_Char_Select_8x8_00000001.png",
              "radimg_Char_Select_8x8_00000002.png",
              "radimg_8x8_00000003.png"]
    for fn in frames:
        (st / fn).write_bytes(b"\x89PNG-fake")
    (tmp_path / "images" / "loose").mkdir()
    (tmp_path / "images" / "loose" / "logo.png").write_bytes(b"\x89PNG-fake")
    card = "/game/scenes/a1b2c3d4e5f6/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        # File order is NOT play order: offsets 300, 100, 200.
        f.write("scene_textures/%s\t%s\t300\t16\t8\t8\t5\n" % (frames[2], card))
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (frames[0], card))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (frames[1], card))
    with open(tmp_path / "images" / "manifest.txt", "w",
              encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n")
        f.write("loose/logo.png\t/game/assets/loose/logo.png\t9\n")
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path)


def _scan_images(window, assets_dir):
    """Synchronously scan + populate the image tab for *assets_dir* (bypasses
    the worker thread so the test is deterministic)."""
    from pinball_decryptor.core.image_slots import scan_image_slots
    slots = scan_image_slots(assets_dir, probe=False)
    groups, occ = window._scan_image_groups(assets_dir)
    window._image_scan_id += 1
    window._populate_image_after_scan(
        slots, window._image_scan_id, assets_dir, groups, occ)
    return slots


def test_image_group_scan_parses_manifests(tmp_path):
    """The manifest parser groups radium frames under their container with a
    friendly element-name label, counts dedup occurrences, and yields nothing
    for a folder with no manifests."""
    from pinball_decryptor.gui.main_window import MainWindow
    assets = _seed_image_assets(tmp_path)
    groups, occ = MainWindow._scan_image_groups(assets)
    key = "rad::/game/scenes/a1b2c3d4e5f6/scene.radium"
    rel1 = "images/scene_textures/radimg_Char_Select_8x8_00000001.png"
    # Label = element hint + searchable container-hash shorthand: hints
    # repeat across sibling containers, so the hash half disambiguates.
    assert groups[rel1] == (key, "Char_Select · a1b2c3d4", 100)
    # The nameless frame inherits the group label; order = its data offset.
    rel3 = "images/scene_textures/radimg_8x8_00000003.png"
    assert groups[rel3] == (key, "Char_Select · a1b2c3d4", 300)
    assert occ[rel1] == 1
    assert groups["images/loose/logo.png"] == (
        "dir::/game/assets/loose", "/game/assets/loose", 0)
    empty = tmp_path / "no_manifests"
    empty.mkdir()
    assert MainWindow._scan_image_groups(str(empty)) == ({}, {})


def test_image_grouped_mode_and_changed_only(app, manufacturers_by_key,
                                             tmp_path):
    """Grouped mode nests slot rows (same iids) under collapsed per-scene
    parents in play order; Changed-only prunes untouched rows and, in grouped
    mode, whole untouched groups; flat mode is unchanged."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_image_assets(tmp_path)
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    tree = w._image_tree
    rels = ["images/scene_textures/radimg_Char_Select_8x8_00000001.png",
            "images/scene_textures/radimg_Char_Select_8x8_00000002.png",
            "images/scene_textures/radimg_8x8_00000003.png",
            "images/loose/logo.png"]

    # Flat mode: exactly the rel-path rows, path-sorted, no parents.
    assert list(tree.get_children()) == sorted(rels, key=str.lower)
    assert "4 images" in w.image_status_var.get()

    w.image_group_by_scene_var.set(True)
    tops = list(tree.get_children())
    assert all(t.startswith("::grp::") for t in tops)
    grp = [t for t in tops if "Char_Select" in tree.item(t, "text")]
    assert len(grp) == 1
    assert "Char_Select · a1b2c3d4 — 3 images" in tree.item(grp[0], "text")
    assert not tree.item(grp[0], "open")          # inserted collapsed
    # Children keep the slot iid and sit in play order (data offset).
    assert list(tree.get_children(grp[0])) == rels[:3]
    # Counts stay over image rows, not group headers.
    assert "4 images" in w.image_status_var.get()

    # Search matches the group LABEL even though the files are hash-named —
    # by element hint or by the container-hash shorthand.
    w.image_search_var.set("char_sel")
    tops = list(tree.get_children())
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 3
    w.image_search_var.set("a1b2c3d4")
    tops = list(tree.get_children())
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 3
    w.image_search_var.set("")

    # Changed-only: an assignment keeps its group; the untouched group goes.
    w._image_assignments[rels[0]] = str(tmp_path / "rep.png")
    w.image_changed_only_var.set(True)
    tops = list(tree.get_children())
    assert len(tops) == 1
    assert "Char_Select · a1b2c3d4 — 1 image" in tree.item(tops[0], "text")
    assert list(tree.get_children(tops[0])) == [rels[0]]
    # ...and in flat mode only the assigned row survives.
    w.image_group_by_scene_var.set(False)
    assert list(tree.get_children()) == [rels[0]]

    w.image_changed_only_var.set(False)
    w._image_assignments.clear()


def test_image_group_bulk_assign_blank_clear(app, manufacturers_by_key,
                                             tmp_path):
    """The group-header bulk actions run through the normal assignment
    plumbing: assign-to-all, blank-to-all (transparent dotfile PNG, invisible
    to a re-scan) and clear-all, persisted to the sidecar each time."""
    import os as _os
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.core.image_slots import scan_image_slots
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_image_assets(tmp_path)
    rep = tmp_path / "rep.png"
    rep.write_bytes(b"\x89PNG-fake")
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    w.image_group_by_scene_var.set(True)
    tree = w._image_tree
    grp = [t for t in tree.get_children()
           if "Char_Select" in tree.item(t, "text")][0]
    kids = tuple(tree.get_children(grp))

    w._image_group_apply(grp, kids, str(rep))
    assert {r: p for r, p in w._image_assignments.items()
            if r in kids} == {k: str(rep) for k in kids}
    assert staged_changes.load(assets)["image"] == w._image_assignments
    # The group survives the refresh and is re-selected.
    assert tree.selection() == (grp,)

    # Blank: the transparent source is created once, as a dotfile the slot
    # scanner skips, and assigned to every child.
    blank = w._ensure_blank_image()
    assert blank and blank.endswith(".blank.png")
    assert _os.path.isfile(blank)
    w._image_group_apply(grp, kids, blank)
    assert all(w._image_assignments[k] == blank for k in kids)
    assert not any(".blank" in s.rel_path
                   for s in scan_image_slots(assets, probe=False))

    # Clear drops exactly the group's assignments.
    w._image_group_apply(grp, kids, None)
    assert w._image_assignments == {}
    assert staged_changes.load(assets)["image"] == {}


def test_image_group_iid_guards_select_and_meta(app, manufacturers_by_key,
                                                tmp_path):
    """Selecting a group header previews its first child's original (no
    crash, replacement pane cleared), and a late metadata probe update lands
    on the nested row."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_image_assets(tmp_path)
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    w.image_group_by_scene_var.set(True)
    tree = w._image_tree
    grp = [t for t in tree.get_children()
           if "Char_Select" in tree.item(t, "text")][0]
    tree.selection_set(grp)
    w._image_on_tree_select()                     # must not raise
    assert w._image_current_rel is None
    # A probe result for a nested child still updates its row in place.
    child = tree.get_children(grp)[0]
    w._apply_image_meta(w._image_scan_id, child, None)
    assert tree.exists(child)
