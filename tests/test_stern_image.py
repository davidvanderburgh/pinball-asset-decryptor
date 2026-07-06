"""Tests for the Stern Spike 2 Replace-Image write path (engine.py helpers).

Pure, deterministic pieces only — trailing-byte padding, changed-image
detection against the ``.checksums.md5`` baseline, and the inode-resolve + pad
path of ``_prepare_image_patches`` driven by a fake ext4 reader.  No real card
needed (the Pillow recompress path for oversized images is exercised by the
manual extract->replace->Write round-trip and by ``tests/core`` image tests).
"""

import os

import pytest

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


# ---- _pad_image: size-neutral trailing padding ----------------------------

def test_pad_image_exact_fit_is_unchanged():
    data = b"\x89PNG" + b"A" * 96
    assert engine._pad_image(data, 100) == data


def test_pad_image_appends_trailing_zeros():
    data = b"A" * 100
    out = engine._pad_image(data, 160)
    assert len(out) == 160
    assert out[:100] == data
    assert out[100:] == b"\x00" * 60


def test_pad_image_truncates_when_oversized():
    assert engine._pad_image(b"A" * 100, 80) == b"A" * 80


# ---- _changed_images: diff staged images vs the Extract baseline -----------

def _make_image_extract(tmp_path):
    img = tmp_path / "images"
    (img / "g" / "login").mkdir(parents=True)
    Image.new("RGBA", (8, 6), (1, 2, 3, 255)).save(img / "g" / "login" / "a.png")
    Image.new("RGB", (8, 6), (9, 9, 9)).save(img / "g" / "b.png")
    (img / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "g/login/a.png\t/munsters_le/assets/g/login/a.png\t100\n"
        "g/b.png\t/munsters_le/assets/g/b.png\t100\n",
        encoding="utf-8")
    return img


def test_changed_images_returns_only_edited(tmp_path):
    img = _make_image_extract(tmp_path)
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))

    # Edit one image after the baseline was taken.
    Image.new("RGBA", (8, 6), (200, 0, 0, 255)).save(img / "g" / "login" / "a.png")

    changed = engine._changed_images(str(tmp_path), baseline)
    assert [c[0] for c in changed] == ["g/login/a.png"]
    output, card_path, staged = changed[0]
    assert card_path == "/munsters_le/assets/g/login/a.png"
    assert os.path.isfile(staged) and staged.endswith("a.png")


def test_changed_images_no_manifest_is_empty(tmp_path):
    assert engine._changed_images(str(tmp_path), {}) == []


# ---- _prepare_image_patches: resolve inode + size-fit (pad path) -----------

class _FakeReader:
    def __init__(self, sizes):
        self._sizes = sizes  # {card_path: size}

    def iter_regular_files(self, min_size=1):
        for path, size in self._sizes.items():
            yield path, 0, {"size": size, "mode": 0, "flags": 0, "i_block": b""}


def _prepare(reader, edits, work):
    return engine._prepare_image_patches(
        reader, edits, str(work),
        log=lambda *a, **k: None, cancel=lambda: False)


def test_prepare_image_patches_pads_to_slot_size(tmp_path):
    staged = tmp_path / "a.png"
    Image.new("RGBA", (8, 6), (1, 2, 3, 255)).save(staged)
    orig = os.path.getsize(staged)
    work = tmp_path / "work"
    work.mkdir()
    target = orig + 64                     # slot is bigger -> pads up
    reader = _FakeReader({"/g/a.png": target})
    edits = [("g/a.png", "/g/a.png", str(staged))]

    patches, skipped = _prepare(reader, edits, work)
    assert skipped == 0
    assert len(patches) == 1
    node, payload = patches[0]
    assert node["size"] == target
    assert len(payload) == target          # exactly the slot size
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"   # original PNG header intact


def test_prepare_image_patches_skips_when_inode_missing(tmp_path):
    staged = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(staged)
    work = tmp_path / "work"
    work.mkdir()
    reader = _FakeReader({})               # card path not found
    edits = [("g/a.png", "/g/a.png", str(staged))]

    patches, skipped = _prepare(reader, edits, work)
    assert patches == []
    assert skipped == 1


# ---- capability / note wiring ---------------------------------------------

def test_stern_enables_replace_image_with_a_note():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    assert mfr.capabilities.replace_image is True
    # The note is now a one-liner pointing at the "?" help (monkeybug); the
    # per-store fitting rules moved into help_dialog's Replace Images tab.
    note = mfr.image_note()
    assert note and "help" in note.lower()
    from pinball_decryptor.gui.help_dialog import HELP_CONTENT
    img_help = " ".join(t + " " + b for t, b in HELP_CONTENT["Replace Images"])
    assert "byte" in img_help.lower()
