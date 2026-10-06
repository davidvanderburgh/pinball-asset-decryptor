"""Edits to a Spike 2 scene's TREE, kept per project and applied twice (PAD-251).

The Scenes window records what the user does to a scene - move, resize, hide, re-order,
add a picture or a line of text - as a list of operations per scene in
``images/scene_textures/scene_edits.json``.  The same list is applied

* to the scene's preview manifest (:mod:`scene_eval`), so the window draws the edit at once,
* to the scene read off the card (:mod:`scene_tree`) when the Write builds, so the card gets it.

Operations name nodes by their id in the file (unique, and the same on every copy of that
scene); a node a card does not have, or has under another name, is left alone and reported -
an edit made on one code version is never applied to a different node on another.

Operations (``op`` and its fields)::

    move    node, dx, dy          add dx, dy to every track of the node (its parent's units)
    scale   node, s, px, py[, sy] scale by s about the node-local point (px, py); with sy, s is
                                  the width's factor and sy the height's (a picture stretched)
    tint    node, mul             multiply the node's colour transform by *mul* (r g b a): its
                                  colour track, which the game applies to pictures and text
                                  alike (a Text's own rgba is ignored by a styled game font)
    visible node, on              on=False: the node's timeline never shows it (code can hide a
                                  node but never reveal one its timeline hides, so this is
                                  final); on=True puts the stock keyframes back
    order   node, index           move the node to position *index* among its siblings (later
                                  siblings draw on top)
    add_picture  parent, index, id, name, image, w, h, x, y
                                  a new Bitmap node under *parent* (a node whose component is a
                                  Sprite; None = the root) showing *image* (a PNG rel under
                                  ``images/``), top-left at (x, y)
    add_text     parent, index, id, name, text, x, y, like, rgba
                                  a new Text node, a copy of the Text node *like* (its font and
                                  size) with *text*, *rgba*, at (x, y)
    rotate  node, deg, px, py     turn the node's content *deg* degrees clockwise on the screen
                                  about its local point (px, py)
    shadow  node, id, dx, dy, mul a drop shadow for a Text node: a copy of the node drawn just
                                  beneath it (sharing its Text, as the game's own outline and
                                  fill pairs do), moved (dx, dy) and its colour multiplied by
                                  *mul* (black, part see-through)
    parent  node, parent, index, m
                                  move an ADDED node into another group (*parent*, a node
                                  whose component is a Sprite; None = the root), at *index*
                                  among its kids, every track of it multiplied by the affine
                                  *m* (a, b, c, d, tx, ty) so it stays where it was on the
                                  glass (PAD-391; the game's own nodes stay in their group:
                                  its code finds them by their path)
    remove  node                  drop a node an add_* made (stock nodes are hidden instead:
                                  the game's code finds them by name and must still find them)

``id`` of an added node is the one it has in the preview; the writer gives it a fresh id in
the card's own id space.
"""
from __future__ import annotations

import copy
import json
import math
import os

RELDIR = ("images", "scene_textures")
FILENAME = "scene_edits.json"
BUILT_FILENAME = "scene_edits_built.json"   # the edits as the last successful Write built them
FIRST_ADDED_ID = 0x7F000000          # preview ids of added nodes (never a stock id)


class SceneEditError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------------------------
def path_of(assets_dir):
    return os.path.join(assets_dir, *RELDIR, FILENAME)


def load(assets_dir):
    """``{card path: [op, ...]}`` (``{}`` when there is none or it is unreadable)."""
    try:
        with open(path_of(assets_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: [op for op in v if isinstance(op, dict) and op.get("op")]
            for k, v in data.items() if isinstance(v, list) and v}


def save(assets_dir, edits):
    path = path_of(assets_dir)
    edits = {k: v for k, v in (edits or {}).items() if v}
    if not edits:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(edits, f, indent=1, sort_keys=True)


def ops_for(assets_dir, card):
    return list(load(assets_dir).get(card) or ())


def add(assets_dir, card, op):
    """Append *op* to *card*'s list, folding it into the previous op when both move (or both
    scale about the same point) the same node, so a drag is one entry."""
    edits = load(assets_dir)
    ops = edits.setdefault(card, [])
    last = ops[-1] if ops else None
    if last and ("group" in last or _carries(assets_dir, card, ops)):
        # a group's edit stays one undo step; one the scene already shows stays as it is
        # (PAD-403: folded into, it would be told apart from the scene's and applied whole)
        ops.append(op)
    elif last and last.get("node") == op.get("node") and last["op"] == op["op"] == "move":
        last["dx"] = round(last["dx"] + op["dx"], 3)
        last["dy"] = round(last["dy"] + op["dy"], 3)
        if not last["dx"] and not last["dy"]:
            ops.pop()
    elif (last and last.get("node") == op.get("node") and last["op"] == op["op"] == "scale"
          and (last.get("px"), last.get("py")) == (op.get("px"), op.get("py"))):
        if "sy" in last or "sy" in op:
            last["sy"] = round(last.get("sy", last["s"]) * op.get("sy", op["s"]), 6)
        last["s"] = round(last["s"] * op["s"], 6)
        if abs(last["s"] - 1.0) < 1e-6 and abs(last.get("sy", 1.0) - 1.0) < 1e-6:
            ops.pop()
    elif last and last.get("node") == op.get("node") and last["op"] == op["op"] == "text_rect":
        last["rect"] = op["rect"]
        if op.get("wrap"):
            last["wrap"] = True
    elif (last and last.get("node") == op.get("node") and last["op"] == op["op"] == "rotate"
          and (last.get("px"), last.get("py")) == (op.get("px"), op.get("py"))):
        last["deg"] = round(last["deg"] + op["deg"], 4)
        if abs(last["deg"] % 360.0) < 1e-6:
            ops.pop()
    else:
        ops.append(op)
    save(assets_dir, edits)
    return ops


def add_group(assets_dir, card, group):
    """Append the ops of one edit made to several nodes at once (PAD-279: a multiple selection
    moved or hidden together) as one undo step.  A move of the same nodes straight after the
    last one folds into it, so a drag or a run of arrow keys is still one step."""
    group = [dict(op) for op in group]
    if len(group) == 1:
        return add(assets_dir, card, group[0])
    edits = load(assets_dir)
    ops = edits.setdefault(card, [])
    tail = ops[-len(group):] if len(ops) >= len(group) else []
    gid = tail[0].get("group") if tail else None
    if (gid is not None and not _carries(assets_dir, card, ops)
            and all(o.get("group") == gid for o in tail)
            and (len(ops) == len(group) or ops[-len(group) - 1].get("group") != gid)
            and all(o["op"] == "move" for o in tail + group)
            and [o["node"] for o in tail] == [o["node"] for o in group]):
        for last, op in zip(tail, group):
            last["dx"] = round(last["dx"] + op["dx"], 3)
            last["dy"] = round(last["dy"] + op["dy"], 3)
        if all(not o["dx"] and not o["dy"] for o in tail):
            del ops[-len(group):]
    else:
        gid = max([o.get("group", 0) for o in ops] + [0]) + 1
        for op in group:
            op["group"] = gid
            ops.append(op)
    save(assets_dir, edits)
    return ops


def reset_node(assets_dir, card, node):
    """Drop every op on *node* (and, when it was ADDED, the node itself)."""
    edits = load(assets_dir)
    ops = edits.get(card) or []
    edits[card] = [op for op in ops if op.get("node") != node and op.get("id") != node]
    save(assets_dir, edits)


def drop(assets_dir, card, node, kind):
    """Remove *node*'s ops of *kind* (showing a hidden node again = dropping its hide)."""
    edits = load(assets_dir)
    edits[card] = [op for op in edits.get(card) or ()
                   if not (op.get("node") == node and op["op"] == kind)]
    save(assets_dir, edits)


def undone(ops):
    """*ops* without its last edit (a group's ops go together)."""
    ops = list(ops or ())
    if ops:
        gid = ops.pop().get("group")
        while gid is not None and ops and ops[-1].get("group") == gid:
            ops.pop()
    return ops


def undo(assets_dir, card):
    edits = load(assets_dir)
    if edits.get(card):
        edits[card] = undone(edits[card])
        save(assets_dir, edits)


def set_ops(assets_dir, card, ops):
    """*card*'s whole list, as an undo or redo puts it back."""
    edits = load(assets_dir)
    edits[card] = [dict(op) for op in ops or ()]
    save(assets_dir, edits)


def clear(assets_dir, card=None):
    edits = load(assets_dir)
    if card is None:
        edits = {}
    else:
        edits.pop(card, None)
    save(assets_dir, edits)


def count(assets_dir):
    return sum(len(v) for v in load(assets_dir).values())


# ---------------------------------------------------------------------------------------------
# a file of edits to share or keep (PAD-281)
# ---------------------------------------------------------------------------------------------
SHARE_MANIFEST = "pad_scene_edits.json"
SHARE_KIND = "pad-scene-edits"


def _safe_rel(rel):
    """*rel* (``a/b.png``) when it stays inside the folder it names a file in; else None."""
    rel = (rel or "").replace("\\", "/")
    parts = rel.split("/")
    if (not rel or rel.startswith("/") or ":" in parts[0]
            or any(p in ("", ".", "..") for p in parts)):
        return None
    return rel


def export_edits(assets_dir, zip_path, cards=None):
    """Write the edits of *cards* (None: every edited scene) to a zip anyone can load into a
    project of the same card: the ops, and every picture an ``add_picture`` shows.  Returns
    the number of scenes written; raises :class:`SceneEditError` when there is nothing."""
    import zipfile
    edits = load(assets_dir)
    if cards is not None:
        edits = {c: edits[c] for c in cards if edits.get(c)}
    if not edits:
        raise SceneEditError("there are no scene edits to save")
    pictures = sorted({op["image"] for ops in edits.values() for op in ops
                       if op["op"] == "add_picture" and _safe_rel(op.get("image"))})
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        doc = {"format": 1, "kind": SHARE_KIND, "scenes": edits}
        states = states_to_save(assets_dir, edits, trees_of(assets_dir))
        if states:
            doc["states"] = states                   # PAD-403
        z.writestr(SHARE_MANIFEST, json.dumps(doc, indent=1, sort_keys=True))
        for rel in pictures:
            src = os.path.join(assets_dir, "images", *rel.split("/"))
            if os.path.isfile(src):
                z.write(src, "images/" + rel)
    return len(edits)


def trees_of(assets_dir):
    """The project's scene trees (``scene_tree.json``: ``{card: preview manifest}``)."""
    try:
        with open(os.path.join(assets_dir, *RELDIR, "scene_tree.json"), "r",
                  encoding="utf-8") as f:
            trees = json.load(f)
    except (OSError, ValueError):
        return {}
    return trees if isinstance(trees, dict) else {}


def read_states(zip_path):
    """``{card: states}`` a file :func:`export_edits` or a full save wrote (PAD-403; ``{}``
    for a file saved before)."""
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            data = json.loads(z.read(SHARE_MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}
    states = data.get("states") if isinstance(data, dict) else None
    return {c: s for c, s in states.items() if isinstance(s, dict)} if isinstance(
        states, dict) else {}


def read_share(zip_path):
    """``{card: [op, ...]}`` of a file :func:`export_edits` wrote; raises
    :class:`SceneEditError` for anything else."""
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            data = json.loads(z.read(SHARE_MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise SceneEditError("%s is not a file of scene edits saved by PAD"
                             % os.path.basename(zip_path)) from None
    if not isinstance(data, dict):
        data = {}
    scenes = data.get("scenes")
    if data.get("kind") != SHARE_KIND or not isinstance(scenes, dict):
        raise SceneEditError("%s is not a file of scene edits saved by PAD"
                             % os.path.basename(zip_path))
    if data.get("format", 1) > 1:
        raise SceneEditError("%s was saved by a newer PAD: update to load it"
                             % os.path.basename(zip_path))
    return {c: [op for op in v if isinstance(op, dict) and op.get("op")]
            for c, v in scenes.items() if isinstance(v, list) and v}


def card_finder(cards_here):
    """A function naming the card here that a card path of a file stands for, or None: the
    same path here, else the one path here that differs only in the game folder
    (``/godzilla_le/`` and ``/godzilla_pro/`` share a scene the scene id names)."""
    here = set(cards_here)
    by_rest = {}
    for c in here:
        by_rest.setdefault(c.lstrip("/").split("/", 1)[-1], []).append(c)

    def find(card):
        if card in here:
            return card
        same = by_rest.get(card.lstrip("/").split("/", 1)[-1], [])
        return same[0] if len(same) == 1 else None
    return find


def match_cards(scenes, cards_here):
    """``({card here: ops}, [card of the file with no scene here])``, each card matched by
    :func:`card_finder`."""
    if cards_here is None:
        return dict(scenes), []
    find = card_finder(cards_here)
    got, missing = {}, []
    for card, ops in scenes.items():
        mine = find(card)
        if mine is not None:
            got[mine] = ops
        else:
            missing.append(card)
    return got, missing


def import_edits(assets_dir, zip_path, cards_here=None, renamed=None, skip=()):
    """Load a file :func:`export_edits` wrote: each scene in it that this project has
    (*cards_here*, None: take every one) gets the file's edits in place of its own, and the
    pictures they add are copied in (under a new name when one of the same name is already
    here and differs; *renamed*, a dict, is filled with ``{rel in the file: rel here}``).
    A scene here in *skip* (PAD-402: the user kept their own) is left as it is.
    Returns ``({card: [op, ...]} as loaded, [card of the file not here])``."""
    import zipfile
    scenes, missing = match_cards(read_share(zip_path), cards_here)
    scenes = {c: ops for c, ops in scenes.items() if c not in set(skip)}
    renamed = {} if renamed is None else renamed
    with zipfile.ZipFile(zip_path) as z:
        members = set(z.namelist())
        for ops in scenes.values():
            for op in ops:
                rel = _safe_rel(op.get("image")) if op["op"] == "add_picture" else None
                if rel is None or rel in renamed or "images/" + rel not in members:
                    continue
                data = z.read("images/" + rel)
                stem, ext = os.path.splitext(rel)
                new, n = rel, 2
                while True:
                    dest = os.path.join(assets_dir, "images", *new.split("/"))
                    if not os.path.exists(dest):
                        break
                    with open(dest, "rb") as f:
                        if f.read() == data:
                            break
                    new, n = "%s_%d%s" % (stem, n, ext), n + 1
                if not os.path.exists(dest):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(data)
                renamed[rel] = new
    for ops in scenes.values():
        for op in ops:
            if op["op"] == "add_picture" and op.get("image") in renamed:
                op["image"] = renamed[op["image"]]
    if scenes:
        edits = load(assets_dir)
        edits.update(scenes)
        save(assets_dir, edits)
    return scenes, missing


# ---------------------------------------------------------------------------------------------
# the last Write: edits are kept the moment they are made, so "the last saved state" a user can
# go back to is what the last successful Write (image build or direct SD) put on a card
# ---------------------------------------------------------------------------------------------
def _built_path(assets_dir):
    return os.path.join(assets_dir, *RELDIR, BUILT_FILENAME)


def mark_built(assets_dir):
    """Record the current edits as the ones the last Write built (called when a Write run from
    this project folder succeeds).  A project with no scene edits at all records nothing."""
    edits = load(assets_dir)
    path = _built_path(assets_dir)
    if not edits and not os.path.isfile(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"edits": edits}, f, indent=1, sort_keys=True)
    # PAD-403: the card built now shows every one of them; a project extracted from it knows so
    try:
        keep_states(assets_dir, states_to_save(assets_dir, edits, trees_of(assets_dir)))
    except Exception:                                # noqa: BLE001 - the Write is done anyway
        pass
    return True


def built_all(assets_dir):
    """Every scene's ops as the last Write built them (``{card: [op]}``), or ``None`` when no
    Write has been recorded."""
    try:
        with open(_built_path(assets_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    edits = data.get("edits") if isinstance(data, dict) else None
    return edits if isinstance(edits, dict) else None


def scene_states(assets_dir):
    """``{card: "edited" | "written"}`` for every scene with edits now or at the last Write:
    *edited* = its edits differ from what the last Write put on the card (not written yet),
    *written* = the last Write put exactly these edits on the card.  A scene as shipped both
    now and then is absent."""
    now = load(assets_dir)
    built = built_all(assets_dir)
    out = {}
    for card in set(now) | set(built or {}):
        ops = now.get(card) or []
        was = [op for op in ((built or {}).get(card) or ()) if isinstance(op, dict)]
        if built is not None and ops == was:
            if ops:
                out[card] = "written"
        else:
            out[card] = "edited"
    return out


def built_ops(assets_dir, card):
    """*card*'s ops as the last Write built them, or ``None`` when no Write has been recorded."""
    try:
        with open(_built_path(assets_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    edits = data.get("edits") if isinstance(data, dict) else None
    if not isinstance(edits, dict):
        return None
    return [op for op in edits.get(card) or () if isinstance(op, dict) and op.get("op")]


def restore_built(assets_dir, card):
    """Put *card*'s edits back to the last Write's; False when there is no recorded Write."""
    ops = built_ops(assets_dir, card)
    if ops is None:
        return False
    edits = load(assets_dir)
    edits[card] = copy.deepcopy(ops)
    save(assets_dir, edits)
    return True


def describe(op):
    k = op["op"]
    if k == "move":
        return "moved %+g,%+g" % (op["dx"], op["dy"])
    if k == "scale":
        if "sy" in op and abs(op["sy"] - op["s"]) > 1e-6:
            return "%d x %d %%" % (round(op["s"] * 100), round(op["sy"] * 100))
        return "%d %%" % round(op["s"] * 100)
    if k == "visible":
        return "shown" if op["on"] else "hidden in game"
    if k == "tint":
        return "tinted #%02x%02x%02x" % tuple(int(round(c * 255)) for c in op["mul"][:3])
    if k == "order":
        return "layer %d" % op["index"]
    if k == "add_picture":
        return "added picture %s%s" % (os.path.basename(op["image"]),
                                       " (colors corrected)" if op.get("color") else "")
    if k == "add_text":
        return 'added text "%s"' % op["text"]
    if k == "rotate":
        return "turned %+g°" % op["deg"]
    if k == "shadow":
        return "added a drop shadow"
    if k == "parent":
        return "put in another group"
    if k == "remove":
        return "removed"
    if k == "text_rect":
        return "box resized" if op.get("wrap") else "box fitted"
    return k


def new_id(man, ops=()):
    """A preview id for a node an edit adds: above every id the manifest and *ops* use."""
    used = [FIRST_ADDED_ID - 1]
    for op in ops:
        if op.get("id"):
            used.append(int(op["id"]))
    return max(used) + 2      # +2: the node and its component object


# ---------------------------------------------------------------------------------------------
# the affine arithmetic (a, b, c, d, tx, ty) shared by both sides
# ---------------------------------------------------------------------------------------------
def _moved(m6, dx, dy):
    a, b, c, d, tx, ty = m6
    return (a, b, c, d, tx + dx, ty + dy)


def _scaled(m6, s, px, py, sy=None):
    """Scale the node's content by *s* (width) and *sy* (height, default *s*) about its local
    point (px, py): the point stays where it was on the glass."""
    a, b, c, d, tx, ty = m6
    sy = s if sy is None else sy
    kx, ky = 1.0 - s, 1.0 - sy
    return (a * s, b * s, c * sy, d * sy,
            tx + kx * a * px + ky * c * py, ty + kx * b * px + ky * d * py)


def _rotated(m6, deg, px, py):
    """Turn the node's content *deg* degrees clockwise on the screen (y points down) about its
    local point (px, py): the point stays where it was on the glass."""
    a, b, c, d, tx, ty = m6
    r = math.radians(deg)
    cs, sn = math.cos(r), math.sin(r)
    rx, ry = cs * px - sn * py, sn * px + cs * py
    return (a * cs + c * sn, b * cs + d * sn, -a * sn + c * cs, -b * sn + d * cs,
            tx + a * (px - rx) + c * (py - ry), ty + b * (px - rx) + d * (py - ry))


def _composed(p, m):
    """Affine *p* applied after *m* (both a, b, c, d, tx, ty)."""
    a, b, c, d, tx, ty = p
    a2, b2, c2, d2, tx2, ty2 = m
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * tx2 + c * ty2 + tx, b * tx2 + d * ty2 + ty)


def _tint_steps(steps):
    """A colour track to multiply: the node's own steps, or one neutral step at frame 1."""
    steps = [(f, list(m), list(a)) for f, m, a in steps or ()]
    return steps or [(1, [1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0])]


def _m6_of16(m):
    return (m[0], m[1], m[4], m[5], m[12], m[13])


def _m16_with(m, m6):
    m = list(m)
    m[0], m[1], m[4], m[5], m[12], m[13] = m6
    return m


# ---------------------------------------------------------------------------------------------
# applying to the PREVIEW manifest (scene_eval)
# ---------------------------------------------------------------------------------------------
def _man_index(man):
    """``{node id: (node dict, the kids list holding it)}`` over the whole manifest."""
    out = {}

    def run(kids):
        for n in kids:
            out[n["id"]] = (n, kids)
            for _s, oid in n["comps"]:
                o = man["objects"].get(str(oid)) or {}
                if o.get("kids") is not None and not o.get("_seen"):
                    o["_seen"] = True
                    run(o["kids"])

    run(man["root"]["kids"])
    for o in man["objects"].values():
        o.pop("_seen", None)
    return out


def _man_kids_of(man, index, parent):
    if parent is None:
        return man["root"]["kids"]
    got = index.get(parent)
    if got is None:
        return None
    for _s, oid in got[0]["comps"]:
        o = man["objects"].get(str(oid)) or {}
        if o.get("kind") in ("Sprite", "StreamingFlipbook"):
            return o["kids"]
    return None


def apply_manifest(man, ops):
    """A copy of manifest *man* with *ops* applied; ``(manifest, [skipped op notes])``."""
    man = copy.deepcopy(man)
    notes = []
    for op in ops or ():
        index = _man_index(man)
        k = op.get("op")
        try:
            if k in ("move", "scale", "visible", "order", "remove", "tint", "rotate", "shadow",
                     "text_rect", "parent"):
                got = index.get(op["node"])
                if got is None:
                    notes.append("%s: node %s is not in this scene" % (k, op["node"]))
                    continue
                n, sibs = got
                if k == "tint":
                    n["col"] = [[f, [m[i] * op["mul"][i] for i in range(4)], a]
                                for f, m, a in _tint_steps(n["col"])]
                elif k == "move":
                    n["tr"] = [[f, list(_moved(m, op["dx"], op["dy"]))] for f, m in n["tr"]] or \
                        [[1, [1, 0, 0, 1, op["dx"], op["dy"]]]]
                elif k == "scale":
                    base = n["tr"] or [[1, [1, 0, 0, 1, 0, 0]]]
                    n["tr"] = [[f, list(_scaled(m, op["s"], op.get("px", 0), op.get("py", 0),
                                                op.get("sy")))]
                               for f, m in base]
                elif k == "rotate":
                    base = n["tr"] or [[1, [1, 0, 0, 1, 0, 0]]]
                    n["tr"] = [[f, list(_rotated(m, op["deg"], op.get("px", 0),
                                                 op.get("py", 0)))]
                               for f, m in base]
                elif k == "shadow":
                    base = n["tr"] or [[1, [1, 0, 0, 1, 0, 0]]]
                    sh = {"id": int(op["id"]), "name": n["name"] + "_Shadow",
                          "kf": copy.deepcopy(n["kf"]),
                          "col": [[f, [m[i] * op["mul"][i] for i in range(4)], a]
                                  for f, m, a in _tint_steps(n["col"])],
                          "tr": [[f, list(_moved(m, op["dx"], op["dy"]))] for f, m in base],
                          "comps": copy.deepcopy(n["comps"]), "added": True}
                    sibs.insert(sibs.index(n), sh)
                elif k == "visible":
                    if not op["on"]:
                        n.setdefault("_kf", n["kf"])
                        n["kf"] = [[1, 0]]
                    elif "_kf" in n:
                        n["kf"] = n.pop("_kf")
                elif k == "order":
                    sibs.remove(n)
                    sibs.insert(max(0, min(len(sibs), int(op["index"]))), n)
                elif k == "parent":
                    kids = _man_kids_of(man, index, op.get("parent"))
                    if kids is None or not n.get("added"):
                        notes.append("parent: node %s cannot go into %s"
                                     % (op["node"], op.get("parent")))
                        continue
                    m = tuple(op["m"])
                    n["tr"] = [[f, list(_composed(m, t))] for f, t in n["tr"]] or [[1, list(m)]]
                    sibs.remove(n)
                    kids.insert(max(0, min(len(kids), int(op["index"]))), n)
                elif k == "remove":
                    sibs.remove(n)
                elif k == "text_rect":
                    texts = [o for o in (man["objects"].get(str(oid)) or {}
                                         for _s, oid in n["comps"]) if o.get("kind") == "Text"]
                    if not texts:
                        notes.append("text_rect: node %s draws no text" % op["node"])
                    for o in texts:
                        o["rect"] = [float(v) for v in op["rect"]]
                        if op.get("wrap"):
                            # Multiline and WordWrap: the words re-flow in the box on the
                            # machine too (PAD-412: the first byte alone keeps the breaks)
                            o["flags"] = [1, 1]
            elif k in ("add_picture", "add_text"):
                kids = _man_kids_of(man, index, op.get("parent"))
                if kids is None:
                    notes.append("%s: parent %s is not a group in this scene"
                                 % (k, op.get("parent")))
                    continue
                oid = int(op["id"]) + 1
                if k == "add_picture":
                    obj = {"kind": "Bitmap", "w": op["w"], "h": op["h"], "tex": None,
                           "image": op["image"]}
                else:
                    like = index.get(op["like"])
                    src = None
                    if like:
                        for _s, lo in like[0]["comps"]:
                            cand = man["objects"].get(str(lo)) or {}
                            if cand.get("kind") == "Text":
                                src = cand
                    if src is None:
                        notes.append("add_text: the text to copy (%s) is not in this scene"
                                     % op["like"])
                        continue
                    obj = dict(copy.deepcopy(src), text=op["text"])
                    if op.get("rgba"):
                        obj["rgba"] = list(op["rgba"])
                    if op.get("flags"):
                        obj["flags"] = list(op["flags"])
                man["objects"][str(oid)] = obj
                node = {"id": int(op["id"]), "name": op["name"], "kf": [[1, 1]], "col": [],
                        "tr": [[1, [1, 0, 0, 1, op["x"], op["y"]]]], "comps": [[1, oid]],
                        "added": True}
                kids.insert(max(0, min(len(kids), int(op.get("index", len(kids))))), node)
            else:
                notes.append("unknown edit %r" % k)
        except (KeyError, TypeError, ValueError) as e:
            notes.append("%s: %s" % (k, e))
    return man, notes


# ---------------------------------------------------------------------------------------------
# applying to the CARD's scene (scene_tree), for the Write
# ---------------------------------------------------------------------------------------------
def _tree_index(scene):
    out = {}
    seen = set()

    def run(kids):
        for n in kids:
            out[n.id] = (n, kids)
            for c in n.components:
                if c.obj.kind in ("Sprite", "StreamingFlipbook") and c.obj.id not in seen:
                    seen.add(c.obj.id)
                    run(c.obj.body["kids"])

    run(scene.root["kids"])
    return out


def _tree_kids_of(index, fresh, parent, scene):
    """The kids list of group *parent* (a preview id; None = the root) on the card's scene."""
    if parent is None:
        return scene.root["kids"]
    got = index.get(fresh.get(parent, parent))
    if got is not None:
        for c in got[0].components:
            if c.obj.kind in ("Sprite", "StreamingFlipbook"):
                return c.obj.body["kids"]
    return None


def _max_id(scene):
    ids = [0]
    for n, _p, _d in scene.walk(library=True):
        ids.append(n.id)
    ids += list(scene.objects) + list(scene.textures) + list(scene.clips)
    ids += list(scene.assets) + list(scene.markers)
    return max(ids)


def _texture_from_png(path, premultiply=True, colour=None):
    """``(w, h, fmt, BC3 blob)`` of the PNG at *path*, padded to the block grid, premultiplied
    as the card's own art is.  (The display-wide color profile reaches it on the machine
    through the game's drawing shaders, PAD-305, like everything else it draws; *colour*, the
    chosen-files profile, is baked in here when the picture is switched on, PAD-312.)"""
    import numpy as np
    from PIL import Image
    from . import dds as _dds
    img = Image.open(path).convert("RGBA")
    if colour is not None:
        img = colour.apply_image(img)
    w, h = img.size
    pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
    arr = np.zeros((ph, pw, 4), np.uint8)
    arr[:h, :w] = np.asarray(img)
    if premultiply:
        a = arr[..., 3:4].astype(np.float32) / 255.0
        arr[..., :3] = (arr[..., :3].astype(np.float32) * a + 0.5).astype(np.uint8)
    return w, h, 5, _dds.encode_bc3(arr)


def _class(scene, name):
    cid = scene.class_id(name)
    if cid is None:
        cid = max(list(scene.classes) + [0]) + 1
        scene.classes[cid] = name
    return cid


def _symbol_of(scene, kind):
    """A symbol key this scene's own objects of *kind* use (a new object copies it, as
    :mod:`scene_write` does)."""
    for o in scene.objects.values():
        if o.kind == kind and isinstance(o.body, dict) and "sym" in o.body:
            return o.body["sym"]
    return None


def apply_scene(scene, ops, assets_dir=None, names=None):
    """Apply *ops* to the :class:`scene_tree.Scene` *scene* in place.  *names*
    ``{node id: name}`` (from the manifest the edits were made on) guards against a card whose
    node of that id is a different node.  Returns ``(applied, [notes])``."""
    from . import scene_tree as T
    notes = []
    applied = 0
    names = names or {}
    fresh = {}                               # preview id of an added node -> id on this card
    nxt = [_max_id(scene) + 1]

    def alloc():
        v = nxt[0]
        nxt[0] += 1
        return v

    for op in ops or ():
        k = op.get("op")
        index = _tree_index(scene)
        try:
            if k in ("move", "scale", "visible", "order", "remove", "tint", "rotate", "shadow",
                     "text_rect", "parent"):
                nid = fresh.get(op["node"], op["node"])
                got = index.get(nid)
                want = names.get(op["node"])
                if got is None or (want is not None and got[0].name != want):
                    notes.append("%s: node %s (%s) is not on this card's scene; left alone"
                                 % (k, op["node"], want or "?"))
                    continue
                n, sibs = got
                if k == "tint":
                    n.colors = [(f, [m[i] * op["mul"][i] for i in range(4)], list(a))
                                for f, m, a in _tint_steps(n.colors)]
                elif k == "move":
                    if not n.tracks:
                        n.tracks = [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
                    n.tracks = [(f, _m16_with(m, _moved(_m6_of16(m), op["dx"], op["dy"])))
                                for f, m in n.tracks]
                elif k == "scale":
                    if not n.tracks:
                        n.tracks = [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
                    n.tracks = [(f, _m16_with(m, _scaled(_m6_of16(m), op["s"],
                                                         op.get("px", 0), op.get("py", 0),
                                                         op.get("sy"))))
                                for f, m in n.tracks]
                elif k == "rotate":
                    if not n.tracks:
                        n.tracks = [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
                    n.tracks = [(f, _m16_with(m, _rotated(_m6_of16(m), op["deg"],
                                                          op.get("px", 0), op.get("py", 0))))
                                for f, m in n.tracks]
                elif k == "shadow":
                    base = n.tracks or [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
                    sh = T.Node(alloc(), n.name + "_Shadow", n.flag, list(n.keyframes),
                                [(f, [m[i] * op["mul"][i] for i in range(4)], list(a))
                                 for f, m, a in _tint_steps(n.colors)],
                                [(f, _m16_with(m, _moved(_m6_of16(m), op["dx"], op["dy"])))
                                 for f, m in base],
                                # the same Text object: the game draws its outline and fill
                                # pairs from one Text the same way
                                [T.Component(c.start, c.cls, c.obj) for c in n.components])
                    fresh[int(op["id"])] = sh.id
                    sibs.insert(sibs.index(n), sh)
                elif k == "visible":
                    if not op["on"]:
                        n.keyframes = [(1, 0)]
                elif k == "order":
                    sibs.remove(n)
                    sibs.insert(max(0, min(len(sibs), int(op["index"]))), n)
                elif k == "parent":
                    kids = _tree_kids_of(index, fresh, op.get("parent"), scene)
                    if op["node"] not in fresh or kids is None:
                        notes.append("parent: node %s cannot go into the group %s on this "
                                     "card's scene; left where it was"
                                     % (op["node"], op.get("parent")))
                        continue
                    m = tuple(op["m"])
                    base = n.tracks or [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
                    n.tracks = [(f, _m16_with(t, _composed(m, _m6_of16(t)))) for f, t in base]
                    sibs.remove(n)
                    kids.insert(max(0, min(len(kids), int(op["index"]))), n)
                elif k == "remove":
                    if op["node"] not in fresh:
                        notes.append("remove: only an added node can be removed (%s is the "
                                     "game's; it is hidden instead)" % op["node"])
                        n.keyframes = [(1, 0)]
                    else:
                        sibs.remove(n)
                elif k == "text_rect":
                    texts = [c.obj for c in n.components if c.obj.kind == "Text"]
                    if not texts:
                        notes.append("text_rect: node %s draws no text; left alone" % op["node"])
                        continue
                    for o in texts:
                        o.body["rect"] = tuple(float(v) for v in op["rect"])
                        if op.get("wrap"):
                            # Multiline + WordWrap: the words re-flow at the rect's width
                            # (PAD-412, emulator: the first byte alone only keeps the breaks)
                            o.body["flags"] = (1, 1)
                applied += 1
            elif k in ("add_picture", "add_text"):
                parent = op.get("parent")
                kids = _tree_kids_of(index, fresh, parent, scene)
                if kids is None:
                    notes.append("%s: the group %s is not on this card's scene"
                                 % (k, parent))
                    continue
                if k == "add_picture":
                    sym = _symbol_of(scene, "Bitmap")
                    if sym is None or not assets_dir:
                        notes.append("add_picture: this scene draws no picture of its own to "
                                     "take the kind from; not added")
                        continue
                    from ...core import colour_profile
                    w, h, fmt, blob = _texture_from_png(
                        os.path.join(assets_dir, "images", *op["image"].split("/")),
                        colour=colour_profile.added_picture_colour(assets_dir, op))
                    tid = alloc()
                    scene.textures[tid] = dict(w=w, h=h, fmt=fmt, name="", blob=blob,
                                               data_off=None)
                    obj = T.Obj(alloc(), "Bitmap", dict(sym=sym, name="", w=w, h=h, tex=tid))
                    cid = _class(scene, "Bitmap")
                else:
                    like = index.get(fresh.get(op["like"], op["like"]))
                    src = None
                    if like:
                        for c in like[0].components:
                            if c.obj.kind == "Text":
                                src = c.obj
                    if src is None:
                        notes.append("add_text: the text to copy is not on this card's scene")
                        continue
                    body = dict(copy.deepcopy(src.body), text=op["text"].encode("utf-8"))
                    if op.get("rgba"):
                        body["rgba"] = list(op["rgba"])
                    if op.get("flags"):
                        body["flags"] = tuple(int(x) for x in op["flags"])
                    obj = T.Obj(alloc(), "Text", body)
                    cid = _class(scene, "Text")
                scene.objects[obj.id] = obj
                nid = alloc()
                fresh[int(op["id"])] = nid
                node = T.Node(nid, op["name"], 1, [(1, 1)], [],
                              [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, op["x"], op["y"], 0, 1])],
                              [T.Component(1, cid, obj)])
                kids.insert(max(0, min(len(kids), int(op.get("index", len(kids))))), node)
                applied += 1
            else:
                notes.append("unknown edit %r" % k)
        except (KeyError, TypeError, ValueError, OSError) as e:
            notes.append("%s: %s" % (k, e))
    return applied, notes


def names_of(man):
    """``{node id: name}`` of a manifest, for :func:`apply_scene`'s guard."""
    return {nid: n["name"] for nid, (n, _k) in _man_index(man).items()}



# ---------------------------------------------------------------------------------------------
# edits the scene already shows (PAD-403): a project extracted from a card a Write built with
# its edits, or a file loaded into the project of the card built from it, has a scene that
# already carries some of its edits.  Every edit is relative (a move adds dx, a resize scales),
# so applying them again on top moves and grows the node twice.  The leading edits a scene
# already shows are found once per scene and left out wherever the edits are applied
# ---------------------------------------------------------------------------------------------
CARRIED_FILENAME = "scene_edits_carried.json"


def _carried_path(assets_dir):
    return os.path.join(assets_dir, *RELDIR, CARRIED_FILENAME)


def _carried_load(assets_dir):
    """``{"carried": {card: {ops, base, names}}, "states": {card: {ops, before, after}}}``."""
    try:
        with open(_carried_path(assets_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for k in ("carried", "states"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


def _carried_save(assets_dir, data):
    path = _carried_path(assets_dir)
    if not data.get("carried") and not data.get("states"):
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


def _r(v):
    return round(float(v), 3)


class _Base:
    """What a scene shows of the nodes edits touch, read off a preview manifest or off a card's
    scene tree: a node's *fingerprint* (its tracks' affines, its text box, hidden or not) and
    how many nodes carry a name."""

    def __init__(self, fps, names):
        self._fps, self._names = fps, names

    def fp(self, nid):
        return self._fps(nid)

    def count(self, name):
        return self._names.get(name, 0)

    @classmethod
    def of_manifest(cls, man):
        index = _man_index(man)
        names = {}
        for n, _k in index.values():
            names[n["name"]] = names.get(n["name"], 0) + 1

        def fps(nid):
            got = index.get(nid)
            if got is None:
                return None
            n = got[0]
            rect = None
            for _s, oid in n["comps"]:
                o = man["objects"].get(str(oid)) or {}
                if o.get("kind") == "Text" and o.get("rect") is not None:
                    rect = [_r(v) for v in o["rect"]]
            return {"m": [[_r(v) for v in m[:6]] for _f, m in n["tr"] or ()],
                    "r": rect, "h": [list(k) for k in n["kf"] or ()] == [[1, 0]]}
        return cls(fps, names)

    @classmethod
    def of_tree(cls, scene):
        index = _tree_index(scene)
        names = {}
        for n, _k in index.values():
            names[n.name] = names.get(n.name, 0) + 1

        def fps(nid):
            got = index.get(nid)
            if got is None:
                return None
            n = got[0]
            rect = None
            for c in n.components:
                if c.obj.kind == "Text" and c.obj.body.get("rect") is not None:
                    rect = [_r(v) for v in c.obj.body["rect"]]
            return {"m": [[_r(v) for v in _m6_of16(m)] for _f, m in n.tracks or ()],
                    "r": rect, "h": [list(k) for k in n.keyframes or ()] == [[1, 0]]}
        return cls(fps, names)


def _near(x, y):
    return abs(x - y) <= 0.01 + 1e-5 * abs(y)


def _close(a, b):
    """Two fingerprints the same within what the card's 32-bit floats keep."""
    if a is None or b is None:
        return a is b
    if a.get("h") != b.get("h") or (a.get("r") is None) != (b.get("r") is None):
        return False
    if a.get("r") is not None and (len(a["r"]) != len(b["r"]) or
                                   not all(_near(x, y) for x, y in zip(a["r"], b["r"]))):
        return False
    ma, mb = a.get("m") or [], b.get("m") or []
    if not ma or not mb:                      # no track = the identity
        ma = ma or [[1, 0, 0, 1, 0, 0]] * max(1, len(mb))
        mb = mb or [[1, 0, 0, 1, 0, 0]] * max(1, len(ma))
    return len(ma) == len(mb) and all(
        len(p) == len(q) and all(_near(x, y) for x, y in zip(p, q)) for p, q in zip(ma, mb))


def _stock_node(op):
    nid = op.get("node")
    return isinstance(nid, int) and not isinstance(nid, bool) and nid < FIRST_ADDED_ID


def _added_names(ops):
    """``{name: nodes of that name the adds in *ops* leave}`` (an add, less a remove of it)."""
    names, ids = {}, {}
    for op in ops:
        if op["op"] in ("add_picture", "add_text") and op.get("name"):
            ids[op.get("id")] = op["name"]
            names[op["name"]] = names.get(op["name"], 0) + 1
        elif op["op"] == "remove" and op.get("node") in ids:
            names[ids[op["node"]]] -= 1
    return names


def states_of(man, ops):
    """What each of *ops* leaves its node looking like on the preview manifest *man* (the
    scene they were made on): ``{"ops", "before": {node: fp}, "after": [fp or None]}``, saved
    beside the edits so a scene that already shows some of them is told exactly."""
    ops = [dict(op) for op in ops or ()]
    base = _Base.of_manifest(man)
    before = {}
    for op in ops:
        if _stock_node(op) and str(op["node"]) not in before:
            before[str(op["node"])] = base.fp(op["node"])
    after, cur = [], man
    for op in ops:
        cur, _n = apply_manifest(cur, [op])
        after.append(_Base.of_manifest(cur).fp(op["node"]) if _stock_node(op) else None)
    return {"ops": ops, "before": before, "after": after}


def _shows(base, ops, k, states=None):
    """Whether *base* looks like the scene with ``ops[:k]`` applied.  With *states*
    (:func:`states_of` of these ops) every node they touch is checked; without, only what
    tells for sure: a text box's last rect and the nodes an add made (the game ships none
    named PAD_...), and at least one of them must be in ``ops[:k]``."""
    names = _added_names(ops[:k])
    for name in _added_names(ops):
        if base.count(name) != names.get(name, 0):
            return False
    if states is not None:
        for nid in {op["node"] for op in ops if _stock_node(op)}:
            want = states["before"].get(str(nid))
            for i in range(k):
                if ops[i].get("node") == nid and states["after"][i] is not None:
                    want = states["after"][i]
            if want is not None and not _close(base.fp(nid), want):
                return False
        return True
    told = bool(names)
    rects = {}
    for op in ops[:k]:
        if op["op"] == "text_rect" and _stock_node(op):
            rects[op["node"]] = [_r(v) for v in op["rect"]]
    for nid, rect in rects.items():
        got = base.fp(nid)
        if got is None or got.get("r") is None or len(got["r"]) != len(rect) or not all(
                _near(x, y) for x, y in zip(got["r"], rect)):
            return False
        told = True
    return told


def _states_for(states, ops):
    """*states* cut to the leading ops they were made for that *ops* still has, or None."""
    if (not isinstance(states, dict) or not isinstance(states.get("after"), list)
            or not isinstance(states.get("before"), dict)):
        return None
    was = states.get("ops") or []
    n = 0
    while n < min(len(was), len(ops), len(states["after"])) and was[n] == ops[n]:
        n += 1
    if n == 0:
        return None
    return {"ops": ops[:n], "before": states["before"], "after": states["after"][:n]}


def shown_count(base, ops, states=None):
    """How many leading *ops* the scene *base* (:class:`_Base`) already shows: 0 for a scene
    as shipped.  Exact with *states* (:func:`states_of`); else the most leading ops nothing on
    the scene goes against, when something on it tells (a text box, a node an add made)."""
    ops = list(ops or ())
    st = _states_for(states, ops)
    if st is not None:
        n = len(st["ops"])
        for k in range(n, -1, -1):
            if _shows(base, ops[:n], k, st):
                return k
    for k in range(len(ops), 0, -1):
        if _shows(base, ops, k):
            return k
    return 0


def _base_info(base, ops):
    """What *base* shows of the nodes *ops* touch, to know the same scene again."""
    return ({str(op["node"]): base.fp(op["node"]) for op in ops if _stock_node(op)},
            {name: base.count(name) for name in _added_names(ops)})


def _same_base(base, rec):
    fps, names = rec.get("base") or {}, rec.get("names") or {}
    return (all(_close(base.fp(int(nid)), fp) for nid, fp in fps.items())
            and all(base.count(name) == n for name, n in names.items()))


def _pending(ops, shown):
    """*ops* without the leading ones in *shown* (the list the scene already carries)."""
    k = 0
    while k < min(len(ops), len(shown)) and ops[k] == shown[k]:
        k += 1
    return list(ops[k:])


def _tellable(ops, states=None):
    """Whether a scene's own edits can tell if it shows them (:func:`_shows`)."""
    return states is not None or any(
        (op["op"] == "text_rect" and _stock_node(op)) or op["op"] in ("add_picture", "add_text")
        for op in ops)


def note_shown(assets_dir, mans, states=None, edits=None):
    """Find (again) which leading edits of each scene in *mans* (``{card: preview manifest}``)
    it already shows, keep it, and return ``{card: how many}``.  *states* (``{card: states}``,
    a loaded file's) are kept for those scenes.

    A scene whose edits are moves and resizes alone cannot tell: it is taken to show them all
    when every scene looked at together that can tell shows all of its own, and one does (a
    project extracted from the card built with them, or the file that card was built from)."""
    data = _carried_load(assets_dir)
    data["states"].update(states or {})
    edits = load(assets_dir) if edits is None else edits
    found, untold, told = {}, [], []
    for card, man in mans.items():
        ops = list(edits.get(card) or ())
        st = _states_for(data["states"].get(card), ops)
        base = _Base.of_manifest(man)
        k = shown_count(base, ops, st)
        found[card] = [base, ops, k]
        (told if _tellable(ops, st) else untold).append(card)
    if (told and untold and all(found[c][2] == len(found[c][1]) for c in told)
            and any(found[c][2] for c in told)):
        for c in untold:
            found[c][2] = len(found[c][1])
    for card, (base, ops, k) in found.items():
        fps, names = _base_info(base, ops)
        data["carried"][card] = {"ops": ops[:k], "base": fps, "names": names}
    _carried_save(assets_dir, data)
    return {card: f[2] for card, f in found.items()}


def _trees_stamp(assets_dir):
    try:
        st = os.stat(os.path.join(assets_dir, *RELDIR, "scene_tree.json"))
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _look_again(assets_dir):
    """The project's scenes read (again) off a card since they were last looked at: every
    edited scene is looked at together (:func:`note_shown`)."""
    stamp = _trees_stamp(assets_dir)
    data = _carried_load(assets_dir)
    if stamp is None or data.get("trees") == stamp:
        return
    trees = trees_of(assets_dir)
    edits = load(assets_dir)
    note_shown(assets_dir, {c: trees[c] for c in edits if c in trees}, edits=edits)
    data = _carried_load(assets_dir)
    data["trees"] = stamp
    _carried_save(assets_dir, data)


def _carries(assets_dir, card, ops):
    """Whether *ops*' last is one of the leading edits *card*'s scene already shows."""
    shown = shown_ops(assets_dir, card)
    return bool(ops) and len(ops) <= len(shown) and ops == shown[:len(ops)]


def shown_ops(assets_dir, card):
    """The leading edits of *card* its scene in this project already shows (``[]``: none)."""
    rec = _carried_load(assets_dir)["carried"].get(card) or {}
    return list(rec.get("ops") or ())


def to_apply(assets_dir, card, man, ops=None):
    """*card*'s edits (or *ops*) less the leading ones its preview manifest *man* already
    shows.  The first look at the project's scenes, or at scenes read again off a card, finds
    them; a scene first edited after that is looked at on its own."""
    ops = ops_for(assets_dir, card) if ops is None else list(ops)
    if not ops or man is None:
        return ops
    _look_again(assets_dir)
    rec = _carried_load(assets_dir)["carried"].get(card)
    if rec is None or not _same_base(_Base.of_manifest(man), rec):
        note_shown(assets_dir, {card: man}, edits={card: ops})
        rec = _carried_load(assets_dir)["carried"].get(card) or {}
    return _pending(ops, rec.get("ops") or [])


def to_apply_on_card(assets_dir, card, scene, ops):
    """*ops* less the leading ones the card's own scene tree *scene* already shows (a Write
    from a card built with them).  The project's finding holds when the card shows what the
    project's scene does; else the card is looked at on its own, and nothing is kept."""
    ops = list(ops or ())
    if not ops or not assets_dir:
        return ops
    data = _carried_load(assets_dir)
    base = _Base.of_tree(scene)
    rec = data["carried"].get(card)
    if rec is not None and _same_base(base, rec):
        return _pending(ops, rec.get("ops") or [])
    return ops[shown_count(base, ops, data["states"].get(card)):]


def keep_states(assets_dir, cards_states):
    """Keep ``{card: states}`` (:func:`states_of`) of scenes a Write built: a project extracted
    from that card again shows them all, and is told so exactly."""
    if not cards_states:
        return
    data = _carried_load(assets_dir)
    data["states"].update(cards_states)
    _carried_save(assets_dir, data)


def states_to_save(assets_dir, edits, trees):
    """``{card: states}`` of *edits* on this project's *trees* (:func:`states_of`): worked out
    on the scene when it shows none of them, else the ones kept for them; none when neither."""
    data = _carried_load(assets_dir)
    out = {}
    for card, ops in (edits or {}).items():
        man = (trees or {}).get(card)
        if not ops or man is None:
            continue
        try:                                         # a save never fails on it
            to_apply(assets_dir, card, man, ops)     # the scene looked at first
            mine = not shown_ops(assets_dir, card)
            if mine:
                out[card] = states_of(man, ops)
        except Exception:                            # noqa: BLE001
            continue
        if not mine:
            st = _states_for(data["states"].get(card), ops)
            if st is not None and len(st["ops"]) == len(ops):
                out[card] = st
    return out
