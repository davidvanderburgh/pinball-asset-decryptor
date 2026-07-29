"""The Video tab's Convert column under "use my files as-is" — monkeybug b23.

He replaced 29 clips with the as-is box ticked, and the column answered for
exactly one of them.  Two separate reasons both rendered as an empty cell: a
pick Write would refuse outright (his .mp4 files against .mov slots), and a
pick Write would happily copy on but the machine cannot decode — which is how
his attract video reached the card and played its sound over a black picture.

The column now names both, so "why is only one file as-is?" is answered on the
row instead of in a build log after the fact.
"""
import pytest

from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.gui.main_window import MainWindow


def _slot(ext=".mov", w=1360, h=768, fps=30.0, codec="h264",
          pix_fmt="yuv420p"):
    info = VideoInfo(path="slot" + ext, vcodec=codec, width=w, height=h,
                     fps=fps, duration=25.0, pix_fmt=pix_fmt,
                     container=ext.lstrip("."))
    return VideoSlot(rel_path="video/AttractMode" + ext,
                     abs_path="/assets/video/AttractMode" + ext, ext=ext,
                     info=info, size=1024)


def _probe(monkeypatch, info):
    """Pin what ffprobe would say about the REPLACEMENT file."""
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda _p: info)


def _rep(codec="h264", w=1360, h=768, fps=30.0, pix_fmt="yuv420p"):
    return VideoInfo(path="rep.mov", vcodec=codec, width=w, height=h, fps=fps,
                     duration=25.0, pix_fmt=pix_fmt, container="mov")


def test_wrong_container_says_what_is_needed(monkeypatch):
    """His 27 .mp4-into-.mov rows.  Write refuses these, and the column used
    to go blank rather than saying so."""
    got = MainWindow._video_conv_mode(_slot(".mov"), "/x/promo.mp4",
                                      no_conversion=True, trim=False)
    assert got == "✗ needs .mov"


def test_right_container_but_undecodable_codec_is_flagged(monkeypatch):
    """The one that got through: a .mov the machine can't decode is copied on
    byte-for-byte and plays black."""
    _probe(monkeypatch, _rep(codec="prores"))
    got = MainWindow._video_conv_mode(_slot(".mov"), "/x/attract.mov",
                                      no_conversion=True, trim=False)
    assert got == "✗ wrong format"


@pytest.mark.parametrize("kwargs", [
    {"pix_fmt": "yuv422p10le"},          # 10-bit 4:2:2
    {"w": 1920, "h": 1080},              # wrong geometry
    {"fps": 60.0},                       # wrong frame rate
])
def test_other_undecodable_shapes_are_flagged(monkeypatch, kwargs):
    _probe(monkeypatch, _rep(**kwargs))
    assert MainWindow._video_conv_mode(
        _slot(".mov"), "/x/attract.mov",
        no_conversion=True, trim=False) == "✗ wrong format"


def test_a_real_drop_in_still_reads_as_as_is(monkeypatch):
    _probe(monkeypatch, _rep())
    assert MainWindow._video_conv_mode(
        _slot(".mov"), "/x/attract.mov",
        no_conversion=True, trim=False) == "As-is"


def test_no_ffprobe_does_not_invent_a_problem(monkeypatch):
    """A file we can't measure is not evidence of a bad file."""
    _probe(monkeypatch, None)
    assert MainWindow._video_conv_mode(
        _slot(".mov"), "/x/attract.mov",
        no_conversion=True, trim=False) == "As-is"


def test_playability_check_needs_the_slot_to_be_probed(monkeypatch):
    """An unprobed slot has no geometry to compare against, so geometry is not
    judged — but the codec rule still stands on its own."""
    slot = _slot(".mov")
    slot.info = None
    _probe(monkeypatch, _rep(w=640, h=480))
    assert MainWindow._video_playability_conflict(slot, "/x/a.mov") is None
    _probe(monkeypatch, _rep(codec="hevc"))
    assert "H.264" in MainWindow._video_playability_conflict(slot, "/x/a.mov")


# ---------------------------------------------------------------------------
# Audio tracks.  A census of 2251 clips across five Spike 2 titles: every one
# is H.264, and Led Zeppelin / Godzilla / Jaws / John Wick are entirely silent
# while Deadpool carries audio on 7 of its 99.  So the rule is "match THIS
# slot", never a blanket "Spike 2 videos have no sound".
# ---------------------------------------------------------------------------

def test_audio_on_a_silent_slot_is_flagged_but_still_plays(monkeypatch):
    """The picture is fine; the machine just also plays the soundtrack the
    file brought with it (monkeybug: "I forgot to drop the audio off")."""
    slot = _slot(".mov")                       # VideoInfo default: no audio
    rep = _rep()
    rep.has_audio = True
    _probe(monkeypatch, rep)
    assert MainWindow._video_conv_mode(
        slot, "/x/a.mov", no_conversion=True, trim=False) == "As-is ⚠ audio"
    why = MainWindow._video_extra_audio(slot, "/x/a.mov")
    assert "audio track" in why and "over the game's own sound" in why


def test_audio_is_fine_when_the_slot_itself_has_audio(monkeypatch):
    """Deadpool's shape — a slot that already carries sound."""
    slot = _slot(".mov")
    slot.info.has_audio = True
    rep = _rep()
    rep.has_audio = True
    _probe(monkeypatch, rep)
    assert MainWindow._video_extra_audio(slot, "/x/a.mov") is None
    assert MainWindow._video_conv_mode(
        slot, "/x/a.mov", no_conversion=True, trim=False) == "As-is"


def test_a_black_picture_outranks_the_audio_note(monkeypatch):
    """Both wrong = report the one that stops it working."""
    slot = _slot(".mov")
    rep = _rep(codec="prores")
    rep.has_audio = True
    _probe(monkeypatch, rep)
    assert MainWindow._video_conv_mode(
        slot, "/x/a.mov", no_conversion=True, trim=False) == "✗ wrong format"


# ---------------------------------------------------------------------------
# "What this slot needs" — the spec + ffmpeg recipe for users who encode
# their own clips rather than let the app convert.
# ---------------------------------------------------------------------------

def test_spec_reads_the_slot_not_a_hardcoded_rule():
    from pinball_decryptor.core.video import dropin_spec
    info = _slot(".mov").info
    info.profile, info.level = "Constrained Baseline", 30
    rows = dict(dropin_spec(info, ".mov"))
    assert rows["Video codec"] == "H264"
    assert rows["Frame size"] == "1360 x 768"
    assert "Constrained Baseline" in rows["Profile"]
    assert "level 3.0" in rows["Profile"]
    assert rows["Audio"] == "none"
    assert "QuickTime" in rows["Container"]


def test_ffmpeg_recipe_pins_only_what_must_match():
    from pinball_decryptor.core.video import dropin_ffmpeg_command
    info = _slot(".mov").info
    info.profile, info.level = "Constrained Baseline", 30
    cmd = dropin_ffmpeg_command(info, ".mov")
    assert "-c:v libx264" in cmd
    assert "-profile:v baseline" in cmd
    assert "-level 3.0" in cmd
    assert "-pix_fmt yuv420p" in cmd
    assert "scale=1360:768" in cmd
    assert "-r 30" in cmd
    assert "-an" in cmd                     # the slot's clip is silent
    # Deliberately absent so the user can tune them without a fight.
    for flag in ("-b:v", "-g", "-preset", "-crf"):
        assert flag not in cmd


def test_recipe_needs_a_probed_slot():
    from pinball_decryptor.core.video import (dropin_ffmpeg_command,
                                              dropin_spec)
    assert dropin_spec(None, ".mov") is None
    assert dropin_ffmpeg_command(None, ".mov") is None


# ---------------------------------------------------------------------------
# Conversion left ON.  aly encoded his replacement to the slot's codec, size
# and frame rate but wrote it as .mp4 for a QuickTime slot: only the wrapper is
# wrong, so it's repackaged (lossless), not re-encoded.
# ---------------------------------------------------------------------------

def _convert_probe(monkeypatch, info, ffmpeg="ffmpeg"):
    monkeypatch.setattr("pinball_decryptor.core.video_slots.detect_video_info",
                        lambda _p: info)
    monkeypatch.setattr("pinball_decryptor.core.video_slots.find_ffmpeg",
                        lambda: ffmpeg)


def test_wrong_container_alone_reads_as_repackage(monkeypatch):
    _convert_probe(monkeypatch, _rep())
    assert MainWindow._video_conv_mode(
        _slot(".mov"), "/x/newfrankic.mp4",
        no_conversion=False, trim=False) == "Repackage"


def test_a_real_mismatch_still_reads_as_re_encode(monkeypatch):
    _convert_probe(monkeypatch, _rep(w=1920, h=1080))
    assert MainWindow._video_conv_mode(
        _slot(".mov"), "/x/newfrankic.mp4",
        no_conversion=False, trim=False) == "Re-encode"
