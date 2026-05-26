"""RSCC container decoder for BOF May 2026+ PCK files.

BOF's May 2026 firmware ships a Godot 4.5.2 binary that no longer uses
the stock Godot PCK format end-to-end.  The PCK section in the binary
has been thoroughly customised:

  - PCK magic ``GDPC`` renamed to ``GBOF`` (handled by pipeline.py)
  - ``PACK_DIR_ENCRYPTED`` flag bit set as a tripwire (no actual AES)
  - Font resources stored in a custom ``RSCC`` Zstd container
  - Other files (textures, audio, scripts, scenes) stored as raw bytes
    with .import sidecars inline immediately after each file's data
  - No traditional Godot file directory at the start; addressing is
    sequential (file → its .import sidecar → next file → ...)

This module handles the ``RSCC`` layer.  Full PCK extraction is a
larger project tracked separately; see memory entry
``reference_bof_may2026_pck_format``.

RSCC container layout (40+ confirmed instances in Dune May code):

    offset  size   field
    ------  ----   -----
    0       4      magic ``RSCC``  (b'RSCC' = 0x43435352 LE)
    4       4      version (always 2 observed)
    8       4      uncompressed block size (always 4096 observed)
    12      4      total uncompressed size (sum of all blocks)
    16      4*N    per-block compressed sizes (N = ceil(total/blk))
    16+4*N  ...    N Zstd frames, back-to-back

Decompressing yields a standard Godot 4 binary resource file (one
RSRC-magic blob per RSCC container), e.g. a FontFile resource for an
imported .ttf/.otf font.  Each RSCC blob in a BOF PCK corresponds to
exactly one font; non-font assets bypass RSCC entirely.
"""

import math
import struct


RSCC_MAGIC = b"RSCC"
RSCC_VERSION = 2
RSCC_BLOCK_SIZE = 4096
RSCC_HEADER_SIZE = 16  # magic + version + blk_size + total_uncompressed


class RsccError(ValueError):
    """Raised on malformed or unsupported RSCC containers."""


def is_rscc_at(buf, offset=0):
    """Return True if a real RSCC container starts at *offset* in *buf*.

    The bytes ``b'RSCC'`` appear ~50 times incidentally inside Zstd
    frames (high-entropy data); we filter those by also checking the
    version + block size fields.
    """
    if len(buf) - offset < RSCC_HEADER_SIZE:
        return False
    if buf[offset:offset + 4] != RSCC_MAGIC:
        return False
    version = int.from_bytes(buf[offset + 4:offset + 8], "little")
    blk_size = int.from_bytes(buf[offset + 8:offset + 12], "little")
    return version == RSCC_VERSION and blk_size == RSCC_BLOCK_SIZE


def parse_header(buf, offset=0):
    """Parse the RSCC container header at *offset*.  Returns a dict with
    ``version``, ``block_size``, ``total_uncompressed``, ``num_blocks``,
    ``block_sizes`` (list[int] of compressed sizes per block),
    ``data_offset`` (offset of first Zstd frame), and ``container_size``
    (total bytes consumed by this RSCC container)."""
    if not is_rscc_at(buf, offset):
        raise RsccError(f"No valid RSCC container at offset {offset}")

    version = int.from_bytes(buf[offset + 4:offset + 8], "little")
    blk_size = int.from_bytes(buf[offset + 8:offset + 12], "little")
    total_unc = int.from_bytes(buf[offset + 12:offset + 16], "little")
    num_blocks = math.ceil(total_unc / blk_size) if blk_size else 0

    sizes_off = offset + RSCC_HEADER_SIZE
    block_sizes_end = sizes_off + 4 * num_blocks
    if block_sizes_end > len(buf):
        raise RsccError(
            f"RSCC@{offset}: block-size table extends past buffer end")
    block_sizes = list(struct.unpack(
        f"<{num_blocks}I", buf[sizes_off:block_sizes_end]))

    total_compressed = sum(block_sizes)
    container_size = RSCC_HEADER_SIZE + 4 * num_blocks + total_compressed

    return {
        "version": version,
        "block_size": blk_size,
        "total_uncompressed": total_unc,
        "num_blocks": num_blocks,
        "block_sizes": block_sizes,
        "data_offset": block_sizes_end,
        "container_size": container_size,
    }


def decompress(buf, offset=0):
    """Decompress an RSCC container at *offset* in *buf*.

    Returns ``(payload_bytes, container_size)`` so the caller can advance
    past the consumed RSCC bytes to find the next structure (typically an
    inline .import sidecar at ``offset + container_size``).
    """
    # Late import — zstandard is an optional dep here; if a user only ever
    # runs BOF pre-May code (no RSCC blobs), they shouldn't be forced to
    # have it installed.  The Extract pipeline will surface a clear
    # "install zstandard" error if/when it's actually needed.
    import zstandard

    hdr = parse_header(buf, offset)

    dctx = zstandard.ZstdDecompressor()
    out = bytearray()
    p = hdr["data_offset"]
    for sz in hdr["block_sizes"]:
        frame = buf[p:p + sz]
        if len(frame) != sz:
            raise RsccError(
                f"RSCC@{offset}: short read on Zstd frame (got {len(frame)}, "
                f"want {sz})")
        try:
            block = dctx.decompress(
                frame, max_output_size=hdr["block_size"] + 1024)
        except zstandard.ZstdError as e:
            raise RsccError(
                f"RSCC@{offset}: Zstd decompress failed at block "
                f"{p - hdr['data_offset']}: {e}")
        out.extend(block)
        p += sz

    if len(out) != hdr["total_uncompressed"]:
        raise RsccError(
            f"RSCC@{offset}: decompressed size mismatch "
            f"(got {len(out)}, header says {hdr['total_uncompressed']})")

    return bytes(out), hdr["container_size"]


def scan(buf, start=0, end=None):
    """Yield ``(offset, header_dict)`` for every real RSCC container in
    ``buf[start:end]``.  Spurious ``RSCC`` byte matches inside compressed
    Zstd payloads are filtered by ``is_rscc_at``'s version/block-size
    check.
    """
    if end is None:
        end = len(buf)
    pos = start
    while pos < end - RSCC_HEADER_SIZE:
        idx = buf.find(RSCC_MAGIC, pos, end)
        if idx == -1:
            return
        if is_rscc_at(buf, idx):
            try:
                hdr = parse_header(buf, idx)
                yield idx, hdr
                pos = idx + hdr["container_size"]
                continue
            except RsccError:
                pass
        pos = idx + 1
