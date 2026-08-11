"""Feedback batch 32 — the Spike 2 tester's Led Zeppelin build day (2026-08-11).

Three things:

* "pad_audio_filter — I found that it isn't 100% filtering. See image."  His
  screenshot showed the Type filter on Music with a row in the list whose own
  Type column said "Sound FX" (a 1:01 "Cheering" effect).  The Music filter
  used to count any track 20 seconds or longer as music, which Led Zeppelin
  1.22 needs when nothing in the folder identifies music at all — but not on
  a folder like his, where the songs ARE identified.  Column and filter now
  answer with one function.

* "I always have my app maximized. After it updates it does not put it back
  to maximize."  Only "WxH+X+Y" was saved, so a maximized window came back as
  an ordinary window of the same size.

* "Would it be possible to have the columns in this screen sortable? I was
  trying to find the item with the biggest length."  The Defaults tab's
  all-settings list was the one table in the app with dead headers.
"""
import os

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


class _Slot:
    """Minimal AudioSlot stand-in (what the list refresher touches)."""

    def __init__(self, rel, duration):
        self.rel_path = rel
        self.abs_path = os.path.join("C:\\x", rel)
        self.duration = duration
        self.info = None
        self.probed = True

    def duration_str(self):
        return "0:01.000"

    def format_summary(self):
        return "WAV 44.1kHz stereo 16-bit"


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    return app.window


def _load_audio(w, slots, cats):
    w._audio_slots = list(slots)
    w._audio_slots_by_rel = {s.rel_path: s for s in slots}
    w._audio_assignments = {}
    w._audio_changed_on_disk = set()
    w._audio_categories = dict(cats)
    w._refresh_audio_type_filter()
    w._refresh_audio_list()


def _rows(w):
    """{rel: Type cell} for what the audio list is currently showing."""
    tree = w._audio_tree
    return {k: tree.set(k, "type") for k in tree.get_children()}


# ---- the Type filter -----------------------------------------------------

SNIPPET = "audio/00m45s375 - idx0206 - Good Times Bad Times Snippet.wav"
CHEERING = "audio/01m01s795 - idx0510 - Cheering.wav"
BLIP = "audio/00m00s074 - idx0290.wav"


def test_music_filter_holds_only_music_when_the_folder_names_music(app):
    """His folder: the songs are identified, so a long Sound FX is a Sound FX
    and the Music list holds nothing that says otherwise."""
    w = _stern(app)
    _load_audio(w, [_Slot(SNIPPET, 45.375), _Slot(CHEERING, 61.795),
                    _Slot(BLIP, 0.074)],
                {SNIPPET: "music", CHEERING: "sfx", BLIP: "other"})

    assert _rows(w)[CHEERING] == "Sound FX"       # unfiltered: as classified

    w.audio_type_var.set("Music")
    w._refresh_audio_list()
    shown = _rows(w)
    assert set(shown) == {SNIPPET}, "a Sound FX row sat in the Music list"
    assert set(shown.values()) == {"Music"}

    w.audio_type_var.set("Sound FX")
    w._refresh_audio_list()
    assert set(_rows(w)) == {CHEERING}

    w.audio_type_var.set("Other")
    w._refresh_audio_list()
    assert set(_rows(w)) == {BLIP}
    w.audio_type_var.set("All types")
    w._refresh_audio_list()


def test_long_sfx_is_music_on_a_folder_that_names_no_music(app):
    """Led Zeppelin 1.22 has no music banks — its songs are cat-0 sounds the
    Sound Test names "SE FX SEQ ...".  There the length rule still runs, and
    the Type column says Music too, so the list stays self-consistent."""
    w = _stern(app)
    song = "audio/03m39s200 - idx0236 - SE FX SEQ ROCK AND ROLL.wav"
    _load_audio(w, [_Slot(song, 219.2), _Slot(BLIP, 0.074)],
                {song: "sfx", BLIP: "sfx"})

    assert _rows(w)[song] == "Music", "the promoted row must say what it is"
    assert _rows(w)[BLIP] == "Sound FX"

    w.audio_type_var.set("Music")
    w._refresh_audio_list()
    assert set(_rows(w)) == {song}

    w.audio_type_var.set("Sound FX")
    w._refresh_audio_list()
    assert set(_rows(w)) == {BLIP}, "a row promoted to Music showed twice"
    w.audio_type_var.set("All types")
    w._refresh_audio_list()


def test_type_column_and_filter_agree_after_a_rename_names_music(app):
    """Categorising one slot as music turns the length fallback off for the
    rest of the folder — the filter's rules must not be frozen at scan time."""
    w = _stern(app)
    _load_audio(w, [_Slot(SNIPPET, 45.375), _Slot(CHEERING, 61.795)],
                {SNIPPET: "sfx", CHEERING: "sfx"})
    w.audio_type_var.set("Music")
    w._refresh_audio_list()
    assert set(_rows(w)) == {SNIPPET, CHEERING}     # nothing names music yet

    w._audio_categories[SNIPPET] = "music"          # what a rename does
    w._refresh_audio_type_filter()
    w._refresh_audio_list()
    assert set(_rows(w)) == {SNIPPET}
    w.audio_type_var.set("All types")
    w._refresh_audio_list()


# ---- the maximized window ------------------------------------------------

def test_maximized_state_is_saved_and_restored(app, monkeypatch):
    """A maximized window has to come back maximized, and the geometry kept
    alongside it is the last NORMAL one — not the maximized rectangle, which
    would restore a screen-sized loose window on un-maximize."""
    app._last_normal_geometry = "900x1000+40+30"
    monkeypatch.setattr(type(app), "_window_is_maximized", lambda self: True)
    app._save_settings()
    assert app._settings["window_maximized"] is True
    assert app._settings["window_geometry"] == "900x1000+40+30"

    calls = []
    monkeypatch.setattr(type(app), "_maximize_window",
                        lambda self: calls.append(True))
    app._restore_window_maximized()
    assert calls == [True]

    # ...and a normal window records neither.
    monkeypatch.setattr(type(app), "_window_is_maximized", lambda self: False)
    app._save_settings()
    assert app._settings["window_maximized"] is False
    app._restore_window_maximized()
    assert calls == [True], "restored a maximize nobody asked for"


def test_configure_tracker_ignores_the_maximized_rectangle(app, monkeypatch):
    """_on_root_configure is what keeps the un-maximized size; it must not
    record anything while the window is zoomed, or the two get confused."""
    class _Ev:
        widget = None

    ev = _Ev()
    ev.widget = app.root
    monkeypatch.setattr(type(app), "_window_is_maximized", lambda self: False)
    app._last_normal_geometry = None
    app._on_root_configure(ev)
    normal = app._last_normal_geometry
    assert normal and "x" in normal

    monkeypatch.setattr(type(app), "_window_is_maximized", lambda self: True)
    app._on_root_configure(ev)
    assert app._last_normal_geometry == normal

    # A child widget's own <Configure> travels up the bindtags to the root
    # binding; it is not the window's geometry and must be ignored.
    monkeypatch.setattr(type(app), "_window_is_maximized", lambda self: False)
    ev.widget = app.window._notebook
    app._last_normal_geometry = "sentinel"
    app._on_root_configure(ev)
    assert app._last_normal_geometry == "sentinel"


def test_real_window_state_round_trips(app):
    """The state probe reads the platform, not our own flag."""
    assert app._window_is_maximized() is False
    if not app._maximize_window():
        pytest.skip("this Tk exposes no way to maximize a window")
    app.root.update()
    if not app._window_is_maximized():
        # X11 asks its window MANAGER to maximize (that is what the -zoomed
        # attribute does), and CI's bare xvfb runs none — Tk accepts the
        # request and nobody acts on it.  There is no real maximized state
        # to read back on such a display, so there is nothing here to test;
        # the probe is exercised for real on any desktop, CI's Windows and
        # macOS runners included.
        pytest.skip("no window manager honoured the maximize request")
    # The probe saw the platform's own maximized state rather than echoing
    # something we set, so the way back out must read false again.
    app.root.state("normal")
    app.root.update()
    assert app._window_is_maximized() is False


# ---- the sortable all-settings list --------------------------------------

def _srow(label, default, lo, hi, adj_id, status=""):
    return {"id": adj_id, "name": "AD_" + label.replace(" ", "_"),
            "label": label, "default": default, "min": lo, "max": hi,
            "step": 1, "labels": None, "status": status}


SETTINGS = [
    _srow("TICKET DISPENSER REST TIME MS", 1200, 0, 5000, 0x11),
    _srow("BALL SAVE TIME", 7, 0, 30, 0x22),
    _srow("MASTER VOLUME SETTING", 64, 0, 64, 0x10, status="service"),
    _srow("ALLOW TOPPER CHEATS", 0, 0, 1, 0x33, status="debug"),
]


def _fill(w, rows=SETTINGS):
    w._settings_all_rows = list(rows)
    w._settings_fill_all_tree()


def _labels(w):
    tree = w._settings_all_tree
    return [tree.item(k, "text").split("  (")[0] for k in tree.get_children()]


def _click(w, col):
    """Invoke the column header's own command, the way a click does."""
    cmd = w._settings_all_tree.heading(col, "command")
    w._settings_all_tree.tk.call(cmd)


def test_all_settings_list_opens_in_firmware_order(app):
    w = _stern(app)
    _fill(w)
    assert _labels(w) == [r["label"] for r in SETTINGS]
    assert w._settings_all_sort == (None, False)


def test_value_header_sorts_numerically_biggest_first(app):
    """"I was trying to find the item with the biggest length and sorting
    would put that to the top."  1200 above 64 — sorted as numbers, not as
    the text in the cell."""
    w = _stern(app)
    _fill(w)
    _click(w, "value")
    assert _labels(w)[0] == "TICKET DISPENSER REST TIME MS"
    assert _labels(w) == ["TICKET DISPENSER REST TIME MS",
                          "MASTER VOLUME SETTING", "BALL SAVE TIME",
                          "ALLOW TOPPER CHEATS"]
    assert "▼" in w._settings_all_tree.heading("value", "text")

    _click(w, "value")                     # flip
    assert _labels(w)[0] == "ALLOW TOPPER CHEATS"
    assert "▲" in w._settings_all_tree.heading("value", "text")

    _click(w, "value")                     # back to the firmware's order
    assert _labels(w) == [r["label"] for r in SETTINGS]
    assert w._settings_all_sort == (None, False)
    assert w._settings_all_tree.heading("value", "text") == "On card"


def test_every_column_sorts(app):
    w = _stern(app)
    _fill(w)
    _click(w, "#0")
    assert _labels(w) == sorted(r["label"] for r in SETTINGS)
    _click(w, "range")
    assert _labels(w)[-1] == "TICKET DISPENSER REST TIME MS"   # widest range
    _click(w, "status")
    assert _labels(w)[0] in ("BALL SAVE TIME",
                             "TICKET DISPENSER REST TIME MS")  # "" Adjustments
    # Sorting never breaks the row identity the editor looks up.
    tree = w._settings_all_tree
    for iid in tree.get_children():
        row = w._settings_all_items[iid]
        assert tree.item(iid, "text").startswith(row["label"])


def test_sorting_survives_the_hidden_only_filter(app):
    w = _stern(app)
    _fill(w)
    _click(w, "value")
    w._settings_hidden_only.set(True)
    w._settings_fill_all_tree()
    assert _labels(w) == ["MASTER VOLUME SETTING", "ALLOW TOPPER CHEATS"]
    w._settings_hidden_only.set(False)
    w._settings_fill_all_tree()
