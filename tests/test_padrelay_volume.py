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
def test_pipe_copies_the_fifo_to_its_output_at_the_volume(relay, tmp_path, capsys):
    import io
    import threading
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
