#!/usr/bin/env python3
"""vpxsetup.py - the Visual Pinball kit's setup, for the app's Visual Pinball tab.

The app's tab (pinball_decryptor/webui/tabs/vpx.py) runs this with the app's
own Windows Python and reads one JSON object back from its last line, so the
kit's pywin32, its DPI awareness and its module names never enter the app's
process:

    vpxsetup.py state                     what is set up: Visual Pinball, the controller,
                                          the card folder and each table the kit knows
    vpxsetup.py vpx <folder>              Visual Pinball is here
    vpxsetup.py download <folder>         download the 10.8.0 release and unpack it there
                                          (progress lines first: `progress <0..1>`)
    vpxsetup.py library <folder>          the folder of card images
    vpxsetup.py layout <key> <player> <lcd>
                                          where the windows go: [x, y, w, h] JSON or null
    vpxsetup.py open <table name>         open a (PAD) table in Visual Pinball

PAD SHIPS NO TABLE. The kit patches the copy the user downloaded from its
author (`padvpx patch`); each map names the table it fits (`table`) so the
tab can say which download that is.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import padisplay  # noqa: E402
import padlaunch   # noqa: E402
import padvpx      # noqa: E402

VPX_URL = ("https://github.com/vpinball/vpinball/releases/download/v10.8.0-2051-28dd6c3/"
           "Developer.VPinballX-10.8.0-2051-28dd6c3-Release-win-x64.zip")
VPX_DEFAULT_DIR = r"C:\Visual Pinball"


def controller_registered():
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PAD.Controller\\CLSID")
        return True
    except Exception:                                       # noqa: BLE001
        return False


def find_vpx():
    kit = padlaunch.kit_load().get("vpx")
    for d in [kit, VPX_DEFAULT_DIR, os.path.join(os.environ.get("ProgramFiles", ""), "Visual Pinball"),
              os.path.join(os.path.expanduser("~"), "Visual Pinball")]:
        if d and os.path.isfile(os.path.join(d, "VPinballX64.exe")):
            return d
    return ""


def vpx_tables_dir():
    vpx = find_vpx()
    return os.path.join(vpx, "tables") if vpx else ""


def set_vpx(folder):
    if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
        return "There is no VPinballX64.exe in %s." % folder
    d = padlaunch.kit_load()
    d["vpx"] = folder
    padlaunch.kit_save(d)
    return "ok"


def set_library(folder):
    d = padlaunch.kit_load()
    d["library"] = folder
    padlaunch.kit_save(d)
    return cards_in(folder)


def cards_in(folder):
    """{title: [file names]} of the Stern card images in `folder`."""
    out = {}
    if folder and os.path.isdir(folder):
        for f in os.listdir(folder):
            m = re.match(r"^([a-z0-9_]+)-\d+_\d+_\d+.*\.sdcard\.raw$", f, re.I)
            if m:
                out.setdefault(m.group(1).lower(), []).append(f)
    return out


def known_tables(tables_dir=None):
    """Each table the kit can patch: the download it fits (the map's
    `table`), the patched name, whether that is in Visual Pinball's tables
    folder, the title Patch takes for it and the card that title boots.
    Maps for one download (JP's Foo Fighters: Pro and LE) are one row:
    `titles` all of them, preferred first, `title` the one padvpx.choose()
    takes, `models` each one's model."""
    tables_dir = vpx_tables_dir() if tables_dir is None else tables_dir
    rows = {}
    for title, info in padvpx.maps().items():
        try:
            m = json.load(open(info["map"], encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        t = m.get("table") or {}
        out_name = info["output"] or ""
        row = rows.get(out_name or title)
        if row is None:
            row = rows[out_name or title] = {
                "name": t.get("name") or title, "by": t.get("by") or "",
                "where": t.get("where") or "", "output": out_name,
                "patched": bool(out_name and tables_dir
                                and os.path.isfile(os.path.join(tables_dir, out_name))),
                "titles": [], "models": {}, "fits": []}
        row["titles"].append(title)
        row["models"][title] = info["model"]
        row["fits"].append((title, info))
    out = []
    for row in rows.values():
        title, _ = padvpx.choose(row.pop("fits"))
        row.update(title=title, card=padlaunch.card_for(title) or "")
        out.append(row)
    return out


def patched_in(tables_dir):
    """The (PAD) tables in a tables folder: what can be opened."""
    if not tables_dir or not os.path.isdir(tables_dir):
        return []
    return sorted(f for f in os.listdir(tables_dir) if f.lower().endswith(".vpx") and "(PAD)" in f)


def layout_presets(mons):
    """Window layouts for the monitors found: (key, words, player rect, lcd rect)."""
    out = []
    if not mons:
        mons = [(0, 0, 1920, 1080)]
    l, t, r, b = mons[0]
    w, h = r - l, b - t
    pw = int(h * 2 / 3)                                  # a playfield is 2:3
    lw = w - pw
    out.append(("side", "Playfield on the main screen, full height on the left; the LCD on the right",
                (l, t, pw, h), (l + pw, t, lw, int(lw * 9 / 16))))
    if len(mons) > 1:
        l2, t2, r2, b2 = mons[1]
        out.append(("two", "Playfield fills the main screen; the LCD fills the second screen",
                    (l, t, int(h * 2 / 3), h), (l2, t2, r2 - l2, b2 - t2)))
    out.append(("centre", "Playfield in the middle at Visual Pinball's own size; the LCD on top, upper middle",
                None, None))
    return out


def layout_key(kit, presets):
    """Which preset the kit's saved player / lcd rectangles are, or ""."""
    player, lcd = kit.get("player"), kit.get("lcd")
    for key, _, p, q in presets:
        want_p = {"x": p[0], "y": p[1], "w": p[2], "h": p[3]} if p else None
        want_q = dict({"x": q[0], "y": q[1], "w": q[2], "h": q[3]}, topmost=True) if q else {"topmost": True}
        if player == want_p and lcd == want_q:
            return key
    return ""


def apply_layout(key, player, lcd):
    """player / lcd: [x, y, w, h] or None (Visual Pinball's own place, the
    LCD's default). Visual Pinball's ini gets the player size."""
    d = padlaunch.kit_load()
    if player:
        x, y, w, h = [int(v) for v in player]
        d["player"] = {"x": x, "y": y, "w": w, "h": h}
        padvpx.vpx_ini_set({"FullScreen": "0", "Width": str(w), "Height": str(h)})
    else:
        d.pop("player", None)
        padvpx.vpx_ini_set({"FullScreen": "0"})
    if lcd:
        x, y, w, h = [int(v) for v in lcd]
        d["lcd"] = {"x": x, "y": y, "w": w, "h": h, "topmost": True}
    else:
        d["lcd"] = {"topmost": True}
    padlaunch.kit_save(d)
    # PAD-811: the game's renderer places its own window from the display
    # setting, live; CONF named here so a test can point it elsewhere
    padisplay.save(display_for(lcd, padisplay.monitors()), padisplay.CONF)
    return "layout %s saved" % key


def display_for(lcd, mons):
    """The display setting (padisplay) for an LCD rectangle: full screen on a
    monitor it fills, else a borderless window on the monitor holding its
    middle (the main one when none does); no rectangle is free, the kit's
    own place for it."""
    if not lcd:
        return {"mode": "free", "monitor": 1, "border": True}
    x, y, w, h = [int(v) for v in lcd]
    for m in mons:
        if (m["x"], m["y"], m["w"], m["h"]) == (x, y, w, h):
            return {"mode": "fullscreen", "monitor": m["n"], "border": False}
    cx, cy = x + w // 2, y + h // 2
    mon = next((m for m in mons if m["x"] <= cx < m["x"] + m["w"]
                and m["y"] <= cy < m["y"] + m["h"]), mons[0])
    return {"mode": "window", "monitor": mon["n"], "border": False,
            "rx": x - mon["x"], "ry": y - mon["y"], "w": w, "h": h}


def download_vpx(folder, say=print, progress=None):
    folder = folder or VPX_DEFAULT_DIR
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, "vpx-release.zip")
    say("Downloading Visual Pinball 10.8.0 (37 MB)...")

    def hook(n, bs, total):
        if total > 0 and progress:
            progress(min(1.0, n * bs / total))
    urllib.request.urlretrieve(VPX_URL, tmp, hook)
    say("Unpacking into %s" % folder)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(folder)
    os.remove(tmp)
    # the release zip may wrap everything in one folder
    if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
        for sub in os.listdir(folder):
            if os.path.isfile(os.path.join(folder, sub, "VPinballX64.exe")):
                for f in os.listdir(os.path.join(folder, sub)):
                    shutil.move(os.path.join(folder, sub, f), folder)
                os.rmdir(os.path.join(folder, sub))
                break
    os.makedirs(os.path.join(folder, "tables"), exist_ok=True)
    return set_vpx(folder)


def open_table(name):
    vpx = find_vpx()
    if not vpx:
        return "Visual Pinball is not set up."
    path = os.path.join(vpx, "tables", name)
    if not os.path.isfile(path):
        return "There is no %s in %s." % (name, os.path.join(vpx, "tables"))
    # no Linux, no game: say so here, not from inside the opened table
    why = padlaunch.no_linux(padlaunch.distro())
    if why:
        return why
    subprocess.Popen([os.path.join(vpx, "VPinballX64.exe"), "-play", path], cwd=vpx)
    return "ok"


def state():
    kit = padlaunch.kit_load()
    lib = os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or ""
    try:
        import padcontroller
        padcontroller.dpi_aware()
        mons = padcontroller.monitors()
    except Exception:                                       # noqa: BLE001
        mons = []
    presets = layout_presets(mons)
    tables = vpx_tables_dir()
    shown = padisplay.load(padisplay.CONF)
    return {
        "registered": controller_registered(),
        "vpx": find_vpx(),
        "tables_dir": tables,
        "library": lib,
        "cards": cards_in(lib),
        "tables": known_tables(tables),
        "patched": patched_in(tables),
        "monitors": len(mons),
        "presets": [{"key": k, "words": w, "player": p, "lcd": q} for k, w, p, q in presets],
        "layout": layout_key(kit, presets),
        # PAD-811: where the game's screen goes, as the layout or the
        # Emulate tab last set it
        "display": {"setting": shown, "text": padisplay.describe(shown)},
    }


def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "state":
        out = state()
    elif cmd == "vpx" and len(rest) == 1:
        out = {"result": set_vpx(rest[0])}
    elif cmd == "library" and len(rest) == 1:
        out = {"result": "ok", "cards": set_library(os.path.abspath(rest[0]))}
    elif cmd == "layout" and len(rest) == 3:
        out = {"result": apply_layout(rest[0], json.loads(rest[1]), json.loads(rest[2]))}
    elif cmd == "download" and len(rest) == 1:
        def prog(f):
            print("progress %.3f" % f, flush=True)
        try:
            out = {"result": download_vpx(rest[0], say=lambda m: print("say " + m, flush=True),
                                          progress=prog)}
        except Exception as exc:                            # noqa: BLE001
            out = {"result": "The download did not finish: %s" % exc}
    elif cmd == "open" and len(rest) == 1:
        out = {"result": open_table(rest[0])}
    else:
        print(__doc__)
        return 2
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
