"""Append-only, human-readable history of what the user changed in an assets
folder — every replacement pick/re-pick/clear (with the old and new source
file), staged default-settings edits, builds and reverts, each stamped with
date and time.

The session log already says these things, but it is a rolling record of one
session; this file is the project's own memory.  Monkeybug (batch 24): a slot
that says "changed on disk" months later doesn't say what it was changed
WITH — he had to open the file and compare it by eye against the folder he
thought it came from.  One grep-able file at the root of the assets folder
answers that, survives app updates, and travels with the project.

Dot-named (:data:`FILE_NAME`) so every existing pipeline ignores it for free:
the audio/video/image slot scanners, the checksum baseline, mod-pack export,
mod transfer and the revert flow all skip dot-entries — the same rule
``.staged_changes.json`` and ``.extract_source.json`` rely on.  It is still a
plain UTF-8 text file, opened from Project ▾ → "Change history…" (Windows
Explorer shows dot-files fine for anyone going in by hand).

Best-effort everywhere: a history line is never worth failing the action it
describes.
"""

import os
import time

FILE_NAME = ".history.log"


def path_for(assets_dir):
    """Where *assets_dir*'s history file lives (the file may not exist yet)."""
    return os.path.join(assets_dir, FILE_NAME)


def record(assets_dir, events):
    """Append *events* (one string or a list of them) to the history file,
    each on its own timestamped line.  Best-effort no-op on any I/O error or
    when there's nothing to write."""
    if not assets_dir or not events:
        return
    if isinstance(events, str):
        events = [events]
    events = [ev for ev in events if ev]
    if not events:
        return                  # don't create an empty file for no news
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path_for(assets_dir), "a", encoding="utf-8") as f:
            for ev in events:
                f.write("%s  %s\n" % (stamp, ev))
    except OSError:
        pass


def diff_assignments(kind, old, new):
    """Human lines for what changed between two ``{rel: source_path}``
    assignment maps — picked / changed (with the previous source) / cleared.
    Returns a list of event strings for :func:`record` (empty = no change)."""
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    events = []
    for rel in sorted(set(old) | set(new), key=str):
        o, n = old.get(rel), new.get(rel)
        if o == n:
            continue
        if o and n:
            events.append('%s  %s  replacement changed to: %s  (was: %s)'
                          % (kind, rel, n, o))
        elif n:
            events.append('%s  %s  replacement picked: %s' % (kind, rel, n))
        else:
            events.append('%s  %s  replacement cleared  (was: %s)'
                          % (kind, rel, o))
    return events


def diff_scalar(label, old, new):
    """One event line for a changed scalar setting, or None if unchanged /
    the old value was never recorded (a first save is not a change)."""
    if old is None or old == new:
        return None
    def _fmt(v):
        if isinstance(v, bool):
            return "on" if v else "off"
        return str(v)
    return "%s: %s -> %s" % (label, _fmt(old), _fmt(new))
