"""Pair a folder of replacement files with a Replace tab's slots BY NAME.

A modder who reworks a whole set of extracted files outside the app (every
clip on the card made black and white, say) gets them back under the same
names -- but not always the same file type.  A batch converter writes one
container, and a Spike 2 extract saves a card's QuickTime clips as ``.mov``
beside its ``.mp4`` ones (145 of Godzilla 1.16's 658), so a third of those
names come back as ``.mp4``.  Dropped into the project folder they landed
BESIDE the slots instead of in them: the Video tab listed each one as "not on
this card" and the build left the card's clip alone (PAD-163).  Picking 145
replacements by hand is the only other way in.

:func:`match_folder` pairs by name instead, ignoring the file type and letter
case, so each file becomes an ordinary replacement pick and the tab's normal
staging converts it to suit its slot (a clip that only differs in container is
repackaged, not re-encoded).  :func:`foreign_twins` is the other half: it tells
the Replace tabs which strays already in a project are one of those files, so
the row can say so instead of blaming a mod pack.
"""

import os
import re

#: A scene picture's or glyph atlas's extracted name ends in the first 8 hex
#: digits of the MD5 of its bytes on the card (``radimg_512x512_bba78124``,
#: see plugins.stern.engine.extract_radium_images).  The same picture off a
#: card that was built with changes, or off different code, has a different
#: name -- no name pairing can find it.
FINGERPRINT_RE = re.compile(r"radimg_[^/]*_[0-9a-f]{8}(?:\.[A-Za-z]+)?(?:/|$)")


def _key_parts(rel):
    """*rel* as lower-case path components with the file type dropped."""
    parts = rel.replace("\\", "/").lower().split("/")
    parts[-1] = os.path.splitext(parts[-1])[0]
    return parts


def _ext(rel):
    return os.path.splitext(rel)[1].lower()


def match_folder(folder, slot_rels, exts):
    """Pair the files under *folder* with *slot_rels* by name.

    *slot_rels* are a Replace tab's ``/``-separated slot paths
    (``video/Tank_Jackpot1.mov``); *exts* the file types this tab can take as
    a replacement (lower-case, with the dot).  Subfolders are walked, and a
    file's folders help it choose: ``BW/video/x.mp4`` prefers the slot at
    ``video/x.*`` when two slots are called ``x``.  The longest run of trailing
    path components that names exactly one slot wins, so a flat folder of
    uniquely named clips pairs as readily as a copy of the whole project.

    Returns a dict:

    ``pairs``       ``{slot_rel: absolute file path}``
    ``retyped``     slot rels paired with a file of a different type
    ``unmatched``   file rels (relative to *folder*) named like no slot
    ``ambiguous``   file rels named like several slots, with nothing in their
                    own path to say which
    ``duplicates``  file rels that lost a slot to a better-named file
    ``files``       how many files of a usable type the folder holds
    """
    exts = {e.lower() for e in exts}
    index = {}
    for rel in slot_rels:
        parts = _key_parts(rel)
        for k in range(1, len(parts) + 1):
            index.setdefault("/".join(parts[-k:]), []).append(rel)

    files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith(".") or _ext(fn) not in exts:
                continue
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, folder).replace(os.sep, "/")
            files.append((rel, abs_path))

    best = {}           # slot rel -> (score, file rel, abs path)
    unmatched, ambiguous, duplicates = [], [], []
    for frel, fabs in files:
        parts = _key_parts(frel)
        cands, depth = None, 0
        for k in range(len(parts), 0, -1):
            cands = index.get("/".join(parts[-k:]))
            if cands:
                depth = k
                break
        if not cands:
            unmatched.append(frel)
            continue
        if len(cands) > 1:
            # Two slots differing only in type (x.png beside x.jpg): the
            # file's own type settles it.
            same = [c for c in cands if _ext(c) == _ext(frel)]
            if len(same) != 1:
                ambiguous.append(frel)
                continue
            cands = same
        slot = cands[0]
        score = (depth, _ext(slot) == _ext(frel))
        prev = best.get(slot)
        if prev is None or score > prev[0]:
            if prev is not None:
                duplicates.append(prev[1])
            best[slot] = (score, frel, fabs)
        else:
            duplicates.append(frel)

    pairs = {slot: fabs for slot, (_s, _f, fabs) in best.items()}
    return {
        "pairs": pairs,
        "retyped": sorted(s for s, (_sc, frel, _a) in best.items()
                          if _ext(s) != _ext(frel)),
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "duplicates": sorted(duplicates),
        "files": len(files),
    }


def foreign_twins(rels, baseline, casefold=None):
    """Split *rels* into strays and their would-be slots.

    Returns ``(foreign, twins)``: *foreign* is the set of *rels* the Extract
    *baseline* (``{rel: md5}``) has no entry for, and *twins* maps each of
    those that differs from exactly one baselined file only in its file type
    to that file (``video/Tank_Jackpot1.mp4`` -> ``video/Tank_Jackpot1.mov``).

    *casefold* (default: on Windows) treats a name that differs only in
    letter case as the baselined file itself, NOT a stray -- the filesystem
    there is case-insensitive, so the build opens it by the card's name and
    writes it."""
    if casefold is None:
        casefold = os.name == "nt"
    by_case = {r.lower(): r for r in baseline} if casefold else {}
    foreign = {r for r in rels
               if r not in baseline and r.lower() not in by_case}
    if not foreign:
        return foreign, {}
    stems = {}
    for r in baseline:
        stems.setdefault("/".join(_key_parts(r)), []).append(r)
    twins = {}
    for r in foreign:
        hits = stems.get("/".join(_key_parts(r)))
        if hits and len(hits) == 1:
            twins[r] = hits[0]
    return foreign, twins
