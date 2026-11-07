"""PAD-1039 proof shots: where the Restart to update splash lands on the
primary monitor.

    python scripts/shot_pad1039.py <out_dir> [--before]

Starts the real splash script (core/update_splash.splash_script) twice: once
at its real place but fully transparent (Opacity 0, so nothing shows on the
desktop) to read where Windows put it, and once off every screen to shoot
its picture with PrintWindow.  Draws the primary monitor to scale with its
centre marked and the picture pasted where the window sat.  --before runs
main's code, which centred the splash on the app's window: the app's real
window if one is up, else a window left of centre like David's.
Needs pywin32 and Pillow.
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from pinball_decryptor.core import update_splash as sp   # noqa: E402

OUT = sys.argv[1]
BEFORE = "--before" in sys.argv
u = ctypes.windll.user32
u.SetProcessDPIAware()
SW, SH = u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def rect(hwnd):
    r = (ctypes.c_long * 4)()
    u.GetWindowRect(ctypes.c_void_p(hwnd), r)
    return tuple(r)


def app_rect():
    """The running app's main window, or a stand-in left of centre."""
    import win32gui
    found = []

    def each(h, _):
        t = win32gui.GetWindowText(h)
        if (win32gui.IsWindowVisible(h) and t.startswith("Pinball Asset Decryptor")
                and "updating" not in t):
            found.append(h)
    win32gui.EnumWindows(each, None)
    if found:
        return rect(found[0]), True
    w, h = SW * 55 // 100, SH * 70 // 100
    left = SW * 8 // 100
    top = (SH - h) // 2
    return (left, top, left + w, top + h), False


def start(text):
    fd, path = tempfile.mkstemp(prefix="pad1039-", suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)
    return subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
         "-ExecutionPolicy", "Bypass", "-File", path],
        creationflags=subprocess.CREATE_NO_WINDOW)


def wait_window(title, proc):
    t0 = time.time()
    while time.time() - t0 < 30:
        h = sp.find_window(title)
        if h:
            return h
        if proc.poll() is not None:
            sys.exit("splash exited with %s" % proc.returncode)
        time.sleep(0.1)
    proc.kill()
    sys.exit("no splash window")


def shoot(hwnd):
    import win32gui
    import win32ui
    l, t, r, b = rect(hwnd)
    w, h = r - l, b - t
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
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(bmp.GetHandle())
    return img


app, real_app = app_rect()
kw = {}
if BEFORE:
    kw["center"] = ((app[0] + app[2]) // 2, (app[1] + app[3]) // 2)

# 1. the real place, invisible
t_place = "PAD-1039 place"
text = sp.splash_script("1.356.1", title=t_place, **kw)
text = text.replace("$win.ShowDialog()", "$win.Opacity = 0; $win.ShowDialog()")
p1 = start(text)
h1 = wait_window(t_place, p1)
time.sleep(1.5)
where = rect(h1)
sp.dismiss(t_place)

# 2. the picture, off screen
t_pic = "PAD-1039 picture"
p2 = start(sp.splash_script("1.356.1", title=t_pic, offscreen=True))
h2 = wait_window(t_pic, p2)
time.sleep(2.0)
for _ in range(40):
    pic = shoot(h2)
    if pic.convert("L").getextrema()[1] > 40:
        break
    time.sleep(0.25)
sp.dismiss(t_pic)

# 3. the primary monitor to scale
mon = Image.new("RGB", (SW, SH), (44, 62, 80))
d = ImageDraw.Draw(mon)
if BEFORE:
    d.rectangle(app, outline=(150, 160, 175), width=6)
    d.text((app[0] + 16, app[1] + 12),
           "app window" + ("" if real_app else " (stand-in)"),
           fill=(200, 205, 215))
pw, ph = where[2] - where[0], where[3] - where[1]
mon.paste(pic.resize((pw, ph)), (where[0], where[1]))
cx, cy = SW // 2, SH // 2
d.line((cx, 0, cx, SH), fill=(255, 80, 80), width=3)
d.line((0, cy, SW, cy), fill=(255, 80, 80), width=3)
d.rectangle((0, 0, SW - 1, SH - 1), outline=(230, 230, 230), width=4)
scx, scy = (where[0] + where[2]) / 2, (where[1] + where[3]) / 2
note = ("primary monitor %dx%d, centre %d,%d; splash centre %.0f,%.0f "
        "(off by %+.0f, %+.0f)" % (SW, SH, cx, cy, scx, scy, scx - cx, scy - cy))
d.text((20, SH - 40), note, fill=(255, 255, 255))
name = ("before_" if BEFORE else "after_") + "splash_position.png"
mon.resize((SW // 2, SH // 2)).save(os.path.join(OUT, name))
print(name, note, "app", app, "real app window" if real_app else "stand-in")
