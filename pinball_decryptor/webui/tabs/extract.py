"""Extract tab: turn a game's shipped media (a card image, an install ISO,
an update file, or the physical card in a reader) into a project folder.

The Python half of ``static/js/tabs/extract.js``.  A port of the Tk Extract
tab (``gui/main_window.py``: ``_build_extract_tab`` and every method it
wires) with the same behaviour per manufacturer / era / capability:

* the source toggle (file vs the physical SD card / SSD) with the drive
  list, Refresh, "Save card as image…" (``gui/read_card_dialog.py``), the
  card identity line, the red safety line and the ADMINISTRATOR / macOS
  Full Disk Access panels;
* the input row with recent paths and the detect badge (Not recognised /
  Looks like … click to switch / Extract only), the era auto-switch and
  ``on_detected_game_change``; the Image Info window;
* the Project Folder row ("Use parent folder?", anchored-project
  auto-load) and the Project Info stats;
* Dutch Pinball's deltas, JJP's asset filters and dongle, the PinMAME
  capture rows, the live DMD frames and switch matrix, Decode DMD, the
  categories, the auto-name options and the Extract / Cancel button with
  its disabled reasons.

Detection, drive enumeration, card identity, Image Info and the project
stats run on worker threads (they read big files or devices); each result
comes back through the UI loop and a bump counter drops stale answers.
"""

import inspect
import logging
import os
import sys
import threading

from .. import compat
from .. import extract_helpers as H
from .base import TabService, rpc

log = logging.getLogger(__name__)

_EXPORTS = (
    "extract_input_var", "extract_output_var", "extract_input_source_var",
    "extract_drive_var", "extract_drive_display_var",
    "extract_partition_override_var", "extract_dongle_var",
    "extract_graphics_var", "extract_sounds_var", "extract_filesystem_var",
    "extract_deltas_display_var", "static_extract_var",
    "capture_mode_var", "capture_duration_var", "capture_gameplay_var",
    "decode_dmd_var", "transcribe_var", "music_id_var",
    "duration_names_var", "extract_delta_paths", "_extract_category_vars",
    "get_extract_options", "set_extract_options",
    "_refresh_extract_phases", "acknowledge_macos_fda",
    "reset_dmd_preview", "on_dmd_frame", "on_capture_ready",
    "_on_input_source_change",
    # shared with the Write tab's copies of the card-mode panels
    "_fda_acknowledged", "_dismiss_macos_fda_banner", "_admin_body_text",
    "_admin_warning_collapsed", "_toggle_admin_warning",
)


def _is_admin():
    from ...core.admin import is_admin
    try:
        return bool(is_admin())
    except Exception:                                   # noqa: BLE001
        return False


class ExtractTab(TabService):
    ns = "extract"
    key = "Extract"
    label = "Extract"
    group = "Card"
    icon = "extract"
    exports = _EXPORTS

    #: milliseconds between live-DMD repaints while a capture runs (the
    #: capture callback is throttled to ~20 fps upstream)
    DMD_PUMP_MS = 50

    def __init__(self, window):
        super().__init__(window)
        v = self.var
        self.extract_input_var = v("input")
        self.extract_output_var = v("output")
        # "iso" = the file row, "ssd" = the physical card / SSD (Tk values)
        self.extract_input_source_var = v("source", value="iso")
        self.extract_drive_var = v("drive")                 # device path
        self.extract_drive_display_var = v("drive_display")
        # no widget (it spooked users) but the SSD extract still reads it
        self.extract_partition_override_var = v("partition_override")
        self.extract_dongle_var = v("dongle", "bool", False)
        self.extract_graphics_var = v("graphics", "bool", True)
        self.extract_sounds_var = v("sounds", "bool", True)
        self.extract_filesystem_var = v("filesystem", "bool", False)
        self.extract_deltas_display_var = v("deltas_summary",
                                            value="No updates added")
        self.static_extract_var = v("static", "bool", True)
        self.capture_mode_var = v("capture", "bool", False)
        self.capture_duration_var = v("capture_duration", "str", "180")
        self.capture_gameplay_var = v("capture_gameplay", "bool", True)
        self.decode_dmd_var = v("decode_dmd", "bool", False)
        self.transcribe_var = v("transcribe", "bool", False)
        self.music_id_var = v("music_id", "bool", False)
        self.duration_names_var = v("duration_names", "bool", False)
        self._rc_image_var = v("rc_image")
        self.extract_delta_paths = []
        self._extract_category_vars = {}
        self._saved_extract_options = {}

        self._audio_supported = True
        self._suggested_mfr = None
        self._probe_seq = 0
        self._probe_thread = None
        self._card_seq = 0
        self._card_thread = None
        self._enum_seq = 0
        self._drives_thread = None
        self._drives_cache = []
        self._stats_seq = 0
        self._stats_after = None
        self._stats_thread = None
        self._info_seq = 0
        self._info_thread = None
        self._info_path = ""
        self._info_sections = []
        self._info_shown_key = None
        self._dmd_latest = None
        self._dmd_shown = None
        self._dmd_pump_id = None
        self._manual_press_fn = None
        self._rc = None
        self._rc_seq = 0
        self._rc_thread = None

        cb = window.cb
        self._fda_ack = bool(cb.get("initial_fda_acknowledged"))
        self._admin_collapsed = bool(
            cb.get("initial_admin_warning_collapsed"))

        self.extract_input_var.trace_add(
            "write", lambda *_a: self._on_input_changed())
        self.extract_output_var.trace_add(
            "write", lambda *_a: self._on_output_changed())
        self.extract_input_source_var.trace_add(
            "write", lambda *_a: self._apply_source())
        self.extract_drive_var.trace_add(
            "write", lambda *_a: self._refresh_gate())
        for var in (self.static_extract_var, self.capture_mode_var):
            var.trace_add("write", lambda *_a: self._on_extract_mode_toggle())
        self.extract_dongle_var.trace_add(
            "write", lambda *_a: self._refresh_extract_phases())
        self._rc_image_var.trace_add(
            "write", lambda *_a: self._rc_update_readout())

        self.set(categories=[], mfr_key="", input_label="Input",
                 direct=False, ssd=False, iso_label="From ISO",
                 ssd_label="From SSD", drive_label="Game SSD",
                 identify=False, read_card=False, drives=[],
                 drives_state="idle", card_line="",
                 safety=H.DEFAULT_SAFETY_TEXT, admin_panel=False,
                 admin_body=H.admin_body_text(None),
                 admin_collapsed=self._admin_collapsed,
                 fda_panel=False, fda_body=H.FDA_BODY,
                 fda_ack=self._fda_ack,
                 badge=None, detected=None, extensions=[],
                 asset_filters=False, dongle_cap=False,
                 capture_cap=False, capture_primary=False,
                 capture_help="", capture_help_kind="",
                 decode_show=False, decode_label="",
                 deltas_show=False, deltas_help=H.DEFAULT_DELTAS_HELP,
                 deltas=[], opt_transcribe=False, opt_music=False,
                 opt_duration=False, autoname_enabled=True,
                 block_reason="", dmd=None, matrix=None,
                 project=None, recents=[], info=None, pinfo=False,
                 rc=None, platform=sys.platform)

    # ------------------------------------------------------------------
    # shared panel state (the Write tab shows the same two panels)
    # ------------------------------------------------------------------
    @property
    def _fda_acknowledged(self):
        return self._fda_ack

    @property
    def _admin_warning_collapsed(self):
        return self._admin_collapsed

    @staticmethod
    def _admin_body_text(mfr):
        return H.admin_body_text(mfr)

    # ------------------------------------------------------------------
    # manufacturer (Tk apply_manufacturer, the Extract part)
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        caps = mfr.capabilities
        self._audio_supported = True
        self._suggested_mfr = None
        self._info_reset()
        direct = bool(getattr(caps, "direct_ssd", False))
        medium = getattr(mfr, "direct_medium_noun", "SSD") or "SSD"
        spec = getattr(mfr, "input_spec", None)
        self.set(
            mfr_key=mfr.key, input_label=H.input_label(mfr),
            extensions=list(spec.extensions) if spec is not None else [],
            direct=direct,
            iso_label=getattr(mfr, "extract_iso_label", "From ISO"),
            ssd_label=getattr(mfr, "extract_ssd_label", "From SSD"),
            drive_label=("Game SSD" if medium == "SSD"
                         else medium[:1].upper() + medium[1:]),
            safety=(getattr(mfr, "direct_safety_text", None)
                    or H.DEFAULT_SAFETY_TEXT),
            admin_body=H.admin_body_text(mfr),
            identify=bool(direct and getattr(caps, "identify_card", False)),
            read_card=bool(getattr(caps, "read_card_image", False)
                           and self.window.cb.get("on_read_card")),
            asset_filters=bool(getattr(caps, "asset_filters", False)),
            dongle_cap=bool(getattr(caps, "dongle_extract", False)),
            capture_cap=bool(getattr(caps, "capture", False)),
            capture_primary=bool(getattr(caps, "capture", False)
                                 and not getattr(caps, "extract", False)),
            badge=None, detected=None, card_line="",
            # game-aware rows wait for the input probe below
            decode_show=False, deltas_show=False,
            deltas_help=(getattr(mfr, "chain_deltas_help", None)
                         or H.DEFAULT_DELTAS_HELP),
            rc=None)
        self._rc = None

        if direct:
            self._apply_source()
        else:
            # the var trace re-lays the source rows out (file only)
            self.extract_input_source_var.set("iso")

        if not getattr(caps, "dongle_extract", False):
            self.extract_dongle_var.set(False)

        # the per-type categories, rebuilt default-on, then the saved state
        self._extract_category_vars = {}
        rows = []
        for entry in tuple(getattr(caps, "extract_categories", ()) or ()):
            key, label = entry[0], entry[1]
            var = self.var("cat_" + key, "bool", True)
            var.trace_add("write",
                          lambda *_a: self._update_autoname_state())
            self._extract_category_vars[key] = var
            rows.append({"key": key, "label": label,
                         "tip": H.EXTRACT_CATEGORY_TIPS.get(
                             key, f"Include {label.lower()} when "
                                  "extracting.")})
        self.set(categories=rows)
        self._apply_saved_extract_options()

        if getattr(caps, "capture", False):
            if not getattr(caps, "extract", False):
                self.static_extract_var.set(False)
                self.capture_mode_var.set(True)
        else:
            self.capture_mode_var.set(False)
            self.static_extract_var.set(True)
            self._stop_dmd_pump()
            self._dmd_latest = None
            self._manual_press_fn = None
            self.set(dmd=None, matrix=None)
        self._update_capture_help()
        self._update_option_visibility()
        self._refresh_extract_phases()
        self._refresh_gate()
        self._start_probe()
        self._refresh_recents()
        self._schedule_stats(0)

    # ------------------------------------------------------------------
    # options (persisted per manufacturer by the run logic)
    # ------------------------------------------------------------------
    def set_extract_options(self, opts):
        self._saved_extract_options = dict(opts or {})
        self._apply_saved_extract_options()

    def get_extract_options(self):
        opts = {
            "auto_name_callouts": bool(self.transcribe_var.get()),
            "auto_name_music": bool(self.music_id_var.get()),
            "duration_names": bool(self.duration_names_var.get()),
        }
        if self._extract_category_vars:
            opts["categories"] = {k: bool(v.get()) for k, v in
                                  self._extract_category_vars.items()}
        if self.cap("asset_filters"):
            opts["asset_filters"] = {
                "graphics": bool(self.extract_graphics_var.get()),
                "sounds": bool(self.extract_sounds_var.get()),
                "filesystem": bool(self.extract_filesystem_var.get()),
            }
        return opts

    def _apply_saved_extract_options(self):
        opts = self._saved_extract_options
        self.transcribe_var.set(bool(opts.get("auto_name_callouts", False)))
        self.music_id_var.set(bool(opts.get("auto_name_music", False)))
        self.duration_names_var.set(bool(opts.get("duration_names", False)))
        cats = opts.get("categories", {})
        for key, var in self._extract_category_vars.items():
            var.set(bool(cats.get(key, True)))
        filt = opts.get("asset_filters", {})
        self.extract_graphics_var.set(bool(filt.get("graphics", True)))
        self.extract_sounds_var.set(bool(filt.get("sounds", True)))
        self.extract_filesystem_var.set(bool(filt.get("filesystem", False)))
        self._update_autoname_state()

    def _update_autoname_state(self):
        """The auto-name options grey out while Audio is unticked (they
        rename extracted audio)."""
        audio = self._extract_category_vars.get("audio")
        self.set(autoname_enabled=audio is None or bool(audio.get()))

    def _on_extract_mode_toggle(self):
        """Basic extract / PinMAME capture toggled."""
        if self.mfr is None:
            return
        self._update_capture_help()
        self._refresh_extract_phases()
        self._update_option_visibility()
        self._refresh_gate()

    def _update_capture_help(self):
        caps = self.caps
        if caps is None or not getattr(caps, "capture", False):
            self.set(capture_help="", capture_help_kind="")
            return
        text, kind = H.capture_help(caps, self.static_extract_var.get(),
                                    self.capture_mode_var.get())
        self.set(capture_help=text, capture_help_kind=kind)

    def _update_option_visibility(self):
        """Auto-name call-outs / music and Length-prefix names show only
        when the plugin has them, the game's audio exports and (for capture
        plugins) Basic extract is ticked; hidden means off."""
        caps = self.caps
        if caps is None:
            return
        base = self._audio_supported and (
            not getattr(caps, "capture", False)
            or bool(self.static_extract_var.get()))
        show = {
            "opt_transcribe": bool(getattr(caps, "transcribe", False)
                                   and base),
            "opt_music": bool(getattr(caps, "music_id", False) and base),
            "opt_duration": bool(getattr(caps, "audio_duration_names", False)
                                 and base),
        }
        for key, var in (("opt_transcribe", self.transcribe_var),
                         ("opt_music", self.music_id_var),
                         ("opt_duration", self.duration_names_var)):
            if not show[key] and var.get():
                var.set(False)
        self.set(**show)

    # ------------------------------------------------------------------
    # the phase ladder
    # ------------------------------------------------------------------
    def _refresh_extract_phases(self):
        mfr = self.mfr
        if mfr is None:
            return
        caps = mfr.capabilities
        extract_ssd = bool(caps.direct_ssd
                           and self.extract_input_source_var.get() == "ssd")
        write_src = getattr(self.window, "write_input_source_var", None)
        write_ssd = bool(caps.direct_ssd and write_src is not None
                         and write_src.get() == "ssd")
        extract_dongle = (getattr(caps, "dongle_extract", False)
                          and not extract_ssd
                          and self.extract_dongle_var.get())
        if extract_dongle and getattr(mfr, "dongle_extract_phases", None):
            phases = mfr.dongle_extract_phases
        elif extract_ssd and mfr.direct_ssd_extract_phases:
            phases = mfr.direct_ssd_extract_phases
        else:
            basic = self.static_extract_var.get()
            capture = self.capture_mode_var.get() and caps.capture
            if basic and capture:
                phases = mfr.combined_phases or mfr.extract_phases
            elif capture and not basic:
                phases = mfr.capture_phases or mfr.extract_phases
            else:
                phases = mfr.extract_phases
            if not self._audio_supported:
                phases = tuple(p for p in phases if p != "Extract audio")
        if write_ssd and getattr(mfr, "direct_ssd_write_phases", None):
            write_phases = mfr.direct_ssd_write_phases
        else:
            write_phases = mfr.write_phases
        self.window._rebuild_phase_steps(phases, write_phases)

    # ------------------------------------------------------------------
    # input / output
    # ------------------------------------------------------------------
    def _on_input_changed(self):
        # the Write tab's Original follows this box (one-way mirror)
        self._mirror("write_upd_var", self.extract_input_var.get())
        self._refresh_gate()
        self._start_probe()

    def _on_output_changed(self):
        # the shared assets folder every other tab reads follows this box
        self._mirror("write_assets_var", self.extract_output_var.get())
        self._refresh_gate()
        self._schedule_stats()
        # which recent project is the current one follows the box too
        self._refresh_recents()

    def _mirror(self, name, val):
        """Set another tab's var when it differs (a failing trace on it is
        logged by compat and does not stop the others, as in Tk)."""
        wvar = getattr(self.window, name, None)
        if wvar is not None and wvar.get() != val:
            wvar.set(val)

    # ------------------------------------------------------------------
    # detection (the badge, the era, the title caption)
    # ------------------------------------------------------------------
    def _start_probe(self):
        self._probe_seq += 1
        seq = self._probe_seq
        mfr = self.mfr
        if mfr is None:
            return
        path = self.extract_input_var.get()
        mfrs = list(self.window.manufacturers)

        def _work():
            try:
                res = H.probe_input(mfr, mfrs, path)
            except Exception:                           # noqa: BLE001
                res = None
            self.ctx.loop.post(self._apply_probe, seq, mfr, res)

        t = threading.Thread(target=_work, daemon=True,
                             name="extract-probe")
        self._probe_thread = t
        t.start()

    def _notify_detected_game(self, caption):
        cb = self.window.cb.get("on_detected_game_change")
        if cb is not None:
            cb(caption)

    def _apply_probe(self, seq, mfr, res):
        if seq != self._probe_seq or self.mfr is not mfr or res is None:
            return
        caps = mfr.capabilities
        # game-aware rows (_on_extract_input_changed)
        if res["decode_applies"]:
            self.set(decode_show=True, decode_label=res["decode_label"])
        else:
            self.decode_dmd_var.set(False)
            self.set(decode_show=False)
        if res["chain_applies"]:
            self.set(deltas_show=True)
        else:
            if self.extract_delta_paths:
                self.extract_delta_paths = []
            self._refresh_deltas()
            self.set(deltas_show=False)

        # the badge (_set_badge)
        self._suggested_mfr = None
        badge = None
        detected = None
        if not res["exists"]:
            self._notify_detected_game(None)
        elif res["game"]:
            era = res["era"]
            if (era and hasattr(mfr, "set_era")
                    and getattr(mfr, "_era", "") != era):
                mfr.set_era(era)
                self.window.apply_manufacturer(mfr, reset_era=False)
                recheck = self.window.cb.get("on_recheck_prereqs")
                if recheck is not None:
                    recheck()
                return
            self._notify_detected_game(res["caption"])
            if hasattr(mfr, "set_era") and not caps.write and not (
                    caps.replace_audio or caps.replace_video
                    or caps.replace_image or caps.replace_text):
                badge = {"text": "Extract only — this format has no "
                                 "Write/Replace support.",
                         "kind": "info", "switch": False}
            era_label = ""
            for entry in tuple(getattr(mfr, "eras", ()) or ()):
                if entry[0] == era:
                    era_label = entry[1]
            detected = {"caption": res["caption"] or "",
                        "era": era_label, "size": res["size"]}
        else:
            self._notify_detected_game(None)
            others = res["others"]
            if len(others) == 1:
                m, g = others[0]
                self._suggested_mfr = m
                badge = {"text": f"Looks like {g.display} ({m.display}) — "
                                 "click to switch",
                         "kind": "warn", "switch": True}
            elif len(others) > 1:
                names = ", ".join(m.display for m, _ in others)
                badge = {"text": f"Matches multiple manufacturers: {names}",
                         "kind": "warn", "switch": False}
            else:
                badge = {"text": f"Not recognised as {mfr.display}",
                         "kind": "warn", "switch": False}
        self.set(badge=badge, detected=detected)

        # audio-export support (_refresh_extract_audio_support)
        supported = bool(res["audio_supported"])
        if supported != self._audio_supported:
            self._audio_supported = supported
            self._refresh_extract_phases()
            self._update_option_visibility()

    @rpc
    def switch_suggested(self):
        """The "Looks like … — click to switch" badge: switch manufacturer
        and keep the path (the new one's saved settings would blank it)."""
        m = self._suggested_mfr
        if m is None:
            return False
        path = self.extract_input_var.get()
        cb = self.window.cb.get("on_manufacturer_change")
        if cb is not None:
            cb(m)
        self.extract_input_var.set(path)
        return True

    # ------------------------------------------------------------------
    # the source toggle and the card row
    # ------------------------------------------------------------------
    def _ssd_mode(self):
        caps = self.caps
        return bool(caps is not None and getattr(caps, "direct_ssd", False)
                    and self.extract_input_source_var.get() == "ssd")

    def _apply_source(self):
        """Swap the file row for the drive row (``_on_input_source_change``
        for "extract")."""
        if self.mfr is None:
            return
        ssd = self._ssd_mode()
        self.set(ssd=ssd,
                 admin_panel=bool(ssd and sys.platform == "win32"
                                  and not _is_admin()),
                 fda_panel=bool(ssd and sys.platform == "darwin"
                                and not self._fda_ack))
        if ssd:
            if self.get("identify"):
                self.set(card_line="")
            self._refresh_drives_async()
        self._refresh_extract_phases()
        self._refresh_gate()

    def _on_input_source_change(self, mode):
        """app.py calls this after setting a source var: "extract" re-lays
        this tab out; "write" belongs to the Write tab's service."""
        if mode == "write":
            svc = self.window.service("write")
            for name in ("_on_input_source_change",
                         "on_input_source_change"):
                fn = getattr(svc, name, None) if svc is not None else None
                if fn is not None and getattr(fn, "__self__", None) \
                        is not self:
                    try:
                        takes_mode = bool(inspect.signature(fn).parameters)
                    except (TypeError, ValueError):
                        takes_mode = True
                    if takes_mode:
                        fn(mode)
                    else:
                        fn()
                    break
            self._refresh_extract_phases()
            return
        self._apply_source()

    @rpc
    def set_source(self, source):
        self.extract_input_source_var.set(
            "ssd" if source == "ssd" else "iso")
        return True

    @rpc
    def refresh_drives(self):
        self._refresh_drives_async()
        return True

    def _refresh_drives_async(self):
        self._enum_seq += 1
        seq = self._enum_seq
        mfr = self.mfr
        prefer = getattr(mfr, "direct_target_kind", "ssd")
        self._drives_cache = []
        self.extract_drive_display_var.set("Detecting drives…")
        self.extract_drive_var.set("")
        self.set(drives=[], drives_state="detecting")

        def _work():
            try:
                from ...core.drives import (list_physical_drives,
                                            pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:                           # noqa: BLE001
                drives, pick = [], (None, None, None)
            self.ctx.loop.post(self._apply_drives, seq, mfr, drives, pick)

        t = threading.Thread(target=_work, daemon=True,
                             name="extract-drives")
        self._drives_thread = t
        t.start()

    def _apply_drives(self, seq, mfr, drives, pick):
        if seq != self._enum_seq or self.mfr is not mfr:
            return
        if not drives:
            self._drives_cache = []
            self.extract_drive_display_var.set(
                "(no drives found — click Refresh)")
            self.extract_drive_var.set("")
            self.set(drives=[], drives_state="none", card_line="")
            self.log("No physical drives detected.  Check that the SSD "
                     "is connected and click Refresh.", "error")
            return
        best, confidence, reason = pick
        from ...core.drives import visible_drives
        prefer = getattr(mfr, "direct_target_kind", "ssd")
        keep = (best,) if best is not None else ()
        shown = visible_drives(drives, prefer=prefer, keep=keep)
        hidden = len(drives) - len(shown)
        self._drives_cache = list(shown)
        self.set(drives=[{"display": d.display, "device": d.device_path}
                         for d in shown], drives_state="ok")
        if best is not None:
            self.extract_drive_display_var.set(best.display)
            self._on_drive_selected()
            self.log("Selected SSD: %s" % best.display,
                     "success" if confidence == "high" else "info")
            if reason:
                self.log("  (%s)" % reason, "info")
            if confidence != "high":
                noun = getattr(mfr, "direct_medium_noun", "SSD")
                self.log("  If this isn't the %s, pick it manually from the "
                         "dropdown." % noun, "info")
        elif shown:
            self.extract_drive_display_var.set(shown[0].display)
            self._on_drive_selected()
        if hidden > 0:
            self.log("  (hid %d drive(s) too large to be a game SD card; "
                     "connect the card and click Refresh if you don't see "
                     "it)" % hidden, "info")

    @rpc
    def select_drive(self, display):
        self.extract_drive_display_var.set(display or "")
        self._on_drive_selected()
        return True

    def _on_drive_selected(self):
        label = self.extract_drive_display_var.get()
        match = next((d for d in self._drives_cache if d.display == label),
                     None)
        self.extract_drive_var.set(match.device_path if match else "")
        self._identify_card_async(self.extract_drive_var.get())

    def _identify_card_async(self, device_path):
        """Name the game on the card in the reader, read in place (nothing
        copied); a bump counter drops a late answer for a swapped card."""
        if not self.get("identify"):
            return
        self._card_seq += 1
        seq = self._card_seq
        if not device_path:
            self.set(card_line="")
            return
        mfr = self.mfr
        self.set(card_line="Reading the card…")

        def _work():
            try:
                caption = mfr.identify_card(device_path) or ""
            except Exception:                           # noqa: BLE001
                caption = ""
            self.ctx.loop.post(self._apply_card_identity, seq, mfr, caption)

        t = threading.Thread(target=_work, daemon=True,
                             name="extract-card-id")
        self._card_thread = t
        t.start()

    def _apply_card_identity(self, seq, mfr, caption):
        if seq != self._card_seq or self.mfr is not mfr \
                or not self.get("identify"):
            return
        if caption:
            self.set(card_line="Card: %s" % caption)
        elif sys.platform == "win32" and not _is_admin():
            self.set(card_line="Card: needs Administrator to read — see "
                               "below")
        else:
            self.set(card_line="Card: not recognised as a %s card"
                               % mfr.display)

    # -- the red panels -------------------------------------------------
    @rpc
    def toggle_admin_warning(self):
        self._toggle_admin_warning()
        return self._admin_collapsed

    def _toggle_admin_warning(self):
        self._admin_collapsed = not self._admin_collapsed
        self.set(admin_collapsed=self._admin_collapsed)
        cb = self.window.cb.get("on_admin_warning_collapsed_change")
        if cb is not None:
            cb(self._admin_collapsed)

    @rpc
    def dismiss_fda(self):
        self._dismiss_macos_fda_banner()
        return True

    def _dismiss_macos_fda_banner(self):
        self._fda_ack = True
        self.set(fda_ack=True)
        cb = self.window.cb.get("on_fda_acknowledge")
        if cb is not None:
            try:
                cb(True)
            except Exception:                           # noqa: BLE001
                pass
        self.set(fda_panel=False)

    def acknowledge_macos_fda(self):
        if not self._fda_ack:
            self._dismiss_macos_fda_banner()

    # ------------------------------------------------------------------
    # the Extract button's gate
    # ------------------------------------------------------------------
    def _block_reason(self):
        mfr = self.mfr
        ssd_mode = self._ssd_mode()
        medium = getattr(mfr, "direct_medium_noun", "SSD") if mfr else "SSD"
        if sys.platform == "win32" and ssd_mode and not _is_admin():
            return ("Administrator privileges are required to read the "
                    f"{medium} directly — see the warning above.")
        have = (bool(self.extract_drive_var.get().strip()) if ssd_mode
                else bool(self.extract_input_var.get().strip()))
        if not have:
            if ssd_mode:
                return f"Select the {medium} to read from first."
            noun = getattr(mfr, "extract_input_label", None) if mfr else None
            article = "an" if noun and noun[:1].lower() in "aeiou" else "a"
            thing = f"{article} {noun}" if noun else "a file"
            return f"Pick {thing} to extract first."
        if not self.extract_output_var.get().strip():
            return "Choose an output folder first."
        return ""

    def _refresh_gate(self):
        if self.mfr is None:
            return
        self.set(block_reason=self._block_reason())

    def on_running(self, running, mode):
        if not running:
            self._refresh_gate()
            self._refresh_recents()
            self._schedule_stats(200)
            if self._dmd_pump_id is not None:
                self._dmd_tick(rearm=False)
                self._stop_dmd_pump()

    def on_show(self):
        self._refresh_recents()

    # ------------------------------------------------------------------
    # the page's calls: paths
    # ------------------------------------------------------------------
    @rpc
    def browse_input(self):
        path = self.window.ask_open(
            "extract_input", "Select input file",
            H.input_filetypes(self.mfr),
            initialdir=self.window._initialdir_for(
                self.extract_input_var.get()))
        if path:
            self.extract_input_var.set(os.path.normpath(path))
        return bool(path)

    @rpc
    def browse_output(self):
        path = self.window.ask_folder(
            "extract_output", "Select project folder",
            initialdir=self.window._initialdir_for(
                self.extract_output_var.get(), self.extract_input_var.get()))
        if not path:
            return False
        self._pick_output(path)
        return True

    def _pick_output(self, path):
        """A picked project folder: offer the extract's real folder when a
        subfolder was picked, then auto-load an anchored project."""
        if not os.path.isfile(os.path.join(path, ".checksums.md5")):
            parent = H.find_checksums_ancestor(path)
            if parent and compat.messagebox.askyesno(
                    "Use parent folder?",
                    "The folder you picked doesn't contain a "
                    "`.checksums.md5` baseline, but its parent "
                    f"`{parent}` does — that's the folder Extract "
                    "produced.\n\nUse the parent folder instead?"):
                path = parent
        path = os.path.normpath(path)
        self.extract_output_var.set(path)
        cb = self.window.cb.get("on_project_folder_picked")
        if cb is not None:
            cb(path)

    @rpc
    def unmap(self, key, value=None):
        """A path box was left: a mapped drive letter this (elevated)
        session can't see becomes its UNC target."""
        var = {"input": self.extract_input_var,
               "output": self.extract_output_var}.get(key)
        if var is None:
            return False
        from ...core.admin import resolve_mapped_drive
        cur = var.get() if value is None else str(value)
        fixed = resolve_mapped_drive(cur)
        if fixed != var.get():
            var.set(fixed)
        return True

    @rpc
    def use_recent(self, key, path):
        """A path picked from a box's recent-paths list."""
        var = {"input": self.extract_input_var,
               "output": self.extract_output_var}.get(key)
        if var is None or not path:
            return False
        from ...core.admin import resolve_mapped_drive
        var.set(resolve_mapped_drive(path))
        return True

    @rpc
    def drop_paths(self, paths):
        """Files dropped on the tab (the desktop window reports their full
        paths): a file is the input, a folder the project folder."""
        for p in paths or ():
            p = os.path.normpath(str(p or ""))
            if not p or p == ".":
                continue
            if os.path.isdir(p):
                if self.window._is_running():
                    return False
                self._pick_output(p)
                return True
            if os.path.isfile(p):
                if self._ssd_mode():
                    self.extract_input_source_var.set("iso")
                self.extract_input_var.set(p)
                return True
        return False

    # -- deltas (Dutch Pinball) ----------------------------------------
    @rpc
    def add_deltas(self):
        paths = self.window.ask_open(
            "extract_deltas", "Select delta update(s) to merge on top",
            H.input_filetypes(self.mfr), multiple=True,
            initialdir=self.window._initialdir_for(
                self.extract_input_var.get(), self.extract_output_var.get()))
        if isinstance(paths, str):
            paths = [paths] if paths else []
        for p in paths or ():
            p = os.path.normpath(p) if p else p
            if p and p not in self.extract_delta_paths:
                self.extract_delta_paths.append(p)
        self._refresh_deltas()
        return len(self.extract_delta_paths)

    @rpc
    def clear_deltas(self):
        self.extract_delta_paths = []
        self._refresh_deltas()
        return True

    def _refresh_deltas(self):
        self.extract_deltas_display_var.set(
            H.deltas_summary(self.extract_delta_paths))
        self.set(deltas=[os.path.basename(p)
                         for p in self.extract_delta_paths])

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------
    @rpc
    def start(self):
        if self.window._is_running():
            return False
        cb = self.window.cb.get("on_extract")
        if cb is not None:
            cb()
        return True

    @rpc
    def cancel(self):
        """The Extract button while this tab's run is in flight."""
        if not self.window._is_running():
            return False
        cb = self.window.cb.get("on_extract_cancel")
        if cb is not None:
            cb()
        return True

    # ------------------------------------------------------------------
    # live DMD + switch matrix (PinMAME capture)
    # ------------------------------------------------------------------
    def on_dmd_frame(self, data, width, height, depth):
        """From libpinmame's display thread: stash the latest frame only
        (the loop's pump renders it)."""
        try:
            n = int(width) * int(height)
            frame = bytes(data[:n])
        except Exception:                               # noqa: BLE001
            return
        self._dmd_latest = (frame, int(width), int(height), int(depth))

    def reset_dmd_preview(self):
        """Before a new capture run: forget the last frame, start the
        pump."""
        self._dmd_latest = None
        self._dmd_shown = None
        self.set(dmd=None)
        if self.ctx.loop.in_loop():
            self._start_dmd_pump()
        else:
            self.ctx.loop.post(self._start_dmd_pump)

    def _start_dmd_pump(self):
        if self._dmd_pump_id is None:
            self._dmd_pump_id = self.ctx.loop.after(self.DMD_PUMP_MS,
                                                    self._dmd_tick)

    def _stop_dmd_pump(self):
        if self._dmd_pump_id is not None:
            try:
                self.ctx.loop.after_cancel(self._dmd_pump_id)
            except Exception:                           # noqa: BLE001
                pass
            self._dmd_pump_id = None

    def _dmd_tick(self, rearm=True):
        latest = self._dmd_latest
        if latest is not None and latest is not self._dmd_shown:
            frame, w, h, depth = latest
            src = H.render_dmd_png(frame, w, h, depth)
            if src:
                self._dmd_shown = latest
                self.set(dmd={"src": src, "w": w, "h": h})
        if rearm:
            self._dmd_pump_id = self.ctx.loop.after(self.DMD_PUMP_MS,
                                                    self._dmd_tick)

    def on_capture_ready(self, manual_press_fn, active_script):
        """From the capture thread once PinMAME booted: the manual-press
        function and the game's switch map."""
        self._manual_press_fn = manual_press_fn
        self.ctx.loop.post(self._build_switch_matrix, active_script)

    def _build_switch_matrix(self, script):
        try:
            self.set(matrix=H.switch_matrix(script))
        except Exception:                               # noqa: BLE001
            self.set(matrix={"title": "Switch matrix (no switches defined)",
                             "named": [], "unknown": []})

    @rpc
    def press_switch(self, sw_no, label=""):
        fn = self._manual_press_fn
        if fn is None:
            return False
        try:
            fn(int(sw_no), 120)
        except Exception as e:                          # noqa: BLE001
            self.log(f"manual press sw#{sw_no} ({label}) failed: {e}",
                     "warning")
            return False
        return True

    # ------------------------------------------------------------------
    # Image Info (the i badge beside the input / the drive)
    # ------------------------------------------------------------------
    @rpc
    def open_image_info(self, which="input"):
        from ...core.rawdevice import is_device_path
        var = (self.extract_drive_var if which == "drive"
               else self.extract_input_var)
        path = (var.get() or "").strip()
        if not path:
            compat.messagebox.showinfo(
                "No image selected",
                "Pick an image in the box next to the Info button first.")
            return False
        if is_device_path(path):
            self._info_path = path
        elif not os.path.isfile(path):
            compat.messagebox.showerror("File not found",
                                        "No file at:\n\n%s" % path)
            return False
        else:
            self._info_path = os.path.normpath(path)
        self._info_refresh()
        return True

    def _info_assets_dir(self):
        wvar = getattr(self.window, "write_assets_var", None)
        assets = ((wvar.get() if wvar is not None else "") or "").strip() \
            or (self.extract_output_var.get() or "").strip()
        return assets if assets and os.path.isdir(assets) else None

    def _info_state(self, **kw):
        info = dict(self.get("info") or {})
        info.update(kw)
        self.set(info=info)

    @rpc
    def info_refresh(self):
        self._info_refresh(force=True)
        return True

    def _info_refresh(self, force=False):
        from ...core import image_info as _info_mod
        path = self._info_path
        if not path:
            return
        assets = self._info_assets_dir()
        key = (os.path.normcase(path), assets)
        if not force and key == self._info_shown_key and self.get("info"):
            self._info_state(open=True, path=path)
            return
        mfr = self.mfr
        self._info_seq += 1
        seq = self._info_seq
        self._info_shown_key = None
        self._info_sections = []
        self.set(info={"open": True, "path": path, "sections": [],
                       "loading": True, "status": "Reading image…"})

        def _work():
            try:
                sections = _info_mod.collect(mfr, path, assets)
            except Exception as e:                      # noqa: BLE001
                sections = [("Error", [("Could not read", str(e))])]
            self.ctx.loop.post(self._apply_info, seq, key, sections)

        t = threading.Thread(target=_work, daemon=True, name="extract-info")
        self._info_thread = t
        t.start()

    def _apply_info(self, seq, key, sections):
        if seq != self._info_seq:
            return
        self._info_shown_key = key
        self._info_sections = list(sections or [])
        out = []
        for title, rows in self._info_sections:
            out.append({"title": str(title),
                        "rows": [[str(r[0]), str(r[1])] for r in rows]})
        self._info_state(sections=out, loading=False, status="")

    @rpc
    def info_copy(self):
        from ...core import image_info as _info_mod
        if not self._info_sections:
            return ""
        text = _info_mod.as_text(self._info_sections)
        self.ctx.bus.publish("clipboard", text=text)
        self._info_state(status="Report copied to clipboard.")
        return text

    @rpc
    def info_close(self):
        self._info_reset()
        return True

    def _info_reset(self):
        self._info_seq += 1
        self._info_sections = []
        self._info_shown_key = None
        self._info_path = ""
        self.set(info=None)

    # ------------------------------------------------------------------
    # This project: stats (the Project Info popup) + recent projects
    # ------------------------------------------------------------------
    def _project_folder(self):
        folder = (self.extract_output_var.get() or "").strip()
        if not folder:
            wvar = getattr(self.window, "write_assets_var", None)
            folder = ((wvar.get() if wvar is not None else "") or "").strip()
        return folder

    def _schedule_stats(self, delay=500):
        if self._stats_after is not None:
            try:
                self.ctx.loop.after_cancel(self._stats_after)
            except Exception:                           # noqa: BLE001
                pass
        self._stats_after = self.ctx.loop.after(delay, self._start_stats)

    @rpc
    def refresh_project(self):
        self._start_stats()
        return True

    def _start_stats(self):
        self._stats_after = None
        self._stats_seq += 1
        seq = self._stats_seq
        folder = self._project_folder()
        if not folder:
            self.set(project=None)
            return
        folder = os.path.normpath(folder)
        name = os.path.basename(folder.rstrip("\\/")) or folder
        if not os.path.isdir(folder):
            self.set(project={"folder": folder, "name": name,
                              "exists": False, "loading": False,
                              "rows": [], "details": None})
            return
        prev = self.get("project") or {}
        same = prev.get("folder") == folder
        self.set(project={"folder": folder, "name": name, "exists": True,
                          "loading": True,
                          "rows": prev.get("rows", []) if same else [],
                          "details": prev.get("details") if same else None})
        # the project's game is detected by the project's own manufacturer
        # (its anchor) from its own image, never read off the input box
        mfrs = list(self.window.manufacturers)
        mfr = self.mfr

        def _work():
            try:
                rows = H.collect_project_stats(folder)
            except Exception as e:                      # noqa: BLE001
                rows = [("Error", str(e))]
            try:
                details = H.project_details(folder, mfrs, mfr)
            except Exception:                           # noqa: BLE001
                details = None
            self.ctx.loop.post(self._apply_stats, seq, folder, name, rows,
                               details)

        t = threading.Thread(target=_work, daemon=True,
                             name="extract-stats")
        self._stats_thread = t
        t.start()

    def _apply_stats(self, seq, folder, name, rows, details):
        if seq != self._stats_seq:
            return
        self.set(project={"folder": folder, "name": name, "exists": True,
                          "loading": False,
                          "rows": [[str(a), str(b)] for a, b in rows],
                          "details": details})

    @rpc
    def open_project_info(self):
        """The i badge on the project row: the Project Info stats."""
        folder = self._project_folder()
        if not folder or not os.path.isdir(folder):
            compat.messagebox.showinfo(
                "No project folder",
                "Pick (or extract into) a project folder first — the stats "
                "describe that folder.")
            return False
        self.set(pinfo=True)
        self._start_stats()
        return True

    @rpc
    def close_project_info(self):
        self.set(pinfo=False)
        return True

    @rpc
    def open_project_folder(self):
        folder = self._project_folder()
        if not folder or not os.path.isdir(folder):
            return False
        from ...core import desktop
        desktop.open_path(folder)
        return True

    def _refresh_recents(self):
        from ...core import project_registry
        settings = getattr(self.app, "_settings", None) or {}
        try:
            entries = project_registry.recent(settings, 8)
        except Exception:                               # noqa: BLE001
            entries = []
        names = {m.key: m.display for m in self.window.manufacturers}
        here = self._project_folder()
        cur = os.path.normcase(os.path.normpath(here)) if here else ""
        rows = []
        for e in entries:
            folder = e.get("folder") or ""
            if not folder:
                continue
            stamp = str(e.get("last_opened") or "")
            rows.append({
                "folder": folder,
                "name": os.path.basename(os.path.normpath(folder)) or folder,
                "mfr": names.get(e.get("manufacturer") or "", ""),
                "date": stamp[:10],
                "current": bool(cur) and os.path.normcase(
                    os.path.normpath(folder)) == cur,
            })
        self.set(recents=rows)

    @rpc
    def open_recent(self, folder):
        if self.window._is_running():
            return False
        cb = self.window.cb.get("on_open_recent_project")
        if cb is not None:
            cb(folder)
        self._refresh_recents()
        return True

    # ------------------------------------------------------------------
    # Save card as image (gui/read_card_dialog.py, as a page dialog)
    # ------------------------------------------------------------------
    @rpc
    def open_read_card(self):
        on_read = self.window.cb.get("on_read_card")
        mfr = self.mfr
        if on_read is None or mfr is None:
            return False
        if self.window._is_running():
            compat.messagebox.showinfo(
                "Busy", "Finish or cancel the current operation before "
                        "reading a card.")
            return False
        initial_dir = (self.extract_output_var.get() or "").strip()
        if not (initial_dir and os.path.isdir(initial_dir)):
            card = (self.extract_input_var.get() or "").strip()
            initial_dir = os.path.dirname(card) if card else ""
        noun = getattr(mfr, "direct_medium_noun", "SD card")
        if _is_admin():
            admin_note = ""
        else:
            from ...core.elevated_flash import can_self_elevate
            try:
                elevates = bool(can_self_elevate())
            except Exception:                           # noqa: BLE001
                elevates = False
            admin_note = ("You may be asked to approve administrator access "
                          "when the read starts." if elevates
                          else "Reading a card needs administrator access. "
                               "Re-launch the app as an administrator, then "
                               "reopen this dialog.")
        self._rc = {"initial_dir": initial_dir if (
                        initial_dir and os.path.isdir(initial_dir)) else None,
                    "noun": noun,
                    "kind": getattr(mfr, "direct_target_kind", "sd_card"),
                    "drives": [], "selected": None, "named_for": None}
        self.set(rc={"open": True, "noun": noun, "drives": [],
                     "drive": "", "detecting": True, "readout": "",
                     "readout_kind": "", "admin_note": admin_note})
        self._rc_image_var.set("")
        self._rc_refresh()
        return True

    def _rc_state(self, **kw):
        rc = dict(self.get("rc") or {})
        rc.update(kw)
        self.set(rc=rc)

    @rpc
    def rc_refresh(self):
        self._rc_refresh()
        return True

    def _rc_refresh(self):
        rc = self._rc
        if rc is None:
            return
        self._rc_seq += 1
        seq = self._rc_seq
        kind = rc["kind"]
        self._rc_state(drives=[], drive="Detecting drives…", detecting=True)

        def _work():
            try:
                from ...core.drives import (list_physical_drives,
                                            pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=kind)
            except Exception:                           # noqa: BLE001
                drives, pick = [], (None, None, None)
            self.ctx.loop.post(self._rc_apply_drives, seq, drives, pick)

        t = threading.Thread(target=_work, daemon=True, name="extract-rc")
        self._rc_thread = t
        t.start()

    def _rc_apply_drives(self, seq, drives, pick):
        rc = self._rc
        if rc is None or seq != self._rc_seq:
            return
        from ...core.drives import visible_drives
        best = pick[0] if pick else None
        drives = visible_drives(drives, prefer=rc["kind"],
                                keep=[best] if best else ())
        rc["drives"] = list(drives)
        if not drives:
            rc["selected"] = None
            self._rc_state(drives=[], detecting=False,
                           drive="(no drives found — click Refresh)")
            self._rc_update_readout()
            return
        chosen = best if (best and best in drives) else drives[0]
        rc["selected"] = chosen
        self._rc_state(drives=[d.display for d in drives], detecting=False,
                       drive=chosen.display)
        self._rc_suggest_name()
        self._rc_update_readout()

    @rpc
    def rc_select(self, display):
        rc = self._rc
        if rc is None:
            return False
        rc["selected"] = next((d for d in rc["drives"]
                               if d.display == display), None)
        self._rc_state(drive=display or "")
        self._rc_suggest_name()
        self._rc_update_readout()
        return True

    def _rc_suggest_name(self):
        rc = self._rc
        if rc is None or rc["selected"] is None:
            return
        cur = self._rc_image_var.get().strip()
        if cur and cur != rc["named_for"]:
            return
        folder = rc["initial_dir"] or os.path.expanduser("~")
        path = os.path.normpath(os.path.join(
            folder, H.default_image_name(rc["selected"], rc["noun"])))
        rc["named_for"] = path
        self._rc_image_var.set(path)

    def _rc_update_readout(self):
        rc = self._rc
        if rc is None:
            return
        text, kind = H.read_card_readout(rc["selected"],
                                         self._rc_image_var.get(),
                                         rc["noun"])
        self._rc_state(readout=text, readout_kind=kind)

    @rpc
    def rc_browse(self):
        rc = self._rc
        if rc is None:
            return False
        cur = self._rc_image_var.get().strip()
        initial_dir = os.path.dirname(cur) if cur else None
        if not (initial_dir and os.path.isdir(initial_dir)):
            initial_dir = rc["initial_dir"]
        path = compat.filedialog.asksaveasfilename(
            title="Save the card image as…", initialdir=initial_dir,
            initialfile=(os.path.basename(cur) if cur
                         else H.default_image_name(rc["selected"],
                                                   rc["noun"])),
            defaultextension=".raw",
            filetypes=[("SD-card image", "*.raw *.img *.bin"),
                       ("All files", "*.*")])
        if path and self._rc is rc:
            rc["named_for"] = None          # the user named it; stop retitling
            self._rc_image_var.set(os.path.normpath(path))
        return bool(path)

    @rpc
    def rc_start(self):
        rc = self._rc
        if rc is None:
            return False
        noun = rc["noun"]
        card = rc["selected"]
        mb = compat.messagebox
        if card is None:
            mb.showwarning("No card picked",
                           "Pick the %s to read from." % noun)
            return False
        path = self._rc_image_var.get().strip()
        if not path:
            mb.showwarning("No image file",
                           "Pick where the image should be saved (Save to:).")
            return False
        path = os.path.normpath(path)
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            mb.showwarning("Folder not found",
                           "This folder doesn't exist:\n%s" % folder)
            return False
        if os.path.exists(path) and not mb.askyesno(
                "Replace file?",
                "%s already exists.\n\nReplace it with a fresh image of the "
                "card?" % path):
            return False
        if H.destination_is_on(card, folder):
            mb.showwarning(
                "Same drive",
                "That folder is on the very drive you are reading, so the "
                "image would be written into its own source. Pick a folder on "
                "a different drive.")
            return False
        self._rc_close()
        on_read = self.window.cb.get("on_read_card")
        if on_read is not None:
            on_read(card.device_path, path)
        return True

    @rpc
    def rc_cancel(self):
        self._rc_close()
        return True

    def _rc_close(self):
        self._rc = None
        self._rc_seq += 1
        self.set(rc=None)

    # ------------------------------------------------------------------
    def _workers(self):
        """The worker threads this tab may have in flight (tests wait on
        them)."""
        return [t for t in (self._probe_thread, self._drives_thread,
                            self._card_thread, self._stats_thread,
                            self._info_thread, self._rc_thread)
                if t is not None]

    def on_close(self):
        self._stop_dmd_pump()


TAB = ExtractTab
