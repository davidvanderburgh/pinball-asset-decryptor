"""Stern **SPKS** archive reader — the container inside a decrypted ``.spk``.

A Spike 3 update package (``.spk``) decrypts (LUKS2 -> ext4) to a single nested
file: a custom Stern **SPKS** archive that stores every shipped file verbatim
(uncompressed), indexed by name.  This module walks that index so files come
out by their real paths — videos, images, scenes AND the loose ``/mfs/sd/*.wav``
audio, which is why the ``.spk`` path is the one that yields audio directly.

Layout (little-endian), reverse-engineered + verified against real packages::

    header (20 bytes): "SPKS", 0xffffffff, 0x6a6f4697, version(u32), section_count(u32)
    then `section_count` sections, each:
        "SPK0", 0xffffffff, 8 bytes (counts/crc, unused here)
        "SIDX", u32, <section name, NUL-terminated> ... (padded)
        "STRS", size(u32), <NUL-separated path table>
        ("FINF", 60, <60-byte record>) * file_count     -- the index
        "FEND", u32 ; "SDAT", u32                        -- end-of-index / start-of-data
        <verbatim file data>                             -- files back to back

    FINF record (60 bytes): name_off(u32 into STRS), stored_size(u32),
        data_offset(u32, from the section's data base), uncomp_size(u32),
        mode(u32), then ~40 bytes of hashes (ignored).  stored==uncomp (no
        compression seen).

The index blocks after SPK0 are not uniformly ``tag+size+payload`` (SIDX's u32
is not its length), so the walk is structural: find ``STRS`` after ``SPK0``,
read the path table, read the contiguous ``FINF`` run, skip ``FEND``/``SDAT``,
and the data base is there.  The next section is found by scanning a small
window past the data region for the next ``SPK0``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SPKS_MAGIC = b"SPKS"
SPKS_MAGIC2 = 0x6A6F4697
_SPK0 = b"SPK0"
_STRS = b"STRS"
_SIDX = b"SIDX"
_FEND = b"FEND"
_SDAT = b"SDAT"
# Per-file index record.  Small sections use 32-bit ``FINF`` (60 bytes); the
# game section, whose data region is >4 GB, uses 64-bit ``FI64`` (80 bytes).
_FINF = b"FINF"
_FI64 = b"FI64"
_REC_LEN = {_FINF: 60, _FI64: 80}
_SCAN = 1 << 20          # window to find the next tag / section


def _decode_record(tag, rec):
    """Return (name_off, stored_size, data_offset, mode) from a FINF/FI64 body."""
    if tag == _FINF:
        name_off, stored, data_off, _uncomp, mode = struct.unpack_from(
            "<IIIII", rec, 0)
    else:  # FI64: name_off(u32), pad, stored(u64), data_off(u64), uncomp(u64), mode(u32)
        name_off = struct.unpack_from("<I", rec, 0)[0]
        stored, data_off, _uncomp = struct.unpack_from("<QQQ", rec, 8)
        mode = struct.unpack_from("<I", rec, 32)[0]
    return name_off, stored, data_off, mode


class SpksError(Exception):
    pass


@dataclass(frozen=True)
class SpksFile:
    section: str          # "spike", the game dir, ...
    path: str             # path within the section, e.g. "mfs/sd/0001.wav"
    offset: int           # absolute byte offset in the SPKS file
    size: int             # stored (== uncompressed) size
    mode: int             # unix mode


class SpksArchive:
    """Index of an SPKS archive over a random-access reader.

    *read* is ``read(offset, length) -> bytes`` (e.g. an
    :class:`~.ext4.Ext4Reader` file wrapped by :func:`ext4_file_reader`), and
    *size* the archive's total byte size.
    """

    def __init__(self, read, size):
        self._read = read
        self._size = size
        self.version = 0
        self.files: list[SpksFile] = []
        self._by_path: dict[str, SpksFile] = {}
        self._parse()

    # -- helpers -------------------------------------------------------------
    def _u32(self, off):
        return struct.unpack("<I", self._read(off, 4))[0]

    def _find(self, tag, start, limit=_SCAN):
        """Find *tag* at/after *start* within *limit* bytes; -1 if absent."""
        window = self._read(start, min(limit, max(0, self._size - start)))
        rel = window.find(tag)
        return start + rel if rel >= 0 else -1

    # -- parse ---------------------------------------------------------------
    def _parse(self):
        head = self._read(0, 20)
        if head[:4] != SPKS_MAGIC:
            raise SpksError("not an SPKS archive (magic %r)" % head[:4])
        magic2, self.version, nsec = struct.unpack_from("<III", head, 8)
        if magic2 != SPKS_MAGIC2:
            raise SpksError("bad SPKS magic2 0x%x" % magic2)

        pos = 20
        for _ in range(nsec):
            spk0 = self._find(_SPK0, pos, 64)
            if spk0 < 0:
                raise SpksError("SPK0 section header not found near %d" % pos)
            pos = self._parse_section(spk0)
        # stable, de-duplicated path -> file
        for fobj in self.files:
            self._by_path.setdefault(fobj.path, fobj)
            self._by_path.setdefault("%s/%s" % (fobj.section, fobj.path), fobj)

    def _parse_section(self, spk0):
        # section name from SIDX (right after SPK0 + sentinel + 8 bytes)
        sidx = self._find(_SIDX, spk0, 64)
        section = ""
        if sidx >= 0:
            nm = self._read(sidx + 8, 64)
            section = nm.split(b"\x00", 1)[0].decode("latin1", "replace")

        strs_pos = self._find(_STRS, spk0, _SCAN)
        if strs_pos < 0:
            raise SpksError("STRS table not found in section at %d" % spk0)
        strs_sz = self._u32(strs_pos + 4)
        strtab = self._read(strs_pos + 8, strs_sz)

        # contiguous run of per-file records (FINF or FI64), read in chunks
        rec_tag = self._read(strs_pos + 8 + strs_sz, 4)
        rec_len = _REC_LEN.get(rec_tag)
        fp = strs_pos + 8 + strs_sz
        records = []
        if rec_len:
            step = 8 + rec_len
            while True:
                chunk = self._read(fp, 256 * step)
                i = 0
                while i + step <= len(chunk) and chunk[i:i + 4] == rec_tag:
                    records.append(_decode_record(rec_tag, chunk[i + 8:i + step]))
                    i += step
                if i == 0:
                    break
                fp += i

        # End-of-index / start-of-data markers, then the data region.
        #   "FEND" tag(4)+size(4)            -- end of the index
        #   "SDAT" tag(4)+size(4)            -- start of data
        # When SDAT's size is the 0xffffffff sentinel (the 64-bit game
        # section), an 8-byte data-region header (CRC + version) follows before
        # the first file; when it is 0 (small sections) the data starts at once.
        data_base = fp
        if self._read(data_base, 4) == _FEND:
            data_base += 8
        if self._read(data_base, 4) == _SDAT:
            sdat_sz = struct.unpack("<I", self._read(data_base + 4, 4))[0]
            data_base += 8
            if sdat_sz == 0xFFFFFFFF:
                data_base += 8

        total = 0
        for noff, ssz, doff, mode in records:
            end = strtab.find(b"\x00", noff)
            name = strtab[noff:end if end >= 0 else None].decode("utf-8", "replace")
            self.files.append(SpksFile(section=section, path=name,
                                       offset=data_base + doff, size=ssz,
                                       mode=mode))
            total = max(total, doff + ssz)

        # next section: scan a small window past the data region for SPK0
        nxt = data_base + total
        found = self._find(_SPK0, nxt, 4096)
        return found if found >= 0 else self._size

    # -- access --------------------------------------------------------------
    def get(self, path):
        return self._by_path.get(path)

    def read_file(self, fobj, chunk=1 << 20):
        """Yield *fobj*'s bytes in chunks (verbatim, uncompressed)."""
        left = fobj.size
        off = fobj.offset
        while left > 0:
            n = min(chunk, left)
            data = self._read(off, n)
            if not data:
                break
            yield data
            off += len(data)
            left -= len(data)

    def extract(self, fobj, out_path, chunk=1 << 20):
        import os
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as o:
            for data in self.read_file(fobj, chunk):
                o.write(data)
        return fobj.size


def ext4_file_reader(ext, inode):
    """A ``read(offset, length)`` over one ext4 regular file, for SpksArchive."""
    def _read(off, n):
        if n <= 0:
            return b""
        return ext.read_range(inode, off, n)
    return _read
