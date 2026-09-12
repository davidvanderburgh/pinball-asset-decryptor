"""Capture a Multi-boot PREVIEW whose art comes from a clip no decoder
here can read (PAD-132).

    python scripts/shot_pad132.py <out.png> [--show TEXT] [--seconds N]

A variant of shot_pad126.py (same PrintWindow, same DPI-unaware capture,
same settings backup, same real run) for the fault a user reported on
2026-09-11: the second image of his menu took its picture from an .mp4
whose video track is stored under a four-character code his ffmpeg has no
decoder for, and the media step ended on ffmpeg's own words -

    refused: ffmpeg scale failed (rc 234): [vist#0:0/none @ ...] Decoding
    requested, but no decoder found for: none | ...

which name neither the clip nor anything he could do about it.

THE RUN IS REAL, and so is the unreadable clip.  Two cards off this
machine go into the form and the preview's own method is called; what is
ARRANGED is the clip:

  * C:\\tmp\\PAD-132\\Godzilla Classic Victory.mp4 is built here by ffmpeg
    and then has the four characters that name its format ('avc1')
    overwritten with nonsense ('zzq1').  The file stays a valid MP4 whose
    picture bytes are real H.264; only the NAME of the format is one no
    ffmpeg knows, which is exactly what a clip with no decoder looks like
    from the outside.  Nothing on the machine is changed.

So the before/after pair is the same machine, the same cards, the same
clip and the same button: the old run ends on a line of ffmpeg noise, the
new one on a sentence naming the file and the format in it.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = list(sys.argv[1:])


def _opt(name, default=""):
    if name in ARGS:
        i = ARGS.index(name)
        val = ARGS[i + 1]
        del ARGS[i:i + 2]
        return val
    return default


SHOW = _opt("--show", "Preview failed")
SECONDS = int(_opt("--seconds", "300"))
OUT = os.path.abspath(ARGS[0] if ARGS else "multiboot-art-clip.png")

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak132"

#: The two cards the menu is made of.  Both are read, never written.
IMAGES = [
    r"D:\Pinball\images\Stern\spike2\Godzilla Premium 1.16 Heisei Custom V1.5 Orchestral Edition.raw",
    r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw",
]
TITLES = [("Heisei Custom", "V1.5 Orchestral Edition"),
          ("Godzilla Pro", "Stern 1.16.0")]

#: The clip image 1 takes its picture from - the arranged fault.
WORK = r"C:\tmp\PAD-132"
CLIP = os.path.join(WORK, "Godzilla Classic Victory.mp4")

#: Where the card would go.  A scratch path, and it must not exist.
CARD_OUT = os.path.join(WORK, "build", "godzilla-multi.16G.sdcard.raw")

#: Tall enough for the tab AND a readable Log under it: the run's own
#: lines are the point of the picture.
SHOT_W, SHOT_H = 1360, 1180

#: No automatic runs behind the photograph - this rig starts exactly one,
#: by calling the preview's own method.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
#: ...in the user's own distro, which is where his ffmpeg is.
os.environ["PAD_RUNTIME"] = "0"


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc),
              flush=True)


def make_clip():
    """Build the unreadable clip, unless it is already there."""
    if os.path.isfile(CLIP):
        log("clip: %s (already there)" % CLIP)
        return
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("no ffmpeg on PATH to build the clip with")
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=1280x720:rate=25",
                    "-pix_fmt", "yuv420p", CLIP], check=True)
    with open(CLIP, "rb") as f:
        data = f.read()
    with open(CLIP, "wb") as f:
        f.write(data.replace(b"avc1", b"zzq1"))
    log("clip: %s (%d bytes, format tag avc1 -> zzq1)" % (CLIP, len(data)))


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.makedirs(os.path.dirname(CARD_OUT), exist_ok=True)
if os.path.exists(CARD_OUT):
    os.remove(CARD_OUT)
make_clip()

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
    """shot_pad126.py's capture, tiles and all: the window is taller than
    this desktop on purpose, and Tk only paints what Windows says is
    visible, so it is walked across the screen a tile at a time."""
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
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def show_in_log(text):
    """Scroll the app's Log pane so the last line holding *text* is the
    last one visible - the scrollbar, driven from here."""
    if not text:
        return
    widget = getattr(win, "_log_text", None)
    if widget is None:
        log("no log pane to scroll")
        return
    root.update_idletasks()
    widget.see = lambda *_a, **_kw: None
    hit = widget.search(text, "end", backwards=True, nocase=False)
    if not hit:
        log("log has no %r to scroll to" % text)
        return
    line = int(str(hit).split(".")[0])
    total = int(str(widget.index("end-1c")).split(".")[0])
    rows = max(1, int(widget.cget("height")))
    top = max(0, line - rows + 1)
    widget.yview_moveto(top / float(max(1, total)))
    log("log scrolled to line %d of %d (%r)" % (line, total, text))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    root.maxsize(max(SHOT_W, root.winfo_screenwidth()) + 100,
                 max(SHOT_H, root.winfo_screenheight()) + 100)
    root.geometry("%dx%d+40+40" % (SHOT_W, SHOT_H))


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
    """The form, through the panel's public seams - the same ones
    tests/test_multiboot_tab.py fills it with.  FROM EMPTY: the tab
    remembers its last form per project, and add_image appends."""
    panel = win._multiboot_panel
    panel.new_card()
    for path in IMAGES:
        if not os.path.isfile(path):
            log("MISSING image %s" % path)
        panel.add_image(path)
    for i, (title, sub) in enumerate(TITLES):
        panel._table.select(i)
        root.update()
        panel._ed_title.set(title)
        panel._ed_sub.set(sub)
    # IMAGE 1 TAKES ITS PICTURE FROM THE CLIP - a typed video path, which
    # is 'art = <video>@<seconds>' to the tool.  Image 0 keeps its own
    # logo off the card, exactly as the reporter's first image did.
    panel._rows[1].art = CLIP
    panel._rows[1].art_time = "0"
    panel._refresh_tree(select=1)
    panel._out_var.set(CARD_OUT)
    root.update()
    log("row 1 art: %r" % panel._rows[1].art)
    log("card out: %s" % panel._out_var.get())


@step(1500)
def s_preview():
    """Press it.  render_preview is what 'Redraw the preview now' calls."""
    panel = win._multiboot_panel
    log("preview started: %s" % panel.render_preview())


@step(500)
def s_wait_and_snap():
    """Wait on the tab's own state, then photograph the window.  A media
    step that cannot read a clip ends by itself in seconds."""
    panel = win._multiboot_panel
    deadline = time.time() + SECONDS

    def busy():
        return bool(getattr(panel, "_busy", False)
                    or getattr(panel, "_pv_busy", False))

    def poll():
        if not busy() or time.time() > deadline:
            lines = panel.log_lines()
            log("run finished=%s lines=%d" % (not busy(), len(lines)))
            for ln in lines[-40:]:
                log("   | %s" % ln)
            log("status: %r" % panel.message())
            show_in_log(SHOW)
            root.update_idletasks()
            snap(OUT)
            if busy():
                log("cancelling the run: %s" % panel.cancel_run())
                root.after(4000, root.destroy)
            else:
                root.after(500, root.destroy)
            return
        root.after(500, poll)

    poll()


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


root.after((SECONDS + 60) * 1000, lambda: root.destroy())
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
