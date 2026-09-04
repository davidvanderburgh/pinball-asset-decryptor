"""Build / flash dialog — build a card image and/or write one onto a card.

A small modal (opened from the Write tab's "Build / flash SD card…" button for
plugins with ``capabilities.flash_image``) with two independently tickable
sections (a tester: "when someone builds an image, they are most likely
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

Which two boxes were ticked is remembered.  A tester who works build-only
(build here, write the card elsewhere) found both boxes ticked again every
time he reopened the dialog: "the Build/Flash screen does not remember your
selections between sessions."  ``initial_choices`` seeds the ticks from the
last run and ``on_choices`` reports the pair back when Start is actually
pressed — a cancelled dialog changes nothing, so what is remembered is what
the user ran, not what they were mid-way through unticking.

It deliberately does no raw device I/O itself: the target card's capacity
comes from the same ``core.drives`` enumeration the Direct-SD picker uses
(advertised size, no privileged open), and a preliminary "does it fit?" check
is shown here so the user catches a too-big image before committing.  The
authoritative size guard runs in the flash pipeline.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.rawdevice import menu_write_plan

from ..core.admin import is_admin
from ..core.elevated_flash import can_self_elevate as _self_elevates
from .placement import centered_over
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


def _flash_words(mfr):
    """Resolve the manufacturer's flash-surface wording (see registry).

    Returns a dict of every string the dialog renders, falling back to the
    dd-flavoured defaults so Stern/CGC read exactly as before.  JJP overrides
    them because its "flash" is a format-and-copy, not a raw image write.
    """
    noun = (getattr(mfr, "flash_medium_noun", None)
            or getattr(mfr, "direct_medium_noun", "SD card"))
    return {
        "noun": noun,
        "title": (getattr(mfr, "flash_dialog_title", None)
                  or "Build / flash %s image" % noun),
        "section": (getattr(mfr, "flash_section_label", None)
                    or "Write an image onto the %s" % noun),
        "action": getattr(mfr, "flash_action_word", None) or "flash",
        "confirm_verb": (getattr(mfr, "flash_confirm_verb", None)
                         or "write the image onto it"),
        "safety": (getattr(mfr, "flash_safety_text", None)
                   or getattr(mfr, "direct_safety_text", None)),
        "target_kind": (getattr(mfr, "flash_target_kind", None)
                        or getattr(mfr, "direct_target_kind", "sd_card")),
        # The target row's label sits in a fixed 12-char column, so a long
        # noun ("USB stick") gets clipped — plugins supply a short form.
        "target_label": (getattr(mfr, "flash_target_label", None)
                         or "Target %s:" % noun),
        "filetypes": [tuple(ft) for ft in
                      getattr(mfr, "flash_image_filetypes", None)
                      or (("SD-card image", "*.img *.raw *.bin"),
                          ("All files", "*.*"))],
    }


class FlashImageDialog:
    """Modal collecting (build?, image, target card) for build and/or flash."""

    def __init__(self, parent, manufacturer, theme_name, on_flash,
                 initial_image=None, on_build_flash=None, build_target="",
                 can_build=False, cannot_build_reason="",
                 has_pending_changes=True, initial_choices=None,
                 on_choices=None):
        self._parent = parent
        self._mfr = manufacturer
        self._on_flash = on_flash
        self._on_build_flash = on_build_flash
        self._can_build = bool(can_build and on_build_flash is not None)
        self._cannot_build_reason = cannot_build_reason
        self._has_pending_changes = has_pending_changes
        self._on_choices = on_choices
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._words = _flash_words(manufacturer)
        self._sans, _ = platform_font()
        self._drives = []            # list[PhysicalDrive] from last enumeration
        self._selected = None        # the chosen PhysicalDrive
        self._enum_id = 0            # bump-counter to drop stale enumerations
        self._menu_seen = None       # the image the menu tick last defaulted for
        self._initial_build, self._initial_write = self._opening_ticks(
            initial_choices)

        self._build(build_target or "")
        # Pre-fill the flash box with the image the Write tab would build
        # (Output Folder + File Name) when it exists on disk — flashing the
        # image just built is the 90% case (feedback batch 8); Browse still
        # overrides.  Only relevant with the build section unticked; ticked,
        # the box tracks the build output instead.
        if (not self._build_var.get() and initial_image
                and os.path.isfile(initial_image)):
            self._image_var.set(initial_image)
        self._sync_sections()
        self._refresh_drives()
        self._update_readout()

    # ------------------------------------------------------------------
    def _opening_ticks(self, saved):
        """(build?, write?) the dialog opens with.

        With nothing remembered these are the originals: build when a build is
        possible and something was actually modified, always flash — so a
        no-changes session (restoring a backup, re-flashing an earlier build)
        starts flash-only, which is the old Flash dialog exactly.

        Once the user has run the dialog, their own pair wins.  Build is still
        gated on ``_can_build``, because a ticked box the Write tab can't
        satisfy is just a disabled box lying; and a remembered pair that is
        somehow all-off is treated as nothing remembered, since a dialog that
        opens with Start greyed out looks broken.
        """
        if not isinstance(saved, dict) or not saved:
            return (self._can_build and self._has_pending_changes), True
        build = self._can_build and bool(
            saved.get("build", self._has_pending_changes))
        write = bool(saved.get("write", True))
        if not (build or write):
            return (self._can_build and self._has_pending_changes), True
        return build, write

    def _remember_choices(self):
        """Report the ticked pair back for next time (Start only)."""
        if self._on_choices is None:
            return
        choices = {"write": bool(self._write_var.get())}
        # A disabled Build box is not a choice — leaving it out keeps the
        # previous answer instead of recording the forced False and opening
        # build-less next time, when the Write tab may well be set up again.
        if self._can_build:
            choices["build"] = bool(self._build_var.get())
        try:
            self._on_choices(choices)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _build(self, build_target):
        th = self._theme
        noun = self._words["noun"]
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        # Stay hidden until fully built AND positioned, then map once with
        # deiconify() at the tail.  Without this the window maps at its
        # default (parent-relative) spot the moment dark_titlebar /
        # _center call update_idletasks, so the user sees an empty white
        # box jump into place as the modal renders (David).
        dlg.withdraw()
        dlg.title(self._words["title"])
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        header = (getattr(self._mfr, "flash_header", None)
                  or "Build an image and/or write one onto a %s" % noun)
        ttk.Label(
            body, text=header,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body,
            text=("Tick both to test changes on the machine in one step: "
                  "build a fresh image, then put it straight onto the %s."
                  % noun),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=560, justify="left").pack(anchor="w", pady=(0, 10))

        # ---- Section 1: build ----------------------------------------
        # Opening state: the pair the user last ran, else the defaults —
        # see _opening_ticks.
        self._build_var = tk.BooleanVar(value=self._initial_build)
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
        self._write_var = tk.BooleanVar(value=self._initial_write)
        ttk.Checkbutton(
            body, text=self._words["section"],
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

        # THE MENU-ONLY WRITE.  A multi-boot card's menu lives in ONE
        # partition, so changing it and writing that partition back is 350 MB
        # rather than the whole image - a minute instead of the hour a 14.7 GB
        # image takes on an ordinary card (David: "writing to my sd card is
        # pretty slow... yes, build the menu-only write").  It also leaves
        # /data and /dump alone, so the machine keeps its settings and scores,
        # which a whole-image flash cannot.
        #
        # DEFAULT ON when the image supports it: the run REFUSES a card this
        # image was not flashed from, naming what differed, so a wrong default
        # costs one refusal - while the wrong default the other way costs an
        # hour, every time.
        self._menu_var = tk.BooleanVar(value=False)
        self._menu_chk = ttk.Checkbutton(
            flash_body, variable=self._menu_var, command=self._sync_sections,
            text="Only the boot menu — fast, and the machine keeps its "
                 "settings and scores")
        self._menu_chk.pack(anchor="w", pady=(2, 0))
        self._menu_note = ttk.Label(
            flash_body, foreground=self._theme["gray"], wraplength=430,
            justify="left", text="")
        self._menu_note.pack(anchor="w", padx=(22, 0))

        # Target-card row.
        card_row = ttk.Frame(flash_body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text=self._words["target_label"], width=12,
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

        # Red safety banner (manufacturer-supplied; flash-specific wording
        # falls back to the Direct-SD text).
        safety = self._words["safety"]
        if safety:
            tk.Label(
                body, text=safety, bg=th["bg"], fg=th["error"],
                font=(self._sans, 9), wraplength=560, justify="left",
                anchor="w").pack(fill="x", pady=(6, 0))

        # Windows + already elevated: mapped network-drive letters (W:) are
        # invisible to an elevated process, so a build reading its assets or
        # writing its output through one silently sees nothing there.  The
        # Write tab carries this warning for Direct-SD mode; feedback batch 22
        # asked for it here too, since this dialog is where a build is actually
        # started.  Only shown when it can bite (Windows, elevated, building).
        self._unc_note = None
        if sys.platform == "win32" and is_admin():
            self._unc_note = tk.Label(
                body,
                text=("Running as administrator: Windows hides mapped network "
                      "drive letters (e.g. W:) from elevated apps. If your "
                      "project or build location is on a network share, use "
                      "its full \\\\server\\share path, not a drive letter."),
                bg=th["bg"], fg=th["gray"], font=(self._sans, 9),
                wraplength=560, justify="left", anchor="w")
            self._unc_note.pack(fill="x", pady=(6, 0))

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
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 620)
        dh = dlg.winfo_reqheight()
        # See placement.centered_over: the max(0, ...) this replaces was a
        # single-screen assumption, not a safety net.
        x, y = centered_over(self._parent, dw, dh)
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, x, y))

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

        self._sync_menu_only(writing, building)

        action = self._words["action"]
        if building and writing:
            label = "Build + %s" % action
        elif building:
            label = "Build image"
        elif writing:
            label = ("Flash image" if action == "flash"
                     else action[0].upper() + action[1:])
        else:
            label = "Start"
        self._start_btn.configure(text=label)
        self._start_btn.state(
            ["!disabled"] if (building or writing) else ["disabled"])
        self._update_readout()

    #: What the menu-only tick says under itself, per state.
    _MENU_NOTE_OK = ("Writes the menu partition only, onto a card this image "
                     "was already flashed from. It checks first, and refuses "
                     "if the card holds anything else.")
    _MENU_NOTE_BUILD = ("A freshly built image has never been on this card, "
                        "so the whole of it has to be written.")

    def _sync_menu_only(self, writing, building):
        """Offer the menu-only write only where it can mean anything: a
        flash (not a build+flash - a fresh image was never on that card) of
        an image that HAS a menu partition to write.

        The image is asked, not assumed: reading its partition table is 512
        bytes, and an image with no Linux rootfs as its second partition is
        not a Stern card at all."""
        why = ""
        can = bool(writing and not building)
        if can:
            img = (self._image_var.get() or "").strip().strip('"')
            try:
                menu_write_plan(img)
                why = self._MENU_NOTE_OK
            except Exception:                           # noqa: BLE001
                can = False                 # not a card image, or not there
        elif writing and building:
            why = self._MENU_NOTE_BUILD
        try:
            self._menu_chk.state(["!disabled"] if can else ["disabled"])
        except tk.TclError:                             # pragma: no cover
            pass
        if not can:
            self._menu_var.set(False)
        elif self._menu_seen != self._image_var.get():
            # First sight of an image that supports it: on by default.
            self._menu_var.set(True)
        self._menu_seen = self._image_var.get()
        try:
            self._menu_note.configure(
                text=(why if (can and self._menu_var.get()) or not can
                      else "The whole image is written."))
        except tk.TclError:                             # pragma: no cover
            pass

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
            filetypes=self._words["filetypes"])
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
            parent=self._dlg,
            title="Select the %s" % self._words["filetypes"][0][0],
            initialdir=initial,
            filetypes=self._words["filetypes"])
        if path:
            self._image_var.set(path)

    def _refresh_drives(self):
        """Enumerate physical drives on a worker thread (PowerShell/diskutil
        startup can block the UI), then populate the combo on the main thread."""
        self._enum_id += 1
        my_id = self._enum_id
        self._drive_combo["values"] = ["Detecting drives…"]
        self._drive_var.set("Detecting drives…")
        prefer = self._words["target_kind"]

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:
                drives, pick = [], (None, None, None)
            try:
                self._dlg.after(0, self._apply_drives, my_id, drives, pick)
            except (tk.TclError, RuntimeError):
                pass                     # dialog closed while enumerating

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        # The worker's after() hand-off can outlive the dialog: enumeration
        # takes seconds (PowerShell/diskutil), and clicking Start or Cancel
        # first destroys the window — after() still queues fine on a
        # destroyed Toplevel, so the guard has to be here, not in the
        # worker.  A tester's build log showed the fallout: TclError
        # "invalid command name …!combobox" from poking the dead dropdown.
        try:
            if not self._dlg.winfo_exists():
                return
        except tk.TclError:
            return
        if my_id != self._enum_id:
            return                       # a newer Refresh superseded this one
        from ..core.drives import visible_drives
        prefer = self._words["target_kind"]
        best = pick[0] if pick else None
        # Small-SD-card media (Stern Spike 2): hide multi-TB backup disks so
        # the dropdown lists plausible cards only — a tester saw the Flash
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
        if best is None and prefer == "usb_stick":
            # The stick picker deliberately selects nothing when every
            # candidate looks like an SSD/HDD — formatting must never
            # default to the game SSD or a backup disk (David).  The list
            # stays available for an explicit manual pick.
            self._drive_var.set(
                "(no USB stick detected — pick one, or connect it and "
                "click Refresh)")
            self._selected = None
            self._update_readout()
            return
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
            # (feedback batch 8: the line was redundant).
            self._readout.configure(text="", foreground=th["gray"])
            return
        noun = self._words["noun"]
        if card is None:
            self._readout.configure(
                text="Image: %s  •  pick a target %s."
                     % (_fmt_size(img_size), noun), foreground=th["gray"])
            return
        if card_size and img_size > card_size:
            self._readout.configure(
                text=("⚠ Image %s is larger than the %s %s — it won't fit. "
                      "Use a larger %s." % (_fmt_size(img_size), noun,
                                            _fmt_size(card_size), noun)),
                foreground=th["error"])
        elif card_size:
            self._readout.configure(
                text="Image %s  →  %s %s   ✓ fits"
                     % (_fmt_size(img_size), noun, _fmt_size(card_size)),
                foreground=th["success"])
        else:
            self._readout.configure(
                text="Image %s  →  %s size unknown (it will be checked "
                     "before writing)" % (_fmt_size(img_size), noun),
                foreground=th["gray"])

    # ------------------------------------------------------------------
    def _do_start(self):
        building = self._build_var.get() and self._can_build
        writing = self._write_var.get()
        noun = self._words["noun"]

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
                    "Pick a %s — or tick \"Build a fresh image\" to build "
                    "one first." % self._words["filetypes"][0][0],
                    parent=self._dlg)
                return
            if card is None:
                messagebox.showwarning(
                    "No %s selected" % noun,
                    "Pick a target %s from the dropdown. If it's empty, "
                    "connect the %s and click Refresh." % (noun, noun),
                    parent=self._dlg)
                return
            # Flash-only with nothing modified this session: legitimate
            # (restoring a backup, re-flashing an earlier build), but worth a
            # heads-up so an accidental no-change flash is caught (a tester).
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
                    "The image (%s) is larger than the %s (%s). Use a "
                    "larger %s." % (_fmt_size(os.path.getsize(img)), noun,
                                    _fmt_size(card.size_bytes), noun),
                    parent=self._dlg)
                return

            flash_what = (os.path.basename(build_path)
                          if building else os.path.basename(img))
            verb = self._words["confirm_verb"]
            if self._menu_var.get() and not building:
                # A MENU WRITE DOES NOT ERASE THE CARD, and must not claim to:
                # one partition is replaced, the games and the machine's own
                # /data and /dump are untouched, and the run refuses outright
                # if the card is not the one this image was flashed onto.
                if not messagebox.askyesno(
                    "Write the boot menu?",
                    "This replaces the BOOT MENU on %s and nothing else.\n\n"
                    "  Target: %s\n  Image:  %s\n\n"
                    "The games stay as they are, and so do the machine's own "
                    "settings and scores. If the card was not written from "
                    "this image it is refused before anything is written. "
                    "Proceed?" % (noun, card.display, flash_what),
                    parent=self._dlg,
                ):
                    return
            else:
                lead = ("After the build finishes, this will ERASE the entire "
                        "%s and %s." % (noun, verb)
                        if building else
                        "This will ERASE the entire %s and %s." % (noun, verb))
                if not messagebox.askyesno(
                    "Erase the %s and continue?" % noun,
                    "%s There is no undo.\n\n  Target: %s\n  Image:  %s\n\n"
                    "Make sure you have a backup of anything on the %s. "
                    "Proceed?"
                    % (lead, card.display, flash_what, noun),
                    icon="warning", parent=self._dlg,
                ):
                    return

        menu_only = bool(self._menu_var.get()) and not building
        device_path = card.device_path if (writing and card) else None
        # Past every confirmation — this is the pair the user committed to, so
        # it's the pair the dialog opens with next time.
        self._remember_choices()
        self._dlg.grab_release()
        self._dlg.destroy()
        if building:
            if self._on_build_flash is not None:
                self._on_build_flash(build_path, device_path)
        elif writing and self._on_flash is not None:
            self._on_flash(img, device_path, menu_only=menu_only)

    def _cancel(self):
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
