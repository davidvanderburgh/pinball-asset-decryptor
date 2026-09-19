"""Append a record to a Spike 2 ``.sidx`` manifest: index a file the card never had.

:mod:`.sidx` can REFRESH a record that already exists, which is all a size-neutral
Write ever needs.  A file that was never on the card has no record at all, and Stern's
``spk`` fails SD validation on an unindexed file, so adding one is the foundation
under a mode's own audio, screen and video.

THE CONTAINER IS A SEQUENCE OF TAGGED BLOCKS, NOT A FIXED LAYOUT.  This matters more
than anything else here.  A 48-byte header, then ``<tag><u32 len><body>`` blocks, then
a ``FEND`` trailer::

    0x00  'SIDX'
    0x04  u32   payload length = filesize - 8   (i.e. up to the FEND trailer)
    0x08  the package name, NUL-padded
    0x30  u32   record count (== the number of paths)
    0x34  u32   FI64: 0xffffffff        FINF: the size total (see below)
    0x38  the first block
    ...   'STRS' <len> NUL-separated paths, no leading slash
    ...   <tag> <len> <payload>  x count, one per path, same order
    end   'FEND' + 4 zero bytes

Godzilla (FI64) has an ``SZ64`` block at 0x38 and ``STRS`` at 0x48; Deadpool (FINF)
has ``STRS`` at 0x38 and no ``SZ64`` at all.  **Anything that indexes 0x38 or 0x48 is
reading one title's accident.**

THE SIZE TOTAL, and why the two formats differ.  Every manifest records the sum of
every indexed file's size, but stores it in its format's own place:

  * ``FI64`` -> an ``SZ64`` block, u64.  Its totals run 4.5-7.8 GB on real cards,
    which would not fit in a u32 at all - that is the reason for the split.
  * ``FINF`` -> header word ``0x34``, u32.  (Documented elsewhere as "an unenforced
    integrity word"; that is true of FI64 cards, where it is 0xffffffff, and wrong
    for FINF, where it carries this total.)

So a FINF manifest whose total would exceed 0xFFFFFFFF cannot be represented, and this
REFUSES rather than wrapping.  Real FINF headroom is 1.2-3.2 GB.

Verified across 14 cards, 7 of each format, 224 to 9704 records: ``0x04`` is always
filesize-8, ``0x30`` always equals both the path count and the record count, the
trailer is always ``FEND`` + 4 zeros, the payload length is uniform within a manifest
(80 FI64 / 60 FINF), and the size total always matches the sum of the records.
"""

import struct

from . import sidx

#: The trailer every manifest ends with.
FEND = b"FEND" + b"\x00" * 4
#: Payload length per record format, uniform within a manifest.
_PAYLOAD_LEN = {"FI64": 80, "FINF": 60}
#: Where the size total lives, per format.
_U32_MAX = 0xFFFFFFFF


class SidxAppendError(Exception):
    """The manifest cannot take this record, and nothing has been written."""


def _blocks(data):
    """``[(tag, offset, length)]`` for each block from 0x38 up to ``FEND``.

    Walks by tag rather than by offset, because the block ORDER differs between
    titles (FI64 carries SZ64 before STRS, FINF has no SZ64).  A run of record
    blocks is returned as one entry using the first record's tag.
    """
    out = []
    pos = 0x38
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        if tag == b"FEND":
            out.append((tag, pos, len(data) - pos))
            break
        ln = struct.unpack_from("<I", data, pos + 4)[0]
        if tag in (b"FI64", b"FINF"):
            start, n = pos, 0
            while pos + 8 <= len(data) and data[pos:pos + 4] == tag:
                rl = struct.unpack_from("<I", data, pos + 4)[0]
                pos += 8 + rl
                n += 1
            out.append((tag, start, pos - start))
            continue
        out.append((tag, pos, 8 + ln))
        pos += 8 + ln
    return out


def _record_size(payload, fmt):
    off = sidx._SIZE_FIELDS[fmt][1]
    pack = sidx._SIZE_FIELDS[fmt][0]
    return struct.unpack_from(pack, payload, off)[0]


def size_total(data):
    """The manifest's stored total of every indexed file's size, or ``None``.

    FI64 keeps it in an ``SZ64`` block (u64); FINF in header word 0x34 (u32).
    """
    recs, _crc, fmt = sidx.parse_records(data)
    if not recs:
        return None
    si = data.find(b"SZ64")
    if si >= 0:
        return struct.unpack_from("<Q", data, si + 8)[0]
    return struct.unpack_from("<I", data, 0x34)[0]


def build_record(payload_len, size, hmac_digest, md5_digest, fmt, template=None):
    """One record payload for a NEW file.

    *template* is an existing record's payload to copy the non-geometry bytes from;
    without one the payload is zero-filled apart from the fields we know.  Copying a
    template is the safer default: a real record carries fields this project has not
    mapped, and zeroing them is a guess, whereas copying a sibling's is at least a
    value the card already contains.
    """
    payload = bytearray(template[:payload_len] if template else payload_len)
    if len(payload) < payload_len:
        payload.extend(b"\x00" * (payload_len - len(payload)))
    pack, *size_offs = sidx._SIZE_FIELDS[fmt]
    if struct.calcsize(pack) == 4 and size > _U32_MAX:
        raise SidxAppendError(
            "%s records store a 32-bit file size; %d does not fit" % (fmt, size))
    for off in size_offs:
        struct.pack_into(pack, payload, off, size)
    hmac_off, md5_off = sidx._FORMATS[fmt]
    payload[hmac_off:hmac_off + sidx._HMAC_LEN] = hmac_digest
    payload[md5_off:md5_off + sidx._MD5_LEN] = md5_digest
    return bytes(payload)


def append_record(data, path, size, hmac_digest, md5_digest):
    """A NEW ``.sidx`` with *path* indexed, as bytes.  Never mutates *data*.

    *path* is the manifest-relative path with no leading slash (e.g.
    ``godzilla_pro/assets/lcd/ours/scene.radium``).  Raises
    :class:`SidxAppendError` rather than producing a manifest the card would
    reject.
    """
    recs, _crc, fmt = sidx.parse_records(data)
    if not recs:
        raise SidxAppendError("not a recognised .sidx manifest")
    if path in recs:
        raise SidxAppendError(
            "%s already has a record; refresh it instead of appending" % path)
    if b"\x00" in path.encode("latin1"):
        raise SidxAppendError("a manifest path cannot contain a NUL")
    if not data.endswith(FEND):
        raise SidxAppendError("manifest does not end with the FEND trailer")

    payload_len = _PAYLOAD_LEN[fmt]
    si = data.find(b"STRS")
    strs_len = struct.unpack_from("<I", data, si + 4)[0]
    strs_end = si + 8 + strs_len
    rec_end = len(data) - len(FEND)

    # One template record, so the bytes this project has not mapped carry a value
    # the card already contains rather than a guess.
    template = data[strs_end + 8:strs_end + 8 + payload_len]

    new_path = path.encode("latin1") + b"\x00"
    new_payload = build_record(payload_len, size, hmac_digest, md5_digest, fmt,
                               template=template)
    new_record = fmt.encode("latin1") + struct.pack("<I", payload_len) + new_payload

    out = bytearray()
    out += data[:si + 4]                                   # header + 'STRS'
    out += struct.pack("<I", strs_len + len(new_path))     # grown STRS length
    out += data[si + 8:strs_end]                           # the existing paths
    out += new_path                                        # ours, last
    out += data[strs_end:rec_end]                          # every existing record
    out += new_record                                      # ours, last
    out += FEND

    count = struct.unpack_from("<I", data, 0x30)[0] + 1
    struct.pack_into("<I", out, 0x30, count)
    struct.pack_into("<I", out, 0x04, len(out) - 8)

    total = size_total(data)
    if total is not None:
        new_total = total + size
        sz = out.find(b"SZ64")
        if sz >= 0:
            struct.pack_into("<Q", out, sz + 8, new_total)
        else:
            if new_total > _U32_MAX:
                raise SidxAppendError(
                    "this %s manifest stores the size total in a 32-bit header "
                    "word; adding %d bytes would overflow it (%d > %d)"
                    % (fmt, size, new_total, _U32_MAX))
            struct.pack_into("<I", out, 0x34, new_total)
    return bytes(out)


def append_file_record(data, path, file_path):
    """:func:`append_record` with the size and both digests taken from a file."""
    import os
    hm, md = sidx.digests_file(file_path)
    return append_record(data, path, os.path.getsize(file_path), hm, md)


def verify(data, expect_paths=None):
    """Check a manifest against every invariant measured on real cards.

    Returns ``[]`` when it holds, else a list of complaints.  Used as the gate
    before a manifest is written to a card, and by the tests.
    """
    bad = []
    if data[0:4] != b"SIDX":
        return ["no SIDX magic"]
    if not data.endswith(FEND):
        bad.append("does not end with the FEND trailer")
    w04 = struct.unpack_from("<I", data, 4)[0]
    if w04 != len(data) - 8:
        bad.append("0x04 is %d, expected filesize-8 = %d" % (w04, len(data) - 8))
    recs, _crc, fmt = sidx.parse_records(data)
    if not recs:
        return bad + ["records do not parse"]
    si = data.find(b"STRS")
    strs_len = struct.unpack_from("<I", data, si + 4)[0]
    paths = [p for p in data[si + 8:si + 8 + strs_len].split(b"\x00") if p]
    count = struct.unpack_from("<I", data, 0x30)[0]
    if count != len(paths):
        bad.append("0x30 is %d, but STRS holds %d paths" % (count, len(paths)))
    if count != len(recs):
        bad.append("0x30 is %d, but there are %d records" % (count, len(recs)))
    # the size total
    pos = si + 8 + strs_len
    tag = fmt.encode("latin1")
    total = 0
    while pos + 8 <= len(data) and data[pos:pos + 4] == tag:
        rl = struct.unpack_from("<I", data, pos + 4)[0]
        total += _record_size(data[pos + 8:pos + 8 + rl], fmt)
        pos += 8 + rl
    stored = size_total(data)
    if stored is not None and stored != total:
        bad.append("size total is %d, records sum to %d" % (stored, total))
    if expect_paths is not None:
        missing = [p for p in expect_paths if p not in recs]
        if missing:
            bad.append("missing record(s): %s" % ", ".join(missing[:4]))
    return bad
