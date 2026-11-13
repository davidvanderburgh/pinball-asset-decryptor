"""Several PCs working on one project together (PAD-1236).

"Say user A is making videos, user B is making scenes, and user C is making
audio.  How can we effectively sync their project together so they're all
looking at the same project together?" (daveyvandy)

Each person keeps their own project, extracted from the same card, and all of
them point it at one TEAM FOLDER that a sync service carries between their PCs
(OneDrive, Dropbox, Google Drive, a network share).  The project is cut into
the parts Project > Reset already cuts it into (:data:`PARTS`: the videos, the
pictures, the sounds, the Scenes edits, ...) and each part has ONE owner, the
member who took it last (:func:`owners`).  So nobody's work is ever merged
over anybody else's:

* :func:`share` writes the parts you own, and only those, into your own
  subfolder of the team folder (``<team>/<you>/``): your files in a Video, an
  Audio and an Images folder (the way Export replacement files lays them out,
  :mod:`.replacement_export`), the Scenes and Modes files their tabs save, the
  extract's files you changed in place, and :data:`SHARE_NAME`, the record of
  it all.  :data:`MEMBER_NAME` beside it, written last, says what you own and
  when you last shared.
* :func:`receive` takes another member's parts into your project the way
  Reset and Import do it: the part is put back the way it was extracted
  (:func:`.project_reset.drop_records`), then their records, files and edits
  go on.  The files are copied into the project (:data:`TEAM_FILES_DIR`), so
  the project never builds from a folder the sync service is rewriting.

Every member writes only inside their own subfolder, so the sync service never
sees two PCs change one file, the case where OneDrive and Dropbox make
"conflicted copy" files and a shared project folder loses work.  A share that
has not finished arriving on this PC (:func:`_complete`) is waited for, not
half applied.

The project remembers its team, its member name and what it last took and
shared in :data:`STATE_NAME`.
"""

import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import time

from . import project_reset, staged_changes
from .atomic_file import write_json_atomic
from .checksums import TEAM_FILES_DIR

#: the project's own record of its team (in the project folder)
STATE_NAME = ".team_sync.json"
#: a member's card in the team folder, written last by a share
MEMBER_NAME = "member.json"
MEMBER_FORMAT = "pad-team-member"
#: what a member shares, beside their files
SHARE_NAME = "share.json"
SHARE_FORMAT = "pad-team-share"
VERSION = 1

#: ``(key, label)`` of every part a member can own, in the order the window lists them;
#: the keys are :data:`.project_reset.KEYS` (what Reset puts back) and ``settings``
PARTS = (
    ("videos", "Videos"),
    ("images", "Images"),
    ("sounds", "Sounds"),
    ("scenes", "Scenes"),
    ("text", "Text"),
    ("fonts", "Fonts"),
    ("modes", "Modes"),
    ("colours", "Color profiles"),
    ("settings", "Defaults and attract"),
)
KEYS = tuple(k for k, _l in PARTS)
LABELS = dict(PARTS)

#: the extracted files a part changes in place, by :func:`.project_reset.kind_of_rel`
#: (a file of no kind is the ``settings`` part's)
_REL_PART = {"videos": "videos", "images": "images", "sounds": "sounds", "fonts": "fonts",
             "text": None}

_SETTINGS_KEYS = ("settings", "high_scores", "setting_ranges", "menu_expose_through",
                  "coin_door", "final_wizard", "topper", "attract_items")

_SAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class TeamError(Exception):
    """Something the user has to sort out, in words for a message box."""


# ---------------------------------------------------------------------------------------------
# which records are which part's
# ---------------------------------------------------------------------------------------------
def part_keys(part):
    """The sidecar keys *part* owns.  A colour key is the Color profiles part's, as on
    Reset, wherever the tab that sets it is."""
    from . import tab_settings
    colour = set(project_reset._colour_keys())
    sec = {"videos": ("video",), "images": ("images",), "sounds": ("audio",)}.get(part, ())
    keys = []
    for s in sec:
        keys += list(tab_settings.SECTIONS[s])
    keys += list(project_reset._SIDECAR.get(part, ()))
    if part == "colours":
        keys += list(project_reset._colour_keys())
    elif part == "settings":
        keys += list(_SETTINGS_KEYS)
    elif part == "modes":
        keys.append("stock_modes")
    if part != "colours":
        keys = [k for k in keys if k not in colour]
    return tuple(k for k in dict.fromkeys(keys) if k != "own_clips")


def part_of_rel(rel):
    """The part an extracted file changed in place belongs to (``None``: one that never
    travels, the Text tab's manifest, whose edits travel as edits)."""
    from .replacement_export import _TEXT_MANIFEST
    rel = (rel or "").replace("\\", "/")
    if rel == _TEXT_MANIFEST:
        return None
    kind = project_reset.kind_of_rel(rel)
    if kind is None:
        return "settings"
    return _REL_PART.get(kind, kind)


def _names_of(names, parts):
    """The ``replacement_names`` entries of *parts*' slots."""
    return {rel: n for rel, n in (names or {}).items() if part_of_rel(rel) in parts}


def records_of(staged, parts):
    """*staged*'s records of *parts*: their keys (empty ones left out), and the names of
    their slots' files."""
    out = {}
    for p in parts:
        for k in part_keys(p):
            v = (staged or {}).get(k)
            if v not in (None, {}, [], ""):
                out[k] = v
    names = _names_of((staged or {}).get("replacement_names"), parts)
    if names:
        out["replacement_names"] = names
    return out


# ---------------------------------------------------------------------------------------------
# this project's record of its team
# ---------------------------------------------------------------------------------------------
def load_state(project):
    try:
        with open(os.path.join(project, STATE_NAME), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(project, st):
    write_json_atomic(os.path.join(project, STATE_NAME), st, indent=1, sort_keys=True)


def this_pc():
    """Who this PC is, so a member's folder taken by another PC is not written over."""
    try:
        user = getpass.getuser()
    except Exception:                                   # noqa: BLE001
        user = ""
    return "%s@%s" % (user, platform.node())


def default_name():
    try:
        return getpass.getuser() or "Me"
    except Exception:                                   # noqa: BLE001
        return "Me"


def folder_name(name):
    """*name* as a folder name (what a member is known by in the team folder)."""
    n = _SAFE_NAME.sub(" ", str(name or "")).strip().strip(".")
    return re.sub(r"\s+", " ", n)[:40]


def _member_dir(team, name):
    return os.path.join(team, folder_name(name))


def _read_any(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def read_member(team, name):
    m = _read_json(os.path.join(_member_dir(team, name), MEMBER_NAME))
    return m if m and m.get("format") == MEMBER_FORMAT else None


def members(team):
    """``{name: member card}`` of everyone in *team* (a subfolder with a card)."""
    out = {}
    try:
        names = sorted(os.listdir(team), key=str.lower)
    except OSError:
        return out
    for n in names:
        m = read_member(team, n)
        if m is not None:
            out[n] = m
    return out


def owners(team, cards=None):
    """``{part: member}``: each part's owner, the member who took it last."""
    best = {}
    for name, m in (members(team) if cards is None else cards).items():
        for part, t in (m.get("claims") or {}).items():
            if part not in LABELS or not isinstance(t, (int, float)):
                continue
            cur = best.get(part)
            if cur is None or (t, name) > cur:
                best[part] = (t, name)
    return {p: n for p, (_t, n) in best.items()}


def _source_name(project):
    from .extract_source import read_extract_source
    try:
        return (read_extract_source(project) or {}).get("input_name") or ""
    except Exception:                                   # noqa: BLE001
        return ""


def _write_member(team, me, card):
    d = _member_dir(team, me)
    os.makedirs(d, exist_ok=True)
    write_json_atomic(os.path.join(d, MEMBER_NAME), card, indent=1, sort_keys=True)


def join(project, team, name):
    """Point *project* at the team folder *team* as member *name* (its folder is made).
    Returns the warnings to show (another card's project in the team).  Raises
    :class:`TeamError` for a name another PC already uses there."""
    team = os.path.normpath(os.path.abspath(team or ""))
    me = folder_name(name)
    if not me:
        raise TeamError("Type the name the others will see you by.")
    if not os.path.isdir(team):
        try:
            os.makedirs(team)
        except OSError as e:
            raise TeamError("Couldn't make the team folder:\n%s\n\n%s" % (team, e))
    if os.path.normcase(project.rstrip("\\/")) == os.path.normcase(team) or \
            os.path.normcase(team).startswith(os.path.normcase(project.rstrip("\\/")) + os.sep):
        raise TeamError("The team folder has to be outside the project folder.")
    pc = this_pc()
    card = read_member(team, me)
    if card is not None and card.get("pc") not in (None, pc):
        raise TeamError("\"%s\" is already in this team from another PC (%s). Pick another "
                        "name." % (me, card.get("pc")))
    src = _source_name(project)
    if card is None:
        card = {"format": MEMBER_FORMAT, "version": VERSION, "name": me, "claims": {}}
    card.update(pc=pc, source_name=src, joined=card.get("joined") or time.time())
    _write_member(team, me, card)
    st = load_state(project)
    if st.get("team") != team or st.get("me") != me:
        st = {"team": team, "me": me, "got": {}, "fp": {}}
    save_state(project, st)
    warn = []
    for n, m in members(team).items():
        other = m.get("source_name") or ""
        if n != me and src and other and other != src:
            warn.append("%s's project was extracted from %s, this one from %s. Parts "
                        "only carry between projects of the same card." % (n, other, src))
    return warn


def leave(project):
    """Forget the team (nothing in the team folder is touched)."""
    try:
        os.remove(os.path.join(project, STATE_NAME))
    except OSError:
        pass


def _team_of(project):
    st = load_state(project)
    team, me = st.get("team"), st.get("me")
    if not team or not me:
        raise TeamError("This project is not in a team yet.")
    if not os.path.isdir(team):
        raise TeamError("The team folder is not there:\n%s\n\nIs the drive or the sync "
                        "service on?" % team)
    return st, team, me


def claim(project, parts):
    """Take *parts*: they are yours from now on (whoever had them before sees it on their
    next look).  Returns the parts taken."""
    st, team, me = _team_of(project)
    card = read_member(team, me) or {"format": MEMBER_FORMAT, "version": VERSION,
                                     "name": me, "pc": this_pc()}
    claims = dict(card.get("claims") or {})
    now = time.time()
    got = [p for p in parts if p in LABELS]
    for p in got:
        claims[p] = now
    card["claims"] = claims
    _write_member(team, me, card)
    return got


def release(project, parts):
    """Let *parts* go: nobody owns them until someone takes them."""
    st, team, me = _team_of(project)
    card = read_member(team, me)
    if card is None:
        return []
    claims = dict(card.get("claims") or {})
    gone = [p for p in parts if claims.pop(p, None) is not None]
    card["claims"] = claims
    _write_member(team, me, card)
    return gone


# ---------------------------------------------------------------------------------------------
# what a part holds here
# ---------------------------------------------------------------------------------------------
def _scene_edits_path(project):
    return os.path.join(project, "images", "scene_textures", "scene_edits.json")


def _stat(path):
    try:
        s = os.stat(path)
        return [s.st_size, s.st_mtime_ns]
    except OSError:
        return None


def _digest(path, limit=4 << 20):
    """A file's bytes in short (a big one by its size and time): what it holds, not when
    a tab last wrote it."""
    st = _stat(path)
    if st is None or st[0] > limit:
        return st
    try:
        with open(path, "rb") as f:
            return [st[0], hashlib.sha1(f.read()).hexdigest()]
    except OSError:
        return None


def _mode_files(project):
    root = os.path.join(project, "modes")
    out = []
    for d, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            out.append([os.path.relpath(p, root).replace("\\", "/"), _digest(p)])
    return sorted(out)


def _text_edits(project):
    from .replacement_export import text_edits
    try:
        return text_edits(project)
    except Exception:                                   # noqa: BLE001
        return [], {}


def part_content(project, part, staged, changed):
    """What *part* holds in *project*, as plain data: its records with each file's size
    and time, and the edits kept outside the sidecar.  Empty: the part is as extracted."""
    from .replacement_export import recorded_files
    out = {}
    recs = records_of(staged, [part])
    if recs:
        out["records"] = recs
        out["files"] = {p: _stat(p) for p in sorted(recorded_files(recs))}
    rels = sorted(r for r in changed or () if part_of_rel(r) == part)
    if rels:
        out["changed"] = {r: _stat(os.path.join(project, *r.split("/"))) for r in rels}
    if part == "scenes":
        edits = _read_any(_scene_edits_path(project))
        if edits:
            out["scenes"] = edits
    elif part == "modes":
        files = _mode_files(project)
        if files:
            out["modes"] = files
    elif part == "text":
        edits, colours = _text_edits(project)
        if edits or colours:
            out["text"] = [edits, colours]
    return out


def fingerprint(content):
    return hashlib.sha1(json.dumps(content, sort_keys=True, default=str)
                        .encode("utf-8")).hexdigest()


def _changed(project, cancel=None):
    from .replacement_export import changed_files
    try:
        return changed_files(project, cancel=cancel)
    except Exception:                                   # noqa: BLE001
        return []


# ---------------------------------------------------------------------------------------------
# where everyone is
# ---------------------------------------------------------------------------------------------
def _complete(team, name, card):
    """Has *name*'s last share fully arrived on this PC?  ``(record or None, files still
    on the way)``."""
    shared = card.get("shared") or {}
    rec = _read_json(os.path.join(_member_dir(team, name), SHARE_NAME))
    if not shared.get("stamp"):
        return None, 0
    if not rec or rec.get("format") != SHARE_FORMAT or rec.get("stamp") != shared["stamp"]:
        return None, -1
    base = _member_dir(team, name)
    missing = 0
    for rel, size in (rec.get("files") or {}).items():
        try:
            if os.path.getsize(os.path.join(base, *rel.split("/"))) != size:
                missing += 1
        except OSError:
            missing += 1
    return (rec if not missing else None), missing


def news(project):
    """The parts another member shared since this project last took them: ``[(part,
    owner, stamp)]``.  Cheap (the members' cards only): the app asks every so often."""
    st = load_state(project)
    team, me = st.get("team"), st.get("me")
    if not team or not me or not os.path.isdir(team):
        return []
    cards = members(team)
    own = owners(team, cards)
    got = st.get("got") or {}
    out = []
    for part in KEYS:
        who = own.get(part)
        if not who or who == me:
            continue
        shared = (cards.get(who) or {}).get("shared") or {}
        if part not in (shared.get("parts") or ()):
            continue
        stamp = shared.get("stamp") or 0
        had = got.get(part) or {}
        if had.get("from") != who or (had.get("stamp") or 0) < stamp:
            out.append((part, who, stamp))
    return out


def when(stamp):
    """A stamp in words for the window: today's time, else the date."""
    if not stamp:
        return ""
    t = time.localtime(stamp)
    if time.strftime("%Y-%m-%d", t) == time.strftime("%Y-%m-%d"):
        return time.strftime("%H:%M", t)
    return time.strftime("%d %b %H:%M", t)


def status(project, cancel=None):
    """Everything the Team window shows.  Reads the project's parts (the changed files
    through the hash cache), so it runs off the UI loop."""
    st = load_state(project)
    team, me = st.get("team") or "", st.get("me") or ""
    out = {"team": team, "me": me, "joined": bool(team and me), "ok": False,
           "members": [], "parts": [], "news": 0, "to_share": 0, "warnings": []}
    if not out["joined"]:
        return out
    if not os.path.isdir(team):
        out["warnings"].append("The team folder is not there: %s. Is the drive or the sync "
                               "service on?" % team)
        return out
    out["ok"] = True
    cards = members(team)
    own = owners(team, cards)
    src = _source_name(project)
    staged = staged_changes.load(project)
    changed = _changed(project, cancel)
    got, fps = st.get("got") or {}, st.get("fp") or {}
    fresh = {p for p, _w, _s in news(project)}
    for name, card in cards.items():
        shared = card.get("shared") or {}
        rec, missing = _complete(team, name, card) if name != me else (None, 0)
        row = {"name": name, "me": name == me,
               "parts": [LABELS[p] for p in KEYS if own.get(p) == name],
               "shared": when(shared.get("stamp")), "arriving": missing != 0 and name != me}
        out["members"].append(row)
        other = card.get("source_name") or ""
        if name != me and src and other and other != src:
            out["warnings"].append("%s's project is of another card (%s); this one is %s."
                                   % (name, other, src))
    mine_shared = (cards.get(me) or {}).get("shared") or {}
    for part in KEYS:
        who = own.get(part) or ""
        content = part_content(project, part, staged, changed)
        fp = fingerprint(content)
        row = {"key": part, "label": LABELS[part], "owner": who, "mine": who == me,
               "news": False, "changed_here": False, "has": bool(content)}
        if who == me:
            if part not in (mine_shared.get("parts") or ()):
                row["state"] = "Yours, not shared yet" if content else "Yours, nothing in it yet"
                row["to_share"] = bool(content)
            elif fps.get(part) != fp:
                row["state"] = "Yours, changed since you shared it"
                row["to_share"] = True
            else:
                row["state"] = "Yours, shared %s" % when(mine_shared.get("stamp"))
            out["to_share"] += bool(row.get("to_share"))
        elif who:
            had = got.get(part) or {}
            row["changed_here"] = bool(content) and (
                fps.get(part) != fp if had.get("from") else True)
            shared = (cards.get(who) or {}).get("shared") or {}
            if part in fresh:
                row["news"] = True
                row["state"] = "New from %s (%s)" % (who, when(shared.get("stamp")))
                out["news"] += 1
            elif had.get("from") == who:
                row["state"] = "%s's, up to date" % who
            else:
                row["state"] = "%s's, nothing shared yet" % who
            if row["changed_here"]:
                row["state"] += "; changed on this PC too"
        else:
            row["state"] = "Nobody's: changes stay on each PC" if content else "Nobody's"
        out["parts"].append(row)
    return out


# ---------------------------------------------------------------------------------------------
# share
# ---------------------------------------------------------------------------------------------
def _rel(path, base):
    return os.path.relpath(path, base).replace("\\", "/")


def _files_under(base, skip=(MEMBER_NAME, SHARE_NAME)):
    out = {}
    for d, _dirs, files in os.walk(base):
        for n in files:
            if n.endswith(".part"):
                continue
            p = os.path.join(d, n)
            rel = _rel(p, base)
            if rel in skip:
                continue
            try:
                out[rel] = os.path.getsize(p)
            except OSError:
                pass
    return out


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def share(project, game="", progress=None, cancel=None):
    """Write the parts this member owns into their folder of the team.  Returns ``{"parts",
    "files", "copied", "bytes", "gone", "cancelled"}`` (*gone*: files the project names
    that are not on this PC, left out)."""
    from . import replacement_export as rx
    st, team, me = _team_of(project)
    cards = members(team)
    own = owners(team, cards)
    card = cards.get(me) or {"format": MEMBER_FORMAT, "version": VERSION, "name": me,
                             "pc": this_pc(), "claims": {}}
    parts = [p for p in KEYS if own.get(p) == me]
    if not parts:
        raise TeamError("You own no part of the project yet. Take the parts you work on "
                        "first, so the others know whose they are.")
    dest = _member_dir(team, me)
    os.makedirs(dest, exist_ok=True)
    staged = staged_changes.load(project)
    recs = records_of(staged, parts)
    plan = rx.plan(recs, dest, project)
    out = rx.export(recs, plan, progress=progress, cancel=cancel)
    result = {"parts": parts, "files": len(out["mapping"]), "copied": out["copied"],
              "bytes": out["bytes"], "gone": list(plan["gone"]), "cancelled": False}
    if out["cancelled"]:
        result["cancelled"] = True
        return result
    rel = {src: _rel(to, dest) for src, to in out["mapping"].items()}
    carried, _n = rx.repoint(recs, rel)
    keep = set(rel.values())
    rec = {"format": SHARE_FORMAT, "version": VERSION, "member": me, "game": game or "",
           "source_name": _source_name(project), "parts": parts, "records": carried}
    if progress is not None:
        progress(0, 0, "Scenes edits, modes and text")
    if "scenes" in parts and rx.export_scenes(project, dest):
        rec["scenes"] = rx.SCENES_NAME
        keep.add(rx.SCENES_NAME)
    if "modes" in parts and rx.export_modes(project, dest):
        rec["modes"] = rx.MODES_NAME
        keep.add(rx.MODES_NAME)
    if "text" in parts:
        edits, colours = _text_edits(project)
        rec["text"], rec["text_colors"] = edits, colours
    changed = [r for r in _changed(project, cancel) if part_of_rel(r) in parts]
    for i, r in enumerate(changed):
        if cancel is not None and cancel():
            result["cancelled"] = True
            return result
        src = os.path.join(project, *r.split("/"))
        to = os.path.join(dest, rx.CHANGED_DIR, *r.split("/"))
        if not (os.path.isfile(to) and rx._same_file(to, src)):
            rx._copy(src, to, None, 0, 0, None)
        keep.add(rx.CHANGED_DIR + "/" + r)
        if progress is not None:
            progress(i + 1, len(changed), r)
    rec["changed"] = changed
    # what an earlier share left that this one does not carry
    for r in list(_files_under(dest)):
        if r not in keep:
            _remove(os.path.join(dest, *r.split("/")))
    for d, dirs, files in sorted(os.walk(dest), reverse=True):
        if d != dest and not dirs and not files:
            try:
                os.rmdir(d)
            except OSError:
                pass
    stamp = time.time()
    rec["stamp"] = stamp
    rec["files"] = _files_under(dest)
    write_json_atomic(os.path.join(dest, SHARE_NAME), rec, indent=1, sort_keys=True)
    # the card last: once it names the stamp, everything it names is in place
    claims = {p: t for p, t in (card.get("claims") or {}).items() if own.get(p) == me}
    card.update(claims=claims, shared={"stamp": stamp, "parts": parts},
                source_name=rec["source_name"], game=game or card.get("game") or "")
    _write_member(team, me, card)
    fps = dict(st.get("fp") or {})
    changed_all = _changed(project)
    staged = staged_changes.load(project)
    for p in parts:
        fps[p] = fingerprint(part_content(project, p, staged, changed_all))
    st["fp"] = fps
    save_state(project, st)
    return result


# ---------------------------------------------------------------------------------------------
# receive
# ---------------------------------------------------------------------------------------------
def _resolve(records, base, local):
    """*records* with each file (named relative to the member's folder *base*) copied to
    *local* and named by its copy there.  Returns ``(records, [files not there])``."""
    from . import replacement_export as rx
    missing = []

    def fix(s, section):
        if not isinstance(s, str) or rx._ABS_RE.match(s) or rx.kind_of(s, section) is None \
                or "/" not in s or s.split("/", 1)[0] not in rx.KIND_DIRS.values():
            return None
        parts = s.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return None
        src = os.path.join(base, *parts)
        to = os.path.join(local, *parts)
        if not os.path.isfile(src):
            missing.append(s)
            return to
        if not (os.path.isfile(to) and rx._same_file(src, to)):
            rx._copy(src, to, None, 0, 0, None)
        return to

    return {k: rx._walk(v, k, fix) for k, v in records.items()}, missing


def _referenced(project, staged):
    """Every file under the project's :data:`TEAM_FILES_DIR` *staged* names."""
    from . import replacement_export as rx
    root = os.path.normcase(os.path.abspath(os.path.join(project, TEAM_FILES_DIR)))
    seen = set()

    def see(s, _section):
        if isinstance(s, str) and rx._ABS_RE.match(s):
            p = os.path.normcase(os.path.abspath(s))
            if p.startswith(root + os.sep):
                seen.add(p)
        return None

    for k, v in (staged or {}).items():
        rx._walk(v, k, see)
    return seen


def _prune_team_files(project, staged):
    root = os.path.join(project, TEAM_FILES_DIR)
    if not os.path.isdir(root):
        return
    keep = _referenced(project, staged)
    for d, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            if os.path.normcase(os.path.abspath(p)) not in keep:
                _remove(p)
    for d, dirs, files in sorted(os.walk(root), reverse=True):
        if not dirs and not files:
            try:
                os.rmdir(d)
            except OSError:
                pass


def _import_text(project, edits):
    """The Text tab's edits on this card's lines (when the app has no Text tab open to
    do it).  Returns ``(put on, found no line)``."""
    from . import tab_settings, text_manifest
    from ..plugins.stern import scene_share
    rows = text_manifest.load(project)
    pairs, missing = tab_settings.match_text({"edits": edits}, rows)
    scene_share.import_text(project, rows, pairs)
    return len(pairs), len(missing)


def receive(project, parts=None, progress=None, import_text=None):
    """Take the parts other members own and have shared into *project*: each is put back
    as extracted, then the owner's records, files and edits go on.  *parts*: which (all
    with news when ``None``).  *import_text*: ``fn(project, edits)`` for the Text tab's
    edits (the app's own, so an open Text tab stays in step).  Returns ``{"got": [(part,
    owner)], "waiting": [(owner, files on the way)], "lines": [str], "notes": [str]}``."""
    from . import replacement_export as rx
    st, team, me = _team_of(project)
    cards = members(team)
    own = owners(team, cards)
    if parts is None:
        parts = [p for p, _w, _s in news(project)]
    by_owner = {}
    for p in parts:
        who = own.get(p)
        if who and who != me:
            by_owner.setdefault(who, []).append(p)
    result = {"got": [], "waiting": [], "lines": [], "notes": []}
    ready = {}
    for who, ps in by_owner.items():
        rec, missing = _complete(team, who, cards[who])
        if rec is None:
            if missing:
                result["waiting"].append((who, missing))
            continue
        ps = [p for p in ps if p in (rec.get("parts") or ())]
        if ps:
            ready[who] = (rec, ps)
    if not ready:
        return result
    taking = [p for _who, (_r, ps) in ready.items() for p in ps]
    # 1. the parts back as extracted (Reset's own steps)
    # one kind at a time: every kind at once is Reset's "everything", which would also
    # take the parts this member owns
    kinds = [p for p in taking if p in project_reset.KEYS]
    said = []
    for k in kinds:
        said += project_reset.drop_records(project, [k])
    project_reset.restore_snapshots(project, [k for k in kinds if k not in ("modes", "text")])
    result["notes"] += ["Put back as extracted first: " + s for s in said]
    # 2. the owners' records, their files copied into the project
    data = staged_changes.load(project)
    for p in taking:
        for k in part_keys(p):
            data.pop(k, None)
    names = dict(data.get("replacement_names") or {})
    names = {r: n for r, n in names.items() if part_of_rel(r) not in taking}
    for who, (rec, ps) in ready.items():
        base = _member_dir(team, who)
        local = os.path.join(project, TEAM_FILES_DIR, folder_name(who))
        recs = {}
        for k, v in (rec.get("records") or {}).items():
            if k == "replacement_names":
                names.update(_names_of(v, ps))
            elif any(k in part_keys(p) for p in ps):
                recs[k] = v
        if progress is not None:
            progress(0, 0, "%s's files" % who)
        recs, missing = _resolve(recs, base, local)
        data.update(recs)
        if missing:
            result["notes"].append("%d of %s's files were not in the team folder."
                                   % (len(missing), who))
    if names:
        data["replacement_names"] = names
    else:
        data.pop("replacement_names", None)
    staged_changes.save(project, data)
    # 3. the edits each part's own tab saves and loads
    for who, (rec, ps) in ready.items():
        base = _member_dir(team, who)
        bits = []
        if "scenes" in ps and rec.get("scenes"):
            got = rx.import_scenes(project, os.path.join(base, rx.SCENES_NAME))
            bits.append("the Scenes edits of %d scene(s)" % got[0])
            if got[1]:
                result["notes"].append("%d of %s's scenes are not on this card."
                                       % (len(got[1]), who))
        if "modes" in ps and rec.get("modes"):
            report = rx.import_modes(project, os.path.join(base, rx.MODES_NAME))
            if report is not None:
                n = len([m for m in report.modes if m.new_slug])
                bits.append("%d mode(s)" % n)
        if "text" in ps:
            if rec.get("text"):
                n, gone = (import_text or _import_text)(project, rec["text"])[:2]
                bits.append("%d text edit(s)" % n)
                if gone:
                    result["notes"].append("%d of %s's text edits found no such line here."
                                           % (gone, who))
            if rec.get("text_colors"):
                rx.import_text_colors(project, rec["text_colors"])
        rels = [r for r in rec.get("changed") or () if part_of_rel(r) in ps]
        if rels:
            done, gone = rx.import_changed(project, os.path.join(base, SHARE_NAME), rels)
            if done:
                bits.append("%d changed file(s) of the extract" % len(done))
        files = rx.counts_of(records_of(data, ps))
        if any(files.values()):
            bits.insert(0, rx.words(files))
        line = "Took %s from %s" % (", ".join(LABELS[p] for p in ps), who)
        if bits:
            line += ": " + ", ".join(bits)
        result["lines"].append(line + ".")
        for p in ps:
            result["got"].append((p, who))
    _prune_team_files(project, staged_changes.load(project))
    # 4. what this project now holds of them, to see a change made here later
    st = load_state(project)
    got, fps = dict(st.get("got") or {}), dict(st.get("fp") or {})
    staged = staged_changes.load(project)
    changed = _changed(project)
    for who, (rec, ps) in ready.items():
        for p in ps:
            got[p] = {"from": who, "stamp": rec.get("stamp")}
            fps[p] = fingerprint(part_content(project, p, staged, changed))
    st.update(got=got, fp=fps)
    save_state(project, st)
    return result
