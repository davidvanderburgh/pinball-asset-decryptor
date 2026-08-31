"""Emulate tab for Stern **Spike 1** — run a DMD-era Spike 1 game on this PC.

A SIBLING of :mod:`.emulate_tab` (Spike 2) and :mod:`.jjp_emulate_tab`, not an
extension of either — the same reasoning as the JJP tab: the Spike 2 panel is
welded to that rig's vocabulary, and threading a second rig through it would
carry two of everything. What the panels genuinely share — how a Windows path is
spelled for WSL, how a rig script is invoked, how ``key=value`` status is
parsed — lives in :mod:`._rig`.

This tab deliberately mirrors the **Spike 2 tab's layout** (David: "use the same
layout … we will need the same features too"): the card row with Browse / Cache,
the control-button row (Start, Restart WSL, Reset windows, Check setup), a Save
states panel, a Status grid, and the shared footer progress ladder. Where a
feature needs rig support that Spike 1 does not have yet (save states, a full
card cache), the widgets are present and honest about it rather than absent.

WHAT MAKES SPIKE 1 DIFFERENT
----------------------------
The game is a *static* armel ELF (no ``LD_PRELOAD`` seam), so its peripherals are
modelled one level down — a patched ``qemu-user`` plus a CUSE device model — and
the whole thing needs root, which on Windows is ``wsl -u root`` (passwordless).
There is no dongle, and the game is EXTRACTED from the card once (not run off it,
the way Spike 2 is). The display is a 128x32 **DMD**, not an LCD, so the picture
is a small dot-matrix window rather than a GL surface. Sound reuses the Spike 2
speaker chain end to end (the i2s shim tees paced PCM into a FIFO; playaudio.sh
owns the sink), so the volume/mute knob here is the SAME knob — same control
file, same ``PAD_AUDIO_CTL`` hand-off — and moves both rigs' loudness.

WHY THE PANEL IS THIN
---------------------
Every step of the launch — build, extract, seed, responder, game, windows —
lives in ``tools/spike1_emu/start.sh`` in the one order that works. This panel
starts it, stops it, and reports truthfully what it is doing.
"""

import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import _rig
# The volume/mute control FILE and its load/store belong to the Spike 2 tab
# (item 56) and are deliberately shared, not copied: one knob value, one file,
# read by the one padplay.py speaker implementation both rigs launch.
from .emulate_tab import (AUDIO_CTL_FILE, _load_audio_ctl, _write_audio_ctl,
                          windows_python)
from .spike1_windows import Spike1Viewers, wsl_unc
from .widgets import _Tooltip

#: The rig ships in the repo next to this package.  ``PAD_SPIKE1_EMU_DIR`` moves
#: it (parity with the JJP tab's ``PAD_JJP_EMU_DIR``).
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spike1_emu"
)


def rig_dir():
    return os.environ.get("PAD_SPIKE1_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present? Checked by script, not by directory — a half-copied tools tree
    is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("start.sh", "stop.sh", "status.sh"))


def rig_cmd(*args, **kw):
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def _load_dmd_decoder():
    """Import ``s1dmd.decode_frame`` from the rig dir — it is a script tree next
    to the rig, not an installed package, so load it by path."""
    import importlib.util
    p = os.path.join(rig_dir(), "s1dmd.py")
    spec = importlib.util.spec_from_file_location("s1dmd_gui", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def state_text(info):
    """(label, hint) for the State cell, from status.sh's key=value.

    Ordered the way a user hits the states: the FIRST thing that is not ready is
    what they are told about.
    """
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The emulator is a Linux program and runs inside WSL.")
    if int(info.get("game_procs") or 0) > 0:
        if info.get("keeper") == "0":
            # a dead keeper wears the game's own clothes: the machine sits on
            # "LOCATING PINBALLS. PLEASE WAIT" forever, which reads as a hung
            # boot (David hit exactly this, 2026-08-31).  Name the real fault.
            return ("No ball keeper", (
                "The game is up but the invisible-ball keeper died, so the "
                "machine cannot find its pinballs (the LOCATING PINBALLS "
                "screen). Press Stop, then Start."))
        if info.get("nodes_registered") == "1":
            # "Game running", matching the Spike 2 tab's wording (David: the
            # two tabs' texts flapped in the shared footer — "choose one").
            return "Game running", ("Boards registered; the DMD shows the "
                                    "attract.")
        return "Booting…", "The game is coming up on the emulator."
    if info.get("qemu_built") != "1":
        return ("Setup needed",
                "The ARM emulator has to be built once (a few minutes). Press "
                "Start — the first run builds it, then launches the game.")
    if info.get("game_ready") != "1":
        return ("No game extracted",
                "Pick a Spike 1 card image and press Start; the game is "
                "extracted from it the first time.")
    return "Not running", ""


#: Rig event logs streamed into the app's log window while a run is up
#: (David: "the emulation needs to output logs of any events to the log
#: window").  Each entry is (file in the run dir, tag, keep) — ``keep`` is a
#: regex a line must match to be forwarded, or None for every line.  The
#: keeper's log IS the event stream (serve/launch/drain/coin/door/service),
#: so it goes through whole; emu.log and audio.log are chatty, so only their
#: event-shaped lines pass.
_EVENT_LOGS = (
    ("s1ball.log", "ball", None),
    ("emu.log", "emu",
     re.compile(r"GAME RUN|RUN \d+ exited|PAD/spike1|FATAL|ERROR|error")),
    # under a checkpointable boot (S1_PIVOT, item 87) the game's own stdout —
    # including qemu's PAD/spike1 lines — moves inside the rootfs; the
    # ``rootfs`` symlink in the run dir reaches it, and on a chroot run the
    # file simply is not there (the tailer skips absentees).
    ("rootfs/dump/game.out", "emu",
     re.compile(r"PAD/spike1|FATAL|Fatal|Segmentation")),
    ("audio.log", "audio",
     re.compile(r"\[play\]|\[padrelay\]|restarting|volume ->|underruns\s+[1-9]")),
)
#: Protective caps for the shared log pane (a flooded Text widget is a known
#: UI-thread freeze class): at most this many lines per file per poll, and
#: lines are clipped.
_EVENT_LINES_PER_POLL = 12
_EVENT_LINE_CLIP = 300
#: A file bigger than this when the tailer attaches (tab reopened mid-run)
#: streams from its END rather than replaying the whole history.
_EVENT_REPLAY_MAX = 64 * 1024


class Spike1EmulatePanel:
    """The Spike 1 Emulate tab's widgets and its background poller."""

    POLL_MS = 2000
    POLL_IDLE_MS = 10000
    POLL_FIRST_MS = 700

    _STATES_TIP = (
        "Save states snapshot the running game and jump back to it later — "
        "mid-ball, across emulator restarts.\n\n"
        "• Save now freezes the game for a second or two and writes a slot "
        "(~15-50 MB on the WSL disk)\n"
        "• Load replaces the running game with the selected slot — the "
        "emulator must be running the same title\n"
        "• slots survive rebuilds (each carries the binaries it depends on) "
        "and stay on disk until deleted\n\n"
        "A GUI-started run always boots checkpointable (S1_PIVOT); command-"
        "line runs opt in with S1_PIVOT=1.")

    def __init__(self, parent, log=None, card_var=None, theme_fn=None,
                 badge_fn=None, resize_fn=None, footer_cb=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        self._card_var = card_var
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn or (lambda: None)
        #: drives the shared footer ladder (Extract / Boot / Node boards /
        #: Ready) — the main window injects ``set_emulate_progress``.
        self._footer_cb = footer_cb

        self._poll_job = None
        self._poll_busy = False
        self._polled_once = False
        self._stopped = False
        self._busy = False
        self._extracting = False
        self._last_up = False
        self._info = {}
        #: the pop-out DMD + switch windows (native, on-screen) — created lazily
        #: so a headless test never spawns Toplevels.
        self._viewers = None
        #: the rig-event log tailer: (thread, stop Event) while a run is up.
        self._log_tailer = None
        #: the slot manager's cached rows + the saves_mtime that produced
        #: them (status.sh reports it; a change triggers a re-list).
        self._slots_rows = []
        self._slots_mtime = None
        self._slots_busy = False
        #: the WINDOWS-side speaker (padplay.py) — owned by the APP, not the
        #: rig.  The rig's WSL side runs only the fifo + TCP relay
        #: (PAD_AUDIO_SINK=relay): launching a Windows exe from WSL depends on
        #: an interop socket that dies with the wsl.exe session that spawned
        #: start.sh, which is why a fresh app + fresh Start used to come up
        #: silent (2026-08-31 — the sounddevice probe hung forever).  The app
        #: is a Windows process, so it spawns the player itself and the audio
        #: path never crosses interop at all.
        self._player = None
        self._player_at = 0.0

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def _timer(self):
        """The TOPLEVEL, which outlives every tab — an ``after`` job on the tab
        frame would raise "can't delete Tcl command" during teardown."""
        return self._parent.winfo_toplevel()

    def _log(self, msg):
        """Log from ANY thread (Tk is not thread safe)."""
        try:
            self._timer().after(0, lambda: self._log_sink(msg))
        except (tk.TclError, RuntimeError):
            pass

    def card_path(self):
        return (self._card_var.get() if self._card_var is not None else "").strip()

    def _footer(self, kind, pct=None, text=""):
        if self._footer_cb is not None:
            try:
                self._footer_cb(kind, pct, text)
            except Exception:                              # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        pad = {"padx": 10, "pady": 4}

        intro = ttk.Label(
            frame, justify=tk.LEFT, wraplength=820,
            text=("Run a Stern Spike 1 (DMD-era) game on this PC. The game is a "
                  "static ARM binary, so it runs under a patched emulator with a "
                  "software model of the machine's boards — this needs WSL and "
                  "runs with root there.\n"
                  "Pick a card image: the game is extracted from it once and "
                  "kept, then boots and shows its attract on the dot-matrix "
                  "display — which opens in its own window, alongside a "
                  "switch/LED window you can click to inject switches."))
        intro.pack(anchor=tk.W, **pad)

        self._build_source(frame, pad)

        # --- control-button row (mirrors the Spike 2 tab) ----------------
        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, **pad)
        self._go_btn = ttk.Button(btns, text="Start emulator",
                                  command=self._toggle, width=16)
        self._go_btn.pack(side=tk.LEFT)

        self._reset_btn = ttk.Button(btns, text="Restart WSL…",
                                     command=self._fix_state, width=17)
        if sys.platform == "win32":
            self._reset_btn.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(self._reset_btn,
                 "Force-restart WSL to clear a wedged emulator. Closes ALL WSL "
                 "sessions and takes ~15s; your card and settings are untouched.",
                 self._theme_fn)

        self._winreset_btn = ttk.Button(btns, text="Reset windows",
                                        command=self._window_reset, width=15)
        self._winreset_btn.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(self._winreset_btn,
                 "Reopen the DMD / switch windows if they got lost or closed.",
                 self._theme_fn)

        self._check_btn = ttk.Button(btns, text="Check setup…",
                                     command=self._check_setup, width=14)
        self._check_btn.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(self._check_btn,
                 "Look at the rig without changing anything — build state, "
                 "extracted game, and whether it is running — and print it to "
                 "the log.", self._theme_fn)

        # The volume trio, mirroring the Spike 2 tab's row (and sharing its
        # control file — see the import note).  The knob is the emulator's OWN
        # volume to the PC speakers, not the game's coin-door adjustment, and
        # is deliberately LIVE — padplay.py polls the file, so dragging it
        # moves a running game's sound without a restart.
        vol0, mute0 = _load_audio_ctl()
        self._volume_var = tk.DoubleVar(value=vol0 * 100)
        self._mute_var = tk.BooleanVar(value=mute0)
        ttk.Label(btns, text="Volume:").pack(side=tk.LEFT, padx=(16, 0))
        self._vol_scale = ttk.Scale(btns, from_=0, to=100, length=110,
                                    orient=tk.HORIZONTAL,
                                    variable=self._volume_var,
                                    command=self._on_volume_change)
        self._vol_scale.pack(side=tk.LEFT, padx=(4, 0))
        self._mute_chk = ttk.Checkbutton(btns, text="Mute",
                                         variable=self._mute_var,
                                         command=self._on_volume_change)
        self._mute_chk.pack(side=tk.LEFT, padx=(6, 0))
        # Seed the control file now so it exists before the first Start (same
        # reasoning as the Spike 2 tab: padplay.py's own default must not be
        # what happens to agree).
        self._on_volume_change()

        self._build_states(frame, pad)

        # --- Status grid (same five-row shape as the Spike 2 tab) --------
        grid = ttk.LabelFrame(frame, text="Status")
        grid.pack(fill=tk.X, **pad)
        self._vals = {}
        rows = [
            ("state", "State:"),
            ("procs", "Processes:"),
            ("cpu", "Game CPU / memory:"),
            ("dmd", "DMD frames:"),
            ("boards", "Boards registered:"),
        ]
        for r, (key, label) in enumerate(rows):
            ttk.Label(grid, text=label, width=22, anchor=tk.W).grid(
                row=r, column=0, sticky=tk.W, padx=8, pady=2)
            v = ttk.Label(grid, text="—", anchor=tk.W)
            v.grid(row=r, column=1, sticky=tk.W, padx=4, pady=2)
            self._vals[key] = v
        grid.columnconfigure(1, weight=1)

        self._hint = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                               foreground="#888", text="")
        self._hint.pack(anchor=tk.W, **pad)

        self._note = ttk.Label(frame, wraplength=820, justify=tk.LEFT,
                               foreground="#c07a3a", text="")
        self._note.pack(anchor=tk.W, **pad)

        if not rig_available():
            self._note.configure(
                text="The Spike 1 emulator rig is missing from tools/spike1_emu "
                     "— this checkout looks incomplete.")
            self._go_btn.configure(state=tk.DISABLED)
        elif sys.platform != "win32":
            self._note.configure(
                text="The Spike 1 emulator runs through WSL, so this tab is "
                     "Windows-only.")
            self._go_btn.configure(state=tk.DISABLED)

        frame.bind("<Destroy>", self._on_destroy)
        self._schedule_poll(self.POLL_FIRST_MS)

    # ---- card row ----------------------------------------------------

    def _build_source(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Card image (extracted once, then kept)")
        box.pack(fill=tk.X, **pad)
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=8, pady=6)
        if self._card_var is None:
            self._card_var = tk.StringVar()
        self._card_entry = ttk.Entry(row, textvariable=self._card_var)
        self._card_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse…", width=10,
                   command=self._browse).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(row, text="Cache…", width=8,
                   command=self._open_cache_manager).pack(side=tk.LEFT,
                                                          padx=(6, 0))
        _Tooltip(self._card_entry,
                 "A Spike 1 game card image (.img/.raw/.vhd/.iso). The game is "
                 "extracted from it once and kept; after that you can Start "
                 "without a card.", self._theme_fn)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select a Spike 1 card image",
            filetypes=[("Spike 1 card image", "*.img *.raw *.vhd *.iso"),
                       ("All files", "*.*")])
        if path:
            self._card_var.set(path)

    # ---- save states (present, but inactive until criu is wired) -----

    def _info_badge(self, parent, tip):
        """The app's round blue ⓘ badge, or a plain marker without the window —
        same shape as the Spike 2 tab's, so the panel works standalone in tests."""
        if self._badge_fn is None:
            lbl = ttk.Label(parent, text="(i)", foreground="#2f80ed")
            lbl.icon_tip = _Tooltip(lbl, tip, self._theme_fn, place="side")
            return lbl
        badge = self._badge_fn(parent, "i", "#2f80ed", "#5296f2",
                               tip, lambda: None, size=18,
                               font=("Georgia", 10, "bold italic"),
                               tooltip_place="side")
        badge.bind("<Button-1>", lambda _e: badge.icon_tip.show(), add="+")
        return badge

    def _build_states(self, frame, pad):
        head = ttk.Frame(frame)
        ttk.Label(head, text="Save states").pack(side=tk.LEFT)
        self._info_badge(head, self._STATES_TIP).pack(side=tk.LEFT, padx=(6, 0))
        box = ttk.LabelFrame(frame, labelwidget=head)
        box.pack(fill=tk.X, **pad)

        wrap = ttk.Frame(box)
        wrap.pack(fill=tk.X, padx=8, pady=(2, 2))
        cols = ("slot", "name", "game", "size", "saved")
        self._slots_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                        height=3, selectmode="browse")
        for col, htext, width, anchor in (
                ("slot", "Slot", 90, tk.W), ("name", "Name", 220, tk.W),
                ("game", "Game", 150, tk.W), ("size", "Size", 80, tk.E),
                ("saved", "Saved", 120, tk.W)):
            self._slots_tree.heading(col, text=htext)
            self._slots_tree.column(col, width=width, anchor=anchor,
                                    stretch=(col == "name"))
        self._slots_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        side = ttk.Frame(wrap)
        side.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        self._slots_btns = []
        for text, cmd in (("Save now", self._slot_save),
                          ("Load", self._slot_load),
                          ("Refresh", self._slots_refresh),
                          ("Rename…", self._slot_rename),
                          ("Delete", self._slot_delete)):
            b = ttk.Button(side, text=text, width=10, command=cmd)
            b.pack(fill=tk.X, pady=1)
            self._slots_btns.append(b)

        self._slots_sum = ttk.Label(box, foreground="#888",
                                    text="The slots appear with the next "
                                         "status poll, or press Refresh.")
        self._slots_sum.pack(anchor=tk.W, padx=8, pady=(0, 6))

        if sys.platform != "win32" or not rig_available():
            # the slot scripts need root, which only WSL gives for free
            for b in self._slots_btns:
                b.configure(state=tk.DISABLED)
            self._slots_sum.configure(
                text="Slot management is available on Windows (WSL).")

    # -- slot manager ---------------------------------------------------

    @staticmethod
    def _fmt_size(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return "?"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return "%d %s" % (n, unit) if unit == "B" else \
                       "%.1f %s" % (n, unit)
            n /= 1024.0
        return "?"

    @staticmethod
    def _fmt_when(epoch):
        import datetime
        try:
            return datetime.datetime.fromtimestamp(
                int(epoch)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError, OverflowError):
            return "?"

    def _slot_selected(self):
        """The selected row's ``game/slot`` ref, or None."""
        try:
            sel = self._slots_tree.selection()
        except tk.TclError:
            return None
        if not sel:
            return None
        return sel[0]

    def _slots_refresh(self):
        """Re-read the slots as root, off the Tk thread, and repaint."""
        if self._slots_busy or sys.platform != "win32" or not rig_available():
            return
        self._slots_busy = True

        def run():
            rows, total, free = [], None, None
            try:
                out = subprocess.run(
                    rig_cmd_root("s1slots.sh", "list"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=30, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    p = line.strip().split("|", 5)
                    if p[0] == "slot" and len(p) >= 6:
                        rows.append({"ref": p[1], "bytes": p[2], "game": p[3],
                                     "label": p[4].strip(), "epoch": p[5]})
                    elif p[0] == "total" and len(p) >= 2:
                        total = p[1]
                    elif p[0] == "free" and len(p) >= 2:
                        free = p[1]
            except Exception:                              # noqa: BLE001
                pass

            def apply():
                self._slots_busy = False
                self._slots_rows = rows
                self._slots_paint(total, free)

            try:
                self._timer().after(0, apply)
            except (tk.TclError, RuntimeError):
                self._slots_busy = False

        threading.Thread(target=run, daemon=True).start()

    def _slots_paint(self, total=None, free=None):
        try:
            tree = self._slots_tree
            tree.delete(*tree.get_children())
            for row in self._slots_rows:
                slot = row["ref"].split("/", 1)[-1]
                tree.insert("", tk.END, iid=row["ref"], values=(
                    slot, row["label"], row["game"],
                    self._fmt_size(row["bytes"]),
                    self._fmt_when(row["epoch"])))
            if self._slots_rows:
                text = "%d slot%s — %s on disk" % (
                    len(self._slots_rows),
                    "" if len(self._slots_rows) == 1 else "s",
                    self._fmt_size(total))
                if free is not None:
                    text += " · %s free (WSL disk)" % self._fmt_size(free)
            else:
                text = ("No save states yet — Save now snapshots the running "
                        "game.")
            self._slots_sum.configure(text=text)
        except tk.TclError:
            pass

    def _slot_op(self, cmd_args, doing, then_refresh=True):
        """Run one root slot operation off the Tk thread, log its tagged
        output, and re-list."""

        def run():
            try:
                out = subprocess.run(
                    rig_cmd_root(*cmd_args),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=300, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8",
                                              "replace").splitlines():
                    line = line.strip()
                    if line:
                        self._log("Spike 1: " + line)
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: %s failed: %s" % (doing, exc))
            if then_refresh:
                try:
                    self._timer().after(0, self._slots_refresh)
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _slot_save(self):
        if int(self._info.get("game_procs") or 0) < 1:
            messagebox.showinfo(
                "Save state",
                "No game is running — start the emulator first, then Save "
                "now snapshots it mid-play.")
            return
        from tkinter import simpledialog
        name = simpledialog.askstring(
            "Save state", "Slot name (letters, digits, _ . - only):",
            initialvalue="quicksave", parent=self._parent)
        if not name:
            return
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            messagebox.showerror("Save state",
                                 "Slot names use letters, digits, _ . - only.")
            return
        self._log("Spike 1: saving the game to slot '%s'…" % name)
        self._slot_op(("s1savestate.sh", name), "save")

    def _slot_load(self):
        ref = self._slot_selected()
        if not ref:
            messagebox.showinfo("Load state", "Pick a slot to load.")
            return
        if int(self._info.get("game_procs") or 0) < 1:
            messagebox.showinfo(
                "Load state",
                "The emulator is not running. Start it on the slot's title "
                "first — Load then swaps the running game for the slot.")
            return
        self._log("Spike 1: loading slot '%s'…" % ref)
        self._slot_op(("s1restorestate.sh", ref), "load")

    def _slot_rename(self):
        ref = self._slot_selected()
        if not ref:
            messagebox.showinfo("Rename", "Pick a slot to rename.")
            return
        row = next((r for r in self._slots_rows if r["ref"] == ref), None)
        from tkinter import simpledialog
        label = simpledialog.askstring(
            "Rename slot", "Name for %s:" % ref,
            initialvalue=(row or {}).get("label", ""), parent=self._parent)
        if label is None:
            return
        self._slot_op(("s1slots.sh", "label", ref, label), "rename")

    def _slot_delete(self):
        ref = self._slot_selected()
        if not ref:
            messagebox.showinfo("Delete", "Pick a slot to delete.")
            return
        if not messagebox.askyesno(
                "Delete slot", "Delete the save state %s?\n\n"
                "This frees its disk space and cannot be undone." % ref):
            return
        self._slot_op(("s1slots.sh", "delete", ref), "delete")

    # ------------------------------------------------------------------

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self._parent:
            return
        self._stopped = True
        j = self._poll_job
        if j:
            try:
                self._timer().after_cancel(j)
            except (tk.TclError, RuntimeError, ValueError):
                pass
            self._poll_job = None
        self._close_viewers()
        self._stop_log_tail()
        self._stop_player()

    # ------------------------------------------------------------------
    # pop-out DMD + switch windows
    # ------------------------------------------------------------------

    def _ensure_viewers(self):
        if self._viewers is None:
            try:
                mod = _load_dmd_decoder()
            except Exception:                              # noqa: BLE001
                return None
            self._viewers = Spike1Viewers(
                master_fn=self._timer,
                decode_frame=mod.decode_frame, log=self._log)
        return self._viewers

    def _open_viewers(self):
        v = self._ensure_viewers()
        if v is None:
            return
        work = self._info.get("work")
        distro = self._info.get("distro")
        if work and distro:
            v.configure(work, distro)
            v.open()

    def _close_viewers(self):
        if self._viewers is not None:
            try:
                self._viewers.close()
            except Exception:                              # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # rig event logs -> the app's log window
    # ------------------------------------------------------------------

    def _start_log_tail(self):
        """Stream the run's event logs into the app log while it runs.

        A plain UNC tail, like the viewer windows: the run dir's files are
        read straight off the WSL disk, no ``wsl.exe`` per poll.  Started
        when a run is first seen, stopped when it ends or the tab dies."""
        if self._log_tailer is not None:
            return
        work = self._info.get("work")
        distro = self._info.get("distro")
        if not (work and distro):
            return
        stop = threading.Event()
        t = threading.Thread(target=self._tail_event_logs,
                             args=(work, distro, stop), daemon=True)
        self._log_tailer = (t, stop)
        t.start()

    def _stop_log_tail(self):
        if self._log_tailer is not None:
            self._log_tailer[1].set()
            self._log_tailer = None

    def _tail_event_logs(self, work, distro, stop):
        pos = {}                      # file -> read offset
        while not stop.wait(1.0):
            for name, tag, keep in _EVENT_LOGS:
                p = wsl_unc(distro, work.rstrip("/") + "/" + name)
                if not p:
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue          # absent / WSL briefly away
                if name not in pos:
                    # first sight: replay a fresh run's history, but attach at
                    # the END of an already-long file (tab reopened mid-run)
                    pos[name] = 0 if size <= _EVENT_REPLAY_MAX else size
                if size < pos[name]:
                    pos[name] = 0     # rig restarted: the file was truncated
                if size == pos[name]:
                    continue
                try:
                    with open(p, "rb") as f:
                        f.seek(pos[name])
                        raw = f.read(256 * 1024)
                except OSError:
                    continue
                # consume whole lines only, so a line caught mid-write is
                # forwarded once, complete, on the next poll
                cut = raw.rfind(b"\n")
                if cut < 0:
                    continue
                pos[name] += cut + 1
                chunk = raw[:cut + 1].decode("utf-8", "replace")
                lines = [ln.strip() for ln in chunk.splitlines()]
                lines = [ln for ln in lines
                         if ln and (keep is None or keep.search(ln))]
                extra = len(lines) - _EVENT_LINES_PER_POLL
                for ln in lines[:_EVENT_LINES_PER_POLL]:
                    self._log("Spike 1 [%s] %s" % (tag, ln[:_EVENT_LINE_CLIP]))
                if extra > 0:
                    self._log("Spike 1 [%s] … %d more lines in %s"
                              % (tag, extra, name))

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _toggle(self):
        if self._busy:
            return
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()

    def _start_async(self):
        card = self.card_path()
        if not card and self._info.get("game_ready") != "1":
            messagebox.showinfo(
                "Emulate",
                "Pick a Spike 1 card image first.\n\nThe game is extracted from "
                "it once and kept — after that you can Start without a card.")
            return

        self._busy = True
        self._go_btn.configure(state=tk.DISABLED, text="Starting…")
        # If a game still has to be extracted, the first stretch is the extract
        # phase — light the footer's first chip for it.
        self._extracting = self._info.get("game_ready") != "1" and bool(card)

        def work():
            try:
                if self._info.get("qemu_built") != "1":
                    self._log("Spike 1: first run — building the emulator, this "
                              "takes a few minutes. Each step is shown below.")
                args = [card] if card else []
                # PAD_AUDIO=1: a GUI-started run plays sound (scripted runs
                # stay muted by default — start.sh's own default).  The ctl
                # file is a native Windows path, handed over by NAME exactly
                # as the Spike 2 tab does it; playaudio.sh forwards it to the
                # Windows padplay.py through WSLENV.
                # S1_PIVOT=1: a GUI-started run always boots CHECKPOINTABLE
                # (pivot_root) so the save-state controls simply work — the
                # same stance the Spike 2 tab settled on.  A machine missing
                # the pivot prerequisites falls back to the ordinary boot and
                # says so in the streamed log (save states off, nothing else
                # changes).
                # PAD_AUDIO_SINK=relay: the rig runs fifo + TCP relay only;
                # THIS APP spawns the Windows speaker (see _ensure_player) —
                # the rig launching one itself needs WSL interop, which dies
                # with start.sh's wsl.exe and wedged the whole chain silent.
                env = ["PAD_AUDIO=1", "PAD_AUDIO_CTL=" + AUDIO_CTL_FILE,
                       "PAD_AUDIO_SINK=relay", "S1_PIVOT=1"]
                rc = self._run_streaming(rig_cmd_root("start.sh", *args,
                                                      env=env),
                                         timeout=1800)
                if rc not in (0, None):
                    self._log("Spike 1: start failed (exit %d)." % rc)
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: start failed: %s" % exc)
            finally:
                self._extracting = False
                self._release()

        threading.Thread(target=work, daemon=True).start()

    def _run_streaming(self, cmd, timeout=1800):
        """Run a rig command, logging each line as it prints (a build or an
        extraction is minutes long — a captured-then-logged-once launch reads as
        a frozen app).  Bounded by ``timeout`` so a wedged step cannot block
        forever."""
        timed_out = {"v": False}
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True,
                creationflags=_rig.CREATE_FLAGS)
        except Exception as exc:                           # noqa: BLE001
            self._log("Spike 1: could not start the rig: %s" % exc)
            return None

        def _kill():
            timed_out["v"] = True
            try:
                proc.kill()
            except Exception:                              # noqa: BLE001
                pass

        killer = threading.Timer(timeout, _kill)
        killer.daemon = True
        killer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log("Spike 1: " + line)
                    # the extract phase ends when the game files land
                    if "extracted" in line and "game files" in line:
                        self._extracting = False
        finally:
            killer.cancel()
            try:
                proc.stdout.close()
            except Exception:                              # noqa: BLE001
                pass
            proc.wait()
        if timed_out["v"]:
            self._log("Spike 1: start timed out — the rig was stopped.")
        return proc.returncode

    def _stop_async(self):
        self._busy = True
        self._go_btn.configure(state=tk.DISABLED, text="Stopping…")

        def work():
            try:
                out = subprocess.run(
                    rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=_rig.CREATE_FLAGS)
                self._log("Spike 1: "
                          + out.stdout.decode("utf-8", "replace").strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: stop failed: %s" % exc)
            finally:
                self._stop_player()
                self._release()

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    # the Windows-side speaker (see the __init__ note for why the app owns it)
    # ------------------------------------------------------------------

    def _player_cmd(self):
        """The speaker command: PAD's own console python running padplay.py
        against the rig's relay.  None when a piece is missing."""
        py = windows_python(console=True)
        pp = os.path.join(os.path.dirname(rig_dir()), "spike2_emu",
                          "padplay.py")
        if not py or not os.path.isfile(pp):
            return None
        return [py, pp, "127.0.0.1", "45998", "44100", "2"]

    def _ensure_player(self):
        """Keep one Windows player alive while a run is up.  Called from the
        status poll; a player that exited (relay not up yet, the 25 s no-data
        watchdog, a crash) is relaunched with a 5 s backoff — connection
        refused costs one instant exit per attempt, nothing more."""
        if sys.platform != "win32":
            return
        p = self._player
        if p is not None and p.poll() is None:
            return
        now = time.monotonic()
        if now - self._player_at < 5.0:
            return
        cmd = self._player_cmd()
        if not cmd:
            return
        self._player_at = now
        env = dict(os.environ)
        env["PAD_AUDIO_CTL"] = AUDIO_CTL_FILE
        try:
            self._player = subprocess.Popen(
                cmd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            if p is None:
                self._log("Spike 1: speaker up (app-side Windows player).")
        except Exception as exc:                           # noqa: BLE001
            self._log("Spike 1: could not start the speaker: %s" % exc)
            self._player = None

    def _stop_player(self):
        p = self._player
        self._player = None
        if p is None:
            return
        try:
            p.kill()
        except Exception:                                  # noqa: BLE001
            pass

    def _release(self):
        def done():
            self._busy = False
            try:
                self._go_btn.configure(state=tk.NORMAL)
            except tk.TclError:
                return
            self._poll()
        try:
            self._timer().after(0, done)
        except (tk.TclError, RuntimeError):
            self._busy = False

    def _on_volume_change(self, *_args):
        """Volume/Mute changed — write the live control file (shared with the
        Spike 2 tab; see the import note).  ``*_args`` because ``ttk.Scale``
        calls back with the new value and the Checkbutton with nothing — both
        ignored, the vars are already current."""
        gain = max(0.0, min(1.0, self._volume_var.get() / 100.0))
        _write_audio_ctl(gain, bool(self._mute_var.get()))

    def _fix_state(self):
        """Force-restart WSL to recover a wedged emulator (the escalation past
        Stop — a frozen window, a game that will not stop, orphaned devices)."""
        if self._busy:
            return
        if sys.platform != "win32":
            messagebox.showinfo(
                "Restart WSL",
                "This recovery restarts WSL and only applies on Windows.")
            return
        if not messagebox.askyesno(
                "Restart WSL",
                "Force-restart WSL to clear a wedged emulator?\n\n"
                "Use this when Stop did not work. It closes EVERYTHING running "
                "in WSL (other terminals too) and takes about 15 seconds. Your "
                "card and settings are untouched."):
            return

        self._busy = True
        self._go_btn.configure(state=tk.DISABLED)
        self._reset_btn.configure(state=tk.DISABLED, text="Restarting…")

        def work():
            try:
                self._log("Spike 1: shutting WSL down to clear stuck state…")
                out = subprocess.run(
                    ["wsl.exe", "--shutdown"], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=120,
                    creationflags=_rig.CREATE_FLAGS)
                if out.returncode == 0:
                    self._log("Spike 1: WSL was shut down — stuck processes and "
                              "frozen windows are cleared. Press Start to run "
                              "again.")
                else:
                    self._log("Spike 1: wsl --shutdown returned %d. %s"
                              % (out.returncode,
                                 out.stdout.decode("utf-8", "replace").strip()))
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: could not restart WSL: %s" % exc)
            finally:
                self._timer().after(0, self._reset_done)

        threading.Thread(target=work, daemon=True).start()

    def _reset_done(self):
        self._busy = False
        try:
            self._go_btn.configure(state=tk.NORMAL)
            self._reset_btn.configure(state=tk.NORMAL, text="Restart WSL…")
        except tk.TclError:
            return
        self._poll()

    def _window_reset(self):
        """Reopen the DMD / switch windows and pull them back on-screen — the
        escape hatch for a window dragged to a monitor that went away, or one
        that was closed."""
        if not self._last_up:
            self._log("Spike 1: nothing running — start the emulator first.")
            return
        self._open_viewers()
        if self._viewers is not None:
            self._viewers.reset()
        self._log("Spike 1: DMD and switch windows reopened.")

    def _check_setup(self):
        """Read-only: print the rig's state to the log (build, extracted game,
        run state), so 'press Check setup and paste what it says' is one paste.
        Never mutates."""
        if sys.platform != "win32":
            self._log("Spike 1: Check setup is available on Windows (WSL).")
            return

        def work():
            try:
                out = subprocess.run(
                    rig_cmd("status.sh"), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=25,
                    creationflags=_rig.CREATE_FLAGS)
                info = _rig.parse_status(
                    out.stdout.decode("utf-8", "replace"))
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: check failed: %s" % exc)
                return
            yn = lambda k: "yes" if info.get(k) == "1" else "no"  # noqa: E731
            self._log("Spike 1 setup — emulator built: %s · device model: %s · "
                      "game extracted: %s · running: %s"
                      % (yn("qemu_built"), yn("hwshim_built"), yn("game_ready"),
                         "yes" if int(info.get("game_procs") or 0) else "no"))

        threading.Thread(target=work, daemon=True).start()

    # ---- extracted-game cache -----------------------------------------

    @staticmethod
    def _human_kb(kb):
        try:
            kb = float(kb)
        except (TypeError, ValueError):
            return "?"
        for unit in ("KB", "MB", "GB", "TB"):
            if kb < 1024 or unit == "TB":
                return "%.0f %s" % (kb, unit) if unit == "KB" \
                    else "%.1f %s" % (kb, unit)
            kb /= 1024.0

    @staticmethod
    def _parse_cache(text):
        """cache.sh list -> (rows, disk_free_kb).  Rows are dicts."""
        rows, free = [], None
        for line in text.splitlines():
            f = line.split("\t")
            if f[0] == "entry" and len(f) >= 6:
                rows.append({"label": f[1], "kb": f[2], "boot": f[3],
                             "game": f[4], "active": f[5] == "1"})
            elif f[0] == "disk" and len(f) >= 2:
                free = f[1]
        rows.sort(key=lambda r: int(r["boot"] or 0), reverse=True)
        return rows, free

    def _open_cache_manager(self):
        if sys.platform != "win32":
            messagebox.showinfo("Cache",
                                "The extracted-game cache lives in WSL, so it "
                                "is managed on Windows.")
            return
        win = tk.Toplevel(self._parent)
        win.title("Extracted games — Spike 1 emulator")
        win.geometry("640x340")
        ttk.Label(win, justify=tk.LEFT, wraplength=600,
                  text="Each card you Start is extracted once and kept here, so "
                       "switching between titles reuses the extraction instead of "
                       "re-extracting (~1 min). The one in use is marked ‘active’ "
                       "and can't be deleted.").pack(anchor="w", padx=12,
                                                     pady=(12, 6))
        cols = ("game", "label", "size", "used", "active")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=7,
                            selectmode="browse")
        for c, htext, w, anchor in (("game", "Game", 150, tk.W),
                                    ("label", "Card", 200, tk.W),
                                    ("size", "Size", 80, tk.E),
                                    ("used", "Last used", 90, tk.W),
                                    ("active", "", 60, tk.W)):
            tree.heading(c, text=htext)
            tree.column(c, width=w, anchor=anchor, stretch=(c == "label"))
        tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))
        header = ttk.Label(win, text="Reading…", foreground="#888")
        header.pack(anchor="w", padx=12)
        foot = ttk.Frame(win)
        foot.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=10)
        ttk.Button(foot, text="Close", command=win.destroy).pack(side=tk.RIGHT)
        delete = ttk.Button(foot, text="Delete selected", state=tk.DISABLED)
        delete.pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(foot, text="Refresh",
                   command=lambda: reload_()).pack(side=tk.RIGHT, padx=(0, 6))

        state = {"rows": []}

        def reload_():
            def work():
                try:
                    out = subprocess.run(
                        rig_cmd("cache.sh", "list"), stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, timeout=30,
                        creationflags=_rig.CREATE_FLAGS)
                    rows, free = self._parse_cache(
                        out.stdout.decode("utf-8", "replace"))
                except Exception:                          # noqa: BLE001
                    rows, free = [], None

                def apply():
                    if not win.winfo_exists():
                        return
                    state["rows"] = rows
                    tree.delete(*tree.get_children())
                    import time as _t
                    now = _t.time()
                    for r in rows:
                        age = now - int(r["boot"] or 0)
                        used = ("just now" if age < 90
                                else "%dh ago" % (age // 3600) if age < 86400
                                else "%dd ago" % (age // 86400))
                        tree.insert("", "end", iid=r["label"],
                                    values=(r["game"], r["label"],
                                            self._human_kb(r["kb"]),
                                            used, "active" if r["active"] else ""))
                    total = sum(int(r["kb"] or 0) for r in rows)
                    header.configure(
                        text="%d cached — %s on disk · %s free (WSL disk)"
                             % (len(rows), self._human_kb(total),
                                self._human_kb(free)))
                try:
                    win.after(0, apply)
                except tk.TclError:
                    pass
            threading.Thread(target=work, daemon=True).start()

        def on_select(_e=None):
            sel = tree.selection()
            row = next((r for r in state["rows"] if r["label"] in sel), None)
            delete.configure(state=tk.NORMAL if (row and not row["active"])
                             else tk.DISABLED)
        tree.bind("<<TreeviewSelect>>", on_select)

        def do_delete():
            sel = tree.selection()
            if not sel:
                return
            label = sel[0]
            if not messagebox.askyesno(
                    "Delete cached game",
                    "Delete the cached extraction for %s? The next Start from "
                    "that card will extract it again (~1 minute)." % label,
                    parent=win):
                return
            delete.configure(state=tk.DISABLED)

            def work():
                try:
                    subprocess.run(
                        rig_cmd_root("cache.sh", "drop", label),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=60, creationflags=_rig.CREATE_FLAGS)
                    self._log("Spike 1: deleted cached extraction %s." % label)
                except Exception as exc:                   # noqa: BLE001
                    self._log("Spike 1: delete failed: %s" % exc)
                try:
                    win.after(0, reload_)
                except tk.TclError:
                    pass
            threading.Thread(target=work, daemon=True).start()

        delete.configure(command=do_delete)
        reload_()

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------

    def _schedule_poll(self, ms=None):
        if self._stopped:
            return
        if ms is None:
            if not self._polled_once:
                ms = self.POLL_FIRST_MS
            else:
                ms = self.POLL_MS if self._last_up else self.POLL_IDLE_MS
        try:
            self._poll_job = self._timer().after(ms, self._poll)
        except (tk.TclError, RuntimeError):
            self._poll_job = None

    def _poll(self):
        self._poll_job = None
        if self._stopped or not rig_available() or sys.platform != "win32":
            return
        if self._poll_busy or self._busy:
            self._schedule_poll()
            return
        self._poll_busy = True

        def run():
            try:
                out = subprocess.run(
                    rig_cmd("status.sh"), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=25,
                    creationflags=_rig.CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                              # noqa: BLE001
                text = ""
            info = _rig.parse_status(text)
            if self._stopped:
                self._poll_busy = False
                return

            def apply_and_release():
                self._poll_busy = False
                self._polled_once = True
                self._apply(info)

            try:
                self._timer().after(0, apply_and_release)
            except (tk.TclError, RuntimeError):
                self._poll_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._schedule_poll()

    def _apply(self, info):
        try:
            self._info = info
            self._last_up = int(info.get("game_procs") or 0) > 0
            label, hint = state_text(info)
            if self._busy and self._extracting:
                label = "Extracting the game…"
            self._vals["state"].configure(text=label)
            self._hint.configure(text=hint if not self._busy else "")
            if not self._busy:
                self._go_btn.configure(text="Stop" if self._last_up
                                       else "Start emulator")

            procs = info.get("game_procs", "0")
            self._vals["procs"].configure(
                text="%s running%s" % (procs,
                                       "  (all stopped)" if procs == "0"
                                       else ""))
            if self._last_up:
                cpu = info.get("cpu", "?")
                rss = info.get("rss_mb", "?")
                up = int(info.get("game_uptime_s") or 0)
                uptxt = "  ·  up %d:%02d" % (up // 60, up % 60) if up else ""
                self._vals["cpu"].configure(
                    text="%s%% of one core, %s MB%s" % (cpu, rss, uptxt))
            else:
                self._vals["cpu"].configure(text="—")
            self._vals["dmd"].configure(text=info.get("dmd_frames", "0"))
            if not self._last_up:
                self._vals["boards"].configure(text="—")
            else:
                self._vals["boards"].configure(
                    text="yes" if info.get("nodes_registered") == "1"
                    else "not yet")

            # the app-side speaker follows the run: alive while a game is up,
            # gone when it is not (padplay also self-exits when the relay
            # closes or the PCM stops for 25 s — this is the belt half).
            if self._last_up:
                self._ensure_player()
            else:
                self._stop_player()

            # re-list the save slots when their directory changed (a save, a
            # delete — status.sh reports the saves dir's mtime), and once on
            # the first poll so the manager fills without a button press.
            sm = info.get("saves_mtime")
            if sm != self._slots_mtime:
                self._slots_mtime = sm
                self._slots_refresh()

            # drive the shared footer ladder (Extract / Boot / Node boards / Ready)
            if self._busy and self._extracting:
                self._footer("copy", 50, "Extracting the game…")
            elif self._last_up and info.get("nodes_registered") == "1":
                self._footer("run", None, "Game running")
            elif self._last_up:
                self._footer("boot", None, "Booting…")
            elif not self._busy:
                self._footer("idle")

            # status note while it runs
            if self._last_up and info.get("nodes_registered") == "1":
                self._note.configure(
                    text="The game is running and the boards registered — it "
                         "boots to its attract on the DMD, with the switch/LED "
                         "window beside it. Click a switch cell to inject it.")
            elif not self._last_up:
                self._note.configure(text="")

            # open the pop-out windows + event-log tail while running, close
            # them when it stops
            if self._last_up:
                self._open_viewers()
                self._start_log_tail()
            else:
                self._close_viewers()
                self._stop_log_tail()
        except tk.TclError:
            pass    # widgets went away under us during shutdown

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------

    def shutdown_sync(self):
        """App-quit hook: take the emulator down with the app (blocking,
        bounded).  A quit must not leave the game, the CUSE daemons and the
        viewer windows orphaned behind a control surface that is gone."""
        self._stopped = True
        self._close_viewers()
        self._stop_log_tail()
        if not rig_available() or sys.platform != "win32":
            return
        if not (self._last_up or self._info.get("responder") == "1"):
            return
        try:
            subprocess.run(rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass
