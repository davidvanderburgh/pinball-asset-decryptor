"""Official Stern stock fingerprints: is this card the one Stern shipped?

Until this table existed, "stock" meant whatever card was extracted: the
project's ``.checksums.md5`` baseline is that card, ``.pad-build.json`` only
knows cards PAD built on THIS machine, and the version stamp comes from the
update index, which a built card keeps (a shared Heisei 1.96 card reads as
Godzilla LE 1.16).  A revision extracted as if it were stock then shows up as
conflicts later (PAD-421).  The table answers the question from the bytes:

* One entry per official Spike 2 release, keyed by the card's own
  ``/spk/index/<title>-<version>.sidx`` name (``godzilla_le-1_16_0.sidx``).
* ``files``: every file Stern's validation manifest indexes, with its size and
  the first 16 hex digits of its MD5 -- taken from the official card's own
  ``.sidx`` and checked against the bytes on that card when the table was
  made (``scripts/make_stock_prints.py``).
* ``pictures``: the first 8 hex digits of the MD5 of every picture embedded in
  the release's ``scene.radium`` files -- the same digits the extract puts at
  the end of a ``radimg_..._<md5[:8]>`` file name, so a project folder can be
  checked against stock without touching a card.

Hashes only: nothing of Stern's ships in the table.

Checking a card is a manifest read, not a hash of the card: every Spike 2
card carries a ``.sidx`` whose records Stern's ``spk`` re-validates at boot,
and every PAD build rewrites the records of the files it changed (see
:mod:`.sidx`), so a card that boots has a manifest that tells the truth about
its files.  Diffing it against the official one costs one directory walk plus
reading the radiums of the scenes that changed (to count pictures).
"""

import hashlib
import json
import lzma
import os

from . import sidx as sidx_mod

#: The shipped table, beside this module.
TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "stock_prints.json.xz")
TABLE_FORMAT = 1
#: Hex digits of each file MD5 kept in the table (64 bits: a collision between
#: a changed file and its own stock digest is not a real-world event).
FILE_DIGITS = 16
#: Hex digits of each picture MD5 -- the extract's ``radimg_`` suffix length.
PICTURE_DIGITS = 8

_SCENE = "/scene.radium"

_table_cache = {}


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

def load_table(path=None):
    """``{sidx_name: release}`` from the shipped table (cached), or ``{}``
    when it is missing or unreadable -- every caller then reads "no official
    record", never a verdict."""
    path = path or TABLE_PATH
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_size, st.st_mtime_ns)
    hit = _table_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with lzma.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        releases = data.get("releases") if data.get("format") == TABLE_FORMAT \
            else None
        if not isinstance(releases, dict):
            releases = {}
    except (OSError, ValueError, EOFError, AttributeError, lzma.LZMAError):
        releases = {}
    _table_cache[path] = (key, releases)
    return releases


def save_table(releases, path=None):
    """Write *releases* as the table (the generator's half of
    :func:`load_table`).  Keys and paths are sorted so a regenerated table
    diffs cleanly."""
    path = path or TABLE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"format": TABLE_FORMAT, "releases": releases}
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"))
    # xz, not gzip: an LE and a Pro release share most paths, and gzip's
    # 32 KB window never sees the repeat (1.0 MB vs 2.3 MB for 53 releases).
    with open(path, "wb") as out:
        out.write(lzma.compress(raw.encode("utf-8"),
                                preset=9 | lzma.PRESET_EXTREME))


def release_for(sidx_name, table=None):
    """The official release named by the card's ``.sidx``, or ``None``."""
    if not sidx_name:
        return None
    table = load_table() if table is None else table
    return table.get(os.path.basename(sidx_name).lower())


def picture_set(release):
    """The release's stock picture digests as a set."""
    blob = (release or {}).get("pictures") or ""
    return {blob[i:i + PICTURE_DIGITS]
            for i in range(0, len(blob), PICTURE_DIGITS)}


def folder_name(folder):
    """``"godzilla_le"`` -> ``"Godzilla LE"`` (the way the Multi-boot tab
    names an image by its game folder)."""
    from .multiimage import _EDITIONS
    words = [w for w in (folder or "").replace("_", " ").split() if w]
    return " ".join(_EDITIONS.get(w.lower(), w.capitalize()) for w in words)


def release_label(release):
    """``"Godzilla LE 1.16"`` for a release entry."""
    return "%s %s" % (release.get("name") or release.get("folder") or "?",
                      _short_version(release.get("version")))


def _short_version(v):
    """``"1.16.0"`` -> ``"1.16"`` (Stern's own way of naming a build);
    ``"1.58.1"`` stays as it is."""
    v = v or "?"
    parts = v.split(".")
    if len(parts) == 3 and parts[2] == "0":
        return ".".join(parts[:2])
    return v


# ---------------------------------------------------------------------------
# Making an entry (the generator; also how a test proves the round trip)
# ---------------------------------------------------------------------------

def radium_pictures(data):
    """The picture digests (``md5[:8]``) of every image inside one
    ``scene.radium``, exactly as the extract names them."""
    from .engine import parse_radium_images
    out = set()
    for im in parse_radium_images(data):
        raw = data[im["data_off"]:im["data_off"] + im["length"]]
        out.add(hashlib.md5(raw).hexdigest()[:PICTURE_DIGITS])
    return out


def _md5_node(reader, node):
    h = hashlib.md5()
    for _off, chunk in reader.read_file_chunks(node):
        h.update(chunk)
    return h.hexdigest()


#: :func:`make_release` re-hashes every indexed file up to this size against
#: the manifest by default: the scenes, pictures and program, a few hundred
#: MB a card.  The videos and the sound bank (GBs, minutes a card on a
#: spinning disk) only with ``verify_max=None``.
VERIFY_MAX = 32 << 20


def make_release(card_path, verify=True, log=None, cancel=None,
                 verify_max=VERIFY_MAX):
    """Read one official card into a table entry ``(sidx_name, release)``.

    With *verify* every indexed file up to *verify_max* bytes (all of them
    when it is ``None``) is read and hashed, and a single one whose bytes
    disagree with the card's own manifest refuses the card: an entry is only
    made from a card that is what its manifest says.  A card with a
    ``.pad-build.json`` beside it is PAD's build, never stock, and is refused
    outright.  The radiums are read either way (their pictures are the
    ``pictures`` field)."""
    from .compare import _probe
    from .explorer import CardImage
    from .engine import BUILD_MANIFEST_SUFFIX
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    if os.path.exists(str(card_path) + BUILD_MANIFEST_SUFFIX):
        raise ValueError("%s is a card PAD built, not an official one"
                         % card_path)
    probe = _probe(card_path)
    files = probe["files"]
    if not files or not probe["sidx_name"]:
        raise ValueError("%s: no readable .sidx manifest" % card_path)
    folders = probe["folders"]
    folder = next(iter(folders)) if len(folders) == 1 else ""
    pictures = set()
    bad = []
    with CardImage(card_path) as card:
        reader = card.reader(probe["part"])
        nodes = {}
        for fpath, _ino, node in reader.iter_regular_files(min_size=0,
                                                           max_depth=20):
            nodes[fpath.lstrip("/")] = node
        for i, (rel, (size, md5)) in enumerate(sorted(files.items())):
            if cancel():
                raise RuntimeError("cancelled")
            node = nodes.get(rel)
            if node is None:
                bad.append("%s: missing" % rel)
                continue
            if rel.endswith(_SCENE):
                data = reader.read_file_bytes(node)
                pictures |= radium_pictures(data)
                if verify and hashlib.md5(data).hexdigest() != md5:
                    bad.append("%s: bytes differ from the manifest" % rel)
            elif node["size"] != size:
                bad.append("%s: size differs from the manifest" % rel)
            elif verify and (verify_max is None or size <= verify_max):
                if _md5_node(reader, node) != md5:
                    bad.append("%s: bytes differ from the manifest" % rel)
            if i % 200 == 0:
                log("  %d/%d files" % (i, len(files)))
    if bad:
        raise ValueError("%s is not consistent with its own manifest "
                         "(%d file(s)), e.g. %s"
                         % (card_path, len(bad), bad[0]))
    release = {
        "folder": folder,
        "name": folder_name(folder),
        "version": probe["version"] or "",
        "edition": probe["edition"] or "",
        "card": os.path.basename(card_path),
        "files": {rel: [size, md5[:FILE_DIGITS]]
                  for rel, (size, md5) in sorted(files.items())},
        "pictures": "".join(sorted(pictures)),
    }
    return probe["sidx_name"].lower(), release


# ---------------------------------------------------------------------------
# Checking a card
# ---------------------------------------------------------------------------

def _scene_of(path, scene_dirs):
    d = path.rsplit("/", 1)[0] if "/" in path else ""
    while d:
        if d in scene_dirs:
            return d
        d = d.rsplit("/", 1)[0] if "/" in d else ""
    return None


def diff_manifest(release, card_files, video_paths=(), radium_reader=None):
    """What a card's manifest (``{path: (size, md5)}``) changes from the
    official *release*.

    Returns ``{"scenes", "pictures", "videos", "sounds", "music", "program",
    "other", "added", "deleted", "changed"}``: counts of changed scene
    folders, pictures (distinct radium pictures not in the release's stock
    set, plus added or changed picture files), videos, music banks and other
    files; ``sounds`` and ``program`` are True when the packed sound bank /
    game program differ; ``added`` / ``deleted`` count files the card has
    that the release doesn't and the other way round; ``changed`` is every
    path that differs from stock (added, deleted or modified), sorted.

    *radium_reader*, when given, is called with a changed ``scene.radium``
    path and returns its bytes, so the pictures inside it can be counted one
    by one; without it each changed radium counts as one picture change."""
    stock = release.get("files") or {}
    card = {p: (int(s), m[:FILE_DIGITS]) for p, (s, m) in card_files.items()}
    stock_t = {p: (int(v[0]), v[1]) for p, v in stock.items()}
    added = sorted(p for p in card if p not in stock_t)
    deleted = sorted(p for p in stock_t if p not in card)
    modified = sorted(p for p in card if p in stock_t and card[p] != stock_t[p])
    scene_dirs = {p[:-len(_SCENE)] for p in list(card) + list(stock_t)
                  if p.endswith(_SCENE)}
    videos = set(v.lstrip("/") for v in video_paths)
    stock_pics = picture_set(release)
    out = {"scenes": 0, "pictures": 0, "videos": 0, "sounds": False,
           "music": 0, "program": False, "other": 0,
           "added": len(added), "deleted": len(deleted),
           "changed": sorted(added + deleted + modified)}
    changed_scenes = {s for s in (_scene_of(p, scene_dirs) for p in deleted)
                      if s is not None}
    new_pics = set()
    for p in added + modified:
        base = p.rsplit("/", 1)[-1]
        scene = _scene_of(p, scene_dirs)
        if scene is not None:
            changed_scenes.add(scene)
        if p.endswith("/image.bin"):
            out["sounds"] = True
        elif base.startswith("image-sc") and base.endswith(".bin"):
            out["music"] += 1
        elif base == "game" and p.count("/") == 1:
            out["program"] = True
        elif p in videos:
            out["videos"] += 1
        elif p.endswith(_SCENE):
            try:
                if radium_reader is None:
                    raise LookupError
                new_pics |= radium_pictures(radium_reader(p)) - stock_pics
            except Exception:                             # noqa: BLE001
                new_pics.add(p)
        elif scene is not None or p.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".dds")):
            out["pictures"] += 1
        else:
            out["other"] += 1
    out["pictures"] += len(new_pics)
    out["scenes"] = len(changed_scenes)
    return out


def check_card(card_path, table=None):
    """Is the card at *card_path* an official Stern release?

    One metadata walk of the card's data partition (the walk the Image Info
    probe does) plus its ``.sidx``; see :func:`check_walked` for the
    answer's shape."""
    from .explorer import CardImage
    from .info import _walk_partition
    try:
        with CardImage(card_path) as card:
            parts = [pt for pt in card.partitions() if pt.browsable]
            parts.sort(key=lambda pt: pt.size, reverse=True)
            for pt in parts:
                reader = card.reader(pt.index)
                found = _walk_partition(reader)
                if found["sidx_node"] is not None:
                    return check_walked(reader, found, table)
    except Exception as e:                                # noqa: BLE001
        return _unreadable("Could not read the card (%s)." % e)
    return check_walked(None, {"sidx_node": None}, table)


def _unreadable(text, sidx_name=""):
    return {"status": "unreadable", "label": "", "diff": None,
            "sidx": sidx_name, "text": text}


def check_walked(reader, found, table=None):
    """The stock verdict for a partition already walked by
    ``info._walk_partition`` (*found*), read through *reader*.

    Returns a dict: ``status`` is ``"official"`` (every indexed file matches
    the release Stern shipped), ``"modified"`` (it names an official release
    but files differ -- ``diff`` holds :func:`diff_manifest`'s counts),
    ``"unknown"`` (a release the table has no record of) or ``"unreadable"``
    (no manifest).  ``label`` is the release ("Godzilla LE 1.16") and
    ``text`` the one line the app shows."""
    node = found.get("sidx_node")
    if reader is None or node is None:
        return _unreadable("No Stern validation manifest on this card, so it "
                           "can't be checked against the official release.")
    sidx_name = os.path.basename(found.get("sidx_path") or "")
    try:
        files = sidx_mod.manifest_files(reader.read_file_bytes(node))
    except Exception:                                     # noqa: BLE001
        files = {}
    if not files:
        return _unreadable("The card's validation manifest can't be read, so "
                           "it can't be checked against the official "
                           "release.", sidx_name)
    table = load_table() if table is None else table
    release = release_for(sidx_name, table)
    if release is None:
        return {"status": "unknown", "label": "", "diff": None,
                "sidx": sidx_name,
                "text": "%s is not a release PAD has an official record of, "
                        "so it can't be checked against stock." % sidx_name}
    nodes = {}

    def read_radium(rel):
        if not nodes:
            for fp, _i, nd in reader.iter_regular_files(min_size=1,
                                                        max_depth=20):
                if fp.endswith(_SCENE):
                    nodes[fp.lstrip("/")] = nd
        return reader.read_file_bytes(nodes[rel])

    label = release_label(release)
    diff = diff_manifest(release, files, found.get("video_paths") or (),
                         radium_reader=read_radium)
    status = "official" if not diff["changed"] else "modified"
    return {"status": status, "label": label, "diff": diff,
            "sidx": sidx_name, "text": describe(status, label, diff)}


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def change_words(diff):
    """``["3 scenes", "12 pictures", "the sound bank"]`` for a diff."""
    bits = []
    if diff.get("scenes"):
        bits.append(_plural(diff["scenes"], "scene"))
    if diff.get("pictures"):
        bits.append(_plural(diff["pictures"], "picture"))
    if diff.get("videos"):
        bits.append(_plural(diff["videos"], "video"))
    if diff.get("sounds"):
        bits.append("the sound bank")
    if diff.get("music"):
        bits.append(_plural(diff["music"], "music bank"))
    if diff.get("program"):
        bits.append("the game program")
    if diff.get("other"):
        bits.append(_plural(diff["other"], "other file"))
    if diff.get("deleted"):
        bits.append("%s removed" % _plural(diff["deleted"], "file"))
    return bits


def describe(status, label, diff):
    """The one line: ``"Official Godzilla LE 1.16 - ..."`` or ``"Godzilla
    LE 1.16, modified: differs from the official card in 3 scenes, 12
    pictures, the sound bank."``."""
    if status == "official":
        return "Official %s - every file matches the card Stern released."             % label
    bits = change_words(diff or {})
    if not bits:
        bits = [_plural(len((diff or {}).get("changed") or ()), "file")]
    return "%s, modified: differs from the official card in %s."         % (label, ", ".join(bits))


# ---------------------------------------------------------------------------
# Checking a project folder (its pictures carry their own digests)
# ---------------------------------------------------------------------------

def project_pictures(assets_dir):
    """``(game_folder, digests)`` for the radium pictures a Spike 2 extract
    named by their digest (``images/scene_textures/radium_images.txt``), or
    ``None`` when the project has no such manifest."""
    path = os.path.join(assets_dir, "images", "scene_textures",
                        "radium_images.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    out = set()
    folder = ""
    for line in lines:
        if not line or line.startswith("#"):
            continue
        cols = line.split("	")
        if not folder and len(cols) > 1:
            folder = cols[1].lstrip("/").split("/", 1)[0]
        stem = os.path.splitext(cols[0].rsplit("/", 1)[-1])[0]
        tail = stem.rsplit("_", 1)[-1]
        if len(tail) == PICTURE_DIGITS and all(
                c in "0123456789abcdef" for c in tail):
            out.add(tail)
    return folder, out


def sidx_for(folder, version):
    """The ``.sidx`` name of *folder* at *version*: ``("godzilla_le",
    "1.16.0")`` -> ``"godzilla_le-1_16_0.sidx"``."""
    return "%s-%s.sidx" % (folder, (version or "").replace(".", "_"))


def check_project(assets_dir, table=None):
    """Was the project at *assets_dir* extracted from the official card?

    The verdict the extract stamped from the card's own manifest (it covers
    sounds, videos and the program too) is the answer when the project has
    one.  Older projects are answered from their pictures: an extract names
    each radium picture by its digest ON THE CARD it came from, so a picture
    the official release doesn't have came off a modified card.

    Returns ``{"status", "label", "text"}`` -- ``status`` ``"official"``,
    ``"modified"`` or ``"unknown"`` (nothing to go on: not a Spike 2 extract,
    or a release PAD has no record of)."""
    from ...core.extract_source import read_extract_source
    unknown = {"status": "unknown", "label": "", "text": ""}
    rec = read_extract_source(assets_dir) or {}
    stamped = rec.get("stock")
    if isinstance(stamped, dict) and stamped.get("status") in (
            "official", "modified"):
        return {"status": stamped["status"],
                "label": stamped.get("label") or "",
                "text": stamped.get("text") or ""}
    got = project_pictures(assets_dir)
    if got is None or not got[0] or not got[1]:
        return unknown
    folder, pics = got
    table = load_table() if table is None else table
    version = rec.get("card_version") or ""
    release = release_for(sidx_for(folder, version), table) if version         else None
    if release is None:
        # No version stamp: only an exact match can be named.
        release = next((r for r in table.values()
                        if r.get("folder") == folder
                        and pics <= picture_set(r)), None)
        if release is None:
            return unknown
    label = release_label(release)
    extra = len(pics - picture_set(release))
    if not extra:
        return {"status": "official", "label": label,
                "text": "Extracted from the official %s card." % label}
    return {"status": "modified", "label": label,
            "text": "Extracted from a modified %s card: %s." % (
                label, "1 picture is not the official one" if extra == 1
                else "%d pictures are not the official ones" % extra)}
