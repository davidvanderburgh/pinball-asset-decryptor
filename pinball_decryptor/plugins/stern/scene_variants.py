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
        side = staged_changes.load(project)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return None
    return normalise(side.get(STAGED_KEY), theme_colour_rels(side))


def normalise(raw, colour=None):
    """*raw* (the sidecar's value) as :func:`load` returns it, ``None`` when it holds no variant. *colour*:
    :func:`theme_colour_rels` - a theme whose only change is a colour profile is a variant too."""
    if not isinstance(raw, dict):
        return None
    colour = {n: set(r) for n, r in (colour or {}).items() if 2 <= n <= MAX_SETS and r}
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
    if colour:
        top = max(top, max(colour))
    if not scenes and not images and not colour:
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
    if colour:
        out["colour"] = colour
    return out


# ---- a theme's own colour profiles (Simon: "every single image can be colour profiled", per theme) -----------------
# A picture's colour switch and its own profile live where theme 1's do (core/colour_profile: image_color_slots,
# image_color_profiles), under a THEME KEY "@<n>:<picture rel>" - so the Colours bar, its undo and Apply to all work on
# a theme's picture unchanged, and nothing of theme 1's is ever touched. A theme key is never a file, so theme 1's build
# never sees one. A theme with nothing of its own for a picture is theme 1's: its switch, then its profile.

_THEME_KEY_RE = re.compile(r"^@(\d+):(.+)$")


def theme_key(n, rel):
    """Theme *n*'s key for picture *rel* (theme 1's is the picture's own rel)."""
    return rel if int(n) <= 1 else "@%d:%s" % (int(n), rel)


def split_theme_key(key):
    """``(n, rel)`` of a theme key, ``(1, key)`` of a plain picture rel."""
    m = _THEME_KEY_RE.match(str(key or ""))
    return (int(m.group(1)), m.group(2)) if m else (1, key)


def theme_colour_rels(side):
    """``{n: {picture rel}}``: the pictures each theme has a colour switch or profile of its own for, read from the
    sidecar dict *side* (``staged_changes.load``)."""
    from ...core import colour_profile as cp
    out = {}
    for key in (cp.IMAGE_SLOTS_KEY, cp.FILE_PROFILES_KEY["images"]):
        m = side.get(key) if isinstance(side, dict) else None
        for k in (m or {}) if isinstance(m, dict) else ():
            n, rel = split_theme_key(k)
            if n >= 2:
                out.setdefault(n, set()).add(rel)
    return out


def _theme1_switch(project, side, settings, rel):
    """Theme 1's colour switch for picture *rel*, as the Images tab has it: its own, else - a replaced picture, or
    one an earlier build put in - the tab-wide box; a game picture has no box (off)."""
    own = settings["images"].get(rel)
    if own is not None:
        return bool(own)
    from ...core import colour_profile as cp
    if not settings.get("all_images"):
        return False
    if isinstance(side, dict) and (side.get("image") or {}).get(rel):
        return True
    try:
        return rel in cp.built_image_rels(project, side)
    except Exception:                                   # noqa: BLE001
        return False


def theme_colour(project, n, rel, side=None, settings=None):
    """``(on, profile or None)``: theme *n*'s colour switch for picture *rel* and the profile baked in with it on -
    the theme's own, else theme 1's (its own, else the project's individual files profile)."""
    from ...core import colour_profile as cp, staged_changes
    side = staged_changes.peek(project) if side is None else side
    settings = cp.asset_settings(project) if settings is None else settings
    key = theme_key(n, rel)
    own_on = settings["images"].get(key)
    on = bool(own_on) if own_on is not None else _theme1_switch(project, side, settings, rel)
    prof = cp.own_profile(project, "images", key) if int(n) >= 2 else None
    if prof is None:
        prof = cp.file_profile(project, "images", rel)
    return on, prof


def theme_pictures(project, n, bake=True):
    """Theme *n*'s pictures as the Scenes preview draws them (:func:`.scene_render.pending_pictures`' shape, keyed by
    the picture's name under images/): each picture the theme changes - its own file, else theme 1's before theme 1's
    colours - with the theme's colour profile where its switch is on (Simon: "a drop down in scenes to show the scene
    as it will appear in theme N"). Only the pictures the theme changes; the rest are theme 1's."""
    from ...core import colour_profile as cp, staged_changes
    if not project or int(n) < 2:
        return {}
    side = staged_changes.peek(project) or {}
    settings = cp.asset_settings(project)
    rels = set(set_pictures(project, n)) | set(theme_colour_rels(side).get(int(n)) or ())
    picks = set_pictures(project, n)
    out = {}
    for rel in rels:
        if not rel.startswith("images/"):
            continue
        path = picks.get(rel) or theme1_source(project, rel)
        on, prof = theme_colour(project, n, rel, side, settings)
        colour = prof if (bake and on and prof is not None and not prof.is_identity()) else None
        out[rel[len("images/"):]] = {"path": path if os.path.isfile(path) else None, "keep": False,
                                     "colour": colour, "skip": not on}
    return out


def theme1_source(project, rel):
    """Theme 1's picture *rel* as a file, before any colour profile of theme 1's was baked into it: the replacement
    the Images tab chose, else the uncorrected copy a build kept, else the game's own (its snapshot, where a build
    corrected the project's copy), else the project's file."""
    from ...core import colour_profile as cp, staged_changes, staged_originals as SO
    rep = (staged_changes.peek(project).get("image") or {}).get(rel)
    if isinstance(rep, str) and os.path.isfile(rep):
        return rep
    kept = cp.uncorrected_path(project, rel)
    if kept:
        return kept
    try:
        if SO.has_snapshot(project, rel):
            return SO.snapshot_path(project, rel)
    except Exception:                                   # noqa: BLE001
        pass
    return os.path.join(project, *rel.split("/"))


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
            and not raw.get("force") and not raw.get("on"):
        side.pop(STAGED_KEY, None)                      # one set of the default name and nothing in it: none
    else:
        side[STAGED_KEY] = raw
    staged_changes.save(project, side)


# Simon (2026-11-18): "hide ... image alternates behind an advanced curtain because to a new user it will be very hard to
# understand all the possibilities" - the project's themes are switched on (Images tab, Advanced) before any of it shows

def themes_on(project):
    """True when the project shows its themes: switched on, or it has more than one already."""
    if not project:
        return False
    _side, raw = _raw(project)
    return bool(raw.get("on")) or len(set_names(project)) > 1


def set_themes_on(project, on):
    """Switch the project's themes on or off; off only while it has theme 1 alone (nothing would be hidden)."""
    if not on and len(set_names(project)) > 1:
        raise SceneVariantError("remove the other themes first (Manage themes), then switch themes off")
    side, raw = _raw(project)
    if on:
        raw["on"] = True
    else:
        raw.pop("on", None)
    _put(project, side, raw)


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
        raise SceneVariantError("a theme needs a name")
    if any(i != skip and n.lower() == name.lower() for i, n in enumerate(names)):
        raise SceneVariantError("there is already a theme called %s" % name)
    return name


def add_set(project, name=""):
    """A new set at the end; returns its number. :data:`MAX_SETS` at most."""
    side, raw = _raw(project)
    names = set_names(project)
    if len(names) >= MAX_SETS:
        raise SceneVariantError("%d themes is the most the service menu can offer" % MAX_SETS)
    n = len(names) + 1
    names.append(_clean_name(name or "Set %d" % n, names))
    raw["names"] = names
    _put(project, side, raw)
    return n


def rename_set(project, n, name):
    side, raw = _raw(project)
    names = set_names(project)
    if not 1 <= int(n) <= len(names):
        raise SceneVariantError("there is no theme %s" % n)
    names[int(n) - 1] = _clean_name(name, names, skip=int(n) - 1)
    raw["names"] = names
    _put(project, side, raw)


def _renumber_colour(side, order):
    """The themes' colour switches and profiles (theme keys in the sidecar *side*) by *order* (``order[new - 1] =
    old``; a theme missing is dropped)."""
    from ...core import colour_profile as cp
    new_of = {old: new for new, old in enumerate(order, 1)}
    for key in (cp.IMAGE_SLOTS_KEY, cp.FILE_PROFILES_KEY["images"]):
        m = side.get(key)
        if not isinstance(m, dict):
            continue
        out = {}
        for k, v in m.items():
            n, rel = split_theme_key(k)
            if n < 2:
                out[k] = v
            elif new_of.get(n, 0) >= 2:
                out[theme_key(new_of[n], rel)] = v
        if out:
            side[key] = out
        else:
            side.pop(key, None)


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
        raise SceneVariantError("theme 1 is the project itself and cannot be removed")
    if not 2 <= n <= len(names):
        raise SceneVariantError("there is no theme %d" % n)
    order = [k for k in range(1, len(names) + 1) if k != n]
    raw["names"] = [names[k - 1] for k in order]
    _renumber(raw, order)
    _renumber_colour(side, order)
    _put(project, side, raw)


def move_set(project, n, to):
    """Set *n* to place *to* (both 2 and up: set 1 stays the project itself)."""
    side, raw = _raw(project)
    names = set_names(project)
    n, to = int(n), int(to)
    if not (2 <= n <= len(names) and 2 <= to <= len(names)):
        raise SceneVariantError("theme 1 stays first")
    order = [k for k in range(1, len(names) + 1) if k != n]
    order.insert(to - 1, n)
    raw["names"] = [names[k - 1] for k in order]
    _renumber(raw, order)
    _renumber_colour(side, order)
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
        raise SceneVariantError("theme 1 is the project itself: its pictures are the Images tab's own")
    names = set_names(project)
    if n > len(names):
        raise SceneVariantError("there is no theme %d" % n)
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
            log("Themes: %s is not where the Extract found it in its scene; that place keeps theme 1's picture."
                % rel, "warning")
            continue
        try:
            im = Image.open(src).convert("RGBA")
        except Exception as e:                          # noqa: BLE001
            log("Themes: %s cannot be read (%s); that place keeps theme 1's picture." % (src, e), "warning")
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
            log("Themes: %s did not encode to its place's size; that place keeps theme 1's picture." % rel,
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
    colour_by_set = (sets or {}).get("colour") or {}
    if not picks_by_set and not colour_by_set:
        return sets
    rows = picture_rows(project)
    out = dict(sets)
    scenes = {c: dict(v) for c, v in (sets.get("scenes") or {}).items()}
    os.makedirs(work, exist_ok=True)
    from ...core import colour_profile as cp, staged_changes
    side = staged_changes.peek(project)
    settings = cp.asset_settings(project)
    for n in sorted(set(picks_by_set) | set(colour_by_set)):
        picks = dict(picks_by_set.get(n) or {})
        name = sets["names"][n - 1] if n - 1 < len(sets["names"]) else "theme %d" % n
        by_card = {}
        # every picture the theme changes: its own file, or theme 1's before theme 1's colours (theme1_source), with
        # the theme's colour profile baked in where its switch is on (Simon: "every single image can be colour
        # profiled", per theme)
        for rel in sorted(set(picks) | set(colour_by_set.get(n) or ())):
            src = picks.get(rel) or theme1_source(project, rel)
            if rows.get(rel) and os.path.isfile(src):
                try:
                    on, prof = theme_colour(project, n, rel, side, settings)
                    if on and prof is not None and not prof.is_identity():
                        from PIL import Image
                        coloured = os.path.join(work, "colour%d_%s.png" % (n, re.sub(r"[^\w.-]", "_", rel)))
                        prof.apply_image(Image.open(src)).save(coloured)
                        src = coloured
                except Exception as e:                  # noqa: BLE001
                    log("Themes: theme %d (%s)'s colour profile could not be baked into %s (%s); it goes in "
                        "without it." % (n, name, rel, e), "warning")
            picks[rel] = src
        for rel, src in sorted(picks.items()):
            if not os.path.isfile(src):
                log("Themes: theme %d (%s)'s picture for %s is missing (%s); left out." % (n, name, rel, src),
                    "warning")
                continue
            places = rows.get(rel)
            if not places:
                log("Themes: %s is not inside a scene, so theme %d (%s) cannot change it; left out."
                    % (rel, n, name), "warning")
                continue
            for card, off, length, pw, ph, fmt in places:
                by_card.setdefault(card, []).append((src, rel, off, length, pw, ph, fmt))
        made = 0
        for card, places in sorted(by_card.items()):
            if n in scenes.get(card, {}):
                log("Themes: theme %d (%s) has a scene file of its own for %s; its pictures are not added to it."
                    % (n, name, card), "info")
                continue
            base = base_scene(card)
            if not base:
                log("Themes: the card has no %s; theme %d (%s)'s pictures in it are left out." % (card, n, name),
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
            log("Themes: theme %d (%s): %d picture(s) of its own (chosen or colour profiled), in %d scene(s)."
                % (n, name, len(picks), made), "info")
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
