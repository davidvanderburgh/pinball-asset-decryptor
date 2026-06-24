"""Tests for the Replace-Audio slot scanning + staging (core/audio_slots).

These don't need ffmpeg: same-extension WAV staging is pure-Python (channel
/ bit-depth conversion + the WAV path through process_modified_audio), so the
round-trip runs anywhere.
"""

import math
import os
import struct
import wave

import pytest

from pinball_decryptor.core.audio_slots import (AudioSlot, scan_audio_slots,
                                                stage_replacements)


def _make_wav(path, seconds=1.0, rate=22050, channels=1, freq=440):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = int(seconds * rate)
        for i in range(frames):
            v = int(3000 * math.sin(2 * math.pi * freq * i / rate))
            w.writeframes(struct.pack("<h", v) * channels)


def test_scan_finds_loose_audio_and_skips_dotdirs(tmp_path):
    _make_wav(str(tmp_path / "sounds" / "a.wav"))
    _make_wav(str(tmp_path / "music.wav"))
    # hidden dir + staging temp must be skipped
    _make_wav(str(tmp_path / ".cache" / "ignore.wav"))
    _make_wav(str(tmp_path / "b.wav.stage.wav"))

    slots = scan_audio_slots(str(tmp_path))
    rels = sorted(s.rel_path for s in slots)
    assert rels == ["music.wav", "sounds/a.wav"]


def test_duration_property_and_longest_first_sort():
    # Guards the regression where AudioSlot lacked a `duration` property
    # and the "Longest first" sort blanked the list.
    from pinball_decryptor.core.audio import AudioInfo

    def mk(rel, dur):
        return AudioSlot(rel_path=rel, abs_path=rel, ext=".wav",
                         info=AudioInfo(rel, channels=2, sample_rate=44100,
                                        bit_depth=16, duration=dur), size=0)

    slots = [mk("a.wav", 5.0), mk("b.wav", 120.0), mk("c.wav", 0.5)]
    slots.sort(key=lambda s: s.duration, reverse=True)
    assert [s.rel_path for s in slots] == ["b.wav", "a.wav", "c.wav"]


def test_duration_property_handles_missing_info():
    slot = AudioSlot(rel_path="x.wav", abs_path="x.wav", ext=".wav",
                     info=None, size=0)
    assert slot.duration == 0.0
    assert slot.duration_str() == "—"


def test_duration_str_shows_milliseconds():
    from pinball_decryptor.core.audio import AudioInfo

    def mk(dur):
        return AudioSlot(rel_path="a.wav", abs_path="a.wav", ext=".wav",
                         info=AudioInfo("a.wav", channels=2, sample_rate=44100,
                                        bit_depth=16, duration=dur), size=0)

    assert mk(45.379).duration_str() == "0:45.379"
    assert mk(147.0).duration_str() == "2:27.000"
    assert mk(0.5).duration_str() == "0:00.500"
    # Rounds to the nearest millisecond rather than truncating.
    assert mk(1.2341).duration_str() == "0:01.234"
    assert mk(1.2349).duration_str() == "0:01.235"


def test_scan_roots_restricts_walk(tmp_path):
    _make_wav(str(tmp_path / "editable" / "keep.wav"))
    _make_wav(str(tmp_path / "elsewhere" / "drop.wav"))

    roots = [str(tmp_path / "editable")]
    slots = scan_audio_slots(str(tmp_path), roots=roots)
    # paths are still relative to assets_dir, but only the root is walked
    assert [s.rel_path for s in slots] == ["editable/keep.wav"]


def test_stage_matches_format_keeps_length_by_default(tmp_path):
    orig = str(tmp_path / "sounds" / "track.wav")
    _make_wav(orig, seconds=1.0, rate=22050, channels=1)
    rep = str(tmp_path / "replacement.wav")
    _make_wav(rep, seconds=2.0, rate=22050, channels=2)  # stereo -> must match

    slots = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}
    rel = "sounds/track.wav"
    staged, failures = stage_replacements(
        {rel: slots[rel]}, {rel: rep}, trim_to_length=False)
    assert staged == 1 and failures == []

    after = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}[rel]
    assert after.info.channels == 1            # matched to original mono
    assert after.info.duration > 1.5           # full replacement length kept


def test_scan_exts_restricts_to_wav(tmp_path):
    _make_wav(str(tmp_path / "keep.wav"))
    # an .ogg present but excluded when exts is restricted
    (tmp_path / "drop.ogg").write_bytes(b"OggS" + b"\x00" * 60)
    all_slots = scan_audio_slots(str(tmp_path))
    assert sorted(s.rel_path for s in all_slots) == ["drop.ogg", "keep.wav"]
    wav_only = scan_audio_slots(str(tmp_path), exts=(".wav",))
    assert [s.rel_path for s in wav_only] == ["keep.wav"]


def test_bof_surfaces_wav_only_others_default(manufacturers_by_key):
    # BoF restricts Replace-Audio to .wav (no .ogg re-import from the
    # editable folder); the loose-file plugins keep both.
    bof = manufacturers_by_key["bof"]
    assert bof.audio_slot_exts("anything") == (".wav",)
    for key in ("jjp", "spooky", "ap", "pb", "dp", "cgc"):
        assert manufacturers_by_key[key].audio_slot_exts("anything") is None


def test_audio_length_notes(manufacturers_by_key):
    # JJP forces a length match on Write; DP is explicitly length-flexible;
    # everyone else gets the neutral default.
    assert "automatically matches" in manufacturers_by_key["jjp"].audio_length_note()
    assert "own length" in manufacturers_by_key["dp"].audio_length_note()
    for key in ("spooky", "pb", "ap", "cgc", "bof"):
        note = manufacturers_by_key[key].audio_length_note()
        assert "trimming usually" in note  # the base default


def test_stage_transcodes_cross_format_source(tmp_path):
    """A source in a different format/extension than the slot is
    auto-encoded into the slot's native format (needs ffmpeg)."""
    from pinball_decryptor.core.audio import find_ffmpeg
    import subprocess
    if not find_ffmpeg():
        pytest.skip("ffmpeg not available")

    slot = str(tmp_path / "sounds" / "track.wav")          # mono 22050 wav
    _make_wav(slot, seconds=1.0, rate=22050, channels=1)
    src_wav = str(tmp_path / "src.wav")
    _make_wav(src_wav, seconds=2.0, rate=44100, channels=2)  # stereo 44100
    src_mp3 = str(tmp_path / "song.mp3")
    subprocess.run([find_ffmpeg(), "-y", "-i", src_wav, src_mp3],
                   capture_output=True)

    slots = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}
    rel = "sounds/track.wav"
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: src_mp3})
    assert staged == 1 and failures == []

    after = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}[rel]
    assert after.ext == ".wav"               # original container kept
    assert after.info.channels == 1          # stereo source matched to mono
    assert after.info.sample_rate == 22050   # resampled to the slot's rate


def test_preview_helpers_spectrogram_and_duration(tmp_path):
    """The Replace-Audio seekable preview renders a spectrogram PNG and
    probes duration via ffmpeg/ffprobe (no new dependency)."""
    from pinball_decryptor.core import audio as a
    if not a.find_ffmpeg():
        pytest.skip("ffmpeg not available")
    wav = str(tmp_path / "t.wav")
    _make_wav(wav, seconds=1.0)
    png = a.render_spectrogram_png(wav, 300, 60)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
    if a.find_ffprobe():
        assert abs(a.probe_duration(wav) - 1.0) < 0.3


def test_stage_reports_failures_for_missing_replacement(tmp_path):
    orig = str(tmp_path / "track.wav")
    _make_wav(orig)
    slots = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}
    staged, failures = stage_replacements(
        slots, {"track.wav": str(tmp_path / "nope.wav")})
    assert staged == 0
    assert failures and failures[0][0] == "track.wav"
