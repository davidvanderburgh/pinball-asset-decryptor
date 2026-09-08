"""PAD-113 proof shot: what PAD says when the WSL distro no longer starts.

The reporter's Ubuntu-22.04 was upgraded in place to the next LTS and stopped
starting.  On that machine every WSL probe fails with wsl.exe's own error, but
the distro is still REGISTERED, so PAD skipped its "which step of the WSL
install is missing" diagnosis and fell through to the prerequisite's static
hint -- which told him the distro was WSL 1 and to convert it.  He ran
``wsl -l -v`` (VERSION 2) and ``wsl --set-version Ubuntu-22.04 2`` (already
version 2) and got nowhere.

The shot simulates exactly that machine: ``wsl -l -q`` and ``wsl -l -v`` answer
from the registry (a registered, WSL 2 Ubuntu-22.04), and anything run INSIDE
the distro comes back with wsl.exe's termination error.  Only
:mod:`pinball_decryptor.core.prereqs` sees the fake -- every other subprocess
call in the app is the real one -- so the pane holds the production wording for
that state and nothing else.

    python scripts/shot_pad113.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, rolling log
sandboxed) follow scripts/take_screenshots.py -- see its header for why they
are what they are.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad113bak"
GEOM = None

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

# The log pane preloads earlier sessions from the real rolling log; a fresh
# scratch dir per run keeps the before shot's lines out of the after shot.
from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad113_log_")

# ----------------------------------------------------------------------
# The simulated machine: registered distro, nothing runs inside it.
# ----------------------------------------------------------------------
from pinball_decryptor.core import prereqs  # noqa: E402

WSL_LIST_V = ("  NAME            STATE           VERSION\n"
              "* Ubuntu-22.04    Running         2\n")
WSL_DEAD = ("The Windows Subsystem for Linux instance has terminated.\n"
            "Error code: Wsl/Service/CreateInstance/CreateVm/HCS/"
            "ERROR_FILE_NOT_FOUND\n")


class _FakeSubprocess:
    """A stand-in for prereqs' ``subprocess`` module.

    Everything is the real module except ``run``, and even that only answers
    for ``wsl`` -- the powershell spawns the diagnosis makes are still real, so
    a state this box is genuinely not in cannot be faked by accident.
    """

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, cmd, *a, **kw):
        if not (isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "wsl"):
            return subprocess.run(cmd, *a, **kw)
        args = list(cmd[1:])
        if args[:2] == ["-l", "-v"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=WSL_LIST_V,
                                               stderr="")
        if "-l" in args:                      # -l -q: registration check
            return subprocess.CompletedProcess(cmd, 0, stdout="Ubuntu-22.04\n",
                                               stderr="")
        if args[:1] == ["--status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=WSL_DEAD)


prereqs.subprocess = _FakeSubprocess()

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

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


def snap(name):
    # The app re-sizes itself to the active tab on an idle callback that fires
    # at a different moment each run; re-assert the geometry twice so the pair
    # is pixel-comparable (PAD-60).
    if GEOM:
        for _ in range(2):
            root.geometry(GEOM)
            root.update_idletasks()
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
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def clear_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is None:
        return
    t.configure(state=tk.NORMAL)
    t.delete("1.0", tk.END)
    t.configure(state=tk.DISABLED)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(800)
def s_enter():
    global GEOM
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(900, root.winfo_screenheight() - 90)
    GEOM = "%dx%d+40+40" % (w, h)
    root.geometry(GEOM)
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


@step(1500)
def s_recheck():
    # Whatever the startup check said, run it again with a clean pane so the
    # shot holds one prerequisite report and nothing else.
    clear_log()
    app._recheck_prereqs()


@step(9000)
def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
    ind = win._prereq_indicators.get("WSL2")
    print("WSL2 indicator: %s" % (ind and ind.get("ok")), flush=True)
    print("strip mapped: %s" % win._prereqs_frame.winfo_ismapped(), flush=True)
    snap("%s_wsl_prereq.png" % WHEN)


@step(600)
def s_done():
    if os.path.exists(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
    root.after(delay, lambda: run(i + 1))


root.after(400, lambda: run(0))
root.mainloop()
