"""Stern **Spike 3** SD-card support — partition map + on-the-fly LUKS decrypt.

Spike 3 is the Pi-4 (BCM2711) secure-boot generation.  A game SD card is an
**MBR**-partitioned image (not GPT):

    p1  type 0x0c  FAT32  (64 MB boot, PLAINTEXT — only signed, not encrypted)
    p2  type 0x83  LUKS2  rootfs
    p3  type 0x83  LUKS2  data (settings/NVRAM)
    p4  type 0x0f  extended  ──┐
    p5  type 0x83  LUKS2  connectivity   (logical, inside p4)
    p6  type 0x83  LUKS2  games/assets   (logical, inside p4 — the big one)

Every encrypted partition is a LUKS2 container (``aes-xts-plain64``) whose data
segment holds an ext4 filesystem.  The asset tree on **p6** uses the same
formats as Spike 2 (QuickTime/H.264 video, PNG, ``.radium``/``.sidx`` scenes,
WAV), so once a partition is decrypted the existing :mod:`.ext4` reader and the
Spike 2 asset extractors read it unchanged.

This module provides, in pure Python (no cryptsetup, no root, no hardware):
  * :func:`parse_partitions` — the full primary + logical (EBR chain) map, each
    entry flagged ``luks`` by reading its first bytes.
  * :func:`is_spike3_card` — structural detection (the boot/LUKS layout above).
  * :class:`DecryptingSegmentReader` — a seekable, read-only file-like over a
    LUKS data segment that decrypts the covering XTS sectors on demand (and
    caches them), so :class:`.ext4.Ext4Reader` can walk a multi-GB filesystem
    reading only the blocks it needs — never the whole 62 GB image.
  * :func:`open_partition_ext4` — resolve a named role (``"games"`` …) to its
    partition, read the LUKS2 header off the image, unlock it with a caller-
    supplied key, and return a ready :class:`.ext4.Ext4Reader`.

**Keys are never baked into this repo.**  The caller supplies them through a
:class:`.spike3_keys.Spike3KeySource` (a user keyfile / a decrypted rootfs they
own).  See :mod:`.spike3_keys`.
"""

from __future__ import annotations

import os
import struct

from . import ext4 as _ext4

# luks_otp lives outside the package (stern-spike-3/tools); import it by path so
# both the app and the bare-interpreter rigs can load this leaf module.
import importlib.util as _ilu

_SS = 512
LUKS2_MAGIC = (b"LUKS\xba\xbe", b"SKUL\xba\xbe")

_MBR_SIG = b"\x55\xaa"
_MBR_FAT = (0x0b, 0x0c, 0x0e, 0x06, 0x04, 0x01)
_MBR_LINUX = 0x83
_MBR_EXTENDED = (0x05, 0x0f)


# --------------------------------------------------------------------------
# luks_otp loader (repo tool, not a package module)
# --------------------------------------------------------------------------
_LUKS_OTP = None


def _luks_otp():
    """Import ``stern-spike-3/tools/luks_otp.py`` once and cache it."""
    global _LUKS_OTP
    if _LUKS_OTP is not None:
        return _LUKS_OTP
    # repo root is four parents up from this file:
    #   plugins/stern/spike3.py -> plugins/stern -> plugins -> pinball_decryptor -> <root>
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "stern-spike-3", "tools", "luks_otp.py")
    spec = _ilu.spec_from_file_location("luks_otp", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LUKS_OTP = mod
    return mod


# --------------------------------------------------------------------------
# Partition map (MBR primaries + EBR logical chain)
# --------------------------------------------------------------------------
def _read_at(f, lba, n):
    f.seek(lba * _SS)
    return f.read(n)


def _is_luks(f, start_lba):
    try:
        head = _read_at(f, start_lba, 6)
    except OSError:
        return False
    return head[:6] in LUKS2_MAGIC


def parse_partitions(fileobj):
    """Return the full partition list for an MBR disk image/open file.

    Each entry is a dict::

        {"index": 1-based disk order, "ptype": int, "start_lba": int,
         "sectors": int, "logical": bool, "luks": bool}

    Primaries come first (index 1..4, in table order), then logical partitions
    walked from the extended partition's EBR chain (index 5, 6, ...), matching
    Linux's p5/p6 numbering.
    """
    f = fileobj
    mbr = _read_at(f, 0, _SS)
    if len(mbr) < _SS or mbr[510:512] != _MBR_SIG:
        return []

    parts = []
    extended = None
    for i in range(4):
        e = mbr[446 + i * 16: 446 + i * 16 + 16]
        ptype = e[4]
        lba, sectors = struct.unpack_from("<II", e, 8)
        if ptype == 0 or sectors == 0:
            continue
        rec = {"index": i + 1, "ptype": ptype, "start_lba": lba,
               "sectors": sectors, "logical": False, "luks": False}
        rec["luks"] = _is_luks(f, lba) if ptype == _MBR_LINUX else False
        parts.append(rec)
        if ptype in _MBR_EXTENDED and extended is None:
            extended = lba

    # Walk the EBR chain for logical partitions (p5, p6, ...).
    if extended is not None:
        idx = 5
        ebr_lba = extended
        seen = set()
        while ebr_lba is not None and ebr_lba not in seen:
            seen.add(ebr_lba)
            ebr = _read_at(f, ebr_lba, _SS)
            if len(ebr) < _SS or ebr[510:512] != _MBR_SIG:
                break
            e0 = ebr[446:462]
            ptype = e0[4]
            rel_lba, sectors = struct.unpack_from("<II", e0, 8)
            if ptype != 0 and sectors > 0:
                start = ebr_lba + rel_lba
                rec = {"index": idx, "ptype": ptype, "start_lba": start,
                       "sectors": sectors, "logical": True, "luks": False}
                rec["luks"] = _is_luks(f, start) if ptype == _MBR_LINUX else False
                parts.append(rec)
                idx += 1
            # next EBR pointer (relative to the extended partition start)
            e1 = ebr[462:478]
            nptype = e1[4]
            next_rel, next_sectors = struct.unpack_from("<II", e1, 8)
            if nptype in _MBR_EXTENDED and next_sectors > 0:
                ebr_lba = extended + next_rel
            else:
                ebr_lba = None
    return parts


def parse_partitions_path(path):
    with open(path, "rb") as f:
        return parse_partitions(f)


def is_spike3_card_parts(parts):
    """True if *parts* carry the Stern Spike 3 signature: a 64 MB FAT boot
    partition (type 0x0c) at LBA 1, and a LUKS2 Linux partition (p2) starting
    at LBA 131073.  This boot/first-LUKS layout is fixed by the firmware across
    titles and card sizes, and the LUKS magic keeps it from grabbing a generic
    Linux SBC image."""
    if len(parts) < 2:
        return False
    p1 = parts[0]
    p2 = parts[1]
    return (p1["ptype"] in _MBR_FAT and p1["start_lba"] == 1
            and p1["sectors"] == 131072
            and p2["ptype"] == _MBR_LINUX and p2["start_lba"] == 131073
            and p2["luks"])


def is_spike3_card(path):
    """Structural Spike 3 detection over a file path (reads only a few sectors)."""
    try:
        with open(path, "rb") as f:
            return is_spike3_card_parts(parse_partitions(f))
    except (OSError, ValueError):
        return False


# Disk-order role of each LUKS partition on a Spike 3 card.  The games/assets
# partition is also, by a wide margin, the largest LUKS partition, so
# :func:`partition_for_role` falls back to "largest LUKS" if the fixed order
# ever shifts.
_ROLE_BY_INDEX = {2: "rootfs", 3: "data", 5: "connectivity", 6: "games"}


def luks_partitions(parts):
    return [p for p in parts if p.get("luks")]


def partition_for_role(parts, role):
    """Return the partition dict for a role name, or None.

    Prefers the fixed disk-order mapping; for ``"games"`` falls back to the
    largest LUKS partition (what the games/assets volume always is)."""
    for p in parts:
        if p.get("luks") and _ROLE_BY_INDEX.get(p["index"]) == role:
            return p
    if role == "games":
        luks = luks_partitions(parts)
        return max(luks, key=lambda p: p["sectors"]) if luks else None
    return None


# --------------------------------------------------------------------------
# On-the-fly decrypting reader over a LUKS data segment
# --------------------------------------------------------------------------
class DecryptingSegmentReader:
    """A seekable, read-only file-like over a LUKS ``aes-xts-plain64`` data
    segment.  ``read``/``seek``/``tell`` operate in the segment's PLAINTEXT
    coordinate space (offset 0 == first plaintext byte of the filesystem);
    covering XTS sectors are decrypted on demand and cached.

    Hand it straight to :class:`.ext4.Ext4Reader` with ``part_offset=0`` and
    ``part_size=`` :attr:`size`.
    """

    def __init__(self, fileobj, part_base_lba, header, master_key,
                 segment_idx="0", cache_sectors=4096):
        otp = _luks_otp()
        seg = header.segment(segment_idx)
        enc = seg["encryption"]
        if not enc.startswith("aes-xts"):
            raise NotImplementedError(
                "Only aes-xts segments are supported (got %r)" % enc)
        self._f = fileobj
        self._xts = otp.aes_xts_decrypt
        self._mk = master_key
        self._sector = int(seg.get("sector_size", 512))
        self._seg_off = int(seg["offset"])            # bytes within partition
        self._phys_base = int(part_base_lba) * _SS + self._seg_off
        part_sectors = header_part_sectors(header, part_base_lba, fileobj)
        # plaintext size = partition bytes after the segment offset.  When the
        # partition size isn't known we fall back to the file's tail.
        if part_sectors is not None:
            self.size = max(0, part_sectors * _SS - self._seg_off)
        else:
            self._f.seek(0, os.SEEK_END)
            self.size = max(0, self._f.tell() - self._phys_base)
        self._pos = 0
        self._cache = {}
        self._cache_order = []
        self._cache_cap = cache_sectors

    # -- cache of decrypted sectors ------------------------------------------
    def _sector_plain(self, sec):
        hit = self._cache.get(sec)
        if hit is not None:
            return hit
        self._f.seek(self._phys_base + sec * self._sector)
        ct = self._f.read(self._sector)
        if len(ct) < self._sector:
            ct = ct + b"\x00" * (self._sector - len(ct))
        pt = self._xts(self._mk, ct, sec, self._sector)
        self._cache[sec] = pt
        self._cache_order.append(sec)
        if len(self._cache_order) > self._cache_cap:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)
        return pt

    # -- file-like interface -------------------------------------------------
    def seek(self, off, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._pos = off
        elif whence == os.SEEK_CUR:
            self._pos += off
        elif whence == os.SEEK_END:
            self._pos = self.size + off
        else:
            raise ValueError("bad whence %r" % whence)
        return self._pos

    def tell(self):
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = max(0, self.size - self._pos)
        if self._pos >= self.size or n == 0:
            return b""
        n = min(n, self.size - self._pos)
        start = self._pos
        end = start + n
        first = start // self._sector
        last = (end - 1) // self._sector
        out = bytearray()
        for sec in range(first, last + 1):
            pt = self._sector_plain(sec)
            lo = start - sec * self._sector if sec == first else 0
            hi = end - sec * self._sector if sec == last else self._sector
            out += pt[lo:hi]
        self._pos = end
        return bytes(out)

    def close(self):
        self._cache.clear()
        self._cache_order.clear()


def header_part_sectors(header, part_base_lba, fileobj):
    """Best-effort partition size in sectors — None if unknown.  The segment
    size in a LUKS2 header is usually ``"dynamic"``, so we don't learn it from
    the header; the extract pipeline passes the real partition size in instead
    (see :func:`open_partition_ext4`).  Kept as a hook so the reader stays
    usable standalone."""
    return getattr(header, "_pad_part_sectors", None)


# --------------------------------------------------------------------------
# Open a partition's filesystem
# --------------------------------------------------------------------------
_HEADER_SCAN_BYTES = 16 << 20          # LUKS2 header + keyslots fit in 16 MB


def read_luks_header(fileobj, part_base_lba):
    """Read and parse the LUKS2 header that sits at the start of a partition.

    Returns a parsed header object (``luks_otp.Luks2Header``) with the raw
    header blob kept on it (needed to unlock keyslots)."""
    otp = _luks_otp()
    fileobj.seek(part_base_lba * _SS)
    blob = fileobj.read(_HEADER_SCAN_BYTES)
    return otp.Luks2Header(blob)


def open_partition_ext4(fileobj, part, key_source, role=None):
    """Unlock *part* (a dict from :func:`parse_partitions`) and return a ready
    :class:`.ext4.Ext4Reader` over its plaintext ext4 filesystem.

    *key_source* is a :class:`.spike3_keys.Spike3KeySource`.  It is asked for a
    master key for this volume; if it can only supply an unlock keyfile (the
    customer-OTP key), the LUKS keyslot is unlocked here to recover the master
    key.  Raises :class:`Spike3KeyError` if no working key is available.
    """
    otp = _luks_otp()
    header = read_luks_header(fileobj, part["start_lba"])
    header._pad_part_sectors = part["sectors"]

    master_key = key_source.master_key(header, role=role, part=part)
    if not otp.verify_master_key(header, master_key):
        raise Spike3KeyError(
            "the supplied key did not unlock this partition "
            "(role=%s, index=%s)" % (role, part.get("index")))

    reader_fo = DecryptingSegmentReader(fileobj, part["start_lba"], header,
                                        master_key)
    return _ext4.Ext4Reader(reader_fo, 0, reader_fo.size)


class Spike3KeyError(Exception):
    """No working key for a Spike 3 partition."""
