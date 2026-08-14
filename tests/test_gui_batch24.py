"""Feedback batch 24 — logic-level tests for the Video/Audio tab fixes.

No Tk window is built: the methods under test only touch plain attributes,
so a duck-typed ``self`` exercises them the way the async workers do.
"""

import os
import time
from types import SimpleNamespace

from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.gui.main_window import MainWindow


def _var(v):
    return SimpleNamespace(get=lambda: v)


def _slot(codec="h264", pix_fmt="yuv420p", ext=".mov", info=True):
    vi = VideoInfo(path="s" + ext, vcodec=codec, width=1360, height=768,
                   fps=30.0, duration=25.0, pix_fmt=pix_fmt,
                   container=ext.lstrip(".")) if info else None
    return VideoSlot(rel_path="video/AttractMode" + ext,
                     abs_path="/assets/video/AttractMode" + ext, ext=ext,
                     info=vi, size=1024)


# ---------------------------------------------------------------------------
# The Convert cache key follows the FILE, not just its name.  He re-exported
# his ProRes pick as H.264 over the same .mov and the column kept serving the
# old file's verdict through re-picks and re-scans.
# ---------------------------------------------------------------------------

class _ConvStub:
    """Just enough of MainWindow for the Convert cache key.

    The key asks ``_video_asis_for`` rather than reading the tab-wide box
    directly, since batch 37 gave each clip its own optional conversion
    setting — with no per-clip flag set, the answer is still the box.
    """
    _video_asis_for = MainWindow._video_asis_for

    def __init__(self):
        self.video_no_conversion_var = _var(True)
        self.video_trim_var = _var(False)
        self._video_asis_flags = {}


def _conv_self():
    return _ConvStub()


def test_conv_key_changes_when_the_file_is_rewritten(tmp_path):
    rep = tmp_path / "attract.mov"
    rep.write_bytes(b"PRORES-ISH BYTES")
    k1 = MainWindow._video_conv_key(_conv_self(), "video/a.mov", str(rep))
    rep.write_bytes(b"H264 NOW, AND A DIFFERENT SIZE TOO")
    os.utime(rep, (time.time() + 5, time.time() + 5))
    k2 = MainWindow._video_conv_key(_conv_self(), "video/a.mov", str(rep))
    assert k1 != k2


def test_conv_key_stable_for_an_untouched_file(tmp_path):
    rep = tmp_path / "attract.mov"
    rep.write_bytes(b"SAME BYTES")
    me = _conv_self()
    assert (MainWindow._video_conv_key(me, "video/a.mov", str(rep))
            == MainWindow._video_conv_key(me, "video/a.mov", str(rep)))


def test_conv_key_survives_a_missing_file(tmp_path):
    # A NAS blip mid-refresh must not raise out of a row repaint.
    k = MainWindow._video_conv_key(_conv_self(), "video/a.mov",
                                   str(tmp_path / "gone.mov"))
    assert k[2] == (0, 0)


# ---------------------------------------------------------------------------
# Slots that ALREADY hold an unplayable clip (his ProRes attract went on
# as-is before the pick-time gate existed) are flagged in the Format column
# and called out in the log, so he can find every slot that needs redoing.
# ---------------------------------------------------------------------------

class _SternStub:
    """Just enough of MainWindow for the slot-playability helpers."""
    _slot_unplayable = MainWindow._slot_unplayable
    _video_fmt_cell = MainWindow._video_fmt_cell
    _warn_unplayable_slot = MainWindow._warn_unplayable_slot

    def __init__(self, key="stern"):
        self._current_mfr = SimpleNamespace(key=key)
        self._video_scan_dir = "/assets"
        self._video_unplayable_warned = set()
        self.logs = []

    def append_log(self, text, level="info"):
        self.logs.append((text, level))


def test_prores_in_the_slot_is_unplayable():
    why = _SternStub()._slot_unplayable(_slot(codec="prores"))
    assert why and "PRORES" in why and "H.264" in why


def test_ten_bit_in_the_slot_is_unplayable():
    why = _SternStub()._slot_unplayable(_slot(pix_fmt="yuv422p10le"))
    assert why and "8-bit" in why


def test_stock_h264_is_fine_and_unprobed_makes_no_claim():
    me = _SternStub()
    assert me._slot_unplayable(_slot()) is None
    assert me._slot_unplayable(_slot(info=False)) is None


def test_non_stern_machines_make_no_claim():
    assert _SternStub(key="jjp")._slot_unplayable(
        _slot(codec="prores")) is None


def test_fmt_cell_carries_the_flag_and_log_fires_once():
    me = _SternStub()
    slot = _slot(codec="prores")
    assert me._video_fmt_cell(slot).endswith("⚠")
    assert not me._video_fmt_cell(_slot()).endswith("⚠")
    me._warn_unplayable_slot(slot.rel_path, slot)
    me._warn_unplayable_slot(slot.rel_path, slot)
    assert len(me.logs) == 1
    text, level = me.logs[0]
    assert level == "error" and "black picture" in text


# ---------------------------------------------------------------------------
# Restore warnings: a slot whose replacement is ALREADY on disk (it has a
# .orig snapshot) gets a calm info note, not red — he read the red line as a
# clip that "cannot be loaded from my NAS" while it played fine.
# ---------------------------------------------------------------------------

def test_dropped_warning_demotes_applied_slots(tmp_path):
    import shutil
    assets = tmp_path / "assets"
    (assets / "video").mkdir(parents=True)
    (assets / ".orig" / "video").mkdir(parents=True)
    (assets / "video" / "a.mov").write_bytes(b"replacement bytes")
    (assets / ".orig" / "video" / "a.mov").write_bytes(b"original bytes")
    (assets / "video" / "b.mov").write_bytes(b"stock bytes")

    saved = {  # both sources vanished since they were picked
        "video/a.mov": str(tmp_path / "gone_applied.mp4"),
        "video/b.mov": str(tmp_path / "gone_pending.mp4"),
    }
    slots = {"video/a.mov": object(), "video/b.mov": object()}
    logs = []
    me = SimpleNamespace(
        append_log=lambda text, level="info": logs.append((text, level)))
    MainWindow._warn_dropped_assignments(me, "video", saved, slots,
                                         str(assets))
    by_level = {lv: t for t, lv in logs}
    assert len(logs) == 2
    assert "already holds its video replacement" in by_level["info"]
    assert "video/a.mov" in by_level["info"]
    assert "wasn't restored" in by_level["error"]
    assert "video/b.mov" in by_level["error"]
    shutil.rmtree(assets)


# ---------------------------------------------------------------------------
# Play-through "Substitute replacements": which rows have something for the
# Replacement pane to play.
# ---------------------------------------------------------------------------

def test_audio_rep_available(tmp_path):
    assets = tmp_path / "assets"
    (assets / "audio").mkdir(parents=True)
    (assets / ".orig" / "audio").mkdir(parents=True)
    rep_src = tmp_path / "my_callout.mp3"
    rep_src.write_bytes(b"mp3")
    (assets / "audio" / "built.wav").write_bytes(b"replacement bytes")
    (assets / ".orig" / "audio" / "built.wav").write_bytes(b"original")
    (assets / "audio" / "stock.wav").write_bytes(b"stock")

    me = SimpleNamespace(
        _audio_assignments={"audio/assigned.wav": str(rep_src)},
        _audio_changed_on_disk={"audio/built.wav"},
        _audio_scan_dir=str(assets),
        _audio_slots_by_rel={
            "audio/built.wav": SimpleNamespace(
                abs_path=str(assets / "audio" / "built.wav")),
            "audio/stock.wav": SimpleNamespace(
                abs_path=str(assets / "audio" / "stock.wav")),
        },
    )
    avail = MainWindow._audio_rep_available
    assert avail(me, "audio/assigned.wav")        # live assignment
    assert avail(me, "audio/built.wav")           # changed on disk + snapshot
    assert not avail(me, "audio/stock.wav")       # nothing replaced
    me._audio_assignments["audio/assigned.wav"] = str(tmp_path / "gone.mp3")
    assert not avail(me, "audio/assigned.wav")    # source vanished
