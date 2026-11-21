"""Grow display-text strings inside a Spike 2 ``scene.radium`` by
re-serialising it.

The in-place text patch (``engine._radium_text_writes``) keeps a scene
byte-identical in size: a replacement has to fit the original's slot and is
space-padded to it.  A LONGER replacement can't, and the scene has no room
to spare -- so instead the file is rewritten with the new length.

A radium is a flat, forward-only serialised stream: strings are ``[u64
len][latin1]``, nodes ``[HANDLE][type STR][HANDLE][payload]``, images
``[dispW][dispH][HANDLE][texW][texH][fmt][0][0][u64 len][data]``, and the
keyframe blocks that carry display text ``[HANDLE][seq][u64 0][rect][rgba]
[u16][align][spacing][u32][STR][font handle]...``.  A format census over
Godzilla's scenes (2026-09-07: the attract score display, the HUD, the
battle intros, the 794 KB / 1.5 MB twin families, the texture and video
catalogues -- see ``plans/spike2_longer_program_text.md``'s scene half)
found NO absolute file offset and NO total-size field anywhere: every count
is a count (object count, glyph count, kern count, dictionary length), every
length is the record's own, the video/texture ``u32`` after an asset path is
that OTHER file's size, the trailing dictionary's values are ids / frame
numbers, and the keyframe's trailing word is a FONT HANDLE (steps of 98 =
97 glyphs + 1, the same value at both positions of a repeated string).
Twin scenes Stern ships differing only in one string's length are byte-
identical everywhere else.  So rewriting one string's ``[u64 len][bytes]``
and letting everything after it shift is a valid file for every parser in
this repo (the ``agree`` check below proves it on each grown file) -- and,
by that census, for the game's loader; the latter is proven in the PC
emulator only, never on a machine.

An embedded IMAGE can change size the same way (PAD-154: a Japanese name
banner that has to hold a longer name).  Its record is re-serialised with
the new width, height, length and block data, and every sprite instance
that draws it is repointed: an instance names its image by the triple
``[u32 dispW][u32 dispH][u32 handle & 0xFFFFFF]`` (see
``scene_layout._instance_image``), so the dimensions are written there too.
On Godzilla's Kaiju Battle Select scene each name banner has exactly four
such triples and no other copy of its size anywhere in the file, u32 or
float.

:func:`regrow` is the re-serialiser (:func:`grow` its text-only form);
:func:`agree` compares every repo parser's view of the stock and grown
files (offsets passed through the shift) and is what the tests pin.  The
engine composes a scene's other in-place edits (colours, layout, embedded
images -- all at stock offsets) into the stock bytes BEFORE growing, so
their offsets stay valid.
"""

import math
import struct

#: ``[dispW][dispH][handle][texW][texH][fmt][0][0][u32 length]`` -- the
#: record's bytes before its block data (``engine.parse_radium_images``).
IMAGE_HEADER_LEN = 36
_DXT1_FORMAT = 4


def _padded4(x):
    return ((x + 3) // 4) * 4


def image_block_len(w, h, fmt):
    """Bytes of block data a *w* x *h* image takes in format *fmt*: one byte
    per pixel of the 4x4-padded grid for BC3, half that for BC1."""
    n = _padded4(w) * _padded4(h)
    return n // 2 if fmt == _DXT1_FORMAT else n


def image_record(data, data_off):
    """The record of the image whose block data starts at *data_off*:
    ``{disp_w, disp_h, handle, tex_w, tex_h, fmt, length}``."""
    (disp_w, disp_h, handle, tex_w, tex_h, fmt, _z0, _z1,
     length) = struct.unpack_from("<9I", data, data_off - IMAGE_HEADER_LEN)
    return dict(disp_w=disp_w, disp_h=disp_h, handle=handle, tex_w=tex_w,
                tex_h=tex_h, fmt=fmt, length=length)


def drawn_by(scene):
    """``{texture id: {"bitmaps": n, "fills": [(w, h), ...]}}`` for a parsed
    :class:`scene_tree.Scene`: how many Bitmaps name each picture, and the
    size of every Shape box that fills with one (PAD-857).

    A Bitmap draws its picture at its own ``[w][h]``: the FIRST Bitmap of a
    picture carries the picture's definition right after them, so its size
    is the record's ``disp`` pair, and every later one is an
    :func:`image_refs` triple; :func:`regrow` rewrites both.  A Shape squeezes
    its fill Bitmap into its own box (``rect`` is left, top, right, bottom),
    which regrow leaves alone: a bigger fill keeps its place and size on
    screen and is sharper where the scene zooms in (emulator: Godzilla's
    attract title, 517x660, drawn whole at 1034x1320 in the same box)."""
    out = {}

    def entry(tid):
        return out.setdefault(tid, {"bitmaps": 0, "fills": []})
    for o in scene.objects.values():
        if o.kind == "Bitmap":
            entry(o.body["tex"])["bitmaps"] += 1
        elif o.kind == "Shape" and o.body.get("bitmap") is not None:
            left, top, right, bottom = o.body["rect"]
            entry(o.body["bitmap"].body["tex"])["fills"].append(
                (int(round(right - left)), int(round(bottom - top))))
    return out


def image_refs(data, data_off, images=None):
    """File offsets of every sprite-instance triple that draws the image at
    *data_off* (``[dispW][dispH][handle & 0xFFFFFF]``, or the texture size in
    the dims' place, both of which ``scene_layout`` accepts).  Matches inside
    any image's own record - its block data, or its 36-byte header - are not
    references and are left out; *images* is
    ``engine.parse_radium_images(data)`` when the caller already has it.

    The header half matters because a record's ``[texW][texH][fmt]`` has the
    triple's shape, and handles are small: on Godzilla's scenes a 1360x768
    BC3 picture with handle 4 "matched" the header of a 1360x768 BC1 one
    (format 4), and resizing the first rewrote the second's texture size."""
    if images is None:
        from .engine import parse_radium_images
        images = parse_radium_images(data)
    rec = image_record(data, data_off)
    blocks = [(im["data_off"] - IMAGE_HEADER_LEN, im["data_off"] + im["length"])
              for im in images]
    h = rec["handle"] & 0xFFFFFF
    out = []
    for w, hh in {(rec["disp_w"], rec["disp_h"]), (rec["tex_w"], rec["tex_h"])}:
        pat = struct.pack("<3I", w, hh, h)
        i = data.find(pat)
        while i >= 0:
            if not any(lo <= i < hi for lo, hi in blocks):
                out.append(i)
            i = data.find(pat, i + 1)
    return sorted(out)


def regrow(data, texts=None, images=None):
    """Re-serialise *data* with longer display text and/or resized images.

    *texts* is ``{old: new}`` (str -> str): every display-text occurrence
    equal to a key is rewritten as ``[u64 len(new)][new]`` -- the Text-node
    keyframes AND the instance keyframes, the same set the in-place patch
    rewrites (``radium.display_texts``).

    *images* is ``{data_off: (width, height, block_bytes)}``: the image whose
    block data starts at ``data_off`` becomes *width* x *height* (display and
    texture size alike, format kept), its length word and data replaced by
    *block_bytes* (which must be :func:`image_block_len` long), and every
    instance triple that draws it (:func:`image_refs`) carries the new size.

    Returns ``{"data", "texts": {old: occurrences}, "images": {data_off:
    references}, "shift"}``; *shift* maps a STOCK file offset to its offset in
    the grown file (piecewise by insertion point).  Only those bytes change;
    every other byte is copied.  Raises ``ValueError`` for an image edit that
    does not describe a real record or whose block data is the wrong size."""
    from . import radium
    from .engine import parse_radium_images
    buf = bytearray(data)
    splices = []                     # (start, end, replacement) on stock offsets
    n_img = {}
    if images:
        parsed = parse_radium_images(data)
        known = {im["data_off"]: im for im in parsed}
        for off, rec4 in sorted(images.items()):
            w, h, payload = rec4[:3]             # a fourth: the picture's own size (keep_boxes)
            im = known.get(off)
            if im is None:
                raise ValueError("no embedded image starts at %#x" % off)
            if not (0 < w <= 8192 and 0 < h <= 8192):
                raise ValueError("image %#x: %dx%d is not a texture size"
                                 % (off, w, h))
            if len(payload) != image_block_len(w, h, im["fmt"]):
                raise ValueError("image %#x: %d bytes of block data for %dx%d"
                                 % (off, len(payload), w, h))
            rec = image_record(data, off)
            refs = image_refs(data, off, parsed)
            for r in refs:
                struct.pack_into("<2I", buf, r, w, h)
            hdr = off - IMAGE_HEADER_LEN
            struct.pack_into("<2I", buf, hdr, w, h)          # disp
            struct.pack_into("<2I", buf, hdr + 12, w, h)     # tex
            struct.pack_into("<I", buf, off - 4, len(payload))
            splices.append((off, off + rec["length"], bytes(payload)))
            n_img[off] = len(refs)
    n_txt = {}
    if texts:
        enc = {k.encode("latin1", "replace"): v.encode("latin1", "replace")
               for k, v in texts.items()}
        for e in radium.display_texts(data):
            old = data[e["offset"]:e["offset"] + e["length"]]
            new = enc.get(old)
            if new is None:
                continue
            splices.append((e["prefix_offset"], e["offset"] + e["length"],
                            struct.pack("<Q", len(new)) + new))
            n_txt[e["text"]] = n_txt.get(e["text"], 0) + 1
    splices.sort()
    out = bytearray()
    pos = 0
    points = []                      # (stock offset after the splice, delta)
    delta = 0
    for start, end, new in splices:
        if start < pos:
            raise ValueError("overlapping edits at %#x" % start)
        out += buf[pos:start]
        out += new
        pos = end
        delta += len(new) - (end - start)
        points.append((pos, delta))
    out += buf[pos:]

    def shift(off):
        d = 0
        for p, cd in points:
            if off >= p:
                d = cd
            else:
                break
        return off + d
    return {"data": bytes(out), "texts": n_txt, "images": n_img,
            "shift": shift}


def fit_box(w, h, bw, bh):
    """The affine ``(a, b, c, d, tx, ty)`` that draws a *w* x *h* picture inside a *bw* x *bh*
    box: scaled to fit whole (its shape kept) and centred in it (PAD-865)."""
    s = min(bw / float(w), bh / float(h))
    return (s, 0.0, 0.0, s, (bw - s * w) / 2.0, (bh - s * h) / 2.0)


# PAD-1200: how many of a kept picture's pixels a Write keeps per pixel of the box the game
# fits it into.  The game draws a scene picture from ONE texture level with a LINEAR filter
# (no mipmaps, padglhost's MIN_FILTER record), so a texture many times bigger than where it
# shows is sampled at scattered texels: DragonRR's 2020x3070 Battle Select grid, fitted into
# its ~400x600 box, came out grainy and jagged in the emulator while PAD's preview (a proper
# resize) looked clean.  Two pixels per box pixel keep PAD-865's extra detail for where a
# scene zooms in, and a LINEAR filter at half size still averages neighbouring texels.
KEEP_HEADROOM = 2.0


def kept_texture_size(w, h, boxes, headroom=KEEP_HEADROOM):
    """``(w, h)`` a *w* x *h* picture kept at its own size is written at, or None to write it
    as it is: shrunk, its shape kept, to *headroom* times the biggest of *boxes* (``(bw, bh)``
    pairs: the stock picture's own size and every Shape box it fills) it is fitted into
    (:func:`fit_box`).  Where it shows on the glass does not change, since the fit is worked
    out from the box, not the picture."""
    boxes = [(bw, bh) for bw, bh in boxes or () if bw and bh]
    if not (w and h and boxes):
        return None
    s = max(min(bw / float(w), bh / float(h)) for bw, bh in boxes) * headroom
    if s >= 1.0:
        return None
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


# Simon (2026-11-21): "high res = better ... is not the case. We should be optimising for the actual screen" - a
# picture kept at its own size is written at the most the game ever shows it on the glass, not at twice its box:
# Godzilla 1.16's Battle Select cards are drawn at two thirds of their 527x725 box at most (346x476), its earth
# map zooms in to 2x its 1360x768 box (2734x1544).  The box alone also grew on every Write onto a card PAD had
# already written (DragonRR's V2.3: 632x828 -> 1264x904 -> 2528x1808), since that card's box was the last
# Write's picture; the box times its zoom is the same on every such card (keep_boxes takes the growth back out of
# the node's tracks).
def _track_scale(m):
    """The biggest of the two axes' scales of a node's track *m* (16 floats, column-major)."""
    return max(math.hypot(m[0], m[1]), math.hypot(m[4], m[5]))


def node_zooms(scene):
    """``{node id: the biggest scale it is ever drawn at}`` for a parsed scene: its own tracks' biggest times its
    groups', down from the root.  Each level's biggest is taken whatever the frame, so it is an upper bound where
    a group and its node peak at different moments.  A node whose timeline never shows it (and what is under it)
    is left out: the game's code can hide a node, never reveal one its timeline hides."""
    out = {}

    def run(kids, up, path):
        for n in kids:
            if n.keyframes and not any(v for _f, v in n.keyframes):
                continue
            z = up * max((_track_scale(m) for _f, m in n.tracks or ()), default=1.0)
            out[n.id] = max(out.get(n.id, 0.0), z)
            for c in n.components:
                if c.obj.kind in ("Sprite", "StreamingFlipbook") and c.obj.id not in path:
                    run(c.obj.body["kids"], z, path | {c.obj.id})
    run(scene.root["kids"], 1.0, frozenset())
    return out


def shown_scale(scene, tids, natural, own=(), own_boxes=None):
    """How big the game shows a picture of *natural* ``(w, h)`` drawn as the textures *tids* of *scene* (parsed,
    the card's scene with the Scenes tab's edits on): the biggest, over every place that draws it, of the
    picture's scale on the glass (1.0 = one pixel of the picture to one pixel of the screen).  ``(scale, left)``,
    *left* True when a node draws it together with something else (its size can't follow the picture's), or
    ``(None, left)`` when nothing that shows draws it.

    A Bitmap's node draws the picture fitted into its box (:func:`keep_boxes`, PAD-865) - the Bitmap's own
    ``[w][h]`` - or, in *own* (laid out over it at its own size, PAD-981; a picture placed pixel for pixel,
    Simon 2026-11-21), at its own size, or fitted into its *own_boxes* box (PAD-1301).  A Shape squeezes it into
    the Shape's box, narrowed to its shape."""
    zooms = node_zooms(scene)
    iw, ih = natural
    if not (iw and ih):
        return None, False
    best, left = None, False
    from .scene_edit import _tree_index
    for n, _sibs in _tree_index(scene).values():
        z = zooms.get(n.id)
        if z is None:
            continue
        for c in n.components:
            o = c.obj
            if o.kind == "Bitmap" and o.body.get("tex") in tids:
                if len(n.components) != 1:
                    left = True
                box = (own_boxes or {}).get(n.id) if n.id in own else (o.body["w"], o.body["h"])
                u = (1.0 if n.id in own and not box
                     else min(box[0] / float(iw), box[1] / float(ih)) if box and box[0] and box[1] else 1.0)
            elif o.kind == "Shape" and o.body.get("bitmap") is not None \
                    and o.body["bitmap"].body.get("tex") in tids:
                left_, top, right, bottom = o.body["rect"]
                rw, rh = abs(right - left_), abs(bottom - top)
                if not (rw and rh):
                    continue
                u = min(rw / float(iw), rh / float(ih))
            else:
                continue
            s = u * z
            best = s if best is None else max(best, s)
    return best, left


def shown_size(natural, scale):
    """``(w, h)``: a picture of *natural* size at *scale* (:func:`shown_scale`), never bigger than itself."""
    iw, ih = natural
    s = min(1.0, scale)
    return max(1, int(math.ceil(iw * s - 1e-6))), max(1, int(math.ceil(ih * s - 1e-6)))


def nodes_drawing(scene, tids):
    """The ids of the nodes of *scene* (parsed) with a Bitmap of one of the textures *tids*."""
    from .scene_edit import _tree_index
    return {n.id for n, _sibs in _tree_index(scene).values()
            if any(c.obj.kind == "Bitmap" and c.obj.body.get("tex") in tids
                   for c in n.components)}


def every_draw_fitted(scene, tids, own=()):
    """True when every node of *scene* (parsed, stock) that draws one of the textures *tids*
    has :func:`keep_boxes` fit it into its box: none draws it together with something else
    (those are left drawing it at its own size) and none is in *own* (laid out over it at its
    own size, PAD-981).  Only then can a Write shrink the texture without moving anything."""
    from .scene_edit import _tree_index
    for n, _sibs in _tree_index(scene).values():
        mine = [c for c in n.components
                if c.obj.kind == "Bitmap" and c.obj.body.get("tex") in tids]
        if mine and (n.id in own or len(mine) != len(n.components)):
            return False
    return True


def keep_boxes(stock, grown, offs, own=(), own_boxes=None, natural=None):
    """*grown* (a scene :func:`regrow` resized the pictures at the stock offsets *offs* in)
    with each of those pictures shown in its stock place and size, fitted and centred:
    ``(bytes, n nodes, n shapes, n left)``.  The nodes in *own* were moved or resized in the
    Scenes window over the picture at its own size, before this fit (PAD-981,
    :func:`scene_edit.own_size_nodes`), so they keep drawing it at that size.

    The game draws a Bitmap's ``[w][h]`` texels 1:1 in its node's units from the node's
    origin, and a bigger texture under a stock ``[w][h]`` is CROPPED to its top-left corner
    (PAD-865, emulator: Godzilla LE's in-game tank icon).  So a picture kept at its own
    size (DragonRR: "retain the original image's size ... keep the image centered") keeps
    its new size, and every node that draws it has :func:`fit_box` multiplied into its
    tracks on the right, inside whatever the Scenes window did to the node: the same
    picture the Scenes preview draws.  A Shape's fill is squeezed into the Shape's box by
    the game (PAD-857), so its box is narrowed to the picture's shape, centred.  A node
    that also draws something else (another picture over its timeline, text, a group) is
    left as it was and counted in *n left*.  A node of *own* that *own_boxes* (``{node: (w,
    h)}``, :func:`scene_edit.own_boxes`) gives a box is fitted into that box instead: the size
    of the picture its layout was made over, since replaced (PAD-1301).

    *natural* ``{stock data_off: (w, h)}`` (Simon, 2026-11-21) is each picture's own size where the Write wrote it
    smaller, for the screen (:func:`shown_scale`): a node of *own* with no box draws it at that size still, its
    tracks scaled by the picture's own size over the written one."""
    from . import scene_tree
    from .scene_edit import _composed, _m16_with, _m6_of16, _tree_index
    sc0 = scene_tree.parse(stock)
    sc = scene_tree.parse(grown)
    tids = {tid for tid, t in sc0.textures.items() if t.get("data_off") in set(offs)}
    if not tids:
        return grown, 0, 0, 0
    nat_of = {tid: (natural or {}).get(t.get("data_off")) for tid, t in sc0.textures.items() if tid in tids}

    def box_of(o):
        was = sc0.objects.get(o.id)
        if was is None or was.kind != "Bitmap":
            return None
        w, h, bw, bh = o.body["w"], o.body["h"], was.body["w"], was.body["h"]
        if not (w and h and bw and bh) or (w, h) == (bw, bh):
            return None
        return fit_box(w, h, bw, bh)
    n_nodes = n_shapes = n_left = 0
    for n, _sibs in _tree_index(sc).values():
        mine = [c.obj for c in n.components
                if c.obj.kind == "Bitmap" and c.obj.body.get("tex") in tids]
        if not mine:
            continue
        fits = {box_of(o) for o in mine}
        if len(fits) != 1 or len(mine) != len(n.components):
            n_left += 1
            continue
        fit = fits.pop()
        if n.id in own:
            box = (own_boxes or {}).get(n.id)
            w, h = mine[0].body["w"], mine[0].body["h"]
            nat = nat_of.get(mine[0].body.get("tex"))
            if not box and nat and w and h and tuple(nat) != (w, h):
                # its own size, from a texture written smaller for the screen
                k = nat[0] / float(w)
                fit = (k, 0.0, 0.0, k, 0.0, 0.0)
            elif not box or not (w and h) or (w, h) == tuple(box):
                continue
            else:
                fit = fit_box(w, h, box[0], box[1])
        elif fit is None:
            continue
        tracks = n.tracks or [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
        n.tracks = [(f, _m16_with(m, _composed(_m6_of16(m), fit))) for f, m in tracks]
        n_nodes += 1
    for o in sc.objects.values():
        bm = o.body.get("bitmap") if o.kind == "Shape" else None
        if bm is None or bm.body.get("tex") not in tids:
            continue
        left, top, right, bottom = o.body["rect"]
        a, _b, _c, d, tx, ty = fit_box(bm.body["w"], bm.body["h"], right - left, bottom - top)
        rect = [left + tx, top + ty, left + tx + a * bm.body["w"], top + ty + d * bm.body["h"]]
        if any(abs(x - y) > 0.01 for x, y in zip(rect, o.body["rect"])):
            o.body["rect"] = rect
            n_shapes += 1
    if not (n_nodes or n_shapes):
        return grown, 0, 0, n_left
    return scene_tree.serialize(sc), n_nodes, n_shapes, n_left


def grow(data, edits):
    """Return ``(new_bytes, occurrences, shift)`` for *data* with every
    display-text occurrence equal to a key of *edits* (``{old: new}``,
    str -> str) re-serialised as ``[u64 len(new)][new]`` -- the text-only
    form of :func:`regrow`.

    *occurrences* is ``{old: count}`` for the texts actually found; *shift*
    maps a STOCK file offset to its offset in the grown file (piecewise by
    insertion point)."""
    r = regrow(data, texts=edits)
    return r["data"], r["texts"], r["shift"]


def _layout_key(t, edits):
    return (t["name"], round(t["x"], 2), round(t["y"], 2),
            edits.get(t["text"], t["text"]),
            tuple(round(v, 2) for v in t["rect"]), t["align"],
            t.get("font_px"), t.get("outline", False))


def agree(old, new, edits, shift, images=None):
    """Compare every parser's view of *old* (stock) and *new* (grown with
    *edits*; *shift* from :func:`grow` / :func:`regrow`).  *images* is
    ``{stock data_off: (width, height)}`` for the images :func:`regrow`
    resized.  Returns ``(mismatches, stats)`` -- *mismatches* a list of
    strings, empty when the parsers agree that the grown file is the stock
    one shifted, with the edited texts substituted, the resized images at
    their new size, and nothing else different."""
    from . import radium, scene_layout as sl
    from .engine import parse_radium_images
    images = images or {}
    bad = []
    so, sn = radium.enumerate_strings(old), radium.enumerate_strings(new)
    if len(so) != len(sn):
        bad.append("enumerate_strings: %d vs %d strings" % (len(so), len(sn)))
    for a, b in zip(so, sn):
        want = (edits.get(a["text"], a["text"])
                if a["kind"] == "display-text" else a["text"])
        if (b["text"], b["kind"]) != (want, a["kind"]):
            bad.append("string %r/%s -> %r/%s"
                       % (a["text"], a["kind"], b["text"], b["kind"]))
            break
        if b["prefix_offset"] != shift(a["prefix_offset"]):
            bad.append("string %r prefix %#x expected %#x got %#x"
                       % (a["text"], a["prefix_offset"],
                          shift(a["prefix_offset"]), b["prefix_offset"]))
            break
    io, inn = parse_radium_images(old), parse_radium_images(new)

    def want_image(i):
        size = images.get(i["data_off"])
        if size is None:
            return (shift(i["data_off"]), i["length"], i["tex_w"], i["tex_h"],
                    i["fmt"])
        w, h = size
        return (shift(i["data_off"]), image_block_len(w, h, i["fmt"]), w, h,
                i["fmt"])
    if ([want_image(i) for i in io]
            != [(i["data_off"], i["length"], i["tex_w"], i["tex_h"], i["fmt"])
                for i in inn]):
        bad.append("parse_radium_images differs (%d vs %d)"
                   % (len(io), len(inn)))
    to = radium.parse_glyph_tables(old, io)
    tn = radium.parse_glyph_tables(new, inn)
    if ([(t["name"], shift(t["table_off"]), shift(t["table_end"]),
          len(t["glyphs"]),
          [(g["char"], g["rect"], g["metrics"]) for g in t["glyphs"]])
         for t in to]
            != [(t["name"], t["table_off"], t["table_end"], len(t["glyphs"]),
                 [(g["char"], g["rect"], g["metrics"]) for g in t["glyphs"]])
                for t in tn]):
        bad.append("parse_glyph_tables differs (%d vs %d)" % (len(to), len(tn)))
    lo = sl.parse_scene_layout(old, io, to)
    ln = sl.parse_scene_layout(new, inn, tn)
    if (lo is None) != (ln is None):
        bad.append("parse_scene_layout: one side None")
    elif lo is not None:
        for k in ("stage", "origin", "states", "groups", "scroll", "unplaced",
                  "offstage", "alternates", "partial"):
            if lo.get(k) != ln.get(k):
                bad.append("layout[%s]: %r vs %r" % (k, lo.get(k), ln.get(k)))
        ko = [_layout_key(t, edits) for t in lo["texts"]]
        kn = [_layout_key(t, {}) for t in ln["texts"]]
        if ko != kn:
            bad.append("layout texts differ: %d vs %d; first diff %s"
                       % (len(ko), len(kn),
                          next(((a, b) for a, b in zip(ko, kn) if a != b),
                               None)))
        for t_o, t_n in zip(lo["texts"], ln["texts"]):
            if shift(t_o["node"]) != t_n["node"] or (
                    t_o.get("font_atlas_off") is not None
                    and shift(t_o["font_atlas_off"]) != t_n.get("font_atlas_off")):
                bad.append("layout text node/atlas offsets not a pure shift: "
                           "%r" % t_o["text"])
                break
        # A resized sprite keeps its anchor in the file, but the parser's
        # centring guess (``_refine_sprite_pivots``) is geometric, so a
        # banner that grew past the stage edge may legitimately be re-read
        # from its centre; its position is not compared.
        grown_new = {shift(o) for o in images}

        def pos(s, off):
            if off in grown_new:
                return None, None
            return round(s["x"], 2), round(s["y"], 2)
        so_ = [(s["name"],) + pos(s, shift(s["image_off"]))
               + (shift(s["image_off"]),
                  tuple(shift(f) for f in s.get("frames") or ()))
               for s in lo["sprites"]]
        sn_ = [(s["name"],) + pos(s, s["image_off"])
               + (s["image_off"], tuple(s.get("frames") or ()))
               for s in ln["sprites"]]
        if so_ != sn_:
            bad.append("layout sprites differ: %d vs %d" % (len(so_), len(sn_)))
    co = sl.text_color_offsets(old, io, to)
    cn = sl.text_color_offsets(new, inn, tn)
    co2 = {edits.get(k, k): [(shift(o), c) for o, c in v] for k, v in co.items()}
    if co2 != cn:
        bad.append("text_color_offsets differ: %d vs %d texts"
                   % (len(co2), len(cn)))
    yo = sl.text_layout_offsets(old, io, to)
    yn = sl.text_layout_offsets(new, inn, tn)

    def norm(v, sh):
        return [(sh(k["off"]), sh(k["rect_off"]), k["rect"], sh(k["align_off"]),
                 k["align"], sh(k["spacing_off"]), k["spacing"], k["font_name"],
                 (k["table"] or {}).get("name")) for k in v]
    yo2 = {edits.get(k, k): norm(v, shift) for k, v in yo.items()}
    yn2 = {k: norm(v, lambda x: x) for k, v in yn.items()}
    if yo2 != yn2:
        bad.append("text_layout_offsets differ: %d vs %d texts"
                   % (len(yo2), len(yn2)))
    stats = dict(strings=len(sn), images=len(inn), tables=len(tn),
                 glyphs=sum(len(t["glyphs"]) for t in tn),
                 layout_texts=len(ln["texts"]) if ln else None,
                 layout_sprites=len(ln["sprites"]) if ln else None,
                 color_texts=len(cn), layout_off_texts=len(yn))
    return bad, stats
