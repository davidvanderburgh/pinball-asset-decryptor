"""IMAGE SETS: one of the game's scenes, one of several, by the operator's IMAGE SET.

An owner retheming Godzilla drew the Kaiju Battle Select screen dark and asked for "a dark or light or perhaps even
multiple versions" of it, picked in the service menu and kept over a power cycle, with the versions made in the Scenes
tab from the scene as it is. So a scene can have VARIANTS: set 1 is the scene as the project has it (its Scenes tab
edits, its pictures), set 2..n a copy of it with edits and pictures of its own. One setting, IMAGE SET, picks the set
for every scene that has variants (a scene without one shows its own whatever the set).

HOW THE MACHINE SHOWS ONE. A Write puts each variant on the card as a whole scene file beside the mode runtime
(``scn_<scene id>_<set>.radium`` in ``/usr/local/padmode``; ``/dump`` in the rig) and lists it in ``scenes.cfg``. The
runtime (pad_mode_runtime.c "IMAGE SETS") re-points the game program's ``fopen64`` import - the call every
``scene.radium`` is opened with - and opens a listed scene's path as the variant's file while the set says so. The
scene's id, its library and the resource manager never change, so nothing of the game's code that finds a node by
name can tell. Scenes in ``auto_loaded/`` (the Battle Select screen is one) are read at boot, before the game has read
its settings, so a start shows the set the game LAST ran with: the runtime keeps it in ``/dump/pad_imageset.state``
(the picture settings' way, PAD-575) and a change in the menu shows from the next start.

THE PROJECT'S SIDECAR (``.staged_changes.json`` :data:`STAGED_KEY`)::

    {"names": ["Dark", "Light", ...],                      set 1's name first
     "scenes": {"<scene card path>": {"2": {...}, ...}},   a variant per set, see :func:`variant_source`
     "force": 2}                                            optional: a rig run's own set (never written to a card)
"""
from __future__ import annotations

import os
import re
import struct

#: the project sidecar's key
STAGED_KEY = "scene_variants"
#: the runtime's table, beside mode.so on p2 (pad_mode_runtime.c SCNV_FILES)
CFG_NAME = "scenes.cfg"
#: the most sets IMAGE SET offers: a service-menu setting of ours names at most menu_settings.MAX_VALUES values (PAD-1390;
#: the runtime's own table, pad_mode_runtime.c SCNV_SETS, holds 16)
MAX_SETS = 8
#: the import slots the runtime re-points (pad_mode_runtime.c SCNV_SYMS)
SYMBOLS = ("fopen64", "eglSwapBuffers")
#: the first set's name when the project names none
DEFAULT_NAMES = ("Standard",)

_R_ARM_JUMP_SLOT = 22
_SCENE_RE = re.compile(r"/([0-9a-f]{40})/scene\.radium$")


class SceneVariantError(ValueError):
    """The image sets cannot go on this card; the message says why."""


def load(project):
    """The project's image sets, normalised: ``{"names": [...], "scenes": {card: {set: source}}, "force": int}``,
    or ``None`` when it has none (or the sidecar cannot be read)."""
    if not project:
        return None
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return None
    return normalise(raw)


def normalise(raw):
    """*raw* (the sidecar's value) as :func:`load` returns it, ``None`` when it holds no variant."""
    if not isinstance(raw, dict):
        return None
    scenes = {}
    top = 1
    for card, sets in (raw.get("scenes") or {}).items():
        if not isinstance(card, str) or not _SCENE_RE.search(card) or not isinstance(sets, dict):
            continue
        keep = {}
        for k, src in sets.items():
            try:
                n = int(k)
            except (TypeError, ValueError):
                continue
            if 2 <= n <= MAX_SETS and isinstance(src, dict):
                keep[n] = src
                top = max(top, n)
        if keep:
            scenes[card] = keep
    images = {}                                         # Simon: a set's own pictures, chosen on the Images tab
    for k, picks in (raw.get("images") or {}).items():
        try:
            n = int(k)
        except (TypeError, ValueError):
            continue
        keep = ({r: p for r, p in picks.items() if isinstance(r, str) and isinstance(p, str) and p}
                if isinstance(picks, dict) and 2 <= n <= MAX_SETS else {})
        if keep:
            images[n] = keep
            top = max(top, n)
    if not scenes and not images:
        return None
    names = [str(x) for x in (raw.get("names") or ()) if str(x).strip()][:MAX_SETS]
    while len(names) < top:
        names.append(DEFAULT_NAMES[0] if not names else "Set %d" % (len(names) + 1))
    try:
        force = int(raw.get("force") or 0)
    except (TypeError, ValueError):
        force = 0
    out = {"names": names, "scenes": scenes, "force": force if 1 <= force <= len(names) else 0}
    if images:
        out["images"] = images
    return out


# ---- the sets themselves: names, made and removed on the app's set picker -----------------------------------------
# Simon (2026-11-18): "add a drop down ... which would let the user switch between video (etc.) sets. The first option
# would be the main set, then SET 2 and so on". The sets are the project's, named here; set 1 is the project as it is.

def _raw(project):
    from ...core import staged_changes
    try:
        side = staged_changes.load(project)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        side = {}
    raw = side.get(STAGED_KEY)
    return side, (dict(raw) if isinstance(raw, dict) else {})


def _put(project, side, raw):
    from ...core import staged_changes
    names = raw.get("names") or []
    if len(names) <= 1 and names in ([], list(DEFAULT_NAMES)) and not raw.get("scenes") and not raw.get("images") \
            and not raw.get("force"):
        side.pop(STAGED_KEY, None)                      # one set of the default name and nothing in it: none
    else:
        side[STAGED_KEY] = raw
    staged_changes.save(project, side)


def set_names(project):
    """The project's sets by name, set 1 first; ``["Standard"]`` when it has made none."""
    if not project:
        return list(DEFAULT_NAMES)
    _side, raw = _raw(project)
    names = [str(x).strip() for x in (raw.get("names") or ()) if str(x).strip()][:MAX_SETS]
    top = max([int(k) for sets in (raw.get("scenes") or {}).values() if isinstance(sets, dict)
               for k in sets if str(k).isdigit()]
              + [int(k) for k, v in (raw.get("images") or {}).items() if str(k).isdigit() and v] or [1])
    while len(names) < max(1, min(top, MAX_SETS)):
        names.append(DEFAULT_NAMES[0] if not names else "Set %d" % (len(names) + 1))
    return names


def _clean_name(name, names, skip=None):
    name = " ".join(str(name or "").split())[:24]
    if not name:
        raise SceneVariantError("a set needs a name")
    if any(i != skip and n.lower() == name.lower() for i, n in enumerate(names)):
        raise SceneVariantError("there is already a set called %s" % name)
    return name


def add_set(project, name=""):
    """A new set at the end; returns its number. :data:`MAX_SETS` at most."""
    side, raw = _raw(project)
    names = set_names(project)
    if len(names) >= MAX_SETS:
        raise SceneVariantError("%d sets is the most the service menu can offer" % MAX_SETS)
    n = len(names) + 1
    names.append(_clean_name(name or "Set %d" % n, names))
    raw["names"] = names
    _put(project, side, raw)
    return n


def rename_set(project, n, name):
    side, raw = _raw(project)
    names = set_names(project)
    if not 1 <= int(n) <= len(names):
        raise SceneVariantError("there is no set %s" % n)
    names[int(n) - 1] = _clean_name(name, names, skip=int(n) - 1)
    raw["names"] = names
    _put(project, side, raw)


def _renumber(raw, order):
    """Every set-keyed part of *raw* by *order* (``order[new - 1] = old``; an old set missing is dropped)."""
    new_of = {old: new for new, old in enumerate(order, 1)}
    scenes = {}
    for card, sets in (raw.get("scenes") or {}).items():
        if not isinstance(sets, dict):
            continue
        keep = {str(new_of[int(k)]): v for k, v in sets.items()
                if str(k).isdigit() and int(k) in new_of and new_of[int(k)] >= 2}
        if keep:
            scenes[card] = keep
    raw["scenes"] = scenes
    images = {str(new_of[int(k)]): v for k, v in (raw.get("images") or {}).items()
              if str(k).isdigit() and int(k) in new_of and new_of[int(k)] >= 2 and v}
    if images:
        raw["images"] = images
    else:
        raw.pop("images", None)
    force = raw.get("force")
    raw["force"] = new_of.get(force, 0) if isinstance(force, int) else 0
    if not raw["force"]:
        raw.pop("force")


def remove_set(project, n):
    """Set *n* (2 and up: set 1 is the project itself) and everything made for it; the sets after it move up."""
    side, raw = _raw(project)
    names = set_names(project)
    n = int(n)
    if n == 1:
        raise SceneVariantError("set 1 is the project itself and cannot be removed")
    if not 2 <= n <= len(names):
        raise SceneVariantError("there is no set %d" % n)
    order = [k for k in range(1, len(names) + 1) if k != n]
    raw["names"] = [names[k - 1] for k in order]
    _renumber(raw, order)
    _put(project, side, raw)


def move_set(project, n, to):
    """Set *n* to place *to* (both 2 and up: set 1 stays the project itself)."""
    side, raw = _raw(project)
    names = set_names(project)
    n, to = int(n), int(to)
    if not (2 <= n <= len(names) and 2 <= to <= len(names)):
        raise SceneVariantError("set 1 stays first")
    order = [k for k in range(1, len(names) + 1) if k != n]
    order.insert(to - 1, n)
    raw["names"] = [names[k - 1] for k in order]
    _renumber(raw, order)
    _put(project, side, raw)


# ---- a set's own pictures (the Images tab with that set picked) ------------------------------------------------------
# Simon: "When the user selects set 2 - there will be an empty list of chosen images. The user can then choose the
# variants". A set keeps {picture rel: file}; a picture it does not name is set 1's. A scene picture is inside its
# scene file, so the Write makes a variant of every scene that holds one of the set's pictures (picture_variants).

def set_pictures(project, n):
    """``{picture rel: file}`` set *n* gives a picture of its own (empty for set 1 and a set with none)."""
    if not project or int(n) < 2:
        return {}
    _side, raw = _raw(project)
    picks = (raw.get("images") or {}).get(str(int(n))) or {}
    return {r: p for r, p in picks.items() if isinstance(r, str) and isinstance(p, str) and p}


def set_picture(project, n, rel, path):
    """Set *n*'s own picture for *rel* (*path* empty or None: back to set 1's)."""
    n = int(n)
    if n < 2:
        raise SceneVariantError("set 1 is the project itself: its pictures are the Images tab's own")
    names = set_names(project)
    if n > len(names):
        raise SceneVariantError("there is no set %d" % n)
    side, raw = _raw(project)
    raw["names"] = names
    images = dict(raw.get("images") or {})
    picks = dict(images.get(str(n)) or {})
    if path:
        picks[rel] = path
    else:
        picks.pop(rel, None)
    if picks:
        images[str(n)] = picks
    else:
        images.pop(str(n), None)
    if images:
        raw["images"] = images
    else:
        raw.pop("images", None)
    _put(project, side, raw)


#: the Extract's table of every scene picture's place (engine._RADIUM_IMAGE_MANIFEST)
PICTURE_ROWS = ("images", "scene_textures", "radium_images.txt")


def picture_rows(project):
    """``{picture rel: [(scene card path, data offset, length, pad w, pad h, format)]}`` from the Extract's table:
    where each scene picture is, in every scene that holds it. A picture rel is the Images tab's
    (``scene_textures/...``)."""
    out = {}
    try:
        with open(os.path.join(project, *PICTURE_ROWS), "r", encoding="utf-8") as f:
            for line in f:
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) < 6 or cols[0].startswith("#"):
                    continue
                try:
                    row = (cols[1], int(cols[2]), int(cols[3]), int(cols[4]), int(cols[5]),
                           int(cols[6]) if len(cols) > 6 else 5)
                except ValueError:
                    continue
                out.setdefault(cols[0], []).append(row)
                # the Images tab names the same picture from the project folder ("images/scene_textures/..."); Simon
                # found every scene picture refused as "not inside a scene" while only the table's name was here
                out.setdefault("images/" + cols[0], out[cols[0]])
    except OSError:
        pass
    return out


def encode_pictures(data, places, log=None):
    """``(bytes, n)``: *data* (a scene file) with each of *places* ``[(picture file, rel, data offset, length, pad w,
    pad h, format)]`` encoded in, fitted to its place (a picture of another size is scaled to it, as the Images tab
    does with Keep size off); *n* how many went in. A place the scene does not hold as the table says keeps its
    picture, said in the log."""
    log = log or (lambda *a, **k: None)
    from PIL import Image
    import numpy as np
    from . import dds as _dds
    from . import engine as E
    buf = bytearray(data)
    found = {im["data_off"]: im for im in E.parse_radium_images(bytes(data))}
    done = 0
    for src, rel, off, length, pad_w, pad_h, fmt in places:
        im0 = found.get(off)
        if im0 is None or im0["length"] != length or im0["fmt"] != fmt:
            log("Image sets: %s is not where the Extract found it in its scene; that place keeps set 1's picture."
                % rel, "warning")
            continue
        try:
            im = Image.open(src).convert("RGBA")
        except Exception as e:                          # noqa: BLE001
            log("Image sets: %s cannot be read (%s); that place keeps set 1's picture." % (src, e), "warning")
            continue
        w, h = im.size
        if (w, h) != (pad_w, pad_h) and (E._padded4(w), E._padded4(h)) == (pad_w, pad_h):
            grid = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
            grid.paste(im, (0, 0))
            im = grid
        elif (w, h) != (pad_w, pad_h):
            im = im.resize((pad_w, pad_h), Image.LANCZOS)
        arr = np.asarray(im, dtype=np.uint8)
        raw = bytes(buf[off:off + length])
        decode = _dds.decode_bc1 if fmt == E._DXT1_FORMAT else _dds.decode_bc3
        arr, _changed = E._premultiply_like_stock(arr, lambda: decode(raw, pad_w, pad_h))
        enc = _dds.encode_bc1(arr) if fmt == E._DXT1_FORMAT else _dds.encode_bc3(arr)
        if len(enc) != length:
            log("Image sets: %s did not encode to its place's size; that place keeps set 1's picture." % rel,
                "warning")
            continue
        buf[off:off + length] = enc
        done += 1
    return bytes(buf), done


def picture_variants(project, sets, base_scene, work, log=None):
    """*sets* (:func:`load`) with a variant made for every scene that holds a picture a set gives its own: the scene
    as *base_scene* ``(card path) -> bytes or None`` has it (set 1's), the set's pictures encoded in, written under
    *work* as a ``{"file": ...}`` source. A scene the set already has a variant file of keeps that one."""
    log = log or (lambda *a, **k: None)
    picks_by_set = (sets or {}).get("images") or {}
    if not picks_by_set:
        return sets
    rows = picture_rows(project)
    out = dict(sets)
    scenes = {c: dict(v) for c, v in (sets.get("scenes") or {}).items()}
    os.makedirs(work, exist_ok=True)
    for n, picks in sorted(picks_by_set.items()):
        name = sets["names"][n - 1] if n - 1 < len(sets["names"]) else "set %d" % n
        by_card = {}
        for rel, src in sorted(picks.items()):
            if not os.path.isfile(src):
                log("Image sets: set %d (%s)'s picture for %s is missing (%s); left out." % (n, name, rel, src),
                    "warning")
                continue
            places = rows.get(rel)
            if not places:
                log("Image sets: %s is not inside a scene, so set %d (%s) cannot change it; left out."
                    % (rel, n, name), "warning")
                continue
            for card, off, length, pw, ph, fmt in places:
                by_card.setdefault(card, []).append((src, rel, off, length, pw, ph, fmt))
        made = 0
        for card, places in sorted(by_card.items()):
            if n in scenes.get(card, {}):
                log("Image sets: set %d (%s) has a scene file of its own for %s; its pictures are not added to it."
                    % (n, name, card), "info")
                continue
            base = base_scene(card)
            if not base:
                log("Image sets: the card has no %s; set %d (%s)'s pictures in it are left out." % (card, n, name),
                    "warning")
                continue
            data, done = encode_pictures(base, places, log)
            if not done:
                continue
            path = os.path.join(work, "set%d_%s.radium" % (n, scene_id(card)[:12]))
            with open(path, "wb") as f:
                f.write(data)
            scenes.setdefault(card, {})[n] = {"file": path}
            made += 1
        if made:
            log("Image sets: set %d (%s): %d picture(s) of its own, in %d scene(s)." % (n, name, len(picks), made),
                "info")
    out["scenes"] = scenes
    return out


def scene_id(card_path):
    """The 40-hex id of a scene's card path (``.../<id>/scene.radium``)."""
    m = _SCENE_RE.search(card_path)
    if not m:
        raise SceneVariantError("%s is not a scene's file" % card_path)
    return m.group(1)


def file_name(card_path, n):
    """The variant's file beside the runtime: ``scn_<first 12 of the id>_<set>.radium``."""
    return "scn_%s_%d.radium" % (scene_id(card_path)[:12], n)


def tail(card_path):
    """What the runtime matches the game's path against: from the scene's folder on (``<id>/scene.radium``), so a
    title folder of another name (a Premium card's ``godzilla_le``) still matches."""
    return "%s/scene.radium" % scene_id(card_path)


def variant_source(project, src):
    """Where a variant's bytes come from, as ``(kind, value)``: ``("file", path)`` a whole scene file the project
    holds (``{"file": "<path, absolute or under the project>"}``), or ``("card", None)`` the card's own copy of the
    scene, as the card has it, before any of the project's edits (``{"card": true}``)."""
    if src.get("card"):
        return "card", None
    f = src.get("file")
    if isinstance(f, str) and f:
        return "file", f if os.path.isabs(f) else os.path.join(project, *f.replace("\\", "/").split("/"))
    raise SceneVariantError("a variant names no source")


def import_slots(elf):
    """``{symbol: address}`` of the game program's import slots of :data:`SYMBOLS` (the picture settings' reader,
    for these two)."""
    from . import picture_settings as PS
    saved = PS.SYMBOLS
    try:
        PS.SYMBOLS = SYMBOLS
        return PS.import_slots(elf)
    except PS.PictureError as e:
        raise SceneVariantError(str(e)) from None
    finally:
        PS.SYMBOLS = saved


def cfg_text(slots, live, sets, lines, only=False, force=0):
    """``scenes.cfg``: *slots* from :func:`import_slots`, *live* IMAGE SET's value in the game's memory (0: none,
    the last start's set stays), *sets* how many, *lines* ``[(card path, set, file name)]``, *only* when the card
    carries no modes, *force* a rig run's own set."""
    out = ["# image sets: which scene file a screen reads, by the operator's IMAGE SET"]
    if only:
        out.append("only")
    for sym in SYMBOLS:
        out.append("got\t%s\t0x%08x" % (sym, slots[sym]))
    out.append("setting\t0x%08x\t%d" % (live or 0, sets))
    for card, n, name in lines:
        out.append("scene\t%s\t%d\t%s" % (tail(card), n, name))
    if force:
        out.append("force\t%d" % force)
    return "\n".join(out) + "\n"


def stage(project, sets, game_elf, read_card, work, live=0, only=False, log=None):
    """Write each variant's file and ``scenes.cfg`` under *work*; returns ``(cfg path, [variant paths])``, or
    ``("", [])`` when none could go (each reason logged). *read_card* ``(card path) -> bytes or None`` reads a scene
    off the card being written."""
    log = log or (lambda *a, **k: None)
    try:
        slots = import_slots(game_elf)
    except SceneVariantError as e:
        log("Image sets: left out - %s." % e, "warning")
        return "", []
    os.makedirs(work, exist_ok=True)
    lines, files = [], []
    for card, by_set in sorted(sets["scenes"].items()):
        for n, src in sorted(by_set.items()):
            try:
                kind, value = variant_source(project, src)
                if kind == "card":
                    data = read_card(card)
                    if not data:
                        raise SceneVariantError("the card has no %s" % card)
                else:
                    with open(value, "rb") as f:
                        data = f.read()
                if len(data) < 16:
                    raise SceneVariantError("its file is empty")
            except (SceneVariantError, OSError) as e:
                log("Image sets: %s's set %d (%s) is left out - %s." % (card, n, sets["names"][n - 1], e), "warning")
                continue
            name = file_name(card, n)
            path = os.path.join(work, name)
            with open(path, "wb") as f:
                f.write(data)
            lines.append((card, n, name))
            files.append(path)
    if not lines:
        return "", []
    cfg = os.path.join(work, CFG_NAME)
    with open(cfg, "w", encoding="ascii", newline="\n") as f:
        f.write(cfg_text(slots, live, len(sets["names"]), lines, only=only, force=sets.get("force") or 0))
    log("Image sets: %d variant(s) of %d scene(s) (%s)%s." % (
        len(lines), len({c for c, _n, _f in lines}), ", ".join(sets["names"]),
        (" - set %d FORCED for this run" % sets["force"]) if sets.get("force") else ""), "info")
    return cfg, files
