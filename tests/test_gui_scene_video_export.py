"""Scenes tab: a scene saved as a video, and every listed scene as videos in one click
(PAD-365, Peanutsfr).

A scene drawn from its tree (the editor) that has more than one frame offers "Export video…":
the whole timeline, full size, at the scene's own frame rate, drawn the way Play draws it.
"Export all videos…" writes one MP4 per listed scene that moves (and a PNG of a still one)
into a folder the user picks, in the background, with the button as Cancel meanwhile.
"""

import os

import pytest

from tests.test_gui_scene_editor import _open, _seed, _wait
from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")


def _need_ffmpeg():
    from pinball_decryptor.core.video import find_ffmpeg
    if not find_ffmpeg():
        pytest.skip("ffmpeg is not installed here")


def _probe(path):
    """(frames, fps, width, height) of the MP4 at *path* (frames from its length)."""
    from pinball_decryptor.core.video import detect_video_info
    info = detect_video_info(str(path))
    assert info is not None and info.vcodec == "h264", path
    return int(round(info.duration * info.fps)), info.fps, info.width, info.height


def test_a_scene_that_moves_exports_as_a_video(tmp_path):
    """"Save a scene as a video": the save dialog offers MP4 first (PNG too, no GIF: the
    preview is one frame), and the MP4 holds every frame of the timeline at the scene's own
    rate, the stage size."""
    _need_ffmpeg()
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    frames = int(man["root"]["frames"])
    fps = float(man["stage"][2] or 30)
    assert frames > 1
    with web_app(tmp_path, mfr="stern") as w:
        sb = _open(w, folder)
        assert _wait(w, lambda: w.state("text_scenes").get("can_video") is True)
        out = tmp_path / "scene.mp4"
        w.answers.append(str(out))
        assert w.call("text_scenes.save_preview") is True
        spec = w.asked[-1]
        assert spec["mode"] == "save" and spec["initialfile"].endswith(".mp4")
        assert [t[1] for t in spec["filetypes"]] == ["*.mp4", "*.png"]
        assert _wait(w, lambda: sb._export is None and out.is_file(), 90)
        st = w.state("text_scenes")
        assert st["exporting"] is False
        assert st["export_msg"].startswith("Saved scene.mp4 — %d frames" % frames), st["export_msg"]
        n, rate, wd, ht = _probe(out)
        assert n == frames and rate == pytest.approx(fps, abs=0.01)
        assert (wd, ht) == (int(man["stage"][0]), int(man["stage"][1]))
        w.call("text_scenes.close")


def test_the_frame_on_the_preview_still_saves_as_a_png(tmp_path):
    """Picking PNG in the same dialog saves the frame on the preview, as before."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert _wait(w, lambda: w.state("text_scenes").get("can_video") is True)
        out = tmp_path / "scene.png"
        w.answers.append(str(out))
        assert w.call("text_scenes.save_preview") is True
        assert out.is_file()
        from PIL import Image
        with Image.open(out) as im:
            assert im.size[0] > 1 and im.size[1] > 1
        assert w.state("text_scenes")["export_msg"] == "Saved scene.png"
        w.call("text_scenes.close")


def test_export_all_videos_writes_an_mp4_per_listed_scene(tmp_path):
    """"Export all the scenes as videos, in one click": one MP4 per listed scene that moves,
    into the folder picked, and the message beside the buttons says what was written."""
    _need_ffmpeg()
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    frames = int(man["root"]["frames"])
    with web_app(tmp_path, mfr="stern") as w:
        sb = _open(w, folder)
        out = tmp_path / "videos"
        out.mkdir()
        w.answers.append(str(out))
        assert w.call("text_scenes.save_all_videos") is True
        spec = w.asked[-1]
        assert spec["mode"] == "folder"
        assert _wait(w, lambda: sb._vbulk is None, 90)
        st = w.state("text_scenes")
        assert st["bulk_video"] is False
        assert st["export_msg"] == "Saved 1 video to videos.", st["export_msg"]
        files = sorted(os.listdir(out))
        assert len(files) == 1 and files[0].endswith(".mp4"), files
        n, _rate, _w, _h = _probe(out / files[0])
        assert n == frames
        w.call("text_scenes.close")


def test_export_all_videos_needs_ffmpeg_and_says_so(tmp_path, monkeypatch):
    """Without ffmpeg the batch does not start (no folder is asked for): one message."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    monkeypatch.setattr("pinball_decryptor.core.video.find_ffmpeg", lambda: "")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        asked = len(w.asked)
        assert w.call("text_scenes.save_all_videos") is False
        assert w.state("text_scenes")["bulk_video"] is False
        assert all(a.get("kind") != "file" for a in w.asked[asked:])
        assert any("ffmpeg" in str(a.get("message", "")) for a in w.asked[asked:])
        w.call("text_scenes.close")


def test_unique_names_keep_their_extension():
    from pinball_decryptor.webui.text_scenes import _unique_name
    used = set()
    assert _unique_name("Intro / A", used, "mp4") == "Intro___A.mp4"
    assert _unique_name("Intro   A", used, "mp4") == "Intro___A_2.mp4"
    assert _unique_name("Intro___A", used, "png") == "Intro___A_3.png"
