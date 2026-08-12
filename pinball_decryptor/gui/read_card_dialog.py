"""Read-card dialog — save a whole physical card to a ``.raw`` image file.

The mirror image of :mod:`gui.flash_dialog`: that one puts an image onto a
card, this one takes a card off into an image.  Asked for in feedback batch 33
("you can write out raw images to SD-cards but you can't read cards into a
.raw"), and it feeds the app's own Partitions and Compare tabs — dump a card,
change something on the machine, dump it again, diff the two.

Nothing is written to the card, so unlike the flash dialog there is no
destructive-write confirmation; the checks here are about the *destination*
(is there room, is something already there).
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.admin import is_admin
from ..core.elevated_flash import can_self_elevate as _self_elevates
from .placement import centered_over
from .theme import THEMES, dark_titlebar, platform_font


def _fmt_size(n):
    """Decimal GB/MB size string (matches how card capacity is advertised)."""
    if not n:
        return "unknown"
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 10 ** 9)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 10 ** 6)
    return "%d bytes" % n


def _default_image_name(drive, noun):
    """A file name for the picked card that says what it came off."""
    base = (getattr(drive, "model", "") or noun or "card").strip()
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in base)
    safe = "-".join(safe.split()) or "card"
    size = getattr(drive, "size_bytes", None)
    if size:
        safe += "-%dGB" % round(size / 10 ** 9)
    return safe + ".raw"


class ReadCardDialog:
    """Modal collecting (source card, destination image file) for a card read."""

    def __init__(self, parent, manufacturer, theme_name, on_read,
                 initial_dir=None):
        self._parent = parent
        self._mfr = manufacturer
        self._on_read = on_read
        self._initial_dir = initial_dir if (
            initial_dir and os.path.isdir(initial_dir)) else None
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._noun = getattr(manufacturer, "direct_medium_noun", "SD card")
        self._target_kind = getattr(manufacturer, "direct_target_kind",
                                    "sd_card")
        self._sans, _ = platform_font()
        self._drives = []            # list[PhysicalDrive] from last enumeration
        self._selected = None        # the chosen PhysicalDrive
        self._enum_id = 0            # bump-counter to drop stale enumerations
        self._named_for = None       # drive the current auto file name came from

        self._build()
        self._refresh_drives()
        self._update_readout()

    # ------------------------------------------------------------------
    def _build(self):
        th = self._theme
        noun = self._noun
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        # Built hidden, mapped once at the end — see FlashImageDialog._build:
        # dark_titlebar/_center force an update_idletasks, and a visible window
        # would flash empty at its default spot first.
        dlg.withdraw()
        dlg.title("Save %s to an image file" % noun)
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="Save the %s to a .raw image file" % noun,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body,
            text=("Copies the whole card, sector for sector, into one file — "
                  "a backup you can flash back later, open on the Partitions "
                  "tab, or compare against another image. The card itself is "
                  "only read from; nothing on it changes."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))

        card_row = ttk.Frame(body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text="Read from:", width=12, anchor="w").pack(
            side="left")
        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            card_row, textvariable=self._drive_var, state="readonly")
        self._drive_combo.pack(side="left", fill="x", expand=True)
        self._drive_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_drive_selected())
        ttk.Button(card_row, text="Refresh",
                   command=self._refresh_drives).pack(side="left", padx=(4, 0))

        img_row = ttk.Frame(body)
        img_row.pack(fill="x", pady=4)
        ttk.Label(img_row, text="Save to:", width=12, anchor="w").pack(
            side="left")
        self._image_var = tk.StringVar()
        self._image_var.trace_add("write", lambda *_a: self._update_readout())
        ttk.Entry(img_row, textvariable=self._image_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(img_row, text="Browse…", command=self._browse_image).pack(
            side="left", padx=(4, 0))

        # Live card-size vs free-space readout.
        self._readout = ttk.Label(
            body, text="", font=(self._sans, 9), wraplength=560,
            justify="left")
        self._readout.pack(anchor="w", pady=(8, 2))

        tk.Label(
            body,
            text=("An image is the size of the WHOLE card, empty space "
                  "included — an 8 GB card makes an 8 GB file, however little "
                  "is on it."),
            bg=th["bg"], fg=th["gray"], font=(self._sans, 9),
            wraplength=560, justify="left", anchor="w").pack(
            fill="x", pady=(0, 2))

        # Raw device reads are gated on elevation the same way writes are, so
        # forewarn rather than block — the read elevates itself when it starts.
        if not is_admin():
            note = ("You may be asked to approve administrator access when "
                    "the read starts." if _self_elevates()
                    else "Reading a card needs administrator access. "
                         "Re-launch the app as an administrator, then reopen "
                         "this dialog.")
            tk.Label(
                body, text=note, bg=th["bg"], fg=th["gray"],
                font=(self._sans, 9), wraplength=560, justify="left",
                anchor="w").pack(fill="x", pady=(6, 0))

        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(14, 0))
        ttk.Button(btn_row, text="Cancel", command=self._cancel,
                   style="Danger.TButton").pack(side="right")
        self._start_btn = ttk.Button(
            btn_row, text="Start", command=self._do_start, style="Go.TButton")
        self._start_btn.pack(side="right", padx=(0, 8))

        self._center()
        dlg.bind("<Escape>", lambda _e: self._cancel())
        dlg.deiconify()
        dlg.lift()
        dlg.update_idletasks()
        try:
            dlg.grab_set()
        except tk.TclError:
            dlg.update()
            dlg.grab_set()

    def _center(self):
        dlg = self._dlg
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 620)
        dh = dlg.winfo_reqheight()
        x, y = centered_over(self._parent, dw, dh)
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, x, y))

    def _refit(self):
        """Grow the dialog to fit its content again.

        The readout is one line most of the time and two when it has to name
        the destination folder in a warning — and a fixed geometry on a
        non-resizable window simply clips the overflow, which ate the whole
        Start / Cancel row the first time this dialog met a card that didn't
        fit.  Only ever grows: shrinking as the text shortens would make the
        window twitch while the user picks drives."""
        dlg = self._dlg
        try:
            dlg.update_idletasks()
            want = dlg.winfo_reqheight()
            if want > dlg.winfo_height():
                dlg.geometry("%dx%d" % (max(dlg.winfo_width(), 620), want))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _browse_image(self):
        cur = self._image_var.get().strip()
        initial_dir = os.path.dirname(cur) if cur else None
        if not (initial_dir and os.path.isdir(initial_dir)):
            initial_dir = self._initial_dir
        path = filedialog.asksaveasfilename(
            parent=self._dlg, title="Save the card image as…",
            initialdir=initial_dir,
            initialfile=(os.path.basename(cur) if cur
                         else _default_image_name(self._selected, self._noun)),
            defaultextension=".raw",
            filetypes=[("SD-card image", "*.raw *.img *.bin"),
                       ("All files", "*.*")])
        if path:
            self._image_var.set(os.path.normpath(path))
            self._named_for = None      # the user has named it; stop retitling

    def _refresh_drives(self):
        """Enumerate physical drives on a worker thread (PowerShell/diskutil
        startup blocks for a second or two), then fill the combo on the main
        thread."""
        self._enum_id += 1
        my_id = self._enum_id
        self._drive_combo["values"] = ["Detecting drives…"]
        self._drive_var.set("Detecting drives…")

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=self._target_kind)
            except Exception:
                drives, pick = [], (None, None, None)
            try:
                self._dlg.after(0, self._apply_drives, my_id, drives, pick)
            except (tk.TclError, RuntimeError):
                pass                     # dialog closed while enumerating

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        # The enumeration can outlive the dialog (Start/Cancel destroys it
        # while PowerShell is still running) and after() still fires on a dead
        # Toplevel — guard here, not in the worker.  Same fix as the flash
        # dialog's, whose stale hand-off poked a destroyed combobox.
        try:
            if not self._dlg.winfo_exists():
                return
        except tk.TclError:
            return
        if my_id != self._enum_id:
            return                       # a newer Refresh superseded this one
        from ..core.drives import visible_drives
        best = pick[0] if pick else None
        drives = visible_drives(drives, prefer=self._target_kind,
                                keep=[best] if best else ())
        self._drives = drives
        if not drives:
            self._drive_combo["values"] = ["(no drives found — click Refresh)"]
            self._drive_var.set(self._drive_combo["values"][0])
            self._selected = None
            self._update_readout()
            return
        self._drive_combo["values"] = [d.display for d in drives]
        chosen = best if (best and best in drives) else drives[0]
        self._drive_var.set(chosen.display)
        self._selected = chosen
        self._suggest_name()
        self._update_readout()

    def _on_drive_selected(self):
        idx = self._drive_combo.current()
        self._selected = (self._drives[idx]
                          if 0 <= idx < len(self._drives) else None)
        self._suggest_name()
        self._update_readout()

    def _suggest_name(self):
        """Pre-fill (and keep in step with the picked card) a destination name.

        Only while the box still holds a name WE suggested — the moment the
        user browses or types, their name is the one that stays.
        """
        if self._selected is None:
            return
        cur = self._image_var.get().strip()
        if cur and cur != self._named_for:
            return
        folder = self._initial_dir or os.path.expanduser("~")
        path = os.path.normpath(os.path.join(
            folder, _default_image_name(self._selected, self._noun)))
        self._named_for = path
        self._image_var.set(path)

    def _update_readout(self):
        """Card size vs free space on the destination volume."""
        self._render_readout()
        self._refit()

    def _render_readout(self):
        th = self._theme
        card = self._selected
        card_size = getattr(card, "size_bytes", None) if card else None
        path = self._image_var.get().strip()
        folder = os.path.dirname(os.path.abspath(path)) if path else ""

        if card is None:
            self._readout.configure(
                text="Pick the %s to read." % self._noun,
                foreground=th["gray"])
            return
        free = None
        if folder and os.path.isdir(folder):
            try:
                import shutil
                free = shutil.disk_usage(folder).free
            except OSError:
                free = None
        if not card_size:
            self._readout.configure(
                text="Card size unknown — it is checked before the read "
                     "starts.", foreground=th["gray"])
            return
        if free is None:
            self._readout.configure(
                text="Card %s  →  image file of the same size."
                     % _fmt_size(card_size), foreground=th["gray"])
            return
        if free < card_size:
            self._readout.configure(
                text=("⚠ Card %s, but only %s free in %s — the image won't "
                      "fit. Pick somewhere with more room."
                      % (_fmt_size(card_size), _fmt_size(free), folder)),
                foreground=th["error"])
        else:
            self._readout.configure(
                text="Card %s  →  %s free in %s   ✓ fits"
                     % (_fmt_size(card_size), _fmt_size(free), folder),
                foreground=th["success"])

    # ------------------------------------------------------------------
    def _do_start(self):
        card = self._selected
        if card is None:
            messagebox.showwarning(
                "No card picked",
                "Pick the %s to read from." % self._noun, parent=self._dlg)
            return
        path = self._image_var.get().strip()
        if not path:
            messagebox.showwarning(
                "No image file",
                "Pick where the image should be saved (Save to:).",
                parent=self._dlg)
            return
        path = os.path.normpath(path)
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            messagebox.showwarning(
                "Folder not found",
                "This folder doesn't exist:\n%s" % folder, parent=self._dlg)
            return
        # asksaveasfilename already asked, but a typed/pre-filled path hasn't
        # been through it — and silently replacing someone's backup would be
        # the worst outcome this dialog can produce.
        if os.path.exists(path) and not messagebox.askyesno(
                "Replace file?",
                "%s already exists.\n\nReplace it with a fresh image of the "
                "card?" % path, parent=self._dlg):
            return
        # Reading a card into a file ON that same card is impossible; reading a
        # 2 TB system disk into a file on itself is merely a very expensive
        # mistake.  Catch the obvious one: the destination sitting on a volume
        # of the drive being read.
        if self._destination_is_on(card, folder):
            messagebox.showwarning(
                "Same drive",
                "That folder is on the very drive you are reading, so the "
                "image would be written into its own source. Pick a folder on "
                "a different drive.", parent=self._dlg)
            return

        self._dlg.destroy()
        self._on_read(card.device_path, path)

    @staticmethod
    def _destination_is_on(drive, folder):
        """True when *folder* sits on one of *drive*'s own mounted volumes.

        Windows-only, and only as good as the drive letters the enumeration
        reported (``mount_label``, e.g. ``"E: F:"``) — an unlettered volume or
        a UNC destination just isn't caught here.  The core read still refuses
        on free space, which is the failure this would otherwise become.
        """
        if sys.platform != "win32":
            return False
        letters = (getattr(drive, "mount_label", "") or "").split()
        try:
            head = os.path.splitdrive(os.path.abspath(folder))[0]
        except (OSError, ValueError):
            return False
        head = head.rstrip(":").upper()
        return bool(head) and any(
            l.rstrip(":").upper() == head for l in letters)

    def _cancel(self):
        try:
            self._dlg.destroy()
        except tk.TclError:
            pass
