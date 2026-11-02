"""Auto-name on audio named nothing: call-outs and music both failed (PAD-936).

Call-outs: PyAV 19 dropped ``av.open(metadata_errors=)``; faster-whisper still
passes it.  A fresh install pulls the newest av, so every clip of a Batman card failed
with "open() got an unexpected keyword argument 'metadata_errors'" and Auto-name
renamed nothing.  faster-whisper's audio decoder now gets an ``av`` whose open
drops that one argument when the installed PyAV refuses it.
"""
import sys
import types

import pytest

import pinball_decryptor.core.transcribe as T


class _Av19:
    """The parts of PyAV 19 faster_whisper.audio touches."""

    AudioResampler = object()

    def __init__(self):
        self.calls = []

    def open(self, file, mode="r", **kwargs):
        self.calls.append(kwargs)
        for k in kwargs:
            if k not in ("format", "options", "metadata_encoding"):
                raise TypeError(f"open() got an unexpected keyword argument '{k}'")
        return "container:" + file


@pytest.fixture
def fw_audio(monkeypatch):
    av = _Av19()
    audio = types.ModuleType("faster_whisper.audio")
    audio.av = av
    pkg = types.ModuleType("faster_whisper")
    pkg.audio = audio
    monkeypatch.setitem(sys.modules, "faster_whisper", pkg)
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", audio)
    return audio, av


def test_metadata_errors_is_dropped_when_av_refuses_it(fw_audio):
    audio, av = fw_audio
    T._patch_faster_whisper_av()
    got = audio.av.open("idx5283.wav", mode="r", metadata_errors="ignore")
    assert got == "container:idx5283.wav"
    assert av.calls == [{"metadata_errors": "ignore"}, {}]


def test_the_rest_of_av_is_the_real_module(fw_audio):
    audio, av = fw_audio
    T._patch_faster_whisper_av()
    assert audio.av.AudioResampler is av.AudioResampler


def test_patching_twice_wraps_once(fw_audio):
    audio, av = fw_audio
    T._patch_faster_whisper_av()
    first = audio.av
    T._patch_faster_whisper_av()
    assert audio.av is first and first._av is av


def test_any_other_bad_argument_still_raises(fw_audio):
    audio, _av = fw_audio
    T._patch_faster_whisper_av()
    with pytest.raises(TypeError, match="bogus"):
        audio.av.open("x.wav", bogus=1)


def test_transcribe_one_patches_before_decoding(fw_audio):
    audio, _av = fw_audio

    class _Model:
        def transcribe(self, path, **kw):
            audio.av.open(path, mode="r", metadata_errors="ignore")
            seg = type("S", (), {"text": " Joker's wild "})()
            return iter([seg]), type("I", (), {"duration": 1.0})()

    rel, kind, text, err = T._transcribe_one(
        _Model(), "audio/idx5283.wav", "idx5283.wav", 25.0)
    assert (kind, text, err) == ("speech", "Joker's wild", None)


# --- music: chromaprint's URL-safe fingerprints -----------------------------
# The same report's music pass identified 0 of 58 clips: every fingerprint
# was refused as "no valid fingerprint emitted" because chromaprint writes
# '-' and '_' and the check only took '+' and '/'.

def test_url_safe_fingerprint_is_accepted(monkeypatch, tmp_path):
    import pinball_decryptor.core.musicid as M
    fp = "AQAAz0mUaEkSRZEGAAAA-_8vKSh0SNmh_IJ-Z4"
    monkeypatch.setattr(M, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(M, "probe_duration", lambda p: 40.2)
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout=(fp + "\n").encode(), stderr=b""))
    assert M.fingerprint_file(str(tmp_path / "idx0123.wav")) == (fp, 40)


def test_console_garbage_is_still_refused():
    import pinball_decryptor.core.musicid as M
    assert not M._B64_RE.fullmatch("[chromaprint @ 0x1] AQAA")
    assert not M._B64_RE.fullmatch("123,456,789")


def test_real_ffmpeg_fingerprint_of_a_music_length_clip(tmp_path):
    import subprocess
    import pinball_decryptor.core.musicid as M
    ffmpeg = M.find_ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    muxers = subprocess.run([ffmpeg, "-hide_banner", "-muxers"],
                            capture_output=True, text=True).stdout
    if "chromaprint" not in muxers:
        pytest.skip("this ffmpeg has no chromaprint muxer")
    wav = tmp_path / "idx0123.wav"
    subprocess.run([ffmpeg, "-hide_banner", "-v", "error",
                    "-f", "lavfi", "-i", "sine=f=440:d=40,aeval=val(0)*sin(t*3)",
                    "-f", "lavfi", "-i", "anoisesrc=d=40:a=0.2",
                    "-filter_complex", "amix=inputs=2", str(wav)], check=True)
    fp, dur = M.fingerprint_file(str(wav))
    assert dur == 40 and len(fp) > 200
