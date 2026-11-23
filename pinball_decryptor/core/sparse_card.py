"""Card images stored COMPACT: sparse files, same path, same bytes (PAD-1507).

A Spike 3 card image is the whole 64 GB card - 61.9 GB - and measured on
Pokemon LE 0.82 only 3.35 GB of it is data; the other 58.6 GB is zeros
(the LUKS partitions are mostly never-written space).  Eight titles took
462 GB of D:.  Compressing them (zip, xz) would make them unusable to
develop against: the rig opens the card read-only in place, the app seeks
around it, the writer copies it.  A SPARSE file is the compact form that
still IS the card: NTFS (and ext4) keep only the clusters that hold data,
the zero runs become holes that cost nothing, and every reader - the app,
WSL's /mnt/d, losetup -r, cryptsetup - reads the very same bytes back,
holes as zeros.  Reads get faster too: a hole is answered without the disk.

What is here:

* :func:`compact_file` - make an existing image sparse IN PLACE: every
  all-zero run of at least ``min_hole`` becomes a hole.  Only ranges that
  were just read back as zeros are touched, so the bytes cannot change.
  Only the file's ALLOCATED ranges are read, so a second run over an
  already-compact card is seconds, not a 62 GB read.
* :func:`sparse_copy` - copy an image to a new sparse file (the build's
  card copy; a plain CopyFileEx writes every zero back out).
* :func:`move_card` - move an image to another folder or drive and keep it
  compact (Explorer's move to another drive writes the holes back out).
* :func:`import_card` - bring a new image into a library folder compact,
  from a .raw/.img or straight out of a .zip/.xz/.gz/.bz2 download.
* :func:`compact_folder` and :func:`main` - the library tool:
  ``python -m pinball_decryptor.core.sparse_card D:\\Pinball\\images\\Stern\\spike3``.

A filesystem without sparse files (FAT32, exFAT, some network shares)
refuses the holes; then nothing is lost, the file just stays full size.
"""

from __future__ import annotations

import bz2
import ctypes
import gzip
import lzma
import os
import struct
import sys
import time
import zipfile
from dataclasses import dataclass, field

from . import rawdevice as rd

#: the granule the scan looks at: NTFS frees a sparse file's clusters in
#: 16-cluster compression units, 64 KiB on a 4 KiB-cluster volume
BLOCK = 64 * 1024
#: the read size
CHUNK = 16 * 1024 * 1024
#: the smallest zero run worth a hole: smaller ones save little and split
#: the data into more fragments
MIN_HOLE = 1024 * 1024

#: what the library tool treats as a card image
IMAGE_SUFFIXES = (".raw", ".img")
#: compressed downloads :func:`import_card` unpacks
ARCHIVE_SUFFIXES = (".zip", ".xz", ".gz", ".bz2")

_ZERO_CHUNK = bytes(CHUNK)
_ZERO_BLOCK = bytes(BLOCK)

_FSCTL_QUERY_ALLOCATED_RANGES = 0x000940CF
_ERROR_MORE_DATA = 234
_FALLOC_FL_KEEP_SIZE = 0x01
_FALLOC_FL_PUNCH_HOLE = 0x02


# ---------------------------------------------------------------- filesystem


def on_disk_size(path):
    """Bytes *path* really takes on its drive (holes cost nothing)."""
    if sys.platform == "win32":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.GetCompressedFileSizeW
        fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        fn.restype = ctypes.c_ulong
        high = ctypes.c_ulong(0)
        low = fn(os.path.abspath(path), ctypes.byref(high))
        if low == 0xFFFFFFFF and ctypes.get_last_error():
            return os.path.getsize(path)
        return (high.value << 32) | low
    st = os.stat(path)
    blocks = getattr(st, "st_blocks", None)
    return st.st_size if blocks is None else blocks * 512


def allocated_ranges(f, size):
    """The ``(offset, length)`` ranges of open file *f* that hold clusters,
    in order.  Everything else is a hole and reads as zeros.  The whole file
    when the filesystem cannot say."""
    if size <= 0:
        return []
    if sys.platform == "win32":
        got = _win_allocated_ranges(f, size)
    else:
        got = _posix_allocated_ranges(f, size)
    return [(0, size)] if got is None else got


def _win_allocated_ranges(f, size):
    try:
        import msvcrt
        from ctypes import wintypes
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(f.fileno()))
    except (OSError, ValueError, AttributeError, ImportError):
        return None
    out = []
    start = 0
    n = 512
    while start < size:
        inbuf = ctypes.create_string_buffer(struct.pack("<qq", start,
                                                        size - start))
        outbuf = ctypes.create_string_buffer(16 * n)
        ret = ctypes.c_ulong(0)
        ok = rd._DeviceIoControl(handle, _FSCTL_QUERY_ALLOCATED_RANGES,
                                 inbuf, 16, outbuf, 16 * n,
                                 ctypes.byref(ret), None)
        more = (not ok) and ctypes.get_last_error() == _ERROR_MORE_DATA
        if not ok and not more:
            return None
        cnt = ret.value // 16
        for i in range(cnt):
            off, ln = struct.unpack_from("<qq", outbuf.raw, 16 * i)
            out.append((off, ln))
        if not more or cnt == 0:
            break
        start = out[-1][0] + out[-1][1]
    return out


def _posix_allocated_ranges(f, size):
    seek_data = getattr(os, "SEEK_DATA", None)
    seek_hole = getattr(os, "SEEK_HOLE", None)
    if seek_data is None:
        return None
    fd = f.fileno()
    out = []
    pos = 0
    try:
        while pos < size:
            try:
                d = os.lseek(fd, pos, seek_data)
            except OSError:          # ENXIO: no data past pos
                break
            h = min(os.lseek(fd, d, seek_hole), size)
            out.append((d, h - d))
            pos = h
    except OSError:
        return None
    return out


def _set_sparse(f):
    """Mark *f* sparse (Windows); True when the filesystem allows holes."""
    if sys.platform != "win32":
        return True
    return rd._win_fsctl(f, rd._FSCTL_SET_SPARSE)


_libc = None


def _punch(f, off, n):
    """Turn ``[off, off+n)`` of *f* into a hole.  True when it became one."""
    if sys.platform == "win32":
        return rd._win_fsctl(f, rd._FSCTL_SET_ZERO_DATA,
                             rd._ZeroDataInformation(off, off + n))
    global _libc
    try:
        if _libc is None:
            _libc = ctypes.CDLL(None, use_errno=True)
            _libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int,
                                        ctypes.c_longlong, ctypes.c_longlong]
        return _libc.fallocate(f.fileno(),
                               _FALLOC_FL_PUNCH_HOLE | _FALLOC_FL_KEEP_SIZE,
                               off, n) == 0
    except (OSError, AttributeError):
        return False


def _flush(f):
    """NTFS counts a write's clusters once the cache has written them."""
    try:
        os.fsync(f.fileno())
    except OSError:
        pass


def _times(path):
    st = os.stat(path)
    return (st.st_atime_ns, st.st_mtime_ns)


def _put_times(path, times):
    """Give *path* back the (atime, mtime) of :func:`_times` (PAD-1510).
    Compacting or expanding changes no byte, so the card keeps its date: the
    Spike 2 library matches a D: original to its library copy by name, size
    AND modified time, and a library tool sorting by date should not see
    every card as new.  Called after the file is closed: Windows can stamp
    the time again when a written handle closes."""
    try:
        os.utime(path, ns=times)
    except OSError:
        pass


# ---------------------------------------------------------------- the scan


def _zero_runs(f, ranges, *, min_hole, progress=None, total=0, done0=0):
    """Yield the ``(offset, length)`` all-zero runs of at least *min_hole*
    inside the allocated *ranges* of *f*, 64 KiB aligned."""
    done = done0
    for start, length in ranges:
        end = start + length
        # whole blocks only: a partial unit at the range's edge stays data
        pos = -(-start // BLOCK) * BLOCK
        run = None
        f.seek(pos)
        while pos < end:
            want = min(CHUNK, end - pos)
            b = f.read(want)
            if not b:
                break
            if len(b) == CHUNK and b == _ZERO_CHUNK:
                zero_all = True
            else:
                zero_all = False
            nblk = len(b) // BLOCK
            if zero_all:
                if run is None:
                    run = pos
            else:
                for i in range(nblk):
                    if b[i * BLOCK:(i + 1) * BLOCK] == _ZERO_BLOCK:
                        if run is None:
                            run = pos + i * BLOCK
                    elif run is not None:
                        s = pos + i * BLOCK
                        if s - run >= min_hole:
                            yield run, s - run
                        run = None
                if len(b) % BLOCK and run is not None:
                    s = pos + nblk * BLOCK     # the tail is not a whole block
                    if s - run >= min_hole:
                        yield run, s - run
                    run = None
            pos += len(b)
            done += len(b)
            if progress:
                progress(done, total)
        if run is not None:
            s = min(pos, end) // BLOCK * BLOCK
            if s - run >= min_hole:
                yield run, s - run


@dataclass
class CompactResult:
    path: str
    size: int
    before: int                 # bytes on disk before
    after: int                  # bytes on disk after
    holes: int = 0
    sparse_ok: bool = True      # False: the filesystem refused holes
    seconds: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def saved(self):
        return max(0, self.before - self.after)


def takes_less(path, min_hole=MIN_HOLE):
    """True when the card at *path* is stored compact as Explorer can tell
    without opening it: it is marked sparse and at least *min_hole* of it
    has no disk space behind it.  This is the rule the card's icon goes by
    (tools/padicon/padicon.c says the same in C, PAD-1522); False on any
    error and for a file that is not there."""
    try:
        st = os.stat(path)
        if sys.platform == "win32":
            # FILE_ATTRIBUTE_SPARSE_FILE
            if not getattr(st, "st_file_attributes", 0) & 0x200:
                return False
        return on_disk_size(path) + min_hole <= st.st_size
    except OSError:
        return False


def shell_refresh(path):
    """Tell Explorer the file changed, so its icon is asked for again (a
    card just made compact, or full size, shows it at once).  Never raises."""
    if sys.platform != "win32":
        return
    try:
        fn = ctypes.windll.shell32.SHChangeNotify
        fn.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_wchar_p,
                       ctypes.c_void_p]
        fn.restype = None
        # SHCNE_UPDATEITEM, SHCNF_PATHW
        fn(0x00002000, 0x0005, os.path.abspath(path), None)
    except Exception:                                   # noqa: BLE001
        pass


def compact_file(path, *, min_hole=MIN_HOLE, progress=None, log=None):
    """Make the image at *path* sparse in place; the bytes do not change,
    nor does its modified time.  Returns a :class:`CompactResult`."""
    times = _times(path)
    try:
        res = _compact_open(path, min_hole=min_hole, progress=progress)
    finally:
        _put_times(path, times)
        shell_refresh(path)
    if log:
        log(describe(res))
    return res


def _compact_open(path, *, min_hole, progress):
    t0 = time.monotonic()
    size = os.path.getsize(path)
    with open(path, "r+b", buffering=0) as f:
        _flush(f)               # what is on disk, not what the cache holds
        before = on_disk_size(path)
        res = CompactResult(path, size, before, before)
        if not _set_sparse(f):
            res.sparse_ok = False
            res.notes.append("this drive does not keep sparse files")
            return res
        ranges = allocated_ranges(f, size)
        total = sum(n for _o, n in ranges)
        # collected first: punching while the scan reads the same range
        # would change what the allocated-range walk sees
        runs = list(_zero_runs(f, ranges, min_hole=min_hole,
                               progress=progress, total=total))
        for off, n in runs:
            if _punch(f, off, n):
                res.holes += 1
            else:
                res.sparse_ok = False
                res.notes.append("hole refused at 0x%x" % off)
                break
        _flush(f)
    res.after = on_disk_size(path)
    res.seconds = time.monotonic() - t0
    return res


# ---------------------------------------------------------------- copies


class _SparseWriter:
    """A new file at full *size*, holes everywhere; :meth:`write_at` lays
    data down, zero blocks are skipped so they stay holes."""

    def __init__(self, path, size):
        self.f = open(path, "w+b", buffering=0)
        self.size = size
        self.sparse = rd.sparse_truncate(self.f, size)

    def write_at(self, off, b):
        n = len(b)
        if not n:
            return
        if b == (_ZERO_CHUNK[:n] if n <= CHUNK else bytes(n)):
            return
        if not self.sparse:
            self.f.seek(off)
            self.f.write(b)
            return
        # block by block: only the blocks with data allocate
        i = 0
        while i < n:
            j = min(n, (off + i) // BLOCK * BLOCK + BLOCK - off)
            piece = b[i:j]
            if piece != _ZERO_BLOCK[:len(piece)]:
                self.f.seek(off + i)
                self.f.write(piece)
            i = j

    def close(self):
        # flushed before the size is asked: NTFS reports a fresh write's
        # clusters only once the cache wrote them
        try:
            os.fsync(self.f.fileno())
        except OSError:
            pass
        self.f.close()


def sparse_copy(src, dst, *, progress=None, cancel=None):
    """Copy image *src* to a new sparse file *dst*: only *src*'s allocated
    ranges are read, and only blocks with data are written.  *progress* is
    ``progress(done, total)`` in bytes of *src* covered; *cancel* a callable
    that raises to stop.  Returns the bytes written."""
    size = os.path.getsize(src)
    written = 0
    w = _SparseWriter(dst, size)
    try:
        with open(src, "rb", buffering=0) as fi:
            ranges = allocated_ranges(fi, size)
            covered = 0
            hole_bytes = size - sum(n for _o, n in ranges)
            for off, n in ranges:
                fi.seek(off)
                pos = off
                end = off + n
                while pos < end:
                    if cancel:
                        cancel()
                    b = fi.read(min(CHUNK, end - pos))
                    if not b:
                        break
                    w.write_at(pos, b)
                    written += len(b)
                    pos += len(b)
                    covered += len(b)
                    if progress:
                        progress(min(size, covered + hole_bytes
                                     * covered // max(size - hole_bytes, 1)),
                                 size)
        if not w.sparse:
            # a drive without holes: the gaps have to be real zeros
            w.f.truncate(size)
    finally:
        w.close()
    if progress:
        progress(size, size)
    return written


@dataclass
class MoveResult:
    src: str
    dst: str
    size: int
    before: int                 # bytes on disk where it was
    after: int                  # bytes on disk where it is now
    renamed: bool = False       # the same drive: a rename, nothing copied
    sparse_ok: bool = True      # False: the new drive refused holes
    kept: bool = False          # the original could not be removed
    seconds: float = 0.0


class SameFolder(ValueError):
    """The card is already in the folder it is to be moved to."""


def _same_volume(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def move_card(src, dest_dir, *, progress=None, cancel=None, copy=None):
    """Move card image *src* into folder *dest_dir* and keep it compact
    (PAD-1535).  Explorer's own move to another drive is a copy
    (CopyFileEx), which writes every hole back out as zeros: a 3 GB compact
    card took its whole 62 GB on the new drive, and as long to write.  Here
    a move on the same drive is a rename (instant, the file untouched); to
    another drive only the card's data is copied (:func:`sparse_copy`),
    written as ``.part``, given the card's dates and renamed when whole, and
    only then is the original removed.  A full-size card arrives compact.

    *progress* is ``progress(done, total)``, *cancel* a callable that raises
    to stop (the ``.part`` is removed, the original left as it was).
    Raises :class:`SameFolder`, ``FileExistsError`` (a file of that name is
    there already) or :class:`NoRoom`."""
    t0 = time.monotonic()
    src = os.path.abspath(src)
    dest_dir = os.path.abspath(dest_dir)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    if not os.path.isdir(dest_dir):
        raise FileNotFoundError(dest_dir)
    dst = os.path.join(dest_dir, os.path.basename(src))
    if os.path.normcase(os.path.dirname(src)) == os.path.normcase(dest_dir):
        raise SameFolder(dest_dir)
    if os.path.exists(dst):
        raise FileExistsError(dst)
    size = os.path.getsize(src)
    before = on_disk_size(src)
    if _same_volume(os.path.dirname(src), dest_dir):
        os.rename(src, dst)
        shell_refresh(dst)
        return MoveResult(src, dst, size, before, on_disk_size(dst),
                          renamed=True, seconds=time.monotonic() - t0)
    with open(src, "rb", buffering=0) as f:
        data = sum(n for _o, n in allocated_ranges(f, size))
    _need_room(dest_dir, data, "the card's data needs %.1f GB")
    times = _times(src)
    part = dst + ".part"
    try:
        (copy or sparse_copy)(src, part, progress=progress, cancel=cancel)
        if os.path.exists(dst):
            raise FileExistsError(dst)
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    _put_times(dst, times)
    after = on_disk_size(dst)
    kept = False
    try:
        os.remove(src)
    except OSError:
        kept = True                 # in use: both stay, nothing is lost
    shell_refresh(dst)
    return MoveResult(src, dst, size, before, after,
                      sparse_ok=not (after >= size
                                     and data + MIN_HOLE <= size),
                      kept=kept, seconds=time.monotonic() - t0)


def _open_archive(src):
    """``(stream, size or None, member name)`` for a compressed download."""
    low = src.lower()
    if low.endswith(".zip"):
        z = zipfile.ZipFile(src)
        members = [i for i in z.infolist()
                   if i.filename.lower().endswith(IMAGE_SUFFIXES)
                   and not i.is_dir()]
        if len(members) != 1:
            z.close()
            raise ValueError("%s holds %d card images; expected one"
                             % (src, len(members)))
        m = members[0]
        return z.open(m), m.file_size, os.path.basename(m.filename)
    base = os.path.basename(src)[: src.rfind(".") - len(src)]
    if low.endswith(".xz"):
        return lzma.open(src, "rb"), None, base
    if low.endswith(".gz"):
        return gzip.open(src, "rb"), None, base
    if low.endswith(".bz2"):
        return bz2.open(src, "rb"), None, base
    raise ValueError("not a compressed card download: %s" % src)


def import_card(src, dest_dir, *, progress=None, log=None, replace=False):
    """Bring a new card image into *dest_dir* compact.  *src* is a .raw/.img
    (copied sparse) or a .zip/.xz/.gz/.bz2 holding one (unpacked straight
    into a sparse file, never full size on disk).  Written as ``.part`` and
    renamed when whole.  Returns the new path."""
    low = src.lower()
    if low.endswith(ARCHIVE_SUFFIXES):
        stream, size, name = _open_archive(src)
    else:
        stream, size, name = None, os.path.getsize(src), os.path.basename(src)
    dst = os.path.join(dest_dir, name)
    if os.path.exists(dst) and not replace:
        if stream is not None:
            stream.close()
        raise FileExistsError(dst)
    part = dst + ".part"
    try:
        if stream is None:
            sparse_copy(src, part, progress=progress)
            _put_times(part, _times(src))
        else:
            _unpack_sparse(stream, part, size, progress)
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    finally:
        if stream is not None:
            stream.close()
    if log:
        log("%s: %.2f GB card, %.2f GB on disk"
            % (name, os.path.getsize(dst) / 1e9, on_disk_size(dst) / 1e9))
    return dst


def _unpack_sparse(stream, part, size, progress):
    if size is None:
        # an .xz/.gz stream does not say how big it unpacks: grow as it goes
        with open(part, "w+b", buffering=0) as f:
            sparse = _set_sparse(f)
            pos = 0
            while True:
                b = stream.read(CHUNK)
                if not b:
                    break
                _write_blocks(f, pos, b, sparse)
                pos += len(b)
                if progress:
                    progress(pos, 0)
            f.truncate(pos)
            if sparse and sys.platform == "win32":
                # truncate past the last write allocates on NTFS: free the
                # tail again (it is zeros the stream ended on)
                last = _last_data_end(f, pos)
                if last < pos:
                    _punch(f, last, pos - last)
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        return
    w = _SparseWriter(part, size)
    try:
        pos = 0
        while True:
            b = stream.read(CHUNK)
            if not b:
                break
            w.write_at(pos, b)
            pos += len(b)
            if progress:
                progress(pos, size)
        if not w.sparse:
            w.f.truncate(size)
    finally:
        w.close()
    if pos != size:
        raise OSError("%s unpacked to %d bytes, expected %d" % (part, pos, size))


def _write_blocks(f, pos, b, sparse):
    i = 0
    n = len(b)
    while i < n:
        j = min(n, i + BLOCK)
        piece = b[i:j]
        if not sparse or piece != _ZERO_BLOCK[:len(piece)]:
            f.seek(pos + i)
            f.write(piece)
        i = j


def _last_data_end(f, size):
    r = allocated_ranges(f, size)
    return r[-1][0] + r[-1][1] if r else 0


# ---------------------------------------------------------------- expand


class NoRoom(OSError):
    """The drive has not got the room a full-size card needs."""


def _need_room(folder, need, what="the full-size card needs %.1f GB more"):
    import shutil
    free = shutil.disk_usage(folder).free
    if free < need:
        raise NoRoom(("%s has %.1f GB free; " + what)
                     % (folder, free / 1e9, need / 1e9))


def hole_ranges(f, size):
    """The ``(offset, length)`` holes of open file *f* (the complement of
    :func:`allocated_ranges`)."""
    out = []
    pos = 0
    for off, n in allocated_ranges(f, size):
        if off > pos:
            out.append((pos, off - pos))
        pos = max(pos, off + n)
    if pos < size:
        out.append((pos, size - pos))
    return out


def is_compact(path):
    """True when *path* has holes (it is stored compact)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        return bool(hole_ranges(f, size))


def expand_copy(src, dst, *, progress=None, cancel=None):
    """Write a FULL-SIZE copy of card *src* at *dst*: every byte on disk, the
    form a drive without sparse files (exFAT, FAT32) or another program's
    plain copy wants.  Written as ``.part`` and renamed when whole."""
    size = os.path.getsize(src)
    _need_room(os.path.dirname(os.path.abspath(dst)) or ".", size)
    part = dst + ".part"
    done = 0
    try:
        with open(src, "rb", buffering=0) as fi, \
                open(part, "wb", buffering=0) as fo:
            while True:
                if cancel:
                    cancel()
                b = fi.read(CHUNK)
                if not b:
                    break
                fo.write(b)
                done += len(b)
                if progress:
                    progress(done, size)
            _flush(fo)
        _put_times(part, _times(src))
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dst


def expand_file(path, *, progress=None, cancel=None):
    """Make the compact card at *path* full size again where it is: its
    holes are written out as zeros and (Windows) the sparse mark cleared.
    The bytes do not change, nor does its modified time.  Returns the bytes
    filled in."""
    times = _times(path)
    try:
        return _expand_open(path, progress=progress, cancel=cancel)
    finally:
        _put_times(path, times)
        shell_refresh(path)


def _expand_open(path, *, progress, cancel):
    size = os.path.getsize(path)
    with open(path, "r+b", buffering=0) as f:
        holes = hole_ranges(f, size)
        need = sum(n for _o, n in holes)
        if need:
            _need_room(os.path.dirname(os.path.abspath(path)) or ".", need)
        done = 0
        for off, n in holes:
            f.seek(off)
            left = n
            while left:
                if cancel:
                    cancel()
                k = min(CHUNK, left)
                f.write(_ZERO_CHUNK[:k])
                left -= k
                done += k
                if progress:
                    progress(done, need)
        _flush(f)
        if sys.platform == "win32":
            # FILE_SET_SPARSE_BUFFER.SetSparse = FALSE: allowed once no hole
            # is left
            rd._win_fsctl(f, rd._FSCTL_SET_SPARSE, ctypes.c_ubyte(0))
    return need


# ---------------------------------------------------------------- the library


def is_image(name):
    low = name.lower()
    return low.endswith(IMAGE_SUFFIXES) and not low.endswith(".part")


def compact_folder(folder, *, recursive=False, min_hole=MIN_HOLE,
                   log=print, progress=None):
    """:func:`compact_file` over every card image in *folder*.  Returns the
    list of results."""
    out = []
    for root, dirs, files in os.walk(folder):
        for name in sorted(files):
            if not is_image(name):
                continue
            p = os.path.join(root, name)
            try:
                r = compact_file(p, min_hole=min_hole,
                                 progress=(lambda d, t, _n=name:
                                           progress(_n, d, t))
                                 if progress else None)
            except OSError as e:
                if log:
                    log("%s: skipped (%s)" % (name, e))
                continue
            out.append(r)
            if log:
                log(describe(r))
        if not recursive:
            break
    return out


def describe(r):
    name = os.path.basename(r.path)
    if not r.sparse_ok and r.after >= r.size:
        return "%s: left as it was (%s)" % (name, "; ".join(r.notes))
    return ("%s: %.2f GB card, %.2f GB on disk (was %.2f GB, %.2f GB freed)"
            " in %.0f s" % (name, r.size / 1e9, r.after / 1e9, r.before / 1e9,
                            r.saved / 1e9, r.seconds))


def _meter():
    last = [0.0]

    def show(name, done, total):
        now = time.monotonic()
        if now - last[0] < 2 and done < total:
            return
        last[0] = now
        pct = done * 100 // total if total else 0
        sys.stderr.write("\r  %s: %d%% of %.1f GB read   "
                         % (name, pct, total / 1e9))
        sys.stderr.flush()
        if done >= total:
            sys.stderr.write("\n")
    return show


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m pinball_decryptor.core.sparse_card",
        description="Store card images compact (sparse): the same .raw files, "
                    "the same bytes, only the data on disk.  Give folders or "
                    "images to compact them in place; --into DIR to import "
                    "new images (or .zip/.xz/.gz downloads) compact; "
                    "--expand / --expand-to DIR for full size again.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--into", metavar="DIR",
                    help="import PATHS into DIR compact instead")
    ap.add_argument("--recursive", action="store_true",
                    help="also the folders inside (not by default: a "
                         "library's 'older versions' stays as it is)")
    ap.add_argument("--replace", action="store_true",
                    help="with --into: replace an image already there")
    ap.add_argument("--expand", action="store_true",
                    help="make PATHS full size again where they are")
    ap.add_argument("--expand-to", metavar="DIR",
                    help="write a full-size copy of PATHS into DIR")
    a = ap.parse_args(argv)
    meter = _meter()
    if a.expand or a.expand_to:
        for p in a.paths:
            prog = (lambda d, t, _n=os.path.basename(p): meter(_n, d, t))
            if a.expand_to:
                dst = expand_copy(p, os.path.join(a.expand_to,
                                                  os.path.basename(p)),
                                  progress=prog)
                print("full-size copy: %s" % dst)
            else:
                n = expand_file(p, progress=prog)
                print("%s: full size (%.2f GB filled in)"
                      % (os.path.basename(p), n / 1e9))
        return 0
    freed = 0
    for p in a.paths:
        if a.into:
            dst = import_card(p, a.into, replace=a.replace, log=print,
                              progress=lambda d, t, _n=os.path.basename(p):
                              meter(_n, d, t or d + 1))
            print("imported %s" % dst)
            continue
        if os.path.isdir(p):
            rs = compact_folder(p, recursive=a.recursive, progress=meter)
        else:
            rs = [compact_file(p, progress=lambda d, t, _n=os.path.basename(p):
                               meter(_n, d, t))]
            print(describe(rs[0]))
        freed += sum(r.saved for r in rs)
    if not a.into:
        print("%.2f GB freed" % (freed / 1e9))
    return 0


if __name__ == "__main__":                      # pragma: no cover
    sys.exit(main())
