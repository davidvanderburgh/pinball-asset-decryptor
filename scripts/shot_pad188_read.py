"""PAD-188 round 2: the Multi-boot tab after the read that follows a restore.

    python scripts/shot_pad188_read.py OUTDIR [--suffix before|after]

Writes ``<suffix>_restored_list.png``: the tab as it stands once the app has
restarted, the form has come back and opening the tab has read the card the
form names.

THE REPORT.  BEN, Discord @ben01434, after the first fix shipped: "I updated
and went to the multiboot screen.  The random group I had is gone."  Both his
screenshots are this tab mid-load - the card's own singles back, the random
card missing, and the loader's own "Loaded <card>: N images" line underneath.
The saved form was fine; ``on_shown``'s read replaced it with the card's image
list, because the card was never rebuilt with the random card on it.

WHAT THE SHOT RUNS, in both builds:

  1. a card is loaded (``load_inspect``, the loader's public seam - its
     report below is made up and no tool runs, the way
     scripts/shot_multiboot_tab.py does it);
  2. a random card is added over its games - the edit he made;
  3. the session is saved the way a quit saves it (``_save_session_state``);
  4. the tab is cleared and the saved form restored, which is a restart;
  5. the tab is opened, so ``on_shown`` reads the card the form names.

The BEFORE build is reproduced by stubbing ``_carry_restored_edits`` to 0:
that step did not exist, and the read it follows replaced every field.
Nothing else differs between the two shots.

Nothing here touches the real settings.json - ``app.SETTINGS_FILE`` is pointed
at a copy in a temp dir before the App is built.  No tool runs:
PAD_MULTIBOOT_AUTO=0 and PAD_MULTIBOOT_PLAN=0 keep the preview render and the
size check off, and the load is stubbed at ``load_card``.

Capture mechanics are scripts/shot_pad188.py's (PrintWindow, DPI-unaware).
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARGS = list(sys.argv[1:])
SUFFIX = "after"
if "--suffix" in ARGS:
    i = ARGS.index("--suffix")
    SUFFIX = ARGS[i + 1]
    del ARGS[i:i + 2]
if not ARGS:
    sys.exit(__doc__)
OUTDIR = os.path.abspath(ARGS[0])
os.makedirs(OUTDIR, exist_ok=True)

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: Tall enough that the status line under the tab is in frame: it is where
#: the loader says what it did, and in this pair that sentence is the point.
SHOT_W, SHOT_H = 1024, 860

#: The games on the card, out of the vendor library so the rows are real
#: files and the load has nothing to warn about.
LIB = r"D:\Pinball\images\Stern\spike2"
GAMES = [
    ("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
     "GODZILLA LE", "Release", "1.16.0"),
    ("jaws_le-1_02_0.Release.16G.sdcard.raw",
     "JAWS LE", "Release", "1.02.0"),
    ("venom_le-1_07_0.Release.8G.sdcard.raw",
     "VENOM LE", "Release", "1.07.0"),
]
#: ...and the row he adds over them, which is the one that went missing.
RANDOM_TITLE = "SURPRISE ME"


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


sys.path.insert(0, REPO)
log("REPO = %s" % REPO)

from PIL import Image  # noqa: E402

import pinball_decryptor.app as app_mod  # noqa: E402
from pinball_decryptor.core import session_log  # noqa: E402
from pinball_decryptor.gui import multiboot_tab as mb  # noqa: E402

SANDBOX = tempfile.mkdtemp(prefix="pad188r_")
session_log.LOG_DIR_OVERRIDE = os.path.join(SANDBOX, "log")
SETTINGS = os.path.join(SANDBOX, "settings.json")
REAL_SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                             "settings.json")
if os.path.isfile(REAL_SETTINGS):
    shutil.copy2(REAL_SETTINGS, SETTINGS)
    log("settings sandboxed: %s -> %s" % (REAL_SETTINGS, SETTINGS))
app_mod.SETTINGS_FILE = SETTINGS

#: The built card the form names.  Never opened - load_card is stubbed and the
#: report below is taken as if the tool had printed it - but it has to EXIST,
#: because on_shown will not read a path with nothing at it.
CARD = os.path.join(SANDBOX, "stern-multi-3game.16G.sdcard.multi.raw")
open(CARD, "wb").write(bytes(16))
MEDIA = os.path.join(SANDBOX, "media-stern-multi-3game")
os.makedirs(MEDIA, exist_ok=True)


def report():
    """What ``inspect --json`` prints for the card above: three games, each
    with its own picture, no animation and no music."""
    images = []
    for i, (name, title, subtitle, version) in enumerate(GAMES):
        images.append({
            "index": i, "device": "/dev/mmcblk0p%d" % (3 + i * 4),
            "title": title, "subtitle": subtitle, "version": version,
            "art": "art%d.png" % i, "anim": None, "music": None,
            "art_source": "auto", "anim_source": "none",
            "source": mb.wsl(os.path.join(LIB, name)),
            "source_exists": True, "bypass": "bypassed"})
    return {
        "card": CARD, "size": 15494807552, "layout": "parts",
        "partitions": [{"index": 3, "device": "/dev/mmcblk0p3"}],
        "images": images, "groups": [],
        "timeout": 15, "default": 0, "volume": 50, "mixer_volume": None,
        "sound_move": "move.wav", "sound_confirm": "confirm.wav",
        "sound_move_source": "auto", "sound_confirm_source": "auto",
        "heading": "MY MACHINES", "media": [], "warnings": [],
        "has_media_json": True, "has_build_json": True,
        "selector": {"bytes": 41272, "version": None}}


app = app_mod.App()
root = app.root
win = app.window
REAL_DESTROY = root.destroy

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


def rows_now():
    return [(r.title, len(getattr(r, "members", []) or []))
            for r in win._multiboot_panel._rows]


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
    root.geometry("%dx%d+40+20" % (SHOT_W, SHOT_H))
    root.update()


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
def s_last_night():
    """The card is loaded, a random card is added over its games, and the
    session is saved the way a quit saves it."""
    panel = win._multiboot_panel
    panel.new_card()
    panel.load_inspect(report(), CARD, MEDIA)
    panel.add_random_over_existing(title=RANDOM_TITLE)
    root.update()
    app._save_session_state()
    log("last night: rows=%s" % (rows_now(),))


@step(1500)
def s_restart():
    """A new app: the form comes back, and nothing has been read yet."""
    panel = win._multiboot_panel
    panel.new_card()
    doc = json.loads(open(SETTINGS, encoding="utf-8").read())
    panel.restore_state(doc.get("multiboot_state") or {})
    root.update()
    log("restored: rows=%s pending_read=%r"
        % (rows_now(), panel._pending_read))


@step(1500)
def s_open_the_tab():
    """...and opening the tab reads the card the form names."""
    panel = win._multiboot_panel
    panel.load_card = (
        lambda p, **kw: panel.load_inspect(report(), p, MEDIA) or True)
    if SUFFIX == "before":
        # The build before this change: the read replaced every field and
        # nothing was put back on top of it.
        panel._carry_restored_edits = lambda: 0
        log("BEFORE build: the read keeps nothing the form brought back")
    panel.on_shown()
    root.update()
    log("after the read: rows=%s" % (rows_now(),))


@step(1500)
def s_settle():
    panel = win._multiboot_panel
    for _ in range(160):
        root.update()
        time.sleep(0.25)
        if not (panel._busy or panel._pv_busy or panel._probe_busy):
            break
    for _ in range(6):
        root.update()
        time.sleep(0.25)
    log("settled: rows=%s" % (rows_now(),))


@step(800)
def s_snap():
    snap(os.path.join(OUTDIR, "%s_restored_list.png" % SUFFIX))


@step(600)
def s_done():
    REAL_DESTROY()


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


root.after(120000, lambda: REAL_DESTROY())
run_steps()
try:
    app.run()
finally:
    log("sandbox left at %s" % SANDBOX)
