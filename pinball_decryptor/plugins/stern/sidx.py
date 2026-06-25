"""Stern Spike 2 ``.sidx`` manifest regeneration.

Every moddable file on the data partition is indexed in ``/spk/index/<title>.sidx``
by an ``FI64`` record carrying the file's size, a keyed **HMAC-SHA1** digest, and a
plain **MD5**.  Stern's ``spk`` re-validates these; a mod with a stale record fails
SD validation.  So after a size-neutral Write we recompute the changed file's
record with the manifest's global validation key:

    record[37:57] = HMAC-SHA1(K, file)   (20B, keyed)
    record[57:73] = MD5(file)            (16B)

Sizes are unchanged (size-neutral) and the header CRC @0x34 is ``0xffffffff``
(disabled) on the modern FI64 cards, so nothing else needs touching.  ``K`` was
recovered by reverse-engineering the validator and verified global across cards
(it reproduces real stored digests, including ``image.bin``).
"""

import hashlib
import hmac
import struct

# Global Spike 2 SIDX manifest HMAC-SHA1 key (16 bytes).
SIDX_KEY = bytes.fromhex("8e1f5543c2f54a11673a282a2f87c006")

# FI64 record payload field offsets (verified on Led Zeppelin / Godzilla).
_HMAC_OFF = 37   # 20-byte HMAC-SHA1(K, file)
_MD5_OFF = 57    # 16-byte MD5(file)
_HMAC_LEN = 20
_MD5_LEN = 16


def find_sidx(reader):
    """Locate the ``/spk/index/*.sidx`` manifest on *reader*'s partition.

    Returns ``(path, inode)`` or ``(None, None)``.  The manifest lives on the
    same data partition as ``image.bin`` (verified), so the caller's existing
    reader can both find and patch it.
    """
    for path, ino, node in reader.iter_regular_files(min_size=1, max_depth=20):
        if path.endswith(".sidx") and "/spk/index/" in path:
            return path, node
    return None, None


def parse_records(data):
    """Parse an FI64 ``.sidx`` into ``{path: payload_offset}`` + header CRC.

    Records follow the ``STRS`` path block, each ``FI64`` + u32 len + payload;
    record *i* belongs to path *i*.  Paths have no leading slash (e.g.
    ``led_zeppelin_pro/image.bin``).  Returns ``({}, None)`` if not an FI64 sidx.
    """
    si = data.find(b"STRS")
    if si < 0 or len(data) < 0x38:
        return {}, None
    strs_len = struct.unpack_from("<I", data, si + 4)[0]
    paths = [p for p in data[si + 8:si + 8 + strs_len].split(b"\x00") if p]
    pos = si + 8 + strs_len
    payload_offs = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == b"FI64":
        ln = struct.unpack_from("<I", data, pos + 4)[0]
        payload_offs.append(pos + 8)
        pos += 8 + ln
    recs = {paths[i].decode("latin1"): payload_offs[i]
            for i in range(min(len(paths), len(payload_offs)))}
    hdr_crc = struct.unpack_from("<I", data, 0x34)[0]
    return recs, hdr_crc


def digests(data):
    """``(HMAC-SHA1(K, data), MD5(data))`` for an in-memory file."""
    return (hmac.new(SIDX_KEY, data, hashlib.sha1).digest(),
            hashlib.md5(data).digest())


def record_field_writes(payload_off, hmac_digest, md5_digest):
    """Sidx-file-relative ``[(offset, bytes), ...]`` to write one record's
    HMAC + MD5.  The caller maps these through the sidx inode to disk."""
    return [(payload_off + _HMAC_OFF, hmac_digest),
            (payload_off + _MD5_OFF, md5_digest)]
