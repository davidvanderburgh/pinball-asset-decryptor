"""PAD-1104: a 16.58 GB Godzilla multi-boot flash wrote for 40 minutes onto
a 6.8 MB/s card, read most of it back, then stopped with "Write Failed:
Unexpected error: [Errno 22] Invalid argument" and a traceback.

On Windows the C runtime turns every card read error it has no errno for (a
bad sector, a CRC error, a reader that dropped off) into EINVAL, and nothing
on the way up caught it.  Now:

1. a read the card or reader fails is tried again on a fresh handle, so a
   one-off reader hiccup no longer fails a 40-minute flash;
2. a card that keeps failing stops the flash with a FlashError that says how
   far it got, that the card must not go in the machine, and what to try;
3. the write side, the menu-only write and verify, and the menu read say
   the same instead of 'Unexpected error'."""

import errno

import pytest

from pinball_decryptor.core import rawdevice as rd
from pinball_decryptor.core.rawdevice import FlashError, RawDeviceFile
from pinball_decryptor.plugins.stern.pipeline import SternFlashImagePipeline
from tests.test_stern_flash import _SEC, _at, _pattern, _spike_image


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(rd, "_READ_RETRY_PAUSE_S", 0)


def _einval():
    return OSError(errno.EINVAL, "Invalid argument")


def _failing_readback(monkeypatch, bad_at, times):
    """Read-only (verify) reads that cover byte *bad_at* raise EINVAL, the
    first *times* times (None = for ever).  Returns the reopen counter."""
    real = RawDeviceFile._aligned_read
    state = {"left": times, "reopens": 0}

    def read(self, start, length):
        if (not self.writable and start <= bad_at < start + length
                and (state["left"] is None or state["left"] > 0)):
            if state["left"] is not None:
                state["left"] -= 1
            raise _einval()
        return real(self, start, length)

    real_reopen = RawDeviceFile.reopen

    def reopen(self):
        state["reopens"] += 1
        return real_reopen(self)

    monkeypatch.setattr(RawDeviceFile, "_aligned_read", read)
    monkeypatch.setattr(RawDeviceFile, "reopen", reopen)
    return state


def _img_and_card(tmp_path, n=40000):
    img = tmp_path / "src.img"
    img.write_bytes(_pattern(n))
    card = tmp_path / "card.dev"
    card.write_bytes(b"\x00" * (n + 8192))
    return img, card


def test_a_read_back_the_reader_fails_once_is_tried_again(tmp_path,
                                                          monkeypatch):
    img, card = _img_and_card(tmp_path)
    state = _failing_readback(monkeypatch, 39000, times=1)
    said = []
    written = rd.flash_image_to_device(
        str(img), str(card), log=lambda m, k="info": said.append(m))
    assert written == 40000
    assert state["reopens"] == 1
    assert "matches the image byte-for-byte" in " ".join(said)


def test_a_card_that_keeps_failing_its_read_back_says_so(tmp_path,
                                                         monkeypatch):
    """The reported card: the read-back fails near the end, every time."""
    img, card = _img_and_card(tmp_path)
    state = _failing_readback(monkeypatch, 39000, times=None)
    with pytest.raises(FlashError) as e:
        rd.flash_image_to_device(str(img), str(card))
    msg = str(e.value)
    assert state["reopens"] == rd._READ_RETRIES
    assert msg.startswith("The card could not be read back at ")
    assert " of %s:" % rd.format_size(40000) in msg
    assert "do NOT install this card" in msg
    assert "different card reader, or a different card" in msg
    assert "%d tries" % (rd._READ_RETRIES + 1) in msg
    assert "Unexpected" not in msg and "Errno" not in msg


def test_the_pipeline_shows_it_as_a_write_failure_not_unexpected(
        tmp_path, monkeypatch):
    import pinball_decryptor.plugins.stern.pipeline as pl
    monkeypatch.setattr(pl, "is_device_path", lambda _p: True)
    img, card = _img_and_card(tmp_path)
    _failing_readback(monkeypatch, 39000, times=None)
    logged, results = [], []
    pipe = SternFlashImagePipeline(
        str(img), str(card),
        log_cb=lambda m, *a, **k: logged.append(m),
        phase_cb=lambda *a, **k: None, progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: results.append((ok, msg)))
    pipe.run()
    assert results and results[0][0] is False
    assert "could not be read back" in results[0][1]
    assert not any("Unexpected error" in m or "Traceback" in m
                   for m in logged + [results[0][1]])


def test_windows_einval_is_named_as_the_catch_all_it_is(monkeypatch):
    monkeypatch.setattr(rd.sys, "platform", "win32")
    assert "Windows reports only as 'Invalid argument'" in \
        rd._card_error_detail(_einval())
    # a real Win32 error keeps its own words
    e = OSError(0, "ReadFile(x) failed (WinError 23)")
    assert rd._card_error_detail(e) == "ReadFile(x) failed (WinError 23)"


def test_elsewhere_the_os_words_are_kept(monkeypatch):
    monkeypatch.setattr(rd.sys, "platform", "linux")
    assert rd._card_error_detail(OSError(errno.EIO, "Input/output error")) \
        == "Input/output error"


def test_reopen_keeps_the_old_handle_when_the_card_is_gone(tmp_path,
                                                           monkeypatch):
    card = tmp_path / "card.dev"
    card.write_bytes(b"\x01" * 4096)
    with RawDeviceFile(str(card), writable=False) as dev:
        monkeypatch.setattr(rd, "_open_backend",
                            lambda p, w: (_ for _ in ()).throw(_einval()))
        with pytest.raises(OSError):
            dev.reopen()
        assert dev._aligned_read(0, 512) == b"\x01" * 512


def test_a_failing_write_is_a_flash_error(tmp_path, monkeypatch):
    img, card = _img_and_card(tmp_path)

    def broken(self, *a, **k):
        raise OSError(0, "WriteFile(card) failed (WinError 1117)")
    monkeypatch.setattr(RawDeviceFile, "copy_image_onto", broken)
    with pytest.raises(FlashError) as e:
        rd.flash_image_to_device(str(img), str(card))
    assert "Writing the card failed" in str(e.value)
    assert "WinError 1117" in str(e.value)
    assert "do NOT install it" in str(e.value)


def _menu_case(tmp_path):
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    card = tmp_path / "card.raw"
    card.write_bytes((tmp_path / "img.raw").read_bytes())
    raw = bytearray((tmp_path / "img.raw").read_bytes())
    raw[128 * _SEC:128 * _SEC + 64] = b"A DIFFERENT MENU".ljust(64)
    (tmp_path / "img.raw").write_bytes(bytes(raw))
    return img, card


def test_menu_verify_retries_then_passes(tmp_path, monkeypatch):
    img, card = _menu_case(tmp_path)
    state = _failing_readback(monkeypatch, 128 * _SEC + 10, times=2)
    n = rd.flash_menu_to_device(img, str(card))
    assert n == 128 * _SEC
    assert _at(str(card), 128, 16) == b"A DIFFERENT MENU"
    assert state["reopens"] == 2


def test_menu_verify_that_keeps_failing_says_so(tmp_path, monkeypatch):
    img, card = _menu_case(tmp_path)
    _failing_readback(monkeypatch, 128 * _SEC + 10, times=None)
    with pytest.raises(FlashError) as e:
        rd.flash_menu_to_device(img, str(card))
    assert str(e.value).startswith("The menu partition could not be read "
                                   "back at 0 bytes of ")


def test_menu_read_error_is_a_flash_error(tmp_path, monkeypatch):
    img, _card = _menu_case(tmp_path)

    def broken(self, start, length):
        if start >= 128 * _SEC:
            raise _einval()
        return real(self, start, length)
    real = RawDeviceFile._aligned_read
    monkeypatch.setattr(RawDeviceFile, "_aligned_read", broken)
    out = tmp_path / "menu.raw"
    with pytest.raises(FlashError) as e:
        rd.read_device_menu_to_image(img, str(out))
    assert "Reading the boot menu off the card failed" in str(e.value)
    assert not out.exists()
    assert not (tmp_path / "menu.raw.part").exists()
