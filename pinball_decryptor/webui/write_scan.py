"""The Write tab's change list, Tk-free.

What the Tk window did in ``_scan_write_preview`` / ``_add_pending_*_rows`` /
``_current_write_fingerprint`` (gui/main_window.py), without widgets: the MD5
walk of a project folder against its ``.checksums.md5`` baseline, and the
"Pending (...)" rows for everything staged but not yet on disk (Replace
Audio / Video / Images assignments, text, text colour, text layout, the
project's modes and the game's own modes).  Every row is
``(file, type, status, tag)`` exactly as the Tk tree held it.

The plugin and core functions the Tk code called are called here too; only
the widget plumbing is gone.
"""

import os
import re

from ..core.checksums import NON_ASSET_DIRS, TRACKING_SIDECARS
from ..core.staged_originals import ORIG_DIR

#: Write-tab status strings for pending on-screen-text edits (main_window.py).
PENDING_TEXT = "Pending (Replace Text)"
PENDING_TEXT_GROWS = "Pending (text, game program grows)"
PENDING_TEXT_GROWS_SCENE = "Pending (text, scene grows)"
PENDING_TEXT_GROW_OFF = "Pending (Replace Text — too long, grow is off)"
TEXT_STATUSES = (PENDING_TEXT, PENDING_TEXT_GROWS, PENDING_TEXT_GROWS_SCENE,
                 PENDING_TEXT_GROW_OFF)
PENDING_MODE = "Pending (Modes)"
PENDING_STOCK_MODES = "Pending (game's own modes)"

_MD5SUM_RE = re.compile(r'^([a-f0-9]{32})\s+\*?(.+)$')
_MD5_RE = re.compile(r'[a-f0-9]{32}')


# ----------------------------------------------------------------------
# text rows (MainWindow._text_row_* classmethods)
# ----------------------------------------------------------------------
def _text_byte_len(s):
    return len(s.encode("latin1", "replace"))


def _text_row_len(r, s):
    if r.get("budget"):
        s = s.replace("\\n", "\n")
    return _text_byte_len(s)


def _text_row_is_scene(r):
    return (r.get("path") or "").lower().endswith(".radium")


def _text_row_grows(r):
    if _text_row_is_scene(r):
        return True
    if r.get("fixed"):
        return False
    return True


def _text_row_outgrows(r, s):
    return _text_row_len(r, s) > _text_row_len(r, r["original"])


def pending_text_status(row, grow_on=True):
    """The status a pending text edit shows on the Write tab."""
    rep = row.get("replacement") or ""
    if _text_row_grows(row) and rep and _text_row_outgrows(row, rep):
        if not grow_on:
            return PENDING_TEXT_GROW_OFF
        return (PENDING_TEXT_GROWS_SCENE if _text_row_is_scene(row)
                else PENDING_TEXT_GROWS)
    return PENDING_TEXT


def text_rows(assets_path, grow_on):
    """strings.tsv edits as pending rows."""
    from ..core import text_manifest
    try:
        rows = text_manifest.load(assets_path)
    except Exception:                                   # noqa: BLE001
        rows = []
    out = []
    for row in rows:
        rep = row.get("replacement") or ""
        if not rep or rep == row["original"]:
            continue
        out.append(("%s  →  %s" % (row["original"], rep), "text",
                    pending_text_status(row, grow_on), "pending"))
    return out


# ----------------------------------------------------------------------
# the MD5 walk
# ----------------------------------------------------------------------
def read_baseline(checksums_file):
    """``{rel: md5}`` from a ``.checksums.md5`` (md5sum or BOF flavour).
    Raises OSError when the file cannot be read."""
    saved = {}
    with open(checksums_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _MD5SUM_RE.match(line)
            if m:
                md5_val = m.group(1)
                fp = m.group(2)
            elif "\t" in line:
                fp, md5_val = line.rsplit("\t", 1)
                md5_val = md5_val.strip()
                if not _MD5_RE.fullmatch(md5_val):
                    continue
            else:
                continue
            if fp.startswith("./"):
                fp = fp[2:]
            saved[fp.replace("\\", "/")] = md5_val
    return saved


def walk_changes(assets_path, saved, *, hide_imported_cache, current,
                 on_found=None):
    """Files under *assets_path* whose MD5 differs from *saved*:
    ``[(rel, ext)]``, or None when *current()* went False mid-walk (a newer
    scan or a cancel superseded this one).  Uses the size+mtime hash cache;
    the cache is written back only when the walk changed it (a scan of an
    unchanged folder leaves the folder untouched)."""
    import json
    from ..core import hashcache
    hcache = hashcache.load(assets_path)
    try:
        before = json.dumps(hcache, sort_keys=True)
    except (TypeError, ValueError):
        before = None

    def _save():
        try:
            after = json.dumps(hcache, sort_keys=True)
        except (TypeError, ValueError):
            after = None
        # a capture run (PAD_UI_CAPTURE) walks the user's REAL project:
        # it must leave the folder exactly as it found it
        if os.environ.get("PAD_UI_CAPTURE"):
            return
        if after is None or after != before:
            hashcache.save(assets_path, hcache)

    changed = []
    for root_dir, dirs, files in os.walk(assets_path):
        dirs[:] = [d for d in dirs
                   if d != ORIG_DIR
                   and not (root_dir == assets_path
                            and d in NON_ASSET_DIRS)]
        for name in files:
            if not current():
                return None
            if (name.startswith(".")
                    or name == "fl_decrypted.dat"
                    or name.endswith(".img")
                    or name in TRACKING_SIDECARS):
                continue
            full = os.path.join(root_dir, name)
            rel = os.path.relpath(full, assets_path).replace("\\", "/")
            if rel not in saved:
                continue
            if hide_imported_cache and rel.startswith("pck/.godot/imported/"):
                continue
            digest = hashcache.md5_for(full, rel, hcache)
            if digest is None or digest == saved[rel]:
                continue
            if not current():
                _save()
                return None
            ext = os.path.splitext(name)[1].lstrip(".") or "?"
            changed.append((rel, ext))
            if on_found is not None:
                on_found(len(changed))
    _save()
    return changed


# ----------------------------------------------------------------------
# pending rows (MainWindow._add_pending_preview_rows and friends)
# ----------------------------------------------------------------------
def _window_getter(window, name):
    """A tab's export, or None when no tab provides it (never a stand-in)."""
    exports = getattr(window, "_exports", {}) or {}
    svc = exports.get(name)
    if svc is not None:
        return getattr(svc, name, None)
    # an attribute a tab keeps without exporting it (the Replace tabs'
    # changed-on-disk sets, which only this fingerprint reads)
    for svc in getattr(window, "tabs", ()) or ():
        if hasattr(svc, name):
            return getattr(svc, name, None)
    return None


def modes_preview_on(mfr):
    if mfr is None or not getattr(mfr.capabilities, "modes", False):
        return False
    from ..core import preview
    return preview.enabled("modes")


def pending_rows(window, mfr, assets_path, *, grow_on, direct):
    """Every staged change the MD5 walk cannot see, as rows."""
    rows = []
    got = {}
    for key, name, label in (
            ("audio", "pending_audio_assignments", "Replace Audio"),
            ("video", "pending_video_assignments", "Replace Video"),
            ("image", "pending_image_assignments", "Replace Images")):
        getter = _window_getter(window, name)
        try:
            pend = getter(assets_path) if getter is not None else None
        except Exception:                               # noqa: BLE001
            pend = None
        got[key] = bool(pend)
        if not pend:
            continue
        assignments = pend[1]
        for rel in sorted(assignments):
            ext = os.path.splitext(rel)[1].lstrip(".") or "?"
            rows.append((rel, ext, "Pending (%s)" % label, "pending"))
    if assets_path and not all(got.values()):
        from ..core import staged_changes
        try:
            saved = staged_changes.load(assets_path)
        except Exception:                               # noqa: BLE001
            saved = {}
        for key, cap, label in (
                ("audio", "replace_audio", "Replace Audio"),
                ("video", "replace_video", "Replace Video"),
                ("image", "replace_image", "Replace Images")):
            if got.get(key) or mfr is None or not getattr(
                    mfr.capabilities, cap, False):
                continue
            for rel, repl in sorted((saved.get(key) or {}).items()):
                if not (isinstance(repl, str) and os.path.isfile(repl)
                        and os.path.isfile(os.path.join(
                            assets_path, rel.replace("/", os.sep)))):
                    continue
                ext = os.path.splitext(rel)[1].lstrip(".") or "?"
                rows.append((rel, ext, "Pending (%s)" % label, "pending"))
    if mfr is not None and getattr(mfr.capabilities, "replace_text", False):
        rows.extend(text_rows(assets_path, grow_on))
        try:
            from ..plugins.stern import text_colors
            recolored = text_colors.load(assets_path)
        except Exception:                               # noqa: BLE001
            recolored = {}
        for _path, per_text in recolored.items():
            for text, (src, dst) in per_text.items():
                rows.append(("%s  —  %s → %s" % (text, text_colors.to_hex(src),
                                                  text_colors.to_hex(dst)),
                             "text", "Pending (text colour)", "pending"))
        try:
            from ..plugins.stern import text_layout
            relaid = text_layout.load(assets_path)
        except Exception:                               # noqa: BLE001
            relaid = {}
        for _path, per_text in relaid.items():
            for text, edit in per_text.items():
                rows.append(("%s  —  %s" % (text, text_layout.describe(edit)),
                             "text", "Pending (text layout)", "pending"))
    rows.extend(mode_rows(mfr, assets_path, direct=direct))
    rows.extend(stock_mode_rows(mfr, assets_path))
    return rows


def stock_mode_rows(mfr, assets_path):
    if not assets_path or not modes_preview_on(mfr):
        return []
    try:
        from ..plugins.stern import stock_modes
        build = stock_modes.table_for_project(assets_path)
        edits = stock_modes.staged_edits(assets_path, build)
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for e in edits:
        num = e["number"]
        label = (build.row_label(num) if build is not None else num.label)
        other = e["staged_for"] not in (None, build.id if build else None)
        out.append((
            "%s %s: %s -> %s%s" % (
                e["mode"], label.lower(), e.get("stock_text") or format(e["stock"], ","),
                e.get("new_text") or format(e["new"], ","),
                "  (staged for %s, not written)" % e["staged_for"]
                if other else ""),
            "setting" if num.is_adjustment else "program",
            PENDING_STOCK_MODES, "pending"))
    return out


def mode_rows(mfr, assets_path, *, direct):
    if not assets_path or not modes_preview_on(mfr):
        return []
    try:
        from ..plugins.stern import mode_write
        modes = mode_write.project_modes(assets_path)
        lines = mode_write.pending_lines(assets_path, modes)
    except Exception as e:                              # noqa: BLE001
        return [("Modes — %s" % e, "mode", PENDING_MODE, "pending")]
    dest_device = bool(getattr(mfr.capabilities, "direct_ssd", False)
                       and direct)
    if modes and not mode_write.enabled():
        lines = ["%s — left out of the build (%s=0)"
                 % (spec.name, mode_write.GATE_ENV) for _s, spec in modes]
    elif modes and dest_device:
        lines = ["%s — left out of a Direct-SD write: it cannot add files to "
                 "the card (build an image file to carry the modes)"
                 % spec.name for _s, spec in modes]
    elif modes and mode_write.host_refusal():
        lines = ["%s — left out of this Write: %s"
                 % (spec.name, mode_write.host_refusal())
                 for _s, spec in modes]
    code = mode_write.code_modes(assets_path)
    if code:
        why = ""
        if not mode_write.enabled():
            why = "the modes gate is off (%s=0)" % mode_write.GATE_ENV
        elif dest_device:
            why = ("a Direct-SD write cannot add files to the card (build an "
                   "image file to carry the modes)")
        elif mode_write.host_refusal():
            why = mode_write.host_refusal()
        if why:
            lines = [ln for ln in lines if "(code mode)" not in ln]
            lines = list(lines) + ["Modes — %s"
                                   % mode_write.code_modes_note(code, why)]
    return [(line, "mode", PENDING_MODE, "pending") for line in lines]


# ----------------------------------------------------------------------
# the fingerprint (MainWindow._current_write_fingerprint)
# ----------------------------------------------------------------------
def _modes_fingerprint(assets_path):
    files = []
    try:
        from ..plugins.stern import mode_project, mode_write
        root = mode_project.modes_dir(assets_path) if assets_path else ""
        if root and os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames.sort()
                for name in sorted(filenames):
                    p = os.path.join(dirpath, name)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    files.append((os.path.relpath(p, root), st.st_mtime_ns,
                                  st.st_size))
        gates = (mode_write.enabled(), mode_write.sound_enabled(),
                 mode_write.preview_on())
    except Exception:                                   # noqa: BLE001
        return None
    return (tuple(files), gates)


def fingerprint(window, assets_path, epoch, grow_on):
    """Cheap equality summary of everything that can change the list."""
    parts = [assets_path, epoch, grow_on]
    for name in ("pending_audio_assignments", "pending_video_assignments",
                 "pending_image_assignments"):
        getter = _window_getter(window, name)
        try:
            pend = getter(assets_path) if getter is not None else None
            parts.append(tuple(sorted((pend[1] or {}).items()))
                         if pend else ())
        except Exception:                               # noqa: BLE001
            parts.append(None)
    for name in ("_audio_changed_on_disk", "_video_changed_on_disk",
                 "_image_changed_on_disk"):
        val = _window_getter(window, name)
        parts.append(tuple(sorted(val)) if val else ())
    try:
        from ..core import text_manifest
        changed = text_manifest.changed(assets_path)
        parts.append(sorted((p, list(pairs)) for p, pairs in changed.items()))
    except Exception:                                   # noqa: BLE001
        parts.append(None)
    try:
        from ..plugins.stern import text_colors
        parts.append(sorted((p, sorted(per.items()))
                            for p, per in text_colors.load(assets_path).items()))
    except Exception:                                   # noqa: BLE001
        parts.append(None)
    try:
        from ..plugins.stern import text_layout
        parts.append(sorted(
            (p, sorted((t, sorted(e.items())) for t, e in per.items()))
            for p, per in text_layout.load(assets_path).items()))
    except Exception:                                   # noqa: BLE001
        parts.append(None)
    parts.append(_modes_fingerprint(assets_path))
    try:
        from ..plugins.stern import stock_modes
        parts.append(stock_modes.fingerprint(assets_path))
    except Exception:                                   # noqa: BLE001
        parts.append(None)
    return repr(parts)


def find_checksums_ancestor(path, max_levels=3):
    current = path
    for _ in range(max_levels):
        parent = os.path.dirname(current)
        if not parent or parent == current:
            return None
        if os.path.isfile(os.path.join(parent, ".checksums.md5")):
            return parent
        current = parent
    return None
