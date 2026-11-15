#!/usr/bin/env python3
"""padsplit.py - a Barrels of Fun game's one window on a cabinet's screens
(PAD-1308).

    pythonw padsplit.py --title dune [--status FILE] [--parent PID]
                        [--focus last|vpx|<hwnd>] [--conf PATH]
                        [--to PART=X,Y,W,H ...] [--shot DIR] [--secs S]

A BoF game draws every display it has into ONE window: Dune's and
Labyrinth's are 1280x1110, the main display (1280x720, the backbox) over the
playfield display (1280x390, the strip over the playfield); Winchester's is
3286x768, the main display (1366x768) beside the 1920x720 one its backbox
reflects. On a cabinet each display has a monitor of its own. This shows
each part as a borderless, topmost window filling the monitor the user
picked for it, through a DWM thumbnail of the game's window: the GPU
composes it, so there is no copying and no delay.

The game's own window is WSLg's (msrdc's RAIL_WINDOW, the game plus a 32 px
invisible margin all round; each build titles it its own way, so it is
found by its size). It can't be minimised (that stops its picture) and,
measured here, it can't be moved off the desktop, made transparent, clipped
or cloaked from Windows either: msrdc refuses all of them and WSLg keeps
every window on a monitor. So the run puts it UNDER a part window - topmost
windows always cover an ordinary one - at the spot cover_spot() picks, and
tools/bof_emu/bofplace.py keeps it there from the Linux side (place_env()
is what a launcher passes to watch.sh). When it takes the focus, the focus
goes back to the window that had it (Visual Pinball's player first, with
--focus vpx: Visual Pinball pauses the table when it loses the focus).
Until the game is up each part's screen says what is starting, read from
the run's status file (padloading.py's protocol: `boot <pct> <words>`,
`up`, `failed <why>`, and `stop`, which ends this).

It ends when the game's window closes, the status says stop, --parent's
process is gone, or after --secs. The setting (which part on which monitor)
is `split.json` beside padisplay's display.conf, so the app's Emulate tab
and the Visual Pinball kit share it.

--to puts a part at a fixed spot instead of its monitor (a test's, off the
desktop); --shot saves each part window's picture there once the game is up
(PrintWindow with PW_RENDERFULLCONTENT sees the thumbnail, also off the
desktop).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import padisplay    # noqa: E402

CONF = os.path.join(os.path.dirname(padisplay.CONF), "split.json")

#: Each title's window in the game's own pixels: (width, height) and its
#: parts, (name, x, y, w, h). Read off live runs (PAD-1308): the main display
#: on top, the playfield display's 1280x390 strip under it.
#: Dune and Labyrinth: the main display over the 1280x390 strip on the
#: playfield; Winchester: the main display beside the 1920x720 one its
#: backbox reflects (drawn mirrored, as the machine's glass wants it; the
#: grey under it is the window's own background).
_STACKED = ((1280, 1110), (("main", 0, 0, 1280, 720), ("second", 0, 720, 1280, 390)))
LAYOUTS = {
    "dune": _STACKED,
    "labyrinth": _STACKED,
    "winchester": ((3286, 768), (("main", 0, 0, 1366, 768), ("second", 1366, 0, 1920, 720))),
}
#: the strip over the playfield, the same on every stacked BoF machine (the
#: machine's own second screen, tools/bof_emu/MULTIBOOT.md)
STRIP_H = 390
PARTS = ("main", "second")
#: what the second display is called on each title (and its own window's
#: title); the main one is always the main display
SECOND_NAMES = {"winchester": "Reflected display"}
SECOND_NAME = "Playfield display"
TITLE_NAMES = {"dune": "Dune", "labyrinth": "Jim Henson's Labyrinth",
               "winchester": "Winchester Mystery House"}
#: WSLg's invisible margin round a RAIL window, when the game's size is not
#: known to measure it by
MARGIN = 32
#: the game's window is told from WSLg's others by its size, not its title:
#: each build names its own ("Godot (Ubuntu)" for Dune, "GDCraze (DEBUG)
#: (Ubuntu)" for Labyrinth)
DEFAULT = {"on": False, "main": 0, "second": 0, "fit": "keep"}


def part_name(part, title=None):
    if part == "main":
        return "Main display"
    return SECOND_NAMES.get((title or "").lower(), SECOND_NAME)


# ----------------------------------------------------------------------
# the setting
# ----------------------------------------------------------------------
def load(path=None):
    """{"on", "main", "second", "fit"}: a monitor number per part
    (padisplay's numbering; 0 = that part is not shown) and "keep" (the
    part's shape, centred) or "fill" (stretched to the monitor)."""
    out = dict(DEFAULT)
    try:
        with open(path or CONF, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return out
    if isinstance(got, dict):
        out["on"] = bool(got.get("on"))
        for part in PARTS:
            try:
                out[part] = max(0, int(got.get(part) or 0))
            except (TypeError, ValueError):
                pass
        if got.get("fit") in ("keep", "fill"):
            out["fit"] = got["fit"]
    return out


def save(setting, path=None):
    path = path or CONF
    merged = dict(load(path))
    merged.update({k: v for k, v in setting.items() if k in DEFAULT})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1)
    os.replace(tmp, path)
    return load(path)


def active(setting):
    """Whether a run should be split: on, with a monitor for some part."""
    return bool(setting.get("on")) and any(setting.get(p) for p in PARTS)


# ----------------------------------------------------------------------
# the plan (pure: the tests run it on any OS)
# ----------------------------------------------------------------------
def layout(title, size=None):
    """(game (w, h), [(part, (x, y, w, h))]) for a title; a title not in
    LAYOUTS is cut by its window's size: the strip at the bottom, the rest
    the main display."""
    known = LAYOUTS.get((title or "").lower())
    if not (known and (size is None or tuple(size) == known[0])):
        known = next((v for v in LAYOUTS.values() if size and tuple(size) == v[0]), None)
    if known:
        return known[0], [(n, (x, y, w, h)) for n, x, y, w, h in known[1]]
    if size is None:
        return None, []
    w, h = size
    if h <= STRIP_H:
        return (w, h), [("main", (0, 0, w, h))]
    return (w, h), [("main", (0, 0, w, h - STRIP_H)),
                    ("second", (0, h - STRIP_H, min(w, 1280), STRIP_H))]


def fit_rect(part_wh, mon, fit="keep"):
    """Where a part goes on a monitor {"x", "y", "w", "h"}: the whole monitor
    ("fill"), or as big as its shape allows, centred ("keep")."""
    mx, my, mw, mh = mon["x"], mon["y"], mon["w"], mon["h"]
    if fit == "fill":
        return mx, my, mw, mh
    pw, ph = part_wh
    scale = min(mw / float(pw), mh / float(ph))
    w, h = int(round(pw * scale)), int(round(ph * scale))
    return mx + (mw - w) // 2, my + (mh - h) // 2, w, h


def plan(setting, title, mons, size=None, fixed=None):
    """[{"part", "src", "window", "dest"}] for the parts that have a monitor
    (or a --to spot): src in the game's pixels, window = the part window's
    rectangle on the desktop (the whole monitor, black round the picture),
    dest = the picture inside it, relative to that window."""
    _, parts = layout(title, size)
    by_n = {m["n"]: m for m in mons}
    out = []
    for name, src in parts:
        if fixed and name in fixed:
            x, y, w, h = fixed[name]
            win = (x, y, w, h)
        else:
            mon = by_n.get(setting.get(name) or 0)
            if not mon:
                continue
            win = (mon["x"], mon["y"], mon["w"], mon["h"])
        dx, dy, dw, dh = fit_rect(src[2:], {"x": 0, "y": 0, "w": win[2], "h": win[3]},
                                  setting.get("fit", "keep"))
        out.append({"part": name, "src": src, "window": win,
                    "dest": (dx, dy, dw, dh)})
    return out


def _overlap(a, b):
    """The area two (x, y, w, h) rectangles share."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def exposed(rect, plans, mons):
    """How much of the game's picture (x, y, w, h) shows: what lies on a
    monitor that no part window covers (off every monitor is never seen;
    the part windows are topmost and fill their monitors)."""
    covered = [p["window"] for p in plans]
    out = 0
    for m in mons:
        mr = (m["x"], m["y"], m["w"], m["h"])
        if any(_overlap(mr, c) == m["w"] * m["h"] for c in covered):
            continue
        out += _overlap(rect, mr)
    return out


def cover_spot(plans, game_wh, mons):
    """Where the game's window goes, its picture's top-left (X root
    coordinates = Windows' physical pixels): under a part window, at the
    corner of its monitor that leaves least of it showing elsewhere; the
    main display's monitor first on a tie. None with no part on a monitor
    (a test's --to spots): the window stays where WSLg put it."""
    gw, gh = game_wh
    best = None
    order = sorted(plans, key=lambda p: p["part"] != "main")
    for rank, p in enumerate(order):
        x, y, w, h = p["window"]
        if not any(_overlap((m["x"], m["y"], m["w"], m["h"]), (x, y, w, h)) for m in mons):
            continue
        for cx, cy in ((x, y), (x + w - gw, y), (x, y + h - gh), (x + w - gw, y + h - gh)):
            score = (exposed((cx, cy, gw, gh), plans, mons), rank)
            if best is None or score < best[0]:
                best = (score, (cx, cy))
    return best[1] if best else None


def is_game_size(win_wh, title):
    """Whether a WSLg window is the size of this title's game window (with
    or without the margin); a title not measured: tall enough to hold the
    strip and a display above it."""
    known = LAYOUTS.get((title or "").lower())
    sizes = [known[0]] if known else [v[0] for v in LAYOUTS.values()]
    for m in (0, MARGIN):
        if (win_wh[0] - 2 * m, win_wh[1] - 2 * m) in sizes:
            return True
    if known:
        return False
    gw, gh = game_size(win_wh)
    return gw >= 640 and gh > STRIP_H + 200


#: the size a title not in LAYOUTS is taken to open at until it does
DEFAULT_SIZE = (1280, 1110)


def spots(setting, mons):
    """{title: (x, y)} where each title's window goes under the part
    windows, "*" for a title not measured; {} when no part has a monitor."""
    out = {}
    for title in list(LAYOUTS) + ["*"]:
        size = LAYOUTS[title][0] if title in LAYOUTS else DEFAULT_SIZE
        spot = cover_spot(plan(setting, title, mons, size=size), size, mons)
        if spot:
            out[title] = spot
    return out


def place_env(setting=None, mons=None):
    """watch.sh's environment for a visible run: [] when the split is off,
    else PAD_BOF_SPLIT=1 (the shipped borderless window) and, when a part
    has a monitor, PAD_BOF_PLACE=<title>:X,Y;...;*:X,Y - a spot per title,
    since the title is only known once the .fun is unpacked (run_game.sh
    picks its own)."""
    setting = load() if setting is None else setting
    if not active(setting):
        return []
    mons = padisplay.monitors() if mons is None else mons
    env = ["PAD_BOF_SPLIT=1"]
    where = spots(setting, mons)
    if where:
        env.append("PAD_BOF_PLACE=" + ";".join(
            "%s:%d,%d" % (t, x, y) for t, (x, y) in where.items()))
    return env


def margins(win_wh, game_wh):
    """The invisible margin left and top of the game in its RAIL window."""
    if not game_wh:
        return MARGIN, MARGIN
    return (max(0, (win_wh[0] - game_wh[0]) // 2),
            max(0, (win_wh[1] - game_wh[1]) // 2))


def game_size(win_wh):
    """The game's size from its RAIL window's. The split's own runs open it
    unfocusable (Godot's no_focus), and WSLg gives such a window no title
    and no margin, measured: 1280x1110 for Dune; an ordinary one has the
    32 px margin all round. A known size says which; else no margin."""
    known = [v[0] for v in LAYOUTS.values()]
    for m in (0, MARGIN):
        if (win_wh[0] - 2 * m, win_wh[1] - 2 * m) in known:
            return win_wh[0] - 2 * m, win_wh[1] - 2 * m
    return tuple(win_wh)


def read_status(path):
    """(state, pct, words) from the status file's last line: state is
    "boot", "up", "failed", "stop" or "" (nothing yet)."""
    if not path:
        return "", None, ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return "", None, ""
    if not lines:
        return "", None, ""
    head, _, rest = lines[-1].partition(" ")
    if head == "boot":
        pct, _, words = rest.partition(" ")
        try:
            return "boot", max(0, min(100, int(float(pct)))), words
        except ValueError:
            return "boot", None, rest
    if head in ("up", "failed", "stop"):
        return head, None, rest
    return "boot", None, lines[-1]


def loading_lines(title, part, state, words):
    name = TITLE_NAMES.get((title or "").lower(), (title or "The game").title())
    if state == "failed":
        return [name, "could not start", words or ""]
    return [name, "is starting", words or "", part_name(part, title)]


# ----------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------
def _win32():
    import ctypes
    from ctypes import wintypes as W
    VP = ctypes.c_void_p
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32")
    k = ctypes.WinDLL("kernel32")
    d = ctypes.WinDLL("dwmapi")
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, VP, ctypes.c_uint, W.WPARAM, W.LPARAM)
    sig = {
        (u, "DefWindowProcW"): (LRESULT, [VP, ctypes.c_uint, W.WPARAM, W.LPARAM]),
        (u, "CreateWindowExW"): (VP, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, VP, VP, VP, VP]),
        (u, "DestroyWindow"): (W.BOOL, [VP]),
        (u, "SetWindowPos"): (W.BOOL, [VP, VP, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_uint]),
        (u, "GetWindowRect"): (W.BOOL, [VP, ctypes.POINTER(W.RECT)]),
        (u, "IsWindow"): (W.BOOL, [VP]),
        (u, "IsWindowVisible"): (W.BOOL, [VP]),
        (u, "GetForegroundWindow"): (VP, []),
        (u, "InvalidateRect"): (W.BOOL, [VP, VP, W.BOOL]),
        (u, "BeginPaint"): (VP, [VP, VP]),
        (u, "EndPaint"): (W.BOOL, [VP, VP]),
        (u, "FillRect"): (ctypes.c_int, [VP, ctypes.POINTER(W.RECT), VP]),
        (u, "DrawTextW"): (ctypes.c_int, [VP, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT),
                                          ctypes.c_uint]),
        (u, "GetClientRect"): (W.BOOL, [VP, ctypes.POINTER(W.RECT)]),
        (u, "GetWindowTextW"): (ctypes.c_int, [VP, W.LPWSTR, ctypes.c_int]),
        (u, "GetClassNameW"): (ctypes.c_int, [VP, W.LPWSTR, ctypes.c_int]),
        (u, "GetWindowThreadProcessId"): (W.DWORD, [VP, ctypes.POINTER(W.DWORD)]),
        (u, "PeekMessageW"): (W.BOOL, [VP, VP, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]),
        (u, "TranslateMessage"): (W.BOOL, [VP]),
        (u, "DispatchMessageW"): (LRESULT, [VP]),
        (u, "GetDC"): (VP, [VP]),
        (u, "ReleaseDC"): (ctypes.c_int, [VP, VP]),
        (u, "PrintWindow"): (W.BOOL, [VP, VP, ctypes.c_uint]),
        (g, "CreateSolidBrush"): (VP, [W.DWORD]),
        (g, "CreateFontW"): (VP, [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]),
        (g, "SelectObject"): (VP, [VP, VP]),
        (g, "DeleteObject"): (W.BOOL, [VP]),
        (g, "SetTextColor"): (W.DWORD, [VP, W.DWORD]),
        (g, "SetBkMode"): (ctypes.c_int, [VP, ctypes.c_int]),
        (g, "CreateCompatibleDC"): (VP, [VP]),
        (g, "CreateCompatibleBitmap"): (VP, [VP, ctypes.c_int, ctypes.c_int]),
        (g, "DeleteDC"): (W.BOOL, [VP]),
        (g, "GetDIBits"): (ctypes.c_int, [VP, VP, ctypes.c_uint, ctypes.c_uint, VP, VP,
                                          ctypes.c_uint]),
        (k, "OpenProcess"): (VP, [W.DWORD, W.BOOL, W.DWORD]),
        (k, "CloseHandle"): (W.BOOL, [VP]),
        (k, "GetExitCodeProcess"): (W.BOOL, [VP, ctypes.POINTER(W.DWORD)]),
        (k, "QueryFullProcessImageNameW"): (W.BOOL, [VP, W.DWORD, W.LPWSTR,
                                                     ctypes.POINTER(W.DWORD)]),
        (k, "GetModuleHandleW"): (VP, [W.LPCWSTR]),
        (d, "DwmRegisterThumbnail"): (ctypes.c_long, [VP, VP, ctypes.POINTER(VP)]),
        (d, "DwmUnregisterThumbnail"): (ctypes.c_long, [VP]),
        (d, "DwmUpdateThumbnailProperties"): (ctypes.c_long, [VP, VP]),
    }
    for (lib, name), (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return ctypes, W, VP, u, g, k, d, WNDPROC


class Splitter:
    """The part windows and their thumbnails, and the game window's minder."""

    WS_POPUP = 0x80000000
    WS_EX = 0x00000008 | 0x00000080 | 0x08000000   # TOPMOST|TOOLWINDOW|NOACTIVATE
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 1, 2, 4, 0x10, 0x40

    def __init__(self, title, plans, status=None, parent=None, focus="last",
                 shot_dir=None, log=None, setting=None, fixed=None):
        (self.ct, self.W, self.VP, self.u, self.g, self.k, self.d,
         self.WNDPROC) = _win32()
        self.title, self.plans = title, plans
        self.setting, self.fixed = setting or dict(DEFAULT), fixed or None
        self.status, self.parent, self.focus = status, parent, focus
        self.shot_dir, self.log = shot_dir, log or (lambda *_: None)
        self.state, self.pct, self.words = "", None, ""
        self.game = None            # the game's RAIL window
        self.shows = None           # how much of the game's picture shows (px)
        self.game_wh = None         # its game size (margin off)
        self.thumbs = []            # (part plan, thumbnail handle)
        self.shown = False          # thumbnails visible (the game is up)
        self.last_fg = None         # the last foreground that was not the game
        self.handbacks = 0
        self.focus_next = 0.0       # when a refused hand-back may try again
        self.focus_tries = 0
        self.failed_at = None
        self.shot_done = False
        self.loading_shot = False
        self.shot_at = 2.0          # seconds after up the --shot pictures are taken
        self.t0 = time.time()
        self.mons = padisplay.monitors()
        self.before = set(h for h, _ in self._rail_windows())
        self._proc = self.WNDPROC(self._wndproc)
        self._brush = self.g.CreateSolidBrush(0)
        self._fonts = {}
        self.windows = {}           # hwnd -> plan
        self._make_windows()

    # -- part windows ------------------------------------------------------
    def _make_windows(self):
        ct, W = self.ct, self.W
        inst = self.k.GetModuleHandleW(None)

        class WNDCLASSW(ct.Structure):
            _fields_ = [("style", ct.c_uint), ("lpfnWndProc", self.WNDPROC),
                        ("cbClsExtra", ct.c_int), ("cbWndExtra", ct.c_int),
                        ("hInstance", self.VP), ("hIcon", self.VP), ("hCursor", self.VP),
                        ("hbrBackground", self.VP), ("lpszMenuName", W.LPCWSTR),
                        ("lpszClassName", W.LPCWSTR)]
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = inst
        wc.hbrBackground = self._brush
        wc.lpszClassName = "PADSplitPart"
        self.u.RegisterClassW(ct.byref(wc))
        for p in self.plans:
            x, y, w, h = p["window"]
            hwnd = self.u.CreateWindowExW(
                self.WS_EX, "PADSplitPart",
                "%s - %s (PAD)" % (TITLE_NAMES.get(self.title, self.title),
                                   part_name(p["part"], self.title)),
                self.WS_POPUP, x, y, w, h, None, None, inst, None)
            if not hwnd:
                self.log("could not make the %s window" % p["part"])
                continue
            self.windows[hwnd] = p
            self.u.SetWindowPos(hwnd, self.VP(-1), x, y, w, h,
                                self.SWP_NOACTIVATE | self.SWP_SHOWWINDOW)
            self.log("%s: monitor window %s, picture %s" % (p["part"], (x, y, w, h), p["dest"]))

    def _font(self, size):
        if size not in self._fonts:
            self._fonts[size] = self.g.CreateFontW(-size, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0,
                                                   "Segoe UI")
        return self._fonts[size]

    def _wndproc(self, hwnd, msg, wp, lp):
        if msg == 0x0021:                     # WM_MOUSEACTIVATE
            return 3                          # MA_NOACTIVATE
        if msg == 0x000F:                     # WM_PAINT
            self._paint(hwnd)
            return 0
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def _paint(self, hwnd):
        ct, W = self.ct, self.W
        ps = (ct.c_byte * 72)()
        hdc = self.u.BeginPaint(hwnd, ps)
        rc = W.RECT()
        self.u.GetClientRect(hwnd, ct.byref(rc))
        self.u.FillRect(hdc, ct.byref(rc), self._brush)
        p = self.windows.get(hwnd)
        if p and not self.shown:
            lines = loading_lines(self.title, p["part"], self.state, self.words)
            h = rc.bottom
            big = max(18, min(64, h // 8))
            self.g.SetBkMode(hdc, 1)
            y = h // 2 - big * 2
            for i, line in enumerate(lines):
                if not line:
                    continue
                size = big if i == 0 else max(14, big // 2)
                old = self.g.SelectObject(hdc, self._font(size))
                self.g.SetTextColor(hdc, 0xFFFFFF if i == 0 else 0xC0C0C0)
                r = W.RECT(0, y, rc.right, y + int(size * 1.6))
                self.u.DrawTextW(hdc, line, -1, ct.byref(r), 0x1 | 0x20 | 0x4)  # CENTER|SINGLELINE|VCENTER
                self.g.SelectObject(hdc, old)
                y += int(size * 1.7)
            if self.pct is not None and self.state == "boot":
                bw = rc.right // 2
                bx, by = (rc.right - bw) // 2, y + big // 2
                bar = W.RECT(bx, by, bx + bw, by + max(4, big // 6))
                b1 = self.g.CreateSolidBrush(0x404040)
                self.u.FillRect(hdc, ct.byref(bar), b1)
                self.g.DeleteObject(b1)
                bar.right = bx + bw * self.pct // 100
                b2 = self.g.CreateSolidBrush(0x33AAFF)
                self.u.FillRect(hdc, ct.byref(bar), b2)
                self.g.DeleteObject(b2)
        self.u.EndPaint(hwnd, ps)

    def _repaint(self):
        for hwnd in self.windows:
            self.u.InvalidateRect(hwnd, None, True)

    # -- the game's window -------------------------------------------------
    def _exe(self, hwnd):
        ct, W = self.ct, self.W
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        hp = self.k.OpenProcess(0x1000, False, pid.value)
        if not hp:
            return ""
        buf = ct.create_unicode_buffer(520)
        n = W.DWORD(520)
        self.k.QueryFullProcessImageNameW(hp, 0, buf, ct.byref(n))
        self.k.CloseHandle(hp)
        return buf.value.rsplit("\\", 1)[-1].lower()

    def _rail_windows(self):
        """[(hwnd, (w, h))] of every visible WSLg window: msrdc's RAIL_WINDOWs."""
        ct = self.ct
        found = []
        proc = ct.WINFUNCTYPE(ct.c_bool, self.VP, self.VP)

        def cb(h, _):
            if self.u.IsWindowVisible(h):
                c = ct.create_unicode_buffer(64)
                self.u.GetClassNameW(h, c, 64)
                if c.value == "RAIL_WINDOW" and self._exe(h) == "msrdc.exe":
                    l, t, r, b = self._rect(h)
                    found.append((h, (r - l, b - t)))
            return True
        self.u.EnumWindows(proc(cb), None)
        return found

    def _rect(self, hwnd):
        r = self.W.RECT()
        self.u.GetWindowRect(hwnd, self.ct.byref(r))
        return r.left, r.top, r.right, r.bottom

    def _find_game(self):
        wins = [(h, wh) for h, wh in self._rail_windows() if is_game_size(wh, self.title)]
        new = [h for h, _ in wins if h not in self.before]
        pick = new[-1] if new else None
        if pick is None and len(wins) == 1 and self.state == "up":
            pick = wins[0][0]                 # split asked for a game already up
        if pick is None:
            return
        l, t, r, b = self._rect(pick)
        self.game = pick
        size = game_size((r - l, b - t))
        self.game_wh = size
        self.log("the game's window: %#x %s, %dx%d (game %dx%d)"
                 % (pick, (l, t), r - l, b - t, size[0], size[1]))
        # its parts as the window it opened says (a title the launch could not
        # name is known by its size; one never measured is cut by it)
        plans = plan(self.setting, self.title, self.mons, size=size, fixed=self.fixed)
        for hwnd, p in list(self.windows.items()):
            self.windows[hwnd] = next((q for q in plans if q["part"] == p["part"]), p)
        self.plans = list(self.windows.values())
        self._check_cover()
        self._thumbnails()

    def _check_cover(self):
        """Say when some of the game's own window shows beside the part
        windows (it should sit under one: bofplace.py keeps it there)."""
        l, t, r, b = self._rect(self.game)
        mx, my = margins((r - l, b - t), self.game_wh)
        pic = (l + mx, t + my, self.game_wh[0], self.game_wh[1])
        shows = exposed(pic, self.plans, self.mons)
        if shows != self.shows:
            self.shows = shows
            self.log("the game's window is at %s: %s" % (
                pic[:2], "under the part windows" if not shows
                else "%d px of it show beside them" % shows))

    def _thumbnails(self):
        class PROPS(self.ct.Structure):
            _fields_ = [("dwFlags", self.W.DWORD), ("rcDestination", self.W.RECT),
                        ("rcSource", self.W.RECT), ("opacity", self.ct.c_ubyte),
                        ("fVisible", self.W.BOOL), ("fSourceClientAreaOnly", self.W.BOOL)]
        self._PROPS = PROPS
        l, t, r, b = self._rect(self.game)
        mx, my = margins((r - l, b - t), self.game_wh)
        for hwnd, p in self.windows.items():
            th = self.VP()
            hr = self.d.DwmRegisterThumbnail(hwnd, self.game, self.ct.byref(th))
            if hr != 0:
                self.log("%s: DwmRegisterThumbnail failed %#x" % (p["part"], hr & 0xffffffff))
                continue
            sx, sy, sw, sh = p["src"]
            p = dict(p, rc_source=(mx + sx, my + sy, mx + sx + sw, my + sy + sh))
            self.thumbs.append((p, th))
        self._show(self.shown)

    def _show(self, visible):
        for p, th in self.thumbs:
            pr = self._PROPS()
            pr.dwFlags = 0x1 | 0x2 | 0x4 | 0x8 | 0x10
            dx, dy, dw, dh = p["dest"]
            pr.rcDestination = self.W.RECT(dx, dy, dx + dw, dy + dh)
            pr.rcSource = self.W.RECT(*p["rc_source"])
            pr.opacity = 255
            pr.fVisible = bool(visible)
            pr.fSourceClientAreaOnly = False
            self.d.DwmUpdateThumbnailProperties(th, self.ct.byref(pr))

    # -- the focus ---------------------------------------------------------
    def _focus_target(self):
        if self.focus not in ("last", "vpx"):
            try:
                h = int(self.focus, 0)
                if self.u.IsWindow(self.VP(h)):
                    return h
            except ValueError:
                pass
        if self.focus == "vpx":
            try:
                import padcontroller
                h = padcontroller.find_player_window()
                if h:
                    return h
            except Exception:                               # noqa: BLE001
                pass
        return self.last_fg

    def give_focus(self, target, fg):
        """The foreground to `target`, from `fg` (the game's window). True
        only when target is in front after. Windows lets a process that is
        not in front set the foreground only if it made the last input:
        msrdc's thread can't be attached to (it refused every cross-process
        call measured here), so the plain hand-over is refused, and an ALT
        press and release first makes this process the last input's - the
        game sees a lone ALT, which none of the titles uses."""
        try:
            import padcontroller
            if padcontroller.hand_foreground(target, fg):
                return True
        except Exception:                                   # noqa: BLE001
            pass
        ct = self.ct
        u = self.u
        u.keybd_event.argtypes = [ct.c_ubyte, ct.c_ubyte, self.W.DWORD, ct.c_size_t]
        u.SetForegroundWindow.argtypes = [self.VP]
        u.keybd_event(0x12, 0, 0, 0)               # VK_MENU down
        u.keybd_event(0x12, 0, 0x0002, 0)          # and up
        u.SetForegroundWindow(self.VP(target))
        return u.GetForegroundWindow() == target

    def _integrity(self, pid=None):
        """A process's integrity level (0x2000 medium, 0x3000 high), this
        one's with no pid; 0 when it can't be read."""
        ct, W = self.ct, self.W
        adv = ct.WinDLL("advapi32")
        adv.OpenProcessToken.argtypes = [self.VP, W.DWORD, ct.POINTER(self.VP)]
        adv.GetTokenInformation.argtypes = [self.VP, ct.c_int, self.VP, W.DWORD, ct.POINTER(W.DWORD)]
        adv.GetSidSubAuthorityCount.restype = ct.POINTER(ct.c_ubyte)
        adv.GetSidSubAuthorityCount.argtypes = [self.VP]
        adv.GetSidSubAuthority.restype = ct.POINTER(W.DWORD)
        adv.GetSidSubAuthority.argtypes = [self.VP, W.DWORD]
        self.k.GetCurrentProcess.restype = self.VP
        hp = self.k.OpenProcess(0x1000, False, pid) if pid else self.k.GetCurrentProcess()
        if not hp:
            return 0
        tok = self.VP()
        try:
            if not adv.OpenProcessToken(hp, 8, ct.byref(tok)):
                return 0
            buf = ct.create_string_buffer(64)
            n = W.DWORD()
            if not adv.GetTokenInformation(tok, 25, buf, 64, ct.byref(n)):
                return 0
            sid = ct.cast(buf, ct.POINTER(self.VP))[0]
            count = adv.GetSidSubAuthorityCount(sid)[0]
            return adv.GetSidSubAuthority(sid, count - 1)[0]
        finally:
            if tok:
                self.k.CloseHandle(tok)
            if pid:
                self.k.CloseHandle(hp)

    def _higher(self, hwnd):
        """Whether a window's process runs above this one's integrity."""
        pid = self.W.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        return self._integrity(pid.value) > self._integrity()

    def _mind_focus(self):
        fg = self.u.GetForegroundWindow()
        if not fg:
            return
        if self.game and fg == self.game:
            now = time.time()
            if now < self.focus_next:
                return
            target = self._focus_target()
            if target and self.u.IsWindow(self.VP(target)):
                ok = self.give_focus(target, fg)
                self.handbacks += 1
                # a refusal waits a little longer each time (never a storm of
                # presses), a success is ready for the next take at once
                self.focus_tries = 0 if ok else self.focus_tries + 1
                self.focus_next = now + (0 if ok else min(5.0, 0.5 * self.focus_tries))
                self.log("the game's window took the focus: given back to %#x (%s)"
                         % (target, "ok" if ok else "refused"))
                if not ok and self.focus_tries == 1 and self._higher(fg):
                    self.log("the game's window runs as administrator (WSL was started "
                             "by an elevated program) and this does not: Windows won't "
                             "let it take the focus back")
        elif fg not in self.windows and fg != self.game:
            self.last_fg = fg
            self.focus_tries = 0

    # -- the run -----------------------------------------------------------
    def _parent_alive(self):
        if not self.parent:
            return True
        hp = self.k.OpenProcess(0x1000, False, int(self.parent))
        if not hp:
            return False
        code = self.W.DWORD()
        self.k.GetExitCodeProcess(hp, self.ct.byref(code))
        self.k.CloseHandle(hp)
        return code.value == 259              # STILL_ACTIVE

    def tick(self):
        """One look round; False when it is time to end."""
        if not self._parent_alive():
            self.log("the process that started this is gone")
            return False
        state, pct, words = read_status(self.status)
        if (state, pct, words) != (self.state, self.pct, self.words):
            self.state, self.pct, self.words = state, pct, words
            if not self.shown:
                self._repaint()
        if state == "stop":
            self.log("asked to stop")
            return False
        if state == "failed":
            if self.failed_at is None:
                self.failed_at = time.time()
                self.log("the start failed: %s" % words)
            return time.time() - self.failed_at < 6
        if (self.shot_dir and not self.loading_shot and not self.shown
                and self.state == "boot" and time.time() - self.t0 > 1.5):
            self.loading_shot = True
            self.shots("loading")
        if self.game is None:
            self._find_game()
        elif not self.u.IsWindow(self.game):
            self.log("the game's window closed")
            self.game = None
            return False
        if self.game is not None:
            self._check_cover()
            # the picture shows once the game is up (or, with no status file
            # to say so, once its window is there)
            up = state == "up" or (not self.status and self.game is not None)
            if up and not self.shown:
                self.shown = True
                self._show(True)
                self._repaint()
                self.log("the game is up: showing its picture")
                self.up_at = time.time()
            if self.shown and self.shot_dir and not self.shot_done \
                    and time.time() - self.up_at > self.shot_at:
                self.shot_done = True
                self.shots("split")
        self._mind_focus()
        return True

    def run(self, secs=None):
        ct = self.ct
        msg = (ct.c_byte * 48)()
        t0 = time.time()
        next_tick = 0.0
        while True:
            while self.u.PeekMessageW(msg, None, 0, 0, 1):
                self.u.TranslateMessage(msg)
                self.u.DispatchMessageW(msg)
            now = time.time()
            if now >= next_tick:
                next_tick = now + 0.1
                if not self.tick():
                    break
            if secs and now - t0 > secs:
                self.log("time is up")
                break
            time.sleep(0.01)
        self.close()

    def close(self):
        for _, th in self.thumbs:
            self.d.DwmUnregisterThumbnail(th)
        self.thumbs = []
        for hwnd in list(self.windows):
            self.u.DestroyWindow(hwnd)
        self.windows = {}
        self.log("done: %d focus hand-back(s)" % self.handbacks)

    # -- proof -------------------------------------------------------------
    def grab(self, hwnd):
        """A part window's picture (PIL Image), thumbnail included."""
        ct = self.ct
        l, t, r, b = self._rect(hwnd)
        w, h = r - l, b - t
        sdc = self.u.GetDC(None)
        mdc = self.g.CreateCompatibleDC(sdc)
        bmp = self.g.CreateCompatibleBitmap(sdc, w, h)
        old = self.g.SelectObject(mdc, bmp)
        self.u.PrintWindow(hwnd, mdc, 2)      # PW_RENDERFULLCONTENT
        hdr = (ct.c_uint32 * 10)(40, w, (-h) & 0xffffffff, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = ct.create_string_buffer(w * h * 4)
        self.g.GetDIBits(mdc, bmp, 0, h, buf, hdr, 0)
        self.g.SelectObject(mdc, old)
        self.g.DeleteObject(bmp)
        self.g.DeleteDC(mdc)
        self.u.ReleaseDC(None, sdc)
        from PIL import Image
        return Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).convert("RGB")

    def shots(self, kind):
        os.makedirs(self.shot_dir, exist_ok=True)
        for hwnd, p in self.windows.items():
            path = os.path.join(self.shot_dir, "%s_%s.png" % (kind, p["part"]))
            try:
                self.grab(hwnd).save(path)
                self.log("saved %s" % path)
            except Exception as exc:                        # noqa: BLE001
                self.log("could not save %s: %s" % (path, exc))


def _spot(text):
    part, _, rect = text.partition("=")
    x, y, w, h = (int(v) for v in rect.split(","))
    return part, (x, y, w, h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--title", default="", help="the game's key (dune, ...), if known")
    ap.add_argument("--status")
    ap.add_argument("--parent", type=int)
    ap.add_argument("--focus", default="last")
    ap.add_argument("--conf")
    ap.add_argument("--to", action="append", default=[], type=_spot)
    ap.add_argument("--shot")
    ap.add_argument("--shot-at", type=float, default=2.0,
                    help="seconds after the game is up to take the --shot pictures")
    ap.add_argument("--secs", type=float)
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    logf = open(a.log, "a", encoding="utf-8") if a.log else None

    def log(text):
        line = "%s padsplit: %s" % (time.strftime("%H:%M:%S"), text)
        if logf:
            logf.write(line + "\n")
            logf.flush()
        else:
            try:
                print(line, flush=True)
            except Exception:                               # noqa: BLE001
                pass
    if sys.platform != "win32":
        log("Windows only")
        return 2
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # physical pixels
    except Exception:                                       # noqa: BLE001
        ctypes.windll.user32.SetProcessDPIAware()
    setting = load(a.conf)
    title = a.title.lower()
    fixed = dict(a.to)
    plans = plan(setting, title, padisplay.monitors(), fixed=fixed or None,
                 size=None if title in LAYOUTS else DEFAULT_SIZE)
    if not plans:
        log("no part has a screen: nothing to do")
        return 1
    sp = Splitter(title, plans, status=a.status, parent=a.parent, focus=a.focus,
             shot_dir=a.shot, log=log, setting=setting, fixed=fixed or None)
    sp.shot_at = a.shot_at
    sp.run(a.secs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
