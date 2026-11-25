"""PAD-1577: a flash, its verify and a card backup read on a thread of their
own, a few chunks ahead, while the loop writes or compares - so the image's
disk and the card work at the same time instead of in turn."""

import io
import os
import threading

import pytest

from pinball_decryptor.core import rawdevice as rd
from pinball_decryptor.core.rawdevice import (
    FlashCancelled, FlashError, RawDeviceFile, _ReadAhead, _file_reader)


def _pattern(n):
    return bytes((i * 7 + (i >> 9)) & 0xFF for i in range(n))


def _ahead_threads():
    return [t for t in threading.enumerate() if t.name == "pad-read-ahead"]


@pytest.mark.parametrize("depth", [0, 1, 2, 4])
def test_chunks_come_in_order_across_spans(depth):
    data = _pattern(10000)
    spans = [(0, 1000), (3000, 2500), (9000, 1000)]
    with _ReadAhead(spans, lambda p, n: data[p:p + n], 700, depth) as ra:
        got = list(ra)
    assert [p for p, _b in got] == [0, 700, 3000, 3700, 4400, 5100, 9000, 9700]
    assert b"".join(b for _p, b in got) == data[0:1000] + data[3000:5500] + data[9000:]
    assert not _ahead_threads()


def test_an_empty_read_ends_its_span_not_the_rest():
    data = _pattern(4000)
    # A source that runs dry at 1500: the first span stops there, handing
    # the empty read on; the second span is still read.
    def read(p, n):
        return b"" if 1500 <= p < 3000 else data[p:p + n]
    with _ReadAhead([(0, 2000), (3000, 1000)], read, 500) as ra:
        got = list(ra)
    assert [(p, len(b)) for p, b in got] == [
        (0, 500), (500, 500), (1000, 500), (1500, 0), (3000, 500), (3500, 500)]


def test_a_read_error_is_raised_in_the_taking_thread():
    def read(p, n):
        if p >= 200:
            raise OSError(5, "I/O error")
        return b"x" * n
    seen = []
    with pytest.raises(OSError, match="I/O error"):
        with _ReadAhead([(0, 1000)], read, 100) as ra:
            for p, _b in ra:
                seen.append(p)
    assert seen == [0, 100]          # every chunk before the bad one arrived
    assert not _ahead_threads()


def test_leaving_early_stops_the_thread_before_the_source_closes():
    reads = []
    def read(p, n):
        reads.append(p)
        return b"y" * n
    with _ReadAhead([(0, 1 << 20)], read, 16, depth=2) as ra:
        for p, _b in ra:
            if p == 32:
                break
    after = len(reads)
    assert not _ahead_threads()
    # Only a few chunks were read past the one the loop stopped at, and
    # nothing more is read once the with has ended.
    assert after <= 3 + 2 + 1
    assert len(reads) == after


def test_the_next_chunk_is_read_while_this_one_is_handled():
    # The read of chunk 1 must start while the loop still holds chunk 0:
    # the loop waits for it, which would time out if reads ran in turn.
    second_read = threading.Event()
    def read(p, n):
        if p == 10:
            second_read.set()
        return b"z" * n
    with _ReadAhead([(0, 40)], read, 10) as ra:
        it = iter(ra)
        next(it)
        assert second_read.wait(5), "chunk 1 was not read ahead"
        assert [p for p, _b in it] == [10, 20, 30]


def test_flash_reads_the_image_on_another_thread(tmp_path):
    img = _pattern(64 * 512)
    card = tmp_path / "c.dev"
    card.write_bytes(b"\0" * len(img))
    readers = set()

    class Src(io.BytesIO):
        def read(self, n=-1):
            readers.add(threading.get_ident())
            return super().read(n)

    with RawDeviceFile(str(card), writable=True, sector=512) as dev:
        assert dev.copy_image_onto(Src(img), len(img), chunk=4096) == len(img)
    assert card.read_bytes() == img
    assert readers and threading.get_ident() not in readers
    assert not _ahead_threads()


def test_flash_ranges_and_overlay_land_as_before(tmp_path):
    img = _pattern(32 * 512)
    card = tmp_path / "c.dev"
    card.write_bytes(b"\xee" * len(img))
    overlay = (5 * 512 + 3, b"OVERLAY!")
    ranges = [(0, 8 * 512), (20 * 512, 4 * 512)]
    with RawDeviceFile(str(card), writable=True, sector=512) as dev:
        n = dev.copy_image_onto(io.BytesIO(img), len(img), chunk=1024,
                                overlay=overlay, ranges=ranges)
    assert n == 12 * 512
    want = bytearray(b"\xee" * len(img))
    want[0:8 * 512] = img[0:8 * 512]
    want[20 * 512:24 * 512] = img[20 * 512:24 * 512]
    want[overlay[0]:overlay[0] + len(overlay[1])] = overlay[1]
    assert card.read_bytes() == bytes(want)


def test_flash_cancel_mid_way_stops_the_reader(tmp_path):
    img = _pattern(64 * 512)
    card = tmp_path / "c.dev"
    card.write_bytes(b"\0" * len(img))
    polls = {"n": 0}
    def cancel():
        polls["n"] += 1
        return polls["n"] > 3
    with RawDeviceFile(str(card), writable=True, sector=512) as dev:
        with pytest.raises(FlashCancelled, match="after 1536 of"):
            dev.copy_image_onto(io.BytesIO(img), len(img), chunk=512,
                                cancel=cancel)
    assert not _ahead_threads()


def test_verify_finds_a_bad_byte_and_stops_the_reader(tmp_path):
    img = tmp_path / "i.img"
    data = bytearray(_pattern(40 * 512))
    img.write_bytes(bytes(data))
    data[25 * 512 + 9] ^= 0xFF
    card = tmp_path / "c.dev"
    card.write_bytes(bytes(data))
    with pytest.raises(FlashError, match="first difference at byte 12,809"):
        rd._verify_flash_readback(str(card), str(img), len(data))
    assert not _ahead_threads()
    card.write_bytes(img.read_bytes())
    rd._verify_flash_readback(str(card), str(img), len(data))


def test_card_backup_reads_the_card_on_another_thread(tmp_path, monkeypatch):
    data = _pattern(48 * 512)
    card = tmp_path / "c.dev"
    card.write_bytes(data)
    readers = set()
    real = RawDeviceFile._aligned_read
    def spy(self, at, n):
        readers.add(threading.get_ident())
        return real(self, at, n)
    monkeypatch.setattr(RawDeviceFile, "_aligned_read", spy)
    monkeypatch.setattr(rd, "device_size", lambda p: len(data))
    monkeypatch.setattr(rd, "_VERIFY_CHUNK", 4096)
    out = tmp_path / "b.raw"
    assert rd.read_device_to_image(str(card), str(out), skip_free=False) \
        == len(data)
    assert out.read_bytes() == data
    assert threading.get_ident() not in readers
    assert not _ahead_threads()


def test_card_backup_read_error_names_how_far_it_got(tmp_path, monkeypatch):
    data = _pattern(48 * 512)
    card = tmp_path / "c.dev"
    card.write_bytes(data)
    real = RawDeviceFile._aligned_read
    def bad(self, at, n):
        if at >= 8192:
            raise OSError(5, "Input/output error")
        return real(self, at, n)
    monkeypatch.setattr(RawDeviceFile, "_aligned_read", bad)
    monkeypatch.setattr(rd, "device_size", lambda p: len(data))
    monkeypatch.setattr(rd, "_VERIFY_CHUNK", 4096)
    out = tmp_path / "b.raw"
    with pytest.raises(FlashError, match="failed at byte 8,192"):
        rd.read_device_to_image(str(card), str(out), skip_free=False)
    assert not os.path.exists(str(out)) and not os.path.exists(str(out) + ".part")
    assert not _ahead_threads()


def test_file_reader_seeks_and_overlays():
    f = io.BytesIO(bytes(range(100)))
    r = _file_reader(f, (10, b"\xff\xff"))
    assert r(8, 4) == bytes([8, 9, 0xFF, 0xFF])
    assert r(50, 2) == bytes([50, 51])
    assert r(100, 4) == b""
