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


def viewed(canvas, view):
    """*canvas* (uint8 RGBA, colour premultiplied by coverage, as the frame is
    accumulated) seen through *view* (``rgb -> rgb``, core.colour_profile
    ``machine_view``): the colour is taken straight, viewed, and multiplied
    back, so a soft edge keeps its edge (PAD-312).  *view* None: unchanged."""
    if view is None:
        return canvas
    import numpy as np
    a = canvas[..., 3:4].astype(np.float32)
    cov = np.maximum(a, 1.0)
    straight = np.clip(canvas[..., :3].astype(np.float32) * 255.0 / cov + 0.5,
                       0, 255).astype(np.uint8)
    shown = np.asarray(view(straight), np.float32)
    out = canvas.copy()
    out[..., :3] = np.clip(shown * a / 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


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


def _layout_edit(layout_edits, text):
    """The pending layout edit for display string *text* as
    ``(dx, dy, align code or None, metric scale)``, or ``None`` when the
    string has none (or the edit is neutral) — so the untouched path stays
    exactly the render it has always been."""
    if not layout_edits or not text:
        return None
    edit = layout_edits.get(text)
    if not edit:
        return None
    from . import text_layout as tl
    try:
        e = tl.normalize(edit)
    except Exception:
        return None
    if tl.is_neutral(e):
        return None
    align = tl.align_code(e["align"]) if e["align"] is not None else None
    scale = (e["size"] / 100.0) if e["size"] else 1.0
    return e["dx"], e["dy"], align, scale


def render_layout(assets_dir, layout, fonts=None, frame=0, background=None,
                  colors=None, state=0, group=None, layout_edits=None,
                  text_edits=None, view=None):
    """Composite *layout* into an RGB ``PIL.Image``, or ``None`` if nothing
    could be drawn.  Pass *fonts* (``fontrender.load_fonts`` output) to render
    many scenes without re-reading the glyph manifest each time, and *frame* to
    pick which frame animated elements show.

    *background* names one of :data:`BACKGROUNDS` (default black, the machine's
    own).  *colors* is ``{display string: (r, g, b)}`` of pending text-colour
    edits, so the preview shows a colour the user has picked but not built yet.
    *layout_edits* is ``{display string: edit}`` of pending text-LAYOUT edits
    (:mod:`text_layout` rows: ``dx``/``dy``/``align``/``size``) for this
    scene: a matching line is drawn shifted by ``dx, dy``, aligned as the edit
    says, with its glyph metrics scaled by ``size / 100`` — the same three
    things the Write path patches into the radium.  Unlike a colour, a layout
    edit applies to the OUTLINE pass too: the border has to move and grow
    with its fill or the pair comes apart.

    *text_edits* is ``{display string: replacement}`` of pending Replace Text
    edits that reach this scene (its own radium rows, and game-program rows
    whose original is a placeholder this scene draws): a line whose string is
    a key is drawn with the REPLACEMENT — same rect, alignment, font, size,
    colour and outline pair, only the letters change.  A longer replacement
    simply runs on inside (or past) its box, exactly as the machine would
    draw it; nothing is re-fitted.  Colours and layout edits stay keyed on
    the ORIGINAL string, which is how ``colors.tsv`` / ``layout.tsv`` name
    their rows.
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
            # A layout the user has changed but not built yet: move, align
            # and size, exactly the bytes the Write path rewrites.
            edit = _layout_edit(layout_edits, tx.get("text"))
            dx, dy, align_pick, scale = edit if edit else (0.0, 0.0, None,
                                                            1.0)
            # A replacement typed on the Text tab but not built yet: draw
            # the new letters in the old line's place.  Every other lookup
            # below stays on the ORIGINAL string (the manifests' key).
            shown = (text_edits or {}).get(tx["text"]) or tx["text"]
            try:
                ink, _missing = fr.render_text(font, shown,
                                               metric_scale=scale)
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
            # A move is a shift of the keyframe's rect, which the drawn box
            # follows edge for edge (the Write path adds dx/dy to L,T,R,B).
            left = rect[0] + tx.get("x", 0) + dx
            right = rect[2] + tx.get("x", 0) + dx
            # The align word picks the edge: 0 left, 1 centre, 2 right — read
            # off the boot screen, where "U.S.A." is 0 and sits left while
            # "V0.01" is 2 and sits right, cross-checked against CLOCK being 1
            # and verified centred.  Centring everything mis-placed the rest.
            align = tx.get("align", 1)
            if align_pick is not None:
                align = align_pick
            if align == 0:
                x = left
            elif align == 2:
                x = right - ink.size[0]
            else:
                x = left + (right - left - ink.size[0]) / 2.0
            # the track y is the baseline, so lift by the font's ascent (the
            # scaled one when a size is pending: the baseline stays put and
            # the ink grows up from it, as it does when the table is scaled)
            y = tx.get("y", 0) + dy - font.get("ascent", 0) * scale
            # BC1 ink adds (black draws nothing, as on the machine); alpha
            # glyphs lay OVER the frame — the outline pass under a title is
            # black and would otherwise vanish into whatever it covers.
            _add(canvas, ink, x, y, over=(fr.font_fmt(font) != 4))
            drew = True
    if not drew:
        return None
    return _over_background(viewed(canvas, view), background_spec(background))


def render_scene(assets_dir, card_path, fonts=None, layouts=None,
                 background=None, colors=None, state=0, layout_edits=None,
                 text_edits=None):
    """Preview for one scene by its ``scene.radium`` card path, or ``None``."""
    if layouts is None:
        layouts = load_layouts(assets_dir)
    return render_layout(assets_dir, layouts.get(card_path), fonts=fonts,
                         background=background, colors=colors, state=state,
                         layout_edits=layout_edits, text_edits=text_edits)


def layout_for_scene_dir(layouts, scene_dir):
    """The layout whose radium lives in *scene_dir* (the Scenes window groups
    by directory, the manifest is keyed by the radium's full path)."""
    want = (scene_dir or "").replace("\\", "/").rstrip("/")
    for card, lay in layouts.items():
        if card.replace("\\", "/").rsplit("/", 1)[0] == want:
            return card, lay
    return None, None


# ---------------------------------------------------------------------------------------------
# PAD-251: the scene as the machine draws it, from its TREE (scene_eval draw list)
# ---------------------------------------------------------------------------------------------
_GUTTER = 2.0


def _warp(img, m, cw, ch):
    """*img* placed on a (cw, ch) glass by the affine *m* = (a, b, c, d, tx, ty): returns
    ``(patch RGBA float array, x0, y0)`` covering only the transformed box, or ``None``."""
    import numpy as np
    from PIL import Image
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if abs(det) < 1e-9:
        return None
    iw, ih = img.size
    xs = [tx, a * iw + tx, c * ih + tx, a * iw + c * ih + tx]
    ys = [ty, b * iw + ty, d * ih + ty, b * iw + d * ih + ty]
    x0, x1 = max(0, int(np.floor(min(xs)))), min(cw, int(np.ceil(max(xs))))
    y0, y1 = max(0, int(np.floor(min(ys)))), min(ch, int(np.ceil(max(ys))))
    if x1 <= x0 or y1 <= y0:
        return None
    # inverse: glass (X, Y) -> image (x, y); PIL wants image = A*(X', Y') + C with X' = X - x0
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    ox, oy = x0 - tx, y0 - ty
    coeffs = (ia, ic, ia * ox + ic * oy, ib, id_, ib * ox + id_ * oy)
    patch = img.transform((x1 - x0, y1 - y0), Image.AFFINE, coeffs, resample=Image.BILINEAR)
    return np.asarray(patch, dtype=np.float32), x0, y0


def _composite(canvas, patch, x0, y0, mul, add=(0, 0, 0, 0), premultiplied=True,
               additive=False):
    """Lay *patch* (RGBA float 0..255) on the float *canvas* (premultiplied RGB + coverage).
    Pictures off the card are PREMULTIPLIED (memory of PAD-154: stock BC art keeps RGB <= A);
    glyph ink from :mod:`fontrender` is straight.  *mul* / *add* are the node's colour
    transform."""
    import numpy as np
    h, w = patch.shape[:2]
    dst = canvas[y0:y0 + h, x0:x0 + w]
    a = patch[..., 3:4] / 255.0 * float(mul[3])
    rgb = patch[..., :3] * np.asarray(mul[:3], np.float32)
    if not premultiplied:
        rgb = rgb * (patch[..., 3:4] / 255.0)
    rgb = rgb * float(mul[3]) + np.asarray(add[:3], np.float32) * 255.0 * a
    if additive:
        dst[..., :3] = dst[..., :3] + rgb
    else:
        dst[..., :3] = rgb + dst[..., :3] * (1.0 - a)
    dst[..., 3:4] = a + dst[..., 3:4] * (1.0 - a)


def _composite_skip(skip, patch, x0, y0, mul, add, own, premultiplied=True,
                    additive=False):
    """Keep *skip* (the part of the frame drawn by pictures that pass the machine screen by,
    PAD-325) in step with the frame: *own* draws are laid on it as on the frame; any other
    draw covers what is under it by its own coverage (an additive one covers nothing)."""
    if own:
        _composite(skip, patch, x0, y0, mul, add, premultiplied, additive)
        return
    if additive:
        return
    h, w = patch.shape[:2]
    dst = skip[y0:y0 + h, x0:x0 + w]
    dst *= 1.0 - patch[..., 3:4] / 255.0 * float(mul[3])


def _load_png(assets_dir, rel, cache):
    """*rel*'s picture, from *cache* while the file is unchanged (an editor keeps one cache
    for many renders; a picture replaced on the Images tab is read again)."""
    path = os.path.join(assets_dir, "images", *rel.split("/")) if rel else ""
    return _load_file(path, rel, cache)


def picture_sizes(assets_dir):
    """``{picture rel: (w, h)}``: each scene texture's size on the card (``radium_images.txt``
    pad_w / pad_h, which is the stock PNG's size) - the size a build scales a replacement to
    unless the Images tab's "keep its own size" is ticked."""
    out = {}
    path = os.path.join(assets_dir, "images", "scene_textures", "radium_images.txt")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 6:
                    try:
                        out.setdefault(parts[0], (int(parts[4]), int(parts[5])))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def pending_pictures(assets_dir, bake=True):
    """The Images tab's picks, as a scene render uses them: ``{picture rel: {"path":
    replacement file or None, "keep": keep its own size, "colour": the chosen-files profile
    baked into it, or None}}``.  A pick not built yet is drawn from its own file, so a
    replacement shows in the Scenes tab the moment it is picked.  Pictures added in Scenes
    are listed too, for their colour (PAD-312): the preview shows a switched-on file the way
    the Write bakes it.  ``"skip"`` is True for the user's own picture whose colour switch is
    OFF (red in the Layers list): with :func:`render_tree`'s *as_made* the machine screen
    passes it by and it shows its own colours (PAD-325).  *bake* False is the preview's
    Individual files switch turned off (PAD-330): no picture gets its correction drawn in."""
    try:
        from ...core import staged_changes, colour_profile
        data = staged_changes.load(assets_dir) or {}
    except Exception:
        return {}
    keep = set(data.get("image_keep_size") or ())
    try:
        prof = colour_profile.asset_active(assets_dir)
        settings = colour_profile.asset_settings(assets_dir)
    except Exception:
        prof, settings = None, None
    if not bake:
        prof = None
    out = {}
    for rel, src in (data.get("image") or {}).items():
        if not isinstance(rel, str) or not rel.startswith("images/"):
            continue
        path = src if isinstance(src, str) and os.path.isfile(src) else None
        switch = bool(settings is not None and src
                      and colour_profile.asset_applies(settings, "images", rel))
        out[rel[len("images/"):]] = {
            "path": path, "keep": rel in keep,
            "colour": prof if (prof and switch) else None,
            "skip": bool(path and settings is not None and not switch)}
    if settings is not None:
        try:
            from . import scene_edit
            for ops in scene_edit.load(assets_dir).values():
                for op in ops or ():
                    if not (isinstance(op, dict) and op.get("op") == "add_picture"):
                        continue
                    rel = op.get("image") or ""
                    if not rel or rel in out:
                        continue
                    on = colour_profile.asset_applies(settings, "images", rel,
                                                      own=op.get("color"))
                    if on and prof is not None:
                        path = os.path.join(assets_dir, "images", *rel.split("/"))
                        if os.path.isfile(path):
                            out[rel] = {"path": path, "keep": True, "colour": prof,
                                        "skip": False}
                    elif not on:
                        # drawn from the project's own file as before; only marked
                        out[rel] = {"path": None, "keep": False, "colour": None,
                                    "skip": True}
        except Exception:
            pass
    return out


def _picture(assets_dir, rel, cache, pictures=None, sizes=None):
    """The picture a bitmap draws: the Images tab's pick when there is one, else the project
    folder's file; scaled to the card texture's size as a build would, unless the pick keeps
    its own size (a stock picture already is that size)."""
    pick = (pictures or {}).get(rel) or {}
    src = pick.get("path")
    img = _load_file(src, "pick:" + src, cache) if src else _load_png(assets_dir, rel, cache)
    colour = pick.get("colour")
    if img is not None and colour is not None:
        # the chosen-files profile, as the Write bakes it in (PAD-312)
        ck = ("colour", src or rel, colour.gamma, colour.gain, colour.lift, colour.saturation)
        got = cache.get(ck)
        if got and got[0] is img:
            img = got[1]
        else:
            corrected = colour.apply_image(img)
            cache[ck] = (img, corrected)
            img = corrected
    img = _premultiplied(img, src or rel, cache)
    want = (sizes or {}).get(rel)
    if img is None or not want or pick.get("keep") or tuple(img.size) == tuple(want):
        return img
    key = ("fit", src or rel)
    got = cache.get(key)
    if got and got[0] is img and got[1] == tuple(want):
        return got[2]
    from PIL import Image
    fitted = img.resize(tuple(want), Image.LANCZOS)
    cache[key] = (img, tuple(want), fitted)
    return fitted


#: engine._PREMULT_TOL / the 0.5 % share: the Write's own test for a straight-alpha picture
_PREMULT_TOL = 48


def _premultiplied(img, key, cache):
    """*img* as the card will hold it: the pictures on the card are PREMULTIPLIED and the
    renderer composites them that way, but a replacement saved by an image editor has
    straight alpha, so the Write multiplies its colour by its alpha
    (``engine._premultiply_like_stock``).  The preview does the same, or a "transparent" pixel
    that is not black draws as a solid halo (DragonRR's white box round Battle Select's tile
    grid, gone while he dragged it because the drag layer is straight-alpha).  A card picture
    already passes the test and is returned as it is."""
    if img is None:
        return None
    ck = ("premult", key)
    got = cache.get(ck)
    if got and got[0] is img:
        return got[1]
    import numpy as np
    from PIL import Image
    arr = np.asarray(img.convert("RGBA"))
    a = arr[..., 3].astype(np.int16)
    straight = float((arr[..., :3].max(axis=2).astype(np.int16) > a + _PREMULT_TOL).mean())
    out = img
    if straight > 0.005:
        pm = arr.copy()
        a16 = arr[..., 3:4].astype(np.uint16)
        pm[..., :3] = ((arr[..., :3].astype(np.uint16) * a16 + 127) // 255).astype(np.uint8)
        out = Image.fromarray(pm, "RGBA")
    cache[ck] = (img, out)
    return out


def _load_file(path, key, cache):
    try:
        stamp = os.stat(path).st_mtime_ns if path else None
    except OSError:
        stamp = None
    got = cache.get(key)
    if got is not None and got[0] == stamp:
        return got[1]
    from PIL import Image
    img = None
    if stamp is not None:
        try:
            img = Image.open(path).convert("RGBA")
        except (OSError, ValueError):
            img = None
    cache[key] = (stamp, img)
    return img


def _wraps(d, box_h, step):
    """Does this line of text wrap at its rect's width?  The Text's first flag byte says so
    (a manifest from before it was recorded: a rect tall enough for two lines does)."""
    flags = d.get("flags")
    if flags:
        return bool(flags[0])
    return step > 0 and box_h >= 1.6 * step


def _ink_width(ink_of, s):
    try:
        return ink_of(s).size[0]
    except Exception:
        return 0


def text_lines(text, width, wrap, measure):
    """*text* as the lines a scene draws it in: broken at every ``\\n``, and, when *wrap*,
    at the last space that keeps a line within *width* (a word longer than the width
    stays whole on its own line, as a word processor does)."""
    out = []
    for para in str(text).replace("\r", "").split("\n"):
        if not wrap or width <= 0 or measure(para) <= width:
            out.append(para)
            continue
        cur = ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if cur and measure(cand) > width:
                out.append(cur)
                cur = word
            else:
                cur = cand
        out.append(cur)
    return out


def render_tree(assets_dir, man, frame=None, pins=None, hidden=(), fonts=None,
                background=None, colors=None, text_edits=None, draws=None, cache=None,
                split=None, pictures=None, sizes=None, inks=None, view=None,
                as_made=False):
    """The scene in manifest *man* (:func:`scene_eval.manifest`) at root *frame* as an RGB
    ``PIL.Image`` - every picture with its own place, scale, tilt and fade, in draw order, from
    the project folder's CURRENT PNGs and glyph slices.  *pins* / *hidden* are
    :func:`scene_eval.draw_list`'s; *colors* ``{string: (r, g, b)}`` and *text_edits*
    ``{string: replacement}`` are pending text edits, as in :func:`render_layout`.  Pass
    *draws* to render a draw list already evaluated (and edited).

    *split*, a set of indices into the draw list (one node's draws, which run together in
    draw order), also returns that node's LAYERS for an editor to move live: a dict of
    ``full`` (the scene, as without *split*), ``under`` (what is drawn before it, over the
    background, RGB), ``sel`` (the node alone) and ``over`` (what is drawn after it), the
    last two RGBA with straight alpha.  ``full`` is composed from the three, so it is exact.

    *inks*, a dict, keeps every line of text drawn (its glyphs read off disk and laid out) for
    the next call: a caller drawing many frames of one scene passes the same dict to them all
    (PAD-261: the Godzilla credits' 98 lines read ~17,000 glyph files per ten frames).  It is
    the caller's to drop when the glyphs may have changed; without it nothing is kept.

    *view* (core.colour_profile ``machine_view``) shows the frame as the machine's screen
    will: applied to the finished frame before the backdrop, and to each layer (PAD-312).
    With *as_made*, a picture whose colour switch is off (*pictures*' ``"skip"``) passes the
    screen by and shows its own colours (PAD-325): its share of each pixel is kept apart as
    it is drawn and added back after the rest is viewed, so what covers it still covers it.
    The whole screen overlay still reaches it (*view*'s ``overlay``, PAD-328): the game
    draws that over everything, the user's own files included."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    from . import fontrender as fr
    from . import scene_eval as ev
    try:
        w, h = int(man["stage"][0]), int(man["stage"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not (0 < w <= 8192 and 0 < h <= 8192):
        return None
    if draws is None:
        draws = ev.draw_list(man, frame, pins=pins, hidden=hidden)
    cache = {} if cache is None else cache
    split = set(split or ())
    layers = [np.zeros((h, w, 4), np.float32) for _i in range(3 if split else 1)]
    canvas = layers[0]

    def _skipped(d):
        return (d["kind"] in ("bitmap", "flip")
                and bool(((pictures or {}).get(d.get("image")) or {}).get("skip")))

    skips = None
    if view is not None and as_made and any(_skipped(d) for d in draws):
        skips = [np.zeros_like(c) for c in layers]
    skip = skips[0] if skips else None
    by_key = None
    for i, d in enumerate(draws):
        if split:
            k = 1 if i in split else (2 if i > min(split) else 0)
            canvas = layers[k]
            skip = skips[k] if skips else None
        if d["mul"][3] <= 0.0:
            continue
        if d["kind"] in ("bitmap", "flip"):
            img = _picture(assets_dir, d.get("image"), cache, pictures, sizes)
            if img is None:
                continue
            got = _warp(img, d["m"], w, h)
            if got is not None:
                _composite(canvas, got[0], got[1], got[2], d["mul"], d["add"])
                if skip is not None:
                    _composite_skip(skip, got[0], got[1], got[2], d["mul"], d["add"],
                                    _skipped(d))
        elif d["kind"] == "text":
            if by_key is None:
                if fonts is None:
                    try:
                        fonts = fr.load_fonts(assets_dir)
                    except Exception:
                        fonts = []
                by_key = {f["key"]: f for f in fonts}
            font = fr.font_at_size(by_key.get(d.get("font") or ""), d.get("font_px") or 0)
            if font is None or not d["text"]:
                continue
            shown = (text_edits or {}).get(d["text"]) or d["text"]
            rgba = list(d.get("rgba") or (1, 1, 1, 1))
            if d.get("styled"):
                rgba = [1.0, 1.0, 1.0, rgba[3]]          # the game ignores it (see scene_eval)
            pick = (colors or {}).get(d["text"])
            if pick:
                rgba = [c / 255.0 for c in pick[:3]] + [rgba[3]]
            L, T, R, B = (list(d.get("rect") or (0, 0, w, h)) + [0, 0, 0, 0])[:4]
            align = d.get("align", 1)
            asc = float(d.get("ascent") or font.get("ascent", 0))
            step = float(d.get("line") or 0) or float(font.get("ascent", 0) + font.get("descent", 0))
            if inks is None:
                ink_of = lambda s, _f=font: fr.render_text(_f, s)[0]     # noqa: E731
            else:
                def ink_of(s, _f=font, _k=(d.get("font") or "", d.get("font_px") or 0)):
                    if (_k, s) not in inks:
                        inks[(_k, s)] = fr.render_text(_f, s)[0]
                    return inks[(_k, s)]
            lines = text_lines(shown, R - L - 2 * _GUTTER, _wraps(d, B - T, step),
                               lambda s, _i=ink_of: _ink_width(_i, s))
            mul = tuple(d["mul"][i] * (1.0 if i < 3 else rgba[3]) for i in range(4))
            for k, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    ink = ink_of(line)
                except Exception:
                    continue
                ink = _tint(ink, rgba)
                iw = ink.size[0]
                # A text field keeps a 2 px gutter inside its rect (every stock rect starts at
                # -2, -2), and the first baseline sits the font size's DECLARED ascent below
                # it - measured against the emulator's language screen to the pixel; each
                # further line is the size's declared line height lower.
                x = (L + _GUTTER if align == 0 else
                     (R - _GUTTER - iw if align == 2 else L + (R - L - iw) / 2.0))
                local = (1.0, 0.0, 0.0, 1.0, x,
                         T + _GUTTER + asc - font.get("ascent", 0) + k * step)
                got = _warp(ink, ev.compose(d["m"], local), w, h)
                if got is not None:
                    _composite(canvas, got[0], got[1], got[2], mul, d["add"],
                               premultiplied=False, additive=(fr.font_fmt(font) == 4))
                    if skip is not None:
                        _composite_skip(skip, got[0], got[1], got[2], mul, d["add"], False,
                                        premultiplied=False,
                                        additive=(fr.font_fmt(font) == 4))
        elif d["kind"] in ("video", "spine"):
            # no picture of its own in the project: outline where it plays
            outline = Image.new("RGBA", (max(1, int(d.get("w") or 64)),
                                         max(1, int(d.get("h") or 64))), (40, 40, 60, 90))
            got = _warp(outline, d["m"], w, h)
            if got is not None:
                _composite(canvas, got[0], got[1], got[2], d["mul"], d["add"],
                           premultiplied=False)
                if skip is not None:
                    _composite_skip(skip, got[0], got[1], got[2], d["mul"], d["add"], False,
                                    premultiplied=False)
    spec = background_spec(background)

    def flat(c, s=None):
        out = c.copy()
        out[..., 3] = c[..., 3] * 255.0
        if s is None:
            return viewed(out.clip(0, 255).astype("uint8"), view)
        # the skipped share is kept out of the view and laid back on after
        own = s.copy()
        own[..., 3] = s[..., 3] * 255.0
        rest = np.maximum(out - own, 0.0).clip(0, 255).astype("uint8")
        seen = viewed(rest, view).astype(np.float32)
        overlay = getattr(view, "overlay", None)
        if overlay is not None:
            own = viewed(own.clip(0, 255).astype("uint8"), overlay).astype(np.float32)
        return (seen + own).clip(0, 255).astype("uint8")

    if not split:
        return _over_background(flat(layers[0], skips[0] if skips else None), spec)
    under, sel, over = layers

    def stack(o, m, u):
        out = o.copy()
        out += m * (1.0 - over[..., 3:4])
        out += u * ((1.0 - sel[..., 3:4]) * (1.0 - over[..., 3:4]))
        return out

    full = stack(over, sel, under)
    full_s = stack(skips[2], skips[1], skips[0]) if skips else None

    def straight(c, s=None):
        if s is not None:
            p = flat(c, s).astype(np.float32)
            a = p[..., 3:4]
            rgb = np.where(a > 0.5, p[..., :3] * 255.0 / np.maximum(a, 1.0), 0.0)
            out = np.concatenate([rgb, a], axis=2).clip(0, 255).astype("uint8")
            return Image.fromarray(out, "RGBA")
        a = c[..., 3:4]
        rgb = np.where(a > 1e-6, c[..., :3] / np.maximum(a, 1e-6), 0.0)
        out = np.concatenate([rgb, a * 255.0], axis=2).clip(0, 255).astype("uint8")
        if view is not None:
            out = out.copy()
            out[..., :3] = view(out[..., :3])
        return Image.fromarray(out, "RGBA")

    sk = skips or (None, None, None)
    return {"full": _over_background(flat(full, full_s), spec),
            "under": _over_background(flat(under, sk[0]), spec),
            "sel": straight(sel, sk[1]), "over": straight(over, sk[2])}
