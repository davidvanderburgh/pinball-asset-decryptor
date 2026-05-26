"""Main window for the unified Pinball Asset Decryptor.

Shape:
  [ Manufacturer ▾ ]                                     [ ☀/☽ ]
  Tabs: Extract | Write | Mod Pack   (tabs gated by capabilities)
  Phase indicators
  Progress bar
  Status row
  Log
"""

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from ..core.config import EXTRACT_PHASES, WRITE_PHASES
from .theme import THEMES, detect_system_theme, platform_font

# PIL lazy-imported on demand for the live DMD preview — keeping the
# import here so a missing Pillow doesn't break the rest of the GUI.
try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False

_SANS_FONT, _MONO_FONT = platform_font()

# _Tooltip used to live here; moved to gui/widgets.py so picker.py can
# also use it without importing main_window (circular).
from .widgets import _Tooltip  # noqa: E402


def _render_pinmame_frame(data, w, h, depth, scale, color):
    """Render a libpinmame RAW DMD frame to an amber-tinted PIL image.

    PinMAME RAW mode hands one byte per pixel where each byte holds a
    brightness value in 0..(2**depth - 1).  We:

      1. Build a per-level RGB LUT (so we don't pay the multiply per
         pixel — there are only ``levels`` distinct shades).
      2. Map the raw bytes through the LUT in one pass into an RGB
         buffer.
      3. ``Image.frombytes`` + ``resize(NEAREST)`` to scale up.
    """
    if not _HAVE_PIL:
        return None
    levels = max(1, (1 << depth) - 1)
    r, g, b = color
    # 256-entry LUT — covers any byte value we might see, clamped to
    # the depth's brightness range.
    lut = bytearray(256 * 3)
    for i in range(256):
        lv = min(i, levels)
        ratio = lv / levels
        lut[3 * i + 0] = int(r * ratio)
        lut[3 * i + 1] = int(g * ratio)
        lut[3 * i + 2] = int(b * ratio)
    n = w * h
    src = data[:n]
    rgb = bytearray(n * 3)
    j = 0
    for px in src:
        k = 3 * px
        rgb[j] = lut[k]
        rgb[j + 1] = lut[k + 1]
        rgb[j + 2] = lut[k + 2]
        j += 3
    img = Image.frombytes("RGB", (w, h), bytes(rgb))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    return img


class MainWindow:
    """Single-window Tk GUI; manufacturer-aware via apply_manufacturer()."""

    def __init__(self, root, app_title, manufacturers,
                 on_manufacturer_change,
                 on_extract, on_extract_cancel,
                 on_write, on_write_cancel,
                 on_export, on_import,
                 on_apply_delta=None,
                 on_recheck_prereqs=None, on_install_prereqs=None,
                 on_back=None,
                 on_theme_change=None, initial_theme=None,
                 on_check_updates=None,
                 initial_fda_acknowledged=False,
                 on_fda_acknowledge=None):
        self.root = root
        self._manufacturers = manufacturers   # list[Manufacturer]
        self._on_manufacturer_change = on_manufacturer_change
        self._on_extract = on_extract
        self._on_extract_cancel = on_extract_cancel
        self._on_write = on_write
        self._on_write_cancel = on_write_cancel
        self._on_apply_delta = on_apply_delta
        self._on_recheck_prereqs = on_recheck_prereqs
        self._on_install_prereqs = on_install_prereqs
        self._on_back = on_back
        self._on_export = on_export
        self._on_import = on_import
        self._on_theme_change = on_theme_change
        self._on_check_updates = on_check_updates
        # macOS FDA banner state.  Persisted in settings.json via
        # ``on_fda_acknowledge`` so the dismissal survives restarts —
        # the previous "always show" behaviour was out of sync with
        # the actual TCC state and felt broken once a user had
        # already granted Full Disk Access in System Settings.  We
        # auto-set this to True on the first successful Direct-SSD
        # run (proof that FDA works); the user can also click the
        # "Hide this notice" link in the banner to dismiss manually.
        self._fda_acknowledged = bool(initial_fda_acknowledged)
        self._on_fda_acknowledge = on_fda_acknowledge
        self._app_title = app_title

        self._current_mfr = None
        self._suppress_mfr_event = False
        # Per-mfr log widgets — created lazily, swapped on mfr select.
        # Each manufacturer keeps its own scrollback so going Back +
        # Forward to the same mfr restores their full log history.
        self._log_widgets = {}    # mfr.key -> tk.Text
        self._log_text = None     # alias for the currently-packed widget

        # Default size picked so the picker fits all 4 current cards
        # (incl. Spooky's 14-game list) without scrolling on a typical
        # 1080p display.  Height bumped in v0.7.11 from 940 → 1060 so
        # the macOS FDA banner doesn't push the log frame below the
        # viewport on the Extract / Write tabs.  minsize bumped to
        # match — when smaller, the scrollable mfr-view (added v0.7.11)
        # lets the user scroll the whole page so nothing is unreachable.
        root.geometry("820x1060")
        root.minsize(720, 700)

        if sys.platform == "win32":
            ico = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "icon.ico")
            if os.path.isfile(ico):
                try:
                    root.iconbitmap(ico)
                except tk.TclError:
                    pass

        self._start_time = None
        self._timer_id = None
        self._current_theme = initial_theme or detect_system_theme()

        # Tk vars
        self.extract_input_var = tk.StringVar()
        self.extract_output_var = tk.StringVar()
        self.write_upd_var = tk.StringVar()
        self.write_assets_var = tk.StringVar()
        self.write_output_var = tk.StringVar()
        # Williams-only: "Use PinMAME runtime capture" toggle on the
        # Extract tab.  When ON, the Extract button kicks off the
        # libpinmame-driven capture pipeline (composed cinematics +
        # audio) instead of the static asset extractor.
        # "Basic extract" — the static ROM asset bitmap scanner.  On
        # by default.  Users with limited disk who only want the
        # PinMAME capture cinematics can untick this.
        self.static_extract_var = tk.BooleanVar(value=True)
        self.capture_mode_var = tk.BooleanVar(value=False)
        # 180s gives the scripted gameplay tour (18-21 moments per
        # rich game) enough time to play through without truncating
        # the final scenes.  Plus ~25s boot/credit/start overhead.
        self.capture_duration_var = tk.StringVar(value="180")
        self.capture_gameplay_var = tk.BooleanVar(value=True)
        # CGC-only: "Generate callouts.csv after Extract" toggle on the
        # Extract tab.  When ON, a successful Extract triggers the
        # transcribe pipeline against the output folder.  Default OFF
        # because the model download (~75 MB) is opt-in.
        self.transcribe_var = tk.BooleanVar(value=False)
        # Companion toggle: when ON (and transcribe is also ON), the
        # transcribe pipeline renames each speech WAV to
        # "<original> - <transcript>.wav".  Write picks up the renamed
        # files via prefix-matching in _diff_assets so the round trip
        # still works.  Default OFF -- some users want to cross-check
        # original names against community sample lists.
        self.transcribe_rename_var = tk.BooleanVar(value=False)
        # Whether the currently-selected extract input is a game whose
        # audio we can export (drives the Auto-transcribe controls +
        # the "Extract audio" phase).  Re-probed on every input change;
        # True when no file is selected yet so the UI isn't pre-hidden.
        self._extract_audio_supported = True

        # JJP-only (capabilities.asset_filters): per-category Extract
        # checkboxes — Graphics / Sounds / File System.  Match the
        # standalone JJP decryptor's defaults: assets on, full
        # filesystem dump off (it's the slow path).  Plumbed into the
        # JJP pipeline as ``extract_graphics`` / ``extract_sounds`` /
        # ``full_dump``.  Hidden for plugins without the capability.
        self.extract_graphics_var = tk.BooleanVar(value=True)
        self.extract_sounds_var = tk.BooleanVar(value=True)
        self.extract_filesystem_var = tk.BooleanVar(value=False)

        # JJP-only (capabilities.direct_ssd): "From ISO / From SSD"
        # radio toggles between the file picker and the physical-drive
        # picker.  Default "iso" so plugins without direct_ssd see no
        # change.  Drive var holds the selected drive's device_path
        # (the value the pipeline accepts); drive_display_var is the
        # combobox's selected label.  Partition override is the
        # optional escape hatch — leave blank to auto-discover.
        self.extract_input_source_var = tk.StringVar(value="iso")
        self.extract_drive_var = tk.StringVar()
        self.extract_drive_display_var = tk.StringVar()
        self.extract_partition_override_var = tk.StringVar()
        self.write_input_source_var = tk.StringVar(value="iso")
        self.write_drive_var = tk.StringVar()
        self.write_drive_display_var = tk.StringVar()
        self.write_partition_override_var = tk.StringVar()
        # Caches of PhysicalDrive — kept in step with the combobox so
        # selecting a label can look up its device_path without
        # re-enumerating.  Refilled by _refresh_drives.
        self._extract_drives_cache = []
        self._write_drives_cache = []

        # Cross-manufacturer auto-detect: when the current mfr doesn't
        # recognise a browsed file but exactly one other mfr does, we
        # store that mfr here so a click on the badge can switch to it.
        self._extract_suggested_mfr = None
        self._write_suggested_mfr = None

        # Per-mfr prereq indicators: name -> dict(label, tooltip, prereq).
        # Rebuilt by reset_prereqs() each time the manufacturer changes.
        self._prereq_indicators = {}

        self._build_ui()
        self._init_phase_steps()
        self._apply_theme(self._current_theme)

        self.extract_input_var.trace_add("write", self._update_extract_badge)
        self.extract_output_var.trace_add("write", self._check_extract_warn)
        self.write_upd_var.trace_add("write", self._update_write_badge)
        self.write_upd_var.trace_add(
            "write", lambda *_: self._update_write_filename())
        self.write_output_var.trace_add(
            "write", lambda *_: self._update_write_filename())
        # Re-scan the Modified Files Preview whenever the assets
        # folder changes, but only if the user is actually looking at
        # the SSD-mode Write tab — otherwise we'd be churning hashing
        # work on every keystroke into the Browse field.
        self.write_assets_var.trace_add(
            "write", lambda *_: self._maybe_rescan_write_preview())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ---- Update-available banner (top of window) ----------------
        # Persistent across picker ↔ working-view switches; only
        # visible once the GitHub update check turns up a newer
        # release.  Lives ABOVE the back/title row so it's
        # impossible to miss regardless of which view is showing.
        # Dismissible per-session via the × button; reappears on
        # next launch if still applicable.
        self._build_update_banner(root)

        # ---- Top bar: Back, title, theme toggle ----------------------
        top = ttk.Frame(root)
        self._top_bar = top  # banner uses this as `before=` anchor
        top.pack(fill=tk.X, padx=10, pady=(8, 0))
        # Back button — hidden until the user has picked a manufacturer.
        self._back_btn = ttk.Button(
            top, text="< Back", width=8,
            command=self._handle_back)
        # not packed yet — show_mfr_view() does that
        self._title_lbl = ttk.Label(
            top, text=self._app_title,
            font=(_SANS_FONT, 13, "bold"))
        self._title_lbl.pack(side=tk.LEFT)
        self._theme_btn = ttk.Button(top, text="", width=3,
                                     command=self._toggle_theme)
        self._theme_btn.pack(side=tk.RIGHT)
        # "Check for updates" button — always visible.  Useful both as
        # a manual override (user wants to check NOW instead of waiting
        # for next launch) and as a dev convenience (lets you exercise
        # the update-banner code path without juggling __version__).
        # Packs second with side=RIGHT, so it sits to the LEFT of the
        # theme toggle.
        self._update_check_btn = ttk.Button(
            top, text="Check for updates",
            command=self._handle_check_updates)
        self._update_check_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ---- Picker view (the entry screen) --------------------------
        from .picker import ManufacturerPicker
        self._picker_view = ManufacturerPicker(
            root,
            manufacturers=self._manufacturers,
            on_select=self._on_picker_select,
            theme_fn=lambda: self._current_theme)
        # Packed in show_picker() — leaving the placement for later so
        # the App can decide the initial view.

        # ---- Manufacturer working view (decryption UI) ---------------
        # Everything below this is parented to _mfr_view so we can hide
        # the whole thing with one pack_forget() and show the picker
        # instead.  Created but not packed; show_mfr_view() does that.
        #
        # As of v0.7.11 the working view lives inside a vertical
        # scrollable canvas so tall content (macOS FDA banner +
        # admin banner + capability matrix + log) can't push the
        # log frame below the visible area on smaller windows.  When
        # the content fits the window, the scrollbar stays hidden;
        # when it doesn't, the bar appears on the right and the
        # user can scroll the whole working view.
        self._mfr_view_wrapper = ttk.Frame(root)
        self._mfr_view_canvas = tk.Canvas(
            self._mfr_view_wrapper,
            highlightthickness=0, borderwidth=0)
        self._mfr_view_scroll = ttk.Scrollbar(
            self._mfr_view_wrapper, orient="vertical",
            command=self._mfr_view_canvas.yview)
        self._mfr_view_canvas.configure(
            yscrollcommand=self._mfr_view_scroll.set)
        self._mfr_view_canvas.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Scrollbar is packed-on-demand by ``_update_mfr_scroll``.
        self._mfr_view = ttk.Frame(self._mfr_view_canvas)
        self._mfr_view_id = self._mfr_view_canvas.create_window(
            (0, 0), window=self._mfr_view, anchor="nw")

        def _update_mfr_scroll(_e=None):
            bbox = self._mfr_view_canvas.bbox("all")
            if bbox is None:
                return
            self._mfr_view_canvas.configure(scrollregion=bbox)
            visible = self._mfr_view_canvas.winfo_height()
            content_h = bbox[3] - bbox[1]
            if content_h > visible + 2:
                self._mfr_view_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                self._mfr_view_scroll.pack_forget()

        self._mfr_view.bind("<Configure>", _update_mfr_scroll)

        def _resize_mfr_view(e):
            # Force the inner canvas-window to be at least as tall as
            # the canvas itself.  Otherwise the inner frame keeps its
            # natural content height, leaving any extra canvas area
            # painted in the canvas's bg — and, more importantly, the
            # log frame (which packs with expand=True) has nothing
            # extra to expand into.  When content is naturally taller
            # than the canvas (small window), keep the content size
            # so scrolling still works.
            inner_h = self._mfr_view.winfo_reqheight()
            self._mfr_view_canvas.itemconfig(
                self._mfr_view_id, width=e.width,
                height=max(e.height, inner_h))
            _update_mfr_scroll()

        self._mfr_view_canvas.bind("<Configure>", _resize_mfr_view)

        # Mouse-wheel scroll the outer view when the pointer is over
        # any non-scrollable region.  The inner log Text widget has
        # its own scrollbar, so we explicitly forward wheel events
        # ONLY when the pointer isn't inside the log frame — keeps
        # log scrolling intuitive when there's a long extraction
        # history to read.
        def _on_mousewheel(event):
            try:
                widget_under = self.root.winfo_containing(
                    event.x_root, event.y_root)
            except Exception:
                widget_under = None
            w = widget_under
            while w is not None:
                if w is getattr(self, "_log_text", None):
                    return  # let the log handle its own wheel
                w = getattr(w, "master", None)
            # Cross-platform wheel: macOS / Windows send delta; X11
            # uses Button-4 / Button-5.
            if event.num == 5 or getattr(event, "delta", 0) < 0:
                self._mfr_view_canvas.yview_scroll(1, "units")
            elif event.num == 4 or getattr(event, "delta", 0) > 0:
                self._mfr_view_canvas.yview_scroll(-1, "units")

        self._mfr_view_canvas.bind_all(
            "<MouseWheel>", _on_mousewheel, add="+")
        self._mfr_view_canvas.bind_all(
            "<Button-4>", _on_mousewheel, add="+")
        self._mfr_view_canvas.bind_all(
            "<Button-5>", _on_mousewheel, add="+")
        mv = self._mfr_view

        # mfr_var stays for compatibility (some helpers read it) — but
        # there's no combobox any more; the title bar shows the choice.
        self.mfr_var = tk.StringVar()

        # Per-manufacturer prerequisite indicators.
        self._prereqs_frame = ttk.LabelFrame(mv, text="Prerequisites")
        self._prereqs_inner = ttk.Frame(self._prereqs_frame)
        self._prereqs_inner.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                 padx=4, pady=4)
        prereq_btns = ttk.Frame(self._prereqs_frame)
        prereq_btns.pack(side=tk.RIGHT, padx=4, pady=4)
        ttk.Button(
            prereq_btns, text="Re-check",
            command=lambda: (self._on_recheck_prereqs()
                             if self._on_recheck_prereqs else None)
        ).pack(side=tk.TOP, fill=tk.X)
        ttk.Button(
            prereq_btns, text="Install Missing",
            command=lambda: (self._on_install_prereqs()
                             if self._on_install_prereqs else None)
        ).pack(side=tk.TOP, fill=tk.X, pady=(2, 0))

        # Tabs
        self._notebook = ttk.Notebook(mv)
        self._notebook.pack(fill=tk.X, expand=False, padx=10, pady=(8, 0))

        self._tab_extract = ttk.Frame(self._notebook)
        self._tab_write = ttk.Frame(self._notebook)
        self._tab_modpack = ttk.Frame(self._notebook)

        self._notebook.add(self._tab_extract, text="  Extract  ")
        self._notebook.add(self._tab_write, text="  Write  ")
        self._notebook.add(self._tab_modpack, text="  Mod Pack  ")

        self._build_extract_tab()
        self._build_write_tab()
        self._build_modpack_tab()

        # Phase indicators + progress bar
        status_frame = ttk.Frame(mv)
        status_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

        self._extract_phases_frame = ttk.Frame(status_frame)
        self._extract_phases_frame.pack(fill=tk.X)
        self._write_phases_frame = ttk.Frame(status_frame)

        self._progress_bar = ttk.Progressbar(status_frame, mode="determinate",
                                             maximum=100)
        self._progress_bar.pack(fill=tk.X, pady=(4, 2))

        status_row = ttk.Frame(status_frame)
        status_row.pack(fill=tk.X)
        self._status_label = ttk.Label(status_row, text="Ready",
                                       font=(_SANS_FONT, 9))
        self._status_label.pack(side=tk.LEFT)
        self._elapsed_label = ttk.Label(status_row, text="",
                                        font=(_SANS_FONT, 9))
        self._elapsed_label.pack(side=tk.RIGHT)

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Log section.  We keep ONE log LabelFrame, but its contents
        # (the Text widget + its scrollbar) are swapped per-manufacturer
        # by _swap_log_widget() so each mfr has its own scrollback.
        self._log_frame = ttk.LabelFrame(mv, text="Log")
        self._log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 8))

    def _build_extract_tab(self):
        f = self._tab_extract
        pad = {"padx": 10, "pady": 4}

        # NOTE: a per-mfr description label used to live here, but the
        # picker page already shows every game the mfr handles, and
        # the prereqs row above the tabs already lists runtime tools,
        # so it was redundant + got clipped when the text was long.

        # JJP-only (capabilities.direct_ssd): "From ISO" / "From SSD"
        # radio toggles between the file picker below and the
        # physical-drive picker frame.  Hidden in apply_manufacturer
        # for plugins without direct_ssd.  Layout mirrors the
        # standalone JJP decryptor so users moving over see the same
        # shape.
        self._extract_source_frame = ttk.Frame(f)
        ttk.Radiobutton(
            self._extract_source_frame, text="From ISO",
            value="iso",
            variable=self.extract_input_source_var,
            command=lambda: self._on_input_source_change("extract"),
        ).pack(side=tk.LEFT, padx=(10, 12))
        ttk.Radiobutton(
            self._extract_source_frame, text="From SSD",
            value="ssd",
            variable=self.extract_input_source_var,
            command=lambda: self._on_input_source_change("extract"),
        ).pack(side=tk.LEFT)

        # ISO file-picker row — shown when source == "iso".
        self._extract_input_row = ttk.Frame(f)
        self._extract_input_lbl = ttk.Label(
            self._extract_input_row, text="Input:", width=14, anchor=tk.W)
        self._extract_input_lbl.pack(side=tk.LEFT)
        ttk.Entry(self._extract_input_row,
                  textvariable=self.extract_input_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._extract_input_row, text="Browse...",
                   command=self._browse_extract_input).pack(
            side=tk.LEFT, padx=(4, 0))
        self._extract_input_row.pack(fill=tk.X, **pad)

        # SSD drive-picker row — shown when source == "ssd".  Created
        # but not packed; _on_input_source_change toggles it in.
        self._extract_drive_row = ttk.Frame(f)
        ttk.Label(self._extract_drive_row,
                  text="Game SSD:", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._extract_drive_combo = ttk.Combobox(
            self._extract_drive_row,
            textvariable=self.extract_drive_display_var,
            state="readonly")
        self._extract_drive_combo.pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._extract_drive_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._on_drive_selected("extract"))
        ttk.Button(self._extract_drive_row, text="Refresh",
                   command=lambda: self._refresh_drives("extract")).pack(
            side=tk.LEFT, padx=(4, 0))

        # We previously surfaced a "Force partition #" entry here, but
        # it spooked users — a numeric override field next to a
        # red-warning panel makes the SSD flow feel risky.  The
        # content-verify loop in DirectSSDDecryptPipeline.\
        # _mount_ssd_windows now tries every Linux candidate in size
        # order, so the auto-pick handles every drive layout we've
        # seen.  If something exotic comes up we can re-expose the
        # override later.

        # Red warning shown only in SSD mode — mirrors the standalone
        # JJP decryptor's prompt.  Pulling an SSD that's still bolted
        # into a powered-on machine risks the host filesystem and the
        # SSD; remind users every time.
        self._extract_ssd_warn = ttk.Label(
            f,
            text="⚠ Remove the SSD from the pinball machine before "
                 "connecting. Always keep the original ISO as a backup.",
            foreground="#f44747",
            font=(_SANS_FONT, 9))

        # Elevation warning — Direct-SSD on Windows needs admin (both
        # Set-Disk and wsl --mount are gated by Windows itself).
        # Designed to be impossible to miss: bold heading, multi-line
        # how-to-fix, contrasting red background.  Shown only when
        # SSD mode is selected AND the app isn't running as admin;
        # the Extract button is *disabled* in that state so users
        # can't kick off a doomed run.
        self._extract_admin_frame = self._build_admin_warning_frame(f)
        # macOS Full Disk Access guidance — analogous warning for the
        # other Direct-SSD-blocking platform constraint.  See the
        # helper for the full explanation.
        self._extract_macos_fda_frame = (
            self._build_macos_fda_warning_frame(f))

        self._extract_badge = ttk.Label(f, text="",
                                        font=(_SANS_FONT, 9, "italic"))
        self._extract_badge.pack(anchor=tk.W, padx=24, pady=(0, 2))
        self._extract_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("extract"))
        self._extract_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("extract", True))
        self._extract_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("extract", False))

        self._extract_output_row_ref = ttk.Frame(f)
        self._extract_output_row_ref.pack(fill=tk.X, **pad)
        ttk.Label(self._extract_output_row_ref,
                  text="Output Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(self._extract_output_row_ref,
                  textvariable=self.extract_output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._extract_output_row_ref, text="Browse...",
                   command=self._browse_extract_output).pack(
            side=tk.LEFT, padx=(4, 0))

        self._extract_warn = ttk.Label(f, text="", foreground="#f44747",
                                       font=(_SANS_FONT, 9))
        self._extract_warn.pack(anchor=tk.W, padx=24)

        # BOF-only callout — explains the custom-format conversion the
        # Extract pipeline does behind the scenes.  Built but not packed;
        # apply_manufacturer() packs it when the user picks BOF and
        # hides it otherwise.  Stands out from the surrounding controls
        # via a yellow background + amber border, matching the "tip"
        # callout convention used elsewhere in the app.
        self._extract_bof_banner = tk.Frame(
            f, bg="#3a3416", padx=12, pady=10,
            highlightbackground="#a08020", highlightthickness=1)
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#ffd966",
            font=(_SANS_FONT, 10, "bold"),
            anchor=tk.W, justify=tk.LEFT,
            text="About BOF Extract",
        ).pack(anchor=tk.W)
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#e8d8a0",
            font=(_SANS_FONT, 9), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "Starting with the April 2026 firmware (Winchester 4/29, "
                "Dune 5/13), BOF ships its games in a custom Godot PCK "
                "format that no public extractor — including GDRE Tools — "
                "can read. Older .fun files use stock Godot and work with "
                "GDRE; this newer format needs the Pinball Asset Decryptor."
            ),
        ).pack(anchor=tk.W, pady=(4, 6))
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#e8d8a0",
            font=(_SANS_FONT, 9), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "During Extract, the app will:\n"
                "   • Decrypt the .fun and pull out the Godot binary\n"
                "   • Patch BOF's custom PCK magic markers back to stock Godot\n"
                "   • Walk BOF's sequential file layout (no traditional directory)\n"
                "   • Decompress fonts from BOF's Zstd \"RSCC\" container\n"
                "   • Decode QOA-compressed audio → standard WAV\n"
                "   • Unwrap textures (GST2 + WebP) → standard WEBP\n"
                "   • Save everything to pck/_EDITABLE ASSETS/, organised "
                "into audio/, images/, video/, and fonts/ subfolders"
            ),
        ).pack(anchor=tk.W, pady=(0, 6))
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#a8e8a0",
            font=(_SANS_FONT, 9, "italic"), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "After Extract, open _EDITABLE ASSETS/ — every audio file "
                "is playable in VLC / Audacity, every texture in any image "
                "viewer. Edit anything, then use the Write tab to repack "
                "your changes back into a new .fun for the machine."
            ),
        ).pack(anchor=tk.W)

        # JJP-only (capabilities.asset_filters): per-category Extract
        # filters.  Mirrors the standalone JJP decryptor: an "Extract:"
        # label followed by Graphics / Sounds / File System
        # checkboxes inline.  Hidden in apply_manufacturer() for
        # plugins without the capability.  Built but not packed.
        self._asset_filters_frame = ttk.Frame(f)
        ttk.Label(
            self._asset_filters_frame, text="Extract:",
            font=(_SANS_FONT, 9)).pack(side=tk.LEFT, padx=(10, 8))
        ttk.Checkbutton(
            self._asset_filters_frame, text="Graphics",
            variable=self.extract_graphics_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            self._asset_filters_frame, text="Sounds",
            variable=self.extract_sounds_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            self._asset_filters_frame, text="File System",
            variable=self.extract_filesystem_var,
        ).pack(side=tk.LEFT, padx=(0, 12))

        # Williams-only: extract-mode checkboxes.  Both hidden in
        # apply_manufacturer() for manufacturers without
        # capabilities.capture (other plugins always run their
        # default extract).
        self._basic_extract_frame = ttk.Frame(f)
        self._basic_extract_check = ttk.Checkbutton(
            self._basic_extract_frame,
            text="Basic extract (raw ROM asset bitmaps + animation MP4s)",
            variable=self.static_extract_var,
            command=self._on_extract_mode_toggle)
        self._basic_extract_check.pack(side=tk.LEFT, padx=(24, 8))

        self._capture_frame = ttk.Frame(f)
        self._capture_check = ttk.Checkbutton(
            self._capture_frame,
            text="Use PinMAME runtime capture (composed cinematics + audio)",
            variable=self.capture_mode_var,
            command=self._on_extract_mode_toggle)
        self._capture_check.pack(side=tk.LEFT, padx=(24, 8))
        ttk.Label(
            self._capture_frame, text="Duration (s):",
            font=(_SANS_FONT, 9)).pack(side=tk.LEFT)
        self._capture_dur_entry = ttk.Entry(
            self._capture_frame, textvariable=self.capture_duration_var,
            width=6)
        self._capture_dur_entry.pack(side=tk.LEFT, padx=(4, 0))
        self._capture_gameplay_check = ttk.Checkbutton(
            self._capture_frame,
            text="Simulate gameplay",
            variable=self.capture_gameplay_var)
        self._capture_gameplay_check.pack(side=tk.LEFT, padx=(12, 0))
        self._capture_help = ttk.Label(
            f, text="",
            font=(_SANS_FONT, 9, "italic"),
            foreground="#888888",
            wraplength=620, justify=tk.LEFT)
        self._capture_help.pack(anchor=tk.W, padx=24, pady=(2, 0))

        # ---- Live DMD preview ------------------------------------
        # While the capture pipeline runs, we show the actual DMD
        # frames PinMAME is rendering — invaluable for "is the game
        # in attract, stuck on ball-search, or actually playing?"
        # diagnostics.  The image label is created here but kept
        # hidden until ``on_dmd_frame`` receives the first frame.
        self._dmd_preview_frame = ttk.Frame(f)
        self._dmd_preview_label = tk.Label(
            self._dmd_preview_frame,
            background="#000000",
            borderwidth=1, relief="solid")
        self._dmd_preview_label.pack(side=tk.LEFT, padx=(24, 8))
        self._dmd_preview_caption = ttk.Label(
            self._dmd_preview_frame,
            text="Live DMD (PinMAME)",
            font=(_SANS_FONT, 9, "italic"),
            foreground="#888888")
        self._dmd_preview_caption.pack(side=tk.LEFT, padx=(0, 0),
                                       anchor="s", pady=(0, 4))
        # Latest frame slot — written from the libpinmame display
        # thread (no GIL contention concerns since dict/tuple writes
        # are atomic in CPython).  The Tk after()-pump reads it.
        self._dmd_latest = None      # (data, w, h, depth) or None
        self._dmd_preview_tkimage = None  # PhotoImage retained as ref
        self._dmd_preview_visible = False
        self._dmd_preview_pump_id = None

        # ---- Diagnostic switch matrix (Williams capture mode) ----
        # When PinMAME is running, expose a clickable grid of every
        # defined switch in the active game.  Lets the user manually
        # press switches to see how the ROM responds (useful when
        # the scripted playthrough doesn't trigger expected cinemas).
        self._switch_matrix_frame = ttk.LabelFrame(
            f, text="Switch matrix (click to press)")
        # Wrap the grid in a scrollable Canvas so games with 60+
        # switches (ToM, STTNG, etc.) work without forcing a wide
        # window.  Vertical scrollbar appears on demand.
        self._switch_matrix_canvas = tk.Canvas(
            self._switch_matrix_frame,
            height=140, highlightthickness=0, borderwidth=0)
        self._switch_matrix_scroll = ttk.Scrollbar(
            self._switch_matrix_frame, orient="vertical",
            command=self._switch_matrix_canvas.yview)
        self._switch_matrix_canvas.configure(
            yscrollcommand=self._switch_matrix_scroll.set)
        self._switch_matrix_canvas.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._switch_matrix_inner = tk.Frame(self._switch_matrix_canvas)
        self._switch_matrix_inner_id = (
            self._switch_matrix_canvas.create_window(
                (0, 0), window=self._switch_matrix_inner, anchor="nw"))

        def _update_matrix_scroll(_e=None):
            bbox = self._switch_matrix_canvas.bbox("all")
            if bbox is None:
                return
            self._switch_matrix_canvas.configure(scrollregion=bbox)
            visible = self._switch_matrix_canvas.winfo_height()
            content_h = bbox[3] - bbox[1]
            if content_h > visible + 2:
                self._switch_matrix_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                self._switch_matrix_scroll.pack_forget()

        self._switch_matrix_inner.bind(
            "<Configure>", _update_matrix_scroll)
        self._switch_matrix_canvas.bind(
            "<Configure>",
            lambda e: self._switch_matrix_canvas.itemconfig(
                self._switch_matrix_inner_id, width=e.width))
        # ``_manual_press_fn`` is set by ``on_capture_ready`` when
        # PinMAME boots; the matrix grid uses it for each button.
        self._manual_press_fn = None
        self._switch_matrix_buttons = []

        # Transcribe checkbox — packed only when the active manufacturer
        # has capabilities.transcribe (currently just CGC).  When ON,
        # Extract chains the transcribe pipeline against the output
        # folder, emitting callouts.csv next to the WAVs.  Mirrors
        # the capture-mode toggle pattern used by Williams.
        self._transcribe_frame = ttk.Frame(f)
        self._transcribe_check = ttk.Checkbutton(
            self._transcribe_frame,
            text="Auto-transcribe samples to callouts.csv",
            variable=self.transcribe_var,
            command=self._on_transcribe_toggle)
        self._transcribe_check.pack(side=tk.LEFT, padx=(24, 8))
        self._transcribe_rename_check = ttk.Checkbutton(
            self._transcribe_frame,
            text="...and rename WAVs using transcripts",
            variable=self.transcribe_rename_var)
        self._transcribe_rename_check.pack(side=tk.LEFT, padx=(12, 0))
        # Greyed-out until the first checkbox is on -- rename only
        # makes sense as a chained step after the CSV exists.
        self._transcribe_rename_check.state(["disabled"])

        btn_row = ttk.Frame(f); btn_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self._extract_btn = ttk.Button(btn_row, text="Extract",
                                       command=self._on_extract)
        self._extract_btn.pack(side=tk.LEFT)
        self._extract_cancel_btn = ttk.Button(btn_row, text="Cancel",
                                              command=self._on_extract_cancel,
                                              state=tk.DISABLED)
        self._extract_cancel_btn.pack(side=tk.LEFT, padx=(6, 0))

    def _build_write_tab(self):
        f = self._tab_write
        pad = {"padx": 10, "pady": 4}

        ttk.Label(
            f,
            text="Re-pack modified assets into an installable update file.",
            font=(_SANS_FONT, 9, "italic")).pack(anchor=tk.W, **pad)

        # Write-destination toggle (hidden for plugins without
        # direct_ssd).  Action-oriented language here — writes have
        # a destination, not a source, so "Build USB ISO" /
        # "Write to SSD" reads more naturally than "From ISO" /
        # "From SSD".  Mirrors the standalone JJP decryptor.
        self._write_source_frame = ttk.Frame(f)
        ttk.Radiobutton(
            self._write_source_frame, text="Build USB ISO",
            value="iso",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        ).pack(side=tk.LEFT, padx=(10, 12))
        ttk.Radiobutton(
            self._write_source_frame, text="Write to SSD",
            value="ssd",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        ).pack(side=tk.LEFT)

        # ISO original file row.
        self._write_upd_row = ttk.Frame(f)
        self._write_original_lbl = ttk.Label(
            self._write_upd_row, text="Original:", width=16, anchor=tk.W)
        self._write_original_lbl.pack(side=tk.LEFT)
        ttk.Entry(self._write_upd_row, textvariable=self.write_upd_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_upd_row, text="Browse...",
                   command=self._browse_write_upd).pack(
            side=tk.LEFT, padx=(4, 0))
        self._write_upd_row.pack(fill=tk.X, **pad)

        # SSD drive picker.
        self._write_drive_row = ttk.Frame(f)
        ttk.Label(self._write_drive_row,
                  text="Game SSD:", width=16, anchor=tk.W).pack(side=tk.LEFT)
        self._write_drive_combo = ttk.Combobox(
            self._write_drive_row,
            textvariable=self.write_drive_display_var,
            state="readonly")
        self._write_drive_combo.pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._write_drive_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._on_drive_selected("write"))
        ttk.Button(self._write_drive_row, text="Refresh",
                   command=lambda: self._refresh_drives("write")).pack(
            side=tk.LEFT, padx=(4, 0))

        # See the extract tab for why the "Force partition #" field
        # is intentionally absent.  Same content-verify auto-pick.

        # Red SSD-mode warning (write is even more dangerous than
        # read since changes go straight to the SSD).
        self._write_ssd_warn = ttk.Label(
            f,
            text="⚠ Remove the SSD from the pinball machine before "
                 "connecting. Always keep the original ISO as a backup.",
            foreground="#f44747",
            font=(_SANS_FONT, 9))

        # Same elevation warning as Extract — see comments there.
        self._write_admin_frame = self._build_admin_warning_frame(f)
        # Same macOS FDA warning as Extract.
        self._write_macos_fda_frame = (
            self._build_macos_fda_warning_frame(f))

        # Per-mode description that swaps text when the radio flips.
        # In ISO mode it explains the USB-install flow; in SSD mode
        # it spells out the in-place encrypt + audio trim/pad
        # behaviour the JJP standalone called out specifically.  This
        # is the kind of cue users read before clicking the button.
        self._write_desc = ttk.Label(
            f,
            text="Re-pack modified assets into an installable update file.",
            foreground="#888888",
            font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        self._write_badge = ttk.Label(f, text="",
                                      font=(_SANS_FONT, 9, "italic"))
        self._write_badge.pack(anchor=tk.W, padx=26, pady=(0, 2))
        self._write_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("write"))
        self._write_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("write", True))
        self._write_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("write", False))

        self._write_assets_row_ref = ttk.Frame(f)
        self._write_assets_row_ref.pack(fill=tk.X, **pad)
        ttk.Label(self._write_assets_row_ref,
                  text="Modified Assets:", width=16, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(self._write_assets_row_ref,
                  textvariable=self.write_assets_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_assets_row_ref, text="Browse...",
                   command=self._browse_write_assets).pack(
            side=tk.LEFT, padx=(4, 0))

        # Editable-folder hint — appears as a subtle italic line below
        # the Modified Assets row.  For BOF May code the Extract step
        # creates a pck/_EDITABLE ASSETS/ folder with WAV / WEBP / OGV
        # / TTF files that mirror the imported binaries; editing those
        # is the main modding workflow.  The label is informational,
        # no event bindings — it's just a signpost so users don't
        # miss the folder (which would otherwise be easy to overlook
        # deep inside the asset tree).
        self._write_editable_hint = ttk.Label(
            f,
            text=("Tip: edit your audio (.wav), images (.webp), and video (.ogv) "
                  "files in pck/_EDITABLE ASSETS/ inside your Modified Assets "
                  "folder. Write auto-detects changes there and re-encodes them."),
            foreground="#888888",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        self._write_editable_hint.pack(anchor=tk.W, padx=26, pady=(0, 4))

        self._write_output_row_ref = ttk.Frame(f)
        self._write_output_row_ref.pack(fill=tk.X, **pad)
        ttk.Label(self._write_output_row_ref,
                  text="Output Folder:", width=16, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(self._write_output_row_ref,
                  textvariable=self.write_output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_output_row_ref, text="Browse...",
                   command=self._browse_write_output).pack(
            side=tk.LEFT, padx=(4, 0))

        self._write_filename_lbl = ttk.Label(f, text="",
                                             font=(_SANS_FONT, 9, "italic"))
        self._write_filename_lbl.pack(anchor=tk.W, padx=26)

        # JJP Direct-SSD-only: "Modified Files Preview" — same shape
        # as the standalone JJP decryptor.  Walks the assets folder
        # comparing each file's MD5 against the .checksums.md5 the
        # Extract phase emitted; anything that doesn't match shows up
        # as "Modified".  Gives users a sanity check before they
        # click Apply Modifications and commit changes to a real SSD.
        # Hidden by apply_manufacturer() for plugins without
        # direct_ssd; populated by _scan_write_preview() on tab show.
        self._write_preview_frame = ttk.LabelFrame(
            f, text=" Modified Files Preview ", padding=4)
        # Pack-managed by apply_manufacturer + _on_input_source_change.

        # Refresh toolbar — when the user edits assets in another
        # window while this app is open, the preview goes stale.
        # An explicit button is cheaper than file-watching and gives
        # the user direct control.  Also useful when the user
        # changes the assets folder textbox and wants to re-scan
        # without flipping tabs.
        preview_toolbar = ttk.Frame(self._write_preview_frame)
        preview_toolbar.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._write_preview_refresh_btn = ttk.Button(
            preview_toolbar, text="🔄  Refresh",
            command=self._scan_write_preview)
        self._write_preview_refresh_btn.pack(side=tk.RIGHT)

        preview_inner = ttk.Frame(self._write_preview_frame)
        preview_inner.pack(fill=tk.BOTH, expand=True)

        self._write_preview_tree = ttk.Treeview(
            preview_inner, columns=("type", "status"),
            height=6, selectmode="browse")
        self._write_preview_tree.heading("#0", text="File", anchor=tk.W)
        self._write_preview_tree.heading(
            "type", text="Type", anchor=tk.W)
        self._write_preview_tree.heading(
            "status", text="Status", anchor=tk.W)
        self._write_preview_tree.column(
            "#0", width=400, minwidth=200)
        self._write_preview_tree.column(
            "type", width=60, minwidth=40)
        self._write_preview_tree.column(
            "status", width=200, minwidth=100)
        preview_scroll = ttk.Scrollbar(
            preview_inner, orient=tk.VERTICAL,
            command=self._write_preview_tree.yview)
        self._write_preview_tree.configure(
            yscrollcommand=preview_scroll.set)
        preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._write_preview_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Placeholder shown when the tree is empty (no scan yet, or
        # scan returned no changes).  Floats centred on top of the
        # tree via .place; the scan code shows/hides it.
        self._write_preview_empty = ttk.Label(
            preview_inner,
            text="Switch to this tab to scan for modified files",
            foreground="#888888",
            anchor=tk.CENTER, justify=tk.CENTER)
        self._write_preview_empty.place(
            relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Bump-counter to invalidate in-flight scans when the user
        # changes the assets folder before a previous scan finishes.
        self._write_preview_scan_id = 0

        btn_row = ttk.Frame(f); btn_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self._write_btn = ttk.Button(btn_row, text="Build update",
                                     command=self._on_write)
        self._write_btn.pack(side=tk.LEFT)
        self._write_cancel_btn = ttk.Button(btn_row, text="Cancel",
                                            command=self._on_write_cancel,
                                            state=tk.DISABLED)
        self._write_cancel_btn.pack(side=tk.LEFT, padx=(6, 0))

        # Apply-delta — gated by capability flag in apply_manufacturer().
        self._delta_frame = ttk.LabelFrame(
            f, text="Optional: Apply Delta on Top")
        ttk.Label(
            self._delta_frame,
            text="Layer a delta update on top of the extracted assets before "
            "rebuilding.  Files in the delta overwrite or get added on top of "
            "your assets folder.",
            font=(_SANS_FONT, 9), justify=tk.LEFT, wraplength=600,
        ).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(self._delta_frame, text="Apply Delta...",
                   command=lambda: self._on_apply_delta() if self._on_apply_delta else None
                   ).pack(anchor=tk.W, padx=8, pady=(2, 6))

        # Install instructions — populated per manufacturer.
        self._install_frame = ttk.LabelFrame(f, text="How to Install")
        self._install_lbl = ttk.Label(
            self._install_frame, text="", font=(_SANS_FONT, 9),
            justify=tk.LEFT, wraplength=600)
        self._install_lbl.pack(anchor=tk.W, padx=8, pady=6)

    def _build_modpack_tab(self):
        f = self._tab_modpack
        pad = {"padx": 10, "pady": 6}

        ttk.Label(f,
                  text="Share or apply mod packs — zips containing only your "
                  "modified files.",
                  font=(_SANS_FONT, 9, "italic")).pack(anchor=tk.W, **pad)

        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row, text="Mod Folder:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row, textvariable=self.write_assets_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_write_assets).pack(
            side=tk.LEFT, padx=(4, 0))
        ttk.Label(f, text="(shared with the Write tab's Modified Assets path)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=8)

        export_frame = ttk.LabelFrame(f, text="Export Mod Pack")
        export_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(export_frame,
                  text="Create a zip of only your modified files to share.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(export_frame, text="Export Mod Pack...",
                   command=self._on_export).pack(
            anchor=tk.W, padx=8, pady=(2, 6))

        import_frame = ttk.LabelFrame(f, text="Import Mod Pack")
        import_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(import_frame,
                  text="Apply a mod pack zip from another user.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(import_frame, text="Import Mod Pack...",
                   command=self._on_import).pack(
            anchor=tk.W, padx=8, pady=(2, 6))

    def _build_phase_steps(self, parent, phases, mode):
        labels = []
        for name in phases:
            lbl = ttk.Label(parent, text=f"○ {name}", font=(_SANS_FONT, 8))
            lbl.pack(side=tk.LEFT, padx=(0, 12))
            labels.append(lbl)
        if mode == "extract":
            self._extract_phase_labels = labels
        else:
            self._write_phase_labels = labels

    def _init_phase_steps(self):
        # Initial labels — apply_manufacturer rebuilds them per-mfr later.
        self._extract_phases = tuple(EXTRACT_PHASES)
        self._write_phases = tuple(WRITE_PHASES)
        self._build_phase_steps(self._extract_phases_frame,
                                self._extract_phases, "extract")
        self._build_phase_steps(self._write_phases_frame,
                                self._write_phases, "write")

    def _rebuild_phase_steps(self, extract_phases, write_phases):
        """Tear down + rebuild the phase indicator widgets when the
        active manufacturer's phase set changes."""
        self._extract_phases = tuple(extract_phases)
        self._write_phases = tuple(write_phases)
        for w in self._extract_phases_frame.winfo_children():
            w.destroy()
        for w in self._write_phases_frame.winfo_children():
            w.destroy()
        self._build_phase_steps(self._extract_phases_frame,
                                self._extract_phases, "extract")
        self._build_phase_steps(self._write_phases_frame,
                                self._write_phases, "write")

    def _on_tab_changed(self, _event=None):
        idx = self._notebook.index(self._notebook.select())
        tab_id = self._notebook.tabs()[idx]
        text = self._notebook.tab(tab_id, "text").strip()
        if text == "Write":
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack(fill=tk.X, before=self._progress_bar)
            # When the Write tab is selected on a Direct-SSD plugin in
            # SSD mode, auto-scan the assets folder so the preview is
            # populated by the time the user looks at it.  The scan
            # itself is no-op when the folder isn't set yet, so this
            # is safe even pre-Decrypt.
            mfr = self._current_mfr
            if (mfr is not None
                    and mfr.capabilities.direct_ssd
                    and self.write_input_source_var.get() == "ssd"):
                self._scan_write_preview()
        else:
            self._write_phases_frame.pack_forget()
            self._extract_phases_frame.pack(
                fill=tk.X, before=self._progress_bar)

    # ------------------------------------------------------------------
    # View navigation (picker <-> manufacturer working view)
    # ------------------------------------------------------------------

    def show_picker(self):
        """Display the manufacturer picker and hide the working view."""
        # The scrollable wrapper, not the inner frame, is what's
        # actually packed into the window — un-pack the wrapper so
        # both the canvas and its (sometimes-packed) scrollbar
        # disappear together.
        self._mfr_view_wrapper.pack_forget()
        self._back_btn.pack_forget()
        # Hide the app-title label entirely — the window title bar
        # already says "Pinball Asset Decryptor" so showing it again in
        # the body is just noise.  The picker has its own internal
        # "Choose a manufacturer" header.
        self._title_lbl.pack_forget()
        self._picker_view.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

    def show_mfr_view(self):
        """Display the working view for the currently-selected mfr."""
        self._picker_view.pack_forget()
        # Pack Back left of the title, then re-pack title so it sits
        # to the right of the Back button.
        self._back_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._title_lbl.pack_forget()
        self._title_lbl.pack(side=tk.LEFT)
        self._mfr_view_wrapper.pack(fill=tk.BOTH, expand=True)

    def set_back_enabled(self, enabled):
        """Enable / disable the Back button — called by App while a
        pipeline is running so the user can't navigate away mid-extract."""
        self._back_btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _on_picker_select(self, mfr):
        # Forward to the App; it'll call apply_manufacturer + show_mfr_view.
        if self._on_manufacturer_change:
            self._on_manufacturer_change(mfr)

    def _handle_back(self):
        if self._on_back:
            self._on_back()
        else:
            self.show_picker()

    # ------------------------------------------------------------------
    # Per-manufacturer log widgets
    # ------------------------------------------------------------------

    def _swap_log_widget(self, mfr):
        """Show *mfr*'s log widget; create it on first access."""
        for w in self._log_frame.winfo_children():
            w.pack_forget()

        bundle = self._log_widgets.get(mfr.key)
        if bundle is None:
            text = tk.Text(self._log_frame, wrap=tk.WORD,
                           font=(_MONO_FONT, 9), state=tk.DISABLED,
                           height=12)
            scroll = ttk.Scrollbar(self._log_frame, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            self._apply_log_theme(text)
            bundle = {"text": text, "scroll": scroll}
            self._log_widgets[mfr.key] = bundle

        bundle["scroll"].pack(side=tk.RIGHT, fill=tk.Y)
        bundle["text"].pack(fill=tk.BOTH, expand=True)
        self._log_text = bundle["text"]  # alias for append_log/append_log_link

    def _apply_log_theme(self, text_widget):
        c = THEMES[self._current_theme]
        text_widget.configure(
            background=c["field_bg"], foreground=c["fg"],
            insertbackground=c["fg"], selectbackground=c["select_bg"])
        text_widget.tag_configure("info", foreground=c["fg"])
        text_widget.tag_configure("success", foreground=c["success"])
        text_widget.tag_configure("error", foreground=c["error"])
        text_widget.tag_configure("ts", foreground=c["timestamp"])
        text_widget.tag_configure("link", foreground=c["link"])

    # ------------------------------------------------------------------
    # Manufacturer switching
    # ------------------------------------------------------------------

    def apply_manufacturer(self, mfr):
        """Reconfigure the UI for *mfr*.  Called on initial load + on switch."""
        self._current_mfr = mfr
        caps = mfr.capabilities
        # Reset audio-export support to the optimistic default; the
        # extract-badge refresh later in this method re-probes it for
        # the actual selected file.
        self._extract_audio_supported = True

        self._suppress_mfr_event = True
        self.mfr_var.set(mfr.display)
        self._suppress_mfr_event = False

        # Title bar shows just the mfr name (window title bar already
        # has the app name).
        self._title_lbl.configure(text=mfr.display)

        # Per-mfr phase indicators (defaults to core EXTRACT/WRITE_PHASES).
        self._rebuild_phase_steps(mfr.extract_phases, mfr.write_phases)

        # Per-mfr prereq indicators - start in "checking" state.  The
        # App's worker thread fills in actual results via
        # set_prereq_result() shortly after.
        self.reset_prereqs(mfr.prerequisites)

        # Per-mfr log: each mfr keeps its own scrollback across switches.
        self._swap_log_widget(mfr)

        # Make sure the working view is visible (and the picker isn't).
        self.show_mfr_view()

        # Per-format label phrasing (e.g. ".upd:" vs "Input:")
        primary_ext = (mfr.input_spec.extensions[0]
                       if mfr.input_spec.extensions else "file")
        self._extract_input_lbl.configure(
            text=f"{primary_ext}:" if primary_ext.startswith(".") else "Input:")
        self._write_original_lbl.configure(
            text=f"Original {primary_ext}:" if primary_ext.startswith(".")
                 else "Original:")

        # Show/hide tabs by capability.
        self._configure_tab("Write", caps.write)
        self._configure_tab("Mod Pack", caps.modpack)

        # BOF-only Extract callout — pack just below the Extract tab's
        # warning label so users see it before they hit Extract.  Other
        # manufacturers don't need this preamble; their extracts use
        # standard tools (or none at all).  Checking mfr.key directly is
        # OK here because the banner copy is BOF-specific (mentions Dune
        # / Winchester / Labyrinth by name, references "GBOF" magic,
        # etc.); promoting this to a generic capability would mean
        # plumbing per-plugin banner text through the manifest, more
        # surface area for one banner.
        if mfr.key == "bof":
            self._extract_bof_banner.pack(
                fill=tk.X, padx=10, pady=(6, 6),
                after=self._extract_warn)
        else:
            self._extract_bof_banner.pack_forget()

        # JJP (or any future plugin with caps.direct_ssd) gets an extra
        # "From ISO / From SSD" radio row above the input rows on both
        # the Extract and Write tabs.  Everyone else: reset the source
        # to "iso" and hide the radio + the SSD-only frames.
        if caps.direct_ssd:
            self._extract_source_frame.pack(
                fill=tk.X, padx=10, pady=(6, 0),
                before=self._extract_input_row)
            self._write_source_frame.pack(
                fill=tk.X, padx=10, pady=(6, 0),
                before=self._write_upd_row)
            # Re-apply whichever source the user last had selected so
            # the right rows are visible.
            self._on_input_source_change("extract")
            self._on_input_source_change("write")
        else:
            self._extract_source_frame.pack_forget()
            self._write_source_frame.pack_forget()
            self.extract_input_source_var.set("iso")
            self.write_input_source_var.set("iso")
            # Force the ISO layout in case we're switching FROM a
            # direct_ssd plugin TO one without it.
            self._extract_drive_row.pack_forget()
            self._extract_ssd_warn.pack_forget()
            self._extract_admin_frame.pack_forget()
            self._extract_macos_fda_frame.pack_forget()
            self._write_drive_row.pack_forget()
            self._write_ssd_warn.pack_forget()
            self._write_admin_frame.pack_forget()
            self._write_macos_fda_frame.pack_forget()
            # The per-mode description is JJP-specific; hide it for
            # plugins whose Write tab is the ISO-build flow.
            self._write_desc.pack_forget()
            # Modified Files Preview — JJP gets it in SSD mode (handled
            # in the direct_ssd branch above); BOF gets it always so
            # modders can see exactly which files they've edited since
            # Extract before hitting Write.  Other plugins don't show
            # the tree.
            if mfr.key == "bof":
                self._write_preview_frame.pack(
                    fill=tk.BOTH, expand=True, padx=10, pady=(4, 4),
                    before=self._write_filename_lbl)
                # Kick a scan so users see the tree populated when they
                # switch tabs.  Has no effect if the assets folder
                # isn't set yet — the scan will re-fire when the
                # textbox is filled in.
                self._scan_write_preview()
            else:
                self._write_preview_frame.pack_forget()
            # Restore the default "Build update" button label too.
            self._write_btn.configure(text="Build update")
            # Make sure the ISO rows are visible — _on_input_source_change
            # would unpack/repack them, but a non-direct_ssd plugin may
            # have inherited an unpacked state from a prior switch.
            try:
                self._extract_input_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
            except tk.TclError:
                pass
            try:
                self._write_upd_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_assets_row())
            except tk.TclError:
                pass
            if self._write_output_row_ref:
                self._write_output_row_ref.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_filename_lbl)

        # Show/hide the per-category Extract filters (JJP).  Packed
        # just below the output-folder warning so it sits above the
        # phase indicator — same shape as the standalone JJP
        # decryptor.  Plugins without the capability never see it.
        if caps.asset_filters:
            self._asset_filters_frame.pack(
                fill=tk.X, padx=10, pady=(4, 0))
        else:
            self._asset_filters_frame.pack_forget()

        # Show/hide the Williams capture toggles on the Extract tab.
        if caps.capture:
            self._basic_extract_frame.pack(fill=tk.X, padx=10, pady=(6, 0))
            self._capture_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
            self._update_capture_help_text()
            # Mount the DMD preview placeholder so it's ready to
            # surface as soon as PinMAME emits the first frame.
            self._dmd_preview_frame.pack(fill=tk.X, padx=10, pady=(4, 0))
            # Switch matrix is mounted on capture_ready (after the
            # active script is known).
        else:
            self._basic_extract_frame.pack_forget()
            self._capture_frame.pack_forget()
            self._capture_help.configure(text="")
            self.capture_mode_var.set(False)
            # Restore basic-extract default for non-Williams plugins
            # (they always run their normal extract).
            self.static_extract_var.set(True)
            self._dmd_preview_frame.pack_forget()
            self._stop_dmd_preview_pump()
            self._switch_matrix_frame.pack_forget()
            self._manual_press_fn = None

        # Show/hide the auto-transcribe checkboxes.  They build a
        # callouts.csv from the extracted WAVs — and only the basic/
        # static extract emits standalone WAVs, so for capture-capable
        # plugins they sit under "Basic extract" and track it.
        self._update_transcribe_visibility()

        # Show/hide apply-delta + install help inside Write tab
        if caps.apply_delta:
            self._delta_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        else:
            self._delta_frame.pack_forget()

        install = mfr.write_install_help()
        if install and caps.write:
            self._install_lbl.configure(text=install)
            self._install_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        else:
            self._install_frame.pack_forget()

        # Refresh detect badges (file might already be selected from
        # the previous manufacturer's settings — unusual but possible).
        self._update_extract_badge()
        self._update_write_badge()

        # If we're entering a direct_ssd plugin in SSD mode without
        # admin, make sure the Extract / Apply buttons are disabled.
        self._refresh_ssd_run_buttons()

    def _on_extract_mode_toggle(self):
        """Either Basic-extract or Capture checkbox toggled."""
        self._update_capture_help_text()
        self._refresh_extract_phases()
        # Transcribe is only meaningful when the basic extract runs.
        self._update_transcribe_visibility()

    def _refresh_extract_phases(self):
        """Rebuild the extract phase indicator for the current extract
        mode and the detected game's audio-export support.

        The Basic-extract and Capture checkboxes are independent —
        four states matter:

          * basic ON,  capture ON  → combined phases (static + capture)
          * basic ON,  capture OFF → static-only (default)
          * basic OFF, capture ON  → capture-only (no static)
          * basic OFF, capture OFF → nothing to do; warn but allow
                                     the toggle so the user can fix it

        On top of that, the dedicated DCS "Extract audio" phase is
        dropped for games whose audio we can't export (pre-DCS).
        """
        if self._current_mfr is None:
            return
        mfr = self._current_mfr
        # SSD-mode swap: when the source radio is on "ssd", the
        # Direct-SSD pipeline skips the ISO extract/build phases.
        # Same logic for write below.
        extract_ssd = (mfr.capabilities.direct_ssd
                       and self.extract_input_source_var.get() == "ssd")
        write_ssd = (mfr.capabilities.direct_ssd
                     and self.write_input_source_var.get() == "ssd")

        if extract_ssd and mfr.direct_ssd_extract_phases:
            phases = mfr.direct_ssd_extract_phases
        else:
            basic = self.static_extract_var.get()
            capture = (self.capture_mode_var.get()
                       and mfr.capabilities.capture)
            if basic and capture:
                phases = mfr.combined_phases or mfr.extract_phases
            elif capture and not basic:
                phases = mfr.capture_phases or mfr.extract_phases
            else:  # basic only, or neither (treated as basic for display)
                phases = mfr.extract_phases
            if not self._extract_audio_supported:
                phases = tuple(p for p in phases if p != "Extract audio")

        if write_ssd and mfr.direct_ssd_write_phases:
            wphases = mfr.direct_ssd_write_phases
        else:
            wphases = mfr.write_phases
        self._rebuild_phase_steps(phases, wphases)

    # Back-compat shim — older code paths may still reference the
    # original toggle name.
    _on_capture_toggle = _on_extract_mode_toggle

    def _on_transcribe_toggle(self):
        """Enable / disable the rename checkbox when transcribe flips.

        The rename pass depends on the transcripts produced by the
        transcribe pass, so it's only meaningful as a child of the
        first checkbox.  When transcribe is unticked we also clear
        the rename flag so a re-tick doesn't carry stale state.
        """
        if self.transcribe_var.get():
            self._transcribe_rename_check.state(["!disabled"])
        else:
            self._transcribe_rename_check.state(["disabled"])
            self.transcribe_rename_var.set(False)

    def _update_transcribe_visibility(self):
        """Show the auto-transcribe checkboxes only when a transcribable
        extract will actually run.

        Three conditions must all hold:
          * the manufacturer supports transcribe at all;
          * the selected game's audio is exportable (pre-DCS Williams
            titles have none — see _refresh_extract_audio_support);
          * standalone WAVs will be produced — only the basic/static
            extract emits those, so for capture-capable plugins the
            checkboxes sit under "Basic extract" and track it.

        Plugins without a Basic-extract toggle (CGC) always pass the
        third condition.
        """
        if self._current_mfr is None:
            return
        caps = self._current_mfr.capabilities
        show = (caps.transcribe and self._extract_audio_supported
                and (not caps.capture or self.static_extract_var.get()))
        if not show:
            self._transcribe_frame.pack_forget()
            # Hidden means it won't run — don't let a stale tick chain
            # transcribe onto an output that has no WAVs.
            self.transcribe_var.set(False)
            self.transcribe_rename_var.set(False)
            return
        if caps.capture:
            # Sit directly below the "Basic extract" checkbox.
            self._transcribe_frame.pack(
                fill=tk.X, padx=10, pady=(2, 0),
                after=self._basic_extract_frame)
        else:
            self._transcribe_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
        # Keep the rename checkbox's enabled state in sync.
        self._on_transcribe_toggle()

    def _update_capture_help_text(self):
        basic = self.static_extract_var.get()
        capture = self.capture_mode_var.get()
        if basic and capture:
            self._capture_help.configure(text=(
                "Combined: runs the basic ROM asset extract (sprites, "
                "fonts, splash bitmaps, animation MP4s) AND the "
                "PinMAME runtime capture (per-scene cinematics with "
                "synced DCS audio) into the same output folder.  "
                "Capture requires libpinmame.dll installed.\n\n"
                "\"Simulate gameplay\" (recommended ON): drives "
                "coin + Start + Launch + the per-game scripted shot "
                "sequences (Big-O-Beam, Stroke of Luck, multiball, "
                "etc.) so the game actually enters play.  OFF = "
                "attract-mode only — leaves PinMAME idle, capturing "
                "just the attract reel."))
        elif capture and not basic:
            self._capture_help.configure(text=(
                "Capture only: PinMAME runtime capture without the "
                "static ROM asset extract.  Output is just the "
                "per-scene cinematics + DCS audio.  Faster + uses "
                "less disk than the combined run, useful when you "
                "already have the static assets or only want the "
                "live cinematics."))
        elif basic and not capture:
            self._capture_help.configure(text=(
                "Basic only: scans the ROM for raw asset bitmaps "
                "(sprites, font glyphs, splash screens, paired "
                "4-shade composites).  Tick \"Use PinMAME\" too to "
                "ALSO record live gameplay cinematics."))
        else:
            self._capture_help.configure(
                text="Tick at least one box above to run an extract.",
                foreground="#f44747")
            return
        # Restore normal help color (the "neither" branch sets red).
        self._capture_help.configure(foreground="#888888")

    # ------------------------------------------------------------------
    # Live DMD preview (Williams capture mode)
    # ------------------------------------------------------------------

    # WPC DMDs are 128x32 — too tiny to read on a modern display.  This
    # is the per-dot scale we render at.  4 = ~512x128 image, big
    # enough to read 5-pixel-tall font glyphs.
    _DMD_PREVIEW_SCALE = 4
    _DMD_AMBER = (255, 130, 0)   # match the orange we use elsewhere

    def on_dmd_frame(self, data, width, height, depth):
        """Receive a live DMD frame from the capture thread.

        Called from libpinmame's display callback on the C side's
        thread — MUST be quick and MUST NOT touch Tk widgets here.
        We just stash the latest frame; the Tk-after pump renders it.
        """
        # Tuple assignment is atomic in CPython, so concurrent reader
        # always sees a coherent slot.
        self._dmd_latest = (data, width, height, depth)

    def reset_dmd_preview(self):
        """Forget the previous capture's last frame + start the pump.

        Called by app.py right before a new capture run.
        """
        self._dmd_latest = None
        if _HAVE_PIL:
            self._start_dmd_preview_pump()

    def _start_dmd_preview_pump(self):
        if self._dmd_preview_pump_id is not None:
            return
        # 33ms ≈ 30 fps redraw — generous; the underlying capture
        # callback is already throttled to ~20 fps so we'll mostly
        # be repainting the same image.
        self._dmd_preview_pump_id = self.root.after(
            33, self._pump_dmd_preview)

    def _stop_dmd_preview_pump(self):
        if self._dmd_preview_pump_id is not None:
            try:
                self.root.after_cancel(self._dmd_preview_pump_id)
            except Exception:
                pass
            self._dmd_preview_pump_id = None

    def _pump_dmd_preview(self):
        """Tk-after redraw loop: pulls the latest frame slot, renders,
        updates the preview label."""
        try:
            latest = self._dmd_latest
            if latest is not None and _HAVE_PIL:
                data, w, h, depth = latest
                img = _render_pinmame_frame(
                    data, w, h, depth,
                    self._DMD_PREVIEW_SCALE, self._DMD_AMBER)
                tkimg = ImageTk.PhotoImage(img)
                self._dmd_preview_tkimage = tkimg  # keep reference!
                self._dmd_preview_label.configure(image=tkimg)
                if not self._dmd_preview_visible:
                    self._dmd_preview_visible = True
        except Exception:
            # GUI must not crash on a malformed frame.
            pass
        # Re-arm — capture-cancel + new-capture loop both rely on
        # this self-rearm behaviour.
        self._dmd_preview_pump_id = self.root.after(
            33, self._pump_dmd_preview)

    # ------------------------------------------------------------------
    # Diagnostic switch matrix (Williams capture mode)
    # ------------------------------------------------------------------

    def on_capture_ready(self, manual_press_fn, active_script):
        """Called by the capture pipeline once PinMAME is initialized
        and the active script is known.

        Stashes the manual-press function and builds a labeled grid
        of clickable switch buttons for the active game.  Called from
        the capture thread — schedule the actual widget build on the
        Tk main thread.
        """
        self._manual_press_fn = manual_press_fn
        self.root.after(0, self._build_switch_matrix, active_script)

    def _build_switch_matrix(self, script):
        """Build the clickable switch-matrix grid from the active
        game's raw switch map."""
        # Tear down previous buttons.
        for w in self._switch_matrix_buttons:
            try:
                w.destroy()
            except Exception:
                pass
        self._switch_matrix_buttons = []

        raw = script.profile.get("raw", {}) if script else {}
        named_by_sw = {int(sw): name for name, sw in raw.items()}
        # Sort the named entries by switch number for stable layout.
        named_entries = sorted(raw.items(), key=lambda kv: int(kv[1]))
        # ALSO surface every standard WPC playfield position (sw#41
        # through sw#88) that isn't already in the raw map.  Sparse
        # prelim-sim games (NF, MB, CC, CV, etc.) only declare the
        # cabinet + trough + a couple of slings — but the real
        # playfield has ramps + saucers + targets at the conventional
        # positions.  Adding buttons for those lets the user fire
        # them manually for diagnostics, even though they're unlabeled.
        unknown_sws = []
        for sw_n in range(11, 89):
            if sw_n in named_by_sw:
                continue
            # Skip slot positions outside the conventional matrix
            # (column 9+, row 0).  WPC matrix is 8 cols × 8 rows so
            # any sw#NN where N%10 == 0 or N%10 > 8 is invalid.
            if sw_n % 10 == 0 or sw_n % 10 > 8:
                continue
            unknown_sws.append(sw_n)
        if not named_entries and not unknown_sws:
            self._switch_matrix_frame.configure(
                text="Switch matrix (no switches defined)")
            self._switch_matrix_frame.pack(
                fill=tk.X, padx=10, pady=(4, 0))
            return
        self._switch_matrix_frame.configure(
            text=f"Switch matrix — {script.title} "
                 f"({len(named_entries)} named + "
                 f"{len(unknown_sws)} unlabeled WPC positions, "
                 "click to press)")
        # 8 columns of compact buttons.
        cols = 8
        # Section 1: named switches.
        idx = 0
        for name, sw in named_entries:
            sw_n = int(sw)
            row, col = divmod(idx, cols)
            short = name.replace("sw", "", 1).strip()
            btn = ttk.Button(
                self._switch_matrix_inner,
                text=f"{sw_n:>2} {short[:8]}",
                width=12,
                command=lambda s=sw_n, n=short:
                    self._on_manual_switch_press(s, n))
            btn.grid(row=row, column=col, padx=1, pady=1, sticky="w")
            self._switch_matrix_buttons.append(btn)
            _Tooltip(btn, f"sw#{sw_n} — {short}",
                     lambda: self._current_theme)
            idx += 1

        # Separator row before the unlabeled positions.
        if unknown_sws:
            # Round up to next row boundary.
            while idx % cols != 0:
                idx += 1
            sep = ttk.Label(
                self._switch_matrix_inner,
                text="── Standard WPC playfield positions (not declared "
                     "in this game's sim — try them to see what's wired here)",
                font=(_SANS_FONT, 9, "italic"))
            sep.grid(row=idx // cols, column=0,
                     columnspan=cols, sticky="w",
                     padx=2, pady=(6, 2))
            self._switch_matrix_buttons.append(sep)
            idx = (idx // cols + 1) * cols
            for sw_n in unknown_sws:
                row, col = divmod(idx, cols)
                btn = ttk.Button(
                    self._switch_matrix_inner,
                    text=f"{sw_n:>2}  ?",
                    width=12,
                    command=lambda s=sw_n:
                        self._on_manual_switch_press(s, f"sw#{s}"))
                btn.grid(row=row, column=col, padx=1, pady=1, sticky="w")
                self._switch_matrix_buttons.append(btn)
                _Tooltip(btn,
                         f"sw#{sw_n} (col {sw_n // 10}, row {sw_n % 10}) "
                         f"— unlabeled standard WPC position",
                         lambda: self._current_theme)
                idx += 1
        # Make the matrix visible.
        self._switch_matrix_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

    def _on_manual_switch_press(self, sw_no: int, label: str):
        """User clicked a switch button — fire the manual press."""
        fn = self._manual_press_fn
        if fn is None:
            return
        try:
            fn(sw_no, 120)
        except Exception as e:
            # Don't let a bad press crash the GUI.
            try:
                self.append_log(
                    f"manual press sw#{sw_no} ({label}) failed: {e}",
                    "warning")
            except Exception:
                pass

    def _configure_tab(self, label, visible):
        for tab_id in self._notebook.tabs():
            if self._notebook.tab(tab_id, "text").strip() == label:
                if visible:
                    self._notebook.tab(tab_id, state="normal")
                else:
                    self._notebook.tab(tab_id, state="hidden")
                return

    # ------------------------------------------------------------------
    # Browse helpers (file-filter pulled from current manufacturer)
    # ------------------------------------------------------------------

    def _input_filetypes(self):
        if self._current_mfr is None:
            return [("All files", "*.*")]
        spec = self._current_mfr.input_spec
        if not spec.extensions:
            return [("All files", "*.*")]
        joined = " ".join(f"*{ext}" for ext in spec.extensions)
        return [(spec.label, joined), ("All files", "*.*")]

    def _browse_extract_input(self):
        path = filedialog.askopenfilename(
            title="Select input file", filetypes=self._input_filetypes())
        if path:
            self.extract_input_var.set(path)

    # ------------------------------------------------------------------
    # Direct-SSD source toggle + drive picker (caps.direct_ssd plugins)
    # ------------------------------------------------------------------

    def _on_input_source_change(self, mode):
        """Swap between the ISO file picker and the SSD drive picker.

        ``mode`` is "extract" or "write".  Called by the radio
        buttons.  Re-packs the visible row in the right order so the
        layout reads top-to-bottom even after multiple toggles.
        """
        if mode == "extract":
            source = self.extract_input_source_var.get()
            self._extract_input_row.pack_forget()
            self._extract_drive_row.pack_forget()
            self._extract_ssd_warn.pack_forget()
            self._extract_admin_frame.pack_forget()
            self._extract_macos_fda_frame.pack_forget()
            self._extract_badge.pack_forget()
            if source == "ssd":
                self._extract_drive_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
                self._extract_ssd_warn.pack(
                    anchor=tk.W, padx=10, pady=(4, 2),
                    before=self._extract_output_row())
                # Platform-specific Direct-SSD preconditions:
                #   * Windows: app must run as Administrator
                #     (wsl --mount + Set-Disk -IsOffline both gated).
                #   * macOS:   Full Disk Access on the app + debugfs
                #     + e2fsck (TCC blocks raw-disk reads otherwise).
                # Linux just uses sudo prompts mid-run, no preflight
                # banner required.
                import sys
                from ..core.admin import is_admin
                if sys.platform == "win32" and not is_admin():
                    self._extract_admin_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._extract_output_row())
                elif (sys.platform == "darwin"
                        and not self._fda_acknowledged):
                    self._extract_macos_fda_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._extract_output_row())
                # Kick off enumeration on a worker thread so the UI
                # never blocks on PowerShell/diskutil startup.  First
                # toggle of the radio always re-enumerates so a
                # freshly-plugged SSD shows up without a Refresh click.
                self._refresh_drives_async("extract")
            else:
                self._extract_input_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
                self._extract_badge.pack(
                    anchor=tk.W, padx=24, pady=(0, 2),
                    before=self._extract_output_row())
            self._refresh_extract_phases()
            # Re-evaluate the Extract button gate after a source flip.
            self._refresh_ssd_run_buttons()
        else:  # write
            source = self.write_input_source_var.get()
            self._write_upd_row.pack_forget()
            self._write_drive_row.pack_forget()
            self._write_ssd_warn.pack_forget()
            self._write_admin_frame.pack_forget()
            self._write_macos_fda_frame.pack_forget()
            self._write_badge.pack_forget()
            self._write_desc.pack_forget()
            self._write_preview_frame.pack_forget()
            if source == "ssd":
                # SSD layout matches the standalone JJP decryptor:
                # Assets → Game SSD → Warning → Description →
                # Modified Files Preview.  Everything dynamic packs
                # `before=filename_lbl` so the order is:
                # [build-time assets row] [dynamic rows] [filename
                # lbl] [btn row].
                self._write_drive_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_filename_lbl)
                self._write_ssd_warn.pack(
                    anchor=tk.W, padx=10, pady=(4, 2),
                    before=self._write_filename_lbl)
                # Platform preconditions — see Extract branch for
                # the rationale.  Windows admin / macOS FDA.
                import sys
                from ..core.admin import is_admin
                if sys.platform == "win32" and not is_admin():
                    self._write_admin_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._write_filename_lbl)
                elif (sys.platform == "darwin"
                        and not self._fda_acknowledged):
                    self._write_macos_fda_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._write_filename_lbl)
                # SSD mode: explain in-place encrypt + audio
                # trim/pad behaviour so users know what to expect
                # before they click Apply Modifications.
                self._write_desc.configure(
                    text="Re-encrypt changed files and write them "
                         "directly to the game SSD. Audio files are "
                         "automatically trimmed or padded to match "
                         "the original duration.")
                self._write_desc.pack(
                    anchor=tk.W, padx=10, pady=(2, 6),
                    before=self._write_filename_lbl)
                # Modified Files Preview only makes sense for SSD
                # mode — the ISO-build flow has its own scan +
                # convert phases the user watches via the phase
                # indicator.
                self._write_preview_frame.pack(
                    fill=tk.BOTH, expand=True, padx=10, pady=(4, 4),
                    before=self._write_filename_lbl)
                self._write_btn.configure(text="Apply Modifications")
                self._refresh_drives_async("write")
                # SSD-write doesn't produce an output file — the SSD
                # IS the output.  Hide the Output Folder row.
                if hasattr(self, "_write_output_row_ref"):
                    self._write_output_row_ref.pack_forget()
                # Kick a preview scan in the background so the user
                # sees the modified files without a separate click.
                self._scan_write_preview()
            else:
                # ISO layout: source → original ISO → badge → assets
                # → output folder.  Dynamic rows go BEFORE the
                # assets row (because the original ISO sits above
                # the modified-assets folder in this flow).
                self._write_upd_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_assets_row())
                self._write_badge.pack(
                    anchor=tk.W, padx=26, pady=(0, 2),
                    before=self._write_assets_row())
                self._write_desc.configure(
                    text="Re-pack modified assets into an "
                         "installable update file.")
                self._write_desc.pack(
                    anchor=tk.W, padx=10, pady=(2, 6),
                    before=self._write_assets_row())
                self._write_btn.configure(text="Build update")
                if hasattr(self, "_write_output_row_ref"):
                    self._write_output_row_ref.pack(
                        fill=tk.X, padx=10, pady=4,
                        before=self._write_filename_lbl)
            # Either branch may have changed the phase indicator
            # shape — refresh both extract and write phases.
            self._refresh_extract_phases()
            # Also re-evaluate the Extract/Apply Modifications
            # button gates: SSD + non-admin disables them so the
            # user can't kick off a doomed run.
            self._refresh_ssd_run_buttons()

    def _extract_output_row(self):
        """Output Folder row — anchor for ``before=`` repacks."""
        return getattr(self, "_extract_output_row_ref", None)

    def _write_assets_row(self):
        """Modified Assets row — anchor for write-tab SSD repacks."""
        return getattr(self, "_write_assets_row_ref", None)

    def _refresh_drives(self, mode):
        """Public Refresh-button handler — kicks off async enumeration."""
        self._refresh_drives_async(mode)

    def _refresh_drives_async(self, mode):
        """Enumerate physical drives on a worker thread.

        PowerShell's first-launch cost (~1-2s) blocks the Tk event
        loop if we run it inline — which is what made the "From SSD"
        radio feel like the app had hung.  We park the subprocess
        call on a daemon thread and hand the result back via
        ``root.after`` so all widget updates happen on the main
        thread.

        While the enumeration runs, the combobox shows a placeholder
        so the user has visual feedback that something is happening.
        """
        combo = (self._extract_drive_combo if mode == "extract"
                 else self._write_drive_combo)
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)
        combo["values"] = ["Detecting drives…"]
        display_var.set("Detecting drives…")

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives)
            except Exception:
                drives, pick = [], (None, None, None)
            # Hop back to the main thread before touching Tk widgets.
            self._tk_root().after(
                0, self._apply_drives, mode, drives, pick)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _tk_root(self):
        """Return the Tk root — used by worker-thread .after() calls.

        ttk.Frame doesn't expose .after directly on this class, but
        any widget can call .after on its toplevel.
        """
        # ``self.master`` or the title label both work; pick a known-
        # existing widget that's created before any threaded work.
        return self._title_lbl.winfo_toplevel()

    def _apply_drives(self, mode, drives, pick):
        """Main-thread continuation of _refresh_drives_async.

        Populates the combobox, auto-selects the best-match drive,
        logs the discovery so the user can see exactly what was
        picked and why.  ``pick`` is the
        ``(drive, confidence, reason)`` triple from
        ``pick_best_game_ssd``.
        """
        combo = (self._extract_drive_combo if mode == "extract"
                 else self._write_drive_combo)
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)
        if mode == "extract":
            self._extract_drives_cache = drives
        else:
            self._write_drives_cache = drives

        if not drives:
            combo["values"] = ["(no drives found — click Refresh)"]
            display_var.set(combo["values"][0])
            self._log_ssd_pick(
                "No physical drives detected.  Check that the SSD "
                "is connected and click Refresh.", level="error")
            return

        combo["values"] = [d.display for d in drives]
        best, confidence, reason = pick
        if best is not None:
            display_var.set(best.display)
            self._on_drive_selected(mode)
            tag = "success" if confidence == "high" else "info"
            self._log_ssd_pick(
                f"Selected SSD: {best.display}", level=tag)
            if reason:
                self._log_ssd_pick(f"  ({reason})", level="info")
            if confidence != "high":
                self._log_ssd_pick(
                    "  If this isn't the JJP SSD, pick it manually "
                    "from the dropdown.", level="info")
        else:
            # pick_best_game_ssd returned (None, None, None) — should
            # only happen on an empty list which we handled above.
            display_var.set(drives[0].display)
            self._on_drive_selected(mode)

    def _build_macos_fda_warning_frame(self, parent):
        """macOS Full Disk Access guidance banner for Direct-SSD mode.

        macOS Sonoma+ blocks raw block-device reads at the TCC layer
        — even from root subprocesses — unless every binary that
        touches ``/dev/rdiskN`` is on the Full Disk Access list.  Our
        Direct-SSD pipeline shells out to ``debugfs`` and ``e2fsck``
        from ``e2fsprogs``, so users need to grant access to BOTH
        helpers plus the app itself.  This banner spells out the
        exact steps so users don't have to learn TCC the hard way
        (operation-not-permitted, password-loop, etc.).

        Dismissible: the original "always shown" design fell out of
        sync with the actual TCC state — a user who had already
        granted everything in System Settings still saw the warning
        and assumed the app didn't know.  The "Hide this notice"
        link sets a persistent flag; the same flag is auto-set on
        the first successful Direct-SSD run, since that's empirical
        proof that FDA is working.
        """
        frame = tk.Frame(
            parent, bg="#5a1a1a", padx=12, pady=10,
            highlightbackground="#f44747", highlightthickness=2)
        header = tk.Frame(frame, bg="#5a1a1a")
        header.pack(fill=tk.X, anchor=tk.W)
        tk.Label(
            header,
            text="⚠  macOS FULL DISK ACCESS REQUIRED",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 11, "bold"),
            anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True,
                              anchor=tk.W)
        # Dismiss link — styled as a clickable label rather than a
        # ttk button so it blends with the banner's red colour
        # scheme.  Cursor flips to a pointer on hover so it reads
        # as interactive.
        dismiss = tk.Label(
            header,
            text="Hide this notice ✕",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 9, "underline"),
            cursor="hand2")
        dismiss.pack(side=tk.RIGHT, anchor=tk.E)
        dismiss.bind("<Button-1>",
                     lambda _e: self._dismiss_macos_fda_banner())
        tk.Label(
            frame,
            text=(
                "Direct-SSD on macOS reads raw disk blocks via "
                "Homebrew's e2fsprogs.  macOS Sonoma+ blocks this "
                "at the TCC layer until every binary involved is on "
                "the Full Disk Access list — even with admin "
                "password.\n\n"
                "To grant (one-time setup):\n"
                "   1.   System Settings → Privacy & Security → "
                "Full Disk Access.\n"
                "   2.   Click + and add each of these:\n"
                "          •   Pinball Asset Decryptor.app\n"
                "          •   debugfs  (usually "
                "/opt/homebrew/opt/e2fsprogs/sbin/debugfs on Apple "
                "Silicon, /usr/local/opt/e2fsprogs/sbin/debugfs on "
                "Intel)\n"
                "          •   e2fsck   (same folder as debugfs)\n"
                "   3.   Toggle each one ON.\n"
                "   4.   Fully quit this app (⌘Q) and reopen.\n\n"
                "Tip:  the binaries are in hidden folders.  In the "
                "Full Disk Access file picker, press ⌘⇧G and paste "
                "the full path.\n\n"
                "Already granted?  Click \"Hide this notice\" above "
                "— it'll stay hidden across restarts.  The notice "
                "auto-hides after your first successful SSD extract."),
            bg="#5a1a1a", fg="#ffffff",
            font=(_SANS_FONT, 9),
            justify=tk.LEFT, anchor=tk.W,
            wraplength=720).pack(fill=tk.X, anchor=tk.W, pady=(6, 0))
        return frame

    def _dismiss_macos_fda_banner(self):
        """Hide the FDA banner everywhere it might currently be packed
        and persist the dismissal via the app callback."""
        self._fda_acknowledged = True
        if self._on_fda_acknowledge is not None:
            try:
                self._on_fda_acknowledge(True)
            except Exception:
                pass
        for attr in ("_extract_macos_fda_frame",
                     "_write_macos_fda_frame"):
            frame = getattr(self, attr, None)
            if frame is not None:
                frame.pack_forget()

    def acknowledge_macos_fda(self):
        """Public API for the app to mark FDA as proven-working
        (called after a successful Direct-SSD run).  Idempotent."""
        if not self._fda_acknowledged:
            self._dismiss_macos_fda_banner()

    def _build_admin_warning_frame(self, parent):
        """Build the prominent "Administrator required" warning panel.

        Uses raw ``tk.Frame`` / ``tk.Label`` (not ttk) so we can set
        the background colour directly — ttk styling per-widget is
        themable but harder to override locally, and the goal here
        is the opposite of "blend in".  Returns the unpacked frame;
        ``_on_input_source_change`` decides when to pack it.
        """
        frame = tk.Frame(
            parent, bg="#5a1a1a", padx=12, pady=10,
            highlightbackground="#f44747", highlightthickness=2)
        tk.Label(
            frame,
            text="⚠  ADMINISTRATOR PRIVILEGES REQUIRED",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 11, "bold"),
            anchor=tk.W).pack(fill=tk.X, anchor=tk.W)
        tk.Label(
            frame,
            text=(
                "Direct-SSD mode needs Windows Administrator "
                "privileges.  Both wsl --mount and Set-Disk "
                "-IsOffline are gated by Windows itself behind "
                "elevation — there is no workaround at the app "
                "level.\n\n"
                "To enable Direct-SSD:\n"
                "   1.   Close this app.\n"
                "   2.   Right-click the \"Pinball Asset Decryptor\" "
                "shortcut (Start menu or desktop).\n"
                "   3.   Choose \"Run as administrator\".\n"
                "   4.   Re-select \"From SSD\" — your drive and "
                "output folder will be remembered."),
            bg="#5a1a1a", fg="#ffffff",
            font=(_SANS_FONT, 9),
            justify=tk.LEFT, anchor=tk.W,
            wraplength=720).pack(fill=tk.X, anchor=tk.W, pady=(6, 0))
        return frame

    def _refresh_ssd_run_buttons(self):
        """Disable Extract / Apply Modifications when SSD + not admin.

        Windows-only gate: the elevation requirement comes from
        ``wsl --mount`` + ``Set-Disk -IsOffline``, both of which are
        Windows-specific.  macOS / Linux handle elevation in-process
        via osascript / sudo prompts in
        :meth:`_debugfs_run_elevated`, so we should NOT disable the
        Extract button there — the user runs the app normally and
        types their password into the system dialog when prompted.

        Re-enabled the moment the user switches the radio back to ISO
        mode, or when ``is_admin()`` flips True (which only happens
        on a re-launched elevated process — same process can't gain
        admin mid-life).
        """
        import sys
        from ..core.admin import is_admin
        admin = is_admin()
        mfr = self._current_mfr
        needs_admin = (
            sys.platform == "win32"
            and mfr is not None
            and mfr.capabilities.direct_ssd
            and not admin)
        block_extract = (
            needs_admin
            and self.extract_input_source_var.get() == "ssd")
        block_write = (
            needs_admin
            and self.write_input_source_var.get() == "ssd")
        # Don't fight whatever set_running() may have set — only
        # touch state if we're not in the middle of a run.
        if not self._is_running():
            self._extract_btn.configure(
                state=(tk.DISABLED if block_extract else tk.NORMAL))
            self._write_btn.configure(
                state=(tk.DISABLED if block_write else tk.NORMAL))

    def _is_running(self):
        """True when a pipeline is mid-flight (either tab)."""
        # Cancel button is enabled during runs; cheaper than tracking
        # a separate flag and keeps the two state machines in sync.
        try:
            return (str(self._extract_cancel_btn.cget("state"))
                    == tk.NORMAL)
        except (AttributeError, tk.TclError):
            return False

    def _log_ssd_pick(self, text, level="info"):
        """Write a Direct-SSD discovery line to the current mfr's log.

        Routes through the same append_log path the pipelines use, so
        the user sees the SSD-pick reasoning in the same console
        they'll watch for the actual decrypt/encrypt run.
        """
        try:
            self.append_log(text, level=level)
        except Exception:
            # Pre-mfr-selected start-up state — the log widget may not
            # be active yet.  Best-effort; the same info will appear
            # when the pipeline runs anyway (the pipeline logs the
            # device + partition picks too).
            pass

    def _on_drive_selected(self, mode):
        """Map the selected combobox label back to its device_path.

        The combobox stores the *display* string (model + size + path);
        the pipeline needs the bare device_path.  We look it up from
        the cached PhysicalDrive list — keying on display is fine
        because the display includes the device_path verbatim, so
        duplicates are impossible.
        """
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)
        device_var = (self.extract_drive_var if mode == "extract"
                      else self.write_drive_var)
        cache = (self._extract_drives_cache if mode == "extract"
                 else self._write_drives_cache)
        label = display_var.get()
        match = next((d for d in cache if d.display == label), None)
        device_var.set(match.device_path if match else "")

    # ------------------------------------------------------------------
    # Direct-SSD Modified Files Preview (JJP-only)
    # ------------------------------------------------------------------

    def _scan_write_preview(self):
        """Populate the Modified Files Preview tree on a worker thread.

        Walks the user's assets folder and MD5-compares each file
        against the baseline ``.checksums.md5`` the Extract phase
        emitted; anything that doesn't match shows up as "Modified"
        in the tree.  Ported almost verbatim from the standalone
        JJP decryptor (which is where users with the file already
        know the format from).

        Silently no-ops when:
          * the assets folder isn't set or doesn't exist (nothing to
            scan yet);
          * no .checksums.md5 is present (user pointed at a folder
            that didn't come from this app's Decrypt phase).

        Cancellable via ``_write_preview_scan_id`` — a re-scan
        invalidates any in-flight work so two scans don't race to
        populate the tree.
        """
        import hashlib
        import os
        import re as _re
        import threading

        assets_path = (self.write_assets_var.get() or "").strip()
        # Clear whatever's there from a prior scan.
        self._write_preview_tree.delete(
            *self._write_preview_tree.get_children())
        if not assets_path or not os.path.isdir(assets_path):
            self._write_preview_empty.configure(
                text="Switch to this tab to scan for modified files")
            self._write_preview_empty.place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)
            return
        checksums_file = os.path.join(assets_path, ".checksums.md5")
        if not os.path.isfile(checksums_file):
            self._write_preview_empty.configure(
                text=("Pick a folder produced by Extract first "
                      "(no .checksums.md5 found)."))
            self._write_preview_empty.place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        # Bump the scan-id so any older in-flight scan stops
        # posting results.
        self._write_preview_scan_id += 1
        scan_id = self._write_preview_scan_id
        self._write_preview_empty.configure(
            text="Scanning for modified files…")
        self._write_preview_empty.place(
            relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _scan():
            # ``.checksums.md5`` ships in two flavours depending on
            # which plugin wrote it:
            #   * JJP / md5sum style   — "<md5>  <path>"  (md5 first)
            #   * BOF style            — "<path>\t<md5>"  (path first)
            # Detect per-line: if the line starts with 32 hex chars,
            # treat as md5sum; otherwise split on the last tab.
            saved = {}
            md5sum_re = _re.compile(r'^([a-f0-9]{32})\s+\*?(.+)$')
            try:
                with open(checksums_file, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        m = md5sum_re.match(line)
                        if m:
                            md5_val = m.group(1)
                            fp = m.group(2)
                        elif "\t" in line:
                            fp, md5_val = line.rsplit("\t", 1)
                            md5_val = md5_val.strip()
                            if not _re.fullmatch(r'[a-f0-9]{32}', md5_val):
                                continue
                        else:
                            continue
                        if fp.startswith("./"):
                            fp = fp[2:]
                        saved[fp.replace("\\", "/")] = md5_val
            except OSError:
                return

            # BOF only: hide the imported-cache subtree from the
            # preview.  Those files are pipeline-managed derivatives
            # of the user's edits to ``_EDITABLE ASSETS/`` (the Write
            # step re-encodes WAV/WEBP/etc. → .sample/.ctex/etc.), and
            # they also accumulate stale state from prior cancelled or
            # partial Write runs — both produce noise the user can't
            # act on directly.  Practice-mode modders aren't affected:
            # script edits live in ``pck/scripts``, scenes in
            # ``pck/.godot/exported``, .tres in ``pck/assets`` — none
            # of those paths are under ``pck/.godot/imported``.  The
            # Write pipeline still MD5-scans the full tree (including
            # imported/) so anything that genuinely differs there
            # still ships into the binary.
            current_mfr = self._current_mfr
            hide_imported_cache = (
                current_mfr is not None and current_mfr.key == "bof")

            changed = []
            for root_dir, _dirs, files in os.walk(assets_path):
                for name in files:
                    if (name.startswith(".")
                            or name == "fl_decrypted.dat"
                            or name.endswith(".img")):
                        continue
                    full = os.path.join(root_dir, name)
                    rel = os.path.relpath(
                        full, assets_path).replace("\\", "/")
                    if rel not in saved:
                        continue
                    if (hide_imported_cache
                            and rel.startswith("pck/.godot/imported/")):
                        continue
                    h = hashlib.md5()
                    try:
                        with open(full, "rb") as fh:
                            for chunk in iter(
                                    lambda: fh.read(65536), b""):
                                h.update(chunk)
                    except OSError:
                        continue
                    if h.hexdigest() == saved[rel]:
                        continue
                    if self._write_preview_scan_id != scan_id:
                        return  # superseded — drop this scan
                    changed.append(rel)
                    ext = os.path.splitext(name)[1].lstrip(".") or "?"
                    self._tk_root().after(
                        0, self._add_write_preview_row,
                        rel, ext, "Modified", scan_id)

            if self._write_preview_scan_id == scan_id:
                self._tk_root().after(
                    0, self._finish_write_preview_scan,
                    len(changed), scan_id)

        threading.Thread(target=_scan, daemon=True).start()

    def _add_write_preview_row(self, rel, ext, status, scan_id):
        """Insert one row into the preview tree (main-thread only)."""
        if self._write_preview_scan_id != scan_id:
            return
        # Once we've added a real row, hide the placeholder.
        try:
            self._write_preview_empty.place_forget()
        except tk.TclError:
            pass
        self._write_preview_tree.insert(
            "", tk.END, text=rel, values=(ext, status),
            tags=("modified",))
        # Tag colour is set in _apply_theme so it tracks dark/light
        # mode; nothing per-row here.

    def _finish_write_preview_scan(self, n_changed, scan_id):
        """End-of-scan housekeeping (main-thread only)."""
        if self._write_preview_scan_id != scan_id:
            return
        if n_changed == 0:
            self._write_preview_empty.configure(
                text="No modified files detected.")
            self._write_preview_empty.place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _maybe_rescan_write_preview(self):
        """Re-scan only when the Write tab is the active view AND the
        current plugin shows the preview tree.

        The ``write_assets_var`` trace fires on every keystroke, on
        every settings-restore, and on programmatic ``set()``; we
        don't want to spin up a hashing thread for any of those when
        the user isn't even looking at the preview.
        """
        mfr = self._current_mfr
        if mfr is None:
            return
        # JJP shows the tree only in SSD mode; BOF shows it always.
        # Other plugins don't have a preview tree at all.
        if mfr.capabilities.direct_ssd:
            if self.write_input_source_var.get() != "ssd":
                return
        elif mfr.key != "bof":
            return
        # Only scan if the Write tab is the currently-selected tab —
        # otherwise the user can't see the preview anyway.
        try:
            idx = self._notebook.index(self._notebook.select())
            tab_id = self._notebook.tabs()[idx]
            if self._notebook.tab(tab_id, "text").strip() != "Write":
                return
        except (tk.TclError, IndexError):
            return
        self._scan_write_preview()

    def _browse_extract_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.extract_output_var.set(path)

    def _browse_write_upd(self):
        path = filedialog.askopenfilename(
            title="Select original update file",
            filetypes=self._input_filetypes())
        if path:
            self.write_upd_var.set(path)

    def _browse_write_assets(self):
        path = filedialog.askdirectory(title="Select modified assets folder")
        if path:
            self.write_assets_var.set(path)

    def _browse_write_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.write_output_var.set(path)

    # ------------------------------------------------------------------
    # Dynamic badges
    # ------------------------------------------------------------------

    def _update_extract_badge(self, *_):
        self._set_badge(self._extract_badge, self.extract_input_var.get(),
                        mode="extract")
        self._refresh_extract_audio_support()

    def _refresh_extract_audio_support(self):
        """Re-probe whether the selected extract input is a game whose
        audio we can export, then refresh the audio-dependent UI (the
        Auto-transcribe checkboxes and the "Extract audio" phase) when
        that answer changes."""
        path = (self.extract_input_var.get() or "").strip()
        if self._current_mfr is None:
            supported = False
        elif path and os.path.isfile(path):
            try:
                supported = bool(
                    self._current_mfr.audio_export_supported(path))
            except Exception:
                supported = False
        else:
            # No file picked yet — don't pre-hide the audio UI; it
            # only hides once an unsupported game is actually chosen.
            supported = True
        if supported == self._extract_audio_supported:
            return
        self._extract_audio_supported = supported
        self._refresh_extract_phases()
        self._update_transcribe_visibility()

    def _update_write_badge(self, *_):
        self._set_badge(self._write_badge, self.write_upd_var.get(),
                        mode="write")

    def _set_badge(self, label, path, mode):
        path = (path or "").strip()
        # Reset suggestion state for this mode each call.
        self._set_suggested_mfr(mode, None)

        if not path or not os.path.isfile(path) or self._current_mfr is None:
            label.configure(text="")
            return

        # 1. Try the current manufacturer first — happy path.
        try:
            game = self._current_mfr.detect(path)
        except Exception:
            game = None
        if game:
            extra = f" — {game.notes}" if game.notes else ""
            label.configure(text=f"Detected: {game.display}{extra}")
            return

        # 2. Walk every other registered manufacturer.  If exactly one
        #    matches, offer to switch.  More than one match is ambiguous;
        #    none means the file is unrecognised by any plugin.
        other_hits = []
        for m in self._manufacturers:
            if m.key == self._current_mfr.key:
                continue
            try:
                g = m.detect(path)
            except Exception:
                continue
            if g:
                other_hits.append((m, g))

        if len(other_hits) == 1:
            m, g = other_hits[0]
            self._set_suggested_mfr(mode, m)
            label.configure(
                text=f"Looks like {g.display} ({m.display}) — "
                     f"click to switch")
        elif len(other_hits) > 1:
            names = ", ".join(m.display for m, _ in other_hits)
            label.configure(
                text=f"Matches multiple manufacturers: {names}")
        else:
            label.configure(
                text=f"Not recognised as {self._current_mfr.display}")

    def _set_suggested_mfr(self, mode, mfr):
        if mode == "extract":
            self._extract_suggested_mfr = mfr
        else:
            self._write_suggested_mfr = mfr

    def _update_badge_cursor(self, mode, hovering):
        badge = self._extract_badge if mode == "extract" else self._write_badge
        suggested = (self._extract_suggested_mfr if mode == "extract"
                     else self._write_suggested_mfr)
        badge.configure(cursor="hand2" if (hovering and suggested) else "")

    def _auto_switch(self, mode):
        """Click handler: swap to the suggested manufacturer, preserving
        the just-browsed path so the user doesn't have to re-pick it.

        The App's `_save_manufacturer_paths` won't persist this path
        under the *old* mfr (its `detect()` won't claim it), so we just
        switch and re-set the path afterwards — the new mfr's saved
        settings get loaded during the switch and would otherwise blank
        out the field.
        """
        suggested = (self._extract_suggested_mfr if mode == "extract"
                     else self._write_suggested_mfr)
        if suggested is None:
            return
        var = (self.extract_input_var if mode == "extract"
               else self.write_upd_var)
        path = var.get()
        if self._on_manufacturer_change:
            self._on_manufacturer_change(suggested)
        var.set(path)

    # ------------------------------------------------------------------
    # Prerequisite indicators
    # ------------------------------------------------------------------

    def reset_prereqs(self, prereqs):
        """Replace the indicator row for the new manufacturer.

        Each prereq starts in "checking" state ([?] name); the App's
        worker thread fills in real results via :meth:`set_prereq_result`.
        Hides the section entirely when *prereqs* is empty.
        """
        for w in self._prereqs_inner.winfo_children():
            w.destroy()
        self._prereq_indicators = {}

        if not prereqs:
            self._prereqs_frame.pack_forget()
            return

        self._prereqs_frame.pack(fill=tk.X, padx=10, pady=(6, 0),
                                 before=self._notebook)

        c = THEMES[self._current_theme]
        for p in prereqs:
            lbl = tk.Label(
                self._prereqs_inner,
                text=f"[?] {p.name}",
                font=(_SANS_FONT, 9),
                background=c["bg"], foreground=c["gray"],
                padx=4, pady=2,
            )
            lbl.pack(side=tk.LEFT, padx=2)
            tooltip = _Tooltip(
                lbl,
                f"{p.name}\n\nChecking...\n\nWhy: {p.reason}",
                lambda: self._current_theme,
            )
            self._prereq_indicators[p.name] = {
                "label": lbl, "tooltip": tooltip, "prereq": p,
            }

    def set_prereq_result(self, name, ok, message):
        """Update one indicator with the probe's result."""
        entry = self._prereq_indicators.get(name)
        if not entry:
            return
        c = THEMES[self._current_theme]
        icon = "✓" if ok else "✗"
        color = c["success"] if ok else c["error"]
        entry["label"].configure(text=f"[{icon}] {name}", foreground=color)
        p = entry["prereq"]
        status = "OK" if ok else "MISSING"
        tip = (f"{p.name}\n\n"
               f"Status: {status}\n"
               f"{message}\n\n"
               f"Why: {p.reason}")
        if not ok and p.install_hint:
            tip += f"\n\nFix: {p.install_hint}"
        entry["tooltip"].text = tip

    def _check_extract_warn(self, *_):
        path = self.extract_output_var.get().strip()
        if path and os.path.isdir(path) and os.listdir(path):
            self._extract_warn.configure(
                text="Output folder is not empty — files may be overwritten.")
        else:
            self._extract_warn.configure(text="")

    def _update_write_filename(self):
        upd = self.write_upd_var.get().strip()
        out = self.write_output_var.get().strip()
        name = os.path.basename(upd) if upd else ""
        if name and out:
            spec_ext = (self._current_mfr.input_spec.extensions[0].lower()
                        if self._current_mfr else ".upd")
            full = out if out.lower().endswith(spec_ext) else os.path.join(
                out, name)
            self._write_filename_lbl.configure(text=f"Output: {full}")
        elif name:
            self._write_filename_lbl.configure(text=f"Filename: {name}")
        else:
            self._write_filename_lbl.configure(text="")

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def append_log(self, text, level="info"):
        # Calls before any mfr is selected (e.g. update-check on startup
        # while picker is showing) are buffered against the first mfr's
        # widget once one is selected.  For now, silently drop them.
        if self._log_text is None:
            return
        ts = time.strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        self._log_text.insert(tk.END, text + "\n", level)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    def append_log_link(self, text, url):
        if self._log_text is None:
            return
        ts = time.strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        tag = f"link_{id(url)}"
        self._log_text.tag_configure(
            tag, foreground=THEMES[self._current_theme]["link"], underline=True)
        self._log_text.tag_bind(tag, "<Button-1>",
                                lambda e, u=url: webbrowser.open(u))
        self._log_text.tag_bind(tag, "<Enter>",
                                lambda e: self._log_text.configure(cursor="hand2"))
        self._log_text.tag_bind(tag, "<Leave>",
                                lambda e: self._log_text.configure(cursor=""))
        self._log_text.insert(tk.END, text + "\n", tag)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    # ------------------------------------------------------------------
    # Phases / progress
    # ------------------------------------------------------------------

    def set_phase(self, index, mode="extract"):
        labels = (self._extract_phase_labels if mode == "extract"
                  else self._write_phase_labels)
        c = THEMES[self._current_theme]
        for i, lbl in enumerate(labels):
            text = lbl.cget("text") or ""
            name = text.lstrip("○● ").strip()
            if i < index:
                lbl.configure(text=f"● {name}", foreground=c["success"])
            elif i == index:
                lbl.configure(text=f"● {name}", foreground=c["accent"])
            else:
                lbl.configure(text=f"○ {name}", foreground=c["gray"])

    def reset_steps(self, mode="extract"):
        phases = (self._extract_phases if mode == "extract"
                  else self._write_phases)
        labels = (self._extract_phase_labels if mode == "extract"
                  else self._write_phase_labels)
        c = THEMES[self._current_theme]
        for lbl, name in zip(labels, phases):
            lbl.configure(text=f"○ {name}", foreground=c["gray"])
        self._progress_bar["value"] = 0

    def set_progress(self, current, total, desc="", mode="extract"):
        if total > 0:
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            self._progress_bar["value"] = int(100 * current / total)
        else:
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
        if desc:
            self.set_status(desc)

    def set_status(self, text):
        self._status_label.configure(text=text)

    # ------------------------------------------------------------------
    # Running state
    # ------------------------------------------------------------------

    def set_running(self, running, mode="extract"):
        if running:
            self._extract_btn.configure(state=tk.DISABLED)
            self._extract_cancel_btn.configure(state=tk.NORMAL)
            self._write_btn.configure(state=tk.DISABLED)
            self._write_cancel_btn.configure(state=tk.NORMAL)
            # Lock the Back button while work is in flight - we don't want
            # the user navigating away from a running pipeline.
            self.set_back_enabled(False)
            # Start the progress bar marching immediately so the user
            # gets visual feedback before the first progress callback
            # arrives — some plugins (Williams DMD scan) take a few
            # seconds of CPU spin-up before they emit any progress.
            # The first set_progress() with total>0 switches it to
            # determinate.
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
            # Cancel any prior tick chain before starting a new one.
            # Without this, a stale chain (e.g. from a back-to-back
            # extract-then-transcribe with two set_running(True) calls)
            # keeps ticking even after set_running(False) cancels what
            # _timer_id points to — orphan _tick_timer chains rewrite
            # the elapsed label indefinitely.
            if self._timer_id:
                self.root.after_cancel(self._timer_id)
                self._timer_id = None
            self._start_time = time.time()
            self._tick_timer()
        else:
            self._extract_btn.configure(state=tk.NORMAL)
            self._extract_cancel_btn.configure(state=tk.DISABLED)
            self._write_btn.configure(state=tk.NORMAL)
            self._write_cancel_btn.configure(state=tk.DISABLED)
            self.set_back_enabled(True)
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            if self._timer_id:
                self.root.after_cancel(self._timer_id)
                self._timer_id = None
            # Belt-and-suspenders: clear _start_time so any orphan
            # tick that slipped past the cancel becomes a no-op for
            # the elapsed label update.
            self._start_time = None
            self._elapsed_label.configure(text="")
            # Stop the live DMD-preview after-pump.  The label keeps
            # the last frame on screen as a static snapshot of where
            # capture ended (useful when reviewing what went wrong).
            self._stop_dmd_preview_pump()

    def _tick_timer(self):
        if self._start_time is None:
            # Pipeline finished -- don't re-schedule.  Leaving the
            # chain alive would burn CPU forever and (worse) reach in
            # to rewrite an elapsed label that we already cleared.
            self._timer_id = None
            return
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._elapsed_label.configure(text=f"{m:02d}:{s:02d}")
        self._timer_id = self.root.after(1000, self._tick_timer)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self):
        new = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme(new)
        if self._on_theme_change:
            self._on_theme_change(new)

    # ------------------------------------------------------------------
    # Update-available banner
    # ------------------------------------------------------------------

    def _build_update_banner(self, parent):
        """Build the persistent 'update available' banner widget.

        Created but not packed.  ``show_update_banner`` packs it
        above the back-button row using ``before=self._top_bar`` so
        it stays at the very top of the window across picker ↔
        working-view transitions.

        Uses raw ``tk`` widgets (not ttk) so the contrasting blue
        background + light-blue border stick regardless of the
        current theme — the banner is intentionally hard to miss.
        """
        self._update_banner = tk.Frame(
            parent, bg="#1e4a8a",
            highlightbackground="#3794ff", highlightthickness=1)
        # Lightning-bolt icon on the left.
        tk.Label(
            self._update_banner,
            text="⚡",
            bg="#1e4a8a", fg="#ffd700",
            font=(_SANS_FONT, 14, "bold")
        ).pack(side=tk.LEFT, padx=(10, 6), pady=4)
        self._update_banner_text = tk.Label(
            self._update_banner,
            text="",
            bg="#1e4a8a", fg="#ffffff",
            font=(_SANS_FONT, 10),
            anchor=tk.W)
        self._update_banner_text.pack(
            side=tk.LEFT, padx=0, pady=4, fill=tk.X, expand=True)
        # Download button — opens the release page in the browser.
        # tk.Button (not ttk) so its bg color sticks; ttk's themed
        # blue would clash with the banner background on light mode.
        tk.Button(
            self._update_banner, text="Download",
            bg="#3794ff", fg="#ffffff",
            activebackground="#5fa5ff", activeforeground="#ffffff",
            relief="flat", padx=10, pady=2, borderwidth=0,
            cursor="hand2",
            command=self._open_update_url,
        ).pack(side=tk.LEFT, padx=4, pady=4)
        # Dismiss × — closes the banner for this session.
        tk.Button(
            self._update_banner, text="✕",
            bg="#1e4a8a", fg="#ffffff",
            activebackground="#3a5a8a", activeforeground="#ffffff",
            relief="flat", padx=6, pady=2, borderwidth=0,
            cursor="hand2",
            command=self._dismiss_update_banner,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=4)
        # The URL to open when the Download button is clicked.
        # Populated by show_update_banner.
        self._update_banner_url = None

    def show_update_banner(self, version, url):
        """Display the 'update available' banner.

        Called from :meth:`App._check_for_update` on the main thread
        (via ``root.after(0, ...)``) when the GitHub release feed
        reports a newer version.  Idempotent — re-calling with the
        same args just re-shows / updates the banner; the user can
        still dismiss it after.
        """
        from pinball_decryptor import __version__ as _current
        self._update_banner_url = url
        self._update_banner_text.configure(
            text=f"Pinball Asset Decryptor v{version} is available "
                 f"— you're on v{_current}.")
        # Anchor above the back-button row so the banner sits at the
        # very top of the window regardless of which view (picker /
        # mfr) is currently shown.
        try:
            self._update_banner.pack(
                fill=tk.X, side=tk.TOP,
                before=self._top_bar)
        except tk.TclError:
            # Top bar not built yet — defer; this method runs on the
            # main thread from a startup-time worker so the widgets
            # should exist by now, but be defensive anyway.
            self._update_banner.pack(fill=tk.X, side=tk.TOP)

    def _dismiss_update_banner(self):
        """Hide the update banner for this session."""
        self._update_banner.pack_forget()

    def _open_update_url(self):
        """Open the release page in the user's default browser."""
        if not self._update_banner_url:
            return
        import webbrowser
        webbrowser.open(self._update_banner_url)

    def _handle_check_updates(self):
        """Manual 'Check for updates' button click."""
        if self._on_check_updates:
            self._on_check_updates()

    def set_update_check_running(self, running):
        """Toggle the 'Check for updates' button between idle / busy.

        ``True`` while the GitHub fetch is in flight: button reads
        "Checking…" and is disabled so the user can't queue up
        concurrent requests.  ``False`` returns it to the idle
        label.
        """
        if running:
            self._update_check_btn.configure(
                text="Checking…", state=tk.DISABLED)
        else:
            self._update_check_btn.configure(
                text="Check for updates", state=tk.NORMAL)

    def show_up_to_date_toast(self):
        """Inform the user the manual check found nothing.

        Called from app.py when ``check_for_update`` returns None on
        a manual request.  Auto-check runs at startup silently no-op
        in this case; only a user-initiated check triggers a
        modal so they have feedback that the click was received.
        """
        from pinball_decryptor import __version__ as _current
        messagebox.showinfo(
            "Up to date",
            f"You're on the latest version (v{_current}).")

    def _apply_theme(self, theme):
        c = THEMES[theme]
        self._current_theme = theme

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=c["bg"], foreground=c["fg"],
                        fieldbackground=c["field_bg"], bordercolor=c["border"],
                        troughcolor=c["trough"], selectbackground=c["select_bg"],
                        selectforeground="#ffffff", insertcolor=c["fg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe.Label", background=c["bg"],
                        foreground=c["fg"])
        style.configure("TButton", background=c["button"], foreground=c["fg"])
        style.map("TButton",
                  background=[("active", c["accent"]), ("pressed", c["accent"])],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
        # ttk.Checkbutton — clam's default flips the background to
        # white on hover/active, which makes our light-grey text
        # invisible in dark mode.  Pin the background to our panel
        # color in every state; convey hover via the indicator
        # accent colour instead.
        style.configure("TCheckbutton",
                        background=c["bg"], foreground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TCheckbutton",
                  background=[("active", c["bg"]),
                              ("selected", c["bg"]),
                              ("pressed", c["bg"])],
                  foreground=[("active", c["accent"]),
                              ("disabled", c["gray"])],
                  indicatorcolor=[("selected", c["accent"]),
                                  ("!selected", c["field_bg"])],
                  indicatorbackground=[("active", c["field_bg"])])
        # ttk.Radiobutton has the same clam-default hover bug.
        style.configure("TRadiobutton",
                        background=c["bg"], foreground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TRadiobutton",
                  background=[("active", c["bg"]),
                              ("selected", c["bg"]),
                              ("pressed", c["bg"])],
                  foreground=[("active", c["accent"]),
                              ("disabled", c["gray"])],
                  indicatorcolor=[("selected", c["accent"]),
                                  ("!selected", c["field_bg"])])
        style.configure("TEntry", fieldbackground=c["field_bg"],
                        foreground=c["fg"])
        # ttk.Combobox with state="readonly" otherwise renders as
        # disabled (gray-on-dark, illegible).  Force the readonly state
        # to use our normal field colors.  The dropdown popup is a Tk
        # Listbox (not ttk), so set it via the option DB.
        style.configure("TCombobox", fieldbackground=c["field_bg"],
                        foreground=c["fg"], background=c["bg"],
                        arrowcolor=c["fg"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", c["field_bg"]),
                                   ("disabled", c["field_bg"])],
                  foreground=[("readonly", c["fg"]),
                              ("disabled", c["gray"])],
                  selectbackground=[("readonly", c["select_bg"])],
                  selectforeground=[("readonly", "#ffffff")],
                  background=[("readonly", c["bg"])],
                  arrowcolor=[("readonly", c["fg"])])
        self.root.option_add("*TCombobox*Listbox.background",      c["field_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground",      c["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
        style.configure("TNotebook.Tab", background=c["button"],
                        foreground=c["fg"], padding=(10, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", c["tab_selected"]),
                              ("active", c["accent"])],
                  foreground=[("selected", c["fg"]), ("active", "#ffffff")])
        style.configure("Horizontal.TProgressbar",
                        troughcolor=c["trough"], background=c["accent"])
        style.configure("TSeparator", background=c["border"])
        # ttk.Treeview — default clam theme leaves rows white-on-black
        # text even when everything else around it is dark; the
        # Modified Files Preview tree on the Write tab needs explicit
        # styling.  Three style names matter: the body, the column
        # headers, and the selected-row state.
        style.configure(
            "Treeview",
            background=c["field_bg"],
            foreground=c["fg"],
            fieldbackground=c["field_bg"],
            bordercolor=c["border"],
            lightcolor=c["field_bg"],
            darkcolor=c["field_bg"])
        style.configure(
            "Treeview.Heading",
            background=c["button"],
            foreground=c["fg"],
            relief="flat")
        style.map(
            "Treeview.Heading",
            background=[("active", c["accent"])],
            foreground=[("active", "#ffffff")])
        style.map(
            "Treeview",
            background=[("selected", c["select_bg"])],
            foreground=[("selected", "#ffffff")])
        # Re-bind the row tag colors to the new theme so the tree
        # rows recolor when the user toggles dark/light mid-session.
        if hasattr(self, "_write_preview_tree"):
            self._write_preview_tree.tag_configure(
                "modified", foreground=c["link"])

        self.root.configure(background=c["bg"])
        # Re-skin EVERY cached per-mfr log widget — not just the currently-
        # visible one — so switching mfrs after a theme change still looks
        # right.
        for bundle in self._log_widgets.values():
            self._apply_log_theme(bundle["text"])
        # Rebuild the picker cards with the new theme colors.
        if hasattr(self, "_picker_view"):
            self._picker_view.apply_theme()

        if theme == "dark":
            self._theme_btn.configure(text="☀", style="Sun.TButton")
        else:
            self._theme_btn.configure(text="☽", style="Moon.TButton")
        icon_style = {"background": c["bg"], "borderwidth": 0, "relief": "flat"}
        style.configure("Sun.TButton", font=(_SANS_FONT, 14), padding=(4, 0),
                        foreground="#e6a817", **icon_style)
        style.map("Sun.TButton", background=[("active", c["button"])])
        style.configure("Moon.TButton", font=(_SANS_FONT, 14), padding=(4, 0),
                        foreground="#7b9fd4", **icon_style)
        style.map("Moon.TButton", background=[("active", c["button"])])

        # Match the Windows title bar to the theme via DWM's immersive
        # dark mode.  Walk to the actual title-bearing HWND: Tk's
        # winfo_id() returns the inner client-area HWND on Windows;
        # GetParent walks up to the toplevel that owns the title bar.
        # Earlier versions called GetForegroundWindow() instead, which
        # at startup is whatever the user was focused on (a terminal,
        # the launcher, Explorer) — so the dark title bar usually
        # landed on the wrong window or was silently skipped.
        if sys.platform == "win32":
            try:
                import ctypes
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if theme == "dark" else 0)
                inner_hwnd = self.root.winfo_id()
                title_hwnd = (ctypes.windll.user32.GetParent(inner_hwnd)
                              or inner_hwnd)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    title_hwnd,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(value),
                    ctypes.sizeof(value))
            except Exception:
                pass

        # Repaint the scrollable mfr-view canvas to the theme bg.  Tk
        # canvases default to system white, which otherwise shows
        # through as an empty white strip below the log whenever the
        # window is taller than the inner content.
        if hasattr(self, "_mfr_view_canvas"):
            try:
                self._mfr_view_canvas.configure(background=c["bg"])
            except Exception:
                pass
