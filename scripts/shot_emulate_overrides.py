"""Capture the Emulate tab's "Card image to run" box for PAD-103.

    python scripts/shot_emulate_overrides.py <out.png>

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one box that rig does not cover:
the source picker at the top of the Emulate tab, which is where the
"apply my edits without rebuilding the card" opt-in lives.

WHY IT DRIVES THE PANEL RATHER THAN JUST SNAPPING IT.  The box only says
anything about edits when there is an assets folder to apply, and that
folder is the Write tab's (one field, one owner - see _build_source).
The app restores both from the real settings.json here, so the shot is
of this machine's own project; the panel's status poll and the WSL setup
probe are stubbed out first so a slow `wsl.exe` cannot repaint the tab
half way through the capture.
"""
import ctypes
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate-card.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak103"


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
# NO UPDATE BANNER IN THE PAIR.  The check fires 1.5 s after launch and lands
# whenever GitHub answers, so it is in some shots and not others - and a banner
# that appears in the AFTER shot alone reads as part of what changed while
# shifting every widget under it down by its own height.
app._check_for_update = lambda *a, **kw: None
win.show_update_banner = lambda *a, **kw: None

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
    # The tab's own content decides the height: the source box is at the
    # TOP, so anything that fits the buttons and the Status grid under it
    # shows the whole of what changed with its surroundings for scale.
    w = min(1100, root.winfo_screenwidth() - 80)
    h = min(1000, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))


@step(6000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_quiesce():
    """Stop the pollers, then say what the box is actually showing.

    The status poll rewrites the hint label every two seconds off a
    `wsl.exe` round trip, and the setup probe can repack a whole notice
    under the buttons - either landing mid-capture makes the before and
    after shots differ for a reason that has nothing to do with this
    change.
    """
    panel = win._emulate_panel
    panel._schedule_poll = lambda *a, **kw: None
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._poll = lambda *a, **kw: None
    log("card      = %r" % win.emulate_card_var.get())
    log("assets    = %r" % win.write_assets_var.get())
    # Present only after this ticket; a build from before it logs None,
    # which is the pair's own control.
    var = getattr(win, "emulate_overrides_var", None)
    log("overrides = %s" % (None if var is None else bool(var.get())))
    # TICKED FOR THE SHOT, deliberately: the box defaults off, and off it
    # only says "tick me".  What is worth photographing is what it says when
    # it is on - which is where the cost of it is written down.  Set through
    # the panel so the label repaints exactly as a click would make it.
    if var is not None:
        var.set(True)
        win._emulate_panel._overrides_paint()
    root.update_idletasks()


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
