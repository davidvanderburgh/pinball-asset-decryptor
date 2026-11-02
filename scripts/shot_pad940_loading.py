"""PAD-940 proof shots: the Visual Pinball loading window, off the desktop.

    python scripts/shot_pad940_loading.py <tools/spike2_emu/vpx> <out_dir> <pythonw.exe>

Starts padloading.py pinned off-screen (--rect), feeds it a run log line by
line (the steps of a real start), shoots each step with PrintWindow, checks
the foreground window never changes (Visual Pinball pauses when it does), and
that `up` closes it at once and `failed` after showing why. Needs pywin32 and
Pillow. The first PrintWindow of a run can come back black (capture timing).
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


def run(case):
    d = tempfile.mkdtemp(prefix="padloading-")
    logf, status = os.path.join(d, "run.log"), os.path.join(d, "status.txt")
    open(logf, "w").write("[watch] an earlier run's line\n[watch] running. CLOSE\n")
    fg0 = u.GetForegroundWindow()
    wrap = [os.environ["DRIVE_WRAP"], os.environ["DRIVE_ERR"] + case + ".txt"] if os.environ.get("DRIVE_WRAP") else []
    p = subprocess.Popen([PYW] + wrap + [os.environ.get("DRIVE_SCRIPT") or os.path.join(KIT, "padloading.py"), "jurassic_park_pro", logf, status,
                          "--expect", "79", "--parent", str(os.getpid()), "--rect", str(X), str(Y), str(W), str(H)])
    time.sleep(3)
    hwnd = find("PAD - starting jurassic_park_pro")
    print(case, "window:", bool(hwnd), "focus kept:", u.GetForegroundWindow() == fg0, flush=True)
    if case == "ok":
        shoot(hwnd, os.path.join(OUT, "loading_1_linux.png"))
        for lines, name in ((["[card] evicting cached Godzilla", "[card] caching jp.raw", "[card]   mounting jp p3"], "loading_2_card"),
                            (["[card] title: jurassic_park_pro", "[watch] cfg GAME=jp", "[watch] starting renderer (it opens"], "loading_3_screen"),
                            (["[watch] game window opened 1452x845", "[watch] starting jurassic_park_pro (boot", "[watch] waiting for the game to start..."], "loading_4_game")):
            open(logf, "a").write("\n".join(lines) + "\n")
            time.sleep(1.5)
            shoot(hwnd, os.path.join(OUT, name + ".png"))
        print(case, "focus kept after steps:", u.GetForegroundWindow() == fg0, flush=True)
        open(status, "w").write("up")
    else:
        shoot(hwnd, os.path.join(OUT, "loading_5_prefail.png"))
        open(status, "w").write("failed The emulator stopped before the game came up. Its log: C:\\...\\padvpx-jurassic_park_pro.log")
        time.sleep(2.5)
        hwnd = find("x") or hwnd
        shoot(hwnd, os.path.join(OUT, "loading_5_failed.png"))
    t = time.time()
    for _ in range(40):
        if not find("x"):
            print(case, "window gone after %.1f s" % (time.time() - t), flush=True)
            break
        time.sleep(0.25)
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()
    print(case, "closed after %.1f s, rc=%s" % (time.time() - t, p.returncode), flush=True)





run("ok")
run("failed")
