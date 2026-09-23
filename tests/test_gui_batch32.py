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

The list tests drive the web tabs (webui/tabs/audio.py, webui/tabs/defaults.py)
through tests/webui_harness.py; the window-state tests drive App and the
desktop host (webui/host.py) directly.
"""
import os
import types

from tests.webui_harness import web_app


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


def _load_audio(w, slots, cats):
    svc = w.window.service("audio")

    def _set():
        svc._slots = list(slots)
        svc._by_rel = {s.rel_path: s for s in slots}
        svc._assign = {}
        svc._changed = set()
        svc._cats = dict(cats)
        svc._refresh_type_filter()
        svc._refresh_list()
    w.run(_set)
    return svc


def _rows(w):
    """{rel: Type cell} for what the audio list is currently showing."""
    return {r["k"]: r["type"] for r in w.state("audio")["rows"]}


def _type(w, value):
    assert w.call("audio.set_type", value) is True


# ---- the Type filter -----------------------------------------------------

SNIPPET = "audio/00m45s375 - idx0206 - Good Times Bad Times Snippet.wav"
CHEERING = "audio/01m01s795 - idx0510 - Cheering.wav"
BLIP = "audio/00m00s074 - idx0290.wav"


def test_music_filter_holds_only_music_when_the_folder_names_music(tmp_path):
    """His folder: the songs are identified, so a long Sound FX is a Sound FX
    and the Music list holds nothing that says otherwise."""
    with web_app(tmp_path, mfr="stern") as w:
        _load_audio(w, [_Slot(SNIPPET, 45.375), _Slot(CHEERING, 61.795),
                        _Slot(BLIP, 0.074)],
                    {SNIPPET: "music", CHEERING: "sfx", BLIP: "other"})

        assert _rows(w)[CHEERING] == "Sound FX"   # unfiltered: as classified

        _type(w, "Music")
        shown = _rows(w)
        assert set(shown) == {SNIPPET}, "a Sound FX row sat in the Music list"
        assert set(shown.values()) == {"Music"}

        _type(w, "Sound FX")
        assert set(_rows(w)) == {CHEERING}

        _type(w, "Other")
        assert set(_rows(w)) == {BLIP}
        _type(w, "All types")


def test_long_sfx_is_music_on_a_folder_that_names_no_music(tmp_path):
    """Led Zeppelin 1.22 has no music banks — its songs are cat-0 sounds the
    Sound Test names "SE FX SEQ ...".  There the length rule still runs, and
    the Type column says Music too, so the list stays self-consistent."""
    song = "audio/03m39s200 - idx0236 - SE FX SEQ ROCK AND ROLL.wav"
    with web_app(tmp_path, mfr="stern") as w:
        _load_audio(w, [_Slot(song, 219.2), _Slot(BLIP, 0.074)],
                    {song: "sfx", BLIP: "sfx"})

        assert _rows(w)[song] == "Music", "the promoted row must say what it is"
        assert _rows(w)[BLIP] == "Sound FX"

        _type(w, "Music")
        assert set(_rows(w)) == {song}

        _type(w, "Sound FX")
        assert set(_rows(w)) == {BLIP}, "a row promoted to Music showed twice"
        _type(w, "All types")


def test_type_column_and_filter_agree_after_a_rename_names_music(tmp_path):
    """Categorising one slot as music turns the length fallback off for the
    rest of the folder — the filter's rules must not be frozen at scan time."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load_audio(w, [_Slot(SNIPPET, 45.375),
                              _Slot(CHEERING, 61.795)],
                          {SNIPPET: "sfx", CHEERING: "sfx"})
        _type(w, "Music")
        assert set(_rows(w)) == {SNIPPET, CHEERING}  # nothing names music yet

        def _rename():
            svc._cats[SNIPPET] = "music"            # what a rename does
            svc._refresh_type_filter()
            svc._refresh_list()
        w.run(_rename)
        assert set(_rows(w)) == {SNIPPET}
        _type(w, "All types")


# ---- the maximized window ------------------------------------------------

def test_maximized_state_is_saved_and_restored(tmp_path, monkeypatch):
    """A maximized window has to come back maximized, and the geometry kept
    alongside it is the last NORMAL one — not the maximized rectangle, which
    would restore a screen-sized loose window on un-maximize."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        app._last_normal_geometry = "900x1000+40+30"
        monkeypatch.setattr(type(app), "_window_is_maximized",
                            lambda self: True)
        w.run(app._save_settings)
        assert app._settings["window_maximized"] is True
        assert app._settings["window_geometry"] == "900x1000+40+30"
        # the desktop host opens the window from this, maximized
        assert w.run(app.saved_geometry) == (900, 1000, 40, 30, True)

        # ...and a normal window records neither.
        monkeypatch.setattr(type(app), "_window_is_maximized",
                            lambda self: False)
        w.run(app._save_settings)
        assert app._settings["window_maximized"] is False
        assert w.run(app.saved_geometry)[4] is False, \
            "restored a maximize nobody asked for"


def test_configure_tracker_ignores_the_maximized_rectangle():
    """The host's resize tracker (webui/host._remember_geometry) is what
    keeps the un-maximized size; it must not record anything while the
    window is zoomed, or the two get confused."""
    from pinball_decryptor.webui import host as host_mod
    app = types.SimpleNamespace(_last_normal_geometry=None, _settings={})
    ctx = types.SimpleNamespace(app=app)
    host = types.SimpleNamespace(window=types.SimpleNamespace(x=40, y=30),
                                 _maximized=False)
    host_mod._remember_geometry(ctx, host, 900, 1000)
    normal = app._last_normal_geometry
    assert normal == "900x1000+40+30"
    assert app._settings["window_geometry"] == normal

    host._maximized = True
    host_mod._remember_geometry(ctx, host, 2560, 1400)
    assert app._last_normal_geometry == normal
    assert app._settings["window_geometry"] == normal


def test_real_window_state_round_trips():
    """The state probe reads the desktop host, not our own flag."""
    from pinball_decryptor.app import App
    from pinball_decryptor.webui.host import Host
    app = App.__new__(App)
    host = Host(types.SimpleNamespace(), "native")
    app.ctx = types.SimpleNamespace(host=host)
    assert app._window_is_maximized() is False
    host._maximized = True              # pywebview's "maximized" event
    assert app._window_is_maximized() is True
    host._maximized = False             # ...and its "restored" event
    assert app._window_is_maximized() is False
    app.ctx = types.SimpleNamespace(host=None)      # no desktop window
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
    from tests.test_webui_defaults import _load
    _load(w, every=rows)


def _labels(w):
    return [r["caption"].split("  (")[0] for r in w.state("defaults")["all"]]


def _click(w, col):
    """The column header's click, the way the page sends it."""
    assert w.call("defaults.sort_all", col) is True


def test_all_settings_list_opens_in_firmware_order(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w)
        assert _labels(w) == [r["label"] for r in SETTINGS]
        assert w.state("defaults")["sort"] == {"key": None, "desc": False}


def test_value_header_sorts_numerically_biggest_first(tmp_path):
    """"I was trying to find the item with the biggest length and sorting
    would put that to the top."  1200 above 64 — sorted as numbers, not as
    the text in the cell."""
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w)
        _click(w, "value")
        assert _labels(w) == ["TICKET DISPENSER REST TIME MS",
                              "MASTER VOLUME SETTING", "BALL SAVE TIME",
                              "ALLOW TOPPER CHEATS"]
        assert w.state("defaults")["sort"] == {"key": "value", "desc": True}

        _click(w, "value")                     # flip
        assert _labels(w)[0] == "ALLOW TOPPER CHEATS"
        assert w.state("defaults")["sort"] == {"key": "value", "desc": False}

        _click(w, "value")                     # back to the firmware's order
        assert _labels(w) == [r["label"] for r in SETTINGS]
        assert w.state("defaults")["sort"] == {"key": None, "desc": False}


def test_every_column_sorts(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w)
        _click(w, "setting")
        assert _labels(w) == sorted(r["label"] for r in SETTINGS)
        _click(w, "range")
        assert _labels(w)[-1] == "TICKET DISPENSER REST TIME MS"  # widest
        _click(w, "status")
        assert _labels(w)[0] in ("BALL SAVE TIME",
                                 "TICKET DISPENSER REST TIME MS")  # Adjustments
        # Sorting never breaks the row identity the editor looks up.
        by_name = {r["name"]: r for r in SETTINGS}
        for row in w.state("defaults")["all"]:
            assert row["caption"].startswith(by_name[row["name"]]["label"])


def test_sorting_survives_the_hidden_only_filter(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w)
        _click(w, "value")
        w.call("ui.set", "defaults", "hidden_only", True)
        assert _labels(w) == ["MASTER VOLUME SETTING", "ALLOW TOPPER CHEATS"]
        w.call("ui.set", "defaults", "hidden_only", False)
