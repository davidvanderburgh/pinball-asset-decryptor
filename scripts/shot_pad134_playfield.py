"""Capture the virtual playfield's Plunge button with a ball in play, PAD-134.

    python scripts/shot_pad134_playfield.py <out.png>

DragonRR, 2026-09-12, trying to reach players 2, 3 and 4 to check their images:
*"when I click ball 6 on the B/W display for player 2 it ignores me"*, and *"I
suspect the machine thinks a ball is still in play"*.  With BALL SAVE on the
game re-serves the drained ball and fires its own AUTO PLUNGER, so by the time
a player reaches for *Plunge* the lane is already EMPTY with a ball in play -
and this window's Plunge served a SECOND ball there.  The game only counts the
balls it asked for, so that extra one leaves the machine a ball short for ever:
the next Start gets LOCATING PINBALLS and a restart refuses.

WHAT THE PAIR SHOWS, same title (godzilla_le, his machine, from this box's own
built tables), same block, same scripted press of *Plunge*: before, the trough
panel loses a second ball - four dots filled where five were - and the status
bar reads out the eject it just did; after, the trough is untouched and the bar
says why, and where a ball in play actually ends.

THE WORDS AND THE DOTS ARE THE REAL HELPER'S.  ``playfield.wsl_run`` is
redirected to run the rig's own ``plunge.py`` in this interpreter against a
hand-written ``padsw`` block (``PAD_SW_FILE``), exactly as PAD-128's shot rig
does - and ``publish()`` then does the one thing the guest shim would do,
copying the ids the helper CHANGED into the merged array, so the window draws
the consequence of the press instead of being told about it.  Last edge wins,
per id, which is the merge padsw.h documents.

THE BALL IN PLAY IS SET UP IN TWO STEPS on purpose: the window opens on a
machine at rest so its ball complement learns six, and only then does a ball
leave the trough.  Written the other way round the panel has never seen six
home and "in play" comes out one short - which is trough.Balls's documented
behaviour and would make the numbers in the shot a lie.
"""
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                      else "playfield-plunge.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

GAME = "godzilla_le"
SRC_TABLES = (r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables\%s"
              % GAME)


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

STAGE = tempfile.mkdtemp(prefix="pad134_")
TABLES = os.path.join(STAGE, "dump", "tables", GAME)
if not os.path.isdir(SRC_TABLES):
    sys.exit("no tables for %s at %s - run the title once first"
             % (GAME, SRC_TABLES))
shutil.copytree(SRC_TABLES, TABLES)
os.makedirs(os.path.join(STAGE, "dump"), exist_ok=True)
BLOCK = os.path.join(STAGE, "dump", "padsw")

os.environ["PAD_ROOT"] = STAGE
os.environ["PAD_TABLES"] = os.path.join(STAGE, "dump", "tables")
os.environ["PAD_GAME"] = GAME
os.environ["PAD_SW_FILE"] = BLOCK

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
             if (r.get("name") or "").upper().strip() == "SHOOTER LANE"), None)


def write_block(home):
    """`home` trough positions full, door shut, the merge published.

    ALL THREE REGIONS, which is what a real run looks like and is not padding.
    The keyboard half is padglhost's window-open latch and the merged half is
    what the window reads (read_merged) - but the SCRIPT half matters just as
    much here, because `swinit.py` writes the machine-at-rest set into it at
    guest start. Leave it empty and `plunge.py`'s `take()` has to change the
    very byte it is about to write again, which collapses into no edge at all
    unless the guest merges in the microseconds between the two - the trough
    then keeps a ball the eject took out, and the shot would be showing this
    rig's own artefact rather than the app's behaviour.
    """
    made = TROUGH_IDS[:home] + ([DOOR] if DOOR else [])
    buf = bytearray(4096)
    struct.pack_into("<I", buf, padsw.OFF_MAGIC, padsw.MAGIC)
    struct.pack_into("<I", buf, padsw.OFF_GEN, 1)
    struct.pack_into("<I", buf, padsw.OFF_SCR_GEN, 1)
    struct.pack_into("<I", buf, padsw.OFF_MRG_GEN, 1)
    for sw in made:
        buf[padsw.OFF_HELD + sw] = 1
        buf[padsw.OFF_SCR_HELD + sw] = 1
        buf[padsw.OFF_MRG + sw] = 1
    with open(BLOCK, "wb") as f:
        f.write(buf)
    log("block: trough %r (%s) with %d home, door %r, lane %r"
        % (TROUGH_IDS, HOW, home, DOOR, LANE))


def write_led_block():
    """A version-4 padled block with lamps in it, so the window looks like the
    live one he is clicking in rather than reading "no emulator" - PAD-120's
    hand-written-block recipe, offsets from padled.h through playfield.py."""
    path = os.path.join(STAGE, "dump", "padled")
    buf = bytearray(8192)
    struct.pack_into("<I", buf, 0, playfield.PADLED_MAGIC)
    struct.pack_into("<I", buf, 4, 4)                       # version
    struct.pack_into("<I", buf, playfield.LED_DECODED_OFF, 41277)
    struct.pack_into("<I", buf, playfield.WIDE_DECODED_OFF, 41277)
    struct.pack_into("<I", buf, playfield.COIL_GEN_OFF + 4, 31)
    for node in range(16):
        for idx in range(playfield.LED_IDX):
            buf[playfield.SEEN_OFF + node * playfield.LED_IDX + idx] = 1
            if (node + idx) % 3 == 0:
                buf[playfield.LED_HDR + node * playfield.LED_IDX + idx] = 255
    with open(path, "wb") as f:
        f.write(buf)
    log("led block %s (%d bytes)" % (path, len(buf)))


def read_block():
    """(script generation, script array) - a read, never a write."""
    with open(BLOCK, "rb") as f:
        buf = f.read()
    return (struct.unpack_from("<I", buf, padsw.OFF_SCR_GEN)[0],
            buf[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])


def publish(edges):
    """Apply `edges` to the merged array - the guest's job, after the fact.

    WHY THE EDGES ARE COLLECTED WHILE THE HELPER RUNS rather than diffed once
    at the end: a helper's sequence can bring a byte back to where it started
    and the MIDDLE is the part that matters. `plunge.py plunge` takes ownership
    of the trough at its merged value (scr_held 0 -> 1 on every made position),
    then ejects (that one position 1 -> 0) - so a before/after diff shows the
    ejected ball as unmoved and the panel would draw a trough that still has
    it. Last edge wins, per id, which is what padsw.h's merge does.

    AND WHY NOTHING IS WRITTEN UNTIL THE HELPER HAS EXITED: it has the block
    MMAPPED and calls flush(), which writes the whole page back - a merge
    written underneath that is simply lost on Windows.
    """
    if not edges:
        log("merged nothing")
        return
    with open(BLOCK, "r+b") as f:
        buf = bytearray(f.read())
        for sw, val in sorted(edges.items()):
            buf[padsw.OFF_MRG + sw] = val
        struct.pack_into("<I", buf, padsw.OFF_MRG_GEN,
                         struct.unpack_from("<I", buf, padsw.OFF_MRG_GEN)[0] + 1)
        f.seek(0)
        f.write(bytes(buf))
    log("merged %r" % (sorted(edges.items()),))


def local_run(script, *args):
    """``playfield.wsl_run``'s stand-in: the REAL helper, in this interpreter,
    against the block above, and then the merge the guest would have done.

    Runs on the window's own SwitchDriver thread, exactly as the real one does,
    so watching the block while the helper works blocks nothing that draws.
    """
    env = dict(os.environ, PAD_SW_SRC="f", PAD_SW_FILE=BLOCK)
    cmd = ([sys.executable, os.path.join(RIG, script)]
           + [str(a) for a in args])
    edges = {}
    try:
        gen, prev = read_block()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env)
        while True:
            done = p.poll() is not None
            now_gen, scr = read_block()
            if now_gen != gen:
                gen = now_gen
                for i in range(padsw.MAX_ID):
                    if scr[i] != prev[i]:
                        edges[i] = scr[i]
                prev = scr
            if done:
                break
            time.sleep(0.01)
        out, err = p.communicate(timeout=60)
        r = subprocess.CompletedProcess(cmd, p.returncode, out, err)
    except Exception:                                       # noqa: BLE001
        traceback.print_exc()
        return None
    log("ran %s %r -> rc=%s" % (script, args, r.returncode))
    for stream in ("stdout", "stderr"):
        for ln in (getattr(r, stream) or b"").decode("utf8",
                                                     "replace").splitlines():
            log("   %s: %s" % (stream, ln))
    publish(edges)
    return r


playfield.wsl_run = local_run
# No run to ask, and starting WSL to be told "nothing saved" is a 30 s wait.
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
    write_block(len(TROUGH_IDS))          # a machine at rest, so six is seen
    write_led_block()
    root = tk.Tk()
    root.title("%s - virtual playfield" % GAME)
    root.geometry("+40+20")
    view = playfield.Field(root)
    log("canvas %dx%d at scale %.2f  actions %r"
        % (view.cv.winfo_reqwidth(), view.cv.winfo_reqheight(), view.scale,
           [b.cget("text") for b in view._acts]))

    def serve_a_ball():
        """The state BALL SAVE leaves: a ball out of the trough, in play, and
        an empty shooter lane because the game auto-plunged it itself."""
        write_block(len(TROUGH_IDS) - 1)
        log("a ball is now in play (trough %d/%d, lane open)"
            % (len(TROUGH_IDS) - 1, len(TROUGH_IDS)))

    def press_plunge():
        btn = next(b for b in view._acts if b.cget("text") == "Plunge")
        btn.invoke()

    def report():
        log("status bar: %r" % view.status.cget("text"))
        log("trough line: %r" % playfield.trough_text(view.sw))

    def go():
        try:
            report()
            snap(root, OUT)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        finally:
            root.destroy()

    root.after(1500, serve_a_ball)
    root.after(2600, press_plunge)
    # Time for the helper to finish and for the next tick to rewrite the bar -
    # a status line that only survives one frame is not a fix.
    root.after(7000, go)
    root.mainloop()
    shutil.rmtree(STAGE, ignore_errors=True)


main()
