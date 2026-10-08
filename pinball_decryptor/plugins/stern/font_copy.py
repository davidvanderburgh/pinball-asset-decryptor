"""A line of text's own copy of its font (PAD-451, DragonRR: "make it so that we can change
each text layer individually").

A font whose letters carry their own colours (Godzilla's orange GameFont_Secondary) keeps them
in its pictures, which every line drawn in it shares, in every scene (PAD-438).  One line can
still have the individual files profile on its own: the Write gives it a COPY of the font
SIZE it is drawn at - that size's letters and the pictures they are cut from, the profile baked
into them - as one more Font entry in the scene's library, right after the font it copies, and
points the line's Text at it.  Every other line keeps the font as it was.

THE FONT ENTRY (:func:`scene_write._walk_font`'s grammar; a copy renumbers every id)::

    entry   u32 key | class | u32 FLAG|font id | u32 key | name | face | u8 u8
            | [u64 n] u16 chars | [u64 s] size* | [u64 v] (variant name, [u64 s] size*)
    size    u32 points x 10 | u32 FLAG|size id | u32 key | f32 line ascent descent | u8
            | [u64 g] glyph*
    glyph   u16 char | u32 FLAG|glyph id | 7 f32 | u8 | 4 f32 uv | page | [u64 k] (u16, f32)
    page    u32 0 (none) | u32 texture id (defined earlier) | u32 FLAG|texture id
            | u32 w | u32 h | u32 format | name | u32 n | n bytes

Godzilla's battle scenes carry ONE Font entry (face STERN_HelveticaNeueBlack) holding both
game fonts as style variants, three sizes each over the variant's three 512x512 pictures; a
Text names the SIZE it draws with (its ``font``, ``used`` and ``fonts`` map).  A copy holds that
one size (about 100 ids, its pictures re-encoded: some 0.8 MB for GameFont_Secondary), its
variant's name and its face ending in ``#PAD<size id>.<tag>`` and its pictures named the same
way, so nothing the game keeps by name across scenes can mix it up with the original, and a
card built with it, read again, finds the size it was copied from (:func:`original_size`).
Lines with the same profile in one scene share one copy; a copy no line draws with any more is
dropped (:func:`prune`).
"""
from __future__ import annotations

import hashlib
import json
import os
import struct

FLAG = 0x80000000
MARK = b"#PAD"


class FontCopyError(ValueError):
    """A font entry this module cannot walk or copy."""


def _u32(v):
    return struct.pack("<I", v)


def _u64(v):
    return struct.pack("<Q", v)


def _bstr(b):
    return _u64(len(b)) + b


class _R:
    def __init__(self, d):
        self.d, self.o = d, 0

    def take(self, n):
        if self.o + n > len(self.d):
            raise FontCopyError("the font entry ends inside a field at 0x%x" % self.o)
        b = self.d[self.o:self.o + n]
        self.o += n
        return b

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self, cap=1 << 24):
        v = struct.unpack("<Q", self.take(8))[0]
        if v > cap:
            raise FontCopyError("a list of %d at 0x%x" % (v, self.o - 8))
        return v

    def bstr(self):
        return self.take(self.u64())


class Font:
    """One Font library entry, walked: ``key``, ``cls`` (the class field's bytes), ``fid``,
    ``name``, ``face`` (bytes), ``flags`` (the two bytes after them), ``chars`` (the char
    list's bytes, count included), ``sizes`` ``[(variant bytes, Size)]`` ("" = the base
    sizes), ``pages`` ``{texture id: (w, h, fmt, name, blob)}`` defined inside it."""

    def __init__(self):
        self.sizes, self.pages = [], {}

    @property
    def copied_from(self):
        """The size id a PAD copy was made from, or ``None`` for a font of the game's."""
        i = self.face.rfind(MARK)
        if i < 0:
            return None
        try:
            return int(self.face[i + len(MARK):].split(b".", 1)[0])
        except ValueError:
            return None

    def size(self, sid):
        for variant, s in self.sizes:
            if s.id == sid:
                return variant, s
        return None, None

    def ids(self):
        out = [self.fid]
        for _v, s in self.sizes:
            out.append(s.id)
            out += [g["id"] for g in s.glyphs]
        return out + list(self.pages)


class Size:
    __slots__ = ("pre", "id", "metrics", "glyphs")


def parse(key, raw):
    """The Font entry whose bytes from its class field on are *raw* (a
    :class:`scene_tree.Scene` library entry ``("font", raw)``)."""
    f = Font()
    f.key = key
    r = _R(raw)
    cls = r.u32()
    if cls & FLAG:
        if r.bstr() != b"Font":
            raise FontCopyError("a font entry whose class is not Font")
    f.cls = raw[:r.o]
    v = r.u32()
    if not v & FLAG:
        raise FontCopyError("a font entry whose font is not defined in it")
    f.fid = v & ~FLAG
    if r.u32() != key:
        raise FontCopyError("a font entry whose key does not repeat")
    f.name, f.face = r.bstr(), r.bstr()
    f.flags = r.take(2)
    n = r.u64(1 << 16)
    f.chars = raw[r.o - 8:r.o + 2 * n]
    r.take(2 * n)

    def page():
        v = r.u32()
        if not v & FLAG:
            return v or None
        tid = v & ~FLAG
        w, h, fmt = struct.unpack("<3I", r.take(12))
        name = r.bstr()
        blob = r.take(r.u32())
        f.pages[tid] = (w, h, fmt, name, blob)
        return tid

    def sizes(variant):
        for _ in range(r.u64(4096)):
            s = Size()
            s.pre = r.u32()
            v = r.u32()
            if not v & FLAG:
                raise FontCopyError("a font size that is not defined where it stands")
            s.id = v & ~FLAG
            if r.u32() != key:
                raise FontCopyError("a font size that does not name its font")
            s.metrics = r.take(13)
            s.glyphs = []
            for _g in range(r.u64(1 << 16)):
                char = struct.unpack("<H", r.take(2))[0]
                v = r.u32()
                if not v & FLAG:
                    raise FontCopyError("a glyph that is not defined where it stands")
                body = r.take(45)
                pg = page()
                at = r.o
                r.take(6 * r.u64(1 << 16))
                s.glyphs.append({"char": char, "id": v & ~FLAG, "body": body, "page": pg,
                                 "kern": raw[at:r.o]})
            f.sizes.append((variant, s))

    sizes(b"")
    for _ in range(r.u64(4096)):
        sizes(r.bstr())
    if r.o != len(raw):
        raise FontCopyError("the font entry has %d bytes past its end" % (len(raw) - r.o))
    return f


def fonts_of(scene):
    """``[(library index, Font)]`` of *scene* (a :class:`scene_tree.Scene`)."""
    out = []
    for i, (key, _cid, obj) in enumerate(scene.library):
        if isinstance(obj, tuple) and obj[0] == "font":
            out.append((i, parse(key, obj[1])))
    return out


def max_id(scene):
    """The highest object id the scene's Font entries define (they are carried as bytes, so
    :func:`scene_edit._max_id` does not see them)."""
    top = 0
    for _i, f in fonts_of(scene):
        top = max([top] + f.ids())
    return top


def free_key(scene):
    """A symbol key no library entry and no object uses."""
    keys = [k for k, _c, _o in scene.library]
    keys += [o.body.get("sym", 0) for o in scene.objects.values()
             if isinstance(o.body, dict) and isinstance(o.body.get("sym"), int)]
    return max(keys + [0]) + 1


def _texts(scene):
    return [o for o in scene.objects.values() if o.kind == "Text"]


def original_size(fonts, sid):
    """The game's own size a size id stands for: *sid* itself, or, for a size of a PAD copy
    (a card built with one, read again), the size it was copied from."""
    for _i, f in fonts:
        if f.copied_from is not None and f.size(sid)[1] is not None:
            return f.copied_from
    return sid


def tag(profile, mul=None):
    """A short name for a copy's look: lines with the same one share a copy."""
    return hashlib.sha1(json.dumps([profile, mul], sort_keys=True).encode()).hexdigest()[:8]


def build(f, sid, key, alloc, look, page_blob):
    """The library entry (from its class field on) of a copy of size *sid* of font *f* under
    symbol key *key*, its ids from *alloc*, named for *look* (:func:`tag`), each picture
    re-encoded by ``page_blob(texture id, (w, h, fmt, name, blob), chars on it)``.  Returns
    ``(entry bytes, new size id, variant name or b"")``."""
    variant, s = f.size(sid)
    if s is None:
        raise FontCopyError("size %d is not in this font" % sid)
    mark = MARK + (b"%d." % sid) + look.encode()
    on_page = {}
    for g in s.glyphs:
        if g["page"]:
            on_page.setdefault(g["page"], []).append(g["char"])
    out = bytearray(_u32(struct.unpack("<I", f.cls[:4])[0] & ~FLAG))
    out += _u32(FLAG | alloc()) + _u32(key)
    out += _bstr(f.name) + _bstr(f.face + mark) + f.flags + f.chars
    body = bytearray(_u32(s.pre))
    new_sid = alloc()
    body += _u32(FLAG | new_sid) + _u32(key) + s.metrics + _u64(len(s.glyphs))
    done = {}
    for g in s.glyphs:
        body += struct.pack("<H", g["char"]) + _u32(FLAG | alloc()) + g["body"]
        pg = g["page"]
        if not pg:
            body += _u32(0)
        elif pg in done:
            body += _u32(done[pg])
        else:
            info = f.pages.get(pg)
            if info is None:
                raise FontCopyError("picture %d of the font is not in its entry" % pg)
            w, h, fmt, name, blob = info
            new = page_blob(pg, info, on_page.get(pg) or [])
            if len(new) != len(blob):
                raise FontCopyError("a re-encoded font picture changed size")
            tid = done[pg] = alloc()
            body += _u32(FLAG | tid) + struct.pack("<3I", w, h, fmt)
            body += _bstr((name or b"page") + mark + (b".%d" % len(done)))
            body += _u32(len(new)) + new
        body += g["kern"]
    if variant:
        out += _u64(0) + _u64(1) + _bstr(variant + mark) + _u64(1) + body
    else:
        out += _u64(1) + body + _u64(0)
    return bytes(out), new_sid, (variant + mark) if variant else b""


def repoint(text, old, new, variant):
    """Text body *text* drawn with size *new* where it named *old* (its ``fonts`` map entry
    renamed to *variant* when the copy's size is a named variant)."""
    if text["font"] == old:
        text["font"] = new
    text["used"] = [new if u == old else u for u in text["used"]]
    text["fonts"] = [((variant.decode("latin1") if variant else n), new) if fid == old
                     else (n, fid) for n, fid in text["fonts"]]


def prune(scene):
    """Drop the PAD copies no Text draws with any more.  Returns how many."""
    fonts = fonts_of(scene)
    if not any(f.copied_from is not None for _i, f in fonts):
        return 0
    used = set()
    for o in _texts(scene):
        used.add(o.body["font"])
        used.update(o.body["used"])
        used.update(fid for _n, fid in o.body["fonts"])
    gone = [i for i, f in fonts if f.copied_from is not None
            and not used & {s.id for _v, s in f.sizes}]
    for i in reversed(gone):
        del scene.library[i]
    return len(gone)


# ---------------------------------------------------------------------------------------------
# the pictures
# ---------------------------------------------------------------------------------------------
def page_pixels(assets_dir, rel):
    """The pristine pixels (uint8 RGBA) of font picture *rel* (under ``images/``): its
    ``.orig`` snapshot when a build corrected the project's file, else the file; ``None``
    without it."""
    import numpy as np
    from PIL import Image
    from ...core import staged_originals
    path = (staged_originals.snapshot_path(assets_dir, "images/" + rel)
            or os.path.join(assets_dir or "", "images", *rel.split("/")))
    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("RGBA"), dtype=np.uint8)
    except (OSError, ValueError):
        return None


def corrected_blob(stock_rgba, w, h, fmt, prof, mul=None):
    """The picture *stock_rgba* (its letters' pixels, as the extract wrote them) with *mul*
    (the line's own colour, baked in) and *prof* applied, encoded as the game's picture of
    ``w`` x ``h`` in ``fmt`` - BC3 (5) or BC1 (4) - premultiplied as the stock one is."""
    import numpy as np
    from PIL import Image
    from . import dds, engine
    arr = np.zeros((h, w, 4), np.uint8)
    hh, ww = min(h, stock_rgba.shape[0]), min(w, stock_rgba.shape[1])
    arr[:hh, :ww] = stock_rgba[:hh, :ww]
    if mul is not None:
        m = np.asarray([float(v) for v in mul[:3]], np.float32)
        arr[..., :3] = np.clip(arr[..., :3].astype(np.float32) * m + 0.5, 0, 255).astype(
            np.uint8)
    arr = np.asarray(prof.apply_image(Image.fromarray(arr)).convert("RGBA"), np.uint8)
    arr, _changed = engine._premultiply_like_stock(arr, stock_rgba)
    if fmt == engine._DXT1_FORMAT:
        return dds.encode_bc1(arr)
    if fmt != engine._DXT5_FORMAT:
        raise FontCopyError("a font picture in format %d, not BC1 or BC3" % fmt)
    return dds.encode_bc3(arr)


def give(scene, text_objs, op, assets_dir, alloc, made):
    """Op ``line_font`` (:mod:`scene_edit`) on the Text bodies *text_objs*: each drawn with a
    copy of its size carrying ``op["profile"]`` (and ``op["mul"]``), made once per size and
    look in *made*; ``op["off"]``: back to the game's own size.  Returns a note or ``""``."""
    from ...core import colour_profile as cp
    from . import dds, engine
    fonts = fonts_of(scene)
    for o in text_objs:
        t = o.body
        sid = t["font"]
        orig = original_size(fonts, sid)
        if op.get("off"):
            if orig != sid:
                owner = next((f for _i, f in fonts if f.size(orig)[1] is not None), None)
                variant = owner.size(orig)[0] if owner is not None else b""
                repoint(t, sid, orig, variant)
            continue
        prof = cp._from_dict(op.get("profile") or {})
        if prof is None:
            return "line_font: no profile"
        look = tag(op.get("profile"), op.get("mul"))
        got = made.get((orig, look))
        if got is None:
            at = next(((i, f) for i, f in fonts if f.copied_from is None
                       and f.size(orig)[1] is not None), None)
            if at is None:
                return "line_font: the font of node %s is not in this scene" % op["node"]
            index, font = at
            art = {int(k): v for k, v in (op.get("art") or {}).items()}

            def page_blob(_tid, info, chars):
                w, h, fmt, _name, blob = info
                rel = next((art[c] for c in chars if c in art), None)
                px = page_pixels(assets_dir, rel) if rel else None
                if px is None or px.shape[0] < h - 3 or px.shape[1] < w - 3:
                    # no picture of it in the project: the scene's own (stock) bytes
                    decode = dds.decode_bc1 if fmt == engine._DXT1_FORMAT else dds.decode_bc3
                    px = decode(blob, w, h)
                return corrected_blob(px, w, h, fmt, prof, op.get("mul"))
            key = free_key(scene)
            entry, new_sid, variant = build(font, orig, key, alloc, look, page_blob)
            scene.library.insert(index + 1, (key, struct.unpack("<I", entry[:4])[0],
                                             ("font", entry)))
            got = made[(orig, look)] = (new_sid, variant)
            fonts = fonts_of(scene)
        repoint(t, sid, got[0], got[1])
    return ""
