"""GUI construction smoke tests.

These exercise the picker -> mfr-view navigation flow and per-mfr log
swapping without actually running pipelines.  Skipped when Tk can't
open a display (typical for headless Linux CI without xvfb).
"""

import pytest

from tests.conftest import HAS_DISPLAY


pytestmark = pytest.mark.skipif(
    not HAS_DISPLAY, reason="no Tk display available")


@pytest.fixture
def app():
    """Build an App() instance + tear it down cleanly per-test."""
    from pinball_decryptor.app import App
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


def test_back_returns_to_picker(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    app._on_back_to_picker()
    app.root.update()
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)


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
    Cancel), and the redundant "Output:" line is blank for SD-card-image
    plugins."""
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
        # Redundant Output line suppressed for flash_image plugins.
        w._update_write_filename()
        assert w._write_filename_lbl.cget("text") == ""
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
