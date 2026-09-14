"""Capture the virtual playfield's BALLS section on the key panel, PAD-134.

    python scripts/shot_pad134_balls.py <out.png>

David, 2026-09-13, after the ball-feeder fix: *"i think our ball in and out
feedback on the switch matrix is a little confusing from the ui perspective
too. what we did on the jjp virtual playfield does look much better."*  The
JJP window says where the balls are in one line (trough, in play, fed), has a
Plunge and a Drain button, and shows the ball keeper's newest three messages
under them.  The Spike 2 panel had six clickable dots whose meaning depended on
whether the dot you clicked was full, with the stack - not the dot - deciding
which switch moved.

WHAT THE PAIR SHOWS: godzilla_le (DragonRR's title, this box's own built
tables), a ball in play with five home, the key panel up, and the feeder's own
recent lines published.  Everything is a hand-written block, the recipe
PAD-119/120/128 use: `PAD_SW_FILE` for the switch block, a version-4 padled
block so the window reads as a live run, `PAD_PF_BINDS` for the key-bind export
the panel is built from, and `PAD_PF_BALL` for the feeder's status file.  The
before tree simply has no reader for the last one.
"""
import ctypes
import os
import shutil
import struct
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "balls.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

GAME = "godzilla_le"
SRC_TABLES = (r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables\%s"
              % GAME)


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
STAGE = tempfile.mkdtemp(prefix="pad134b_")
TABLES = os.path.join(STAGE, "dump", "tables", GAME)
if not os.path.isdir(SRC_TABLES):
    sys.exit("no tables for %s at %s - run the title once first"
             % (GAME, SRC_TABLES))
shutil.copytree(SRC_TABLES, TABLES)
BLOCK = os.path.join(STAGE, "dump", "padsw")
BINDS = os.path.join(STAGE, "dump", "padbinds")
BALL = os.path.join(STAGE, "dump", "padball")

os.environ["PAD_ROOT"] = STAGE
os.environ["PAD_TABLES"] = os.path.join(STAGE, "dump", "tables")
os.environ["PAD_GAME"] = GAME
os.environ["PAD_SW_FILE"] = BLOCK
os.environ["PAD_PF_BINDS"] = BINDS
os.environ["PAD_PF_BALL"] = BALL

sys.path.insert(0, RIG)
sys.argv = ["playfield.py", GAME]

import tkinter as tk  # noqa: E402

from PIL import Image  # noqa: E402

import padsw  # noqa: E402
import trough  # noqa: E402

import playfield  # noqa: E402

ROWS = trough.load_list(os.path.join(TABLES, "switch_list.txt"))
POSITIONS, HOW = trough.find(ROWS)
TROUGH_IDS = [P["id"] for P in POSITIONS]
DOOR = next((r["id"] for r in ROWS
             if r.get("node") == 0 and r.get("bit") == 23), None)

#: padglhost's compiled bind table (padglhost.c binds[]), in the tab-separated
#: shape binds_export() writes and keybinds.py reads: key, flags (c = cabinet,
#: t = toggle), ids, label.  The trough row carries this title's own ids.
BINDS_ROWS = [
    ("Enter", "c", "25", "Service Select"),
    ("KP Ent", "c", "25", "Service Select"),
    ("=", "c", "26", "Service Plus"),
    ("-", "c", "27", "Service Minus"),
    ("Bksp", "c", "28", "Service Back"),
    ("Esc", "c", "28", "Service Back"),
    ("1", "c", "36", "Start Button"),
    ("5", "c", "39", "Left Coin"),
    ("Space", "c", "34", "Action Button"),
    ("T", "c", "38", "Tilt Pendulum"),
    ("C", "ct", str(DOOR or 33), "Coin Door Closed"),
    ("Left", "-", "60", "Left Flipper"),
    ("Right", "-", "59", "Right Flipper"),
    ("Up", "-", "61", "Upper Left Flipper"),
    ("F", "-", "62", "Shooter Lane"),
    ("W", "-", "47", "Left Spinner"),
    ("E", "-", "49", "Pop Bumper"),
    ("A", "-", "64", "Left Slingshot"),
    ("S", "-", "63", "Right Slingshot"),
    ("D", "-", "53", "Right Scoop"),
    ("Z", "-", "55", "Left Outlane"),
    ("X", "-", "58", "Right Outlane"),
    ("B", "t", ",".join(str(i) for i in TROUGH_IDS), "6 balls in trough"),
]

#: What ballfeed.py publishes: its count, then its newest lines, oldest first.
#: The words are the feeder's own sentences from a real harness run.
BALL_LINES = [
    "fed 3",
    "trough switch 66 opened (ball out)",
    "shooter lane 62 closed (ball waiting)",
    "shooter lane 62 opened (ball launched)",
    "somebody is playing - 1 launched ball(s) stay in play until Drain",
]


def write_blocks():
    """Five balls home, door shut, all three regions - a ball in play."""
    made = TROUGH_IDS[:-1] + ([DOOR] if DOOR else [])
    buf = bytearray(4096)
    struct.pack_into("<I", buf, padsw.OFF_MAGIC, padsw.MAGIC)
    for off in (padsw.OFF_GEN, padsw.OFF_SCR_GEN, padsw.OFF_MRG_GEN):
        struct.pack_into("<I", buf, off, 1)
    for sw in made:
        for off in (padsw.OFF_HELD, padsw.OFF_SCR_HELD, padsw.OFF_MRG):
            buf[off + sw] = 1
    with open(BLOCK, "wb") as f:
        f.write(buf)
    path = os.path.join(STAGE, "dump", "padled")
    led = bytearray(8192)
    struct.pack_into("<I", led, 0, playfield.PADLED_MAGIC)
    struct.pack_into("<I", led, 4, 4)
    struct.pack_into("<I", led, playfield.LED_DECODED_OFF, 41277)
    struct.pack_into("<I", led, playfield.WIDE_DECODED_OFF, 41277)
    for node in range(16):
        for idx in range(playfield.LED_IDX):
            led[playfield.SEEN_OFF + node * playfield.LED_IDX + idx] = 1
            if (node + idx) % 3 == 0:
                led[playfield.LED_HDR + node * playfield.LED_IDX + idx] = 255
    with open(path, "wb") as f:
        f.write(led)
    with open(BINDS, "w", encoding="utf8", newline="\n") as f:
        f.write("# key\tflags\tids\tlabel  (shot rig, %s)\n" % GAME)
        for row in BINDS_ROWS:
            f.write("\t".join(row) + "\n")
    with open(BALL, "w", encoding="utf8", newline="\n") as f:
        f.write("\n".join(BALL_LINES) + "\n")
    log("blocks: trough %r (%s), %d home, door %r"
        % (TROUGH_IDS, HOW, len(made) - 1, DOOR))


# No run to ask, and nothing a click here should reach.
playfield.state_slots = lambda: {}
playfield.wsl_run = lambda script, *a: None
playfield.SwitchPipe._ensure = lambda self: False

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
    write_blocks()
    root = tk.Tk()
    root.title("%s - virtual playfield" % GAME)
    root.geometry("+40+20")
    view = playfield.Field(root)
    log("key panel %s" % ("up" if view.key_panel is not None else "MISSING"))

    def go():
        try:
            if view.key_panel is not None:
                log("trough panel %r" % (view.trough_panel,))
            snap(root, OUT)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        finally:
            root.destroy()

    root.after(3500, go)
    root.mainloop()
    shutil.rmtree(STAGE, ignore_errors=True)


main()
