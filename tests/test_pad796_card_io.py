"""PAD-796: sector-aligned device writes go straight through (no pre-read),
aligned reads come back as one buffer, and a partclone restore reads and
writes runs of used blocks instead of one block at a time.  Each is held to
the byte-by-byte code it replaced."""

import io
import os
import random
import struct

import pytest

from pinball_decryptor.core import partclone, rawdevice
from pinball_decryptor.core.rawdevice import RawDeviceFile

SEC = 512


def _card(tmp_path, sectors=64):
    p = tmp_path / "card.bin"
    body = bytes(random.Random(7).getrandbits(8) for _ in range(sectors * SEC))
    p.write_bytes(body)
    return str(p), bytearray(body)


def _reads(monkeypatch):
    """Record every device read the RawDeviceFile makes: (start, length)."""
    calls = []
    real = RawDeviceFile._aligned_read

    def _spy(self, start, length):
        calls.append((start, length))
        return real(self, start, length)
    monkeypatch.setattr(RawDeviceFile, "_aligned_read", _spy)
    return calls


def test_aligned_write_does_not_read_the_card_first(tmp_path, monkeypatch):
    path, model = _card(tmp_path)
    calls = _reads(monkeypatch)
    data = os.urandom(3 * SEC)
    with RawDeviceFile(path, writable=True, sector=SEC) as dev:
        dev.seek(5 * SEC)
        assert dev.write(data) == len(data)
        assert dev.tell() == 5 * SEC + len(data)
    assert calls == []
    model[5 * SEC:8 * SEC] = data
    assert open(path, "rb").read() == bytes(model)


@pytest.mark.parametrize("start,length", [
    (3, 10),                      # inside one sector
    (SEC - 3, 6),                 # straddles two sectors, no whole one
    (SEC, 7),                     # aligned start, partial tail
    (SEC + 9, SEC - 9),           # partial head, aligned end
    (SEC + 9, 3 * SEC),           # partial head, whole middle, partial tail
    (2 * SEC, 4 * SEC),           # whole sectors only
    (60 * SEC + 5, 4 * SEC - 5),  # runs to the end of the card
])
def test_unaligned_writes_land_and_only_the_edges_are_read(
        tmp_path, monkeypatch, start, length):
    path, model = _card(tmp_path)
    calls = _reads(monkeypatch)
    data = bytes((i * 31 + 7) & 0xFF for i in range(length))
    with RawDeviceFile(path, writable=True, sector=SEC) as dev:
        dev.seek(start)
        dev.write(data)
    model[start:start + length] = data
    assert open(path, "rb").read() == bytes(model)
    # at most the head sector and the tail sector are read back
    assert len(calls) <= 2
    for s, n in calls:
        assert s % SEC == 0 and n <= 2 * SEC


def test_many_random_writes_match_a_byte_model(tmp_path):
    path, model = _card(tmp_path, sectors=40)
    rng = random.Random(796)
    with RawDeviceFile(path, writable=True, sector=SEC) as dev:
        for _ in range(300):
            start = rng.randrange(0, 40 * SEC - 1)
            length = rng.randrange(1, min(5 * SEC, 40 * SEC - start) + 1)
            data = bytes(rng.getrandbits(8) for _ in range(length))
            dev.seek(start)
            dev.write(data)
            model[start:start + length] = data
    assert open(path, "rb").read() == bytes(model)


def test_aligned_read_is_exact_and_single_buffer(tmp_path, monkeypatch):
    path, model = _card(tmp_path)
    with RawDeviceFile(path, writable=False, sector=SEC) as dev:
        # unaligned start and length
        assert dev._aligned_read(SEC + 5, 2 * SEC - 9) == bytes(model[SEC + 5:3 * SEC - 4])
        # aligned: exactly the device's bytes
        got = dev._aligned_read(4 * SEC, 6 * SEC)
        assert got == bytes(model[4 * SEC:10 * SEC]) and isinstance(got, bytes)
        # short at the device end, and past it
        assert dev._aligned_read(62 * SEC, 10 * SEC) == bytes(model[62 * SEC:])
        assert dev._aligned_read(64 * SEC + 3, 5) == b""
        assert dev._aligned_read(10, 0) == b""
        # several device-sized chunks are joined in order
        monkeypatch.setattr(rawdevice, "_IO_CHUNK", 3 * SEC)
        assert dev._aligned_read(1 * SEC, 10 * SEC) == bytes(model[SEC:11 * SEC])
        assert dev._aligned_read(1 * SEC + 1, 10 * SEC) == bytes(model[SEC + 1:11 * SEC + 1])
        dev.seek(2 * SEC)
        assert dev.read(7 * SEC + 3) == bytes(model[2 * SEC:9 * SEC + 3])
        assert dev.tell() == 9 * SEC + 3


# ---------------------------------------------------------------------------
# partclone
# ---------------------------------------------------------------------------

def _old_restore(img, stream, out):
    """PartcloneImage.restore as it was: one block per read/seek/write."""
    bitmap = partclone._read_exact(stream, img.bitmap_bytes)
    partclone._read_exact(stream, img.checksum_size)
    bs, bpc, csize, total = (img.block_size, img.blocks_per_checksum or 0,
                             img.checksum_size, img.totalblock)
    written = since_crc = 0
    for byte_idx in range(img.bitmap_bytes):
        bits = bitmap[byte_idx]
        if bits == 0:
            continue
        for i in range(8):
            if not (bits >> i) & 1:
                continue
            block = byte_idx * 8 + i
            if block >= total:
                break
            out.seek(block * bs)
            out.write(partclone._read_exact(stream, bs))
            written += 1
            since_crc += 1
            if bpc and since_crc == bpc:
                partclone._read_exact(stream, csize)
                since_crc = 0
    out.truncate(total * bs)
    return written


def _naive_runs(bitmap, total):
    runs, start = [], None
    for b in range(total):
        used = (bitmap[b >> 3] >> (b & 7)) & 1
        if used and start is None:
            start = b
        elif not used and start is not None:
            runs.append((start, b - start))
            start = None
    if start is not None:
        runs.append((start, total - start))
    return runs


def _image(used, total, bs=64, bpc=5):
    """A partclone v2 stream for *used* blocks of *total* (bitmap padded to
    whole bytes, CRC after every *bpc* data blocks)."""
    from tests import synthetic  # noqa: F401  (same layout as its builder)
    head = bytearray()
    head += b"partclone-image\x00" + b"0.3.36".ljust(14, b"\x00") + b"0002"
    head += struct.pack("<H", 0xC0DE) + b"EXTFS".ljust(16, b"\x00")
    head += struct.pack("<4Q", total * bs, total, len(used), len(used))
    head += struct.pack("<I", bs) + struct.pack("<I", 18)
    head += struct.pack("<HHHH", 2, 64, 32, 4) + struct.pack("<I", bpc)
    head += bytes([1, 1]) + struct.pack("<I", 0)
    bitmap = bytearray((total + 7) // 8)
    for b in used:
        bitmap[b >> 3] |= 1 << (b & 7)
    # pad bits past ``total`` set: the reader must clip them
    for b in range(total, len(bitmap) * 8):
        bitmap[b >> 3] |= 1 << (b & 7)
    body = bytearray(bytes(bitmap) + b"\0\0\0\0")
    n = 0
    for blk in sorted(used):
        body += bytes([(blk * 37 + 11) & 0xFF]) * bs
        n += 1
        if bpc and n % bpc == 0:
            body += b"CRC!"
    return bytes(head) + bytes(body)


@pytest.mark.parametrize("pattern", [
    "none", "all", "first", "last", "alternate", "long-runs", "random",
])
@pytest.mark.parametrize("bpc", [0, 1, 3, 5, 64])
def test_restore_matches_the_block_by_block_reader(pattern, bpc, monkeypatch,
                                                   tmp_path):
    total = 203                                         # not a byte multiple
    rng = random.Random(hash((pattern, bpc)) & 0xFFFF)
    used = {
        "none": set(), "all": set(range(total)), "first": {0}, "last": {202},
        "alternate": set(range(0, total, 2)),
        "long-runs": set(range(3, 90)) | set(range(100, 190)) | {202},
        "random": {b for b in range(total) if rng.random() < 0.6},
    }[pattern]
    monkeypatch.setattr(partclone, "_RUN_CHUNK_BLOCKS", 7)  # pieces inside runs
    data = _image(used, total, bpc=bpc)
    img = partclone.PartcloneImage.from_stream(io.BytesIO(data[:110]))
    # real files: truncate() extends them, as the restore's padding relies on
    with open(tmp_path / "want.img", "wb") as want:
        _old_restore(img, io.BytesIO(data[110:]), want)
    progress = []
    with open(tmp_path / "got.img", "wb") as got:
        n = img.restore(io.BytesIO(data[110:]), got,
                        progress_cb=lambda d, t: progress.append((d, t)))
    assert n == len(used)
    got_bytes = (tmp_path / "got.img").read_bytes()
    assert got_bytes == (tmp_path / "want.img").read_bytes()
    assert len(got_bytes) == total * img.block_size
    assert progress[-1] == (len(used), len(used))
    assert [d for d, _t in progress] == sorted(d for d, _t in progress)


def test_iter_runs_matches_bit_walk():
    rng = random.Random(1)
    for total in (1, 7, 8, 9, 64, 65, 1000, 4097):
        for density in (0.0, 0.05, 0.5, 0.95, 1.0):
            bitmap = bytearray((total + 7) // 8)
            for b in range(total):
                if rng.random() < density:
                    bitmap[b >> 3] |= 1 << (b & 7)
            for b in range(total, len(bitmap) * 8):      # padding bits set
                bitmap[b >> 3] |= 1 << (b & 7)
            assert (list(partclone.iter_runs(bytes(bitmap), total))
                    == _naive_runs(bitmap, total)), (total, density)
    # long uniform stretches are skipped whole
    bitmap = b"\0" * 1000 + b"\xff" * 1000 + b"\x0f" + b"\0" * 1000
    assert list(partclone.iter_runs(bitmap, 8 * len(bitmap))) == [(8000, 8004)]


def test_restore_cancel_and_truncated_stream():
    used = set(range(0, 100))
    data = _image(used, 100, bpc=10)
    img = partclone.PartcloneImage.from_stream(io.BytesIO(data[:110]))
    with pytest.raises(partclone.PartcloneError, match="canceled"):
        img.restore(io.BytesIO(data[110:]), io.BytesIO(),
                    cancel_cb=lambda: True)
    with pytest.raises(partclone.PartcloneError, match="Unexpected end"):
        img.restore(io.BytesIO(data[110:-40]), io.BytesIO())
