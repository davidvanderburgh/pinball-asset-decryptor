"""PAD-138: a JJP "Build / make USB stick" write that died before it started.

    python scripts/shot_pad138.py <out_dir> <before|after>

Three shots, each as ``<before|after>_<screen>.png``:

``stick_dialog``
    The Build / make USB stick dialog opened flash-only on an ISO, as the
    Write tab's button opens it.  It carried Stern's "Only the boot menu"
    tick, a write no JJP stick has.

``write_usb_stick``
    The Write tab a few seconds after the dialog hands the app its (ISO,
    stick) pair - the exact ``_start_flash_image(img, device,
    menu_only=False)`` call ``FlashImageDialog._do_start`` makes.  Before the
    fix that raised a TypeError (only Stern's flash factory took
    ``menu_only``) AFTER the run state was armed, so the window sat "running"
    with a Cancel and nothing behind it.

``write_usb_stick_log``
    The same moment from the short Mod Pack tab, so the log pane has room to
    show what the run said.

NOTHING IS WRITTEN TO ANY DRIVE: the ISO is a 1 MB scratch file, the device
check is told the placeholder path is a drive, the pipeline's format step is
replaced by a wait, and the dialog does not enumerate drives.  The shot shows
the real Check phase and its real log line, then parks on "Format stick".
Both modes run under the same patches, so the pair is an A/B of the code
alone - run the "before" from an export of the commit before the fix.

The app opens straight into JJP with a scratch project folder (settings.json
is backed up and restored), and the session log is sandboxed, so neither
David's saved state nor his real project logs see this run.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad138bak"
DEVICE = r"\\.\PHYSICALDRIVE9"
GEOM = ["1100x760+40+40"]


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

scratch = tempfile.mkdtemp(prefix="pad138_")
project = os.path.join(scratch, "sonichedgehogcode")
os.makedirs(project)
open(os.path.join(project, ".checksums.md5"), "w").close()
ISO = os.path.join(scratch, "sonic_modified.iso")
BUILT = os.path.join(scratch, "sonic_modified-modified.iso")
for path in (ISO, BUILT):
    with open(path, "wb") as f:
        f.write(b"\x00" * (1 << 20))

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "jjp"
jjp = settings.setdefault("manufacturers", {}).setdefault("jjp", {})
jjp.update(extract_input=ISO, write_original=ISO, extract_output=project,
           write_assets=project, write_output=scratch)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad138_log_")

from pinball_decryptor.plugins.jjp import usbstick  # noqa: E402
from pinball_decryptor.gui.flash_dialog import FlashImageDialog  # noqa: E402

usbstick.is_device_path = lambda _p: True
FlashImageDialog._refresh_drives = lambda self: None


def _hold_instead_of_formatting(self):
    while True:
        time.sleep(0.2)
        self._check_cancel()


usbstick.UsbStickPreparePipeline._format_stick = _hold_instead_of_formatting

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


def grab(hwnd, name, crop_border):
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
    bih.biWidth, bih.biHeight = w, -h  # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    if crop_border:
        border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
        img = img.crop((border, 0, w - border, h - border))
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def snap_main(name):
    for _ in range(2):              # let a queued auto-resize run, then win
        root.geometry(GEOM[0])
        root.update()
    grab(user32.GetAncestor(root.winfo_id(), 2), name, True)  # GA_ROOT


def the_dialog():
    tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    return tops[-1] if tops else None


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_write_tab():
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    GEOM[0] = "%dx%d+20+10" % (min(1100, sw - 60), sh - 70)
    log("screen %dx%d -> geometry %s; manufacturer: %s" % (
        sw, sh, GEOM[0], getattr(app._current_mfr, "key", None)))
    root.geometry(GEOM[0])
    win._notebook.select(win._tab_write)


# Prereq checks + update check settle first, so their lines are above the
# flash's in the log rather than landing in the middle of it.
@step(9000)
def s_open_dialog():
    choices = getattr(win, "_saved_flash_choices", None)
    if isinstance(choices, dict):
        choices["jjp"] = {"build": False, "write": True}
    # Its own callback: the dialog is modal, and the rest of this chain has
    # to keep firing while it is up.
    root.after(0, win._open_flash_dialog)


@step(2500)
def s_snap_dialog():
    dlg = the_dialog()
    if dlg is None:
        log("!! dialog not found")
        return
    dlg.update()
    grab(user32.GetAncestor(dlg.winfo_id(), 2), "stick_dialog", False)
    dlg.destroy()


@step(1000)
def s_start_flash():
    # Its OWN Tk callback, as the dialog's Start button is: an exception out
    # of it must reach the app's report_callback_exception, not this rig's
    # try/except.
    root.after(0, lambda: app._start_flash_image(ISO, DEVICE,
                                                 menu_only=False))


@step(4000)
def s_snap_write():
    log("running=%s flash button=%r pipeline=%s" % (
        win._running, win._flash_btn.cget("text"),
        type(app.pipeline).__name__ if app.pipeline else None))
    snap_main("write_usb_stick")


@step(500)
def s_short_tab():
    win._notebook.select(win._tab_modpack)
    fit = getattr(win, "_resize_notebook_to_current_tab", None)
    if fit:
        fit()


@step(2500)
def s_snap_log():
    win._log_text.see("end")
    snap_main("write_usb_stick_log")


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


root.after(90000, root.destroy)     # watchdog
run_steps()
try:
    app.run()
finally:
    try:
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
        log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
    shutil.rmtree(scratch, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)                     # the parked stick thread must not hold us
