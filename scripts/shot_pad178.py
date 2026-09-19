"""PAD-178 proof shot: the Emulate tab's log when the game puts up
"Game validation error, Update SD card".

    python scripts/shot_pad178.py <watch.log> <out.png>

THE REPORT.  DragonRR, the same user as PAD-172, came back with "still having
the validation problem" and a log of a run on the STOCK Godzilla LE 1.16 card
with his edits on top.  Nothing in that log could say which of the six checks
behind that one banner was up, so the answer could only be deduced, and the
PAD-172 deduction ("#4, so the card must carry longer sounds") cannot hold on
a stock card.

WHAT THE PANE HOLDS.  A REAL RUN'S OUTPUT, fed through the tab's own ``_log``
exactly as its drain thread feeds watch.sh's stdout (``"[emulate] " + line``).
*watch.log* is what run.sh captured from ``watch.sh`` on this machine: the
card PAD-172 built with two longer callouts (C:\\tmp\\pad172\\M.raw), with a
DragonRR-shaped override set bound on top whose game program lacks that
card's sound-count patch - the run that puts the banner up at Ball 1.  The
before log is from HEAD's rig, the after log from this branch's.  The pane is
fed up to a few lines past the game's first picture, the same cut for both.

Nothing is launched and no WSL is touched: the pollers are stopped and the
card field is set to the card the logs came from.  Capture mechanics
(PrintWindow, DPI-unaware, settings backed up, rolling log sandboxed) follow
scripts/shot_pad173.py.
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

if len(sys.argv) != 3:
    sys.exit("usage: shot_pad178.py <watch.log> <out.png>")
LOG_IN = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
CARD = os.environ.get("PAD178_CARD", r"C:\tmp\pad172\M.raw")
ASSETS = os.environ.get("PAD178_ASSETS", r"C:\tmp\pad178\P178")
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 300
#: Lines fed past the game's first picture, the same for both halves of the
#: pair: the sound bank is counted during boot, so the verdict lands a few
#: lines after it, long before a game is started.
AFTER_FIRST = int(os.environ.get("PAD178_AFTER_FIRST", "9"))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak178"


def log(msg):
    print(msg, flush=True)


def fed_lines(path):
    """The run's lines up to AFTER_FIRST lines past the first picture."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f]
    first = next((i for i, ln in enumerate(lines) if "picture: FIRST" in ln),
                 None)
    end = (first + 1 + AFTER_FIRST) if first is not None else len(lines)
    return lines[:end]


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
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad178shot_")

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
    for _ in range(2):
        root.geometry(GEOM)
        root.update_idletasks()
    win._notebook.configure(height=NB_H)
    # On a short screen the log pane is packed to expand and runs on past the
    # window's bottom edge, and what that hides is exactly the run's latest
    # lines: size the pane to the rows that are on screen, then show its end.
    root.update_idletasks()
    t = getattr(win, "_log_text", None)
    if t is not None:
        bottom = root.winfo_rooty() + root.winfo_height()
        if t.winfo_rooty() + t.winfo_height() > bottom:
            info = t.dlineinfo("@0,0")
            row = info[3] if info else 14
            t.pack_configure(expand=False)
            t.configure(height=max(4, (bottom - t.winfo_rooty() - 12) // row))
        root.update_idletasks()
        t.see("end")
        root.update()           # repaint the strip the shorter pane gave up
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
    w = min(1360, root.winfo_screenwidth() - 40)
    h = min(1010, root.winfo_screenheight() - 60)
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
    """Stop the pollers so a slow wsl.exe cannot repaint mid-capture, and
    point the card field at the card the run was made on."""
    panel = win._emulate_panel
    panel._schedule_poll = lambda *a, **kw: None
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._poll = lambda *a, **kw: None
    panel._apply = lambda *_a, **_kw: None
    win.emulate_card_var.set(CARD)
    # the runs had the set bound on top; the settings are restored after
    win.write_assets_var.set(ASSETS)
    win.emulate_overrides_var.set(True)
    try:
        panel._overrides_paint()
    except Exception:                                   # noqa: BLE001
        pass
    try:
        win._resize_notebook_to_current_tab()
    except Exception:                                   # noqa: BLE001
        pass


@step(1500)
def s_feed():
    panel = win._emulate_panel
    lines = fed_lines(LOG_IN)
    for line in lines:
        panel._log("[emulate] " + line)
    log("fed %d line(s) from %s" % (len(lines), LOG_IN))
    named = [ln for ln in lines if "[validation]" in ln or "validation:" in ln]
    log("validation lines fed: %d" % len(named))
    for ln in named:
        log("   " + ln[:160])


@step(3000)
def s_snap():
    root.update_idletasks()
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
