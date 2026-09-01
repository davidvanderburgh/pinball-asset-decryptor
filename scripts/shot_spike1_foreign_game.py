"""Capture the Spike 1 tab reacting to somebody ELSE's game (PAD-98).

    python scripts/shot_spike1_foreign_game.py <out.png>

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for a screen that rig does not cover: the
Spike 1 Emulate tab while a game that is NOT this rig's is running, with
the pop-out DMD and switch windows composited in at the positions they
actually open at.

WHY A FAKE GUEST.  The report is "spike 1 windows showup when running an
spike 2 game": both rigs name their guest process ``game`` (Spike 2's
run_game.sh copies qemu to ``.padqemu/game`` "so comm stays game", and
Spike 1's emu_root.sh says the same thing), so ANY process whose comm is
``game`` used to satisfy this tab's "is my game up?" test.  Booting a real
Spike 2 title for a screenshot takes minutes and a card; a copy of
/bin/sleep named ``game`` reproduces the fault exactly - same comm, no
Spike 1 mounts behind it - and costs a second.  The rig starts one, and
kills it BY PID afterwards (never ``pkill -x game``, which is the very
mistake being fixed).

It refuses to run when a real guest is already up, for the same reason.

The pop-outs are separate Toplevels, so PrintWindow on the app's hwnd
cannot see them: each is captured on its own hwnd and pasted into the app
image at its true screen offset - which is what the fault looks like, two
Spike 1 windows sitting on top of what you were doing.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "spike1_tab.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak98"
#: Fresh per run: the log pane preloads earlier sessions from the rolling log,
#: so a shared dir drags the previous shot's lines into the next one - which on
#: a before/after pair is the before run's log showing up in the after shot.
SCRATCH = os.path.join(os.environ.get("TEMP", "."),
                       "pad98_shotlog_%d" % os.getpid())
CREATE_NO_WINDOW = 0x08000000

#: One geometry, re-asserted inside snap(): the app re-sizes itself to the
#: selected tab on an idle callback that fires at a different moment in each
#: run, and a before/after pair at two sizes is not comparable.
GEOM = None


def log(msg):
    print(msg, flush=True)


def wsl(script):
    out = subprocess.run(["wsl.exe", "-e", "bash", "-c", script],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=CREATE_NO_WINDOW, timeout=60)
    return out.stdout.decode("utf-8", "replace").strip()


# ----------------------------------------------------------------------
# The stand-in guest.  Started before the app so the tab's first status
# poll already sees it.
# ----------------------------------------------------------------------
try:
    live = wsl("pgrep -x game || true")
except Exception as exc:                                       # noqa: BLE001
    sys.exit("WSL did not answer (%s) - this capture needs it." % exc)
if live:
    sys.exit("A guest (comm=game) is already running: %s\nStop it first - "
             "this capture starts its own stand-in and must not photograph "
             "or disturb a real run." % live.replace("\n", " "))

FAKE = wsl("cp -f /bin/sleep /tmp/game && setsid /tmp/game 900 "
           "</dev/null >/dev/null 2>&1 & sleep 0.4; pgrep -x game | head -1")
if not FAKE.isdigit():
    sys.exit("Could not start the stand-in guest: %r" % FAKE)
log("stand-in guest (comm=game) pid %s" % FAKE)

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.makedirs(SCRATCH, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    try:                        # the Spike 1 tab is a Stern capability
        with open(SETTINGS, encoding="utf-8") as fh:
            _s = json.load(fh)
        _s["last_manufacturer"] = "stern"
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(_s, fh, indent=2)
    except Exception:                                          # noqa: BLE001
        log("settings tweak skipped:\n%s" % traceback.format_exc())

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402

session_log.LOG_DIR_OVERRIDE = SCRATCH      # keep David's real log out of it

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
panel = win._spike1_emulate_panel

# The app owns the Windows-side speaker and starts one the moment it believes
# a game is up (_ensure_player).  That is not what is being photographed, and
# a player talking to a relay that does not exist is noise in both shots.
panel._ensure_player = lambda *a, **kw: None

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


def grab(hwnd):
    """PrintWindow one window -> (PIL image, its screen RECT)."""
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
    return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1), wrect


def snap(path):
    if GEOM:                    # let a queued auto-resize run, then override it
        for _ in range(2):
            root.geometry(GEOM)
            root.update_idletasks()
    root.update_idletasks()
    img, wrect = grab(user32.GetAncestor(root.winfo_id(), 2))  # GA_ROOT
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, img.width - border, img.height - border))
    # the pop-outs, at the offset they actually sit at on the desktop
    viewers = panel._viewers
    for attr, name in (("_dmd", "DMD"), ("_sw", "switches")):
        w = getattr(viewers, attr, None) if viewers is not None else None
        if w is None:
            log("pop-out %s: not open" % name)
            continue
        try:
            pimg, prect = grab(user32.GetAncestor(w.winfo_id(), 2))
        except Exception:                                      # noqa: BLE001
            log("pop-out %s: could not be captured" % name)
            continue
        x = prect.left - (wrect.left + border)
        y = prect.top - wrect.top
        img.paste(pimg, (x, y))
        log("pop-out %s: pasted at %d,%d (%dx%d)"
            % (name, x, y, pimg.width, pimg.height))
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
    h = min(1000, root.winfo_screenheight() - 90)
    GEOM = "%dx%d+40+40" % (w, h)
    root.geometry(GEOM)


@step(4000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    win._notebook.select(win._tab_spike1_emulate)


# The tab polls status.sh at 700 ms and then every 2-10 s; give it several
# polls, plus the moment the viewer windows need to paint (a freshly opened
# Toplevel grabbed too early is a blank client area).
@step(14000)
def s_report():
    log("state=%r  procs=%r  game_procs=%r"
        % (panel._vals["state"].cget("text"),
           panel._vals["procs"].cget("text"),
           panel._info.get("game_procs")))


@step(1500)
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
    # BY PID.  `pkill -x game` would reach a real guest, which is the bug.
    try:
        wsl("kill %s 2>/dev/null; rm -f /tmp/game" % FAKE)
        log("stand-in guest %s stopped" % FAKE)
    except Exception:
        log("stand-in cleanup FAILED:\n%s" % traceback.format_exc())
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
