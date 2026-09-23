"""The Multi-boot tab's panel, painted into the web UI's store.

:class:`.multiboot_core.MultibootPanel` is the whole of the Multi-boot tab's
behaviour: the form, the build / apply / update / load / recover runs, the
size check, the preview pipeline, the sounds, every refusal and every
confirmation.  A second copy of any of it is how two copies come to disagree
about one card, so the web tab does not re-implement it - it RUNS it:

* :func:`_rebind_class` rebuilds ``MultibootPanel``'s methods over a copy of
  :mod:`.multiboot_core`'s globals in which ``messagebox`` / ``filedialog``
  are the page's and the four dialogs are the web proxies below.  The core
  module itself is not patched.  (Its Tk variables are already
  :mod:`.compat`'s.)
* Its ``after`` jobs run on the web UI loop (the parent's ``winfo_toplevel``
  is a :class:`compat.Root`); its worker threads hand back through its own
  queue exactly as they do under Tk.
* The few methods that PAINT a widget are overridden (below) to mark a part
  of the page's state dirty; :meth:`WebMultibootPanel._flush` then publishes
  that part into the store namespace ``multiboot`` on the next loop turn.
  Every decision - the checks, the size view, the write plan, validation,
  blockers, confirmations, messages - is still the Tk code's.

``PAD_UI_NO_RIG=1`` (the tests and the screenshot rig) refuses every tool
run and the card reader, and turns the automatic preview and size check off,
so a capture against a real settings file can never start WSL.
"""

import hashlib
import logging
import os
import tempfile
import threading
import types

from . import compat
from . import multiboot_core as mt

log = logging.getLogger(__name__)

NS = "multiboot"

#: What a refused tool run says when the rig is switched off for the session.
NO_RIG_TEXT = ("The rig's tools are switched off in this session "
               "(PAD_UI_NO_RIG=1), so nothing was run.")

_PNG_DIR = os.path.join(tempfile.gettempdir(), "pad-webui-multiboot")
_PNG_KEEP = 96


def no_rig():
    return os.environ.get("PAD_UI_NO_RIG", "") not in ("", "0")


# ----------------------------------------------------------------------
# widget stand-ins
# ----------------------------------------------------------------------
def _noop(*_a, **_k):
    return None


class _Null:
    """A widget that is not there: every method is a no-op.  Given to the
    few attributes the Tk code reads without a ``getattr`` guard, and to the
    ones whose mere presence switches a Tk code path on (``_check_lbls``,
    ``_compact_chk``, ``_roll_repeat_box``...)."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _noop

    def cget(self, *_a):
        return ""

    def winfo_viewable(self):
        return True

    def winfo_width(self):
        return 0

    def winfo_manager(self):
        return ""

    def state(self, *_a):
        return ()

    def __bool__(self):
        return True


class _Parent:
    """The panel's parent frame: all it is asked for is its toplevel, the
    object ``after`` jobs hang off."""

    def __init__(self, root):
        self._root = root

    def winfo_toplevel(self):
        return self._root

    def __str__(self):
        return ".multiboot"


class _WebTable:
    """The images table without widgets (the Tk tab's ``ImageTable``): the
    rows' cell values, the selection, and the busy lock, with ImageTable's
    exact semantics (``set_rows`` keeps or clamps the selection; ``select``
    notifies only on a change and never while locked)."""

    add_text = ""
    add_tip = ""

    def __init__(self, panel):
        self._panel = panel
        self._values = []
        self._sel = None
        self._locked = False
        self._add_row = None

    def _changed(self):
        self._panel._dirty("rows")

    def count(self):
        return len(self._values)

    def set_rows(self, values, select=None):
        values = [dict(v) for v in values]
        keep = self._sel if select is None else select
        self._values = values
        if keep is not None and not (0 <= keep < len(values)):
            keep = len(values) - 1 if values else None
        self._sel = keep if keep is not None and keep >= 0 else None
        self._changed()

    def set_row(self, i, values):
        if not 0 <= i < len(self._values):
            return False
        self._values[i] = dict(values)
        self._changed()
        return True

    def set_cell(self, i, col, text):
        if not 0 <= i < len(self._values):
            return False
        self._values[i][col] = text
        self._changed()
        return True

    def cell(self, i, col):
        if not 0 <= i < len(self._values):
            return None
        return str(self._values[i].get(col, "") or "")

    def row_values(self, i):
        if not 0 <= i < len(self._values):
            return None
        return dict(self._values[i])

    def selected(self):
        return self._sel

    def select(self, i, notify=True):
        if i is None or not 0 <= i < len(self._values):
            return False
        changed = self._sel != i
        self._sel = i
        self._changed()
        if notify and changed and not self._locked:
            self._panel._on_table_select(i)
        return True

    def cell_clicked(self, i):
        """A click on a row's text opens its editor (ImageTable.cell_clicked)."""
        if not 0 <= i < len(self._values):
            return None
        self.select(i)
        self._panel.edit_image(i)
        return "break"

    def icon_clicked(self, i, kind):
        if not 0 <= i < len(self._values):
            return None
        self.select(i)
        if self._locked:
            return "break"
        self._panel._table_action(i, kind)
        return "break"

    def add_clicked(self):
        if self._locked:
            return "break"
        self._panel._add_row_clicked()
        return "break"

    def set_busy(self, busy):
        self._locked = bool(busy)
        self._changed()
        return self._locked

    def apply_theme(self, colors=None):
        return True

    def winfo_width(self):
        return 0

    def destroy(self):
        return None


# ----------------------------------------------------------------------
# the file pickers, the page's, remembering where each one was last
# ----------------------------------------------------------------------
class _FileDialogs:
    """``tkinter.filedialog`` for the panel: compat's pickers (native in the
    desktop window, the page's own browser otherwise), each remembering the
    folder it was last pointed at under its own title."""

    def __init__(self, window):
        self._w = window

    def _start(self, opts):
        key = "multiboot:" + str(opts.get("title") or "")
        if not opts.get("initialdir"):
            d = self._w.last_browse_dir(key)
            if d:
                opts["initialdir"] = d
        return key

    def _keep(self, key, path):
        if not path:
            return
        first = path[0] if isinstance(path, (list, tuple)) else path
        if first:
            self._w.remember_browse_dir(key, first)

    def askopenfilename(self, **opts):
        key = self._start(opts)
        path = compat.filedialog.askopenfilename(**opts)
        self._keep(key, path)
        return path

    def askopenfilenames(self, **opts):
        key = self._start(opts)
        paths = compat.filedialog.askopenfilenames(**opts)
        self._keep(key, paths)
        return paths

    def asksaveasfilename(self, **opts):
        key = self._start(opts)
        if opts.get("confirmoverwrite", True) is False:
            path = _save_without_replace_prompt(opts)
        else:
            path = compat.filedialog.asksaveasfilename(**opts)
        self._keep(key, path)
        return path

    def askdirectory(self, **opts):
        key = self._start(opts)
        path = compat.filedialog.askdirectory(**opts)
        self._keep(key, path)
        return path


def _save_without_replace_prompt(opts):
    """``asksaveasfilename(confirmoverwrite=False)``: the card path's
    Browse…, which picks a card to READ as often as a place to build one.

    Tk passed ``confirmoverwrite=False`` because "already exists - replace
    it?" is a lie while you are picking a card to read (``_browse_card``).
    The desktop window's native save panels (WinForms' SaveFileDialog,
    NSSavePanel, Qt's) all ask it, and pywebview has no way to say not to,
    so until the host's picker says it honours the flag
    (``honours_confirmoverwrite``) this question goes to the page's own
    picker, which never asks."""
    dialogs = compat.ctx().dialogs
    native = getattr(dialogs, "native_file_dialog", None)
    normalise = getattr(dialogs, "_normalise", None)
    if native is None or normalise is None or \
            getattr(native, "honours_confirmoverwrite", False):
        return compat.filedialog.asksaveasfilename(**opts)
    spec = {
        "kind": "file", "mode": "save", "title": opts.get("title") or "",
        "initialdir": opts.get("initialdir") or "",
        "initialfile": opts.get("initialfile") or "",
        "filetypes": [list(ft) for ft in (opts.get("filetypes") or [])
                      if isinstance(ft, (list, tuple)) and len(ft) == 2],
        "multiple": False,
        "defaultextension": opts.get("defaultextension") or "",
        "confirmoverwrite": False,
    }
    return normalise(dialogs.ask(spec), spec)


class _FileDialogProxy:
    """What the rebuilt methods see as ``filedialog``: forwards to the live
    panel's pickers (one module-level name, one panel per window)."""

    target = None

    def __getattr__(self, name):
        target = type(self).target
        if target is None:
            return getattr(compat.filedialog, name)
        return getattr(target, name)


# ----------------------------------------------------------------------
# the four Tk dialogs, as web proxies (same constructor shapes)
# ----------------------------------------------------------------------
PREVIEW_NOTES = mt.PREVIEW_NOTES


class _WebImageDialog:
    """'Edit image…' (:class:`.multiboot_core.ImageEditorDialog`) for the
    page.  The fields are the panel's own editor variables, mirrored into
    the store; this keeps what the Tk dialog kept itself - its title, its
    options, and the preview card's picture."""

    FILETYPES = mt.ImageEditorDialog.FILETYPES

    def __init__(self, panel, index, row):
        self._panel = panel
        self._index = index
        self._group = mt.is_group(row)
        self.title = (("Edit random card %d — %d games"
                       % (index, len(row.members))) if self._group else
                      ("Edit image %d — %s" % (index, os.path.basename(
                          (row.path or "").strip()) or row.device
                          or "no source")))
        self.source = mt._cell_image(row)
        self.kinds = list(mt.ImageEditorDialog.GROUP_KINDS if self._group
                          else mt.ImageEditorDialog.kinds_for(panel._backend))
        names = [val for what, val in mt.on_card_fields(row)
                 if what in ("art", "animation")]
        if names:
            self.kinds.append(("card", "Keep the card's own "
                               + ", ".join(names)))
        labels = dict(self.kinds)
        self.file_kinds = [k for k in ("picture", "video")
                           if not (self._group and k == "video")
                           and k in labels]
        panel._media_entries = {}
        panel._clip_widgets = []
        if self._group:
            panel._roll_repeat_box = _Null()
        # The editor variables must hold THIS row before the page shows the
        # dialog: a click selects the row and Tk loads the editor a turn
        # later (_defer_selection), which a Tk Entry follows live - but the
        # page's focused Title field keeps what it mounted with, and typing
        # into it would write the previous row's title into this one.
        if panel._selected() == index:
            panel._load_editor()
        self.card = {"img": None, "note": PREVIEW_NOTES["none"]}
        self._frame_hit = None          # ((path, seconds), png or None, note)
        self._frame_token = 0
        self._frame_job = None
        self._closed = False

    def show(self):
        self.sync_kind()
        self.sync_preview()
        self._panel._svc.open_dialog("edit")
        return self

    def sync_kind(self):
        self._panel._dirty("editor")

    def sync_confirm_note(self):
        self._panel._dirty("editor")

    def sync_preview(self):
        """The preview card <- the dialog: what ``ImageEditorDialog.
        sync_preview`` decides, with the picture as a file the page shows."""
        panel = self._panel
        try:
            media = panel.media_dir()
            form = panel.form()
            what, value = mt.still_for_row(form, self._index, media,
                                           panel._manifest(media))
        except OSError:
            return
        img, note = None, PREVIEW_NOTES["none"]
        kind = (panel._ed_media.get() or "").strip()
        if what == "video":
            img, note = self._video_frame(*value)
        elif what in ("file", "rendered"):
            img = _picture_file(value)
            note = PREVIEW_NOTES[what] if img else PREVIEW_NOTES["unreadable"]
        elif kind == "none":
            note = PREVIEW_NOTES["text"]
        elif kind in ("picture", "video"):
            row = form.images[self._index] \
                if self._index < len(form.images) else None
            named = "" if row is None else (
                mt.group_media_file(row) if self._group
                else mt.media_file(row))
            note = PREVIEW_NOTES["missing"] if (named or "").strip() \
                else PREVIEW_NOTES["none"]
        self.card = {"img": img, "note": note}
        panel._dirty("editor")

    # -- a video's first frame, fetched off the loop (Tk's _want_frame) --
    def _video_frame(self, path, seconds):
        key = (os.path.abspath(path), str(seconds))
        hit = self._frame_hit
        if hit is not None and hit[0] == key:
            return hit[1], (hit[2] if hit[1] is None else PREVIEW_NOTES["video"])
        self._want_frame(key)
        return None, "Reading the frame this clip starts on…"

    def _want_frame(self, key):
        loop = self._panel._svc.ctx.loop
        if self._frame_job is not None:
            loop.after_cancel(self._frame_job)
        self._frame_job = loop.after(mt.PREVIEW_DEBOUNCE_MS,
                                     lambda: self._grab_frame(key))

    def _grab_frame(self, key):
        self._frame_job = None
        if self._closed:
            return
        self._frame_token += 1
        token = self._frame_token
        path, seconds = key
        loop = self._panel._svc.ctx.loop

        def work():
            try:
                from ..core.audio import find_ffmpeg
                from ..plugins.stern import film_cut
                ffmpeg = find_ffmpeg()
                if not ffmpeg:
                    result = (None, PREVIEW_NOTES["noffmpeg"])
                else:
                    image = film_cut.preview_frame(
                        path, float(seconds or 0), ffmpeg,
                        box=(mt.PREVIEW_ART_W * 2, mt.PREVIEW_ART_H * 2))
                    result = (_save_png(image, "frame", key),
                              PREVIEW_NOTES["video"])
            except Exception as e:                      # noqa: BLE001
                result = (None, "No frame here: %s" % e)
            loop.post(lambda: self._got_frame(token, key, *result))

        threading.Thread(target=work, daemon=True).start()

    def _got_frame(self, token, key, png, note):
        if self._closed or token != self._frame_token:
            return
        self._frame_hit = (key, png, note)
        self.sync_preview()

    def close(self):
        self._closed = True
        if self._frame_job is not None:
            self._panel._svc.ctx.loop.after_cancel(self._frame_job)
            self._frame_job = None


class _WebMenuDialog:
    """'Menu settings' (:class:`.multiboot_core.MenuSettingsDialog`): the
    fields are the panel's own menu variables; this only marks the widgets
    whose presence the Tk code keys on as there."""

    def __init__(self, panel, images):
        self._panel = panel
        panel._heading_entry = _Null()
        panel._theme_combo = _Null()
        panel._default_spin = _Null()
        panel._countdown_word_entry = _Null()
        panel._countdown_word_lbl = _Null()
        panel._sync_theme_states()
        panel._say_countdown_word()

    def show(self):
        self._panel._svc.open_dialog("menu")
        self._panel._dirty("menu")
        return self


class _WebBuildDialog:
    """'Build / flash card' (:class:`.multiboot_core.BuildFlashDialog`):
    the plan the panel decided, and the two ticks."""

    def __init__(self, panel):
        self._panel = panel
        self.plan = panel._write_plan()
        self.write = bool(self.plan["default_write"])
        self.flash = False

    def show(self):
        self._panel._svc.open_dialog("build")
        self._panel._dirty("build")
        return self

    def refresh(self, plan):
        self.plan = plan
        if not plan["can_write"]:
            self.write = False
        self._panel._dirty("build")

    def tick(self, which, value):
        value = bool(value)
        plan = self.plan
        if which == "write" and plan["can_write"]:
            self.write = value
        elif which == "flash" and (plan["can_write"] or plan["have_card"]):
            self.flash = value
        self._panel._dirty("build")

    def start(self):
        if not (self.write or self.flash):
            return False
        self._panel._do_build_flash(bool(self.write), bool(self.flash))
        return True


class _WebCardPick:
    """'Read an SD card' (:class:`.multiboot_core.CardPickDialog`): the
    drive list is enumerated off the loop, as in Tk."""

    MENU_ONLY_TEXT = mt.CardPickDialog.MENU_ONLY_TEXT
    WHOLE_CARD_TEXT = mt.CardPickDialog.WHOLE_CARD_TEXT

    def __init__(self, parent, theme_fn, on_read):
        self._panel = on_read.__self__
        self._on_read = on_read
        self.drives = []
        self.best = None
        self.why = ""
        self.looking = True
        self.picked = None
        self.mode = "menu"
        self._panel._card_pick = self
        self._panel._svc.open_dialog("cardpick")
        self.refresh()

    def refresh(self):
        self.looking = True
        self.picked = None
        self._panel._dirty("cardpick")
        loop = self._panel._svc.ctx.loop

        def work():
            try:
                found, best, why = self._panel._card_drives()
            except Exception as exc:                    # noqa: BLE001
                found, best, why = [], None, \
                    "could not list the drives: %s" % exc
            loop.post(lambda: self.apply(found, best, why))

        threading.Thread(target=work, daemon=True).start()

    def apply(self, drives, best, why):
        self.drives = list(drives)
        self.best = best
        self.why = why or ""
        self.looking = False
        if best is not None and best in self.drives:
            self.picked = self.drives.index(best)
        elif self.drives:
            self.picked = 0
        else:
            self.picked = None
        self._panel._dirty("cardpick")

    def read(self, index=None, whole=None):
        if index is not None:
            self.picked = int(index)
        if whole is not None:
            self.mode = "whole" if whole else "menu"
        if self.picked is None or not 0 <= self.picked < len(self.drives):
            return False
        d = self.drives[self.picked]
        self.close()
        self._on_read(d.device_path, d, self.mode == "whole")
        return True

    def close(self):
        if getattr(self._panel, "_card_pick", None) is self:
            self._panel._card_pick = None
            self._panel._svc.close_dialog("cardpick")


# ----------------------------------------------------------------------
# rebuilding the core panel's methods over web globals
# ----------------------------------------------------------------------
def _rebind(val, g):
    if isinstance(val, types.FunctionType):
        f = types.FunctionType(val.__code__, g, val.__name__,
                               val.__defaults__, val.__closure__)
        f.__kwdefaults__ = val.__kwdefaults__
        f.__qualname__ = val.__qualname__
        f.__doc__ = val.__doc__
        f.__module__ = val.__module__
        f.__dict__.update(val.__dict__)
        return f
    if isinstance(val, staticmethod):
        return staticmethod(_rebind(val.__func__, g))
    if isinstance(val, classmethod):
        return classmethod(_rebind(val.__func__, g))
    if isinstance(val, property):
        return property(*[None if x is None else _rebind(x, g)
                          for x in (val.fget, val.fset, val.fdel)],
                        val.__doc__)
    return val


def _rebind_class(cls, g):
    ns = {}
    for name, val in vars(cls).items():
        if name in ("__dict__", "__weakref__"):
            continue
        ns[name] = _rebind(val, g)
    return type(cls.__name__, cls.__bases__, ns)


_FILEDIALOG = _FileDialogProxy()

_GLOBALS = dict(vars(mt))
_GLOBALS.update(
    messagebox=compat.messagebox,
    filedialog=_FILEDIALOG,
    ImageEditorDialog=_WebImageDialog,
    MenuSettingsDialog=_WebMenuDialog,
    BuildFlashDialog=_WebBuildDialog,
    CardPickDialog=_WebCardPick,
)

_Base = _rebind_class(mt.MultibootPanel, _GLOBALS)


# ----------------------------------------------------------------------
# pictures for the page
# ----------------------------------------------------------------------
def _prune_pngs():
    try:
        names = [os.path.join(_PNG_DIR, n) for n in os.listdir(_PNG_DIR)
                 if n.endswith(".png")]
    except OSError:
        return
    if len(names) <= _PNG_KEEP:
        return
    try:
        names.sort(key=os.path.getmtime)
    except OSError:
        return
    for p in names[:len(names) - _PNG_KEEP]:
        try:
            os.remove(p)
        except OSError:
            pass


def _save_png(image, tag, key):
    """A Pillow image as a PNG in the tab's temp folder; its path."""
    os.makedirs(_PNG_DIR, exist_ok=True)
    digest = hashlib.sha1(repr((tag, key)).encode("utf-8")).hexdigest()[:20]
    path = os.path.join(_PNG_DIR, "%s_%s.png" % (tag, digest))
    image.convert("RGB").save(path, "PNG", compress_level=1)
    _prune_pngs()
    return path


def _png_of(path):
    """The PPM (or any picture) at *path* as a PNG the page can show:
    ``(png path, width, height)``.  Raises when it cannot be read."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:20]
    png = os.path.join(_PNG_DIR, "frame_%s.png" % digest)
    with mt.Image.open(path) as img:
        img.load()
        size = img.size
        if not os.path.isfile(png):
            os.makedirs(_PNG_DIR, exist_ok=True)
            img.convert("RGB").save(png, "PNG", compress_level=1)
            _prune_pngs()
    return png, size[0], size[1]


def _picture_file(path):
    """A picture the owner chose, if it can be read as one (Tk's
    ``CardPreview._photo_for`` test); the page shows the file itself."""
    try:
        with mt.Image.open(path) as img:
            img.verify()
        return os.path.abspath(path)
    except Exception:                                   # noqa: BLE001
        return None


# ----------------------------------------------------------------------
# the panel
# ----------------------------------------------------------------------
class WebMultibootPanel(_Base):
    """``MultibootPanel`` with the store where its widgets were."""

    def __init__(self, svc, platform="stern"):
        self._svc = svc
        self._dirty_parts = set()
        self._flush_job = None
        self._web_frame = None          # {"ppm", "src", "w", "h"}
        self._web_black = None          # {"src": png or None} during a beat
        self._web_alarm = None
        self._card_pick = None
        self._files = _FileDialogs(svc.window)
        _FileDialogProxy.target = self._files
        win = svc.window
        super().__init__(
            _Parent(compat.Root(svc.ctx)),
            log=lambda msg: win.append_log(msg),
            theme_fn=svc.theme_name,
            badge_fn=None, resize_fn=None,
            flash_fn=svc.flash_card, emulate_fn=svc.run_card,
            phase_fn=win.set_multiboot_phase,
            status_fn=win.set_status, platform=platform)
        # the widgets whose presence switches a Tk code path on
        self._table = _WebTable(self)
        self._check_lbls = {k: _Null() for k, _l in mt.STATUS_CHECKS}
        self._pv_canvas = _Null()
        self._pv_status = _Null()
        self._compact_chk = _Null()
        self._action_btns = []
        if no_rig():
            self._auto_plan = False
            self._auto_preview.set(False)
        self._hl_var.trace_add("write", lambda *_a: self._dirty("preview"))
        for var in (self._pv_gain_var, self._pv_mute_var):
            var.trace_add("write", lambda *_a: self._on_preview_volume())
        self._apply_platform_words()
        self._set_busy(False)
        self._sync_editor_states()
        self._update_menu_summary()
        self._refresh_tree()
        self._pv_placeholder()
        self._ok("Browse… to a card you already built and it is read into "
                 "this form, or press + in the table to add the first "
                 "image.")

    # -- seams the tests replace ------------------------------------------
    def _card_drives(self):
        return mt.card_drives()

    # -- publishing ---------------------------------------------------------
    def _dirty(self, *parts):
        self._dirty_parts.update(parts)
        if self._flush_job is None and not getattr(self, "_stopped", False):
            try:
                self._flush_job = self._svc.ctx.loop.after(0, self._flush)
            except Exception:                           # noqa: BLE001
                self._flush_job = None

    def flush_now(self):
        """Publish every part now (the service's first paint, and tests)."""
        self._dirty_parts.update(("words", "rows", "checks", "size",
                                  "summary", "preview", "busy", "alarm",
                                  "msg", "editor", "menu", "build",
                                  "cardpick"))
        self._flush()

    def _flush(self):
        self._flush_job = None
        parts, self._dirty_parts = self._dirty_parts, set()
        out = {}
        for part in ("words", "rows", "checks", "size", "summary", "preview",
                     "busy", "alarm", "msg", "editor", "menu", "build",
                     "cardpick"):
            if part not in parts:
                continue
            try:
                getattr(self, "_pub_" + part)(out)
            except Exception:                           # noqa: BLE001
                log.exception("multiboot: publishing %s", part)
        if out:
            self._svc.set(**out)

    def _pub_words(self, out):
        be = self._backend
        jjp = be.key == "jjp"
        out["w"] = {
            "platform": be.key,
            "out_label": be.out_label,
            "out_noun": be.out_noun,
            "medium": be.medium,
            "medium_needed": be.medium_needed,
            "build_text": be.build_flash_text,
            "flash_frame": be.flash_frame,
            "flash_tick": be.flash_tick,
            "flash_detail": be.flash_detail,
            "add_text": self.ADD_ROW_TEXT,
            "read_card": bool(be.read_card),
            "extract": bool(be.extract),
            "compact": bool(be.compact),
            "groups": bool(be.groups),
            "machine_volume": bool(be.machine_volume),
            "volume_max": int(be.volume_max),
            "max_cards": min(mt.MAX_IMAGES, be.max_cards),
            "about": self.ABOUT_TIP_JJP if jjp else self.ABOUT_TIP,
            "list_tip": self.LIST_TIP,
            "size_tip": self.SIZE_TIP,
            "path_tip": self.PATH_TIP,
            "new_tip": self.NEW_TIP,
            "from_card_tip": self.FROM_CARD_TIP,
            "recover_tip": self.RECOVER_TIP,
            "preview_tip": self.PREVIEW_TIP,
            "select_tip": self.SELECT_TIP,
            "flipper_tip": self.FLIPPER_TIP,
            "volume_tip": self.VOLUME_TIP,
            "media_tip": self.MEDIA_TIP,
            "build_tip": self.BUILD_FLASH_TIP,
            "cancel_tip": self.CANCEL_TIP,
            "play_tip": mt.PLAY_TIP,
            "row_hint": self.ROW_HINT,
            "row_actions": dict((k, t) for k, t in self.ROW_ACTIONS),
            "cancel_text": self.CANCEL_TEXT,
            "cancelling_text": self.CANCELLING_TEXT,
        }

    def _pub_rows(self, out):
        table = self._table
        rows = []
        n = len(table._values)
        for i, v in enumerate(table._values):
            row = self._rows[i] if i < len(self._rows) else None
            full = str(v.get("title", "") or "")
            main = mt.plain_title(row, i) if row is not None else full
            if main and full.startswith(main):
                suffix = full[len(main):].strip()
            else:
                main, suffix = full, ""
            rows.append({
                "i": i, "title": main, "suffix": suffix, "full": full,
                "warn": "[" in suffix,
                "group": bool(row is not None and mt.is_group(row)),
                "sub": str(v.get("sub", "") or ""),
                "media": str(v.get("media", "") or ""),
                "music": str(v.get("music", "") or ""),
                "sound": str(v.get("sound", "") or ""),
                "code": str(v.get("code", "") or ""),
                "up": i > 0, "down": i < n - 1,
            })
        i = self._selected()
        full = mt._cell_image(self._rows[i]) if i is not None else ""
        out.update(
            rows=rows, sel=table._sel, locked=bool(table._locked),
            row_line=full or self.ROW_HINT,
            row_tip=full or self.LIST_TIP,
            flippers=len(self._rows) >= 2,
            add_choices=[{"label": label, "attr": attr, "enabled": bool(live),
                          "why": why}
                         for label, attr, live, why
                         in self.add_row_choices()],
            list_actions=[{"label": label, "attr": attr, "row": bool(need)}
                          if label else {"sep": True}
                          for label, attr, need in self.LIST_ACTIONS])

    def _pub_checks(self, out):
        words = dict(self._backend.status_checks)
        plain = dict(mt.STATUS_CHECKS)
        checks = []
        card_detail, card_state = "", "no"
        for key, label, state, detail in self.checks():
            if label == plain.get(key):
                label = words.get(key, label)
            checks.append({"key": key, "label": label, "state": state,
                           "mark": mt.CHECK_MARKS.get(state, ""),
                           "detail": detail})
            if key == "card":
                card_detail, card_state = detail, state
        out.update(checks=checks, card_detail=card_detail,
                   card_state=card_state,
                   can_read=bool(getattr(self, "_can_read", False)))

    def _pub_size(self, out):
        view = self._size_view
        locked = any(mt.is_group(r) for r in self._rows)
        size = {"tip": self.SIZE_TIP}
        if not view or not view.get("known"):
            state, text = self._size_state()
            thinking = state == "measuring"
            prog = self._size_progress
            size.update(known=False, state=state, measuring=thinking,
                        head=self.SIZE_THINKING if thinking
                        else self.SIZE_UNKNOWN,
                        detail=text, why="", over=False, bands=[],
                        frac=(prog[0] if prog and prog[0] > 0 else None))
        else:
            scale = float(view.get("scale") or 1)
            bands = []
            for label, nbytes, kind in view.get("bands") or ():
                band = {"label": label, "kind": kind,
                        "pct": 100.0 * nbytes / scale,
                        "gb": mt._gbytes(nbytes)}
                if kind == "free" and view.get("saved"):
                    band["saved_pct"] = 100.0 * min(
                        nbytes, view["saved"]) / max(1, nbytes)
                bands.append(band)
            lines = ["%s: %s" % (b["label"], b["gb"]) for b in bands]
            if view.get("saved"):
                lines.append("Saved by compact (stored once): %s"
                             % mt._gbytes(view["saved"]))
            size.update(
                known=True, state="known", measuring=False,
                head=view.get("head") or "", detail=view.get("detail") or "",
                why=view.get("why") or "", over=bool(view.get("over")),
                bands=bands,
                cap_pct=(100.0 * view["cap"] / scale
                         if view.get("over") and view.get("cap") else None),
                tip=self.SIZE_TIP + "\n\n" + "\n".join(lines)
                + ("\n\n" + view["why"] if view.get("why") else ""))
        out.update(size=size, compact_locked=locked,
                   compact_tip=self.COMPACT_TIP_GROUP if locked
                   else self.COMPACT_TIP)

    def _pub_summary(self, out):
        form = self.form()
        text = mt.menu_summary(form)
        parts = text.split("  ·  ")
        groups = None
        if len(parts) >= 6:
            menu = [parts[4], parts[5] if parts[5] == "no heading"
                    else "heading " + parts[5]]
            countdown = [parts[2]]
            d = int(form.default)
            if 0 <= d < len(self._rows):
                countdown.append("%s (%s)" % (parts[3], mt.plain_title(
                    self._rows[d], d)))
            else:
                countdown.append(parts[3])
            for extra in parts[6:]:
                (countdown if extra.startswith("countdown says")
                 else menu).append(extra)
            groups = [["Menu", " · ".join(menu)],
                      ["Countdown", " · ".join(countdown)],
                      ["Sounds", " · ".join(parts[:2])]]
        out.update(summary=text, summary_groups=groups)

    def _pub_preview(self, out):
        hl = mt._int(self._hl_var, mt._int(self._default_var, 0))
        frame = self._web_frame if self._pv_src else None
        pv = {
            "frame": ({"src": frame["src"], "w": frame["w"],
                       "h": frame["h"]} if frame else None),
            "clips": self._web_clips() if frame else [],
            "black": self._web_black,
            "caption": getattr(self, "_pv_full", "") or "",
            "error": bool(self._pv_error),
            "video": self._media_state.get("video", ""),
            "audio": self._media_state.get("audio", ""),
            "hl": hl,
            "sketch": None,
            "placeholder": "",
        }
        if frame is None:
            if self._rows:
                pv["sketch"] = self._sketch(hl)
            else:
                pv["placeholder"] = ("The boot menu is drawn here, by the "
                                     "selector itself.\nAdd two images and "
                                     "it appears; every change redraws it.")
        out["preview"] = pv

    def _sketch(self, hl):
        """The menu drawn from the form, in its own colours, for the page to
        show until the selector has drawn it."""
        n = len(self._rows)
        cards = [{"i": i, "title": mt.plain_title(r, i),
                  "sub": (r.subtitle or "").strip(),
                  "label": "IMAGE %d" % (i + 1)}
                 for i, r in enumerate(self._rows)]
        counter = ""
        if n >= 5:
            page = max(0, min(hl, n - 1)) // 3
            cards = cards[page * 3:page * 3 + 3]
            if self._counter_var.get():
                counter = "<  %d / %d  >" % (min(hl, n - 1) + 1, n)
        d = mt._int(self._default_var, 0)
        row = self._rows[d] if 0 <= d < n else None
        return {
            "heading": self._heading_var.get().strip(),
            "cards": cards, "counter": counter,
            "footer": "LEFT / RIGHT FLIPPER: choose    START: boot",
            "countdown": mt.countdown_example(
                self._countdown_word_var.get(),
                mt.plain_title(row, d) if row is not None else "",
                mt._int(self._timeout_var, 15)),
            "colors": self.menu_colors(),
        }

    def _web_clips(self):
        """Every visible card's rendered clip, laid where the selector put
        its picture (``_play_clips``'s choice of file and rectangle)."""
        if not self._play_var.get() or self._web_black is not None:
            return []
        fp, media = self._pv_fp, self._pv_media
        if not fp or not media:
            return []
        hl = mt._int(self._hl_var, mt._int(self._default_var, 0))
        base = self._pv_cache.get((fp, hl, 0))
        rects = self._pv_rects.get((fp, hl))
        frame = self._web_frame
        if not base or not rects or not frame or \
                frame["ppm"] != os.path.abspath(base):
            return []
        names = mt.card_media_names(self.form())
        clips = []
        for i, rect in sorted(rects.items()):
            name = names[i][1] if 0 <= i < len(names) else ""
            if not name:
                continue
            path = os.path.join(media, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            x, y, w, h = rect
            clips.append({"i": i, "src": path, "v": int(st.st_mtime_ns),
                          "x": x, "y": y, "w": w, "h": h})
        return clips

    def _pub_busy(self, out):
        if self._busy and self._cancel_pending:
            mode = "cancelling"
        elif self._busy:
            mode = "cancel"
        else:
            mode = "build"
        out.update(busy=bool(self._busy), build_mode=mode,
                   run_kind=self._run_kind if self._busy else "",
                   recover_live=bool(self.recoverable()) and not self._busy)

    def _pub_alarm(self, out):
        out["alarm"] = self._web_alarm

    def _pub_msg(self, out):
        out["message"] = self._msg

    def _used(self):
        return [{"label": label, "path": path}
                for label, path in mt.sound_choices(self.used_sounds())]

    def _pub_editor(self, out):
        d = self._image_dialog
        if not isinstance(d, _WebImageDialog):
            out["ed"] = None
            return
        kind = (self._ed_media.get() or "").strip()
        kinds = [{"value": k, "label": label} for k, label in d.kinds]
        if kind and kind not in dict(d.kinds):
            kinds.append({"value": kind, "label": kind})
        shown = "video" if kind == "video" and "video" in d.file_kinds \
            else "picture"
        out["ed"] = {
            "index": d._index, "title": d.title, "source": d.source,
            "group": d._group, "kinds": kinds, "kind": kind,
            "file_kind": shown if shown in d.file_kinds else None,
            "file_label": "Video file:" if shown == "video"
            else "Picture file:",
            "file_live": kind == shown,
            "note": mt.media_note(kind, d._group),
            "confirm_note": mt.image_confirm_note(self._ed_confirm.get(),
                                                  self._confirm_var.get()),
            "rolls": [{"value": k, "label": label}
                      for k, label in mt.ROLL_DRAWS],
            "roll_locked": mt.roll_repeat_locked(
                (self._ed_roll.get() or "").strip()),
            "roll_repeat_label": mt.ROLL_REPEAT_LABEL,
            "roll_note": mt.ImageEditorDialog.ROLL_NOTE,
            "music_words": list(mt.MUSIC_CHOICES),
            "confirm_words": list(mt.IMAGE_CONFIRM_CHOICES),
            "used": self._used(),
            "sounds_note": (
                "Music loops while this image is highlighted. The "
                "confirm sound plays when you press START on it - not "
                "as you scroll past, which is the menu's move click. "
                "menu = whatever the whole menu uses. Under those "
                "words, each list offers every sound file this menu "
                "already uses. %s hears either one now, here."
                % mt.PLAY_NAME),
            "card": {"img": d.card.get("img"), "note": d.card.get("note"),
                     "title": self._ed_title.get(),
                     "sub": self._ed_sub.get(),
                     "colors": self.menu_colors()},
        }

    def _pub_menu(self, out):
        if not isinstance(self._menu_dialog, _WebMenuDialog):
            out["md"] = None
            return
        theme = (self._theme_var.get() or "").strip().lower()
        roles = mt.theme_roles()
        colors = []
        for role in roles:
            var = self._color_vars.get(role)
            value = var.get() if var is not None else ""
            clean = mt.clean_colors({role: value}).get(role)
            colors.append({"role": role, "label": mt.theme_label(role),
                           "value": value, "hex": clean or "",
                           "ok": bool(clean)})
        d = mt._int(self._default_var, 0)
        row = self._rows[d] if 0 <= d < len(self._rows) else None
        own = mt.own_confirm_note(self._rows)
        out["md"] = {
            "themes": [{"value": n, "label": mt.theme_title(n),
                        "about": mt.theme_about(n)}
                       for n in mt.theme_names() + [mt.CUSTOM_THEME]],
            "theme": theme, "custom": theme == mt.CUSTOM_THEME,
            "about": mt.theme_about(theme),
            "colors": colors, "roles_ok": bool(roles),
            "themes_file": mt.THEMES_JSON,
            "example": mt.countdown_example(
                self._countdown_word_var.get(),
                mt.plain_title(row, d) if row is not None else "",
                mt._int(self._timeout_var, 15)),
            "own_note": own,
            "sounds_note": (
                "auto = a click and a stinger pulled from the primary "
                "image; synth = generated tones. The move sound plays "
                "on a flipper press, never over itself, and a file is "
                "cut to 3 s; the confirm sound plays to "
                "the end after START, before the game loads. "
                + (own + " " if own else "") +
                "Under those words, each list offers every sound "
                "file this menu already uses. " +
                mt.PLAY_NAME + " hears either one now, here. With the box "
                "ticked the menu follows the machine's MASTER VOLUME "
                "(the coin-door setting) and the number above is only "
                "how loud the preview plays here."),
            "colors_note": (
                "Make your own…: start from the theme shown, then "
                "change any colour - type it (RRGGBB) or click its "
                "swatch to pick one. The preview redraws as you go."
                if roles else
                "The themes file (%s) could not be read: the menu "
                "keeps its default colours." % mt.THEMES_JSON),
            "default_max": max(0, len(self._rows) - 1),
            "sound_words": list(mt.SOUND_CHOICES),
            "used": self._used(),
        }

    def _pub_build(self, out):
        d = self._buildflash_dialog
        if not isinstance(d, _WebBuildDialog):
            out["bf"] = None
            return
        p = d.plan
        out["bf"] = {
            "write_label": p.get("write_label", ""),
            "write_detail": p.get("write_detail", ""),
            "can_write": bool(p.get("can_write")),
            "have_card": bool(p.get("have_card")),
            "action": p.get("action", ""),
            "write": bool(d.write), "flash": bool(d.flash),
        }

    def _pub_cardpick(self, out):
        c = self._card_pick
        if c is None:
            out["cp"] = None
            return
        out["cp"] = {
            "looking": c.looking,
            "drives": [getattr(dr, "display", str(dr)) for dr in c.drives],
            "picked": c.picked, "why": c.why, "mode": c.mode,
            "menu_text": c.MENU_ONLY_TEXT, "whole_text": c.WHOLE_CARD_TEXT,
        }

    # -- the Tk painters, as store publishers -----------------------------
    def _refresh_tree(self, select=None):
        super()._refresh_tree(select)
        self._dirty("rows", "preview", "summary")

    def _draw_checks(self):
        self._dirty("checks")

    def _draw_size(self):
        self._size_view = (mt.card_size_view(self._plan_info, **self._pk())
                           if self._plan_info else None)
        self._dirty("size")

    def _stop_size_anim(self):
        self._size_anim_job = None

    def _update_menu_summary(self):
        self._dirty("summary", "preview")

    def _say(self, msg):
        super()._say(msg)
        self._dirty("msg")

    def _set_busy(self, busy):
        super()._set_busy(busy)
        self._dirty("busy", "rows")

    def _sync_build_button(self):
        self._dirty("busy")

    def _sync_recover_button(self):
        self._dirty("busy")

    def _sync_flippers(self):
        self._dirty("rows")

    def _sync_compact_lock(self):
        super()._sync_compact_lock()
        self._dirty("size")

    def _show_alarm(self, info):
        super()._show_alarm(info)
        found = mt.version_alarm(info or {}) if info else None
        self._web_alarm = ({"head": self.ALARM_PREFIX + found[0],
                            "full": found[1]} if found else None)
        self._dirty("alarm")

    def _update_row_label(self):
        self._dirty("rows")

    def _row_label_chars(self):
        return 140

    def _on_configure(self, event=None):
        return None

    def _fit_status_height(self):
        return None

    def _focus_preview(self, _event=None):
        return None

    def _popup_add_menu(self, choices):
        # the page shows the add row's choices itself (add_choices)
        self._dirty("rows")
        return None

    def _popup_list_menu(self, row, x, y):
        return None

    def apply_theme(self, colors=None):
        return True

    def _update_edit_status(self):
        super()._update_edit_status()
        self._dirty("checks", "busy", "size")

    def _update_menu_dialog(self):
        if self._menu_dialog is not None:
            self._dirty("menu")

    def _say_countdown_word(self):
        self._update_menu_dialog()
        self._dirty("preview")

    def _paint_swatches(self):
        self._update_menu_dialog()
        self._dirty("preview")

    def _sync_theme_states(self):
        super()._sync_theme_states()
        self._update_menu_dialog()

    def _sync_editor_states(self):
        super()._sync_editor_states()
        if self._image_dialog is not None:
            self._dirty("editor")

    def _forget_image_dialog(self):
        d = self._image_dialog
        if isinstance(d, _WebImageDialog):
            d.close()
        super()._forget_image_dialog()
        self._svc.close_dialog("edit")
        self._dirty("editor")

    def _forget_menu_dialog(self):
        super()._forget_menu_dialog()
        self._svc.close_dialog("menu")
        self._dirty("menu")

    def _forget_build_flash(self):
        super()._forget_build_flash()
        self._svc.close_dialog("build")
        self._dirty("build")

    # -- the preview's picture -------------------------------------------
    def _one_line(self, text):
        return text

    def _status_font(self):
        return None

    def _pv_placeholder(self):
        self._pv_caption, self._pv_error = "", False
        self._web_frame = None
        self._web_black = None
        self._dirty("preview")

    def _pv_say(self, msg, error=False, note="", log=True):
        super()._pv_say(msg, error=error, note=note, log=log)
        self._dirty("preview")

    def _media_say(self, kind, state):
        super()._media_say(kind, state)
        self._dirty("preview")

    def _decode_photo(self, path):
        """The frame at *path* as a PNG the page can show (Tk scaled it into
        a PhotoImage); ``(png, w, h, ppm)``, or None (said)."""
        try:
            png, w, h = _png_of(path)
        except Exception as exc:                        # noqa: BLE001
            self._pv_say("Cannot load %s: %s" % (path, exc), error=True)
            return None
        return (png, w, h, os.path.abspath(path))

    def _drop_photos(self):
        super()._drop_photos()
        self._web_frame = None
        self._dirty("preview")

    def load_frame(self, path, highlight=None, frame=0, total=None):
        ok = super().load_frame(path, highlight, frame, total)
        if ok:
            png, w, h, ppm = self._pv_photo
            self._web_frame = {"src": png, "w": w, "h": h, "ppm": ppm}
            self._web_black = None
            self._dirty("preview")
        return ok

    def _play_start(self):
        if self._stopped:
            return False
        self._play_var.set(True)
        if self._play_t0 is None:
            self._play_t0 = self._play_clock()
        self._dirty("preview")
        return True

    def _schedule_tick(self, ms=None):
        return None

    def _play_tick(self):
        self._play_job = None

    def _play_visible(self):
        return not self._pv_hidden

    def _stop_play(self, msg, error=True):
        super()._stop_play(msg, error)
        self._dirty("preview")

    def _blackout(self, still=None):
        ok = super()._blackout(still)
        png = None
        if still:
            got = self._scaled_photo(still)
            png = got[0] if got else None
        self._web_black = {"src": png}
        self._dirty("preview")
        return ok

    def _blackout_over(self):
        self._web_black = None
        self._dirty("preview")
        return super()._blackout_over()

    # -- the tab on screen / off it (Tk's <Map> / <Unmap>) ----------------
    def _on_shown(self, _event=None):
        super()._on_shown(_event)
        self._dirty("preview")

    def restore_state(self, doc):
        # A restore turns the automatic preview back on (the saved flag no
        # longer counts - see the Tk panel); a session with the rig switched
        # off (tests, captures) must still start no tool by itself.
        ok = super().restore_state(doc)
        if no_rig():
            self._auto_preview.set(False)
        return ok

    def _on_hidden(self, _event=None):
        super()._on_hidden(_event)

    # -- the rig switch (tests, captures) ---------------------------------
    def _run_commands(self, cmds, on_step=None, on_done=None, quiet=(),
                      preview=False, on_tick=None):
        if no_rig():
            if not preview:
                self._error(NO_RIG_TEXT)
            return False
        return super()._run_commands(cmds, on_step, on_done, quiet, preview,
                                     on_tick)

    def load_from_card(self, device_path, drive, whole=False):
        if no_rig():
            self._error(NO_RIG_TEXT)
            return False
        return super().load_from_card(device_path, drive, whole)

    def _write_menu_to_device(self, after=None):
        if no_rig():
            self._error(NO_RIG_TEXT)
            return False
        return super()._write_menu_to_device(after)

    def _on_destroy(self, event=None):
        super()._on_destroy(event)
        job, self._flush_job = self._flush_job, None
        if job is not None:
            try:
                self._svc.ctx.loop.after_cancel(job)
            except Exception:                           # noqa: BLE001
                pass
        if _FileDialogProxy.target is self._files:
            _FileDialogProxy.target = None


def mirror(var, store, window, key, bind=True):
    """Show a panel variable at ``multiboot.<key>``; with *bind*, take the
    page's edits of it back through ``var.set`` (its traces fire, as a Tk
    entry's did).  A dialog's fields are not bound: the service hands their
    edits on only while that dialog is open."""
    var._store, var._ns, var._key = store, NS, key
    store.set(NS, **{key: var.get()})
    if bind:
        window.bind_var(NS, key, var)
    return var
