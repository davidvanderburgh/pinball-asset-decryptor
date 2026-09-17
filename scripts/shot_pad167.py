"""PAD-167: checking the videos already written to a card for blocky clips.

    python scripts/shot_pad167.py <card.raw> <project_dir> <out_dir> <before|after>

Two shots per run:

* ``<when>_video_tab.png`` — the Replace Video tab over *project_dir*.  Before
  the change its toolbar offers Search / Show / Export CSV and no way to ask
  anything about the card the clips came off; after it, there is a
  "Check card…" button.
* ``<when>_card_report.png`` — after: the report window itself, having
  measured every clip on *card.raw*.  Before: the same Video tab, because the
  window did not exist and the Video tab is where a user went looking.

Nothing is written: the report opens the card image read-only and the tab is
only scanned, never staged.  settings.json is backed up and restored, and the
session log is sandboxed to a scratch dir so the log pane starts clean.
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
if len(sys.argv) != 5 or sys.argv[4] not in ("before", "after"):
    sys.exit(__doc__)
CARD, PROJECT, OUT_DIR, WHEN = sys.argv[1:5]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad167bak"


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "stern"
stern = settings.setdefault("manufacturers", {}).setdefault("stern", {})
stern.update(extract_input=CARD, write_original=CARD,
             extract_output=PROJECT, write_assets=PROJECT)
# Widths dragged on a wide monitor push the last column off this shot; let the
# tab fit its own content so both runs measure the same way.
(settings.get("column_widths") or {}).pop("video", None)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad167_log_")

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
SW, SH = root.winfo_screenwidth(), root.winfo_screenheight()
GEOM = "%dx%d+10+10" % (min(1100, SW - 40), SH - 70)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def _grab(hwnd, name, crop_border=True):
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
    bih.biWidth, bih.biHeight = w, -h  # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    if crop_border:
        border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
        img = img.crop((border, 0, w - border, h - border))
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def snap(name):
    # The app re-sizes itself to the active tab on an idle callback; let it
    # run, then put the shot's geometry back so before and after line up.
    for _ in range(2):
        root.geometry(GEOM)
        root.update_idletasks()
    root.update()
    _grab(user32.GetAncestor(root.winfo_id(), 2), name)   # GA_ROOT


def snap_dialog(dlg, name):
    root.update_idletasks()
    _grab(user32.GetAncestor(dlg.winfo_id(), 2), name)


STEPS = []
STATE = {}


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_setup():
    root.geometry(GEOM)
    log("manufacturer: %s" % getattr(app._current_mfr, "key", None))
    log("assets: %s" % win.write_assets_var.get())
    log("card: %s" % win.extract_input_var.get())


@step(6000)
def s_video_tab():
    win._notebook.select(win._tab_video)


# The scan lists the slots straight away; the ffprobe pass that fills Length /
# Resolution / Format is one subprocess per clip, so both runs wait the same
# (long) time before snapping or the two shots show different columns.
@step(75000)
def s_video_snap():
    log("video slots: %d" % len(win._video_slots))
    probed = sum(1 for s in win._video_slots if s.probed)
    log("probed: %d" % probed)
    snap("video_tab")


@step(1000)
def s_open_report():
    btn = getattr(win, "_video_card_check_btn", None)
    log("check-card button present: %s" % bool(btn))
    if btn is None:
        # BEFORE: there is no such button.  The Video tab IS the answer to
        # "where would you have looked", so it stands in for the pair.
        snap("card_report")
        root.destroy()
        raise StopIteration
    win._open_video_quality_report()
    dlg = next((w for w in root.winfo_children()
                if isinstance(w, __import__("tkinter").Toplevel)
                and w.title() == "Check the videos on a card"), None)
    STATE["dlg"] = dlg
    log("report window: %s" % bool(dlg))


@step(1500)
def s_check():
    panel = win._video_quality_dlg
    STATE["panel"] = panel
    log("card in the dialog: %s" % panel._card_var.get())
    panel._start()


@step(500)
def s_wait():
    # The scan is a worker thread; re-arm until it clears rather than guessing
    # a delay, then hand the chain back at the step after this one.
    resume = STATE["index"] + 1

    def poll():
        panel = STATE["panel"]
        if panel._busy:
            root.after(400, poll)
            return
        log("scan finished: %d clip(s)" % len(panel._clips))
        run_steps(resume)

    poll()
    raise StopIteration


@step(2000)
def s_report_snap():
    panel = STATE["panel"]
    log("summary: %s" % panel._summary.cget("text"))
    log("rows shown: %d" % len(panel._tree.get_children("")))
    snap_dialog(STATE["dlg"], "card_report")


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
            STATE["index"] = i
            fn()
        except StopIteration:
            return            # the step owns what happens next
        except Exception:
            log("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))
        run_steps(i + 1)

    root.after(delay, _go)


root.after(240000, root.destroy)    # watchdog
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
    sys.stdout.flush()
    os._exit(0)
