"""Capture the Multi-boot tab (item 90) for the README, and measure it.

    python scripts/shot_multiboot_tab.py [out.png] [emulate-out.png]
                                         [--frame F.ppm] [--fit fit.png]
                                         [--measure]

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one tab that rig does not cover.
``out.png`` defaults to docs/screenshots/multi-boot.png.  Given a second
path the Emulate tab is snapped there too, straight after - the tab's
button row gained a 'Boot selector' checkbutton in the same ticket, and
one launch of the GUI can show both.

``--fit fit.png`` takes a SECOND shot of the same tab in a 1024x768
window - David's desktop - which is the size the layout is designed
around; ``--dialogs DIR`` snaps the two modals the detail lives behind
(Edit image… and Menu settings…) into that directory; and ``--measure``
skips the pictures altogether and prints the height every section of the
tab needs, at 1360x900, at 1024x768, and then SWEPT across every width in
SWEEP_WIDTHS.  The number that matters is the first line of each: the
notebook is pinned to the selected tab's requested height, so that is the
tab's whole vertical cost, and it has to stay under about 640 px at every
one of those widths - and the preview must never grow as the window
shrinks (the layout does not reflow, so the width can only change the
size of the picture, and only one way).

WHAT THE FORM SHOWS.  An empty tab proves nothing, so the form is filled
with THREE images the way a user would fill it - which is also what puts
every state of the table's row icons in one picture: the first row's up
arrow outlined, the last row's down arrow outlined, a middle row with
both live, and the dim '+ Add an image…' row under them.  Nothing is
built - Build, Flash, the preview's own redraw and the two runs the tab
starts BY ITSELF (the size check when the image list moves, the media
prepare when Sound is ticked) all shell out to wsl.exe; none of them is
pressed, and both automatic ones are switched off with
``PAD_MULTIBOOT_AUTO=0`` and ``PAD_MULTIBOOT_PLAN=0`` before the app
starts.  The tab is also EMPTIED first (it remembers its form per project
now, so a developer's own card would otherwise be in the picture).  The
size sentence in the status block is the one the automatic size check
prints (the tool's own plan output, fed to the same parser that run's own
step calls), and the preview shows a frame through the panel's public
``load_frame`` seam: a real selector snapshot when ``--frame F.ppm`` names
one, otherwise a stand-in drawn here with PIL in the menu's own layout
(dark ground, SELECT GAME CODE, one card per image, the highlighted one
framed amber) so the shot shows the whole tab at work without a tool
having run.

AND THE TAB IS SHOWN AFTER A LOAD.  The last thing the shot does is hand
the panel a synthetic ``inspect --json`` report through its public loader
(``load_inspect``) - the same report the tool prints for a multi-image
card, made up here so no card is opened and WSL is never called - and
then makes one pending change to the menu.  So the picture is of the tab
in editing mode: the fields all came off a card, and the status block
says what 'Apply to card' would write into it.
"""
import ctypes
import os
import re
import shutil
import sys
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def selector_footer(which="START"):
    """The footer line the SELECTOR draws, read out of its own source.

    The stand-in frame below is drawn in Python (this script must never
    need WSL or an ARM binary), so it would otherwise carry a COPY of a
    string the selector owns - and a copy drifts: the selector grew a
    second footer for the Action button while a copy here would have gone
    on claiming START alone.  codeselect.c keeps both spellings as macros
    on their own lines for exactly this, and tests/test_multiboot_tab.py
    fails if this stops matching them.  FOOT_START is the honest one here:
    a faked frame resolves no switch table, so it has no Action button.
    """
    src = os.path.join(REPO, "tools", "spike2_emu", "codeselect",
                       "codeselect.c")
    with open(src, encoding="utf-8") as fh:
        found = dict(re.findall(r'^#define FOOT_(START|ACTION)\s+"(.*)"$',
                                fh.read(), re.M))
    return found[which]


ARGS = list(sys.argv[1:])
FRAME = None
if "--frame" in ARGS:
    i = ARGS.index("--frame")
    FRAME = os.path.abspath(ARGS[i + 1])
    del ARGS[i:i + 2]
FIT_OUT = None
if "--fit" in ARGS:
    i = ARGS.index("--fit")
    FIT_OUT = os.path.abspath(ARGS[i + 1])
    del ARGS[i:i + 2]
#: ``--warn out.png``: the same card with one image a version behind, so
#: the version strip is up.  It is the one state a screenshot cannot show
#: by accident - every card the tab is otherwise driven with is sound.
WARN_OUT = None
if "--warn" in ARGS:
    i = ARGS.index("--warn")
    WARN_OUT = os.path.abspath(ARGS[i + 1])
    del ARGS[i:i + 2]

DIALOG_DIR = None
if "--dialogs" in ARGS:
    i = ARGS.index("--dialogs")
    DIALOG_DIR = os.path.abspath(ARGS[i + 1])
    os.makedirs(DIALOG_DIR, exist_ok=True)
    del ARGS[i:i + 2]
MEASURE = "--measure" in ARGS
if MEASURE:
    ARGS.remove("--measure")
OUT = os.path.abspath(ARGS[0] if ARGS else os.path.join(
    REPO, "docs", "screenshots", "multi-boot.png"))
EMU_OUT = os.path.abspath(ARGS[1]) if len(ARGS) > 1 else None
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak90"

#: The tab drives the selector under WSL whenever a field changes, and asks
#: mkmulticard for the card's size whenever the image list does; a
#: photograph must start neither.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"

#: The window the README shot is taken in, and the desktop the fit check
#: is taken in (David's, measured 2026-09-02).
SHOT_W, SHOT_H = 1360, 900
FIT_W, FIT_H = 1024, 768

#: The images on the card, in card order (first = primary), and the menu
#: text typed for each.  THREE of them, so the shot shows every state of
#: the row icons at once: the first row's ▲ outlined, the last row's ▼
#: outlined, and a middle row with both live - plus the template row under
#: them.  Sample DATA is allowed to be specific; the tab's own copy is not.
IMAGES = [
    (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images"
     r"\Stern\spike2\turtles_pro-1_59_0.Release.8G.sdcard.raw",
     "STERN 1.59.0", "Original Stern code"),
    (r"D:\Pinball\TMNT 1987\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw",
     "TMNT 1987", "1987 cartoon upscale"),
    (r"D:\Pinball\TMNT 1987\turtles_le-1_59_0.1987-upscaled.8G.sdcard.raw",
     "TMNT 1987 LE", "1987 upscale, LE code"),
]

#: The game code version each row shows in its Code column - the column a
#: builder fills in when it has read one off the .raw.
VERSIONS = ["1.59.0", "1.59.0", "1.59.0"]

#: The second image's animation: its attract clip, 20 s in, 2 s at 8 fps.
CLIP = ("auto", "20", "2", "8")

#: The preview: image 1 highlighted, frame 3 of the 16-frame clip.
HIGHLIGHT, FRAME_INDEX, FRAMES = 1, 3, 16

#: The card the shot then LOADS.  It is never opened: the report below is
#: made up, and load_inspect takes it as if the tool had printed it.
CARD = (r"D:\Pinball\TMNT 1987\multi"
        r"\turtles_pro-1_59_0.multi-v2-stock+1987patched.16G.sdcard.raw")

#: The countdown on that card, and the one typed after the load - the one
#: pending change the status line reports (the preview shows the new one,
#: which is what a redraw would draw).
TIMEOUT_ON_CARD, TIMEOUT_NOW = 15, 20

#: mkmulticard.py plan, as it reports two 8G images side by side - the
#: lines the tab's parser reads.  Fed to the same _plan_step the size check
#: button's worker calls, so the sentence in the shot is the real one.
PLAN_TEXT = (
    "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7\n"
    "image: 28755968 sectors = 14723055616 bytes (14.72 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -6861881344)\n"
    "  fits Stern 16G image size 15494807552: YES (spare 771751936)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 15636365312)\n")


def log(msg):
    # The tab's row icons (✎ − ▲ ▼) are outside cp1252, and a console that
    # cannot encode one must not take the step down with it.
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc),
              flush=True)


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
if EMU_OUT:
    os.makedirs(os.path.dirname(EMU_OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.gui import multiboot_tab  # noqa: E402

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
    root.update_idletasks()
    hwnd = user32.GetAncestor((widget or root).winfo_id(), 2)  # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    # THE DESKTOP MAY BE SMALLER THAN THE WINDOW.  Tk only paints what
    # Windows says is visible, and the DWM surface PrintWindow reads is black
    # everywhere else - a 1360x1180 window on the 1024x768 desktop this rig
    # first ran on came back with the tab cut off under the Menu box and the
    # rest solid black.  So when the window overhangs, it is walked across
    # the desktop a tile at a time: each stop puts another part of it on
    # screen (Tk paints that part), PrintWindow is read, and the on-screen
    # slice goes into one canvas.  A window that fits is one tile, in place.
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    sw, sh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)

    def offsets(size, span):
        if size <= span:
            return [0]
        out = list(range(0, size - span, span)) + [size - span]
        return out
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
            # Let Tk see the expose and paint the newly visible part.
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


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def stand_in_frame(path):
    """A 1360x768 P6 PPM in the selector's own layout (see codeselect's
    README: the dark ground, SELECT GAME CODE, a row of cards with an art
    panel across the top, the highlighted one framed amber, the footer and
    the countdown) - what the machine draws, redrawn here with PIL so the
    README shot needs no WSL.  Pass --frame to use a real snapshot."""
    W, H = 1360, 768
    img = Image.new("RGB", (W, H), (11, 14, 20))
    d = ImageDraw.Draw(img)

    def centred(y, text, size, fill):
        f = _font(size)
        tw = d.textlength(text, font=f)
        d.text(((W - tw) / 2, y), text, font=f, fill=fill)
        return f

    centred(50, "SELECT GAME CODE", 54, (236, 240, 246))
    # One card per image, across the frame - the selector lays them out the
    # same way however many there are.
    n = len(IMAGES)
    margin, gap = 60, 36
    card_w = (W - 2 * margin - gap * (n - 1)) / float(n)
    cards = [(int(margin + i * (card_w + gap)), 152,
              int(margin + i * (card_w + gap) + card_w), 568)
             for i in range(n)]
    for i, (x0, y0, x1, y1) in enumerate(cards):
        hi = i == HIGHLIGHT
        d.rounded_rectangle((x0, y0, x1, y1), radius=18,
                            fill=(38, 46, 62) if hi else (26, 31, 42),
                            outline=(250, 190, 40) if hi else (60, 70, 90),
                            width=6 if hi else 2)
        # the art panel across the top 40 % of the card
        px0, py0, px1, py1 = x0 + 28, y0 + 22, x1 - 28, y0 + 190
        d.rectangle((px0, py0, px1, py1), fill=(18, 22, 30))
        if i != HIGHLIGHT:
            centred_x = (px0 + px1) / 2
            f = _font(60)
            tw = d.textlength("TMNT", font=f)
            d.text((centred_x - tw / 2, py0 + 40), "TMNT", font=f,
                   fill=(120, 190, 90))
            f2 = _font(24)
            word = "PRO" if i == 0 else "LE"
            tw = d.textlength(word, font=f2)
            d.text((centred_x - tw / 2, py0 + 112), word, font=f2,
                   fill=(200, 205, 215))
        else:
            # frame 3 of the attract clip: stripes standing in for it
            for k in range(0, px1 - px0, 40):
                shade = 70 + (k // 40 + FRAME_INDEX) % 5 * 22
                d.rectangle((px0 + k, py0, min(px1, px0 + k + 40), py1),
                            fill=(shade // 3, shade // 2, shade))
            f = _font(28)
            d.text((px0 + 16, py1 - 44), "attract clip - frame %d"
                   % FRAME_INDEX, font=f, fill=(240, 240, 240))
        f = _font(20)
        label = "IMAGE %d" % (i + 1)
        tw = d.textlength(label, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, y0 + 206), label, font=f,
               fill=(250, 190, 40) if hi else (110, 120, 140))
        title, sub = IMAGES[i][1], IMAGES[i][2]
        # ...at whatever size fits the card the layout gave it
        size = 48
        f = _font(size)
        while size > 20 and d.textlength(title, font=f) > (x1 - x0) - 30:
            size -= 4
            f = _font(size)
        tw = d.textlength(title, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, y0 + 250), title, font=f,
               fill=(255, 255, 255) if hi else (160, 170, 190))
        size = 26
        f = _font(size)
        while size > 14 and d.textlength(sub, font=f) > (x1 - x0) - 24:
            size -= 2
            f = _font(size)
        tw = d.textlength(sub, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, y0 + 322), sub, font=f,
               fill=(225, 230, 240) if hi else (120, 130, 150))
    centred(626, selector_footer(), 26, (150, 160, 180))
    centred(690, "booting %s in %d s" % (IMAGES[HIGHLIGHT][1], TIMEOUT_NOW),
            30, (250, 190, 40))
    img.save(path)           # .ppm -> binary P6, what --snapshot writes
    return path


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


def set_window(w, h):
    """Size the window, lifting Tk's default maxsize (the screen) first -
    PrintWindow renders the whole window whether or not the screen can show
    it, and without this the geometry is silently capped."""
    root.maxsize(max(w, root.winfo_screenwidth()) + 100,
                 max(h, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (w, h))
    root.update_idletasks()


#: Every window width the sweep measures the tab at, and what it has to
#: be true at all of them.
SWEEP_WIDTHS = (840, 889, 950, 1024, 1200, 1360)
HEIGHT_BUDGET = 640

#: What the sweep found, so s_sweep can judge it once it has walked them.
SWEEP = []


def measure(label, collect=False):
    """Print the height every part of the tab needs.  The first line is the
    one that matters: the notebook is pinned to the selected tab's
    requested height (MainWindow._resize_notebook_to_current_tab), so that
    IS the tab's whole vertical cost."""
    panel = win._multiboot_panel
    tab = win._tab_multiboot
    root.update_idletasks()
    log("")
    log("== %s: window %dx%d, screen %dx%d"
        % (label, root.winfo_width(), root.winfo_height(),
           root.winfo_screenwidth(), root.winfo_screenheight()))
    budget = root.winfo_height() - multiboot_tab.APP_CHROME_H
    log("   TAB reqheight = %d px  (budget %d for this %d-high window; "
        "%d on a 768-high desktop)  reqwidth = %d"
        % (tab.winfo_reqheight(), budget, root.winfo_height(),
           HEIGHT_BUDGET, tab.winfo_reqwidth()))
    outer = panel._outer
    # In the order the panel builds them - the version banner included,
    # even though it is packed only while a card's images disagree: it is
    # a CHILD from the start, so leaving it out of this list shifted every
    # name after it onto the wrong row.
    names = ["source row", "version banner", "preview", "images table",
             "row label", "action bar", "status"]
    for name, child in zip(names, outer.winfo_children()):
        log("   %-24s reqh %4d  h %4d  mapped %s"
            % (name, child.winfo_reqheight(), child.winfo_height(),
               child.winfo_ismapped()))
    log("   preview box  %dx%d  (aspect %.3f, the frame's is %.3f)"
        % (panel._pv_w, panel._pv_h, panel._pv_w / float(panel._pv_h),
           multiboot_tab.FRAME_W / float(multiboot_tab.FRAME_H)))
    log("   table        rows %d  reqh %d  reqw %d"
        % (len(panel._tree.get_children()),
           panel._table_box.winfo_reqheight(),
           panel._table_box.winfo_reqwidth()))
    for btn, name in ((panel._out_entry, "Multi-boot card image"),
                      (panel._browse_btn, "Browse…"),
                      (panel._new_btn, "New card"),
                      (panel._apply_btn, "Apply to card"),
                      (panel._build_btn, "Build & verify"),
                      (panel._flash_btn, "Flash to SD card…"),
                      (panel._emu_btn, "Run in emulator"),
                      (panel._menu_btn, "Menu settings…")):
        if not btn.winfo_ismapped():
            log("   !! %s IS NOT MAPPED - the row overflowed" % name)
    if collect:
        SWEEP.append((root.winfo_width(), tab.winfo_reqheight(),
                      panel._pv_w, panel._pv_h))


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
    # A newer release on GitHub packs the update banner across the top; it
    # is about this checkout, not the tab, so it stays out of the README.
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    """Fill the form through the panel's public seam (add_image) and its
    editor variables, exactly as tests/test_multiboot_tab.py does.  No
    action button is pressed: every one of them runs a tool under WSL."""
    panel = win._multiboot_panel
    # FROM AN EMPTY TAB, ALWAYS.  The tab now remembers its form per project
    # and falls back to the global settings, so App() and then s_stern's
    # manufacturer change have each restored whatever THIS developer left in
    # it - and add_image APPENDS.  Without this the README shot carried
    # someone's own card path and image list, and --measure was measuring a
    # taller table than the gate was written for (the table's height follows
    # the row count), which made "sweep: OK" a statement about one machine.
    panel.new_card()
    log("tab cleared: rows=%d card=%r"
        % (len(panel._rows), panel._out_var.get()))
    for path, _title, _sub in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s - the row will show the path only" % path)
        panel.add_image(path)
    for i, (_path, title, sub) in enumerate(IMAGES):
        # Select the row, let <<TreeviewSelect>> load the editor, then type
        # into it: the editor writes back to the selected row on every
        # keystroke (the trace on _ed_title / _ed_sub).
        panel._tree.selection_set(str(i))
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    # The second image animates: its attract clip, through the clip fields.
    panel._tree.selection_set("1")
    root.update()
    anim, start, seconds, fps = CLIP
    panel._ed_anim.set(anim)
    panel._ed_anim_start.set(start)
    panel._ed_anim_seconds.set(seconds)
    panel._ed_anim_fps.set(fps)
    # ...and it has a confirm sound of its OWN, so the Confirm column shows
    # both states in one picture: a row's own value plain, and the rows that
    # fall back to the menu's in brackets.
    panel._ed_confirm.set("synth")
    panel._default_var.set(str(HIGHLIGHT))
    # The Code column: what a builder that has read the version off each
    # .raw would put there.  Set on the rows, then redrawn.
    for row, version in zip(panel._rows, VERSIONS):
        row.version = version
    panel._refresh_tree(select=HIGHLIGHT)
    # Leave the highlighted row selected so the editor shows its text.
    panel._tree.selection_set(str(HIGHLIGHT))
    panel._tree.focus(str(HIGHLIGHT))
    root.update()
    panel._plan_step("plan", 0, PLAN_TEXT)
    # The preview: a frame through load_frame, the panel's public seam -
    # never a render, which would run the selector under WSL.
    frame = FRAME
    if frame is None:
        frame = stand_in_frame(os.path.join(
            os.environ.get("TEMP", "."), "multiboot_shot_frame.ppm"))
        log("stand-in frame drawn at %s" % frame)
    else:
        log("frame from --frame: %s" % frame)
    log("load_frame -> %s"
        % panel.load_frame(frame, HIGHLIGHT, FRAME_INDEX, FRAMES))
    # ROOM FOR IT.  The notebook was measured when the tab was selected
    # and the table has grown a row since; the status block is the LAST
    # thing packed, and short of its height the notebook clips it.  This
    # is the app's own resize (the panel's resize_fn), not a lever added
    # for the photograph.
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    form = panel.form()
    log("rows: %s" % [(r.title, r.subtitle, r.anim, r.anim_start,
                       r.anim_seconds, r.anim_fps) for r in form.images])
    log("output: %s" % form.out)
    log("size sentence: %r" % panel._plan_text)
    log("consequence: %r" % panel._edit_lbl.cget("text"))
    log("preview status: %r" % panel._pv_status.cget("text"))
    log("menu summary: %r" % panel._menu_lbl.cget("text"))
    log("table rows:")
    for i in panel._tree.get_children():
        log("   %-4s %s" % (i, panel._tree.item(i)["values"]))
    log("row label: %r" % panel._row_lbl.cget("text"))
    log("tab reqheight=%s notebook height=%s window=%sx%s"
        % (win._tab_multiboot.winfo_reqheight(), win._notebook.cget("height"),
           root.winfo_width(), root.winfo_height()))


def inspect_report():
    """The report ``mkmulticard.py inspect --card <CARD> --json`` prints for
    a multi-image card - made up here, with the same images the form above
    was filled with, so nothing is opened and WSL is never called.  Its
    shape is the tool's contract; the tab reads no more of it than this."""
    src = [multiboot_tab.wsl(path) for path, _t, _s in IMAGES]
    _anim, start, seconds, fps = CLIP
    devices = ["/dev/mmcblk0p3", "/dev/mmcblk0p7"] + [
        "/dev/mmcblk0p7:img%d" % i for i in range(2, len(IMAGES))]
    images = [
        {"index": i, "device": devices[i], "title": title,
         "subtitle": sub, "art": "art%d.png" % i,
         "anim": "anim%d.gif" % i if i == HIGHLIGHT else None,
         "art_source": "auto",
         "anim_source": ("auto@%s:%s:%s" % (start, seconds, fps)
                         if i == HIGHLIGHT else "none"),
         "music": None,
         # image 1 has a confirm sound of its OWN, so the Confirm column
         # shows both states at once: its own value plain, and the rows
         # that fall back to the menu's in brackets
         "confirm": "confirm%d.wav" % i if i == HIGHLIGHT else None,
         "confirm_source": "synth" if i == HIGHLIGHT else None,
         "source": src[i], "source_exists": os.path.isfile(path),
         "title_dir": "turtles", "bypass": "bypassed",
         # the version gate reads this off the image itself
         "version": VERSIONS[i], "version_source": "sidx",
         "node_fw_version": "1.33.0"}
        for i, (path, title, sub) in enumerate(IMAGES)]
    return {
        "card": CARD, "size": 15494807552, "layout": "parts",
        "partitions": [{"index": 3, "device": "/dev/mmcblk0p3"},
                       {"index": 7, "device": "/dev/mmcblk0p7"}],
        "images": images,
        "timeout": TIMEOUT_ON_CARD, "default": HIGHLIGHT, "volume": 50,
        "mixer_volume": None, "sound_move": "auto", "sound_confirm": "auto",
        "font": "/usr/local/codeselect/font.ttf",
        "media": ([{"name": "art%d.png" % i, "bytes": 178_432 + i}
                   for i in range(len(IMAGES))]
                  + [{"name": "anim%d.gif" % HIGHLIGHT,
                      "bytes": 1_402_880}]),
        "has_media_json": True, "has_build_json": True,
        "selector": {"bytes": 41272, "version": "codeselect 1.0"},
        "warnings": []}


@step(2500)
def s_load():
    """...and now the tab in EDITING mode: the same form, but read back off
    a card with 'Load card…' (through load_inspect, the loader's public
    seam - no tool runs), with one pending change so the line under the
    buttons says what Apply to card would write."""
    panel = win._multiboot_panel
    warnings = panel.load_inspect(inspect_report(), CARD)
    log("load warnings: %s" % (warnings or "none"))
    # The size sentence is about the IMAGE LIST, and the load has just
    # replaced it - so the tab drops the old answer and asks for a new one
    # by itself (MultibootPanel._maybe_plan).  That run is off here
    # (PAD_MULTIBOOT_PLAN=0: a photograph starts no tools), so the answer it
    # would print is fed to the same parser the run's own step calls.
    panel._plan_step("plan", 0, PLAN_TEXT)
    # One change: the countdown. The preview frame above was drawn with the
    # new value, which is what Render preview would show.
    panel._timeout_var.set(str(TIMEOUT_NOW))
    # The Code column fills itself here: the report carries each image's
    # game code version, read off the image by the tool that inspected it.
    log("versions off the card: %s" % [r.version for r in panel._rows])
    log("confirm sounds: %s" % [r.confirm or "(the menu's)"
                                for r in panel._rows])
    panel._refresh_tree(select=HIGHLIGHT)
    panel._tree.selection_set(str(HIGHLIGHT))
    panel._tree.focus(str(HIGHLIGHT))
    root.update()
    # The load cleared the preview (its media dir changed under it); put the
    # frame back through the same public seam.
    frame = FRAME or os.path.join(os.environ.get("TEMP", "."),
                                  "multiboot_shot_frame.ppm")
    log("load_frame -> %s" % panel.load_frame(frame, HIGHLIGHT, FRAME_INDEX,
                                              FRAMES))
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    log("editing %s" % panel._loaded_card)
    log("status: %r" % panel._edit_lbl.cget("text"))
    log("Apply to card: %s" % panel._apply_btn.cget("state"))
    # The row has no verb button any more (Browse… reads a card it picks,
    # and <Return> reads a typed path), so editing mode shows in the
    # sentence above and in Apply being live.
    log("can_read=%s  Apply mapped=%s"
        % (panel._can_read, panel._apply_btn.winfo_ismapped()))
    log("output: %s" % panel._out_var.get())
    log("hint: %r" % panel._hint.cget("text"))
    log("menu summary: %r" % panel._menu_lbl.cget("text"))
    log("table rows:")
    for i in panel._tree.get_children():
        log("   %-4s %s" % (i, panel._tree.item(i)["values"]))
    log("tab reqheight=%s window=%sx%s"
        % (win._tab_multiboot.winfo_reqheight(), root.winfo_width(),
           root.winfo_height()))


@step(2000)
def s_snap():
    measure("README window")
    if not MEASURE:
        snap(OUT)


@step(700)
def s_warn():
    """The loud one: a card whose images are NOT the same game code.  The
    strip is packed above the picture only while there is something wrong,
    so this is the only way to see it - and the only way to keep proving it
    fits."""
    if not WARN_OUT:
        return
    panel = win._multiboot_panel
    rep = inspect_report()
    rep["images"][-1]["version"] = "1.58.0"
    rep["version_mismatch"] = (
        "Images 0, 1 are 1.59.0 and image 2 is 1.58.0. Two builds of the "
        "same title share the machine's settings by NAME, so most carry "
        "over - but a setting only one build has falls back to its default, "
        "a renamed one reverts, and the store keeps three generations, so "
        "two boots of the other build erase a build-exclusive value.")
    rep["node_fw_mismatch"] = (
        "Images 0, 1 carry node board firmware 1.33.0; image 2 carries "
        "1.19.0. The machine records the running build's version at every "
        "boot, so this card can reflash the node boards on every swap.")
    panel.load_inspect(rep, CARD)
    panel._refresh_tree(select=HIGHLIGHT)
    # A load clears the preview (its media dir changed under it); put the
    # frame back, so the picture shows the banner OVER a drawn menu rather
    # than over the empty-tab placeholder.
    frame = FRAME or os.path.join(os.environ.get("TEMP", "."),
                                  "multiboot_shot_frame.ppm")
    panel.load_frame(frame, HIGHLIGHT, FRAME_INDEX, FRAMES)
    root.update()
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    measure("version warning")
    log("strip: %r" % panel._alarm.cget("text"))
    snap(WARN_OUT)


@step(800)
def s_fit():
    """The fit check: the same populated tab on David's own desktop.  The
    layout is designed around this size, so this is the picture that proves
    it - and --measure prints the numbers behind it."""
    if not (FIT_OUT or MEASURE):
        return
    set_window(FIT_W, FIT_H)
    root.update()
    time.sleep(0.4)
    root.update()
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    measure("David's desktop")
    if FIT_OUT:
        snap(FIT_OUT)
    set_window(SHOT_W, SHOT_H)


@step(400)
def s_sweep():
    """THE WIDTH SWEEP.  The layout does not reflow, so the only thing the
    width may change is the picture - and it may only ever get SMALLER as
    the window does.  Two things are asserted at every width: the tab never
    grows past its height budget (the notebook is pinned to it, and past
    that the rows below the fold are gone), and the preview never grows as
    the window shrinks (the old layout's worst trick: dragging the window
    narrower made the picture BIGGER and pushed the actions off the
    bottom)."""
    if not MEASURE:
        return
    SWEEP[:] = []
    for width in SWEEP_WIDTHS:
        set_window(width, FIT_H)
        root.update()
        time.sleep(0.25)
        root.update()
        win._resize_notebook_to_current_tab()
        root.update_idletasks()
        measure("sweep %d" % width, collect=True)
    log("")
    log("== SWEEP: width -> tab height, preview")
    bad = []
    prev_area = None
    for width, height, pw, ph in SWEEP:
        log("   %5d px -> tab %3d px, preview %4dx%-4d" % (width, height,
                                                           pw, ph))
        if height > HEIGHT_BUDGET:
            bad.append("%d px wide: the tab needs %d px (budget %d)"
                       % (width, height, HEIGHT_BUDGET))
        # (the sweep runs at 768 high on purpose - that is the desktop the
        # budget is for, so HEIGHT_BUDGET is the right number here)
        # walked narrowest first, so the picture must never get SMALLER as
        # the window gets wider - which is the same statement as 'it never
        # grows as the window shrinks', read backwards
        if prev_area is not None and pw * ph < prev_area:
            bad.append("%d px wide: the preview shrank as the window grew"
                       % width)
        prev_area = pw * ph
    for line in bad:
        log("   !! " + line)
    log("   sweep: %s" % ("FAIL" if bad else "OK"))
    set_window(SHOT_W, SHOT_H)


@step(600)
def s_dialogs():
    """The two modals the detail lives behind, each snapped on its own -
    they are separate toplevels, so PrintWindow has to be pointed at them
    rather than at the app window."""
    if not DIALOG_DIR:
        return
    panel = win._multiboot_panel
    for name, opener in (("multi-boot-edit-image.png",
                          lambda: panel.edit_image(1)),
                         ("multi-boot-menu-settings.png",
                          panel.open_menu_settings)):
        dlg = opener()
        if dlg is None:
            log("could not open %s" % name)
            continue
        for _ in range(3):
            root.update()
            time.sleep(0.2)
        log("%s: %dx%d" % (name, dlg.top.winfo_width(),
                           dlg.top.winfo_height()))
        snap(os.path.join(DIALOG_DIR, name), dlg.top)
        dlg.cancel()
        root.update()


@step(500)
def s_emulate():
    if EMU_OUT:
        win._notebook.select(win._tab_emulate)
        win._resize_notebook_to_current_tab()


@step(2500)
def s_emulate_snap():
    if EMU_OUT:
        chk = win._emulate_panel._select_chk
        log("Boot selector mapped=%s at x=%s y=%s w=%s"
            % (chk.winfo_ismapped(), chk.winfo_rootx() - root.winfo_rootx(),
               chk.winfo_rooty() - root.winfo_rooty(), chk.winfo_width()))
        snap(EMU_OUT)


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
