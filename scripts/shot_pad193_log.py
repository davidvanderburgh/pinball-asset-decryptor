"""PAD-193: what the Log says when the Mac's container is not up yet.

    python scripts/shot_pad193_log.py <out_dir> <before|after>

One shot, ``<before|after>_multiboot_container_log.png``: the Multi-boot tab
with the reporter's own Log lines in the pane at the foot of the window.

REPLAYED, NOT REPRODUCED.  These lines only happen on a Mac with Docker, and
this rig is Windows, so the script feeds the panel the exact lines from the
reporter's project.log (2026-09-21 18:28-18:30, v0.229.1) through the same
``_append`` / ``_say_once`` pair the worker uses, and then snaps the window.
The BEFORE shot is what he got: six steps, each dying on Docker's own "No
such container: pad-multiboot-worker", and nothing anywhere saying that a
container is started by Build and not by the preview.  The AFTER shot is the
same six lines with the one sentence :func:`multiboot_tab.container_note`
adds the first time - once, not once per step, because the preview redraws
on every keystroke.

NOTHING REAL IS TOUCHED: no settings are written, no card is read, no tool
is run, and the update check is stubbed so a release published mid-run
cannot put a banner in one shot of the pair.
"""
import ctypes
import os
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOM = ["1100x860+30+20"]

#: Straight out of the reporter's log - the preview's three steps, twice
#: over, as the tab runs them on a load and on the next redraw.
REPLAY = [
    "$ cd /tmp/repo && python3 tools/jjp_emu/mkjjpmulti.py plan --primary "
    "'/host/Volumes/Mac SSD/Sonichedge/Sonic-v00.930.iso'",
    "Error response from daemon: No such container: pad-multiboot-worker",
    "plan: exit 1",
    "the size check failed (exit 1) - the sentence beside the status line "
    "is left blank.",
    "$ cd /tmp/repo && bash tools/jjp_emu/ensurejjpselect.sh --preview "
    "'/host/Volumes/Mac SSD/Sonichedge/Sonic-v00.930.iso' /var/tmp/jjpselect",
    "Error response from daemon: No such container: pad-multiboot-worker",
    "selector: exit 1",
    "[preview] Preview failed at selector (exit 1) - see the tool output.",
]
#: What Docker said, as the worker hands it to the note.
FAILED_STEP_TEXT = ("Error response from daemon: No such container: "
                    "pad-multiboot-worker")

os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)


def log(msg):
    print(msg, flush=True)


log("code under test: %s" % REPO)

from PIL import Image                                       # noqa: E402

from pinball_decryptor.app import App                       # noqa: E402
from pinball_decryptor.gui import multiboot_docker as D     # noqa: E402
from pinball_decryptor.gui import multiboot_tab as mt       # noqa: E402

App._check_for_update = lambda self: None

# The note is a macOS one and asks the module whether it is on one.  The
# lines being replayed ARE from a Mac; only the screen is not.
D.enabled = lambda: True

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


def snap(name, crop_to=None):
    """The window, or - with *crop_to* - the part of it that widget fills.

    The Log is a strip at the foot of a tall tab, and a pair of shots of
    the whole window would be two pictures of the Multi-boot tab with four
    lines of six-point text along the bottom.  The lines ARE the change."""
    for _ in range(2):              # let a queued auto-resize run, then win
        root.geometry(GEOM[0])
        root.update()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)       # GA_ROOT
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
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    if crop_to is not None:
        # The crop above moved the image's origin to the screen point
        # (wrect.left + border, wrect.top); the widget's own is on screen.
        pad = 6
        x = crop_to.winfo_rootx() - (wrect.left + border)
        y = crop_to.winfo_rooty() - wrect.top
        img = img.crop((max(0, x - pad), max(0, y - pad),
                        min(img.width, x + crop_to.winfo_width() + pad),
                        min(img.height, y + crop_to.winfo_height() + pad)))
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(1200)
def s_multiboot_tab():
    # As tall as the screen allows: the Multi-boot tab's preview canvas is a
    # fixed height, so every extra pixel goes to the Log, which is the strip
    # this pair is of.
    root.maxsize(9999, 9999)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    GEOM[0] = "%dx%d+20+10" % (min(1100, sw - 60), sh - 80)
    root.geometry(GEOM[0])
    win._notebook.select(win._tab_multiboot)


#: Absent from the BEFORE half of the pair, which is the point of it.
note_for = getattr(mt, "container_note", lambda _text: "")


@step(1500)
def s_replay():
    import tkinter as tk
    # The app's own startup lines are not what this pair is of.
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.configure(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        t.configure(state=tk.DISABLED)
    panel = win._multiboot_panel
    for line in REPLAY:
        panel._write(line)
        # Every failing step asks for the note; _say_once is what keeps six
        # steps from printing six paragraphs.
        if line.endswith(": exit 1"):
            panel._say_once(note_for(FAILED_STEP_TEXT))
    # _say_once queues for the Tk loop (it is called from the worker
    # thread), and the panel only drains while a run is up.  There is no run
    # here, so drain it by hand - the same call the panel's own timer makes.
    panel._drain()
    log("note said: %r" % (note_for(FAILED_STEP_TEXT),))


@step(800)
def s_snap():
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see("end")
    snap("multiboot_container_log", crop_to=win._log_frame)


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
