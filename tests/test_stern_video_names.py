"""Tests for the Stern Spike 2 scene-element names given to extracted videos.

A ``scene.radium`` video record is
``<u64 len><name><u32 id><u64 len><N.asset/M.asset>``.  Naming a video by the
nearest identifier *text* used to append a stray character, because the id is
``0x800000nn`` and its low byte is usually printable ASCII -- so a run of clips
picked up ``a, b, c ...`` as the id counted up.  These pin the framed parse and
the identifier-scan fallback.
"""

import os
import struct

from pinball_decryptor.plugins.stern import engine


def _record(name, ref, ident):
    """One radium video record with the id byte *ident* (the stray-char source)."""
    return (struct.pack("<Q", len(name)) + name.encode("latin1")
            + struct.pack("<I", 0x80000000 | ident)
            + struct.pack("<Q", len(ref)) + ref.encode("latin1"))


def test_name_drops_the_ascii_id_byte():
    # id low byte 0x69 == "i": the old scan produced "..._Award1i".
    data = b"\x00" * 16 + _record("GodzillaVsMegalon_Award1", "2.asset/103.asset", 0x69)
    assert engine._parse_radium(data) == {
        "2.asset/103.asset": "GodzillaVsMegalon_Award1"}


def test_consecutive_records_do_not_pick_up_the_counter():
    """The bug's signature: names ending in a rising letter across clips."""
    data = b"\x00" * 16
    for i, ref in enumerate(("2.asset/353.asset", "2.asset/354.asset",
                             "2.asset/355.asset")):
        data += _record("gigan_ghidorah_vs_godzilla%d" % (10 + i), ref, 0x63 + i)
    assert engine._parse_radium(data) == {
        "2.asset/353.asset": "gigan_ghidorah_vs_godzilla10",
        "2.asset/354.asset": "gigan_ghidorah_vs_godzilla11",
        "2.asset/355.asset": "gigan_ghidorah_vs_godzilla12",
    }


def test_name_keeps_characters_the_identifier_regex_cannot_match():
    """``Credits_ASTRO-MONSTER`` used to be truncated to ``MONSTER``."""
    data = b"\x00" * 16 + _record("Credits_ASTRO-MONSTER", "2.asset/40.asset", 0x2f)
    assert engine._parse_radium(data) == {"2.asset/40.asset": "Credits_ASTRO-MONSTER"}


def test_trailing_underscore_id_byte_is_not_kept():
    # 0x5f == "_", which the identifier regex also swallows.
    data = b"\x00" * 16 + _record("ghidorah_victory", "2.asset/12.asset", 0x5f)
    assert engine._parse_radium(data) == {"2.asset/12.asset": "ghidorah_victory"}


def test_non_ascii_id_byte_was_already_fine_and_still_is():
    data = b"\x00" * 16 + _record("megalon_drill", "2.asset/462.asset", 0x02)
    assert engine._parse_radium(data) == {"2.asset/462.asset": "megalon_drill"}


def test_unframed_reference_falls_back_to_the_identifier_scan():
    """A ref with no length-prefixed name in front still gets named."""
    data = b"\x00" * 8 + b"Some_Element_Name" + b"\xff" * 6 + b"2.asset/9.asset"
    assert engine._parse_radium(data) == {"2.asset/9.asset": "Some_Element_Name"}


def test_first_name_wins_for_a_repeated_reference():
    data = (b"\x00" * 16
            + _record("First_Clip", "2.asset/1.asset", 0x41)
            + _record("Second_Clip", "2.asset/1.asset", 0x42))
    assert engine._parse_radium(data) == {"2.asset/1.asset": "First_Clip"}


def test_skip_words_are_not_used_as_names():
    """A wrapper element named ``Video`` must not become the clip's name."""
    data = b"\x00" * 16 + _record("Video", "2.asset/7.asset", 0x41)
    assert engine._parse_radium(data).get("2.asset/7.asset") != "Video"


def test_radium_name_before_reports_none_when_unframed():
    assert engine._radium_name_before(b"\x11" * 64, 40) is None


# ---- stale twins left behind when a clip's name changes --------------------

def _touch(d, *names):
    for n in names:
        with open(os.path.join(d, n), "w", encoding="utf-8") as f:
            f.write(n)


def test_renamed_clip_does_not_leave_its_old_copy_behind(tmp_path):
    d = str(tmp_path)
    _touch(d, "clip10c.mp4", "clip10.mp4", "unchanged.mp4")
    removed = engine._remove_renamed_video_twins(
        d,
        {"clip10c.mp4": "/g/2.asset/1.asset", "unchanged.mp4": "/g/2.asset/2.asset"},
        {"/g/2.asset/1.asset": "clip10.mp4", "/g/2.asset/2.asset": "unchanged.mp4"})
    assert removed == 1
    assert sorted(os.listdir(d)) == ["clip10.mp4", "unchanged.mp4"]


def test_files_the_user_added_are_never_removed(tmp_path):
    """Only names the old manifest recorded are candidates."""
    d = str(tmp_path)
    _touch(d, "my_own_clip.mp4", "clip10.mp4")
    engine._remove_renamed_video_twins(
        d, {}, {"/g/2.asset/1.asset": "clip10.mp4"})
    assert sorted(os.listdir(d)) == ["clip10.mp4", "my_own_clip.mp4"]


def test_clip_not_rewritten_this_run_is_left_alone(tmp_path):
    """A cancelled run must not delete clips it never got to re-extract."""
    d = str(tmp_path)
    _touch(d, "clip10c.mp4")
    engine._remove_renamed_video_twins(
        d, {"clip10c.mp4": "/g/2.asset/1.asset"}, {})
    assert os.listdir(d) == ["clip10c.mp4"]


def test_read_video_manifest_round_trips(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n"
                "a.mp4\t/g/2.asset/1.asset\t10\n"
                "b.mov\t/g/2.asset/2.asset\t20\n")
    assert engine._read_video_manifest(d) == {
        "a.mp4": "/g/2.asset/1.asset", "b.mov": "/g/2.asset/2.asset"}


def test_read_video_manifest_missing_file_is_empty(tmp_path):
    assert engine._read_video_manifest(str(tmp_path)) == {}


# ---- PAD-633: a clip no scene names keeps its name whatever a build adds ----

from tests._ext4_fake import FakeExt4Reader  # noqa: E402

_GZ = "/godzilla_le/assets/lcd/auto_loaded/"
_LONE = "eae3e0844950ec5f071bf3c4e951fbff709a2028"


def _clip(tag):
    """Enough of an MP4 for find_card_videos' ftyp sniff (>= 0x1000 bytes)."""
    return b"\x00\x00\x00\x18ftypisom" + tag.encode() + b"\x00" * 0x1000


def _card(added=0):
    """Godzilla LE's shape: named clips in one scene, the one clip its scene
    does not name in another, and *added* named clips a build put in a scene
    the walk reaches first."""
    named = b"\x00" * 16 + b"".join(
        _record("clip%d" % i, "%d.asset" % i, 0x02) for i in range(3))
    tree = {}
    if added:
        tree["00bank"] = {
            "scene.radium": b"\x00" * 16 + b"".join(
                _record("PAD_Mode%d" % i, "%d.asset" % i, 0x02) for i in range(added)),
            "scene.assets": {"%d.asset" % i: _clip("m%d" % i) for i in range(added)}}
    tree["11named"] = {"scene.radium": named,
                       "scene.assets": {"%d.asset" % i: _clip("n%d" % i)
                                        for i in range(3)}}
    tree[_LONE] = {"scene.radium": b"\x00" * 64,
                   "scene.assets": {"34.asset": _clip("lone")}}
    return FakeExt4Reader({"godzilla_le": {"assets": {"lcd": {"auto_loaded": tree}}}})


def _manifest(out):
    return engine._read_video_manifest(os.path.join(out, "video"))


def test_unnamed_clip_is_named_from_its_card_path():
    assert engine._unnamed_clip_base(_GZ + _LONE + "/scene.assets/34.asset") \
        == "video_eae3e084_34"
    assert engine._unnamed_clip_base(_GZ + "60ed7e50abc/scene.assets/2.asset/584.asset") \
        == "video_60ed7e50_2_584"
    other = engine._unnamed_clip_base("/videos/attract.mp4")
    assert other.startswith("video_attract_") and other == \
        engine._unnamed_clip_base("/videos/attract.mp4")


def test_unnamed_clip_name_does_not_move_when_a_build_adds_clips(tmp_path):
    """The report: video_0655 on the stock card came out as video_0721 off
    the card a Write made, because the number was its place in the walk."""
    names = {}
    for added in (0, 66):
        out = str(tmp_path / ("x%d" % added))
        engine.extract_videos(_card(added), out)
        names[added] = {c: n for n, c in _manifest(out).items()}
    path = _GZ + _LONE + "/scene.assets/34.asset"
    assert names[0][path] == names[66][path] == "video_eae3e084_34.mp4"
    assert len(names[66]) == len(names[0]) + 66


def test_a_project_keeps_the_name_it_already_has(tmp_path):
    """A folder extracted before the fix keeps video_0655: its edits, sidecars
    and records are filed under that name."""
    out = str(tmp_path)
    vid = os.path.join(out, "video")
    os.makedirs(vid)
    path = _GZ + _LONE + "/scene.assets/34.asset"
    with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\nvideo_0655.mp4\t%s\t4120\n" % path)
    _touch(vid, "video_0655.mp4")
    engine.extract_videos(_card(66), out)
    assert _manifest(out)["video_0655.mp4"] == path
    assert os.path.isfile(os.path.join(vid, "video_0655.mp4"))
    assert not any(n.startswith("video_eae3") for n in os.listdir(vid))


def test_a_kept_name_is_never_given_to_another_clip():
    vids = [("/a/scene.assets/1.asset", None, b"isom"),
            ("/b/scene.assets/2.asset", None, b"isom")]
    got = engine._video_names(vids, lambda p: None,
                              {"/b/scene.assets/2.asset": "video_a_1.mp4"})
    assert [n for n, _t in got] == ["video_a_1_2.mp4", "video_a_1.mp4"]


def test_a_named_clip_ignores_an_old_number():
    vids = [("/a/scene.assets/1.asset", None, b"isom")]
    got = engine._video_names(vids, lambda p: "Cowabunga",
                              {"/a/scene.assets/1.asset": "video_0001.mp4"})
    assert got == [("Cowabunga.mp4", True)]


def test_card_scan_names_the_clip_like_the_extract(tmp_path):
    clips = engine.scan_video_quality(_card(66))
    assert "video_eae3e084_34.mp4" in [c.name for c in clips]
