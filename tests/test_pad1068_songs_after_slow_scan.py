"""PAD-1068: the Expression lights page's songs come in when the Audio scan does, however long it takes.

BEN (Led Zeppelin 1.21): "The app suggests that you can play the audio and have the expression light show play at the
same time but I cannot hear the audio." His Audio scan ran past two minutes; the page waited at most 120 s for it and
then read an empty song list once, so the game's own show said "(not one of this project's songs)" and played silent.
"""
import inspect
import threading
import time
import types

from pinball_decryptor.webui import window as W
from pinball_decryptor.webui.tabs import audio as AT
from pinball_decryptor.webui.tabs import lights as LT


class _Store:
    def __init__(self):
        self.d = {}

    def set(self, ns, **kw):
        self.d.setdefault(ns, {}).update(kw)

    def get(self, ns, k, default=None):
        return self.d.get(ns, {}).get(k, default)


class _Loop:
    def post(self, fn, *a):
        fn(*a)


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def _slot(rel, secs):
    return types.SimpleNamespace(rel_path=rel, abs_path="C:/p/" + rel, duration=secs, info=object())


class _Audio:
    def __init__(self):
        self._slots, self._assign, self._scan_dir, self._scanning = [], {}, "", True
        self.scans = 0

    def scan(self):
        self.scans += 1


class _Win:
    def __init__(self, folder):
        self.ctx = types.SimpleNamespace(store=_Store(), loop=_Loop())
        self.write_assets_var = _Var(folder)
        self.audio = _Audio()

    def service(self, ns):
        return self.audio if ns == "audio" else None


def _wait_songs(tab, n, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if len(tab.get("songs") or []) == n:
            return tab.get("songs")
        time.sleep(0.02)
    return tab.get("songs")


def test_a_scan_that_ends_after_any_wait_still_brings_the_songs():
    win = _Win("C:/proj")
    tab = LT.LightsTab(win)
    tab._songs_now()                                    # the page read while the scan still ran: nothing yet
    assert _wait_songs(tab, 0) == []
    win.audio._slots = [_slot("audio/idx0229.wav", 289.0), _slot("audio/idx0001.wav", 1.5)]
    win.audio._scan_dir, win.audio._scanning = "C:/proj", False
    tab.on_audio_scanned("C:/proj")                     # minutes later: the scan is in
    songs = _wait_songs(tab, 1)
    assert [s["slot"] for s in songs] == [229] and songs[0]["seconds"] == 289.0


def test_another_projects_scan_leaves_the_songs_alone():
    win = _Win("C:/proj")
    tab = LT.LightsTab(win)
    tab.set(songs=[{"slot": 7}])
    win.audio._slots = [_slot("audio/idx0229.wav", 289.0)]
    tab.on_audio_scanned("C:/other")
    time.sleep(0.2)
    assert tab.get("songs") == [{"slot": 7}]


def test_the_page_no_longer_gives_up_on_a_slow_scan():
    win = _Win("C:/proj")
    tab = LT.LightsTab(win)
    win.audio._scanning = False                         # this project not scanned yet
    before = {t.name for t in threading.enumerate()}
    tab._audio_ready()                                  # starts the scan, and waits on nothing
    assert win.audio.scans == 1
    assert "lights-songs" not in {t.name for t in threading.enumerate()} - before


def test_every_finished_audio_scan_is_announced_to_the_tabs():
    seen = []
    tab = type("T", (), {"ns": "x", "on_audio_scanned": lambda self, folder: seen.append(folder)})()
    host = types.SimpleNamespace(tabs=[tab])
    W.WebWindow.audio_scanned(types.SimpleNamespace(_fan=lambda name, *a: W.WebWindow._fan(host, name, *a)),
                               "C:/proj")
    assert seen == ["C:/proj"]
    src = inspect.getsource(AT.AudioTab._populate_after_scan)
    assert "audio_scanned" in src


# ---- BEN, after the fix above shipped: "still no sound", with a 9 s scan ------------------------------------------
def test_length_prefixed_sound_names_are_their_records():
    from pinball_decryptor.plugins.stern import sound_modes as SM
    assert SM.slot_idx("audio/02m21s867 - idx0384 - music - Led Zeppelin - Immigrant Song.wav") == 384
    assert SM.slot_idx(r"audio\04m49s012 - idx0229.wav") == 229
    assert SM.slot_idx("02m48s700 - idx0309.wav") == 309
    assert SM.slot_idx("audio/idx0004.wav") == 4
    assert SM.slot_idx("audio/my 02m21s867 - idx0384.wav") is None


def test_a_length_prefixed_project_has_its_songs():
    audio = _Audio()
    audio._slots = [_slot("audio/04m49s012 - idx0229.wav", 289.0), _slot("audio/00m01s500 - idx0001.wav", 1.5)]
    assert [s["slot"] for s in LT._songs(audio)] == [229]


def test_a_game_shows_song_is_kept_however_short_and_a_missing_one_is_said():
    win = _Win("C:/proj")
    win.audio._slots = [_slot("audio/idx0013.wav", 12.0)]
    win.audio._scan_dir, win.audio._scanning = "C:/proj", False
    tab = LT.LightsTab(win)
    tab.set(stock=[{"req": 62, "slot": 13}, {"req": 64, "slot": 309}])
    tab._songs_now()
    songs = _wait_songs(tab, 1)
    assert [s["slot"] for s in songs] == [13]
    why = tab.get("song_missing")
    assert list(why) == ["309"] and "idx0309" in why["309"]


def test_the_page_says_why_a_game_shows_song_is_missing():
    import os
    js = open(os.path.join(os.path.dirname(LT.__file__), "..", "static", "js", "tabs", "lights.js"),
              encoding="utf-8").read()
    assert "song_missing" in js and "missingWhy" in js
