"""PAD-144: the SD-card write a Multi-boot card is handed to.

    python scripts/shot_pad144.py <out_dir> <before|after>

Three shots, each as ``<before|after>_<screen>.png``:

``flash_dialog``
    The flash dialog as the Multi-boot tab opens it straight after building
    a fresh card (the tester's own sequence).  It carried the Write tab's
    "Build a fresh image" section and build path - a single-game build that
    has nothing to do with the card - and pre-ticked "Only the boot menu",
    a write no SD card can take for a card that was only just made.

``menu_unticked``
    The same dialog for a card that was built earlier, with "Only the boot
    menu" unticked, which is the state the tester's screenshot was in.  The
    note under the tick is what has to say what the tick is FOR.

``start_confirm``
    The first question Start asks in that state.  Before the fix it was
    "Nothing modified" - a check on the Write tab's edits, which a
    Multi-boot card never came from.

NOTHING IS WRITTEN TO ANY DRIVE: the card is a 64 MB scratch file with a
Stern-shaped partition table, the drive list is one made-up card reader at a
device path that does not exist, and the confirmation is answered No by
this script.  The app opens into Stern with a scratch project (settings.json
is backed up and restored) and the session log is sandboxed.
"""
import ctypes
import inspect
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
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
SETTINGS_BAK = SETTINGS + ".pad144bak"
CONFIRM_TITLES = ("Nothing modified", "Erase the SD card and continue?",
                  "Write the boot menu?")


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

scratch = tempfile.mkdtemp(prefix="pad144_")
project = os.path.join(scratch, "Stern v129")
build_dir = os.path.join(project, "build")
multi_dir = os.path.join(scratch, "Releases", "multi")
for d in (project, build_dir, multi_dir):
    os.makedirs(d, exist_ok=True)
open(os.path.join(project, ".checksums.md5"), "w").close()
STOCK = os.path.join(scratch, "beatles-1_27_0.Pepper.8G.sdcard.raw")
CARD = os.path.join(multi_dir, "beatles-1_29_0.Multigame.8G.sdcard.multi.raw")


def _entry(ptype, lba, count):
    return (b"\x00\x00\x00\x00" + bytes([ptype]) + b"\x00\x00\x00"
            + struct.pack("<II", lba, count))


def _card_image(path):
    """p1 FAT, p2 the Linux rootfs (the menu), p3 games, p4 extended."""
    mbr = bytearray(512)
    for i, (t, lba, cnt) in enumerate([(0x0C, 8, 8), (0x83, 16, 16),
                                       (0x83, 32, 16), (0x0F, 64, 64)]):
        mbr[446 + i * 16:446 + (i + 1) * 16] = _entry(t, lba, cnt)
    mbr[510:512] = b"\x55\xaa"
    with open(path, "wb") as f:
        f.write(bytes(mbr))
        f.truncate(64 * 1024 * 1024)


_card_image(STOCK)
_card_image(CARD)

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "stern"
stern = settings.setdefault("manufacturers", {}).setdefault("stern", {})
stern.update(extract_input=STOCK, write_original=STOCK,
             extract_output=project, write_assets=project,
             write_output=build_dir)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad144_log_")

from pinball_decryptor.core.drives import PhysicalDrive  # noqa: E402
from pinball_decryptor.gui import flash_dialog  # noqa: E402

READER = PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE9",
                       model="Generic- USB3.0 CRW   -SD",
                       size_bytes=15_931_539_456, bus_type="USB",
                       mount_label="D:")
DIALOGS = []
_orig_init = flash_dialog.FlashImageDialog.__init__


def _recording_init(self, *a, **kw):
    DIALOGS.append(self)
    _orig_init(self, *a, **kw)


flash_dialog.FlashImageDialog.__init__ = _recording_init
flash_dialog.FlashImageDialog._refresh_drives = (
    lambda self: self._apply_drives(self._enum_id, [READER],
                                    (READER, None, None)))

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
AFTER_CODE = "fresh" in inspect.signature(win._open_flash_dialog).parameters
log("hand-off knows a fresh card: %s" % AFTER_CODE)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def grab(hwnd, name):
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
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def snap_dialog(name):
    dlg = DIALOGS[-1]._dlg
    dlg.update()
    grab(user32.GetAncestor(dlg.winfo_id(), 2), name)  # GA_ROOT


def close_dialog():
    d = DIALOGS[-1]
    try:
        d._dlg.grab_release()
    except tk.TclError:
        pass
    d._dlg.destroy()


def hand_off(fresh):
    """Exactly what the Multi-boot tab calls: its flash_fn, with the card."""
    panel = win._multiboot_panel
    if AFTER_CODE:
        root.after(0, lambda: panel._flash_fn(CARD, fresh=fresh))
    else:
        root.after(0, lambda: panel._flash_fn(CARD))


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
CONFIRMED = threading.Event()


def _find_confirm():
    found = []
    pid = os.getpid()

    def cb(hwnd, _lp):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value in CONFIRM_TITLES:
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else (None, None)


def _answer_the_confirm():
    deadline = time.time() + 20
    while time.time() < deadline:
        hwnd, title = _find_confirm()
        if hwnd:
            time.sleep(0.8)                 # let it paint
            log("first confirm: %r" % title)
            grab(hwnd, "start_confirm")
            user32.PostMessageW(hwnd, 0x0111, 7, 0)     # WM_COMMAND, IDNO
            break
        time.sleep(0.2)
    else:
        log("!! no confirm box appeared")
    CONFIRMED.set()


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_setup():
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+10+10" % (min(1100, sw - 40), sh - 70))
    log("manufacturer: %s" % getattr(app._current_mfr, "key", None))
    # The tester's Write tab: a single-game build set up, nothing edited.
    win.write_upd_var.set(STOCK)
    win.write_assets_var.set(project)
    win.write_output_var.set(build_dir)
    win.write_filename_var.set("beatles-1_27_0.Pepper.8G.sdcard-modified.raw")
    win._has_pending_write_changes = lambda: False
    win._on_flash_image = lambda *a, **k: log("!! would flash %r %r" % (a, k))
    try:
        win._notebook.select(win._tab_multiboot)
    except Exception:                               # noqa: BLE001
        pass


@step(9000)
def s_open_after_build():
    hand_off(fresh=True)


@step(1800)
def s_snap_after_build():
    d = DIALOGS[-1]
    log("build section mapped=%s menu tick=%s state=%s" % (
        d._build_entry.winfo_ismapped(), d._menu_var.get(),
        d._menu_chk.state()))
    snap_dialog("flash_dialog")
    close_dialog()


@step(800)
def s_open_existing():
    hand_off(fresh=False)


@step(1800)
def s_untick_menu():
    d = DIALOGS[-1]
    d._menu_var.set(False)
    d._sync_sections()


@step(800)
def s_snap_unticked():
    snap_dialog("menu_unticked")


@step(300)
def s_start():
    threading.Thread(target=_answer_the_confirm, daemon=True).start()
    # Its own callback, as the Start button is.
    root.after(200, DIALOGS[-1]._do_start)


@step(500)
def s_wait_confirm():
    if not CONFIRMED.is_set():
        STEPS.insert(STEPS.index((500, s_wait_confirm)) + 1,
                     (500, s_wait_confirm))


@step(800)
def s_done():
    try:
        close_dialog()
    except Exception:                               # noqa: BLE001
        pass
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


root.after(120000, root.destroy)    # watchdog
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
    shutil.rmtree(scratch, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)
