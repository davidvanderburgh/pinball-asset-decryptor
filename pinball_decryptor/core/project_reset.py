"""The project menu's Reset... (PAD-569, DragonRR; PAD-576 moved it off the top bar): parts of a project back the way they were
extracted, picked by kind, for starting a heavily modded project over.

Each kind is one :data:`KINDS` row: its records (the sidecar's keys, the files a tab keeps
its edits in) and the extracted files it changed (by where they sit, :func:`kind_of_rel`).
:func:`drop_records` forgets the records of the kinds picked and :func:`restore_snapshots`
puts their files back from the ``.orig`` snapshots; the files changed before snapshots
existed are re-derived from the card by the caller (``App._start_reset``), as Revert all
changes always did.  Every kind picked is Revert all changes plus the Scenes edits and the
project's own modes, which it never reached (new files, so never in the extract's baseline).

The Color profile tab's machine screen is never reset: it describes the user's machine, not a
change to the card (as Revert all).
"""

import os
import shutil

from . import staged_changes, staged_originals

#: ``(key, label, what it covers)``, in the order the dialog lists them
KINDS = (
    ("scenes", "Scenes edits",
     "Every scene as the game shipped it: moves, resizes, tints, layers, added pictures and "
     "text, the Font bar's changes, and the score panel's colors."),
    ("colours", "Color profiles",
     "The project's color profile and every picture's, video's and line's own one, with "
     "every color switch turned off."),
    ("images", "Replaced images",
     "Every picture picked on the Images tab, and every picture file changed, back to the "
     "extracted one."),
    ("videos", "Replaced videos",
     "Every clip picked on the Video tab, random clips, and every video file changed."),
    ("sounds", "Replaced sounds",
     "Every sound picked on the Audio tab, its loop, level and play-in-turn settings, and "
     "every sound file changed."),
    ("text", "Text edits",
     "Every line of text changed on the Text tab, and every text color picked there."),
    ("fonts", "Fonts",
     "Every font's letters back from the game's own font pictures (imports, glyph edits, "
     "removed outlines)."),
    ("modes", "Modes",
     "Every mode made in this project, with its picture, clip and sound (the modes folder), "
     "and every change to the game's own modes."),
)
KEYS = tuple(k for k, _l, _d in KINDS)
LABELS = {k: label for k, label, _d in KINDS}

#: the sidecar keys each kind owns (besides what :func:`drop_records` does by hand)
_SIDECAR = {
    "scenes": ("score_colors",),
    "images": ("image", "image_keep_size"),
    "videos": ("video", "video_asis_slots", "video_length_slots", "video_variants",
               "own_clips"),
    "sounds": ("audio", "audio_loop", "audio_keep", "audio_levels", "grow_keep_whole",
               "sound_modes"),
}


#: extracted files that hold a kind's records: the app rewrites them, so they differ from the
#: extract with no change in them; their changes are counted from what they record
_RECORD_FILES = frozenset({"text/strings.tsv"})


def _colour_keys():
    from . import colour_profile as cp
    return (cp.KEY, cp.ASSET_KEY, cp.ALL_IMAGES_KEY, cp.ALL_VIDEOS_KEY, cp.IMAGE_SLOTS_KEY,
            cp.VIDEO_SLOTS_KEY, cp.STOCK_IMAGES_KEY, cp.STOCK_VIDEOS_KEY, cp.TEXT_SLOTS_KEY,
            cp.LOCKED_SWITCHES_KEY) + tuple(cp.FILE_PROFILES_KEY.values())


def normalise(kinds):
    """The known kinds of *kinds*, in :data:`KEYS` order."""
    kinds = set(kinds or ())
    return [k for k in KEYS if k in kinds]


def kind_of_rel(rel):
    """The kind an extracted file at *rel* (``/``-separated) belongs to, or ``None`` for one
    only a reset of everything puts back."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    low = rel.lower()
    if low.startswith("audio/"):
        return "sounds"
    if low.startswith("video/"):
        return "videos"
    if low.startswith("text/"):
        return "text"
    if low.startswith("images/scene_textures/glyphs/"):
        return "fonts"
    if low.startswith("images/"):
        return "images"
    return None


def rel_filter(kinds):
    """``rel -> bool``: the extracted files a reset of *kinds* puts back (every kind: all)."""
    kinds = set(normalise(kinds))
    if kinds == set(KEYS):
        return lambda rel: True
    return lambda rel: kind_of_rel(rel) in kinds


# ---------------------------------------------------------------------------------------------
# what there is to reset
# ---------------------------------------------------------------------------------------------
def _mode_dirs(assets_dir):
    d = os.path.join(assets_dir, "modes")
    try:
        return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def _colour_count(assets_dir, data):
    from . import colour_profile as cp
    n = 0
    try:
        n += cp.for_project(assets_dir) is not None
    except Exception:                                # noqa: BLE001
        pass
    for key in _colour_keys():
        if key in (cp.KEY,):
            continue
        val = data.get(key)
        if isinstance(val, dict):
            n += len(val) if key != cp.ASSET_KEY else 1
        elif isinstance(val, (list, tuple)):
            n += len(val)
        elif val:
            n += 1
    return n


def counts(assets_dir, changed=None):
    """``{kind: how many changes}`` in *assets_dir*: its records, and the extracted files it
    changed (*changed*: the rels :func:`checksums.all_changed` found, when known)."""
    out = dict.fromkeys(KEYS, 0)
    if not assets_dir or not os.path.isdir(assets_dir):
        return out
    data = staged_changes.load(assets_dir)
    try:
        from ..plugins.stern import scene_edit
        out["scenes"] += scene_edit.count(assets_dir)
    except Exception:                                # noqa: BLE001
        pass
    out["scenes"] += len(data.get("score_colors") or {})
    out["colours"] = _colour_count(assets_dir, data)
    for kind, keys in _SIDECAR.items():
        if kind == "scenes":
            continue
        main = keys[0]
        out[kind] += len(data.get(main) or {})
    out["videos"] += len(data.get("video_variants") or {}) + len(data.get("own_clips") or [])
    out["sounds"] += len(staged_changes.sound_modes_of(data) or {})
    try:
        from . import text_manifest
        out["text"] += text_manifest.count_changed(assets_dir)
    except Exception:                                # noqa: BLE001
        pass
    try:
        from ..plugins.stern import text_colors
        out["text"] += text_colors.count(assets_dir)
    except Exception:                                # noqa: BLE001
        pass
    out["modes"] += len(_mode_dirs(assets_dir))
    try:
        from ..plugins.stern import stock_modes
        out["modes"] += stock_modes.pending_count(assets_dir)
    except Exception:                                # noqa: BLE001
        pass
    for rel in changed or ():
        if rel.replace("\\", "/").lower() in _RECORD_FILES:
            continue                                 # counted by its edits above
        kind = kind_of_rel(rel)
        if kind is not None:
            out[kind] += 1
    return out


# ---------------------------------------------------------------------------------------------
# resetting
# ---------------------------------------------------------------------------------------------
def drop_records(assets_dir, kinds):
    """Forget the records of *kinds*: the sidecar's keys, the Scenes, Text and modes files.
    Every kind: the whole sidecar but what Revert all keeps (the machine screen, and the
    record that the project manages the game's own modes).  Returns the lines for the log."""
    kinds = set(normalise(kinds))
    if not kinds or not assets_dir:
        return []
    said = []
    data = staged_changes.load(assets_dir)
    if kinds == set(KEYS):
        try:
            from ..plugins.stern import stock_modes
            data = stock_modes.kept_by_revert_all(data)
        except Exception:                            # noqa: BLE001
            from .colour_profile import SCREEN_KEY
            data = {k: v for k, v in data.items() if k == SCREEN_KEY}
    else:
        if "videos" in kinds:
            _remove_clip_copies(assets_dir)
            data = staged_changes.load(assets_dir)
        drop = set()
        for kind in kinds:
            drop.update(_SIDECAR.get(kind, ()))
        if "colours" in kinds:
            drop.update(_colour_keys())
        if "modes" in kinds:
            try:
                from ..plugins.stern import stock_modes
                kept = stock_modes.kept_by_revert_all(
                    {stock_modes.STAGE_KEY: data.get(stock_modes.STAGE_KEY)})
                if stock_modes.STAGE_KEY in kept:
                    data[stock_modes.STAGE_KEY] = kept[stock_modes.STAGE_KEY]
            except Exception:                        # noqa: BLE001
                pass
        for key in drop:
            data.pop(key, None)
        names = data.get("replacement_names")
        if isinstance(names, dict):
            data["replacement_names"] = {
                rel: n for rel, n in names.items() if kind_of_rel(rel) not in kinds}
    if kinds == set(KEYS) and "own_clips" in staged_changes.load(assets_dir):
        _remove_clip_copies(assets_dir)
    staged_changes.save(assets_dir, data)
    if "scenes" in kinds:
        try:
            from ..plugins.stern import scene_edit
            n = scene_edit.count(assets_dir)
            scene_edit.clear(assets_dir)
            if n:
                said.append("dropped %d Scenes edit(s)" % n)
        except Exception:                            # noqa: BLE001
            pass
    if "text" in kinds:
        try:
            from . import text_manifest
            n = text_manifest.revert_all(assets_dir)
            if n:
                said.append("dropped %d text edit(s)" % n)
        except Exception:                            # noqa: BLE001
            pass
        try:
            from ..plugins.stern import text_colors
            n = text_colors.clear_all(assets_dir)
            if n:
                said.append("dropped %d text color(s)" % n)
        except Exception:                            # noqa: BLE001
            pass
    if "fonts" in kinds:
        n = _revert_fonts(assets_dir)
        if n:
            said.append("restored %d font letter(s)" % n)
    if "modes" in kinds:
        gone = _mode_dirs(assets_dir)
        for slug in gone:
            shutil.rmtree(os.path.join(assets_dir, "modes", slug), ignore_errors=True)
        for name in ("stock.json",):
            try:
                os.remove(os.path.join(assets_dir, "modes", name))
            except OSError:
                pass
        if gone:
            said.append("deleted %d mode(s): %s" % (len(gone), ", ".join(gone)))
    return said


def _remove_clip_copies(assets_dir):
    try:
        from ..plugins.stern import clip_modes
        clip_modes.remove_copies(assets_dir)
    except Exception:                                # noqa: BLE001
        pass


def _revert_fonts(assets_dir):
    try:
        from ..plugins.stern import fontrender as fr
        fonts = fr.load_fonts(assets_dir)
    except Exception:                                # noqa: BLE001
        return 0
    n = 0
    for fo in fonts:
        try:
            n += fr.revert_slices(assets_dir, fo)
        except Exception:                            # noqa: BLE001
            continue
    return n


def restore_snapshots(assets_dir, kinds):
    """Put back every snapshotted file of *kinds* (``.orig``); returns the rels restored."""
    keep = rel_filter(kinds)
    done = []
    for rel in sorted(staged_originals.snapshot_rels(assets_dir)):
        if keep(rel) and staged_originals.revert(assets_dir, rel):
            done.append(rel)
    root = os.path.join(assets_dir, staged_originals.ORIG_DIR)
    if os.path.isdir(root) and not os.listdir(root):
        try:
            os.rmdir(root)
        except OSError:
            pass
    return done
