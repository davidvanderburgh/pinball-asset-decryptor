"""PAD-179: the Keep size note for a picture an earlier run already replaced.

    python scripts/shot_pad179.py <card.raw> <project_dir> <pick.png> <out_dir> <before|after>

One shot, ``<before|after>_keep_size_note.png``: the Replace Images tab over
*project_dir* (a Stern Godzilla LE 1.16 project holding the Kaiju Battle
Select scene) with its full-screen background selected
(``radimg_Shape_1360x768_254531f8``, 1360x768) and *pick.png* (1600x900)
assigned to it with Keep size OFF.

The rig first puts the project in the state a run leaves behind when that
pick was applied with Keep size ON: the pristine picture is snapshotted under
``.orig/`` (as staging does) and the pick, at its own size, is written over
the slot's file.  Before the change the note read that file's size as the
original's ("Same size as the original (1600x900)") and staging fitted every
later pick to it; after it, both use the snapshot.

NOTHING IS WRITTEN TO THE CARD and no build runs, but the project folder is
changed as described, so point it at a scratch copy.  settings.json is
backed up and restored, and the session log is sandboxed.
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
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
if len(sys.argv) != 6 or sys.argv[5] not in ("before", "after"):
    sys.exit(__doc__)
CARD, PROJECT, PICK_PNG, OUT_DIR, WHEN = sys.argv[1:6]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad179bak"
BG = "images/scene_textures/radimg_Shape_1360x768_254531f8.png"


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

# The state an earlier run leaves: pristine snapshot, then the pick at its
# own size over the slot's file.  Same bytes for the before and after shots.
from pinball_decryptor.core import staged_originals  # noqa: E402
from pinball_decryptor.core.checksums import read_checksums  # noqa: E402
try:
    os.remove(os.path.join(PROJECT, ".staged_changes.json"))
except OSError:
    pass
if not staged_originals.snapshot_path(PROJECT, BG):
    if not staged_originals.snapshot(PROJECT, BG,
                                     read_checksums(PROJECT).get(BG)):
        sys.exit("could not snapshot %s: is the project pristine?" % BG)
shutil.copyfile(PICK_PNG, os.path.join(PROJECT, *BG.split("/")))
log("applied state: snapshot %s, slot file = the pick"
    % staged_originals.snapshot_path(PROJECT, BG))

shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "stern"
stern = settings.setdefault("manufacturers", {}).setdefault("stern", {})
stern.update(extract_input=CARD, write_original=CARD,
             extract_output=PROJECT, write_assets=PROJECT)
# Column widths dragged on a wide monitor add up past this shot's 1100 px and
# clip the Replacement column off the edge; fit-to-content sizes both shots.
(settings.get("column_widths") or {}).pop("image", None)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad179_log_")

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
SW, SH = root.winfo_screenwidth(), root.winfo_screenheight()
GEOM = "%dx%d+10+10" % (min(1100, SW - 40), SH - 70)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def snap(name):
    # The app re-sizes itself to the active tab on an idle callback; let it
    # run, then put the shot's geometry back so before and after line up.
    for _ in range(2):
        root.geometry(GEOM)
        root.update_idletasks()
    root.update()
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
    path = os.path.join(OUT_DIR, "%s_%s.png" % (WHEN, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_setup():
    root.geometry(GEOM)
    log("manufacturer: %s" % getattr(app._current_mfr, "key", None))
    log("assets: %s" % win.write_assets_var.get())


@step(6000)
def s_image_tab():
    win._notebook.select(win._tab_image)


@step(8000)
def s_assign():
    tree = win._image_tree
    log("image slots scanned: %d" % len(win._image_slots))
    win._image_assignments[BG] = PICK_PNG
    win._image_set_keep_size(BG, False)
    win._save_staged_changes()
    win._image_sort = ("rep", False)
    win._refresh_image_list()
    tree.see(BG)
    tree.focus(BG)
    tree.selection_set(BG)
    win._image_current_rel = None
    win._image_on_tree_select()
    log("%s -> %s" % (BG, tree.item(BG, "values")))


@step(4000)
def s_snap():
    log("keep note: %s" % win._image_size_lbl["text"])
    snap("keep_size_note")


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


root.after(120000, root.destroy)    # watchdog
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
    sys.stdout.flush()
    os._exit(0)
