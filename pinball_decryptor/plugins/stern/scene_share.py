"""Scenes saved with everything they show (PAD-369, DragonRR).

A file of scene edits (:func:`scene_edit.export_edits`, PAD-281) carries the moves, resizes,
tints, hidden layers and added pictures and text.  Saved "with pictures and color profiles" it
also carries, for the pictures those scenes draw:

* each picture replaced on the Images tab: the replacement file itself, its Keep size tick, its
  color switch and the color profile baked into it (its own, else the project's individual
  files profile, so it looks the same in a project with another one);
* the color switch and profile of each picture added in Scenes;
* the project's whole screen overlay;
* the Text tab's edits of those scenes' words (PAD-387).

Every scene saved this way also carries every other picture replaced on the Images tab (the
boot screen, the game's splash, any picture no scene draws) and every Text tab edit, the game
program's words too: the project's whole look in one file, sounds, videos and modes aside.

The machine screen is not carried: it describes the screen of the PC or machine it was set on.

Loading never deletes or overwrites a file: the pictures are copied into
``<project>/Shared pictures/<file name>/`` (a name already there with other bytes gets a new
one), and each replaced picture's pick points at its copy.  What it changes in the project
(a pick made here, the overlay) is listed by :func:`clashes` so the page can ask first.

The extras sit beside ``scenes`` in the same manifest, so a PAD from before reads the edits
of such a file as it always did and leaves the rest.

A scene picture's extracted name ends in a hash of its bytes on the card it came from, so a
project extracted from a card built with changes names a replaced picture differently from a
project extracted from the stock card.  Each saved picture therefore also says which nodes of
its scenes draw it (``drawn``, PAD-385), and :func:`localise` finds the picture those nodes draw
in the project it is loaded into.  A text edit is keyed by its scene and original words, as the
Text tab's own file of edits is (PAD-300); it also says which Text nodes show those words
(``nodes``, a scene's) and the words of the lines either side of it (``near``), so
:func:`match_text` finds the line on a card whose words were built differently.
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


def manifest_drawers(man):
    """``{picture: [[node], [node, frame], ...]}``: every picture (rel under ``images/``) the
    stock scene *man* (a preview manifest) can draw, and the nodes drawing it - a bitmap or a
    shape fill's bitmap by its id, a flipbook frame by the flipbook's id and the frame's index.
    Node ids are the same on every copy of a scene, whatever pictures the card was built with."""
    objs = (man or {}).get("objects") or {}
    out = {}

    def note(img, where):
        if isinstance(img, str) and img and where not in out.setdefault(img, []):
            out[img].append(where)
    for key, o in objs.items():
        if not isinstance(o, dict):
            continue
        k = o.get("kind")
        if k == "Bitmap":
            note(o.get("image"), [str(key)])
        elif k == "Shape" and o.get("fill") is not None:
            note((objs.get(str(o["fill"])) or {}).get("image"), [str(o["fill"])])
        elif k == "StreamingFlipbook":
            for i, fr in enumerate(o.get("seq") or ()):
                if isinstance(fr, dict):
                    note(fr.get("image"), [str(key), i])
    return out


def manifest_pictures(man):
    """Every picture (rel under ``images/``) the stock scene *man* can draw: its bitmaps,
    shape fills and flipbook frames."""
    return set(manifest_drawers(man))


def _drawn_image(man, node, frame=None):
    """The picture node *node* (a flipbook's: its frame *frame*) of scene *man* draws, or None."""
    o = ((man or {}).get("objects") or {}).get(str(node))
    if not isinstance(o, dict):
        return None
    if frame is not None:
        seq = o.get("seq") or ()
        o = seq[frame] if isinstance(frame, int) and 0 <= frame < len(seq) else None
        if not isinstance(o, dict):
            return None
    img = o.get("image")
    return img if isinstance(img, str) and img else None


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
    manifest}``, and then every replaced picture and text edit of the project): their edits,
    and the pictures, profiles, overlay and text described above."""
    from ...core import colour_profile as cp, staged_changes
    edits = scene_edit.load(assets_dir)
    want = list(trees) if cards is None else [c for c in cards if c in trees]
    edits = {c: edits[c] for c in want if edits.get(c)}
    data = staged_changes.load(assets_dir) or {}
    built = cp.built_image_rels(assets_dir, data)
    settings = cp.asset_settings(assets_dir)
    keep = set(data.get("image_keep_size") or ())
    drawn = {}
    for c in want:
        for pic, nodes in manifest_drawers(trees[c]).items():
            drawn.setdefault(pic, []).extend([c] + n for n in nodes)
    rels = {"images/" + pic for pic in drawn}
    if cards is None:
        # the whole project: the pictures no scene draws too (PAD-387)
        rels.update(r for r in set(data.get("image") or ()) | built
                    if isinstance(r, str) and r.startswith("images/") and scene_edit._safe_rel(r))
    pictures = {}
    for rel in sorted(rels):
        src = _source(assets_dir, data, rel, built)
        if src is None:
            continue
        on = cp.asset_applies(settings, "images", rel)
        pictures[rel] = {"src": src, "name": os.path.basename(src), "keep": rel in keep,
                         "color": on, "profile": _profile_raw(data, rel) if on else None}
        if drawn.get(rel[len("images/"):]):
            pictures[rel]["drawn"] = drawn[rel[len("images/"):]]
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
              "overlay": dict(overlay) if isinstance(overlay, dict) else None,
              "text": text_to_save(assets_dir, cards, trees)}
    return edits, extras


def export_all(assets_dir, zip_path, cards, trees):
    """Save *cards* (None: every scene, and the whole project's look) with their pictures,
    color profiles and text to *zip_path*.  Returns ``(scenes with edits, pictures, text
    edits)`` written; raises :class:`scene_edit.SceneEditError` when there is nothing to
    save."""
    edits, extras = gather(assets_dir, cards, trees)
    if not edits and not extras["pictures"] and not extras["text"]:
        raise scene_edit.SceneEditError(
            "there are no scene edits, replaced pictures or text edits to save")
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
        if extras["text"]:
            doc["text"] = extras["text"]
        states = scene_edit.states_to_save(assets_dir, edits, trees)
        if states:
            doc["states"] = states                   # PAD-403
        z.writestr(scene_edit.SHARE_MANIFEST, json.dumps(doc, indent=1, sort_keys=True))
    return len(edits), len(pictures), len(extras["text"])


def read_extras(zip_path):
    """``{"pictures", "added", "overlay", "text"}`` of a file :func:`export_all` wrote (empty
    for a file of edits alone)."""
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
    text = []
    for e in doc.get("text") if isinstance(doc.get("text"), list) else ():
        if (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in
                                        ("path", "original", "new")) and e["new"]):
            nodes = e.get("nodes") if isinstance(e.get("nodes"), list) else []
            near = e.get("near")
            near = ([w if isinstance(w, str) else None for w in near]
                    if isinstance(near, list) and len(near) == 2 else None)
            text.append({"path": e["path"], "original": e["original"], "new": e["new"],
                         "nodes": [str(n) for n in nodes if isinstance(n, (str, int))],
                         "near": near})
    return {"pictures": pictures, "added": added, "overlay": overlay, "text": text}


def has_extras(extras):
    return bool(extras["pictures"] or extras["added"] or extras["overlay"])


def _here(assets_dir, rel):
    """Does this project have picture *rel* (``images/...``)?"""
    return os.path.isfile(os.path.join(assets_dir, *rel.split("/")))


def _other_game_folder(assets_dir, rel):
    """The one picture here of *rel*'s path in another game folder (``images/godzilla_pro/x``
    of the file is ``images/godzilla_le/x`` here, PAD-401), or None."""
    parts = rel.split("/")
    if len(parts) < 3 or parts[0] != "images" or parts[1] == "scene_textures":
        return None
    try:
        dirs = os.listdir(os.path.join(assets_dir, "images"))
    except OSError:
        return None
    same = ["/".join(["images", d] + parts[2:]) for d in sorted(dirs)
            if d != parts[1] and d != "scene_textures"]
    same = [h for h in same if _here(assets_dir, h)]
    return same[0] if len(same) == 1 else None


def localise(assets_dir, extras, trees):
    """*extras* (:func:`read_extras`) with its replaced pictures named as this project names
    them (PAD-385).  A picture this project has under the file's name keeps it.  One it does
    not is looked up by the nodes that draw it in the file's scenes (*trees*: this project's
    ``{card: stock manifest}``) and takes the name of what they draw here - every such picture,
    when they draw more than one.  A picture here that two of the file's pictures lead to, or
    that the file names itself, goes to neither by lookup.  A picture with nothing found (a
    file saved before PAD-385, a scene this card does not have) keeps the file's name and is
    left out at load, as before.  A picture no scene draws (a boot screen, a backglass logo) is
    found in the other game folder here (le/pro folders matched, PAD-401)."""
    pics = extras.get("pictures") or {}
    if not pics:
        return extras
    find = scene_edit.card_finder((trees or {}).keys())
    found = {}
    for rel, p in pics.items():
        if _here(assets_dir, rel):
            continue
        other = _other_game_folder(assets_dir, rel)
        if other:
            found[rel] = {other}
            continue
        heres = set()
        for d in p.get("drawn") or ():
            if not (isinstance(d, list) and len(d) in (2, 3) and isinstance(d[0], str)):
                continue
            card = find(d[0])
            img = _drawn_image((trees or {}).get(card), *d[1:]) if card else None
            here = scene_edit._safe_rel("images/" + img) if img else None
            if here and _here(assets_dir, here):
                heres.add(here)
        if heres:
            found[rel] = heres
    claims = {}
    for rel, heres in found.items():
        for here in heres:
            claims.setdefault(here, []).append(rel)
    out = {}
    for rel, p in sorted(pics.items()):
        mine = [h for h in sorted(found.get(rel, ())) if claims[h] == [rel] and h not in pics]
        for here in mine or [rel]:
            out[here] = p
    return dict(extras, pictures=out)


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


def _ops_words(ops):
    """A scene's edits in a few words: ``2 edits: moved +25,+0, 50 %``."""
    words = [scene_edit.describe(op) for op in ops[:3]]
    more = len(ops) - len(words)
    return "%d edit%s: %s%s" % (len(ops), "" if len(ops) == 1 else "s", ", ".join(words),
                                " and %d more" % more if more else "")


def conflict_items(assets_dir, over, extras, clash, tclash, label_of=None):
    """PAD-402 (DragonRR): one row per thing of the user's own here a load would change, for
    the page to ask about each: ``[{"id", "what", "mine", "theirs"}]``.  *over* ``{card here:
    (my ops, the file's ops)}``; *clash* :func:`clashes`; *tclash* ``[(Text tab row, the
    file's words)]``; *label_of* names a scene of a card path.  Ids: ``scene:<card>``,
    ``picture:<rel>``, ``overlay``, ``text:<n>`` (n-th of *tclash*)."""
    from ...core import colour_profile as cp, staged_changes
    label_of = label_of or (lambda card: card.rstrip("/").split("/")[-2][:8])
    items = []
    for card, (mine, theirs) in over.items():
        items.append({"id": "scene:" + card, "what": "Scene " + label_of(card),
                      "mine": _ops_words(mine), "theirs": _ops_words(theirs)})
    data = staged_changes.load(assets_dir) or {}
    picks = data.get("image") or {}
    for rel in clash["pictures"]:
        mine = picks.get(rel)
        items.append({"id": "picture:" + rel, "what": "Picture " + os.path.basename(rel),
                      "mine": ("replaced by " + os.path.basename(mine)) if mine
                      else "changed on the card you built",
                      "theirs": "replaced by " + os.path.basename(
                          extras["pictures"][rel].get("name") or "a picture")})
    if clash["overlay"]:
        mine = data.get(cp.KEY)
        items.append({"id": "overlay", "what": "Whole screen overlay",
                      "mine": ((mine or {}).get("name") or "your own") if mine else "none",
                      "theirs": (extras["overlay"] or {}).get("name") or "the file's own"})
    for i, (r, new) in enumerate(tclash):
        items.append({"id": "text:%d" % i, "what": 'Text "%s"' % r["original"],
                      "mine": '"%s"' % r["replacement"], "theirs": '"%s"' % new})
    return items


def backup(assets_dir, loading, trees):
    """PAD-402: save every scene's edits, replaced picture, color profile and text edit of the
    project, as Save every scene... does, to a new file in its Backups folder before *loading*
    is loaded: loading that file puts them back.  Returns its path, or None when there is
    nothing to save."""
    from .mode_project import backup_path
    path = backup_path(assets_dir, loading)
    try:
        export_all(assets_dir, path, None, trees)
    except scene_edit.SceneEditError:
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return path


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


# ---------------------------------------------------------------------------------------------
# the Text tab's edits (PAD-387)
# ---------------------------------------------------------------------------------------------
def _text_nodes(man, original):
    """Ids of the Text nodes of scene *man* showing *original* (in the manifest's flattened
    form of a line with breaks)."""
    from ...core import text_manifest
    objs = (man or {}).get("objects") or {}
    return sorted((str(k) for k, o in objs.items()
                   if isinstance(o, dict) and o.get("kind") == "Text"
                   and text_manifest.escape_cell(o.get("text") or "") == original),
                  key=lambda k: (len(k), k))


def _neighbours(rows):
    """``{id(row): [original of the row before it, of the row after it]}`` among the rows of
    its own scene or program, in manifest order (None past either end)."""
    by_path = {}
    for r in rows:
        by_path.setdefault(r["path"], []).append(r)
    out = {}
    for same in by_path.values():
        for i, r in enumerate(same):
            out[id(r)] = [same[i - 1]["original"] if i else None,
                          same[i + 1]["original"] if i + 1 < len(same) else None]
    return out


def text_to_save(assets_dir, cards, trees):
    """The Text tab's edits to save for *cards* (None: every edit of the project, the game
    program's words too), ``[{"path", "original", "new", "near", "nodes"?}]``: *near* the
    original words of the rows on either side of it, *nodes* the Text nodes showing it."""
    from ...core import text_manifest
    want = None if cards is None else set(cards)
    rows = text_manifest.load(assets_dir)
    near = _neighbours(rows)
    out = []
    for r in rows:
        new = r.get("replacement") or ""
        if not new or new == r["original"] or (want is not None and r["path"] not in want):
            continue
        e = {"path": r["path"], "original": r["original"], "new": new, "near": near[id(r)]}
        nodes = _text_nodes((trees or {}).get(r["path"]), r["original"])
        if nodes:
            e["nodes"] = nodes
        out.append(e)
    return out


def match_text(saved, rows, trees, already=None):
    """Pair each saved text edit with a row of this project's manifest *rows*
    (:func:`text_manifest.load`) of the same scene or program (le/pro folders matched):

    1. the row with the same original words, the n-th copy for the n-th edit;
    2. else, for a scene line, the row of the words the same Text nodes show here;
    3. else the one row here between rows of the same words as the saved one's neighbours.

    2 and 3 find a line on a card that was built with other words there (the file saved from
    a project extracted from a card built with changes).  Returns ``(pairs, missing)``:
    ``[(row, new)]`` and the saved edits with no row here.

    An edit whose new words a line of its scene or program already shows here, when no line
    here has its original words or only one the game no longer reads (``unused``: the build
    moved the line's longer words elsewhere), is already on this card (PAD-401: a modder's
    own file loaded into the project of the card built from it): it goes to the *already*
    list when one is given, and is neither paired nor missing."""
    from ...core import text_manifest
    find = scene_edit.card_finder({r["path"] for r in rows})
    near = _neighbours(rows)
    free, between = {}, {}
    for r in rows:
        free.setdefault((r["path"], r["original"]), []).append(r)
        between.setdefault((r["path"],) + tuple(near[id(r)]), []).append(r)
    shows = {}
    for r in rows:
        if not r.get("unused"):
            shows.setdefault((r["path"], (r.get("replacement") or r["original"]).rstrip()), r)
    taken = set()

    def first(cands):
        left = [r for r in cands or () if id(r) not in taken]
        return left[0] if left else None
    pairs, missing = [], []
    for e in saved:
        path = find(e["path"])
        if (already is not None and path and (path, e["new"].rstrip()) in shows
                and not [r for r in free.get((path, e["original"])) or ()
                         if not r.get("unused")]):
            already.append(e)
            continue
        got = first(free.get((path, e["original"]))) if path else None
        if got is None and path and e.get("nodes"):
            man = (trees or {}).get(path)
            words = {text_manifest.escape_cell(_text_of(man, n)) for n in e["nodes"]} - {""}
            if len(words) == 1:
                got = first(free.get((path, words.pop())))
        nb = e.get("near")
        if (got is None and path and isinstance(nb, list) and len(nb) == 2
                and any(isinstance(w, str) for w in nb)):
            cands = [r for r in between.get((path,) + tuple(nb)) or () if id(r) not in taken]
            got = cands[0] if len(cands) == 1 else None
        if got is not None:
            taken.add(id(got))
            pairs.append((got, e["new"]))
        else:
            missing.append(e)
    return pairs, missing


def _text_of(man, node):
    o = ((man or {}).get("objects") or {}).get(str(node))
    return (o.get("text") or "") if isinstance(o, dict) and o.get("kind") == "Text" else ""


def import_text(assets_dir, rows, pairs):
    """Put *pairs* (:func:`match_text`) into this project's manifest *rows* and write it."""
    from ...core import text_manifest
    for r, new in pairs:
        r["replacement"] = "" if new == r["original"] else new
    if pairs:
        text_manifest.save(assets_dir, rows)
