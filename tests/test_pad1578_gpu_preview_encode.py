"""PAD-1578: preview copies (the preview pane, Video Compare, the Audio tab's player) are made on the PC's GPU
encoder when a one-frame test encode with it works, with libx264 as the fallback, both when no GPU encoder works
and when one fails on a real clip.  Card clips keep their own x264 flags in core.video."""

import os
import shutil
import subprocess

import pytest

from pinball_decryptor.core import preview_encoder as pe


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("PAD_PREVIEW_ENCODER", raising=False)
    monkeypatch.delenv("PAD_PREVIEW_DECODE", raising=False)
    pe.reset()
    yield
    pe.reset()


def test_first_working_candidate_wins_and_is_probed_once(monkeypatch):
    tried = []

    def probe(ff, name):
        tried.append(name)
        return name == "qsv"

    monkeypatch.setattr(pe, "probe", probe)
    monkeypatch.setattr(pe, "candidates", lambda platform=None: ["nvenc", "qsv", "amf"])
    assert pe.h264_args("ff")[0] == "qsv"
    assert pe.h264_args("ff") == ("qsv", pe._GPU["qsv"])
    assert tried == ["nvenc", "qsv"]                 # once per run, stops at the first that works


def test_no_working_gpu_encoder_is_x264(monkeypatch):
    monkeypatch.setattr(pe, "probe", lambda ff, name: False)
    name, args = pe.h264_args("ff")
    assert name == "x264" and args == pe.X264
    assert args[:2] == ["-c:v", "libx264"]


def test_override_forces_x264_without_probing(monkeypatch):
    monkeypatch.setenv("PAD_PREVIEW_ENCODER", "x264")
    monkeypatch.setattr(pe, "probe", lambda ff, name: pytest.fail("probed"))
    assert pe.pick("ff") == "x264"


def test_override_names_one_candidate(monkeypatch):
    monkeypatch.setenv("PAD_PREVIEW_ENCODER", "amf")
    tried = []
    monkeypatch.setattr(pe, "probe", lambda ff, name: tried.append(name) or True)
    assert pe.pick("ff") == "amf" and tried == ["amf"]


def test_failed_drops_encoder_only_when_its_test_fails_too(monkeypatch):
    ok = {"nvenc": True}
    monkeypatch.setattr(pe, "probe", lambda ff, name: ok.get(name, False))
    monkeypatch.setattr(pe, "candidates", lambda platform=None: ["nvenc"])
    assert pe.pick("ff") == "nvenc"
    pe.failed("ff", "nvenc")                         # a busy moment: the test still passes
    assert pe.pick("ff") == "nvenc"
    ok["nvenc"] = False
    pe.failed("ff", "nvenc")
    assert pe.pick("ff") == "x264"


def test_candidates_per_platform():
    assert pe.candidates("win32") == ["nvenc", "qsv", "amf"]
    assert pe.candidates("darwin") == ["videotoolbox"]
    assert pe.candidates("linux") == ["nvenc"]


def test_every_gpu_flag_set_makes_browser_playable_h264():
    for name, args in pe._GPU.items():
        assert args[args.index("-c:v") + 1].startswith("h264_"), name
        assert args[args.index("-profile:v") + 1] == "main", name
        assert args[args.index("-pix_fmt") + 1] in ("yuv420p", "nv12"), name


def test_probe_never_raises_on_a_missing_ffmpeg(tmp_path):
    assert pe.probe(str(tmp_path / "no-ffmpeg.exe"), "nvenc") is False
    assert pe.probe(None, "x264") is False
    assert pe.probe("ffmpeg", "no-such-encoder") is False


def test_card_encoders_stay_x264():
    from pinball_decryptor.core import video
    assert video._ENCODERS["h264"][0][:2] == ["-c:v", "libx264"]


def _proxy_env(monkeypatch, tmp_path, vh):
    monkeypatch.setattr(vh, "cache_dir", lambda: str(tmp_path))


def test_proxy_uses_picked_encoder_and_falls_back_to_x264(tmp_path, monkeypatch):
    from pinball_decryptor.core import video as _video
    from pinball_decryptor.webui import video_helpers as vh
    _proxy_env(monkeypatch, tmp_path, vh)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ff")
    monkeypatch.setattr(_video, "detect_video_info", lambda p: None)
    monkeypatch.setattr(_video, "backend_for", lambda p: None)
    monkeypatch.setattr(pe, "candidates", lambda platform=None: ["nvenc"])
    alive = {"nvenc": True}
    monkeypatch.setattr(pe, "probe", lambda ff, name: alive.get(name, False))
    monkeypatch.setattr(pe, "probe_decode", lambda ff, hw: False)
    runs = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stderr = rc, b"encoder fell over"

    def run(cmd, **kw):
        enc = cmd[cmd.index("-c:v") + 1]
        runs.append(enc)
        if enc == "h264_nvenc":
            alive["nvenc"] = False                      # the GPU encoder has gone away
            return R(1)
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4")
        return R(0)

    monkeypatch.setattr(vh.subprocess, "run", run)
    out = vh.browser_proxy(str(clip), "mp4")
    assert open(out, "rb").read() == b"mp4"
    assert runs == ["h264_nvenc", "libx264"]
    assert pe.pick("ff") == "x264"                       # dropped for the rest of the run
    os.remove(out)
    vh.browser_proxy(str(clip), "mp4")
    assert runs[-1] == "libx264" and len(runs) == 3


def test_proxy_x264_failure_still_reports(tmp_path, monkeypatch):
    from pinball_decryptor.core import video as _video
    from pinball_decryptor.webui import video_helpers as vh
    _proxy_env(monkeypatch, tmp_path, vh)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ff")
    monkeypatch.setattr(_video, "detect_video_info", lambda p: None)
    monkeypatch.setattr(_video, "backend_for", lambda p: None)
    monkeypatch.setenv("PAD_PREVIEW_ENCODER", "x264")
    monkeypatch.setenv("PAD_PREVIEW_DECODE", "cpu")

    class R:
        returncode, stderr = 1, b"bad clip"

    calls = []
    monkeypatch.setattr(vh.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    with pytest.raises(RuntimeError, match="bad clip"):
        vh.browser_proxy(str(clip), "mp4")
    assert len(calls) == 1                               # no pointless second try


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_real_ffmpeg_probe_x264_works():
    assert pe.probe(shutil.which("ffmpeg"), "x264") is True


def test_decode_probed_once_and_switchable(monkeypatch):
    tried = []
    monkeypatch.setattr(pe, "probe_decode", lambda ff, hw: tried.append(hw) or True)
    monkeypatch.setattr(pe, "hwaccels", lambda platform=None: ["d3d11va"])
    monkeypatch.setattr(pe, "worth_gpu_decode", lambda info, threads=None: True)
    assert pe.decode_args("ff") == ["-hwaccel", "d3d11va"]
    assert pe.decode_args("ff") == ["-hwaccel", "d3d11va"] and tried == ["d3d11va"]
    pe.reset()
    monkeypatch.setenv("PAD_PREVIEW_DECODE", "cpu")
    assert pe.decode_args("ff") == [] and tried == ["d3d11va"]


class _Info:
    def __init__(self, duration, width, height):
        self.duration, self.width, self.height = duration, width, height


def test_gpu_decode_only_when_threads_are_short():
    # The real clips the rule was timed on (docs/plans/gpu-preview-encode.md).
    groot, godzilla = _Info(554.4, 1360, 768), _Info(90.2, 1360, 768)
    deadpool, short_1080 = _Info(26.1, 1360, 768), _Info(9.7, 1920, 1080)
    assert not pe.worth_gpu_decode(groot, 16, 1)          # big CPU: it decodes faster itself
    assert not pe.worth_gpu_decode(groot, 6, 1)
    assert pe.worth_gpu_decode(groot, 4, 1) and pe.worth_gpu_decode(godzilla, 2, 1)
    assert pe.worth_gpu_decode(godzilla, 16, 4)            # Video Compare's four at once
    assert not pe.worth_gpu_decode(deadpool, 4, 1)         # too short to pay the start-up
    assert pe.worth_gpu_decode(deadpool, 1, 1) and not pe.worth_gpu_decode(short_1080, 4, 1)
    assert not pe.worth_gpu_decode(None) and not pe.worth_gpu_decode(_Info(0, 0, 0), 1, 1)


def test_making_counts_previews_at_once():
    big = _Info(554.4, 1360, 768)
    with pe.making():
        with pe.making(), pe.making(), pe.making():
            assert pe._active[0] == 4 and pe.worth_gpu_decode(big, 16)
        assert pe._active[0] == 1 and not pe.worth_gpu_decode(big, 16)
    assert pe._active[0] == 0


def test_small_clip_never_probes_the_decoder(monkeypatch):
    monkeypatch.setattr(pe, "probe_decode", lambda ff, hw: pytest.fail("probed"))
    assert pe.decode_args("ff", _Info(5, 640, 360)) == []


def test_hwaccels_per_platform():
    assert pe.hwaccels("win32") == ["d3d11va"]
    assert pe.hwaccels("darwin") == ["videotoolbox"]
    assert pe.hwaccels("linux") == ["cuda"]


def _fake_proxy_run(tmp_path, monkeypatch, fail_when):
    from pinball_decryptor.core import video as _video
    from pinball_decryptor.webui import video_helpers as vh
    _proxy_env(monkeypatch, tmp_path, vh)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ff")
    monkeypatch.setattr(_video, "detect_video_info", lambda p: None)
    monkeypatch.setattr(_video, "backend_for", lambda p: None)
    runs = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stderr = rc, b"no"

    def run(cmd, **kw):
        runs.append(cmd)
        if fail_when(cmd):
            return R(1)
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4")
        return R(0)

    monkeypatch.setattr(vh.subprocess, "run", run)
    return vh, str(clip), runs


def test_proxy_decodes_on_gpu_webm_too(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "probe", lambda ff, name: False)
    monkeypatch.setattr(pe, "probe_decode", lambda ff, hw: True)
    monkeypatch.setattr(pe, "hwaccels", lambda platform=None: ["d3d11va"])
    monkeypatch.setattr(pe, "worth_gpu_decode", lambda info, threads=None: True)
    vh, clip, runs = _fake_proxy_run(tmp_path, monkeypatch, lambda cmd: False)
    vh.browser_proxy(clip, "webm")
    assert runs[0][3:6] == ["error", "-hwaccel", "d3d11va"]
    assert runs[0][runs[0].index("-c:v") + 1] == "libvpx"


def test_proxy_gpu_decode_failure_redone_on_cpu(tmp_path, monkeypatch):
    alive = {"d3d11va": True}
    monkeypatch.setattr(pe, "probe", lambda ff, name: False)
    monkeypatch.setattr(pe, "probe_decode", lambda ff, hw: alive.get(hw, False))
    monkeypatch.setattr(pe, "hwaccels", lambda platform=None: ["d3d11va"])
    monkeypatch.setattr(pe, "worth_gpu_decode", lambda info, threads=None: True)

    def fail(cmd):
        if "-hwaccel" in cmd:
            alive["d3d11va"] = False
            return True
        return False

    vh, clip, runs = _fake_proxy_run(tmp_path, monkeypatch, fail)
    vh.browser_proxy(clip, "webm")
    assert ["-hwaccel" in c for c in runs] == [True, False]
    assert runs[1][runs[1].index("-c:v") + 1] == "libvpx"     # webm stays VP8 on the redo
    assert pe.decode_args("ff") == []                         # dropped for the run


def test_backend_clip_gets_no_hwaccel(tmp_path, monkeypatch):
    from pinball_decryptor.core import video as _video
    from pinball_decryptor.webui import video_helpers as vh
    monkeypatch.setattr(pe, "probe", lambda ff, name: False)
    monkeypatch.setattr(pe, "decode_args", lambda ff: pytest.fail("decode asked for a raw-frame clip"))
    _proxy_env(monkeypatch, tmp_path, vh)
    clip = tmp_path / "clip.cdmd"
    clip.write_bytes(b"x")
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ff")
    monkeypatch.setattr(_video, "detect_video_info", lambda p: None)
    monkeypatch.setattr(_video, "backend_for", lambda p: object())
    seen = []

    def fake_backend(ffmpeg, path, info, w, h, vargs, aargs, tail, out, creation):
        seen.append(vargs[1])
        open(out, "wb").write(b"mp4")

    monkeypatch.setattr(vh, "_backend_proxy", fake_backend)
    vh.browser_proxy(str(clip), "mp4")
    assert seen == ["libx264"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_real_ffmpeg_decode_probe_never_raises():
    assert pe.probe_decode(shutil.which("ffmpeg"), "no-such-hwaccel") is False
