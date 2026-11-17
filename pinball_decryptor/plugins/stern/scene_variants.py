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
#: the most sets IMAGE SET offers (pad_mode_runtime.c SCNV_SETS)
MAX_SETS = 16
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
    if not scenes:
        return None
    names = [str(x) for x in (raw.get("names") or ()) if str(x).strip()][:MAX_SETS]
    while len(names) < top:
        names.append(DEFAULT_NAMES[0] if not names else "Set %d" % (len(names) + 1))
    try:
        force = int(raw.get("force") or 0)
    except (TypeError, ValueError):
        force = 0
    return {"names": names, "scenes": scenes, "force": force if 1 <= force <= len(names) else 0}


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
