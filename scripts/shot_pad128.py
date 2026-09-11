"""Capture the Replace Image tab's bulk-clear controls for PAD-128.

    python scripts/shot_pad128.py <out.png>

DragonRR, 2026-09-11: *"We could do with a 'clear all' replacements button -
or an ability to select a series/group by highlighting and right click - clear
replacement. I currently have 48 replacements - I can order by replacements
which is good but I would have to clear each one individually."*

So the shot is that exact screen: the Images tab sorted by Replacement with
every pick at the top, and the two controls that were missing - a highlighted
RANGE of rows (the tree was ``selectmode="browse"``, which cannot hold one)
and the *Clear replacements…* button on the project-folder row.

WHY A SYNTHETIC PROJECT FOLDER.  There is no extract on this box any more,
and a capture run must never write into a real one: picking a replacement
persists it into the folder's own ``.staged_changes.json``.  ``c:\\tmp\\pad128``
is built by ``mkdata.py`` beside this script's own notes - 72 Stern-shaped
image slots and eight replacement PNGs - and the run leaves its picks there.

THE RANGE IS SELECTED WITH REAL CLICKS, not ``selection_set``: Tk's
``browse`` restriction lives in the default BINDINGS, so a programmatic
``selection_set(a, b, c)`` highlights three rows in both trees and the
before/after pair would be a lie.  A Button-1 then a Shift-Button-1 through
``event_generate`` is what a user does, and it is what tells the two modes
apart.  The clicks land in column #0 on purpose - a click in the Replacement
column opens the file picker (``_image_on_tree_click``).
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
                      else "replace-images-clear.png")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = r"c:\tmp\pad128"
PROJ = os.path.join(DATA, "proj")
MODS = os.path.join(DATA, "mods")
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad128bak"

#: Which slots get a pick, and what with.  Spread across the folders so the
#: sorted-by-Replacement view is a believable mid-project one.
PICKS = [
    ("images/attract/gz_logo_main.png", "my_godzilla_logo.png"),
    ("images/attract/attract_bg_skyline.png", "skyline_night.png"),
    ("images/modes/mode_mechagodzilla_card.png", "burning_godzilla.png"),
    ("images/modes/mode_heisei_card.png", "heisei_card.png"),
    ("images/modes/mode_planet_x_card.png", "burning_godzilla.png"),
    ("images/hud/hud_multiball.png", "custom_hud_ball.png"),
    ("scene_textures/mechagodzilla_mb/frame_0001.png", "shin_gojira.png"),
    ("scene_textures/mechagodzilla_mb/frame_0002.png", "mothra_frame.png"),
    ("scene_textures/kaiju_wars/radimg_0001.png", "kaiju_poster.png"),
]
#: The rows the pair highlights - three consecutive picks in the sorted view.
RANGE_OF = 3

GEOM = "1180x900+40+30"


def log(msg):
    print(msg, flush=True)


if not os.path.isdir(PROJ):
    sys.exit("no synthetic project at %s - run mkdata.py first" % PROJ)

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

# A fresh rolling-log dir per run: the log pane preloads earlier sessions, so
# an un-sandboxed run drags the previous shot's lines into this one.
from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(DATA, "logs")
shutil.rmtree(session_log.LOG_DIR_OVERRIDE, ignore_errors=True)
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

# NO UPDATE BANNER.  Another session publishes releases while this runs, and
# the banner is a strip at the top of the window: one shot of the pair would
# carry it and the other would not, which moves every row under it.
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
    # Re-assert the geometry INSIDE the snap: the notebook resizes itself to
    # the selected tab from an idle callback that fires at a different moment
    # in each run, and a before/after pair at two sizes is not comparable
    # (PAD-60).
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


def click_range(tree, iids):
    """Highlight *iids* the way a user does: click the first, shift-click the
    last.  Column #0, so the Replacement cell's picker never opens."""
    tree.focus_set()
    first, last = iids[0], iids[-1]
    tree.see(first)
    root.update_idletasks()
    for seq, iid in (("<Button-1>", first), ("<Shift-Button-1>", last)):
        box = tree.bbox(iid)
        if not box:
            log("  %s has no bbox (scrolled out?)" % iid)
            continue
        tree.event_generate(seq, x=box[0] + 6, y=box[1] + box[3] // 2)
        root.update_idletasks()
    log("selection after a click + shift-click: %d row(s)"
        % len(tree.selection()))
    for iid in tree.selection():
        log("   selected %s" % iid)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_geometry():
    root.geometry(GEOM)


@step(9000)
def s_image_tab():
    """The tab's own visibility hook starts the scan."""
    win._notebook.select(win._tab_image)


@step(6000)
def s_assign():
    n = 0
    for rel, mod in PICKS:
        if rel not in win._image_slots_by_rel:
            log("  no slot %s" % rel)
            continue
        win._image_assignments[rel] = os.path.join(MODS, mod)
        n += 1
    log("slots scanned: %d   picks assigned: %d"
        % (len(win._image_slots), n))
    win._save_staged_changes()
    # "I can order by replacements which is good" - his own view.
    win._image_sort = ("rep", False)
    win._refresh_image_list()


@step(2500)
def s_select_range():
    tree = win._image_tree
    log("selectmode: %s" % tree.cget("selectmode"))
    rows = [iid for iid in tree.get_children("")
            if iid in win._image_assignments][:RANGE_OF]
    if len(rows) < RANGE_OF:
        log("only %d picked rows at the top - sorted wrong?" % len(rows))
    click_range(tree, rows)
    btn = getattr(win, "_clear_all_btns", {}).get("image")
    log("clear-all button: %s"
        % ("absent (before)" if btn is None
           else "%r state=%s" % (btn.cget("text"), str(btn.cget("state")))))


@step(1200)
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
