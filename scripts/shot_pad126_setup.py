"""Capture the Emulate tab's prerequisite notice for PAD-126.

    python scripts/shot_pad126_setup.py <out.png>

A variant of shot_emulate_setup.py (same PrintWindow, same DPI-unaware
capture, same settings backup, same synthetic facts) for the package
this ticket adds.

WHY THE FACTS ARE SYNTHETIC.  The notice is built from what
setupcheck.sh finds in WSL, and this machine has every package - so a
live capture shows an empty tab in both shots and proves nothing.
_setup_apply is fed the machine that REPORTED the bug instead: every
emulator package present (his rootfs was already unpacked and the ARM
cross compiler built the menu program's sources happily), and no `make`,
which is what the boot menu program is built by.  A build of the app
from before this ticket does not know that key at all, and says nothing
about it - which is exactly the silence being captured.
"""
import ctypes
import os
import shutil
import sys
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak126"

#: The reporter's machine, as setupcheck.sh would report it.  `make` is the
#: fact this ticket adds; a build of the app from before it ignores the key
#: entirely, which is the silence the "before" shot is of.
FACTS = {"qemu": "1", "armgcc": "1", "nativecc": "1", "debugfs": "1",
         "fuse": "1", "ffmpeg": "1", "make": "0",
         "binfmt": "1", "iswsl": "1", "wslconf": "1",
         "distro": "ubuntu 24.04 noble",
         "components": "main multiverse restricted universe",
         "indexed": "1", "nocand": "", "universe": "1", "xrel": ""}


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

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


def _print_window(hwnd, w, h):
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
    return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)


def snap(path):
    """shot_multiboot_selector.py's tiled capture.  THE WINDOW IS TALLER
    THAN THIS DESKTOP on purpose: the notice is the last widget packed into
    the tab page, and a page short of its requested height is handed one
    pixel and never mapped - which is a capture that succeeds with the
    notice simply not in it.  Tk only paints what Windows says is visible,
    so the window is walked across the screen a tile at a time."""
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    sw, sh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)

    def offsets(size, span):
        if size <= span:
            return [0]
        return list(range(0, size - span, span)) + [size - span]

    tiles = [(ox, oy) for oy in offsets(h, sh) for ox in offsets(w, sw)]
    if len(tiles) == 1:
        img = _print_window(hwnd, w, h)
    else:
        log("window %dx%d overhangs the %dx%d desktop: %d tiles"
            % (w, h, sw, sh, len(tiles)))
        img = Image.new("RGB", (w, h))
        SWP = 0x0001 | 0x0004 | 0x0010   # NOSIZE | NOZORDER | NOACTIVATE
        for ox, oy in tiles:
            user32.SetWindowPos(hwnd, 0, vx - ox, vy - oy, 0, 0, SWP)
            for _ in range(3):
                root.update()
                time.sleep(0.15)
            tile = _print_window(hwnd, w, h)
            box = (ox, oy, min(w, ox + sw), min(h, oy + sh))
            img.paste(tile.crop(box), box[:2])
        user32.SetWindowPos(hwnd, 0, wrect.left, wrect.top, 0, 0, SWP)
        root.update()
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    # TALL ENOUGH FOR THE NOTICE, AND THE LOG PANE GIVES UP THE HEIGHT (see
    # shot_emulate_setup.py: the notice is the last widget packed into the
    # tab frame, and a frame short of its requested height never maps it).
    root.maxsize(root.winfo_screenwidth() + 100,
                 root.winfo_screenheight() + 600)
    root.geometry("1100x1400+40+40")


@step(6000)
def s_emulate_tab():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_facts():
    """Hand the panel the reporter's machine.

    The panel's own probe runs against THIS PC and would overwrite it, so
    the real one is stubbed out first - the widget path is the same either
    way, _setup_apply is what draws the notice.
    """
    panel = win._emulate_panel
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._setup_apply(dict(FACTS))
    # THE PAGE ASKS FOR WHAT IT NEEDS; the log pane below is the one thing
    # with expand=True, so it is what gives the height up.
    win._notebook.configure(height=win._notebook.winfo_reqheight()
                            + panel._setup_msg.winfo_reqheight() + 60)
    root.update_idletasks()
    # SAY WHETHER IT IS ACTUALLY ON SCREEN.  An unmapped label is invisible
    # in the log as well as in the shot; a build from before this ticket
    # reports an empty text, which is the point of the pair.
    msg = panel._setup_msg
    log("notice mapped=%s h=%s text=%r"
        % (msg.winfo_ismapped(), msg.winfo_height(), msg.cget("text")))


@step(2000)
def s_snap():
    snap(OUT)


@step(500)
def s_done():
    root.destroy()


def run_steps(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            log("step %d: %s" % (i, fn.__name__))
            fn()
        except Exception:
            log("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))
        run_steps(i + 1)

    root.after(delay, _go)


root.after(120000, lambda: root.destroy())
run_steps()
try:
    app.run()
finally:
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
