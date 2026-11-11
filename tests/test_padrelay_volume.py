"""PAD-957: on a Mac the Emulate tab's Volume and Mute reach the speaker.

The Mac's speaker is ffplay, which reads nothing once it plays, so the slider
and Mute did nothing there. The box's relay now scales the samples by a copy
of the tab's audio_ctl.json that padbox.sh keeps in the box. These pin the
relay's half: the level it reads off the file, and the scaling itself.
(Proven end to end in the Mac container on Docker Desktop: a game's sound
went to digital zero on Mute and to half and a quarter on the slider.)
"""
import importlib.util
import json
import os
import struct

import pytest

RELAY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools", "spike2_emu", "padrelay.py")


@pytest.fixture(scope="module")
def relay():
    spec = importlib.util.spec_from_file_location("padrelay", RELAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # import-safe: the relay is in main()
    return mod


def _pcm(*samples):
    return struct.pack("<%dh" % len(samples), *samples)


def _write(path, **data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, str(path))


def test_full_volume_passes_the_bytes_through_untouched(relay):
    b = _pcm(32767, -32768, 1, -1)
    assert relay.scale(b, 1.0) is b


def test_mute_is_digital_silence_of_the_same_length(relay):
    assert relay.scale(_pcm(32767, -32768, 5), 0.0) == bytes(6)


def test_in_between_scales_every_sample(relay):
    out = relay.scale(_pcm(32767, -32768, 1000, -1000), 0.5)
    assert struct.unpack("<4h", out) == (16383, -16384, 500, -500)


def test_the_meter_says_every_30_s_what_left_and_how_loud(relay):
    """PAD-1109: a silent Mac run had nothing in the app's log saying whether
    the box sent sound or silence; the relay now says it every 30 s."""
    t = [0.0]
    m = relay.Meter(clock=lambda: t[0])
    m.add(_pcm(16384, -32768, 100) + b"\x01")     # odd byte: counted, not read
    assert m.line(now=29.9) is None
    s = m.line(now=30.0)
    assert s.startswith("[padrelay] last 30 s: 0 KB to the player")
    assert s.endswith("loudest 0.0 dBFS")
    m.add(bytes(176400 * 30))                     # 30 s of digital silence
    s = m.line(now=60.0)
    assert "5167 KB to the player (172 KB/s)" in s and s.endswith("digital silence")
    m.add(_pcm(3277))
    assert m.line(now=90.0).endswith("loudest -20.0 dBFS")


def test_the_file_says_the_level(relay, tmp_path):
    p = tmp_path / "audio_ctl.json"
    _write(p, gain=0.4, muted=False)
    assert relay.read_gain(str(p)) == pytest.approx(0.4)
    _write(p, gain=0.4, muted=True)
    assert relay.read_gain(str(p)) == 0.0
    _write(p, gain=7, muted=False)
    assert relay.read_gain(str(p)) == 1.0
    p.write_text("not json")
    assert relay.read_gain(str(p)) is None
    p.write_text("[1, 2]")
    assert relay.read_gain(str(p)) is None
    assert relay.read_gain(str(tmp_path / "missing.json")) is None


def test_the_relay_follows_the_file_and_keeps_its_level_without_one(relay, tmp_path):
    p = tmp_path / "audio_ctl.json"
    vol = relay.Volume(str(p))
    assert vol.poll(now=0.0) == 1.0           # no file yet: full volume
    _write(p, gain=0.5, muted=False)
    assert vol.poll(now=0.1) == 1.0           # not looked at again so soon
    assert vol.poll(now=0.3) == 0.5
    _write(p, gain=0.5, muted=True)
    assert vol.poll(now=0.6) == 0.0
    p.write_text("{")                         # a torn copy changes nothing
    assert vol.poll(now=0.9) == 0.0
    os.remove(str(p))                         # nor does a file being replaced
    assert vol.poll(now=1.2) == 0.0
    _write(p, gain=0.25, muted=False)
    assert vol.poll(now=1.5) == 0.25


def test_no_volume_file_is_a_plain_relay(relay):
    vol = relay.Volume(None)
    assert vol.path is None
    assert vol.poll(now=10.0) == 1.0


# ---- PAD-1109: the Mac reads the FIFO over docker exec (--pipe) ------------

class _Vol:
    def __init__(self, g):
        self.path, self.g = "ctl", g

    def poll(self):
        return self.g


def test_pump_keeps_samples_whole_scales_and_meters(relay):
    chunks = [_pcm(1000, -1000) + b"\x10", b"\x00" + _pcm(4000), b""]
    out, said = [], []
    t = [0.0]
    meter = relay.Meter(clock=lambda: t[0])

    def read(_n):
        t[0] += 20.0
        return chunks.pop(0)
    relay.pump(read, out.append, _Vol(0.5), said.append, meter)
    got = b"".join(out)
    assert struct.unpack("<4h", got) == (500, -500, 8, 2000)
    assert said and said[0].startswith("[padrelay] last 40 s:")


def test_pipe_gives_up_and_says_so_when_no_fifo_appears(relay, tmp_path, capsys):
    t = [0.0]

    def sleep(s):
        t[0] += s
    rc = relay.pipe_main([str(tmp_path / "audio.fifo"), ""], out=None,
                         clock=lambda: t[0], sleep=sleep)
    assert rc == 1
    assert "this run is silent" in capsys.readouterr().err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_pipe_copies_the_fifo_to_its_output_at_the_volume(relay, tmp_path, capsys, monkeypatch):
    import io
    import threading
    monkeypatch.delenv("PAD_AUDIO_LEAD_MS", raising=False)   # plain is the default
    fifo = str(tmp_path / "audio.fifo")
    os.mkfifo(fifo)
    ctl = tmp_path / "ctl.json"
    _write(ctl, gain=0.5, muted=False)

    def guest():
        with open(fifo, "wb") as w:
            w.write(_pcm(2000, -2000, 30000))
    threading.Thread(target=guest, daemon=True).start()
    out = io.BytesIO()
    assert relay.pipe_main([fifo, str(ctl)], out=out) == 0
    assert struct.unpack("<3h", out.getvalue()) == (1000, -1000, 15000)
    err = capsys.readouterr().err
    assert "over docker exec" in err and "6 bytes forwarded" in err


# ---- PAD-1109: the paced stream the Mac's player never waits for -----------

class _Clock:
    """A clock the pump's own sleeps advance; `at` hooks run when it passes."""

    def __init__(self):
        self.t = 0.0
        self.hooks = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        for when, fn in list(self.hooks):
            if self.t >= when:
                self.hooks.remove((when, fn))
                fn()


def _paced(relay, feed, lead_ms=350, close_at=0.5, vol=None, settle=0.0, **kw):
    """Run paced_pump over a real pipe: `feed` is written by a thread (a
    pipe's buffer is small), the pipe is closed when the fake clock passes
    `close_at`; `settle` seconds of REAL time at the first sleep let the
    reader take the whole feed first."""
    import threading
    import time as _time
    r, w = os.pipe()

    def feeder():
        os.write(w, feed)
    threading.Thread(target=feeder, daemon=True).start()
    clk = _Clock()
    if settle:
        clk.hooks.append((0.0, lambda: _time.sleep(settle)))
    def close():
        # fake time outruns real time; the reader needs a moment to see EOF
        os.close(w)
        _time.sleep(0.2)
    clk.hooks.append((close_at, close))
    out, said = [], []
    n = relay.paced_pump(r, out.append, vol or relay.Volume(None), said.append,
                         44100, 2, lead_ms, clock=clk.now, sleep=clk.sleep, **kw)
    os.close(r)
    return b"".join(out), said, n


def test_paced_stream_is_continuous_real_time_with_silence_for_gaps(relay):
    sound = _pcm(*([1000, -1000] * 441))            # 10 ms of sound
    out, said, n = _paced(relay, sound, close_at=0.5, settle=0.2)
    bps = 176400
    lead = bps * 350 // 1000
    # the sound, whole and frame-aligned, inside the first lead; silence
    # everywhere else; in all what 0.5 s of real time needs plus the lead
    at = out.index(sound)
    assert at % 4 == 0 and at <= lead + 4 * 1764, at   # the first write may be the lead alone
    assert out[:at] == bytes(at)
    assert out[at + len(sound):at + len(sound) + 4000] == bytes(4000)
    assert abs(n - (bps // 2 + lead)) <= 2 * 1764, n
    assert n % 4 == 0


def test_paced_stream_drops_a_source_that_ran_too_far_ahead(relay):
    bps = 176400
    two_s = bytes(range(256)) * (2 * bps // 256)   # 2 s, recognisable bytes
    out, said, n = _paced(relay, two_s, close_at=0.05, settle=0.4)
    # a source 2 s ahead is cut back to the 350 ms lead: not everything
    # passes, and what the end flushes is the source's own tail
    assert n < len(two_s), n
    assert out.endswith(two_s[-1764:])


def test_paced_stream_scales_by_the_volume_and_says_what_it_filled(relay, tmp_path):
    p = tmp_path / "ctl.json"
    _write(p, gain=0.5, muted=False)
    vol = relay.Volume(str(p))
    sound = _pcm(*([2000, -2000] * 441))
    relay_report = relay.REPORT_S
    try:
        relay.REPORT_S = 0.3
        out, said, n = _paced(relay, sound, close_at=0.5, vol=vol, settle=0.2)
    finally:
        relay.REPORT_S = relay_report
    half = _pcm(*([1000, -1000] * 441))
    assert half in out and out.index(half) % 4 == 0
    assert said and "silence filled in" in said[0], said


def test_the_fmt_file_gives_the_rate_and_channels(relay, tmp_path):
    p = tmp_path / "audio.fmt"
    assert relay.read_fmt(str(p)) == (44100, 2)
    p.write_text("48000 1" + chr(10))
    assert relay.read_fmt(str(p)) == (48000, 1)
    p.write_text("junk")
    assert relay.read_fmt(str(p)) == (44100, 2)


def test_pace_reads_stdin_and_writes_a_paced_stream(relay, monkeypatch, capsys):
    """--pace on the Mac: the app's binary between docker exec and ffplay."""
    import io
    import threading
    import time as _time
    monkeypatch.delenv("PAD_AUDIO_LEAD_MS", raising=False)
    r, w = os.pipe()
    sound = _pcm(*([3000, -3000] * 441))
    clk = _Clock()

    def feeder():
        os.write(w, sound)
    threading.Thread(target=feeder, daemon=True).start()
    clk.hooks.append((0.0, lambda: _time.sleep(0.2)))

    def close():
        os.close(w)
        _time.sleep(0.2)
    clk.hooks.append((0.3, close))
    out = io.BytesIO()
    rc = relay.pace_main(["44100", "2"], fd=r, out=out, clock=clk.now, sleep=clk.sleep)
    os.close(r)
    assert rc == 0
    got = out.getvalue()
    assert sound in got and got.index(sound) % 4 == 0
    assert len(got) >= 176400 * 350 // 1000
    err = capsys.readouterr().err
    assert "pacing the stream on the Mac: 44100 Hz x 2 ch, 350 ms ahead" in err
    assert "bytes paced to the player" in err
    assert relay.pace_main(["x"]) == 2
