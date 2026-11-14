"""PAD-1247 proof shot: the Visual Pinball loading window 70 s into a Rush LE
start whose game is up inside WSL but which Windows cannot reach.

    python scripts/shot_pad1247_loading.py <tools/spike2_emu/vpx> <out_dir> <pythonw.exe> [--after]

Before: the window just keeps waiting (the reporter's run sat there). After:
the bridge's own words for it (padcontroller.WSL_STUCK), as its status file
says them. Pinned off-screen (--rect), shot with PrintWindow. Needs pywin32
and Pillow.
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image

KIT = sys.argv[1]
OUT = sys.argv[2]
PYW = sys.argv[3]
PRE = "after_" if "--after" in sys.argv else "before_"
u = ctypes.windll.user32
u.SetProcessDPIAware()
X, Y, W, H = -5000, 100, 1360, 768

def find(title):
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, buf, 256)
        r = (ctypes.c_long * 4)(); u.GetWindowRect(ctypes.c_void_p(h), r)
        if u.IsWindowVisible(h) and r[0] == X and r[2] - r[0] == W:
            found.append(h)
        return True
    u.EnumWindows(proc(cb), 0)
    return found[0] if found else 0


def shoot(hwnd, path):
    import win32gui
    import win32ui
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, W, H)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    img.save(path)
    mem.DeleteDC(); src.DeleteDC(); win32gui.ReleaseDC(hwnd, hdc); win32gui.DeleteObject(bmp.GetHandle())


def run(name, lines, status_line=""):
    d = tempfile.mkdtemp(prefix="padloading-")
    logf, status = os.path.join(d, "run.log"), os.path.join(d, "status.txt")
    open(logf, "w").write("[watch] an earlier run's line\n[watch] running. CLOSE\n")
    p = subprocess.Popen([PYW, os.path.join(KIT, "padloading.py"), "rush_le", logf, status,
                          "--expect", "22", "--parent", str(os.getpid()), "--rect", str(X), str(Y), str(W), str(H)])
    time.sleep(3)
    hwnd = find("PAD - starting rush_le")
    print(name, "window:", bool(hwnd), flush=True)
    if status_line:
        open(status, "w", encoding="utf-8").write(status_line)
    open(logf, "a").write("\n".join(lines) + "\n")
    time.sleep(2)
    shoot(hwnd, os.path.join(OUT, PRE + name + ".png"))
    open(status, "w", encoding="utf-8").write("up")
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()



sys.path.insert(0, KIT)
sys.path.insert(0, os.path.dirname(KIT))
LINES = [
    "[card-check] cached: The card image is in the emulator's cache",
    "[card] rush_le-1_19_0.Release.16G.sdcard.raw is in the card library - booting it from there",
    "[card] mounting rush_le-1_19_0.Release.16G.sdcard.raw p3 at offset 364904448 (read only)",
    "[card] title: rush_le",
    "[watch] starting renderer (it opens the game window; the picture arrives",
    "[watch] starting rush_le (boot to the first picture takes ~15 s)",
    "[watch] waiting for the game to start...",
    "[watch] running. CLOSE THE WINDOW to stop (or press Ctrl-C here).",
    "[event] [padplay] no data for 25 s - transport presumed dead, exiting for a fresh connection",
    "[event] [play] Windows player exited; restarting it",
]
if PRE == "after_":
    import padcontroller
    run("vpx_loading", LINES, "failed " + padcontroller.WSL_STUCK)
else:
    run("vpx_loading", LINES)
