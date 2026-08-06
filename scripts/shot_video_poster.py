"""Capture the Replace Video Preview box after a clip has played to the end.

    python scripts/shot_video_poster.py <out_dir> <before|after>

``video_preview``
    Original and Replacement side by side.  Both clips fade in from black —
    the shape of the field report's replacement — and the Replacement pane is
    photographed right after it played through and rewound to 0:00, which is
    the moment the reporter filmed.

The two clips are generated with ffmpeg into a scratch folder, so the run
needs no project data and touches nothing of David's.  Capture notes follow
take_screenshots.py: DPI-unaware process, PrintWindow(PW_RENDERFULLCONTENT)
rather than a screen grab, settings.json backed up and restored, and the
rolling session log redirected to the scratch folder.
"""
import ctypes
import json
import os
import shutil
import subprocess
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
SETTINGS_BAK = SETTINGS + ".pad36bak"
SCRATCH = os.path.join(tempfile.gettempdir(), "pad36_shot_%s" % WHEN)
shutil.rmtree(SCRATCH, ignore_errors=True)
os.makedirs(SCRATCH, exist_ok=True)


def log(msg):
    print(msg, flush=True)


# --- the two clips ----------------------------------------------------------
# A logo sting: 7 s, black at frame 0, fading up to a bright card by the
# middle.  Frame 0 being black is the whole point — that is the frame the
# pane went back to when the clip ended.
def make_clip(name, box):
    path = os.path.join(SCRATCH, name)
    vf = ("drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill,"
          "fade=in:st=0:d=2.5" % box)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", "color=c=black:s=1360x768:r=30:d=7",
           "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path]
    subprocess.run(cmd, check=True)
    log("built %s" % path)
    return path


ORIG = make_clip("GameLogo.mp4", (230, 250, 900, 170, "0xff2d78@1"))
REP = make_clip("GameLogo Update.mp4", (180, 230, 1000, 220, "0x22e0ff@1"))

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


if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
try:
    # Open straight into the Stern tabs with no project data behind them: an
    # empty scratch folder keeps the log free of missing-folder noise.
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

    def snap_preview(name):
        """Snap the window, then crop to the Preview box — the panes are what
        changed, and a full-window shot buries them."""
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
        player = win._video_pane_orig.frame.master.master  # the Preview box
        x0 = player.winfo_rootx() - (r.left + border) - 10
        y0 = player.winfo_rooty() - r.top - 24
        img = img.crop((max(0, x0), max(0, y0),
                        min(w, x0 + player.winfo_width() + 20),
                        min(h, y0 + player.winfo_height() + 34)))
        path = os.path.join(OUT_DIR, name)
        img.save(path)
        log("snapped %s (%dx%d)" % (path, img.width, img.height))

    STEPS = []

    def step(delay_ms):
        def deco(fn):
            STEPS.append((delay_ms, fn))
            return fn
        return deco

    @step(2500)
    def s_video_tab():
        root.geometry("1360x830+40+40")
        win._notebook.select(win._tab_video)

    @step(1200)
    def s_load():
        win._video_pane_orig.load(ORIG)
        win._video_pane_rep.load(REP)

    # Both panes poster a mid-clip frame here.  Then play the Replacement all
    # the way through: at the end the pane rewinds to 0:00 and re-posters,
    # which is the state under test.
    @step(3000)
    def s_play():
        win._video_pane_rep.start_playback(0.0)

    @step(11000)
    def s_snap():
        log("rep pane pos=%.2f playing=%s"
            % (win._video_pane_rep.pos, win._video_pane_rep.playing))
        snap_preview("%s_video_preview.png" % WHEN)

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
