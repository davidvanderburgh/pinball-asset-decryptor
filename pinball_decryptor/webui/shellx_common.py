"""Helpers the app-wide menus and windows share (the ``shellx`` service).

Plain functions with no Tk in them: opening a file or folder in the OS,
the size strings the Tk windows printed, and running a slow read off the UI
loop while the loop keeps turning (what a Tk window did with a worker thread
and ``after``).
"""

import logging
import os
import subprocess
import sys
import threading

log = logging.getLogger(__name__)


def human_size(n):
    """projects_ui._human_size: "12.4 GB", "310.5 MB", "512 B"."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit) if unit == "B"
                    else "%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d B" % n


def fmt_binary(n):
    """disk_dialog._fmt: binary GiB/MiB/KiB (how WSL and df report)."""
    if n is None:
        return "—"
    if n >= 1024 ** 3:
        return "%.2f GiB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MiB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.0f KiB" % (n / 1024)
    return "%d B" % n


def reveal(folder):
    """projects_ui._reveal: open *folder* in the OS file browser."""
    try:
        if sys.platform == "win32":
            os.startfile(folder)                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            from ..core import desktop
            desktop.open_path(folder)
    except OSError:
        pass


def reveal_in_file_manager(path):
    """main_window._reveal_in_file_manager: the file selected where the OS
    can (Explorer, Finder), else its folder.  Never raises."""
    if not path:
        return
    path = os.path.abspath(path)
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if sys.platform == "win32":
            if os.path.isfile(path):
                subprocess.Popen('explorer /select,"%s"' % os.path.normpath(path))
            else:
                os.startfile(folder)                  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path)
                             else ["open", folder])
        else:
            from ..core import desktop
            ok, err = desktop.open_path(folder)
            if not ok:
                raise RuntimeError(err)
    except Exception:                                 # noqa: BLE001
        log.exception("reveal %s", path)


def open_in_text_viewer(path):
    """main_window._open_in_text_viewer: the OS's viewer for *path*, falling
    back to showing it in the file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                        # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            from ..core import desktop
            ok, err = desktop.open_path(path)
            if not ok:
                raise RuntimeError(err)
    except Exception:                                 # noqa: BLE001
        reveal_in_file_manager(path)


def open_in_default_app(path):
    """Hand *path* to the OS's default app for its type (Photos, the video
    player, the music player: PAD-208).  Returns None, or the error text
    to show; unlike :func:`open_in_text_viewer` it never falls back to the
    file manager, so the caller can say why nothing opened."""
    if not path or not os.path.isfile(path):
        return "The file isn't there:\n%s" % (path or "(no file)")
    path = os.path.abspath(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)                        # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            from ..core import desktop
            ok, err = desktop.open_path(path)
            if not ok:
                return err or "no desktop opener found"
    except Exception as e:                            # noqa: BLE001
        log.exception("open %s", path)
        return "%s\n\n%s" % (path, e)
    return None


def open_in_default_app_or_warn(path):
    """:func:`open_in_default_app`, with a warning box when it fails."""
    err = open_in_default_app(path)
    if err:
        from . import compat
        compat.messagebox.showwarning("Couldn't open file",
                                      "Couldn't open this file in its "
                                      "default app:\n%s" % err)
        return False
    return True


def off_loop(ctx, fn, *args, timeout=None):
    """Run ``fn(*args)`` on a worker thread and wait for it WITHOUT stalling
    the UI loop (log lines, progress and other calls keep flowing, as they
    did while a Tk window measured a folder).  Re-raises fn's error."""
    box = {}
    done = threading.Event()

    def _work():
        try:
            box["r"] = fn(*args)
        except BaseException as e:                    # noqa: BLE001
            box["e"] = e
        finally:
            done.set()
            try:
                ctx.loop.notify()
            except Exception:                         # noqa: BLE001
                pass

    threading.Thread(target=_work, name="pad-shellx-read",
                     daemon=True).start()
    if ctx.loop.in_loop():
        ctx.loop.pump_until(done, timeout=timeout)
    else:
        done.wait(timeout)
    if "e" in box:
        raise box["e"]
    return box.get("r")


def same_path(a, b):
    """Case- and separator-insensitive path equality ("" never matches)."""
    if not a or not b:
        return False
    return (os.path.normcase(os.path.normpath(a))
            == os.path.normcase(os.path.normpath(b)))
