"""PAD-114 proof shot: the prerequisite run now says WHICH Linux it probed.

Every WSL ticket this project has triaged arrived with a log that named the
step that failed and never the distro it failed on, so the first reply was a
request for ``wsl -l -v`` - PAD-73 asked for it and four tickets later it had
still not been answered.  A prerequisite run that probes inside WSL now puts
one line in the log naming the distro and its release, and a second line only
when that release is below the oldest one PAD is tested against.

This is the REAL check on this machine: no faked WSL, no stubbed probe.  The
app is launched, Stern is selected (its WSL2 prerequisite is what sends the
probes into the distro), and the log pane is photographed once the run has
finished.

    python scripts/shot_pad114_release.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, rolling log
sandboxed) follow scripts/take_screenshots.py -- see its header for why they
are what they are.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad114relbak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

# The log pane preloads earlier sessions from the real rolling log; a fresh
# scratch dir per run keeps the before shot's lines out of the after shot.
from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad114rel_log_")

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


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(600)
def s_enter():
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(900, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


# The probes run in WSL on a worker; a warm VM answers in a few seconds and a
# cold one boots first.  Long enough for either, and the log is what is being
# photographed rather than a stopwatch.
@step(25000)
def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
        body = t.get("1.0", tk.END)
        for line in body.splitlines():
            if "WSL:" in line or "prerequisite" in line.lower():
                print("  log: %s" % line.strip(), flush=True)
    root.update()
    snap("%s_prereq_release.png" % WHEN)


@step(600)
def s_done():
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            print("step %d: %s" % (i, fn.__name__), flush=True)
            fn()
        except Exception:
            print("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()),
                  flush=True)
        run(i + 1)

    root.after(delay, _go)


root.after(90000, lambda: root.destroy())
run()
try:
    app.run()
finally:
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            print("settings restored", flush=True)
    except Exception:
        print("settings restore FAILED:\n%s" % traceback.format_exc(),
              flush=True)
