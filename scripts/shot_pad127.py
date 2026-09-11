"""PAD-127 proof shot: the run that came up with no picture and said so once.

    python scripts/shot_pad127.py <out_dir> <before|after>

THE REPORTED RUN.  A Godzilla card, an app update, and a run that started
normally: the guest booted, the sound played, the virtual playfield came up and
answered its keys - and the game window never painted.  The reporter sent a
photograph of its Windows taskbar preview, empty, and rebooted the machine.

WHAT HAPPENED UNDERNEATH.  padglhost creates and maps its window BEFORE it asks
Mesa for anything, so when the driver then refuses a window surface the window
is already on the desktop.  The renderer clears win_on, carries on into a
pbuffer nobody sees, and stays alive - so watch.sh's ``if ! pad_gl_try`` gate,
which is how PAD-117's software retry is reached, never fires.  One line in a
log the user had no reason to open was the only sign.

WHAT THE PANE HOLDS IN EACH SHOT.  Both shots share the two "starting renderer"
lines and the renderer's own output; they diverge at the verdict.  NEITHER SET
IS RETYPED: the renderer block was EXTRACTED FROM watch.sh BY MARKER (from
``PAD_GL_MODE=gpu`` to the ``esac`` that closes the window verdict) and run in
WSL against a stub padglhost that fails the way his machine does - once against
HEAD for the before shot and once against this branch for the after one.

  * before - the run keeps going with no picture at all, for the whole session,
    and the cure it names is a Windows command.
  * after  - the same failure is treated as the same fault PAD-117 already
    treats: the renderer is stopped, tried again on the software rasteriser,
    and this time it gets its window.

TRIMMED, AND THE ONLY TRIM: the after run also prints the nine standing lines
that follow every "window opened" verdict (where to look if the window is not
on the desktop, and what a black one means).  They are not this ticket's and
they are identical before and after it; they are left out so the two panes can
be read side by side.

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
SETTINGS_BAK = SETTINGS + ".pad127bak"
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

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad127_log_")

# ----------------------------------------------------------------------
# The run, as the app's log pane sees it.
# ----------------------------------------------------------------------
#: Shared by both shots.  The two "starting renderer" lines are watch.sh's own
#: echoes either side of the block; everything after them is the probe's
#: measured output, with the stub's paths replaced by a real rig's.
LEAD = [
    "[emulate] [watch] starting renderer (it opens the game window; the "
    "picture arrives",
    "[emulate] [watch] with the guest's first frame, ~15 s later)",
]

#: v0.205.0.  The renderer is alive, so nothing retries; the run goes on to
#: boot the game and play it with no picture for as long as it is left up.
BEFORE = LEAD + [
    "[emulate] libEGL warning: DRI3 error: Could not get DRI3 device",
    "[emulate] [padglhost] window opened 1360x768 on DISPLAY=:0",
    "[emulate] [padglhost] ready, waiting for the game",
    "[emulate] [watch] THE RENDERER HAS NO WINDOW, so this run will show no "
    "picture at all.",
    "[emulate] [watch]   [padglhost] eglCreateWindowSurface failed 0x3003; "
    "falling back to headless",
    "[emulate] [watch]   The game itself still boots, the sound still plays and",
    "[emulate] [watch]   the virtual playfield still works - which is why this",
    "[emulate] [watch]   is worth saying out loud rather than leaving to look",
    "[emulate] [watch]   like a black screen.",
    "[emulate] [watch]   DISPLAY=:0, display state: ok",
    "[emulate] [watch]   'wsl --shutdown' and start again is the usual cure.",
    "[emulate] [watch] starting godzilla_le (boot to the first picture takes "
    "~15 s)",
]

#: This branch.  Same failure, same cure the dead renderer has had since
#: PAD-117 - and the window arrives.
AFTER = LEAD + [
    "[emulate] [watch] the renderer is UP BUT HAS NO WINDOW:",
    "[emulate] [watch]   [padglhost] eglCreateWindowSurface failed 0x3003; "
    "falling back to headless",
    "[emulate] [watch] TRYING THE RENDERER AGAIN IN SOFTWARE. The window "
    "surface",
    "[emulate] [watch]   is the graphics driver's to give and this one would "
    "not",
    "[emulate] [watch]   give it; the software rasteriser is not asking that "
    "driver",
    "[emulate] [watch]   for anything. Nothing else about the run changes - "
    "this",
    "[emulate] [watch]   game measures 59.9 fps in software - and the failed "
    "GPU",
    "[emulate] [watch]   attempt's log is kept at /home/david/padglhost.log"
    ".gpu.",
    "[emulate] [watch] cfg GALLIUM_DRIVER=llvmpipe (software renderer)",
    "[emulate] [watch] the renderer is up in SOFTWARE (llvmpipe).",
    "[emulate] [padglhost] window opened 1360x768 on DISPLAY=:0",
    "[emulate] [padglhost] llvmpipe (LLVM 20.1.2, 256 bits) | OpenGL ES 3.2 "
    "Mesa 25.2.8-0ubuntu0.24.04.2",
    "[emulate] [padglhost] ring /home/david/spike2root/dump/padgl (64 MB), "
    "display 1920x1080",
    "[emulate] [padglhost] ready, waiting for the game",
    "[emulate] [watch] game window opened 1360x768 on DISPLAY=:0",
    "[emulate] [watch] starting godzilla_le (boot to the first picture takes "
    "~15 s)",
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
    # callback after a tab change, which undoes a value set any earlier.
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
