"""Capture the Write Complete dialog in the states a bad card comes out in.

    python scripts/shot_write_complete.py <out_dir> <before|after> [scenario]

A companion to ``take_screenshots.py`` for one screen that rig doesn't reach:
the modal the Write pops when it finishes.  Two scenarios:

``validator`` (default)
    A firmware that carries Stern's SD-card validator but whose validator
    routine the Write could not locate -- the card then shows GAME VALIDATION
    ERROR on the machine.  Read from the REAL game binary of a real card (Jaws
    LE 1.01.0 is the shipped title where the locator comes up empty).

``blipfree``
    A blip-free build whose rebuilt firmware never reached the card.  Both
    modes here are the values two REAL James Bond LE 1.06.0 writes actually
    returned -- before the grow-source fix, and after it.

Either way the summary is built by the SAME pipeline helpers the real Write
uses, so the shot is the dialog a user actually gets, not mocked-up text.

Capture notes follow take_screenshots.py: DPI-unaware process, PrintWindow
(PW_RENDERFULLCONTENT) rather than a screen grab.  The dialog runs its own
nested event loop, so the capture is armed with root.after() before it opens.
"""
import ctypes
import glob
import os
import sys
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

if not (3 <= len(sys.argv) <= 4) or sys.argv[2] not in ("before", "after"):
    sys.exit(__doc__)
OUT_DIR, WHEN = sys.argv[1], sys.argv[2]
SCENARIO = sys.argv[3] if len(sys.argv) == 4 else "validator"
if SCENARIO not in ("validator", "blipfree"):
    sys.exit(__doc__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = (r"C:\Users\david\Documents\development\pinball-asset-decryptor"
       r"\images\Stern\spike2")

os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

from PIL import Image  # noqa: E402

from pinball_decryptor.plugins.stern import pipeline as pl  # noqa: E402
from pinball_decryptor.plugins.stern import valpatch  # noqa: E402
from pinball_decryptor.plugins.stern.engine import _locate  # noqa: E402
from pinball_decryptor.plugins.stern.formats import linux_partitions  # noqa: E402

if SCENARIO == "validator":
    # --- real validator status of a real card --------------------------------
    cards = glob.glob(os.path.join(LIB, "jaws_le-*.raw"))
    if not cards:
        sys.exit("Need a Jaws LE card in %s to capture this state." % LIB)
    card = cards[0]
    print("reading game binary from %s" % os.path.basename(card), flush=True)
    with open(card, "rb") as f:
        reader, fw_node, _img = _locate(f, linux_partitions(card))
        elf = bytes(reader.read_file_bytes(fw_node))
    if hasattr(valpatch, "bypass_overlay"):
        try:
            _ov, vmode = valpatch.bypass_overlay(elf)
        except (TypeError, ValueError):
            vmode = None
        if not isinstance(vmode, tuple):      # pre-fix: no mode reported at all
            vmode = None
    else:
        vmode = None
    print("validator located: %s   reported mode: %r"
          % (valpatch.find_validation_exec(elf) is not None, vmode), flush=True)
    amode = ("blip-free", "")
    counts = (1, 0, 2, 0)          # the reporter's card: one sound + two images
    out_path = r"C:\Users\david\Desktop\jaws_modded.raw"
else:
    # --- what two real James Bond LE 1.06.0 writes actually returned ---------
    vmode = ("bypassed", "")
    counts = (1, 0, 0, 0)
    out_path = r"C:\Users\david\Desktop\james_bond_modded.raw"
    amode = (("blip-free", "") if WHEN == "after" else
             ("standard",
              "the rebuilt blip-free firmware could not be copied onto the "
              "card (see the build log; this image will fail SD validation "
              "until rebuilt)"))
    print("scenario=blipfree %s: audio_mode=%r" % (WHEN, amode), flush=True)

# --- the summary the pipeline would hand the dialog -------------------------
summary = ("Wrote %s to %s%s"
           % (pl._write_summary(counts), out_path,
              pl._audio_mode_note(amode)))
if hasattr(pl, "_valpatch_note"):
    summary += pl._valpatch_note(vmode)
print("--- dialog text ---\n%s\n-------------------" % summary, flush=True)

# --- show the real dialog and capture it ------------------------------------
from pinball_decryptor.app import App  # noqa: E402
from tkinter import messagebox  # noqa: E402

app = App()
root = app.root
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


def find_dialog(title):
    """HWND of this process's top-level window titled *title*."""
    found = []
    pid = wintypes.DWORD()
    me = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != me or not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value == title:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def snap_hwnd(hwnd, name):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)      # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h       # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print("snapped %s (%dx%d)" % (path, img.width, img.height), flush=True)


def capture_then_close():
    hwnd = find_dialog("Write Complete")
    if hwnd is None:
        print("!! dialog window not found", flush=True)
    else:
        name = ("%s_write_complete.png" % WHEN if SCENARIO == "validator"
                else "%s_blipfree_write_complete.png" % WHEN)
        snap_hwnd(hwnd, name)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
    root.after(600, root.destroy)


root.geometry("1000x700+40+40")
root.update()
root.after(2500, capture_then_close)
root.after(1500, lambda: messagebox.showinfo("Write Complete", summary))
root.mainloop()
