"""My machines (PAD-783): the owner's pinball machines, each a record they
name, bound to the card it runs by that card's FINGERPRINT (see
:mod:`.lineage`), not its path.  "Card" is whatever file the machine runs:
a Stern SD card image, a JJP full-install ISO, a BoF ``.fun`` update
(PAD-787); each manufacturer joins with :func:`register_kind`.

Pure functions over the app's settings dict, like :mod:`.project_registry`
(the App owns persistence; every mutator rides on the caller's
``_save_settings()``).  An entry::

    {"id", "name", "manufacturer", "card", "size", "print", "sidx",
     "label", "official", "added"}

A project joins a machine's row by itself: a project in the registry whose
lineage holds the machine's print -- as the official card it is of, the card
it was extracted from, one of its revisions, or the card a revision was built
over -- is that machine's project.  Nothing is crawled: only registry folders
are read, as the Projects window does.
"""

import os
import uuid

from . import lineage

SECTION = "machines"
#: settings key: the daily game-code check (on unless switched off)
WATCH_KEY = "machine_code_watch"
#: settings key: ``"<machine id>:<build>"`` of every newer build already told
TOLD_KEY = "machine_code_told"
MAX_ENTRIES = 100


_kinds = {}


def register_kind(mfr_key, maker, release, words, noun, file_types,
                  what=""):
    """A manufacturer whose machines can be listed (PAD-787: Stern, JJP,
    BoF).  *release(sidx)* is ``{"key", "version", "build", "title",
    "edition"}`` for a release key its printer answered (or ``None``);
    *words(version)* spells a build as the maker does; *noun* names the
    file a machine runs ("card image", "install ISO"); *file_types* the
    picker's ``(label, patterns)``; *what* that file in a phrase for the
    "isn't a file PAD can read" message."""
    _kinds[mfr_key] = {"maker": maker, "release": release, "words": words,
                       "noun": noun, "types": tuple(file_types),
                       "what": what or noun}


def kinds():
    return dict(_kinds)


def maker(mfr_key):
    return (_kinds.get(mfr_key) or {}).get("maker") or mfr_key or ""


def noun(mfr_key):
    return (_kinds.get(mfr_key) or {}).get("noun") or "card image"


def release_info(machine):
    """The release words for *machine* from its maker's kind, or ``None``."""
    kind = _kinds.get((machine or {}).get("manufacturer"))
    if kind is None or not machine.get("sidx"):
        return None
    return kind["release"](machine["sidx"])


def version_words(mfr_key, version):
    kind = _kinds.get(mfr_key)
    return kind["words"](version) if kind else ""


def _norm(path):
    return os.path.normcase(os.path.normpath(path or ""))


def entries(settings):
    """Every machine, in the owner's order (copies)."""
    return [dict(e) for e in settings.get(SECTION, []) or []
            if isinstance(e, dict) and e.get("id")]


def get(settings, mid):
    for e in entries(settings):
        if e["id"] == mid:
            return e
    return None


def _card_fields(card, info):
    try:
        size = os.path.getsize(card)
    except OSError:
        size = 0
    return {"card": card, "size": size,
            "print": info.get("print") or "", "sidx": info.get("sidx") or "",
            "label": info.get("label") or "",
            "official": bool(info.get("official"))}


def add(settings, card, info, name, manufacturer, stamp=""):
    """A new machine running the card at *card* (*info*: its printer's
    answer).  The same card file added again updates that machine instead.
    Returns the entry."""
    card = os.path.normpath(card)
    rows = entries(settings)
    for e in rows:
        if _norm(e.get("card")) == _norm(card):
            e.update(_card_fields(card, info))
            if name:
                e["name"] = name
            settings[SECTION] = rows
            return e
    entry = {"id": uuid.uuid4().hex[:12], "name": name or "My machine",
             "manufacturer": manufacturer, "added": stamp,
             **_card_fields(card, info)}
    settings[SECTION] = (rows + [entry])[-MAX_ENTRIES:]
    return entry


def rebind(settings, mid, card, info):
    """Point machine *mid* at another card (new code, a new build)."""
    rows = entries(settings)
    for e in rows:
        if e["id"] == mid:
            e.update(_card_fields(os.path.normpath(card), info))
            settings[SECTION] = rows
            return e
    return None


def rename(settings, mid, name):
    name = (name or "").strip()
    rows = entries(settings)
    for e in rows:
        if e["id"] == mid and name:
            e["name"] = name
            settings[SECTION] = rows
            return True
    return False


def remove(settings, mid):
    """List-only: the card and any project are never touched."""
    rows = entries(settings)
    kept = [e for e in rows if e["id"] != mid]
    settings[SECTION] = kept
    return len(kept) != len(rows)


def watch_on(settings):
    return bool(settings.get(WATCH_KEY, True))


def set_watch(settings, on):
    settings[WATCH_KEY] = bool(on)


# ---------------------------------------------------------------------------
# Projects that belong to a machine
# ---------------------------------------------------------------------------

def place_in(lin, pr):
    """Where the print *pr* sits in the lineage *lin*: :func:`lineage.where`'s
    answer, else ``("over", n)`` when a revision was built over that card
    (*n* the newest such revision), else ``None``."""
    w = lineage.where(lin, pr)
    if w is not None:
        return w
    over = [int(r.get("rev") or 0) for r in (lin or {}).get("revs") or []
            if r.get("parent") == pr]
    return ("over", max(over)) if over else None


def projects_for(machine, folders, read=lineage.read_lineage):
    """``[(folder, place, lineage)]`` for every folder in *folders* (the
    registry's, most recent first) whose lineage knows the machine's card."""
    pr = (machine or {}).get("print")
    out = []
    if not pr:
        return out
    for folder in folders:
        lin = read(folder)
        if not lin:
            continue
        w = place_in(lin, pr)
        if w is not None:
            out.append((folder, w, lin))
    return out


def card_words(machine, place=None):
    """What the machine's card is, in a word or three: ``"Stock"``, ``"PAD
    build, rev 3"``, ``"Modified card"``."""
    if place and place[0] in ("rev", "source") and place[1]:
        return "PAD build, rev %d" % int(place[1])
    if machine.get("official"):
        return "Stock"
    if not machine.get("label"):
        return "Not a known release"
    return "Modified card"
