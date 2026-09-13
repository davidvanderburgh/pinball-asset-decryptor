"""Capture a Multi-boot BUILD RUN on a machine whose guest filesystem
belongs to root (PAD-140).

    python scripts/shot_pad140.py <out.png> [--stop-at TEXT] [--show TEXT]
                                            [--seconds N]

A variant of shot_pad126.py (same PrintWindow, same DPI-unaware capture,
same settings backup, same real run) for the fault a user reported on
2026-09-12: his first multi-boot Build stopped on

    [build]   install: cannot change permissions of
              '/home/home/spike2root/usr/local/codeselect': No such file or directory
    [selector] error: the boot menu program could not be built - see the lines above.

The app's own emulator Start runs as root (`wsl -u root`, PAD_PIVOT) and
unpacks ~/spike2root with debugfs as root, so the whole guest filesystem is
root's.  The Multi-boot tab's selector step ran as the USER, and a user
cannot create /usr/local/codeselect inside a directory root owns - coreutils'
`install -d` reports the failed mkdir as the stat that followed it.

THE RUN IS REAL, and so is the ownership.  Two card images off this machine
go into the form and the green button's own method is called; the one thing
ARRANGED is the fault:

  * ~/pad140root is a guest filesystem that belongs to root: this machine's
    own /usr/include, /usr/lib and /lib copied out of ~/spike2root by root
    (the real one is read, never written), and an empty root-owned
    /usr/local.  PAD_MULTIBOOT_SELECTOR points the tab at it - the rig's own
    knob, and a rootfs-shaped directory, so the tab installs into it exactly
    as it would into ~/spike2root.  Deleted afterwards.

So the before/after pair is the same machine, the same card and the same
button: the old build stops on coreutils' misleading line, the new one
installs the menu program and moves on to the plan.
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


STOP_AT = _opt("--stop-at")
SHOW = _opt("--show")
SECONDS = int(_opt("--seconds", "240"))
OUT = os.path.abspath(ARGS[0] if ARGS else "multiboot-rootowned.png")

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak140"

#: The card the menu is built from, and the second image on it.  Both are
#: read, never written (the tools refuse an output under the library).
IMAGES = [
    r"D:\Pinball\images\Stern\spike2\turtles_pro-1_59_0.Release.8G.sdcard.raw",
    r"D:\Pinball\TMNT 1987\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw",
]
TITLES = [("STERN 1.59.0", "Original Stern code"),
          ("TMNT 1987", "1987 cartoon upscale")]

#: Where the card would go.  A scratch path, and it must not exist: an
#: existing file puts a confirmation in front of the run.
CARD_OUT = r"C:\tmp\PAD-140\build\turtles-multi.16G.sdcard.raw"

#: THE FAULT: a rootfs that belongs to root, beside the real one.
SCRATCH = "pad140root"
SELECTOR = "~/%s/usr/local/codeselect" % SCRATCH

ARRANGE = r"""
set -e
H=$1
src=$H/spike2root
dst=$H/%s
rm -rf "$dst"
mkdir -p "$dst/usr/local"
cp -a "$src/usr/include" "$src/usr/lib" "$dst/usr/"
cp -a "$src/lib" "$dst/"
chown -R root:root "$dst"
chmod 755 "$dst" "$dst/usr" "$dst/usr/local"
echo "arranged: $(stat -c '%%U' "$dst/usr/local") owns $dst/usr/local," \
     "$(du -sh "$dst" | cut -f1)"
""" % SCRATCH

REPORT = r"""
H=$1
d=$H/%s/usr/local/codeselect
if [ -e "$d" ]; then
  echo "after the run: $(stat -c '%%U' "$d") owns $d:" $(ls "$d")
else
  echo "after the run: no $d"
fi
""" % SCRATCH

RESTORE = r"""
H=$1
rm -rf "$H/%s"
[ -e "$H/%s" ] && echo "restore: STILL THERE" || echo "restored: scratch rootfs removed"
""" % (SCRATCH, SCRATCH)

#: Tall enough for the tab AND a readable Log under it: the run's own
#: lines are the point of the picture.
SHOT_W, SHOT_H = 1360, 1180

#: No automatic runs behind the photograph - the size check and the
#: preview both shell out to WSL, and this rig starts exactly one run.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
#: The reporter's own Ubuntu, not the PAD Runtime image (shot_pad126.py).
os.environ["PAD_RUNTIME"] = "0"
os.environ["PAD_MULTIBOOT_SELECTOR"] = SELECTOR


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc),
              flush=True)


def wsl_home():
    out = subprocess.run(["wsl.exe", "-e", "bash", "-lc", "echo $HOME"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return out.stdout.decode("utf-8", "replace").strip()


def as_root(script, home):
    """Run one shell script as root in the default distro, the desktop
    home as $1, and log what it said."""
    out = subprocess.run(["wsl.exe", "-u", "root", "-e", "bash", "-c",
                          script, "pad140", home],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log(out.stdout.decode("utf-8", "replace").strip())
    return out.returncode


HOME = wsl_home()
if not HOME.startswith("/"):
    sys.exit("cannot read the WSL home (%r)" % HOME)

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.makedirs(os.path.dirname(CARD_OUT), exist_ok=True)
if os.path.exists(CARD_OUT):
    os.remove(CARD_OUT)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

if as_root(ARRANGE, HOME) != 0:
    sys.exit("could not arrange the root-owned rootfs")

from PIL import Image  # noqa: E402

from pinball_decryptor.gui import multiboot_tab  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402

#: THE RUN STOPS AT THE PLAN.  The selector step is the whole subject, and
#: the plan after it is the proof the run moved on; the build (a 16 GB card,
#: as root) and the verify never belong in a photograph of this.
_orig_build_commands = multiboot_tab.build_commands


def _selector_and_plan_only(*a, **kw):
    return [c for c in _orig_build_commands(*a, **kw)
            if c[0] in ("selector", "plan")]


multiboot_tab.build_commands = _selector_and_plan_only

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
    """shot_pad126.py's capture, tiles and all."""
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
    last one visible."""
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
    """The form, through the panel's public seams, FROM EMPTY."""
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
    panel._out_var.set(CARD_OUT)
    # AFTER new_card(): the tab restores the project's saved form, selector
    # directory included, over the environment's default - the first run of
    # this rig built against the real ~/spike2root because of it.
    panel._selector_var.set(SELECTOR)
    root.update()
    log("selector dir: %s" % panel._selector_var.get())
    log("card out: %s" % panel._out_var.get())


@step(1500)
def s_build():
    """Press it.  _build_card is what the green button's modal calls -
    and only when the form really names the scratch rootfs."""
    panel = win._multiboot_panel
    sel = panel.form().selector_dir
    log("selector dir at press: %s" % sel)
    if sel != SELECTOR:
        log("REFUSING to press Build: the form names %r, not %r" % (sel, SELECTOR))
        root.after(500, root.destroy)
        return
    log("build started: %s" % panel._build_card())


@step(500)
def s_wait_and_snap():
    """Wait on the tab's own state, then photograph the window."""
    panel = win._multiboot_panel
    deadline = time.time() + SECONDS

    def poll():
        lines = panel.log_lines()
        hit = STOP_AT and any(STOP_AT in ln for ln in lines)
        if not panel._busy or hit or time.time() > deadline:
            log("run finished=%s hit=%s lines=%d"
                % (not panel._busy, bool(hit), len(lines)))
            for ln in lines[-40:]:
                log("   | %s" % ln)
            log("status: %r" % panel.message())
            show_in_log(SHOW)
            root.update_idletasks()
            snap(OUT)
            if panel._busy:
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
    # WHAT THE RUN LEFT, then THE MACHINE PUT BACK, whatever happened above.
    try:
        as_root(REPORT, HOME)
        as_root(RESTORE, HOME)
    except Exception:
        log("restore FAILED:\n%s" % traceback.format_exc())
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
