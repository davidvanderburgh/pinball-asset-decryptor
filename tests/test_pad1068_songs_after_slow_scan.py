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
