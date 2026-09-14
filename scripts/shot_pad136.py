"""PAD-136: the sound dropdowns, DROPPED OPEN, in both Multi-boot modals.

    python scripts/shot_pad136.py OUTDIR [--suffix before|after]

Writes ``<suffix>_edit_image_confirm.png`` and ``<suffix>_menu_settings_move
.png`` into OUTDIR.

A variant of scripts/shot_multiboot_tab.py - same App, same PrintWindow,
same DPI-unaware capture, same settings backup.  What it adds is the one
thing that rig cannot do: a ttk combobox's LIST is a separate override-
redirect toplevel, so PrintWindow on the dialog alone photographs a shut
dropdown.  Here the dialog and the popdown are each PrintWindow'd and
pasted into one canvas, which is what the eye sees.

The form is filled the way the complaint describes: three images, a WAV
browsed for the menu's confirm sound, another for image 1's confirm and a
third for image 3's music - three files already chosen SOMEWHERE in this
menu.  Then image 2 is edited and its 'Confirm sound' list is dropped
open, which is exactly the moment the report is about ("if I add one ...
it would be nice to have it as an option in the drop down list").  The
second shot does the same to the menu's own 'Move sound' list.

Nothing is built and no tool runs: PAD_MULTIBOOT_AUTO=0 and
PAD_MULTIBOOT_PLAN=0 keep the preview render and the size check off, and
no button in either dialog is pressed.
"""
import ctypes
import os
import shutil
import sys
import time
import traceback
import wave
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
SETTINGS_BAK = SETTINGS + ".shotbak136"

os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: David's desktop, which is also the size the tab is designed around.
SHOT_W, SHOT_H = 1024, 768

#: The three images on the card - the same card the report was filed
#: against (a Beatles multi-game), by the names its owner used.
IMAGES = [
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Abbey.8G.sdcard.raw",
     "Abbey Road", "v1.29"),
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Pepper.8G.sdcard.raw",
     "Sgt. Pepper", "v1.29"),
    (r"C:\temp\Beatles\Releases\beatles-1_29_0.Revolver.8G.sdcard.raw",
     "Revolver", "v1.29"),
]

#: The WAVs already chosen somewhere in this menu, and where.  Written for
#: real below: a path that is not on this machine is not an offer.
SOUNDS = [
    ("menu-confirm", "Beatles_MenuConfirm.wav"),
    ("image-confirm", "Beatles_3s_ComeTogether_Snip.wav"),
    ("image-music", "Beatles_AbbeyRoad_Medley.wav"),
]


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


def make_wavs():
    """The three WAVs, in a folder of their own under TEMP."""
    base = os.path.join(os.environ.get("TEMP", "."), "pad136_sounds")
    os.makedirs(base, exist_ok=True)
    out = {}
    for key, name in SOUNDS:
        path = os.path.join(base, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(bytes(2 * 2205))
        out[key] = path
    return out


WAVS = make_wavs()
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


def window_shot(widget):
    """``(image, left, top)``: the widget's whole window, PrintWindow'd,
    with the invisible resize border cropped off - and where on the desktop
    what is left starts, so a popdown can be pasted on to it."""
    root.update_idletasks()
    hwnd = user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    img = _print_window(hwnd, w, h)
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    return (img.crop((border, 0, w - border, h - border)),
            rect.left + border, rect.top)


def combos(widget, out=None):
    """Every ttk.Combobox under *widget*, in creation order."""
    out = [] if out is None else out
    for w in widget.winfo_children():
        if w.winfo_class() == "TCombobox":
            out.append(w)
        combos(w, out)
    return out


def post(cb):
    """Drop *cb*'s list open, and hand back the popdown's screen box."""
    root.tk.call("ttk::combobox::Post", cb)
    for _ in range(3):
        root.update()
        time.sleep(0.15)
    pd = root.tk.eval("ttk::combobox::PopdownWindow %s" % cb)
    return pd, (int(root.tk.call("winfo", "rootx", pd)),
                int(root.tk.call("winfo", "rooty", pd)),
                int(root.tk.call("winfo", "width", pd)),
                int(root.tk.call("winfo", "height", pd)))


def snap_with_list(path, dlg, cb):
    """The dialog AND its dropped-open list in one picture.

    The list is its own toplevel, so it is PrintWindow'd on its own and
    pasted where it sits; the canvas is whatever box holds both, because
    a list longer than the dialog's foot hangs off the bottom."""
    log("list: %s" % list(cb.cget("values")))
    pd, (px, py, pw, ph) = post(cb)
    dlg_img, dx, dy = window_shot(dlg.top)
    pd_hwnd = user32.GetAncestor(int(root.tk.call("winfo", "id", pd), 0), 2)
    pd_img = _print_window(pd_hwnd, pw, ph)
    left, top = min(dx, px), min(dy, py)
    right = max(dx + dlg_img.width, px + pw)
    bottom = max(dy + dlg_img.height, py + ph)
    canvas = Image.new("RGB", (right - left, bottom - top), (32, 32, 32))
    canvas.paste(dlg_img, (dx - left, dy - top))
    canvas.paste(pd_img, (px - left, py - top))
    canvas.save(path)
    log("snapped %s (%dx%d)" % (path, canvas.width, canvas.height))
    root.tk.call("ttk::combobox::Unpost", cb)
    root.update()


def set_window(w, h):
    root.geometry("%dx%d+0+0" % (w, h))
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
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    """Three images, and three WAVs already chosen among them."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, _t, _s in IMAGES:
        panel.add_image(path)
    for i, (_p, title, sub) in enumerate(IMAGES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    # image 1's OWN confirm sound: a file, browsed
    panel._table.select(0)
    root.update()
    panel._ed_confirm.set(WAVS["image-confirm"])
    # image 3's music: another file
    panel._table.select(2)
    root.update()
    panel._ed_music.set(WAVS["image-music"])
    # and the menu's own confirm sound: a third
    panel._confirm_var.set(WAVS["menu-confirm"])
    panel._refresh_tree(select=1)
    panel._table.select(1)
    root.update()
    log("rows: %s" % [(r.title, r.music, r.confirm) for r in panel._rows])
    log("menu: move=%r confirm=%r"
        % (panel._move_var.get(), panel._confirm_var.get()))


@step(1500)
def s_edit_image():
    """Image 2's 'Confirm sound' list, dropped open - the report's screen."""
    panel = win._multiboot_panel
    dlg = panel.edit_image(1)
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    cbs = combos(dlg.body)
    log("edit image: %d comboboxes" % len(cbs))
    snap_with_list(os.path.join(OUTDIR, "%s_edit_image_confirm.png" % SUFFIX),
                   dlg, cbs[1])
    dlg.cancel()
    root.update()


@step(1200)
def s_menu_settings():
    """...and the menu's own 'Move sound' list, which has the same list."""
    panel = win._multiboot_panel
    dlg = panel.open_menu_settings()
    for _ in range(3):
        root.update()
        time.sleep(0.2)
    cbs = combos(dlg.body)
    log("menu settings: %d comboboxes" % len(cbs))
    snap_with_list(os.path.join(OUTDIR, "%s_menu_settings_move.png" % SUFFIX),
                   dlg, cbs[0])
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
