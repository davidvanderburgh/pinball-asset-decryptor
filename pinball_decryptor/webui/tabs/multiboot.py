"""Multi-boot tab: one SD card (Stern Spike 2) or one install ISO (JJP)
carrying several game images and a boot menu.

The behaviour is :class:`..multiboot_core.MultibootPanel` (see
:mod:`..multiboot_panel`); this service is the seam between it and the page:
the page's buttons call the same panel methods the Tk widgets' commands
called, and the panel's painting is published into the ``multiboot`` store
namespace.  ``window._multiboot_panel`` is that panel, so ``app.py``'s
``multiboot_state`` / ``save_multiboot_state`` / ``restore_multiboot_state``
work unchanged.  Status: docs/plans/web_ui_tabs/multiboot.md.
"""

import copy
import logging
import os

from ..rpc import RpcError
from .base import TabService, rpc

log = logging.getLogger(__name__)

# THE PANEL MAY NOT LOAD, AND THE TAB MUST STILL BE BUILT.  A build missing
# one of the panel's imports (or a bug in the panel) must not cost the
# window its ``_multiboot_panel``.  Without one, App.multiboot_state() answers {} and
# the next quit, project switch or Project > Save writes that {} over the
# open project's saved form - an evening's card, image list and menu, gone
# without a word.  Tk always builds its panel (main_window.py), so it never
# could; here the tab is built either way and a :class:`_SavedForm` keeps
# the form that was restored.
try:
    from .. import multiboot_panel as mbp
except Exception as _exc:                               # noqa: BLE001
    mbp = None
    _PANEL_IMPORT_ERROR = _exc
else:
    _PANEL_IMPORT_ERROR = None

mt = getattr(mbp, "mt", None)


class _SavedForm:
    """``window._multiboot_panel`` when the real panel could not be built:
    it keeps the document app.py restored and hands that SAME document back,
    so the quit-time flush, a project switch and Project > Save write back
    what was saved instead of erasing it."""

    platform = "stern"

    def __init__(self):
        self._doc = {}

    def state(self):
        return copy.deepcopy(self._doc)

    def restore_state(self, doc):
        self._doc = copy.deepcopy(doc) if isinstance(doc, dict) else {}
        return bool(self._doc)

    def image_titles(self):
        return [str(r.get("title") or "")
                for r in (self._doc.get("images") or ())
                if isinstance(r, dict)]

    def on_shown(self):
        return None


class MultibootTab(TabService):
    ns = "multiboot"
    key = "Multi-boot"
    label = "Multi-boot"
    group = "Build"
    icon = "multiboot"
    exports = ("_multiboot_panel",)

    #: The panel's variables the page edits outside any dialog, bound to
    #: their store keys: the page's edit is ``var.set`` and the Tk traces
    #: fire, as a Tk entry's did.
    _BOUND = (
        ("card", "_out_var"), ("compact", "_compact_var"),
        ("pv_gain", "_pv_gain_var"), ("pv_mute", "_pv_mute_var"),
    )

    #: Edit image…'s fields.  Published, but NOT bound: a page edit reaches
    #: the variable only while that dialog is open (see :meth:`on_field`).
    _EDITOR = (
        ("ed_title", "_ed_title"), ("ed_sub", "_ed_sub"),
        ("ed_media", "_ed_media"), ("ed_picture", "_ed_picture"),
        ("ed_video", "_ed_video"), ("ed_music", "_ed_music"),
        ("ed_confirm", "_ed_confirm"), ("ed_roll", "_ed_roll"),
        ("ed_roll_norepeat", "_ed_roll_norepeat"),
    )

    #: Menu settings' fields (and ``color_<role>``): the same, while that
    #: dialog is open.
    _MENU = (
        ("move", "_move_var"), ("confirm", "_confirm_var"),
        ("volume", "_volume_var"), ("machine_vol", "_machine_vol_var"),
        ("timeout", "_timeout_var"), ("heading", "_heading_var"),
        ("same_text", "_same_text_var"), ("counter", "_counter_var"),
        ("countdown_word", "_countdown_word_var"),
        ("default", "_default_var"), ("theme", "_theme_var"),
    )

    #: Sound fields a ▶ Play / Browse… belongs to: (panel var, Tk label).
    _SOUNDS = {"ed_music": ("_ed_music", "Music"),
               "ed_confirm": ("_ed_confirm", "Confirm sound"),
               "move": ("_move_var", "Move sound"),
               "confirm": ("_confirm_var", "Confirm sound")}

    def __init__(self, window):
        super().__init__(window)
        self._dlg = None
        self._broken = None
        self.set(dlg=None, broken=None)
        try:
            self._multiboot_panel = self._build_panel()
        except Exception as exc:                        # noqa: BLE001
            log.exception("the Multi-boot panel could not be built")
            self._broken = (
                "The Multi-boot tab could not start (%s). The form saved "
                "for this project is kept as it was; the session log has "
                "the details." % exc)
            self._multiboot_panel = _SavedForm()
            self.set(broken=self._broken)

    def _build_panel(self):
        if mbp is None:
            raise RuntimeError("its module did not load: %s"
                               % _PANEL_IMPORT_ERROR)
        panel = mbp.WebMultibootPanel(self)
        try:
            for key, attr in self._BOUND:
                mbp.mirror(getattr(panel, attr), self.store, self.window,
                           key)
            for key, attr in self._EDITOR + self._MENU:
                mbp.mirror(getattr(panel, attr), self.store, self.window,
                           key, bind=False)
            for role, var in panel._color_vars.items():
                mbp.mirror(var, self.store, self.window, "color_" + role,
                           bind=False)
            panel.flush_now()
        except Exception:
            try:
                panel._on_destroy()
            except Exception:                           # noqa: BLE001
                pass
            raise
        return panel

    # -- plumbing the panel uses -----------------------------------------
    def theme_name(self):
        theme = self.store.get("shell", "theme") or "dark"
        return "light" if theme == "light" else "dark"

    def open_dialog(self, name):
        self._dlg = name
        self.set(dlg=name)

    def close_dialog(self, name):
        if self._dlg == name:
            self._dlg = None
            self.set(dlg=None)

    def flash_card(self, path, fresh=False):
        """The panel's ``flash_fn``: the app's one SD-card flash dialog (the
        Write tab's), opened on the finished card - main_window's lambda."""
        fn = getattr(self.window, "_open_flash_dialog", None)
        if fn is None:
            self._multiboot_panel._error(
                "The SD-card flash dialog is not available: the Write tab "
                "did not load.")
            return None
        return fn(initial_image=path, fresh=fresh,
                  image_titles=self._multiboot_panel.image_titles())

    def run_card(self, path):
        """The panel's ``emulate_fn`` (main_window's ``run_emulator``): the
        Emulate tab's launch with the boot selector ticked, or the Emulate
        JJP tab's for a JJP multi-boot ISO."""
        if getattr(self._multiboot_panel, "platform", "stern") == "jjp":
            target = getattr(self.window, "_jjp_emulate_panel", None) \
                or self.window.service("emulate_jjp")
            fn = getattr(target, "launch_iso", None)
            if fn is None:
                self.window.append_log("[multi-boot] the Emulate JJP tab is "
                                       "not built; cannot start the rig")
                return
            self._show_tab("emulate_jjp")
            fn(path)
            return
        target = getattr(self.window, "_emulate_panel", None) \
            or self.window.service("emulate")
        fn = getattr(target, "launch_card", None)
        if fn is None:
            self.window.append_log("[multi-boot] the Emulate tab is not "
                                   "built; cannot start the rig")
            return
        self._show_tab("emulate")
        fn(path, select=True)

    def _show_tab(self, ns):
        try:
            self.window.select_tab(ns)
        except Exception:                               # noqa: BLE001
            pass

    # -- hooks -------------------------------------------------------------
    def on_manufacturer(self, mfr):
        if self._broken:
            return
        panel = self._multiboot_panel
        if getattr(getattr(mfr, "capabilities", None), "multiboot", False):
            panel.set_platform(getattr(mfr, "key", "stern"))
        panel._apply_platform_words()
        panel.flush_now()

    def on_show(self):
        if self._broken:
            return
        panel = self._multiboot_panel
        panel.on_shown()
        panel._refresh_facts()

    def on_close(self):
        if self._broken:
            return
        self._multiboot_panel._on_destroy()

    def on_field(self, key, value):
        """A dialog's field, which is published but not bound.

        THE DIALOGS TAKE THE GRAB, AS TK'S DID.  A page edit lands a moment
        after it was typed (the field's debounce, or its blur), and Cancel
        or Escape can get there first: the snapshot is put back, and then
        the late edit wrote straight into the row or the menu again - the
        editor's variables write through on every change - and Build wrote
        it to the card.  In Tk nothing reaches a dialog that has gone, so an
        edit for a closed dialog is dropped here."""
        if self._broken:
            return
        panel = self._multiboot_panel
        var, dialog = self._dialog_var(panel, key)
        if var is None:
            self.set(**{key: value})
            return
        if dialog is not None:
            var.set(value)

    def _dialog_var(self, panel, key):
        """``(variable, its open dialog or None)`` for a dialog field, or
        ``(None, None)`` for a key no dialog owns."""
        for k, attr in self._EDITOR:
            if k == key:
                return getattr(panel, attr), panel._image_dialog
        for k, attr in self._MENU:
            if k == key:
                return getattr(panel, attr), panel._menu_dialog
        if key.startswith("color_"):
            var = panel._color_vars.get(key[len("color_"):])
            if var is not None:
                return var, panel._menu_dialog
        return None, None

    # -- helpers -----------------------------------------------------------
    def _live(self):
        """The panel, for a page call (the tab says why when there is none)."""
        if self._broken:
            raise RpcError(self._broken)
        return self._multiboot_panel

    def _panel(self):
        return self._live()

    def _row(self, i):
        try:
            i = int(i)
        except (TypeError, ValueError):
            raise RpcError("No such image.")
        if not 0 <= i < len(self._live()._rows):
            raise RpcError("No such image.")
        return i

    def _done(self):
        self._multiboot_panel._dirty("rows", "checks", "busy", "preview")
        return True

    # -- the page's calls: the card row ------------------------------------
    @rpc
    def visible(self, on):
        """The page is (not) showing this tab: Tk's <Map> / <Unmap>, which is
        when the preview's sound plays and stops."""
        if self._broken:
            return False
        panel = self._multiboot_panel
        if on:
            panel._on_shown()
        else:
            panel._on_hidden()
        return True

    @rpc
    def path_enter(self, text=None):
        """<Return> in the path box (the box's value comes with it, so the
        read is of what was typed)."""
        panel = self._live()
        if text is not None and panel._out_var.get() != text:
            panel._out_var.set(text)
        panel._path_committed()
        return self._done()

    @rpc
    def path_focus(self):
        """Clicking into the path box asks again what is at it (Tk's
        <FocusIn>)."""
        if self._broken:
            return False
        self._multiboot_panel._refresh_facts()
        return True

    @rpc
    def browse(self):
        self._live()._browse_card()
        return self._done()

    @rpc
    def new_card(self):
        self._live()._new_card_clicked()
        return self._done()

    @rpc
    def from_card(self):
        self._live()._from_card_clicked()
        return self._done()

    @rpc
    def cardpick_refresh(self):
        pick = self._live()._card_pick
        if pick is not None:
            pick.refresh()
        return True

    @rpc
    def cardpick_pick(self, index=None, mode=None):
        panel = self._live()
        pick = panel._card_pick
        if pick is None:
            return False
        if index is not None:
            pick.picked = int(index)
        if mode in ("menu", "whole"):
            pick.mode = mode
        panel._dirty("cardpick")
        return True

    @rpc
    def cardpick_read(self):
        pick = self._live()._card_pick
        if pick is None:
            return False
        pick.read()
        return self._done()

    @rpc
    def cardpick_cancel(self):
        pick = self._live()._card_pick
        if pick is not None:
            pick.close()
        return True

    # -- the images table ---------------------------------------------------
    @rpc
    def select(self, i):
        self._live()._table.select(self._row(i))
        return True

    @rpc
    def cell_clicked(self, i):
        self._live()._table.cell_clicked(self._row(i))
        return self._done()

    @rpc
    def row_action(self, i, kind):
        if kind not in ("edit", "del", "up", "down"):
            raise RpcError("No such action.")
        self._live()._table.icon_clicked(self._row(i), kind)
        return self._done()

    @rpc
    def add_choice(self, attr):
        """One of the add row's choices (``add_row_choices``): the same
        method its menu entry ran."""
        panel = self._live()
        if panel._table._locked:
            return False
        for _label, name, live, _why in panel.add_row_choices():
            if name == attr:
                if live:
                    getattr(panel, attr)()
                return self._done()
        raise RpcError("No such choice.")

    @rpc
    def list_action(self, attr, i=None):
        """The row's right-click menu (``LIST_ACTIONS``), greyed as
        ``_popup_list_menu`` greys it."""
        panel = self._live()
        for label, name, needs_row in panel.LIST_ACTIONS:
            if label is None or name != attr:
                continue
            if panel._busy:
                return False
            if i is not None:
                panel._table.select(self._row(i))
            if needs_row and panel._selected() is None:
                return False
            getattr(panel, attr)()
            return self._done()
        raise RpcError("No such command.")

    # -- the preview ----------------------------------------------------------
    @rpc
    def redraw(self):
        """The preview's right-click 'Draw it with the selector now' (David,
        2026-09-23: the sketch "is not exactly what the user sees"): the
        frame the preview points at, drawn by the real selector whether or
        not it is cached - Tk's render_preview."""
        panel = self._live()
        if panel._busy or panel._pv_busy:
            return False
        ok = bool(panel.render_preview())
        self._done()
        return ok

    @rpc
    def save_picture(self):
        """Save the selector's own frame (the picture the machine will show)
        as a PNG. False when only the sketch is up."""
        panel = self._live()
        frame = getattr(panel, "_web_frame", None)
        if not frame or not os.path.isfile(frame.get("src") or ""):
            return False
        path = self.window.ask_save(
            "multiboot_picture", "Save the boot menu picture",
            initialfile="boot-menu.png",
            filetypes=[("PNG image", "*.png")], defaultextension=".png")
        if not path:
            return False
        import shutil
        shutil.copyfile(frame["src"], path)
        self.window.append_log("[multi-boot] saved the boot menu picture to %s"
                               % path)
        return True

    @rpc
    def flip(self, step):
        panel = self._live()
        if int(step) < 0:
            panel.flip_left()
        else:
            panel.flip_right()
        return self._done()

    @rpc
    def press_select(self):
        self._live().press_select()
        return True

    @rpc
    def remeasure(self):
        panel = self._live()
        panel._remeasure()
        panel._dirty("size")
        return True

    # -- Edit image… ------------------------------------------------------
    @rpc
    def edit(self, i=None):
        panel = self._live()
        panel.edit_image(None if i is None else self._row(i))
        return self._done()

    @rpc
    def edit_ok(self):
        panel = self._live()
        if panel._image_dialog is not None:
            panel._image_editor_ok()
        return self._done()

    @rpc
    def edit_cancel(self):
        panel = self._live()
        if panel._image_dialog is not None:
            panel._image_editor_cancel()
        return self._done()

    @rpc
    def edit_browse(self, kind):
        """Browse… on the picture / video row: picking a file IS picking
        that option (ImageEditorDialog._browse)."""
        panel = self._live()
        if kind not in mbp._WebImageDialog.FILETYPES:
            raise RpcError("No such file row.")
        if panel._image_dialog is None:
            return False
        var = panel._ed_picture if kind == "picture" else panel._ed_video
        path = mbp._FILEDIALOG.askopenfilename(
            title="Pick a media file",
            filetypes=list(mbp._WebImageDialog.FILETYPES[kind])
            + [("All files", "*.*")])
        if panel._image_dialog is None:
            return False            # the dialog went while the picker was up
        if path:
            var.set(path)
        if var.get().strip():
            panel._ed_media.set(kind)
        return True

    @rpc
    def sound_browse(self, field):
        """Browse… beside a sound box (``_media_row``'s)."""
        panel = self._live()
        attr, _label = self._sound(field)
        if self._dialog_var(panel, field)[1] is None:
            return False
        var = getattr(panel, attr)
        path = mbp._FILEDIALOG.askopenfilename(
            title="Pick a media file",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")])
        if path and self._dialog_var(panel, field)[1] is not None:
            var.set(path)
        return True

    @rpc
    def play(self, field):
        """▶ Play beside a sound box: what that row names, now."""
        panel = self._live()
        attr, label = self._sound(field)
        image = None
        if field.startswith("ed_") and panel._image_dialog is not None:
            image = getattr(panel._image_dialog, "_index", None)
        return bool(panel.play_sound_choice(label, getattr(panel, attr),
                                            image=image))

    def _sound(self, field):
        entry = self._SOUNDS.get(field)
        if entry is None:
            raise RpcError("No such sound.")
        return entry

    # -- Menu settings… -----------------------------------------------------
    @rpc
    def menu_settings(self):
        self._live().open_menu_settings()
        return True

    @rpc
    def menu_ok(self):
        panel = self._live()
        if panel._menu_dialog is not None:
            panel._menu_settings_ok()
        return self._done()

    @rpc
    def menu_cancel(self):
        panel = self._live()
        if panel._menu_dialog is not None:
            panel._menu_settings_cancel()
        return self._done()

    @rpc
    def pick_theme(self, name):
        """The theme list (MenuSettingsDialog's combobox -> _theme_picked)."""
        panel = self._live()
        name = (name or "").strip().lower()
        if name not in mt.theme_names() + [mt.CUSTOM_THEME]:
            raise RpcError("No such theme.")
        if panel._menu_dialog is None:
            return False
        if name != panel._theme_var.get().strip().lower():
            panel._theme_var.set(name)
        return True

    @rpc
    def set_color(self, role, value):
        """A colour's swatch picked (Tk's _pick_color: only for 'Make your
        own…')."""
        panel = self._live()
        var = panel._color_vars.get(role)
        if var is None or panel._menu_dialog is None or \
                panel._theme_var.get().strip().lower() != mt.CUSTOM_THEME:
            return False
        var.set(str(value or "").strip().lstrip("#").lower())
        return True

    # -- the action bar -----------------------------------------------------
    @rpc
    def build_flash(self):
        """The green button: the Build / flash dialog, or - while a run is
        up - that run's Cancel."""
        panel = self._live()
        if panel._busy:
            return panel.cancel_run()
        panel._open_build_flash()
        return self._done()

    @rpc
    def build_tick(self, which, value):
        d = self._live()._buildflash_dialog
        if d is None:
            return False
        d.tick(which, value)
        return True

    @rpc
    def build_start(self):
        d = self._live()._buildflash_dialog
        if d is None:
            return False
        d.start()
        return self._done()

    @rpc
    def build_cancel(self):
        panel = self._live()
        if panel._buildflash_dialog is not None:
            panel._forget_build_flash()
        return True

    @rpc
    def cancel_run(self):
        return bool(self._live().cancel_run())

    @rpc
    def run_emulator(self):
        self._live()._run_emulator()
        return self._done()

    @rpc
    def recover(self):
        self._live()._recover_clicked()
        return self._done()


TAB = MultibootTab
