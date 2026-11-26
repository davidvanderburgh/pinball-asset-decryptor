"""Godot 4 resource packs (``.pck``) on a Stern card, and the textures in them
(PAD-1621).

Stern's Pokemon (LE and Pro, Spike 3) draws its pokedex, battle and arena
screens with a Godot 4.4 game whose resources are one plain pack,
``assets/godot/main.pck``: the scenes' pictures as compressed textures
(``.godot/imported/<name>.png-<hash>.ctex``), their background clips as the
MP4 files themselves.  This module reads that pack and builds a new one with
some files replaced; :mod:`.spike3_godot` uses it for Extract and Write.

The pack (format 2, Godot 4.0-4.4)::

    "GDPC" u32 format(2) u32 major u32 minor u32 patch u32 flags
    u64 file_base  16 x u32 reserved  u32 file_count
    file_count x { u32 path_len, path (NUL-padded to 4), u64 offset (from
                   file_base), u64 size, md5[16], u32 flags }
    ...the files, each padded to 16 bytes...

An encrypted pack (flag 1, BoF's) or one of another format is refused with a
message; the BoF plugin has its own road for those.

A ``.ctex`` (``GST2``) texture::

    "GST2" u32 version u32 width u32 height u32 flags u32 mipmap_limit
    3 x u32 reserved
    u32 data_format u16 width u16 height u32 mipmaps u32 image_format
    (mipmaps + 1) x { u32 size, the level as a PNG / WebP file }

for data_format 1 (PNG) and 2 (WebP); every one of Pokemon's is a lossless
WebP, so a picture comes out and goes back exactly.  A level is
``max(1, w >> i) x max(1, h >> i)``.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct

MAGIC = b"GDPC"
CTEX_MAGIC = b"GST2"
ALIGN = 16
_HDR = 4 + 5 * 4 + 8 + 16 * 4          # through the reserved words
_PACK_ENCRYPTED = 1
_FILE_ENCRYPTED = 1
_FILE_REMOVAL = 2

#: the clip files a pack carries as themselves (Godot plays them from there)
VIDEO_EXTS = (".mp4", ".webm", ".ogv", ".mov", ".m4v")

#: ctex data formats: the levels are image files
DF_PNG, DF_WEBP = 1, 2
#: Godot Image::Format -> Pillow mode, the 8-bit ones a picture can be
_MODES = {0: "L", 1: "LA", 4: "RGB", 5: "RGBA"}


class PckError(ValueError):
    """Not a pack this module reads (another format, encrypted, damaged)."""


class Entry:
    __slots__ = ("path", "offset", "size", "md5", "flags", "raw_path")

    def __init__(self, path, offset, size, md5, flags, raw_path):
        self.path = path            # "scenes/x/y.png.import" (no res://)
        self.offset = offset        # absolute, in the pack file
        self.size = size
        self.md5 = md5
        self.flags = flags
        self.raw_path = raw_path    # the directory's own (padded) bytes

    def __repr__(self):
        return "Entry(%r, %d, %d)" % (self.path, self.offset, self.size)


class Pack:
    """A parsed pack: its header bytes, its entries in directory order."""

    def __init__(self, header, file_base, entries):
        self.header = header
        self.file_base = file_base
        self.entries = entries
        self.by_path = {e.path: e for e in entries}

    def version(self):
        return struct.unpack_from("<4I", self.header, 4)


def is_pack(head):
    return head[:4] == MAGIC


def parse(read):
    """The pack *read* reads from (``read(offset, n) -> bytes``)."""
    head = read(0, _HDR + 4)
    if len(head) < _HDR + 4 or head[:4] != MAGIC:
        raise PckError("not a Godot pack")
    fmt, major, minor, _patch, flags = struct.unpack_from("<5I", head, 4)
    if fmt != 2:
        raise PckError("Godot pack format %d (Godot %d.%d) is not read yet"
                       % (fmt, major, minor))
    if flags & _PACK_ENCRYPTED:
        raise PckError("the pack's directory is encrypted")
    file_base, = struct.unpack_from("<Q", head, 24)
    count, = struct.unpack_from("<I", head, _HDR)
    blob = read(_HDR + 4, max(0, file_base - _HDR - 4))
    pos, entries = 0, []
    try:
        for _ in range(count):
            n, = struct.unpack_from("<I", blob, pos)
            raw = blob[pos + 4:pos + 4 + n]
            pos += 4 + n
            off, size = struct.unpack_from("<QQ", blob, pos)
            md5 = blob[pos + 16:pos + 32]
            fl, = struct.unpack_from("<I", blob, pos + 32)
            pos += 36
            path = raw.rstrip(b"\0").decode("utf-8")
            if path.startswith("res://"):
                path = path[6:]
            entries.append(Entry(path, file_base + off, size, md5, fl, raw))
    except (struct.error, UnicodeDecodeError) as e:
        raise PckError("the pack's directory is damaged (%s)" % e) from None
    return Pack(bytes(head[:_HDR]), file_base, entries)


def parse_file(path):
    with open(path, "rb") as f:
        def read(off, n):
            f.seek(off)
            return f.read(n)
        return parse(read)


def readable(entry):
    """Can this entry's bytes be taken as they are (not encrypted/removed)?"""
    return not entry.flags & (_FILE_ENCRYPTED | _FILE_REMOVAL)


def _pad(n):
    return (-n) % ALIGN


def rewrite(pack, read, out, subs, chunk=4 << 20):
    """Write a pack to the file object *out*: *pack* (read through *read*)
    with ``subs`` (``{entry path: new bytes}``) in place of those files.
    The files keep the pack's own order, each padded to 16 bytes; the
    directory's offsets, sizes and MD5s are the new ones.  Returns the
    number of bytes written."""
    missing = set(subs) - set(pack.by_path)
    if missing:
        raise PckError("not in the pack: %s" % ", ".join(sorted(missing)))
    order = sorted(pack.entries, key=lambda e: e.offset)
    dir_len = 4 + sum(4 + len(e.raw_path) + 36 for e in pack.entries)
    file_base = _HDR + dir_len
    file_base += _pad(file_base)
    placed, pos = {}, 0
    md5s = {}
    for e in order:
        size = len(subs[e.path]) if e.path in subs else e.size
        placed[e.path] = (pos, size)
        pos += size + _pad(size)
        if e.path in subs:
            md5s[e.path] = hashlib.md5(subs[e.path]).digest()
    head = bytearray(pack.header)
    struct.pack_into("<Q", head, 24, file_base)
    body = bytearray(struct.pack("<I", len(pack.entries)))
    for e in pack.entries:
        off, size = placed[e.path]
        body += struct.pack("<I", len(e.raw_path)) + e.raw_path
        body += struct.pack("<QQ", off, size)
        body += md5s.get(e.path, e.md5) + struct.pack("<I", e.flags)
    out.write(bytes(head) + bytes(body) + b"\0" * (file_base - _HDR - len(body)))
    total = file_base
    for e in order:
        if e.path in subs:
            data = subs[e.path]
            out.write(data)
            n = len(data)
        else:
            n, left, src = 0, e.size, e.offset
            while left:
                b = read(src, min(chunk, left))
                if not b:
                    raise PckError("the pack ended inside %s" % e.path)
                out.write(b)
                src += len(b)
                left -= len(b)
                n += len(b)
        out.write(b"\0" * _pad(n))
        total += n + _pad(n)
    return total


# --------------------------------------------------------------------------
# The pack's pictures: an import record names each texture's source
# --------------------------------------------------------------------------

_IMPORT_PATH_RE = re.compile(r'^path(?:\.\w+)?="res://([^"]+)"', re.M)
_IMPORT_TYPE_RE = re.compile(r'^type="(\w+)"', re.M)


def texture_sources(pack, read):
    """``{ctex entry path: source path}`` from the pack's ``.import`` records
    (``scenes/pokedex/gfx/001_BULBASAUR.png`` for its ctex), the textures
    only."""
    out = {}
    for e in pack.entries:
        if not e.path.endswith(".import") or not readable(e):
            continue
        text = read(e.offset, e.size).decode("utf-8", "replace")
        m = _IMPORT_TYPE_RE.search(text)
        if not m or m.group(1) != "CompressedTexture2D":
            continue
        for p in _IMPORT_PATH_RE.findall(text):
            if p.endswith(".ctex") and p in pack.by_path:
                out.setdefault(p, e.path[:-len(".import")])
    return out


# --------------------------------------------------------------------------
# GST2 textures
# --------------------------------------------------------------------------

class Texture:
    """A ctex's header and its levels (the image files' bytes)."""

    def __init__(self, data):
        if data[:4] != CTEX_MAGIC or len(data) < 56:
            raise PckError("not a GST2 texture")
        self.prefix = bytes(data[:36])
        (self.data_format, self.width, self.height, self.mipmaps,
         self.image_format) = struct.unpack_from("<IHHII", data, 36)
        self.levels = []
        if self.data_format not in (DF_PNG, DF_WEBP):
            return
        pos = 52
        for _ in range(self.mipmaps + 1):
            if pos + 4 > len(data):
                raise PckError("the texture ends inside a level")
            n, = struct.unpack_from("<I", data, pos)
            self.levels.append(bytes(data[pos + 4:pos + 4 + n]))
            pos += 4 + n

    @property
    def mode(self):
        return _MODES.get(self.image_format)

    def picture_ok(self):
        """Is this a texture a picture comes out of and goes back into?"""
        return bool(self.levels) and self.mode is not None

    def level_size(self, i):
        return max(1, self.width >> i), max(1, self.height >> i)


def decode_texture(data):
    """The ctex *data*'s full-size picture (a Pillow image in its own mode),
    or ``None`` for a texture that is not a PNG/WebP picture (a GPU-
    compressed one)."""
    from PIL import Image
    tex = Texture(data)
    if not tex.picture_ok():
        return None
    im = Image.open(io.BytesIO(tex.levels[0]))
    im.load()
    if im.mode != tex.mode:
        im = im.convert(tex.mode)
    return im


def encode_texture(image, orig):
    """A ctex like the original *orig* (its header, its level count and
    format) holding the Pillow *image*: scaled to the texture's size when it
    is not that size, every mip level made from it, each saved as the
    original's levels are (lossless WebP / PNG)."""
    from PIL import Image
    tex = Texture(orig)
    if not tex.picture_ok():
        raise PckError("this texture is not a picture PAD can rebuild")
    im = image.convert(tex.mode)
    if im.size != (tex.width, tex.height):
        im = im.resize((tex.width, tex.height), Image.LANCZOS)
    out = bytearray(tex.prefix)
    out += struct.pack("<IHHII", tex.data_format, tex.width, tex.height,
                       tex.mipmaps, tex.image_format)
    for i in range(tex.mipmaps + 1):
        size = tex.level_size(i)
        lvl = im if size == im.size else im.resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        if tex.data_format == DF_WEBP:
            lvl.save(buf, "WEBP", lossless=True, quality=100, method=4,
                     exact=True)
        else:
            lvl.save(buf, "PNG")
        b = buf.getvalue()
        out += struct.pack("<I", len(b)) + b
    return bytes(out)
