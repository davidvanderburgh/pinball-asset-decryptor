"""GUI construction smoke tests.

These exercise the picker -> mfr-view navigation flow and per-mfr log
swapping without actually running pipelines.  Skipped when Tk can't
open a display (typical for headless Linux CI without xvfb).
"""

import os

import pytest

from tests.conftest import HAS_DISPLAY


# Every test here builds a full Tk App() (~0.5s setup) — tag them `gui` so a
# fast dev run can deselect the lot with -m "not gui".
pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


import re as _re_mod
import tkinter as _tk_mod

# The shapes Tcl reports when its runtime scripts can't be loaded: the direct
# read failures (Tcl's init.tcl, Tk's tk.tcl — "Can't find a usable tk.tcl"
# broke the v0.100.3 release CI run) and the follow-on symptom once a
# half-built interpreter is left behind.  Deliberately narrow — see the `app`
# fixture.
_TCL_RUNTIME_UNAVAILABLE = _re_mod.compile(
    r"init\.tcl|tk\.tcl|tcl_findLibrary")


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
    # Same sandboxing for the rolling on-disk log history — every
    # append_log() a test triggers would otherwise land in (and eventually
    # roll!) the developer's real session.log.
    from pinball_decryptor.core import session_log
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE",
                        str(tmp_path / "logs"))
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
    # runtime scripts; GitHub's windows-latest runner hits it too).  Don't
    # retry in-process — a failed create leaves a zombie Tcl interpreter that
    # poisons every Tk instance created after it in the same run.
    #
    # SKIP rather than error: the Tcl runtime failing to load is a property of
    # the machine, not of the code under test — it lands on a different,
    # always-unrelated test each time, and it failed two consecutive CI runs of
    # one release commit whose local runs passed.  A release must not hinge on
    # whether an indexer happened to hold init.tcl for a moment.  ONLY this
    # signature skips; any other TclError still fails the test, so a real GUI
    # regression can't hide behind it.
    try:
        a = App()
    except _tk_mod.TclError as exc:
        if _TCL_RUNTIME_UNAVAILABLE.search(str(exc)):
            pytest.skip("Tcl runtime transiently unavailable: %s" % exc)
        raise
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
    # No saved last_manufacturer (fresh sandboxed settings) -> picker.
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)
    assert app._current_mfr is None


def test_resolve_startup_manufacturer(all_manufacturers):
    """The launch-target decision: a saved key that still loads opens directly;
    a missing / stale key falls back to the picker (returns None).  Pure — no
    Tk — so it can't add to the init.tcl flake surface."""
    from pinball_decryptor.app import _resolve_startup_manufacturer as resolve
    stern = next(m for m in all_manufacturers if m.key == "stern")
    assert resolve(all_manufacturers, {"last_manufacturer": "stern"}) is stern
    assert resolve(all_manufacturers, {"last_manufacturer": "gone"}) is None
    assert resolve(all_manufacturers, {}) is None
    assert resolve(all_manufacturers, {"last_manufacturer": ""}) is None


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


def test_audio_group_duplicates_checkbox_only_for_cgc(
        app, manufacturers_by_key):
    """The Replace Audio 'Group duplicates' checkbox is packed only for
    plugins implementing find_duplicate_sounds (CGC — Pulp Fiction ships the
    same recording at several bank slots); everyone else must not see it."""
    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update(); app.root.update()
    assert win._audio_dup_group_cb.winfo_manager() == "pack"
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert win._audio_dup_group_cb.winfo_manager() == ""


def test_audio_experiment_buttons_only_for_stern(app, manufacturers_by_key):
    """Advanced… / Profile vs stock drive env vars read solely by the Spike 2
    encoder, so they are packed only for Stern.  The Trim/pad checkbox that
    shares their row is HIDDEN for Stern (Spike 2 always length-matches —
    batch 20) but stays for plugins where the toggle is real."""
    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert win._audio_trim_cb.winfo_manager() == ""
    assert win.audio_trim_var.get() is True     # forced on, just not shown
    assert win._audio_adv_btn.winfo_manager() == "pack"
    assert win._audio_profile_btn.winfo_manager() == "pack"
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert win._audio_adv_btn.winfo_manager() == ""
    assert win._audio_profile_btn.winfo_manager() == ""
    # The free toggle comes back for a plugin that doesn't force it.
    assert win._audio_trim_cb.winfo_manager() == "pack"


def test_audio_raw_encode_env_always_pinned(app):
    """The match-to-callouts shaper is retired (batch 20): App startup pins
    PAD_STERN_AUDIO_RAW=1 unconditionally, so the Stern encoder always writes
    replacements as provided — no toggle, no persisted setting."""
    import os
    assert os.environ.get("PAD_STERN_AUDIO_RAW") == "1"
    assert not hasattr(app.window, "audio_declick_var")


def test_stern_title_caption_from_vendor_filename(manufacturers_by_key):
    """Batch 20: the title bar identifies the game leanly — no platform echo,
    plus version + edition parsed off Stern's vendor filename."""
    from pinball_decryptor.core.registry import Game
    stern = manufacturers_by_key["stern"]
    g = Game(key="led_zeppelin", display="Led Zeppelin (Spike 2)",
             manufacturer_key="stern", era="spike2",
             notes="Spike 2 card image")
    cap = stern.title_caption(
        "X:/cards/led_zeppelin_le-1_22_0.Release.8G.sdcard.raw", g)
    assert cap == "Led Zeppelin v1.22.0 LE"
    # A renamed card still shows the bare title, never the platform suffix.
    assert stern.title_caption("X:/cards/backup.raw", g) == "Led Zeppelin"


def test_detected_game_caption_drives_title_bar(app):
    """The App composes the title bar from the detected-game caption (batch
    20) plus the loaded project (batch 19); losing the detection drops the
    caption again."""
    app._on_detected_game_change("Led Zeppelin v1.22 LE")
    assert "Led Zeppelin v1.22 LE" in app.root.title()
    app._on_detected_game_change(None)
    assert "Led Zeppelin" not in app.root.title()


def test_badge_row_hidden_until_it_carries_text(app, manufacturers_by_key):
    """Batch 20: the Extract detect-badge row packs only while it carries a
    warning ("Not recognised…" etc.); the happy path keeps it hidden (the
    game lives in the title bar) so it doesn't burn a blank line."""
    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    win.extract_input_var.set("")
    app.root.update()
    assert win._extract_badge_row.winfo_manager() == ""
    # An existing file the plugin does NOT recognise -> warning text -> row.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as fh:
        fh.write(b"not a card")
        bogus = fh.name
    try:
        win.extract_input_var.set(bogus)
        app.root.update()
        assert "Not recognised" in win._extract_badge.cget("text")
        assert win._extract_badge_row.winfo_manager() == "pack"
    finally:
        win.extract_input_var.set("")
        app.root.update()
        os.unlink(bogus)
    assert win._extract_badge_row.winfo_manager() == ""


def test_collect_project_stats_counts_and_changes(tmp_path):
    """The Project Info ⓘ stats (batch 20): asset counts by kind skip
    bookkeeping dot-dirs, total size includes them, and the Changed row folds
    staged picks + .orig build snapshots together."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.gui.main_window import MainWindow

    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    (proj / "audio" / "idx0001.wav").write_bytes(b"x" * 10)
    (proj / "audio" / "idx0002.wav").write_bytes(b"x" * 10)
    (proj / "video").mkdir()
    (proj / "video" / "clip.mp4").write_bytes(b"x" * 30)
    (proj / "images").mkdir()
    (proj / "images" / "logo.png").write_bytes(b"x" * 5)
    (proj / "notes.txt").write_bytes(b"x")
    # Bookkeeping: counts toward size on disk, not toward the asset rows.
    (proj / ".orig" / "audio").mkdir(parents=True)
    (proj / ".orig" / "audio" / "idx0001.wav").write_bytes(b"y" * 10)
    staged_changes.save(str(proj), {"audio": {"audio/idx0002.wav": "r.wav"}})

    rows = dict(MainWindow._collect_project_stats(str(proj)))
    assert rows["Audio"].startswith("2 file(s)")
    assert rows["Video"].startswith("1 file(s)")
    assert rows["Images"].startswith("1 file(s)")
    assert rows["Other files"].startswith("1 file(s)")
    assert "1 staged for the next build" in rows["Changed"]
    assert "1 changed by earlier builds" in rows["Changed"]
    assert "Project started" in rows


def test_project_mirror_label_follows_shared_var(app):
    """The Replace tabs' project rows are plain labels mirroring the shared
    project var (batch 20 — no fake-editable box, no jump button), with a
    pointer at the Extract tab while no project is loaded."""
    win = app.window
    win.write_assets_var.set("")
    assert "Extract tab" in win._project_mirror_var.get()
    win.write_assets_var.set(r"C:\proj\lz")
    assert win._project_mirror_var.get() == r"C:\proj\lz"
    win.write_assets_var.set("")
    assert "Extract tab" in win._project_mirror_var.get()


def test_audio_advanced_env_mirror(app, manufacturers_by_key, monkeypatch):
    """Advanced audio options persist and mirror into the PAD_STERN_* env
    vars; defaults clear every var so the engine baseline stays
    authoritative.  The retired shaper knobs (fade / cap / roll-off — batch
    20) are actively CLEARED even when a stale persisted config still carries
    them.  Machine-render previews point next to the build output."""
    import os
    for var in ("PAD_STERN_HEAD_MODE", "PAD_STERN_LEADOUT",
                "PAD_STERN_PREVIEW_DIR", "PAD_STERN_SLOT_SEED_DB"):
        monkeypatch.delenv(var, raising=False)
    # Simulate an old session's leftover experiment env.
    monkeypatch.setenv("PAD_STERN_FADE_MS", "80.0")
    monkeypatch.setenv("PAD_STERN_HEADROOM", "0.6")
    monkeypatch.setenv("PAD_STERN_LOWPASS_HZ", "0")

    # A stale persisted cfg may still carry the retired keys — they must be
    # ignored, not re-applied.
    cfg = {"fade_ms": 80, "headroom_pct": 60, "lowpass_hz": 0,
           "head_mode": "stock", "leadout": "stock", "previews": True,
           "slot_seed": True, "slot_seed_db": 65}
    app._on_audio_advanced_change(cfg)
    for var in ("PAD_STERN_FADE_MS", "PAD_STERN_HEADROOM",
                "PAD_STERN_LOWPASS_HZ"):
        assert var not in os.environ, var
    assert os.environ["PAD_STERN_HEAD_MODE"] == "stock"
    assert os.environ["PAD_STERN_LEADOUT"] == "stock"
    assert os.environ["PAD_STERN_SLOT_SEED_DB"] == "-65"
    assert app._settings["audio_advanced"] == cfg

    # Preview dir: gate on the current manufacturer without switching the
    # whole GUI (a full switch would leak state into later tests).
    monkeypatch.setattr(app, "_current_mfr", manufacturers_by_key["stern"])
    app._apply_audio_preview_env(os.path.join("X:", "out", "card.raw"))
    assert os.environ["PAD_STERN_PREVIEW_DIR"].endswith(
        "card_machine_previews")

    app._on_audio_advanced_change({})              # back to defaults
    for var in ("PAD_STERN_FADE_MS", "PAD_STERN_HEADROOM",
                "PAD_STERN_LOWPASS_HZ", "PAD_STERN_HEAD_MODE",
                "PAD_STERN_LEADOUT", "PAD_STERN_SLOT_SEED_DB"):
        assert var not in os.environ
    app._apply_audio_preview_env(os.path.join("X:", "out", "card.raw"))
    assert "PAD_STERN_PREVIEW_DIR" not in os.environ


def test_audio_advanced_modal_shaper_gone_and_grey_buttons(
        app, manufacturers_by_key):
    """Batch 20: the Advanced dialog no longer offers the match-to-callouts
    shaper or its fade/cap/roll-off knobs, its OK/Cancel are standard grey,
    and OK still applies the remaining options (anti-pop seed here)."""
    import os

    def _descendants(w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out += _descendants(c)
        return out

    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()

    win._open_audio_advanced()
    app.root.update()
    dlg = [c for c in win.root.winfo_children()
           if isinstance(c, _tk_mod.Toplevel)][-1]
    kids = _descendants(dlg)
    texts = [str(w.cget("text")) for w in kids if "text" in w.keys()]
    assert not any("Match audio replacements" in t for t in texts)
    assert not any("Edge fade length" in t for t in texts)
    assert not any("Treble roll-off" in t for t in texts)
    ok = next(w for w in kids if "text" in w.keys()
              and str(w.cget("text")) == "OK")
    cancel = next(w for w in kids if "text" in w.keys()
                  and str(w.cget("text")) == "Cancel")
    assert str(ok.cget("style")) in ("", "TButton")
    assert str(cancel.cget("style")) in ("", "TButton")
    seed_cb = next(w for w in kids if "text" in w.keys()
                   and "Anti-pop codec seed" in str(w.cget("text")))
    seed_cb.invoke()
    ok.invoke()
    app.root.update()
    assert app._settings["audio_advanced"]["slot_seed"] is True
    assert os.environ.get("PAD_STERN_SLOT_SEED_DB") == "-65"
    # Leave a clean slate for later tests.
    app._on_audio_advanced_change({})


def test_audio_group_duplicates_renders_two_level_tree(
        app, manufacturers_by_key):
    """With 'Group duplicates' on and a warm group cache, the audio list
    renders one parent per duplicate group (dup-scan order, members nested,
    'N of M modded' note) and every unique slot flat below; toggling off
    restores the flat list.  Parent rows must never collide with slot iids
    and must not offer per-slot actions."""
    from pinball_decryptor.core.audio_slots import AudioSlot
    from pinball_decryptor.gui.main_window import _AUD_DUP_GROUP_IID

    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update(); app.root.update()
    win = app.window

    rels = ["data/pfspeech/pfspeech_sound_000.wav",
            "data/pfspeechBEEPD/pfspeechBEEPD_sound_000.wav",
            "data/pfspeech/pfspeech_sound_001.wav"]
    win._audio_slots = [
        AudioSlot(rel_path=r, abs_path="X:/pf/" + r, ext=".wav",
                  info=None, size=0) for r in rels]
    win._audio_slots_by_rel = {s.rel_path: s for s in win._audio_slots}
    win._audio_scan_dir = "X:/pf"
    win._audio_dup_scan_dir = "X:/pf"
    win._audio_dup_groups = [("pfspeech_sound_000", "0:01.000",
                              [rels[0], rels[1]])]
    win._audio_assignments = {rels[0]: "C:/mods/new.wav"}

    win.audio_group_dups_var.set(True)     # trace triggers the refresh
    app.root.update()
    tree = win._audio_tree
    top = tree.get_children()
    giid = _AUD_DUP_GROUP_IID + "0"
    assert list(top) == [giid, rels[2]]    # group first, unique flat below
    assert set(tree.get_children(giid)) == {rels[0], rels[1]}
    assert "2 copies" in tree.item(giid, "text")
    assert "1 of 2 modded" in tree.item(giid, "values")[2]

    win.audio_group_dups_var.set(False)
    app.root.update()
    assert set(tree.get_children()) == set(rels)  # flat again


def test_audio_apply_to_all_copies_fans_out_assignment(
        app, manufacturers_by_key):
    """Right-click 'Apply to all copies' pushes one slot's replacement onto
    every other copy in its duplicate group, so the machine can't play a
    still-stock twin — the action that replaced the removed fan-out dialog."""
    from pinball_decryptor.core.audio_slots import AudioSlot

    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update(); app.root.update()
    win = app.window

    rels = ["data/pfspeech/pfspeech_sound_152.wav",
            "data/pfspeechBEEPD/pfspeechBEEPD_sound_152.wav",
            "data/pfsndui/pfsndui_sound_011.wav",
            "data/pfsndfx/pfsndfx_sound_003.wav"]      # a non-duplicate slot
    win._audio_slots = [
        AudioSlot(rel_path=r, abs_path="X:/pf/" + r, ext=".wav",
                  info=None, size=0) for r in rels]
    win._audio_slots_by_rel = {s.rel_path: s for s in win._audio_slots}
    win._audio_scan_dir = "X:/pf"
    win._audio_dup_scan_dir = "X:/pf"
    win._audio_dup_groups = [("pfspeech_sound_152", "0:02.500", rels[:3])]
    win._audio_assignments = {rels[0]: "C:/mods/royale.wav"}

    # Siblings resolve only within the group, and only present slots.
    assert set(win._audio_dup_siblings(rels[0])) == {rels[1], rels[2]}
    assert win._audio_dup_siblings(rels[3]) == []      # not in any group

    win._audio_fanout_to_copies(rels[0])
    assert win._audio_assignments[rels[1]] == "C:/mods/royale.wav"
    assert win._audio_assignments[rels[2]] == "C:/mods/royale.wav"
    assert rels[3] not in win._audio_assignments       # untouched


def test_audio_group_duplicates_off_by_default_and_not_remembered(
        app, manufacturers_by_key):
    """'Group duplicates' starts unchecked and isn't carried across a
    manufacturer switch — it kicks a ~10 s scan, so it must be opt-in each
    session, never restored on."""
    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update()
    assert not win.audio_group_dups_var.get()
    win.audio_group_dups_var.set(True)
    app.root.update()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update()
    assert not win.audio_group_dups_var.get()


def test_audio_group_duplicates_shows_busy_overlay(app, manufacturers_by_key):
    """The bank scan runs ~10 s on a worker thread, so the busy painter must
    clear the list to a centred 'scanning' overlay the instant grouping
    starts — otherwise the checkbox click looks like a dead pause."""
    from pinball_decryptor.core.audio_slots import AudioSlot

    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update()
    win = app.window
    win._audio_slots = [AudioSlot(rel_path="data/pfspeech/a.wav",
                                  abs_path="X:/pf/a.wav", ext=".wav",
                                  info=None, size=0)]
    win._audio_slots_by_rel = {s.rel_path: s for s in win._audio_slots}
    win._refresh_audio_list()
    assert win._audio_tree.get_children()               # flat row present

    win._set_audio_dup_scanning(True)
    assert not win._audio_tree.get_children()            # cleared to overlay
    assert win._audio_empty.winfo_manager() == "place"
    assert "duplicates" in win._audio_empty.cget("text").lower()
    assert win.audio_status_var.get() == "Grouping duplicates…"


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
    Pulp Fiction extract (fixed-length bank slots) forces trim on and HIDES
    the checkbox (batch 20 — mandatory behavior isn't shown as an option);
    scanning a WPC-remake extract (loose WAVs) brings the toggle back."""
    cgc = manufacturers_by_key["cgc"]
    app._on_manufacturer_change(cgc)
    app.root.update()
    win = app.window

    # At manufacturer-select (no extract yet) the toggle is free + visible.
    assert str(win._audio_trim_cb.cget("state")) != "disabled"
    assert win._audio_trim_cb.winfo_manager() == "pack"

    # A Pulp Fiction extract (has data/*.bnk) forces the lock on.
    pf = tmp_path / "pf"
    (pf / "data").mkdir(parents=True)
    (pf / "data" / "pfmusic.bnk").write_bytes(b"")
    win._apply_audio_trim_lock(cgc, str(pf))
    assert win._audio_trim_cb.winfo_manager() == ""
    assert win._audio_trim_forced() is True
    assert win.audio_trim_var.get() is True

    # A WPC-remake extract (loose WAVs, no bank) unlocks it again, and the
    # saved preference is restored rather than force-set.
    afm = tmp_path / "afm"
    (afm / "afmdata").mkdir(parents=True)
    (afm / "afmdata" / "s1.wav").write_bytes(b"")
    win._apply_audio_trim_lock(cgc, str(afm), persisted_trim=False)
    assert str(win._audio_trim_cb.cget("state")) != "disabled"
    assert win._audio_trim_cb.winfo_manager() == "pack"
    assert win.audio_trim_var.get() is False


def test_audio_preview_limit_caps_trimmed_replacement(app,
                                                      manufacturers_by_key):
    """When Trim/pad is on and a replacement is longer than its slot, the
    Replacement pane stops at the slot length (matching the machine); only
    the Replacement pane is ever capped (the Original pane always passes
    limit=None), and a shorter replacement isn't capped."""
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

    # Trim on + replacement longer than the 46s slot -> capped at slot length.
    assert win._audio_compute_preview_limit(rel, 61.8) == 46.0

    # Trim off -> no cap even for the replacement.
    win.audio_trim_var.set(False)
    assert win._audio_compute_preview_limit(rel, 61.8) is None

    # A slot exempted via the per-slot "Full" flag -> no cap.
    win.audio_trim_var.set(True)
    win._audio_keep_full_flags = {rel: True}
    assert win._audio_compute_preview_limit(rel, 61.8) is None

    # Replacement SHORTER than the slot -> no cap (padding is silent).
    win._audio_keep_full_flags = {}
    assert win._audio_compute_preview_limit(rel, 30.0) is None


def test_preview_panes_side_by_side(app, manufacturers_by_key):
    """Replace Audio + Replace Video previews show Original and Replacement
    side by side (like the image tab), each with its own play/stop transport
    — the old single player's Source A/B radios are gone (David)."""
    app._on_manufacturer_change(manufacturers_by_key["jjp"])
    app.root.update()
    w = app.window
    for orig, rep in ((w._audio_pane_orig, w._audio_pane_rep),
                      (w._video_pane_orig, w._video_pane_rep)):
        assert orig is not None and rep is not None
        # Wired as siblings so starting one pane pauses the other.
        assert orig.sibling is rep and rep.sibling is orig
        assert orig.frame.winfo_manager() == "grid"
        assert rep.frame.winfo_manager() == "grid"
        # Each pane owns its own transport + clock.
        assert orig.play_canvas is not rep.play_canvas
        assert orig.time_var is not rep.time_var
    # The old single-player Source switch is gone.
    assert not hasattr(w, "audio_source_var")
    assert not hasattr(w, "video_source_var")
    assert not hasattr(w, "_audio_src_rep")
    assert not hasattr(w, "_video_src_rep")
    # Clearing resets both panes; the Replacement side keeps its hint.
    w._audio_clear_preview()
    w._video_clear_preview()
    assert w._audio_pane_rep._hint == "no replacement assigned"
    assert w._video_pane_rep._hint == "no replacement assigned"


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


def test_audio_probe_fills_length_column(app, manufacturers_by_key, tmp_path):
    """The probe=False fast scan leaves Length as "—"; the background
    metadata pass must then fill every row (David: a fresh Guardians
    extract showed dashes across all 2562 slots)."""
    import time
    import wave
    from pinball_decryptor.core.audio_slots import scan_audio_slots
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    (tmp_path / "audio").mkdir()
    for i in range(3):
        wf = wave.open(str(tmp_path / "audio" / ("idx%04d.wav" % i)), "wb")
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 4410)          # 0.1 s
        wf.close()
    assets = str(tmp_path)
    w.write_assets_var.set(assets)
    slots = scan_audio_slots(assets, probe=False)
    assert slots and all(s.info is None for s in slots)
    w._audio_scan_id += 1
    w._populate_audio_after_scan(slots, w._audio_scan_id, assets)
    tree = w._audio_tree
    assert tree.set(slots[0].rel_path, "len") == "—"
    # The probe thread posts results via after(), which needs a REAL running
    # mainloop (update()-pumping makes cross-thread after() raise) — run one
    # briefly, polling until the rows fill or a deadline passes.
    deadline = time.time() + 10

    def _poll():
        done = all(tree.set(s.rel_path, "len") != "—" for s in slots)
        if done or time.time() > deadline:
            app.root.quit()
        else:
            app.root.after(50, _poll)

    app.root.after(50, _poll)
    app.root.mainloop()
    vals = [tree.set(s.rel_path, "len") for s in slots]
    assert vals == ["0:00.100"] * 3, vals
    assert "44.1kHz" in tree.set(slots[0].rel_path, "fmt")


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


def test_audio_metadata_backfills_rows_after_fast_scan(
        app, manufacturers_by_key, tmp_path):
    """The fast (probe=False) scan lists rows with placeholder length/format;
    _apply_audio_meta then fills each row in place as the background pass
    delivers its header info.  Guards the instant-list rework (a slow-to-read
    folder must never hold the whole list hostage on 'Scanning…')."""
    from pinball_decryptor.core.audio import AudioInfo
    from pinball_decryptor.core.audio_slots import scan_audio_slots
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_audio_assets(tmp_path)
    w.write_assets_var.set(assets)
    slots = scan_audio_slots(assets, probe=False)
    w._audio_scan_id += 1
    w._populate_audio_after_scan(slots, w._audio_scan_id, assets)

    rel = "audio/idx0001.wav"
    assert w._audio_slots_by_rel[rel].info is None
    assert w._audio_tree.set(rel, "len") == "—"      # placeholder until probed

    info = AudioInfo(rel, channels=1, sample_rate=22050, bit_depth=16,
                     duration=1.5)
    w._apply_audio_meta(w._audio_scan_id, rel, info)
    assert w._audio_slots_by_rel[rel].info is info
    assert w._audio_tree.set(rel, "len") == "0:01.500"
    assert "mono" in w._audio_tree.set(rel, "fmt")

    # A stale pass (newer scan started) must not touch slot or row.
    stale = AudioInfo(rel, channels=2, sample_rate=44100, bit_depth=16,
                      duration=9.0)
    w._apply_audio_meta(w._audio_scan_id - 1, rel, stale)
    assert w._audio_slots_by_rel[rel].info is info
    assert w._audio_tree.set(rel, "len") == "0:01.500"


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
# a tester UI batch: Scan/Browse busy state, column-width persistence,
# responsive intro-text wrapping
# ---------------------------------------------------------------------------

def test_scan_buttons_built_for_every_replace_tab(app):
    # All four Replace tabs are built at construction, so their Scan buttons
    # register up front (independent of the selected manufacturer).  Batch 20
    # dropped the per-tab "Set on Extract tab" jump buttons — the project row
    # is a plain read-only mirror now.
    for key in ("audio", "video", "image", "text"):
        assert key in app.window._scan_buttons
    assert not app.window._browse_buttons


def test_set_tab_scanning_toggles_button_state(app):
    w = app.window
    scan = w._scan_buttons["audio"]

    # Scanning: the Scan button becomes an ENABLED Cancel (a tester) and a
    # spinner animation is scheduled.
    w._audio_empty.configure(text="Scanning for audio files…")
    w._set_tab_scanning("audio", True)
    assert "Cancel" in scan.cget("text")
    assert str(scan.cget("state")) == "normal"
    assert "audio" in w._scan_spinner_after          # animation running

    w._set_tab_scanning("audio", False)
    assert scan.cget("text") == "Scan"
    assert str(scan.cget("state")) == "normal"
    assert "audio" not in w._scan_spinner_after       # animation stopped


def test_scan_blanks_list_and_cancel_resets(app):
    w = app.window
    w._audio_tree.insert("", "end", iid="stale", text="old row")
    before = w._audio_scan_id

    # Scan start blanks the list so a cancel can't leave it half-filled.
    w._audio_empty.configure(text="Scanning for audio files…")
    w._set_tab_scanning("audio", True)
    assert not w._audio_tree.get_children()

    # Cancel bumps the scan id (drops the in-flight worker), restores the
    # button, and shows a cancelled message.
    w._cancel_scan("audio")
    assert w._audio_scan_id == before + 1
    assert w._scan_buttons["audio"].cget("text") == "Scan"
    assert "cancelled" in w._audio_empty.cget("text").lower()
    assert "audio" not in w._scan_spinner_after


def test_set_tab_scanning_tolerates_unknown_tab(app):
    app.window._set_tab_scanning("nope", True)   # no raise
    app.window._cancel_scan("nope")              # no raise


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


def test_flash_button_shown_for_stern_hidden_otherwise(
        app, manufacturers_by_key):
    # winfo_manager() == "pack" means the Flash-image button is laid out in
    # the Modified Files toolbar (winfo_ismapped() reads 0 unless the Write
    # tab is raised).  feedback batch 8 moved it out of its own LabelFrame
    # onto the Build row.
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
    assert app.window._flash_btn.winfo_manager() == "pack"
    # Same row as Build (the preview-frame toolbar), not a separate frame.
    assert (app.window._flash_btn.master
            is app.window._write_btn.master)
    # Consolidated (David: "two build buttons"): for flash-capable plugins
    # the Build / flash dialog IS the build entry point, so the plain Build
    # button hides — exactly one primary write-side action button.
    assert app.window._write_btn.winfo_manager() == ""

    # Whitestar (MAME capture) era has no flash capability → flash hidden,
    # plain Build back.
    stern.set_era("whitestar")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    assert app.window._flash_btn.winfo_manager() == ""
    assert app.window._write_btn.winfo_manager() == "pack"

    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assert app.window._flash_btn.winfo_manager() == ""
    assert app.window._write_btn.winfo_manager() == "pack"


def test_write_preview_scan_uses_shared_scan_state(app, manufacturers_by_key):
    """feedback batch 8: the Modified Files scan gets the same treatment as
    the Replace tabs — Refresh flips to a live (enabled) Cancel while a scan
    runs instead of the old disabled hourglass button, and cancelling
    invalidates the in-flight scan and restores a plain "Refresh"."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    # Registered with the shared scan-state machinery under its own tab key.
    assert w._scan_buttons["write_preview"] is w._write_preview_refresh_btn
    assert w._scan_idle_labels["write_preview"] == "Refresh"
    w._set_tab_scanning("write_preview", True)
    try:
        assert "Cancel" in w._write_preview_refresh_btn.cget("text")
        assert str(w._write_preview_refresh_btn.cget("state")) != "disabled"
        before = w._write_preview_scan_id
        w._cancel_scan("write_preview")
        assert w._write_preview_scan_id == before + 1
        # Idle label is "Refresh" (no icon), and the cancelled-state hint
        # names the right button.
        assert w._write_preview_refresh_btn.cget("text") == "Refresh"
        assert "Refresh" in w._write_preview_empty.cget("text")
    finally:
        w._set_tab_scanning("write_preview", False)


def test_flash_button_folds_cancel_and_status_resets_on_run_start(
        app, manufacturers_by_key):
    """feedback batch 8: (a) starting any run replaces the previous run's
    terminal status ("Complete!") immediately instead of letting it linger
    until the first progress callback; (b) during a flash run the Flash
    button doubles as its live Cancel and is restored by set_running(False)
    however the run ends."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    w.set_status("Complete!")
    w.set_running(True, mode="write")
    try:
        assert w._status_label.cget("text") == "Starting…"
        w.set_flash_running(True)
        assert w._flash_btn.cget("text") == "Cancel"
    finally:
        w.set_running(False, mode="write")
    assert w._flash_btn.cget("text").startswith("Build / flash")
    assert not getattr(w, "_flash_running", False)


def test_write_build_button_folds_cancel_and_lives_in_toolbar(
        app, manufacturers_by_key):
    """a tester Write-tab rework: Build/Revert moved into the Modified Files
    toolbar, the standalone Cancel widget is gone (Build doubles as a live
    Cancel), and the built file's name lives in an editable File Name box
    pre-filled with the original + the plugin's suffix; the hint line under it
    stays blank unless the chosen name would overwrite an existing file."""
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
        # The build name lives in the editable File Name box, pre-filled with
        # the original + Stern's -modified suffix; the hint line stays blank
        # while there's no collision.
        w.write_upd_var.set("")
        w._update_write_filename()
        assert w.write_filename_var.get() == ""
        assert w._write_filename_lbl.cget("text") == ""
        w.write_upd_var.set("C:/cards/game-1_0_0.sdcard.raw")
        w._update_write_filename()
        assert (w.write_filename_var.get()
                == "game-1_0_0.sdcard-modified.raw")
        assert w._write_filename_lbl.cget("text") == ""
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


def test_write_filename_box_editable_and_flags_collisions(
        app, manufacturers_by_key, tmp_path):
    """The Write tab's File Name box pre-fills with original + suffix, keeps
    tracking the original until the user types a name of their own, and the
    hint line goes amber when the chosen name would overwrite an existing
    file in the Output Folder."""
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.window.extract_input_var.set("")
    stern.set_era("spike2")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    w = app.window
    try:
        out_dir = tmp_path / "builds"
        out_dir.mkdir()
        w.write_output_var.set(str(out_dir))
        # Default name = original basename + Stern's -modified suffix.
        w.write_upd_var.set("C:/cards/game-1_0_0.sdcard.raw")
        w._update_write_filename()
        assert w.write_filename_var.get() == "game-1_0_0.sdcard-modified.raw"
        # No file there yet -> no collision warning.
        assert w._write_filename_lbl.cget("text") == ""

        # Create the colliding build; the hint states the fact (gray,
        # informational — the Build click now asks before overwriting,
        # feedback batch 14).
        (out_dir / "game-1_0_0.sdcard-modified.raw").write_bytes(b"old")
        w._update_write_filename_hint()
        assert "already exists" in w._write_filename_lbl.cget("text")
        assert str(w._write_filename_lbl.cget("foreground")) == "#888888"

        # A user edit to a free name clears the warning and is NOT clobbered
        # when the original changes again (box has diverged from the default).
        w.write_filename_var.set("my-build.raw")
        assert w._write_filename_lbl.cget("text") == ""
        w.write_upd_var.set("C:/cards/other-2_0_0.sdcard.raw")
        w._update_write_filename()
        assert w.write_filename_var.get() == "my-build.raw"
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_write_output_ext_forces_correct_extension(manufacturers_by_key):
    """Flash-image plugins pin the extension their built image must carry, so a
    user-typed File Name can never come out extensionless or in the wrong
    format: Stern Spike 2 = .raw, CGC = .img.  Whitestar (capture-only) and
    plugins whose build name is looked up by the machine pin nothing."""
    stern = manufacturers_by_key["stern"]
    stern.set_era("spike2")
    try:
        assert stern.write_output_ext() == ".raw"
        # Extensionless -> appended; a recognised card extension -> swapped in
        # place (not stacked into ".img.raw"); an already-correct name -> kept.
        assert stern.force_write_ext("my_mod") == "my_mod.raw"
        assert stern.force_write_ext("game.img") == "game.raw"
        assert stern.force_write_ext("game.bin") == "game.raw"
        assert stern.force_write_ext("game.raw") == "game.raw"
        # An unrecognised trailing extension is appended to, not clobbered, so a
        # dotted name never silently loses a part.
        assert stern.force_write_ext("v1.2.3") == "v1.2.3.raw"
        # Whitestar is MAME capture-only: no build, so no forced extension.
        stern.set_era("whitestar")
        assert stern.write_output_ext() == ""
        assert stern.force_write_ext("whatever") == "whatever"
    finally:
        stern.set_era("spike2")

    cgc = manufacturers_by_key["cgc"]
    assert cgc.write_output_ext() == ".img"
    assert cgc.force_write_ext("installer") == "installer.img"
    assert cgc.force_write_ext("installer.img") == "installer.img"

    # JJP builds a Clonezilla-derived install ISO, so it pins .iso (v0.100.0,
    # when the Build / make USB stick dialog started deriving its Build-to
    # path from this).
    jjp = manufacturers_by_key.get("jjp")
    if jjp is not None:
        assert jjp.write_output_ext() == ".iso"
        assert jjp.force_write_ext("update") == "update.iso"

    # BOF's machine looks the update up by name, so it pins nothing.
    bof = manufacturers_by_key.get("bof")
    if bof is not None:
        assert bof.write_output_ext() == ""
        assert bof.force_write_ext("update") == "update"


def test_write_filename_forces_raw_extension_and_states_it(
        app, manufacturers_by_key, tmp_path):
    """Stern Spike 2 builds a raw card image (.raw): the default name lands as
    .raw even when the original was a .img, the merged Build Image row shows
    the forced-extension destination (batch 21 — the standalone "saved as
    .raw" label is gone), and an extensionless typed name is forced to .raw
    with a 'Will build:' line spelling out the resulting file."""
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    app.window.extract_input_var.set("")
    stern.set_era("spike2")
    app.window.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    w = app.window
    try:
        out_dir = tmp_path / "builds"
        out_dir.mkdir()
        w.write_output_var.set(str(out_dir))
        # The old standalone extension label is gone (batch 21).
        assert not hasattr(w, "_write_ext_lbl")
        # A .img original still defaults to a .raw build name.
        w.write_upd_var.set("C:/cards/game-1_0_0.sdcard.img")
        w._update_write_filename()
        assert w.write_filename_var.get() == "game-1_0_0.sdcard-modified.raw"
        # A user-typed extensionless name is forced to .raw, and the hint spells
        # out the resulting file so the added extension is explicit.
        w.write_filename_var.set("my_mod")
        w._update_write_filename_hint()
        assert w._write_filename_lbl.cget("text") == "Will build: my_mod.raw"
        assert w._target_write_path().endswith("my_mod.raw")
        # The merged Build Image row shows the same forced destination.
        assert w._write_build_path_var.get().endswith("my_mod.raw")
        # A name that already carries the right extension -> no surprise line.
        w.write_filename_var.set("my_mod.raw")
        w._update_write_filename_hint()
        assert w._write_filename_lbl.cget("text") == ""
    finally:
        app._on_back_to_picker()
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()


def test_capture_help_line_removed_for_noncapture_plugin(
        app, manufacturers_by_key):
    """The capture-help line is fully unpacked (not just blanked) for a
    non-capture plugin, so it can't reserve an empty line between the
    Output-folder warning and the Extract row and skew the 3-step spacing
    (a tester Extract #1).  winfo_manager() == "" means not managed."""
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
    """Path boxes keep a per-manufacturer recent-paths history (a tester):
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
    """The header "?" opens the per-tab tips modal (a tester): shown only
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
            caption = w._tab_key(tab_id)      # stable key, not the short label
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
    """The header ⚙ replaces the old button row (a tester: settings live in
    a dropdown, not permanent top-bar clutter), and the Prerequisites strip
    stays hidden until a probe CONFIRMS something is missing (David: no
    flash-then-vanish "checking" strip on tab entry)."""
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
        # Still checking -> strip stays hidden; only the ⚙ menu says so.
        assert w._prereqs_frame.winfo_manager() == ""
        assert "checking" in w._prereq_menu_summary()[0]
        # All green -> strip stays hidden; menu summary says ready.
        for name in names:
            w.set_prereq_result(name, True, "ok")
        assert w._prereqs_frame.winfo_manager() == ""
        label, missing = w._prereq_menu_summary()
        assert "ready" in label and not missing
        # One goes missing -> strip appears; Install entry re-arms.
        w.set_prereq_result(names[0], False, "gone")
        assert w._prereqs_frame.winfo_manager() == "pack"
        label, missing = w._prereq_menu_summary()
        assert "1 missing" in label and missing
        # Update-check busy state is just a flag now (menu built per click).
        w.set_update_check_running(True)
        assert w._update_check_busy
        w.set_update_check_running(False)
        assert not w._update_check_busy
        # A found update lights the gear's red notification dot (composited
        # into the gear's anti-aliased disc image — icon_dots is the state),
        # puts a Download entry at the top of the menu, and the outcome in
        # the log (David).
        assert "update" not in w._gear_btn.icon_dots
        app._handle_update_check_result(
            ("99.0.0", "https://example.com/release", "", None), False)
        assert "update" in w._gear_btn.icon_dots
        upd_menu = w._build_settings_menu()
        assert "Download update v99.0.0" in upd_menu.entrycget(0, "label")
        assert "Update available: v99.0.0" in w._log_text.get("1.0", "end-1c")
        # No installer asset -> browser flow: Install button hidden,
        # Download button keeps its plain label.
        assert not w._update_install_btn.winfo_ismapped()
        assert w._update_download_btn.cget("text") == "Download"
        # A release that DOES carry a Windows installer asset flips the
        # banner to the one-click flow (jim-beam): Install button shown,
        # browser button demoted to Release notes, gear entry = Install.
        fake_asset = {"name": "setup.exe", "url": "https://x/w.exe",
                      "size": 1, "sha256": None,
                      "kind": "windows-installer"}
        app._handle_update_check_result(
            ("99.0.0", "https://example.com/release", "", fake_asset), False)
        app.root.update_idletasks()
        assert w._update_install_btn.winfo_ismapped()
        assert w._update_install_btn.cget("text") == "Install update"
        assert w._update_download_btn.cget("text") == "Release notes"
        upd_menu = w._build_settings_menu()
        assert "Install update v99.0.0" in upd_menu.entrycget(0, "label")
        # Linux gets the same one-click flow with an honest verb: an
        # AppImage download installs nothing, it just lands next to the
        # one being run (a tester -- the browser handoff it replaces was dead).
        appimage_asset = {"name": "PAD_v99_Linux_x86_64.AppImage",
                          "url": "https://x/pad.AppImage",
                          "size": 1, "sha256": None, "kind": "appimage"}
        app._handle_update_check_result(
            ("99.0.0", "https://example.com/release", "", appimage_asset),
            False)
        app.root.update_idletasks()
        assert w._update_install_btn.winfo_ismapped()
        assert w._update_install_btn.cget("text") == "Download update"
        upd_menu = w._build_settings_menu()
        assert "Download update v99.0.0" in upd_menu.entrycget(0, "label")
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
        # The accepted disclaimer stays re-readable from the gear (David).
        assert "View disclaimer…" in joined
        # Prerequisites are a cascade now (a tester): the cascade label IS
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


def test_disclaimer_review_mode(app):
    """Gear "View disclaimer…" re-opens the accepted terms read-only: one
    Close button (no I Agree / Quit pair), and closing — here via Esc —
    returns True, so a re-read can never register as a decline."""
    from pinball_decryptor.gui.disclaimer import (
        DISCLAIMER_TITLE, show_disclaimer_dialog)

    seen = {}

    def _probe_and_close():
        dlg = next((c for c in app.root.winfo_children()
                    if isinstance(c, _tk_mod.Toplevel)
                    and c.title() == DISCLAIMER_TITLE), None)
        if dlg is None:                   # modal not mapped yet — re-arm
            app.root.after(50, _probe_and_close)
            return
        labels, stack = [], [dlg]
        while stack:
            wgt = stack.pop()
            stack.extend(wgt.winfo_children())
            if isinstance(wgt, _tk_mod.Label):
                labels.append(wgt.cget("text"))
        seen["labels"] = labels
        dlg.event_generate("<Escape>")

        # Failsafe: a regressed Escape binding must fail the test, not
        # hang the whole run inside wait_window().
        def _failsafe():
            if dlg.winfo_exists():
                seen["hung"] = True
                dlg.destroy()
        app.root.after(2000, _failsafe)

    app.root.after(100, _probe_and_close)
    result = show_disclaimer_dialog(app.root, theme_name="light",
                                    review=True)
    assert result is True
    assert not seen.get("hung"), "Esc did not close the review dialog"
    assert "Close" in seen["labels"]
    assert "I Agree" not in seen["labels"]
    assert "Quit" not in seen["labels"]


def test_help_window_singleton_and_tab_refresh(app, manufacturers_by_key):
    """"?" re-uses one tips window instead of stacking new ones, and a
    notebook tab switch re-renders the open window (a tester round 2)."""
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
    (a tester: 'do not stick between sessions')."""
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
    # The slicer's glyphs dir marks this as a modern extract — name hints
    # are only trusted when the extractor recorded which members are fonts.
    (st / "glyphs").mkdir()
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
    groups, occ, where = window._scan_image_groups(assets_dir)
    window._image_scan_id += 1
    window._populate_image_after_scan(
        slots, window._image_scan_id, assets_dir, groups, occ, where)
    return slots


def test_image_group_scan_parses_manifests(tmp_path):
    """The manifest parser groups radium frames under their container with a
    friendly element-name label, counts dedup occurrences, and yields nothing
    for a folder with no manifests."""
    from pinball_decryptor.gui.main_window import MainWindow
    assets = _seed_image_assets(tmp_path)
    groups, occ, _where = MainWindow._scan_image_groups(assets)
    key = "rad::/game/scenes/a1b2c3d4e5f6/scene.radium"
    rel1 = "images/scene_textures/radimg_Char_Select_8x8_00000001.png"
    # Label = element hint + searchable container-hash shorthand: hints
    # repeat across sibling containers, so the hash half disambiguates.
    assert groups[rel1] == (key, "Char_Select · a1b2c3d4", 100)
    # The nameless frame inherits the group label; order = its data offset.
    rel3 = "images/scene_textures/radimg_8x8_00000003.png"
    assert groups[rel3] == (key, "Char_Select · a1b2c3d4", 300)
    assert occ[rel1] == 1
    # Group KEY keeps the manifest's leading slash (so saved tags match); the
    # display LABEL drops it for consistency with the other tabs (a tester).
    assert groups["images/loose/logo.png"] == (
        "dir::/game/assets/loose", "game/assets/loose", 0)
    empty = tmp_path / "no_manifests"
    empty.mkdir()
    assert MainWindow._scan_image_groups(str(empty)) == ({}, {}, {})


def test_image_group_label_skips_font_atlases(tmp_path):
    """A scene whose first named member is a FONT atlas must not be labeled
    after the font (Stern names fonts "Stern_...", so every hash-named member
    matched a search for "stern" through the invisible label — a tester).
    The hint comes from the first non-atlas named member, or falls back to
    the hash shorthand when the font is the only named member."""
    from pinball_decryptor.gui.main_window import MainWindow
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    atlas = "radimg_Stern_FooFont_512x512_deadbeef.png"
    named = "radimg_Char_Select_8x8_00000001.png"
    plain = "radimg_8x8_00000002.png"
    for fn in (atlas, named, plain):
        (st / fn).write_bytes(b"\x89PNG-fake")
    # What marks the atlas as a font: its extracted glyphs/<stem>/ dir.
    (st / "glyphs" / atlas[:-4]).mkdir(parents=True)
    card_a = "/game/scenes/aaaaaaaa1111/scene.radium"
    card_b = "/game/scenes/bbbbbbbb2222/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        # Scene A: font first (offset 100), real named element later.
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (atlas, card_a))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (named, card_a))
        # Scene B: the font is the ONLY named member.
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (atlas, card_b))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (plain, card_b))
    groups, _occ, where = MainWindow._scan_image_groups(str(tmp_path))
    rel_named = "images/scene_textures/" + named
    rel_plain = "images/scene_textures/" + plain
    assert groups[rel_named][1] == "Char_Select · aaaaaaaa"
    assert groups[rel_plain][1] == "bbbbbbbb"
    # The atlas itself keeps its membership (home = scene A) — only the
    # label derivation skips it.
    rel_atlas = "images/scene_textures/" + atlas
    assert [g[0] for g in where[rel_atlas]] == [
        "rad::" + card_a, "rad::" + card_b]


def _seed_shared_image_assets(tmp_path):
    """Two scenes that share one image: the extract dedupes it to a single
    PNG whose HOME group is the first scene, so the second scene owns no
    first-occurrence row at all (a tester's training scene)."""
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    shared = "radimg_Logo_8x8_000000aa.png"
    own = "radimg_Only_8x8_000000bb.png"
    for fn in (shared, own):
        (st / fn).write_bytes(b"\x89PNG-fake")
    home = "/game/scenes/aaaaaaaa1111/scene.radium"
    other = "/game/scenes/bbbbbbbb2222/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (shared, home))
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (own, home))
        # The second scene draws ONLY the shared image — nothing is first
        # seen here, so before the fix this scene had no rows anywhere.
        f.write("scene_textures/%s\t%s\t400\t16\t8\t8\t5\n" % (shared, other))
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path), "images/scene_textures/" + shared


def test_image_search_finds_scene_by_any_occurrence(app, manufacturers_by_key,
                                                    tmp_path):
    """Searching a scene id finds the images that scene draws even when they
    are filed under another scene, and shows them UNDER the scene searched
    for."""
    from pinball_decryptor.gui.main_window import MainWindow
    assets, shared = _seed_shared_image_assets(tmp_path)
    groups, occ, where = MainWindow._scan_image_groups(assets)
    home_key = "rad::/game/scenes/aaaaaaaa1111/scene.radium"
    other_key = "rad::/game/scenes/bbbbbbbb2222/scene.radium"
    # One home group, but both containers recorded — home first.
    assert groups[shared][0] == home_key
    assert [g[0] for g in where[shared]] == [home_key, other_key]
    assert occ[shared] == 2

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    tree = w._image_tree
    w.image_group_by_scene_var.set(True)

    # The second scene's id now finds its image, grouped under THAT scene.
    w.image_search_var.set("bbbbbbbb")
    tops = list(tree.get_children())
    assert len(tops) == 1
    assert tops[0] == "::grp::" + other_key
    assert list(tree.get_children(tops[0])) == [shared]
    # The full on-card scene hash (what a file listing shows) works too.
    w.image_search_var.set("bbbbbbbb2222")
    assert list(tree.get_children()) == ["::grp::" + other_key]
    # Its home scene still lists it, alongside the image only that scene has.
    w.image_search_var.set("aaaaaaaa")
    tops = list(tree.get_children())
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 2
    # Flat mode searches scenes too (it used to match paths only).
    w.image_group_by_scene_var.set(False)
    w.image_search_var.set("bbbbbbbb")
    assert list(tree.get_children()) == [shared]
    w.image_search_var.set("")


def test_image_grouped_mode_and_change_filter(app, manufacturers_by_key,
                                              tmp_path):
    """Grouped mode nests slot rows (same iids) under collapsed per-scene
    parents in play order; the Show filter prunes untouched rows (and, in
    grouped mode, whole untouched groups) or keeps only those; flat mode is
    unchanged."""
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
    assert "Char_Select · a1b2c3d4" in tree.item(grp[0], "text")
    # The member count lives in its own sortable "Images" column (a tester),
    # which only shows in grouped mode.
    assert tree.item(grp[0], "values")[0] == "3 images"
    assert tree["displaycolumns"][0] == "n"
    assert not tree.item(grp[0], "open")          # inserted collapsed
    # Children keep the slot iid and sit in play order (data offset).
    assert list(tree.get_children(grp[0])) == rels[:3]
    # Counts stay over image rows, not group headers.
    assert "4 images" in w.image_status_var.get()

    # Clicking the Images header sorts the GROUPS by member count.
    w._image_sort = ("n", True)
    w._refresh_image_list()
    tops = list(tree.get_children())
    counts = [tree.item(t, "values")[0] for t in tops]
    assert counts == ["3 images", "1 image"]
    w._image_sort = ("n", False)
    w._refresh_image_list()
    tops = list(tree.get_children())
    assert [tree.item(t, "values")[0] for t in tops] == ["1 image", "3 images"]
    w._image_sort = ("#0", False)
    w._refresh_image_list()

    # Search matches the group LABEL even though the files are hash-named —
    # by element hint or by the container-hash shorthand.
    w.image_search_var.set("char_sel")
    tops = list(tree.get_children())
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 3
    w.image_search_var.set("a1b2c3d4")
    tops = list(tree.get_children())
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 3
    w.image_search_var.set("")

    # Show=Changed: an assignment keeps its group; the untouched group goes.
    w._image_assignments[rels[0]] = str(tmp_path / "rep.png")
    w.image_change_filter_var.set("Changed")
    tops = list(tree.get_children())
    assert len(tops) == 1
    assert "Char_Select · a1b2c3d4" in tree.item(tops[0], "text")
    assert tree.item(tops[0], "values")[0] == "1 image"
    assert list(tree.get_children(tops[0])) == [rels[0]]
    # ...and in flat mode only the assigned row survives (count column gone).
    w.image_group_by_scene_var.set(False)
    assert list(tree.get_children()) == [rels[0]]
    assert "n" not in tree["displaycolumns"]

    # Show=Unchanged is its exact complement: everything BUT that row.
    w.image_change_filter_var.set("Unchanged")
    assert list(tree.get_children()) == [r for r in sorted(rels, key=str.lower)
                                         if r != rels[0]]

    w.image_change_filter_var.set("All")
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


def test_image_source_filter_and_group_rename(app, manufacturers_by_key,
                                              tmp_path, monkeypatch):
    """The Source dropdown narrows the list to one image store, and
    right-click Rename gives a scene group a persistent display name that
    renders, searches, and lands in the staged-changes sidecar; a blank
    rename restores the manifest label (a tester)."""
    from pinball_decryptor.core import staged_changes
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assets = _seed_image_assets(tmp_path)
    # ...plus one font-glyph slice (the glyph-atlas slicer's output tree).
    gdir = tmp_path / "images" / "scene_textures" / "glyphs" / "atlas_x"
    gdir.mkdir(parents=True)
    (gdir / "U+0041_A.png").write_bytes(b"\x89PNG-fake")
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    tree = w._image_tree

    # Source filter: the radimg_* slots are "Radium", logo.png is "File",
    # the glyphs/ slice is "Glyph".
    w.image_source_filter_var.set("Radium")
    assert len(tree.get_children()) == 3
    assert all("radimg" in r for r in tree.get_children())
    w.image_source_filter_var.set("File")
    assert list(tree.get_children()) == ["images/loose/logo.png"]
    w.image_source_filter_var.set("Glyph")
    assert list(tree.get_children()) == [
        "images/scene_textures/glyphs/atlas_x/U+0041_A.png"]
    w.image_source_filter_var.set("All sources")
    assert len(tree.get_children()) == 5

    # Rename a grouped scene: display + sidecar + search all follow.
    w.image_group_by_scene_var.set(True)
    grp = [t for t in tree.get_children()
           if "Char_Select" in tree.item(t, "text")][0]
    monkeypatch.setattr(type(w), "_ask_text",
                        lambda self, *a, **k: "Boss Intro")
    w._image_group_rename(grp)
    assert "Boss Intro" in tree.item(grp, "text")
    assert tree.item(grp, "values")[0] == "3 images"
    saved = staged_changes.load(assets)
    assert list(saved.get("image_group_tags", {}).values()) == ["Boss Intro"]
    w.image_search_var.set("boss in")
    tops = tree.get_children()
    assert len(tops) == 1 and len(tree.get_children(tops[0])) == 3
    w.image_search_var.set("")
    # A blank rename restores the manifest label and drops the tag.
    monkeypatch.setattr(type(w), "_ask_text", lambda self, *a, **k: "")
    w._image_group_rename(grp)
    assert "Char_Select · a1b2c3d4" in tree.item(grp, "text")
    assert not staged_changes.load(assets).get("image_group_tags")


# ---------------------------------------------------------------------------
# feedback batch 9: mode-aware Cancel buttons, "Cancel scan" labelling,
# Write-toolbar grouping, live scan-activity text, Total-changes readout
# ---------------------------------------------------------------------------

def test_scan_cancel_button_says_cancel_scan(app):
    """The scan buttons' running label is "Cancel scan" — context so it can't
    be confused with a run's "Cancel", and no ✕ glyph (feedback batch 9)."""
    w = app.window
    w._audio_empty.configure(text="Scanning for audio files…")
    w._set_tab_scanning("audio", True)
    try:
        assert w._scan_buttons["audio"].cget("text") == "Cancel scan"
        assert "✕" not in w._scan_buttons["audio"].cget("text")
    finally:
        w._set_tab_scanning("audio", False)
    assert w._scan_buttons["audio"].cget("text") == "Scan"


def test_run_cancel_only_on_initiating_side_extract(app):
    """During an extract run only the Extract button becomes Cancel; the Write
    tab's Build button greys out with its idle label instead of becoming a
    second Cancel that would kill the extract (feedback batch 9 — he clicked
    it and cancelled his extract)."""
    w = app.window
    idle = w._write_btn.cget("text")
    w.set_running(True, mode="extract")
    try:
        assert w._extract_btn.cget("text") == "Cancel"
        assert str(w._extract_btn.cget("state")) == "normal"
        assert w._write_btn.cget("text") == idle
        assert str(w._write_btn.cget("state")) == "disabled"
    finally:
        w.set_running(False, mode="extract")
    assert w._extract_btn.cget("text") == "Extract"
    assert w._write_btn.cget("text") == idle
    assert str(w._write_btn.cget("state")) == "normal"


def test_run_cancel_only_on_initiating_side_write(app):
    """Mirror case: during a build/write run the Extract button is parked
    disabled on its idle label while Build is the live Cancel."""
    w = app.window
    w.set_running(True, mode="write")
    try:
        assert w._write_btn.cget("text") == "Cancel"
        assert str(w._write_btn.cget("state")) == "normal"
        assert w._extract_btn.cget("text") == "Extract"
        assert str(w._extract_btn.cget("state")) == "disabled"
    finally:
        w.set_running(False, mode="write")
    assert w._write_btn.cget("text") != "Cancel"


def test_flash_run_has_exactly_one_cancel(app, manufacturers_by_key):
    """A flash run arms the Flash button as the live Cancel and parks the
    Build button (which set_running(mode="write") had armed) disabled on its
    idle label — one Cancel on screen, not two (feedback batch 9)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    idle = w._write_btn.cget("text")
    w.set_running(True, mode="write")
    try:
        w.set_flash_running(True)
        assert w._flash_btn.cget("text") == "Cancel"
        assert w._write_btn.cget("text") == idle
        assert str(w._write_btn.cget("state")) == "disabled"
    finally:
        w.set_running(False, mode="write")
    assert w._flash_btn.cget("text").startswith("Build / flash")
    assert w._write_btn.cget("text") == idle
    assert str(w._write_btn.cget("state")) == "normal"


def test_set_cancelling_only_relabels_live_cancel(app):
    """set_cancelling flips only the button that reads "Cancel" to
    "Cancelling…"; the parked other-side button keeps its idle label (it was
    never a Cancel) — both end up disabled."""
    w = app.window
    idle = w._write_btn.cget("text")
    w.set_running(True, mode="extract")
    try:
        w.set_cancelling()
        assert w._extract_btn.cget("text") == "Cancelling…"
        assert w._write_btn.cget("text") == idle
        assert str(w._write_btn.cget("state")) == "disabled"
    finally:
        w.set_running(False, mode="extract")


def test_write_toolbar_right_justifies_scan_and_actions(
        app, manufacturers_by_key):
    """Modified Files toolbar (feedback batch 22): every button is
    right-justified, with the scan control at the LEFT end of that group —
    i.e. last in the side=RIGHT packing order.  For a flash-capable plugin the
    plain Build button is hidden (David: the consolidated Build / flash button
    replaces it), so the group is scan + Revert + Build / flash."""
    w = app.window
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    w.extract_input_var.set("")
    stern.set_era("spike2")
    w.apply_manufacturer(stern, reset_era=False)
    app.root.update()
    assert w._write_btn.winfo_manager() == ""     # consolidated away
    for btn in (w._write_preview_refresh_btn, w._flash_btn,
                w._revert_all_btn):
        assert btn.pack_info()["side"] == "right"
    order = w._write_preview_toolbar.pack_slaves()
    assert order[-1] is w._write_preview_refresh_btn
    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()


def test_write_preview_scan_status_ticks_and_clears(app):
    """The Modified Files scan shows the SAME big animated overlay as every
    other tab, carrying a running "N found", and resets when the scan ends or
    is cancelled (feedback batch 22 — the old small toolbar label is gone)."""
    w = app.window
    w._write_preview_empty.configure(text="Scanning for modified files…")
    w._set_tab_scanning("write_preview", True)
    try:
        assert "Scanning for modified files" in \
            w._write_preview_empty.cget("text")
        # The running count goes into the overlay's own text.
        w._write_preview_progress(7, w._write_preview_scan_id)
        assert "7 found" in w._scan_msgs["write_preview"]
    finally:
        w._set_tab_scanning("write_preview", False)
    # Cancel path resets the overlay to its idle message.
    w._set_tab_scanning("write_preview", True)
    w._cancel_scan("write_preview")
    assert "Scan cancelled" in w._write_preview_empty.cget("text")


def test_write_preview_total_changes_readout(app):
    """"Total changes: N" tracks the preview tree's row count and goes blank
    when the list empties (feedback batch 9)."""
    w = app.window
    sid = w._write_preview_scan_id
    w._add_write_preview_row("audio/one.wav", "wav", "Modified", sid)
    w._add_write_preview_row("audio/two.wav", "wav",
                             "Pending (Replace Audio)", sid, tag="pending")
    assert w._write_preview_count_lbl.cget("text") == "Total changes: 2"
    # A new scan blanks the tree — the readout follows.
    w._set_tab_scanning("write_preview", True)
    assert w._write_preview_count_lbl.cget("text") == ""
    w._cancel_scan("write_preview")
    assert w._write_preview_count_lbl.cget("text") == ""


def test_run_preempts_preview_scan(app):
    """One live Cancel at a time (feedback batch 10): starting a run kills an
    in-flight Modified Files scan (no "Cancel scan" next to the run's
    "Cancel"), greys Refresh for the run, and re-fires the scan afterwards."""
    w = app.window
    w._set_tab_scanning("write_preview", True)
    assert "write_preview" in w._scan_spinner_after
    w.set_running(True, mode="write")
    try:
        assert "write_preview" not in w._scan_spinner_after   # scan cancelled
        assert str(w._write_preview_refresh_btn["state"]) == "disabled"
        assert w._rescan_preview_after_run
        # A scan requested mid-run defers instead of starting.
        w._scan_write_preview()
        assert "write_preview" not in w._scan_spinner_after
    finally:
        w.set_running(False)
    assert str(w._write_preview_refresh_btn["state"]) == "normal"
    assert not w._rescan_preview_after_run                    # flag consumed


def test_begin_revert_view_blanks_preview(app):
    """Revert blanks the Modified Files list immediately — its rows are about
    to go stale — and says so in place (feedback batch 10)."""
    w = app.window
    sid = w._write_preview_scan_id
    w._add_write_preview_row("audio/one.wav", "wav", "Modified", sid)
    assert w._write_preview_tree.get_children()
    w.begin_revert_view()
    assert not w._write_preview_tree.get_children()
    assert w._write_preview_count_lbl.cget("text") == ""
    assert "Reverting" in w._write_preview_empty.cget("text")


def test_group_tags_reseed_across_reextract(app, manufacturers_by_key,
                                            tmp_path, monkeypatch):
    """A group name given one extract is restored when the SAME card is
    re-extracted to a fresh folder (a tester: tags lost on re-extract).  The
    per-card library is keyed by the source card's file name, so only the
    same-version card seeds; the fresh folder's sidecar also gets the name so
    it rides Mod Transfer / reopen."""
    from pinball_decryptor.core import (extract_source, staged_changes,
                                        tag_library)
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "settings" / "group_tags.json"))
    card = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    card.write_bytes(b"\x00" * 32)

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    # First extract: rename a group -> lands in sidecar AND the card library.
    a = _seed_image_assets(tmp_path / "A")
    extract_source.write_extract_source(a, str(card))
    w.write_assets_var.set(a)
    _scan_images(w, a)
    w.image_group_by_scene_var.set(True)
    grp = [t for t in w._image_tree.get_children()
           if "Char_Select" in w._image_tree.item(t, "text")][0]
    monkeypatch.setattr(type(w), "_ask_text",
                        lambda self, *a, **k: "Boss Intro")
    w._image_group_rename(grp)
    key = "rad::/game/scenes/a1b2c3d4e5f6/scene.radium"
    assert tag_library.load() == {
        "turtles_pro-1_59_0.release.8g.sdcard.raw": {key: "Boss Intro"}}

    # Second extract of the same card to a blank folder: name comes back.
    b = _seed_image_assets(tmp_path / "B")
    extract_source.write_extract_source(b, str(card))
    assert not staged_changes.load(b).get("image_group_tags")  # starts blank
    w.write_assets_var.set(b)
    _scan_images(w, b)
    assert w._image_group_tags.get(key) == "Boss Intro"
    # Seeded name is written back into the fresh folder's own sidecar.
    assert staged_changes.load(b).get("image_group_tags") == {key: "Boss Intro"}
    tree = w._image_tree
    w.image_group_by_scene_var.set(True)
    w._refresh_image_list()
    grp_b = [t for t in tree.get_children()
             if "Boss Intro" in tree.item(t, "text")]
    assert len(grp_b) == 1


def test_partition_explorer_browse_and_extract(app, manufacturers_by_key,
                                               tmp_path, monkeypatch):
    """Open a card image, list partitions, browse the ext4 tree (lazy expand),
    preview a text file, and extract one file (a tester wishlist #3)."""
    from pinball_decryptor.gui.main_window import _PEX_PLACEHOLDER
    from tests._ext4_fake import install_fake_reader, write_fake_card

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")

    w.partition_image_var.set(img)
    w._pex_open_image()

    labels = list(w._pex_part_combo["values"])
    # Device-style names: MBR slot N -> sda(N+1) (feedback batch 14).
    assert any("sda2" in l and "not browsable" not in l for l in labels)
    assert sum("not browsable" in l for l in labels) == 3   # FAT, bad ext, ext'd

    tree = w._pex_tree
    assert [tree.item(i, "text") for i in tree.get_children("")] == [
        "etc", "spk", "zeta", "game", "readme.txt"]

    # /etc starts with only its lazy placeholder; opening it loads real children.
    kids = tree.get_children("/etc")
    assert len(kids) == 1 and kids[0].endswith(_PEX_PLACEHOLDER)
    tree.item("/etc", open=True)
    w._pex_fill_open_dirs()     # the after_idle worker _pex_on_tree_open defers to
    assert [tree.item(i, "text") for i in tree.get_children("/etc")] == ["init.d"]

    # Select a text file -> preview; select a dir -> preview clears.
    tree.selection_set("/readme.txt")
    w._pex_on_tree_select()
    assert w._pex_preview.get("1.0", "end").strip() == "hello world"

    out = tmp_path / "out.txt"
    msg = w._pex_do_extract("file", "/readme.txt", str(out))
    assert out.read_bytes() == b"hello world" and "Extracted" in msg


def test_partition_explorer_find_and_replace(app, manufacturers_by_key,
                                             tmp_path, monkeypatch):
    """Find Next reveals matches in the lazy tree; right-click Replace writes
    an exact-size stand-in through the extent map (batch-14 wishlist)."""
    import time
    from tests._ext4_fake import (install_fake_reader, materialize_files,
                                  write_fake_card)

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")
    placed = materialize_files(img)

    w.partition_image_var.set(img)
    w._pex_open_image()
    tree = w._pex_tree

    # Find: reveals + selects the nested match, then cycles on repeat.
    w.partition_search_var.set("game")
    w._pex_find_next()
    assert tree.selection() == ("/etc/init.d/game",)
    assert str(tree.item("/etc", "open")) in ("1", "True", "true")
    w.partition_search_var.set("zzz-nope")
    w._pex_find_next()
    assert "No file path" in str(w._pex_action_status["text"])

    # Replace: same-size stand-in lands at the file's disk offset; the GUI
    # flow (confirm + picker) is monkeypatched to say yes.
    src = tmp_path / "new_game.sh"
    src.write_bytes(b"#!/bin/sh\necho HI\n")           # 18 bytes like the orig
    from pinball_decryptor.gui import main_window as mw
    monkeypatch.setattr(mw.filedialog, "askopenfilename",
                        lambda **k: str(src))
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a, **k: True)
    w._pex_replace_selected("/etc/init.d/game")
    deadline = time.time() + 10
    while w._pex_busy and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert not w._pex_busy
    off, _old = placed["/etc/init.d/game"]
    with open(img, "rb") as f:
        f.seek(off)
        assert f.read(18) == b"#!/bin/sh\necho HI\n"


def test_partition_explorer_replace_different_size(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """Right-click Replace accepts a file that ISN'T the slot's size: the tab
    warns that the card gets mounted, hands the copy to the ext4 driver, and
    reports the resize (PAD-31 — a tester wanted to swap sda2's splash
    screen and boot scripts, which never match byte-for-byte)."""
    import time

    from pinball_decryptor.core import ext4_grow
    from tests._ext4_fake import (install_fake_reader, materialize_files,
                                  write_fake_card)

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")
    placed = materialize_files(img)

    w.partition_image_var.set(img)
    w._pex_open_image()

    new = b"#!/bin/sh\n# a longer boot script\n"           # not 18 bytes
    src = tmp_path / "longer_game.sh"
    src.write_bytes(new)

    # Stub the platform driver: it needs WSL2/loop devices, and what this test
    # is about is the GUI wiring around it.
    def fake_grow(image_path, part_offset, jobs, log=None, **k):
        for rel, s in jobs:
            off, _old = placed["/" + rel]
            with open(image_path, "r+b") as f:
                f.seek(off)
                f.write(open(s, "rb").read())
            if log:
                log("  grew %s" % rel, "info")
        return len(jobs)
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "stub"))
    monkeypatch.setattr(ext4_grow, "grow_files", fake_grow)

    asked = []
    from pinball_decryptor.gui import main_window as mw
    monkeypatch.setattr(mw.filedialog, "askopenfilename", lambda **k: str(src))
    monkeypatch.setattr(mw.messagebox, "askyesno",
                        lambda *a, **k: (asked.append(a), True)[1])

    w._pex_replace_selected("/etc/init.d/game")
    deadline = time.time() + 10
    while w._pex_busy and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert not w._pex_busy

    # The confirmation named the size change and what it costs, BEFORE writing.
    prompt = " ".join(str(a) for a in asked[0])
    assert "different size" in prompt and "WSL2" in prompt

    off, _old = placed["/etc/init.d/game"]
    with open(img, "rb") as f:
        f.seek(off)
        assert f.read(len(new)) == new
    status = str(w._pex_action_status["text"])
    assert status.startswith("Replaced /etc/init.d/game") and "grown" in status


def test_partition_explorer_threaded_extract_and_cancel(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """The real button path: _pex_run_extract runs on a worker thread, flips
    the launching button to a live Cancel + shows the spinner overlay, and
    restores everything when it lands.  Regression for a tester's lockup —
    a missing ``threading`` import killed the launch after the buttons were
    disabled, and the old synchronous-only test never went through here."""
    import os
    import threading as threading_mod
    import time
    from tests._ext4_fake import (FakeExt4Reader, install_fake_reader,
                                  write_fake_card)

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")
    w.partition_image_var.set(img)
    w._pex_open_image()

    def _pump_until(cond, timeout=10.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            app.root.update()
            time.sleep(0.01)
        assert cond()

    # Hold the worker at a gate inside every file write so the mid-run UI
    # state (and later the Cancel click) can be asserted without racing it.
    orig_extract = FakeExt4Reader.extract_file
    gates = {"g": threading_mod.Event()}

    def gated(self, node, out_path, progress=None):
        assert gates["g"].wait(10)
        return orig_extract(self, node, out_path, progress=progress)

    monkeypatch.setattr(FakeExt4Reader, "extract_file", gated)

    # --- single-file extract completes and restores the buttons ---
    out = tmp_path / "out.txt"
    w._pex_run_extract("file", "/readme.txt", str(out), w._pex_extract_btn)
    assert w._pex_busy
    assert "Cancel" in str(w._pex_extract_btn["text"])
    assert str(w._pex_extract_part_btn["state"]) == "disabled"
    assert w._pex_busy_lbl.winfo_manager() == "place"   # spinner overlay up
    gates["g"].set()
    _pump_until(lambda: not w._pex_busy)
    assert out.read_bytes() == b"hello world"
    assert "Extracted" in str(w._pex_action_status["text"])
    assert str(w._pex_extract_btn["text"]) == "Extract Selected"
    assert str(w._pex_extract_part_btn["state"]) == "normal"
    assert w._pex_busy_lbl.winfo_manager() == ""        # overlay gone

    # --- whole-partition extract, cancelled mid-run ---
    gates["g"] = threading_mod.Event()
    dump = tmp_path / "dump"
    w._pex_run_extract("dir", "/", str(dump), w._pex_extract_part_btn)
    assert "Cancel" in str(w._pex_extract_part_btn["text"])
    w._pex_extract_part_btn.invoke()                    # the live Cancel
    assert "Cancelling" in str(w._pex_extract_part_btn["text"])
    gates["g"].set()   # worker resumes, sees the cancel at its next tick
    _pump_until(lambda: not w._pex_busy)
    assert "cancelled" in str(w._pex_action_status["text"]).lower()
    assert str(w._pex_extract_part_btn["text"]) == "Extract Whole Partition"
    assert str(w._pex_extract_part_btn["state"]) == "normal"


def test_partition_explorer_defaults_and_history(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """Entering the tab with a blank Card Image defaults to (and opens) the
    Extract tab's image, a successful open lands in the field's recent-paths
    history, and the Extract/Write phase strip hides on this tab
    (a tester's Partition Explorer feedback batch)."""
    import os
    from tests._ext4_fake import install_fake_reader, write_fake_card

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")

    w.extract_input_var.set(img)
    assert not (w.partition_image_var.get() or "").strip()

    for tid in w._notebook.tabs():
        if w._tab_key(tid) == "Partition Explorer":
            w._notebook.select(tid)
            break
    app.root.update()

    assert w.partition_image_var.get() == os.path.normpath(img)
    assert list(w._pex_part_combo["values"])   # opened, not just prefilled
    assert w._extract_phases_frame.winfo_manager() == ""
    assert w._write_phases_frame.winfo_manager() == ""
    # The open was recorded into the recent-paths history backing the
    # Card Image dropdown (same "last N" memory as the Extract screen).
    assert (app._settings["path_history"]["stern"]["partition_image"]
            == [os.path.normpath(img)])
    assert w._path_history["partition_image"] == [os.path.normpath(img)]


def test_partition_explorer_tab_gated_by_capability(app, manufacturers_by_key):
    """The Partition Explorer tab shows for Stern (card image) and hides for a
    plugin without the capability."""
    w = app.window

    def _state(label):
        for tid in w._notebook.tabs():
            if w._tab_key(tid) == label:
                return str(w._notebook.tab(tid, "state"))
        return None

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert _state("Partition Explorer") == "normal"
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert _state("Partition Explorer") == "hidden"


def test_settings_tab_gated_and_form(app, manufacturers_by_key, monkeypatch):
    """The Settings tab shows only for Stern, its form builds from decoded
    adjustment rows, and change-detection reports only edited-and-differing
    settings validated against range."""
    w = app.window

    def _state(label):
        for tid in w._notebook.tabs():
            if w._tab_key(tid) == label:
                return str(w._notebook.tab(tid, "state"))
        return None

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert _state("Default Settings") == "normal"
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert _state("Default Settings") == "hidden"

    # Build the form directly from synthetic rows (no firmware image needed).
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()

    class _FakeTable:
        node = "SYS"
    w._settings_table = _FakeTable()
    rows = [
        {"name": "AD_FREE_PLAY", "label": "Free Play", "kind": "toggle",
         "help": "", "default": 0, "min": 0, "max": 1},
        {"name": "AD_SOUND_MASTER_VOLUME_SETTING", "label": "Master Volume",
         "kind": "number", "help": "", "default": 64, "min": 0, "max": 64},
    ]
    w._settings_build_form(rows)
    assert len(w._settings_rows) == 2
    assert str(w._settings_reset_btn["state"]) == "normal"
    assert w._settings_changes() == {}                 # nothing edited yet
    # Auto-apply belongs to a preset — greyed out while none is selected.
    assert "disabled" in w._settings_auto_cb.state()

    # Edit both; only the differing, in-range values are reported.
    by = {r["name"]: r for r in w._settings_rows}
    by["AD_FREE_PLAY"]["var"].set(1)
    by["AD_SOUND_MASTER_VOLUME_SETTING"]["var"].set(40)
    assert w._settings_changes() == {"AD_FREE_PLAY": 1,
                                     "AD_SOUND_MASTER_VOLUME_SETTING": 40}

    # Out-of-range is clamped into range by the change collector (a below-min
    # volume lands at 0, which differs from the default so it's a real change).
    by["AD_SOUND_MASTER_VOLUME_SETTING"]["var"].set(-5)
    assert w._settings_changes()["AD_SOUND_MASTER_VOLUME_SETTING"] == 0

    # Reset restores the image's current defaults.
    w._settings_reset()
    assert w._settings_changes() == {}

    # --- presets: save / load / auto-apply / delete ---
    by["AD_FREE_PLAY"]["var"].set(1)
    by["AD_SOUND_MASTER_VOLUME_SETTING"]["var"].set(50)
    monkeypatch.setattr(type(w), "_ask_text",
                        lambda self, *a, **k: "My route")
    w._settings_save_preset()
    assert w._presets_blob()["presets"]["My route"]["AD_FREE_PLAY"] == 1
    # Saving selected the preset, so auto-apply is now available.
    assert "disabled" not in w._settings_auto_cb.state()
    # persisted through the app's settings
    assert (app._settings["default_settings_presets"]["presets"]["My route"]
            ["AD_SOUND_MASTER_VOLUME_SETTING"] == 50)

    # Changing fields then reloading the preset restores its values.
    by["AD_FREE_PLAY"]["var"].set(0)
    w._settings_load_preset("My route")
    assert by["AD_FREE_PLAY"]["var"].get() == 1

    # Marking it auto-apply records it as the active preset (persisted).
    w.settings_preset_var.set("My route")
    w.settings_autoapply_var.set(True)
    w._settings_auto_toggle()
    assert w._presets_blob()["active"] == "My route"
    assert app._settings["default_settings_presets"]["active"] == "My route"

    # Delete removes it and clears the active flag.
    import tkinter.messagebox as _mb
    monkeypatch.setattr(_mb, "askyesno", lambda *a, **k: True)
    w.settings_preset_var.set("My route")
    w._settings_delete_preset()
    assert "My route" not in w._presets_blob()["presets"]
    assert w._presets_blob()["active"] is None
    assert "disabled" in w._settings_auto_cb.state()


def test_compare_tab_gated_by_capability(app, manufacturers_by_key):
    """The Compare tab shows only for plugins advertising capabilities.compare
    (Stern), and a manufacturer switch drops any rendered report so a stale
    diff can't survive under the new manufacturer's name."""
    w = app.window

    def _state(label):
        for tid in w._notebook.tabs():
            if w._tab_key(tid) == label:
                return str(w._notebook.tab(tid, "state"))
        return None

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert _state("Compare") == "normal"
    # A rendered report + a manufacturer switch: the tree and sections clear.
    w._compare_sections = [("Compared", [("Image A", "x.raw")])]
    w._compare_tree.insert("", "end", text="Compared", tags=("section",))
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert _state("Compare") == "hidden"
    assert w._compare_sections == []
    assert not w._compare_tree.get_children("")


def test_video_noconv_conflict_helper(app, manufacturers_by_key):
    """'No conversion' + a container the verbatim copy would reject is
    flagged at pick/toggle time (a tester hit it only at build time)."""
    import types
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    w._video_slots_by_rel = {
        "video/AttractMode.mov": types.SimpleNamespace(
            abs_path="C:/x/video/AttractMode.mov", ext=".mov"),
    }
    why = w._video_noconv_conflict("video/AttractMode.mov", "C:/y/clip.mp4")
    assert why and ".mov" in why and ".mp4" in why
    assert w._video_noconv_conflict(
        "video/AttractMode.mov", "C:/y/clip.MOV") is None
    assert w._video_noconv_conflict("unknown/slot.mov", "C:/y/c.mp4") is None


def test_write_preview_scan_in_flight_counts_as_changes(
        app, manufacturers_by_key):
    """Build during a still-running preview scan must not trip the
    "nothing modified" warning — an in-flight scan means "unknown, assume
    changes" (the build diffs everything itself)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    w._write_preview_tree.delete(*w._write_preview_tree.get_children())
    w._scan_t0 = {}
    assert not w._has_pending_write_changes()
    w._scan_t0 = {"write_preview": 1.0}
    assert w._has_pending_write_changes()
    w._scan_t0 = {}


def test_header_double_click_is_not_a_row_action(app, manufacturers_by_key,
                                                 tmp_path, monkeypatch):
    """Clicking a sortable column header fast registers as <Double-1> too;
    the row-action double-click handlers must ignore anything outside the
    data rows (a tester: sorting the image tab quickly popped the
    "No Slot Selected" box / opened the picker)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_image_assets(tmp_path)
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    tree = w._image_tree
    app.root.update()

    popups, assigns = [], []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda *a, **k: popups.append(a))
    monkeypatch.setattr(w, "_image_assign_rel", assigns.append)
    # The invisible test window never maps the tree, so Tk's pixel
    # hit-testing can't run for real — stub the region resolution.
    monkeypatch.setattr(tree, "identify_region",
                        lambda x, y: "heading" if y < 20 else "tree")

    class _HdrEv:
        x, y = 5, 5

    class _RowEv:
        x, y = 5, 40

    # Header double-click: no popup, no picker — with and without a selection.
    w._image_on_tree_double(_HdrEv)
    rel = tree.get_children()[0]
    tree.selection_set(rel)
    w._image_on_tree_double(_HdrEv)
    assert popups == [] and assigns == []

    # A row double-click still opens the picker for the selected slot.
    w._image_on_tree_double(_RowEv)
    assert assigns == [rel] and popups == []


def test_double_click_opens_picker_on_audio_and_video(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """Double-click = choose-a-replacement on EVERY Replace tab (a tester
    batch 11): audio/video used to PLAY the original on double-click while
    images opened the picker.  Playback stays on the right-click menu and
    the preview panes' transport buttons."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    class _RowEv:
        x, y = 5, 40

    # --- audio: real seeded rows ---
    assets = _seed_audio_assets(tmp_path)
    w.write_assets_var.set(assets)
    _scan_audio(w, assets)
    tree = w._audio_tree
    rel = tree.get_children()[0]
    tree.selection_set(rel)
    monkeypatch.setattr(tree, "identify_region", lambda x, y: "tree")
    assigns, plays = [], []
    monkeypatch.setattr(w, "_audio_assign_rel", assigns.append)
    monkeypatch.setattr(w, "_audio_play_original",
                        lambda *a, **k: plays.append("audio"))
    w._audio_on_tree_double(_RowEv)
    assert assigns == [rel] and plays == []

    # --- video: selection stubbed (no video seed helper needed) ---
    vtree = w._video_tree
    monkeypatch.setattr(vtree, "identify_region", lambda x, y: "tree")
    vassigns = []
    monkeypatch.setattr(w, "_video_selected_rel", lambda: "video/clip.mp4")
    monkeypatch.setattr(w, "_video_assign_rel", vassigns.append)
    monkeypatch.setattr(w, "_video_play_original",
                        lambda *a, **k: plays.append("video"))
    w._video_on_tree_double(_RowEv)
    assert vassigns == ["video/clip.mp4"] and plays == []


def test_assign_and_clear_write_log_lines(app, manufacturers_by_key,
                                          tmp_path, monkeypatch):
    """Staging or clearing a replacement writes a log line so a session can
    be double-checked afterwards (feedback batch 11: 'the log does not
    record any replaced video or audio')."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()

    assets = _seed_audio_assets(tmp_path)
    rep = tmp_path / "new_song.wav"
    rep.write_bytes(b"RIFF\x00\x00\x00\x00")
    w.write_assets_var.set(assets)
    _scan_audio(w, assets)

    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.filedialog.askopenfilename",
        lambda *a, **k: str(rep))
    w._audio_tree.selection_set("audio/idx0001.wav")
    w._audio_assign_rel("audio/idx0001.wav")
    log = w._log_text.get("1.0", "end-1c")
    assert "Replace Audio: audio/idx0001.wav ← new_song.wav" in log

    w._audio_clear_selected()
    log = w._log_text.get("1.0", "end-1c")
    assert "cleared replacement for audio/idx0001.wav" in log


def test_write_tab_output_label_says_build_image(app, manufacturers_by_key):
    """The Write tab's destination row reads "Build Image:" — batch 21 merged
    the old "Build Location:" (batch 11) + "File Name:" rows into one full
    destination path."""
    from tkinter import ttk as _ttk
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    labels = [c for c in w._write_output_row_ref.winfo_children()
              if isinstance(c, _ttk.Label)]
    assert any(str(l.cget("text")) == "Build Image:" for l in labels)


# ---------------------------------------------------------------------------
# Image Info tab (a tester)
# ---------------------------------------------------------------------------

def _pump_until(app, cond, timeout=5.0):
    """Drive Tk's event loop (after() callbacks + the info worker poll) until
    *cond* is truthy or *timeout* elapses."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_image_info_window_populates(app, manufacturers_by_key, tmp_path,
                                     monkeypatch):
    """The "Info" button beside the Extract picker opens the Image Info
    window; the worker probe fills the tree with File / Detection /
    Firmware / Assets on Card / Partitions sections and enables Copy
    Report (a tester; window-not-tab per David)."""
    from tests._ext4_fake import install_fake_reader, write_fake_card
    from tests.test_image_info import SIDX_TREE

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch, spec=SIDX_TREE)
    img = write_fake_card(
        tmp_path / "turtles_le-1_23_0.Release.8G.sdcard.raw")

    w.extract_input_var.set(img)
    w._open_image_info(w.extract_input_var)
    assert w._info_win is not None and w._info_win.winfo_exists()
    # While the probe worker runs, the big "Reading image…" overlay sits
    # over the blanked tree (the window looked hung on slow images).
    assert w._info_empty.winfo_manager() == "place"
    assert _pump_until(app, lambda: w._info_tree.get_children(""))
    assert w._info_empty.winfo_manager() == ""

    tree = w._info_tree
    secs = [tree.item(i, "text") for i in tree.get_children("")]
    assert secs[:2] == ["File", "Detection"]
    assert "Firmware" in secs and "Partitions" in secs
    assert "Assets on Card" in secs
    fw_iid = tree.get_children("")[secs.index("Firmware")]
    fw = {tree.item(i, "text"): tree.item(i, "values")[0]
          for i in tree.get_children(fw_iid)}
    assert fw["Version"].startswith("1.23.0") and fw["Edition"] == "LE"
    assert str(w._info_copy_btn["state"]) == "normal"

    # The rendered sections back the Copy Report text verbatim.
    from pinball_decryptor.core.image_info import as_text
    assert "Stern Spike 2" in as_text(w._info_sections)

    # Clicking Info again with the same path re-uses the window and the
    # shown-key skip leaves the tree alone.
    before = tree.get_children("")
    win_before = w._info_win
    w._open_image_info(w.extract_input_var)
    app.root.update()
    assert w._info_win is win_before
    assert tree.get_children("") == before

    w._info_reset()
    assert w._info_win is None


def test_image_info_window_closes_on_mfr_switch(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    import os
    from tests._ext4_fake import install_fake_reader, write_fake_card
    from tests.test_image_info import SIDX_TREE

    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    install_fake_reader(monkeypatch, spec=SIDX_TREE)
    img = write_fake_card(tmp_path / "turtles_pro-1_10_0.sdcard.raw")

    w.extract_input_var.set(img)
    w._open_image_info(w.extract_input_var)
    assert _pump_until(app, lambda: w._info_tree.get_children(""))
    assert os.path.normpath(img) == w._info_path

    # Switching manufacturers closes the window (a JJP header must not sit
    # over Stern card details).
    app._on_manufacturer_change(manufacturers_by_key["jjp"])
    app.root.update()
    assert w._info_win is None
    assert not w._info_sections


def test_image_info_button_without_valid_path(app, manufacturers_by_key,
                                              monkeypatch):
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    shown = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda title, msg, **k: shown.append(("info", title)))
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showerror",
        lambda title, msg, **k: shown.append(("error", title)))

    w.extract_input_var.set("")
    w._open_image_info(w.extract_input_var)
    assert shown[-1] == ("info", "No image selected")
    assert w._info_win is None

    w.extract_input_var.set(r"C:\nope\gone.raw")
    w._open_image_info(w.extract_input_var)
    assert shown[-1] == ("error", "File not found")
    assert w._info_win is None


def test_jjp_dongle_extract_checkbox_and_phase_swap(app, manufacturers_by_key):
    """The advanced 'Decrypt using the game's HASP dongle' checkbox is shown
    only for JJP, and ticking it swaps the extract step row to the dongle-
    bearing phase list (Chroot / Dongle / Compile appear)."""
    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["jjp"])
    app.root.update(); app.root.update()
    # ISO mode (not SSD) so the dongle option is meaningful
    win.extract_input_source_var.set("iso")
    win._refresh_extract_phases()
    assert win._dongle_extract_frame.winfo_manager() == "pack"
    assert win.extract_dongle_var.get() is False
    assert "Dongle" not in win._extract_phases

    win.extract_dongle_var.set(True)
    win._on_dongle_extract_toggle()
    app.root.update()
    assert "Dongle" in win._extract_phases
    assert "Compile" in win._extract_phases

    # A plugin without the capability never shows the row, and the toggle is
    # reset so it can't leak a stale ON.
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert win._dongle_extract_frame.winfo_manager() == ""
    assert win.extract_dongle_var.get() is False


def test_scene_browser_preview_and_videos(app, tmp_path):
    """The Scenes window lists a scene's videos and previews the scene itself.

    The render runs on a worker thread, so the threaded hop is exercised by
    calling the two halves directly — a sleep-until-drawn loop would put real
    wall-clock into the suite for no extra coverage."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import json
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import scene_render

    _make_extract(tmp_path)
    # a video belonging to scene1, named the way the extractor names them
    vdir = tmp_path / "video"
    vdir.mkdir()
    (vdir / "Intro_Clip.mp4").write_bytes(b"\x00" * 32)
    (vdir / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "Intro_Clip.mp4\t/g/scene1/scene.assets/3.asset/0.asset\t32\n",
        encoding="utf-8")
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 60.0], "partial": False, "unplaced": 0,
        "offstage": 0, "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": "A",
             "rect": [0, 0, 320, 180], "rgba": [1, 1, 1, 1], "align": 1,
             "font": "radimg_TestA_8x8_00000001"}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)

    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser
    sb._tree.selection_set("/g/scene1")
    sb._on_select()

    # the video shows up in Contents, and its row jumps to the Video tab
    rows = {}
    for sect in sb._detail.get_children():
        name = sb._detail.item(sect, "text").split(" (")[0]
        rows[name] = list(sb._detail.get_children(sect))
    assert [sb._detail.item(r, "text") for r in rows["Videos"]] == [
        "Intro_Clip.mp4"]
    assert rows["Videos"][0] == "vid::video/Intro_Clip.mp4"

    # the scene has a layout, so a render was scheduled
    assert sb._preview_lbl.cget("text") == "Drawing…"
    # finishing it enables Save and captions what the frame does/doesn't show
    img = Image.new("RGB", (320, 180), (0, 0, 0))
    sb._show_preview(sb._preview_token, [img],
                     layout["/g/scene1/scene.radium"])
    assert str(sb._save_btn.cget("state")) == "normal"
    # A still picture says so, and offers NO playback controls: a Speed box on
    # something that cannot move implied there was animation being withheld.
    assert "Still picture" in sb._preview_lbl.cget("text")
    assert sb._fps_shown is False
    # ...and no Screen control either: this scene is a single screen
    assert sb._screen_shown is False
    assert sb._preview_full is img

    # a superseded render is discarded rather than painted over the new scene
    sb._show_preview(sb._preview_token - 1, [Image.new("RGB", (8, 8))], {})
    assert sb._preview_full is img

    # an animated scene hands over several frames and starts playing them
    frames = [Image.new("RGB", (320, 180), c)
              for c in ((10, 0, 0), (0, 10, 0), (0, 0, 10))]
    animated = dict(layout["/g/scene1/scene.radium"])
    animated["sprites"] = [{"name": "a", "x": 0, "y": 0, "image": "x.png",
                            "frames": ["a.png", "b.png", "c.png"]}]
    sb._show_preview(sb._preview_token, frames, animated)
    assert len(sb._frame_imgs) == 3
    assert sb._play_job is not None            # the loop is running
    assert "Animation: 3 frames" in sb._preview_lbl.cget("text")
    assert sb._fps_shown is True               # ...so Speed appears now
    # the scene's own 60 fps rate is played, not an arbitrary cap (David: the
    # animation ran slow), and the Speed box can pin a fixed rate instead
    assert "60 fps" in sb._preview_lbl.cget("text")
    assert sb._effective_fps(animated) == 60.0
    sb._fps_var.set("4 fps")
    sb._restart_animation()
    assert sb._effective_fps(animated) == 4.0
    assert sb._play_job is not None            # still running, just slower
    sb._fps_var.set("Scene rate")
    assert sb._effective_fps(animated) == 60.0
    # switching scenes invalidates the token, which stops the old loop
    before = sb._preview_token
    sb._render_preview("/g/scene2")
    assert sb._preview_token != before
    assert sb._frame_imgs == []

    # a scene with no recorded layout says so instead of drawing a black frame
    sb._tree.selection_set("/g/scene2")
    sb._on_select()
    assert sb._preview_lbl.cget("text").startswith("No preview")
    assert str(sb._save_btn.cget("state")) == "disabled"

    sb._close()
    app.root.update()


def test_scene_browser_caption_is_one_line_with_the_rest_on_its_button(app,
                                                                      tmp_path):
    """The caption admits whatever a scene couldn't decode, so it wrapped to
    one, two or three lines depending on the scene and the pane jumped every
    time you stepped to another screen — "the area gets resized between
    different screens and it is jarring" (David).  One capped line stays on
    screen; the whole text lives on the "?" beside it."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod

    _make_extract(tmp_path)
    app.window.write_assets_var.set(str(tmp_path))
    app.window._open_scene_browser()
    sb = app.window._scene_browser

    long_note = ("Still picture: 2 images and 6 text lines on a 1360x768 "
                 "stage. 43 more images in this scene can't be placed yet. "
                 "1 element sits off the stage, so its position isn't fully "
                 "decoded.")
    sb._set_caption(long_note)
    shown = sb._preview_lbl.cget("text")
    assert shown == "Still picture: 2 images and 6 text lines on a 1360x768 stage."
    assert "\n" not in shown and len(shown) <= sb_mod._CAPTION_CHARS
    assert sb._caption_tip.text == long_note      # the rest is a hover away
    # a caption longer than the cap is truncated rather than allowed to widen
    sb._set_caption("x" * 400)
    assert len(sb._preview_lbl.cget("text")) <= sb_mod._CAPTION_CHARS
    assert sb._caption_tip.text == "x" * 400

    sb._close()
    app.root.update()


def test_scene_browser_steps_through_screens(app, tmp_path):
    """◀/▶ walk the Screen list without re-opening the drop-down (David), with
    "All screens" as the entry before the first and wrap-around at both ends."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod

    _make_extract(tmp_path)
    app.window.write_assets_var.set(str(tmp_path))
    app.window._open_scene_browser()
    sb = app.window._scene_browser
    # drive the stepper against a known screen list
    sb._current_layout = lambda: {"groups": ["Intro_Instance", "Award1"]}
    sb._render_preview = lambda *_a, **_k: None
    sb._tree.selection_set()

    assert sb._screen_var.get() == sb_mod._ALL_SCREENS
    sb._step_screen(1)
    assert sb._screen_var.get() == "Intro_Instance"
    sb._step_screen(1)
    assert sb._screen_var.get() == "Award1"
    sb._step_screen(1)                       # wraps back to the composite
    assert sb._screen_var.get() == sb_mod._ALL_SCREENS
    sb._step_screen(-1)                      # and backwards off the front
    assert sb._screen_var.get() == "Award1"

    sb._close()
    app.root.update()


def test_side_tooltip_does_not_cover_its_row(app):
    """A tooltip bound to a combobox opened exactly where the drop-down does,
    so hovering to read it hid the control being clicked and the picker was
    unusable (David).  The explanation moved onto its own "?" button, and the
    tip is placed BESIDE it."""
    import tkinter as tk
    from tkinter import ttk
    from pinball_decryptor.gui.widgets import _Tooltip

    top = tk.Toplevel(app.root)
    top.geometry("400x200+100+100")
    row = ttk.Frame(top)
    row.pack()
    box = ttk.Combobox(row, values=["a"], width=12, state="readonly")
    box.pack(side=tk.LEFT)
    btn = ttk.Button(row, text="?", width=2)
    btn.pack(side=tk.LEFT, padx=(6, 0))
    tip = _Tooltip(btn, "an explanation long enough to wrap " * 4,
                   lambda: "dark", place="side")
    app.root.update_idletasks()
    tip.show()
    app.root.update_idletasks()

    def rect(w):
        return (w.winfo_rootx(), w.winfo_rooty(),
                w.winfo_rootx() + w.winfo_width(),
                w.winfo_rooty() + w.winfo_height())

    t = tip._tip
    tr = (t.winfo_rootx(), t.winfo_rooty(),
          t.winfo_rootx() + t.winfo_width(),
          t.winfo_rooty() + t.winfo_height())

    def overlaps(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0]
                    or a[3] <= b[1] or b[3] <= a[1])

    assert not overlaps(tr, rect(box)), "the tip must not cover the picker"
    assert not overlaps(tr, rect(btn))
    assert tr[0] >= rect(btn)[2], "placed beside it, not under it"
    tip.hide()
    top.destroy()
    app.root.update()


def test_scene_browser_rebuild_previews_action(app, tmp_path, monkeypatch):
    """"Rebuild previews…" re-reads the layouts off the card without a full
    re-extract (which would overwrite the atlas PNGs and glyph slices, wiping
    a font import).  The threaded read is covered in the engine tests; what
    matters here is that it takes the card from the Extract tab, refuses
    politely without one, and can be cancelled."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod

    _make_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser

    said = []
    monkeypatch.setattr(sb_mod.messagebox, "showinfo",
                        lambda *a, **k: said.append(a))

    # no card image on the Extract tab -> a nudge, and nothing starts
    w.extract_input_var.set("")
    sb._rebuild_previews()
    assert len(said) == 1 and sb._rebuild is None

    # a path that isn't a file is the same case (a stale saved setting)
    w.extract_input_var.set(str(tmp_path / "not_a_card.raw"))
    sb._rebuild_previews()
    assert len(said) == 2 and sb._rebuild is None

    card = tmp_path / "card.raw"
    card.write_bytes(b"\x00" * 16)
    w.extract_input_var.set(str(card))
    assert sb.card_image_path() == str(card)

    # while one runs the button cancels it, and a cancelled run leaves the
    # layouts alone rather than reporting a rebuild
    state = sb._rebuild = {"cancel": False}
    sb._rebuild_btn.configure(text="Cancel")
    sb._rebuild_previews()
    assert state["cancel"] is True
    sb._rebuild_done(state, 0, None, [])
    assert "Stopped" in sb._rebuild_lbl.cget("text")
    assert str(sb._rebuild_btn.cget("text")) == "Rebuild previews…"

    # a finished run reports the count and reloads the window
    reloaded = []
    monkeypatch.setattr(type(sb), "reload",
                        lambda self, preselect=None: reloaded.append(preselect))
    state = sb._rebuild = {"cancel": False}
    sb._rebuild_tick(state, 40, 297)
    assert "40 of 297" in sb._rebuild_lbl.cget("text")
    sb._rebuild_done(state, 297, None, [])
    assert "297" in sb._rebuild_lbl.cget("text")
    assert len(reloaded) == 1

    # a stale worker's result (its state superseded) is ignored outright
    sb._rebuild_done({"cancel": False}, 5, None, [])
    assert len(reloaded) == 1

    sb._close()
    app.root.update()


def _seed_scene_with_text(tmp_path, text="CLOCK NOT SET",
                          rgba=(1.0, 1.0, 1.0, 1.0)):
    """``_make_extract`` plus one editable string and a layout drawing it, so
    the Scenes window has a Text row with a known colour."""
    import json
    from pinball_decryptor.plugins.stern import scene_render
    (tmp_path / "text").mkdir(exist_ok=True)
    (tmp_path / "text" / "strings.tsv").write_text(
        "# asset_path\toriginal\treplacement\n"
        "/g/scene1/scene.radium\t%s\t\n" % text, encoding="utf-8")
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0,
        "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": text,
             "rect": [0, 0, 320, 180], "rgba": list(rgba), "align": 1,
             "font": "tbl"}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)


def test_scene_browser_recolours_a_line_and_offers_backdrops(app, tmp_path,
                                                             monkeypatch):
    """a tester: "as i understand the Font color is in the scene itself... maybe
    something to switch the color to turtle green" — and, separately, "would it
    be possible to do some different backgrounds?".

    Recolouring is a scene edit, not a font edit, so it lives on the text row
    and records what the colour was as well as what it becomes."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod
    from pinball_decryptor.plugins.stern import scene_render, text_colors

    _make_extract(tmp_path)
    _seed_scene_with_text(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser
    sb._tree.selection_set("/g/scene1")
    sb._on_select()

    def _text_row():
        for sect in sb._detail.get_children():
            for row in sb._detail.get_children(sect):
                if row.startswith("txt::"):
                    return sb._detail.item(row, "values")[0]
        return ""

    # the row says the colour the GAME draws that line in
    assert "#ffffff" in _text_row()

    monkeypatch.setattr(sb_mod.colorchooser, "askcolor",
                        lambda *a, **k: ((51, 204, 51), "#33cc33"))
    sb._pick_text_color("CLOCK NOT SET")
    assert text_colors.load(str(tmp_path)) == {
        "/g/scene1/scene.radium": {
            "CLOCK NOT SET": ((255, 255, 255), (51, 204, 51))}}
    # ...shown as a pending change, and handed to the preview render
    assert "#ffffff → #33cc33" in _text_row()
    assert "not built yet" in _text_row()
    assert sb._pending_colors("/g/scene1/scene.radium") == {
        "CLOCK NOT SET": (51, 204, 51)}

    # backdrops: the machine's black plus somewhere to see a black border
    assert "Checkerboard" in list(sb._bg_box.cget("values"))
    sb._bg_var.set("White")
    sb._rerender()
    assert sb._background_name() == "White"
    assert sb._preview.cget("bg") == "#ffffff"
    assert scene_render.background_spec("White") == (255, 255, 255)

    # and it can be put back, which removes the row rather than storing a no-op
    sb._pick_text_color("CLOCK NOT SET", reset=True)
    assert text_colors.load(str(tmp_path)) == {}
    assert "right-click to recolour" in _text_row()

    sb._close()
    app.root.update()


def test_scene_browser_blanks_a_font_out_of_one_scene(app, tmp_path,
                                                      monkeypatch):
    """a tester, about an outline/shadow font: "Is there an easy way to blank it
    out from the scene menu? when i do doubleclick on it, it will go the import
    windows, but it will not blank it out there."

    It blanks scoped to the scene it was asked from — the atlas is shared, so
    an unscoped blank strips the same border off every other scene."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    _seed_scene_with_text(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser
    sb._tree.selection_set("/g/scene1")
    sb._on_select()

    font = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}["tbl"]
    glyph = font["glyphs"][0x41]["abs"]
    assert np.asarray(Image.open(glyph).convert("RGBA"))[..., 3].max() > 0

    monkeypatch.setattr(sb_mod.messagebox, "askyesno", lambda *a, **k: True)
    sb._blank_font("tbl", True)
    assert np.asarray(Image.open(glyph).convert("RGBA"))[..., 3].max() == 0
    # this font is also in /g/scene9; the blank must not reach it
    assert fr.get_font_scope(str(tmp_path), font) == [
        "/g/scene1/scene.radium"]
    assert "Blanked" in sb._preview_lbl.cget("text")

    sb._close()
    app.root.update()


def test_font_studio_blank_button_and_scene_tint_note(app, tmp_path,
                                                      monkeypatch):
    """The Fonts window can blank a font on its own (it used to happen only as
    a side effect of importing into the font an outline sits behind), and says
    what the scenes multiply the ink by — which is why a tester's colour picks
    "did not produce what i wanted"."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import font_studio as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    # the scenes draw this font BLACK: no ink colour can ever show there
    _seed_scene_with_text(tmp_path, rgba=(0.0, 0.0, 0.0, 1.0))
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("tbl")
    fs._on_select()

    assert fs._tint_lbl.winfo_manager() != ""
    note = fs._tint_lbl.cget("text")
    assert "MULTIPLIES" in note and "tinted black" in note

    # the preview can be put on something other than black
    assert "Checkerboard" in fs_mod._SCENE_BG_NAMES
    fs._bg_var.set("Checkerboard")
    fs._render_now()                       # must not raise

    glyph = fs._current_font()["glyphs"][0x41]["abs"]
    assert np.asarray(Image.open(glyph).convert("RGBA"))[..., 3].max() > 0
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._blank()
    assert np.asarray(Image.open(glyph).convert("RGBA"))[..., 3].max() == 0
    assert "blanked" in fs._status.cget("text")

    # blanking is undoable — it is a write like any other, not a one-way door
    fs._undo_last()
    assert np.asarray(Image.open(glyph).convert("RGBA"))[..., 3].max() > 0

    # a font no scene is recorded as drawing says nothing at all rather than
    # guessing white
    assert "tbl2" in {f["key"] for f in fr.load_fonts(str(tmp_path))}
    fs._tree.selection_set("tbl2")
    fs._on_select()
    assert fs._tint_lbl.winfo_manager() == ""
    fs._close()
    app.root.update()


def test_font_studio_colour_alone_repaints_the_current_letters(app, tmp_path,
                                                               monkeypatch):
    """The Color swatch used to reach only an imported desktop font: pick a
    colour with no font file and the swatch went green while the preview stayed
    white (David hit exactly this).  A colour on its own now stages a repaint of
    the letters already there, applied like any other edit."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("tbl")
    fs._on_select()
    assert str(fs._apply_btn.cget("state")) == "disabled"

    monkeypatch.setattr(fs_mod.colorchooser, "askcolor",
                        lambda *a, **k: ((51, 204, 51), "#33cc33"))
    fs._pick_color()

    # previewable and applyable with no font file anywhere, and NOT staged as
    # a pending import (browsing the list must not fill it with edits)
    assert "tbl" not in fs._pending
    assert fs._custom_color() is True
    assert str(fs._apply_btn.cget("state")) == "normal"
    fs._render_now()
    assert "in #33cc33" in fs._status.cget("text")

    # the colour is a SETTING: it follows the selection down the list, which is
    # what David reported missing ("when i change the font selection, the color
    # preview does not carry over")
    fs._tree.selection_set("tbl2")
    fs._on_select()
    fs._render_now()
    assert fs._custom_color() is True
    assert "in #33cc33" in fs._status.cget("text")
    assert str(fs._apply_btn.cget("state")) == "normal"

    fs._tree.selection_set("tbl")
    fs._on_select()
    glyph = fs._current_font()["glyphs"][0x41]["abs"]
    fs._apply()
    on_disk = np.asarray(Image.open(glyph).convert("RGBA"))
    assert (on_disk[on_disk[..., 3] > 0][:, :3] == (51, 204, 51)).all()
    assert "repainted #33cc33" in fs._status.cget("text")

    # ...and it undoes like any other write
    fs._undo_last()
    back = np.asarray(Image.open(glyph).convert("RGBA"))
    assert not (back[back[..., 3] > 0][:, :3] == (51, 204, 51)).all()

    # back on "match original" there is nothing of the user's left to apply
    fs._auto_color_var.set(True)
    fs._on_option_change()
    assert fs._custom_color() is False
    assert str(fs._apply_btn.cget("state")) == "disabled"

    fs._close()
    app.root.update()


def test_font_studio_outline_companion(app, tmp_path, monkeypatch):
    """The Fonts window names the outline font drawn behind a typeface, and
    can remove it with the import.

    A tester restyled a whole game and kept getting "a strange inconsistent black
    border" he blamed on his own stroke colour: it was the ORIGINAL typeface's
    outline companion, a separate font he had no reason to open.  The window
    now says so on the font that has one, and Apply can blank it."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio

    # the body font is told what sits behind it, and offered the removal
    fs._tree.selection_set("body")
    fs._on_select()
    assert fs._companion(fs._current_font())["key"] == "ok"
    assert "in black behind" in fs._comp_lbl.cget("text")
    assert fs._comp_ctrl.winfo_manager() != ""
    assert "+outline" in fs._tree.item("body", "values")[0]

    # the companion itself explains what it IS, with no action offered
    fs._tree.selection_set("ok")
    fs._on_select()
    assert "This IS an outline font" in fs._comp_lbl.cget("text")
    assert fs._comp_ctrl.winfo_manager() == ""

    # a font with neither says nothing at all
    fs._tree.selection_set("wrong")
    fs._on_select()
    assert fs._comp_row.winfo_manager() == "" or fs._comp_lbl.cget("text")

    # Apply with "remove it" blanks the companion's slices…
    fs._tree.selection_set("body")
    fs._on_select()
    fo = fs._current_font()
    fs._pending[fo["key"]] = ({0x41: Image.new("RGBA", (4, 6), (9, 9, 9, 255))},
                              6, [], "x.ttf")
    fs._comp_var.set(fs_mod._COMP_CLEAR)
    fs._apply()
    comp = fs._companions["body"]
    a = np.asarray(Image.open(comp["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert a[..., 3].max() == 0, "the old outline should draw nothing now"
    assert "was blanked" in fs._status.cget("text")

    # …and ONLY in the scenes this font is in.  Blanking is card-wide by
    # default (one atlas serves every scene that draws it), so an unscoped
    # removal strips the outline off screens the user never touched — on TMNT
    # 446 scene occurrences against 6 that overlap the body font.  A tester did
    # exactly that by hand: "i did remove to much shadow, now on the normal
    # font some are missing too".
    scoped = fr.get_font_scope(str(tmp_path), comp)
    assert scoped == ["/g/scene1/scene.radium"], scoped
    assert "/g/scene5/scene.radium" not in (scoped or []), \
        "the scene without the body font must keep its outline"

    # …and Revert puts it back, so the removal is never a one-way door
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._revert()
    back = np.asarray(Image.open(comp["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert back.shape[:2] == a.shape[:2]

    fs._close()
    app.root.update()


def test_font_studio_applies_to_every_size_of_a_typeface(app, tmp_path,
                                                         monkeypatch):
    """One typeface is baked at many sizes and each is its own font here —
    TMNT lists Stern_CCZoinks 94 times.  A tester "replaced the font wherever i
    found it" and still saw stock letters, because nobody does 94 imports by
    hand.  Apply fits the same font file into every size."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract, _system_ttf
    if _system_ttf() is None:
        pytest.skip("no system TTF found")
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("body")
    fs._on_select()

    # the tick names the real count and is hidden for a one-off typeface
    assert fs._same_typeface(fs._current_font())[0]["key"] == "body2"
    assert "other 1 size" in fs._all_sizes_cb.cget("text")
    assert fs._all_sizes_cb.winfo_manager() != ""

    sib = fs._by_key["body2"]
    before = open(sib["glyphs"][0x41]["abs"], "rb").read()
    fs._ttf_paths["body"] = _system_ttf()
    fs._rasterize()
    assert fs._all_sizes_var.get() is True
    fs._apply()
    after = open(sib["glyphs"][0x41]["abs"], "rb").read()
    assert after != before, "the other size should have been restyled too"
    assert "1 more size" in fs._status.cget("text")

    # Revert all puts the whole project back, which is how you start over
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._revert_all()
    assert "restored to stock" in fs._status.cget("text")
    a = np.asarray(Image.open(sib["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert a.shape[:2] == (sib["glyphs"][0x41]["h"], sib["glyphs"][0x41]["w"])

    fs._close()
    app.root.update()


def test_font_studio_undo_steps_back_rather_than_to_stock(app, tmp_path,
                                                          monkeypatch):
    """Undo is not Revert.  Revert goes all the way back to the stock letters;
    Undo goes back ONE step, to whatever was there before — the import you had
    before this one, or the whole project before "Revert all fonts"."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._all_sizes_var.set(False)
    fs._tree.selection_set("body")
    fs._on_select()
    fo = fs._current_font()
    slot = fo["glyphs"][0x41]
    stock = open(slot["abs"], "rb").read()
    assert str(fs._undo_btn.cget("state")) == "disabled"

    def apply_colour(rgb):
        fs._pending[fo["key"]] = (
            {0x41: Image.new("RGBA", (slot["w"], slot["h"]), rgb)},
            34, [], "x.ttf")
        fs._apply()
        return open(slot["abs"], "rb").read()

    first = apply_colour((10, 200, 10, 255))
    assert first != stock
    assert str(fs._undo_btn.cget("state")) == "normal"
    assert "import" in fs._undo_btn.cget("text")
    second = apply_colour((200, 10, 10, 255))
    assert second != first

    fs._undo_last()
    assert open(slot["abs"], "rb").read() == first, "back one step, not to stock"
    assert "Undid" in fs._status.cget("text")
    fs._undo_last()
    assert open(slot["abs"], "rb").read() == stock
    assert str(fs._undo_btn.cget("state")) == "disabled"

    # and the destructive action is recoverable too
    third = apply_colour((10, 10, 200, 255))
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._revert_all()
    assert open(slot["abs"], "rb").read() != third
    fs._undo_last()
    assert open(slot["abs"], "rb").read() == third, \
        "Revert all fonts must be undoable"

    # switching project folders drops the history: those are absolute paths in
    # the OLD project, and undoing would write files back into it
    apply_colour((0, 0, 0, 255))
    assert fs._undo
    fs.assets_dir = str(tmp_path / "elsewhere")
    fs.reload()
    assert fs._undo == []
    assert str(fs._undo_btn.cget("state")) == "disabled"

    fs._close()
    app.root.update()


def test_font_studio_will_not_lose_an_unapplied_import(app, tmp_path,
                                                       monkeypatch):
    """a tester: "on some i have forgotten to press the apply font :(".  A fitted
    import that was never applied is invisible once the window closes, and he
    found out on the machine."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("body")
    fs._on_select()
    fs._pending["body"] = ({0x41: Image.new("RGBA", (20, 34))}, 34, [], "x.ttf")
    fs._refresh_font_list("body")
    assert "NOT APPLIED" in fs._tree.item("body", "values")[0]

    # closing asks first, and "no" keeps the window open
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: False)
    fs._close()
    assert fs.win.winfo_exists()

    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._close()
    app.root.update()


def test_font_studio_warns_before_restyling_a_tiny_font(app, tmp_path,
                                                        monkeypatch):
    """a tester: "smaller fonts do look more and more strange the smaller they
    get… i guess they should be skipped".  The list marks them and Apply asks
    once — it does not refuse, because his call is the one that counts."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import font_studio as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("tbl")
    fs._on_select()
    fo = fs._current_font()
    assert fo["px"] < fr.MIN_RESTYLE_PX
    assert "tiny" in fs._tree.item("tbl", "values")[0]

    asked = []
    monkeypatch.setattr(fs_mod.messagebox, "askyesno",
                        lambda *a, **k: (asked.append(a), False)[1])
    fs._pending[fo["key"]] = ({0x41: Image.new("RGBA", (4, 6))}, 6, [], "x.ttf")
    fs._apply()
    assert asked and "pixels tall" in asked[0][1]
    assert fo["key"] in fs._pending, "declining must not write anything"

    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._apply()
    assert fo["key"] not in fs._pending

    fs._close()
    app.root.update()


def test_font_studio_scene_scope_control(app, tmp_path):
    """The Fonts window can limit a font edit to chosen scenes: picking scenes
    persists a scope the Build reads, and switching back to "all" clears it."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("tbl")
    fs._on_select()

    # Default is every scene, and nothing is persisted until you narrow it.
    assert fs._scope_var.get() == "all"
    assert fs._scene_paths == ["/g/scene1/scene.radium",
                               "/g/scene9/scene.radium"]
    assert "all 2 scenes" in fs._scope_lbl.cget("text")
    assert fr.get_font_scope(str(tmp_path), fs._current_font()) is None

    # Narrow to the second scene -> saved for the Build to read.
    fs._scope_var.set("some")
    fs._on_scope_mode()
    fs._scenes_list.selection_clear(0, "end")
    fs._scenes_list.selection_set(1)
    fs._on_scope_select()
    assert fr.get_font_scope(str(tmp_path), fs._current_font()) == [
        "/g/scene9/scene.radium"]
    assert "Only 1 of 2" in fs._scope_lbl.cget("text")

    # It survives a reload of the window (it lives in the project folder).
    fs.reload("tbl")
    assert fs._scope_var.get() == "some"
    assert fs._scenes_list.curselection() == (1,)

    # Back to all -> scope cleared.
    fs._scope_var.set("all")
    fs._on_scope_mode()
    assert fr.get_font_scope(str(tmp_path), fs._current_font()) is None

    # Close the tool window: it leaves a pending preview-render `after` job
    # that would otherwise outlive the root and break teardown.
    fs._close()
    app.root.update()


def test_font_studio_and_scene_browser_smoke(app, tmp_path):
    """The Fonts and Scenes tool windows (a tester) open on a synthetic Stern
    extract, populate their lists from the manifests, render a preview, and
    close cleanly.  Layout/pixel correctness lives in test_stern_fontrender;
    this is construction + wiring only."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.core import text_manifest

    _make_extract(tmp_path)
    text_manifest.save(str(tmp_path), [
        {"path": "/g/scene1/scene.radium", "original": "HELLO",
         "replacement": ""}])
    w = app.window
    w.write_assets_var.set(str(tmp_path))

    w._open_font_studio()
    fs = w._font_studio
    assert fs.win.winfo_exists()
    assert set(fs._tree.get_children()) == {"tbl", "tbl2"}
    fs._text_var.set("AB")
    fs._render_now()
    assert fs._photo is not None                 # a preview actually rendered
    # scene usage list filled for the selected font
    assert fs._scenes_list.size() >= 1

    # re-open with a glyph-row preselect resolves the owning font
    w._open_font_studio(
        preselect_rel="images/scene_textures/glyphs/"
                      "radimg_bc1_8x8_00000003/U+0043_C.png")
    assert fs._tree.selection() == ("tbl2",)

    w._open_scene_browser()
    sb = w._scene_browser
    assert sb.win.winfo_exists()
    kids = sb._tree.get_children()
    assert "/g/scene1" in kids and "/g/scene2" in kids
    # every heading sorts, counts descending first, and clicking again flips
    by_imgs = lambda: [int(sb._tree.set(k, "imgs"))
                       for k in sb._tree.get_children()]
    sb._sort_by("imgs")
    assert by_imgs() == sorted(by_imgs(), reverse=True)
    sb._sort_by("imgs")
    assert by_imgs() == sorted(by_imgs())
    assert "▴" in sb._tree.heading("imgs", "text")
    sb._sort_by("#0")
    names = [sb._tree.item(k, "text").lower()
             for k in sb._tree.get_children()]
    assert names == sorted(names)
    sb._tree.selection_set("/g/scene1")
    sb._on_select()
    det = sb._detail.get_children()
    sections = [sb._detail.item(d, "text").split(" (")[0] for d in det]
    assert sections == ["Images", "Fonts", "Text", "Videos"]
    # double-clicking a text row lands on the Replace Text tab's search
    sb._detail.selection_set(
        sb._detail.get_children(det[2])[0])
    sb._on_detail_double(None)
    assert w.text_search_var.get() == "HELLO"

    fs._close()
    sb._close()
    app.root.update()


# ---------------------------------------------------------------------------
# feedback batch 22
# ---------------------------------------------------------------------------

def test_write_original_row_keeps_the_info_badge_beside_the_path(app):
    """The ⓘ badge sits right after the Original path, not shoved to the far
    edge of the window by an expanding label (feedback batch 22)."""
    w = app.window
    kids = w._write_upd_row.pack_slaves()
    path_lbl = kids[1]
    assert path_lbl.pack_info().get("expand") in (0, "0", False)


def test_text_scan_uses_the_shared_scanning_state(app, tmp_path):
    """Replace Text scans on a worker thread behind the same big animated
    indicator + Cancel-scan button as the other Replace tabs (feedback batch
    22: it used to freeze the window with no sign of life)."""
    w = app.window
    w._set_tab_scanning("text", True)
    try:
        assert w._scan_buttons["text"].cget("text") == "Cancel scan"
        assert "18" in str(w._text_empty.cget("font"))     # the big font
    finally:
        w._set_tab_scanning("text", False)
    assert w._scan_buttons["text"].cget("text") == "Scan"

    # The worker's result lands through the main-thread half, which leaves the
    # scanning state and reports an empty manifest.  (The worker itself posts
    # via a cross-thread after(), which only runs under a real mainloop — the
    # same shape as the audio/video/image scans.)
    w._set_tab_scanning("text", True)
    w._populate_text_after_scan([], None, w._text_scan_id, str(tmp_path))
    assert w._scan_buttons["text"].cget("text") == "Scan"
    assert w._text_rows == []
    assert w._text_scan_dir == str(tmp_path)
    assert "No editable on-screen text" in w._text_empty.cget("text")

    # A result from a superseded scan is dropped, stamp and all.
    w._set_tab_scanning("text", True)
    stale = w._text_scan_id
    w._text_scan_id += 1
    w._populate_text_after_scan(
        [{"path": "p", "original": "A", "replacement": "B"}], None, stale, "x")
    assert w._text_rows == []
    w._set_tab_scanning("text", False)


def test_invalidating_scans_rescans_the_visible_tab(app, manufacturers_by_key):
    """Opening/forking a project clears the scan stamps, and the tab already on
    screen gets no <<NotebookTabChanged>> — so it is re-scanned directly
    (feedback batch 22: after a fork the Video tab kept the old project's
    slots until he left and came back)."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    called = []
    w._scan_assets_tab_by_name = lambda text: called.append(text)
    w.invalidate_asset_scans()
    assert len(called) == 1
    # The scan-every-tab path must not double up on the visible one.
    called.clear()
    w._rescan_all_assets_tabs = lambda: called.append("all")
    w.reload_assets_tabs()
    assert called == ["all"]


def test_video_convert_column_reports_as_is_vs_reencode(app, tmp_path):
    """The video list says what Write will DO with each assigned clip, instead
    of leaving it in the log at pick time (feedback batch 22)."""
    from pinball_decryptor.core.video_slots import VideoSlot
    w = app.window
    slot = VideoSlot(rel_path="video/a.mov",
                     abs_path=str(tmp_path / "a.mov"),
                     ext=".mov", info=None, size=1)
    rep = tmp_path / "rep.mov"
    rep.write_bytes(b"x")

    # "No conversion" on + matching container = copied through verbatim.
    assert w._video_conv_mode(slot, str(rep), True, False) == \
        w._VIDEO_CONV_ASIS
    # ...and a container the copy-through would reject NAMES what it needs.
    # This used to report nothing at all, which is why 27 of a tester's 29
    # rows sat blank and he asked why only one said "As-is" (batch 23); see
    # test_gui_video_convert_column.py for the rest of that behaviour.
    other = tmp_path / "rep.mp4"
    other.write_bytes(b"x")
    assert w._video_conv_mode(slot, str(other), True, False) == \
        w._VIDEO_CONV_WRONG_TYPE % ".mov"

    # The cache is keyed on the pick AND both option flags, so flipping a
    # checkbox can't leave a stale answer on screen.
    key_off = w._video_conv_key("video/a.mov", str(rep))
    w.video_trim_var.set(not w.video_trim_var.get())
    assert w._video_conv_key("video/a.mov", str(rep)) != key_off
    # Unresolved rows read "…"; unassigned rows stay blank.
    assert w._video_conv_cached("video/a.mov", str(rep)) == "…"
    assert w._video_conv_cached("video/a.mov", None) == ""


def _poster_pane(app):
    """A video preview pane parented on the live window, with a stub renderer
    so no ffmpeg runs — tests drive ``_show_poster`` directly."""
    import tkinter as tk
    from pinball_decryptor.gui import main_window as mw
    pane = mw._VideoPreviewPane(app.window, tk.Frame(app.window._tk_root()),
                                "Original")
    pane.path = "clip.mp4"
    pane.dur = 10.0
    return pane


def _png(color):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 18), color).save(buf, "PNG")
    return buf.getvalue()


def test_video_poster_keeps_looking_when_the_frame_is_black(app):
    """A black still and a broken preview look identical, which is exactly
    what a field report couldn't tell apart.  Sample on past a black frame,
    and when the clip really is black everywhere, say so instead of leaving a
    bare black rectangle."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    asked = []
    pane._render_poster = lambda pos, fallbacks=None: asked.append(pos)

    # Black frame + somewhere else to look -> try the next spot, silently.
    pane._show_poster(_png((0, 0, 0)), pane._render_id, (2.5, 7.5))
    assert asked == [2.5]
    assert pane.canvas.find_withtag("note") == ()

    # Black everywhere we looked -> a note, not an empty pane.
    pane._show_poster(_png((0, 0, 0)), pane._render_id, ())
    assert pane.canvas.find_withtag("note")

    # A frame with picture in it just draws, no note.
    pane._show_poster(_png((10, 90, 200)), pane._render_id, (2.5,))
    assert pane.canvas.find_withtag("frame")
    assert pane.canvas.find_withtag("note") == ()


def test_video_poster_explains_a_frame_it_cannot_show(app):
    """Neither a dead decode nor a Pillow/Tk failure may fall through to a
    silent black canvas — each has to name itself on the pane."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)

    pane._show_poster(None, pane._render_id)          # ffmpeg gave us nothing
    assert pane.canvas.find_withtag("note")

    pane._show_poster(b"not a png at all", pane._render_id)
    notes = pane.canvas.find_withtag("note")
    assert notes
    assert "Couldn't show this frame" in pane.canvas.itemcget(notes[0], "text")


# ---------------------------------------------------------------------------
# a tester round 6 — jumping between the scene, the text and the tabs
# ---------------------------------------------------------------------------

def _stern_text_extract(tmp_path):
    """A synthetic Stern extract with two scenes' worth of display text."""
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.core import text_manifest
    _make_extract(tmp_path)
    text_manifest.save(str(tmp_path), [
        {"path": "/g/scene1/scene.radium", "original": "HELLO",
         "replacement": ""},
        {"path": "/g/scene2/scene.radium", "original": "BALL ONE",
         "replacement": ""}])
    return str(tmp_path)


def _load_text_rows(w, assets):
    from pinball_decryptor.core import text_manifest
    w._set_tab_scanning("text", True)
    w._populate_text_after_scan(text_manifest.load(assets), None,
                                w._text_scan_id, assets)


def test_a_jump_steps_the_tool_windows_out_of_the_way(app, tmp_path):
    """a tester: "when you have the font / scene folder open and jump to it with
    a double click, it will visit the page in the background, it was hard for
    me to find out that it did jump there."

    Both tool windows are ``transient`` children of the main window, which on
    Windows pins them ABOVE it — raising the main window cannot uncover the
    tab.  Lowering them BELOW the root can and does, so that is what a jump
    has to do (and it must be below the root specifically, not just lowered
    among its siblings)."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")

    assets = _stern_text_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(assets)
    w._open_font_studio()
    w._open_scene_browser()
    fs, sb = w._font_studio, w._scene_browser

    lowered = []
    sb.win.lower = lambda below=None: lowered.append(("scenes", below))
    fs.win.lower = lambda below=None: lowered.append(("fonts", below))

    w.reveal_image_slot("images/scene_textures/radimg_TestA_8x8_00000001.png")
    assert sorted(n for n, _b in lowered) == ["fonts", "scenes"]
    assert all(b is w._tk_root() for _n, b in lowered)
    assert w._notebook.select() == str(w._tab_image)

    # Every jump target does it, not just the Images tab.
    lowered.clear()
    _load_text_rows(w, assets)
    w.reveal_text_string("HELLO")
    assert sorted(n for n, _b in lowered) == ["fonts", "scenes"]
    assert w._notebook.select() == str(w._tab_text)
    # ...and lands ON the row: the search filter alone left nothing selected,
    # which reads as "nothing happened".
    assert w._text_tree.selection() == ("0",)
    assert w._text_orig_var.get() == "HELLO"

    lowered.clear()
    w.reveal_video_slot("video/nope.mp4")
    assert sorted(n for n, _b in lowered) == ["fonts", "scenes"]

    fs._close()
    sb._close()
    app.root.update()


def test_text_tab_jumps_into_the_scene(app, tmp_path):
    """a tester: "Could you jump from the text tab into the scene?"  Show in
    Scenes… opens the Scenes window on the scene that draws the selected
    string, with the line itself picked out."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")

    assets = _stern_text_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(assets)
    _load_text_rows(w, assets)

    # Select "BALL ONE" (scene2) — the second manifest row.
    row = next(str(i) for i, r in enumerate(w._text_rows)
               if r["original"] == "BALL ONE")
    w._text_tree.selection_set(row)
    w._text_on_tree_select()
    w._text_show_in_scene()

    sb = w._scene_browser
    assert sb.win.winfo_exists()
    # <<TreeviewSelect>> is delivered a turn later and rebuilds the contents
    # pane, so pump the loop: a row picked out before that is wiped, which is
    # exactly what the real window did.
    app.root.update()
    assert sb._tree.selection() == ("/g/scene2",)
    sel = sb._detail.selection()
    assert sel and sel[0].startswith("txt::")
    assert sb._detail.item(sel[0], "text") == "BALL ONE"

    # A search left in the Scenes window must not swallow the jump: with the
    # filter still on, the scene asked for isn't in the list at all and the
    # fallback would quietly land on a different one.
    sb._search_var.set("scene1")
    assert sb._tree.get_children() == ("/g/scene1",)
    row1 = next(str(i) for i, r in enumerate(w._text_rows)
                if r["original"] == "HELLO")
    w._text_tree.selection_set(row1)
    w._text_on_tree_select()
    sb._search_var.set("scene2")            # now hiding scene1 instead
    w._text_show_in_scene()
    app.root.update()
    assert sb._search_var.get() == ""
    assert sb._tree.selection() == ("/g/scene1",)
    assert sb._detail.item(sb._detail.selection()[0], "text") == "HELLO"

    # Moving to another scene drops the remembered line rather than dragging
    # the selection along.
    sb._tree.selection_set("/g/scene2")
    app.root.update()
    assert sb._focus_want is None

    sb._close()
    app.root.update()


def test_scene_jumps_from_the_font_and_video_lists(app, tmp_path):
    """The other two ways into a scene: right-clicking a scene in the Fonts
    window's usage list, and a video row on the Video tab.  The Fonts one is
    right-click on purpose — that listbox's selection IS the font's scene
    scope, and a jump must not rewrite where an import lands."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")

    assets = _stern_text_extract(tmp_path)
    vdir = tmp_path / "video"
    vdir.mkdir()
    (vdir / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "Intro.mp4\t/g/scene2/scene.assets/3.asset/0.asset\t32\n",
        encoding="utf-8")

    w = app.window
    w.write_assets_var.set(assets)
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("tbl")
    fs._on_select()
    assert fs._scene_paths                      # scenes using the font
    before = list(fs._scenes_list.curselection())
    fs._show_scene(fs._scene_paths[0])
    sb = w._scene_browser
    assert sb._tree.selection() == (
        fs._scene_paths[0].rsplit("/", 1)[0],)
    assert list(fs._scenes_list.curselection()) == before   # scope untouched

    # Video row -> the scene that plays the clip.
    w._open_scene_browser(preselect_video="video/Intro.mp4")
    assert sb._tree.selection() == ("/g/scene2",)

    fs._close()
    sb._close()
    app.root.update()
