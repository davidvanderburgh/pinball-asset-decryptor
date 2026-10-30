"""padisplay.py - where the Spike 2 game window goes (PAD-811).

One setting, for the desktop and for a Visual Pinball cabinet alike: the
game window is FREE (where it was left, with its frame, as before), FULL
SCREEN on a monitor, or a WINDOW at a rectangle on a monitor; borderless or
framed. It is a line in `display.conf` on the rig board
(%USERPROFILE%\\.pad-rig), which padglhost reads twice a second while the
game runs - a change moves the window at once, no restart:

    game monitor=2 mode=fullscreen border=0 rx=0 ry=0 x=3840 y=0 w=1920 h=1080 fs=1

`monitor`, `mode`, `rx`/`ry` (the rectangle's corner on its monitor) are the
choice as the user made it; `x y w h fs` are what padglhost acts on, in
Windows' physical desktop pixels (which under WSLg are X root coordinates).
The Windows side resolves the one into the other because only it knows the
monitors; a cabinet whose screens change is resolved again by saving again.

Monitors are numbered as Windows' own Display settings would list them for
a user: 1 is the main screen, then left to right, top to bottom.

    python padisplay.py                       the setting and the monitors
    python padisplay.py monitor 2             full screen on monitor 2, borderless
    python padisplay.py monitor 2 window 0 0 1360 768
                                              a 1360x768 window at monitor 2's corner
    python padisplay.py border on|off         the frame, keeping the rest
    python padisplay.py free                  back to where it was left, framed
"""
import json
import os
import sys

#: the board every side reads (padlaunch.BOARD, core/rigslot.py)
BOARD = os.path.join(os.path.expanduser("~"), ".pad-rig")
CONF = os.path.join(BOARD, "display.conf")
MODES = ("free", "fullscreen", "window")


def monitors():
    """Every monitor as {"n", "x", "y", "w", "h", "primary"} in physical
    pixels, numbered: the main one 1, then left to right, top to bottom.
    ctypes only, so the app's Python needs nothing installed."""
    if sys.platform != "win32":
        return [{"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}]
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    # physical pixels on EVERY monitor: an unaware process sees scaled ones,
    # and a system-aware one (the app's, pywebview's) still sees a monitor
    # whose DPI differs from the main one's scaled. Per-monitor v2 for this
    # thread only, put back after.
    old = None
    try:
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:                                       # noqa: BLE001
        try:
            u.SetProcessDPIAware()
        except Exception:                                   # noqa: BLE001
            pass

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)

    def cb(hmon, _hdc, _rect, _data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if u.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi)):
            r = mi.rcMonitor
            found.append({"x": r.left, "y": r.top, "w": r.right - r.left,
                          "h": r.bottom - r.top, "primary": bool(mi.dwFlags & 1)})
        return 1
    u.EnumDisplayMonitors(None, None, proc(cb), None)
    if old:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    found.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    for i, m in enumerate(found):
        m["n"] = i + 1
    return found or [{"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}]


def load(path=CONF):
    """The game window's setting as the user made it: {"mode", "monitor",
    "border", "rx", "ry", "w", "h"}; free when there is none."""
    out = {"mode": "free", "monitor": 1, "border": True}
    try:
        for line in open(path, encoding="utf-8"):
            p = line.split()
            if not p or p[0] != "game":
                continue
            kv = dict(t.split("=", 1) for t in p[1:] if "=" in t)
            out["mode"] = kv.get("mode", "fullscreen" if kv.get("fs") == "1" else "window")
            out["monitor"] = int(kv.get("monitor", 1))
            out["border"] = kv.get("border", "1") != "0"
            for k in ("rx", "ry", "w", "h"):
                if k in kv:
                    out[k] = int(kv[k])
            break
    except (OSError, ValueError):
        pass
    if out["mode"] not in MODES:
        out["mode"] = "free"
    return out


def resolve(setting, mons=None):
    """The game line for a setting, against the monitors now; None = free.
    A monitor that is not there any more falls back to the main one."""
    s = dict(setting)
    if s.get("mode", "free") == "free":
        return None
    mons = mons or monitors()
    n = int(s.get("monitor") or 1)
    mon = next((m for m in mons if m["n"] == n), mons[0])
    border = 1 if s.get("border", False) else 0
    if s["mode"] == "fullscreen":
        x, y, w, h, fs = mon["x"], mon["y"], mon["w"], mon["h"], 1
        rx = ry = 0
    else:
        rx, ry = int(s.get("rx", 0)), int(s.get("ry", 0))
        w = int(s.get("w") or min(1360, mon["w"]))
        h = int(s.get("h") or min(768, mon["h"]))
        x, y, fs = mon["x"] + rx, mon["y"] + ry, 0
    return ("game monitor=%d mode=%s border=%d rx=%d ry=%d x=%d y=%d w=%d h=%d fs=%d"
            % (mon["n"], s["mode"], border, rx, ry, x, y, w, h, fs))


def save(setting, path=CONF):
    """Write the setting (atomically: padglhost may read mid-write). Free
    removes the line, and the window goes back to where it was left."""
    line = resolve(setting)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# the Spike 2 game window (padisplay.py); padglhost reads it live\n")
        if line:
            f.write(line + "\n")
    os.replace(tmp, path)
    return line


def describe(setting, mons=None):
    """One line a person reads."""
    s = setting
    if s.get("mode", "free") == "free":
        return "free: where it was last left, with its frame"
    mons = mons or monitors()
    n = int(s.get("monitor") or 1)
    mon = next((m for m in mons if m["n"] == n), None)
    where = "monitor %d" % n + ("" if mon else " (not connected: the main one for now)")
    frame = "with its frame" if s.get("border") else "borderless"
    if s["mode"] == "fullscreen":
        return "full screen on %s, %s" % (where, frame)
    return "a %dx%d window at %d,%d on %s, %s" % (
        s.get("w", 1360), s.get("h", 768), s.get("rx", 0), s.get("ry", 0), where, frame)


def main(argv):
    s = load()
    if not argv:
        print("game window: %s" % describe(s))
        for m in monitors():
            print("  monitor %d: %dx%d at %d,%d%s" % (m["n"], m["w"], m["h"], m["x"], m["y"],
                                                     " (main)" if m["primary"] else ""))
        return 0
    cmd = argv[0]
    if cmd == "free":
        s = {"mode": "free", "monitor": s.get("monitor", 1), "border": True}
    elif cmd == "monitor" and len(argv) >= 2:
        s = {"mode": "fullscreen", "monitor": int(argv[1]), "border": False}
        if len(argv) >= 3 and argv[2] == "window":
            nums = [int(v) for v in argv[3:7]]
            s["mode"] = "window"
            if len(nums) == 4:
                s["rx"], s["ry"], s["w"], s["h"] = nums
        elif len(argv) >= 3 and argv[2] not in ("fullscreen", "full"):
            print(__doc__)
            return 2
    elif cmd == "border" and len(argv) >= 2 and argv[1] in ("on", "off"):
        s["border"] = argv[1] == "on"
        if s["mode"] == "free" and not s["border"]:
            print("a free window keeps its frame; name a monitor first")
            return 2
    elif cmd == "json":
        print(json.dumps({"setting": s, "monitors": monitors(), "text": describe(s)}))
        return 0
    else:
        print(__doc__)
        return 2
    save(s)
    print("game window: %s" % describe(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
