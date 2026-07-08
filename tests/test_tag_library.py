"""Tests for core.tag_library — the per-card library that lets a fresh
re-extract of the same Stern card restore the user's renamed image-group names
(monkeybug's "group tags lost on re-extract")."""

import json
import os

import pytest

from pinball_decryptor.core import extract_source, tag_library


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Point the library at a throwaway file so tests never touch the real
    ~/.config/pinball_decryptor/group_tags.json."""
    lib = tmp_path / "settings" / "group_tags.json"
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(lib))
    return lib


def _extract_dir(tmp_path, card_name="turtles_pro-1_59_0.Release.8G.sdcard.raw",
                 sub="out"):
    """A fake extract folder carrying an .extract_source.json for *card_name*."""
    img = tmp_path / card_name
    img.write_bytes(b"\x00" * 32)
    out = tmp_path / sub
    out.mkdir()
    extract_source.write_extract_source(str(out), str(img))
    return str(out)


def test_seed_empty_without_extract_source(tmp_path):
    # A folder with no .extract_source.json opts out cleanly.
    plain = tmp_path / "plain"
    plain.mkdir()
    assert tag_library.seed_tags(str(plain), {"scn::a"}) == {}


def test_remember_then_seed_roundtrip(tmp_path):
    out = _extract_dir(tmp_path)
    tags = {"scn::sceneA": "Boss Intro", "rad::card/x": "Menu Font"}
    known = set(tags)
    tag_library.remember(out, tags, known)
    # A fresh extract of the SAME card gets the names back.
    fresh = _extract_dir(tmp_path, sub="out2")
    assert tag_library.seed_tags(fresh, known) == tags


def test_seed_filters_to_present_keys(tmp_path):
    out = _extract_dir(tmp_path)
    tag_library.remember(
        out, {"scn::a": "Alpha", "scn::b": "Beta"}, {"scn::a", "scn::b"})
    # Only groups that exist in the new extract are seeded.
    assert tag_library.seed_tags(out, {"scn::a"}) == {"scn::a": "Alpha"}


def test_remember_drops_cleared_tag(tmp_path):
    out = _extract_dir(tmp_path)
    known = {"scn::a", "scn::b"}
    tag_library.remember(out, {"scn::a": "Alpha", "scn::b": "Beta"}, known)
    # User blanks scn::b (it leaves the tags map); a save must not resurrect it.
    tag_library.remember(out, {"scn::a": "Alpha"}, known)
    assert tag_library.seed_tags(out, known) == {"scn::a": "Alpha"}


def test_different_card_does_not_bleed(tmp_path):
    v121 = _extract_dir(tmp_path,
                        "turtles_pro-1_21_0.Release.8G.sdcard.raw", "v121")
    v122 = _extract_dir(tmp_path,
                        "turtles_pro-1_22_0.Release.8G.sdcard.raw", "v122")
    tag_library.remember(v121, {"scn::a": "Old Name"}, {"scn::a"})
    # A different version (different card file name) shares no entry — that's
    # Mod Transfer's job, not the library's.
    assert tag_library.seed_tags(v122, {"scn::a"}) == {}


def test_remember_no_extract_source_is_noop(tmp_path, _isolated_library):
    plain = tmp_path / "plain"
    plain.mkdir()
    tag_library.remember(plain, {"scn::a": "X"}, {"scn::a"})
    assert not os.path.exists(_isolated_library)  # nothing written


def test_names_capped_at_50(tmp_path):
    out = _extract_dir(tmp_path)
    long = "z" * 80
    tag_library.remember(out, {"scn::a": long}, {"scn::a"})
    assert tag_library.seed_tags(out, {"scn::a"}) == {"scn::a": "z" * 50}


def test_load_corrupt_library_is_empty(_isolated_library):
    os.makedirs(os.path.dirname(_isolated_library), exist_ok=True)
    with open(_isolated_library, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert tag_library.load() == {}


def test_load_drops_empty_and_blank(tmp_path, _isolated_library):
    os.makedirs(os.path.dirname(_isolated_library), exist_ok=True)
    with open(_isolated_library, "w", encoding="utf-8") as f:
        json.dump({"card.raw": {"scn::a": "  ", "scn::b": "Real"},
                   "empty.raw": {}}, f)
    assert tag_library.load() == {"card.raw": {"scn::b": "Real"}}


def test_remember_empty_removes_entry(tmp_path, _isolated_library):
    out = _extract_dir(tmp_path)
    tag_library.remember(out, {"scn::a": "Alpha"}, {"scn::a"})
    tag_library.remember(out, {}, {"scn::a"})  # user cleared everything
    assert tag_library.load() == {}


def test_remember_skips_noop_write(tmp_path, _isolated_library):
    out = _extract_dir(tmp_path)
    tag_library.remember(out, {"scn::a": "Alpha"}, {"scn::a"})
    mtime = os.stat(_isolated_library).st_mtime_ns
    # Identical state again -> file must not be rewritten.
    tag_library.remember(out, {"scn::a": "Alpha"}, {"scn::a"})
    assert os.stat(_isolated_library).st_mtime_ns == mtime
