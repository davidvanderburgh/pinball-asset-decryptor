"""PAD-1036 proof shots: the window shown while Restart to update swaps
versions, off the desktop.

    python scripts/shot_pad1036.py <out_dir> [--before]

Starts the real splash (core/update_splash.start_splash, the PowerShell/WPF
window) pinned off every screen, waits for its window, shoots it with
PrintWindow a moment into the animation, then closes it the way the new
version does (update_splash.dismiss) and checks the process is gone.  Two
moments: the plain wait, and the long wait (its hint and Close button,
with the waits shortened to seconds).  Needs pywin32 and Pillow.
"""
import ctypes
import os
import sys
import time

from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from pinball_decryptor.core import update_splash as sp   # noqa: E402

OUT = sys.argv[1]
PRE = "before_" if "--before" in sys.argv else "after_"
u = ctypes.windll.user32
u.SetProcessDPIAware()


def shoot(hwnd, path):
    import win32gui
    import win32ui
    r = (ctypes.c_long * 4)()
    u.GetWindowRect(ctypes.c_void_p(hwnd), r)
    w, h = r[2] - r[0], r[3] - r[1]
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    u.PrintWindow(ctypes.c_void_p(hwnd), mem.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    img.save(path)
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(bmp.GetHandle())
    return w, h


def run(name, delay, **timing):
    title = "PAD-1036 shot " + name
    ok, proc = sp.start_splash("1.356.0", title=title, offscreen=True,
                               **timing)
    if not ok:
        sys.exit("splash did not start: %s" % proc)
    t0 = time.time()
    hwnd = 0
    while time.time() - t0 < 30 and not hwnd:
        if proc.poll() is not None:
            sys.exit("the splash exited with %s before showing" % proc.returncode)
        hwnd = sp.find_window(title)
        time.sleep(0.1)
    if not hwnd:
        proc.kill()
        sys.exit("no splash window after 30 s")
    shown = time.time() - t0
    time.sleep(delay)
    path = os.path.join(OUT, PRE + name + ".png")
    # the first paint can come a moment after the window exists (a cold
    # WPF load): a black capture is shot again
    for _ in range(40):
        w, h = shoot(hwnd, path)
        if Image.open(path).convert("L").getextrema()[1] > 40:
            break
        time.sleep(0.25)
    else:
        sys.exit("the splash never painted")
    assert sp.dismiss(title)
    proc.wait(15)
    print("%s: %dx%d, window up after %.1f s, closed on dismiss (rc %s)"
          % (path, w, h, shown, proc.returncode))


os.makedirs(OUT, exist_ok=True)
run("update_splash", 1.5)
run("update_splash_waiting", 3.0, hint_after=1, give_up_after=2)
