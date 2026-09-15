"""Capture the Emulate tab's "Card image to run" box for PAD-149.

    python scripts/shot_pad149.py <out.png> [--pick]

A variant of shot_emulate_overrides.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the machine row PAD-149 adds under the
card: the country the CPU board's DIP switches report, and the mains power.

``--pick`` sets the row to a European machine (France, 50 Hz) through the
panel's own variables before the snap, so the AFTER shot shows the row doing
something rather than sitting on its defaults.  A build from before PAD-149
has no row; the rig logs that and snaps the tab as it is, which is the pair's
own control.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PICK = "--pick" in sys.argv[1:]
OUT = os.path.abspath(ARGS[0] if ARGS else "emulate-machine.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak149"


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("repo = %s" % REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

# A fresh log dir: the log pane preloads earlier sessions from the rolling
# log, and a real session's noise in one shot of the pair is not the change.
from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad149shot_")

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
app._check_for_update = lambda *a, **kw: None
win.show_update_banner = lambda *a, **kw: None

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
GEOM = None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def snap(path):
    # Re-assert the geometry: the window re-sizes itself to the active tab on
    # an idle callback, and that lands at a different moment in each run.
    for _ in range(2):
        root.geometry(GEOM)
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
    global GEOM
    w = min(1100, root.winfo_screenwidth() - 40)
    h = min(1000, root.winfo_screenheight() - 60)
    GEOM = "%dx%d+10+10" % (w, h)
    root.geometry(GEOM)


@step(6000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_quiesce():
    """Stop the pollers so a slow wsl.exe cannot repaint mid-capture."""
    panel = win._emulate_panel
    panel._schedule_poll = lambda *a, **kw: None
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._poll = lambda *a, **kw: None
    log("card = %r" % win.emulate_card_var.get())
    country = getattr(panel, "_country_var", None)
    power = getattr(panel, "_power_var", None)
    log("machine row present = %s" % (country is not None))
    if PICK and country is not None and power is not None:
        country.set("France")
        power.set(panel.POWER_CHOICES[1][0])
        log("picked: %s / %s" % (country.get(), power.get()))
        log("launch env adds: %s" % panel._machine_env())
    root.update_idletasks()
    try:
        win._resize_notebook_to_current_tab()
    except Exception:                                   # noqa: BLE001
        pass


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
    except OSError as e:
        log("could not restore settings: %s" % e)
