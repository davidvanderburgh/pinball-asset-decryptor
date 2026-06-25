"""Stern Spike 2 ``.sidx`` manifest regeneration.

Every moddable file on the data partition is indexed in ``/spk/index/<title>.sidx``
by a per-file record carrying the file's size, a keyed **HMAC-SHA1** digest, and a
plain **MD5**.  Stern's ``spk`` re-validates these; a mod with a stale record fails
SD validation.  So after a size-neutral Write we recompute the changed file's
record with the manifest's global validation key.

Two record formats exist in the wild — **same keyed scheme, different layout**, and
a given manifest uses one throughout:

  * ``FI64`` (80-byte payload): ``HMAC-SHA1(K, file)`` @37, ``MD5(file)`` @57.
    Led Zeppelin, Godzilla, Metallica, Batman, Elvira, …
  * ``FINF`` (60-byte payload): ``HMAC-SHA1(K, file)`` @21, ``MD5(file)`` @41.
    TMNT, Deadpool, King Kong, Munsters, Avengers, Jurassic Park, …

The split is per-title (NOT chronological). Sizes are unchanged (size-neutral) so
only the two digest fields need rewriting.  ``K`` was recovered by
reverse-engineering the validator and verified global across cards and both
formats (it reproduces real stored digests, including ``image.bin``).

The header word @0x34 (live on FINF cards, ``0xffffffff`` on FI64) is intentionally
left untouched: disassembly of both on-card ``.sidx`` parsers (``spk`` and the
``spike_menu`` shell) and the game firmware shows none of them read offset 0x34,
and a hardware test forcing it to ``0xffffffff`` still failed — it is not an
enforced integrity word.
"""

import hashlib
import hmac
import struct

# Global Spike 2 SIDX manifest HMAC-SHA1 key (16 bytes).
SIDX_KEY = bytes.fromhex("8e1f5543c2f54a11673a282a2f87c006")

# Per-format record payload field offsets: ``tag -> (hmac_off, md5_off)``.  Both
# carry a 20-byte HMAC-SHA1(K, file) then a 16-byte MD5(file), just at different
# offsets within the record's payload.  Verified 300/300 on real cards of each
# format (Led Zeppelin = FI64, TMNT = FINF).
_FORMATS = {"FI64": (37, 57), "FINF": (21, 41)}
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
    """Parse a ``.sidx`` into ``{path: payload_offset}`` + header CRC + format.

    Records follow the ``STRS`` path block, each ``<tag>`` + u32 len + payload,
    where ``<tag>`` is ``FI64`` or ``FINF`` (one format per manifest); record *i*
    belongs to path *i*.  Paths have no leading slash (e.g.
    ``led_zeppelin_pro/image.bin``).  Returns ``({}, None, None)`` if it isn't a
    recognised sidx.  The returned ``fmt`` ("FI64"/"FINF") selects the digest
    offsets for :func:`record_field_writes`.
    """
    si = data.find(b"STRS")
    if si < 0 or len(data) < 0x38:
        return {}, None, None
    strs_len = struct.unpack_from("<I", data, si + 4)[0]
    paths = [p for p in data[si + 8:si + 8 + strs_len].split(b"\x00") if p]
    pos = si + 8 + strs_len
    # Every record in a manifest shares one tag — read it from the first record.
    tag = data[pos:pos + 4].decode("latin1")
    if tag not in _FORMATS:
        return {}, None, None
    tag_b = tag.encode("latin1")
    payload_offs = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == tag_b:
        ln = struct.unpack_from("<I", data, pos + 4)[0]
        payload_offs.append(pos + 8)
        pos += 8 + ln
    recs = {paths[i].decode("latin1"): payload_offs[i]
            for i in range(min(len(paths), len(payload_offs)))}
    hdr_crc = struct.unpack_from("<I", data, 0x34)[0]
    return recs, hdr_crc, tag


def digests(data):
    """``(HMAC-SHA1(K, data), MD5(data))`` for an in-memory file."""
    return (hmac.new(SIDX_KEY, data, hashlib.sha1).digest(),
            hashlib.md5(data).digest())


def record_field_writes(payload_off, hmac_digest, md5_digest, fmt="FI64"):
    """Sidx-file-relative ``[(offset, bytes), ...]`` to write one record's
    HMAC + MD5 for format *fmt* ("FI64"/"FINF").  The caller maps these through
    the sidx inode to disk."""
    hmac_off, md5_off = _FORMATS.get(fmt, _FORMATS["FI64"])
    return [(payload_off + hmac_off, hmac_digest),
            (payload_off + md5_off, md5_digest)]
