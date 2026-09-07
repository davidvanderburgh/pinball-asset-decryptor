"""PAD-109 proof shots: what the log pane says when a transfer can't place a
sound, and when Whisper runs out of memory.

Both changes land in the main window's log pane, so both shots are that pane
with real lines pushed through the real code paths -- ``plan_detail_lines`` for
the transfer, ``_emit_file_row`` / ``_retry_out_of_memory`` for the transcribe.
The fixture folders mirror the tester's Beatles run: sounds whose new-version
twin is exactly the same length but decoded to something else.

    python scripts/shot_pad109.py <out_dir> <before|after>

Capture mechanics (PrintWindow, DPI-unaware, settings backed up) follow
scripts/take_screenshots.py -- see its header for why they are what they are.
"""
import ctypes
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
SETTINGS_BAK = SETTINGS + ".pad109bak"

os.makedirs(OUT, exist_ok=True)
os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
sys.path.insert(0, REPO)

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, SETTINGS_BAK)

from PIL import Image  # noqa: E402

from pinball_decryptor.app import App  # noqa: E402
from pinball_decryptor.core import mod_transfer, staged_changes  # noqa: E402
import pinball_decryptor.core.transcribe as T  # noqa: E402

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
    bih.biWidth, bih.biHeight = w, -h
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
    img.save(os.path.join(OUT, name))
    print("snapped %s (%dx%d)" % (name, img.width, img.height), flush=True)


def clear_log():
    import tkinter as tk
    t = getattr(win, "_log_text", None)
    if t is None:
        return
    t.configure(state=tk.NORMAL)
    t.delete("1.0", tk.END)
    t.configure(state=tk.DISABLED)


# ----------------------------------------------------------------------
# Fixture: the tester's shape.  Four modded sounds whose new-version twin
# is byte-for-byte the same LENGTH and different audio (the PAD-108 noise
# range), one that carries, one the new version really doesn't have.
# ----------------------------------------------------------------------
WORK = tempfile.mkdtemp(prefix="pad109_shot_")
OLD, NEW = os.path.join(WORK, "Rubber v127"), os.path.join(WORK, "Stern v129")

_PAIRS = [("idx0181", "idx0797", 1_180_444),
          ("idx0343", "idx0848", 2_064_812),
          ("idx0423", "idx0667", 968_100),
          ("idx0554", "idx0494", 3_121_016)]


def _write(root_dir, rel, payload):
    p = os.path.join(root_dir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(payload)


def build_fixture():
    staged = {}
    for old_ix, new_ix, size in _PAIRS:
        # Same length, different bytes: what a mis-decoded slot looks like.
        _write(OLD, "audio/%s.wav" % old_ix, (b"GOOD" * size)[:size])
        _write(NEW, "audio/%s.wav" % new_ix, (b"NOIS" * size)[:size])
        staged["audio/%s.wav" % old_ix] = r"C:\Mods\Beatles\%s.wav" % old_ix
    _write(OLD, "audio/idx0042.wav", b"CARRIES-FINE" * 20000)
    _write(NEW, "audio/idx0042.wav", b"CARRIES-FINE" * 20000)
    staged["audio/idx0042.wav"] = r"C:\Mods\Beatles\intro.wav"
    _write(OLD, "audio/idx0094.wav", b"ONLY-ON-THE-OLD-CARD" * 9000)
    _write(NEW, "audio/idx0900.wav", b"unrelated-and-a-different-length" * 700)
    staged["audio/idx0094.wav"] = r"C:\Mods\Beatles\close_your_eyes.wav"
    staged_changes.save(OLD, {"audio": staged})


STEPS = []


def step(delay_ms):
    def deco(fn):
        STEPS.append((delay_ms, fn))
        return fn
    return deco


@step(600)
def s_enter():
    w = min(1360, root.winfo_screenwidth() - 80)
    h = min(900, root.winfo_screenheight() - 90)
    root.geometry("%dx%d+40+40" % (w, h))
    mfr = next((m for m in app._manufacturers if m.key == "stern"), None)
    if mfr is not None:
        app._on_manufacturer_change(mfr)


# ---- shot 1: a transfer that can't place four sounds -------------------
@step(6000)
def s_transfer():
    build_fixture()
    clear_log()
    win.append_log("Transfer: reading pending edits from %s ..." % OLD, "info")
    win.append_log("Using the stock old-version extract as a baseline — this "
                   "is the accurate route and can also carry audio and text.",
                   "info")
    plan = mod_transfer.plan_transfer(OLD, NEW, log_cb=win.append_log)
    for level, text in mod_transfer.plan_detail_lines(plan):
        win.append_log(text, level)
    win.append_log("Transferred mods from %s: 1 audio, 0 video, 0 image, "
                   "0 text." % OLD, "info")


@step(1800)
def s_transfer_snap():
    snap("%s_transfer_log.png" % WHEN)


# ---- shot 2: Whisper running out of memory ----------------------------
class _StubModel:
    """Raises the tester's own allocator errors, then transcribes."""

    def __init__(self, script):
        self.script = list(script)

    def transcribe(self, path, **kw):
        if self.script:
            raise RuntimeError(self.script.pop(0))
        seg = type("S", (), {"text": "Ladies and gentlemen, the Beatles!"})()
        return iter([seg]), type("I", (), {"duration": 2.1})()


_FAILED = ["audio/00m02s162 - idx0227.wav", "audio/00m02s152 - idx0021.wav",
           "audio/00m02s153 - idx0155.wav", "audio/00m02s166 - idx0369.wav"]
_ERRS = ["mkl_malloc: failed to allocate memory",
         "mkl_malloc: failed to allocate memory",
         "could not create a memory object",
         "Unable to allocate 209. MiB for an array with shape (95107, 576) "
         "and data type float32"]


@step(1200)
def s_transcribe():
    clear_log()
    win.append_log("  Loading 8 model(s) across 8 process(es)...", "info")
    win.append_log("Transcribing 927 sample(s) (non-speech files skip Whisper "
                   "via VAD)...", "info")
    new_api = hasattr(T, "_new_counts")
    counts = (T._new_counts() if new_api
              else {"speech": 0, "music": 0, "non": 0})
    pipe = T.TranscribePipeline(WORK, win.append_log, lambda *a: None,
                                lambda *a, **k: None, lambda *a, **k: None)
    pipe._check_cancel = lambda: None
    pipe._load_model = lambda: _StubModel([])
    n = 912
    for rel, err in zip(_FAILED, _ERRS):
        n += 1
        kind = "error" if new_api else "non-speech"
        pipe._emit_file_row(n, 927, rel, kind, "", err, counts)
    if new_api:
        pipe._retry_out_of_memory(
            [(r, "error", "") for r in _FAILED], counts)
    win.append_log("Renaming speech + music files...", "info")


@step(1800)
def s_transcribe_snap():
    snap("%s_transcribe_log.png" % WHEN)


@step(600)
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
