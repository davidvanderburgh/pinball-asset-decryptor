"""Stern S.A.M. DMD art: read every still picture and font glyph out of a
code update, and write replacements back in place.

Worked out from the files and the game's renderer (PAD-583, with PAD-584
which decodes the animations; see docs/plans/sam_compatibility.md):

*Two tables* name all the art: a font table (20-byte records) and, right
after it, the *picture table*, one bank pointer (``bank << 24 | offset``,
as for the sounds) per picture number -- the number the game code draws
by.  The code keeps their addresses as four words in a row,
``font count, font table, picture count, picture table`` (World Poker
Tour: the pairs swapped), so they are found by that pattern (the picture
table starts where the font table's records end).

*A picture record* is a header and its data.  From 2007 on the header is
``u32 id, u32 flags, s16 width, s16 height, u8 format`` (13 bytes); the
first titles (World Poker Tour, Family Guy, Pirates of the Caribbean,
Wheel of Fortune) have only ``s16 width, s16 height, u8 format`` (5
bytes).  Format 0 is one byte per
pixel, row by row; 12 is four bits per pixel, low nibble first.  The rest
(1/7 run-length, 3/9 delta frames that patch the picture before them) are
animation frames, :mod:`.sam_anim`'s.  A pixel is a shade ``0..15`` or
``0xFF``, transparent.

*Pictures here* are the plain ones -- format 0 or 12 -- whose pixels are
all shades or transparent and end before the next record, and that no
delta frame builds on: service-menu icons, still pictures, every font
glyph, and the animation frames stored whole.  (The id's high half is no
guide: Metallica 1.64 sets it on every still.)

*A font* record is ``u32 end, u32 start`` of its glyph array, then its
height; the array has one entry per character, ``(bank pointer to the
glyph's picture, s16 x offset, s16 y offset)``, 8 bytes (12 on the 2012
titles on).  Which character each entry draws is the code's business:
the fonts don't share one map (some leave out ``&``, some add a glyph
after ``Z``), so glyphs are known by their picture numbers only.

A replacement keeps the record's place and size, so nothing else in the
image moves; the checksums are :func:`.sam_sound.fix_checksums`' job.
"""

import struct
from dataclasses import dataclass, field

import numpy as np

from .sam_sound import file_offset

#: the pixel byte of a transparent pixel
TRANSPARENT = 0xFF
#: shades a pixel can be (0 = off .. 15 = full)
SHADES = 16
#: formats of the plain pictures: one byte a pixel, four bits a pixel
RAW8 = 0
RAW4 = 12
#: formats that patch the picture before them (PAD-584: 10 is the
#: 2008-2010 engine's 9; its 8 is a whole run-length frame, format 7)
_DELTAS = (3, 9, 10)

_VALID = np.zeros(256, bool)
_VALID[:SHADES] = True
_VALID[TRANSPARENT] = True

_FONT_RECORD = 20
_SCAN = 0x200000


class SamArtError(Exception):
    """The file's pictures could not be read."""


@dataclass(frozen=True)
class Bitmap:
    """A plain picture record."""
    number: int        # its place in the picture table (the game's number)
    offset: int        # of the record's header in the file
    header: int        # header length: 13, or 5 on the first titles
    width: int
    height: int
    fmt: int           # RAW8 or RAW4

    @property
    def data_offset(self):
        return self.offset + self.header

    @property
    def data_size(self):
        n = self.width * self.height
        return n if self.fmt == RAW8 else (n + 1) // 2


@dataclass(frozen=True)
class Font:
    number: int        # its place in the font table, from 0
    height: int
    glyphs: tuple      # picture numbers, in character order (None: none)


@dataclass
class Art:
    fonts_at: int                    # file offset of the font table
    table: int                       # file offset of the picture table
    entries: int                     # pointers in it
    header: int                      # record header length (13 or 5)
    bitmaps: dict                    # picture number -> Bitmap (plain ones)
    fonts: list = field(default_factory=list)
    #: picture number -> (font number, glyph index), its first font
    glyph_of: dict = field(default_factory=dict)


def find_tables(data):
    """``(font table, font count, picture table, picture count)``: the
    code's four words that name them -- ``font count, font table, picture
    count, picture table``, or (World Poker Tour) the two pairs the other
    way round."""
    n = min(len(data), _SCAN) // 4
    a = np.frombuffer(data, "<u4", count=n).astype(np.int64)
    off = ((a >> 24) << 23) | (a & 0xFFFFFF)
    for f, g in ((0, 2), (2, 0)):
        nf, pf = a[f:n - 3 + f], off[f + 1:n - 2 + f]
        ng, pg = a[g:n - 3 + g], off[g + 1:n - 2 + g]
        hit = np.nonzero((nf > 1) & (nf < 400) & (ng > 16) & (ng < 0x10000)
                         & (pf < len(data))
                         & (pg == pf + _FONT_RECORD * nf)
                         & (pg + 4 * ng <= len(data)))[0]
        if len(hit):
            k = int(hit[0])
            return (int(off[k + f + 1]), int(a[k + f]),
                    int(off[k + g + 1]), int(a[k + g]))
    raise SamArtError("this file's picture table can't be found")


def _header_len(data, offs):
    """13 when the records carry an id and flags, 5 on the first titles."""
    def plausible(at):
        ok = 0
        for o in offs:
            if o + at + 4 <= len(data):
                w, h = struct.unpack_from("<hh", data, o + at)
                ok += 0 < w <= 1024 and 0 < h <= 64
        return ok
    return 13 if plausible(8) >= plausible(0) else 5


def _glyph_array(data, start, end, numbers):
    """Picture numbers of a font's glyph array, or None.  Its entries are
    8 bytes (pointer, x, y) or, from 2012, 12; on some titles the font
    record's words carry no bank, so each bank is tried for the one whose
    entries are all pictures."""
    span = end - start
    for stride in (8, 12):
        count = span // stride
        if count <= 0 or count > 256 or span % stride:
            continue
        base = file_offset(start)
        for bank in range(16):
            at = base if bank == 0 else (bank << 23) | (start & 0x7FFFFF)
            if at + span > len(data):
                continue
            out = []
            for i in range(count):
                p = struct.unpack_from("<I", data, at + stride * i)[0]
                n = numbers.get(file_offset(p)) if p else None
                if p and n is None:
                    break
                out.append(n)
            else:
                if sum(g is not None for g in out) * 2 > count:
                    return tuple(out)
    return None


def read_art(data):
    """The :class:`Art` of a SAM image (bytes)."""
    fonts_at, n_fonts, table, count = find_tables(data)
    ptrs = struct.unpack_from(f"<{count}I", data, table)
    offs = [file_offset(p) for p in ptrs]
    hl = _header_len(data, offs[:256])
    # where the next record (or a table) begins after each one
    starts = sorted(set(offs) | {table, fonts_at})
    after = {o: (starts[i + 1] if i + 1 < len(starts) else len(data))
             for i, o in enumerate(starts)}
    px = np.frombuffer(data, np.uint8)
    heads = []
    for o in offs:
        if o + hl > len(data):
            heads.append(None)
        elif hl == 13:
            heads.append(struct.unpack_from("<IIhhB", data, o))
        else:
            w, h, fmt = struct.unpack_from("<hhB", data, o)
            heads.append((None, 0, w, h, fmt))
    # ids a delta frame patches: the cached record whose id is one less,
    # matched (as the game's cache does) on the id's low half
    based = {(hd[0] - 1) & 0xFFFF for hd in heads
             if hd and hd[0] is not None and hd[4] in _DELTAS}
    bitmaps = {}
    for number, (o, hd) in enumerate(zip(offs, heads)):
        if hd is None:
            continue
        ident, _flags, w, h, fmt = hd
        if fmt not in (RAW8, RAW4) or w <= 0 or h <= 0:
            continue
        if ident is not None and ident & 0xFFFF in based:
            continue
        bm = Bitmap(number, o, hl, w, h, fmt)
        end = bm.data_offset + bm.data_size
        if end > after[o]:
            continue
        if fmt == RAW8 and not _VALID[px[bm.data_offset:end]].all():
            continue
        bitmaps[number] = bm
    if not bitmaps:
        raise SamArtError("no still pictures in this file's picture table")
    art = Art(fonts_at, table, count, hl, bitmaps)
    numbers = {b.offset: b.number for b in bitmaps.values()}
    for i in range(n_fonts):
        end, start, height = struct.unpack_from(
            "<IIh", data, fonts_at + _FONT_RECORD * i)
        glyphs = _glyph_array(data, start, end, numbers)
        if glyphs:
            art.fonts.append(Font(i, height, glyphs))
    for f in art.fonts:
        for i, g in enumerate(f.glyphs):
            if g is not None:
                art.glyph_of.setdefault(g, (f.number, i))
    return art


def pixels(data, bm):
    """*bm*'s pixels as a ``height x width`` uint8 array (shades 0..15,
    0xFF transparent)."""
    raw = np.frombuffer(data, np.uint8, count=bm.data_size,
                        offset=bm.data_offset)
    if bm.fmt == RAW8:
        return raw.reshape(bm.height, bm.width).copy()
    n = bm.width * bm.height
    out = np.empty(2 * len(raw), np.uint8)
    out[0::2] = raw & 0x0F
    out[1::2] = raw >> 4
    return out[:n].reshape(bm.height, bm.width)


def to_la(px):
    """Pixels -> an ``L``+alpha array (``h x w x 2``): shade ``s`` is grey
    ``s * 17``, transparent is alpha 0."""
    out = np.zeros(px.shape + (2,), np.uint8)
    solid = px != TRANSPARENT
    out[..., 0] = np.where(solid, np.minimum(px, SHADES - 1) * 17, 0)
    out[..., 1] = np.where(solid, 255, 0)
    return out


def from_la(la, transparent=True):
    """An ``L``+alpha array (``h x w x 2``) -> pixels: grey to the nearest
    of the 16 shades, alpha under half to transparent (to shade 0 when
    *transparent* is False: a four-bit picture has no transparency).  The
    exact inverse of :func:`to_la`."""
    grey = la[..., 0].astype(np.int32)
    shade = np.clip((grey + 8) // 17, 0, SHADES - 1)
    clear = TRANSPARENT if transparent else 0
    return np.where(la[..., 1] < 128, clear, shade).astype(np.uint8)


def encode(bm, px):
    """Pixels (``height x width``) -> *bm*'s data bytes."""
    px = np.asarray(px, np.uint8)
    if px.shape != (bm.height, bm.width):
        raise SamArtError("picture %d is %dx%d, the replacement %dx%d"
                          % (bm.number, bm.width, bm.height, px.shape[1],
                             px.shape[0]))
    if bm.fmt == RAW8:
        if not _VALID[px].all():
            raise SamArtError("picture %d: pixels must be 0-15 or 255"
                              % bm.number)
        return px.tobytes()
    if (px > SHADES - 1).any():
        raise SamArtError("picture %d has no transparency: pixels must be "
                          "0-15" % bm.number)
    flat = px.reshape(-1)
    if len(flat) & 1:
        flat = np.concatenate((flat, [0]))
    return (flat[0::2] | (flat[1::2] << 4)).astype(np.uint8).tobytes()


def replace(image, bm, px):
    """Write pixels *px* over *bm* in *image* (a bytearray) and return the
    byte-sum change.  The last byte of an odd-sized four-bit picture keeps
    its unused top nibble."""
    new = bytearray(encode(bm, px))
    lo, hi = bm.data_offset, bm.data_offset + bm.data_size
    old = bytes(image[lo:hi])
    if bm.fmt == RAW4 and (bm.width * bm.height) & 1:
        new[-1] = (new[-1] & 0x0F) | (old[-1] & 0xF0)
    image[lo:hi] = new
    return sum(new) - sum(old)
