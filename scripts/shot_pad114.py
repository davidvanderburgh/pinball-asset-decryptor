"""PAD-114 proof shot: what the Multi-boot tab's log says when the build step
resolves its root command on a distro whose default account is root.

The tester's WSL logs in as root (every path in his run is under /root:
/root/spike2root, /root/emusrc).  Selector, media, preview and plan all ran,
and then the build - the one step that must be root - refused with "cannot
find your WSL home ... check that WSL starts", on a WSL that plainly starts.

The shot drives the REAL step: the tab's own build_commands() is asked for its
'build' entry and that callable is resolved exactly the way the worker
resolves it (MultibootPanel._start_worker), with the home probe pinned to the
tester's machine - no desktop user, root's own home.  Whatever the production
code says lands in the app's Log pane.

    python scripts/shot_pad114.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up) follow
scripts/take_screenshots.py -- see its header for why they are what they are.
"""
import ctypes
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad114bak"

#: The tab drives the selector and the size check under WSL whenever a field
#: changes; a photograph must start neither.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"

#: His card, near enough: his own Heisei build and the stock Godzilla code,
#: both in David's library.  Only the argv is being photographed, so the
#: images are read for their titles and nothing else.
LIB = os.path.join("D:", os.sep, "Pinball", "images", "Stern", "spike2")
IMAGES = [
    (os.path.join(LIB, "Godzilla Premium 1.16 Heisei Custom "
                       "V1.5 Standard Edition.raw"), "GODZILLA HEISEI"),
    (os.path.join(LIB, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"),
     "STERN 1.16.0"),
]

os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

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


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc), flush=True)


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


def snap(name):
    """The whole window, tiled across the desktop when it is taller than the
    screen - this shot needs the tall Multi-boot tab AND the Log pane under
    it, and Tk paints only what Windows says is visible (the rest comes back
    black).  Same walk shot_multiboot_tab.py uses, for the same reason."""
    import time
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
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
    img.save(os.path.join(OUT, name))
    log("snapped %s (%dx%d)" % (name, img.width, img.height))


def clear_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is None:
        return
    t.configure(state=tk.NORMAL)
    t.delete("1.0", tk.END)
    t.configure(state=tk.DISABLED)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


#: The tall Multi-boot tab plus room for the Log under it.  Taller than
#: David's desktop on purpose - snap() walks the window across it.
SHOT_W, SHOT_H = 944, 1080


@step(600)
def s_enter():
    w = min(SHOT_W, root.winfo_screenwidth() - 80)
    root.maxsize(max(w, root.winfo_screenwidth()) + 100,
                 max(SHOT_H, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (w, SHOT_H))
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


@step(4000)
def s_tab():
    try:
        win._update_banner.pack_forget()
    except Exception:                                   # noqa: BLE001
        pass
    win._notebook.select(win._tab_multiboot)


@step(2000)
def s_fill():
    """Two images in the tab, the way a user puts them there.  No action
    button is pressed: every one of them runs a tool under WSL."""
    panel = win._multiboot_panel
    panel.new_card()
    for path, title in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s" % path)
        panel.add_image(path)
    for i, (_path, title) in enumerate(IMAGES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
    panel._table.select(0)
    win._resize_notebook_to_current_tab()
    log("rows: %d  out=%r" % (len(panel._rows), panel._out_var.get()))


@step(1500)
def s_build_step():
    """HIS MACHINE, in one line: no desktop user, root's own home.  Then the
    build step is resolved exactly as MultibootPanel._start_worker resolves a
    callable step, and whatever the production code produces goes into the
    Log.  ``_write`` rather than ``_append``: the worker's queue is drained
    only while a run is up, and _write is the main-loop half it drains to -
    the same line, on the thread this rig is already on."""
    panel = win._multiboot_panel
    multiboot_tab.wsl_home = lambda: None
    if hasattr(multiboot_tab, "wsl_account"):
        multiboot_tab.wsl_account = lambda: ("root", "/root")
    else:
        log("this build has no wsl_account() - the pre-fix code")
    clear_log()
    cmds = dict(multiboot_tab.build_commands(panel.form()))
    argv = cmds["build"]
    if callable(argv):
        try:
            argv = argv({})
        except Exception as exc:                        # noqa: BLE001
            panel._write("[multi-boot] %s: %s" % ("build", exc))
            log("build step REFUSED: %s" % exc)
            return
    panel._write("$ " + argv[-1])
    log("build step argv head: %s" % argv[:8])


@step(1500)
def s_snap():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)
    root.update()
    snap("%s_multiboot_build_root.png" % WHEN)


@step(600)
def s_done():
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            log("step %d: %s" % (i, fn.__name__))
            fn()
        except Exception:                               # noqa: BLE001
            log("step %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))
        run(i + 1)

    root.after(delay, _go)


root.after(90000, lambda: root.destroy())
run()
try:
    app.run()
finally:
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:                                   # noqa: BLE001
        log("settings restore FAILED:\n%s" % traceback.format_exc())
