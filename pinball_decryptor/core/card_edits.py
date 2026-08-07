"""What PAD itself has replaced on a raw card image, remembered per image.

The Partitions tab's Replace writes straight into the card image the user
points it at, and nothing recorded that it happened.  That cost a tester
(batch 30) twice in one session, both times on the same ``SternLogo.png`` swap:

  * The write moved the image's mtime, so the Replace/Write tabs' "the source
    image has changed on disk since these assets were extracted — re-run
    Extract to refresh" banner fired on PAD's own edit and told him to redo an
    extract that was perfectly fine.  :mod:`core.extract_source` asks this
    module first now.
  * Nothing on the tab said which files he had already swapped: "there is no
    indicator if the file is original or has been changed … this could make it
    more difficult for deeper and more complex changes to keep track of all
    changes."

One JSON store beside ``settings.json``, keyed by the image's absolute path.
Each entry holds that image's replaces — partition, on-card path, old and new
size, when, and the file they came from — plus the image's ``(size, mtime)``
signature as of the last of them.  The signature is the interesting part: it
is what lets a caller tell "this image differs from the extract because of MY
edits" from "something else changed it", with one ``stat`` and no re-read of a
multi-gigabyte card.

It records what PAD did, which is all it can honestly claim: an edit made
outside the app (a hand mount, another tool) leaves no trace here, so callers
present the result as "files you replaced with PAD", never as proof that
everything else on the card is untouched.

Best-effort throughout — a missing or corrupt store reports nothing, and a
failed write never fails the replace it was describing.
"""

import json
import os
import time

from . import config

#: One shared file alongside settings.json: {image key: {...}}.
CARD_EDITS_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                               "card_edits.json")

#: Keep the per-image journal from growing without bound (newest kept).
_MAX_EDITS_PER_IMAGE = 500


def _key(image_path):
    """Store key for *image_path* — absolute, and case-folded on Windows so
    the same card reached through a differently-cased path is one entry."""
    if not image_path:
        return ""
    return os.path.normcase(os.path.abspath(str(image_path)))


def _signature(image_path):
    """``{"size": …, "mtime": …}`` for *image_path*, or ``None``.

    Whole-second mtime, matching :mod:`core.extract_source` — the two compare
    the same numbers about the same file.
    """
    try:
        st = os.stat(image_path)
    except OSError:
        return None
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def _load():
    try:
        with open(CARD_EDITS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    try:
        os.makedirs(os.path.dirname(CARD_EDITS_FILE), exist_ok=True)
        with open(CARD_EDITS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except OSError:
        pass


def record_replace(image_path, partition, card_path, old_size, new_size,
                   source_path=None):
    """Remember that PAD replaced *card_path* on *image_path*.

    *partition* is the 0-based partition index (``sda1`` is 0), *card_path* the
    absolute on-card path, and *source_path* the file the bytes came from.  The
    image's signature is re-stamped from disk afterwards, so this must be
    called AFTER the write lands.
    """
    key = _key(image_path)
    if not key or not card_path:
        return
    data = _load()
    entry = data.get(key)
    if not isinstance(entry, dict):
        entry = {}
    edits = entry.get("edits")
    if not isinstance(edits, list):
        edits = []
    edits.append({
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "partition": partition,
        "path": card_path,
        "old_size": old_size,
        "new_size": new_size,
        "source": os.path.abspath(str(source_path)) if source_path else "",
    })
    entry["edits"] = edits[-_MAX_EDITS_PER_IMAGE:]
    entry["path"] = os.path.abspath(str(image_path))
    sig = _signature(image_path)
    if sig:
        entry["sig"] = sig
    data[key] = entry
    _save(data)


def edits_for(image_path):
    """Every recorded replace on *image_path*, oldest first (``[]`` if none)."""
    entry = _load().get(_key(image_path))
    if not isinstance(entry, dict):
        return []
    edits = entry.get("edits")
    return [e for e in edits if isinstance(e, dict)] if isinstance(edits, list) \
        else []


def replaced(image_path, partition=None):
    """``{on-card path: latest edit}`` for *image_path*.

    Pass *partition* to keep only that partition's replaces — the Partitions
    tab marks one partition's tree at a time, and the same path can exist on
    two of them (``/etc`` is on both Spike 2 ext partitions).
    """
    out = {}
    for e in edits_for(image_path):
        if partition is not None and e.get("partition") != partition:
            continue
        p = e.get("path")
        if p:
            out[p] = e                  # later edit of the same file wins
    return out


def signature_current(image_path):
    """Whether *image_path* still looks exactly as it did after PAD's last
    recorded replace.

    ``False`` when there are no recorded edits, when the signature was never
    stamped, or when the image's size/mtime moved since — i.e. when something
    other than PAD has had at it, so callers must not blame their own edits for
    the difference.
    """
    entry = _load().get(_key(image_path))
    if not isinstance(entry, dict) or not entry.get("edits"):
        return False
    sig = entry.get("sig")
    if not isinstance(sig, dict):
        return False
    now = _signature(image_path)
    if now is None:
        return False
    return (now["size"] == sig.get("size")
            and now["mtime"] == sig.get("mtime"))


def describe(image_path, partition=None, limit=3):
    """A human phrase naming the replaces on *image_path*, or ``""``.

    e.g. ``2 files you replaced with the Partitions tab
    (/usr/local/spike/SternLogo.png, /etc/init.d/game)``.
    """
    paths = sorted(replaced(image_path, partition))
    if not paths:
        return ""
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += ", and %d more" % (len(paths) - limit)
    return ("%d file%s you replaced with the Partitions tab (%s)"
            % (len(paths), "" if len(paths) == 1 else "s", shown))


def forget(image_path):
    """Drop *image_path*'s journal entirely (nothing else needs it — kept for
    tests and for a future "start tracking this card again")."""
    key = _key(image_path)
    data = _load()
    if key in data:
        del data[key]
        _save(data)
