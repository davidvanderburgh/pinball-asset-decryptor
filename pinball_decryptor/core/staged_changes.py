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
import threading
import time

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
        with open(os.path.join(assets_dir, SIDE_CAR), "w",
                  encoding="utf-8") as f:
            f.write(text)
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
