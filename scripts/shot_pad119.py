"""Capture the virtual playfield's bottom button row for PAD-119.

    python scripts/shot_pad119.py <out.png>

C FB's screenshot (2026-09-08, beatles on a 1080p screen) has the slot
picker sitting ON TOP of "Start" and the "Load" button sitting on top of
"Plunge": the state cluster is laid out left to right from the canvas's
left edge and the action cluster right to left from its right edge, and
on a narrow canvas the two meet in the middle.

WHY THIS RIG AND NOT take_screenshots.py.  The window is not a tab of the
app - it is tools/spike2_emu/playfield.py, its own Tk process, normally
started by watch.sh inside a run.  Everything it draws comes from the
title's tables, so a real one is handed to it (beatles, the ticket's own
title, from this machine's rootfs) and nothing else about a run is needed.

PAD_PF_SCALE IS THE WHOLE POINT.  The canvas is sized from the artwork
times a scale picked from the screen height, so a tall screen makes a
canvas wide enough for both clusters and hides the bug entirely - which is
why it reached a tester rather than a desk.  1.25 is the reporter's:
beatles' artwork is 336x710 and his canvas measured ~420 px wide.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "playfield.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

#: This machine's own built tables for the ticket's title.  Read-only, and
#: copied out before anything is imported: the window resolves TDIR at import
#: time, and pointing it at a UNC path would also make every helper it shells
#: out to take the \\wsl.localhost route.
SRC_TABLES = r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables\beatles"
GAME = "beatles"


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

STAGE = tempfile.mkdtemp(prefix="pad119_")
TABLES = os.path.join(STAGE, "dump", "tables", GAME)
if not os.path.isdir(SRC_TABLES):
    sys.exit("no tables for %s at %s - run the title once first" % (GAME, SRC_TABLES))
shutil.copytree(SRC_TABLES, TABLES)
os.makedirs(os.path.join(STAGE, "dump"), exist_ok=True)
log("tables staged at %s" % TABLES)

# A Windows PAD_ROOT keeps padpath off wslpath entirely, so the window opens
# with no WSL round trip at all.
os.environ["PAD_ROOT"] = STAGE
os.environ["PAD_TABLES"] = os.path.join(STAGE, "dump", "tables")
os.environ["PAD_GAME"] = GAME
os.environ["PAD_PF_SCALE"] = os.environ.get("PAD_PF_SCALE", "1.25")

sys.path.insert(0, RIG)
sys.argv = ["playfield.py", GAME, "--savestates"]

import tkinter as tk  # noqa: E402

from PIL import Image  # noqa: E402

import playfield  # noqa: E402

# The slot list is read off the rig with `wsl.exe -u root ... slots.sh list`.
# There is no run here to ask, and starting WSL to be told "nothing saved" is
# a 30 s wait for the answer this returns instantly.  Ten empty slots is what
# the reporter's picker showed anyway.
playfield.state_slots = lambda: {}

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


def snap(root, path):
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
    bih.biWidth, bih.biHeight = w, -h
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
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def main():
    playfield.SAVESTATES = True
    root = tk.Tk()
    root.title("%s - virtual playfield" % GAME)
    root.geometry("+40+20")
    log("layout usable: %s  artwork: %s"
        % (playfield.layout_is_usable(), playfield.layout_art()))
    view = playfield.Field(root)
    log("canvas %dx%d at scale %.2f"
        % (view.cv.winfo_reqwidth(), view.cv.winfo_reqheight(), view.scale))

    def report():
        """What the shot is of, in numbers, for the log beside it."""
        boxes = []
        for item in view.cv.find_all():
            if view.cv.type(item) != "window":
                continue
            wdg = view.cv.itemcget(item, "window")
            box = view.cv.bbox(item)
            label = root.nametowidget(wdg)
            try:
                text = label.cget("text")
            except tk.TclError:
                text = "<picker>"
            boxes.append((box, text))
        boxes.sort(key=lambda b: (b[0][1], b[0][0]))
        for box, text in boxes:
            log("  %-14s x %4d..%4d  y %4d..%4d" % (text, box[0], box[2],
                                                    box[1], box[3]))
        rows = {}
        for box, text in boxes:
            rows.setdefault(box[1], []).append((box, text))
        for _y, row in rows.items():
            row.sort(key=lambda b: b[0][0])
            for (a, at), (b, bt) in zip(row, row[1:]):
                if b[0] < a[2]:
                    log("  OVERLAP: %r and %r share x %d..%d"
                        % (at, bt, b[0], a[2]))

    def go():
        try:
            report()
            snap(root, OUT)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        finally:
            root.destroy()

    root.after(1500, go)
    root.mainloop()
    shutil.rmtree(STAGE, ignore_errors=True)


main()
