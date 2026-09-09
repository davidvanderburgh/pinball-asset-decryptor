"""PAD-124 proof shots: the Mod Pack tab's field 3 (stock extract of the OLD
version) and what the compare says about text it could not pair.

Two shots, both real code paths on a fixture shaped like the tester's Beatles
run:

* ``modpack_fields`` -- the four transfer fields with the version chip column
  beside them.  Field 3 never had a chip, so picking a folder there looked
  like nothing happened ("it does not update on the right what Stern code
  version is but the other three folders work well").
* ``compare_log`` -- ``mod_transfer.diff_baked_mods`` streaming into the main
  window's log pane with 61 strings it cannot line up, so the capped block
  ends in "...and N more" the way his 195-string run did.

    python scripts/shot_pad124.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up, session log
sandboxed) follow scripts/shot_pad118.py -- see its header.  The script runs
unchanged against the pre-fix tree: the new ``report_dir`` argument is only
passed when the running code accepts it.
"""
import ctypes
import inspect
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
SETTINGS = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                        "settings.json")
SETTINGS_BAK = SETTINGS + ".pad124bak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

WORK = tempfile.mkdtemp(prefix="pad124_shot_")
OLD_MOD = os.path.join(WORK, "Beatles Pepper v127")
OLD_STK = os.path.join(WORK, "Stern v127")
NEW = os.path.join(WORK, "Stern v129")
SCRATCH = os.path.join(WORK, "scratch")
os.makedirs(SCRATCH, exist_ok=True)

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
from pinball_decryptor.core import (extract_source, mod_transfer,  # noqa: E402
                                    text_manifest)

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


def _shoot(hwnd):
    """PrintWindow *hwnd* -> (PIL image of the whole window, window RECT)."""
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
    return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1), wrect


def _save(img, name):
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def snap(name, widget=None, pad=10):
    """Whole window, or just *widget* (plus *pad* px) when one is given.

    Re-assert the geometry first: the app re-sizes itself to the active tab on
    an idle callback that fires at a different moment in each run, and a
    before/after pair has to be pixel-comparable (PAD-60)."""
    for _ in range(2):
        if GEOM:
            root.geometry(GEOM)
        root.update_idletasks()
    img, wrect = _shoot(user32.GetAncestor(root.winfo_id(), 2))   # GA_ROOT
    border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
    if widget is None:
        _save(img.crop((border, 0, img.width - border,
                        img.height - border)), name)
        return
    x = widget.winfo_rootx() - wrect.left
    y = widget.winfo_rooty() - wrect.top
    _save(img.crop((max(0, x - pad), max(0, y - pad),
                    min(img.width, x + widget.winfo_width() + pad),
                    min(img.height, y + widget.winfo_height() + pad))), name)


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


def transfer_fields_frame():
    """The Mod Pack tab's 'Advanced -- do each step myself' panel: the four
    pickers and the version-chip column this ticket is about."""
    import tkinter.ttk as ttk
    for child in win._modpack_transfer_frame.winfo_children():
        if isinstance(child, ttk.LabelFrame) and \
                str(child.cget("text")).startswith("Advanced"):
            return child
    return win._modpack_transfer_frame


# ----------------------------------------------------------------------
# Fixture: the tester's shape at small scale.  A modded old extract, the
# stock extract of that same old version, and the new stock version --
# each with the recorded-source sidecar the version chips read.  The text
# is the point: a run of 60 strings the modded extract has and the stock
# one doesn't (his log had 194 of them, mostly compiler leftovers), plus
# one the stock extract has alone, so the capped log block ends in
# "...and N more".
# ----------------------------------------------------------------------
def _write(root_dir, rel, payload):
    p = os.path.join(root_dir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(payload)


def _blob(tag, n):
    return (tag.encode() * n)[:n]


JUNK = ["ower", "kstemp", "cflow", "flow", "hutdown", "utdown", "down",
        "snprintf", "nprintf", "printf", "igaddset", "addset", "ddset",
        "otect", "trtoull", "flags", "GRAND CHAMPION SCORE", "BIGLIETTI",
        "VOLUME", "LAUTSTARKE", "LOTERIE", "MATCH", "EXTRABALL",
        "PARTIES GRAT.", "REPLAY", "STARTED", "POINTS", "JEUX MINUTE",
        "SAVED", "CREDITS", "CREDITO", "PUNTEGGI RECORD", "SPEZIAL",
        "O MEDIO PER PARTITIA", "ME SESSIONS NOT SENT", "TICKETS",
        "PARTITE", "SPECIAL", "GRATIS", "COMPTEUR", "AUDIT", "RESET",
        "TEST REPORT", "SERVICE MENU", "COIN DOOR", "SLAM TILT",
        "BALL SAVE", "TILT WARNING", "PLAYER 1", "PLAYER 2", "PLAYER 3",
        "PLAYER 4", "FREE PLAY", "GAME OVER", "PRESS START", "ADD PLAYER",
        "HIGH SCORE #4", "HIGH SCORE #3", "HIGH SCORE #2", "HIGH SCORE #1"]


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
        if "idx0181" in rel:
            _write(OLD_MOD, rel, _blob("PEPPER-TAXMAN", 1180444))
        elif "idx0417" in rel:
            _write(OLD_MOD, rel, _blob("PEPPER-MAIN", 968100))
        else:
            _write(OLD_MOD, rel, data)
    for rel, data in stock_audio.items():
        _write(NEW, rel.replace("idx0181", "idx0797"), data)

    for i, tag in enumerate(("attract", "mode_select", "bonus", "gameover")):
        img = _blob("STERN-ART-%s" % tag, 8000 + i)
        _write(OLD_STK, "images/%s.png" % tag, img)
        _write(NEW, "images/%s.png" % tag, img)
        _write(OLD_MOD, "images/%s.png" % tag,
               _blob("PEPPER-ART", 8000 + i) if tag == "attract" else img)

    for folder in (OLD_STK, OLD_MOD, NEW):
        _write(folder, "video/manifest.txt", b"")

    stock_text = ([("/beatles/game", "ATTRACT", ""),
                   ("/beatles/game", "HIGH SCORE", ""),
                   ("/beatles/game", "TILT", "")]
                  + [("/beatles/game", "SHOULD HAVE KNOWN BETTER", "")]
                  + [("/beatles/game", "GAME OVER TEXT", ""),
                     ("attract.radium", "TICKET TO RIDE", ""),
                     ("mode_select.radium", "YELLOW SUBMARINE", "")])
    mod_text = ([("/beatles/game", "ATTRACT", ""),
                 ("/beatles/game", "HIGH SCORE", "")]
                + [("/beatles/game", j, "") for j in JUNK]
                + [("/beatles/game", "TILT", ""),
                   ("/beatles/game", "GAME OVER TEXT", ""),
                   ("attract.radium", "SGT PEPPER", "")])
    new_text = list(stock_text)
    for folder, rows in ((OLD_STK, stock_text), (OLD_MOD, mod_text),
                         (NEW, new_text)):
        text_manifest.save(folder, [{"path": p, "original": o,
                                     "replacement": r} for p, o, r in rows])

    # The version chips read these.  The modded card reports no version of
    # its own (normal for a card modded outside the app), the two stock
    # extracts report theirs, and the new one also names the .raw the build
    # patches onto -- which is what auto-fills field 4.
    mod_raw = os.path.join(WORK, "beatles-pepper-custom.sdcard.raw")
    old_raw = os.path.join(WORK, "beatles-1_27_0.Release.8G.sdcard.raw")
    new_raw = os.path.join(WORK, "beatles-1_29_0.Release.8G.sdcard.raw")
    for p in (mod_raw, old_raw, new_raw):
        with open(p, "wb") as f:
            f.write(b"")
    extract_source.write_extract_source(OLD_MOD, mod_raw)
    extract_source.write_extract_source(OLD_STK, old_raw)
    extract_source.amend_extract_source(OLD_STK, card_version="1.27.0")
    extract_source.write_extract_source(NEW, new_raw)
    extract_source.amend_extract_source(NEW, card_version="1.29.0")


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
    build_fixture()
    try:
        win._notebook.select(win._tab_modpack)
        win.transfer_src_var.set(OLD_MOD)
        win.transfer_oldstock_var.set(OLD_STK)
        win.transfer_dst_var.set(NEW)
    except Exception:
        traceback.print_exc()


# ---- shot 1: the four fields and their version chips --------------------
@step(1500)
def s_fields_snap():
    print("chips: 1=%r 2=%r 3=%r 4=%r"
          % (win.transfer_src_ver_var.get(), win.transfer_dst_ver_var.get(),
             getattr(win, "transfer_oldstock_ver_var", None)
             and win.transfer_oldstock_ver_var.get(),
             win.transfer_img_ver_var.get()), flush=True)
    snap("%s_modpack_fields.png" % WHEN, transfer_fields_frame())


# ---- shot 2: the compare's own log --------------------------------------
@step(1200)
def s_compare():
    clear_log()
    win.append_log("Transfer: reading pending edits from %s ..." % OLD_MOD,
                   "info")
    win.append_log("Using the stock old-version extract as a baseline — this "
                   "is the accurate route and can also carry audio and text.",
                   "info")
    win.append_log("Comparing the modded extract against the stock same-"
                   "version extract — progress below.", "info")
    kw = {}
    if "report_dir" in inspect.signature(
            mod_transfer.diff_baked_mods).parameters:
        kw["report_dir"] = NEW
    STATE["diff"] = mod_transfer.diff_baked_mods(OLD_MOD, OLD_STK,
                                                 log_cb=win.append_log, **kw)
    tail_log()


@step(1500)
def s_log_snap():
    tail_log()
    snap("%s_compare_log.png" % WHEN)
    report = os.path.join(NEW, "logs", mod_transfer.UNMATCHED_TEXT_REPORT) \
        if hasattr(mod_transfer, "UNMATCHED_TEXT_REPORT") else None
    if report and os.path.isfile(report):
        with open(report, encoding="utf-8") as f:
            print("---- report file ----\n%s" % f.read(), flush=True)
    else:
        print("no report file written", flush=True)


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
