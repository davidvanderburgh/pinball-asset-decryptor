"""PAD-1408: a maker's whole game as one file another owner loads.

A shared game is a zip holding everything a project changed, in the formats PAD already
loads, side by side:

``pad_game.json``     the manifest (:data:`GAME_MANIFEST`, kind :data:`GAME_KIND`)
``mod_pack.zip``      the project's Mod Pack (:func:`.modpack.export_mod_pack`): every
                      changed file, the settings, high scores, music modes, random clips,
                      attract items and the files replaced on the card image
``modes.zip``         a file of its modes (the Modes tab's Save to a file, PAD-1050): each
                      mode's folder with its sources, pictures, clips and sounds, so its
                      saved-progress layout (PAD-1402) and own sounds come with it
``modes_root/<f>``    the loose files of the project's ``modes`` folder (the counts-as rows,
                      the rules sheet...)
``code/<key>.so``     the maker's compiled code modes (the object a Write puts on the card
                      as ``mode.so``), kept under :func:`.mode_write.code_object_key` so the
                      owner's Write of the same sources on the same PAD uses the very object
                      the maker built and played; any other owner's PAD compiles the sources

No file of the manufacturer's goes in. A member whose bytes are one of the maker's card's
own files (a stock clip used for a mode, a stock sound copied over another slot) is left
out and only named (``stock`` in the manifest: where it goes, the card file it is, its
MD5); a load takes those bytes from the owner's OWN extract of their card. A file the
maker changed is the maker's own work and travels, as in a Mod Pack.

The owner loads it into the project of their own card (:func:`import_game`) and writes it
to their card, or builds it as an Edition beside the original on the Multi-boot tab, the
way they write anything else.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

from . import modpack
from . import staged_originals
from .checksums import NON_ASSET_DIRS, read_baseline_any

GAME_MANIFEST = "pad_game.json"
GAME_KIND = "pad-game"
FORMAT = 1
PACK_MEMBER = "mod_pack.zip"
MODES_MEMBER = "modes.zip"
MODES_ROOT = "modes_root/"
CODE_DIR = "code/"
#: where a project keeps what it loaded from a shared game: ``game.json`` (which game, the
#: modes it brought) and ``code/<key>.so`` (the maker's objects, for the next Write)
PROJECT_DIR = ".pad_game"
PROJECT_RECORD = "game.json"
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_ARCHES = ("arm", "a64")


class GameFileError(ValueError):
    """A shared game that cannot be made or loaded, in words for the owner."""


def _say(log_cb):
    return log_cb or (lambda *a, **k: None)


def _md5_stream(read_chunks):
    h = hashlib.md5()
    for chunk in read_chunks:
        h.update(chunk)
    return h.hexdigest()


def _zip_member_md5(zf, info):
    with zf.open(info) as f:
        return _md5_stream(iter(lambda: f.read(1 << 20), b""))


def _file_md5(path):
    with open(path, "rb") as f:
        return _md5_stream(iter(lambda: f.read(1 << 20), b""))


#: top folders of a project that hold the maker's own work, never the card's files, even when
#: a baseline taken after they were made lists them (the baseline walk keeps ``modes``)
_OWN_TOPS = frozenset(NON_ASSET_DIRS) | {"modes", "Backups", PROJECT_DIR}


def _card_file(rel):
    top = rel.replace("\\", "/").split("/", 1)[0]
    return top not in _OWN_TOPS and not top.startswith(".")


def stock_index(folder):
    """``{md5: [rel, ...]}`` of the card's own files: the extract's baseline, without the
    project's own folders (:data:`_OWN_TOPS`)."""
    out = {}
    for rel, md5 in read_baseline_any(folder).items():
        if _card_file(rel):
            out.setdefault(str(md5).lower(), []).append(rel)
    return out


def _strip_stock(src_zip, dst_zip, stock, part, keep=()):
    """Copy ``src_zip`` to ``dst_zip`` without any member whose bytes are a stock file
    (``stock``: :func:`stock_index`); ``keep`` names members always copied (manifests).
    Returns the left-out members as ``[{"part", "member", "card", "md5", "size"}]``."""
    refs = []
    with zipfile.ZipFile(src_zip) as zin, zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.is_dir():
                continue
            if info.filename not in keep and info.file_size:
                md5 = _zip_member_md5(zin, info)
                if md5 in stock:
                    refs.append({"part": part, "member": info.filename, "card": stock[md5][0],
                                 "md5": md5, "size": info.file_size})
                    continue
            with zin.open(info) as src, zout.open(_copy_info(info), "w") as out:
                shutil.copyfileobj(src, out, 1 << 20)
    return refs


def _copy_info(info):
    out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    out.compress_type = info.compress_type
    out.external_attr = info.external_attr
    out.file_size = info.file_size
    return out


def _owner_copy(project, md5, wanted, owner_stock):
    """A path in the owner's project holding the stock bytes ``md5``: the card file
    ``wanted`` names first, then any other file of the owner's card with those bytes; its
    untouched original (``.orig``) when the owner changed it. None when they have none."""
    rels = list(owner_stock.get(md5, ()))
    if wanted in rels:
        rels.remove(wanted)
        rels.insert(0, wanted)
    for rel in rels:
        for path in (staged_originals.snapshot_path(project, rel),
                     os.path.join(project, *rel.split("/"))):
            try:
                if path and os.path.isfile(path) and _file_md5(path) == md5:
                    return path
            except OSError:
                continue
    return None


def _restore_stock(game, member, dst_zip, refs, project, owner_stock, missing):
    """Write the inner zip ``member`` of the game ``game`` (an open ZipFile) to ``dst_zip``
    with each stock file ``refs`` names put back from the owner's own card; the ones the
    owner's card does not have go on ``missing``."""
    with game.open(member) as raw, tempfile.TemporaryDirectory(prefix="pad-game-") as tmp:
        inner = os.path.join(tmp, "inner.zip")
        with open(inner, "wb") as f:
            shutil.copyfileobj(raw, f, 1 << 20)
        with zipfile.ZipFile(inner) as zin, \
                zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if not info.is_dir():
                    with zin.open(info) as src, zout.open(_copy_info(info), "w") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
            for ref in refs:
                path = _owner_copy(project, ref["md5"], ref.get("card"), owner_stock)
                if path is None:
                    missing.append(ref)
                    continue
                zout.write(path, ref["member"], compress_type=zipfile.ZIP_STORED)


# ---- what a file is ----------------------------------------------------------------------

def _read_head(zf):
    try:
        head = json.loads(zf.read(GAME_MANIFEST).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError):
        return None
    return head if isinstance(head, dict) and head.get("kind") == GAME_KIND else None


def game_file_about(path):
    """Is ``path`` a shared game? Its manifest when it is (``name``, ``made_for``,
    ``modes``, ``files``...), else None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            return _read_head(zf)
    except (OSError, zipfile.BadZipFile):
        return None


def game_file_words(head):
    """One sentence naming what a shared game holds."""
    bits = []
    n = int(head.get("files") or 0)
    if n:
        bits.append("%d changed file%s" % (n, "" if n == 1 else "s"))
    modes = [m for m in head.get("modes") or () if isinstance(m, str)]
    if modes:
        shown = ", ".join(modes[:6]) + (" and %d more" % (len(modes) - 6) if len(modes) > 6 else "")
        bits.append("%d mode%s (%s)" % (len(modes), "" if len(modes) == 1 else "s", shown))
    if head.get("objects"):
        bits.append("the maker's compiled code modes")
    held = ", ".join(bits[:-1]) + " and " + bits[-1] if len(bits) > 1 else (bits[0] if bits else "nothing")
    made = head.get("made_for") or {}
    return "%s holds %s%s." % (
        ("\"%s\"" % head["name"]) if head.get("name") else "This shared game", held,
        ", made on %s" % made["label"] if isinstance(made, dict) and made.get("label") else "")


# ---- making one --------------------------------------------------------------------------

def _stern_modes():
    from ..plugins.stern import mode_project as MP
    return MP


def _mode_names(MP, project, slugs):
    """Each mode's name as the Modes tab lists it: a code mode's is its MODE_NAME."""
    from ..plugins.stern import code_modes as CM
    specs = dict(MP.list_modes(project)[0])
    out = []
    for slug in slugs:
        name = getattr(specs.get(slug), "name", "") or ""
        if not name:
            try:
                name = CM.load(project, slug).name
            except Exception:                                    # noqa: BLE001
                name = ""
        out.append(name or slug)
    return out


def _code_objects(project, log):
    """``[(key, arch, path)]`` of the compiled object the project's code modes make, for
    each ARM it is kept for; compiled now (for Spike 2's 32-bit ARM) when none is kept and
    the app's Linux can. ``[]`` with no code modes."""
    from ..plugins.stern import mode_write as MW
    from ..plugins.stern import code_modes as CM
    try:
        code = MW.code_mode_list(project)
    except Exception as e:                                       # noqa: BLE001
        log("Shared game: the code modes could not be listed (%s), so their compiled object "
            "is not in the file; the owner's PAD compiles them." % e, "warning")
        return []
    if not code:
        return []
    sources = [CM.source_path(project, s) for s, _c in code]
    got = []
    for arch in _ARCHES:
        try:
            key = MW.code_object_key(sources, arch)
        except OSError:
            continue
        path = os.path.join(MW.code_cache_dir(), key + ".so")
        if os.path.isfile(path) and os.path.getsize(path):
            got.append((key, arch, path))
    if got:
        return got
    tmp = tempfile.mkdtemp(prefix="pad-game-code-")
    try:
        MW.compile_code_object(sources, os.path.join(tmp, "mode.so"), log=log)
        key = MW.code_object_key(sources, "arm")
        path = os.path.join(MW.code_cache_dir(), key + ".so")
        if os.path.isfile(path):
            return [(key, "arm", path)]
    except Exception as e:                                       # noqa: BLE001
        log("Shared game: the code modes did not compile here (%s), so the file carries their "
            "sources only; the owner's PAD compiles them." % e, "warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return []


def export_game(project, zip_path, name="", log_cb=None, progress_cb=None):
    """Write the whole game of ``project`` to ``zip_path`` (see the module's words).
    Returns the manifest written. Raises :class:`GameFileError` when there is nothing to
    share or the project has no extract baseline (without it no stock file can be told
    from the maker's own, so none could be kept out)."""
    log = _say(log_cb)
    stock = stock_index(project)
    if not os.path.isfile(os.path.join(project, modpack.CHECKSUMS_FILE)):
        raise GameFileError("This project has no extract of its card (%s is missing), so PAD "
                            "cannot tell the card's own files from yours and keep them out of "
                            "the file. Extract the card into it first." % modpack.CHECKSUMS_FILE)
    head = {"format": FORMAT, "kind": GAME_KIND, "name": (name or "").strip(),
            "made": time.strftime("%Y-%m-%d %H:%M"), "files": 0, "modes": [], "mode_slugs": [],
            "modes_root": [], "objects": [], "stock": []}
    try:
        from .. import __version__
        head["pad"] = __version__
    except ImportError:
        pass
    tmp = tempfile.mkdtemp(prefix="pad-game-")
    try:
        parts = []                                         # (member, path)
        # the Mod Pack: every changed file, settings, music modes, clips, attract items
        raw = os.path.join(tmp, "pack_raw.zip")
        try:
            n, _p = modpack.export_mod_pack(project, raw, log_cb=log_cb, progress_cb=progress_cb)
        except (ValueError, FileNotFoundError) as e:       # nothing changed / an empty baseline
            log("Shared game: no changed file of the card to carry (%s)." % e, "info")
        else:
            pack = os.path.join(tmp, PACK_MEMBER)
            head["stock"] += _strip_stock(raw, pack, stock, PACK_MEMBER,
                                          keep=(modpack.MANIFEST_NAME,))
            head["files"] = n
            parts.append((PACK_MEMBER, pack))
            try:
                with zipfile.ZipFile(raw) as z:
                    pm = json.loads(z.read(modpack.MANIFEST_NAME).decode("utf-8"))
                head["made_for"] = {"label": pm.get("source_name") or "",
                                    "version": pm.get("version_hint") or ""}
            except (KeyError, ValueError, OSError):
                pass
        # the modes, their loose files and compiled code (Stern projects)
        modes_root = os.path.join(project, "modes")
        if os.path.isdir(modes_root):
            MP = _stern_modes()
            about = MP.card_about(project)
            if about:
                head["made_for"] = dict(head.get("made_for") or {}, **about)
            raw = os.path.join(tmp, "modes_raw.zip")
            try:
                slugs = MP.export_modes(project, raw, about=about)
            except MP.ModeProjectError:
                slugs = []
            if slugs:
                modes = os.path.join(tmp, MODES_MEMBER)
                head["stock"] += _strip_stock(raw, modes, stock, MODES_MEMBER,
                                              keep=(MP.SHARE_MANIFEST,))
                parts.append((MODES_MEMBER, modes))
                head["mode_slugs"] = list(slugs)
                head["modes"] = _mode_names(MP, project, slugs)
                for key, arch, path in _code_objects(project, log):
                    member = "%s%s.so" % (CODE_DIR, key)
                    head["objects"].append({"key": key, "arch": arch, "member": member,
                                            "size": os.path.getsize(path)})
                    parts.append((member, path))
            for leaf in sorted(os.listdir(modes_root)):
                path = os.path.join(modes_root, leaf)
                if os.path.isfile(path) and not leaf.endswith(".tmp") and not leaf.startswith("."):
                    head["modes_root"].append(leaf)
                    parts.append((MODES_ROOT + leaf, path))
        if not parts:
            raise GameFileError("This project has nothing to share yet: no changed file of the "
                                "card and no modes.")
        for member, path in parts:          # a loose mode file can be a stock one too
            if member.startswith(MODES_ROOT):
                md5 = _file_md5(path)
                if md5 in stock:
                    head["stock"].append({"part": "", "member": member, "card": stock[md5][0],
                                          "md5": md5, "size": os.path.getsize(path)})
        left = {r["member"] for r in head["stock"] if not r["part"]}
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(GAME_MANIFEST, json.dumps(head, indent=1))
            for member, path in parts:
                if member in left:
                    continue
                z.write(path, member, compress_type=zipfile.ZIP_STORED
                        if member.endswith(".zip") else zipfile.ZIP_DEFLATED)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if head["stock"]:
        log("Shared game: %d file(s) are the card's own, byte for byte, so they are not in the "
            "file; loading it takes them from the owner's own card." % len(head["stock"]), "info")
    log("Shared game: %s" % game_file_words(head), "success")
    return head


# ---- loading one -------------------------------------------------------------------------

def project_record(project):
    """What the project last loaded from a shared game (``{}`` when nothing)."""
    try:
        with open(os.path.join(project, PROJECT_DIR, PROJECT_RECORD), encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {}
    except (OSError, ValueError):
        return {}


def shared_object(project, key):
    """The maker's compiled object a shared game brought ``project`` for ``key``, or None."""
    if not project or not _KEY_RE.match(key or ""):
        return None
    path = os.path.join(project, PROJECT_DIR, "code", key + ".so")
    return path if os.path.isfile(path) and os.path.getsize(path) else None


def _safe_leaf(name):
    return (isinstance(name, str) and name and name == os.path.basename(name)
            and name not in (".", "..") and ":" not in name and "\\" not in name
            and not name.startswith("."))


def import_game(zip_path, project, log_cb=None, progress_cb=None):
    """Load the shared game ``zip_path`` into ``project`` (the owner's extract of their own
    card). Returns ``{"head", "applied", "skipped", "modes", "report", "objects", "missing",
    "mode_files"}``. A mode a load of the same game brought before is replaced, so a newer
    version of a game loads over the last; any other mode of the same folder name is kept
    beside it. Raises :class:`GameFileError` for a file that is not a shared game."""
    log = _say(log_cb)
    base = os.path.basename(zip_path)
    try:
        game = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile):
        raise GameFileError("%s is not a shared game saved by PAD" % base) from None
    with game, tempfile.TemporaryDirectory(prefix="pad-game-") as tmp:
        head = _read_head(game)
        if head is None:
            raise GameFileError("%s is not a shared game saved by PAD" % base)
        if int(head.get("format") or 1) > FORMAT:
            raise GameFileError("%s was saved by a newer PAD: update to load it" % base)
        names = set(game.namelist())
        owner_stock = stock_index(project)
        refs = [r for r in head.get("stock") or () if isinstance(r, dict)
                and isinstance(r.get("md5"), str) and isinstance(r.get("member"), str)]
        if refs and not owner_stock:
            raise GameFileError("This game takes %d file(s) from the owner's own card, and this "
                                "project has no extract of one. Load it into the project you "
                                "extracted your card into." % len(refs))
        missing, kept = [], []
        out = {"head": head, "applied": [], "skipped": [], "modes": [], "report": None,
               "objects": [], "missing": missing, "mode_files": []}
        # the Mod Pack part
        if PACK_MEMBER in names:
            pack = os.path.join(tmp, PACK_MEMBER)
            _restore_stock(game, PACK_MEMBER, pack,
                           [r for r in refs if r.get("part") == PACK_MEMBER],
                           project, owner_stock, missing)
            try:
                res = modpack.import_mod_pack(pack, project, log_cb=log_cb, progress_cb=progress_cb)
                out["applied"], out["skipped"] = res["applied"], res["skipped"]
            except ValueError as e:
                log("Shared game: none of its changed files are files of this card (%s)" % e,
                    "warning")
        # the modes part
        if MODES_MEMBER in names:
            MP = _stern_modes()
            modes = os.path.join(tmp, MODES_MEMBER)
            _restore_stock(game, MODES_MEMBER, modes,
                           [r for r in refs if r.get("part") == MODES_MEMBER],
                           project, owner_stock, missing)
            before = project_record(project)
            mine = set(before.get("mode_slugs") or ()) if (
                before.get("name") or "") == (head.get("name") or "") else set()
            conflicts, same = MP.share_conflicts(modes, project)
            replace = [c["slug"] for c in conflicts if c["slug"] in mine]
            kept = list(same)
            report = MP.import_modes(modes, project, replace=replace, skip=same)
            out["report"] = report
            out["modes"] = list(head.get("mode_slugs") or ())
            if report is not None:
                log("Shared game: modes: %s" % report.summary(), "info")
        # the loose files of the modes folder
        backup = os.path.join(project, "Backups", "shared game %s" % time.strftime("%Y-%m-%d %H%M%S"))
        for leaf in head.get("modes_root") or ():
            if not _safe_leaf(leaf):
                continue
            member = MODES_ROOT + leaf
            ref = next((r for r in refs if r["member"] == member), None)
            if member in names:
                data = game.read(member)
            elif ref is not None:
                src = _owner_copy(project, ref["md5"], ref.get("card"), owner_stock)
                if src is None:
                    missing.append(ref)
                    continue
                with open(src, "rb") as f:
                    data = f.read()
            else:
                continue
            dest = os.path.join(project, "modes", leaf)
            if os.path.isfile(dest):
                with open(dest, "rb") as f:
                    if f.read() == data:
                        continue
                os.makedirs(backup, exist_ok=True)
                shutil.copy2(dest, os.path.join(backup, leaf))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            out["mode_files"].append(leaf)
        # the maker's compiled code modes
        code_dir = os.path.join(project, PROJECT_DIR, "code")
        for obj in head.get("objects") or ():
            key = obj.get("key") if isinstance(obj, dict) else None
            member = "%s%s.so" % (CODE_DIR, key)
            if not _KEY_RE.match(key or "") or member not in names:
                continue
            data = game.read(member)
            if not data.startswith(b"\x7fELF"):
                log("Shared game: %s is not a compiled object, left out." % member, "warning")
                continue
            os.makedirs(code_dir, exist_ok=True)
            with open(os.path.join(code_dir, key + ".so"), "wb") as f:
                f.write(data)
            out["objects"].append(key)
        # remember the game, so a newer version of it replaces its modes
        os.makedirs(os.path.join(project, PROJECT_DIR), exist_ok=True)
        with open(os.path.join(project, PROJECT_DIR, PROJECT_RECORD), "w", encoding="utf-8") as f:
            json.dump({"name": head.get("name") or "", "made_for": head.get("made_for") or {},
                       "made": head.get("made") or "", "file": base,
                       "loaded": time.strftime("%Y-%m-%d %H:%M"),
                       "mode_slugs": sorted(set(kept) | {
                           m.new_slug for m in (out["report"].modes if out["report"] else ())
                           if m.new_slug})}, f, indent=1)
    if missing:
        log("Shared game: %d file(s) of the game are files of the maker's card that this card "
            "does not have, so they are left out: %s" % (
                len(missing), ", ".join(sorted({m.get("card") or m["member"] for m in missing})[:8])),
            "warning")
    return out
