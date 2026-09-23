"""Modal questions and file pickers for the web UI.

A modal is a question the page must answer before the asker goes on, exactly
like a Tk ``messagebox``: :meth:`Dialogs.ask` publishes it, then waits.  On
the UI loop the wait keeps the loop turning (see ``UiLoop.pump_until``), so
log lines and progress keep arriving under the question, as they did under a
Tk dialog.  Open modals live in the ``modals`` namespace of the store, so a
page that reloads shows them again.

File pickers are native when the desktop host provides them (pywebview's
dialogs: the real Windows / macOS / GTK-Qt panels); otherwise the page shows
its own folder browser, served by :func:`list_dir`.
"""

import itertools
import os
import string
import sys
import threading


class DialogClosed(Exception):
    """The app is shutting down while a modal was open."""


class Dialogs:
    def __init__(self, loop, store):
        self._loop = loop
        self._store = store
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pending = {}          # id -> [Event, answer]
        self._open = []             # specs shown, oldest first
        #: set by the desktop host: fn(kind, spec) -> answer, runs off-loop
        self.native_file_dialog = None

    # ------------------------------------------------------------------
    def ask(self, spec):
        """Show ``spec`` (a dict: kind, title, message, buttons...) and return
        the page's answer.  Blocks the caller; on the UI loop the loop keeps
        running underneath."""
        mid = "m%d" % next(self._ids)
        spec = dict(spec)
        spec["id"] = mid
        event = threading.Event()
        with self._lock:
            self._pending[mid] = [event, None]
            self._open.append(spec)
            self._store.set("modals", open=list(self._open))
        try:
            self._loop.pump_until(event)
        finally:
            with self._lock:
                entry = self._pending.pop(mid, [None, None])
                self._open = [s for s in self._open if s["id"] != mid]
                self._store.set("modals", open=list(self._open))
        if not event.is_set():
            raise DialogClosed(mid)
        return entry[1]

    def reply(self, mid, answer):
        """The page answered modal ``mid`` (called from an HTTP thread)."""
        with self._lock:
            entry = self._pending.get(mid)
            if entry is None:
                return False
            entry[1] = answer
            entry[0].set()
        self._loop.notify()
        return True

    def cancel_all(self):
        with self._lock:
            for entry in self._pending.values():
                entry[1] = None
                entry[0].set()
        self._loop.notify()

    # ------------------------------------------------------------------
    # message boxes (tkinter.messagebox semantics)
    # ------------------------------------------------------------------
    def message(self, icon, title, message, buttons, default=None,
                detail=None):
        answer = self.ask({
            "kind": "message", "icon": icon, "title": title or "",
            "message": "" if message is None else str(message),
            "detail": detail or "", "buttons": buttons,
            "default": default,
        })
        return answer

    # ------------------------------------------------------------------
    # file pickers (tkinter.filedialog semantics: "" / () when cancelled)
    # ------------------------------------------------------------------
    def file(self, mode, title="", initialdir="", initialfile="",
             filetypes=None, multiple=False, defaultextension="",
             confirmoverwrite=True):
        spec = {
            "kind": "file", "mode": mode, "title": title or "",
            "initialdir": initialdir or "", "initialfile": initialfile or "",
            "filetypes": [list(ft) for ft in (filetypes or [])
                          if isinstance(ft, (list, tuple)) and len(ft) == 2],
            "multiple": bool(multiple),
            "defaultextension": defaultextension or "",
            "confirmoverwrite": bool(confirmoverwrite),
        }
        native = self.native_file_dialog
        if native is not None:
            result = self._run_native(native, spec)
            if result is not NotImplemented:
                return self._normalise(result, spec)
        return self._normalise(self.ask(spec), spec)

    def _run_native(self, native, spec):
        """Run the native picker off the loop and keep the loop turning."""
        box = {}
        done = threading.Event()

        def _work():
            try:
                box["r"] = native(spec)
            except Exception as e:                 # noqa: BLE001
                box["e"] = e
            finally:
                done.set()
                self._loop.notify()

        threading.Thread(target=_work, name="pad-native-dialog",
                         daemon=True).start()
        self._loop.pump_until(done)
        if "e" in box:
            return NotImplemented
        return box.get("r")

    @staticmethod
    def _normalise(result, spec):
        if spec["multiple"]:
            if not result:
                return ()
            if isinstance(result, str):
                return (result,)
            return tuple(os.path.normpath(p) for p in result if p)
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            result = result[0] if result else ""
        path = os.path.normpath(result) if result else ""
        ext = spec.get("defaultextension") or ""
        if (path and spec["mode"] == "save" and ext
                and not os.path.splitext(path)[1]):
            path += ext if ext.startswith(".") else "." + ext
        return path


# ----------------------------------------------------------------------
# The page's own folder browser (used when there is no native picker)
# ----------------------------------------------------------------------
def list_roots():
    if sys.platform == "win32":
        roots = []
        for letter in string.ascii_uppercase:
            path = letter + ":\\"
            if os.path.isdir(path):
                roots.append({"name": path, "path": path, "dir": True})
        return roots
    roots = [{"name": "/", "path": "/", "dir": True}]
    home = os.path.expanduser("~")
    roots.insert(0, {"name": "Home", "path": home, "dir": True})
    for base in ("/Volumes", "/media", "/mnt"):
        if os.path.isdir(base):
            roots.append({"name": base, "path": base, "dir": True})
    return roots


def list_dir(path, patterns=None, show_hidden=False):
    """One directory's entries for the page's browser: folders first, then
    files matching ``patterns`` (["*.raw", "*.img"]; empty = all)."""
    import fnmatch
    path = os.path.expanduser(path or "")
    if not path:
        return {"path": "", "parent": "", "entries": list_roots()}
    path = os.path.abspath(path)
    dirs, files = [], []
    try:
        with os.scandir(path) as it:
            for entry in it:
                name = entry.name
                if not show_hidden and name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if is_dir:
                    dirs.append({"name": name, "path": entry.path,
                                 "dir": True})
                else:
                    pats = [p for p in (patterns or []) if p and p != "*.*"]
                    if pats and not any(fnmatch.fnmatch(name.lower(),
                                                        p.lower())
                                        for p in pats):
                        continue
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = None
                    files.append({"name": name, "path": entry.path,
                                  "dir": False, "size": size})
    except OSError as e:
        return {"path": path, "parent": os.path.dirname(path),
                "entries": [], "error": str(e)}
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda d: d["name"].lower())
    parent = os.path.dirname(path)
    if parent == path:
        parent = ""
    return {"path": path, "parent": parent, "entries": dirs + files}
