"""Capture the Images tab right after *Clear replacements…* for PAD-142.

    python scripts/shot_pad142.py <out.png>

Field report, 2026-09-13, on v0.212.3: *"I HAVE cleared all replacements but note
that the replacement is still showing in the list. I also noticed that when I
first did this it didn't seem to 'take'. The replacement was still in."*

His screenshot is the Images tab after the clear: the button greyed, and his
PlayerScore row still reading ``✓ changed on disk (Godzilla_Player1_Gunmetal_
v1_1920x316.png)`` with his artwork in the Replacement pane.  The pick was
gone; the bytes were not.  He never pressed Build - Start with "Apply my
replaced assets on top" had applied the pick into the project folder
(PAD-121), and a clear only ever dropped the pick.

So the shot replays exactly that, with the app's own code at each step: pick a
replacement, apply it the way Start does (``App.stage_pending_replacements``,
which writes the slot AND its ``.orig`` snapshot), press Clear replacements…,
then photograph the row.  The console says what the emulator's next Start
would find changed in the folder, which is the "didn't take" half.

A SYNTHETIC PROJECT FOLDER, rebuilt from nothing on every run: the run writes
into it (the apply), so a before shot would otherwise hand its state to the
after shot.  Never point this at a real extract.
"""
import ctypes
import json
import os
import shutil
import sys
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                      else "images-clear-applied.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = r"c:\tmp\pad142"
PROJ = os.path.join(DATA, "proj")
MODS = os.path.join(DATA, "mods")
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad142bak"

#: His slot and his file, from his screenshot.
SLOT = "images/scene_textures/radimg_PlayerScore_1920x316_3d8c5f15.png"
MOD = "Godzilla_Player1_Gunmetal_v1_1920x316.png"
#: His search box, so the rows in the pair are the ones in his shot.
SEARCH = "1920"

SLOTS = [
    ("images/scene_textures", "radimg_1920x1080_1af83a7b", (1920, 1080)),
    ("images/scene_textures", "radimg_PlayerScore_1920x316_076942d5",
     (1920, 316)),
    ("images/scene_textures", "radimg_PlayerScore_1920x316_3d8c5f15",
     (1920, 316)),
    ("images/scene_textures", "radimg_PlayerScore_1920x316_5096f2e7",
     (1920, 316)),
    ("images/scene_textures", "radimg_PlayerScore_1920x316_f22bb141",
     (1920, 316)),
    ("images/attract", "gz_logo_main", (640, 360)),
    ("images/attract", "attract_bg_city", (1280, 720)),
    ("images/hud", "hud_ball_1", (96, 96)),
    ("images/hud", "hud_multiball", (256, 96)),
    ("images/modes", "mode_mechagodzilla_card", (800, 480)),
]

GEOM = "1180x900+0+0"


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def log(msg):
    print(msg, flush=True)


def build_data():
    """A fresh Stern-shaped folder with a baseline, and his replacement."""
    from PIL import Image, ImageDraw
    shutil.rmtree(DATA, ignore_errors=True)

    def draw(path, size, text, fill, bar):
        img = Image.new("RGB", size, fill)
        d = ImageDraw.Draw(img)
        h = size[1]
        d.rectangle([0, h // 3, size[0] - 1, 2 * h // 3], fill=bar)
        d.text((12, 12), text, fill=(245, 245, 245))
        img.save(path)

    for sub, name, size in SLOTS:
        d = os.path.join(PROJ, sub.replace("/", os.sep))
        os.makedirs(d, exist_ok=True)
        draw(os.path.join(d, name + ".png"), size, name, (18, 18, 22),
             (110, 110, 118))
    os.makedirs(MODS, exist_ok=True)
    draw(os.path.join(MODS, MOD), (1920, 316), MOD, (10, 10, 12),
         (205, 140, 40))
    from pinball_decryptor.core import checksums
    n = checksums.generate_checksums(PROJ)
    log("synthetic project %s: %d baselined files" % (PROJ, n))


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)
build_data()

# A fresh rolling-log dir per run: the log pane preloads earlier sessions.
from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(DATA, "logs")
os.makedirs(session_log.LOG_DIR_OVERRIDE, exist_ok=True)

shutil.copy2(SETTINGS, SETTINGS_BAK)
with open(SETTINGS, encoding="utf-8") as f:
    _cfg = json.load(f)
_stern = _cfg.setdefault("manufacturers", {}).setdefault("stern", {})
_stern["extract_output"] = PROJ
_stern["write_assets"] = PROJ
_cfg["last_manufacturer"] = "stern"
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(_cfg, f, indent=2)
log("settings pointed at %s (backup %s)" % (PROJ, SETTINGS_BAK))

import tkinter as tk  # noqa: E402

from PIL import Image  # noqa: E402

import pinball_decryptor.app as _appmod  # noqa: E402
from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.core import checksums, staged_originals  # noqa: E402
from pinball_decryptor.gui import main_window as mw  # noqa: E402

# No update banner: a release published mid-run would put a strip in one shot
# of the pair and not the other.
_appmod.check_for_update = lambda *_a, **_kw: None

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


def snap(path):
    # Re-assert the geometry inside the snap (PAD-60: the notebook's own idle
    # resize lands at a different moment in each run).
    for _ in range(2):
        root.geometry(GEOM)
        root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)  # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h  # top-down
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
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def folder_still_changed():
    """What a build, or the emulator's next Start, reads as edited."""
    base = checksums.read_baseline_any(PROJ)
    return sorted(checksums.changed_rels(
        PROJ, [s.rel_path for s in win._image_slots], baseline=base))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    global GEOM
    # This desk's DPI-unaware screen is small; a window bigger than it comes
    # back with black edges.
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    GEOM = "%dx%d+0+0" % (min(1180, sw - 8), min(900, sh - 48))
    log("screen %dx%d -> geometry %s" % (sw, sh, GEOM))
    root.geometry(GEOM)


@step(8000)
def s_image_tab():
    """The tab's own visibility hook starts the scan."""
    win._notebook.select(win._tab_image)


@step(6000)
def s_pick_then_start():
    if SLOT not in win._image_slots_by_rel:
        log("  no slot %s - scanned %d" % (SLOT, len(win._image_slots)))
        return
    win._image_assignments[SLOT] = os.path.join(MODS, MOD)
    win._save_staged_changes()
    win._refresh_image_list()
    # Start with "Apply my replaced assets on top" ticked: the emulator
    # panel's stage_fn is this very call (PAD-121).
    pending, staged, failures = app.stage_pending_replacements(PROJ)
    log("Start applied the picks: pending=%d staged=%d failures=%r"
        % (pending, staged, failures))
    log("  .orig snapshot now: %s"
        % staged_originals.snapshot_path(PROJ, SLOT))
    win._start_change_scan("image")


@step(3000)
def s_clear_all():
    log("before the clear: picks=%d changed on disk=%s  button=%s"
        % (len(win._image_assignments), sorted(win._image_changed_on_disk),
           win._clear_all_btns["image"].cget("state")))

    def _ask(title, msg, **_k):
        log("CONFIRM %r:\n%s" % (title, msg))
        return True
    mw.messagebox.askyesno = _ask
    mw.messagebox.showinfo = lambda t, m, **_k: log("INFO %r: %s" % (t, m))
    win._clear_all_replacements("image")


@step(3000)
def s_show_row():
    win.image_search_var.set(SEARCH)
    root.update_idletasks()
    tree = win._image_tree
    if tree.exists(SLOT):
        tree.selection_set(SLOT)
        tree.see(SLOT)
        win._image_render_preview(SLOT)
        log("row Replacement cell: %r" % (tree.item(SLOT, "values")[-1],))
    log("after the clear: picks=%d changed on disk=%s  button=%s"
        % (len(win._image_assignments), sorted(win._image_changed_on_disk),
           win._clear_all_btns["image"].cget("state")))
    log("the folder still differs from the extract in: %s"
        % (folder_still_changed() or "nothing"))


@step(2500)
def s_snap():
    snap(OUT)


def run_steps(i=0):
    if i >= len(STEPS):
        root.after(300, root.destroy)
        return
    delay, fn = STEPS[i]

    def _go():
        try:
            fn()
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
        run_steps(i + 1)

    root.after(delay, _go)


try:
    run_steps()
    root.mainloop()
finally:
    shutil.move(SETTINGS_BAK, SETTINGS)
    log("settings restored")
