"""Flash-image dialog — write a whole pre-built card image onto an SD card.

A small modal (opened from the Write tab's "Flash Image to SD Card" button for
plugins with ``capabilities.flash_image``) that collects two things — the source
``.img``/``.raw`` and the target physical card — confirms the destructive write,
then hands ``(image_path, device_path)`` back to the app, which runs the actual
flash through the main window's normal status area (progress bar + log).

It deliberately does no raw device I/O itself: the target card's capacity comes
from the same ``core.drives`` enumeration the Direct-SD picker uses (advertised
size, no privileged open), and a preliminary "does it fit?" check is shown here
so the user catches a too-big image before committing.  The authoritative size
guard runs in the flash pipeline.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.admin import is_admin
from .theme import THEMES, platform_font


def _fmt_size(n):
    """Decimal GB/MB size string for the readout (matches card packaging)."""
    if not n:
        return "unknown"
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 10 ** 9)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 10 ** 6)
    return "%d bytes" % n


class FlashImageDialog:
    """Modal collecting (image, target card) for a whole-card flash."""

    def __init__(self, parent, manufacturer, theme_name, on_flash):
        self._parent = parent
        self._mfr = manufacturer
        self._on_flash = on_flash
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._sans, _ = platform_font()
        self._drives = []            # list[PhysicalDrive] from last enumeration
        self._selected = None        # the chosen PhysicalDrive
        self._enum_id = 0            # bump-counter to drop stale enumerations

        self._build()
        self._refresh_drives()
        self._update_readout()

    # ------------------------------------------------------------------
    def _build(self):
        th = self._theme
        noun = getattr(self._mfr, "direct_medium_noun", "SD card")
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        dlg.title("Flash image to %s" % noun)
        dlg.configure(bg=th["bg"])
        dlg.transient(self._parent)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="Flash a complete image onto a %s" % noun,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body,
            text=("Writes the whole image verbatim — the entire %s is erased "
                  "and replaced. Use a built or backed-up image." % noun),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=560, justify="left").pack(anchor="w", pady=(0, 10))

        # Red safety banner (manufacturer-supplied; same wording as Direct-SD).
        safety = getattr(self._mfr, "direct_safety_text", None)
        if safety:
            tk.Label(
                body, text=safety, bg=th["bg"], fg=th["error"],
                font=(self._sans, 9), wraplength=560, justify="left",
                anchor="w").pack(fill="x", pady=(0, 10))

        # Image-file row.
        img_row = ttk.Frame(body)
        img_row.pack(fill="x", pady=4)
        ttk.Label(img_row, text="Image file:", width=14, anchor="w").pack(
            side="left")
        self._image_var = tk.StringVar()
        self._image_var.trace_add("write", lambda *_a: self._update_readout())
        ttk.Entry(img_row, textvariable=self._image_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(img_row, text="Browse…", command=self._browse_image).pack(
            side="left", padx=(4, 0))

        # Target-card row.
        card_row = ttk.Frame(body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text="Target %s:" % noun, width=14,
                  anchor="w").pack(side="left")
        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            card_row, textvariable=self._drive_var, state="readonly")
        self._drive_combo.pack(side="left", fill="x", expand=True)
        self._drive_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_drive_selected())
        ttk.Button(card_row, text="Refresh", command=self._refresh_drives).pack(
            side="left", padx=(4, 0))

        # Live size readout / fit check.
        self._readout = ttk.Label(
            body, text="", font=(self._sans, 9), wraplength=560,
            justify="left")
        self._readout.pack(anchor="w", pady=(8, 2))

        # Administrator gate (Windows): the flash needs an elevated process.
        self._admin_note = tk.Label(
            body,
            text=("⚠ Flashing needs Administrator. Close the app, right-click "
                  "the shortcut, choose \"Run as administrator\", and reopen "
                  "this dialog."),
            bg=th["bg"], fg=th["error"], font=(self._sans, 9),
            wraplength=560, justify="left", anchor="w")
        if not is_admin():
            self._admin_note.pack(fill="x", pady=(2, 0))

        # Buttons.
        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(14, 0))
        ttk.Button(btn_row, text="Cancel", command=self._cancel).pack(
            side="right")
        self._flash_btn = ttk.Button(
            btn_row, text="Flash image", command=self._do_flash)
        self._flash_btn.pack(side="right", padx=(0, 8))

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
        self._parent.update_idletasks()
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 620)
        dh = dlg.winfo_reqheight()
        pw = self._parent.winfo_width()
        ph = self._parent.winfo_height()
        if pw <= 1 or ph <= 1:
            sw = self._parent.winfo_screenwidth()
            sh = self._parent.winfo_screenheight()
            x, y = (sw - dw) // 2, (sh - dh) // 2
        else:
            x = self._parent.winfo_rootx() + (pw - dw) // 2
            y = self._parent.winfo_rooty() + (ph - dh) // 2
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, max(0, x), max(0, y)))

    # ------------------------------------------------------------------
    def _browse_image(self):
        cur = self._image_var.get().strip()
        initial = None
        if cur:
            parent = os.path.dirname(cur)
            if parent and os.path.isdir(parent):
                initial = parent
        path = filedialog.askopenfilename(
            parent=self._dlg, title="Select an SD-card image to flash",
            initialdir=initial,
            filetypes=[("SD-card image", "*.img *.raw *.bin"),
                       ("All files", "*.*")])
        if path:
            self._image_var.set(path)

    def _refresh_drives(self):
        """Enumerate physical drives on a worker thread (PowerShell/diskutil
        startup can block the UI), then populate the combo on the main thread."""
        self._enum_id += 1
        my_id = self._enum_id
        self._drive_combo["values"] = ["Detecting drives…"]
        self._drive_var.set("Detecting drives…")
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:
                drives, pick = [], (None, None, None)
            self._dlg.after(0, self._apply_drives, my_id, drives, pick)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        if my_id != self._enum_id:
            return                       # a newer Refresh superseded this one
        from ..core.drives import visible_drives
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")
        best = pick[0] if pick else None
        # Small-SD-card media (Stern Spike 2): hide multi-TB backup disks so
        # the dropdown lists plausible cards only — monkeybug saw the Flash
        # dialog still offering large drives because it skipped this filter
        # the Direct-SD picker already uses.  The auto-picked best is force-
        # kept visible so the selection always exists in the list.
        drives = visible_drives(drives, prefer=prefer,
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
        self._update_readout()

    def _on_drive_selected(self):
        idx = self._drive_combo.current()
        self._selected = (self._drives[idx]
                          if 0 <= idx < len(self._drives) else None)
        self._update_readout()

    def _update_readout(self):
        """Show image size vs card capacity and a preliminary fit check."""
        th = self._theme
        img = self._image_var.get().strip()
        img_size = (os.path.getsize(img)
                    if img and os.path.isfile(img) else None)
        card = self._selected
        card_size = card.size_bytes if card else None

        if img_size is None:
            self._readout.configure(
                text="Pick an image file to flash.", foreground=th["gray"])
            return
        if card is None:
            self._readout.configure(
                text="Image: %s  •  pick a target card."
                     % _fmt_size(img_size), foreground=th["gray"])
            return
        if card_size and img_size > card_size:
            self._readout.configure(
                text=("⚠ Image %s is larger than the card %s — it won't fit. "
                      "Use a larger card." % (_fmt_size(img_size),
                                              _fmt_size(card_size))),
                foreground=th["error"])
        elif card_size:
            self._readout.configure(
                text="Image %s  →  card %s   ✓ fits"
                     % (_fmt_size(img_size), _fmt_size(card_size)),
                foreground=th["success"])
        else:
            self._readout.configure(
                text="Image %s  →  card size unknown (it will be checked "
                     "before writing)" % _fmt_size(img_size),
                foreground=th["gray"])

    # ------------------------------------------------------------------
    def _do_flash(self):
        img = self._image_var.get().strip()
        card = self._selected
        if not img or not os.path.isfile(img):
            messagebox.showwarning(
                "No image", "Pick an SD-card image (.img / .raw) to flash.",
                parent=self._dlg)
            return
        if card is None:
            messagebox.showwarning(
                "No card selected",
                "Pick a target card from the dropdown. If it's empty, connect "
                "the card and click Refresh.", parent=self._dlg)
            return
        if not is_admin():
            messagebox.showerror(
                "Administrator required",
                "Flashing writes raw disk sectors, which needs Administrator. "
                "Re-launch the app as administrator and try again.",
                parent=self._dlg)
            return
        if card.size_bytes and os.path.getsize(img) > card.size_bytes:
            messagebox.showerror(
                "Image too big",
                "The image (%s) is larger than the card (%s). Use a larger "
                "card." % (_fmt_size(os.path.getsize(img)),
                           _fmt_size(card.size_bytes)),
                parent=self._dlg)
            return

        noun = getattr(self._mfr, "direct_medium_noun", "SD card")
        if not messagebox.askyesno(
            "Erase the card and flash?",
            "This will ERASE the entire %s and write the image onto it. There "
            "is no undo.\n\n  Card:  %s\n  Image: %s\n\nMake sure you have a "
            "backup of the card. Proceed?"
            % (noun, card.display, os.path.basename(img)),
            icon="warning", parent=self._dlg,
        ):
            return

        device_path = card.device_path
        self._dlg.grab_release()
        self._dlg.destroy()
        if self._on_flash is not None:
            self._on_flash(img, device_path)

    def _cancel(self):
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
