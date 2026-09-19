"""PAD-181 proof shot: the Advanced Audio Options dialog, whose "Blip-free
callouts" and "Allow replacements longer than the original" notes were
reworded (they said no real machine had booted such a card; both are now
confirmed working, so they are described as opt-in, with the ~45 min sound-
bank budget spelled out).

    python scripts/shot_pad181.py <out_dir> <before|after>

The dialog is captured in a fresh install's state (no persisted overrides).
To import a DIFFERENT checkout of the package (e.g. HEAD for the "before"
shot), set ``PAD181_REPO`` to that repo root.

Capture mechanics follow scripts/shot_blipfree_default.py: DPI-unaware
process, PrintWindow (PW_RENDERFULLCONTENT), settings.json backed up and
restored so a run leaves no trace.
"""
import ctypes
import os
import shutil
import sys
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]

REPO = os.environ.get("PAD181_REPO") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
os.environ.pop("PAD_STERN_AUDIO_GROW", None)
os.environ.pop("PAD_STERN_BLIP_FREE", None)
sys.path.insert(0, REPO)
print("importing package from %s" % REPO, flush=True)

from PIL import Image  # noqa: E402

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad181bak"

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


def find_dialog(title):
    found = []
    pid = wintypes.DWORD()
    me = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != me or not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value == title:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def snap_hwnd(hwnd, name):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)      # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h       # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print("snapped %s (%dx%d)" % (path, img.width, img.height), flush=True)


if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
try:
    from pinball_decryptor.app import App  # noqa: E402

    app = App()
    root = app.root
    root.geometry("1000x760+40+40")
    root.update()

    def open_dialog():
        app.window._audio_advanced = {}     # fresh-install defaults
        app.window._open_audio_advanced()
        root.after(1800, capture)

    def capture():
        hwnd = find_dialog("Advanced Audio Options")
        if hwnd is None:
            print("!! Advanced Audio Options not found", flush=True)
        else:
            snap_hwnd(hwnd, "%s_audio_advanced.png" % WHEN)
            user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
        root.after(500, root.destroy)

    root.after(2000, open_dialog)
    root.after(30000, root.destroy)         # watchdog
    root.mainloop()
finally:
    if os.path.exists(SETTINGS_BAK):
        shutil.move(SETTINGS_BAK, SETTINGS)
        print("settings.json restored", flush=True)
