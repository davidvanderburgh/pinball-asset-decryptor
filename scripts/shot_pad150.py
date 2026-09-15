"""PAD-150 proof shot: what the log says as an in-app update closes the app.

    python scripts/shot_pad150.py <out_dir> <before|after>

THE REPORT.  DragonRR, after every in-app update: the emulator's game window
has no picture until he restarts WSL.  His log from the first run after one
said ``WSL session up 0h 2m`` - a VM started just before the update and still
running across it - while ``[padglhost] picture: FIRST at frame 81`` said the
game was drawing.  Restart WSL cured it every time, without reopening PAD.

WHAT THE PANE HOLDS.  Both shots run the REAL update path from "Update
available" to the moment the app closes: ``_handle_update_check_result`` puts
up the banner and its log lines, ``_launch_downloaded_installer`` writes the
"Installing ..." line.  Three things are stubbed, because each would end the
shot or change the machine taking it:

  * ``launch_installer_windows`` answers True instead of running a setup exe;
  * ``_on_close`` does not destroy the window.  In the after shot it runs the
    one step of the real ``_on_close`` this change added,
    ``_restart_wsl_for_update``;
  * that step's WSL is fake - Ubuntu running, shutdown succeeds - so the shot
    does not shut down WSL on the machine taking it.

Capture mechanics follow scripts/shot_pad117.py (PrintWindow, DPI-unaware,
settings backed up, rolling log sandboxed).
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
SETTINGS_BAK = SETTINGS + ".pad150bak"
GEOM = None
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 275
NEW = "0.214.1"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad150_log_")

from PIL import Image  # noqa: E402

import pinball_decryptor.app as app_mod  # noqa: E402
from pinball_decryptor.core import updater, wsl_disk  # noqa: E402

app = app_mod.App()
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


class _Dialog:
    def close(self):
        pass


def _fake_close():
    """The part of _on_close that is under test, and nothing that ends the
    shot.  Absent in the before build, which had no such step."""
    step = getattr(app, "_restart_wsl_for_update", None)
    if step is not None and getattr(app, "_restart_wsl_on_close", False):
        step()


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
def s_update():
    clear_log()
    app_mod.launch_installer_windows = lambda path: True
    app._on_close = _fake_close
    # The fake WSL for the after shot.  Module attributes, because that is
    # where restart_wsl_for_update looks them up at call time.
    wsl_disk.running_distros = lambda: ["Ubuntu"]
    wsl_disk.default_distro_name = lambda: "Ubuntu"
    if hasattr(updater, "_wsl_shutdown"):
        updater._wsl_shutdown = lambda: None
    win.append_log("Checking for updates...", "info")
    url = "https://github.com/davidvanderburgh/pinball-asset-decryptor/" \
          "releases/tag/v" + NEW
    installer = {"kind": "windows-installer", "url": url + ".exe",
                 "name": "PAD_v%s_Windows.exe" % NEW, "size": 1}
    app._handle_update_check_result((NEW, url, "", installer), False)
    app._launch_downloaded_installer(
        _Dialog(), os.path.join(tempfile.gettempdir(), installer["name"]), NEW)
    root.update_idletasks()


@step(1500)
def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
        root.update_idletasks()
        print("pane:\n" + t.get("1.0", "end-1c"), flush=True)
    snap("%s_update_log.png" % WHEN)


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

    def _go():
        try:
            print("step %d: %s" % (i, fn.__name__), flush=True)
            fn()
        except Exception:
            print("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()),
                  flush=True)
        run(i + 1)

    root.after(delay, _go)


root.after(120000, lambda: root.destroy())
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
