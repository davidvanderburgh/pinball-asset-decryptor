"""PAD-122 proof shots: what an Extract of a MULTI-BOOT card tells the user.

A multi-boot card carries several complete games and a boot menu; this app
reads and writes exactly the first one.  Nothing said so, so a tester spent an
afternoon modding a multi-boot card before working that out.  Two shots, both
the real code path over a real (small) multi-boot card image:

  <when>_extract_warning.png  the confirm the Extract button now raises first,
                              composited over the window it belongs to
  <when>_extract_log.png      the run log afterwards, with the [multi-boot]
                              lines naming every game and the one in play

    python scripts/shot_pad122.py <out_dir> <before|after> [card.raw]

The card is built by ``c:\\tmp\\pad122\\build_card.py`` under WSL (mke2fs -d
into a real MBR/EBR layout — the extras sit in logical partitions exactly as
``mkmulticard.py --layout parts`` puts them).  Audio and Text are unticked for
the run so the shot is a complete, honest extract of that card rather than a
firmware emulation of a fixture ELF.

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, session log
sandboxed) follow scripts/take_screenshots.py and scripts/shot_pad118.py; the
confirm is a NATIVE message box, photographed from a helper thread that finds
it by pid + title, then answered YES so the run continues into the second
shot.  The BEFORE tree has no such dialog, so its first shot is the same
window at the same moment — a run that started with nothing said.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
CARD = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else \
    r"C:\tmp\pad122\godzilla_multi-1_16_0.Release.16G.sdcard.raw"
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad122bak"
DIALOG_TITLE = "Multi-boot card"

if not os.path.isfile(CARD):
    sys.exit("No multi-boot card at %s — build it first:\n"
             "  wsl python3 /mnt/c/tmp/pad122/build_card.py "
             "/mnt/c/tmp/pad122/<name>.raw" % CARD)

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

WORK = tempfile.mkdtemp(prefix="pad122_shot_")
SCRATCH = os.path.join(WORK, "godzilla multi")
os.makedirs(SCRATCH, exist_ok=True)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            _cfg = json.load(f)
        _st = (_cfg.setdefault("manufacturers", {})).setdefault("stern", {})
        _st["extract_input"] = CARD
        _st["extract_output"] = SCRATCH
        _st["write_assets"] = SCRATCH
        _st["write_upd"] = CARD
        _cfg["last_manufacturer"] = "stern"
        _cfg.pop("column_widths", None)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(_cfg, f, indent=2)
    except Exception:
        traceback.print_exc()

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(WORK, "logs")

from pinball_decryptor import app as app_mod  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402


class _Quiet:
    """Every modal except the one under test — a completion/error popup would
    stall the after() chain with nothing to show."""
    @staticmethod
    def showinfo(*a, **k):
        print("showinfo suppressed: %r" % (a,), flush=True)

    showwarning = showerror = showinfo

    @staticmethod
    def askyesno(*a, **k):
        return True

    def __getattr__(self, name):
        return self.showinfo


_real_mb = app_mod.messagebox


class _MB(_Quiet):
    """askyesno stays REAL (that is the shot); the rest go quiet."""
    askyesno = staticmethod(_real_mb.askyesno)


app_mod.messagebox = _MB()

app = App()
root = app.root
win = app.window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
GEOM = None
STATE = {}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def _shot(hwnd, crop_border=True):
    """``(PIL image, window rect, cropped border)`` for *hwnd*."""
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
    border = 0
    if crop_border:
        border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
        img = img.crop((border, 0, w - border, h - border))
    return img, wrect, border


def window_shot():
    # Re-assert the geometry: the app re-sizes itself to the active tab on an
    # idle callback that fires at a different moment in each run, and the pair
    # has to be pixel-comparable (PAD-60).
    for _ in range(2):
        if GEOM:
            root.geometry(GEOM)
        root.update_idletasks()
    return _shot(user32.GetAncestor(root.winfo_id(), 2))   # GA_ROOT


def save(img, name):
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def snap(name):
    save(window_shot()[0], name)


def tail_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)


def _centre_over_app(hwnd):
    """Move the confirm to the middle of the app window.

    Windows centres a message box on the SCREEN, and the app window is not
    centred there — so the modal hung off the right edge and the composite
    below cropped half of it.  Moving it is only cosmetic: this is the shot's
    frame, not the app's behaviour.
    """
    app_rect = STATE.get("app_rect")
    if app_rect is None:
        return
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    x = app_rect.left + ((app_rect.right - app_rect.left) - w) // 2
    y = app_rect.top + ((app_rect.bottom - app_rect.top) - h) // 2
    user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)  # NOSIZE|NOZORDER


def dialog_watcher():
    """Photograph the native confirm, keep it, then answer YES."""
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)
    found = []

    def _cb(hwnd, _lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != os.getpid() or not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value == DIALOG_TITLE:
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + 12
    while time.time() < deadline:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        if found:
            time.sleep(0.5)
            _centre_over_app(found[0])
            time.sleep(0.5)                       # let it paint where it moved
            try:
                STATE["dialog"] = _shot(found[0], crop_border=False)
            except Exception:
                traceback.print_exc()
            user32.PostMessageW(found[0], 0x0111, 6, 0)   # WM_COMMAND, IDYES
            return
        time.sleep(0.25)
    print("no %r dialog (expected in the BEFORE run)" % DIALOG_TITLE,
          flush=True)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(900)
def s_enter():
    global GEOM
    root.maxsize(9999, 9999)
    w = min(1210, root.winfo_screenwidth() - 60)
    h = min(950, root.winfo_screenheight() - 60)
    GEOM = "%dx%d+30+20" % (w, h)
    root.geometry(GEOM)
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)
    win._notebook.select(win._tab_extract)
    win.extract_input_var.set(CARD)
    win.extract_output_var.set(SCRATCH)
    # Audio + Text off: this fixture's firmware is a stub, and the point of
    # the shot is what the app SAYS about the card, not a decode.
    for key, on in (("audio", False), ("video", True),
                    ("images", True), ("text", False)):
        var = (getattr(win, "_extract_category_vars", {}) or {}).get(key)
        if var is not None:
            var.set(on)
    root.update_idletasks()


@step(1200)
def s_extract():
    """Press Extract.  In the AFTER tree this blocks on the confirm until the
    watcher photographs it and answers Yes.

    Nothing after this is on the fixed schedule: a Tk modal pumps the event
    loop, so an ``after`` chain queued behind it fires WHILE the dialog is up
    and the log shot lands on a run that has not started.  Each remaining step
    is armed by the one before it instead.
    """
    rect = wintypes.RECT()
    user32.GetWindowRect(user32.GetAncestor(root.winfo_id(), 2),
                         ctypes.byref(rect))
    STATE["app_rect"] = rect
    t = threading.Thread(target=dialog_watcher, daemon=True)
    t.start()
    app._start_extract()
    t.join(15)
    shot, wrect, border = window_shot()
    dlg = STATE.get("dialog")
    if dlg is not None:
        # Paste the modal back where it stood, so the pair is the same window
        # with and without it (the tooltip trick from PAD-13).
        dimg, drect, _b = dlg
        shot.paste(dimg, (drect.left - (wrect.left + border),
                          drect.top - wrect.top))
    save(shot, "%s_extract_warning.png" % WHEN)
    root.after(400, s_wait)


def s_wait(n=0):
    """Let the run finish before the log shot (it is a 128 MB card)."""
    if getattr(win, "_running", False) and n < 200:
        root.after(300, lambda: s_wait(n + 1))
        return
    tail_log()
    root.after(1200, s_log)


def s_log():
    tail_log()
    snap("%s_extract_log.png" % WHEN)
    root.after(600, s_info)


def s_info():
    """Third shot: the Info window's own report on the same card.

    Its probe runs on a worker with a "Reading image…" overlay, so the grab
    waits rather than photographing the spinner.
    """
    win._open_image_info(win.extract_input_var)
    root.after(4000, s_info_snap)


def s_info_snap():
    import tkinter as tk
    dlg = next((w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel) and w.title() == "Image Info"),
               None)
    if dlg is None:
        print("no Image Info window", flush=True)
    else:
        root.update_idletasks()
        img, _r, _b = _shot(user32.GetAncestor(dlg.winfo_id(), 2),
                            crop_border=False)
        save(img, "%s_image_info.png" % WHEN)
    root.after(600, s_done)


def s_done():
    try:
        if os.path.exists(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
        shutil.rmtree(WORK, ignore_errors=True)
    finally:
        root.destroy()


def _schedule():
    t = 0
    for delay, fn in STEPS:
        t += delay

        def run(fn=fn):
            try:
                fn()
            except Exception:
                traceback.print_exc()
        root.after(t, run)


_schedule()
root.mainloop()
print("done", flush=True)
