"""Tests for the Stern Spike 2 Replace-Video write path (engine.py helpers).

These cover the pure, deterministic pieces — size-neutral ``free``-box padding,
changed-video detection against the ``.checksums.md5`` baseline, and the
inode-resolve + pad path of ``_prepare_video_patches`` driven by a fake ext4
reader.  None of them need ffmpeg or a real card image (the ffmpeg shrink path
for oversized clips is exercised by the manual extract->replace->Write
round-trip).
"""

import os

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine


# ---- _pad_isobmff: size-neutral padding -----------------------------------

def test_pad_isobmff_exact_fit_is_unchanged():
    data = b"A" * 100
    assert engine._pad_isobmff(data, 100) == data


def test_pad_isobmff_appends_a_valid_free_box():
    data = b"A" * 100
    out = engine._pad_isobmff(data, 200)
    assert len(out) == 200
    assert out[:100] == data
    box = out[100:]
    # 32-bit box: size word == box length, type 'free', zero payload.
    assert int.from_bytes(box[:4], "big") == 100
    assert box[4:8] == b"free"
    assert box[8:] == b"\x00" * 92


def test_pad_isobmff_small_gap_zero_pads():
    # A <8-byte gap can't hold a box header; trailing zeros are tolerated.
    data = b"A" * 100
    out = engine._pad_isobmff(data, 105)
    assert out == data + b"\x00" * 5


def test_pad_isobmff_truncates_when_oversized():
    # Defensive: the caller never pads past the target, but the branch is real.
    assert engine._pad_isobmff(b"A" * 100, 80) == b"A" * 80


# ---- _changed_videos: diff staged clips vs the Extract baseline ------------

def _make_extract(tmp_path):
    vid = tmp_path / "video"
    vid.mkdir()
    (vid / "a.mp4").write_bytes(b"AAAA")
    (vid / "b.mov").write_bytes(b"BBBB")
    (vid / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "a.mp4\t/spinball_le/scene.assets/1.asset\t4\n"
        "b.mov\t/spinball_le/scene.assets/2.asset\t4\n",
        encoding="utf-8")
    return vid


def test_changed_videos_returns_only_edited(tmp_path):
    vid = _make_extract(tmp_path)
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))

    # Edit one clip after the baseline was taken.
    (vid / "a.mp4").write_bytes(b"ZZZZZZ")

    changed = engine._changed_videos(str(tmp_path), baseline)
    assert [c[0] for c in changed] == ["a.mp4"]
    fname, card_path, staged = changed[0]
    assert card_path == "/spinball_le/scene.assets/1.asset"
    assert os.path.basename(staged) == "a.mp4"
    assert os.path.isfile(staged)


def test_changed_videos_no_manifest_is_empty(tmp_path):
    assert engine._changed_videos(str(tmp_path), {}) == []


def test_changed_videos_no_baseline_treats_all_as_changed(tmp_path):
    # Without a baseline entry we can't prove a clip is untouched, so it's
    # conservatively included (mirrors the audio "no baseline -> all" path).
    _make_extract(tmp_path)
    changed = engine._changed_videos(str(tmp_path), {})
    assert {c[0] for c in changed} == {"a.mp4", "b.mov"}


# ---- _prepare_video_patches: resolve inode + size-fit (pad path) -----------

class _FakeReader:
    """Duck-typed ext4 reader: yields (path, ino, node) for the given files."""

    def __init__(self, sizes):
        self._sizes = sizes  # {card_path: size}

    def iter_regular_files(self, min_size=1):
        for path, size in self._sizes.items():
            yield path, 0, {"size": size, "mode": 0, "flags": 0, "i_block": b""}


def test_prepare_video_patches_pads_to_slot_size(tmp_path):
    staged = tmp_path / "a.mp4"
    staged.write_bytes(b"A" * 50)
    work = tmp_path / "work"
    work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mp4", "/g/1.asset", str(staged))]

    patches, skipped = _prepare(reader, edits, work)
    assert skipped == 0
    assert len(patches) == 1
    node, payload = patches[0]
    assert node["size"] == 80
    assert len(payload) == 80              # exactly the slot size
    assert payload[:50] == b"A" * 50       # original bytes intact, then padded


def test_prepare_video_patches_skips_when_inode_missing(tmp_path):
    staged = tmp_path / "a.mp4"
    staged.write_bytes(b"A" * 50)
    work = tmp_path / "work"
    work.mkdir()
    reader = _FakeReader({})               # card path not found on the card
    edits = [("a.mp4", "/g/1.asset", str(staged))]

    patches, skipped = _prepare(reader, edits, work)
    assert patches == []
    assert skipped == 1


def _prepare(reader, edits, work):
    return engine._prepare_video_patches(
        reader, edits, str(work),
        log=lambda *a, **k: None, cancel=lambda: False)


# ---- capability / note wiring ---------------------------------------------

def test_stern_enables_replace_video_with_a_size_note():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    assert mfr.capabilities.replace_video is True
    note = mfr.video_length_note()
    assert note and "fit" in note.lower()
