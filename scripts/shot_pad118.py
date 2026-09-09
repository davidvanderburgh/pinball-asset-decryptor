"""PAD-118 proof shots: what the Mod Pack compare says about the text it could
NOT line up between the two old-version extracts.

Both shots are the real code paths on a fixture shaped like the tester's
Beatles run -- ``mod_transfer.diff_baked_mods`` streaming into the main
window's log pane, then ``App._baked_diff_ready`` opening the real
"Transfer mods?" confirm dialog.

    python scripts/shot_pad118.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, session log
sandboxed) follow scripts/take_screenshots.py and scripts/shot_pad109.py --
see their headers for why they are what they are.  The confirm dialog is a
NATIVE message box, so it is photographed from a helper thread that finds it
by pid + title and then dismisses it with IDNO (nothing is applied).
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad118bak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

WORK = tempfile.mkdtemp(prefix="pad118_shot_")
OLD_MOD = os.path.join(WORK, "Revolver v127")
OLD_STK = os.path.join(WORK, "Stern v127")
NEW = os.path.join(WORK, "Stern v129")
SCRATCH = os.path.join(WORK, "scratch")
os.makedirs(SCRATCH, exist_ok=True)

# Settings: keep David's real file, but point this run at an empty folder so
# the app opens clean and no real extract is touched.
if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            _cfg = json.load(f)
        _st = (_cfg.setdefault("manufacturers", {})).setdefault("stern", {})
        _st["write_assets"] = SCRATCH
        _st["extract_output"] = SCRATCH
        _cfg["last_manufacturer"] = "stern"
        _cfg.pop("column_widths", None)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(_cfg, f, indent=2)
    except Exception:
        traceback.print_exc()

from PIL import Image  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402
session_log.LOG_DIR_OVERRIDE = os.path.join(WORK, "logs")

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.core import mod_transfer, text_manifest  # noqa: E402

app = App()
root = app.root
win = app.window

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


def _grab(hwnd, name, crop_border=True):
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
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def snap(name):
    # Re-assert the geometry inside snap(): the app re-sizes itself to the
    # active tab on an idle callback that fires at a different moment in each
    # run, and a before/after pair has to be pixel-comparable (PAD-60).
    for _ in range(2):
        if GEOM:
            root.geometry(GEOM)
        root.update_idletasks()
    _grab(user32.GetAncestor(root.winfo_id(), 2), name)   # GA_ROOT


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


# ----------------------------------------------------------------------
# Fixture: the tester's shape at small scale.  A modded old extract, the
# stock extract of that same old version, and the new stock version.
# Two sounds modded (one of which moved index in the new version), one
# image modded, one text edit -- plus the things that can NOT be lined
# up: two sounds only on one side, one text asset the modded extract
# doesn't carry, and a lopsided run of strings.
# ----------------------------------------------------------------------
def _write(root_dir, rel, payload):
    p = os.path.join(root_dir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(payload)


def _blob(tag, n):
    return (tag.encode() * n)[:n]


def build_fixture():
    stock_audio = {
        "audio/00m05s945 - idx0042.wav": _blob("LADIES-AND-GENTLEMEN", 240000),
        "audio/00m00s793 - idx0094.wav": _blob("CLOSE-YOUR-EYES", 96000),
        "audio/01m50s553 - idx0181.wav": _blob("MUSIC-TAXMAN", 1180444),
        "audio/00m49s152 - idx0343.wav": _blob("AND-ILL-KISS-YOU", 264812),
        "audio/00m31s294 - idx0417.wav": _blob("MUSIC-MAIN-PLAY", 968100),
        "audio/01m55s751 - idx0554.wav": _blob("MUSIC-MULTIBALL", 312101),
    }
    for rel, data in stock_audio.items():
        _write(OLD_STK, rel, data)
        # The modded extract: the tester's own audio in two slots.
        if "idx0181" in rel:
            _write(OLD_MOD, rel, _blob("RUBBER-SOUL-TAXMAN", 1180444))
        elif "idx0417" in rel:
            _write(OLD_MOD, rel, _blob("RUBBER-SOUL-MAIN", 968100))
        elif "idx0554" not in rel:
            _write(OLD_MOD, rel, data)
    # One slot only in the modded extract, one only in the stock one.
    _write(OLD_MOD, "audio/00m02s241 - idx0900.wav", _blob("HAND-ADDED", 40000))

    # New version: same sounds, but the taxman music moved index.
    for rel, data in stock_audio.items():
        _write(NEW, rel.replace("idx0181", "idx0797"), data)

    for i, tag in enumerate(("attract", "mode_select", "bonus", "gameover")):
        img = _blob("STERN-ART-%s" % tag, 8000 + i)
        _write(OLD_STK, "images/%s.png" % tag, img)
        _write(NEW, "images/%s.png" % tag, img)
        _write(OLD_MOD, "images/%s.png" % tag,
               _blob("RUBBER-SOUL-ART", 8000 + i) if tag == "attract" else img)

    _write(OLD_STK, "video/manifest.txt", b"")
    _write(OLD_MOD, "video/manifest.txt", b"")
    _write(NEW, "video/manifest.txt", b"")

    # Text.  game_real: three anchors, then a run the two sides disagree on
    # (one string only in the stock extract, two only in the modded one) --
    # that run is what can't be lined up.  attract.radium: a real edit.
    # mode_select.radium: an asset the modded extract doesn't carry at all.
    stock_text = [("game_real", "ATTRACT", ""),
                  ("game_real", "HIGH SCORE", ""),
                  ("game_real", "TILT", ""),
                  ("game_real", "PRESS START TO PLAY", ""),
                  ("game_real", "GAME OVER", ""),
                  ("attract.radium", "TICKET TO RIDE", ""),
                  ("mode_select.radium", "YELLOW SUBMARINE", "")]
    mod_text = [("game_real", "ATTRACT", ""),
                ("game_real", "HIGH SCORE", ""),
                ("game_real", "TILT", ""),
                ("game_real", "PRESS FLIPPER TO START", ""),
                ("game_real", "RUBBER SOUL BONUS", ""),
                ("game_real", "GAME OVER", ""),
                ("attract.radium", "NORWEGIAN WOOD", "")]
    new_text = [("game_real", "ATTRACT", ""),
                ("game_real", "HIGH SCORE", ""),
                ("game_real", "TILT", ""),
                ("game_real", "PRESS START TO PLAY", ""),
                ("game_real", "GAME OVER", ""),
                ("attract.radium", "TICKET TO RIDE", ""),
                ("mode_select.radium", "YELLOW SUBMARINE", "")]
    for folder, rows in ((OLD_STK, stock_text), (OLD_MOD, mod_text),
                         (NEW, new_text)):
        text_manifest.save(folder, [{"path": p, "original": o,
                                     "replacement": r} for p, o, r in rows])


STEPS = []
STATE = {}


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(700)
def s_enter():
    global GEOM
    root.maxsize(9999, 9999)
    w = min(1210, root.winfo_screenwidth() - 60)
    h = min(950, root.winfo_screenheight() - 60)
    GEOM = "%dx%d+30+20" % (w, h)
    root.geometry(GEOM)
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)
    # The compare is run from the Mod Pack tab, so show it behind the log.
    try:
        win._notebook.select(win._tab_modpack)
        win.transfer_src_var.set(OLD_MOD)
        win.transfer_oldstock_var.set(OLD_STK)
        win.transfer_dst_var.set(NEW)
    except Exception:
        traceback.print_exc()


# ---- shot 1: the compare's own log --------------------------------------
@step(2500)
def s_compare():
    build_fixture()
    clear_log()
    win.append_log("Transfer: reading pending edits from %s ..." % OLD_MOD,
                   "info")
    win.append_log("Using the stock old-version extract as a baseline — this "
                   "is the accurate route and can also carry audio and text.",
                   "info")
    win.append_log("Comparing the modded extract against the stock same-"
                   "version extract — progress below.", "info")
    STATE["diff"] = mod_transfer.diff_baked_mods(OLD_MOD, OLD_STK,
                                                 log_cb=win.append_log)
    tail_log()


@step(1500)
def s_compare_snap():
    tail_log()
    snap("%s_compare_log.png" % WHEN)


# ---- shot 2: the confirm dialog ----------------------------------------
def _dialog_watcher(title, name):
    """Photograph the native message box, then answer No."""
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)
    found = []

    def _cb(hwnd, _lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != os.getpid() or not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value == title:
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + 25
    while time.time() < deadline:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        if found:
            time.sleep(0.8)            # let it paint
            try:
                _grab(found[0], name, crop_border=False)
            except Exception:
                traceback.print_exc()
            user32.PostMessageW(found[0], 0x0111, 7, 0)   # WM_COMMAND, IDNO
            return
        time.sleep(0.25)
    print("dialog %r never appeared" % title, flush=True)


@step(1200)
def s_dialog():
    diff = STATE["diff"]
    plan = mod_transfer.plan_transfer(OLD_STK, NEW, saved=diff["saved"],
                                      src_text_rows=diff["text_rows"])
    t = threading.Thread(target=_dialog_watcher,
                         args=("Transfer mods?",
                               "%s_transfer_dialog.png" % WHEN), daemon=True)
    t.start()
    app._baked_diff_ready(OLD_MOD, OLD_STK, NEW, diff, plan)
    t.join(5)


@step(2500)
def s_done():
    try:
        if os.path.exists(SETTINGS_BAK):
            shutil.copy2(SETTINGS_BAK, SETTINGS)
            os.remove(SETTINGS_BAK)
        shutil.rmtree(WORK, ignore_errors=True)
    finally:
        root.destroy()


def _schedule():
    t = 0
    for delay, fn in STEPS:
        t += delay

        def run(fn=fn):
            try:
                fn()
            except Exception:
                traceback.print_exc()
        root.after(t, run)


_schedule()
root.mainloop()
print("done", flush=True)
