"""PAD-162: the Emulate JJP tab of an INSTALLED app, not of a checkout.

    python scripts/shot_pad162.py <out_dir> <before|after>

A Windows user (a field report) installed the release and the Emulate JJP
tab said "The JJP emulator rig is missing from tools/jjp_emu - this checkout
looks incomplete", with Start greyed out.  Their tools folder held spike1_emu
and spike2_emu and nothing else: pinball_decryptor.iss never had a [Files]
line for tools\\jjp_emu, so no installed copy has ever had the JJP rig.

A checkout always has the rig, so running the app from this repo shows nothing
either way.  This rig therefore lays out {app} the way the installer would:
it reads THIS tree's installer/pinball_decryptor.iss, applies each Source /
DestDir / Excludes line for the package and the tools folder (Inno's Excludes
rules: a pattern matches the END of a path unless it starts with a
backslash), copies into ``c:\\tmp\\pad162\\<when>\\Pinball Asset Decryptor``
(a space in it, like Program Files), and runs the app from THERE.  The pair
is the same code under the before and after manifest.

``emulate_jjp``
    The Emulate JJP tab four seconds after it is selected, in both runs.  The
    shot does not wait for the first status poll: that is a WSL round trip
    whose answer depends on the machine (on 2026-09-17 this box's WSL did not
    answer at all, and a poll that times out fills the grid with "no"s that
    read like real facts).  Four seconds is before any poll can land, so the
    pair differs only by what the installed tree holds.  Nothing on the
    machine is changed: the poll runs status.sh, which only reads.

settings.json is backed up and restored, and the session log is sandboxed.
"""
import ctypes
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Screenshot capture is Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(REPO, "installer", "pinball_decryptor.iss")
STAGE_ROOT = r"c:\tmp\pad162"


def log(msg):
    print(msg, flush=True)


# --- stage {app} from the .iss ----------------------------------------------

def _excluded(rel, patterns):
    """Inno Setup's Excludes match for ``rel`` (backslash-separated)."""
    parts = rel.split("\\")
    for pat in patterns:
        pp = pat.lstrip("\\").split("\\")
        if len(pp) > len(parts):
            continue
        cand = parts[:len(pp)] if pat.startswith("\\") else parts[-len(pp):]
        if all(fnmatch.fnmatchcase(c.lower(), p.lower())
               for c, p in zip(cand, pp)):
            return True
    return False


def iss_file_lines(iss_text):
    """``[(source, destdir, flags, excludes)]`` for every [Files] entry, with
    Inno's backslash line continuations joined."""
    text = iss_text.replace("\\\n", " ").replace("\\\r\n", " ")
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("Source:"):
            continue
        field = dict((m.group(1).lower(), m.group(2)) for m in
                     re.finditer(r'(\w+):\s*"([^"]*)"', s))
        flags = re.search(r"Flags:\s*([^;]*)", s)
        out.append((field.get("source", ""), field.get("destdir", ""),
                    flags.group(1).split() if flags else [],
                    [p.strip() for p in field.get("excludes", "").split(",")
                     if p.strip()]))
    return out


def stage(app_dir):
    """Copy the package and the tools the .iss ships into ``app_dir``."""
    with open(ISS, encoding="utf-8", errors="replace") as f:
        entries = iss_file_lines(f.read())
    shipped = []
    for source, dest, flags, excludes in entries:
        m = re.match(r"\{#ProjectDir\}\\((?:pinball_decryptor|tools\\[^\\]+))"
                     r"\\\*$", source)
        if not m or "recursesubdirs" not in flags:
            continue
        src = os.path.join(REPO, m.group(1))
        dst = os.path.join(app_dir, dest.replace("{app}\\", ""))
        n = 0
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = os.path.relpath(dirpath, src)
            rel_dir = "" if rel_dir == "." else rel_dir
            # Inno tests a directory against the patterns too, and skips it.
            dirnames[:] = [d for d in dirnames if not _excluded(
                os.path.join(rel_dir, d) if rel_dir else d, excludes)]
            for name in filenames:
                rel = os.path.join(rel_dir, name) if rel_dir else name
                if _excluded(rel, excludes):
                    continue
                os.makedirs(os.path.join(dst, rel_dir), exist_ok=True)
                shutil.copy2(os.path.join(dirpath, name), os.path.join(dst, rel))
                n += 1
        shipped.append((m.group(1), n))
    return shipped


# --- capture (runs from the staged tree) -------------------------------------

def inner(app_dir, out_png):
    sys.path.insert(0, app_dir)
    os.environ["PINBALL_SKIP_DISCLAIMER"] = "1"
    import tkinter as tk  # noqa: F401  (Tk before PIL's ImageTk glue)

    import pinball_decryptor
    log("package under test: %s" % os.path.dirname(pinball_decryptor.__file__))

    settings_path = os.path.join(os.environ["APPDATA"], "pinball_decryptor",
                                 "settings.json")
    backup = settings_path + ".pad162bak"
    shutil.copy2(settings_path, backup)
    try:
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
        settings["last_manufacturer"] = "jjp"
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        from pinball_decryptor.core import session_log
        session_log.LOG_DIR_OVERRIDE = tempfile.mkdtemp(prefix="pad162_log_")
        from PIL import Image
        from pinball_decryptor.app import App
        from pinball_decryptor.gui import jjp_emulate_tab

        log("rig dir: %s (present=%s)" % (jjp_emulate_tab.rig_dir(),
                                          jjp_emulate_tab.rig_available()))
        app = App()
        root, win = app.root, app.window
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        geom = ["1100x760+20+10"]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]

        def grab():
            for _ in range(2):
                root.geometry(geom[0])
                root.update()
            hwnd = user32.GetAncestor(root.winfo_id(), 2)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            hdc = user32.GetWindowDC(hwnd)
            mem = gdi32.CreateCompatibleDC(hdc)
            bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
            old = gdi32.SelectObject(mem, bmp)
            user32.PrintWindow(hwnd, mem, 2)
            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth, bih.biHeight, bih.biPlanes, bih.biBitCount = w, -h, 1, 32
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(hwnd, hdc)
            img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
            border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
            img.crop((border, 0, w - border, h - border)).save(out_png)
            log("snapped %s (%dx%d)" % (out_png, w - 2 * border, h - border))

        def select_tab():
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            geom[0] = "%dx%d+20+10" % (min(1100, sw - 60), min(760, sh - 70))
            root.geometry(geom[0])
            win._notebook.select(win._tab_jjp_emulate)
            fit = getattr(win, "_resize_notebook_to_current_tab", None)
            if fit:
                fit()
            root.after(4000, snap_and_quit)

        def snap_and_quit():
            try:
                panel = win._jjp_emulate_panel
                log("polled=%s note=%r start=%s" % (
                    getattr(panel, "_polled_once", None),
                    panel._note.cget("text"), panel._go_btn.cget("state")))
                grab()
            except Exception:
                log("snap FAILED:\n%s" % traceback.format_exc())
            root.destroy()

        root.after(8000, select_tab)
        root.after(150000, root.destroy)      # watchdog
        app.run()
    finally:
        shutil.copy2(backup, settings_path)
        os.remove(backup)
        log("settings restored")
        sys.stdout.flush()
        os._exit(0)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--inner":
        return inner(sys.argv[2], sys.argv[3])
    if len(sys.argv) != 3 or sys.argv[2] not in ("before", "after"):
        sys.exit(__doc__)
    out_dir, when = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    app_dir = os.path.join(STAGE_ROOT, when, "Pinball Asset Decryptor")
    shutil.rmtree(app_dir, ignore_errors=True)
    log("manifest: %s" % ISS)
    for what, n in stage(app_dir):
        log("  staged %-22s %4d files" % (what, n))
    tools = os.path.join(app_dir, "tools")
    log("{app}\\tools holds: %s" % sorted(os.listdir(tools)))
    return subprocess.call([sys.executable, os.path.abspath(__file__), "--inner",
                            app_dir, os.path.join(out_dir, "%s_emulate_jjp.png" % when)])


if __name__ == "__main__":
    sys.exit(main())
