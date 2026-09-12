"""PAD-135 proof shots: the Multi-boot tab's two modals and its size strip.

    python scripts/shot_pad135.py <out_dir> <before|after>

Three shots, each the real widget tree with no tool run:

  <when>_edit_image.png    'Edit image…' - the Sounds box (a ▶ beside each
                           sound, and what the confirm sound actually does)
                           and the dialog's own width
  <when>_menu_settings.png 'Menu settings…' - the Look section, where the
                           menu's HEADING is now typed
  <when>_size_strip.png    the tab after a size check the tool refused: what
                           the strip says about it

A variant of scripts/shot_multiboot_tab.py: same PrintWindow capture, same
DPI-unaware process, same settings backup, and the same two off switches
(PAD_MULTIBOOT_AUTO / PAD_MULTIBOOT_PLAN) so a photograph starts no WSL run.
The modals are separate toplevels, so PrintWindow is pointed at each one's
own GA_ROOT rather than at the app window.

THE IMAGE ROWS ARE EMPTY FILES in a scratch directory.  Nothing here opens a
card: the rows only have to BE there (and be on this machine, or the size
strip says it cannot measure), and the refusal the strip reports is fed to
the same _plan_step the size check's own worker calls.

THE 'BEFORE' HALF RUNS THE SAME FILE AGAINST A TREE THAT HAS NONE OF
PAD-135's CHANGES - `git archive HEAD` into a scratch directory, this script
copied in beside it - so nothing here may name an attribute the old tree
lacks.  It names none: the rows, the two modals and the plan step are all
seams the tab already had.

The two selector frames in this ticket's artifacts (the carousel's arrows and
the menu's heading) are NOT from here - they are the real ARM binary, cross
built out of each tree and rendered under qemu-arm-static.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import wave
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad135bak"

#: The window the shots are taken in - the tab's own README size.
SHOT_W, SHOT_H = 1360, 900

#: The menu the form is filled with: six Beatles images, which is the card
#: C FB was building when he found all this.
IMAGES = [("Abbey Road", "v1.29"), ("Sgt Peppers", "v1.29"),
          ("Beatlemania", "v1.29"), ("Revolver", "v1.29"),
          ("Rubber Soul", "v1.29"), ("The Beatles", "v1.29")]

#: ...and the refusal the compact size check came back with on that card -
#: the tool's own line, out of his log.
PLAN_REFUSAL = (
    "[card] measuring beatles-1_29_0.Abbey.8G.sdcard.raw\n"
    "[card] error: the images' unique content needs 6.42 GB of p3 and the "
    "8G class leaves 6.86 GB after the deltas' work partition - this content "
    "wants a 16G card\n"
    "plan: exit 2\n")

os.makedirs(OUT, exist_ok=True)
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

WORK = tempfile.mkdtemp(prefix="pad135_shot_")
CARDS = os.path.join(WORK, "cards")
os.makedirs(CARDS, exist_ok=True)
PATHS = []
for i, (title, _sub) in enumerate(IMAGES):
    p = os.path.join(CARDS, "beatles-1_29_0.%s.8G.sdcard.raw"
                     % title.replace(" ", ""))
    with open(p, "wb") as f:
        f.write(b"\0" * 4096)
    PATHS.append(p)


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        st = (cfg.setdefault("manufacturers", {})).setdefault("stern", {})
        st["extract_output"] = CARDS
        st["write_assets"] = CARDS
        cfg["last_manufacturer"] = "stern"
        cfg.pop("column_widths", None)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        traceback.print_exc()

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(WORK, "logs")

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


def snap(name, widget=None):
    """PrintWindow the widget's own top-level window into
    ``<when>_<name>.png``.

    THE DESKTOP MAY BE SMALLER THAN THE WINDOW (this box is 1366x768 and the
    tab's shot is 1360x931): Tk only paints what Windows says is visible and
    the DWM surface is black everywhere else, so a window that overhangs is
    walked across the desktop a tile at a time and the on-screen slices are
    pasted into one canvas.  Lifted from scripts/shot_multiboot_tab.py, which
    learned it the hard way on the same desktop.
    """
    path = os.path.join(OUT, "%s_%s.png" % (WHEN, name))
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


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    set_window(SHOT_W, SHOT_H)


@step(5000)
def s_stern():
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(2500)
def s_select():
    try:
        win._update_banner.pack_forget()
    except Exception:
        pass
    win._notebook.select(win._tab_multiboot)


@step(2500)
def s_fill():
    panel = win._multiboot_panel
    panel.new_card()
    for p in PATHS:
        panel.add_image(p)
    for i, (title, sub) in enumerate(IMAGES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    panel._out_var.set(os.path.join(CARDS, "multi",
                                    "beatles-1_29_0.Abbey.8G.sdcard.multi.raw"))
    # A SOUND FILE IN THE ROWS, so the ▶ beside it has something to offer and
    # the shot shows the row in the state the ticket is about (his own
    # 3s_ComeTogether_Snippet.wav, by name).
    # A REAL, PLAYABLE WAV at the format the selector's mixer takes, so the
    # Play button beside it has something to offer rather than a refusal.
    wav = os.path.join(CARDS, "3s_ComeTogether_Snippet.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0" * (4 * 44100 * 2))      # 2 s of silence, stereo
    panel._table.select(0)
    root.update()
    panel._ed_confirm.set(wav)
    panel._table.select(1)
    root.update()
    log("rows=%d confirm=%r" % (len(panel._rows), panel._rows[0].confirm))
    win._resize_notebook_to_current_tab()


@step(1500)
def s_edit_image():
    panel = win._multiboot_panel
    dlg = panel.edit_image(0)
    if dlg is None:
        log("could not open Edit image")
        return
    for _ in range(3):
        root.update()
        time.sleep(0.25)
    log("edit image: %dx%d" % (dlg.top.winfo_width(), dlg.top.winfo_height()))
    snap("edit_image", dlg.top)
    dlg.cancel()
    root.update()


@step(1200)
def s_menu_settings():
    panel = win._multiboot_panel
    dlg = panel.open_menu_settings()
    if dlg is None:
        log("could not open Menu settings")
        return
    for _ in range(3):
        root.update()
        time.sleep(0.25)
    log("menu settings: %dx%d" % (dlg.top.winfo_width(),
                                  dlg.top.winfo_height()))
    snap("menu_settings", dlg.top)
    dlg.cancel()
    root.update()


@step(1200)
def s_size_strip():
    """The size check the tool refused, fed to the panel's own step handler -
    which is what draws the strip."""
    panel = win._multiboot_panel
    panel._plan_step("plan", 2, PLAN_REFUSAL)
    panel._draw_size()
    root.update()
    try:
        log("strip says: %r" % panel._size_detail.cget("text"))
    except Exception:
        traceback.print_exc()
    win._resize_notebook_to_current_tab()
    root.update()
    snap("size_strip")


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
