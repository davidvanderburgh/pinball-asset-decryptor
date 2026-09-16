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


def image_refs(data, data_off, images=None):
    """File offsets of every sprite-instance triple that draws the image at
    *data_off* (``[dispW][dispH][handle & 0xFFFFFF]``, or the texture size in
    the dims' place, both of which ``scene_layout`` accepts).  Matches inside
    any image's own block data are not references and are left out;
    *images* is ``engine.parse_radium_images(data)`` when the caller already
    has it."""
    if images is None:
        from .engine import parse_radium_images
        images = parse_radium_images(data)
    rec = image_record(data, data_off)
    blocks = [(im["data_off"], im["data_off"] + im["length"]) for im in images]
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
        for off, (w, h, payload) in sorted(images.items()):
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
