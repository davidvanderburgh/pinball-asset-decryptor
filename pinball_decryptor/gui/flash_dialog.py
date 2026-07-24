"""Build / flash dialog — build a card image and/or write one onto a card.

A small modal (opened from the Write tab's "Build / flash SD card…" button for
plugins with ``capabilities.flash_image``) with two independently tickable
sections (monkeybug: "when someone builds an image, they are most likely
writing it out after" — testing a change on the machine used to be a
mandatory two-step):

  1. **Build a fresh image** — the Write tab's normal Build, to the shown
     output path (pre-filled from Output Folder + File Name; editing it here
     writes back so the Write tab agrees).
  2. **Write an image onto the card** — the dd-style whole-card flash.  When
     section 1 is ticked the image box tracks the build output (you flash
     what you just built); untick it to flash a pre-built or backup image,
     which is exactly the old Flash dialog.

Both ticked = build, then flash the fresh build, one click.  The dialog
hands the choice back to the app (``on_build_flash`` / ``on_flash``), which
runs the pipelines through the main window's normal status area.

It deliberately does no raw device I/O itself: the target card's capacity
comes from the same ``core.drives`` enumeration the Direct-SD picker uses
(advertised size, no privileged open), and a preliminary "does it fit?" check
is shown here so the user catches a too-big image before committing.  The
authoritative size guard runs in the flash pipeline.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.admin import is_admin
from ..core.elevated_flash import can_self_elevate as _self_elevates
from .theme import THEMES, dark_titlebar, platform_font


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
    """Modal collecting (build?, image, target card) for build and/or flash."""

    def __init__(self, parent, manufacturer, theme_name, on_flash,
                 initial_image=None, on_build_flash=None, build_target="",
                 can_build=False, cannot_build_reason="",
                 has_pending_changes=True):
        self._parent = parent
        self._mfr = manufacturer
        self._on_flash = on_flash
        self._on_build_flash = on_build_flash
        self._can_build = bool(can_build and on_build_flash is not None)
        self._cannot_build_reason = cannot_build_reason
        self._has_pending_changes = has_pending_changes
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._sans, _ = platform_font()
        self._drives = []            # list[PhysicalDrive] from last enumeration
        self._selected = None        # the chosen PhysicalDrive
        self._enum_id = 0            # bump-counter to drop stale enumerations

        self._build(build_target or "")
        # Pre-fill the flash box with the image the Write tab would build
        # (Output Folder + File Name) when it exists on disk — flashing the
        # image just built is the 90% case (monkeybug batch 8); Browse still
        # overrides.  Only relevant with the build section unticked; ticked,
        # the box tracks the build output instead.
        if (not self._build_var.get() and initial_image
                and os.path.isfile(initial_image)):
            self._image_var.set(initial_image)
        self._sync_sections()
        self._refresh_drives()
        self._update_readout()

    # ------------------------------------------------------------------
    def _build(self, build_target):
        th = self._theme
        noun = getattr(self._mfr, "direct_medium_noun", "SD card")
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        # Stay hidden until fully built AND positioned, then map once with
        # deiconify() at the tail.  Without this the window maps at its
        # default (parent-relative) spot the moment dark_titlebar /
        # _center call update_idletasks, so the user sees an empty white
        # box jump into place as the modal renders (David).
        dlg.withdraw()
        dlg.title("Build / flash %s image" % noun)
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="Build an image and/or write one onto a %s" % noun,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body,
            text=("Tick both to test changes on the machine in one step: "
                  "build a fresh image, then write it straight onto the "
                  "card."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=560, justify="left").pack(anchor="w", pady=(0, 10))

        # ---- Section 1: build ----------------------------------------
        # Ticked by default when a build is possible and something was
        # actually modified; a no-changes session (restoring a backup /
        # re-flashing an earlier build) starts flash-only, which is the old
        # Flash dialog exactly.
        self._build_var = tk.BooleanVar(
            value=self._can_build and self._has_pending_changes)
        build_check = ttk.Checkbutton(
            body, text="Build a fresh image from your modifications",
            variable=self._build_var, command=self._sync_sections)
        build_check.pack(anchor="w")
        if self._on_build_flash is None:
            build_check.state(["disabled"])
        elif not self._can_build:
            build_check.state(["disabled"])
            ttk.Label(
                body,
                text=(self._cannot_build_reason
                      or "Set the original image, assets folder and build "
                         "location on the Write tab first."),
                font=(self._sans, 9), foreground=th["gray"],
                wraplength=540, justify="left").pack(
                anchor="w", padx=(22, 0))

        target_row = ttk.Frame(body)
        target_row.pack(fill="x", pady=(4, 10), padx=(22, 0))
        ttk.Label(target_row, text="Build to:", width=12, anchor="w").pack(
            side="left")
        self._build_path_var = tk.StringVar(value=build_target)
        self._build_path_var.trace_add(
            "write", lambda *_a: self._on_build_path_changed())
        self._build_entry = ttk.Entry(
            target_row, textvariable=self._build_path_var)
        self._build_entry.pack(side="left", fill="x", expand=True)
        self._build_browse = ttk.Button(
            target_row, text="Browse…", command=self._browse_build_target)
        self._build_browse.pack(side="left", padx=(4, 0))

        # ---- Section 2: flash ----------------------------------------
        self._write_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            body, text="Write an image onto the %s" % noun,
            variable=self._write_var, command=self._sync_sections).pack(
            anchor="w")

        flash_body = ttk.Frame(body)
        flash_body.pack(fill="x", padx=(22, 0))

        # Image-file row.  Tracks the build output while section 1 is ticked.
        img_row = ttk.Frame(flash_body)
        img_row.pack(fill="x", pady=4)
        ttk.Label(img_row, text="Image file:", width=12, anchor="w").pack(
            side="left")
        self._image_var = tk.StringVar()
        self._image_var.trace_add("write", lambda *_a: self._update_readout())
        self._image_entry = ttk.Entry(img_row, textvariable=self._image_var)
        self._image_entry.pack(side="left", fill="x", expand=True)
        self._image_browse = ttk.Button(
            img_row, text="Browse…", command=self._browse_image)
        self._image_browse.pack(side="left", padx=(4, 0))

        # Target-card row.
        card_row = ttk.Frame(flash_body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text="Target %s:" % noun, width=12,
                  anchor="w").pack(side="left")
        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            card_row, textvariable=self._drive_var, state="readonly")
        self._drive_combo.pack(side="left", fill="x", expand=True)
        self._drive_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_drive_selected())
        self._drive_refresh = ttk.Button(
            card_row, text="Refresh", command=self._refresh_drives)
        self._drive_refresh.pack(side="left", padx=(4, 0))

        # Live size readout / fit check.
        self._readout = ttk.Label(
            body, text="", font=(self._sans, 9), wraplength=560,
            justify="left")
        self._readout.pack(anchor="w", pady=(8, 2))

        # Red safety banner (manufacturer-supplied; same wording as Direct-SD).
        safety = getattr(self._mfr, "direct_safety_text", None)
        if safety:
            tk.Label(
                body, text=safety, bg=th["bg"], fg=th["error"],
                font=(self._sans, 9), wraplength=560, justify="left",
                anchor="w").pack(fill="x", pady=(6, 0))

        # A flash writes raw sectors, which needs elevation — but the app no
        # longer has to be launched elevated.  When it isn't already
        # Administrator/root, the flash elevates just the write on its own (a
        # UAC prompt on Windows, the macOS password dialog, pkexec on Linux),
        # so we only forewarn the user rather than blocking here.
        if not is_admin():
            note = ("You may be asked to approve administrator access when "
                    "the card write starts." if _self_elevates()
                    else "Writing the card needs administrator access. "
                         "Re-launch the app as an administrator, then reopen "
                         "this dialog.")
            tk.Label(
                body, text=note, bg=th["bg"], fg=th["gray"],
                font=(self._sans, 9), wraplength=560, justify="left",
                anchor="w").pack(fill="x", pady=(6, 0))

        # Buttons — green "go" Start, red Cancel (David: Cancel is red in
        # general, matching the live-run Cancel in the main window).
        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(14, 0))
        ttk.Button(btn_row, text="Cancel", command=self._cancel,
                   style="Danger.TButton").pack(side="right")
        self._start_btn = ttk.Button(
            btn_row, text="Start", command=self._do_start,
            style="Go.TButton")
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
    def _sync_sections(self):
        """Enable/disable each section's widgets to match its checkbox, keep
        the image box tracking the build output while building, and retitle
        the action button so it always says exactly what Start will do."""
        building = self._build_var.get() and self._can_build
        writing = self._write_var.get()

        for w in (self._build_entry, self._build_browse):
            w.state(["!disabled"] if building else ["disabled"])
        # While building, you flash what you build — the image box mirrors
        # the build path read-only.  Flash-only re-arms it for browsing.
        if building:
            self._image_var.set(self._build_path_var.get())
        for w in (self._image_entry, self._image_browse):
            w.state(["!disabled"] if (writing and not building)
                    else ["disabled"])
        for w in (self._drive_combo, self._drive_refresh):
            try:
                if writing:
                    w.state(["!disabled", "readonly"]
                            if w is self._drive_combo else ["!disabled"])
                else:
                    w.state(["disabled"])
            except tk.TclError:
                pass

        if building and writing:
            label = "Build + flash"
        elif building:
            label = "Build image"
        elif writing:
            label = "Flash image"
        else:
            label = "Start"
        self._start_btn.configure(text=label)
        self._start_btn.state(
            ["!disabled"] if (building or writing) else ["disabled"])
        self._update_readout()

    def _on_build_path_changed(self):
        if self._build_var.get() and self._can_build:
            self._image_var.set(self._build_path_var.get())

    def _browse_build_target(self):
        cur = self._build_path_var.get().strip()
        initial_dir = os.path.dirname(cur) if cur else None
        if initial_dir and not os.path.isdir(initial_dir):
            initial_dir = None
        path = filedialog.asksaveasfilename(
            parent=self._dlg, title="Build the image to…",
            initialdir=initial_dir,
            initialfile=os.path.basename(cur) if cur else None,
            filetypes=[("SD-card image", "*.img *.raw *.bin"),
                       ("All files", "*.*")])
        if path:
            self._build_path_var.set(os.path.normpath(path))

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
        if not self._write_var.get():
            self._readout.configure(text="", foreground=th["gray"])
            return
        building = self._build_var.get() and self._can_build
        img = self._image_var.get().strip()
        img_size = (os.path.getsize(img)
                    if img and os.path.isfile(img) else None)
        card = self._selected
        card_size = card.size_bytes if card else None

        if building and img_size is None:
            # Fresh build to a not-yet-existing file — nothing to measure
            # here; the flash pipeline's authoritative fit check still runs.
            self._readout.configure(
                text="The image is built first — its size is checked "
                     "against the card before writing.",
                foreground=th["gray"])
            return
        if img_size is None:
            # No instructive text — the empty Image-file box + Browse button
            # say it already, and the Start-click validation still nags
            # (monkeybug batch 8: the line was redundant).
            self._readout.configure(text="", foreground=th["gray"])
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
    def _do_start(self):
        building = self._build_var.get() and self._can_build
        writing = self._write_var.get()
        noun = getattr(self._mfr, "direct_medium_noun", "SD card")

        build_path = self._build_path_var.get().strip() if building else None
        if building and not build_path:
            messagebox.showwarning(
                "No build location",
                "Pick where the built image should be written (Build to:).",
                parent=self._dlg)
            return
        # Building with nothing modified makes an unmodified copy — the same
        # guard the standalone Build button had (this dialog replaced it for
        # flash-capable plugins, so the guard moves here).
        if building and not self._has_pending_changes:
            if not messagebox.askyesno(
                "Nothing modified",
                "No modified files were detected, so this will build a copy "
                "of the original image with no changes.\n\nBuild anyway?",
                icon="warning", parent=self._dlg,
            ):
                return

        img = self._image_var.get().strip()
        card = self._selected
        if writing:
            if not building and (not img or not os.path.isfile(img)):
                messagebox.showwarning(
                    "No image",
                    "Pick an SD-card image (.img / .raw) to flash — or tick "
                    "\"Build a fresh image\" to build one first.",
                    parent=self._dlg)
                return
            if card is None:
                messagebox.showwarning(
                    "No card selected",
                    "Pick a target card from the dropdown. If it's empty, "
                    "connect the card and click Refresh.", parent=self._dlg)
                return
            # Flash-only with nothing modified this session: legitimate
            # (restoring a backup, re-flashing an earlier build), but worth a
            # heads-up so an accidental no-change flash is caught (monkeybug).
            if not building and not self._has_pending_changes:
                if not messagebox.askyesno(
                    "Nothing modified",
                    "Nothing was modified this session.\n\nFlashing writes a "
                    "whole pre-built or backup image onto the card, "
                    "independent of any edits here — expected if you're "
                    "restoring a backup or re-flashing an image you built "
                    "earlier.\n\nFlash anyway?",
                    icon="warning", parent=self._dlg,
                ):
                    return
            # No admin gate here: the flash pipeline elevates just the write
            # when the app isn't already running as Administrator/root (see
            # core.elevated_flash).  On a platform with no self-elevation
            # path (Linux without pkexec) the flash surfaces a clear
            # "re-launch as root" error instead of writing.
            if (not building and card.size_bytes
                    and os.path.getsize(img) > card.size_bytes):
                messagebox.showerror(
                    "Image too big",
                    "The image (%s) is larger than the card (%s). Use a "
                    "larger card." % (_fmt_size(os.path.getsize(img)),
                                      _fmt_size(card.size_bytes)),
                    parent=self._dlg)
                return

            flash_what = (os.path.basename(build_path)
                          if building else os.path.basename(img))
            lead = ("After the build finishes, this will ERASE the entire "
                    "%s and write the fresh image onto it." % noun
                    if building else
                    "This will ERASE the entire %s and write the image onto "
                    "it." % noun)
            if not messagebox.askyesno(
                "Erase the card and flash?",
                "%s There is no undo.\n\n  Card:  %s\n  Image: %s\n\n"
                "Make sure you have a backup of the card. Proceed?"
                % (lead, card.display, flash_what),
                icon="warning", parent=self._dlg,
            ):
                return

        device_path = card.device_path if (writing and card) else None
        self._dlg.grab_release()
        self._dlg.destroy()
        if building:
            if self._on_build_flash is not None:
                self._on_build_flash(build_path, device_path)
        elif writing and self._on_flash is not None:
            self._on_flash(img, device_path)

    def _cancel(self):
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
