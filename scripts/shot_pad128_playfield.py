"""Capture the virtual playfield's ball controls for PAD-128.

    python scripts/shot_pad128_playfield.py <out.png>

DragonRR, 2026-09-11: *"I can force it in using the black and white icons but
the game acts like nothing has happened. If I click plunge a ball goes out but
again nothing really happens."*  Part of that is the machine being in attract
mode - the ball controls only mean anything during a game - and part of it is
this window, which ran every one of those helpers and then threw its answer
away.  ``plunge.py start`` says out loud that a game needs credits; nobody
ever saw it.

WHAT THE PAIR SHOWS.  The same scripted press of *Start* on the same title
(godzilla_le, his machine, from this box's own built tables): before, the
status bar carries on showing the tick's numbers as if nothing had run; after,
it carries the helper's own sentences, and the row has the *Insert coin*
button that makes the advice actionable.

THE WORDS ARE THE REAL HELPER'S.  ``playfield.wsl_run`` is redirected to run
the rig's own ``plunge.py`` in this interpreter against a hand-written
``padsw`` block (``PAD_SW_FILE``, which padsw.py documents as the way to
exercise the helpers with no game) - not to a canned string.  So whatever the
helper actually prints on each tree is what lands in the shot.  The block is
a machine at rest: coin door shut, six balls in the trough, mrg published, so
the window draws what a window opening on a real attract-mode run draws.
"""
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                      else "playfield-actions.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

#: DragonRR's own title, from this machine's built tables (read-only; copied
#: out before anything is imported, because the window resolves TDIR at import
#: time and a UNC PAD_ROOT would send every helper down \\wsl.localhost too).
GAME = "godzilla_le"
SRC_TABLES = (r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables\%s"
              % GAME)


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

STAGE = tempfile.mkdtemp(prefix="pad128_")
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


def write_block():
    """A machine at rest, in a 4096-byte padsw block: door shut, six balls
    home, and the merged half published so the window reads the game's own
    view rather than falling back to the keyboard's (read_merged())."""
    rows = trough.load_list(os.path.join(TABLES, "switch_list.txt"))
    positions, how = trough.find(rows)
    door = next((r["id"] for r in rows
                 if r.get("node") == 0 and r.get("bit") == 23), None)
    rest = [P["id"] for P in positions] + ([door] if door else [])
    buf = bytearray(4096)
    struct.pack_into("<I", buf, padsw.OFF_MAGIC, padsw.MAGIC)
    struct.pack_into("<I", buf, padsw.OFF_GEN, 1)
    struct.pack_into("<I", buf, padsw.OFF_MRG_GEN, 1)
    for sw in rest:
        buf[padsw.OFF_HELD + sw] = 1
        buf[padsw.OFF_MRG + sw] = 1
    with open(BLOCK, "wb") as f:
        f.write(buf)
    log("block %s: trough %r (%s), door %r"
        % (BLOCK, [P["id"] for P in positions], how, door))


def write_led_block():
    """A version-4 padled block with lamps in it, so the window looks like the
    live one he is clicking in: without it the status bar reads "no emulator"
    and the bar is what this pair is about.  Offsets from padled.h through
    playfield.py / coilmap.py - the same hand-written-block recipe PAD-120
    used to photograph lit lamps with no rig."""
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


def local_run(script, *args):
    """``playfield.wsl_run``'s stand-in: the REAL helper, in this
    interpreter, against the block above.  Same shape as the module's own
    non-win32 branch - a CompletedProcess or None."""
    env = dict(os.environ, PAD_SW_SRC="f", PAD_SW_FILE=BLOCK)
    try:
        r = subprocess.run([sys.executable, os.path.join(RIG, script)]
                           + [str(a) for a in args],
                           capture_output=True, timeout=60, env=env)
    except Exception:                                       # noqa: BLE001
        traceback.print_exc()
        return None
    log("ran %s %r -> rc=%s" % (script, args, r.returncode))
    for stream in ("stdout", "stderr"):
        for ln in (getattr(r, stream) or b"").decode("utf8",
                                                     "replace").splitlines():
            log("   %s: %s" % (stream, ln))
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
    write_block()
    write_led_block()
    root = tk.Tk()
    root.title("%s - virtual playfield" % GAME)
    root.geometry("+40+20")
    view = playfield.Field(root)
    log("canvas %dx%d at scale %.2f  actions %r"
        % (view.cv.winfo_reqwidth(), view.cv.winfo_reqheight(), view.scale,
           [b.cget("text") for b in view._acts]))

    def press_start():
        btn = next(b for b in view._acts if b.cget("text") == "Start")
        btn.invoke()

    def report():
        log("status bar: %r" % view.status.cget("text"))
        log("flash: %r" % (getattr(view, "_state_msg", None),))

    def go():
        try:
            report()
            snap(root, OUT)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        finally:
            root.destroy()

    # The press, then time for the helper to finish and for the next tick to
    # rewrite the bar - a status line that only survives one frame is not a
    # fix, and this is what proves it.
    root.after(1200, press_start)
    root.after(5200, go)
    root.mainloop()
    shutil.rmtree(STAGE, ignore_errors=True)


main()
