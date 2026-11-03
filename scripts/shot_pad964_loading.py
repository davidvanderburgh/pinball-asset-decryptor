"""PAD-964 proof shots: the Visual Pinball loading window names what the
card image costs the disk, off the desktop.

    python scripts/shot_pad964_loading.py <tools/spike2_emu/vpx> <out_dir> <pythonw.exe> [--after]

Starts padloading.py pinned off-screen (--rect), feeds it the lines a real
start writes (cardmount.sh's own words) and shoots two moments with
PrintWindow: the card image being copied into the cache (its progress
line), and a start with no room for the copy (the game reads the image
where it lies). Needs pywin32 and Pillow.
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

COPY = [
    "[card-check] room: Copying the card image (6.1 GB) into the emulator's cache, this first start only (41.5 GB free there)",
    "[card] caching batman-1_14_0.Release.8G.sdcard.raw to the WSL disk in the background",
    "[card]   (first run only; next boot of this card is native speed)",
    "[card] copying batman-1_14_0.Release.8G.sdcard.raw: 2114 / 7497 MB (28%)",
]
FULL = [
    "[card-check] full: No room in the cache for the card image (6.1 GB needed with 8.0 GB kept free, 7.3 GB free): the game reads it where it lies, a slow start",
    "[card] disk too full to cache (7 GB free, want 15 GB) and nothing evictable (4 library cards kept) - running off the original",
    "[card] mounting batman-1_14_0.Release.8G.sdcard.raw p3 at offset 364904448 (read only)",
]


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
    p = subprocess.Popen([PYW, os.path.join(KIT, "padloading.py"), "batman", logf, status,
                          "--expect", "30", "--parent", str(os.getpid()), "--rect", str(X), str(Y), str(W), str(H)])
    time.sleep(3)
    hwnd = find("PAD - starting batman")
    print(name, "window:", bool(hwnd), flush=True)
    if status_line:
        open(status, "w").write(status_line)
    open(logf, "a").write("\n".join(lines) + "\n")
    time.sleep(2)
    shoot(hwnd, os.path.join(OUT, PRE + name + ".png"))
    open(status, "w").write("up")
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()


run("vpx_loading_copy", COPY,
    "" if PRE == "before_" else "")
run("vpx_loading_full", FULL)
