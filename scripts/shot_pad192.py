"""PAD-192: the app's own log listed as one of the card's modified assets.

    python scripts/shot_pad192.py <out_dir> <before|after>

One shot, ``<before|after>_write_preview.png``: the Write tab's Modified
Files Preview for a JJP project folder.

``core.session_log`` mirrors every log line into ``<project>/logs/project.log``
while the app is working that project.  The preview's walk pruned a
hand-written ``("build", ".hydrate")`` — a subset of
``checksums.NON_ASSET_DIRS`` that had gone stale — so ``logs/project.log``
listed as a modified asset the user was expected to act on.  It is the app's
own file, it changes every second the app is open, and the JJP Write then
failed it with ``[FAIL] logs/project.log (not found in fl.dat)``: a red
[ERROR] and an inflated FAILED count on every single build (a Sonic owner's
log reads "557/562 files replaced and verified (5 FAILED)" where only four
were his clips).

NOTHING REAL IS TOUCHED: the project is a temp folder of small files with a
baseline this script writes, the ISO paths are 1 MB of zeroes, settings.json
is backed up and restored, and the session log is sandboxed to a temp dir.
"""
import ctypes
import hashlib
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
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad192bak"
GEOM = ["1100x860+30+20"]


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

# ----------------------------------------------------------------------
# A JJP project folder shaped like the reporter's Sonic extract: the two
# top-level asset trees the card really has (graphics/, sound/) and the
# logs/ folder the APP puts there.
# ----------------------------------------------------------------------
SCRATCH = tempfile.mkdtemp(prefix="pad192_")
PROJECT = os.path.join(SCRATCH, "sonichedgehogcode")

BASELINED = [
    "graphics/Attract Mode/Game_Logo_Sonic.webm",
    "graphics/Levels/Level_2_RooftopRun/TOTAL/RTR_RANK_C.webm",
    "graphics/Levels/Level_6_SpeedHighway/TOTALS/SPH_RANK_S.webm",
    "sound/vs/Levels/Sky Sanctuary/SSZ_CP5_AVG.wav",
    "sound/fanfare/Extra Ball/Fanfare_ExtraBall.wav",
    # The app's own log.  An extract run baselines whatever is in the folder,
    # and by then the app has already been mirroring into logs/.
    "logs/project.log",
]
# The ones the user actually replaced — the rows the preview is FOR.
EDITED = {
    "graphics/Levels/Level_2_RooftopRun/TOTAL/RTR_RANK_C.webm",
    "graphics/Levels/Level_6_SpeedHighway/TOTALS/SPH_RANK_S.webm",
    "sound/vs/Levels/Sky Sanctuary/SSZ_CP5_AVG.wav",
}

lines = []
for rel in BASELINED:
    path = os.path.join(PROJECT, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"stock asset bytes\n")
    lines.append("%s  ./%s" % (hashlib.md5(b"stock asset bytes\n").hexdigest(),
                               rel))
with open(os.path.join(PROJECT, ".checksums.md5"), "w",
          encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")

for rel in EDITED:
    with open(os.path.join(PROJECT, *rel.split("/")), "wb") as fh:
        fh.write(b"the user's replacement, a different size entirely\n")
# ...and the app appending to its own log, which is what makes it "modified".
with open(os.path.join(PROJECT, "logs", "project.log"), "a",
          encoding="utf-8") as fh:
    fh.write("[2026-09-21 15:23:31] Write change scan finished in 3.9 s.\n")

ISO = os.path.join(SCRATCH, "Sonic-v00.930.iso")
with open(ISO, "wb") as fh:
    fh.write(b"\x00" * (1 << 20))

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "jjp"
jjp = settings.setdefault("manufacturers", {}).setdefault("jjp", {})
jjp.update(extract_input=ISO, write_original=ISO, extract_output=PROJECT,
           write_assets=PROJECT, write_output=SCRATCH)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad192_log_")

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

# A release published by another session mid-run would put an update banner
# in one shot of the pair and move every row under it.  Stub the METHOD, not
# updater.check_for_update: the startup check reports whatever it catches,
# so any stand-in with the wrong shape just trades the banner for a red
# "Internal error in ValueError" line in the log panel of both shots.
App._check_for_update = lambda self: None

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
    for _ in range(2):              # let a queued auto-resize run, then win
        root.geometry(GEOM[0])
        root.update()
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
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(600)
def s_write_tab():
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    GEOM[0] = "%dx%d+20+10" % (min(1100, sw - 60), min(900, sh - 70))
    log("screen %dx%d -> %s; manufacturer %s"
        % (sw, sh, GEOM[0], getattr(app._current_mfr, "key", None)))
    root.geometry(GEOM[0])
    win._notebook.select(win._tab_write)


# The prereq check and the startup "write destination changed" scan settle
# first; then ask for a fresh one against the folder built above.
@step(9000)
def s_rescan():
    win.write_assets_var.set(PROJECT)
    win._scan_write_preview()


@step(6000)
def s_snap():
    tree = getattr(win, "_write_preview_tree", None)
    if tree is not None:
        rows = [tree.item(i, "values") for i in tree.get_children("")]
        log("preview rows: %r" % (rows,))
    snap("write_preview")


def run(i=0):
    if i >= len(STEPS):
        root.after(200, finish)
        return
    delay, fn = STEPS[i]

    def go():
        try:
            fn()
        except Exception:
            log("!! step %s failed:\n%s" % (fn.__name__, traceback.format_exc()))
        run(i + 1)

    root.after(delay, go)


def finish():
    try:
        root.destroy()
    except Exception:
        pass


def cleanup():
    if os.path.exists(SETTINGS_BAK):
        shutil.move(SETTINGS_BAK, SETTINGS)
        log("settings restored")
    shutil.rmtree(SCRATCH, ignore_errors=True)


try:
    run()
    root.mainloop()
finally:
    cleanup()
