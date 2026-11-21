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


# the rules themselves are every machine's (core/video_sizes.py); these keep Spike 2's words for its callers
from ...core.video_sizes import player_of  # noqa: E402,F401  (re-exported)


def shown_size(slot_wh, player):
    """``(w, h)`` the most the game shows a slot of *slot_wh* in *player*; the slot's own size with none."""
    from ...core import video_sizes as core
    return core.shown_size(slot_wh, player) or tuple(slot_wh)


def written_size(slot_wh, rep_wh, player):
    """Spike 2's Written: :func:`core.video_sizes.written_size` with the VPU's :data:`DECODER_MAX`."""
    from ...core import video_sizes as core
    return core.written_size(slot_wh, rep_wh, player, DECODER_MAX, True, True)
