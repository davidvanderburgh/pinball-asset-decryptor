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

"This function should include any form of customization modification, and the
replacements.json file should be able to restore every customization" (the
same modder): :func:`export_rest` / :func:`import_rest` carry the rest of a
project beside the files, each in the form its own tab saves and loads it --
the Scenes edits (:data:`SCENES_NAME`), the modes (:data:`MODES_NAME`), the
Text tab's edits and text colors, the Defaults (the mod pack's records), and
every file of the extract changed in place (the Fonts window's letters, a file
a mod pack brought) under :data:`CHANGED_DIR`.
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
    from . import project_reset, tab_settings
    keys = []
    for kind in ("images", "videos", "sounds"):
        keys += [k for k in project_reset._SIDECAR[kind] if k != "own_clips"]
    # every section a Replace tab saves to its own settings file (PAD-300)
    for kind in ("images", "audio", "video"):
        keys += list(tab_settings.SECTIONS[kind])
    keys += ["attract_items", "replacement_names"]
    keys += list(project_reset._SIDECAR["scenes"])      # the score panel's colors
    keys += list(project_reset._colour_keys())
    return tuple(dict.fromkeys(keys))


#: the Scenes tab's edits, beside the record: the Scenes tab's own file of edits
#: (``scene_edit.export_edits``: the ops, the pictures they add, how each scene
#: looked), so "Can this function please include scene modifications?" loads
#: them the way Load edits from a file does
SCENES_NAME = "Scenes.zip"


def export_scenes(project, dest):
    """Write *project*'s Scenes edits to :data:`SCENES_NAME` in *dest*.
    Returns the number of scenes written (0: none, and no file)."""
    from ..plugins.stern import scene_edit
    if not scene_edit.count(project):
        return 0
    path = os.path.join(dest, SCENES_NAME)
    part = path + ".part"
    try:
        n = scene_edit.export_edits(project, part)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return n


def scenes_file(record_path, rec):
    """The Scenes file a record names, when it is beside it, else ``None``."""
    name = rec.get("scenes") if isinstance(rec, dict) else None
    return _beside(record_path, SCENES_NAME) if name == SCENES_NAME else None


def modes_file(record_path, rec):
    """The file of modes a record names, when it is beside it, else ``None``."""
    name = rec.get("modes") if isinstance(rec, dict) else None
    return _beside(record_path, MODES_NAME) if name == MODES_NAME else None


def scenes_count(path):
    from ..plugins.stern import scene_edit
    try:
        return len(scene_edit.read_share(path))
    except scene_edit.SceneEditError:
        return 0


def import_scenes(project, path):
    """Load the Scenes file at *path* into *project* as the Scenes tab's Load
    edits from a file does for a project with no edits of its own: each scene
    it has takes the file's edits (a scene of the project's own is replaced),
    the pictures they add are copied in, and the scenes that already show some
    of them (a card built with them) are noted.  Returns ``(scenes loaded,
    scenes of the file this card does not have)``."""
    from ..plugins.stern import scene_edit
    trees = scene_edit.trees_of(project)
    got, missing = scene_edit.import_edits(project, path, trees.keys())
    if got:
        states = scene_edit.read_states(path)
        find = scene_edit.card_finder(states.keys())
        scene_edit.note_shown(project, {c: trees[c] for c in got if c in trees},
                              states={c: states[find(c)] for c in got
                                      if find(c) in states})
    return len(got), missing


#: the modes made in the project (the Modes tab's own file of modes)
MODES_NAME = "Modes.zip"
#: the extract's files changed in place, each at its path in the extract
CHANGED_DIR = "Changed files"
#: written by the app from the Text tab's edits, which travel as edits
_TEXT_MANIFEST = "text/strings.tsv"


def export_modes(project, dest):
    """Write *project*'s modes to :data:`MODES_NAME` in *dest*; returns how many."""
    from ..plugins.stern import mode_project as MP
    part = os.path.join(dest, MODES_NAME + ".part")
    try:
        try:
            got = MP.export_modes(project, part)
        except MP.ModeProjectError:                     # no modes
            return 0
        os.replace(part, os.path.join(dest, MODES_NAME))
    finally:
        if os.path.exists(part):
            os.remove(part)
    return len(got)


def changed_files(project, staged=None, cancel=None):
    """The extract's files changed in place (rels): every baselined file whose
    bytes are not the extract's, except a slot given a file of the user's (its
    pick is in the record and rebuilds it), the Text tab's manifest (its edits
    travel as edits) and the working files a mod pack leaves out too."""
    from . import hashcache, modpack
    from .checksums import read_baseline_any
    baseline = read_baseline_any(project)
    if not baseline:
        return []
    staged = staged_changes.load(project) if staged is None else staged
    picked = set()
    for key in ("audio", "video", "image"):
        sec = staged.get(key)
        if isinstance(sec, dict):
            picked.update(rel for rel, src in sec.items() if src)
    cache = hashcache.load(project)
    out = []
    for rel, md5 in baseline.items():
        if cancel is not None and cancel():
            break
        rel = rel.replace("\\", "/")
        if rel in picked or rel == _TEXT_MANIFEST or not modpack._is_packable(rel):
            continue
        path = os.path.join(project, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        got = hashcache.md5_for(path, rel, cache)
        if got is not None and got != md5:
            out.append(rel)
    hashcache.save(project, cache)
    return sorted(out)


def text_edits(project):
    """``(the Text tab's edits [[scene, original, new], ...], its text colors
    {card: {text: [from, to]}})``."""
    from . import tab_settings, text_manifest
    try:
        edits = tab_settings.text_edits(text_manifest.load(project))
    except Exception:                                   # noqa: BLE001
        edits = []
    colours = {}
    try:
        from ..plugins.stern import text_colors as TC
        for card, by in TC.load(project).items():
            colours[card] = {t: [TC.to_hex(a), TC.to_hex(b)] for t, (a, b) in by.items()}
    except Exception:                                   # noqa: BLE001
        colours = {}
    return edits, colours


def defaults_of(project):
    """The Defaults tab's records and the rest a mod pack carries as values
    (:func:`modpack.project_extras`), the ones the record has already left out."""
    from . import modpack
    skip = {"sound_modes", "video_variants", "attract_items", "replacement_names",
            "audio_levels"}
    return {k: v for k, v in modpack.project_extras(project).items() if k not in skip}


def export_rest(project, dest, progress=None, cancel=None):
    """Everything else of *project* into *dest*: the Scenes edits, the modes,
    the changed files, and (returned, for the record) the text edits, text
    colors and defaults.  Returns the record's part ``{"scenes", "modes",
    "changed", "text", "text_colors", "defaults"}`` (empty ones left out)."""
    out = {}
    if progress is not None:
        progress(0, 0, "Scenes edits and modes")
    n = export_scenes(project, dest)
    if n:
        out["scenes"], out["scenes_n"] = SCENES_NAME, n
    n = export_modes(project, dest)
    if n:
        out["modes"], out["modes_n"] = MODES_NAME, n
    if progress is not None:
        progress(0, 0, "Finding the extract's files changed in place")
    changed = changed_files(project, cancel=cancel)
    done = []
    try:
        for i, rel in enumerate(changed):
            src = os.path.join(project, *rel.split("/"))
            to = os.path.join(dest, CHANGED_DIR, *rel.split("/"))
            if not (os.path.isfile(to) and _same_file(to, src)):
                _copy(src, to, None, 0, 0, cancel)
            done.append(rel)
            if progress is not None:
                progress(i + 1, len(changed), rel)
    except _Cancelled:
        out["cancelled"] = True
    if done:
        out["changed"] = done
    edits, colours = text_edits(project)
    if edits:
        out["text"] = edits
    if colours:
        out["text_colors"] = colours
    d = defaults_of(project)
    if d:
        out["defaults"] = d
    return out


def rest_summary(rec):
    """The parts of a record besides its files, in words, for the question and the log."""
    bits = []
    if rec.get("scenes"):
        n = rec.get("scenes_n") or 0
        bits.append("the Scenes edits%s" % (" of %d scene%s" % (n, "" if n == 1 else "s")
                                            if n else ""))
    if rec.get("text"):
        bits.append("%d text edit%s" % (len(rec["text"]), "" if len(rec["text"]) == 1 else "s"))
    if rec.get("text_colors"):
        n = sum(len(v) for v in rec["text_colors"].values())
        bits.append("%d text color%s" % (n, "" if n == 1 else "s"))
    if rec.get("modes"):
        n = rec.get("modes_n") or 0
        bits.append("%s mode%s" % (n or "the", "" if n == 1 else "s"))
    if rec.get("changed"):
        n = len(rec["changed"])
        bits.append("%d file%s of the extract changed in place (font letters, sounds or pictures changed on disk)"
                    % (n, "" if n == 1 else "s"))
    if rec.get("defaults"):
        bits.append("the Defaults")
    return bits


def _beside(record_path, name):
    path = os.path.join(os.path.dirname(os.path.abspath(record_path)), name)
    return path if os.path.isfile(path) else None


def import_changed(project, record_path, rels):
    """Put the record's changed files on *project*: each one this extract has
    goes over it, its extracted bytes backed up first (``.orig``, so Revert
    puts them back).  Returns ``(rels written, rels this extract has not)``."""
    from . import staged_originals
    from .checksums import read_baseline_any
    base = os.path.dirname(os.path.abspath(record_path))
    baseline = read_baseline_any(project)
    done, gone = [], []
    for rel in rels or ():
        parts = str(rel).replace("\\", "/").split("/")
        if any(p in ("", ".", "..") for p in parts) or ":" in rel:
            continue
        src = os.path.join(base, CHANGED_DIR, *parts)
        to = os.path.join(project, *parts)
        if not os.path.isfile(src) or not os.path.isfile(to):
            gone.append(rel)
            continue
        if _same_file(src, to):
            done.append(rel)
            continue
        md5 = baseline.get("/".join(parts))
        if md5 is not None:
            staged_originals.snapshot(project, "/".join(parts), md5)
        _copy(src, to, None, 0, 0, None)
        done.append(rel)
    return done, gone


def import_text_colors(project, colours):
    """Merge the record's text colors into *project*'s (the record's win). Returns how many."""
    from ..plugins.stern import text_colors as TC
    have = TC.load(project)
    n = 0
    for card, by in (colours or {}).items():
        if not isinstance(by, dict):
            continue
        for text, pair in by.items():
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            a, b = TC.parse_hex(pair[0]), TC.parse_hex(pair[1])
            if a is None or b is None:
                continue
            have.setdefault(card, {})[text] = (a, b)
            n += 1
    if n:
        TC.save(project, have)
    return n


def import_modes(project, path):
    """Load the record's file of modes: a mode of the same name here takes the
    file's, one already the same is left as it is.  Returns the :class:`CopyReport`
    or None."""
    from ..plugins.stern import mode_project as MP
    conflicts, same = MP.share_conflicts(path, project)
    return MP.import_modes(path, project, replace=[c["slug"] for c in conflicts], skip=same)


def _rel(path, dest):
    return os.path.relpath(path, dest).replace("\\", "/")


def make_record(staged, mapping, dest, game="", rest=None):
    """The record of *staged*'s replacements with every exported file (in
    *mapping*) named relative to *dest*; a file not exported (not on this PC)
    keeps its full path, for a later Relink to find.  *rest*: what
    :func:`export_rest` wrote beside it."""
    rel = {src: _rel(to, dest) for src, to in mapping.items()}
    carried = {k: staged[k] for k in record_keys()
               if k in (staged or {}) and staged[k] not in (None, {}, [], "")}
    carried, _n = repoint(carried, rel)
    out = {"format": RECORD_FORMAT, "version": RECORD_VERSION,
           "game": game or "", "made": time.strftime("%Y-%m-%d %H:%M"),
           "files": len(mapping), "records": carried}
    out.update(rest or {})
    return out


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
