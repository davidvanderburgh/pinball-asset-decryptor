"""How big the game shows each video slot, and the size a replacement clip goes on the card at (Simon,
2026-11-21: "Same as pictures").

Simon: "We need to make a decision about video soon - can it be brought in higher resolution? I think the answer
is the same override and warnings - VERY unlikely someone should ever bring in a video - but there could be a
table that zooms into a video so it may be important."

A Spike 2 scene plays its clips in a ``Video`` component: a box (``w`` x ``h``, the clip's own size on every
stock clip - 626 clips 1360x768, 32 of 520x294 on Godzilla 1.16) on a node the scene can zoom.  Godzilla's main
in-game player (nearly every clip) zooms to 1.32x, the city maps to 1.42x, the attract player not at all.  So, as
for pictures (:mod:`picture_sizes`), a replacement goes on at the most the game shows its slot: the box times the
player's biggest zoom (an upper bound: the clips share a player, so which one plays while it is zoomed can't be
told), with the Scenes tab's layout on, never enlarged past the user's own file, and never past what the machine's
decoder plays - the i.MX6's VPU decodes H.264 up to 1920x1088; a clip above it plays its sound over a black
picture.  The clip keeps the slot's shape (the game draws it in the box).

A clip no bigger than its slot is converted to the slot's size, exactly as before.
"""
from __future__ import annotations

import os

from .picture_sizes import man_zooms

#: the biggest picture Spike 2's i.MX6 VPU decodes (H.264, 1080p with its 16-line macroblock rows)
DECODER_MAX = (1920, 1088)


def player_zooms(assets_dir):
    """``{clip name: (box w, box h, biggest zoom)}`` over every scene of the project with the Scenes tab's edits on;
    a clip in several players takes the biggest it is shown at.  Kept until the project's scenes or edits change."""
    from .picture_sizes import _stamp
    key = os.path.normcase(os.path.abspath(assets_dir or ""))
    stamp = _stamp(assets_dir) if assets_dir else None
    got = _CACHE.get(key)
    if got and got[0] == stamp:
        return got[1]
    out = _player_zooms(assets_dir)
    _CACHE[key] = (stamp, out)
    return out


_CACHE = {}


def _player_zooms(assets_dir):
    from . import scene_edit
    trees = scene_edit.trees_of(assets_dir) or {}
    edits = scene_edit.load(assets_dir)
    out = {}
    for card, man in trees.items():
        if not isinstance(man, dict) or not man.get("root"):
            continue
        ops = edits.get(card)
        if ops:
            try:
                man = scene_edit.apply_manifest(man, ops)[0]
            except Exception:                       # noqa: BLE001 - measured on the stock layout
                pass
        objs = man.get("objects") or {}
        zooms = man_zooms(man)

        def nodes(kids, seen):
            for n in kids or ():
                yield n
                for _s, oid in n.get("comps") or ():
                    o = objs.get(str(oid)) or {}
                    if o.get("kids") is not None and oid not in seen:
                        seen.add(oid)
                        yield from nodes(o["kids"], seen)
        for n in nodes((man.get("root") or {}).get("kids"), set()):
            z = zooms.get(n.get("id"))
            if z is None:
                continue
            for _s, oid in n.get("comps") or ():
                o = objs.get(str(oid)) or {}
                if o.get("kind") != "Video" or not (o.get("w") and o.get("h")):
                    continue
                for clip in o.get("clips") or ():
                    was = out.get(clip)
                    if was is None or o["w"] * z > was[0] * was[2]:
                        out[clip] = (int(o["w"]), int(o["h"]), float(z))
    return out


def _even(v):
    return max(2, int(v) // 2 * 2)


def shown_size(slot_wh, player):
    """``(w, h)`` the most the game shows a clip of a slot *slot_wh* in *player* ``(box w, box h, zoom)`` (or
    None: shown at its own size)."""
    if not player:
        return tuple(slot_wh)
    bw, bh, z = player
    return (int(round(bw * z)), int(round(bh * z)))


def written_size(slot_wh, rep_wh, player):
    """``(w, h)`` a replacement of *rep_wh* for a slot of *slot_wh* goes on the card at: the slot's shape, as big as
    the game shows it (*player*, :func:`player_zooms`), never bigger than the replacement nor the decoder's
    :data:`DECODER_MAX`, and never smaller than the slot (a clip no bigger is converted to the slot's size)."""
    sw, sh = slot_wh
    if not (sw and sh):
        return tuple(slot_wh)
    most = shown_size(slot_wh, player)
    s = min(most[0] / float(sw), most[1] / float(sh))
    if rep_wh and rep_wh[0] and rep_wh[1]:
        s = min(s, rep_wh[0] / float(sw), rep_wh[1] / float(sh))
    s = min(s, DECODER_MAX[0] / float(sw), DECODER_MAX[1] / float(sh))
    if s <= 1.0:
        return (sw, sh)
    w, h = _even(sw * s), _even(sh * s)
    if (w, h) == (sw, sh) or w <= sw or h <= sh:
        return (sw, sh)
    return (w, h)


def _stem(rel):
    return os.path.splitext(os.path.basename(rel))[0]


def player_of(players, rel):
    """The player entry of the slot *rel* (``video/<clip>.mov``), or None."""
    return players.get(_stem(rel))


def sizes_for(assets_dir, slots_by_rel, assignments, probe=None):
    """``{rel: (w, h)}`` of the assigned clips that go on bigger than their slot (:func:`written_size`); the rest
    are converted to the slot's size as before.  *probe* reads a file's ``(w, h)`` (``core.video``'s by
    default)."""
    if probe is None:
        def probe(path):
            from ...core.video import detect_video_info
            info = detect_video_info(path)
            return (info.width, info.height) if info and info.width and info.height else None
    from ...core import staged_originals
    try:
        players = player_zooms(assets_dir)
    except Exception:                               # noqa: BLE001 - every clip at its slot's size
        return {}
    out = {}
    for rel, rep in (assignments or {}).items():
        slot = (slots_by_rel or {}).get(rel)
        player = player_of(players, rel)
        if slot is None or not player or not rep or not os.path.isfile(rep):
            continue
        # the slot's size is the clip it shipped with: once a bigger clip was staged, the slot holds that one
        orig = staged_originals.snapshot_path(assets_dir, rel) if assets_dir else None
        base = probe(orig) if orig else None
        if not base:
            info = slot.info
            base = (info.width, info.height) if info is not None and info.width and info.height else None
        mine = probe(rep)
        if not base or not mine:
            continue
        got = written_size(base, mine, player)
        if tuple(got) != tuple(base):
            out[rel] = tuple(got)
    return out
