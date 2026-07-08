"""A cross-extract library of the user's renamed image-group tags.

Image-group tags (the "Rename group…" names in Replace Images) are stored per
extract folder in that folder's ``.staged_changes.json`` sidecar, keyed by the
group's container identity (``rad::`` / ``scn::`` / ``dir::``).  A brand-new
extract folder has no sidecar, so re-extracting the *same* card loses every name
the user typed — monkeybug's report (they DO ride mod packs + version transfer,
but a plain re-extract starts blank).

This module mirrors those names into one small JSON file next to
``settings.json``, scoped by *machine identity* (the source card's file name,
which encodes game + version).  On a fresh extract the GUI seeds the sidecar
from the library for that identity, applying only the group keys that still
exist in the new extract.  Cross-VERSION carry-over stays Mod Transfer's job
(its ``_plan_group_tags`` remaps version-shifted keys); this restores
same-version re-extracts only — which is why the scope key includes the version.

Best-effort throughout: a missing/corrupt library, or an extract with no
``.extract_source.json`` (older or device-sourced), simply yields no tags —
exactly the pre-library behaviour.
"""

import json
import os

from . import config, extract_source

# One shared file alongside settings.json, keyed {machine_key: {group_key: name}}.
LIBRARY_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                            "group_tags.json")

_MAX_NAME = 50  # same cap the Rename-group dialog enforces


def _machine_key(assets_dir):
    """The library scope for *assets_dir*: its source card's file name,
    lower-cased.  The name encodes game + version (e.g.
    ``turtles_pro-1_59_0.release.8g.sdcard.raw``), so two versions of the same
    game never share an entry and a v1.21 name is never seeded onto a v1.22
    extract.  ``None`` when the extract has no ``.extract_source.json`` — an
    older or device-sourced extract opts out cleanly."""
    rec = extract_source.read_extract_source(assets_dir)
    if not rec:
        return None
    name = rec.get("input_name")
    if not name:
        return None
    return str(name).strip().lower() or None


def load():
    """Return the whole library ``{machine_key: {group_key: name}}``.

    ``{}`` on a missing/corrupt/foreign-shaped file; each entry is normalised
    (names stripped + capped, blanks and empty entries dropped) so callers get
    the same clean shape :func:`remember` writes."""
    try:
        with open(LIBRARY_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for mkey, tags in data.items():
        if not isinstance(tags, dict):
            continue
        clean = {str(k): str(v).strip()[:_MAX_NAME]
                 for k, v in tags.items() if str(v).strip()}
        if clean:
            out[str(mkey)] = clean
    return out


def _save(data):
    """Write *data* to :data:`LIBRARY_FILE` (best-effort, creates the settings
    dir if needed)."""
    root = os.path.dirname(LIBRARY_FILE)
    try:
        os.makedirs(root, exist_ok=True)
        with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except OSError:
        pass


def seed_tags(assets_dir, present_keys):
    """Return ``{group_key: name}`` the library holds for *assets_dir*'s card,
    limited to keys in *present_keys* (the group keys that exist in this
    extract).

    ``{}`` when the card is unknown or the library has nothing for it.  The
    caller merges these UNDER any names already in the folder's own sidecar, so
    a name the user set in *this* folder always wins over the library."""
    mkey = _machine_key(assets_dir)
    if not mkey:
        return {}
    present = set(present_keys or ())
    tags = load().get(mkey) or {}
    return {k: v for k, v in tags.items() if k in present}


def remember(assets_dir, tags, known_keys):
    """Fold *tags* (the folder's current ``{group_key: name}``) into the library
    under *assets_dir*'s card.

    *known_keys* is this extract's full group-key space; every one is cleared
    from the stored entry first so a name the user *removed* doesn't linger (and
    later re-seed itself), then the non-empty *tags* are written back.  Keys
    outside *known_keys* (a different version's space, in the unlikely event of
    a reused card file name) are left untouched.  No-ops when the card is
    unknown or nothing actually changed."""
    mkey = _machine_key(assets_dir)
    if not mkey:
        return
    data = load()
    entry = dict(data.get(mkey) or {})
    for k in set(known_keys or ()) | set(tags or {}):
        entry.pop(k, None)
    for k, name in (tags or {}).items():
        name = str(name).strip()[:_MAX_NAME]
        if name:
            entry[k] = name
    new_data = dict(data)
    if entry:
        new_data[mkey] = entry
    else:
        new_data.pop(mkey, None)
    if new_data != data:            # skip the write when it's a no-op
        _save(new_data)
