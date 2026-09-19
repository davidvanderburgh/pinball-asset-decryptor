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
    out += u64(len(components)) + b"".join(u32(k) + u32(t) + u32(o) + body for k, t, o, body in components)
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
    font: tuple               # (font object id, font name)
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
    ptr, name = p.insert_before
    at = p.insert_at
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
    p_group, o_group, p_art, o_art, tex, p_txt, o_txt = ids
    wx, wy = words_at if words_at is not None else (20.0, h + 50.0)
    art_node = node(FLAG | p_art, art_name, 1, [(1, 1)], [(1, matrix())],
                    [(1, p.poly["bitmap"], FLAG | o_art,
                      bitmap_body(p.symbol["bitmap"], w, h, texture_new(tex, w, h, blob)))])
    words_node = node(FLAG | p_txt, words_name, 1, [(1, 1)], [(1, matrix(tx=wx, ty=wy))],
                      [(1, p.poly["text"], FLAG | o_txt,
                        text_body(p.symbol["text"], (0.0, -40.0, float(w), 48.0), words_rgba, words,
                                  p.font[0], p.font[1], p.text_align, p.text_spacing, *p.text_tail))])
    group = node(FLAG | p_group, name, 1, [(1, 1)], [(1, matrix(tx=x, ty=y))],
                 [(1, p.poly["sprite"], FLAG | o_group,
                   sprite_body(p.symbol["sprite"], [art_node, words_node]))])
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


def add_screens(data, screens):
    """Splice SEVERAL screens into a profiled stock scene in one pass (item 127: a card
    carries several modes, item 133 - and this refuses any file that is not the measured
    stock one, so screens cannot be added one call at a time). ``screens`` is a list of
    dicts of :func:`screen`'s arguments (``name``, ``art_rgba``, ``words``, and optionally
    ``x``, ``y``, ``words_at``, ``art_name``, ``words_name``). Each takes the next seven
    object ids and becomes one more root child, in order. Returns (new bytes, [info]).

    Every screen is authored visible, and every one needs the mode.so that hides it."""
    p = profile_for(data)
    check(data, p)
    if not screens:
        raise SceneWriteError("no screens to add")
    names = [s["name"] for s in screens]
    if len(set(names)) != len(names):
        raise SceneWriteError("two screens share a name: %r" % names)
    groups, infos = [], []
    for i, s in enumerate(screens):
        words_name = s.get("words_name") or s["name"] + "_Words"
        sub = SceneProfile(**{**p.__dict__, "first_free_id": p.first_free_id + 7 * i})
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
    new = bytearray(data[:p.insert_at]) + b"".join(groups) + bytearray(data[p.insert_at:])
    struct.pack_into("<Q", new, p.root_count_at, p.root_count + len(screens))
    return bytes(new), infos
