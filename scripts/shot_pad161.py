"""PAD-161 proof shot: "Apply my replaced assets on top" over a card PAD built.

    python scripts/shot_pad161.py <out_dir> <before|after>

THE REPORT.  A field report's Godzilla LE run stopped after the Stern logo
(PAD-159).  Asked which card was picked and whether the box was ticked, the
answer was: the card he had BUILT, the box ticked, and a few pictures changed
to newer ones since.  Ticked it failed, unticked it worked, and picking the
original card instead worked too.

WHAT THE PANE HOLDS.  NOTHING IS FED: the rig presses nothing but runs the
tab's own ``_prepare_overrides`` - the step Start takes before it launches -
on real inputs, and the pane is what that step logged.

* ``PAD161_CARD`` (B): godzilla_le 1.16 built by ``engine.write_image`` from a
  project where one banner kept its own size (the scene grew 8192 bytes) and
  another picture was replaced in place.
* ``PAD161_ASSETS`` (P2): the same project with the second picture changed
  again - "a few of the assets changed to newer ones".  Its
  ``.extract_source.json`` names the stock card it was extracted from.

Before the fix the set was prepared from B, where neither picture is where
the extract found it: v0.217.3 skips both and the run is refused (on v0.217.2
the newer picture was written into the scene's structure, which is the crash).
After it, the set is prepared from the stock card and run over B.

The override set goes to a scratch folder under the rig's own temp dir, never
the app's real ``spike2_overrides``.  Nothing is launched.

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, rolling log
sandboxed) follow scripts/take_screenshots.py -- see its header for why they
are what they are.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import threading
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
CARD = os.environ.get("PAD161_CARD", r"C:\tmp\pad161\B.raw")
ASSETS = os.environ.get("PAD161_ASSETS", r"C:\tmp\pad161\P2")
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad161bak"
GEOM = None
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 306

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad161_log_")
SET_DIR = tempfile.mkdtemp(prefix="pad161_set_")

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

import pinball_decryptor.app as app_mod  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.gui import emulate_tab  # noqa: E402

# A release published by another session mid-run would put an update banner in
# one shot of the pair and move every row under it.
app_mod.check_for_update = None
# Never the app's real staged set.
emulate_tab.overrides_dir = lambda: SET_DIR

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
    if GEOM:
        for _ in range(2):
            root.geometry(GEOM)
            root.update_idletasks()
    win._notebook.configure(height=NB_H)
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
WORK = {}


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(800)
def s_enter():
    global GEOM
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(980, root.winfo_screenheight() - 60)
    GEOM = "%dx%d+30+20" % (w, h)
    root.geometry(GEOM)
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


@step(4000)
def s_emulate_tab():
    win._notebook.select(win._tab_emulate)


@step(1500)
def s_inputs():
    panel = win._emulate_panel
    # No background card copy or boot-menu probe: nothing here is running
    # the rig, and both would reach for WSL.
    panel._precache_kick = lambda *a, **k: None
    panel._select_probe_kick = lambda *a, **k: None
    win.emulate_card_var.set(CARD)
    win.write_assets_var.set(ASSETS)
    win.emulate_overrides_var.set(True)
    panel._overrides_paint()


@step(1500)
def s_prepare():
    clear_log()
    panel = win._emulate_panel
    win.append_log("[emulate] Start: preparing your edits for %s" % CARD)

    def work():
        try:
            WORK["extra"] = panel._prepare_overrides(CARD, ASSETS)
        except Exception:
            WORK["error"] = traceback.format_exc()
        WORK["done"] = True

    threading.Thread(target=work, daemon=True).start()


def s_wait():
    if not WORK.get("done"):
        root.after(500, s_wait)
        return
    print("prepare returned %r %s" % (WORK.get("extra"),
                                      WORK.get("error") or ""), flush=True)
    root.after(1500, s_snap)


def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
        root.update_idletasks()
    snap("%s_emulate_overrides.png" % WHEN)
    if os.path.exists(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
    shutil.rmtree(SET_DIR, ignore_errors=True)
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        root.after(500, s_wait)
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


root.after(300000, lambda: root.destroy())
run()
try:
    app.run()
finally:
    try:
        if os.path.exists(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            print("settings restored", flush=True)
    except Exception:
        print("settings restore FAILED:\n%s" % traceback.format_exc(),
              flush=True)
