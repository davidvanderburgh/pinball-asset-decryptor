"""PAD-79 proof shot: the Replace Video tab on a Spooky Halloween extract.

Launches the real GUI against a Halloween (code_H78.pkg) extract, opens
Replace Video, and captures the slot list.

    python scripts/shot_spooky_video.py <extract-dir> <out.png>

Same capture rules as scripts/take_screenshots.py -- PrintWindow
(PW_RENDERFULLCONTENT) on a deliberately DPI-unaware process, settings.json
backed up and restored -- see that file's header for why.
"""
import ctypes
import json
import os
import shutil
import sys
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad79bak"

if len(sys.argv) != 3:
    sys.exit(__doc__)
EXTRACT = os.path.abspath(sys.argv[1])
OUT_PNG = os.path.abspath(sys.argv[2])
if not os.path.isdir(EXTRACT):
    sys.exit("No extract folder at %s" % EXTRACT)
os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)

# Point the app's saved state at the Halloween extract so it comes up on
# Spooky with the project already loaded.
shutil.copy2(SETTINGS, SETTINGS_BAK)
with open(SETTINGS, encoding="utf-8") as f:
    _cfg = json.load(f)
_cfg["last_manufacturer"] = "spooky"
_sp = _cfg.setdefault("manufacturers", {}).setdefault("spooky", {})
_sp["extract_output"] = EXTRACT
_sp["write_assets"] = EXTRACT
# So the title bar's game badge reads Halloween rather than whatever the
# previous session left selected.
_PKG = r"C:\Users\david\OneDrive\Desktop\code_H78.pkg"
if os.path.isfile(_PKG):
    _sp["extract_input"] = _PKG
    _sp["write_original"] = _PKG
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(_cfg, f, indent=2)

os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

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
    bih.biWidth, bih.biHeight = w, -h  # top-down
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
    print("snapped %s (%dx%d)" % (path, img.width, img.height), flush=True)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(900, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))


@step(6000)
def s_spooky():
    mfr = next(m for m in app._manufacturers if m.key == "spooky")
    app._on_manufacturer_change(mfr)


@step(2500)
def s_input():
    # Detection on the Extract input is what names the game in the title
    # bar; set it explicitly so the shot says Halloween.
    if os.path.isfile(_PKG):
        win.extract_input_var.set(_PKG)
    win.write_assets_var.set(EXTRACT)


@step(2500)
def s_video_tab():
    win._notebook.select(win._tab_video)


@step(2500)
def s_scan():
    win._scan_video_slots_async()


# The scan lists instantly; ffprobe fills length/resolution on a background
# pass, so give that a beat before selecting a row.
@step(9000)
def s_pick():
    tree = win._video_tree
    rows = tree.get_children("")
    print("video rows: %d" % len(rows), flush=True)
    target = None
    for iid in rows:
        if "bg_school" in str(iid).lower():
            target = iid
            break
    if target is None and rows:
        target = rows[min(8, len(rows) - 1)]
    if target:
        tree.see(target)
        tree.focus(target)
        tree.selection_set(target)


@step(6000)
def s_snap():
    snap(OUT_PNG)


@step(1200)
def s_quit():
    try:
        root.destroy()
    except Exception:
        pass


def _chain(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _run():
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()
        _chain(i + 1)
    root.after(delay, _run)


try:
    _chain()
    root.mainloop()
finally:
    shutil.copy2(SETTINGS_BAK, SETTINGS)
    os.remove(SETTINGS_BAK)
    print("settings restored", flush=True)
