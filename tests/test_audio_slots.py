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

from pinball_decryptor.core.audio_slots import (AudioSlot, replace_with_retry,
                                                scan_audio_slots,
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


def test_scan_probe_false_lists_without_reading(tmp_path):
    # probe=False is the GUI's instant-list mode: same slots, no per-file
    # header reads (info stays None until the background pass fills it).
    _make_wav(str(tmp_path / "sounds" / "a.wav"))
    _make_wav(str(tmp_path / "b.wav"))

    fast = scan_audio_slots(str(tmp_path), probe=False)
    assert sorted(s.rel_path for s in fast) == ["b.wav", "sounds/a.wav"]
    assert all(s.info is None for s in fast)
    assert all(s.size > 0 for s in fast)


def test_stage_from_unprobed_slot_detects_info_on_demand(tmp_path):
    # A slot staged before the background metadata pass reaches it must not
    # skip format matching: stage_replacement detects the slot's info itself.
    orig = str(tmp_path / "sounds" / "track.wav")
    _make_wav(orig, seconds=1.0, rate=22050, channels=1)
    rep = str(tmp_path / "replacement.wav")
    _make_wav(rep, seconds=2.0, rate=22050, channels=2)

    slots = {s.rel_path: s for s in
             scan_audio_slots(str(tmp_path), probe=False)}
    rel = "sounds/track.wav"
    assert slots[rel].info is None
    staged, failures = stage_replacements(
        {rel: slots[rel]}, {rel: rep}, trim_to_length=False)
    assert staged == 1 and failures == []

    after = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}[rel]
    assert after.info.channels == 1            # matched to original mono
    assert after.info.duration > 1.5           # full replacement length kept


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


def test_staging_snapshots_original_and_revert_restores(tmp_path):
    # Staging with assets_dir set must back the pristine original up under
    # .orig/ before overwriting, so the edit can be reverted instantly.
    from pinball_decryptor.core import staged_originals
    from pinball_decryptor.core.checksums import generate_checksums, md5_file

    assets = str(tmp_path)
    orig = str(tmp_path / "audio" / "idx0001.wav")
    _make_wav(orig, seconds=1.0, rate=22050, channels=1)
    generate_checksums(assets)                 # baseline (needed for snapshot)
    pristine_md5 = md5_file(orig)

    rep = str(tmp_path / "replacement.wav")
    _make_wav(rep, seconds=2.0, rate=22050, channels=2)

    slots = {s.rel_path: s for s in scan_audio_slots(assets)}
    rel = "audio/idx0001.wav"
    staged, failures = stage_replacements(
        {rel: slots[rel]}, {rel: rep}, trim_to_length=False, assets_dir=assets)
    assert staged == 1 and failures == []

    # Snapshot captured + the on-disk file actually changed.
    assert staged_originals.has_snapshot(assets, rel)
    assert md5_file(orig) != pristine_md5

    # Reverting restores the exact original bytes and drops the snapshot.
    assert staged_originals.revert(assets, rel) is True
    assert md5_file(orig) == pristine_md5
    assert not staged_originals.has_snapshot(assets, rel)


def test_staging_without_assets_dir_takes_no_snapshot(tmp_path):
    # Back-compat: callers that don't pass assets_dir behave exactly as before
    # (no .orig dir created).
    from pinball_decryptor.core.staged_originals import ORIG_DIR

    orig = str(tmp_path / "audio" / "idx0001.wav")
    _make_wav(orig, seconds=1.0, rate=22050, channels=1)
    rep = str(tmp_path / "replacement.wav")
    _make_wav(rep, seconds=1.0, rate=22050, channels=1)
    slots = {s.rel_path: s for s in scan_audio_slots(str(tmp_path))}
    rel = "audio/idx0001.wav"
    stage_replacements({rel: slots[rel]}, {rel: rep})
    assert not os.path.isdir(os.path.join(str(tmp_path), ORIG_DIR))


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
    # CGC's note explains Pulp Fiction's fixed-length bank slots; the rest
    # get the neutral default.
    assert "automatically matches" in manufacturers_by_key["jjp"].audio_length_note()
    assert "own length" in manufacturers_by_key["dp"].audio_length_note()
    assert "fixed-length" in manufacturers_by_key["cgc"].audio_length_note()
    for key in ("spooky", "pb", "ap", "bof"):
        note = manufacturers_by_key[key].audio_length_note()
        assert "trimming usually" in note  # the base default


def test_cgc_forces_length_match_only_for_bnk_extracts(manufacturers_by_key,
                                                       tmp_path):
    """CGC's Pulp Fiction stores audio in fixed-length JPS ``.bnk`` banks, so
    the Trim/pad lock must engage for a PF extract but stay a free choice for
    the WPC remakes' loose ``.wav`` files (and before any extract is scanned).
    """
    cgc = manufacturers_by_key["cgc"]
    # No extract loaded yet -> can't tell the game apart -> not forced.
    assert cgc.audio_forces_length_match() is False
    assert cgc.audio_forces_length_match(None) is False

    # Pulp Fiction extract: data/<name>.bnk present -> forced.
    pf = tmp_path / "pf"
    (pf / "data").mkdir(parents=True)
    (pf / "data" / "pfmusic.bnk").write_bytes(b"")
    assert cgc.audio_forces_length_match(str(pf)) is True

    # WPC remake extract: loose .wav, no bank -> not forced.
    afm = tmp_path / "afm"
    (afm / "afmdata" / "samples").mkdir(parents=True)
    (afm / "afmdata" / "samples" / "s1.wav").write_bytes(b"")
    assert cgc.audio_forces_length_match(str(afm)) is False


def test_forces_length_match_accepts_assets_arg(manufacturers_by_key):
    """Every plugin's audio_forces_length_match must accept the optional
    assets_dir arg (the GUI always calls it with the scanned folder)."""
    for mfr in manufacturers_by_key.values():
        # Must not raise regardless of arg.
        mfr.audio_forces_length_match()
        mfr.audio_forces_length_match("/some/extract")
    # JJP and Spike 2 force unconditionally.
    assert manufacturers_by_key["jjp"].audio_forces_length_match("/x") is True
    assert manufacturers_by_key["stern"].audio_forces_length_match("/x") is True


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


# --- replace_with_retry: hardens staging against transient SMB/AV locks -----

def test_replace_with_retry_plain_success(tmp_path):
    src = tmp_path / "a.stage.wav"
    dst = tmp_path / "a.wav"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    replace_with_retry(str(src), str(dst))
    assert dst.read_bytes() == b"new"
    assert not src.exists()             # temp consumed by the rename


def test_replace_with_retry_recovers_after_transient_lock(tmp_path, monkeypatch):
    src = tmp_path / "a.stage.wav"
    dst = tmp_path / "a.wav"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] < 3:              # first two attempts "Access is denied"
            raise PermissionError(5, "Access is denied")
        return real_replace(s, d)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr("pinball_decryptor.core.audio_slots.time.sleep",
                        lambda *_a: None)
    replace_with_retry(str(src), str(dst))
    assert calls["n"] == 3
    assert dst.read_bytes() == b"new"


def test_replace_with_retry_falls_back_to_content_overwrite(tmp_path, monkeypatch):
    src = tmp_path / "a.stage.wav"
    dst = tmp_path / "a.wav"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")

    def always_denied(_s, _d):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr("pinball_decryptor.core.audio_slots.time.sleep",
                        lambda *_a: None)
    # os.replace never succeeds, but copyfile-over-write does — no exception.
    replace_with_retry(str(src), str(dst), attempts=3)
    assert dst.read_bytes() == b"new"


def test_replace_with_retry_reraises_when_everything_fails(tmp_path, monkeypatch):
    src = tmp_path / "a.stage.wav"
    dst = tmp_path / "a.wav"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")

    def always_denied(*_a):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr("pinball_decryptor.core.audio_slots.shutil.copyfile",
                        always_denied)
    monkeypatch.setattr("pinball_decryptor.core.audio_slots.time.sleep",
                        lambda *_a: None)
    with pytest.raises(PermissionError):
        replace_with_retry(str(src), str(dst), attempts=2)
