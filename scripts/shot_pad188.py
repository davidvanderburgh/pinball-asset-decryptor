"""PAD-188: the Multi-boot image list an in-app update hands back.

    python scripts/shot_pad188.py OUTDIR [--suffix before|after]

Writes ``<suffix>_multiboot_list.png`` into OUTDIR: the Multi-boot tab as the
UPDATED app opens it, after the whole trip BEN described.

The report (BEN, Discord @ben01434): "I add a random image as one of my images
in a multiboot collection.  I then see a notification that there is an update
and I use the built in updater.  When it restarts, the original single images
are still there but the random one is gone."

WHAT THE SHOT ACTUALLY RUNS, in both builds, is the real thing:

  1. three single card images are added and the session is saved the way an
     ordinary quit saves it - that is the state he still had afterwards;
  2. a random card is added over them (``Add random over the images
     above...``),
     which is the row he lost;
  3. the real ``_launch_downloaded_installer`` runs, with the installer stubbed
     to "started" and the emulator shutdown raising instead of returning - the
     installer's /FORCECLOSEAPPLICATIONS ending this process mid-quit, which is
     the race this ticket is about;
  4. whatever reached settings.json is restored into the tab, which is what the
     updated app does on its next launch.

The BEFORE build is reproduced by stubbing ``_save_session_state`` out: that
step did not exist, and the save it replaces sat AFTER the shutdown in step 3,
so it never ran.  Nothing else differs between the two shots.

Nothing here touches the real settings.json - ``app.SETTINGS_FILE`` is pointed
at a copy in a temp dir before the App is built, so the rig reads David's real
look and writes only to the sandbox.  No tool runs: PAD_MULTIBOOT_AUTO=0 and
PAD_MULTIBOOT_PLAN=0 keep the preview render and the size check off.

Capture mechanics are scripts/shot_pad185.py's (PrintWindow, DPI-unaware).
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

#: David's desktop, which is also the size the tab is designed around.
SHOT_W, SHOT_H = 1024, 768

#: His collection, out of the vendor library: three builds that would each get
#: a card of their own in the menu.
LIB = r"D:\Pinball\images\Stern\spike2"
SINGLES = [
    (os.path.join(LIB, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"),
     "GODZILLA LE", "1.16.0"),
    (os.path.join(LIB, "jaws_le-1_02_0.Release.16G.sdcard.raw"),
     "JAWS LE", "1.02.0"),
    (os.path.join(LIB, "venom_le-1_07_0.Release.8G.sdcard.raw"),
     "VENOM LE", "1.07.0"),
]
#: ...and the row he adds last, which is the one that went missing.
RANDOM_TITLE = "SURPRISE ME"
NEW = "9.0.0"


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

SANDBOX = tempfile.mkdtemp(prefix="pad188_")
session_log.LOG_DIR_OVERRIDE = os.path.join(SANDBOX, "log")
SETTINGS = os.path.join(SANDBOX, "settings.json")
REAL_SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                             "settings.json")
if os.path.isfile(REAL_SETTINGS):
    shutil.copy2(REAL_SETTINGS, SETTINGS)
    log("settings sandboxed: %s -> %s" % (REAL_SETTINGS, SETTINGS))
app_mod.SETTINGS_FILE = SETTINGS

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
    panel = win._multiboot_panel
    return [(r.title, len(getattr(r, "members", []) or []))
            for r in panel._rows]


def on_disk():
    """The image list the updated app would read back out of settings.json."""
    try:
        doc = json.loads(open(SETTINGS, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        return "unreadable (%s)" % e
    images = (doc.get("multiboot_state") or {}).get("images") or []
    return [(str(r.get("title") or ""), len(r.get("members") or []))
            for r in images]


class _ForceClosed(BaseException):
    """The installer ending this process mid-quit."""


class _Dialog:
    def close(self):
        pass


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
def s_last_clean_quit():
    """Three single images, saved the way an ordinary quit saves them."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, title, version in SINGLES:
        panel.add_image(path)
        panel._rows[-1].title = title
        panel._rows[-1].version = version
    panel._refresh_tree(select=0)
    root.update()
    app._save_session_state()
    log("after the last clean quit: rows=%s disk=%s" % (rows_now(), on_disk()))


@step(1500)
def s_add_the_random_card():
    """...and the row he adds in the session that then updates."""
    panel = win._multiboot_panel
    panel.add_random_over_existing(title=RANDOM_TITLE)
    panel._refresh_tree(select=len(panel._rows) - 1)
    root.update()
    log("on the tab now: rows=%s disk=%s" % (rows_now(), on_disk()))


@step(1500)
def s_update():
    """The built-in updater, force-closed mid-quit."""
    app_mod.launch_installer_windows = lambda path: True
    app._restart_wsl_for_update = lambda: None
    root.destroy = lambda: None

    def _killed():
        raise _ForceClosed("the installer closed the app")

    win.emulate_shutdown = _killed
    if SUFFIX == "before":
        # The build before this change: no such step, and the save it stands
        # in for came after the shutdown above, so it never ran.
        app._save_session_state = lambda: None
        log("BEFORE build: the state is only written after the shutdown")
    try:
        app._launch_downloaded_installer(
            _Dialog(), os.path.join(SANDBOX, "setup.exe"), NEW)
    except _ForceClosed as e:
        log("force-closed: %s" % e)
    log("what the installer left on disk: %s" % (on_disk(),))


@step(1500)
def s_relaunch():
    """What the updated app puts on the tab when it opens."""
    panel = win._multiboot_panel
    try:
        doc = json.loads(open(SETTINGS, encoding="utf-8").read())
    except (OSError, ValueError):
        doc = {}
    panel.restore_state(doc.get("multiboot_state") or {})
    root.update()
    log("the updated app shows: %s" % (rows_now(),))


@step(1500)
def s_settle():
    """Let the restore's card probe finish before the picture is taken: a
    shot caught mid-probe has a running progress bar and a red Cancel where
    its pair has the green button, and the pair is meant to differ in one
    thing only."""
    panel = win._multiboot_panel
    for _ in range(160):
        root.update()
        time.sleep(0.25)
        if not (panel._busy or panel._pv_busy or panel._probe_busy):
            break
    for _ in range(6):
        root.update()
        time.sleep(0.25)
    log("settled: busy=%r probe=%r rows=%s"
        % (panel._busy, panel._probe_busy, rows_now()))


@step(800)
def s_snap():
    snap(os.path.join(OUTDIR, "%s_multiboot_list.png" % SUFFIX))


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
