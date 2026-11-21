"""How big the game shows each scene picture, worked out from the project alone (Simon, 2026-11-21).

The Images tab's resolution columns (Simon's words):

* **Original** - "the resolution of the original asset pulled from the raw image";
* **Imported** - "the resolution of your graphic you chose";
* **Current** - "the highest resolution you have set by scaling for the asset in the scenes; you may have other
  lower resolutions set": the biggest the game draws the picture on the glass, over every place that draws it,
  with the Scenes tab's layout on - its box times its biggest zoom (:func:`radium_grow.shown_scale` reads the
  same off the card's scene);
* **Written** - "the maximum resolution PAD will write to the card": the imported picture, never enlarged, at no
  more than Current.

The measurement runs on the project's scene manifests (``scene_tree.json``, :mod:`scene_eval`) with the Scenes
tab's edits applied (:func:`scene_edit.apply_manifest`), so it follows the layout as it is now, and a picture
drawn at its own size (a layout made over it, PAD-981, or a pick placed pixel for pixel,
:data:`scene_edit.PLACE_KEY`) is measured at its own size.
"""
from __future__ import annotations

import math
import os

#: the scene pictures' folder under the project's ``images``
SCENE_DIR = "scene_textures/"


def _scale6(m):
    a, b, c, d = m[:4]
    return max(math.hypot(a, b), math.hypot(c, d))


def man_zooms(man):
    """``{node id: biggest scale}`` over a preview manifest: each node's own tracks' biggest times its groups',
    down from the root (an upper bound where they peak at different moments); a node its timeline never shows,
    and what is under it, is left out."""
    objs = man.get("objects") or {}
    out = {}

    def run(kids, up, path):
        for n in kids or ():
            kf = n.get("kf") or []
            if kf and not any(v for _f, v in kf):
                continue
            z = up * max((_scale6(m) for _f, m in n.get("tr") or ()), default=1.0)
            nid = n.get("id")
            out[nid] = max(out.get(nid, 0.0), z)
            for _s, oid in n.get("comps") or ():
                o = objs.get(str(oid)) or {}
                if o.get("kids") is not None and oid not in path:
                    run(o["kids"], z, path | {oid})
    run((man.get("root") or {}).get("kids"), 1.0, frozenset())
    return out


def man_scales(man, natural_of):
    """``{picture rel: biggest scale}`` (1.0 = one pixel of the picture to one of the screen) of every picture a
    manifest draws, for pictures of the sizes *natural_of* gives (``rel -> (w, h)`` or None).  A Bitmap's node
    fits the picture into its box (PAD-865) unless it is marked ``own`` (drawn at its own size, or fitted into
    its ``own_box``, :func:`scene_edit.mark_own`); a Shape squeezes it into the Shape's box."""
    objs = man.get("objects") or {}
    zooms = man_zooms(man)
    out = {}

    def note(rel, s):
        if rel and s > 0:
            out[rel] = max(out.get(rel, 0.0), s)

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
            if o.get("kind") == "Bitmap" and o.get("image"):
                nat = natural_of(o["image"])
                if not nat or not (nat[0] and nat[1]):
                    continue
                if n.get("own"):
                    box = n.get("own_box")
                    u = min(box[0] / float(nat[0]), box[1] / float(nat[1])) if box else 1.0
                else:
                    u = min((o.get("w") or nat[0]) / float(nat[0]), (o.get("h") or nat[1]) / float(nat[1]))
                note(o["image"], u * z)
            elif o.get("kind") == "Shape" and o.get("fill") is not None:
                f = objs.get(str(o["fill"])) or {}
                nat = natural_of(f.get("image")) if f.get("image") else None
                r = o.get("rect") or ()
                if not nat or len(r) != 4 or not (nat[0] and nat[1]):
                    continue
                rw, rh = abs(r[2] - r[0]), abs(r[3] - r[1])
                if rw and rh:
                    note(f["image"], min(rw / float(nat[0]), rh / float(nat[1])) * z)
    return out


def size_at(natural, scale):
    """``(w, h)``: a picture of *natural* size shown at *scale* (not capped: bigger than the picture means the
    game enlarges it)."""
    return (max(1, int(math.ceil(natural[0] * scale - 1e-6))),
            max(1, int(math.ceil(natural[1] * scale - 1e-6))))


def written_size(natural, scale):
    """``(w, h)`` the Write puts a picture kept at its own size on the card at: its *natural* size, shown at most
    at *scale*, never enlarged (engine._kept_size)."""
    return size_at(natural, min(1.0, scale))


def scene_scales(assets_dir, natural_of):
    """``{rel under images/: biggest scale}`` over every scene of the project (:func:`man_scales`), with the
    Scenes tab's edits on and the pictures drawn at their own size marked."""
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
        try:
            scene_edit.mark_own_of(man, assets_dir, card)
        except Exception:                           # noqa: BLE001
            pass
        for rel, s in man_scales(man, natural_of).items():
            out[rel] = max(out.get(rel, 0.0), s)
    return out


_CACHE = {}


def _stamp(assets_dir):
    from . import scene_edit
    paths = (os.path.join(assets_dir, "images", "scene_textures", "scene_tree.json"),
             scene_edit.path_of(assets_dir),
             os.path.join(assets_dir, ".staged_changes.json"))
    out = []
    for p in paths:
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def columns(assets_dir, rows):
    """The four resolution columns for *rows* ``{rel (images/...): (original (w, h) or None, imported (w, h) or
    None)}``: ``{rel: {"o": original, "i": imported, "c": current, "w": written, "z": biggest zoom of the
    picture, "fixed": True where the size can't change}}``, each size a ``[w, h]`` list or None.

    Current and Written are worked out only for scene pictures; any other picture is written at the original's
    size (``fixed``).  Cached per project until its scenes, edits or picks change."""
    key = (os.path.normcase(os.path.abspath(assets_dir or "")), _stamp(assets_dir) if assets_dir else None)
    natural = {}
    for rel, (orig, imp) in rows.items():
        if rel.startswith("images/" + SCENE_DIR):
            natural[rel[len("images/"):]] = imp or orig
    cached = _CACHE.get(key[0])
    if cached and cached[0] == key[1] and cached[1] == natural:
        scales = cached[2]
    else:
        scales = scene_scales(assets_dir, natural.get) if assets_dir and natural else {}
        _CACHE[key[0]] = (key[1], dict(natural), scales)
    out = {}
    for rel, (orig, imp) in rows.items():
        cell = {"o": list(orig) if orig else None, "i": list(imp) if imp else None,
                "c": None, "w": None, "z": None, "fixed": False}
        nat = imp or orig
        s = scales.get(rel[len("images/"):]) if rel.startswith("images/" + SCENE_DIR) else None
        if s is not None and nat:
            cell["c"] = list(size_at(nat, s))
            cell["z"] = round(s, 3)
            if imp:
                cell["w"] = list(written_size(imp, s))
        elif rel.startswith("images/" + SCENE_DIR):
            if imp:
                cell["w"] = list(imp)
        else:
            cell["fixed"] = True
            cell["c"] = list(orig) if orig else None
            if imp:
                cell["w"] = list(orig) if orig else list(imp)
        out[rel] = cell
    return out
