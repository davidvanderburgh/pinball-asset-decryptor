"""core.audio_compare — the sound-by-sound diff between two extract folders.

A tester ran the Compare tab's own "Extract Both", pressed Compare, and got
back the same "extract both cards to compare them one by one" sentence he had
just acted on: the report never looked at the extracts.  These tests pin the
comparison that sentence promised, and the two decisions that make it useful
rather than noise —

* slots pair up by the ``idxNNNN`` token, so two folders extracted with
  different naming options still line up;
* bytes are matched BEFORE slots, so a build that inserts one sound and
  renumbers everything after it reports one addition, not two thousand
  changes;
* and the codec's LEAD-IN FRAME is not part of the sound (PAD-86) — it is
  read out of whatever ``image.bin`` packs in front of the body, so a build
  that repacks changes it on every sound at once.
"""

import hashlib
import os

import pytest

from pinball_decryptor.core import audio_compare
from pinball_decryptor.core.checksums import CHECKSUMS_FILE


def _extract(root, wavs, baseline=True):
    """An extract folder holding ``{name: content}`` under ``audio/``, with
    the ``.checksums.md5`` every real Extract leaves behind."""
    os.makedirs(os.path.join(root, "audio"), exist_ok=True)
    lines = []
    for name, data in wavs.items():
        with open(os.path.join(root, "audio", name), "wb") as f:
            f.write(data)
        lines.append("audio/%s\t%s" % (name, hashlib.md5(data).hexdigest()))
    if baseline:
        with open(os.path.join(root, CHECKSUMS_FILE), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return str(root)


def _names(pairs):
    return [(a.split("/")[-1], b.split("/")[-1]) for a, b in pairs]


def test_identical_extracts_are_all_same(tmp_path):
    wavs = {"idx0001.wav": b"one", "idx0002.wav": b"two"}
    a = _extract(tmp_path / "a", wavs)
    b = _extract(tmp_path / "b", wavs)
    d = audio_compare.diff_audio(a, b)
    assert (d["count_a"], d["count_b"], d["same"]) == (2, 2, 2)
    assert not (d["changed"] or d["moved"] or d["added"] or d["removed"])


def test_a_replaced_sound_is_the_only_change(tmp_path):
    """The modded-card-against-its-stock-base case: same slots, one new
    sound in one of them."""
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one", "idx0002.wav": b"two",
                                  "idx0003.wav": b"three"})
    b = _extract(tmp_path / "b", {"idx0001.wav": b"one",
                                  "idx0002.wav": b"MY MOD",
                                  "idx0003.wav": b"three"})
    d = audio_compare.diff_audio(a, b)
    assert d["same"] == 2
    assert _names(d["changed"]) == [("idx0002.wav", "idx0002.wav")]
    assert not (d["moved"] or d["added"] or d["removed"])


def test_an_inserted_sound_renumbers_without_flooding_the_report(tmp_path):
    """THE REASON CONTENT IS MATCHED FIRST.  A new build inserting one sound
    shifts every index after it; pairing on the index alone would call all of
    them changed and bury the one that really is new."""
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one", "idx0002.wav": b"two",
                                  "idx0003.wav": b"three"})
    b = _extract(tmp_path / "b", {"idx0001.wav": b"one", "idx0002.wav": b"NEW",
                                  "idx0003.wav": b"two",
                                  "idx0004.wav": b"three"})
    d = audio_compare.diff_audio(a, b)
    assert d["same"] == 1                                  # idx0001
    assert _names(d["moved"]) == [("idx0002.wav", "idx0003.wav"),
                                  ("idx0003.wav", "idx0004.wav")]
    assert [r.split("/")[-1] for r in d["added"]] == ["idx0002.wav"]
    assert not (d["changed"] or d["removed"])


def test_a_removed_sound_lists_on_its_own_side(tmp_path):
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one", "idx0002.wav": b"two"})
    b = _extract(tmp_path / "b", {"idx0001.wav": b"one"})
    d = audio_compare.diff_audio(a, b)
    assert [r.split("/")[-1] for r in d["removed"]] == ["idx0002.wav"]
    assert not (d["changed"] or d["moved"] or d["added"])


def test_naming_options_do_not_read_as_changes(tmp_path):
    """One folder extracted with length-prefix names, the other auto-named:
    the idx token is what both keep, so nothing reads as changed."""
    a = _extract(tmp_path / "a", {"01m22s235 - idx0001.wav": b"one",
                                  "idx0002.wav": b"two"})
    b = _extract(tmp_path / "b", {"idx0001 - Kashmir.wav": b"one",
                                  "idx0002 - Rain Song.wav": b"two"})
    d = audio_compare.diff_audio(a, b)
    assert d["same"] == 2
    assert not (d["changed"] or d["moved"] or d["added"] or d["removed"])


def test_music_banks_key_on_their_own_token(tmp_path):
    a = _extract(tmp_path / "a", {"music_cat09_0001.wav": b"song"})
    b = _extract(tmp_path / "b", {"music_cat09_0001 - Immigrant Song.wav":
                                  b"song"})
    assert audio_compare.diff_audio(a, b)["same"] == 1


def test_a_missing_baseline_falls_back_to_hashing(tmp_path):
    """An extract whose .checksums.md5 never landed still compares — the
    fallback hashes into the same md5 space, so the two sources mix."""
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one"}, baseline=False)
    b = _extract(tmp_path / "b", {"idx0001.wav": b"one"})
    assert audio_compare.diff_audio(a, b)["same"] == 1


def test_a_renamed_file_missing_from_the_baseline_is_still_hashed(tmp_path):
    """Auto-transcribe renames a WAV after the baseline was written.  The
    file is not in it under its new name, so it gets hashed rather than
    silently dropping out of the count."""
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one"})
    os.rename(os.path.join(a, "audio", "idx0001.wav"),
              os.path.join(a, "audio", "idx0001 - Kashmir.wav"))
    b = _extract(tmp_path / "b", {"idx0001.wav": b"one"})
    d = audio_compare.diff_audio(a, b)
    assert (d["count_a"], d["same"]) == (1, 1)


def test_an_extract_without_audio_counts_zero(tmp_path):
    """A video/images-only Extract has no audio folder at all — the caller
    needs a count of 0, not a crash."""
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one"})
    (tmp_path / "b").mkdir()
    d = audio_compare.diff_audio(a, str(tmp_path / "b"))
    assert (d["count_a"], d["count_b"]) == (1, 0)
    assert [r.split("/")[-1] for r in d["removed"]] == ["idx0001.wav"]


def test_dot_files_are_not_sounds(tmp_path):
    a = _extract(tmp_path / "a", {"idx0001.wav": b"one"})
    with open(os.path.join(a, "audio", ".hidden.wav"), "wb") as f:
        f.write(b"x")
    assert audio_compare.diff_audio(a, a)["count_a"] == 1


# ---------------------------------------------------------------------------
# The codec's lead-in frame (PAD-86)
# ---------------------------------------------------------------------------

def _wav(samples, chan=1):
    """A canonical decoded WAV — the 44-byte header the extractor writes,
    over 16-bit *samples* (a flat list of ints)."""
    import struct
    body = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, chan, 44100,
                                    44100 * 2 * chan, 2 * chan, 16)
            + b"data" + struct.pack("<I", len(body)) + body)


def test_a_repacked_build_is_not_a_rewritten_one(tmp_path):
    """THE PAD-86 CASE.  A Spike 2 sound decodes its first frame out of the
    word below its body, i.e. out of whatever image.bin packs in front of it,
    so a build that repacks changes that one sample on every sound and
    nothing else.  Measured on Jaws LE 1.01 vs 1.02: all 1,733 sounds differ
    in exactly their first 2 (mono) or 4 (stereo) bytes.  Counting that read
    the whole catalog as changed — a tester saw 3,968 of them.
    """
    body = list(range(1, 400))
    a = _extract(tmp_path / "a", {"idx0001.wav": _wav([111] + body),
                                  "idx0002.wav": _wav([111, 111] + body,
                                                      chan=2)})
    b = _extract(tmp_path / "b", {"idx0001.wav": _wav([-9] + body),
                                  "idx0002.wav": _wav([-9, 7] + body,
                                                      chan=2)})
    d = audio_compare.diff_audio(a, b)
    assert (d["same"], d["lead_in"]) == (2, 2)
    assert not (d["changed"] or d["moved"] or d["added"] or d["removed"])


def test_a_repack_that_also_renumbers_still_reads_as_moved(tmp_path):
    """Both at once, which is what Stern actually ships (Jaws 1.01 -> 1.02
    renumbered the whole directory AND repacked it)."""
    one, two = list(range(1, 300)), list(range(500, 800))
    a = _extract(tmp_path / "a", {"idx0001.wav": _wav([111] + one),
                                  "idx0002.wav": _wav([111] + two)})
    b = _extract(tmp_path / "b", {"idx0007.wav": _wav([-3] + two),
                                  "idx0009.wav": _wav([-3] + one)})
    d = audio_compare.diff_audio(a, b)
    assert d["lead_in"] == 2 and d["same"] == 0
    assert _names(d["moved"]) == [("idx0001.wav", "idx0009.wav"),
                                  ("idx0002.wav", "idx0007.wav")]
    assert not (d["changed"] or d["added"] or d["removed"])


def test_only_the_lead_in_is_forgiven(tmp_path):
    """One sample past it and the sounds are different sounds.  A tolerance
    that grew would quietly turn real changes into "unchanged"."""
    body = list(range(1, 300))
    a = _extract(tmp_path / "a", {"idx0001.wav": _wav([111] + body)})
    b = _extract(tmp_path / "b",
                 {"idx0001.wav": _wav([-9, 12345] + body[1:])})
    d = audio_compare.diff_audio(a, b)
    assert d["same"] == 0 and d["lead_in"] == 0
    assert _names(d["changed"]) == [("idx0001.wav", "idx0001.wav")]


def test_the_second_pass_reads_nothing_when_the_first_placed_everything(
        tmp_path, monkeypatch):
    """The fast path stays free: two folders that match on their baselines
    never open a WAV, however many thousand sounds they hold."""
    wavs = {"idx0001.wav": _wav([1, 2, 3]), "idx0002.wav": _wav([4, 5, 6])}
    a = _extract(tmp_path / "a", wavs)
    b = _extract(tmp_path / "b", wavs)
    monkeypatch.setattr(audio_compare, "sound_digest",
                        lambda p: pytest.fail("hashed %s for nothing" % p))
    assert audio_compare.diff_audio(a, b)["same"] == 2


def test_a_file_that_is_not_a_walkable_wav_is_hashed_whole(tmp_path):
    """An identity that is merely stricter, never wrong."""
    p = tmp_path / "x.bin"
    p.write_bytes(b"not a RIFF at all")
    assert audio_compare.sound_digest(str(p)) == \
        hashlib.md5(b"not a RIFF at all").hexdigest()
