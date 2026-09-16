"""Capture the virtual playfield's BALLS section with a ball in the lane, PAD-153.

    python scripts/shot_pad153_balls.py <out.png> [--in-play]

DragonRR, on godzilla_le: *"I drained before I plunged.. and that forces an
endless cycle. Is it possible to grey out the drain until it is valid?"*  At
ball start the feeder lands the ball in the shooter lane and waits for Plunge.
Drain then closed a trough switch for a ball that had never left the lane, so
the game saw a full trough AND a ball waiting - one ball more than the machine
holds - and the eject it fired next had nowhere to land.

WHAT THE PAIR SHOWS: the key panel at that exact moment - five balls home, the
shooter lane closed, nothing in play - with the feeder's own sentences for the
serve published.  `--in-play` is the same machine a moment after Plunge (lane
open, one ball out), where Drain is the right button and must stay live.

The recipe is shot_pad134_balls.py's: hand-written switch, LED, key-bind and
ball-status files, and no run.  Nothing here writes anywhere but a temp stage.
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

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
IN_PLAY = "--in-play" in sys.argv[1:]
OUT = os.path.abspath(ARGS[0] if ARGS else "balls.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

GAME = "godzilla_le"
SRC_TABLES = (r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables\%s"
              % GAME)


def log(msg):
    print(msg, flush=True)


log("repo %s" % REPO)
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
STAGE = tempfile.mkdtemp(prefix="pad153b_")
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
LANE = next((r["id"] for r in ROWS
             if (r.get("name") or "").upper().strip() == "SHOOTER LANE"), 62)

#: padglhost's compiled bind table, as shot_pad134_balls.py writes it.
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
    ("F", "-", str(LANE), "Shooter Lane"),
    ("W", "-", "47", "Left Spinner"),
    ("E", "-", "49", "Pop Bumper"),
    ("A", "-", "64", "Left Slingshot"),
    ("S", "-", "63", "Right Slingshot"),
    ("D", "-", "53", "Right Scoop"),
    ("Z", "-", "55", "Left Outlane"),
    ("X", "-", "58", "Right Outlane"),
    ("B", "t", ",".join(str(i) for i in TROUGH_IDS), "6 balls in trough"),
]

#: The feeder's own sentences for one served ball (ballfeed.py run_plan/poll).
BALL_LINES = [
    "fed 1",
    "trough switch %d opened (ball out)" % TROUGH_IDS[-1],
    "shooter lane %d closed (ball waiting)" % LANE,
    "trough 5/6 after the feed",
]


def write_blocks():
    """Five balls home, door shut; the sixth waiting in the lane, or launched
    (`--in-play`).  All three regions, as PAD-134's rig learned to."""
    made = TROUGH_IDS[:-1] + ([DOOR] if DOOR else [])
    if not IN_PLAY:
        made.append(LANE)
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
    lines = BALL_LINES + (["shooter lane %d opened (ball launched)" % LANE]
                          if IN_PLAY else [])
    with open(BALL, "w", encoding="utf8", newline="\n") as f:
        f.write("\n".join([lines[0]] + lines[-3:]) + "\n")
    log("blocks: trough %r (%s), 5 home, lane %d %s, door %r"
        % (TROUGH_IDS, HOW, LANE, "open" if IN_PLAY else "CLOSED", DOOR))


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
            panel = view.key_panel
            if panel is not None:
                log("line %r" % panel.cv.itemcget(panel.ball_state, "text"))
                log("buttons %r" % [(b.cget("text"), b.cget("state"))
                                    for b in panel.ball_btns])
            snap(root, OUT)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        finally:
            root.destroy()

    root.after(3500, go)
    root.mainloop()
    shutil.rmtree(STAGE, ignore_errors=True)


main()
