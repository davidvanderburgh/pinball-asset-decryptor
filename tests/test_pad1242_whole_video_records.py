"""PAD-1242: a Spike 2 build refreshes the .sidx records of the videos the ext4
driver copies on whole, so the card's own manifest matches what PAD put on it.

DragonRR built his Heisei card with PAD from the official Godzilla LE 1.16,
and Card details said "Its own manifest still lists 543 changed files as
Stern's, so it was not built by PAD": the 543 were the videos replaced
intact, whose records the build never touched.
"""

import hashlib
import io
import struct

from pinball_decryptor.plugins.stern import engine, sidx, stock_prints

VIDEO = "godzilla_le/assets/video/attract.mp4"
STOCK = b"STOCK-CLIP-" + b"\x00" * 53                    # 64 bytes
NEW = b"A MUCH LONGER REPLACEMENT CLIP " * 9             # another size


def _finf_sidx(path, size, md5):
    """A one-record FINF manifest naming *path* at *size* / *md5*."""
    paths = path.encode() + b"\x00"
    rec = bytearray(60)
    struct.pack_into("<I", rec, 12, size)
    rec[41:57] = bytes.fromhex(md5)
    body = b"STRS" + struct.pack("<I", len(paths)) + paths
    body += b"FINF" + struct.pack("<I", 60) + bytes(rec)
    hdr = bytearray(0x48)
    hdr[0:4] = b"SIDX"
    struct.pack_into("<I", hdr, 0x34, 0xffffffff)
    return bytes(hdr) + body


def test_a_video_copied_on_whole_gets_its_record_refreshed(tmp_path):
    src = tmp_path / "attract.mp4"
    src.write_bytes(NEW)
    man = _finf_sidx(VIDEO, len(STOCK), hashlib.md5(STOCK).hexdigest())
    X = 0x10000
    disk = io.BytesIO(b"\x00" * (X + len(man) + 16))
    disk.seek(0)
    disk.write(STOCK)
    disk.seek(X)
    disk.write(man)
    vnode = {"size": len(STOCK), "i_block": b"video-ib", "_b": 0}
    snode = {"size": len(man), "i_block": b"sidx-ib", "_b": X}

    class Reader:
        def iter_regular_files(self, min_size=1, max_depth=None):
            yield "/" + VIDEO, 11, vnode
            yield "/spk/index/godzilla_le-1_16_0.sidx", 12, snode

        def read_file_bytes(self, node):
            return disk.getvalue()[node["_b"]:node["_b"] + node["size"]]

        def disk_ranges(self, node, off, length):
            return [(node["_b"] + off, length)]

    # before PAD-1242 a whole-copied video wrote no record at all
    assert engine._compute_sidx_writes(
        Reader(), disk, None, {}, [], [], {}, lambda *a, **k: None) == []

    writes = engine._compute_sidx_writes(
        Reader(), disk, None, {}, [], [], {}, lambda *a, **k: None,
        whole_files=[(VIDEO, str(src))])
    assert writes
    buf = bytearray(disk.getvalue())
    for d, b in writes:
        buf[d:d + len(b)] = b
    after = bytes(buf[X:X + len(man)])
    assert len(after) == len(man)                # patched in place
    got = sidx.manifest_files(after)[VIDEO]
    assert got == (len(NEW), hashlib.md5(NEW).hexdigest())
    recs, _crc, _fmt = sidx.parse_records(after)
    hm, _md = sidx.digests(NEW)
    po = recs[VIDEO]
    assert after[po + 21:po + 41] == hm

    # and the stock check finds the record true to the card's file
    class CardReader:
        pass
    files, stale = stock_prints.card_files(
        CardReader(), sidx.manifest_files(after), [VIDEO],
        nodes={VIDEO: {"size": len(NEW)}})
    assert stale == 0 and files[VIDEO][0] == len(NEW)
