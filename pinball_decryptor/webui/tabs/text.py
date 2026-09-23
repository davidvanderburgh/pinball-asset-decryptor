"""Replace Text tab: the editable on-screen strings from ``text/strings.tsv``
with an in-place editor.  Edits are saved straight to the manifest so the
Write step patches them into their scene files / the game program.

Ported from the Tk window's Replace Text section (``gui/main_window.py``
``_build_text_tab`` .. ``_refresh_scene_browser_text``, and the
``_TextReplaceDialog``).  The rules (Max, grows, filters, Replace
everywhere's plan) live in :mod:`..text_rules`; the Scenes window this tab
opens ("Show in Scenes…") is :mod:`..text_scenes`.

Page state (``text.*``):

  rows          one compact dict per manifest row, in manifest order:
                {o: original, n: new text, mx: Max cell, sc: Scene cell,
                 nm: scene Name, ed: edited, sf: a scene (.radium) row}
  view          the row indices the filters + sort show, in display order
  scene_options the Scene dropdown's values
  sel           the selected row index (None = nothing selected)
  orig, scene_note, budget_over, can_edit, sel_edited   the editor
  scanning, empty   the list's scanning state / empty-state message
  folder        the project folder the row mirrors
  sort          {col, desc}
Tk variables (exported to the run logic): search, status, new, budget,
apply_all, change_filter, scene_filter.
"""

import os
import subprocess
import sys
import threading
import time

from .. import compat
from .. import text_rules as R
from .base import TabService, rpc

EMPTY_NO_FOLDER = "Set the project folder on the Extract tab, then click Scan."
EMPTY_SCANNING = "Scanning for on-screen text…"
EMPTY_NONE = ("No editable on-screen text found in this folder.\n"
              "Run Extract on a Spike 2 card first — it writes "
              "text/strings.tsv.")
EMPTY_CANCELLED = "Scan cancelled — click Scan to try again."

#: Sortable columns: Tk's _text_sort_cfg ids, and whether each starts
#: descending (Max does).
SORT_COLS = {"#0": False, "new": False, "max": True, "scene": False,
             "name": False}


def reveal_in_file_manager(path):
    """Open the native file manager on *path* (Tk ``_reveal_in_file_manager``):
    select a file on Windows / macOS, open its folder on Linux.  Raises on
    failure so the caller can say why."""
    from ...core import desktop
    path = os.path.abspath(path)
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if sys.platform == "win32":
        if os.path.isfile(path):
            subprocess.Popen('explorer /select,"%s"' % os.path.normpath(path))
        else:
            os.startfile(folder)                    # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path)
                         else ["open", folder])
    else:
        ok, err = desktop.open_path(folder)
        if not ok:
            raise RuntimeError(err)


class TextTab(TabService):
    ns = "text"
    key = "Replace Text"
    label = "Text"
    group = "Replace"
    icon = "text"
    exports = (
        "text_search_var", "text_status_var", "text_new_var",
        "text_budget_var", "text_apply_all_var", "text_change_filter_var",
        "text_scene_filter_var", "reveal_text_string",
        "_refresh_scene_browser_text", "_scan_text_strings",
        "_open_scene_browser", "open_scene_browser", "open_font_studio",
        "_open_font_studio", "_text_rows", "_text_scan_dir",
    )

    def __init__(self, window):
        super().__init__(window)
        self.text_search_var = self.var("search")
        self.text_status_var = self.var("status")
        self.text_new_var = self.var("new")
        self.text_budget_var = self.var("budget")
        self.text_apply_all_var = self.var("apply_all", "bool", False)
        self.text_change_filter_var = self.var("change_filter", value="All")
        self.text_scene_filter_var = self.var("scene_filter",
                                              value=R.SCENE_ALL)
        self._text_rows = []              # manifest dicts
        self._text_scan_dir = ""          # folder the rows were loaded from
        self._text_scan_id = 0
        self._scan_t0 = None
        self._current = None              # selected row index
        self._sort = ("#0", False)
        self._scene_choices = {}          # display -> path
        self._scene_displays = {}         # path -> display
        self._scene_names = {}            # {"rad::<card path>": name}
        self._assets_var = None           # write_assets_var, traced once
        self._suspend = 0                 # batch filter sets: one refresh
        self.text_search_var.trace_add("write", self._on_filter_var)
        self.text_change_filter_var.trace_add("write", self._on_filter_var)
        self.text_scene_filter_var.trace_add("write", self._on_filter_var)
        self.text_new_var.trace_add("write",
                                    lambda *_a: self._update_budget())
        from ..text_scenes import TextScenesService
        from ..text_fonts import TextFontsService
        self.scenes = TextScenesService(self)
        self.ctx.registry.service(self.scenes.ns, self.scenes)
        self.fonts = TextFontsService(self)
        self.ctx.registry.service(self.fonts.ns, self.fonts)
        self.set(rows=[], view=[], scene_options=[R.SCENE_ALL],
                 sel=None, orig="", scene_note="", budget_over=False,
                 can_edit=False, sel_edited=False, scanning=False,
                 empty=EMPTY_NO_FOLDER, folder="", sort={"col": "#0",
                                                        "desc": False},
                 total=0, edited=0, col_widths=self._saved_widths())

    # ------------------------------------------------------------------
    # the project folder (shared; set on the Extract tab)
    # ------------------------------------------------------------------
    def _assets(self):
        var = self.window.write_assets_var
        if var is not self._assets_var:
            self._assets_var = var
            try:
                var.trace_add("write", lambda *_a: self._mirror_folder())
            except Exception:                        # noqa: BLE001
                pass
        return var

    def _assets_path(self):
        return (self._assets().get() or "").strip()

    def _mirror_folder(self):
        self.set(folder=self._assets_path())

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        # New mfr: drop any rows loaded for the previous one so a stale
        # manifest can't leak across a manufacturer switch.
        self._text_scan_id += 1
        self._scan_t0 = None
        self._text_rows = []
        self._text_scan_dir = ""
        # The Scenes window shows the previous project's scenes: close it
        # (nothing in it is unsaved).  Tk left both tool windows alone on a
        # switch, so a Fonts window holding an import that was fitted but
        # never applied stays open (closing it asks, as Tk's did); an empty
        # one closes with the Scenes window.
        self.scenes.close()
        if not self.fonts.has_pending():
            self.fonts.close(force=True)
        self._clear_edit_panel()
        self._refresh_list()
        self.set(scanning=False, empty=EMPTY_NO_FOLDER)
        self._mirror_folder()

    def on_show(self):
        self._mirror_folder()
        self._maybe_rescan()

    def on_close(self):
        self.scenes.close()
        self.fonts.close(force=True)

    def _is_visible(self):
        return bool(getattr(self, "_visible", False))

    def _maybe_rescan(self):
        """Auto-load when the tab becomes visible and the folder has changed
        since the last scan."""
        mfr = self.mfr
        if mfr is None or not getattr(mfr.capabilities, "replace_text",
                                      False):
            return
        path = self._assets_path()
        if path and path != self._text_scan_dir:
            self._scan_text_strings()

    # cross-tab calls the run logic fans out ----------------------------
    def invalidate_asset_scans(self, rescan_visible=True):
        self._text_scan_dir = ""
        if rescan_visible and self.window.current_tab_key() == self.key:
            self._scan_text_strings()

    def reload_assets_tabs(self):
        # the window's invalidate pass already blanked the stamp; re-scan
        # every tab this manufacturer shows, like Tk's _rescan_all_assets_tabs
        self._text_scan_dir = ""
        if self._is_visible():
            self._scan_text_strings()

    def refresh_after_revert(self):
        """The revert wiped the manifest: reload it if it had been scanned."""
        if self._text_scan_dir:
            self._text_scan_dir = ""
            self._scan_text_strings()

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------
    def _scan_text_strings(self):
        """Load ``text/strings.tsv`` from the project folder on a worker
        thread (a manifest on a slow share must not freeze the page)."""
        from ...core import text_manifest
        assets_path = self._assets_path()
        self._mirror_folder()
        self._text_scan_id += 1
        scan_id = self._text_scan_id
        if not assets_path or not os.path.isdir(assets_path):
            self._text_rows = []
            self._text_scan_dir = ""
            self._clear_edit_panel()
            self._refresh_list()
            self._end_scan(log=False)
            self.set(empty=EMPTY_NO_FOLDER)
            return

        def _work():
            try:
                loaded, err = text_manifest.load(assets_path), None
            except Exception as e:                   # noqa: BLE001
                loaded, err = [], e
            # A project extracted before the tool measured which program
            # strings can take longer text carries no flag on any of them:
            # re-read the limits once from the card it came from (best
            # effort; the rows already show the optimistic default).
            if err is None and any(
                    not (r.get("path") or "").lower().endswith(".radium")
                    and not r.get("grow") and not r.get("fixed")
                    for r in loaded):
                try:
                    from ...plugins.stern import engine as _stern_engine
                    if _stern_engine.refresh_program_text_flags(assets_path):
                        loaded = text_manifest.load(assets_path)
                except Exception:                    # noqa: BLE001
                    pass
            if self._text_scan_id != scan_id:
                return
            self.ctx.loop.post(self._populate_after_scan, loaded, err,
                               scan_id, assets_path)

        self._begin_scan()
        threading.Thread(target=_work, daemon=True,
                         name="text-scan").start()

    def _begin_scan(self):
        now = time.monotonic()
        if self._scan_t0 is not None:
            self.log("Text scan replaced after %.1f s by a newer scan."
                     % (now - self._scan_t0), "info")
        self._scan_t0 = now
        self.log("Text scan started.", "info")
        self.set(scanning=True, empty=EMPTY_SCANNING, view=[])

    def _end_scan(self, log=True):
        t0, self._scan_t0 = self._scan_t0, None
        if log and t0 is not None:
            self.log("Text scan finished in %.1f s."
                     % (time.monotonic() - t0), "info")
        self.set(scanning=False)

    @rpc
    def cancel_scan(self):
        """Cancel-button handler: drop the running scan's result and reset
        to idle with a blank list."""
        self._text_scan_id += 1
        t0, self._scan_t0 = self._scan_t0, None
        if t0 is not None:
            self.log("Text scan cancelled after %.1f s."
                     % (time.monotonic() - t0), "info")
        self.set(scanning=False, view=[], empty=EMPTY_CANCELLED)
        return True

    def _populate_after_scan(self, loaded, err, scan_id, scan_dir):
        if self._text_scan_id != scan_id:
            return
        self._end_scan()
        if err is not None:
            compat.messagebox.showerror(
                "Couldn't read text",
                "Couldn't read the on-screen-text manifest:\n%s" % err)
        rows = []
        for r in loaded:
            rep = r["replacement"]
            if rep == r["original"]:
                rep = ""                    # rep == orig => unchanged
            row = {"path": r["path"], "original": r["original"],
                   "replacement": rep}
            if r.get("budget"):
                row["budget"] = r["budget"]
            for flag in ("grow", "fixed", "unused"):
                if r.get(flag):
                    row[flag] = True
            rows.append(row)
        self._text_rows = rows
        if not _same_folder(scan_dir, self._text_scan_dir):
            # New folder: its filters and scene names come off its own
            # sidecar (the names are the Images tab's group tags).
            from ...core import staged_changes
            staged = staged_changes.load(scan_dir)
            self._suspend += 1
            try:
                self.text_change_filter_var.set("All")
                val = staged.get("text_change_filter")
                if val in R.CHANGE_FILTER_VALUES:
                    self.text_change_filter_var.set(val)
                elif "text_changed_only" in staged:
                    self.text_change_filter_var.set(
                        "Changed" if staged["text_changed_only"] else "All")
                tags = staged.get("image_group_tags")
                self._scene_names = (
                    {str(k): str(v).strip()[:50] for k, v in tags.items()
                     if str(v).strip()} if isinstance(tags, dict) else {})
                _seed_names_from_library(
                    scan_dir,
                    {R.scene_key(r["path"]) for r in rows
                     if R.row_is_scene(r)},
                    self._scene_names)
                saved = staged.get("text_scene_filter")
                self.text_scene_filter_var.set(
                    saved if isinstance(saved, str) and saved
                    else R.SCENE_ALL)
            finally:
                self._suspend -= 1
        self._text_scan_dir = scan_dir
        self._clear_edit_panel()
        self._refresh_list(rebuild_rows=True)
        self.set(empty=EMPTY_NONE if not rows else "")

    # ------------------------------------------------------------------
    # the list
    # ------------------------------------------------------------------
    def _scene_name(self, path):
        if not (path or "").lower().endswith(".radium"):
            return ""
        return self._scene_names.get(R.scene_key(path), "")

    def _row_view(self, r):
        return {"o": r["original"], "n": r["replacement"] or "",
                "mx": R.row_max_label(r), "sc": R.scene_label(r["path"]),
                "nm": self._scene_name(r["path"]), "ed": R.is_edited(r),
                "sf": R.row_is_scene(r)}

    def _rebuild_scene_menu(self):
        values, by_display = R.scene_menu(self._text_rows, self._scene_names)
        self._scene_choices = by_display
        self._scene_displays = {p: d for d, p in by_display.items()}
        self.set(scene_options=values)

    def _scene_selection(self):
        choice = (self.text_scene_filter_var.get() or "").strip()
        if not choice or choice == R.SCENE_ALL:
            return None
        if choice == R.SCENE_PROGRAM:
            return R.SCENE_PROGRAM
        return self._scene_choices.get(choice)

    def _on_filter_var(self, *_a):
        if not self._suspend:
            self._refresh_list()

    def _refresh_list(self, rebuild_rows=False, changed=None):
        """Apply the search box + the Show / Scene filters and the sort.
        *rebuild_rows* re-sends every row (a scan, a rename); *changed* is
        a list of row indices whose cells changed (an edit)."""
        self._rebuild_scene_menu()
        choice = (self.text_scene_filter_var.get() or "").strip()
        scene = self._scene_selection()
        if scene is None and choice and choice != R.SCENE_ALL:
            # A saved scene this folder doesn't have: fall back to All
            # rather than an inexplicably empty list.
            self._suspend += 1
            try:
                self.text_scene_filter_var.set(R.SCENE_ALL)
            finally:
                self._suspend -= 1
        rows = self._text_rows
        if rows and self.get("empty") == EMPTY_CANCELLED:
            self.set(empty="")
        if rebuild_rows:
            self.set(rows=[self._row_view(r) for r in rows])
        elif changed:
            for i in changed:
                if 0 <= i < len(rows):
                    self.set_item("rows", i, self._row_view(rows[i]))
        query = (self.text_search_var.get() or "").strip().lower()
        mode = self.text_change_filter_var.get()
        want_changed = (mode == "Changed") if mode in (
            "Changed", "Unchanged") else None
        total = len(rows)
        edited = sum(1 for r in rows if R.is_edited(r))
        col, desc = self._sort

        def _key(i):
            r = rows[i]
            if col == "new":
                return ((r["replacement"] or "").lower(),
                        r["original"].lower())
            if col == "max":
                return (R.row_budget(r),)
            if col == "scene":
                return (R.scene_label(r["path"]).lower(),
                        r["original"].lower())
            if col == "name":
                name = self._scene_name(r["path"])
                return (not name, name.lower(), r["original"].lower())
            return (r["original"].lower(),)

        visible = [i for i, r in enumerate(rows)
                   if R.row_matches(r, query, want_changed, scene)]
        visible.sort(key=_key, reverse=desc)
        shown = len(visible)
        if total == 0:
            status = ""
        else:
            extra = "  (%d shown)" % shown if shown != total else ""
            status = "%d string(s), %d edited%s" % (total, edited, extra)
        self.text_status_var.set(status)
        self.set(view=visible, total=total, edited=edited,
                 sort={"col": col, "desc": desc})

    @rpc
    def sort_by(self, col):
        """Header click: sort on *col*, or flip the direction."""
        if col not in SORT_COLS:
            return False
        cur, desc = self._sort
        self._sort = (col, not desc) if col == cur else (col, SORT_COLS[col])
        self._refresh_list()
        return True

    @rpc
    def set_show(self, mode):
        """Show: All / Changed / Unchanged (persisted to the sidecar)."""
        if mode not in R.CHANGE_FILTER_VALUES:
            return False
        self.text_change_filter_var.set(mode)
        self._save_filters()
        return True

    @rpc
    def set_scene(self, display):
        """Scene: All / Game program / one scene (persisted)."""
        self.text_scene_filter_var.set(display or R.SCENE_ALL)
        self._save_filters()
        return True

    def _save_filters(self):
        """Tk ``_save_staged_changes``, the Text part: its two view filters
        are folder state like every other tab's."""
        from ...core import staged_changes
        assets_dir = self._assets_path()
        if not assets_dir or not os.path.isdir(assets_dir):
            return
        if not _same_folder(self._text_scan_dir, assets_dir):
            return
        data = staged_changes.load(assets_dir)
        data["text_change_filter"] = self.text_change_filter_var.get()
        data["text_scene_filter"] = self.text_scene_filter_var.get()
        staged_changes.save(assets_dir, data)
        cb = self.window.cb.get("on_folder_state_written")
        if cb is not None:
            cb(assets_dir)

    # ------------------------------------------------------------------
    # the editor
    # ------------------------------------------------------------------
    def _row(self, index):
        try:
            i = int(index)
        except (TypeError, ValueError):
            return None, None
        if 0 <= i < len(self._text_rows):
            return i, self._text_rows[i]
        return None, None

    @rpc
    def select(self, index):
        """A row was selected: fill the editor from it."""
        i, r = self._row(index)
        if r is None:
            return False
        self._current = i
        if R.row_is_scene(r):
            note = R.scene_note(r, self._scene_name(r["path"]))
        else:
            note = R.program_note(r)
        # Pre-fill with the current effective text so the user edits from
        # what's shown today.
        self.set(sel=i, orig=r["original"], scene_note=note, can_edit=True,
                 sel_edited=R.is_edited(r))
        self.text_new_var.set(r["replacement"] or r["original"])
        self._update_budget()
        return True

    def _clear_edit_panel(self):
        self._current = None
        self.text_new_var.set("")
        self.text_budget_var.set("")
        self.set(sel=None, orig="", scene_note="", can_edit=False,
                 budget_over=False, sel_edited=False)

    def _update_budget(self):
        i, r = self._row(self._current)
        if r is None:
            self.text_budget_var.set("")
            self.set(budget_over=False)
            return
        text, over = R.budget_readout(r, self.text_new_var.get())
        self.text_budget_var.set(text)
        self.set(budget_over=over)

    @rpc
    def apply(self, new=None):
        """Apply (or Return in the New text box)."""
        if new is not None:
            self.text_new_var.set(new)
        i, r = self._row(self._current)
        if r is None:
            return False
        orig = r["original"]
        new = self.text_new_var.get()
        if R.row_len(r, new) > R.row_budget(r):
            compat.messagebox.showwarning("Replacement too long",
                                          R.too_long_message(r, new))
            return False
        eff = "" if new == orig else new
        if self.text_apply_all_var.get():
            targets = [rr for rr in self._text_rows if rr["original"] == orig]
        else:
            targets = [r]
        self._set_replacements([(rr, eff) for rr in targets])
        return True

    def _set_replacements(self, changes):
        """The one way an edit lands: set each ``(row, effective)``, save the
        manifest once, record history + log, refresh the list."""
        from ...core import history_log
        groups, order = {}, []
        index_of = {id(rr): n for n, rr in enumerate(self._text_rows)}
        touched = []
        for rr, eff in changes:
            prev = rr.get("replacement") or ""
            rr["replacement"] = eff
            touched.append(index_of.get(id(rr), -1))
            key = (rr["original"], eff)
            if key not in groups:
                groups[key] = {"prev": prev, "n": 0, "changed": False}
                order.append(key)
            groups[key]["n"] += 1
            if eff != prev:
                groups[key]["changed"] = True
        self._save_text_manifest()
        events = []
        for key in order:
            orig, eff = key
            g = groups[key]
            if not g["changed"]:
                continue
            copies = ("  (%d copies)" % g["n"]) if g["n"] > 1 else ""
            was = ('  (was: "%s")' % g["prev"]) if g["prev"] else ""
            events.append(
                ('text  "%s"  changed to: "%s"%s%s' % (orig, eff, was, copies))
                if eff else
                ('text  "%s"  reverted to original%s%s' % (orig, was, copies)))
            if eff:
                self.log('Replace Text: "%s" → "%s"%s'
                         % (R.ellipsize(orig), R.ellipsize(eff),
                            " (%d copies)" % g["n"] if g["n"] > 1 else ""),
                         "info")
        if events:
            history_log.record(self._text_scan_dir, events)
        self._refresh_list(changed=touched)
        i, r = self._row(self._current)
        if r is not None:
            self.set(sel_edited=R.is_edited(r))
        self._update_budget()

    @rpc
    def revert(self):
        """Revert the selected string (and same-text siblings when 'apply to
        every scene' is ticked) back to its original."""
        i, r = self._row(self._current)
        if r is None:
            return False
        orig = r["original"]
        prev = r.get("replacement") or ""
        if self.text_apply_all_var.get():
            targets = [(n, rr) for n, rr in enumerate(self._text_rows)
                       if rr["original"] == orig]
        else:
            targets = [(i, r)]
        for _n, rr in targets:
            rr["replacement"] = ""
        self._save_text_manifest()
        if prev:
            from ...core import history_log
            history_log.record(
                self._text_scan_dir,
                'text  "%s"  reverted to original  (was: "%s")%s'
                % (orig, prev,
                   "  (%d copies)" % len(targets) if len(targets) > 1 else ""))
        self.log('Replace Text: reverted "%s"%s'
                 % (R.ellipsize(orig),
                    " (%d copies)" % len(targets) if len(targets) > 1 else ""),
                 "info")
        self.text_new_var.set(orig)
        self._refresh_list(changed=[n for n, _rr in targets])
        self.set(sel_edited=False)
        self._update_budget()
        return True

    @rpc
    def clear_all(self):
        """Clear all edits (asks first)."""
        n_edited = sum(1 for r in self._text_rows if r["replacement"])
        if not n_edited:
            return False
        if not compat.messagebox.askyesno(
                "Clear all edits",
                "Remove every on-screen-text edit and restore the originals?"):
            return False
        changed = [n for n, r in enumerate(self._text_rows)
                   if r["replacement"]]
        for r in self._text_rows:
            r["replacement"] = ""
        self._save_text_manifest()
        self.log("Replace Text: cleared all %d edit(s)" % n_edited, "info")
        self._refresh_list(changed=changed)
        i, r = self._row(self._current)
        if r is not None:
            self.text_new_var.set(r["original"])
            self.set(sel_edited=False)
        self._update_budget()
        return True

    def _save_text_manifest(self):
        """Persist the full row set to text/strings.tsv (the manifest is the
        model: Write re-reads it).  Returns the edited-string count."""
        from ...core import text_manifest
        if not self._text_scan_dir:
            return 0
        try:
            text_manifest.save(self._text_scan_dir, self._text_rows)
            cb = self.window.cb.get("on_folder_state_written")
            if cb is not None:
                cb(self._text_scan_dir)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror(
                "Couldn't save",
                "Couldn't write the on-screen-text manifest:\n%s" % e)
            return 0
        self._refresh_scene_browser_text()
        return sum(1 for r in self._text_rows if R.is_edited(r))

    def _refresh_scene_browser_text(self):
        """Keep an open Scenes window in step with an edit here."""
        try:
            if self.scenes.is_open() and _same_folder(
                    self.scenes.assets_dir, self._text_scan_dir):
                self.scenes.text_edits_changed()
        except Exception:                            # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Replace everywhere…
    # ------------------------------------------------------------------
    @rpc
    def replace_open(self, index=None):
        """Open the Find / Replace dialog: returns its pre-fill, or None
        (after saying why) when there is nothing to search."""
        if not self._text_rows:
            compat.messagebox.showinfo(
                "Replace everywhere",
                "Scan the project folder first — there are no strings to "
                "search yet.")
            return None
        find, repl = "", ""
        if index is None:
            index = self._current
        i, r = self._row(index)
        if r is not None:
            typed = (self.text_new_var.get() if i == self._current
                     else (r["replacement"] or ""))
            pair = R.split_edit(r["original"], typed)
            if pair is None and r["replacement"]:
                pair = R.split_edit(r["original"], r["replacement"])
            if pair is not None:
                find, repl = pair
            else:
                find = r["original"]
        return {"find": find, "repl": repl}

    MAX_LISTED = 200

    @rpc
    def replace_plan(self, find, repl, case=True):
        """The dialog's live readout: count line, Apply enable, misfits."""
        plan = R.replace_plan(self._text_rows, find or "", repl or "",
                              bool(case))
        fits = [p for p in plan if p["fits"]]
        n, m = len(fits), len(plan)
        already = sum(1 for p in fits
                      if p["row"].get("replacement")
                      and p["row"]["replacement"] != p["new"])
        if not find:
            text = "Type the word to look for."
        else:
            text = "%d of %d matching rows fit" % (n, m)
            if m and n < m:
                text += " — %d listed below would not, and will be skipped" \
                        % (m - n)
            if already:
                text += " (%d already edited: their edit is replaced)" \
                        % already
        misfits = [p for p in plan if not p["fits"]]
        rows = [{"o": p["row"]["original"], "n": p["new"],
                 "b": R.row_len(p["row"], p["new"]),
                 "mx": R.row_max_label(p["row"]),
                 "sc": R.scene_label(p["row"]["path"])}
                for p in misfits[:self.MAX_LISTED]]
        return {"text": text, "can_apply": bool(n), "misfits": rows,
                "more": max(0, len(misfits) - self.MAX_LISTED)}

    @rpc
    def replace_apply(self, find, repl, case=True):
        """Apply: land every fitting row through the per-row path, then name
        the skipped rows.  Returns ``{applied, skipped}`` or None."""
        plan = R.replace_plan(self._text_rows, find or "", repl or "",
                              bool(case))
        fits = [p for p in plan if p["fits"]]
        if not fits:
            return None
        skipped = [p for p in plan if not p["fits"]]
        self._set_replacements(
            [(p["row"], "" if p["new"] == p["row"]["original"]
              else p["new"]) for p in fits])
        i, r = self._row(self._current)
        if r is not None:
            self.text_new_var.set(r["replacement"] or r["original"])
        if skipped:
            lines = []
            for p in skipped[:12]:
                lines.append("• %s → %s  (%d bytes, Max %d)" % (
                    p["row"]["original"], p["new"],
                    R.row_len(p["row"], p["new"]),
                    R.row_budget(p["row"])))
            if len(skipped) > 12:
                lines.append("… and %d more" % (len(skipped) - 12))
            compat.messagebox.showinfo(
                "Replace everywhere",
                "%d row(s) changed. %d row(s) were skipped because the new "
                "text would not fit their Max — shorten those by hand:\n\n%s"
                % (len(fits), len(skipped), "\n".join(lines)))
        return {"applied": len(fits), "skipped": len(skipped)}

    # ------------------------------------------------------------------
    # scene names
    # ------------------------------------------------------------------
    @rpc
    def rename_prompt(self, index=None):
        """Right-click → Name this scene…: what the name dialog asks, or
        None (after saying why) for a game-program row."""
        i, r = self._row(self._current if index is None else index)
        if r is None:
            return None
        path = r["path"] or ""
        if not path.lower().endswith(".radium"):
            compat.messagebox.showinfo(
                "Name this scene",
                "This is a game-program string — the game code draws it at "
                "runtime, so there's no scene file to name.")
            return None
        return {"index": i,
                "prompt": "A name for the scene %s\n(blank clears it):"
                          % R.scene_label(path),
                "value": self._scene_names.get(R.scene_key(path), "")}

    @rpc
    def set_scene_name(self, index, name):
        """Store (or clear, on a blank name) a scene's friendly name in the
        folder's sidecar, the same store the Images tab's group names use."""
        i, r = self._row(index)
        if r is None or not R.row_is_scene(r):
            return False
        name = " ".join((name or "").split())[:50]
        self._set_scene_name(R.scene_key(r["path"]), name)
        return True

    def _set_scene_name(self, key, name):
        from ...core import staged_changes
        was = self._scene_selection()
        if name:
            self._scene_names[key] = name
        else:
            self._scene_names.pop(key, None)
        scan_dir = self._text_scan_dir
        if scan_dir and os.path.isdir(scan_dir):
            data = staged_changes.load(scan_dir)
            tags = {str(k): str(v) for k, v in
                    (data.get("image_group_tags") or {}).items()
                    if str(v).strip()}
            if name:
                tags[key] = name
            else:
                tags.pop(key, None)
            data["image_group_tags"] = tags
            staged_changes.save(scan_dir, data)
            # Mirror into the per-card library, exactly as the Images tab's
            # rename does, so a fresh extract of the same card keeps it.
            try:
                from ...core import tag_library
                known = {R.scene_key(r["path"]) for r in self._text_rows
                         if R.row_is_scene(r)}
                known |= set(tags)
                tag_library.remember(scan_dir, tags, known)
            except Exception:                        # noqa: BLE001
                pass
            self._images_follow(scan_dir, tags)
        self._rebuild_scene_menu()
        # A rename rewrites the scene's own dropdown entry: follow it, so
        # filtering to a scene and naming it doesn't drop the filter.
        self._suspend += 1
        try:
            if was and was != R.SCENE_PROGRAM:
                display = self._scene_displays.get(was)
                if display and display != self.text_scene_filter_var.get():
                    self.text_scene_filter_var.set(display)
        finally:
            self._suspend -= 1
        self._refresh_list(rebuild_rows=True)

    def _images_follow(self, scan_dir, tags):
        """Tk ``_text_set_scene_name``: when the Images tab is on the same
        folder, its in-memory group names take the new set and its list
        redraws.  Without this its next sidecar save (any pick, any filter
        change) writes its stale names over ``image_group_tags`` and the
        name given here is lost again."""
        images = self.window.service("images")
        if images is None:
            return
        try:
            hook = getattr(images, "scene_names_changed", None)
            if hook is not None:
                hook(scan_dir, dict(tags))
                return
            if not _same_folder(getattr(images, "_scan_dir", ""), scan_dir):
                return
            images._group_tags = dict(tags)
            refresh = getattr(images, "_refresh_image_list", None)
            if refresh is not None:
                refresh()
        except Exception:                            # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("images scene names")

    # ------------------------------------------------------------------
    # column widths (dragged on the page; kept in settings.json under the
    # Tk tree's key and column ids, so the two versions share them)
    # ------------------------------------------------------------------
    _WIDTHS_KEY = "text"
    #: page column key -> Tk Treeview column id
    _WIDTH_IDS = {"o": "#0", "n": "new", "mx": "max", "sc": "scene",
                  "nm": "name"}

    def _all_widths(self):
        s = getattr(self.app, "_settings", None) if self.app else None
        widths = (s or {}).get("column_widths")
        if not isinstance(widths, dict):
            widths = dict(self.window.cb.get("initial_column_widths") or {})
        return widths

    def _saved_widths(self):
        """The saved widths as the page's column keys."""
        try:
            got = self._all_widths().get(self._WIDTHS_KEY) or {}
        except Exception:                            # noqa: BLE001
            got = {}
        out = {}
        for key, tk_id in self._WIDTH_IDS.items():
            v = got.get(tk_id) if isinstance(got, dict) else None
            if isinstance(v, (int, float)) and 20 <= v <= 4000:
                out[key] = int(v)
        return out

    @rpc
    def save_widths(self, widths):
        """The page's Table dragged a column edge: keep every width it
        reports (the last column takes what is left, as Tk's did)."""
        clean = {}
        for key, v in (widths or {}).items():
            tk_id = self._WIDTH_IDS.get(str(key))
            if tk_id and isinstance(v, (int, float)) and 20 <= v <= 4000:
                clean[tk_id] = int(v)
        allw = dict(self._all_widths())
        allw[self._WIDTHS_KEY] = clean
        self.set(col_widths={k: clean[t] for k, t in self._WIDTH_IDS.items()
                             if t in clean})
        cb = self.window.cb.get("on_column_widths_change")
        if cb is not None:
            cb(allw)
        return True

    # ------------------------------------------------------------------
    # the Scenes window
    # ------------------------------------------------------------------
    @rpc
    def show_in_scene(self, index=None):
        """Open the Scenes window on the scene that draws the row, with the
        line picked out."""
        i, r = self._row(self._current if index is None else index)
        if r is None:
            compat.messagebox.showinfo(
                "Scenes",
                "Pick a line of text first — the Scenes window then opens on "
                "the scene that draws it.")
            return False
        if not R.row_is_scene(r):
            compat.messagebox.showinfo(
                "Scenes",
                "This is a game-program string — the game code draws it at "
                "runtime, so there's no scene file to show. (It still writes "
                "to the card like any other text edit.)")
            return False
        scene_dir = (r["path"] or "").replace("\\", "/").rsplit("/", 1)[0]
        if not scene_dir:
            compat.messagebox.showinfo(
                "Scenes", "This string isn't recorded against a scene file.")
            return False
        return self._open_scene_browser(preselect_dir=scene_dir,
                                        focus_text=r["original"])

    def _open_scene_browser(self, preselect_rel=None, preselect_video=None,
                            preselect_dir=None, focus_text=None):
        """Tk ``_open_scene_browser``: the Scenes window, optionally on the
        scene holding an Images row / a Video row / a scene directory."""
        assets = self._assets_path()
        if not assets or not os.path.isdir(assets):
            compat.messagebox.showinfo(
                "Scenes", "Pick your extracted project folder first (Extract "
                          "tab) — the Scenes window works on an extracted "
                          "Stern Spike 2 card.")
            return False
        return self.scenes.open(assets, preselect_rel=preselect_rel,
                                preselect_video=preselect_video,
                                preselect_dir=preselect_dir,
                                focus_text=focus_text)

    def open_scene_browser(self, assets=None, preselect=None, focus_text=None,
                           preselect_rel=None, preselect_video=None,
                           preselect_dir=None):
        """``scene_browser.open_scene_browser`` for the other tabs: the
        Scenes window on *assets* (default: the project folder).  The page
        shows it wherever ``ScenesWindow`` (js/tabs/text_scenes.js) is
        rendered."""
        assets = assets or self._assets_path()
        if not assets or not os.path.isdir(assets):
            return self._open_scene_browser()      # says why
        return self.scenes.open(assets, preselect_rel=preselect_rel,
                                preselect_video=preselect_video,
                                preselect_dir=preselect_dir or preselect,
                                focus_text=focus_text)

    def open_font_studio(self, assets=None, preselect=None,
                         preselect_rel=None):
        """``font_studio.open_font_studio`` for the other tabs and the Scenes
        window: the Fonts window on *assets* (default: the project folder),
        optionally on font *preselect* (a table key) or the font owning the
        glyph slice at Images-tab row *preselect_rel*."""
        assets = assets or self._assets_path()
        if not assets or not os.path.isdir(assets):
            compat.messagebox.showinfo(
                "Fonts", "Pick your extracted project folder first (Extract "
                         "tab) — the Fonts window works on an extracted "
                         "Stern Spike 2 card.")
            return False
        return self.fonts.open(assets, preselect=preselect,
                               preselect_rel=preselect_rel)

    def _open_font_studio(self, preselect_rel=None):
        return self.open_font_studio(preselect_rel=preselect_rel)

    def reveal_text_string(self, text):
        """Scenes window: find one display string on this tab (clearing any
        filter that would hide it) and land on its row."""
        self.window.select_tab(self.ns)
        if not self._text_rows and self._text_scan_dir == "":
            self._scan_text_strings()
        self._suspend += 1
        try:
            self.text_change_filter_var.set("All")
            self.text_scene_filter_var.set(R.SCENE_ALL)
            self.text_search_var.set(text)
        finally:
            self._suspend -= 1
        self._refresh_list()
        for i, r in enumerate(self._text_rows):
            if r["original"] == text:
                self.select(i)
                self.set(focus_row=i)
                return True
        return False

    @rpc
    def open_folder(self):
        """Click on the project folder: open it in the file manager, or say
        plainly why there's nothing to open."""
        path = self._assets_path()
        if not path:
            compat.messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return False
        if not os.path.exists(path):
            compat.messagebox.showinfo(
                "Open folder", "This folder doesn't exist yet:\n%s" % path)
            return False
        try:
            reveal_in_file_manager(path)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, e))
            return False
        return True

    @rpc
    def scan(self):
        """The Scan button."""
        self._scan_text_strings()
        return True


def _same_folder(a, b):
    """True when two paths name the same folder (case/sep insensitive);
    both empty never matches."""
    if not a or not b:
        return False
    return (os.path.normcase(os.path.normpath(a))
            == os.path.normcase(os.path.normpath(b)))


def _seed_names_from_library(scan_dir, present_keys, tags):
    """Tk ``_seed_names_from_library``: merge the container names a previous
    extract of this same card was given into *tags* (in place) and persist
    anything new into the folder's sidecar.  Best effort."""
    try:
        from ...core import staged_changes, tag_library
        seeded = tag_library.seed_tags(scan_dir, present_keys)
        added = False
        for key, name in seeded.items():
            if key not in tags:
                tags[key] = name
                added = True
        if added:
            data = staged_changes.load(scan_dir)
            merged = dict(data.get("image_group_tags") or {})
            merged.update({k: v for k, v in tags.items() if v})
            data["image_group_tags"] = merged
            staged_changes.save(scan_dir, data)
        return added
    except Exception:                                # noqa: BLE001
        return False


TAB = TextTab
