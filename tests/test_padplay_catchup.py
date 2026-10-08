"""PAD-456: the emulator's speaker catches up instead of staying late for good.

A tester's James Bond LE 1.06 ran in sync for 45 s, then its sound trailed the
picture by 18-20 s for the rest of the run. padplay.py (the one player behind
every emulator's sound: the WSL bridge, macOS and Linux) queued whatever
reached it and had no way to give lateness back: the source and the speaker
both run at 1x, so a backlog from any hiccup - a speaker that stalled, a socket
that held its bytes and let them go at once - stayed for the rest of the run.

These run the real player against a fake sound card, so they need no speaker
and make no sound.
"""
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import types

import pytest

from tests._watch_event_filter import event_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PADPLAY = os.path.join(ROOT, "tools", "spike2_emu", "padplay.py")
pytestmark = pytest.mark.skipif(not os.path.isfile(PADPLAY), reason="rig not present")
AWK = shutil.which("awk")


class _FakeStream:
    """A sound card that pulls 10 ms blocks at wall-clock speed."""

    def __init__(self, samplerate, channels, callback, **_kw):
        self.frames = samplerate // 100
        self.need = self.frames * channels * 2
        self.callback = callback
        self.stop = threading.Event()

    def __enter__(self):
        def pull():
            nxt = time.monotonic()
            while not self.stop.is_set():
                self.callback(bytearray(self.need), self.frames, None, None)
                nxt += 0.01
                time.sleep(max(0.0, nxt - time.monotonic()))
        self.thread = threading.Thread(target=pull, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(2)


@pytest.fixture
def padplay(monkeypatch):
    sd = types.ModuleType("sounddevice")
    sd.RawOutputStream = _FakeStream
    sd.query_hostapis = lambda *a: []
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    spec = importlib.util.spec_from_file_location("padplay_pad456", PADPLAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k in ("PAD_AUDIO_CTL", "PAD_AUDIO_PREBUFFER_MS", "PAD_AUDIO_MAX_LATE_MS"):
        monkeypatch.delenv(k, raising=False)
    return mod


def test_catch_up_leaves_a_normal_queue_alone(padplay):
    # 44100 x 2 ch: 176400 bytes a second. ~200 ms is where the queue rests.
    bps, frame = 176400, 4
    assert padplay.catch_up(None, bps * 350 // 1000, bps * 750 // 1000, frame) == 0
    assert padplay.catch_up(bps * 200 // 1000, bps * 350 // 1000, bps * 750 // 1000, frame) == 0
    assert padplay.catch_up(bps * 750 // 1000, bps * 350 // 1000, bps * 750 // 1000, frame) == 0


def test_catch_up_drops_a_standing_backlog_back_to_the_cushion(padplay):
    bps, frame = 176400, 4
    target, ceiling = bps * 350 // 1000, bps * 750 // 1000
    least = bps * 20 + 2                      # 20 s behind, mid-frame
    cut = padplay.catch_up(least, target, ceiling, frame)
    assert cut % frame == 0                   # whole frames: L and R stay paired
    assert target <= least - cut < target + frame


def _serve(burst, rate_bps, seconds):
    """A relay that hands over `burst` bytes at once (a transport letting a
    stall go), then streams at 1x for `seconds` and hangs up."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        try:
            conn.sendall(b"\0" * burst)
            t0 = time.monotonic()
            sent = 0
            while time.monotonic() - t0 < seconds:
                due = int((time.monotonic() - t0) * rate_bps) // 2 * 2
                if due > sent:
                    conn.sendall(b"\0" * (due - sent))
                    sent = due
                time.sleep(0.01)
        finally:
            conn.close()
            srv.close()
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


def test_a_20_second_backlog_is_skipped_not_played_late(padplay, monkeypatch, capsys):
    rate = 8000                               # mono 16-bit: 16000 bytes a second
    bps = rate * 2
    port = _serve(burst=bps * 20, rate_bps=bps, seconds=4)
    monkeypatch.setattr(sys, "argv", ["padplay.py", "127.0.0.1", str(port), str(rate), "1"])
    t0 = time.monotonic()
    padplay.main()
    took = time.monotonic() - t0
    out = capsys.readouterr().out
    # Playing the backlog out would take 20 s past the source's last byte.
    assert took < 12, out
    assert "to catch up" in out, out
    skipped = sum(int(line.split("skipped ")[1].split(" ms")[0])
                  for line in out.splitlines() if "to catch up" in line)
    assert skipped >= 18000, out


@pytest.mark.skipif(not AWK, reason="no awk")
def test_the_log_the_user_sends_says_where_the_sound_stood():
    """The report came with nothing in the app's log that could say whether the
    game wrote late or the speaker played late. watch.sh's real [event] filter
    now carries the player's catch-up and dead-feed lines and the guest's 30 s
    audio summary; the player's 5 s queue line stays out of it."""
    lines = [
        "[padplay] queue stayed above 19840 ms for 2 s - skipped 19490 ms to catch up",
        "[padplay] no data for 25 s - transport presumed dead, exiting for a fresh connection",
        "[aud] --- 30117 ms --- writei calls=6487 frames=1173600 (26.6 s @ 44100 Hz x 2 ch)"
        "  main played=564600 dropped=0  center=586800  gate=0  latency=186/185 ms  fifo=0 ms",
        "[padplay] queue  204 ms  underruns    0  fed 15471200  played 15435176  skipped 0 ms",
        "[aud] voice[0] stream=0x00000000 pos=0 queue=0x00000000 en=0 vol=0/0 ch=0",
    ]
    out = subprocess.run([AWK, event_filter()], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["[event] " + l for l in lines[:3]]
