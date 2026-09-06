"""Capture a Multi-boot BUILD RUN on a machine with no menu program (PAD-105).

    python scripts/shot_multiboot_selector.py <out.png>
                                              [--selector-dir DIR]
                                              [--stop-at TEXT] [--seconds N]

A variant of shot_multiboot_tab.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one screen that rig does not
cover: the app's shared Log at the foot of the window while 'Build /
flash card...' is running, which is where a build says why it stopped.

THE RUN IS REAL.  Two card images off this machine go into the form, the
green button's own method is called, and every line in the picture came
out of WSL.  The one thing arranged is the FAULT: ``--selector-dir``
points at a rootfs with no ``usr/local/codeselect`` in it, which is the
state every machine is in until something builds the menu program - and
until this ticket nothing in the app ever did (the tab builds a selector
for its PREVIEW, into a scratch directory, installing nothing).  That is
what the reporter hit: the form filled in, the menu previewed, and

    [card] error: selector dir /home/x/spike2root/usr/local/codeselect is not a directory
    build failed (exit 2) - see the tool output.

seconds after pressing Build, with nothing in it to act on.

``--stop-at TEXT`` snaps as soon as a log line contains TEXT and then
CANCELS the run: the fixed build goes on to copy 14 GB into the card,
which is not what the picture is about.  Without it the shot waits for
the run to end by itself, which is what the broken one does in seconds.
"""
import ctypes
import os
import shutil
import sys
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = list(sys.argv[1:])


def _opt(name, default=""):
    if name in ARGS:
        i = ARGS.index(name)
        val = ARGS[i + 1]
        del ARGS[i:i + 2]
        return val
    return default


SELECTOR_DIR = _opt("--selector-dir", "/tmp/pad105root/usr/local/codeselect")
STOP_AT = _opt("--stop-at")
SECONDS = int(_opt("--seconds", "240"))
OUT = os.path.abspath(ARGS[0] if ARGS else "multiboot-selector.png")

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak105"

#: The card the menu is built from, and the second image on it.  Both are
#: read, never written (the tools refuse an output under the library).
IMAGES = [
    r"D:\Pinball\images\Stern\spike2\turtles_pro-1_59_0.Release.8G.sdcard.raw",
    r"D:\Pinball\TMNT 1987\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw",
]
TITLES = [("STERN 1.59.0", "Original Stern code"),
          ("TMNT 1987", "1987 cartoon upscale")]

#: Where the card would go.  A scratch path, and it must not exist: an
#: existing file puts a confirmation in front of the run.
CARD_OUT = r"C:\tmp\PAD-105\build\turtles-multi.16G.sdcard.raw"

#: No automatic runs behind the photograph - the size check and the
#: preview both shell out to WSL, and this rig starts exactly one run.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
#: ...and THE FAULT (the tab reads this on startup - it is the only way to
#: move the selector directory; there is no box for it).
os.environ["PAD_MULTIBOOT_SELECTOR"] = SELECTOR_DIR

SHOT_W, SHOT_H = 1360, 900


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc),
              flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.makedirs(os.path.dirname(CARD_OUT), exist_ok=True)
if os.path.exists(CARD_OUT):
    os.remove(CARD_OUT)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

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


def snap(path):
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


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    root.maxsize(max(SHOT_W, root.winfo_screenwidth()) + 100,
                 max(SHOT_H, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (SHOT_W, SHOT_H))


@step(6000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    """The form, through the panel's public seams - the same ones
    tests/test_multiboot_tab.py fills it with.  FROM EMPTY: the tab
    remembers its last form per project, and add_image appends."""
    panel = win._multiboot_panel
    panel.new_card()
    for path in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s" % path)
        panel.add_image(path)
    for i, (title, sub) in enumerate(TITLES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    panel._out_var.set(CARD_OUT)
    # THE FAULT, SET ON THE TAB AND NOT ONLY IN THE ENVIRONMENT.  The var
    # is seeded from PAD_MULTIBOOT_SELECTOR at build time, but the tab
    # remembers its form per project and the restore that follows puts the
    # saved value back - so a shot that only exported the variable
    # photographed a build against THIS machine's own installed selector.
    panel._selector_var.set(SELECTOR_DIR)
    root.update()
    log("selector dir: %s" % panel._selector_var.get())
    log("card out: %s" % panel._out_var.get())


@step(1500)
def s_build():
    """Press it.  _build_card is what the green button's modal calls."""
    panel = win._multiboot_panel
    panel._selector_var.set(SELECTOR_DIR)       # nothing may have moved it
    log("selector dir at press: %s" % panel.form().selector_dir)
    log("build started: %s" % panel._build_card())


@step(500)
def s_wait_and_snap():
    """Wait on the tab's own state, then photograph the window.

    Two ways out: the run ends by itself (what a build with nothing to
    build the menu from does, in seconds), or --stop-at names a log line
    to stop at - snapped first, then cancelled, so the picture is of the
    run rather than of the cancellation."""
    panel = win._multiboot_panel
    deadline = time.time() + SECONDS

    def poll():
        lines = panel.log_lines()
        hit = STOP_AT and any(STOP_AT in ln for ln in lines)
        if not panel._busy or hit or time.time() > deadline:
            log("run finished=%s hit=%s lines=%d"
                % (not panel._busy, bool(hit), len(lines)))
            for ln in lines[-40:]:
                log("   | %s" % ln)
            log("status: %r" % panel.message())
            root.update_idletasks()
            snap(OUT)
            if panel._busy:
                log("cancelling the run: %s" % panel.cancel_run())
                root.after(4000, root.destroy)
            else:
                root.after(500, root.destroy)
            return
        root.after(500, poll)

    poll()


def run_steps(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            log("step %d: %s" % (i, fn.__name__))
            fn()
        except Exception:
            log("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))
        run_steps(i + 1)

    root.after(delay, _go)


root.after((SECONDS + 60) * 1000, lambda: root.destroy())
run_steps()
try:
    app.run()
finally:
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
