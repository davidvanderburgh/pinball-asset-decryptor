"""PAD-1583: a flash's verify reads the card alone.

Each chunk is hashed as it is written; the verify reads the card back and
compares the hashes, so the image (often on a spinning disk) is not read a
second time.  Only a chunk that does not match sends it back to the image,
to name the first byte that differs, as before."""

import os

import pytest

from pinball_decryptor.core import rawdevice as rd
from tests.test_flash_card_read_errors import _menu_case
from tests.test_stern_flash import _pattern


def _img_and_card(tmp_path, n=300 * 512 + 77):
    img = tmp_path / "img.raw"
    img.write_bytes(_pattern(n))
    card = tmp_path / "card.raw"
    card.write_bytes(b"\xA5" * (n + 4096))
    return str(img), str(card)


def _swap_image_at_verify(path):
    """An ``on_verify_start`` that puts other bytes in the image: a verify
    that read the image would now fail a good card."""
    def swap():
        size = os.path.getsize(path)
        with open(path, "wb") as f:
            f.write(b"\x5A" * size)
    return swap


def _image_reads(monkeypatch, path):
    """Opens of *path* from here on, counted."""
    seen = []
    real = open

    def counting(file, *a, **k):
        if os.fspath(file) == path:
            seen.append(a[0] if a else k.get("mode", "r"))
        return real(file, *a, **k)
    monkeypatch.setattr("builtins.open", counting)
    return seen


@pytest.mark.parametrize("skip_free", [True, False])
def test_verify_does_not_read_the_image(tmp_path, monkeypatch, skip_free):
    img, card = _img_and_card(tmp_path)
    data = open(img, "rb").read()
    monkeypatch.setattr(rd, "_FLASH_CHUNK", 64 * 512)
    state = {}

    def at_verify():
        state["opens"] = _image_reads(monkeypatch, img)
        _swap_image_at_verify(img)()
        state["opens"].clear()          # the swap's own write
    seen = []
    rd.flash_image_to_device(img, card, eject=False, skip_free=skip_free,
                             on_verify_start=at_verify,
                             log=lambda m, _l="": seen.append(m))
    assert state["opens"] == []
    assert open(card, "rb").read()[:len(data)] == data
    assert any("Card verified" in m for m in seen)


def test_a_bad_byte_is_still_named_exactly(tmp_path, monkeypatch):
    img, card = _img_and_card(tmp_path)
    monkeypatch.setattr(rd, "_FLASH_CHUNK", 64 * 512)
    bad = 130 * 512 + 9
    real = rd.RawDeviceFile.copy_image_onto

    def flaky(self, *a, **k):
        n = real(self, *a, **k)
        self.seek(bad)
        self.write(b"\x00\x00")
        return n
    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", flaky)
    want = bad if open(img, "rb").read()[bad] != 0 else bad + 1
    with pytest.raises(rd.FlashError,
                       match="first difference at byte %s" % f"{want:,}"):
        rd.flash_image_to_device(img, card, eject=False, skip_free=False)


def test_the_unaligned_tail_is_verified_too(tmp_path, monkeypatch):
    img, card = _img_and_card(tmp_path)
    size = os.path.getsize(img)
    real = rd.RawDeviceFile.copy_image_onto

    def flaky(self, *a, **k):
        n = real(self, *a, **k)
        self.seek(size - 1)
        self.write(b"\xFF" if open(img, "rb").read()[-1] != 0xFF else b"\0")
        return n
    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", flaky)
    with pytest.raises(rd.FlashError,
                       match="first difference at byte %s" % f"{size - 1:,}"):
        rd.flash_image_to_device(img, card, eject=False, skip_free=False)


def test_digests_cover_every_written_byte_with_the_overlay(tmp_path):
    img, card = _img_and_card(tmp_path)
    data = open(img, "rb").read()
    overlay = (1000, b"KEPT" * 300)
    digests = []
    with rd.RawDeviceFile(card, writable=True) as dev, open(img, "rb") as src:
        n = dev.copy_image_onto(src, len(data), chunk=8 * 512,
                                overlay=overlay, digests=digests)
    assert n == len(data)
    assert sum(length for _p, length, _d in digests) == len(data)
    assert [p for p, _l, _d in digests] == sorted(p for p, _l, _d in digests)
    on_card = open(card, "rb").read()
    for pos, length, d in digests:
        assert rd._chunk_digest(on_card[pos:pos + length]) == d
    # the card holds the overlay, so a verify by hash passes ...
    rd._verify_flash_readback(card, img, len(data), overlay=overlay,
                              digests=digests)
    # ... and a byte off inside it is named against the overlay, not the image
    with open(card, "r+b") as f:
        f.seek(1003)
        f.write(b"?")
    with pytest.raises(rd.FlashError, match="first difference at byte 1,003"):
        rd._verify_flash_readback(card, img, len(data), overlay=overlay,
                                  digests=digests)


def test_verify_by_hash_can_be_canceled(tmp_path):
    img, card = _img_and_card(tmp_path)
    data = open(img, "rb").read()
    digests = []
    with rd.RawDeviceFile(card, writable=True) as dev, open(img, "rb") as src:
        dev.copy_image_onto(src, len(data), chunk=8 * 512, digests=digests)
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 3
    with pytest.raises(rd.FlashCancelled, match="Verify canceled after"):
        rd._verify_flash_readback(card, img, len(data), cancel=cancel,
                                  digests=digests)


def test_no_hashes_kept_when_not_verifying(tmp_path, monkeypatch):
    img, card = _img_and_card(tmp_path)
    got = {}
    real = rd.RawDeviceFile.copy_image_onto

    def spy(self, *a, **k):
        got["digests"] = k.get("digests")
        return real(self, *a, **k)
    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", spy)
    rd.flash_image_to_device(img, card, eject=False, verify=False)
    assert got["digests"] is None


def test_menu_verify_does_not_read_the_image(tmp_path, monkeypatch):
    img, card = _menu_case(tmp_path)
    img = str(img)
    state = {}

    def at_verify():
        state["opens"] = _image_reads(monkeypatch, img)
        _swap_image_at_verify(img)()
        state["opens"].clear()
    rd.flash_menu_to_device(img, str(card), on_verify_start=at_verify)
    assert state["opens"] == []


def test_menu_verify_still_catches_a_bad_write(tmp_path, monkeypatch):
    img, card = _menu_case(tmp_path)
    img = str(img)
    off, _length, _w = rd.menu_write_plan(img)["write"][0]
    real = rd._flash_menu_plan

    def flaky(image_path, device_path, plan, **k):
        n = real(image_path, device_path, plan, **k)
        assert k["digests"]
        with open(device_path, "r+b") as f:
            f.seek(off + 5)
            f.write(b"\x00\xFF\x00\xFF")
        return n
    monkeypatch.setattr(rd, "_flash_menu_plan", flaky)
    with pytest.raises(rd.FlashError, match="of the menu partition"):
        rd.flash_menu_to_device(img, str(card))
