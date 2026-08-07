"""Read-only browser over a Stern Spike 2 card image (or raw device).

Backs the GUI's Partition Explorer: open a ``.raw``/``.img`` card, list its MBR
partitions, walk the ext4 filesystem(s), preview small text files, and extract
files or whole subtrees to disk.  A tester's use cases: pull radium files out
of an old modded card to transfer into a new stock version, read/copy the boot
``.sh`` scripts, and dump partitions/folders to diff a modded card vs stock.

Browsing composes the existing size-neutral machinery (:mod:`.formats` for the
MBR + :class:`.ext4.Ext4Reader` for read-only ext4).  The one write the
explorer offers is :meth:`CardImage.replace_file`, which takes one of two
routes depending on the replacement's size:

  * **same size** — rewritten in place through the ext4 extent map.  No
    filesystem metadata moves at all, so this needs nothing but the image
    file itself (feedback batch 14 wishlist: swap a radium/script file
    straight into a card without a full Write cycle).
  * **any other size** (opt-in via ``allow_resize``) — handed to the
    platform's own ext4 driver via :mod:`...core.ext4_grow`, the same
    loop-mount-and-``cp`` path full-size video replacement already uses.
    The kernel reallocates the file's blocks; we never hand-edit an extent
    tree or a bitmap.  Needs WSL2 on Windows / e2fsprogs on macOS.

Either way the file's Spike 2 ``.sidx`` validation record is refreshed
afterwards — including the two stored copies of its SIZE when the length
changed.  Renaming, creating and deleting files stay out of scope; that's
the engine's Write path.

``Ext4Reader``/``formats`` are referenced as module globals so tests can swap in
a lightweight fake filesystem.
"""

import functools
import os
import threading
from dataclasses import dataclass
from typing import Optional

from . import formats, sidx
from .ext4 import S_IFDIR, S_IFMT, S_IFREG, Ext4Reader

# ext4 mode bits the reader doesn't export.
S_IFLNK = 0xA000


def _serialised(method):
    """Run *method* holding the card's read lock (see ``CardImage.__init__``).

    Applied to the short, interactive reads only — a decorator rather than an
    indented ``with`` block so the diff stays on the locking and not on
    re-indenting bodies that didn't otherwise change.
    """
    @functools.wraps(method)
    def wrapper(self, *a, **kw):
        with self._lock:
            return method(self, *a, **kw)
    return wrapper

# MBR partition-type buckets (the type byte at entry+4).
_EXT_TYPE = 0x83
_FAT_TYPES = frozenset({0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E})
_EXTENDED_TYPES = frozenset({0x05, 0x0F})

# Files larger than this aren't previewed inline (extract them instead) — keeps
# a "preview" from pulling a 700 MB image.bin fully into memory.
PREVIEW_CAP = 256 * 1024


def _extent_writes(reader, node, file_off, buf):
    """``[(disk_offset, bytes), ...]`` placing *buf* at *file_off* within
    *node*'s file, split across whatever extents that range spans."""
    out = []
    pos = 0
    for doff, n in reader.disk_ranges(node, file_off, len(buf)):
        out.append((doff, buf[pos:pos + n]))
        pos += n
    return out


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
        # Every read seeks the ONE shared handle, so two at once interleave
        # their seeks and the loser gets nonsense — a bogus FileNotFoundError
        # or a short struct unpack for a file that is plainly there.  The GUI
        # renders image/font previews on a worker thread now, so arrowing down
        # a folder of PNGs overlaps a read with the next one (and with the Tk
        # thread's own directory fills).  This serialises the short,
        # interactive reads; the streaming extract paths are deliberately
        # outside it so a multi-GB dump can't freeze the browsing UI behind it.
        self._lock = threading.RLock()
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

    @_serialised
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

    @_serialised
    def preview(self, part_index, path, cap=None):
        """The bytes of a regular file up to *cap*, or ``None`` when it's a
        directory or bigger than that (extract it instead).

        *cap* defaults to :data:`PREVIEW_CAP`, which is sized for the text
        preview; the GUI raises it for the file types it can actually render
        (a card's PNGs run past 256 KB) and reads those off the Tk thread.
        Late-bound (``None`` -> the global) rather than a def-time default:
        ``cap=PREVIEW_CAP`` froze the value at import, which quietly ignored
        anything that changes the global afterwards - the test suite does,
        and its cap test failed on every platform the moment the parameter
        appeared.
        """
        if cap is None:
            cap = PREVIEW_CAP
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFREG:
            return None
        if node["size"] > cap:
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

    @_serialised
    def file_size(self, part_index, path):
        """Byte size of the regular file at *path*.

        The tree's Size column is a rounded human string ("162.1 KB"), and a
        replace has to compare against the file's real length — so callers
        that need the number ask here rather than parsing the display.
        """
        reader = self._reader(part_index)
        res = self._resolve(reader, path)
        if res is None:
            raise FileNotFoundError(path)
        _ino, node = res
        if (node["mode"] & S_IFMT) != S_IFREG:
            raise IsADirectoryError(path)
        return node["size"]

    @_serialised
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
    def replace_file(self, part_index, path, src_path, allow_resize=False,
                     log=None):
        """Replace the regular file *path* with the contents of *src_path* and
        refresh its ``.sidx`` validation record when the manifest indexes it.

        A same-size replacement is rewritten into the file's own allocated
        blocks, touching no filesystem metadata at all (no inode, allocation
        or checksum changes) — the discipline the engine's size-neutral Write
        uses, and why it needs nothing but the image file.

        A different-size one is refused unless *allow_resize* is set, because
        it cannot be done that way: the file needs blocks allocated or freed,
        its extent tree rewritten and the group/superblock accounting kept
        consistent.  With *allow_resize* the copy is handed to the platform's
        own ext4 driver (:func:`...core.ext4_grow.grow_files`) so the kernel
        does all of that, which is the same route full-size video replacement
        takes; the record's stored size is then refreshed alongside its
        digests.  *log* is an optional ``(message, level)`` callable for that
        step's progress.

        Raises ``ValueError`` when the card was opened from a stream rather
        than an image file, when a resize is needed but not allowed, or when
        the platform can't mount ext4.

        Returns ``(n_bytes, sidx_refreshed)``."""
        new_size = os.path.getsize(src_path)
        if allow_resize and new_size != self.file_size(part_index, path):
            return self._resize_file(part_index, path, src_path, new_size, log)
        with open(src_path, "rb") as f:
            new = f.read()
        return self.replace_file_bytes(part_index, path, new)

    def _resize_file(self, part_index, path, src_path, new_size, log=None):
        """The different-size half of :meth:`replace_file`: let the platform's
        ext4 driver copy *src_path* over the file (growing or shrinking the
        inode), then refresh the ``.sidx`` record against the new bytes.

        The refresh runs over a FRESH reader: the copy moved the file's blocks,
        so every extent this instance cached is stale.  ``.sidx`` itself keeps
        its length, so its own record fields are still patchable at raw disk
        offsets the way a size-neutral write does it.
        """
        from ...core import ext4_grow
        if not self._source_path:
            raise ValueError(
                "replace requires a card image file (not a raw stream)")
        part = next((p for p in self._parts if p.index == part_index), None)
        if part is None:
            raise ValueError("no partition %r on this card" % part_index)
        cur_size = self.file_size(part_index, path)
        rel = self._norm(path).lstrip("/")

        # Checked before the copy, not after it fails inside the mount script,
        # so the user gets the fix (install/convert WSL) rather than a losetup
        # error — and gets it while the card is still untouched.
        ok, why = ext4_grow.available()
        if not ok:
            raise ValueError(
                "a replacement of a different size has to go through the "
                "platform's Linux filesystem driver, which isn't available "
                "here: %s. Until then, replace %s with a file of exactly %d "
                "bytes." % (why, rel, cur_size))
        try:
            grown = ext4_grow.grow_files(self._source_path, part.offset,
                                         [(rel, src_path)], log=log)
        except ext4_grow.Ext4GrowNoSpace as e:
            raise ValueError(
                "partition sda%d hasn't enough free space to hold %s at %d "
                "bytes (it is %d bytes now); nothing was changed on the card."
                % (part_index + 1, rel, new_size, cur_size)) from e
        except ext4_grow.Ext4GrowUnavailable as e:
            # available() said yes and the mount still couldn't run — report it
            # as the platform problem it is rather than as a failed replace.
            raise ValueError(
                "the platform's Linux filesystem driver couldn't open the "
                "card image: %s" % e) from e
        if not grown:
            raise ValueError("%s was not written to the card" % rel)

        refreshed = False
        with CardImage(self._source_path) as fresh:
            reader = fresh._reader(part_index)
            try:
                _sidx_path, sidx_node = sidx.find_sidx(reader)
            except Exception:
                sidx_node = None
            if sidx_node is not None:
                sdata = reader.read_file_bytes(sidx_node)
                recs, _crc, fmt = sidx.parse_records(sdata)
                po = recs.get(rel)
                if po is not None:
                    hm, md = sidx.digests_file(src_path)
                    writes = []
                    for foff, b in sidx.record_field_writes(
                            po, hm, md, fmt, size=new_size):
                        writes.extend(_extent_writes(reader, sidx_node, foff, b))
                    with open(self._source_path, "r+b") as wf:
                        for doff, chunk in writes:
                            wf.seek(doff)
                            wf.write(chunk)
                    refreshed = True
        return new_size, refreshed

    def replace_file_bytes(self, part_index, path, new):
        """As :meth:`replace_file` but the replacement content is passed
        directly as *new* (bytes) — used by callers that generate the bytes in
        memory (e.g. the adjustment-default patcher).  Same exact-size rule and
        ``.sidx`` refresh.  Returns ``(n_bytes, sidx_refreshed)``."""
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
        if len(new) != node["size"]:
            raise ValueError(
                "size mismatch: the replacement is %d bytes but %s is %d "
                "bytes on the card — an in-place replace must be exact-size "
                "(pad or trim the file, or allow the file to be resized)"
                % (len(new), path, node["size"]))

        writes = _extent_writes(reader, node, 0, new) if new else []

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
                    writes.extend(_extent_writes(reader, sidx_node, foff, b))
                refreshed = True

        # All extents resolved before the first byte is written — a mapping
        # failure can't leave a half-replaced file.
        with open(self._source_path, "r+b") as wf:
            for doff, chunk in writes:
                wf.seek(doff)
                wf.write(chunk)
        return len(new), refreshed

    # ---- game firmware (adjustment defaults) ---------------------------------
    def find_firmwares(self):
        """Yield ``(part_index, path)`` for every browsable partition's game
        ELF.  A Spike 2 card carries several ARM ELFs — the small
        ``spike_menu`` ``game`` on the rootfs and the real ``game_real`` in the
        data partition's game directory — and only the latter holds the
        adjustment table, so the caller tries each until one decodes."""
        for p in self._parts:
            if not p.browsable:
                continue
            reader = self._readers.get(p.index)
            if reader is None:
                continue
            try:
                _img_ino, fw_ino = reader.find_spike_assets()
            except Exception:
                fw_ino = None
            if fw_ino is None:
                continue
            for path, ino, _node in reader.iter_regular_files(
                    min_size=1, max_depth=20):
                if ino == fw_ino:
                    yield p.index, "/" + path.strip("/")
                    break

    def find_firmware(self):
        """First ``(part_index, path)`` game ELF, or ``(None, None)``."""
        for part, path in self.find_firmwares():
            return part, path
        return None, None

    def read_firmware(self, part_index, path):
        """The ELF bytes of the firmware at *part_index*/*path*."""
        reader = self._reader(part_index)
        _ino, node = self._resolve(reader, path)
        return reader.read_file_bytes(node)

    def adjustment_table(self):
        """Decode the card's adjustment-default table.  Tries each partition's
        game ELF and returns ``(AdjustmentTable, part_index, path)`` for the
        first that decodes to a sane table (skips the ``spike_menu`` binary,
        which has no adjustments).  Raises ``ValueError`` if none decode (an
        unrecognised build)."""
        from .adjustments import AdjustmentTable
        last_err = None
        found_any = False
        for part, path in self.find_firmwares():
            found_any = True
            try:
                table = AdjustmentTable(self.read_firmware(part, path))
            except Exception as e:
                last_err = e
                continue
            if table.sane():
                return table, part, path
            last_err = ValueError("decoded table failed the sanity check")
        if not found_any:
            raise FileNotFoundError("game firmware not found on this card")
        raise ValueError("no game firmware on this card exposes an adjustment "
                         "table (%s)" % (last_err or "unrecognised build"))

    def write_adjustment_defaults(self, part_index, path, table, overrides,
                                  high_scores=None, name_overrides=None,
                                  menu_last_id=None, menu_plan=None):
        """Patch the game ELF's compiled defaults and write it back in place
        (exact-size, extent-mapped) with the ``.sidx`` record refreshed.

        *overrides* is ``{AD_name: value}`` for the numeric adjustment defaults.
        *name_overrides* is ``{slot label: {initials, name}}`` for the factory
        high-score board (see :mod:`.high_scores`); it needs the matching
        ``HighScoreDefaults`` in *high_scores*.  *menu_last_id* raises the
        operator menu's Feature Adjustments page to end at that adjustment id,
        which is what makes the settings above it reachable on the machine (see
        :mod:`.menu_visibility`); pass the caller's ``widen_plan`` as
        *menu_plan* to save re-scanning the firmware for it.  Every patch is
        composed into ONE buffer so the card is written — and its ``.sidx``
        refreshed — once.

        Returns ``(n_settings, sidx_refreshed)``, where n_settings counts every
        adjustment and high-score slot changed (the menu page is one edit to
        the firmware's code, not a setting, and isn't counted).
        """
        new = table.patched_bytes(overrides)
        n = len(overrides)
        if name_overrides and high_scores is not None:
            # Re-bind to the already-patched bytes: the adjustment patch only
            # touched 4-byte value fields, so every string offset still holds,
            # but the object must own the buffer it edits.
            from .high_scores import HighScoreDefaults
            hs = HighScoreDefaults(new, table)
            new = hs.patched_bytes(name_overrides)
            n += len(name_overrides)
        if menu_last_id is not None:
            # Last, and on the composed buffer: it rewrites one instruction in
            # .text, which no earlier patch touches, and it verifies itself by
            # re-reading the page out of the result.
            from .menu_visibility import widened_bytes
            new = widened_bytes(table, new, int(menu_last_id), plan=menu_plan)
        _n, refreshed = self.replace_file_bytes(part_index, path, new)
        return n, refreshed

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
