"""Capture a Multi-boot BUILD RUN on a machine with no `make` (PAD-126).

    python scripts/shot_pad126.py <out.png> [--stop-at TEXT] [--show TEXT]
                                            [--seconds N]

A variant of shot_multiboot_selector.py (same PrintWindow, same
DPI-unaware capture, same settings backup, same real run) for the fault
a user reported on 2026-09-10: the boot menu program is built by a
Makefile, `make` is on no prerequisite list anywhere, and a WSL without
it answered Build with the shell's own words -

    [build] .../buildselect.sh: line 78: make: command not found
    [build] build FAILED, and a PAD_SELECT run has no menu without it.

with nothing in the run, the tab or the app naming a package to install.

THE RUN IS REAL, and so is the missing tool.  Two card images off this
machine go into the form and the green button's own method is called;
the two things ARRANGED are the fault:

  * `make` is hidden from the run - /tmp/pad126nomake is a directory of
    symlinks to every command on this distro EXCEPT that one, and the
    selector step is run with it as its whole PATH.  Nothing is
    uninstalled: the machine is untouched and the directory is deleted
    afterwards.
  * the installed menu program is moved aside (and moved back at the
    end), because a machine that already has one never builds it - which
    is every machine that has run the emulator once, including this one.

So the before/after pair is the same machine, the same card and the same
button: the old build stops on a line of shell noise, the new one stops
on a sentence naming the package.
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
OUT = os.path.abspath(ARGS[0] if ARGS else "multiboot-nomake.png")

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak126"

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
CARD_OUT = r"C:\tmp\PAD-126\build\turtles-multi.16G.sdcard.raw"

#: THE FAULT.  A PATH with every command on this distro in it except the
#: one this ticket is about, and the menu program moved out of the way so
#: the build is actually attempted.
NOMAKE = "/tmp/pad126nomake"
STASH = "/tmp/pad126_codeselect.bak"
SEL_BIN = "$HOME/spike2root/usr/local/codeselect/codeselect"

ARRANGE = r"""
d=%s
rm -rf "$d"; mkdir -p "$d"
for dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
  [ -d "$dir" ] || continue
  for f in "$dir"/*; do
    b=${f##*/}
    [ "$b" = make ] && continue
    [ -e "$d/$b" ] || ln -s "$f" "$d/$b" 2>/dev/null
  done
done
bin=%s
[ -f "$bin" ] && mv -f "$bin" %s
echo "arranged: make=$(PATH=$d command -v make || echo hidden)" \
     "menu=$([ -f "$bin" ] && echo still-there || echo moved-aside)" \
     "commands=$(ls "$d" | wc -l)"
""" % (NOMAKE, SEL_BIN, STASH)

RESTORE = r"""
bin=%s
[ -f %s ] && mv -f %s "$bin"
rm -rf %s
echo "restored: menu=$([ -x "$bin" ] && echo back || echo MISSING)"
""" % (SEL_BIN, STASH, STASH, NOMAKE)

#: Tall enough for the tab AND a readable Log under it: the run's own
#: lines are the point of the picture.
SHOT_W, SHOT_H = 1360, 1180

#: No automatic runs behind the photograph - the size check and the
#: preview both shell out to WSL, and this rig starts exactly one run.
os.environ["PAD_MULTIBOOT_AUTO"] = "0"
os.environ["PAD_MULTIBOOT_PLAN"] = "0"
#: AND THE RUN GOES INTO THE USER'S OWN DISTRO, which is the machine this
#: ticket is about.  The PAD Runtime image installs `make` itself
#: (tools/runtime/Dockerfile), so a run routed there could never show the
#: fault; the reporter's log is his own Ubuntu, and so is this one.
os.environ["PAD_RUNTIME"] = "0"


def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "backslashreplace").decode(enc),
              flush=True)


def in_wsl(script):
    """Run one shell script in the default distro and log what it said."""
    out = subprocess.run(["wsl.exe", "-e", "bash", "-lc", script],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log(out.stdout.decode("utf-8", "replace").strip())
    return out.returncode


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.makedirs(os.path.dirname(CARD_OUT), exist_ok=True)
if os.path.exists(CARD_OUT):
    os.remove(CARD_OUT)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.isfile(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

in_wsl(ARRANGE)

from PIL import Image  # noqa: E402

from pinball_decryptor.gui import multiboot_tab  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402

#: THE SELECTOR STEP, RUN WITHOUT `make` ON ITS PATH.  The step's own
#: command line is untouched otherwise - this is the same ensureselect.sh
#: run the tab always does, on a machine that happens not to have the
#: tool.
_orig_selector_line = multiboot_tab.install_selector_line


def _nomake_selector_line(*a, **kw):
    return "PATH=%s %s" % (NOMAKE, _orig_selector_line(*a, **kw))


multiboot_tab.install_selector_line = _nomake_selector_line

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
    """shot_multiboot_selector.py's capture, tiles and all: the window is
    taller than this desktop on purpose, and Tk only paints what Windows
    says is visible, so it is walked across the screen a tile at a time."""
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
    panel._out_var.set(CARD_OUT)
    root.update()
    log("selector dir: %s" % panel._selector_var.get())
    log("card out: %s" % panel._out_var.get())


@step(1500)
def s_build():
    """Press it.  _build_card is what the green button's modal calls."""
    panel = win._multiboot_panel
    log("selector dir at press: %s" % panel.form().selector_dir)
    log("build started: %s" % panel._build_card())


@step(500)
def s_wait_and_snap():
    """Wait on the tab's own state, then photograph the window.  A build
    that cannot make its menu program ends by itself in seconds."""
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
    # THE MACHINE IS PUT BACK, whatever happened above: the menu program
    # returns to the rootfs and the PATH directory is deleted.
    try:
        in_wsl(RESTORE)
    except Exception:
        log("restore FAILED:\n%s" % traceback.format_exc())
    try:
        if os.path.isfile(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
