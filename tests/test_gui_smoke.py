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
    # The per-project mirror is module state that would otherwise leak from
    # one test into the next (and keep writing into the previous test's
    # tmp_path).  Start every test with no project attached.
    monkeypatch.setattr(session_log, "_project_dir", None)
    # Don't fire the real prerequisite probes: every mfr selection would
    # spawn a background thread + a storm of subprocess probes that outlive
    # the (sub-second) test and churn against the next Tk create.  Tests
    # that care about indicator state drive set_prereq_result() directly.
    monkeypatch.setattr(app_mod.App, "_kick_off_prereq_check",
                        lambda self, mfr: None)
    # Don't let the startup update check reach GitHub.  App() arms
    # after(1500, _check_for_update): any test that keeps the Tk event
    # loop alive past 1.5s fires a REAL anonymous api.github.com request
    # (GitHub allows those 60/hour per IP, machine-wide).  Measured
    # 2026-09-01 with a counting stub over a full `-n auto` run: ZERO
    # current tests cross the line — teardown's after-cancel sweep wins —
    # but a 2.5s-mainloop control test fired reliably, so the suite is
    # one slow test (or one loaded machine) away from spending the
    # developer's API quota.  Stubbing the app module's reference (the
    # name App actually calls) keeps the threading/log plumbing live but
    # offline; a test exercising the update flow overrides this stub.
    monkeypatch.setattr(app_mod, "check_for_update",
                        lambda *a, **kw: None)

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
    # read file .../init.tcl" (antivirus/indexer briefly in the way of the
    # Tcl runtime scripts; GitHub's windows-latest runner hits it too).
    # RETRY in-process first: this file's old warning that a failed create
    # "leaves a zombie Tcl interpreter that poisons every Tk instance created
    # after it" was measured false on 2026-09-01 - a worker whose App() lost
    # the race passed every later Tk test in the same process, so the failure
    # is per-attempt.  Retry with a short backoff (same shape as conftest's
    # make_tk_root) before giving up.
    #
    # SKIP rather than error when it persists: the Tcl runtime failing to
    # load is a property of the machine, not of the code under test — it
    # lands on a different, always-unrelated test each time, and it failed
    # two consecutive CI runs of one release commit whose local runs passed.
    # A release must not hinge on whether an indexer happened to hold
    # init.tcl for a moment.  ONLY this signature skips (and only it is
    # retried); any other TclError still fails the test, so a real GUI
    # regression can't hide behind it.
    import time as _time_mod
    try:
        for _attempt in range(4):
            try:
                a = App()
                break
            except _tk_mod.TclError as exc:
                if not _TCL_RUNTIME_UNAVAILABLE.search(str(exc)):
                    raise
                if _attempt == 3:
                    raise
                _time_mod.sleep(0.1 * (_attempt + 1))
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


def test_checkout_badge_in_title_bar(app):
    """A window running an item worktree (the /next chooser flow) carries
    the checkout badge in the title bar, alongside the usual caption —
    two open copies must be tellable apart.  The fixture app runs under
    pytest so its badge is None; set it as the picker flow would."""
    app._checkout_badge = "item/27 — Any Spike 2 title should load"
    app._on_detected_game_change("Led Zeppelin v1.22 LE")
    assert "[item/27 — Any Spike 2 title should load]" in app.root.title()
    assert "Led Zeppelin v1.22 LE" in app.root.title()
    app._checkout_badge = None
    app._refresh_title()
    assert "item/27" not in app.root.title()


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


def test_audio_advanced_offers_replacement_loudness(app, manufacturers_by_key):
    """PAD-90: the loudness match is scale-invariant, so a user who remixes a
    track louder gets a byte-identical card.  The dialog has to expose a way
    to sit above (or below) the stock level, and OK has to mirror it into the
    encoder env vars the spawned encode workers read."""
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
    for var in ("PAD_STERN_MATCH_LOUDNESS", "PAD_STERN_MATCH_GAIN_DB"):
        os.environ.pop(var, None)

    win._open_audio_advanced()
    app.root.update()
    dlg = [c for c in win.root.winfo_children()
           if isinstance(c, _tk_mod.Toplevel)][-1]
    kids = _descendants(dlg)
    texts = [str(w.cget("text")) for w in kids if "text" in w.keys()]
    assert any("Replacement loudness" in t for t in texts)
    # the explanation has to say the user's own mix level is discarded
    assert any("level you mixed your own file at" in t for t in texts)

    combo = next(w for w in kids if "values" in w.keys()
                 and any("Match the sound being replaced" in str(v)
                         for v in w.cget("values")))
    spin = next(w for w in kids
                if "from" in w.keys() and float(w.cget("from")) == -12.0)
    spin.set("6")
    ok = next(w for w in kids if "text" in w.keys()
              and str(w.cget("text")) == "OK")
    ok.invoke()
    app.root.update()

    cfg = app._settings["audio_advanced"]
    assert cfg["loudness"] == "match" and cfg["loudness_db"] == 6
    # "match" is the engine baseline, so only the offset sets a var
    assert "PAD_STERN_MATCH_LOUDNESS" not in os.environ
    assert os.environ["PAD_STERN_MATCH_GAIN_DB"] == "6"

    # Full-scale mode sets the kill switch; defaults clear both again.
    app._on_audio_advanced_change({"loudness": "full", "loudness_db": -30})
    assert os.environ["PAD_STERN_MATCH_LOUDNESS"] == "0"
    assert os.environ["PAD_STERN_MATCH_GAIN_DB"] == "-12"   # clamped
    app._on_audio_advanced_change({})
    for var in ("PAD_STERN_MATCH_LOUDNESS", "PAD_STERN_MATCH_GAIN_DB"):
        assert var not in os.environ


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
    # Field 3 reports its version too (PAD-124: it was the one picker with no
    # chip, so choosing a folder there looked like nothing happened — and it
    # is the field where a wrong version does the most damage, since the whole
    # compare is against it).
    oldstock = tmp_path / "oldstock158"
    oldstock.mkdir()
    extract_source.write_extract_source(str(oldstock), old_img)
    w.transfer_oldstock_var.set(str(oldstock))
    app.root.update()
    assert "1.58.1 (1987)" in w.transfer_oldstock_ver_var.get()
    w.transfer_oldstock_var.set("")
    app.root.update()
    assert w.transfer_oldstock_ver_var.get() == ""
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
    slots_by_rel, assignments, keep_size = pend
    assert assignments == {"images/backglass.png": str(repl)}
    assert "images/backglass.png" in slots_by_rel
    assert keep_size == frozenset()
    # A kept-size flag recorded for the pick reaches the build (PAD-154).
    staged_changes.save(str(assets), {
        "image": {"images/backglass.png": str(repl)},
        "image_keep_size": ["images/backglass.png", "images/gone.png"]})
    assert app._sidecar_pending(str(assets), "image")[2] == frozenset(
        {"images/backglass.png"})


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


def test_audio_preview_keeps_a_longer_replacement_whole_when_the_bank_grows(
        app, manufacturers_by_key):
    """With the Stern longer-replacements option on, a replacement longer
    than its slot is kept whole on Write, so the Replacement pane must not
    hatch its tail as trimmed: no cap, the original's end marked instead,
    and the clock says the bank grows.  Off, or on Spike 1 (no grow path),
    it trims exactly as before."""
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    win = app.window

    class _Slot:
        duration = 0.32

    rel = "audio/idx0044.wav"
    win._audio_slots_by_rel = {rel: _Slot()}
    win._audio_current_rel = rel
    win._audio_assignments = {rel: "C:/rep.wav"}
    win._audio_keep_full_flags = {}
    win.audio_trim_var.set(True)

    win._audio_advanced = dict(win._audio_advanced, audio_grow=False)
    assert win._audio_compute_preview_limit(rel, 45.6) == 0.32
    assert win._audio_preview_grow_from(rel, 45.6) is None

    win._audio_advanced = dict(win._audio_advanced, audio_grow=True)
    assert win._audio_compute_preview_limit(rel, 45.6) is None
    assert win._audio_preview_grow_from(rel, 45.6) == 0.32
    # a replacement that fits its slot has nothing to mark
    assert win._audio_preview_grow_from(rel, 0.30) is None

    # the pane's clock says so where "trimmed from" used to be
    pane = win._audio_pane_rep
    pane.path, pane.dur, pane.limit, pane.grow_from, pane.pos = (
        "C:/rep.wav", 45.6, None, 0.32, 0.0)
    pane._update_time()
    assert "the sound bank grows" in pane.time_var.get()
    assert "trimmed" not in pane.time_var.get()
    pane.limit = 0.32
    pane._update_time()
    assert "trimmed from" in pane.time_var.get()

    # Spike 1 has no grow path, so the option does not reach its preview
    mfr = manufacturers_by_key["stern"]
    if hasattr(mfr, "set_era"):
        mfr.set_era("spike1")
        try:
            assert win._audio_compute_preview_limit(rel, 45.6) == 0.32
        finally:
            mfr.set_era("")


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

    # Only a press that landed on a column separator counts as a resize
    # (batch 37) — record one, the way _note_tree_press does.
    w._tree_drag_widths["audio"] = {
        c: int(w._audio_tree.column(c, "width")) for c in cols}
    w._audio_tree.column("fmt", width=137)
    w._save_tree_columns(w._audio_tree, "audio", cols)
    assert captured and captured[-1]["audio"]["fmt"] == 137

    # No real change → no second callback.
    n = len(captured)
    w._tree_drag_widths["audio"] = {
        c: int(w._audio_tree.column(c, "width")) for c in cols}
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
        assert set(win._era_badge_widgets) == {"spike2", "spike1",
                                               "whitestar"}
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


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_gated_by_capability(app, manufacturers_by_key):
    """The Modes tab (item 127) shows for Stern and hides for a plugin without
    the capability - a mode runtime is Spike 2's, not every manufacturer's."""
    w = app.window

    def _state(label):
        for tid in w._notebook.tabs():
            if w._tab_key(tid) == label:
                return str(w._notebook.tab(tid, "state"))
        return None

    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert _state("Modes") == "normal"
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update(); app.root.update()
    assert _state("Modes") == "hidden"


def _tab_state(w, label):
    for tid in w._notebook.tabs():
        if w._tab_key(tid) == label:
            return str(w._notebook.tab(tid, "state"))
    return None


def test_the_mode_maker_is_hidden_until_a_preview_code_unlocks_it(app, manufacturers_by_key,
                                                                  monkeypatch):
    """The mode maker ships dark (core/preview.py): no Modes tab for Stern without a code.
    Settings > Preview features takes one; a bad one says why and changes nothing, a good
    one shows the tab at once and is kept in settings.json, and Remove hides it again."""
    from pinball_decryptor.core import preview
    from tests.test_preview_switch import OTHER_SECRET, TEST_PUB, make_code
    monkeypatch.setattr(preview, "PUBLIC_KEYS", (TEST_PUB,))
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    assert _tab_state(w, "Modes") == "hidden"
    menu = w._build_settings_menu()
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
              if menu.type(i) not in ("separator", "tearoff")]
    assert "Preview features…" in labels
    dlg = w._open_preview_dialog()
    try:
        assert dlg.listbox.get(0) == "No preview features are switched on."
        for bad, needle in (("hello", "not a preview code"),
                            (make_code(secret=OTHER_SECRET), "not issued for this app"),
                            (make_code(days=3, issued=preview.utc_today()
                                       - dt_days(20)), "ended on")):
            assert not dlg.unlock(bad)
            assert needle in dlg.message.get()
            assert _tab_state(w, "Modes") == "hidden" and not preview.enabled("modes")
            assert preview.SETTINGS_KEY not in app._settings
        code = make_code(name="Test Person", days=30, issued=preview.utc_today())
        dlg.entry.insert("1.0", code[:40] + "\n" + code[40:].lower())    # as pasted
        assert dlg.unlock()
        app.root.update()
        assert preview.enabled("modes") and _tab_state(w, "Modes") == "normal"
        assert app._settings[preview.SETTINGS_KEY] == [code]
        until = (preview.utc_today() + dt_days(30)).isoformat()
        assert dlg.listbox.get(0) == "Mode maker: on for Test Person, until %s" % until
        assert dlg.message.get().startswith("Unlocked.")
        assert dlg.remove_selected(0)
        app.root.update()
        assert not preview.enabled("modes") and _tab_state(w, "Modes") == "hidden"
        assert preview.SETTINGS_KEY not in app._settings
        # another manufacturer never shows it, code or not
        dlg.unlock(code)
        app._on_manufacturer_change(manufacturers_by_key["spooky"])
        app.root.update()
        assert _tab_state(w, "Modes") == "hidden"
    finally:
        dlg.close()


def dt_days(n):
    import datetime
    return datetime.timedelta(days=n)


def test_an_expired_code_turns_the_mode_maker_off_at_the_next_start(app, manufacturers_by_key,
                                                                    monkeypatch):
    """Verification happens at start-up (App._load_preview_codes, cached for the run): a
    stored code that has ended switches nothing on, and the log says so."""
    from pinball_decryptor.core import preview
    from tests.test_preview_switch import TEST_PUB, make_code
    monkeypatch.setattr(preview, "PUBLIC_KEYS", (TEST_PUB,))
    ended = make_code(days=5, issued=preview.utc_today() - dt_days(10))
    app._settings[preview.SETTINGS_KEY] = [ended]
    said = []
    monkeypatch.setattr(app.window, "append_log", lambda m, lvl="info", *a, **k: said.append(m))
    app._load_preview_codes()
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    app._log_preview_startup()
    assert not preview.enabled("modes") and _tab_state(app.window, "Modes") == "hidden"
    assert any("Mode maker: expired on" in m for m in said), said
    assert any("1 code(s) checked in" in m for m in said), said
    # a good one at the next start
    app._settings[preview.SETTINGS_KEY] = [make_code(issued=preview.utc_today())]
    app._load_preview_codes()
    app.window.apply_preview_features()
    assert preview.enabled("modes") and _tab_state(app.window, "Modes") == "normal"


def test_the_write_scan_lists_no_mode_rows_with_the_switch_off(app, manufacturers_by_key,
                                                               tmp_path, monkeypatch):
    """With the switch off a tester's project lists no "Pending (Modes)" or game's-own-modes
    rows: the Write leaves them out (and its log says so), so the list promises nothing."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import stock_modes as SM
    w = app.window
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    monkeypatch.setattr(SM, "staged_edits", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("read with the switch off")))
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    sid = w._write_preview_scan_id
    assert w._add_pending_mode_rows(project, sid) == 0
    assert w._add_pending_stock_mode_rows(project, sid) == 0
    assert not [r for r in w._write_preview_rows if "Modes" in r[2] or "modes" in r[2]]


# ---- THE APP WITHOUT A CODE NAMES NOTHING OF THE MODE MAKER ------------------------------
from tkinter import ttk as _ttk_mod                                     # noqa: E402

#: The mode maker's own vocabulary, any of which gives it away (case-insensitive
#: substrings).  "mode" alone is an ordinary word in this app - service mode, attract
#: mode, a game's own battle modes on tabs that predate the family - so the list is the
#: family's words, not the word.
_REVEALING = ("mode maker", "modes tab", "try it", "code mode", "mode file", "mode.json",
              "film cutter", "from a film", "film cut", "showcase", "game's own modes",
              "mode of your own", "modes of your own", "mode of our own", "modes of our own",
              "own modes", "your own mode", "mode sdk", "mode runtime", "modes folder",
              "stock mode", "kaiju", "make a mode", "new mode", "a game mode")
#: ...matched as whole words ("the country it is set to" is not "try it") ...
_REVEALING_RE = _re_mod.compile(
    r"\b(?:%s)\b" % "|".join(_re_mod.escape(t) for t in _REVEALING), _re_mod.I)
#: ...and the tab's and the feature's name, capitalised as a name.
_REVEALING_NAME = _re_mod.compile(r"\bModes\b")


@pytest.fixture
def tip_log(monkeypatch):
    """Every hover tooltip made while the test runs (widgets._Tooltip), so the walk below
    reads tooltips too: they are Python objects, not widget options. Requested BEFORE
    ``app`` so the window's own tooltips are caught as it builds."""
    from pinball_decryptor.gui import widgets
    tips = []
    real = widgets._Tooltip.__init__

    def init(tip, widget, text, *a, **k):
        real(tip, widget, text, *a, **k)
        tips.append(tip)
    monkeypatch.setattr(widgets._Tooltip, "__init__", init)
    return tips


def _hidden_pages(root):
    """The path names of every HIDDEN notebook page under *root*: nobody can open one,
    so what is on it is not something a person can read."""
    out = set()
    stack = [root]
    while stack:
        w = stack.pop()
        if isinstance(w, _ttk_mod.Notebook):
            for tid in w.tabs():
                try:
                    if str(w.tab(tid, "state")) == "hidden":
                        out.add(str(tid))
                except _tk_mod.TclError:
                    pass
        stack.extend(w.winfo_children())
    return out


def _under(path, pages):
    return any(path == p or path.startswith(p + ".") for p in pages)


def _readable_texts(root, tips=(), skip=()):
    """``[(where, text)]``: every text a person can read in *root*'s widget tree - the
    text of labels, buttons, frames and menubuttons (and their text variables), notebook
    tab captions, menu entries, listbox and combobox items, entries, Text contents,
    treeview headings and rows, canvas text, and the hover tooltips in *tips*. Pages in
    *skip* (hidden notebook tabs) are left out."""
    out = []

    def add(w, text):
        if isinstance(text, (tuple, list)):
            for t in text:
                add(w, t)
        elif text not in (None, ""):
            out.append(("%s %s" % (w.winfo_class(), w), str(text)))

    stack = [root]
    while stack:
        w = stack.pop()
        if _under(str(w), skip):
            continue
        for opt in ("text", "label"):
            try:
                add(w, w.cget(opt))
            except (_tk_mod.TclError, ValueError, AttributeError):
                pass
        try:
            var = str(w.cget("textvariable"))
            if var:
                add(w, w.getvar(var))
        except (_tk_mod.TclError, ValueError, AttributeError):
            pass
        try:
            if isinstance(w, _ttk_mod.Notebook):
                for tid in w.tabs():
                    if str(tid) not in skip:
                        add(w, w.tab(tid, "text"))
            elif isinstance(w, _tk_mod.Menu):
                end = w.index("end")
                for i in range(0 if end is None else end + 1):
                    if w.type(i) not in ("separator", "tearoff"):
                        add(w, w.entrycget(i, "label"))
            elif isinstance(w, _tk_mod.Listbox):
                add(w, w.get(0, "end"))
            elif isinstance(w, _ttk_mod.Combobox):
                add(w, w.cget("values"))
                add(w, w.get())
            elif isinstance(w, (_tk_mod.Entry, _ttk_mod.Entry)):
                add(w, w.get())
            elif isinstance(w, _tk_mod.Text):
                add(w, w.get("1.0", "end"))
            elif isinstance(w, _ttk_mod.Treeview):
                for col in ("#0",) + tuple(w.cget("columns") or ()):
                    add(w, w.heading(col, "text"))
                rows = list(w.get_children(""))
                while rows:
                    iid = rows.pop()
                    add(w, w.item(iid, "text"))
                    add(w, w.item(iid, "values"))
                    rows.extend(w.get_children(iid))
            elif isinstance(w, _tk_mod.Canvas):
                for item in w.find_all():
                    if w.type(item) == "text":
                        add(w, w.itemcget(item, "text"))
        except _tk_mod.TclError:
            pass
        stack.extend(w.winfo_children())
    for tip in tips:
        try:
            wpath = str(tip._widget)
        except Exception:
            continue
        if _under(wpath, skip):
            continue
        text = tip.text() if callable(tip.text) else tip.text
        if text:
            out.append(("tooltip %s" % wpath, str(text)))
    return out


def _revealing(texts):
    return [(where, text) for where, text in texts
            if _REVEALING_RE.search(text) or _REVEALING_NAME.search(text)]


def _help_texts(app, tabs):
    """``[(where, text)]``: what the "?" window shows for each tab in *tabs*."""
    from pinball_decryptor.gui.help_dialog import TabHelpWindow
    win = TabHelpWindow(app.root, lambda: app.window._current_theme)
    out = []
    try:
        for tab in tabs:
            win.show(tab)
            out.append(("help %s" % tab, win._dlg.title()))
            out.append(("help %s" % tab, win._text.get("1.0", "end")))
    finally:
        win.close()
    return out


def _everything_readable(app, tips):
    """Every readable text of the window as it stands, with the gear's and the Project
    menus built (they are made when clicked) and the "?" text of every visible tab."""
    w = app.window
    menus = [w._build_settings_menu(), w._build_project_menu()]
    try:
        app.root.update_idletasks()
        skip = _hidden_pages(app.root)
        texts = _readable_texts(app.root, tips, skip)
        visible = [w._tab_key(tid) for tid in w._notebook.tabs() if str(tid) not in skip]
        texts += _help_texts(app, visible)
        return texts
    finally:
        for m in menus:
            try:
                m.destroy()
            except _tk_mod.TclError:
                pass


def test_the_app_without_a_preview_code_names_nothing_of_the_mode_maker(
        tip_log, app, manufacturers_by_key, monkeypatch):
    """THE CLEAN SURFACE (David, 2026-09-18): a copy of the app with no preview code shows
    nothing of the mode maker. Every text a person can read - every widget, tab caption,
    menu entry, list, tooltip, the log, and the "?" text of every tab - is walked on the
    picker and for EVERY manufacturer, and none of the family's words is in any of it.
    The Preview features dialog, before a code, names no feature at all. The control at
    the end switches the mode maker on and finds its words with the same walk, so the
    walk can see them."""
    from pinball_decryptor.core import preview
    assert not preview.enabled("modes") and tip_log
    w = app.window
    hits = _revealing(_everything_readable(app, tip_log))
    assert not hits, hits[:10]
    for key in sorted(manufacturers_by_key):
        app._on_manufacturer_change(manufacturers_by_key[key])
        app.root.update()
        hits = _revealing(_everything_readable(app, tip_log))
        assert not hits, (key, hits[:10])
    # the "?" text of the hidden tab itself (nobody can reach it: its caption is the
    # window's title), and of Write, say nothing of it either
    bodies = [x for x in _help_texts(app, ["Modes", "Write"]) if not x[1].startswith("Tips")]
    assert len(bodies) == 2 and not _revealing(bodies), _revealing(bodies)
    # the Settings gear keeps "Preview features..." exactly as it is ...
    menu = w._build_settings_menu()
    try:
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                  if menu.type(i) not in ("separator", "tearoff")]
    finally:
        menu.destroy()
    assert "Preview features…" in labels
    # ... and its window, before a code, names no feature
    dlg = w._open_preview_dialog()
    try:
        app.root.update_idletasks()
        said = _readable_texts(dlg.win)
        assert dlg.listbox.get(0, "end") == ("No preview features are switched on.",)
        for label in preview.FEATURES.values():
            assert not [t for _w, t in said if label.lower() in t.lower()], label
        assert not _revealing(said), _revealing(said)
    finally:
        dlg.close()

    # THE CONTROL: the switch on, the same walk finds the tab and its words
    real = preview.enabled
    monkeypatch.setattr(preview, "enabled", lambda f: f == "modes" or real(f))
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    w.apply_preview_features()
    app.root.update()
    found = {t.strip() for _w, t in _revealing(_everything_readable(app, tip_log))}
    assert "Modes" in found and any("Try it" in t for t in found), sorted(found)[:10]
    assert _revealing(_help_texts(app, ["Modes", "Write"]))


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_is_built_and_sits_between_defaults_and_write(app):
    """The WINDOW builds the Modes tab, and it sits after Defaults, before Write.

    Item 127 shipped this tab EMPTY: ``_build_modes_tab`` existed and nothing
    called it, and every earlier test constructed ``ModesPanel`` by hand, so
    none of them could see it. This one looks at the real window's frame.
    Placement is David's (2026-09-16): a mode is one more change a card build
    applies, so it is authored before Write like the tabs to its left.
    """
    w = app.window
    keys = [w._tab_key(tid) for tid in w._notebook.tabs()]
    assert keys.index("Default Settings") + 1 == keys.index("Modes")
    assert keys.index("Modes") + 1 == keys.index("Write")
    assert w._tab_modes.winfo_children(), "the Modes tab frame is empty"
    assert getattr(w, "_modes_panel", None) is not None


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_makes_and_edits_a_mode_in_the_project(app, tmp_path):
    """New makes a mode IN THE PROJECT, and an edit on the form lands in its mode.json.

    David, 2026-09-16: a mode belongs to the card project and reaches a card through
    Write. The starter is buildable as it stands (the runtime refuses a mode without a
    clock or a trigger count), shots are picked BY NAME, and the list follows a rename.
    """
    import json
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode()
    assert slug == "new_mode" and panel._list.get(0) == "NEW MODE"
    assert "Ready to build" in panel._status.cget("text")
    assert panel._preview_img is not None                      # the screen preview drew

    panel.v["name"].set("KAIJU RUSH")
    panel.v["start_shot"].set("Maser target")
    panel.v["award"].set("2,000,000")
    for name, var in panel._shot_vars.items():
        var.set(name in ("Left ramp", "Powerline center"))
    panel.v["clip"].set("title")
    panel.save_now()
    data = json.load(open(project / "modes" / slug / "mode.json", encoding="utf-8"))
    assert data["name"] == "KAIJU RUSH" and data["award"] == 2000000
    assert data["scoring_shots"] == ["Left ramp", "Powerline center"] and data["clip"] == "title"
    assert panel._list.get(0) == "KAIJU RUSH"
    spec = MP.load(str(project / "modes" / slug / "mode.json"))
    assert "0x20100000" in MP.runtime_cfg(spec, slug)          # the named shots, as a mask

    panel.v["seconds"].set("0")
    panel.save_now()
    assert "at least a second" in panel._status.cget("text")


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_examples_add_kaiju_rush_and_an_empty_editor_keeps_its_labels(app, tmp_path):
    """Two things David saw on 2026-09-16 with a project that had no modes: the form was
    "barely legible" in the dark theme, and KAIJU RUSH was nowhere to be found.

    The first was every widget under the editor being DISABLED with no mode open - a
    disabled ttk.Label draws in the disabled grey against the dark panel. Now only the
    widgets a person types in or clicks are greyed; labels keep their colour. The second
    is the Examples menu: KAIJU RUSH, as it ran on the machine, one click away.
    """
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert "Examples" in panel._status.cget("text")

    labels, fields = [], []

    def walk(widget):
        for child in widget.winfo_children():
            (labels if isinstance(child, ttk.Label) else fields if isinstance(child, ttk.Entry) else []).append(child)
            walk(child)
    walk(panel._editor)
    assert labels and fields
    assert not any(lb.instate(["disabled"]) for lb in labels), "a label was greyed out"
    assert all(f.instate(["disabled"]) for f in fields), "a field was left live with no mode open"
    assert str(panel._ex_btn.cget("state")) == "normal"

    panel._on_example("KAIJU RUSH")
    app.root.update()
    assert panel._list.get(0) == "KAIJU RUSH"
    assert not any(f.instate(["disabled"]) for f in fields)
    spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
    assert spec.start_shot == "Maser target" and spec.start_count == 3 and spec.seconds == 30
    assert "0x08000000 3" in MP.runtime_cfg(spec, "kaiju_rush")   # the machine-proven trigger


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_follows_the_project_and_never_leaks_an_edit(app, tmp_path):
    """Switching project shows THAT project's modes, and an edit in flight is saved to
    the project it was made in - never into the one switched to."""
    w = app.window
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    w.write_assets_var.set(str(a))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode()
    panel.v["name"].set("ONLY IN A")                 # debounced, not yet saved
    w.write_assets_var.set(str(b))
    app.root.update()
    assert panel._list.size() == 0 and not (b / "modes").exists()
    assert '"name": "ONLY IN A"' in (a / "modes" / slug / "mode.json").read_text(encoding="utf-8")
    w.write_assets_var.set(str(a))
    app.root.update()
    assert panel._list.get(0) == "ONLY IN A"
    panel.delete_mode(slug)
    assert panel._list.size() == 0 and not (a / "modes" / slug).exists()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_without_a_project_says_where_modes_go(app, tmp_path):
    w = app.window
    w.write_assets_var.set("")
    app.root.update()
    panel = w._modes_panel
    assert panel.new_mode() is None
    assert "Extract tab" in panel._project_label.cget("text")


# ---- item 127: Try it, on the Mode SDK ---------------------------------------------------
def _no_wsl(monkeypatch):
    """Any process start at all fails the test: these reach no WSL and launch nothing."""
    import subprocess
    from pinball_decryptor.gui import emulate_tab, modes_tab

    def refuse(*a, **kw):
        raise AssertionError("a GUI test started a process: %r" % (a[:1],))
    for mod in (subprocess, modes_tab.subprocess, emulate_tab.subprocess):
        monkeypatch.setattr(mod, "run", refuse)
        monkeypatch.setattr(mod, "Popen", refuse)


def _fake_rig(panel, ran=None):
    panel._rig_cmd_fn = lambda script, *args: ["RIG", script] + [str(a) for a in args]
    if ran is not None:
        panel._run_fn = lambda cmd, **kw: ran.append(cmd) or type(
            "R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()


def _wait_for(pred, root, secs=5):
    import time
    deadline = time.time() + secs
    while not pred() and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    return pred()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_tryit_section_is_built_and_its_env_is_pure(app, tmp_path, monkeypatch):
    _no_wsl(monkeypatch)
    panel = app.window._modes_panel
    for btn in ("_try_btn", "_start_btn", "_end_btn", "_code_btn", "_sdk_btn"):
        assert getattr(panel, btn).winfo_exists(), btn
    panel._tryit_base = str(tmp_path / "try")
    env = panel.tryit_env()
    assert env[0].startswith("PAD_OVERRIDE_DIR=") and env[0].endswith("/try/set")
    assert "\\" not in env[0]
    assert env[1] == "PAD_MODE_SO=/lib/pad_mode.so"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_tryit_commands_name_the_right_slot(app, tmp_path, monkeypatch):
    _no_wsl(monkeypatch)
    panel = app.window._modes_panel
    _fake_rig(panel)
    assert panel.trigger_cmd(0) == ["RIG", "modes/tryit.sh", "start", "0"]
    assert panel.trigger_cmd(3) == ["RIG", "modes/tryit.sh", "start", "3"]
    assert panel.stop_cmd() == ["RIG", "modes/tryit.sh", "stop"]
    stage = str(tmp_path / "rig")
    cmd = panel.install_cmd(stage)
    assert cmd[:3] == ["RIG", "modes/tryit.sh", "install"] and "\\" not in cmd[3]
    push = panel.push_cmd(os.path.join(stage, "push", "mode2.cfg"), 2)
    assert push[:3] == ["RIG", "modes/tryit.sh", "push"] and push[-1] == "2"
    build = panel.compile_cmd(os.path.join(stage, "pad_mode.so"), [str(tmp_path / "blitz.c")])
    assert build[1] == "modes/sdk/build_mode.sh" and build[2] == "-o"
    assert build[-1].endswith("modes/sdk/mode_file.c") and build[-2].endswith("blitz.c")
    # ...and the rig script those commands run is there, with every verb
    rig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tools", "spike2_emu", "modes", "tryit.sh")
    body = open(rig, encoding="utf-8").read()
    for verb in ("install)", "start)", "stop)", "push)"):
        assert verb in body
    assert '"$LIB/pad_mode.so"' in body and '"$DUMP/game.port"' in body


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_hands_the_emulate_tab_a_preparation(app, tmp_path, monkeypatch):
    """Try it launches NOTHING itself: it hands a preparation to the Emulate tab's own
    launch. The preparation builds the set, installs through the rig script, and returns
    the env; while the run is up an autosave pushes the regenerated mode file."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    running = [False]
    panel._running_fn = lambda: running[0]
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    from tests.test_stern_mode_tryit import _writes_builder
    _writes_builder(monkeypatch, [])
    assert panel._on_try() is True
    assert handed == [panel.tryit_prepare] and not ran     # nothing launched, nothing run

    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    env = handed[0](str(card))                              # what the start worker does
    # Write's set for QUIET (no screen, no clip) holds the game program with the validator
    # bypass, so the run binds the set and preloads the object (item 149)
    assert env == panel.tryit_env() and env[1] == "PAD_MODE_SO=/lib/pad_mode.so"
    assert len(ran) == 1 and ran[0][:3] == ["RIG", "modes/tryit.sh", "install"]
    stage = MT.stage_dir(panel._tryit_base)
    assert sorted(os.listdir(stage)) == ["game.port", "mode.cfg", "pad_mode.so"]
    assert handed[0](str(tmp_path / "no_such.raw")) is None  # a missing card refuses

    # Start mode now / End mode, per slot, only while the emulator is up
    assert panel._on_start_now() is None
    running[0] = True
    assert panel._on_start_now() == ["RIG", "modes/tryit.sh", "start", "0"]
    assert panel._on_end_now() == ["RIG", "modes/tryit.sh", "stop"]
    assert _wait_for(lambda: len(ran) >= 3, app.root)

    # an edit while the game runs: the regenerated file is pushed into slot 0
    panel.v["seconds"].set("9")
    panel.save_now()
    assert _wait_for(lambda: any(c[2] == "push" for c in ran), app.root)
    push = [c for c in ran if c[2] == "push"][-1]
    assert push[-1] == "0"
    pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
    assert "seconds        9" in pushed
    # a screen change cannot reload live, and says so
    n = len(ran)
    panel.v["screen"].set(True)
    panel.save_now()
    assert _wait_for(lambda: len(ran) > n, app.root)
    assert _wait_for(lambda: "next Try it" in panel._tryit_status.cget("text"), app.root)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_new_code_mode_copies_the_template_and_opens_the_sdk(app, tmp_path, monkeypatch):
    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    opened = []
    panel._opener = opened.append
    panel._ask_fn = lambda: "Blitz Rush"
    path = panel._on_new_code_mode()
    assert path == str(project / "modes" / "blitz_rush" / "blitz_rush.c")
    text = open(path, encoding="utf-8").read()
    assert '#define MODE_NAME        "Blitz Rush"' in text
    assert '"blitz_rush.start"' in text and "PadMode_blitz_rush_Screen" in text
    assert "target_rush" not in text and "PM_REGISTER(blitz_rush_mode);" in text
    assert opened == [path]
    panel.open_sdk_doc()
    assert opened[-1].endswith("MODE_SDK.md") and os.path.isfile(opened[-1])


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_compiles_a_code_mode_first_and_names_it(app, tmp_path, monkeypatch):
    """A project with a CODE mode (New code mode): Try it compiles it with build_mode.sh,
    beside the mode-file interpreter, BEFORE the install, and the ready line names it -
    it has no mode.json, so it is not in the list and Start mode now cannot reach it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    MT.new_code_mode(str(project), "Blitz")
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    from tests.test_stern_mode_tryit import _writes_builder
    _writes_builder(monkeypatch, [])
    assert panel._on_try() is True and not ran
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    assert handed[0](str(card)) == panel.tryit_env()      # Write's set: the game program
    assert [c[1] for c in ran] == ["modes/sdk/build_mode.sh", "modes/tryit.sh"]
    assert ran[0][-2].endswith("blitz/blitz.c") and ran[0][-1].endswith("mode_file.c")
    assert ran[0][3].endswith("/pad_mode.so") and ran[1][2] == "install"
    status = panel._tryit_status.cget("text")
    assert "1 mode(s) ready (QUIET)" in status and "Code mode(s) built in: blitz" in status
    # a card Written from the project carries the code modes too (their own assets with them)
    assert "A card Written from this project carries them the same way" in status
    # End mode ends both: the form modes' mode.stop and the code mode's own blitz.stop
    panel._running_fn = lambda: True
    assert panel._on_end_now() == ["RIG", "modes/tryit.sh", "stop", "blitz"]
    assert _wait_for(lambda: "end the running mode, and the code mode(s) blitz."
                     in panel._tryit_status.cget("text"), app.root)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_says_it_does_not_run_on_a_mac_yet(app, tmp_path, monkeypatch):
    """On macOS the rig runs in padbox.sh's container, which neither mounts the Try it
    folder nor forwards PAD_MODE_SO: Try it there would start a run with no mode in it, or
    fail with a rig error. It says so in a sentence and hands nothing to the Emulate tab."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    monkeypatch.setattr(panel, "_platform", "darwin")
    assert panel._on_try() is False and handed == [] and ran == []
    assert "runs on Windows and Linux for now" in panel._tryit_status.cget("text")
    monkeypatch.setattr(panel, "_platform", "linux")
    assert panel._on_try() is True and handed == [panel.tryit_prepare]
    panel._tryit_working = False              # ends the status watch the hand-off started
    app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_in_the_window_reaches_the_emulate_tabs_own_launch(
        app, tmp_path, monkeypatch, manufacturers_by_key):
    """The WINDOW's wiring of Try it (item 127): the button reaches the Emulate panel's own
    launch_with with the tab's preparation, the Emulate tab comes forward, and "is the
    emulator up?" is that panel's own poll answer. The emulator runs drove the two panels
    by hand, and the tab once shipped unbuilt because every test did the same - so this
    one presses the button in the real window and patches only the launch."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    _no_wsl(monkeypatch)
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update(); app.root.update()
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel, emul = w._modes_panel, w._emulate_panel
    handed = []
    monkeypatch.setattr(emul, "launch_with", lambda prepare: handed.append(prepare) or True)
    try:
        panel._try_btn.invoke()
        app.root.update()
        assert handed == [panel.tryit_prepare]
        assert w._tab_key(w._notebook.select()) == "Emulate"
        monkeypatch.setattr(emul, "_last_up", False)
        assert panel._running_fn() is False
        emul._last_up = True
        assert panel._running_fn() is True
    finally:
        panel._tryit_working = False          # ends the status watch the hand-off started
        app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_a_save_that_changes_nothing_pushes_nothing(app, tmp_path, monkeypatch):
    """Item 127 run 2 (2026-09-17): picking another mode in the list saves the open one
    first, and every such click pushed an IDENTICAL mode file into the running game and
    said "updated in the running game". Only a file the game does not have is pushed."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    for name in ("ALPHA", "BRAVO"):
        MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran = []
    _fake_rig(panel, ran)
    panel._running_fn = lambda: True
    # what a Try it install leaves: the stage's mode files, one per slot
    stage = tmp_path / "stage"
    stage.mkdir()
    found = MP.list_modes(str(project))[0]
    for slot, (slug, spec) in enumerate(found):
        with open(stage / MA.mode_file_name(slot), "w", encoding="utf-8", newline="\n") as f:
            f.write(MP.runtime_cfg(spec, slug))
    panel._tryit_live = {"project": str(project),
                         "slots": {slug: i for i, (slug, _s) in enumerate(found)},
                         "signatures": {slug: MT.asset_signature(s) for slug, s in found},
                         "stage": str(stage)}

    def select(slug):
        i = panel._slugs.index(slug)
        panel._list.selection_clear(0, "end")
        panel._list.selection_set(i)
        panel._on_select()
        app.root.update()

    select(found[0][0])
    select(found[1][0])                       # saves the first, unchanged
    select(found[0][0])                       # and the second
    assert ran == [] and "updated in the running game" not in panel._tryit_status.cget("text")

    panel.v["seconds"].set("9")               # a real edit is pushed, once
    panel.save_now()
    assert _wait_for(lambda: "updated in the running game" in panel._tryit_status.cget("text"),
                     app.root)
    assert len(ran) == 1 and ran[0][2] == "push" and ran[0][-1] == "0"
    panel.save_now()
    select(found[1][0])
    assert len(ran) == 1


def _modes_select(panel, root, slug):
    i = panel._slugs.index(slug)
    panel._list.selection_clear(0, "end")
    panel._list.selection_set(i)
    panel._on_select()
    root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_start_mode_now_reaches_only_a_mode_the_running_game_has(
        app, tmp_path, monkeypatch):
    """Start mode now names a SLOT, and the game's slot K is whatever Try it installed
    there. A mode added after Try it (BRAVO, between ALPHA and CHARLIE) would take
    CHARLIE's slot by the project's order: it is refused in a sentence, never guessed. The
    record belongs to Try it's own launch: after another Start there are no modes to reach,
    and an edit pushes nothing."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    for name in ("ALPHA", "CHARLIE"):
        MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran = []
    _fake_rig(panel, ran)
    launch = [7]
    panel._running_fn = lambda: True
    panel._run_id_fn = lambda: launch[0]
    found = MP.list_modes(str(project))[0]
    stage = tmp_path / "stage"                    # what Try it installed: ALPHA 0, CHARLIE 1
    stage.mkdir()
    for slot, (slug, spec) in enumerate(found):
        with open(stage / MA.mode_file_name(slot), "w", encoding="utf-8", newline="\n") as f:
            f.write(MP.runtime_cfg(spec, slug))
    panel._tryit_live = {"project": str(project), "slots": {"alpha": 0, "charlie": 1},
                         "signatures": {slug: MT.asset_signature(s) for slug, s in found},
                         "stage": str(stage), "run": 7}

    MP.new_mode(str(project), "BRAVO", MP.ModeSpec(name="BRAVO", screen=False, clip="none"))
    panel.refresh()
    app.root.update()
    assert MT.slot_of(str(project), "bravo") == 1          # CHARLIE's slot in the game
    _modes_select(panel, app.root, "bravo")
    assert panel._on_start_now() is None and ran == []
    assert "BRAVO is not in the running game yet" in panel._tryit_status.cget("text")

    _modes_select(panel, app.root, "charlie")
    assert panel._on_start_now() == ["RIG", "modes/tryit.sh", "start", "1"]
    assert _wait_for(lambda: "start CHARLIE (slot 1)" in panel._tryit_status.cget("text"),
                     app.root)
    # an edit while Try it's OWN launch is up (the window's wiring: a matching run id) is
    # pushed into the slot the game has
    panel.v["seconds"].set("9")
    panel.save_now()
    assert _wait_for(lambda: any(c[2] == "push" for c in ran), app.root)
    assert [c[-1] for c in ran if c[2] == "push"] == ["1"]
    assert _wait_for(lambda: "CHARLIE updated in the running game"
                     in panel._tryit_status.cget("text"), app.root)

    # a mode opened from ANOTHER project is not in the game either
    other = tmp_path / "other"
    other.mkdir()
    MP.new_mode(str(other), "ALPHA", MP.ModeSpec(name="ALPHA", screen=False, clip="none"))
    w.write_assets_var.set(str(other))
    app.root.update()
    _modes_select(panel, app.root, "alpha")
    n = len(ran)
    assert panel._on_start_now() is None and len(ran) == n
    assert "another project's modes" in panel._tryit_status.cget("text")
    w.write_assets_var.set(str(project))
    app.root.update()

    # the Emulate tab launched again (its own Start, no modes): the record is forgotten
    launch[0] = 8
    _modes_select(panel, app.root, "alpha")
    assert panel._on_start_now() is None and len(ran) == n
    assert "not started by Try it" in panel._tryit_status.cget("text")
    assert panel._tryit_live is None
    assert panel._on_end_now() is None and len(ran) == n
    panel.v["seconds"].set("9")
    panel.save_now()
    app.root.update()
    assert len(ran) == n                                     # nothing pushed


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_logs_from_the_start_worker_on_the_main_loop(app, tmp_path, monkeypatch):
    """Try it's preparation runs on the Emulate tab's start WORKER, and the app's log is a
    Tk Text widget (Tk may only be touched from the main loop): every line the preparation
    and the rig commands log reaches the log ON THE MAIN THREAD, in order, while the tab's
    own watch runs - never from the worker."""
    import threading
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, logged, result = [], [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    # the Emulate tab's launch_with, as it behaves: the preparation on a worker thread
    panel._try_fn = lambda prepare: threading.Thread(
        target=lambda: result.append(prepare(str(card))), daemon=True).start() or True
    panel._running_fn = lambda: True
    monkeypatch.setattr(panel, "_log", lambda msg: logged.append(
        (msg, threading.current_thread() is threading.main_thread())))
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    from tests.test_stern_mode_tryit import _writes_builder
    _writes_builder(monkeypatch, [])
    assert panel._on_try() is True
    assert _wait_for(lambda: result and any("ready" in m for m, _t in logged), app.root, 20)
    assert result == [panel.tryit_env()] and ran and ran[-1][2] == "install"
    said = [m for m, _t in logged]
    built = [m for m in said                                # build_set's own log, on the worker
             if "Try it: building the" in m and "Emulate tab" not in m]
    assert built, said
    assert said.index([m for m in said if "ready" in m][0]) > said.index(built[0])
    # ...and a rig command's answer, from the tab's own thread
    assert panel._on_end_now() == ["RIG", "modes/tryit.sh", "stop"]
    assert _wait_for(lambda: any("asked the game to end" in m for m, _t in logged), app.root)
    assert all(on_main for _m, on_main in logged), [m for m, t in logged if not t]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_a_project_of_code_modes_only(app, tmp_path, monkeypatch):
    """A project whose only mode is a CODE mode (New code mode, nothing in the form) can
    Try it: no set (no screens or clips to build), only the object compiled from it, the
    card's port, and PAD_MODE_SO. A card the SDK has no port for is refused."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MT.new_code_mode(str(project), "Blitz")
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    running = [False]
    panel._running_fn = lambda: running[0]
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    monkeypatch.setattr(MT, "card_title", lambda c: ("nosuch_pro", "9.9.0", 0))
    assert panel._on_try() is True and not ran
    assert handed[0](str(card)) is None and not ran
    assert "no port for nosuch_pro 9.9.0" in panel._tryit_status.cget("text")

    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 0))
    assert panel._on_try() is True
    assert handed[-1](str(card)) == ["PAD_MODE_SO=/lib/pad_mode.so"]
    assert [c[1] for c in ran] == ["modes/sdk/build_mode.sh", "modes/tryit.sh"]
    assert ran[0][-2].endswith("blitz/blitz.c") and ran[1][2] == "install"
    stage = MT.stage_dir(panel._tryit_base)
    assert os.listdir(stage) == ["game.port"]          # the object is the compiler's to make
    assert not os.path.isdir(MT.set_dir(panel._tryit_base))
    assert "Code mode(s) built in: blitz" in panel._tryit_status.cget("text")
    assert "carries them the same way" in panel._tryit_status.cget("text")
    running[0] = True
    # End mode reaches the code mode by ITS trigger (a code mode never reads mode.stop)
    assert panel._on_end_now() == ["RIG", "modes/tryit.sh", "stop", "blitz"]
    assert _wait_for(lambda: len(ran) >= 3, app.root)
    assert _wait_for(lambda: "end the code mode(s) blitz." in panel._tryit_status.cget("text"),
                     app.root)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_without_screens_or_clips_takes_no_override_set(
        app, tmp_path, monkeypatch):
    """Item 127 (2026-09-17): a set that holds no file of the TITLE - with Write's code
    (item 149), one whose only file is the manifest beside the title, as Jaws' is -
    is refused by run_game.sh ("nothing in this set belongs to the title being booted",
    exit 1), and the game never started. Such a project, alone or beside a code mode,
    hands the launch PAD_MODE_SO and no PAD_OVERRIDE_DIR, and its mode files still reach
    the rig."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    _no_wsl(monkeypatch)
    w = app.window
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    _writes_builder(monkeypatch, [], files=["spk/index/godzilla_pro-1_15_0.sidx"])
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    for with_code in (False, True):
        kind = "code" if with_code else "form"
        project = tmp_path / ("proj_" + kind)
        project.mkdir()
        for name in ("QUIET", "HUSH"):
            MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
        if with_code:
            MT.new_code_mode(str(project), "Blitz")
        w.write_assets_var.set(str(project))
        app.root.update()
        panel = w._modes_panel
        ran, handed = [], []
        _fake_rig(panel, ran)
        panel._tryit_base = str(tmp_path / ("try_" + kind))
        panel._try_fn = lambda prepare, handed=handed: handed.append(prepare) or True
        try:
            assert panel._on_try() is True and not ran
            env = handed[0](str(card))                      # what the start worker does
            assert env == ["PAD_MODE_SO=/lib/pad_mode.so"], (kind, env)
            # the set on disk really holds no file of the title...
            sdir = MT.set_dir(panel._tryit_base)
            held = sorted(os.path.relpath(os.path.join(d, n), sdir).replace(os.sep, "/")
                          for d, _dirs, names in os.walk(sdir) for n in names)
            assert held == ["spk/index/godzilla_pro-1_15_0.sidx"], (kind, held)
            # ...and the modes still reach the rig: compiled (a code mode), then installed
            assert [c[1] for c in ran] == (["modes/sdk/build_mode.sh"] if with_code else []) \
                + ["modes/tryit.sh"], (kind, ran)
            assert ran[-1][2] == "install"
            assert {"mode.cfg", "mode1.cfg", "game.port"} <= set(
                os.listdir(MT.stage_dir(panel._tryit_base)))
            assert panel._tryit_live["slots"] == {"hush": 0, "quiet": 1}
            assert panel._tryit_live["codes"] == (["blitz"] if with_code else [])
            assert "2 mode(s) ready" in panel._tryit_status.cget("text")
        finally:
            panel._tryit_working = False      # ends the status watch the hand-off started
            app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_with_game_files_in_the_set_still_binds_it(app, tmp_path, monkeypatch):
    """The other side of the fix above: when the build DOES make a file of the title (a
    mode's screen puts the HUD scene in the set), the launch binds the set with
    PAD_OVERRIDE_DIR as before. Write's builder is stood in for with that scene file in its
    set, so this needs neither the stock HUD scene nor ffmpeg."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "LOUD", MP.ModeSpec(name="LOUD", screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    hud_rel = "%s/%s/scene.radium" % (MA.LCD, MP.GODZILLA_PRO_1_15.hud_scene)
    _writes_builder(monkeypatch, [], files=["godzilla_pro/" + hud_rel,
                                            "spk/index/godzilla_pro-1_15_0.sidx"])
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    try:
        assert panel._on_try() is True
        env = handed[0](str(card))
        assert env == panel.tryit_env()
        assert env[0].startswith("PAD_OVERRIDE_DIR=") and env[0].endswith("/try/set")
        assert os.path.isfile(os.path.join(MT.set_dir(panel._tryit_base), "godzilla_pro",
                                           *hud_rel.split("/")))
        assert ran and ran[-1][2] == "install"
    finally:
        panel._tryit_working = False
        app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_open_sdk_doc_falls_back_to_plain_text(app, tmp_path, monkeypatch):
    """Open MODE_SDK.md on a Windows PC with no .md association: os.startfile raises "No
    application is associated", and the tab only said "could not open". MODE_SDK.md and a
    code mode's .c are plain text: Notepad opens them on Windows, the web browser elsewhere,
    and only when that fails too does the tab say it could not open the file."""
    import webbrowser
    from pinball_decryptor.gui import modes_tab

    _no_wsl(monkeypatch)
    panel = app.window._modes_panel
    doc = panel.sdk_doc()
    tries = []

    def no_association(path):
        tries.append(path)
        raise OSError(1155, "No application is associated with the specified file")
    panel._opener = no_association
    started = []
    monkeypatch.setattr(modes_tab.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    monkeypatch.setattr(panel, "_platform", "win32")
    panel.open_sdk_doc()
    assert tries == [doc] and started == [["notepad.exe", doc]]
    assert "opened MODE_SDK.md in Notepad" in panel._tryit_status.cget("text")

    # elsewhere, the web browser, by a file URI
    browsed = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **kw: browsed.append(url) or True)
    monkeypatch.setattr(panel, "_platform", "linux")
    panel.open_sdk_doc()
    assert len(browsed) == 1 and browsed[0].startswith("file:")
    assert browsed[0].endswith("/MODE_SDK.md") and len(started) == 1
    assert "MODE_SDK.md in the web browser" in panel._tryit_status.cget("text")

    # when the fallback fails too, it says it could not open the file
    def no_notepad(argv, **kw):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    monkeypatch.setattr(modes_tab.subprocess, "Popen", no_notepad)
    monkeypatch.setattr(panel, "_platform", "win32")
    panel.open_sdk_doc()
    assert "could not open %s" % doc in panel._tryit_status.cget("text")

    # an opener that works needs no fallback
    opened = []
    panel._opener = opened.append
    monkeypatch.setattr(modes_tab.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    panel.open_sdk_doc()
    assert opened == [doc] and len(started) == 1


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_on_the_projects_own_card(app, tmp_path, monkeypatch):
    """Item 127 with item 148: a project made from a Premium/LE 1.16 card whose modes were
    saved as Pro 1.15 (David's own project is exactly this). Try it used to refuse that card
    and, on a Pro 1.15 card, staged Pro's port while the build inside went to LE. Now the
    run takes the project's card: LE 1.16's port and masks in the stage, pressing Try it on
    an unedited mode leaves its mode.json as it was (only an edit is saved), and an edit
    while the game runs pushes LE's masks without claiming its screen waits for the next
    Try it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                                  "1.16.0")
    shots = ["Shield target right"]
    slug, _spec = MP.new_mode(str(project), "QUIET", MP.ModeSpec(
        name="QUIET", screen=False, clip="none", scoring_shots=shots))
    mode_json = project / "modes" / slug / "mode.json"
    saved = mode_json.read_bytes()
    le = MP.profile_for_card("godzilla_le", "1.16.0")
    assert le.mask(shots) != MP.GODZILLA_PRO_1_15.mask(shots)
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert panel._spec.title == le.key                      # the form shows the card's title
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    running = [False]
    panel._running_fn = lambda: running[0]
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_le", "1.16.0", 2))
    from tests.test_stern_mode_tryit import _writes_builder
    _writes_builder(monkeypatch, [])
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    try:
        assert panel._on_try() is True
        assert mode_json.read_bytes() == saved              # no edit, nothing saved
        env = handed[0](str(card))
        assert env == panel.tryit_env(), panel._tryit_status.cget("text")
        stage = MT.stage_dir(panel._tryit_base)
        with open(os.path.join(stage, "game.port"), "rb") as a, open(MP.port_path(le), "rb") as b:
            assert a.read() == b.read()
        cfg = open(os.path.join(stage, "mode.cfg"), encoding="utf-8").read()
        assert "shots          0x%08x" % le.mask(shots) in cfg
        assert "1 mode(s) ready" in panel._tryit_status.cget("text")
        assert mode_json.read_bytes() == saved
        # while the game runs, an edit pushes LE's masks, and nothing waits for the next Try it
        running[0] = True
        panel.v["seconds"].set("9")
        panel.save_now()
        assert _wait_for(lambda: any(c[2] == "push" for c in ran), app.root)
        pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
        assert "seconds        9" in pushed and "shots          0x%08x" % le.mask(shots) in pushed
        assert _wait_for(lambda: "updated in the running game" in panel._tryit_status.cget("text"),
                         app.root)
        assert "next Try it" not in panel._tryit_status.cget("text")
        # a sound of its own is built into the set's sound bank: a change to one waits for
        # the next Try it, and the tab says so
        spec = panel.collect()
        spec.music = "theme.wav"
        panel._tryit_saved(str(project), slug, spec)
        assert _wait_for(lambda: "own sounds reaches the game at the next Try it"
                         in panel._tryit_status.cget("text"), app.root)
    finally:
        running[0] = False
        panel._tryit_working = False
        app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_pushes_keep_the_carriers_writes_set_named(app, tmp_path, monkeypatch):
    """Item 149 with item 150: Try it's set is Write's, so a mode's own start sound is in its
    sound bank on a carrier request, and the stage's mode file names it. The ready line does
    not call that sound left out, and an edit pushed while the game runs keeps naming the
    carrier (a push without it would silence the sound the set carries)."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    _no_wsl(monkeypatch)
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    slug, spec = MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False,
                                                                 clip="none"))
    folder = MP.mode_folder(str(project), slug)
    with open(os.path.join(folder, "go.wav"), "wb") as f:
        f.write(b"RIFF")
    spec.sound_start = "go.wav"
    MP.save(str(project), slug, spec)
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed = [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    running = [False]
    panel._running_fn = lambda: running[0]
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    carried = {slug: {"requests": {"sound_start": 1251}, "ms": {"sound_start": 480}}}
    _writes_builder(monkeypatch, [], own_sounds=carried)
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    try:
        assert panel._on_try() is True
        assert handed[0](str(card)) == panel.tryit_env()
        status = panel._tryit_status.cget("text")
        assert "1 mode(s) ready (QUIET)" in status and "not in this run" not in status, status
        stage = MT.stage_dir(panel._tryit_base)
        assert "sound_start    1251 480" in open(os.path.join(stage, "mode.cfg"),
                                                 encoding="utf-8").read()
        running[0] = True
        panel.v["seconds"].set("9")
        panel.save_now()
        assert _wait_for(lambda: any(c[2] == "push" for c in ran), app.root)
        pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
        assert "seconds        9" in pushed and "sound_start    1251 480" in pushed
    finally:
        running[0] = False
        panel._tryit_working = False
        app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_a_tmnt_pro_project(app, tmp_path, monkeypatch):
    """Item 127 with item 148: TMNT Pro 1.59's port names no HUD scene, and Try it read one
    anyway (``/turtles_pro/assets/lcd/auto_loaded//scene.radium``), so every form mode on
    TMNT Pro and Deadpool was refused while a Write build of it succeeded. Try it's own
    check runs here against a stand-in card and reads no scene; Write's builder (stood in
    for; tests/test_stern_mode_tryit runs the real one on the real TMNT card) gives the run
    TMNT's port and TMNT's masks, and the set with its patched game program."""
    from pinball_decryptor.plugins.stern import explorer
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    _no_wsl(monkeypatch)
    w = app.window
    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    shots = ["Left ramp", "Right ramp"]
    slug, _spec = MP.new_mode(str(project), "SHELL SHOCK", MP.ModeSpec(
        name="SHELL SHOCK", title=tmnt.key, start_shot="Center loop", scoring_shots=shots,
        screen=False, clip="none"))
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    ran, handed, reads = [], [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True

    class Card:
        def __init__(self, path):
            reads.append(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def preview(self, part, path, cap=None):
            reads.append(path)
            return None
    monkeypatch.setattr(explorer, "CardImage", Card)
    monkeypatch.setattr(MT, "card_title", lambda card: ("turtles_pro", "1.59.0", 3))
    from tests.test_stern_mode_tryit import _writes_builder
    _writes_builder(monkeypatch, [])
    card = tmp_path / "turtles.raw"
    card.write_bytes(b"\0" * 32)
    try:
        assert panel._on_try() is True and not ran
        env = handed[0](str(card))
        status = panel._tryit_status.cget("text")
        assert env == panel.tryit_env(), status
        assert reads == [] and "scene.radium" not in status
        assert "1 mode(s) ready (SHELL SHOCK)" in status
        assert len(ran) == 1 and ran[0][:3] == ["RIG", "modes/tryit.sh", "install"]
        stage = MT.stage_dir(panel._tryit_base)
        with open(os.path.join(stage, "game.port"), "rb") as a, open(MP.port_path(tmnt), "rb") as b:
            assert a.read() == b.read()
        cfg = open(os.path.join(stage, "mode.cfg"), encoding="utf-8").read()
        assert "shots          0x%08x" % tmnt.mask(shots) in cfg
        assert panel._tryit_live["slots"] == {slug: 0}
    finally:
        panel._tryit_working = False
        app.root.update()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_without_a_card_names_the_projects_own_card(app, tmp_path, monkeypatch):
    """With no card picked in the Emulate tab, Try it says which card to pick: the
    PROJECT'S card (item 148), not the title its modes were first saved for."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    _no_wsl(monkeypatch)
    w = app.window
    cases = (("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0", MP.GODZILLA_PRO_1_15.key,
              "Godzilla Premium/LE 1.16"),
             ("turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0", "turtles_pro_1_59",
              "TMNT Pro 1.59"))
    for n, (card_name, version, saved_as, label) in enumerate(cases):
        project = _modes_card_project(tmp_path, card_name, version, folder="proj%d" % n)
        MP.new_mode(str(project), "QUIET", MP.ModeSpec(
            name="QUIET", title=saved_as, start_shot="Left ramp", scoring_shots=["Left ramp"],
            screen=False, clip="none"))
        w.write_assets_var.set(str(project))
        app.root.update()
        panel = w._modes_panel
        ran, handed = [], []
        _fake_rig(panel, ran)
        panel._tryit_base = str(tmp_path / ("try%d" % n))
        panel._try_fn = lambda prepare, handed=handed: handed.append(prepare) or True
        try:
            assert panel._on_try() is True
            assert handed[0](str(tmp_path / "no_card_picked.raw")) is None
            status = panel._tryit_status.cget("text")
            assert "pick a card image in the Emulate tab first (a %s card)" % label in status, status
            assert not ran
        finally:
            panel._tryit_working = False
            app.root.update()


def _modes_card_project(tmp_path, card_name, card_version=None, folder="proj"):
    """A project folder whose extract record names ``card_name`` (item 148)."""
    import json
    project = tmp_path / folder
    project.mkdir()
    rec = {"input_path": "D:\\cards\\" + card_name, "input_name": card_name, "size": 1, "mtime": 1}
    if card_version:
        rec["card_version"] = card_version
    (project / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    return project


def _modes_widgets(widget, kinds):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, kinds):
            out.append(child)
        out.extend(_modes_widgets(child, kinds))
    return out


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_on_a_tmnt_pro_project_lists_its_shots_and_greys_what_it_cannot(app, tmp_path):
    """Item 148: a project on a TMNT Pro 1.59 card offers TMNT's 17 shots from its port,
    greys Lights, Screen and Clip and the countdown WITH the reason in words, and New
    makes a mode whose runtime file carries TMNT's own masks and no line TMNT cannot do."""
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    names = [n for n, _m in tmnt.shots]
    assert len(names) == 17
    assert list(panel._shot_vars) == names
    assert len(_modes_widgets(panel._shots_box, ttk.Checkbutton)) == 17
    assert list(panel._start_combo.cget("values")) == names
    title = panel._title_label.cget("text")
    assert "TMNT Pro 1.59" in title and "turtles_pro-1.59.port" in title and "17 shots" in title
    assert panel._ex_menu.index("end") == 0 and panel._ex_menu.entrycget(0, "label") == "TARGET RUSH"
    assert str(panel._new_btn.cget("state")) == "normal"

    slug = panel.new_mode()
    app.root.update()
    assert "Ready to build" in panel._status.cget("text")
    for part, box in (("lights", panel._lights_box), ("screen", panel._screen_box),
                      ("clip", panel._clip_box)):
        reason = panel._reason_labels[part]
        assert reason.grid_info() and "Not on this game" in reason.cget("text")
        assert tmnt.why_not(part) in reason.cget("text")
        live = [f for f in _modes_widgets(box, panel._INTERACTIVE) if str(f.cget("state")) != "disabled"]
        assert not live, "%s left live on TMNT" % part
        assert str(reason.cget("state")) != "disabled"          # the reason itself is legible
    assert panel._countdown_chk.instate(["disabled"]) and panel._own_sound_radio.instate(["disabled"])
    assert "countdown" in panel._reason_labels["sound"].cget("text")
    assert not any(f.instate(["disabled"]) for f in _modes_widgets(panel._shots_box, ttk.Checkbutton))

    spec = MP.load(str(project / "modes" / slug / "mode.json"))
    assert spec.title == "turtles_pro_1_59" and spec.start_shot == "Center loop"
    cfg = MP.runtime_cfg(spec, slug)
    assert "trigger        0x00000080 3" in cfg                  # Center loop x3, TMNT's bit
    assert "shots          0x00000210" in cfg                    # Left ramp + Right ramp on TMNT
    for gone in ("screen_scene", "clip_start", "light_on", "callout_count", "callout_end"):
        assert gone not in cfg


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_premium_1_16_project_offers_godzillas_names(app, tmp_path):
    """The machine's card, Godzilla Premium 1.16 (a godzilla_le card): Godzilla's names
    including its third shield target, KAIJU RUSH under Examples, nothing greyed."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    names = list(panel._shot_vars)
    assert len(names) == 18 and "Shield target center" in names and "Maser target" in names
    assert "Godzilla Premium/LE 1.16" in panel._title_label.cget("text")
    assert panel._ex_menu.entrycget(0, "label") == "KAIJU RUSH"
    panel._on_title_example("KAIJU RUSH")
    app.root.update()
    assert "Ready to build" in panel._status.cget("text")
    assert not any(lb.grid_info() for lb in panel._reason_labels.values())
    assert not panel._lights_box.winfo_children()[0].instate(["disabled"])
    spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
    assert spec.title == "godzilla_le_1_16"
    assert "0x08000000 3" in MP.runtime_cfg(spec, "kaiju_rush")


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_card_with_no_port_points_at_making_a_port(app, tmp_path):
    """Godzilla Pro 1.16 has no port: the tab says so, names MODE_SDK.md's "Making a
    port", and New and Examples are off."""
    project = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    note = panel._title_note.cget("text")
    assert "MODE_SDK.md" in note and "Making a port for another game or version" in note
    assert "Godzilla Pro 1.16.0" in note
    assert str(panel._new_btn.cget("state")) == "disabled"
    assert str(panel._ex_btn.cget("state")) == "disabled"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_jaws_greys_lights_and_screen_and_a_godzilla_mode_is_retargeted(app, tmp_path):
    """Jaws LE 1.02 can count down and add a clip (an added clip played in item 148's run2)
    but has no lights and no measured HUD; its 27 shots go in three columns. A Godzilla mode already in the project is matched
    by name: the shots Jaws lacks are dropped and the log says which."""
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    MP.new_mode(str(project), spec=MP.example("KAIJU RUSH"))
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert len(_modes_widgets(panel._shots_box, ttk.Checkbutton)) == 27
    assert max(int(c.grid_info()["column"]) for c in panel._shots_box.winfo_children()) == 2
    for part in ("lights", "screen"):
        assert panel._reason_labels[part].grid_info()
    assert "clip" not in panel._reason_labels or not panel._reason_labels["clip"].grid_info()
    assert not panel._countdown_chk.instate(["disabled"])
    assert panel.v["start_shot"].get() == "Chum bucket target"
    assert [n for n, var in panel._shot_vars.items() if var.get()] == ["Left ramp", "Right ramp"]
    status = panel._status.cget("text")
    assert "Maser target is not a shot on Jaws LE 1.02, so it starts on Chum bucket target until you pick one" in status
    assert "Powerline left, Powerline center, Powerline right are not on Jaws LE 1.02" in status
    assert status.startswith("Ready to build once saved") and "its file is unchanged" in status
    # the countdown stays live on Jaws, and says its callouts have not been heard
    unheard = panel._reason_labels["sound_unheard"]
    assert unheard.grid_info() and "not been heard yet" in unheard.cget("text")
    panel.v["award"].set("1,500,000")                  # an edit: now the card's shots are saved
    panel.save_now()
    spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
    assert spec.title == "jaws_le_1_02" and spec.scoring_shots == ["Left ramp", "Right ramp"]
    assert spec.start_shot == "Chum bucket target" and spec.award == 1500000
    assert panel._status.cget("text").startswith("Ready to build.")
    assert "Its file now has this card's shots" in panel._status.cget("text")
    log = w._log_text.get("1.0", "end") if getattr(w, "_log_text", None) is not None else ""
    if log.strip():
        assert "Powerline left" in log and "Jaws LE 1.02" in log


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_bare_project_keeps_godzilla_pro_1_15(app, tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "bare"
    project.mkdir()
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert list(panel._shot_vars) == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    assert "names no card" in panel._title_label.cget("text")
    assert panel._title_note.cget("text") == ""
    assert str(panel._new_btn.cget("state")) == "normal"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_greys_stacking_and_film_cuts_a_title_cannot_use(app, tmp_path):
    """Item 148 with items 140 and 142: TMNT Pro 1.59's port names none of the game's own
    mode queries and cannot use a clip, a screen picture or a sound of the mode's own, so
    "The game's own modes" and the three film buttons are greyed, each with the reason;
    Jaws LE 1.02 greys only the picture cut. On the machine's Premium 1.16 card
    everything stays live."""
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert panel.new_mode()
    app.root.update()
    box = panel._stacking_box()
    assert box is not None and "game's own modes" in str(box.cget("text"))
    assert all(c.instate(["disabled"]) for c in _modes_widgets(box, ttk.Checkbutton))
    assert panel._reason_labels["stack"].grid_info()
    assert tmnt.why_not("stack") in panel._reason_labels["stack"].cget("text")
    assert all(str(b.cget("state")) == "disabled" for b in panel._film_btns.values())
    film = panel._reason_labels["film"].cget("text")
    assert "a clip, a picture for the screen or a sound" in film and "TMNT Pro 1.59" in film
    # item 147's events: TMNT's port names none, so "An event" is greyed with the reason
    ev = panel._reason_labels["events"]
    assert ev.grid_info() and tmnt.why_not("events") in ev.cget("text")
    assert all(c.instate(["disabled"]) for c in _modes_widgets(ev.master, ttk.Combobox))
    assert sorted(str(r.cget("value")) for r in _modes_widgets(ev.master, ttk.Radiobutton)
                  if not r.instate(["disabled"])) == ["clock", "drain", "shot"]

    jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0", folder="jaws")
    w.write_assets_var.set(str(jaws))
    app.root.update()
    assert panel.new_mode()
    app.root.update()
    assert {t: str(b.cget("state")) for t, b in panel._film_btns.items()} == {
        "clip": "normal", "still": "disabled", "sound": "normal"}
    assert "cutting a picture for the screen from a film" in panel._reason_labels["film"].cget("text")

    premium = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                                  folder="prem")
    w.write_assets_var.set(str(premium))
    app.root.update()
    assert panel.new_mode()
    app.root.update()
    assert not any(c.instate(["disabled"]) for c in _modes_widgets(panel._stacking_box(), ttk.Checkbutton))
    assert not panel._reason_labels["stack"].grid_info()
    assert all(str(b.cget("state")) == "normal" for b in panel._film_btns.values())
    assert not panel._reason_labels["film"].grid_info()
    assert not panel._reason_labels["events"].grid_info()
    assert not any(r.instate(["disabled"]) for r in _modes_widgets(panel._reason_labels["events"].master,
                                                                   ttk.Radiobutton))


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_no_port_card_after_another_title_never_rewrites_a_modes_shots(app, tmp_path):
    """Item 148: after a TMNT project, a project on a card with no port (Godzilla Pro 1.16)
    that already holds Godzilla modes shows each mode with the shots of the title it was
    made for - never TMNT's - read-only, and nothing it does rewrites mode.json. A no-port
    project with no modes shows no shot names at all."""
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    gz116 = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                                folder="gz116")
    for name, spec in MP.example_specs()[:2]:
        MP.new_mode(str(gz116), name, spec)
    files = {slug: (gz116 / "modes" / slug / "mode.json").read_bytes()
             for slug, _s in MP.list_modes(str(gz116))[0]}
    w = app.window
    w.write_assets_var.set(str(tmnt))
    app.root.update()
    panel = w._modes_panel
    assert panel.new_mode()
    app.root.update()
    assert "Center loop" in panel._shot_vars

    w.write_assets_var.set(str(gz116))
    app.root.update()
    pro = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    assert list(panel._shot_vars) == pro and "Center loop" not in panel._shot_vars
    assert list(panel._start_combo.cget("values")) == pro
    assert panel._spec.name == "ATOMIC BREATH"                  # slug order: atomic_breath first
    assert sorted(n for n, var in panel._shot_vars.items() if var.get()) == sorted(MP.example("ATOMIC BREATH").scoring_shots)
    live =[c for c in _modes_widgets(panel._editor, panel._INTERACTIVE) if str(c.cget("state")) != "disabled"]
    assert not live, "a mode on a card with no port is shown read-only"
    assert str(panel._del_btn.cget("state")) == "normal"
    assert "read-only" in panel._status.cget("text")
    panel.v["award"].set("2,000,000")                       # even a change made in code
    panel.save_now()
    panel._list.selection_clear(0, "end")                  # and moving between modes
    panel._list.selection_set(1)
    panel._on_select()
    app.root.update()
    assert panel._spec.name == "KAIJU RUSH"
    assert sorted(n for n, var in panel._shot_vars.items() if var.get()) == sorted(MP.example("KAIJU RUSH").scoring_shots)
    panel.save_now()
    assert {slug: (gz116 / "modes" / slug / "mode.json").read_bytes() for slug in files} == files

    jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0", folder="jaws")
    w.write_assets_var.set(str(jaws))
    app.root.update()
    assert len(panel._shot_vars) == 27
    empty = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                                folder="empty")
    w.write_assets_var.set(str(empty))
    app.root.update()
    assert panel._shot_vars == {} and not _modes_widgets(panel._shots_box, ttk.Checkbutton)
    assert list(panel._start_combo.cget("values")) == [] and panel.v["start_shot"].get() == ""
    assert str(panel._new_btn.cget("state")) == "disabled"
    # and a disabled button LOOKS disabled, in both themes (it drew like a live one in dark)
    from pinball_decryptor.gui.theme import THEMES
    style = ttk.Style()
    before = w._current_theme
    try:
        for theme in ("dark", "light"):
            w._apply_theme(theme)
            assert style.lookup("TButton", "foreground", ["disabled"]) == THEMES[theme]["gray"]
            assert style.lookup("TButton", "foreground") == THEMES[theme]["fg"]
    finally:
        w._apply_theme(before)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_renamed_card_is_read_only_until_its_game_is_read(app, tmp_path, monkeypatch):
    """Item 148: while a renamed card's game is read off the UI thread, its project's mode is
    shown on its own title, read-only, and nothing is saved; once the card answers, the mode
    is on the card's port and editable. A card file that goes away mid-read stops the wait."""
    import json
    import threading
    import time
    from pinball_decryptor.plugins.stern import mode_project as MP

    def project(folder, image):
        p = tmp_path / folder
        p.mkdir()
        rec = {"input_path": str(image), "input_name": image.name, "size": 1, "mtime": 1,
               "card_version": "1.16.0"}
        (p / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
        return p

    def pump(until, seconds=8):
        end = time.time() + seconds
        while time.time() < end and not until():
            app.root.update()
            time.sleep(0.05)
        return until()

    go = threading.Event()

    def probe(path):
        go.wait(15)
        try:
            MP._PROBED[MP._probe_key(path)] = ("godzilla_le", "1.16.0")
        except OSError:
            return None, None
        return "godzilla_le", "1.16.0"

    monkeypatch.setattr(MP, "_PROBED", {})
    monkeypatch.setattr(MP, "probe_card_title", probe)
    image = tmp_path / "my card.raw"
    image.write_bytes(b"\0" * 1024)
    proj = project("proj", image)
    MP.new_mode(str(proj), spec=MP.example("KAIJU RUSH"))
    saved = (proj / "modes" / "kaiju_rush" / "mode.json").read_bytes()
    w = app.window
    panel = w._modes_panel
    try:
        w.write_assets_var.set(str(proj))
        app.root.update()
        assert "Reading which game" in panel._title_label.cget("text")
        assert list(panel._shot_vars) == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
        live = [c for c in _modes_widgets(panel._editor, panel._INTERACTIVE) if str(c.cget("state")) != "disabled"]
        assert not live
        panel.v["award"].set("5")
        panel.save_now()
        assert (proj / "modes" / "kaiju_rush" / "mode.json").read_bytes() == saved
        go.set()
        assert pump(lambda: "Premium/LE 1.16" in panel._title_label.cget("text"))
        assert len(panel._shot_vars) == 18 and panel._spec.title == "godzilla_le_1_16"
        assert str(panel._dup_btn.cget("state")) == "normal"
        assert "read-only" not in panel._status.cget("text")
    finally:
        go.set()

    go.clear()
    gone = tmp_path / "gone card.raw"
    gone.write_bytes(b"\0" * 1024)
    w.write_assets_var.set(str(project("gone", gone)))
    app.root.update()
    try:
        assert "Reading which game" in panel._title_label.cget("text")
        gone.unlink()
        assert pump(lambda: "could not be read" in panel._title_label.cget("text"))
        assert str(panel._new_btn.cget("state")) == "normal"
    finally:
        go.set()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_bare_project_keeps_a_modes_own_title(app, tmp_path):
    """Item 148: a project that names no card retargets nothing. A TMNT mode in it is shown
    with TMNT's shots and saved back as TMNT, while New still makes Godzilla Pro 1.15."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = tmp_path / "bare"
    project.mkdir()
    spec = MP.blank_spec(tmnt, "TURTLE RUSH")
    spec.scoring_shots = ["Left orbit", "Left ramp", "Right top lane"]
    slug, _s = MP.new_mode(str(project), spec=spec)
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert list(panel._shot_vars) == [n for n, _m in tmnt.shots]
    panel.v["award"].set("123456")
    panel.save_now()
    saved = MP.load(str(project / "modes" / slug / "mode.json"))
    assert saved.title == tmnt.key and saved.scoring_shots == spec.scoring_shots and saved.award == 123456
    assert panel._ex_menu.entrycget(0, "label") == "KAIJU RUSH"
    new = panel.new_mode()
    app.root.update()
    assert MP.load(str(project / "modes" / new / "mode.json")).title == MP.GODZILLA_PRO_1_15.key
    assert list(panel._shot_vars) == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]


def _modes_pump(app, seconds):
    """Run the Tk loop long enough for a debounced save (500 ms) to have fired."""
    import time
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_opening_a_mode_on_another_titles_card_writes_nothing_until_an_edit(app, tmp_path):
    """Item 148: opening a mode made for Godzilla Pro 1.15 on a Jaws LE 1.02 card matches
    its shots by name IN THE FORM only. Moving between modes, pressing New and switching
    project, with no edit, leave its mode.json byte for byte as it was, so a build still
    refuses it (MODE_SDK.md: a mode naming a shot the card's game lacks is refused, never
    built with shots left out). On the machine's Premium 1.16 card a mode saved as Pro 1.15
    keeps its file too."""
    import pytest
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP

    def files(project):
        return {p.parent.name: p.read_bytes() for p in project.glob("modes/*/mode.json")}

    jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0", folder="jaws")
    MP.new_mode(str(jaws), spec=MP.example("KAIJU RUSH"))
    MP.new_mode(str(jaws), spec=MP.example("ATOMIC BREATH"))
    before = files(jaws)
    bare = tmp_path / "bare"
    bare.mkdir()
    w = app.window
    panel = w._modes_panel
    w.write_assets_var.set(str(jaws))
    app.root.update()
    assert panel._spec.name == "ATOMIC BREATH" and panel._spec.title == "jaws_le_1_02"   # in the form
    for i in (1, 0, 1):                                  # between the two modes, no edit
        panel._list.selection_clear(0, "end")
        panel._list.selection_set(i)
        panel._on_select()
        _modes_pump(app, 0.2)
    assert panel._spec.name == "KAIJU RUSH" and panel.v["start_shot"].get() == "Chum bucket target"
    assert "until you pick one" in panel._status.cget("text")
    w.write_assets_var.set(str(bare))                    # and away, no edit
    _modes_pump(app, 0.7)
    assert files(jaws) == before
    w.write_assets_var.set(str(jaws))
    app.root.update()
    new = panel.new_mode()                               # New flushes only an edit
    _modes_pump(app, 0.7)
    after = files(jaws)
    assert set(after) == set(before) | {new} and {k: after[k] for k in before} == before
    with pytest.raises(MA.ModeAssetError) as e:
        MA.build(str(jaws), None, None, str(tmp_path / "out"))
    assert "KAIJU RUSH" in str(e.value) and "Maser target" in str(e.value)

    prem = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                               folder="prem")
    MP.new_mode(str(prem), spec=MP.example("KAIJU RUSH"))
    saved = files(prem)
    assert MP.load(str(prem / "modes" / "kaiju_rush" / "mode.json")).title == "godzilla_pro_1_15"
    w.write_assets_var.set(str(prem))
    app.root.update()
    assert panel._spec.title == "godzilla_le_1_16"
    assert "until you pick one" not in panel._status.cget("text")    # every shot is on Premium
    w.write_assets_var.set(str(bare))
    _modes_pump(app, 0.7)
    assert files(prem) == saved


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_and_the_games_call_follow_the_title(app, tmp_path):
    """Item 148 with item 141: on TMNT Pro 1.59 the Advanced section's points per shot and
    its early-ending shot offer TMNT's own 17 shots (they listed Godzilla Pro 1.15's on
    every game), its callout picks name none (TMNT's port names no countdown or time-up
    callout), and "The game's own call" is greyed with the reason, since nothing plays when
    time is up. A TMNT shot's own points are saved as TMNT's mask and shown again when the
    mode is opened again. A project with no modes shows none of the last mode's values."""
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    names = [n for n, _m in tmnt.shots]
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    w = app.window
    panel = w._modes_panel
    w.write_assets_var.set(str(project))
    app.root.update()
    slug = panel.new_mode()
    app.root.update()
    assert list(panel._shot_award_vars) == names
    ends = [c for c in _modes_widgets(panel._params_frame, ttk.Combobox)
            if str(c.cget("textvariable")) == str(panel.v["end_shot"])]
    assert len(ends) == 1 and list(ends[0].cget("values")) == [panel.PARAM_NEVER] + names
    picks = [m for m in _modes_widgets(panel._params_frame, ttk.Menubutton) if str(m.cget("text")) == "Pick"]
    assert len(picks) == panel.PARAM_CALLOUT_ROWS
    for pick in picks:
        menu = pick.nametowidget(pick.cget("menu"))
        assert menu.index("end") == 0 and "TMNT Pro 1.59" in menu.entrycget(0, "label")
        assert menu.entrycget(0, "state") == "disabled"
    game = [r for r in _modes_widgets(panel._sound_box, ttk.Radiobutton) if str(r.cget("value")) == "game"]
    assert len(game) == 1 and game[0].instate(["disabled"])
    assert "nothing plays when time is up" in panel._reason_labels["sound"].cget("text")
    assert not any(e.instate(["disabled"]) for e in _modes_widgets(panel._params_frame, ttk.Entry)
                   if str(e.cget("textvariable")) == str(panel._shot_award_vars["Left orbit"]))
    second = [r for r in _modes_widgets(panel._params_frame, ttk.Radiobutton)
              if str(r.cget("variable")) == str(panel.v["clip_both"])]
    assert len(second) == 4 and all(r.instate(["disabled"]) for r in second)
    assert "a second clip" in panel._reason_labels["clip_both"].cget("text")

    panel._shot_award_vars["Left orbit"].set("750000")
    panel.v["end_shot"].set("Center loop")
    panel.save_now()
    spec = MP.load(str(project / "modes" / slug / "mode.json"))
    assert spec.shot_award == [["Left orbit", 750000]] and spec.end_shot == "Center loop"
    assert MP.validate(spec) == []
    cfg = MP.runtime_cfg(spec, slug)
    assert "shot_award     0x%08x 750000" % tmnt.mask(["Left orbit"]) in cfg
    assert "end_shot       0x%08x" % tmnt.mask(["Center loop"]) in cfg

    empty = tmp_path / "empty"
    empty.mkdir()
    w.write_assets_var.set(str(empty))
    app.root.update()
    assert list(panel._shot_award_vars) == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    for key in ("name", "seconds", "award", "start_shot", "clip_title"):
        assert panel.v[key].get() == "", key
    assert not any(var.get() for var in panel._shot_vars.values())
    w.write_assets_var.set(str(project))
    app.root.update()
    assert panel._shot_award_vars["Left orbit"].get() == "750000"      # shown, not kept aside
    assert panel.v["end_shot"].get() == "Center loop"
    no_port = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                                  folder="noport")
    w.write_assets_var.set(str(no_port))                # no port, no modes: no shot names anywhere
    app.root.update()
    assert panel._shot_award_vars == {} and list(ends[0].cget("values")) == [panel.PARAM_NEVER]
    assert panel.v["name"].get() == ""

    prem = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                               folder="prem")
    w.write_assets_var.set(str(prem))
    app.root.update()
    assert panel.new_mode()
    app.root.update()
    le = MP.profile("godzilla_le_1_16")
    assert list(panel._shot_award_vars) == [n for n, _m in le.shots]
    menu = picks[0].nametowidget(picks[0].cget("menu"))
    assert menu.index("end") == 1 and "Ten seconds left (%d)" % le.callout_ten_seconds == menu.entrycget(0, "label")
    game = [r for r in _modes_widgets(panel._sound_box, ttk.Radiobutton) if str(r.cget("value")) == "game"]
    assert not game[0].instate(["disabled"])
    assert "sound_unheard" not in panel._reason_labels or not panel._reason_labels["sound_unheard"].grid_info()
    assert not any(r.instate(["disabled"]) for r in _modes_widgets(panel._params_frame, ttk.Radiobutton)
                   if str(r.cget("variable")) == str(panel.v["clip_both"]))
    assert not panel._reason_labels["clip_both"].grid_info()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_a_godzilla_modes_advanced_fields_follow_a_jaws_card(app, tmp_path):
    """Family sweep (item 148's open gap with item 141): a Godzilla Pro 1.15 mode with points
    on a Powerline, a Powerline that ends it early and a hand-typed callout, opened on a Jaws
    LE 1.02 card. Before, the Powerline's points were kept aside where no control showed them
    and every build refused the mode for good. Now the form drops what Jaws lacks and says so,
    moves the ten-seconds call to Jaws's own id, and after one edit the file builds."""
    import pytest
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    spec = MP.example("KAIJU RUSH")
    spec.clip = "none"                                   # no stock bank is read here
    spec.shot_award = [["Powerline left", 750000], ["Left ramp", 500000]]
    spec.end_shot = "Powerline right"
    spec.callout_at = [[10, 1291], [3, 1111]]
    slug, _spec = MP.new_mode(str(project), spec=spec)
    path = project / "modes" / slug / "mode.json"
    before = path.read_bytes()
    w = app.window
    panel = w._modes_panel
    w.write_assets_var.set(str(project))
    app.root.update()
    assert panel._shot_award_vars["Left ramp"].get() == "500000"
    assert "Powerline left" not in panel._shot_award_vars and panel._params_kept_awards == []
    assert panel.v["end_shot"].get() == panel.PARAM_NEVER and "end_shot" not in panel._params_raw
    assert [(s.get(), c.get()) for s, c in panel._callout_rows][:2] == [("10", "1387"), ("", "")]
    assert panel._params_kept_callouts == []
    status = panel._status.cget("text")
    for words in ("Powerline left is not on Jaws LE 1.02, so its own points are left out",
                  "Powerline right is not on Jaws LE 1.02, so no shot ends the mode early",
                  "callout 1111 is a sound number of another game and no callout measured on Jaws LE 1.02",
                  "callout 1291 is 1387 on Jaws LE 1.02", "a build refuses it"):
        assert words in status, words
    assert path.read_bytes() == before                   # opening it wrote nothing
    with pytest.raises(MA.ModeAssetError, match="callout 1111"):
        MA.build(str(project), None, None, str(tmp_path / "out"))

    panel.v["award"].set("1,500,000")                    # one edit saves the card's version
    panel.save_now()
    saved = MP.load(str(path))
    assert saved.shot_award == [["Left ramp", 500000]] and saved.end_shot == ""
    assert saved.callout_at == [[10, 1387]] and MP.validate(saved) == []
    assert panel._status.cget("text").startswith("Ready to build.")
    out = tmp_path / "out2"
    MA.build(str(project), None, None, str(out))
    cfg = (out / "padmode" / "mode.cfg").read_text(encoding="utf-8")
    assert "shot_award     0x%08x 500000" % MP.profile("jaws_le_1_02").mask(["Left ramp"]) in cfg
    assert "callout_at     10 1291" not in cfg and "1111" not in cfg and "end_shot" not in cfg


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_offers_sounds_of_its_own(app, tmp_path):
    """Item 150: a start sound, a shot sound (every Nth shot) and music, each a WAV in the
    mode folder, saved with the mode and turned into the mode-file keys once carried."""
    import json
    import wave
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_sounds as MS

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode()
    folder = project / "modes" / slug
    assert set(panel._own_sound_labels) == {"sound_start", "sound_shot", "music"}
    for name in ("start.wav", "shot.wav", "music.wav", "end.wav"):
        with wave.open(str(folder / name), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(b"\x00\x00" * 4410)
    # what "My sound…" does after the file dialog: the file named, the radio on file
    panel._spec.sound_start, panel._spec.sound_shot, panel._spec.music = "start.wav", "shot.wav", "music.wav"
    panel._spec.end_sound = "end.wav"
    for var in ("start_sound_mode", "shot_sound_mode", "music_mode", "end_mode"):
        panel.v[var].set("file")
    panel.v["sound_shot_every"].set("3")
    panel.save_now()
    data = json.load(open(folder / "mode.json", encoding="utf-8"))
    assert (data["sound_start"], data["sound_shot"], data["music"], data["sound_shot_every"]) == \
        ("start.wav", "shot.wav", "music.wav", 3)
    assert "Ready to build" in panel._status.cget("text")
    assert panel._own_sound_labels["music"].cget("text") == "Sound: music.wav"

    spec = MP.load(str(folder / "mode.json"))
    carried = MS.assign_specs(spec.title, [spec])[0]
    assert set(carried) == set(MS.SOUND_KEYS) | {"music_sid"}      # item 150 follow-up: its own bed
    text = MP.runtime_cfg(spec, slug, own_sounds=carried)
    assert "sound_shot     %d 3" % carried["sound_shot"] in text
    assert "music          %d %d" % (carried["music"], carried["music_sid"]) in text
    assert "callout_end" in text                     # an older mode.so still has its call
    assert "sound_start" not in MP.runtime_cfg(spec, slug)

    panel.v["music_mode"].set("none")
    panel.save_now()
    assert json.load(open(folder / "mode.json", encoding="utf-8"))["music"] == ""
    panel.v["sound_shot_every"].set("0")
    panel.save_now()
    assert "every 2nd" in panel._status.cget("text")


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_own_sounds_note_never_says_write_leaves_them_out(app):
    """Item 149 (`b15b0ebd`) made Write carry item 150's start sound, shot sound and music,
    so the "Sounds of its own" note may not go back to saying Write leaves them off the
    card. A stale note here is the tab telling a person their sounds will not be written."""
    note = app.window._modes_panel._own_sounds_note.cget("text")
    assert "does not add" not in note and "not yet" not in note and "yet." not in note, note
    assert "Write puts them on the card" in note, note


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_how_often_a_mode_can_start(app, tmp_path):
    """Item 139: the tab's "How often it can start" choices land in mode.json and in the
    generated mode file, the tab says it in words - the same words the generator gives
    for the saved spec, so the tab and the file agree - and reopening restores the form.
    A mode left at the default writes neither key, as before."""
    import json
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode()
    path = project / "modes" / slug / "mode.json"
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert (data["starts"], data["cooldown"]) == ("unlimited", 0)
    text = MP.runtime_cfg(MP.load(str(path)), slug)
    assert "\nstarts " not in text and "\ncooldown " not in text
    assert panel._starts_words.cget("text") == "Can start: any number of times"

    cases = [
        ("once_per_game", None, "0", "once_per_game", 0, "starts         once_per_game"),
        ("once_per_ball", None, "15", "once_per_ball", 15, "starts         once_per_ball"),
        ("count", "3", "0", 3, 0, "starts         3"),
        ("unlimited", None, "20", "unlimited", 20, "cooldown       20"),
    ]
    for policy, count, cooldown, want_starts, want_cooldown, want_line in cases:
        panel.v["starts_policy"].set(policy)
        if count is not None:
            panel.v["starts_count"].set(count)
        panel.v["cooldown"].set(cooldown)
        panel.save_now()
        data = json.load(open(path, encoding="utf-8"))
        assert (data["starts"], data["cooldown"]) == (want_starts, want_cooldown), policy
        spec = MP.load(str(path))
        assert want_line in MP.runtime_cfg(spec, slug).splitlines(), policy
        assert panel._starts_words.cget("text") == MP.starts_words(spec), policy
        assert "Ready to build" in panel._status.cget("text"), policy

    # reopening the mode puts the form back as it was saved
    panel.v["starts_policy"].set("count")
    panel.v["starts_count"].set("7")
    panel.v["cooldown"].set("45")
    panel.save_now()
    panel._slug = None
    panel.refresh(select=slug)
    assert panel.v["starts_policy"].get() == "count" and panel.v["starts_count"].get() == "7"
    assert panel.v["cooldown"].get() == "45"
    assert panel._starts_words.cget("text") == \
        "Can start: up to 7 times a game, for each player; not again until 45 s after it ends"

    # a count that is not one is named, not silently changed
    panel.v["starts_count"].set("0")
    panel.save_now()
    assert "How often it can start" in panel._status.cget("text")


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_from_a_film_makes_the_cut_the_modes_clip_sound_and_picture(app, tmp_path):
    """Item 142: "From a film" on the Modes tab. The dialog's logic (FilmCutForm, never a
    window) cuts a span of a synthetic lavfi film into the open mode's folder, and the tab
    makes the cut the mode's clip, end sound and screen picture, saves where each came
    from, and still says Ready to build. The mode keeps only the cut: nothing of the film
    is copied in."""
    import json
    import os
    import pytest
    from pinball_decryptor.core import audio
    from pinball_decryptor.gui.film_cut_dialog import FilmCutForm
    from pinball_decryptor.plugins.stern import mode_project as MP
    from tests.test_stern_film_cut import make_film

    ff = audio.find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    film = make_film(str(tmp_path / "films"), ff)
    if not film:
        pytest.skip("this ffmpeg cannot make the synthetic film")
    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode("FILM RUSH")
    assert "Nothing cut from a film yet" in panel._film_label.cget("text")
    assert all(str(b.cget("state")) == "normal" for b in panel._film_btns.values())
    folder = MP.mode_folder(str(project), slug)

    form = FilmCutForm.from_spec(panel._spec, "clip")
    form.film, form.start, form.length, form.crop = film, "0:02", "6", "fill"
    form.take_sound = form.take_still = True
    panel.apply_film_cut(form.apply(folder, ff))
    app.root.update()

    data = json.load(open(os.path.join(folder, "mode.json"), encoding="utf-8"))
    assert (data["clip"], data["clip_file"], data["end_sound"], data["screen_art"]) == (
        "file", "clip.mp4", "end.wav", "art.png")
    assert (data["clip_from"], data["clip_length"], data["sound_from"], data["art_from"]) == (2.0, 6.0, 2.0, 2.0)
    assert data["clip_source"] == data["sound_source"] == data["art_source"] == os.path.abspath(film)
    assert sorted(os.listdir(folder)) == ["art.png", "clip.mp4", "end.wav", "mode.json"]
    film_bytes = open(film, "rb").read()
    assert all(open(os.path.join(folder, n), "rb").read() != film_bytes for n in os.listdir(folder))
    assert "Ready to build" in panel._status.cget("text")
    assert (panel.v["clip"].get(), panel.v["end_mode"].get(), panel.v["art_mode"].get()) == ("file", "file", "file")
    assert panel._film_label.cget("text") == ("Clip: 6 s from 0:02. Sound: 6 s from 0:02. Picture: the "
                                              "frame at 0:02. Cut from synthetic_film.mp4.")
    assert "Video: clip.mp4" in panel._clip_label.cget("text")
    spec = MP.load(os.path.join(folder, "mode.json"))
    assert "synthetic_film" not in MP.runtime_cfg(spec, slug)


def _film_dialog_setup(app, tmp_path, monkeypatch):
    """Item 142 dialog tests: the synthetic film, a project with one mode open, and the
    dialog's staging folders kept under tmp_path so a leaked one is seen."""
    import tempfile
    import pytest
    from pinball_decryptor.core import audio
    from tests.test_stern_film_cut import make_film

    ff = audio.find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    film = make_film(str(tmp_path / "films"), ff)
    if not film:
        pytest.skip("this ffmpeg cannot make the synthetic film")
    stages = tmp_path / "stages"
    stages.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(stages))
    project = tmp_path / "proj"
    project.mkdir()
    app.window.write_assets_var.set(str(project))
    app.root.update()
    panel = app.window._modes_panel
    slug = panel.new_mode("FILM RUSH")
    return ff, film, stages, panel, slug


def _pump(app, cond, secs=60.0):
    import time
    end = time.time() + secs
    while time.time() < end:
        app.root.update()
        if cond():
            return True
        time.sleep(0.02)
    app.root.update()
    return bool(cond())


@pytest.mark.usefixtures("preview_modes_on")
def test_film_cut_dialog_probes_previews_and_cuts_on_workers(app, tmp_path, monkeypatch):
    """Item 142: the "From a film" DIALOG itself (an invisible window), driven like a
    person: a Preview pressed before the film's probe has answered does not strand the
    film line, the preview draws, Cut runs on a worker and makes the cut the mode's, the
    dialog closes, its timer stops and no staging folder is left behind."""
    import json
    import os
    from pinball_decryptor.plugins.stern import mode_project as MP

    ff, film, stages, panel, slug = _film_dialog_setup(app, tmp_path, monkeypatch)
    dlg = panel._open_film_cut("clip")
    assert dlg.form.film == "" and dlg.form.take_clip
    dlg.v["film"].set(film)
    dlg.v["start"].set("0:02")
    dlg.v["length"].set("6")
    dlg.v["crop"].set("fill")
    dlg.v["take_sound"].set(True)
    dlg.v["take_still"].set(True)
    dlg._probe()
    dlg._preview()                                   # before the probe answers
    assert _pump(app, lambda: dlg._preview_img is not None
                 and dlg._info.cget("text") not in ("", "Reading the film…"))
    assert dlg._info.cget("text").startswith("720x300, 23.976 fps, 0:10, sound 6 ch")
    assert dlg._status.cget("text") == "The frame at 0:02, as the clip will show it."

    dlg._cut()
    dlg.v["start"].set("0:09")                       # an edit during the cut changes nothing
    assert _pump(app, lambda: not dlg.win.winfo_exists())
    folder = MP.mode_folder(panel._open_project, slug)
    data = json.load(open(os.path.join(folder, "mode.json"), encoding="utf-8"))
    assert (data["clip_file"], data["end_sound"], data["screen_art"]) == ("clip.mp4", "end.wav", "art.png")
    assert (data["clip_from"], data["clip_length"], data["clip_crop"], data["art_crop"]) == (2.0, 6.0, "fill", "fill")
    assert sorted(os.listdir(folder)) == ["art.png", "clip.mp4", "end.wav", "mode.json"]
    assert "Ready to build" in panel._status.cget("text")
    assert _pump(app, lambda: False, 0.4) is False
    assert dlg._poll_job is None                     # the timer stopped with the window
    assert os.listdir(str(stages)) == []

    again = panel._open_film_cut("clip")             # reopens on the cut, its crop included
    assert (again.v["film"].get(), again.v["start"].get(), again.v["crop"].get()) == (
        os.path.abspath(film), "0:02", "fill")
    again.close()


@pytest.mark.usefixtures("preview_modes_on")
def test_film_cut_dialog_closed_during_a_cut_leaves_the_mode_as_it_was(app, tmp_path, monkeypatch):
    """Item 142: Cancel (or Escape, or the window's X) while a cut runs abandons it: the
    mode's files and mode.json are untouched and the staging folder goes. A cut already
    being moved into the mode when the dialog closes still lands, and the mode's file
    follows it."""
    import json
    import os
    import threading
    from pinball_decryptor.gui import film_cut_dialog as D
    from pinball_decryptor.gui.film_cut_dialog import FilmCutForm
    from pinball_decryptor.plugins.stern import mode_project as MP

    ff, film, stages, panel, slug = _film_dialog_setup(app, tmp_path, monkeypatch)
    folder = MP.mode_folder(panel._open_project, slug)
    first = FilmCutForm(film=film, start="0:02", length="6", take_sound=True)
    panel.apply_film_cut(first.apply(folder, ff))
    app.root.update()
    mode_json = os.path.join(folder, "mode.json")
    before = {n: open(os.path.join(folder, n), "rb").read() for n in ("clip.mp4", "end.wav", "mode.json")}

    gate = threading.Event()
    real_apply = FilmCutForm.apply

    def held_apply(self, mode_folder, ffmpeg=None):
        gate.wait(60)
        return real_apply(self, mode_folder, ffmpeg)
    monkeypatch.setattr(FilmCutForm, "apply", held_apply)
    dlg = panel._open_film_cut("clip")
    dlg.v["film"].set(film)
    dlg.v["start"].set("0:06")
    dlg.v["length"].set("3")
    worker = dlg._cut()
    _pump(app, lambda: False, 0.2)
    dlg.close()                                      # Cancel, mid-cut
    gate.set()
    worker.join(120)
    assert not worker.is_alive()
    _pump(app, lambda: False, 0.4)
    after = {n: open(os.path.join(folder, n), "rb").read() for n in ("clip.mp4", "end.wav", "mode.json")}
    assert after == before
    assert sorted(os.listdir(folder)) == ["clip.mp4", "end.wav", "mode.json"]
    assert os.listdir(str(stages)) == []
    assert dlg._poll_job is None

    # closed while the cut is already being moved in: it lands, and mode.json follows it
    monkeypatch.setattr(FilmCutForm, "apply", real_apply)
    moving, go = threading.Event(), threading.Event()
    real_commit = D.commit_cut

    def held_commit(result, mode_folder):
        moving.set()
        go.wait(60)
        return real_commit(result, mode_folder)
    monkeypatch.setattr(D, "commit_cut", held_commit)
    dlg2 = panel._open_film_cut("clip")
    dlg2.v["start"].set("0:06")
    dlg2.v["length"].set("3")
    worker = dlg2._cut()
    assert moving.wait(120)
    dlg2.close()
    go.set()
    worker.join(120)
    assert _pump(app, lambda: json.load(open(mode_json, encoding="utf-8"))["clip_from"] == 6.0)
    data = json.load(open(mode_json, encoding="utf-8"))
    assert (data["clip_from"], data["clip_length"]) == (6.0, 3.0)
    assert open(os.path.join(folder, "clip.mp4"), "rb").read() != before["clip.mp4"]
    assert os.listdir(str(stages)) == []
    _pump(app, lambda: False, 0.3)
    assert dlg2._poll_job is None


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_can_run_during_the_game_s_own_modes(app, tmp_path):
    """Item 140: "Can run during the game's own modes" is on for a new mode; unticking it
    saves stack false, the generated file says `stack no`, and reopening the mode shows
    it unticked while another mode keeps its own tick."""
    import json
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    boxes = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Checkbutton) and child.cget("text") == "Can run during the game's own modes":
                boxes.append(child)
            walk(child)
    walk(panel._editor)
    assert len(boxes) == 1

    slug = panel.new_mode("WAITS")
    assert panel.v["stack"].get() is True
    panel.v["stack"].set(False)
    panel.save_now()
    path = project / "modes" / slug / "mode.json"
    assert json.load(open(path, encoding="utf-8"))["stack"] is False
    assert "stack          no" in MP.runtime_cfg(MP.load(str(path)), slug)

    other = panel.new_mode("STACKS")
    assert other != slug and panel.v["stack"].get() is True
    panel._list.selection_clear(0, "end")
    panel._list.selection_set(panel._slugs.index(slug))
    panel._on_select()
    assert panel._slug == slug and panel.v["stack"].get() is False
    assert json.load(open(project / "modes" / other / "mode.json", encoding="utf-8"))["stack"] is True


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_lights_the_shots_and_sets_a_display_priority(app, tmp_path):
    """Item 157: the form's "Light the shots that score" (a colour and a pattern) and its "Display
    priority" land in mode.json and in the generated file as `light_shots` and `priority`; a new mode
    writes neither (the bytes of every mode before them), a reopened mode shows them, a bad priority is
    named, and the section's words are plain labels (legible in the dark theme)."""
    import json
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    box = panel._display_lights_box
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Label, ttk.Checkbutton)):
                texts.append(child.cget("text"))
            walk(child)
    walk(box)
    assert "Light the shots that score" in texts and "Display priority" in texts

    slug = panel.new_mode("LIT")
    path = project / "modes" / slug / "mode.json"
    cfg = MP.runtime_cfg(MP.load(str(path)), slug)
    assert "light_shots" not in cfg and "priority" not in cfg
    assert panel.v["light_shots_on"].get() is False and panel.v["priority"].get() == "0"
    assert str(box.winfo_children()[0].cget("state")) != "disabled"          # the open mode's form is live

    panel.v["light_shots_on"].set(True)
    panel.v["light_shots_color"].set("#FF6000")
    panel.v["light_shots_pattern"].set("Pulse")
    panel.v["priority"].set("180")
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert data["light_shots"] == "#FF6000" and data["light_shots_pattern"] == "pulse" and data["priority"] == 180
    cfg = MP.runtime_cfg(MP.load(str(path)), slug)
    assert "light_shots    ff6000 pulse\n" in cfg and "priority       180\n" in cfg

    other = panel.new_mode("PLAIN")
    assert other != slug and panel.v["light_shots_on"].get() is False and panel.v["priority"].get() == "0"
    panel._list.selection_clear(0, "end")
    panel._list.selection_set(panel._slugs.index(slug))
    panel._on_select()
    assert panel._slug == slug and panel.v["light_shots_on"].get() is True
    assert panel.v["light_shots_pattern"].get() == "Pulse" and panel.v["priority"].get() == "180"

    panel.v["priority"].set("300")
    panel.save_now()
    assert "display priority is 0 (none) to 255" in panel._status.cget("text")
    panel.v["priority"].set("0")
    panel.v["light_shots_on"].set(False)
    panel.save_now()
    cfg = MP.runtime_cfg(MP.load(str(path)), slug)
    assert "light_shots" not in cfg and "priority" not in cfg


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_writes_every_parameter(app, tmp_path):
    """Item 141: the Advanced section edits every parameter the tab hid - the award ladder,
    points per shot, an ending shot, a second clip, callouts at chosen seconds and how long
    the screen stays up - and each lands in mode.json and in the runtime file. It is
    collapsed until Show, and a mode that sets any of them opens with it shown."""
    import json
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode("PARAM TEST")
    assert panel._params_frame.grid_info() == {}                 # collapsed
    path = project / "modes" / slug / "mode.json"
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert (data["award_ladder"], data["shot_award"], data["end_shot"], data["clip_both"],
            data["callout_at"], data["restore_after"]) == ("rising", [], "", {}, [], 6)

    panel._params_show.set(True)
    panel._show_parameters()
    assert panel._params_frame.grid_info() != {}
    panel.v["seconds"].set("45")
    panel.v["award_ladder"].set("fixed")
    panel._shot_award_vars["Building"].set("5,000,000")
    panel._shot_award_vars["Godzilla target"].set("3000000")
    panel.v["end_shot"].set("Shield target left")
    panel.v["clip"].set("title")
    panel.v["clip_both"].set("title")
    panel.v["clip_both_title"].set("PARAM END")
    panel.v["clip_both_seconds"].set("3")
    (s0, c0), (s1, c1) = panel._callout_rows[:2]
    s0.set("30")
    c0.set("1291")
    s1.set("20")
    panel._pick_callout(c1, MP.callout_choices(MP.GODZILLA_PRO_1_15)[1][1])
    panel.v["restore_after"].set("8")
    panel.save_now()
    assert "Ready to build" in panel._status.cget("text")

    data = json.load(open(path, encoding="utf-8"))
    assert data["award_ladder"] == "fixed"
    assert data["shot_award"] == [["Building", 5000000], ["Godzilla target", 3000000]]
    assert data["end_shot"] == "Shield target left"
    assert data["clip_both"] == {"clip": "title", "title": "PARAM END", "seconds": 3.0}
    assert data["callout_at"] == [[30, 1291], [20, 1295]] and data["restore_after"] == 8
    cfg = MP.runtime_cfg(MP.load(str(path)), slug)
    for line in ("award_ladder   fixed", "shot_award     0x00400000 5000000",
                 "shot_award     0x00080000 3000000", "end_shot       0x80000000",
                 "clip_start     PadMode_param_test_Clip", "clip_end       PadMode_param_test_Clip2",
                 "callout_at     30 1291", "callout_at     20 1295", "restore_after  8"):
        assert line + "\n" in cfg, line

    # reopen: every control comes back, and the section opens shown
    panel._params_show.set(False)
    panel._show_parameters()
    panel._open(slug, MP.load(str(path)))
    assert panel._params_frame.grid_info() != {}
    assert panel.v["award_ladder"].get() == "fixed" and panel.v["end_shot"].get() == "Shield target left"
    assert panel._shot_award_vars["Building"].get() == "5000000" and panel._shot_award_vars["Big loop"].get() == ""
    assert (panel.v["clip_both"].get(), panel.v["clip_both_title"].get(), panel.v["clip_both_seconds"].get()) == (
        "title", "PARAM END", "3")
    assert [(s.get(), c.get()) for s, c in panel._callout_rows] == [("30", "1291"), ("20", "1295"), ("", ""), ("", "")]
    assert panel.v["restore_after"].get() == "8"

    # the same clip at both ends, and back to none
    panel.v["clip_both"].set("same")
    panel.v["end_shot"].set(panel.PARAM_NEVER)
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert data["clip_both"] == {"clip": "same"} and data["end_shot"] == ""
    panel.v["clip_both"].set("none")
    panel.save_now()
    assert json.load(open(path, encoding="utf-8"))["clip_both"] == {}


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_names_bad_values_and_keeps_what_it_cannot_show(app, tmp_path):
    """A bad value in the Advanced section is named in the status, not dropped; rows the form
    has no place for (callouts past its four rows, a shot this title does not name) are
    written back as they were; and with no mode open every Advanced field is greyed."""
    import json
    from tkinter import ttk
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel

    def fields():
        out = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Radiobutton)):
                    out.append(child)
                walk(child)
        walk(panel._params_frame)
        return out

    assert fields() and all(f.instate(["disabled"]) for f in fields())

    slug = panel.new_mode("BAD")
    assert not any(f.instate(["disabled"]) for f in fields())
    panel._shot_award_vars["Building"].set("lots")
    panel.v["seconds"].set("30")
    s0, c0 = panel._callout_rows[0]
    s0.set("45")
    c0.set("1291")
    panel.v["restore_after"].set("0")
    panel.v["clip"].set("none")
    panel.v["clip_both"].set("same")
    panel.save_now()
    status = panel._status.cget("text")
    for words in ("Building's own points", "45 seconds left", "1 to 60 seconds", "choose the first clip"):
        assert words in status, words
    assert json.load(open(project / "modes" / slug / "mode.json", encoding="utf-8"))["shot_award"] == [
        ["Building", "lots"]]

    path = project / "modes" / slug / "mode.json"
    data = json.load(open(path, encoding="utf-8"))
    data.update(callout_at=[[25, 1], [24, 2], [23, 3], [22, 4], [21, 5]], shot_award=[["Spinner", 7]],
                restore_after=6, clip_both={})
    json.dump(data, open(path, "w", encoding="utf-8"))
    panel._open(slug, MP.load(str(path)))
    panel._shot_award_vars["Building"].set("")
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert data["callout_at"] == [[25, 1], [24, 2], [23, 3], [22, 4], [21, 5]]
    assert data["shot_award"] == [["Spinner", 7]]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_keeps_hand_edited_values_until_changed(app, tmp_path):
    """Item 141: a hand-edited mode.json the Advanced section cannot show (an unknown ladder,
    end shot or second clip, a shot name that is not text, a second award for one shot, a
    callout row that is not [seconds, id]) opens without an error, is written back as it was,
    and is named in the status; setting that control replaces it. The form shows a shot's
    FIRST award, the one the runtime pays. restore_after is checked only with the mode's own
    screen, the only time it is written."""
    import json
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode("RAW")
    panel.save_now()
    path = project / "modes" / slug / "mode.json"
    data = json.load(open(path, encoding="utf-8"))
    data.update(award_ladder="steep", end_shot=["Shield target left"], clip_both={"clip": "loop"},
                shot_award=[["Building", 5], ["Building", 7], [["x"], 3]],
                callout_at=[[25, 1], "bad", [24, 2]])
    json.dump(data, open(path, "w", encoding="utf-8"))
    panel._open(slug, MP.load(str(path)))
    assert (panel.v["award_ladder"].get(), panel.v["end_shot"].get(), panel.v["clip_both"].get()) == (
        "rising", panel.PARAM_NEVER, "none")
    assert panel._shot_award_vars["Building"].get() == "5"
    assert [(s.get(), c.get()) for s, c in panel._callout_rows] == [("25", "1"), ("24", "2"), ("", ""), ("", "")]
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert (data["award_ladder"], data["end_shot"], data["clip_both"]) == (
        "steep", ["Shield target left"], {"clip": "loop"})
    assert data["shot_award"] == [["Building", 5], ["Building", 7], [["x"], 3]]
    assert data["callout_at"] == [[25, 1], [24, 2], "bad"]
    status = panel._status.cget("text")
    for words in ("rising or fixed", "to end the mode", "same clip, a title card", "[shot, points]",
                  "Building has its own points twice", "[seconds left, id]"):
        assert words in status, words

    panel.v["award_ladder"].set("fixed")
    panel.v["end_shot"].set(panel.PARAM_NEVER)
    panel.v["clip_both"].set("none")
    panel.save_now()
    data = json.load(open(path, encoding="utf-8"))
    assert (data["award_ladder"], data["end_shot"], data["clip_both"]) == ("fixed", "", {})

    # restore_after does nothing without the mode's own screen, so it does not block a build
    data.update(shot_award=[], callout_at=[])
    json.dump(data, open(path, "w", encoding="utf-8"))
    panel._open(slug, MP.load(str(path)))
    panel.v["restore_after"].set("0")
    panel.save_now()
    assert "1 to 60 seconds" in panel._status.cget("text")
    panel.v["screen"].set(False)
    panel.save_now()
    assert "1 to 60 seconds" not in panel._status.cget("text")


def _stock_modes_project(tmp_path, name="godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"):
    import json
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".extract_source.json").write_text(json.dumps(
        {"input_path": "D:\\cards\\" + name, "input_name": name, "size": 1, "mtime": 1}),
        encoding="utf-8")
    return project


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_lists_the_games_own_modes_and_stages_like_defaults(app, tmp_path):
    """Item 145: the Modes tab lists the timers and awards of the modes the game shipped
    with (from item 144's table for the project's build), and Set / Stock / All to stock
    stage them in the project's .staged_changes.json: a word under "stock_modes", an
    operator setting under Defaults' own "settings". A number the game computes in code
    stays read-only and says why."""
    from pinball_decryptor.core import staged_changes
    w = app.window
    project = _stock_modes_project(tmp_path)
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    tree = panel._stock_tree
    assert "godzilla_pro 1.15" in panel._stock_msg.cget("text")
    rows = tree.get_children()
    assert "12.start.caward_add" in rows and "12.timer.seconds" in rows
    assert "12.timer.v57" not in rows                      # one row per operator setting
    assert tree.item("12.start.caward_add", "text") == "Battle vs Ebirah"
    assert tree.set("12.start.caward_add", "value") == "250,000"

    # an award: select, type, Set
    tree.selection_set("12.start.caward_add")
    app.root.update()
    panel._stock_value.set("777,777")
    panel._stock_set_btn.invoke()
    data = staged_changes.load(str(project))
    assert data["stock_modes"] == {"build": "godzilla_pro 1.15",
                                   "values": {"12.start.caward_add": 777777},
                                   "touched": ["12.start.caward_add"]}
    assert tree.set("12.start.caward_add", "value").startswith("777,777")
    # a timer that is an operator setting: Defaults' settings key
    tree.selection_set("12.timer.seconds")
    app.root.update()
    assert "Defaults tab" in panel._stock_note.cget("text")
    # what the emulator measured (item 145 runs 2-3): a machine at the default follows it
    assert "still on the game's default takes the new one" in panel._stock_note.cget("text")
    assert "still on the game's default takes the new one" in panel.STOCK_TIP
    panel._stock_value.set("30")
    panel._stock_set_btn.invoke()
    assert staged_changes.load(str(project))["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}
    panel._stock_value.set("99")                           # outside the game's own range
    panel._stock_set_btn.invoke()
    assert "between 30 and 70" in panel._stock_note.cget("text")
    assert staged_changes.load(str(project))["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}

    # code stays read-only, with the reason
    tree.selection_set("12.shot.caward_add")
    app.root.update()
    assert str(panel._stock_set_btn.cget("state")) == "disabled"
    assert "Read-only" in panel._stock_note.cget("text") and "code" in panel._stock_note.cget("text")

    # Stock on one row, then All to stock
    tree.selection_set("12.start.caward_add")
    app.root.update()
    panel._stock_reset_btn.invoke()
    assert staged_changes.load(str(project))["stock_modes"]["values"] == {}
    panel._stock_all_btn.invoke()
    data = staged_changes.load(str(project))
    assert "settings" not in data and data["stock_modes"]["values"] == {}


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_says_when_the_build_has_no_table(app, tmp_path):
    w = app.window
    project = _stock_modes_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw")
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    assert "doesn't know" in panel._stock_msg.cget("text")
    assert "turtles_pro 1.59.0" in panel._stock_msg.cget("text")
    assert not panel._stock_tree.get_children()
    assert str(panel._stock_set_btn.cget("state")) == "disabled"


@pytest.mark.usefixtures("preview_modes_on")
def test_write_scan_lists_the_games_own_mode_changes(app, tmp_path, manufacturers_by_key):
    """Item 145: a staged stock-mode number is a pending Write row (the Write computes it
    from the sidecar, the MD5 scan can't see it), the operator setting too, and staging
    moves the Write fingerprint."""
    from pinball_decryptor.plugins.stern import stock_modes as SM
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    project = _stock_modes_project(tmp_path)
    w.write_assets_var.set(str(project))
    app.root.update()
    fp0 = w._current_write_fingerprint()
    build = SM.table_for_project(str(project))
    SM.stage(str(project), build, build.number("23.start.caward_add"), 555555)
    SM.stage(str(project), build, build.number("12.timer.seconds"), 30)
    assert w._current_write_fingerprint() != fp0
    sid = w._write_preview_scan_id
    n = w._add_pending_preview_rows(str(project), sid)
    assert n >= 2
    rows = [r[0] for r in w._write_preview_rows if r[2] == "Pending (game's own modes)"]
    assert "Tesla Strike start award: 250,000 -> 555,555" in rows
    assert "Battle vs Ebirah timer: 60 -> 30" in rows


@pytest.mark.usefixtures("preview_modes_on")
def test_defaults_form_adopts_a_timer_the_modes_tab_staged(app, tmp_path):
    """The Defaults form's autostage REPLACES the staged settings from its own fields, so
    a timer staged on the Modes tab is put into the form's field (item 145) - else the next
    Defaults edit would drop it."""
    import tkinter as tk
    from pinball_decryptor.plugins.stern import stock_modes as SM
    w = app.window
    project = _stock_modes_project(tmp_path)
    w.write_assets_var.set(str(project))
    app.root.update()
    var = tk.IntVar(value=60)
    w._settings_rows = [{"name": "AD_BATTLE_VS_EBIRAH_TIMER", "label": "Ebirah timer",
                         "kind": "int", "var": var, "default": 60, "min": 30, "max": 70}]
    w._settings_fill_all_tree = lambda: None
    build = SM.table_for_project(str(project))
    w._modes_panel.refresh_stock_modes()
    w._modes_panel.stage_stock_value("12.timer.seconds", 45)
    assert var.get() == 45
    assert w._settings_changes() == {"AD_BATTLE_VS_EBIRAH_TIMER": 45}
    w._modes_panel.stage_stock_value("12.timer.seconds", 60)
    assert var.get() == 60 and w._settings_changes() == {}
    assert build is not None


@pytest.mark.usefixtures("preview_modes_on")
def test_revert_all_and_defaults_only_settings_with_the_games_own_modes(
        app, tmp_path, manufacturers_by_key):
    """Item 145 fix round 2. A setting staged only on the Defaults tab is not a Write row of
    the game's own modes (Defaults applies it after the next build, as before). Revert all
    changes drops every staged number but keeps the project managing the game's own modes,
    so the next Write can put its card back to stock."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import stock_modes as SM
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    project = _stock_modes_project(tmp_path)
    w.write_assets_var.set(str(project))
    app.root.update()
    staged_changes.save(str(project), {"settings": {"AD_BATTLE_VS_EBIRAH_TIMER": 30}})
    w._add_pending_preview_rows(str(project), w._write_preview_scan_id)
    assert not [r for r in w._write_preview_rows if r[2] == "Pending (game's own modes)"]

    build = SM.table_for_project(str(project))
    SM.stage(str(project), build, build.number("12.start.caward_add"), 777777)
    w.clear_replace_assignments(str(project))
    data = staged_changes.load(str(project))
    assert data == {"stock_modes": {"build": "godzilla_pro 1.15", "values": {},
                                    "touched": ["12.start.caward_add"]}}
    assert SM.manages(str(project)) and SM.pending_count(str(project)) == 0


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_starts_and_ends_on_an_event(app, tmp_path):
    """Item 147: "Starts on: its shot / an event" and "Ends on: the drain / the clock only /
    an event". The form shows events in words, the file keeps their names, and the runtime
    file an event start generates has no trigger line."""
    import json
    from pinball_decryptor.plugins.stern import mode_project as MP

    w = app.window
    project = tmp_path / "proj"
    project.mkdir()
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    slug = panel.new_mode("EVENT RUSH")
    assert panel.v["starts_kind"].get() == "shot" and panel.v["ends_kind"].get() == "drain"
    panel.v["starts_kind"].set("event")
    panel.v["start_event"].set(MP.EVENT_LABELS["ball_start"])
    panel.v["ends_kind"].set("event")
    panel.v["end_event"].set(MP.EVENT_LABELS["multiball_end"])
    panel.save_now()
    data = json.load(open(project / "modes" / slug / "mode.json", encoding="utf-8"))
    assert data["starts_on"] == "event ball_start" and data["ends_on"] == "event multiball_end"
    assert "Ready to build" in panel._status.cget("text")
    cfg = MP.runtime_cfg(MP.load(str(project / "modes" / slug / "mode.json")), slug)
    assert "starts_on      event ball_start" in cfg
    assert not [line for line in cfg.splitlines() if line.startswith("trigger ")]

    panel.v["ends_kind"].set("clock")
    panel.save_now()
    assert json.load(open(project / "modes" / slug / "mode.json", encoding="utf-8"))["ends_on"] == "clock"
    # reopening the mode shows what was saved
    panel._slug = None
    panel.refresh(select=slug)
    assert panel.v["starts_kind"].get() == "event"
    assert panel.v["start_event"].get() == MP.EVENT_LABELS["ball_start"]
    assert panel.v["ends_kind"].get() == "clock"
    panel.v["start_event"].set("")
    panel.save_now()
    assert "Pick the event that starts" in panel._status.cget("text")


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
    # The fixture card is NAMED turtles_le but its on-card game folder is
    # turtles_pro, so the edition comes back Pro — the card outranks the file
    # name (info.resolve_version).  Its sidx carries no version, so the
    # version is still the name's.
    assert fw["Version"].startswith("1.23.0") and fw["Edition"] == "Pro"
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


def test_scene_browser_saves_an_animated_scene_as_mp4(app, tmp_path,
                                                      monkeypatch):
    """"Save preview…" exports a scene that moves as an MP4 (a tester: "it
    would be cool to have the option to export the rendered scenes as MP4").

    The two things worth pinning: MP4 is what an animated scene offers and
    defaults to, and the export covers the WHOLE scene — the canvas only ever
    plays the first ``_MAX_PREVIEW_FRAMES``, and a GIF of a 1900-frame loop is
    not the answer.  ffmpeg itself is covered in test_scene_export_mp4."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    import json
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.gui import scene_browser as sb_mod
    from pinball_decryptor.plugins.stern import scene_render

    _make_extract(tmp_path)
    # 80 frames: more than the 60 the preview renders, so "all of it" and
    # "what is on the canvas" are different numbers.
    n_all = 80
    assert n_all > sb_mod._MAX_PREVIEW_FRAMES
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 30.0], "unplaced": 0, "offstage": 0, "texts": [],
        "sprites": [{"name": "a", "x": 0, "y": 0, "image": "a.png",
                     "frames": ["f%d.png" % i for i in range(n_all)]}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)

    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser
    sb._tree.selection_set("/g/scene1")
    sb._on_select()
    # _on_select starts a real render on a worker; this test flushes the event
    # queue later for its own after() hop, so retire that render the way the
    # window itself does (its result carries the old token and is discarded).
    app.root.update()
    sb._preview_token += 1
    frames = [Image.new("RGB", (320, 180), (i, 0, 0)) for i in range(60)]
    sb._show_preview(sb._preview_token, frames,
                     layout["/g/scene1/scene.radium"])
    assert sb._fps_shown is True                    # it moves
    # the caption promises the export, and says how many frames it will hold
    # (on the "?" button: the visible line is one sentence of it)
    assert "writes all 80 to MP4" in sb._caption_tip.text

    asked = {}

    def fake_dialog(**kw):
        asked.update(kw)
        return str(tmp_path / "out.mp4")

    monkeypatch.setattr(sb_mod.filedialog, "asksaveasfilename", fake_dialog)

    # The worker runs inline so the export is deterministic here.
    class _SyncThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(sb_mod, "threading",
                        type("_T", (), {"Thread": _SyncThread}))

    got = {}

    def fake_encode(frames_iter, path, fps=12.0, progress=None):
        n = 0
        for _f in frames_iter:               # drains the generator lazily
            n += 1
            if progress is not None:
                progress(n)
        got.update(path=path, fps=fps, n=n)
        return n

    monkeypatch.setattr(sb_mod.video, "encode_frames_to_mp4", fake_encode)

    sb._save_preview()
    app.root.update()                        # flush the after() hop

    # MP4 is offered first and is the default extension for a moving scene
    assert asked["defaultextension"] == ".mp4"
    assert asked["filetypes"][0] == ("MP4 video", "*.mp4")
    assert ("Animated GIF", "*.gif") in asked["filetypes"]
    assert asked["initialfile"].endswith(".mp4")
    # ...and the export is the whole scene at its own rate, not the 60 frames
    # the canvas is playing
    assert got["n"] == n_all
    assert got["fps"] == 30.0
    assert got["path"] == str(tmp_path / "out.mp4")
    assert sb._export is None                       # finished, not stuck
    assert str(sb._save_btn.cget("state")) == "normal"
    assert "Saved out.mp4" in sb._preview_lbl.cget("text")
    assert "80 frames at 30 fps" in sb._preview_lbl.cget("text")

    # a failed encode (no ffmpeg on this machine) says so and leaves the
    # button usable rather than disabled forever
    errs = []
    monkeypatch.setattr(sb_mod.messagebox, "showerror",
                        lambda *a, **k: errs.append(a))

    def boom(*_a, **_k):
        raise RuntimeError("ffmpeg is needed to write an MP4")

    monkeypatch.setattr(sb_mod.video, "encode_frames_to_mp4", boom)
    sb._save_preview()
    app.root.update()
    assert len(errs) == 1 and "ffmpeg" in errs[0][1]
    assert sb._export is None
    assert str(sb._save_btn.cget("state")) == "normal"
    assert "Could not write out.mp4" in sb._preview_lbl.cget("text")

    # While one is being written the button cancels it (a long scene is a
    # minute of rendering), and a cancelled export leaves no half-length file
    # behind — ffmpeg closes a truncated stream cleanly, so one would exist.
    partial = tmp_path / "partial.mp4"
    partial.write_bytes(b"\x00" * 8)
    state = sb._export = {"cancel": False}
    sb._save_btn.configure(text="Cancel")
    sb._save_preview()
    assert state["cancel"] is True
    sb._export_done(state, str(partial), 12, 30.0, None)
    assert not partial.exists()
    assert "Stopped" in sb._preview_lbl.cget("text")
    assert str(sb._save_btn.cget("text")) == "Save preview…"
    assert str(sb._save_btn.cget("state")) == "normal"

    # a stale worker's result (its state superseded) is ignored outright
    sb._export_done({"cancel": False}, str(tmp_path / "x.mp4"), 5, 30.0, None)
    assert "Stopped" in sb._preview_lbl.cget("text")

    # a still scene offers no video at all — an MP4 of one frame is a picture
    still = dict(layout["/g/scene1/scene.radium"], sprites=[])
    sb._show_preview(sb._preview_token, [frames[0]], still)
    monkeypatch.setattr(sb_mod.filedialog, "asksaveasfilename", fake_dialog)
    sb._save_preview()
    assert asked["defaultextension"] == ".png"
    assert [t[0] for t in asked["filetypes"]] == ["PNG image"]

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


def test_a_tooltip_follows_the_cursor_and_never_sits_under_it(app):
    """David: "all tooltips should follow the cursor".  A tip pinned under a
    wide widget explains the WIDGET while the cursor is on one small part of
    it; following the pointer is what makes one tooltip able to say where
    you actually are.  It must never land under the pointer, or it would eat
    the click being lined up."""
    import tkinter as tk
    from tkinter import ttk
    from pinball_decryptor.gui.widgets import _Tooltip

    top = tk.Toplevel(app.root)
    top.geometry("500x200+120+120")
    lbl = ttk.Label(top, text="a wide row of a table")
    lbl.pack(fill=tk.X)
    tip = _Tooltip(lbl, "what this cell is", lambda: "dark")
    app.root.update_idletasks()

    class _Ev:
        def __init__(self, x, y):
            self.x_root, self.y_root = x, y

    def where(ev):
        tip._moved(ev)
        app.root.update_idletasks()
        t = tip._tip
        return t.winfo_rootx(), t.winfo_rooty()

    tip._show(_Ev(300, 300))
    app.root.update_idletasks()
    first = (tip._tip.winfo_rootx(), tip._tip.winfo_rooty())
    # the pointer moves along the row: the tip goes with it
    second = where(_Ev(420, 300))
    assert second[0] > first[0]
    # ...and it is offset clear of the pointer, never on top of it
    assert second[0] > 420 and second[1] > 300
    tip.hide()
    # with no pointer at all (a caller-driven show) it still falls back to
    # the widget, which is what the "side" placement above relies on
    assert tip._at is None
    top.destroy()


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


def test_font_studio_outline_scope_covers_every_restyled_size(app, tmp_path,
                                                              monkeypatch):
    """Removing the outline has to reach the scenes of every size Apply just
    restyled, not only the one size the outline is paired to.

    An outline font pairs with exactly ONE size of its typeface, but Apply
    restyles all of them, so pairing used to decide the scope: on a tester's
    TMNT the OUTLINE6 companion was narrowed to the 1 scene it shared with the
    94px row while the typeface he had restyled in full is drawn in all 25 of
    that outline's scenes, and 24 screens kept the old border.  The scope is
    still an INTERSECTION, so a scene that draws the outline without any of
    those body rows keeps it."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("body")
    fs._on_select()
    fo = fs._current_font()
    comp = fs._companion(fo)
    assert comp["key"] == "ok"

    # "body2" is the same typeface in /g/scene1 too; make it a second scene so
    # the union is bigger than the paired row's own overlap
    tex = tmp_path / "images" / "scene_textures"
    rows = (tex / "radium_images.txt").read_text(encoding="utf-8")
    rows += ("scene_textures/radimg_T_8x8_00000005.png\t/g/scene5/scene.radium"
             "\t100\t256\t32\t32\t5\n")
    (tex / "radium_images.txt").write_text(rows, encoding="utf-8")
    fs.reload("body")
    fs._tree.selection_set("body")
    fs._on_select()
    fo = fs._current_font()
    assert set(fr.scenes_for_font(str(tmp_path), fs._by_key["body2"])) == {
        "/g/scene1/scene.radium", "/g/scene5/scene.radium"}

    fs._all_sizes_var.set(True)
    fs._comp_var.set(fs_mod._COMP_CLEAR)
    fs._pending[fo["key"]] = ({0x41: Image.new("RGBA", (20, 34), (9, 9, 9, 255))},
                              34, [], "x.ttf")
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._apply()

    scoped = fr.get_font_scope(str(tmp_path), fs._companions["body"])
    assert scoped == ["/g/scene1/scene.radium", "/g/scene5/scene.radium"], \
        "the outline must go from every scene the restyled sizes are drawn in"

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

    # the tick names the real count and is hidden for a one-off typeface.  It
    # says "copies", not "sizes": a typeface is baked once per size AND once
    # per scene, so its other rows are often the same size (Godzilla lists
    # HelveticaNeueBlack three times at 102px) and "sizes" told a user who
    # wanted one size that he could safely untick it.
    assert fs._same_typeface(fs._current_font())[0]["key"] == "body2"
    assert "other 1 copy" in fs._all_sizes_cb.cget("text")
    assert fs._all_sizes_cb.winfo_manager() != ""

    sib = fs._by_key["body2"]
    before = open(sib["glyphs"][0x41]["abs"], "rb").read()
    fs._ttf_paths["body"] = _system_ttf()
    fs._rasterize()
    assert fs._all_sizes_var.get() is True
    fs._apply()
    after = open(sib["glyphs"][0x41]["abs"], "rb").read()
    assert after != before, "the other size should have been restyled too"
    assert "1 more copy" in fs._status.cget("text")

    # Revert all puts the whole project back, which is how you start over
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._revert_all()
    assert "restored to stock" in fs._status.cget("text")
    a = np.asarray(Image.open(sib["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert a.shape[:2] == (sib["glyphs"][0x41]["h"], sib["glyphs"][0x41]["w"])

    fs._close()
    app.root.update()


def test_font_studio_blank_reaches_every_copy_of_a_typeface(app, tmp_path,
                                                            monkeypatch):
    """Blanking an outline font has to reach every ROW of that typeface.

    A typeface is baked into its own atlas per size AND per scene, so it fills
    several rows here that nothing on screen tells apart (Godzilla lists
    HelveticaNeueBlack three times at 102px, 113 letters, 5 scenes — different
    scenes each).  Blank used to erase exactly the row that was selected, so a
    tester who "went through the font list and blanked the outlines" still had
    the old outline on every scene the other rows cover, and read the font's
    short scene list as proof the scenes weren't being enumerated."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_outline_extract(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio

    # "ok" and "far" are the same outline typeface in different scenes
    fs._tree.selection_set("ok")
    fs._on_select()
    assert [f["key"] for f in fs._same_typeface(fs._current_font())] == ["far"]
    # ...and the list finally says so, instead of showing two identical rows
    assert "copy 1 of 2" in fs._tree.item("ok", "values")[0]
    assert "copy 2 of 2" in fs._tree.item("far", "values")[0]
    assert "further copies of a font already listed" in fs._hint.cget("text")

    def ink(key):
        fo = fs._by_key[key]
        a = np.asarray(Image.open(fo["glyphs"][0x41]["abs"]).convert("RGBA"))
        return int(a[..., 3].max())

    assert ink("ok") > 0 and ink("far") > 0
    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._blank()
    assert ink("ok") == 0
    assert ink("far") == 0, "the other copy still draws the old outline"
    assert "1 more copy" in fs._status.cget("text")

    # ...and one Undo brings both back — reaching further must not make the
    # step back smaller
    fs._undo_last()
    assert ink("ok") > 0 and ink("far") > 0

    # with the tick off it is the selected row only, which is the old behaviour
    # and still the way to blank an outline out of one place
    fs._all_sizes_var.set(False)
    fs._blank()
    assert ink("ok") == 0
    assert ink("far") > 0

    fs._close()
    app.root.update()


def test_font_studio_revert_reaches_as_far_as_the_blank_did(app, tmp_path,
                                                            monkeypatch):
    """Revert follows the same tick as Blank and Apply.  Anything else means
    "blank every copy" is one click and the way back is 94."""
    pytest = __import__("pytest")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.gui import font_studio as fs_mod

    _make_outline_extract(tmp_path)
    # the fixture's atlases are empty, and revert re-cuts the letters FROM the
    # atlas — give the two outline copies something to come back to
    tex = tmp_path / "images" / "scene_textures"
    for aid in ("0002", "0004"):
        Image.fromarray(np.full((32, 32, 4), 255, np.uint8), "RGBA").save(
            str(tex / ("radimg_T_8x8_0000%s.png" % aid)))
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_font_studio()
    fs = w._font_studio
    fs._tree.selection_set("ok")
    fs._on_select()

    def ink(key):
        fo = fs._by_key[key]
        a = np.asarray(Image.open(fo["glyphs"][0x41]["abs"]).convert("RGBA"))
        return int(a[..., 3].max())

    monkeypatch.setattr(fs_mod.messagebox, "askyesno", lambda *a, **k: True)
    fs._blank()
    assert ink("ok") == 0 and ink("far") == 0
    fs._revert()
    assert ink("ok") > 0
    assert ink("far") > 0, "the copy blanked with it has to come back with it"
    assert "all 2 copies" in fs._status.cget("text")

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
    pane._render_poster = (lambda pos, fallbacks=None, sampling=False:
                           asked.append((pos, sampling)))

    # Black frame + somewhere else to look -> try the next spot, silently,
    # still flagged as part of the hunt for a representative frame.
    pane._show_poster(_png((0, 0, 0)), pane._render_id, (2.5, 7.5),
                      sampling=True)
    assert asked == [(2.5, True)]
    assert pane.canvas.find_withtag("note") == ()

    # Black everywhere we looked -> a note, not an empty pane.
    pane._show_poster(_png((0, 0, 0)), pane._render_id, (), sampling=True)
    notes = pane.canvas.find_withtag("note")
    assert notes
    assert "Every frame sampled is black" in \
        pane.canvas.itemcget(notes[0], "text")

    # A frame with picture in it just draws, no note.
    pane._show_poster(_png((10, 90, 200)), pane._render_id, (2.5,))
    assert pane.canvas.find_withtag("frame")
    assert pane.canvas.find_withtag("note") == ()


def test_video_poster_black_scrub_speaks_only_for_that_frame(app):
    """A scrub asks for ONE frame at a position the user chose.  Landing on a
    fade-in must not accuse the whole clip of being black: a tester got that
    verdict on a replacement that had just played fine (batch 29)."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    pane._show_poster(_png((0, 0, 0)), pane._render_id)   # no fallbacks, scrub
    notes = pane.canvas.find_withtag("note")
    assert notes
    text = pane.canvas.itemcget(notes[0], "text")
    assert "This frame is black" in text
    assert "Every frame" not in text


def test_video_pane_rewind_reposters_a_representative_frame(app):
    """Stopping (■) and playing a clip to the end both rewind to 0:00, and
    frame 0 is black on any clip that fades in — which replaced the picture
    with the all-black note the moment a tester's clip finished playing.  Both
    paths re-run the same sampling load() does."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    asked = []
    pane._render_poster = (
        lambda pos, fallbacks=None, sampling=False:
        asked.append((pos, tuple(fallbacks or ()), sampling)))

    pane.pos = 6.0
    pane.stop_to_start()
    assert pane.pos == 0.0                      # playhead still rewinds
    pos, fallbacks, sampling = asked[-1]
    assert pos == pytest.approx(5.0)            # mid-clip, not 0.0
    assert fallbacks and sampling               # ...more spots to try

    # The end-of-playback path lands in the same place.
    asked.clear()
    pane.playing = True
    pane.dur = 10.0
    pane.pos = 10.5                             # clock ran past the end
    pane._tick()
    assert not pane.playing
    assert pane.pos == 0.0
    assert asked[-1][0] == pytest.approx(5.0)


def test_video_poster_does_not_seek_past_a_short_clip(app):
    """463 of Batman's 6331 clips are under 0.2 s (a one-frame still is
    1/30 s).  The blind 0.5 s offset landed past their last frame, ffmpeg
    returned nothing, and the pane told a field reporter his file couldn't be
    decoded — for a clip that is perfectly fine, just short."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    asked = []
    pane._render_poster = (lambda pos, fallbacks=None, sampling=False:
                           asked.append((pos, tuple(fallbacks or ()))))

    pane.dur = 0.033333                       # one frame at 30 fps
    pane._render_representative_poster()
    assert asked[-1] == (0.0, ())             # its first frame IS the clip

    # Duration unknown: still guess 0.5 s in, but frame 0 now backs it up.
    asked.clear()
    pane.dur = 0.0
    pane._render_representative_poster()
    assert asked[-1] == (0.5, (0.0,))

    # A normal clip keeps its mid-clip sampling, 0.0 as the last resort.
    asked.clear()
    pane.dur = 10.0
    pane._render_representative_poster()
    assert asked[-1] == (pytest.approx(5.0),
                         pytest.approx((2.5, 7.5, 0.8, 0.0)))


def test_video_poster_tries_the_next_spot_when_a_seek_decodes_nothing(app):
    """A duration that overstates the clip makes ffmpeg return no frame at
    all.  That is a bad offset, not a bad file — keep sampling, and only
    blame ffmpeg once frame 0 itself has come back empty."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    asked = []
    pane._render_poster = (lambda pos, fallbacks=None, sampling=False:
                           asked.append((pos, sampling)))

    pane._show_poster(None, pane._render_id, (2.5, 0.0), sampling=True)
    assert asked == [(2.5, True)]
    assert pane.canvas.find_withtag("note") == ()


def test_video_pane_time_readout_shows_a_sub_second_clip(app):
    """"0:00 / 0:00" under a clip that plays is the same "this is empty"
    impression the list's Length column gave (a field report)."""
    pytest.importorskip("PIL")
    pane = _poster_pane(app)
    pane.dur, pane.pos = 0.876, 0.4
    pane._update_time()
    assert pane.time_var.get() == "0:00.400 / 0:00.876"

    # The playback clock overruns the end before _tick stops it; the readout
    # must never claim more than the clip holds.
    pane.pos = 1.2
    pane._update_time()
    assert pane.time_var.get() == "0:00.876 / 0:00.876"

    # A clip of a second or more reads exactly as before.
    pane.dur, pane.pos = 65.0, 12.9
    pane._update_time()
    assert pane.time_var.get() == "0:12 / 1:05"


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


# --- Spike 1 Default Settings tab (operator adjustments from the game ELF) ---

_SPIKE1_CARD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "images", "Stern", "spike1", "ghostbusters_le-1_17.iso")


@pytest.mark.skipif(not os.path.isfile(_SPIKE1_CARD),
                    reason="Spike 1 sample card not present")
def test_settings_tab_loads_spike1_card(app, manufacturers_by_key):
    """The Default Settings tab decodes a Spike 1 card's operator adjustments
    (from the game ELF) into the all-settings list — the read side of Spike 1
    settings parity."""
    a = app
    a._on_manufacturer_change(manufacturers_by_key["stern"])
    a.root.update()
    w = a.window
    # the REAL workflow: the Stern plugin on its SPIKE 1 era (not the default
    # Spike 2), so the era badge, tab strip and capabilities are Spike 1's.
    w._on_era_badge_click("spike1")
    a.root.update()
    assert getattr(a._current_mfr, "current_era", "") == "spike1"
    assert getattr(a._current_mfr.capabilities, "settings_editor", False)
    w.settings_image_var.set(_SPIKE1_CARD)
    w._settings_open_image()
    # the worker is threaded + after()-polled; pump until it lands
    import time
    t0 = time.time()
    while time.time() - t0 < 30 and not getattr(w, "_settings_all_rows", None):
        a.root.update()
        time.sleep(0.05)
    assert w._settings_spike1 is True
    assert w._settings_table is None
    rows = w._settings_all_rows
    assert len(rows) > 100                      # GBLE carries ~175 adjustments
    r0 = rows[0]
    assert set(r0) >= {"id", "name", "label", "default", "min", "max", "step"}
    assert r0["name"].startswith("AD_")         # stable synthetic key
    # a real firmware label made it through (not a raw AD_ id)
    assert any("VOLUME" in r["label"].upper() or "COIN" in r["label"].upper()
               for r in rows)


def test_audio_advanced_offers_longer_replacements_and_wires_them_up(
        app, manufacturers_by_key, monkeypatch):
    """The "Allow replacements longer than the original" option exists, says
    it is unverified on a machine, and OK carries it out to the env var the
    engine gates on.

    The dialog is the ONLY way a user can turn this on, and the engine reads
    it from os.environ (spawned encode workers inherit that, nothing else), so
    a dialog that builds but doesn't wire the box up would look completely
    normal and silently keep trimming."""
    import os

    import tkinter as _tk_mod

    def _descendants(w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out += _descendants(c)
        return out

    win = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)

    win._open_audio_advanced()
    app.root.update()
    dlg = [c for c in win.root.winfo_children()
           if isinstance(c, _tk_mod.Toplevel)][-1]
    kids = _descendants(dlg)
    texts = [str(w.cget("text")) for w in kids if "text" in w.keys()]
    box = [t for t in texts if "longer than the original" in t]
    assert box, "the longer-replacements checkbox is missing"
    assert any("hardware-unverified" in t for t in box)
    assert any("no real machine has booted" in t for t in texts), (
        "the explanation must say no machine has booted one")

    cb = next(w for w in kids
              if "text" in w.keys()
              and "longer than the original" in str(w.cget("text")))
    assert not dlg.getvar(cb.cget("variable")), "it must default to off"
    cb.invoke()
    ok = next(w for w in kids if "text" in w.keys()
              and str(w.cget("text")) == "OK")
    ok.invoke()
    app.root.update()
    assert os.environ.get("PAD_STERN_AUDIO_GROW") == "1"
    assert app._settings["audio_advanced"]["audio_grow"] is True
    # Leave a clean slate for later tests.
    app._on_audio_advanced_change({})
    assert "PAD_STERN_AUDIO_GROW" not in os.environ


# --------------------------------------------------------------------------
# PAD-128 — clearing replacement picks in bulk.  DragonRR, 2026-09-11:
# "We could do with a 'clear all' replacements button - or an ability to
# select a series/group by highlighting and right click - clear replacement.
# I currently have 48 replacements - I can order by replacements which is
# good but I would have to clear each one individually."
# --------------------------------------------------------------------------

def _seed_image_picks(w, tmp_path):
    """Scan the image fixture and pick a replacement for three of its four
    slots, the way the tab's own picker would."""
    assets = _seed_image_assets(tmp_path)
    w.write_assets_var.set(assets)
    _scan_images(w, assets)
    rep = tmp_path / "mine.png"
    rep.write_bytes(b"\x89PNG-mine")
    rels = ["images/loose/logo.png",
            "images/scene_textures/radimg_8x8_00000003.png",
            "images/scene_textures/radimg_Char_Select_8x8_00000001.png"]
    for rel in rels:
        w._image_assignments[rel] = str(rep)
    w._refresh_image_list()
    return assets, rels


def test_every_replace_tree_allows_a_range_selection(app,
                                                     manufacturers_by_key):
    """`browse` could not HOLD a multi-row selection, so "highlight a series
    and right-click" was not a thing the user could do at all."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    for kind in ("audio", "video", "image"):
        tree = getattr(w, "_%s_tree" % kind)
        assert str(tree.cget("selectmode")) == "extended", kind


def test_a_right_click_keeps_an_existing_multi_row_selection(
        app, manufacturers_by_key, tmp_path):
    """The rule that makes a range actionable: right-clicking INSIDE the
    selection keeps it, right-clicking anywhere else selects that row only —
    which is what every single-row menu on these tabs assumes."""
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, rels = _seed_image_picks(w, tmp_path)
    tree = w._image_tree
    tree.selection_set(rels)
    assert w._right_click_selection(tree, rels[1]) == tuple(tree.selection())
    assert len(w._right_click_selection(tree, rels[1])) == 3
    other = "images/scene_textures/radimg_Char_Select_8x8_00000002.png"
    assert w._right_click_selection(tree, other) == (other,)
    assert tree.selection() == (other,)


def test_the_real_right_click_handler_routes_by_selection(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """Through `_image_on_tree_right` itself, because that is where the
    routing lives: a right-click on a row outside the selection has to give
    the old single-row menu (it selects that row first, which every entry in
    it assumes), and one inside a range has to give the bulk menu.

    A tk.Menu on Windows is a native popup that cannot be photographed, so
    `tk_popup` is captured and its labels read here instead (the PAD-31
    recipe)."""
    import tkinter as tk
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, rels = _seed_image_picks(w, tmp_path)
    tree = w._image_tree

    shown = []
    monkeypatch.setattr(tk.Menu, "tk_popup",
                        lambda self, *a, **k: shown.append(self))
    monkeypatch.setattr(tk.Menu, "grab_release", lambda self: None)

    class _Ev:
        x = y = 5
        x_root = y_root = 200

    def _labels(menu):
        return [str(menu.entrycget(i, "label"))
                for i in range(menu.index("end") + 1)
                if str(menu.type(i)) != "separator"]

    tree.selection_set(rels)
    monkeypatch.setattr(tree, "identify_row", lambda _y: rels[1])
    w._image_on_tree_right(_Ev())
    assert len(shown) == 1
    assert "Clear 3 replacements in this selection" in _labels(shown[0])
    assert tree.selection() == tuple(rels)      # the range survived

    other = "images/scene_textures/radimg_Char_Select_8x8_00000002.png"
    monkeypatch.setattr(tree, "identify_row", lambda _y: other)
    w._image_on_tree_right(_Ev())
    assert len(shown) == 2
    assert "Choose replacement…" in _labels(shown[1])
    assert tree.selection() == (other,)


def test_the_selection_menu_offers_one_clear_for_all_of_it(
        app, manufacturers_by_key, tmp_path):
    """The menu itself cannot be photographed (a native popup), so its labels
    are asserted here instead: the count it offers to clear is the number of
    selected rows that actually carry a pick, not the selection size."""
    import tkinter as tk
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, rels = _seed_image_picks(w, tmp_path)
    unpicked = "images/scene_textures/radimg_Char_Select_8x8_00000002.png"

    menu = tk.Menu(w._image_tree, tearoff=0)
    w._add_multi_row_clear(menu, "image", tuple(rels) + (unpicked,))
    labels = [str(menu.entrycget(i, "label"))
              for i in range(menu.index("end") + 1)
              if str(menu.type(i)) != "separator"]
    assert "4 slots selected" in labels
    assert "Clear 3 replacements in this selection" in labels

    # A selection with nothing picked says so rather than offering a no-op.
    menu2 = tk.Menu(w._image_tree, tearoff=0)
    w._add_multi_row_clear(menu2, "image", (unpicked,))
    labels2 = [str(menu2.entrycget(i, "label"))
               for i in range(menu2.index("end") + 1)
               if str(menu2.type(i)) != "separator"]
    assert "No replacements in this selection" in labels2


def test_clearing_a_selection_drops_every_pick_in_it(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """Three picks, one action, and the untouched fourth slot stays as it
    was.  The log gets ONE line with the count (the folder's history log
    names each one), and the sidecar is rewritten so a relaunch agrees."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assets, rels = _seed_image_picks(w, tmp_path)
    w._image_assignments["images/scene_textures/"
                         "radimg_Char_Select_8x8_00000002.png"] = "keep.png"
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a, **k: True)

    w._image_tree.selection_set(rels)
    w._clear_selected_replacements("image")

    assert list(w._image_assignments) == ["images/scene_textures/"
                                          "radimg_Char_Select_8x8_00000002.png"]
    assert staged_changes.load(assets).get("image") == w._image_assignments
    log = w._log_text.get("1.0", "end-1c")
    assert "Replace Images: cleared 3 replacements" in log
    assert "cleared replacement for images/loose/logo.png" not in log


def test_clear_replacements_button_clears_the_whole_tab(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """The button he asked for, on the row the three Replace tabs share.

    It is greyed out when there is nothing to clear — the same "tell the user
    it isn't relevant" rule as Revert all changes… — and it drops the PICKS
    only, which is what the confirm promises.
    """
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    for kind in ("audio", "video", "image"):
        btn = w._clear_all_btns[kind]
        assert str(btn.cget("text")) == "Clear replacements…"
        assert str(btn.cget("state")) == "disabled", kind

    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, _rels = _seed_image_picks(w, tmp_path)
    assert str(w._clear_all_btns["image"].cget("state")) == "normal"

    asked = []
    monkeypatch.setattr(mw.messagebox, "askyesno",
                        lambda _t, msg, **k: asked.append(msg) or True)
    w._clear_all_btns["image"].invoke()
    app.root.update()
    assert w._image_assignments == {}
    assert str(w._clear_all_btns["image"].cget("state")) == "disabled"
    assert asked and "all 3 replacements" in asked[0]
    # The promise the confirm makes, in the confirm's own words: nothing had
    # been applied yet, so nothing in the folder changes.
    assert "only drops the picks" in asked[0]
    assert "none of your own files are touched" in asked[0]
    assert "applied to the project folder" not in asked[0]


def _apply_image_pick(assets, rel, mine=b"\x89PNG-mine"):
    """What a build, or the emulator's Start, does to a picked slot: snapshot
    the extract's own file under .orig, then write the replacement over it."""
    import os as _os
    from pinball_decryptor.core import staged_originals
    assert staged_originals.snapshot(assets, rel, None)
    with open(_os.path.join(assets, *rel.split("/")), "wb") as f:
        f.write(mine)


def test_clearing_a_pick_start_already_applied_puts_the_cards_file_back(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """PAD-142, a field report: "I HAVE cleared all replacements but note that the
    replacement is still showing in the list."  Start with the overlay box
    ticked had applied his pick into the project folder, and a clear dropped
    only the pick: the slot kept his bytes, stayed "changed on disk", and the
    next emulator run still showed it.  A clear takes it back out."""
    import os as _os
    from pinball_decryptor.core import history_log, staged_originals
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assets, rels = _seed_image_picks(w, tmp_path)
    rel = rels[0]
    _apply_image_pick(assets, rel)
    w._image_changed_on_disk.add(rel)
    w._refresh_image_list()
    monkeypatch.setattr(
        mw.messagebox, "askyesno",
        lambda *a, **k: pytest.fail("a single-row clear must not ask"))

    w._image_tree.selection_set(rel)
    w._image_clear_selected()

    with open(_os.path.join(assets, *rel.split("/")), "rb") as f:
        assert f.read() == b"\x89PNG-fake"          # the extract's own bytes
    assert staged_originals.snapshot_path(assets, rel) is None
    assert rel not in w._image_assignments
    assert rel not in w._image_changed_on_disk
    assert w._image_tree.item(rel, "values")[-1] == "Choose…"
    assert "put the card's original file back" in w._log_text.get(
        "1.0", "end-1c")
    with open(history_log.path_for(assets), encoding="utf-8") as f:
        assert "put back to the extract's original" in f.read()


def test_a_slot_left_applied_after_its_pick_went_can_still_be_cleared(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """His folder as v0.212.3 left it: the pick already cleared, the slot
    still holding his image under its remembered name.  The button must not
    be greyed out over that, and its confirm has to say that Yes changes a
    file in the project folder."""
    import os as _os
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assets, rels = _seed_image_picks(w, tmp_path)
    applied = rels[1]
    _apply_image_pick(assets, applied)
    data = staged_changes.load(assets)
    data["replacement_names"] = {applied: "Godzilla_Player1_Gunmetal.png"}
    staged_changes.save(assets, data)
    for rel in rels:
        del w._image_assignments[rel]
    w._image_changed_on_disk.add(applied)
    w._refresh_image_list()
    assert str(w._clear_all_btns["image"].cget("state")) == "normal"

    asked = []
    monkeypatch.setattr(mw.messagebox, "askyesno",
                        lambda _t, msg, **k: asked.append(msg) or True)
    w._clear_all_btns["image"].invoke()
    app.root.update()

    assert asked and "Clear all 1 replacement on this tab?" in asked[0]
    assert "1 of these is already applied to the project folder" in asked[0]
    assert "back to the card's original file" in asked[0]
    with open(_os.path.join(assets, *applied.split("/")), "rb") as f:
        assert f.read() == b"\x89PNG-fake"
    assert applied not in (
        staged_changes.load(assets).get("replacement_names") or {})
    assert str(w._clear_all_btns["image"].cget("state")) == "disabled"


def test_every_clear_menu_counts_a_slot_already_applied(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """An applied slot with no pick is a replacement to the selection menu,
    the row menu and a scene group's menu alike, and the group's clear puts
    its file back through the same path."""
    import os as _os
    import tkinter as tk
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assets, rels = _seed_image_picks(w, tmp_path)
    unpicked = "images/scene_textures/radimg_Char_Select_8x8_00000002.png"
    _apply_image_pick(assets, unpicked)

    def _labels(menu):
        return [str(menu.entrycget(i, "label"))
                for i in range(menu.index("end") + 1)
                if str(menu.type(i)) != "separator"]

    menu = tk.Menu(w._image_tree, tearoff=0)
    w._add_multi_row_clear(menu, "image", tuple(rels) + (unpicked,))
    assert "Clear 4 replacements in this selection" in _labels(menu)

    shown = []
    monkeypatch.setattr(tk.Menu, "tk_popup",
                        lambda self, *a, **k: shown.append(self))
    monkeypatch.setattr(tk.Menu, "grab_release", lambda self: None)

    class _Ev:
        x = y = 5
        x_root = y_root = 200

    tree = w._image_tree
    monkeypatch.setattr(tree, "identify_row", lambda _y: unpicked)
    w._image_on_tree_right(_Ev())
    assert "Clear replacement" in _labels(shown[-1])

    w.image_group_by_scene_var.set(True)
    grp = [t for t in tree.get_children()
           if "Char_Select" in tree.item(t, "text")][0]
    kids = tuple(tree.get_children(grp))
    assert unpicked in kids
    monkeypatch.setattr(tree, "identify_row", lambda _y: grp)
    tree.selection_set(())
    w._image_on_tree_right(_Ev())
    assert "Clear replacements in group" in _labels(shown[-1])
    w._image_group_apply(grp, kids, None)
    with open(_os.path.join(assets, *unpicked.split("/")), "rb") as f:
        assert f.read() == b"\x89PNG-fake"
    assert not any(k in w._image_assignments for k in kids)


def test_declining_the_confirm_keeps_every_pick(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """A destructive bulk action that fires on No is worse than not having
    it: 48 picks are an afternoon's work."""
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, rels = _seed_image_picks(w, tmp_path)
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a, **k: False)
    w._clear_all_replacements("image")
    assert sorted(w._image_assignments) == sorted(rels)
    w._image_tree.selection_set(rels)
    w._clear_selected_replacements("image")
    assert sorted(w._image_assignments) == sorted(rels)


def test_one_row_still_clears_without_a_confirm(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """The per-row menu entry is the shared path with a selection of one, and
    it must not have grown a dialog: it was a single click before."""
    from pinball_decryptor.gui import main_window as mw
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    _assets, rels = _seed_image_picks(w, tmp_path)
    monkeypatch.setattr(
        mw.messagebox, "askyesno",
        lambda *a, **k: pytest.fail("a single-row clear must not ask"))
    w._image_tree.selection_set(rels[0])
    w._image_clear_selected()
    assert rels[0] not in w._image_assignments
    assert sorted(w._image_assignments) == sorted(rels[1:])
    log = w._log_text.get("1.0", "end-1c")
    assert "cleared replacement for %s" % rels[0] in log


@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_lists_each_mode_and_what_it_adds(app, manufacturers_by_key,
                                                         tmp_path, monkeypatch):
    """Item 149: a project's modes are a change Build applies, so the Write change scan
    lists one "Pending (Modes)" row per mode saying what it adds - its screen, its clip,
    its own end sound, its mode file - and none for a project without modes or a
    manufacturer without the modes capability."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    # a host that carries modes (a Mac's rows say they are left out: the test below pins that)
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    w = app.window
    project = str(tmp_path / "project")
    for name, spec in MP.example_specs()[:2]:
        slug, spec = MP.new_mode(project, spec=spec)
        if name == "KAIJU RUSH":
            spec.end_sound = "end.wav"
            MP.save(project, slug, spec)
    sid = w._write_preview_scan_id
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    assert w._add_pending_mode_rows(project, sid) == 2
    rows = [r for r in w._write_preview_rows if r[2] == "Pending (Modes)"]
    assert [r[1] for r in rows] == ["mode", "mode"]
    kaiju = next(r[0] for r in rows if r[0].startswith("KAIJU RUSH"))
    for needle in ("its own screen", "title-card clip", "its own end sound end.wav",
                   "mode file mode1.cfg"):
        assert needle in kaiju, needle
    # the other mode ends on the same (re-pointed) time-up call, and the row says whose sound
    atomic = next(r[0] for r in rows if r[0].startswith("ATOMIC BREATH"))
    assert "KAIJU RUSH's end sound when it ends" in atomic
    assert w._write_preview_count_lbl.cget("text") == "Total changes: 2"
    # nothing for a folder with no modes, or a manufacturer without the capability
    assert w._add_pending_mode_rows(str(tmp_path / "empty"), sid) == 0
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["spooky"])
    assert w._add_pending_mode_rows(project, sid) == 0
    # a CODE mode (modes/<slug>/<slug>.c, no mode file) reaches the card too, and the scan says what
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    os.makedirs(os.path.join(project, "modes", "blitz"))
    with open(os.path.join(project, "modes", "blitz", "blitz.c"), "w") as f:
        f.write("/* a mode */\n")
    assert w._add_pending_mode_rows(project, sid) == 3
    assert w._write_preview_rows[-1][0].startswith("BLITZ (code mode): its code (blitz.c)")


@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_says_a_direct_sd_write_leaves_the_modes_out(app, manufacturers_by_key,
                                                                    tmp_path, monkeypatch):
    """Item 149: a direct-SD write cannot add files, so the engine leaves a project's modes out.
    With the Write tab set to write to the SD card, the scan's Modes rows say so instead of
    promising the screens, clips and mode files an image build would add."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    w = app.window
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    sid = w._write_preview_scan_id
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    old = w.write_input_source_var.get()
    try:
        w.write_input_source_var.set("ssd")
        n = len(w._write_preview_rows)
        assert w._add_pending_mode_rows(project, sid) == 2
        rows = [r[0] for r in w._write_preview_rows[n:]]
        assert all("left out of a Direct-SD write" in r for r in rows), rows
        assert not any("its own screen" in r or "mode file" in r for r in rows), rows
        # an image build lists what it adds, as before
        w.write_input_source_var.set("iso")
        n = len(w._write_preview_rows)
        assert w._add_pending_mode_rows(project, sid) == 2
        assert not any("Direct-SD" in r[0] for r in w._write_preview_rows[n:])
    finally:
        w.write_input_source_var.set(old)


@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_says_a_mac_leaves_the_modes_out(app, manufacturers_by_key, tmp_path,
                                                        monkeypatch):
    """Item 149: on a Mac the tools that put a mode's files on the card do not run, so the engine
    leaves every mode out; the scan's Modes rows say so instead of promising them."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    w = app.window
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    sid = w._write_preview_scan_id
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    old = w.write_input_source_var.get()
    try:
        w.write_input_source_var.set("iso")
        monkeypatch.setattr(MW, "host_refusal", lambda platform=None: MW.MAC_REFUSAL)
        n = len(w._write_preview_rows)
        assert w._add_pending_mode_rows(project, sid) == 2
        rows = [r[0] for r in w._write_preview_rows[n:]]
        assert all("left out of this Write: a Mac cannot put" in r for r in rows), rows
        assert not any("its own screen" in r or "mode file" in r for r in rows), rows
        monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
        n = len(w._write_preview_rows)
        assert w._add_pending_mode_rows(project, sid) == 2
        assert not any("left out" in r[0] for r in w._write_preview_rows[n:])
    finally:
        w.write_input_source_var.set(old)


@pytest.mark.usefixtures("preview_modes_on")
def test_a_mode_edit_makes_the_write_tab_rescan(app, manufacturers_by_key, tmp_path, monkeypatch):
    """Item 149: the Write scan's fingerprint covers the project's modes, so adding a mode,
    editing its mode.json, giving it a sound, removing it or closing a modes gate rescans when
    the Write tab is shown again, instead of keeping stale Modes rows (or none, and a Build
    that warns "no modified files" while it writes the modes)."""
    import shutil
    from pinball_decryptor.plugins.stern import mode_project as MP
    w = app.window
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(w, "_current_mfr", manufacturers_by_key["stern"])
    monkeypatch.setattr(w, "_current_tab_key", lambda: "Write")
    monkeypatch.delenv("PAD_STERN_MODES", raising=False)
    monkeypatch.delenv("PAD_STERN_MODE_SOUND", raising=False)
    old = w.write_assets_var.get()
    scans = []
    monkeypatch.setattr(w, "_scan_write_preview", lambda: scans.append(1))
    try:
        w.write_assets_var.set(str(project))

        def shown_again():
            """what the tab does when shown: rescan only if the fingerprint moved;
            then record the fingerprint the way a finished scan does."""
            n = len(scans)
            w._maybe_rescan_write_preview()
            w._write_scan_fingerprint = w._current_write_fingerprint()
            return len(scans) > n

        w._write_scan_fingerprint = w._current_write_fingerprint()
        assert not shown_again()                      # nothing changed: no rescan
        name, spec = MP.example_specs()[0]
        slug, spec = MP.new_mode(str(project), spec=spec)
        assert shown_again(), "a mode added"
        assert not shown_again()
        spec.name = spec.name + " TWO"
        MP.save(str(project), slug, spec)
        assert shown_again(), "a mode.json edited"
        (project / "modes" / slug / "end.wav").write_bytes(b"RIFF")
        assert shown_again(), "a sound added to a mode"
        monkeypatch.setenv("PAD_STERN_MODE_SOUND", "0")
        assert shown_again(), "the own-sound gate closed"
        monkeypatch.setenv("PAD_STERN_MODES", "0")
        assert shown_again(), "the modes gate closed"
        shutil.rmtree(str(project / "modes" / slug))
        assert shown_again(), "a mode removed"
        assert not shown_again()
    finally:
        w.write_assets_var.set(old)


# ---- the intricate modes' own audio and video: code modes with assets, the code-mode Examples ------------
def _code_menu_labels(panel):
    m = panel._ex_menu
    out = []
    for i in range((m.index("end") or 0) + 1):
        if m.type(i) == "command":
            out.append(m.entrycget(i, "label"))
    return out


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_offers_the_five_intricate_modes_as_code_examples(app, tmp_path):
    """Examples lists the form modes, then the SDK's five intricate modes as CODE modes (a Godzilla
    title only: their shots are Godzilla's)."""
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    labels = _code_menu_labels(panel)
    assert labels[0] == "KAIJU RUSH"
    assert labels[-5:] == ["KING GHIDORAH (code mode)", "OXYGEN DESTROYER (code mode)",
                           "MASER BARRAGE (code mode)", "FINAL WARS (code mode)", "ANGUIRUS (code mode)"]
    assert "No code modes in this project" in panel._code_label.cget("text")


@pytest.mark.usefixtures("preview_modes_on")
def test_a_code_example_without_its_films_is_added_and_the_tab_says_which(app, tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.delenv("PAD_FILMS_DIR", raising=False)
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    t = panel.add_code_example("ANGUIRUS", dirs=[str(tmp_path)], wait=True)
    assert t is not None and not t.is_alive()
    folder = MP.mode_folder(str(project), "anguirus_assist")
    assert sorted(os.listdir(folder)) == ["anguirus_assist.c", "assets.json", "intricate_kit.h"]
    status = panel._tryit_status.cget("text")
    assert "added the example ANGUIRUS as modes/anguirus_assist with its code" in status
    assert "Godzilla Raids Again (1955)" in status and "Cut film assets" in status
    assert "ANGUIRUS (its film assets are not cut yet)" in panel._code_label.cget("text")
    # not in the form's list: a code mode has no mode.json
    assert panel._list.size() == 0
    assert panel.add_code_example("ANGUIRUS") is None
    assert "already in this project" in panel._tryit_status.cget("text")


@pytest.mark.usefixtures("preview_modes_on")
def test_a_code_example_is_cut_from_the_films_folder_the_person_picks(app, tmp_path, monkeypatch):
    """The recipe's clip, picture, music loop and calls are cut with the film cutter from the folder
    asked for (a synthetic film under a collection file name: nothing of a film is in the repo)."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    from tests.test_stern_code_modes import _ffmpeg, _synthetic_film
    ff = _ffmpeg()
    monkeypatch.delenv("PAD_FILMS_DIR", raising=False)
    films = str(tmp_path / "films")
    _synthetic_film(films, CM.FILMS["fw04"], ff)
    ex = {"name": "TEST WARS", "slug": "test_wars", "source": "final_wars.c", "headers": ["intricate_kit.h"],
          "seconds": 40,
          "recipe": {"clip": {"film": "fw04", "from": 1.0, "length": 3.0, "crop": "fill"},
                     "art": {"film": "fw04", "at": 2.0, "crop": "fill"},
                     "music": {"film": "fw04", "from": 2.0, "length": 10.0},
                     "calls": {"won": {"film": "fw04", "from": 3.0, "length": 1.5}}}}
    monkeypatch.setattr(CM, "EXAMPLES", [ex])
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    w = app.window
    w.write_assets_var.set(str(project))
    app.root.update()
    panel = w._modes_panel
    panel._ffmpeg_fn = lambda: ff
    asked = []
    panel._ask_dir_fn = lambda why: asked.append(why) or films
    t = panel._on_code_example("TEST WARS")
    t.join(60)
    assert _wait_for(lambda: "TEST WARS (clip, picture, music, 1 call(s))" in panel._code_label.cget("text"),
                     app.root, secs=10)
    assert asked and "Godzilla: Final Wars (2004)" in asked[0]
    assert "its own clip, picture, music and calls cut from the films" in panel._tryit_status.cget("text")
    spec = CM.load(str(project), "test_wars")
    assert spec.film["dir"] == films and spec.calls == {"won": "won.wav"}


@pytest.mark.usefixtures("preview_modes_on")
def test_try_it_carries_code_modes_with_assets_through_writes_set(app, tmp_path, monkeypatch):
    """A project of code modes WITH assets is not the code-only fast path: Try it builds Write's own
    set (their screens, clips and sounds), whose stage already holds the object Write compiled, so
    the tab installs it without compiling again."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_code_modes import _code_project

    _no_wsl(monkeypatch)
    project = _code_project(tmp_path)
    w = app.window
    w.write_assets_var.set(project)
    app.root.update()
    panel = w._modes_panel
    ran, handed, calls = [], [], []
    _fake_rig(panel, ran)
    panel._tryit_base = str(tmp_path / "try")
    panel._try_fn = lambda prepare: handed.append(prepare) or True
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    monkeypatch.setattr(CM, "profile_for", lambda project, code=(): MP.GODZILLA_PRO_1_15)

    def build(project_, card, base, log=None, **kw):
        calls.append(project_)
        s = os.path.join(base, MW.TRYIT_SET)
        stage = s + "-modes"
        os.makedirs(os.path.join(s, "godzilla_pro"), exist_ok=True)
        with open(os.path.join(s, "godzilla_pro", "game"), "wb") as f:
            f.write(b"set file")
        os.makedirs(stage, exist_ok=True)
        for name, data in (("pad_mode.so", b"\x7fELF compiled by Write"), ("game.port", b"game godzilla_pro\n"),
                           ("ghidorah_heads.assets", b"name KING GHIDORAH\n")):
            with open(os.path.join(stage, name), "wb") as f:
                f.write(data)
        return MW.TryItSet(set_dir=s, stage_dir=stage, game_dir="godzilla_pro", version="1.15",
                           files=["godzilla_pro/game"], port=os.path.join(stage, "game.port"),
                           codes=["ghidorah_heads"], code_object=True)
    monkeypatch.setattr(MW, "build_tryit_set", build)
    assert panel._on_try() is True
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    env = handed[0](str(card))
    assert calls == [project]                               # Write's set, not the fast path
    assert env == panel.tryit_env()
    assert [c[1] for c in ran] == ["modes/tryit.sh"] and ran[0][2] == "install"   # no second compile
    status = panel._tryit_status.cget("text")
    assert "Code mode(s) built in: ghidorah_heads" in status and "carries them the same way" in status
    assert status.startswith("Ready. Start a game") and "0 mode(s)" not in status   # no form mode to name
    assert MR.sdk_dir()                                      # the SDK is where the tab looks
