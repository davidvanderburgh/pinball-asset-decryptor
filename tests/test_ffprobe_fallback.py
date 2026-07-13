"""Tests for the ffmpeg-banner fallback prober (ffmpeg-only installs).

The frozen macOS/Linux apps bundle ffmpeg via imageio-ffmpeg, whose wheel
ships ONLY the ffmpeg binary — no ffprobe.  Every ffprobe-based readout was
silently empty there: the Replace-Audio/Video preview timers stuck at
"0:00 / 0:00", the video slot list showed no Length/Resolution, and video
replacement bailed with "could not determine clip duration".  When ffprobe
is missing, the probers now parse the metadata banner ``ffmpeg -i`` prints
to stderr instead.  These tests feed canned banners to the pure parsers and
monkeypatch the finder to prove the fallback is actually wired in.
"""

import os

import pinball_decryptor.core.audio as audio
import pinball_decryptor.core.video as video

_MP4_BANNER = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:01:23.45, start: 0.000000, bitrate: 4382 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1920x1080 [SAR 1:1 DAR 16:9], 4276 kb/s, 29.97 fps, 29.97 tbr, 30k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 96 kb/s (default)
At least one output file must be specified
"""

_WEBM_ALPHA_BANNER = """\
Input #0, matroska,webm, from 'topper.webm':
  Duration: 00:00:07.60, start: 0.000000, bitrate: 1024 kb/s
  Stream #0:0: Video: vp9 (Profile 0), yuva420p(tv), 400x128, SAR 1:1 DAR 25:8, 30 fps, 30 tbr, 1k tbn (default)
At least one output file must be specified
"""

_OGG_AUDIO_BANNER = """\
Input #0, ogg, from 'jackpot.ogg':
  Duration: 00:00:02.34, start: 0.000000, bitrate: 112 kb/s
  Stream #0:0: Audio: vorbis, 44100 Hz, stereo, fltp, 112 kb/s
At least one output file must be specified
"""

_NA_DURATION_BANNER = """\
Input #0, mpegts, from 'stream.ts':
  Duration: N/A, start: 1.400000, bitrate: N/A
  Stream #0:0[0x100]: Video: h264, none, 90k tbr, 90k tbn
At least one output file must be specified
"""


def test_banner_duration_parses_hms():
    assert audio.parse_banner_duration(_MP4_BANNER) == 60 + 23.45


def test_banner_duration_handles_na_and_garbage():
    assert audio.parse_banner_duration(_NA_DURATION_BANNER) == 0.0
    assert audio.parse_banner_duration("") == 0.0
    assert audio.parse_banner_duration(None) == 0.0


def test_video_banner_full_metadata():
    info = video.parse_video_banner(_MP4_BANNER, "clip.mp4")
    assert info.vcodec == "h264"
    assert (info.width, info.height) == (1920, 1080)
    assert abs(info.fps - 29.97) < 1e-6
    assert abs(info.duration - 83.45) < 1e-6
    assert info.has_audio
    assert not info.has_alpha
    assert info.pix_fmt == "yuv420p"
    assert info.container == "mp4"


def test_video_banner_alpha_no_audio():
    info = video.parse_video_banner(_WEBM_ALPHA_BANNER, "topper.webm")
    assert info.vcodec == "vp9"
    assert (info.width, info.height) == (400, 128)
    assert info.has_alpha and info.pix_fmt == "yuva420p"
    assert not info.has_audio


def test_video_banner_audio_only_returns_none():
    assert video.parse_video_banner(_OGG_AUDIO_BANNER, "jackpot.ogg") is None
    assert video.parse_video_banner("", "x.mp4") is None


def test_video_banner_no_size_no_fps_survives():
    info = video.parse_video_banner(_NA_DURATION_BANNER, "stream.ts")
    assert (info.width, info.height) == (0, 0)
    # "90k tbr" must not parse as 90 fps (the k suffix means it's a tbn-style
    # clock, not a frame rate).
    assert info.fps == 0.0
    assert info.duration == 0.0


def test_duration_probe_falls_back_without_ffprobe(monkeypatch, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(audio, "find_ffprobe", lambda: None)
    monkeypatch.setattr(audio, "_ffmpeg_banner", lambda _p: _MP4_BANNER)
    assert audio._ffmpeg_get_duration(str(f)) == 83.45


def test_detect_video_info_falls_back_without_ffprobe(monkeypatch, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(video, "find_ffprobe", lambda: None)
    monkeypatch.setattr(video, "_ffmpeg_banner", lambda _p: _MP4_BANNER)
    info = video.detect_video_info(str(f))
    assert info is not None and info.vcodec == "h264"
    assert info.path == str(f)
    assert info.container == "mp4"
