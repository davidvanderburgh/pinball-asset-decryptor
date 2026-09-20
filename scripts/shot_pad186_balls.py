"""Capture the virtual playfield's BALLS section after a pause in play, PAD-186.

    python scripts/shot_pad186_balls.py <out.png> [--before]

DragonRR, on godzilla_le: *"in battle mode clicking to drain the ball does not
end the game. This is if the timer isn't actively ticking when you drain it.
It works if it is."*  A Stern mode clock freezes after a few seconds with no
playfield switch, so a frozen clock and "this player has not clicked anything
for a few seconds" are one state - and that was the state the ball feeder's
way home took his ball in, leaving his own Drain click on a trough it had
already filled.

WHAT THE PAIR SHOWS: the same machine a couple of seconds after the game
served and auto-plunged a ball, with the player watching rather than clicking.
`--before` is the shipped behaviour (the ball taken back: 6/6 trough, nothing
in play, "came home untouched"); without it the ball is still theirs.

THE FEEDER IN BOTH SHOTS IS THE REAL ballfeed.py, run here against a scratch
machine - the block, the coil counters and every word under BALLS are its own
output, not a caption written for the picture.  `--before` runs it with
PAD_BALL_HUMAN_MS=0, which is documented as restoring the PAD-134 behaviour
exactly; the control against the unmodified tree is ballfeedtest.py.

The recipe is shot_pad153_balls.py's: hand-written switch, LED and key-bind
files, and no emulator run.  Nothing here writes anywhere but a temp stage.
"""
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
BEFORE = "--before" in sys.argv[1:]
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
STAGE = tempfile.mkdtemp(prefix="pad186b_")
TABLES = os.path.join(STAGE, "dump", "tables", GAME)
if not os.path.isdir(SRC_TABLES):
    sys.exit("no tables for %s at %s - run the title once first"
             % (GAME, SRC_TABLES))
shutil.copytree(SRC_TABLES, TABLES)
BLOCK = os.path.join(STAGE, "dump", "padsw")
LED = os.path.join(STAGE, "dump", "padled")
BINDS = os.path.join(STAGE, "dump", "padbinds")
BALL = os.path.join(STAGE, "dump", "padball")

os.environ["PAD_ROOT"] = STAGE
os.environ["PAD_TABLES"] = os.path.join(STAGE, "dump", "tables")
os.environ["PAD_GAME"] = GAME
os.environ["PAD_SW_FILE"] = BLOCK
os.environ["PAD_LED_FILE"] = LED
os.environ["PAD_PF_BINDS"] = BINDS
os.environ["PAD_PF_BALL"] = BALL

sys.path.insert(0, RIG)
sys.argv = ["playfield.py", GAME]

import tkinter as tk  # noqa: E402

from PIL import Image  # noqa: E402

import coilmap  # noqa: E402
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
#: The switch the player clicks.  A spinner if this title has one, because
#: that is the input DragonRR's earlier report was made of.
CLICK = next((r["id"] for r in ROWS
              if "SPINNER" in (r.get("name") or "").upper()), 47)
COILS = coilmap.load(os.path.join(TABLES, "device_xy.txt"))
EJECT = coilmap.address(COILS, coilmap.TROUGH)
PLUNGER = coilmap.address(COILS, coilmap.AUTO_PLUNGER)

#: padglhost's compiled bind table, as shot_pad153_balls.py writes it.
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


def write_blocks():
    """A machine at rest - six balls home, door shut, lane empty."""
    made = list(TROUGH_IDS) + ([DOOR] if DOOR else [])
    buf = bytearray(4096)
    struct.pack_into("<I", buf, padsw.OFF_MAGIC, padsw.MAGIC)
    for off in (padsw.OFF_GEN, padsw.OFF_SCR_GEN, padsw.OFF_MRG_GEN):
        struct.pack_into("<I", buf, off, 1)
    for sw in made:
        for off in (padsw.OFF_HELD, padsw.OFF_SCR_HELD, padsw.OFF_MRG):
            buf[off + sw] = 1
    with open(BLOCK, "wb") as f:
        f.write(buf)
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
    with open(LED, "wb") as f:
        f.write(led)
    with open(BINDS, "w", encoding="utf8", newline="\n") as f:
        f.write("# key\tflags\tids\tlabel  (shot rig, %s)\n" % GAME)
        for row in BINDS_ROWS:
            f.write("\t".join(row) + "\n")
    log("blocks: trough %r (%s) all home, lane %d, door %r, click %d"
        % (TROUGH_IDS, HOW, LANE, DOOR, CLICK))


class Machine:
    """The far side of the block: the guest's merge and the coil counters.

    The merge is the one thing a desk run cannot do without - the feeder's
    next decision has to see its own last one - and it is the same loop
    ballfeedtest.py's Shim runs: with one writer, mrg[] is scr_held[].
    """

    def __init__(self):
        import mmap
        self.sw = mmap.mmap(os.open(BLOCK, os.O_RDWR | os.O_BINARY), 4096)
        self.led = mmap.mmap(os.open(LED, os.O_RDWR | os.O_BINARY), 8192)
        self.stop = False
        self.t = threading.Thread(target=self._merge, daemon=True)
        self.t.start()

    def _merge(self):
        last = -1
        while not self.stop:
            gen = struct.unpack_from("<I", self.sw, padsw.OFF_SCR_GEN)[0]
            if gen != last:
                last = gen
                for i in range(padsw.MAX_ID):
                    self.sw[padsw.OFF_MRG + i] = self.sw[padsw.OFF_SCR_HELD + i]
                struct.pack_into("<I", self.sw, padsw.OFF_MRG_GEN, gen)
            time.sleep(0.005)

    def fire(self, addr):
        o = coilmap.COIL_OFF + addr[0] * coilmap.COIL_N + addr[1]
        self.led[o] = (self.led[o] + 1) & 0xFF

    def click(self, sw, tag="f"):
        """A click in the playfield window: a SCRIPT write tagged `f`, which
        is what playfield.wsl_run's helpers carry (PAD_SW_SRC=f)."""
        for val in (1, 0):
            self.sw[padsw.OFF_SCR_HELD + sw] = val
            struct.pack_into("<I", self.sw, padsw.OFF_SCR_SRC, ord(tag))
            struct.pack_into("<I", self.sw, padsw.OFF_SCR_GEN,
                             struct.unpack_from("<I", self.sw,
                                                padsw.OFF_SCR_GEN)[0] + 1)
            time.sleep(0.08)


def play():
    """Click, let the game serve and plunge a ball, then stop clicking.

    THE ORDER IS THE WHOLE TICKET. The click comes first - it is what drained
    the last ball - and the launch the game answers it with is one this feeder
    owns. Nothing moves after that, because the player is watching the battle.
    """
    env = dict(os.environ, PAD_BALL_HZ="50", PAD_BALL_LANE_MS="150",
               PAD_BALL_MIN_GAP_MS="100", PAD_BALL_HOME_MS="1500",
               PAD_BALL_HUMAN_MS="0" if BEFORE else "60000",
               PAD_BALL_FILE=BALL)
    p = subprocess.Popen([sys.executable, os.path.join(RIG, "ballfeed.py")],
                         env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    said = []
    threading.Thread(target=lambda: [said.append(l.rstrip()) for l in p.stdout],
                     daemon=True).start()
    m = Machine()
    time.sleep(1.0)
    m.click(CLICK)
    time.sleep(0.3)
    m.fire(EJECT)
    time.sleep(0.3)
    m.fire(PLUNGER)
    time.sleep(2.6)            # past PAD_BALL_HOME_MS, with nobody clicking
    p.terminate()
    p.wait(timeout=5)
    m.stop = True
    for line in said:
        log("  " + line)


# No run to ask, and nothing a click in the SHOT should reach.
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
    log("the feeder said (%s):" % ("PAD_BALL_HUMAN_MS=0, as shipped"
                                   if BEFORE else "with the window"))
    play()
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
