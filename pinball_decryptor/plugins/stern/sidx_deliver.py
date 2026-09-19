"""Put a file the card never had ONTO a card, indexed so ``spk`` accepts it.

:mod:`.sidx_append` makes the manifest; this delivers both halves together, which is
the part no existing caller does.

WHY IT CANNOT REUSE THE EXISTING ROUTE.  Every write today is size-neutral for the
manifest itself - ``explorer._resize_file`` says so in as many words: *".sidx itself
keeps its length, so its own record fields are still patchable at raw disk offsets."*
Appending a record makes the manifest LONGER, so it stops being patchable in place and
becomes a copy job of its own.  Both files therefore go through the ext4 driver in ONE
pass, and everything cached about either of them is stale afterwards: the copy
reallocates blocks, so a reader held across it would read the old extents.

Order matters and is deliberate.  The asset and the manifest are shipped together, so
a failure leaves either both or neither - never a manifest indexing a file that is not
there (the failure mode ``ext4_grow.grow_files`` already warns about, where a card got
a rewritten ``.sidx`` for a firmware that never landed).
"""

import os
import tempfile

from . import sidx, sidx_append


class SidxDeliverError(Exception):
    """The card was not changed, or was changed only partly; the message says which."""


def plan_new_file(manifest_bytes, card_rel, src_path):
    """``(new_manifest_bytes, size)`` for indexing *card_rel* with *src_path*'s
    contents.  Pure: reads the source, touches no card.

    *card_rel* is the manifest-relative path (no leading slash), e.g.
    ``godzilla_pro/assets/lcd/ours/scene.radium``.
    """
    size = os.path.getsize(src_path)
    hm, md = sidx.digests_file(src_path)
    return sidx_append.append_record(manifest_bytes, card_rel, size, hm, md), size


def add_file(image_path, part_offset, reader_factory, card_rel, src_path,
             log=None, grow=None):
    """Write *src_path* onto the card as *card_rel* and index it.

    *reader_factory* returns a FRESH reader over the partition each time it is
    called - it is called twice, once to read the manifest and once to verify
    afterwards, because the copy moves blocks and a reader cannot span it.
    *grow* is the ``grow_files``-shaped callable to deliver with (injected so this
    is testable without an ext4 host).

    Returns ``(size, manifest_path)``.  Raises :class:`SidxDeliverError` without
    having touched the card whenever the manifest cannot take the record.
    """
    log = log or (lambda *a, **k: None)
    if grow is None:
        from ...core import ext4_grow
        grow = ext4_grow.grow_files

    reader = reader_factory()
    manifest_path, node = sidx.find_sidx(reader)
    if node is None:
        raise SidxDeliverError(
            "no /spk/index/*.sidx manifest on this card, so a new file could "
            "not be indexed and would fail SD validation")
    manifest = reader.read_file_bytes(node)

    try:
        new_manifest, size = plan_new_file(manifest, card_rel, src_path)
    except sidx_append.SidxAppendError as e:
        raise SidxDeliverError(str(e)) from e

    # Refuse before the copy, not after it: a half-delivered card is the one
    # outcome worth more than any amount of convenience here.
    bad = sidx_append.verify(new_manifest, expect_paths=[card_rel])
    if bad:
        raise SidxDeliverError(
            "the rewritten manifest would not be valid (%s); the card was not "
            "touched" % "; ".join(bad))

    staged = None
    try:
        fd, staged = tempfile.mkstemp(prefix="pad_sidx_", suffix=".sidx")
        with os.fdopen(fd, "wb") as f:
            f.write(new_manifest)
        jobs = [(card_rel, src_path), (manifest_path.lstrip("/"), staged)]
        log("Indexing %s (%d bytes) and rewriting the manifest..."
            % (card_rel, size), "info")
        n = grow(image_path, part_offset, jobs, log=log)
        if n != len(jobs):
            raise SidxDeliverError(
                "only %d of %d file(s) reached the card; it may now carry a "
                "manifest and asset that disagree - rebuild it from stock"
                % (n, len(jobs)))
    finally:
        if staged:
            try:
                os.unlink(staged)
            except OSError:
                pass

    # Verify through a FRESH reader: the copy reallocated blocks for both files.
    fresh = reader_factory()
    _p, node2 = sidx.find_sidx(fresh)
    if node2 is None:
        raise SidxDeliverError("the manifest vanished from the card after the copy")
    after = fresh.read_file_bytes(node2)
    bad = sidx_append.verify(after, expect_paths=[card_rel])
    if bad:
        raise SidxDeliverError(
            "the manifest on the card is not valid after the copy: %s"
            % "; ".join(bad))
    recs, _crc, fmt = sidx.parse_records(after)
    if card_rel not in recs:
        raise SidxDeliverError(
            "the manifest on the card has no record for %s after the copy"
            % card_rel)
    log("Indexed %s in the %s manifest (%d records now)."
        % (card_rel, fmt, len(recs)), "success")
    return size, manifest_path


def remove_file_record(manifest_bytes, card_rel):
    """The manifest with *card_rel*'s record removed - the inverse of
    :func:`plan_new_file`'s manifest half.

    One of item 129's acceptance clauses is that removing an added file restores
    the stock manifest EXACTLY, so the inverse belongs beside the appender rather
    than being re-derived by whoever needs it.
    """
    import struct

    recs, _crc, fmt = sidx.parse_records(manifest_bytes)
    if card_rel not in recs:
        raise sidx_append.SidxAppendError(
            "%s has no record to remove" % card_rel)
    paths_blk = manifest_bytes.find(b"STRS")
    strs_len = struct.unpack_from("<I", manifest_bytes, paths_blk + 4)[0]
    strs_end = paths_blk + 8 + strs_len
    paths = [p for p in manifest_bytes[paths_blk + 8:strs_end].split(b"\x00") if p]
    want = card_rel.encode("latin1")
    if paths[-1] != want:
        raise sidx_append.SidxAppendError(
            "only the LAST record can be removed this way (%s is not last); "
            "record i belongs to path i, so removing from the middle would "
            "re-point every record after it" % card_rel)

    plen = sidx_append._PAYLOAD_LEN[fmt]
    size_pack, size_off = sidx._SIZE_FIELDS[fmt][0], sidx._SIZE_FIELDS[fmt][1]
    last_po = recs[card_rel]
    size = struct.unpack_from(size_pack, manifest_bytes, last_po + size_off)[0]
    rec_end = len(manifest_bytes) - len(sidx_append.FEND)

    out = bytearray()
    out += manifest_bytes[:paths_blk + 4]
    out += struct.pack("<I", strs_len - (len(want) + 1))
    out += manifest_bytes[paths_blk + 8:strs_end - (len(want) + 1)]
    out += manifest_bytes[strs_end:rec_end - (8 + plen)]
    out += sidx_append.FEND
    struct.pack_into("<I", out, 0x30,
                     struct.unpack_from("<I", manifest_bytes, 0x30)[0] - 1)
    struct.pack_into("<I", out, 0x04, len(out) - 8)
    total = sidx_append.size_total(manifest_bytes)
    if total is not None:
        sz = out.find(b"SZ64")
        if sz >= 0:
            struct.pack_into("<Q", out, sz + 8, total - size)
        else:
            struct.pack_into("<I", out, 0x34, total - size)
    return bytes(out)
