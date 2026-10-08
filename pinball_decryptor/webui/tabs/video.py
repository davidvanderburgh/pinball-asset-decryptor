"""Replace Video tab: a searchable list of the video files in the project
folder, each a slot the user can assign a replacement clip to, with the
Original and Replacement side by side.  Nothing is written here: picks live
in the folder's ``.staged_changes.json`` sidecar and the Write flow applies
them (``pending_video_assignments``).

A port of the Tk tab (gui/main_window.py ``_build_video_tab`` and the
``_video_*`` methods it wires, the shared Replace-tab helpers it calls, and
gui/video_quality_dialog.py).  The Tk-free logic lives in
``webui/video_helpers.py``; status: docs/plans/web_ui_tabs/video.md.

Store namespace ``video``:
  search, change_filter, trim, no_conversion   the Tk variables (exported)
  rows       every slot, in scan order: {rel, name, dir, len, res, fmt,
             fmt_bad, aud, rep, rep_cls, conv, conv_cls}
  view       indices into rows: the filtered + sorted list on screen
  sort       {key, desc}
  status     "12 of 99 slots changed  (4 shown)" (+ "still checking…")
  empty      the text over an empty list; scanning: a scan is running
  preview    {rel, orig: pane, rep: pane, note: {text, kind}, can_clear}
  play       {side, seq}: start that pane once it is loaded
  stop_seq   bumped to stop both panes (tab change, picker opening)
  quality    the "Check the videos on a card" report window
  best_quality  the "Best quality" option (exported)
  best       the "Best quality…" window (webui/video_best.py)
  widths     {column key: px} the columns the user dragged (settings.json
             column_widths["video_web"]); the rest fit their content
  compare    {open, max, tiles: [{id, rel, side, sides, pane, look}]}: the
             Compare view's players (PAD-440), each with its colour steps

A row's RANDOM CLIPS (PAD-446): more clips for one slot, the game playing
one of them at random each time it plays the slot's clip.  Kept in the
sidecar's ``video_variants`` ({rel: [file, ...]}); which slots can have them
is the plugin's answer (``Manufacturer.video_variants_offer``), asked once
per scan off the UI thread.
"""

import csv
import logging
import os
import queue as queue_mod
import threading
import time

from .. import compat
from ...core.video_slots import LENGTH_FULL, LENGTH_STOCK, length_seconds
from .. import look_switches
from .. import video_helpers as vh
from ..video_best import BEST_TIP, BestQualityMixin
from ..video_modes import ModesMixin
from ..video_undo import UndoMixin, undoable
from .base import TabService, rpc

log = logging.getLogger(__name__)

_LABEL = "Replace Video"          # MainWindow._REPLACE_LABELS["video"]


def _length_ok(choice):
    """A per-clip length choice worth keeping from a sidecar."""
    return choice in (LENGTH_STOCK, LENGTH_FULL) or bool(
        length_seconds(choice))


def _variants_from(raw, by_rel):
    """A sidecar's ``video_variants`` as ``{rel: [file, ...]}``, for the
    slots this scan found (PAD-446)."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for rel, files in raw.items():
        if rel in by_rel and isinstance(files, (list, tuple)):
            keep = [f for f in files if isinstance(f, str) and f.strip()]
            if keep:
                out[rel] = keep
    return out


def _length_key(choice):
    """The row menu's name for a clip's length choice."""
    if choice is None:
        return "box"
    return "custom" if length_seconds(choice) else choice
_SCAN_LABEL = "Video"             # MainWindow._SCAN_LABELS["video"]

NO_PROJECT_TEXT = "Set the project folder on the Extract tab, then click Scan."
COMPARE_MAX = 4                   # clips side by side in Compare (PAD-440)
NO_PROJECT_MIRROR = "(no project yet — extract into one on the Extract tab)"
# a game's own clip with its color profile attached: the Replacement player's
# title for it (PAD-336, PAD-448)
STOCK_COLOURED = "With its color profile"


class VideoTab(ModesMixin, BestQualityMixin, UndoMixin, TabService):
    ns = "video"
    key = "Replace Video"
    label = "Video"
    group = "Replace"
    icon = "video"
    exports = (
        "pending_video_assignments", "video_trim_var",
        "video_no_conversion_var", "video_search_var",
        "video_change_filter_var", "reveal_video_slot",
        "video_best_quality_var",
    )

    def __init__(self, window):
        super().__init__(window)
        self.video_search_var = self.var("search", "str", "")
        self.video_change_filter_var = self.var("change_filter", "str", "All")
        self.video_trim_var = self.var("trim", "bool", False)
        self.video_no_conversion_var = self.var("no_conversion", "bool", False)
        self.video_best_quality_var = self.var("best_quality", "bool", False)
        self._slots = []                 # [VideoSlot] from the last scan
        self._by_rel = {}                # rel -> VideoSlot
        self._assign = {}                # rel -> replacement file path
        self._asis = {}                  # rel -> per-clip as-is override
        self._length = {}                # rel -> per-clip length choice
        self._color = {}                 # rel -> per-clip colour switch (PAD-312)
        self._variants = {}              # rel -> [extra clip, ...] (PAD-446)
        # PAD-446: the plugin's {"why", "slots", "max"} for this scan, or None
        # when it offers no random clips at all
        self._var_offer = None
        # the Advanced box (PAD-336): the game's own clips get a switch too,
        # and these are the ones switched on
        self._color_stock = False
        self._stock_on = set()
        # the preview's three switches on the players (PAD-329, PAD-330), as
        # they were left last time (PAD-348)
        self._lsw = look_switches.initial(window, "video")
        self._color_all = False          # the Color profile tab's "every replaced video"
        self._scan_id = 0
        self._scan_dir = ""
        self._scan_dir_prev = ""
        self._changed = set()
        self._foreign = set()
        self._twins = {}
        self._conv_cache = {}
        self._conv_pass = 0
        self._conv_kick = False
        self._unplayable_warned = set()
        self._current = None
        self._sort = ("#0", False)
        self._change_id = 0
        self._change_running = False
        self._scan_t0 = None
        self._rep_names = {}
        self._rep_names_dir = ""
        self._foreign_notes = {}
        self._rows = []
        self._index = {}                 # rel -> index in _rows
        self._restoring = False
        self._pane_seq = 0
        self._cmp = []                   # the Compare players (PAD-440)
        self._cmp_open = False
        self._cmp_ids = 0
        # PAD-448: the players' colour tables still to build ({path: steps}),
        # newest last, and whether a worker is on them
        self._lut_lock = threading.Lock()
        self._lut_want = {}
        self._lut_busy = False
        self._play_seq = 0
        self._stop_seq = 0
        self._sel_seq = 0
        self._running = False
        self._assets_traced = False
        self._q_scan = 0
        self._q_cancel = False
        self._q_clips = []
        self._q_card = ""
        self._m_init()                  # PAD-444: Played in (video_modes.py)
        self._u_init()                  # PAD-453: Undo / Redo (video_undo.py)
        self._m_select_after = []
        for v in (self.video_search_var, self.video_change_filter_var):
            v.trace_add("write", lambda *_a: self._refresh_list())
        for v in (self.video_trim_var, self.video_no_conversion_var):
            v.trace_add("write", lambda *_a: self._on_option_var())
        self.set(rows=[], view=[], sort={"key": "#0", "desc": False},
                 status="", empty=NO_PROJECT_TEXT, scanning=False,
                 ffmpeg_missing=False, project="", project_text=
                 NO_PROJECT_MIRROR, can_clear=False, running=False,
                 trim_enabled=True, trim_tip="", quality_report=False,
                 stern=False, preview=self._empty_preview(),
                 play={"side": None, "seq": 0}, stop_seq=0,
                 select={"rels": [], "seq": 0},
                 quality=self._quality_state(open_=False),
                 best_tip=BEST_TIP, best_supported=False,
                 color_offered=False, color_stock=False,
                 compare={"open": False, "max": COMPARE_MAX, "tiles": []},
                 widths=self._saved_widths())
        threading.Thread(target=vh.prune_cache, daemon=True,
                         name="video-cache-prune").start()

    # ==================================================================
    # manufacturer / show / running
    # ==================================================================
    def on_manufacturer(self, mfr):
        """apply_manufacturer's video part: a clean slate, the Trim
        tooltip's per-plugin note, and "Check card…" for the plugins that
        advertise video_quality_report."""
        self._trace_assets()
        self._scan_id += 1
        self._slots = []
        self._by_rel = {}
        self._assign = {}
        self._asis = {}
        self._length = {}
        self._color = {}
        self._color_all = False
        self._color_stock = False
        self._stock_on = set()
        self._scan_dir = ""
        self._changed = set()
        self._foreign = set()
        self._twins = {}
        self._conv_cache = {}
        # a report still reading the last manufacturer's card is dropped
        self._q_cancel = True
        self._q_scan += 1
        self._q_clips = []
        self._set_scan_ui(False, log_it=False)
        self._clear_preview()
        self._m_reset()
        self._u_reset()
        try:
            note = (mfr.video_length_note() or "").strip()
        except Exception:                                   # noqa: BLE001
            note = ""
        caps = mfr.capabilities
        self.set(
            trim_tip=("When on, a replacement longer or shorter than the "
                      "original clip is trimmed or padded to the original "
                      "length during the re-encode. When off, the "
                      "replacement's own length is kept."
                      + (("\n\n" + note) if note else "")),
            quality_report=bool(getattr(caps, "video_quality_report", False)),
            best_supported=bool(getattr(caps, "video_source_search", False)),
            stern=getattr(mfr, "key", "") == "stern",
            quality=self._quality_state(open_=False))
        self._b_cancel = True
        self._b_run += 1
        self._b_rows = []
        self.set(best=self._best_state(open_=False))
        self._refresh_list()
        self._update_project()

    def on_show(self):
        """<<NotebookTabChanged>> for Replace Video: the ffmpeg banner, the
        project folder defaulted from Extract, and the auto-scan."""
        self._refresh_ffmpeg_warning()
        self._default_assets_from_extract()
        self._update_project()
        self._maybe_rescan()
        self.publish_look()

    # -- As on the machine on the players (PAD-329) ------------------------
    def publish_look(self):
        """The colour steps the two players draw through: the Color profile
        tab's profiles change elsewhere, so this is worked out again whenever
        the tab shows, a row loads, or a switch moves."""
        offered = self._per_file_colour()
        sw = dict(self._lsw)
        look = {"offered": offered, "on": any(sw.values()), "sw": sw, "parts": None,
                "orig": [], "rep": [], "lut": {"orig": None, "rep": None}}
        with self._lut_lock:
            self._lut_want.clear()
        folder = self._assets_path()
        if offered and folder and os.path.isdir(folder):
            try:
                from ...core import colour_profile
                look["parts"] = colour_profile.preview_parts(folder)
            except Exception:                           # noqa: BLE001
                log.exception("preview parts")
        if offered and look["on"] and folder and os.path.isdir(folder):
            rel = self._current
            switch = self._color_state(rel) if rel else None
            try:
                from ...core import colour_profile
                kw = dict(overlay_on=sw["overlay"], files_on=sw["files"],
                          screen_on=sw["screen"], rel=rel)
                look.update(colour_profile.video_look(
                    folder, switch, self._own_colours(), **kw))
                exact = colour_profile.video_look_exact(
                    folder, switch, self._own_colours(), **kw)
                prev = (self.get("look") or {}).get("lut") or {}
                look["lut"] = {side: self._lut(exact[side], prev.get(side))
                               for side in ("orig", "rep")}
            except Exception:                           # noqa: BLE001
                log.exception("video machine look")
        if look != self.get("look"):
            self.set(look=look)
        if self._cmp_open:
            self._cmp_steps()
            self._cmp_publish()

    def _own_colours(self):
        """The Scenes gear menu's setting: a clip with no color profile
        attached passes the machine screen by."""
        var = getattr(self.window, "scenes_own_colours_var", None)
        try:
            return False if var is None else bool(var.get())
        except Exception:                               # noqa: BLE001
            return False

    def _lut(self, steps, prev):
        """The colour table a player draws *steps* through (PAD-448: the
        exact maths, colour ranges too): its path once built, ``None`` for
        no steps.  One not built yet is built on a worker and the player
        keeps *prev* meanwhile, so a slider dragged in the Colors bar never
        holds the page up."""
        from ...core import colour_profile
        path = colour_profile.look_lut_path(steps)
        if path is None or os.path.isfile(path):
            return path
        with self._lut_lock:
            self._lut_want.pop(path, None)
            self._lut_want[path] = steps
            if self._lut_busy:
                return prev
            self._lut_busy = True
        threading.Thread(target=self._lut_work, daemon=True,
                         name="video-lut").start()
        return prev

    def _lut_work(self):
        """Build the wanted colour tables, newest first; each one built
        redraws the players, which then find it."""
        from ...core import colour_profile
        while True:
            with self._lut_lock:
                if not self._lut_want:
                    self._lut_busy = False
                    return
                _path, steps = self._lut_want.popitem()
            try:
                colour_profile.build_look_lut(steps)
            except Exception:                           # noqa: BLE001
                log.exception("video colour table")
                continue
            self.ctx.loop.post(self.publish_look)

    @rpc
    def set_look_part(self, part, on):
        """One of the preview's three switches: "overlay", "files" or
        "screen" (PAD-330).  Only the players change."""
        if part not in self._lsw:
            return False
        self._lsw[part] = bool(on)
        look_switches.save(self.window, "video", self._lsw)
        self.publish_look()
        return True

    @rpc
    def set_machine_look(self, on):
        """All three switches at once: as on the machine, or the PC's own
        colours."""
        for k in self._lsw:
            self._lsw[k] = bool(on)
        look_switches.save(self.window, "video", self._lsw)
        self.publish_look()
        return True

    def on_running(self, running, mode):
        self._running = bool(running)
        self.set(running=self._running)
        self._update_clear_all()

    def on_close(self):
        self._scan_id += 1
        self._conv_pass += 1
        self._q_cancel = True
        self._b_cancel = True

    def _trace_assets(self):
        """Follow the shared project folder (the Tk mirror label).  Done on
        the first manufacturer, once every tab service exists."""
        if self._assets_traced:
            return
        self._assets_traced = True
        try:
            self.window.write_assets_var.trace_add(
                "write", lambda *_a: self._update_project())
        except Exception:                                   # noqa: BLE001
            log.exception("video: tracing the project folder")

    def _assets_path(self):
        try:
            return (self.window.write_assets_var.get() or "").strip()
        except Exception:                                   # noqa: BLE001
            return ""

    def _update_project(self):
        path = self._assets_path()
        self.set(project=path, project_text=path or NO_PROJECT_MIRROR)

    def _is_running(self):
        try:
            return bool(self.window._is_running())
        except Exception:                                   # noqa: BLE001
            return self._running

    def _mfr_key(self):
        return getattr(self.mfr, "key", "") or ""

    def _default_assets_from_extract(self):
        """MainWindow._default_assets_from_extract."""
        if self._assets_path():
            return
        try:
            out = (self.window.extract_output_var.get() or "").strip()
        except Exception:                                   # noqa: BLE001
            out = ""
        if out and os.path.isdir(out):
            self.window.write_assets_var.set(out)

    def _refresh_ffmpeg_warning(self):
        """MainWindow._refresh_video_ffmpeg_warning: re-probe on every visit
        so installing ffmpeg mid-session clears the banner."""
        from ...core import audio as _audio
        _audio._ffmpeg_path = None
        self.set(ffmpeg_missing=not bool(_audio.find_ffmpeg()))

    def _maybe_rescan(self):
        """MainWindow._maybe_rescan_video."""
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_video",
                                      False):
            return
        path = self._assets_path()
        if path and path != self._scan_dir:
            self._scan_async()

    def _tab_present(self):
        mfr = self.mfr
        return bool(mfr is not None and getattr(mfr.capabilities,
                                                "replace_video", False))

    # ==================================================================
    # the cross-tab calls the run logic fans out
    # ==================================================================
    def pending_video_assignments(self, assets_dir):
        """MainWindow.pending_video_assignments: ``(slots_by_rel,
        assignments, trim, no_conversion, asis_overrides)`` for
        *assets_dir*, or None.  Called from the Write worker thread; it
        only reads."""
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_video",
                                      False):
            return None
        if not assets_dir:
            return None
        if not vh.same_dir(assets_dir, self._scan_dir or ""):
            return None
        by_rel = {rel: s for rel, s in self._by_rel.items()
                  if rel not in self._m_virtual}
        assignments = {rel: rep for rel, rep in dict(self._assign).items()
                       if rep and rel in by_rel}
        if not assignments:
            return None
        return (by_rel, assignments,
                bool(self.video_trim_var.get()),
                bool(self.video_no_conversion_var.get()),
                {rel: bool(v) for rel, v in dict(self._asis).items()
                 if rel in assignments},
                {rel: v for rel, v in dict(self._length).items()
                 if rel in assignments})

    def replacement_folder_mismatches(self, assets_dir):
        """The video part of MainWindow.replacement_folder_mismatches."""
        if not assets_dir:
            return []
        live = [rel for rel, rep in self._assign.items()
                if rep and rel in self._by_rel]
        if not live:
            return []
        scanned = self._scan_dir or self._scan_dir_prev or ""
        if not vh.same_dir(scanned, assets_dir):
            return [("video", len(live), scanned or "(unknown)")]
        return []

    def invalidate_asset_scans(self, rescan_visible=True):
        """The video part of MainWindow.invalidate_asset_scans."""
        if self._scan_dir:
            self._scan_dir_prev = self._scan_dir
        self._scan_dir = ""
        if rescan_visible and self.window.current_tab_key() == self.key:
            self._scan_async()

    def reload_assets_tabs(self):
        """The video part of MainWindow.reload_assets_tabs: forget the scan
        stamp and re-scan against the current folder (every tab present
        for the manufacturer, not only the one on screen)."""
        self.invalidate_asset_scans(rescan_visible=False)
        try:
            self.window._relink_hint_for = None
        except Exception:                                   # noqa: BLE001
            pass
        if self._tab_present():
            self._scan_async()

    def stop_all_preview_playback(self):
        """Stop both preview panes (the page pauses its players)."""
        self._stop_seq += 1
        self.set(stop_seq=self._stop_seq)

    def clear_replace_assignments(self, assets_dir):
        """The video part of MainWindow.clear_replace_assignments: drop
        every pick and wipe the sidecar (keeping what Revert all keeps)."""
        from ...core import staged_changes
        self._assign = {}
        self._asis = {}
        self._length = {}
        self._color = {}
        self._color_stock = False
        self._stock_on = set()
        kept = {}
        try:
            from ...plugins.stern import stock_modes
            kept = stock_modes.kept_by_revert_all(
                staged_changes.load(assets_dir))
        except Exception:                                   # noqa: BLE001
            kept = {}
        staged_changes.save(assets_dir, kept)
        self._u_reset()

    def refresh_after_revert(self):
        """The video part of MainWindow.refresh_after_revert."""
        self._changed = set()
        self._foreign = set()
        self._refresh_list()
        if self._slots:
            self._start_change_scan()

    def reveal_video_slot(self, rel):
        """MainWindow.reveal_video_slot (the Scenes window): show one slot
        on this tab, clearing any filter that would hide it."""
        self.window.select_tab(self.ns)
        if rel not in self._by_rel:
            return False
        i = self._index.get(rel)
        if i is None or i not in set(self.get("view") or []):
            self.video_search_var.set("")
            self.video_change_filter_var.set("All")
            self._refresh_list()
        self._reselect([rel])
        self._load_track(rel)
        return True

    # ==================================================================
    # scanning
    # ==================================================================
    @rpc
    def scan(self):
        """The Scan button (Cancel scan while one runs)."""
        if self.get("scanning"):
            return self.cancel_scan()
        self._scan_async()
        return True

    @rpc
    def cancel_scan(self):
        """MainWindow._cancel_scan("video")."""
        self._scan_id += 1
        t0, self._scan_t0 = self._scan_t0, None
        if t0 is not None:
            self.log("%s scan cancelled after %.1f s."
                     % (_SCAN_LABEL, time.monotonic() - t0), "info")
        self.set(scanning=False, rows=[], view=[],
                 empty="Scan cancelled — click Scan to try again.")
        self._rows = []
        self._index = {}
        return True

    def _set_scan_ui(self, active, log_it=True):
        """MainWindow._set_tab_scanning("video", ...)."""
        if active:
            if self._scan_t0 is not None and log_it:
                self.log("%s scan replaced after %.1f s by a newer scan."
                         % (_SCAN_LABEL, time.monotonic() - self._scan_t0),
                         "info")
            self._scan_t0 = time.monotonic()
            if log_it:
                self.log("%s scan started." % _SCAN_LABEL, "info")
            self._rows = []
            self._index = {}
            self.set(scanning=True, rows=[], view=[],
                     empty="Scanning for video files…")
        else:
            t0, self._scan_t0 = self._scan_t0, None
            if t0 is not None and log_it:
                self.log("%s scan finished in %.1f s."
                         % (_SCAN_LABEL, time.monotonic() - t0), "info")
            self.set(scanning=False)

    def _scan_async(self):
        """MainWindow._scan_video_slots_async."""
        from ...core.video_slots import scan_video_slots
        path = self._assets_path()
        self._scan_id += 1
        scan_id = self._scan_id
        self._update_project()
        if not path or not os.path.isdir(path):
            self._slots = []
            self._by_rel = {}
            self._refresh_list()
            self.set(empty=NO_PROJECT_TEXT)
            self._set_scan_ui(False)
            return
        mfr = self.mfr

        def _work():
            try:
                roots = mfr.video_slot_dirs(path) if mfr else None
            except Exception:                               # noqa: BLE001
                roots = None
            try:
                exts = mfr.video_slot_exts(path) if mfr else None
            except Exception:                               # noqa: BLE001
                exts = None
            try:
                slots = scan_video_slots(path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:                               # noqa: BLE001
                slots = []
            if self._scan_id != scan_id:
                return
            # PAD-446: which slots can play one of several clips at random
            # (it may open the card image, so here and not on the UI thread)
            try:
                offer = (mfr.video_variants_offer(
                    path, [sl.rel_path for sl in slots]) if mfr else None)
            except Exception:                               # noqa: BLE001
                offer = None
            if self._scan_id != scan_id:
                return
            self.ctx.loop.post(self._populate_after_scan, slots, scan_id,
                               path, offer)

        self._set_scan_ui(True)
        threading.Thread(target=_work, daemon=True,
                         name="video-scan").start()

    def _populate_after_scan(self, slots, scan_id, scan_dir, offer=None):
        """MainWindow._populate_video_after_scan."""
        if self._scan_id != scan_id:
            return
        from ...core import staged_changes
        self._set_scan_ui(False)
        self._slots = slots
        self._by_rel = {s.rel_path: s for s in slots}
        self._var_offer = offer if isinstance(offer, dict) else None
        if scan_dir != self._scan_dir:
            staged = self._load_staged(scan_dir)
            self._assign = staged_changes.live_assignments(
                staged.get("video"), self._by_rel)
            self._warn_dropped(staged.get("video"), scan_dir)
            self._restoring = True
            try:
                # A folder that doesn't say is at the default, never the
                # last project's setting.
                self.video_trim_var.set(bool(staged.get("video_trim")))
                self.video_no_conversion_var.set(
                    bool(staged.get("video_no_conversion")))
                self.video_best_quality_var.set(
                    bool(staged.get("video_best_quality")))
                self._asis = {
                    rel: bool(v) for rel, v in
                    (staged.get("video_asis_slots") or {}).items()
                    if rel in self._by_rel}
                self._length = {
                    rel: v for rel, v in
                    (staged.get("video_length_slots") or {}).items()
                    if rel in self._by_rel and _length_ok(v)}
                self._color = {
                    rel: bool(v) for rel, v in
                    (staged.get("video_color_slots") or {}).items()
                    if rel in self._by_rel}
                self._color_all = bool(staged.get("color_all_videos"))
                self._color_stock = bool(staged.get("video_color_stock"))
                self._stock_on = {rel for rel, v in self._color.items()
                                  if v and not self._assign.get(rel)
                                  and self._color_stock}
                self._color = {rel: v for rel, v in self._color.items()
                               if self._assign.get(rel)}
                self._variants = _variants_from(staged.get("video_variants"),
                                                self._by_rel)
                val = staged.get("video_change_filter")
                if val in vh.CHANGE_FILTER_VALUES:
                    self.video_change_filter_var.set(val)
                elif "video_changed_only" in staged:
                    self.video_change_filter_var.set(
                        "Changed" if staged["video_changed_only"] else "All")
            finally:
                self._restoring = False
            self._update_trim_enabled()
        else:
            self._assign = {rel: rep for rel, rep in self._assign.items()
                            if rel in self._by_rel}
            self._asis = {rel: v for rel, v in self._asis.items()
                          if rel in self._by_rel}
            self._length = {rel: v for rel, v in self._length.items()
                            if rel in self._by_rel}
            self._color = {rel: v for rel, v in self._color.items()
                           if rel in self._by_rel}
            self._stock_on = {rel for rel in self._stock_on
                              if rel in self._by_rel}
            self._variants = {rel: v for rel, v in self._variants.items()
                              if rel in self._by_rel}
        folder_changed = scan_dir != self._scan_dir
        self._scan_dir = scan_dir
        self._changed = set()
        self._foreign = set()
        if folder_changed:
            self._clear_preview()
            self._m_reset()
            self._u_reset()
        # the modes the card's program names (read once per card; a card read
        # before publishes now, so the rows below carry them)
        self._m_kick(scan_dir)
        self._refresh_list()
        # Default to the first clip so a poster frame shows on a fresh scan
        # (PAD-444: the row a copy was just made or dropped for, when it is listed)
        view = self.get("view") or []
        after = [r for r in self._m_select_after if r in self._index]
        self._m_select_after = []
        if after and self._index[after[0]] not in view:
            self.video_search_var.set("")
            self._m_filter = ""
            self._refresh_list()
            view = self.get("view") or []
        if after:
            self._reselect(after[:1])
            self._load_track(after[0])
        elif view:
            first = self._rows[view[0]]["rel"]
            self._reselect([first])
            self._load_track(first)
        self._start_change_scan()
        self._probe_metadata_async(scan_id)

    def _load_staged(self, assets_dir):
        """MainWindow._load_staged_changes (plus the replacement-name
        cache every Replace tab reads)."""
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
        self._rep_names_dir = assets_dir
        self._rep_names = {
            rel: str(name)
            for rel, name in (data.get("replacement_names") or {}).items()
            if isinstance(name, str) and name.strip()}
        return data

    def _remembered_rep_name(self, rel):
        """MainWindow._remembered_rep_name("video", rel)."""
        if not self._scan_dir or not self._rep_names:
            return ""
        if not vh.same_dir(self._scan_dir, self._rep_names_dir or "\0"):
            return ""
        return self._rep_names.get(rel, "")

    def _warn_dropped(self, saved, scan_dir):
        """MainWindow._warn_dropped_assignments("video", ...)."""
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
                    % (rel, "video", why, path, hint), "info")
            else:
                any_pending = True
                self.log(
                    'Saved %s replacement for "%s" wasn\'t restored — %s:\n'
                    '        %s%s' % ("video", rel, why, path, hint),
                    "error")
        if len(dropped) > 6:
            self.log("…and %d more saved %s replacement(s) like this."
                     % (len(dropped) - 6, "video"),
                     "error" if any_pending else "info")
        key = os.path.normcase(os.path.normpath(scan_dir or ""))
        if getattr(self.window, "_relink_hint_for", None) != key:
            try:
                self.window._relink_hint_for = key
            except Exception:                               # noqa: BLE001
                pass
            self.log(
                'Moved this project (or the files it points at) to another '
                'PC or drive? Project ▾ → "Relink moved files…" searches a '
                'folder you pick and re-points every one of these at once.',
                "info")

    # ---- metadata probe (MainWindow._run_probe_pass) -------------------
    def _probe_metadata_async(self, scan_id):
        """MainWindow._probe_video_metadata_async: ffprobe each slot on a
        worker pool; a loop timer drains results in bounded batches."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from ...core.video import backend_for, detect_video_info
        pending = [s for s in self._slots
                   if s.info is None and backend_for(s.abs_path) is None]
        if not pending:
            return
        q = queue_mod.SimpleQueue()
        done = threading.Event()

        def _coordinator():
            try:
                workers = min(8, (os.cpu_count() or 4))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(detect_video_info, s.abs_path): s
                            for s in pending}
                    for fut in as_completed(futs):
                        if self._scan_id != scan_id:
                            for f in futs:
                                f.cancel()
                            return
                        try:
                            info = fut.result()
                        except Exception:                   # noqa: BLE001
                            info = None
                        q.put((futs[fut].rel_path, info))
            except Exception:                               # noqa: BLE001
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
                self.ctx.loop.after(100, _drain)

        threading.Thread(target=_coordinator, daemon=True,
                         name="video-probe").start()
        self.ctx.loop.after(100, _drain)

    def _apply_meta(self, scan_id, rel, info):
        """MainWindow._apply_video_meta."""
        if self._scan_id != scan_id:
            return
        slot = self._by_rel.get(rel)
        if slot is None:
            return
        slot.info = info
        slot.probed = True
        self._warn_unplayable(rel, slot)
        if rel == self._current:
            self._update_note(rel)
        i = self._index.get(rel)
        if i is not None:
            self._put_row(i, self._row(slot))
        self._m_meta(rel)
        if self._assign.get(rel) and not self._conv_kick:
            # its Convert answer can be worked out properly now
            self._conv_kick = True
            self.ctx.loop.after(300, self._conv_kicked)

    def _conv_kicked(self):
        self._conv_kick = False
        self._probe_conv_async()

    def _warn_unplayable(self, rel, slot):
        """MainWindow._warn_unplayable_slot."""
        why = vh.slot_unplayable(self._mfr_key(), slot)
        if not why:
            return
        key = (self._scan_dir, rel)
        if key in self._unplayable_warned:
            return
        self._unplayable_warned.add(key)
        self.log(
            'Video slot "%s" currently holds a clip that %s — on the machine '
            'it will play its sound over a black picture. Assign a good '
            'replacement (or revert the slot) before building.' % (rel, why),
            "error")

    # ---- change diff (MainWindow._start_change_scan("video")) ---------
    def _start_change_scan(self):
        from ...core import checksums, staged_originals
        path = self._assets_path()
        rels = [s.rel_path for s in self._slots]
        self._change_id += 1
        change_id = self._change_id
        if not path or not os.path.isdir(path) or not rels:
            self._changed = set()
            self._foreign = set()
            self._twins = {}
            self._mark_change_scan(False)
            return
        self._mark_change_scan(True)
        # PAD-444: a mode's own copy is the project's file, not the card's
        copies = {r.get("rel") for r in self._m_records() if r.get("state") != "shared"}

        def _work():
            from ...core import folder_match
            foreign, twins = set(), {}
            try:
                baseline = checksums.read_baseline_any(path)
                rel_set = set(rels)
                snaps = {r for r in staged_originals.snapshot_rels(path)
                         if r in rel_set}
                to_hash = [r for r in rels if r not in snaps]
                changed = snaps | checksums.changed_rels(
                    path, [r for r in to_hash if r not in copies],
                    baseline=baseline)
                if baseline:
                    foreign, twins = folder_match.foreign_twins(
                        [r for r in rels if r not in copies], baseline)
            except Exception:                               # noqa: BLE001
                changed = set()

            def _apply():
                if self._change_id != change_id:
                    return
                self._changed = set(changed)
                self._foreign = set(foreign)
                self._twins = dict(twins)
                self._change_running = False
                self._note_foreign(path, foreign, twins)
                self._refresh_list()
                if self._current:
                    self._reload_rep_pane(self._current)
            self.ctx.loop.post(_apply)

        threading.Thread(target=_work, daemon=True,
                         name="video-changes").start()

    def _mark_change_scan(self, running):
        """MainWindow._mark_change_scan: the count line wears the
        "still checking…" tail while the diff runs."""
        self._change_running = bool(running)
        text = self.get("status") or ""
        has = text.endswith(vh.CHANGE_SCAN_NOTE)
        if running and text and not has:
            self.set(status=text + vh.CHANGE_SCAN_NOTE)
        elif not running and has:
            self.set(status=text[:-len(vh.CHANGE_SCAN_NOTE)])

    def _note_foreign(self, assets_path, foreign, twins):
        """MainWindow._note_foreign_slots("video", ...)."""
        key = os.path.normcase(os.path.normpath(assets_path or ""))
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
            % (_SCAN_LABEL, len(foreign), shown), "warning")
        twins = twins or {}
        if twins:
            rel = sorted(twins)[0]
            self.log(
                "%s: %d of them are named like one of the card's files but "
                "are a different file type (%s where the card has %s), so "
                "they sit beside their slot instead of in it. Keep your files "
                "in a folder of their own and use \"Replace from folder…\": "
                "it matches names whatever the file type."
                % (_SCAN_LABEL, len(twins), os.path.basename(rel),
                   os.path.basename(twins[rel])), "warning")

    def _slot_changed_on_disk(self, rel):
        """MainWindow._slot_changed_on_disk("video", rel)."""
        if rel in self._changed:
            return True
        from ...core import staged_originals
        return staged_originals.snapshot_path(self._scan_dir, rel) is not None

    def _changed_cell(self, rel):
        """MainWindow._changed_on_disk_cell("video", rel)."""
        name = self._remembered_rep_name(rel)
        return "✓ changed on disk (%s)" % name if name else "✓ changed on disk"

    def _rep_pane_empty_text(self, rel, default):
        """MainWindow._rep_pane_empty_text("video", rel, default)."""
        from ...core import staged_originals
        follow = self._m_follow_text(rel)
        if follow:
            return follow
        if rel is None or not self._slot_changed_on_disk(rel):
            return default
        if rel in self._foreign:
            twin = self._twins.get(rel)
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

    # ==================================================================
    # the list
    # ==================================================================
    def _stock_path(self, rel):
        """MainWindow._video_stock_path."""
        from ...core import staged_originals
        if not rel:
            return None
        return staged_originals.snapshot_path(self._scan_dir, rel)

    def _trim_for(self, rel):
        """Whether *rel* is matched to a length: its own Length choice,
        else the Trim / pad box."""
        choice = self._length.get(rel)
        if choice is None:
            return bool(self.video_trim_var.get())
        return choice != LENGTH_FULL

    def _length_cell(self, rel, length):
        """The Length column, with a clip's own length choice after it."""
        choice = self._length.get(rel)
        if choice is None or not self._assign.get(rel):
            return length
        secs = length_seconds(choice)
        word = ("%g s" % secs if secs else
                "stock" if choice == LENGTH_STOCK else "full")
        return "%s • %s" % (length, word)

    def _asis_for(self, rel):
        """MainWindow._video_asis_for."""
        flag = self._asis.get(rel)
        if flag is None:
            return bool(self.video_no_conversion_var.get())
        return bool(flag)

    def _conv_key(self, rel, path):
        """MainWindow._video_conv_key, plus whether the slot's own clip has
        been probed yet: an answer worked out before the metadata pass
        reached the slot compares against nothing and says "Re-encode" for
        a clip that would repackage (the Tk cache kept that answer)."""
        try:
            st = os.stat(path)
            ident = (st.st_size, st.st_mtime_ns)
        except OSError:
            ident = (0, 0)
        slot = self._by_rel.get(rel)
        return (rel, path, ident, self._asis_for(rel),
                self._trim_for(rel),
                bool(slot is not None and slot.info is not None))

    def _conv_cached(self, rel, path):
        """MainWindow._video_conv_cached."""
        if not path:
            return ""
        return self._conv_cache.get(self._conv_key(rel, path), "…")

    def _conv_cell(self, rel, path):
        """MainWindow._video_conv_cell."""
        text = self._conv_cached(rel, path)
        if text and self._asis.get(rel) is not None:
            return "• " + text
        return text

    @staticmethod
    def _conv_cls(text):
        t = (text or "").lstrip("• ")
        if t.startswith("✗"):
            return "bad"
        if t == vh.CONV_ASIS_NOISY:
            return "stray"
        return ""

    def _row(self, s):
        """One row's cells (MainWindow._refresh_video_list's insert)."""
        rel = s.rel_path
        rep = self._assign.get(rel)
        is_changed = rel in self._changed
        if rep:
            rep_disp = os.path.basename(rep)
            cls = "ondisk" if is_changed else "picked"
        elif rel in self._foreign:
            rep_disp, cls = vh.NOT_ON_CARD_MARK, "stray"
        elif is_changed:
            rep_disp, cls = self._changed_cell(rel), "ondisk"
        else:
            rep_disp, cls = "Choose…", ""
        if s.info is None and not s.probed:
            length, res, aud = "…", "…", "…"
        else:
            length, res = s.duration_str(), s.resolution_str()
            aud = s.info.audio_summary() if s.info else ""
        fmt = vh.fmt_cell(self._mfr_key(), s)
        conv = self._conv_cell(rel, rep)
        d = os.path.dirname(rel)
        var = self._variants.get(rel) or []
        return {"rel": rel, "name": os.path.basename(rel),
                # PAD-446: the slot's random clips, and the words for them
                "var": len(var), "var_tip": self._variants_words(rel),
                "dir": (d + "/") if d else "",
                "len": self._length_cell(rel, length), "res": res,
                "fmt": fmt, "fmt_bad": fmt.endswith("⚠"), "aud": aud,
                "rep": rep_disp, "rep_cls": cls, "conv": conv,
                "conv_cls": self._conv_cls(conv),
                "col": self._color_state(rel), "col_own": rel in self._color,
                "col_lock": self._color_locked(rel),
                "col_stock": bool(self._color_stock
                                  and not self._assign.get(rel)),
                **self._m_row(rel)}

    # -- the chosen-files colour profile (PAD-312) ------------------------
    def _per_file_colour(self):
        """Offered only where the display-wide profile does not correct the
        files itself (Spike 2)."""
        mfr = self.mfr
        try:
            return bool(mfr is not None and mfr.colour_profile_on_display())
        except Exception:                               # noqa: BLE001
            return False

    def _color_state(self, rel):
        if not (rel and self._per_file_colour()):
            return None
        if not self._assign.get(rel):
            # the game's own clip: a switch only with Advanced ticked
            # (PAD-336), and only its own (the tab-wide box never reaches it)
            return (rel in self._stock_on) if self._color_stock else None
        own = self._color.get(rel)
        return bool(self._color_all if own is None else own)

    def _color_locked(self, rel):
        """The game's own clip (PAD-334): no switch, shown as a lock, the
        way Scenes shows a stock picture, until Advanced unlocks it."""
        return bool(rel and not self._assign.get(rel)
                    and not self._color_stock and self._per_file_colour())

    @rpc
    @undoable("Advanced")
    def set_color_stock(self, on):
        """The Advanced box (PAD-336): unlock the Color switch on the game's
        own clips.  Unticked, they lock again and any of them already built
        with the profile get their original file back."""
        on = bool(on)
        if on == self._color_stock or not self._per_file_colour():
            return False
        self._color_stock = on
        back = []
        if not on:
            was = sorted(self._stock_on)
            self._stock_on = set()
            back = [] if self._is_running() else self._put_back(was)
        if on:
            msg = ("the game's own clips are unlocked: each one's Color "
                   "switch can bake the individual files profile into it")
        else:
            msg = "the game's own clips are locked again" + (
                " (%d put back to the original)" % len(back) if back else "")
        self.log("Replace Video: %s." % msg, "info")
        self._save_staged()
        self._refresh_list()
        if self._current:
            self._reload_rep_pane(self._current)
        self._color_changed()
        self.publish_look()
        return True

    def color_all_changed(self):
        """The Color profile tab moved its "every replaced video" box."""
        from ...core import staged_changes
        folder = self._assets_path()
        self._color_all = bool(folder and staged_changes.load(folder).get(
            "color_all_videos"))
        self._refresh_list()
        self.publish_look()

    def _color_changed(self):
        for ns, name in (("color", "asset_switches_changed"),
                         ("write", "_maybe_rescan_write_preview")):
            try:
                fn = getattr(self.window.service(ns), name, None)
            except Exception:                           # noqa: BLE001
                fn = None
            if fn is not None:
                try:
                    fn()
                except Exception:                       # noqa: BLE001
                    log.exception("video colour %s.%s", ns, name)

    @rpc
    @undoable("the colors of %s")
    def set_color(self, rel, value):
        """This clip's own colour switch (PAD-312): True / False, or None
        to follow the Color profile tab's box again."""
        if (rel in self._by_rel and not self._assign.get(rel)
                and self._color_stock and self._per_file_colour()):
            return self._set_stock_color(rel, bool(value))
        if not (rel in self._by_rel and self._assign.get(rel)
                and self._per_file_colour()):
            return False
        if value is None:
            self._color.pop(rel, None)
            self.log("Replace Video: %s follows the Color profile tab's box "
                     "again (%s)." % (rel, "color profile attached" if self._color_all
                                      else "no color profile attached"), "info")
        else:
            self._color[rel] = bool(value)
            self.log("Replace Video: %s %s." % (
                rel, "has the color profile attached" if value
                else "has no color profile attached"), "info")
        self._save_staged()
        self._refresh_list()
        self._color_changed()
        self.publish_look()
        return True

    def _set_stock_color(self, rel, on):
        """A game's own clip's switch, with Advanced ticked (PAD-336): on,
        the next build re-encodes it from its original with the individual
        files profile; off, a clip already built that way gets its original
        file back."""
        if on == (rel in self._stock_on):
            return True
        if on:
            self._stock_on.add(rel)
            self.log("Replace Video: %s (the game's own clip) gets the "
                     "individual files color profile at the next build; it "
                     "is re-encoded for that." % rel, "info")
        else:
            self._stock_on.discard(rel)
            back = [] if self._is_running() else self._put_back([rel])
            self.log("Replace Video: %s stays as the game shipped it%s." % (
                rel, " (its original file is back)" if back else ""), "info")
        self._save_staged()
        self._refresh_list()
        self._reload_rep_pane(rel)
        self._color_changed()
        self.publish_look()
        return True

    def color_targets(self):
        """PAD-439: the clips the Colors bar's "Apply to all videos" gives
        its profile, ``{rel: attached}``: every replaced clip, and the game's
        own clips attached with Advanced ticked."""
        if not self._per_file_colour():
            return {}
        out = {}
        for rel in set(self._assign) | self._stock_on:
            on = self._color_state(rel) if rel in self._by_rel else None
            if on is not None and (on or self._assign.get(rel)):
                out[rel] = on
        return out

    def put_color_switches(self, switches):
        """PAD-439: replaced clips' own switches set at once (``True`` /
        ``False``, ``None`` = follow the box again), one save and one redraw.
        Returns what each was, the same way (Apply to all's Undo)."""
        before = {}
        for rel, value in (switches or {}).items():
            if not (rel in self._by_rel and self._assign.get(rel)):
                continue
            before[rel] = self._color.get(rel)
            if value is None:
                self._color.pop(rel, None)
            else:
                self._color[rel] = bool(value)
        if before:
            self._save_staged()
            self._refresh_list()
            self._color_changed()
            self.publish_look()
        return before

    def _put_row(self, i, row):
        if 0 <= i < len(self._rows) and self._rows[i] != row:
            self._rows[i] = row
            self.set_item("rows", i, row)

    def _publish_rows(self, rows):
        """Send the rows: whole list when the slots changed, else only the
        rows whose cells did (a 6000-clip card must not resend them all
        for one pick)."""
        same = (len(rows) == len(self._rows)
                and all(a["rel"] == b["rel"]
                        for a, b in zip(rows, self._rows)))
        if not same:
            self._rows = rows
            self._index = {r["rel"]: i for i, r in enumerate(rows)}
            self.set(rows=rows)
            return
        for i, row in enumerate(rows):
            if row != self._rows[i]:
                self._rows[i] = row
                self.set_item("rows", i, row)

    def _change_pred(self):
        """MainWindow._change_filter_pred("video")."""
        mode = self.video_change_filter_var.get()
        if mode not in ("Changed", "Unchanged"):
            return None
        # PAD-446: a slot given random clips is a change a build makes too
        touched = set(self._assign) | self._changed | set(self._variants)
        want = mode == "Changed"
        return lambda rel: (rel in touched) == want

    def _sort_key(self, col):
        changed = self._changed

        def _key(s):
            if col == "len":
                return (s.duration,)
            if col == "res":
                # width first, then height: every 1920-wide row together (PAD-207)
                return ((s.info.width, s.info.height) if s.info else (-1, -1),)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "aud":
                a = s.info.audio_summary() if s.info else ""
                return (a.lower(), s.rel_path.lower())
            if col == "rep":
                rep = self._assign.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                return (1, "") if s.rel_path in changed else (2, "")
            if col == "conv":
                mode = self._conv_cached(s.rel_path,
                                         self._assign.get(s.rel_path))
                return ((0, mode) if mode else (1, ""), s.rel_path.lower())
            return (s.rel_path.lower(),)
        return _key

    def _refresh_list(self):
        """MainWindow._refresh_video_list: filter + sort, the rows, the
        count line, the empty state, the Clear button, the Convert pass and
        the callout under the preview."""
        if self._restoring:
            return
        listed = self._m_slots()            # PAD-444: + the followers' rows
        self._publish_rows([self._row(s) for s in listed])
        query = (self.video_search_var.get() or "").strip().lower()
        slots = [s for s in listed
                 if not query or query in s.rel_path.lower()
                 or query in self._m_of.get(s.rel_path, "").lower()]
        ok = self._change_pred()
        if ok is not None:
            slots = [s for s in slots if ok(s.rel_path)]
        slots = [s for s in slots if self._m_keep(s.rel_path)]
        col, desc = self._sort
        slots.sort(key=self._sort_key(col), reverse=desc)
        view = [self._index[s.rel_path] for s in slots
                if s.rel_path in self._index]
        total = len(self._slots)
        changed_total = len(set(self._assign) | self._changed
                            | set(self._variants))
        values = {"view": view, "sort": {"key": col, "desc": bool(desc)}}
        if total == 0:
            values["status"] = ""
            if not self.get("scanning"):
                values["empty"] = ("No replaceable video found in this "
                                   "folder." if self._scan_dir
                                   else NO_PROJECT_TEXT)
        else:
            shown = len(view)
            extra = "  (%d shown)" % shown if shown != total else ""
            values["status"] = ("%d of %d slots changed%s"
                                % (changed_total, total, extra)
                                + (vh.CHANGE_SCAN_NOTE if self._change_running
                                   else ""))
            values["empty"] = "" if shown else (
                "No slots match the search, the Show filter and the mode."
                if self._m_filter else
                "No slots match the search and the Show filter.")
        values["counts"] = {"changed": changed_total, "total": total,
                            "shown": len(view)}
        values["color_offered"] = bool(total and self._per_file_colour())
        values["color_stock"] = self._color_stock
        self.set(**values)
        # the rail's count beside "Video" (the designs' rail: "Video 1")
        try:
            self.window.set_tab_badge(self.ns, changed_total or None)
        except Exception:                                   # noqa: BLE001
            pass
        self._update_clear_all()
        self._probe_conv_async()
        self._update_note()
        self._cmp_sync()

    # ---- Convert column (MainWindow._video_probe_conv_async) -----------
    def _probe_conv_async(self):
        self._conv_pass += 1
        pass_id = self._conv_pass
        pending = [(self._conv_key(rel, path), rel, path)
                   for rel, path in sorted(self._assign.items())]
        pending = [p for p in pending if p[0] not in self._conv_cache]
        if not pending:
            return
        slots = {rel: self._by_rel.get(rel) for _k, rel, _p in pending}
        stock = {rel: self._stock_path(rel) for _k, rel, _p in pending}
        asis = {rel: self._asis_for(rel) for _k, rel, _p in pending}
        trims = {rel: self._trim_for(rel) for _k, rel, _p in pending}

        def _work():
            out = []
            for key, rel, path in pending:
                if self._conv_pass != pass_id:
                    return
                out.append((key, vh.conv_mode(slots.get(rel), path,
                                              asis.get(rel, False),
                                              trims.get(rel, False),
                                              stock.get(rel))))
            self.ctx.loop.post(self._apply_conv, pass_id, out)

        threading.Thread(target=_work, daemon=True,
                         name="video-convert").start()

    def _apply_conv(self, pass_id, results):
        """MainWindow._apply_video_conv."""
        if self._conv_pass != pass_id:
            return
        for key, mode in results:
            self._conv_cache[key] = mode
            rel = key[0]
            if rel == self._current:
                self._update_note(rel)
            i = self._index.get(rel)
            slot = self._by_rel.get(rel)
            if i is not None and slot is not None:
                self._put_row(i, self._row(slot))

    # ---- toolbar ------------------------------------------------------
    @rpc
    def sort(self, col):
        """Header click (MainWindow._sort_click)."""
        default = {c: d for c, _t, d in vh.SORT_CFG}
        if col not in default:
            return False
        cur = self._sort
        self._sort = ((col, not cur[1]) if cur and cur[0] == col
                      else (col, default[col]))
        self._refresh_list()
        return True

    @rpc
    def set_change_filter(self, value):
        """The Show: All / Changed / Unchanged picker (persisted with the
        folder's staged changes, as the Tk combobox did)."""
        if value not in vh.CHANGE_FILTER_VALUES:
            return False
        self.video_change_filter_var.set(value)
        self._save_staged()
        return True

    @rpc
    @undoable("Trim / pad")
    def set_trim(self, value):
        """MainWindow._on_video_trim_toggle."""
        self.video_trim_var.set(bool(value))
        self._save_staged()
        self._refresh_list()
        return True

    @rpc
    @undoable("Use my files as-is")
    def set_no_conversion(self, value):
        """MainWindow._video_on_no_conversion_toggle."""
        self.video_no_conversion_var.set(bool(value))
        self._update_trim_enabled()
        self._save_staged()
        if self.video_no_conversion_var.get():
            bad = [w for w in (
                vh.noconv_conflict(self._by_rel.get(rel), rel, p, deep=False)
                for rel, p in sorted(self._assign.items())
                if self._asis_for(rel))
                if w is not None]
            if bad:
                compat.messagebox.showwarning(
                    "Using your files as-is",
                    "These assigned replacements can't be used as-is and "
                    "would be rejected at build time:\n\n%s\n\nUntick \"Use "
                    "my files as-is\" to have them all converted, or "
                    "right-click just these rows and set them to be "
                    "converted." % "\n".join("  • %s" % w for w in bad))
        self._refresh_list()
        return True

    def _on_option_var(self):
        if not self._restoring:
            self._update_trim_enabled()

    def _update_trim_enabled(self):
        """MainWindow._update_video_trim_enabled."""
        any_converted = (not self.video_no_conversion_var.get()
                         or any(v is False for v in self._asis.values()))
        self.set(trim_enabled=bool(any_converted))

    # ==================================================================
    # staged changes (the video part of MainWindow._save_staged_changes)
    # ==================================================================
    def _save_staged(self):
        from ...core import history_log, staged_changes
        assets_dir = self._assets_path()
        if not assets_dir or not os.path.isdir(assets_dir):
            return
        if not (self._scan_dir and vh.same_dir(self._scan_dir, assets_dir)):
            return
        data = staged_changes.load(assets_dir)
        hist = history_log.diff_assignments(
            "video", data.get("video"), self._assign)
        hist.append(history_log.diff_scalar(
            'video  option "Trim / pad to the original clip length"',
            data.get("video_trim"), bool(self.video_trim_var.get())))
        hist.append(history_log.diff_scalar(
            'video  option "Use my files as-is — never re-encode"',
            data.get("video_no_conversion"),
            bool(self.video_no_conversion_var.get())))
        hist.append(history_log.diff_scalar(
            'video  option "Best quality"',
            data.get("video_best_quality"),
            bool(self.video_best_quality_var.get())))
        data["video"] = dict(self._assign)
        data["video_trim"] = bool(self.video_trim_var.get())
        data["video_no_conversion"] = bool(
            self.video_no_conversion_var.get())
        data["video_best_quality"] = bool(self.video_best_quality_var.get())
        data["video_asis_slots"] = {rel: bool(v)
                                    for rel, v in self._asis.items()}
        data["video_length_slots"] = dict(self._length)
        # PAD-446: the slots' random clips, and one history line per slot
        old_var = data.get("video_variants")
        old_var = old_var if isinstance(old_var, dict) else {}
        for rel in sorted(set(old_var) | set(self._variants)):
            o, n = old_var.get(rel) or [], self._variants.get(rel) or []
            if list(o) != list(n):
                hist.append("video  %s  random clips: %s" % (
                    rel, ", ".join(n) if n else "none"))
        if self._variants:
            data["video_variants"] = {rel: list(v) for rel, v
                                      in self._variants.items() if v}
        else:
            data.pop("video_variants", None)
        slots = {rel: v for rel, v in self._color.items() if rel in self._assign}
        if self._color_stock:
            slots.update((rel, True) for rel in self._stock_on
                         if not self._assign.get(rel))
            data["video_color_stock"] = True
        else:
            data.pop("video_color_stock", None)
        if slots:
            data["video_color_slots"] = slots
        else:
            data.pop("video_color_slots", None)
        data["video_change_filter"] = self.video_change_filter_var.get()
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

    # ==================================================================
    # picking a replacement
    # ==================================================================
    @rpc
    @undoable("the pick for %s")
    def choose(self, rel):
        """MainWindow._video_assign_rel: the picker, the as-is gate, the
        pick, its log line."""
        if not rel or rel not in self._by_rel:
            return False
        # The row the picker is for is the row the panes show, whether a
        # file is picked or not (Tk: a Replacement-cell click, a
        # double-click and Enter all select the row, and <<TreeviewSelect>>
        # loads it), so the pick lands in the panes on screen.
        if rel != self._current:
            self._load_track(rel)
        self.stop_all_preview_playback()
        path = self.window.ask_open("video_replacement",
                                    "Choose a replacement for %s" % rel,
                                    vh.PICK_FILETYPES)
        if not path:
            return False
        path = os.path.normpath(path)
        if self._asis_for(rel):
            why = vh.noconv_conflict(self._by_rel.get(rel), rel, path,
                                     self._stock_path(rel))
            if why is not None:
                if compat.messagebox.askyesno(
                        "Using your files as-is",
                        "%s.\n\nAs things stand this file goes onto the card "
                        "exactly as it is, and the machine plays its sound "
                        "over a black picture.\n\nConvert just this clip to "
                        "suit the slot? Every other clip keeps whatever it is "
                        "set to." % why, icon="warning"):
                    self._asis[rel] = False
                    self.log("Replace Video: %s is set to be converted, "
                             "whatever the box below says." % rel, "info")
                else:
                    self.log(
                        "Replace Video: %s — %s; it goes on the card as it "
                        "is. Right-click the row → This clip's conversion to "
                        "change just this one." % (rel, why), "error")
        if rel in self._m_follow:
            # PAD-444: a mode that played its shared clip gets a clip of its own
            if not self._m_materialize(rel):
                return False
            self._m_publish()
        self._assign[rel] = path
        self._save_staged()
        note = vh.conversion_note(self._by_rel.get(rel), rel, path,
                                  self._asis_for(rel),
                                  bool(self.video_trim_var.get()),
                                  self._stock_path(rel))
        self.log("Replace Video: %s ← %s%s"
                 % (rel, os.path.basename(path),
                    ("  (%s)" % note) if note else ""), "info")
        self._update_trim_enabled()
        self._refresh_list()
        if rel == self._current:
            self._reload_rep_pane(rel)
            self._update_note(rel)
        self._reselect([rel])
        return True

    @rpc
    @undoable("the conversion of %s")
    def set_asis(self, rel, value):
        """MainWindow._video_set_asis: this clip's own conversion setting
        (None = follow the box)."""
        if rel not in self._by_rel:
            return False
        if value is None:
            self._asis.pop(rel, None)
            word = ("as-is" if self.video_no_conversion_var.get()
                    else "converted")
            self.log("Replace Video: %s follows the box below again (%s)."
                     % (rel, word), "info")
        else:
            self._asis[rel] = bool(value)
            self.log("Replace Video: %s is set to %s, whatever the box "
                     "below says." % (rel, "go on as-is" if value
                                      else "be converted"), "info")
        self._save_staged()
        self._update_trim_enabled()
        self._probe_conv_async()
        self._refresh_list()
        if rel == self._current:
            self._update_note(rel)
        return True

    @rpc
    @undoable("the length of %s")
    def set_length(self, rel, value):
        """This clip's own length (PAD-215): None follows the Trim / pad
        box, "stock" cuts or pads to the stock clip, "full" keeps the
        replacement's own length, "custom" asks for a number of seconds."""
        slot = self._by_rel.get(rel)
        if slot is None:
            return False
        if value == "custom":
            now = length_seconds(self._length.get(rel)) or slot.duration
            secs = compat.simpledialog.askfloat(
                "Clip length",
                "How many seconds should %s run?\n\nA longer replacement "
                "is cut to this; a shorter one holds its last frame to "
                "fill it." % os.path.basename(rel),
                initialvalue=("%g" % round(now, 2)) if now else "",
                minvalue=0.1, maxvalue=3600)
            if secs is None:
                return False
            value = round(float(secs), 3)
        if value is None:
            self._length.pop(rel, None)
            self.log("Replace Video: %s follows the Trim / pad box again."
                     % rel, "info")
        elif value in (LENGTH_STOCK, LENGTH_FULL) or length_seconds(value):
            self._length[rel] = value
            what = ("%g s" % value if length_seconds(value) else
                    "the stock clip's length" if value == LENGTH_STOCK
                    else "your file's own length")
            self.log("Replace Video: %s will run %s, whatever the Trim / "
                     "pad box says." % (rel, what), "info")
            if self._asis_for(rel):
                self.log("Replace Video: %s goes on as-is, so its length "
                         "can't be changed until it is converted (right-"
                         "click → This clip's conversion)." % rel, "warning")
        else:
            return False
        self._save_staged()
        self._probe_conv_async()
        self._refresh_list()
        if rel == self._current:
            self._update_note(rel)
        return True

    # ---- clearing (the shared Replace-tab clear, kind "video") ---------
    def _applied_rels(self, rels=None):
        """MainWindow._applied_replacement_rels("video", rels)."""
        from ...core import staged_originals
        snaps = staged_originals.snapshot_rels(self._scan_dir or None)
        if rels is None:
            return sorted(rel for rel in snaps if rel in self._by_rel)
        return [rel for rel in dict.fromkeys(rels)
                if rel in snaps and rel in self._by_rel]

    def _targets(self, rels=None):
        """MainWindow._replacement_targets("video", rels)."""
        if rels is None:
            rels = list(self._assign) + self._applied_rels()
        applied = set(self._applied_rels(rels))
        return [rel for rel in dict.fromkeys(rels)
                if self._assign.get(rel) or rel in applied]

    def _put_back(self, rels):
        """MainWindow._put_back_originals("video", rels)."""
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
            "was cleared)" % ("video", rel) for rel in done])
        return done

    def _clear_picks(self, rels, reselect=True):
        """MainWindow._clear_replacement_picks("video", rels)."""
        rels = list(dict.fromkeys(rels))
        picks = [rel for rel in rels if rel in self._assign]
        applied = [] if self._is_running() else self._applied_rels(rels)
        if not picks and not applied:
            return 0
        for rel in picks:
            del self._assign[rel]
            self._color.pop(rel, None)
        restored = self._put_back(applied)
        self._stock_on.difference_update(rels)
        self._save_staged()
        gone = list(dict.fromkeys(picks + restored))
        if len(gone) == 1:
            msg = "%s: cleared replacement for %s" % (_LABEL, gone[0])
            if restored:
                msg += (" and put the card's original file back in the "
                        "project folder")
        else:
            msg = ("%s: cleared %d replacements (the folder's history log "
                   "names each one)" % (_LABEL, len(gone)))
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
                "closed." % (_LABEL, ", ".join(stuck[:3])
                             + (" and %d more" % (len(stuck) - 3)
                                if len(stuck) > 3 else "")), "warning")
        self._update_trim_enabled()
        self._refresh_list()
        if self._current in set(gone):
            self._reload_rep_pane(self._current)
            self._update_note(self._current)
        if reselect:
            alive = [rel for rel in gone
                     if rel in self._index
                     and self._index[rel] in set(self.get("view") or [])]
            if alive:
                self._reselect(alive)
        self._update_clear_all()
        self._m_after_clear(gone)
        return len(gone)

    def _clear_confirm_text(self, targets, question):
        """MainWindow._clear_confirm_text("video", ...)."""
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

    @rpc
    @undoable("clearing %s", "clearing %d replacements")
    def clear(self, rels):
        """The row menu's "Clear replacement(s)": one row, or the selected
        rows (MainWindow._video_clear_selected /
        _clear_selected_replacements)."""
        rels = [r for r in (rels or []) if r in self._by_rel]
        if not rels:
            return 0
        if len(rels) == 1:
            return self._clear_picks(rels)
        targets = self._targets(rels)
        if len(targets) > 1 and not compat.messagebox.askyesno(
                "Clear replacements",
                self._clear_confirm_text(
                    targets, "Clear the replacements for these %d "
                             "slots?" % len(targets))):
            return 0
        return self._clear_picks(rels)

    @rpc
    @undoable("Clear replacements")
    def clear_all(self):
        """The Clear replacements… button (MainWindow._clear_all_
        replacements("video"))."""
        if self._is_running():
            return 0
        targets = self._targets()
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
        return self._clear_picks(targets, reselect=False)

    def _update_clear_all(self):
        """MainWindow._update_clear_all_btn("video")."""
        live = (not self._is_running()) and bool(self._targets()) \
            if self._slots else False
        self.set(can_clear=bool(live))

    # ---- Replace from folder… (MainWindow._replace_from_folder) --------
    @rpc
    @undoable("Replace from folder")
    def replace_from_folder(self):
        from ...core import folder_match
        if self._is_running():
            return False
        slot_rels = [rel for rel in self._by_rel if rel not in self._foreign
                     and rel not in self._m_virtual]
        if not slot_rels:
            compat.messagebox.showinfo(
                "Replace from folder",
                "There are no slots on this tab to match files to yet. Set "
                "the project folder on the Extract tab and Scan first.")
            return False
        folder = self.window.ask_folder(
            "video_replacement", "Choose a folder of replacement files")
        if not folder:
            return False
        folder = os.path.normpath(folder)
        project = self._assets_path()
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
                                          vh.FOLDER_MATCH_EXTS)
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
        to_convert = [rel for rel in found["retyped"] if self._asis_for(rel)]
        if found["retyped"]:
            slot = found["retyped"][0]
            lines.append(
                "%d of them are a different file type from their slot (%s "
                "for %s). That's fine: each is converted to suit its slot, "
                "like any other pick.%s"
                % (len(found["retyped"]),
                   os.path.basename(pairs[slot]), os.path.basename(slot),
                   (" %d of those clips were set to go on as-is, which "
                    "needs the slot's own file type, so just those are set "
                    "to be converted." % len(to_convert))
                   if to_convert else ""))
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
        for rel in to_convert:
            self._asis[rel] = False
        self._save_staged()
        self.log(
            "%s: picked %d replacement(s) by name from %s%s."
            % (_LABEL, n, folder,
               (" (%d of a different file type, converted to suit their "
                "slot)" % len(found["retyped"])) if found["retyped"] else ""),
            "info")
        if to_convert:
            self.log(
                "%s: %s set to be converted, whatever the box below says — "
                "a clip that goes on as-is has to be the slot's own file type."
                % (_LABEL, vh.folder_match_list(to_convert)), "info")
        if found["unmatched"]:
            self.log("%s: %d file(s) named like no slot on this tab: %s"
                     % (_LABEL, len(found["unmatched"]),
                        vh.folder_match_list(found["unmatched"])), "warning")
        if found["ambiguous"]:
            self.log(
                "%s: %d file(s) named like more than one slot, so left out "
                "(put each in a subfolder named like its slot's to say "
                "which): %s"
                % (_LABEL, len(found["ambiguous"]),
                   vh.folder_match_list(found["ambiguous"])), "warning")
        if found["duplicates"]:
            self.log(
                "%s: %d file(s) left out because another file in the folder "
                "has the same name: %s"
                % (_LABEL, len(found["duplicates"]),
                   vh.folder_match_list(found["duplicates"])), "warning")
        if fingerprinted:
            self.log(
                "%s: %d of the left-out files are scene pictures or glyphs "
                "named for a different card's contents; \"Transfer Mods to "
                "New Version\" carries those over by content."
                % (_LABEL, len(fingerprinted)), "warning")
        self._update_trim_enabled()
        self._refresh_list()
        if self._current in pairs:
            self._reload_rep_pane(self._current)
            self._update_note(self._current)
        self._update_clear_all()
        return True

    # ------------------------------------------------------------------
    # Save settings to a file / Load settings from a file (PAD-300)
    # ------------------------------------------------------------------
    def _settings_dir(self):
        folder = self._assets_path()
        if self._scan_dir and folder and vh.same_dir(self._scan_dir, folder):
            return self._scan_dir
        return ""

    @rpc
    def settings_save(self):
        """More > Save settings to a file...: this tab's picks and options
        (not the files) in one small file.  Returns its path, or None."""
        from .. import tab_settings_ui
        folder = self._settings_dir()
        return tab_settings_ui.save_media(self, "video", folder, bool(folder),
                                          self._save_staged_changes)

    @rpc
    def settings_load(self, path=None):
        """More > Load settings from a file...: merge a saved settings file
        into this project and re-scan."""
        from .. import tab_settings_ui
        return tab_settings_ui.load_media(
            self, "video", self._settings_dir(),
            set(self._by_rel) - set(self._m_virtual),
            self._is_running(), self._save_staged_changes,
            self._scan_async, path)

    # ---- Export CSV (MainWindow._video_export_csv) ----------------------
    @rpc
    def export_csv(self):
        if not self._slots:
            compat.messagebox.showinfo("Export CSV",
                                       "Scan an assets folder first — the "
                                       "video table is empty.")
            return False
        path = self.window.ask_save(
            "video_csv", "Save video table as CSV",
            initialfile="video_slots.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            defaultextension=".csv")
        if not path:
            return False
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Original Video", "Length", "Resolution",
                            "Format", "Audio", "Replacement", "Convert",
                            "Changed On Disk", "Color Profile"])
                for s in sorted(self._slots, key=lambda q: q.rel_path):
                    rel = s.rel_path
                    rep = self._assign.get(rel, "")
                    w.writerow([
                        rel, s.duration_str(), s.resolution_str(),
                        vh.fmt_cell(self._mfr_key(), s),
                        s.info.audio_summary() if s.info else "",
                        rep,
                        self._conv_cache.get(self._conv_key(rel, rep), "")
                        if rep else "",
                        "yes" if rel in self._changed else "",
                        "yes" if self._color_state(rel) else "",
                    ])
        except OSError as e:
            compat.messagebox.showerror("Export CSV",
                                        "Couldn't write the CSV:\n%s" % e)
            return False
        self.log("Video table exported: %d slot(s) → %s"
                 % (len(self._slots), os.path.normpath(path)), "success")
        return True

    # ==================================================================
    # the row menu
    # ==================================================================
    @rpc
    def row_menu(self, rels):
        """What the right-click menu offers for *rels* (one row, or a
        multi-row selection: MainWindow._video_on_tree_right /
        _add_multi_row_clear)."""
        rows = [rel for rel in (rels or []) if rel in self._by_rel]
        if len(rows) >= 2:
            return {"multi": True, "rows": len(rows),
                    "targets": len(self._targets(rows))}
        if not rows:
            return None
        rel = rows[0]
        flag = self._asis.get(rel)
        return {
            "multi": False, "rel": rel,
            "has_pick": bool(self._assign.get(rel)),
            "open_rep": bool(self._open_target(rel, "rep")),
            "can_clear": bool(self._targets([rel])),
            "stern": self._mfr_key() == "stern",
            "scenes": self._scene_browser() is not None,
            "asis": {None: "box", True: "asis", False: "convert"}[flag],
            "follow": ("as-is" if self.video_no_conversion_var.get()
                       else "convert"),
            "length": _length_key(self._length.get(rel)),
            "length_secs": length_seconds(self._length.get(rel)),
            "length_follow": ("stock length" if self.video_trim_var.get()
                              else "full length"),
            "color": (None if (self._color_state(rel) is None
                               or not self._assign.get(rel)) else
                      {None: "box", True: "on", False: "off"}[
                          self._color.get(rel)]),
            "color_follow": "corrected" if self._color_all else "own colors",
            "reveal": vh.reveal_menu_label(),
            "variants": self._variant_menu(rel),
            "partition": bool(self.window.tab_visible("Partition Explorer")
                              and getattr(self.window, "find_in_partition",
                                          None) is not None),
            # PAD-444: a mode's own clip an earlier build made plays the shared one again
            "back": (self._m_preview(rel) or {}).get("back") or "",
        }

    # -- random clips (PAD-446) ---------------------------------------------
    def _variant_menu(self, rel):
        """The row menu's "Random clips" part: ``{why, n, max, files}``, or
        None where the plugin offers no random clips."""
        offer = self._var_offer
        files = self._variants.get(rel) or []
        if offer is None and not files:
            return None
        offer = offer or {}
        why = offer.get("why") or (offer.get("slots") or {}).get(rel, "")
        if not why and rel in self._m_follow and not self._assign.get(rel):
            # PAD-444: a mode's row that plays another mode's clip has no clip of its own
            # to vary until it is given one; the clip it plays varies in that mode's row
            why = ("this row plays the same clip as %s's; give it a replacement first, or "
                   "add the random clips in that row" % self._m_label(self._m_follow[rel]))
        elif rel in self._m_copy and rel not in ((self._m_clips.name_of if self._m_clips
                                                   else {}) or {}):
            why = ("this is %s's own clip, new to the card: random clips go on a clip the card "
                   "already has, so build it onto the card first"
                   % self._m_label(self._m_copy[rel]["mode"]))
        return {"why": why or "", "n": len(files),
                "max": int(offer.get("max") or 0),
                "files": [{"i": i, "name": os.path.basename(f)}
                          for i, f in enumerate(files)]}

    def _variants_words(self, rel):
        """What the row and the preview say of a slot's random clips, or
        "" for a slot that has none."""
        files = self._variants.get(rel) or []
        if not files:
            return ""
        own = (os.path.basename(self._assign[rel]) if self._assign.get(rel)
               else "the game's own clip")
        return ("Plays one of %d clips at random each time, never the same "
                "one twice in a row: %s, %s." % (
                    1 + len(files), own,
                    ", ".join(os.path.basename(f) for f in files)))

    def _variants_changed(self, rel):
        self._save_staged()
        self._refresh_list()
        if rel == self._current:
            self._update_note(rel)
        self._reselect([rel])

    @rpc
    @undoable("the random clips of %s")
    def add_variants(self, rel):
        """PAD-446: more clips the game may play in this slot's place, one
        of them at random each time (the file picker takes several)."""
        menu = self._variant_menu(rel) if rel in self._by_rel else None
        if not menu or menu["why"]:
            return False
        files = list(self._variants.get(rel) or [])
        room = menu["max"] - len(files)
        if room <= 0:
            self.log("Replace Video: %s already has %d random clips, the most "
                     "a slot can have." % (rel, len(files)), "warning")
            return False
        if rel != self._current:
            self._load_track(rel)
        self.stop_all_preview_playback()
        picked = self.window.ask_open(
            "video_replacement",
            "Choose clips the game can play at random in place of %s" % rel,
            vh.PICK_FILETYPES, multiple=True)
        if isinstance(picked, str):
            picked = [picked] if picked else []
        picked = [os.path.normpath(p) for p in (picked or ()) if p]
        if not picked:
            return False
        if len(picked) > room:
            self.log("Replace Video: %s can take %d more random clip(s); the "
                     "first %d were added." % (rel, room, room), "warning")
            picked = picked[:room]
        files += picked
        self._variants[rel] = files
        self.log("Replace Video: %s ← %s, played at random (%d clips: the "
                 "slot's own and %d more)."
                 % (rel, ", ".join(os.path.basename(p) for p in picked),
                    1 + len(files), len(files)), "info")
        self._variants_changed(rel)
        return True

    @rpc
    def variants_why(self, rel):
        """PAD-446: why this slot cannot play other clips at random."""
        menu = self._variant_menu(rel)
        if not menu or not menu["why"]:
            return False
        compat.messagebox.showinfo("Random clips", menu["why"])
        return True

    @rpc
    @undoable("the random clips of %s")
    def remove_variant(self, rel, index):
        """PAD-446: take one random clip off the slot."""
        files = list(self._variants.get(rel) or [])
        try:
            gone = files.pop(int(index))
        except (TypeError, ValueError, IndexError):
            return False
        if files:
            self._variants[rel] = files
        else:
            self._variants.pop(rel, None)
        self.log("Replace Video: %s no longer plays %s at random."
                 % (rel, os.path.basename(gone)), "info")
        self._variants_changed(rel)
        return True

    @rpc
    @undoable("the random clips of %s")
    def clear_variants(self, rel):
        """PAD-446: the slot plays its one clip again."""
        if not self._variants.pop(rel, None):
            return False
        self.log("Replace Video: %s plays one clip again (its random clips "
                 "were taken off)." % rel, "info")
        self._variants_changed(rel)
        return True

    def _scene_browser(self):
        for name in ("_open_scene_browser", "open_scene_browser"):
            try:
                fn = getattr(self.window, name)
            except AttributeError:
                continue
            if callable(fn):
                return fn
        return None

    @rpc
    def scene_contents(self, rel):
        """"Show scene contents…" (Stern): the Scenes window on this clip."""
        fn = self._scene_browser()
        if fn is None or rel not in self._by_rel:
            return False
        fn(preselect_video=rel)
        return True

    def _open_target(self, rel, which):
        """The file "Open in default app" hands the OS (PAD-208): the
        slot's own clip, or its assigned replacement when that is a file."""
        slot = self._by_rel.get(rel)
        if slot is None:
            return None
        if which == "orig":
            return slot.abs_path
        rep = self._assign.get(rel)
        return rep if isinstance(rep, str) and os.path.isfile(rep) else None

    @rpc
    def open_default(self, rel, which="orig"):
        """"Open in default app": the clip in the OS's own player."""
        path = self._open_target(rel, which)
        if path is None:
            return False
        from ..shellx_common import open_in_default_app_or_warn
        return open_in_default_app_or_warn(path)

    @rpc
    def reveal(self, rel):
        slot = self._by_rel.get(rel)
        if slot is None:
            return False
        err = vh.reveal_in_file_manager(slot.abs_path)
        if err:
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s"
                % (os.path.abspath(slot.abs_path), err))
            return False
        return True

    @rpc
    def find_in_partition(self, rel):
        """"Find in Partition Explorer" (the Partition Explorer's own
        find, handed this clip)."""
        try:
            fn = self.window.find_in_partition
        except AttributeError:
            return False
        fn("video", rel, self._scan_dir)
        return True

    @rpc
    def open_project_folder(self):
        """The project-folder link (MainWindow._open_folder_link)."""
        path = self._assets_path()
        if not path:
            compat.messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return False
        if not os.path.exists(path):
            compat.messagebox.showinfo(
                "Open folder", "This folder doesn't exist yet:\n%s" % path)
            return False
        err = vh.reveal_in_file_manager(path)
        if err:
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, err))
        return True

    @rpc
    def target_spec(self, rel):
        """"What this slot needs…" (MainWindow._video_show_target_spec):
        the data the page's dialog shows, or None after the not-probed
        message."""
        from ...core import video as _video
        slot = self._by_rel.get(rel)
        if slot is None:
            return None
        info = slot.info
        if info is None:
            compat.messagebox.showinfo(
                "What this slot needs",
                "This clip hasn't been probed yet — its Length / Resolution / "
                "Format cells still read \"…\".\n\nGive the scan a moment and "
                "try again. (Without ffmpeg on this machine the app can't "
                "read the clip's format at all.)")
            return None
        spec = _video.dropin_spec(info, slot.ext) or []
        cmd = _video.dropin_ffmpeg_command(info, slot.ext) or ""
        return {"rel": rel, "spec": [list(p) for p in spec], "cmd": cmd,
                "silent": not info.has_audio}

    @rpc
    def copied_command(self, rel):
        self.log("Copied the ffmpeg command for %s." % rel, "info")
        return True

    # ==================================================================
    # the preview panes
    # ==================================================================
    @staticmethod
    def _pane(side, title, path=None, label="", hint=""):
        return {"side": side, "title": title, "path": path or None,
                "label": label, "hint": hint, "facts": None,
                "poster": None, "poster_note": "", "proxy": None,
                "proxy_err": "", "seq": 0}

    def _empty_preview(self):
        return {"rel": None,
                "orig": self._pane("orig", "Original"),
                "rep": self._pane("rep", "Replacement",
                                  hint="no replacement assigned"),
                "note": None, "can_clear": False, "has_pick": False}

    def _clear_preview(self):
        """MainWindow._video_clear_preview."""
        self._current = None
        self._pane_seq += 1
        self.set(preview=self._empty_preview())
        self._cmp_reset()

    @rpc
    def select(self, rel, autoplay=None):
        """A row was selected (MainWindow._video_preview_selected; the page
        debounces like the Tk 250 ms job): a different row loads into both
        panes, resuming playback on *autoplay*'s pane; the row already on
        show is left alone, so a playing clip keeps playing."""
        if rel not in self._by_rel:
            return False
        if rel == self._current:
            return True
        self._load_track(rel, autoplay)
        return True

    @rpc
    def activate_pane(self, rel, side):
        """MainWindow._video_activate_pane: ▶ on an empty pane loads the
        selected row, then plays the pane that asked."""
        if rel not in self._by_rel:
            return False
        self._load_track(rel, side if side in ("orig", "rep") else None)
        return True

    @rpc
    def play(self, rel, side="orig"):
        """"▶ Play original" / "▶ Play replacement" (and a row's ▶)."""
        if side == "rep" and not self._assign.get(rel):
            compat.messagebox.showinfo(
                "No Replacement", "Assign a replacement to this slot first.")
            return False
        if rel not in self._by_rel:
            compat.messagebox.showinfo("No Slot Selected",
                                       "Select a clip to preview.")
            return False
        self._load_track(rel, side)
        return True

    def _orig_pane(self, rel):
        """The Original pane of *rel*: the stock clip (its snapshot when a
        build already changed the slot on disk)."""
        from ...core import staged_originals
        slot = self._by_rel.get(rel)
        opath = slot.abs_path if slot else None
        snap_used = False
        changed = self._slot_changed_on_disk(rel)
        if changed:
            snap = staged_originals.snapshot_path(self._scan_dir, rel)
            if snap:
                opath = snap
                snap_used = True
        title = ("Current file (already modified)"
                 if changed and not snap_used
                 else "Original (stock)" if snap_used else "Original")
        self._pane_seq += 1
        if opath and os.path.isfile(opath):
            orig = self._pane("orig", title, opath,
                              label=os.path.basename(opath))
        else:
            orig = self._pane("orig", title)
        orig["seq"] = self._pane_seq
        return orig

    def _load_track(self, rel, autoplay=None):
        """MainWindow._video_load_track."""
        if rel not in self._by_rel:
            return
        self._current = rel
        orig = self._orig_pane(rel)
        pv = dict(self.get("preview") or self._empty_preview())
        pv["rel"] = rel
        pv["orig"] = orig
        pv["rep"] = self._rep_pane(rel)
        pv.update(self._pick_state(rel))
        self.set(preview=pv)
        for pane in (pv["orig"], pv["rep"]):
            self._load_pane_async(pane)
        if autoplay in ("orig", "rep"):
            self._play_seq += 1
            self.set(play={"side": autoplay, "seq": self._play_seq})
        self._update_note(rel)
        self.publish_look()

    def _pick_state(self, rel):
        return {"can_clear": bool(rel and self._targets([rel])),
                "has_pick": bool(rel and self._assign.get(rel))}

    def _stock_coloured(self, rel):
        """A game's own clip with its color profile attached (Advanced,
        PAD-336): the card gets its original through the profile."""
        return bool(rel and not self._assign.get(rel)
                    and self._color_state(rel))

    def _rep_pane(self, rel):
        """MainWindow._video_load_rep_pane.  A game's own clip with its
        color profile attached has no replacement: this player shows its
        original through the profile, as the card will get it (PAD-448:
        nothing on the tab showed the profile on such a clip)."""
        from ...core import staged_originals
        if self._stock_coloured(rel):
            pane = self._orig_pane(rel)
            pane.update(side="rep", title=STOCK_COLOURED)
            return pane
        self._pane_seq += 1
        rpath = self._assign.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            pane = self._pane("rep", "Replacement", rpath,
                              label=os.path.basename(rpath))
        elif rel and staged_originals.snapshot_path(self._scan_dir, rel):
            slot = self._by_rel.get(rel)
            cur = slot.abs_path if slot else None
            if cur and os.path.isfile(cur):
                pane = self._pane(
                    "rep", "Replacement (your file)", cur,
                    label=self._remembered_rep_name(rel)
                    or os.path.basename(cur))
            else:
                pane = self._pane("rep", "Replacement", hint=self.
                                  _rep_pane_empty_text(
                                      rel, "no replacement assigned"))
        else:
            pane = self._pane("rep", "Replacement",
                              hint=self._rep_pane_empty_text(
                                  rel, "no replacement assigned"))
        pane["seq"] = self._pane_seq
        return pane

    def _reload_rep_pane(self, rel):
        if rel != self._current:
            return
        pv = dict(self.get("preview") or self._empty_preview())
        old = pv.get("rep") or {}
        new = self._rep_pane(rel)
        if old.get("path") == new.get("path") and old.get("path"):
            # same file: keep what was already worked out for it
            for k in ("facts", "poster", "poster_note", "proxy",
                      "proxy_err"):
                new[k] = old.get(k)
        pv["rep"] = new
        pv.update(self._pick_state(rel))
        self.set(preview=pv)
        if new.get("facts") is None:
            self._load_pane_async(new)

    def _load_pane_async(self, pane):
        """_VideoPreviewPane.load: probe the clip and render its
        representative still on a worker, then hand both to the page."""
        path, side, seq = pane.get("path"), pane["side"], pane["seq"]
        if path:
            self._probe_async(path, lambda fields: self.ctx.loop.post(
                self._pane_update, side, seq, fields))

    @staticmethod
    def _probe_async(path, post):
        """Probe *path* and render its representative still on a worker,
        handing each to *post(fields)* (called on the worker)."""
        def _work():
            try:
                info, facts = vh.media_facts(path)
            except Exception:                               # noqa: BLE001
                info, facts = None, {"dur": 0.0}
            post({"facts": facts})
            try:
                poster, note = vh.representative_poster(
                    path, info, facts.get("dur") or 0.0)
            except Exception as e:                          # noqa: BLE001
                poster, note = None, "Couldn't show this frame: %s" % e
            post({"poster": poster, "poster_note": note})

        threading.Thread(target=_work, daemon=True,
                         name="video-pane").start()

    def _pane_update(self, side, seq, fields):
        pv = self.get("preview") or {}
        pane = pv.get(side)
        if not pane or pane.get("seq") != seq:
            return
        pane = dict(pane)
        pane.update(fields)
        pv = dict(pv)
        pv[side] = pane
        self.set(preview=pv)

    @rpc
    def make_proxy(self, side, seq, fmt="mp4"):
        """The page's engine can't play this pane's clip as it is: make a
        copy it can (video_helpers.browser_proxy) and hand it over."""
        pv = self.get("preview") or {}
        pane = pv.get(side)
        if not pane or pane.get("seq") != seq or not pane.get("path"):
            return False
        if pane.get("proxy") or pane.get("proxy_busy"):
            return True
        self._pane_update(side, seq, {"proxy_busy": True, "proxy_err": ""})
        self._proxy_async(pane["path"], fmt, lambda fields: self.ctx.loop.post(
            self._pane_update, side, seq, fields))
        return True

    @staticmethod
    def _proxy_async(path, fmt, post):
        """Make a copy of *path* the page's engine can play, on a worker;
        *post(fields)* gets ``proxy`` / ``proxy_err``."""
        def _work():
            try:
                out, err = vh.browser_proxy(path, fmt), ""
            except Exception as e:                          # noqa: BLE001
                out, err = None, str(e) or e.__class__.__name__
            post({"proxy": out, "proxy_err": err, "proxy_busy": False})

        threading.Thread(target=_work, daemon=True,
                         name="video-proxy").start()

    # ==================================================================
    # Compare (PAD-440, DragonRR): several clips side by side, big, each
    # drawn through its own colors beside the Color profiles bar, so a
    # profile picked or a slider moved for one is seen against the others
    # ==================================================================
    def _cmp_sides(self, rel):
        """What a Compare player can show of *rel*: ``[[side, label]]``."""
        if self._stock_coloured(rel):
            return [["orig", "Original"], ["rep", STOCK_COLOURED]]
        if self._rep_pane(rel).get("path"):
            return [["orig", "Original"], ["rep", "Replacement"]]
        return [["orig", "Original"]]

    def _cmp_pane(self, rel, side):
        return self._rep_pane(rel) if side == "rep" else self._orig_pane(rel)

    def _cmp_tile(self, tid):
        return next((t for t in self._cmp if t["id"] == tid), None)

    def _cmp_add(self, rel, side):
        self._cmp_ids += 1
        tile = {"id": self._cmp_ids, "rel": rel, "side": side,
                "sides": self._cmp_sides(rel),
                "pane": self._cmp_pane(rel, side), "look": [], "lut": None}
        self._cmp.append(tile)
        self._cmp_load(tile)

    def _cmp_load(self, tile):
        pane = tile["pane"]
        if pane.get("path"):
            tid, seq = tile["id"], pane["seq"]
            self._probe_async(pane["path"], lambda fields: self.ctx.loop.post(
                self._cmp_update, tid, seq, fields))

    def _cmp_update(self, tid, seq, fields):
        tile = self._cmp_tile(tid)
        if tile is None or tile["pane"].get("seq") != seq:
            return
        tile["pane"] = dict(tile["pane"], **fields)
        self._cmp_publish()

    def _cmp_steps(self):
        """Each tile's colour steps: the players' (publish_look), worked
        out for the tile's own clip and side."""
        look = self.get("look") or {}
        folder = self._assets_path()
        if not (look.get("offered") and look.get("on") and folder
                and os.path.isdir(folder)):
            for t in self._cmp:
                t["look"] = []
                t["lut"] = None
            return
        from ...core import colour_profile
        sw, own, done = self._lsw, self._own_colours(), {}
        for t in self._cmp:
            rel = t["rel"]
            if rel not in done:
                try:
                    kw = dict(overlay_on=sw["overlay"], files_on=sw["files"],
                              screen_on=sw["screen"], rel=rel)
                    switch = self._color_state(rel)
                    done[rel] = (
                        colour_profile.video_look(folder, switch, own, **kw),
                        colour_profile.video_look_exact(folder, switch, own,
                                                        **kw))
                except Exception:                       # noqa: BLE001
                    log.exception("video compare look")
                    done[rel] = ({}, {})
            steps, exact = done[rel]
            t["look"] = steps.get(t["side"]) or []
            t["lut"] = self._lut(exact.get(t["side"]), t.get("lut"))

    def _cmp_publish(self):
        st = {"open": self._cmp_open, "max": COMPARE_MAX, "tiles": [
            {k: t[k] for k in ("id", "rel", "side", "sides", "pane", "look",
                               "lut")}
            for t in self._cmp] if self._cmp_open else []}
        if st != self.get("compare"):
            self.set(compare=st)

    def _cmp_sync(self):
        """The list changed (a pick, a clear, a switch, a scan): each tile
        follows its clip, and a clip no longer listed leaves."""
        if not self._cmp_open:
            return
        keep = []
        moved = False
        for t in self._cmp:
            rel = t["rel"]
            if rel not in self._by_rel:
                moved = True
                continue
            sides = self._cmp_sides(rel)
            side = t["side"] if any(k == t["side"] for k, _l in sides) \
                else "orig"
            if len(t["sides"]) == 1 and len(sides) > 1:
                # PAD-448: a profile just attached to a game's own clip (or
                # a replacement just picked) is what the player was put up
                # to show
                side = sides[-1][0]
            pane = self._cmp_pane(rel, side)
            moved = moved or side != t["side"] or sides != t["sides"]
            t["sides"] = sides
            t["side"] = side
            if pane.get("path") != t["pane"].get("path"):
                moved = True
                t["pane"] = pane
                self._cmp_load(t)
            else:
                t["pane"] = dict(t["pane"], **{k: pane[k] for k in (
                    "side", "title", "label", "hint")})
            keep.append(t)
        self._cmp = keep
        if not keep:
            self._cmp_open = False
        if moved:
            self._cmp_steps()
        self._cmp_publish()

    def _cmp_reset(self):
        self._cmp_open = False
        self._cmp = []
        self._cmp_publish()

    @rpc
    def compare_open(self, rels):
        """Compare: the clips selected, side by side.  One clip: its
        Original beside its Replacement.  Several: each one's Replacement
        where it has one, else its Original, the first COMPARE_MAX of them.
        Returns how many players it opened with."""
        seen = set()
        rels = [r for r in (rels or []) if r in self._by_rel
                and not (r in seen or seen.add(r))]
        if not rels:
            return 0
        if len(rels) > COMPARE_MAX:
            self.toast("Compare shows %d clips at a time: the first %d "
                       "selected are in it." % (COMPARE_MAX, COMPARE_MAX))
            rels = rels[:COMPARE_MAX]
        sides = self._cmp_sides(rels[0])
        if len(rels) == 1 and len(sides) > 1:
            want = [(rels[0], "orig"), (rels[0], "rep")]
        else:
            want = [(r, self._cmp_sides(r)[-1][0]) for r in rels]
        self._cmp = []
        for rel, side in want:
            self._cmp_add(rel, side)
        self._cmp_open = True
        self.stop_all_preview_playback()
        self._cmp_steps()
        self._cmp_publish()
        return len(self._cmp)

    @rpc
    def compare_close(self):
        if not self._cmp_open:
            return False
        self._cmp_reset()
        return True

    @rpc
    def compare_side(self, tid, side):
        """One player shows the other side of its clip (Original /
        Replacement)."""
        tile = self._cmp_tile(tid)
        if tile is None or side == tile["side"] or not any(
                k == side for k, _l in tile["sides"]):
            return False
        tile["side"] = side
        tile["pane"] = self._cmp_pane(tile["rel"], side)
        self._cmp_load(tile)
        self._cmp_steps()
        self._cmp_publish()
        return True

    @rpc
    def compare_remove(self, tid):
        """A player's ×: the clip leaves Compare (the last one stays)."""
        tile = self._cmp_tile(tid)
        if tile is None or len(self._cmp) < 2:
            return False
        self._cmp.remove(tile)
        self._cmp_publish()
        return True

    @rpc
    def compare_make_proxy(self, tid, seq, fmt="mp4"):
        """make_proxy for a Compare player."""
        tile = self._cmp_tile(tid)
        pane = tile["pane"] if tile else {}
        if pane.get("seq") != seq or not pane.get("path"):
            return False
        if pane.get("proxy") or pane.get("proxy_busy"):
            return True
        self._cmp_update(tid, seq, {"proxy_busy": True, "proxy_err": ""})
        self._proxy_async(pane["path"], fmt, lambda fields: self.ctx.loop.post(
            self._cmp_update, tid, seq, fields))
        return True

    def _update_note(self, rel=None):
        """MainWindow._video_update_preview_note: the big callout under the
        panes (nothing here probes a file)."""
        if rel is None:
            rel = self._current
        slot = self._by_rel.get(rel) if rel else None
        note = None
        if slot is not None:
            why = vh.slot_unplayable(self._mfr_key(), slot)
            rep = self._assign.get(rel)
            mode = self._conv_cached(rel, rep) if rep else ""
            if why:
                if mode in vh.CONV_GOOD:
                    note = {"kind": "warn", "text": (
                        "⚠  The clip in this slot right now %s — the "
                        "Format and Audio columns describe that clip "
                        "until you build. Your replacement goes on at "
                        "the next build and fixes it." % why)}
                else:
                    note = {"kind": "err", "text": (
                        "⚠  WRONG FORMAT — the clip in this slot %s. On "
                        "the machine it will play its sound over a black "
                        "picture. Assign a good replacement (or "
                        "right-click → revert the slot) before building."
                        % why)}
            elif rep and mode in (vh.CONV_REJECT, vh.CONV_ASIS_NOISY):
                if mode == vh.CONV_ASIS_NOISY:
                    note = {"kind": "warn", "text": (
                        "⚠  %s brings its own audio track and this "
                        "slot's clip has none — the machine will play it "
                        "over the game's sound." % os.path.basename(rep))}
                else:
                    conflict = vh.noconv_conflict(slot, rel, rep, deep=False)
                    note = {"kind": "err", "text": (
                        "✗  WRONG FORMAT — %s. As-is it will play its "
                        "sound over a black picture on the machine. "
                        "Right-click the row → This clip's conversion → "
                        "Always convert this clip, untick \"Use my files "
                        "as-is\" for the lot, or pick a game-ready file."
                        % (conflict or ("%s can't play on the machine "
                                        "as it is" % os.path.basename(rep))))}
            if note is None and self._variants.get(rel):
                # PAD-446: the slot's random clips, where nothing is wrong
                note = {"kind": "info", "text": self._variants_words(rel)}
        pv = self.get("preview") or {}
        modes = self._m_preview(rel)
        if pv.get("note") != note or pv.get("modes") != modes:
            pv = dict(pv)
            pv["note"] = note
            pv["modes"] = modes
            self.set(preview=pv)

    def _reselect(self, rels):
        self._sel_seq += 1
        self.set(select={"rels": list(rels), "seq": self._sel_seq})

    # ==================================================================
    # "Check card…" (gui/video_quality_dialog.py)
    # ==================================================================
    def _quality_state(self, open_=True, **kw):
        st = {"open": bool(open_), "card": self._q_card if hasattr(
            self, "_q_card") else "", "busy": False,
              "summary": "Pick a card image and press Check.",
              "rows": [], "only_bad": True, "can_copy": False}
        st.update(kw)
        return st

    def _quality_default_card(self):
        """MainWindow._video_quality_default_card."""
        from ...core.extract_source import read_extract_source
        rec = read_extract_source(self._assets_path())
        recorded = (rec or {}).get("input_path") or ""
        if recorded and os.path.isfile(recorded):
            return recorded
        try:
            picked = (self.window.extract_input_var.get() or "").strip()
        except Exception:                                   # noqa: BLE001
            picked = ""
        return picked if os.path.isfile(picked) else ""

    def _quality_set(self, **kw):
        q = dict(self.get("quality") or self._quality_state())
        q.update(kw)
        self.set(quality=q)

    @rpc
    def quality_open(self):
        """MainWindow._open_video_quality_report: open the report (an open
        one keeps its results)."""
        if self.mfr is None:
            return False
        q = self.get("quality") or {}
        if q.get("rows") or q.get("busy"):
            self._quality_set(open=True)
            return True
        self._q_card = self._quality_default_card()
        self._q_clips = []
        self.set(quality=self._quality_state(open_=True, card=self._q_card))
        return True

    @rpc
    def quality_close(self):
        """VideoQualityDialog._close (Close, the window's ×, Escape): stop a
        running check and drop the report, so the next Check card… starts
        a fresh one.  A click elsewhere on the tab never closes it: it is
        a non-modal window, as the Tk Toplevel was."""
        self._q_cancel = True
        self._q_scan += 1
        self._q_clips = []
        self.set(quality=self._quality_state(open_=False))
        return True

    @rpc
    def quality_set_card(self, path):
        self._q_card = path or ""
        self._quality_set(card=self._q_card)
        return True

    @rpc
    def quality_browse(self):
        """VideoQualityDialog._browse."""
        card = (self.get("quality") or {}).get("card") or ""
        path = self.window.ask_open(
            "video_quality_card", "Pick a card image to check",
            [("Card images", "*.raw *.img *.bin"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(card))
        if path:
            self._q_card = os.path.normpath(path)
            self._quality_set(card=self._q_card)
        return path

    @rpc
    def quality_check(self, path=None):
        """VideoQualityDialog._start: Check, or Stop while one runs."""
        q = self.get("quality") or {}
        if q.get("busy"):
            self._q_cancel = True
            self._quality_set(summary="Stopping…")
            return True
        if path is not None:
            self._q_card = path
        path = (self._q_card or q.get("card") or "").strip().strip('"')
        if not os.path.isfile(path):
            compat.messagebox.showwarning(
                "Pick a card image",
                "Pick the .raw / .img card image you want to check.")
            return False
        self._q_scan += 1
        scan_id = self._q_scan
        self._q_cancel = False
        self._q_clips = []
        mfr = self.mfr
        self._quality_set(card=path, busy=True, rows=[], can_copy=False,
                          summary="Reading %s…" % os.path.basename(path))

        def on_log(msg, level="info"):
            self.ctx.loop.post(self.log, msg, level)

        def work():
            clips, err = [], ""
            try:
                clips = mfr.video_quality(
                    path, log=on_log, progress=None,
                    cancel=lambda: self._q_cancel) or []
            except Exception as e:                          # noqa: BLE001
                err = str(e) or e.__class__.__name__
            self.ctx.loop.post(self._quality_done, scan_id, clips, err)

        threading.Thread(target=work, daemon=True,
                         name="video-quality").start()
        return True

    def _quality_done(self, scan_id, clips, err):
        """VideoQualityDialog._poll's landing."""
        from ...core import video_quality
        if scan_id != self._q_scan:
            return
        if err:
            self._quality_set(busy=False, summary="Could not read that card "
                                                  "image: %s" % err)
            return
        if self._q_cancel and not clips:
            self._quality_set(busy=False, summary="Stopped.")
            return
        self._q_clips = video_quality.sort_worst_first(clips)
        self._quality_set(
            busy=False,
            summary=" ".join(video_quality.summary_lines(self._q_clips)),
            can_copy=bool(self._q_clips))
        self._quality_repaint()

    def _quality_repaint(self):
        """VideoQualityDialog._repaint."""
        only_bad = bool((self.get("quality") or {}).get("only_bad", True))
        rows = []
        for c in self._q_clips:
            if only_bad and c.verdict == "ok":
                continue
            rows.append({"name": c.name, "len": c.length_str(),
                         "res": c.resolution_str(), "rate": c.bitrate_str(),
                         "quality": c.quality_str(), "verdict": c.verdict})
        if self._q_clips and not rows:
            rows.append({"name": "Nothing below the bar on this card.",
                         "len": "", "res": "", "rate": "", "quality": "",
                         "verdict": "unknown"})
        self._quality_set(rows=rows)

    @rpc
    def quality_only_bad(self, value):
        self._quality_set(only_bad=bool(value))
        self._quality_repaint()
        return True

    @rpc
    def quality_report_text(self):
        """VideoQualityDialog._copy: the text the page puts on the
        clipboard."""
        from ...core import video_quality
        if not self._q_clips:
            return ""
        title = "Video quality — %s" % os.path.basename(
            (self._q_card or "").strip())
        return video_quality.as_text(self._q_clips, title=title)

    @rpc
    def quality_copied(self):
        self.log("Copied the video-quality report (%d clip(s)) to the "
                 "clipboard." % len(self._q_clips), "info")
        return True

    # ==================================================================
    # column widths (MainWindow._persist_tree_columns "video": the ones
    # the user drags are kept in settings.json and stop fitting to their
    # content; the page fits the others, as _autosize_tree_columns did)
    # ==================================================================
    _WIDTHS_KEY = "video_web"
    _WIDTH_COLS = ("rel", "len", "res", "fmt", "aud", "rep", "col", "conv")

    def _all_widths(self):
        s = getattr(self.app, "_settings", None) if self.app else None
        widths = (s or {}).get("column_widths")
        if not isinstance(widths, dict):
            widths = dict(self.window.cb.get("initial_column_widths") or {})
        return widths

    def _saved_widths(self):
        try:
            got = self._all_widths().get(self._WIDTHS_KEY) or {}
        except Exception:                                   # noqa: BLE001
            got = {}
        if not isinstance(got, dict):
            return {}
        return {k: int(v) for k, v in got.items()
                if k in self._WIDTH_COLS and isinstance(v, (int, float))
                and not isinstance(v, bool) and v > 0}

    @rpc
    def save_widths(self, widths):
        """The columns a drag just changed (MainWindow._save_tree_columns:
        only those, added to the ones dragged before)."""
        changed = {str(k): int(round(v)) for k, v in (widths or {}).items()
                   if str(k) in self._WIDTH_COLS
                   and isinstance(v, (int, float))
                   and not isinstance(v, bool) and 20 <= v <= 4000}
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


TAB = VideoTab
