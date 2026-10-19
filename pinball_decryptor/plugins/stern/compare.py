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

Sounds packed inside ``image.bin`` can't be diffed one-by-one off the cards
alone (the per-sound layout needs the booted firmware), so from the cards the
report gives the container header's sound/fragment counts and its size —
never a verdict off its digest, which is repacked and re-keyed on every build
and so always differs.  The sound-by-sound answer comes from the two cards'
EXTRACT folders when the caller can find them; see :func:`_sound_rows` and
:mod:`core.audio_compare`.  That comparison is on the audio: a build that
repacks changes the codec's lead-in frame on every sound, and one that
resolves its codec a second way shifts every sound along a frame — counting
either would report a whole catalog as rewritten.

Requested by a tester: compare two releases — or a modded card against its
stock base — and get a complete added/modified/deleted summary per type.

Every change is listed IN FULL — a build that renumbers 4,000 sounds
produces 4,000 rows here.  A row whose name is blank is an item of the count
row above it, and the Compare tab shows the first N of each such run with the
rest one double-click away; see :func:`_listed`.

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
from . import multiimage
from . import sidx as sidx_mod
from .explorer import CardImage
from .info import (_IMAGE_EXTS, _game_elf_bytes, _walk_partition,
                   container_counts, resolve_version)

# NOTHING IS CAPPED HERE.  The report carries every changed file and every
# changed sound it found; how many of them the window lists is the Compare
# tab's "Rows per list" setting, applied when the tree is painted.  Keeping
# the cap out of the report is what lets that setting be instant — raising it
# repaints a report already in memory instead of re-reading two multi-GB
# cards — and what lets Copy Report hand over the whole list.  A tester,
# looking at a build that renumbered thousands of sounds: "would it be
# possible to display more than the first 12 entries for each asset category?
# (Having 25 or 50 entries would be much more comfortable)".


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
         "folders": set(), "sidx_name": "", "part": None,
         "version": None, "edition": None, "name_version": None,
         "manifest": None, "stale": 0, "mtimes": {},
         "images": multiimage.images_for_path(path)}
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
                p["manifest"] = sidx_mod.manifest_files(
                    reader.read_file_bytes(found["sidx_node"])) or None
            except Exception:
                p["manifest"] = None
            if p["manifest"]:
                p["files"], p["stale"], p["mtimes"] = _card_truth(
                    reader, p["manifest"])
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
    if p["manifest"]:
        p["folders"] = {f.split("/", 1)[0] for f in p["manifest"]
                        if "/" in f}
    # The card's own update index outranks the filename (info.resolve_version)
    # — a renamed or relabelled card diffs as the build it really is, so the
    # "Version A -> B" row can't be thrown off by what the file is called.
    folder = next(iter(p["folders"])) if len(p["folders"]) == 1 else ""
    p["version"], p["edition"], _src, p["name_version"] = \
        resolve_version(path, p["sidx_name"], folder)
    return p


def _card_truth(reader, manifest):
    """``(files, stale, mtimes)`` for one card: what it REALLY holds.

    The card's own ``.sidx`` is not the whole truth (PAD-631).  A card built
    by another tool can replace a file and leave its manifest record as Stern
    wrote it: the Heisei Godzilla card swapped 534 videos and still lists
    every one at its stock size and MD5, so a diff of the two manifests said
    "Videos: No changes".  So every record is checked against the size the
    filesystem gives (free: one metadata walk, no file bytes), the way the
    official-release check does (:func:`stock_prints.card_files`); a file of
    another size is changed whatever its record says.  *stale* counts those.

    Files on the card that its manifest does not index at all are kept too,
    so a mod that ADDED one without indexing it still shows; the manifest
    files themselves and Stern's ``spk`` tree are not game assets.  *mtimes*
    is each file's modification time, for :func:`_touched_same_size`."""
    from .stock_prints import _file_nodes, card_files
    nodes = _file_nodes(reader)
    files, stale = card_files(reader, manifest, set(manifest), nodes=nodes)
    for rel, node in nodes.items():
        if (rel not in files and "/" in rel and not rel.startswith("spk/")
                and not rel.endswith(".sidx")):
            files[rel] = (node["size"], "")
    mtimes = {rel: node.get("mtime") for rel, node in nodes.items()}
    return files, stale, mtimes


#: Bytes read from EACH end of a file by :func:`_sample`.
SAMPLE_BYTES = 64 << 10


def _sample(reader, node):
    """MD5 of a file's first and last :data:`SAMPLE_BYTES` (the whole file
    when it is no bigger than both).

    A sample, not the whole file: two mods built from the same stock card
    carry the same replaced videos at fresh times, and hashing all 534 of
    them on both cards took 171 s off a spinning disk.  A re-encode that
    lands on the very same byte count is already rare; one that also keeps
    the head and the tail (an MP4's ``ftyp``/``moov`` boxes hold every
    sample's size and offset) is not a case worth minutes per compare."""
    import hashlib
    size = node["size"]
    h = hashlib.md5()
    if size <= 2 * SAMPLE_BYTES:
        h.update(reader.read_range(node, 0, size))
    else:
        h.update(reader.read_range(node, 0, SAMPLE_BYTES))
        h.update(reader.read_range(node, size - SAMPLE_BYTES, SAMPLE_BYTES))
    return h.hexdigest()


def _touched_same_size(a, b):
    """Paths whose bytes differ although size and record agree on both
    cards — the one replacement a size check cannot see (PAD-631).

    Only asked when the two cards are copies of the SAME base image (most
    shared files keep the identical modification time): then a file whose
    time differs was written later, by whatever built the mod, and only
    those are sampled (:func:`_sample`, in on-disk order).  Two different
    Stern releases carry different times on every file, but their manifests
    are Stern's own and already tell every change, so nothing is read
    there."""
    from .info import _first_block
    from .stock_prints import _file_nodes
    fa, fb, ta, tb = a["files"], b["files"], a["mtimes"], b["mtimes"]
    common = [k for k in fa if k in fb]
    if not common or not ta or not tb:
        return []
    same_time = sum(1 for k in common if ta.get(k) == tb.get(k))
    if same_time * 2 < len(common):
        return []
    todo = [k for k in common
            if fa[k] == fb[k] and ta.get(k) != tb.get(k)]
    if not todo:
        return []
    digests = []
    for side in (a, b):
        with CardImage(side["path"]) as card:
            reader = card.reader(side["part"])
            nodes = _file_nodes(reader)
            have = sorted((k for k in todo if k in nodes),
                          key=lambda k: _first_block(reader, nodes[k]))
            digests.append({k: _sample(reader, nodes[k]) for k in have})
    da, db = digests
    changed = sorted(k for k in todo if da.get(k) != db.get(k))
    for k in changed:
        fb[k] = (fb[k][0], "sample:" + (db.get(k) or "?"))
    return changed


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
    """Asset-type bucket for a manifest path.

    A video or picture is listed as one wherever it sits, scene folder or not
    (PAD-631): Godzilla keeps every one of its 658 videos inside a scene's
    ``scene.assets``, so with the scene test first the Videos section could
    never list a single one.  The Scenes section still counts them in their
    folder's changed files (:func:`compare_cards` rolls every changed path up
    to its scene, not just this bucket's)."""
    base = path.rsplit("/", 1)[-1]
    if path.endswith("/image.bin"):
        return "container"
    if base.startswith("image-sc") and base.endswith(".bin"):
        return "music"
    if path in video_paths:
        return "video"
    if path.lower().endswith(_IMAGE_EXTS):
        return "image"
    if _scene_dir_of(path, scene_dirs) is not None:
        return "scene"
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
    """Rows for one change status: a count row, then one row per item — ALL
    of them — with the status column left blank under its header row.

    That blank name is not cosmetic: it is what marks a row as an ITEM of the
    count row above it, so the renderer can group them and show the first N
    (:func:`core.image_info.group_rows`).  Truncation belongs there, where the
    user can change his mind about it for free; a cap baked in here would mean
    re-reading both cards to see the thirteenth row.

    *ref*, when given, is called per item for that row's third element — the
    on-card file it names, for the Compare tab's double-click open.  The count
    row never gets one: it is not a file."""
    if not items:
        return []
    rows = [(status, "%s:" % _num(len(items)))]
    for it in items:
        rows.append(("", detail(it)) if ref is None
                    else ("", detail(it), ref(it)))
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
# Sounds
# ---------------------------------------------------------------------------

def _container_size(files):
    """Bytes of the packed-audio container per the manifest, or ``None``."""
    if not files:
        return None
    for path in sorted(files):
        if path.endswith("/image.bin"):
            return files[path][0]
    return None


def disk_ref(side, path):
    """A report row pointing at a file that is already on disk — one decoded
    WAV in the user's own extract folder.

    The other rows' refs name a file still inside a card image and are read
    back out of it on demand (:func:`file_ref` / :func:`extract_ref`).  This
    one is a path, so double-clicking a changed sound plays it straight out of
    the extract instead of decoding it a second time."""
    return {"side": side, "disk": os.path.abspath(path),
            "name": os.path.basename(path)}


def _snd_name(rel):
    """A decoded sound's row label: its file name, without the ``audio/``."""
    return rel.split("/", 1)[-1]


def _extract_audio_rows(assets_a, assets_b, md5_a=None, md5_b=None,
                        folders=False):
    """The per-sound diff rows, or ``None`` when the two extracts can't
    supply one (with a row saying which of them was the problem).

    *folders*: the user picked these two FOLDERS (the folder compare,
    :func:`folder_sound_rows`), so the rows name them rather than the cards,
    and *md5_a* / *md5_b* read the sounds as they are on disk now."""
    from ...core import audio_compare

    missing = [tag for tag, d in (("A", assets_a), ("B", assets_b)) if not d]
    if missing:
        return [("Per-sound diff",
                 "no extract found for %s — click Extract Both, then Compare "
                 "again and every changed sound is listed here"
                 % ("either card" if len(missing) == 2
                    else "image " + missing[0]))]

    rows = [] if folders else [("Extract A", assets_a),
                               ("Extract B", assets_b)]
    diff = audio_compare.diff_audio(assets_a, assets_b, md5_a, md5_b)
    if not diff["count_a"] or not diff["count_b"]:
        silent = [tag for tag, n in (("A", diff["count_a"]),
                                     ("B", diff["count_b"])) if not n]
        if folders:
            if len(silent) == 2:
                return [("No changes", "no decoded sounds in either folder")]
            rows.append((
                "Per-sound diff",
                "folder %s holds no decoded sounds — it was extracted with "
                "Audio switched off" % silent[0]))
            return rows
        rows.append((
            "Per-sound diff",
            "the extract for %s holds no decoded sounds — that Extract ran "
            "with Audio switched off, so re-run it with Audio ticked"
            % ("either card" if len(silent) == 2 else "image " + silent[0])))
        return rows

    rows.append(_count_delta("Decoded sounds", diff["count_a"],
                             diff["count_b"]))
    if diff.get("lead_in"):
        # SAY IT, don't just do it.  Silently ignoring bytes is the kind of
        # tolerance that makes a diff untrustworthy; this names exactly what
        # was set aside and why it isn't audio (core.audio_compare).
        rows.append(("Codec lead-in",
                     "%s sound(s) matched only once their first frame was "
                     "set aside — a Spike 2 sound decodes that one sample "
                     "out of whatever image.bin packs in front of it, so "
                     "repacking changes it on every sound at once. It is "
                     "packing, not audio." % _num(diff["lead_in"])))
    if diff.get("shifted"):
        # Same rule as the row above: name the bytes that were set aside.
        # This one is a whole frame of SHIFT, not one frame's value — the
        # two cards hold the same samples at offsets one frame apart, which
        # no digest of the whole file can match (core.audio_compare).
        rows.append(("Codec frame shift",
                     "%s sound(s) matched once one card was read a frame "
                     "later — that build resolved its codec onto the entry "
                     "that emits the packing word as sample 0 and pushes the "
                     "sound along 23 microseconds. Same callout, same samples."
                     % _num(diff["shifted"])))
    # "Unchanged", not "identical": a sound that is byte-identical but has
    # been renumbered lands under Moved, and two rows both claiming to count
    # the identical audio would read as a contradiction.
    rows.append(("Unchanged",
                 "%s of %s sounds are identical and still in the same slot"
                 % (_num(diff["same"]), _num(diff["count_a"]))))
    rows += _listed("Changed", diff["changed"],
                    lambda pair: _snd_name(pair[1]) if
                    _snd_name(pair[0]) == _snd_name(pair[1])
                    else "%s (image A: %s)" % (_snd_name(pair[1]),
                                               _snd_name(pair[0])),
                    ref=lambda pair: disk_ref("B", os.path.join(assets_b,
                                                                pair[1])))
    # Same audio, new slot.  Kept separate from "Changed" because it is the
    # ordinary consequence of a build inserting a sound, not a difference the
    # user can hear — folding it in would drown the rows that matter.
    moved_rows = _listed("Moved", diff["moved"],
                         lambda pair: "%s  ->  %s" % (_snd_name(pair[0]),
                                                      _snd_name(pair[1])),
                         ref=lambda pair: disk_ref(
                             "B", os.path.join(assets_b, pair[1])))
    if moved_rows and len(diff["moved"]) * 2 > diff["count_a"]:
        # Stern renumbers the whole sound directory on some builds (Led
        # Zeppelin 1.21 -> 1.22 moves 545 of 549).  A bare "545:" over a
        # column of renamed slots reads as a disaster; say what it is.
        moved_rows[0] = ("Moved",
                         "%s — this build renumbered the sound directory; "
                         "the audio itself is unchanged"
                         % _num(len(diff["moved"])))
    rows += moved_rows
    rows += _listed("Added", diff["added"], _snd_name,
                    ref=lambda rel: disk_ref("B", os.path.join(assets_b, rel)))
    rows += _listed("Removed", diff["removed"], _snd_name,
                    ref=lambda rel: disk_ref("A", os.path.join(assets_a, rel)))
    if not (diff["changed"] or diff["moved"] or diff["added"]
            or diff["removed"]):
        rows.append(("No changes", "every sound decodes identically in both "
                                   "folders" if folders else
                                   "every sound decodes identically on both "
                                   "cards"))
    return rows


def owns_sound(rel):
    """Is project file *rel* one of the decoded sounds the per-sound diff
    pairs up (``audio/*.wav``, flat, the way an Extract lays them out)?"""
    from ...core.audio_compare import AUDIO_DIR
    head, _, name = rel.partition("/")
    return (head == AUDIO_DIR and bool(name) and "/" not in name
            and not name.startswith(".") and name.lower().endswith(".wav"))


def folder_sound_rows(dir_a, dir_b, dig_a, dig_b):
    """The Sounds section of a two-FOLDER compare (PAD-442).

    The same per-sound diff the card report gives once both cards are
    extracted — slots paired by their ``idxNNNN`` token whatever the naming
    settings, content matched before slots, the codec's lead-in and frame
    shift stepped over (:mod:`core.audio_compare`) — but on the bytes in the
    folders NOW: a project's Replace Audio picks were written over its
    extracted sounds, and its baseline still describes the stock card."""
    return _extract_audio_rows(dir_a, dir_b, md5_a=dig_a, md5_b=dig_b,
                               folders=True)


def _official(side, path):
    """Is *side*'s file at *path* the one Stern released?  ``None`` when the
    official-release table has no record of the card's build or the file."""
    try:
        from . import stock_prints as sp
        release = sp.release_for(side["sidx_name"])
    except Exception:                                     # noqa: BLE001
        return None
    want = ((release or {}).get("files") or {}).get(path)
    got = (side["files"] or {}).get(path)
    if not want or not got:
        return None
    return (got[0] == want[0]
            and (got[1] or "")[:len(want[1])] == want[1])


def _container_differs(a, b, path):
    """The "Container bytes" row when the two ``image.bin`` digests differ.

    Between two BUILDS that says nothing: Stern repacks and re-keys the
    container every time.  Between two cards of the SAME build it says a
    lot (PAD-631): Stern ships one image.bin per build, so one of them has
    had its sounds changed since — the "Orchestral" Heisei Godzilla card
    against stock 1.16.0 LE read "says nothing about the sounds inside it".
    The official-release table, when it knows the build, names which."""
    same = (a["version"] and a["version"] == b["version"]
            and (a["edition"] or "") == (b["edition"] or ""))
    if not same:
        return ("differ — as they do between ANY two builds: Stern repacks "
                "and re-keys image.bin every time, so this says nothing "
                "about the sounds inside it")
    build = " ".join(x for x in (a["version"], a["edition"]) if x)
    oa, ob = _official(a, path), _official(b, path)
    if oa is True and ob is False:
        who = "image B's sounds were replaced (A's are Stern's)"
    elif ob is True and oa is False:
        who = "image A's sounds were replaced (B's are Stern's)"
    elif oa is False and ob is False:
        who = "neither card's sounds are Stern's"
    else:
        who = "one card's sounds were replaced"
    return ("differ — both are build %s, which Stern ships with one "
            "image.bin, so %s; Extract Both lists them" % (build, who))

def _sound_rows(a, b, cont, a_files, b_files, assets_a, assets_b):
    """The Sounds section: what the two cards say about their packed audio,
    and — once both cards have been extracted — the sound-by-sound diff.

    NO VERDICT IS READ OFF THE CONTAINER'S DIGEST.  ``image.bin`` is repacked
    and re-keyed on every Stern build, so its stored MD5 differs between any
    two releases whether or not one sound changed (Led Zeppelin 1.21 vs 1.22:
    same 549 sounds, same container length, 2.4% of the body bytes in common).
    The row used to call that "sounds were re-encoded or replaced" and send
    the user off to extract both cards — which the tab's own Extract Both
    button does, and which used to change nothing about what this section
    said.  Now it changes everything: the extracts ARE the answer.
    """
    rows = [_count_delta("Sounds", a["counts"][1], b["counts"][1],
                         unavailable="container header not readable on this "
                                     "build"),
            _count_delta("Sound fragments", a["counts"][0], b["counts"][0],
                         unavailable="container header not readable on this "
                                     "build")]
    if cont and (cont["added"] or cont["deleted"]):
        rows.append(("Audio container", "present on only one card"))
    else:
        size_a, size_b = _container_size(a_files), _container_size(b_files)
        if size_a is not None or size_b is not None:
            rows.append(("Audio container",
                         "image.bin — %s" % (
                             "%s (unchanged)" % human_size(size_a)
                             if size_a == size_b
                             else "%s -> %s" % (
                                 human_size(size_a) if size_a is not None
                                 else "?",
                                 human_size(size_b) if size_b is not None
                                 else "?"))))
        if cont and cont["modified"]:
            rows.append(("Container bytes", _container_differs(
                a, b, cont["modified"][0])))
        elif a_files is not None and b_files is not None:
            # Matching digests DO settle it: same container bytes, same
            # packed audio.  (The inequality is the meaningless direction.)
            rows.append(("Container bytes",
                         "identical — both cards carry the same packed "
                         "audio, byte for byte"))
    rows += _extract_audio_rows(assets_a, assets_b)
    return rows


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def compare_cards(path_a, path_b, assets_a=None, assets_b=None):
    """Image-Info-shaped sections describing what changed from card A to
    card B: ``[(section_title, [(name, value), ...]), ...]``.

    *assets_a* / *assets_b* are the two cards' extract folders when the caller
    could find them (:func:`core.extract_source.find_extract_for`).  They are
    what makes the Sounds section a real answer rather than an instruction —
    see :func:`_sound_rows`.  Everything else in the report is read off the
    cards themselves and never needs them."""
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
    # A multi-boot card holds several games; the report is on its first,
    # the one every other tab reads and writes (multiimage).  Say which, or
    # a mod sitting in another of its images reads as "No changes".
    for tag, side in (("A", a), ("B", b)):
        imgs = side["images"] or []
        if len(imgs) > 1:
            head.append(("Multi-boot (%s)" % tag,
                         "this card carries %d game images; compared is the "
                         "first, %s (p%d) — the one the boot menu lists "
                         "first and the app edits"
                         % (len(imgs), multiimage.pretty(imgs[0]),
                            imgs[0].part)))
    if a["version"] or b["version"]:
        av, bv = a["version"] or "?", b["version"] or "?"
        head.append(("Version",
                     "%s (same)" % av if av == bv
                     else "%s -> %s" % (av, bv)))
    if a["edition"] or b["edition"]:
        ae, be = a["edition"] or "?", b["edition"] or "?"
        head.append(("Edition", ae if ae == be else "%s -> %s" % (ae, be)))
    # Say so when a file's NAME claims a different build than the card does,
    # or the version row above looks wrong against what's in the file picker.
    for tag, side in (("A", a), ("B", b)):
        if side["name_version"]:
            head.append(("Filename version (%s)" % tag,
                         "named %s but the card says %s — renamed or "
                         "relabelled; the diff uses the card"
                         % (side["name_version"], side["version"])))
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
                                 len(a["manifest"]), len(b["manifest"])))
        for tag, side in (("A", a), ("B", b)):
            if side["stale"]:
                head.append((
                    "Manifest out of date (%s)" % tag,
                    "%s file(s) on this card are not what its own validation "
                    "manifest records (it still lists Stern's size and digest "
                    "for them) — they were compared by what is really on the "
                    "card" % _num(side["stale"])))
        try:
            _touched_same_size(a, b)
        except Exception:                                 # noqa: BLE001
            pass                # the size + record diff below still stands
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

    cont = buckets.pop("container", None) if buckets is not None else None
    sections.append(("Sounds", _sound_rows(a, b, cont, a_files, b_files,
                                           assets_a, assets_b)))

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
        # Every changed path counts toward its scene folder — the videos and
        # pictures listed in their own sections too (see _classify).
        changed_by_dir = {}
        for p in added + deleted + modified:
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

    A ref carrying ``disk`` (:func:`disk_ref`) is already a file: the Sounds
    section's rows point at decoded WAVs in the user's own extract folder.
    Those are handed back untouched rather than copied to *out_dir* — the
    sound has been decoded once already, and a temp duplicate would be a
    second copy of the same audio for no gain.
    """
    on_disk = (ref or {}).get("disk") or ""
    if on_disk:
        if os.path.isfile(on_disk):
            return on_disk
        raise FileNotFoundError(
            "%s is no longer in that extract folder" % on_disk)
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
