"""Defaults tab (the Tk "Default Settings" tab).

Presets the operator-adjustment DEFAULTS baked into a Stern card: the curated
settings form (display units, help, groups), the High Scores block (initials,
player names, default scores), the list of every adjustment the firmware
carries (editable one at a time), widening the machine's own Adjustments menu,
and saved presets (one of which can be baked into every card you build).

Every edit auto-stages into the project's ``.staged_changes.json`` (keys
``settings``, ``high_scores``, ``menu_expose_through``) and the run logic
bakes it into the OUTPUT image after a successful build
(``app.App._apply_staged_settings_to_build`` reads ``staged_default_settings``,
``staged_high_scores`` and ``staged_menu_expose`` off the window;
``_apply_active_preset_to_build`` reads the presets straight from settings).
The master image is only ever read.

Ported from ``gui/main_window.py`` ``_build_settings_tab`` and the
``_settings_*`` methods it wires (12917-14633); the behaviour, the order of
operations and the wording are the Tk tab's.  Where Tk kept a widget + IntVar
per row, this keeps a plain ``value`` per row, read as the IntVar did
(``_as_int``; ``None`` = a field that holds no number, which Tk's
``int(var.get())`` skipped the same way).
"""

import logging
import math
import os
import threading

from .. import compat
from .base import TabService, rpc

log = logging.getLogger(__name__)

EMPTY_TEXT = ("Set the card image on the Extract tab to edit its default "
              "settings.")
LOADING_TEXT = "Reading the image's firmware…"
NO_CURATED_TEXT = ("None of the settings with friendly units and help are "
                   "in this firmware — use the full list below.")
NO_FOLDER_TEXT = ("Set the project folder on the Extract tab first — "
                  "changes stage with the project.")

# Status -> what the reference list calls it.  "service" is still a real
# operator setting, just edited on a different service-menu screen, so it
# must not read as "debug" (see plugins/stern/menu_visibility.py).
STATUS_TEXT = {"": "Adjustments", "service": "Service menu",
               "debug": "Debug", None: ""}

# Sortable columns of the all-settings list: (column, first click descending?)
# "On card" opens on descending - the reason to sort a value column is to
# bring the extreme to the top.  ("setting" is Tk's "#0".)
SORT_CFG = (("setting", False), ("value", True), ("new", False),
            ("range", False), ("status", False))

STAGE_DELAY_MS = 500
LOG_DELAY_MS = 1400


# ---------------------------------------------------------------- formatting
def fmt_num(v):
    """Group thousands once a value is big enough to be hard to read at a
    glance - high-score defaults run to ten digits (feedback batch 22)."""
    return "{:,}".format(v) if abs(v) >= 100000 else str(v)


def range_text(r):
    """The "Range" cell for a row - ``min - max``, plus a note when the
    card's own default falls outside it (Stern ships those: Led Zeppelin
    1.22's ELECTRIC MAGIC FRENZY / MULTIBALL champions)."""
    rng = "%s - %s" % (fmt_num(r["min"]), fmt_num(r["max"]))
    if not (r["min"] <= r["default"] <= r["max"]):
        rng += "  (card ships %s, outside its own range)" % (
            fmt_num(r["default"]))
    return rng


def fmt_value(r, v):
    """A curated row's value the way the operator menu shows it."""
    if r["kind"] == "toggle":
        return "On" if v else "Off"
    if r.get("labels") and v in r["labels"]:
        return "%d - %s" % (v, r["labels"][v])
    return fmt_num(v)


def all_value_text(r, v):
    """A value from the all-settings list, the way the machine shows it."""
    if r["min"] == 0 and r["max"] == 1:
        return "On" if v else "Off"
    if r.get("labels") and v in r["labels"]:
        return "%d - %s" % (v, r["labels"][v])
    return fmt_num(v)


def _as_int(value):
    """``int(var.get())`` on a Tk ``IntVar``, or None where Tk's call raised.

    ``IntVar.get()`` tries a whole number first and then truncates a decimal
    toward zero (``getint``, then ``int(getdouble())``), so a typed "7.5"
    read as 7 in the Tk form and in the editor's OK.  Text that is no number
    at all (and "nan" / "inf", whose ``int()`` raised) gives None, which Tk's
    callers skipped."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if value is None:
        return None
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        f = float(text)
    except ValueError:
        return None
    return int(f) if math.isfinite(f) else None


def read_image(path):
    """The worker half of Tk's ``_settings_open_image``: read *path*'s
    adjustments.  Returns ``("ok_spike1", rows, path)``,
    ``("ok", table, part, fw, rows, path, hstd, every, plan)`` or
    ``("err", exception)``.  Runs off the UI loop; read-only."""
    try:
        # Spike 1 (DMD era) is a different card + firmware format: the
        # operator-adjustment defaults live in the game ELF, decoded by
        # spike1_adjustments.  It has no curated-units / menu-visibility /
        # factory-volume / high-score layer, so it takes the "all settings"
        # list only - everything else below is Spike 2.
        from ...plugins.stern.formats import detect_spike1_game
        if detect_spike1_game(path) is not None:
            from ...plugins.stern import spike1
            from ...plugins.stern.formats import spike1_linux_partitions
            from ...plugins.stern.spike1_adjustments import Spike1Adjustments
            parts = spike1_linux_partitions(path)
            adj = Spike1Adjustments(spike1.read_game_elf(path, parts))
            return ("ok_spike1", adj.rows(), path)
        from ...plugins.stern import factory_volume
        from ...plugins.stern.adjustments import all_rows, curated_rows
        from ...plugins.stern.explorer import CardImage
        from ...plugins.stern.menu_visibility import statuses, widen_plan
        with CardImage(path) as c:
            table, part, fw = c.adjustment_table()
            elf = c.read_firmware(part, fw)
        # Best-effort by design: a build whose menu can't be read still gets
        # the list and the editor, just without the flags.
        try:
            menu = statuses(table)
        except Exception:                               # noqa: BLE001
            menu = {}
        try:
            plan = widen_plan(table)
        except Exception:                               # noqa: BLE001
            plan = None
        # The volume a machine actually starts at is a byte of its own, not
        # the (inert) compiled default - see plugins.stern.factory_volume.
        try:
            master_volume = factory_volume.find(table)
        except Exception:                               # noqa: BLE001
            master_volume = None
        rows = curated_rows(table, menu, master_volume=master_volume)
        try:
            every = all_rows(table, menu)
        except Exception:                               # noqa: BLE001
            every = []
        # The factory high-score board (initials + player names).
        try:
            from ...plugins.stern.high_scores import HighScoreDefaults
            hstd = HighScoreDefaults(elf, table)
        except Exception:                               # noqa: BLE001
            hstd = None
        return ("ok", table, part, fw, rows, path, hstd, every, plan)
    except Exception as e:                              # noqa: BLE001
        return ("err", e)


class DefaultsTab(TabService):
    ns = "defaults"
    key = "Default Settings"
    label = "Defaults"
    group = "Make"
    icon = "defaults"
    exports = (
        "staged_default_settings", "staged_high_scores", "staged_menu_expose",
        "settings_image_var", "settings_preset_var", "settings_autoapply_var",
        "_modes_settings_staged",
    )

    def __init__(self, window):
        super().__init__(window)
        self.settings_image_var = self.var("image", "str", "")
        self.settings_preset_var = self.var("preset", "str", "")
        self.settings_autoapply_var = self.var("autoapply", "bool", False)
        self._hidden_only = self.var("hidden_only", "bool", False)
        self._hidden_only.trace_add("write", lambda *_a: self._fill_all())
        # {"presets": {name: {AD_name: internal value}}, "active": name};
        # persisted through the app's on_default_presets_change.
        self._default_presets = dict(
            self.window.cb.get("initial_default_presets") or {})
        self._image_path = None       # Tk _settings_image_path
        self._table = None            # the AdjustmentTable (Spike 2)
        self._part = None
        self._fw = None
        # Spike 1 has no table object; this flag lets staging / editing /
        # logging run anyway (Tk _settings_spike1).
        self._spike1 = False
        self._busy = False
        self._loading = False         # True while the form is being filled
        self._stage_job = None        # debounced auto-stage timer
        self._log_job = None          # debounced "say what changed" timer
        # Field state as of the last log line - None until a card is loaded.
        self._logged = None
        self._rows = []               # the editable rows (form, scores, extra)
        self._hstd = None             # plugins.stern.high_scores table
        self._hs = []                 # [{label, record, values}] per slot
        self._every = []
        self._all_rows = []
        self._all_sort = (None, False)
        self._all_published = []      # names of the list as last published
        self._menu_plan = None
        self._batch = 0
        self.set(phase="empty", message=EMPTY_TEXT, form=[], hs=[],
                 values={}, hs_values=[], all=[], all_legend="",
                 all_total=0, menu_enabled=False, reset_enabled=False,
                 status="", presets=[], auto_enabled=False,
                 sort={"key": None, "desc": False}, spike1=False,
                 loaded=False, era="")
        self._refresh_presets()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        self.set(era=getattr(mfr, "current_era", "") or "")
        # An era switch with this tab still selected never re-selects it,
        # so follow the Extract tab's card here too (Tk's tab-change did).
        if (getattr(self, "_visible", False)
                and self.store.get("shell", "tab") == self.ns):
            self.ctx.loop.post(self._sync_image)

    def on_show(self):
        self._sync_image()

    def reload_assets_tabs(self):
        """A mod-pack import / transfer wrote staged settings into the folder
        sidecar: put them into the form (Tk's reload_assets_tabs did)."""
        if self._loaded():
            self._apply_staged_overlay()

    def on_close(self):
        for job in (self._stage_job, self._log_job):
            if job is not None:
                try:
                    self.ctx.loop.after_cancel(job)
                except Exception:                       # noqa: BLE001
                    pass
        self._stage_job = self._log_job = None

    def _sync_image(self):
        """The card image mirrors the Extract tab (batch 21): resync on every
        visit and (re)load whenever it changed."""
        src_var = self._win_var("extract_input_var")
        src = (src_var.get() if src_var is not None else "") or ""
        src = src.strip()
        if src and os.path.isfile(src):
            self.settings_image_var.set(os.path.normpath(src))
        img = (self.settings_image_var.get() or "").strip()
        if (img and os.path.isfile(img) and not self._busy
                and img != self._image_path):
            self._open_image()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _win_var(self, name):
        try:
            return getattr(self.window, name)
        except AttributeError:
            return None

    def _loaded(self):
        return self._table is not None or self._spike1

    def _staged_dir(self):
        """The shared assets folder staged settings ride with ('' if unset)."""
        var = self._win_var("write_assets_var")
        d = ((var.get() if var is not None else "") or "").strip()
        return d if d and os.path.isdir(d) else ""

    def _folder_written(self, assets_dir):
        cb = self.window.cb.get("on_folder_state_written")
        if cb is not None:
            cb(assets_dir)

    def _status(self, text):
        self.set(status=text)

    def _after(self, ms, fn):
        return self.ctx.loop.after(ms, fn)

    def _cancel(self, job):
        if job is not None:
            try:
                self.ctx.loop.after_cancel(job)
            except Exception:                           # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # presets
    # ------------------------------------------------------------------
    def _presets_blob(self):
        b = self._default_presets
        b.setdefault("presets", {})
        b.setdefault("active", None)
        return b

    def _persist_presets(self):
        cb = self.window.cb.get("on_default_presets_change")
        if cb is not None:
            cb(self._presets_blob())

    def _refresh_presets(self):
        b = self._presets_blob()
        names = sorted(b["presets"])
        active = b.get("active")
        self.set(presets=names)
        # Reflect the active/auto preset in the dropdown + checkbox.
        if active in b["presets"]:
            self.settings_preset_var.set(active)
            self.settings_autoapply_var.set(True)
        else:
            if self.settings_preset_var.get() not in names:
                self.settings_preset_var.set("")
            self.settings_autoapply_var.set(False)
        self._update_auto_cb()

    def _update_auto_cb(self):
        """Auto-apply is a property of the SELECTED preset - greyed out until
        one is selected so it can't read as an independent feature."""
        self.set(auto_enabled=self.settings_preset_var.get()
                 in self._presets_blob()["presets"])

    def _load_preset(self, name):
        self._update_auto_cb()
        vals = self._presets_blob()["presets"].get(name)
        if not vals or not self._rows:
            return
        self._begin()
        try:
            for r in self._rows:
                if r["name"] in vals:
                    # Preset holds internal units; show them in display units.
                    self._set_row(r, int(vals[r["name"]]) // r.get("scale", 1))
        finally:
            self._end()
        self._status("Loaded preset \"%s\"." % name)

    @rpc
    def pick_preset(self, name):
        """The Preset dropdown picked *name* (Tk <<ComboboxSelected>>, which
        fired on EVERY pick: choosing the preset already selected loads it
        again over the edits).  Tk's read-only combobox only ever offered the
        saved names, so a blank pick is not a choice and changes nothing."""
        name = "" if name is None else str(name)
        if not name:
            return False
        self.settings_preset_var.set(name)
        self._load_preset(name)
        return True

    @rpc
    def save_preset(self):
        """Save As…: check there is something to save, ask for a name (Tk's
        ``_ask_text``, one step), then save it."""
        if not self._rows:
            compat.messagebox.showinfo(
                "Save preset", "Load a card image first, then set the values "
                "you want to save as a preset.")
            return {"ok": False}
        name = compat.simpledialog.askstring(
            "Save preset", "Name this preset (e.g. \"My route\"):")
        if not name or not name.strip():
            return {"ok": False}
        name = name.strip()
        # Store INTERNAL values (display * scale) so a preset means the same
        # thing across titles and the build-time auto-apply writes it directly.
        vals = {}
        for r in self._rows:
            v = _as_int(r["value"])
            if v is None:
                v = r["default"]
            vals[r["name"]] = v * r.get("scale", 1)
        self._presets_blob()["presets"][name] = vals
        self.settings_preset_var.set(name)
        self._persist_presets()
        self._refresh_presets()
        self._status("Saved preset \"%s\" (%d settings)." % (name, len(vals)))
        return {"ok": True, "name": name}

    @rpc
    def delete_preset(self):
        name = self.settings_preset_var.get()
        b = self._presets_blob()
        if name not in b["presets"]:
            return False
        if not compat.messagebox.askyesno("Delete preset",
                                          "Delete preset \"%s\"?" % name):
            return False
        del b["presets"][name]
        if b.get("active") == name:
            b["active"] = None
        self.settings_preset_var.set("")
        self._persist_presets()
        self._refresh_presets()
        self._status("Deleted preset \"%s\"." % name)
        return True

    @rpc
    def toggle_auto(self, on):
        """The "Apply this preset automatically…" checkbox."""
        self.settings_autoapply_var.set(bool(on))
        b = self._presets_blob()
        name = self.settings_preset_var.get()
        if self.settings_autoapply_var.get():
            if name not in b["presets"]:
                compat.messagebox.showinfo(
                    "Auto-apply", "Pick or save a preset first, then tick "
                    "this to bake it into every card you build.")
                self.settings_autoapply_var.set(False)
                return False
            b["active"] = name
            self._status("\"%s\" will be applied to every card you build."
                         % name)
        else:
            b["active"] = None
        self._persist_presets()
        return True

    # ------------------------------------------------------------------
    # reading the card
    # ------------------------------------------------------------------
    def _open_image(self):
        path = (self.settings_image_var.get() or "").strip()
        if not path or not os.path.isfile(path) or self._busy:
            return
        self._busy = True
        self._menu_plan = None
        self._clear_form()
        self.set(phase="loading", message=LOADING_TEXT, status="",
                 reset_enabled=False)

        def _work():
            res = read_image(path)
            self.ctx.loop.post(self._load_done, path, res)

        threading.Thread(target=_work, name="pad-defaults-read",
                         daemon=True).start()

    def _load_done(self, path, res):
        self._busy = False
        # The Card Image changed while this load ran - reload so the form
        # never shows one card's values under another card's path.
        live = (self.settings_image_var.get() or "").strip()
        if live and live != path:
            self._open_image()
            return
        self._apply_result(res)

    def _apply_result(self, res):
        if res[0] == "err":
            self._table = None
            self._spike1 = False
            self.set(phase="error", reset_enabled=False, loaded=False,
                     message="Couldn't read settings from this image:\n%s\n\n"
                             "(The Extract tab's card image must be a Stern "
                             "Spike 2 card. Some newer game builds aren't "
                             "decoded yet.)" % res[1])
            return
        if res[0] == "ok_spike1":
            # Spike 1: no curated form / high scores / menu widening - just
            # the full editable list of the firmware's adjustments.
            _ok, every, ipath = res
            self._table = None
            self._spike1 = True
            self._part = None
            self._fw = None
            self._image_path = ipath
            self._hstd = None
            self._every = every
            self._menu_plan = None
            self._build_form([])
            return
        self._spike1 = False
        _ok, table, part, fw, rows, ipath, hstd, every, plan = res
        self._table = table
        self._part = part
        self._fw = fw
        self._image_path = ipath
        self._hstd = hstd
        self._every = every
        self._menu_plan = plan
        self._build_form(rows)

    def _clear_form(self):
        self._cancel(self._log_job)
        self._log_job = None
        # A different card's fields are a different conversation - the next
        # flush adopts them silently.
        self._logged = None
        self._rows = []
        self._hs = []
        self._all_rows = []
        self._all_published = []
        # _menu_plan is NOT cleared here: the loader sets it before building
        # the form, and the form is what reads it.
        self.set(form=[], hs=[], values={}, hs_values=[], all=[],
                 all_legend="", all_total=0, menu_enabled=False,
                 loaded=False, spike1=False)

    # ------------------------------------------------------------------
    # the form
    # ------------------------------------------------------------------
    @staticmethod
    def _editor(r):
        """How a row is edited: toggle / enum / number, and the numbers the
        page needs for it (the spinner's travel takes in a shipped default
        outside the declared range)."""
        ed = {"lo": min(r["min"], r["default"]),
              "hi": max(r["max"], r["default"]),
              "step": r.get("step") or 1,
              "chars": max(8, len("%d" % r["max"]) + 1)}
        if r["kind"] == "toggle":
            ed["ui"] = "toggle"
        elif r["kind"] == "enum" and r.get("labels"):
            ed["ui"] = "enum"
            ed["options"] = [{"value": v, "label": "%d - %s"
                              % (v, r["labels"][v])}
                             for v in range(r["min"], r["max"] + 1)]
        else:
            ed["ui"] = "number"
        return ed

    def _build_form(self, rows):
        self._clear_form()
        # The reference list stands on its own: a build with no *editable*
        # settings still gets it.
        self._all_rows = list(self._every or [])
        self.set(menu_enabled=bool(self._menu_plan),
                 spike1=bool(self._spike1), loaded=True,
                 all_total=len(self._all_rows))
        if self._all_rows:
            self._fill_all()
        if not rows:
            # Only the curated form is empty - the all-settings list below it
            # still edits everything this firmware has.
            self.set(phase="ready", message=NO_CURATED_TEXT)
            self._apply_staged_overlay()
            return
        from ...plugins.stern.adjustments import is_score_adjustment
        hstd = self._hstd
        hs_adj = {r["adjustment"] for r in hstd.rows} if hstd else set()
        hs_adj.discard(None)
        # EVERY board score goes to the High Scores block, not just the ones
        # whose initials/player-name record was found.
        grid_rows = [r for r in rows
                     if r["name"] not in hs_adj
                     and not is_score_adjustment(r["name"])]
        by_adj = {r["name"]: r for r in rows if r["name"] in hs_adj}
        extra_scores = [r for r in rows
                        if r["name"] not in hs_adj
                        and is_score_adjustment(r["name"])]
        if not grid_rows and not by_adj and not extra_scores:
            grid_rows = rows
        form = []
        group = None
        for r in grid_rows:
            # A heading whenever the block changes.
            if r.get("group") and r["group"] != group:
                group = r["group"]
                form.append({"type": "group", "label": group})
            help_text = r.get("help") or ""
            if r.get("status") == "service":
                help_text = (help_text + "\n\n" if help_text else "") + (
                    "This machine edits this on a different service screen, "
                    "not in the Adjustments menu — so the value there may "
                    "not match what you set here.")
            elif r.get("status") == "debug":
                help_text = (help_text + "\n\n" if help_text else "") + (
                    "This machine's menus never show this setting at all.")
            ed = self._editor(r)
            rng = range_text(r)
            if ed["ui"] == "toggle":
                rng = "off / on"
            elif ed["ui"] == "enum":
                rng = "%d options" % len(ed["options"])
            item = {"type": "row", "name": r["name"], "label": r["label"],
                    "help": help_text, "status": r.get("status"),
                    "on_card": fmt_value(r, r["default"]),
                    "default": r["default"], "range": rng}
            item.update(ed)
            form.append(item)
            self._rows.append(dict(r, value=r["default"], where="form"))
        self.set(phase="ready", message="", form=form)
        self._build_hs(by_adj, extra_scores)
        self._apply_staged_overlay()

    def _score_item(self, score):
        """One slot's on-card score + editable default, registered as an
        ordinary settings row so staging, presets and Reset keep working."""
        self._rows.append(dict(score, value=score["default"], where="hs"))
        return {"name": score["name"], "on_card": fmt_num(score["default"]),
                "default": score["default"], "range": range_text(score),
                "lo": min(score["min"], score["default"]),
                "hi": max(score["max"], score["default"]),
                "step": score.get("step") or 1,
                "chars": max(8, len("%d" % score["max"]) + 1)}

    def _build_hs(self, by_adj, extra_scores=()):
        """The "High Scores" block: one row per slot on the machine's board -
        initials, player name and (where the firmware exposes it as an
        adjustment) the default score.  *extra_scores* are score rows with no
        name record; they get score-only lines so every champion is here."""
        hstd = self._hstd
        self._hs = []
        hs_rows = list(hstd.rows) if hstd is not None else []
        extra_scores = list(extra_scores or [])
        if not hs_rows and not extra_scores:
            self.set(hs=[], hs_values=[])
            return
        items, values = [], []
        for i, rec in enumerate(hs_rows):
            item = {"type": "slot", "index": i, "display": rec["display"]}
            for key in ("initials", "name"):
                cap = rec["%s_max" % key]
                item["%s_max" % key] = cap
                item["card_%s" % key] = rec[key]
                item["%s_tip" % key] = (
                    "On card: \"%s\".\nUp to %d character(s) — the text is "
                    "written into the slot's own space in the firmware, so "
                    "it can't grow." % (rec[key], cap))
            score = by_adj.get(rec["adjustment"])
            item["score"] = (self._score_item(score)
                             if score is not None else None)
            items.append(item)
            vals = {"initials": rec["initials"], "name": rec["name"]}
            self._hs.append({"label": rec["label"], "record": rec,
                             "values": vals})
            values.append(dict(vals))
        for score in extra_scores:
            items.append({"type": "score", "display": score["label"],
                          "score": self._score_item(score)})
        self.set(hs=items, hs_values=values)

    # ------------------------------------------------------------------
    # values
    # ------------------------------------------------------------------
    def _begin(self):
        self._batch += 1

    def _end(self):
        self._batch -= 1
        if self._batch <= 0:
            self._batch = 0
            self._publish_values()

    def _publish_values(self):
        if self._batch:
            return
        self.set(values={r["name"]: r["value"] for r in self._rows})

    def _publish_hs(self):
        self.set(hs_values=[dict(h["values"]) for h in self._hs])

    def _set_value(self, r, value):
        """``r["var"].set(value)`` + its trace (mark + auto-stage)."""
        r["value"] = value
        self._publish_values()
        self._schedule_autostage()

    def _set_row(self, r, display_value):
        """Set a row to a DISPLAY value.  The row's own on-card default always
        goes in verbatim: clamping it would turn "put this back the way the
        card has it" into an edit on rows whose shipped default sits outside
        their declared range."""
        dv = int(display_value)
        v = dv if dv == r["default"] else max(r["min"], min(r["max"], dv))
        self._set_value(r, v)

    def _row(self, name):
        return next((r for r in self._rows if r["name"] == name), None)

    def on_field(self, key, value):
        """The page's field edits: ``val:<AD name>`` for a setting,
        ``hs:<slot>:initials|name`` for the high-score board."""
        if key.startswith("val:"):
            self.set_value(key[4:], value)
            return
        if key.startswith("hs:"):
            try:
                _hs, idx, field = key.split(":", 2)
                self.set_hs_text(int(idx), field, value)
            except ValueError:
                pass
            return
        super().on_field(key, value)

    @rpc
    def set_value(self, name, value):
        """A form field changed (typing, a spinner click, a tick, a pick)."""
        r = self._row(name)
        if r is None:
            return False
        if isinstance(value, str) and not value.strip():
            v = None
        else:
            v = _as_int(value)
        self._set_value(r, v)
        return True

    @rpc
    def set_hs_text(self, index, field, text):
        """A high-score initials / player-name entry changed.  Hard-capped at
        the slot's room as you type: a too-long value would only fail later,
        at build time."""
        if field not in ("initials", "name") or not 0 <= index < len(self._hs):
            return False
        row = self._hs[index]
        cap = row["record"]["%s_max" % field]
        if cap <= 0:
            return False
        text = "" if text is None else str(text)
        row["values"][field] = text[:cap]
        self._publish_hs()
        self._schedule_autostage()
        return True

    @rpc
    def commit(self):
        """A field is done being edited (focus left it, Return): stage now
        and say what moved (Tk's <FocusOut>/<Return> binding)."""
        self._flush_log()
        return True

    # ------------------------------------------------------------------
    # staged overlay, pending, reset
    # ------------------------------------------------------------------
    def _apply_staged_overlay(self):
        """Put the standing preset and the folder's staged edits into the
        freshly built form, and say what's pending - in build-time order
        (the auto-apply preset first, then the staged values on top)."""
        self.set(reset_enabled=True)
        self._refresh_presets()
        staged = self.staged_default_settings(self._staged_dir())
        expose = self.staged_menu_expose(self._staged_dir())
        high = self.staged_high_scores(self._staged_dir())
        self._loading = True
        self._begin()
        try:
            active = self._presets_blob().get("active")
            if active in self._presets_blob()["presets"]:
                self._load_preset(active)
            for r in self._rows:
                if r["name"] in staged:
                    self._set_row(r, int(staged[r["name"]])
                                  // r.get("scale", 1))
            # A staged setting the curated form doesn't draw was edited in the
            # all-settings list - give it its row back.
            have = {r["name"] for r in self._rows}
            by_name = {a["name"]: a for a in self._all_rows}
            for name, val in staged.items():
                if name in have or name not in by_name:
                    continue
                self._set_row(self._add_extra_row(by_name[name]), int(val))
            # Staged initials / player names (Tk left the entries at the
            # card's text here, so the next edit dropped them from the
            # staged record; they are put back like every other setting).
            for row in self._hs:
                fields = high.get(row["label"]) or {}
                for key in ("initials", "name"):
                    if key in fields:
                        cap = row["record"]["%s_max" % key]
                        row["values"][key] = str(fields[key])[:max(0, cap)]
        finally:
            self._end()
            self._loading = False
        self._publish_hs()
        self._fill_all()
        bits = []
        if staged:
            bits.append("%d setting(s) staged for the next Build"
                        % len(staged))
        if expose:
            bits.append("the machine's menu will be opened up to \"%s\""
                        % self._expose_label(expose))
        if active in self._presets_blob()["presets"]:
            bits.append("preset \"%s\" is baked into every card you Build"
                        % active)
        self._status(("; ".join(bits) + ".") if bits else "")
        # This card's state is now the baseline the session log reports
        # against.
        self._logged = self._log_state()

    def _pending(self):
        """``{AD_name: internal value}`` for every field currently set away
        from the image's own default - whichever editor set it."""
        out = {}
        for r in self._rows:
            v = _as_int(r["value"])
            if v is None:
                continue
            if v != r["default"]:
                out[r["name"]] = v * r.get("scale", 1)
        return out

    def _changes(self):
        """``{AD_name: internal_value}`` for rows whose display value differs
        from the image's current default; the "is this row changed?" test is
        the RAW one (what the ● shows) and only a changed row is then clamped
        into the adjustment's own range for writing."""
        out = {}
        for r in self._rows:
            v = _as_int(r["value"])
            if v is None or v == r["default"]:
                continue
            v = max(r["min"], min(r["max"], v))
            if v == r["default"]:
                continue
            out[r["name"]] = v * r.get("scale", 1)
        return out

    def _hs_changes(self):
        """``{slot label: {initials, name}}`` for slots whose text differs
        from the image's - only the changed FIELDS are listed."""
        out = {}
        for row in self._hs:
            diff = {}
            for key, val in row["values"].items():
                if val != row["record"][key]:
                    diff[key] = val
            if diff:
                out[row["label"]] = diff
        return out

    @rpc
    def reset(self):
        """Reset Fields: back to the image's own defaults AND nothing
        staged - with auto-staging the two are one action (batch 21)."""
        self._loading = True
        self._begin()
        try:
            for r in self._rows:
                self._set_row(r, r["default"])
            for row in self._hs:
                for key in row["values"]:
                    row["values"][key] = row["record"][key]
        finally:
            self._end()
            self._loading = False
        self._publish_hs()
        n = 0
        menu = False
        assets_dir = self._staged_dir()
        if assets_dir:
            from ...core import staged_changes
            data = staged_changes.load(assets_dir)
            n = len(data.get("settings") or {}) + len(
                data.get("high_scores") or {})
            menu = bool(data.get("menu_expose_through"))
            if ("settings" in data or "high_scores" in data
                    or "menu_expose_through" in data):
                data.pop("settings", None)
                data.pop("high_scores", None)
                data.pop("menu_expose_through", None)
                staged_changes.save(assets_dir, data)
                self._folder_written(assets_dir)
        self._fill_all()
        cleared = []
        if n:
            cleared.append("%d staged setting(s)" % n)
        if menu:
            cleared.append("the menu widening")
        self._status("Fields reset to the image's current defaults%s."
                     % (" — cleared " + " and ".join(cleared)
                        if cleared else ""))
        if cleared:
            self.log("Defaults: cleared %s." % " and ".join(cleared), "info")
        return True

    # ------------------------------------------------------------------
    # what the run logic reads
    # ------------------------------------------------------------------
    def staged_default_settings(self, assets_dir):
        """``{AD_name: internal_value}`` staged for *assets_dir*, or ``{}``.
        Called by the app's Write flow after a successful build."""
        from ...core import staged_changes
        vals = staged_changes.load(assets_dir).get("settings")
        if not isinstance(vals, dict):
            return {}
        out = {}
        for name, v in vals.items():
            try:
                out[str(name)] = int(v)
            except (TypeError, ValueError):
                continue
        return out

    def staged_high_scores(self, assets_dir):
        """``{slot label: {initials, name}}`` staged for *assets_dir*, or
        ``{}``.  Read by the app's Write flow after a successful build."""
        from ...core import staged_changes
        vals = staged_changes.load(assets_dir).get("high_scores")
        if not isinstance(vals, dict):
            return {}
        out = {}
        for label, fields in vals.items():
            if isinstance(fields, dict):
                clean = {k: str(v) for k, v in fields.items()
                         if k in ("initials", "name")}
                if clean:
                    out[str(label)] = clean
        return out

    def staged_menu_expose(self, assets_dir):
        """The ``AD_`` name the machine's Adjustments menu is staged to be
        opened up to, or ``""``.  Read by the app's Write flow after a
        successful build."""
        from ...core import staged_changes
        val = staged_changes.load(assets_dir).get("menu_expose_through")
        return str(val) if isinstance(val, str) and val else ""

    # ------------------------------------------------------------------
    # auto-staging and the log
    # ------------------------------------------------------------------
    def _schedule_autostage(self):
        """Debounce an auto-stage: edits arrive per keystroke / spinner click,
        so the staging write runs once things settle."""
        if self._loading or not self._loaded():
            return
        self._cancel(self._stage_job)
        self._stage_job = self._after(STAGE_DELAY_MS, self._autostage)

    def _log_state(self):
        """The edited fields as ``{key: (what, old_display, new_display)}``."""
        state = {}
        for r in self._rows:
            v = _as_int(r["value"])
            if v is None or v == r["default"]:
                continue
            state[("set", r["name"])] = (
                r["label"], fmt_value(r, r["default"]), fmt_value(r, v))
        for row in self._hs:
            for key, val in row["values"].items():
                old = row["record"][key]
                if val == old:
                    continue
                state[("hs", row["label"], key)] = (
                    "%s %s" % (row["label"],
                               "initials" if key == "initials" else "name"),
                    '"%s"' % old, '"%s"' % val)
        return state

    def _schedule_log(self, delay=LOG_DELAY_MS):
        """Say what changed once the field settles - a longer wait than the
        stage write, so typing a name logs the name, not each letter."""
        self._cancel(self._log_job)
        self._log_job = self._after(delay, self._flush_log)

    def _flush_log(self):
        """Log every field that moved since the last time we said so.  A stage
        write still waiting on its debounce is brought forward first, so the
        log never describes an edit that isn't staged yet."""
        self._log_job = None
        if self._loading or not self._loaded():
            return
        if self._stage_job is not None:
            self._cancel(self._stage_job)
            self._stage_job = None
            self._autostage()                 # re-schedules a log job…
            job, self._log_job = self._log_job, None
            self._cancel(job)                 # …which is this call
        state = self._log_state()
        before = self._logged
        if before is None:
            # First look at this card: adopt the state without narrating it.
            self._logged = state
            return
        if state == before:
            return
        for key in sorted(set(state) | set(before), key=lambda k: k[1:]):
            now, was = state.get(key), before.get(key)
            if now == was:
                continue
            if now is None:
                what, card, _prev = was
                self.log("Defaults: %s back to the card's %s — no longer "
                         "staged." % (what, card), "info")
            else:
                what, card, val = now
                # From the value last reported, or the card's own on a first
                # edit (Tk's ``(was or now)[2]`` printed the NEW value twice
                # there: "Master Volume 24 → 24").
                self.log("Defaults: %s %s → %s staged for the next Build "
                         "(card has %s)." % (what, was[2] if was else card,
                                             val, card), "info")
        self._logged = state

    def _autostage(self):
        """Record the form's diffs as staged-for-Build (or clear the record
        when the fields are back at the image's defaults)."""
        self._stage_job = None
        if self._busy or not self._loaded():
            return
        self._fill_all()
        changes = self._changes()
        hstd = self._hs_changes()
        assets_dir = self._staged_dir()
        if not assets_dir:
            if changes or hstd:
                self._status(NO_FOLDER_TEXT)
            return
        from ...core import history_log, staged_changes
        data = staged_changes.load(assets_dir)
        before = data.get("settings") or {}
        before_hs = data.get("high_scores") or {}
        new = {k: int(v) for k, v in changes.items()}
        if new == before and hstd == before_hs:
            return
        if new:
            data["settings"] = new
        elif "settings" in data:
            del data["settings"]
        if hstd:
            data["high_scores"] = hstd
        elif "high_scores" in data:
            del data["high_scores"]
        staged_changes.save(assets_dir, data)
        # Project history (batch 24): staged default-settings edits.
        hist = []
        for k in sorted(set(before) | set(new)):
            o, n = before.get(k), new.get(k)
            if o == n:
                continue
            if n is None:
                hist.append("defaults  %s  un-staged (back to the card's "
                            "default, was staged: %s)" % (k, o))
            elif o is None:
                hist.append("defaults  %s  staged: %s" % (k, n))
            else:
                hist.append("defaults  %s  staged: %s  (was staged: %s)"
                            % (k, n, o))

        def _hs(d):
            return ", ".join("%s=%s" % kv for kv in sorted(
                (d or {}).items()))
        for k in sorted(set(before_hs) | set(hstd)):
            o, n = before_hs.get(k), hstd.get(k)
            if o == n:
                continue
            if n is None:
                hist.append("defaults  high score %s  un-staged  (was: %s)"
                            % (k, _hs(o)))
            else:
                hist.append("defaults  high score %s  staged: %s%s"
                            % (k, _hs(n),
                               ("  (was: %s)" % _hs(o)) if o else ""))
        history_log.record(assets_dir, hist)
        self._folder_written(assets_dir)
        total = len(new) + len(hstd)
        self._status(("%d change(s) staged — baked into the next card you "
                      "Build." % total) if total else "Nothing staged.")
        self._schedule_log()

    # ------------------------------------------------------------------
    # the all-settings list
    # ------------------------------------------------------------------
    def _sort_key(self, col, pending):
        """Values sort as NUMBERS, not as the text in the cell."""
        def key(r):
            if col == "value":
                return (r["default"], r["label"].lower())
            if col == "new":
                new = pending.get(r["name"])
                # Staged rows on top, biggest first.
                if new is None or new == r["default"]:
                    return (1, 0, r["label"].lower())
                return (0, -new, r["label"].lower())
            if col == "range":
                return (r["min"], r["max"], r["label"].lower())
            if col == "status":
                return (STATUS_TEXT.get(r.get("status"), ""),
                        r["label"].lower())
            return (r["label"].lower(), r["id"])
        return key

    def _fill_all(self):
        """(Re)build the all-settings list from the last load."""
        rows = self._all_rows
        col, desc = self._all_sort
        self.set(sort={"key": col, "desc": bool(desc)})
        if not rows:
            self._all_published = []
            self.set(all=[], all_legend="")
            return
        known = rows[0].get("status") is not None
        only_hidden = bool(self._hidden_only.get())
        pending = self._pending()
        display = list(rows)
        if col is not None:
            display.sort(key=self._sort_key(col, pending), reverse=desc)
        out = []
        for r in display:
            st = r.get("status")
            if only_hidden and st in ("", None):
                continue
            new = pending.get(r["name"])
            if new == r["default"]:       # a scaled row that round-trips
                new = None
            out.append({
                "name": r["name"],
                "caption": "%s  (0x%02X)" % (r["label"], r["id"]),
                "value": all_value_text(r, r["default"]),
                "new": "" if new is None else all_value_text(r, new),
                "range": ("off / on" if r["min"] == 0 and r["max"] == 1
                          else range_text(r)),
                "menu": STATUS_TEXT.get(st, ""),
                "status": st or "unknown"})
        names = [o["name"] for o in out]
        if names == self._all_published:
            current = self.get("all") or []
            for i, item in enumerate(out):
                if i < len(current) and current[i] != item:
                    self.set_item("all", i, item)
        else:
            self.set(all=out)
            self._all_published = names
        if not known:
            legend = ("%d setting(s) — double-click one to change the default "
                      "it ships with. This build's operator menu couldn't be "
                      "read, so settings hidden from it aren't flagged."
                      % len(rows))
        else:
            n_dbg = sum(1 for r in rows if r["status"] == "debug")
            n_svc = sum(1 for r in rows if r["status"] == "service")
            legend = ("%d setting(s)%s — double-click one to change the "
                      "default it ships with. \"Adjustments\" = in the "
                      "machine's Adjustments menu; \"Service menu\" = %d "
                      "edited on another service screen (volume, speakers, "
                      "software update, tournament, redemption); \"Debug\" = "
                      "%d the machine never shows at all."
                      % (len(rows),
                         ", %d listed" % len(out) if only_hidden else "",
                         n_svc, n_dbg))
        self.set(all_legend=legend)

    @rpc
    def sort_all(self, col):
        """Header click: toggle direction when already sorting by *col*,
        otherwise switch to it at its default direction; a third click on the
        active column goes back to the firmware's own order."""
        cfg = dict(SORT_CFG)
        if col not in cfg:
            return False
        default_desc = cfg[col]
        cur = self._all_sort
        if cur and cur[0] == col:
            if cur[1] != default_desc:
                nxt = (None, False)
            else:
                nxt = (col, not cur[1])
        else:
            nxt = (col, default_desc)
        self._all_sort = nxt
        self._fill_all()
        return True

    # ---- editing anything in the all-settings list ----------------------
    def _add_extra_row(self, all_row):
        """Register a setting from the all-settings list as an editable row
        (no widget of its own; internal units, so ``scale`` is 1)."""
        labels = all_row.get("labels")
        if all_row["min"] == 0 and all_row["max"] == 1:
            kind = "toggle"
        elif labels:
            kind = "enum"
        else:
            kind = "number"
        row = {"name": all_row["name"], "label": all_row["label"],
               "kind": kind, "help": "", "scale": 1, "labels": labels,
               "group": None, "status": all_row.get("status"),
               "default": all_row["default"], "min": all_row["min"],
               "max": all_row["max"], "step": all_row.get("step") or 1,
               "value": all_row["default"], "where": "extra", "extra": True}
        self._rows.append(row)
        self._publish_values()
        return row

    def _all_row(self, name):
        return next((r for r in self._all_rows if r["name"] == name), None)

    @rpc
    def edit_info(self, name):
        """What the "Default setting" editor shows for *name*."""
        row = self._all_row(name)
        if row is None or not self._loaded():
            return None
        note = None
        if row.get("status") == "debug":
            note = ("The machine's menus never show this one, so it can only "
                    "be set from here — unless you also open the menu up to "
                    "it with the button above the list.")
        elif row.get("status") == "service":
            note = ("The machine edits this on a different service screen, "
                    "so what it shows there may not match this default.")
        cur = self._pending().get(row["name"], row["default"])
        info = {"name": row["name"],
                "caption": "%s  (0x%02X)" % (row["label"], row["id"]),
                "on_card": "On card: %s        %s" % (
                    all_value_text(row, row["default"]), range_text(row)),
                "fresh": "A fresh flash or a factory reset picks this up; a "
                         "machine that already has a value keeps it.",
                "note": note, "cur": cur, "default": row["default"],
                "min": row["min"], "max": row["max"],
                "lo": min(row["min"], row["default"]),
                "hi": max(row["max"], row["default"]),
                "step": row.get("step") or 1,
                "chars": max(8, len("%d" % row["max"]) + 1)}
        if row["min"] == 0 and row["max"] == 1:
            info["ui"] = "toggle"
        elif row.get("labels"):
            info["ui"] = "enum"
            info["options"] = [
                {"value": v, "label": "%d - %s" % (v, row["labels"].get(v, v))}
                for v in range(row["min"], row["max"] + 1)]
        else:
            info["ui"] = "number"
        return info

    @rpc
    def edit_apply(self, name, value=None, card=False):
        """The editor's OK (a new value) or "Back to card value"."""
        row = self._all_row(name)
        if row is None or not self._loaded():
            return False
        if card:
            value = row["default"]
        else:
            v = _as_int(value)
            if v is None:
                return False
            value = (max(row["min"], min(row["max"], v))
                     if v != row["default"] else v)
        existing = self._row(row["name"])
        if existing is None:
            existing = self._add_extra_row(row)
        self._set_row(existing, int(value) // existing.get("scale", 1))
        self._fill_all()
        # There is no field to leave here, so report it now.
        self._flush_log()
        return True

    # ---- showing hidden settings on the machine -------------------------
    def _expose_label(self, name):
        """The machine's caption for a staged expose-through name."""
        for r in self._all_rows:
            if r["name"] == name:
                return r["label"]
        return name

    def _stage_menu_expose(self, name):
        """Record (or clear, with ``name=""``) the menu widening."""
        assets_dir = self._staged_dir()
        if not assets_dir:
            self._status(NO_FOLDER_TEXT)
            return False
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
        if name:
            data["menu_expose_through"] = name
        elif "menu_expose_through" in data:
            del data["menu_expose_through"]
        else:
            return True
        staged_changes.save(assets_dir, data)
        self._folder_written(assets_dir)
        return True

    @rpc
    def menu_info(self):
        """What the "Show hidden settings in the machine's menu" dialog
        lists, and which entry it opens on."""
        plan = self._menu_plan
        if not plan:
            return None
        cands = plan["candidates"]
        labels = {r["name"]: r["label"] for r in self._all_rows}
        items = []
        for c in cands:
            items.append({
                "name": c["name"], "label": labels.get(c["name"], c["name"]),
                "id": "0x%02X" % c["id"],
                "n": sum(1 for x in cands if x["id"] <= c["id"])})
        staged = self.staged_menu_expose(self._staged_dir())
        pre = staged if any(c["name"] == staged for c in cands) else None
        if pre is None and cands:
            # Default to the last entry that isn't one of the game's internal
            # "…_CHANGED" bookkeeping flags.
            useful = [c["name"] for c in cands
                      if not c["name"].endswith("_CHANGED")]
            pre = useful[-1] if useful else cands[-1]["name"]
        return {
            "text": "The machine's Feature Adjustments page stops at setting "
                    "0x%02X, which is the only reason the settings below "
                    "can't be reached on the machine. Picking one moves that "
                    "stopping point: everything down to and including your "
                    "pick becomes visible in the Adjustments menu, and can be "
                    "changed there like any other setting.\n\nThe page is a "
                    "straight run, so settings above your pick come with it "
                    "— you can't skip one." % plan["last"],
            "caveat": "This edits the game's code, not just a value. It has "
                      "been verified against the firmware but not yet on a "
                      "real machine — the settings it exposes include factory "
                      "test and bookkeeping entries the game never expected "
                      "an operator to change.",
            "items": items, "pre": pre, "staged": staged}

    @rpc
    def menu_apply(self, name):
        """"Show them": stage the widening through *name*."""
        plan = self._menu_plan
        if not plan:
            return False
        cands = plan["candidates"]
        c = next((x for x in cands if x["name"] == name), None)
        if c is None:
            return False
        label = self._expose_label(c["name"])
        if self._stage_menu_expose(c["name"]):
            n = sum(1 for x in cands if x["id"] <= c["id"])
            self.log("Defaults: the machine's Adjustments menu will show %d "
                     "hidden setting(s), through \"%s\" — staged for the next "
                     "Build." % (n, label), "info")
            self._status("The machine's menu will be opened up to \"%s\" on "
                         "the next Build." % label)
        return True

    @rpc
    def menu_clear(self):
        """"Leave the menu alone": clear a staged widening."""
        staged = self.staged_menu_expose(self._staged_dir())
        if self._stage_menu_expose(""):
            if staged:
                self.log("Defaults: the machine's menu will be left as the "
                         "game ships it.", "info")
            self._status("The machine's menu will be left as the game ships "
                         "it.")
        return True

    # ------------------------------------------------------------------
    # the Modes tab staged one of these settings (item 145)
    # ------------------------------------------------------------------
    def _modes_settings_staged(self, name):
        """The Modes tab staged (or put back) the operator setting *name* in
        the project's Defaults settings.  This form's autostage REPLACES those
        settings from its own fields, so the field is put in step here."""
        rows = self._rows
        if not rows:
            return  # no card read yet: the overlay picks it up when built
        staged = self.staged_default_settings(self._staged_dir())
        self._loading = True
        self._begin()
        try:
            have = False
            for r in rows:
                if r["name"] != name:
                    continue
                have = True
                if name in staged:
                    self._set_row(r, int(staged[name]) // r.get("scale", 1))
                else:
                    self._set_row(r, r["default"])
            if not have and name in staged:
                by_name = {a["name"]: a for a in self._all_rows}
                if name in by_name:
                    self._set_row(self._add_extra_row(by_name[name]),
                                  int(staged[name]))
        finally:
            self._end()
            self._loading = False
        try:
            self._fill_all()
        except Exception:                               # noqa: BLE001
            log.exception("defaults list refresh")

    modes_settings_staged = _modes_settings_staged


TAB = DefaultsTab
