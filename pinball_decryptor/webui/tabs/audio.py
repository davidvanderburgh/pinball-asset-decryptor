"""Replace Audio tab: the Tk tab (gui/main_window.py ``_build_audio_tab`` and
the ``_audio_*`` methods it wires) on the web UI.

Everything the Tk tab decided stays decided here, in Python, by the same
core calls: the slot scan (``core.audio_slots``), the categories
(``core.audio_categories``), the change diff (``core.checksums`` +
``core.staged_originals``), the staged-changes sidecar
(``core.staged_changes`` + ``core.history_log``), folder matching
(``core.folder_match``), renames (``core.name_memory``), and the spectrogram
(``core.audio.render_spectrogram_png``).  The page renders the list and the
two preview panes and plays sound with its own ``<audio>`` elements; the
Python side tells it what to play (``audio_play`` / ``audio_stop`` events)
and it reports back when a clip ends on its own (sequential play).

Store namespace ``audio`` (what ``static/js/tabs/audio.js`` renders):

  folder, folder_note     the project folder mirror (path, or the note)
  ffmpeg_missing          the red ffmpeg banner
  scanning, empty         the scan state and the empty-list text
  rows                    the visible table rows (see :meth:`_refresh_list`)
  status                  "N of M slots changed  (K shown)  ·  still checking…"
  sel, cur                the selected slot rows, and the first one's state
  panes                   {orig, rep}: the two preview panes
  ...and the capability gates (col, level_cap, dups_cap, adv_cap, trim_visible)
"""

import csv
import os
import re
import sys
import threading
import time

from .. import compat
from .base import TabService, rpc

#: The tail the count line wears while the change diff runs.
_CHANGE_SCAN_NOTE = "  ·  still checking…"
#: Row id prefix of a "Group duplicates" parent row.
_GROUP = "::dupgrp::"
_NOT_ON_CARD_MARK = "⚠ not on this card"
_NO_PROJECT_NOTE = "(no project yet — extract into one on the Extract tab)"

_TYPE_KEYS = {"Music": "music", "Sound FX": "sfx", "Callouts": "callouts",
              "Other": "other"}
_CAT_DISP = {"music": "Music", "sfx": "Sound FX", "callouts": "Callouts"}
_CAT_NAMES = (("music", "Music"), ("sfx", "Sound FX"),
              ("callouts", "Callouts"), ("other", "Other"))
_CHANGE_FILTER_VALUES = ("All", "Changed", "Unchanged")

_AUDIO_FILETYPES = [("Audio files",
                     "*.wav *.ogg *.mp3 *.flac *.m4a *.aac *.opus "
                     "*.wma *.aiff *.aif"),
                    ("All files", "*.*")]
_FOLDER_MATCH_EXTS = (".wav", ".ogg", ".mp3", ".flac", ".m4a", ".aac",
                      ".opus", ".wma", ".aiff", ".aif")

#: Click-header sort: (column id, heading, default descending).
_SORT_CFG = (("#0", "Original Track", False), ("len", "Length", True),
             ("fmt", "Format", False), ("type", "Type", False),
             ("rep", "Replacement", False), ("loop", "Loop", True),
             ("keep", "Full", True), ("lvl", "Level", True))
_SORT_DEFAULT_DESC = {c: d for c, _h, d in _SORT_CFG}

# Keep in step with App._AUDIO_ADV_DEFAULTS (and the Tk dialog).
ADV_DEFAULTS = {
    "head_mode": "encode", "leadout": "silence", "previews": False,
    "experiment_idxs": "", "slot_seed": False, "slot_seed_db": 65,
    "blip_free_optin": False, "audio_grow": False,
    "loudness": "match", "loudness_db": 0,
}
LOUDNESS_CHOICES = (
    ("match", "Match the sound being replaced (default)"),
    ("full", "Normalize each replacement to full scale"),
)
HEAD_CHOICES = (
    ("encode", "Re-encode from the first sample (default)"),
    ("stock", "Keep the stock head block (experimental, first 4.5 ms)"),
)
LEADOUT_CHOICES = (
    ("silence", "Encode the tail block to silence (default)"),
    ("stock", "Keep the stock tail scrap (pre-v0.71.1 behavior)"),
)

_FFMPEG_WARN = (
    "ffmpeg not found — you can still swap files already in the game's "
    "format (.wav→.wav, .ogg→.ogg), but converting other formats (mp3, "
    "flac, …) or matching sample rate needs ffmpeg. Install it with "
    "“Install Missing” above the tabs.")

#: Spectrogram strip size the page stretches to its pane.
_SPEC_W, _SPEC_H = 800, 90


class _ProfileButton:
    """What ``App._on_audio_profile_request`` drives as the "Profile vs
    stock" button: ``cget("state")`` / ``configure(state=...)``, mirrored
    into the page as ``audio.profile_busy``."""

    def __init__(self, svc):
        self._svc = svc
        self._state = "normal"

    def cget(self, key):
        return self._state if key == "state" else ""

    def configure(self, **kw):
        if "state" in kw:
            self._state = str(kw["state"])
            self._svc.set(profile_busy=self._state == "disabled")

    config = configure

    def winfo_ismapped(self):
        return bool(self._svc.get("adv_cap"))

    def pack(self, *_a, **_k):
        pass

    pack_forget = pack


class AudioTab(TabService):
    ns = "audio"
    key = "Replace Audio"
    label = "Audio"
    group = "Replace"
    icon = "audio"
    exports = (
        "pending_audio_assignments", "audio_keep_full_rels",
        "audio_loop_basenames", "audio_trim_var", "_audio_grow_active",
        "_audio_profile_btn",
    )

    def __init__(self, window):
        super().__init__(window)
        # Tk variables (same names and defaults as MainWindow's)
        self.audio_trim_var = self.var("trim", "bool", False)
        self.audio_search_var = self.var("search", "str", "")
        self.audio_type_var = self.var("type", "str", "All types")
        self.audio_change_filter_var = self.var("show", "str", "All")
        self.audio_play_through_var = self.var("play_through", "bool", False)
        self.audio_play_subst_var = self.var("play_subst", "bool", False)
        self.audio_group_dups_var = self.var("group_dups", "bool", False)
        self.audio_search_var.trace_add("write",
                                        lambda *a: self._refresh_list())
        self.audio_change_filter_var.trace_add(
            "write", lambda *a: self._refresh_list())
        self.audio_group_dups_var.trace_add("write",
                                            lambda *a: self._refresh_list())
        self._audio_profile_btn = _ProfileButton(self)

        self._slots = []
        self._by_rel = {}
        self._assign = {}           # rel -> replacement path
        self._loop = {}             # rel -> bool (BOF)
        self._keep = {}             # rel -> bool (JJP)
        self._level = {}            # rel -> int dB (Stern)
        self._keep_whole = []       # ordered rels (Stern Spike 2 grow)
        self._cats = {}
        self._music_by_length = True
        self._sort = ("#0", False)
        self._scan_id = 0
        self._scan_dir = ""
        self._scan_dir_prev = ""
        self._scanning = False
        self._scan_t0 = None
        self._cancelled = False
        self._dup_groups = None     # [(label, dur_str, [rel, ...]), ...]
        self._dup_scan_dir = ""
        self._dup_scan_id = 0
        self._dup_scanning = False
        self._open_groups = set()
        self._changed = set()
        self._foreign = set()
        self._twins = {}
        self._change_scan_id = 0
        self._change_running = False
        self._foreign_notes = {}
        self._rep_names = {}
        self._rep_names_dir = ""
        self._status_base = ""
        self._visible_rels = []
        self._row_index = {}
        self._sel = []
        self._current_rel = None
        self._select_job = None
        self._advance_job = None
        self._level_job = None
        self._traced_assets = None
        self._advanced = dict(window.cb.get("initial_audio_advanced") or {})
        self._panes = {"orig": self._blank_pane("Original"),
                       "rep": self._blank_pane("Replacement",
                                               "no replacement assigned")}
        self._pane_ids = {"orig": 0, "rep": 0}
        self.set(rows=[], sel=[], cur=None, status="", empty="",
                 scanning=False, folder="", folder_note=_NO_PROJECT_NOTE,
                 ffmpeg_missing=False, ffmpeg_text=_FFMPEG_WARN,
                 col=None, level_cap=False, dups_cap=False, adv_cap=False,
                 trim_visible=True, trim_tip="", type_useful=False,
                 level="0", level_enabled=False, can_clear=False,
                 running=False, profile_busy=False, adv_marker=False,
                 prefix="", sort={"key": "#0", "desc": False},
                 panes=dict(self._panes), dup_scanning=False,
                 widths=self._saved_widths(), pex=False)

    # ------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _blank_pane(base, hint=""):
        return {"base": base, "name": "", "path": None, "dur": 0.0,
                "limit": None, "grow_from": None, "gain": 0.0,
                "hint": hint, "spec": None, "spec_state": "", "v": 0}

    def _assets_var(self):
        return getattr(self.window, "write_assets_var", None)

    def _assets(self):
        var = self._assets_var()
        return ((var.get() if var is not None else "") or "").strip()

    @staticmethod
    def _norm(p):
        return os.path.normcase(os.path.normpath(p or ""))

    def _running(self):
        return bool(getattr(self.window, "_running", False))

    def _post(self, fn, *args):
        self.ctx.loop.post(fn, *args)

    def _after(self, ms, fn, *args):
        return self.ctx.loop.after(ms, fn, *args)

    def _cancel(self, tid):
        if tid:
            self.ctx.loop.after_cancel(tid)

    def _publish(self, event, **data):
        self.ctx.bus.publish(event, **data)

    def _ask_path(self, mode, key, title, **opts):
        """``window.ask_open`` / ``ask_folder`` / ``ask_save`` with the Tk
        ``last_browse_dir`` rule: the folder remembered for *key* is where the
        picker opens only while it still exists.  One since deleted or renamed
        opens the picker's own default instead of "[WinError 3]" over an empty
        listing (Tk: ``v if v and os.path.isdir(v) else None``)."""
        start = self.window.last_browse_dir(key)
        if not (start and os.path.isdir(start)):
            start = ""
        fd = compat.filedialog
        if mode == "open":
            path = fd.askopenfilename(title=title, initialdir=start, **opts)
        elif mode == "folder":
            path = fd.askdirectory(title=title, initialdir=start)
        else:
            path = fd.asksaveasfilename(title=title, initialdir=start, **opts)
        if path:
            first = path[0] if isinstance(path, (list, tuple)) else path
            # Tk remember_browse_dir: only a folder that exists is kept
            folder = first if os.path.isdir(first) else os.path.dirname(first)
            if folder and os.path.isdir(folder):
                self.window.remember_browse_dir(key, folder)
        return path

    # ------------------------------------------------------------------
    # manufacturer / show / running
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        caps = mfr.capabilities
        self._watch_assets()
        # the Tk apply_manufacturer's clean slate
        self._slots = []
        self._by_rel = {}
        self._assign = {}
        self._loop = {}
        self._keep = {}
        self._level = {}
        self._scan_dir = ""
        self._dup_groups = None
        self._dup_scan_dir = ""
        self._open_groups = set()
        self._cancelled = False
        self._sel = []
        self.audio_group_dups_var.set(False)
        if getattr(caps, "audio_loop_inject", False):
            col = "loop"
        elif getattr(caps, "audio_keep_length_override", False):
            col = "keep"
        elif getattr(caps, "audio_level_offset", False):
            col = "lvl"
        else:
            col = None
        self.set(col=col,
                 level_cap=bool(getattr(caps, "audio_level_offset", False)),
                 dups_cap=getattr(mfr, "find_duplicate_sounds", None)
                 is not None,
                 adv_cap=(mfr.key == "stern"), sel=[],
                 pex=bool(getattr(caps, "partition_explorer", False)),
                 profile_busy=False)
        self._audio_profile_btn._state = "normal"
        self._clear_preview()
        self._refresh_list()
        self._apply_trim_lock(mfr)
        self._refresh_adv_marker()
        self._refresh_folder()

    def on_show(self):
        self._refresh_ffmpeg_warning()
        self._default_assets_from_extract()
        self._refresh_folder()
        self._maybe_rescan()

    def on_running(self, running, mode):
        self.set(running=bool(running))
        self._update_clear_all()

    def on_close(self):
        self.stop_all_preview_playback()
        try:
            from .. import audio_media
            audio_media.cleanup()
        except Exception:                               # noqa: BLE001
            pass

    def _watch_assets(self):
        """Follow the shared project folder (a var another tab owns; looked
        up once every tab exists, so a missing owner is its gap, not ours)."""
        var = self._assets_var()
        if var is None or var is self._traced_assets:
            return
        self._traced_assets = var
        try:
            var.trace_add("write", lambda *a: self._refresh_folder())
        except Exception:                               # noqa: BLE001
            pass

    def _refresh_folder(self):
        path = self._assets()
        self.set(folder=path, folder_note="" if path else _NO_PROJECT_NOTE)

    def _refresh_ffmpeg_warning(self):
        from ...core import audio as _audio
        _audio._ffmpeg_path = None      # a fresh probe, not the cached one
        self.set(ffmpeg_missing=not _audio.find_ffmpeg())

    def _default_assets_from_extract(self):
        var = self._assets_var()
        if var is None or (var.get() or "").strip():
            return
        out_var = getattr(self.window, "extract_output_var", None)
        out = ((out_var.get() if out_var is not None else "") or "").strip()
        if out and os.path.isdir(out):
            var.set(out)

    def _maybe_rescan(self):
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_audio",
                                      False):
            return
        path = self._assets()
        if path and path != self._scan_dir:
            self._scan_async()

    # ------------------------------------------------------------------
    # fan-out calls the run logic makes (window._fan)
    # ------------------------------------------------------------------
    def invalidate_asset_scans(self, rescan_visible=True):
        if self._scan_dir:
            self._scan_dir_prev = self._scan_dir
        self._scan_dir = ""
        if rescan_visible and self.window.current_tab_key() == self.key:
            self._scan_async()

    def reload_assets_tabs(self):
        self.invalidate_asset_scans(rescan_visible=False)
        self.window._relink_hint_for = None
        if getattr(self, "_visible", False):
            self._scan_async()

    def stop_all_preview_playback(self):
        self._cancel_advance()
        self._publish("audio_stop")

    def clear_replace_assignments(self, assets_dir):
        from ...core import staged_changes
        self._assign = {}
        kept = {}
        try:
            from ...plugins.stern import stock_modes
            kept = stock_modes.kept_by_revert_all(
                staged_changes.load(assets_dir))
        except Exception:                               # noqa: BLE001
            kept = {}
        staged_changes.save(assets_dir, kept)

    def refresh_after_revert(self):
        self._changed = set()
        self._foreign = set()
        self._refresh_list()
        if self._slots:
            self._start_change_scan()

    def replacement_folder_mismatches(self, assets_dir):
        if not assets_dir:
            return []
        live = [rel for rel, rep in (self._assign or {}).items()
                if rep and rel in self._by_rel]
        if not live:
            return []
        scanned = self._scan_dir or self._scan_dir_prev or ""
        if self._norm(scanned) != self._norm(assets_dir):
            return [("audio", len(live), scanned or "(unknown)")]
        return []

    # ------------------------------------------------------------------
    # what the Write flow reads (same guards as the Tk window)
    # ------------------------------------------------------------------
    def _folder_matches(self, assets_dir):
        return self._norm(assets_dir) == self._norm(self._scan_dir or "")

    def pending_audio_assignments(self, assets_dir):
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_audio",
                                      False):
            return None
        if not assets_dir or not self._folder_matches(assets_dir):
            return None
        assignments = {rel: rep for rel, rep in self._assign.items()
                       if rep and rel in self._by_rel}
        if not assignments:
            return None
        keep_full = frozenset(rel for rel in assignments
                              if self._keep.get(rel))
        return (dict(self._by_rel), assignments,
                bool(self.audio_trim_var.get()), keep_full)

    def audio_keep_full_rels(self, assets_dir):
        mfr = self.mfr
        if mfr is None or not getattr(
                mfr.capabilities, "audio_keep_length_override", False) \
                or not assets_dir:
            return frozenset()
        if not self._folder_matches(assets_dir):
            return frozenset()
        return frozenset(rel for rel, rep in self._assign.items()
                         if rep and rel in self._by_rel
                         and self._keep.get(rel))

    def audio_loop_basenames(self, assets_dir):
        mfr = self.mfr
        if mfr is None or not getattr(
                mfr.capabilities, "audio_loop_inject", False) \
                or not assets_dir:
            return frozenset()
        if not self._folder_matches(assets_dir):
            return frozenset()
        return frozenset(os.path.basename(rel)
                         for rel, rep in self._assign.items()
                         if rep and rel in self._by_rel
                         and self._loop.get(rel))

    def _audio_grow_active(self):
        mfr = self.mfr
        if getattr(mfr, "key", None) != "stern":
            return False
        if getattr(mfr, "current_era", "spike2") != "spike2":
            return False
        return bool(self._advanced.get("audio_grow"))

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------
    def _scan_async(self):
        from ...core.audio_slots import scan_audio_slots

        assets_path = self._assets()
        self._scan_id += 1
        scan_id = self._scan_id
        self._cancelled = False
        if not assets_path or not os.path.isdir(assets_path):
            self._slots = []
            self._by_rel = {}
            self._cats = {}
            self._refresh_type_filter()
            if self._scanning:
                self._set_scanning(False)
            self._refresh_list()
            return
        mfr = self.mfr

        def _work():
            try:
                roots = mfr.audio_slot_dirs(assets_path) if mfr else None
            except Exception:                           # noqa: BLE001
                roots = None
            try:
                exts = mfr.audio_slot_exts(assets_path) if mfr else None
            except Exception:                           # noqa: BLE001
                exts = None
            try:
                slots = scan_audio_slots(assets_path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:                           # noqa: BLE001
                slots = []
            try:
                from ...core import audio_categories
                cats = audio_categories.classify(
                    assets_path, [s.rel_path for s in slots])
            except Exception:                           # noqa: BLE001
                cats = {}
            if self._scan_id != scan_id:
                return
            self._post(self._populate_after_scan, slots, scan_id,
                       assets_path, cats)

        self._set_scanning(True)
        threading.Thread(target=_work, daemon=True,
                         name="pad-audio-scan").start()

    def _set_scanning(self, active):
        if active:
            if self._scan_t0 is not None:
                self.log("Audio scan replaced after %.1f s by a newer scan."
                         % (time.monotonic() - self._scan_t0), "info")
            self._scan_t0 = time.monotonic()
            self.log("Audio scan started.", "info")
            self._scanning = True
            self.set(scanning=True, rows=[],
                     empty="Scanning for audio files…")
        else:
            t0, self._scan_t0 = self._scan_t0, None
            if t0 is not None:
                self.log("Audio scan finished in %.1f s."
                         % (time.monotonic() - t0), "info")
            self._scanning = False
            self.set(scanning=False)

    @rpc
    def scan(self):
        """The Scan button (it reads "Cancel scan" while a scan runs)."""
        if self._scanning:
            return self.cancel_scan()
        self._scan_async()
        return True

    @rpc
    def cancel_scan(self):
        self._scan_id += 1
        t0, self._scan_t0 = self._scan_t0, None
        if t0 is not None:
            self.log("Audio scan cancelled after %.1f s."
                     % (time.monotonic() - t0), "info")
        self._scanning = False
        self._cancelled = True
        self.set(scanning=False, rows=[],
                 empty="Scan cancelled — click Scan to try again.")
        return True

    def _populate_after_scan(self, slots, scan_id, scan_dir, cats=None):
        from ...core import staged_changes
        if self._scan_id != scan_id:
            return
        self._set_scanning(False)
        self._cats = cats or {}
        if scan_dir != self._scan_dir:
            self.audio_type_var.set("All types")
        self._refresh_type_filter()
        if scan_dir == self._scan_dir:
            old = self._by_rel
            for s in slots:
                prev = old.get(s.rel_path)
                if (prev is not None and prev.info is not None
                        and s.info is None and s.size == prev.size):
                    s.info = prev.info
        self._slots = slots
        self._by_rel = {s.rel_path: s for s in slots}
        saved_loops, saved_keep = {}, {}
        saved_levels = saved_keep_whole = None
        persisted_trim = bool(self.audio_trim_var.get())
        if scan_dir != self._scan_dir:
            staged = self._load_staged_changes(scan_dir)
            self._assign = staged_changes.live_assignments(
                staged.get("audio"), self._by_rel)
            self._warn_dropped_assignments(staged.get("audio"), scan_dir)
            saved_loops = staged.get("audio_loop") or {}
            saved_keep = staged.get("audio_keep") or {}
            saved_levels = staged.get("audio_levels") or {}
            saved_keep_whole = list(staged.get("grow_keep_whole") or [])
            persisted_trim = bool(staged.get("audio_trim", False))
            self._restore_change_filter(staged)
            self.audio_group_dups_var.set(False)
        else:
            self._assign = {rel: rep for rel, rep in self._assign.items()
                            if rel in self._by_rel}
        self._loop = {
            s.rel_path: (bool(saved_loops[s.rel_path])
                         if s.rel_path in saved_loops
                         else self._loop.get(
                             s.rel_path,
                             "loop" in os.path.basename(s.rel_path).lower()))
            for s in slots}
        self._keep = {
            s.rel_path: (bool(saved_keep[s.rel_path])
                         if s.rel_path in saved_keep
                         else self._keep.get(s.rel_path, False))
            for s in slots}
        levels = self._level if saved_levels is None else saved_levels
        self._level = {}
        for rel, db in levels.items():
            if rel not in self._by_rel:
                continue
            try:
                db = int(db)
            except (TypeError, ValueError):
                continue
            if db:
                self._level[rel] = max(min(db, 12), -12)
        keep_whole = (self._keep_whole if saved_keep_whole is None
                      else saved_keep_whole)
        self._keep_whole = [r for r in keep_whole if r in self._by_rel]
        self._scan_dir = scan_dir
        self._apply_trim_lock(self.mfr, scan_dir,
                              persisted_trim=persisted_trim)
        self._changed = set()
        self._foreign = set()
        if self._dup_scan_dir and self._dup_scan_dir != scan_dir:
            self._dup_groups = None
        elif (self._dup_groups is not None
              and any(r not in self._by_rel
                      for _l, _d, rels in self._dup_groups for r in rels)):
            self._dup_groups = None
        self.set(prefix=self._common_prefix())
        if self.audio_group_dups_var.get():
            self._ensure_dup_groups(quiet=True)
        self._refresh_list()
        self._select_first_row()
        self._start_change_scan()
        self._probe_metadata_async(scan_id)

    def _common_prefix(self):
        """The folder most slots share ("audio/" on a Stern extract), so the
        list can leave it off those rows (display only; a row in any other
        folder still shows its folder, and the full path is its tooltip)."""
        import collections
        dirs = collections.Counter(s.rel_path.rpartition("/")[0]
                                   for s in self._slots)
        if not dirs:
            return ""
        d, n = dirs.most_common(1)[0]
        if not d or n * 2 < len(self._slots):
            return ""
        return d + "/"

    def _select_first_row(self):
        if not self._visible_rels:
            return
        self._sel = [self._visible_rels[0]]
        self.set(sel=list(self._sel))
        self._on_select(None)

    def _probe_metadata_async(self, scan_id):
        import queue as queue_mod
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ...core.audio import detect_audio_info

        pending = [s for s in self._slots if s.info is None]
        if not pending:
            return
        q = queue_mod.SimpleQueue()
        done = threading.Event()

        def _coordinator():
            try:
                workers = min(8, (os.cpu_count() or 4))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(detect_audio_info, s.abs_path): s
                            for s in pending}
                    for fut in as_completed(futs):
                        if self._scan_id != scan_id:
                            for f in futs:
                                f.cancel()
                            return
                        try:
                            info = fut.result()
                        except Exception:               # noqa: BLE001
                            info = None
                        q.put((futs[fut].rel_path, info))
            except Exception:                           # noqa: BLE001
                pass
            finally:
                done.set()

        def _drain():
            if self._scan_id != scan_id:
                return
            for _ in range(500):
                try:
                    rel, info = q.get_nowait()
                except queue_mod.Empty:
                    break
                self._apply_meta(scan_id, rel, info)
            if not (done.is_set() and q.empty()):
                self._after(100, _drain)

        threading.Thread(target=_coordinator, daemon=True,
                         name="pad-audio-probe").start()
        self._after(0, _drain)

    def _apply_meta(self, scan_id, rel, info):
        if self._scan_id != scan_id:
            return
        slot = self._by_rel.get(rel)
        if slot is None:
            return
        slot.info = info
        i = self._row_index.get(rel)
        if i is not None:
            self.patch_item("rows", i, len=slot.duration_str(),
                            fmt=slot.format_summary())

    # ------------------------------------------------------------------
    # the on-disk change diff
    # ------------------------------------------------------------------
    def _start_change_scan(self):
        from ...core import checksums, staged_originals

        assets_path = self._assets()
        rels = [s.rel_path for s in self._slots]
        self._change_scan_id += 1
        scan_id = self._change_scan_id
        if not assets_path or not os.path.isdir(assets_path) or not rels:
            self._changed = set()
            self._foreign = set()
            self._twins = {}
            self._mark_change_scan(False)
            return
        self._mark_change_scan(True)

        def _work():
            from ...core import folder_match
            foreign, twins = set(), {}
            try:
                baseline = checksums.read_baseline_any(assets_path)
                rel_set = set(rels)
                snaps = {r for r in staged_originals.snapshot_rels(
                    assets_path) if r in rel_set}
                to_hash = [r for r in rels if r not in snaps]
                changed = snaps | checksums.changed_rels(
                    assets_path, to_hash, baseline=baseline)
                if baseline:
                    foreign, twins = folder_match.foreign_twins(rels,
                                                                baseline)
            except Exception:                           # noqa: BLE001
                changed = set()
            self._post(_apply, changed, foreign, twins)

        def _apply(changed, foreign, twins):
            if self._change_scan_id != scan_id:
                return
            self._changed = set(changed)
            self._foreign = set(foreign)
            self._twins = dict(twins or {})
            self._mark_change_scan(False)
            self._note_foreign_slots(assets_path, self._foreign, self._twins)
            self._refresh_list()
            self._publish_cur()

        self._after(0, lambda: threading.Thread(
            target=_work, daemon=True, name="pad-audio-diff").start())

    def _mark_change_scan(self, running):
        self._change_running = bool(running)
        self._publish_status()

    def _note_foreign_slots(self, assets_path, foreign, twins=None):
        key = self._norm(assets_path)
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
            % ("Audio", len(foreign), shown), "warning")
        twins = twins or {}
        if twins:
            rel = sorted(twins)[0]
            self.log(
                "%s: %d of them are named like one of the card's files but "
                "are a different file type (%s where the card has %s), so "
                "they sit beside their slot instead of in it. Keep your files "
                "in a folder of their own and use \"Replace from folder…\": "
                "it matches names whatever the file type."
                % ("Audio", len(twins), os.path.basename(rel),
                   os.path.basename(twins[rel])), "warning")

    def _not_on_card(self, rel):
        return rel is not None and rel in self._foreign

    def _changed_on_disk(self, rel):
        if rel in self._changed:
            return True
        from ...core import staged_originals
        return staged_originals.snapshot_path(self._scan_dir, rel) is not None

    def _changed_on_disk_cell(self, rel):
        name = self._remembered_rep_name(rel)
        return ("✓ changed on disk (%s)" % name if name
                else "✓ changed on disk")

    def _rep_pane_empty_text(self, rel, default):
        from ...core import staged_originals
        if rel is None or not self._changed_on_disk(rel):
            return default
        if self._not_on_card(rel):
            twin = (self._twins or {}).get(rel)
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
                        % (os.path.basename(twin), os.path.basename(rel),
                           fix))
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
        if staged_originals.snapshot_path(self._scan_dir, rel):
            return default
        return ("already changed on disk — the change is on the left, and it "
                "is what the next build puts on the card. No original was "
                "saved for this slot.")

    # ------------------------------------------------------------------
    # the staged-changes sidecar
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
        if self._norm(self._scan_dir) != self._norm(
                self._rep_names_dir or "\0"):
            return ""
        return self._rep_names.get(rel, "")

    def _warn_dropped_assignments(self, saved, scan_dir):
        from ...core import staged_changes, staged_originals
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
                    % (rel, "audio", why, path, hint), "info")
            else:
                any_pending = True
                self.log(
                    'Saved %s replacement for "%s" wasn\'t restored — %s:\n'
                    '        %s%s' % ("audio", rel, why, path, hint), "error")
        if len(dropped) > 6:
            self.log("…and %d more saved %s replacement(s) like this."
                     % (len(dropped) - 6, "audio"),
                     "error" if any_pending else "info")
        key = self._norm(scan_dir)
        if getattr(self.window, "_relink_hint_for", None) != key:
            self.window._relink_hint_for = key
            self.log(
                'Moved this project (or the files it points at) to another '
                'PC or drive? Project ▾ → "Relink moved files…" searches a '
                'folder you pick and re-points every one of these at once.',
                "info")

    def _restore_change_filter(self, staged):
        val = staged.get("audio_change_filter")
        if val in _CHANGE_FILTER_VALUES:
            self.audio_change_filter_var.set(val)
        elif "audio_changed_only" in staged:
            self.audio_change_filter_var.set(
                "Changed" if staged["audio_changed_only"] else "All")

    def _save_staged_changes(self):
        """Persist this tab's part of the folder's sidecar (the Tk window's
        ``_save_staged_changes``, audio sections): every other tab's
        sections are read back and kept."""
        from ...core import history_log, staged_changes
        assets_dir = self._assets()
        if not assets_dir or not os.path.isdir(assets_dir):
            return
        if not (self._scan_dir and self._norm(self._scan_dir)
                == self._norm(assets_dir)):
            return
        data = staged_changes.load(assets_dir)
        hist = history_log.diff_assignments("audio", data.get("audio"),
                                            self._assign)
        hist.append(history_log.diff_scalar(
            'audio  option "Trim / pad replacements to the original '
            'slot length"',
            data.get("audio_trim"), bool(self.audio_trim_var.get())))
        data["audio"] = dict(self._assign)
        data["audio_loop"] = dict(self._loop)
        data["audio_keep"] = dict(self._keep)
        data["audio_levels"] = {rel: int(db) for rel, db
                                in self._level.items() if db}
        data["grow_keep_whole"] = [r for r in self._keep_whole
                                   if r in self._by_rel]
        data["audio_trim"] = bool(self.audio_trim_var.get())
        data["audio_change_filter"] = self.audio_change_filter_var.get()
        names = dict(data.get("replacement_names") or {})
        for rel, path in self._assign.items():
            if isinstance(path, str) and path.strip():
                names[rel] = os.path.basename(path)
        if names:
            data["replacement_names"] = names
        staged_changes.save(assets_dir, data)
        history_log.record(assets_dir, [h for h in hist if h])
        cb = self.window.cb.get("on_folder_state_written")
        if cb is not None:
            cb(assets_dir)

    # ------------------------------------------------------------------
    # the trim / pad lock and the Advanced marker
    # ------------------------------------------------------------------
    def _apply_trim_lock(self, mfr, assets_dir=None, persisted_trim=None):
        if mfr is None:
            return False
        try:
            forces = mfr.audio_forces_length_match(assets_dir)
        except TypeError:
            forces = mfr.audio_forces_length_match()
        if forces:
            self.audio_trim_var.set(True)
        else:
            self.audio_trim_var.set(bool(persisted_trim))
        note = (mfr.audio_length_note() or "").strip()
        self.set(trim_visible=not forces,
                 trim_tip=("When on, a replacement longer or shorter than the "
                           "original is trimmed or padded to the original slot "
                           "length before Write. When off, the replacement is "
                           "used as-is." + (("\n\n" + note) if note else "")))
        return forces

    def _refresh_adv_marker(self):
        d = dict(ADV_DEFAULTS)
        d.update({k: v for k, v in self._advanced.items()
                  if k in ADV_DEFAULTS and v is not None})
        self.set(adv_marker=d != ADV_DEFAULTS)

    # ------------------------------------------------------------------
    # the list
    # ------------------------------------------------------------------
    def _refresh_type_filter(self):
        from ...core import audio_categories as _ac
        self._music_by_length = _ac.needs_length_fallback(self._cats)
        useful = any(c != "other" for c in self._cats.values())
        if not useful:
            self.audio_type_var.set("All types")
        self.set(type_useful=useful)

    def _change_filter_pred(self):
        mode = self.audio_change_filter_var.get()
        if mode not in ("Changed", "Unchanged"):
            return None
        touched = set(self._assign) | self._changed
        want = mode == "Changed"
        return lambda rel: (rel in touched) == want

    def _cat_key_fn(self):
        from ...core import audio_categories as _ac
        cats = self._cats
        by_length = bool(self._music_by_length)

        def _cat_key(s):
            dur = s.duration or _ac.name_duration_seconds(
                os.path.basename(s.rel_path)) or 0.0
            return _ac.effective_category(cats.get(s.rel_path, "other"), dur,
                                          by_length)
        return _cat_key

    def _level_disp(self, rel):
        db = self._level.get(rel) or 0
        return "%+d dB" % db if db else ""

    def _row(self, s, cat_disp, depth=0):
        rel = s.rel_path
        rep = self._assign.get(rel)
        is_changed = rel in self._changed
        if rep:
            rep_disp = os.path.basename(rep)
            tag = "ondisk" if is_changed else "picked"
        elif self._not_on_card(rel):
            rep_disp, tag = _NOT_ON_CARD_MARK, "stray"
        elif is_changed:
            rep_disp, tag = self._changed_on_disk_cell(rel), "ondisk"
        else:
            rep_disp, tag = "Choose…", ""
        row = {"k": rel, "len": s.duration_str(), "fmt": s.format_summary(),
               "type": cat_disp, "rep": rep_disp, "t": tag,
               "loop": bool(self._loop.get(rel)),
               "keep": bool(self._keep.get(rel)),
               "lvl": self._level_disp(rel)}
        if depth:
            row["d"] = depth
        return row

    def _refresh_list(self):
        """The Tk ``_refresh_audio_list``: filter, sort, (group), count."""
        query = (self.audio_search_var.get() or "").strip().lower()
        type_key = _TYPE_KEYS.get(self.audio_type_var.get())
        change_ok = self._change_filter_pred()
        _cat_key = self._cat_key_fn()

        def _cat_disp(s):
            return _CAT_DISP.get(_cat_key(s), "Other")

        def _passes(s):
            if query and query not in s.rel_path.lower():
                return False
            if change_ok is not None and not change_ok(s.rel_path):
                return False
            if type_key is None:
                return True
            return _cat_key(s) == type_key

        slots = [s for s in self._slots if _passes(s)]
        col, desc = self._sort
        changed = self._changed

        def _key(s):
            if col == "len":
                return (s.duration,)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "rep":
                rep = self._assign.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                if s.rel_path in changed:
                    return (1, "")
                return (2, "")
            if col == "loop":
                return (1 if self._loop.get(s.rel_path) else 0,)
            if col == "keep":
                return (1 if self._keep.get(s.rel_path) else 0,)
            if col == "lvl":
                return (self._level.get(s.rel_path, 0),)
            if col == "type":
                return (_cat_disp(s), s.rel_path.lower())
            return (s.rel_path.lower(),)

        rows, visible = [], []
        grouped = (bool(self.audio_group_dups_var.get())
                   and self._dup_groups is not None
                   and self._dup_scan_dir == self._scan_dir)
        if grouped:
            in_groups = set()
            for gidx, (label, dur_str, rels) in enumerate(self._dup_groups):
                members = [self._by_rel[r] for r in rels if r in self._by_rel]
                shown = [m for m in members if _passes(m)]
                if len(members) < 2 or not shown:
                    continue
                in_groups.update(m.rel_path for m in shown)
                if col == "#0":
                    if desc:
                        shown = list(reversed(shown))
                else:
                    shown = sorted(shown, key=_key, reverse=desc)
                touched_n = sum(1 for m in members
                                if m.rel_path in self._assign
                                or m.rel_path in changed)
                giid = _GROUP + str(gidx)
                is_open = giid in self._open_groups
                rows.append({
                    "k": giid, "g": 1, "open": is_open,
                    "label": "%s — %d copies" % (label, len(members)),
                    "len": dur_str,
                    "rep": ("%d of %d modded" % (touched_n, len(members))
                            if touched_n else "")})
                for m in shown:
                    visible.append(m.rel_path)
                    if is_open:
                        rows.append(self._row(m, _cat_disp(m), depth=1))
            rest = [s for s in slots if s.rel_path not in in_groups]
            rest.sort(key=_key, reverse=desc)
            for s in rest:
                visible.append(s.rel_path)
                rows.append(self._row(s, _cat_disp(s)))
        else:
            slots.sort(key=_key, reverse=desc)
            for s in slots:
                visible.append(s.rel_path)
                rows.append(self._row(s, _cat_disp(s)))

        total = len(self._slots)
        changed_total = len(set(self._assign) | changed)
        shown_n = len(slots)
        if total == 0:
            status = ""
            hint = self._idle_hint()
        else:
            extra = "  (%d shown)" % shown_n if shown_n != total else ""
            status = "%d of %d slots changed%s" % (changed_total, total,
                                                   extra)
            hint = ""
            if shown_n == 0:
                hint = "Nothing matches the Search / Show / Type filters."
                if not query and type_key == "callouts":
                    hint = ("No call-outs identified in this folder yet.\n"
                            "Tick \"Auto-name call-outs\" on the Extract tab "
                            "to transcribe and name the speech files.")
                elif not query and type_key == "music":
                    hint = ("No music identified in this folder — no music "
                            "banks and no Auto-name music results.")
                    if self._music_by_length:
                        hint = ("No music identified in this folder — no "
                                "music banks, no track 20 seconds or longer, "
                                "and no Auto-name music results.")
                elif not query and type_key is None:
                    mode = self.audio_change_filter_var.get()
                    if mode == "Unchanged":
                        hint = ("Every slot in this folder has a replacement "
                                "or already differs from the extract — "
                                "nothing is left unchanged.")
                    elif mode == "Changed":
                        hint = "Nothing in this folder has been changed yet."
        if self._scanning:
            rows, hint = [], "Scanning for audio files…"
        elif self._dup_scanning:
            rows = []
            hint = ("⏳  Scanning the sound banks for duplicates…\n"
                    "(about ten seconds)")
        self._visible_rels = visible
        self._row_index = {r["k"]: i for i, r in enumerate(rows)}
        self._status_base = status
        # keep the selection on rows that are still there
        keep = set(visible) | {r["k"] for r in rows}
        sel = [r for r in self._sel if r in keep]
        if sel != self._sel:
            self._sel = sel
        self.set(rows=rows, empty=hint, sel=list(self._sel),
                 sort={"key": col, "desc": desc},
                 dup_scanning=self._dup_scanning)
        self._publish_status()
        self._update_clear_all()
        self._level_sync()
        self._publish_cur()

    def _idle_hint(self):
        if self._cancelled:
            return "Scan cancelled — click Scan to try again."
        if not self._scan_dir:
            return "Set the project folder on the Extract tab, then click Scan."
        return "No .wav / .ogg audio found in this folder."

    def _publish_status(self, text=None):
        if text is not None:
            self._status_base = text
        base = self._status_base
        if self._change_running and base and not base.endswith(
                _CHANGE_SCAN_NOTE):
            base = base + _CHANGE_SCAN_NOTE
        self.set(status=base)

    # ------------------------------------------------------------------
    # page calls: filters, sort, groups
    # ------------------------------------------------------------------
    @rpc
    def set_show(self, value):
        """Show: All / Changed / Unchanged (persisted per folder)."""
        if value not in _CHANGE_FILTER_VALUES:
            return False
        self.audio_change_filter_var.set(value)
        self._save_staged_changes()
        return True

    @rpc
    def set_type(self, value):
        if value != "All types" and value not in _TYPE_KEYS:
            return False
        self.audio_type_var.set(value)
        self._refresh_list()
        return True

    @rpc
    def set_trim(self, on):
        if not self.get("trim_visible"):
            return False
        self.audio_trim_var.set(bool(on))
        self._save_staged_changes()
        return True

    @rpc
    def set_play_subst(self, on):
        """"Play replacements": ticking it turns "Play sequentially" on."""
        self.audio_play_subst_var.set(bool(on))
        if (self.audio_play_subst_var.get()
                and not self.audio_play_through_var.get()):
            self.audio_play_through_var.set(True)
        return True

    @rpc
    def sort(self, col):
        if col not in _SORT_DEFAULT_DESC:
            return False
        cur = self._sort
        if cur and cur[0] == col:
            self._sort = (col, not cur[1])
        else:
            self._sort = (col, _SORT_DEFAULT_DESC[col])
        self._refresh_list()
        return True

    @rpc
    def set_group_dups(self, on):
        self.audio_group_dups_var.set(bool(on))
        if self.audio_group_dups_var.get():
            self._ensure_dup_groups()
        return True

    @rpc
    def toggle_group(self, gid):
        if gid in self._open_groups:
            self._open_groups.discard(gid)
        else:
            self._open_groups.add(gid)
        self._refresh_list()
        return True

    # ------------------------------------------------------------------
    # duplicate grouping (CGC)
    # ------------------------------------------------------------------
    def _dup_siblings(self, rel):
        if not self._dup_groups:
            return []
        for _label, _dur, rels in self._dup_groups:
            if rel in rels:
                return [r for r in rels if r != rel and r in self._by_rel]
        return []

    def _fanout_to_copies(self, rel):
        rep = self._assign.get(rel)
        siblings = self._dup_siblings(rel)
        if not rep or not siblings:
            return
        for sib in siblings:
            self._assign[sib] = rep
        self._save_staged_changes()
        self.log("Replace Audio: applied %s to %d duplicate cop%s of %s"
                 % (os.path.basename(rep), len(siblings),
                    "y" if len(siblings) == 1 else "ies", rel), "info")
        self._refresh_list()
        self._publish_status("Applied to %d duplicate copy%s of this sound."
                             % (len(siblings),
                                "" if len(siblings) == 1 else "ies"))

    def _ensure_dup_groups(self, quiet=False):
        assets = self._scan_dir or self._assets()
        mfr = self.mfr
        if (not assets or not os.path.isdir(assets)
                or getattr(mfr, "find_duplicate_sounds", None) is None):
            return
        if self._dup_groups is not None and self._dup_scan_dir == assets:
            self._refresh_list()
            return
        if self._dup_scanning:
            return
        self._dup_scan_id += 1
        my_id = self._dup_scan_id
        self._dup_scanning = True
        self._refresh_list()
        self._publish_status("Grouping duplicates…")

        def _work():
            try:
                res = mfr.find_duplicate_sounds(assets)
            except Exception as e:                      # noqa: BLE001
                res = e
            self._post(self._apply_dup_groups, my_id, assets, res, quiet)

        threading.Thread(target=_work, daemon=True,
                         name="pad-audio-dups").start()

    def _apply_dup_groups(self, my_id, assets, res, quiet=False):
        if my_id != self._dup_scan_id:
            return
        self._dup_scanning = False
        if isinstance(res, Exception):
            self._dup_groups = []
            self.audio_group_dups_var.set(False)
            self._refresh_list()
            if not quiet:
                compat.messagebox.showinfo("Can't group duplicates", str(res))
            return

        def _dur(sec):
            m, s = divmod(max(0.0, float(sec or 0)), 60)
            return "%d:%06.3f" % (int(m), s)

        groups = []
        for g in getattr(res, "groups", ()):
            rels = [os.path.relpath(s.wav_path, assets).replace(os.sep, "/")
                    for s in g.slots if s.wav_path]
            if len(rels) >= 2:
                stem = os.path.splitext(os.path.basename(rels[0]))[0]
                groups.append((stem, _dur(g.duration_seconds), rels))
        self._dup_groups = groups
        self._dup_scan_dir = assets
        self._refresh_list()

    # ------------------------------------------------------------------
    # selection and the preview panes
    # ------------------------------------------------------------------
    def _selected_rel(self):
        return self._sel[0] if self._sel else None

    def _selected_slot_rels(self):
        return [r for r in self._sel if r in self._by_rel]

    @rpc
    def select(self, rels, playing=None):
        """The page's selection changed (click, Shift/Ctrl-click, arrows).
        *playing* names the pane that was playing at the time ("orig" /
        "rep" / None), so click-through listening keeps going."""
        rels = [r for r in (rels or []) if isinstance(r, str)]
        self._sel = rels
        self.set(sel=list(rels))
        self._on_select(playing)
        return True

    def _on_select(self, playing):
        self._level_sync()
        self._publish_cur()
        self._cancel(self._select_job)
        self._select_job = self._after(250, self._preview_selected, playing)

    def _preview_selected(self, playing=None):
        self._select_job = None
        rel = self._selected_rel()
        if rel is None or rel == self._current_rel:
            return
        resume = playing if playing in ("orig", "rep") else None
        self._load_track(rel, autoplay=resume)

    def _cancel_select_job(self):
        self._cancel(self._select_job)
        self._select_job = None

    def _publish_cur(self):
        rel = self._selected_rel()
        if rel is None or rel not in self._by_rel:
            self.set(cur=None)
            return
        self.set(cur={"rel": rel, "assigned": bool(self._assign.get(rel)),
                      "built": rel in self._changed})

    def _pane_publish(self, side):
        self.set(panes=dict(self._panes))

    def _pane_load(self, side, path, dur=0.0, limit_fn=None, autoplay=False,
                   label=None, gain_db=0.0, base=None):
        """Load *path* into pane *side*: the page's player gets the file at
        once; its length (ffprobe), the trim / grow marks and the strip
        picture come from a worker and land when ready."""
        self._pane_ids[side] += 1
        lid = self._pane_ids[side]
        pane = self._panes[side]
        v = pane["v"] + 1
        base = base or pane["base"]
        from ...core import audio as _audio
        have_ffmpeg = bool(_audio.find_ffmpeg())
        self._panes[side] = {
            "base": base, "name": label or os.path.basename(path),
            "path": path, "dur": float(dur or 0.0), "limit": None,
            "grow_from": None, "gain": float(gain_db or 0.0), "hint": "",
            "spec": None,
            "spec_state": "rendering" if have_ffmpeg else "noffmpeg",
            "v": v}
        self._pane_publish(side)
        if autoplay:
            self._publish("audio_play", pane=side, path=path, pos=0.0, v=v)
        gain = float(gain_db or 0.0)

        def _work():
            d = 0.0
            try:
                d = _audio.probe_duration(path) or 0.0
            except Exception:                           # noqa: BLE001
                d = 0.0
            self._post(self._pane_set_dur, side, lid, d, limit_fn)
            self._render_strip(side, lid, path, gain)

        threading.Thread(target=_work, daemon=True,
                         name="pad-audio-pane").start()

    def _render_strip(self, side, lid, path, gain):
        from .. import audio_media
        try:
            png = audio_media.spectrogram_file(path, _SPEC_W, _SPEC_H, gain)
        except Exception:                               # noqa: BLE001
            png = None
        self._post(self._pane_set_spec, side, lid, png)

    def _pane_set_dur(self, side, lid, dur, limit_fn):
        if self._pane_ids[side] != lid:
            return
        pane = dict(self._panes[side])
        if dur > 0 or not pane["dur"]:
            pane["dur"] = float(dur or 0.0) or pane["dur"]
        if limit_fn is not None:
            limit, grow = limit_fn(pane["dur"])
            pane["limit"] = limit
            pane["grow_from"] = grow if limit is None else None
        self._panes[side] = pane
        self._pane_publish(side)

    def _pane_set_spec(self, side, lid, png):
        if self._pane_ids[side] != lid:
            return
        pane = dict(self._panes[side])
        pane["spec"] = png
        if png:
            pane["spec_state"] = "ready"
        else:
            from ...core import audio as _audio
            pane["spec_state"] = ("failed" if _audio.find_ffmpeg()
                                  else "noffmpeg")
        self._panes[side] = pane
        self._pane_publish(side)

    def _pane_clear(self, side, hint="", base=None):
        self._pane_ids[side] += 1
        v = self._panes[side]["v"] + 1
        pane = self._blank_pane(base or self._panes[side]["base"], hint)
        pane["v"] = v
        self._panes[side] = pane
        self._pane_publish(side)

    def _pane_set_gain(self, side, db):
        pane = self._panes[side]
        db = float(db or 0.0)
        if db == pane["gain"]:
            return
        pane = dict(pane)
        pane["gain"] = db
        self._pane_ids[side] += 1
        lid = self._pane_ids[side]
        path = pane["path"]
        if path:
            pane["spec"] = None
            pane["spec_state"] = "rendering"
        self._panes[side] = pane
        self._pane_publish(side)
        if path:
            # keep the duration/limit already known; only the picture moves
            threading.Thread(target=self._render_strip,
                             args=(side, lid, path, db), daemon=True,
                             name="pad-audio-gain").start()

    def _load_track(self, rel, autoplay=None):
        """Both panes for *rel*: its true original on the left (the ``.orig``
        snapshot when the slot is already changed), its replacement on the
        right.  *autoplay* names the pane to start."""
        if rel not in self._by_rel:
            return
        from ...core import staged_originals
        self._current_rel = rel
        slot = self._by_rel.get(rel)
        opath = slot.abs_path if slot else None
        snap_used = False
        changed = self._changed_on_disk(rel)
        if changed:
            snap = staged_originals.snapshot_path(self._scan_dir, rel)
            if snap:
                opath = snap
                snap_used = True
        base = ("Current file (already modified)" if changed and not snap_used
                else "Original (stock)" if snap_used else "Original")
        if opath and os.path.isfile(opath):
            self._pane_load("orig", opath,
                            slot.duration if not snap_used else 0.0,
                            autoplay=(autoplay == "orig"), base=base)
        else:
            self._pane_clear("orig", base=base)
        self._load_rep_pane(rel, autoplay=(autoplay == "rep"))

    def _rep_available(self, rel):
        from ...core import staged_originals
        rpath = self._assign.get(rel)
        if rpath and os.path.isfile(rpath):
            return True
        if staged_originals.snapshot_path(self._scan_dir, rel):
            slot = self._by_rel.get(rel)
            return bool(slot and slot.abs_path
                        and os.path.isfile(slot.abs_path))
        return False

    def _load_rep_pane(self, rel, autoplay=False):
        from ...core import staged_originals
        rpath = self._assign.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            self._pane_load(
                "rep", rpath, 0.0,
                limit_fn=lambda d, r=rel: (
                    self._compute_preview_limit(r, d),
                    self._preview_grow_from(r, d)),
                autoplay=autoplay, gain_db=self._level.get(rel, 0),
                base="Replacement")
            return
        if rel and staged_originals.snapshot_path(self._scan_dir, rel):
            slot = self._by_rel.get(rel)
            cur = slot.abs_path if slot else None
            if cur and os.path.isfile(cur):
                self._pane_load(
                    "rep", cur, slot.duration, autoplay=autoplay,
                    label=self._remembered_rep_name(rel) or None,
                    gain_db=self._level.get(rel, 0),
                    base="Replacement (your file)")
                return
        self._pane_clear("rep", self._rep_pane_empty_text(
            rel, "no replacement assigned"), base="Replacement")

    def _compute_preview_limit(self, rel, rep_dur):
        if rel is None:
            return None
        if not self.audio_trim_var.get():
            return None
        if self._keep.get(rel):
            return None
        if self._audio_grow_active():
            return None
        slot = self._by_rel.get(rel)
        slot_dur = slot.duration if slot else 0.0
        if slot_dur > 0 and rep_dur > slot_dur + 0.02:
            return slot_dur
        return None

    def _preview_grow_from(self, rel, rep_dur):
        if rel is None or not self._audio_grow_active():
            return None
        slot = self._by_rel.get(rel)
        slot_dur = slot.duration if slot else 0.0
        if slot_dur > 0 and rep_dur > slot_dur + 0.02:
            return slot_dur
        return None

    def _clear_preview(self):
        self._cancel_select_job()
        self._current_rel = None
        self._pane_clear("orig", base="Original")
        self._pane_clear("rep", "no replacement assigned", base="Replacement")
        self._level_sync(reset=True)

    def _cancel_advance(self):
        self._cancel(self._advance_job)
        self._advance_job = None

    def _stop_playback(self):
        self._cancel_advance()
        self._publish("audio_stop")

    # -- transport (the page's buttons) -------------------------------------
    @rpc
    def play(self, side):
        """▶ on a pane that is not playing (the page pauses by itself)."""
        pane = self._panes.get(side)
        if pane is None:
            return False
        if not pane["path"]:
            self._activate_pane(side)
            return True
        if side == "orig" and self._play_intercept():
            return True
        self._publish("audio_play", pane=side, path=pane["path"], pos=None,
                      v=pane["v"])
        return True

    def _play_intercept(self):
        if not self.audio_play_subst_var.get():
            return False
        rel = self._current_rel
        if rel is None or not self._rep_available(rel):
            return False
        pane = self._panes["rep"]
        if not pane["path"]:
            return False
        self._publish("audio_play", pane="rep", path=pane["path"], pos=0.0,
                      v=pane["v"])
        return True

    def _activate_pane(self, side):
        rel = self._selected_rel()
        if rel is None:
            return
        if (side == "orig" and self.audio_play_subst_var.get()
                and self._rep_available(rel)):
            side = "rep"
        self._load_track(rel, autoplay=side)

    @rpc
    def play_row(self, rel):
        """The row's own ▶: select it and play what the card will play
        for it (its replacement with "Play replacements" ticked)."""
        if rel not in self._by_rel:
            return False
        self._sel = [rel]
        self.set(sel=[rel])
        self._cancel_select_job()
        self._level_sync()
        self._publish_cur()
        side = ("rep" if self.audio_play_subst_var.get()
                and self._rep_available(rel) else "orig")
        self._load_track(rel, autoplay=side)
        return True

    @rpc
    def space(self):
        """Space on the list with nothing playing (the page pauses a
        playing pane itself)."""
        rel = self._selected_rel()
        if rel is not None and rel != self._current_rel:
            self._cancel_select_job()
            self._load_track(rel, autoplay="orig")
        elif self._panes["orig"]["path"]:
            self.play("orig")
        return True

    @rpc
    def stop(self):
        """■: the page silenced both panes; drop a queued sequential step."""
        self._cancel_advance()
        return True

    def on_tab_changed(self, ns):
        """Another tab was picked: ``window.select_tab`` has already stopped
        every preview (the Tk ``_on_tab_changed``); a row selected in the
        last 250 ms does not load (and resume playing) behind it."""
        if ns != self.ns:
            self._cancel_select_job()

    @rpc
    def clip_finished(self, side, path=None):
        """A clip finished on its own: step down the list when "Play
        sequentially" is on."""
        pane = self._panes.get(side)
        if pane is None or (path and pane["path"] != path):
            return False
        if not self.audio_play_through_var.get():
            return False
        rel = self._current_rel
        if rel is None:
            return False
        nxt = self._next_visible_rel(rel)
        if nxt is None:
            self.log("Replace Audio: played through to the end of the list.",
                     "info")
            return False
        if self.audio_play_subst_var.get():
            side = "rep" if self._rep_available(nxt) else "orig"

        def _advance():
            self._advance_job = None
            self._sel = [nxt]
            self.set(sel=[nxt])
            self._cancel_select_job()
            self._level_sync()
            self._publish_cur()
            self._load_track(nxt, autoplay=side)

        self._cancel_advance()
        self._advance_job = self._after(120, _advance)
        return True

    def _next_visible_rel(self, rel):
        rels = self._visible_rels
        try:
            i = rels.index(rel)
        except ValueError:
            return None
        return rels[i + 1] if i + 1 < len(rels) else None

    @rpc(loop=False)
    def playable(self, path):
        """A WAV the page's player can decode, for a file it could not
        (``None`` when ffmpeg is missing or cannot read it either)."""
        from .. import audio_media
        return audio_media.playable_copy(path)

    @rpc
    def cant_preview(self, path=""):
        from ...core import audio as _audio
        exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        msg = ("This file can't be previewed here:\n%s\n\nThe preview player "
               "can't read this format, and converting it for the preview "
               "needs %s.\n\nPreview is optional -- it doesn't affect "
               "building the update; your replacements still get staged and "
               "written." % (path, exe))
        cb = self.window.cb.get("on_install_prereqs")
        if not _audio.find_ffmpeg() and cb is not None \
                and sys.platform != "darwin":
            if compat.messagebox.askyesno(
                    "Can't Preview",
                    msg + "\n\nRun the prerequisites installer now?"):
                cb()
        else:
            compat.messagebox.showwarning("Can't Preview", msg)
        return True

    # ------------------------------------------------------------------
    # the per-clip loudness (Stern)
    # ------------------------------------------------------------------
    @staticmethod
    def _level_value(raw):
        raw = ("" if raw is None else str(raw)).strip()
        if not raw:
            return 0
        try:
            return max(min(int(float(raw)), 12), -12)
        except ValueError:
            return None

    def _level_sync(self, reset=False):
        rel = self._selected_rel()
        if rel is not None or reset:
            self.set(level=str(self._level.get(rel, 0) if rel else 0))
        self.set(level_enabled=bool(self._slots))

    @rpc
    def set_level(self, rel, value):
        """The dB box, typed for *rel* (the row that was selected when the
        user typed; 0 clears)."""
        db = self._level_value(value)
        if db is None or rel is None or rel not in self._by_rel:
            return False
        if db:
            self._level[rel] = db
        else:
            self._level.pop(rel, None)
        if rel == self._selected_rel():
            self.set(level=str(value).strip() or "0")
        i = self._row_index.get(rel)
        if i is not None:
            self.patch_item("rows", i, lvl=self._level_disp(rel))
        self._level_preview_soon(rel)
        self._save_staged_changes()
        return True

    def _level_preview_soon(self, rel):
        self._cancel(self._level_job)

        def _go():
            self._level_job = None
            if self._current_rel == rel:
                self._pane_set_gain("rep", self._level.get(rel, 0))
        self._level_job = self._after(350, _go)

    @rpc
    def level_apply_all(self, value):
        """Apply to all shown: the box's value on every row the list is
        showing (search, Type and Show filters included)."""
        db = self._level_value(value)
        if db is None:
            return False
        rels = list(self._visible_rels)
        if not rels:
            compat.messagebox.showinfo(
                "Replacement loudness",
                "No sounds are listed to apply that to.")
            return False
        if not compat.messagebox.askyesno(
                "Replacement loudness",
                ("Clear the loudness offset on all %d sound(s) currently "
                 "listed?" % len(rels)) if not db else
                ("Set the loudness offset to %+d dB on all %d sound(s) "
                 "currently listed?\n\nThis affects only what the list is "
                 "showing right now (search, Type and Show filters "
                 "included)." % (db, len(rels)))):
            return False
        for rel in rels:
            if db:
                self._level[rel] = db
            else:
                self._level.pop(rel, None)
        self._refresh_list()
        if self._current_rel in rels:
            self._level_preview_soon(self._current_rel)
        self._save_staged_changes()
        return True

    # ------------------------------------------------------------------
    # picking, flags, undo
    # ------------------------------------------------------------------
    @rpc
    def choose_selected(self):
        rel = self._selected_rel()
        if rel is None:
            compat.messagebox.showinfo(
                "No Slot Selected",
                "Select a track in the list first, then choose a "
                "replacement.")
            return False
        return self.choose(rel)

    @rpc
    def choose(self, rel):
        """The replacement picker for *rel* (the Replacement cell, a
        double-click, the menu or the pane's Choose…)."""
        if not rel or rel not in self._by_rel:
            return False
        self._cancel_select_job()
        self.stop_all_preview_playback()
        path = self._ask_path(
            "open", "audio_replacement", "Choose a replacement for %s" % rel,
            filetypes=_AUDIO_FILETYPES)
        if not path:
            return False
        if isinstance(path, (list, tuple)):
            path = path[0] if path else ""
            if not path:
                return False
        self._assign[rel] = path
        self._save_staged_changes()
        self.log("Replace Audio: %s ← %s" % (rel, os.path.basename(path)),
                 "info")
        self._sel = [rel]
        self._refresh_list()
        if rel == self._current_rel:
            self._load_rep_pane(rel)
        else:
            self._on_select(None)
        return True

    @rpc
    def toggle_flag(self, rel, which):
        """Click in the Loop (BOF) or Full (JJP) cell."""
        if rel not in self._by_rel or which not in ("loop", "keep"):
            return False
        store = self._loop if which == "loop" else self._keep
        store[rel] = not store.get(rel, False)
        self._save_staged_changes()
        i = self._row_index.get(rel)
        if i is not None:
            self.patch_item("rows", i, **{which: bool(store[rel])})
        return True

    def _toggle_keep_whole(self, rel):
        if rel in self._keep_whole:
            self._keep_whole.remove(rel)
        else:
            self._keep_whole.append(rel)
        self._save_staged_changes()

    def _revert(self, rel):
        from ...core import staged_originals
        if rel is None:
            return
        assets_dir = self._assets()
        had = rel in self._assign
        if had:
            del self._assign[rel]
        restored = False
        on_disk = rel in self._changed
        if on_disk and assets_dir:
            restored = staged_originals.revert(assets_dir, rel)
        if restored:
            self._changed.discard(rel)
        self._save_staged_changes()
        if had or restored:
            self.log("Replace Audio: reverted %s to the extracted original"
                     % rel, "info")
        self._refresh_list()
        if rel == self._current_rel:
            self._load_track(rel)
        self._sel = [rel]
        self.set(sel=[rel])
        self._publish_cur()
        if on_disk and not restored:
            compat.messagebox.showinfo(
                "No saved original",
                "This track was changed on disk without a per-edit backup — "
                "edited outside the app, or before this version started "
                "keeping backups — so there's no saved original to restore "
                "here.\n\nUse “Revert all changes…” on the Write tab to "
                "rebuild it from the source card, or re-extract the card.")

    @rpc
    def remove_selected(self):
        """The Replacement pane's Remove replacement / Revert to original
        (one row, by state, like the row menu)."""
        rel = self._selected_rel()
        if rel is None or rel not in self._by_rel:
            return False
        if rel in self._changed:
            self._revert(rel)
        elif self._assign.get(rel):
            self._clear_picks(self._selected_slot_rels()[:1])
        return True

    # -- the bulk clear (one implementation for every entry point) ----------
    def _applied_rels(self, rels=None):
        from ...core import staged_originals
        snaps = staged_originals.snapshot_rels(self._scan_dir or None)
        if rels is None:
            return sorted(rel for rel in snaps if rel in self._by_rel)
        return [rel for rel in dict.fromkeys(rels)
                if rel in snaps and rel in self._by_rel]

    def _targets(self, rels=None):
        if rels is None:
            rels = list(self._assign) + self._applied_rels()
        applied = set(self._applied_rels(rels))
        return [rel for rel in dict.fromkeys(rels)
                if self._assign.get(rel) or rel in applied]

    def _put_back_originals(self, rels):
        from ...core import history_log, staged_changes, staged_originals
        scan_dir = self._scan_dir
        done = [rel for rel in rels if staged_originals.revert(scan_dir, rel)]
        if not done:
            return []
        self._changed.difference_update(done)
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
            "was cleared)" % ("audio", rel) for rel in done])
        return done

    def _clear_picks(self, rels, reselect=True):
        rels = list(dict.fromkeys(rels))
        picks = [rel for rel in rels if rel in self._assign]
        applied = [] if self._running() else self._applied_rels(rels)
        if not picks and not applied:
            return 0
        for rel in picks:
            del self._assign[rel]
        restored = self._put_back_originals(applied)
        self._save_staged_changes()
        gone = list(dict.fromkeys(picks + restored))
        label = "Replace Audio"
        if len(gone) == 1:
            msg = "%s: cleared replacement for %s" % (label, gone[0])
            if restored:
                msg += (" and put the card's original file back in the "
                        "project folder")
        else:
            msg = ("%s: cleared %d replacements (the folder's history log "
                   "names each one)" % (label, len(gone)))
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
                "closed." % (label, ", ".join(stuck[:3])
                             + (" and %d more" % (len(stuck) - 3)
                                if len(stuck) > 3 else "")), "warning")
        if reselect:
            self._sel = [r for r in gone if r in self._by_rel]
        self._refresh_list()
        if self._current_rel is not None and self._current_rel in set(gone):
            self._load_rep_pane(self._current_rel)
        if reselect and self._sel:
            self._on_select(None)
        self._update_clear_all()
        return len(gone)

    def _clear_confirm_text(self, targets, question):
        applied = len(self._applied_rels(targets))
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

    def _clear_selected(self, rels):
        rels = [r for r in rels if r in self._by_rel]
        targets = self._targets(rels)
        if len(targets) > 1 and not compat.messagebox.askyesno(
                "Clear replacements",
                self._clear_confirm_text(
                    targets, "Clear the replacements for these %d slots?"
                    % len(targets))):
            return False
        self._clear_picks(rels)
        return True

    @rpc
    def clear_all(self):
        """Clear replacements…: every replacement on this tab."""
        if self._running():
            return False
        targets = self._targets()
        n = len(targets)
        if not n:
            compat.messagebox.showinfo(
                "Clear replacements",
                "Nothing is picked on this tab, so there is nothing to "
                "clear.")
            return False
        if not compat.messagebox.askyesno(
                "Clear replacements",
                self._clear_confirm_text(
                    targets, "Clear all %d replacement%s on this tab?"
                    % (n, "" if n == 1 else "s"))):
            return False
        self._clear_picks(targets, reselect=False)
        return True

    def _update_clear_all(self):
        live = (not self._running()) and bool(self._targets())
        self.set(can_clear=live)

    # -- Replace from folder… -----------------------------------------------
    @staticmethod
    def _folder_match_list(names, cap=10):
        shown = ", ".join(names[:cap])
        if len(names) > cap:
            shown += ", and %d more" % (len(names) - cap)
        return shown

    @rpc
    def replace_from_folder(self):
        from ...core import folder_match
        if self._running():
            return False
        label = "Replace Audio"
        slot_rels = [rel for rel in self._by_rel if rel not in self._foreign]
        if not slot_rels:
            compat.messagebox.showinfo(
                "Replace from folder",
                "There are no slots on this tab to match files to yet. Set "
                "the project folder on the Extract tab and Scan first.")
            return False
        folder = self._ask_path(
            "folder", "audio_replacement",
            "Choose a folder of replacement files")
        if not folder:
            return False
        folder = os.path.normpath(folder)
        project = self._assets()
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
                return False
        found = folder_match.match_folder(folder, slot_rels,
                                          _FOLDER_MATCH_EXTS)
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
            return False
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
        already = [rel for rel in pairs if self._assign.get(rel)]
        if already:
            lines.append("%d of those slots already have a replacement "
                         "picked; it is swapped for the file from this "
                         "folder." % len(already))
        left = (len(found["unmatched"]) + len(found["ambiguous"])
                + len(found["duplicates"]))
        if left:
            lines.append("%d file(s) in the folder are left out; the log "
                         "names them." % left)
        if not compat.messagebox.askyesno("Replace from folder",
                                          "\n\n".join(lines)
                                          + fingerprint_note):
            return False
        self._assign.update(pairs)
        self._save_staged_changes()
        self.log(
            "%s: picked %d replacement(s) by name from %s%s."
            % (label, n, folder,
               (" (%d of a different file type, converted to suit their "
                "slot)" % len(found["retyped"])) if found["retyped"] else ""),
            "info")
        if found["unmatched"]:
            self.log("%s: %d file(s) named like no slot on this tab: %s"
                     % (label, len(found["unmatched"]),
                        self._folder_match_list(found["unmatched"])),
                     "warning")
        if found["ambiguous"]:
            self.log(
                "%s: %d file(s) named like more than one slot, so left out "
                "(put each in a subfolder named like its slot's to say "
                "which): %s"
                % (label, len(found["ambiguous"]),
                   self._folder_match_list(found["ambiguous"])), "warning")
        if found["duplicates"]:
            self.log(
                "%s: %d file(s) left out because another file in the folder "
                "has the same name: %s"
                % (label, len(found["duplicates"]),
                   self._folder_match_list(found["duplicates"])), "warning")
        if fingerprinted:
            self.log(
                "%s: %d of the left-out files are scene pictures or glyphs "
                "named for a different card's contents; \"Transfer Mods to "
                "New Version\" carries those over by content."
                % (label, len(fingerprinted)), "warning")
        self._refresh_list()
        if self._current_rel in pairs:
            self._load_rep_pane(self._current_rel)
        self._update_clear_all()
        return True

    # ------------------------------------------------------------------
    # the row menu
    # ------------------------------------------------------------------
    @staticmethod
    def _reveal_label():
        if sys.platform == "darwin":
            return "Reveal in Finder"
        if sys.platform == "win32":
            return "Show in File Explorer"
        return "Show in File Manager"

    @rpc
    def menu(self, rel, sel=None):
        """The right-click menu for *rel* (*sel*: the page's selection; a
        click inside a multi-row selection keeps it and gets the bulk
        menu).  Items: {label, action, disabled, sep, checked, icon}."""
        sel = [r for r in (sel or []) if r in self._by_rel]
        if rel not in self._by_rel:
            return []
        if rel in sel and len(sel) >= 2:
            picked = self._targets(sel)
            items = [{"label": "%d slot%s selected"
                      % (len(sel), "" if len(sel) == 1 else "s"),
                      "disabled": True}, {"sep": True}]
            if picked:
                items.append({"label": "Clear %d replacement%s in this "
                              "selection" % (len(picked),
                                             "" if len(picked) == 1 else "s"),
                              "action": "clear_selection"})
            else:
                items.append({"label": "No replacements in this selection",
                              "disabled": True})
            return items
        from ...core import name_memory as _nmem
        items = [{"label": "Play original", "action": "play_orig",
                  "icon": "play"},
                 {"label": "Choose replacement…", "action": "choose",
                  "icon": "file"}]
        if _nmem.split_decode_name(os.path.basename(rel)):
            items.append({"label": "Properties…  (name / type)",
                          "action": "props", "kbd": "F2", "icon": "edit"})
        has_assignment = bool(self._assign.get(rel))
        is_built = rel in self._changed
        if has_assignment:
            items.append({"label": "Play replacement", "action": "play_rep",
                          "icon": "play"})
        siblings = self._dup_siblings(rel)
        if has_assignment and siblings:
            items.append({"label": "Apply to all %d copies of this sound"
                          % (len(siblings) + 1), "action": "fanout",
                          "icon": "copy"})
        if is_built:
            items += [{"sep": True},
                      {"label": "Revert to original", "action": "revert",
                       "icon": "undo"}]
        elif has_assignment:
            items += [{"sep": True},
                      {"label": "Remove replacement", "action": "remove",
                       "icon": "x"}]
        if self._audio_grow_active() and re.match(
                r"idx\d+", os.path.basename(rel) or ""):
            items += [{"sep": True},
                      {"label": "Keep this song whole if the bank fills up",
                       "action": "keep_whole",
                       "checked": rel in self._keep_whole}]
        items += [{"sep": True},
                  {"label": "Open in default app", "action": "open_orig",
                   "icon": "file"}]
        if self._open_target(rel, "rep"):
            items.append({"label": "Open replacement in default app",
                          "action": "open_rep", "icon": "file"})
        items.append({"label": self._reveal_label(), "action": "reveal",
                      "icon": "folder"})
        if self.window.tab_visible("Partition Explorer"):
            items.append({"label": "Find in Partition Explorer",
                          "action": "find_pex", "icon": "search"})
        return items

    @rpc
    def menu_action(self, action, rel, sel=None):
        if action == "clear_selection":
            return self._clear_selected(list(sel or self._sel))
        if rel not in self._by_rel:
            return False
        if action == "play_orig":
            self._load_track(rel, autoplay="orig")
        elif action == "choose":
            return self.choose(rel)
        elif action == "props":
            return {"open": "props", "data": self.props_info(rel)}
        elif action == "play_rep":
            if not self._assign.get(rel):
                compat.messagebox.showinfo(
                    "No Replacement",
                    "Assign a replacement to this slot first.")
                return False
            self._load_track(rel, autoplay="rep")
        elif action == "fanout":
            self._fanout_to_copies(rel)
        elif action == "revert":
            self._revert(rel)
        elif action == "remove":
            self._clear_picks([rel])
        elif action == "keep_whole":
            self._toggle_keep_whole(rel)
        elif action == "reveal":
            slot = self._by_rel.get(rel)
            if slot is not None:
                self._reveal(slot.abs_path)
        elif action in ("open_orig", "open_rep"):
            path = self._open_target(rel, action[5:])
            if path is None:
                return False
            from ..shellx_common import open_in_default_app_or_warn
            return open_in_default_app_or_warn(path)
        elif action == "find_pex":
            self._find_in_partition(rel)
        else:
            return False
        return True

    def _open_target(self, rel, which):
        """The file "Open in default app" hands the OS (PAD-208): the
        slot's own file, or its assigned replacement when that is a file."""
        slot = self._by_rel.get(rel)
        if slot is None:
            return None
        if which == "orig":
            return slot.abs_path
        rep = self._assign.get(rel)
        return rep if isinstance(rep, str) and os.path.isfile(rep) else None

    def _reveal(self, path):
        import subprocess
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
                    os.startfile(folder)                # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path] if os.path.isfile(path)
                                 else ["open", folder])
            else:
                from ...core import desktop
                ok, err = desktop.open_path(folder)
                if not ok:
                    raise RuntimeError(err)
        except Exception as e:                          # noqa: BLE001
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, e))

    @rpc
    def open_folder(self):
        """The project folder link."""
        path = self._assets()
        if not path:
            compat.messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return False
        if not os.path.exists(path):
            compat.messagebox.showinfo(
                "Open folder", "This folder doesn't exist yet:\n%s" % path)
            return False
        self._reveal(path)
        return True

    def _find_in_partition(self, rel):
        """Hand the row to the Partition Explorer service (the Tk
        ``_asset_find_in_partition``: it resolves the sound's bank on the
        card, opens the image and reveals it)."""
        svc = self.window.service("partitions")
        fn = (getattr(svc, "find_in_partition", None) if svc is not None
              else None)
        if fn is not None:
            fn("audio", rel, self._scan_dir)
            return
        from ...core import card_paths
        want, note = card_paths.audio_card_hint(rel)
        compat.messagebox.showinfo("Find in Partition Explorer", note)

    # ------------------------------------------------------------------
    # Properties… (rename / Type)
    # ------------------------------------------------------------------
    def _sound_test_suggestions(self):
        path = os.path.join(self._scan_dir or "", "sound_test_names.csv")
        if not self._scan_dir or not os.path.isfile(path):
            return []
        rows = []
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    nm = (row.get("name") or "").strip()
                    num = (row.get("sound_number") or "").strip()
                    if nm:
                        rows.append((int(num) if num.isdigit() else 10 ** 9,
                                     nm))
        except Exception:                               # noqa: BLE001
            return []
        return ["#%d  %s" % (n, nm) if n < 10 ** 9 else nm
                for n, nm in sorted(rows)]

    @rpc
    def props_info(self, rel=None):
        """What the Audio Properties dialog opens with, or None when the
        slot's name can't be renamed (F2 then does nothing)."""
        from ...core import name_memory
        rel = rel or self._selected_rel()
        if rel is None or rel not in self._by_rel:
            return None
        parts = name_memory.split_decode_name(os.path.basename(rel))
        if parts is None:
            return None
        prefix, label, ext = parts
        return {
            "rel": rel,
            "prompt": ("Name for this sound — remembered for future extracts\n"
                       "(blank restores \"%s\" and forgets it):"
                       % (prefix + ext)),
            "label": label,
            "suggestions": self._sound_test_suggestions(),
            "category": self._cats.get(rel) or "other",
            "cats": [{"value": k, "label": v} for k, v in _CAT_NAMES],
        }

    @rpc
    def rename(self, rel, text, new_cat):
        """OK in Audio Properties: rename the file in place (keeping its
        decode index), re-point the baseline, remember the name and Type."""
        from ...core import name_memory
        from ...core.audio_slots import replace_with_retry
        from ...core.checksums import rename_in_baseline
        slot = self._by_rel.get(rel)
        if slot is None:
            return False
        parts = name_memory.split_decode_name(os.path.basename(rel))
        if parts is None:
            return False
        prefix, label, ext = parts
        m = re.match(r"^#\d+\s+(.*)$", text or "")
        name = m.group(1) if m else (text or "")
        if new_cat not in dict(_CAT_NAMES):
            new_cat = "other"
        cur_cat = self._cats.get(rel) or "other"
        new_label = name_memory.sanitize_label(name)
        if new_label == label:
            if new_cat == cur_cat:
                return True
            md5 = name_memory.baseline_md5(self._scan_dir, rel)
            if md5 is None and rel not in self._changed:
                md5 = name_memory.file_md5(slot.abs_path)
            self._cats[rel] = new_cat
            if md5 and new_label:
                name_memory.remember(md5, new_label, category=new_cat)
                note = " (remembered)"
            else:
                note = (" (this session only — give the slot a name to "
                        "remember its Type across extracts)")
            self.log("Replace Audio: %s Type → %s%s" % (rel, new_cat, note),
                     "info")
            self._refresh_type_filter()
            self._refresh_list()
            return True
        new_base = ("%s - %s%s" % (prefix, new_label, ext) if new_label
                    else prefix + ext)
        folder = rel.rpartition("/")[0]
        new_rel = (folder + "/" + new_base) if folder else new_base
        dst = os.path.join(os.path.dirname(slot.abs_path), new_base)
        if os.path.exists(dst):
            compat.messagebox.showerror(
                "Audio Properties",
                "A file named\n%s\nalready exists in that folder." % new_base)
            return False
        md5 = name_memory.baseline_md5(self._scan_dir, rel)
        if md5 is None and rel not in self._changed:
            md5 = name_memory.file_md5(slot.abs_path)
        self._stop_playback()
        try:
            replace_with_retry(slot.abs_path, dst)
        except OSError as e:
            compat.messagebox.showerror("Audio Properties",
                                        "Rename failed:\n%s" % e)
            return False
        try:
            rename_in_baseline(self._scan_dir, {rel: new_rel})
        except OSError as e:
            self.log(
                "Replace Audio: renamed the file, but couldn't re-point the "
                "extract baseline (%s) — the slot will read as \"changed on "
                "disk\" until the next Extract, even though its audio is "
                "untouched." % e, "error")
        if md5:
            try:
                name_memory.remember(md5, new_label, category=new_cat)
            except OSError as e:
                self.log(
                    "Replace Audio: couldn't remember \"%s\" for future "
                    "extracts (%s)." % (new_label, e), "error")
        for d in (self._assign, self._loop, self._keep, self._cats,
                  self._level):
            if rel in d:
                d[new_rel] = d.pop(rel)
        if rel in self._changed:
            self._changed.discard(rel)
            self._changed.add(new_rel)
        self._keep_whole = [new_rel if r == rel else r
                            for r in self._keep_whole]
        self._cats[new_rel] = new_cat
        slot.rel_path = new_rel
        slot.abs_path = dst
        self._by_rel.pop(rel, None)
        self._by_rel[new_rel] = slot
        for _label, _dur, rels in (self._dup_groups or ()):
            for i, r in enumerate(rels):
                if r == rel:
                    rels[i] = new_rel
        if self._current_rel == rel:
            self._clear_preview()
        self._sel = [new_rel]
        self._refresh_type_filter()
        self._refresh_list()
        self._on_select(None)
        if not md5:
            note = " (not remembered: the slot is modded and has no baseline)"
        elif new_label:
            note = " (remembered for future extracts)"
        else:
            note = " (forgotten)"
        self.log("Replace Audio: renamed %s → %s%s" % (rel, new_base, note),
                 "info")
        self._save_staged_changes()
        return True

    # ------------------------------------------------------------------
    # Export CSV
    # ------------------------------------------------------------------
    @rpc
    def export_csv(self):
        if not self._slots:
            compat.messagebox.showinfo(
                "Export CSV",
                "Scan an assets folder first — the audio table is empty.")
            return False
        path = self._ask_path(
            "save", "audio_csv", "Save audio table as CSV",
            initialfile="audio_slots.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            defaultextension=".csv")
        if not path:
            return False
        _cat_key = self._cat_key_fn()
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Original Track", "Length", "Format", "Type",
                            "Replacement", "Changed On Disk", "Loop",
                            "Full Length", "Level dB"])
                for s in sorted(self._slots, key=lambda q: q.rel_path):
                    rel = s.rel_path
                    w.writerow([
                        rel, s.duration_str(), s.format_summary(),
                        _CAT_DISP.get(_cat_key(s), "Other"),
                        self._assign.get(rel, ""),
                        "yes" if rel in self._changed else "",
                        "yes" if self._loop.get(rel) else "",
                        "yes" if self._keep.get(rel) else "",
                        self._level.get(rel, "") or "",
                    ])
        except OSError as e:
            compat.messagebox.showerror("Export CSV",
                                        "Couldn't write the CSV:\n%s" % e)
            return False
        self.log("Audio table exported: %d slot(s) → %s"
                 % (len(self._slots), os.path.normpath(path)), "success")
        return True

    # ------------------------------------------------------------------
    # Advanced… and Profile vs stock (Stern)
    # ------------------------------------------------------------------
    @rpc
    def advanced_get(self):
        cfg = dict(ADV_DEFAULTS)
        cfg.update({k: v for k, v in self._advanced.items() if v is not None})
        if cfg.get("loudness") not in dict(LOUDNESS_CHOICES):
            cfg["loudness"] = "match"
        if cfg.get("head_mode") not in dict(HEAD_CHOICES):
            cfg["head_mode"] = "encode"
        if cfg.get("leadout") not in dict(LEADOUT_CHOICES):
            cfg["leadout"] = "silence"
        cfg["loudness_db"] = cfg.get("loudness_db") or 0
        cfg["slot_seed_db"] = cfg.get("slot_seed_db") or 65
        cfg["experiment_idxs"] = str(cfg.get("experiment_idxs") or "")
        return {"cfg": cfg, "defaults": dict(ADV_DEFAULTS),
                "loudness": [{"value": k, "label": v}
                             for k, v in LOUDNESS_CHOICES],
                "head": [{"value": k, "label": v} for k, v in HEAD_CHOICES],
                "leadout": [{"value": k, "label": v}
                            for k, v in LEADOUT_CHOICES]}

    @rpc
    def advanced_set(self, cfg):
        """OK in Advanced Audio Options (the Tk dialog's ``_collect``)."""
        cfg = dict(cfg or {})

        def num(v, lo, hi, dflt):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return dflt
            return int(min(max(v, lo), hi))

        idxs = ",".join(t.strip() for t in
                        str(cfg.get("experiment_idxs") or "")
                        .replace(";", ",").split(",")
                        if t.strip().isdigit())
        out = {
            "head_mode": cfg.get("head_mode") if cfg.get("head_mode")
            in dict(HEAD_CHOICES) else "encode",
            "leadout": cfg.get("leadout") if cfg.get("leadout")
            in dict(LEADOUT_CHOICES) else "silence",
            "previews": bool(cfg.get("previews")),
            "experiment_idxs": idxs,
            "slot_seed": bool(cfg.get("slot_seed")),
            "slot_seed_db": num(cfg.get("slot_seed_db"), 40, 90, 65),
            "blip_free_optin": bool(cfg.get("blip_free_optin")),
            "audio_grow": bool(cfg.get("audio_grow")),
            "loudness": cfg.get("loudness") if cfg.get("loudness")
            in dict(LOUDNESS_CHOICES) else "match",
            "loudness_db": num(cfg.get("loudness_db"), -12, 12, 0),
        }
        self._advanced = out
        cb = self.window.cb.get("on_audio_advanced_change")
        if cb is not None:
            cb(dict(out))
        try:
            self._load_rep_pane(self._current_rel)
        except Exception:                               # noqa: BLE001
            pass
        self._refresh_adv_marker()
        return True

    @rpc
    def profile(self):
        assets = self._scan_dir
        if not assets:
            compat.messagebox.showinfo(
                "Profile vs stock",
                "Scan an extract folder on the Audio tab first — the report "
                "characterizes the sounds in that folder.")
            return False
        cb = self.window.cb.get("on_audio_profile")
        if cb is not None:
            cb(assets)
        return True

    # ------------------------------------------------------------------
    # column widths: the ones the user drags, kept in settings.json under
    # column_widths["audio"] exactly as the Tk tree kept them
    # (``_persist_tree_columns(self._audio_tree, "audio", ...)``), so a
    # layout tuned in either UI opens the same in the other
    # ------------------------------------------------------------------
    _WIDTHS_KEY = "audio"
    #: The key an earlier web build saved under; dropped on the next save.
    _OLD_WIDTHS_KEY = "audio_web"
    #: Each column's Tk ``minwidth`` (``_build_audio_tab``): a saved width
    #: never shows narrower than the Tk tree let it be dragged.
    _MIN_WIDTHS = {"#0": 80, "len": 66, "fmt": 104, "rep": 110, "loop": 40,
                   "keep": 40, "type": 64, "lvl": 58}

    def _all_widths(self):
        s = getattr(self.app, "_settings", None) if self.app else None
        widths = (s or {}).get("column_widths")
        if not isinstance(widths, dict):
            widths = getattr(self, "_widths_local", None)
        if not isinstance(widths, dict):
            widths = dict(self.window.cb.get("initial_column_widths") or {})
        return widths

    @staticmethod
    def _width_ok(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)
                and 20 <= v <= 4000)

    def _saved_widths(self):
        try:
            got = self._all_widths().get(self._WIDTHS_KEY) or {}
        except Exception:                               # noqa: BLE001
            got = {}
        if not isinstance(got, dict):
            return {}
        # Tk restored any positive width and let minwidth hold the floor
        return {k: min(max(int(v), self._MIN_WIDTHS[k]), 4000)
                for k, v in got.items()
                if k in self._MIN_WIDTHS and isinstance(v, (int, float))
                and not isinstance(v, bool) and v > 0}

    @rpc
    def save_widths(self, widths):
        """The columns a header drag just changed (only those, as the Tk
        ``_save_tree_columns`` saved them), merged into the saved ones."""
        changed = {str(k): int(round(v)) for k, v in (widths or {}).items()
                   if str(k) in self._MIN_WIDTHS and self._width_ok(v)}
        if not changed:
            return False
        allw = dict(self._all_widths())
        tuned = allw.get(self._WIDTHS_KEY)
        tuned = dict(tuned) if isinstance(tuned, dict) else {}
        tuned.update(changed)
        allw[self._WIDTHS_KEY] = tuned
        allw.pop(self._OLD_WIDTHS_KEY, None)
        self._widths_local = allw
        cb = self.window.cb.get("on_column_widths_change")
        if cb is not None:
            cb(allw)
        self.set(widths=self._saved_widths())
        return True


TAB = AudioTab
