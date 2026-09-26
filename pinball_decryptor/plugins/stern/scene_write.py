"""WRITE nodes into a Spike 2 ``scene.radium``: a screen of a mode's OWN (item 131).

EMULATOR-PROVEN on Godzilla Pro 1.15 (2026-09-16), NOT hardware-proven: a Sprite
node carrying a Bitmap with a texture the card never had and a Text with our own
string, spliced into the in-game HUD scene ``32e6ae28``, draws over a game on the
Tokyo map. KAIJU RUSH's ``mode.so`` finds it by name, keeps it hidden until the mode
runs, shows it and rewrites its words live ("+1,000,000", "TOTAL 3,000,000") with the
game's own set-text, then hides it. No message id is borrowed.

WHY THIS REPLACED THE FIRST VERSION OF THIS MODULE. That version emitted a whole
scene from structural words lifted from one TMNT scene; it rebuilt that scene
byte-for-byte and the game aborted on everything else it wrote. Four boots of hand
insertions then "rejected an added node" until an instrument - ``modes/scenelog.c``,
which records every read cereal's ``PortableBinaryInputArchive`` makes - showed that
each of them had simply put the bytes in the wrong place. The grammar below is what
the GAME read, not what a parser inferred, and the emitters rebuild real stock nodes
byte-for-byte (see the tests).

THE GRAMMAR (strings ``[u64 len][latin1]``; ids u32, top bit set on first occurrence)::

    node       u32 ptr id | name | u32 flag
               | keyframes [u64 n] n x (u32 frame, u8 visible)
               | list [u64 0]
               | tracks [u64 n] n x (u32 key, 64 B column-major 4x4 matrix, glass px, y down)
               | components [u64 n] n x (u32 start frame, u32 poly type, u32 object id, body)
               | frame map [u64 0]
    Sprite     u32 symbol | name | u32 frame count | [u64 n][children] | u64
               | labels [u64 n] n x (name, u32 frame)
    Bitmap     u32 symbol | name | u32 w | u32 h | texture
    texture    u32 id (bare = a reference) or, first time: u32 id | w | h | u32 format
               (5 BC3, 4 BC1) | "" | u32 length | blob
    Text       u32 symbol | name | f32 left top right bottom | f32 r g b a | u8 u8
               | u32 align | f32 f32 | text | u32 font | [u64 1](font name, u32 font)
               | [u64 1](u32 font, u8, u32)

A group's children live INSIDE its Sprite body, and a child ends at its own frame
map; the root is itself Sprite data. The polymorphic TYPE ids, symbol keys and font ids
are per file (attract registers Sprite 2 / Bitmap 3 / Text 5, the HUD scene Bitmap 1 /
Sprite 2 / Text 4), so they come from a :class:`SceneProfile` measured on that exact
file and keyed by its md5. A file without a profile is refused, never guessed at.

DRAWN = KEYFRAMES AND A CODE FLAG. Code can hide a node (vfn ``+0xa8``) but not reveal
one its timeline hides, so a screen is authored visible and the mode hides it. That is
also this format's one hazard: **a scene written here must never be installed without
the mode.so that hides it**, or the screen stays on the glass all game.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

import numpy as np

from . import dds as _dds

FLAG = 0x80000000
BC3, BC1 = 5, 4


class SceneWriteError(ValueError):
    """The scene is not one this module has measured, or does not look like it."""


# ---- encoding --------------------------------------------------------------------
def u32(v):
    return struct.pack("<I", v & 0xFFFFFFFF)


def u64(v):
    return struct.pack("<Q", v)


def string(s):
    b = s.encode("latin1") if isinstance(s, str) else bytes(s)
    return u64(len(b)) + b


def matrix(sx=1.0, sy=1.0, tx=0.0, ty=0.0):
    """The 64-byte track transform: column-major 4x4, translation at [12] and [13]."""
    return struct.pack("<16f", sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, 1, 0, tx, ty, 0, 1)


def node(ptr_id, name, flag, keyframes, tracks, components):
    """One node. ``keyframes`` = [(frame, visible)], ``tracks`` = [(key, 64-byte
    matrix)], ``components`` = [(start frame, poly type, object id, body)]."""
    out = u32(ptr_id) + string(name) + u32(flag)
    out += u64(len(keyframes)) + b"".join(struct.pack("<IB", f, 1 if v else 0) for f, v in keyframes)
    out += u64(0)
    out += u64(len(tracks))
    for key, m in tracks:
        if len(m) != 64:
            raise SceneWriteError("a track matrix is 64 bytes, got %d" % len(m))
        out += u32(key) + m
    out += u64(len(components)) + b"".join(u32(k) + (t if isinstance(t, bytes) else u32(t)) + u32(o) + body
                                           for k, t, o, body in components)
    out += u64(0)
    return out


def sprite_body(symbol, children, frames=1, name=""):
    """A group's data: its children inline, and no labels."""
    return (u32(symbol) + string(name) + u32(frames) + u64(len(children)) + b"".join(children)
            + u64(0) + u64(0))


def texture_ref(tid):
    return u32(tid)


def texture_new(tid, w, h, blob, fmt=BC3):
    pad = ((w + 3) // 4 * 4) * ((h + 3) // 4 * 4)
    want = pad if fmt == BC3 else pad // 2
    if len(blob) != want:
        raise SceneWriteError("a %dx%d format-%d texture is %d bytes, got %d" % (w, h, fmt, want, len(blob)))
    return u32(FLAG | tid) + u32(w) + u32(h) + u32(fmt) + string("") + u32(len(blob)) + blob


def bitmap_body(symbol, w, h, texture, name=""):
    return u32(symbol) + string(name) + u32(w) + u32(h) + texture


def text_body(symbol, ltrb, rgba, text, font_id, font_name, align, spacing, tail_flag, tail_u32,
              flags=(0, 0), name=""):
    out = u32(symbol) + string(name) + struct.pack("<4f", *ltrb) + struct.pack("<4f", *rgba)
    out += struct.pack("<BB", *flags) + u32(align) + struct.pack("<2f", *spacing)
    out += string(text) + u32(font_id)
    out += u64(1) + string(font_name) + u32(font_id)
    out += u64(1) + u32(font_id) + struct.pack("<B", tail_flag) + u32(tail_u32)
    return out


# ---- what was measured, per file ----------------------------------------------------------
@dataclass(frozen=True)
class SceneProfile:
    """Everything about ONE stock scene file that a screen needs, read off a boot."""
    label: str
    scene_id: str
    tree: str                 # auto_loaded / demand_loaded
    md5: str
    size: int
    poly: dict                # {"sprite": n, "bitmap": n, "text": n}
    symbol: dict              # symbol keys of this file's own nodes of each kind
    font: tuple               # (font object id, font name); None: the screen has no words line (no font in the file)
    text_align: int
    text_spacing: tuple
    text_tail: tuple          # (u8, u32) after the font reference
    root_frames: int
    root_count_at: int
    root_count: int
    insert_at: int            # a root child's ptr id: the previous child ends here
    insert_before: tuple      # (ptr id, name) found at insert_at
    first_free_id: int
    in_game: bool             # drawn during play; attract scenes are not
    append: bytes = b""       # item 164: insert AFTER the last root child (drawn last, on top) - insert_at is
                              # then the root's trailer, and these are its bytes (checked in place of a child)
    origin: tuple = (0.0, 0.0)  # item 164: where the scene's own (0, 0) is on the glass (a nested scene the game
                              # places: Deadpool's score card sits at 742, 424) - a screen's x, y are glass pixels
    new_poly: tuple = ()      # classes the file never registered (item 164: Avengers' HUD has no Bitmap):
                              # the first screen registers each inline, u32 FLAG|id + its name, as the game does
    video: tuple = ()         # item 164: (class id, symbol key) a grafted Video takes (:func:`add_screens`
                              # ``clips``) - a free class id and one past the library's highest key
    words_font: tuple = ()    # item 164: (Font class id, symbol key) for the card's full system font, carried
                              # in because this file's own fonts lack the words' glyphs (:func:`carried_font`)


PROFILES = {
    "f9daed5a19aafc807bf9eb3c2def6c27": SceneProfile(
        label="godzilla Pro 1.15 in-game HUD slide-outs",
        scene_id="32e6ae280ddaec08e203a02289bb39a04968e7b0", tree="auto_loaded",
        md5="f9daed5a19aafc807bf9eb3c2def6c27", size=943999,
        poly={"sprite": 2, "bitmap": 1, "text": 4},
        symbol={"sprite": 19, "bitmap": 16, "text": 5},
        font=(9, "GameFont_Primary"), text_align=1, text_spacing=(2.0, 0.0), text_tail=(1, 1),
        root_frames=1, root_count_at=0x0E16E1, root_count=3,
        insert_at=0x0E4BE3, insert_before=(0x800000D3, "BattleSlideOut_Artbox"),
        first_free_id=0x100, in_game=True),
    "c36dd5f54a876772e4a109320a44830e": SceneProfile(
        label="godzilla Pro 1.15 attract (not drawn during a game)",
        scene_id="394c4a037fb26e12f536c42b2677bfed831f5c98", tree="demand_loaded",
        md5="c36dd5f54a876772e4a109320a44830e", size=5290876,
        poly={"sprite": 2, "bitmap": 3, "text": 5},
        symbol={"sprite": 11, "bitmap": 5, "text": 10},
        font=(16, "GameFont_Primary"), text_align=2, text_spacing=(2.0, 2.0), text_tail=(1, 2),
        root_frames=269, root_count_at=0x500C0C, root_count=51,
        insert_at=0x50B350, insert_before=(0x800008AF, "SternLogo"),
        first_free_id=2237, in_game=False),
    "53c9a69e39abf2dbb54fd134afe68b01": SceneProfile(
        label='Aerosmith LE 1.15 in-game 11ce95fe (item 164, read statically)',
        scene_id='11ce95fe13add22617598c5e7afbcc0f8356be9b', tree='auto_loaded',
        md5='53c9a69e39abf2dbb54fd134afe68b01', size=3765880,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 17, 'bitmap': 30, 'text': 17},
        font=(290, 'Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0x391250, root_count=6,
        insert_at=0x39731F, insert_before=(0x80000380, 'BallInPlay_Instance'),
        first_free_id=0x400, in_game=True),
    "62614053077f96e15d4d3d89a88d8a20": SceneProfile(
        label='Avengers: Infinity Quest LE 1.09 in-game 6cd5668f (item 164, read statically)',
        scene_id='6cd5668f1f8189d6aa5e79203f12a0d0a4c90038', tree='auto_loaded',
        md5='62614053077f96e15d4d3d89a88d8a20', size=660715,
        poly={'sprite': 2, 'text': 4, 'bitmap': 5},
        symbol={'sprite': 8, 'bitmap': 8, 'text': 6},
        font=(8, 'BlambotOrange_HVY'), text_align=1, text_spacing=(0.0, 0.0), text_tail=(1, 0),
        root_frames=1, root_count_at=0xA0B6F, root_count=1,
        insert_at=0xA0B77, insert_before=(0x8000005E, 'InfoText'),
        first_free_id=0x100, in_game=True, new_poly=('bitmap',)),
    "fe7ab9c3143f1db4ebf9c917df8b47fe": SceneProfile(
        label='The Beatles 1.29 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821/68f53edf22edb8b5fb918e77ebb222a139a6a0e6', tree='auto_loaded',
        md5='fe7ab9c3143f1db4ebf9c917df8b47fe', size=12751382,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 1074, 'bitmap': 324, 'text': 1124},
        font=(10100, 'WonderBarOutline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=10, root_count_at=0xA93771, root_count=58,
        insert_at=0xC28EA5, insert_before=(0x800077CF, 'NetUser4'),
        first_free_id=0x7900, in_game=True, words_font=(3, 1639)),
    "ab5a66fa89ef57cfe38b7820978cc08c": SceneProfile(
        label='Deadpool LE 1.14 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821/7bae43761f538dd582c19f3973bcedcc2b7ab6dd', tree='auto_loaded',
        md5='ab5a66fa89ef57cfe38b7820978cc08c', size=1012821,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 30, 'bitmap': 24, 'text': 28},
        font=(117, 'Stern_GovtAgentBB_BlackOutline'), text_align=0, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0xF2985, root_count=1,
        insert_at=0xF298D, insert_before=(0x80000214, 'Counters_Main'),
        first_free_id=0x300, in_game=True, origin=(742.0, 424.0)),
    "d447242dd58e9a5d1271bf98516465ce": SceneProfile(
        label='Deadpool Pro 1.16 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821/7bae43761f538dd582c19f3973bcedcc2b7ab6dd', tree='auto_loaded',
        md5='d447242dd58e9a5d1271bf98516465ce', size=1012821,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 30, 'bitmap': 24, 'text': 28},
        font=(117, 'Stern_GovtAgentBB_BlackOutline'), text_align=0, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0xF2985, root_count=1,
        insert_at=0xF298D, insert_before=(0x80000214, 'Counters_Main'),
        first_free_id=0x300, in_game=True),
    "f1b87fa9a6f94cddc4aca6268dcd96ea": SceneProfile(
        label='Guardians of the Galaxy LE 1.14 in-game 4853b69e (item 164, read statically)',
        scene_id='4853b69e9fd122157772aaac5db81948331def2b', tree='auto_loaded',
        md5='f1b87fa9a6f94cddc4aca6268dcd96ea', size=12338348,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 103, 'bitmap': 102, 'text': 129},
        font=(10, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0xA4916B, root_count=34,
        insert_at=0xBC0AEF, insert_before=(0x8000144B, 'SpellOutInstance'),
        first_free_id=0x1600, in_game=True),
    "9b6a1b230e2dcfe050606a7d7bb4c283": SceneProfile(
        label='Iron Maiden LE 1.16 in-game 7b4db7ef (item 164, read statically)',
        scene_id='7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a', tree='auto_loaded',
        md5='9b6a1b230e2dcfe050606a7d7bb4c283', size=2880083,
        poly={'bitmap': 2, 'text': 3, 'sprite': 4},
        symbol={'sprite': 55, 'bitmap': 59, 'text': 86},
        font=(341, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(1, 0),
        root_frames=8, root_count_at=0x2B7261, root_count=19,
        insert_at=0x2BEE8F, insert_before=(0x800008B8, 'NetUser4'),
        first_free_id=0x900, in_game=True, video=(6, 103)),
    "aa4caf7b0c0a142f39d8c62388601dd1": SceneProfile(
        label='John Wick LE 1.01 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='aa4caf7b0c0a142f39d8c62388601dd1', size=5438300,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 71, 'bitmap': 27, 'text': 74},
        font=(126, 'Stern_LeagueGothic_Italic_Glyph_Outline_4'), text_align=0, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0x50A345, root_count=10,
        insert_at=0x52F975, insert_before=(0x80001303, 'NetUser4'),
        first_free_id=0x1400, in_game=True),
    "cf8da03fa56cd71e414702db70b6aa3d": SceneProfile(
        label='King Kong LE 0.97 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='cf8da03fa56cd71e414702db70b6aa3d', size=61713020,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 385, 'bitmap': 353, 'text': 797},
        font=(654, 'Stern_Aztech_whiteWBlackOutline'), text_align=0, text_spacing=(0.0, 0.0), text_tail=(1, 0),
        root_frames=1, root_count_at=0x3A8EE4E, root_count=10,
        insert_at=0x3AD8863, insert_before=(0x8000244D, 'MonsterIcons_Slidein_Instance'),
        first_free_id=0x2500, in_game=True),
    "52c8fb8417a3ee2442bc31e12563b6fa": SceneProfile(
        label='Led Zeppelin LE 1.22 in-game 7b4db7ef (item 164, read statically)',
        scene_id='7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a', tree='auto_loaded',
        md5='52c8fb8417a3ee2442bc31e12563b6fa', size=7850500,
        poly={'bitmap': 1, 'text': 4, 'sprite': 5},
        symbol={'sprite': 158, 'bitmap': 156, 'text': 93},
        font=(624, 'Stern_PollockOne_Outline_8'), text_align=0, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0x71B999, root_count=23,
        insert_at=0x77C0FF, insert_before=(0x80001E86, 'BallAndCredits_Instance'),
        first_free_id=0x1F00, in_game=True),
    "b8745c86480a44976d95068a7dc773f2": SceneProfile(
        label='Led Zeppelin Pro 1.22 in-game 7b4db7ef (item 164, read statically)',
        scene_id='7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a', tree='auto_loaded',
        md5='b8745c86480a44976d95068a7dc773f2', size=7850500,
        poly={'bitmap': 1, 'text': 4, 'sprite': 5},
        symbol={'sprite': 158, 'bitmap': 156, 'text': 93},
        font=(624, 'Stern_PollockOne_Outline_8'), text_align=0, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0x71B999, root_count=23,
        insert_at=0x77C0FF, insert_before=(0x80001E86, 'BallAndCredits_Instance'),
        first_free_id=0x1F00, in_game=True),
    "7b8d6f595c97a76e16bf54bee5d10007": SceneProfile(
        label='The Mandalorian LE 1.44 in-game 6742a6fa (item 164, read statically)',
        scene_id='6742a6fac556d32c1c4ff0f672ab7a513ac8bafd', tree='auto_loaded',
        md5='7b8d6f595c97a76e16bf54bee5d10007', size=12363928,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 53, 'bitmap': 32, 'text': 133},
        font=(1472, 'Stern_AgencyFB_Outline4'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0xBB8B71, root_count=34,
        insert_at=0xBCA61F, insert_before=(0x80001217, 'NetUser4'),
        first_free_id=0x1300, in_game=True),
    "809cbf843c36555ddbda41c3b4909543": SceneProfile(
        label='Metallica Remastered 1.03 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='809cbf843c36555ddbda41c3b4909543', size=6658819,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 10, 'bitmap': 6, 'text': 18},
        font=(860, 'Stern_DharmaGothicPBold_Glyphs_StoneLighten'), text_align=2, text_spacing=(2.0, -2.0), text_tail=(0, 0),
        root_frames=6, root_count_at=0x63D32B, root_count=30,
        insert_at=0x65973C, insert_before=(0x80000E1E, 'Balls_Instance_ConcertMode'),
        first_free_id=0xF00, in_game=True, video=(6, 174), words_font=(1, 175)),
    "9869621883a18ce97bd3446d67dfbbff": SceneProfile(
        label='The Munsters LE 1.28 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='9869621883a18ce97bd3446d67dfbbff', size=8957731,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 14, 'bitmap': 13, 'text': 143},
        font=(627, 'Blackmoor_Outline_Thick'), text_align=1, text_spacing=(-22.0, 0.0), text_tail=(0, 0),
        root_frames=3, root_count_at=0x85E6FA, root_count=18,
        insert_at=0x88ACC2, insert_before=(0x80000E7A, 'BallInPlayAnimation'),
        first_free_id=0xF00, in_game=True, video=(5, 163)),
    "a516ede995deda83619a4d57469a8760": SceneProfile(
        label='Rush LE 1.18 in-game 28aff8e6 (item 164, read statically)',
        scene_id='28aff8e66e7c61dc4722a30ee31e22d1afe094d6/efd9321ee61c0467eaaecb1369842d69eed4a6aa', tree='auto_loaded',
        md5='a516ede995deda83619a4d57469a8760', size=1312338,
        poly={'text': 2, 'sprite': 3, 'bitmap': 5},
        symbol={'sprite': 20, 'bitmap': 19, 'text': 21},
        font=(196, 'Stern_Impact_Outline_4'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x1320F1, root_count=11,
        insert_at=0x13F321, insert_before=(0x80000290, 'Panel_Instance'),
        first_free_id=0x300, in_game=True),
    "315de4afdec66df3ea56cc64b5673a95": SceneProfile(
        label='Stranger Things LE 1.12 in-game 8d4b1e7a (item 164, read statically)',
        scene_id='8d4b1e7add4280a7790929a643df09196c28c29f', tree='auto_loaded',
        md5='315de4afdec66df3ea56cc64b5673a95', size=1895728,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 18, 'bitmap': 36, 'text': 33},
        font=(293, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0x1BF9F0, root_count=5,
        insert_at=0x1CE7A7, insert_before=(0x8000069E, 'BallAndCredits_Instance'),
        first_free_id=0x700, in_game=True),
    "ff7ed4a354fd8f5565250ea1411ef2ed": SceneProfile(
        label='Sword of Rage LE 1.18 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='ff7ed4a354fd8f5565250ea1411ef2ed', size=39291900,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 33, 'bitmap': 169, 'text': 388},
        font=(720, 'Stern_DuskTillDawn_score'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(1, 0),
        root_frames=4, root_count_at=0x253D931, root_count=31,
        insert_at=0x2578A0C, insert_before=(0x80001D3A, 'NetUser4'),
        first_free_id=0x1E00, in_game=True),
    "e9a5916df0d6c41510453c83e1dd6fb8": SceneProfile(
        label='TMNT Pro 1.59 in-game 297053bb (item 164, read statically)',
        scene_id='297053bbcfae2550c2caeee5a28b70634acf9126/dbfc32cef3a745637ee4e6f03a7461a7f63df3ed', tree='auto_loaded',
        md5='e9a5916df0d6c41510453c83e1dd6fb8', size=2319302,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 8, 'bitmap': 1, 'text': 3},
        font=(100, 'Stern_Impact_Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x235DED, root_count=1,
        insert_at=0x235DF5, insert_before=(0x8000019F, 'CountdownBox'),
        first_free_id=0x200, in_game=True),
    "0d31df0d25052d0ec251c18d5b8b33a1": SceneProfile(
        label='Uncanny X-Men LE 0.98 in-game 0da52941 (item 164, read statically)',
        scene_id='0da52941985fea0ac31857f47794e990638156bb', tree='auto_loaded',
        md5='0d31df0d25052d0ec251c18d5b8b33a1', size=20890201,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 354, 'bitmap': 353, 'text': 378},
        font=(2748, 'Stern_ComicAvengers_RedWWhiteDropBlackOutLn'), text_align=1, text_spacing=(0.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0x139F133, root_count=57,
        insert_at=0x13E2E15, insert_before=(0x800013D5, 'BishopMeter_Instance'),
        first_free_id=0x1600, in_game=True),
    "a337459aee72b3ec5dc9b0a50981e16d": SceneProfile(
        label='TMNT LE 1.59 in-game 297053bb (item 164, read statically)',
        scene_id='297053bbcfae2550c2caeee5a28b70634acf9126/dbfc32cef3a745637ee4e6f03a7461a7f63df3ed', tree='auto_loaded',
        md5='a337459aee72b3ec5dc9b0a50981e16d', size=2319302,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 8, 'bitmap': 1, 'text': 3},
        font=(100, 'Stern_Impact_Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x235DED, root_count=1,
        insert_at=0x235DF5, insert_before=(0x8000019F, 'CountdownBox'),
        first_free_id=0x200, in_game=True),
    "3f34991c6809a039dd47b2086a12937a": SceneProfile(
        label='Foo Fighters LE 1.04 in-game 2c8ffcac (item 164, read statically)',
        scene_id='2c8ffcac48035d12ef91df61fb7a796ec391f1e7', tree='auto_loaded',
        md5='3f34991c6809a039dd47b2086a12937a', size=2177265,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 22, 'bitmap': 6, 'text': 15},
        font=(108, 'Stern_Komika_OutlineWhite'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x20BCD2, root_count=1,
        insert_at=0x20BCDA, insert_before=(0x8000015A, 'mystery_instance'),
        first_free_id=0x400, in_game=True),
    "629ec55571a6651b53ce72cfdbfc1cf6": SceneProfile(
        label='James Bond 60th LE 1.11 in-game 4f25684e (item 164, read statically)',
        scene_id='4f25684e54b3be073912d2878b2fb0e3e778d703/0f1e6208e1b4f62cb09f9c089aadd48173e0ef0f', tree='auto_loaded',
        md5='629ec55571a6651b53ce72cfdbfc1cf6', size=188072,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 11, 'bitmap': 10, 'text': 15},
        font=(16, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x2BE23, root_count=2,
        insert_at=0x2DD8F, insert_before=(0x8000007B, 'BarText_Instance'),
        first_free_id=0x200, in_game=True),
    "2714280910e8768b6a17dba50fb150f7": SceneProfile(
        label='Jaws LE 1.02 in-game 9d578751 (item 164, read statically)',
        scene_id='9d57875196c613785a1eee010c55223a0f1aa821', tree='auto_loaded',
        md5='2714280910e8768b6a17dba50fb150f7', size=11987106,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 47, 'bitmap': 176, 'text': 235},
        font=(1142, 'GameFont_Primary'), text_align=2, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=5, root_count_at=0xAFC30A, root_count=27,
        insert_at=0xB6E777, insert_before=(0x80001420, 'unnamed_instance_150'),
        first_free_id=0x1A00, in_game=True),
    "5a57df0fc5f2f441faf8f5a6b012c277": SceneProfile(
        label='Jurassic Park LE 1.16 in-game 7b4db7ef (item 164, read statically)',
        scene_id='7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a', tree='auto_loaded',
        md5='5a57df0fc5f2f441faf8f5a6b012c277', size=11335988,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 35, 'bitmap': 61, 'text': 107},
        font=(1206, 'Stern_JP'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0xAB4C3C, root_count=42,
        insert_at=0xACF7AB, insert_before=(0x80000AAD, 'NetUser4'),
        first_free_id=0xD00, in_game=True),
    "0b5daf037e8e2c4d203c9ce502e0ce3a": SceneProfile(
        label='Dungeons & Dragons LE 1.00 in-game e3ff23bf (item 164, read statically)',
        scene_id='e3ff23bf818995a58895b4115c3cc054c9ab76c7', tree='auto_loaded',
        md5='0b5daf037e8e2c4d203c9ce502e0ce3a', size=55089234,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 349, 'bitmap': 16, 'text': 548},
        font=(171, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=77, root_count_at=0x344F5B3, root_count=77,
        insert_at=0x3488D88, insert_before=(0x00000000, ''),
        first_free_id=0x1600, in_game=True, append=b'\x00\x00\x00\x00\x00\x00\x00\x00M\x00\x00\x00\x00\x00\x00\x00'),
    "2191bafeae511328ebf5448ace320642": SceneProfile(
        label='Star Wars LE 1.30 in-game a7c4bd2b (item 164, read statically)',
        scene_id='a7c4bd2b9e8c4da706a7de59cbd189a8f715deee', tree='auto_loaded',
        md5='2191bafeae511328ebf5448ace320642', size=574784,
        poly={'sprite': 2, 'bitmap': 3, 'text': 5},
        symbol={'sprite': 8, 'bitmap': 6, 'text': 10},
        font=(23, ''), text_align=1, text_spacing=(0.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x89B07, root_count=11,
        insert_at=0x8C530, insert_before=(0x00000000, ''),
        first_free_id=0x300, in_game=True, append=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'),
    "30f53700c4425924355ecc70e345452a": SceneProfile(
        label='Venom LE 1.07 in-game e3ff23bf (item 164, read statically)',
        scene_id='e3ff23bf818995a58895b4115c3cc054c9ab76c7', tree='auto_loaded',
        md5='30f53700c4425924355ecc70e345452a', size=19463989,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 9, 'bitmap': 79, 'text': 11},
        font=(313, 'Stern_Impact_Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=38, root_count_at=0x127480E, root_count=39,
        insert_at=0x128FB13, insert_before=(0x00000000, ''),
        first_free_id=0x1300, in_game=True, append=b'\x00\x00\x00\x00\x00\x00\x00\x00&\x00\x00\x00\x00\x00\x00\x00'),
    "fda0fad4bd0931e1412872f85a232834": SceneProfile(
        label='Elvira 1.13 in-game fb70914f (item 164, read statically)',
        scene_id='fb70914f6b52e9c3d8f2db191946bbafe87ae44f', tree='auto_loaded',
        md5='fda0fad4bd0931e1412872f85a232834', size=1262581,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 8, 'bitmap': 6, 'text': 3},
        font=(105, 'Stern_HouseofTerror_OutlineWhite'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x131178, root_count=7,
        insert_at=0x133CB2, insert_before=(0x8000012C, 'Per_Instance7'),
        first_free_id=0x400, in_game=True, video=(5, 9), words_font=(1, 10)),
    "832c77c669803d557c730a3be09fb9e5": SceneProfile(
        label='James Bond 007 LE 1.06 in-game 6fb39344 (item 164, read statically)',
        scene_id='6fb393447ae7e3c2e1c629efff24bd1991ac1368/7de1c1596973efa1e95d16d7cb9229f4c6d36db9', tree='auto_loaded',
        md5='832c77c669803d557c730a3be09fb9e5', size=431326,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 3, 'bitmap': 2, 'text': 8},
        font=(19, 'Stern_Montserrat_EX_WhiteOnBlack'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(1, 0),
        root_frames=1, root_count_at=0x65F98, root_count=2,
        insert_at=0x6612C, insert_before=(0x80000137, 'StatusBar_Instance'),
        first_free_id=0x200, in_game=True),
    "322b14238d0351d6e6ddeb6333e07c8a": SceneProfile(
        label='Batman 66 1.13 in-game b59deafd (item 164, read statically)',
        scene_id='b59deafd663e85b406a4d490cd2b2bdf8efcf13a', tree='auto_loaded',
        md5='322b14238d0351d6e6ddeb6333e07c8a', size=14082343,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 267, 'bitmap': 124, 'text': 229},
        font=(817, 'Batman66_Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0xCCAE50, root_count=14,
        insert_at=0xD67B03, insert_before=(0x8000193C, 'FourPlayerGame'),
        first_free_id=0x1B00, in_game=True, video=(6, 293)),
    "e8bbe9670a9a212f18408a602d7b187b": SceneProfile(
        label='Dungeons & Dragons LE 1.00 in-game b237b728 (item 164, read statically)',
        scene_id='b237b7288453dee42f8299bea3fb57de90e6e473', tree='auto_loaded',
        md5='e8bbe9670a9a212f18408a602d7b187b', size=416609,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 28, 'bitmap': 1, 'text': 26},
        font=(44, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x5B419, root_count=8,
        insert_at=0x6466B, insert_before=(0x8000025C, 'Coin8_Instance'),
        first_free_id=0x300, in_game=True),
    "6ad2d6fb45a03892f43675a9faf8d1ac": SceneProfile(
        label='Star Wars LE 1.30 in-game 9db420cf (item 164, read statically)',
        scene_id='9db420cfd5ec648153ce2e0f17dfcbc3a6b43df6', tree='auto_loaded',
        md5='6ad2d6fb45a03892f43675a9faf8d1ac', size=2521218,
        poly={'bitmap': 1, 'sprite': 2, 'text': 4},
        symbol={'sprite': 9, 'bitmap': 1, 'text': 46},
        font=(155, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x25B1C6, root_count=2,
        insert_at=0x261802, insert_before=(0x80000365, 'TIEfighter2'),
        first_free_id=0x500, in_game=True),
    "2a91907fb78f42cb8eb224ba4322548d": SceneProfile(
        label='Venom LE 1.07 in-game a5a5ca3d (item 164, read statically)',
        scene_id='a5a5ca3d705d93c2e9b3e01a7cd075363f5a6319', tree='auto_loaded',
        md5='2a91907fb78f42cb8eb224ba4322548d', size=1293145,
        poly={'bitmap': 1, 'text': 3, 'sprite': 4},
        symbol={'sprite': 11, 'bitmap': 1, 'text': 12},
        font=(295, 'Stern_Impact_Outline'), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x13A773, root_count=2,
        insert_at=0x13B161, insert_before=(0x80000294, 'PopUp1'),
        first_free_id=0x300, in_game=True),
    "f3fab9b27b70ee2f2bfc067da0d847d8": SceneProfile(
        label='James Bond 60th LE 1.11 in-game 852c03a3 (item 164, read statically)',
        scene_id='852c03a30ec326f25f1848f433dcdc00804ef373', tree='auto_loaded',
        md5='f3fab9b27b70ee2f2bfc067da0d847d8', size=140993,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 3, 'bitmap': 4, 'text': 2},
        font=(2, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x22353, root_count=2,
        insert_at=0x224CF, insert_before=(0x80000072, 'Player1'),
        first_free_id=0x300, in_game=True),
    "354935f6d901c89105d1a97edd4a559e": SceneProfile(
        label='Star Wars ELG 1.10 in-game 7b4db7ef (item 164, read statically)',
        scene_id='7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a/835949dafb924a7cfeb0ec0fe2a3a4d8696d4aea', tree='auto_loaded',
        md5='354935f6d901c89105d1a97edd4a559e', size=18946356,
        poly={'bitmap': 2, 'sprite': 3, 'text': 4},
        symbol={'sprite': 63, 'bitmap': 9, 'text': 116},
        font=(798, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=4, root_count_at=0x11F384D, root_count=10,
        insert_at=0x1208CB9, insert_before=(0x80000D86, 'IconGroup4_Instance'),
        first_free_id=0x1100, in_game=True, origin=(280.0, 40.0)),
    "2ce488d819e6f9d8b02e2e28ebc284e0": SceneProfile(
        label='Deadpool LE 1.14 in-game c3328c39 (item 164, read statically)',
        scene_id='c3328c39b0e29f78e9ff45db674248b1d245887d/0d167902e97be9e342b1950754601e41c79f615e', tree='auto_loaded',
        md5='2ce488d819e6f9d8b02e2e28ebc284e0', size=931434,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 74, 'bitmap': 74, 'text': 67},
        font=(26, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0xE0E66, root_count=23,
        insert_at=0xE349D, insert_before=(0x8000008E, 'TextBox100pt_Instance0'),
        first_free_id=0x100, in_game=True, new_poly=('bitmap',), words_font=(1, 75)),
    "2039fc21e598c672fa4d45df2283178b": SceneProfile(
        label='Deadpool Pro 1.16 in-game c3328c39 (item 164, read statically)',
        scene_id='c3328c39b0e29f78e9ff45db674248b1d245887d/0d167902e97be9e342b1950754601e41c79f615e', tree='auto_loaded',
        md5='2039fc21e598c672fa4d45df2283178b', size=931434,
        poly={'text': 2, 'sprite': 3, 'bitmap': 4},
        symbol={'sprite': 74, 'bitmap': 74, 'text': 67},
        font=(26, ''), text_align=1, text_spacing=(2.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0xE0E66, root_count=23,
        insert_at=0xE349D, insert_before=(0x8000008E, 'TextBox100pt_Instance0'),
        first_free_id=0x100, in_game=True, new_poly=('bitmap',), words_font=(1, 75)),
    "37d90179d849daf5afcbe4db0cf1cf1d": SceneProfile(
        label='James Bond 60th LE 1.11 in-game 91b06583 (item 164, read statically)',
        scene_id='91b0658329efa06d4da89c23a162b41dfcee5202', tree='auto_loaded',
        md5='37d90179d849daf5afcbe4db0cf1cf1d', size=1539463,
        poly={'bitmap': 1, 'sprite': 2, 'text': 3},
        symbol={'sprite': 8, 'bitmap': 1, 'text': 1},
        font=None, text_align=0, text_spacing=(0.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x177706, root_count=2,
        insert_at=0x177BFD, insert_before=(0x80000027, 'frame_instance'),
        first_free_id=0x600, in_game=True, new_poly=('text',), origin=(280.0, 40.0), video=(4, 9)),
    "6f3c2dbd6a176794ca54794f41f699fd": SceneProfile(
        label='Jurassic Park Pin 1.05 in-game 60ed7e50 (item 164, read statically)',
        scene_id='60ed7e5036b8ce09d35a3e101ea6fc1380b37d97', tree='auto_loaded',
        md5='6f3c2dbd6a176794ca54794f41f699fd', size=14097,
        poly={'sprite': 2, 'bitmap': 3, 'text': 4},
        symbol={'sprite': 0, 'bitmap': 0, 'text': 1},
        font=None, text_align=0, text_spacing=(0.0, 0.0), text_tail=(0, 0),
        root_frames=1, root_count_at=0x23A3, root_count=1,
        insert_at=0x3701, insert_before=(0x00000000, ''),
        first_free_id=0x100, in_game=True, new_poly=('sprite', 'bitmap', 'text'), append=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', origin=(0.0, -124.0)),
}


def profile_for(data):
    md5 = hashlib.md5(data).hexdigest()
    p = PROFILES.get(md5)
    if p is None:
        raise SceneWriteError("no measured profile for a scene with md5 %s; read it off a boot "
                              "with modes/scenelog.c first (scenelog.want)" % md5)
    return p


def check(data, p):
    """Refuse unless the bytes are where the profile says."""
    if len(data) != p.size:
        raise SceneWriteError("%s: expected %d bytes, got %d" % (p.label, p.size, len(data)))
    if struct.unpack_from("<Q", data, p.root_count_at)[0] != p.root_count:
        raise SceneWriteError("%s: root child count is not %d" % (p.label, p.root_count))
    if struct.unpack_from("<I", data, p.root_count_at - 4)[0] != p.root_frames:
        raise SceneWriteError("%s: root frame count is not %d" % (p.label, p.root_frames))
    at = p.insert_at
    if p.append:
        if data[at:at + len(p.append)] != p.append:
            raise SceneWriteError("%s: 0x%x is not the root's trailer" % (p.label, at))
        return
    ptr, name = p.insert_before
    if struct.unpack_from("<I", data, at)[0] != ptr or data[at + 12:at + 12 + len(name)] != name.encode():
        raise SceneWriteError("%s: 0x%x is not the ptr id of %s" % (p.label, at, name))


def screen(p, name, art_rgba, words, x, y, words_at=None, words_rgba=(1.0, 0.9, 0.0, 1.0),
           art_name=None, words_name=None):
    """A root Sprite ``name`` holding an art Bitmap (our texture) and a words Text,
    named ``<name>_Art`` / ``<name>_Words`` unless given. Returns (bytes, the seven
    object ids it uses)."""
    art_name = art_name or name + "_Art"
    words_name = words_name or name + "_Words"
    art = np.asarray(art_rgba, dtype=np.uint8)
    if art.ndim != 3 or art.shape[2] != 4:
        raise SceneWriteError("art must be an (h, w, 4) RGBA array")
    h, w = art.shape[:2]
    if w % 4 or h % 4:
        raise SceneWriteError("art is %dx%d; BC3 wants both sides a multiple of 4" % (w, h))
    blob = _dds.encode_bc3(art)
    ids = list(range(p.first_free_id, p.first_free_id + 7))
    names = {"sprite": "Sprite", "bitmap": "Bitmap", "text": "Text"}
    poly = {k: (u32(FLAG | v) + string(names[k]) if k in p.new_poly else v) for k, v in p.poly.items()}
    p_group, o_group, p_art, o_art, tex, p_txt, o_txt = ids
    wx, wy = words_at if words_at is not None else (20.0, h + 50.0)
    art_node = node(FLAG | p_art, art_name, 1, [(1, 1)], [(1, matrix())],
                    [(1, poly["bitmap"], FLAG | o_art,
                      bitmap_body(p.symbol["bitmap"], w, h, texture_new(tex, w, h, blob)))])
    kids = [art_node]
    if p.font:          # item 164: a scene with no Text of its own (Bond 60th's frame) has no font to use
        kids.append(node(FLAG | p_txt, words_name, 1, [(1, 1)], [(1, matrix(tx=wx, ty=wy))],
                         [(1, poly["text"], FLAG | o_txt,
                           text_body(p.symbol["text"], (0.0, -40.0, float(w), 48.0), words_rgba, words,
                                     p.font[0], p.font[1], p.text_align, p.text_spacing, *p.text_tail))]))
    group = node(FLAG | p_group, name, 1, [(1, 1)], [(1, matrix(tx=x - p.origin[0], ty=y - p.origin[1]))],
                 [(1, poly["sprite"], FLAG | o_group,
                   sprite_body(p.symbol["sprite"], kids))])
    return group, ids


def add_screen(data, name, art_rgba, words, x=360.0, y=200.0, words_at=None,
               art_name=None, words_name=None):
    """Splice a screen into a profiled stock scene. Returns (new bytes, info) where info
    names what the mode file needs: ``screen_scene``, ``screen_node``, ``screen_text``."""
    new, infos = add_screens(data, [dict(name=name, art_rgba=art_rgba, words=words, x=x, y=y,
                                         words_at=words_at, art_name=art_name,
                                         words_name=words_name)])
    info = dict(infos[0])
    info["md5"] = hashlib.md5(new).hexdigest()
    return new, info


def _rebased(p, stock, data):
    """``p`` (measured on ``stock``) moved onto ``data``: the same scene after other edits that
    only INSERTED bytes before the profile's two offsets - a clip added to the video bank when
    the bank is also the scene a screen goes in (item 164: JP The Pin 1.05 draws one scene, its
    video bank). Each offset is found again by the stock bytes around it, which must appear
    exactly once in the window the growth allows."""
    grow = len(data) - len(stock)
    if grow < 0:
        raise SceneWriteError("%s: the edited scene is smaller than the stock one" % p.label)

    def moved(at, after):
        for width in (16, 64, 256, 1024):       # a trailer of zeros matches at several shifts
            lo = max(0, at - width)
            key = stock[lo:at + after]
            hits = [i for i in range(lo, lo + grow + 1) if data[i:i + len(key)] == key]
            if len(hits) == 1:
                return hits[0] + (at - lo)
        raise SceneWriteError("%s: 0x%x is not one place in the edited scene" % (p.label, at))

    return SceneProfile(**{**p.__dict__, "size": len(data),
                           "root_count_at": moved(p.root_count_at, 8),
                           "insert_at": moved(p.insert_at, max(len(p.append), 16))})


# ---- item 164: a VIDEO grafted into a scene with none --------------------------------------
# Some titles draw no video bank in play (The Munsters' bank 69db8744 is its attract background),
# so a clip added there plays and is never seen. The HUD scene IS drawn, so the clip goes in it,
# in the grammar of a stock bank (video_bank.py): one more LIBRARY entry - the Video, registered
# with each clip's path and size - and one more root child, the Sprite "PadMode_Clips", holding a
# node "VideoSurface" whose component names the same clips by bare id. The runtime's clip route
# finds "PadMode_Clips.VideoSurface" on the scene the port's `scene video_bank` names (`value
# clip_surface_hide 1`), and hides the Sprite while no clip plays: a surface keeps a finished clip's
# last frame on the glass, and a VideoSurface is no Sprite, so it cannot be hidden itself (the
# Sprite's visibility slot crashes the game on it - emulator, The Munsters 2026-09-26). The library
# is ``u8 1 | [u64 n] entries``, and after it come ``u64 0`` and the stage (u32 w, u32 h, f32 fps,
# f32 rgba) just before the root.
VIDEO_NODE = "VideoSurface"
VIDEO_GROUP = "PadMode_Clips"


def _stage_at(data, p):
    """The stage's offset: the root (u32 symbol | name | u32 frames | u64 count) ends at
    ``p.root_count_at``, and the stage's 28 bytes and a u64 0 are before it."""
    for n in range(0, 65):
        name_at = p.root_count_at - 4 - n - 8
        if name_at >= 40 and struct.unpack_from("<Q", data, name_at)[0] == n:
            at = name_at - 4 - 28
            w, h = struct.unpack_from("<II", data, at)
            if struct.unpack_from("<Q", data, at - 8)[0] == 0 and 64 <= w <= 4096 and 64 <= h <= 4096:
                return at
    raise SceneWriteError("%s: no stage before the root" % p.label)


def grafts_video(data):
    """True when ``data`` is a profiled scene a Video can be grafted into."""
    p = PROFILES.get(hashlib.md5(data).hexdigest())
    return bool(p and p.video)


def video_size(data):
    """(w, h) of a profiled scene's stage: the size a clip grafted into it is made at."""
    p = profile_for(data)
    return struct.unpack_from("<II", data, _stage_at(data, p))


def _video_body(symbol, name, w, h, entries):
    return (u32(symbol) + string(name) + u32(w) + u32(h) + u32(1) + b"\0"
            + u64(len(entries)) + b"".join(entries) + u64(0))


def _graft(p, data, clips, ids):
    """(library entry, node) for ``clips`` [(name, path, size)] with object ids from ``ids``."""
    if not p.video:
        raise SceneWriteError("%s: no Video can be grafted into it (no class id measured)" % p.label)
    if string(VIDEO_GROUP) in data:
        raise SceneWriteError("%s: the scene already has a %s" % (p.label, VIDEO_GROUP))
    if "sprite" in p.new_poly:
        raise SceneWriteError("%s: the scene registers no Sprite to hold a Video" % p.label)
    poly, key = p.video
    reg = struct.pack("<I", FLAG | poly)            # a class registration: FLAG|id, then its name
    registered = False                              # the file's own Video class (Batman's HUD) is used
    at = data.find(reg)
    while 0 <= at < len(data) - 13:
        n = struct.unpack_from("<Q", data, at + 4)[0]
        if 3 <= n <= 24 and data[at + 12:at + 13].isupper():
            if data[at + 12:at + 12 + n] != b"Video":
                raise SceneWriteError("%s: class id %d is already registered" % (p.label, poly))
            registered = True
        at = data.find(reg, at + 1)
    w, h = struct.unpack_from("<II", data, _stage_at(data, p))
    clips = sorted(clips, key=lambda c: c[0].encode("latin1"))     # a std::map, sorted by name
    if len({c[0] for c in clips}) != len(clips):
        raise SceneWriteError("two clips share a name")
    o_lib, p_node, o_comp, p_group, o_group = ids[:GRAFT_IDS]
    cid = {c[0]: ids[GRAFT_IDS + i] for i, c in enumerate(clips)}
    name = "video.pad_mode_clips"
    lib = (u32(key) + (u32(poly) if registered else u32(FLAG | poly) + string("Video")) + u32(FLAG | o_lib)
           + _video_body(key, name, w, h, [string(c) + u32(FLAG | cid[c]) + string(path) + u32(size)
                                           for c, path, size in clips]))
    surf = node(FLAG | p_node, VIDEO_NODE, 1, [(1, 1)], [(1, matrix())],
                [(1, poly, FLAG | o_comp, _video_body(key, name, w, h,
                                                      [string(c) + u32(cid[c]) for c, _p, _s in clips]))])
    # at the scene's own (0, 0): the Video fills the scene's stage, wherever the game places the scene
    group = node(FLAG | p_group, VIDEO_GROUP, 1, [(1, 1)], [(1, matrix())],
                 [(1, p.poly["sprite"], FLAG | o_group, sprite_body(p.symbol["sprite"], [surf]))])
    return lib, group


#: object ids a graft takes before its clips': the Video, the surface node and its component, the
#: Sprite node and its component
GRAFT_IDS = 5


# ---- item 164: a FULL font carried into a scene whose own fonts lack the glyphs -------------
# A scene embeds only the glyphs its own text uses: Deadpool's HUD fonts hold " 0x", Metallica's
# digits, The Beatles' no space or comma. Every card also carries the framework's system scenes, and
# one of them opens its library with a complete font (HelveticaNeueBlack, 114 glyphs), so that entry
# is copied from the card into the HUD's library and the screen's words use it. Its grammar (walked
# to its last byte on the card)::
#
#     entry   u32 key | class (FLAG|id + "Font", or the bare id) | u32 FLAG|font id | Font
#     Font    u32 key | name | face | u8 | u8 | [u64 n] u16 chars | [u64 s] sizes | u64 0
#     size    u32 | u32 FLAG|size id | u32 the font's KEY | f32 f32 f32 | u8 | [u64 g] glyphs
#     glyph   u16 char | u32 FLAG|glyph id | 7 f32 | u8 | 4 f32 (uv) | page | u64 0
#     page    u32 bare id (0: none), or a texture on its first use (texture_new's grammar)
#
# (A HUD's own fonts end in named style variants - "Stern_GovtAgentBB_BlackOutline" - where the
# system font's tail is empty.) A Text names no Font: its font field is one SIZE object's id, and
# its name map the variant ("" = the base sizes) - Deadpool's words use id 26, its HUD font's fifth
# size. So the words take the carried size nearest 50 px of line height. Every object id in the
# entry is renumbered from ``base`` up (they must not meet the HUD's own), the pages' bare
# references with them, and the key where the entry and its sizes name it.
SYSTEM_FONT_SCENE = ("assets/lcd/demand_loaded/bc0792d8dc81e8aa30b987246a5ce97c40cd6833/"
                     "0d349f5f898e96d26e5ecefebe09b3344ba50424/scene.radium")
FONT_ID_GAP = 0x800           # the carried font's ids start this far past the profile's first free id
WORDS_LINE = 50.0             # the line height (px) the words' size is chosen nearest to


class _Walk:
    def __init__(self, d, o):
        self.d, self.o = d, o
        self.ids, self.pages, self.keys, self.sizes = [], [], [], []

    def take(self, fmt):
        v = struct.unpack_from(fmt, self.d, self.o)
        self.o += struct.calcsize(fmt)
        return v[0] if len(v) == 1 else v

    def string(self):
        n = self.take("<Q")
        if n > 4096:
            raise SceneWriteError("the system font does not walk: a %d-byte string at 0x%x" % (n, self.o))
        self.o += n
        return self.d[self.o - n:self.o]

    def new(self):
        v = self.take("<I")
        if not v & FLAG:
            raise SceneWriteError("the system font does not walk: no new object at 0x%x" % (self.o - 4))
        self.ids.append((self.o - 4, v & ~FLAG))

    def page(self):
        v = self.take("<I")
        if not v & FLAG:
            if v:
                self.pages.append((self.o - 4, v))
            return
        self.ids.append((self.o - 4, v & ~FLAG))
        w, h, fmt = self.take("<3I")
        self.string()
        n = self.take("<I")
        self.o += n


def _walk_font(d, o=9):
    """Walk the font entry at ``o``: (key, class bytes span, face, end, walk)."""
    w = _Walk(d, o)
    key = w.take("<I")
    cls_at = w.o
    if w.take("<I") & FLAG and w.string() != b"Font":
        raise SceneWriteError("the system scene's first library entry is not a Font")
    cls_end = w.o
    w.new()
    w.keys.append(w.o)
    if w.take("<I") != key:
        raise SceneWriteError("the system font's key does not repeat")
    w.string()
    face = w.string().decode("latin1")
    w.o += 2
    n = w.take("<Q")
    w.o += 2 * n
    for _ in range(w.take("<Q")):
        w.o += 4
        w.new()
        w.keys.append(w.o)
        if w.take("<I") != key:
            raise SceneWriteError("a system font size does not name its font")
        w.sizes.append((w.ids[-1][1], struct.unpack_from("<f", d, w.o)[0]))
        w.o += 13
        for _ in range(w.take("<Q")):
            w.o += 2
            w.new()
            w.o += 29 + 16
            w.page()
            if w.take("<Q"):
                raise SceneWriteError("a system font glyph has a list the walk does not know")
    if w.take("<Q"):
        raise SceneWriteError("the system font has a tail the walk does not know")
    return key, (cls_at, cls_end), face, w.o, w


def carried_font(source, font_class, key, base):
    """The system scene's font as a library entry of another scene: (entry bytes, the id of the
    size the words use, its variant name ""). ``font_class`` is that scene's own Font class id,
    ``key`` a free symbol key, ``base`` the first of the object ids it takes."""
    if not source or source[0] != 1:
        raise SceneWriteError("the system font's scene is not a scene")
    old_key, (cls_at, cls_end), _face, end, w = _walk_font(source)
    if not w.sizes:
        raise SceneWriteError("the system font has no sizes")
    top = max(i for _a, i in w.ids)
    if sorted(i for _a, i in w.ids) != list(range(1, top + 1)):
        raise SceneWriteError("the system font's object ids are not 1..%d" % top)
    patch = {a: FLAG | (base + i - 1) for a, i in w.ids}
    patch.update({a: base + i - 1 for a, i in w.pages})
    patch.update({a: key for a in w.keys})
    out = bytearray(source[cls_end:end])
    for at, v in patch.items():
        struct.pack_into("<I", out, at - cls_end, v)
    size_id = min(w.sizes, key=lambda s: abs(s[1] - WORDS_LINE))[0]
    return u32(key) + u32(font_class) + bytes(out), base + size_id - 1, ""


def add_screens(data, screens, stock=None, clips=None, font_source=None):
    """Splice SEVERAL screens into a profiled stock scene in one pass (item 127: a card
    carries several modes, item 133 - and this refuses any file that is not the measured
    stock one, so screens cannot be added one call at a time). ``screens`` is a list of
    dicts of :func:`screen`'s arguments (``name``, ``art_rgba``, ``words``, and optionally
    ``x``, ``y``, ``words_at``, ``art_name``, ``words_name``). Each takes the next seven
    object ids and becomes one more root child, in order. Returns (new bytes, [info]).

    ``stock`` is given when ``data`` is that stock scene already grown by insertions of
    another kind (a clip: :func:`_rebased`); the profile is the stock one's.

    ``clips`` ([(name, path under scene.assets, file size)]) grafts a Video into the scene (item
    164, :func:`_graft`): a root child ``VideoSurface`` before the screens, which play over it.
    The info then carries ``video_scene``. Screens may be empty when clips are given.

    ``font_source`` (the card's :data:`SYSTEM_FONT_SCENE`) carries its full font into a scene whose
    profile names ``words_font``, and the screens' words use it (:func:`carried_font`).

    Every screen is authored visible, and every one needs the mode.so that hides it."""
    if stock is None:
        p = profile_for(data)
        check(data, p)
    else:
        p = profile_for(stock)
        check(stock, p)
        p = _rebased(p, stock, data)
        check(data, p)
    if not screens and not clips:
        raise SceneWriteError("no screens to add")
    names = [s["name"] for s in screens]
    if len(set(names)) != len(names):
        raise SceneWriteError("two screens share a name: %r" % names)
    libs, font = [], {}
    if p.words_font and font_source and screens:
        entry, size_id, variant = carried_font(font_source, p.words_font[0], p.words_font[1],
                                               p.first_free_id + FONT_ID_GAP)
        libs.append(entry)
        font = {"font": (size_id, variant)}
    groups, infos = [], []
    for i, s in enumerate(screens):
        words_name = s.get("words_name") or s["name"] + "_Words"
        sub = SceneProfile(**{**p.__dict__, "first_free_id": p.first_free_id + 7 * i, **font,
                              "new_poly": p.new_poly if i == 0 else ()})       # registered once, by the first
        group, ids = screen(sub, s["name"], s["art_rgba"], s["words"], s.get("x", 360.0),
                            s.get("y", 200.0), s.get("words_at"), art_name=s.get("art_name"),
                            words_name=words_name)
        for nid in ids:
            if struct.pack("<I", FLAG | nid) in data:
                raise SceneWriteError("%s: object id 0x%x is already used" % (p.label, nid))
        if string(s["name"]) in data:
            raise SceneWriteError("%s: a node called %s is already in the scene" % (p.label, s["name"]))
        groups.append(group)
        infos.append({
            "screen_scene": p.scene_id, "screen_node": s["name"],
            "screen_text": s["name"] + "." + words_name,
            "tree": p.tree, "in_game": p.in_game, "node_bytes": len(group),
        })
    if clips:
        base = p.first_free_id + 7 * len(screens)
        ids = list(range(base, base + GRAFT_IDS + len(clips)))
        for nid in ids:
            if struct.pack("<I", FLAG | nid) in data:
                raise SceneWriteError("%s: object id 0x%x is already used" % (p.label, nid))
        entry, surf = _graft(p, data, clips, ids)
        libs.append(entry)
        groups.insert(0, surf)
        infos.append({"video_scene": p.scene_id, "tree": p.tree, "node_bytes": len(surf)})
    lib = b"".join(libs)
    lib_at = _stage_at(data, p) - 8 if lib else p.root_count_at
    new = (bytearray(data[:lib_at]) + lib + bytearray(data[lib_at:p.insert_at]) + b"".join(groups)
           + bytearray(data[p.insert_at:]))
    struct.pack_into("<Q", new, p.root_count_at + len(lib), p.root_count + len(groups))
    if lib:
        if new[0] != 1:
            raise SceneWriteError("%s: the library does not start at byte 1" % p.label)
        struct.pack_into("<Q", new, 1, struct.unpack_from("<Q", new, 1)[0] + len(libs))
    return bytes(new), infos
