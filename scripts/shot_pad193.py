"""PAD-193: what the Multi-boot tips say about building a card on a Mac.

    python scripts/shot_pad193.py <out_dir> <before|after>

One shot, ``<before|after>_multiboot_mac_tips.png``: the Tips window for the
Multi-boot tab, scrolled to "Building one on a Mac".

A Sonic owner's log (2026-09-21, v0.229.1) ends with the container's own
compiler refusing to link the boot menu::

    ld: skipping incompatible .../libc.so.6 when searching for -l:libc.so.6
    make: *** [Makefile:176: /var/tmp/jjpselect_build/jjpselect] Error 1

His Mac has Apple silicon, so ``docker build`` made an arm64 Debian, and
jjpselect is a NATIVE x86-64 link against the card's own
``usr/lib/x86_64-linux-gnu`` - which the preview then runs with no emulator
in front of it.  The container is asked for ``linux/amd64`` now, and the
tips say so, in place of the line that promised "a minute or two" for an
image that on Apple silicon is built emulated.

NOTHING REAL IS TOUCHED: this opens the Tips window and nothing else - no
settings are written, no card is read, and the update check is stubbed so a
release published mid-run cannot move the text in one shot of the pair.
"""
import ctypes
import os
import sys
import tkinter as tk
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Taller than the window's own 560x520 default: the section is a paragraph,
#: and a pair of shots is only worth reading if the whole of it is in both.
GEOM = "700x540+40+30"
HEADING = "Building one on a Mac"

os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)


def log(msg):
    print(msg, flush=True)


log("code under test: %s" % REPO)

from PIL import Image                                       # noqa: E402

from pinball_decryptor.app import App                       # noqa: E402
from pinball_decryptor.gui.help_dialog import TabHelpWindow  # noqa: E402

App._check_for_update = lambda self: None

app = App()
root = app.root
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


def snap(widget, name):
    widget.update()
    hwnd = user32.GetAncestor(widget.winfo_id(), 2)      # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)                  # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h                   # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


TIPS = {}


@step(1500)
def s_open_tips():
    root.geometry("1000x700+760+40")
    win = TabHelpWindow(root, lambda: app.window._current_theme)
    dlg = win.show("Multi-boot")
    dlg.geometry(GEOM)
    TIPS["win"], TIPS["dlg"] = win, dlg


@step(600)
def s_scroll_to_the_section():
    dlg, text = TIPS["dlg"], TIPS["win"]._text
    idx = text.search(HEADING, "1.0", tk.END)
    if not idx:
        raise RuntimeError("no %r heading in the Multi-boot tips" % HEADING)
    # yview(index), not see(index): this puts the heading at the TOP of the
    # widget, so the two shots start the paragraph in the same place even
    # though the paragraph itself is a different length in each.
    text.yview(idx)
    dlg.update_idletasks()
    log("heading at %s; first line: %s"
        % (idx, text.get(idx, "%s lineend" % idx)))


@step(600)
def s_snap():
    snap(TIPS["dlg"], "multiboot_mac_tips")


def run(i=0):
    if i >= len(STEPS):
        root.after(200, finish)
        return
    delay, fn = STEPS[i]

    def go():
        try:
            fn()
        except Exception:
            log("!! step %s failed:\n%s" % (fn.__name__, traceback.format_exc()))
        run(i + 1)

    root.after(delay, go)


def finish():
    try:
        root.destroy()
    except Exception:
        pass


run()
root.mainloop()
