"""Write tab: turn the project's edits into something a machine can use.

The port of gui/main_window.py ``_build_write_tab`` and every method behind
it: the destination toggle (build an image file / write to the card in
place), the Original + Project Folder mirrors, the Build Image path and its
Change…, the BOF update-version date, the grow-for-longer-text option, the
Modified Files list (MD5 scan + staged rows, sort, Export CSV, Revert all),
the one primary button (Build / Apply, or the Build / flash dialog) with its
one live Cancel, Card diagnostics (CGC), Apply Delta and How to Install.

The run logic (app.py) reads ``write_*_var`` and the methods in ``exports``
off the window exactly as it read them off the Tk window.  Status: see
docs/plans/web_ui_tabs/write.md.
"""

import csv
import logging
import os
import re
import sys
import threading
import time

from .. import compat
from .. import write_scan
from ..write_dialogs import DiagnoseDialog, FlashDialog, ImageInfo
from .base import TabService, rpc

log = logging.getLogger(__name__)

NO_PROJECT = "(no project yet — extract into one on the Extract tab)"
EMPTY_NO_FOLDER = ("Select your modified assets folder above to preview "
                   "changed files.")
FLASH_BTN_TEXT = "Build / flash SD card…"
FLASH_BTN_TIP = (
    "Build a fresh image and/or write one onto an SD card — tick "
    "both in the dialog to build and flash in one step. Flashing "
    "erases and replaces the whole card, and needs Administrator "
    "(approved when the write starts).")
EXPORT_TIP = (
    "Save this list — every file the next build will write, with its "
    "type and whether it already differs from the extract or is "
    "staged for the build — as a CSV.\n\nFor comparing two projects "
    "that disagree about how many changes they hold.")
TEXT_GROW_LABEL = ("Advanced: grow the game program / a scene for longer text "
                   "(default on; a machine has not booted such a build yet)")
TEXT_GROW_TIP = (
    "On: a Replace Text edit longer than its original slot (a row "
    "whose Max reads \"96 (grows)\") is placed in a new read-only "
    "area of the game program with every reference pointed at it, "
    "or — for scene text — the scene file is rewritten at the new "
    "length; either needs the card built as an image, not a "
    "Direct-SD write. Off: every row keeps its original budget and "
    "over-long edits are skipped with a named reason in the build "
    "log. Proven in the PC emulator only; keep the stock card to "
    "hand. Mirrored to PAD_STERN_TEXT_GROW for the build.")
#: Stern Spike 2: the SD card class a build is for (plugins/stern/card_size.py;
#: the engine's no-space failure points at this control by its label).
CARD_SIZE_LABEL = "SD card size"
CARD_SIZE_TIP = (
    "Every replaced video and longer sound goes onto the card's games "
    "partition, which is only as big as Stern made it for the original's "
    "card size; the note under this control says how much of it is free at "
    "each size. If the SD card in your machine is bigger, build for it: the "
    "games partition grows to fill that card size and everything else on the "
    "card stays exactly as it was. The built image is that size, so it only "
    "fits an SD card at least that big. A bigger card adds room and nothing "
    "else: the game's own limit of about 2 GB on its sound bank stays the "
    "same, and a replacement that has to fit its original's space (a sound "
    "that isn't made longer, a video written straight to the card) still "
    "has to.")
CARD_SIZE_SAME = "Same as the original"
#: the way back, said under every refusal of an SD card size (the Build /
#: flash dialog's and app._start_write's)
CARD_SIZE_WAY_BACK = ("To build it at its own size, choose \"Same as the "
                      "original\" under SD card size on the Write tab.")
#: the classes a build can be grown to, smallest first (card_size.CARD_SIZES
#: holds the 8 GB class too, which no card grows to)
CARD_SIZE_CHOICES = ("16G", "32G")
EDITABLE_HINT = (
    "Tip: edit your audio (.wav), images (.webp), and video (.ogv) "
    "files in pck/_EDITABLE ASSETS/ inside your Modified Assets "
    "folder. Write auto-detects changes there and re-encodes them.")
UNC_HINT = (
    "Running as administrator: Windows hides mapped network "
    "drive letters (e.g. W:) from elevated apps. If your "
    "modified assets live on a network share, paste the full "
    "\\\\server\\share path into the field above instead of "
    "browsing to a drive letter.")
DEFAULT_SSD_WARN = (
    "⚠ Remove the SSD from the pinball machine before "
    "connecting. Always keep the original ISO as a backup.")
DELTA_TEXT = (
    "Layer a delta update on top of the extracted assets before "
    "rebuilding.  Files in the delta overwrite or get added on top of "
    "your assets folder.")
FDA_TITLE = "⚠  macOS FULL DISK ACCESS REQUIRED"
FDA_TEXT = (
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
    "auto-hides after your first successful SSD extract.")
ADMIN_TITLE = "⚠  ADMINISTRATOR PRIVILEGES REQUIRED"
SORT_IDX = {"file": 0, "type": 1, "status": 2}
FLASHED_IMAGES_KEPT = 32
#: settings.json column_widths key of the Modified Files list (Tk's
#: _persist_tree_columns(self._write_preview_tree, "write_preview", ...)),
#: and the page's column keys against Tk's column ids.
WIDTHS_KEY = "write_preview"
TK_COLUMN_IDS = {"file": "#0", "type": "type", "status": "status"}
MISMATCH_HEAD = ("Your Replace-tab assignments were made against a different "
                 "project folder than the one you're building.")
UNPLAYABLE_NOTE = (
    'Video slot "%s" currently holds a clip that %s — on the machine it '
    'will play its sound over a black picture. Assign a good replacement '
    '(or revert the slot) before building.')
#: the Replace tabs whose lists can hold files this extract never produced
#: (Tk _note_foreign_slots): (service ns, surface name, attribute)
FOREIGN_SURFACES = (("audio", "Replace Audio", "_foreign"),
                    ("video", "Replace Video", "_foreign"),
                    ("images", "Replace Images", "_foreign_rels"))


def _is_admin():
    try:
        from ...core.admin import is_admin
        return bool(is_admin())
    except Exception:                                   # noqa: BLE001
        return False


def card_size_supported(platform=None):
    """Whether this computer (or *platform*, a ``sys.platform`` value) can
    build a Spike 2 card for a bigger SD card.  card_size.py grows the games
    partition through a loop device, and macOS has none (card_size._E2fs
    refuses there), so the option is not offered on macOS and a saved choice
    reads as the original's size.  app.App's _norm_card_size asks this."""
    return (platform or sys.platform) != "darwin"


def _norm_card_size(val):
    """A card size as the setting holds it: "16G" / "32G", anything else ""
    (the original's own size); always "" where the option isn't offered.
    app.App._norm_card_size's rule."""
    val = val.strip().upper() if isinstance(val, str) else ""
    if not card_size_supported():
        return ""
    return val if val in CARD_SIZE_CHOICES else ""


def _class_words(name):
    """"16G" -> "16 GB" (the card packaging's words)."""
    return name[:-1] + " GB" if name and name.endswith("G") else name


#: the card class in a build's default file name (Stern names its images
#: "...Release.8G.sdcard.raw")
_NAME_CLASS = re.compile(r"(?<![0-9A-Za-z])(8|16|32)G(?![0-9A-Za-z])")


def _name_for_class(name, cls):
    """*name* with its card class token (the last "8G" / "16G" / "32G"
    standing on its own in the stem) swapped for *cls*; unchanged when it
    has none.  A build for a bigger card must not be named for the
    original's card size, and an 8 GB and a 16 GB build of one project then
    stop overwriting each other."""
    stem, ext = os.path.splitext(name)
    hits = list(_NAME_CLASS.finditer(stem))
    if not hits:
        return name
    m = hits[-1]
    return stem[:m.start()] + cls + stem[m.end():] + ext


def _probe_card_size(path):
    """What the SD card size control needs to know about the original at
    *path* (reads its partition tables, and for a card that can grow, asks
    the multi-boot reader; OFF the UI loop).  ``None`` when it is not a file
    this app can read; else ``{"own": "8G" | None, "size": the file's size,
    "why": {choice: (class it builds at or None, error sentence, the built
    image's size or None)}, "room": {class: usable bytes}}`` with ``own``
    None when the tables are not laid out the way Stern lays a Spike 2 card
    out.  The built size is card_size.plan's: the class size, or the original
    FILE's size when that is longer (a dump of a whole bigger SD card keeps
    its length).  ``room`` is :func:`_probe_room`'s."""
    from ...core.longpath import ext as _lp
    from ...plugins.stern import card_size as cs
    try:
        if not os.path.isfile(path):
            return None
        own = layout = None
        with open(_lp(path), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            try:
                layout = cs.read_layout(f, size)
                own = cs.class_of(layout.laid_out)
            except cs.CardSizeError:
                own = layout = None
        why = {}
        for choice in CARD_SIZE_CHOICES:
            try:
                builds_at = cs.target_for(path, choice)
            except cs.CardSizeError as e:
                why[choice] = (None, str(e), None)
                continue
            out = None
            if builds_at and layout is not None:
                out = cs.plan(layout, builds_at)[1].size
            why[choice] = (builds_at, "", out)
    except OSError:
        return None
    room = _probe_room(path, layout, own, why)
    return {"own": own, "size": size, "why": why, "room": room}


def _probe_room(path, layout, own, why):
    """``{class: bytes}``: the room the files a build puts on whole
    (replaced videos, a grown sound bank) have on the games partition of the
    original at *path*, at its own size and at each bigger size it can be
    built for (card_size.room_by_class, the figures the engine's pre-flight
    measures a build against).  Read from the partition's superblock and
    group descriptors, a few KB, OFF the UI loop.  Counted as the kernel's
    driver copies (card_size.ROUTE_MOUNT), which keeps a small reserve back:
    never more room than every route has.  A size whose room can't be worked
    out is left out; ``{}`` when the partition can't be read."""
    if layout is None or not own:
        return {}
    from ...plugins.stern import card_size as cs
    try:
        space = cs.read_space(path)
    except Exception:  # noqa: BLE001 - not a filesystem this reads: no figure
        log.debug("card size probe: games partition not read", exc_info=True)
        return {}
    classes = [own] + [c for c in CARD_SIZE_CHOICES
                       if (why.get(c) or (None, "", None))[0]
                       and not why[c][1]]
    room = {}
    for c in classes:
        try:
            room.update(cs.room_by_class(layout, space, [c], cs.ROUTE_MOUNT))
        except Exception:  # noqa: BLE001 - a layout the estimate can't grow
            log.debug("card size probe: no room figure at %s", c,
                      exc_info=True)
    return room


def _room_words(room, own, offered):
    """The SD card size note's sentence on the room a build has for the files
    it puts on whole, from the probe's *room* (:func:`_probe_room`): at the
    original's own size *own*, then at each of the *offered* bigger sizes, or
    "" when the original's own figure isn't known.  Starts with a space, to
    follow the note's first sentence."""
    from ...plugins.stern.card_size import size_words
    if own not in room:
        return ""
    text = (" Its games partition, where replaced videos and longer sounds "
            "go, has %s free" % size_words(room[own]))
    bigger = [c for c in offered if c in room]
    for i, c in enumerate(bigger):
        text += ("; built for a %s card it has %s" if not i
                 else ", for a %s card %s") % (_class_words(c),
                                               size_words(room[c]))
    return text + "."


# Whether THIS computer can grow a card: card_size._E2fs asks the Linux this
# app uses (WSL on Windows) for e2fsprogs and a loop device, the machine half
# of card_size.preflight.  Asking starts that Linux, so it is never asked on
# the UI loop: a worker asks once a bigger size is chosen, well before the
# Build / flash dialog's Start, and the answer is kept.  A yes holds for the
# session; a no (or no answer) is asked again after a minute, because the
# prerequisites strip can mend it, and holds until the new answer is in.
_GROW_HERE = {"why": None, "at": None, "busy": False}
_GROW_HERE_LOCK = threading.Lock()
_GROW_HERE_RECHECK = 60.0


def _grow_here():
    """"" when this computer can grow a card, the reason it can't, or None
    when that isn't known yet."""
    with _GROW_HERE_LOCK:
        return _GROW_HERE["why"]


def _ask_grow_here(then=None):
    """Ask whether this computer can grow a card, on a worker thread, unless
    it can, is being asked, or was asked less than a minute ago.  *then()*
    runs on that thread once the answer is in.  True when it asks."""
    with _GROW_HERE_LOCK:
        st = _GROW_HERE
        if st["busy"] or st["why"] == "" or (
                st["at"] is not None
                and time.monotonic() - st["at"] < _GROW_HERE_RECHECK):
            return False
        st["busy"] = True

    def _worker():
        from ...plugins.stern import card_size as cs
        why = None
        try:
            cs._E2fs()
            why = ""
        except cs.CardSizeError as e:
            why = (str(e).strip()
                   or "the games partition can't be grown here")
        except Exception:                               # noqa: BLE001
            # no answer: the build's own check says, and this asks again
            # in a minute rather than straight away
            log.exception("can this computer grow a card")
        with _GROW_HERE_LOCK:
            if why is not None:
                _GROW_HERE["why"] = why
            _GROW_HERE["at"] = time.monotonic()
            _GROW_HERE["busy"] = False
        if then is not None:
            try:
                then()
            except Exception:                           # noqa: BLE001
                log.exception("card size: after asking this computer")

    threading.Thread(target=_worker, daemon=True,
                     name="card-size-here").start()
    return True


class WriteTab(TabService):
    ns = "write"
    key = "Write"
    label = "Write"
    group = "Build"
    icon = "write"
    exports = (
        "write_upd_var", "write_assets_var", "write_output_var",
        "write_filename_var", "write_input_source_var", "write_drive_var",
        "write_drive_display_var", "write_partition_override_var",
        "write_text_grow_var", "write_version_auto_var",
        "write_version_date_var", "write_card_size_var",
        "write_version_override", "write_version_validation_error",
        "_target_write_path", "text_grow_enabled", "card_size_choice",
        "card_size_problem", "set_flash_running",
        "begin_revert_view", "_remember_flashed_image", "_image_was_flashed",
        "_open_flash_dialog", "_has_pending_write_changes",
        "_scan_write_preview", "_maybe_rescan_write_preview",
        "_default_write_filename", "_update_write_filename",
    )

    def __init__(self, window):
        super().__init__(window)
        cb = window.cb
        self.write_upd_var = self.var("upd")
        self.write_assets_var = self.var("assets")
        self.write_output_var = self.var("output")
        self.write_filename_var = self.var("filename")
        self.write_input_source_var = self.var("source", value="iso")
        self.write_drive_var = self.var("drive")
        self.write_drive_display_var = self.var("drive_display")
        self.write_partition_override_var = self.var("partition_override")
        tg = cb.get("initial_text_grow")
        self.write_text_grow_var = self.var(
            "text_grow", "bool", True if tg is None else bool(tg))
        self.write_card_size_var = self.var(
            "card_size", "str", _norm_card_size(cb.get("initial_card_size")))
        self.write_version_auto_var = self.var("version_auto", "bool", True)
        self.write_version_date_var = self.var("version_date")

        self._write_filename_auto = ""
        self._write_output_auto = ""
        self._write_version_baseline = None
        self._drives_cache = []
        self._drive_enum_id = 0
        self._badge_seq = 0
        # the SD card size control: what the original is, read off the loop
        # (None = nothing to show), and the probe that answers for the
        # current original
        self._card_probe = None
        self._card_probe_path = ""
        self._card_seq = 0
        self._suggested_mfr = None
        self._rows = []                  # [(file, type, status, tag)]
        self._sort = (None, False)
        self._scan_id = 0
        self._scan_t0 = None
        self._scan_reason = None
        self._scanning = False
        self._scan_fp = None
        self._disk_epoch = 0
        self._rescan_after_run = False
        self._flash_running = False
        self._run_mode = None
        self._applying = False
        self._mirrors_hooked = False
        self._saved_flash_choices = dict(cb.get("initial_flash_choices")
                                         or {})
        self._flashed_images = [d for d in (cb.get("initial_flashed_images")
                                            or []) if isinstance(d, str)]
        self._fda_ack = bool(cb.get("initial_fda_acknowledged", False))
        self._admin_collapsed = bool(cb.get("initial_admin_warning_collapsed",
                                            False))
        self._flash = None
        self._return_tab = None
        # True once the shell draws the Build / flash dialog over every tab
        # (write_dialogs.js WriteOverlays); until then the dialog is drawn
        # by this tab's page and a caller on another tab borrows it
        self._flash_hosted = False
        self._diag = None
        self._info = ImageInfo(self.ctx.loop, lambda d: self.set(info=d))

        self.write_upd_var.trace_add("write", lambda *_a: self._on_upd())
        self.write_assets_var.trace_add("write", lambda *_a: self._on_assets())
        self.write_output_var.trace_add(
            "write", lambda *_a: self._update_write_filename())
        self.write_filename_var.trace_add(
            "write", lambda *_a: self._on_filename())
        self.write_input_source_var.trace_add(
            "write", lambda *_a: self._on_source_var())
        self.write_drive_display_var.trace_add(
            "write", lambda *_a: self._on_drive_selected())
        self.write_text_grow_var.trace_add(
            "write", lambda *_a: self._on_text_grow_toggle())
        self.write_card_size_var.trace_add(
            "write", lambda *_a: self._on_card_size_change())
        self.write_version_auto_var.trace_add(
            "write", lambda *_a: self._on_version_auto_toggle())
        self.write_version_date_var.trace_add(
            "write", lambda *_a: self._publish_version())

        self.set(rows=[], sort=None, count=0, scanning=False, scan_msg="",
                 empty=EMPTY_NO_FOLDER, flash_dlg=None, diag=None, info=None,
                 drives=[], drive_text="", badge="", badge_switch=False,
                 assets_warning="", build_path="", filename_hint="",
                 filename_hint_kind="", version_hint="", running=False,
                 cancel=False, primary_disabled=False, revert_enabled=False,
                 refresh_disabled=False, fda_ack=self._fda_ack,
                 admin_collapsed=self._admin_collapsed,
                 project=NO_PROJECT, project_set=False, prebuild=[],
                 widths=self._saved_widths(), flash_hosted=False,
                 card_size_cap=False, card_size_options=[],
                 card_size_shown="", card_size_note="",
                 card_size_note_kind="", card_size_label=CARD_SIZE_LABEL,
                 card_size_tip=CARD_SIZE_TIP)
        self._hook_mirrors()

    # ------------------------------------------------------------------
    # the Extract tab is the single source of truth (Tk batch 19): its
    # Input IS the Original, its Project Folder IS the shared assets folder
    # ------------------------------------------------------------------
    def _export_var(self, name):
        svc = (getattr(self.window, "_exports", {}) or {}).get(name)
        return getattr(svc, name, None) if svc is not None else None

    def _hook_mirrors(self):
        if self._mirrors_hooked:
            return
        inp = self._export_var("extract_input_var")
        out = self._export_var("extract_output_var")
        if inp is None or out is None:
            return
        self._mirrors_hooked = True
        inp.trace_add("write", lambda *_a: self._mirror_stock_image())
        out.trace_add("write", lambda *_a: self._mirror_project_folder())
        self._mirror_stock_image()
        self._mirror_project_folder()

    def _mirror_stock_image(self):
        var = self._export_var("extract_input_var")
        if var is None:
            return
        val = var.get()
        if self.write_upd_var.get() != val:
            self.write_upd_var.set(val)

    def _mirror_project_folder(self):
        var = self._export_var("extract_output_var")
        if var is None:
            return
        val = var.get()
        if self.write_assets_var.get() != val:
            self.write_assets_var.set(val)

    # ------------------------------------------------------------------
    # manufacturer
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        self._hook_mirrors()
        caps = mfr.capabilities
        g = lambda n: bool(getattr(caps, n, False))    # noqa: E731
        noun = getattr(mfr, "extract_input_label", None)
        primary = (mfr.input_spec.extensions[0]
                   if mfr.input_spec and mfr.input_spec.extensions
                   else "file")
        if noun:
            original_label = "Original %s" % noun
        else:
            original_label = ("Original %s" % primary
                              if primary.startswith(".") else "Original")
        medium = getattr(mfr, "direct_medium_noun", "SSD")
        has_replace = (g("replace_audio") or g("replace_video")
                       or g("replace_image") or g("replace_text"))
        flash = g("flash_image")
        try:
            install = mfr.write_install_help() if g("write") else None
        except Exception:                               # noqa: BLE001
            install = None
        values = dict(
            write_cap=g("write"),
            direct=g("direct_ssd"),
            iso_label=getattr(mfr, "write_iso_label", "Build USB ISO"),
            ssd_label=getattr(mfr, "write_ssd_label", "Write to SSD"),
            iso_tip=(
                "Build a modified copy of the whole image to a FILE on this "
                "PC. Nothing is written to a %s — use \"Build / flash %s…\" "
                "below to put the finished image onto one (that erases and "
                "rewrites the entire %s)." % (medium, medium, medium)),
            ssd_tip=(
                "Write your changed files straight onto a connected %s, in "
                "place — no image file, and the rest of the %s is left "
                "alone. This is NOT the same as flashing: \"Build / flash "
                "%s…\" replaces the whole %s with a fresh image."
                % (medium, medium, medium, medium)),
            medium=medium,
            original_label=original_label,
            # what Build makes, for the page subtitle: the flash plugins
            # build a whole card/stick image, the rest an update package
            # (their button reads "Build update")
            build_noun="an image" if flash else "an update",
            flash=flash,
            flash_label=(getattr(mfr, "flash_button_text", None)
                         or FLASH_BTN_TEXT),
            flash_tip=(getattr(mfr, "flash_button_tip", None)
                       or FLASH_BTN_TIP),
            flash_noun=(getattr(mfr, "flash_medium_noun", None)
                        or medium),
            revert_cap=bool(has_replace
                            and self.window.cb.get("on_revert_all")),
            diagnose=bool(flash and getattr(mfr, "diagnose_card", None)),
            editable_hint=(EDITABLE_HINT if mfr.key == "bof" and g("write")
                           else ""),
            text_grow_cap=bool(g("replace_text") and g("write")),
            version_cap=bool(g("write_version_date") and g("write")),
            delta_cap=g("apply_delta"),
            delta_text=DELTA_TEXT,
            install_help=install or "",
            safety=(getattr(mfr, "direct_safety_text", None)
                    or DEFAULT_SSD_WARN),
            admin_title=ADMIN_TITLE,
            admin_body=self._admin_body_text(mfr),
            fda_title=FDA_TITLE, fda_text=FDA_TEXT,
            unc_hint=UNC_HINT,
            text_grow_label=TEXT_GROW_LABEL, text_grow_tip=TEXT_GROW_TIP,
            export_tip=EXPORT_TIP,
            platform=sys.platform,
        )
        self.set(**values)
        # a previous manufacturer's windows must not survive under this one
        self._return_tab = None
        for dlg in (self._flash, self._diag):
            if dlg is not None:
                dlg.close()
        self._flash = self._diag = None
        self._info.close()
        self._applying = True
        try:
            if not g("direct_ssd"):
                self.write_input_source_var.set("iso")
        finally:
            self._applying = False
        if g("direct_ssd"):
            self._on_input_source_change()
        else:
            self._layout_for_source()
            if g("write"):
                self._scan_write_preview()
        if g("write_version_date") and g("write"):
            self._refresh_write_version_field()
        self._update_write_badge()
        self._update_write_filename()
        self._refresh_prebuild_notes()
        self._refresh_card_size()
        self._sync_buttons()

    @staticmethod
    def _admin_body_text(mfr):
        noun = getattr(mfr, "direct_medium_noun", "SSD") if mfr else "SSD"
        ssd_label = (getattr(mfr, "extract_ssd_label", "From SSD")
                     if mfr else "From SSD")
        return (
            f"Reading directly from the {noun} needs Windows Administrator "
            "privileges — Windows gates raw disk access behind elevation. "
            "Close the app, right-click the \"Pinball Asset Decryptor\" "
            "shortcut, choose \"Run as administrator\", then re-select "
            f"\"{ssd_label}\" — your drive and output folder are remembered.")

    # ------------------------------------------------------------------
    # destination (image file vs straight onto the card)
    # ------------------------------------------------------------------
    def _is_direct(self):
        mfr = self.mfr
        return bool(mfr is not None
                    and getattr(mfr.capabilities, "direct_ssd", False)
                    and self.write_input_source_var.get() == "ssd")

    def _on_source_var(self):
        if self._applying:
            return
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "direct_ssd", False):
            return
        self._on_input_source_change()

    def _layout_for_source(self):
        """What the Tk repack did: which rows show for this source."""
        direct = self._is_direct()
        admin = _is_admin()
        # the app acknowledges FDA through the Extract tab's export (after a
        # successful direct run); honour either side's acknowledgement
        fda_ack = self._fda_ack or bool(self.store.get("extract", "fda_ack"))
        self.set(
            direct_mode=direct,
            show_admin=bool(direct and sys.platform == "win32"
                            and not admin),
            show_fda=bool(direct and sys.platform == "darwin"
                          and not fda_ack),
            show_unc=bool(direct and sys.platform == "win32" and admin))

    def _on_input_source_change(self):
        """main_window._on_input_source_change("write")."""
        self._layout_for_source()
        self._sync_badge()
        if self._is_direct():
            self._refresh_drives()
        self._scan_reason = "write destination changed"
        self._scan_write_preview()
        self._update_write_filename()
        fn = self._export_fn("_refresh_extract_phases")
        if fn is not None:
            try:
                fn()
            except Exception:                           # noqa: BLE001
                log.exception("refresh phases")
        self._sync_buttons()

    def _export_fn(self, name):
        svc = (getattr(self.window, "_exports", {}) or {}).get(name)
        return getattr(svc, name, None) if svc is not None else None

    # -- the card picker (direct mode) -------------------------------------
    def _refresh_drives(self):
        self._drive_enum_id += 1
        my_id = self._drive_enum_id
        self.set(drives=[], drive_text="Detecting drives…")
        self.write_drive_display_var.set("Detecting drives…")
        prefer = getattr(self.mfr, "direct_target_kind", "ssd")

        def _worker():
            try:
                from ...core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:                           # noqa: BLE001
                drives, pick = [], (None, None, None)
            self.ctx.loop.post(self._apply_drives, my_id, drives, pick)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        if my_id != self._drive_enum_id:
            return
        if not drives:
            self._drives_cache = []
            text = "(no drives found — click Refresh)"
            self.set(drives=[], drive_text=text)
            self.write_drive_display_var.set(text)
            self.log("No physical drives detected.  Check that the SSD "
                     "is connected and click Refresh.", "error")
            return
        best, confidence, reason = pick
        from ...core.drives import visible_drives
        prefer = getattr(self.mfr, "direct_target_kind", "ssd")
        keep = (best,) if best is not None else ()
        shown = visible_drives(drives, prefer=prefer, keep=keep)
        hidden = len(drives) - len(shown)
        self._drives_cache = list(shown)
        self.set(drives=[d.display for d in shown], drive_text="")
        if best is not None:
            self.write_drive_display_var.set(best.display)
            self.log("Selected SSD: %s" % best.display,
                     "success" if confidence == "high" else "info")
            if reason:
                self.log("  (%s)" % reason, "info")
            if confidence != "high":
                noun = getattr(self.mfr, "direct_medium_noun", "SSD")
                self.log("  If this isn't the %s, pick it manually from "
                         "the dropdown." % noun, "info")
        else:
            self.write_drive_display_var.set(shown[0].display)
        if hidden > 0:
            self.log("  (hid %d drive(s) too large to be a game SD card; "
                     "connect the card and click Refresh if you don't see "
                     "it)" % hidden, "info")

    def _on_drive_selected(self):
        label = self.write_drive_display_var.get()
        match = next((d for d in self._drives_cache if d.display == label),
                     None)
        dev = match.device_path if match else ""
        if self.write_drive_var.get() != dev:
            self.write_drive_var.set(dev)

    # ------------------------------------------------------------------
    # Original / detect badge
    # ------------------------------------------------------------------
    def _on_upd(self):
        self._update_write_badge()
        self._maybe_default_write_output()
        self._update_write_filename()
        self._refresh_card_size()

    def _update_write_badge(self):
        """main_window._set_badge(mode="write"), with the detection (it reads
        the image) off the loop."""
        self._badge_seq += 1
        seq = self._badge_seq
        self._suggested_mfr = None
        path = (self.write_upd_var.get() or "").strip()
        mfr = self.mfr
        if not path or mfr is None or not os.path.isfile(path):
            self.set(badge="", badge_switch=False)
            self._sync_badge()
            return
        others = list(self.window.manufacturers)

        def _worker():
            try:
                game = mfr.detect(path)
            except Exception:                           # noqa: BLE001
                game = None
            hits = []
            if not game:
                for m in others:
                    if m.key == mfr.key:
                        continue
                    try:
                        g = m.detect(path)
                    except Exception:                   # noqa: BLE001
                        continue
                    if g:
                        hits.append((m, g))
            self.ctx.loop.post(self._apply_badge, seq, mfr, game, hits)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_badge(self, seq, mfr, game, hits):
        if seq != self._badge_seq or mfr is not self.mfr:
            return
        text, switch = "", False
        if game:
            caps = mfr.capabilities
            if hasattr(mfr, "set_era") and not caps.write and not (
                    caps.replace_audio or caps.replace_video
                    or caps.replace_image or caps.replace_text):
                text = ("Extract only — this format has no Write/Replace "
                        "support.")
        elif len(hits) == 1:
            m, g = hits[0]
            self._suggested_mfr = m
            text = "Looks like %s (%s) — click to switch" % (g.display,
                                                             m.display)
            switch = True
        elif len(hits) > 1:
            text = "Matches multiple manufacturers: %s" % ", ".join(
                m.display for m, _ in hits)
        else:
            text = "Not recognised as %s" % mfr.display
        self.set(badge=text, badge_switch=switch)
        self._sync_badge()

    def _sync_badge(self):
        self.set(badge_shown=bool(self.get("badge")) and not self._is_direct())

    # ------------------------------------------------------------------
    # project folder
    # ------------------------------------------------------------------
    def _on_assets(self):
        folder = (self.write_assets_var.get() or "").strip()
        self.set(project=folder or NO_PROJECT, project_set=bool(folder))
        self._derive_build_output()
        self._maybe_rescan_write_preview()
        self._refresh_write_assets_warning()
        self._refresh_write_version_field()
        self._refresh_prebuild_notes()

    # ------------------------------------------------------------------
    # "Before you build" (the design's card): problems the run logic and
    # the Replace tabs already find before a build, in their own words.
    # Tk only logged them (and app.py asks about the first at Build).
    # ------------------------------------------------------------------
    @staticmethod
    def _norm(path):
        return os.path.normcase(os.path.normpath(path)) if path else ""

    def _prebuild_notes(self):
        mfr = self.mfr
        assets = (self.write_assets_var.get() or "").strip()
        if (not assets or mfr is None
                or not getattr(mfr.capabilities, "write", False)):
            return []
        here = self._norm(assets)
        errs, warns, infos = [], [], []
        # a video slot holding a clip the machine can't play (the Video
        # tab's red log line, MainWindow._warn_unplayable_slot)
        video = self.window.service("video")
        warned = getattr(video, "_unplayable_warned", None) or ()
        by_rel = getattr(video, "_by_rel", None) or {}
        if warned and by_rel:
            from .. import video_helpers as vh
            for scan_dir, rel in sorted(warned, key=lambda k: str(k[1])):
                if self._norm(scan_dir) != here or rel not in by_rel:
                    continue
                try:
                    why = vh.slot_unplayable(mfr.key, by_rel[rel])
                except Exception:                       # noqa: BLE001
                    why = None
                if why:
                    errs.append({"kind": "err",
                                 "text": UNPLAYABLE_NOTE % (rel, why)})
        # Replace-tab assignments made against another folder (the question
        # app.py asks before a build: replacement_mismatch_message)
        try:
            mism = self.window.replacement_folder_mismatches(assets) or []
        except Exception:                               # noqa: BLE001
            mism = []
        if mism:
            lines = "\n".join(
                "  • %d %s replacement(s) — assigned for: %s" % (n, kind,
                                                                folder)
                for kind, n, folder in mism)
            warns.append({"kind": "warn",
                          "text": "%s\n%s" % (MISMATCH_HEAD, lines)})
        # files a Replace tab lists that this extract never produced
        # (MainWindow._note_foreign_slots)
        for ns, surface, attr in FOREIGN_SURFACES:
            svc = self.window.service(ns)
            foreign = getattr(svc, attr, None) if svc is not None else None
            if (not foreign
                    or self._norm(getattr(svc, "_scan_dir", "") or "")
                    != here):
                continue
            shown = ", ".join(sorted(foreign)[:3])
            if len(foreign) > 3:
                shown += ", and %d more" % (len(foreign) - 3)
            infos.append({"kind": "", "text": (
                "%s: %d file(s) in this folder aren't part of this extract "
                "(%s); a build can't use them." % (surface, len(foreign),
                                                   shown))})
        return errs + warns + infos

    def _refresh_prebuild_notes(self):
        try:
            notes = self._prebuild_notes()
        except Exception:                               # noqa: BLE001
            log.exception("write pre-build notes")
            notes = []
        self.set(prebuild=notes)

    def _refresh_write_assets_warning(self):
        path = (self.write_assets_var.get() or "").strip()
        msg = ""
        if (path and os.path.isdir(path)
                and not os.path.isfile(os.path.join(path, ".checksums.md5"))):
            ancestor = write_scan.find_checksums_ancestor(path)
            if ancestor:
                msg = ("⚠ No `.checksums.md5` here. Did you mean the "
                       f"parent folder `{ancestor}`?")
            else:
                msg = ("⚠ No `.checksums.md5` here. Pick the folder "
                       "produced by Extract (it should contain "
                       "`.checksums.md5` at the root).")
        self.set(assets_warning=msg)

    # ------------------------------------------------------------------
    # Build Image (folder + name)
    # ------------------------------------------------------------------
    def _maybe_default_write_output(self):
        if self.write_output_var.get().strip():
            return
        upd = self.write_upd_var.get().strip()
        if upd and os.path.isfile(upd):
            parent = os.path.dirname(os.path.normpath(upd))
            if parent and os.path.isdir(parent):
                self.write_output_var.set(parent)

    def _derive_build_output(self):
        folder = (self.write_assets_var.get() or "").strip()
        if not folder:
            return
        from ...core import project_file
        try:
            derived = os.path.normpath(project_file.project_build_dir(folder))
        except Exception:                               # noqa: BLE001
            derived = os.path.normpath(os.path.join(folder, "build"))
        current = self.write_output_var.get().strip()
        if current == derived:
            self._write_output_auto = derived
            return
        legacy_auto = ""
        upd = (self.write_upd_var.get() or "").strip()
        if upd:
            legacy_auto = os.path.normpath(
                os.path.dirname(os.path.normpath(upd)))
        if (not current or current == self._write_output_auto
                or (legacy_auto and current == legacy_auto)):
            self._write_output_auto = derived
            self.write_output_var.set(derived)

    def _default_write_filename(self):
        upd = self.write_upd_var.get().strip()
        if not upd:
            return ""
        name = os.path.basename(upd)
        mfr = self.mfr
        suffix = getattr(mfr, "write_output_suffix", "") if mfr else ""
        if (not suffix and mfr is not None
                and getattr(mfr.capabilities, "flash_image", False)):
            suffix = "-modified"
        if suffix:
            stem, ext = os.path.splitext(name)
            name = f"{stem}{suffix}{ext}"
        if mfr is not None:
            name = mfr.force_write_ext(name)
        # a Stern Spike 2 build for a bigger SD card is named for that card
        # ("...Release.16G.sdcard-modified.raw"), not the original's
        grown = self._card_build()[0]
        if grown:
            name = _name_for_class(name, grown)
        return name

    def _target_write_path(self):
        """Absolute path Write will build to, or "" (Direct / not set)."""
        if self.write_input_source_var.get() == "ssd":
            return ""
        out = self.write_output_var.get().strip()
        name = self.write_filename_var.get().strip()
        if not out or not name:
            return ""
        mfr = self.mfr
        if mfr is not None:
            name = mfr.force_write_ext(name)
        spec_ext = ""
        if mfr is not None and mfr.input_spec.extensions:
            spec_ext = mfr.input_spec.extensions[0].lower()
        if spec_ext and out.lower().endswith(spec_ext):
            return os.path.abspath(out)
        return os.path.abspath(os.path.join(out, name))

    def _maybe_default_write_filename(self):
        default = self._default_write_filename()
        if not default:
            return
        current = self.write_filename_var.get().strip()
        if not current or current == self._write_filename_auto:
            self._write_filename_auto = default
            if default != current:
                self.write_filename_var.set(default)

    def _update_write_filename(self):
        if self.write_input_source_var.get() == "ssd":
            self.set(filename_hint="", filename_hint_kind="")
            self._refresh_build_path_display()
            return
        self._maybe_default_write_filename()
        self._refresh_build_path_display()
        self._update_write_filename_hint()

    def _on_filename(self):
        self._refresh_build_path_display()
        self._update_write_filename_hint()

    def _refresh_build_path_display(self):
        try:
            target = self._target_write_path()
        except Exception:                               # noqa: BLE001
            target = ""
        if not target:
            out = (self.write_output_var.get() or "").strip()
            name = (self.write_filename_var.get() or "").strip()
            target = os.path.join(out, name) if out and name else out
        self.set(build_path=target)

    def _update_write_filename_hint(self):
        target = self._target_write_path()
        if not target:
            self.set(filename_hint="", filename_hint_kind="")
            return
        original = self.write_upd_var.get().strip()
        if original and os.path.abspath(original) == target:
            self.set(filename_hint=(
                "⚠ This name matches the original — rename the build or "
                "the folder so it isn't overwritten."),
                filename_hint_kind="err")
        elif os.path.exists(target):
            self.set(filename_hint=(
                f"{os.path.basename(target)} already exists here — "
                "Build will ask before overwriting."),
                filename_hint_kind="muted")
        else:
            typed = self.write_filename_var.get().strip()
            final = os.path.basename(target)
            if typed and final != typed:
                self.set(filename_hint=f"Will build: {final}",
                         filename_hint_kind="muted")
            else:
                self.set(filename_hint="", filename_hint_kind="")

    @rpc
    def change_build_location(self):
        """Build Image "Change…": one Save-As picker for folder + name."""
        mfr = self.mfr
        ext = ""
        if mfr is not None:
            try:
                ext = mfr.write_output_ext() or ""
            except Exception:                           # noqa: BLE001
                ext = ""
        initial = ((self.write_filename_var.get() or "").strip()
                   or self._default_write_filename())
        path = compat.filedialog.asksaveasfilename(
            title="Build image as",
            initialdir=self.window._initialdir_for(
                self.write_output_var.get(), self.write_assets_var.get()),
            initialfile=initial, defaultextension=(ext or ""),
            filetypes=(([("Card image", "*" + ext)] if ext else [])
                       + [("All files", "*.*")]),
            confirmoverwrite=False)
        if not path:
            return None
        path = os.path.normpath(path)
        folder_part, name_part = os.path.split(path)
        if mfr is not None:
            name_part = mfr.force_write_ext(name_part)
        self.write_output_var.set(folder_part)
        self.write_filename_var.set(name_part)
        self._write_output_auto = ""
        folder = (self.write_assets_var.get() or "").strip()
        from ...core import project_file
        if folder and project_file.has_anchor(folder):
            default = os.path.normpath(os.path.join(folder, "build"))
            override = "" if folder_part == default else folder_part
            if project_file.update_anchor(folder, build_dir=override):
                self.log("Project build location %s" % (
                    "reset to the default build\\ folder" if not override
                    else "set to %s" % folder_part), "info")
        self._update_write_filename_hint()
        return path

    # ------------------------------------------------------------------
    # BOF update-version date
    # ------------------------------------------------------------------
    def _on_version_auto_toggle(self):
        seed = (not self.write_version_auto_var.get()
                and not (self.write_version_date_var.get() or "").strip())
        self._refresh_write_version_field(force_value=seed)

    def _refresh_write_version_field(self, force_value=False):
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "write_version_date",
                                      False):
            return
        from ...plugins.bof.pipeline import peek_next_update_version
        path = (self.write_assets_var.get() or "").strip()
        baseline, next_str = (None, None)
        if path and os.path.isdir(path):
            try:
                baseline, next_str = peek_next_update_version(path)
            except Exception:                           # noqa: BLE001
                baseline, next_str = (None, None)
        self._write_version_baseline = baseline
        auto = self.write_version_auto_var.get()
        if auto or force_value:
            self.write_version_date_var.set(next_str or "")
        if next_str is None:
            hint = ("(select your extracted assets folder — the date is "
                    "read from it)")
        elif auto:
            hint = ("auto: one day past installed code (%s)"
                    % baseline.strftime('%Y.%m.%d'))
        else:
            hint = ("installed code is %s — enter a newer date to install"
                    % baseline.strftime('%Y.%m.%d'))
        self.set(version_hint=hint)

    def _publish_version(self):
        return None                      # the var mirrors itself

    def write_version_override(self):
        if self.write_version_auto_var.get():
            return None
        return (self.write_version_date_var.get() or "").strip() or None

    def write_version_validation_error(self):
        if self.write_version_auto_var.get():
            return None
        from ...plugins.bof.pipeline import parse_update_date
        raw = (self.write_version_date_var.get() or "").strip()
        if not raw:
            return ("Enter an update version date as YYYY.MM.DD, or re-check "
                    "Auto to let the app pick one.")
        d = parse_update_date(raw)
        if d is None:
            return (f"'{raw}' isn't a valid date. Use the format "
                    f"YYYY.MM.DD (e.g. 2026.01.15).")
        base = self._write_version_baseline
        if base is not None and d <= base:
            return (f"{raw} isn't newer than the installed code "
                    f"({base.strftime('%Y.%m.%d')}). The game only installs "
                    f"a newer date — pick something after it.")
        return None

    # ------------------------------------------------------------------
    # grow for longer text (Stern)
    # ------------------------------------------------------------------
    def text_grow_enabled(self):
        try:
            return bool(self.write_text_grow_var.get())
        except Exception:                               # noqa: BLE001
            return True

    def _on_text_grow_toggle(self):
        on = self.text_grow_enabled()
        fn = self.window.cb.get("on_text_grow_change")
        if fn is not None:
            try:
                fn(on)
            except Exception:                           # noqa: BLE001
                log.exception("text grow change")
        self._refresh_pending_text_rows()

    def _refresh_pending_text_rows(self):
        """Re-list the strings.tsv rows in place (their status names the
        path a longer edit takes) without the MD5 rescan."""
        keep = [r for r in self._rows
                if not (r[1] == "text" and r[2] in write_scan.TEXT_STATUSES)]
        assets = (self.write_assets_var.get() or "").strip()
        mfr = self.mfr
        if assets and mfr is not None and getattr(
                mfr.capabilities, "replace_text", False):
            keep.extend(write_scan.text_rows(assets,
                                             self.text_grow_enabled()))
        self._rows = keep
        self._publish_rows()

    # ------------------------------------------------------------------
    # SD card size (Stern Spike 2, plugins/stern/card_size.py)
    # ------------------------------------------------------------------
    def card_size_choice(self):
        """The SD card size the next build is asked for: "16G" / "32G", or
        "" for the original's own size (what PAD_STERN_CARD_SIZE mirrors)."""
        try:
            return _norm_card_size(self.write_card_size_var.get())
        except Exception:                               # noqa: BLE001
            return ""

    def _on_card_size_change(self):
        choice = self.card_size_choice()
        if self.write_card_size_var.get() != choice:
            self.write_card_size_var.set(choice)        # traces back here
            return
        fn = self.window.cb.get("on_card_size_change")
        if fn is not None:
            try:
                fn(choice)
            except Exception:                           # noqa: BLE001
                log.exception("card size change")
        self._publish_card_size()

    def _card_size_applies(self):
        """A Stern Spike 2 build on a computer that can grow one: the only
        build card_size.py grows (not on macOS: see card_size_supported)."""
        mfr = self.mfr
        return bool(mfr is not None and mfr.key == "stern"
                    and getattr(mfr, "current_era", "spike2") == "spike2"
                    and self.cap("write") and card_size_supported())

    def card_size_problem(self):
        """Why the next image build can't be made at the SD card size asked
        for: the sentence the control shows in red, or "" (it can, or the
        original's own size is asked for).  The Build / flash dialog asks
        this first when its Start builds (``_build_refusal``), and
        app._start_write before its prompts, so a size the original can't
        take is refused in a second, before any other question, rather than
        after every assigned video has been re-encoded.  It reads the
        original's tables itself (a few sectors; the multi-boot answer is
        cached by the probe) rather than trust a probe that may still be
        running.  Whether this computer can grow a card is the answer a
        worker already has (``_grow_here_problem``); while there is none, the
        build's own check (Manufacturer.write_preflight) still refuses."""
        choice = self.card_size_choice()
        if (not choice or not self._card_size_applies()
                or self._is_direct()):
            return ""
        path = (self.write_upd_var.get() or "").strip()
        if not path:
            return ""
        from ...plugins.stern import card_size as cs
        from ...plugins.stern.pipeline import card_class_words
        try:
            grows_to = cs.target_for(path, choice)
        except cs.CardSizeError as e:
            return card_class_words(str(e))
        except OSError:
            return ""                   # the build's own checks say why
        return self._grow_here_problem(grows_to) if grows_to else ""

    def _grow_here_problem(self, cls):
        """The sentence refusing a build grown to *cls* on this computer
        (card_size.preflight's own words), or "" when it can grow one or
        that isn't known yet.  An answer that is missing, or a no a minute
        old, is asked for again here, off the UI loop, and the control is
        re-published when it comes in."""
        self._ask_grow_here()
        why = _grow_here()
        if not why:
            return ""
        from ...plugins.stern import card_size as cs
        from ...plugins.stern.pipeline import card_class_words
        return card_class_words(
            "This card can't be built for a %s SD card on this computer: "
            "%s." % (cs.words(cls), why.rstrip(".")))

    def _ask_grow_here(self):
        loop = self.ctx.loop

        def _then():
            try:
                loop.post(self._publish_card_size)
            except Exception:                           # noqa: BLE001
                pass                    # the window has gone
        return _ask_grow_here(_then)

    def _build_refusal(self):
        """The Build / flash dialog's first check when its Start builds:
        ``(title, message)`` when the SD card size asked for can't be built
        from this original or on this computer, else None.  Asked before the
        dialog's own questions, so a build that is going to be refused never
        follows an "Erase the SD card" confirmation, and the dialog stays
        open (Flash on its own still works)."""
        problem = self.card_size_problem()
        if not problem:
            return None
        return CARD_SIZE_LABEL, "%s\n\n%s" % (problem, CARD_SIZE_WAY_BACK)

    def _refresh_card_size(self):
        """Re-read what the original is (its partition tables, off the
        loop) and re-publish the control."""
        self._card_seq += 1
        seq = self._card_seq
        path = (self.write_upd_var.get() or "").strip()
        if not path or not self._card_size_applies():
            self._card_probe, self._card_probe_path = None, ""
            self._publish_card_size()
            return

        def _worker():
            try:
                probe = _probe_card_size(path)
            except Exception:                           # noqa: BLE001
                log.exception("card size probe")
                probe = None
            self.ctx.loop.post(self._apply_card_probe, seq, path, probe)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_card_probe(self, seq, path, probe):
        if (seq != self._card_seq
                or (self.write_upd_var.get() or "").strip() != path):
            return
        self._card_probe, self._card_probe_path = probe, path
        self._publish_card_size()

    def _current_card_probe(self):
        """The probe of the original picked NOW, or None (another
        manufacturer or era, macOS, or a probe of a file no longer picked
        whose successor is still being read)."""
        if not self._card_size_applies():
            return None
        path = (self.write_upd_var.get() or "").strip()
        if not path or path != self._card_probe_path:
            return None
        return self._card_probe

    def _card_build(self):
        """``(class, size, error)`` of the next image build as the SD card
        size control knows it: the class it grows to (None: it keeps the
        original's), the size of the file it makes (None: unknown - not a
        Stern Spike 2 original this tab has read), and the sentence refusing
        the size asked for ("" when it can be built)."""
        probe = self._current_card_probe()
        if probe is None:
            return None, None, ""
        choice = self.card_size_choice()
        builds_at, err, out = ((probe.get("why") or {}).get(
            choice, (None, "", None)) if choice else (None, "", None))
        if err:
            return None, None, err
        if builds_at and out:
            return builds_at, out, ""
        if not probe.get("own"):
            # not laid out the way the control reads: no build of it was
            # ever grown, so the file at the build path still tells
            return None, None, ""
        # the original's own size: a Spike 2 build is a copy of the original
        # patched in place, to the byte its length
        return None, probe.get("size"), ""

    def _publish_card_size(self):
        """The control's state: shown (``card_size_cap``) when the original
        is a Spike 2 card laid out the way Stern lays one out and a bigger
        card class it can be built at exists for it, or when the size asked
        for can't be built from this original (so the reason, and the way
        back to the original's size, are on screen before a build is
        refused).  The note says what the original is, how much room its
        games partition has at each size (the probe read it off the loop:
        :func:`_probe_room`), and what the size asked for costs.  The Build
        Image line's default name follows the class."""
        from ...plugins.stern.card_size import CARD_SIZES
        from ...plugins.stern.pipeline import card_class_words
        from ..write_dialogs import _fmt_size
        probe = self._current_card_probe()
        choice = self.card_size_choice()
        own = probe.get("own") if probe else None
        why = (probe.get("why") or {}) if probe else {}
        none = (None, "", None)
        # only the sizes this original CAN be built at: a multi-boot store
        # card is laid out like a stock one, and target_for refuses it
        offered = [c for c in CARD_SIZE_CHOICES
                   if own and CARD_SIZES[c] > CARD_SIZES[own]
                   and not why.get(c, none)[1]]
        builds_at, err, out = why.get(choice, none) if choice else none
        if probe is not None and builds_at and not err:
            # the original can grow to it: can THIS computer grow a card?
            # (asked off the loop; this runs again when the answer is in)
            err = self._grow_here_problem(builds_at)
        if probe is None or (not offered and not err):
            # not a Stern-shaped card, one of the biggest class already, or
            # one that can't grow at all: nothing to choose
            self.set(card_size_cap=False, card_size_options=[],
                     card_size_shown="", card_size_note="",
                     card_size_note_kind="")
            self._update_write_filename()
            return
        options = [{"value": "", "label": CARD_SIZE_SAME}]
        options += [{"value": c, "label": "%s card" % _class_words(c)}
                    for c in offered]
        shown = choice if choice in offered else ""
        if err:
            # the size asked for, which this original (or this computer)
            # can't build: kept in the list so the control shows what a build
            # would be refused
            if choice not in offered:
                options.append({"value": choice,
                                "label": "%s card" % _class_words(choice)})
            shown = choice
            note, kind = card_class_words(err), "err"
        else:
            size = int(probe.get("size") or 0)
            note = ("The original is %s %s card"
                    % ("an" if own == "8G" else "a", _class_words(own)))
            if size > CARD_SIZES[own]:
                note += " in a %s file" % _fmt_size(size)
            note += "." + _room_words(probe.get("room") or {}, own, offered)
            if builds_at:
                out = out or CARD_SIZES[builds_at]
                if out > CARD_SIZES[builds_at]:
                    # card_size.plan keeps a longer original's length
                    note += (" The built image is %s, as long as the original "
                             "file, so it needs an SD card that holds at "
                             "least %s; flashing it takes longer."
                             % (_fmt_size(out), _fmt_size(out)))
                else:
                    note += (" The built image is %s and needs an SD card of "
                             "at least %s; flashing it takes longer."
                             % (_fmt_size(out), _class_words(builds_at)))
            kind = ""
        self.set(card_size_cap=True,
                 card_size_options=options, card_size_shown=shown,
                 card_size_note=note, card_size_note_kind=kind)
        self._update_write_filename()

    # ------------------------------------------------------------------
    # Modified Files: the scan
    # ------------------------------------------------------------------
    def _log_scan(self, text):
        self.log(text, "info")

    def _begin_scan_ui(self):
        if self._scan_t0 is not None:
            self._log_scan("Write change scan replaced after %.1f s by a "
                           "newer scan." % (time.monotonic() - self._scan_t0))
        self._scan_t0 = time.monotonic()
        why = self._scan_reason
        self._scan_reason = None
        self._log_scan("Write change scan started%s."
                       % (" (%s)" % why if why else ""))
        self._rows = []
        self._scanning = True
        self.set(scanning=True, scan_msg="Scanning for modified files…",
                 empty="Scanning for modified files…")
        self._publish_rows()

    def _end_scan_ui(self):
        if self._scan_t0 is not None:
            self._log_scan("Write change scan finished in %.1f s."
                           % (time.monotonic() - self._scan_t0))
        self._scan_t0 = None
        self._scanning = False
        self.set(scanning=False, scan_msg="")
        self._sync_buttons()

    def _scan_write_preview(self):
        """Populate the Modified Files list (MD5 walk on a worker)."""
        if self.window._running:
            self._rescan_after_run = True
            return
        assets_path = (self.write_assets_var.get() or "").strip()
        self._scan_id += 1
        scan_id = self._scan_id
        self._begin_scan_ui()
        self._sync_buttons()
        mfr = self.mfr
        hide_imported_cache = mfr is not None and mfr.key == "bof"

        def _post(fn, *args):
            self.ctx.loop.post(fn, *args)

        def _scan():
            if not assets_path or not os.path.isdir(assets_path):
                _post(self._bail, scan_id, assets_path, EMPTY_NO_FOLDER)
                return
            checksums_file = os.path.join(assets_path, ".checksums.md5")
            if not os.path.isfile(checksums_file):
                _post(self._bail, scan_id, assets_path,
                      "Pick a folder produced by Extract first "
                      "(no .checksums.md5 found).")
                return
            try:
                saved = write_scan.read_baseline(checksums_file)
            except OSError:
                _post(self._finish_scan, 0, scan_id, assets_path)
                return
            try:
                changed = write_scan.walk_changes(
                    assets_path, saved,
                    hide_imported_cache=hide_imported_cache,
                    current=lambda: self._scan_id == scan_id,
                    on_found=lambda n: _post(self._scan_progress, n,
                                             scan_id))
            except Exception:                           # noqa: BLE001
                log.exception("write scan")
                changed = 0
            if changed is None:
                return                                  # superseded
            if self._scan_id == scan_id:
                _post(self._finish_scan, changed, scan_id, assets_path)

        threading.Thread(target=_scan, daemon=True).start()

    def _pending(self, assets_path):
        try:
            return write_scan.pending_rows(
                self.window, self.mfr, assets_path,
                grow_on=self.text_grow_enabled(), direct=self._is_direct())
        except Exception:                               # noqa: BLE001
            log.exception("write pending rows")
            return []

    def _bail(self, scan_id, assets_path, msg):
        if scan_id != self._scan_id:
            return
        self._rows = list(self._pending(assets_path)) if assets_path else []
        self._end_scan_ui()
        self.set(empty=msg)
        self._publish_rows()
        self._refresh_prebuild_notes()

    def _scan_progress(self, n, scan_id):
        if scan_id != self._scan_id or not self._scanning:
            return
        self.set(scan_msg="Scanning for modified files…   %d found" % n)

    def _finish_scan(self, changed, scan_id, assets_path=None):
        if scan_id != self._scan_id:
            return
        if isinstance(changed, int):
            n_changed, changed = changed, []
        else:
            n_changed = len(changed)
        rows = []
        if assets_path is not None:
            rows.extend(self._pending(assets_path))
        rows.extend((rel, ext, "Modified", "modified")
                    for rel, ext in changed)
        self._rows = rows
        self._end_scan_ui()
        self.log("Write change scan: %d modified on disk, %d total "
                 "change(s) for the next build." % (n_changed, len(rows)),
                 "info")
        self._scan_fp = self._fingerprint()
        self.set(empty="No modified files detected.")
        self._publish_rows()
        self._refresh_prebuild_notes()

    def _fingerprint(self):
        assets_path = (self.write_assets_var.get() or "").strip()
        try:
            return write_scan.fingerprint(self.window, assets_path,
                                          self._disk_epoch,
                                          self.text_grow_enabled())
        except Exception:                               # noqa: BLE001
            return None

    def _maybe_rescan_write_preview(self):
        mfr = self.mfr
        if mfr is None or not mfr.capabilities.write:
            return
        if self.window.current_tab_key() != "Write":
            return
        fp = self._fingerprint()
        if self._scan_fp is not None and fp == self._scan_fp:
            return
        if self._scan_reason is None:
            self._scan_reason = "staged changes differ from the last scan"
        self._scan_write_preview()

    def _cancel_scan(self, text=None):
        self._scan_id += 1
        if self._scan_t0 is not None:
            self._log_scan("Write change scan cancelled after %.1f s."
                           % (time.monotonic() - self._scan_t0))
        self._scan_t0 = None
        self._scanning = False
        self._rows = []
        self.set(scanning=False, scan_msg="",
                 empty=text or "Scan cancelled — click Refresh to try "
                               "again.")
        self._publish_rows()

    def begin_revert_view(self):
        """Blank the list the moment a revert starts."""
        if self._scanning:
            self._cancel_scan()
        else:
            self._scan_id += 1
            self._rows = []
        self.set(empty="Reverting…")
        self._publish_rows()

    def refresh_after_revert(self):
        mfr = self.mfr
        if mfr is None or not mfr.capabilities.write:
            return
        self._scan_reason = "after Revert all changes"
        self._scan_write_preview()

    def invalidate_asset_scans(self, rescan_visible=True):
        if rescan_visible:
            self._maybe_rescan_write_preview()

    def reload_assets_tabs(self):
        self._maybe_rescan_write_preview()

    def _has_pending_write_changes(self):
        if self._scanning:
            return True
        return bool(self._rows)

    # ------------------------------------------------------------------
    # Modified Files: the list
    # ------------------------------------------------------------------
    def _sorted_rows(self):
        col, desc = self._sort
        rows = list(self._rows)
        if col is not None:
            idx = SORT_IDX.get(col, 0)
            rows.sort(key=lambda r: (str(r[idx]).lower(), r[0].lower()),
                      reverse=desc)
        return rows

    def _publish_rows(self):
        rows = [{"file": r[0], "type": r[1], "status": r[2], "tag": r[3]}
                for r in self._sorted_rows()]
        col, desc = self._sort
        self.set(rows=rows, count=len(rows),
                 sort={"key": col, "desc": desc} if col else None)
        self._sync_buttons()
        self.window.set_tab_badge(self.ns, len(rows) or None)

    @rpc
    def sort(self, col):
        """Header click: ascending → descending → the scan's own order."""
        if col not in SORT_IDX:
            return False
        cur, desc = self._sort
        if cur != col:
            self._sort = (col, False)
        elif not desc:
            self._sort = (col, True)
        else:
            self._sort = (None, False)
        self._publish_rows()
        return True

    @rpc
    def refresh(self):
        """Refresh / Cancel scan."""
        if self._scanning:
            self._cancel_scan()
            self._sync_buttons()
            return "cancelled"
        if self.window._running:
            return False
        self._scan_reason = "Refresh clicked"
        self._scan_write_preview()
        return True

    @rpc
    def export_csv(self):
        rows = self._sorted_rows()
        if not rows:
            compat.messagebox.showinfo(
                "Export CSV",
                "Nothing to export yet — scan the Write tab first.")
            return False
        path = self.window.ask_save(
            "write_csv", "Save the modified-files list as CSV",
            initialfile="modified_files.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            defaultextension=".csv")
        if not path:
            return False
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["File", "Type", "Status"])
                for rel, ext, status, _tag in rows:
                    w.writerow([rel, ext, status])
        except OSError as e:
            compat.messagebox.showerror("Export CSV",
                                        "Couldn't write the CSV:\n%s" % e)
            return False
        self.log("Modified files exported: %d row(s) → %s"
                 % (len(rows), os.path.normpath(path)), "success")
        return True

    @rpc
    def revert_all(self):
        fn = self.window.cb.get("on_revert_all")
        if fn is None or self.window._running:
            return False
        fn((self.write_assets_var.get() or "").strip())
        return True

    # ------------------------------------------------------------------
    # the primary button (Build / Apply, or Build / flash) and its Cancel
    # ------------------------------------------------------------------
    def _current_write_button_label(self):
        mfr = self.mfr
        if mfr is None:
            return "Build update"
        if self.write_input_source_var.get() == "ssd":
            return getattr(mfr, "write_direct_button", "Apply Modifications")
        return getattr(mfr, "write_build_button", "Build update")

    def _block_write(self):
        mfr = self.mfr
        return bool(sys.platform == "win32" and mfr is not None
                    and getattr(mfr.capabilities, "direct_ssd", False)
                    and not _is_admin()
                    and self.write_input_source_var.get() == "ssd")

    def _sync_buttons(self):
        mfr = self.mfr
        running = bool(self.window._running)
        active = running and self._run_mode == "write"
        flash = bool(mfr is not None
                     and getattr(mfr.capabilities, "flash_image", False))
        if flash:
            label = (getattr(mfr, "flash_button_text", None)
                     or FLASH_BTN_TEXT)
            cancel = self._flash_running or active
            disabled = running and not cancel
        else:
            label = self._current_write_button_label()
            cancel = active
            disabled = (running and not cancel) or (
                not running and self._block_write())
        revert = bool(self.get("revert_cap") and self._rows and not running)
        self.set(primary_label=label, cancel=bool(cancel),
                 primary_disabled=bool(disabled), running=running,
                 revert_enabled=revert,
                 refresh_disabled=bool(running and not self._scanning))

    def on_running(self, running, mode):
        self._run_mode = mode if running else None
        if running:
            if self._scanning:
                self._cancel_scan("Scan paused — it re-runs when this "
                                  "operation finishes.")
                self._rescan_after_run = True
        else:
            self._disk_epoch += 1
            self._flash_running = False
            if self._rescan_after_run:
                self._rescan_after_run = False
                self._scan_reason = "the run just finished"
                self._sync_buttons()
                self._maybe_rescan_write_preview()
        self._sync_buttons()

    def set_flash_running(self, running):
        self._flash_running = bool(running)
        self._sync_buttons()

    @rpc
    def primary(self):
        """The one button: Cancel while this side runs, else Build / Apply
        (plain plugins) or the Build / flash dialog (flash_image plugins)."""
        mfr = self.mfr
        if mfr is None:
            return False
        running = bool(self.window._running)
        if self.get("cancel"):
            fn = self.window.cb.get("on_write_cancel")
            if fn is not None and running:
                fn()
                return "cancel"
            return False
        if getattr(mfr.capabilities, "flash_image", False):
            return self._open_flash_dialog()
        if running or self._block_write():
            return False
        return self._on_write_clicked()

    def _on_write_clicked(self):
        if (not self.window._running
                and not self._has_pending_write_changes()):
            if not compat.messagebox.askyesno(
                    "Nothing modified",
                    "No modified files were detected, so this will build a "
                    "copy of the original image with no changes.\n\nBuild "
                    "anyway?", icon="warning"):
                return False
        fn = self.window.cb.get("on_write")
        if fn is not None:
            fn()
        return True

    # ------------------------------------------------------------------
    # the Build / flash dialog
    # ------------------------------------------------------------------
    def _open_flash_dialog(self, initial_image=None, fresh=False,
                           image_titles=None):
        on_flash = self.window.cb.get("on_flash_image")
        if on_flash is None:
            return False
        if self.window._running:
            compat.messagebox.showinfo(
                "Busy",
                "Finish or cancel the current operation before flashing a "
                "card.")
            return False
        target = self._target_write_path()
        missing = []
        if not self.write_upd_var.get().strip():
            missing.append("the original image")
        if not self.write_assets_var.get().strip():
            missing.append("the assets folder")
        if not target:
            missing.append("the build location")
        reason = ("Set %s on the Write tab first." % " and ".join(missing)
                  if missing else "")
        mfr = self.mfr
        caps = getattr(mfr, "capabilities", None)
        can_build = (not missing and bool(caps is not None
                                          and getattr(caps, "write", False)))
        initial = target if (target and os.path.isfile(target)) else None
        mfr_key = getattr(mfr, "key", "")
        choices = self._saved_flash_choices.get(mfr_key)
        handed_in = ""
        if initial_image and os.path.isfile(initial_image):
            initial = initial_image
            handed_in = "Multi-boot"
        if self._flash is not None:
            self._flash.close()
        # Tk opened the dialog over whatever tab was showing.  Once the shell
        # draws it over every tab (write_dialogs.js WriteOverlays, which
        # reports itself through flash_host_ready) nothing switches.  Until
        # then the dialog is drawn by this tab's page, so a caller on another
        # tab (the Multi-boot tab's "flash this card") gets this tab under
        # the dialog and its own tab back when it closes.
        cur = self.store.get("shell", "tab")
        self._return_tab = None
        if cur and cur != self.ns and not self._flash_hosted:
            self._return_tab = cur
            try:
                self.window.select_tab(self.ns)
            except Exception:                           # noqa: BLE001
                self._return_tab = None
        # the size of the image a build makes, when this tab knows it: the
        # SD card size chosen here changes it, so the file a LAST build left
        # at the build path says nothing about the next one
        grown, build_size, _err = self._card_build()
        # "pick a smaller size" only when one builds a smaller image: an
        # original FILE longer than its card class (a dump of a whole bigger
        # SD card) builds at the file's length whatever size is picked
        probe = self._current_card_probe() or {}
        smaller = bool(grown and build_size
                       and build_size > int(probe.get("size") or 0))
        if grown:
            # a stale answer to "can this computer grow a card?" is renewed
            # while the SD card is being picked, before the dialog's Start
            self._ask_grow_here()
        self._flash = FlashDialog(
            self.ctx.loop, mfr, on_flash,
            initial_image=initial,
            on_build_flash=self.window.cb.get("on_build_flash"),
            build_target=target, can_build=can_build,
            cannot_build_reason=reason,
            build_size=build_size,
            build_size_hint=(
                "or pick a smaller SD card size on the Write tab" if smaller
                else ""),
            build_refusal=self._build_refusal,
            has_pending_changes=self._has_pending_write_changes(),
            initial_choices=choices,
            on_choices=lambda c, k=mfr_key: self._remember_flash_choices(
                k, c),
            handed_in=handed_in, fresh_image=bool(handed_in and fresh),
            flashed_fn=self._image_was_flashed, image_titles=image_titles,
            publish=self._publish_flash,
            ask_open=self.window.ask_open, ask_save=self._ask_save)
        self._flash.publish()
        return True

    def _publish_flash(self, d):
        self.set(flash_dlg=d)
        if d is None and self._return_tab:
            back, self._return_tab = self._return_tab, None
            try:
                self.window.select_tab(back)
            except Exception:                           # noqa: BLE001
                pass

    open_flash_dialog = _open_flash_dialog

    @rpc
    def flash_host_ready(self):
        """The shell draws the Build / flash dialog over every tab."""
        self._flash_hosted = True
        self.set(flash_hosted=True)
        return True

    def _ask_save(self, key, title, initialfile="", filetypes=None,
                  defaultextension="", initialdir=""):
        path = compat.filedialog.asksaveasfilename(
            title=title,
            initialdir=initialdir or self.window.last_browse_dir(key),
            initialfile=initialfile, filetypes=filetypes or [],
            defaultextension=defaultextension)
        if path:
            self.window.remember_browse_dir(key, path)
        return path

    def _remember_flash_choices(self, mfr_key, choices):
        if not mfr_key or not choices:
            return
        current = dict(self._saved_flash_choices.get(mfr_key) or {})
        current.update(choices)
        if current == self._saved_flash_choices.get(mfr_key):
            return
        self._saved_flash_choices[mfr_key] = current
        fn = self.window.cb.get("on_flash_choices_change")
        if fn is not None:
            try:
                fn(dict(self._saved_flash_choices))
            except Exception:                           # noqa: BLE001
                pass

    def _remember_flashed_image(self, image_path, digest=None):
        if digest is None:
            from ...core.rawdevice import menu_identity_digest
            try:
                digest = menu_identity_digest(image_path)
            except Exception:                           # noqa: BLE001
                return
        kept = [digest] + [d for d in self._flashed_images if d != digest]
        kept = kept[:FLASHED_IMAGES_KEPT]
        if kept == self._flashed_images:
            return
        self._flashed_images = kept
        fn = self.window.cb.get("on_flashed_images_change")
        if fn is not None:
            try:
                fn(list(kept))
            except Exception:                           # noqa: BLE001
                pass

    def _image_was_flashed(self, image_path):
        from ...core.rawdevice import menu_identity_digest
        try:
            return menu_identity_digest(image_path) in self._flashed_images
        except Exception:                               # noqa: BLE001
            return False

    @rpc
    def flash_set(self, key, value):
        if self._flash is None:
            return False
        self._flash.set(key, value)
        return True

    @rpc
    def flash_browse(self, which):
        if self._flash is None:
            return None
        return self._flash.browse(which)

    @rpc
    def flash_refresh_drives(self):
        if self._flash is None:
            return False
        self._flash.refresh_drives()
        return True

    @rpc
    def flash_start(self):
        dlg = self._flash
        if dlg is None:
            return False
        done = dlg.start()
        if done and self._flash is dlg:
            self._flash = None
        return done

    @rpc
    def flash_close(self):
        if self._flash is not None:
            self._flash.close()
            self._flash = None
        return True

    # ------------------------------------------------------------------
    # Card diagnostics (CGC)
    # ------------------------------------------------------------------
    @rpc
    def diag_open(self):
        mfr = self.mfr
        if self.window._running:
            compat.messagebox.showinfo(
                "Busy",
                "Finish or cancel the current operation before reading a "
                "card.")
            return False
        if getattr(mfr, "diagnose_card", None) is None:
            return False
        if self._diag is not None:
            self._diag.close()
        self._diag = DiagnoseDialog(
            self.ctx.loop, mfr, publish=lambda d: self.set(diag=d),
            ask_open=self.window.ask_open, ask_save=self._ask_save)
        return True

    @rpc
    def diag_refresh(self):
        if self._diag is not None:
            self._diag.refresh_drives()
        return True

    @rpc
    def diag_select(self, index):
        if self._diag is not None:
            self._diag.select(index)
        return True

    @rpc
    def diag_read(self):
        return self._diag.read_card() if self._diag is not None else False

    @rpc
    def diag_read_file(self):
        return self._diag.read_file() if self._diag is not None else False

    @rpc
    def diag_save(self):
        return self._diag.save() if self._diag is not None else False

    @rpc
    def diag_close(self):
        if self._diag is not None:
            self._diag.close()
            self._diag = None
        return True

    # ------------------------------------------------------------------
    # Image Info (the ⓘ badge beside the Original)
    # ------------------------------------------------------------------
    def _info_assets_dir(self):
        ext = self._export_var("extract_output_var")
        assets = ((self.write_assets_var.get() or "").strip()
                  or ((ext.get() if ext is not None else "") or "").strip())
        return assets if assets and os.path.isdir(assets) else None

    @rpc
    def image_info(self):
        return self._info.show(self.write_upd_var.get(), self.mfr,
                               self._info_assets_dir())

    @rpc
    def image_info_refresh(self):
        self._info.refresh(self.mfr, self._info_assets_dir(), force=True)
        return True

    @rpc
    def image_info_copy(self):
        text = self._info.report_text()
        if text:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(text)
        return text

    @rpc
    def image_info_close(self):
        self._info.close()
        return True

    # ------------------------------------------------------------------
    # the rest of the page's calls
    # ------------------------------------------------------------------
    @rpc
    def set_source(self, source):
        """The destination toggle ("iso" = build an image file, "ssd" =
        write straight onto the card)."""
        if source not in ("iso", "ssd") or self.window._running:
            return False
        self.write_input_source_var.set(source)
        return True

    @rpc
    def refresh_drives(self):
        self._refresh_drives()
        return True

    @rpc
    def open_project(self):
        path = (self.write_assets_var.get() or "").strip()
        if not path:
            compat.messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return False
        if not os.path.exists(path):
            compat.messagebox.showinfo(
                "Open folder", "This folder doesn't exist yet:\n%s" % path)
            return False
        from ...core import desktop
        ok, err = desktop.open_path(os.path.abspath(path))
        if not ok:
            self.log("Couldn't open %s: %s" % (path, err), "warning")
        return bool(ok)

    @rpc
    def switch_suggested(self):
        """The detect badge's "click to switch"."""
        suggested = self._suggested_mfr
        if suggested is None or self.window._running:
            return False
        path = self.write_upd_var.get()
        fn = self.window.cb.get("on_manufacturer_change")
        if fn is not None:
            fn(suggested)
        self.write_upd_var.set(path)
        return True

    @rpc
    def apply_delta(self):
        fn = self.window.cb.get("on_apply_delta")
        if fn is None or self.window._running:
            return False
        fn()
        return True

    @rpc
    def dismiss_fda(self):
        self._fda_ack = True
        fn = self.window.cb.get("on_fda_acknowledge")
        if fn is not None:
            try:
                fn(True)
            except Exception:                           # noqa: BLE001
                pass
        # the window hands the acknowledgement to every tab showing the panel
        # (Extract's and this one's), as Tk hid both frames at once
        try:
            self.window.acknowledge_macos_fda()
        except Exception:                               # noqa: BLE001
            log.exception("acknowledge FDA")
        self.set(fda_ack=True)
        self._layout_for_source()
        return True

    def acknowledge_macos_fda(self):
        self._fda_ack = True
        self.set(fda_ack=True)
        self._layout_for_source()

    # -- the ADMINISTRATOR panel's collapsed flag ---------------------------
    # ONE flag for every admin panel (Tk: self._admin_warning_collapsed,
    # re-applied to each frame in self._admin_warning_frames).  The Extract
    # tab holds it and persists it; this tab shows it and flips it there.
    def _shared_admin_collapsed(self):
        # Tk's window attribute (a property on the Extract service)
        try:
            val = self._export_fn("_admin_warning_collapsed")
            if callable(val):
                val = val()
        except Exception:                               # noqa: BLE001
            log.exception("admin panel flag")
            val = None
        return self._admin_collapsed if val is None else bool(val)

    def set_admin_warning_collapsed(self, collapsed):
        """Show the shared flag (also the hook a window-level fan-out of the
        flag calls)."""
        self._admin_collapsed = bool(collapsed)
        self.set(admin_collapsed=self._admin_collapsed)

    @rpc
    def toggle_admin_warning(self):
        collapsed = not self._shared_admin_collapsed()
        toggle = self._export_fn("_toggle_admin_warning")
        if toggle is not None:
            # flips the one flag, shows it on the Extract tab, persists it
            try:
                toggle()
                collapsed = self._shared_admin_collapsed()
            except Exception:                           # noqa: BLE001
                log.exception("toggle admin panel")
                toggle = None
        if toggle is None:
            fn = self.window.cb.get("on_admin_warning_collapsed_change")
            if fn is not None:
                try:
                    fn(collapsed)
                except Exception:                       # noqa: BLE001
                    pass
        self.set_admin_warning_collapsed(collapsed)
        return collapsed

    # -- Modified Files column widths (Tk _persist_tree_columns) ------------
    def _all_widths(self):
        s = getattr(self.app, "_settings", None) if self.app else None
        widths = (s or {}).get("column_widths")
        if not isinstance(widths, dict):
            widths = dict(self.window.cb.get("initial_column_widths") or {})
        return widths

    def _saved_widths(self):
        """The widths the user dragged, by the page's column keys (Tk saved
        them by its column ids, so a Tk-tuned list keeps its widths)."""
        try:
            got = self._all_widths().get(WIDTHS_KEY) or {}
        except Exception:                               # noqa: BLE001
            got = {}
        if not isinstance(got, dict):
            return {}
        out = {}
        for key, tk_id in TK_COLUMN_IDS.items():
            v = got.get(tk_id)
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and v > 0:
                out[key] = int(v)
        return out

    @rpc
    def save_widths(self, widths):
        """A column drag ended: keep the dragged widths in settings.json
        under Tk's key and ids (only the columns given; the rest keep their
        saved width, as Tk merged the dragged ones into what it had)."""
        clean = {}
        for key, v in (widths or {}).items():
            tk_id = TK_COLUMN_IDS.get(str(key))
            if (tk_id and isinstance(v, (int, float))
                    and not isinstance(v, bool) and 20 <= v <= 4000):
                clean[tk_id] = int(v)
        if not clean:
            return False
        allw = dict(self._all_widths())
        prev = allw.get(WIDTHS_KEY)
        tuned = dict(prev) if isinstance(prev, dict) else {}
        tuned.update(clean)
        allw[WIDTHS_KEY] = tuned
        fn = self.window.cb.get("on_column_widths_change")
        if fn is not None:
            try:
                fn(allw)
            except Exception:                           # noqa: BLE001
                log.exception("save column widths")
        self.set(widths={k: tuned[t] for k, t in TK_COLUMN_IDS.items()
                         if isinstance(tuned.get(t), int)})
        return True

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_show(self):
        # borrowed as the Build / flash dialog's backdrop by another tab: the
        # user did not come here, so no rescan of the project behind it
        if not self._return_tab:
            self._maybe_rescan_write_preview()
        self._refresh_write_assets_warning()
        self._update_write_filename_hint()
        self._refresh_prebuild_notes()
        # the original may have been replaced on disk since it was read
        self._refresh_card_size()
        self.set_admin_warning_collapsed(self._shared_admin_collapsed())

    def on_close(self):
        self._scan_id += 1
        self._drive_enum_id += 1
        self._badge_seq += 1
        self._card_seq += 1
        self._return_tab = None
        for dlg in (self._flash, self._diag):
            if dlg is not None:
                try:
                    dlg.close()
                except Exception:                       # noqa: BLE001
                    pass
        self._info.close()


TAB = WriteTab
