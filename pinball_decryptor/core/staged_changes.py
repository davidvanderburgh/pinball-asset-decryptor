"""Persists the user's pending (un-written) Replace-Audio/Video/Image
assignments into the assets folder, so they survive quitting and re-opening
the app.

The Replace tabs hold each assignment in memory only — ``rel_path ->
replacement source file`` — and apply them at Write time; there is no manual
"stage" step.  Without this, quitting the app loses every assignment and the
user has to re-pick each replacement folder by folder.  This drops a small JSON
sidecar (:data:`SIDE_CAR`) at the root of the assets folder recording those
assignments (plus the per-slot audio Loop flags, the per-slot audio loudness
offsets under ``"audio_levels"``, and the trim toggles).

``"audio_levels"`` (``{rel path -> dB}``) is also read by the Stern write
pipeline itself (``engine._slot_gain_maps``) rather than passed to it, the same
way the video path reads its originals map back out of here.

The sidecar is keyed implicitly by the folder it lives in: each Replace tab only
restores it when it scans that same folder, and the assets folder's identity vs
its source image is already tracked separately by ``.extract_source.json``.
(Replace Text already persists via ``text/strings.tsv``, so it isn't included
here.)
"""

import json
import os

# Sidecar written at the root of the assets folder.  Dotfile so the
# audio/video/image slot scanners (which skip dot-entries) ignore it — same
# rule the ``.extract_source.json`` / ``.checksums.md5`` sidecars rely on.
SIDE_CAR = ".staged_changes.json"


def load(assets_dir):
    """Return the staged-changes mapping recorded for *assets_dir*, or ``{}``.

    Best-effort: a missing/old/corrupt sidecar simply yields ``{}`` (the same
    empty state a folder that was never edited has), so callers never need to
    special-case "no file yet".
    """
    if not assets_dir:
        return {}
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(assets_dir, payload):
    """Write *payload* (a JSON-able dict) to ``assets_dir``/:data:`SIDE_CAR`.

    Best-effort: silently no-ops if the folder doesn't exist or isn't writable.
    """
    if not assets_dir or not os.path.isdir(assets_dir):
        return
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), "w",
                  encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


def live_assignments(saved, slots_by_rel):
    """Filter a saved ``{rel: replacement_path}`` map down to the entries that
    are still applicable: the slot still exists in *slots_by_rel* and the
    replacement source file is still present on disk.

    Used when a tab restores from the sidecar so a since-deleted replacement
    file or a slot that vanished from a re-extract is dropped quietly rather
    than surfacing as a broken assignment.
    """
    out = {}
    for rel, path in (saved or {}).items():
        if (rel in slots_by_rel and isinstance(path, str)
                and os.path.isfile(path)):
            out[rel] = path
    return out


def dropped_assignments(saved, slots_by_rel):
    """The entries :func:`live_assignments` would drop, as ``[(rel, path,
    reason)]`` — the slot no longer exists in this folder, or the replacement
    source file isn't reachable.

    A disconnected NAS share / mapped drive looks exactly like a missing
    source file, so callers must WARN with these instead of quietly building
    or exporting without a recorded replacement (a tester).

    The two missing-file cases get different words (batch 24: a tester read
    "NAS/drive disconnected?" as the app failing to load a clip that was fine):
    when the file's own folder still answers, the drive is clearly connected —
    the file itself was moved, renamed or deleted since it was picked.  Only
    when the folder doesn't answer either is a disconnected share the likely
    story.
    """
    out = []
    for rel, path in (saved or {}).items():
        if not path or not isinstance(path, str):
            continue
        if rel not in slots_by_rel:
            out.append((rel, path, "its slot isn't in this folder"))
        elif not os.path.isfile(path):
            if os.path.isdir(os.path.dirname(path) or "."):
                out.append((rel, path,
                            "the file is no longer in its folder (moved, "
                            "renamed or deleted since it was picked)"))
            else:
                out.append((rel, path,
                            "its folder isn't reachable right now "
                            "(NAS/drive disconnected?)"))
    return out


def same_stem_sibling(path):
    """A file beside the missing *path* with the same name but another
    extension (``clip.mp4`` recorded, only ``clip.mov`` on disk), or ``None``.

    The usual story behind "the file is no longer in its folder": the clip
    was re-exported in a new container and the old file deleted, so only the
    extension differs — a difference invisible in a full NAS path (batch 25:
    A tester saw ``26s_..._Promos2.mov`` sitting right there and read the
    note about the recorded ``...Promos2.mp4`` as a false alarm).  Callers
    surface it next to the missing path so the note explains itself."""
    folder = os.path.dirname(path) or "."
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    if not stem:
        return None
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        if (name.lower() != base.lower()
                and os.path.splitext(name)[0].lower() == stem.lower()
                and os.path.isfile(os.path.join(folder, name))):
            return name
    return None
