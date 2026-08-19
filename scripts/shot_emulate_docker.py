"""Capture the Emulate tab's macOS Docker notice for PAD-74.

    python scripts/shot_emulate_docker.py <out.png>

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one screen that rig does not
cover.

WHY THE MACHINE IS SIMULATED, NOT THE ANSWER.  The notice is built from
what ``docker_state()`` finds, and the capture box is a Windows PC with
no Docker at all - so feeding the panel a state word would only
photograph a string this script chose.  What is faked instead is
dbotte's Mac, one layer lower: the ``docker`` command installed by
``sudo port install docker`` at /opt/local/bin/docker, no Homebrew, no
Docker Desktop, and no daemon behind the client.  ``docker_state()``
then runs for real and reaches its own conclusion, which is the thing
the pair is about - the same Mac, told "Docker Desktop is required"
before and told what it actually has and actually needs now.

The Windows-only setup notice is packed away first: this shot is what a
Mac shows, and that half of the tab never runs there.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak74"

#: The one docker-ish file that exists on the reporter's Mac.  `sudo port
#: install docker` puts the CLIENT here and nothing else: MacPorts' own port
#: page says the port "contains command line utilities for interacting with
#: Docker, but not the core daemon".
MACPORTS_DOCKER = "/opt/local/bin/docker"

#: ...and the MacPorts `port` command that put it there, which is how the tab
#: works out that `sudo port install colima` is the line for THIS Mac.
MAC_FILES = (MACPORTS_DOCKER, "/opt/local/bin/port")

#: Everything the probe may look for lives under one of these, and on his Mac
#: none of it is there - no Homebrew (his .zprofile fails on /opt/homebrew/bin/
#: brew), no /Applications/Docker.app (Docker Desktop does not install on his
#: macOS Ventura), no colima.
MAC_PREFIXES = ("/opt/", "/usr/local/", "/Applications/", "/private/",
                "/Users/", "/var/")


def log(msg):
    print(msg, flush=True)


def mac(path):
    """A path as the Mac would spell it.

    os.path.join is the HOST's join, so on this Windows box
    join("/opt/local/bin", "docker") comes back with a backslash in it and
    would miss every literal below.  Only the simulation needs this; on a Mac
    the two spellings are the same string.
    """
    return str(path).replace("\\", "/")


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.gui import emulate_tab  # noqa: E402


# ----------------------------------------------------------------------
# dbotte's Mac, wired under emulate_tab only.  Proxies rather than
# monkeypatched functions, because the module's os/shutil/subprocess do a
# hundred other things on this Windows box and every one of them has to keep
# working while the shot is taken.
# ----------------------------------------------------------------------
class _PathProxy:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def isfile(self, p):
        s = mac(p)
        if s in MAC_FILES:
            return True
        if s.startswith(MAC_PREFIXES):
            return False
        return self._real.isfile(p)

    def join(self, *parts):
        """POSIX join for the Mac's own directories.

        Only the simulation needs this, and it is not cosmetic: os.path.join
        is the HOST's, so on this Windows box a Mac directory joined to a tool
        name comes back with a backslash in the middle of it - and that is the
        string the tab then prints at the user.
        """
        if parts and str(parts[0]).startswith("/"):
            return "/".join([str(parts[0]).rstrip("/")]
                            + [str(x) for x in parts[1:]])
        return self._real.join(*parts)

    def isdir(self, p):                     # /Applications/Docker.app is one
        s = mac(p)
        if s.startswith(MAC_PREFIXES):
            return False
        return self._real.isdir(p)

    def exists(self, p):
        s = mac(p)
        if s in MAC_FILES:
            return True
        if s.startswith(MAC_PREFIXES):
            return False
        return self._real.exists(p)


class _OsProxy:
    def __init__(self, real):
        self.path = _PathProxy(real.path)
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)


class _ShutilProxy:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def which(self, cmd, *a, **kw):
        # launchd hands a GUI app /usr/bin:/bin:/usr/sbin:/sbin, and none of
        # these are on it.  pythonw.exe lookups pass straight through.
        if str(cmd) in ("docker", "colima", "podman", "brew", "port",
                        "docker-compose"):
            return None
        return self._real.which(cmd, *a, **kw)


class _SubprocessProxy:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def run(self, cmd, *a, **kw):
        argv = [mac(a) for a in
                (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
        head = argv[0] if argv else ""
        if head == "docker":
            # Not on the inherited PATH: this is the exception the old probe
            # read as "Docker is not installed".
            raise FileNotFoundError(2, "No such file or directory: 'docker'")
        if head == MACPORTS_DOCKER:
            # The client is real; there is no daemon for it to talk to.
            log("sim: %s -> rc 1 (cannot connect to the Docker daemon)"
                % " ".join(argv))
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        return self._real.run(cmd, *a, **kw)


class _SysProxy:
    """`sys`, but this is a Mac.

    ONLY AROUND THE PROBE (see as_darwin): docker_state's last question -
    client installed, but is there an engine to run it? - is macOS-only by
    construction, and everything else in this module that reads sys.platform
    would be told a lie it cannot act on.
    """
    platform = "darwin"

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)


def as_darwin():
    """Ask the three real probes as though this were the Mac, and put the
    module back exactly as it was."""
    real_sys = emulate_tab.sys
    emulate_tab.sys = _SysProxy(real_sys)
    try:
        # getattr, because the BEFORE half of this pair is a build that has
        # neither function - which is the whole point of the shot: nothing
        # then knew where to look for a docker that was not on PATH.
        cli = getattr(emulate_tab, "docker_cli", lambda: None)()
        eng = getattr(emulate_tab, "docker_engine", lambda: None)()
        return (emulate_tab.docker_state(), cli, eng)
    finally:
        emulate_tab.sys = real_sys


emulate_tab.os = _OsProxy(emulate_tab.os)
emulate_tab.shutil = _ShutilProxy(emulate_tab.shutil)
emulate_tab.subprocess = _SubprocessProxy(emulate_tab.subprocess)

app = App()
root = app.root
win = app.window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def snap(path):
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)  # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    # See shot_emulate_setup.py: the notice is the last widget packed into a
    # frame inside a scrolling canvas, so it needs the height to exist at all.
    w = min(1100, root.winfo_screenwidth() - 80)
    h = min(1040, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))


@step(6000)
def s_emulate_tab():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_docker():
    """Ask the real probe about the simulated Mac, and show its answer."""
    panel = win._emulate_panel
    # This PC's WSL half is not part of the picture a Mac gets.
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    for w in (panel._setup_msg, panel._setup_btn):
        try:
            w.pack_forget()
        except Exception:
            pass
    state, cli, eng = as_darwin()
    log("docker_state() on the simulated Mac: %r (cli=%r engine=%r)"
        % (state, cli, eng))
    panel._docker_cli, panel._docker_engine = cli, eng
    panel._docker_apply(state)
    # ROOM FOR IT, measured rather than guessed.  The notice is the last widget
    # packed into the tab's frame and the log pane below the notebook is the
    # only thing with expand=True, so the notebook has to be told to take the
    # height or Tk hands the notice one pixel and never maps it (see
    # shot_emulate_setup.py, which met the same wall).  A fixed +460 was not
    # enough here: this tab also carries the save-state table.
    root.update_idletasks()
    frame = panel._docker_msg.master
    win._notebook.configure(
        height=min(frame.winfo_reqheight() + 40,
                   root.winfo_screenheight() - 260))
    root.update_idletasks()


@step(2000)
def s_snap():
    panel = win._emulate_panel
    msg = panel._docker_msg
    log("notice mapped=%s h=%s text=%r"
        % (msg.winfo_ismapped(), msg.winfo_height(), msg.cget("text")))
    log("button text=%r" % panel._docker_btn.cget("text"))
    snap(OUT)


@step(500)
def s_done():
    root.destroy()


def run_steps(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            log("step %d: %s" % (i, fn.__name__))
            fn()
        except Exception:
            log("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))
        run_steps(i + 1)

    root.after(delay, _go)


root.after(120000, lambda: root.destroy())
run_steps()
try:
    app.run()
finally:
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
