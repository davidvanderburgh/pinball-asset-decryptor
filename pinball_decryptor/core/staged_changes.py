"""Persists the user's pending (un-written) Replace-Audio/Video/Image
assignments into the assets folder, so they survive quitting and re-opening
the app.

The Replace tabs hold each assignment in memory only — ``rel_path ->
replacement source file`` — and apply them at Write time; there is no manual
"stage" step.  Without this, quitting the app loses every assignment and the
user has to re-pick each replacement folder by folder.  This drops a small JSON
sidecar (:data:`SIDE_CAR`) at the root of the assets folder recording those
assignments (plus the per-slot audio Loop flags, the per-slot audio loudness
offsets under ``"audio_levels"``, and the trim toggles).

``"audio_levels"`` (``{rel path -> dB}``) is also read by the Stern write
pipeline itself (``engine._slot_gain_maps``) rather than passed to it, the same
way the video path reads its originals map back out of here.

The sidecar is keyed implicitly by the folder it lives in: each Replace tab only
restores it when it scans that same folder, and the assets folder's identity vs
its source image is already tracked separately by ``.extract_source.json``.
(Replace Text already persists via ``text/strings.tsv``, so it isn't included
here.)
"""

import json
import marshal
import os
import re
import threading
import time

from .atomic_file import write_text_atomic

# Sidecar written at the root of the assets folder.  Dotfile so the
# audio/video/image slot scanners (which skip dot-entries) ignore it — same
# rule the ``.extract_source.json`` / ``.checksums.md5`` sidecars rely on.
SIDE_CAR = ".staged_changes.json"

#: Extensions the extractor's own bookkeeping files carry — ``manifest.txt``,
#: ``radium_images.txt``, ``glyph_images.txt``, ``glyph_scope.txt`` and
#: ``images/scene_textures/scene_layout.json``.  NO replaceable slot ever has
#: one (audio slots are ``.wav``, video slots a movie container, image slots an
#: image format), so an assignment keyed on one can only have come from a byte
#: diff that mistook a manifest for an asset — which is exactly what Mod
#: Transfer's no-baseline compare used to do with ``scene_layout.json``
#: (PAD-107).  Also the skip list for walking an extract's asset folders (see
#: ``mod_transfer._walk_rels``): these files name content-hashed filenames and
#: per-version offsets, so they ALWAYS differ between two extracts.
NON_SLOT_EXTS = (".txt", ".json")


def _prune_non_slot_keys(data):
    """Drop assignment entries keyed on a :data:`NON_SLOT_EXTS` file, in place.

    Self-heal for a sidecar an affected version already wrote: the entry can
    never match a slot, so the Replace tab reported it as an unrestorable
    replacement on every single scan.  Pruning at load means the next save
    writes it out for good.
    """
    for kind in ("audio", "video", "image"):
        m = data.get(kind)
        if not isinstance(m, dict):
            continue
        for rel in [r for r in m if isinstance(r, str)
                    and r.lower().endswith(NON_SLOT_EXTS)]:
            del m[rel]
    return data


# -- the file as last read (PAD-464) ------------------------------------------
#
# DragonRR: "Color profiling is very slow again".  One slider move in the
# Colors bar read and parsed this file some 90 to 150 times (every switch,
# count and profile asks it again), ~5 ms each once a project's files carry
# profiles of their own: most of a second with the window waiting.  So each
# folder's file is parsed once and kept until it changes on disk.  A change
# is seen by its time and size, and where a write could have kept both (one
# made in the same clock tick as the one read) by its bytes too, the way git
# guards its index against "racy" writes.

class _Entry:
    """One folder's file as last read: its *stamp* (time, size), when it was
    read (*read_ns*), its bytes, the parsed *data*, the same data marshalled
    (a fresh copy for :func:`load` in a third of the time json takes), and
    what callers worked out from it (:func:`derived`)."""
    __slots__ = ("stamp", "read_ns", "raw", "data", "frozen", "derived")

    def __init__(self, stamp, read_ns, raw, data, frozen=None, derived=None):
        self.stamp, self.read_ns, self.raw, self.data = stamp, read_ns, raw, data
        self.frozen = marshal.dumps(data) if frozen is None else frozen
        self.derived = {} if derived is None else derived


#: ``{path: _Entry}``, the newest last
_CACHE = {}
_CACHE_LOCK = threading.Lock()
#: a file read within this long of its last change is checked byte for byte:
#: a later write in the same tick of the file system's clock (up to 2 s on
#: FAT) keeps the time and maybe the size
_RACY_NS = 2_000_000_000
_CACHE_MAX = 16


def _cache_path(assets_dir):
    return os.path.normcase(os.path.abspath(os.path.join(assets_dir,
                                                         SIDE_CAR)))


def _parsed(raw):
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}
    return _prune_non_slot_keys(data) if isinstance(data, dict) else {}


def _remember(path, entry):
    with _CACHE_LOCK:
        _CACHE.pop(path, None)
        _CACHE[path] = entry
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
    return entry


def _entry(assets_dir):
    """The cache entry of *assets_dir*'s file, read again only when it
    changed; ``None`` when there is no file to read."""
    path = _cache_path(assets_dir)
    try:
        st = os.stat(path)
    except OSError:
        with _CACHE_LOCK:
            _CACHE.pop(path, None)
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        hit = _CACHE.get(path)
    if hit is not None and hit.stamp == stamp \
            and hit.read_ns - st.st_mtime_ns > _RACY_NS:
        return hit
    now = time.time_ns()
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if hit is not None and hit.raw == raw:
        # the same bytes: the same data, and what was worked out from it
        return _remember(path, _Entry(stamp, now, raw, hit.data, hit.frozen,
                                      hit.derived))
    return _remember(path, _Entry(stamp, now, raw, _parsed(raw)))


def peek(assets_dir):
    """:func:`load`, shared and never to be changed: the caller only reads it
    (PAD-464: no copy is made, so a look-up costs next to nothing)."""
    if not assets_dir:
        return {}
    got = _entry(assets_dir)
    return got.data if got is not None else {}


def derived(assets_dir, name, build):
    """``build(data)`` (*data* :func:`peek`'s) for the file as it is now,
    worked out once and kept with it until the file changes (PAD-464: a
    project's colour profiles, parsed once rather than for every look-up).
    What it returns is shared too, never to be changed."""
    got = _entry(assets_dir) if assets_dir else None
    if got is None:
        return build({})
    try:
        return got.derived[name]
    except KeyError:
        pass
    out = got.derived[name] = build(got.data)
    return out


def load(assets_dir):
    """Return the staged-changes mapping recorded for *assets_dir*, or ``{}``.

    Best-effort: a missing/old/corrupt sidecar simply yields ``{}`` (the same
    empty state a folder that was never edited has), so callers never need to
    special-case "no file yet".  The caller's own copy, free to change (one
    only read is :func:`peek`'s).
    """
    if not assets_dir:
        return {}
    got = _entry(assets_dir)
    return marshal.loads(got.frozen) if got is not None else {}


def save(assets_dir, payload):
    """Write *payload* (a JSON-able dict) to ``assets_dir``/:data:`SIDE_CAR`.

    Best-effort: silently no-ops if the folder doesn't exist or isn't writable.
    """
    if not assets_dir or not os.path.isdir(assets_dir):
        return
    text = json.dumps(payload, indent=2)
    path = _cache_path(assets_dir)
    now = time.time_ns()
    try:
        write_text_atomic(os.path.join(assets_dir, SIDE_CAR), text)
        st = os.stat(path)
    except OSError:
        with _CACHE_LOCK:
            _CACHE.pop(path, None)
        return
    # the bytes on disk: text mode wrote each newline as the system's
    raw = text.replace("\n", os.linesep).encode("utf-8")
    _remember(path, _Entry((st.st_mtime_ns, st.st_size), now, raw,
                           _parsed(raw)))


def live_assignments(saved, slots_by_rel):
    """Filter a saved ``{rel: replacement_path}`` map down to the entries that
    are still applicable: the slot still exists in *slots_by_rel* and the
    replacement source file is still present on disk.

    Used when a tab restores from the sidecar so a since-deleted replacement
    file or a slot that vanished from a re-extract is dropped quietly rather
    than surfacing as a broken assignment.
    """
    out = {}
    for rel, path in (saved or {}).items():
        if (rel in slots_by_rel and isinstance(path, str)
                and os.path.isfile(path)):
            out[rel] = path
    return out


def dropped_assignments(saved, slots_by_rel):
    """The entries :func:`live_assignments` would drop, as ``[(rel, path,
    reason)]`` — the slot no longer exists in this folder, or the replacement
    source file isn't reachable.

    A disconnected NAS share / mapped drive looks exactly like a missing
    source file, so callers must WARN with these instead of quietly building
    or exporting without a recorded replacement (a tester).

    The two missing-file cases get different words (batch 24: a tester read
    "NAS/drive disconnected?" as the app failing to load a clip that was fine):
    when the file's own folder still answers, the drive is clearly connected —
    the file itself was moved, renamed or deleted since it was picked.  Only
    when the folder doesn't answer either is a disconnected share the likely
    story.
    """
    out = []
    for rel, path in (saved or {}).items():
        if not path or not isinstance(path, str):
            continue
        if rel not in slots_by_rel:
            out.append((rel, path, "its slot isn't in this folder"))
        elif not os.path.isfile(path):
            if os.path.isdir(os.path.dirname(path) or "."):
                out.append((rel, path,
                            "the file is no longer in its folder (moved, "
                            "renamed or deleted since it was picked)"))
            else:
                out.append((rel, path,
                            "its folder isn't reachable right now "
                            "(NAS/drive disconnected?)"))
    return out


def same_stem_sibling(path):
    """A file beside the missing *path* with the same name but another
    extension (``clip.mp4`` recorded, only ``clip.mov`` on disk), or ``None``.

    The usual story behind "the file is no longer in its folder": the clip
    was re-exported in a new container and the old file deleted, so only the
    extension differs — a difference invisible in a full NAS path (batch 25:
    A tester saw ``26s_..._Promos2.mov`` sitting right there and read the
    note about the recorded ``...Promos2.mp4`` as a false alarm).  Callers
    surface it next to the missing path so the note explains itself."""
    folder = os.path.dirname(path) or "."
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    if not stem:
        return None
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        if (name.lower() != base.lower()
                and os.path.splitext(name)[0].lower() == stem.lower()
                and os.path.isfile(os.path.join(folder, name))):
            return name
    return None


#: PAD-494: a Stern project's music modes (``plugins.stern.sound_modes``):
#: ``{"names": [...], "slots": {rel: {"2": file}}, "levels": {rel: {"2": dB}}}``
#: and (PAD-565) its sounds in turn, ``"turns": {rel: [file 2, file 3, ...]}``,
#: (PAD-638) the slots of them that play at random, ``"random": [rel, ...]``,
#: and each such file's own loudness, ``"turn_levels": {rel: {"2": dB}}``
SOUND_MODES_KEY = "sound_modes"
#: PAD-565: the mod routes carry a slot's file k in turn as one more of its
#: files, under this mode key + k ("t2"), so it travels wherever its slot's
#: music mode files do; :func:`merge_sound_modes` puts it back in ``turns``
#: (PAD-638: its loudness rides ``levels`` under the same key)
TURN_KEY = "t"


#: PAD-638: music mode m's own file k in turn is carried under "m<m>t<k>"
#: ("m2t3"), its loudness under the same key in ``levels``, and the modes of a
#: slot whose own files play at random in ``"mode_random": {rel: ["2"]}``
_MODE_TURN_RE = re.compile(r"^m(\d+)t(\d+)$")


def _mode_turn_k(m):
    """``(mode, k)`` for a carried key "m2t3", else None."""
    hit = _MODE_TURN_RE.match(str(m))
    return (int(hit.group(1)), int(hit.group(2))) if hit else None


def _turn_k(m):
    """File k in turn for a carried mode key ("t2" -> 2), else None."""
    m = str(m)
    if m.startswith(TURN_KEY) and m[len(TURN_KEY):].isdigit():
        return int(m[len(TURN_KEY):])
    return None


def sound_modes_of(data):
    """The music modes record in sidecar *data* as the mod routes carry it:
    ``{"names", "slots", "levels"}`` with every slot's files (and PAD-638
    ``"random"``, the slots whose files in turn play at random), or ``None`` when
    there are none.  A record saved before mode files had a loudness of their
    own (no ``"levels"``) gave each one its slot's ``audio_levels`` offset, so
    those come out as the files' own levels: carried anywhere, they build the
    same."""
    raw = (data or {}).get(SOUND_MODES_KEY)
    if not isinstance(raw, dict):
        return None
    slots = {}
    for rel, files in (raw.get("slots") or {}).items():
        if isinstance(rel, str) and isinstance(files, dict):
            keep = {str(m): f for m, f in files.items()
                    if isinstance(f, str) and f.strip()}
            if keep:
                slots[rel] = keep
    names = raw.get("names")
    names = ([n if isinstance(n, str) else "" for n in names]
             if isinstance(names, list) else [])
    turns = {}
    for rel, files in (raw.get("turns") or {}).items():
        if isinstance(rel, str) and isinstance(files, list):
            keep = {"%s%d" % (TURN_KEY, k): f for k, f in enumerate(
                [f for f in files if isinstance(f, str) and f.strip()], 2)}
            if keep:
                turns[rel] = keep
    # PAD-641: the flipper buttons' sounds in attract belong to no slot: they go as they are
    attract = [f for f in (raw.get("attract") or []) if isinstance(f, str) and f.strip()] \
        if isinstance(raw.get("attract"), list) else []
    if not slots and not any(names) and not turns and not attract:
        return None
    levels = raw.get("levels")
    if isinstance(levels, dict):
        levels = {rel: {str(m): db for m, db in v.items() if str(m) in slots[rel]}
                  for rel, v in levels.items()
                  if rel in slots and isinstance(v, dict)}
    else:
        own = (data or {}).get("audio_levels") or {}
        levels = {rel: {m: own[rel] for m in files}
                  for rel, files in slots.items() if own.get(rel)}
    # PAD-638: a file in turn's own loudness, under its carried key ("t2")
    for rel, v in ((raw.get("turn_levels") or {}).items()
                   if isinstance(raw.get("turn_levels"), dict) else ()):
        if rel in turns and isinstance(v, dict):
            for k, db in v.items():
                key = "%s%s" % (TURN_KEY, k)
                if key in turns[rel] and db:
                    levels.setdefault(rel, {})[key] = db
    # PAD-638: a music mode's own files in turn, and their loudness, under "m<m>t<k>"
    mturns, mrandom = {}, {}
    mt = raw.get("mode_turns") if isinstance(raw.get("mode_turns"), dict) else {}
    ml = raw.get("mode_turn_levels") if isinstance(raw.get("mode_turn_levels"), dict) else {}
    for rel, by in mt.items():
        if not isinstance(rel, str) or rel not in slots or not isinstance(by, dict):
            continue
        for m, files in by.items():
            if str(m) not in slots[rel] or not isinstance(files, list):
                continue
            for k, f in enumerate([f for f in files if isinstance(f, str) and f.strip()], 2):
                key = "m%st%d" % (m, k)
                mturns.setdefault(rel, {})[key] = f
                db = ((ml.get(rel) or {}).get(str(m)) or {}).get(str(k)) \
                    if isinstance(ml.get(rel), dict) else None
                if db:
                    levels.setdefault(rel, {})[key] = db
        ms = (raw.get("mode_random") or {}).get(rel) \
            if isinstance(raw.get("mode_random"), dict) else None
        keep = sorted(str(m) for m in (ms or ()) if any(
            _mode_turn_k(k)[0] == int(m) for k in mturns.get(rel, {})))
        if keep:
            mrandom[rel] = keep
    for rel, files in turns.items():
        slots.setdefault(rel, {}).update(files)
    for rel, files in mturns.items():
        slots.setdefault(rel, {}).update(files)
    out = {"names": names, "slots": slots,
           "levels": {rel: v for rel, v in levels.items() if v}}
    rnd = sorted(rel for rel in (raw.get("random") or ())
                 if isinstance(rel, str) and rel in turns)
    if rnd:
        out["random"] = rnd
    if mrandom:
        out["mode_random"] = mrandom
    if attract:
        out["attract"] = attract
        if raw.get("attract_gap"):
            out["attract_gap"] = raw["attract_gap"]      # PAD-641 round 2
    return out


def merge_sound_modes(data, rec):
    """Merge a carried music modes record *rec* (``{"names", "slots",
    "levels"}``, files as local paths) into *data*, a project's staged changes.
    A slot's file for a mode the record names wins, with its level; the
    project's own names win where it has them (the user named its modes);
    everything else here is left alone.  Returns how many slots it gave files.
    The record here becomes the kind with levels of their own, its older
    files' levels carried from their slots first (see
    :func:`sound_modes_of`)."""
    here = sound_modes_of(data) or {
        "names": [], "slots": {}, "levels": {}}
    slots = {rel: dict(v) for rel, v in here["slots"].items()}
    random = set(here.get("random") or ())
    mrandom = {rel: set(ms) for rel, ms in (here.get("mode_random") or {}).items()}
    # PAD-565: a slot the record gives files in turn takes the record's, in its order (PAD-638:
    # and its order, at random or not)
    for rel, by_mode in (rec.get("slots") or {}).items():
        if isinstance(by_mode, dict) and any(_turn_k(m) is not None for m in by_mode):
            if rel in slots:
                slots[rel] = {m: f for m, f in slots[rel].items() if _turn_k(m) is None}
            if rel in (rec.get("random") or ()):
                random.add(rel)
            else:
                random.discard(rel)
        # PAD-638: a mode the record gives files in turn of its own takes the record's
        given = {_mode_turn_k(m)[0] for m in (by_mode if isinstance(by_mode, dict) else ())
                 if _mode_turn_k(m)}
        if given:
            if rel in slots:
                slots[rel] = {m: f for m, f in slots[rel].items()
                              if not (_mode_turn_k(m) and _mode_turn_k(m)[0] in given)}
            ms = mrandom.setdefault(rel, set())
            for g in given:
                if str(g) in ((rec.get("mode_random") or {}).get(rel) or ()):
                    ms.add(str(g))
                else:
                    ms.discard(str(g))
    levels = {rel: dict(v) for rel, v in here["levels"].items()}
    n = 0
    for rel, by_mode in (rec.get("slots") or {}).items():
        if not isinstance(by_mode, dict) or not by_mode:
            continue
        got = slots.setdefault(rel, {})
        lv = levels.setdefault(rel, {})
        for m, path in by_mode.items():
            got[str(m)] = path
            db = (rec.get("levels") or {}).get(rel, {}).get(str(m))
            if db:
                lv[str(m)] = db
            else:
                lv.pop(str(m), None)
        n += 1
    names = list(here["names"])
    for i, name in enumerate(rec.get("names") or []):
        if i >= len(names):
            names.append(name)
        elif not str(names[i] or "").strip():
            names[i] = name
    # PAD-641: the record's flipper sounds in attract, when it has any, in place of these
    attract, gap = list(here.get("attract") or []), here.get("attract_gap")
    if rec.get("attract"):
        attract = [f for f in rec["attract"] if isinstance(f, str) and f.strip()]
        gap = rec.get("attract_gap")
        n += 1
    if not n and names == here["names"]:
        return 0
    turns, turn_levels = {}, {}
    for rel, by_mode in slots.items():
        got = sorted((_turn_k(m), f) for m, f in by_mode.items() if _turn_k(m) is not None)
        if got:
            turns[rel] = [f for _k, f in got]
            # PAD-638: each file's own loudness, by where it now stands in the list
            tl = {str(i): (levels.get(rel) or {}).get("%s%d" % (TURN_KEY, k))
                  for i, (k, _f) in enumerate(got, 2)}
            tl = {i: db for i, db in tl.items() if db}
            if tl:
                turn_levels[rel] = tl
    # PAD-638: a music mode's own files in turn, for a mode the slot still has a file for
    mode_turns, mode_levels = {}, {}
    for rel, by_mode in slots.items():
        got = sorted((_mode_turn_k(m), f) for m, f in by_mode.items() if _mode_turn_k(m))
        for (m, k), f in got:
            if str(m) in by_mode:
                mode_turns.setdefault(rel, {}).setdefault(str(m), []).append((k, f))
        for m, kf in (mode_turns.get(rel) or {}).items():
            for i, (k, _f) in enumerate(kf, 2):
                db = (levels.get(rel) or {}).get("m%st%d" % (m, k))
                if db:
                    mode_levels.setdefault(rel, {}).setdefault(m, {})[str(i)] = db
    mode_turns = {rel: {m: [f for _k, f in kf] for m, kf in by.items()}
                  for rel, by in mode_turns.items()}
    slots = {rel: {m: f for m, f in v.items() if _turn_k(m) is None and not _mode_turn_k(m)}
             for rel, v in slots.items()}
    levels = {rel: {m: db for m, db in v.items() if m in slots.get(rel, {})}
              for rel, v in levels.items()}
    out = {"names": names, "slots": {rel: v for rel, v in slots.items() if v},
           "levels": {rel: v for rel, v in levels.items() if v}}
    if turns:
        out["turns"] = turns
        if random & set(turns):
            out["random"] = sorted(random & set(turns))
        if turn_levels:
            out["turn_levels"] = turn_levels
    if mode_turns:
        out["mode_turns"] = mode_turns
        mr = {rel: sorted(m for m in ms if m in mode_turns.get(rel, {}))
              for rel, ms in mrandom.items()}
        mr = {rel: ms for rel, ms in mr.items() if ms}
        if mr:
            out["mode_random"] = mr
        if mode_levels:
            out["mode_turn_levels"] = mode_levels
    if attract:
        out["attract"] = attract
        if gap:
            out["attract_gap"] = gap
    data[SOUND_MODES_KEY] = out
    return n
