"""Capture the Emulate tab's prerequisite notice for PAD-48.

    python scripts/shot_emulate_setup.py <out.png>

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one screen that rig does not
cover.

WHY THE FACTS ARE SYNTHETIC.  The notice is built from what
setupcheck.sh finds in WSL, and this machine has every package - so a
live capture shows an empty tab in both the before and the after shot
and proves nothing.  _setup_apply is fed the machine that REPORTED the
bug instead: the ARM cross compiler present (his shim built and said
"built ok: 154684 bytes"), no native gcc, everything else fine.  That
is the whole point of the pair - the same machine, silently cleared
before and named now.
"""
import ctypes
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak48"

#: Jim-Beam's machine, as setupcheck.sh would report it.  `nativecc` is the
#: fact this ticket adds; a build of the app from before it ignores the key
#: entirely, which is exactly the silence being captured.
FACTS = {"qemu": "1", "armgcc": "1", "nativecc": "0", "debugfs": "1",
         "fuse": "1", "binfmt": "1", "iswsl": "1", "wslconf": "1",
         "distro": "ubuntu 24.04 noble",
         "components": "main multiverse restricted universe",
         "indexed": "1", "nocand": "", "universe": "1", "xrel": ""}


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

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
    # TALL ENOUGH FOR THE NOTICE, AND THE LOG PANE GIVES UP THE HEIGHT.
    # The notice is the LAST widget packed into the tab frame, and that frame
    # sits in the main window's scrolling canvas: when it is short of its
    # requested height Tk hands the last slave one pixel and never maps it, so
    # the shot comes back with the button and no words beside it.  The log
    # pane is the one thing on this window with expand=True, so it is what has
    # to shrink - a taller toplevel alone just makes a taller log.
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
def s_facts():
    """Hand the panel the reporter's machine.

    The panel's own probe runs against THIS PC and would overwrite it, so the
    real one is stubbed out first - the widget path under test is the same
    either way, _setup_apply is what draws the notice.
    """
    panel = win._emulate_panel
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._setup_apply(dict(FACTS))
    # ROOM FOR IT.  The notebook packs at its requested height and the log
    # pane takes everything left over, so the notice - the last widget packed
    # into the page - is handed one pixel and never mapped.  -height is the
    # notebook's own override and the only lever that does not mean editing
    # the app to photograph it.
    win._notebook.configure(height=max(520, panel._setup_msg.winfo_reqheight()
                                       + 460))
    root.update_idletasks()
    # SAY WHETHER IT IS ACTUALLY ON SCREEN.  An unmapped label is the failure
    # this rig had, and it is invisible in the log as well as in the shot - the
    # capture succeeds and the notice simply is not in it.  A build from before
    # this ticket reports mapped=0, which is the point of the pair.
    msg = panel._setup_msg
    log("notice mapped=%s h=%s text=%r"
        % (msg.winfo_ismapped(), msg.winfo_height(), msg.cget("text")))


@step(2000)
def s_snap():
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
