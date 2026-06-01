"""Tests for The Big Lebowski .cdmd Replace-Video support: the cdmd encoder
round-trip, the metadata/preview helpers, the core.video backend wiring, and
slot scanning + staging through that backend.

The pure-Python codec tests run anywhere; the ffmpeg-encode test (replacement
clip -> .cdmd) skips when ffmpeg is unavailable.
"""

import os
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.dp import cdmd
from pinball_decryptor.core import video, video_slots


def _make_cdmd(path, nframes=4, w=8, h=4, with_wav=False):
    """Write a synthetic multi-frame .cdmd (full-canvas frames)."""
    buf = bytearray(cdmd.CDMD_MAGIC + struct.pack("<3I", nframes, w, h))
    for f in range(nframes):
        buf += struct.pack("<4I", 0, 0, w, h)
        buf += bytes([255, (f * 30) % 256, 64, 128]) * (w * h)  # ARGB
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(buf)
    if with_wav:
        import wave
        wav = os.path.splitext(path)[0] + ".wav"
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00\x00" * 8000)  # 1.0s of silence
    return path


# ---- codec round-trip -----------------------------------------------------

def test_cdmd_encode_decode_roundtrip(tmp_path):
    p = str(tmp_path / "out.cdmd")
    frames = [bytes([r, 20, 30]) * (8 * 4) for r in (0, 100, 200)]
    cdmd.write_cdmd(p, frames, nframes=3, canvas_w=8, canvas_h=4)

    decoded = list(cdmd.iter_frames(open(p, "rb").read()))
    assert len(decoded) == 3
    assert decoded[0].size == (8, 4)
    # opaque, R taken from the source rgb24 (ARGB order preserved)
    assert decoded[2].getpixel((0, 0)) == (200, 20, 30, 255)


def test_write_cdmd_pads_short_iterables(tmp_path):
    p = str(tmp_path / "pad.cdmd")
    cdmd.write_cdmd(p, [bytes([9, 9, 9]) * (4 * 2)], nframes=5,
                    canvas_w=4, canvas_h=2)
    assert cdmd.frame_count(open(p, "rb").read()) == 5  # header honest


# ---- metadata / preview ---------------------------------------------------

def test_cdmd_video_info_and_still_filtering(tmp_path):
    clip = _make_cdmd(str(tmp_path / "clip.cdmd"), nframes=6, w=8, h=4)
    cw, ch, n, fps, dur, wav = cdmd.cdmd_video_info(clip)
    assert (cw, ch, n) == (8, 4, 6)
    assert fps > 0 and dur > 0

    # single-frame still -> not a video slot
    still = _make_cdmd(str(tmp_path / "still.cdmd"), nframes=1, w=8, h=4)
    assert cdmd.cdmd_video_info(still) is None

    # wrong magic (font/glyph data) -> not a video
    bad = tmp_path / "glyph.cdmd"
    bad.write_bytes(b"dmd\x00" + b"\x00" * 32)
    assert cdmd.cdmd_video_info(str(bad)) is None


def test_cdmd_info_fps_from_sibling_wav(tmp_path):
    clip = _make_cdmd(str(tmp_path / "v.cdmd"), nframes=30, with_wav=True)
    _cw, _ch, n, fps, dur, wav = cdmd.cdmd_video_info(clip)
    assert wav is not None
    assert abs(dur - 1.0) < 0.05      # the 1s wav drives duration
    assert abs(fps - 30.0) < 1.0      # 30 frames / 1s


def test_preview_frame_png_decodes(tmp_path):
    clip = _make_cdmd(str(tmp_path / "v.cdmd"), nframes=4, w=8, h=4)
    png = cdmd.preview_frame_png(clip, pos=0.0, target_w=16, target_h=8)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"


# ---- core.video backend wiring -------------------------------------------

def test_backend_registered_and_dispatches(tmp_path):
    assert ".cdmd" in video.backend_exts()
    clip = _make_cdmd(str(tmp_path / "v.cdmd"), nframes=4, w=8, h=4)
    info = video.detect_video_info(clip)            # routed to the backend
    assert info is not None and info.vcodec == "cdmd"
    assert info.width == 8 and info.nframes == 4
    assert video.audio_source_for(clip) is None     # no sibling wav here


def test_generator_stream_yields_frames(tmp_path):
    clip = _make_cdmd(str(tmp_path / "v.cdmd"), nframes=3, w=8, h=4)
    stream = video.open_raw_stream(clip, 8, 4, fps=30.0, start=0.0)
    assert stream is not None
    data = stream.read(8 * 4 * 3)
    assert len(data) == 8 * 4 * 3
    stream.terminate()
    assert stream.poll() is not None


# ---- scanning + staging ---------------------------------------------------

def test_scan_surfaces_clips_and_skips_stills(tmp_path):
    _make_cdmd(str(tmp_path / "clips" / "movie.cdmd"), nframes=5)
    _make_cdmd(str(tmp_path / "icon.cdmd"), nframes=1)  # still -> skipped
    slots = video_slots.scan_video_slots(str(tmp_path), exts=(".cdmd",))
    assert [s.rel_path for s in slots] == ["clips/movie.cdmd"]
    assert slots[0].info.nframes == 5


def test_dp_video_slot_exts_includes_cdmd(manufacturers_by_key):
    exts = manufacturers_by_key["dp"].video_slot_exts("anything")
    assert ".cdmd" in exts and ".mp4" in exts


def test_dp_dirs_exclude_decoded_videos_but_keep_cdmd(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    (tmp_path / "_DECODED VIDEOS").mkdir()
    _make_cdmd(str(tmp_path / "_DECODED VIDEOS" / "should_not_count.cdmd"))
    _make_cdmd(str(tmp_path / "videos" / "real.cdmd"), nframes=5)
    roots = dp.video_slot_dirs(str(tmp_path))
    exts = dp.video_slot_exts(str(tmp_path))
    found = video_slots.scan_video_slots(str(tmp_path), roots=roots, exts=exts)
    assert [s.rel_path for s in found] == ["videos/real.cdmd"]


def test_stage_reencodes_replacement_into_cdmd(tmp_path):
    from pinball_decryptor.core.video import find_ffmpeg
    if not find_ffmpeg():
        pytest.skip("ffmpeg not available")

    slot_path = str(tmp_path / "clips" / "movie.cdmd")
    _make_cdmd(slot_path, nframes=6, w=16, h=8)
    # a replacement clip in a normal format + different size
    rep = str(tmp_path / "rep.mp4")
    r = subprocess.run(
        [find_ffmpeg(), "-y", "-f", "lavfi",
         "-i", "testsrc=size=64x48:rate=10:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", rep],
        capture_output=True)
    if r.returncode != 0:
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in
             video_slots.scan_video_slots(str(tmp_path), exts=(".cdmd",))}
    rel = "clips/movie.cdmd"
    staged, failures = video_slots.stage_replacements({rel: slots[rel]},
                                                      {rel: rep})
    assert staged == 1 and failures == []

    # still a valid cdmd, same canvas + frame count as the original
    info = cdmd.cdmd_video_info(slot_path)
    assert info is not None
    cw, ch, n, _fps, _dur, _wav = info
    assert (cw, ch, n) == (16, 8, 6)
