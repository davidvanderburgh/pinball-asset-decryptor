"""A project's revision history, kept in the project folder (PAD-427).

Users build revision after revision of one project, on more than one
computer.  Everything that tied a project to its cards used to be a recorded
PATH (the extract sidecar's ``input_path``, the build record's ``assets``)
plus name, size and mtime, and all of it breaks the moment the folder or the
card moves to another machine; a card built over the last revision was also
taken for "stock" (David, PAD-421: "a lot of times with revisions like this,
we are treating the last version of revisions as stock").

So a project now carries :data:`LINEAGE_FILE`::

    {"format": 1, "id": "<uuid hex>",
     "stock":  {"sidx", "label", "print"},     # the official release it is of
     "source": {"print", "name", "status", "label", "rev"},   # what was extracted
     "revs":   [{"rev", "print", "parent", "parent_rev", "name", "built",
                 "host", "app"}, ...]}          # every card built from it

Every card is named by its FINGERPRINT, not its path: a hash of what the card
holds (for Stern, the card's own manifest checked against the real file
sizes, see ``stock_prints.card_print``).  The same card gives the same print
on any computer under any name, so "which revision is this card?" is a lookup
in ``revs``.  The file is a dotfile in the project folder: a copy of the
folder takes it along, the baseline and the slot scanners skip it, and a mod
pack carries it in its manifest.

Taking a print opens the card (well under a second warm, longer on a cold
spinning disk), so prints are cached per file stamp in :data:`PRINT_CACHE`;
:func:`card_print` answers from the cache unless asked to *measure*.  The
manufacturer that can fingerprint its cards registers a printer
(:func:`register_printer`); this module stays plugin-free.
"""

import json
import os
import socket
import time
import uuid

from . import config

LINEAGE_FILE = ".pad-lineage.json"
LINEAGE_FORMAT = 1

#: ``{card key: {"size", "mtime_ns", "print", "sidx", "label", "official"}}``
#: beside settings.json.
PRINT_CACHE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                           "card_prints.json")
#: Newest entries kept (a print is ~150 bytes).
_MAX_CACHED = 400

_printers = []
_off_stock = []


# ---------------------------------------------------------------------------
# Card fingerprints
# ---------------------------------------------------------------------------

def register_printer(fn):
    """*fn(card_path)* returns ``{"print", "sidx", "label", "official"}`` for
    a card it knows, ``None`` for one it doesn't (or raises)."""
    if fn not in _printers:
        _printers.append(fn)


def _key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def _stamp(path):
    try:
        st = os.stat(path)
    except (OSError, ValueError, TypeError):
        return None
    return st.st_size, st.st_mtime_ns


def _load_cache():
    try:
        with open(PRINT_CACHE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(data):
    if len(data) > _MAX_CACHED:
        keep = sorted(data, key=lambda k: data[k].get("seen", 0))[-_MAX_CACHED:]
        data = {k: data[k] for k in keep}
    try:
        os.makedirs(os.path.dirname(PRINT_CACHE), exist_ok=True)
        tmp = PRINT_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, PRINT_CACHE)
    except OSError:
        pass


def remember_print(card_path, info):
    """Cache *info* (a printer's answer) for the card as it is right now."""
    stamp = _stamp(card_path)
    if stamp is None or not info or not info.get("print"):
        return
    data = _load_cache()
    data[_key(card_path)] = {
        "size": stamp[0], "mtime_ns": stamp[1], "seen": time.time(),
        **{k: info.get(k) for k in ("print", "sidx", "label", "official")}}
    _save_cache(data)


def card_print(card_path, measure=False):
    """The card's fingerprint answer (see :func:`register_printer`), or
    ``None``.  From the cache while the file's size and mtime are unchanged;
    otherwise only with *measure*, which opens the card (call off the UI
    thread)."""
    if not card_path:
        return None
    stamp = _stamp(card_path)
    if stamp is None:
        return None
    hit = _load_cache().get(_key(card_path))
    if hit and (hit.get("size"), hit.get("mtime_ns")) == stamp \
            and hit.get("print"):
        return hit
    if not measure:
        return None
    for fn in list(_printers):
        try:
            info = fn(card_path)
        except Exception:                                 # noqa: BLE001
            info = None
        if info and info.get("print"):
            remember_print(card_path, info)
            return info
    return None


def register_off_stock(fn):
    """*fn(assets_dir)* returns ``(words, files)`` -- what the project's
    extract holds that the official card doesn't, in words, and those
    files' project-relative paths -- or ``None`` when it has no official
    record to measure against."""
    if fn not in _off_stock:
        _off_stock.append(fn)


def off_stock(assets_dir):
    """``(words, files)`` from the first registered measure that answers
    (see :func:`register_off_stock`), or ``("", [])``."""
    for fn in list(_off_stock):
        try:
            got = fn(assets_dir)
        except Exception:                                 # noqa: BLE001
            got = None
        if got is not None:
            return got
    return "", []


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def read_lineage(folder):
    """The project's lineage dict, or ``None`` when it has none."""
    if not folder:
        return None
    try:
        with open(os.path.join(folder, LINEAGE_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != LINEAGE_FORMAT:
        return None
    if not isinstance(data.get("revs"), list):
        data["revs"] = []
    return data


def write_lineage(folder, data):
    """Best-effort atomic write; ``False`` when the folder isn't writable."""
    path = os.path.join(folder, LINEAGE_FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(path + ".tmp", path)
    except OSError:
        return False
    return True


def _new(stock=None):
    return {"format": LINEAGE_FORMAT, "id": uuid.uuid4().hex,
            "stock": stock or {}, "source": {}, "revs": []}


def where(lin, pr):
    """Where the print *pr* sits in the lineage *lin*: ``("rev", n)`` for a
    card built from this project, ``("source", n)`` for the card it was
    extracted from (*n* its revision, ``None`` when unknown), ``("stock",
    0)`` for the official card it is of, or ``None``."""
    if not lin or not pr:
        return None
    for r in reversed(lin.get("revs") or []):
        if r.get("print") == pr:
            return "rev", r.get("rev")
    src = lin.get("source") or {}
    if src.get("print") == pr:
        return "source", src.get("rev")
    if (lin.get("stock") or {}).get("print") == pr:
        return "stock", 0
    return None


def _rev_of(lin, pr):
    w = where(lin, pr)
    return w[1] if w else None


def note_extract(folder, card_name, info, status=""):
    """The project in *folder* was (re-)extracted from the card *info*
    describes (a printer's answer).  *status* is the stock verdict
    (``"official"``/``"modified"``) when one was taken.

    Re-extracting one of this project's own revisions (or its source again)
    keeps the history; extracting any other card starts a new project
    lineage, because the folder's baseline is now that card."""
    if not folder or not info or not info.get("print"):
        return None
    pr = info["print"]
    official = bool(info.get("official"))
    lin = read_lineage(folder)
    w = where(lin, pr)
    if lin is None or (lin.get("stock") or {}).get("sidx") != info.get("sidx") \
            or (w is None and not official):
        lin = _new()
        w = None
    rev = 0 if official else (w[1] if w else None)
    lin["stock"] = {"sidx": info.get("sidx") or "",
                    "label": info.get("label") or "",
                    "print": pr if official else
                    (lin.get("stock") or {}).get("print") or ""}
    lin["source"] = {"print": pr, "name": card_name or "",
                     "status": status or ("official" if info.get("official")
                                          else ""),
                     "label": info.get("label") or "", "rev": rev,
                     "at": time.strftime("%Y-%m-%d %H:%M")}
    write_lineage(folder, lin)
    return lin


def _host():
    try:
        return socket.gethostname()
    except OSError:
        return ""


def note_build(folder, out_name, out_info, parent_info, app_version=""):
    """A card was built from the project in *folder* over the card
    *parent_info* describes; *out_info* describes the result.  Appends the
    revision (or refreshes it when the build changed nothing) and returns its
    entry, or ``None`` when there is nothing to record."""
    if not folder or not out_info or not out_info.get("print"):
        return None
    lin = read_lineage(folder) or _new({
        "sidx": out_info.get("sidx") or "", "label": out_info.get("label") or "",
        "print": ""})
    if parent_info and parent_info.get("official") and \
            not (lin.get("stock") or {}).get("print"):
        lin["stock"] = {"sidx": parent_info.get("sidx") or "",
                        "label": parent_info.get("label") or "",
                        "print": parent_info.get("print")}
    pr = out_info["print"]
    parent = (parent_info or {}).get("print") or ""
    parent_rev = _rev_of(lin, parent)
    if parent_rev is None and (parent_info or {}).get("official"):
        parent_rev = 0
    stamp = {"name": out_name or "", "built": time.strftime("%Y-%m-%d %H:%M"),
             "host": _host(), "app": app_version or ""}
    for r in lin["revs"]:
        if r.get("print") == pr:
            r.update(stamp)       # rebuilt with nothing changed: same revision
            write_lineage(folder, lin)
            return r
    rev = 1 + max([int(r.get("rev") or 0) for r in lin["revs"]] or [0])
    entry = {"rev": rev, "print": pr, "parent": parent,
             "parent_rev": parent_rev, **stamp}
    lin["revs"].append(entry)
    write_lineage(folder, lin)
    return entry


def latest(lin):
    revs = (lin or {}).get("revs") or []
    return max(revs, key=lambda r: int(r.get("rev") or 0)) if revs else None


def base_words(lin):
    """``"official Godzilla LE 1.16"`` / ``"a modified Godzilla LE 1.16
    card"``: what the project's revisions are built on."""
    stock = (lin or {}).get("stock") or {}
    src = (lin or {}).get("source") or {}
    label = stock.get("label") or src.get("label") or "the card"
    if src and src.get("status") not in ("", "official") \
            and not src.get("rev"):
        return "a modified %s card" % label
    return "official %s" % label


def describe(lin):
    """``(line, history)`` for the "This project" card, or ``("", [])``
    when the project has no built revision to name."""
    last = latest(lin)
    if not last:
        return "", []
    line = "Rev %d of %s - last built %s%s" % (
        last["rev"], base_words(lin), last.get("built") or "?",
        (" on %s" % last["host"]) if last.get("host") else "")
    history = []
    for r in sorted(lin.get("revs") or [], key=lambda r: int(r.get("rev")
                                                            or 0)):
        pr = r.get("parent_rev")
        over = ("stock" if pr == 0 else "rev %d" % pr if pr
                else "another card")
        history.append("Rev %d: %s, built %s%s over %s" % (
            r["rev"], r.get("name") or "?", r.get("built") or "?",
            (" on %s" % r["host"]) if r.get("host") else "", over))
    return line, history


def describe_card(lin, pr):
    """``"rev 3 of this project"`` / ``"the card this project was extracted
    from"`` / ``"the official Godzilla LE 1.16 card"`` for a card whose print
    is *pr*, or ``""``."""
    w = where(lin, pr)
    if w is None:
        return ""
    kind, n = w
    if kind == "rev":
        return "rev %d of this project" % n
    if kind == "source":
        return "the card this project was extracted from"
    return "the official %s card" % ((lin.get("stock") or {}).get("label")
                                     or "stock")


# ---------------------------------------------------------------------------
# Finding the official extract of a project's release
# ---------------------------------------------------------------------------

def _release_of(folder):
    """``(sidx, official)`` for the extract in *folder*: the release it is
    of and whether it was extracted from the official card, from its
    lineage, else the extract's stock verdict (PAD-426)."""
    from .extract_source import read_extract_source
    lin = read_lineage(folder) or {}
    sidx = (lin.get("stock") or {}).get("sidx") or ""
    src = lin.get("source") or {}
    if sidx and src.get("print"):
        return sidx, src.get("status") == "official" or src.get("rev") == 0
    stock = (read_extract_source(folder) or {}).get("stock")
    if isinstance(stock, dict) and stock.get("sidx"):
        return stock["sidx"], stock.get("status") == "official"
    return sidx, False


def find_official_extract(assets_dir, candidates=()):
    """An extract of the same release as *assets_dir* that was taken from
    the official card, or ``""``.

    Transfer mods needs one to tell a modified card's own content from
    stock (PAD-176), and the user had to know to supply it.  The project
    knows which release it is of, and an extract records whether its card
    was the official one, so a folder already on disk can be found: the
    *candidates* (recent project folders) and the folders beside
    *assets_dir* are looked at, sidecars only."""
    sidx, _official = _release_of(assets_dir)
    if not sidx:
        return ""
    roots = list(candidates or ())
    parent = os.path.dirname(os.path.normpath(assets_dir))
    try:
        roots += [os.path.join(parent, n) for n in sorted(os.listdir(parent))]
    except OSError:
        pass
    seen = {os.path.normcase(os.path.abspath(assets_dir))}
    for cand in roots:
        if not cand:
            continue
        key = os.path.normcase(os.path.abspath(cand))
        if key in seen or not os.path.isdir(cand):
            continue
        seen.add(key)
        got_sidx, official = _release_of(cand)
        if official and got_sidx == sidx and os.path.isfile(
                os.path.join(cand, ".checksums.md5")):
            return os.path.normpath(cand)
    return ""


# ---------------------------------------------------------------------------
# The history as a graph (the "This project" card draws it)
# ---------------------------------------------------------------------------

def graph(lin):
    """The project's history laid out for drawing, newest first, the way
    ``git log --graph`` lays out commits: ``{"rows": [...], "lanes": n,
    "hosts": [...], "imported": [...]}`` or ``None`` with no revision yet.

    Each row is ``{"key", "parent", "lane", "kind", "title", "sub",
    "host", "tags"}``.  ``kind`` is ``"rev"``, ``"stock"`` (the official
    card), ``"modified"`` (somebody's build the project was extracted from)
    or ``"other"`` (a card a revision was built over that the history does
    not know).  A child keeps its lane until its parent's row, so a build
    over an older revision (a branch) gets a lane of its own and lines
    never cross a node.  ``hosts`` is the computers in order of first build,
    for colouring each revision by where it was built."""
    revs = sorted((r for r in (lin or {}).get("revs") or []
                   if r.get("rev")), key=lambda r: -int(r["rev"]))
    if not revs:
        return None
    src = lin.get("source") or {}
    stock = lin.get("stock") or {}
    label = stock.get("label") or src.get("label") or "the card"
    by_print = {r.get("print"): r for r in revs}
    src_rev = src.get("rev")
    root_kind = ("modified" if src.get("print") and src.get("status")
                 not in ("", "official") and not src_rev else "stock")
    rows, extra = [], {}

    def parent_key(r):
        pr = r.get("parent_rev")
        if pr == 0:
            return "stock"
        if pr and any(int(x["rev"]) == int(pr) for x in revs):
            return "rev%d" % int(pr)
        parent = r.get("parent") or ""
        if parent and parent in by_print:
            return "rev%d" % int(by_print[parent]["rev"])
        if parent and parent == src.get("print"):
            return "source" if root_kind == "modified" else "stock"
        key = "other:" + (parent[:8] or "?")
        extra.setdefault(key, {"key": key, "parent": None, "kind": "other",
                               "title": "Another card",
                               "sub": "not in this project's history",
                               "host": "", "tags": []})
        return key

    newest = int(revs[0]["rev"])
    for r in revs:
        n = int(r["rev"])
        tags = []
        if n == newest:
            tags.append("latest")
        if src_rev and int(src_rev) == n:
            tags.append("extracted")
        sub = " · ".join(x for x in (r.get("name"), r.get("built"),
                                     r.get("host")) if x)
        rows.append({"key": "rev%d" % n, "parent": parent_key(r),
                     "kind": "rev", "title": "Rev %d" % n, "sub": sub,
                     "host": r.get("host") or "", "tags": tags})
    rows += list(extra.values())
    when = src.get("at") or ""
    if root_kind == "modified":
        rows.append({"key": "source", "parent": None, "kind": "modified",
                     "title": "A modified %s card" % label,
                     "sub": " · ".join(x for x in (
                         "extracted from " + (src.get("name") or "?"),
                         when) if x),
                     "host": "", "tags": ["extracted"]})
    else:
        from_card = (src.get("name") if src.get("print") and not src_rev
                     else "")
        rows.append({"key": "stock", "parent": None, "kind": "stock",
                     "title": "Official %s" % label,
                     "sub": " · ".join(x for x in (
                         ("extracted from " + from_card) if from_card else
                         "as Stern released it", when if from_card else "")
                         if x),
                     "host": "", "tags": ["extracted"] if from_card else []})
    # lanes: each slot holds the key of the row it is waiting for
    slots = []
    for row in rows:
        mine = [i for i, k in enumerate(slots) if k == row["key"]]
        if mine:
            lane = mine[0]
            for i in mine[1:]:
                slots[i] = None
        elif None in slots:
            lane = slots.index(None)
        else:
            slots.append(None)
            lane = len(slots) - 1
        slots[lane] = row["parent"]
        row["lane"] = lane
        while slots and slots[-1] is None:
            slots.pop()
    hosts = []
    for r in sorted(revs, key=lambda r: int(r["rev"])):
        if r.get("host") and r["host"] not in hosts:
            hosts.append(r["host"])
    imported = [{"pack": i.get("pack") or "?", "from": i.get("from") or "",
                 "rev": i.get("rev"), "at": i.get("at") or ""}
                for i in (lin.get("imported") or [])]
    return {"rows": rows, "lanes": 1 + max(r["lane"] for r in rows),
            "hosts": hosts, "imported": imported}
