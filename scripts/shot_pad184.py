"""PAD-184: the image's Confirm sound box, and what the list says it plays.

    python scripts/shot_pad184.py OUTDIR [--suffix before|after]

Writes two pictures into OUTDIR:

  ``<suffix>_images_table.png``  the tab's images table, whose Confirm
                                 column names the sound each row plays -
                                 including the row whose box was typed
                                 'none', which the card answers with the
                                 menu's sound.
  ``<suffix>_edit_image.png``    Edit image… on the first row, whose
                                 Confirm sound is the menu's: the box says
                                 'menu' and the report is that it never
                                 says WHICH sound that is, though ▶ beside
                                 it plays the right one.

A variant of scripts/shot_pad137.py - same App, same PrintWindow, same
DPI-unaware capture, same settings backup.  What it adds is a menu-wide
confirm sound that is a real WAV FILE (the case where 'menu' and the
column's '(Kaiju Confirm.wav)' look like two different settings) and a row
carrying its own.

Nothing is built and no tool runs: PAD_MULTIBOOT_AUTO=0 and
PAD_MULTIBOOT_PLAN=0 keep the preview render and the size check off, and no
button in either dialog is pressed.
"""
import ctypes
import os
import shutil
import struct
import sys
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARGS = list(sys.argv[1:])
SUFFIX = "before"
if "--suffix" in ARGS:
    i = ARGS.index("--suffix")
    SUFFIX = ARGS[i + 1]
    del ARGS[i:i + 2]
if not ARGS:
    sys.exit(__doc__)
OUTDIR = os.path.abspath(ARGS[0])
os.makedirs(OUTDIR, exist_ok=True)

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak184"

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: Wide enough for the images table's own width: the Confirm column is the
#: second from the right, and a narrow window is a picture of the titles.
SHOT_W, SHOT_H = 1360, 900

IMG_DIR = os.path.join(
    r"C:\Users\david\Documents\development\pinball-asset-decryptor",
    "images", "Stern", "spike2")

#: Three real Spike 2 cards, and the menu text typed for each.
IMAGES = [
    (os.path.join(IMG_DIR, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"),
     "GODZILLA PRO", "Stock 1.16"),
    (os.path.join(IMG_DIR, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"),
     "GODZILLA LE", "Stock 1.16"),
    (os.path.join(IMG_DIR, "godzilla_le-1_13_0.Release.8G.sdcard.raw"),
     "GODZILLA LE 1.13", "Older code"),
]

#: The WAVs this menu uses: the menu-wide confirm sound, and one image's own.
#: REAL FILES in the temp directory, so the boxes offer them and ▶ could
#: play them - the report is about a sound that is set, not a missing one.
WAV_DIR = os.path.join(os.environ.get("TEMP", r"C:\tmp"), "pad184")
MENU_WAV = os.path.join(WAV_DIR, "Kaiju Confirm.wav")
OWN_WAV = os.path.join(WAV_DIR, "Godzilla Roar.wav")

#: Row 1 has a confirm sound of its own; row 2's box was typed 'none',
#: which this format has no room for - the card plays the menu's sound for
#: it, and the column used to say 'none'.
OWN_ROW, NONE_ROW = 1, 2

#: ...and Edit image… is opened on row 0, which inherits: the row the
#: report is about.
EDIT_ROW = 0


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


def make_wav(path, seconds=0.4, rate=44100):
    """A real, playable 16-bit mono WAV of silence."""
    n = int(rate * seconds)
    data = b"\0\0" * n
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
           struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
           b"data" + struct.pack("<I", len(data)))
    with open(path, "wb") as fh:
        fh.write(hdr + data)


os.makedirs(WAV_DIR, exist_ok=True)
for _w in (MENU_WAV, OWN_WAV):
    if not os.path.isfile(_w):
        make_wav(_w)

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


def _print_window(hwnd, w, h):
    """PrintWindow(PW_RENDERFULLCONTENT) of the whole window, as an image."""
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
    return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)


def snap(path, widget=None):
    """PrintWindow the widget's whole window, with the invisible resize
    border cropped off.  The window is walked across the desktop a tile at
    a time when it overhangs it: Tk paints only what Windows says is
    visible, and the rest comes back black."""
    root.update_idletasks()
    hwnd = user32.GetAncestor((widget or root).winfo_id(), 2)  # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    sw, sh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)

    def offsets(size, span):
        if size <= span:
            return [0]
        return list(range(0, size - span, span)) + [size - span]

    tiles = [(ox, oy) for oy in offsets(h, sh) for ox in offsets(w, sw)]
    if len(tiles) == 1:
        img = _print_window(hwnd, w, h)
    else:
        log("window %dx%d overhangs the %dx%d desktop: %d tiles"
            % (w, h, sw, sh, len(tiles)))
        img = Image.new("RGB", (w, h))
        SWP = 0x0001 | 0x0004 | 0x0010   # NOSIZE | NOZORDER | NOACTIVATE
        for ox, oy in tiles:
            user32.SetWindowPos(hwnd, 0, vx - ox, vy - oy, 0, 0, SWP)
            for _ in range(3):
                root.update()
                time.sleep(0.15)
            tile = _print_window(hwnd, w, h)
            box = (ox, oy, min(w, ox + sw), min(h, oy + sh))
            img.paste(tile.crop(box), box[:2])
        user32.SetWindowPos(hwnd, 0, wrect.left, wrect.top, 0, 0, SWP)
        root.update()
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def set_window(w, h):
    """Size the window, lifting Tk's default maxsize (the screen) first -
    PrintWindow renders the whole window whether or not the screen can show
    it, and without this the geometry is silently capped."""
    root.maxsize(max(w, root.winfo_screenwidth()) + 100,
                 max(h, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (w, h))
    root.update_idletasks()
    root.update()


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    log("screen %dx%d -> window %dx%d"
        % (root.winfo_screenwidth(), root.winfo_screenheight(),
           SHOT_W, SHOT_H))
    set_window(SHOT_W, SHOT_H)


@step(6000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(3000)
def s_select():
    # A newer release on GitHub packs an update banner across the top; it is
    # about this checkout, not the tab.
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    """Three images: one inheriting the menu's confirm sound, one with its
    own, one whose box was typed 'none'."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, _t, _s in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s - the row will show the path only" % path)
        panel.add_image(path)
    # THE ROWS DIRECTLY, not through the editor variables: a select() and
    # the editor load it defers do not both land inside one root.update(),
    # and the second row's title went onto the third.
    for i, (_p, title, sub) in enumerate(IMAGES):
        panel._rows[i].title = title
        panel._rows[i].subtitle = sub
    panel._refresh_tree(select=0)
    root.update()
    # the menu's own confirm sound is a FILE, which is the shape of the
    # report: the column names it and the image box says only 'menu'
    panel._confirm_var.set(MENU_WAV)
    panel._rows[OWN_ROW].confirm = OWN_WAV
    panel._rows[NONE_ROW].confirm = "none"
    panel._refresh_tree(select=EDIT_ROW)
    panel._table.select(EDIT_ROW)
    panel._compact_var.set(False)
    root.update()
    log("rows: %s" % [(r.title, r.confirm) for r in panel._rows])
    log("confirm column: %s"
        % [panel._table.cell(i, "sound") for i in range(len(panel._rows))])


@step(1500)
def s_table():
    snap(os.path.join(OUTDIR, "%s_images_table.png" % SUFFIX))


@step(1200)
def s_edit_image():
    """Edit image… on a row whose Confirm sound is the menu's."""
    panel = win._multiboot_panel
    dlg = panel.edit_image(EDIT_ROW)
    if dlg is None:
        log("could not open Edit image")
        return
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    log("dialog wants %d px of a %d px desktop"
        % (dlg.top.winfo_reqheight(), root.winfo_screenheight()))
    note = getattr(dlg, "_confirm_note", None)
    log("confirm line: %r" % (note.cget("text") if note is not None else None))
    snap(os.path.join(OUTDIR, "%s_edit_image.png" % SUFFIX), dlg.top)
    dlg.cancel()
    root.update()


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
