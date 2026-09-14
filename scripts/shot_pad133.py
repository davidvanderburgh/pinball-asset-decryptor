"""PAD-133 proof shot: the override run that ended before the guest started.

    python scripts/shot_pad133.py <out_dir> <before|after>

THE REPORTED RUN.  DragonRR ticks "Apply my replaced assets on top, without
rebuilding the card", having replaced ONE image.  The set builds, his asset is
named in the log, the emulator's window opens - and stays black.  Writing a
card image from the same edit and running THAT works.

WHY.  Every override set carries three files, not one: the asset, the game ELF
(the validator bypass is applied on every write) and ``spk/index/<title>.sidx``
(so is the SD-validation refresh).  The .sidx sits BESIDE the title on the
games partition - and a CARD run does not mount that partition.  cardmount.sh
puts it on a FUSE mount outside the namespace and prints the TITLE directory,
which is the only thing run_game.sh binds into ``games/``.  So the .sidx had
nowhere to land, the bind loop's "a target that is not there is a hard error"
fired, and ``exit 1`` ran with the renderer window already open.  It passed on
the desk it was written on because that rootfs has titles extracted into
``games/`` by hand, so it has a ``games/spk/index`` to bind onto.

WHAT THE PANE HOLDS IN EACH SHOT.  Both share the lead-in - the app's own
override build, and the rig up to the bind loop - and diverge at the line after
it.  NOTHING IS RETYPED.  The build lines are from a real
``engine.write_overrides`` against
``D:\\Pinball\\images\\Stern\\spike2\\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw``
with one replaced image; the ``[ovr]`` lines are from running overrides.sh on
that set in WSL; and both ``[run] your edits:`` blocks are the output of
run_game.sh's OWN bind loop, extracted by marker and run in a real mount
namespace against a games/ laid out the way a card run lays one out - before
the fix and after it.

WHY THE LINES ARE FED RATHER THAN PRODUCED.  A real card run copies a 7.3 GB
card onto the WSL disk and boots a guest; the widget path is the real one
either way (``append_log`` is the sink every emulator line goes through), so
what the pane does with these lines is exactly what it does with a run's.

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
SETTINGS_BAK = SETTINGS + ".pad133bak"
GEOM = None
#: How much of the window the Emulate tab keeps; the log pane gets the rest.
NB_H = 205

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

# The log pane preloads earlier sessions from the real rolling log; a fresh
# scratch dir per run keeps the before shot's lines out of the after shot.
from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad133_log_")

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

# ----------------------------------------------------------------------
# The run, as the app's log pane sees it.
# ----------------------------------------------------------------------
#: Shared by both shots: the set being built (the engine's own lines, measured)
#: and the rig up to the bind loop.  Three of the build's lines are left out
#: (the image's fit, the .sidx refresh and the validation-bypass line that
#: says why the game ELF is in the set) so that the longer of the two panes
#: still fits this desktop without scrolling; nothing else is trimmed and
#: nothing is reworded.
LEAD = [
    "[emulate] preparing your edits (there is no set staged yet)",
    "[emulate] Found 1 replaced image(s) to write.",
    "[emulate] Override: /godzilla_le/assets/nuk/images/Connectivity/TestMenu/"
    "Boxes_2.png (0.0 MB)",
    "[emulate] Override: /godzilla_le/game (8.0 MB)",
    "[emulate] Override: /spk/index/godzilla_le-1_16_0.sidx (0.4 MB)",
    "[emulate] Built the emulator override set in 1 s: 3 file(s), 8 MB "
    "written (0 sound(s), 0 video(s), 1 image(s), 0 display string(s)).",
    "[emulate] 3 card file(s) will be applied on top of the card: "
    "/godzilla_le/assets/nuk/images/Connectivity/TestMenu/Boxes_2.png, "
    "/godzilla_le/game, /spk/index/godzilla_le-1_16_0.sidx",
    "[emulate] [watch] starting godzilla_le (boot to the first picture takes "
    "~15 s)",
    "[emulate] [run] title: godzilla_le (from the card, not extracted)",
    "[emulate] [ovr] staging 8 MB of override files -> /home/david/override",
    "[emulate] [ovr] staged 4 file(s)",
]

#: v0.206.1.  The bind loop's own output, and then the run is over: the
#: renderer's window is open and nothing will ever draw into it.
BEFORE = LEAD + [
    "[emulate] [run] your edits: could not apply "
    "spk/index/godzilla_le-1_16_0.sidx",
    "[emulate] [run]   the card being booted does not have that file, so this",
    "[emulate] [run]   override set was built from a different card. Rebuild it",
    "[emulate] [run]   against this one.",
    "[emulate] [watch] waiting for the game to start...",
    "[emulate] [watch] the game never started. Last lines of its log:",
]

#: The same loop, fixed, on the same set and the same games/ layout.
AFTER = LEAD + [
    "[emulate] [run] your edits: 2 file(s) applied on top of the card (nothing",
    "[emulate] [run]   was rebuilt and the card image itself is untouched)",
    "[emulate] [run]   not applied, and not needed here: "
    "spk/index/godzilla_le-1_16_0.sidx",
    "[emulate] [run]   those sit beside the title on the card (the "
    "SD-validation",
    "[emulate] [run]   record the machine checks), and a card run mounts the",
    "[emulate] [run]   title's own directory and nothing else. Every edit you",
    "[emulate] [run]   made is in the 2 file(s) above.",
    "[emulate] [watch] waiting for the game to start...",
    "[emulate] [watch] auto-advance on: it will press Service Back until the "
    "game",
    "[emulate] [watch] leaves Tech Alerts (PAD_AUTO_ATTRACT=0 to do it "
    "yourself).",
]

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
