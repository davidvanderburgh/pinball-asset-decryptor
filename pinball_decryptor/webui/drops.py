"""Files dropped on the app window, by their full paths (PAD-838).

A web page never learns where a dropped file lives: ``File`` has a name and
the bytes, no path.  pywebview hands the path to a drop handler registered
from Python instead (``pywebviewFullPath`` on each dropped file, see
host.py), and the page's own drop handler, which knows WHERE the file went
(which row), only has the names.  The two meet here: the window's handler
puts the paths in, the tab the page called takes them out by name.

The two arrive on different threads in either order, so ``take`` waits a
moment for paths that are not in yet.  In a browser (no app window) they
never come, and ``take`` answers ``[]`` after that moment.
"""

import os
import threading
import time

#: how long a drop's paths are kept for the page's call to claim them
KEEP_S = 30.0
#: how long ``take`` waits for paths the window has not handed in yet
WAIT_S = 2.0


class DropBox:
    def __init__(self):
        self._cv = threading.Condition()
        self._paths = []            # [(time put, full path)]

    def put(self, paths):
        """The window's drop handler: the full paths of one drop."""
        now = time.monotonic()
        with self._cv:
            self._paths = [(t, p) for t, p in self._paths
                           if now - t < KEEP_S]
            self._paths += [(now, os.path.normpath(p)) for p in paths if p]
            self._cv.notify_all()

    def put_event(self, event):
        """``put`` from a pywebview drop event (its ``dataTransfer.files``,
        each with the ``pywebviewFullPath`` pywebview filled in)."""
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
        except AttributeError:
            return
        self.put([f.get("pywebviewFullPath") for f in files
                  if isinstance(f, dict)])

    def take(self, names, wait=WAIT_S):
        """The full paths of the dropped files named *names* (the page's
        ``File.name`` of each), in that order; ``[]`` unless every one came
        in within *wait* seconds.  Each path is handed out once."""
        names = [str(n) for n in names or [] if n]
        if not names:
            return []
        end = time.monotonic() + wait
        with self._cv:
            while True:
                got = self._claim(names)
                if got is not None:
                    return got
                left = end - time.monotonic()
                if left <= 0:
                    return []
                self._cv.wait(left)

    def _claim(self, names):
        pool = list(self._paths)
        out = []
        for name in names:
            # the newest drop of that name wins
            for i in range(len(pool) - 1, -1, -1):
                if os.path.basename(pool[i][1]) == name:
                    out.append(pool.pop(i)[1])
                    break
            else:
                return None
        self._paths = pool
        return out
