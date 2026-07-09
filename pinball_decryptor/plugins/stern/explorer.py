"""Read-only browser over a Stern Spike 2 card image (or raw device).

Backs the GUI's Partition Explorer: open a ``.raw``/``.img`` card, list its MBR
partitions, walk the ext4 filesystem(s), preview small text files, and extract
files or whole subtrees to disk.  monkeybug's use cases: pull radium files out
of an old modded card to transfer into a new stock version, read/copy the boot
``.sh`` scripts, and dump partitions/folders to diff a modded card vs stock.

This is the pure read side — it composes the existing size-neutral machinery
(:mod:`.formats` for the MBR + :class:`.ext4.Ext4Reader` for read-only ext4) and
never writes to the card.  Editing a file back in place is a separate,
SIDX-aware step owned by the engine's Write path.

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
        else:
            self._f = open(source, "rb")
            self._owns = True
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
                     max_depth=64, chunk_progress=None):
        """Extract *path* (a file or directory) under *out_dir*, mirroring the
        card's layout beneath a folder named after *path*'s basename (``root``
        for the whole partition).

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

        top = os.path.basename(base) or "root"
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
