"""PAD-137: the size strip's answer, and the two places a confirm sound lives.

    python scripts/shot_pad137.py OUTDIR [--suffix before|after]

Writes three pictures into OUTDIR:

  ``<suffix>_size_strip.png``    the whole tab, with the size strip drawn
                                 from a plan whose games are 10.83 GB and
                                 whose card is 32 GB - the report's own
                                 numbers ("why it suggested a 32gb card for
                                 my images when it looks like it does not
                                 break 16gb").
  ``<suffix>_edit_image.png``    Edit image… on an image whose Confirm sound
                                 is 'menu'.
  ``<suffix>_menu_settings.png`` Menu settings…, where the menu-wide confirm
                                 sound lives - the other of the two places
                                 the same report calls "not in synch".

A variant of scripts/shot_multiboot_tab.py and scripts/shot_pad136.py -
same App, same PrintWindow, same DPI-unaware capture, same settings
backup.  What it adds is a PLAN whose free space is what buys the bigger
card: the rig's own plan text fits a 16 GB card with 0.70 GB free, which
is the one shape this ticket is not about.

Nothing is built and no tool runs: PAD_MULTIBOOT_AUTO=0 and
PAD_MULTIBOOT_PLAN=0 keep the preview render and the size check off, the
plan output is handed to the panel's own ``_plan_step`` seam, and no
button in either dialog is pressed.
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
SETTINGS_BAK = SETTINGS + ".shotbak137"

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: Wide enough for the size strip's sentence to be read at all: the strip
#: gives the BAR up before the words, so a narrow window is a picture of a
#: sentence with no bar beside it.
SHOT_W, SHOT_H = 1360, 900

#: The card the report was filed against, by the names its owner used.
IMAGES = [
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Abbey.8G.sdcard.raw",
     "Abbey Road", "v1.29"),
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Pepper.8G.sdcard.raw",
     "Sgt. Pepper", "v1.29"),
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Revolver.8G.sdcard.raw",
     "Revolver", "v1.29"),
]

#: mkmulticard.py plan, in the shape the report describes: 10.83 GB of
#: games and 6.21 GB of room for updates, which together do not fit the
#: 16 GB card the games alone would.  Every number is a whole sector and
#: the three rows plus the room plus the overhead add up to the total, the
#: way the tool's own arithmetic does.
PLAN_TEXT = (
    "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7:img1, 2=/dev/mmcblk0p7:img2\n"
    "image-size 0 /dev/mmcblk0p3 1600000000 beatles-1_29_0.Abbey\n"
    "image-size 1 /dev/mmcblk0p7:img1 4600000000 beatles-1_29_0.Pepper\n"
    "image-size 2 /dev/mmcblk0p7:img2 4630000128 beatles-1_29_0.Revolver\n"
    "image-size free 6210000384 room for updates in the games partitions\n"
    "image-size overhead 609999872 boot + rootfs + data + dump + metadata\n"
    "image: 34472657 sectors = 17650000384 bytes (17.65 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -9788826112)\n"
    "  fits Stern 16G image size 15494807552: NO (spare -2155192832)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 12709420544)\n")

#: The image whose own confirm sound is set, so the list shows both states
#: and Menu settings has something to say about the images that ignore it.
OWN_CONFIRM = (1, "synth")

#: ...and the one Edit image… is opened on: it has no confirm of its own,
#: which is the row the question is about.
EDIT_ROW = 0


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


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
    """Three images, one of them with a confirm sound of its own, and the
    plan handed to the panel's own seam."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, _t, _s in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s - the row will show the path only" % path)
        panel.add_image(path)
    for i, (_p, title, sub) in enumerate(IMAGES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    i, value = OWN_CONFIRM
    panel._table.select(i)
    root.update()
    panel._ed_confirm.set(value)
    panel._refresh_tree(select=EDIT_ROW)
    panel._table.select(EDIT_ROW)
    # THE TICK IS OFF, whatever this developer last left in the settings:
    # the plan below is the ordinary layout's, and a picture of it beside a
    # ticked 'Compact build' would be a picture of two different questions.
    panel._compact_var.set(False)
    root.update()
    panel._plan_step("plan", 0, PLAN_TEXT)
    root.update()
    view = panel._size_view
    log("size: need=%r detail=%r" % (view["head"], view["detail"]))
    log("why: %r" % view.get("why", ""))
    log("rows: %s" % [(r.title, r.confirm) for r in panel._rows])


@step(1500)
def s_tab():
    snap(os.path.join(OUTDIR, "%s_size_strip.png" % SUFFIX))


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
    snap(os.path.join(OUTDIR, "%s_edit_image.png" % SUFFIX), dlg.top)
    dlg.cancel()
    root.update()


@step(1200)
def s_menu_settings():
    """...and Menu settings…, where the other confirm sound lives."""
    panel = win._multiboot_panel
    dlg = panel.open_menu_settings()
    if dlg is None:
        log("could not open Menu settings")
        return
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    snap(os.path.join(OUTDIR, "%s_menu_settings.png" % SUFFIX), dlg.top)
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
