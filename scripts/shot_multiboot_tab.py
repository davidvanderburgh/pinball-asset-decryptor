"""Capture the Multi-boot tab (item 90) for the README.

    python scripts/shot_multiboot_tab.py [out.png] [emulate-out.png] [--frame F.ppm]

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one tab that rig does not cover.
``out.png`` defaults to docs/screenshots/multi-boot.png.  Given a second
path the Emulate tab is snapped there too, straight after - the tab's
button row gained a 'Boot selector' checkbutton in the same ticket, and
one launch of the GUI can show both.  One difference from that rig: the
window is sized for the tab, not for the desktop, and when it overhangs
the desktop the capture is tiled (see ``snap``) - the tab is ~1370px tall
and a 1024x768 desktop cannot show it whole.

WHAT THE FORM SHOWS.  An empty tab proves nothing, so the form is filled
the way a user would fill it for the card the ticket was written for:
the stock Turtles image as the primary and the 1987-cartoon upscale
beside it, with the menu titles typed in and the second image's attract
clip as its animation (20 s in, 2 s long, 8 fps - the new clip fields).
Nothing is built - Check size, Prepare media, Build, Flash and Render
preview all shell out to wsl.exe, and none of them is pressed.  The size
sentence under the buttons is the one Check size would print for two 8G
images (the tool's own plan output, fed to the same parser the button
uses), and the preview box shows a frame through the panel's public
``load_frame`` seam: a real selector snapshot when ``--frame F.ppm`` names
one, otherwise a stand-in drawn here with PIL in the menu's own layout
(dark ground, SELECT GAME CODE, one card per image, the highlighted one
framed amber) so the shot shows the whole tab at work without a tool
having run.

AND THE TAB IS SHOWN AFTER A LOAD.  The last thing the shot does is hand
the panel a synthetic ``inspect --json`` report through its public loader
(``load_inspect``) - the same report the tool prints for David's v2 card,
made up here so no card is opened and WSL is never called - and then makes
one pending change to the menu.  So the picture is of the tab in editing
mode: the fields all came off a card, and the line under the buttons says
what 'Apply to card' would write into it.
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
FRAME = None
if "--frame" in ARGS:
    i = ARGS.index("--frame")
    FRAME = os.path.abspath(ARGS[i + 1])
    del ARGS[i:i + 2]
OUT = os.path.abspath(ARGS[0] if ARGS else os.path.join(
    REPO, "docs", "screenshots", "multi-boot.png"))
EMU_OUT = os.path.abspath(ARGS[1]) if len(ARGS) > 1 else None
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak90"

#: The two images on the card, in card order (first = primary), and the
#: menu text typed for each.
IMAGES = [
    (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images"
     r"\Stern\spike2\turtles_pro-1_59_0.Release.8G.sdcard.raw",
     "STERN 1.59.0", "Original Stern code"),
    (r"D:\Pinball\TMNT 1987\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw",
     "TMNT 1987", "1987 cartoon upscale"),
]

#: The second image's animation: its attract clip, 20 s in, 2 s at 8 fps.
CLIP = ("auto", "20", "2", "8")

#: The preview: image 1 highlighted, frame 3 of the 16-frame clip.
HIGHLIGHT, FRAME_INDEX, FRAMES = 1, 3, 16

#: The card the shot then LOADS - David's v2 multi card.  It is never
#: opened: the report below is made up, and load_inspect takes it as if
#: the tool had printed it.
CARD = (r"D:\Pinball\TMNT 1987\multi"
        r"\turtles_pro-1_59_0.multi-v2-stock+1987patched.16G.sdcard.raw")

#: The countdown on that card, and the one typed after the load - the one
#: pending change the status line reports (the preview shows the new one,
#: which is what Render preview would draw).
TIMEOUT_ON_CARD, TIMEOUT_NOW = 15, 20

#: mkmulticard.py plan, as it reports two 8G images side by side - the
#: lines the tab's parser reads.  Fed to the same _plan_step the Check size
#: button's worker calls, so the sentence in the shot is the real one.
PLAN_TEXT = (
    "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7\n"
    "image: 28755968 sectors = 14723055616 bytes (14.72 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -6861881344)\n"
    "  fits Stern 16G image size 15494807552: YES (spare 771751936)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 15636365312)\n")


def log(msg):
    print(msg, flush=True)


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


def snap(path):
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
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
    cards = [(60, 152, 662, 568), (698, 152, 1300, 568)]
    for i, (x0, y0, x1, y1) in enumerate(cards):
        hi = i == HIGHLIGHT
        d.rounded_rectangle((x0, y0, x1, y1), radius=18,
                            fill=(38, 46, 62) if hi else (26, 31, 42),
                            outline=(250, 190, 40) if hi else (60, 70, 90),
                            width=6 if hi else 2)
        # the art panel across the top 40 % of the card
        px0, py0, px1, py1 = x0 + 28, y0 + 22, x1 - 28, y0 + 190
        d.rectangle((px0, py0, px1, py1), fill=(18, 22, 30))
        if i == 0:
            centred_x = (px0 + px1) / 2
            f = _font(60)
            tw = d.textlength("TMNT", font=f)
            d.text((centred_x - tw / 2, py0 + 40), "TMNT", font=f,
                   fill=(120, 190, 90))
            f2 = _font(24)
            tw = d.textlength("PRO", font=f2)
            d.text((centred_x - tw / 2, py0 + 112), "PRO", font=f2,
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
        f = _font(48)
        tw = d.textlength(title, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, y0 + 250), title, font=f,
               fill=(255, 255, 255) if hi else (160, 170, 190))
        f = _font(26)
        tw = d.textlength(sub, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, y0 + 322), sub, font=f,
               fill=(225, 230, 240) if hi else (120, 130, 150))
    centred(626, "LEFT / RIGHT FLIPPER: choose      START: boot", 26,
            (150, 160, 180))
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


@step(500)
def s_geometry():
    # Tall enough for the whole tab (image list + editor, Menu, Output, the
    # button row, the size sentence, the preview and the tool pane) at the
    # README's width.  NOT clamped to the desktop the way
    # take_screenshots.py clamps: PrintWindow renders the whole window
    # whether or not the screen can show it, and this rig has run on a
    # 1024x768 virtual desktop where the clamp cut the tab off under the
    # Menu box.  Tk's default maxsize is the screen, so it is lifted first
    # or the geometry is silently capped.
    w, h = 1360, 1730
    root.maxsize(max(w, root.winfo_screenwidth()) + 100,
                 max(h, root.winfo_screenheight()) + 100)
    log("screen %dx%d -> window %dx%d"
        % (root.winfo_screenwidth(), root.winfo_screenheight(), w, h))
    root.geometry("%dx%d+40+40" % (w, h))


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
    panel._default_var.set(str(HIGHLIGHT))
    # Leave the second row selected so the editor shows its text.
    panel._tree.selection_set("1")
    panel._tree.focus("1")
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
    log("load_frame -> %s" % panel.load_frame(frame, HIGHLIGHT, FRAME_INDEX,
                                             FRAMES))
    # ROOM FOR IT.  The notebook was measured when the tab was selected;
    # the size sentence has since appeared under the buttons, and the
    # tool pane is the LAST widget packed - short of its height the
    # notebook clips it.  This is the app's own resize (the panel's
    # resize_fn), not a lever added for the photograph.
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    form = panel.form()
    log("rows: %s" % [(r.title, r.subtitle, r.anim, r.anim_start,
                       r.anim_seconds, r.anim_fps) for r in form.images])
    log("output: %s" % form.out)
    log("size sentence: %r" % panel._plan_lbl.cget("text"))
    log("preview status: %r" % panel._pv_status.cget("text"))
    log("tab reqheight=%s notebook height=%s window=%sx%s"
        % (win._tab_multiboot.winfo_reqheight(), win._notebook.cget("height"),
           root.winfo_width(), root.winfo_height()))
    log("tool pane mapped=%s h=%s"
        % (panel._log_text.winfo_ismapped(), panel._log_text.winfo_height()))


def inspect_report():
    """The report ``mkmulticard.py inspect --card <CARD> --json`` prints for
    David's v2 card - made up here, with the same two images the form above
    was filled with, so nothing is opened and WSL is never called.  Its
    shape is the tool's contract; the tab reads no more of it than this."""
    src = [multiboot_tab.wsl(path) for path, _t, _s in IMAGES]
    _anim, start, seconds, fps = CLIP
    return {
        "card": CARD, "size": 15494807552, "layout": "parts",
        "partitions": [{"index": 3, "device": "/dev/mmcblk0p3"},
                       {"index": 7, "device": "/dev/mmcblk0p7"}],
        "images": [
            {"index": 0, "device": "/dev/mmcblk0p3", "title": IMAGES[0][1],
             "subtitle": IMAGES[0][2], "art": "art0.png", "anim": None,
             "music": None, "art_source": "auto", "anim_source": "none",
             "source": src[0], "source_exists": os.path.isfile(IMAGES[0][0]),
             "title_dir": "turtles", "bypass": "bypassed"},
            {"index": 1, "device": "/dev/mmcblk0p7", "title": IMAGES[1][1],
             "subtitle": IMAGES[1][2], "art": "art1.png",
             "anim": "anim1.gif", "music": None, "art_source": "auto",
             "anim_source": "auto@%s:%s:%s" % (start, seconds, fps),
             "source": src[1], "source_exists": os.path.isfile(IMAGES[1][0]),
             "title_dir": "turtles", "bypass": "bypassed"}],
        "timeout": TIMEOUT_ON_CARD, "default": HIGHLIGHT, "volume": 50,
        "mixer_volume": None, "sound_move": "auto", "sound_confirm": "auto",
        "font": "/usr/local/codeselect/font.ttf",
        "media": [{"name": "art0.png", "bytes": 178_432},
                  {"name": "art1.png", "bytes": 191_204},
                  {"name": "anim1.gif", "bytes": 1_402_880}],
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
    # One change: the countdown. The preview frame above was drawn with the
    # new value, which is what Render preview would show.
    panel._timeout_var.set(str(TIMEOUT_NOW))
    panel._tree.selection_set("1")
    panel._tree.focus("1")
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
    log("Load card… mapped=%s  Apply mapped=%s"
        % (panel._load_btn.winfo_ismapped(),
           panel._apply_btn.winfo_ismapped()))
    log("output: %s" % panel._out_var.get())
    log("hint: %r" % panel._hint.cget("text"))
    log("tab reqheight=%s window=%sx%s"
        % (win._tab_multiboot.winfo_reqheight(), root.winfo_width(),
           root.winfo_height()))


@step(2000)
def s_snap():
    snap(OUT)


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
