"""PAD-171: a converted replacement clip came out far below the stock bitrate.

    python scripts/shot_pad171.py <card.raw> <stock_clip> <replacement> <out_dir> <before|after>

Two shots per run:

* ``<when>_stage_log.png`` — the main window's log after the app converts
  *replacement* for a one-clip scratch project whose only slot is
  *stock_clip* (copied in as ``video/<its name>``), with "match length" on so
  the clip really is re-encoded.  The log line is where the user can see what
  the conversion did to the clip.
* ``<when>_card_report.png`` — the "Check the videos on a card" report over
  *card.raw*, whose summary told the user to re-export clips that the app
  itself had converted.

Nothing is written outside a temp dir: the scratch project is made there, the
card is only read, settings.json is backed up and restored, and the session
log is sandboxed so the log pane starts clean.
"""
import ctypes
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 6 or sys.argv[5] not in ("before", "after"):
    sys.exit(__doc__)
CARD, STOCK, REPLACEMENT, OUT_DIR, WHEN = sys.argv[1:6]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad171bak"


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

# The scratch project: one slot, the stock clip, and a recorded assignment —
# exactly what the Video tab leaves behind for the build to stage.
PROJECT = tempfile.mkdtemp(prefix="pad171_proj_")
# The ticket's attachments are numbered ("02-magnagrab.mp4"); the slot is the
# card's own name.
slot_name = re.sub(r"^\d+-", "", os.path.basename(STOCK))
os.makedirs(os.path.join(PROJECT, "video"))
shutil.copy2(STOCK, os.path.join(PROJECT, "video", slot_name))
with open(os.path.join(PROJECT, ".staged_changes.json"), "w",
          encoding="utf-8") as f:
    json.dump({"video": {"video/" + slot_name: REPLACEMENT},
               "video_trim": True}, f)

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "stern"
stern = settings.setdefault("manufacturers", {}).setdefault("stern", {})
stern.update(extract_input=CARD, write_original=CARD,
             extract_output=PROJECT, write_assets=PROJECT)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad171_log_")

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


def wait_for(done, resume_offset=1):
    """Re-arm until *done()* is true, then continue the chain after this
    step (rather than guessing a delay for work on another thread)."""
    resume = STATE["index"] + resume_offset

    def poll():
        if not done():
            root.after(300, poll)
            return
        run_steps(resume)

    poll()
    raise StopIteration


@step(500)
def s_setup():
    root.geometry(GEOM)
    log("manufacturer: %s" % getattr(app._current_mfr, "key", None))
    log("scratch project: %s" % PROJECT)


@step(2500)
def s_video_tab():
    win._notebook.select(win._tab_video)


@step(2500)
def s_stage():
    # What a build does first: stage the recorded assignment on a worker.
    def work():
        try:
            STATE["staged"] = app._stage_pending_video(PROJECT)
        except Exception:
            STATE["staged"] = traceback.format_exc()
    threading.Thread(target=work, daemon=True).start()
    wait_for(lambda: "staged" in STATE)


@step(1500)
def s_stage_snap():
    log("staging result: %r" % (STATE["staged"],))
    out = os.path.join(PROJECT, "video", slot_name)
    from pinball_decryptor.core.video_quality import quality_of_file
    q = quality_of_file(out)
    log("staged clip: %d B, %s, %.2f s, bpp %.4f"
        % (q.size, q.bitrate_str(), q.duration, q.bpp or 0))
    snap("stage_log")


@step(500)
def s_open_report():
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
    wait_for(lambda: not STATE["panel"]._busy)


@step(2000)
def s_report_snap():
    panel = STATE["panel"]
    log("scan finished: %d clip(s)" % len(panel._clips))
    log("summary: %s" % panel._summary.cget("text"))
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
    shutil.rmtree(PROJECT, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)
