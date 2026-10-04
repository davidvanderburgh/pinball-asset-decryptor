"""Scenes saved with everything they show (PAD-369, DragonRR).

A file of scene edits (:func:`scene_edit.export_edits`, PAD-281) carries the moves, resizes,
tints, hidden layers and added pictures and text.  Saved "with pictures and color profiles" it
also carries, for the pictures those scenes draw:

* each picture replaced on the Images tab: the replacement file itself, its Keep size tick, its
  color switch and the color profile baked into it (its own, else the project's individual
  files profile, so it looks the same in a project with another one);
* the color switch and profile of each picture added in Scenes;
* the project's whole screen overlay.

The machine screen is not carried: it describes the screen of the PC or machine it was set on.

Loading never deletes or overwrites a file: the pictures are copied into
``<project>/Shared pictures/<file name>/`` (a name already there with other bytes gets a new
one), and each replaced picture's pick points at its copy.  What it changes in the project
(a pick made here, the overlay) is listed by :func:`clashes` so the page can ask first.

The extras sit beside ``scenes`` in the same manifest, so a PAD from before reads the edits
of such a file as it always did and leaves the rest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile

from . import scene_edit

#: where the pictures of a loaded file are copied, inside the project folder
SHARED_DIR = "Shared pictures"


def manifest_pictures(man):
    """Every picture (rel under ``images/``) the stock scene *man* (a preview manifest) can
    draw: its bitmaps, shape fills and flipbook frames."""
    out = set()
    for o in ((man or {}).get("objects") or {}).values():
        if not isinstance(o, dict):
            continue
        k = o.get("kind")
        if k == "Bitmap":
            out.add(o.get("image"))
        elif k == "Shape" and o.get("fill") is not None:
            out.add((man["objects"].get(str(o["fill"])) or {}).get("image"))
        elif k == "StreamingFlipbook":
            out.update(fr.get("image") for fr in o.get("seq") or () if isinstance(fr, dict))
    return {r for r in out if isinstance(r, str) and r}


def _profile_raw(data, rel):
    """What a switched-on picture *rel* (a sidecar key) has baked in, as stored: its own
    profile, else the project's individual files profile, else the Recommended one (which
    follows the screen of the project it is loaded into, as it does here)."""
    from ...core import colour_profile as cp
    own = cp._own_dicts(data, "images").get(rel)
    if isinstance(own, dict):
        return dict(own)
    shared = data.get(cp.ASSET_KEY)
    return dict(shared) if isinstance(shared, dict) else {"recommended": True}


def _source(assets_dir, data, rel, built):
    """The file replacing picture *rel* (``images/...``), or None: the pick, or for a picture
    an earlier build put in the project, that picture (its uncorrected copy when kept)."""
    from ...core import colour_profile as cp
    src = (data.get("image") or {}).get(rel)
    if isinstance(src, str) and src and os.path.isfile(src):
        return src
    if rel in built:
        for p in (cp.uncorrected_path(assets_dir, rel),
                  os.path.join(assets_dir, *rel.split("/"))):
            if p and os.path.isfile(p):
                return p
    return None


def gather(assets_dir, cards, trees):
    """``(edits, extras)`` to save for *cards* (None: every scene of *trees*, ``{card: stock
    manifest}``): their edits, and the pictures, profiles and overlay described above."""
    from ...core import colour_profile as cp, staged_changes
    edits = scene_edit.load(assets_dir)
    want = list(trees) if cards is None else [c for c in cards if c in trees]
    edits = {c: edits[c] for c in want if edits.get(c)}
    data = staged_changes.load(assets_dir) or {}
    built = cp.built_image_rels(assets_dir, data)
    settings = cp.asset_settings(assets_dir)
    keep = set(data.get("image_keep_size") or ())
    pictures = {}
    for pic in sorted(set().union(*(manifest_pictures(trees[c]) for c in want)) if want else ()):
        rel = "images/" + pic
        src = _source(assets_dir, data, rel, built)
        if src is None:
            continue
        on = cp.asset_applies(settings, "images", rel)
        pictures[rel] = {"src": src, "name": os.path.basename(src), "keep": rel in keep,
                         "color": on, "profile": _profile_raw(data, rel) if on else None}
    added = {}
    for ops in edits.values():
        for op in ops:
            img = op.get("image") if op.get("op") == "add_picture" else None
            if not img or img in added:
                continue
            on = cp.asset_applies(settings, "images", img, own=op.get("color"))
            added[img] = {"color": on, "profile": _profile_raw(data, img) if on else None}
    overlay = data.get(cp.KEY)
    extras = {"pictures": pictures, "added": added,
              "overlay": dict(overlay) if isinstance(overlay, dict) else None}
    return edits, extras


def export_all(assets_dir, zip_path, cards, trees):
    """Save *cards* (None: every scene) with their pictures and color profiles to
    *zip_path*.  Returns ``(scenes with edits, pictures)`` written; raises
    :class:`scene_edit.SceneEditError` when there is nothing to save."""
    edits, extras = gather(assets_dir, cards, trees)
    if not edits and not extras["pictures"]:
        raise scene_edit.SceneEditError(
            "there are no scene edits or replaced pictures to save")
    added_files = sorted({op["image"] for ops in edits.values() for op in ops
                          if op["op"] == "add_picture" and scene_edit._safe_rel(op.get("image"))})
    pictures = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (rel, p) in enumerate(sorted(extras["pictures"].items())):
            member = "replaced/%d/%s" % (i, re.sub(r"[\\/:*?\"<>|]+", "_", p["name"]) or "picture")
            z.write(p["src"], member)
            pictures[rel] = {k: v for k, v in p.items() if k != "src"}
            pictures[rel]["file"] = member
        for rel in added_files:
            src = os.path.join(assets_dir, "images", *rel.split("/"))
            if os.path.isfile(src):
                z.write(src, "images/" + rel)
        doc = {"format": 1, "kind": scene_edit.SHARE_KIND, "scenes": edits,
               "pictures": pictures, "added": extras["added"]}
        if extras["overlay"] is not None:
            doc["overlay"] = extras["overlay"]
        z.writestr(scene_edit.SHARE_MANIFEST, json.dumps(doc, indent=1, sort_keys=True))
    return len(edits), len(pictures)


def read_extras(zip_path):
    """``{"pictures", "added", "overlay"}`` of a file :func:`export_all` wrote (empty for a
    file of edits alone)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            doc = json.loads(z.read(scene_edit.SHARE_MANIFEST).decode("utf-8"))
            members = set(z.namelist())
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise scene_edit.SceneEditError("%s is not a file of scene edits saved by PAD"
                                        % os.path.basename(zip_path)) from None
    if not isinstance(doc, dict):
        doc = {}
    pictures = {}
    for rel, p in (doc.get("pictures") or {}).items() if isinstance(
            doc.get("pictures"), dict) else ():
        if (isinstance(rel, str) and rel.startswith("images/") and scene_edit._safe_rel(rel)
                and isinstance(p, dict) and p.get("file") in members):
            pictures[rel] = p
    added = {r: a for r, a in (doc.get("added") or {}).items()
             if isinstance(r, str) and isinstance(a, dict)} if isinstance(
                 doc.get("added"), dict) else {}
    overlay = doc.get("overlay") if isinstance(doc.get("overlay"), dict) else None
    return {"pictures": pictures, "added": added, "overlay": overlay}


def has_extras(extras):
    return bool(extras["pictures"] or extras["added"] or extras["overlay"])


def _here(assets_dir, rel):
    """Does this project have picture *rel* (``images/...``)?"""
    return os.path.isfile(os.path.join(assets_dir, *rel.split("/")))


def clashes(assets_dir, extras):
    """What loading *extras* would change of the user's own here: ``{"pictures": [rel, ...]
    with another replacement here], "overlay": True when the overlay here differs}``."""
    from ...core import colour_profile as cp, staged_changes
    data = staged_changes.load(assets_dir) or {}
    picks = data.get("image") or {}
    built = cp.built_image_rels(assets_dir, data)
    pics = []
    for rel in sorted(extras["pictures"]):
        if not _here(assets_dir, rel):
            continue
        mine = picks.get(rel)
        if mine or rel in built:
            pics.append(rel)
    mine = data.get(cp.KEY)
    overlay = bool(extras["overlay"] is not None and extras["overlay"] != mine)
    return {"pictures": pics, "overlay": overlay}


def _digest(data):
    return hashlib.sha1(data).hexdigest()


def import_extras(assets_dir, zip_path, extras, renamed=None, overlay=True):
    """Put *extras* (:func:`read_extras` of *zip_path*) into the project: each replaced
    picture copied into :data:`SHARED_DIR` and picked, with its Keep size tick, color switch
    and profile; each added picture's switch and profile (*renamed*: ``{its rel in the file:
    its rel here}`` from :func:`scene_edit.import_edits`); the overlay when *overlay*.
    A picture this project does not have is left out.  Nothing is deleted or overwritten.  Returns ``(pictures loaded, [picture of the file not here])``."""
    from ...core import colour_profile as cp, staged_changes
    renamed = renamed or {}
    stem = os.path.splitext(os.path.basename(zip_path))[0]
    stem = re.sub(r"[\\/:*?\"<>|]+", "_", stem).strip(" .") or "scenes"
    folder = os.path.join(assets_dir, SHARED_DIR, stem)
    data = staged_changes.load(assets_dir) or {}
    picks = dict(data.get("image") or {})
    keep = set(data.get("image_keep_size") or ())
    slots_on = dict(data.get(cp.IMAGE_SLOTS_KEY) or {})
    owns = dict(cp._own_dicts(data, "images"))
    loaded, missing = [], []

    def _own(rel, a):
        if a.get("color") is None:
            return
        slots_on[rel] = bool(a["color"])
        if a.get("color") and isinstance(a.get("profile"), dict):
            owns[rel] = dict(a["profile"])
        else:
            owns.pop(rel, None)

    with zipfile.ZipFile(zip_path) as z:
        for rel, p in sorted(extras["pictures"].items()):
            if not _here(assets_dir, rel):
                missing.append(rel)
                continue
            blob = z.read(p["file"])
            name = os.path.basename(p.get("name") or p["file"]) or "picture.png"
            name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
            base, ext = os.path.splitext(name)
            dest, n = os.path.join(folder, name), 2
            while os.path.exists(dest):
                with open(dest, "rb") as f:
                    if _digest(f.read()) == _digest(blob):
                        break
                dest, n = os.path.join(folder, "%s_%d%s" % (base, n, ext)), n + 1
            if not os.path.exists(dest):
                os.makedirs(folder, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(blob)
            picks[rel] = dest
            if p.get("keep"):
                keep.add(rel)
            else:
                keep.discard(rel)
            _own(rel, p)
            loaded.append(rel)
    for rel, a in extras["added"].items():
        _own(renamed.get(rel, rel), a)
    data["image"] = picks
    data["image_keep_size"] = sorted(r for r in keep if r in picks)
    for key, val in ((cp.IMAGE_SLOTS_KEY, slots_on), (cp.FILE_PROFILES_KEY["images"], owns)):
        if val:
            data[key] = val
        else:
            data.pop(key, None)
    if overlay and extras["overlay"] is not None:
        data[cp.KEY] = dict(extras["overlay"])
    staged_changes.save(assets_dir, data)
    return loaded, missing
