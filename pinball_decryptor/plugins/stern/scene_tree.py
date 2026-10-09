"""A Spike 2 ``scene.radium`` as the TREE the game reads, and back to bytes (PAD-251).

:mod:`scene_layout` reads a scene by scanning for byte patterns, which is enough to name its
pictures and strings but not to draw it: it misses parent transforms, ignores scale and draws
every state of a screen at once.  This module reads the file with the grammar the GAME reads
(measured with ``tools/spike2_emu/modes/scenelog.c`` and written down in :mod:`scene_write`),
walking every byte, and writes it back byte for byte.  An editor can then change the tree -
move, scale, re-order, add, delete - and :func:`serialize` produces a file in the same grammar.

THE GRAMMAR (strings ``[u64 len][latin1]``; an id is a u32 whose top bit marks the id's FIRST
occurrence, which carries the definition; later occurrences are the bare id)::

    file       u8 1 | library [u64 n] entry* | u64 0 | stage | root (a Sprite body)
    entry      u32 symbol key | class | object      (a Font entry: scene_write._walk_font)
    class      u32 id (first: | name)
    object     u32 id (first: | the class's body)
    stage      u32 w | u32 h | f32 fps | f32 r g b a
    node       u32 id (first: the rest) | name | u32 flag
               | keyframes [u64 n](u32 frame, u8 visible)
               | colours   [u64 n](u32 frame, f32 mul r g b a, f32 add r g b a)
               | tracks    [u64 n](u32 frame, 64-byte column-major 4x4, tx ty at [12] [13])
               | components [u64 n](u32 start frame, class, object)
               | events [u64 n](u32 frame, [u64 k](call, [u64 m] arg))   (SetAnimation ...)
    Sprite     u32 symbol | name | u32 frames | [u64 n] node* | u64 0
               | labels [u64 n](name, u32 frame)
    Bitmap     u32 symbol | name | u32 w | u32 h | texture
    texture    u32 id (first: | u32 w | u32 h | u32 format | name | u32 length | blob)
    Text       u32 symbol | name | f32 L T R B | f32 r g b a | u8 u8 | u32 align | f32 f32
               | text | u32 font | [u64 n](name, u32) | [u64 n] u32 | u8 | u32
    Shape      u32 symbol | name | f32 x y w h | u32 fill (0: none | else: object, a Bitmap)
    StreamingFlipbook  a Sprite body | u32 w | u32 h
               | [u64 n] frame (u32 0 = none | a shared Frame: u32 w | u32 h | u32 fmt
               | asset | u32 index | 4x4)          asset: u32 id (first: | path | u32 size)
    Spine      u32 symbol | name | skeleton JSON | atlas text | [u64 n] texture (its pages)
    Video      u32 symbol | name | u32 w | u32 h | u32 | u8 | [u64 n](name, clip)
               | [u64 n](name, marker)
    clip       u32 id (first: | path | u32 file size)
    marker     u32 id (first: | f32 fps | [u64 n](u32 frame, name))

Ids are keys in the loader's map, not positions, so the writer emits each definition where the
id first occurs IN THE NEW ORDER: re-ordering nodes or deleting the one that defined a shared
picture moves the definition with it and the file stays loadable.

Anything this module cannot walk to the last byte is refused (:class:`SceneTreeError`); a
scene is never half-read or guessed at.
"""
from __future__ import annotations

import struct

from . import scene_write as _sw

FLAG = 0x80000000


class SceneTreeError(ValueError):
    """A file this module cannot walk exactly (or a tree it cannot write)."""


# ---------------------------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------------------------
class Node:
    """A node: a name, its timeline (keyframes, colours, tracks) and its components."""
    __slots__ = ("id", "name", "flag", "keyframes", "colors", "tracks", "components", "events",
                 "at", "end")

    def __init__(self, id, name, flag=1, keyframes=None, colors=None, tracks=None,
                 components=None, at=None, end=None):
        self.id = id
        self.name = name
        self.flag = flag
        self.keyframes = keyframes if keyframes is not None else [(1, 1)]
        self.colors = colors if colors is not None else []      # (frame, mul4, add4)
        self.tracks = tracks if tracks is not None else []      # (frame, 16 floats)
        self.components = components if components is not None else []
        self.events = []            # (frame, [(call, [args])]): the timeline's script events
        self.at, self.end = at, end

    def __repr__(self):
        return "Node(%r, %d components)" % (self.name, len(self.components))


class Component:
    __slots__ = ("start", "cls", "obj")

    def __init__(self, start, cls, obj):
        self.start, self.cls, self.obj = start, cls, obj


class Obj:
    """A shared object: ``kind`` (the class name), ``body`` (a dict, per kind)."""
    __slots__ = ("id", "kind", "body")

    def __init__(self, id, kind, body):
        self.id, self.kind, self.body = id, kind, body

    def __repr__(self):
        return "Obj(%d, %s, %r)" % (self.id, self.kind, self.body.get("name"))


class Scene:
    """``library``: ``[(symbol key, class id, Obj | ("font", raw bytes, class name span))]``;
    ``stage``: (w, h, fps, rgba); ``root``: the root Sprite body (a dict)."""

    def __init__(self):
        self.classes = {}       # class id -> name
        self.objects = {}       # object id -> Obj
        self.textures = {}      # texture id -> dict(w, h, fmt, name, blob, data_off)
        self.clips = {}         # clip id -> (path, size)
        self.markers = {}       # marker id -> (fps raw 4 bytes, [(frame, name)])
        self.assets = {}        # flipbook asset id -> (path under scene.assets, file size)
        self.library = []
        self.stage = None
        self.root = None
        self.fonts = []         # (entry offset, entry end) of each Font entry
        self.font_sizes = {}    # size id -> dict(offset, variant, entry, line, ascent, descent)

    # --- convenience ----------------------------------------------------------------------
    def walk(self, library=False):
        """Every node on the STAGE, depth first in file (= draw) order, as ``(node, parent
        node or None, depth)``.  A shared object's children are walked where it is first
        placed.

        The library holds the scene's symbols as TEMPLATES (Battle Select's library carries a
        ``CharacterSelect_Instance`` of its own beside the one the root places); the stage
        draws the root's instances, so templates are walked only when *library* is asked
        for, and then first, as their own roots."""
        out = []
        seen = set()

        def sprite(body, parent, depth):
            for kid in body["kids"]:
                out.append((kid, parent, depth))
                for c in kid.components:
                    if c.obj.kind == "Sprite" and c.obj.id not in seen:
                        seen.add(c.obj.id)
                        sprite(c.obj.body, kid, depth + 1)

        for _k, _c, obj in (self.library if library else ()):
            if isinstance(obj, Obj) and obj.kind == "Sprite" and obj.id not in seen:
                seen.add(obj.id)
                sprite(obj.body, None, 0)
        sprite(self.root, None, 0)
        return out

    def class_id(self, name):
        for k, v in self.classes.items():
            if v == name:
                return k
        return None


# ---------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------
class _R:
    def __init__(self, d):
        self.d, self.o = d, 0

    def take(self, n):
        if self.o + n > len(self.d):
            raise SceneTreeError("the file ends inside a field at 0x%x" % self.o)
        b = self.d[self.o:self.o + n]
        self.o += n
        return b

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def f32s(self, n):
        return list(struct.unpack("<%df" % n, self.take(4 * n)))

    def count(self, cap=1 << 20):
        n = self.u64()
        if n > cap:
            raise SceneTreeError("a list of %d at 0x%x" % (n, self.o - 8))
        return n

    def string(self):
        n = self.count(1 << 22)
        return self.take(n).decode("latin1")


class _Reader:
    def __init__(self, data):
        self.r = _R(data)
        self.s = Scene()

    def cls(self):
        v = self.r.u32()
        if v & FLAG:
            v &= ~FLAG
            if v in self.s.classes:
                raise SceneTreeError("class %d registered twice at 0x%x" % (v, self.r.o - 4))
            self.s.classes[v] = self.r.string()
        elif v not in self.s.classes:
            raise SceneTreeError("class %d used before it is registered at 0x%x"
                                 % (v, self.r.o - 4))
        return v

    def obj(self, cid, kind=None):
        v = self.r.u32()
        if not v & FLAG:
            o = self.s.objects.get(v)
            if o is None:
                raise SceneTreeError("object %d referenced before it is defined at 0x%x"
                                     % (v, self.r.o - 4))
            return o
        oid = v & ~FLAG
        if oid in self.s.objects:
            raise SceneTreeError("object %d defined twice at 0x%x" % (oid, self.r.o - 4))
        kind = kind or self.s.classes[cid]
        o = Obj(oid, kind, None)
        self.s.objects[oid] = o
        o.body = self.body(kind)
        return o

    def texture(self):
        v = self.r.u32()
        if not v & FLAG:
            return v          # a picture defined earlier, or a font's own page
        tid = v & ~FLAG
        w, h, fmt = self.r.u32(), self.r.u32(), self.r.u32()
        name = self.r.string()
        n = self.r.u32()
        at = self.r.o
        blob = self.r.take(n)
        self.s.textures[tid] = dict(w=w, h=h, fmt=fmt, name=name, blob=blob, data_off=at)
        return tid

    def body(self, kind):
        r = self.r
        if kind == "Sprite":
            sym = r.u32()
            name = r.string()
            frames = r.u32()
            kids = [self.node() for _ in range(r.count())]
            if r.u64():
                raise SceneTreeError("a Sprite's second list is not empty at 0x%x" % (r.o - 8))
            labels = [(r.string(), r.u32()) for _ in range(r.count())]
            return dict(sym=sym, name=name, frames=frames, kids=kids, labels=labels)
        if kind == "Bitmap":
            sym = r.u32()
            name = r.string()
            w, h = r.u32(), r.u32()
            return dict(sym=sym, name=name, w=w, h=h, tex=self.texture())
        if kind == "Text":
            sym = r.u32()
            name = r.string()
            rect, rgba = r.f32s(4), r.f32s(4)
            flags = (r.u8(), r.u8())
            align = r.u32()
            spacing = r.f32s(2)
            text = r.take(r.count(1 << 16))
            font = r.u32()
            fonts = [(r.string(), r.u32()) for _ in range(r.count())]
            used = [r.u32() for _ in range(r.count())]      # the font sizes it draws with
            tail = (r.u8(), r.u32())
            return dict(sym=sym, name=name, rect=rect, rgba=rgba, flags=flags, align=align,
                        spacing=spacing, text=text, font=font, fonts=fonts, used=used, tail=tail)
        if kind == "Shape":
            sym = r.u32()
            name = r.string()
            rect = r.f32s(4)
            fill = r.u32()
            # fill 0: none; otherwise a Bitmap object follows, named by id alone (no class id)
            bm = self.obj(None, "Bitmap") if fill else None
            return dict(sym=sym, name=name, rect=rect, fill=fill, bitmap=bm)
        if kind == "Video":
            sym = r.u32()
            name = r.string()
            w, h, x = r.u32(), r.u32(), r.u32()
            b = r.u8()
            clips = []
            for _ in range(r.count()):
                cname = r.string()
                v = r.u32()
                if v & FLAG:
                    cid = v & ~FLAG
                    self.s.clips[cid] = (r.string(), r.u32())
                else:
                    cid = v
                    if cid not in self.s.clips:
                        raise SceneTreeError("clip %d referenced before it is defined" % cid)
                clips.append((cname, cid))
            marked = []
            for _ in range(r.count()):
                mname = r.string()
                v = r.u32()
                if v & FLAG:
                    mid = v & ~FLAG
                    fps = r.take(4)
                    marks = [(r.u32(), r.string()) for _ in range(r.count())]
                    self.s.markers[mid] = (fps, marks)
                else:
                    mid = v
                marked.append((mname, mid))
            return dict(sym=sym, name=name, w=w, h=h, x=x, b=b, clips=clips, marked=marked)
        if kind == "Spine":                      # a Spine 3.1 skeleton + its atlas pages
            sym = r.u32()
            name = r.string()
            skeleton = r.take(r.count(1 << 26))
            atlas = r.take(r.count(1 << 22))
            pages = [self.texture() for _ in range(r.count())]
            return dict(sym=sym, name=name, skeleton=skeleton, atlas=atlas, pages=pages)
        if kind == "StreamingFlipbook":          # a Sprite, then its streamed frames
            b = self.body("Sprite")
            b["w"], b["h"] = r.u32(), r.u32()
            b["seq"] = [self.flip_frame() for _ in range(r.count())]
            return b
        raise SceneTreeError("no walker for class %r at 0x%x" % (kind, r.o))

    def flip_frame(self):
        """One frame of a StreamingFlipbook: 0 (no picture this frame), or a shared Frame -
        ``w h fmt | asset | u32 index | 4x4`` - whose asset (the ``scene.assets`` file it
        streams) is itself shared: ``u32 id (first: | path | u32 file size)``."""
        r = self.r
        v = r.u32()
        if not v & FLAG:
            if v and v not in self.s.objects:
                raise SceneTreeError("flipbook frame %d referenced before it is defined" % v)
            return self.s.objects.get(v) if v else None
        fid = v & ~FLAG
        w, h, fmt = r.u32(), r.u32(), r.u32()
        a = r.u32()
        if a & FLAG:
            aid = a & ~FLAG
            self.s.assets[aid] = (r.string(), r.u32())
        else:
            aid = a
            if aid not in self.s.assets:
                raise SceneTreeError("flipbook asset %d referenced before it is defined" % aid)
        index = r.u32()
        m = r.f32s(16)
        o = Obj(fid, "FlipFrame", dict(w=w, h=h, fmt=fmt, asset=aid, index=index, m=m))
        self.s.objects[fid] = o
        return o

    def node(self):
        r = self.r
        at = r.o
        v = r.u32()
        if not v & FLAG:
            raise SceneTreeError("a node by reference (%d) at 0x%x" % (v, at))
        name = r.string()
        flag = r.u32()
        kf = [(r.u32(), r.u8()) for _ in range(r.count())]
        colors = [(r.u32(), r.f32s(4), r.f32s(4)) for _ in range(r.count())]
        tracks = [(r.u32(), r.f32s(16)) for _ in range(r.count())]
        comps = []
        for _ in range(r.count()):
            start = r.u32()
            cid = self.cls()
            comps.append(Component(start, cid, self.obj(cid)))
        events = [(r.u32(), [(r.string(), [r.string() for _ in range(r.count())])
                             for _ in range(r.count())]) for _ in range(r.count())]
        n = Node(v & ~FLAG, name, flag, kf, colors, tracks, comps, at, r.o)
        n.events = events
        return n

    def run(self):
        r, s = self.r, self.s
        if r.u8() != 1:
            raise SceneTreeError("not a scene (first byte is not 1)")
        for _ in range(r.count()):
            at = r.o
            key = r.u32()
            v = struct.unpack_from("<I", r.d, r.o)[0]
            cid = v & ~FLAG
            name = s.classes.get(cid)
            if v & FLAG:
                save = r.o
                r.u32()
                name = r.string()
                r.o = save
            if name == "Font":
                end, sizes, face = _font_end(r.d, at)
                for sid, off, variant in sizes:
                    # the size record: u32 key | f32 line height | f32 ascent | f32 descent
                    line, asc, desc = struct.unpack_from("<3f", r.d, off + 4)
                    s.font_sizes[sid] = dict(offset=off, variant=variant, entry=len(s.fonts),
                                             line=line, ascent=asc, descent=desc, face=face)
                if v & FLAG:
                    s.classes[cid] = "Font"
                s.library.append((key, cid, ("font", r.d[at + 4:end])))
                s.fonts.append((at, end))
                r.o = end
                continue
            cid = self.cls()
            s.library.append((key, cid, self.obj(cid)))
        if r.u64():
            raise SceneTreeError("the library is not followed by 0 at 0x%x" % (r.o - 8))
        w, h = r.u32(), r.u32()
        fps = r.f32s(1)[0]
        rgba = r.f32s(4)
        s.stage = (w, h, fps, rgba)
        s.root = self.body("Sprite")
        if r.o != len(r.d):
            raise SceneTreeError("the walk ended at 0x%x of 0x%x" % (r.o, len(r.d)))
        return s


def _font_end(d, at):
    """``(end, [(size id, offset, variant)], face)``: where the Font library entry at *at*
    ends, and each of its SIZES - the object a Text names as its font - with the offset its
    record starts at (its glyph table follows) and its style variant ("" = the base sizes),
    and the typeface it was made from (``STERN_HelveticaNeueBlack``).
    :func:`scene_write._walk_font`'s walk
    (which Modes relies on, with its caps) without the caps: a scene's game font can carry
    30 style variants (Iron Maiden) and long kerning lists."""
    w = _sw._Walk(d, at)
    key = w.take("<I")
    if w.take("<I") & FLAG and w.string() != b"Font":
        raise SceneTreeError("a Font entry that is not a Font at 0x%x" % at)
    w.new()
    if w.take("<I") != key:
        raise SceneTreeError("a Font's key does not repeat at 0x%x" % at)
    w.string()
    face = w.string().decode("latin1")
    w.o += 2
    n = w.take("<Q")           # (not ``w.o += 2 * w.take()``: that reads w.o before take moves it)
    w.o += 2 * n

    def sizes(variant):
        for _ in range(w.take("<Q")):
            w.o += 4
            w.new()
            found.append((w.ids[-1][1], w.o, variant))
            if w.take("<I") != key:
                raise SceneTreeError("a font size does not name its font at 0x%x" % w.o)
            w.o += 13
            for _ in range(w.take("<Q")):
                w.o += 2
                w.new()
                w.o += 29 + 16
                w.page()
                kern = w.take("<Q")
                if kern > 1 << 16:
                    raise SceneTreeError("a glyph with %d kerning pairs at 0x%x" % (kern, w.o))
                w.o += 6 * kern

    found = []
    try:
        sizes("")
        nv = w.take("<Q")
        if nv > 4096:
            raise SceneTreeError("a font with %d variants at 0x%x" % (nv, w.o))
        for _ in range(nv):
            sizes(w.string().decode("latin1"))
    except (_sw.SceneWriteError, struct.error) as e:
        raise SceneTreeError("the Font at 0x%x does not walk: %s" % (at, e))
    return w.o, found, face


def parse(data):
    """The scene in *data* as a :class:`Scene`; :class:`SceneTreeError` unless every byte
    walks."""
    try:
        return _Reader(bytes(data)).run()
    except struct.error as e:
        raise SceneTreeError(str(e))


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------
class _W:
    def __init__(self, scene):
        self.s = scene
        self.out = bytearray()
        self.cls_seen, self.obj_seen, self.tex_seen = set(), set(), set()
        self.clip_seen, self.mark_seen, self.asset_seen = set(), set(), set()

    def u8(self, v):
        self.out += struct.pack("<B", v)

    def u32(self, v):
        self.out += struct.pack("<I", v & 0xFFFFFFFF)

    def u64(self, v):
        self.out += struct.pack("<Q", v)

    def f32s(self, vs):
        self.out += struct.pack("<%df" % len(vs), *vs)

    def string(self, s):
        b = s.encode("latin1") if isinstance(s, str) else bytes(s)
        self.u64(len(b))
        self.out += b

    def cls(self, cid):
        if cid in self.cls_seen:
            self.u32(cid)
        else:
            self.cls_seen.add(cid)
            self.u32(FLAG | cid)
            self.string(self.s.classes[cid])

    def obj(self, o):
        if o.id in self.obj_seen:
            self.u32(o.id)
            return
        self.obj_seen.add(o.id)
        self.u32(FLAG | o.id)
        self.body(o.kind, o.body)

    def texture(self, tid):
        if tid == 0 or tid in self.tex_seen or tid not in self.s.textures:
            self.u32(tid)
            return
        self.tex_seen.add(tid)
        t = self.s.textures[tid]
        self.u32(FLAG | tid)
        self.u32(t["w"])
        self.u32(t["h"])
        self.u32(t["fmt"])
        self.string(t["name"])
        self.u32(len(t["blob"]))
        self.out += t["blob"]

    def body(self, kind, b):
        if kind == "Sprite":
            self.u32(b["sym"])
            self.string(b["name"])
            self.u32(b["frames"])
            self.u64(len(b["kids"]))
            for k in b["kids"]:
                self.node(k)
            self.u64(0)
            self.u64(len(b["labels"]))
            for name, fr in b["labels"]:
                self.string(name)
                self.u32(fr)
        elif kind == "Bitmap":
            self.u32(b["sym"])
            self.string(b["name"])
            self.u32(b["w"])
            self.u32(b["h"])
            self.texture(b["tex"])
        elif kind == "Text":
            self.u32(b["sym"])
            self.string(b["name"])
            self.f32s(b["rect"])
            self.f32s(b["rgba"])
            self.u8(b["flags"][0])
            self.u8(b["flags"][1])
            self.u32(b["align"])
            self.f32s(b["spacing"])
            self.string(b["text"])
            self.u32(b["font"])
            self.u64(len(b["fonts"]))
            for name, fid in b["fonts"]:
                self.string(name)
                self.u32(fid)
            self.u64(len(b["used"]))
            for fid in b["used"]:
                self.u32(fid)
            self.u8(b["tail"][0])
            self.u32(b["tail"][1])
        elif kind == "Shape":
            self.u32(b["sym"])
            self.string(b["name"])
            self.f32s(b["rect"])
            self.u32(b["fill"])
            if b["fill"]:
                self.obj(b["bitmap"])
        elif kind == "Video":
            self.u32(b["sym"])
            self.string(b["name"])
            self.u32(b["w"])
            self.u32(b["h"])
            self.u32(b["x"])
            self.u8(b["b"])
            self.u64(len(b["clips"]))
            for cname, cid in b["clips"]:
                self.string(cname)
                if cid in self.clip_seen:
                    self.u32(cid)
                else:
                    self.clip_seen.add(cid)
                    self.u32(FLAG | cid)
                    path, size = self.s.clips[cid]
                    self.string(path)
                    self.u32(size)
            self.u64(len(b["marked"]))
            for mname, mid in b["marked"]:
                self.string(mname)
                if mid in self.mark_seen or mid not in self.s.markers:
                    self.u32(mid)
                else:
                    self.mark_seen.add(mid)
                    self.u32(FLAG | mid)
                    fps, marks = self.s.markers[mid]
                    self.out += fps
                    self.u64(len(marks))
                    for fr, name in marks:
                        self.u32(fr)
                        self.string(name)
        elif kind == "Spine":
            self.u32(b["sym"])
            self.string(b["name"])
            self.string(b["skeleton"])
            self.string(b["atlas"])
            self.u64(len(b["pages"]))
            for tid in b["pages"]:
                self.texture(tid)
        elif kind == "StreamingFlipbook":
            self.body("Sprite", b)
            self.u32(b["w"])
            self.u32(b["h"])
            self.u64(len(b["seq"]))
            for fr in b["seq"]:
                self.flip_frame(fr)
        else:
            raise SceneTreeError("cannot write class %r" % kind)

    def flip_frame(self, fr):
        if fr is None:
            self.u32(0)
            return
        if fr.id in self.obj_seen:
            self.u32(fr.id)
            return
        self.obj_seen.add(fr.id)
        b = fr.body
        self.u32(FLAG | fr.id)
        self.u32(b["w"])
        self.u32(b["h"])
        self.u32(b["fmt"])
        if b["asset"] in self.asset_seen:
            self.u32(b["asset"])
        else:
            self.asset_seen.add(b["asset"])
            self.u32(FLAG | b["asset"])
            path, size = self.s.assets[b["asset"]]
            self.string(path)
            self.u32(size)
        self.u32(b["index"])
        self.f32s(b["m"])

    def node(self, n):
        self.u32(FLAG | n.id)
        self.string(n.name)
        self.u32(n.flag)
        self.u64(len(n.keyframes))
        for fr, vis in n.keyframes:
            self.u32(fr)
            self.u8(vis)
        self.u64(len(n.colors))
        for fr, mul, add in n.colors:
            self.u32(fr)
            self.f32s(mul)
            self.f32s(add)
        self.u64(len(n.tracks))
        for fr, m in n.tracks:
            if len(m) != 16:
                raise SceneTreeError("node %r: a track matrix has %d floats" % (n.name, len(m)))
            self.u32(fr)
            self.f32s(m)
        self.u64(len(n.components))
        for c in n.components:
            self.u32(c.start)
            self.cls(c.cls)
            self.obj(c.obj)
        self.u64(len(n.events))
        for fr, calls in n.events:
            self.u32(fr)
            self.u64(len(calls))
            for name, args in calls:
                self.string(name)
                self.u64(len(args))
                for a in args:
                    self.string(a)

    def run(self):
        s = self.s
        self.u8(1)
        self.u64(len(s.library))
        for key, cid, obj in s.library:
            self.u32(key)
            if isinstance(obj, tuple):          # a Font entry, carried as it was read
                self.out += obj[1]
                self.cls_seen.add(cid)
                continue
            self.cls(cid)
            self.obj(obj)
        self.u64(0)
        w, h, fps, rgba = s.stage
        self.u32(w)
        self.u32(h)
        self.f32s([fps])
        self.f32s(rgba)
        self.body("Sprite", s.root)
        return bytes(self.out)


def serialize(scene):
    """The bytes of *scene* in the grammar :func:`parse` reads.  An unedited scene comes back
    byte for byte."""
    return _W(scene).run()
