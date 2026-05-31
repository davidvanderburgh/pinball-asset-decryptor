"""Pure-Python reader for partclone **image format v2** (``"0002"``).

Clonezilla saves each partition with ``partclone`` in its native format —
a header describing the filesystem, a used-block bitmap, and then only the
*used* blocks' data (with a CRC32 interleaved every N blocks).  This module
reconstructs the original raw partition image from that stream, without
needing the ``partclone`` binary installed.

It reads from any binary stream (e.g. a ``zstandard`` decompressor's
``stream_reader``), so a Clonezilla ``*.ext4-ptcl-img.zst`` can be restored
on the fly with no intermediate full-size temp file on the input side.

On-disk layout (all integers little-endian), reverse-engineered against
partclone 0.3.36 / Clonezilla output and cross-checked with the upstream
``image_desc_v2`` struct:

    image_head_v2          (36 bytes)
      magic[16]            "partclone-image\0"
      ptc_version[14]      e.g. "0.3.36"
      version[4]           "0002"
      endianess  uint16    0xC0DE little-endian
    file_system_info_v2    (52 bytes)
      fs[16]               e.g. "EXTFS\0..."
      device_size  u64
      totalblock   u64
      superBlockUsedBlocks u64
      usedblocks   u64
      block_size   u32
    image_options_v2       (18 bytes)
      feature_size u32, image_version u16, cpu_bits u16,
      checksum_mode u16, checksum_size u16, blocks_per_checksum u32,
      reseed_checksum u8, bitmap_mode u8
    crc                    (4 bytes)   — CRC of the header

    bitmap                 (ceil(totalblock/8) bytes, 1 bit per block, LSB first)
    bitmap CRC             (checksum_size bytes)

    data                   for each set bit in block order: block_size bytes,
                           with a checksum_size CRC after every
                           blocks_per_checksum data blocks written.
"""

import struct

IMAGE_MAGIC = b"partclone-image"
ENDIAN_MAGIC = 0xC0DE

_HEAD_SIZE = 36
_FSINFO_SIZE = 52
_OPTIONS_SIZE = 18
_DESC_CRC = 4
_HEADER_SIZE = _HEAD_SIZE + _FSINFO_SIZE + _OPTIONS_SIZE + _DESC_CRC  # 110


class PartcloneError(Exception):
    pass


class PartcloneImage:
    """Parsed partclone v2 header plus a streaming restore."""

    def __init__(self, fs, device_size, totalblock, usedblocks, block_size,
                 checksum_size, blocks_per_checksum):
        self.fs = fs
        self.device_size = device_size
        self.totalblock = totalblock
        self.usedblocks = usedblocks
        self.block_size = block_size
        self.checksum_size = checksum_size
        self.blocks_per_checksum = blocks_per_checksum

    @classmethod
    def parse_header(cls, header):
        """Build a :class:`PartcloneImage` from the first 110 header bytes."""
        if len(header) < _HEADER_SIZE:
            raise PartcloneError(
                f"partclone header too short: {len(header)} < {_HEADER_SIZE}")
        if header[:15] != IMAGE_MAGIC:
            raise PartcloneError("Not a partclone image (bad magic)")
        version = header[30:34]
        if version != b"0002":
            raise PartcloneError(
                f"Unsupported partclone image version {version!r} "
                f"(only v2 '0002' is supported)")
        endian = struct.unpack_from("<H", header, 34)[0]
        if endian != ENDIAN_MAGIC:
            raise PartcloneError(
                f"Unsupported partclone endianness 0x{endian:04x} "
                f"(big-endian images are not supported)")
        fs = header[36:51].split(b"\0")[0].decode("latin1")
        device_size, totalblock, _sb_used, usedblocks = \
            struct.unpack_from("<4Q", header, 52)
        block_size = struct.unpack_from("<I", header, 84)[0]
        checksum_size = struct.unpack_from("<H", header, 98)[0]
        blocks_per_checksum = struct.unpack_from("<I", header, 100)[0]
        if block_size == 0 or totalblock == 0:
            raise PartcloneError("Invalid partclone geometry (zero block/total)")
        return cls(fs, device_size, totalblock, usedblocks, block_size,
                   checksum_size, blocks_per_checksum)

    @classmethod
    def from_stream(cls, stream):
        """Read and parse the header from *stream*, leaving it at the bitmap."""
        return cls.parse_header(_read_exact(stream, _HEADER_SIZE))

    @property
    def bitmap_bytes(self):
        return (self.totalblock + 7) // 8

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(self, stream, out, progress_cb=None, cancel_cb=None):
        """Reconstruct the raw partition from *stream* into *out*.

        *stream* must be positioned immediately after the 110-byte header
        (i.e. use :meth:`from_stream`).  *out* is a seekable binary file;
        unused blocks are left as holes (seek-over), so on a sparse-aware
        filesystem the output only consumes ~``usedblocks`` of real space.

        Returns the number of data blocks written (== ``usedblocks``).
        """
        bitmap = _read_exact(stream, self.bitmap_bytes)
        _read_exact(stream, self.checksum_size)  # bitmap CRC (not verified)

        bs = self.block_size
        bpc = self.blocks_per_checksum or 0
        csize = self.checksum_size
        total = self.totalblock

        written = 0
        since_crc = 0
        # Walk the bitmap byte-by-byte; bit i (LSB first) of byte b is block
        # b*8 + i.  Writing each used block at its absolute offset keeps the
        # output correctly positioned and lets unused blocks stay holes.
        for byte_idx in range(self.bitmap_bytes):
            bits = bitmap[byte_idx]
            if bits == 0:
                continue
            base = byte_idx * 8
            for i in range(8):
                if not (bits >> i) & 1:
                    continue
                block = base + i
                if block >= total:
                    break
                data = _read_exact(stream, bs)
                out.seek(block * bs)
                out.write(data)
                written += 1
                since_crc += 1
                if bpc and since_crc == bpc:
                    _read_exact(stream, csize)  # interleaved CRC (reseeded)
                    since_crc = 0
                    if progress_cb:
                        progress_cb(written, self.usedblocks)
            if cancel_cb and cancel_cb():
                raise PartcloneError("Restore cancelled.")

        # Pad the image out to the full device size so the trailing unused
        # blocks read back as zeros (and the ext4 size is correct).
        out.truncate(total * bs)
        if progress_cb:
            progress_cb(written, self.usedblocks)
        return written


def _read_exact(stream, n):
    """Read exactly *n* bytes from *stream* or raise PartcloneError."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise PartcloneError(
                f"Unexpected end of partclone stream "
                f"(wanted {n} bytes, got {n - remaining})")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks) if len(chunks) > 1 else chunks[0]


def restore_zst_fileobj(fileobj, out_path, progress_cb=None, cancel_cb=None,
                        log_cb=None):
    """Restore a zstd-compressed partclone image read from a binary stream.

    *fileobj* is any read()-able binary stream of the ``.zst`` bytes (e.g. a
    subprocess pipe), so the compressed image never has to be staged on
    disk.  Writes a sparse raw partition image to *out_path*; returns the
    :class:`PartcloneImage`.
    """
    import zstandard as zstd

    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    dctx = zstd.ZstdDecompressor()
    reader = dctx.stream_reader(fileobj)
    img = PartcloneImage.from_stream(reader)
    log(f"  partclone {img.fs} image: {img.totalblock} blocks x "
        f"{img.block_size} B = {img.device_size / (1024**3):.2f} GiB "
        f"({img.usedblocks} used)", "info")
    with open(out_path, "wb") as out:
        img.restore(reader, out, progress_cb=progress_cb, cancel_cb=cancel_cb)
    return img


def restore_zst(zst_path, out_path, progress_cb=None, cancel_cb=None,
                log_cb=None):
    """Decompress a ``*-ptcl-img.zst`` file and restore it to a raw image.

    Streams the zstd input (no full-size decompressed temp file) and writes
    a sparse raw partition image to *out_path*.  Returns the
    :class:`PartcloneImage`.
    """
    with open(zst_path, "rb") as zf:
        return restore_zst_fileobj(zf, out_path, progress_cb=progress_cb,
                                   cancel_cb=cancel_cb, log_cb=log_cb)
