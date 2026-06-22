r"""Sector-aligned raw-device I/O for the Spike 2 Direct-SD path.

The file-based Extract/Write open the card *image* with ``open(path, "rb")``;
Direct-SD instead points the same pure-Python ext4 reader / size-neutral patcher
at the **physical card** (``\\.\PHYSICALDRIVEn`` on Windows, ``/dev/sdX`` on
Linux/macOS).  Block devices require every read/write to be aligned to the
device's logical sector size, so a plain ``open()`` (which issues arbitrary
offsets/lengths) fails.  :class:`RawDeviceFile` presents the usual
byte-addressable ``seek``/``read``/``write`` interface that ``Ext4Reader`` and
``engine`` expect, doing sector-aligned reads — and read-modify-write for
unaligned writes — underneath.

Why this works for size-neutral writes without taking the disk offline: every
byte we patch lives in the **ext4** data partition, which Windows has no
filesystem driver for, so it is not a mounted volume.  Windows blocks raw writes
only to sectors that belong to a *mounted* volume; the (FAT) boot partition we
never touch.  So an Administrator handle can patch the ext sectors in place.

Reading a physical drive always needs Administrator (Windows) / root (POSIX);
the GUI gates the Direct-SD buttons on that before these are reached.
"""

import os
import sys

# Open block devices in binary mode; O_BINARY only exists on Windows.
_O_BINARY = getattr(os, "O_BINARY", 0)
# Cap each underlying device read/write at 8 MB (a sector multiple) so a single
# os.read/os.write stays well within driver limits while still streaming fast.
_IO_CHUNK = 8 << 20


def is_device_path(path):
    r"""True if *path* names a raw physical device rather than a file.

    Windows: ``\\.\PHYSICALDRIVEn``.  POSIX: anything under ``/dev/``.
    """
    if not path:
        return False
    p = path.strip()
    if sys.platform == "win32":
        return p.upper().startswith("\\\\.\\PHYSICALDRIVE")
    return p.startswith("/dev/")


class RawDeviceFile:
    """A seekable byte stream over a raw block device with aligned underlying I/O.

    ``writable=False`` opens read-only (Extract); ``writable=True`` opens
    read-write for the in-place size-neutral patch (Write).  ``sector`` may be
    forced (used by tests against a regular file); otherwise it is probed.
    """

    def __init__(self, path, writable=False, sector=None):
        self.path = path
        self.writable = writable
        flags = (os.O_RDWR if writable else os.O_RDONLY) | _O_BINARY
        self.fd = os.open(path, flags)
        try:
            self.sector = sector or self._probe_sector()
            self._size = self._probe_size()
        except Exception:
            os.close(self.fd)
            raise
        self._pos = 0

    # ---- probing -----------------------------------------------------------
    def _probe_sector(self):
        """Logical sector size: the smallest power-of-two read that succeeds.

        A block device rejects reads whose length isn't a multiple of its
        logical sector size, so a successful 512-byte read at offset 0 means
        512; otherwise 4096.  (Regular files accept any length → 512.)"""
        for s in (512, 4096):
            try:
                os.lseek(self.fd, 0, os.SEEK_SET)
                if len(os.read(self.fd, s)) == s:
                    return s
            except OSError:
                continue
        return 512

    def _probe_size(self):
        """Device byte length (a sector multiple), or ``None`` if unknown."""
        try:
            end = os.lseek(self.fd, 0, os.SEEK_END)
            os.lseek(self.fd, 0, os.SEEK_SET)
            return end if end and end > 0 else None
        except OSError:
            return None

    # ---- stream interface --------------------------------------------------
    def seek(self, pos, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._pos = pos
        elif whence == os.SEEK_CUR:
            self._pos += pos
        elif whence == os.SEEK_END:
            if self._size is None:
                raise OSError("device size unknown; SEEK_END unsupported")
            self._pos = self._size + pos
        else:
            raise ValueError("invalid whence: %r" % (whence,))
        return self._pos

    def tell(self):
        return self._pos

    def _aligned_read(self, start, length):
        """Return exactly the bytes ``[start, start+length)`` (start/length need
        not be aligned), reading only whole sectors from the device."""
        if length <= 0:
            return b""
        sec = self.sector
        a_start = (start // sec) * sec
        a_end = ((start + length + sec - 1) // sec) * sec
        if self._size is not None:
            a_end = min(a_end, self._size)
        if a_end <= a_start:
            return b""
        os.lseek(self.fd, a_start, os.SEEK_SET)
        buf = bytearray()
        want = a_end - a_start
        while len(buf) < want:
            chunk = os.read(self.fd, min(_IO_CHUNK, want - len(buf)))
            if not chunk:
                break
            buf += chunk
        lo = start - a_start
        return bytes(buf[lo:lo + length])

    def read(self, n=-1):
        if n is None or n < 0:
            if self._size is None:
                raise OSError("read-to-EOF unsupported on this device")
            n = max(0, self._size - self._pos)
        data = self._aligned_read(self._pos, n)
        self._pos += len(data)
        return data

    def write(self, data):
        """Write *data* at the current position via read-modify-write of the
        sectors it touches (so an arbitrary-offset, arbitrary-length patch lands
        without violating the device's sector alignment)."""
        if not self.writable:
            raise OSError("device opened read-only")
        if not data:
            return 0
        sec = self.sector
        start = self._pos
        length = len(data)
        a_start = (start // sec) * sec
        a_end = ((start + length + sec - 1) // sec) * sec
        # Never write past the device end: a block device's length is a sector
        # multiple, so clamping keeps the region sector-aligned; for a backing
        # file it just avoids extending it past its original size.
        if self._size is not None:
            a_end = min(a_end, self._size)
        region = bytearray(self._aligned_read(a_start, a_end - a_start))
        if len(region) < (a_end - a_start):           # extend (tail / new file)
            region += bytes((a_end - a_start) - len(region))
        lo = start - a_start
        region[lo:lo + length] = data
        os.lseek(self.fd, a_start, os.SEEK_SET)
        mv = memoryview(region)
        off = 0
        while off < len(region):
            off += os.write(self.fd, mv[off:off + min(_IO_CHUNK, len(region) - off)])
        self._pos += length
        return length

    def flush(self):
        try:
            os.fsync(self.fd)
        except OSError:
            pass

    def fileno(self):
        return self.fd

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def read_mbr(device_path):
    r"""Read the first 512 bytes (the MBR) of a raw device, sector-aligned.

    Returns the bytes (possibly empty on failure).  Used to confirm the Spike 2
    partition signature and locate the ext partitions before extracting/writing.
    """
    try:
        with RawDeviceFile(device_path, writable=False) as f:
            return f.read(512)
    except OSError:
        return b""
