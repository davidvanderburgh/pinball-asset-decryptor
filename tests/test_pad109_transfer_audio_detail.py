"""Why an audio replacement could not be carried, not just that it wasn't.

A tester's run told him some of his sounds did not match and named nothing
else -- "there is no detail log or anything to see which ones actually failed
with details of size, index etc."  Worse, the answer was sitting in the two
folders: every one of his 11 uncarried sounds had a byte-identical-LENGTH twin
in the new version, each at an index inside the range PAD-108 was decoding to
noise, while all 9 that did carry sat below it.  A failure line now carries the
slot's stock byte length and the same-length slots the new version does have,
and a block of such failures ends in the read that matters.
"""
import os

from pinball_decryptor.core import mod_transfer, staged_changes


def _wav(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)


def _mk(root, sounds):
    for rel, data in sounds.items():
        _wav(os.path.join(root, rel.replace("/", os.sep)), data)


def _lines(plan):
    return "\n".join(t for _lvl, t in mod_transfer.plan_detail_lines(plan))


def test_dropped_sound_names_its_size_and_same_length_twin(tmp_path):
    # Same length to the byte, different content: the new version's copy
    # decoded to something else.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk(src, {"audio/idx0181.wav": b"REAL-MUSIC" * 100})
    _mk(tgt, {"audio/idx0797.wav": b"NOISE-JUNK" * 100,
              "audio/idx0002.wav": b"other" * 10})
    staged_changes.save(src, {"audio": {"audio/idx0181.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["dropped"]) == 1
    e = plan["audio"]["dropped"][0]
    assert e["size"] == 1000
    assert e["near"] == ["audio/idx0797.wav"]

    text = _lines(plan)
    assert "audio/idx0181.wav" in text
    assert "1,000 bytes" in text
    assert "idx0797.wav" in text
    assert "the audio differs" in text


def test_a_sound_the_new_version_simply_lacks_says_so(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk(src, {"audio/idx0001.wav": b"GONE" * 100})
    _mk(tgt, {"audio/idx0001.wav": b"a-different-length-sound" * 30})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    e = (plan["audio"]["dropped"] + plan["audio"]["flagged"])[0]
    assert e["size"] == 400 and e["near"] == []

    text = _lines(plan)
    assert "400 bytes" in text
    assert "nothing of that length in the new version" in text
    # ...and no re-extract advice, because nothing lined up by length.
    assert "re-extract both folders" not in text


def test_a_block_of_same_length_failures_reads_as_a_bad_extract(tmp_path):
    # The tester's shape: every uncarried sound has a same-length twin.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    src_sounds = {"audio/idx%04d.wav" % i: b"GOOD%02d" % i * 100
                  for i in range(5)}
    tgt_sounds = {"audio/idx%04d.wav" % (500 + i): b"NOIS%02d" % i * 100
                  for i in range(5)}
    _mk(src, src_sounds)
    _mk(tgt, tgt_sounds)
    staged_changes.save(src, {"audio": {r: r"C:\r\x.mp3" for r in src_sounds}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["dropped"]) == 5

    text = _lines(plan)
    assert "5 of those sound(s) DO exist in the new version at exactly the "\
           "same length" in text
    assert "re-extract both folders" in text


def test_a_reused_index_still_reports_its_length(tmp_path):
    # Flagged, not dropped: the index survives but now holds other audio.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk(src, {"audio/idx0007.wav": b"OLD-TAKE" * 50})
    _mk(tgt, {"audio/idx0007.wav": b"NEW-TAKE" * 50})
    staged_changes.save(src, {"audio": {"audio/idx0007.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["flagged"]) == 1
    assert plan["audio"]["flagged"][0]["near"] == ["audio/idx0007.wav"]
    text = _lines(plan)
    assert "400 bytes" in text
    assert "same length as idx0007.wav" in text


def test_many_same_length_twins_are_summarised(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk(src, {"audio/idx0001.wav": b"AAAA" * 100})
    _mk(tgt, {"audio/idx%04d.wav" % (100 + i): bytes([66 + i]) * 400
              for i in range(6)})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    text = _lines(mod_transfer.plan_transfer(src, tgt))
    assert "and 3 more" in text          # 6 twins, 3 named
