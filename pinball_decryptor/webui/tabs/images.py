"""Replace Images tab.

A port of the Tk tab: ``gui/main_window.py`` ``_build_image_tab`` (9209-9431)
and the image methods it wires (9431-10873), the shared Replace-tab helpers it
calls (probe pass 4576, change scan 4806-5140, bulk clear / Replace from
folder 8117-8660, scan buttons + scanning state 21103-21420, the sidecar
writer 11433) and its part of ``apply_manufacturer`` (18270-18291).  What is
ported and what is owed: docs/plans/web_ui_tabs/images.md.

The page gets the slot rows in chunks (``rows_<k>``, :data:`CHUNK` rows each,
index = scan order) and the filtered + sorted order as ``view`` (slot indexes,
and group headers in "Group by scene" mode), so a search keystroke resends a
list of numbers, not 6 000 rows, and a metadata probe resends only the chunks
it touched.  The filter / sort / grouping rules are the Tk tab's own, run here.
"""

import base64
import csv
import os
import queue as queue_mod
import re
import subprocess
import sys
import threading
import time

from .. import compat
from .base import TabService, rpc

#: Tk's iid prefix for a "Group by scene" header row; the page's id for one.
GROUP_IID = "::grp::"
CHANGE_SCAN_NOTE = "  ·  still checking…"
NOT_ON_CARD_MARK = "⚠ not on this card"
SOURCES = ("All sources", "File", "Scene texture", "Radium", "Glyph",
           "Boot screen")
CHANGE_FILTER_VALUES = ("All", "Changed", "Unchanged")
#: (column, heading, default descending) - Tk's _image_sort_cfg.
SORT_CFG = (("#0", "Original Image", False), ("n", "Images", True),
            ("res", "Resolution", True), ("fmt", "Format", False),
            ("src", "Source", False), ("keep", "Keep size", True),
            ("rep", "Replacement", False))
CHUNK = 256
LABEL = "Replace Images"
SCAN_LABEL = "Images"

EMPTY_NO_FOLDER = "Set the project folder on the Extract tab, then click Scan."
EMPTY_SCANNING = "Scanning for image files…"
EMPTY_NONE = "No replaceable image found in this folder."
EMPTY_CANCELLED = "Scan cancelled — click Scan to try again."

_BLANK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAEklEQVR42mNgGAWjYBSM"
    "AggAAAQQAAGvRYgsAAAAAElFTkSuQmCC")

_NAME_RE = re.compile(r"^radimg_(.+)_\d+x\d+_[0-9a-f]{8}\.png$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# pure helpers (Tk static methods, verbatim)
# ---------------------------------------------------------------------------
def source_label(rel_path):
    """Which of the image stores *rel_path* came from (Tk
    ``_image_source_label``): derived purely from the extract layout."""
    parts = rel_path.replace("\\", "/").lower().split("/")
    if parts[:2] == ["images", "boot_screen"] and len(parts) > 2:
        return "Boot screen"
    if "scene_textures" in parts:
        if "glyphs" in parts:
            return "Glyph"
        if os.path.basename(rel_path).lower().startswith("radimg"):
            return "Radium"
        return "Scene texture"
    return "File"


def scan_image_groups(assets_path):
    """The "Group by scene" mapping from the Stern extractor's manifests (Tk
    ``_scan_image_groups``): ``(groups, occurrences, every_occurrence)``."""
    groups, occ, where = {}, {}, {}

    def _rows(*parts):
        try:
            with open(os.path.join(assets_path, *parts),
                      encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\r\n")
                    if line and not line.startswith("#"):
                        yield line.split("\t")
        except OSError:
            return

    primary = {}
    per_card = {}
    for cols in _rows("images", "scene_textures", "radium_images.txt"):
        if len(cols) < 3:
            continue
        try:
            off = int(cols[2])
        except ValueError:
            continue
        rel = "images/" + cols[0]
        occ[rel] = occ.get(rel, 0) + 1
        primary.setdefault(rel, (cols[1], off))
        per_card.setdefault(cols[1], []).append((off, rel))
    try:
        atlases = set(os.listdir(os.path.join(
            assets_path, "images", "scene_textures", "glyphs")))
        sliced = True
    except OSError:
        atlases, sliced = set(), False
    for cols in _rows("images", "scene_textures", "glyph_images.txt"):
        if len(cols) >= 2:
            atlases.add(os.path.splitext(os.path.basename(cols[1]))[0])
            sliced = True
    labels = {}
    for card, members in per_card.items():
        label = ""
        if sliced:
            for _off, mrel in sorted(members):
                base = os.path.basename(mrel)
                if os.path.splitext(base)[0] in atlases:
                    continue
                m = _NAME_RE.match(base)
                if m:
                    label = m.group(1)
                    break
        id8 = os.path.basename(os.path.dirname(card))[:8] or card
        labels[card] = ("%s · %s" % (label, id8)) if label else id8
    for rel, (card, off) in primary.items():
        groups[rel] = ("rad::" + card, labels[card], off)
    for card, members in per_card.items():
        for off, mrel in members:
            entry = ("rad::" + card, labels[card], off)
            lst = where.setdefault(mrel, [])
            if entry not in lst:
                lst.append(entry)
    for rel, lst in where.items():
        home = groups.get(rel)
        if home in lst:
            lst.remove(home)
            lst.insert(0, home)
    for idx, cols in enumerate(
            _rows("images", "scene_textures", "manifest.txt")):
        if len(cols) < 2:
            continue
        card = cols[1]
        if "/scene.assets/" in card:
            scene = card.rsplit("/scene.assets/", 1)[0]
        else:
            scene = card.rsplit("/", 1)[0] or card
        label = scene.rstrip("/").rsplit("/", 1)[-1][:8] or scene
        groups.setdefault("images/" + cols[0], ("scn::" + scene, label, idx))
    for idx, cols in enumerate(_rows("images", "manifest.txt")):
        if len(cols) < 2:
            continue
        card_dir = cols[1].rsplit("/", 1)[0] if "/" in cols[1] else ""
        folder = card_dir or "(root)"
        label = folder.lstrip("/") or "(root)"
        groups.setdefault("images/" + cols[0], ("dir::" + folder, label, idx))
    return groups, occ, where


def compute_key_tails(groups, groups_all):
    """``{group_key(lower): distinguishing tail}`` (Tk
    ``_compute_image_key_tails``)."""
    keys = {g[0] for g in groups.values()}
    for lst in groups_all.values():
        keys.update(g[0] for g in lst)
    by_ns = {}
    for k in keys:
        by_ns.setdefault(k.split("::", 1)[0], []).append(k.lower())
    tails = {}
    for _ns, ks in by_ns.items():
        if len(ks) < 2:
            for k in ks:
                tails[k] = k.split("::", 1)[-1]
            continue
        prefix = os.path.commonprefix(ks)
        cut = prefix.rfind("/") + 1
        for k in ks:
            tails[k] = k[cut:]
    return tails


def search_hits_path(rel_path, query):
    """Tk ``_image_search_hits_path``: a glyph matches on its own file name
    only; a query with a path separator is a deliberate path search."""
    rel = rel_path.replace("\\", "/").lower()
    if "/" in query or "\\" in query:
        return query.replace("\\", "/") in rel
    if "glyphs" in rel.split("/"):
        return query in os.path.basename(rel)
    return query in rel


def slot_search_hit(rel_path, query, group_hit):
    """Tk ``_image_slot_search_hit``."""
    if search_hits_path(rel_path, query):
        return True
    if "glyphs" in rel_path.replace("\\", "/").lower().split("/"):
        return False
    return group_hit()


def reveal_menu_label():
    if sys.platform == "darwin":
        return "Reveal in Finder"
    if sys.platform == "win32":
        return "Show in File Explorer"
    return "Show in File Manager"


def _norm(p):
    return os.path.normcase(os.path.normpath(p or ""))


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


# ---------------------------------------------------------------------------
class ImagesTab(TabService):
    ns = "images"
    key = "Replace Images"
    label = "Images"
    group = "Replace"
    icon = "images"
    exports = (
        "pending_image_assignments", "reveal_image_slot",
        "image_search_var", "image_source_filter_var",
        "image_change_filter_var", "image_group_by_scene_var",
        "image_keep_size_var", "image_status_var",
    )

    def __init__(self, window):
        super().__init__(window)
        self.image_search_var = self.var("search")
        self.image_source_filter_var = self.var("source", value="All sources")
        self.image_change_filter_var = self.var("show", value="All")
        self.image_group_by_scene_var = self.var("grouped", "bool", False)
        self.image_keep_size_var = self.var("keep_size", "bool", False)
        self.image_status_var = self.var("status")
        self._sort = ("#0", False)
        self._slots = []
        self._by_rel = {}
        self._idx = {}
        self._assignments = {}
        self._keep_size = set()
        self._groups = {}
        self._group_occ = {}
        self._groups_all = {}
        self._key_tails = {}
        self._group_tags = {}
        self._scan_id = 0
        self._scan_dir = ""
        self._scan_dir_prev = ""
        self._scan_t0 = None
        self._change_scan_id = 0
        self._change_running = False
        self._changed_on_disk = set()
        self._foreign_rels = set()
        self._foreign_twins = {}
        self._foreign_notes = {}
        self._rep_names = {}
        self._rep_names_dir = ""
        self._current_rel = None
        self._current_group = None
        self._preview_ver = 0
        self._open_groups = set()
        self._view_groups = {}
        self._atlas_cache = None
        self._keep_col_cache = None
        self._nchunks = 0
        self._shown = 0
        self._focus_n = 0
        self._running = False
        self._visible_mfr = False
        self._quiet = 0
        #: a file picker of this tab is open (see _pick)
        self._picking = False
        for v in (self.image_search_var, self.image_source_filter_var,
                  self.image_change_filter_var,
                  self.image_group_by_scene_var):
            v.trace_add("write", lambda *_a: self._refresh_image_list())
        self.set(pil_ok=True, note="", scanning=False, view=[], nchunks=0,
                 empty={"text": EMPTY_NO_FOLDER, "busy": False},
                 sort={"key": "#0", "desc": False},
                 cols={"n": False, "keep": False}, can_clear=False,
                 running=False, preview=self._empty_preview(), dir="",
                 focus=None, total=0, shown=0,
                 reveal_label=reveal_menu_label(), sources=list(SOURCES),
                 shows=list(CHANGE_FILTER_VALUES),
                 widths=self._saved_widths())

    # ------------------------------------------------------------------
    # small accessors
    # ------------------------------------------------------------------
    def _assets_dir(self):
        var = getattr(self.window, "write_assets_var", None)
        try:
            return ((var.get() if var is not None else "") or "").strip()
        except Exception:                                # noqa: BLE001
            return ""

    def _is_running(self):
        try:
            return bool(self.window._is_running())
        except Exception:                                # noqa: BLE001
            return self._running

    def _live(self, assets_dir):
        return bool(self._scan_dir) and _norm(self._scan_dir) == _norm(
            assets_dir)

    def _is_current_tab(self):
        return self.store.get("shell", "tab") == self.ns

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        """Tk apply_manufacturer's "same clean slate for the image tab"."""
        self._visible_mfr = bool(getattr(mfr.capabilities, "replace_image",
                                         False))
        self._scan_id += 1
        self._change_scan_id += 1
        self._slots = []
        self._by_rel = {}
        self._idx = {}
        self._assignments = {}
        self._keep_size = set()
        self._scan_dir = ""
        self._changed_on_disk = set()
        self._foreign_rels = set()
        self._foreign_twins = {}
        self._open_groups = set()
        self._scan_t0 = None
        self._change_running = False
        self._clear_preview()
        try:
            note = mfr.image_note() or ""
        except Exception:                                # noqa: BLE001
            note = ""
        self.set(note=note, scanning=False, dir="",
                 pex=self._pex_available(),
                 empty={"text": EMPTY_NO_FOLDER, "busy": False})
        self._refresh_pillow()
        self._refresh_image_list()

    def on_show(self):
        self._refresh_pillow()
        self._maybe_rescan_image()
        self.set(pex=self._pex_available())

    def on_running(self, running, mode):
        self._running = bool(running)
        self.set(running=bool(running))
        self._update_clear_all()

    def _refresh_pillow(self):
        from ...core import image as _image
        self.set(pil_ok=bool(_image.pil_available()))

    def _pex_available(self):
        """"Find in Partition Explorer" needs the Partition Explorer tab
        (Stern Spike 2) and its service's find_in_partition."""
        if not self.window.tab_visible("Partition Explorer"):
            return False
        return self._pex_jump() is not None

    def _pex_jump(self):
        svc = self.window.service("partitions")
        fn = getattr(svc, "find_in_partition", None)
        return fn if callable(fn) else None

    def _maybe_rescan_image(self):
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_image",
                                      False):
            return
        assets_path = self._assets_dir()
        if assets_path and assets_path != self._scan_dir:
            self._scan_image_slots_async()
        elif not assets_path and not self._slots:
            self.set(empty={"text": EMPTY_NO_FOLDER, "busy": False})

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------
    @rpc
    def scan(self):
        self._scan_image_slots_async()
        return True

    def _scan_image_slots_async(self):
        from ...core.image_slots import scan_image_slots
        assets_path = self._assets_dir()
        self._scan_id += 1
        scan_id = self._scan_id
        if not assets_path or not os.path.isdir(assets_path):
            self._slots = []
            self._by_rel = {}
            self._idx = {}
            self._groups = {}
            self._group_occ = {}
            self._groups_all = {}
            self._key_tails = {}
            self._set_scanning(False)
            self._refresh_image_list()
            self.set(empty={"text": EMPTY_NO_FOLDER, "busy": False})
            return
        self._clear_preview()
        mfr = self.mfr

        def _work():
            try:
                roots = mfr.image_slot_dirs(assets_path) if mfr else None
            except Exception:                            # noqa: BLE001
                roots = None
            try:
                exts = mfr.image_slot_exts(assets_path) if mfr else None
            except Exception:                            # noqa: BLE001
                exts = None
            try:
                slots = scan_image_slots(assets_path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:                            # noqa: BLE001
                slots = []
            try:
                groups, occ, where = scan_image_groups(assets_path)
            except Exception:                            # noqa: BLE001
                groups, occ, where = {}, {}, {}
            if self._scan_id != scan_id:
                return
            self.ctx.loop.post(self._populate_image_after_scan, slots,
                               scan_id, assets_path, groups, occ, where)

        self._set_scanning(True)
        threading.Thread(target=_work, daemon=True,
                         name="images-scan").start()

    def _set_scanning(self, active):
        """Tk _set_tab_scanning: the Scan button turns into Cancel scan, the
        list blanks under a busy indicator, and the scan is logged."""
        if active:
            if self._scan_t0 is not None:
                self.log("%s scan replaced after %.1f s by a newer scan."
                         % (SCAN_LABEL, time.monotonic() - self._scan_t0))
            self._scan_t0 = time.monotonic()
            self.log("%s scan started." % SCAN_LABEL)
            self.set(scanning=True, view=[],
                     empty={"text": EMPTY_SCANNING, "busy": True})
        else:
            if self._scan_t0 is not None:
                self.log("%s scan finished in %.1f s."
                         % (SCAN_LABEL, time.monotonic() - self._scan_t0))
            self._scan_t0 = None
            self.set(scanning=False)

    @rpc
    def cancel_scan(self):
        """Tk _cancel_scan."""
        self._scan_id += 1
        if self._scan_t0 is not None:
            self.log("%s scan cancelled after %.1f s."
                     % (SCAN_LABEL, time.monotonic() - self._scan_t0))
        self._scan_t0 = None
        self.set(scanning=False, view=[],
                 empty={"text": EMPTY_CANCELLED, "busy": False})
        return True

    def _populate_image_after_scan(self, slots, scan_id, scan_dir,
                                   groups=None, group_occ=None,
                                   group_all=None):
        if self._scan_id != scan_id:
            return
        from ...core import staged_changes
        self._set_scanning(False)
        self._slots = slots
        self._by_rel = {s.rel_path: s for s in slots}
        self._idx = {s.rel_path: i for i, s in enumerate(slots)}
        self._groups = groups or {}
        self._group_occ = group_occ or {}
        self._groups_all = group_all or {}
        self._key_tails = compute_key_tails(self._groups, self._groups_all)
        self._keep_col_cache = None
        self._quiet += 1
        try:
            if scan_dir != self._scan_dir:
                staged = self._load_staged_changes(scan_dir)
                self._assignments = staged_changes.live_assignments(
                    staged.get("image"), self._by_rel)
                self._keep_size = {
                    r for r in (staged.get("image_keep_size") or ())
                    if r in self._assignments}
                self._warn_dropped_assignments(staged.get("image"),
                                               scan_dir)
                self._restore_change_filter(staged)
                if "image_group_by_scene" in staged:
                    self.image_group_by_scene_var.set(
                        bool(staged["image_group_by_scene"]))
                tags = staged.get("image_group_tags")
                self._group_tags = (
                    {str(k): str(v).strip()[:50] for k, v in tags.items()
                     if str(v).strip()}
                    if isinstance(tags, dict) else {})
                self._seed_group_tags_from_library(scan_dir)
                srcf = staged.get("image_source_filter")
                if srcf in SOURCES:
                    self.image_source_filter_var.set(srcf)
            else:
                self._assignments = {
                    rel: rep for rel, rep in self._assignments.items()
                    if rel in self._by_rel}
        finally:
            self._quiet -= 1
        folder_changed = scan_dir != self._scan_dir
        self._scan_dir = scan_dir
        self._changed_on_disk = set()
        self._foreign_rels = set()
        self._foreign_twins = {}
        if folder_changed:
            self._clear_preview()
            self._open_groups = set()
        self.set(dir=scan_dir)
        self._refresh_image_list()
        self._select_first_row()
        self._start_change_scan()
        self._probe_image_metadata_async(scan_id)

    # ------------------------------------------------------------------
    # metadata probe (Tk _run_probe_pass + _apply_image_meta)
    # ------------------------------------------------------------------
    def _probe_image_metadata_async(self, scan_id):
        from ...core.image import detect_image_info
        pending = [s for s in self._slots if s.info is None]
        if not pending:
            return
        q = queue_mod.SimpleQueue()
        done = threading.Event()
        current = lambda: self._scan_id                   # noqa: E731

        def _coordinator():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            try:
                workers = min(8, (os.cpu_count() or 4))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(detect_image_info, s.abs_path): s
                            for s in pending}
                    for fut in as_completed(futs):
                        if current() != scan_id:
                            for f in futs:
                                f.cancel()
                            return
                        try:
                            info = fut.result()
                        except Exception:                # noqa: BLE001
                            info = None
                        q.put((futs[fut].rel_path, info))
            except Exception:                            # noqa: BLE001
                pass
            finally:
                done.set()

        def _drain():
            if current() != scan_id:
                return
            dirty = set()
            for _ in range(500):
                try:
                    rel, info = q.get_nowait()
                except queue_mod.Empty:
                    break
                i = self._apply_image_meta(scan_id, rel, info)
                if i is not None:
                    dirty.add(i // CHUNK)
            if dirty:
                self._publish_chunks(dirty)
            if not (done.is_set() and q.empty()):
                self.ctx.loop.after(100, _drain)

        threading.Thread(target=_coordinator, daemon=True,
                         name="images-probe").start()
        _drain()

    def _apply_image_meta(self, scan_id, rel, info):
        if self._scan_id != scan_id:
            return None
        slot = self._by_rel.get(rel)
        if slot is None:
            return None
        slot.info = info
        slot.probed = True
        return self._idx.get(rel)

    # ------------------------------------------------------------------
    # change-on-disk diff (Tk _start_change_scan and friends)
    # ------------------------------------------------------------------
    def _start_change_scan(self):
        from ...core import checksums, staged_originals
        assets_path = self._assets_dir()
        rels = [s.rel_path for s in self._slots]
        self._change_scan_id += 1
        scan_id = self._change_scan_id
        if not assets_path or not os.path.isdir(assets_path) or not rels:
            self._changed_on_disk = set()
            self._foreign_rels = set()
            self._foreign_twins = {}
            self._mark_change_scan(False)
            return
        self._mark_change_scan(True)

        def _work():
            from ...core import folder_match
            foreign, twins = set(), {}
            try:
                baseline = checksums.read_baseline_any(assets_path)
                rel_set = set(rels)
                snaps = {r for r in staged_originals.snapshot_rels(assets_path)
                         if r in rel_set}
                to_hash = [r for r in rels if r not in snaps]
                changed = snaps | checksums.changed_rels(
                    assets_path, to_hash, baseline=baseline)
                if baseline:
                    foreign, twins = folder_match.foreign_twins(rels, baseline)
            except Exception:                            # noqa: BLE001
                changed = set()

            def _apply():
                if self._change_scan_id != scan_id:
                    return
                self._changed_on_disk = set(changed)
                self._foreign_rels = set(foreign)
                self._foreign_twins = dict(twins)
                self._mark_change_scan(False)
                self._note_foreign_slots(assets_path, foreign, twins)
                self._refresh_image_list()
                if self._current_rel is not None:
                    self._render_preview(self._current_rel)

            self.ctx.loop.post(_apply)

        threading.Thread(target=_work, daemon=True,
                         name="images-changes").start()

    def _mark_change_scan(self, running):
        self._change_running = bool(running)
        text = self.image_status_var.get() or ""
        has = text.endswith(CHANGE_SCAN_NOTE)
        if running and text and not has:
            self.image_status_var.set(text + CHANGE_SCAN_NOTE)
        elif not running and has:
            self.image_status_var.set(text[:-len(CHANGE_SCAN_NOTE)])

    def _change_scan_note(self):
        return CHANGE_SCAN_NOTE if self._change_running else ""

    def _note_foreign_slots(self, assets_path, foreign, twins=None):
        key = _norm(assets_path)
        if self._foreign_notes.get(key) == len(foreign):
            return
        self._foreign_notes[key] = len(foreign)
        if not foreign:
            return
        shown = ", ".join(sorted(foreign)[:3])
        if len(foreign) > 3:
            shown += ", and %d more" % (len(foreign) - 3)
        self.log(
            "%s: %d file(s) in this folder aren't part of this extract (%s). "
            "They are listed here, but nothing on the card matches them so a "
            "build can't use them — usually files copied in from a different "
            "extract, or a mod pack built from a different card (importing "
            "that pack again takes them back out)."
            % (SCAN_LABEL, len(foreign), shown), "warning")
        twins = twins or {}
        if twins:
            rel = sorted(twins)[0]
            self.log(
                "%s: %d of them are named like one of the card's files but "
                "are a different file type (%s where the card has %s), so "
                "they sit beside their slot instead of in it. Keep your files "
                "in a folder of their own and use \"Replace from folder…\": "
                "it matches names whatever the file type."
                % (SCAN_LABEL, len(twins), os.path.basename(rel),
                   os.path.basename(twins[rel])), "warning")

    def _slot_not_on_card(self, rel):
        return rel is not None and rel in self._foreign_rels

    def _slot_changed_on_disk(self, rel):
        if rel in self._changed_on_disk:
            return True
        from ...core import staged_originals
        return staged_originals.snapshot_path(self._scan_dir or None,
                                              rel) is not None

    def _changed_on_disk_cell(self, rel):
        name = self._remembered_rep_name(rel)
        return "✓ changed on disk (%s)" % name if name else "✓ changed on disk"

    def _rep_pane_empty_text(self, rel, default):
        from ...core import staged_originals
        if rel is None or not self._slot_changed_on_disk(rel):
            return default
        if self._slot_not_on_card(rel):
            twin = (self._foreign_twins or {}).get(rel)
            if twin:
                fix = ("keep your files in a folder of their own and use "
                       "\"Replace from folder…\" above, which matches names "
                       "whatever the file type." if twin in self._by_rel else
                       "extract the card again into a fresh folder, keep your "
                       "files in a folder of their own, and use \"Replace "
                       "from folder…\" there, which matches names whatever "
                       "the file type.")
                return ("this file is not part of this extract. The card's "
                        "file is %s and this one is %s: a file dropped into "
                        "the project folder only counts under the card's "
                        "exact name, file type included, so the next build "
                        "cannot use it. Instead, %s"
                        % (os.path.basename(twin), os.path.basename(rel), fix))
            return ("this file is not part of this extract — nothing on the "
                    "card matches its name, so the next build cannot put it "
                    "anywhere. Files copied in from a different extract do "
                    "this (a scene picture's or glyph's name ends in a "
                    "fingerprint of the card it came from, so a copy from "
                    "another card, or from one already built with changes, "
                    "is named differently), and so does a mod pack made from "
                    "an older extract. Use \"Transfer Mods to New Version\" on "
                    "the Mod Pack tab to carry changes over by content instead "
                    "of by name.")
        if staged_originals.snapshot_path(self._scan_dir or None, rel):
            return default
        return ("already changed on disk — the change is on the left, and it "
                "is what the next build puts on the card. No original was "
                "saved for this slot.")

    # ------------------------------------------------------------------
    # the sidecar (Tk _load_staged_changes / _save_staged_changes, image part)
    # ------------------------------------------------------------------
    def _load_staged_changes(self, assets_dir):
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
        self._rep_names_dir = assets_dir
        self._rep_names = {
            rel: str(name)
            for rel, name in (data.get("replacement_names") or {}).items()
            if isinstance(name, str) and name.strip()}
        return data

    def _remembered_rep_name(self, rel):
        if not self._scan_dir or not self._rep_names:
            return ""
        if _norm(self._scan_dir) != _norm(self._rep_names_dir or "\0"):
            return ""
        return self._rep_names.get(rel, "")

    def _save_staged_changes(self):
        """The image sections of the sidecar (every other tab's sections are
        re-read from the file and written back untouched, so one tab's save
        never wipes another's)."""
        from ...core import history_log, staged_changes
        assets_dir = self._assets_dir()
        if not assets_dir or not os.path.isdir(assets_dir):
            return
        data = staged_changes.load(assets_dir)
        hist = []
        if self._live(assets_dir):
            hist += history_log.diff_assignments(
                "image", data.get("image"), self._assignments)
            data["image"] = dict(self._assignments)
            data["image_keep_size"] = sorted(
                r for r in self._keep_size if r in self._assignments)
            data["image_change_filter"] = self.image_change_filter_var.get()
            data["image_group_by_scene"] = bool(
                self.image_group_by_scene_var.get())
            data["image_group_tags"] = {
                k: v for k, v in self._group_tags.items() if v}
            data["image_source_filter"] = self.image_source_filter_var.get()
            try:
                from ...core import tag_library
                known = {self._group_of(s.rel_path)[0] for s in self._slots}
                known |= set(self._group_tags)
                tag_library.remember(assets_dir, self._group_tags, known)
            except Exception:                            # noqa: BLE001
                pass
            names = dict(data.get("replacement_names") or {})
            for rel, path in self._assignments.items():
                if isinstance(path, str) and path.strip():
                    names[rel] = os.path.basename(path)
            if names:
                data["replacement_names"] = names
        staged_changes.save(assets_dir, data)
        history_log.record(assets_dir, [h for h in hist if h])
        cb = self.window.cb.get("on_folder_state_written")
        if cb is not None:
            cb(assets_dir)

    def _warn_dropped_assignments(self, saved, scan_dir):
        from ...core import staged_changes, staged_originals
        kind = "image"
        dropped = staged_changes.dropped_assignments(saved, self._by_rel)
        if not dropped:
            return
        any_pending = False
        for rel, path, why in dropped[:6]:
            alt = staged_changes.same_stem_sibling(path)
            hint = ('\n        (a file named "%s" IS in that folder — same '
                    "name, different extension. If that's this clip "
                    "re-exported, re-pick it.)" % alt) if alt else ""
            if staged_originals.snapshot_path(scan_dir, rel):
                self.log(
                    'Note: "%s" already holds its %s replacement (changed on '
                    'disk) — nothing is lost.  But the source file it was '
                    'made from wasn\'t found (%s), so it can\'t be '
                    're-applied until it\'s re-picked:\n        %s%s'
                    % (rel, kind, why, path, hint), "info")
            else:
                any_pending = True
                self.log(
                    'Saved %s replacement for "%s" wasn\'t restored — %s:\n'
                    '        %s%s' % (kind, rel, why, path, hint), "error")
        if len(dropped) > 6:
            self.log("…and %d more saved %s replacement(s) like this."
                     % (len(dropped) - 6, kind),
                     "error" if any_pending else "info")
        # Once per folder across the Replace tabs (Tk kept one flag on the
        # window for audio, video and images; so does this).
        key = _norm(scan_dir)
        if getattr(self.window, "_relink_hint_for", None) != key:
            self.window._relink_hint_for = key
            self.log(
                'Moved this project (or the files it points at) to another '
                'PC or drive? Project ▾ → "Relink moved files…" searches a '
                'folder you pick and re-points every one of these at once.',
                "info")

    def _restore_change_filter(self, staged):
        val = staged.get("image_change_filter")
        if val in CHANGE_FILTER_VALUES:
            self.image_change_filter_var.set(val)
        elif "image_changed_only" in staged:
            self.image_change_filter_var.set(
                "Changed" if staged["image_changed_only"] else "All")

    def _seed_group_tags_from_library(self, scan_dir):
        try:
            present = {self._group_of(s.rel_path)[0] for s in self._slots}
        except Exception:                                # noqa: BLE001
            return
        try:
            from ...core import staged_changes, tag_library
            seeded = tag_library.seed_tags(scan_dir, present)
            added = False
            for key, name in seeded.items():
                if key not in self._group_tags:
                    self._group_tags[key] = name
                    added = True
            if added:
                data = staged_changes.load(scan_dir)
                merged = dict(data.get("image_group_tags") or {})
                merged.update({k: v for k, v in self._group_tags.items()
                               if v})
                data["image_group_tags"] = merged
                staged_changes.save(scan_dir, data)
        except Exception:                                # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # grouping + keep size
    # ------------------------------------------------------------------
    def _group_of(self, rel):
        g = self._groups.get(rel)
        if g is not None:
            return g
        folder = os.path.dirname(rel).replace("\\", "/") or "(root)"
        return ("dir::" + folder, folder, 0)

    def _groups_of(self, rel):
        return self._groups_all.get(rel) or [self._group_of(rel)]

    def _group_matches(self, group, query):
        key, label, _order = group
        if (query in label.lower()
                or query in self._group_tags.get(key, "").lower()):
            return True
        k = key.lower()
        if "/" in query or "\\" in query:
            return query.replace("\\", "/") in k
        return query in self._key_tails.get(k, k)

    def _font_atlas_stems(self):
        scan = self._scan_dir or ""
        cache = self._atlas_cache
        if cache and cache[0] == scan:
            return cache[1]
        stems = set()
        tex = os.path.join(scan, "images", "scene_textures")
        try:
            stems.update(os.listdir(os.path.join(tex, "glyphs")))
        except OSError:
            pass
        try:
            with open(os.path.join(tex, "glyph_images.txt"),
                      encoding="utf-8") as f:
                for line in f:
                    cols = line.rstrip("\r\n").split("\t")
                    if len(cols) >= 2 and not line.startswith("#"):
                        stems.add(os.path.splitext(
                            os.path.basename(cols[1]))[0])
        except OSError:
            pass
        self._atlas_cache = (scan, stems)
        return stems

    def _can_keep_size(self, rel):
        if not rel or rel not in self._by_rel:
            return False
        if source_label(rel) != "Radium":
            return False
        stem = os.path.splitext(os.path.basename(rel))[0]
        return stem not in self._font_atlas_stems()

    def _keep_state(self, rel):
        if not (self._assignments.get(rel) and self._can_keep_size(rel)):
            return None
        return rel in self._keep_size

    def _offers_keep_size(self):
        cache = self._keep_col_cache
        if cache is None or cache[0] is not self._slots:
            cache = (self._slots, any(self._can_keep_size(s.rel_path)
                                      for s in self._slots))
            self._keep_col_cache = cache
        return cache[1]

    # ------------------------------------------------------------------
    # the list (Tk _refresh_image_list)
    # ------------------------------------------------------------------
    def _row(self, s):
        rel = s.rel_path
        rep = self._assignments.get(rel)
        is_changed = rel in self._changed_on_disk
        if rep:
            disp = os.path.basename(rep)
            tag = "changed" if is_changed else "assigned"
        elif self._slot_not_on_card(rel):
            disp, tag = NOT_ON_CARD_MARK, "foreign"
        elif is_changed:
            disp, tag = self._changed_on_disk_cell(rel), "changed"
        else:
            disp, tag = "Choose…", ""
        res = "…" if (s.info is None and not s.probed) \
            else s.resolution_str()
        return {"r": rel, "s": res, "f": s.format_summary(),
                "o": source_label(rel), "k": self._keep_state(rel),
                "p": disp, "t": tag}

    def _publish_chunks(self, which=None):
        """Send the rows (all chunks, or the chunk numbers in *which*)."""
        n = (len(self._slots) + CHUNK - 1) // CHUNK
        out = {}
        ks = range(n) if which is None else sorted(k for k in which if k < n)
        for k in ks:
            out["rows_%d" % k] = [self._row(s) for s in
                                  self._slots[k * CHUNK:(k + 1) * CHUNK]]
        if which is None:
            for k in range(n, self._nchunks):
                out["rows_%d" % k] = None
            self._nchunks = n
            out["nchunks"] = n
        if out:
            self.set(**out)

    def _change_filter_pred(self):
        mode = self.image_change_filter_var.get()
        if mode not in ("Changed", "Unchanged"):
            return None
        touched = set(self._assignments) | self._changed_on_disk
        want_changed = (mode == "Changed")
        return lambda rel: (rel in touched) == want_changed

    def _refresh_image_list(self):
        if self._quiet or self.get("scanning"):
            # a scan in flight owns the (blanked) list; it refreshes on landing
            return
        query = (self.image_search_var.get() or "").strip().lower()
        grouped = bool(self.image_group_by_scene_var.get())
        changed = self._changed_on_disk
        slots = self._slots
        change_ok = self._change_filter_pred()
        if change_ok is not None:
            slots = [s for s in slots if change_ok(s.rel_path)]
        srcf = self.image_source_filter_var.get()
        if srcf and srcf != "All sources":
            slots = [s for s in slots if source_label(s.rel_path) == srcf]

        def _matched_group(s):
            for g in self._groups_of(s.rel_path):
                if self._group_matches(g, query):
                    return g
            return None

        def _match(s):
            return slot_search_hit(
                s.rel_path, query, lambda: _matched_group(s) is not None)
        if query:
            slots = [s for s in slots if _match(s)]
        col, desc = self._sort

        def _key(s):
            if col == "res":
                return ((s.info.width * s.info.height) if s.info else -1,)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "src":
                return (source_label(s.rel_path), s.rel_path.lower())
            if col == "keep":
                state = self._keep_state(s.rel_path)
                return (0 if state is None else 1 + state,
                        s.rel_path.lower())
            if col == "rep":
                rep = self._assignments.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                return (1, "") if s.rel_path in changed else (2, "")
            return (s.rel_path.lower(),)

        view = []
        view_groups = {}
        if grouped:
            disp = {}
            for s in slots:
                g = _matched_group(s) if query else None
                disp[s.rel_path] = g or self._group_of(s.rel_path)
            by_grp = {}
            for s in slots:
                key, label, _order = disp[s.rel_path]
                by_grp.setdefault(key, (label, []))[1].append(s)

            def _disp(k):
                return self._group_tags.get(k) or by_grp[k][0]
            if col == "n":
                group_order = sorted(
                    by_grp, key=lambda k: (len(by_grp[k][1]),
                                           _disp(k).lower(), k),
                    reverse=desc)
            else:
                group_order = sorted(by_grp,
                                     key=lambda k: (_disp(k).lower(), k))
            for key in group_order:
                members = by_grp[key][1]
                if col in ("#0", "n"):
                    members.sort(
                        key=lambda s: (disp[s.rel_path][2],
                                       s.rel_path.lower()),
                        reverse=desc if col == "#0" else False)
                else:
                    members.sort(key=_key, reverse=desc)
                n = len(members)
                is_open = key in self._open_groups
                view.append({"g": key, "l": _disp(key), "n": n,
                             "c": "%d image%s" % (n, "" if n == 1 else "s"),
                             "o": is_open})
                view_groups[key] = [s.rel_path for s in members]
                if is_open:
                    view.extend(self._idx[s.rel_path] for s in members)
        else:
            slots = sorted(slots, key=_key, reverse=desc)
            view = [self._idx[s.rel_path] for s in slots]
        self._view_groups = view_groups
        self._shown = len(slots)

        total = len(self._slots)
        changed_total = len(set(self._assignments) | changed)
        if total == 0:
            self.image_status_var.set("")
            text = EMPTY_NONE if self._scan_dir else EMPTY_NO_FOLDER
            empty = {"text": text, "busy": False}
        else:
            shown = len(slots)
            extra = "  (%d shown)" % shown if shown != total else ""
            self.image_status_var.set(
                "%d images, %d changed%s" % (total, changed_total, extra)
                + self._change_scan_note())
            empty = None
        self._publish_chunks()
        self.set(view=view, total=total, shown=len(slots),
                 changed=changed_total,
                 sort={"key": col, "desc": bool(desc)},
                 cols={"n": grouped, "keep": self._offers_keep_size()},
                 empty=empty)
        self._update_clear_all()

    def _select_first_row(self):
        view = self.get("view") or []
        if not view:
            return
        first = view[0]
        iid = (GROUP_IID + first["g"]) if isinstance(first, dict) \
            else self._slots[first].rel_path
        self._focus([iid], iid)
        self.select(iid)

    def _focus(self, ids, cur):
        """Tell the page which rows to select (and scroll to)."""
        self._focus_n += 1
        self.set(focus={"ids": list(ids), "id": cur, "n": self._focus_n})

    # ------------------------------------------------------------------
    # the page's list controls
    # ------------------------------------------------------------------
    @rpc
    def sort(self, col):
        """Tk _sort_click: toggle the direction on the active column, else
        switch to *col* at its default direction."""
        default = dict((c, d) for c, _t, d in SORT_CFG).get(col)
        if default is None:
            return False
        cur = self._sort
        self._sort = (col, not cur[1]) if cur and cur[0] == col \
            else (col, default)
        self._refresh_image_list()
        return True

    @rpc
    def set_source(self, value):
        if value not in SOURCES:
            return False
        self.image_source_filter_var.set(value)
        self._save_staged_changes()
        return True

    @rpc
    def set_show(self, value):
        if value not in CHANGE_FILTER_VALUES:
            return False
        self.image_change_filter_var.set(value)
        self._save_staged_changes()
        return True

    @rpc
    def set_grouped(self, value):
        self.image_group_by_scene_var.set(bool(value))
        self._save_staged_changes()
        return True

    @rpc
    def toggle_group(self, key, is_open=None):
        want = (key not in self._open_groups) if is_open is None \
            else bool(is_open)
        if want:
            self._open_groups.add(key)
        else:
            self._open_groups.discard(key)
        self._refresh_image_list()
        return want

    # ------------------------------------------------------------------
    # selection + preview
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_preview():
        return {"rel": None, "group": None, "hdr": "Original",
                "hdr_main": "Original", "hdr_note": "", "orig": "",
                "rep": "", "rep_name": "", "empty": "", "keep": None,
                "has_pick": False, "clearable": False, "ver": 0}

    def _clear_preview(self):
        self._current_rel = None
        self._current_group = None
        self._preview_ver += 1
        p = self._empty_preview()
        p["ver"] = self._preview_ver
        self.image_keep_size_var.set(False)
        self.set(preview=p)

    @rpc
    def select(self, iid):
        """Tk _image_on_tree_select."""
        if not iid:
            return False
        if iid.startswith(GROUP_IID):
            key = iid[len(GROUP_IID):]
            kids = self._view_groups.get(key) or []
            slot = self._by_rel.get(kids[0]) if kids else None
            self._current_rel = None
            self._current_group = key
            self._preview_ver += 1
            p = self._empty_preview()
            p.update(group=key, orig=slot.abs_path if slot else "",
                     ver=self._preview_ver)
            self.set(preview=p)
            return True
        if iid not in self._by_rel:
            return False
        self._current_group = None
        if iid == self._current_rel:
            return True
        self._current_rel = iid
        self._render_preview(iid)
        return True

    def _render_preview(self, rel):
        """Tk _image_render_preview."""
        from ...core import staged_originals
        slot = self._by_rel.get(rel) if rel is not None else None
        rep = self._assignments.get(rel) if rel is not None else None
        opath = slot.abs_path if slot else None
        changed = self._slot_changed_on_disk(rel) if rel is not None \
            else False
        snap = None
        if changed:
            snap = staged_originals.snapshot_path(self._scan_dir or None, rel)
            if snap:
                opath = snap
        hdr_main = ("Current file (already modified)" if changed and not snap
                    else "Original")
        note = ""
        n_occ = self._group_occ.get(rel, 0) if rel is not None else 0
        if n_occ > 1:
            note = ("shared by %d scenes (replacing it changes all of them)"
                    % n_occ)
        hdr = hdr_main + (("  ·  " + note) if note else "")
        shown_rep = rep
        if shown_rep is None and changed and snap and slot:
            shown_rep = slot.abs_path
        empty = (self._rep_pane_empty_text(
            rel, "(no replacement assigned — double-click the row to pick "
                 "one)") if slot else "")
        self._preview_ver += 1
        self.set(preview={
            "rel": rel, "group": None, "hdr": hdr, "hdr_main": hdr_main,
            "hdr_note": note, "orig": opath or "",
            "rep": shown_rep or "",
            "rep_name": os.path.basename(shown_rep) if shown_rep else "",
            "empty": empty, "keep": self._keep_row(rel),
            "has_pick": bool(rep),
            "clearable": bool(self._replacement_targets([rel]))
            if slot else False,
            "ver": self._preview_ver})

    def _keep_row(self, rel):
        """Tk _image_refresh_keep_row: ``{on, text}`` or None (hidden)."""
        rep = self._assignments.get(rel) if rel else None
        if not rep or not self._can_keep_size(rel):
            return None
        slot = self._by_rel[rel]
        from ...core import staged_originals
        orig_path = (staged_originals.snapshot_path(self._scan_dir or None,
                                                    rel)
                     or slot.abs_path)
        try:
            from PIL import Image
            with Image.open(orig_path) as im:
                orig = im.size
            with Image.open(rep) as im:
                new = im.size
        except Exception:                                # noqa: BLE001
            return None
        keep = rel in self._keep_size
        self.image_keep_size_var.set(keep)
        if new == orig:
            text = "Same size as the original (%d×%d)." % orig
        elif keep:
            text = ("Kept at %d×%d (the original is %d×%d): the scene grows "
                    "to fit it." % (new + orig))
        else:
            text = ("Your picture is %d×%d, the original %d×%d: it will be "
                    "squeezed to fit." % (new + orig))
        return {"on": keep, "text": text}

    @rpc(loop=False)
    def thumb(self, path, w=320, h=214):
        """A preview picture as a data: URL (the Tk panes' own helper,
        core.image.thumbnail_png), or "" when it cannot be read."""
        from ...core.image import thumbnail_png
        try:
            w = max(16, min(2400, int(w)))
            h = max(16, min(2400, int(h)))
        except (TypeError, ValueError):
            w, h = 320, 214
        png = thumbnail_png(path, w, h) if path else None
        if not png:
            return ""
        return "data:image/png;base64," + base64.b64encode(png).decode()

    # ------------------------------------------------------------------
    # assigning
    # ------------------------------------------------------------------
    @staticmethod
    def _image_filetypes():
        from ...core.image import REPLACEMENT_EXTS
        spec = " ".join("*%s" % e for e in REPLACEMENT_EXTS)
        return [("Image files", spec), ("All files", "*.*")]

    def _pick(self, ask, *args, **kw):
        """Run one of the window's pickers (``ask_open`` / ``ask_folder`` /
        ``ask_save``), or answer "cancelled" when one of this tab's pickers is
        already open.  Tk's pickers were modal and took the grab, so a
        double-click could only ever open one.  Here the loop keeps turning
        under an open picker, so the second click of a double-click (and the
        row's double-click after it) arrive while the first is still up."""
        if self._picking:
            return None
        self._picking = True
        try:
            return ask(*args, **kw)
        finally:
            self._picking = False

    @rpc
    def choose(self, rel):
        """Tk _image_assign_rel: pick the replacement for one slot."""
        if not rel or rel not in self._by_rel:
            if rel is None:
                compat.messagebox.showinfo("No Slot Selected",
                                           "Select an image to assign.")
            return None
        path = self._pick(
            self.window.ask_open, "image_replacement",
            "Choose a replacement for %s" % rel, self._image_filetypes())
        if not path:
            return None
        self._assignments[rel] = path
        self._save_staged_changes()
        self.log("Replace Images: %s ← %s" % (rel, os.path.basename(path)),
                 "info")
        self._refresh_image_list()
        if rel == self._current_rel:
            self._render_preview(rel)
        self._focus([rel], rel)
        return rel

    @rpc
    def set_keep(self, rel, value):
        """Tk _image_set_keep_size."""
        if not self._can_keep_size(rel):
            return False
        if value:
            self._keep_size.add(rel)
        else:
            self._keep_size.discard(rel)
        self.log("Replace Images: %s %s." % (
            rel, "keeps its replacement's own size" if value
            else "scales its replacement to the original size"), "info")
        self._save_staged_changes()
        i = self._idx.get(rel)
        if i is not None:
            self._publish_chunks({i // CHUNK})
        if rel == self._current_rel:
            self._render_preview(rel)
        return True

    # ------------------------------------------------------------------
    # clearing (Tk 8117-8386)
    # ------------------------------------------------------------------
    def _applied_replacement_rels(self, rels=None):
        from ...core import staged_originals
        snaps = staged_originals.snapshot_rels(self._scan_dir or None)
        if rels is None:
            return sorted(rel for rel in snaps if rel in self._by_rel)
        return [rel for rel in dict.fromkeys(rels)
                if rel in snaps and rel in self._by_rel]

    def _replacement_targets(self, rels=None):
        assigns = self._assignments
        if rels is None:
            rels = list(assigns) + self._applied_replacement_rels()
        applied = set(self._applied_replacement_rels(rels))
        return [rel for rel in dict.fromkeys(rels)
                if assigns.get(rel) or rel in applied]

    def _put_back_originals(self, rels):
        from ...core import history_log, staged_changes, staged_originals
        scan_dir = self._scan_dir or None
        done = [rel for rel in rels if staged_originals.revert(scan_dir, rel)]
        if not done:
            return []
        self._changed_on_disk.difference_update(done)
        data = staged_changes.load(scan_dir)
        names = data.get("replacement_names") or {}
        if any(rel in names for rel in done):
            for rel in done:
                names.pop(rel, None)
            data["replacement_names"] = names
            staged_changes.save(scan_dir, data)
        for rel in done:
            self._rep_names.pop(rel, None)
        history_log.record(scan_dir, [
            "%s  %s  put back to the extract's original (its replacement "
            "was cleared)" % ("image", rel) for rel in done])
        return done

    def _clear_replacement_picks(self, rels, reselect=True):
        assigns = self._assignments
        rels = list(dict.fromkeys(rels))
        picks = [rel for rel in rels if rel in assigns]
        applied = ([] if self._is_running()
                   else self._applied_replacement_rels(rels))
        if not picks and not applied:
            return 0
        for rel in picks:
            del assigns[rel]
        restored = self._put_back_originals(applied)
        self._save_staged_changes()
        gone = list(dict.fromkeys(picks + restored))
        if len(gone) == 1:
            msg = "%s: cleared replacement for %s" % (LABEL, gone[0])
            if restored:
                msg += (" and put the card's original file back in the "
                        "project folder")
        else:
            msg = ("%s: cleared %d replacements (the folder's history log "
                   "names each one)" % (LABEL, len(gone)))
            if restored:
                msg += ("; %d of them had already been applied to the "
                        "project folder and have the card's original file "
                        "back" % len(restored))
        self.log(msg, "info")
        stuck = [rel for rel in applied if rel not in restored]
        if stuck:
            self.log(
                "%s: could not put the card's original file back in %s — is "
                "it open in another program? Clear it again once it is "
                "closed." % (LABEL, ", ".join(stuck[:3])
                             + (" and %d more" % (len(stuck) - 3)
                                if len(stuck) > 3 else "")), "warning")
        self._refresh_image_list()
        cur = self._current_rel
        if cur is not None and cur in set(gone):
            self._render_preview(cur)
        if reselect:
            shown = self._shown_rels()
            alive = [rel for rel in gone if rel in shown]
            if alive:
                self._focus(alive, alive[0])
        self._update_clear_all()
        return len(gone)

    def _shown_rels(self):
        out = set()
        for e in self.get("view") or []:
            if not isinstance(e, dict):
                out.add(self._slots[e].rel_path)
        return out

    def _clear_confirm_text(self, targets, question):
        applied = len(self._applied_replacement_rels(targets))
        if not applied:
            return ("%s\n\nThis only drops the picks: none of your own files "
                    "are touched." % question)
        one = applied == 1
        return ("%s\n\n%d of these %s already applied to the project folder "
                "(by a build, or by Start on the Emulate tab), and %s back "
                "to the card's original file. None of your own files are "
                "touched."
                % (question, applied, "is" if one else "are",
                   "it goes" if one else "they go"))

    @rpc
    def clear_one(self, rel):
        """The row menu's / preview's "Clear replacement" (one slot)."""
        if rel not in self._by_rel:
            return 0
        return self._clear_replacement_picks([rel])

    @rpc
    def clear_selected(self, rels):
        """Tk _clear_selected_replacements: the whole selection."""
        rels = [r for r in (rels or []) if r in self._by_rel]
        targets = self._replacement_targets(rels)
        if len(targets) > 1 and not compat.messagebox.askyesno(
                "Clear replacements",
                self._clear_confirm_text(
                    targets, "Clear the replacements for these %d "
                             "slots?" % len(targets))):
            return 0
        return self._clear_replacement_picks(rels)

    @rpc
    def clear_all(self):
        """Tk _clear_all_replacements (the Clear replacements… button)."""
        if self._is_running():
            return 0
        targets = self._replacement_targets()
        n = len(targets)
        if not n:
            compat.messagebox.showinfo(
                "Clear replacements",
                "Nothing is picked on this tab, so there is nothing to "
                "clear.")
            return 0
        if not compat.messagebox.askyesno(
                "Clear replacements",
                self._clear_confirm_text(
                    targets, "Clear all %d replacement%s on this tab?"
                             % (n, "" if n == 1 else "s"))):
            return 0
        return self._clear_replacement_picks(targets, reselect=False)

    def _update_clear_all(self):
        live = (not self._is_running()
                and bool(self._replacement_targets()))
        self.set(can_clear=live)

    # ------------------------------------------------------------------
    # Replace from folder… (Tk _replace_from_folder, kind "image")
    # ------------------------------------------------------------------
    @staticmethod
    def _folder_match_list(names, cap=10):
        shown = ", ".join(names[:cap])
        if len(names) > cap:
            shown += ", and %d more" % (len(names) - cap)
        return shown

    @rpc
    def from_folder(self):
        from ...core import folder_match
        from ...core.image import REPLACEMENT_EXTS
        if self._is_running():
            return 0
        slot_rels = [rel for rel in self._by_rel
                     if rel not in self._foreign_rels]
        if not slot_rels:
            compat.messagebox.showinfo(
                "Replace from folder",
                "There are no slots on this tab to match files to yet. Set "
                "the project folder on the Extract tab and Scan first.")
            return 0
        folder = self._pick(
            self.window.ask_folder, "image_replacement",
            "Choose a folder of replacement files")
        if not folder:
            return 0
        folder = os.path.normpath(folder)
        project = self._assets_dir()
        if project:
            a = os.path.normcase(os.path.abspath(folder))
            b = os.path.normcase(os.path.abspath(project))
            if a == b or a.startswith(b.rstrip(os.sep) + os.sep) \
                    or b.startswith(a.rstrip(os.sep) + os.sep):
                compat.messagebox.showwarning(
                    "Replace from folder",
                    "That folder is part of the project folder, and the "
                    "files in the project folder are the card's own. Keep "
                    "your replacement files in a folder of their own, "
                    "outside the project, and choose that one.")
                return 0
        found = folder_match.match_folder(folder, slot_rels, REPLACEMENT_EXTS)
        pairs = found["pairs"]
        fingerprinted = [f for f in found["unmatched"]
                         if folder_match.FINGERPRINT_RE.search(f)]
        fingerprint_note = (
            "\n\nScene pictures and font glyphs are named with a fingerprint "
            "of the card they were extracted from (the 8 letters and digits "
            "at the end, like _bba78124), so the same picture from a "
            "different card, or from a card that was already built with "
            "changes, has a different name. To carry those over, use "
            "\"Transfer Mods to New Version\" on the Mod Pack tab with that "
            "extract's whole folder as the old extract."
            if fingerprinted else "")
        if not pairs:
            compat.messagebox.showinfo(
                "Replace from folder",
                "None of the %d file(s) in that folder is named like a slot "
                "on this tab. Files pair by name: the file type and capital "
                "letters don't matter, and subfolders are fine.%s"
                % (found["files"], fingerprint_note))
            return 0
        assigns = self._assignments
        n = len(pairs)
        lines = ["Use %d file(s) from\n%s\nas replacements, each for the slot "
                 "with its name?" % (n, folder)]
        if found["retyped"]:
            slot = found["retyped"][0]
            lines.append(
                "%d of them are a different file type from their slot (%s "
                "for %s). That's fine: each is converted to suit its slot, "
                "like any other pick."
                % (len(found["retyped"]), os.path.basename(pairs[slot]),
                   os.path.basename(slot)))
        already = [rel for rel in pairs if assigns.get(rel)]
        if already:
            lines.append("%d of those slots already have a replacement "
                         "picked; it is swapped for the file from this "
                         "folder." % len(already))
        left = (len(found["unmatched"]) + len(found["ambiguous"])
                + len(found["duplicates"]))
        if left:
            lines.append("%d file(s) in the folder are left out; the log "
                         "names them." % left)
        if not compat.messagebox.askyesno(
                "Replace from folder", "\n\n".join(lines) + fingerprint_note):
            return 0
        assigns.update(pairs)
        self._save_staged_changes()
        self.log(
            "%s: picked %d replacement(s) by name from %s%s."
            % (LABEL, n, folder,
               (" (%d of a different file type, converted to suit their "
                "slot)" % len(found["retyped"])) if found["retyped"] else ""),
            "info")
        if found["unmatched"]:
            self.log("%s: %d file(s) named like no slot on this tab: %s"
                     % (LABEL, len(found["unmatched"]),
                        self._folder_match_list(found["unmatched"])),
                     "warning")
        if found["ambiguous"]:
            self.log(
                "%s: %d file(s) named like more than one slot, so left out "
                "(put each in a subfolder named like its slot's to say "
                "which): %s"
                % (LABEL, len(found["ambiguous"]),
                   self._folder_match_list(found["ambiguous"])), "warning")
        if found["duplicates"]:
            self.log(
                "%s: %d file(s) left out because another file in the folder "
                "has the same name: %s"
                % (LABEL, len(found["duplicates"]),
                   self._folder_match_list(found["duplicates"])), "warning")
        if fingerprinted:
            self.log(
                "%s: %d of the left-out files are scene pictures or glyphs "
                "named for a different card's contents; \"Transfer Mods to "
                "New Version\" carries those over by content."
                % (LABEL, len(fingerprinted)), "warning")
        self._refresh_image_list()
        if self._current_rel in set(pairs):
            self._render_preview(self._current_rel)
        self._update_clear_all()
        return n

    # ------------------------------------------------------------------
    # Export CSV (the Audio / Video tabs' export, for this table)
    # ------------------------------------------------------------------
    @rpc
    def export_csv(self):
        if not self._slots:
            compat.messagebox.showinfo(
                "Export CSV",
                "Scan an assets folder first — the image table is empty.")
            return ""
        path = self._pick(
            self.window.ask_save, "image_csv", "Save image table as CSV",
            initialfile="image_slots.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            defaultextension=".csv")
        if not path:
            return ""
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Original Image", "Resolution", "Format",
                            "Source", "Replacement", "Changed On Disk",
                            "Keep Size"])
                for s in sorted(self._slots, key=lambda q: q.rel_path):
                    rel = s.rel_path
                    keep = self._keep_state(rel)
                    w.writerow([
                        rel, s.resolution_str(), s.format_summary(),
                        source_label(rel), self._assignments.get(rel, ""),
                        "yes" if rel in self._changed_on_disk else "",
                        "yes" if keep else "",
                    ])
        except OSError as e:
            compat.messagebox.showerror("Export CSV",
                                        "Couldn't write the CSV:\n%s" % e)
            return ""
        self.log("Image table exported: %d slot(s) → %s"
                 % (len(self._slots), os.path.normpath(path)), "success")
        return path

    # ------------------------------------------------------------------
    # the right-click menus (built here so their rules are the Tk tab's)
    # ------------------------------------------------------------------
    @rpc
    def menu(self, iid, sel=None):
        """The context menu for row *iid* with *sel* selected, as
        ``[{label, act, disabled, sep}]``; the page shows it and sends the
        chosen ``act`` back to :meth:`act`."""
        sel = [s for s in (sel or []) if s]
        items = []
        if iid in sel and len(sel) >= 2:
            rows = [rel for rel in sel if rel in self._by_rel]
            picked = self._replacement_targets(rows)
            items.append({"label": "%d slot%s selected"
                          % (len(rows), "" if len(rows) == 1 else "s"),
                          "disabled": True})
            items.append({"sep": True})
            if picked:
                items.append({
                    "label": "Clear %d replacement%s in this selection"
                             % (len(picked), "" if len(picked) == 1 else "s"),
                    "act": "clear_sel"})
            else:
                items.append({"label": "No replacements in this selection",
                              "disabled": True})
            return items
        if iid.startswith(GROUP_IID):
            key = iid[len(GROUP_IID):]
            kids = self._view_groups.get(key) or []
            n = len(kids)
            plural = "" if n == 1 else "s"
            items.append({"label": "Assign replacement to all %d image%s…"
                          % (n, plural), "act": "group_assign"})
            items.append({"label": "Blank all %d image%s (transparent)…"
                          % (n, plural), "act": "group_blank"})
            if self._replacement_targets(kids):
                items.append({"sep": True})
                items.append({"label": "Clear replacements in group",
                              "act": "group_clear"})
            items.append({"sep": True})
            items.append({"label": "Rename group…", "act": "group_rename"})
            return items
        if iid not in self._by_rel:
            return []
        items.append({"label": "Choose replacement…", "act": "choose"})
        if self._replacement_targets([iid]):
            items.append({"sep": True})
            items.append({"label": "Clear replacement", "act": "clear_one"})
        src = source_label(iid)
        if src in ("Glyph", "Radium", "Scene texture"):
            items.append({"sep": True})
            if src == "Glyph":
                items.append({"label": "Open in Fonts window…",
                              "act": "fonts"})
            items.append({"label": "Show scene contents…", "act": "scenes"})
        items.append({"sep": True})
        items.append({"label": reveal_menu_label(), "act": "reveal"})
        if self._pex_available():
            items.append({"label": "Find in Partition Explorer",
                          "act": "pex"})
        return items

    @rpc
    def act(self, action, iid, sel=None):
        """Run a menu entry from :meth:`menu`."""
        if action == "choose":
            return self.choose(iid)
        if action == "clear_one":
            return self.clear_one(iid)
        if action == "clear_sel":
            return self.clear_selected(sel or [])
        if action == "reveal":
            slot = self._by_rel.get(iid)
            if slot is not None:
                self._reveal_in_file_manager(slot.abs_path)
            return True
        if action == "pex":
            fn = self._pex_jump()
            if fn is not None:
                fn("image", iid, self._scan_dir)
            return True
        if action == "fonts":
            return self.open_fonts(iid)
        if action == "scenes":
            return self.open_scenes(iid)
        if not iid.startswith(GROUP_IID):
            return None
        key = iid[len(GROUP_IID):]
        kids = list(self._view_groups.get(key) or [])
        if action == "group_assign":
            return self._group_assign(iid, kids)
        if action == "group_blank":
            return self._group_blank(iid, kids)
        if action == "group_clear":
            return self._group_apply(iid, kids, None)
        if action == "group_rename":
            return self.rename_info(key)
        return None

    # ------------------------------------------------------------------
    # group bulk actions (Tk 10473-10600)
    # ------------------------------------------------------------------
    def _group_generic(self, key):
        generic = next((label for gkey, label, _o in self._groups.values()
                        if gkey == key), "")
        if not generic and key.startswith("dir::"):
            generic = key[len("dir::"):]
        return generic

    @rpc
    def rename_info(self, key):
        generic = self._group_generic(key)
        return {"key": key, "title": "Rename Group",
                "prompt": "Display name for this group\n"
                          "(blank restores \"%s\"):"
                          % (generic or "the original name"),
                "initial": self._group_tags.get(key, generic)}

    @rpc
    def rename_group(self, key, name):
        """Tk _image_group_rename, after the page's prompt (None = the
        prompt was cancelled)."""
        if name is None:
            return False
        generic = self._group_generic(key)
        name = " ".join(str(name).split())[:50]
        if not name or name == generic:
            self._group_tags.pop(key, None)
        else:
            self._group_tags[key] = name
        self._save_staged_changes()
        self._refresh_image_list()
        self._focus([GROUP_IID + key], GROUP_IID + key)
        return True

    def _group_apply(self, group_iid, rels, rep_path):
        rels = [rel for rel in rels if rel in self._by_rel]
        if rep_path is None:
            if not self._clear_replacement_picks(rels, reselect=False):
                return 0
        else:
            if not rels:
                return 0
            for rel in rels:
                self._assignments[rel] = rep_path
            self._save_staged_changes()
            self.log("Replace Images: assigned %s to %d slot(s) in group"
                     % (os.path.basename(rep_path), len(rels)), "info")
            self._refresh_image_list()
            if self._current_rel in set(rels):
                self._render_preview(self._current_rel)
        self._focus([group_iid], group_iid)
        return len(rels)

    def _group_assign(self, group_iid, rels):
        if not rels:
            return 0
        path = self._pick(
            self.window.ask_open, "image_replacement",
            "Choose a replacement for %d images" % len(rels),
            self._image_filetypes())
        if not path:
            return 0
        return self._group_apply(group_iid, rels, path)

    def _group_blank(self, group_iid, rels):
        if not rels:
            return 0
        n = len(rels)
        if not compat.messagebox.askyesno(
                "Blank Images",
                "Assign a transparent image to all %d image%s in this "
                "group?\n\nThey'll render as fully transparent once you "
                "build the update on the Write tab (and can be cleared "
                "again from this menu until then)."
                % (n, "" if n == 1 else "s")):
            return 0
        blank = self._ensure_blank_image()
        if not blank:
            compat.messagebox.showerror(
                "Blank Images",
                "Couldn't create the transparent placeholder image in the "
                "assets folder — check the folder is writable.")
            return 0
        return self._group_apply(group_iid, rels, blank)

    def _ensure_blank_image(self):
        assets = self._scan_dir or self._assets_dir()
        if not assets or not os.path.isdir(assets):
            return ""
        path = os.path.join(assets, ".blank.png")
        if os.path.isfile(path):
            return path
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(_BLANK_PNG_B64))
        except OSError:
            return ""
        return path

    # ------------------------------------------------------------------
    # Fonts / Scenes windows, reveal
    # ------------------------------------------------------------------
    def _assets_dir_or_warn(self, noun):
        assets = self._assets_dir()
        if not assets or not os.path.isdir(assets):
            compat.messagebox.showinfo(
                noun, "Pick your extracted project folder first (Extract "
                      "tab) — the %s window works on an extracted Stern "
                      "Spike 2 card." % noun)
            return None
        return assets

    @rpc
    def open_fonts(self, rel=None):
        """Tk _open_font_studio: the Fonts window (the Text tab's service
        draws it over any tab), on the font owning glyph row *rel*."""
        assets = self._assets_dir_or_warn("Fonts")
        if assets is None:
            return False
        return bool(self.window.open_font_studio(assets, preselect_rel=rel))

    @rpc
    def open_scenes(self, rel=None):
        """Tk _open_scene_browser: the Scenes window, on the scene holding
        image row *rel* (a glyph finds its atlas's scene)."""
        assets = self._assets_dir_or_warn("Scenes")
        if assets is None:
            return False
        return bool(self.window.open_scene_browser(assets,
                                                   preselect_rel=rel))

    def _reveal_in_file_manager(self, path):
        if not path:
            return
        path = os.path.abspath(path)
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            if sys.platform == "win32":
                if os.path.isfile(path):
                    subprocess.Popen(
                        'explorer /select,"%s"' % os.path.normpath(path))
                else:
                    os.startfile(folder)                 # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", "-R", path] if os.path.isfile(path)
                    else ["open", folder])
            else:
                from ...core import desktop
                ok, err = desktop.open_path(folder)
                if not ok:
                    raise RuntimeError(err)
        except Exception as e:                           # noqa: BLE001
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, e))

    def reveal_image_slot(self, rel):
        """Scene Browser: show one image slot here (clearing any filter that
        would hide it)."""
        self.window.select_tab(self.ns)
        if rel not in self._by_rel:
            return
        if rel not in self._shown_rels():
            self._quiet += 1
            try:
                self.image_search_var.set("")
                self.image_source_filter_var.set("All sources")
                self.image_change_filter_var.set("All")
            finally:
                self._quiet -= 1
            if self.image_group_by_scene_var.get():
                self._open_groups.add(self._group_of(rel)[0])
            self._refresh_image_list()
        if self.image_group_by_scene_var.get() and \
                rel not in self._shown_rels():
            for key, kids in self._view_groups.items():
                if rel in kids:
                    self._open_groups.add(key)
                    break
            self._refresh_image_list()
        self._focus([rel], rel)
        self.select(rel)

    # ------------------------------------------------------------------
    # what the run logic reads, and the cross-tab fan-outs
    # ------------------------------------------------------------------
    def pending_image_assignments(self, assets_dir):
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_image",
                                      False):
            return None
        if not assets_dir:
            return None
        if _norm(assets_dir) != _norm(self._scan_dir or ""):
            return None
        assignments = {rel: rep for rel, rep in self._assignments.items()
                       if rep and rel in self._by_rel}
        if not assignments:
            return None
        return (dict(self._by_rel), assignments,
                frozenset(r for r in self._keep_size if r in assignments))

    def invalidate_asset_scans(self, rescan_visible=True):
        if self._scan_dir:
            self._scan_dir_prev = self._scan_dir
        self._scan_dir = ""
        if rescan_visible and self._is_current_tab() and self._visible_mfr:
            self._scan_image_slots_async()

    def reload_assets_tabs(self):
        self.invalidate_asset_scans(rescan_visible=False)
        self.window._relink_hint_for = None
        if getattr(self, "_visible", False):
            self._scan_image_slots_async()

    def refresh_after_revert(self):
        self._changed_on_disk = set()
        self._foreign_rels = set()
        self._refresh_image_list()
        if self._slots:
            self._start_change_scan()
        if self._current_rel is not None:
            self._render_preview(self._current_rel)

    def clear_replace_assignments(self, assets_dir):
        """The image part of Tk clear_replace_assignments: drop every pick and
        wipe the sidecar (keeping only what Revert all keeps).  Idempotent,
        so the other Replace tabs doing the same wipe is harmless."""
        from ...core import staged_changes
        self._assignments = {}
        kept = {}
        try:
            from ...plugins.stern import stock_modes
            kept = stock_modes.kept_by_revert_all(
                staged_changes.load(assets_dir))
        except Exception:                                # noqa: BLE001
            kept = {}
        staged_changes.save(assets_dir, kept)

    def replacement_folder_mismatches(self, assets_dir):
        if not assets_dir:
            return []
        live = [rel for rel, rep in (self._assignments or {}).items()
                if rep and rel in self._by_rel]
        if not live:
            return []
        scanned = self._scan_dir or self._scan_dir_prev or ""
        if _norm(scanned) != _norm(assets_dir):
            return [("image", len(live), scanned or "(unknown)")]
        return []

    # ------------------------------------------------------------------
    # column widths the user drags (Tk _persist_tree_columns): kept in
    # settings.json, and a dragged column stops fitting its content
    # ------------------------------------------------------------------
    #: A key of its own: Tk's "image" widths are Tk pixels for another font
    #: and a table without the thumbnail column (the Audio port's rule).
    _WIDTHS_KEY = "image_web"
    _WIDTH_COLS = ("th", "#0", "n", "res", "fmt", "src", "keep", "rep")

    def _all_widths(self):
        s = getattr(self.app, "_settings", None) if self.app else None
        widths = (s or {}).get("column_widths")
        if not isinstance(widths, dict):
            widths = dict(self.window.cb.get("initial_column_widths") or {})
        return widths

    def _saved_widths(self):
        try:
            got = self._all_widths().get(self._WIDTHS_KEY) or {}
        except Exception:                                # noqa: BLE001
            got = {}
        if not isinstance(got, dict):
            return {}
        return {k: int(v) for k, v in got.items()
                if k in self._WIDTH_COLS and not isinstance(v, bool)
                and isinstance(v, (int, float)) and v > 0}

    @rpc
    def save_widths(self, widths):
        """The columns the user just dragged, ``{col: px}``.  Like Tk's
        _save_tree_columns only those are added to the saved set; the others
        keep fitting their content."""
        changed = {str(k): int(v) for k, v in (widths or {}).items()
                   if str(k) in self._WIDTH_COLS
                   and not isinstance(v, bool)
                   and isinstance(v, (int, float)) and 20 <= v <= 4000}
        if not changed:
            return False
        tuned = self._saved_widths()
        tuned.update(changed)
        allw = dict(self._all_widths())
        allw[self._WIDTHS_KEY] = tuned
        self.set(widths=tuned)
        cb = self.window.cb.get("on_column_widths_change")
        if cb is not None:
            cb(allw)
        return True


TAB = ImagesTab
