"""Read-only browser over a Stern Spike 2 card image (or raw device).

Backs the GUI's Partition Explorer: open a ``.raw``/``.img`` card, list its MBR
partitions, walk the ext4 filesystem(s), preview small text files, and extract
files or whole subtrees to disk.  monkeybug's use cases: pull radium files out
of an old modded card to transfer into a new stock version, read/copy the boot
``.sh`` scripts, and dump partitions/folders to diff a modded card vs stock.

Browsing composes the existing size-neutral machinery (:mod:`.formats` for the
MBR + :class:`.ext4.Ext4Reader` for read-only ext4).  The one write the
explorer offers is :meth:`CardImage.replace_file` — an EXACT-SIZE in-place
replacement of a single file through the ext4 extent map, refreshing the
file's Spike 2 ``.sidx`` validation record (monkeybug batch 14 wishlist:
swap a radium/script file straight into a card without a full Write cycle).
Anything that would change the filesystem's shape (sizes, allocation,
names) stays out of scope — that's the engine's Write path.

``Ext4Reader``/``formats`` are referenced as module globals so tests can swap in
a lightweight fake filesystem.
"""

import os
from dataclasses import dataclass
from typing import Optional

from . import formats
from .ext4 import S_IFDIR, S_IFMT, S_IFREG, Ext4Reader

# ext4 mode bits the reader doesn't export.
S_IFLNK = 0xA000

# MBR partition-type buckets (the type byte at entry+4).
_EXT_TYPE = 0x83
_FAT_TYPES = frozenset({0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E})
_EXTENDED_TYPES = frozenset({0x05, 0x0F})

# Files larger than this aren't previewed inline (extract them instead) — keeps
# a "preview" from pulling a 700 MB image.bin fully into memory.
PREVIEW_CAP = 256 * 1024


@dataclass
class Partition:
    """One MBR primary partition and how the explorer treats it."""
    index: int          # MBR primary slot 0..3
    ptype: int          # MBR type byte
    lba_start: int
    sectors: int
    offset: int         # byte offset of the partition on the disk
    size: int           # byte size
    kind: str           # 'ext' | 'fat' | 'extended' | 'other'
    browsable: bool     # ext4 the reader could open
    label: str          # human label for the tab


@dataclass
class Entry:
    """One directory child."""
    name: str
    path: str           # full POSIX path within the partition (leading '/')
    is_dir: bool
    is_symlink: bool
    size: int
    inode: int
    link_target: Optional[str] = None


class CardImage:
    """Open a Spike 2 card image/device for read-only browsing.

    *source* is a path to a ``.raw``/``.img`` file, or an already-open, seekable
    binary object (e.g. a read-only ``RawDeviceFile`` over a physical card); an
    object is not closed by :meth:`close`.  Use as a context manager.
    """

    def __init__(self, source):
        if hasattr(source, "read") and hasattr(source, "seek"):
            self._f = source
            self._owns = False
            self._source_path = None       # replace_file needs a real path
        else:
            self._f = open(source, "rb")
            self._owns = True
            self._source_path = source
        self._readers = {}                 # partition index -> Ext4Reader
        try:
            self._parts = self._scan_partitions()
        except Exception:
            self.close()
            raise

    # ---- partitions ---------------------------------------------------------
    def _scan_partitions(self):
        self._f.seek(0)
        mbr = self._f.read(512)
        parts = []
        for index, ptype, lba, sectors in formats.parse_mbr_partitions_bytes(mbr):
            offset, size = lba * 512, sectors * 512
            if ptype == _EXT_TYPE:
                # Confirm it really is ext (and cache the reader) so the tab can
                # gray out anything that won't open.
                try:
                    self._readers[index] = Ext4Reader(self._f, offset, size)
                    kind, browsable, label = "ext", True, "Linux (ext4)"
                except Exception:
                    kind, browsable, label = "ext", False, "Linux (unreadable)"
            elif ptype in _FAT_TYPES:
                kind, browsable, label = "fat", False, "FAT (boot)"
            elif ptype in _EXTENDED_TYPES:
                kind, browsable, label = "extended", False, "Extended"
            else:
                kind, browsable, label = "other", False, "0x%02X" % ptype
            parts.append(Partition(index, ptype, lba, sectors, offset, size,
                                   kind, browsable, label))
        return parts

    def partitions(self):
        """The card's primary partitions (logical partitions inside an extended
        one aren't enumerated — the Spike 2 rootfs and data partitions are both
        primary)."""
        return list(self._parts)

    def _reader(self, part_index):
        r = self._readers.get(part_index)
        if r is None:
            raise ValueError("partition %r is not a browsable ext filesystem"
                             % part_index)
        return r

    def reader(self, part_index):
        """The read-only :class:`Ext4Reader` for a browsable partition.
        Raises ``ValueError`` for a partition that isn't browsable ext.
        Used by the Image Info probe to walk the data partition directly."""
        return self._reader(part_index)

    # ---- browsing -----------------------------------------------------------
    @staticmethod
    def _norm(path):
        return "/" + (path or "").strip("/")

    def _resolve(self, reader, path):
        """``(inode_number, inode)`` for *path* within *reader*, or ``None``."""
        ino, node = 2, reader.read_inode(2)
        for name in self._norm(path).strip("/").split("/"):
            if not name:
                continue
            if (node["mode"] & S_IFMT) != S_IFDIR:
                return None
            child = next((c for n, c, _t in reader._iter_dir(node) if n == name),
                         None)
            if child is None:
                return None
            ino, node = child, reader.read_inode(child)
        return ino, node

    def list_dir(self, part_index, path="/"):
        """Directory children of *path*, directories first then case-folded by
        name.  Symlinks carry their (fast-symlink) target for display."""
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFDIR:
            raise NotADirectoryError(path)
        base = self._norm(path).rstrip("/")
        out = []
        for name, child, _ftype in reader._iter_dir(node):
            if name in (".", ".."):
                continue
            try:
                cn = reader.read_inode(child)
            except Exception:
                continue
            m = cn["mode"] & S_IFMT
            is_lnk = m == S_IFLNK
            target = None
            if is_lnk and 0 < cn["size"] < 60:
                target = cn["i_block"][:cn["size"]].decode("utf-8", "replace")
            out.append(Entry(name=name, path=base + "/" + name,
                             is_dir=(m == S_IFDIR), is_symlink=is_lnk,
                             size=cn["size"], inode=child, link_target=target))
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    def preview(self, part_index, path):
        """First :data:`PREVIEW_CAP` bytes of a regular file, or ``None`` when
        it's a directory or too big to preview (extract it instead)."""
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFREG:
            return None
        if node["size"] > PREVIEW_CAP:
            return None
        return reader.read_file_bytes(node)

    # ---- extraction ---------------------------------------------------------
    def extract_file(self, part_index, path, out_path, progress=None):
        """Stream one regular file to *out_path*; returns its byte size."""
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFREG:
            raise IsADirectoryError(path)
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        reader.extract_file(node, out_path, progress=progress)
        return node["size"]

    def extract_tree(self, part_index, path, out_dir, progress=None,
                     max_depth=64, chunk_progress=None, top_name=None):
        """Extract *path* (a file or directory) under *out_dir*, mirroring the
        card's layout beneath a folder named after *path*'s basename —
        overridable via *top_name*, so a whole-partition extract can land in
        e.g. ``Partition 2`` instead of a generic ``root`` (two partitions
        extracted into the same folder used to mix together there).

        Returns ``(n_files, n_bytes)``.  Only regular files are written
        (symlinks/devices are skipped).  *progress* is called
        ``(n_files, n_bytes, current_rel_path)`` after each file;
        *chunk_progress* is forwarded to each file's streaming extract
        (``(written, size)`` per chunk) so a caller can cancel mid-file
        instead of waiting out a 700 MB image.bin."""
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        ino, node = res
        m = node["mode"] & S_IFMT
        base = self._norm(path).rstrip("/")

        if m == S_IFREG:
            out = os.path.join(out_dir, os.path.basename(base) or "file")
            n = self.extract_file(part_index, base, out,
                                  progress=chunk_progress)
            if progress:
                progress(1, n, base)
            return 1, n
        if m != S_IFDIR:
            raise ValueError("not a file or directory: %s" % path)

        top = top_name or os.path.basename(base) or "root"
        n_files = n_bytes = 0
        for rel_path, _fino, fnode in reader.iter_regular_files(
                root_ino=ino, max_depth=max_depth, min_size=0):
            parts = [p for p in rel_path.strip("/").split("/") if p]
            out = os.path.join(out_dir, top, *parts)
            parent = os.path.dirname(out)
            if parent:
                os.makedirs(parent, exist_ok=True)
            reader.extract_file(fnode, out, progress=chunk_progress)
            n_files += 1
            n_bytes += fnode["size"]
            if progress:
                progress(n_files, n_bytes, rel_path)
        return n_files, n_bytes

    def dir_stats(self, part_index, path, max_depth=64):
        """``(n_files, n_bytes)`` of every regular file at/under directory
        *path* — recursive folder sizes for the Properties view."""
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        ino, node = res
        if (node["mode"] & S_IFMT) != S_IFDIR:
            return 1, node["size"]
        n = b = 0
        for _rel, _fino, fnode in reader.iter_regular_files(
                root_ino=ino, max_depth=max_depth, min_size=0):
            n += 1
            b += fnode["size"]
        return n, b

    # ---- in-place replace ----------------------------------------------------
    def replace_file(self, part_index, path, src_path):
        """Replace the regular file *path* with the EXACT-SIZE contents of
        *src_path*, in place through the ext4 extent map, and refresh the
        file's ``.sidx`` validation record when the manifest indexes it.

        Same-size only: rewriting content into the file's own allocated
        blocks touches no filesystem metadata (no inode, allocation or
        checksum changes), which is what makes this safe on a real card —
        the exact discipline the engine's size-neutral Write uses.  Raises
        ``ValueError`` on a size mismatch or when the card was opened from a
        stream rather than an image file.

        Returns ``(n_bytes, sidx_refreshed)``."""
        from . import sidx
        if not self._source_path:
            raise ValueError(
                "replace requires a card image file (not a raw stream)")
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFREG:
            raise IsADirectoryError(path)
        with open(src_path, "rb") as f:
            new = f.read()
        if len(new) != node["size"]:
            raise ValueError(
                "size mismatch: the replacement is %d bytes but %s is %d "
                "bytes on the card — in-place replace must be exact-size "
                "(pad or trim the file, or use the Write tab's flows)"
                % (len(new), path, node["size"]))

        def _writes_for(target_node, file_off, buf):
            out = []
            pos = 0
            for doff, n in reader.disk_ranges(target_node, file_off, len(buf)):
                out.append((doff, buf[pos:pos + n]))
                pos += n
            return out

        writes = _writes_for(node, 0, new) if new else []

        # Refresh the file's validation record (HMAC-SHA1 + MD5) so the card
        # still passes Stern's SD validation.  Files the manifest doesn't
        # index (or a card with no manifest at all) need nothing.
        refreshed = False
        try:
            sidx_path, sidx_node = sidx.find_sidx(reader)
        except Exception:
            sidx_path, sidx_node = None, None
        if sidx_node is not None:
            sdata = reader.read_file_bytes(sidx_node)
            recs, _crc, fmt = sidx.parse_records(sdata)
            rel = self._norm(path).lstrip("/")
            po = recs.get(rel)
            if po is not None:
                hm, md = sidx.digests(new)
                for foff, b in sidx.record_field_writes(po, hm, md, fmt):
                    writes.extend(_writes_for(sidx_node, foff, b))
                refreshed = True

        # All extents resolved before the first byte is written — a mapping
        # failure can't leave a half-replaced file.
        with open(self._source_path, "r+b") as wf:
            for doff, chunk in writes:
                wf.seek(doff)
                wf.write(chunk)
        return len(new), refreshed

    # ---- lifecycle ----------------------------------------------------------
    def close(self):
        if getattr(self, "_owns", False):
            try:
                self._f.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
