"""A small, read-only **SquashFS 4.0** reader (pure Python, PAD-1641).

Stern's Spike 2 update package (``<title>-<a>_<b>_<c>.spk``, published as a
split ``.spk.zip``) is a plain SquashFS image - not encrypted - holding one
file: the same SPKS archive (:mod:`.spks`) a Spike 3 package keeps behind its
LUKS layer.  This module reads just what that needs: the superblock, the inode
and directory tables, and a file's contents with random access (each data
block is decompressed when first read; a few stay cached so a sequential read
decompresses every block once).

Compressors: gzip (zlib, Stern's), xz and lzma from the standard library, zstd
when the interpreter has it.  Anything else is a clear :class:`SquashfsError`.
"""

from __future__ import annotations

import struct
import zlib
from collections import OrderedDict

MAGIC = b"hsqs"

_GZIP, _LZMA, _LZO, _XZ, _LZ4, _ZSTD = 1, 2, 3, 4, 5, 6
_NAMES = {_GZIP: "gzip", _LZMA: "lzma", _LZO: "lzo", _XZ: "xz",
          _LZ4: "lz4", _ZSTD: "zstd"}

# inode types
DIR, FILE, SYMLINK = 1, 2, 3
LDIR, LFILE, LSYMLINK = 8, 9, 10

_META_MAX = 8192
_NO_FRAG = 0xFFFFFFFF
_UNCOMPRESSED_DATA = 1 << 24


class SquashfsError(Exception):
    pass


def _decompressor(comp):
    if comp == _GZIP:
        return zlib.decompress
    if comp in (_XZ, _LZMA):
        import lzma
        fmt = lzma.FORMAT_XZ if comp == _XZ else lzma.FORMAT_ALONE
        return lambda b: lzma.decompress(b, format=fmt)
    if comp == _ZSTD:
        try:
            from compression import zstd            # Python 3.14+
            return zstd.decompress
        except ImportError:
            pass
        try:
            import zstandard                         # noqa: F401
            return lambda b: zstandard.ZstdDecompressor().decompress(
                b, max_output_size=1 << 24)
        except ImportError:
            pass
    raise SquashfsError("this package is compressed with %s, which this app "
                        "cannot read" % _NAMES.get(comp, "compressor %d" % comp))


class Inode:
    """One inode: ``kind`` (DIR/FILE/SYMLINK/other type number), ``mode``
    (permission bits), ``size`` and the fields its kind needs."""
    __slots__ = ("kind", "mode", "number", "size", "blocks_start", "blocks",
                 "frag", "frag_off", "dir_block", "dir_offset", "target")

    def __init__(self, kind, mode, number):
        self.kind, self.mode, self.number = kind, mode, number
        self.size = 0
        self.blocks_start = 0
        self.blocks = ()
        self.frag = _NO_FRAG
        self.frag_off = 0
        self.dir_block = self.dir_offset = 0
        self.target = b""

    @property
    def is_dir(self):
        return self.kind in (DIR, LDIR)

    @property
    def is_file(self):
        return self.kind in (FILE, LFILE)

    @property
    def is_symlink(self):
        return self.kind in (SYMLINK, LSYMLINK)


class SquashfsReader:
    """Read-only SquashFS over *f* (a seekable binary file) starting at byte
    *base*."""

    def __init__(self, f, base=0, cache_blocks=8):
        self.f = f
        self.base = base
        sb = self._raw(0, 96)
        if len(sb) < 96 or sb[:4] != MAGIC:
            raise SquashfsError("not a SquashFS image")
        (self.inode_count, _mtime, self.block_size, self.frag_count, comp,
         _blog, self.flags, _ids, vmaj, _vmin) = struct.unpack_from(
             "<IIIIHHHHHH", sb, 4)
        if vmaj != 4:
            raise SquashfsError("SquashFS version %d is not supported" % vmaj)
        (self.root_ref, self.bytes_used, _id_t, _xattr_t, self.inode_table,
         self.dir_table, self.frag_table, _export_t) = struct.unpack_from(
             "<QQQQQQQQ", sb, 32)
        self.compressor = _NAMES.get(comp, str(comp))
        self._decompress = _decompressor(comp)
        self._meta_cache = {}
        self._frags = None
        self._blocks = OrderedDict()
        self._cache_max = max(1, cache_blocks)

    # ---- raw + metadata -------------------------------------------------
    def _raw(self, off, n):
        self.f.seek(self.base + off)
        return self.f.read(n)

    def _meta_block(self, pos):
        """``(data, next_pos)`` of the metadata block at absolute *pos*."""
        got = self._meta_cache.get(pos)
        if got is None:
            hdr = struct.unpack("<H", self._raw(pos, 2))[0]
            n = hdr & 0x7FFF
            raw = self._raw(pos + 2, n)
            data = raw if hdr & 0x8000 else self._decompress(raw)
            got = (data, pos + 2 + n)
            if len(self._meta_cache) > 4096:
                self._meta_cache.clear()
            self._meta_cache[pos] = got
        return got

    def _meta_read(self, start, block, offset, n):
        """*n* bytes of the metadata stream beginning at table *start*, at the
        block *block* bytes into it and *offset* into that block's data."""
        pos = start + block
        out = bytearray()
        data, nxt = self._meta_block(pos)
        out += data[offset:]
        while len(out) < n:
            data, nxt = self._meta_block(nxt)
            out += data
        return bytes(out[:n])

    # ---- inodes ---------------------------------------------------------
    def inode(self, ref):
        """The :class:`Inode` an inode reference (``block << 16 | offset``)
        names."""
        block, offset = ref >> 16, ref & 0xFFFF
        head = self._meta_read(self.inode_table, block, offset, 16 + 40)
        kind, mode, _uid, _gid, _mt, number = struct.unpack_from("<HHHHII",
                                                                 head, 0)
        ino = Inode(kind, mode, number)
        bs = self.block_size
        if kind == DIR:
            ino.dir_block, _nl, size, ino.dir_offset, _par = struct.unpack_from(
                "<IIHHI", head, 16)
            ino.size = size
        elif kind == LDIR:
            _nl, size, ino.dir_block, _par, _ic, ino.dir_offset = \
                struct.unpack_from("<IIIIHH", head, 16)
            ino.size = size
        elif kind in (FILE, LFILE):
            if kind == FILE:
                start, frag, frag_off, size = struct.unpack_from("<IIII", head, 16)
                fixed = 32
            else:
                start, size, _sparse, _nl, frag, frag_off, _x = struct.unpack_from(
                    "<QQQIIII", head, 16)
                fixed = 56
            n = size // bs if frag != _NO_FRAG else -(-size // bs)
            body = self._meta_read(self.inode_table, block, offset,
                                   fixed + 4 * n)
            ino.blocks = struct.unpack_from("<%dI" % n, body, fixed)
            ino.blocks_start, ino.size = start, size
            ino.frag, ino.frag_off = frag, frag_off
        elif kind in (SYMLINK, LSYMLINK):
            _nl, tsize = struct.unpack_from("<II", head, 16)
            body = self._meta_read(self.inode_table, block, offset, 24 + tsize)
            ino.target = body[24:24 + tsize]
            ino.size = tsize
        return ino

    def root(self):
        return self.inode(self.root_ref)

    def listdir(self, ino):
        """``[(name bytes, inode ref, type)]`` for directory *ino*."""
        if not ino.is_dir:
            raise SquashfsError("not a directory")
        total = ino.size - 3
        if total <= 0:
            return []
        data = self._meta_read(self.dir_table, ino.dir_block, ino.dir_offset,
                               total)
        out = []
        p = 0
        while p + 12 <= len(data):
            count, start, _base = struct.unpack_from("<IIi", data, p)
            p += 12
            for _ in range(count + 1):
                off, _delta, typ, nsize = struct.unpack_from("<HhHH", data, p)
                name = data[p + 8:p + 9 + nsize]
                p += 9 + nsize
                out.append((name, (start << 16) | off, typ))
        return out

    def walk(self, ino=None, prefix=""):
        """Every entry under *ino* (the root by default) as ``(path, Inode)``,
        depth first; paths have no leading slash."""
        ino = ino or self.root()
        for name, ref, _t in self.listdir(ino):
            child = self.inode(ref)
            path = prefix + name.decode("utf-8", "surrogateescape")
            yield path, child
            if child.is_dir:
                yield from self.walk(child, path + "/")

    # ---- file data ------------------------------------------------------
    def _fragment(self, index):
        if self._frags is None:
            self._frags = {}
        got = self._frags.get(index)
        if got is None:
            ptr_off = self.frag_table + (index // 512) * 8
            meta = struct.unpack("<Q", self._raw(ptr_off, 8))[0]
            ent = self._meta_read(meta, 0, (index % 512) * 16, 16)
            start, size, _u = struct.unpack("<QII", ent)
            got = self._frags[index] = (start, size)
        return got

    def _block(self, key, pos, word):
        got = self._blocks.get(key)
        if got is not None:
            self._blocks.move_to_end(key)
            return got
        n = word & ~_UNCOMPRESSED_DATA & 0xFFFFFFFF
        if n == 0:
            got = bytes(self.block_size)               # a sparse block
        else:
            raw = self._raw(pos, n)
            got = raw if word & _UNCOMPRESSED_DATA else self._decompress(raw)
        self._blocks[key] = got
        if len(self._blocks) > self._cache_max:
            self._blocks.popitem(last=False)
        return got

    def _file_layout(self, ino):
        """Absolute start of each of *ino*'s data blocks (cached on it)."""
        lay = getattr(self, "_layouts", None)
        if lay is None:
            lay = self._layouts = {}
        got = lay.get(ino.number)
        if got is None:
            pos, starts = ino.blocks_start, []
            for w in ino.blocks:
                starts.append(pos)
                pos += w & ~_UNCOMPRESSED_DATA & 0xFFFFFFFF
            got = lay[ino.number] = starts
        return got

    def read(self, ino, offset, length):
        """Bytes ``[offset, offset+length)`` of regular file *ino* (clamped to
        its size)."""
        if not ino.is_file:
            raise SquashfsError("not a regular file")
        if offset >= ino.size or length <= 0:
            return b""
        end = min(ino.size, offset + length)
        bs = self.block_size
        starts = self._file_layout(ino)
        out = bytearray()
        pos = offset
        while pos < end:
            i = pos // bs
            if i < len(ino.blocks):
                data = self._block((ino.number, i), starts[i], ino.blocks[i])
                lo = pos - i * bs
            else:                                       # the tail fragment
                fstart, fsize = self._fragment(ino.frag)
                data = self._block(("f", ino.frag), fstart, fsize)
                lo = ino.frag_off + (pos - i * bs)
            take = min(end - pos, bs - (pos - i * bs))
            out += data[lo:lo + take]
            pos += take
        return bytes(out)


class SquashfsFileReader:
    """``read(offset, length)`` over one file inside a SquashFS image - the
    shape :class:`.spks.SpksArchive` reads through."""

    def __init__(self, sqfs, ino):
        self.sqfs, self.ino = sqfs, ino
        self.size = ino.size

    def __call__(self, offset, length):
        return self.sqfs.read(self.ino, offset, length)


def is_squashfs(path_or_head):
    """True if the bytes (or the file at the path) start with the SquashFS
    magic."""
    if isinstance(path_or_head, (bytes, bytearray)):
        return bytes(path_or_head[:4]) == MAGIC
    try:
        with open(path_or_head, "rb") as f:
            return f.read(4) == MAGIC
    except OSError:
        return False
