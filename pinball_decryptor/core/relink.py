"""Repoint a project's recorded replacement sources after the files move.

The sidecar (:mod:`.staged_changes`) records the PATH of the file each slot
was replaced with, not a copy of it — that is what keeps a project folder
small and what lets a re-pick of the same clip be recognised later.  The
cost is that every one of those paths is a path *on the PC that picked it*.
Copy the project to a second machine (or move the media library to another
drive) and every recorded replacement points at a folder that isn't there:
:func:`staged_changes.live_assignments` drops them all, the Replace tabs come
up empty, and a build applies nothing.

A modder hit exactly this moving a 500-replacement Godzilla project onto a
faster PC to build images: "There's like hundreds and hundreds of changes I
can't click through each one of them it will take forever".  Editing the
JSON by hand with a find/replace is the workaround, and it is not one to ask
for.

So: point this module at the folder the files live in NOW and it re-points
the lot in one pass.  The matching is by file NAME plus as much of the
recorded path's tail as still agrees, so it survives the whole shape of the
move — a different drive letter, a renamed top folder, a library that was
re-organised under it — without needing the old and new trees to be
identical.  Only assignments whose recorded file is genuinely missing are
touched: a slot you have already re-picked by hand on this PC is left
exactly as it is.

Pure path/dict work with the filesystem behind two injectable callables, so
the whole thing is testable without a media library.
"""

import os
import re

#: The sidecar sections that hold a ``{slot rel path: source file}`` map.
KINDS = ("audio", "video", "image")

_SEP_RE = re.compile(r"[\\/]+")

#: Hard stop on how many files a search will index.  A user who picks the
#: root of a 4 TB drive by mistake should get a bounded (and cancellable)
#: wait, not a walk that looks like a hang.
MAX_INDEX_FILES = 400000


def _parts(path):
    """*path* split into its components, separator-agnostic.

    Recorded paths come from whichever PC made the pick, so a project made
    on Windows can be relinked on a Mac and vice versa — splitting on both
    separators means the tail comparison still works across that."""
    return [p for p in _SEP_RE.split(path or "") if p and p != "."]


def file_name(path):
    """The file name out of a RECORDED path, whichever PC wrote it.

    ``os.path.basename`` only knows the host's separator, so the name it reads
    out of a Windows-recorded path on a Mac is the whole path — and a project
    carried between those two PCs is the case this module exists for.  The
    window lists these names back to the user, so it needs the same rule the
    matching uses."""
    parts = _parts(path)
    return parts[-1] if parts else ""


def recorded_sources(staged):
    """``{source path: [(kind, slot rel), ...]}`` for every replacement the
    sidecar records, in a stable order (kind, then slot).

    Keyed by the SOURCE file because that is the unit of a move: one clip
    assigned to eight slots is one file to find, not eight."""
    out = {}
    for kind in KINDS:
        section = (staged or {}).get(kind)
        if not isinstance(section, dict):
            continue
        for rel in sorted(section):
            path = section.get(rel)
            if isinstance(path, str) and path.strip():
                out.setdefault(path, []).append((kind, rel))
    return out


def missing_sources(staged, isfile=os.path.isfile):
    """:func:`recorded_sources` filtered to the files that aren't there.

    *isfile* is injectable for tests.  A path that raises (a dead mapped
    drive can) counts as missing — that is exactly the case this exists
    for."""
    out = {}
    for path, slots in recorded_sources(staged).items():
        try:
            present = isfile(path)
        except OSError:
            present = False
        if not present:
            out[path] = slots
    return out


def common_root(paths):
    """The deepest folder every path in *paths* sits under, as a string.

    Shown back to the user as "these were last seen in …", so they know
    which folder of theirs the app is asking them to re-find.  Comparison
    is case-insensitive (the recorded paths are usually Windows) but the
    answer keeps the first path's original casing.  ``""`` when the paths
    share nothing (two different drives)."""
    paths = [p for p in (paths or []) if p]
    if not paths:
        return ""
    # The FOLDER of each path, taken with _parts rather than
    # os.path.dirname: dirname only knows the host's separator, so on a Mac
    # or a Linux box it reads a whole recorded Windows path as one bare name
    # and answers "" — which is precisely the PC this module exists to move a
    # project ONTO, and it made the readout say "more than one drive" for a
    # set of paths that shared every folder.
    first = _parts(paths[0])[:-1]
    shared = list(first)
    for p in paths[1:]:
        other = _parts(p)[:-1]
        keep = 0
        for a, b in zip(shared, other):
            if a.lower() != b.lower():
                break
            keep += 1
        shared = shared[:keep]
        if not shared:
            return ""
    if not shared:
        return ""
    # Re-attach the separator style of the original path: a leading drive
    # component ("G:") needs its own backslash, a POSIX path a leading "/".
    if re.match(r"^[A-Za-z]:$", shared[0]):
        return shared[0] + "\\" + "\\".join(shared[1:])
    if paths[0][:1] in ("/", "\\"):
        return "/" + "/".join(shared)
    return os.path.join(*shared)


def build_index(root, wanted_names=None, walk=os.walk, cancel=None,
                progress=None, max_files=MAX_INDEX_FILES):
    """``{lowercased file name: [full path, ...]}`` for the files under
    *root*.

    *wanted_names* (a set of lowercased base names) narrows the index to the
    files we are actually looking for, which is what keeps a 200 000-file
    media library to a few hundred entries of memory.  *cancel* is polled
    per directory so the user can stop a search down the wrong tree, and
    *progress(n_seen, current_dir)* is called as it goes.  Dot-directories
    are skipped: nothing a user picked a replacement from lives in one, and
    they are where caches hide.
    """
    index = {}
    seen = 0
    for dirpath, dirnames, filenames in walk(root):
        if cancel is not None and cancel():
            break
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            seen += 1
            if wanted_names is None or name.lower() in wanted_names:
                index.setdefault(name.lower(), []).append(
                    os.path.join(dirpath, name))
        if progress is not None:
            progress(seen, dirpath)
        if seen >= max_files:
            break
    return index


def _tail_score(old_parts, new_path):
    """How many path components the two agree on, counting back from the
    file name.  The tie-breaker that makes a re-organised library land on
    the right file: ``…\\Godzilla\\intro.mp4`` beats ``…\\Gigan\\intro.mp4``
    for a recorded ``…\\GZ mods\\Godzilla\\intro.mp4``."""
    new_parts = _parts(new_path)
    n = 0
    for a, b in zip(reversed(old_parts), reversed(new_parts)):
        if a.lower() != b.lower():
            break
        n += 1
    return n


def best_match(old_path, index):
    """``(new path, n_candidates)`` for *old_path* in *index*, or
    ``(None, 0)``.

    Ranked by the longest agreeing path tail, then by the shallowest
    candidate (a file at the top of the picked folder is the more likely
    counterpart than one buried in an old backup copy of it), then
    alphabetically so a run is repeatable."""
    old_parts = _parts(old_path)
    if not old_parts:
        return None, 0
    candidates = index.get(old_parts[-1].lower()) or []
    if not candidates:
        return None, 0
    ranked = sorted(candidates,
                    key=lambda c: (-_tail_score(old_parts, c),
                                   len(_parts(c)), c.lower()))
    return ranked[0], len(candidates)


def plan(staged, root, isfile=os.path.isfile, walk=os.walk, cancel=None,
         progress=None):
    """Work out where every missing replacement source moved to.

    Returns ``{"root", "found": {old: new}, "ambiguous": {old: n},
    "not_found": [old, ...], "slots": {old: [(kind, rel), ...]},
    "cancelled": bool}`` — a preview, nothing written.  ``ambiguous`` names
    the files that had more than one candidate under *root*; the pick is
    still the best-ranked one, it just gets said out loud."""
    slots = missing_sources(staged, isfile=isfile)
    # _parts, not os.path.basename, for the same reason common_root does not
    # use os.path.dirname: a recorded Windows path read on a Mac has no base
    # name as far as the host's os.path is concerned, so every wanted name
    # came out as the whole path and the index matched nothing at all.
    wanted = {parts[-1].lower() for parts in map(_parts, slots) if parts}
    index = build_index(root, wanted_names=wanted, walk=walk, cancel=cancel,
                        progress=progress)
    found, ambiguous, not_found = {}, {}, []
    for old in slots:
        new, n = best_match(old, index)
        if new is None:
            not_found.append(old)
            continue
        found[old] = new
        if n > 1:
            ambiguous[old] = n
    return {"root": root, "found": found, "ambiguous": ambiguous,
            "not_found": not_found, "slots": slots,
            "cancelled": bool(cancel is not None and cancel())}


def apply_plan(staged, found):
    """Rewrite *staged* (a copy) with every ``old -> new`` in *found*.

    Returns ``(new staged dict, slots repointed, files repointed)``.  Only
    the three assignment maps are touched — the per-slot loop / loudness /
    as-is flags are keyed on the SLOT, not the source file, so a relink
    leaves every one of them exactly where it was."""
    data = dict(staged or {})
    n_slots = 0
    used = set()
    for kind in KINDS:
        section = data.get(kind)
        if not isinstance(section, dict):
            continue
        section = dict(section)
        for rel, path in list(section.items()):
            new = found.get(path) if isinstance(path, str) else None
            if new:
                section[rel] = new
                used.add(path)
                n_slots += 1
        data[kind] = section
    return data, n_slots, len(used)


def summary_line(result, n_slots):
    """The one line the log and the dialog both say after a relink."""
    n_files = len(result.get("found") or {})
    line = ("Relinked %d replacement file(s) across %d slot(s) to %s"
            % (n_files, n_slots, result.get("root") or "the chosen folder"))
    left = len(result.get("not_found") or [])
    if left:
        line += " — %d file(s) still not found" % left
    return line + "."
