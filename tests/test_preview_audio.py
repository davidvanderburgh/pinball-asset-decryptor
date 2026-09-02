"""The Multi-boot preview's WAV player (item 90).

NOTHING HERE OPENS A DEVICE OR MAKES A SOUND, which is the whole shape of the
file: the mixer is arithmetic and is checked as arithmetic, the backends are
handed fake ``sounddevice`` / ``winsound`` modules that record what they were
asked to do, and the one test that runs a real worker thread drives a backend
that only appends to a list.  The numbers the mixer is measured against come
from ``tools/spike2_emu/codeselect/audio.c`` - the C the card will actually
run - because a preview that mixes differently from the machine is a preview
that lies about the machine.

There is no Tk in this file, deliberately: the player is not a widget, and
keeping it out of the Tk group means these tests always RUN rather than
sometimes skipping when a worker cannot start a Tk root.
"""

import importlib
import os
import struct
import sys
import threading
import time
import wave

import numpy as np
import pytest

from pinball_decryptor.gui import preview_audio as pa


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _wav(path, samples, rate=pa.RATE, channels=2, sampwidth=2):
    """A WAV holding *samples* (a flat sequence of ints, already interleaved)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        if sampwidth == 2:
            w.writeframes(struct.pack("<%dh" % len(samples), *samples))
        else:
            # The 8-/24-bit files exist only to be refused, so the right
            # NUMBER of bytes is the whole requirement; silence will do.
            w.writeframes(bytes(len(samples) * sampwidth))
    return str(path)


def _tone(path, frames=1000, value=1000, **kw):
    ch = kw.get("channels", 2)
    return _wav(path, [value] * (frames * ch), **kw)


def _clip(values):
    """An ``(n, 2)`` int16 clip from a list of per-frame values."""
    return np.array([[v, v] for v in values], dtype=np.int16)


class FakeStream(object):
    def __init__(self, **kw):
        self.kw = kw
        self.started = self.stopped = self.closed = False
        self.callback = kw.get("callback")

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


WASAPI_HOSTAPIS = [{"name": "MME", "default_output_device": 0},
                   {"name": "Windows WASAPI", "default_output_device": 13}]


class FakeSD(object):
    """A sounddevice that never touches PortAudio.

    ``refuse(kw) -> Exception|None`` is how a test describes David's own
    machine: a WASAPI endpoint at 96 kHz that turns down a bare 44100 open."""

    def __init__(self, hostapis=(), fail=None, refuse=None, wasapi=False):
        self._hostapis = list(hostapis)
        self.fail = fail
        self.refuse = refuse
        self.streams = []
        self.asked = []
        if wasapi:
            self.WasapiSettings = self._wasapi_settings

    @staticmethod
    def _wasapi_settings(exclusive=False, auto_convert=False,
                         explicit_sample_format=False):
        return ("wasapi", auto_convert)

    def query_hostapis(self):
        return self._hostapis

    def OutputStream(self, **kw):                           # noqa: N802
        self.asked.append(kw)
        if self.fail:
            raise self.fail
        if self.refuse:
            exc = self.refuse(kw)
            if exc:
                raise exc
        s = FakeStream(**kw)
        self.streams.append(s)
        return s


class FakeWinsound(object):
    """winsound's PlaySound, recorded rather than played."""

    SND_FILENAME = 0x00020000
    SND_ASYNC = 0x0001
    SND_LOOP = 0x0008
    SND_NODEFAULT = 0x0002
    SND_PURGE = 0x0040

    def __init__(self):
        self.calls = []

    def PlaySound(self, sound, flags):                      # noqa: N802
        self.calls.append((sound, flags))


class FakeTimer(object):
    def __init__(self):
        self.pending = []

    def schedule(self, delay, fn):
        self.pending.append([delay, fn, False])
        return self

    def cancel(self):
        for entry in self.pending:
            entry[2] = True

    def fire_all(self):
        for entry in list(self.pending):
            if not entry[2]:
                entry[1]()


class RecordingBackend(object):
    """A backend for the PreviewAudio tests: it only writes down the calls."""

    name = "recorder"
    note = ""

    def __init__(self, errors=None):
        self.calls = []
        self.errors = errors or {}

    def loop(self, path):
        self.calls.append(("loop", path))
        return self.errors.get("loop", "")

    def play(self, path):
        self.calls.append(("play", path))
        return self.errors.get("play", "")

    def set_volume(self, volume):
        self.calls.append(("volume", volume))
        return ""

    def close(self):
        self.calls.append(("close", None))
        return ""


def _player(backend, why="", **kw):
    """A PreviewAudio wired to *backend*, running inline unless asked."""
    kw.setdefault("threaded", False)
    return pa.PreviewAudio(backend_factory=lambda vol: (backend, why), **kw)


# --------------------------------------------------------------------------
# importing the module costs nothing
# --------------------------------------------------------------------------

def test_import_does_not_pull_in_sounddevice(monkeypatch):
    """The hard rule: opening the app must not cost a PortAudio load.

    Proven rather than asserted from the source - sounddevice is dropped out
    of sys.modules and a finder is planted that shouts if anyone asks for it,
    then the module is imported again from scratch and a player is built and
    read."""
    asked = []

    class Spy(object):
        def find_module(self, name, path=None):
            return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "sounddevice":
                asked.append(name)
            return None

    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    monkeypatch.setattr(sys, "meta_path", [Spy()] + list(sys.meta_path))
    importlib.reload(pa)
    try:
        p = pa.PreviewAudio(threaded=False)
        assert p.backend_name == ""
        assert not p.available
        assert "not been started" in p.status
        assert asked == []
    finally:
        monkeypatch.undo()
        importlib.reload(pa)


# --------------------------------------------------------------------------
# reading a WAV
# --------------------------------------------------------------------------

def test_wav_header_reads_the_selectors_format(tmp_path):
    p = _tone(tmp_path / "music0.wav", frames=4410)
    head = pa.wav_header(p)
    assert head == {"rate": 44100, "channels": 2, "sampwidth": 2,
                    "frames": 4410, "seconds": pytest.approx(0.1)}
    assert pa.wav_refusal(head) is None


@pytest.mark.parametrize("kw,word", [
    ({"sampwidth": 1}, "8-bit"),
    ({"rate": 22050}, "22050 Hz"),
    ({"channels": 3}, "3 channels"),
])
def test_wav_refusal_names_what_is_wrong(tmp_path, kw, word):
    """The same three tests the card's loader applies, said as a sentence."""
    p = _tone(tmp_path / "bad.wav", frames=100, **kw)
    why = pa.wav_refusal(pa.wav_header(p))
    assert why and word in why, why


def test_read_clip_refuses_a_file_that_is_not_a_wav(tmp_path):
    p = tmp_path / "move.wav"
    p.write_bytes(b"this is not a RIFF file at all")
    with pytest.raises(pa.WavRefused) as exc:
        pa.read_clip(str(p))
    assert "move.wav" in str(exc.value)


def test_read_clip_refuses_a_missing_file(tmp_path):
    with pytest.raises(pa.WavRefused):
        pa.read_clip(str(tmp_path / "nope.wav"))


def test_read_clip_refuses_24_bit(tmp_path):
    """'Refuse anything that is not 16-bit PCM' - and say 24-bit, not 'error'."""
    p = _wav(tmp_path / "deep.wav", list(range(300)), sampwidth=3)
    with pytest.raises(pa.WavRefused) as exc:
        pa.read_clip(p)
    assert "24-bit" in str(exc.value)


def test_read_clip_duplicates_mono_to_stereo(tmp_path):
    p = _wav(tmp_path / "mono.wav", [10, -20, 30], channels=1)
    clip = pa.read_clip(p)
    assert clip.shape == (3, 2)
    assert clip.dtype == np.int16
    assert clip.tolist() == [[10, 10], [-20, -20], [30, 30]]


def test_read_clip_keeps_stereo_interleaving(tmp_path):
    p = _wav(tmp_path / "st.wav", [1, 2, 3, 4])
    assert pa.read_clip(p).tolist() == [[1, 2], [3, 4]]


def test_read_clip_cuts_a_long_bed(tmp_path):
    """audio.c's CLIP_CAP_S, with a cap small enough for a test to afford."""
    p = _tone(tmp_path / "long.wav", frames=1000)
    clip = pa.read_clip(p, cap_seconds=100.0 / pa.RATE)
    assert len(clip) == 100


def test_clip_cache_reads_once_then_again_after_a_change(tmp_path):
    p = tmp_path / "move.wav"
    _wav(p, [7, 7])
    cache = pa.ClipCache()
    first = cache.get(str(p))
    assert cache.get(str(p)) is first          # same bytes, same object
    time.sleep(0.01)
    _wav(p, [9, 9, 9, 9])
    os.utime(str(p), (time.time() + 5, time.time() + 5))
    again = cache.get(str(p))
    assert again is not first and len(again) == 2


def test_clip_cache_forgets_the_oldest(tmp_path):
    cache = pa.ClipCache(limit=2)
    paths = [_wav(tmp_path / ("c%d.wav" % i), [i, i]) for i in range(3)]
    for p in paths:
        cache.get(p)
    assert len(cache._items) == 2


def test_clip_cache_refusal_names_the_file(tmp_path):
    with pytest.raises(pa.WavRefused) as exc:
        pa.ClipCache().get(str(tmp_path / "gone.wav"))
    assert "gone.wav" in str(exc.value)


# --------------------------------------------------------------------------
# the gain: the menu's number must mean the menu's loudness
# --------------------------------------------------------------------------

@pytest.mark.parametrize("volume,q8", [(0, 0), (50, 128), (100, 256)])
def test_gain_q8_is_the_cards_own_arithmetic(volume, q8):
    """audio.c: ``a->gain_q8 = volume * 256 / 100``.  Linear, so a 50 in
    media.json's ``volume`` is a 50 here."""
    assert pa.gain_q8(volume) == q8


def test_gain_q8_clamps_like_audio_open():
    assert pa.gain_q8(-5) == 0
    assert pa.gain_q8(400) == 256
    assert pa.gain_q8("loud") == pa.gain_q8(pa.DEFAULT_VOLUME)


def test_clamp_volume_keeps_a_fallback_for_nonsense():
    assert pa.clamp_volume(None, 42) == 42
    assert pa.clamp_volume(77) == 77


# --------------------------------------------------------------------------
# the mixer
# --------------------------------------------------------------------------

def test_a_one_shot_plays_over_the_loop():
    """The behaviour the whole sounddevice backend exists for: the move click
    sounds WHILE the music keeps going, so the block holds their sum."""
    m = pa.Mixer(volume=100)
    m.start(_clip([100] * 8), loop=True)
    m.start(_clip([5, 5]), loop=False)
    out = m.render(4)
    assert [v[0] for v in out] == [105, 105, 100, 100]


def test_a_loop_wraps_and_a_one_shot_does_not():
    m = pa.Mixer(volume=100)
    m.start(_clip([1, 2]), loop=True)
    assert [v[0] for v in m.render(5)] == [1, 2, 1, 2, 1]

    m2 = pa.Mixer(volume=100)
    m2.start(_clip([3, 4]), loop=False)
    assert [v[0] for v in m2.render(5)] == [3, 4, 0, 0, 0]
    assert not m2.playing(0)


def test_the_gain_is_applied_once_to_the_sum():
    """Half volume is q8 128, and 128/256 of the SUM - not of each voice, which
    would round (and clip) differently."""
    m = pa.Mixer(volume=50)
    m.start(_clip([1000] * 4), loop=True)
    m.start(_clip([1000] * 4), loop=True)
    assert m.render(1)[0][0] == (2000 * 128) >> 8


def test_the_mix_saturates_instead_of_wrapping():
    m = pa.Mixer(volume=100)
    for _ in range(4):
        m.start(_clip([30000] * 4), loop=True)
    out = m.render(2)
    assert out.dtype == np.int16
    assert [int(v[0]) for v in out] == [32767, 32767]

    m2 = pa.Mixer(volume=100)
    for _ in range(4):
        m2.start(_clip([-30000] * 4), loop=True)
    assert int(m2.render(1)[0][0]) == -32768


def test_a_stopped_voice_ramps_out_over_20ms():
    """FADE_FRAMES, so replacing the music does not click."""
    m = pa.Mixer(volume=100)
    v = m.start(_clip([1000] * (pa.FADE_FRAMES * 2)), loop=True)
    m.fade_out(v)
    out = m.render(pa.FADE_FRAMES + 10)
    assert int(out[0][0]) == 1000                       # full at the first frame
    assert 0 < int(out[pa.FADE_FRAMES // 2][0]) < 1000  # half way down
    assert int(out[pa.FADE_FRAMES - 1][0]) <= 1         # a whisker off zero,
    assert int(out[pa.FADE_FRAMES][0]) == 0             # and silent from there
    assert not m.playing(v)


def test_a_fade_that_spans_two_blocks_keeps_going_down():
    m = pa.Mixer(volume=100)
    v = m.start(_clip([1000] * (pa.FADE_FRAMES * 2)), loop=True)
    m.fade_out(v)
    first = m.render(100)
    second = m.render(100)
    assert int(first[-1][0]) > int(second[0][0]) > int(second[-1][0])
    assert m.playing(v)


def test_fading_twice_does_not_restart_the_ramp():
    m = pa.Mixer(volume=100)
    v = m.start(_clip([1000] * 4000), loop=True)
    m.fade_out(v)
    m.render(400)
    m.fade_out(v)
    assert m.voices[v].fade_left == pa.FADE_FRAMES - 400


def test_a_fifth_sound_steals_a_one_shot_and_never_the_music():
    """audio_play()'s allocation: the music has to survive a busy flipper."""
    m = pa.Mixer(volume=100)
    music = m.start(_clip([1] * 100), loop=True)
    for _ in range(pa.VOICES - 1):
        m.start(_clip([2] * 100), loop=False)
    m.start(_clip([3] * 100), loop=False)
    assert m.voices[music].loop and m.voices[music].clip[0][0] == 1


def test_an_empty_clip_is_not_given_a_voice():
    m = pa.Mixer(volume=100)
    assert m.start(np.zeros((0, 2), dtype=np.int16), loop=True) == -1
    assert m.start(None) == -1


def test_set_volume_is_heard_on_the_next_block():
    m = pa.Mixer(volume=100)
    m.start(_clip([1000] * 8), loop=True)
    assert int(m.render(1)[0][0]) == 1000
    m.set_volume(0)
    assert int(m.render(1)[0][0]) == 0


def test_stop_all_silences_every_voice():
    m = pa.Mixer(volume=100)
    m.start(_clip([1000] * 8), loop=True)
    m.stop_all()
    assert int(m.render(2)[0][0]) == 0


# --------------------------------------------------------------------------
# the sounddevice backend, with no sounddevice
# --------------------------------------------------------------------------

def test_sounddevice_backend_opens_the_selectors_format(tmp_path):
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=50)
    be.start()
    kw = sd.streams[0].kw
    assert kw["samplerate"] == pa.RATE and kw["channels"] == 2
    assert kw["dtype"] == "int16"
    assert sd.streams[0].started


def test_sounddevice_backend_mixes_the_click_over_the_music(tmp_path):
    """Driving the stream's own callback: the block PortAudio would have been
    handed holds both sounds."""
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    assert be.loop(_tone(tmp_path / "music0.wav", frames=200, value=100)) == ""
    assert be.play(_tone(tmp_path / "move.wav", frames=200, value=5)) == ""
    out = np.zeros((4, 2), dtype=np.int16)
    sd.streams[0].callback(out, 4, None, None)
    assert [int(v[0]) for v in out] == [105] * 4


def test_sounddevice_backend_replaces_the_loop_and_fades_the_old_one(tmp_path):
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    be.loop(_tone(tmp_path / "a.wav", frames=8000, value=100))
    first = be._loop_voice
    be.loop(_tone(tmp_path / "b.wav", frames=8000, value=200))
    assert be._loop_voice != first
    assert be.mixer.voices[first].fade_left == pa.FADE_FRAMES


def test_sounddevice_backend_loop_none_silences_the_music(tmp_path):
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    be.loop(_tone(tmp_path / "a.wav", frames=8000, value=100))
    be.loop(None)
    assert be._loop_voice == -1
    assert be.mixer.voices[0].fade_left == pa.FADE_FRAMES


def test_sounddevice_backend_returns_the_reason_a_wav_will_not_play(tmp_path):
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    bad = _tone(tmp_path / "bad.wav", frames=10, rate=22050)
    said = be.loop(bad)
    assert "22050 Hz" in said
    assert be.play(bad) == said


def test_the_callback_never_raises_into_portaudio(tmp_path):
    """A raise on PortAudio's thread kills the stream for the evening, so a
    bad block has to become silence instead."""
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    be.mixer.render = lambda frames: (_ for _ in ()).throw(RuntimeError("boom"))
    out = np.full((4, 2), 999, dtype=np.int16)
    sd.streams[0].callback(out, 4, None, None)
    assert not out.any()


def test_closing_stops_the_stream_and_the_voices(tmp_path):
    sd = FakeSD()
    be = pa.SoundDeviceBackend(sd, volume=100)
    be.start()
    be.loop(_tone(tmp_path / "a.wav", frames=800))
    assert be.close() == ""
    assert sd.streams[0].stopped and sd.streams[0].closed
    assert be._loop_voice == -1 and not be.mixer.playing(0)
    assert be.close() == ""                     # twice is fine


def test_pick_output_device_prefers_wasapi():
    """padplay's measured reason: MME's ~200 ms would put the click well
    behind the flipper."""
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS)
    assert pa.pick_output_device(sd, platform="win32") == 13
    assert pa.pick_output_device(sd, platform="darwin") is None


def test_pick_output_device_survives_a_sounddevice_that_throws():
    class Angry(object):
        def query_hostapis(self):
            raise OSError("PortAudio not initialized")

    assert pa.pick_output_device(Angry(), platform="win32") is None


def test_output_candidates_offers_the_resampler_first_on_windows():
    """David's speakers sit at 96 kHz, so the FIRST route has to be the one
    that lets Windows resample - a bare 44100 WASAPI open is refused."""
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True)
    routes = pa.output_candidates(sd, platform="win32")
    assert [r[0] for r in routes] == [13, 13, None]
    assert routes[0][1] == ("wasapi", True)
    assert routes[1][1] is None and routes[2][1] is None
    assert "resampler" in routes[0][2]


def test_output_candidates_without_wasapi_settings_drops_that_route():
    """An older sounddevice has no auto_convert; it must contribute one fewer
    route, not an exception."""
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=False)
    routes = pa.output_candidates(sd, platform="win32")
    assert [r[0] for r in routes] == [13, None]


def test_output_candidates_off_windows_is_just_the_default():
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True)
    assert pa.output_candidates(sd, platform="linux") == [
        (None, None, "the system's default output")]


def test_start_walks_past_a_route_the_device_will_not_take():
    """The measured failure on this machine, in a test: WASAPI answers
    'Invalid sample rate' to a bare 44100 and takes the resampled one."""
    def refuse(kw):
        if kw.get("device") == 13 and "extra_settings" not in kw:
            return OSError("Invalid sample rate [PaErrorCode -9997]")
        return None

    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True, refuse=refuse)
    be = pa.SoundDeviceBackend(sd, volume=50,
                               candidates=pa.output_candidates(sd, "win32"))
    assert be.start() == "WASAPI with Windows' own resampler"
    assert sd.streams[0].kw["extra_settings"] == ("wasapi", True)
    assert "resampler" in be.note


def test_start_falls_all_the_way_to_the_default_output():
    def refuse(kw):
        return OSError("nope") if kw.get("device") == 13 else None

    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True, refuse=refuse)
    be = pa.SoundDeviceBackend(sd, volume=50,
                               candidates=pa.output_candidates(sd, "win32"))
    assert be.start() == "the system's default output"
    assert sd.streams[0].kw["device"] is None


def test_start_raises_the_last_failure_when_no_route_works():
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True,
                refuse=lambda kw: OSError("Invalid device [PaErrorCode -9996]"))
    be = pa.SoundDeviceBackend(sd, volume=50,
                               candidates=pa.output_candidates(sd, "win32"))
    with pytest.raises(OSError) as exc:
        be.start()
    assert "-9996" in str(exc.value)
    assert be.stream is None


# --------------------------------------------------------------------------
# the winsound fallback, and the compromise it is
# --------------------------------------------------------------------------

def test_winsound_loops_asynchronously(tmp_path):
    ws = FakeWinsound()
    be = pa.WinsoundBackend(ws, volume=50)
    music = _tone(tmp_path / "music0.wav", frames=4410)
    assert be.loop(music) == ""
    sound, flags = ws.calls[-1]
    assert sound == music
    assert flags & ws.SND_LOOP and flags & ws.SND_ASYNC and flags & ws.SND_FILENAME


def test_winsound_click_interrupts_the_music_and_schedules_its_return(tmp_path):
    """The documented compromise, held to in a test so nobody 'fixes' it into
    a silent music bed: one sound at a time, and the bed comes back."""
    ws = FakeWinsound()
    timer = FakeTimer()
    be = pa.WinsoundBackend(ws, volume=50, schedule=timer.schedule)
    music = _tone(tmp_path / "music0.wav", frames=4410)
    move = _tone(tmp_path / "move.wav", frames=4410)     # 0.1 s
    be.loop(music)
    be.play(move)
    assert ws.calls[-1][0] == move
    assert not ws.calls[-1][1] & ws.SND_LOOP
    assert timer.pending and timer.pending[0][0] == pytest.approx(0.15)
    timer.fire_all()
    assert ws.calls[-1][0] == music and ws.calls[-1][1] & ws.SND_LOOP


def test_winsound_click_with_no_music_schedules_nothing(tmp_path):
    ws = FakeWinsound()
    timer = FakeTimer()
    be = pa.WinsoundBackend(ws, volume=50, schedule=timer.schedule)
    be.play(_tone(tmp_path / "move.wav", frames=100))
    assert timer.pending == []


def test_winsound_volume_zero_is_the_only_volume_it_can_honour(tmp_path):
    ws = FakeWinsound()
    be = pa.WinsoundBackend(ws, volume=0)
    be.loop(_tone(tmp_path / "music0.wav", frames=100))
    assert ws.calls == []                       # nothing played at all
    be.set_volume(80)
    assert ws.calls[-1][1] & ws.SND_LOOP        # and the bed starts on the way up
    be.set_volume(0)
    assert ws.calls[-1] == (None, ws.SND_PURGE)


def test_winsound_refuses_the_same_wavs_the_card_refuses(tmp_path):
    ws = FakeWinsound()
    be = pa.WinsoundBackend(ws, volume=50)
    bad = _tone(tmp_path / "bad.wav", frames=10, sampwidth=1)
    assert "8-bit" in be.loop(bad)
    assert "8-bit" in be.play(bad)
    assert ws.calls == []


def test_winsound_says_so_when_playsound_throws(tmp_path):
    class Angry(FakeWinsound):
        def PlaySound(self, sound, flags):                  # noqa: N802
            raise RuntimeError("device in use")

    be = pa.WinsoundBackend(Angry(), volume=50)
    said = be.loop(_tone(tmp_path / "music0.wav", frames=100))
    assert "music0.wav" in said and "device in use" in said


def test_winsound_close_purges_and_cancels(tmp_path):
    ws = FakeWinsound()
    timer = FakeTimer()
    be = pa.WinsoundBackend(ws, volume=50, schedule=timer.schedule)
    be.loop(_tone(tmp_path / "music0.wav", frames=4410))
    be.play(_tone(tmp_path / "move.wav", frames=4410))
    be.close()
    assert ws.calls[-1] == (None, ws.SND_PURGE)
    timer.fire_all()                            # a cancelled resume stays quiet
    assert ws.calls[-1] == (None, ws.SND_PURGE)


def test_winsound_note_explains_what_the_listener_hears():
    note = pa.WinsoundBackend(FakeWinsound()).note
    assert "one sound at a time" in note and "volume" in note


# --------------------------------------------------------------------------
# choosing a backend
# --------------------------------------------------------------------------

def _importer(**mods):
    def imp(name):
        if name not in mods:
            raise ImportError("No module named %r" % name)
        val = mods[name]
        if isinstance(val, Exception):
            raise val
        return val
    return imp


def test_sounddevice_is_preferred(monkeypatch):
    monkeypatch.setattr(pa.sys, "platform", "linux")
    sd = FakeSD()
    be, why = pa.open_backend(50, importer=_importer(sounddevice=sd, numpy=np))
    assert isinstance(be, pa.SoundDeviceBackend) and why == ""
    assert sd.streams[0].started


def test_no_sounddevice_on_windows_falls_back_to_winsound():
    ws = FakeWinsound()
    be, why = pa.open_backend(50, importer=_importer(winsound=ws),
                              platform="win32")
    assert isinstance(be, pa.WinsoundBackend) and why == ""


def test_a_device_that_will_not_open_falls_back_too():
    """Installed but useless is the case a bare import check would miss."""
    sd = FakeSD(fail=OSError("Error querying device -1"))
    be, why = pa.open_backend(50,
                              importer=_importer(sounddevice=sd, numpy=np,
                                                 winsound=FakeWinsound()),
                              platform="win32")
    assert isinstance(be, pa.WinsoundBackend) and why == ""


def test_no_sounddevice_off_windows_is_silence_with_a_reason():
    be, why = pa.open_backend(50, importer=_importer(), platform="darwin")
    assert isinstance(be, pa.NullBackend)
    assert why.startswith("No sound:")
    assert "sounddevice is not installed" in why
    assert "darwin" in why
    assert why.endswith(".")


def test_the_reason_names_the_device_failure_not_just_the_import():
    sd = FakeSD(fail=OSError("Error querying device -1"))
    _be, why = pa.open_backend(
        50, importer=_importer(sounddevice=sd, numpy=np), platform="linux")
    assert "no output device" in why and "device -1" in why


def test_a_null_backend_swallows_every_call():
    be = pa.NullBackend("No sound: nothing here.")
    assert be.loop("x") == "" and be.play("x") == ""
    assert be.set_volume(10) == "" and be.close() == ""


# --------------------------------------------------------------------------
# PreviewAudio, the thing the tab holds
# --------------------------------------------------------------------------

def test_loop_play_and_volume_reach_the_backend():
    rec = RecordingBackend()
    p = _player(rec)
    p.loop("/media/music0.wav")
    p.play("/media/move.wav")
    p.set_volume(30)
    assert rec.calls == [("loop", "/media/music0.wav"),
                         ("play", "/media/move.wav"),
                         ("volume", 30)]
    assert p.volume == 30


def test_the_same_music_is_not_restarted():
    """codeselect.c only switches the bed when the CLIP differs, so moving
    between two cards that share one must not make it start over."""
    rec = RecordingBackend()
    p = _player(rec)
    p.loop("/media/music0.wav")
    p.loop("/media/music0.wav")
    p.play("/media/move.wav")
    p.loop("/media/music1.wav")
    assert rec.calls == [("loop", "/media/music0.wav"),
                         ("play", "/media/move.wav"),
                         ("loop", "/media/music1.wav")]


def test_loop_none_stops_the_music_and_can_be_restarted():
    rec = RecordingBackend()
    p = _player(rec)
    p.loop("/media/music0.wav")
    p.loop(None)
    p.loop("/media/music0.wav")
    assert rec.calls == [("loop", "/media/music0.wav"), ("loop", None),
                         ("loop", "/media/music0.wav")]


def test_the_volume_reaches_the_backend_that_opens_later():
    """set_volume before anything played must still be the volume the backend
    is built with - the tab reads media.json's ``volume`` at load time."""
    seen = []

    def factory(vol):
        seen.append(vol)
        return RecordingBackend(), ""

    p = pa.PreviewAudio(volume=50, backend_factory=factory, threaded=False)
    p.set_volume(11)
    assert seen == [11]


def test_a_backend_that_raises_is_a_sentence_not_a_traceback():
    class Angry(RecordingBackend):
        def play(self, path):
            raise RuntimeError("the device went away")

    p = _player(Angry())
    p.play("/media/move.wav")                   # must not raise
    assert "the device went away" in p.status


def test_a_backend_that_reports_a_bad_wav_shows_it_then_clears_it():
    rec = RecordingBackend(errors={"loop": "music0.wav will not play: 8-bit"})
    p = _player(rec)
    p.loop("/media/music0.wav")
    assert "8-bit" in p.status
    rec.errors = {}
    p.play("/media/move.wav")
    assert "8-bit" not in p.status


def test_a_factory_that_raises_is_a_sentence_too():
    def boom(vol):
        raise OSError("PortAudio exploded")

    p = pa.PreviewAudio(backend_factory=boom, threaded=False)
    p.loop("/media/music0.wav")
    assert not p.available
    assert "PortAudio exploded" in p.status
    assert "PortAudio exploded" in p.why_silent


def test_status_before_anything_played():
    p = pa.PreviewAudio(threaded=False)
    assert not p.available
    assert p.backend_name == ""
    assert "not been started" in p.why_silent
    assert "not been started" in p.status


def test_status_reads_as_a_sentence_on_each_backend():
    rec = RecordingBackend()
    p = _player(rec)
    p.play("/media/move.wav")
    assert p.available and p.why_silent == ""
    assert p.status == "Sound plays through recorder."

    why = "No sound: nothing here."
    q = _player(pa.NullBackend(why), why=why)
    q.play("/media/move.wav")
    assert not q.available
    assert q.status == "No sound: nothing here."


def test_status_names_the_route_sound_found(tmp_path):
    """When someone asks why the preview is silent, the first useful fact is
    which way out it took."""
    sd = FakeSD(hostapis=WASAPI_HOSTAPIS, wasapi=True)
    be = pa.SoundDeviceBackend(sd, volume=50,
                               candidates=pa.output_candidates(sd, "win32"))
    be.start()
    p = _player(be)
    p.play(_tone(tmp_path / "move.wav", frames=100))
    assert p.status == ("Sound plays through sounddevice. It is playing "
                        "through WASAPI with Windows' own resampler.")


def test_status_repeats_the_winsound_compromise(tmp_path):
    ws = pa.WinsoundBackend(FakeWinsound(), volume=50)
    p = _player(ws)
    p.play(_tone(tmp_path / "move.wav", frames=100))
    assert p.status.startswith("Sound plays through winsound.")
    assert "one sound at a time" in p.status


def test_on_status_is_told_once_the_backend_is_known():
    told = []
    rec = RecordingBackend()
    p = pa.PreviewAudio(backend_factory=lambda vol: (rec, ""), threaded=False,
                        on_status=told.append)
    p.play("/media/move.wav")
    assert told and told[0] is p


def test_an_on_status_that_throws_does_not_break_the_sound():
    def angry(_p):
        raise ValueError("the label is gone")

    rec = RecordingBackend()
    p = pa.PreviewAudio(backend_factory=lambda vol: (rec, ""), threaded=False,
                        on_status=angry)
    p.loop("/media/music0.wav")
    assert rec.calls == [("loop", "/media/music0.wav")]


def test_stop_closes_the_backend_and_a_later_loop_reopens_it():
    made = []

    def factory(vol):
        made.append(RecordingBackend())
        return made[-1], ""

    p = pa.PreviewAudio(backend_factory=factory, threaded=False)
    p.loop("/media/music0.wav")
    p.stop()
    assert made[0].calls[-1] == ("close", None)
    assert p.backend_name == ""
    p.loop("/media/music0.wav")
    assert len(made) == 2 and made[1].calls == [("loop", "/media/music0.wav")]


def test_stop_before_anything_played_is_harmless():
    made = []
    p = pa.PreviewAudio(backend_factory=lambda vol: (made.append(1), ""),
                        threaded=False)
    p.stop()
    p.stop()
    assert made == []                           # nothing was ever opened


# --------------------------------------------------------------------------
# the worker thread
# --------------------------------------------------------------------------

def _threads():
    return {t for t in threading.enumerate() if t.name == "preview-audio"}


def test_the_tab_thread_is_not_the_one_that_waits():
    """Every call returns at once; the slow factory runs on the worker."""
    gate = threading.Event()
    rec = RecordingBackend()

    def slow(vol):
        gate.wait(5)
        return rec, ""

    before = _threads()
    p = pa.PreviewAudio(backend_factory=slow)
    try:
        t0 = time.time()
        p.loop("/media/music0.wav")
        p.play("/media/move.wav")
        assert time.time() - t0 < 1.0           # nothing blocked on the gate
        assert not p.available                  # and nothing is known yet
        gate.set()
        assert p.wait_ready(5)
        for _ in range(200):
            if len(rec.calls) == 2:
                break
            time.sleep(0.01)
        assert rec.calls == [("loop", "/media/music0.wav"),
                             ("play", "/media/move.wav")]
        assert p.available
    finally:
        gate.set()
        p.stop()
    assert _threads() <= before                 # no thread left behind


def test_stop_leaves_no_thread_behind():
    before = _threads()
    p = pa.PreviewAudio(backend_factory=lambda vol: (RecordingBackend(), ""))
    p.loop("/media/music0.wav")
    assert p.wait_ready(5)
    assert _threads() - before                  # it really did start one
    p.stop()
    assert _threads() <= before
    p.stop()                                    # twice, from anywhere
    assert _threads() <= before


def test_stop_from_the_status_callback_does_not_deadlock():
    """on_status fires on the worker; a caller who stops from there must not
    join the thread it is standing on."""
    done = threading.Event()

    def on_status(player):
        player.stop()
        done.set()

    p = pa.PreviewAudio(backend_factory=lambda vol: (RecordingBackend(), ""),
                        on_status=on_status)
    p.loop("/media/music0.wav")
    assert done.wait(5), "the worker never got past stop()"
    p.stop()


# --------------------------------------------------------------------------
# a stop during a slow first open
# --------------------------------------------------------------------------
#
# THE FIRST OPEN IS SLOW ENOUGH TO CHANGE YOUR MIND DURING, which is the whole
# subject here: sounddevice and numpy are imported, PortAudio's host APIs are
# asked for, and up to three output streams are tried, all on the worker.  A
# stop that lands in the middle of that is a stop whose join times out - and a
# join that times out is not a stop unless the worker itself, which is the only
# thing that can still reach that device, gives it back.  Both tests below hold
# the FIRST factory call open on a gate and shorten the join to a fraction of a
# second; the shape is the same one a real 96 kHz WASAPI probe makes at 2.0 s.

def _sounded(backend):
    """The loop/play calls a backend was given - what a listener would hear."""
    return [c for c in backend.calls if c[0] in ("loop", "play")]


def _was_closed(backend):
    return ("close", None) in backend.calls


def _until(predicate, timeout=5.0):
    """Wait for something an abandoned worker does on its own clock.

    Everything these tests ask about happens after a stop has stopped waiting,
    so there is no call to hang the answer off: they watch for it instead."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _settle(before, timeout=5.0):
    """Wait for every preview-audio thread this test started to end."""
    return _until(lambda: _threads() <= before, timeout)


def _gated_factory(made, gate, entered):
    """A backend factory whose FIRST call blocks until *gate* is set.

    *entered* says that call has begun, so a test can stop the player at the
    one moment it means to - inside the open - rather than at whatever moment
    a loaded machine happens to give it."""
    def factory(vol):
        rec = RecordingBackend()
        made.append(rec)
        if len(made) == 1:
            entered.set()
            gate.wait(5)
        return rec, ""
    return factory


def test_a_stop_during_the_first_open_still_gives_the_device_back(monkeypatch):
    """Untick Sound before the device has finished opening, and the device is
    still closed - and never plays a note on its way out.

    The worker cannot be interrupted inside PortAudio, so it WILL finish that
    open; what it must not do is then act on the commands the stop overtook,
    and what it must always do is close what it opened."""
    monkeypatch.setattr(pa, "STOP_JOIN_SECONDS", 0.05)
    gate, entered = threading.Event(), threading.Event()
    made = []
    before = _threads()
    p = pa.PreviewAudio(backend_factory=_gated_factory(made, gate, entered))
    try:
        p.loop("/media/music0.wav")
        p.play("/media/move.wav")
        assert entered.wait(5), "the worker never reached the open"
        p.stop()                                # the join must time out here
        assert not _was_closed(made[0])         # it cannot have closed yet
    finally:
        gate.set()
    assert _settle(before), "the abandoned worker never finished"
    assert len(made) == 1
    assert _sounded(made[0]) == [], "it played after the sound was stopped"
    assert _was_closed(made[0]), "the device it opened was never given back"
    assert p.backend_name == "" and not p.available


def test_sound_off_then_on_during_the_first_open_leaves_no_second_device(
        monkeypatch):
    """The reported mis-click: tick Sound, untick it before the device is
    open, tick it again.

    The second tick gets a session of its own, and the first one is still in
    PortAudio - so for a moment two backends exist.  Only one of them may ever
    make a sound, and BOTH have to be closed by the end, because a started
    output stream that nothing holds a reference to is a bed that plays until
    the process dies."""
    monkeypatch.setattr(pa, "STOP_JOIN_SECONDS", 0.05)
    gate, entered = threading.Event(), threading.Event()
    made = []
    before = _threads()
    p = pa.PreviewAudio(backend_factory=_gated_factory(made, gate, entered))
    try:
        p.loop("/media/music1.wav")             # Sound on
        assert entered.wait(5), "the worker never reached the open"
        p.stop()                                # Sound off, mid-open
        p.loop("/media/music2.wav")             # Sound on again
        assert p.wait_ready(5), "the second tick never chose a backend"
        p.play("/media/move.wav")               # ...and the highlight moves
    finally:
        gate.set()
    # Let the abandoned worker finish before the last stop, so that what is
    # measured below is a settled machine rather than a race: by here the
    # first session is completely done with, and the only device left is the
    # one the second tick opened.
    assert _until(lambda: _was_closed(made[0])), \
        "the abandoned worker never gave its device back"
    p.stop()
    assert _settle(before), "a worker was left running"
    assert len(made) == 2, "each tick opens its own"
    abandoned, live = made
    assert _was_closed(abandoned) and _was_closed(live), \
        "a device was left open with nothing left holding it"
    assert _sounded(abandoned) == [], "two beds played at once"
    assert _sounded(live) == [("loop", "/media/music2.wav"),
                              ("play", "/media/move.wav")]
