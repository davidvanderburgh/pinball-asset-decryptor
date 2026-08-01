"""Capture the two screens the blip-free default change is visible on.

    python scripts/shot_blipfree_default.py <out_dir> <before|after>

``audio_advanced``
    Advanced Audio Options, showing the "Blip-free callouts" checkbox in the
    state a fresh install gets it.

``blipfree_write_complete``
    The Write Complete modal for a James Bond Premium 1.06.0 write with one
    replaced sound -- the reporter's card.  Which sentence it carries is read
    from the LIVE ``engine._pathA_enabled()``, so the pair is a real A/B of
    the code change rather than two hand-typed strings.

Capture notes follow take_screenshots.py: DPI-unaware process, PrintWindow
(PW_RENDERFULLCONTENT) rather than a screen grab.  settings.json is backed up
and restored, so a run leaves no trace in the app's saved state.
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
# The shot must show the SHIPPED default, not whatever this machine has in its
# environment from an earlier experiment.
os.environ.pop("PAD_STERN_BLIP_FREE", None)
os.environ.pop("PAD_STERN_SKIP_KEYPATCH", None)
sys.path.insert(0, REPO)

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad11bak"

from PIL import Image  # noqa: E402

from pinball_decryptor.plugins.stern import engine as E  # noqa: E402
from pinball_decryptor.plugins.stern import pipeline as pl  # noqa: E402

# --- the completion-dialog text, built by the real helpers ------------------
# One replaced sound, validator bypassed: the reporter's James Bond card.
counts = (1, 0, 0, 0)
out_path = r"C:\Users\david\Desktop\james_bond_modded.raw"
if E._pathA_enabled():
    amode = ("blip-free", "")
else:
    amode = ("standard", getattr(
        E, "_BLIP_FREE_OFF_REASON",
        "turned off for this build (Advanced Audio Options / "
        "PAD_STERN_SKIP_KEYPATCH)"))
print("pathA enabled: %s -> audio_mode=%r" % (E._pathA_enabled(), amode),
      flush=True)
summary = ("Wrote %s to %s%s"
           % (pl._write_summary(counts), out_path, pl._audio_mode_note(amode)))
summary += pl._valpatch_note(("bypassed", ""))
print("--- dialog text ---\n%s\n-------------------" % summary, flush=True)

# --- capture plumbing -------------------------------------------------------
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
    """HWND of this process's visible top-level window titled *title*."""
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
    from tkinter import messagebox  # noqa: E402

    from pinball_decryptor.app import App  # noqa: E402

    app = App()
    root = app.root
    root.geometry("1000x700+40+40")
    root.update()

    def shot_audio_advanced():
        # A fresh install's state: no persisted overrides, so the dialog shows
        # the shipped defaults.
        app.window._audio_advanced = {}
        app.window._open_audio_advanced()
        # The Toplevel needs an event-loop turn or two to actually paint;
        # PrintWindow on a freshly-mapped window gives an empty client area.
        root.after(1500, capture_audio_advanced)

    def capture_audio_advanced():
        hwnd = find_dialog("Advanced Audio Options")
        if hwnd is None:
            print("!! Advanced Audio Options not found", flush=True)
        else:
            snap_hwnd(hwnd, "%s_audio_advanced.png" % WHEN)
            user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
        root.after(800, shot_write_complete)

    def shot_write_complete():
        root.after(1200, capture_write_complete)
        messagebox.showinfo("Write Complete", summary)

    def capture_write_complete():
        hwnd = find_dialog("Write Complete")
        if hwnd is None:
            print("!! Write Complete not found", flush=True)
        else:
            snap_hwnd(hwnd, "%s_blipfree_write_complete.png" % WHEN)
            user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
        root.after(600, root.destroy)

    root.after(2000, shot_audio_advanced)
    root.mainloop()
finally:
    if os.path.exists(SETTINGS_BAK):
        shutil.move(SETTINGS_BAK, SETTINGS)
        print("settings.json restored", flush=True)
