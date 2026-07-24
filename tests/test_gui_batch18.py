"""GUI guards for monkeybug batch 18.

Covers: the Audio-category gate on the chained Auto-name steps (video-only
extract must not run transcribe / music-ID against an output with no WAVs),
the build→flash chain behind the two-section Build / flash dialog, and the
project-file save/load round-trip.
"""

import os
import tkinter as tk
from tkinter import ttk

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


def _pick(app, key):
    mfr = next(m for m in app._manufacturers if m.key == key)
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


# ---- Audio category off ⇒ no chained auto-name steps ----------------------

def test_autoname_chain_skipped_when_audio_category_off(app):
    """monkeybug: a video-only extract (Audio unchecked) still chained
    Auto-transcribe + Music-ID, which then errored on \"No .wav files\".
    The wrappers must return the done_cb untouched when the run won't
    produce audio."""
    w = _pick(app, "stern")
    assert app._current_mfr.capabilities.transcribe
    assert app._current_mfr.capabilities.music_id
    assert "audio" in w._extract_category_vars

    sentinel = lambda s, m: None
    w.transcribe_var.set(True)
    w.music_id_var.set(True)

    w._extract_category_vars["audio"].set(False)
    assert app._maybe_wrap_done_for_transcribe(sentinel, "X") is sentinel
    assert app._maybe_wrap_done_for_music_id(sentinel, "X") is sentinel

    w._extract_category_vars["audio"].set(True)
    assert app._maybe_wrap_done_for_transcribe(sentinel, "X") is not sentinel
    assert app._maybe_wrap_done_for_music_id(sentinel, "X") is not sentinel


def test_plugins_without_audio_category_still_chain(app):
    """The gate must only ever SKIP for plugins exposing an Audio category
    checkbox — everyone else keeps the old behaviour."""
    _pick(app, "stern")
    app.window._extract_category_vars = {}
    assert app._extract_will_produce_audio()


# ---- Build → flash chain --------------------------------------------------

def test_build_success_chains_flash(app, monkeypatch):
    import pinball_decryptor.app as app_mod
    _pick(app, "stern")
    app._active_mode = "write"

    flashed = []
    monkeypatch.setattr(
        app, "_start_flash_image",
        lambda img, dev: flashed.append((img, dev)))
    # A chained build must NOT pop the "Write Complete" modal in between.
    monkeypatch.setattr(
        app_mod.messagebox, "showinfo",
        lambda *a, **k: pytest.fail("no modal between build and flash"))

    app._chain_flash_after_build = (r"\\.\PHYSICALDRIVE9", r"C:\img.raw")
    app._on_done(True, "built.")
    app.root.update()          # fire the after(0, …) hand-off

    assert flashed == [(r"C:\img.raw", r"\\.\PHYSICALDRIVE9")]
    assert app._chain_flash_after_build is None


def test_failed_build_drops_the_chained_flash(app, monkeypatch):
    import pinball_decryptor.app as app_mod
    _pick(app, "stern")
    app._active_mode = "write"

    flashed = []
    monkeypatch.setattr(
        app, "_start_flash_image",
        lambda img, dev: flashed.append((img, dev)))
    monkeypatch.setattr(app_mod.messagebox, "showerror",
                        lambda *a, **k: None)

    app._chain_flash_after_build = (r"\\.\PHYSICALDRIVE9", r"C:\img.raw")
    app._on_done(False, "boom")
    app.root.update()

    assert flashed == [], "a failed build must never flash the card"
    assert app._chain_flash_after_build is None


def test_unrelated_success_never_fires_a_stale_chain(app, monkeypatch):
    """The chain is consumed on ANY _on_done — an extract finishing after a
    cancelled build must not flash the card."""
    _pick(app, "stern")
    app._active_mode = "extract"
    flashed = []
    monkeypatch.setattr(
        app, "_start_flash_image",
        lambda img, dev: flashed.append((img, dev)))
    app._chain_flash_after_build = (r"\\.\PHYSICALDRIVE9", r"C:\img.raw")
    app._on_done(True, "extract done")
    app.root.update()
    assert flashed == []
    assert app._chain_flash_after_build is None


# ---- The two-section Build / flash dialog ---------------------------------

def _make_dialog(app, monkeypatch, **kw):
    from pinball_decryptor.gui.flash_dialog import FlashImageDialog
    # Don't enumerate real drives (spawns PowerShell) in a unit test.
    monkeypatch.setattr(FlashImageDialog, "_refresh_drives",
                        lambda self: None)
    defaults = dict(
        parent=app.root, manufacturer=app._current_mfr, theme_name="light",
        on_flash=lambda i, d: None)
    defaults.update(kw)
    return FlashImageDialog(**defaults)


def test_dialog_defaults_build_and_flash_when_changes_pending(
        app, monkeypatch):
    _pick(app, "stern")
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: None,
        build_target=r"C:\x\y-modified.raw",
        can_build=True, has_pending_changes=True)
    try:
        assert dlg._build_var.get() and dlg._write_var.get()
        assert dlg._start_btn.cget("text") == "Build + flash"
        # The flash box mirrors the build output while building.
        assert dlg._image_var.get() == r"C:\x\y-modified.raw"
        # Build unticked ⇒ plain flash (the old dialog).
        dlg._build_var.set(False); dlg._sync_sections()
        assert dlg._start_btn.cget("text") == "Flash image"
        # Flash unticked too ⇒ nothing to do; Start is disabled.
        dlg._write_var.set(False); dlg._sync_sections()
        assert "disabled" in dlg._start_btn.state()
    finally:
        dlg._cancel()


def test_dialog_no_pending_changes_defaults_flash_only(app, monkeypatch):
    _pick(app, "stern")
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: None,
        build_target=r"C:\x\y-modified.raw",
        can_build=True, has_pending_changes=False)
    try:
        assert not dlg._build_var.get()
        assert dlg._write_var.get()
        assert dlg._start_btn.cget("text") == "Flash image"
    finally:
        dlg._cancel()


def test_dialog_cancel_is_red_start_is_green(app, monkeypatch):
    """The dialog's Start is green (go) and Cancel is red — Cancel is red in
    general (David), matching the main window's live-run Cancel."""
    _pick(app, "stern")
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: None,
        build_target=r"C:\x\y-modified.raw", can_build=True)
    try:
        assert str(dlg._start_btn.cget("style")) == "Go.TButton"
        # The Cancel button is the sibling of Start in the button row.
        cancels = [c for c in dlg._start_btn.master.winfo_children()
                   if isinstance(c, ttk.Button)
                   and c.cget("text") == "Cancel"]
        assert cancels, "dialog must have a Cancel button"
        assert str(cancels[0].cget("style")) == "Danger.TButton"
    finally:
        dlg._cancel()


def test_dialog_opens_without_default_position_flicker(app, monkeypatch):
    """The dialog stays withdrawn from creation right up until the single
    deiconify at the tail — built AND positioned first — so the user never
    sees an empty box map at its default spot and jump into place (David).
    Proven by spying on the map: the window is still withdrawn when
    deiconify is finally called, and its reqwidth is the built size (i.e.
    the whole layout happened while hidden)."""
    from pinball_decryptor.gui.flash_dialog import FlashImageDialog
    monkeypatch.setattr(FlashImageDialog, "_refresh_drives",
                        lambda self: None)
    _pick(app, "stern")

    seen = {}
    real_deiconify = tk.Toplevel.deiconify

    def spy(self):
        seen["state_before"] = self.state()
        seen["reqwidth"] = self.winfo_reqwidth()
        return real_deiconify(self)

    monkeypatch.setattr(tk.Toplevel, "deiconify", spy)
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: None,
        build_target=r"C:\x\y.raw", can_build=True)
    try:
        assert seen.get("state_before") == "withdrawn", \
            "dialog must be hidden right up until the single deiconify"
        assert seen["reqwidth"] >= 400, \
            "the layout must be fully built before the window is mapped"
    finally:
        dlg._cancel()


def test_dialog_build_only_hands_off_without_confirm(app, monkeypatch):
    """Build-only (write section unticked) needs no erase confirm and hands
    (build_path, None) to the app."""
    _pick(app, "stern")
    calls = []
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: calls.append((b, d)),
        build_target=r"C:\x\y-modified.raw",
        can_build=True, has_pending_changes=True)
    dlg._write_var.set(False); dlg._sync_sections()
    dlg._do_start()
    assert calls == [(r"C:\x\y-modified.raw", None)]


def test_on_build_flash_request_writes_back_and_arms_chain(app, monkeypatch):
    """The dialog's Build-to box pushes back into Output Folder + File Name,
    and the device rides into _start_write's chain parameter."""
    w = _pick(app, "stern")
    seen = {}
    monkeypatch.setattr(
        app, "_start_write",
        lambda chain_flash_device=None: seen.update(
            device=chain_flash_device))
    # Build the path with the OS-native separator (os.path.split only treats
    # os.sep as a separator — a hardcoded r"D:\..." reads as one flat name on
    # POSIX CI and the folder push-back looks empty).
    build_path = os.path.join(os.sep + "builds", "lz-test.raw")
    expected_folder, expected_name = os.path.split(build_path)
    app._on_build_flash_request(build_path, r"\\.\PHYSICALDRIVE7")
    assert w.write_output_var.get() == expected_folder
    assert w.write_filename_var.get() == expected_name == "lz-test.raw"
    assert seen["device"] == r"\\.\PHYSICALDRIVE7"


# ---- Previous-session log seeded into the pane ----------------------------

def test_previous_session_log_seeds_pane_dimmed_above_cut(app):
    """The log pane opens pre-loaded with the previous sessions' tail in the
    dimmed "hist" tag, closed by a cut line, with this session's lines
    landing below it (David: show the history in the log window itself
    rather than behind a menu item)."""
    # Fabricate an earlier session ABOVE the banner the fixture's App()
    # already wrote (widgets are created lazily per mfr, so none has read
    # the file yet).
    _fabricate_history(app)

    w = _pick(app, "stern")          # first widget for this mfr → seeds
    t = w._log_text
    content = t.get("1.0", "end")
    assert "line from last time" in content
    assert "this session below" in content
    assert t.tag_ranges("hist"), "history must carry the dimmed tag"
    assert t.tag_ranges("cut"), "the cut line must carry its tag"

    w.append_log("fresh line")
    # The fresh line lands AFTER the cut line.
    cut_end = t.tag_ranges("cut")[-1]
    fresh_at = t.search("fresh line", "1.0", tk.END)
    assert t.compare(fresh_at, ">", cut_end)


def test_show_log_history_defaults_on(app):
    """A fresh install (no settings.json) shows previous sessions in the
    log by default — hiding them is the opt-out (David)."""
    assert app.window.show_log_history_var.get() is True


def test_no_history_means_no_cut_line(app):
    """A first-ever session (no earlier banner in the file) seeds nothing —
    no stray cut line over an empty pane."""
    w = _pick(app, "stern")
    t = w._log_text
    assert "this session below" not in t.get("1.0", "end")


def _fabricate_history(app):
    """Prepend a fake earlier session above the banner the fixture's App()
    wrote, so lazily-created log widgets have something to seed."""
    from pinball_decryptor.core import session_log as sl
    with open(sl.log_path(), encoding="utf-8") as fh:
        current = fh.read()
    older = (sl.BANNER_PREFIX + "0.0.1 — session started "
             "2026-01-01 00:00:00 =====\n"
             "[2026-01-01 00:00:05] line from last time\n")
    with open(sl.log_path(), "w", encoding="utf-8") as fh:
        fh.write(older + current)


def test_show_history_toggle_strips_and_reseeds_live(app):
    """⚙ → "Show previous sessions in the log" off: existing panes lose the
    dimmed history + cut line but keep this session's lines, and the choice
    persists to settings.  Back on: the history returns above the live
    lines."""
    _fabricate_history(app)
    w = _pick(app, "stern")
    t = w._log_text
    w.append_log("fresh line")
    assert "line from last time" in t.get("1.0", "end")

    w.show_log_history_var.set(False)
    w._on_toggle_log_history()
    content = t.get("1.0", "end")
    assert "line from last time" not in content
    assert "this session below" not in content
    assert "fresh line" in content, "live lines must survive the strip"
    assert app._settings.get("show_log_history") is False

    w.show_log_history_var.set(True)
    w._on_toggle_log_history()
    content = t.get("1.0", "end")
    assert "line from last time" in content
    assert "this session below" in content
    # History re-lands ABOVE the live line.
    assert content.index("line from last time") < content.index("fresh line")
    assert app._settings.get("show_log_history") is True


def test_history_disabled_skips_seeding_new_panes(app):
    """With the toggle off, a freshly-created pane starts clean (no history,
    no cut line)."""
    _fabricate_history(app)
    app.window.show_log_history_var.set(False)
    w = _pick(app, "stern")
    content = w._log_text.get("1.0", "end")
    assert "line from last time" not in content
    assert "this session below" not in content


def test_copy_current_session_skips_history(app):
    """Right-click → "Copy current session log" copies only what's below
    the cut line."""
    _fabricate_history(app)
    w = _pick(app, "stern")
    w.append_log("fresh line one")
    w.append_log("fresh line two")
    w._log_copy_session(w._log_text)
    clip = w.root.clipboard_get()
    assert "fresh line one" in clip and "fresh line two" in clip
    assert "line from last time" not in clip
    assert "this session below" not in clip, "the cut line itself stays out"


def test_copy_current_session_without_history_copies_all(app):
    """No cut line in the pane (no history) ⇒ the whole pane is the current
    session and all of it copies."""
    w = _pick(app, "stern")
    w.append_log("only line")
    w._log_copy_session(w._log_text)
    assert "only line" in w.root.clipboard_get()


# ---- Consolidated Build / flash button ------------------------------------

def test_flash_button_mirrors_build_cancel_role(app):
    """With the plain Build button hidden for flash-capable plugins, the
    Build / flash button takes over Build's live-Cancel role during write
    runs — and greys out (not a second Cancel) during extract runs."""
    w = _pick(app, "stern")
    assert w._write_btn.winfo_manager() == ""

    w.set_running(True, mode="write")
    try:
        assert w._flash_btn.cget("text") == "Cancel"
        assert str(w._flash_btn.cget("style")) == "Danger.TButton"
    finally:
        w.set_running(False, mode="write")
    assert w._flash_btn.cget("text").startswith("Build / flash")
    assert str(w._flash_btn.cget("style")) == "Go.TButton"

    w.set_running(True, mode="extract")
    try:
        assert w._flash_btn.cget("text") != "Cancel"
        assert str(w._flash_btn.cget("state")) == "disabled"
    finally:
        w.set_running(False, mode="extract")
    assert str(w._flash_btn.cget("state")) == "normal"


def test_flash_run_still_owns_its_cancel(app):
    """set_flash_running wins over the write-run mirror: during the flash
    phase the button stays a live Cancel and restores cleanly after."""
    w = _pick(app, "stern")
    w.set_running(True, mode="write")
    w.set_flash_running(True)
    try:
        assert w._flash_btn.cget("text") == "Cancel"
        assert str(w._flash_btn.cget("state")) == "normal"
    finally:
        w.set_running(False, mode="write")
    assert w._flash_btn.cget("text").startswith("Build / flash")
    assert not w._flash_running


def test_dialog_build_warns_when_nothing_modified(app, monkeypatch):
    """The standalone Build button's nothing-modified guard lives in the
    dialog now (it replaced that button): building with no pending changes
    asks first, and declining runs nothing."""
    import pinball_decryptor.gui.flash_dialog as fd
    _pick(app, "stern")
    asked = []
    monkeypatch.setattr(
        fd.messagebox, "askyesno",
        lambda *a, **k: (asked.append(a), False)[1])
    calls = []
    dlg = _make_dialog(
        app, monkeypatch,
        on_build_flash=lambda b, d: calls.append((b, d)),
        build_target=r"C:\x\y-modified.raw",
        can_build=True, has_pending_changes=False)
    try:
        dlg._build_var.set(True)
        dlg._write_var.set(False)
        dlg._sync_sections()
        dlg._do_start()
        assert asked, "must warn before building an unmodified copy"
        assert calls == [], "declining the warning must not build"
    finally:
        if dlg._dlg.winfo_exists():
            dlg._cancel()


# ---- Color-coded action buttons -------------------------------------------

def test_action_buttons_carry_go_and_danger_styles(app):
    """Green = go (Extract / Build / Build / flash), red = destructive
    (run Cancel, Revert all changes); the styles exist with the theme's
    fills in both themes."""
    from tkinter import ttk
    from pinball_decryptor.gui.main_window import THEMES
    w = _pick(app, "stern")
    assert str(w._extract_btn.cget("style")) == "Go.TButton"
    assert str(w._flash_btn.cget("style")) == "Go.TButton"
    assert str(w._revert_all_btn.cget("style")) == "Danger.TButton"

    w.set_running(True, mode="extract")
    try:
        assert str(w._extract_btn.cget("style")) == "Danger.TButton"
    finally:
        w.set_running(False, mode="extract")
    assert str(w._extract_btn.cget("style")) == "Go.TButton"

    style = ttk.Style()
    for theme in ("dark", "light"):
        w._apply_theme(theme)
        c = THEMES[theme]
        assert style.lookup("Go.TButton", "background") == c["go_btn"]
        assert style.lookup("Danger.TButton", "background") == \
            c["danger_btn"]


def _all_buttons(widget):
    out = []
    for c in widget.winfo_children():
        if isinstance(c, ttk.Button):
            out.append(c)
        out.extend(_all_buttons(c))
    return out


def test_modpack_tab_actions_are_green(app):
    """Export / Import / Transfer on the Mod Pack tab are go actions and
    carry the green Go style (David)."""
    w = _pick(app, "stern")
    wanted = {"Export Mod Pack...", "Import Mod Pack...",
              "Transfer mods → new version..."}
    found = {b.cget("text"): str(b.cget("style"))
             for b in _all_buttons(w._tab_modpack)
             if b.cget("text") in wanted}
    assert wanted <= set(found), \
        "missing a Mod Pack action button: %s" % (wanted - set(found))
    for text, style in found.items():
        assert style == "Go.TButton", "%s should be green, got %s" % (
            text, style)


# ---- ⚙ menu indicator visibility ------------------------------------------

def test_settings_menu_indicators_visible_in_both_themes(app):
    """The ⚙ menu's ✓/radio indicators are drawn in ``selectcolor`` — Tk's
    default is near-black, invisible on the dark theme (David).  Both the
    top menu and the voice-quality submenu must use the theme fg."""
    from pinball_decryptor.gui.main_window import THEMES
    _pick(app, "stern")
    for theme in ("dark", "light"):
        app.window._current_theme = theme
        menu = app.window._build_settings_menu()
        assert str(menu.cget("selectcolor")) == THEMES[theme]["fg"]
        # The voice-quality cascade holds the radiobuttons — same rule.
        for i in range(menu.index("end") + 1):
            if menu.type(i) == "cascade" and "Voice recognition" in \
                    menu.entrycget(i, "label"):
                sub = menu.nametowidget(menu.entrycget(i, "menu"))
                assert str(sub.cget("selectcolor")) == THEMES[theme]["fg"]
                break
        else:
            pytest.fail("voice-quality cascade not found")


def _menu_labels(menu):
    return {menu.entrycget(i, "label"): i
            for i in range(menu.index("end") + 1)
            if menu.type(i) != "separator"}


def test_logs_cascade_groups_log_settings(app):
    """⚙ → Logs holds both log settings (history viewer + seed toggle) as a
    submenu, like Voice recognition quality — no loose top-level entries.
    Dark theme appends its own ▸ to every cascade label (Windows Tk draws
    the native arrow in the system color, invisible on dark); light theme
    keeps the native arrow only."""
    _pick(app, "stern")
    for theme in ("dark", "light"):
        app.window._current_theme = theme
        menu = app.window._build_settings_menu()
        labels = _menu_labels(menu)
        logs_label = next((l for l in labels if l.startswith("Logs")), None)
        assert logs_label, "Logs cascade missing"
        assert menu.type(labels[logs_label]) == "cascade"
        sub = menu.nametowidget(menu.entrycget(labels[logs_label], "menu"))
        sub_labels = _menu_labels(sub)
        assert any("View log history" in l for l in sub_labels)
        assert any("Show previous sessions" in l for l in sub_labels)
        # Not loose at the top level any more.
        assert not any("View log history" in l for l in labels)
        # Dark-theme label arrows, on every cascade.
        cascade_labels = [l for l, i in labels.items()
                          if menu.type(i) == "cascade"]
        assert cascade_labels
        for l in cascade_labels:
            if theme == "dark":
                assert l.endswith("▸"), l
            else:
                assert not l.endswith("▸"), l


# ---- Project files --------------------------------------------------------

def test_project_apply_restores_everything(app, tmp_path):
    from pinball_decryptor.core import project_file as pf

    # Start somewhere that is NOT the project's manufacturer.
    other = next(m.key for m in app._manufacturers if m.key != "stern")
    _pick(app, other)

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

    app._apply_project_file(p)
    app.root.update(); app.root.update()
    w = app.window

    assert app._current_mfr.key == "stern", "project switches manufacturer"
    assert w.extract_input_var.get() == str(tmp_path / "in.raw")
    assert w.extract_output_var.get() == str(tmp_path / "out")
    assert w.write_output_var.get() == str(tmp_path / "builds")
    assert w.write_assets_var.get() == str(tmp_path / "out")
    assert w.transcribe_var.get() is True
    assert w._extract_category_vars["audio"].get() is False
    assert w.write_filename_var.get() == "lz-test.raw"
    assert "lz-2.10.pinproj" in app.root.title()


def test_project_load_rejects_unknown_manufacturer(app, tmp_path):
    from pinball_decryptor.core import project_file as pf
    _pick(app, "stern")
    p = str(tmp_path / "weird.pinproj")
    pf.save(p, manufacturer_key="not-a-real-plugin", paths={},
            extract_options={})
    with pytest.raises(ValueError):
        app._apply_project_file(p)
