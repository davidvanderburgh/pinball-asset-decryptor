"""Capture the Emulate tab's virtual-playfield notice for PAD-99.

    python scripts/shot_emulate_playfield.py <out.png>

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one screen that rig does not
cover, and a near-twin of shot_emulate_sound.py - which photographs the
same label for the SOUND half of the notice.

WHY THE FACTS ARE SYNTHETIC.  The notice is built from what
setupcheck.sh finds in WSL, and this machine's WSL answers with a
Windows Python that has Pillow - so a live capture shows an empty tab
in both shots and proves nothing.  _setup_apply is fed the machine that
reported the bug instead: every package installed, the emulator running
with sound and switches, and one window that could never open on it.
"""
import ctypes
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "emulate.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak99"

#: dragonrr's PC, as setupcheck.sh would report it.  Every package present,
#: the handler registered, interop on, a Windows Python for the sound - he
#: wrote in with a screenshot of a running godzilla_le, video playing, and no
#: playfield window anywhere on the desktop.
#:
#: `winpf` and `pfpy` are the facts this ticket adds, and they are about the
#: OTHER Windows Python: the playfield window is drawn with tkinter AND
#: Pillow, his python.org 3.13 had the first and not the second, and it was
#: the one the run picked, because it was the one PATH answered with.  A build
#: from before this ignores both keys - which is exactly the silence the
#: BEFORE shot is of.
THEIR_PY = r"C:\Users\dragonrr\AppData\Local\Programs\Python\Python313"
FACTS = {"qemu": "1", "armgcc": "1", "nativecc": "1", "debugfs": "1",
         "fuse": "1", "binfmt": "1", "iswsl": "1", "wslconf": "1",
         "user": "dragonrr", "interop": "1", "display": "ok",
         "winaudio": "1", "winpy": THEIR_PY + r"\python.exe",
         "winpf": "0", "pfpy": THEIR_PY + r"\pythonw.exe",
         "padpy": r"C:\Program Files\Pinball Asset Decryptor\python"
                  r"\python.exe",
         "distro": "ubuntu 24.04 noble",
         "components": "main multiverse restricted universe",
         "indexed": "1", "nocand": "", "universe": "1", "xrel": ""}


def log(msg):
    print(msg, flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

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


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    # Same lever, same reason, as shot_emulate_setup.py: the notice is the
    # last widget packed into the tab frame, and a frame short of its
    # requested height hands the last slave one pixel and never maps it.
    w = min(1100, root.winfo_screenwidth() - 80)
    h = min(1040, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))


@step(6000)
def s_emulate_tab():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    # SPIKE 2 EXPLICITLY.  The app reopens the last project, and if that was a
    # Spike 1 one the header comes up on the SPIKE 1 era - which photographs
    # the right panel under the wrong badge.  This notice is about the Spike 2
    # rig's playfield window, so say so.
    if hasattr(win, "_on_era_badge_click"):
        win._on_era_badge_click("spike2")


@step(3000)
def s_select():
    win._notebook.select(win._tab_emulate)


@step(2500)
def s_facts():
    """Hand the panel the reporter's machine.

    The panel's own probe runs against THIS PC and would overwrite it, so the
    real one is stubbed out first - the widget path is the same either way,
    _setup_apply is what draws the notice.
    """
    panel = win._emulate_panel
    panel._setup_check = lambda *a, **kw: None
    panel._setup_drain = lambda *a, **kw: None
    panel._setup_apply(dict(FACTS))
    # ROOM FOR IT, MEASURED RATHER THAN GUESSED.  shot_emulate_setup.py's
    # fixed 520 is not enough for this tab as it stands (the save-state table
    # and the status grid grew), and a notebook page short of its requested
    # height hands the LAST packed slave one pixel and never maps it - which
    # is a capture that succeeds with the notice missing.  Ask the page what
    # it needs, with the notice already packed into it.
    root.update_idletasks()
    win._notebook.configure(height=win._tab_emulate.winfo_reqheight() + 30)
    root.update_idletasks()
    msg = panel._setup_msg
    log("notice mapped=%s h=%s text=%r"
        % (msg.winfo_ismapped(), msg.winfo_height(), msg.cget("text")))


@step(2000)
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
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
