"""Tests for exporting a rendered scene to MP4 (core.video.encode_frames_to_mp4).

The Scenes window's "Save preview…" writes an animated scene as H.264 through
this.  The encode tests need a real ffmpeg and skip without one; the argument /
streaming / failure tests run anywhere.
"""

import os
import subprocess

import pytest

from pinball_decryptor.core import video
from pinball_decryptor.core.video import encode_frames_to_mp4, find_ffmpeg

Image = pytest.importorskip("PIL.Image")


def _frame(i, size=(64, 48)):
    """A frame that differs from its neighbours, so a desynced raw stream
    would show up as a decode error rather than pass silently."""
    img = Image.new("RGB", size, (10 * (i % 20), 60, 200 - 4 * (i % 40)))
    img.paste(Image.new("RGB", (8, 8), (255, 255, 0)), (i % (size[0] - 8), 4))
    return img


def _probe(path):
    """(codec, width, height, nb_frames) via ffprobe, or None."""
    from pinball_decryptor.core.video import find_ffprobe
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,nb_read_frames",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout.split()
    if len(out) < 4:
        return None
    return out[0], int(out[1]), int(out[2]), int(out[3])


# ---- argument handling (no ffmpeg needed) ---------------------------------

def test_no_frames_is_a_value_error(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    with pytest.raises(ValueError):
        encode_frames_to_mp4(iter(()), str(tmp_path / "out.mp4"))


def test_all_none_frames_is_a_value_error(tmp_path, monkeypatch):
    """render_layout returns None for a frame it can't draw; a generator of
    nothing but those is 'no frames', not a zero-byte MP4."""
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    with pytest.raises(ValueError):
        encode_frames_to_mp4(iter([None, None]), str(tmp_path / "out.mp4"))


def test_missing_ffmpeg_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "find_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError) as e:
        encode_frames_to_mp4(iter([_frame(0)]), str(tmp_path / "out.mp4"))
    assert "ffmpeg" in str(e.value).lower()


def test_frames_are_pulled_lazily(tmp_path, monkeypatch):
    """The whole point of the generator: a long scene is never all in memory.

    Fails the encode deliberately (ffmpeg missing) AFTER one frame would have
    been consumed, and asserts the generator was not drained first."""
    monkeypatch.setattr(video, "find_ffmpeg", lambda: None)
    pulled = []

    def gen():
        for i in range(500):
            pulled.append(i)
            yield _frame(i)

    with pytest.raises(RuntimeError):
        encode_frames_to_mp4(gen(), str(tmp_path / "out.mp4"))
    assert pulled == [], "frames were materialised before ffmpeg was found"


# ---- real encodes (need ffmpeg) -------------------------------------------

@pytest.mark.slow
def test_encodes_an_h264_mp4(tmp_path):
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    out = str(tmp_path / "scene.mp4")
    n = encode_frames_to_mp4((_frame(i) for i in range(31)), out, fps=30.0)
    assert n == 31
    assert os.path.getsize(out) > 0
    info = _probe(out)
    if info is None:
        pytest.skip("ffprobe not installed")
    codec, w, h, frames = info
    assert codec == "h264"
    assert (w, h) == (64, 48)
    assert frames == 31


@pytest.mark.slow
def test_odd_dimensions_are_padded_even(tmp_path):
    """yuv420p can't encode an odd width/height — an isolated screen out of a
    scene need not be even, and it must not fail the export."""
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    out = str(tmp_path / "odd.mp4")
    n = encode_frames_to_mp4(
        (_frame(i, size=(65, 49)) for i in range(4)), out, fps=12.0)
    assert n == 4
    info = _probe(out)
    if info is None:
        pytest.skip("ffprobe not installed")
    _codec, w, h, _frames = info
    assert (w, h) == (66, 50)


@pytest.mark.slow
def test_progress_reports_every_frame(tmp_path):
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    seen = []
    n = encode_frames_to_mp4(
        (_frame(i) for i in range(10)), str(tmp_path / "p.mp4"),
        fps=12.0, progress=seen.append)
    assert n == 10
    assert seen == list(range(1, 11))


@pytest.mark.slow
def test_peak_memory_is_one_frame(tmp_path):
    """A 1900-frame 1360x768 scene is ~6 GB held at once; the encoder must
    never hold more than a couple of frames however long the scene is."""
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    alive = {"now": 0, "peak": 0}

    class Tracked:
        """A PIL image that notices when the encoder drops it."""

        def __init__(self, img):
            self._img = img
            alive["now"] += 1
            alive["peak"] = max(alive["peak"], alive["now"])

        def __del__(self):
            alive["now"] -= 1

        def __getattr__(self, name):
            return getattr(self._img, name)

    def gen():
        for i in range(120):
            yield Tracked(_frame(i))

    n = encode_frames_to_mp4(gen(), str(tmp_path / "big.mp4"), fps=30.0)
    assert n == 120
    assert alive["peak"] <= 3, "held %d frames at once" % alive["peak"]


@pytest.mark.slow
def test_a_mismatched_frame_does_not_desync_the_stream(tmp_path):
    """One odd-sized frame mid-scene is placed on a correct-size canvas
    instead of shifting every later frame into diagonal garbage."""
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    frames = [_frame(0), _frame(1, size=(32, 24)), _frame(2)]
    out = str(tmp_path / "mixed.mp4")
    n = encode_frames_to_mp4(iter(frames), out, fps=12.0)
    assert n == 3
    info = _probe(out)
    if info is None:
        pytest.skip("ffprobe not installed")
    _codec, w, h, count = info
    assert (w, h) == (64, 48)
    assert count == 3


@pytest.mark.slow
def test_ffmpeg_failure_is_reported(tmp_path, monkeypatch):
    """An unwritable destination must raise, not return a frame count for a
    file that isn't there."""
    if not find_ffmpeg():
        pytest.skip("ffmpeg not installed")
    bad = str(tmp_path / "nope.mp4")
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
    # An extension ffmpeg has no muxer for fails at once, whatever the OS.
    with pytest.raises(RuntimeError):
        encode_frames_to_mp4((_frame(i) for i in range(3)),
                             bad + ".notaformat", fps=12.0)
