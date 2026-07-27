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
  so ink is composited additively rather than alpha-blended over the
  background (:func:`fontrender.load_slice` already keys alpha off luminance
  for those, which is what makes this work).
"""

import json
import os

SCENE_LAYOUT_MANIFEST = os.path.join("images", "scene_textures",
                                     "scene_layout.json")


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


def describe(layout):
    """One human line about what a preview will show, including what it can't
    (so a static frame is never mistaken for the whole truth)."""
    if not layout:
        return "No preview for this scene."
    n_t = len(layout.get("texts") or ())
    n_s = len(layout.get("sprites") or ())
    bits = []
    if n_s:
        bits.append("%d image%s" % (n_s, "" if n_s == 1 else "s"))
    if n_t:
        bits.append("%d text line%s" % (n_t, "" if n_t == 1 else "s"))
    what = " and ".join(bits) or "nothing drawable"
    w, h, _fps = (list(layout.get("stage") or (0, 0, 0)) + [0, 0, 0])[:3]
    stage = " on a %dx%d stage" % (w, h) if w and h else ""
    n_frames = frame_count(layout)
    if n_frames > 1:
        msg = ("Animation: %d frames of %s%s at the scene's own %g fps, each "
               "frame held for one tick (per-frame holds aren't decoded). "
               % (n_frames, what, stage, frame_rate(layout)))
    else:
        msg = "Still frame: %s%s. Animation isn't shown. " % (what, stage)
    # Say WHAT is missing, not merely that something is: nearly every real
    # scene has an undecoded corner, so a bare "partial" told the user nothing.
    n_un = int(layout.get("unplaced") or 0)
    n_off = int(layout.get("offstage") or 0)
    if n_un:
        msg += ("%d more image%s in this scene can't be placed yet. "
                % (n_un, "" if n_un == 1 else "s"))
    scroll = layout.get("scroll") or ""
    if scroll and n_off:
        # A credits roll is taller than the screen ON PURPOSE.  Calling its
        # off-stage lines undecoded said the preview was broken when it was
        # right — Led Zeppelin's credits span 23 screens of it.
        msg += ("This scene is a %s strip that scrolls through the screen, so "
                "%d of its elements sit outside the frame by design — the "
                "preview is one screenful of it, not the whole strip. "
                % ("tall" if scroll == "vertical" else "wide", n_off))
    elif n_off:
        msg += ("%s off the stage, so %s position isn't fully decoded. "
                % ("1 element sits" if n_off == 1
                   else "%d elements sit" % n_off,
                   "its" if n_off == 1 else "their"))
    n_alt = int(layout.get("alternates") or 0)
    if n_alt:
        msg += ("%d repeat%s of this content sit on top of each other — "
                "alternative states the machine shows one at a time — so only "
                "one of each is drawn. " % (n_alt, "" if n_alt == 1 else "s"))
    return msg.strip()


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


def _add(canvas, img, x, y):
    """Composite *img* onto *canvas* additively (the machine's blend for
    ink-on-black art), clipped to the canvas."""
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
    out = dst[..., :3] + src[..., :3] * alpha
    canvas[dy0:dy0 + h, dx0:dx0 + w, :3] = out.clip(0, 255).astype("uint8")
    canvas[dy0:dy0 + h, dx0:dx0 + w, 3] = 255


def frame_count(layout):
    """How many frames this scene animates over (1 = a still).  Elements with
    different frame counts loop independently; the scene's cycle is the
    longest."""
    if not layout:
        return 1
    return max([1] + [len(sp.get("frames") or ())
                      for sp in layout.get("sprites") or ()])


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


def render_layout(assets_dir, layout, fonts=None, frame=0):
    """Composite *layout* into an RGB ``PIL.Image``, or ``None`` if nothing
    could be drawn.  Pass *fonts* (``fontrender.load_fonts`` output) to render
    many scenes without re-reading the glyph manifest each time, and *frame* to
    pick which frame animated elements show."""
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
    canvas = np.zeros((h, w, 4), np.uint8)
    canvas[..., 3] = 255
    drew = False

    # Art first, then text over it (a scene's text is an overlay; true z-order
    # lives in the undecoded node tree).
    for sp in layout.get("sprites") or ():
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

    texts = layout.get("texts") or ()
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
            try:
                ink, _missing = fr.render_text(font, tx["text"])
            except Exception:
                continue
            ink = _tint(ink, tx.get("rgba") or (1, 1, 1, 1))
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
            _add(canvas, ink, x, y)
            drew = True
    if not drew:
        return None
    return Image.fromarray(canvas, "RGBA").convert("RGB")


def render_scene(assets_dir, card_path, fonts=None, layouts=None):
    """Preview for one scene by its ``scene.radium`` card path, or ``None``."""
    if layouts is None:
        layouts = load_layouts(assets_dir)
    return render_layout(assets_dir, layouts.get(card_path), fonts=fonts)


def layout_for_scene_dir(layouts, scene_dir):
    """The layout whose radium lives in *scene_dir* (the Scenes window groups
    by directory, the manifest is keyed by the radium's full path)."""
    want = (scene_dir or "").replace("\\", "/").rstrip("/")
    for card, lay in layouts.items():
        if card.replace("\\", "/").rsplit("/", 1)[0] == want:
            return card, lay
    return None, None
