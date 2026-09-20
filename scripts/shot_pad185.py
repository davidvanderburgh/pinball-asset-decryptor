"""PAD-185: 'How it picks' on a random card, in both of its states.

    python scripts/shot_pad185.py OUTDIR [--suffix before|after]

Writes two pictures into OUTDIR:

  ``<suffix>_how_it_picks.png``          Edit image… on a random card with
                                         the truly-random rule chosen.
  ``<suffix>_how_it_picks_shuffle.png``  the same dialog with the shuffle
                                         rule chosen.

The report (BEN, Discord @ben01434) is about the shape of that box: three
exclusive radio buttons where the third one, "Never the one it booted
last", is not a third way of drawing at all - it is a rule laid on top of
one of the other two, and on its own it "does not make sense to stand on
its own".  Both shots are of the same box, so the pair shows the third
radio becoming a tick under the two that remain, and shows what the tick
does when a shuffle is the choice.

A variant of scripts/shot_pad137.py - same App, same PrintWindow, same
DPI-unaware capture, same settings backup.  Nothing is built and no tool
runs: PAD_MULTIBOOT_AUTO=0 and PAD_MULTIBOOT_PLAN=0 keep the preview
render and the size check off, and no button in the dialog is pressed.
"""
import ctypes
import os
import shutil
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
SETTINGS_BAK = SETTINGS + ".shotbak185"

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: David's desktop, which is also the size the tab is designed around.
SHOT_W, SHOT_H = 1024, 768

#: The primary, plus the four song-set builds the random card rolls
#: between - the forty-variant jukebox in miniature, which is the card the
#: "How it picks" box exists for.
PRIMARY = (r"C:\temp\Godzilla\godzilla_le-1_16_0.Stock.16G.sdcard.raw",
           "STERN STOCK", "Godzilla LE 1.16.0")
MEMBERS = [
    (r"C:\temp\Godzilla\godzilla_le-1_16_0.Heisei.16G.sdcard.raw", "Heisei"),
    (r"C:\temp\Godzilla\godzilla_le-1_16_0.Showa.16G.sdcard.raw", "Showa"),
    (r"C:\temp\Godzilla\godzilla_le-1_16_0.Millennium.16G.sdcard.raw",
     "Millennium"),
    (r"C:\temp\Godzilla\godzilla_le-1_16_0.MonsterVerse.16G.sdcard.raw",
     "MonsterVerse"),
]
GROUP_ROW = 1           # the random card is the second row


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


sys.path.insert(0, REPO)
log("REPO = %s" % REPO)

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
    a time when it overhangs it (shot_pad137): Tk paints only what Windows
    says is visible, and this dialog is taller than this box's 768-line
    screen, so the foot of it comes back blank otherwise."""
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
    root.maxsize(max(w, root.winfo_screenwidth()) + 100,
                 max(h, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (w, h))
    root.update_idletasks()
    root.update()


def describe(panel):
    """What the 'How it picks' box holds, in words - the log is what proves
    the picture, the same way PAD-184's row dump did."""
    row = panel._rows[GROUP_ROW]
    log("row %d: title=%r members=%d roll=%r"
        % (GROUP_ROW, row.title, len(row.members), row.roll))
    log("  _ed_roll=%r norepeat=%r"
        % (panel._ed_roll.get(),
           getattr(panel, "_ed_roll_norepeat", None)
           and panel._ed_roll_norepeat.get()))


def controls(widget, out=None):
    """Every radio button and tick under *widget*, as (class, text, state)."""
    out = [] if out is None else out
    for w in widget.winfo_children():
        cls = w.winfo_class()
        if cls in ("TRadiobutton", "TCheckbutton"):
            out.append((cls, w.cget("text"), str(w.state())))
        controls(w, out)
    return out


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
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    """The primary, then a random card over four song sets of its own.

    THE ROWS ARE WRITTEN, NOT THE EDITOR VARIABLES (PAD-184): a select and
    the editor load it defers do not both land inside one update(), and the
    titles end up on the wrong rows."""
    panel = win._multiboot_panel
    panel.new_card()
    panel.add_image(PRIMARY[0])
    panel.add_group([q for q, _t in MEMBERS], title="GODZILLA JUKEBOX",
                    subtitle="four song sets, one card")
    panel._rows[0].title, panel._rows[0].subtitle = PRIMARY[1], PRIMARY[2]
    for m, (_q, title) in zip(panel._rows[GROUP_ROW].members, MEMBERS):
        m.title = title
    panel._refresh_tree(select=GROUP_ROW)
    panel._table.select(GROUP_ROW)
    root.update()
    log("rows: %s" % [(r.title, len(getattr(r, "members", []) or []))
                      for r in panel._rows])
    describe(panel)


@step(1500)
def s_truly_random():
    """The box as a new random card comes up: the truly-random rule."""
    panel = win._multiboot_panel
    dlg = panel.edit_image(GROUP_ROW)
    if dlg is None:
        log("could not open Edit image")
        return
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    log("controls: %s" % controls(dlg.body))
    describe(panel)
    snap(os.path.join(OUTDIR, "%s_how_it_picks.png" % SUFFIX), dlg.top)
    globals()["DLG"] = dlg


@step(1200)
def s_shuffle():
    """...and the same box with the shuffle rule chosen."""
    panel = win._multiboot_panel
    dlg = globals().get("DLG")
    if dlg is None:
        return
    panel._ed_roll.set("shuffle")
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    log("controls: %s" % controls(dlg.body))
    describe(panel)
    snap(os.path.join(OUTDIR, "%s_how_it_picks_shuffle.png" % SUFFIX),
         dlg.top)
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
