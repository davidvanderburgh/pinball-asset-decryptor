"""GUI guards for monkeybug batch 16.

Covers the pieces that are easy to break silently by editing layout code:
the "Changed only" filters, the removed sort-hint labels + their former
`before=`/`after=` pack anchors, the new video Export CSV, and the themed
replacements for the unthemed popups.
"""

import csv
import os

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


pytestmark = pytest.mark.skipif(
    not HAS_DISPLAY, reason="no Tk display available")


class _Slot:
    """Minimal stand-in for AudioSlot / VideoSlot (only what the list
    refreshers and the CSV writer touch)."""

    def __init__(self, rel, duration=1.0):
        self.rel_path = rel
        self.abs_path = os.path.join("C:\\x", rel)
        self.duration = duration
        self.info = None
        self.probed = True

    def duration_str(self):
        return "0:01.000"

    def format_summary(self):
        return "WAV 44.1kHz mono"

    def resolution_str(self):
        return "640x480"


def _stern(app):
    """Select Stern so the Replace tabs + Partition Explorer are live."""
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


def _show_tab(app, w, frame):
    """Raise a notebook tab and settle geometry.

    Widgets on an UNSELECTED tab report winfo_ismapped()==0 and x==0, so any
    layout assertion has to raise the tab first or it passes vacuously."""
    w._notebook.select(frame)
    app.root.update(); app.root.update_idletasks()


# ---- "Changed only" filter (monkeybug: show only modified files) ----------

def test_audio_changed_only_filters_the_list(app):
    w = _stern(app)
    w._audio_slots = [_Slot("audio/a.wav"), _Slot("audio/b.wav"),
                      _Slot("audio/c.wav")]
    w._audio_slots_by_rel = {s.rel_path: s for s in w._audio_slots}
    w._audio_assignments = {"audio/b.wav": "C:\\rep.wav"}
    w._audio_changed_on_disk = {"audio/c.wav"}

    w.audio_changed_only_var.set(False)
    w._refresh_audio_list()
    assert len(w._audio_tree.get_children()) == 3

    w.audio_changed_only_var.set(True)     # traced -> refreshes
    app.root.update()
    rows = set(w._audio_tree.get_children())
    assert rows == {"audio/b.wav", "audio/c.wav"}, \
        "changed-only must keep BOTH a pending pick and a changed-on-disk row"


def test_video_changed_only_filters_the_list(app):
    w = _stern(app)
    w._video_slots = [_Slot("video/a.mp4"), _Slot("video/b.mp4")]
    w._video_slots_by_rel = {s.rel_path: s for s in w._video_slots}
    w._video_assignments = {"video/b.mp4": "C:\\rep.mp4"}
    w._video_changed_on_disk = set()

    w.video_changed_only_var.set(True)
    app.root.update()
    assert set(w._video_tree.get_children()) == {"video/b.mp4"}


def test_changed_only_does_not_hide_the_total_count(app):
    """The status line still reports the real total, with "(N shown)" so a
    filtered view can't be mistaken for the whole card."""
    w = _stern(app)
    w._audio_slots = [_Slot("audio/a.wav"), _Slot("audio/b.wav")]
    w._audio_slots_by_rel = {s.rel_path: s for s in w._audio_slots}
    w._audio_assignments = {"audio/b.wav": "C:\\rep.wav"}
    w._audio_changed_on_disk = set()
    w.audio_changed_only_var.set(True)
    app.root.update()
    status = w.audio_status_var.get()
    assert "of 2 slots changed" in status and "1 shown" in status


# ---- the removed sort hints + their former pack anchors -------------------

def test_sort_hint_labels_are_gone(app):
    """They were pure clutter after first read (monkeybug)."""
    w = _stern(app)
    assert not hasattr(w, "_audio_sort_hint_lbl")
    for tab in (w._tab_audio, w._tab_video, w._tab_image):
        for child in tab.winfo_children():
            for gc in child.winfo_children():
                text = str(gc.cget("text")) if "text" in gc.keys() else ""
                assert "click a column header" not in text


def test_optional_toolbar_widgets_still_pack(app):
    """Type / Group-duplicates used to pack `before=` the sort hint, and the
    declick checkbox `after=` a blank note label; both anchors were deleted.
    Their replacements must still place the widgets."""
    w = _stern(app)
    _show_tab(app, w, w._tab_audio)
    w._audio_categories = {"audio/a.wav": "callouts"}
    w._refresh_audio_type_filter()
    app.root.update()
    assert w._audio_type_frame.winfo_ismapped(), \
        "Type filter lost its pack anchor"
    # Stern shows the callout-matching checkbox, packed after the trim box.
    assert w._audio_declick_cb.winfo_ismapped()
    assert w._audio_trim_cb.winfo_ismapped()
    # ...and the Type filter still sits LEFT of the Changed-only checkbox.
    order = w._audio_type_frame.master.pack_slaves()
    assert order.index(w._audio_type_frame) < order.index(
        w._audio_changed_only_cb)


def test_audio_checkboxes_are_left_aligned(app):
    """monkeybug: "move checkbox to same level as other and tighten up"."""
    w = _stern(app)
    _show_tab(app, w, w._tab_audio)
    assert w._audio_trim_cb.winfo_ismapped()
    assert w._audio_trim_cb.winfo_x() == w._audio_declick_cb.winfo_x()
    # The blank spacer label that used to wedge a full text line between them
    # is gone, so they are adjacent rows.
    gap = w._audio_declick_cb.winfo_y() - (
        w._audio_trim_cb.winfo_y() + w._audio_trim_cb.winfo_height())
    assert 0 <= gap <= 6, "checkboxes drifted apart again (gap=%d)" % gap


def test_video_checkboxes_are_left_aligned(app):
    w = _stern(app)
    _show_tab(app, w, w._tab_video)
    assert w._video_no_conversion_cb.winfo_ismapped()
    assert (w._video_no_conversion_cb.winfo_x()
            == w._video_trim_cb.winfo_x())
    gap = w._video_trim_cb.winfo_y() - (
        w._video_no_conversion_cb.winfo_y()
        + w._video_no_conversion_cb.winfo_height())
    assert 0 <= gap <= 6, "checkboxes drifted apart again (gap=%d)" % gap


# ---- video Export CSV (mirrors audio) ------------------------------------

def test_video_export_csv_writes_every_slot(app, tmp_path, monkeypatch):
    w = _stern(app)
    w._video_slots = [_Slot("video/b.mp4"), _Slot("video/a.mp4")]
    w._video_slots_by_rel = {s.rel_path: s for s in w._video_slots}
    w._video_assignments = {"video/a.mp4": "C:\\rep.mp4"}
    w._video_changed_on_disk = {"video/b.mp4"}
    # Filter the view down — the CSV must still hold EVERY slot.
    w.video_changed_only_var.set(True)

    out = tmp_path / "video_slots.csv"
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.filedialog.asksaveasfilename",
        lambda **kw: str(out))
    w._video_export_csv()

    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "Original Video"
    assert [r[0] for r in rows[1:]] == ["video/a.mp4", "video/b.mp4"]
    assert rows[1][5] == "C:\\rep.mp4"        # Replacement
    assert rows[2][6] == "yes"                # Changed On Disk


def test_video_export_csv_empty_table_is_a_no_op(app, monkeypatch):
    w = _stern(app)
    w._video_slots = []
    called = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda *a, **k: called.append(a))
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.filedialog.asksaveasfilename",
        lambda **kw: pytest.fail("should not open a save dialog"))
    w._video_export_csv()
    assert called


# ---- dark mode on popups -------------------------------------------------

def test_theme_toplevel_paints_the_window_background(app):
    import tkinter as tk
    from pinball_decryptor.gui.theme import THEMES

    w = _stern(app)
    w._current_theme = "dark"
    win = tk.Toplevel(w.root)
    try:
        w._theme_toplevel(win)
        assert str(win.cget("bg")) == THEMES["dark"]["bg"]
    finally:
        win.destroy()


def test_partition_preview_is_themed_not_system_white(app):
    from pinball_decryptor.gui.theme import THEMES

    w = _stern(app)
    for name in ("dark", "light"):
        w._apply_theme(name)
        app.root.update_idletasks()
        assert str(w._pex_preview.cget("bg")) == THEMES[name]["field_bg"]
        assert str(w._pex_preview.cget("fg")) == THEMES[name]["fg"]


# ---- Find in Partition Explorer -----------------------------------------

def test_find_in_partition_asks_for_an_image_when_none_is_open(app,
                                                               monkeypatch):
    """With no card image open the jump can't resolve anything — it must say
    so and raise the Partitions tab, not crash or fail silently."""
    w = _stern(app)
    w._video_scan_dir = ""
    w._video_slots_by_rel = {"video/a.mp4": _Slot("video/a.mp4")}
    said = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda *a, **k: said.append(a))
    w._asset_find_in_partition("video", "video/a.mp4")
    assert said, "should explain why it can't jump"


def test_find_in_partition_menu_item_hidden_without_the_tab(app, monkeypatch):
    """The item cross-links to the Partition Explorer, so it must not appear
    for a manufacturer that doesn't have that tab."""
    import tkinter as tk

    w = _stern(app)
    menu = tk.Menu(w.root, tearoff=0)
    w._add_find_in_partition_item(menu, "audio", "audio/a.wav")
    assert menu.index("end") is not None, "Stern has the tab -> item present"

    monkeypatch.setattr(type(w), "_tab_visible", lambda self, key: False)
    menu2 = tk.Menu(w.root, tearoff=0)
    w._add_find_in_partition_item(menu2, "audio", "audio/a.wav")
    assert menu2.index("end") is None, "no Partition tab -> no menu item"


def test_ask_text_replaces_simpledialog(app):
    """The rename/preset prompts must be our themed dialog, not the
    unstyled tkinter.simpledialog (a white box in dark mode)."""
    import inspect
    from pinball_decryptor.gui import main_window

    src = inspect.getsource(main_window)
    # Only real call sites matter — the helper's docstring names the API it
    # replaced, so match the import that a call site would need.
    assert "from tkinter import simpledialog" not in src
    assert hasattr(main_window.MainWindow, "_ask_text")
