"""Handing URLs and files off to the desktop (browser, file manager).

Why this exists instead of a bare ``webbrowser.open``: inside a frozen
build the environment we hand a child process is *our* environment, and
both PyInstaller and the AppImage runtime rewrite it to point inside the
bundle — ``LD_LIBRARY_PATH`` at our bundled libstdc++/libssl, ``PATH`` at
our ``usr/bin``, ``PYTHONHOME``/``PYTHONPATH`` at our interpreter.  A
browser launched with that inherited env loads the wrong libraries and
dies before it ever draws a window, and because ``webbrowser.open``
reports success the moment ``Popen`` returns, the GUI happily believes
the link opened.  That is exactly what the update banner's Download
button looked like on Ubuntu (aly): click, nothing, no error.

So: scrub the bundle out of the child env (PyInstaller stashes the real
values in ``<VAR>_ORIG``), try the openers in turn, and — the part that
matters most — return an honest boolean so callers can say "couldn't
open your browser, here's the link" instead of doing nothing.
"""

import os
import shutil
import subprocess
import sys

# How long to wait for an opener before deciding it worked.  Openers that
# hand off and exit do so in milliseconds; xdg-open's generic fallback
# instead blocks for as long as the browser lives, so "still running" is
# a success, not a hang.
_LAUNCH_GRACE = 2.0

# Environment variables a frozen bundle points at itself.  Anything we
# launch for the *system* has to get the system's values back.
_BUNDLE_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONEXECUTABLE",
    "TCL_LIBRARY",
    "TK_LIBRARY",
    "TKPATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "GI_TYPELIB_PATH",
    "GTK_PATH",
    "GTK_DATA_PREFIX",
    "GTK_EXE_PREFIX",
    "GDK_PIXBUF_MODULE_FILE",
    "GDK_PIXBUF_MODULEDIR",
    "GIO_MODULE_DIR",
    "GSETTINGS_SCHEMA_DIR",
    "QT_PLUGIN_PATH",
    "QML2_IMPORT_PATH",
    "FONTCONFIG_FILE",
    "FONTCONFIG_PATH",
    "XDG_DATA_DIRS",
    "PATH",
)

# Tried in order; the first one present on PATH that doesn't fail wins.
# xdg-open first (it honours the user's default browser), then the
# desktop-specific openers, then browsers by name as a last resort.
_LINUX_URL_OPENERS = (
    ["xdg-open"],
    ["gio", "open"],
    ["gvfs-open"],
    ["gnome-open"],
    ["kde-open5"],
    ["kde-open"],
    ["x-www-browser"],
    ["sensible-browser"],
    ["firefox"],
    ["chromium"],
    ["chromium-browser"],
    ["google-chrome"],
)

# Same list minus the by-name browsers — handing a folder to firefox is
# not a useful fallback.
_LINUX_PATH_OPENERS = (
    ["xdg-open"],
    ["gio", "open"],
    ["gvfs-open"],
    ["gnome-open"],
    ["kde-open5"],
    ["kde-open"],
    ["nautilus"],
    ["dolphin"],
    ["thunar"],
    ["nemo"],
)


def _bundle_dirs():
    """Directories that mean "inside our bundle" for env scrubbing.

    Three of them because they differ: ``_MEIPASS`` is PyInstaller's
    ``_internal`` payload dir, ``APPDIR`` is the AppImage mount root, and
    the frozen exe's own folder (``AppDir/usr/bin``, which our AppRun
    prepends to PATH) sits between the two.  The exe's folder only counts
    when we're actually frozen — unfrozen it is the system's python dir,
    and stripping *that* from PATH would take /usr/bin with it.
    """
    dirs = []
    candidates = [getattr(sys, "_MEIPASS", None), os.environ.get("APPDIR")]
    if getattr(sys, "frozen", False):
        candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
    for d in candidates:
        if d:
            try:
                dirs.append(os.path.realpath(d))
            except OSError:
                pass
    return dirs


def _inside(path, dirs):
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return any(real == d or real.startswith(d + os.sep) for d in dirs)


def desktop_env(env=None, bundle_dirs=None):
    """A copy of the environment safe to launch system programs with.

    Two passes, in priority order: PyInstaller's own ``<VAR>_ORIG``
    stash wins where it exists (that *is* the pre-freeze value), and
    otherwise we drop bundle-internal entries from anything path-shaped.
    Variables that never pointed at the bundle are left completely
    alone — the user's desktop session put them there.
    """
    out = dict(os.environ if env is None else env)
    dirs = (_bundle_dirs() if bundle_dirs is None
            else [os.path.realpath(d) for d in bundle_dirs])
    for var in _BUNDLE_VARS:
        orig = out.pop(var + "_ORIG", None)
        if orig is not None:
            if orig:
                out[var] = orig
            else:
                out.pop(var, None)
            continue
        val = out.get(var)
        if not val or not dirs:
            continue
        kept = [p for p in val.split(os.pathsep)
                if p and not _inside(p, dirs)]
        if kept:
            out[var] = os.pathsep.join(kept)
        elif var == "PATH":
            # Never hand a child an empty PATH — it would fail to find
            # even /usr/bin/xdg-open.
            out[var] = os.defpath
        else:
            out.pop(var, None)
    return out


def _which(prog, env):
    return shutil.which(prog, path=env.get("PATH") or os.defpath)


def _launch(argv, env, grace=_LAUNCH_GRACE):
    """Run *argv* detached; (ok, error-text).

    ``start_new_session`` so the browser outlives us, and a short wait so
    an opener that fails immediately is reported as a failure rather than
    assumed good the way ``webbrowser.open`` assumes it.
    """
    try:
        proc = subprocess.Popen(
            argv, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=True)
    except OSError as exc:
        return False, str(exc)
    try:
        _out, err = proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        return True, ""          # still alive == it took the handoff
    if proc.returncode == 0:
        return True, ""
    detail = (err or b"").decode("utf-8", "replace").strip().splitlines()
    return False, "%s exited %s%s" % (
        argv[0], proc.returncode, (": " + detail[-1]) if detail else "")


def _open_linux(target, openers, env=None):
    env = desktop_env() if env is None else env
    errors = []
    tried = False
    for opener in openers:
        if not _which(opener[0], env):
            continue
        tried = True
        ok, err = _launch(list(opener) + [target], env)
        if ok:
            return True, ""
        if err:
            errors.append(err)
    if not tried:
        return False, "no desktop opener found (tried xdg-open, gio, …)"
    return False, "; ".join(errors) or "every opener failed"


def open_url(url, env=None):
    """Open *url* in the user's browser.  Returns ``(ok, error_text)``.

    Blocks for up to :data:`_LAUNCH_GRACE` seconds, so GUI callers should
    run it off the main thread.
    """
    if not url:
        return False, "no URL"
    if sys.platform == "win32":
        try:
            os.startfile(url)          # noqa: S606 - Windows-only
            return True, ""
        except OSError as exc:
            return False, str(exc)
    if sys.platform == "darwin":
        return _launch(["open", url], desktop_env() if env is None else env)
    ok, err = _open_linux(url, _LINUX_URL_OPENERS, env)
    if ok:
        return True, ""
    # Last resort: stdlib's own search (BROWSER=, console browsers).  It
    # inherits our polluted env, which is why it isn't tried first, but a
    # browser started wrong beats no browser at all.
    try:
        import webbrowser
        if webbrowser.open(url):
            return True, ""
    except Exception as exc:                      # pragma: no cover
        err = err or str(exc)
    return False, err


def run_detached(argv, env=None, grace=_LAUNCH_GRACE):
    """Start *argv* as an independent program; ``(ok, error_text)``.

    Same scrubbed environment as the openers above, for the same reason:
    the one program we launch this way is the *newly downloaded
    AppImage*, and handing it our ``LD_LIBRARY_PATH`` /
    ``PYTHONHOME`` would point the new app at the old bundle's
    interpreter and libraries — the failure this module exists to stop,
    aimed at ourselves.
    """
    if not argv:
        return False, "nothing to run"
    return _launch(list(argv), desktop_env() if env is None else env, grace)


def open_path(path, env=None):
    """Open a file or folder with its desktop default.  ``(ok, error)``."""
    if not path:
        return False, "no path"
    path = str(path)
    if sys.platform == "win32":
        try:
            os.startfile(path)         # noqa: S606 - Windows-only
            return True, ""
        except OSError as exc:
            return False, str(exc)
    if sys.platform == "darwin":
        return _launch(["open", path], desktop_env() if env is None else env)
    return _open_linux(path, _LINUX_PATH_OPENERS, env)
