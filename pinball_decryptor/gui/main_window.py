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
from tkinter import ttk, filedialog
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
                 on_theme_change=None, initial_theme=None):
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
        # 1080p display.  minsize stays modest because the scrollable
        # canvas + log handle smaller windows gracefully.
        root.geometry("820x940")
        root.minsize(700, 600)

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

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ---- Top bar: Back, title, theme toggle ----------------------
        top = ttk.Frame(root)
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
        self._mfr_view = ttk.Frame(root)
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

        row = ttk.Frame(f); row.pack(fill=tk.X, **pad)
        self._extract_input_lbl = ttk.Label(
            row, text="Input:", width=14, anchor=tk.W)
        self._extract_input_lbl.pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.extract_input_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_extract_input).pack(
            side=tk.LEFT, padx=(4, 0))

        self._extract_badge = ttk.Label(f, text="",
                                        font=(_SANS_FONT, 9, "italic"))
        self._extract_badge.pack(anchor=tk.W, padx=24, pady=(0, 2))
        self._extract_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("extract"))
        self._extract_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("extract", True))
        self._extract_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("extract", False))

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Output Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.extract_output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Browse...",
                   command=self._browse_extract_output).pack(
            side=tk.LEFT, padx=(4, 0))

        self._extract_warn = ttk.Label(f, text="", foreground="#f44747",
                                       font=(_SANS_FONT, 9))
        self._extract_warn.pack(anchor=tk.W, padx=24)

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

        row_upd = ttk.Frame(f); row_upd.pack(fill=tk.X, **pad)
        self._write_original_lbl = ttk.Label(
            row_upd, text="Original:", width=16, anchor=tk.W)
        self._write_original_lbl.pack(side=tk.LEFT)
        ttk.Entry(row_upd, textvariable=self.write_upd_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row_upd, text="Browse...",
                   command=self._browse_write_upd).pack(
            side=tk.LEFT, padx=(4, 0))

        self._write_badge = ttk.Label(f, text="",
                                      font=(_SANS_FONT, 9, "italic"))
        self._write_badge.pack(anchor=tk.W, padx=26, pady=(0, 2))
        self._write_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("write"))
        self._write_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("write", True))
        self._write_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("write", False))

        row = ttk.Frame(f); row.pack(fill=tk.X, **pad)
        ttk.Label(row, text="Modified Assets:", width=16, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row, textvariable=self.write_assets_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_write_assets).pack(
            side=tk.LEFT, padx=(4, 0))

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Output Folder:", width=16, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.write_output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Browse...",
                   command=self._browse_write_output).pack(
            side=tk.LEFT, padx=(4, 0))

        self._write_filename_lbl = ttk.Label(f, text="",
                                             font=(_SANS_FONT, 9, "italic"))
        self._write_filename_lbl.pack(anchor=tk.W, padx=26)

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
        else:
            self._write_phases_frame.pack_forget()
            self._extract_phases_frame.pack(
                fill=tk.X, before=self._progress_bar)

    # ------------------------------------------------------------------
    # View navigation (picker <-> manufacturer working view)
    # ------------------------------------------------------------------

    def show_picker(self):
        """Display the manufacturer picker and hide the working view."""
        self._mfr_view.pack_forget()
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
        self._mfr_view.pack(fill=tk.BOTH, expand=True)

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
        basic = self.static_extract_var.get()
        capture = self.capture_mode_var.get() and mfr.capabilities.capture
        if basic and capture:
            phases = mfr.combined_phases or mfr.extract_phases
        elif capture and not basic:
            phases = mfr.capture_phases or mfr.extract_phases
        else:  # basic only, or neither (treated as basic for display)
            phases = mfr.extract_phases
        if not self._extract_audio_supported:
            phases = tuple(p for p in phases if p != "Extract audio")
        self._rebuild_phase_steps(phases, mfr.write_phases)

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

        if sys.platform == "win32":
            try:
                import ctypes
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if theme == "dark" else 0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.windll.user32.GetForegroundWindow(),
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(value),
                    ctypes.sizeof(value))
            except Exception:
                pass
