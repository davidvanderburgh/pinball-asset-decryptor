"""The layered test from the app (Simon, 2026-11-26) and test card videos through the machine's decoder.

Simon: the layered test - "a clip with scenes over it (e.g. Match clip + 0335207f MATCH/digits + 9d578751 score
panel)" - made on the Scenes tab (Layered test…), kept on the Test card tab's list as one video with its scenes
(testcard_core.Item.layers), built as a clip plus an overlay (layered_test.make_overlay, selectmedia --test-overlay).
And every Spike 2 test card video now plays through the machine's own decoder (30 fps on the table) instead of JPEG
frames (0.1-0.5 fps)."""
import inspect
import os
import types

import pytest

from pinball_decryptor.webui import testcard_core as tc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TESTCARD_STORE", str(tmp_path / "store" / "testcard.json"))
    tc._SHARED[:] = []
    yield
    tc._SHARED[:] = []


def _info(w, h, codec="h264", fmt=""):
    from pinball_decryptor.core import video
    return video.VideoInfo("x", vcodec=codec, width=w, height=h, fps=30.0, duration=7.4, pix_fmt=fmt)


def test_a_clip_the_decoder_plays_goes_as_it_is(tmp_path, monkeypatch):
    from pinball_decryptor.core import video
    monkeypatch.setattr(video, "detect_video_info", lambda p: _info(1360, 768))
    called = []
    monkeypatch.setattr(video, "transcode_video_to", lambda *a, **k: called.append(a) or (True, ""))
    assert tc.as_clip(str(tmp_path / "match.mp4"), str(tmp_path), 0) == str(tmp_path / "match.mp4")
    assert not called
    monkeypatch.setattr(video, "detect_video_info", lambda p: _info(1360, 768, fmt="yuvj420p"))
    assert tc.as_clip(str(tmp_path / "jpeg_range.mp4"), str(tmp_path), 0) == str(tmp_path / "jpeg_range.mp4")
    assert not called
    assert tc.as_clip(str(tmp_path / "anim.gif"), str(tmp_path), 0) is None, "a GIF stays frames"


@pytest.mark.parametrize("name,info,want", [
    ("big.mp4", (3840, 2160, "h264"), (1920, 1080)),      # past the VPU's 1920x1088: fitted inside it
    ("hevc.mp4", (1360, 768, "hevc"), (1360, 768)),      # not H.264: made into it, same size
    ("old.avi", (640, 480, "mpeg4"), (640, 480)),        # not a container the menu opens
    ("hi10.mp4", (1360, 768, "h264", "yuv420p10le"), (1360, 768)),   # 10-bit: the VPU decodes 8-bit only
    ("full.mp4", (1360, 768, "h264", "yuv444p"), (1360, 768)),       # 4:4:4: the VPU decodes 4:2:0 only
    ("odd.mp4", (1359, 767, "h264", "yuv420p"), (1358, 766)),        # odd sizes: chroma read at half the even
])
def test_anything_else_is_made_into_one(tmp_path, monkeypatch, name, info, want):
    from pinball_decryptor.core import video
    monkeypatch.setattr(video, "detect_video_info", lambda p: _info(*info))
    seen = {}

    def transcode(src, dst, target, **kw):
        seen.update(dst=dst, w=target.width, h=target.height, codec=target.vcodec)
        return True, ""
    monkeypatch.setattr(video, "transcode_video_to", transcode)
    got = tc.as_clip(str(tmp_path / name), str(tmp_path), 3)
    assert got == seen["dst"] and got.endswith("clip03.mp4")
    assert (seen["w"], seen["h"], seen["codec"]) == want + ("h264",)


def test_staging_sends_videos_as_clips_on_spike_2_only(tmp_path, monkeypatch):
    clip = tmp_path / "match.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(tc, "as_clip", lambda path, work, n, log=print, cancel=None: path)
    items = [tc.Item("video", "Match", str(clip))]
    assert tc.stage(items, str(tmp_path / "w"), clips=True) == [("clip", str(clip), "Match")]
    assert tc.stage(items, str(tmp_path / "w2")) == [("video", str(clip), "Match")], "Spike 3: frames, as before"


def test_a_layered_item_keeps_its_scenes_and_builds_its_overlay(tmp_path, monkeypatch):
    clip = tmp_path / "match.mp4"
    clip.write_bytes(b"x")
    it = tc.Item("video", "Match over match", str(clip), str(tmp_path), "video/match.mp4", "Godzilla",
                 layers=["9d578751@MatchFrame", "0335207f"])
    again = tc.Item.from_json(it.to_json())
    assert again.layers == ("9d578751@MatchFrame", "0335207f")
    assert again.key() != tc.Item("video", "m", str(clip), str(tmp_path), "video/match.mp4").key(), \
        "the plain clip and its layered test are two items"
    lst = tc.shared()
    assert lst.add_layered(it) == "" and "already" in lst.add_layered(it)
    monkeypatch.setattr(tc, "as_clip", lambda path, work, n, log=print, cancel=None: path)
    made = []
    monkeypatch.setattr(tc, "layer_overlay", lambda item, path, work, n, log=print: made.append(item.layers) or "o.pado")
    staged = tc.stage([it], str(tmp_path / "w"), clips=True, resolver=lambda item: None)   # no colour profile
    assert staged == [("clip", str(clip), "Match over match", "o.pado")]
    assert made == [("9d578751@MatchFrame", "0335207f")]
    assert tc.stage([it], str(tmp_path / "w3"), resolver=lambda item: None) == [],         "a Spike 3 card plays no clips: left out"


def test_the_overlay_goes_with_its_test_by_number():
    args = tc.test_specs([("scene", "/a.png", "S"), ("clip", "/m.mp4", "M", "/m.pado")])
    assert args == ["--test", "scene:/a.png|S", "--test", "clip:/m.mp4|M", "--test-overlay", "1=/m.pado"]


def test_the_overlay_is_timed_by_the_clips_own_frames():
    src = inspect.getsource(tc.layer_overlay)
    assert "frames, fps = LT.clip_frames(clip)" in src and "LT.make_overlay(item.project, list(item.layers)" in src
    from pinball_decryptor.plugins.stern import layered_test as LT
    assert "find_ffprobe()" in inspect.getsource(LT.clip_frames), "PAD's own ffprobe on Windows"


def test_the_scenes_tab_offers_it():
    from pinball_decryptor.webui import text_scenes as TS
    assert hasattr(TS.TextScenesService, "layered_options") and hasattr(TS.TextScenesService, "add_layered")
    src = inspect.getsource(TS.TextScenesService.add_layered)
    assert 'os.path.basename(d) + ("@" + pin if pin else "")' in src
    assert "tc.shared().add_layered(" in src and "tc.changed(self.window)" in src
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "text_scenes.js"),
              encoding="utf-8").read()
    # Simon (2026-11-26): the Scenes tab's list of layered tests opens it (New… / Edit)
    assert "function LayeredDialog" in js and ">New…<//>" in js
    # Simon (2026-11-26): with the video player's state, the layered test it replaces (Edit) and its colours
    assert ('call("text_scenes.add_layered", layers.map((l) => ({ d: l.d, pin: l.pin })), clip, label, player,'
            in js)
    assert "index == null ? null : index, plain);" in js


def test_both_builds_ask_for_clips():
    src = open(os.path.join(ROOT, "pinball_decryptor", "webui", "tabs", "testcard.py"), encoding="utf-8").read()
    assert "clips=not s3)" in src
    from pinball_decryptor.webui import multiboot_core as mbc
    assert "clips=True" in inspect.getsource(mbc.MultibootPanel._stage_test_entry)


def test_a_layered_tests_row_says_so(monkeypatch):
    from pinball_decryptor.webui.tabs.testcard import TestCardTab
    t = TestCardTab.__new__(TestCardTab)
    t.window = types.SimpleNamespace(service=lambda n: None)
    t.state = {}
    t.set = lambda **kw: t.state.update(kw)
    t._lines, t._busy, t._pct, t._step, t._msg, t._cancel, t._proc = [], False, None, "", ("", ""), False, None
    t._address = lambda: ""
    tc.shared().items.append(tc.Item("video", "L", __file__, layers=["0335207f"]))
    t._pub()
    row = t.state["rows"][0]
    assert "layered: 1 scene over it (0335207f)" in row["where"]


def test_the_clip_under_a_layered_test_is_one_of_the_projects_videos(tmp_path):
    """PR #50 review: add_layered's clip comes from the browser; only a video file in the project's own video
    folder is taken (layered_options offers nothing else), never a file elsewhere on the PC."""
    from pinball_decryptor.webui import text_scenes as TS
    proj = tmp_path / "proj"
    (proj / "video").mkdir(parents=True)
    (proj / "video" / "match.txt").write_text("x")
    (tmp_path / "secret.mp4").write_bytes(b"x")
    (proj / "notes.mp4").write_bytes(b"x")
    svc = TS.TextScenesService.__new__(TS.TextScenesService)
    svc.assets_dir, svc._scenes, svc.window = str(proj), {"/s/0335207f": {"label": "Match"}}, None
    layers = [{"d": "/s/0335207f", "pin": ""}]
    for rel in ("../secret.mp4", "notes.mp4", "video/match.txt", "video/../../secret.mp4", ""):
        assert svc.add_layered(layers, rel) == "Pick the video to play under the scenes.", rel
