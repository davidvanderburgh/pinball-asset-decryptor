"""Scenes saved with everything they show (PAD-369, DragonRR).

A file of scene edits (:func:`scene_edit.export_edits`, PAD-281) carries the moves, resizes,
tints, hidden layers and added pictures and text.  Saved "with pictures and color profiles" it
also carries, for the pictures those scenes draw:

* each picture replaced on the Images tab: the replacement file itself, its Keep size tick, its
  color switch and the color profile baked into it (its own, else the project's individual
  files profile, so it looks the same in a project with another one);
* the color switch and profile of each picture added in Scenes;
* each of the game's own pictures switched on behind the unlock box (PAD-502, DragonRR: a
  project colored without replacing a picture saved none of it): its own profile, or none when
  it follows the individual files profile, which the file then carries too;
* the project's whole screen overlay;
* the Text tab's edits of those scenes' words (PAD-387).

Every scene saved this way also carries every other picture replaced on the Images tab (the
boot screen, the game's splash, any picture no scene draws) and every Text tab edit, the game
program's words too: the project's whole look in one file, sounds, videos and modes aside.

The machine screen is not carried: it describes the screen of the PC or machine it was set on.

Loading never deletes or overwrites a file: the pictures are copied into
``<project>/Shared pictures/<file name>/`` (a name already there with other bytes gets a new
one), and each replaced picture's pick points at its copy.  What it changes in the project
(a pick made here, the overlay, a game picture's other profile here, another individual files
profile) is listed by :func:`clashes` so the page can ask first.  A file bringing the game's own
pictures or lines switched on ticks the unlock box, without which they would not count.

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
from ...core.checksums import SHARED_PICTURES_DIR

#: where the pictures of a loaded file are copied, inside the project folder (never
#: scanned as slots: core.checksums.NON_ASSET_DIRS)
SHARED_DIR = SHARED_PICTURES_DIR


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


def _profile_raw(data, rel, kind="images"):
    """What a switched-on picture *rel* (a sidecar key; *kind* "text": a line of text's
    :func:`colour_profile.text_rel`, PAD-438) has baked in, as stored: its own profile, else
    the project's individual files profile, else the Recommended one (which follows the
    screen of the project it is loaded into, as it does here)."""
    from ...core import colour_profile as cp
    own = cp._own_dicts(data, kind).get(rel)
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
    colored, files_profile = _game_pictures_on(data, settings, built, drawn,
                                               None if cards is None else rels)
    added = {}
    for ops in edits.values():
        for op in ops:
            img = op.get("image") if op.get("op") == "add_picture" else None
            if not img or img in added:
                continue
            on = cp.asset_applies(settings, "images", img, own=op.get("color"))
            added[img] = {"color": on, "profile": _profile_raw(data, img) if on else None}
    # PAD-438: the lines of text with the colour profile on, per scene, by node: the game's
    # own (switched on behind the unlock) and the added ones (their switch rides in their
    # edit; the profile is what the file carries)
    lines = {}
    on_lines = cp.text_lines_on(assets_dir, data)
    for c in want:
        per = {}
        for rel in on_lines:
            card, _h, node = rel.rpartition("#")
            if card == c and node.isdigit():
                per[node] = {"color": True, "profile": _profile_raw(data, rel, "text")}
        for op in edits.get(c) or ():
            if op.get("op") == "add_text" and isinstance(op.get("id"), int):
                on = bool(op.get("color"))
                per[str(op["id"])] = {
                    "color": on,
                    "profile": _profile_raw(data, cp.text_rel(c, op["id"]), "text") if on
                    else None}
        if per:
            lines[c] = per
    overlay = data.get(cp.KEY)
    extras = {"pictures": pictures, "added": added, "lines": lines,
              "colored": colored, "files_profile": files_profile,
              "overlay": dict(overlay) if isinstance(overlay, dict) else None,
              "text": text_to_save(assets_dir, cards, trees)}
    return edits, extras


def _game_pictures_on(data, settings, built, drawn, scope=None):
    """``({rel: {"profile", "drawn"?}}, files profile or None)``: the game's own pictures (no
    pick, not built) switched on while the unlock box is ticked, the only time their switch
    counts, among *scope* (None: every one).  *profile* is the picture's own, or None when it
    follows the project's individual files profile, which is then returned as stored (the
    Recommended one when none is)."""
    from ...core import colour_profile as cp
    if not data.get(cp.STOCK_IMAGES_KEY):
        return {}, None
    picks = data.get("image") or {}
    owns = cp._own_dicts(data, "images")
    out = {}
    for rel, on in sorted(settings["images"].items()):
        if (not on or picks.get(rel) or rel in built or not rel.startswith("images/")
                or not scene_edit._safe_rel(rel) or (scope is not None and rel not in scope)):
            continue
        own = owns.get(rel)
        out[rel] = {"profile": dict(own) if isinstance(own, dict) else None}
        if drawn.get(rel[len("images/"):]):
            out[rel]["drawn"] = drawn[rel[len("images/"):]]
    if not any(p["profile"] is None for p in out.values()):
        return out, None
    shared = data.get(cp.ASSET_KEY)
    return out, dict(shared) if isinstance(shared, dict) else {"recommended": True}


def export_all(assets_dir, zip_path, cards, trees, counts=None):
    """Save *cards* (None: every scene, and the whole project's look) with their pictures,
    color profiles and text to *zip_path*.  Returns ``(scenes with edits, pictures, text
    edits)`` written (*counts*, a dict, is filled with the ``"colored"`` game pictures and the
    ``"lines"`` of text whose color profiles it holds); raises
    :class:`scene_edit.SceneEditError` when there is nothing to save."""
    edits, extras = gather(assets_dir, cards, trees)
    if counts is not None:
        counts.update(colored=len(extras["colored"]),
                      lines=sum(len(per) for per in extras["lines"].values()))
    if not (edits or extras["pictures"] or extras["text"] or extras["colored"]
            or extras["lines"]):
        raise scene_edit.SceneEditError(
            "there are no scene edits, replaced pictures, color profiles or text edits to save")
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
        if extras.get("lines"):
            doc["lines"] = extras["lines"]       # PAD-438
        if extras["colored"]:
            doc["colored"] = extras["colored"]       # PAD-502
            if extras["files_profile"] is not None:
                doc["files_profile"] = extras["files_profile"]
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
    # PAD-438: the lines of text with the colour profile on, ``{card: {node: {"color",
    # "profile"}}}``
    lines = {}
    for card, per in (doc.get("lines") or {}).items() if isinstance(
            doc.get("lines"), dict) else ():
        if not (isinstance(card, str) and isinstance(per, dict)):
            continue
        good = {str(n): {"color": bool(a.get("color")),
                         "profile": dict(a["profile"]) if isinstance(a.get("profile"), dict)
                         else None}
                for n, a in per.items() if isinstance(a, dict) and str(n).isdigit()}
        if good:
            lines[card] = good
    # PAD-502: the game's own pictures switched on, ``{rel: {"profile", "drawn"?}}``, and the
    # individual files profile the ones with no profile of their own follow
    colored = {}
    for rel, p in (doc.get("colored") or {}).items() if isinstance(
            doc.get("colored"), dict) else ():
        if (isinstance(rel, str) and rel.startswith("images/") and scene_edit._safe_rel(rel)
                and isinstance(p, dict)):
            colored[rel] = {"profile": dict(p["profile"]) if isinstance(p.get("profile"), dict)
                            else None}
            if isinstance(p.get("drawn"), list):
                colored[rel]["drawn"] = p["drawn"]
    files_profile = (dict(doc["files_profile"]) if isinstance(doc.get("files_profile"), dict)
                     else None)
    return {"pictures": pictures, "added": added, "overlay": overlay, "text": text,
            "lines": lines, "colored": colored, "files_profile": files_profile}


def has_extras(extras):
    return bool(extras["pictures"] or extras["added"] or extras["overlay"]
                or extras.get("lines") or extras.get("colored"))


def _followers(extras):
    """The file's game pictures that follow its individual files profile (PAD-502)."""
    return [r for r, p in (extras.get("colored") or {}).items() if p.get("profile") is None]


def _files_profile(extras):
    """The individual files profile the file's game pictures with none of their own follow."""
    return dict(extras.get("files_profile") or {"recommended": True})


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
    found in the other game folder here (le/pro folders matched, PAD-401).  The game's own
    pictures with a color profile (``colored``, PAD-502) are named the same way."""
    if not (extras.get("pictures") or extras.get("colored")):
        return extras
    find = scene_edit.card_finder((trees or {}).keys())
    return dict(extras, pictures=_localised(assets_dir, extras.get("pictures") or {}, find, trees),
                colored=_localised(assets_dir, extras.get("colored") or {}, find, trees))


def _localised(assets_dir, pics, find, trees):
    """:func:`localise` of one ``{rel: {"drawn"?, ...}}`` of the file."""
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
    return out


def clashes(assets_dir, extras):
    """What loading *extras* would change of the user's own here: ``{"pictures": [rel, ...]
    with another replacement here], "overlay": True when the overlay here differs,
    "colored": [game picture switched on here with another profile], "files_profile": True
    when the file's game pictures follow another individual files profile than this project's,
    one the user set or that something here is attached to}`` (PAD-502)."""
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
    # a game picture switched on here with another look; one following the individual files
    # profile both here and in the file goes with that profile's own question
    colored = []
    owns = cp._own_dicts(data, "images")
    for rel, p in sorted((extras.get("colored") or {}).items()):
        if (_game_on_here(data, picks, built, rel) and _here(assets_dir, rel)
                and (p.get("profile") is not None or isinstance(owns.get(rel), dict))
                and _profile_raw(data, rel) != (p.get("profile") or _files_profile(extras))):
            colored.append(rel)
    shared = data.get(cp.ASSET_KEY)
    files = bool(_followers(extras) and (shared if isinstance(shared, dict) else {
        "recommended": True}) != _files_profile(extras) and (
            isinstance(shared, dict) or _any_attached(data, built)))
    return {"pictures": pics, "overlay": overlay, "colored": colored, "files_profile": files}


def _game_on_here(data, picks, built, rel):
    """Is *rel* a game picture of the project's sidecar *data* switched on (unlock box ticked,
    no pick, not built)?"""
    from ...core import colour_profile as cp
    slots = data.get(cp.IMAGE_SLOTS_KEY)
    return bool(data.get(cp.STOCK_IMAGES_KEY) and isinstance(slots, dict) and slots.get(rel)
                and not picks.get(rel) and rel not in built)


def _any_attached(data, built):
    """Is anything of the project's sidecar *data* attached to a color profile: a box ticked,
    or a switch on that counts (a game picture's, clip's or line's only with its unlock box)?"""
    from ...core import colour_profile as cp
    if data.get(cp.ALL_IMAGES_KEY) or data.get(cp.ALL_VIDEOS_KEY):
        return True

    def on(key):
        m = data.get(key)
        return [r for r, v in m.items() if v] if isinstance(m, dict) else []
    picks, clips = data.get("image") or {}, data.get("video") or {}
    if any(picks.get(r) or r in built or not str(r).startswith("images/")
           or data.get(cp.STOCK_IMAGES_KEY) for r in on(cp.IMAGE_SLOTS_KEY)):
        return True
    if any(clips.get(r) or data.get(cp.STOCK_VIDEOS_KEY) for r in on(cp.VIDEO_SLOTS_KEY)):
        return True
    return bool(data.get(cp.STOCK_IMAGES_KEY) and on(cp.TEXT_SLOTS_KEY))


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
    # PAD-502: the game's own pictures' color profiles, one row for them all
    if clash.get("files_profile"):
        items.append({"id": "files_profile", "what": "Individual files color profile",
                      "mine": _profile_name(data.get(cp.ASSET_KEY)),
                      "theirs": _profile_name(_files_profile(extras))})
    if clash.get("colored"):
        n = len(clash["colored"])
        theirs = extras["colored"]
        items.append({"id": "colored", "what": "Color profile of %d game picture%s" % (
            n, "" if n == 1 else "s"),
            "mine": _names([_profile_raw(data, r) for r in clash["colored"]]),
            "theirs": _names([theirs[r].get("profile") or _files_profile(extras)
                              for r in clash["colored"]])})
    for i, (r, new) in enumerate(tclash):
        items.append({"id": "text:%d" % i, "what": 'Text "%s"' % r["original"],
                      "mine": '"%s"' % r["replacement"], "theirs": '"%s"' % new})
    return items


def _profile_name(stored):
    """A stored profile's name (none stored, or the Recommended one: "Recommended")."""
    from ...core import colour_profile as cp
    if not isinstance(stored, dict) or stored.get("recommended"):
        return cp.RECOMMENDED
    return stored.get("name") or "your own"


def _names(stored):
    """The names of the stored profiles *stored*, each once: ``A, B and 2 more``."""
    names = sorted({_profile_name(s) for s in stored})
    more = len(names) - 3
    return ", ".join(names[:3]) + (" and %d more" % more if more > 0 else "")


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


def import_extras(assets_dir, zip_path, extras, renamed=None, overlay=True, cards_here=None,
                  files_profile=True, counts=None):
    """Put *extras* (:func:`read_extras` of *zip_path*) into the project: each replaced
    picture copied into :data:`SHARED_DIR` and picked, with its Keep size tick, color switch
    and profile; each added picture's switch and profile (*renamed*: ``{its rel in the file:
    its rel here}`` from :func:`scene_edit.import_edits`); the overlay when *overlay*; each
    line of text's switch and profile (PAD-438), on the scenes here (*cards_here*, matched as
    :func:`scene_edit.match_cards` matches them; None: by path alone); each game picture's
    switch and profile (PAD-502), those following the file's individual files profile
    following it here when *files_profile* (it becomes this project's), else each given a copy
    of it (a picture following this project's own here keeps it).  Game pictures or lines
    switched on tick the unlock box, a game switch left from before it was ticked dropped.
    A picture this project does not have, or has replaced, is left out.  Nothing is deleted or
    overwritten.  Returns ``(pictures loaded, [picture of the file not here])``; *counts*, a
    dict, is filled with the ``"colored"`` game pictures and ``"lines"`` loaded and the
    game pictures not here (``"colored_missing"``)."""
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
    # PAD-502: the game's own pictures switched on, each with the file's look
    unlocked = bool(data.get(cp.STOCK_IMAGES_KEY))
    built = cp.built_image_rels(assets_dir, data)
    theirs = _files_profile(extras)
    colored, colored_missing = set(), []
    for rel, p in sorted((extras.get("colored") or {}).items()):
        if picks.get(rel) or rel in built:
            continue                        # replaced here: the file's color was for the game's
        if not _here(assets_dir, rel):
            colored_missing.append(rel)
            continue
        own = p.get("profile")
        if (own is None and not files_profile and unlocked and slots_on.get(rel)
                and not isinstance(owns.get(rel), dict)):
            continue                        # it follows this project's own, which is kept
        slots_on[rel] = True
        if own is not None:
            owns[rel] = dict(own)
        elif files_profile:
            owns.pop(rel, None)
        else:
            owns[rel] = dict(theirs)
        colored.add(rel)
    if files_profile and any(extras["colored"][r].get("profile") is None for r in colored):
        if theirs.get("recommended"):
            data.pop(cp.ASSET_KEY, None)
        else:
            data[cp.ASSET_KEY] = dict(theirs)
    # PAD-438: the lines of text: a game line's switch (it counts once the unlock box is
    # ticked here, as a game picture's does) and each line's own profile; an added line's
    # switch rides in its edit, so only its profile is put here
    tslots = dict(data.get(cp.TEXT_SLOTS_KEY) or {}) if isinstance(
        data.get(cp.TEXT_SLOTS_KEY), dict) else {}
    towns = dict(cp._own_dicts(data, "text"))
    find = (scene_edit.card_finder(cards_here) if cards_here is not None
            else (lambda card: card))
    lines_on, lines_n = set(), 0
    for card, per in (extras.get("lines") or {}).items():
        here = find(card)
        if here is None:
            continue
        for node, a in per.items():
            rel = cp.text_rel(here, int(node))
            stock = int(node) < scene_edit.FIRST_ADDED_ID
            if a.get("color"):
                lines_n += 1
                if stock:
                    tslots[rel] = True
                    lines_on.add(rel)
                if isinstance(a.get("profile"), dict):
                    towns[rel] = dict(a["profile"])
                else:
                    towns.pop(rel, None)
            else:
                tslots.pop(rel, None)
                towns.pop(rel, None)
    if (colored or lines_on) and not unlocked:
        # PAD-502: without the unlock box ticked the game's own pictures and lines the file
        # switched on would not count, and nothing of it would show.  Ticked here, it wakes no
        # switch left from before (as ticking it on the Images tab does not)
        for r in list(slots_on):
            if r.startswith("images/") and not picks.get(r) and r not in built \
                    and r not in colored:
                del slots_on[r]
        tslots = {r: v for r, v in tslots.items() if r in lines_on}
        data[cp.STOCK_IMAGES_KEY] = True
    if counts is not None:
        counts.update(colored=len(colored), lines=lines_n, colored_missing=len(colored_missing))
    data["image"] = picks
    data["image_keep_size"] = sorted(r for r in keep if r in picks)
    for key, val in ((cp.IMAGE_SLOTS_KEY, slots_on), (cp.FILE_PROFILES_KEY["images"], owns),
                     (cp.TEXT_SLOTS_KEY, tslots), (cp.FILE_PROFILES_KEY["text"], towns)):
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
