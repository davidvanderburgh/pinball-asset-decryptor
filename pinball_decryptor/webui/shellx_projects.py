"""The Project menu's windows on the page: New project, Save project as
(fork), Project properties, Change history, Projects (the manager) and
Relink moved files.

A port of ``gui/projects_ui.py`` and ``MainWindow._open_change_history``: the
same ``core.project_file`` / ``project_ops`` / ``project_registry`` /
``relink`` calls, the same questions and wording.  The windows themselves are
page dialogs (``static/js/shellx_dialogs.js``); what they show and what their
buttons do lives here, on the ``shellx`` service (a mixin of it).
"""

import itertools
import logging
import os
import shutil
import threading
import time

from . import compat
from .rpc import rpc
from .shellx_common import (human_size, off_loop, open_in_text_viewer,
                            reveal, same_path)

log = logging.getLogger(__name__)

_BAD_NAME_CHARS = '<>:"/\\|?*'

MANAGER_NOTE = (
    "Remove from list never touches the folder.  Archive shrinks a dormant "
    "project to its unique bytes (edits, backups, notes); opening it later "
    "re-extracts to hydrate.  This list is only folders the app has opened "
    "or anchored — it never scans your disks.")


def _mb():
    return compat.messagebox


def _fd():
    return compat.filedialog


class ProjectsMixin:
    """Mixed into the ``shellx`` service (needs ``self.app``, ``self.window``,
    ``self.ctx``, ``self.set``, ``self.get``)."""

    def _projects_init(self):
        self._job_ids = itertools.count(1)
        self._jobs = {}
        self._relink = None
        self._pm_token = 0
        self._props_token = 0
        self.set(job=None, relink=None, pm_rows=[], pm_sizes={},
                 props=None)

    # ------------------------------------------------------------------
    # shared
    # ------------------------------------------------------------------
    def _running(self):
        try:
            return bool(self.window._is_running())
        except Exception:                               # noqa: BLE001
            return False

    def _active_folder(self):
        try:
            return self.app._project_folder() or ""
        except Exception:                               # noqa: BLE001
            return ""

    def _settings(self):
        return getattr(self.app, "_settings", {}) or {}

    def _start_job(self, title, text, fn, on_done):
        """projects_ui._ProgressDialog: ``fn(progress, cancel)`` on a worker,
        a progress window on the page (``shellx.job``) with Cancel, and
        ``on_done(result, error)`` back on the loop once it ends."""
        jid = next(self._job_ids)
        st = {"cancel": False, "last": 0.0, "frac": -1.0}
        self._jobs[jid] = st
        self.set(job={"id": jid, "title": title, "text": text,
                      "frac": 0.0, "detail": "", "cancelling": False})

        def progress(cur, total, text_=""):
            now = time.monotonic()
            frac = (cur / max(1, total)) if total else st["frac"]
            if (now - st["last"] < 0.1 and abs(frac - st["frac"]) < 0.01):
                return
            st["last"], st["frac"] = now, frac
            self.ctx.loop.post(self._job_progress, jid, frac, text_)

        def run():
            try:
                result, err = fn(progress, lambda: st["cancel"]), None
            except Exception as e:                      # noqa: BLE001
                log.exception("%s failed", title)
                result, err = None, e
            self.ctx.loop.post(self._job_done, jid, result, err, on_done)

        threading.Thread(target=run, name="pad-shellx-job",
                         daemon=True).start()
        return jid

    def _job_progress(self, jid, frac, text):
        job = self.get("job")
        if not job or job.get("id") != jid:
            return
        job = dict(job)
        if frac is not None and frac >= 0:
            job["frac"] = round(float(frac), 3)
        if text:
            job["detail"] = str(text)
        self.set(job=job)

    def _job_done(self, jid, result, err, on_done):
        self._jobs.pop(jid, None)
        job = self.get("job")
        if job and job.get("id") == jid:
            self.set(job=None)
        try:
            on_done(result, err)
        except Exception:                               # noqa: BLE001
            log.exception("job %s on_done", jid)
            self.window.append_log(
                "Internal error after %s; the details are in the session log."
                % (job or {}).get("title", "a project task"), "error")

    @rpc(loop=False)
    def job_cancel(self, jid):
        st = self._jobs.get(jid)
        if st is not None:
            st["cancel"] = True
            self.ctx.loop.post(self._job_cancelling, jid)
        return True

    def _job_cancelling(self, jid):
        job = self.get("job")
        if job and job.get("id") == jid:
            self.set(job=dict(job, cancelling=True))

    # ------------------------------------------------------------------
    # New project (projects_ui.new_project_dialog)
    # ------------------------------------------------------------------
    @rpc
    def project_form(self):
        """What the New project / Save as windows start from."""
        mfrs = []
        for m in getattr(self.app, "_manufacturers", ()) or ():
            exts = tuple(getattr(getattr(m, "input_spec", None),
                                 "extensions", ()) or ())
            mfrs.append({"key": m.key, "display": m.display,
                         "exts": list(exts)})
        cur = getattr(self.app, "_current_mfr", None)
        return {"parent": self._settings().get("project_dir") or "",
                "mfrs": mfrs,
                "mfr": cur.key if cur else (mfrs[0]["key"] if mfrs else ""),
                "running": self._running(),
                "sep": os.sep}

    @rpc
    def browse_location(self, current=""):
        p = _fd().askdirectory(
            title="Select the location the project folder will be created "
                  "in", initialdir=current or None)
        return os.path.normpath(p) if p else ""

    @rpc
    def browse_stock(self, mfr_key="", current=""):
        mfr = self._mfr_by_key(mfr_key)
        filetypes = [("All files", "*.*")]
        exts = tuple(getattr(getattr(mfr, "input_spec", None),
                             "extensions", ()) or ()) if mfr else ()
        if exts:
            filetypes.insert(0, ("%s image" % mfr.display,
                                 " ".join("*" + e for e in exts)))
        p = _fd().askopenfilename(
            title="Select the stock image (kept OUTSIDE the project — "
                  "shared, referenced)", filetypes=filetypes,
            initialdir=(os.path.dirname(current) if current else None))
        return os.path.normpath(p) if p else ""

    def _mfr_by_key(self, key):
        for m in getattr(self.app, "_manufacturers", ()) or ():
            if m.key == key:
                return m
        return None

    @rpc
    def project_new_create(self, parent, name, mfr_key, stock=""):
        """New project's Create: the checks and the clean slate of
        projects_ui.new_project_dialog.ok().  Returns {"ok": True} or
        {"error": text} (shown in the window, which stays open)."""
        from ..core import project_file
        if self._running():
            return {"error": "Wait for the running job to finish first."}
        parent = (parent or "").strip()
        name = (name or "").strip()
        stock = (stock or "").strip()
        mfr = self._mfr_by_key(mfr_key)
        if not parent or not os.path.isdir(parent):
            return {"error": "Pick a location that exists."}
        if not name or any(ch in name for ch in _BAD_NAME_CHARS):
            return {"error": "Enter a usable folder name."}
        if mfr is None:
            return {"error": "Pick a game."}
        if stock and not os.path.isfile(stock):
            return {"error": "The stock image doesn't exist:\n%s" % stock}
        folder = os.path.normpath(os.path.join(parent, name))
        if project_file.has_anchor(folder):
            return {"error": "That folder already contains a project — use "
                             "Open instead:\n%s" % folder}
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            return {"error": "Couldn't create the folder:\n%s" % e}
        app, win = self.app, self.window
        if app._current_mfr is not mfr:
            app._on_manufacturer_change(mfr)
            win.show_mfr_view()
        win.set_extract_options({})
        win.extract_input_var.set(stock)
        win.extract_output_var.set(folder)
        app._settings["project_dir"] = parent
        app._materialize_anchor(folder)
        app._save_settings()
        win.append_log("New project created: %s" % folder, "success")
        return {"ok": True, "folder": folder}

    # ------------------------------------------------------------------
    # Save project as (fork) (projects_ui.save_project_as)
    # ------------------------------------------------------------------
    @rpc
    def fork_form(self, folder=None):
        if self._running():
            return None
        src = os.path.normpath(folder or self._active_folder() or "")
        if not src or src == "." or not os.path.isdir(src):
            return None
        return {"src": src,
                "hint": os.path.basename(src.rstrip("\\/")) + " fork",
                "parent": self._settings().get("project_dir") or "",
                "sep": os.sep}

    @rpc
    def fork_start(self, src, parent, name):
        """Save as (fork) OK: the destination checks of _ask_new_folder, the
        size confirm, then the copy behind a progress window."""
        from ..core import project_file, project_ops
        if self._running():
            return {"error": "Wait for the running job to finish first."}
        parent = (parent or "").strip()
        name = (name or "").strip()
        if not parent or not os.path.isdir(parent):
            return {"error": "Pick a location that exists."}
        if not name or any(ch in name for ch in _BAD_NAME_CHARS):
            return {"error": "Enter a usable folder name."}
        dest = os.path.normpath(os.path.join(parent, name))
        if os.path.isdir(dest) and os.listdir(dest):
            return {"error": "That folder already exists and isn't empty:\n%s"
                             % dest}
        src = os.path.normpath(src or "")
        if not src or not os.path.isdir(src) or same_path(dest, src):
            return {"ok": True}
        build_dir = project_file.project_build_dir(src)
        size = off_loop(self.ctx, project_ops.fork_size, src, build_dir)
        if not _mb().askyesno(
                "Save project as",
                "This copies the project's current state (%s) to:\n%s\n\n"
                "The build output isn't copied — the fork rebuilds its own.\n"
                "Continue?" % (human_size(size), dest)):
            return {"ok": True, "cancelled": True}

        def work(progress, cancel):
            return project_ops.fork_copy(src, dest, build_dir=build_dir,
                                         progress=progress, cancel=cancel)

        def done(result, error):
            app, win = self.app, self.window
            if error is not None:
                shutil.rmtree(dest, ignore_errors=True)
                _mb().showerror("Save project as",
                                "The copy failed:\n%s" % error)
                return
            copied, nbytes, cancelled = result
            if cancelled:
                shutil.rmtree(dest, ignore_errors=True)
                win.append_log("Fork cancelled — nothing kept.", "info")
                return
            project_file.update_anchor(dest, build_dir="")
            win.append_log("Project forked: %d file(s), %s → %s"
                           % (copied, human_size(nbytes), dest), "success")
            app._registry_touch(dest)
            app._save_settings()
            self._projects_changed()
            app._open_project_folder_checked(dest)

        self._start_job("Save project as", "Copying project to %s…" % dest,
                        work, done)
        return {"ok": True, "started": True}

    # ------------------------------------------------------------------
    # Project properties (projects_ui.open_properties)
    # ------------------------------------------------------------------
    @rpc
    def properties_state(self, folder=None):
        from ..core import project_file
        from ..core.registry import get_manufacturer
        target = os.path.normpath(folder or self._active_folder() or "")
        if not target or target == "." or not os.path.isdir(target):
            return None
        anchored = project_file.has_anchor(target)
        data = {}
        if anchored:
            try:
                data = project_file.load_anchor(target)
            except (OSError, ValueError):
                data = {}
        is_active = same_path(target, self._active_folder())
        mfr = get_manufacturer(data.get("manufacturer", "")) if data else None
        cur = getattr(self.app, "_current_mfr", None)
        game = (mfr.display if mfr else
                (cur.display if is_active and cur else "—"))
        stock = data.get("stock_image") or (
            self.window.extract_input_var.get().strip() if is_active else "—")
        build_dir = project_file.project_build_dir(target, data or None)
        self._props_token += 1
        token = self._props_token
        self.set(props={"folder": target, "sizes": "Measuring sizes…"})

        def fill_sizes():
            from ..core import project_ops
            try:
                sizes = project_ops.project_sizes(target, build_dir=build_dir)
                text = ("Extraction %s   ·   Build %s   ·   Mod backups %s"
                        % (human_size(sizes["assets"]),
                           human_size(sizes["build"]),
                           human_size(sizes["mods"])))
            except Exception as e:                      # noqa: BLE001
                text = "Couldn't measure the sizes: %s" % e
            self.ctx.loop.post(self._props_sizes, token, target, text)

        threading.Thread(target=fill_sizes, name="pad-shellx-sizes",
                         daemon=True).start()
        return {"folder": target, "anchored": anchored, "game": game,
                "stock": stock or "—", "build_dir": build_dir,
                "saved_with": data.get("saved_with") or "—",
                "notes": data.get("notes") or "",
                "archived": bool(data.get("archived")),
                "is_active": is_active}

    def _props_sizes(self, token, target, text):
        if token == self._props_token:
            self.set(props={"folder": target, "sizes": text})

    @rpc
    def open_folder_link(self, folder):
        """A path shown as a link: open it in the file browser, or say it
        does not exist yet."""
        if folder and os.path.isdir(folder):
            reveal(folder)
        else:
            _mb().showinfo("Open folder",
                           "This folder doesn't exist yet:\n%s" % folder)
        return True

    @rpc
    def properties_delete_build(self, folder):
        from ..core import project_file, project_ops
        build_dir = project_file.project_build_dir(folder)
        if not os.path.isdir(build_dir):
            _mb().showinfo("Delete build", "No build output to delete.")
            return False
        freed = off_loop(self.ctx, project_ops.dir_size, build_dir)
        if _mb().askyesno(
                "Delete build",
                "Delete the build output (%s)?  A build is always "
                "regenerable from the project + stock image."
                % human_size(freed)):
            shutil.rmtree(build_dir, ignore_errors=True)
            self.window.append_log("Build deleted: %s freed (%s)"
                                   % (human_size(freed), build_dir),
                                   "success")
            return True
        return False

    @rpc
    def properties_change_build(self, folder):
        from ..core import project_file
        p = _fd().askdirectory(title="Select build output folder")
        if not p:
            return False
        p = os.path.normpath(p)
        default = os.path.normpath(os.path.join(folder, "build"))
        project_file.update_anchor(folder,
                                   build_dir=("" if p == default else p))
        if same_path(folder, self._active_folder()):
            self.window.write_output_var.set(p)
        return True

    @rpc
    def properties_save_notes(self, folder, notes):
        """Close: keep the notes typed (anchored projects only)."""
        from ..core import project_file
        if not folder or not project_file.has_anchor(folder):
            return False
        try:
            data = project_file.load_anchor(folder)
        except (OSError, ValueError):
            data = {}
        new_notes = (notes or "").rstrip("\n")
        if new_notes != (data.get("notes") or ""):
            project_file.update_anchor(folder, notes=new_notes)
            return True
        return False

    # ------------------------------------------------------------------
    # Archive (projects_ui._archive_flow)
    # ------------------------------------------------------------------
    @rpc
    def project_archive(self, target):
        """Confirm, then archive behind a progress window.  Returns True when
        the archive started."""
        from ..core import project_file, project_ops
        if self._running() or not target:
            return False
        is_active = same_path(target, self._active_folder())
        msg = ("Archiving deletes the extracted files that still match the "
               "stock baseline, plus the build output.  Your edited files, "
               "revert backups and notes stay.\n\nOpening the project later "
               "re-extracts to hydrate it.")
        if is_active:
            msg += ("\n\nThis project is currently open, so archiving also "
                    "closes it — the tabs empty until you open or extract "
                    "another project.")
        if not _mb().askyesno("Archive project", msg + "\n\nContinue?"):
            return False
        build_dir = project_file.project_build_dir(target)

        def work(progress, cancel):
            return project_ops.archive(target, build_dir=build_dir,
                                       progress=progress, cancel=cancel)

        def done(result, error):
            if error is not None:
                _mb().showerror("Archive project",
                                "Archiving failed:\n%s" % error)
                return
            deleted, freed, cancelled = result
            self.window.append_log(
                "Project archived%s: %d file(s) removed, %s freed — %s"
                % (" (cancelled part-way; still safe)" if cancelled else "",
                   deleted, human_size(freed), target),
                "info" if cancelled else "success")
            if is_active:
                self.app._close_active_project()
            self._projects_changed()

        self._start_job("Archive project",
                        "Verifying + removing pristine files…", work, done)
        return True

    # ------------------------------------------------------------------
    # Change history (MainWindow._open_change_history)
    # ------------------------------------------------------------------
    @rpc
    def change_history(self):
        """Project ▾ → Change history…: the folder's .history.log in a window
        (with the OS viewer one click away), or why there is none yet."""
        from ..core import history_log
        assets_dir = self._active_folder()
        if not assets_dir:
            return False
        path = history_log.path_for(assets_dir)
        if not os.path.isfile(path):
            _mb().showinfo(
                "Change history",
                "Nothing recorded for this folder yet.\n\nFrom now on, every "
                "replacement pick (with what it replaced), text edit, staged "
                "default, build and revert is appended with a timestamp "
                "to:\n\n%s" % path)
            return False
        self.ctx.bus.publish("open_dialog", name="project_history",
                             props={"path": path})
        return True

    @rpc(loop=False)
    def read_text_tail(self, path, max_lines=4000):
        """The last lines of a log file for an in-page viewer."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            return {"error": "Couldn't open %s:\n%s" % (path, e), "lines": []}
        total = len(lines)
        return {"lines": lines[-int(max_lines):], "total": total,
                "path": path}

    @rpc
    def open_in_viewer(self, path):
        open_in_text_viewer(path)
        return True

    # ------------------------------------------------------------------
    # Projects… manager (projects_ui.open_manager)
    # ------------------------------------------------------------------
    def _projects_changed(self):
        self.ctx.bus.publish("shellx_projects_changed")

    @rpc
    def manager_refresh(self):
        from ..core import project_file, project_registry
        from ..core.registry import get_manufacturer
        rows = []
        for ent in project_registry.entries(self._settings()):
            folder = ent["folder"]
            missing = not os.path.isdir(folder)
            anchored = (not missing) and project_file.has_anchor(folder)
            archived = False
            game = ent.get("manufacturer", "")
            if anchored:
                try:
                    data = project_file.load_anchor(folder)
                    archived = bool(data.get("archived"))
                    game = data.get("manufacturer") or game
                except (OSError, ValueError):
                    pass
            mfr = get_manufacturer(game)
            state = ("missing" if missing else "archived" if archived
                     else "" if anchored else "no anchor")
            rows.append({"folder": folder,
                         "game": mfr.display if mfr else game,
                         "size": "…" if not missing else "—",
                         "opened": ent.get("last_opened", ""),
                         "state": state, "missing": missing,
                         "anchored": anchored, "archived": archived})
        self._pm_token += 1
        token = self._pm_token
        self.set(pm_rows=rows, pm_sizes={}, pm_note=MANAGER_NOTE)

        def fill_sizes():
            from ..core import project_ops
            for r in rows:
                if r["missing"] or token != self._pm_token:
                    continue
                folder = r["folder"]
                try:
                    sizes = project_ops.project_sizes(
                        folder,
                        build_dir=project_file.project_build_dir(folder))
                    total = sizes["assets"] + sizes["build"] + sizes["mods"]
                    text = human_size(total)
                except Exception:                       # noqa: BLE001
                    text = "?"
                self.ctx.loop.post(self._pm_size, token, folder, text)

        threading.Thread(target=fill_sizes, name="pad-shellx-pmsizes",
                         daemon=True).start()
        return rows

    def _pm_size(self, token, folder, text):
        if token != self._pm_token:
            return
        sizes = dict(self.get("pm_sizes") or {})
        sizes[folder] = text
        self.set(pm_sizes=sizes)

    def _pm_row(self, folder):
        for r in self.get("pm_rows") or []:
            if r["folder"] == folder:
                return r
        return None

    @rpc
    def manager_open(self, folder):
        ent = self._pm_row(folder)
        if not ent or ent["missing"]:
            return False
        if ent["anchored"]:
            self.app._open_project_folder_checked(ent["folder"])
        else:
            self.window.extract_output_var.set(ent["folder"])
            self.window.append_log(
                "Folder set as project folder: %s" % ent["folder"], "info")
        return True

    @rpc
    def manager_reveal(self, folder):
        ent = self._pm_row(folder)
        if ent and not ent["missing"]:
            reveal(ent["folder"])
        return True

    @rpc
    def manager_remove(self, folder):
        from ..core import project_registry
        if not self._pm_row(folder):
            return False
        project_registry.remove(self.app._settings, folder)
        self.app._save_settings()
        self.manager_refresh()
        self._refresh_recents()
        return True

    @rpc
    def manager_locate(self, folder):
        from ..core import project_registry
        if not self._pm_row(folder):
            return False
        p = _fd().askdirectory(title="Where did this project move to?")
        if not p:
            return False
        project_registry.relocate(self.app._settings, folder,
                                  os.path.normpath(p))
        self.app._save_settings()
        self.manager_refresh()
        self._refresh_recents()
        return True

    def _refresh_recents(self):
        fn = getattr(self.app, "_publish_project", None)
        if fn is not None:
            try:
                fn()
            except Exception:                           # noqa: BLE001
                log.exception("publish project")

    # ------------------------------------------------------------------
    # Relink moved files (projects_ui.open_relink)
    # ------------------------------------------------------------------
    @rpc
    def relink_open(self, folder=None):
        """The window's first look: None (and an info box) when the project
        records no replacements, else the state it shows."""
        from ..core import relink, staged_changes
        target = os.path.normpath(folder or self._active_folder() or "")
        if not target or target == "." or not os.path.isdir(target):
            return None
        if not relink.recorded_sources(staged_changes.load(target)):
            _mb().showinfo(
                "Relink moved files",
                "This project has no recorded replacements yet, so there is "
                "nothing to re-point.\n\n%s" % target)
            return None
        self._relink = {"target": target, "missing": {}, "result": None,
                        "cancel": False, "busy": False}
        self._relink_refresh_missing()
        return self.get("relink")

    def _relink_publish(self, **kw):
        cur = dict(self.get("relink") or {})
        cur.update(kw)
        self.set(relink=cur)

    def _relink_refresh_missing(self):
        from ..core import relink, staged_changes
        st = self._relink
        target = st["target"]
        data = staged_changes.load(target)
        st["missing"] = relink.missing_sources(data)
        st["result"] = None
        n_all = len(relink.recorded_sources(data))
        n_gone = len(st["missing"])
        rows = []
        root_now = (self.get("relink") or {}).get("root") or ""
        if not n_gone:
            self.set(relink={
                "target": target, "busy": False, "rows": [],
                "head": ("All %d replacement file(s) this project records "
                         "are reachable on this PC. Nothing to re-point."
                         % n_all),
                "status": target, "root": root_now, "can_apply": False,
                "apply_label": "Relink", "done": True})
            return
        root = relink.common_root(list(st["missing"]))
        head = ("%d of this project's %d replacement file(s) are not on "
                "this PC, so they can't be applied. Pick the folder that "
                "holds them now: every slot using them is re-pointed in "
                "one pass, matched on the recorded file names. Nothing is "
                "copied, and a replacement still sitting where the project "
                "expects it is left alone." % (n_gone, n_all))
        status = (("Last seen in:  %s" % root) if root else
                  "These came from more than one drive, so do one folder at "
                  "a time. Whatever isn't found stays listed.")
        for path, slots in st["missing"].items():
            rows.append({"file": relink.file_name(path), "slots": len(slots),
                         "found": path, "path": path, "hit": False})
        if root and not root_now.strip():
            root_now = root
        self.set(relink={"target": target, "busy": False, "rows": rows,
                         "head": head, "status": status, "root": root_now,
                         "can_apply": False, "apply_label": "Relink",
                         "done": False})

    @rpc
    def relink_set_root(self, root):
        if self._relink is not None:
            self._relink_publish(root=root or "")
        return True

    @rpc
    def relink_browse(self):
        if self._relink is None:
            return ""
        p = _fd().askdirectory(
            title="The folder that holds these files now")
        if p:
            self._relink_publish(root=os.path.normpath(p))
            return os.path.normpath(p)
        return ""

    @rpc
    def relink_search(self, root=None):
        """Search (or Stop while a search runs)."""
        from ..core import relink, staged_changes
        st = self._relink
        if st is None:
            return False
        if st["busy"]:
            st["cancel"] = True
            self._relink_publish(status="Stopping...")
            return True
        if root is not None:
            self._relink_publish(root=root)
        root = ((self.get("relink") or {}).get("root") or "").strip()
        if not os.path.isdir(root):
            _mb().showwarning(
                "Relink moved files",
                "Pick the folder that holds the replacement files now.")
            return False
        st["cancel"] = False
        st["busy"] = True
        self._relink_publish(busy=True, can_apply=False,
                             status="Searching %s ..." % root)
        target = st["target"]

        def tick(seen, seen_in):
            if self._relink is not st:
                st["cancel"] = True
                return
            self.ctx.loop.post(
                self._relink_tick,
                st, "Searching %s ...  (%d file(s) seen)" % (seen_in, seen))

        def work():
            try:
                res = relink.plan(staged_changes.load(target), root,
                                  cancel=lambda: st["cancel"], progress=tick)
            except Exception as e:                      # noqa: BLE001
                res = e
            self.ctx.loop.post(self._relink_done, st, res)

        threading.Thread(target=work, name="pad-shellx-relink",
                         daemon=True).start()
        return True

    def _relink_tick(self, st, text):
        if self._relink is st and st["busy"] and not st["cancel"]:
            self._relink_publish(status=text)

    def _relink_done(self, st, res):
        from ..core import relink
        if self._relink is not st:
            return
        st["busy"] = False
        if isinstance(res, Exception):
            self._relink_publish(busy=False,
                                 status="The search failed: %s" % res)
            return
        st["result"] = res
        found, amb = res["found"], res["ambiguous"]
        rows = []
        for path, slots in st["missing"].items():
            new = found.get(path)
            extra = ""
            if new and path in amb:
                extra = ("   (%d files carry this name; the closest match)"
                         % amb[path])
            rows.append({"file": relink.file_name(path), "slots": len(slots),
                         "found": (new + extra) if new
                         else "not found under that folder",
                         "path": path, "hit": bool(new)})
        n_slots = sum(len(st["missing"][p]) for p in found)
        status = ("Found %d of %d file(s)%s, covering %d slot(s).%s"
                  % (len(found), len(st["missing"]),
                     " (search stopped early)" if res["cancelled"] else "",
                     n_slots,
                     "  Nothing is written until you click Relink."
                     if found else
                     "  Try the folder one level up, or the folder these "
                     "files were copied into."))
        self._relink_publish(
            busy=False, rows=rows, status=status, can_apply=bool(found),
            apply_label=("Relink %d file(s)" % len(found)) if found
            else "Relink")

    @rpc
    def relink_apply(self):
        from ..core import history_log, relink, staged_changes
        st = self._relink
        if st is None:
            return False
        res = st["result"]
        if not res or not res["found"]:
            return False
        target = st["target"]
        data = staged_changes.load(target)
        data, n_slots, _n_files = relink.apply_plan(data, res["found"])
        staged_changes.save(target, data)
        line = relink.summary_line(res, n_slots)
        history_log.record(target, [line])
        self.window.append_log(line, "success")
        if same_path(target, self._active_folder()):
            self.window.reload_assets_tabs()
        _mb().showinfo("Relink moved files", line)
        if self._relink is st:
            self._relink_refresh_missing()
        return True

    @rpc(loop=False)
    def relink_close(self):
        st = self._relink
        if st is not None:
            st["cancel"] = True
        self._relink = None
        self.ctx.loop.post(lambda: self.set(relink=None))
        return True
