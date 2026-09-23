"""Hot reload while developing (a checkout only; a frozen build never runs it).

A thread watches the source tree's modification times:

* a stylesheet under ``webui/static`` -> the page swaps that stylesheet in
  place (no reload, nothing moves);
* the page's JavaScript or HTML -> the page reloads itself.  Every piece of
  UI state lives in Python's store and is replayed on connect, so a reload
  loses nothing but an open menu;
* a Python file under ``pinball_decryptor`` -> Python code cannot be swapped
  safely under a live app (a half-reloaded tab service is worse than a stale
  one), so the header shows "Python changed" with a one-click restart.

``PAD_UI_HOT=0`` turns it off.
"""

import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PKG, "webui", "static")
POLL_S = 0.4


def enabled():
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("PAD_UI_HOT", "1") not in ("0", "", "false", "no")


def _scan(root, exts):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", "vendor", "fonts")]
        for n in files:
            if n.endswith(exts):
                p = os.path.join(d, n)
                try:
                    out[p] = os.stat(p).st_mtime_ns
                except OSError:
                    pass
    return out


def _changed(old, new):
    return sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))


class Watcher:
    def __init__(self, ctx):
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread = None
        self.py_changed = []

    def start(self):
        self._thread = threading.Thread(target=self._run, name="pad-hot",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        web = _scan(STATIC, (".css", ".js", ".html"))
        py = _scan(PKG, (".py",))
        while not self._stop.wait(POLL_S):
            try:
                web2 = _scan(STATIC, (".css", ".js", ".html"))
                py2 = _scan(PKG, (".py",))
            except Exception:                           # noqa: BLE001
                continue
            wch, pch = _changed(web, web2), _changed(py, py2)
            web, py = web2, py2
            if wch:
                # an editor writes in bursts: let the burst finish
                time.sleep(0.15)
                web = _scan(STATIC, (".css", ".js", ".html"))
                rel = [os.path.relpath(p, STATIC).replace("\\", "/")
                       for p in wch]
                kind = ("css" if all(r.endswith(".css") for r in rel)
                        else "full")
                log.info("hot reload (%s): %s", kind, ", ".join(rel))
                self.ctx.bus.publish("dev_reload", kind=kind, files=rel)
            if pch:
                rel = [os.path.relpath(p, PKG).replace("\\", "/")
                       for p in pch]
                for r in rel:
                    if r not in self.py_changed:
                        self.py_changed.append(r)
                self.ctx.loop.post(self._publish_py)

    def _publish_py(self):
        self.ctx.store.set("shell", dev_py_changed=list(self.py_changed))


def restart(ctx):
    """Close this app (its close runs the usual quit-time saves), then start
    a fresh copy: host.main launches it once everything here has stopped."""
    if ctx.host is None:
        return False
    ctx.dev_relaunch = True
    ctx.host.quit()
    return True


def relaunch():
    """Called by host.main after the app has closed."""
    import subprocess
    env = dict(os.environ)
    env["PAD_UI_VENV_RELAUNCHED"] = "1"
    try:
        from ..worktree_picker import ENV_PICKED
        env[ENV_PICKED] = "1"
    except Exception:                                   # noqa: BLE001
        pass
    root = os.path.dirname(PKG)
    args = [a for a in sys.argv[1:] if a != "--serve"]
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(w):
            exe = w

    subprocess.Popen([exe, "-m", "pinball_decryptor"] + args, cwd=root,
                     env=env)
