"""Capture the Emulate tab's setup notice for PAD-139 (Ubuntu 26.04).

    python scripts/shot_pad139.py <out.png> <facts.txt>

A near-twin of shot_emulate_sound.py (same PrintWindow, same DPI-unaware
capture, same settings backup, same measured notebook height).

WHERE THE FACTS COME FROM.  <facts.txt> is what setupcheck.sh printed inside a
real Ubuntu 26.04.1 userland (ubuntu-base, apt-get update against the resolute
archive) with no qemu installed - HEAD's rig for the before shot, the fixed
rig for the after shot.  Only the facts about the ARM interpreter and the
archive are taken from it.  Everything else is the reporter's machine as his
screenshot shows it: every other package present and the 32-bit ARM handler
registered, because his notice named qemu-user-static and nothing else.  A
bare ubuntu-base has no compiler, no WSL and no /proc, and letting THAT into
the shot would bury the one line the ticket is about.
"""
import ctypes
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate.png")
FACTS_FILE = sys.argv[2] if len(sys.argv) > 2 else ""
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak139"

#: The facts the 26.04 probe decides.  pkg_* is the key PAD-139 adds; a build
#: from before it ignores the key, which is exactly what a before shot shows.
FROM_PROBE = ("qemu", "indexed", "components", "nocand", "universe", "xrel",
              "distro", "pm")

#: The reporter's machine apart from the interpreter.
FACTS = {"qemu": "1", "armgcc": "1", "nativecc": "1", "debugfs": "1",
         "fuse": "1", "ffmpeg": "1", "busybox": "1", "make": "1", "criu": "1",
         "binfmt": "1", "iswsl": "1", "wslconf": "1", "user": "ales",
         "interop": "1", "display": "ok", "winaudio": "1", "winpf": "1"}


def log(msg):
    print(msg, flush=True)


def probe_facts(path):
    got = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            key, sep, value = line.rstrip("\r\n").partition("=")
            if sep and (key in FROM_PROBE or key.startswith("pkg_")):
                got[key] = value
    return got


if FACTS_FILE:
    FACTS.update(probe_facts(FACTS_FILE))
log("REPO=%s" % REPO)
log("FACTS=%r" % FACTS)

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = os.path.join(
    os.environ.get("TEMP", "c:\\tmp"), "pad139_shot_log_%d" % os.getpid())

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.gui import emulate_tab  # noqa: E402

log("fix steps: %r" % (emulate_tab.setup_fix_steps(dict(FACTS)),))

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


GEOM = None


def snap(path):
    # Re-asserted here (PAD-60): the app resizes itself to the active tab on
    # an idle callback whose timing differs run to run.
    for _ in range(2):
        if GEOM:
            root.geometry(GEOM)
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
    global GEOM
    w = min(1100, root.winfo_screenwidth() - 80)
    h = min(1040, root.winfo_screenheight() - 90)
    GEOM = "%dx%d+40+40" % (w, h)
    root.geometry(GEOM)


@step(6000)
def s_emulate_tab():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_facts():
    """Hand the panel the 26.04 machine.  The panel's own probe asks THIS PC
    and would overwrite it, so it is stubbed first; _setup_apply draws the
    notice and packs (or hides) the button either way."""
    panel = win._emulate_panel
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._setup_apply(dict(FACTS))
    root.update_idletasks()
    win._notebook.configure(height=win._tab_emulate.winfo_reqheight() + 30)
    root.update_idletasks()
    # The tab is taller than this box's 1024x768 desktop, and the notice is
    # the LAST thing in it - the first capture showed its headline and
    # nothing else.  The manufacturer view scrolls; take it to the bottom.
    win._mfr_view_canvas.yview_moveto(1.0)
    root.update_idletasks()
    log("view yview=%r" % (win._mfr_view_canvas.yview(),))
    msg = panel._setup_msg
    log("notice mapped=%s h=%s button packed=%s text=%r"
        % (msg.winfo_ismapped(), msg.winfo_height(),
           bool(panel._setup_btn.winfo_manager()), msg.cget("text")))


@step(2000)
def s_snap():
    snap(OUT)


@step(500)
def s_done():
    root.destroy()


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


root.after(120000, lambda: root.destroy())
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
