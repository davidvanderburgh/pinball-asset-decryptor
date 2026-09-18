"""PAD-174 proof shots: a whole song assigned to a 38 s music loop went on
the card at 38 s even with "Allow replacements longer than the original"
ticked, because the Replace Audio staging trimmed it to the slot before the
build ever saw it.

    python scripts/shot_pad174.py <out_dir> <before|after> <grow|cantgrow>

Both scenarios are a REAL Write from the GUI (``App._start_write``, the
Build button's path, staging included) of the stock Godzilla Premium 1.16
card with one replacement assigned on the Replace Audio tab: a 115 s stereo
track over idx 1145 (a 38.38 s music loop), with the option ticked.

``write_log_grow``
    WSL is up.  Before: staging logs "trimmed 115.2s -> 38.4s" and the build
    never grows anything.  After: staging keeps the clip whole and the build
    grows the sound bank for it.
``write_log_cantgrow``
    The same, but the image can't be grown (the WSL probe is made to fail
    the way a WSL that won't start fails, the PAD-112 case).  Before: the
    staging trim again, and nothing else.  After: the build trims it itself
    and its log line names the clip and both lengths.

The shot is scrolled to the staging line, which is where the difference
starts.  ``PAD174_BUILD_DIR`` keeps the built card there (default: a temp
dir that is deleted), so it can be extracted afterwards.

Capture mechanics (DPI-unaware process, PrintWindow with
PW_RENDERFULLCONTENT, settings.json backed up and restored, the rolling
session log redirected into the scratch dir) follow ``scripts/shot_pad130.py``.
Everything runs under ``__main__``: the build's encode pool re-imports this
module in its workers.
"""
import ctypes
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.environ.get("PAD_SPIKE2_IMG_DIR",
                         r"D:\Pinball\images\Stern\spike2")
CARD = os.path.join(IMG_DIR, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
# The stock slot as the extract wrote it, and the replacement to assign.
STOCK_WAV = os.environ.get(
    "PAD174_STOCK_WAV",
    r"C:\Users\david\OneDrive\Desktop\gzho\audio\idx1145 - music.wav")
REPLACEMENT = os.environ.get("PAD174_REPLACEMENT",
                             r"C:\tmp\pad174\replacement_idx1145.wav")
SLOT = "audio/idx1145.wav"
# What ext4_grow.available() returns when the WSL it needs won't answer.
NO_WSL = ("WSL2 not available: a command in the default distro failed. If "
          "WSL is installed, check that the distro still starts \u2014 'wsl -l "
          "-v', then 'wsl -d <name> -- echo ok'. If it is not installed: wsl "
          "--install -d Ubuntu")


def main():
    if sys.platform != "win32":
        sys.exit("Windows-only (PrintWindow/GDI).")
    if len(sys.argv) < 4 or sys.argv[2] not in ("before", "after") \
            or sys.argv[3] not in ("grow", "cantgrow"):
        sys.exit(__doc__)
    out = os.path.abspath(sys.argv[1])
    when, scenario = sys.argv[2], sys.argv[3]
    for p in (CARD, STOCK_WAV, REPLACEMENT):
        if not os.path.isfile(p):
            sys.exit("Not capturing - missing %r" % p)

    settings = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                            "settings.json")
    settings_bak = settings + ".pad174bak"
    work = tempfile.mkdtemp(prefix="pad174_shot_")
    project = os.path.join(work, "GZ 1.16 Premium Extract Custom")
    build_dir = os.environ.get("PAD174_BUILD_DIR") or os.path.join(work,
                                                                   "build")
    os.makedirs(out, exist_ok=True)
    os.makedirs(build_dir, exist_ok=True)
    os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
    sys.path.insert(0, REPO)

    def log(msg):
        print("REPO %s | %s" % (REPO, msg), flush=True)

    # The project: the stock slot, its baseline, the card it came off, and
    # the one assignment the Replace Audio tab records.
    os.makedirs(os.path.join(project, "audio"))
    dst = os.path.join(project, *SLOT.split("/"))
    shutil.copyfile(STOCK_WAV, dst)
    with open(dst, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    with open(os.path.join(project, ".checksums.md5"), "w",
              encoding="utf-8") as f:
        f.write("%s\t%s\n" % (SLOT, md5))
    with open(os.path.join(project, ".extract_source.json"), "w",
              encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "size": os.path.getsize(CARD),
                   "mtime": int(os.path.getmtime(CARD)),
                   "card_version": "1.16.0"}, f, indent=2)
    with open(os.path.join(project, ".staged_changes.json"), "w",
              encoding="utf-8") as f:
        json.dump({"audio": {SLOT: REPLACEMENT}, "audio_trim": True}, f)

    if os.path.exists(settings):
        shutil.copy2(settings, settings_bak)
        with open(settings, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        st = cfg.setdefault("manufacturers", {}).setdefault("stern", {})
        st["write_assets"] = project
        st["extract_output"] = project
        st["extract_input"] = CARD
        st["write_original"] = CARD
        st["write_output"] = build_dir
        cfg["last_manufacturer"] = "stern"
        cfg.pop("column_widths", None)
        adv = cfg.setdefault("audio_advanced", {})
        adv["audio_grow"] = True                  # the option, ticked
        with open(settings, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log("settings backed up + pointed at %s" % project)

    if scenario == "cantgrow":
        from pinball_decryptor.core import ext4_grow
        ext4_grow.available = lambda: (False, NO_WSL)

    from PIL import Image
    from tkinter import messagebox

    from pinball_decryptor.core import session_log
    session_log.LOG_DIR_OVERRIDE = os.path.join(work, "logs")

    from pinball_decryptor.app import App
    App._check_for_update = lambda self: None
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name,
                lambda title, msg="", _n=name, **k: log("%s: %s | %s"
                                                         % (_n, title, msg)))
    messagebox.askyesno = lambda *a, **k: True
    done = {}
    real_done = App._on_done

    def on_done(self, success, summary):
        done["ok"] = success
        real_done(self, success, summary)
    App._on_done = on_done

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD)]

    app = App()
    root = app.root
    win = app.window
    geom = []
    log("PAD_STERN_AUDIO_GROW=%r" % os.environ.get("PAD_STERN_AUDIO_GROW"))

    def snap(name):
        for _ in range(2):
            if geom:
                root.geometry(geom[0])
            root.update_idletasks()
        hwnd = user32.GetAncestor(root.winfo_id(), 2)       # GA_ROOT
        wrect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(wrect))
        w, h = wrect.right - wrect.left, wrect.bottom - wrect.top
        hdc_win = user32.GetWindowDC(hwnd)
        memdc = gdi32.CreateCompatibleDC(hdc_win)
        bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        old = gdi32.SelectObject(memdc, bmp)
        user32.PrintWindow(hwnd, memdc, 2)                  # PW_RENDERFULLCONTENT
        bih = BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bih.biWidth, bih.biHeight = w, -h                   # top-down
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
        path = os.path.join(out, "%s_%s.png" % (when, name))
        img.save(path)
        log("snapped %s (%dx%d)" % (path, img.width, img.height))

    def s_geometry():
        w = min(1500, root.winfo_screenwidth() - 60)
        h = min(820, root.winfo_screenheight() - 90)
        geom.append("%dx%d+30+30" % (w, h))
        root.geometry(geom[0])
        root.after(4000, s_write)

    def s_write():
        win._notebook.select(win._tab_write)
        log("starting the Write")
        app._start_write()
        root.after(5000, s_poll)

    def s_poll():
        if "ok" not in done:
            root.after(3000, s_poll)
            return
        log("Write finished, success=%r" % done["ok"])
        root.after(3000, s_snap)

    def s_snap():
        import tkinter as tk
        t = win._log_text
        # The whole log, for reading past what one screenful shows (kept out
        # of <out_dir>, where a .txt is taken as a shot's caption).
        dump = os.path.join(os.environ.get("PAD174_DUMP_DIR")
                            or tempfile.gettempdir(),
                            "pad174_%s_%s.log" % (when, scenario))
        with open(dump, "w", encoding="utf-8") as f:
            f.write(t.get("1.0", tk.END))
        log("log saved to %s" % dump)
        at = t.search("Staging " + SLOT, "1.0", tk.END)
        if at:
            line = int(at.split(".")[0])
            t.yview("%d.0" % max(1, line - 2))
        snap("write_log_" + scenario)
        root.after(500, root.destroy)

    root.after(1800000, root.destroy)
    root.after(600, s_geometry)
    try:
        app.run()
    finally:
        try:
            if os.path.exists(settings_bak):
                shutil.copy2(settings_bak, settings)
                os.remove(settings_bak)
                log("settings restored")
        except Exception:
            log("settings restore FAILED:\n%s" % traceback.format_exc())
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
