"""PAD-187: the Edit image… dialog's height, and what the image will look like.

    python scripts/shot_pad187.py OUTDIR [--suffix before|after]

Writes three pictures into OUTDIR:

  ``<suffix>_edit_image.png``    Edit image… on a row that shows the game's
                                 own logo, with a prepared media set behind
                                 it (the state the tab is in after it has
                                 drawn its preview once).
  ``<suffix>_edit_picture.png``  the same dialog on a row whose picture is a
                                 file the owner chose.
  ``<suffix>_edit_random.png``   Edit random card… - the tallest shape this
                                 dialog has, and the one BEN reported: nine
                                 ways for a random card to draw itself, one
                                 under the other.

BEN, 2026-09-20: "The properties window on a multiboot image properties can
go off the bottom of the screen hiding critical buttons... change all the
radio buttons to a drop down list to save space... Add in a preview of what
it will look like. Currently you have to select it, and go back to the main
page to see what it looks like."

A variant of scripts/shot_pad184.py - same App, same PrintWindow, same
DPI-unaware capture, same settings backup.  What it adds is a STAGED MEDIA
DIRECTORY: three art PNGs and a media.json that names what each was made
from, copied out of David's own Beatles card media (read only, never
written), so the dialog can be photographed in the state it is in on a tab
that has already rendered.

Each run logs the dialog's requested height against the desktop's, which is
the measurement the report is about.

Nothing is built and no tool runs: PAD_MULTIBOOT_AUTO=0 and
PAD_MULTIBOOT_PLAN=0 keep the preview render and the size check off, and no
button in any dialog is pressed.
"""
import ctypes
import json
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
SETTINGS_BAK = SETTINGS + ".shotbak187"

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

SHOT_W, SHOT_H = 1360, 900

IMG_DIR = os.path.join(
    r"C:\Users\david\Documents\development\pinball-asset-decryptor",
    "images", "Stern", "spike2")

#: The three Beatles builds David's own multi card rolls between.
IMAGES = [
    (os.path.join(IMG_DIR, "beatles-1_29_0.Release.8G.sdcard.raw"),
     "BEATLES", "Stock 1.29"),
    (os.path.join(IMG_DIR, "beatles-1_29_0.i107-variant-a.8G.sdcard.raw"),
     "BEATLES A", "Variant A"),
    (os.path.join(IMG_DIR, "beatles-1_29_0.i107-variant-b.8G.sdcard.raw"),
     "BEATLES B", "Variant B"),
]

#: Where this card is written, and so where its media directory is:
#: <out dir>/media (multiboot_tab.media_dir_for).
WORK = os.path.join(os.environ.get("TEMP", r"C:\tmp"), "pad187")
OUT = os.path.join(WORK, "beatles.multi.raw")
MEDIA = os.path.join(WORK, "media")
PICTURE = os.path.join(WORK, "Abbey Road.png")

#: David's own prepared media, the source of the art PNGs staged above.
#: READ ONLY - the rig copies out of it and never writes into it.
REAL_MEDIA = os.path.join(
    r"C:\Users\david\OneDrive\Desktop",
    "media-beatles-1_29_0.Multigame.8G.sdcard.multi.beta")

#: Row 0 shows the game's own logo (the default), row 1 a picture file, and
#: the last row is the random card.
LOGO_ROW, PICTURE_ROW = 0, 1


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


def stage_media():
    """A prepared media directory for this form: art<N>.png per image and a
    media.json that says each was made from 'auto' (the game's own logo),
    which is what the rows below ask for.  Copied out of David's real card
    media; a missing source is not fatal (the dialog then says the picture
    has not been rendered yet, which is its other honest answer)."""
    os.makedirs(MEDIA, exist_ok=True)
    got = []
    for i in range(len(IMAGES)):
        src = os.path.join(REAL_MEDIA, "art%d.png" % i)
        dst = os.path.join(MEDIA, "art%d.png" % i)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            got.append(i)
        else:
            log("no %s - image %d will have no rendered picture" % (src, i))
    with open(os.path.join(MEDIA, "media.json"), "w", encoding="utf-8") as f:
        json.dump({"images": [{"art": "art%d.png" % i if i in got else None,
                               "anim": None, "music": None, "confirm": None,
                               "art_source": "auto", "anim_source": "none",
                               "music_source": "none", "confirm_source": "none"}
                              for i in range(len(IMAGES))],
                   "sound_move": None, "sound_confirm": None, "volume": 50},
                  f, indent=1)
    # ...and the picture file row 1 uses: another of the same card's logos,
    # standing in for a picture the owner picked off their own disk.
    src = os.path.join(REAL_MEDIA, "art3.png")
    if os.path.isfile(src) and not os.path.isfile(PICTURE):
        shutil.copy2(src, PICTURE)
    log("staged %s (%s)" % (MEDIA, ", ".join(sorted(os.listdir(MEDIA)))))


os.makedirs(WORK, exist_ok=True)
stage_media()

sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

app = App()
# NOTHING PUTS DAVID'S OWN CARD BACK OVER THE FORM THIS RIG BUILDS.  The app
# restores the saved multi-boot form whenever a manufacturer is applied
# (App.restore_multiboot_state), and on a slow start that landed AFTER the
# rows below were added: one run photographed his Beatles project's titles in
# a dialog opened on this rig's random card.
app.restore_multiboot_state = lambda *_a, **_kw: None
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
    """Three Beatles builds, a picture file on one of them, and a random
    card over all three - the form the three shots are taken from."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, _t, _s in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s - the row will show the path only" % path)
        panel.add_image(path)
    for i, (_p, title, sub) in enumerate(IMAGES):
        panel._rows[i].title = title
        panel._rows[i].subtitle = sub
    panel._out_var.set(OUT)
    panel.add_random_over_existing(title="SURPRISE ME",
                                   subtitle="a different one every power-up")
    panel._refresh_tree(select=PICTURE_ROW)
    panel._table.select(PICTURE_ROW)
    root.update()
    # the picture row's own file, set the way the dialog sets it (the
    # editor writes through to the selected row)
    panel._ed_picture.set(PICTURE)
    panel._ed_media.set("picture")
    panel._compact_var.set(False)
    root.update()
    log("media dir: %s (%s)"
        % (panel.media_dir(), os.path.isdir(panel.media_dir())))
    log("rows: %s" % [(r.title, r.art, r.anim) for r in panel._rows])


def shoot(name, index):
    panel = win._multiboot_panel
    # The form this shot is about, said in the log: a rig whose rows have
    # been replaced under it photographs the wrong card (see above).
    log("%s: row %d of %d is %r" % (name, index, len(panel._rows),
                                    panel._rows[index].title
                                    if index < len(panel._rows) else None))
    dlg = panel.edit_image(index)
    if dlg is None:
        log("could not open Edit image on row %d" % index)
        return
    for _ in range(4):
        root.update()
        time.sleep(0.25)
    log("%s: dialog wants %dx%d of a %dx%d desktop"
        % (name, dlg.top.winfo_reqwidth(), dlg.top.winfo_reqheight(),
           root.winfo_screenwidth(), root.winfo_screenheight()))
    snap(os.path.join(OUTDIR, "%s_%s.png" % (SUFFIX, name)), dlg.top)
    dlg.cancel()
    root.update()


@step(1500)
def s_edit_image():
    shoot("edit_image", LOGO_ROW)


@step(1200)
def s_edit_picture():
    shoot("edit_picture", PICTURE_ROW)


@step(1200)
def s_edit_random():
    panel = win._multiboot_panel
    shoot("edit_random", len(panel._rows) - 1)


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


root.after(180000, lambda: root.destroy())
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
