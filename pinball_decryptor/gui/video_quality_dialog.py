"""The video-quality report: which clips ALREADY on a card look blocky.

A size-neutral Write squeezes a replacement clip down into the byte slot it
replaces, and says so once, in the log, while it is doing it ("it will look
very blocky").  That is the only time the app has ever mentioned it — so a
user who has built a dozen editions over a year, and wants to know whether any
of the clips on those finished cards came out badly, has nothing to ask.  The
build logs are long gone and the project folder holds the *sources*, not what
landed on the card.

This window asks the card instead.  Pick a card image, press Check, and every
clip on it is measured by the same rule the warning uses
(:mod:`core.video_quality`) and listed worst first.

Two things it deliberately says out loud, because getting them wrong sends a
user off to re-encode for nothing (which is exactly what happened before the
warning carried a reason):

* a clip PAD **squeezed into its slot** is one a rebuild can fix — build an
  image file with WSL working and it goes on whole instead;
* a clip that is simply a **small file** is on the card exactly as the user's
  own encoder made it, and no amount of rebuilding will improve it.

Nothing is written; the card image is opened read-only.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import video_quality
from .placement import centered_over
from .theme import THEMES, dark_titlebar, platform_font

_COLUMNS = (
    ("len", "Length", 70),
    ("res", "Resolution", 90),
    ("rate", "Bitrate", 90),
    ("verdict", "Quality", 170),
)


class VideoQualityDialog:
    """Non-modal report window over one card image's video clips."""

    def __init__(self, parent, manufacturer, theme_name, card_path="",
                 initial_dir=None, on_log=None):
        self._parent = parent
        self._mfr = manufacturer
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._on_log = on_log or (lambda *_a, **_k: None)
        self._initial_dir = initial_dir if (
            initial_dir and os.path.isdir(initial_dir)) else None
        self._sans, _ = platform_font()
        self._clips = []
        self._busy = False
        self._cancel = False
        self._scan_id = 0            # bump-counter: a stale result is dropped
        self._result = None          # (scan_id, clips, error) from the worker

        self._build()
        self._card_var.set(card_path or "")

    # ------------------------------------------------------------------
    def _build(self):
        th = self._theme
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        # Built hidden and mapped at the end, like the other dialogs: centring
        # forces an update_idletasks and a visible window would flash empty at
        # its default spot first.
        dlg.withdraw()
        dlg.title("Check the videos on a card")
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.protocol("WM_DELETE_WINDOW", self._close)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Check the videos already on a card",
                  font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body,
            text=("Measures every clip on a built card image and lists the "
                  "ones whose bitrate is low enough to look blocky — the same "
                  "test a Write applies to a replacement, applied after the "
                  "fact to what is actually on the card. This reads the card "
                  "image only; nothing is written and nothing is extracted."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=760, justify="left").pack(anchor="w", pady=(0, 12))

        card_row = ttk.Frame(body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text="Card image:", width=12, anchor="w").pack(
            side="left")
        self._card_var = tk.StringVar()
        self._card_entry = ttk.Entry(card_row, textvariable=self._card_var)
        self._card_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(card_row, text="Browse…", command=self._browse).pack(
            side="left", padx=(4, 0))
        self._check_btn = ttk.Button(card_row, text="Check",
                                     command=self._start, style="Go.TButton")
        self._check_btn.pack(side="left", padx=(8, 0))

        # Summary: up to three sentences, so it is given room to be three.
        self._summary = ttk.Label(
            body, text="Pick a card image and press Check.",
            font=(self._sans, 9), wraplength=760, justify="left")
        self._summary.pack(anchor="w", fill="x", pady=(12, 6))

        list_frame = ttk.Frame(body)
        list_frame.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(
            list_frame, columns=[c[0] for c in _COLUMNS], height=14,
            selectmode="browse")
        self._tree.heading("#0", text="Clip")
        self._tree.column("#0", width=300, minwidth=160, stretch=True)
        for key, title, width in _COLUMNS:
            self._tree.heading(key, text=title)
            self._tree.column(key, width=width, minwidth=60, anchor="w",
                              stretch=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical",
                               command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        # A blocky row is the answer to the question asked — colour it so the
        # list reads at a glance on a card with hundreds of clips.
        self._tree.tag_configure("blocky", foreground=th["error"])
        self._tree.tag_configure("unknown", foreground=th["gray"])

        opts = ttk.Frame(body)
        opts.pack(fill="x", pady=(8, 0))
        self._only_bad = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Show only the clips below the bar",
                        variable=self._only_bad,
                        command=self._repaint).pack(side="left")
        self._copy_btn = ttk.Button(opts, text="Copy report",
                                    command=self._copy, state=tk.DISABLED)
        self._copy_btn.pack(side="right")
        ttk.Button(opts, text="Close", command=self._close).pack(
            side="right", padx=(0, 8))

        dlg.bind("<Escape>", lambda _e: self._close())
        self._center()
        dlg.deiconify()
        dlg.lift()

    def _center(self):
        dlg = self._dlg
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 820)
        dh = max(dlg.winfo_reqheight(), 560)
        x, y = centered_over(self._parent, dw, dh)
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, x, y))
        dlg.minsize(680, 460)

    def _refit(self):
        """Grow the window to fit its content again, never shrink it.

        The summary is one line before a scan and three after it ("38 of 658…
        None of them were squeezed… Re-export those clips…"), and a window
        sized on the one-line version simply clips the overflow — which ate
        the filter tick and the Copy/Close row the first time this was
        photographed.  Shrinking again would make the window twitch while a
        user re-checks card after card.
        """
        dlg = self._dlg
        try:
            dlg.update_idletasks()
            want = dlg.winfo_reqheight()
            if want > dlg.winfo_height():
                dlg.geometry("%dx%d" % (max(dlg.winfo_width(), 820), want))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _browse(self):
        path = filedialog.askopenfilename(
            parent=self._dlg, title="Pick a card image to check",
            initialdir=self._initial_dir or None,
            filetypes=[("Card images", "*.raw *.img *.bin"),
                       ("All files", "*.*")])
        if path:
            self._card_var.set(path)

    # ------------------------------------------------------------------
    def _start(self):
        if self._busy:
            # The button doubles as Stop while a scan runs: a card that turns
            # out to be the wrong one should not hold the window for a minute.
            self._cancel = True
            self._summary.configure(text="Stopping…")
            return
        path = (self._card_var.get() or "").strip().strip('"')
        if not os.path.isfile(path):
            messagebox.showwarning(
                "Pick a card image",
                "Pick the .raw / .img card image you want to check.",
                parent=self._dlg)
            return
        self._scan_id += 1
        scan_id = self._scan_id
        self._busy = True
        self._cancel = False
        self._result = None
        self._clips = []
        self._tree.delete(*self._tree.get_children(""))
        self._copy_btn.configure(state=tk.DISABLED)
        self._check_btn.configure(text="Stop")
        self._summary.configure(text="Reading %s…" % os.path.basename(path))

        def work():
            clips, err = [], ""
            try:
                clips = self._mfr.video_quality(
                    path, log=self._on_log, progress=None,
                    cancel=lambda: self._cancel) or []
            except Exception as e:
                err = str(e) or e.__class__.__name__
            self._result = (scan_id, clips, err)

        threading.Thread(target=work, daemon=True).start()
        self._dlg.after(120, lambda: self._poll(scan_id))

    def _poll(self, scan_id):
        if scan_id != self._scan_id:
            return                       # a newer scan owns the window now
        res = self._result
        if res is None:
            try:
                self._dlg.after(120, lambda: self._poll(scan_id))
            except tk.TclError:
                pass                     # window closed under the scan
            return
        _sid, clips, err = res
        self._busy = False
        try:
            self._check_btn.configure(text="Check")
        except tk.TclError:
            return
        if err:
            self._summary.configure(
                text="Could not read that card image: %s" % err)
            self._refit()
            return
        if self._cancel and not clips:
            self._summary.configure(text="Stopped.")
            return
        self._clips = video_quality.sort_worst_first(clips)
        self._summary.configure(text=" ".join(
            video_quality.summary_lines(self._clips)))
        self._copy_btn.configure(
            state=(tk.NORMAL if self._clips else tk.DISABLED))
        self._repaint()
        self._refit()

    # ------------------------------------------------------------------
    def _repaint(self):
        tree = self._tree
        tree.delete(*tree.get_children(""))
        only_bad = self._only_bad.get()
        shown = 0
        for c in self._clips:
            if only_bad and c.verdict == "ok":
                continue
            shown += 1
            tree.insert("", "end", text=c.name,
                        values=(c.length_str(), c.resolution_str(),
                                c.bitrate_str(), c.quality_str()),
                        tags=(c.verdict,))
        if self._clips and not shown:
            # An empty list under a "38 clips" summary reads as a failure;
            # say which filter emptied it.
            tree.insert("", "end",
                        text="Nothing below the bar on this card.",
                        values=("", "", "", ""), tags=("unknown",))

    def _copy(self):
        if not self._clips:
            return
        title = "Video quality — %s" % os.path.basename(
            (self._card_var.get() or "").strip())
        text = video_quality.as_text(self._clips, title=title)
        try:
            self._dlg.clipboard_clear()
            self._dlg.clipboard_append(text)
        except tk.TclError:
            return
        self._on_log("Copied the video-quality report (%d clip(s)) to the "
                     "clipboard." % len(self._clips), "info")

    def raise_window(self):
        """Bring an already-open report to the front; ``False`` once the user
        has closed it, which is the caller's cue to build a new one."""
        try:
            self._dlg.deiconify()
            self._dlg.lift()
            return True
        except tk.TclError:
            return False

    def _close(self):
        self._cancel = True
        self._scan_id += 1               # orphan any in-flight poll
        try:
            self._dlg.destroy()
        except tk.TclError:
            pass


def open_video_quality_dialog(parent, manufacturer, theme_name, card_path="",
                              initial_dir=None, on_log=None):
    """Open (and return) the report window."""
    return VideoQualityDialog(parent, manufacturer, theme_name,
                              card_path=card_path, initial_dir=initial_dir,
                              on_log=on_log)
