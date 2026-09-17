"""PAD-163: files dropped into a project by name, and "Replace from folder…".

    python scripts/shot_pad163.py <gz_extract> <out_dir> <screen> <before|after>

*gz_extract* is a Godzilla 1.16 extract with ``video/`` and
``images/scene_textures/glyphs/`` (real clips and glyphs are copied out of it
into a scratch fixture; nothing in it is touched).  *screen* is one of:

``video_dropin``
    What the reporter did: every clip in ``video/`` deleted and a black and
    white copy of each dropped in under the same name, as the ``.mp4`` their
    converter writes.  The ``.mov`` slots' copies are the rows the Video tab
    disowns; one of them is selected, so the Replacement pane explains why.

``images_dropin``
    The same move on the Images tab with glyphs from another card's extract:
    their atlas folder name carries a different fingerprint, so none of them
    are on this card.  One is selected, like the reporter's screenshot.

``video_from_folder``
    The extract left intact and the black and white copies kept in a folder of
    their own.  After the change, "Replace from folder…" is pressed (the folder
    dialog and the confirm are answered by the rig) and every clip is assigned.

settings.json is backed up and restored and the session log is sandboxed.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")
SCREENS = ("video_dropin", "images_dropin", "video_from_folder")
if (len(sys.argv) != 5 or sys.argv[3] not in SCREENS
        or sys.argv[4] not in ("before", "after")):
    sys.exit(__doc__)
GZ, OUT_DIR, SCREEN, WHEN = sys.argv[1:5]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad163bak"
SCRATCH = os.path.join(tempfile.gettempdir(), "pad163_shot_%s_%s"
                       % (SCREEN, WHEN))
CLIPS = ["Tank_Jackpot1.mov", "Tank_Jackpot2.mov", "Tank_Jackpot3.mov",
         "Tank_Jackpot4.mov", "SaucerAttackMultiball_Jackpot1.mov",
         "Mothra_powerlines_attack1_1.mov", "Rampage_P.mov", "Rampage_R.mov",
         "megalon_drill.mp4", "planetXescape.mp4", "tilt.mp4",
         "Xiliens_Intro.mp4"]
ATLAS_STOCK = "radimg_512x512_a4a16c84"
ATLAS_OTHER = "radimg_512x512_bba78124"
GLYPHS = ["U+0041_A.png", "U+0042_B.png", "U+0043_C.png", "U+0069_i.png",
          "U+006C_l.png", "U+007C.png", "U+02C6.png", "U+2013.png",
          "U+2014.png", "U+2018.png", "U+2019.png"]


def log(msg):
    print(msg, flush=True)


os.makedirs(OUT_DIR, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)
log("code under test: %s" % REPO)

from pinball_decryptor.core import checksums  # noqa: E402


def _bw(src, dst):
    """A black and white copy the way a batch converter makes one: always
    .mp4, whatever the source was."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v",
                    "-map", "0:a?", "-vf", "hue=s=0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", dst], check=True)


# --- the scratch fixture ------------------------------------------------------
shutil.rmtree(SCRATCH, ignore_errors=True)
PROJECT = os.path.join(SCRATCH, "GZ 1.16 Extract BW")
BW_DIR = os.path.join(SCRATCH, "BW clips")
vid = os.path.join(PROJECT, "video")
os.makedirs(vid)
os.makedirs(BW_DIR)
rows = {}
with open(os.path.join(GZ, "video", "manifest.txt"), encoding="utf-8") as f:
    for line in f:
        cols = line.rstrip("\n").split("\t")
        if cols and cols[0] in CLIPS:
            rows[cols[0]] = line
for clip in CLIPS:
    shutil.copy2(os.path.join(GZ, "video", clip), os.path.join(vid, clip))
with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
    f.write("# output\tcard path\tbytes\n")
    f.write("".join(rows[c] for c in CLIPS if c in rows))
gly_src = os.path.join(GZ, "images", "scene_textures", "glyphs", ATLAS_STOCK)
gly = os.path.join(PROJECT, "images", "scene_textures", "glyphs", ATLAS_STOCK)
os.makedirs(gly)
for g in GLYPHS:
    shutil.copy2(os.path.join(gly_src, g), os.path.join(gly, g))
checksums.generate_checksums(PROJECT)
log("fixture baseline written")

for clip in CLIPS:
    _bw(os.path.join(vid, clip),
        os.path.join(BW_DIR, os.path.splitext(clip)[0] + ".mp4"))
log("black and white copies made")

if SCREEN == "video_dropin":
    for clip in CLIPS:
        os.remove(os.path.join(vid, clip))
    for fn in os.listdir(BW_DIR):
        shutil.copy2(os.path.join(BW_DIR, fn), os.path.join(vid, fn))
elif SCREEN == "images_dropin":
    other = os.path.join(os.path.dirname(gly), ATLAS_OTHER)
    os.rename(gly, other)

# --- the app --------------------------------------------------------------------
shutil.copy2(SETTINGS, SETTINGS_BAK)
log("settings backed up")
with open(SETTINGS, encoding="utf-8") as f:
    settings = json.load(f)
settings["last_manufacturer"] = "stern"
stern = settings.setdefault("manufacturers", {}).setdefault("stern", {})
stern.update(extract_output=PROJECT, write_assets=PROJECT)
for k in ("video", "image"):
    (settings.get("column_widths") or {}).pop(k, None)
with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad163_log_")

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402

app = App()
root = app.root
win = app.window
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
SW, SH = root.winfo_screenwidth(), root.winfo_screenheight()
GEOM = "%dx%d+10+10" % (min(1100, SW - 40), min(1000, SH - 70))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def snap(name):
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


def select(tree, rel, on_select):
    tree.see(rel)
    tree.focus(rel)
    tree.selection_set(rel)
    on_select()


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(500)
def s_setup():
    root.geometry(GEOM)
    log("assets: %s" % win.write_assets_var.get())


@step(5000)
def s_tab():
    win._notebook.select(win._tab_image if SCREEN == "images_dropin"
                         else win._tab_video)


@step(9000)
def s_act():
    if SCREEN == "video_dropin":
        rel = "video/Tank_Jackpot1.mp4"
        log("foreign: %s" % sorted(win._video_foreign_rels))
        win._video_current_rel = None
        select(win._video_tree, rel, win._video_preview_selected)
    elif SCREEN == "images_dropin":
        rel = "images/scene_textures/glyphs/%s/U+02C6.png" % ATLAS_OTHER
        log("foreign: %d" % len(win._image_foreign_rels))
        win._image_current_rel = None
        select(win._image_tree, rel, win._image_on_tree_select)
    elif SCREEN == "video_from_folder":
        if not hasattr(win, "_replace_from_folder"):
            log("no Replace from folder in this build")
            return
        from tkinter import filedialog, messagebox
        filedialog.askdirectory = lambda **kw: BW_DIR
        messagebox.askyesno = lambda title, msg, **kw: (
            log("confirm: %s\n%s" % (title, msg)) or True)
        messagebox.showinfo = lambda title, msg, **kw: log(
            "info: %s\n%s" % (title, msg))
        win._replace_from_folder("video")
        rel = "video/Tank_Jackpot1.mov"
        win._video_current_rel = None
        select(win._video_tree, rel, win._video_preview_selected)
        for r in ("video/Tank_Jackpot1.mov", "video/tilt.mp4"):
            log("%s -> %s" % (r, win._video_tree.item(r, "values")))


@step(6000)
def s_snap():
    win._log_text.see("end")
    snap(SCREEN)


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


root.after(150000, root.destroy)    # watchdog
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
