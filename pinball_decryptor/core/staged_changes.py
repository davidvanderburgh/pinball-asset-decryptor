"""Persists the user's pending (un-written) Replace-Audio/Video/Image
assignments into the assets folder, so they survive quitting and re-opening
the app.

The Replace tabs hold each assignment in memory only — ``rel_path ->
replacement source file`` — and apply them at Write time; there is no manual
"stage" step.  Without this, quitting the app loses every assignment and the
user has to re-pick each replacement folder by folder.  This drops a small JSON
sidecar (:data:`SIDE_CAR`) at the root of the assets folder recording those
assignments (plus the per-slot audio Loop flags and the trim toggles).

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
