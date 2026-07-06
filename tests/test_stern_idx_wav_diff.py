"""Regression test for Stern Write's idx-wav change detection.

Re-extracting into a folder that still holds the prior run's Auto-transcribe/
Music-ID *renamed* copies leaves two files for one sound — e.g. ``idx0001.wav``
and ``idx0001 - music.wav`` (same leading index, identical content).  Both map
to ONE on-card sound at Write.  The old code keyed a dict by idx in os.walk
order, so an edit to the twin that wasn't walked last was silently dropped.
``_select_changed_idx_wavs`` must instead pick whichever twin the user edited.
"""

import hashlib
import os

from pinball_decryptor.plugins.stern.engine import (
    _fmt_idx_list, _remove_renamed_audio_twins, _select_changed_idx_wavs,
    _wav_basename, _wav_idx)


def _wav(path, data):
    with open(path, "wb") as f:
        f.write(data)


def _baseline(*pairs):
    """Build a {rel_path: md5} baseline like read_checksums returns."""
    return {rel: hashlib.md5(data).hexdigest() for rel, data in pairs}


def test_unchanged_twins_are_skipped(tmp_path):
    orig = b"RIFF....original sound...."
    _wav(tmp_path / "idx0001.wav", orig)
    _wav(tmp_path / "idx0001 - music.wav", orig)
    base = _baseline(("idx0001.wav", orig), ("idx0001 - music.wav", orig))
    assert _select_changed_idx_wavs(str(tmp_path), base) == {}


def test_edit_to_bare_twin_is_detected(tmp_path):
    orig = b"RIFF....original sound...."
    edit = b"RIFF....the user's replacement...."
    _wav(tmp_path / "idx0001.wav", edit)             # user replaced the bare one
    _wav(tmp_path / "idx0001 - music.wav", orig)     # stale named twin
    base = _baseline(("idx0001.wav", orig), ("idx0001 - music.wav", orig))
    edits = _select_changed_idx_wavs(str(tmp_path), base)
    assert set(edits) == {1}
    assert os.path.basename(edits[1]) == "idx0001.wav"


def test_edit_to_named_twin_is_detected(tmp_path):
    # The crux: os.walk visits "idx0001 - music.wav" *before* "idx0001.wav"
    # (alphabetical: space < '.'), so the old last-wins dict kept the bare
    # unedited file and dropped this edit.
    orig = b"RIFF....original sound...."
    edit = b"RIFF....the user's replacement...."
    _wav(tmp_path / "idx0001.wav", orig)             # stale bare twin
    _wav(tmp_path / "idx0001 - music.wav", edit)     # user replaced the named one
    base = _baseline(("idx0001.wav", orig), ("idx0001 - music.wav", orig))
    edits = _select_changed_idx_wavs(str(tmp_path), base)
    assert set(edits) == {1}
    assert os.path.basename(edits[1]) == "idx0001 - music.wav"


def test_single_file_unchanged_and_changed(tmp_path):
    orig = b"sound-five"
    _wav(tmp_path / "idx0005.wav", orig)
    base = _baseline(("idx0005.wav", orig))
    assert _select_changed_idx_wavs(str(tmp_path), base) == {}
    _wav(tmp_path / "idx0005.wav", b"sound-five-EDITED")
    assert set(_select_changed_idx_wavs(str(tmp_path), base)) == {5}


def test_distinct_indices_are_independent(tmp_path):
    # Two *different* idx with identical content are NOT twins — each is its own
    # on-card sound, so editing one must not implicate the other.
    a, b = b"aaaa", b"bbbb"
    _wav(tmp_path / "idx0001.wav", a)
    _wav(tmp_path / "idx0002.wav", b)
    base = _baseline(("idx0001.wav", a), ("idx0002.wav", b))
    _wav(tmp_path / "idx0002.wav", b"bbbb-EDITED")
    edits = _select_changed_idx_wavs(str(tmp_path), base)
    assert set(edits) == {2}


def test_no_baseline_treats_everything_as_edit(tmp_path):
    _wav(tmp_path / "idx0001.wav", b"x")
    _wav(tmp_path / "idx0007.wav", b"y")
    edits = _select_changed_idx_wavs(str(tmp_path), {})
    assert set(edits) == {1, 7}


def test_music_cat_files_are_ignored(tmp_path):
    # music_catNN_* live in separate banks (handled by _changed_music_banks);
    # they must not be picked up as idx edits.
    _wav(tmp_path / "music_cat01_0001.wav", b"song")
    assert _select_changed_idx_wavs(str(tmp_path), {}) == {}


# --- _remove_renamed_audio_twins (root-cause cleanup on re-extract) --------

def test_cleanup_removes_renamed_idx_twins_keeps_bare(tmp_path):
    _wav(tmp_path / "idx0001.wav", b"a")               # bare — kept (overwritten)
    _wav(tmp_path / "idx0001 - music.wav", b"a")        # renamed twin — removed
    _wav(tmp_path / "idx0010 - The Song Remains.wav", b"b")  # removed
    _remove_renamed_audio_twins(str(tmp_path))
    names = set(os.listdir(tmp_path))
    assert names == {"idx0001.wav"}


def test_cleanup_removes_renamed_music_cat_twins(tmp_path):
    _wav(tmp_path / "music_cat01_0001.wav", b"x")              # kept
    _wav(tmp_path / "music_cat01_0001 - Battery.wav", b"x")    # removed
    _remove_renamed_audio_twins(str(tmp_path))
    assert set(os.listdir(tmp_path)) == {"music_cat01_0001.wav"}


def test_cleanup_leaves_unrelated_files_alone(tmp_path):
    # Bare files, non-idx names, and files without the " - " annotation survive.
    keep = ["idx0002.wav", "video_0001.mp4", "notes.txt",
            "my callout - keep.wav"]  # no idx/music_cat prefix → not a twin
    for n in keep:
        _wav(tmp_path / n, b"k")
    _wav(tmp_path / "idx0002 - hello.wav", b"k")  # the only twin
    _remove_renamed_audio_twins(str(tmp_path))
    assert set(os.listdir(tmp_path)) == set(keep)


def test_cleanup_is_noop_on_empty_or_missing(tmp_path):
    _remove_renamed_audio_twins(str(tmp_path / "does_not_exist"))  # no raise
    _remove_renamed_audio_twins(str(tmp_path))                     # empty dir
    assert os.listdir(tmp_path) == []


# --- Length-prefix names (monkeybug: sort extracts by play length) ---------

def test_wav_basename_formats():
    # Header length carries a 200-sample cursor lead-in the codec never
    # emits; the prefix must reflect the TRUE 1m22.235s play length the
    # decoded WAV actually has (monkeybug: names read ~4.5 ms long).
    p = {"idx": 1, "length": 82 * 44100 + int(0.235 * 44100) + 200}
    assert _wav_basename(p, False) == "idx0001.wav"
    assert _wav_basename(p, True) == "01m22s235 - idx0001.wav"


def test_wav_idx_parses_every_shape():
    # bare decode output, renamed, length-prefixed, and both combined
    assert _wav_idx("idx0001") == 1
    assert _wav_idx("idx0001 - Kashmir") == 1
    assert _wav_idx("01m22s235 - idx0001") == 1
    assert _wav_idx("01m22s235 - idx0001 - Kashmir") == 1
    assert _wav_idx("0007") == 7                 # hand-named all-digits stem
    # The length prefix's own digits must NEVER be read as the index, and
    # non-slot names must not match at all.
    assert _wav_idx("01m22s235 - somebody's song") is None
    assert _wav_idx("my callout - keep") is None
    assert _wav_idx("music_cat01_0001") is None
    assert _wav_idx("20 seconds of fame") is None


def test_select_changed_handles_length_prefixed_names(tmp_path):
    orig = b"RIFF....original sound...."
    edit = b"RIFF....the user's replacement...."
    name = "01m22s235 - idx0003.wav"
    _wav(tmp_path / name, edit)
    base = _baseline((name, orig))
    edits = _select_changed_idx_wavs(str(tmp_path), base)
    assert set(edits) == {3}
    assert os.path.basename(edits[3]) == name


def test_cleanup_swaps_naming_styles(tmp_path):
    # Re-extract with Length-prefix ON removes the old bare style (the fresh
    # decode writes prefixed names, so the bare ones would linger as twins)…
    _wav(tmp_path / "idx0001.wav", b"a")
    _wav(tmp_path / "01m22s235 - idx0001.wav", b"a")
    _remove_renamed_audio_twins(str(tmp_path), duration_names=True)
    assert set(os.listdir(tmp_path)) == {"01m22s235 - idx0001.wav"}
    # …and OFF removes the prefixed style, keeping the bare one.
    _wav(tmp_path / "idx0001.wav", b"a")
    _remove_renamed_audio_twins(str(tmp_path), duration_names=False)
    assert set(os.listdir(tmp_path)) == {"idx0001.wav"}


def test_cleanup_removes_prefixed_renamed_twins(tmp_path):
    _wav(tmp_path / "01m22s235 - idx0001.wav", b"a")             # kept (bare)
    _wav(tmp_path / "01m22s235 - idx0001 - Kashmir.wav", b"a")   # renamed twin
    _remove_renamed_audio_twins(str(tmp_path), duration_names=True)
    assert set(os.listdir(tmp_path)) == {"01m22s235 - idx0001.wav"}


# --- _fmt_idx_list: the Write log spells out which sounds it will re-encode --

def test_fmt_idx_list_sorts_and_zero_pads():
    # The "Found N edited sound(s) to write" log enumerates the idx so a count
    # larger than just-staged (e.g. an earlier session's edit still on disk)
    # is self-explaining rather than an unexplained +N.
    assert _fmt_idx_list({41, 6, 472}) == "idx0006, idx0041, idx0472"


def test_fmt_idx_list_accepts_a_dict_keyed_by_idx():
    # _select_changed_idx_wavs returns {idx: path}; the log passes it straight in.
    assert _fmt_idx_list({6: "a", 41: "b"}) == "idx0006, idx0041"


def test_fmt_idx_list_truncates_huge_sets():
    out = _fmt_idx_list(range(200), cap=3)
    assert out == "idx0000, idx0001, idx0002, … and 197 more"
