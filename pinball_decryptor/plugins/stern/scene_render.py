"""Composite a Spike 2 scene preview from an extract folder.

:mod:`scene_layout` reads a ``scene.radium`` into positions and strings at
extract time; this module turns one of those layouts into a picture, reading
the assets **as they currently sit in the project folder** — the atlas PNGs
and the per-character glyph slices.  That indirection is the point: replace an
image or import a desktop font and the preview redraws with YOUR version, so
the Scenes window answers "what will this look like on the machine?" and not
just "what did Stern ship?".

Deliberately a STATIC frame.  The keyframe timeline (animation) is not
decoded, so a scene that slides in is drawn in its resting position; see
``plans/spike2_scene_renderer_handoff.md``.

Fidelity notes, all learned from visual spot-checks against the machine's own
output:

* A text line's track ``y`` is its BASELINE, not the top of the ink, and the
  string is centered in the Text node's box (the instance ``x`` shifts it).
* Glyph ink is TINTED by the keyframe's RGBA — stock atlases are mostly white
  ink precisely so the scene can color them.
* BC1 atlases hold ink on opaque black and the machine adds it to the frame,
  so that ink is composited additively (:func:`fontrender.load_slice` already
  keys alpha off luminance for those, which is what makes this work).  Alpha
  (BC3) glyphs are laid OVER the frame instead — the outline fonts prove the
  machine does, since their black ink could never show additively.
* A title is drawn TWICE: an outline under-pass in a companion font, then the
  fill on top.  The layout keeps the pair (``outline``-tagged) and this module
  draws them in that order, so the border is finally inspectable here — over a
  light backdrop, exactly like any other black ink.

The machine draws on black, so black is the truthful backdrop and the default.
A preview is also something you *inspect*, though, and black ink on a black
frame is invisible in it exactly as it is on the machine — which is no help
when the thing you are checking IS the black border round a letter (a tester).
So the render tracks COVERAGE as it composites and lays the finished frame over
a backdrop of the caller's choosing; over black the result is byte-identical to
drawing straight onto black, and over anything else the black bits finally show.
"""

import json
import os

SCENE_LAYOUT_MANIFEST = os.path.join("images", "scene_textures",
                                     "scene_layout.json")

# Backdrops a preview may be laid over.  Black is what the machine does; the
# rest exist to make one kind of ink visible — light greys and white for black
# outlines, the checkerboard for both at once, magenta for "is this pixel drawn
# at all?".
BACKGROUNDS = (
    ("Black", (0, 0, 0)),
    ("Dark grey", (46, 46, 52)),
    ("Mid grey", (128, 128, 128)),
    ("White", (255, 255, 255)),
    ("Checkerboard", "checker"),
    ("Magenta", (255, 0, 255)),
)
BACKGROUND_NAMES = tuple(name for name, _spec in BACKGROUNDS)
_CHECKER = ((104, 104, 110), (150, 150, 156), 16)   # dark, light, square px


def load_layouts(assets_dir):
    """``{radium card path: layout}`` recorded by the last extract, or ``{}``
    when this project has none (a pre-layout extract, or a non-Stern one)."""
    path = os.path.join(assets_dir, SCENE_LAYOUT_MANIFEST)
    try:
        with open(path, "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def text_tints(layouts):
    """``{font key: {(r, g, b) 0-255: how many lines}}`` over every layout.

    What a font actually LOOKS like on the machine is its ink multiplied by the
    colour the scene draws it in, and the stock ink is white precisely so the
    scene can decide.  Importing a green font therefore produces green only
    where the scene tints white — and nothing at all where it tints black.
    That is invisible from the glyph files, so the Fonts window says it."""
    out = {}
    for lay in (layouts or {}).values():
        for tx in (lay or {}).get("texts") or ():
            key = tx.get("font") or ""
            if not key:
                continue
            rgba = tx.get("rgba") or (1, 1, 1, 1)
            try:
                rgb = tuple(max(0, min(255, int(round(float(c) * 255.0))))
                            for c in tuple(rgba)[:3])
            except (TypeError, ValueError):
                continue
            per = out.setdefault(key, {})
            per[rgb] = per.get(rgb, 0) + 1
    return out


def describe(layout, state=0, group=None):
    """One human line about what a preview will show, including what it can't
    (so a static frame is never mistaken for the whole truth)."""
    return " ".join(_describe_parts(layout, state, group))


def caption_lead(layout, state=0, group=None):
    """The ONE sentence of :func:`describe` worth putting on screen when only
    one fits.

    Normally that is the first: what the preview IS.  Nearly every real scene
    has an undecoded corner, so leading with the caveat every time it exists
    fires on essentially every scene, and trades a useful summary ("Animation:
    20 frames ... at 30 fps") for a triviality ("1 more image can't be placed
    yet") — measured at 182 of 182 scenes on a godzilla_pro card.

    IT LEADS WITH THE ADMISSION ONLY WHEN THE PREVIEW IS SHOWING LESS OF THE
    SCENE THAN IT IS LEAVING OUT, which is self-relative rather than a
    threshold picked to fit one card.  PAD-81: a tester sent in Venom 1.07's
    7f71ddb3 as a scene that "fails to render".  It draws 200 images and
    cannot place 309, so what is on the canvas is a composite of a minority of
    the scene — and the visible line said "Still picture: 200 images on a
    1360x768 stage." while both the "309 can't be placed" and the "327
    separate screens, pick one from Screen" sentences sat behind the "?".  At
    that ratio the summary is the misleading half.

    Built from the same parts as :func:`describe` so the two cannot drift.
    """
    parts = _describe_parts(layout, state, group)
    if len(parts) > 1 and _mostly_missing(layout, state, group):
        return parts[1]
    return parts[0]


def _mostly_missing(layout, state=0, group=None):
    """Is more of this scene's art left out of the preview than is in it?

    Counted in IMAGES, the same unit ``unplaced`` is counted in — mixing in
    text lines would let a wordy scene tip the balance without a single piece
    of art being missing."""
    if not layout:
        return False
    drawn = len(_pick(layout.get("sprites") or (), state, group))
    return int(layout.get("unplaced") or 0) > drawn


def _describe_parts(layout, state=0, group=None):
    """:func:`describe`'s sentences, in reading order: what the preview shows
    first, then everything it has to admit."""
    if not layout:
        return ["No preview for this scene."]
    n_states = state_count(layout)
    names = group_names(layout)
    # An outline pass is the same line twice; counting it said "2 text lines"
    # where the user sees one.
    texts = [t for t in _pick(layout.get("texts") or (), state, group)
             if not t.get("outline")]
    sprites = _pick(layout.get("sprites") or (), state, group)
    n_t = len(texts)
    n_s = len(sprites)
    bits = []
    if n_s:
        bits.append("%d image%s" % (n_s, "" if n_s == 1 else "s"))
    if n_t:
        bits.append("%d text line%s" % (n_t, "" if n_t == 1 else "s"))
    what = " and ".join(bits) or "nothing drawable"
    w, h, _fps = (list(layout.get("stage") or (0, 0, 0)) + [0, 0, 0])[:3]
    stage = " on a %dx%d stage" % (w, h) if w and h else ""
    n_frames = frame_count(layout, state, group)
    if group is not None and 0 <= group < len(names):
        where = " Showing the screen \"%s\" on its own." % names[group]
    else:
        where = ""
    if n_frames > 1:
        head = ("Animation: %d frames of %s%s at the scene's own %g fps, each "
                "frame held for one tick (per-frame holds aren't decoded).%s"
                % (n_frames, what, stage, frame_rate(layout), where))
    else:
        # Only claim animation is missing when the scene HAS any: saying
        # "animation isn't shown" on a still picture implied there was
        # something to play.
        head = "Still picture: %s%s.%s" % (what, stage, where)
    parts = [head.strip()]
    # Say WHAT is missing, not merely that something is: nearly every real
    # scene has an undecoded corner, so a bare "partial" told the user nothing.
    n_un = int(layout.get("unplaced") or 0)
    n_off = int(layout.get("offstage") or 0)
    if n_un:
        parts.append("%d more image%s in this scene can't be placed yet."
                     % (n_un, "" if n_un == 1 else "s"))
    scroll = layout.get("scroll") or ""
    if scroll and n_off:
        # A credits roll is taller than the screen ON PURPOSE.  Calling its
        # off-stage lines undecoded said the preview was broken when it was
        # right — Led Zeppelin's credits span 23 screens of it.
        parts.append("This scene is a %s strip that scrolls through the "
                     "screen, so %d of its elements sit outside the frame by "
                     "design — the preview is one screenful of it, not the "
                     "whole strip."
                     % ("tall" if scroll == "vertical" else "wide", n_off))
    elif n_off:
        parts.append("%s off the stage, so %s position isn't fully decoded."
                     % ("1 element sits" if n_off == 1
                        else "%d elements sit" % n_off,
                        "its" if n_off == 1 else "their"))
    n_alt = int(layout.get("alternates") or 0)
    if group is None and len(names) > 1:
        parts.append("This scene holds %d separate screens the machine shows "
                     "one at a time, drawn here together — pick one from "
                     "Screen to see it by itself." % len(names))
    elif group is None and n_alt:
        # No named screens to offer (the node tree didn't decode for this one),
        # so the repeats still have to be admitted rather than silently pruned.
        parts.append("%d repeat%s of this content sit on top of each other — "
                     "alternative states the machine shows one at a time — so "
                     "only one of each is drawn."
                     % (n_alt, "" if n_alt == 1 else "s"))
    return parts


def _tint(img, rgba):
    """Multiply ink by the keyframe color (stock ink is white to allow this).
    Returns *img* unchanged when the color is white or unusable."""
    try:
        import numpy as np
    except Exception:
        return img
    try:
        r, g, b = (float(c) for c in rgba[:3])
    except (TypeError, ValueError):
        return img
    if min(r, g, b) >= 0.999:
        return img
    r, g, b = (max(0.0, min(1.0, c)) for c in (r, g, b))
    from PIL import Image
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    arr[..., 0] *= r
    arr[..., 1] *= g
    arr[..., 2] *= b
    return Image.fromarray(arr.clip(0, 255).astype("uint8"), "RGBA")


def _add(canvas, img, x, y, over=False):
    """Composite *img* onto *canvas*, clipped to the canvas.

    Two blends, matching the machine's own: additive (the default — its blend
    for BC1 ink-on-black art) and, with *over*, ordinary src-over for alpha
    art.  Over is what the outline fonts prove the machine does with BC3
    glyphs: their ink is BLACK, and an additive black is invisible, yet the
    borders show on screen — so those must be laid over the frame, not added
    to it.  The canvas RGB is premultiplied by coverage, which makes the over
    blend the plain ``src*a + dst*(1-a)``.

    The alpha channel is not part of either blend — it accumulates COVERAGE,
    so :func:`_over_background` can tell "nothing was drawn here" from "black
    was drawn here".  Those are the same pixel on the machine and had to
    become different ones here, or a black outline could never be looked at."""
    import numpy as np
    ch, cw = canvas.shape[:2]
    a = np.asarray(img.convert("RGBA"))
    ih, iw = a.shape[:2]
    x0, y0 = int(round(x)), int(round(y))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    w = min(iw - sx0, cw - dx0)
    h = min(ih - sy0, ch - dy0)
    if w <= 0 or h <= 0:
        return
    src = a[sy0:sy0 + h, sx0:sx0 + w].astype(np.float32)
    dst = canvas[dy0:dy0 + h, dx0:dx0 + w].astype(np.float32)
    alpha = (src[..., 3:4] / 255.0)
    if over:
        out = src[..., :3] * alpha + dst[..., :3] * (1.0 - alpha)
    else:
        out = dst[..., :3] + src[..., :3] * alpha
    canvas[dy0:dy0 + h, dx0:dx0 + w, :3] = out.clip(0, 255).astype("uint8")
    cov = alpha + (dst[..., 3:4] / 255.0) * (1.0 - alpha)
    canvas[dy0:dy0 + h, dx0:dx0 + w, 3:] = (
        cov * 255.0).round().clip(0, 255).astype("uint8")


def background_spec(name):
    """The backdrop *name* asks for, defaulting to the machine's black."""
    for nm, spec in BACKGROUNDS:
        if nm == name:
            return spec
    return BACKGROUNDS[0][1]


def _background_plane(w, h, spec):
    """An ``(h, w, 3)`` float array of the chosen backdrop."""
    import numpy as np
    if spec == "checker":
        dark, light, sq = _CHECKER
        yy, xx = np.mgrid[0:h, 0:w]
        mask = (((yy // sq) + (xx // sq)) % 2).astype(bool)
        plane = np.empty((h, w, 3), np.float32)
        plane[...] = np.asarray(dark, np.float32)
        plane[mask] = np.asarray(light, np.float32)
        return plane
    return np.broadcast_to(
        np.asarray(spec, np.float32), (h, w, 3))


def flatten_over_background(img, name):
    """Lay a straight-alpha RGBA image over the named backdrop -> RGB.

    For pictures that are already alpha-composited (a rendered line of text in
    the Fonts window) rather than additively accumulated — those go through
    ``_over_background`` instead."""
    from PIL import Image
    spec = background_spec(name)
    w, h = img.size
    if spec == "checker":
        back = Image.fromarray(
            _background_plane(w, h, spec).astype("uint8"), "RGB").convert(
                "RGBA")
    else:
        back = Image.new("RGBA", (w, h), tuple(spec) + (255,))
    return Image.alpha_composite(back, img.convert("RGBA")).convert("RGB")


def _over_background(canvas, spec):
    """Lay the accumulated frame over *spec* and return an RGB ``PIL.Image``.

    The accumulated RGB is already premultiplied by the ink's own alpha (``_add``
    adds ``src * a``), so the composite is the ordinary ``src + bg * (1 - a)``.
    Over black that is ``src`` unchanged — the default preview is exactly the
    frame this module has always produced."""
    import numpy as np
    from PIL import Image
    h, w = canvas.shape[:2]
    if spec == (0, 0, 0):
        return Image.fromarray(canvas, "RGBA").convert("RGB")
    cov = canvas[..., 3:4].astype(np.float32) / 255.0
    out = canvas[..., :3].astype(np.float32) + \
        _background_plane(w, h, spec) * (1.0 - cov)
    return Image.fromarray(out.clip(0, 255).astype("uint8"), "RGB")


def state_count(layout):
    """How many alternative STATES this scene holds (1 = a single picture).

    A slot is one place on the stage the machine redraws with different
    content — a page carousel, a mode's instruction pages, a co-op variant of a
    score panel.  Compositing them all is an unreadable pile, so the preview
    shows one at a time."""
    if not layout:
        return 1
    try:
        return max(1, int(layout.get("states") or 1))
    except (TypeError, ValueError):
        return 1


def group_names(layout):
    """The scene's own named screens, or ``[]``.

    A mode's radium holds every screen that mode can show and the machine picks
    one; the node tree separates them exactly, so these are the scene's
    structure rather than a guess about it."""
    if not layout:
        return []
    got = layout.get("groups") or []
    return list(got) if isinstance(got, (list, tuple)) else []


def _in_group(elements, group):
    """Every element of one named screen, pruning included — isolating a screen
    should show all of it, not the subset that survived being composited with
    the others."""
    return [el for el in elements if el.get("group") == group]


def _visible(elements, state):
    """The elements of *elements* that belong to state *state*.

    Anything with no slot is part of every state (the backdrop a carousel sits
    on).  A slot shallower than *state* shows its LAST state rather than
    vanishing, so stepping never blanks part of the picture."""
    depth = {}
    for el in elements:
        sid = el.get("slot")
        if sid is not None:
            depth[sid] = max(depth.get(sid, 0), int(el.get("state", 0)) + 1)
    out = []
    for el in elements:
        sid = el.get("slot")
        if sid is None:
            out.append(el)
            continue
        want = min(state, depth.get(sid, 1) - 1)
        if int(el.get("state", 0)) == want:
            out.append(el)
    return out


def frame_count(layout, state=0, group=None):
    """How many frames this scene animates over (1 = a still).  Elements with
    different frame counts loop independently; the scene's cycle is the
    longest.

    Counted over the elements VISIBLE in *state*, so a still state is reported
    as still even when a different state of the same scene animates — the
    window keys its playback controls off this."""
    if not layout:
        return 1
    return max([1] + [len(sp.get("frames") or ()) for sp in
                      _pick(layout.get("sprites") or (), state, group)])


def frame_rate(layout, cap=60.0):
    """Frames per second to play a preview at.

    The stage header carries the scene's OWN rate as an f32 and it is really
    authored per scene, not a constant — across one corpus of TMNT and Munsters
    radiums it reads 12, 24, 30 and 60 — so it is the rate to play at, not a
    starting guess.  It used to be capped at 20 out of caution about the
    undecoded per-frame timeline; that made every 30 fps scene play at two
    thirds speed and every 60 fps one at a third (David: "this animation is
    running slow").  What is still undecoded is whether individual frames HOLD
    for more than one tick, which can only make playback too fast, never too
    slow — and the window offers a manual speed anyway."""
    try:
        fps = float((layout or {}).get("stage", (0, 0, 0))[2])
    except (TypeError, ValueError, IndexError):
        fps = 0.0
    if not (1.0 <= fps <= 240.0):
        fps = 12.0
    return min(fps, cap)


def _pick(elements, state, group):
    """The elements to draw: one named screen, or the composited default."""
    if group is None:
        return _visible(elements, state)
    return _in_group(elements, group)


def render_layout(assets_dir, layout, fonts=None, frame=0, background=None,
                  colors=None, state=0, group=None):
    """Composite *layout* into an RGB ``PIL.Image``, or ``None`` if nothing
    could be drawn.  Pass *fonts* (``fontrender.load_fonts`` output) to render
    many scenes without re-reading the glyph manifest each time, and *frame* to
    pick which frame animated elements show.

    *background* names one of :data:`BACKGROUNDS` (default black, the machine's
    own).  *colors* is ``{display string: (r, g, b)}`` of pending text-colour
    edits, so the preview shows a colour the user has picked but not built yet.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    if not layout:
        return None
    try:
        w, h, _fps = layout["stage"]
        w, h = int(w), int(h)
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < w <= 8192 and 0 < h <= 8192):
        return None
    from . import fontrender as fr
    # Alpha starts EMPTY: it is coverage, not opacity (see ``_add``).
    canvas = np.zeros((h, w, 4), np.uint8)
    drew = False

    # Art first, then text over it (a scene's text is an overlay; true z-order
    # lives in the undecoded node tree).
    for sp in _pick(layout.get("sprites") or (), state, group):
        seq = sp.get("frames") or ()
        # An animated element draws ONE frame, never the whole stack.
        rel = seq[frame % len(seq)] if seq else sp.get("image")
        if not rel:
            continue
        path = os.path.join(assets_dir, "images", *rel.split("/"))
        try:
            img = Image.open(path).convert("RGBA")
        except (OSError, ValueError):
            continue
        _add(canvas, img, sp.get("x", 0), sp.get("y", 0))
        drew = True

    texts = _pick(layout.get("texts") or (), state, group)
    if texts:
        if fonts is None:
            try:
                fonts = fr.load_fonts(assets_dir)
            except Exception:
                fonts = []
        by_key = {f["key"]: f for f in fonts}
        for tx in texts:
            font = by_key.get(tx.get("font") or "")
            if font is None and len(fonts) == 1:
                font = fonts[0]          # single-font scene, key drifted
            if font is None or not tx.get("text"):
                continue
            # The same atlas is drawn at several sizes; this scene named the
            # one it uses.  Without this the preview drew every scene on the
            # card at whichever size the extract happened to keep first.
            font = fr.font_at_size(font, tx.get("font_px") or 0)
            try:
                ink, _missing = fr.render_text(font, tx["text"])
            except Exception:
                continue
            rgba = list(tx.get("rgba") or (1, 1, 1, 1))
            # A colour the user picked but hasn't built yet: the scene's own
            # alpha is kept, because that is what fades the line in.  An
            # OUTLINE line shares the fill's display string and must not take
            # its colour — repainting it is how a border silently disappears
            # (the Write path guards the same way, by the current rgba).
            pick = (colors or {}).get(tx.get("text"))
            if pick and not tx.get("outline"):
                rgba = [c / 255.0 for c in pick[:3]] + [
                    rgba[3] if len(rgba) > 3 else 1.0]
            ink = _tint(ink, rgba)
            rect = list(tx.get("rect") or (0, 0, w, h)) + [0, 0, 0, 0]
            # The keyframe's rect is LEFT, TOP, RIGHT, BOTTOM — not x/y/w/h.
            # Reading it as a width put the box in the wrong place: as edges,
            # two independent scenes (CLOCK and a 199px "LINE 1" screen) centre
            # their text on exactly 680.00 of a 1360-wide stage, where the
            # width reading gives 679 and 694.3.
            left = rect[0] + tx.get("x", 0)
            right = rect[2] + tx.get("x", 0)
            # The align word picks the edge: 0 left, 1 centre, 2 right — read
            # off the boot screen, where "U.S.A." is 0 and sits left while
            # "V0.01" is 2 and sits right, cross-checked against CLOCK being 1
            # and verified centred.  Centring everything mis-placed the rest.
            align = tx.get("align", 1)
            if align == 0:
                x = left
            elif align == 2:
                x = right - ink.size[0]
            else:
                x = left + (right - left - ink.size[0]) / 2.0
            # the track y is the baseline, so lift by the font's ascent
            y = tx.get("y", 0) - font.get("ascent", 0)
            # BC1 ink adds (black draws nothing, as on the machine); alpha
            # glyphs lay OVER the frame — the outline pass under a title is
            # black and would otherwise vanish into whatever it covers.
            _add(canvas, ink, x, y, over=(fr.font_fmt(font) != 4))
            drew = True
    if not drew:
        return None
    return _over_background(canvas, background_spec(background))


def render_scene(assets_dir, card_path, fonts=None, layouts=None,
                 background=None, colors=None, state=0):
    """Preview for one scene by its ``scene.radium`` card path, or ``None``."""
    if layouts is None:
        layouts = load_layouts(assets_dir)
    return render_layout(assets_dir, layouts.get(card_path), fonts=fonts,
                         background=background, colors=colors, state=state)


def layout_for_scene_dir(layouts, scene_dir):
    """The layout whose radium lives in *scene_dir* (the Scenes window groups
    by directory, the manifest is keyed by the radium's full path)."""
    want = (scene_dir or "").replace("\\", "/").rstrip("/")
    for card, lay in layouts.items():
        if card.replace("\\", "/").rsplit("/", 1)[0] == want:
            return card, lay
    return None, None
