"""Regenerate the README's docs/screenshots/*.png from the live app.

Run from the repo on David's Windows box (any checkout location works):

    python scripts/take_screenshots.py

Launches the real GUI (visible, ~1 minute), steps through the picker /
Extract / Replace Audio / Replace Images / Partition Explorer screens
against the Stern data already saved in the app's settings.json, and
captures each state straight into docs/screenshots/.  The /release
workflow runs this when a release touched the GUI, so the README's
"What it looks like" section can't go stale.

Needs on this machine (checked up front; aborts cleanly if missing):
- the Stern extract_input card image saved in settings.json (any
  Spike 2 .raw/.img/.bin), and
- the Stern write_assets extract folder with audio/ and images/ in it
  (extract with Audio + Images ticked).

Capture notes (learned the hard way — don't "fix" these):
- The window is rendered via PrintWindow(PW_RENDERFULLCONTENT), not a
  screen grab, so other windows sitting on top can't bleed into the
  shots.
- The process is deliberately NOT DPI-aware: the app runs DPI-unaware,
  and a DPI-aware capture scales the Tk fonts up while ttk's fixed
  Treeview rowheight stays put, clipping every descender.  PrintWindow
  on the unaware window yields the crisp internal 96-DPI surface —
  exactly what the app looks like.
- settings.json is backed up and restored, so a capture run leaves no
  trace in the app's saved state.
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "screenshots")
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".shotbak"
SHOTS = ["picker.png", "stern-extract.png", "replace-audio.png",
         "replace-images.png", "partition-explorer.png"]


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# Preflight: the shots need real Stern data, resolved from the app's own
# saved settings (the app restores these paths itself on launch).
# ----------------------------------------------------------------------
try:
    with open(SETTINGS, encoding="utf-8") as f:
        _stern = json.load(f).get("manufacturers", {}).get("stern", {})
except OSError:
    sys.exit("No app settings at %s — launch the app once and extract a "
             "Stern card (Audio + Images) before capturing." % SETTINGS)

_card = (_stern.get("extract_input") or "").strip()
_assets = (_stern.get("write_assets") or _stern.get("extract_output")
           or "").strip()
_missing = []
if not (_card and os.path.isfile(_card)):
    _missing.append("Stern card image (settings extract_input): %r" % _card)
for sub in ("audio", "images"):
    if not os.path.isdir(os.path.join(_assets, sub)):
        _missing.append("Stern extract folder with %s/ (settings "
                        "write_assets): %r" % (sub, _assets))
if _missing:
    sys.exit("Not capturing — screenshot source data missing:\n  "
             + "\n  ".join(_missing)
             + "\nExisting docs/screenshots/*.png left untouched.")

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")

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


def snap(name):
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
    # Crop the invisible resize borders (left/right/bottom; the top edge
    # is the visible title bar).  DWM's extended-frame-bounds API can't
    # be used here: it reports physical pixels even to a DPI-unaware
    # process, and this bitmap is in logical ones.
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    img = img.crop((border, 0, w - border, h - border))
    img.save(os.path.join(OUT, name))
    log("snapped %s (%dx%d)" % (name, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


def big_geometry(target_h):
    # Per-screen heights that fit the content (no giant empty log pane),
    # clamped to the logical desktop.
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(target_h, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))


@step(500)
def s_geometry():
    big_geometry(830)


# Let prereq checks / update check / log settle, then capture the Stern
# Extract tab (the view the app opens into).
@step(9000)
def s_extract():
    snap("stern-extract.png")


@step(500)
def s_picker():
    win.show_picker()
    big_geometry(1060)  # fit the ~1010px card list


@step(2500)
def s_picker_snap():
    snap("picker.png")


@step(500)
def s_reenter():
    big_geometry(1080)
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)


@step(2500)
def s_audio_tab():
    win._notebook.select(win._tab_audio)


# Scan finishes fast; select a row so the spectrogram pane renders.
@step(9000)
def s_audio_select():
    tree = win._audio_tree
    kids = tree.get_children("")
    log("audio rows: %d" % len(kids))
    if kids:
        iid = kids[min(30, len(kids) - 1)]
        tree.see(iid)
        tree.focus(iid)
        tree.selection_set(iid)


@step(6000)
def s_audio_snap():
    snap("replace-audio.png")


@step(500)
def s_image_tab():
    win._notebook.select(win._tab_image)


# Filter to the game-logo art so the preview pane shows something
# recognisable instead of a random sprite frame.
@step(12000)
def s_image_search():
    win.image_search_var.set("logo")


@step(2500)
def s_image_select():
    tree = win._image_tree
    rows = tree.get_children("")
    if not rows:            # no *logo* art on this card — show row 30
        win.image_search_var.set("")
        root.update_idletasks()
        rows = tree.get_children("")
        rows = rows[min(30, len(rows) - 1):] if rows else rows
    log("image rows shown: %d" % len(rows))
    target = None
    for iid in rows:
        if "gamelogo" in str(tree.item(iid, "text")).lower():
            target = iid
            break
    if target is None and rows:
        target = rows[0]
    if target:
        tree.see(target)
        tree.focus(target)
        tree.selection_set(target)


@step(3000)
def s_image_snap():
    snap("replace-images.png")


@step(500)
def s_pex_tab():
    big_geometry(980)
    win._notebook.select(win._tab_partition)


@step(7000)
def s_pex_partition():
    # Switch from the first browsable partition (small rootfs) to the
    # biggest one — the game partition, where the interesting files live.
    best_label, best = None, None
    for label, p in win._pex_part_labels.items():
        if p.browsable and (best is None or p.size > best.size):
            best_label, best = label, p
    if best_label:
        win.partition_part_var.set(best_label)
        win._pex_on_partition_select()


@step(3000)
def s_pex_expand():
    tree = win._pex_tree
    pick = None
    for iid in tree.get_children(""):
        name = str(tree.item(iid, "text")).lower()
        if iid in win._pex_dirs and "lost+found" not in name:
            if pick is None or "game" in name:
                pick = iid
            if "game" in name:
                break
    if pick:
        tree.item(pick, open=True)
        win._pex_fill_open_dirs()
        globals()["_pex_pick"] = pick


@step(2000)
def s_pex_select():
    tree = win._pex_tree
    pick = globals().get("_pex_pick")
    kids = tree.get_children(pick) if pick else ()
    if kids:
        target = kids[0]
        tree.see(target)
        tree.focus(target)
        tree.selection_set(target)


@step(2000)
def s_pex_snap():
    snap("partition-explorer.png")


@step(500)
def s_done():
    log("done — review docs/screenshots/ before committing")
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


def watchdog():
    log("watchdog fired — forcing exit")
    try:
        root.destroy()
    except Exception:
        pass


root.after(180000, watchdog)
run_steps()
try:
    app.run()
finally:
    try:
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
        log("settings restored")
    except Exception:
        log("settings restore FAILED:\n%s" % traceback.format_exc())
