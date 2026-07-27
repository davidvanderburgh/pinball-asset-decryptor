"""Read a Spike 2 ``scene.radium``'s node graph as a static LAYOUT.

The Scenes window could always say what a scene is made of; it could not show
what the scene LOOKS like.  Everything needed for that is in the file itself
(positions, boxes, colors, which string, which image) rather than in game
code, so a static frame is recoverable — reverse-engineered byte-exactly on
TMNT's "CLOCK NOT SET" screen and its sprite sibling, see the grammar in
``plans/spike2_scene_renderer_handoff.md``.

This module only PARSES, into plain numbers:

    {"stage": (w, h, fps),
     "texts":   [{"name", "x", "y", "text", "rect", "rgba", "align",
                  "font_atlas_off", "node"}],
     "sprites": [{"name", "x", "y", "image_off", "node"}],
     "partial": bool}

Positions come out ABSOLUTE.  In the file they are not: the graph is a tree of
nodes and a child's coordinates are measured from its parent, so the numbers
only mean something once :func:`_node_tree` has said who contains whom (that
tree also decides which repeats are alternative states, since a state is a
whole subtree).  When the tree doesn't decode exactly, every instance is read
as top-level instead — never guessed at.

Offsets (``font_atlas_off`` / ``image_off``) are raw ``data_off`` values of
inline image blocks, which the caller maps to the atlas PNGs the image
extract writes — that indirection is what lets the GUI composite a preview
from the user's CURRENT (possibly edited) PNGs instead of baking one at
extract time.

Design rules learned the hard way (see the handoff's gotchas):

* The stream is BYTE-aligned — an odd-length string shifts everything after
  it, so every structure is found by pattern scan, never by a fixed offset.
* ``f32 1.0`` is ``00 00 80 3f``, which looks exactly like a 0x80 node
  handle to a naive scan.  Regions already decoded as images or glyph tables
  are skipped, and every candidate must pass a full structural walk.
* Nothing here raises on malformed input: a scene we can't read returns
  ``None`` (the caller shows no preview) and a scene we can only partly read
  sets ``partial``.  This runs over every radium on a card during extract,
  including 9 MB ones, so it must never abort an extract or take long.
"""

import bisect
import struct

# A property track's value quad is [f32 1.0][f32 0][f32 x][f32 y]; anchoring
# on the byte-exact 1.0/0.0 pair is what makes the position readable without
# knowing how many flag words precede it.
_TRACK_SIG = b"\x00\x00\x80\x3f\x00\x00\x00\x00"
_MAX_ELEMENTS = 512           # runaway guard on a misparse
_MAX_NAME = 64
_STAGE_MIN, _STAGE_MAX = 64, 8192
_FPS_MIN, _FPS_MAX = 1.0, 240.0


class _R:
    """Bounds-checked little-endian reader; every getter raises ValueError
    rather than struct.error/IndexError so callers catch one type."""

    def __init__(self, data, pos=0):
        self.d = data
        self.i = pos

    def _take(self, n):
        if self.i + n > len(self.d) or self.i < 0:
            raise ValueError("out of range")
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def u8(self):
        return self._take(1)[0]

    def u16(self):
        return struct.unpack("<H", self._take(2))[0]

    def u32(self):
        return struct.unpack("<I", self._take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self._take(8))[0]

    def f32(self):
        return struct.unpack("<f", self._take(4))[0]

    def f32s(self, k):
        return struct.unpack("<%df" % k, self._take(4 * k))

    def string(self, maxlen=4096):
        ln = self.u64()
        if ln > maxlen:
            raise ValueError("absurd string length")
        return self._take(ln).decode("latin1")

    def skip(self, n):
        self.i += n


def _sane_floats(vals, limit=1e5):
    return all(-limit < v < limit and v == v for v in vals)


def _clean_coord(v):
    """Denormal junk (``-2.9e-42`` and friends, seen where a coordinate was
    never written) is a zero, not a position."""
    return 0.0 if abs(v) < 1e-6 else float(v)


_MIN_FRAMES = 3           # below this, repeated art is not a sequence


def _fold_frame_sequences(sprites, images):
    """Collapse a run of instances that share a position and image size but
    each draw a DIFFERENT image into one animated element carrying ``frames``.

    That shape is an animation, not a pile of sprites: TMNT's Michelangelo
    jump is 42 images of 600x768 all anchored at one spot, and its TV-static
    loop is ~1900.  Compositing them together produced a smear (David); the
    honest still is frame one, and the preview plays them in file order —
    which is the same order the Images tab already calls play order."""
    dims = {im["data_off"]: (im["tex_w"], im["tex_h"]) for im in images or ()}
    groups, order = {}, []
    for s in sprites:
        key = (round(s["x"]), round(s["y"]), dims.get(s["image_off"]))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)
    out = []
    for key in order:
        g = groups[key]
        offs = [s["image_off"] for s in g]
        if len(g) >= _MIN_FRAMES and len(set(offs)) == len(offs):
            first = dict(g[0])
            # file order = play order (a frame's data offset is its sequence)
            first["frames"] = sorted(offs)
            first["image_off"] = first["frames"][0]
            out.append(first)
        else:
            out.extend(g)
    return out


def _image_dims(images):
    return {im["data_off"]: (im["tex_w"], im["tex_h"])
            for im in images or ()}


def _text_box(t):
    """A text element's box in stage coords.  The keyframe rect is LEFT, TOP,
    RIGHT, BOTTOM (see scene_render), offset by the instance's position."""
    r = list(t.get("rect") or (0, 0, 0, 0)) + [0, 0, 0, 0]
    return (r[0] + t["x"], r[1] + t["y"], r[2] + t["x"], r[3] + t["y"])


def _sprite_box(s, dims):
    w, h = dims.get(s.get("image_off"), (0, 0))
    return (s["x"], s["y"], s["x"] + w, s["y"] + h)


def _box_centre_on_stage(box, stage, dx=0.0, dy=0.0, inset=0.02):
    """Whether a box's centre sits meaningfully inside the stage.

    The small inset matters: a title box centred on x=0 is 99% off the left
    edge, so counting it as "on stage" left the high-score screen's titles piled
    at the edge instead of being re-read from the centre."""
    cx = (box[0] + box[2]) / 2.0 + dx
    cy = (box[1] + box[3]) / 2.0 + dy
    mx, my = stage[0] * inset, stage[1] * inset
    return mx <= cx <= stage[0] - mx and my <= cy <= stage[1] - my


def _refine_origins(texts, sprites, stage, dims):
    """Per-element origin fix, for scenes that MIX the two conventions.

    :func:`_resolve_origin` handles a scene that is wholly centre-relative, but
    real scenes nest elements under different parents: the high-score screen has
    rows at (680, 522) alongside titles at (-347.5, 5.4), and drawing the latter
    as read piled several copies of "TEAM PLAY HIGH SCORES" on top of each other
    at the left edge (David: "not legible").

    An element is re-read from the centre only when its BOX would fall off the
    stage as written and falls ON it when centred — a tighter test than the
    anchor alone, and one that can only ever move an element from outside the
    frame to inside it.  Returns how many were shifted."""
    cx, cy = stage[0] / 2.0, stage[1] / 2.0
    n = 0
    for el, box_of in ([(t, _text_box) for t in texts]
                       + [(s, lambda s_: _sprite_box(s_, dims))
                          for s in sprites]):
        box = box_of(el)
        if _box_centre_on_stage(box, stage):
            continue
        if _box_centre_on_stage(box, stage, cx, cy):
            el["x"] += cx
            el["y"] += cy
            n += 1
    return n


def _on_stage_fraction(box, stage):
    """How much of *box* is inside the stage, 0..1."""
    iw = min(box[2], stage[0]) - max(box[0], 0)
    ih = min(box[3], stage[1]) - max(box[1], 0)
    if iw <= 0 or ih <= 0:
        return 0.0
    area = (box[2] - box[0]) * (box[3] - box[1])
    return (iw * ih) / area if area > 0 else 0.0


def _refine_sprite_pivots(sprites, stage, dims, off_max=0.7, on_min=0.95):
    """Draw a sprite CENTRED on its anchor when top-left clearly doesn't work.

    Most art hangs off its anchor's top-left corner — 657 of TMNT's 712 placed
    sprites land fully on stage read that way, including the verified LAIR
    banner at (395,127), which is clipped if centred.  A handful do not: a
    1360x768 full-screen image anchored at (679.95, 383.9), i.e. exactly the
    stage centre, only makes sense centred.

    PROVEN NEGATIVE — there is no per-sprite pivot field to read: an instance
    CAN carry its box as ``[f32 L][f32 T][f32 R][f32 B]`` at body+133, but
    exactly 2 of those 712 instances do, so it is not the mechanism.  This is
    therefore geometric and deliberately one-way, the same shape as
    :func:`_refine_origins`: it only fires when the art is mostly OFF the stage
    as written and fully ON when centred, so it can never move a sprite that
    already works.  Returns how many were re-read."""
    n = 0
    for s in sprites:
        w, h = dims.get(s.get("image_off"), (0, 0))
        if not w or not h:
            continue
        x, y = s["x"], s["y"]
        if _on_stage_fraction((x, y, x + w, y + h), stage) > off_max:
            continue
        if _on_stage_fraction((x - w / 2.0, y - h / 2.0,
                               x + w / 2.0, y + h / 2.0), stage) < on_min:
            continue
        s["x"] = x - w / 2.0
        s["y"] = y - h / 2.0
        n += 1
    return n


_SCROLL_MIN_ELEMENTS = 6
_SCROLL_LONG = 1.5            # times the stage, along the scrolling axis
_SCROLL_ACROSS = 1.2          # times the stage, across it


def _scroll_axis(texts, sprites, stage):
    """``"vertical"``, ``"horizontal"`` or ``""`` — whether this scene is a
    long strip that MOVES THROUGH the screen rather than sitting on it.

    A credits roll is the clear case: Led Zeppelin's spans 17,684 px of y on a
    768-high stage (23 screens) inside one ``Credits_Instance``, and Godzilla's
    console artbox spans 3,509.  Their elements are off the stage because they
    are meant to be — the scene scrolls past — so counting them as "positions
    we couldn't decode" told the user the preview was broken when it was
    right.  Needs a real column (few elements can spread far by accident) and
    a span that stays narrow ACROSS the axis, which is what separates a scroll
    from a scene that is simply mis-placed."""
    els = list(texts) + list(sprites)
    if len(els) < _SCROLL_MIN_ELEMENTS:
        return ""
    xs = [e["x"] for e in els]
    ys = [e["y"] for e in els]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    w, h = float(stage[0]), float(stage[1])
    if dy >= h * _SCROLL_LONG and dx <= w * _SCROLL_ACROSS:
        return "vertical"
    if dx >= w * _SCROLL_LONG and dy <= h * _SCROLL_ACROSS:
        return "horizontal"
    return ""


def _drop_exact_duplicates(texts, sprites):
    """Remove elements that repeat the same content at the same spot.

    Scenes carry redundant copies (the high-score screen lists "GRAND CHAMPION"
    four times, twice at each of two positions), and drawing a string twice over
    itself only thickens and blurs it.

    The one KEPT is the LAST, because later means drawn on top.  That is not a
    detail: a Stern title is an outline instance followed by a fill instance at
    the same spot, and the outline is tinted pure black — keeping it rendered
    TMNT's AWARD popup as an empty frame (ink multiplied by black, composited
    additively, adds nothing).  Keeping the fill draws the popup."""
    def dedupe(els, key):
        last = {}
        for i, el in enumerate(els):
            last[key(el)] = i
        return [el for i, el in enumerate(els) if last[key(el)] == i]
    return (dedupe(texts, lambda t: (t["text"], round(t["x"], 1),
                                     round(t["y"], 1), t.get("font_atlas_off"))),
            dedupe(sprites, lambda s: (tuple(s.get("frames") or
                                             (s.get("image_off"),)),
                                       round(s["x"], 1), round(s["y"], 1))))


def _intersection(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    return (iw * ih) if (iw > 0 and ih > 0) else 0.0


def _overlap_fraction(a, b):
    """Intersection area as a fraction of the smaller box (0 when either is
    empty)."""
    inter = _intersection(a, b)
    if not inter:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    smaller = min(area_a, area_b)
    return inter / smaller if smaller > 0 else 0.0


def _iou(a, b):
    """Intersection over UNION — how nearly two boxes are the same box.

    Intersection-over-smaller can't tell "drawn in the same place" from
    "standing next to each other": five 280x336 letter sprites 160px apart
    each cover 55% of their neighbour, which read as alternative states and
    deleted every other letter of a word (TMNT's "APRIL" drew as "A R L").
    Over the union those neighbours score 0.38 while a page redrawn on top of
    another page scores near 1."""
    inter = _intersection(a, b)
    if not inter:
        return 0.0
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def _drop_overlapping_states(texts, sprites, dims, thresh=0.3):
    """Where the SAME content is drawn several times on top of itself, keep one.

    Those repeats are alternative STATES the machine shows one at a time, not
    layers it composites:

    * Leonardo's character-select holds two 42-frame sequences of the same
      turtle — a 600x768 standing pose and a full-screen jump-kick — and playing
      both double-exposed him (the other characters have one each).
    * The high-score screen is a carousel of pages (HS1..HS4 plus co-op
      variants) that repeats one 944x580 frame at seven overlapping positions
      and its title five times, which rendered as an unreadable pile.

    Only *heavily overlapping* repeats collapse, so genuinely repeated layout
    survives: the two columns of player initials and the separate score rows
    barely overlap and are all kept.  Returns ``(texts, sprites, dropped)``."""
    def prune(els, key, box_of):
        groups = {}
        for el in els:
            groups.setdefault(key(el), []).append(el)
        drop = set()
        for members in groups.values():
            if len(members) < 2:
                continue
            keep = []
            for el in members:
                box = box_of(el)
                if any(_overlap_fraction(box, box_of(k)) >= thresh
                       for k in keep):
                    drop.add(id(el))
                else:
                    keep.append(el)
        return [el for el in els if id(el) not in drop], len(drop)

    texts, n_t = prune(texts, lambda t: (t["text"], t.get("font_atlas_off")),
                       _text_box)
    # Animations are compared to EACH OTHER regardless of content: Leonardo's
    # two takes are entirely different images, so grouping them by content would
    # never have caught them.  Static art still groups by content, since two
    # different pictures overlapping are usually a real composition.
    anims = [s for s in sprites if len(s.get("frames") or ()) > 1]
    statics = [s for s in sprites if len(s.get("frames") or ()) <= 1]
    anims, n_a = prune(anims, lambda _s: "animation",
                       lambda s: _sprite_box(s, dims))
    statics, n_s = prune(
        statics, lambda s: tuple(s.get("frames") or (s.get("image_off"),)),
        lambda s: _sprite_box(s, dims))
    keep = {id(s) for s in anims} | {id(s) for s in statics}
    sprites = [s for s in sprites if id(s) in keep]
    return texts, sprites, n_t + n_a + n_s


def _subtree_roots(elements, parent_of):
    """``{element id: the top-level node it hangs off}`` — a scene's pages,
    panels and popups are whole subtrees, so that ancestor is the unit a state
    is kept or dropped in."""
    top = {}
    out = {}
    for el in elements:
        node = el.get("node")
        seen = 0
        root = node
        while root is not None and seen < _MAX_ELEMENTS:
            p = parent_of.get(root)
            if p is None:
                break
            root = p
            seen += 1
        out[id(el)] = top.setdefault(node, root)
    return out


def _drop_overlapping_subtrees(texts, sprites, parent_of, dims, thresh=0.3,
                               art_thresh=0.5):
    """Where two GROUPS sit on top of each other, keep one.

    The element-level rule in :func:`_drop_overlapping_states` only compares
    like with like, so it cannot see a page whose repeat says something
    different: TMNT's high-score screen draws a three-player team list and a
    co-op list over the same two panels, six lines each, and the machine shows
    one at a time.  As subtrees they overlap almost completely, while the two
    score ROWS inside one list are 207px apart and both survive — which is why
    this compares group extents and not single elements.

    Only groups of TWO OR MORE elements are compared, so a caption sitting on
    its own icon (single-element siblings, which is the whole award grid) can
    never be mistaken for an alternative page.

    ART-ONLY groups are judged on :func:`_iou` instead, because a sprite's box
    is a padded artwork slot: TMNT spells "APRIL" and "LAIR" out of 280x336
    letter images about 160px apart, so each letter covers 55% of its
    neighbour's BOX while sharing none of its ink, and every second letter was
    deleted as an alternative state.  Over the union those letters score 0.38
    while a page redrawn on top of another page still scores near 1.  A group
    holding TEXT keeps the stricter test — a text element's box IS its text,
    so trespassing on it really does mean drawing over it, and that is what
    collapses the repeated "INFORMATION" placeholders of a template screen."""
    if not parent_of:
        return texts, sprites, 0
    els = list(texts) + list(sprites)
    roots = _subtree_roots(els, parent_of)
    groups, order = {}, []
    for el in els:
        r = roots.get(id(el))
        if r not in groups:
            groups[r] = []
            order.append(r)
        groups[r].append(el)

    def box(el):
        return (_text_box(el) if "text" in el else _sprite_box(el, dims))

    kept = []                         # (bounding box, holds text?)
    drop = set()
    for r in order:
        members = groups[r]
        if len(members) < 2:
            continue                  # a lone element is not a page
        bs = [box(el) for el in members]
        bb = (min(b[0] for b in bs), min(b[1] for b in bs),
              max(b[2] for b in bs), max(b[3] for b in bs))
        texty = any("text" in el for el in members)
        covered = any(
            _overlap_fraction(bb, kb) >= thresh if (texty or ktexty)
            else _iou(bb, kb) >= art_thresh
            for kb, ktexty in kept)
        if covered:
            drop.update(id(el) for el in members)
        else:
            kept.append((bb, texty))
    if not drop:
        return texts, sprites, 0
    return ([t for t in texts if id(t) not in drop],
            [s for s in sprites if id(s) not in drop], len(drop))


def _resolve_origin(texts, sprites, stage):
    """Decide where this scene measures its coordinates FROM, shifting the
    elements in place, and return ``"topleft"`` or ``"center"``.

    Most scenes place elements from the stage's top-left corner, but a large
    family measures from its CENTRE, and those read as far-negative
    coordinates: TMNT's AWARD popup sits at (-172.5, -25) and a 199px "LINE 1"
    screen at (-678.6, -107.55), both of which land exactly where you'd expect
    once half the stage is added.

    The rule is deliberately conservative and monotone — it only reinterprets a
    scene that is BROKEN as read (not every element on stage) and only when
    centring fixes it COMPLETELY.  A scene that already places everything from
    the top-left is never touched, so the verified CLOCK and LAIR screens keep
    their positions.  Evidence: of 79 TMNT scenes that placed nothing at all
    under top-left, centring rescued 79 — every element, no partial wins,
    which is what makes it a real convention rather than a lucky nudge."""
    def count_on(dx, dy):
        n = 0
        for t in texts:
            if _text_on_stage(t["x"] + dx, t["y"] + dy, stage):
                n += 1
        for s in sprites:
            if _sprite_on_stage(s["x"] + dx, s["y"] + dy, stage):
                n += 1
        return n

    total = len(texts) + len(sprites)
    if not total or count_on(0.0, 0.0) == total:
        return "topleft"
    cx, cy = stage[0] / 2.0, stage[1] / 2.0
    if count_on(cx, cy) != total:
        return "topleft"              # neither reading works; don't guess
    for el in texts + sprites:
        el["x"] += cx
        el["y"] += cy
    return "center"


def _text_on_stage(x, y, stage):
    """A text anchor is its BASELINE and the ink sits ABOVE it, so a negative
    baseline means the whole line is off the top — nothing would show.  x is
    generous: it is an offset inside a box that may itself start off-screen."""
    w, h = stage[0], stage[1]
    return 0 < y <= h * 1.15 and -w <= x <= 2 * w


def _sprite_on_stage(x, y, stage):
    """A sprite anchor is its top-left and the art extends down-right, so a
    negative anchor can still be partly visible; only reject anchors a whole
    stage away."""
    w, h = stage[0], stage[1]
    return -h < y < h and -w < x < 2 * w


def _parse_keyframe(data, off):
    """One keyframe block -> ``(dict, end_offset)`` or ``None``.

    ``[HANDLE][u32 seq][u64 0][f32 rect x4][f32 rgba x4][u16 0][u32 align]
    [f32 spacing][u32][STR text][u8 2][24B pad]``  (validated byte-exactly on
    the CLOCK scene; the same block shape carries a sprite instance's link).
    """
    r = _R(data, off)
    try:
        handle = r.u32()
        if handle >> 24 != 0x80 or handle == 0x80000000:
            return None
        seq = r.u32()
        if r.u64() != 0:
            return None
        rect = r.f32s(4)
        rgba = r.f32s(4)
        if not _sane_floats(rect) or not _sane_floats(rgba, 1e3):
            return None
        r.u16()
        align = r.u32()
        spacing = r.f32()
        r.u32()
        text = r.string(1024)
        r.u8()
        r.skip(24)
    except (ValueError, UnicodeDecodeError):
        return None
    return ({"seq": seq, "rect": list(rect), "rgba": list(rgba),
             "align": align, "spacing": spacing, "text": text}, r.i)


def _find_stage(data, start):
    """Scan for the stage header ``[u64 0][u32 W][u32 H][f32 fps]`` and return
    ``((w, h, fps), offset_after)`` or ``None``.  Sizes and fps are range
    -gated because eight zero bytes are common filler."""
    i = data.find(b"\x00" * 8, start)
    while i >= 0:
        try:
            w, h = struct.unpack_from("<2I", data, i + 8)
            fps, = struct.unpack_from("<f", data, i + 16)
        except struct.error:
            return None
        if (_STAGE_MIN <= w <= _STAGE_MAX and _STAGE_MIN <= h <= _STAGE_MAX
                and _FPS_MIN <= fps <= _FPS_MAX):
            return (w, h, float(fps)), i + 20
        i = data.find(b"\x00" * 8, i + 1)
    return None


def _decoded_ranges(images, tables):
    """Byte ranges already understood as image data or glyph tables — skipped
    by every scan here (their floats mimic handles and strings)."""
    rng = []
    for im in images or ():
        rng.append((im["data_off"], im["data_off"] + im["length"]))
    for t in tables or ():
        end = t.get("table_end")
        if end:
            rng.append((t["table_off"], end))
    rng.sort()
    return rng


def _tail_start(images, tables):
    """Where the node graph can begin: past every decoded region."""
    end = 0
    for a, b in _decoded_ranges(images, tables):
        end = max(end, b)
    return end


def _is_instance_name(name):
    """Reject strings that are structure, not element names.  ``N.asset`` and
    ``N.asset/M.asset`` are the video/texture references a scene's asset
    tables are full of — treating them as instances turned one video-list
    scene into a dozen phantom sprites stacked at the same spot."""
    if name.endswith(".asset") or ".asset/" in name:
        return False
    return any(c.isalpha() for c in name)


def _find_names(data, start, stop):
    """``[(offset, name)]`` for identifier-ish strings in the node region —
    the instance names ("Line1", "LAIR") that anchor each element."""
    out = []
    j = start
    while j + 8 <= stop:
        try:
            ln, = struct.unpack_from("<Q", data, j)
        except struct.error:
            break
        if 1 <= ln <= _MAX_NAME and j + 8 + ln <= stop:
            b = data[j + 8:j + 8 + ln]
            if all(32 <= c < 127 for c in b):
                name = b.decode()
                if _is_instance_name(name):
                    out.append((j, name))
                    j += 8 + ln
                    continue
        j += 1
    return out


def _scan_nodes(data, start, stop):
    """``[(name offset, name)]`` for every NODE record in the graph.

    A node is introduced by ``[u32 child count][u32 0][u32 handle]
    [u64 name len][name]``: the count and the zero word are the tail of the
    PREVIOUS record, the handle is this node's.  Demanding all three is what
    separates real nodes from the keyframe strings :func:`_find_names`
    deliberately also picks up ("KME", "GRAND CHAMPION") — those carry no
    handle, so they can't be mistaken for children."""
    out = []
    j = start
    while j + 8 <= stop:
        try:
            ln, = struct.unpack_from("<Q", data, j)
        except struct.error:
            break
        if 1 <= ln <= _MAX_NAME and j + 8 + ln <= stop and j >= 12:
            b = data[j + 8:j + 8 + ln]
            if all(32 <= c < 127 for c in b):
                zero, handle = struct.unpack_from("<2I", data, j - 8)
                if (handle >> 24 == 0x80 and handle != 0x80000000
                        and zero == 0):
                    out.append((j, b.decode()))
                    j += 8 + ln
                    continue
        j += 1
    return out


def _node_tree(data, start, stop):
    """``([(offset, name)], {offset: parent offset or None})`` for the scene
    graph, or ``None`` when it does not decode exactly.

    Each record ENDS with ``[u32 child count][u32 0]`` immediately before the
    next record's handle, and children are serialized depth-first straight
    after their parent — so a node's child count is the word 12 bytes before
    the NEXT node's name, the root's is the word 12 bytes before the first
    (the same word that trails the stage header), and the counts alone rebuild
    the tree.

    This is what makes a child's coordinates mean anything: they are measured
    from its PARENT.  TMNT's two-page high-score scene declares 5 root
    children and 3/6/3/6 for its four score frames — exactly what its instance
    names say — and its second page's title at (50, 28.45) lands inside its own
    frame at (376.75, 411.45) instead of in the top-left corner.  The boot
    screen is the same bug vertically: "VERIFYING IMAGE" at y=7.6 is 7.6 below
    its progress bar at y=372.8, not 7.6 below the top of the screen.

    Returning ``None`` the moment a count doesn't add up is load-bearing: a
    hierarchy guessed from a misparse would move elements silently, so the
    caller falls back to reading every instance as top-level instead."""
    ns = _scan_nodes(data, start, stop)
    if not ns:
        return None
    try:
        counts = [struct.unpack_from("<I", data, ns[i + 1][0] - 12)[0]
                  for i in range(len(ns) - 1)] + [0]
        root = struct.unpack_from("<I", data, ns[0][0] - 12)[0]
    except struct.error:
        return None
    if root > len(ns):
        return None
    parent = {}
    stack = [[None, root]]        # [node offset, children still expected]
    for (off, _name), nkids in zip(ns, counts):
        while stack and stack[-1][1] == 0:
            stack.pop()
        if not stack or nkids > len(ns):
            return None           # more nodes than any parent claimed
        parent[off] = stack[-1][0]
        stack[-1][1] -= 1
        stack.append([off, nkids])
    while stack and stack[-1][1] == 0:
        stack.pop()
    if stack:
        return None               # a parent promised children it never got
    return ns, parent


def _compose_positions(order, local, parent_of):
    """Absolute position per node: a child's coordinates are its parent's plus
    its own, all the way up.  *order* is file order, which is depth-first, so
    a single forward pass always has the parent's answer already."""
    out = {}
    for off in order:
        x, y = local.get(off, (0.0, 0.0))
        px, py = out.get(parent_of.get(off), (0.0, 0.0))
        out[off] = (px + x, py + y)
    return out


def _drop_orphans(texts, sprites, parent_of, produced):
    """Remove elements whose ancestor was dropped.

    Pruning a repeated STATE has to take the state's whole subtree with it.
    The high-score screen's page 2 is a score frame plus six text lines
    positioned inside it; dropping the duplicate frame on its own left those
    six lines drawn against the top-left corner of the screen — the visible
    debris this whole decode exists to remove.  *produced* is every node that
    contributed an element before pruning, so a node that never drew anything
    (a plain group) is not mistaken for a dropped one."""
    if not parent_of:
        return texts, sprites, 0
    kept = {el.get("node") for el in texts}
    kept |= {el.get("node") for el in sprites}

    def alive(el):
        p = parent_of.get(el.get("node"))
        seen = 0
        while p is not None and seen < _MAX_ELEMENTS:
            if p in produced and p not in kept:
                return False
            p = parent_of.get(p)
            seen += 1
        return True

    t2 = [t for t in texts if alive(t)]
    s2 = [s for s in sprites if alive(s)]
    return t2, s2, (len(texts) - len(t2)) + (len(sprites) - len(s2))


def _instance_tracks(data, seg, limit):
    """Every property track in an instance's segment, as
    ``[(start, end, x, y)]`` in file order.

    Two things depend on having them all rather than just the last one:

    * A track's own bytes can be misread as a keyframe — ``f32 1.0`` is
      ``00 00 80 3f``, whose 0x80 looks like a node handle three bytes in — so
      the keyframe scan must exclude these ranges.  Requiring the keyframe to
      come after every track instead does NOT work: some instances carry more
      tracks after it, and that rule lost four of five text lines on the
      Munsters boot scene.
    * Those trailing tracks are not positions (they read as 1.0/0.0 scale-ish
      values), so the position is the last track BEFORE the keyframe, which is
      what :func:`_position_before` picks."""
    out = []
    j = seg
    while True:
        j = data.find(_TRACK_SIG, j, limit)
        if j < 0:
            return out
        try:
            vx, vy = struct.unpack_from("<2f", data, j + 8)
        except struct.error:
            return out
        if _sane_floats((vx, vy)):
            # the signature sits after the track's handle; the quad ends at +16
            out.append((j - 4, j + 16,
                        _clean_coord(vx), _clean_coord(vy)))
        j += 1


def _position_before(tracks, kf_at):
    """``(x, y, found_any)`` from the last track before the instance's
    keyframe (all of them when it has no keyframe, as sprites don't)."""
    usable = [t for t in tracks
              if kf_at is None or t[1] <= kf_at] or tracks
    if not usable:
        return 0.0, 0.0, False
    return usable[-1][2], usable[-1][3], True


def _find_keyframe_in(data, seg, seg_end, skip=()):
    """First plausible keyframe block start in ``[seg, seg_end)``, ignoring
    candidates that fall inside one of the *skip* byte ranges (an instance's
    property tracks — see :func:`_instance_tracks`)."""
    for j in range(seg, max(seg, seg_end - 60)):
        if data[j + 3] == 0x80 and data[j:j + 3] != b"\x00\x00\x00":
            if any(a <= j < b for a, b in skip):
                continue
            got = _parse_keyframe(data, j)
            if got is not None:
                return j, got[0]
    return None, None


def parse_scene_layout(data, images, tables=None):
    """Parse *data* into a static layout dict, or ``None`` when this radium
    isn't a drawable scene (video lists and texture catalogs aren't).

    *images* is :func:`engine.parse_radium_images` output and *tables* is
    :func:`radium.parse_glyph_tables` output for the same bytes — both are
    needed to skip decoded regions, and *tables* also identifies the font a
    text element draws with."""
    try:
        return _parse_scene_layout(data, images, tables)
    except Exception:
        # A preview is a nicety; never let a malformed scene fail an extract.
        return None


# Where the RGBA floats sit inside a keyframe block: handle (4) + seq (4) +
# the zero u64 (8) + the rect's four floats (16).  See ``_parse_keyframe``.
_KF_RGBA_AT = 32


def text_color_offsets(data, images, tables=None):
    """``{display string: [(file offset of the keyframe RGBA, rgba), ...]}``.

    The colour a line of text is drawn in lives in the scene, not the glyphs
    (the atlas is white ink precisely so the scene can tint it), so recolouring
    text means rewriting floats in the ``scene.radium``.  This finds them by
    exactly the scan :func:`parse_scene_layout` uses for the same blocks, so the
    offsets belong to the keyframes whose colours the Scenes window shows.

    One string can have SEVERAL keyframes and they are not interchangeable: on
    TMNT's AWARD popup "AWARD" has four, two of them the pure-black OUTLINE
    instance drawn under the coloured fill.  That is why the current rgba comes
    back with each offset — a recolour has to match the colour the user picked
    from, or it repaints the outline as well and the letters lose their border.

    Never raises: an unreadable scene yields ``{}`` and its colours are left
    alone."""
    out = {}
    try:
        start = _tail_start(images, tables)
        if start <= 0 or start >= len(data):
            return out
        found = _find_stage(data, start)
        if found is None:
            return out
        _stage, after_stage = found
        j, n = start, 0
        while j < after_stage and n < _MAX_ELEMENTS:
            got = _parse_keyframe(data, j)
            if got is None:
                j += 1
                continue
            kf, end = got
            if kf["text"]:
                out.setdefault(kf["text"], []).append(
                    (j + _KF_RGBA_AT, list(kf["rgba"])))
                n += 1
            j = end
    except Exception:
        return out
    return out


def _glyph_atlas_offs(tables):
    """Every inline image a glyph table draws from — i.e. the FONT ATLAS pages.

    These are not art and must never be treated as unplaced sprites: they are
    already on screen as the scene's text.  A text-heavy scene embeds one atlas
    page per size per font (eleven of them on TMNT's AWARD screen), and
    counting those as "images we couldn't place" reported a fully-rendered
    scene as mostly broken."""
    return {g["atlas"]["data_off"] for t in (tables or ())
            for g in t["glyphs"] if g.get("atlas") is not None}


def _font_names(tables):
    """The font names, which appear as strings in the node region and are NOT
    instances — reading them as such invented sprites that don't exist."""
    return {t["name"] for t in (tables or ()) if t.get("name")}


def _image_refs(data, images):
    """``{masked handle: (disp_w, disp_h, tex_w, tex_h, data_off)}`` for the
    scene's inline images.

    An image is introduced by a handle 28 bytes before its block data (the same
    anchor :func:`radium.parse_glyph_tables` resolves glyph atlases with), and
    later USERS refer to it by that handle with the 0x80 top byte stripped."""
    out = {}
    for im in images or ():
        hoff = im["data_off"] - 28
        if hoff < 0:
            continue
        try:
            h, = struct.unpack_from("<I", data, hoff)
        except struct.error:
            continue
        if h >> 24 == 0x80:
            out[h & 0xFFFFFF] = (im["disp_w"], im["disp_h"],
                                 im["tex_w"], im["tex_h"], im["data_off"])
    return out


def _instance_image(data, seg, seg_end, refs):
    """The image an instance draws, as its ``data_off``, or ``None``.

    A sprite instance carries ``[u32 dispW][u32 dispH][u32 image handle]`` —
    the same width/height/handle triple the image's own intro block holds.
    Handles are small sequential integers, so the handle alone is far too
    common to search for; requiring the two dimensions beside it to match that
    exact image is what makes this unambiguous.  (Derived by diffing two
    adjacent instances of TMNT's award grid, which differed only in position
    and this triple.)"""
    if not refs:
        return None
    # +12 <= seg_end, not < : the triple is often the instance's LAST field.
    for j in range(seg, max(seg, seg_end - 11)):
        try:
            w, h, hh = struct.unpack_from("<3I", data, j)
        except struct.error:
            return None
        got = refs.get(hh)
        if got and ((w, h) == (got[0], got[1]) or (w, h) == (got[2], got[3])):
            return got[4]
    return None


def _font_atlas_off(tables):
    """The atlas offset identifying the scene's text font.

    A text scene normally embeds exactly one font; when it holds several we
    take the one with the most drawable glyphs, which on every multi-font
    scene checked is the body font rather than an outline companion."""
    best, best_n = None, -1
    for t in tables or ():
        offs = [g["atlas"]["data_off"] for g in t["glyphs"]
                if g.get("atlas") is not None]
        if len(offs) > best_n:
            best, best_n = offs[0] if offs else None, len(offs)
    return best


def _parse_scene_layout(data, images, tables):
    start = _tail_start(images, tables)
    if start <= 0 or start >= len(data):
        return None
    found = _find_stage(data, start)
    if found is None:
        return None
    stage, after_stage = found

    # Text keyframes live in the Text node BEFORE the stage header; each holds
    # one display string keyed by a sequence id that an instance links to.
    keyframes = {}
    j = start
    while j < after_stage and len(keyframes) < _MAX_ELEMENTS:
        got = _parse_keyframe(data, j)
        if got is None:
            j += 1
            continue
        kf, end = got
        if kf["text"]:
            keyframes[kf["seq"]] = kf
        j = end

    # Instances (text lines and sprites) follow the stage header: a name
    # string, some flag words, property tracks, then the keyframe that links
    # the instance to its content.
    names = _find_names(data, after_stage, len(data))
    # The node TREE, when it decodes exactly: a child's coordinates are its
    # parent's plus its own, and a dropped state has to take its subtree with
    # it.  ``None`` = read every instance as top-level, which is what this
    # module did before membership was decoded.
    tree = _node_tree(data, after_stage, len(data))
    if tree is None:
        walk, parent_of = names, None
    else:
        walk, parent_of = tree
    # Segment boundaries stay the LOOSE scan's: a keyframe's own text string
    # bounds its instance, and widening that window would let an instance
    # adopt the next one's keyframe.
    bounds = [o for o, _n in names]
    font_off = _font_atlas_off(tables)
    # Art = the images that are NOT font atlas pages.  Splitting them is what
    # makes a text-heavy scene (eleven atlases plus one piece of art) place its
    # art instead of reporting twelve images it couldn't figure out.
    atlas_offs = _glyph_atlas_offs(tables)
    art = [im for im in images or () if im["data_off"] not in atlas_offs]
    single_image = art[0]["data_off"] if len(art) == 1 else None
    skip_names = _font_names(tables)
    # Each instance names its own image, so multi-art scenes resolve properly;
    # the single-art fallback covers instances that carry no such triple.
    art_offs = {im["data_off"] for im in art}
    refs = {h: v for h, v in _image_refs(data, images).items()
            if v[4] in art_offs}
    texts, sprites = [], []
    unplaced = 0                  # image instances we can't locate (see below)
    container = (0.0, 0.0)        # position the next (0,0) child inherits
    local = {}                    # node offset -> its OWN (x, y)
    order = []                    # node offsets in file (= depth-first) order
    parsed = []                   # [(noff, name, seg, seg_end, kf, has_track)]
    for gi, (noff, name) in enumerate(walk):
        seg = noff + 8 + len(name)
        bi = bisect.bisect_right(bounds, noff)
        seg_end = bounds[bi] if bi < len(bounds) else len(data)
        # Instance := name, flag words, property tracks, then (TEXT lines
        # only) a keyframe block carrying or linking its string.  A SPRITE
        # instance has no keyframe at all — its content is the image — so the
        # keyframe is looked for but not required, and only AFTER the tracks.
        tracks = _instance_tracks(data, seg, seg_end)
        kf_at, kf = _find_keyframe_in(
            data, seg, seg_end, skip=[(a, b) for a, b, _x, _y in tracks])
        x, y, has_track = _position_before(tracks, kf_at)
        # A group that draws nothing still carries the transform its children
        # are measured from, so EVERY node's position is recorded — only
        # element-building is skipped below.
        order.append(noff)
        local[noff] = (x, y)
        parsed.append((noff, name, seg, seg_end, kf, has_track, kf_at))
    place = (_compose_positions(order, local, parent_of)
             if parent_of is not None else None)
    has_children = ({p for p in (parent_of or {}).values() if p is not None}
                    if parent_of is not None else set())
    produced = set()              # nodes that contributed an element
    for noff, name, seg, seg_end, kf, has_track, kf_at in parsed:
        if len(texts) + len(sprites) >= _MAX_ELEMENTS:
            unplaced += 1
            break
        if name in skip_names:
            continue                      # a font name, not an instance
        if not has_track and kf_at is None:
            continue                      # not an instance, just a string
        x, y = place[noff] if place is not None else local[noff]
        linked = keyframes.get(kf["seq"]) if kf else None
        text = (linked or kf or {}).get("text", "")
        if text:
            produced.add(noff)
            texts.append({"name": name, "x": x, "y": y, "text": text,
                          "rect": (linked or kf)["rect"],
                          "rgba": (linked or kf)["rgba"],
                          "align": (linked or kf)["align"],
                          "font_atlas_off": font_off, "node": noff})
        elif has_track:
            # Sprite instance: it names its own image; failing that, a scene
            # with exactly one piece of art is unambiguous anyway.
            off = _instance_image(data, seg, seg_end, refs)
            if off is None and noff not in has_children:
                # ...but a node WITH CHILDREN is a group: it carries the
                # transform its children hang off, not art.  The high-score
                # screen's score frames drew the scene's only image — its
                # backdrop — a second time in the bottom-right corner until
                # the tree said they were containers.
                off = single_image
            if off is not None:
                sx, sy = x, y
                if place is None and (sx, sy) == (0.0, 0.0):
                    # Fallback when the node tree didn't decode: a child's
                    # position is relative to its container, and the container
                    # is the instance serialized before it (TMNT's TV scene
                    # puts ~1900 static frames at (0,0) inside
                    # TVStaticLooping_Instance at (533, 296.5)).  With the
                    # tree, _compose_positions has already done this properly.
                    sx, sy = container
                produced.add(noff)
                sprites.append({"name": name, "x": sx, "y": sy,
                                "image_off": off, "node": noff})
            elif art and noff not in has_children:
                # A group is not "an image we couldn't place" — saying so on
                # the caption reported four containers as missing art on the
                # high-score screen.
                unplaced += 1
        if place is None and has_track and local[noff] != (0.0, 0.0):
            # A positioned instance is the container for the (0,0) ones after
            # it, whether or not it draws anything itself.
            container = local[noff]
    # Repeated instances of one sprite with no position are animation-state
    # copies (the slide-in start, per the RE notes), not extra copies drawn on
    # top of each other: when any instance carries a real position, the
    # origin-pinned duplicates are dropped.  All-at-origin keeps just one.
    if len(sprites) > 1:
        placed = [s for s in sprites if (s["x"], s["y"]) != (0.0, 0.0)]
        sprites = placed or sprites[:1]
        # Same art at the same spot more than once is the same state-alternative
        # pattern: a carousel scene stacks dozens of instances on one another and
        # the machine reveals them over time.  Drawing the stack adds nothing but
        # a smear, so one of each (image, position) is kept.
        seen = set()
        unique = []
        for s in sprites:
            key = (s["image_off"], round(s["x"]), round(s["y"]))
            if key in seen:
                continue
            seen.add(key)
            unique.append(s)
        sprites = _fold_frame_sequences(unique, images)
    if not texts and not sprites:
        return None
    # Sanity gate.  Some scenes nest their elements under a group node whose
    # own transform is not decoded, so the positions we read are relative to
    # something we can't see and land off the stage.  Rendering those produced
    # a convincing all-black frame, which reads as "this scene is empty" —
    # worse than admitting we can't draw it.  Nothing on stage => no preview;
    # some off stage => partial.
    origin = _resolve_origin(texts, sprites, stage)
    dims = _image_dims(images)
    if origin == "topleft":
        # Only worth trying per element when the scene as a whole reads
        # top-left; a wholly centred scene is already resolved.
        if _refine_origins(texts, sprites, stage, dims):
            origin = "mixed"
    if _refine_sprite_pivots(sprites, stage, dims) and origin == "topleft":
        origin = "mixed"
    texts, sprites = _drop_exact_duplicates(texts, sprites)
    # Pages first, then what is left inside them: pruning elements first can
    # strip a page down to a couple of lines, and those no longer cover enough
    # of the page they duplicate to be recognised as its repeat.
    texts, sprites, pages = _drop_overlapping_subtrees(
        texts, sprites, parent_of, dims)
    texts, sprites, alternates = _drop_overlapping_states(texts, sprites, dims)
    # Whatever the pruning above dropped, its children go too — a state is a
    # subtree, and orphaning its contents is what left debris on the screen.
    texts, sprites, orphans = _drop_orphans(texts, sprites, parent_of, produced)
    alternates += pages + orphans
    on = off = 0
    for el, check in ([(t, _text_on_stage) for t in texts]
                      + [(s, _sprite_on_stage) for s in sprites]):
        if check(el["x"], el["y"], stage):
            on += 1
        else:
            off += 1
    if on == 0:
        return None
    return {"stage": stage, "origin": origin,
            "texts": texts, "sprites": sprites,
            # a long strip that moves THROUGH the screen (a credits roll), so
            # its off-stage elements are by design, not a decode failure
            "scroll": _scroll_axis(texts, sprites, stage),
            # Counted, not just flagged: on a real card almost every scene has
            # SOMETHING undecoded, so a bare "partial" was noise on 94% of
            # scenes.  The numbers say what is actually missing.
            "unplaced": unplaced, "offstage": off,
            # alternative animations of the same thing, deliberately not drawn
            "alternates": alternates,
            "partial": bool(unplaced or off or alternates)}
