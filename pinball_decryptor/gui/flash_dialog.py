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
                 on_choices=None, handed_in="", fresh_image=False,
                 flashed_fn=None, image_titles=None):
        self._parent = parent
        self._mfr = manufacturer
        self._on_flash = on_flash
        self._on_build_flash = on_build_flash
        # A FINISHED CARD HANDED IN BY ANOTHER TAB (named: the Multi-boot
        # tab's) is only ever written.  The Build section builds the Write
        # tab's single-game image, which is not that card, and the "nothing
        # modified" check is about Write-tab edits the card never came from
        # (PAD-144: "Could you even use this option to create a fresh build
        # of a multigame?" / "a warning that nothing has changed but its not
        # really true").
        self._handed_in = handed_in or ""
        self._can_build = bool(can_build and on_build_flash is not None
                               and not self._handed_in)
        # ...and a card that was only just BUILT or UPDATED is on no SD card
        # yet.  The menu-only write refuses a card this image was not flashed
        # onto, so after a build it could only refuse - and after an update,
        # which rewrites game files INSIDE the card without changing what the
        # check compares, it would pass and leave the old games on the SD card.
        self._fresh_image = (os.path.normpath(initial_image)
                             if fresh_image and initial_image else "")
        # ...and whether a flash of an image has FINISHED onto an SD card
        # from here, asked of the app, which records every one (PAD-145).
        self._flashed_fn = flashed_fn
        self._cannot_build_reason = cannot_build_reason
        self._has_pending_changes = has_pending_changes
        self._on_choices = on_choices
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._words = _flash_words(manufacturer)
        self._base_target_label = self._words["target_label"]
        self._targets = ()           # (key, wording, drive kind) per place, stick first
        self._target_var = None
        self._target_row = None
        # The disk's WRITE (item 124): everything, only the menu, or only one
        # image from its own ISO.  Titles name the images when the tab knows
        # them; the rows exist for any brand and show only for a disk target.
        self._image_titles = [t for t in (image_titles or [])]
        self._disk_mode_var = None
        self._disk_mode_row = None
        self._from_row = None
        self._from_var = None
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
        if self._handed_in:
            return False, True              # a finished card: write it
        if not isinstance(saved, dict) or not saved:
            return (self._can_build and self._has_pending_changes), True
        build = self._can_build and bool(
            saved.get("build", self._has_pending_changes))
        write = bool(saved.get("write", True))
        if not (build or write):
            return (self._can_build and self._has_pending_changes), True
        return build, write

    def _remember_choices(self):
        """Report the ticked pair back for next time (Start only).

        Never for a handed-in card: writing the Multi-boot tab's card is not
        a choice about the Write tab's own dialog, and recording its forced
        build-off opened that dialog without the build ticked next time."""
        if self._on_choices is None or self._handed_in:
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

        # THE BUTTON ROW IS PACKED FIRST, AGAINST THE BOTTOM, and only
        # filled in at the end.  pack() hands out space in the order things
        # were packed, so the LAST widget in is the one squeezed when the
        # window ends up a few pixels short of its content - and that was
        # the row carrying Start and Cancel (David: "the confirm and cancel
        # buttons in this modal are squeezed to be too tiny to see").  A
        # dialog can be wrong about its height; it must not be able to eat
        # the two controls that end it.
        btn_row = ttk.Frame(dlg, padding=(16, 0, 16, 16))
        btn_row.pack(side="bottom", fill="x")
        body = ttk.Frame(dlg, padding=(16, 16, 16, 8))
        body.pack(fill="both", expand=True)
        self._btn_row = btn_row

        header = (getattr(self._mfr, "flash_header", None)
                  or "Build an image and/or write one onto a %s" % noun)
        intro = ("Tick both to test changes on the machine in one step: "
                 "build a fresh image, then put it straight onto the %s."
                 % noun)
        if self._handed_in:
            # Only the write is on offer, so the words say only that.
            dlg.title("Flash %s image" % noun)
            header = "Write the %s card onto the %s" % (self._handed_in,
                                                          noun)
            intro = ("The card the %s tab made, as it is: nothing here "
                     "builds or changes it. Pick the %s below; nothing is "
                     "written until you confirm." % (self._handed_in, noun))
        ttk.Label(
            body, text=header,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            body, text=intro,
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=560, justify="left").pack(anchor="w", pady=(0, 10))

        # ---- Section 1: build ----------------------------------------
        # Opening state: the pair the user last ran, else the defaults —
        # see _opening_ticks.  Never shown for a handed-in card (see
        # __init__); its widgets still exist, so the syncing has one shape.
        build_box = ttk.Frame(body)
        self._build_box = build_box
        if not self._handed_in:
            build_box.pack(fill="x")
        self._build_var = tk.BooleanVar(value=self._initial_build)
        build_check = ttk.Checkbutton(
            build_box, text="Build a fresh image from your modifications",
            variable=self._build_var, command=self._sync_sections)
        build_check.pack(anchor="w")
        if self._on_build_flash is None:
            build_check.state(["disabled"])
        elif not self._can_build:
            build_check.state(["disabled"])
            ttk.Label(
                build_box,
                text=(self._cannot_build_reason
                      or "Set the original image, assets folder and build "
                         "location on the Write tab first."),
                font=(self._sans, 9), foreground=th["gray"],
                wraplength=540, justify="left").pack(
                anchor="w", padx=(22, 0))

        target_row = ttk.Frame(build_box)
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
        # A handed-in card has nothing else to do, so there is no tick to
        # take away the one thing Start can do.
        self._write_chk = ttk.Checkbutton(
            body, text=self._words["section"],
            variable=self._write_var, command=self._sync_sections)
        if not self._handed_in:
            self._write_chk.pack(anchor="w")

        flash_body = ttk.Frame(body)
        flash_body.pack(fill="x", padx=(0 if self._handed_in else 22, 0))

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

        # WHERE IT GOES (item 123).  A brand that names ``flash_targets`` has a
        # second place for the image besides its usual medium: a JJP install ISO
        # can go straight onto the game's SSD in a dock, installed on this PC
        # exactly as the machine would (no stick, no security key).  The choice
        # swaps the drive picker's kind, so a stick is never offered as the disk
        # nor a disk as the stick.  Windows (WSL) and Linux only: the install
        # wants a Linux block device, which Docker on macOS cannot hand it.
        self._targets = tuple(getattr(self._mfr, "flash_targets", ()) or ())
        self._target_var = tk.StringVar(
            value=self._targets[0][0] if self._targets else "")
        if len(self._targets) > 1 and sys.platform in ("win32", "linux"):
            self._target_row = ttk.Frame(flash_body)
            self._target_row.pack(fill="x", pady=(2, 0))
            ttk.Label(self._target_row, text="Onto:", width=12,
                      anchor="w").pack(side="left", anchor="n")
            choices = ttk.Frame(self._target_row)
            choices.pack(side="left", fill="x", expand=True)
            for key, text, _kind in self._targets:
                ttk.Radiobutton(
                    choices, text=text, value=key, variable=self._target_var,
                    command=self._on_target_changed).pack(anchor="w")

        # WHAT GOES ONTO THE DISK (item 124).  A disk that already holds this
        # install can take the menu alone, or one image alone from that image's
        # own install ISO, and keep its settings and scores - the tool checks
        # the disk is that install before it writes.  Everything else is the
        # full install, which erases the disk.
        self._disk_mode_var = tk.StringVar(value="full")
        self._disk_mode_row = ttk.Frame(flash_body)
        ttk.Label(self._disk_mode_row, text="Write:", width=12,
                  anchor="w").pack(side="left")
        self._disk_mode_combo = ttk.Combobox(
            self._disk_mode_row, state="readonly", values=self._disk_mode_labels())
        self._disk_mode_combo.current(0)
        self._disk_mode_combo.pack(side="left", fill="x", expand=True)
        self._disk_mode_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_disk_mode_changed())
        self._from_row = ttk.Frame(flash_body)
        ttk.Label(self._from_row, text="From ISO:", width=12,
                  anchor="w").pack(side="left")
        self._from_var = tk.StringVar()
        self._from_var.trace_add("write", lambda *_a: self._update_readout())
        self._from_entry = ttk.Entry(self._from_row, textvariable=self._from_var)
        self._from_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self._from_row, text="Browse…",
                   command=self._browse_from).pack(side="left", padx=(4, 0))

        # THE MENU-ONLY WRITE.  A multi-boot card's menu lives in ONE
        # partition, so changing it and writing that partition back is 350 MB
        # rather than the whole image - a minute instead of the hour a 14.7 GB
        # image takes on an ordinary card (David: "writing to my sd card is
        # pretty slow... yes, build the menu-only write").  It also leaves
        # /data and /dump alone, so the machine keeps its settings and scores,
        # which a whole-image flash cannot.
        #
        # DEFAULT ON for an image a flash has already put onto an SD card
        # from here, and only then.  It used to be on for any image that
        # could take it, since the run refuses a card this image was not
        # flashed onto - but that ticked it for cards no SD card had ever
        # held, and a tester who had just built one reported it twice
        # (PAD-144, then PAD-145: "only boot menu" was still checked, on a
        # card built in an earlier run and flashed on its own).  Once a
        # flash of it finishes, the app records it and the next dialog ticks
        # it again, so the fast write stays one dialog away for its card.
        self._menu_var = tk.BooleanVar(value=False)
        self._menu_chk = ttk.Checkbutton(
            flash_body, variable=self._menu_var, command=self._sync_sections,
            text="Only the boot menu — fast, and the machine keeps its "
                 "settings and scores")
        self._menu_note = ttk.Label(
            flash_body, foreground=self._theme["gray"], wraplength=430,
            justify="left", text="")
        # ...and only on a brand whose flash CAN write just the menu.  A JJP
        # USB stick or a CGC card has no such write, so there the tick was a
        # Stern promise ("the machine keeps its settings and scores") that
        # the run could never keep (PAD-138).
        self._menu_offered = bool(getattr(self._mfr, "menu_flash_phases", ()))
        if self._menu_offered:
            self._menu_chk.pack(anchor="w", pady=(2, 0))
            self._menu_note.pack(anchor="w", padx=(22, 0))

        # Target-card row.
        card_row = ttk.Frame(flash_body)
        card_row.pack(fill="x", pady=4)
        self._target_label = ttk.Label(
            card_row, text=self._words["target_label"], width=12, anchor="w")
        self._target_label.pack(side="left")
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
        # general, matching the live-run Cancel in the main window).  The
        # row itself was packed at the top of this method; only its contents
        # are made here, where they read in order with everything else.
        btn_row = self._btn_row
        ttk.Button(btn_row, text="Cancel", command=self._cancel,
                   style="Danger.TButton").pack(side="right")
        self._start_btn = ttk.Button(
            btn_row, text="Start", command=self._do_start,
            style="Go.TButton")
        self._start_btn.pack(side="right", padx=(0, 8))

        self._built = True
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

    def _refit(self):
        """Re-fit the window to what it NOW needs, where it already is.

        The dialog is not resizable and its size is pinned once, at the end
        of :meth:`_build` - so anything that grows the content afterwards
        comes out of the last thing packed, which is the button row.  David
        got a Start and a Cancel squeezed to coloured slivers with no text
        in them, under a note that had grown by a line after the geometry
        was set.

        Everything that can change the height calls :meth:`_update_readout`
        on its way through, so this hangs off the end of that: the ticks
        (which swap the menu-only note), the drive list, the readout itself.
        It keeps the position - a dialog that re-centred every time someone
        ticked a box would walk across the screen."""
        if not getattr(self, "_built", False):
            return
        dlg = self._dlg
        try:
            dlg.update_idletasks()
            want = (max(dlg.winfo_reqwidth(), 620), dlg.winfo_reqheight())
            if want != (dlg.winfo_width(), dlg.winfo_height()):
                dlg.geometry("%dx%d+%d+%d"
                             % (want[0], want[1], dlg.winfo_x(),
                                dlg.winfo_y()))
        except tk.TclError:                             # pragma: no cover
            pass

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

    #: What the menu-only tick says under itself, per state.  Each says what
    #: the write is FOR, not only what it does: "The whole image is written."
    #: left a tester asking what the tick was and how it related to anything
    #: else in the dialog (PAD-144).
    _MENU_NOTE_OK = ("For an SD card that already has this image on it: "
                     "writes the menu partition only, so the games, settings "
                     "and scores stay. It checks the card first, and refuses "
                     "if the card holds anything else.")
    _MENU_NOTE_WHOLE = ("The whole image is written, games and all - what an "
                        "SD card needs the first time this image goes onto "
                        "it. The machine's settings and scores are replaced "
                        "too.")
    _MENU_NOTE_BUILD = ("A freshly built image has never been on this card, "
                        "so the whole of it has to be written.")
    _MENU_NOTE_FRESH = ("This card was only just built or updated, so no SD "
                        "card holds it yet: the whole image has to be "
                        "written.")
    _MENU_NOTE_UNFLASHED = ("This image has not been flashed onto an SD card "
                            "from here yet, so the whole of it is written, "
                            "games and all - what an SD card needs the first "
                            "time. If yours already has this image, tick this "
                            "to write only the menu; it checks the card "
                            "first.")

    def _was_flashed(self, img):
        """Has a flash of *img* finished from here?  Asked of the app; a
        dialog opened without the question knows of none."""
        if self._flashed_fn is None:
            return False
        try:
            return bool(self._flashed_fn(img))
        except Exception:                               # noqa: BLE001
            return False

    def _sync_menu_only(self, writing, building):
        """Offer the menu-only write only where it can mean anything: a
        flash (not a build+flash - a fresh image was never on that card, nor
        a handed-in card that was only just built or updated, see __init__)
        of an image that HAS a menu partition to write - and tick it only for
        an image a flash has already put onto an SD card (see _was_flashed).

        The image is asked, not assumed: reading its partition table is 512
        bytes, and an image with no Linux rootfs as its second partition is
        not a Stern card at all."""
        why = ""
        flashed = False
        img = (self._image_var.get() or "").strip().strip('"')
        # Fresh is about THAT card: browse to another image and it is offered.
        fresh = bool(self._fresh_image and img
                     and os.path.normpath(img) == self._fresh_image)
        can = bool(writing and not building and not fresh
                   and self._menu_offered)
        if can:
            try:
                menu_write_plan(img)
            except Exception:                           # noqa: BLE001
                can = False                 # not a card image, or not there
            else:
                flashed = self._was_flashed(img)
        elif writing and building:
            why = self._MENU_NOTE_BUILD
        elif writing and fresh:
            why = self._MENU_NOTE_FRESH
        try:
            self._menu_chk.state(["!disabled"] if can else ["disabled"])
        except tk.TclError:                             # pragma: no cover
            pass
        if not can:
            self._menu_var.set(False)
        elif self._menu_seen != self._image_var.get():
            # First sight of an image that supports it: on by default only
            # when an SD card already has it.
            self._menu_var.set(flashed)
        self._menu_seen = self._image_var.get()
        if can:
            why = (self._MENU_NOTE_OK if self._menu_var.get()
                   else self._MENU_NOTE_WHOLE if flashed
                   else self._MENU_NOTE_UNFLASHED)
        try:
            self._menu_note.configure(text=why)
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

    def _target(self):
        """The (key, wording, drive kind) chosen, or None when the brand offers
        one place only."""
        key = self._target_var.get() if (self._targets and self._target_var) else ""
        for t in self._targets:
            if t[0] == key:
                return t
        return None

    def _to_disk(self):
        """Is the image going onto the game's own disk rather than the brand's
        usual medium (the first target)?"""
        t = self._target()
        return t is not None and t is not self._targets[0]

    #: The disk's write choices: (key, label).  Image labels carry the tab's
    #: titles when it handed them over.
    def _disk_modes(self):
        titles = self._image_titles
        return [("full", "everything: a fresh install (the disk is erased)"),
                ("menu", "only the boot menu (the games, settings and scores stay)"),
                ("image0", "only image 0%s, from its own ISO" % ((": " + titles[0]) if len(titles) > 0 and titles[0] else " (root A)")),
                ("image1", "only image 1%s, from its own ISO" % ((": " + titles[1]) if len(titles) > 1 and titles[1] else " (root B)"))]

    def _disk_mode_labels(self):
        return [label for _k, label in self._disk_modes()]

    def _disk_mode(self):
        """"full" / "menu" / "image0" / "image1" - "full" whenever the disk is
        not the target."""
        if not self._to_disk() or self._disk_mode_var is None:
            return "full"
        idx = self._disk_mode_combo.current() if hasattr(self, "_disk_mode_combo") else 0
        modes = self._disk_modes()
        return modes[idx][0] if 0 <= idx < len(modes) else "full"

    def _on_disk_mode_changed(self):
        self._disk_mode_var.set(self._disk_mode())
        self._sync_disk_rows()
        self._update_readout()

    def _sync_disk_rows(self):
        """The Write row shows for a disk target; the From ISO row for an image
        write.  Packed after the image-file row, before the drive row."""
        if self._disk_mode_row is None:
            return
        to_disk = self._to_disk()
        mode = self._disk_mode()
        if to_disk and not self._disk_mode_row.winfo_manager():
            self._disk_mode_row.pack(fill="x", pady=(2, 0), after=self._target_row)
        elif not to_disk and self._disk_mode_row.winfo_manager():
            self._disk_mode_row.pack_forget()
        want_from = to_disk and mode.startswith("image")
        if want_from and not self._from_row.winfo_manager():
            self._from_row.pack(fill="x", pady=(2, 0), after=self._disk_mode_row)
        elif not want_from and self._from_row.winfo_manager():
            self._from_row.pack_forget()

    def _browse_from(self):
        path = filedialog.askopenfilename(
            parent=self._dlg,
            title="Select the image's own install ISO",
            filetypes=self._words["filetypes"])
        if path:
            self._from_var.set(path)

    def _on_target_changed(self):
        t = self._target()
        if t is None:
            return
        self._sync_disk_rows()
        # the picker's kind follows the place: a stick's list hides disks, a
        # disk's shows them (the game SSD is a big removable disk)
        self._words["target_kind"] = t[2]
        self._words["target_label"] = ("Target disk:" if self._to_disk()
                                       else self._base_target_label)
        self._target_label.configure(text=self._words["target_label"])
        self._selected = None
        self._refresh_drives()
        self._update_readout()

    def _on_drive_selected(self):
        idx = self._drive_combo.current()
        self._selected = (self._drives[idx]
                          if 0 <= idx < len(self._drives) else None)
        self._update_readout()

    def _update_readout(self):
        """Show image size vs card capacity and a preliminary fit check -
        and then re-fit the window to whatever that left it needing.

        EVERYTHING THAT CHANGES THIS DIALOG'S HEIGHT COMES THROUGH HERE (the
        ticks, the drive list, the readout's own three states), which is why
        the re-fit hangs off it rather than off each of them."""
        self._readout_text()
        self._refit()

    def _readout_text(self):
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
        if self._to_disk():
            # No fit line: the disk must be big enough for the INSTALL, which the
            # tool checks the way the machine's installer does before it writes.
            mode = self._disk_mode()
            if card is None:
                self._readout.configure(
                    text="Image: %s  •  pick the game's disk." % _fmt_size(img_size),
                    foreground=th["gray"])
            elif mode == "menu":
                self._readout.configure(
                    text="Image %s  →  %s: only the boot menu is replaced; the disk "
                         "must already hold this install (it is checked first)."
                         % (_fmt_size(img_size), card.display),
                    foreground=th["gray"])
            elif mode.startswith("image"):
                src = (self._from_var.get() or "").strip()
                self._readout.configure(
                    text="Image %s  →  %s: only image %s is replaced, from %s; the "
                         "disk must already hold this install (it is checked first)."
                         % (_fmt_size(img_size), card.display, mode[-1],
                            os.path.basename(src) if src else "an ISO still to pick"),
                    foreground=th["gray"] if src else th["error"])
            else:
                self._readout.configure(
                    text="Image %s  →  %s: the whole disk is erased and the game "
                         "installed onto it, as the machine's installer would."
                         % (_fmt_size(img_size), card.display),
                    foreground=th["gray"])
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

        if building and self._to_disk():
            messagebox.showwarning(
                "Build first",
                "Build the image first, then reopen this dialog to install the "
                "finished image onto the disk - or choose the stick to build "
                "and make a stick in one step.", parent=self._dlg)
            return
        img = self._image_var.get().strip()
        card = self._selected
        if writing:
            if not building and (not img or not os.path.isfile(img)):
                what = self._words["filetypes"][0][0]
                messagebox.showwarning(
                    "No image",
                    ("Pick a %s." % what if self._handed_in else
                     "Pick a %s — or tick \"Build a fresh image\" to build "
                     "one first." % what),
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
            # Never for a handed-in card: it was just made on another tab,
            # and "nothing was modified" said the opposite (PAD-144).
            if (not building and not self._has_pending_changes
                    and not self._handed_in):
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
            if (not building and card.size_bytes and not self._to_disk()
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
            elif self._to_disk() and self._disk_mode() == "menu":
                if not messagebox.askyesno(
                    "Replace the boot menu?",
                    "This replaces the BOOT MENU on the disk and nothing else: the "
                    "games, settings and scores stay. The disk is checked first "
                    "and refused if it does not hold this install.\n\n"
                    "  Target: %s\n  Image:  %s\n\nProceed?"
                    % (card.display, flash_what), parent=self._dlg,
                ):
                    return
            elif self._to_disk() and self._disk_mode().startswith("image"):
                src = (self._from_var.get() or "").strip()
                if not src or not os.path.isfile(src):
                    messagebox.showwarning(
                        "No ISO for the image",
                        "Pick the image's own install ISO (From ISO:) - the game "
                        "code that goes into that slot.", parent=self._dlg)
                    return
                if not messagebox.askyesno(
                    "Replace image %s?" % self._disk_mode()[-1],
                    "This replaces IMAGE %s on the disk with the game in %s and "
                    "nothing else: the other image, the menu, the settings and "
                    "scores stay. The disk is checked first, and a different game "
                    "version is refused (both images share one settings "
                    "partition).\n\n  Target: %s\n  Image:  %s\n\nProceed?"
                    % (self._disk_mode()[-1], os.path.basename(src), card.display,
                       flash_what), parent=self._dlg,
                ):
                    return
            elif self._to_disk():
                # THE DISK IS INSTALLED, NOT COPIED ONTO: every partition is
                # rewritten the way the machine's installer rewrites them, so
                # whatever the disk held - a game, its settings and scores - is
                # gone, and the words say so before the drive name.
                if not messagebox.askyesno(
                    "Erase the disk and install onto it?",
                    "This will ERASE the entire disk and install %s onto it "
                    "exactly as the machine's own installer would: every "
                    "partition is rewritten, so any settings and scores on it "
                    "are gone (as after every JJP install). There is no undo."
                    "\n\n  Target: %s\n  Image:  %s\n\n"
                    "Make sure this is the game's SSD and not a backup drive. "
                    "Proceed?" % (flash_what, card.display, flash_what),
                    icon="warning", parent=self._dlg,
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
        # The disk's extras are read NOW, while the widgets exist: the dialog
        # is destroyed before the callback runs, and a combobox asked after
        # that is a TclError.  ``target`` and the rest go only where a second
        # place was chosen: every other brand's callback has never heard of them.
        extra = {}
        if self._to_disk():
            extra["target"] = self._target()[0]
            mode = self._disk_mode()
            if mode == "menu":
                extra["disk_mode"] = "menu"
            elif mode.startswith("image"):
                extra["disk_mode"] = "image"
                extra["image"] = int(mode[-1])
                extra["from_iso"] = (self._from_var.get() or "").strip()
        # Past every confirmation — this is the pair the user committed to, so
        # it's the pair the dialog opens with next time.
        self._remember_choices()
        self._dlg.grab_release()
        self._dlg.destroy()
        if building:
            if self._on_build_flash is not None:
                self._on_build_flash(build_path, device_path)
        elif writing and self._on_flash is not None:
            self._on_flash(img, device_path, menu_only=menu_only, **extra)

    def _cancel(self):
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
