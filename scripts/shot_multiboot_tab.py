"""Capture the Multi-boot tab (item 90) for the README.

    python scripts/shot_multiboot_tab.py [out.png] [emulate-out.png]

A variant of take_screenshots.py (same PrintWindow, same DPI-unaware
capture, same settings backup) for the one tab that rig does not cover.
``out.png`` defaults to docs/screenshots/multi-boot.png.  Given a second
path the Emulate tab is snapped there too, straight after - the tab's
button row gained a 'Boot selector' checkbutton in the same ticket, and
one launch of the GUI can show both.  One difference from that rig: the
window is sized for the tab, not for the desktop, and when it overhangs
the desktop the capture is tiled (see ``snap``) - the tab is 926px tall
and a 1024x768 desktop cannot show it whole.

WHAT THE FORM SHOWS.  An empty tab proves nothing, so the form is filled
the way a user would fill it for the card the ticket was written for:
the stock Turtles image as the primary and the 1987-cartoon upscale
beside it, with the menu titles typed in.  Nothing is built - Check size,
Prepare media, Build and Flash all shell out to wsl.exe, and none of them
is pressed.  The size sentence under the buttons is the one Check size
would print for two 8G images (the tool's own plan output, fed to the
same parser the button uses), so the shot shows the whole tab at work
without a tool having run.
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
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots", "multi-boot.png"))
EMU_OUT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
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


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    # Tall enough for the whole tab (image list + editor, Menu, Output, the
    # button row, the size sentence and the tool pane) at the README's
    # width.  NOT clamped to the desktop the way take_screenshots.py clamps:
    # PrintWindow renders the whole window whether or not the screen can
    # show it, and this rig has run on a 1024x768 virtual desktop where the
    # clamp cut the tab off under the Menu box.  Tk's default maxsize is
    # the screen, so it is lifted first or the geometry is silently capped.
    w, h = 1360, 1180
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
    # Leave the second row selected so the editor shows its text.
    panel._tree.selection_set("1")
    panel._tree.focus("1")
    root.update()
    panel._plan_step("plan", 0, PLAN_TEXT)
    # ROOM FOR IT.  The notebook was measured when the tab was selected;
    # the size sentence has since appeared under the buttons, and the
    # tool pane is the LAST widget packed - short of its height the
    # notebook clips it.  This is the app's own resize (the panel's
    # resize_fn), not a lever added for the photograph.
    win._resize_notebook_to_current_tab()
    root.update_idletasks()
    form = panel.form()
    log("rows: %s" % [(r.title, r.subtitle) for r in form.images])
    log("output: %s" % form.out)
    log("size sentence: %r" % panel._plan_lbl.cget("text"))
    log("tab reqheight=%s notebook height=%s window=%sx%s"
        % (win._tab_multiboot.winfo_reqheight(), win._notebook.cget("height"),
           root.winfo_width(), root.winfo_height()))
    log("tool pane mapped=%s h=%s"
        % (panel._log_text.winfo_ismapped(), panel._log_text.winfo_height()))


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
