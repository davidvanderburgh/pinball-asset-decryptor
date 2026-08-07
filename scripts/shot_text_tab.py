"""Capture the Replace Text tab (the screen PAD-37's feedback is about).

    python scripts/shot_text_tab.py <out_dir> <before|after>

``text_tab``
    The whole Text tab on a wide window, with a string selected so the
    editor panel and its scene note are filled in.  Wide on purpose: the
    reported problems (a stretched Max column whose header sits nowhere
    near its numbers, and help text that wraps in the left half of a
    window with 600 spare pixels) only show up once the window is bigger
    than the fixed wraplengths.

The app is pointed at a COPY of the project folder's ``text/`` (in a
scratch dir under %TEMP%), never the real extract: the tab writes a
``.staged_changes.json`` sidecar when a filter or a scene name changes,
and a proof run must not leave anything behind in a real project.

Capture notes follow take_screenshots.py: DPI-unaware process, PrintWindow
(PW_RENDERFULLCONTENT) rather than a screen grab.  settings.json is backed
up and restored, and the rolling session log is redirected into the scratch
dir so the log pane can't drag a previous run's noise into the shot.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad37bak"
SCRATCH = os.path.join(tempfile.gettempdir(), "pad37_text_%s" % WHEN)


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# Preflight: the shot needs a real extract's text/strings.tsv, resolved
# from the app's own saved settings.
# ----------------------------------------------------------------------
with open(SETTINGS, encoding="utf-8") as f:
    _settings = json.load(f)
_stern = _settings.get("manufacturers", {}).get("stern", {})
_src = (_stern.get("write_assets") or _stern.get("extract_output") or "").strip()
_tsv = os.path.join(_src, "text", "strings.tsv")
if not os.path.isfile(_tsv):
    sys.exit("Not capturing — no on-screen-text manifest at %r.\n"
             "Extract a Spike 2 card with Text ticked first." % _tsv)

shutil.rmtree(SCRATCH, ignore_errors=True)
os.makedirs(os.path.join(SCRATCH, "text"), exist_ok=True)
shutil.copy2(_tsv, os.path.join(SCRATCH, "text", "strings.tsv"))
log("project folder for the shot: %s" % SCRATCH)

shutil.copy2(SETTINGS, SETTINGS_BAK)
_settings.setdefault("manufacturers", {}).setdefault("stern", {})
_settings["manufacturers"]["stern"]["write_assets"] = SCRATCH
_settings["manufacturers"]["stern"]["extract_output"] = SCRATCH
_settings["last_manufacturer"] = "stern"
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(_settings, f, indent=2)
log("settings backed up + pointed at the scratch folder")

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402

# Keep this run's log lines out of David's real rolling log (and the previous
# run's lines out of this shot).
session_log.LOG_DIR_OVERRIDE = os.path.join(SCRATCH, "logs")

from pinball_decryptor.app import App  # noqa: E402

# The update banner is whatever GitHub happens to be serving on the day, and
# it shifts the whole window down — a before/after pair has to differ only in
# the change under test, so this run never checks.
App._check_for_update = lambda self: None

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


app = App()
root = app.root
win = app.window


def snap(name):
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)      # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)                 # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h                  # top-down
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
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
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
    # Wide enough that the fixed wraplengths and the stretched Max column
    # are obvious — the reporter's own window was ~1900 logical pixels.
    w = min(1700, root.winfo_screenwidth() - 60)
    h = min(760, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+30+30" % (w, h))


@step(6000)
def s_text_tab():
    win._notebook.select(win._tab_text)


@step(4000)
def s_select_row():
    tree = win._text_tree
    kids = tree.get_children("")
    log("text rows: %d" % len(kids))
    if kids:
        iid = kids[min(4, len(kids) - 1)]
        tree.see(iid)
        tree.focus(iid)
        tree.selection_set(iid)


@step(1500)
def s_name_a_scene():
    """after-run only: give the selected row's scene a friendly name, so the
    shot shows the Name column doing its job."""
    if WHEN != "after":
        return
    sel = win._text_tree.selection()
    if not sel:
        log("!! nothing selected — no scene to name")
        return
    win._ask_text = lambda *a, **k: "Ball save banner"
    win._text_scene_rename(sel[0])
    log("named the selected row's scene")


@step(1500)
def s_snap():
    snap("text_tab")


@step(500)
def s_write_tab():
    # The Project Folder link is shared by every tab that shows the folder;
    # Write draws its row through the other of the two helpers, so it proves
    # the change reached both.
    win._notebook.select(win._tab_write)


@step(4000)
def s_write_snap():
    snap("write_tab")


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


def watchdog():
    log("watchdog fired — forcing exit")
    try:
        root.destroy()
    except Exception:
        pass


root.after(120000, watchdog)
run_steps()
try:
    app.run()
finally:
    try:
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
        log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
