"""Tests for the Spike 2 static scene preview (layout parse + compositing).

The layout parser is exercised against a SYNTHETIC radium built here to the
documented serialization grammar, so the byte-level expectations are visible
in the test rather than hidden in a card image.  The real cards are the other
half of the bar and can't live in the suite: a crash-free sweep over TMNT
(1385 radiums) and Munsters plus visual spot-checks against the machine's own
output are scratchpad work, recorded in the handoff notes.

What matters here: the parser reads positions/strings the way the compositor
expects, refuses scenes it cannot honestly draw, never raises on junk, and the
compositor draws from the CURRENT project files (so a font import or replaced
image shows up in the preview).
"""

import json
import os
import struct

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")
import numpy as np                          # noqa: E402
from PIL import Image                       # noqa: E402

from pinball_decryptor.plugins.stern import (                # noqa: E402
    scene_layout, scene_render)


# ---------------------------------------------------------------------------
# Synthetic radium tail (the node graph the parser reads)
# ---------------------------------------------------------------------------

def _s(text):
    """``[u64 len][latin1]`` — the file's string encoding."""
    b = text.encode("latin1")
    return struct.pack("<Q", len(b)) + b


def _keyframe(seq, text, rect=(0.0, 0.0, 1360.0, 120.0),
              rgba=(1.0, 1.0, 1.0, 1.0), align=1, font=""):
    """``[HANDLE][seq][u64 0][rect x4][rgba x4][u16 0][align][spacing][u32]
    [STR][u8 2][24B pad]``.

    *font* writes the line's FONT NAME string 12 bytes after the display
    string's data, which is where the real file carries it — the ``[u8 2]``
    plus the first 11 pad bytes."""
    tail = (bytes([2]) + b"\x00" * 11 + _s(font) + b"\x00" * 13) if font \
        else (bytes([2]) + b"\x00" * 24)
    return (struct.pack("<II", 0x80000001 | (seq << 8), seq)
            + struct.pack("<Q", 0)
            + struct.pack("<4f", *rect) + struct.pack("<4f", *rgba)
            + struct.pack("<H", 0) + struct.pack("<I", align)
            + struct.pack("<f", 0.0) + struct.pack("<I", 0)
            + _s(text) + tail)


def _track(x=0.0, y=0.0):
    """``[u32 null handle][f32 1.0][f32 0][f32 x][f32 y]`` — the last track of
    an instance is its position."""
    return (struct.pack("<I", 0x80000000) + struct.pack("<2f", 1.0, 0.0)
            + struct.pack("<2f", x, y))


def _stage(w=1360, h=768, fps=60.0, root_kids=2):
    """Stage header, then the ROOT's own record trailer: ``[u32 node-type
    count][u32 child count][u32 0]`` sits immediately before the first node's
    handle, which is where the tree walk starts."""
    return (b"\x00" * 8 + struct.pack("<2I", w, h) + struct.pack("<f", fps)
            + b"\x00" * 12 + struct.pack("<f", 1.0) + b"\x00" * 12
            + struct.pack("<3I", 1, root_kids, 0))


def _text_scene(lines, stage_wh=(1360, 768), rect=(0.0, 0.0, 1360.0, 120.0),
                fonts=None):
    """A text scene: keyframes, then the stage, then one instance per line.
    *lines* = ``[(name, x, baseline_y, string)]``; *fonts*, when given, is the
    per-line font NAME each keyframe references."""
    out = bytearray()
    for i, (_n, _x, _y, s) in enumerate(lines):
        out += _keyframe(i + 1, s, rect=rect,
                         font=(fonts[i] if fonts else ""))
    out += _stage(*stage_wh)
    for i, (name, x, y, _s) in enumerate(lines):
        out += _s_instance(name, x, y, seq=i + 1)
    return bytes(out)


def _s_instance(name, x, y, seq=None, image_ref=b""):
    """Instance := name, flag words, 3 tracks (last = position), and — for a
    text line only — a keyframe linking it to its string.  A sprite instance
    instead carries the width/height/handle triple naming its image."""
    body = _s(name) + struct.pack("<9I", *([1] * 9))
    body += _track() + _track() + _track(x, y)
    if seq is not None:
        body += _keyframe(seq, "")
    return body + image_ref


def _sprite_scene(sprites, stage_wh=(1360, 768)):
    """A sprite scene: the stage, then instances with a position and NO
    keyframe (the machine's own shape for image instances)."""
    out = bytearray(_stage(*stage_wh))
    for name, x, y in sprites:
        out += _s_instance(name, x, y, seq=None)
    return bytes(out)


def _fake_image(off, w=64, h=32):
    """Minimal ``parse_radium_images``-shaped dict."""
    return {"data_off": off, "length": 16, "fmt": 5, "tex_w": w, "tex_h": h,
            "pad_w": w, "pad_h": h, "disp_w": w, "disp_h": h}


def _image_head(specs, head_len=256):
    """A file head carrying each image's introducing handle 28 bytes before its
    block data, which is where a user's back-reference resolves to.
    *specs* = ``[(data_off, handle)]``."""
    buf = bytearray(head_len)
    for off, handle in specs:
        struct.pack_into("<I", buf, off - 28, 0x80000000 | handle)
    return bytes(buf)


def _image_ref(w, h, handle):
    """What a sprite instance carries to say which image it draws:
    ``[u32 dispW][u32 dispH][u32 handle]`` (handle without the 0x80 top byte)."""
    return struct.pack("<3I", w, h, handle)


def _framed_scene(nodes, stage_wh=(1360, 768), root_kids=1,
                  rect=(0.0, 0.0, 1360.0, 120.0), kid_counts=None):
    """A scene serialized as a node TREE.

    Every record is ``[u32 handle][u64 name len][name][payload]`` and ENDS with
    ``[u32 child count][u32 0]`` immediately before the next record's handle;
    children follow their parent depth-first.  *nodes* is that depth-first
    order as ``(name, x, y, children, text or None, image ref bytes)``.
    *kid_counts* overrides what each record CLAIMS, so a scene whose counts
    don't add up can be tested."""
    head = bytearray()
    for i, (_n, _x, _y, _k, text, _r) in enumerate(nodes):
        if text:
            head += _keyframe(i + 1, text, rect=rect)
    body = bytearray(_stage(stage_wh[0], stage_wh[1], root_kids=root_kids))
    for i, (name, x, y, kids, text, ref) in enumerate(nodes):
        if i:
            claim = kid_counts[i - 1] if kid_counts else nodes[i - 1][3]
            body += struct.pack("<2I", claim, 0)     # previous record's tail
        body += struct.pack("<I", 0x80000101 + i * 2)          # this handle
        body += _s_instance(name, x, y, seq=(i + 1) if text else None,
                            image_ref=ref)
    return bytes(head + body)


def _radium(tail, head_len=64):
    """A file whose decoded region ends at *head_len* (an image block) so the
    parser starts scanning at the tail."""
    return b"\x00" * head_len + tail


# ---------------------------------------------------------------------------
# alternative-state pruning
# ---------------------------------------------------------------------------

def _art(node, x, y, off):
    return {"name": "i%d" % node, "node": node, "x": x, "y": y,
            "image_off": off}


def _line(node, x, y, text, w=300.0, h=60.0):
    return {"name": "t%d" % node, "node": node, "x": x, "y": y, "text": text,
            "rect": [0.0, 0.0, w, h]}


def test_letters_in_a_row_are_not_alternative_states():
    """A word spelled out of letter SPRITES keeps every letter.

    Letter art is a padded slot — TMNT's "APRIL" is five 280x336 images about
    160px apart, so each covers 55% of its neighbour's box while sharing none
    of its ink.  Judged that way every second letter was deleted as a repeat
    and the screen read "A R L" (David).  Each letter is its own subtree of
    two states (off + on), which is what made them eligible at all."""
    xs = [252.0, 413.0, 567.0, 729.0, 854.0]
    dims, sprites, parent_of = {}, [], {}
    for i, x in enumerate(xs):
        for state in (0, 1):
            off = 100 + i * 2 + state
            dims[off] = (280, 336)
            sprites.append(_art(off, x, 207.0, off))
            parent_of[off] = 10 + i        # each letter is its own subtree
    texts, kept, _alt_t, alt_s = scene_layout._drop_overlapping_subtrees(
        [], sprites, parent_of, dims)
    assert texts == [] and alt_s == []
    assert sorted({s["x"] for s in kept}) == xs

    # ...while art genuinely redrawn in the same place is still one state
    dup = [_art(1, 100.0, 100.0, 1), _art(2, 100.0, 100.0, 2),
           _art(3, 104.0, 102.0, 3), _art(4, 104.0, 102.0, 4)]
    dims2 = {n: (400, 300) for n in (1, 2, 3, 4)}
    _t, kept2, _at2, alt_s2 = scene_layout._drop_overlapping_subtrees(
        [], dup, {1: 20, 2: 20, 3: 21, 4: 21}, dims2)
    assert len(alt_s2) == 2 and len(kept2) == 2
    # the repeat is not discarded — it is state 1 of the slot state 0 holds
    assert {s["state"] for s in kept2} == {0}
    assert {s["state"] for s in alt_s2} == {1}


def test_repeated_text_placeholders_still_collapse():
    """A group holding TEXT keeps the stricter test: a text element's box IS
    its text, so overlapping really does mean drawing on top.  A template
    screen repeating "INFORMATION" across the same band must still show one —
    loosening this for text piled six copies into an unreadable smear."""
    lines = [_line(1, 90.0, 200.0, "INFORMATION"),
             _line(2, 100.0, 205.0, "TOTAL"),
             _line(3, 250.0, 200.0, "INFORMATION"),
             _line(4, 260.0, 205.0, "TOTAL")]
    texts, _s, alt_t, _as = scene_layout._drop_overlapping_subtrees(
        lines, [], {1: 30, 2: 30, 3: 31, 4: 31}, {})
    assert len(alt_t) == 2 and len(texts) == 2


# ---------------------------------------------------------------------------
# parse_scene_layout
# ---------------------------------------------------------------------------

def test_parse_text_scene_positions_and_strings():
    """Each line's string comes from the keyframe its sequence id links to,
    and its track y is the baseline."""
    lines = [("Line1", 2.0, 264.0, "CLOCK NOT SET"),
             ("Line2", 2.0, 386.0, "APR. 15, 2016")]
    data = _radium(_text_scene(lines))
    # A text scene's image IS its font atlas, so it is declared as one — with
    # no table it counts as art nothing draws, which is now (correctly) an
    # unplaced image.
    atlas = _fake_image(48)
    lay = scene_layout.parse_scene_layout(data, [atlas],
                                          [_font_table("F", atlas, 40)])
    assert lay is not None
    assert lay["stage"] == (1360, 768, 60.0)
    assert lay["partial"] is False
    got = [(t["name"], t["x"], t["y"], t["text"]) for t in lay["texts"]]
    assert got == [("Line1", 2.0, 264.0, "CLOCK NOT SET"),
                   ("Line2", 2.0, 386.0, "APR. 15, 2016")]
    assert lay["sprites"] == []


def _font_table(name, atlas, px):
    """A glyph table whose metrics make :func:`radium.table_size_px` read *px*
    (ascent + descent, with descent 0)."""
    return {"name": name, "table_off": 0, "table_end": 8,
            "glyphs": [{"char": 65, "atlas": atlas,
                        "metrics": (10.0, float(px), 0.0, float(px), 12.0)}]}


def test_each_line_uses_the_font_its_keyframe_names():
    """A keyframe names the font for THAT LINE, 12 bytes after its string.

    Before this was decoded the parser picked one table for the whole scene,
    which is wrong far more often than it looks — most scenes hold several
    named fonts (57 of 60 sampled TMNT radiums).  JAWS' 30ec1fad named
    Stern_SharpGrotesk (42px) on every line while the scene-wide guess took
    Stern_AmityJack (81px), so its instructions rendered huge and overlapping."""
    big, small = _fake_image(32), _fake_image(48)
    tables = [_font_table("BigFace", big, 90), _font_table("SmallFace", small,
                                                           30)]
    lines = [("Line1", 2.0, 100.0, "TITLE"), ("Line2", 2.0, 300.0, "BODY")]
    data = _radium(_text_scene(lines, fonts=["BigFace", "SmallFace"]))
    lay = scene_layout.parse_scene_layout(data, [big, small], tables)
    assert lay is not None
    got = [(t["text"], t["font_atlas_off"], t["font_px"]) for t in lay["texts"]]
    assert got == [("TITLE", 32, 90), ("BODY", 48, 30)]


def test_line_with_no_named_font_falls_back_to_the_scene_pick():
    """Only ~90% of display strings carry the reference (27% on Munsters, and
    TMNT's CLOCK screen none at all), so the scene-wide pick has to remain."""
    big, small = _fake_image(32), _fake_image(48)
    tables = [_font_table("BigFace", big, 90), _font_table("SmallFace", small,
                                                           30)]
    lines = [("Line1", 2.0, 100.0, "TITLE")]
    data = _radium(_text_scene(lines))          # no font names written
    lay = scene_layout.parse_scene_layout(data, [big, small], tables)
    assert lay is not None
    assert [(t["font_atlas_off"], t["font_px"]) for t in lay["texts"]] \
        == [(32, 90)]


def test_outline_and_fill_collapse_even_in_different_fonts():
    """A title is an outline instance under a fill instance at the SAME spot,
    and they name DIFFERENT faces.

    The duplicate rules keyed on the font, which was invisible while every line
    in a scene shared one — decoding the per-line font split the pair apart and
    every John Wick title drew twice, in two faces, on top of itself."""
    body, outline = _fake_image(32), _fake_image(48)
    tables = [_font_table("Body", body, 60), _font_table("Body_Outline",
                                                         outline, 60)]
    lines = [("Instance_T_Outline", 40.0, 100.0, "KIRILL BATTLE READY"),
             ("Instance_T", 40.0, 100.0, "KIRILL BATTLE READY")]
    data = _radium(_text_scene(lines, fonts=["Body_Outline", "Body"]))
    lay = scene_layout.parse_scene_layout(data, [body, outline], tables)
    assert lay is not None
    # one line survives, and it is the LAST — the fill, drawn on top
    assert [(t["text"], t["font_atlas_off"]) for t in lay["texts"]] \
        == [("KIRILL BATTLE READY", 32)]


def test_scene_names_its_screens_and_they_can_be_isolated():
    """One scene file holds every screen a mode can put up, and the node tree
    already separates them: JAWS' 30ec1fad has Intro_Instance, Award1_Instance,
    Phase2_Start_Instance, Victory_Start_Instance and more, which the machine
    shows one at a time under game control (there is no timeline in the file —
    the only per-instance words that vary are a byte-misaligned sequential node
    index).  Drawn together they are the pile David reported, so each is
    offered by its own name.

    Isolating a screen must show ALL of it, including elements the composite
    pruned — a whole screen is often pruned as a repeat of an earlier one, and
    filtering the isolated view by state would then draw nothing."""
    page = lambda tag, dy: [                                    # noqa: E731
        ("%s_Frame" % tag, 680.0, 300.0 + dy, 2, None, b""),
        ("%s_Title" % tag, -260.0, -99.15, 0, "%s TITLE" % tag, b""),
        ("%s_Name" % tag, -347.5, 5.4, 0, "%s NAME" % tag, b"")]
    nodes = page("HS", 0.0) + page("COOP", 8.0)
    data = _radium(_framed_scene(nodes, root_kids=2,
                                 rect=(-322.5, -40.0, 322.5, 40.0)))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None
    assert lay["groups"] == ["HS_Frame", "COOP_Frame"]
    # the composite still draws one of them, exactly as before
    assert sorted(t["text"] for t in scene_render._visible(lay["texts"], 0)) \
        == ["HS NAME", "HS TITLE"]
    # ...and the pruned screen is fully reachable by name
    assert sorted(t["text"] for t in scene_render._in_group(lay["texts"], 1)) \
        == ["COOP NAME", "COOP TITLE"]
    assert "COOP_Frame" in scene_render.describe(lay, 0, 1)


def test_states_are_stepped_not_composited():
    """Alternative states are kept and drawn ONE AT A TIME.

    They used to be discarded and merely counted, so a scene that redraws the
    same spot — a page carousel, a mode's instruction screens — had nothing to
    step through and the caption just said some content wasn't drawn (David:
    "how can i see the different states by themselves? there is no control for
    that").  Anything with no slot belongs to every state."""
    els = [{"name": "bg"},                                  # no slot: always
           {"name": "p0", "slot": 0, "state": 0},
           {"name": "p1", "slot": 0, "state": 1},
           {"name": "p2", "slot": 0, "state": 2},
           {"name": "q0", "slot": 1, "state": 0},           # shallower slot
           {"name": "q1", "slot": 1, "state": 1}]
    seen = [sorted(e["name"] for e in scene_render._visible(els, k))
            for k in range(3)]
    assert seen == [["bg", "p0", "q0"],
                    ["bg", "p1", "q1"],
                    # slot 1 has run out, so it holds its LAST state rather
                    # than vanishing and blanking part of the picture
                    ["bg", "p2", "q1"]]


def test_parse_sprite_scene_needs_no_keyframe():
    """An image instance carries only a name and a position — requiring a
    keyframe (as text lines have) made every sprite scene unreadable."""
    data = _radium(_sprite_scene([("unnamed_instance_1", 395.0, 127.0)]))
    imgs = [_fake_image(48, 572, 500)]
    lay = scene_layout.parse_scene_layout(data, imgs, [])
    assert lay is not None
    assert [(s["name"], s["x"], s["y"], s["image_off"])
            for s in lay["sprites"]] == [("unnamed_instance_1", 395.0,
                                          127.0, 48)]


def test_parse_drops_origin_pinned_duplicate_instances():
    """Repeated copies of one sprite pinned at the origin are animation-state
    copies, not extra art stacked at the corner: with a positioned instance
    present they're dropped."""
    data = _radium(_sprite_scene([("unnamed_instance_1", 395.0, 127.0),
                                  ("unnamed_instance_0", 0.0, 0.0)]))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert [(s["x"], s["y"]) for s in lay["sprites"]] == [(395.0, 127.0)]


def test_parse_ignores_asset_reference_names():
    """``N.asset`` strings are a scene's video/texture references.  Reading
    them as instance names turned one video-list scene into a dozen phantom
    sprites stacked at the same spot."""
    data = _radium(_sprite_scene([("13.asset", 547.0, 0.0),
                                  ("12.asset", 547.0, 0.0),
                                  ("Real_Sprite", 100.0, 200.0)]))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert [s["name"] for s in lay["sprites"]] == ["Real_Sprite"]


def test_parse_reads_far_negative_coordinates_from_the_stage_centre():
    """A large family of scenes measures coordinates from the stage CENTRE, not
    its top-left, and those read as far-negative numbers: TMNT's AWARD popup
    sits at (-172.5, -25).  Adding half the stage lands them where they belong.

    On the TMNT card, 79 scenes placed nothing at all under the top-left
    reading and centring rescued all 79 — every element, no partial wins,
    which is what makes it a convention rather than a lucky nudge."""
    data = _radium(_text_scene([("Instance_AwardTitle", -172.5, -102.0,
                                 "AWARD")]))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None and lay["origin"] == "center"
    t = lay["texts"][0]
    assert (t["x"], t["y"]) == (-172.5 + 680, -102.0 + 384)
    assert lay["offstage"] == 0


def test_parse_leaves_a_working_scene_on_its_own_coordinates():
    """The reinterpretation is conservative: a scene that already places every
    element from the top-left is never shifted, so the verified CLOCK screen
    keeps the positions its render was checked against."""
    lines = [("Line1", 2.0, 264.0, "CLOCK NOT SET"),
             ("Line2", 2.0, 386.0, "APR. 15, 2016")]
    lay = scene_layout.parse_scene_layout(
        _radium(_text_scene(lines)), [_fake_image(48)], [])
    assert lay["origin"] == "topleft"
    assert [(t["x"], t["y"]) for t in lay["texts"]] == [(2.0, 264.0),
                                                        (2.0, 386.0)]


def test_parse_declines_when_neither_reading_works():
    """Centring is only accepted when it fixes the scene COMPLETELY; anything
    else keeps the coordinates as read rather than guessing, so a scene with
    nothing on stage still gets no preview instead of a black frame."""
    data = _radium(_text_scene([("Line1", 2.0, -4000.0, "MILES ABOVE")]))
    assert scene_layout.parse_scene_layout(data, [_fake_image(48)], []) is None


def test_parse_counts_what_is_missing_rather_than_just_flagging_it():
    """On a real card nearly every scene has an undecoded corner, so a bare
    "partial" was noise on 94% of them; the caption states the numbers."""
    lines = [("Line1", 2.0, 264.0, "ON STAGE"),
             ("Line2", 2.0, -400.0, "OFF STAGE")]
    atlas = _fake_image(48)
    lay = scene_layout.parse_scene_layout(
        _radium(_text_scene(lines)), [atlas], [_font_table("F", atlas, 40)])
    assert lay is not None and lay["partial"] is True
    assert lay["offstage"] == 1 and lay["unplaced"] == 0
    assert "1 element sits off the stage" in scene_render.describe(lay)


def test_unplaced_counts_images_and_cannot_exceed_the_art_present():
    """"N more images can't be placed" has to MEAN images.

    It used to count INSTANCES with no image triple, which reported 43 on
    JAWS' 30ec1fad — a scene holding nine pieces of art. Those 43 were Text
    nodes (the child a text instance hangs its string on) falling through to
    the sprite branch, so the figure was not merely wrong, it was impossible.
    Counting the scene's own art that nothing draws is bounded by the art it
    has, and it went quiet: 41 of 50 sampled scenes on both JAWS and TMNT now
    report zero."""
    drawn, spare = _fake_image(60, 40, 20), _fake_image(120, 40, 20)
    head = _image_head([(60, 2), (120, 4)], head_len=256)
    tail = _sprite_scene([])
    tail += _s_instance("Art", 10.0, 20.0, image_ref=_image_ref(40, 20, 2))
    lay = scene_layout.parse_scene_layout(head + tail, [drawn, spare], [])
    assert lay is not None
    assert [s["image_off"] for s in lay["sprites"]] == [60]
    # exactly one piece of art goes undrawn, and that is the number reported
    assert lay["unplaced"] == 1
    assert "1 more image in this scene can't be placed" \
        in scene_render.describe(lay)


def test_parse_resolves_which_image_each_instance_draws():
    """A sprite instance names its image with a width/height/handle triple, so
    a scene holding several pieces of art places each one correctly.

    Handles are small sequential integers — far too common to search for alone
    — which is why the two dimensions beside it must match that same image.
    Derived by diffing two adjacent instances of TMNT's award grid; verified on
    the real card by its icons matching their captions."""
    imgs = [_fake_image(60, 122, 84), _fake_image(120, 944, 578)]
    head = _image_head([(60, 2), (120, 26)])
    tail = _sprite_scene([])                       # stage only
    tail += _s_instance("icon", 276.0, 230.0, image_ref=_image_ref(122, 84, 2))
    tail += _s_instance("backdrop", 208.0, 95.0,
                        image_ref=_image_ref(944, 578, 26))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert lay is not None
    got = {s["name"]: s["image_off"] for s in lay["sprites"]}
    assert got == {"icon": 60, "backdrop": 120}
    assert lay["unplaced"] == 0


def test_parse_counts_unplaceable_images_when_no_reference_is_present():
    """Without that triple, one of several images cannot be chosen, so the
    instance is reported as unplaced instead of guessed at."""
    data = _radium(_sprite_scene([("Sprite_A", 100.0, 200.0),
                                  ("Sprite_B", 300.0, 400.0)]))
    lay = scene_layout.parse_scene_layout(
        data, [_fake_image(40), _fake_image(48)], [])
    assert lay is None or lay["sprites"] == []
    if lay is not None:
        assert lay["unplaced"] >= 1
        assert "can't be placed yet" in scene_render.describe(lay)


def test_parse_ignores_font_atlases_when_placing_art():
    """A text-heavy scene embeds an atlas page per font size (eleven on TMNT's
    award screen).  Those are already on screen AS the text, so counting them
    as art reported a fully-rendered scene as mostly broken — and hid the one
    real image, which is placeable precisely because it is then unambiguous."""
    atlas, art = _fake_image(60, 512, 512), _fake_image(120, 40, 20)
    tables = [{"name": "AFont", "table_off": 0, "table_end": 8,
               "glyphs": [{"char": 65, "atlas": atlas}]}]
    data = _image_head([(60, 2), (120, 4)]) + _sprite_scene(
        [("Art", 10.0, 20.0)])
    lay = scene_layout.parse_scene_layout(data, [atlas, art], tables)
    assert lay is not None
    assert [(s["name"], s["image_off"]) for s in lay["sprites"]] == [("Art",
                                                                     120)]
    assert lay["unplaced"] == 0


def test_parse_skips_font_name_strings_as_instances():
    """A font's name sits in the node region as a plain string; reading it as
    an instance invented sprites that don't exist."""
    tables = [{"name": "Stern_Impact", "table_off": 0, "table_end": 8,
               "glyphs": [{"char": 65, "atlas": _fake_image(60)}]}]
    data = _image_head([(60, 2), (120, 4)]) + _sprite_scene(
        [("Stern_Impact", 500.0, 500.0), ("RealArt", 10.0, 20.0)])
    lay = scene_layout.parse_scene_layout(
        data, [_fake_image(60), _fake_image(120, 40, 20)], tables)
    assert lay is not None
    assert [s["name"] for s in lay["sprites"]] == ["RealArt"]


def test_parse_collapses_stacked_duplicate_sprites():
    """Carousel scenes stack dozens of instances of one image at one spot and
    reveal them over time; drawing the stack adds only a smear."""
    imgs = [_fake_image(60, 122, 84)]
    head = _image_head([(60, 2)])
    tail = _sprite_scene([])
    for i in range(4):
        tail += _s_instance("copy%d" % i, 100.0, 200.0,
                            image_ref=_image_ref(122, 84, 2))
    tail += _s_instance("elsewhere", 700.0, 300.0,
                        image_ref=_image_ref(122, 84, 2))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert [(s["x"], s["y"]) for s in lay["sprites"]] == [(100.0, 200.0),
                                                          (700.0, 300.0)]


def test_parse_denormal_coordinate_reads_as_zero():
    """A coordinate that was never written shows up as denormal junk
    (-2.9e-42), which is a zero, not a position."""
    junk = struct.unpack("<f", struct.pack("<I", 0x80000123))[0]
    data = _radium(_sprite_scene([("Sprite", 100.0, junk)]))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay["sprites"][0]["y"] == 0.0


def test_parse_returns_none_for_non_scenes_and_junk():
    """Video lists and texture catalogs aren't drawable scenes, and no input
    may raise — this runs over every radium on a card during extract."""
    assert scene_layout.parse_scene_layout(b"", [], []) is None
    assert scene_layout.parse_scene_layout(b"\x00" * 4096,
                                           [_fake_image(48)], []) is None
    assert scene_layout.parse_scene_layout(
        bytes(range(256)) * 40, [_fake_image(48)], []) is None
    # a stage header with nothing drawable after it is not a scene
    assert scene_layout.parse_scene_layout(
        _radium(_stage()), [_fake_image(48)], []) is None


def test_parse_never_raises_on_truncation():
    """Every prefix of a valid scene must parse or decline, never explode."""
    full = _radium(_text_scene([("Line1", 2.0, 264.0, "HELLO")]))
    for cut in range(0, len(full), 7):
        scene_layout.parse_scene_layout(full[:cut], [_fake_image(48)], [])


# ---------------------------------------------------------------------------
# Compositing from an extract folder
# ---------------------------------------------------------------------------

def _seed_preview_extract(tmp_path, font_px=(255, 255, 255)):
    """A project folder holding one sprite PNG, one 1-glyph font (atlas +
    slice + manifest), and a scene_layout.json using both."""
    st = tmp_path / "images" / "scene_textures"
    gdir = st / "glyphs" / "radimg_font_64x64_aaaa0001"
    gdir.mkdir(parents=True)
    # sprite art: a solid red square
    Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(
        st / "radimg_art_40x20_bbbb0002.png")
    # font: one 8x8 'A' glyph, white ink
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(
        st / "radimg_font_64x64_aaaa0001.png")
    Image.new("RGBA", (8, 8), tuple(font_px) + (255,)).save(
        gdir / "U+0041_A.png")
    (st / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "scene_textures/radimg_font_64x64_aaaa0001.png\t/g/s1/scene.radium"
        "\t100\t16\t64\t64\t5\n"
        "scene_textures/radimg_art_40x20_bbbb0002.png\t/g/s1/scene.radium"
        "\t200\t16\t40\t20\t5\n", encoding="utf-8")
    (st / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\trot\tglyph_w"
        "\tglyph_h\tbearing_x\tbearing_y\tadvance\ttable\n"
        "scene_textures/glyphs/radimg_font_64x64_aaaa0001/U+0041_A.png\t"
        "scene_textures/radimg_font_64x64_aaaa0001.png\t0x0041\t0\t0\t8\t8\t"
        "TestFont\t0\t8\t8\t0\t8\t9\tradimg_font_64x64_aaaa0001\n",
        encoding="utf-8")
    layout = {
        "/g/s1/scene.radium": {
            "stage": [200, 100, 60.0], "partial": False,
            "texts": [{"name": "Line1", "x": 0, "y": 60,
                       "text": "A", "rect": [0, 0, 200, 100],
                       "rgba": [1, 1, 1, 1], "align": 1,
                       "font": "radimg_font_64x64_aaaa0001"}],
            "sprites": [{"name": "Art", "x": 10, "y": 5,
                         "image": "scene_textures/radimg_art_40x20_bbbb0002"
                                  ".png"}],
        }
    }
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)
    return str(tmp_path)


def test_render_scene_draws_sprite_and_text():
    """The frame is stage-sized, the sprite lands at its own coordinates, and
    the glyph lands above its baseline."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        img = scene_render.render_scene(assets, "/g/s1/scene.radium")
        assert img is not None and img.size == (200, 100)
        a = np.asarray(img)
        # sprite: red block at (10,5)..(50,25)
        assert tuple(a[15, 30]) == (255, 0, 0)
        assert tuple(a[2, 2]) == (0, 0, 0)          # background stays black
        # glyph: white ink somewhere above the baseline (y=60), centered
        band = a[52:60, :]
        assert band.max() > 200, "no glyph ink above the baseline"


def test_render_reflects_an_edited_glyph():
    """The preview composites the project's CURRENT files, so a font import
    (which rewrites the glyph slice PNGs) shows up without re-extracting."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        assets = _seed_preview_extract(root)
        before = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium")).copy()
        # repaint the 'A' slice green, exactly what an import does
        slice_png = (root / "images" / "scene_textures" / "glyphs"
                     / "radimg_font_64x64_aaaa0001" / "U+0041_A.png")
        Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(slice_png)
        after = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium"))
        assert not np.array_equal(before, after)
        band = after[52:60, :]
        # green channel now dominates where the ink is
        ink = band.reshape(-1, 3)[band.reshape(-1, 3).max(axis=1) > 200]
        assert len(ink) and (ink[:, 1] > ink[:, 0]).all()


def test_render_tints_text_by_keyframe_color():
    """Stock ink is white so the scene can color it; the keyframe RGBA is the
    tint."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        assets = _seed_preview_extract(root)
        path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
        with open(path, encoding="utf-8") as f:
            lay = json.load(f)
        lay["/g/s1/scene.radium"]["texts"][0]["rgba"] = [0.0, 0.0, 1.0, 1.0]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lay, f)
        a = np.asarray(scene_render.render_scene(assets,
                                                 "/g/s1/scene.radium"))
        band = a[52:60, :].reshape(-1, 3)
        ink = band[band.max(axis=1) > 200]
        assert len(ink) and (ink[:, 2] > ink[:, 0]).all()   # blue, not white


def _relayout(assets, mutate):
    """Edit the seeded layout in place (the fixture only covers one shape)."""
    path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
    with open(path, encoding="utf-8") as f:
        lay = json.load(f)
    mutate(lay["/g/s1/scene.radium"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lay, f)


def test_background_black_is_the_render_that_has_always_been_drawn():
    """The machine draws on black, so "Black" must stay byte-for-byte the frame
    this module produced before backdrops existed — the others only fill in
    where nothing was drawn."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        base = scene_render.render_scene(assets, "/g/s1/scene.radium")
        black = scene_render.render_scene(assets, "/g/s1/scene.radium",
                                          background="Black")
        assert np.array_equal(np.asarray(base), np.asarray(black))
        white = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium", background="White"))
        assert tuple(white[2, 2]) == (255, 255, 255)      # untouched pixel
        assert tuple(white[15, 30]) == (255, 0, 0)        # the art is intact
        # an unknown name falls back to black rather than failing
        assert np.array_equal(np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium", background="Puce")),
            np.asarray(base))


def test_black_ink_is_invisible_on_black_and_shows_on_a_light_backdrop():
    """a tester asked for other backgrounds to "check the black border stuff".
    Black ink adds nothing to a black frame — on the machine as here — so it
    can only be looked at over something else."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        _relayout(assets, lambda sc: (sc["texts"][0].__setitem__(
            "rgba", [0.0, 0.0, 0.0, 1.0]), sc.__setitem__("sprites", [])))
        on_black = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium"))
        assert on_black.max() == 0, "black ink somehow lit a black frame"
        on_white = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium", background="White"))
        band = on_white[52:60, :].reshape(-1, 3)
        assert (band.max(axis=1) < 40).any(), "the black letter never showed"


def test_render_shows_a_colour_the_user_has_picked_but_not_built():
    """The Scenes window passes pending colours straight into the render, so a
    recolour is visible before the card is written."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        a = np.asarray(scene_render.render_scene(
            assets, "/g/s1/scene.radium", colors={"A": (255, 0, 0)}))
        band = a[52:60, :].reshape(-1, 3)
        ink = band[band.max(axis=1) > 200]
        assert len(ink) and (ink[:, 0] > ink[:, 2]).all()   # red, not white


def test_text_tints_reports_what_each_font_is_drawn_in():
    """The Fonts window can only explain "your green came out olive" if it
    knows the colours the scenes multiply that font by."""
    layouts = {
        "/g/a.radium": {"texts": [
            {"font": "tbl", "text": "A", "rgba": [1, 1, 1, 1]},
            {"font": "tbl", "text": "B", "rgba": [1, 1, 1, 1]},
            {"font": "tbl", "text": "C", "rgba": [0, 0, 0, 1]},
            {"font": "", "text": "D", "rgba": [1, 0, 0, 1]},   # no font: skip
        ]},
        "/g/b.radium": {"texts": [
            {"font": "other", "text": "E", "rgba": [1.0, 0.4, 0.2, 1]}]},
    }
    tints = scene_render.text_tints(layouts)
    assert tints["tbl"] == {(255, 255, 255): 2, (0, 0, 0): 1}
    assert tints["other"] == {(255, 102, 51): 1}
    assert "" not in tints
    assert scene_render.text_tints({}) == {}


def test_render_missing_pieces_degrades_quietly():
    """No layout file, an unknown scene, and a layout whose assets are gone
    all yield None rather than raising or drawing a fake frame."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        empty = str(pathlib.Path(td) / "no_extract")
        os.makedirs(empty)
        assert scene_render.load_layouts(empty) == {}
        assert scene_render.render_scene(empty, "/g/s1/scene.radium") is None
        assets = _seed_preview_extract(pathlib.Path(td))
        assert scene_render.render_scene(assets, "/nope/scene.radium") is None
        os.remove(os.path.join(
            assets, "images", "scene_textures",
            "radimg_art_40x20_bbbb0002.png"))
        # the text still draws, so a frame is still produced
        assert scene_render.render_scene(assets,
                                        "/g/s1/scene.radium") is not None


def test_parse_folds_a_frame_sequence_into_one_animated_element():
    """Instances that share a position and image size but each draw a
    DIFFERENT image are an ANIMATION, not a pile: TMNT's jump is 42 images of
    600x768 all anchored at one spot, and compositing them made a smear."""
    imgs = [_fake_image(60, 600, 768), _fake_image(120, 600, 768),
            _fake_image(180, 600, 768)]
    head = _image_head([(60, 2), (120, 4), (180, 6)], head_len=320)
    tail = _sprite_scene([])
    for i, (off, h) in enumerate(((60, 2), (120, 4), (180, 6))):
        tail += _s_instance("frame%d" % i, 19.0, 63.0,
                            image_ref=_image_ref(600, 768, h))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert lay is not None
    assert len(lay["sprites"]) == 1, "frames must fold into one element"
    sp = lay["sprites"][0]
    assert sp["frames"] == [60, 120, 180]     # file order = play order
    assert sp["image_off"] == 60              # the still is frame one
    assert (sp["x"], sp["y"]) == (19.0, 63.0)


def test_child_instance_inherits_its_container_position():
    """A child's position is relative to its container.  TMNT's TV scene puts
    ~1900 static frames at (0,0) inside TVStaticLooping_Instance at
    (533, 296.5); drawing them at the stage origin jammed the TV into the
    top-left corner."""
    imgs = [_fake_image(60, 128, 108), _fake_image(120, 128, 108),
            _fake_image(180, 128, 108)]
    head = _image_head([(60, 2), (120, 4), (180, 6)], head_len=320)
    tail = _sprite_scene([])
    # the container: positioned, draws nothing itself (no image reference)
    tail += _s_instance("TVStaticLooping_Instance", 533.0, 296.5)
    for i, h in enumerate((2, 4, 6)):
        tail += _s_instance("child%d" % i, 0.0, 0.0,
                            image_ref=_image_ref(128, 108, h))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert lay is not None and lay["sprites"], "children should be placed"
    for sp in lay["sprites"]:
        assert (sp["x"], sp["y"]) == (533.0, 296.5)


def test_parse_keeps_one_of_several_overlapping_animations():
    """Two sequences of the same thing on top of each other are alternative
    takes, not layers: Leonardo's character-select holds a 600x768 standing pose
    AND a full-screen jump-kick, and playing both double-exposed him."""
    imgs = ([_fake_image(60 + 60 * i, 600, 768) for i in range(3)]
            + [_fake_image(300 + 60 * i, 1360, 768) for i in range(3)])
    head = _image_head([(60, 2), (120, 4), (180, 6),
                        (300, 8), (360, 10), (420, 12)], head_len=520)
    tail = _sprite_scene([])
    for i, h in enumerate((2, 4, 6)):
        tail += _s_instance("small%d" % i, 300.0, 0.0,
                            image_ref=_image_ref(600, 768, h))
    for i, h in enumerate((8, 10, 12)):
        tail += _s_instance("big%d" % i, 0.0, 0.0,
                            image_ref=_image_ref(1360, 768, h))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert lay is not None
    # one is DRAWN per state; the other is kept as the next state, not binned
    assert len(scene_render._visible(lay["sprites"], 0)) == 1
    assert len(scene_render._visible(lay["sprites"], 1)) == 1
    assert lay["alternates"] == 1 and lay["states"] == 2
    assert "one at a time" in scene_render.describe(lay)


def test_parse_collapses_repeated_pages_but_keeps_distinct_rows():
    """The high-score screen repeats one frame at seven overlapping positions
    (its carousel pages) and rendered as an unreadable pile — those collapse.
    Separate score rows barely overlap and must all survive."""
    imgs = [_fake_image(60, 944, 580)]
    head = _image_head([(60, 2)], head_len=320)
    tail = _sprite_scene([])
    # the real positions of three of those pages: nearly on top of each other
    for i, (x, y) in enumerate(((680.0, 522.0), (680.0, 538.3), (680.0, 529.0))):
        tail += _s_instance("page%d" % i, x, y,
                            image_ref=_image_ref(944, 580, 2))
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert len(scene_render._visible(lay["sprites"], 0)) == 1
    assert lay["alternates"] == 2 and lay["states"] == 3
    # each page is reachable, and they are the three distinct positions
    assert sorted(round(scene_render._visible(lay["sprites"], k)[0]["y"], 1)
                  for k in range(3)) == [522.0, 529.0, 538.3]

    # rows: same string, small boxes stacked 39px apart -> all kept
    rows = [("Row%d" % i, 136.0, 134.4 + 39 * i, "ABCDEFGHIJ") for i in range(3)]
    lay2 = scene_layout.parse_scene_layout(
        _radium(_text_scene(rows, rect=(25.0, 15.6, 238.0, 61.0))),
        [_fake_image(48)], [])
    assert len(lay2["texts"]) == 3 and lay2["alternates"] == 0
    assert lay2["states"] == 1               # nothing to step through


def test_parse_refines_origin_per_element_for_mixed_scenes():
    """Real scenes mix the two origins because elements hang off different
    parents: the high-score screen has rows at (680, 522) beside titles at
    (-347.5, 5.4).  Only the element whose BOX falls off the stage is re-read,
    so the one already on stage keeps its coordinates."""
    lines = [("OnStage", 300.0, 400.0, "HERE"),
             ("OffStage", -347.5, 5.4, "THERE")]
    lay = scene_layout.parse_scene_layout(
        _radium(_text_scene(lines, rect=(25.0, 15.6, 670.0, 78.2))),
        [_fake_image(48)], [])
    assert lay is not None and lay["origin"] == "mixed"
    got = {t["text"]: (t["x"], t["y"]) for t in lay["texts"]}
    assert got["HERE"] == (300.0, 400.0)                   # untouched
    assert got["THERE"] == pytest.approx((-347.5 + 680, 5.4 + 384), abs=1e-3)


def test_render_draws_one_frame_not_the_stack():
    """Rendering frame N shows exactly that frame — the bug David caught was
    every frame composited together."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        assets = _seed_preview_extract(root)
        st = root / "images" / "scene_textures"
        Image.new("RGBA", (40, 20), (0, 0, 255, 255)).save(st / "f2.png")
        path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
        with open(path, encoding="utf-8") as f:
            lay = json.load(f)
        sp = lay["/g/s1/scene.radium"]["sprites"][0]
        sp["frames"] = [sp["image"], "scene_textures/f2.png"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lay, f)
        one = lay["/g/s1/scene.radium"]
        assert scene_render.frame_count(one) == 2
        a = np.asarray(scene_render.render_layout(assets, one, frame=0))
        b = np.asarray(scene_render.render_layout(assets, one, frame=1))
        assert tuple(a[15, 30]) == (255, 0, 0)     # frame 1 = the red art
        assert tuple(b[15, 30]) == (0, 0, 255)     # frame 2 = the blue art
        # and the caption says it animates instead of claiming a still
        msg = scene_render.describe(one)
        assert "Animation: 2 frames" in msg
        assert "Animation isn't shown" not in msg


def test_render_aligns_text_by_the_keyframe_align_word():
    """align 0/1/2 = left/center/right.  Centering everything put the boot
    screen's left- and right-aligned lines in the wrong place."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        assets = _seed_preview_extract(root)
        path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
        with open(path, encoding="utf-8") as f:
            base = json.load(f)["/g/s1/scene.radium"]
        base["sprites"] = []                       # text only, easier to find
        xs = {}
        for align in (0, 1, 2):
            lay = json.loads(json.dumps(base))
            lay["texts"][0]["align"] = align
            a = np.asarray(scene_render.render_layout(assets, lay))
            cols = np.nonzero(a.max(axis=(0, 2)) > 200)[0]
            xs[align] = int(cols.min())
        assert xs[0] < xs[1] < xs[2], xs           # left, center, right


def test_frame_rate_uses_the_scenes_own_rate():
    """The stage header's rate is authored per scene (12/24/30/60 all occur on
    one card), so it is played as written — an old 20 fps cap made every 30 fps
    scene run at two thirds speed.  A nonsense stage still yields something
    playable, and 240 fps junk is still refused."""
    assert scene_render.frame_rate({"stage": [1360, 768, 30.0]}) == 30.0
    assert scene_render.frame_rate({"stage": [1360, 768, 60.0]}) == 60.0
    assert scene_render.frame_rate({"stage": [1360, 768, 24.0]}) == 24.0
    assert scene_render.frame_rate({"stage": [1360, 768, 12.0]}) == 12.0
    assert scene_render.frame_rate({"stage": [1360, 768, 0.0]}) == 12.0
    assert scene_render.frame_rate({"stage": [1360, 768, 1e9]}) == 12.0
    assert scene_render.frame_rate(None) == 12.0
    assert scene_render.frame_count(None) == 1


def test_describe_is_honest_about_animation():
    lay = {"stage": [1360, 768, 60.0], "texts": [{}, {}], "sprites": [{}],
           "partial": False}
    msg = scene_render.describe(lay)
    assert "1 image" in msg and "2 text lines" in msg
    assert "1360x768" in msg
    # A still picture must not imply there is animation being withheld — the
    # old wording said "Animation isn't shown" on every static scene, which
    # read as a missing feature rather than a scene that simply doesn't move.
    assert "Still picture" in msg and "nimation" not in msg
    assert scene_render.describe(None) == "No preview for this scene."


# ---------------------------------------------------------------------------
# Parent/child membership in the node tree
# ---------------------------------------------------------------------------

def test_parse_composes_a_child_onto_its_parents_position():
    """A child's coordinates are measured from its PARENT, not the screen.

    TMNT's boot screen is the proof: "VERIFYING IMAGE" sits at (355.95, 7.6)
    inside a ProgressBar at (80, 372.8).  Read as screen coordinates its
    baseline is 7.6, so the whole line drew above the top edge; composed it
    lands at (435.95, 380.4), on the bar where it belongs."""
    data = _radium(_framed_scene(
        [("ProgressBar", 80.0, 372.8, 1, None, b""),
         ("Text", 355.95, 7.6, 0, "VERIFYING IMAGE", b"")],
        root_kids=1))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None and lay["origin"] == "topleft"
    t = lay["texts"][0]
    assert (t["x"], t["y"]) == pytest.approx((435.95, 380.4), abs=1e-3)
    assert lay["offstage"] == 0


def test_parse_falls_back_when_the_child_counts_do_not_add_up():
    """A hierarchy guessed from a misparse would move elements silently, so
    anything that doesn't close out exactly is read as a flat list instead —
    the same coordinates this module used before membership was decoded."""
    good = [("ProgressBar", 80.0, 372.8, 1, None, b""),
            ("Text", 355.95, 7.6, 0, "VERIFYING IMAGE", b"")]
    # the parent claims 5 children but only one follows it
    data = _radium(_framed_scene(good, root_kids=1, kid_counts=[5, 0]))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None
    assert (lay["texts"][0]["x"], lay["texts"][0]["y"]) == \
        pytest.approx((355.95, 7.6), abs=1e-3)


def test_parse_drops_a_repeated_page_with_its_whole_subtree():
    """Alternative states are whole subtrees.  TMNT's high-score screen draws
    a team list and a co-op list over the same panel; dropping only the
    duplicate frame left the second list's lines orphaned against the corner,
    which was the debris on every busy preview."""
    page = lambda tag, dy: [                                    # noqa: E731
        ("%s_Frame" % tag, 680.0, 300.0 + dy, 2, None, b""),
        ("%s_Title" % tag, -260.0, -99.15, 0, "%s TITLE" % tag, b""),
        ("%s_Name" % tag, -347.5, 5.4, 0, "%s NAME" % tag, b"")]
    nodes = page("HS", 0.0) + page("COOP", 8.0)
    data = _radium(_framed_scene(nodes, root_kids=2,
                                 rect=(-322.5, -40.0, 322.5, 40.0)))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None
    got = sorted(t["text"] for t in scene_render._visible(lay["texts"], 0))
    assert got == ["HS NAME", "HS TITLE"], "the repeat should go as one unit"
    assert lay["alternates"] == 2 and lay["states"] == 2
    # ...and the co-op page is the SECOND state, whole, not debris
    assert sorted(t["text"] for t in scene_render._visible(lay["texts"], 1)) \
        == ["COOP NAME", "COOP TITLE"]


def test_parse_group_node_does_not_borrow_the_scenes_only_image():
    """A node with children carries the transform its children hang off, not
    art.  Falling back to "this scene has exactly one image, so draw that" made
    the high-score frames paint the backdrop a second time in the corner."""
    imgs = [_fake_image(60, 40, 20)]
    head = _image_head([(60, 2)])
    tail = _framed_scene(
        [("Group", 300.0, 200.0, 1, None, b""),
         ("Child", 20.0, 10.0, 0, None, _image_ref(40, 20, 2))],
        root_kids=1)
    lay = scene_layout.parse_scene_layout(head + tail, imgs, [])
    assert lay is not None
    assert [(s["name"], s["x"], s["y"]) for s in lay["sprites"]] == [
        ("Child", 320.0, 210.0)]


def test_parse_keeps_the_visible_half_of_an_outline_fill_pair():
    """A Stern title is an outline instance followed by a fill instance at the
    same spot.  The outline is tinted pure BLACK, and ink is composited
    additively, so keeping it drew nothing at all — TMNT's AWARD popup rendered
    as an empty frame until the LAST of a duplicate pair won."""
    data = _radium(_framed_scene(
        [("AwardTitle", 700.0, 400.0, 2, None, b""),
         ("Instance_AwardTitle_Outline", 0.0, 0.0, 0, "AWARD", b""),
         ("Instance_AwardTitle", 0.0, 0.0, 0, "AWARD", b"")],
        root_kids=1))
    lay = scene_layout.parse_scene_layout(data, [_fake_image(48)], [])
    assert lay is not None
    assert [t["name"] for t in lay["texts"]] == ["Instance_AwardTitle"]


# ---------------------------------------------------------------------------
# Rebuilding the layouts alone (without re-extracting anything)
# ---------------------------------------------------------------------------

def _pad4(x):
    return ((x + 3) // 4) * 4


def _radium_with_image(data_off, handle, w, h, tail=b""):
    """A radium whose one inline BC3 block puts its pixel data at *data_off* —
    the offset ``radium_images.txt`` records — with *tail* (the node graph)
    after it.  Field order is the documented intro block:
    ``[dispW][dispH][HANDLE][texW][texH][fmt 5][0][0][len][data]``."""
    length = _pad4(w) * _pad4(h)
    m = data_off - 16                    # where the fmt,0,0 anchor sits
    buf = bytearray(m)
    struct.pack_into("<I", buf, m - 20, w)                    # dispW
    struct.pack_into("<I", buf, m - 16, h)                    # dispH
    struct.pack_into("<I", buf, m - 12, 0x80000000 | handle)  # introducer
    struct.pack_into("<I", buf, m - 8, w)                     # texW
    struct.pack_into("<I", buf, m - 4, h)                     # texH
    buf += struct.pack("<3I", 5, 0, 0) + struct.pack("<I", length)
    buf += bytes(length)
    return bytes(buf) + tail


class _FakeCardReader:
    """The ``Ext4Reader`` surface ``rebuild_scene_layouts`` uses: walk the
    card's files, read one whole."""

    def __init__(self, files):
        self._files = files                   # [(card path, bytes)]

    def iter_regular_files(self, min_size=1):
        for i, (path, data) in enumerate(self._files):
            yield path, i, {"size": len(data), "idx": i}

    def read_file_bytes(self, node):
        return self._files[node["idx"]][1]


def _rebuild_card():
    """A card holding the one scene ``_seed_preview_extract`` describes: its
    art image at the offset that folder's manifest names, drawn by one sprite
    instance."""
    tail = _sprite_scene([]) + _s_instance(
        "Art", 300.0, 200.0, image_ref=_image_ref(40, 20, 7))
    return _FakeCardReader([("/g/s1/scene.radium",
                             _radium_with_image(200, 7, 40, 20, tail))])


def test_rebuild_rewrites_only_the_layout_file(tmp_path):
    """A parser change has to reach an existing project folder WITHOUT a full
    re-extract: that would take minutes and overwrite every atlas PNG and
    glyph slice, silently throwing away an imported font.  The rebuild reads
    the node graphs alone and writes exactly one file."""
    from pinball_decryptor.plugins.stern import engine
    assets = _seed_preview_extract(tmp_path)
    # a font import, i.e. the work a re-extract would destroy
    slice_png = (tmp_path / "images" / "scene_textures" / "glyphs"
                 / "radimg_font_64x64_aaaa0001" / "U+0041_A.png")
    Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(slice_png)

    def snap():
        out = {}
        base = os.path.join(assets, "images")
        for dirpath, _d, files in os.walk(base):
            for fn in files:
                p = os.path.join(dirpath, fn)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, base)] = f.read()
        return out

    before = snap()
    n = engine.rebuild_scene_layouts(_rebuild_card(), assets)
    assert n == 1
    after = snap()
    assert set(before) == set(after)
    changed = [k for k in before if before[k] != after[k]]
    assert changed == [os.path.join("scene_textures", "scene_layout.json")]

    # and it is a real re-parse: the sprite is placed from the card, resolved
    # through the manifest to the project folder's own PNG
    lay = scene_render.load_layouts(assets)["/g/s1/scene.radium"]
    assert lay["stage"] == [1360, 768, 60.0]
    assert [(s["name"], s["x"], s["y"], s["image"]) for s in lay["sprites"]] \
        == [("Art", 300.0, 200.0,
             "scene_textures/radimg_art_40x20_bbbb0002.png")]


def test_rebuild_needs_the_image_manifest_and_says_so(tmp_path):
    """Without ``radium_images.txt`` there is nothing to resolve an image
    offset against, and inventing PNG names would produce layouts that draw
    nothing.  It declines with a reason instead."""
    from pinball_decryptor.plugins.stern import engine
    assets = _seed_preview_extract(tmp_path)
    os.remove(os.path.join(assets, "images", "scene_textures",
                           "radium_images.txt"))
    logs = []
    n = engine.rebuild_scene_layouts(
        _rebuild_card(), assets, log=lambda m, lvl="info": logs.append((m, lvl)))
    assert n == 0
    assert any(lvl == "warning" and "radium_images.txt" in m
               for m, lvl in logs)


def test_rebuild_stops_on_cancel_without_writing(tmp_path):
    """Cancelling leaves the previous layouts in place rather than a
    half-written file."""
    from pinball_decryptor.plugins.stern import engine
    assets = _seed_preview_extract(tmp_path)
    path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
    with open(path, "rb") as f:
        before = f.read()
    assert engine.rebuild_scene_layouts(_rebuild_card(), assets,
                                        cancel=lambda: True) == 0
    with open(path, "rb") as f:
        assert f.read() == before


def test_rebuild_translation_is_the_extracts_own(tmp_path):
    """Both paths go through ``_scene_layout_entry``, so a layout can never
    mean one thing at extract and another at rebuild."""
    from pinball_decryptor.plugins.stern import engine
    lay = {"stage": (1360, 768, 60.0), "origin": "topleft", "partial": False,
           "unplaced": 0, "offstage": 0, "alternates": 0,
           "texts": [{"name": "L", "x": 1.0, "y": 2.0, "text": "HI",
                      "rect": [0, 0, 10, 10], "rgba": [1, 1, 1, 1],
                      "align": 1, "font_atlas_off": 100}],
           "sprites": [{"name": "A", "x": 3.0, "y": 4.0, "image_off": 200,
                        "frames": [200, 300]}]}
    off2rel = {100: "scene_textures/atlas_stem.png",
               200: "scene_textures/f1.png", 300: "scene_textures/f2.png"}
    entry = engine._scene_layout_entry(lay, off2rel)
    assert entry["texts"][0]["font"] == "atlas_stem"
    assert entry["sprites"][0]["image"] == "scene_textures/f1.png"
    assert entry["sprites"][0]["frames"] == ["scene_textures/f1.png",
                                             "scene_textures/f2.png"]
    # a scene whose images are all missing from the manifest draws nothing
    assert engine._scene_layout_entry(
        {**lay, "texts": []}, {}) is None


def test_layout_for_scene_dir_matches_the_browsers_grouping():
    """The Scenes window groups by directory; the manifest is keyed by the
    radium's full path."""
    layouts = {"/g/lcd/abc123/scene.radium": {"stage": [1, 2, 3]}}
    card, lay = scene_render.layout_for_scene_dir(layouts, "/g/lcd/abc123")
    assert card == "/g/lcd/abc123/scene.radium" and lay is not None
    assert scene_render.layout_for_scene_dir(layouts, "/g/lcd/zzz") == (None,
                                                                       None)


def test_sprite_centres_on_its_anchor_only_when_top_left_cannot_work():
    """Almost all art hangs off its anchor's top-left corner (657 of TMNT's
    712 placed sprites land fully on stage that way, including the verified
    LAIR banner, which is CLIPPED if centred).  A few cannot: a full-screen
    image anchored at the stage centre only makes sense centred.

    There is no per-sprite pivot field to read — an instance can carry its box
    as four floats at body+133, but exactly 2 of those 712 do — so this is
    geometric and one-way: mostly OFF the stage as written AND fully ON when
    centred, or it doesn't fire."""
    stage = (1360, 768)
    dims = {60: (1360, 768), 120: (572, 500), 180: (100, 100)}
    # full-screen art anchored at the stage centre -> re-read from the centre
    full = {"x": 679.95, "y": 383.9, "image_off": 60}
    # the LAIR anchor: fits as top-left, so it must NOT move
    lair = {"x": 395.0, "y": 127.0, "image_off": 120}
    # half off the right edge either way -> neither reading is good, leave it
    edge = {"x": 1340.0, "y": 700.0, "image_off": 180}
    sprites = [full, lair, edge]
    n = scene_layout._refine_sprite_pivots(sprites, stage, dims)
    assert n == 1
    assert (full["x"], full["y"]) == pytest.approx((-0.05, -0.1), abs=1e-3)
    assert (lair["x"], lair["y"]) == (395.0, 127.0)
    assert (edge["x"], edge["y"]) == (1340.0, 700.0)
    # an unknown image size can never be re-read
    unknown = [{"x": 5000.0, "y": 5000.0, "image_off": 999}]
    assert scene_layout._refine_sprite_pivots(unknown, stage, dims) == 0


def test_a_scrolling_scene_is_described_as_one_not_as_broken():
    """A credits roll is taller than the screen ON PURPOSE.  Led Zeppelin's
    spans 17,684px of a 768-high stage — 23 screens — and calling its
    off-stage lines "positions we couldn't decode" said the preview was broken
    when it was right.  That one scene held 208 of the card's 218 off-stage
    elements."""
    stage = (1360, 768)
    rows = [{"x": 400.0, "y": -2000.0 + i * 120.0} for i in range(20)]
    assert scene_layout._scroll_axis(rows, [], stage) == "vertical"
    strip = [{"x": -1500.0 + i * 200.0, "y": 300.0} for i in range(20)]
    assert scene_layout._scroll_axis(strip, [], stage) == "horizontal"
    # an ordinary screenful is not a scroll, and neither is a handful of
    # elements that happen to spread (a real strip has a column of them)
    normal = [{"x": 100.0 + i * 50.0, "y": 100.0 + i * 30.0} for i in range(20)]
    assert scene_layout._scroll_axis(normal, [], stage) == ""
    assert scene_layout._scroll_axis(rows[:3], [], stage) == ""

    lay = {"stage": [1360, 768, 30.0], "texts": [{}] * 20, "sprites": [],
           "offstage": 17, "scroll": "vertical", "partial": True}
    msg = scene_render.describe(lay)
    assert "scrolls through the screen" in msg
    assert "isn't fully decoded" not in msg
    # without the flag the honest admission is still there
    lay["scroll"] = ""
    assert "isn't fully decoded" in scene_render.describe(lay)
