"""PAD-159 proof shot: the emulator run that stops on a scene it cannot read.

    python scripts/shot_pad159.py <out_dir> <before|after>

THE REPORT.  DragonRR's Godzilla LE run showed the Stern logo and stopped, and
the pane ended on libstdc++'s own words: "terminate called after throwing an
instance of 'cereal::Exception' / what(): Error while trying to deserialize a
polymorphic pointer. Could not find type id 993416120".  That is a scene.radium
the game could not read - but nothing said WHICH of the title's 194 scenes, or
whether it was one PAD had written into his override set, so the ticket could
not be settled from the log.

THE FIX IN THE PANE.  hwshim.c now reports every cereal exception with the
scene the throwing thread was reading and how far cereal got ([scenefail]), and
watch.sh's exit report names it and says whether it is one of the user's edits.

WHAT THE PANE HOLDS.  NOTHING IS RETYPED: both panes are real watch.sh output
from the SAME run input - godzilla_pro 1.15 with an override set in which the
reported type id (993416120) was planted over a polymorphic id in three
demand-loaded scenes - once before the fix and once after it.  The lead-in is
the start of the before run (the after run's differs only in the frame number
of its first picture, 130 for 131); the 88-line switch table printed between the
lead-in and the exit is left out so the exit report fits this desktop, and the
renderer's frame-rate lines after the exit are left out for the same reason.

WHY THE LINES ARE FED RATHER THAN PRODUCED.  A real run boots a guest on WSL;
the widget path is the real one either way (``append_log`` is the sink every
emulator line goes through), so what the pane does with these lines is exactly
what it does with a run's.

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, rolling log
sandboxed) follow scripts/take_screenshots.py -- see its header for why they
are what they are.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad159bak"
GEOM = None
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 205

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad159_log_")

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

# ----------------------------------------------------------------------
# The run, as the app's log pane sees it.
# ----------------------------------------------------------------------
LEAD = [
    "[emulate] [watch] starting godzilla_pro (boot to the first picture takes "
    "~15 s)",
    "[emulate] [watch] waiting for the game to start...",
    "[emulate] [watch] auto-advance on: it will press Service Back until the "
    "game",
    "[emulate] [watch] leaves Tech Alerts (PAD_AUTO_ATTRACT=0 to do it "
    "yourself).",
    "[emulate] [watch] running. CLOSE THE WINDOW to stop (or press Ctrl-C "
    "here).",
    "[emulate] [watch] backstop: will stop by itself after 2 min.",
    "[emulate] [event] [padglhost] display 0 upload: teximage tex 13 1024x256 "
    "at 0,0 fmt 0x1908 frame 3",
    "[emulate] [event] [sw] --- switches: count=88 entry[]=0x00991f08 "
    "raw[]=0x0086a490 ---",
    "[emulate] [event] [padglhost] picture: FIRST at frame 131 (96463 of "
    "1044480 pixels are not black)",
    "[emulate] [watch] the game exited. Last lines of its log:",
] + ["[emulate] ExchangeData: read failed (received 0, expected length=%d), "
     "timed out" % n for n in (13, 3, 3, 12, 12)]

FATAL = [
    "[emulate] [watch] the game's own debug log "
    "(/home/david/spike2root/dump/debug_log.txt) holds FATAL lines; the last:",
    "[emulate] 2026-09-11T16:57:43.674Z: ** FATAL: error 256 (NVMigration: "
    "create_current_map_file created an invalid or mismatched file?!?).",
    "[emulate] 2026-09-11T17:01:25.099Z: ** FATAL: error 256 (NVMigration: "
    "create_current_map_file created an invalid or mismatched file?!?).",
    "[emulate] [exit] status=5 from 0x1c45c tid=1",
    "[emulate] [watch] stopping...",
]

#: Before: the exit report goes straight from the game's last lines to a stale
#: FATAL from days earlier - nothing about the scene it could not read.
BEFORE = LEAD + FATAL

#: After: the same run names the scene, the byte, and that it is an edit.
AFTER = LEAD + [
    "[emulate] [watch] the game could not read one of its scene files:",
    "[emulate] [watch]   ./assets/lcd/demand_loaded/"
    "394c4a037fb26e12f536c42b2677bfed831f5c98/scene.radium at byte 41934: "
    "Error while trying to deserialize a polymorphic pointer. Could not find "
    "type id 993416120",
    "[emulate] [watch]   that file is one of YOUR EDITS: PAD rebuilt it from "
    "what you replaced",
    "[emulate] [watch]   in that scene. Start again with \"Apply my replaced "
    "assets on top\"",
    "[emulate] [watch]   unticked - if the game starts, that scene's edit is "
    "what it could not",
    "[emulate] [watch]   read.",
] + FATAL

LINES = BEFORE if WHEN == "before" else AFTER

from PIL import Image  # noqa: E402

import pinball_decryptor.app as app_mod  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402

# A release published by another session mid-run would put an update banner in
# one shot of the pair and move every row under it.
app_mod.check_for_update = None

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


def snap(name):
    # The app re-sizes itself to the active tab on an idle callback that fires
    # at a different moment each run; re-assert the geometry twice so the pair
    # is pixel-comparable (PAD-60).
    if GEOM:
        for _ in range(2):
            root.geometry(GEOM)
            root.update_idletasks()
    # AND THE NOTEBOOK HEIGHT LAST: the app re-asserts the tab's own requested
    # height on an idle callback after a tab change, which undoes a value set
    # any earlier.  The log pane is what is left, and the log is the shot.
    win._notebook.configure(height=NB_H)
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
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def clear_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is None:
        return
    t.configure(state=tk.NORMAL)
    t.delete("1.0", tk.END)
    t.configure(state=tk.DISABLED)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(800)
def s_enter():
    global GEOM
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(980, root.winfo_screenheight() - 60)
    GEOM = "%dx%d+30+20" % (w, h)
    root.geometry(GEOM)
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


@step(4000)
def s_emulate_tab():
    win._notebook.select(win._tab_emulate)


@step(1500)
def s_feed():
    clear_log()
    for line in LINES:
        win.append_log(line)
    root.update_idletasks()
    print("fed %d lines" % len(LINES), flush=True)


@step(1500)
def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
        root.update_idletasks()
        print("pane holds %s lines" % t.index("end-1c").split(".")[0],
              flush=True)
    snap("%s_emulate_log.png" % WHEN)


@step(600)
def s_done():
    if os.path.exists(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            print("step %d: %s" % (i, fn.__name__), flush=True)
            fn()
        except Exception:
            print("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()),
                  flush=True)
        run(i + 1)

    root.after(delay, _go)


root.after(120000, lambda: root.destroy())
run()
try:
    app.run()
finally:
    try:
        if os.path.exists(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            print("settings restored", flush=True)
    except Exception:
        print("settings restore FAILED:\n%s" % traceback.format_exc(),
              flush=True)
