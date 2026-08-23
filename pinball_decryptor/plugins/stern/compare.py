"""Two-card what-changed report for the Compare tab.

Everything is read the way the Image Info probe reads a single card — one
metadata walk plus small bounded reads, nothing extracted or decoded:

* File-level added / modified / deleted comes from each card's OWN ``.sidx``
  validation manifest, which stores a size and an MD5 for every moddable
  file (see :mod:`.sidx`).  "Modified" therefore means Stern's own stored
  digest differs, and diffing two multi-GB cards costs two manifest reads.
* Changed files are bucketed by asset type: videos (the same 12-byte
  ``ftyp`` sniff the extract uses), images (by extension), scenes (any
  change under a directory holding a ``scene.radium``), the per-song music
  banks, the packed-audio container, and everything else.
* Adjustment defaults and the high-score board are decoded from both game
  ELFs with the same parsers the Defaults tab uses, then diffed by
  adjustment name / slot label (the stable keys across builds).

Sounds packed inside ``image.bin`` can't be diffed one-by-one without an
Extract (the per-sound layout needs the booted firmware), so the report
gives the header's sound/fragment counts and whether the container's bytes
changed at all.

Requested by a tester: compare two releases — or a modded card against its
stock base — and get a complete added/modified/deleted summary per type.

Every listed FILE row also carries a *ref* — the third element of the row
tuple, ``{"side", "part", "path", "name"}`` — naming the card and the
on-card path that row came from, so the Compare tab can pull that one file
off the image and open it (:func:`extract_ref`).  A tester, after the report
shipped: "being able to open/play modified, added, or deleted assets via
double-click would be awesome".  Nothing else in the report has one: an
adjustment default or a scene FOLDER is not a file anything can open, and a
ref that pointed at something unopenable would be worse than none.
"""

import os

from ...core.image_info import human_size
from . import sidx as sidx_mod
from .explorer import CardImage
from .info import (_IMAGE_EXTS, _game_elf_bytes, _walk_partition,
                   container_counts, version_from_filename)

# Listed file names are capped per change row; a final "… and N more" row
# keeps the report honest about what it didn't list (Copy Report includes
# the same rows, so the caps are never silent).
_MAX_LISTED = 12


# ---------------------------------------------------------------------------
# Per-card probe
# ---------------------------------------------------------------------------

def _firmware_tables(fw):
    """``(adjustment defaults by name, high-score rows by label)`` from a
    game ELF; either is ``None`` when that table can't be located on this
    build (the caller degrades to a note instead of a diff)."""
    try:
        from .adjustments import AdjustmentTable
        table = AdjustmentTable(fw)
    except Exception:
        return None, None
    adjust = {}
    for i in range(table.count):
        e = table.entry(i)
        if e["name"] and e["name"] != "AD_INVALID":
            adjust[e["name"]] = e["default"]
    try:
        from .high_scores import HighScoreDefaults
        rows = HighScoreDefaults(fw, table).rows
    except Exception:
        return adjust, None
    scores = {}
    for r in rows:
        adj = r.get("adjustment")
        scores[r["label"]] = {
            "display": r["display"],
            "initials": r["initials"],
            "player": r["name"],
            "score": adjust.get(adj) if adj else None,
        }
    return adjust, scores


def _probe(path):
    """Everything the diff needs from one card, in one open: the manifest's
    per-file digests, the ftyp-sniffed video paths, the container counts,
    and the firmware's adjustment/high-score tables."""
    p = {"path": path, "files": None, "video_paths": set(),
         "counts": (None, None), "adjust": None, "scores": None,
         "folders": set(), "sidx_name": "", "part": None}
    p["version"], p["edition"] = version_from_filename(path)
    with CardImage(path) as card:
        parts = [pt for pt in card.partitions() if pt.browsable]
        parts.sort(key=lambda pt: pt.size, reverse=True)
        best = None
        for pt in parts:
            reader = card.reader(pt.index)
            found = _walk_partition(reader)
            if best is None:
                best = (reader, found, pt.index)
            if found["sidx_node"] is not None:
                best = (reader, found, pt.index)
                break
        if best is None:
            raise ValueError("no readable data partition")
        # The partition index travels with the report so a row's ref can be
        # reopened later without repeating this walk (extract_ref).
        reader, found, p["part"] = best
        if found["sidx_node"] is not None:
            p["sidx_name"] = os.path.basename(found["sidx_path"])
            try:
                p["files"] = sidx_mod.manifest_files(
                    reader.read_file_bytes(found["sidx_node"])) or None
            except Exception:
                p["files"] = None
        p["video_paths"] = {v.lstrip("/") for v in found["video_paths"]}
        if found["image_bin"] is not None:
            try:
                p["counts"] = container_counts(
                    reader.peek(found["image_bin"], 0x68))
            except Exception:
                p["counts"] = (None, None)
        fw = _game_elf_bytes(reader, found)
        if fw:
            p["adjust"], p["scores"] = _firmware_tables(fw)
    if p["files"]:
        p["folders"] = {f.split("/", 1)[0] for f in p["files"] if "/" in f}
    # A renamed card still carries its version in the on-card sidx name.
    if p["sidx_name"] and p["version"] is None:
        p["version"], s_ed = version_from_filename(p["sidx_name"])
        if p["edition"] is None:
            p["edition"] = s_ed
    return p


# ---------------------------------------------------------------------------
# Diff helpers (pure — unit-tested directly)
# ---------------------------------------------------------------------------

def _tri(a_map, b_map):
    """``(added, deleted, modified)`` key lists between two ``{key: value}``
    maps — added/deleted by presence, modified by value inequality."""
    added = sorted(k for k in b_map if k not in a_map)
    deleted = sorted(k for k in a_map if k not in b_map)
    modified = sorted(k for k in a_map
                      if k in b_map and a_map[k] != b_map[k])
    return added, deleted, modified


def _scene_dir_of(path, scene_dirs):
    """The scene directory owning *path* (any ancestor holding a
    ``scene.radium``), or ``None``."""
    d = path.rsplit("/", 1)[0] if "/" in path else ""
    while d:
        if d in scene_dirs:
            return d
        d = d.rsplit("/", 1)[0] if "/" in d else ""
    return None


def _classify(path, scene_dirs, video_paths):
    """Asset-type bucket for a manifest path.  A video or image inside a
    scene's folder belongs to the scene (the game treats the folder as one
    unit), so the scene test outranks the sniff/extension ones."""
    base = path.rsplit("/", 1)[-1]
    if path.endswith("/image.bin"):
        return "container"
    if base.startswith("image-sc") and base.endswith(".bin"):
        return "music"
    if _scene_dir_of(path, scene_dirs) is not None:
        return "scene"
    if path in video_paths:
        return "video"
    if path.lower().endswith(_IMAGE_EXTS):
        return "image"
    return "other"


def _disp(path, folders):
    """Path as shown: the shared game folder adds nothing, so strip it."""
    if len(folders) == 1:
        folder = next(iter(folders))
        if path.startswith(folder + "/"):
            return path[len(folder) + 1:]
    return path


def _num(n):
    return format(n, ",")


def _count_delta(name, av, bv, unavailable="not readable"):
    """A count row: "549 -> 561 (+12)", "549 (unchanged)", or the reason."""
    if av is None and bv is None:
        return (name, unavailable)
    if av is None or bv is None:
        return (name, "%s -> %s" % (_num(av) if av is not None else "?",
                                    _num(bv) if bv is not None else "?"))
    if av == bv:
        return (name, "%s (unchanged)" % _num(av))
    return (name, "%s -> %s (%+d)" % (_num(av), _num(bv), bv - av))


def _listed(status, items, detail, ref=None):
    """Rows for one change status: a count row, then one row per item (the
    status column left blank under its header row), capped with an honest
    "… and N more".

    *ref*, when given, is called per item for that row's third element — the
    on-card file it names, for the Compare tab's double-click open.  The count
    row and the "… and N more" row never get one: neither is a file."""
    if not items:
        return []
    rows = [(status, "%s:" % _num(len(items)))]
    for it in items[:_MAX_LISTED]:
        rows.append(("", detail(it)) if ref is None
                    else ("", detail(it), ref(it)))
    if len(items) > _MAX_LISTED:
        rows.append(("", "… and %s more"
                     % _num(len(items) - _MAX_LISTED)))
    return rows


def file_ref(side, part, path):
    """One listed file row's ref: which card, which partition, which path.

    ``part`` may be ``None`` on a card whose partition index could not be
    recorded — :func:`extract_ref` then searches, rather than refusing."""
    return {"side": side, "part": part, "path": path,
            "name": path.rsplit("/", 1)[-1]}


def _file_section(added, deleted, modified, a_files, b_files, folders,
                  a_part=None, b_part=None):
    """The Added/Modified/Deleted rows for one asset-type bucket.

    Added and Modified rows point at card B (the file is there); Deleted rows
    point at card A, which is the only card that still HAS the file — pointing
    a deleted row at B would open nothing, every time."""
    rows = []
    rows += _listed("Added", added,
                    lambda p: "%s — %s" % (_disp(p, folders),
                                           human_size(b_files[p][0])),
                    ref=lambda p: file_ref("B", b_part, p))
    rows += _listed("Modified", modified, lambda p: "%s — %s" % (
        _disp(p, folders),
        "content changed (%s)" % human_size(b_files[p][0])
        if a_files[p][0] == b_files[p][0]
        else "%s -> %s" % (human_size(a_files[p][0]),
                           human_size(b_files[p][0]))),
        ref=lambda p: file_ref("B", b_part, p))
    rows += _listed("Deleted", deleted,
                    lambda p: "%s — %s" % (_disp(p, folders),
                                           human_size(a_files[p][0])),
                    ref=lambda p: file_ref("A", a_part, p))
    if not rows:
        rows = [("No changes", "")]
    return rows


def _adjust_rows(a_adj, b_adj):
    """Diff rows for the adjustment-default tables (either side ``None`` =
    that build's table couldn't be located)."""
    if a_adj is None or b_adj is None:
        return [("Adjustments",
                 "table not readable on %s — no diff"
                 % ("either card" if a_adj is None and b_adj is None
                    else ("image A" if a_adj is None else "image B")))]
    added, deleted, modified = _tri(a_adj, b_adj)
    rows = [_count_delta("Total", len(a_adj), len(b_adj))]
    rows += _listed("Added", added, lambda n: n)
    rows += _listed("Modified defaults", modified,
                    lambda n: "%s: %s -> %s" % (n, _num(a_adj[n]),
                                                _num(b_adj[n])))
    rows += _listed("Deleted", deleted, lambda n: n)
    return rows


def _score_rows(a_sc, b_sc):
    """Diff rows for the high-score boards (added/deleted places by slot
    label — the stable key across builds — and per-slot default changes)."""
    if a_sc is None or b_sc is None:
        return [("High scores",
                 "board not readable on %s — no diff"
                 % ("either card" if a_sc is None and b_sc is None
                    else ("image A" if a_sc is None else "image B")))]
    added, deleted, modified = _tri(a_sc, b_sc)
    rows = [_count_delta("Places", len(a_sc), len(b_sc))]
    rows += _listed("Added", added, lambda k: b_sc[k]["display"])
    rows += _listed("Deleted", deleted, lambda k: a_sc[k]["display"])

    def _changes(k):
        av, bv = a_sc[k], b_sc[k]
        bits = []
        if av["initials"] != bv["initials"]:
            bits.append("initials %s -> %s" % (av["initials"] or "?",
                                               bv["initials"] or "?"))
        if av["player"] != bv["player"]:
            bits.append("player %s -> %s" % (av["player"] or "?",
                                             bv["player"] or "?"))
        if av["score"] != bv["score"]:
            bits.append("default score %s -> %s"
                        % (_num(av["score"]) if av["score"] is not None
                           else "?",
                           _num(bv["score"]) if bv["score"] is not None
                           else "?"))
        return "%s: %s" % (bv["display"], "; ".join(bits))

    rows += _listed("Modified", modified, _changes)
    return rows


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def compare_cards(path_a, path_b):
    """Image-Info-shaped sections describing what changed from card A to
    card B: ``[(section_title, [(name, value), ...]), ...]``."""
    try:
        a = _probe(path_a)
    except Exception as e:
        return [("Error", [("Image A", "could not read: %s" % e)])]
    try:
        b = _probe(path_b)
    except Exception as e:
        return [("Error", [("Image B", "could not read: %s" % e)])]

    head = [
        ("Image A", "%s — %s" % (os.path.basename(path_a),
                                 human_size(os.path.getsize(path_a)))),
        ("Image B", "%s — %s" % (os.path.basename(path_b),
                                 human_size(os.path.getsize(path_b)))),
    ]
    if a["version"] or b["version"]:
        av, bv = a["version"] or "?", b["version"] or "?"
        head.append(("Version",
                     "%s (same)" % av if av == bv
                     else "%s -> %s" % (av, bv)))
    if a["edition"] or b["edition"]:
        ae, be = a["edition"] or "?", b["edition"] or "?"
        head.append(("Edition", ae if ae == be else "%s -> %s" % (ae, be)))
    folders = a["folders"] | b["folders"]
    if a["folders"] and b["folders"] and a["folders"] != b["folders"]:
        head.append(("Warning",
                     "different games (%s vs %s) — this diff will read as "
                     "everything changed"
                     % (", ".join(sorted(a["folders"])),
                        ", ".join(sorted(b["folders"])))))
    elif len(folders) == 1:
        head.append(("Game folder", next(iter(folders))))

    sections = [("Compared", head)]

    a_files, b_files = a["files"], b["files"]
    if a_files is None or b_files is None:
        which = ("either card" if a_files is None and b_files is None
                 else ("image A" if a_files is None else "image B"))
        head.append(("File diff",
                     "unavailable — the validation manifest could not be "
                     "read on %s" % which))
        buckets = None
    else:
        head.append(_count_delta("Validated files",
                                 len(a_files), len(b_files)))
        scene_dirs = {p[:-len("/scene.radium")]
                      for p in list(a_files) + list(b_files)
                      if p.endswith("/scene.radium")}
        video_paths = a["video_paths"] | b["video_paths"]
        added, deleted, modified = _tri(a_files, b_files)
        buckets = {}
        for status, paths in (("added", added), ("deleted", deleted),
                              ("modified", modified)):
            for p in paths:
                kind = _classify(p, scene_dirs, video_paths)
                buckets.setdefault(kind, {"added": [], "deleted": [],
                                          "modified": []})[status].append(p)

    # Sounds: header counts + whether the container's bytes moved at all.
    snd = [_count_delta("Sounds", a["counts"][1], b["counts"][1],
                        unavailable="header not readable — run Extract"),
           _count_delta("Sound fragments", a["counts"][0], b["counts"][0],
                        unavailable="header not readable — run Extract")]
    if buckets is not None:
        cont = buckets.pop("container", None)
        if cont and cont["modified"]:
            snd.append(("Audio container",
                        "image.bin changed — sounds were re-encoded or "
                        "replaced (extract both cards to compare them "
                        "one by one)"))
        elif cont and (cont["added"] or cont["deleted"]):
            snd.append(("Audio container", "present on only one card"))
        else:
            snd.append(("Audio container", "image.bin unchanged"))
    sections.append(("Sounds", snd))

    if buckets is not None:
        def _bucket_section(title, kind):
            bk = buckets.get(kind, {"added": [], "deleted": [],
                                    "modified": []})
            sections.append((title, _file_section(
                bk["added"], bk["deleted"], bk["modified"],
                a_files, b_files, folders,
                a_part=a["part"], b_part=b["part"])))

        _bucket_section("Music banks", "music")
        _bucket_section("Videos", "video")
        _bucket_section("Images", "image")

        # Scenes diff at the scene-folder level: the game treats the folder
        # (scene.radium + its assets) as one unit, so "modified by content"
        # is any indexed file in it changing (the tester's wish list called
        # this the hard one — the manifest's own digests make it cheap).
        a_dirs = {p[:-len("/scene.radium")] for p in a_files
                  if p.endswith("/scene.radium")}
        b_dirs = {p[:-len("/scene.radium")] for p in b_files
                  if p.endswith("/scene.radium")}
        changed_by_dir = {}
        for st in ("added", "deleted", "modified"):
            for p in buckets.get("scene", {}).get(st, ()):
                d = _scene_dir_of(p, scene_dirs)
                if d is not None:
                    changed_by_dir.setdefault(d, []).append(p)
        sc_rows = []
        sc_rows += _listed(
            "Added", sorted(b_dirs - a_dirs),
            lambda d: "%s — %s files" % (
                _disp(d, folders),
                _num(sum(1 for p in b_files if p.startswith(d + "/")))))
        sc_rows += _listed(
            "Modified", sorted(d for d in (a_dirs & b_dirs)
                               if d in changed_by_dir),
            lambda d: "%s — %s file(s) changed"
                      % (_disp(d, folders), _num(len(changed_by_dir[d]))))
        sc_rows += _listed(
            "Deleted", sorted(a_dirs - b_dirs),
            lambda d: "%s — %s files" % (
                _disp(d, folders),
                _num(sum(1 for p in a_files if p.startswith(d + "/")))))
        if not sc_rows:
            sc_rows = [("No changes", "")]
        sections.append(("Scenes", sc_rows))

        _bucket_section("Other files", "other")

    sections.append(("Adjustments", _adjust_rows(a["adjust"], b["adjust"])))
    sections.append(("High scores", _score_rows(a["scores"], b["scores"])))
    return sections


# ---------------------------------------------------------------------------
# Opening one listed file
# ---------------------------------------------------------------------------

#: Sniffed head -> the extension the desktop needs to open the copy.  Spike 2
#: stores its videos EXTENSIONLESS (``0.asset``), so a straight copy of one
#: lands on a name Windows has no handler for and "open the changed video"
#: fails on the file name rather than on anything real.  Only formats the
#: report already identifies this way are listed; a byte pattern nobody
#: recognises keeps the card's own name.
def _sniffed_ext(head):
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ".mp4"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"OggS":
        return ".ogg"
    return ""


def _name_for_desktop(path):
    """Rename *path* to carry the extension its bytes say it has, when the
    card's own name has none (or the useless ``.asset``).  Returns the path to
    open — the original when nothing is recognised, so a file is never hidden
    behind a wrong extension."""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if ext and ext.lower() != ".asset":
        return path
    try:
        with open(path, "rb") as f:
            new_ext = _sniffed_ext(f.read(12))
    except OSError:
        return path
    if not new_ext:
        return path
    renamed = os.path.join(os.path.dirname(path), (stem or base) + new_ext)
    try:
        os.replace(path, renamed)
    except OSError:
        return path
    return renamed


def extract_ref(image_path, ref, out_dir):
    """Copy the file *ref* names off *image_path* into *out_dir*; return the
    written path.

    The recorded partition index is TRIED, NOT TRUSTED: the report can outlive
    the card being renamed or replaced under the same path, and a stale index
    would raise ``ValueError`` for a file that is plainly on the image.  So a
    miss falls back to every browsable partition, biggest first (the data
    partition), and only a genuine absence raises ``FileNotFoundError``.

    Nothing is written on failure — a zero-byte file the desktop then opens
    into an error dialog is the worst of both outcomes.
    """
    path = (ref or {}).get("path") or ""
    if not path:
        raise FileNotFoundError("no file recorded for that row")
    out_path = os.path.join(out_dir, path.rsplit("/", 1)[-1])
    with CardImage(image_path) as card:
        order = [pt.index for pt in
                 sorted((pt for pt in card.partitions() if pt.browsable),
                        key=lambda pt: pt.size, reverse=True)]
        want = ref.get("part")
        if want is not None and want in order:
            order.remove(want)
            order.insert(0, want)
        last = None
        for index in order:
            try:
                card.extract_file(index, "/" + path.lstrip("/"), out_path)
                return _name_for_desktop(out_path)
            except (FileNotFoundError, IsADirectoryError, ValueError) as e:
                last = e
    raise FileNotFoundError(str(last) if last is not None else path)
