"""Batch 19 project dialogs: New project, Save As (fork by copy), project
Properties, and the Projects… manager window.

All entry points take the App instance — these dialogs orchestrate across
the window, the settings-backed registry, and the folder anchors.  They are
imported lazily from app.py's menu handlers, so importing main_window here
is cycle-free.

Threaded operations (measuring, fork copy, archive, size fills) run behind
:class:`_ProgressDialog` or a daemon fill thread and post UI updates via
``widget.after`` — never from the worker thread directly.
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .main_window import THEMES, _SANS_FONT
from .theme import platform_font
from .widgets import center_over
from ..core import project_file, project_ops, project_registry
from ..core.registry import get_manufacturer

_MONO_FONT = platform_font()[1]


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit) if unit == "B"
                    else "%.1f %s" % (n, unit))
        n /= 1024.0


def _reveal(folder):
    """Open *folder* in the OS file browser (plain — no shell tricks)."""
    try:
        if sys.platform == "win32":
            os.startfile(folder)                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


def _theme(app):
    return THEMES[app.window._current_theme]


def _modal(app, title):
    """Start a modal Toplevel WITHDRAWN — it stays invisible while its
    widgets are built, then :func:`_present` centers it over the app and
    shows it (every modal centered over the app — David).  Building
    visible would flash the dialog at Tk's default position first."""
    win = tk.Toplevel(app.root)
    win.withdraw()
    win.title(title)
    win.transient(app.root)
    win.configure(bg=_theme(app)["bg"])
    win.resizable(False, False)
    return win


def _present(app, win):
    """Center a finished :func:`_modal` window over the app and show it.
    The grab happens HERE, not at creation — Tk refuses grabs on unmapped
    windows."""
    center_over(app.root, win)
    win.deiconify()
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass


class _ProgressDialog:
    """A small modal progress window: label + determinate bar + Cancel.

    Runs ``fn(progress, cancel)`` on a worker thread; *progress(cur, total,
    text)* updates the bar (thread-safe via a queue drained with ``after``),
    ``cancel()`` returns True once Cancel/× is clicked.  ``on_done(result,
    error)`` fires on the UI thread after the window closes."""

    def __init__(self, app, title, text, fn, on_done):
        self._win = _modal(app, title)
        self._q = queue.Queue()
        self._cancelled = False
        self._on_done = on_done
        c = _theme(app)
        tk.Label(self._win, text=text, bg=c["bg"], fg=c["fg"],
                 font=(_SANS_FONT, 10)).pack(padx=16, pady=(14, 6),
                                             anchor=tk.W)
        self._bar = ttk.Progressbar(self._win, length=380, maximum=1.0)
        self._bar.pack(padx=16, pady=2, fill=tk.X)
        self._detail = tk.Label(self._win, text="", bg=c["bg"], fg=c["gray"],
                                font=(_SANS_FONT, 8), anchor=tk.W)
        self._detail.pack(padx=16, pady=(0, 6), fill=tk.X)
        ttk.Button(self._win, text="Cancel", command=self._cancel).pack(
            pady=(2, 12))
        self._win.protocol("WM_DELETE_WINDOW", self._cancel)
        _present(app, self._win)

        def progress(cur, total, text_=""):
            self._q.put(("p", cur, total, text_))

        def run():
            try:
                result = fn(progress, lambda: self._cancelled)
                self._q.put(("done", result, None))
            except Exception as e:            # surfaced via on_done(error=)
                self._q.put(("done", None, e))

        threading.Thread(target=run, daemon=True).start()
        self._poll()

    def _cancel(self):
        self._cancelled = True

    def _poll(self):
        finished = None
        try:
            while True:
                item = self._q.get_nowait()
                if item[0] == "p":
                    _tag, cur, total, text = item
                    if total:
                        self._bar.configure(value=cur / max(1, total))
                    if text:
                        self._detail.configure(text=text)
                else:
                    finished = item
        except queue.Empty:
            pass
        if finished is None:
            try:
                self._win.after(80, self._poll)
            except tk.TclError:
                pass
            return
        try:
            self._win.grab_release()
            self._win.destroy()
        except tk.TclError:
            pass
        _tag, result, error = finished
        self._on_done(result, error)


def _ask_new_folder(app, title, name_hint=""):
    """The New-project / Save-As destination picker: parent location +
    subfolder name, with a live preview of the resulting path.  Returns the
    (not-yet-created) absolute path, or None."""
    win = _modal(app, title)
    c = _theme(app)
    out = {"path": None}

    parent_var = tk.StringVar(
        value=app._settings.get("project_dir") or "")
    name_var = tk.StringVar(value=name_hint)

    frm = tk.Frame(win, bg=c["bg"])
    frm.pack(padx=16, pady=12)

    tk.Label(frm, text="Location:", bg=c["bg"], fg=c["fg"], width=10,
             anchor=tk.W, font=(_SANS_FONT, 10)).grid(row=0, column=0,
                                                      sticky=tk.W, pady=3)
    ttk.Entry(frm, textvariable=parent_var, width=48).grid(
        row=0, column=1, pady=3)

    def browse():
        p = filedialog.askdirectory(title="Select the location the project "
                                          "folder will be created in",
                                    parent=win,
                                    initialdir=parent_var.get() or None)
        if p:
            parent_var.set(os.path.normpath(p))
    ttk.Button(frm, text="Browse...", command=browse).grid(
        row=0, column=2, padx=(6, 0), pady=3)

    tk.Label(frm, text="Folder name:", bg=c["bg"], fg=c["fg"], width=10,
             anchor=tk.W, font=(_SANS_FONT, 10)).grid(row=1, column=0,
                                                      sticky=tk.W, pady=3)
    ttk.Entry(frm, textvariable=name_var, width=48).grid(
        row=1, column=1, pady=3, sticky=tk.W)

    preview = tk.Label(win, text="", bg=c["bg"], fg=c["gray"],
                       font=(_SANS_FONT, 8))
    preview.pack(padx=16, anchor=tk.W)

    def refresh_preview(*_a):
        parent = (parent_var.get() or "").strip()
        name = (name_var.get() or "").strip()
        preview.configure(text=(os.path.join(parent, name)
                                if parent and name else ""))
    parent_var.trace_add("write", refresh_preview)
    name_var.trace_add("write", refresh_preview)
    refresh_preview()

    def ok():
        parent = (parent_var.get() or "").strip()
        name = (name_var.get() or "").strip()
        if not parent or not os.path.isdir(parent):
            messagebox.showerror(title, "Pick a location that exists.",
                                 parent=win)
            return
        if not name or any(ch in name for ch in '<>:"/\\|?*'):
            messagebox.showerror(title, "Enter a usable folder name.",
                                 parent=win)
            return
        path = os.path.normpath(os.path.join(parent, name))
        if os.path.isdir(path) and os.listdir(path):
            messagebox.showerror(
                title, "That folder already exists and isn't empty:\n%s"
                % path, parent=win)
            return
        out["path"] = path
        win.destroy()

    btns = tk.Frame(win, bg=c["bg"])
    btns.pack(pady=(8, 12))
    ttk.Button(btns, text="OK", command=ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(
        side=tk.LEFT, padx=4)
    _present(app, win)
    win.wait_window()
    return out["path"]


# ----------------------------------------------------------------------
# New project
# ----------------------------------------------------------------------

def new_project_dialog(app):
    """Project ▾ → New…: one small dialog, three questions — where the
    project folder goes, which manufacturer, which stock image.  OK resets
    the Extract options to that manufacturer's defaults, anchors the
    folder, and leaves the user ready to Extract (monkeybug: "no easy way
    of wiping out most of the settings")."""
    if app.window._is_running():
        return
    win = _modal(app, "New project")
    c = _theme(app)

    mfrs = list(app._manufacturers)
    display_by_key = {m.key: m.display for m in mfrs}
    mfr_var = tk.StringVar(
        value=(app._current_mfr.display if app._current_mfr
               else (mfrs[0].display if mfrs else "")))
    parent_var = tk.StringVar(value=app._settings.get("project_dir") or "")
    name_var = tk.StringVar()
    stock_var = tk.StringVar()

    frm = tk.Frame(win, bg=c["bg"])
    frm.pack(padx=16, pady=12)

    def _row(r, label):
        tk.Label(frm, text=label, bg=c["bg"], fg=c["fg"], width=12,
                 anchor=tk.W, font=(_SANS_FONT, 10)).grid(
            row=r, column=0, sticky=tk.W, pady=3)

    _row(0, "Location:")
    ttk.Entry(frm, textvariable=parent_var, width=46).grid(row=0, column=1,
                                                           pady=3)

    def browse_parent():
        p = filedialog.askdirectory(
            title="Select the location the project folder will be created "
                  "in", parent=win, initialdir=parent_var.get() or None)
        if p:
            parent_var.set(os.path.normpath(p))
    ttk.Button(frm, text="Browse...", command=browse_parent).grid(
        row=0, column=2, padx=(6, 0), pady=3)

    _row(1, "Folder name:")
    ttk.Entry(frm, textvariable=name_var, width=46).grid(
        row=1, column=1, pady=3, sticky=tk.W)

    _row(2, "Game:")
    combo = ttk.Combobox(frm, textvariable=mfr_var, state="readonly",
                         values=[m.display for m in mfrs], width=44)
    combo.grid(row=2, column=1, pady=3, sticky=tk.W)

    _row(3, "Stock image:")
    ttk.Entry(frm, textvariable=stock_var, width=46).grid(row=3, column=1,
                                                          pady=3)

    def _picked_mfr():
        for m in mfrs:
            if m.display == mfr_var.get():
                return m
        return None

    def browse_stock():
        mfr = _picked_mfr()
        filetypes = [("All files", "*.*")]
        exts = tuple(getattr(getattr(mfr, "input_spec", None), "extensions",
                             ()) or ())
        if exts:
            filetypes.insert(0, ("%s image" % mfr.display,
                                 " ".join("*" + e for e in exts)))
        p = filedialog.askopenfilename(
            title="Select the stock image (kept OUTSIDE the project — "
                  "shared, referenced)", parent=win, filetypes=filetypes,
            initialdir=(os.path.dirname(stock_var.get())
                        if stock_var.get() else None))
        if p:
            stock_var.set(os.path.normpath(p))
    ttk.Button(frm, text="Browse...", command=browse_stock).grid(
        row=3, column=2, padx=(6, 0), pady=3)

    # Live folder-structure preview (David): show exactly what gets built
    # on disk, as an example until the fields fill in.  Line COUNT is
    # constant and long paths are middle-ellipsized so the dialog's size
    # stays put while the user types.
    prev_title = tk.Label(win, text="", bg=c["bg"], fg=c["gray"],
                          font=(_SANS_FONT, 8))
    prev_title.pack(padx=16, pady=(8, 0), anchor=tk.W)
    prev = tk.Label(win, text="", bg=c["bg"], fg=c["fg"],
                    font=(_MONO_FONT, 8), justify=tk.LEFT, anchor=tk.W)
    prev.pack(padx=24, anchor=tk.W)

    def _ell(path, keep=52):
        return (path if len(path) <= keep
                else path[:22] + "…" + path[-(keep - 23):])

    def refresh_preview(*_a):
        parent = (parent_var.get() or "").strip()
        name = (name_var.get() or "").strip()
        stock = (stock_var.get() or "").strip()
        example = not (parent and name)
        p = parent or "D:\\pinball"
        n = name or "TMNT 1.59 upscale"
        s = stock or (p + "\\stock\\tmnt_1.59.raw")
        prev_title.configure(
            text=("Example — the structure a project gets:" if example
                  else "This will create:"))
        prev.configure(text="\n".join((
            _ell(p) + "\\",
            "└─ " + n + "\\               <- the project",
            "     ├─ audio\\ videos\\ …    extracted assets",
            "     ├─ build\\               the built card image",
            "     └─ .pinproj             project settings (hidden)",
            "",
            "stock image — stays OUTSIDE the project, shared:",
            "  " + _ell(s),
        )))
    parent_var.trace_add("write", refresh_preview)
    name_var.trace_add("write", refresh_preview)
    stock_var.trace_add("write", refresh_preview)
    refresh_preview()

    def ok():
        parent = (parent_var.get() or "").strip()
        name = (name_var.get() or "").strip()
        mfr = _picked_mfr()
        stock = (stock_var.get() or "").strip()
        if not parent or not os.path.isdir(parent):
            messagebox.showerror("New project",
                                 "Pick a location that exists.", parent=win)
            return
        if not name or any(ch in name for ch in '<>:"/\\|?*'):
            messagebox.showerror("New project",
                                 "Enter a usable folder name.", parent=win)
            return
        if mfr is None:
            messagebox.showerror("New project", "Pick a game.", parent=win)
            return
        if stock and not os.path.isfile(stock):
            messagebox.showerror("New project",
                                 "The stock image doesn't exist:\n%s"
                                 % stock, parent=win)
            return
        folder = os.path.normpath(os.path.join(parent, name))
        if project_file.has_anchor(folder):
            messagebox.showerror(
                "New project",
                "That folder already contains a project — use "
                "Open instead:\n%s" % folder, parent=win)
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror("New project",
                                 "Couldn't create the folder:\n%s" % e,
                                 parent=win)
            return
        win.destroy()
        if app._current_mfr is not mfr:
            app._on_manufacturer_change(mfr)
            app.window.show_mfr_view()
        # Clean slate: manufacturer defaults for every Extract option.
        app.window.set_extract_options({})
        app.window.extract_input_var.set(stock)
        app.window.extract_output_var.set(folder)
        app._settings["project_dir"] = parent
        app._materialize_anchor(folder)     # explicit action → anchor now
        app._save_settings()
        app.window.append_log("New project created: %s" % folder, "success")

    btns = tk.Frame(win, bg=c["bg"])
    btns.pack(pady=(8, 12))
    ttk.Button(btns, text="Create", command=ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(
        side=tk.LEFT, padx=4)
    _present(app, win)
    _ = display_by_key   # (kept for future key→display needs)


# ----------------------------------------------------------------------
# Save As — fork by literal copy
# ----------------------------------------------------------------------

def save_project_as(app, folder=None):
    """Project ▾ → Save As… (fork): a plain full copy of the project's
    current modified state — assets as edited in place, sidecars, .orig,
    notes — EXCLUDING build/ (an output; the fork rebuilds).  The size is
    shown before anything is copied so the disk cost is a visible choice.
    No links, no re-derivation: the fork is exactly what you were looking
    at (David)."""
    if app.window._is_running():
        return
    src = os.path.normpath(folder or app._project_folder())
    if not src or not os.path.isdir(src):
        return
    hint = os.path.basename(src.rstrip("\\/")) + " fork"
    dest = _ask_new_folder(app, "Save project as (fork)", name_hint=hint)
    if not dest:
        return
    if os.path.normcase(dest) == os.path.normcase(src):
        return

    build_dir = project_file.project_build_dir(src)
    size = project_ops.fork_size(src, build_dir=build_dir)
    if not messagebox.askyesno(
            "Save project as",
            "This copies the project's current state (%s) to:\n%s\n\n"
            "The build output isn't copied — the fork rebuilds its own.\n"
            "Continue?" % (_human_size(size), dest)):
        return

    def work(progress, cancel):
        return project_ops.fork_copy(src, dest, build_dir=build_dir,
                                     progress=progress, cancel=cancel)

    def done(result, error):
        if error is not None:
            shutil.rmtree(dest, ignore_errors=True)
            messagebox.showerror("Save project as",
                                 "The copy failed:\n%s" % error)
            return
        copied, nbytes, cancelled = result
        if cancelled:
            shutil.rmtree(dest, ignore_errors=True)
            app.window.append_log("Fork cancelled — nothing kept.", "info")
            return
        # The fork is its own project: fresh identity, and the build
        # override is cleared — two projects must never build to the same
        # file.
        project_file.update_anchor(dest, build_dir="")
        app.window.append_log(
            "Project forked: %d file(s), %s → %s"
            % (copied, _human_size(nbytes), dest), "success")
        app._registry_touch(dest)
        app._save_settings()
        # Save As means "continue in the copy".
        app._open_project_folder_checked(dest)

    _ProgressDialog(app, "Save project as",
                    "Copying project to %s…" % dest, work, done)


# ----------------------------------------------------------------------
# Properties
# ----------------------------------------------------------------------

def open_properties(app, folder=None):
    """Project properties: location, game, stock image, build location
    (override), notes, size breakdown, Delete build / Archive.  Targets the
    active project from the menu; the manager passes any row's folder."""
    target = os.path.normpath(folder or app._project_folder())
    if not target or not os.path.isdir(target):
        return
    anchored = project_file.has_anchor(target)
    data = {}
    if anchored:
        try:
            data = project_file.load_anchor(target)
        except (OSError, ValueError):
            data = {}
    is_active = (os.path.normcase(target)
                 == os.path.normcase(app._project_folder() or ""))

    win = _modal(app, "Project properties")
    c = _theme(app)
    frm = tk.Frame(win, bg=c["bg"])
    frm.pack(padx=16, pady=12, fill=tk.X)

    def _row(r, label, value, extra=None):
        tk.Label(frm, text=label, bg=c["bg"], fg=c["gray"], width=13,
                 anchor=tk.W, font=(_SANS_FONT, 9)).grid(
            row=r, column=0, sticky=tk.W, pady=2)
        tk.Label(frm, text=value, bg=c["bg"], fg=c["fg"],
                 font=(_SANS_FONT, 9), anchor=tk.W, wraplength=380,
                 justify=tk.LEFT).grid(row=r, column=1, sticky=tk.W, pady=2)
        if extra is not None:
            extra.grid(row=r, column=2, padx=(8, 0), pady=2)

    mfr = get_manufacturer(data.get("manufacturer", "")) if data else None
    reveal_btn = ttk.Button(frm, text="Reveal",
                            command=lambda: _reveal(target))
    _row(0, "Location:", target, reveal_btn)
    _row(1, "Game:", (mfr.display if mfr else
                      (app._current_mfr.display
                       if is_active and app._current_mfr else "—")))
    _row(2, "Stock image:", data.get("stock_image") or
         (app.window.extract_input_var.get().strip() if is_active else "—"))
    build_dir = project_file.project_build_dir(target, data or None)
    _row(3, "Build location:", build_dir)
    _row(4, "Saved with:", data.get("saved_with") or "—")

    size_lbl = tk.Label(win, text="Measuring sizes…", bg=c["bg"],
                        fg=c["gray"], font=(_SANS_FONT, 9))
    size_lbl.pack(padx=16, anchor=tk.W)

    def fill_sizes():
        sizes = project_ops.project_sizes(target, build_dir=build_dir)
        text = ("Extraction %s   ·   Build %s   ·   Mod backups %s"
                % (_human_size(sizes["assets"]),
                   _human_size(sizes["build"]),
                   _human_size(sizes["mods"])))
        try:
            size_lbl.after(0, lambda: size_lbl.configure(text=text))
        except tk.TclError:
            pass
    threading.Thread(target=fill_sizes, daemon=True).start()

    tk.Label(win, text="Notes:", bg=c["bg"], fg=c["gray"],
             font=(_SANS_FONT, 9)).pack(padx=16, anchor=tk.W, pady=(8, 0))
    notes = tk.Text(win, width=58, height=5, bg=c["bg"], fg=c["fg"],
                    insertbackground=c["fg"], font=(_SANS_FONT, 9),
                    wrap=tk.WORD)
    notes.pack(padx=16, pady=(2, 4))
    notes.insert("1.0", data.get("notes") or "")
    if not anchored:
        notes.configure(state=tk.DISABLED)
        tk.Label(win, text="(notes are stored in the project anchor — "
                           "extract or stage a change first)",
                 bg=c["bg"], fg=c["gray"], font=(_SANS_FONT, 8)).pack(
            padx=16, anchor=tk.W)

    def delete_build():
        if not os.path.isdir(build_dir):
            messagebox.showinfo("Delete build", "No build output to delete.",
                                parent=win)
            return
        freed = project_ops.dir_size(build_dir)
        if messagebox.askyesno(
                "Delete build",
                "Delete the build output (%s)?  A build is always "
                "regenerable from the project + stock image."
                % _human_size(freed), parent=win):
            shutil.rmtree(build_dir, ignore_errors=True)
            app.window.append_log(
                "Build deleted: %s freed (%s)"
                % (_human_size(freed), build_dir), "success")

    def change_build():
        p = filedialog.askdirectory(title="Select build output folder",
                                    parent=win)
        if not p:
            return
        p = os.path.normpath(p)
        default = os.path.normpath(os.path.join(target, "build"))
        project_file.update_anchor(
            target, build_dir=("" if p == default else p))
        if is_active:
            app.window.write_output_var.set(p)
        win.destroy()
        open_properties(app, target)      # reopen with fresh values

    def archive():
        _archive_flow(app, target, parent_win=win)

    btns = tk.Frame(win, bg=c["bg"])
    btns.pack(pady=(6, 12))
    ttk.Button(btns, text="Delete build", command=delete_build).pack(
        side=tk.LEFT, padx=4)
    if anchored:
        ttk.Button(btns, text="Change build location...",
                   command=change_build).pack(side=tk.LEFT, padx=4)
        if not data.get("archived"):
            ttk.Button(btns, text="Archive...", command=archive).pack(
                side=tk.LEFT, padx=4)

    def close():
        if anchored:
            new_notes = notes.get("1.0", tk.END).rstrip("\n")
            if new_notes != (data.get("notes") or ""):
                project_file.update_anchor(target, notes=new_notes)
        win.destroy()

    ttk.Button(btns, text="Close", command=close).pack(side=tk.LEFT, padx=4)
    win.protocol("WM_DELETE_WINDOW", close)
    _present(app, win)


def _archive_flow(app, target, parent_win=None, on_done=None):
    """Shared archive confirm + progress (Properties and the manager)."""
    if app.window._is_running():
        return
    is_active = (os.path.normcase(os.path.normpath(target))
                 == os.path.normcase(
                     os.path.normpath(app._project_folder() or "x")))
    if is_active:
        messagebox.showinfo(
            "Archive project",
            "This project is currently open — open a different project "
            "(or go back to the game picker) first, then archive it from "
            "Projects….", parent=parent_win)
        return
    if not messagebox.askyesno(
            "Archive project",
            "Archiving deletes the extracted files that still match the "
            "stock baseline, plus the build output.  Your edited files, "
            "revert backups and notes stay.\n\nOpening the project later "
            "re-extracts to hydrate it.  Continue?", parent=parent_win):
        return
    build_dir = project_file.project_build_dir(target)

    def work(progress, cancel):
        return project_ops.archive(target, build_dir=build_dir,
                                   progress=progress, cancel=cancel)

    def done(result, error):
        if error is not None:
            messagebox.showerror("Archive project",
                                 "Archiving failed:\n%s" % error)
            return
        deleted, freed, cancelled = result
        app.window.append_log(
            "Project archived%s: %d file(s) removed, %s freed — %s"
            % (" (cancelled part-way; still safe)" if cancelled else "",
               deleted, _human_size(freed), target),
            "info" if cancelled else "success")
        if on_done:
            on_done()

    _ProgressDialog(app, "Archive project",
                    "Verifying + removing pristine files…", work, done)


# ----------------------------------------------------------------------
# The Projects… manager
# ----------------------------------------------------------------------

_manager_win = [None]     # singleton, like the help window


def open_manager(app):
    """Projects…: every known project in one window — where "projects all
    over my filesystem" becomes a list you sort by size (David: collates
    and organizes).  Backed by the settings registry; never crawls disk."""
    existing = _manager_win[0]
    if existing is not None:
        try:
            existing.lift()
            existing.focus_force()
            return
        except tk.TclError:
            _manager_win[0] = None

    c = _theme(app)
    win = tk.Toplevel(app.root)
    win.withdraw()                    # shown centered once built (below)
    win.title("Projects")
    win.configure(bg=c["bg"])
    _manager_win[0] = win

    cols = ("project", "game", "size", "opened", "state")
    tree = ttk.Treeview(win, columns=cols, show="headings",
                        selectmode="browse")
    for col, title, width in (
            ("project", "Project", 300), ("game", "Game", 130),
            ("size", "Size on disk", 100), ("opened", "Last opened", 110),
            ("state", "State", 90)):
        tree.heading(col, text=title)
        tree.column(col, width=width, anchor=tk.W)
    tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

    note = tk.Label(win, text="", bg=c["bg"], fg=c["gray"],
                    font=(_SANS_FONT, 8), anchor=tk.W, wraplength=780,
                    justify=tk.LEFT)
    note.pack(fill=tk.X, padx=12)

    rows = {}         # item id -> entry dict

    def refresh():
        tree.delete(*tree.get_children())
        rows.clear()
        for ent in project_registry.entries(app._settings):
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
            state = ("missing" if missing
                     else "archived" if archived
                     else "" if anchored else "no anchor")
            iid = tree.insert("", tk.END, values=(
                folder, (mfr.display if mfr else game),
                "…" if not missing else "—",
                ent.get("last_opened", ""), state))
            rows[iid] = dict(ent, missing=missing, anchored=anchored,
                             archived=archived)
        threading.Thread(target=fill_sizes, daemon=True).start()

    def fill_sizes():
        for iid, ent in list(rows.items()):
            if ent["missing"]:
                continue
            folder = ent["folder"]
            sizes = project_ops.project_sizes(
                folder, build_dir=project_file.project_build_dir(folder))
            total = sizes["assets"] + sizes["build"] + sizes["mods"]

            def update(iid=iid, total=total):
                try:
                    vals = list(tree.item(iid, "values"))
                    vals[2] = _human_size(total)
                    tree.item(iid, values=vals)
                except tk.TclError:
                    pass
            try:
                win.after(0, update)
            except tk.TclError:
                return

    def selected():
        sel = tree.selection()
        return rows.get(sel[0]) if sel else None

    def open_sel():
        ent = selected()
        if not ent or ent["missing"]:
            return
        if ent["anchored"]:
            app._open_project_folder_checked(ent["folder"])
        else:
            app.window.extract_output_var.set(ent["folder"])
            app.window.append_log(
                "Folder set as project folder: %s" % ent["folder"], "info")

    def props_sel():
        ent = selected()
        if ent and not ent["missing"]:
            open_properties(app, ent["folder"])

    def fork_sel():
        ent = selected()
        if ent and not ent["missing"]:
            save_project_as(app, ent["folder"])

    def archive_sel():
        ent = selected()
        if ent and not ent["missing"] and ent["anchored"]:
            _archive_flow(app, ent["folder"], parent_win=win,
                          on_done=refresh)

    def reveal_sel():
        ent = selected()
        if ent and not ent["missing"]:
            _reveal(ent["folder"])

    def remove_sel():
        ent = selected()
        if not ent:
            return
        project_registry.remove(app._settings, ent["folder"])
        app._save_settings()
        refresh()

    def locate_sel():
        ent = selected()
        if not ent:
            return
        p = filedialog.askdirectory(
            title="Where did this project move to?", parent=win)
        if p:
            project_registry.relocate(app._settings, ent["folder"],
                                      os.path.normpath(p))
            app._save_settings()
            refresh()

    tree.bind("<Double-1>", lambda _e: open_sel())

    btns = tk.Frame(win, bg=c["bg"])
    btns.pack(pady=(4, 10))
    for text, cmd in (("Open", open_sel), ("Properties...", props_sel),
                      ("Save As (fork)...", fork_sel),
                      ("Archive...", archive_sel),
                      ("Reveal", reveal_sel),
                      ("Remove from list", remove_sel),
                      ("Locate...", locate_sel)):
        ttk.Button(btns, text=text, command=cmd).pack(side=tk.LEFT, padx=3)

    note.configure(
        text="Remove from list never touches the folder.  Archive shrinks "
             "a dormant project to its unique bytes (edits, backups, "
             "notes); opening it later re-extracts to hydrate.  This list "
             "is only folders the app has opened or anchored — it never "
             "scans your disks.")

    def on_close():
        _manager_win[0] = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)
    center_over(app.root, win, 820, 420)
    win.deiconify()
    refresh()
