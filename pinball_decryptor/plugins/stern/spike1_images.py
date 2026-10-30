"""Stern Spike 1 DMD pictures and animation frames (PAD-870): Extract every
one to a PNG, write edited ones back into the card's ``image.bin``.

The game draws them with the same engine as S.A.M. (its ``image.cpp``:
``sys_image_render`` and the per-format ``image_op_table``), so the record
format and the frame codecs are :mod:`..pinmame_classic.sam_anim`'s,
unchanged: a 13-byte header (``u32 id, u32 flags, s16 width, s16 height,
u8 format``), formats 0 raw, 1 / 7 run-length ("whitespace") in column /
row order, 3 / 9 delta on the cached keyframe ("delta"), 12 raw 4-bit
("row_16", low nibble first); flag 4 keeps a keyframe cached for the deltas
after it.  Checked instruction by instruction against KISS LE 1.41's
decompressors.  What differs is where the table is:

* ``image.bin`` holds the graphics table: ``hook_image_table_entry_count``
  u64 file offsets (8-byte aligned records) at
  ``hook_image_table_flash_offset`` - both read from the game ELF's own
  symbols (every Spike 1 program on hand ships its symbol table).  KISS LE
  1.41: 24,195 records in 34.6 MB, packed solid.
* No banks: an offset is the record's place in the file.

Extract writes the plain pictures (raw records no delta builds on) to
``images/pictures/imgNNNN.png`` and every other record (run-length, 4-bit,
delta frames, and the keyframes deltas build on) to
``animations/imgNNNN.png``, ``NNNN`` the record's place in the table (the
game plays an animation by stepping through those numbers, so its frames
sort together), as grey + alpha: shade ``s`` of 16 is grey ``s * 17``,
transparent is alpha 0.

Write re-encodes each changed PNG in the shortest exact form its place
allows (:func:`sam_anim.plan_write`).  A frame that can't fit its own
bytes, even sharing the run of frames around it, goes whole into the free
front page most titles carry: ``image.bin`` starts with a 1.15 MB page
shipped erased (0xFF) that nothing the game reads lies in (every
``hook_*_flash_offset`` is past it), and the record's table entry is
repointed there.  Only where that is full (or missing: Ghostbusters'
image.bin starts with its tables) does a frame get fewer shades, or keep
its original picture; the log names each one.  The file never moves or
grows, so a write is an in-place patch like the audio's.
"""

import os
import struct
from dataclasses import dataclass

import numpy as np

from ...core import checksums
from ...core.longpath import ext as _lp
from ..pinmame_classic import sam_anim
from . import sam_anim_assets

PICTURES = "images/pictures"
FONTS = "images/fonts"
ANIMATIONS = "animations"

ALIGN = 8
# the erased front page: [0x1000, 0x11f000) on the titles whose every
# flash structure starts at or after 0x120000 (the header block, the sound
# scripts, the configs, the font and picture tables)
_FRONT = (0x1000, 0x11F000)
_FRONT_LIMIT = 0x120000
_HOOK_SUFFIXES = ("_flash_offset",)

_FORMAT_WORDS = sam_anim_assets._FORMAT_WORDS


class Spike1ImagesError(Exception):
    pass


def png_name(number, count=0):
    """``imgNNNN.png``; five digits throughout on a table of 10,000 or
    more, so the files sort in table order."""
    return "img%0*d.png" % (5 if count > 10000 else 4, number)


# --------------------------------------------------------------------------
# where the tables are
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Layout:
    """Where the game program says its pictures are in ``image.bin``."""
    table: int          # picture table: *count* u64 record offsets
    count: int
    fonts: int          # font table: *font_count* 32-byte font records
    font_count: int
    lowest: int         # the lowest offset any hook_*_flash_offset names


def locate(elf):
    """The :class:`Layout` from the game ELF bytes *elf*'s own symbols."""
    from .spike1_adjustments import Spike1AdjustmentError, _Elf
    try:
        e = _Elf(elf)

        def u64(name):
            return struct.unpack("<Q", e.read(e.sym(name), 8))[0]

        table = u64("hook_image_table_flash_offset")
        count = e.u32(e.sym("hook_image_table_entry_count"))
        try:
            fonts = u64("hook_font_table_flash_offset")
            font_count = e.u32(e.sym("hook_font_table_entry_count"))
        except Spike1AdjustmentError:
            fonts = font_count = 0
        lowest = table
        for name, va in e.syms.items():
            if name.startswith("hook_") and name.endswith(_HOOK_SUFFIXES):
                try:
                    lowest = min(lowest,
                                 struct.unpack("<Q", e.read(va, 8))[0])
                except Spike1AdjustmentError:
                    pass
    except Spike1AdjustmentError as e:
        raise Spike1ImagesError("the game program doesn't say where its "
                                "pictures are (%s)" % e)
    if not 0 < count < 200000:
        raise Spike1ImagesError("picture table count %d is not plausible"
                                % count)
    if not 0 <= font_count < 1000:
        fonts = font_count = 0
    return Layout(table, count, fonts, font_count, lowest)


def _font_heads(read, size, lay):
    """``[(charset offset, glyph array offset, size word)]`` per font."""
    if not lay.font_count or lay.fonts + 32 * lay.font_count > size:
        return []
    raw = read(lay.fonts, 32 * lay.font_count)
    return [struct.unpack_from("<QQQ", raw, 32 * i)
            for i in range(lay.font_count)]


def _charset(read, size, at):
    """The characters a font has, from its ``lo, hi`` byte pairs (0 ends),
    or None when *at* holds no such list."""
    out = []
    raw = read(at, min(512, size - at)) if at < size else b""
    for i in range(0, len(raw) - 1, 2):
        lo, hi = raw[i], raw[i + 1]
        if lo == 0:
            return out
        if hi < lo:
            break
        out += [chr(c) for c in range(lo, hi + 1)]
    return None


def art_extent(read, size, lay):
    """Bytes ``[0, end)`` of ``image.bin`` holding every picture record and
    the fonts' glyph arrays: *read(off, n)* reads the file, *size* is its
    length."""
    table, count = lay.table, lay.count
    if table + 8 * count > size:
        raise Spike1ImagesError("picture table runs past the end of "
                                "image.bin")
    ptrs = struct.unpack("<%dQ" % count, read(table, 8 * count))
    last = max(ptrs)
    if last + sam_anim.HEADER > size:
        raise Spike1ImagesError("picture record at 0x%x is past the end of "
                                "image.bin" % last)
    _id, _fl, w, h = struct.unpack("<IIhh", read(last, 12))
    n = max(w, 0) * max(h, 0)
    # a run-length record can be a little longer than its pixels
    end = max(table + 8 * count, last + sam_anim.HEADER + n + n // 32 + 64,
              lay.fonts + 32 * lay.font_count)
    for cs, arr, _w in _font_heads(read, size, lay):
        chars = _charset(read, size, cs)
        if chars is not None:
            end = max(end, cs + 2 * len(chars) + 2, arr + 16 * len(chars))
    return min(size, end)


def read_table(data, lay):
    """The :class:`sam_anim.ArtTable` of the ``image.bin`` bytes *data*
    (from offset 0 to at least :func:`art_extent`), with ``fonts``:
    ``[(font number, height, [(record number, character)])]``."""
    table, count = lay.table, lay.count
    if table + 8 * count > len(data):
        raise Spike1ImagesError("picture table is past the bytes read")
    ptrs = struct.unpack_from("<%dQ" % count, data, table)
    out = []
    for i, off in enumerate(ptrs):
        if off % ALIGN or off + sam_anim.HEADER > len(data):
            raise Spike1ImagesError("picture %d's record at 0x%x is not a "
                                    "record" % (i, off))
        rid, fl, w, h = struct.unpack_from("<IIhh", data, off)
        fmt = data[off + 12]
        if fmt not in sam_anim._KINDS or fl >= 8 or not (0 < w <= 1024) \
                or not (0 < h <= 1024):
            raise Spike1ImagesError("picture %d's record at 0x%x is not a "
                                    "record (format %d, %dx%d)"
                                    % (i, off, fmt, w, h))
        try:
            length = sam_anim._rec_length(data, off, w, h, fmt)
        except sam_anim.SamAnimError as e:
            raise Spike1ImagesError(str(e))
        out.append(sam_anim.Record(i, off, rid, fl, w, h, fmt, length))
    art = sam_anim.ArtTable(0, table, out, entry=8, align=ALIGN, bank=None)
    sam_anim.finish(art)
    art.fonts = _read_fonts(data, lay, ptrs)
    art.movable = _movable(data, art)
    # a glyph stays where its font's array points
    for _n, _h, glyphs in art.fonts:
        for num, _c in glyphs:
            art.movable[num] = False
    art.lowest = lay.lowest
    return art


def _read_fonts(data, lay, ptrs):
    where = {p: i for i, p in enumerate(ptrs)}

    def read(off, n):
        return bytes(data[off:off + n])

    fonts = []
    for i, (cs, arr, word) in enumerate(_font_heads(read, len(data), lay)):
        chars = _charset(read, len(data), cs)
        if not chars or arr + 16 * len(chars) > len(data):
            continue
        glyphs = []
        for k, c in enumerate(chars):
            g = struct.unpack_from("<Q", data, arr + 16 * k)[0]
            if g in where:
                glyphs.append((where[g], c))
        if glyphs:
            fonts.append((i, word & 0xFFFF, glyphs))
    return fonts


def _movable(data, art):
    """number -> True when the record's offset is named nowhere in the
    art bytes but its table entry (an aligned u64 that matches by chance
    only pins a record in place)."""
    n = len(data) // 8
    words = np.frombuffer(data, "<u8", count=n)
    ptrs = np.frombuffer(data, "<u8", count=len(art.records),
                         offset=art.table)
    hits = np.isin(words, ptrs)
    lo = art.table // 8
    hits[lo:lo + len(art.records)] = False
    seen = set(int(v) for v in np.unique(words[hits]))
    return {r.number: int(ptrs[r.number]) not in seen for r in art.records}


def still_numbers(art):
    """Records written to ``images/pictures``: raw ones no delta builds on
    and no font uses.  Every other record is a font glyph or an animation
    frame."""
    based = {b for b in sam_anim.bases(art).values() if b is not None}
    glyphs = {num for _n, _h, gl in art.fonts for num, _c in gl}
    return {r.number for r in art.records
            if r.fmt == 0 and r.number not in based | glyphs}


def rel_paths(art):
    """number -> where the record's PNG goes under the project folder:
    ``images/fonts/fontNN (H px)/imgNNNN-<character>.png`` for a font
    glyph, ``images/pictures/imgNNNN.png`` for a plain picture,
    ``animations/imgNNNN.png`` for everything else."""
    out = {}
    count = len(art.records)
    for fnum, height, glyphs in art.fonts:
        folder = "%s/font%02d (%d px)" % (FONTS, fnum, height)
        for num, c in glyphs:
            out.setdefault(num, "%s/%s-%s.png" % (
                folder, png_name(num, count)[:-4], _char_tag(c)))
    stills = still_numbers(art)
    for r in art.records:
        if r.number not in out:
            out[r.number] = "%s/%s" % (
                PICTURES if r.number in stills else ANIMATIONS,
                png_name(r.number, count))
    return out


def _char_tag(c):
    """A glyph's character as a file-name part: letters and digits as
    they are, anything else as its code (``x2C`` for a comma)."""
    return c if c.isascii() and c.isalnum() else "x%02X" % ord(c)


# --------------------------------------------------------------------------
# the free front page
# --------------------------------------------------------------------------

class FrontPage:
    """The erased page at the front of ``image.bin`` as spare room for
    :func:`sam_anim.plan_write`: what isn't held by a record the table
    already points into it (an earlier build's), handed out first-fit."""

    def __init__(self, art, size):
        lo, hi = _FRONT
        self.free = []
        if art.lowest < _FRONT_LIMIT or size < _FRONT_LIMIT:
            return
        held = sorted((r.offset, r.offset + r.length) for r in art.records
                      if r.offset < hi and r.offset + r.length > lo)
        at = lo
        for a, b in held:
            if a > at:
                self.free.append([at, a])
            at = max(at, _align(b))
        if at < hi:
            self.free.append([at, hi])

    @property
    def room(self):
        return sum(b - a for a, b in self.free)

    def take(self, n):
        n = _align(n)
        for span in self.free:
            if span[1] - span[0] >= n:
                off = span[0]
                span[0] += n
                return off
        return None


def _align(x):
    return (x + ALIGN - 1) & ~(ALIGN - 1)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def extract_all(data, lay, output_dir, log=None, progress=None,
                cancel=None):
    """Write every picture, font glyph and animation frame of the
    ``image.bin`` bytes *data* under *output_dir*.  Returns
    ``{"pictures": n, "fonts": n, "glyphs": n, "frames": n}``."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    art = read_table(data, lay)
    frames = sam_anim.decode_all(data, art)
    rels = rel_paths(art)
    made = set()
    n = len(art.records)
    counts = {PICTURES: 0, FONTS: 0, ANIMATIONS: 0}
    for r in art.records:
        if check():
            raise Spike1ImagesError("cancelled")
        rel = rels[r.number]
        folder = os.path.join(output_dir, *rel.split("/")[:-1])
        if folder not in made:
            os.makedirs(_lp(folder), exist_ok=True)
            made.add(folder)
        sam_anim_assets._save(os.path.join(output_dir, *rel.split("/")),
                              frames[r.number])
        counts[next(k for k in counts if rel.startswith(k + "/"))] += 1
        if progress and (r.number % 64 == 0 or r.number == n - 1):
            progress(r.number + 1, n,
                     "Decoding pictures (%d/%d)" % (r.number + 1, n))
    log("DMD pictures: %d picture(s) in images/pictures, %d font glyph(s) "
        "of %d font(s) in images/fonts and %d animation frame(s) in "
        "animations/ (%d records in the picture table)"
        % (counts[PICTURES], counts[FONTS], len(art.fonts),
           counts[ANIMATIONS], n))
    return {"pictures": counts[PICTURES], "fonts": len(art.fonts),
            "glyphs": counts[FONTS], "frames": counts[ANIMATIONS]}


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------

def _pngs(assets_dir):
    """``(rel, path)`` for every PNG under the picture folders."""
    for root in (PICTURES, FONTS, ANIMATIONS):
        top = os.path.join(assets_dir, *root.split("/"))
        for dirpath, _dirs, files in os.walk(_lp(top)):
            for fn in sorted(files):
                if not fn.lower().endswith(".png") or ".stage." in fn                         or ".part" in fn:
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, _lp(assets_dir))                     .replace(os.sep, "/")
                yield rel, path


def changed_pngs(assets_dir, log=None):
    """``{number: path}`` for every picture / glyph / frame PNG changed vs
    the extract's checksum baseline."""
    log = log or (lambda *a, **k: None)
    baseline = checksums.read_checksums(assets_dir)
    out = {}
    for rel, path in _pngs(assets_dir):
        num = sam_anim_assets.parse_png_stem(
            os.path.splitext(os.path.basename(rel))[0])
        if num is None:
            continue
        base = baseline.get(rel)
        if base is not None and checksums.md5_file(path) == base:
            continue
        if num in out:
            log("  note: %s and %s are the same picture; using %s"
                % (os.path.basename(out[num]), os.path.basename(rel),
                   os.path.basename(out[num])))
        else:
            out[num] = path
    return out


def plan(data, lay, changed, log=None, cancel=None):
    """The patches putting the *changed* PNGs (``{number: path}``) into
    the ``image.bin`` bytes *data*.  Returns ``(writes, written,
    skipped)``: ``[(file offset, bytes)]``, the number of pictures
    written, and the names left out."""
    from PIL import Image

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    art = read_table(data, lay)
    frames = sam_anim.decode_all(data, art)
    edits, skipped = {}, []
    for num, path in sorted(changed.items()):
        if check():
            raise Spike1ImagesError("cancelled")
        name = os.path.basename(path)
        if num >= len(art.records):
            skipped.append(name)
            log("  ! %s: this card has no picture %d - skipped"
                % (name, num), "warning")
            continue
        rec = art.records[num]
        note = []
        try:
            with Image.open(_lp(path)) as img:
                img.load()
                rgba = img.convert("RGBA")
            if rgba.size != (rec.width, rec.height):
                # a picture of another size fits the slot, as on S.A.M.
                note.append("scaled from %dx%d" % rgba.size)
                rgba = rgba.resize((rec.width, rec.height), Image.LANCZOS)
            frame = sam_anim_assets.from_image(rgba)
        except Exception as e:                      # noqa: BLE001
            skipped.append(name)
            log("  ! %s could not be read (%s) - skipped" % (name, e),
                "warning")
            continue
        if rec.fmt == 12 and (frame == sam_anim.TRANSPARENT).any():
            # 4-bit frames have no transparency
            frame[frame == sam_anim.TRANSPARENT] = 0
            note.append("transparent pixels made black (this picture has "
                        "no transparency)")
        if note:
            log("  note: %s %s" % (name, ", ".join(note)))
        if np.array_equal(frame, frames[num]):
            continue
        edits[num] = frame
    if not edits:
        return [], 0, skipped
    front = FrontPage(art, len(data))
    owned = {r.number for r in art.records}
    try:
        p = sam_anim.plan_write(data, art, frames, edits, owned,
                                spare=front if front.free else None)
    except sam_anim.SamAnimError as e:
        raise Spike1ImagesError(str(e))
    for num in sorted(edits):
        how = p.how.get(num, "exact")
        name = os.path.basename(changed[num])
        rec = art.records[num]
        fmt, size = p.written.get(num, (rec.fmt, rec.length))
        where = " - moved to free space" if num in p.away else ""
        if how == "original":
            skipped.append(name)
            log("  ! %s is too detailed to fit this picture's place even "
                "with two shades - it keeps its original picture" % name,
                "warning")
        elif how != "exact":
            log("  %s: %dx%d, simplified to %s to fit (%s, %d bytes)%s"
                % (name, rec.width, rec.height, how, _FORMAT_WORDS[fmt],
                   size, where), "warning")
        else:
            log("  %s: %dx%d (%s, %d bytes)%s"
                % (name, rec.width, rec.height, _FORMAT_WORDS[fmt], size,
                   where))
    followers = len(p.written) - len(edits)
    if followers > 0:
        log("  %d following delta frame(s) re-encoded on the new pictures"
            % followers)
    image = bytearray(data[:len(data)])
    sam_anim.apply_plan(image, art, p)
    writes = list(p.patches)
    for n in p.moved:
        at = lay.table + 8 * n
        writes.append((at, bytes(image[at:at + 8])))
    written = sum(1 for n in edits if p.how.get(n) != "original")
    return writes, written, skipped


# --------------------------------------------------------------------------
# revert
# --------------------------------------------------------------------------

def revert(data, lay, assets_dir, rels, log=None):
    """Re-decode the original PNGs for *rels* (``images/pictures/...`` or
    ``animations/...``) from the ``image.bin`` bytes *data*.  Returns
    ``(reverted, failed)``."""
    log = log or (lambda *a, **k: None)
    art = read_table(data, lay)
    frames = sam_anim.decode_all(data, art)
    reverted, failed = [], []
    for rel in rels:
        num = sam_anim_assets.parse_png_stem(
            os.path.splitext(os.path.basename(rel))[0])
        if num is None or num >= len(art.records):
            failed.append(rel)
            log("  ! %s: no matching picture on the source card" % rel)
            continue
        sam_anim_assets._save(os.path.join(assets_dir, *rel.split("/")),
                              frames[num])
        reverted.append(rel)
        log("  restored %s" % rel)
    return reverted, failed
