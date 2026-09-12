"""PAD-130 proof shots: a C string's last bytes read as a pointer INTO an
award line, which invented an editable line the machine never shows and then
refused to rename the real one.

    python scripts/shot_pad130.py <out_dir> <before|after>

``text_tab``
    The Replace Text tab on a project built from the STOCK Godzilla Pro
    1.16 card, with ``MEGALON AWARD`` selected and the tester's own
    replacement typed in.  The search is ``N AWARD`` because that one
    query puts both of the award lines he renamed and the invented
    ``LON AWARD`` in one short list; the before run has that extra row,
    which is a fragment of the line under it that nothing ever draws.
``write_log``
    The real :func:`progtext.plan_writes` run over that same card's game
    program with the tester's three award renames, streamed into the main
    window's log pane.  Before: one of the three is skipped for not ending
    in the fragment.  After: all three land.

Nothing here is staged text -- both screens are the production code paths
over the vendor card image.  The manifest is generated the way
``engine.extract_display_text`` writes its game-program rows (program rows
only: a full radium scan would add minutes and no AWARD row).

Capture mechanics (DPI-unaware process, PrintWindow with
PW_RENDERFULLCONTENT, settings.json backed up and restored, the rolling
session log redirected into the scratch dir) follow
``scripts/take_screenshots.py`` and ``scripts/shot_pad118.py``.
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
if WHEN not in ("before", "after"):
    sys.exit(__doc__)

IMG_DIR = os.environ.get("PAD_SPIKE2_IMG_DIR",
                         r"D:\Pinball\images\Stern\spike2")
CARD = os.path.join(IMG_DIR, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
if not os.path.isfile(CARD):
    sys.exit("Not capturing - no stock Godzilla Pro 1.16 card at %r" % CARD)

# The tester's own edit: three award lines merged into one name.
EDITS = [("MEGALON AWARD", "KAIJU AWARD"),
         ("GIGAN AWARD", "KAIJU AWARD"),
         ("HEDORAH AWARD", "KAIJU AWARD")]
PICK = EDITS[0][0]

SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad130bak"
WORK = tempfile.mkdtemp(prefix="pad130_shot_")
PROJECT = os.path.join(WORK, "GZ Pro 1.16 Heisei")
ELF_CACHE = os.path.join(tempfile.gettempdir(), "pad130_gzpro116.elf")

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# The project folder: the card's game-program rows, written the way the
# extract writes them.  The ELF is cached between the two runs (reading it
# costs a couple of seconds and cannot differ between them).
# ----------------------------------------------------------------------
from pinball_decryptor.core import text_manifest            # noqa: E402
from pinball_decryptor.plugins.stern import progtext        # noqa: E402

if os.path.isfile(ELF_CACHE):
    with open(ELF_CACHE, "rb") as f:
        RAW = f.read()
    log("game program: %s (cached, %d bytes)" % (ELF_CACHE, len(RAW)))
else:
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.info import (_game_elf_bytes,
                                                      _walk_partition)
    with CardImage(CARD) as card:
        part = max((p for p in card.partitions() if p.browsable),
                   key=lambda p: p.size)
        reader = card.reader(part.index)
        RAW = _game_elf_bytes(reader, _walk_partition(reader))
    with open(ELF_CACHE, "wb") as f:
        f.write(RAW)
    log("game program: read from %s (%d bytes)" % (CARD, len(RAW)))

ASSET = "/godzilla_pro/game"
picked = dict(EDITS)
rows = []
for e in progtext.enumerate_program_strings(RAW):
    row = {"path": ASSET, "original": e["text"], "budget": e["budget"],
           "replacement": picked.get(e["text"], "")}
    row["grow" if e.get("growable") else "fixed"] = True
    if not e.get("refs"):
        row["unused"] = True
    rows.append(row)
os.makedirs(PROJECT, exist_ok=True)
text_manifest.save(PROJECT, rows)
log("manifest: %d program row(s), %d of them AWARD lines"
    % (len(rows), sum(1 for r in rows if "AWARD" in r["original"])))

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        st = cfg.setdefault("manufacturers", {}).setdefault("stern", {})
        st["write_assets"] = PROJECT
        st["extract_output"] = PROJECT
        # ... and at this card, so the Write tab names the game the log is
        # about instead of whatever was open last.
        st["extract_input"] = CARD
        st["write_original"] = CARD
        st["write_output"] = os.path.join(WORK, "build")
        cfg["last_manufacturer"] = "stern"
        cfg.pop("column_widths", None)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log("settings backed up + pointed at %s" % PROJECT)
    except Exception:
        traceback.print_exc()

from PIL import Image                                       # noqa: E402

from pinball_decryptor.core import session_log              # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(WORK, "logs")

from pinball_decryptor.app import App                       # noqa: E402

# The update banner is whatever GitHub is serving that minute and it shifts
# the whole window down; a pair has to differ only in the change under test.
App._check_for_update = lambda self: None

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
GEOM = None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


app = App()
root = app.root
win = app.window


def snap(name):
    # Re-assert the geometry inside snap(): the app re-sizes itself to the
    # active tab on an idle callback that fires at a different moment in
    # each run, and a before/after pair has to be pixel-comparable.
    for _ in range(2):
        if GEOM:
            root.geometry(GEOM)
        root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)           # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)                      # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h                       # top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_win)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    path = os.path.join(OUT, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def clear_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is None:
        return
    t.configure(state=tk.NORMAL)
    t.delete("1.0", tk.END)
    t.configure(state=tk.DISABLED)


def tail_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is not None:
        t.see(tk.END)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(600)
def s_geometry():
    global GEOM
    w = min(1500, root.winfo_screenwidth() - 60)
    h = min(820, root.winfo_screenheight() - 90)
    GEOM = "%dx%d+30+30" % (w, h)
    root.geometry(GEOM)


@step(5000)
def s_text_tab():
    win._notebook.select(win._tab_text)


@step(3500)
def s_filter():
    win.text_search_var.set("N AWARD")


@step(2500)
def s_select_the_award_line():
    tree = win._text_tree
    log("rows shown: %d" % len(tree.get_children("")))
    for i, r in enumerate(win._text_rows):
        if r["original"] == PICK:
            iid = str(i)
            if tree.exists(iid):
                tree.see(iid)
                tree.focus(iid)
                tree.selection_set(iid)
                log("selected %r" % PICK)
            return
    log("!! %r is not in the manifest" % PICK)


@step(1500)
def s_text_snap():
    snap("text_tab")


@step(600)
def s_write_tab():
    win._notebook.select(win._tab_write)


@step(2500)
def s_plan():
    """The real planner over the real card, into the real log pane."""
    clear_log()
    win.append_log("Write: planning the game program's text edits for %s ..."
                   % PROJECT, "info")
    progtext.plan_writes(RAW, dict(EDITS), win.append_log)
    tail_log()


@step(2500)
def s_write_snap():
    tail_log()
    snap("write_log")


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
        if os.path.exists(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
            log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
    shutil.rmtree(WORK, ignore_errors=True)
