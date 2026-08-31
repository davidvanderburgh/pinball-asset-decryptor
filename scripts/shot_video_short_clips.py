"""Capture the Replace Video tab on a folder of very short clips.

    python scripts/shot_video_short_clips.py <out_dir> <before|after>

``video-short-clips``
    The slot list plus the Preview box, with a one-frame slot selected.  A
    sixth of a Spike 2 card's clips are shorter than a second, and the field
    report this reproduces is what that looked like: a Length column reading
    "0:00", a player readout of "0:00 / 0:00", and a Preview pane saying the
    clip couldn't be decoded.

The five clips are the "Egghead" slots the report showed, copied out of a
real Batman extract into a scratch folder together with the matching
.checksums.md5 rows (so the list reads "0 of 5 slots changed", the way it
does in a real project rather than a hand-made folder).  Capture notes follow
take_screenshots.py: DPI-unaware process, PrintWindow(PW_RENDERFULLCONTENT)
rather than a screen grab, settings.json backed up and restored, and the
rolling session log redirected to the scratch folder.
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
SETTINGS_BAK = SETTINGS + ".pad97bak"
SCRATCH = os.path.join(tempfile.gettempdir(), "pad97_shot_%s" % WHEN)

# The row the report had selected: a single 800x600 frame, 1/30 s long.
ROW = "video/VillainsCaptured_Villain_Egghead.mp4"
CLIPS = ["AttractModeVillains_Egghead.mp4",
         "VillainsCaptured_Villain_Egghead.mp4",
         "VillainsCaptured_Villain_Egghead_2.mp4",
         "VillainsCaptured_Villain_Egghead_Captured.mov",
         "VillainsCaptured_Villain_Egghead_Captured_2.mp4"]


def log(msg):
    print(msg, flush=True)


# --- the scratch project ----------------------------------------------------
# Sourced from whichever Stern extract the app is pointed at, so the shot is
# of real card video rather than something ffmpeg made up.
with open(SETTINGS, encoding="utf-8") as f:
    _stern = json.load(f).get("manufacturers", {}).get("stern", {})
SRC = (_stern.get("write_assets") or _stern.get("extract_output") or "").strip()
if not os.path.isdir(os.path.join(SRC, "video")):
    sys.exit("Not capturing — no extracted video/ folder at %r (settings "
             "write_assets). Extract a Stern card with Video ticked first."
             % SRC)
missing = [c for c in CLIPS
           if not os.path.isfile(os.path.join(SRC, "video", c))]
if missing:
    sys.exit("Not capturing — %s holds no %s. These shots want a Batman "
             "extract." % (SRC, missing[0]))

shutil.rmtree(SCRATCH, ignore_errors=True)
os.makedirs(os.path.join(SCRATCH, "video"))
for clip in CLIPS:
    shutil.copy2(os.path.join(SRC, "video", clip),
                 os.path.join(SCRATCH, "video", clip))
# Carry the Extract baseline for just these five, or every row reads
# "already changed on disk" and buries the columns under test.
try:
    with open(os.path.join(SRC, ".checksums.md5"), encoding="utf-8") as f:
        rows = [ln for ln in f
                if ln.split("\t")[0] in ("video/" + c for c in CLIPS)]
    with open(os.path.join(SCRATCH, ".checksums.md5"), "w",
              encoding="utf-8") as f:
        f.writelines(rows)
except OSError:
    pass
log("scratch project: %s" % SCRATCH)

# --- capture plumbing -------------------------------------------------------
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


shutil.copy2(SETTINGS, SETTINGS_BAK)
try:
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["last_manufacturer"] = "stern"
    st = cfg.setdefault("manufacturers", {}).setdefault("stern", {})
    st["extract_output"] = SCRATCH
    st["write_assets"] = SCRATCH
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    from PIL import Image  # noqa: E402

    from pinball_decryptor.core import session_log  # noqa: E402
    session_log.LOG_DIR_OVERRIDE = SCRATCH  # never touch the real history

    from pinball_decryptor.app import App  # noqa: E402

    app = App()
    root = app.root
    win = app.window

    def snap(name):
        root.update_idletasks()
        hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
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
        border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
        img = img.crop((border, 0, w - border, h - border))
        path = os.path.join(OUT_DIR, name)
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
        w = min(1040, root.winfo_screenwidth() - 80)
        h = min(860, root.winfo_screenheight() - 90)
        root.geometry("%dx%d+40+40" % (w, h))

    # Let the prereq / update checks settle before touching the tabs.
    @step(7000)
    def s_video_tab():
        win._notebook.select(win._tab_video)
        win.video_search_var.set("egg")

    @step(6000)
    def s_select_short_clip():
        tree = win._video_tree
        rows = tree.get_children("")
        log("video rows: %d" % len(rows))
        target = ROW if tree.exists(ROW) else (rows[0] if rows else None)
        if target:
            tree.see(target)
            tree.focus(target)
            tree.selection_set(target)
            win._video_on_tree_select()

    # The poster frame renders on a worker thread; the delay is it landing
    # before the shutter.
    @step(6000)
    def s_snap():
        snap("%s_video-short-clips.png" % WHEN)
        for iid in win._video_tree.get_children(""):
            log("  %-58s len=%s" % (iid, win._video_tree.set(iid, "len")))
        log("player readout: %s" % win._video_pane_orig.time_var.get())

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
                log("step %s FAILED:\n%s" % (fn.__name__,
                                             traceback.format_exc()))
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
    app.run()
finally:
    if os.path.exists(SETTINGS_BAK):
        shutil.move(SETTINGS_BAK, SETTINGS)
        log("settings.json restored")
