r"""PAD-131 proof shots: a project whose replacement files moved to another PC.

    python scripts/shot_pad131.py --mode before --out <dir>
    python scripts/shot_pad131.py --mode after  --out <dir>

Builds a scratch Stern project whose recorded replacements all point at a
drive that isn't on this PC (``G:\Pinball Custom Image\Heisei media``) plus
a second folder holding those same files where they live "now", points the
app's saved settings at it, and captures:

  <mode>_replace_video.png  the Replace Video tab.  BEFORE: every recorded
                            replacement was dropped, the log says re-assign
                            them by hand.  AFTER: one pass of the new window
                            put them all back.
  <mode>_relink_window.png  BEFORE: the main window + the log block that was
                            the whole of the old answer.  AFTER: the new
                            Project ▾ → "Relink moved files…" window, having
                            found the moved files.

The ``before`` run is meant to be driven against a checkout of the code
BEFORE the change (``git archive HEAD | tar -x -C <tmp>``); it detects the
absent ``projects_ui.open_relink`` and captures the main window for the
second shot instead.

Capture rules are scripts/take_screenshots.py's (PrintWindow with
PW_RENDERFULLCONTENT, DPI-unaware, settings.json backed up + restored, the
rolling session log sandboxed into a scratch dir so a previous run can't
bleed into the shots).
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad131bak"
SCRATCH = r"C:\tmp\pad131_shots"

ap = argparse.ArgumentParser()
ap.add_argument("--mode", choices=("before", "after"), required=True)
ap.add_argument("--out", required=True)
ARGS = ap.parse_args()
os.makedirs(ARGS.out, exist_ok=True)


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# Fixture: the project as it looks the morning after the move.
# ----------------------------------------------------------------------
#: (slot file in the project, the file it was replaced with on the old PC)
VIDEO = [
    ("video/idx0012.mp4", "megaguirus_out_of_the_water.mp4"),
    ("video/idx0013.mp4", "megaguirus_approaches.mp4"),
    ("video/idx0031.mp4", "alien_monitor_upscaled.mp4"),
    ("video/idx0044.mp4", "city_carnage_bonus.mp4"),
    ("video/idx0052.mp4", "spacegodzilla_jackpot.mp4"),
    ("video/idx0067.mp4", "biollante_multiball.mp4"),
]
AUDIO = [
    ("audio/idx0417.wav", "aburo_orchestral.wav"),
    ("audio/idx0418.wav", "kaiju_award_cue.wav"),
]
#: The one his gaming PC hasn't got a copy of yet, so the pair shows both
#: outcomes rather than a suspiciously perfect 100%.
NOT_COPIED = "biollante_multiball.mp4"

OLD_ROOT = r"G:\Pinball Custom Image\Heisei media"
PROJECT = os.path.join(SCRATCH, "GZ Heisei Custom V1.6")
MEDIA = os.path.join(SCRATCH, "D_drive", "Heisei media")
LOGDIR = os.path.join(SCRATCH, "log_" + ARGS.mode)


def _mp4(path, seconds=2):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=640x480:rate=30:duration=%d" % seconds,
         "-pix_fmt", "yuv420p", "-y", path],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def _wav(path, seconds=1):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0\0" * int(44100 * seconds))


def build_fixture():
    shutil.rmtree(SCRATCH, ignore_errors=True)
    for sub in ("video", "audio"):
        os.makedirs(os.path.join(PROJECT, sub))
        os.makedirs(os.path.join(MEDIA, sub))
    os.makedirs(LOGDIR)
    staged = {"video": {}, "audio": {}, "replacement_names": {}}
    for rel, name in VIDEO:
        _mp4(os.path.join(PROJECT, rel.replace("/", os.sep)))
        if name != NOT_COPIED:
            _mp4(os.path.join(MEDIA, "video", name), seconds=3)
        staged["video"][rel] = OLD_ROOT + r"\video" + "\\" + name
        staged["replacement_names"][rel] = name
    for rel, name in AUDIO:
        _wav(os.path.join(PROJECT, rel.replace("/", os.sep)))
        _wav(os.path.join(MEDIA, "audio", name), seconds=2)
        staged["audio"][rel] = OLD_ROOT + r"\audio" + "\\" + name
        staged["replacement_names"][rel] = name
    with open(os.path.join(PROJECT, ".staged_changes.json"), "w",
              encoding="utf-8") as fh:
        json.dump(staged, fh, indent=2)
    # A real extract's baseline, so the slots read as PENDING picks rather
    # than "changed on disk" — the Replacement column then says plainly
    # whether the project still knows what goes in each slot.
    lines = []
    for rel, _name in VIDEO + AUDIO:
        h = hashlib.md5()
        with open(os.path.join(PROJECT, rel.replace("/", os.sep)), "rb") as fh:
            h.update(fh.read())
        lines.append("%s  %s" % (h.hexdigest(), rel))
    with open(os.path.join(PROJECT, ".checksums.md5"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(PROJECT, ".pinproj"), "w", encoding="utf-8") as fh:
        json.dump({"kind": "pinball-asset-decryptor-project", "format": 2,
                   "manufacturer": "stern", "stock_image": "",
                   "paths": {}, "extract_options": {}, "notes": "",
                   "build_dir": "", "archived": False}, fh, indent=2)
    log("fixture built: %s" % PROJECT)


def point_settings_at_fixture():
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    with open(SETTINGS, encoding="utf-8") as fh:
        data = json.load(fh)
    data["last_manufacturer"] = "stern"
    stern = data.setdefault("manufacturers", {}).setdefault("stern", {})
    stern["extract_output"] = PROJECT
    stern["write_assets"] = PROJECT
    stern["extract_input"] = ""
    stern["write_original"] = ""
    stern["write_output"] = os.path.join(PROJECT, "build")
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    log("settings backed up + pointed at the fixture")


def restore_settings():
    if os.path.isfile(SETTINGS_BAK):
        shutil.copy2(SETTINGS_BAK, SETTINGS)
        os.remove(SETTINGS_BAK)
        log("settings restored")


build_fixture()
point_settings_at_fixture()

os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
# The dev-checkout badge ("[ticket/PAD-131]") is in the title bar of a
# worktree run and not of the plain export the before shots come from,
# which would be the loudest difference in the pair.  The app suppresses
# it under pytest; borrow that (the only other thing the variable gates
# is the disclaimer modal, already skipped above).
os.environ["PYTEST_CURRENT_TEST"] = "shot_pad131"
sys.path.insert(0, REPO)

from PIL import Image                                            # noqa: E402

from pinball_decryptor.core import session_log                   # noqa: E402
session_log.LOG_DIR_OVERRIDE = LOGDIR        # never touch the real history

from pinball_decryptor.app import App                            # noqa: E402
from pinball_decryptor.gui import projects_ui                    # noqa: E402

app = App()
root = app.root
win = app.window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
GEOM = [1360, 900]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def _grab(hwnd, name, crop_border=True):
    wrect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wrect))
    w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
    hdc_win = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)           # PW_RENDERFULLCONTENT
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
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    if crop_border:
        border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
        img = img.crop((border, 0, w - border, h - border))
    path = os.path.join(ARGS.out, "%s_%s.png" % (ARGS.mode, name))
    img.save(path)
    log("snapped %s (%dx%d)" % (path, img.width, img.height))


def _fit_geometry():
    GEOM[0] = min(1360, root.winfo_screenwidth() - 60)
    GEOM[1] = min(900, root.winfo_screenheight() - 80)


#: Logical screen here is 1024x768 (the app runs DPI-unaware), and the
#: Video tab's natural height eats the whole window — so the log pane, which
#: is half of what this ticket changed, never renders.  Pin the notebook
#: shorter for the shot so the slot list AND the log are both in frame.
NB_HEIGHT = 400


def _fit_video_columns():
    """The Replacement column is the one this ticket moves, and at 964
    logical pixels the tab's default widths push it off the right edge.
    Narrow the columns for the shot (view-only; nothing persisted)."""
    try:
        tree = win._video_tree
        for col, wide in (("#0", 150), ("len", 46), ("res", 70),
                          ("fmt", 104), ("aud", 46), ("rep", 250),
                          ("conv", 86)):
            tree.column(col, width=wide)
    except Exception:                                         # noqa: BLE001
        pass


def snap(name, nb_height=None):
    # Re-assert the geometry inside snap(): the notebook re-sizes itself on
    # tab select via after_idle, and that idle fires at a different moment
    # in each run (PAD-60).  Several passes: the first lets the queued
    # resize run, the rest override it, so before/after are comparable.
    _fit_geometry()
    _fit_video_columns()
    for _ in range(3):
        root.geometry("%dx%d+20+20" % tuple(GEOM))
        if nb_height:
            win._notebook.configure(height=nb_height)
        root.update()
    try:
        # The dropped-replacement block arrives via msg_queue and is longer
        # than the pane: park it at the END or the shot shows the startup
        # lines instead of the warning this ticket is about.
        for _ in range(2):
            win._log_text.see("end")
            win._log_text.yview_moveto(1.0)
            root.update()
        log("log view %s" % (win._log_text.yview(),))
    except Exception as e:                                    # noqa: BLE001
        log("log scroll failed: %s" % e)
    log("geometry now %s (screen %dx%d)"
        % (root.winfo_geometry(), root.winfo_screenwidth(),
           root.winfo_screenheight()))
    _grab(user32.GetAncestor(root.winfo_id(), 2), name)


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------

@step(600)
def s_geometry():
    _fit_geometry()
    root.geometry("%dx%d+20+20" % tuple(GEOM))


@step(4000)
def s_video_tab():
    win._notebook.select(win._tab_video)


@step(9000)
def s_show_log_end():
    # The dropped-replacement block arrives via msg_queue, i.e. AFTER the
    # scan lines appended directly, and can sit below the fold.
    win._log_text.see("end")


@step(4000)
def s_shot_tab_before():
    rows = win._video_tree.get_children("")
    log("video rows: %d" % len(rows))
    if ARGS.mode == "before":
        snap("replace_video")


@step(1200)
def s_log_tab():
    # The Video tab's natural height fills the window, pushing the log pane
    # out of the scrollable view entirely.  The Extract tab is short, so the
    # whole log fits under it -- that is where the log pair is shot.
    if ARGS.mode == "before":
        win._notebook.select(win._tab_extract)


@step(2500)
def s_shot_log_before():
    if ARGS.mode == "before":
        snap("log")
        # No such window existed yet: what the user had was this log, so the
        # pair's "before" is the app sitting in it.
        snap("relink_window")
        raise SystemExit(0)


# --- after only: drive the real dialog --------------------------------

DLG = {}


def _walk(w):
    for child in w.winfo_children():
        yield child
        for sub in _walk(child):
            yield sub


def _button(dlg, prefix):
    for w in _walk(dlg):
        try:
            if str(w.cget("text")).startswith(prefix):
                return w
        except Exception:                                     # noqa: BLE001
            continue
    raise SystemExit("no button starting %r" % prefix)


def _entry(dlg):
    for w in _walk(dlg):
        if w.winfo_class() in ("TEntry", "Entry"):
            return w
    raise SystemExit("no entry in the relink window")


@step(800)
def s_open_dialog():
    projects_ui.open_relink(app)
    dlg = projects_ui._relink_win[0]
    DLG["win"] = dlg
    e = _entry(dlg)
    e.delete(0, "end")
    e.insert(0, MEDIA)


@step(1200)
def s_search():
    _button(DLG["win"], "Search").invoke()


@step(3000)
def s_shot_dialog():
    dlg = DLG["win"]
    dlg.update_idletasks()
    _grab(user32.GetAncestor(dlg.winfo_id(), 2), "relink_window",
          crop_border=False)


@step(800)
def s_apply():
    projects_ui.messagebox.showinfo = lambda *a, **k: None
    _button(DLG["win"], "Relink").invoke()


@step(2500)
def s_close_dialog():
    _button(DLG["win"], "Close").invoke()


@step(9000)
def s_shot_tab_after():
    rows = win._video_tree.get_children("")
    log("video rows after relink: %d" % len(rows))
    snap("replace_video")


@step(1200)
def s_after_log_tab():
    win._notebook.select(win._tab_extract)


@step(2500)
def s_shot_log_after():
    snap("log")
    raise SystemExit(0)


def run(i=0):
    if i >= len(STEPS):
        root.after(200, lambda: sys.exit(0))
        return
    delay, fn = STEPS[i]

    def go():
        try:
            fn()
        except SystemExit:
            restore_settings()
            root.destroy()
            return
        except Exception:                                     # noqa: BLE001
            import traceback
            traceback.print_exc()
            restore_settings()
            root.destroy()
            return
        run(i + 1)
    root.after(delay, go)


try:
    run()
    root.mainloop()
finally:
    restore_settings()
