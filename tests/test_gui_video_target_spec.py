"""The Video tab's "What this slot needs…" (``video.target_spec``, the web
UI's port of the Tk target-spec dialog): the slot's spec and the ffmpeg
recipe the page shows, or a message instead of a blank dialog."""
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from tests.webui_harness import web_app


def _with_slot(w, slot):
    svc = w.window.service("video")

    def _do():
        svc._by_rel = {slot.rel_path: slot}
    w.run(_do)
    return svc


def test_target_spec_dialog_opens(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        info = VideoInfo(path="a.mov", vcodec="h264", width=1360, height=768,
                         fps=30.0, duration=25.0, pix_fmt="yuv420p",
                         profile="Constrained Baseline", level=30)
        slot = VideoSlot(rel_path="video/AttractMode.mov", abs_path="a.mov",
                         ext=".mov", info=info, size=1)
        _with_slot(w, slot)
        got = w.call("video.target_spec", "video/AttractMode.mov")
        assert got is not None
        blob = "\n".join(["%s: %s" % tuple(p) for p in got["spec"]]
                         + [got["cmd"]])
        assert "1360 x 768" in blob
        assert "Constrained Baseline" in blob
        assert "-profile:v baseline" in blob
        assert "-an" in blob
        assert got["silent"] is True


def test_unprobed_slot_says_so_instead_of_a_blank_dialog(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        slot = VideoSlot(rel_path="video/x.mov", abs_path="x.mov", ext=".mov",
                         info=None, size=1)
        _with_slot(w, slot)
        n = len(w.asked)
        assert w.call("video.target_spec", "video/x.mov") is None
        said = w.asked[n:]
        assert said and said[0]["title"] == "What this slot needs"
