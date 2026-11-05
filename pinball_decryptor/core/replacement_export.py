"""Export a project's replacement files to one folder, and put them back on a
fresh extract (PAD-1015).

A project records the PATH of every file it was given (:mod:`.staged_changes`),
wherever on the PC each one was picked from, so a retheme of a few hundred
clips ends up spread over every folder its maker ever worked in.  "I would
like to be able to export all of my replacement videos and random variant
videos to a single folder for cleanliness", the same for pictures and sounds,
and "needs to be able to rebuild my project folder from a fresh stock extract
using these new folders": the modder who asked.

:func:`plan` / :func:`export` copy every file the project records into one
folder, a subfolder per kind (:data:`KIND_DIRS`), and leave beside them
:data:`RECORD_NAME`, the project's replacement records (every slot's file, the
random clips, the music modes, the loudness and loop settings, the per-file
colour profiles...) with each file named relative to that folder.
:func:`repoint` points the project itself at the copies, so it builds from
the export folder from then on.  :func:`read_record` / :func:`import_record`
take that record into another project (a fresh stock extract), the files
found wherever the folder sits by then.

Every file is found by walking the whole sidecar (:func:`recorded_files`)
rather than a list of known sections, so a section added later (as music
modes, attract items and their shots all were) is exported with no change
here.  A file is a string that is an absolute path with a picture, video or
sound extension; slot keys and every other value are relative or not a file.
"""

import json
import os
import re
import shutil
import time

from . import staged_changes

#: the subfolder each kind of file is copied into, the names the modder asked for
KIND_DIRS = {"video": "Video", "audio": "Audio", "image": "Images"}
KINDS = ("video", "audio", "image")

#: the record left in the export folder, read back by :func:`read_record`
RECORD_NAME = "replacements.json"
RECORD_FORMAT = "pad-replacements"
RECORD_VERSION = 1

#: which kind a file under each sidecar section is (a section not here goes by
#: the file's extension: attract items, a later section)
_SECTION_KIND = {"video": "video", "video_variants": "video",
                 "audio": "audio", "sound_modes": "audio", "image": "image"}

_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]|/)")

#: the project's own working folders: nothing in them is a file of the user's
_PROJECT_INTERNAL = (".orig", ".write_cache", ".hydrate", ".uncorrected")

_CHUNK = 4 << 20


def _exts():
    from .audio_slots import AUDIO_EXTS
    from .image import REPLACEMENT_EXTS as IMAGE_IN
    from .video import REPLACEMENT_EXTS as VIDEO_IN
    return {"audio": tuple(AUDIO_EXTS) + (".mp3", ".flac", ".aif", ".aiff", ".m4a"),
            "image": tuple(IMAGE_IN) + (".dds",), "video": tuple(VIDEO_IN)}


def kind_of(path, section=None):
    """``"video"``, ``"audio"``, ``"image"`` for a recorded file, else ``None``.
    The section it is recorded under decides first (a ``.gif`` on the Video tab
    is a clip), then the extension."""
    ext = os.path.splitext(path or "")[1].lower()
    exts = _exts()
    k = _SECTION_KIND.get(section)
    if k and ext in exts[k]:
        return k
    for k in ("audio", "image", "video"):
        if ext in exts[k]:
            return k
    return None


def _looks_like_file(s, section):
    return (isinstance(s, str) and len(s) > 3 and _ABS_RE.match(s) is not None
            and kind_of(s, section) is not None)


def _walk(node, section, fn):
    """Call ``fn(string, section)`` for every string VALUE under *node*;
    ``fn``'s answer (not ``None``) replaces it.  Returns the new node."""
    if isinstance(node, dict):
        return {k: _walk(v, section, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, section, fn) for v in node]
    if isinstance(node, str):
        got = fn(node, section)
        return node if got is None else got
    return node


def recorded_files(staged):
    """``{path: {"kind", "uses"}}`` for every user file *staged* records, in
    the order first met (``uses``: how many times it is named)."""
    out = {}

    def see(s, section):
        if _looks_like_file(s, section):
            e = out.setdefault(s, {"kind": kind_of(s, section), "uses": 0})
            e["uses"] += 1
        return None

    for key, val in (staged or {}).items():
        _walk(val, key, see)
    return out


def _inside(path, folder):
    try:
        a = os.path.normcase(os.path.abspath(path))
        b = os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([a, b]) == b
    except ValueError:                       # another drive
        return False


def _internal(path, project):
    if not project or not _inside(path, project):
        return False
    rel = os.path.relpath(path, project).replace("\\", "/")
    return rel.split("/", 1)[0].lower() in _PROJECT_INTERNAL


def _same_file(a, b):
    """Are *a* and *b* the same bytes?  Size first, then mtime (a copy we made
    keeps it), then the bytes themselves."""
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    if sa.st_size != sb.st_size:
        return False
    if sa.st_mtime_ns == sb.st_mtime_ns:
        return True
    with open(a, "rb") as f, open(b, "rb") as g:
        while True:
            x, y = f.read(_CHUNK), g.read(_CHUNK)
            if x != y:
                return False
            if not x:
                return True


def plan(staged, dest, project=None, isfile=os.path.isfile):
    """Where each recorded file goes in *dest*: ``{"dest", "files": [{"src",
    "kind", "to", "size", "uses", "state"}], "gone": [path], "counts": {kind:
    n}, "bytes": n}``.  ``state`` is ``"copy"``, ``"there"`` (already in its
    folder of *dest*, left as it is) or ``"same"`` (a copy of the same bytes is
    already there, a re-export).  Two different files of one name get "name
    (2).ext"; one file named by many slots is one copy.  Nothing is written."""
    files, gone, taken = [], [], {}
    counts = {k: 0 for k in KINDS}
    total = 0
    for src, e in recorded_files(staged).items():
        if _internal(src, project):
            continue
        try:
            present = isfile(src)
        except OSError:
            present = False
        if not present:
            gone.append(src)
            continue
        kind = e["kind"]
        sub = os.path.join(dest, KIND_DIRS[kind])
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        if _inside(src, sub):
            files.append({"src": src, "kind": kind, "to": src, "size": size,
                          "uses": e["uses"], "state": "there"})
            taken[os.path.normcase(os.path.abspath(src))] = src
            counts[kind] += 1
            continue
        name = os.path.basename(src) or "file"
        stem, ext = os.path.splitext(name)
        k = 2
        while True:
            to = os.path.join(sub, name)
            key = os.path.normcase(os.path.abspath(to))
            if key in taken:
                if _same_file(taken[key], src):
                    state = "same"
                    break
            elif not os.path.exists(to):
                state = "copy"
                break
            elif _same_file(to, src):
                state = "same"
                break
            name = "%s (%d)%s" % (stem, k, ext)
            k += 1
        taken[key] = src
        files.append({"src": src, "kind": kind, "to": to, "size": size,
                      "uses": e["uses"], "state": state})
        counts[kind] += 1
        if state == "copy":
            total += size
    return {"dest": dest, "files": files, "gone": gone, "counts": counts,
            "bytes": total}


def _copy(src, to, progress, done_bytes, total, cancel):
    """Copy *src* to *to* through a ``.part`` file (a stopped export leaves
    no half file under the real name), keeping its times."""
    os.makedirs(os.path.dirname(to), exist_ok=True)
    part = to + ".part"
    try:
        with open(src, "rb") as f, open(part, "wb") as g:
            while True:
                if cancel is not None and cancel():
                    raise _Cancelled()
                buf = f.read(_CHUNK)
                if not buf:
                    break
                g.write(buf)
                done_bytes += len(buf)
                if progress is not None:
                    progress(done_bytes, total, os.path.basename(to))
        shutil.copystat(src, part)
        os.replace(part, to)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return done_bytes


class _Cancelled(Exception):
    pass


def export(staged, result, progress=None, cancel=None):
    """Copy the files of a :func:`plan` *result*.  Returns ``{"mapping": {src:
    to}, "copied", "reused", "bytes", "cancelled"}``; the mapping names every
    file that is in the export folder now (copied, or already there)."""
    mapping, copied, reused, done = {}, 0, 0, 0
    total = result.get("bytes") or 0
    cancelled = False
    for f in result["files"]:
        if f["state"] == "copy":
            try:
                done = _copy(f["src"], f["to"], progress, done, total, cancel)
            except _Cancelled:
                cancelled = True
                break
            copied += 1
        else:
            reused += 1
        mapping[f["src"]] = f["to"]
    return {"mapping": mapping, "copied": copied, "reused": reused,
            "bytes": done, "cancelled": cancelled}


def repoint(staged, mapping):
    """*staged* (a copy) with every file in *mapping* named by its new path,
    in every section.  Returns ``(new staged, references changed)``."""
    n = [0]

    def swap(s, _section):
        new = mapping.get(s)
        if new is not None and new != s:
            n[0] += 1
            return new
        return None

    data = {k: _walk(v, k, swap) for k, v in (staged or {}).items()}
    return data, n[0]


# ---------------------------------------------------------------------------------------------
# the record beside the files
# ---------------------------------------------------------------------------------------------
def record_keys():
    """The sidecar sections a record carries: everything the project's
    replaced pictures, videos and sounds are (each slot's file and its
    settings, the random clips, the music modes, the attract items, the color
    profiles of those files), nothing about the card it was made from."""
    from . import project_reset
    keys = []
    for kind in ("images", "videos", "sounds"):
        keys += [k for k in project_reset._SIDECAR[kind] if k != "own_clips"]
    keys += ["attract_items", "replacement_names"]
    keys += list(project_reset._colour_keys())
    return tuple(dict.fromkeys(keys))


def _rel(path, dest):
    return os.path.relpath(path, dest).replace("\\", "/")


def make_record(staged, mapping, dest, game=""):
    """The record of *staged*'s replacements with every exported file (in
    *mapping*) named relative to *dest*; a file not exported (not on this PC)
    keeps its full path, for a later Relink to find."""
    rel = {src: _rel(to, dest) for src, to in mapping.items()}
    carried = {k: staged[k] for k in record_keys()
               if k in (staged or {}) and staged[k] not in (None, {}, [], "")}
    carried, _n = repoint(carried, rel)
    return {"format": RECORD_FORMAT, "version": RECORD_VERSION,
            "game": game or "", "made": time.strftime("%Y-%m-%d %H:%M"),
            "files": len(mapping), "records": carried}


def write_record(dest, record):
    from .atomic_file import write_text_atomic
    path = os.path.join(dest, RECORD_NAME)
    write_text_atomic(path, json.dumps(record, indent=1, sort_keys=True))
    return path


def read_record(path):
    """The record at *path* with every file resolved against the folder it is
    in now: ``(record, records with full paths, [files not there])``.
    Raises ``ValueError`` for a file that is not one."""
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    if not isinstance(rec, dict) or rec.get("format") != RECORD_FORMAT \
            or not isinstance(rec.get("records"), dict):
        raise ValueError("not a replacements file")
    base = os.path.dirname(os.path.abspath(path))
    missing = []

    def resolve(s, section):
        if not isinstance(s, str) or _ABS_RE.match(s) or kind_of(s, section) is None \
                or "/" not in s or s.split("/", 1)[0] not in KIND_DIRS.values():
            if _looks_like_file(s, section) and not os.path.isfile(s):
                missing.append(s)
            return None
        parts = s.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return None
        full = os.path.join(base, *parts)
        if not os.path.isfile(full):
            missing.append(full)
        return full

    records = {k: _walk(v, k, resolve) for k, v in rec["records"].items()
               if k in record_keys()}
    return rec, records, sorted(set(missing))


def counts_of(records):
    """``{kind: files}`` a record's records name, for the question and the log."""
    out = {k: 0 for k in KINDS}
    for e in recorded_files(records).values():
        out[e["kind"]] += 1
    return out


def import_record(staged, records):
    """*staged* (a project's, a copy) with *records* taken in: a map keyed by
    slot is merged slot by slot, the record's winning; anything else (the
    music modes, the attract items, a switch) is the record's.  Returns
    ``(new staged, slots given a file)``."""
    data = dict(staged or {})
    n = 0
    for key, val in records.items():
        if key in ("audio", "video", "image", "video_variants"):
            n += len(val) if isinstance(val, dict) else 0
        if isinstance(val, dict) and isinstance(data.get(key), dict) \
                and key not in (staged_changes.SOUND_MODES_KEY, "attract_items"):
            merged = dict(data[key])
            merged.update(val)
            data[key] = merged
        else:
            data[key] = val
    return data, n


def words(counts):
    """ "3 videos, 2 sounds and 1 picture" """
    names = {"video": ("video", "videos"), "audio": ("sound", "sounds"),
             "image": ("picture", "pictures")}
    bits = ["%d %s" % (counts[k], names[k][counts[k] != 1])
            for k in KINDS if counts.get(k)]
    if not bits:
        return "no files"
    return bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " and " + bits[-1]
