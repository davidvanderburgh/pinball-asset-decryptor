"""PAD-110 proof shots: what the log pane says about a replacement video the
app did not put on the card, why a clip was re-encoded, and what the sound
encoding step is actually doing.

All three land in the main window's log pane, so all three shots are that pane
with real lines pushed through the real code paths -- ``_intact_copy_source``
for the build verdict, ``core.video_slots.stage_replacements`` (real ffmpeg,
real clips) for the staging line, and ``_encode_cat0_parallel`` for the sound
header.  The fixture mirrors the tester's Beatles run: his mod card is
MP4-branded throughout, the 1.29 card's slots are QuickTime.

    python scripts/shot_pad110.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up) follow
scripts/take_screenshots.py -- see its header for why they are what they are.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad110bak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.core.video import find_ffmpeg  # noqa: E402
from pinball_decryptor.core.video_slots import (  # noqa: E402
    scan_video_slots, stage_replacements)
from pinball_decryptor.plugins.stern import engine  # noqa: E402

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


# ----------------------------------------------------------------------
# Fixture: real clips, the tester's shapes.  His mod files are MP4-branded
# (that is how they sit on his working 1.27 card); the 1.29 slots they go
# into are QuickTime, at 720x540.
# ----------------------------------------------------------------------
WORK = tempfile.mkdtemp(prefix="pad110_shot_")
FFMPEG = find_ffmpeg()


def render(path, width=720, height=540, fps=30, seconds=1.0):
    """A real clip, so every probe in the gates below is a real probe."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi",
         "-i", "testsrc=size=%dx%d:rate=%d:duration=%s"
               % (width, height, fps, seconds),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True)
    return path


def pad_to(path, size):
    """Grow a rendered clip to a realistic on-card byte count with a trailing
    ``free`` box (what the build itself pads with), so the sizes in the log
    lines are the tester's rather than a one-second test clip's."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < size:
        with open(path, "wb") as fh:
            fh.write(engine._pad_isobmff(data, size))
    return path


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(600)
def s_enter():
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(900, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


# ---- shot 1: the build deciding whose bytes go on the card -------------
# (fname, the user's own file, the app's format-matched copy, the slot).
# The last two columns are the tester's real numbers, straight out of his
# log -- including the three where the app's re-encode came out BIGGER than
# the clip it was replacing.
_CLIPS = [("Sullivan_Sullivan_Sub_26.mov", 611392, 554788, 880124),
          ("Sullivan_Sullivan_Sub_27.mov", 7955168, 8438404, 8871809),
          ("Sullivan_Sullivan_Sub_36.mov", 6104960, 7109533, 5891532),
          ("Shea_Shea_Sub_17.mov", 3312640, 4617622, 2850059),
          ("Shea_Shea_Sub_23.mov", 3901184, 4643578, 3423931)]


@step(900)
def s_build():
    clear_log()
    win.append_log("Applying 228 video replacement(s) to the card...", "info")
    for fname, src_size, staged_size, slot_size in _CLIPS:
        stem = os.path.splitext(fname)[0]
        # The user's own file, as PAD extracted it off his modded card: MP4.
        src = pad_to(render(os.path.join(WORK, "mods", stem + ".mp4")),
                     src_size)
        # The app's format-matched copy, made by Replace-Video: QuickTime.
        staged = pad_to(render(os.path.join(WORK, "new", fname)),
                        staged_size)
        engine._intact_copy_source(src, staged, fname, slot_size,
                                   win.append_log)
    win.append_log("Growing 229 file(s) to full size via the Linux "
                   "filesystem driver...", "info")


@step(900)
def s_build_snap():
    snap("%s_video_build_log.png" % WHEN)


# ---- shot 2: staging saying why a clip was re-encoded ------------------
@step(900)
def s_staging():
    clear_log()
    slots_dir = os.path.join(WORK, "proj")
    picks = {}
    # A drop-in in the wrong wrapper, and three that really do differ.
    for name, kw in (("Sullivan_Sullivan_Sub_26", {}),
                     ("Sullivan_Sullivan_Sub_27",
                      dict(width=640, height=480)),
                     ("Shea_Shea_Sub_17", dict(fps=25)),
                     ("Shea_Shea_Sub_23", dict(width=1360, height=768))):
        render(os.path.join(slots_dir, "video", name + ".mov"))
        picks["video/" + name + ".mov"] = render(
            os.path.join(WORK, "picks", name + ".mp4"), **kw)
    slots = {s.rel_path: s for s in scan_video_slots(
        slots_dir, roots=[os.path.join(slots_dir, "video")], exts=(".mov",))}
    win.append_log("Applying 4 video replacement(s) to the assets folder...",
                   "info")
    stage_replacements(slots, picks, log_cb=win.append_log)


@step(900)
def s_staging_snap():
    snap("%s_video_staging_log.png" % WHEN)


# ---- shot 3: the sound encoding header --------------------------------
class _DeadPool:
    """A pool that never boots, so the real function logs its header and
    then bails the way it does when the parallel path is unavailable."""

    def __init__(self, *a, **kw):
        pass

    def apply_async(self, *a, **kw):
        raise RuntimeError("no workers in the shot rig")

    def terminate(self):
        pass

    def join(self):
        pass


class _Ctx:
    Pool = _DeadPool


@step(1200)
def s_audio():
    import multiprocessing as mp
    clear_log()
    win.append_log("Rebuilding 20 replaced sound(s) for the card...", "info")
    real = mp.get_context
    mp.get_context = lambda *a, **kw: _Ctx()
    try:
        engine._encode_cat0_parallel(
            "", "", {}, [(i, "") for i in range(20)], 8, None,
            win.append_log, None, lambda: False)
    except Exception:
        pass
    finally:
        mp.get_context = real
    for idx in (417, 848, 669, 370, 667):
        win.append_log("Re-encoded idx %d." % idx, "info")


@step(900)
def s_audio_snap():
    snap("%s_audio_encode_log.png" % WHEN)


@step(600)
def s_done():
    if os.path.exists(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
    shutil.rmtree(WORK, ignore_errors=True)
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
    root.after(delay, lambda: run(i + 1))


root.after(400, lambda: run(0))
root.mainloop()
