"""The size a replacement video goes on the card at, on every machine (Simon, 2026-11-21).

Simon: "As discussed we MUST cover all machines, spike 3, JJP ALL. We don't know whether a certain machine might
display (SAY) an animated map for a battle screen which it dynamically zooms into. Therefore we must be very
careful. It may also at some point be possible to put a video into a scene and again - this could be oversized.
So the image rules need to apply to the video rules even if we can't see a valid case right now."

The Images tab's rules, for a clip:

* **Imported size** (per clip, :data:`KEEP_KEY`): on, the clip keeps its own size in the slot's shape; off, it is
  converted to the slot's size, as PAD always did.  A new pick starts on where a bigger clip has been proven to
  show right on the machine (:meth:`registry.Manufacturer.video_size_limit`'s *tested*: Stern Spike 2, Simon's
  emulator test of a 4K clip), off elsewhere.
* **Current** - the most the machine's video player shows the slot, where PAD can measure it
  (:meth:`registry.Manufacturer.video_players`: a Spike 2 scene's Video box times its biggest zoom); unknown
  elsewhere.
* **Written** - Imported size on: the clip in the slot's shape, never bigger than the user's file, than Current
  where it is known, or than what the machine's decoder plays; never smaller than the slot (a smaller clip is
  enlarged to the slot, as before).  Off, or where the slot can't change size (a fixed canvas, a card that holds
  each clip to its byte size): the slot's size.
"""
from __future__ import annotations

import os

#: the project sidecar's ``{rel: bool}`` of each clip's Imported size (absent: the machine's default)
KEEP_KEY = "video_keep_size_slots"


def _even(v):
    return max(2, int(v) // 2 * 2)


def shown_size(slot_wh, player):
    """``(w, h)`` the most the game shows a clip of a slot *slot_wh* in *player* ``(box w, box h, zoom)``, or None
    where it can't be measured."""
    if not player:
        return None
    bw, bh, z = player
    return (int(round(bw * z)), int(round(bh * z)))


def written_size(slot_wh, rep_wh, player=None, limit=None, keep=True, measured=True):
    """``(w, h)`` a replacement of *rep_wh* for a slot of *slot_wh* goes on the card at (see the module's words).
    *player* is the slot's ``(box w, box h, zoom)`` (None: shown at the slot's own size where *measured*, or
    unknown where not); *limit* the biggest ``(w, h)`` the machine's decoder plays (None: the slot's size is
    the most it can take)."""
    sw, sh = slot_wh
    if not (sw and sh) or not keep or not limit:
        return tuple(slot_wh)
    s = min(limit[0] / float(sw), limit[1] / float(sh))
    most = shown_size(slot_wh, player)
    if most:
        s = min(s, most[0] / float(sw), most[1] / float(sh))
    elif measured:
        return tuple(slot_wh)                       # shown at its own size: never bigger
    if rep_wh and rep_wh[0] and rep_wh[1]:
        s = min(s, rep_wh[0] / float(sw), rep_wh[1] / float(sh))
    if s <= 1.0:
        return tuple(slot_wh)
    w, h = _even(sw * s), _even(sh * s)
    if w <= sw or h <= sh:
        return tuple(slot_wh)
    return (w, h)


def _stem(rel):
    return os.path.splitext(os.path.basename(rel))[0]


def player_of(players, rel):
    """The player entry of the slot *rel* (``video/<clip>.mov``) in *players* ``{clip name: (w, h, zoom)}``."""
    return (players or {}).get(_stem(rel))


def keep_of(saved_keep, rel, tested):
    """Whether *rel*'s Imported size is on: its own setting in *saved_keep*, else on where the machine is
    *tested*."""
    v = (saved_keep or {}).get(rel)
    return bool(tested) if v is None else bool(v)


class Facts:
    """What the machine says about one slot: ``limit`` (biggest decodable ``(w, h)``, or None), ``why`` (why the
    slot can't change size, or None), ``tested`` (a bigger clip has been seen to show right), ``player`` (its
    ``(box w, box h, zoom)``) and ``measured`` (PAD can tell how big the machine shows it)."""
    __slots__ = ("limit", "why", "tested", "player", "measured")

    def __init__(self, limit=None, why=None, tested=False, player=None, measured=False):
        self.limit, self.why, self.tested = limit, why, tested
        self.player, self.measured = player, measured


def facts(mfr, assets_dir, rel, slot, players=None):
    """:class:`Facts` of the slot *slot* (``rel``) on the machine *mfr*."""
    if mfr is None:
        return Facts(why="no machine is loaded")
    try:
        limit, why, tested = mfr.video_size_limit(assets_dir, rel, slot)
    except Exception:                                   # noqa: BLE001 - the slot's size, as before
        limit, why, tested = None, "PAD could not tell what this machine plays", False
    return Facts(limit=None if why else limit, why=why, tested=tested,
                 player=player_of(players, rel) if players is not None else None,
                 measured=players is not None)


#: Simon (2026-11-21): "we MUST cover all machines ... we must be very careful" - said wherever a bigger clip has
#: not been seen to show right on the machine
UNTESTED = ("A clip bigger than its slot has not been tested on this machine yet: it may show oversized or cut "
            "off. Untick Imported size to convert it to the slot's size.")


def verdict(stock, mine, f, keep):
    """``(written (w, h), why)`` of a clip of *mine* for a slot of *stock*, with the slot's :class:`Facts` *f* and
    its Imported size *keep*; *why*: ``"fixed"`` (the slot can't change size), ``"off"``, ``"same"`` (written as
    it is), ``"up"`` (a smaller clip enlarged to the slot), ``"shown"`` (reduced to the most the game shows it),
    ``"limit"`` (reduced to the decoder's limit) or ``"own"`` (kept at its own size, in the slot's shape)."""
    if f.why or not f.limit:
        return tuple(stock), "fixed"
    if not keep:
        return tuple(stock), "off"
    got = tuple(written_size(stock, mine, f.player, f.limit, True, f.measured))
    if got == tuple(mine):
        return got, "same"
    if got[0] > mine[0]:
        return got, "up"
    if got == tuple(stock):                         # reduced to the slot: the most it is shown, or can be played
        return got, "shown" if f.measured else "limit"
    most = shown_size(stock, f.player)
    if most and got[0] >= most[0] - 2 and got[1] >= most[1] - 2:
        return got, "shown"
    if got[0] >= f.limit[0] - 2 or got[1] >= f.limit[1] - 2:
        return got, "limit"
    return got, "own"


def words(stock, mine, f, keep, rate=""):
    """The note under the Video tab's preview for a clip of *mine* in a slot of *stock* (Simon, 2026-11-21:
    "Your image/video is nnnn x nnnn. The original image size is nnnn x nnnn. PAD will limit your image to nnnn x
    nnnn"), or None when it goes on as it is.  *rate* names a frame rate it is converted to."""
    got, why = verdict(stock, mine, f, keep)
    if why == "same" and not rate:
        return None

    def wh(v):
        return "%d×%d" % tuple(v[:2])
    head = "Your video is %s. The original is %s" % (wh(mine), wh(stock))
    most = shown_size(stock, f.player)
    if most:
        head += ", and the machine's video player plays this slot at up to %s" % wh(most)
    elif f.measured is False and not f.why:
        head += "; PAD can't measure how big this machine plays this slot"
    tail = " Your own file stays full size in the project."
    if why == "fixed":
        return "%s: PAD will convert it to %s%s, since %s.%s" % (head, wh(got), rate, f.why, tail)
    if why == "off":
        return "%s: Imported size is off, so PAD will convert it to the slot's size, %s%s.%s" % (
            head, wh(got), rate, tail)
    if why == "up":
        return "%s: PAD will convert it to the slot's size, %s%s.%s" % (head, wh(got), rate, tail)
    text = {"same": "%s: PAD will write it at its own size, %s%s.",
            "shown": "%s: PAD will write it at %s%s, the most the machine's video player shows it - a bigger "
                     "clip would not look sharper.",
            "limit": "%s: PAD will write it at %s%s, the most this machine's video decoder plays.",
            "own": "%s: PAD will write it at its own size in the slot's shape, %s%s."}[why] % (head, wh(got), rate)
    if not f.tested and tuple(got) != tuple(stock):
        text += " WARNING: " + UNTESTED
    return text + tail


def _probe(path):
    from .video import detect_video_info
    info = detect_video_info(path)
    return (info.width, info.height) if info and info.width and info.height else None


def stock_size(assets_dir, rel, slot, probe=None):
    """``(w, h)`` of the clip the slot *rel* shipped with: its ``.orig/`` snapshot once a build staged over it,
    else the slot's own."""
    from . import staged_originals
    probe = probe or _probe
    snap = staged_originals.snapshot_path(assets_dir, rel) if assets_dir else None
    got = probe(snap) if snap else None
    if got:
        return tuple(got)
    info = getattr(slot, "info", None)
    return (int(info.width), int(info.height)) if info is not None and info.width and info.height else None


def sizes_for(mfr, assets_dir, slots_by_rel, assignments, probe=None, saved=None):
    """``{rel: (w, h)}`` of the assigned clips that go on at another size than their slot (:func:`written_size`);
    every other clip is converted to its slot's size.  *saved* is the project's sidecar (read when not given)."""
    probe = probe or _probe
    if saved is None:
        from . import staged_changes
        try:
            saved = staged_changes.load(assets_dir) if assets_dir else {}
        except Exception:                               # noqa: BLE001
            saved = {}
    keep = saved.get(KEEP_KEY) or {}
    try:
        players = mfr.video_players(assets_dir) if mfr is not None else None
    except Exception:                                   # noqa: BLE001
        players = None
    out = {}
    for rel, rep in (assignments or {}).items():
        slot = (slots_by_rel or {}).get(rel)
        if slot is None or not rep or not isinstance(rep, str) or not os.path.isfile(rep):
            continue
        f = facts(mfr, assets_dir, rel, slot, players)
        if f.why or not f.limit or not keep_of(keep, rel, f.tested):
            continue
        base = stock_size(assets_dir, rel, slot, probe)
        mine = probe(rep)
        if not base or not mine:
            continue
        got = written_size(base, mine, f.player, f.limit, True, f.measured)
        if tuple(got) != tuple(base):
            out[rel] = tuple(got)
    return out
