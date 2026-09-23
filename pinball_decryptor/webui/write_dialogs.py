"""The Write tab's windows, as page dialogs.

* :class:`FlashDialog` - gui/flash_dialog.py's ``FlashImageDialog``: build an
  image and/or write one onto a card (a JJP stick, a JJP disk in a dock).
* :class:`DiagnoseDialog` - gui/diagnose_dialog.py's ``DiagnoseCardDialog``
  (CGC's "Card diagnostics…").
* :class:`ImageInfo` - the Tk window's Image Info window (the ⓘ badge).

Each keeps its state in Python and publishes a plain dict the page renders
(``write.flash`` / ``write.diag`` / ``write.info``); the page's edits come
back through the Write tab's ``@rpc`` methods.  The logic, the wording and
every confirmation are the Tk dialogs'; only the widgets are gone.  No raw
device I/O happens here: drives come from ``core.drives`` (advertised sizes),
and the writes run in the app's pipelines after the dialog has closed.
"""

import os
import sys
import threading

from . import compat


def _fmt_size(n):
    """Decimal GB/MB size string for the readout (matches card packaging)."""
    if not n:
        return "unknown"
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 10 ** 9)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 10 ** 6)
    return "%d bytes" % n


def flash_words(mfr):
    """The manufacturer's flash-surface wording (flash_dialog._flash_words)."""
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
        "target_label": (getattr(mfr, "flash_target_label", None)
                         or "Target %s:" % noun),
        "filetypes": [tuple(ft) for ft in
                      getattr(mfr, "flash_image_filetypes", None)
                      or (("SD-card image", "*.img *.raw *.bin"),
                          ("All files", "*.*"))],
    }


def _is_admin():
    try:
        from ..core.admin import is_admin
        return bool(is_admin())
    except Exception:                                   # noqa: BLE001
        return False


def _self_elevates():
    try:
        from ..core.elevated_flash import can_self_elevate
        return bool(can_self_elevate())
    except Exception:                                   # noqa: BLE001
        return False


def _enumerate(prefer):
    """(drives, pick) off the UI loop: the same enumeration Tk used."""
    try:
        from ..core.drives import list_physical_drives, pick_best_game_ssd
        drives = list_physical_drives()
        pick = pick_best_game_ssd(drives, prefer=prefer)
    except Exception:                                   # noqa: BLE001
        drives, pick = [], (None, None, None)
    return drives, pick


class FlashDialog:
    """The Build / flash dialog's state and logic (FlashImageDialog)."""

    #: What the menu-only tick says under itself, per state.
    MENU_NOTE_OK = ("For an SD card that already has this image on it: "
                    "writes the menu partition only, so the games, settings "
                    "and scores stay. It checks the card first, and refuses "
                    "if the card holds anything else.")
    MENU_NOTE_WHOLE = ("The whole image is written, games and all - what an "
                       "SD card needs the first time this image goes onto "
                       "it. The machine's settings and scores are replaced "
                       "too.")
    MENU_NOTE_BUILD = ("A freshly built image has never been on this card, "
                       "so the whole of it has to be written.")
    MENU_NOTE_FRESH = ("This card was only just built or updated, so no SD "
                       "card holds it yet: the whole image has to be "
                       "written.")
    MENU_NOTE_UNFLASHED = ("This image has not been flashed onto an SD card "
                           "from here yet, so the whole of it is written, "
                           "games and all - what an SD card needs the first "
                           "time. If yours already has this image, tick this "
                           "to write only the menu; it checks the card "
                           "first.")

    def __init__(self, host, manufacturer, on_flash, initial_image=None,
                 on_build_flash=None, build_target="", can_build=False,
                 cannot_build_reason="", has_pending_changes=True,
                 initial_choices=None, on_choices=None, handed_in="",
                 fresh_image=False, flashed_fn=None, image_titles=None,
                 publish=None, ask_open=None, ask_save=None,
                 build_size=None, build_size_hint=""):
        self._host = host                  # the UI loop (post)
        # The size of the image a build makes, when the Write tab knows it
        # (Stern Spike 2: the SD card size chosen there changes it).  With
        # Build ticked, the fit is checked against THIS rather than whatever
        # an earlier build left at the build path; None keeps that file.
        self._build_size = int(build_size) if build_size else None
        #: what else the user can do when the build won't fit the card
        self._build_size_hint = build_size_hint or ""
        self._mfr = manufacturer
        self._on_flash = on_flash
        self._on_build_flash = on_build_flash
        self._handed_in = handed_in or ""
        self._can_build = bool(can_build and on_build_flash is not None
                               and not self._handed_in)
        self._build_possible = on_build_flash is not None
        self._fresh_image = (os.path.normpath(initial_image)
                             if fresh_image and initial_image else "")
        self._flashed_fn = flashed_fn
        self._cannot_build_reason = cannot_build_reason
        self._has_pending_changes = has_pending_changes
        self._on_choices = on_choices
        self._publish = publish or (lambda d: None)
        self._ask_open = ask_open
        self._ask_save = ask_save
        self.words = flash_words(manufacturer)
        self._base_target_label = self.words["target_label"]
        self._image_titles = list(image_titles or [])
        self._targets = tuple(getattr(manufacturer, "flash_targets", ())
                              or ())
        self.target = self._targets[0][0] if self._targets else ""
        self.disk_mode = "full"
        self.from_path = ""
        self.drives = []
        self.selected = None
        self.drive_text = ""
        self._enum_id = 0
        self._menu_seen = None
        self.menu_offered = bool(getattr(manufacturer, "menu_flash_phases",
                                         ()))
        self.menu = False
        self.menu_enabled = False
        self.menu_note = ""
        self.closed = False
        self.build, self.write = self._opening_ticks(initial_choices)
        self.build_path = build_target or ""
        self.image_path = ""
        if (not self.build and initial_image
                and os.path.isfile(initial_image)):
            self.image_path = initial_image
        self._admin = _is_admin()
        self._elevates = _self_elevates()
        self._sync_sections(publish=False)
        self.refresh_drives()

    # ------------------------------------------------------------------
    def _opening_ticks(self, saved):
        if self._handed_in:
            return False, True
        if not isinstance(saved, dict) or not saved:
            return (self._can_build and self._has_pending_changes), True
        build = self._can_build and bool(
            saved.get("build", self._has_pending_changes))
        write = bool(saved.get("write", True))
        if not (build or write):
            return (self._can_build and self._has_pending_changes), True
        return build, write

    def _remember_choices(self):
        if self._on_choices is None or self._handed_in:
            return
        choices = {"write": bool(self.write)}
        if self._can_build:
            choices["build"] = bool(self.build)
        try:
            self._on_choices(choices)
        except Exception:                               # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    @property
    def building(self):
        return bool(self.build and self._can_build)

    def _target(self):
        key = self.target if self._targets else ""
        for t in self._targets:
            if t[0] == key:
                return t
        return None

    def to_disk(self):
        t = self._target()
        return t is not None and t is not self._targets[0]

    def disk_modes(self):
        titles = self._image_titles
        return [("full", "everything: a fresh install (the disk is erased)"),
                ("menu", "only the boot menu (the games, settings and "
                         "scores stay)"),
                ("image0", "only image 0%s, from its own ISO" % (
                    (": " + titles[0]) if len(titles) > 0 and titles[0]
                    else " (root A)")),
                ("image1", "only image 1%s, from its own ISO" % (
                    (": " + titles[1]) if len(titles) > 1 and titles[1]
                    else " (root B)"))]

    def current_disk_mode(self):
        if not self.to_disk():
            return "full"
        keys = [k for k, _l in self.disk_modes()]
        return self.disk_mode if self.disk_mode in keys else "full"

    def start_label(self):
        action = self.words["action"]
        building, writing = self.building, bool(self.write)
        if building and writing:
            return "Build + %s" % action
        if building:
            return "Build image"
        if writing:
            return ("Flash image" if action == "flash"
                    else action[0].upper() + action[1:])
        return "Start"

    def _sync_sections(self, publish=True):
        if self.building:
            self.image_path = self.build_path
        self._sync_menu_only()
        if publish:
            self.publish()

    def _was_flashed(self, img):
        if self._flashed_fn is None:
            return False
        try:
            return bool(self._flashed_fn(img))
        except Exception:                               # noqa: BLE001
            return False

    def _sync_menu_only(self):
        from ..core.rawdevice import menu_write_plan
        writing, building = bool(self.write), self.building
        why = ""
        flashed = False
        img = (self.image_path or "").strip().strip('"')
        fresh = bool(self._fresh_image and img
                     and os.path.normpath(img) == self._fresh_image)
        can = bool(writing and not building and not fresh
                   and self.menu_offered)
        if can:
            try:
                menu_write_plan(img)
            except Exception:                           # noqa: BLE001
                can = False
            else:
                flashed = self._was_flashed(img)
        elif writing and building:
            why = self.MENU_NOTE_BUILD
        elif writing and fresh:
            why = self.MENU_NOTE_FRESH
        self.menu_enabled = can
        if not can:
            self.menu = False
        elif self._menu_seen != self.image_path:
            self.menu = flashed
        self._menu_seen = self.image_path
        if can:
            why = (self.MENU_NOTE_OK if self.menu
                   else self.MENU_NOTE_WHOLE if flashed
                   else self.MENU_NOTE_UNFLASHED)
        self.menu_note = why

    # ------------------------------------------------------------------
    def readout(self):
        """(text, kind) - kind is "gray" | "err" | "ok"."""
        if not self.write:
            return "", "gray"
        building = self.building
        img = (self.image_path or "").strip()
        img_size = (os.path.getsize(img)
                    if img and os.path.isfile(img) else None)
        if building and self._build_size:
            img_size = self._build_size
        card = self.selected
        card_size = card.size_bytes if card else None
        if building and img_size is None:
            return ("The image is built first — its size is checked "
                    "against the card before writing.", "gray")
        if img_size is None:
            return "", "gray"
        if self.to_disk():
            mode = self.current_disk_mode()
            if card is None:
                return ("Image: %s  •  pick the game's disk."
                        % _fmt_size(img_size), "gray")
            if mode == "menu":
                return ("Image %s  →  %s: only the boot menu is replaced; "
                        "the disk must already hold this install (it is "
                        "checked first)." % (_fmt_size(img_size),
                                             card.display), "gray")
            if mode.startswith("image"):
                src = (self.from_path or "").strip()
                return ("Image %s  →  %s: only image %s is replaced, from "
                        "%s; the disk must already hold this install (it is "
                        "checked first)."
                        % (_fmt_size(img_size), card.display, mode[-1],
                           os.path.basename(src) if src
                           else "an ISO still to pick"),
                        "gray" if src else "err")
            return ("Image %s  →  %s: the whole disk is erased and the game "
                    "installed onto it, as the machine's installer would."
                    % (_fmt_size(img_size), card.display), "gray")
        noun = self.words["noun"]
        if card is None:
            return ("Image: %s  •  pick a target %s."
                    % (_fmt_size(img_size), noun), "gray")
        if card_size and img_size > card_size:
            if building and self._build_size:
                return ("⚠ The build will be %s, larger than the %s %s — it "
                        "won't fit. Use a larger %s%s."
                        % (_fmt_size(img_size), noun, _fmt_size(card_size),
                           noun, (", " + self._build_size_hint)
                           if self._build_size_hint else ""), "err")
            return ("⚠ Image %s is larger than the %s %s — it won't fit. "
                    "Use a larger %s." % (_fmt_size(img_size), noun,
                                          _fmt_size(card_size), noun), "err")
        if card_size:
            return ("Image %s  →  %s %s   ✓ fits"
                    % (_fmt_size(img_size), noun, _fmt_size(card_size)),
                    "ok")
        return ("Image %s  →  %s size unknown (it will be checked before "
                "writing)" % (_fmt_size(img_size), noun), "gray")

    def state(self):
        building, writing = self.building, bool(self.write)
        noun = self.words["noun"]
        header = (getattr(self._mfr, "flash_header", None)
                  or "Build an image and/or write one onto a %s" % noun)
        intro = ("Tick both to test changes on the machine in one step: "
                 "build a fresh image, then put it straight onto the %s."
                 % noun)
        title = self.words["title"]
        if self._handed_in:
            title = "Flash %s image" % noun
            header = "Write the %s card onto the %s" % (self._handed_in,
                                                          noun)
            intro = ("The card the %s tab made, as it is: nothing here "
                     "builds or changes it. Pick the %s below; nothing is "
                     "written until you confirm." % (self._handed_in, noun))
        text, kind = self.readout()
        to_disk = self.to_disk()
        mode = self.current_disk_mode()
        show_targets = (len(self._targets) > 1
                        and sys.platform in ("win32", "linux"))
        unc = ""
        if sys.platform == "win32" and self._admin:
            unc = ("Running as administrator: Windows hides mapped network "
                   "drive letters (e.g. W:) from elevated apps. If your "
                   "project or build location is on a network share, use "
                   "its full \\\\server\\share path, not a drive letter.")
        admin_note = ""
        if not self._admin:
            admin_note = ("You may be asked to approve administrator access "
                          "when the card write starts." if self._elevates
                          else "Writing the card needs administrator access. "
                               "Re-launch the app as an administrator, then "
                               "reopen this dialog.")
        drives = [{"i": i, "display": d.display}
                  for i, d in enumerate(self.drives)]
        sel = (self.drives.index(self.selected)
               if self.selected is not None and self.selected in self.drives
               else None)
        return {
            "title": title, "header": header, "intro": intro,
            "handed_in": bool(self._handed_in),
            "build_possible": self._build_possible,
            "can_build": self._can_build,
            "cannot_build_reason": (
                "" if self._can_build or not self._build_possible
                else (self._cannot_build_reason
                      or "Set the original image, assets folder and build "
                         "location on the Write tab first.")),
            "build": bool(self.build), "building": building,
            "build_path": self.build_path,
            "write": writing, "section": self.words["section"],
            "image_path": self.image_path,
            "image_enabled": bool(writing and not building),
            "targets": ([{"key": k, "label": t} for k, t, _kind
                         in self._targets] if show_targets else []),
            "target": self.target,
            "show_disk_mode": bool(to_disk),
            "disk_modes": [{"value": k, "label": lbl}
                           for k, lbl in self.disk_modes()],
            "disk_mode": mode,
            "show_from": bool(to_disk and mode.startswith("image")),
            "from_path": self.from_path,
            "menu_offered": self.menu_offered, "menu": bool(self.menu),
            "menu_enabled": bool(self.menu_enabled),
            "menu_note": self.menu_note,
            "target_label": self.words["target_label"],
            "drives": drives, "drive": sel, "drive_text": self.drive_text,
            "drives_enabled": writing,
            "readout": text, "readout_kind": kind,
            "safety": self.words["safety"] or "",
            "unc_note": unc, "admin_note": admin_note,
            "start_label": self.start_label(),
            "start_enabled": bool(building or writing),
        }

    def publish(self):
        if not self.closed:
            self._publish(self.state())

    # ------------------------------------------------------------------
    # the page's edits
    # ------------------------------------------------------------------
    def set(self, key, value):
        if key in ("build", "write", "menu"):
            if key == "build" and not self._can_build:
                return
            if key == "menu" and not self.menu_enabled:
                return
            setattr(self, key, bool(value))
            if key == "menu":
                # the note follows the tick (flash_dialog: the tick's own
                # command is _sync_sections)
                self._sync_sections()
            else:
                self._sync_sections()
            return
        if key == "build_path":
            self.build_path = str(value or "")
            if self.building:
                self.image_path = self.build_path
                self._sync_menu_only()
        elif key == "image_path":
            if self.building:
                return
            self.image_path = str(value or "")
            self._sync_menu_only()
        elif key == "from_path":
            self.from_path = str(value or "")
        elif key == "target":
            if value in [t[0] for t in self._targets]:
                self.target = value
                self._on_target_changed()
                return
        elif key == "disk_mode":
            self.disk_mode = str(value or "full")
        elif key == "drive":
            try:
                idx = int(value)
            except (TypeError, ValueError):
                idx = -1
            self.selected = (self.drives[idx]
                             if 0 <= idx < len(self.drives) else None)
        self.publish()

    def _on_target_changed(self):
        t = self._target()
        if t is None:
            return
        self.words["target_kind"] = t[2]
        self.words["target_label"] = ("Target disk:" if self.to_disk()
                                      else self._base_target_label)
        self.selected = None
        self.refresh_drives()

    def browse(self, which):
        if which == "build":
            if not self.building or self._ask_save is None:
                return None
            cur = (self.build_path or "").strip()
            initial_dir = os.path.dirname(cur) if cur else ""
            if initial_dir and not os.path.isdir(initial_dir):
                initial_dir = ""
            path = self._ask_save(
                "write_flash_build", "Build the image to…",
                initialfile=os.path.basename(cur) if cur else "",
                filetypes=self.words["filetypes"], initialdir=initial_dir)
            if path:
                self.set("build_path", os.path.normpath(path))
            return path
        if which == "image":
            if not (self.write and not self.building) or \
                    self._ask_open is None:
                return None
            cur = (self.image_path or "").strip()
            initial = ""
            if cur:
                parent = os.path.dirname(cur)
                if parent and os.path.isdir(parent):
                    initial = parent
            path = self._ask_open(
                "write_flash_image",
                "Select the %s" % self.words["filetypes"][0][0],
                self.words["filetypes"], initialdir=initial)
            if path:
                self.set("image_path", path)
            return path
        if which == "from":
            if self._ask_open is None:
                return None
            path = self._ask_open(
                "write_flash_from", "Select the image's own install ISO",
                self.words["filetypes"])
            if path:
                self.set("from_path", path)
            return path
        return None

    # ------------------------------------------------------------------
    # drives
    # ------------------------------------------------------------------
    def refresh_drives(self):
        self._enum_id += 1
        my_id = self._enum_id
        self.drives = []
        self.selected = None
        self.drive_text = "Detecting drives…"
        self.publish()
        prefer = self.words["target_kind"]

        def _worker():
            drives, pick = _enumerate(prefer)
            self._host.post(self._apply_drives, my_id, drives, pick)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        if self.closed or my_id != self._enum_id:
            return
        from ..core.drives import visible_drives
        prefer = self.words["target_kind"]
        best = pick[0] if pick else None
        drives = visible_drives(drives, prefer=prefer,
                                keep=[best] if best else ())
        self.drives = list(drives)
        if not drives:
            self.drive_text = "(no drives found — click Refresh)"
            self.selected = None
            self.publish()
            return
        if best is None and prefer == "usb_stick":
            self.drive_text = ("(no USB stick detected — pick one, or "
                               "connect it and click Refresh)")
            self.selected = None
            self.publish()
            return
        chosen = best if (best and best in drives) else drives[0]
        self.selected = chosen
        self.drive_text = ""
        self.publish()

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def start(self):
        """Validate, confirm and hand off.  True when the dialog closed."""
        mb = compat.messagebox
        building = self.building
        writing = bool(self.write)
        noun = self.words["noun"]
        if not (building or writing):
            return False
        build_path = (self.build_path or "").strip() if building else None
        if building and not build_path:
            mb.showwarning(
                "No build location",
                "Pick where the built image should be written (Build to:).")
            return False
        if building and not self._has_pending_changes:
            if not mb.askyesno(
                    "Nothing modified",
                    "No modified files were detected, so this will build a "
                    "copy of the original image with no changes.\n\nBuild "
                    "anyway?", icon="warning"):
                return False
        if building and self.to_disk():
            mb.showwarning(
                "Build first",
                "Build the image first, then reopen this dialog to install "
                "the finished image onto the disk - or choose the stick to "
                "build and make a stick in one step.")
            return False
        img = (self.image_path or "").strip()
        card = self.selected
        if writing:
            if not building and (not img or not os.path.isfile(img)):
                what = self.words["filetypes"][0][0]
                mb.showwarning(
                    "No image",
                    ("Pick a %s." % what if self._handed_in else
                     "Pick a %s — or tick \"Build a fresh image\" to build "
                     "one first." % what))
                return False
            if card is None:
                mb.showwarning(
                    "No %s selected" % noun,
                    "Pick a target %s from the dropdown. If it's empty, "
                    "connect the %s and click Refresh." % (noun, noun))
                return False
            if (not building and not self._has_pending_changes
                    and not self._handed_in):
                if not mb.askyesno(
                        "Nothing modified",
                        "Nothing was modified this session.\n\nFlashing "
                        "writes a whole pre-built or backup image onto the "
                        "card, independent of any edits here — expected if "
                        "you're restoring a backup or re-flashing an image "
                        "you built earlier.\n\nFlash anyway?",
                        icon="warning"):
                    return False
            if (not building and card.size_bytes and not self.to_disk()
                    and os.path.getsize(img) > card.size_bytes):
                mb.showerror(
                    "Image too big",
                    "The image (%s) is larger than the %s (%s). Use a "
                    "larger %s." % (_fmt_size(os.path.getsize(img)), noun,
                                    _fmt_size(card.size_bytes), noun))
                return False
            # the same check for a build, when its size is known up front:
            # refused now, not after the build when the chained write is
            if (building and self._build_size and card.size_bytes
                    and not self.to_disk()
                    and self._build_size > card.size_bytes):
                mb.showerror(
                    "Image too big",
                    "The build will be %s, larger than the %s (%s). Use a "
                    "larger %s%s." % (_fmt_size(self._build_size), noun,
                                      _fmt_size(card.size_bytes), noun,
                                      (", " + self._build_size_hint)
                                      if self._build_size_hint else ""))
                return False
            flash_what = (os.path.basename(build_path)
                          if building else os.path.basename(img))
            verb = self.words["confirm_verb"]
            mode = self.current_disk_mode()
            if self.menu and not building:
                if not mb.askyesno(
                        "Write the boot menu?",
                        "This replaces the BOOT MENU on %s and nothing "
                        "else.\n\n  Target: %s\n  Image:  %s\n\nThe games "
                        "stay as they are, and so do the machine's own "
                        "settings and scores. If the card was not written "
                        "from this image it is refused before anything is "
                        "written. Proceed?" % (noun, card.display,
                                               flash_what)):
                    return False
            elif self.to_disk() and mode == "menu":
                if not mb.askyesno(
                        "Replace the boot menu?",
                        "This replaces the BOOT MENU on the disk and nothing "
                        "else: the games, settings and scores stay. The disk "
                        "is checked first and refused if it does not hold "
                        "this install.\n\n  Target: %s\n  Image:  %s\n\n"
                        "Proceed?" % (card.display, flash_what)):
                    return False
            elif self.to_disk() and mode.startswith("image"):
                src = (self.from_path or "").strip()
                if not src or not os.path.isfile(src):
                    mb.showwarning(
                        "No ISO for the image",
                        "Pick the image's own install ISO (From ISO:) - the "
                        "game code that goes into that slot.")
                    return False
                if not mb.askyesno(
                        "Replace image %s?" % mode[-1],
                        "This replaces IMAGE %s on the disk with the game in "
                        "%s and nothing else: the other image, the menu, the "
                        "settings and scores stay. The disk is checked "
                        "first, and a different game version is refused "
                        "(both images share one settings partition).\n\n"
                        "  Target: %s\n  Image:  %s\n\nProceed?"
                        % (mode[-1], os.path.basename(src), card.display,
                           flash_what)):
                    return False
            elif self.to_disk():
                if not mb.askyesno(
                        "Erase the disk and install onto it?",
                        "This will ERASE the entire disk and install %s onto "
                        "it exactly as the machine's own installer would: "
                        "every partition is rewritten, so any settings and "
                        "scores on it are gone (as after every JJP install). "
                        "There is no undo.\n\n  Target: %s\n  Image:  %s\n\n"
                        "Make sure this is the game's SSD and not a backup "
                        "drive. Proceed?" % (flash_what, card.display,
                                             flash_what),
                        icon="warning"):
                    return False
            else:
                lead = ("After the build finishes, this will ERASE the "
                        "entire %s and %s." % (noun, verb)
                        if building else
                        "This will ERASE the entire %s and %s." % (noun,
                                                                   verb))
                if not mb.askyesno(
                        "Erase the %s and continue?" % noun,
                        "%s There is no undo.\n\n  Target: %s\n  Image:  %s"
                        "\n\nMake sure you have a backup of anything on the "
                        "%s. Proceed?"
                        % (lead, card.display, flash_what, noun),
                        icon="warning"):
                    return False

        menu_only = bool(self.menu) and not building
        device_path = card.device_path if (writing and card) else None
        extra = {}
        if self.to_disk():
            extra["target"] = self._target()[0]
            mode = self.current_disk_mode()
            if mode == "menu":
                extra["disk_mode"] = "menu"
            elif mode.startswith("image"):
                extra["disk_mode"] = "image"
                extra["image"] = int(mode[-1])
                extra["from_iso"] = (self.from_path or "").strip()
        self._remember_choices()
        self.close()
        if building:
            if self._on_build_flash is not None:
                self._on_build_flash(build_path, device_path)
        elif writing and self._on_flash is not None:
            self._on_flash(img, device_path, menu_only=menu_only, **extra)
        return True

    def close(self):
        self.closed = True
        self._enum_id += 1
        self._publish(None)


class DiagnoseDialog:
    """CGC's Card diagnostics (DiagnoseCardDialog): read-only."""

    def __init__(self, host, manufacturer, publish, ask_open, ask_save):
        self._host = host
        self._mfr = manufacturer
        self._publish = publish
        self._ask_open = ask_open
        self._ask_save = ask_save
        self.noun = getattr(manufacturer, "direct_medium_noun", "SD card")
        self.help = getattr(
            manufacturer, "diagnose_card_help",
            "Reads diagnostic information off the card. Read-only.")
        self.drives = []
        self.selected = None
        self.drive_text = ""
        self.lines = []
        self.report = None
        self.running = False
        self.closed = False
        self._enum_id = 0
        self._admin = _is_admin()
        self.refresh_drives()

    def state(self):
        sel = (self.drives.index(self.selected)
               if self.selected is not None and self.selected in self.drives
               else None)
        return {
            "header": "Read the installer's log from a %s" % self.noun,
            "help": self.help,
            "admin_warn": (
                "" if self._admin else
                "⚠ Reading a physical card needs Administrator (close the "
                "app, right-click the shortcut, choose \"Run as "
                "administrator\", and reopen). Diagnosing an image file with "
                "\"Image file…\" does not need Administrator."),
            "drives": [{"i": i, "display": d.display}
                       for i, d in enumerate(self.drives)],
            "drive": sel, "drive_text": self.drive_text,
            "text": "\n".join(self.lines),
            "running": self.running,
            "can_save": bool(self.report),
        }

    def publish(self):
        if not self.closed:
            self._publish(self.state())

    def refresh_drives(self):
        self._enum_id += 1
        my_id = self._enum_id
        self.drives = []
        self.selected = None
        self.drive_text = "Detecting drives…"
        self.publish()
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")

        def _worker():
            drives, pick = _enumerate(prefer)
            self._host.post(self._apply_drives, my_id, drives, pick)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        if self.closed or my_id != self._enum_id:
            return
        from ..core.drives import visible_drives
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")
        best = pick[0] if pick else None
        drives = visible_drives(drives, prefer=prefer,
                                keep=[best] if best else ())
        self.drives = list(drives)
        if not drives:
            self.drive_text = "(no drives found — click Refresh)"
            self.selected = None
        else:
            self.selected = best if (best and best in drives) else drives[0]
            self.drive_text = ""
        self.publish()

    def select(self, index):
        try:
            idx = int(index)
        except (TypeError, ValueError):
            idx = -1
        self.selected = (self.drives[idx]
                         if 0 <= idx < len(self.drives) else None)
        self.publish()

    def read_card(self):
        if self.running:
            return False
        mb = compat.messagebox
        if self.selected is None:
            mb.showwarning(
                "No card selected",
                "Pick a card from the dropdown. If it's empty, connect the "
                "card and click Refresh.")
            return False
        if not self._admin:
            mb.showerror(
                "Administrator required",
                "Reading raw disk sectors needs Administrator. Re-launch the "
                "app as administrator and try again.\n\nTo diagnose an image "
                "*file* instead (no Administrator needed), use \"Image "
                "file…\".")
            return False
        self._launch(self.selected.device_path)
        return True

    def read_file(self):
        if self.running:
            return False
        path = self._ask_open(
            "write_diag_file", "Select an installer image to diagnose",
            [("Installer image", "*.img *.raw *.bin"), ("All files", "*.*")])
        if not path:
            return False
        self._launch(path)
        return True

    def _launch(self, target):
        self.running = True
        self.report = None
        self.lines = []
        self.publish()
        mfr = self._mfr

        def _log(m):
            self._host.post(self._append, str(m))

        def _worker():
            try:
                report = mfr.diagnose_card(target, log=_log)
                self._host.post(self._finish, report, None)
            except Exception as e:                      # noqa: BLE001
                self._host.post(self._finish, None, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _append(self, msg):
        if self.closed:
            return
        self.lines.append(msg)
        self.publish()

    def _finish(self, report, error):
        if self.closed:
            return
        self.running = False
        if error is not None:
            self.lines += ["", "FAILED: %s" % error]
            self.publish()
            return
        self.report = report
        self.lines += ["", str(report)]
        self.publish()

    def save(self):
        if not self.report:
            return False
        mb = compat.messagebox
        path = self._ask_save(
            "write_diag_save", "Save diagnostics report",
            initialfile="card_diagnostics.txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
            defaultextension=".txt")
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.report + "\n")
        except OSError as e:
            mb.showerror("Save failed", str(e))
            return False
        mb.showinfo("Saved", "Report saved to:\n%s" % path)
        return True

    def close(self):
        self.closed = True
        self._enum_id += 1
        self._publish(None)


class ImageInfo:
    """The Image Info window (main_window._open_image_info & co.)."""

    def __init__(self, host, publish):
        self._host = host
        self._publish = publish
        self.path = ""
        self.sections = []
        self.busy = False
        self.status = ""
        self.open = False
        self._seq = 0
        self._shown_key = None

    def state(self):
        return {"path": self.path, "busy": self.busy, "status": self.status,
                "sections": [{"title": t, "rows": [[str(r[0]), str(r[1])]
                                                   for r in rows]}
                             for t, rows in self.sections]}

    def publish(self):
        self._publish(self.state() if self.open else None)

    def show(self, path, mfr, assets):
        from ..core.rawdevice import is_device_path
        mb = compat.messagebox
        path = (path or "").strip()
        if not path:
            mb.showinfo("No image selected",
                        "Pick an image in the box next to the Info button "
                        "first.")
            return False
        if is_device_path(path):
            self.path = path
        elif not os.path.isfile(path):
            mb.showerror("File not found", "No file at:\n\n%s" % path)
            return False
        else:
            self.path = os.path.normpath(path)
        self.open = True
        self.refresh(mfr, assets)
        return True

    def refresh(self, mfr, assets, force=False):
        if not self.open:
            return
        key = (os.path.normcase(self.path), assets)
        if not force and key == self._shown_key:
            self.publish()
            return
        from ..core import image_info as info_mod
        self._seq += 1
        seq = self._seq
        self._shown_key = None
        self.sections = []
        self.busy = True
        self.status = "Reading image…"
        self.publish()
        path = self.path

        def _worker():
            try:
                sections = info_mod.collect(mfr, path, assets)
            except Exception as e:                      # noqa: BLE001
                sections = [("Error", [("Could not read", str(e))])]
            self._host.post(self._done, seq, key, sections)

        threading.Thread(target=_worker, daemon=True).start()

    def _done(self, seq, key, sections):
        if seq != self._seq or not self.open:
            return
        self._shown_key = key
        self.sections = list(sections or [])
        self.busy = False
        self.status = ""
        self.publish()

    def report_text(self):
        from ..core import image_info as info_mod
        if not self.sections:
            return ""
        self.status = "Report copied to clipboard."
        self.publish()
        return info_mod.as_text(self.sections)

    def close(self):
        self._seq += 1
        self.open = False
        self.sections = []
        self.path = ""
        self._shown_key = None
        self._publish(None)
