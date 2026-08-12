"""Tests for the Stern Spike 2 scene-element names given to extracted videos.

A ``scene.radium`` video record is
``<u64 len><name><u32 id><u64 len><N.asset/M.asset>``.  Naming a video by the
nearest identifier *text* used to append a stray character, because the id is
``0x800000nn`` and its low byte is usually printable ASCII -- so a run of clips
picked up ``a, b, c ...`` as the id counted up.  These pin the framed parse and
the identifier-scan fallback.
"""

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
