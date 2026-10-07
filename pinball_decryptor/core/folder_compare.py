"""Two-folder what-changed report for the Compare tab (PAD-442).

The card report (``Manufacturer.compare_images``) reads two CARD IMAGES, and
only Stern Spike 2 cards carry the validation manifest that makes that cheap.
A modder versioning a mod has something every manufacturer has instead: the
project folders themselves.  A tester: "compare two card image files (or two
extract folders) and report the differences between the assets — which
videos are different, which audio is different … a helpful check when
versioning a complex mod to ensure everything is in there as intended (or not
in there!)".

:func:`compare_folders` is that report, in the same section shape as the card
one, so the tab paints, folds, copies and opens it the same way.

* **Which files count.**  The same ones an Extract's baseline does
  (:func:`checksums.generate_checksums`): no dot-entries (the app's own
  sidecars and its ``.orig`` / ``.write_cache`` / ``.uncorrected`` folders),
  no tracking sidecars, none of :data:`checksums.NON_ASSET_DIRS` (the build
  output, the logs …) and no other extract nested inside.
* **The bytes on disk now, not the baseline.**  A Replace tab writes its pick
  OVER the extracted file (see :mod:`staged_originals`), so a project's
  ``.checksums.md5`` still describes the card it came from, not the mod.
  Reading a digest off it would call a replaced clip unchanged.  So contents
  are hashed — but only where the sizes cannot already answer (a size change
  is a change; a file on one side only needs no read unless it may have
  moved), and through the folder's size+mtime :mod:`hashcache`, which the
  Write scan keeps for the same files.
* **Moved, not deleted and added.**  A byte-identical file under a different
  name is listed once, as Moved, so renaming a folder of clips doesn't read as
  losing them all.
* **By kind**, the way the Replace tabs see files (their own extension lists):
  sounds, videos, images, the Text tab's strings, everything else.
* **The build settings that live beside the files.**  A sound's Level, a
  clip's length or conversion rule, which pictures carry the color profile:
  those sit in the project's :mod:`staged_changes` sidecar, not in any file,
  and two projects with identical files can still build different cards.  The
  sections listed are :data:`tab_settings.SECTIONS` — what the Replace tabs
  save as their settings — minus the picks themselves (their result is the
  file on disk, already compared) and pure display state.

A plugin with a better identity for some files (Stern's decoded sounds pair by
slot and step over its codec's lead-in frame) hands :func:`compare_folders` a
*special* section that takes those files over.

Every listed file row carries a ``{"side", "disk", "name"}`` ref to the file
itself, so a double-click opens it straight out of the folder.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from . import hashcache
from .checksums import (CHECKSUMS_FILE, NON_ASSET_DIRS, TRACKING_SIDECARS,
                        is_other_extract)
from .image_info import human_size

#: The report's file sections, in order: ``(kind, title)``.
KINDS = (("sound", "Sounds"), ("video", "Videos"), ("image", "Images"),
         ("text", "Text"), ("other", "Other files"))

#: What the Text tab edits lives here (``text/strings.tsv``).
TEXT_DIR = "text"

#: Readers hashing at once.  Reads, not CPU: two or three keep one disk busy
#: and let two disks run side by side; more only seek.
_WORKERS = 4


def kind_of(rel):
    """The report section a project file lands in, by the same extension
    lists the Replace tabs scan with."""
    from .audio_slots import AUDIO_EXTS
    from .image import IMAGE_EXTS
    from .video import VIDEO_EXTS
    ext = os.path.splitext(rel)[1].lower()
    if ext in AUDIO_EXTS:
        return "sound"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS or ext == ".dds":
        return "image"
    if rel.split("/", 1)[0] == TEXT_DIR:
        return "text"
    return "other"


def walk(folder):
    """``{rel: (size, mtime_ns)}`` for every project file under *folder*.

    The baseline's rules (see the module docstring), plus EVERY dot-folder:
    the walk that writes the baseline runs before the app has made any of its
    own (``.orig``, ``.uncorrected``, ``.modpack_card`` …), and a compare runs
    after."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        rel_dir = os.path.relpath(dirpath, folder).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and not (not rel_dir and d in NON_ASSET_DIRS)
            and not is_other_extract(os.path.join(dirpath, d)))
        for fn in filenames:
            if fn.startswith(".") or (not rel_dir and fn in TRACKING_SIDECARS):
                continue
            path = os.path.join(dirpath, fn)
            try:
                if os.path.islink(path):
                    continue
                st = os.stat(path)
            except OSError:
                continue
            out[rel_dir + fn] = (st.st_size, st.st_mtime_ns)
    return out


def nested_extracts(folder):
    """Names of the extracts directly inside *folder* (an Extract Both
    holder): picking one of those as A or B leaves the walk nothing to read,
    and the report should say why."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [n for n in names if not n.startswith(".")
            and is_other_extract(os.path.join(folder, n))]


class Digests:
    """MD5s of one folder's files, read on demand through its hashcache.

    Nothing is written into the folder unless the app already keeps a cache
    or a baseline there (:meth:`save`): a folder of the user's own that PAD
    never extracted gets compared, not decorated."""

    def __init__(self, folder):
        self.folder = folder
        self._cache = hashcache.load(folder)
        self._got = {}

    def __call__(self, rel):
        """The file's MD5, or ``None`` when it can't be read."""
        if rel not in self._got:
            self._got[rel] = hashcache.md5_for(
                os.path.join(self.folder, *rel.split("/")), rel, self._cache)
        return self._got[rel]

    def save(self):
        if any(os.path.isfile(os.path.join(self.folder, name))
               for name in (CHECKSUMS_FILE, hashcache.CACHE_FILE)):
            hashcache.save(self.folder, self._cache)


def hash_all(jobs, progress=None, cancel=None):
    """Run ``[(digests, rel)]`` through their readers, a few at a time.

    *progress(done, total)* is called as they land; *cancel()* stops handing
    out new reads (the ones already running finish)."""
    total = len(jobs)
    if not total:
        return
    cancel = cancel or (lambda: False)
    done = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = []
        for dig, rel in jobs:
            if cancel():
                break
            futures.append(pool.submit(dig, rel))
        for fut in futures:
            fut.result()
            done += 1
            if progress is not None:
                progress(done, total)


def diff_files(files_a, files_b, dig_a, dig_b, progress=None, cancel=None):
    """What changed between two ``{rel: (size, mtime_ns)}`` walks.

    Returns ``{"same", "modified", "moved", "deleted", "added"}``: a count of
    files identical at the same path, ``[rel]`` same path with other bytes,
    ``[(rel_a, rel_b)]`` the same bytes under another name, and ``[rel]`` on
    one side only.

    Only the files the sizes can't settle are read: a same-path pair of equal
    size, and a one-sided file whose size the other side also has one-sided
    (the only way it can have moved).  A file that can't be read is never
    called unchanged and never pairs up as moved."""
    common = sorted(set(files_a) & set(files_b))
    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))
    same_size = [r for r in common if files_a[r][0] == files_b[r][0]]
    sizes_a = {files_a[r][0] for r in only_a}
    sizes_b = {files_b[r][0] for r in only_b}
    may_move_a = [r for r in only_a if files_a[r][0] in sizes_b]
    may_move_b = [r for r in only_b if files_b[r][0] in sizes_a]
    jobs = ([(dig_a, r) for r in same_size] + [(dig_b, r) for r in same_size]
            + [(dig_a, r) for r in may_move_a]
            + [(dig_b, r) for r in may_move_b])
    hash_all(jobs, progress=progress, cancel=cancel)

    modified = []
    for rel in common:
        if files_a[rel][0] != files_b[rel][0]:
            modified.append(rel)
            continue
        ma, mb = dig_a(rel), dig_b(rel)
        if ma is None or mb is None or ma != mb:
            modified.append(rel)

    pools = {}
    for rel in may_move_b:
        md5 = dig_b(rel)
        if md5 is not None:
            pools.setdefault((files_b[rel][0], md5), []).append(rel)
    moved, gone = [], set()
    for rel in may_move_a:
        md5 = dig_a(rel)
        pool = pools.get((files_a[rel][0], md5)) if md5 is not None else None
        if pool:
            other = pool.pop(0)
            moved.append((rel, other))
            gone.add(rel)
            gone.add(other)
    return {
        "same": len(common) - len(modified),
        "modified": modified,
        "moved": moved,
        "deleted": [r for r in only_a if r not in gone],
        "added": [r for r in only_b if r not in gone],
    }


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _num(n):
    return format(n, ",")


def listed(status, items, detail, ref=None):
    """A count row, then one row per item — ALL of them — with the name left
    blank, which is what makes them items of the count row above
    (:func:`image_info.group_rows`; the tab folds long runs, never the report).
    *ref* gives each item row its file ref."""
    if not items:
        return []
    rows = [(status, "%s:" % _num(len(items)))]
    for it in items:
        rows.append(("", detail(it)) if ref is None
                    else ("", detail(it), ref(it)))
    return rows


def disk_ref(side, folder, rel):
    """A row's ref: the file itself, in folder A or B."""
    path = os.path.abspath(os.path.join(folder, *rel.split("/")))
    return {"side": side, "disk": path, "name": os.path.basename(path)}


def count_delta(name, av, bv):
    """A count row: "549 -> 561 (+12)" or "549 (unchanged)"."""
    if av == bv:
        return (name, "%s (unchanged)" % _num(av))
    return (name, "%s -> %s (%+d)" % (_num(av), _num(bv), bv - av))


def size_change(av, bv):
    """How a modified file's size moved: "2.0 KB -> 2.5 KB", or the bytes
    when the two round to the same size, or that only the content did."""
    if av == bv:
        return "content changed (%s)" % human_size(bv)
    ha, hb = human_size(av), human_size(bv)
    if ha == hb:
        return "%s (%+d bytes)" % (hb, bv - av)
    return "%s -> %s" % (ha, hb)


def _file_rows(diff, files_a, files_b, dir_a, dir_b, empty):
    """One kind's Added / Modified / Moved / Deleted rows.  Deleted rows open
    folder A's copy — the only one there is; the rest open folder B's."""
    rows = []
    rows += listed("Added", diff["added"],
                   lambda r: "%s — %s" % (r, human_size(files_b[r][0])),
                   ref=lambda r: disk_ref("B", dir_b, r))
    rows += listed("Modified", diff["modified"], lambda r: "%s — %s" % (
        r, size_change(files_a[r][0], files_b[r][0])),
        ref=lambda r: disk_ref("B", dir_b, r))
    rows += listed("Moved", diff["moved"],
                   lambda p: "%s  ->  %s" % p,
                   ref=lambda p: disk_ref("B", dir_b, p[1]))
    rows += listed("Deleted", diff["deleted"],
                   lambda r: "%s — %s" % (r, human_size(files_a[r][0])),
                   ref=lambda r: disk_ref("A", dir_a, r))
    if not rows:
        rows = [("No changes", empty)]
    return rows


def _split(diff, kind_for):
    """The diff, one sub-diff per kind (a moved file goes by its new name)."""
    out = {}

    def bucket(rel):
        return out.setdefault(kind_for(rel), {
            "modified": [], "moved": [], "deleted": [], "added": []})
    for key in ("modified", "deleted", "added"):
        for rel in diff[key]:
            bucket(rel)[key].append(rel)
    for pair in diff["moved"]:
        bucket(pair[1])["moved"].append(pair)
    return out


# ---------------------------------------------------------------------------
# The build settings beside the files
# ---------------------------------------------------------------------------

#: What each settings section is called in the report.  Anything a later tab
#: adds to tab_settings.SECTIONS and this misses is still listed, by its key.
SETTING_LABELS = {
    "audio_loop": "Audio: Loop",
    "audio_keep": "Audio: Keep",
    "audio_levels": "Audio: Level",
    "grow_keep_whole": "Audio: kept whole when the bank grows",
    "audio_trim": "Audio: Trim box",
    "video_asis_slots": "Video: this clip's conversion",
    "video_length_slots": "Video: this clip's length",
    "video_trim": "Video: Trim / pad box",
    "video_no_conversion": "Video: use my files as-is box",
    "video_best_quality": "Video: Best quality box",
    "video_color_slots": "Video: this clip's colors",
    "color_all_videos": "Video: color profile on every clip",
    "video_color_stock": "Video: color profile on stock clips",
    "video_color_profiles": "Video: this clip's color profile",
    "image_keep_size": "Images: Keep size",
    "image_color_slots": "Images: this picture's colors",
    "color_all_images": "Images: color profile on every picture",
    "image_color_unlocked": "Images: game pictures unlocked",
    "image_color_profiles": "Images: this picture's color profile",
    "asset_color_profile": "Color profile for your files",
}

#: Settings compared whole, never slot by slot: a profile is one object.
_WHOLE = ("asset_color_profile",)

#: A setting whose values read better in its own unit than bare.
_UNITS = {"audio_levels": lambda v: "0 dB" if not v else "%+g dB" % v}


def setting_keys():
    """The sidecar sections a build reads: every Replace tab's saved settings
    (:data:`tab_settings.SECTIONS`) bar the picks and pure display state, and
    the files' own color profile."""
    from .tab_settings import NOT_BY_SLOT, PICKS, SECTIONS
    keys = []
    for kind in ("audio", "video", "images"):
        for key in SECTIONS[kind]:
            if key not in PICKS.values() and key not in NOT_BY_SLOT:
                keys.append(key)
    keys.append("asset_color_profile")
    return keys


def _show(value):
    """One setting value as the report shows it."""
    if value is None:
        return "not set"
    if value is True:
        return "on"
    if value is False:
        return "off"
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"] or "unnamed"
    if isinstance(value, (int, float, str)):
        return str(value)
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "…"


def _setting_rows(key, a, b):
    """Rows for one settings section that differs between the two sidecars."""
    label = SETTING_LABELS.get(key, key)
    if key in _WHOLE:
        sa, sb = _show(a), _show(b)
        return [(label, "%s, changed" % sb if sa == sb
                 else "%s -> %s" % (sa, sb))]
    if isinstance(a, dict) or isinstance(b, dict):
        # {slot: value}: the slots whose value moved
        a = a if isinstance(a, dict) else {}
        b = b if isinstance(b, dict) else {}
        show = _UNITS.get(key, _show)
        slots = sorted(r for r in set(a) | set(b) if a.get(r) != b.get(r))
        return listed(label, slots, lambda r: "%s — %s -> %s" % (
            r, show(a.get(r)), show(b.get(r))))
    if isinstance(a, list) or isinstance(b, list):
        # [slot]: the slots ticked on one side only
        sa = {x for x in a if isinstance(x, str)} if isinstance(a, list) \
            else set()
        sb = {x for x in b if isinstance(x, str)} if isinstance(b, list) \
            else set()
        changes = sorted([(r, "off", "on") for r in sb - sa]
                         + [(r, "on", "off") for r in sa - sb])
        return listed(label, changes, lambda c: "%s — %s -> %s" % c)
    if isinstance(a, bool) or isinstance(b, bool):
        # a tick box: never ticked is off
        a, b = bool(a), bool(b)
    return [(label, "%s -> %s" % (_show(a), _show(b)))]


def settings_rows(dir_a, dir_b):
    """The Project settings section, or ``None`` when neither folder has a
    settings sidecar (a plain extract: nothing set, nothing to compare)."""
    from . import staged_changes
    have = [os.path.isfile(os.path.join(d, staged_changes.SIDE_CAR))
            for d in (dir_a, dir_b)]
    if not any(have):
        return None
    sa, sb = staged_changes.load(dir_a), staged_changes.load(dir_b)
    rows = []
    for key in setting_keys():
        va, vb = sa.get(key), sb.get(key)
        if va == vb or (_blank(va) and _blank(vb)):
            continue
        rows += _setting_rows(key, va, vb)
    if not rows:
        rows = [("No changes", "the Replace tabs' per-file settings match")]
    return rows


def _blank(value):
    return value is None or value is False or value == {} or value == []


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _folder_row(tag, folder, files):
    total = sum(size for size, _m in files.values())
    return ("Folder %s" % tag, "%s — %s files, %s"
            % (folder, _num(len(files)), human_size(total)))


def _source_row(tag, folder):
    """Which card the folder was extracted from, when it recorded one."""
    from .extract_source import read_extract_source
    rec = read_extract_source(folder) or {}
    name = rec.get("input_name") or ""
    if not name:
        return None
    ver = rec.get("card_version") or ""
    return ("Extracted from %s" % tag,
            "%s (%s)" % (name, ver) if ver else name)


def compare_folders(dir_a, dir_b, special=None, progress=None, cancel=None):
    """Image-Info-shaped sections describing what changed from folder A to
    folder B: ``[(section_title, [(name, value[, ref]), ...]), ...]``.

    *special*, when a plugin gives one, is ``(title, owns, rows)``: the files
    ``owns(rel)`` accepts leave the generic sections, and ``rows(dir_a, dir_b,
    dig_a, dig_b)`` builds the section *title* for them instead (it replaces
    the generic section of that name; the rest of that kind are listed under
    "Other <title lower-cased>").  *dig_a* / *dig_b* are the folders'
    :class:`Digests`, so it reads the bytes on disk, not a baseline.

    *progress(done, total)* reports reads of file contents; *cancel()* stops
    them.  Read-only on both folders except for the hashcache the app already
    keeps in its own projects (:meth:`Digests.save`)."""
    dir_a, dir_b = os.path.abspath(dir_a), os.path.abspath(dir_b)
    if os.path.normcase(dir_a) == os.path.normcase(dir_b):
        return [("Compared", [("Folder A", dir_a), ("Folder B", dir_b),
                              ("Warning", "A and B are the same folder — "
                                          "pick two different ones")])]
    files_a, files_b = walk(dir_a), walk(dir_b)
    head = [_folder_row("A", dir_a, files_a), _folder_row("B", dir_b, files_b)]
    for tag, folder in (("A", dir_a), ("B", dir_b)):
        row = _source_row(tag, folder)
        if row:
            head.append(row)
    for tag, folder, files in (("A", dir_a, files_a), ("B", dir_b, files_b)):
        inner = nested_extracts(folder) if not files else []
        if inner:
            head.append(("Warning", "folder %s holds other extracts (%s), "
                                    "not files of its own — pick one of them"
                         % (tag, ", ".join(inner))))
    head.append(count_delta("Files", len(files_a), len(files_b)))
    sections = [("Compared", head)]

    dig_a, dig_b = Digests(dir_a), Digests(dir_b)
    own_title, owns, own_rows = special or (None, None, None)
    generic_a = {r: v for r, v in files_a.items() if not (owns and owns(r))}
    generic_b = {r: v for r, v in files_b.items() if not (owns and owns(r))}
    try:
        diff = diff_files(generic_a, generic_b, dig_a, dig_b,
                          progress=progress, cancel=cancel)
        if cancel is not None and cancel():
            return []
        own = own_rows(dir_a, dir_b, dig_a, dig_b) if own_rows else None
    finally:
        dig_a.save()
        dig_b.save()
    head.append(("Unchanged", "%s files identical in both, at the same path%s"
                 % (_num(diff["same"]),
                    " (%s: see that section)" % own_title.lower()
                    if own is not None else "")))

    by_kind = _split(diff, kind_of)
    present = {kind_of(r) for r in list(generic_a) + list(generic_b)}
    for kind, title in KINDS:
        sub = by_kind.get(kind, {"modified": [], "moved": [], "deleted": [],
                                 "added": []})
        if own is not None and title == own_title:
            sections.append((title, own))
            if kind not in present:
                continue
            title = "Other %s" % title.lower()
        empty = ("" if kind in present
                 else "no %s in either folder" % title.lower())
        sections.append((title, _file_rows(sub, files_a, files_b,
                                           dir_a, dir_b, empty)))
    if own is not None and own_title not in dict(KINDS).values():
        sections.insert(1, (own_title, own))

    settings = settings_rows(dir_a, dir_b)
    if settings is not None:
        sections.append(("Project settings", settings))
    return sections
