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

:func:`grow` is the re-serialiser; :func:`agree` compares every repo
parser's view of the stock and grown files (offsets passed through the
shift) and is what the tests pin.  The engine composes a scene's other
in-place edits (colours, layout, embedded images -- all at stock offsets)
into the stock bytes BEFORE growing, so their offsets stay valid.
"""

import struct


def grow(data, edits):
    """Return ``(new_bytes, occurrences, shift)`` for *data* with every
    display-text occurrence equal to a key of *edits* (``{old: new}``,
    str -> str) re-serialised as ``[u64 len(new)][new]``.

    *occurrences* is ``{old: count}`` for the texts actually found; *shift*
    maps a STOCK file offset to its offset in the grown file (piecewise by
    insertion point).  Only the text bodies and their length words change;
    every other byte is copied.  Occurrences are the Text-node keyframes AND
    the instance keyframes -- the same set the in-place patch rewrites
    (``radium.display_texts``)."""
    from . import radium
    enc = {k.encode("latin1", "replace"): v.encode("latin1", "replace")
           for k, v in edits.items()}
    out = bytearray()
    pos = 0
    n = {}
    points = []                      # (stock offset after the string, delta)
    delta = 0
    for e in radium.display_texts(data):
        old = data[e["offset"]:e["offset"] + e["length"]]
        new = enc.get(old)
        if new is None:
            continue
        out += data[pos:e["prefix_offset"]]
        out += struct.pack("<Q", len(new)) + new
        pos = e["offset"] + e["length"]
        delta += len(new) - len(old)
        points.append((pos, delta))
        n[e["text"]] = n.get(e["text"], 0) + 1
    out += data[pos:]

    def shift(off):
        d = 0
        for p, cd in points:
            if off >= p:
                d = cd
            else:
                break
        return off + d
    return bytes(out), n, shift


def _layout_key(t, edits):
    return (t["name"], round(t["x"], 2), round(t["y"], 2),
            edits.get(t["text"], t["text"]),
            tuple(round(v, 2) for v in t["rect"]), t["align"],
            t.get("font_px"), t.get("outline", False))


def agree(old, new, edits, shift):
    """Compare every parser's view of *old* (stock) and *new* (grown with
    *edits*; *shift* from :func:`grow`).  Returns ``(mismatches, stats)`` --
    *mismatches* a list of strings, empty when the parsers agree that the
    grown file is the stock one shifted, with the edited texts substituted
    and nothing else different."""
    from . import radium, scene_layout as sl
    from .engine import parse_radium_images
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
    if ([(shift(i["data_off"]), i["length"], i["tex_w"], i["tex_h"], i["fmt"])
         for i in io]
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
        so_ = [(s["name"], round(s["x"], 2), round(s["y"], 2),
                shift(s["image_off"]),
                tuple(shift(f) for f in s.get("frames") or ()))
               for s in lo["sprites"]]
        sn_ = [(s["name"], round(s["x"], 2), round(s["y"], 2), s["image_off"],
                tuple(s.get("frames") or ())) for s in ln["sprites"]]
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
