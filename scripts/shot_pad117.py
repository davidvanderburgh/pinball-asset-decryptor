"""PAD-117 proof shot: the run that ended because the GPU driver would not load.

    python scripts/shot_pad117.py <out_dir> <before|after>

THE REPORTED RUN.  A Beatles card, WSL up 1190 hours, v0.194.0.  The renderer
opened its window, Mesa went to load the d3d12 driver, and glibc's loader
aborted on a shared object whose hash header did not read as one.  watch.sh
printed the twenty lines it had and ran ``exit 1``, so the guest never started
- and the last word the user got was an assertion about ``bitmask_nwords``.

WHAT THE PANE HOLDS IN EACH SHOT.  Both shots share the lead-in and the death,
and both are the reporter's own log, pasted from his attachment.  They diverge
at the line after it:

  * before - the teardown, verbatim from his log.  Nothing ran.
  * after  - what the new code prints, and these are not retyped either: the
    renderer block was EXTRACTED FROM watch.sh BY MARKER and run in WSL
    against a stub padglhost that fails the way his machine does, and this is
    that run's output.  The four ``[padglhost]`` lines at the end are from a
    real llvmpipe padglhost started on this box, with his paths.

WHY THE LINES ARE FED RATHER THAN PRODUCED.  Reproducing the fault needs a WSL
whose Windows-side GPU libraries have gone stale underneath it, which is not a
state a script can put a machine into.  The widget path is the real one -
``append_log`` is the sink every emulator line goes through - so what the pane
does with these lines is exactly what it does with a run's.

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
SETTINGS_BAK = SETTINGS + ".pad117bak"
GEOM = None
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 275

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

# The log pane preloads earlier sessions from the real rolling log; a fresh
# scratch dir per run keeps the before shot's lines out of the after shot.
from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad117_log_")

# ----------------------------------------------------------------------
# The run, as the app's log pane sees it.
# ----------------------------------------------------------------------
#: Shared by both shots: his log, from "starting renderer" to the last line of
#: the renderer's own output.  Trimmed at the front only so the longer of the
#: two panes still fits without scrolling - the pair must show the same lines
#: up to the point where they differ.
LEAD = [
    "[emulate] [watch] starting renderer (it opens the game window; the "
    "picture arrives",
    "[emulate] [watch] with the guest's first frame, ~15 s later)",
    "[emulate] [watch] the renderer died on startup:",
    "[emulate] [padglhost] no switch list for beatles yet; playfield keys and "
    "the trough latch WAIT for it (cabinet keys work; the table normally "
    "arrives a minute into a first run)",
    "[emulate] [padglhost] key binds exported to "
    "/home/home/spike2root/dump/padbinds",
    "[emulate] [padglhost] keyboard -> switches via "
    "/home/home/spike2root/dump/padsw",
    "[emulate] [padglhost] window opened 1360x768 on DISPLAY=:0",
    "[emulate] libEGL warning: DRI3 error: Could not get DRI3 device",
    "[emulate] libEGL warning: Ensure your X server supports DRI3 to get "
    "accelerated rendering",
    "[emulate] Inconsistency detected by ld.so: dl-setup_hash.c: 36: "
    "_dl_setup_hash: Assertion (bitmask_nwords & (bitmask_nwords - 1)) == 0 "
    "failed!",
]

#: v0.194.0, verbatim from his attachment.  The run is over.
BEFORE = LEAD + [
    "[emulate] [watch] stopping...",
    "[emulate] [watch] unmounted the card",
    "[emulate] --- what is still running (all must be 0) ---",
    "[emulate] guest (comm=game)      : 0",
    "[emulate] qemu  (arm-binfmt)     : 0",
    "[emulate] host  (padglhost)      : 0",
    "[emulate] audio player           : 0",
    "[emulate] video host (padvidhost): 0",
    "[emulate] run scripts (watch.sh) : 0",
    "[emulate] TOTAL STILL RUNNING    : 0  (clean)",
]

#: The new block's own output, measured (see the header).
AFTER = LEAD + [
    "[emulate] [watch]   WHAT THAT LOADER LINE MEANS: one of the graphics",
    "[emulate] [watch]   libraries would not load - the loader judged the",
    "[emulate] [watch]   file itself corrupt. On WSL the GPU libraries are",
    "[emulate] [watch]   not part of Ubuntu: Windows lays them into",
    "[emulate] [watch]   /usr/lib/wsl/lib when the VM starts, and a Windows",
    "[emulate] [watch]   or graphics-driver update swaps them underneath a",
    "[emulate] [watch]   VM that is already running. A session that has",
    "[emulate] [watch]   been up for days is the one that gets caught (its",
    "[emulate] [watch]   age is printed further up this log).",
    "[emulate] [watch]   THE CURE IS A VM RESTART, and nothing in here can",
    "[emulate] [watch]   do it: Stop, then 'Restart WSL...' on the Emulate",
    "[emulate] [watch]   tab - or 'wsl --shutdown' in a Windows terminal -",
    "[emulate] [watch]   and start again.",
    "[emulate] [watch] TRYING THE RENDERER AGAIN IN SOFTWARE. That costs less",
    "[emulate] [watch]   than it sounds - this game measures 59.9 fps on the",
    "[emulate] [watch]   software rasteriser - and nothing else about the run",
    "[emulate] [watch]   changes. The failed GPU attempt's log is kept at",
    "[emulate] [watch]   /home/home/padglhost.log.gpu.",
    "[emulate] [watch] cfg GALLIUM_DRIVER=llvmpipe (software renderer)",
    "[emulate] [watch] the renderer is up in SOFTWARE (llvmpipe).",
    "[emulate] [padglhost] llvmpipe (LLVM 20.1.2, 256 bits) | OpenGL ES 3.2 "
    "Mesa 25.2.8-0ubuntu0.24.04.2",
    "[emulate] [padglhost] window opened 1360x768 on DISPLAY=:0",
    "[emulate] [padglhost] ring /home/home/spike2root/dump/padgl (64 MB), "
    "display 1920x1080",
    "[emulate] [padglhost] ready, waiting for the game",
    "[emulate] [watch] game window opened 1360x768 on DISPLAY=:0",
    "[emulate] [watch] starting beatles (boot to the first picture takes ~15 s)",
]

LINES = BEFORE if WHEN == "before" else AFTER

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


def snap(name):
    # The app re-sizes itself to the active tab on an idle callback that fires
    # at a different moment each run; re-assert the geometry twice so the pair
    # is pixel-comparable (PAD-60).
    if GEOM:
        for _ in range(2):
            root.geometry(GEOM)
            root.update_idletasks()
    # AND THE NOTEBOOK HEIGHT LAST.  The tab is packed fill=X/expand=False and
    # the log frame takes what is left, so the pane's height is entirely this
    # number - but the app re-asserts the tab's own requested height on an idle
    # callback after a tab change, which undoes a value set any earlier.  The
    # Emulate tab is taller than this desktop either way; the log is the shot.
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
