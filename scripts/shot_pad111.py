"""PAD-111 proof shot: what the log pane says when a game-program text edit is
longer than the original and THIS WRITE cannot place longer text.

The tester retitled Godzilla's kaiju (EBIRAH -> BIOLLANTE, MEGALON ->
SPACEGODZILLA) and every long line came back "the game reads this line in a
way the tool can't follow ... Use a shorter replacement" -- which is not what
happened: every one of those strings is growable on his card, the WRITE was
the thing that could not grow the game program.  The shot pushes his own edits
through the real :func:`progtext.plan_writes` against the real stock Godzilla
1.16 ELF, with the growth gate refusing exactly as it refused for him
(:func:`engine._text_grow_gate` on a direct-SD destination supplies the
reason), so the pane holds the production wording and nothing else.

    python scripts/shot_pad111.py <out_dir> <before|after>

The ELF is read once from the vendor card image and cached in the temp dir, so
the second run is instant.  Capture mechanics (PrintWindow, DPI-unaware,
settings backed up) follow scripts/take_screenshots.py -- see its header for
why they are what they are.
"""
import ctypes
import inspect
import os
import shutil
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
SETTINGS_BAK = SETTINGS + ".pad111bak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.plugins.stern import engine, progtext  # noqa: E402

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
# Fixture: the real game ELF off the stock Godzilla 1.16 card, and the
# tester's own renames.
# ----------------------------------------------------------------------
CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CARD_DIRS = (os.path.join(REPO, "images", "Stern", "spike2"),
             os.path.join("D:", os.sep, "Pinball", "images", "Stern", "spike2"))
ELF_CACHE = os.path.join(tempfile.gettempdir(), "pad111_godzilla_116.elf")

EDITS = {
    "GODZILLA VS EBIRAH": "GODZILLA VS BIOLLANTE",
    "MEGALON FINAL BLOW!": "SPACEGODZILLA FINAL BLOW!",
    "MEGALON 5X AWARD!": "SPACEGODZILLA 5X AWARD!",
    "MEGALON WILL EMERGE SOON...": "SPACEGODZILLA WILL EMERGE SOON...",
}


def game_elf():
    """The stock 1.16 game program, cached after the first card read."""
    if os.path.exists(ELF_CACHE):
        with open(ELF_CACHE, "rb") as fh:
            return fh.read()
    card = next((os.path.join(d, CARD) for d in CARD_DIRS
                 if os.path.isfile(os.path.join(d, CARD))), None)
    if card is None:
        sys.exit("needs the stock Godzilla 1.16 card image (%s)" % CARD)
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.info import (_game_elf_bytes,
                                                      _walk_partition)
    with CardImage(card) as ci:
        reader = found = None
        for p in sorted((p for p in ci.partitions() if p.browsable),
                        key=lambda p: p.size, reverse=True):
            r = ci.reader(p.index)
            f = _walk_partition(r)
            if reader is None:
                reader, found = r, f
            if f["sidx_node"] is not None:
                reader, found = r, f
                break
        raw = _game_elf_bytes(reader, found)
    with open(ELF_CACHE, "wb") as fh:
        fh.write(raw)
    return raw


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


@step(1500)
def s_write():
    import tkinter as tk
    clear_log()
    raw = game_elf()
    # The gate the write really asked: this destination cannot grow the game
    # program, so plan_writes is given no extension segment -- his case.
    _ok, why = engine._text_grow_gate(dest_is_device=True)
    win.append_log("Applying display-text edits to the card...", "info")
    win.append_log(
        "Program text: %d edit(s) are longer than the original and can't be "
        "placed in new space for this write (%s); they are skipped — "
        "same-length edits still land in place." % (len(EDITS), why),
        "warning")
    kw = {}
    if "no_grow_why" in inspect.signature(progtext.plan_writes).parameters:
        kw["no_grow_why"] = why
    progtext.plan_writes(raw, dict(EDITS), win.append_log, **kw)
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)


@step(1200)
def s_snap():
    snap("%s_text_write_log.png" % WHEN)


@step(600)
def s_done():
    if os.path.exists(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
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
