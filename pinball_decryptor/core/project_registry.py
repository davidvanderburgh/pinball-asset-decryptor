"""The known-projects registry — what the Project menu's Recent list and the
Projects… manager window show.

Pure functions over the app's settings dict (the App owns persistence — every
mutator here rides on the caller's ``_save_settings()``).  The list is only
ever fed by folders the app has actually anchored or opened: it NEVER crawls
the filesystem (slow on a NAS, and surprising).  A folder that has since been
deleted or moved stays listed as "missing" until the user removes or
relocates it — the manager surfaces that state rather than silently dropping
history.

Entries are dicts ``{"folder", "manufacturer", "last_opened"}``, most recent
first, deduped case-insensitively on the normalised folder path.
"""

import os

SECTION = "projects"

# A generous cap — this is a bounded history, not a database.  Oldest fall
# off; 200 projects is far past any real modding workflow.
MAX_ENTRIES = 200


def _norm(folder):
    return os.path.normcase(os.path.normpath(folder or ""))


def entries(settings):
    """All registry entries, most recent first (copies — safe to mutate)."""
    out = []
    for e in settings.get(SECTION, []):
        if isinstance(e, dict) and (e.get("folder") or "").strip():
            out.append(dict(e))
    return out


def touch(settings, folder, *, manufacturer="", stamp=""):
    """Upsert *folder* at the head of the registry.

    *stamp* is the caller-supplied last-opened value (ISO datetime string) —
    passed in rather than read from the clock so this module stays pure and
    trivially testable.  An existing entry keeps its manufacturer unless a
    non-empty one is given."""
    folder = (folder or "").strip()
    if not folder:
        return
    key = _norm(folder)
    kept = []
    prev = None
    for e in entries(settings):
        if _norm(e.get("folder")) == key:
            prev = e
        else:
            kept.append(e)
    entry = {
        "folder": folder,
        "manufacturer": (manufacturer
                         or (prev or {}).get("manufacturer", "") or ""),
        "last_opened": stamp or (prev or {}).get("last_opened", "") or "",
    }
    settings[SECTION] = [entry] + kept[:MAX_ENTRIES - 1]


def remove(settings, folder):
    """Drop *folder* from the registry (list-only — never touches disk).
    Returns True when an entry was removed."""
    key = _norm(folder)
    kept = [e for e in entries(settings) if _norm(e.get("folder")) != key]
    removed = len(kept) != len(entries(settings))
    settings[SECTION] = kept
    return removed


def relocate(settings, old_folder, new_folder):
    """Re-point a (typically "missing") entry at *new_folder*, keeping its
    place in the recency order.  Returns True when an entry moved."""
    key = _norm(old_folder)
    new_folder = (new_folder or "").strip()
    if not new_folder:
        return False
    moved = False
    out = []
    for e in entries(settings):
        if _norm(e.get("folder")) == key:
            e = dict(e, folder=new_folder)
            moved = True
        out.append(e)
    settings[SECTION] = out
    return moved


def recent(settings, n=8):
    """The first *n* entries — the Project menu's Recent submenu."""
    return entries(settings)[:max(0, n)]
