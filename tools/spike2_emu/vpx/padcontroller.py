#!/usr/bin/env python3
"""padcontroller.py - PAD.Controller: the Spike 2 emulator as a Visual Pinball
controller, in the shape of VPinMAME.Controller.

    python padcontroller.py --register      once, as the user (HKCU; no admin)
    python padcontroller.py --unregister
    python padcontroller.py --status        is a run up, what the map says
    python padcontroller.py --selftest      drive it through COM from Python

A VPX table script does `Set Controller = CreateObject("PAD.Controller")`
(PADSPIKE2.vbs does it inside LoadVPM) and core.vbs then talks to it exactly
as it talks to VPinMAME: `Controller.Switch(n) = 1` when a ball closes a
switch, `Controller.ChangedSolenoids` and `Controller.ChangedLamps` every
timer tick for what the game did, `Controller.Solenoid(n)` from cvpmMagnet,
`Run`/`Stop`/`Pause` around the session.

BEHIND IT IS THE RIG, NOT A ROM. The game is the real Spike 2 binary running
under tools/spike2_emu (watch.sh, or the app's Emulate tab) in WSL. This
server attaches to that run through the two shared blocks every other host
tool uses:

  switches IN   padsw   (padsw.h) - written from INSIDE WSL by swkeys.py,
                one helper for the session, fed "<id> <level>" lines down a
                pipe, because a Windows write to the guest's mmap races it
                across the 9p boundary (playfield.py, the same rule).
  lamps, coils  padled  (padled.h) - re-opened and read over \\wsl.localhost
  OUT           by a poll thread (never mapped, never held open: a held
                handle reads a frozen cache over 9p).

PAD-1306: BOTH NOW GO THROUGH ONE HELPER, padlink.py, run inside WSL beside
the game. It maps padled and padsw there, compares them every 2 ms and
pushes only the changes up the wsl.exe pipe (RigLink keeps the copy the poll
reads), and takes the switch lines swkeys.py took, reading each back off the
merge and writing it again until the game has it (padsw.Confirmer). The two
lines above are the fallback: no HELLO, an ERR, or 6 s without a ping and the
session drops back to them, every held switch handed over. PAD_VPX_LINK=0
starts there.

The LCD is the game's own window: nothing to bridge. Sound is the rig's.

NUMBERING, shared with PADSPIKE2.vbs and the .vpxmap.json files:

    switch   1000 + <Spike 2 switch id>          switch_list.txt `id`
    solenoid 1000 + <node> * 16 + <coil index>   device_xy coil (group->node)
    lamp     1000 + <node> * 100 + <LED index>   led_io.txt

A number below 1000 is a table's ORIGINAL number and goes through the map
(`switch_rewrite`, `solenoids`, `lamps`), so a table can be driven with its
script left on its old numbering while the map is being built.

    service  9000 + <node 0 bit>                 SERVICE below

The coin door's four service buttons sit on the same wire on every Spike 2
machine (node 0, bits 8-11) but under a different switch id per title
(Godzilla's 28 is Batman's Service Select), so a table names the button and
this resolves it through the run's switch_list.txt (PAD-882).

WHICH MAP: `Controller.GameName` names the title (`godzilla_le`), and
`<title>.vpxmap.json` beside this file is loaded on `Run`. No map = the
1000+ convention alone, which is enough to start.

WHICH RIG: the one padpath finds - `PAD_WSL_DISTRO`, `PAD_ROOT_WSL`,
`PAD_SLOT` when the environment carries them (the app sets them for the
tools it launches), else the default distro's ~/spike2root, like every
helper run by hand. Visual Pinball is started by the user, so this process
sees the user's environment: set those three in the shell that starts VPX
to aim at another rig.

COM. One out-of-process server (pythonw.exe, LocalServer32 under HKCU):
Visual Pinball is 64-bit and this Python need not be; the calls are
~50 us round trips, and core.vbs makes a few hundred a second. DynamicPolicy
answers every name, so a VPinMAME member this does not model (DIP, NVRAM,
the DMD) is a no-op rather than a script error - the table scripts wrap
those in On Error Resume Next anyway.
"""
import atexit
import json
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import coilmap    # noqa: E402  offsets into padled, the drive decoder
import padpath    # noqa: E402  where the rig is
import padsw      # noqa: E402  offsets into padsw
import bootprog   # noqa: E402  how far a Spike 2 boot is, off the run's own log (PAD-963)
import padlaunch  # noqa: E402  starts a run for a table when none is up
import s1bridge   # noqa: E402  the Spike 1 rig's files, for a Spike 1 title (PAD-943)
import spkbridge  # noqa: E402  the Spooky rig's files, for a Spooky title (PAD-952)
import bofbridge  # noqa: E402  the Barrels of Fun rig's files (PAD-1305)
import padcabinet  # noqa: E402  a cabinet's backglass and button lights (PAD-1304)
SLOT_BRIDGES = {"spike1": s1bridge, "spooky": spkbridge, "bof": bofbridge}

try:
    import pythoncom
    import winerror
    from win32com.server import policy as _policy, register as _reg, util as _util
    from win32com.server.exception import COMException
except ImportError:            # a Linux test run; the COM half is Windows only
    pythoncom = None


def _anything():
    """A COM object that takes any property (Games(...).Settings.Value(...))."""
    return _util.wrap(_Anything(), usePolicy=_policy.DynamicPolicy)

CLSID = "{7D5B2A1E-6C3F-4B8A-9E21-5A2F0C7D9B11}"
PROGID = "PAD.Controller"
VERSION = "03060000"            # what core.vbs compares; modulated solenoids off

SW_SRC = "v"                    # padsw.h's writer tag for Visual Pinball
POLL_S = 0.008                  # padled poll; a 9p read is ~1-3 ms
READ_N = max(coilmap.HI_READ, coilmap.STEP_READ)   # one read takes every plane
LAMP_ON = int(os.environ.get("PAD_VPX_LAMP_ON", "1"))   # LED level that is "lit"
MIN_PULSE_MS = 40               # a coil pulse shorter than a poll still shows
FRONT_WATCH_S = 300             # how long after Run a started run's windows are watched
FRONT_SETTLE_S = 10.0           # after the game is up, its windows' grabs are still undone (PAD-949)
FRONT_TRIES = 10                # hand-backs Windows refused before a window is left alone
#: the coin door's service buttons by number: {number: (node, bit)}
SERVICE = {9008: (0, 8),        # Service Select
           9009: (0, 9),        # Service Plus
           9010: (0, 10),       # Service Minus
           9011: (0, 11)}       # Service Back
#: PAD-952: a map's cabinet can name the coin door's buttons itself (a
#: Spooky machine's are MENU ENTER, VOLUME UP / DOWN, MENU BACK: no Stern wire)
SERVICE_KEYS = {9008: "service_select", 9009: "service_plus", 9010: "service_minus",
                9011: "service_back"}
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPATCH_PROPERTYPUT = 1, 2, 4

LOG = os.path.join(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp",
                   "padcontroller.log")


# The log is written by one daemon thread, never by the caller: set_switch
# logs every flipper press inside Visual Pinball's synchronous COM call (its
# main thread) and _sol_set logs holding the bridge lock, so an open+append
# there put file I/O in the flipper's path. Lines are queued and written in
# batches; whatever is still queued at exit is flushed by atexit.
_LOGQ = queue.Queue()
_LOG_THREAD = None
_LOG_START = threading.Lock()


def _log_write(lines):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("".join(lines))
    except OSError:
        pass


def _log_drain():
    lines = []
    try:
        while True:
            lines.append(_LOGQ.get_nowait())
    except queue.Empty:
        pass
    return lines


def _log_writer():
    while True:
        lines = [_LOGQ.get()] + _log_drain()
        _log_write(lines)


def _log_flush():
    lines = _log_drain()
    if lines:
        _log_write(lines)


atexit.register(_log_flush)


def log(msg):
    global _LOG_THREAD
    _LOGQ.put("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    if _LOG_THREAD is None:
        with _LOG_START:
            if _LOG_THREAD is None:
                _LOG_THREAD = threading.Thread(target=_log_writer, daemon=True, name="padlog")
                _LOG_THREAD.start()


# ---------------------------------------------------------------- the map --

#: where the user's own maps go (vpxgen.py writes a generated table's there)
USER_MAPS = os.path.join(os.path.expanduser("~"), ".pad-vpx", "maps")

#: the game's LCD is 16:9 (1360x768 on Spike 2)
LCD_ASPECT = 16.0 / 9.0


def lcd_rect(setting, mons, aspect=LCD_ASPECT):
    """(x, y, w, h) for the LCD window: the kit's `lcd` setting against the
    monitors [(left, top, right, bottom), ...] (the first is the main one).
    A `monitor` n (1-based) fills that screen; `x y w h` is taken as is;
    otherwise the upper middle of the main screen, 40% of its width."""
    setting = setting or {}
    if not mons:
        mons = [(0, 0, 1920, 1080)]
    if all(k in setting for k in ("x", "y", "w", "h")):
        return int(setting["x"]), int(setting["y"]), int(setting["w"]), int(setting["h"])
    n = setting.get("monitor")
    if n and 1 <= int(n) <= len(mons):
        l, t, r, b = mons[int(n) - 1]
        return l, t, r - l, b - t
    l, t, r, b = mons[0]
    w = int((r - l) * 0.4)
    h = int(w / aspect)
    return l + ((r - l) - w) // 2, t, w, h


def monitors():
    """Every monitor's rectangle, the main one first (pywin32 or nothing)."""
    try:
        import win32api
        out = []
        for hmon, _, rect in win32api.EnumDisplayMonitors(None, None):
            info = win32api.GetMonitorInfo(hmon)
            out.append((tuple(rect), bool(info.get("Flags", 0) & 1)))
        out.sort(key=lambda m: not m[1])
        return [r for r, _ in out]
    except Exception:                                       # noqa: BLE001
        return []


#: how long after a window's first placement a WSLg reset to the top-left
#: is undone; after that the window is wherever the user put it
PLACE_S = 15.0


def find_kit_window(word):
    """A started run's window: the top-level window whose title carries the
    kit's label and `word` (watch.sh titles them `[rig N: PAD-VPX] <title> -
    Stern Spike 2 emulator (...)` and `... - virtual playfield`)."""
    import ctypes
    u = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, buf, 256)
            if padlaunch.LABEL in buf.value and word in buf.value:
                found.append(h)
        return True
    u.EnumWindows(proc(cb), 0)
    return found[0] if found else 0


def find_lcd_window():
    return find_kit_window("emulator")


def window_pid(hwnd):
    import ctypes
    pid = ctypes.c_ulong(0)
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    return pid.value


def hand_foreground(hwnd, fg):
    """The foreground to `hwnd`, from the window `fg` that has it, with
    the input of fg's thread attached (Windows lets a thread that shares
    the foreground's input take it). True only when hwnd is in front after:
    SetForegroundWindow says yes when it only flashed the taskbar button."""
    import ctypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    fg_tid = u.GetWindowThreadProcessId(ctypes.c_void_p(fg), None)
    me = k.GetCurrentThreadId()
    attached = bool(fg_tid) and fg_tid != me and u.AttachThreadInput(me, fg_tid, True)
    try:
        u.ShowWindow(ctypes.c_void_p(hwnd), 9)              # SW_RESTORE, if it was minimised
        u.SetForegroundWindow(ctypes.c_void_p(hwnd))
        u.BringWindowToTop(ctypes.c_void_p(hwnd))
    finally:
        if attached:
            u.AttachThreadInput(me, fg_tid, False)
    return u.GetForegroundWindow() == hwnd


#: B2S.Server's own windows, by how B2SScreen.vb titles them: the backglass
#: ("B2S Backglass" / "B2S Backglass Server") and its DMD ("B2S DMD")
B2S_TITLES = ("B2S Backglass", "B2S DMD")


def b2s_window(title):
    """Whether a window is the backglass's (PAD-893)."""
    return title.startswith(B2S_TITLES)


def find_player_window():
    """Visual Pinball's playfield: the visible top-level "Visual Pinball
    Player" window, as B2S.Server finds it - for a table that ran the
    controller without GetPlayerHWnd."""
    import ctypes
    u = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, buf, 256)
            if buf.value.startswith("Visual Pinball Player"):
                found.append(h)
        return True
    u.EnumWindows(proc(cb), 0)
    return found[0] if found else 0


def kit_window_in_front():
    """Whether the foreground window is one of the kit's run's own."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        fg = u.GetForegroundWindow()
        if not fg:
            return False
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(fg, buf, 256)
        return padlaunch.LABEL in buf.value
    except Exception:                                       # noqa: BLE001
        return False


def at_reset_spot(rect):
    """Where WSLg puts a window back: the screen's top-left corner."""
    return rect[0] <= 0 and rect[1] <= 0


def dpi_aware():
    """This process in physical pixels: a process that is not DPI aware has
    its window coordinates virtualised, and a WSLg window moved from one
    ended up at the screen's top-left at the scaled size (150% here)."""
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:                                       # noqa: BLE001
        pass


def place_window(hwnd, rect, topmost=True):
    import ctypes
    u = ctypes.windll.user32
    x, y, w, h = rect
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_SHOWWINDOW, SWP_NOACTIVATE = 0x0040, 0x0010
    u.ShowWindow(hwnd, 9)                                   # SW_RESTORE
    u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST if topmost else HWND_NOTOPMOST),
                   x, y, w, h, SWP_SHOWWINDOW | SWP_NOACTIVATE)
    return window_rect(hwnd)


def raise_window(hwnd, topmost=True):
    """On top (or not) WITHOUT moving it: the z-order only. Moving a WSLg
    window from this side breaks dragging it (padglhost.c, "THE DELAYED
    MOVE"); where it goes is the renderer's, from display.conf (PAD-811)."""
    import ctypes
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
    ctypes.windll.user32.SetWindowPos(
        ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST if topmost else HWND_NOTOPMOST),
        0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


def display_setting():
    """The game window's display setting (padisplay.py), or None when it is
    free - then the kit's own `lcd` placement below still applies."""
    try:
        import padisplay
        s = padisplay.load()
        return None if s.get("mode", "free") == "free" else s
    except Exception:                                       # noqa: BLE001
        return None


def carry_lcd_layout(kit, conf=None, mons=None):
    """PAD-1131: a Visual Pinball layout saved before the display setting
    existed (PAD-811 came a day after the layouts) left only the kit's LCD
    rectangle, so its run MOVED the framed WSLg window over the second
    screen from this side, and the title bar and edges stayed visible ("the
    windows border is visible ... when it goes full screen"). With the
    display setting free, that rectangle becomes the setting the layout
    writes today (full screen, borderless, on the monitor it fills), once:
    the kit is marked so a later choice of "free" on the Emulate tab holds.
    Returns the setting written, or None."""
    lcd = kit.get("lcd") or {}
    if kit.get("display_carried") or not all(k in lcd for k in ("x", "y", "w", "h")):
        return None
    kit["display_carried"] = True
    import padisplay
    conf = conf or padisplay.CONF
    if padisplay.load(conf).get("mode", "free") != "free":
        return None
    mons = mons or padisplay.monitors()
    s = padisplay.for_rect([lcd["x"], lcd["y"], lcd["w"], lcd["h"]], mons)
    if s["mode"] == "free":
        return None
    padisplay.save(s, conf, mons)
    return s


def window_rect(hwnd):
    import ctypes
    r = (ctypes.c_long * 4)()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), r)
    return r[0], r[1], r[2] - r[0], r[3] - r[1]


def keep_proportions(before, now, aspect):
    """The playfield picture's size after a resize, in the table's own
    proportions (PAD-845): the side the user dragged wins. A side edge
    changes the width, so the height follows; a top or bottom edge only the
    height, so the width follows (keeping the width put a bottom-edge drag
    straight back); a corner, whichever changed more."""
    cw, ch = now
    if before and before[0] and before[1]:
        dw, dh = abs(cw - before[0]) / float(before[0]), abs(ch - before[1]) / float(before[1])
        if dh > dw:
            return int(round(ch / aspect)), ch
    return cw, int(round(cw * aspect))


def fit_on_monitor(rect, aspect, mons):
    """The saved playfield place, made to fit its monitor (PAD-851). The
    place is saved as a WIDTH, the height following each table's own
    proportions, so a width filled by a wide table (Iron Maiden, 2881) made
    a tall one (JAWS) 4322 high on a 2160 screen, half of it off the
    bottom. Scaled down to the monitor the window's middle is on (the main
    one when none), in proportion, and moved inside it."""
    x, y, w, h = rect
    if not mons:
        return rect
    cx, cy = x + w // 2, y + h // 2
    m = next((m for m in mons if m[0] <= cx < m[2] and m[1] <= cy < m[3]),
             next((m for m in mons if m[0] <= x < m[2] and m[1] <= y < m[3]), mons[0]))
    mw, mh = m[2] - m[0], m[3] - m[1]
    if w > mw or h > mh:
        w = min(mw, int(mh / aspect))
        h = int(round(w * aspect))
    x = min(max(x, m[0]), m[2] - w)
    y = min(max(y, m[1]), m[3] - h)
    return x, y, w, h


def fill_monitor(win, client, mon):
    """The largest window on monitor `mon` (left, top, right, bottom) whose
    picture keeps its proportions, centred: the maximize box or a title-bar
    double-click (PAD-845). `win` and `client` are (x, y, w, h)."""
    fw, fh = win[2] - client[2], win[3] - client[3]
    mw, mh = mon[2] - mon[0], mon[3] - mon[1]
    aspect = client[3] / float(client[2]) if client[2] else 1.0
    ncw = min(mw - fw, int((mh - fh) / aspect))
    nw, nh = ncw + fw, int(round(ncw * aspect)) + fh
    return mon[0] + (mw - nw) // 2, mon[1] + (mh - nh) // 2, nw, nh


def raw_leds(v):
    """A raw_lamp_rewrite value as its LEDs: one (node, index), or several."""
    return v if isinstance(v[0], tuple) else (v,)


class VpxMap:
    """A title's .vpxmap.json, reduced to the three lookups the server makes."""

    def __init__(self, title=None):
        self.title = title
        self.game = title                   # variants may share one native game
        self.switch_rewrite = {}            # old table number -> Spike 2 id
        self.solenoids = {}                 # number -> (node, index)
        self.lamp_groups = {}               # number -> [(node, index), ...]
        self.raw_lamp_rewrite = {}          # legacy number -> one LED read as its raw level
        self.led_lamps = True               # every LED also as 1000 + node * 100 + index
        self.rgb_groups = set()             # numbers whose LEDs are an insert's R, G, B
        self.rgb_order = {}                 # number -> "BGR" etc. when not listed R, G, B (PAD-1097)
        self.fakes = {}                     # name -> dict (switch_fakes)
        self.game_on = None                 # (number, [coils]) "flippers armed"
        self.cabinet = {}                   # cabinet switch names -> 1000+id
        self.mechs = {}                     # GetMech(n) -> (node, motor) of a stepper (PAD-1228)
        self.platform = "spike2"            # which rig the title runs on (PAD-943)
        # core.vbs indexes SolCallback(68) and friends by the number it is
        # handed, so ChangedSolenoids may only carry numbers up to this; a
        # coil's 1000+ name still answers Controller.Solenoid(n).
        self.sol_max = 68
        self._load_dof({})
        # a rebuilt table's map (<title>.vpxmap.json) or a shadow-patched
        # tribute's (<title>.shadow.json, vpxshadow.py): same keys where
        # they overlap - solenoids, game_on, cabinet, solenoid_max. The
        # user's own maps (a generated table's, vpxgen.py) live in
        # ~/.pad-vpx/maps, since an installed kit's folder is not writable.
        self.path = None
        for d in (USER_MAPS, HERE):
            for suffix in (".vpxmap.json", ".shadow.json"):
                path = os.path.join(d, "%s%s" % (title, suffix)) if title else None
                if path and os.path.exists(path):
                    self.load(path)
                    self.path = path
                    break
            if self.path:
                break

    def load(self, path):
        m = json.load(open(path, encoding="utf-8"))
        game = m.get("game")
        self.game = game if isinstance(game, str) and game else self.title
        self.platform = (m.get("platform") or "spike2").lower()
        g = m.get("game_on") or {}
        self.game_on = (int(g["number"]), [tuple(c) for c in g["coils"]]) if g else None
        self.cabinet = {k: int(v) for k, v in m.get("cabinet", {}).items()
                        if k != "_" and isinstance(v, int)}
        for k, v in m.get("switch_rewrite", {}).items():
            if k != "_":
                self.switch_rewrite[int(k)] = int(v)
        self.sol_max = int(m.get("solenoid_max", 68))
        # every LED is also reported as its own number, 1000 + node * 100 +
        # index, for a table that names LEDs directly (PAD-859). A SAM table
        # whose LampTimer indexes its own lamp arrays (Walking Dead's are 220
        # long) with every number ChangedLamps hands it stops on those with
        # "Subscript out of range" (PAD-1560): its map says "led_lamps": false
        self.led_lamps = bool(m.get("led_lamps", True))
        self.raw_lamp_rewrite = {}
        for k, v in m.get("raw_lamp_rewrite", {}).items():
            if k == "_":
                continue
            # a legacy number (below 1000: 1000+ is already every LED's own
            # number) -> one [node, index]; anything else would be set twice
            # a poll and report a change every frame. PAD-1560: or a list of
            # them, read as the brightest - a SAM table's one-colour insert on
            # an RGB insert of the newer game lights whatever colour it is given
            pair = lambda p: (isinstance(p, list) and len(p) == 2
                              and all(isinstance(x, int) for x in p))
            ok = 0 < int(k) < 1000 and isinstance(v, list) and (
                pair(v) or (v and all(pair(p) for p in v)))
            if not ok:
                raise ValueError("raw_lamp_rewrite %r: want a number 1-999 -> [node, index] "
                                 "or a list of them, got %r" % (k, v))
            self.raw_lamp_rewrite[int(k)] = ((int(v[0]), int(v[1])) if pair(v)
                                             else tuple((int(a), int(b)) for a, b in v))
        for k, v in m.get("solenoids", {}).items():
            if k != "_":
                self.solenoids[int(k)] = tuple(v["coil"])
        for sect in ("lamps", "lamp_calls", m.get("retrofit_lights", {}).get("lights", {})):
            table = m.get(sect, {}) if isinstance(sect, str) else sect
            for name, v in table.items():
                if name == "_" or not isinstance(v, dict):
                    continue
                leds = [tuple(x) for x in v["leds"]]
                self.lamp_groups[lamp_number(*leds[0])] = leds
                # an insert's R, G and B LEDs; or ONE LED that is all three
                # (a Spooky or BoF board's, PAD-952 / PAD-1305: its colour is in the slot)
                if v.get("rgb") and (len(leds) == 3 or (len(leds) == 1 and self.platform in ("spooky", "bof"))):
                    self.rgb_groups.add(lamp_number(*leds[0]))
                    if isinstance(v["rgb"], str):
                        self.rgb_order[lamp_number(*leds[0])] = v["rgb"]
        self.fakes = {k: v for k, v in m.get("switch_fakes", {}).items() if k != "_"}
        # PAD-1228: a node board's stepper the table shows (Rush LE's drum
        # clock): Controller.GetMech(n) answers its place in steps from home
        self.mechs = {}
        for k, v in m.get("mechs", {}).items():
            if k != "_":
                self.mechs[int(k)] = (int(v["stepper"][0]), int(v["stepper"][1]))
        self._load_dof(m)

    def _load_dof(self, m):
        """What DOF hears, in the ORIGINAL ROM's numbers (PAD-879): the
        table's DOF config (the B2S name, PadB2SName) is keyed by the S/L/W
        numbers VPinMAME reported through B2S.Server, so each is the map's
        own key read backwards - a solenoid's number (or its `dof`, where the
        key is core.vbs's flipper Const: null = not sent), a light named
        l<n> (lamp n) or f<n> (the flasher solenoid n), and every table
        switch number the rewrite sends to a Spike 2 id."""
        self.dof_sols = {}                  # S number -> (node, index)
        self.dof_lamps = {}                 # L number -> [(node, index), ...]
        self.dof_flashers = {}              # S number -> [(node, index), ...]
        self.dof_switches = {}              # Spike 2 id -> [W numbers]
        for k, v in m.get("solenoids", {}).items():
            if k == "_" or not isinstance(v, dict):
                continue
            n = v["dof"] if "dof" in v else int(k)
            if n is not None and 0 < int(n) < 1000:
                self.dof_sols[int(n)] = tuple(v["coil"])
        for name, v in m.get("lamps", {}).items():
            hit = re.match(r"^([lf])(\d+)[a-z]?$", name, re.I)
            if not hit or not isinstance(v, dict) or not v.get("leds"):
                continue
            table = self.dof_lamps if hit.group(1).lower() == "l" else self.dof_flashers
            leds = table.setdefault(int(hit.group(2)), [])
            leds.extend(tuple(x) for x in v["leds"] if tuple(x) not in leds)
        for k, v in m.get("switch_rewrite", {}).items():
            if k != "_" and int(v) > 0:
                self.dof_switches.setdefault(int(v), []).append(int(k))

    # -- resolution. A VBScript Empty arrives as None: VPinMAME reads that as
    # switch 0 and ignores it (core.vbs's classes hand one over for a slot
    # they never configured), so this does the same rather than raise.
    def switch_id(self, n):
        n = int(n or 0)
        if n >= 1000:
            return n - 1000
        return self.switch_rewrite.get(n, 0)

    def coil(self, n):
        n = int(n or 0)
        if n in self.solenoids:
            return self.solenoids[n]
        if n >= 1000:
            return ((n - 1000) // 16, (n - 1000) % 16)
        return None

    def leds(self, n):
        n = int(n or 0)
        if n in self.lamp_groups:
            return self.lamp_groups[n]
        if n >= 1000:
            return [((n - 1000) // 100, (n - 1000) % 100)]
        return []


def lamp_number(node, index):
    return 1000 + node * 100 + index


def rgb_value(r, g, b):
    """A lit RGB insert's lamp value (PAD-859): its colour as VBScript's RGB()
    makes it, brightest channel at 255, so a mode's shot colour reaches the
    table - never 0 or 1, which a table reads as off / on."""
    top = max(r, g, b, 1)
    r, g, b = (min(255, c * 255 // top) for c in (r, g, b))
    return max(r | g << 8 | b << 16, 2)


RGB_CHANNEL = re.compile(r"^(.*?\S)(?:-|\s+)(R|G|B|RED|GRN|GREEN|BLU|BLUE)$", re.I)


def rgb_channels(names):
    """The channel order of an RGB insert's three LED names, as "RGB", "BGR",
    ... (PAD-1097: Aerosmith lists LOVE IN AN ELEVATOR-BLU, -GRN, -RED; Rush
    names "SHOOT ME VUK R"), or None when they are not one insert's red,
    green and blue."""
    if len(names) != 3:
        return None
    parts = [RGB_CHANNEL.match((n or "").strip()) for n in names]
    if not all(parts) or len({p.group(1).upper() for p in parts}) != 1:
        return None
    order = "".join(p.group(2)[0].upper() for p in parts)
    return order if sorted(order) == ["B", "G", "R"] else None


def rgb_levels(levels, order):
    """An rgb light's three levels as R, G, B: its map's `rgb` is True (the
    LEDs listed R, G, B) or the order they are listed in ("BGR"). The LEDs
    themselves keep their order, so the light keeps its number (its first
    LED's) and a table patched before stays wired."""
    if isinstance(order, str) and sorted(order.upper()) == ["B", "G", "R"]:
        order = order.upper()
        return [levels[order.index(c)] for c in "RGB"]
    return list(levels)


def sol_number(node, index):
    return 1000 + node * 16 + index


# ---------------------------------------------------------------- the rig --

BOARD = os.path.join(os.path.expanduser("~"), ".pad-rig")


class Rig:
    """WHERE the run is: its dump directory as Windows sees it, and how to
    call back into its WSL.

    Three answers, first one wins:
      1. the environment (PAD_WSL_DISTRO / PAD_ROOT_WSL / PAD_SLOT), which the
         app sets for every tool it launches;
      2. the rig board (~/.pad-rig/slot-N.run, written by watch.sh for every
         run): the run whose `game` is the title the table named (a table
         that names none: the only Spike 2 run up). This is how a Visual Pinball started from the
         Start menu, with no PAD environment at all, finds the app's run;
      3. padpath's default: the default distro's ~/spike2root.

    PAD-1560: a Spike 3 run (`emu` "spike3") is the same shape - s3leds.py
    fills dump/padled, s3keys.py takes dump/padsw - found by its own board
    record (spike3-<n>.run, its slot directory as `root`), with the switch
    table where s3bridge.py writes it (tables/game/switch_list.txt).
    """

    def __init__(self, title=None, record=None, emu="spike2"):
        self.emu = emu or "spike2"
        self.distro = os.environ.get("PAD_WSL_DISTRO")
        self.root = os.environ.get("PAD_ROOT_WSL")        # posix
        self.slot = padpath.slot()
        self.how = "environment"
        if self.emu == "spike3" and not record:
            # the app's environment names its own Spike 2 rig: never a
            # Spike 3 run's
            self.root = None
        if record or not self.root:
            rec = record or self.board_run(title, self.emu)
            if rec:
                self.distro = rec.get("distro") or self.distro
                self.root = rec.get("root")
                self.slot = rec.get("slot", 0)
                self.how = "rig board slot %s (%s)" % (self.slot, rec.get("game"))
        if self.root and self.distro:
            self.dump = r"\\wsl.localhost\%s%s\dump" % (self.distro, self.root.replace("/", "\\"))
        elif self.root:
            self.dump = os.path.join(padpath.to_win(self.root), "dump")   # the default distro
        else:
            self.dump = padpath.dump() or ""
            self.how = "padpath default"

    @staticmethod
    def board_slot(slot, emu="spike2"):
        """The board's record for one slot, or None until watch.sh (a Spike 3
        run: s3run.sh, as spike3-<n>.run) writes it."""
        if emu == "spike3":
            return padlaunch.spike3_record(slot=int(slot))
        try:
            rec = json.load(open(os.path.join(BOARD, "slot-%d.run" % int(slot)), encoding="utf-8"))
            return rec if isinstance(rec, dict) and rec.get("root") else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def board_run(title, emu="spike2"):
        if emu == "spike3":
            # a Spike 3 table always names its title; a stale record (its run
            # gone with WSL) is not a run
            return padlaunch.spike3_record(title) if title else None
        runs = []
        try:
            names = sorted(os.listdir(BOARD))
        except OSError:
            return None
        for n in names:
            if not (n.startswith("slot-") and n.endswith(".run")):
                continue
            try:
                rec = json.load(open(os.path.join(BOARD, n), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if rec.get("emu", "spike2") == "spike2":
                runs.append(rec)
        mine = [r for r in runs if title and r.get("game") == title]
        if len(mine) > 1:
            # several runs of the title (a library sweep had foo_fighters_le
            # up on another slot while the table's own run came up on this
            # one): the newest - the one started for this table - wins. Not
            # "the visible one": a sweep's board record carries no hidden
            # flag and read as visible.
            mine.sort(key=lambda r: -(r.get("started") or 0))
            log("rig board: %d runs of %s, taking the newest, slot %s, over %s" % (
                len(mine), title, mine[0].get("slot"),
                ", ".join("slot %s" % r.get("slot") for r in mine[1:])))
        if mine:
            return mine[0]
        # a table that names its title takes only a run OF that title: the
        # one other run up may be anything - PAD-811: JAWS attached to
        # another ticket's hidden Godzilla run, drove its switches and never
        # started its own. Only a nameless table takes the lone run.
        return runs[0] if len(runs) == 1 and not title else None

    def wsl_head(self):
        head = ["wsl.exe"]
        if self.distro:
            head += ["-d", self.distro]
        return head

    def wsl_env(self):
        env = ["PAD_SW_SRC=%s" % SW_SRC]
        if self.root:
            env.append("PAD_ROOT=%s" % self.root)
        if self.slot:
            env.append("PAD_SLOT=%d" % int(self.slot))
        if os.environ.get("PAD_SW_FILE"):
            env.append("PAD_SW_FILE=%s" % os.environ["PAD_SW_FILE"])
        return env

    def led_path(self):
        return os.path.join(self.dump, "padled")

    def sw_path(self):
        return os.environ.get("PAD_SW_FILE") or os.path.join(self.dump, "padsw")

    def ballfeed_off_path(self):
        """ballfeed.py answers the game's trough eject on a rig run; while a
        table's own trough does, this file (in the run's dump dir) stops it."""
        return os.path.join(self.dump, "ballfeed.off")

    # -- PAD-1437: a PC whose Windows cannot open the run's files at all.
    # Mike St P, v1.512.5: every table, every start, across WSL restarts -
    # the game up on its LCD, WSL reading padled with its mark, Windows
    # unable to open it over \\wsl.localhost. The run was stopped as "WSL's
    # link is stuck" (PAD-1247) and no table played. With `share` False the
    # run goes through wsl.exe instead: padlink.py pushes the blocks
    # (RigLink), and the few files the controller reads or writes beside
    # them are fetched and put through WSL here.

    #: False once Windows has been seen unable to open the run's block
    share = True
    #: how long a fetched copy of a folder is good for
    FETCH_FRESH_S = 1.5

    def wsl_dump(self, *parts):
        """A path in the run's dump directory as WSL names it."""
        return "/".join([(self.root or "").rstrip("/") + "/dump"] + [p for p in parts if p])

    def _wsl(self, args, data=None, timeout=20, runner=None):
        """One command inside the run's distro, as the default user: its
        CompletedProcess, or None when WSL did not answer."""
        run = runner or subprocess.run
        try:
            return run(self.wsl_head() + ["-e"] + list(args), input=data,
                       stdin=None if data is not None else subprocess.DEVNULL,
                       capture_output=True, timeout=timeout,
                       creationflags=_CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def wsl_read(self, name, n, runner=None):
        """The first `n` bytes of dump/<name> as WSL reads it, or None."""
        r = self._wsl(["head", "-c", str(int(n)), self.wsl_dump(name)], runner=runner)
        return r.stdout if r is not None and r.returncode == 0 else None

    def local_dir(self):
        """Where this run's fetched files are kept on the Windows side."""
        import tempfile
        return os.path.join(tempfile.gettempdir(), "pad-vpx-fetched",
                            "%s-slot%s" % (self.distro or "wsl", self.slot or 0))

    def fetch(self, src, names, dest, runner=None):
        """Copy `names` (files or folders) in WSL folder `src` into Windows
        folder `dest` through one tar over wsl.exe; True when it answered."""
        import io
        import tarfile
        r = self._wsl(["sh", "-c", 'cd "$1" 2>/dev/null || exit 0; shift; '
                       'for f; do [ -e "$f" ] && printf "%s\\n" "$f"; done | tar -cf - -T -',
                       "sh", src] + list(names), timeout=30, runner=runner)
        if r is None or r.returncode != 0:
            return False
        os.makedirs(dest, exist_ok=True)
        try:
            with tarfile.open(fileobj=io.BytesIO(r.stdout or b"")) as tf:
                members = [m for m in tf.getmembers() if m.isfile() or m.isdir()]
                try:
                    tf.extractall(dest, members=members, filter="data")
                except TypeError:                           # a Python without filters
                    tf.extractall(dest, members=[m for m in members
                                                 if not (m.name.startswith(("/", "\\")) or ".." in m.name)])
        except (tarfile.TarError, OSError) as exc:
            log("fetch from WSL failed: %s" % exc)
            return False
        return True

    def tables_dir(self, title, runner=None):
        """dump/tables/<title> as Windows can read it: over the share, or a
        fresh copy fetched through WSL when the share cannot be opened. A
        Spike 3 run's is its slot's tables/game (s3run.sh: PAD_TABLES,
        PAD_GAME=game), whatever the title."""
        spike3 = getattr(self, "emu", "spike2") == "spike3"
        if spike3:
            title = "game"
        if self.share:
            if spike3:
                return os.path.join(os.path.dirname(self.dump), "tables", title)
            return os.path.join(self.dump, "tables", title or "")
        local = os.path.join(self.local_dir(), "tables")
        got = getattr(self, "_fetched", None)
        if got is None:
            got = self._fetched = {}
        now = time.monotonic()
        if title and now - got.get(title, -1e9) > self.FETCH_FRESH_S:
            got[title] = now
            src = ((self.root or "").rstrip("/") + "/tables") if spike3 else self.wsl_dump("tables")
            self.fetch(src, [title], local, runner=runner)
        return os.path.join(local, title or "")

    def boot_log_dir(self, runner=None):
        """The slot's boot logs (gzwatch.log, padauto.log) as Windows can
        read them; through WSL when the share cannot be opened."""
        if self.share:
            return os.path.dirname(os.path.dirname(self.dump))
        local = os.path.join(self.local_dir(), "logs")
        self.fetch(os.path.dirname((self.root or "").rstrip("/")) or "/",
                   ["gzwatch.log", "padauto.log"], local, runner=runner)
        return local

    def ballfeed_off(self, on, runner=None):
        """Stand ballfeed.py aside for the table (on) or hand the trough back."""
        if self.share:
            try:
                if on:
                    open(self.ballfeed_off_path(), "w").write("PAD.Controller\n")
                else:
                    os.remove(self.ballfeed_off_path())
                return True
            except OSError as exc:
                if on:
                    log("ballfeed.off not written: %s" % exc)
                return False
        path = self.wsl_dump("ballfeed.off")
        r = self._wsl(["sh", "-c", 'echo PAD.Controller > "$1"' if on else 'rm -f "$1"', "sh", path],
                      runner=runner)
        ok = r is not None and r.returncode == 0
        if on and not ok:
            log("ballfeed.off not written through WSL")
        return ok

    def seed_switch_list_wsl(self, title, runner=None):
        """seed_switch_list inside WSL, for a run the share cannot reach."""
        slots = (self.root or "").rstrip("/").rsplit("/", 2)[0]          # .../padslots
        self._wsl(["sh", "-c",
                   'dst="$1/dump/tables/$3/switch_list.txt"; [ -e "$dst" ] && exit 0; '
                   'src=$(ls -t "$2"/*/root/dump/tables/"$3"/switch_list.txt 2>/dev/null | head -n 1); '
                   '[ -n "$src" ] || exit 0; mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" '
                   '&& echo "$src"', "sh", self.root.rstrip("/"), slots, title], runner=runner)

    def switch_ids(self, title):
        """{(node, bit): id} from the title's switch_list.txt, the rig's own
        reading of the game's switch table (empty when the run has none)."""
        out = {}
        # a Spike 3 run's bridge writes its own as the node boards answer:
        # no other slot's copy is taken in
        seed = getattr(self, "emu", "spike2") != "spike3"
        if seed and not self.share and title and self.root:
            self.seed_switch_list_wsl(title)
        path = os.path.join(self.tables_dir(title), "switch_list.txt")
        if seed and self.share and title and not os.path.exists(path):
            self.seed_switch_list(title, path)
        try:
            for line in open(path, encoding="utf-8", errors="replace"):
                p = line.split()
                if len(p) >= 5 and p[0].isdigit():
                    out[(int(p[2]), int(p[3]))] = int(p[0])
        except OSError:
            pass
        return out

    def seed_switch_list(self, title, path):
        """A title's FIRST run on a slot has no switch_list.txt, and under a
        table it never gets one: the rig derives it once the game is up, the
        game waits on a trough the table cannot report without it, and the
        ball feeder stands aside for the table (PAD-811: TMNT sat on its logo
        on a fresh slot for minutes). Another slot's copy of the same title
        is the same game's table: the newest goes in, for the renderer's
        keyboard and the playfield as well."""
        import glob
        import shutil
        slots = os.path.dirname(os.path.dirname(os.path.dirname(self.dump)))   # .../padslots
        found = [p for p in glob.glob(os.path.join(slots, "*", "root", "dump", "tables",
                                                   title, "switch_list.txt"))
                 if os.path.normcase(p) != os.path.normcase(path)]
        if not found:
            return
        src = max(found, key=os.path.getmtime)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(src, path)
            log("switch table for %s taken from %s (this slot had none)" % (title, src))
        except OSError as exc:
            log("switch table for %s not copied from %s: %s" % (title, src, exc))


#: the run log's lines that say nothing about why a run stalled or ended
_RUN_LOG_NOISE = re.compile(r"^\[event\] \[sw\] id=|^\[padglhost\] [\d.]+ fps ")


def run_log_tail(path, n=8):
    """The last *n* telling lines of a started run's log (padlaunch's
    padvpx-<title>.log, watch.sh's output), [] when it cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return []
    return [ln.strip()[:300] for ln in lines
            if ln.strip() and not _RUN_LOG_NOISE.match(ln)][-n:]


def run_log_said(path, n=8):
    """': its log ends:' and the run log's last lines, one per controller log
    line, so a report (which leaves paths out) still says why (PAD-1208)."""
    tail = run_log_tail(path, n)
    return (": its log ends:\n" + "\n".join("    | " + ln for ln in tail)) if tail else ""


def read_block(path, n):
    """One fresh read of `n` bytes, or None (no run, or a 9p hiccup)."""
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return None


def block_state(data):
    """How a Windows read of padled went, in words for the controller log."""
    if data is None:
        return "Windows cannot open it"
    if not data:
        return "Windows reads it empty"
    return "Windows reads %d bytes with %s" % (
        len(data), "its mark" if coilmap.has_magic(data) else "no mark")


def block_in_wsl(rig, runner=None, timeout=20):
    """Does the run's padled carry its mark as WSL ITSELF reads it (PAD-1247)?

    True / False, or None when WSL did not answer. Read as the distro's
    default user, the one \\\\wsl.localhost serves Windows as, so a file only
    root could read is not taken for a stuck share. Mike St P's runs on
    v1.427.1: the game booted to attract, its block never came up for
    Windows and its sound never reached the Windows player, five starts in a
    row and across an app restart; the next WSL restart (an update's) put
    both right with no change to the rig. That is WSL's link to Windows
    stuck, and Linux reading the mark while Windows cannot is how it is told
    from a game that never opened its block."""
    if not (getattr(rig, "root", None) and getattr(rig, "distro", None)):
        return None
    path = rig.root.rstrip("/") + "/dump/padled"
    run = runner or subprocess.run
    try:
        r = run(rig.wsl_head() + ["-e", "od", "-An", "-tx1", "-N4", path],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return False
    try:
        raw = bytes(int(h, 16) for h in r.stdout.decode("ascii", "replace").split())
    except ValueError:
        return None
    return len(raw) == 4 and coilmap.has_magic(raw)


#: what the loading window says when WSL's link to Windows is stuck (PAD-1247)
WSL_STUCK = ("WSL's link to Windows is stuck: the game runs inside WSL, but the "
             "table cannot reach it and its sound does not come through. "
             "Close Visual Pinball, press Restart WSL… on PAD's Emulate tab, "
             "then open the table again.")


class SwitchPipe:
    """The session's swkeys.py, fed "<id> <level>" lines (playfield.py's
    KeyWriter, minus the per-action fallback: VPX has no mouse to wait on)."""

    def __init__(self, rig):
        self.rig = rig
        self._p = None
        self._failed = 0
        self.held = {}

    def _ensure(self):
        if self._p is not None and self._p.poll() is None:
            return True
        if self._failed >= 2:
            return False
        try:
            if sys.platform == "win32":
                cmd = (self.rig.wsl_head() + ["-e", "env"] + self.rig.wsl_env()
                       + ["python3", "%s/swkeys.py" % padpath.to_wsl(RIG, self.rig.distro)])
            else:
                cmd = ["python3", os.path.join(RIG, "swkeys.py")]
            self._p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=_CREATE_NO_WINDOW)
            log("swkeys up: %s" % " ".join(cmd))
            return True
        except Exception as exc:                            # noqa: BLE001
            self._failed += 1
            self._p = None
            log("swkeys spawn failed: %s" % exc)
            return False

    def set(self, sw, level):
        level = 1 if level else 0
        if self.held.get(sw) == level:
            return True
        self.held[sw] = level
        return self._send(b"%d %d\n" % (sw, level))

    def pause(self):
        return self._send(b"pause\n")

    def _send(self, line):
        if not self._ensure():
            return False
        try:
            self._p.stdin.write(line)
            self._p.stdin.flush()
            return True
        except Exception as exc:                            # noqa: BLE001
            self._failed += 1
            self._p = None
            log("swkeys write failed: %s" % exc)
            return False

    def close(self):
        try:
            if self._p is not None and self._p.poll() is None:
                self._p.stdin.close()          # EOF: the helper releases all
                self._p.wait(timeout=3)
        except Exception:                                   # noqa: BLE001
            pass
        self._p = None
        self.held.clear()


#: PAD-1306: PAD_VPX_LINK=0 keeps the old way (9p reads + swkeys) for a session
LINK_ON = os.environ.get("PAD_VPX_LINK", "1") != "0"

#: PAD-1437: PAD_VPX_SHARE=0 takes a run through WSL from the start, as if
#: Windows could not open its files over \\wsl.localhost (a PC where it
#: cannot, without waiting to find out; and how that path is proven live)
SHARE_ON = os.environ.get("PAD_VPX_SHARE", "1") != "0"


class RigLink:
    """The run's padled and merged switches PUSHED from inside WSL (padlink.py),
    and the switch lines sent back down the same helper (PAD-1306).

    SwitchPipe's interface (set / pause / close / held), plus `blocks()`: the
    newest (padled, mrg) the helper sent, or None while the link is not up -
    the poll then reads over 9p as it always did. The link is trusted from
    its HELLO; it is given up when the helper ends, says ERR, or sends nothing
    for SILENT_S (it pings every 2 s), and from then on the session runs on
    SwitchPipe and 9p reads, with every switch still held handed over."""

    HELLO_S = 20.0             # wsl.exe + python3 starting on a busy machine
    SILENT_S = 6.0

    def __init__(self, rig, spawn=None, clock=time.monotonic):
        self.rig = rig
        self.clock = clock
        self.held = {}
        self.state = "starting"
        self.why = ""
        self.led = None
        self.mrg = None
        self.frames = 0
        self.news = threading.Event()   # set on every change pushed (the poll waits on it)
        self.sent = 0
        self.lost = []
        self._queue = []           # switch lines said before HELLO
        self._fallback = None
        self._lock = threading.Lock()
        self._t = self._last = clock()
        self._p = None
        try:
            self._p = (spawn or self._spawn)()
        except Exception as exc:                            # noqa: BLE001
            self._give_up("not started: %s" % exc)
            return
        if self._p is not None:
            threading.Thread(target=self._read, daemon=True).start()

    def _cmd(self):
        here = padpath.to_wsl(os.path.join(RIG, "padlink.py"), self.rig.distro)
        return (self.rig.wsl_head() + ["-e", "env"] + self.rig.wsl_env()
                + ["PAD_LINK_READ=%d" % READ_N, "python3", here])

    def _spawn(self):
        cmd = self._cmd()
        log("link: %s" % " ".join(cmd))
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)

    # -- what comes up from WSL
    def _read(self):
        p = self._p
        try:
            for raw in p.stdout:
                if not self.feed(raw):
                    break
        except Exception as exc:                            # noqa: BLE001
            self._give_up("read failed: %s" % exc)
            return
        self._give_up("the helper ended")

    def feed(self, raw):
        """One line from padlink.py; False once the link is over."""
        text = raw.decode("ascii", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not text:
            return True
        tag, _, rest = text.partition(" ")
        with self._lock:
            if self.state == "down":
                return False
            self._last = self.clock()
            try:
                if tag == "HELLO":
                    self.state = "hello"
                elif tag == "F":
                    self.led = bytearray.fromhex(rest)
                elif tag == "G":
                    self.mrg = bytearray.fromhex(rest)
                elif tag in ("L", "M") and self.led is not None and self.mrg is not None:
                    into = self.led if tag == "L" else self.mrg
                    for run in rest.split():
                        off, _, hx = run.partition(":")
                        b = bytes.fromhex(hx)
                        o = int(off)
                        into[o:o + len(b)] = b
                    self.frames += 1
                    self.news.set()
                elif tag == "LOST":
                    self.lost.append(rest)
                    log("link: switch %s never reached the game" % rest)
                elif tag == "ERR":
                    pass
            except ValueError:
                log("link: a line it could not read: %s" % text[:80])
                return True
            up = self.state == "hello" and self.led is not None and self.mrg is not None
        if tag == "ERR":
            self._give_up("helper: %s" % rest)
            return False
        if up and self.state != "up":
            self._up()
        return True

    def _up(self):
        with self._lock:
            self.state = "up"
            queued, self._queue = self._queue, []
        log("link up after %.1f s: lights, coils and switches pushed from WSL"
            % (self.clock() - self._t))
        for ln in queued:
            self._write(ln)

    # -- what goes down
    def set(self, sw, level):
        level = 1 if level else 0
        if self.held.get(sw) == level:
            return True
        self.held[sw] = level
        self.sent += 1
        return self._send(b"%d %d\n" % (sw, level))

    def pause(self):
        return self._send(b"pause\n")

    def _send(self, line):
        self.alive()
        with self._lock:
            if self._fallback is None and self.state != "up":
                self._queue.append(line)
                return True
        if self._fallback is not None:
            return self._fallback._send(line)
        return self._write(line)

    def _write(self, line):
        try:
            self._p.stdin.write(line)
            self._p.stdin.flush()
            return True
        except Exception as exc:                            # noqa: BLE001
            self._give_up("write failed: %s" % exc)
            return self._fallback._send(line) if self._fallback else False

    # -- health
    def alive(self):
        """Up and heard from lately; gives the link up when it is not."""
        now = self.clock()
        if self.state == "up" and now - self._last > self.SILENT_S:
            self._give_up("silent %.0f s" % (now - self._last))
        elif self.state in ("starting", "hello") and now - self._t > self.HELLO_S:
            self._give_up("no HELLO in %.0f s" % self.HELLO_S)
        return self.state == "up"

    def blocks(self):
        if not self.alive():
            return None
        with self._lock:
            return bytes(self.led), bytes(self.mrg)

    def _give_up(self, why):
        with self._lock:
            if self.state == "down":
                return
            self.state, self.why = "down", why
            self._queue = []
        log("link down (%s): back to reading over \\\\wsl.localhost and swkeys" % why)
        self._kill()
        fb = SwitchPipe(self.rig)
        for sw, level in sorted(self.held.items()):
            fb.set(sw, level)
        self._fallback = fb

    def _kill(self):
        p, self._p = self._p, None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.stdin.close()            # EOF: the helper releases what it held
                p.wait(timeout=3)
        except Exception:                                   # noqa: BLE001
            try:
                p.kill()
            except Exception:                               # noqa: BLE001
                pass

    def status(self):
        return {"state": self.state, "why": self.why, "frames": self.frames,
                "lost": list(self.lost[-8:])}

    def close(self):
        with self._lock:
            self.state = "down"
        self._kill()
        if self._fallback is not None:
            self._fallback.close()
        self.held.clear()


# ---------------------------------------------------------------- the bridge

#: how far inside the playfield's edge a press grabs it to resize (the game
#: display's DISP_EDGE, padglhost.c)
GRIP_EDGE = 16
PLAYER_MIN_W = 240


def grip_edge(pt, client, edge=GRIP_EDGE):
    """Which edges of the playfield picture `pt` is within `edge` pixels of
    ("l", "br", ...), or None: the grip ring (PAD-845). `client` is the
    picture's (x, y, w, h) on the screen."""
    x, y = pt
    cx, cy, cw, ch = client
    if not (cx <= x < cx + cw and cy <= y < cy + ch):
        return None
    edges = ("t" if y < cy + edge else "b" if y >= cy + ch - edge else "") \
        + ("l" if x < cx + edge else "r" if x >= cx + cw - edge else "")
    return edges or None


def resized(edges, win, client, start, pt, min_w=PLAYER_MIN_W):
    """The window rectangle after dragging `edges` from `start` to `pt`, the
    picture in its proportions: a side edge sets the width, a top or bottom
    edge the height, and the edges opposite the dragged ones stay put."""
    wx, wy, ww, wh = win
    cw, ch = client[2], client[3]
    aspect = ch / float(cw) if cw else 1.0
    dx, dy = pt[0] - start[0], pt[1] - start[1]
    if "l" in edges or "r" in edges:
        ncw = cw + (dx if "r" in edges else -dx)
    else:
        ncw = (ch + (dy if "b" in edges else -dy)) / aspect
    ncw = max(int(round(ncw)), min_w)
    nw, nh = ncw + (ww - cw), int(round(ncw * aspect)) + (wh - ch)
    return (wx + ww - nw if "l" in edges else wx), (wy + wh - nh if "t" in edges else wy), nw, nh


class PlayerGrips:
    """The playfield window by hand, the way the game display is (PAD-845).
    David: "I wish it worked more like the display where you could loosely
    grab 16 pixels from the edge", "we should be able to double click it to
    fill the screen and it should be borderless". Visual Pinball's window
    procedure is its own, so a window of ours lies over the whole picture,
    all but invisible (alpha 1, which still takes the mouse) and owned by the
    player so it stays just above it:

      * within GRIP_EDGE px of an edge or corner the cursor is that resize
        arrow, and a drag resizes the player in the table's proportions
        (resized());
      * anywhere else a drag moves it;
      * a press becomes a drag only after GRIP_SLOP px, so a click stays a
        click, and a double-click anywhere fills the monitor and the next
        puts it back (Bridge._fill_player).

    It never takes the focus (WS_EX_NOACTIVATE, MA_NOACTIVATE): Visual
    Pinball pauses the moment it loses it. And a press on it hands the
    keyboard to the player (PAD-851): the window covers the whole picture,
    so the click that used to activate Visual Pinball lands here, and with
    the game display in front the flippers went to the display instead
    ("i can't do the flippers with left and right shift"). The click is
    input to this process, so Windows lets it set the foreground. The cost: the table gets no mouse
    of its own while this is up (`padvpx player frame on` brings back the
    frame instead). One thread with its own message loop, following the
    player every 50 ms."""

    CLASS = "PADPlayerGrips"
    GRIP_SLOP = 4
    CURSORS = {"l": 32644, "r": 32644, "t": 32645, "b": 32645,          # IDC_SIZEWE, IDC_SIZENS
               "tl": 32642, "br": 32642, "tr": 32643, "bl": 32643,      # IDC_SIZENWSE, IDC_SIZENESW
               None: 32512}                                            # IDC_ARROW

    def __init__(self, bridge):
        self.bridge = bridge
        self.hwnd = 0
        self.player = 0
        self.placed = None
        self.press = None
        self.drag = None
        self.aside = False                  # hidden while Visual Pinball is paused
        self.tid = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        import ctypes
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)     # WM_QUIT
        self.thread.join(timeout=2)

    def _run(self):
        import ctypes
        from ctypes import wintypes
        import win32api
        import win32gui
        u = self.u = ctypes.windll.user32
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))     # physical pixels, as the player's
        u.LoadCursorW.restype = ctypes.c_void_p
        u.SetCursor.argtypes = [ctypes.c_void_p]
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = self.CLASS
        wc.lpfnWndProc = self._proc
        wc.style = 0x0008                                    # CS_DBLCLKS
        wc.hInstance = self.hinst = win32api.GetModuleHandle(None)
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass                                             # this process registered it already
        u.SetTimer(None, 0, 50, None)
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0113 and not msg.hWnd:   # WM_TIMER, the thread's own
                    self._tick()
                    continue
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:                            # noqa: BLE001
            log("player grips stopped: %s" % exc)
        finally:
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
                self.hwnd = 0

    def _tick(self):
        import ctypes
        import win32gui
        u = self.u
        try:
            b = self.bridge
            player = getattr(b, "player_hwnd", 0) if b.running else 0
            if player and not (u.IsWindow(ctypes.c_void_p(player)) and u.IsWindowVisible(ctypes.c_void_p(player))
                               and not u.IsIconic(ctypes.c_void_p(player))):
                player = 0
            if player != self.player:
                if self.hwnd:
                    win32gui.DestroyWindow(self.hwnd)
                    self.hwnd = 0
                self.player, self.placed = player, None
                if player:
                    # WS_EX_LAYERED | TOOLWINDOW | NOACTIVATE, WS_POPUP owned by the player
                    self.hwnd = win32gui.CreateWindowEx(0x00080000 | 0x00000080 | 0x08000000, self.CLASS,
                                                        "PAD grips", 0x80000000, 0, 0, 1, 1, player, 0,
                                                        self.hinst, None)
                    u.SetLayeredWindowAttributes(ctypes.c_void_p(self.hwnd), 0, 1, 2)    # alpha 1: there, unseen
                    log("player grips on: drag the playfield to move it, %d px from an edge to resize it, "
                        "double-click it to fill the screen" % GRIP_EDGE)
            if self.hwnd and not self.drag:
                if getattr(b, "paused", False):
                    self._stand_aside()
                else:
                    if self.aside:
                        self.aside = False
                        log("player grips back: Visual Pinball plays on")
                    self._follow()
        except Exception as exc:                            # noqa: BLE001
            log("player grips: %s" % exc)

    def _stand_aside(self):
        """Out of the way while Visual Pinball is paused (PAD-882): Esc opens
        its menu (Resume, Quit to editor...) INSIDE the picture this window
        covers, and the menu's buttons took no click. Back, over the whole
        picture again, the moment VPX plays on (_follow, placed forgotten)."""
        import ctypes
        if not self.aside:
            self.aside = True
            self.placed = None
            self.u.ShowWindow(ctypes.c_void_p(self.hwnd), 0)            # SW_HIDE
            log("player grips aside: Visual Pinball is paused, its menu takes the mouse")

    def _follow(self):
        """Over the whole picture, wherever the player is."""
        import ctypes
        u = self.u
        c = Bridge._client_on_screen(self.player)
        if c == self.placed:
            return
        self.placed = c
        if u.IsZoomed(ctypes.c_void_p(self.player)) or c[2] < 2 * GRIP_EDGE or c[3] < 2 * GRIP_EDGE:
            u.ShowWindow(ctypes.c_void_p(self.hwnd), 0)
            return
        # SWP_NOACTIVATE | SWP_SHOWWINDOW; an owned window stays over its owner
        u.SetWindowPos(ctypes.c_void_p(self.hwnd), None, *c, 0x0010 | 0x0040)

    def _point(self):
        import ctypes
        from ctypes import wintypes
        p = wintypes.POINT()
        self.u.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def _proc(self, hwnd, msg, wparam, lparam):
        import ctypes
        import win32gui
        u = self.u
        try:
            if msg == 0x0021:                                # WM_MOUSEACTIVATE
                return 3                                     # MA_NOACTIVATE: the player keeps the focus
            if msg == 0x0020:                                # WM_SETCURSOR
                edge = (self.drag or self.press or (grip_edge(self._point(), Bridge._client_on_screen(self.player)),))[0]
                edge = None if edge == "move" else edge
                u.SetCursor(u.LoadCursorW(None, ctypes.c_void_p(self.CURSORS[edge])))
                return 1
            if msg == 0x0201:                                # WM_LBUTTONDOWN: only remembered
                if u.GetForegroundWindow() != self.player:
                    ok = u.SetForegroundWindow(ctypes.c_void_p(self.player))
                    log("player window clicked: it has the keyboard%s" % ("" if ok else " (Windows refused)"))
                p = self._point()
                client = Bridge._client_on_screen(self.player)
                self.press = (grip_edge(p, client) or "move", window_rect(self.player), client, p)
                u.SetCapture(ctypes.c_void_p(hwnd))
                return 0
            if msg == 0x0200 and (self.press or self.drag):  # WM_MOUSEMOVE with the button down
                p = self._point()
                if not self.drag:
                    s = self.press[3]
                    if abs(p[0] - s[0]) < self.GRIP_SLOP and abs(p[1] - s[1]) < self.GRIP_SLOP:
                        return 0
                    self.drag, self.press = self.press, None
                edge, win, client, start = self.drag
                if edge == "move":
                    to = (win[0] + p[0] - start[0], win[1] + p[1] - start[1], win[2], win[3])
                else:
                    to = resized(edge, win, client, start, p)
                if to != window_rect(self.player):
                    u.SetWindowPos(ctypes.c_void_p(self.player), None, *to, 0x4 | 0x10)   # NOZORDER | NOACTIVATE
                    self.placed = None
                    self._follow()
                return 0
            if msg in (0x0202, 0x0215):                      # WM_LBUTTONUP, WM_CAPTURECHANGED
                if self.drag:
                    log("player window %s by hand: %s" % ("moved" if self.drag[0] == "move" else
                                                          "resized from its %s edge" % self.drag[0],
                                                          window_rect(self.player)))
                self.press = self.drag = None
                if msg == 0x0202:
                    u.ReleaseCapture()
                self.placed = None
                return 0
            if msg == 0x0203:                                # WM_LBUTTONDBLCLK: fill the screen, or back
                self.press = self.drag = None
                u.ReleaseCapture()
                self.bridge._fill_player(self.player)
                self.placed = None
                return 0
        except Exception as exc:                            # noqa: BLE001
            log("player grips: %s" % exc)
            self.press = self.drag = None
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


DOF_DLL = "DirectOutputComObject.dll"


def _dof_shells():
    """(64-bit, 32-bit) Windows PowerShell; a 32-bit Python sees the 64-bit
    one as Sysnative."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = r"WindowsPowerShell\v1.0\powershell.exe"
    native = os.path.join(root, "Sysnative", ps)
    if not os.path.exists(native):
        native = os.path.join(root, "System32", ps)
    return native, os.path.join(root, "SysWOW64", ps)


def _dof_dirs():
    """DOF's install folders, best first: the one its installer saved, the
    one B2S.Server's DOF plugin points at, then the default C:\\DirectOutput."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\DirectOutput\DirectOutput") as k:
            out.append(winreg.QueryValueEx(k, "InstallPath")[0])
    except OSError:
        pass
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"B2S.Server\CLSID") as k:
                clsid = winreg.QueryValueEx(k, "")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\InprocServer32" % clsid,
                                0, winreg.KEY_READ | view) as k:
                code = winreg.QueryValueEx(k, "CodeBase")[0]
        except OSError:
            continue
        b2s = os.path.dirname(code.replace("file:///", "").replace("/", "\\"))
        for sub in ("Plugins64", "Plugins"):
            d = os.path.join(b2s, sub, "DirectOutput")
            if os.path.isdir(d):
                out.append(d)
            elif os.path.isfile(d + ".lnk"):
                try:
                    import win32com.client
                    out.append(win32com.client.Dispatch("WScript.Shell").CreateShortcut(d + ".lnk").TargetPath)
                except Exception:                           # noqa: BLE001
                    pass
    out.append(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "DirectOutput"))
    return out


def dof_dll_candidates(dirs=None):
    """[(DirectOutputComObject.dll, [PowerShell to load it in])]: the x64
    build in a 64-bit PowerShell, the x86 one in a 32-bit one, and an older
    install's single folder in whichever loads it."""
    ps64, ps32 = _dof_shells()
    seen, out = set(), []
    for d in (dirs if dirs is not None else _dof_dirs()):
        d = os.path.normpath(d) if d else ""
        if not d or d.lower() in seen:
            continue
        seen.add(d.lower())
        if os.path.basename(d).lower() in ("x64", "x86"):
            d = os.path.dirname(d)
        for sub, shells in (("x64", [ps64]), ("x86", [ps32]), ("", [ps64, ps32])):
            dll = os.path.join(d, sub, DOF_DLL) if sub else os.path.join(d, DOF_DLL)
            if os.path.isfile(dll) and dll.lower() not in seen:
                seen.add(dll.lower())
                out.append((dll, shells))
    return out


#: VPinMAME clone ROMs a table may name whose DOF table config (the config
#: tool's) is keyed by the parent ROM (PAD-948: "The Beatles" plays the free
#: play Seawitch, seawitfp; DOF's configs know Seawitch as seawitch). DOF
#: itself only matches a name, its "<name>_" prefix or its plain prefix.
DOF_PARENT_ROMS = {"seawitfp": ("seawitch",)}


def dof_config_dirs(table_file="", dirs=None):
    """Where DOF reads its table configs (GlobalConfig.GetIniFilesDictionary):
    the global config's IniFilesPath, the table's folder, the global config's
    folder (DOF's Config) and DOF's own folder."""
    out = []
    for d in (dirs if dirs is not None else _dof_dirs()):
        d = os.path.normpath(d) if d else ""
        if os.path.basename(d).lower() in ("x64", "x86"):
            d = os.path.dirname(d)
        if not d:
            continue
        cfg = os.path.join(d, "Config")
        try:
            xml = open(os.path.join(cfg, "GlobalConfig_B2SServer.xml"), encoding="utf-8",
                       errors="replace").read()
            hit = re.search(r"<IniFilesPath>([^<]*)</IniFilesPath>", xml)
            if hit and hit.group(1).strip():
                out.append(hit.group(1).strip())
        except OSError:
            pass
        out.extend([cfg, d])
    if table_file:
        out.insert(1 if out else 0, os.path.dirname(table_file))
    return out


def dof_config_names(dirs):
    """Every table name DOF's configs (directoutputconfig*.ini, ledcontrol*.ini)
    in these folders have a row for: the first field of each [Config ...] row."""
    names = set()
    for d in dirs:
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in files:
            low = f.lower()
            if not low.endswith(".ini") or not low.startswith(("directoutputconfig", "ledcontrol")):
                continue
            try:
                lines = open(os.path.join(d, f), encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            section = ""
            for line in lines:
                line = line.strip()
                if line.startswith("["):
                    section = line.lower()
                elif section.startswith("[config") and "," in line:
                    name = line.split(",", 1)[0].strip()
                    if name:
                        names.add(name)
    return names


def dof_knows(rom, names):
    """DOF's own match (LedControlConfigList.GetTableConfigDictionary): the
    name, then "<name>_" as a prefix, then the name as a plain prefix."""
    up = rom.upper()
    return any(up == n.upper() or up.startswith(n.upper() + "_") or rom.startswith(n)
               for n in names)


def dof_rom_for(rom, table_file="", dirs=None):
    """The name to Init DOF with: the table's ROM name, unless DOF's configs
    have no row for it but do for its parent ROM. Configs unreadable: as is."""
    parents = DOF_PARENT_ROMS.get((rom or "").lower())
    if not parents:
        return rom
    names = dof_config_names(dof_config_dirs(table_file, dirs))
    if not names or dof_knows(rom, names):
        return rom
    for p in parents:
        if dof_knows(p, names):
            log("DOF: no table config for %s; using its parent ROM's, %s" % (rom, p))
            return p
    return rom


#: run by _DofProcess: DOF's ComObject loaded from its DLL, Init'ed from the
#: environment, then one "<kind> <number> <value>" line per event on stdin
_DOF_PS = r"""
$ErrorActionPreference = 'Stop'
try {
  $a = [Reflection.Assembly]::LoadFrom($env:PAD_DOF_DLL)
  $d = $a.CreateInstance('DirectOutputCom.ComObject')
  $d.Init($env:PAD_DOF_HOST, $env:PAD_DOF_TABLE, $env:PAD_DOF_ROM)
} catch {
  [Console]::Out.WriteLine('PADDOF ERR ' + $_.Exception.GetBaseException().Message)
  exit 1
}
[Console]::Out.WriteLine('PADDOF UP')
[Console]::Out.Flush()
[Console]::SetOut([IO.TextWriter]::Null)
$in = [Console]::In
while ($true) {
  $l = $in.ReadLine()
  if ($l -eq $null -or $l -eq 'END') { break }
  $p = $l.Split(' ')
  try { $d.UpdateTableElement($p[0], [int]$p[1], [int]$p[2]) } catch {}
}
$d.Finish()
"""


class _DofProcess:
    """DOF's ComObject without its COM registration (PAD-909): a PowerShell
    helper loads DirectOutputComObject.dll itself and takes the events on
    its stdin. Same three methods DofHost calls on the COM object."""

    INIT_WAIT_S = 15

    def __init__(self, dll, shell):
        self.dll = dll
        self.shell = shell
        self.proc = None

    def Init(self, host, table_file, rom):                 # noqa: N802  DOF's own name
        import base64
        if not os.path.isfile(self.shell):
            raise RuntimeError("no %s" % self.shell)
        env = dict(os.environ, PAD_DOF_DLL=self.dll, PAD_DOF_HOST=host,
                   PAD_DOF_TABLE=table_file or "", PAD_DOF_ROM=rom or "")
        cmd = [self.shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-EncodedCommand", base64.b64encode(_DOF_PS.encode("utf-16-le")).decode("ascii")]
        # DOF's log (.\DirectOutput.log) lands in DOF's main folder, not x64
        cwd = os.path.dirname(self.dll)
        if os.path.basename(cwd).lower() in ("x64", "x86"):
            cwd = os.path.dirname(cwd)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env, cwd=cwd,
                                     creationflags=_CREATE_NO_WINDOW)
        said = []

        def read():
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("PADDOF "):
                    said.append(line[7:])
                    return
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(self.INIT_WAIT_S)
        if said[:1] != ["UP"]:
            self._kill()
            raise RuntimeError(said[0] if said else "DOF did not start in %d s" % self.INIT_WAIT_S)

    def UpdateTableElement(self, kind, number, value):     # noqa: N802
        self.proc.stdin.write(b"%s %d %d\n" % (kind.encode("ascii"), number, value))
        self.proc.stdin.flush()

    def Finish(self):                                       # noqa: N802
        try:
            self.proc.stdin.write(b"END\n")
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:                                   # noqa: BLE001
            self._kill()

    def _kill(self):
        try:
            self.proc.kill()
        except Exception:                                   # noqa: BLE001
            pass


class DofHost:
    """DOF for a table PAD drives (PAD-879). Under VPinMAME a table's DOF is
    B2S.Server's DOF plugin hearing every solenoid, lamp and switch the ROM
    reports (S/L/W); here B2S.Server runs BESIDE PAD.Controller (PAD-852) and
    a released one passes another controller only the script's own `DOF n`
    calls (E). So this hosts DOF itself, through the COM object DOF ships for
    exactly that (DirectOutput.ComObject), under B2S's host name - the same
    GlobalConfig_B2SServer.xml, cabinet and table configs the plugin reads -
    and is started before B2S.Server, so it opens the cabinet's devices first.

    DOF's installer registers that object per user, and the registration can
    go missing while DOF itself still works through B2S.Server's plugin
    (PAD-909: one install lost its ProgID between two runs). So the object is
    found by ProgID, then by its class id, then by loading DOF's own
    DirectOutputComObject.dll from DOF's folder in a PowerShell helper
    (_DofProcess), which needs no registration at all.

    One thread owns the object (its own apartment); send() only queues."""

    PROGID = "DirectOutput.ComObject"
    CLSID = "{A23BFDBC-9A8A-46C0-8672-60F23D54FFB6}"   # DOF's ComObject.ClassId
    HOST = "B2SServer"
    INIT_WAIT_S = 20

    def __init__(self, rom, table_file, factory=None, dlls=None):
        self.rom = rom
        self.up = False
        self.why = ""
        self.how = ""
        self.sent = 0
        self._dlls = dlls
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._factory = factory
        self._thread = threading.Thread(target=self._run, args=(rom, table_file), daemon=True)
        self._thread.start()
        if not self._ready.wait(self.INIT_WAIT_S):
            self.why = "DOF did not finish starting in %d s" % self.INIT_WAIT_S
        log("DOF for %s: %s" % (rom, ("up" + (" (%s)" % self.how if self.how else ""))
                                if self.up else "off - " + self.why))

    def _open(self, table_file, rom):
        """DOF's object, Init'ed: by ProgID, by class id, else DOF's own DLL."""
        import win32com.client
        tried = []
        for name in (self.PROGID, self.CLSID):
            try:
                dof = win32com.client.Dispatch(name)
            except Exception as exc:                        # noqa: BLE001
                tried.append("no %s (%s)" % (name, exc))
                continue
            dof.Init(self.HOST, table_file, rom)
            if name == self.CLSID:
                self.how = "by its class id; the %s name is not registered" % self.PROGID
            return dof
        dlls = self._dlls if self._dlls is not None else dof_dll_candidates()
        if not dlls:
            tried.append("no DirectOutputComObject.dll in DOF's folder either")
        for dll, shells in dlls:
            for shell in shells:
                try:
                    dof = _DofProcess(dll, shell)
                    dof.Init(self.HOST, table_file, rom)
                except Exception as exc:                    # noqa: BLE001
                    tried.append("%s: %s" % (dll, exc))
                    continue
                self.how = "DOF's own %s; DOF's COM registration is missing" % dll
                return dof
        raise RuntimeError("; ".join(tried))

    def _run(self, rom, table_file):
        if pythoncom:
            pythoncom.CoInitialize()
        try:
            if self._factory:
                try:
                    dof = self._factory()
                except Exception as exc:                    # noqa: BLE001
                    raise RuntimeError("no %s (%s)" % (self.PROGID, exc))
                dof.Init(self.HOST, table_file, rom)
            else:
                dof = self._open(table_file, rom)
            self.up = True
        except Exception as exc:                            # noqa: BLE001
            self.why = str(exc)
        self._ready.set()
        if not self.up:
            return
        failed = False
        while True:
            item = self._q.get()
            if item is None:
                break
            try:
                dof.UpdateTableElement(*item)
                self.sent += 1
            except Exception as exc:                        # noqa: BLE001
                if not failed:
                    log("DOF UpdateTableElement%r failed: %s" % (item, exc))
                failed = True
        try:
            dof.Finish()
        except Exception as exc:                            # noqa: BLE001
            log("DOF Finish failed: %s" % exc)
        log("DOF for %s finished after %d events" % (rom, self.sent))

    def send(self, kind, number, value):
        if self.up:
            self._q.put((kind, int(number), int(value)))

    def finish(self):
        if self.up:
            self.up = False
            self._q.put(None)
            self._thread.join(timeout=5)


class B2SHost:
    """B2S.Server's bulbs, set by name (PAD-1304): PADSPIKE2.vbs hands the
    B2S.Server it started over (Controller.PadB2S), and BACKBOX GI lights the
    bulbs the kit names for the title through B2SSetIllumination. The object
    lives in Visual Pinball's process, so the calls go from a thread of their
    own (the poll never waits on Visual Pinball's) with the object marshalled
    to it; *direct* hands a plain object over as it is (the tests')."""

    def __init__(self, obj, direct=False):
        self._q = queue.Queue()
        self.up = True
        self.sent = 0
        self.why = ""
        self._obj = obj
        self._stream = None
        if not direct and pythoncom:
            self._stream = pythoncom.CoMarshalInterThreadInterfaceInStream(pythoncom.IID_IDispatch, obj)
            self._obj = None
        self._thread = threading.Thread(target=self._run, name="b2s", daemon=True)
        self._thread.start()

    def _run(self):
        b2s = self._obj
        if self._stream is not None:
            pythoncom.CoInitialize()
            try:
                import win32com.client
                b2s = win32com.client.Dispatch(pythoncom.CoGetInterfaceAndReleaseStream(
                    self._stream, pythoncom.IID_IDispatch))
            except Exception as exc:                        # noqa: BLE001
                self.up = False
                self.why = "B2S.Server could not be reached: %s" % exc
                log(self.why)
                return
        failed = set()
        while True:
            item = self._q.get()
            if item is None:
                break
            call, args = item
            try:
                getattr(b2s, call)(*args)
                self.sent += 1
            except Exception as exc:                        # noqa: BLE001
                if call not in failed:
                    log("%s%r failed: %s" % (call, args, exc))
                failed.add(call)
        b2s = None

    def set(self, name, value):
        if self.up:
            self._q.put(("B2SSetIllumination", (str(name), int(value))))

    def data(self, number, value):
        """A DOF E event through B2S.Server (PAD-1480): B2SSetData with a
        number is what controller.vbs's own DOF sub sends, and B2S.Server's
        DOF plugin takes it as E<number>."""
        if self.up:
            self._q.put(("B2SSetData", (int(number), int(value))))

    def finish(self):
        if self.up:
            self.up = False
            self._q.put(None)
            self._thread.join(timeout=5)


class Bridge:
    """Everything that is not COM: the poll thread, the state, the pipe.
    Testable on its own (see --selftest and tests/test_vpx_bridge.py)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.map = VpxMap()
        self.title = ""
        self.rig = None
        self.pipe = None
        self.launch = None                 # the run this bridge started, if any
        self.attached = False              # the run is up and its tables read
        self.front_done = False            # the started run's LCD window was handed back once
        self.b2s_handed = set()            # ... and each backglass window, once (PAD-893)
        self.front_tries = {}              # hand-backs tried per window (PAD-949)
        self.attached_t = 0.0
        self.boot = None                   # a started run's boot, read until the game is in attract
        self.ready_t = 0.0                 # ... and when it got there (PAD-963)
        self.lcd_placed = False            # ... and put where the kit says, on top, once
        self.player_placed = False         # Visual Pinball's own window moved where the kit says, once
        self.start_t = 0.0
        self.running = False
        self.paused = False
        self._thread = None
        # lamps: number -> 0/1, as last published; pending: numbers changed
        self.lamp_state = {}
        self.lamp_pending = set()
        # solenoids: number -> 0/1; pending likewise
        self.sol_state = {}
        self.sol_pending = set()
        self.sol_unread_on = set()         # went ON since the table last read them
        self._coil_seen = {}               # (node, idx) -> (fires, until)
        self._coil_off_at = {}             # (node, idx) -> monotonic s
        self.sw_ids = {}                   # (node, input bit) -> switch id
        self._button_coils = {}            # (node, idx) -> button input bit
        # PAD-1304: the cabinet's own lights (BACKBOX GI, the START and
        # LOCKDOWN buttons) where the title's tables put them, the kit's
        # cabinet settings, and the backglass handed over for BACKBOX GI
        self.cab_leds = {}
        self.cab_strips = None             # PAD-1571: padcabinet.cabinet_strips
        self.cab_shaker = None             # PAD-1460: (node, idx) of the SHAKER MOTOR, None = none
        self.cab = padcabinet.settings({})
        self.b2s = None
        self._b2s_state = {}
        # switch id -> [((node, idx), release_now)]: the board-fired coils
        # each switch fires, from the last poll, so set_switch can turn the
        # coil on (and off) at once instead of a poll later
        self._rule_coils = {}
        self.mrg = bytes(padsw.MAX_ID)     # the guest's merged switch truth
        self.mech_pos = {}                 # GetMech number -> steps (PAD-1228)
        self.max_id = padsw.MAX_ID         # one past the highest switch id (set_game)
        self.polls = 0
        self.poll_fail = 0
        self.link_polls = 0             # polls served by the pushed copy (PAD-1306)
        self.link_idle = 0              # ...and those with nothing new to decode
        self._link_mark, self._link_t = None, 0.0
        self.last_poll_ms = 0.0
        self._fake = {}                    # name -> state for switch_fakes
        self._early = {}                   # switch id -> level the table set before the run was up
        self.dof = None                    # DofHost, when the table asked for DOF
        self._dof_state = {}               # (kind, number) -> value last sent
        self.own_sols = {}                 # number -> (node, index) the table's script gave (PAD-1303)

    # -- lifecycle
    def set_game(self, title):
        self.title = title
        self.map = VpxMap(title)
        # a coil number the table's own script gave (padvpx stubs, PAD-1303)
        # outlives the map: tables name their game in Table_Init, after the
        # stubs' top-level code has said its numbers
        self.map.solenoids.update(getattr(self, "own_sols", {}))
        # PAD-943: a Spike 1 title's switches are slots up to 1023
        self.max_id = self.rigmod.N_SLOTS if self.slots else padsw.MAX_ID
        log("game %s: map %s (%s): switches=%d solenoids=%d lamp groups=%d"
            % (title, self.map.path or "NONE", self.map.platform, len(self.map.switch_rewrite),
               len(self.map.solenoids), len(self.map.lamp_groups)))

    @property
    def native_title(self):
        return getattr(self.map, "game", None) or self.title

    @property
    def rigmod(self):
        """The rig module of a platform whose run publishes one block of
        slots (PAD-943, PAD-952): s1bridge for Spike 1, spkbridge for
        Spooky; None for Spike 2 (padled / padsw)."""
        return SLOT_BRIDGES.get(getattr(self.map, "platform", "spike2"))

    @property
    def slots(self):
        return self.rigmod is not None

    @property
    def spike1(self):
        return getattr(self.map, "platform", "spike2") == "spike1"

    @property
    def emu(self):
        """The board record's emulator for a Spike 2-shaped run: "spike3" for
        a Spike 3 title (PAD-1560), else "spike2"."""
        return "spike3" if getattr(self.map, "platform", "spike2") == "spike3" else "spike2"

    def own_solenoid(self, n, coil):
        """`Controller.PadSolenoid(n) = Array(node, index)` (PAD-1303): the
        table's script names a coil the map has no number for, so core.vbs's
        SolCallback(n) hears it. False (and a log line) when n is not 1 to
        the map's solenoid_max, or `coil` is not two numbers."""
        try:
            n = int(n)
            node, idx = (int(v) for v in coil)
        except (TypeError, ValueError):
            log("PadSolenoid %r = %r: want a number and Array(node, index)" % (n, coil))
            return False
        if not 0 < n <= self.map.sol_max or not (0 <= node < 16 and 0 <= idx < 16):
            log("PadSolenoid %d = (%d, %d): outside 1..%d or not a coil" % (n, node, idx, self.map.sol_max))
            return False
        with self.lock:
            self.own_sols[n] = (node, idx)
            self.map.solenoids[n] = (node, idx)
        log("table: coil (%d, %d) is solenoid %d" % (node, idx, n))
        return True

    def _sol_number(self, node, idx):
        return self.rigmod.sol_number(node, idx) if self.slots else sol_number(node, idx)

    def _rig_up(self, data):
        """A fresh read of the run's output block says the game is up."""
        if self.slots:
            return self.rigmod.is_up(data)
        return bool(data) and coilmap.has_magic(data)

    def dof_init(self, rom, table_file, factory=None):
        """Start DOF for the table's ROM name (PADSPIKE2.vbs, before it
        starts B2S.Server). True when DOF is up; a second call for the same
        name keeps the one that is up (the table's Reset key). A clone ROM
        whose config DOF keys by its parent gets the parent's (PAD-948)."""
        rom = dof_rom_for(rom, table_file)
        if self.dof and self.dof.up and self.dof.rom == rom:
            return True
        self.dof_finish()
        self.dof = DofHost(rom, table_file, factory=factory)
        self._dof_state = {}
        return self.dof.up

    def dof_send(self, kind, number, value):
        if self.dof:
            self.dof.send(kind, number, value)

    def dof_finish(self):
        if self.dof:
            self.dof.finish()
            self.dof = None

    def _dof_set(self, kind, number, value):
        if self._dof_state.get((kind, number)) != value:
            self._dof_state[(kind, number)] = value
            self.dof.send(kind, number, value)

    def _poll_dof(self, data):
        """The machine's coils and lights, as the ROM's S and L for DOF: a
        coil on its state (the board-fired ones included), a lamp lit when
        any of its LEDs is, a flasher at its LED's level."""
        m = self.map
        for n, key in m.dof_sols.items():
            self._dof_set("S", n, 1 if self.sol_state.get(sol_number(*key)) else 0)
        for n, leds in m.dof_lamps.items():
            level = max(self._led_level(data, nd, ix) for nd, ix in leds)
            self._dof_set("L", n, 1 if level >= LAMP_ON else 0)
        for n, leds in m.dof_flashers.items():
            level = max(self._led_level(data, nd, ix) for nd, ix in leds)
            self._dof_set("S", n, level if level >= LAMP_ON else 0)
        ev = self._cab_events(data)
        for n, v in ev:
            self._dof_set("E", n, v)
        self._note_strips("PAD's own DOF", ev)

    #: how often the controller log says what the strips sent DOF (PAD-1603)
    STRIP_LOG_S = 30.0

    def _note_strips(self, route, events, now=None):
        """The light strips in the controller log (PAD-1603): the first time
        they light, and every STRIP_LOG_S what they showed and how many
        changes went to DOF, or that the game kept them dark. Mike St P's
        report after a minute of Jaws named the strips' E numbers and nothing
        of what was sent on them, so it could not say whether PAD or the DOF
        config left his side LEDs dark."""
        base, parts = self.cab.get("dof_strips"), self.cab.get("strip_parts", 1)
        if not base or not getattr(self, "cab_strips", None):
            return
        now = time.monotonic() if now is None else now
        top = base + 2 * parts * len(padcabinet.STRIP_COLOURS)
        st = {n: v for n, v in events if base <= n < top}
        sl = getattr(self, "_strip_log", None)
        if sl is None:
            sl = self._strip_log = {"t": now, "prev": {}, "sent": 0, "polls": 0, "lit": 0,
                                    "shown": [], "first": True}
        sl["sent"] += sum(1 for n, v in st.items() if sl["prev"].get(n) != v)
        sl["prev"] = st
        sl["polls"] += 1
        lit = padcabinet.strip_lit(base, parts, sorted(st.items()))
        if lit:
            sl["lit"] += 1
            for _n, w, _v in lit:
                if w not in sl["shown"]:
                    sl["shown"].append(w)
            if sl["first"]:
                sl["first"] = False
                log("DOF strips: first lit, %s, to %s" % (
                    ", ".join("E%d = %d (%s)" % (n, v, w) for n, w, v in lit), route))
        if now - sl["t"] < self.STRIP_LOG_S:
            return
        secs = now - sl["t"]
        if sl["lit"]:
            log("DOF strips, last %.0f s, to %s: %d changes sent, lit in %d of %d polls, showed %s; now %s"
                % (secs, route, sl["sent"], sl["lit"], sl["polls"], ", ".join(sl["shown"]),
                   ", ".join("E%d = %d (%s)" % (n, v, w) for n, w, v in lit) or "dark"))
        else:
            log("DOF strips, last %.0f s, to %s: the game lit none of its %s, so E%d-E%d stayed 0"
                % (secs, route, "blades" if self.cab_strips["source"] == "blades" else "speaker lights",
                   base, top - 1))
        sl.update(t=now, sent=0, polls=0, lit=0, shown=[])

    def _cab_events(self, data):
        """[(E number, value)] of the cabinet's own DOF events: the buttons'
        LEDs (PAD-1304) and the machine's shaker motor, on while the game
        drives it (PAD-1460; the board stops a timed shake itself)."""
        out = []
        for key, n in (("start", self.cab["dof_start"]), ("lockdown", self.cab["dof_lockdown"])):
            leds = self.cab_leds.get(key)
            if n and leds:
                level = max(self._led_level(data, nd, ix) for nd, ix in leds)
                out.append((n, level if level >= LAMP_ON else 0))
        n = self.cab["dof_shaker"]
        if n and self.cab_shaker:
            out.append((n, 1 if self.sol_state.get(self._sol_num(self.cab_shaker)) else 0))
        # PAD-1571: the cabinet's light strips (blades, else speaker lights)
        out += padcabinet.strip_events(self.cab.get("dof_strips"), self.cab.get("strip_parts", 1),
                                       getattr(self, "cab_strips", None),
                                       lambda nd, ix: self._led_level(data, nd, ix), LAMP_ON)
        return out

    def _poll_b2s_dof(self, data):
        """The cabinet's E events through B2S.Server when PAD hosts no DOF of
        its own (PAD-1480): an original table PAD drives (vpxshadow) keeps the
        DOF its controller.vbs started inside B2S.Server, and Mike St P's Jaws
        shaker never reached it."""
        ev = self._cab_events(data)
        self._note_strips("the DOF in B2S.Server", ev)
        for n, v in ev:
            if self._b2s_dof.get(n) != v:
                if not self._b2s_dof:
                    log("DOF: the cabinet's E events (start E%s, lockdown E%s, shaker E%s, strips %s) go to"
                        " the DOF in B2S.Server" % (self.cab["dof_start"] or "-", self.cab["dof_lockdown"]
                                                    or "-", self.cab["dof_shaker"] or "-",
                                                    self._strips_words()))
                self._b2s_dof[n] = v
                self.b2s.data(n, v)

    #: ~10 s of polls: by then a table has started DOF or handed B2S.Server over
    E_ROUTE_POLLS = 1250

    def _tell_no_e_route(self):
        """PAD-1571: say so, once, when the cabinet's E events are set but
        nothing carries them: no DOF of PAD's own and no B2S.Server handed
        over. Mike St P's Jaws (PAD).vpx, patched before v1.552.2 (PAD-1480),
        never handed its B2S.Server over: the table's own DOF worked, the
        shaker and the light strips stayed dark, and the log said nothing."""
        cab = getattr(self, "cab", None) or {}
        if not any(cab.get(k) for k in ("dof_start", "dof_lockdown", "dof_shaker", "dof_strips")):
            return
        log("DOF: the cabinet's E events (start E%s, lockdown E%s, shaker E%s, strips %s) go nowhere:"
            " PAD hosts no DOF for this table and it handed no B2S.Server over (a table patched before"
            " v1.552.2: Patch it again)" % (cab.get("dof_start") or "-", cab.get("dof_lockdown") or "-",
                                           cab.get("dof_shaker") or "-", self._strips_words()))

    def b2s_attach(self, obj, direct=False):
        """PADSPIKE2.vbs's B2S.Server, once it runs (PAD-1304). A second
        call (the table's Reset) replaces the first."""
        self.b2s_finish()
        try:
            self.b2s = B2SHost(obj, direct=direct)
        except Exception as exc:                            # noqa: BLE001
            log("B2S.Server not taken: %s" % exc)
            self.b2s = None
            return False
        self._b2s_state = {}
        self._b2s_dof = {}
        self._b2s_gi_seen = False
        log("B2S.Server handed over; BACKBOX GI bulbs for %s: %s"
            % (self.title, ", ".join(self.cab["gi_bulbs"].get(self.title, [])) or "none named"))
        return True

    def b2s_finish(self):
        if self.b2s:
            self.b2s.finish()
            self.b2s = None

    def _poll_b2s(self, data):
        """BACKBOX GI on the backglass: each bulb the kit names for the
        title lit while the backbox's GI is, out while it is out. Not before
        the run has shown it lit once: jaws_le's attract never lit it under
        the emulator (node 0 dark throughout, 2026-11-14), and a backglass
        put dark by a light the run does not drive would be worse than one
        left as B2S shows it."""
        bulbs = self.cab["gi_bulbs"].get(self.title)
        leds = self.cab_leds.get("backbox_gi")
        if not bulbs or not leds:
            return
        on = 1 if max(self._led_level(data, nd, ix) for nd, ix in leds) >= LAMP_ON else 0
        if on:
            self._b2s_gi_seen = True
        elif not getattr(self, "_b2s_gi_seen", False):
            return
        for name in bulbs:
            if self._b2s_state.get(name) != on:
                self._b2s_state[name] = on
                self.b2s.set(name, on)

    def run(self):
        """Attach to the title's run, or START one (padlaunch) when none is
        up and a card for the title is known: Run returns at once, the poll
        thread attaches when the game is up, and the table plays from then
        on - switches before that are kept and handed over at attach (the
        table's trough, set once at its Init), Visual Pinball never waits."""
        self.rig = (self.rigmod.Rig(self.native_title) if self.slots
                    else Rig(self.native_title, emu=self.emu))
        self.pipe = None
        self.launch = None
        self.attached = False
        self.boot = None
        self.ready_t = 0.0
        self.start_t = time.monotonic()
        self._start_retried = False
        self._board_t = None           # when the started run's board record came (PAD-1208)
        self._block_said = False
        self.front_done = False            # the LCD window's first grab is undone once, never again
        self.b2s_handed = set()            # backglass windows whose first grab was undone (PAD-893)
        self.front_tries = {}
        self.lcd_placed = False
        self.lcd_tries = 0
        self.lcd_stable = 0
        self.player_placed = False
        self._player_client = self._player_unfill = self._player_filled = None
        log("rig: %s -> %s" % (self.rig.how, self.rig.dump))
        data = read_block(self.rig.led_path(), READ_N) if SHARE_ON else None
        if self._rig_up(data):
            self._attach(data)
        elif self._attach_unshared(data):
            pass
        else:
            card = padlaunch.card_for(self.title, self.map.platform)
            if not card:
                raise RuntimeError(
                    "no %s run is up for %s and no card image to start one "
                    "(looked in %s). Start the game first (the app's Emulate tab, "
                    "or watch.sh), or record its card: padvpx card %s <image>."
                    % (padlaunch.PLATFORM_NAMES.get(self.map.platform, self.map.platform),
                       self.title or "this title", padlaunch.card_places(self.title, self.map.platform),
                       self.title))
            self._carry_lcd_layout()
            self.launch = padlaunch.launch_for(self.map.platform, self.title, card)
            self._loading_start()
            try:
                slot = self.launch.start()
            except Exception as exc:
                self._loading_end("failed %s" % exc)
                raise
            self.rig = None
            log("starting %s on slot %d; the table plays once the game is up" % (self.title, slot))
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        if sys.platform == "win32" and not getattr(self, "_grips", None):
            try:
                self._grips = PlayerGrips(self)
            except Exception as exc:                        # noqa: BLE001
                log("player grips not started: %s" % exc)
        log("run")

    def _attach(self, data, pipe=None):
        """The run is up: read its tables, open the switch pipe, own the balls.
        `pipe`: the link a run the share cannot reach came up on (PAD-1437)."""
        if pipe is not None:
            pass
        elif self.slots:
            pipe = self.rigmod.Pipe(self.rig)
        elif LINK_ON and sys.platform == "win32" and isinstance(self.rig, Rig):
            pipe = RigLink(self.rig)       # PAD-1306: pushed from WSL, not read over 9p
        else:
            pipe = SwitchPipe(self.rig)
        with self.lock:
            early, self._early = self._early, {}
            self.pipe = pipe
        # PAD-878: what the table said while the game booted. A table sets its
        # trough once, at Init - Star Wars' physical trough by PadTroughSync,
        # the others by bsTrough.Balls - long before a run it started is up,
        # and those edges used to be dropped. The renderer's own boot fill
        # covered for it only where the slot had the title's switch list: on
        # Star Wars Pro's first run (its list cannot be read from the binary)
        # the game came up on an empty trough and searched for its balls.
        # A switch the table has set again since the pipe went up is newer.
        early = {sid: level for sid, level in sorted(early.items()) if sid not in pipe.held}
        for sid, level in early.items():
            pipe.set(sid, level)
        if early:
            log("handed the game %d switch(es) the table set while it booted: %s"
                % (len(early), " ".join("%d=%d" % kv for kv in early.items())))
        self._read_tables(data)
        for name, f in self.map.fakes.items():
            if f.get("kind") == "latch":
                # PAD-968: a latched post starts down (open), as the game leaves it
                self._fake[name] = {"up": 0, "was": (0, 0)}
                self.pipe.set(f["switch"], 0)
                self._sol_set(int(f["solenoid"]), 0)
                continue
            self._fake[name] = {"open": 0}
            self.pipe.set(f["closed"], 1)
            self.pipe.set(f["open"], 0)
        if hasattr(self.rig, "ballfeed_off"):
            self.rig.ballfeed_off(True)
        else:
            try:
                open(self.rig.ballfeed_off_path(), "w").write("PAD.Controller\n")
            except OSError as exc:
                log("ballfeed.off not written: %s" % exc)
        self.attached = True
        self.attached_t = time.monotonic()
        log("attached to %s after %.0f s" % (self.rig.how, time.monotonic() - self.start_t))
        if self.launch is not None:
            self._boot_watch()

    #: PAD-1306: the longest a link poll goes without decoding the block
    LINK_STALE_S = 0.5

    # -- PAD-963: a started run is up when the game is in attract
    #: how long a boot log may stay unreadable before the run counts as up
    BOOT_LOG_S = 15.0
    #: a Spike 3 run's: its first progress line can come minutes in (the
    #: card's first decrypt into the store), and every line after re-arms it
    S3_FIRST_LINE_S = 900.0
    #: a board record whose output block is not up this long after is said, with
    #: the run log's last lines (PAD-1208: attach normally comes ~20 s after it)
    BLOCK_LATE_S = 60

    def _boot_watch(self):
        """The padled block comes up early in a Spike 2 boot: Batman sat on
        "Startup In Progress" for two more minutes after it (its card read
        off D:), with the loading window gone and the hand-backs over, so the
        game's LCD window took the foreground and Visual Pinball paused until
        the player clicked it (David). So a run this bridge started is READY
        only when its log says attract (bootprog.py, as the app's footer and
        the playfield window read it); until then the loading window says
        which step the boot is on, and the run's windows are still handed
        back from (_starting). A rig that keeps no such log is ready now."""
        if self.emu == "spike3" and isinstance(self.launch, padlaunch.Spike3Launch):
            # PAD-1560: a Spike 3 run says its boot in its own output
            # (s3prog.py's `[s3run] progress` lines), from this launch on
            self.boot = padlaunch.Spike3Boot(self.launch.logfile, self.launch.log_from)
            self._boot_seen = time.monotonic()
            self.BOOT_LOG_S = self.S3_FIRST_LINE_S
            self._poll_boot()
            return
        logdir = ""
        if not self.slots and self.rig is not None and getattr(self.rig, "slot", None):
            # a slot's logs are beside its root: padslots/<n>/root/dump
            logdir = (self.rig.boot_log_dir() if hasattr(self.rig, "boot_log_dir")
                      else os.path.dirname(os.path.dirname(self.rig.dump)))
        if not logdir:
            self._ready()
            return
        self.boot = bootprog.BootLog(logdir)
        self._boot_seen = time.monotonic()
        self._poll_boot()

    def _poll_boot(self):
        """Once a second until the started run's game is in attract."""
        if self.boot is None:
            return
        now = time.monotonic()
        if self.rig is not None and not getattr(self.rig, "share", True):
            self.rig.boot_log_dir()                 # PAD-1437: a fresh copy through WSL
        got = self.boot.poll()
        if got is None:
            if now - self._boot_seen > self.BOOT_LOG_S:
                log("no boot log at %s: the game counts as up" % self.boot.logdir)
                self._ready()
            return
        self._boot_seen = now
        state, pct, words = got
        if state == "attract":
            self._ready()
        elif "Stuck" in words or now - self.start_t > self.START_TIMEOUT_S:
            # the game's own screen says what it needs (Service Back): the
            # loading window must not stand over it
            log("game not in attract after %.0f s (%s); its window is the player's"
                % (now - self.start_t, words))
            self._ready()
        else:
            self._loading_say("boot %d %s" % (pct, words))

    def _ready(self):
        self.boot = None
        self.ready_t = time.monotonic()
        took = self.ready_t - self.start_t
        log("game ready after %.0f s" % took)
        self._loading_end("up", took)

    # -- PAD-940: the loading window, while a run this bridge started comes up
    def _loading_start(self):
        """padloading.py where the game's screen goes, for a run this bridge
        starts: a minute and more of nothing read as broken. Its own
        process (Tk), so nothing here waits on it; Windows only."""
        self._loading = None
        self._loading_split = False
        if sys.platform != "win32":
            return
        self._loading_file = os.path.join(os.path.dirname(LOG), "padloading-%s.txt" % (self.title or "game"))
        try:
            os.remove(self._loading_file)
        except OSError:
            pass
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = exe if os.path.isfile(exe) else sys.executable
        try:
            at = os.path.getsize(self.launch.logfile)       # this run's lines start here (PAD-964)
        except OSError:
            at = 0
        cmd = [exe, os.path.join(HERE, "padloading.py"), self.title or "", self.launch.logfile,
               self._loading_file, "--parent", str(os.getpid()), "--from", str(at)]
        took = (padlaunch.kit_load().get("start_s") or {}).get(self.title)
        if took:
            cmd += ["--expect", "%d" % took]
        if padlaunch.is_bof(self.launch) and padlaunch.split_env():
            # a BoF game on a cabinet's screens (PAD-1308): padsplit is the
            # loading screen on each of them, then the game's displays, and
            # gives Visual Pinball back the focus the game's window takes
            cmd = [exe, os.path.join(HERE, "padsplit.py"), "--title", self.title or "",
                   "--status", self._loading_file, "--parent", str(os.getpid()),
                   "--focus", "vpx", "--log", os.path.join(os.path.dirname(LOG), "padsplit.log")]
            self._loading_split = True
        try:
            self._loading = subprocess.Popen(cmd, cwd=HERE, creationflags=0x08000000)
            log("loading window up for %s%s" % (self.title, " (%d s last time)" % took if took else ""))
        except OSError as exc:
            log("loading window not started: %s" % exc)

    @staticmethod
    def _loading_kill(proc):
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:                                   # noqa: BLE001
            pass

    def _loading_say(self, word):
        """A line for the loading window while the game boots: `boot <pct>
        <words>` (padloading.py shows it)."""
        if not getattr(self, "_loading", None):
            return
        try:
            with open(self._loading_file, "w", encoding="utf-8") as f:
                f.write(word)
        except OSError:
            pass

    def _split_end(self):
        """The table closed: a cabinet split ends (its `stop`, then gone),
        whether the game was up yet or still starting."""
        if getattr(self, "_loading_split", False) and getattr(self, "_loading", None):
            self._loading_end("stop")
        proc, self._split = getattr(self, "_split", None), None
        if proc is not None:
            try:
                with open(self._loading_file, "w", encoding="utf-8") as f:
                    f.write("stop")
            except OSError:
                pass
            kill = threading.Timer(2.0, self._loading_kill, (proc,))
            kill.daemon = True
            kill.start()

    def _loading_end(self, word, took=None):
        """`up` closes it; `failed <why>` shows why, then closes it. The time
        a start took paces the next one's bar."""
        if not getattr(self, "_loading", None):
            return
        proc, self._loading = self._loading, None
        try:
            with open(self._loading_file, "w", encoding="utf-8") as f:
                f.write(word)
        except OSError as exc:
            log("loading window not told %s: %s" % (word, exc))
        if getattr(self, "_loading_split", False) and word == "up":
            # the split's windows ARE the game's screens now: kept until the
            # table closes (_split_end)
            self._split = proc
        else:
            # and gone for sure: `up` at once, a failure once it has been
            # read (`stop`: the split closes itself, given two seconds)
            wait = {"up": 0.0, "stop": 2.0}.get(word, 10.0)
            kill = threading.Timer(wait, self._loading_kill, (proc,))
            kill.daemon = True
            kill.start()
        if took:
            try:
                kit = padlaunch.kit_load()
                kit.setdefault("start_s", {})[self.title] = int(round(took))
                padlaunch.kit_save(kit)
            except (OSError, ValueError) as exc:
                log("start time not kept: %s" % exc)

    def _read_tables(self, data):
        """The run's switch table (the rig writes it a little after the game
        is up, so a run this bridge started may be read again) and the
        flipper buttons' coils for a run without the rule plane."""
        self.sw_ids = self.rig.switch_ids(self.native_title)
        if self.slots:
            # PAD-943: no rule plane on this rig; a held flipper button is a
            # held flipper coil, and the map's game_on is always armed (the
            # Spooky board publishes its flipper coils itself: no ids needed)
            log("switch table: %d ids (%s: %s)"
                % (len(self.sw_ids), padlaunch.PLATFORM_NAMES.get(self.map.platform, self.map.platform),
                   "the board's armed rules fire its coils" if hasattr(self.rigmod, "rules")
                   else "button coils assumed live"))
            ver = 0
        else:
            ver = struct.unpack_from("<I", data, 4)[0]
            log("switch table: %d ids; padled version %d%s"
                % (len(self.sw_ids), ver, "" if ver >= 7 else
                   " (no coil-rule plane: button coils assumed live)"))
        # the flipper buttons' coils, for a run without the rule plane:
        # {coil: the board input of its button}, from the map's cabinet ids
        self._button_coils = {}
        cab = self.map.cabinet
        by_id = {v: k for k, v in self.sw_ids.items()}       # id -> (node, bit)
        for coil, key in ((self.map.coil(48), "left_flipper"),
                          (self.map.coil(46), "right_flipper"),
                          (self.map.coil(36), "up_left_flipper")):
            sid = cab.get(key, 0) - 1000
            if coil and sid in by_id:
                self._button_coils[coil] = by_id[sid][1]
        if not self.slots:                 # Spike 2's cabinet and backbox boards
            try:
                self._read_cabinet()
            except Exception as exc:                        # noqa: BLE001
                log("cabinet lights not read: %s" % exc)

    def _read_cabinet(self, tables_dir=None, kit=None):
        """The cabinet's lights on this title's boards and the kit's cabinet
        settings (PAD-1304), read with the run's tables."""
        if tables_dir is None and hasattr(self.rig, "tables_dir"):
            tables_dir = self.rig.tables_dir(self.native_title)
        if tables_dir is None:
            tables_dir = os.path.join(self.rig.dump, "tables", self.native_title or "")
        self.cab_leds = padcabinet.cabinet_leds(tables_dir)
        self.cab = padcabinet.settings(padlaunch.kit_load() if kit is None else kit)
        try:                                # PAD-1460: the shaker, for DOF
            self.cab_shaker = coilmap.shaker_address(os.path.join(tables_dir, "device_xy.txt"))
        except Exception:                                   # noqa: BLE001
            self.cab_shaker = None
        try:                                # PAD-1571: the light strips, for DOF
            self.cab_strips = padcabinet.cabinet_strips(tables_dir)
        except Exception:                                   # noqa: BLE001
            self.cab_strips = None
        self._strip_log = None              # PAD-1603: a fresh strip log a run
        bulbs = self.cab["gi_bulbs"].get(self.title, [])
        log("cabinet lights: %s; DOF start E%s, lockdown E%s, shaker E%s (%s), strips %s; BACKBOX GI bulbs: %s"
            % (", ".join("%s %s" % (k, v) for k, v in sorted(self.cab_leds.items())) or "none named",
               self.cab["dof_start"] or "-", self.cab["dof_lockdown"] or "-", self.cab["dof_shaker"] or "-",
               ("node %d coil %d" % self.cab_shaker) if self.cab_shaker else "no shaker",
               self._strips_words(), ", ".join(bulbs) or "none"))

    def _strips_words(self):
        """The light strips' DOF events in words, for the log (PAD-1571)."""
        base, st = self.cab.get("dof_strips"), getattr(self, "cab_strips", None)
        if not st:
            return "- (no blades or speaker lights on this title)"
        what = "%s, node %d, %d+%d pixels" % (st["source"], st["node"], len(st["sides"][0]), len(st["sides"][1]))
        if not base:
            return "off (%s)" % what
        parts = self.cab.get("strip_parts", 1)
        return "E%d-E%d (%s; %d part%s a side, %d colours each)" % (
            base, base + 2 * parts * len(padcabinet.STRIP_COLOURS) - 1, what, parts,
            "" if parts == 1 else "s", len(padcabinet.STRIP_COLOURS))

    #: how long a run started for a table may take to come up (a card copied
    #: into the cache first, then the boot)
    START_TIMEOUT_S = 420

    # -- PAD-1437: a run whose files Windows cannot open over \\wsl.localhost
    #: from its board record, how long Windows may fail to open the block
    #: before WSL is asked whether the game has it (a game opens it ~20 s in)
    SHARE_PROBE_S = 12
    #: and how often WSL is asked after that
    SHARE_PROBE_EVERY_S = 5

    def _attach_unshared(self, data, wait_s=None):
        """A run already up that Windows cannot read over the share but WSL
        can (PAD-1437): attached through its link. False when that is not
        the case, or the link would not come up."""
        if data is not None and SHARE_ON:
            return False
        if not self._can_go_unshared() or not self.rig.root:
            return False
        if not block_in_wsl(self.rig):
            return False
        self._go_unshared()
        link = self._unshared
        end = time.monotonic() + (RigLink.HELLO_S + 1 if wait_s is None else wait_s)
        while time.monotonic() < end:
            got = link.blocks()
            if got and self._rig_up(got[0]):
                self._unshared = None
                log("the run came up through WSL")
                self._attach(got[0], pipe=link)
                return True
            if link.state == "down":
                break
            link.news.wait(0.2)
        self._unshared = None
        link.close()
        self.rig.share = SHARE_ON
        log("the run's link did not come up (%s)" % (link.why or "no blocks"))
        return False

    def _can_go_unshared(self):
        return (LINK_ON and sys.platform == "win32" and not self.slots
                and isinstance(self.rig, Rig) and bool(self.rig.root) and bool(self.rig.distro))

    def _stop_stuck(self, why="the game is up, Windows cannot read it"):
        log("WSL's link to Windows is stuck: %s; stopping the run (Restart WSL clears it)" % why)
        self._loading_end("failed " + WSL_STUCK)
        failed, self.launch, self.rig = self.launch, None, None
        link, self._unshared = getattr(self, "_unshared", None), None
        if link is not None:
            link.close()
        failed.stop()

    def _go_unshared(self):
        """Windows cannot open the block, WSL has it with its mark: run the
        table through wsl.exe (padlink.py and fetched files) instead of
        stopping it (PAD-1437)."""
        self.rig.share = False
        log("Windows cannot open the run's files over \\wsl.localhost, but the game is "
            "up inside WSL: the table takes its lights, coils and switches through WSL "
            "instead (PAD-1437)")
        self._unshared = RigLink(self.rig)

    def _poll_unshared(self, data):
        """True when this poll was a run going through WSL: attached once its
        link brought the block, or stopped when the link could not come up."""
        link = getattr(self, "_unshared", None)
        if link is not None:
            got = link.blocks()
            if got and self._rig_up(got[0]):
                self._unshared = None
                log("the run came up through WSL")
                self._attach(got[0], pipe=link)
                return True
            if link.state == "down":
                self._stop_stuck("the game is up inside WSL, and neither Windows' share "
                                 "nor wsl.exe can reach it (%s)" % link.why)
                return True
            return False
        if (data is not None and SHARE_ON) or not self._can_go_unshared():
            return False
        now = time.monotonic()
        t0 = getattr(self, "_board_t", None)
        if t0 is None:
            self._board_t = t0 = now
        if SHARE_ON and now - t0 < self.SHARE_PROBE_S:
            return False
        if now - getattr(self, "_share_probe_t", -1e9) < self.SHARE_PROBE_EVERY_S:
            return False
        self._share_probe_t = now
        if not block_in_wsl(self.rig):
            return False
        again = read_block(self.rig.led_path(), READ_N) if SHARE_ON else None
        if self._rig_up(again):                               # the share caught up after all
            self._attach(again)
            return True
        self._go_unshared()
        return True

    #: how often a run through WSL starts its link again once it dropped
    RELINK_S = 5.0

    def _relink(self, link):
        """A run the share cannot reach has nothing to fall back on: its link
        is started again, every held switch handed over (PAD-1437)."""
        now = time.monotonic()
        if now - getattr(self, "_relink_t", -1e9) < self.RELINK_S:
            return
        self._relink_t = now
        new = RigLink(self.rig)
        for sw, level in sorted(link.held.items()):
            new.set(sw, level)
        with self.lock:
            if self.pipe is not link:
                new.close()
                return
            self.pipe = new
        link.close()
        log("link started again (the run's files cannot be read over the share)")

    def _poll_starting(self):
        """Once a second until the run this bridge started is up."""
        if self.launch is None:
            return
        if self.rig is None:
            rec = (self.rigmod.board_record(self.native_title) if self.slots
                   else Rig.board_slot(self.launch.slot) if self.emu == "spike2"
                   else Rig.board_slot(self.launch.slot, self.emu))
            if rec:
                self.rig = (self.rigmod.Rig(self.native_title, record=rec) if self.slots
                            else Rig(self.native_title, record=rec, emu=self.emu))
                log("rig: %s -> %s" % (self.rig.how, self.rig.dump))
        if self.rig is not None:
            data = read_block(self.rig.led_path(), READ_N) if SHARE_ON else None
            if self._rig_up(data):
                self._attach(data)
                return
            if self._poll_unshared(data):
                return
            # PAD-1208: a game is up ~20 s after its board record; one whose
            # block never came said nothing here, and the table sat idle
            now = time.monotonic()
            if getattr(self, "_board_t", None) is None:
                self._board_t = now
            elif (not getattr(self, "_block_said", False) and self.launch.alive()
                  and now - self._board_t > self.BLOCK_LATE_S):
                self._block_said = True
                # PAD-1247: and as WSL itself reads it, which tells a stuck
                # WSL-to-Windows link from a game that never opened its block
                seen = None if self.slots else block_in_wsl(self.rig)
                log("the game's output block (%s) is not up %d s after its board record "
                    "came (%s; inside WSL %s)%s"
                    % (self.rig.led_path(), self.BLOCK_LATE_S, block_state(data),
                       {True: "it has its mark", False: "it has none either",
                        None: "WSL did not say"}[seen],
                       run_log_said(self.launch.logfile)))
                if seen and not self._can_go_unshared():
                    self._stop_stuck()
                    return
                if seen and getattr(self, "_unshared", None) is None:
                    self._go_unshared()
        if not self.launch.alive():
            # A board record can appear before the game is ready. It does
            # not make an exited launcher alive: clean the run we owned,
            # including its slot, before reporting failure or trying again.
            failed = self.launch
            logfile = failed.logfile
            link, self._unshared = getattr(self, "_unshared", None), None
            if link is not None:
                link.close()
            self.launch, self.rig = None, None
            failed.stop()
            retry_titles = padlaunch.kit_load().get("startup_retry_titles", [])
            if (self.running and isinstance(retry_titles, list) and self.title in retry_titles
                    and not self._start_retried):
                self._start_retried = True
                log("retrying %s once after its startup process exited" % self.title)
                self.start_t = time.monotonic()
                self.boot, self.ready_t = None, 0.0
                self._board_t, self._block_said = None, False
                self.front_done, self.front_tries = False, {}
                self.lcd_placed = False
                self.lcd_tries = self.lcd_stable = 0
                retry = padlaunch.launch_for(self.map.platform, self.title, failed.card)
                self.launch = retry
                try:
                    slot = retry.start()
                    if not self.running:
                        retry.stop()
                        if self.launch is retry:
                            self.launch = None
                    else:
                        log("retry started %s on slot %d" % (self.title, slot))
                    return
                except Exception as exc:
                    retry.stop()
                    if self.launch is retry:
                        self.launch = None
                    self._loading_end("failed Startup retry failed: %s" % exc)
                    return
            log("the run started for %s ended before it came up (see %s)%s"
                % (self.title, logfile, run_log_said(logfile)))
            self._loading_end("failed The emulator stopped before the game came up. Its log: %s"
                              % logfile)
        elif time.monotonic() - self.start_t > self.START_TIMEOUT_S:
            log("the run started for %s is not up after %d s; giving up on it"
                % (self.title, self.START_TIMEOUT_S))
            self._loading_end("failed The game was not up after %d s. Its log: %s"
                              % (self.START_TIMEOUT_S, self.launch.logfile))
            self.launch.stop()
            self.launch = None

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if getattr(self, "_grips", None):
            self._grips.stop()
            self._grips = None
        if self.pipe:
            self.pipe.close()
        link, self._unshared = getattr(self, "_unshared", None), None
        if link is not None:
            link.close()
        if self.rig:
            if hasattr(self.rig, "ballfeed_off"):
                self.rig.ballfeed_off(False)
            else:
                try:
                    os.remove(self.rig.ballfeed_off_path())
                except OSError:
                    pass
        log("stop after %d polls (%d off the link, %d of them idle, %d failed)"
            % (self.polls, self.link_polls, self.link_idle, self.poll_fail))
        self._split_end()                        # a BoF game's cabinet screens close with it
        self._loading_end("up")                  # the table closed while the game started
        if self.launch is not None:
            self.launch.stop()           # what this bridge started, it stops
            self.launch = None

    def set_pause(self, want):
        """VPX pauses when its window loses focus and says so through
        Controller.Pause, a LEVEL; the rig's pause is a TRUE freeze of the
        game (PAD-204) that one `pause` line TOGGLES. So read the rig's own
        `paused` flag (padsw) and toggle only when it differs from what VPX
        wants: two Pause=True in a row must not un-freeze the game."""
        want = 1 if want else 0
        if not self.attached or not self.pipe:
            self.paused = bool(want)         # nothing to freeze yet
            return
        self.paused = bool(want)
        if not self.pipe or not self.rig:
            return
        if want:
            self._release_buttons()
        if self.slots:
            self.pipe.pause()                # says once that this rig has none
            return
        if want and kit_window_in_front():
            # the player clicked the game's own LCD or playfield window (to
            # move it, to look at it): Visual Pinball pauses, the GAME does
            # not - freezing it here left the screen dead under the mouse
            log("pause from the kit's own window in front: the game runs on")
            return

        def rig_flag():
            if not getattr(self.rig, "share", True):          # PAD-1437
                sw = self.rig.wsl_read("padsw", padsw.OFF_PAUSED + 4)
            else:
                sw = read_block(self.rig.sw_path(), padsw.OFF_PAUSED + 4)
            return struct.unpack_from("<I", sw, padsw.OFF_PAUSED)[0] if sw and len(sw) > padsw.OFF_PAUSED else -1

        now = rig_flag()
        if now != want:
            self.pipe.pause()
            # VPX flips Pause twice within a few ms as its player starts; the
            # rig takes ~10 ms to act on a toggle, so wait for the flag to
            # follow before the next call reads it - or the second call sees
            # the old value, sends nothing, and the game stays frozen.
            for _ in range(30 if getattr(self.rig, "share", True) else 3):
                time.sleep(0.01)
                now = rig_flag()
                if now == want:
                    break
        log("pause -> %d (rig now %d)" % (want, now))

    #: the cabinet buttons a player holds down with a key
    BUTTONS = ("start", "launch", "left_flipper", "right_flipper",
               "up_left_flipper", "up_right_flipper", "tilt")

    def _release_buttons(self):
        """Visual Pinball delivers a key's release only while its window has
        the focus, so a key held as the focus goes (David clicked the game's
        display to drag it) stays pressed in the game for good: TMNT's
        launch button stuck down and every ball was launched the moment it
        reached the shooter lane, a game nobody could play (PAD-811). Losing
        the focus lets go of every cabinet button, as letting go of the keys
        would."""
        cab = getattr(self.map, "cabinet", None) or {}
        for key in self.BUTTONS:
            n = cab.get(key)
            if not n or not self.pipe:
                continue
            sid = self.map.switch_id(int(n))
            if sid > 0 and self.pipe.held.get(sid) == 1:
                self.set_switch(int(n), 0)
                log("focus lost: %s (switch %d) let go" % (key, sid))
        for n in SERVICE if self.pipe else ():
            sid = self.switch_id(n)
            if sid > 0 and self.pipe.held.get(sid) == 1:
                self.set_switch(n, 0)
                log("focus lost: service %d (switch %d) let go" % (n, sid))

    # -- switches
    def switch_id(self, n):
        """The map's switch id for table number `n`; a SERVICE button by its
        wire in this run's switch table (0 until the table is read)."""
        if n is not None and int(n) in SERVICE:
            own = self.map.cabinet.get(SERVICE_KEYS[int(n)])
            if own:
                return own - 1000
            return (getattr(self, "sw_ids", None) or {}).get(SERVICE[int(n)], 0)
        return self.map.switch_id(n)

    def set_switch(self, n, level):
        sid = self.switch_id(n)
        if getattr(self, "dof", None) and self.dof.up:
            for w in self.map.dof_switches.get(sid, ()):
                self._dof_set("W", w, 1 if level else 0)
        if not 0 < sid < getattr(self, "max_id", padsw.MAX_ID):
            return
        if not self.pipe:
            with self.lock:
                if not self.pipe:
                    # the run is not up yet: kept for _attach, which hands it over
                    self._early[sid] = 1 if level else 0
                    return
        if self.pipe.held.get(sid) != (1 if level else 0):
            log("sw %s -> id %d = %d" % (n, sid, 1 if level else 0))
        self.pipe.set(sid, level)
        # A board-fired coil (a flipper) follows its switch NOW, not on the
        # next poll (~25-30 ms a cycle over \\wsl.localhost): the same answer
        # _poll_coils gives from pipe.held, so the next poll agrees with it.
        rc = (getattr(self, "_rule_coils", None) or {}).get(sid)
        if rc:
            now = time.monotonic()
            with self.lock:
                for key, release_now in rc:
                    if level:
                        self._coil_set(key, 1)
                    elif release_now and self._coil_off_at.get(key, 0) <= now:
                        self._coil_set(key, 0)

    def get_switch(self, n):
        sid = self.switch_id(n)
        if sid <= 0:
            return False
        if not self.pipe and sid in self._early:
            got = bool(self._early[sid])
        elif self.pipe and sid in self.pipe.held:
            got = bool(self.pipe.held[sid])
        else:
            got = bool(self.mrg[sid]) if sid < len(self.mrg) else False
        # PAD-1225: what the table READ, each time it changes - Batman 66's
        # turntable and crane follow the machine by reading its position
        # switches, and a report of a turntable that never moved could not
        # say whether the table read them at all, or what it was told
        seen = self.__dict__.setdefault("_reads", {})
        if seen.get(sid) is not got:
            seen[sid] = got
            log("table reads switch %d = %d%s" % (sid, got, "" if self.attached
                                                    else " (before the game is up)"))
        return got

    # -- the poll
    def _poll_loop(self):
        last_front = 0.0
        while self.running:
            now = time.monotonic()
            # PAD-893: the backglass's grab is undone for any run, not only
            # one this bridge started, so the watch runs for every Run
            if now - last_front >= 1.0 and now - self.start_t < FRONT_WATCH_S:
                last_front = now
                self._find_player()
                if self.launch is not None and not self.lcd_placed:
                    self._place_lcd()
                self._keep_player_front()
            if not self.player_placed and now - self.start_t < FRONT_WATCH_S:
                self._place_player()
            if not self.attached:
                self._poll_starting()
                time.sleep(1.0)
                continue
            if self.boot is not None and now - getattr(self, "_boot_check", 0.0) >= 1.0:
                self._boot_check = now
                self._poll_boot()
            t0 = time.monotonic()
            self._poll_once()
            if now - getattr(self, "_front_check", 0.0) >= 0.25:
                self._front_check = now
                self._watch_focus()
                self._watch_player()
            self.last_poll_ms = (time.monotonic() - t0) * 1000.0
            self._poll_wait()

    #: PAD-1306: a poll on the link waits for news, but never closer than this
    LINK_MIN_S = 0.003

    def _poll_wait(self):
        """Sleep to the next poll: POLL_S, or on the link until it sends a
        change (it pushes within ~2 ms of the game), at least LINK_MIN_S on."""
        news = getattr(self.pipe, "news", None)
        if news is None or getattr(self.pipe, "state", "") != "up":
            time.sleep(POLL_S)
            return
        time.sleep(self.LINK_MIN_S)
        news.wait(max(0.0, POLL_S - self.LINK_MIN_S))
        news.clear()

    def _find_player(self):
        """The player window of a table that ran the controller without
        GetPlayerHWnd (PAD-933: The Beatles' and TMNT's `Controller.Run`, as
        their ROM scripts had it): found by its title, as B2S.Server finds it,
        so the grips, the placing and the size watch follow it as they do a
        handed one - the Beatles' playfield could not be moved or resized."""
        if sys.platform != "win32" or getattr(self, "player_hwnd", 0):
            return
        try:
            hwnd = find_player_window()
        except Exception:                                   # noqa: BLE001
            return
        if hwnd:
            self.player_hwnd = hwnd
            log("player window found by its title (the table ran the controller without it)")

    def _watch_focus(self):
        """Not every table tells the controller it lost the focus (TMNT's
        never said Pause), so the foreground itself is watched: the moment
        Visual Pinball's player is not the window in front, the held
        buttons are let go (_release_buttons)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(u.GetForegroundWindow(), buf, 256)
            front = buf.value.startswith("Visual Pinball Player")
        except Exception:                                   # noqa: BLE001
            return
        if getattr(self, "_player_front", True) and not front:
            self._release_buttons()
        self._player_front = front

    #: the kit's windows a started run opens, by the word in their title,
    #: and the kit setting that places each
    WINDOWS = (("lcd", "emulator"), ("playfield", "virtual playfield"))

    def _place_lcd(self):
        """The started run's windows (their titles carry the PAD-VPX label:
        the LCD, `... - Stern Spike 2 emulator`, and the virtual playfield
        when the kit asked for one) are put where the kit says, the LCD ON
        TOP: Visual Pinball comes up full screen and would cover it. The
        kit's `lcd` / `playfield` (padvpx lcd, padvpx playfield) name a
        monitor to fill, a rectangle, or nothing - then the upper middle of
        the main screen, 40% of its width in the LCD's 16:9.

        ONCE, AND THEN HANDS OFF. A WSLg window re-places itself at the
        screen's top-left a few seconds after it opens, undoing a move that
        read back fine, so for the first PLACE_S seconds a window found back
        at the top-left is put again; anywhere else it is where the user
        dragged it, and it stays there. David's first try had the window
        snapping back under the mouse (2026-10-28)."""
        if sys.platform != "win32":
            self.lcd_placed = True
            return
        kit = padlaunch.kit_load()
        self.lcd_tries = getattr(self, "lcd_tries", 0) + 1
        if not hasattr(self, "placed_at"):
            self.placed_at = {}
        try:
            dpi_aware()
            done = True
            shown = display_setting()
            for key, word in self.WINDOWS:
                setting = kit.get(key) if key == "lcd" else kit.get(key)
                if key == "playfield" and not setting:
                    continue                     # no playfield window asked for
                hwnd = find_kit_window(word)
                if not hwnd:
                    done = False if key == "lcd" else done
                    continue
                if key == "lcd" and shown:
                    # PAD-811: the renderer puts it where display.conf says
                    # (and keeps it there as that changes); here only ON TOP
                    # of Visual Pinball, which comes up full screen
                    if key not in self.placed_at:
                        # PAD-1231: on top unless the tab's Always on top is off
                        on_top = bool((setting or {}).get("topmost", True))
                        raise_window(hwnd, on_top)
                        self.placed_at[key] = time.monotonic()
                        log("lcd window left to the display setting (%s), %s"
                            % (shown.get("mode"), "on top" if on_top else "not on top"))
                    continue
                rect = lcd_rect(setting or {}, monitors())
                if key == "playfield" and not any(k in (setting or {}) for k in ("x", "monitor")):
                    # no spot asked for: under the LCD, down to the screen's bottom
                    lx, ly, lw, lh = lcd_rect(kit.get("lcd") or {}, monitors())
                    mons = monitors() or [(0, 0, 1920, 1080)]
                    rect = (lx, ly + lh, lw, max(300, mons[0][3] - (ly + lh)))
                topmost = bool((setting or {}).get("topmost", key == "lcd"))
                first = self.placed_at.get(key)
                now = window_rect(hwnd)
                if first is None:
                    place_window(hwnd, rect, topmost)
                    self.placed_at[key] = time.monotonic()
                    log("%s window placed at %s%s" % (key, rect, ", on top" if topmost else ""))
                    done = False
                elif time.monotonic() - first < PLACE_S:
                    if at_reset_spot(now) and not all(abs(a - b) <= 40 for a, b in zip(now, rect)):
                        place_window(hwnd, rect, topmost)
                        log("%s window put back from the top-left (%s)" % (key, now))
                    done = False
            if done or self.lcd_tries >= 60:
                self.lcd_placed = True
                log("windows are the user's from here (%d checks)" % self.lcd_tries)
        except Exception as exc:                            # noqa: BLE001
            log("window placement failed: %s" % exc)
            self.lcd_placed = True

    def _carry_lcd_layout(self):
        """carry_lcd_layout for this run, before its window opens: the
        renderer then maps it borderless and full screen itself."""
        if sys.platform != "win32":
            return
        try:
            kit = padlaunch.kit_load()
            if kit.get("display_carried"):
                return
            s = carry_lcd_layout(kit)
            padlaunch.kit_save(kit)
            if s:
                log("lcd: the layout's screen is now the display setting (%s on monitor %s, "
                    "borderless)" % (s["mode"], s["monitor"]))
        except Exception as exc:                            # noqa: BLE001
            log("lcd: layout not carried into the display setting: %s" % exc)

    def _place_player(self):
        """Visual Pinball's own playfield window, where the kit's `player`
        says (padvpx player): borderless in windowed mode, so the user
        cannot drag it, and 10.8 ignores WindowPosX/Y in its ini. Moved
        once per Run, for any run (not only one this bridge started); its
        size stays Visual Pinball's own unless the kit gives one."""
        hwnd = getattr(self, "player_hwnd", 0)
        setting = padlaunch.kit_load().get("player")
        if sys.platform != "win32":
            self.player_placed = True
            return
        if not hwnd:
            return
        try:
            import ctypes
            # A minimized player has an icon rectangle (often at -32000),
            # not its playfield's proportions. Wait until it is restored.
            if ctypes.windll.user32.IsIconic(ctypes.c_void_p(hwnd)):
                return
            dpi_aware()
            # THE TABLE'S OWN PROPORTIONS (PAD-811): Visual Pinball scales its
            # picture to the window, so a window forced to the kit's 1440x2160
            # squeezed a table that opens at 2000x1500 (JAWS, Metallica: "way
            # too stretched vertically"). Read before the frame goes on (the
            # borderless window IS the picture); a saved width scales it, the
            # height follows; a saved height is not used.
            cur = window_rect(hwnd)
            aspect = cur[3] / float(cur[2]) if cur[2] else 1.0
            self.player_aspect = aspect
            framed = self._frame_player(hwnd)
            if not setting:
                self.player_placed = True
                log("player window left where Visual Pinball put it (%s)%s"
                    % (cur, ", framed" if framed else ""))
                return
            if "monitor" in setting:
                mx, my, mw, mh = lcd_rect(setting, monitors())
                w = min(mw, int(mh / aspect))
                h = int(w * aspect)
                x, y = mx + (mw - w) // 2, my + (mh - h) // 2
            else:
                x, y = int(setting["x"]), int(setting["y"])
                w = int(setting.get("w", cur[2]))
                h = int(round(w * aspect))
                x, y, w, h = fit_on_monitor((x, y, w, h), aspect, monitors())
            ow, oh = self._outer_for_client(hwnd, w, h) if framed else (w, h)
            place_window(hwnd, (x, y, ow, oh), False)
            self.player_placed = True
            log("player window placed at %s, picture %dx%d (was %s)" % ((x, y, ow, oh), w, h, cur))
        except Exception as exc:                            # noqa: BLE001
            log("player window not placed: %s" % exc)
            self.player_placed = True

    # ---- the playfield window, by hand (PAD-811) ------------------------
    #
    # David: "i just need to be able to move them around and resize those
    # windows like we do for the display" - Visual Pinball's windowed player
    # has no frame, so it could not be moved at all. It gets a title bar and
    # resize edges (WS_CAPTION | WS_THICKFRAME; Visual Pinball draws on into
    # the smaller client area), and after a resize the client area is snapped
    # back to the table's own proportions: Visual Pinball scales its picture
    # to the window, so any other shape stretches it. Where it is left is
    # saved as the kit's `player` (x, y of the window, w of the picture), so
    # the next table opens there. `padvpx player frame off` turns the frame
    # off again.
    #
    # PAD-845: the snap kept the WIDTH and set the height from it, so a drag
    # of the top or bottom edge (only the height changes) was put straight
    # back - "i want to be able to resize the virtual pinball display". The
    # side the user dragged now wins (keep_proportions). And a maximize box:
    # its button, or a double-click on the title bar, fills the monitor at the
    # table's proportions (a maximized window would stretch it), and doing it
    # again puts the window back, as the game's display does.
    _WS_FRAME = 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000   # caption, thickframe, min + max box

    def _frame_player(self, hwnd):
        import ctypes
        u = ctypes.windll.user32
        if not padlaunch.kit_load().get("player_frame", False):
            return False          # borderless, as the game display (PAD-845): PlayerGrips moves and resizes it
        style = u.GetWindowLongW(ctypes.c_void_p(hwnd), -16)
        if style & self._WS_FRAME != self._WS_FRAME:
            u.SetWindowLongW(ctypes.c_void_p(hwnd), -16, style | self._WS_FRAME)
            # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE
            u.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, 0x20 | 0x2 | 0x1 | 0x4 | 0x10)
            log("player window framed: drag it by its title bar, resize from its edges")
        return True

    @staticmethod
    def _client_on_screen(hwnd):
        """The picture's (x, y, w, h) on the screen."""
        import ctypes
        from ctypes import wintypes
        cw, ch = Bridge._client_size(hwnd)
        pt = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(pt))
        return pt.x, pt.y, cw, ch

    @staticmethod
    def _client_size(hwnd):
        import ctypes
        r = (ctypes.c_long * 4)()
        ctypes.windll.user32.GetClientRect(ctypes.c_void_p(hwnd), r)
        return r[2], r[3]

    def _outer_for_client(self, hwnd, cw, ch):
        """The window size that gives a cw x ch client area with its frame."""
        ww, wh = window_rect(hwnd)[2:]
        ow, oh = self._client_size(hwnd)
        return cw + (ww - ow), ch + (wh - oh)

    def _watch_player(self):
        """After the user moves or resizes the playfield window: the picture's
        proportions put back, and the place saved (once the mouse is up and
        the window has been still for half a second)."""
        hwnd = getattr(self, "player_hwnd", 0)
        aspect = getattr(self, "player_aspect", None)
        if sys.platform != "win32" or not hwnd or not aspect or not self.player_placed:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            if not u.IsWindow(ctypes.c_void_p(hwnd)) or u.IsIconic(ctypes.c_void_p(hwnd)):
                return
            if u.IsZoomed(ctypes.c_void_p(hwnd)):
                self._fill_player(hwnd)
                return
            rect = window_rect(hwnd)
            now = time.monotonic()
            if rect != getattr(self, "_player_seen", None):
                self._player_seen, self._player_seen_t = rect, now
                return
            if rect == getattr(self, "_player_settled", None) or now - self._player_seen_t < 0.5:
                return
            if u.GetAsyncKeyState(0x01) & 0x8000:            # the left button is still down
                return
            cw, ch = self._client_size(hwnd)
            tw, th = keep_proportions(getattr(self, "_player_client", None), (cw, ch), aspect)
            if cw > 0 and (abs(ch - th) > 2 or abs(cw - tw) > 2):
                ow, oh = self._outer_for_client(hwnd, tw, th)
                u.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, ow, oh, 0x2 | 0x4 | 0x10)
                log("player window kept to the table's proportions: %dx%d" % (tw, th))
                rect = window_rect(hwnd)
                self._player_seen = rect
                cw, ch = self._client_size(hwnd)
            self._player_settled, self._player_client = rect, (cw, ch)
            filled = getattr(self, "_player_filled", None)
            if filled and max(abs(a - b) for a, b in zip(rect, filled)) > 4:
                self._player_unfill = self._player_filled = None    # resized by hand since: forget it
            kit = padlaunch.kit_load()
            if (kit.get("player") or {}) != {"x": rect[0], "y": rect[1], "w": cw}:
                kit["player"] = {"x": rect[0], "y": rect[1], "w": cw}
                padlaunch.kit_save(kit)
                log("player window left at %d,%d, %d wide: saved" % (rect[0], rect[1], cw))
        except Exception as exc:                            # noqa: BLE001
            log("player window watch failed: %s" % exc)

    def _fill_player(self, hwnd):
        """Maximized (its button, or a double-click on the title bar): fill
        the monitor at the table's proportions instead - or, when it already
        fills it, go back to where it was before."""
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow(ctypes.c_void_p(hwnd), 9)               # SW_RESTORE: back to its own rectangle
        back = getattr(self, "_player_unfill", None)
        if back:
            to, self._player_unfill = back, None
            log("player window put back: %s" % (to,))
        else:
            win, client = window_rect(hwnd), self._client_size(hwnd)
            mons = monitors() or [(0, 0, 1920, 1080)]
            mx, my = win[0] + win[2] // 2, win[1] + win[3] // 2
            mon = next((m for m in mons if m[0] <= mx < m[2] and m[1] <= my < m[3]), mons[0])
            to = fill_monitor(win, (0, 0) + tuple(client), mon)
            self._player_unfill, self._player_filled = win, to
            log("player window fills its monitor: %s" % (to,))
        u.SetWindowPos(ctypes.c_void_p(hwnd), None, *to, 0x4 | 0x10)  # NOZORDER | NOACTIVATE

    def _keep_player_front(self):
        """A run this bridge started opens the game's LCD window, and that
        window takes the foreground - and Visual Pinball pauses the moment it
        loses it, so the table sat frozen until the player clicked it. While
        the run comes up, the foreground is handed back to the player from a
        window of the kit's own run (its title carries the PAD-VPX label, or
        it is the loading window) or the backglass's (_hand_back_from): never
        from anything else the user has in front.

        PAD-949: one hand-back was not enough. Windows refuses it now and
        then (1 in 3 with stand-in windows, the loading window up), and the
        LCD window or the loading window can take the foreground again while
        the run comes up - either way the table played on with the keyboard
        in the game's window until Alt+Tab (Mike's Beatles). So it
        counts only when the player really is in front after it, and the
        run's own windows are handed back from every time until
        FRONT_SETTLE_S after the game is up - in attract, not merely
        attached (PAD-963)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = getattr(self, "player_hwnd", 0) or find_player_window()
            fg = u.GetForegroundWindow()
            if not hwnd or not fg or fg == hwnd:
                return
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(fg, buf, 256)
            if not self._hand_back_from(fg, buf.value, window_pid(fg)):
                return
            ok = hand_foreground(hwnd, fg)
            self._handed_back(fg, buf.value, ok)
            if ok:
                log("foreground: [%s] -> the player again" % buf.value)
            else:
                log("foreground: [%s] kept it, Windows refused the player (try %d of %d)"
                    % (buf.value, self.front_tries.get(fg, 0), FRONT_TRIES))
        except Exception as exc:                            # noqa: BLE001
            log("foreground hand-back failed: %s" % exc)

    def _starting(self):
        """A run this bridge started that is not up yet, or only just."""
        return self.launch is not None and (
            not self.attached or not self.ready_t or time.monotonic() - self.ready_t < FRONT_SETTLE_S)

    def _hand_back_from(self, fg, title, pid=0):
        """Whether the window in front is one whose grab is undone. The
        started run's own windows (the LCD window, the loading window): every
        time while it starts (_starting) - the loading window by its process
        (Tk's windows are not all titled) - and the LCD window's first grab
        after that once. THE BACKGLASS (PAD-893): PADSPIKE2.vbs starts
        B2S.Server from LoadVPM, and its window takes the foreground as it
        opens; B2S hands it back only to a VISIBLE "Visual Pinball Player"
        window, at the moment it shows and 2 s later (formBackglass.vb
        SetFocusToVPPlayer), so a backglass that opened before the playfield
        did - later since DOF opens the cabinet first (PAD-879) - kept it,
        and Metallica sat paused. Each backglass window (the backglass, its
        DMD) is undone once, for any run: a later click on it is the user's
        own. A window Windows refused FRONT_TRIES times is left alone."""
        if self.front_tries.get(fg, 0) >= FRONT_TRIES:
            return False
        if b2s_window(title):
            return fg not in self.b2s_handed
        if self.launch is None:
            return False
        loading = getattr(self, "_loading", None)
        if self._starting() and (padlaunch.LABEL in title or (pid and loading and pid == loading.pid)):
            return True
        return not self.front_done and padlaunch.LABEL in title

    def _handed_back(self, fg, title, ok):
        """Marks a hand-back: a refused one is tried again next second, a
        done one makes a later grab of that window the user's own."""
        if not ok:
            self.front_tries[fg] = self.front_tries.get(fg, 0) + 1
            return
        self.front_tries.pop(fg, None)
        if b2s_window(title):
            self.b2s_handed.add(fg)
        elif padlaunch.LABEL in title:
            self.front_done = True       # after the start, a click on the LCD window is the user's own

    def _poll_once(self):
        if self.slots:
            return self._poll_once_s1()
        link = self.pipe if hasattr(self.pipe, "blocks") else None
        pushed = None
        if (link is not None and not getattr(self.rig, "share", True)
                and getattr(link, "state", "up") == "down"):
            self._relink(link)
            return
        if link is not None and link.alive():
            # PAD-1306: the link's copy, no 9p read - and when the link sent
            # nothing and the table no switch since the last look, nothing
            # can have moved but a coil's own off time, so the block is not
            # decoded again (that decode was most of the poll's CPU)
            now0 = time.monotonic()
            mark = (getattr(link, "frames", None), getattr(link, "sent", None))
            if (mark == self._link_mark and now0 - self._link_t < self.LINK_STALE_S
                    and not any(st.get("moving") and st["moving"] <= now0 for st in self._fake.values())
                    and not any(self._link_t < t <= now0 for t in self._coil_off_at.values())):
                self.link_idle += 1
                return
            pushed = link.blocks()
            self._link_mark, self._link_t = mark, now0
        if pushed:
            data, mrg = pushed
            self.link_polls += 1
        else:
            data = read_block(self.rig.led_path(), READ_N)
            mrg = None
        if not data or len(data) < coilmap.DRIVE_READ or not coilmap.has_magic(data):
            self.poll_fail += 1
            return
        self.polls += 1
        if not self.sw_ids and self.polls % 250 == 0:      # ~ every 2 s until the rig wrote it
            self._read_tables(data)
            if self.sw_ids:
                log("switch table arrived: %d ids" % len(self.sw_ids))
        if mrg is None:
            sw = read_block(self.rig.sw_path(), padsw.OFF_MRG + padsw.MAX_ID)
            if sw and len(sw) >= padsw.OFF_MRG + padsw.MAX_ID:
                mrg = sw[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
        now = time.monotonic()
        with self.lock:
            if mrg:
                self.mrg = mrg
            self._poll_lamps(data)
            self._poll_coils(data, now)
            for n, (node, motor) in self.map.mechs.items():
                pos = coilmap.stepper(data, node, motor)
                if pos is not None:
                    self.mech_pos[n] = pos
            if self.dof and self.dof.up:
                self._poll_dof(data)
            if self.b2s and self.b2s.up:
                self._poll_b2s(data)
                if not (self.dof and self.dof.up):
                    self._poll_b2s_dof(data)
            elif not (self.dof and self.dof.up) and self.polls == self.E_ROUTE_POLLS:
                self._tell_no_e_route()

    def _poll_once_s1(self):
        """The Spike 1 rig's block (s1bridge), or the Spooky board's in the
        same layout (spkbridge, PAD-952): every lamp's level, every coil
        on or off as the responder saw it, the switches the game is being
        told. The map's groups and RGB inserts work as on Spike 2; a lamp
        with no group is reported under its own 1000+ number."""
        rm = self.rigmod
        data = read_block(self.rig.led_path(), rm.STATE_SIZE)
        parts = rm.unpack(data)
        if not parts:
            self.poll_fail += 1
            return
        switches, lamps, coils, _ = parts
        # PAD-1305: a bridge with a rule plane (BoF) says which coils the
        # board fires itself and on which switch; without one, a held
        # flipper button is a held flipper coil
        plane = rm.rules(data) if hasattr(rm, "rules") else None
        self.polls += 1
        if not self.sw_ids and self.polls % 250 == 0:      # ~ every 2 s until the walk wrote it
            self._read_tables(data)
            if self.sw_ids:
                log("switch table arrived: %d ids" % len(self.sw_ids))
        now = time.monotonic()
        rule_coils = {}
        with self.lock:
            self.mrg = switches
            # Some ROM tables read Lamp(n) as a mechanical position or raw
            # brightness, rather than the normal 0/1 or RGB insert value.
            for n, leds in self.map.raw_lamp_rewrite.items():
                self._lamp_set(n, max(rm.lamp_level(lamps, nd, ix) for nd, ix in raw_leds(leds)))
            for n, leds in self.map.lamp_groups.items():
                levels = [rm.lamp_level(lamps, nd, ix) for nd, ix in leds]
                if max(levels) < LAMP_ON:
                    self._lamp_set(n, 0)
                elif n in self.map.rgb_groups:
                    self._lamp_set(n, rgb_value(*(rgb_levels(levels, getattr(self.map, "rgb_order", {}).get(n)) if len(leds) == 3
                                                  else rm.lamp_rgb(lamps, *leds[0]))))
                else:
                    self._lamp_set(n, 1)
            for node in range(rm.MAX_NODES if self.map.led_lamps else 0):
                for idx in range(rm.MAX_INDEX):
                    n = lamp_number(node, idx)
                    if n in self.map.lamp_groups:
                        continue
                    self._lamp_set(n, 1 if rm.lamp_level(lamps, node, idx) >= LAMP_ON else 0)
            for node in range(rm.MAX_NODES):
                for idx in range(rm.MAX_INDEX):
                    key = (node, idx)
                    on = 1 if coils[rm.slot(node, idx)] else 0
                    if plane is not None:
                        sid = plane.get(rm.slot(node, idx))
                        if sid:
                            # armed: the coil follows its switch from the
                            # table's own edge (set_switch), let go with it
                            rule_coils.setdefault(sid, []).append((key, True))
                            if self.pipe.held.get(sid) if self.pipe else 0:
                                on = 1
                        self._coil_set(key, on)
                        continue
                    # a flipper button held in this bridge is a held coil
                    # (no rule plane here: the board's reflex is assumed live)
                    bit = self._button_coils.get(key)
                    if bit is not None:
                        sid = self.sw_ids.get((node, bit))
                        if sid:
                            # the board's own coil state says when it lets
                            # go, so set_switch only turns it on
                            rule_coils.setdefault(sid, []).append((key, False))
                        if sid and (self.pipe.held.get(sid) if self.pipe else 0):
                            on = 1
                    self._coil_set(key, on)
            self._rule_coils = rule_coils
            if self.map.game_on:
                num, gcoils = self.map.game_on
                if plane is None:
                    self._sol_set(num, 1)
                else:
                    self._sol_set(num, 1 if any(rm.slot(nd, ix) in plane
                                                for nd, ix in gcoils) else 0)
            self._fakes_tick(now)
            if self.dof and self.dof.up:
                self._poll_dof_s1(lamps, rm)

    def _poll_dof_s1(self, lamps, rm):
        m = self.map
        for n, key in m.dof_sols.items():
            self._dof_set("S", n, 1 if self.sol_state.get(self._sol_number(*key)) else 0)
        for n, leds in m.dof_lamps.items():
            level = max(rm.lamp_level(lamps, nd, ix) for nd, ix in leds)
            self._dof_set("L", n, 1 if level >= LAMP_ON else 0)
        for n, leds in m.dof_flashers.items():
            level = max(rm.lamp_level(lamps, nd, ix) for nd, ix in leds)
            self._dof_set("S", n, level if level >= LAMP_ON else 0)

    @staticmethod
    def _led_level(data, node, idx):
        """One LED's level: val[] for channels 0..95, the hi plane past that
        (coilmap.hi_level is the same arithmetic; inlined for the poll)."""
        if idx < 96:
            return data[20 + node * 96 + idx]
        if idx < 96 + coilmap.HI_IDX and len(data) >= coilmap.HI_READ:
            return data[coilmap.HI_OFF + node * coilmap.HI_IDX + idx - 96]
        return 0

    def _poll_lamps(self, data):
        # raw channels (a mechanism's position, a mono level), then the
        # mapped groups, then every LED any table might name directly
        for n, leds in self.map.raw_lamp_rewrite.items():
            self._lamp_set(n, max(self._led_level(data, nd, ix) for nd, ix in raw_leds(leds)))
        for n, leds in self.map.lamp_groups.items():
            levels = [self._led_level(data, nd, ix) for nd, ix in leds]
            if max(levels) < LAMP_ON:
                self._lamp_set(n, 0)
            elif n in self.map.rgb_groups:
                self._lamp_set(n, rgb_value(*rgb_levels(levels, getattr(self.map, "rgb_order", {}).get(n))))
            else:
                self._lamp_set(n, 1)
        for node in range(16 if self.map.led_lamps else 0):
            base = 20 + node * 96
            for idx in range(96):
                n = lamp_number(node, idx)
                if n in self.map.lamp_groups:
                    continue
                self._lamp_set(n, 1 if data[base + idx] >= LAMP_ON else 0)

    def _lamp_set(self, n, on):
        if self.lamp_state.get(n) != on:
            self.lamp_state[n] = on
            self.lamp_pending.add(n)

    def _poll_coils(self, data, now):
        fires = struct.unpack_from("<I", data, coilmap.DRIVE_FIRES_OFF)[0]
        rule_coils = {}
        for node in range(16):
            for idx in range(16):
                key = (node, idx)
                count = data[coilmap.COIL_OFF + node * 16 + idx]
                d = coilmap.drive(data, node, idx)
                until = d["until"] if d else 0
                seen = self._coil_seen.get(key)
                on = self.sol_state.get(self._sol_num(key), 0)
                if seen is None:
                    self._coil_seen[key] = (count, until)
                    continue
                if count != seen[0] or (until and until != seen[1]):
                    # a fire landed: on for the command's pulse + hold
                    length = (d["pulse_ms"] + d["hold_ms"]) if d else 0
                    self._coil_off_at[key] = now + max(length, MIN_PULSE_MS) / 1000.0
                    on = 1
                elif until == 0 and seen[1] != 0:
                    on = 0                           # an OFF (cmd 4d) landed
                elif on and now >= self._coil_off_at.get(key, 0):
                    on = 0
                self._coil_seen[key] = (count, until)
                # A BOARD-FIRED COIL (padled v7): the game installed a rule
                # naming the input that fires it, and the board does the rest
                # - flippers, slingshots, pop bumpers. Nothing crosses the bus
                # per flip, so the coil is ON exactly while that switch is made
                # and the rule is live; the switch is one this bridge wrote.
                r = coilmap.rule(data, node, idx)
                if r is None and key in self._button_coils:
                    # A run on a shim without the rule plane (padled < 7, the
                    # app's bundled rig until PAD-775 ships): the flippers are
                    # assumed live, so a held button is a held coil.
                    r = {"power": 1, "input": self._button_coils[key]}
                if r and r["power"] and r["input"] is not None:
                    sid = self.sw_ids.get((node, r["input"]))
                    if sid:
                        rule_coils.setdefault(sid, []).append((key, True))
                        made = (self.pipe.held.get(sid) if self.pipe and sid in self.pipe.held
                                else (self.mrg[sid] if sid < len(self.mrg) else 0))
                        if made:
                            on = 1
                        elif self._coil_off_at.get(key, 0) <= now:
                            on = 0
                self._coil_set(key, on)
        self._rule_coils = rule_coils
        if self.map.game_on:
            num, coils = self.map.game_on
            armed = 0
            for node, idx in coils:
                r = coilmap.rule(data, node, idx)
                if r is None or r["power"]:        # no rule plane = assume live
                    armed = 1
            self._sol_set(num, armed)
        self._fakes_tick(now)
        self._fires = fires

    def _sol_nums(self, key):
        """Every number a coil is reported under: its 1000+ number and any
        the map gives it (core.vbs's flipper Consts, a table's own number)."""
        node, idx = key
        nums = [self._sol_number(node, idx)]
        for n, coil in self.map.solenoids.items():
            if coil == key and n not in nums:
                nums.append(n)
        return nums

    def _sol_num(self, key):
        return self._sol_nums(key)[0]

    def _sol_set(self, n, on):
        if self.sol_state.get(n) != on:
            self.sol_state[n] = on
            self.sol_pending.add(n)
            if on:
                self.sol_unread_on.add(n)
            if n <= self.map.sol_max:
                log("sol %d -> %d" % (n, on))

    def _coil_set(self, key, on):
        for n in self._sol_nums(key):
            self._sol_set(n, on)

    def _fakes_tick(self, now):
        """A motor the table has no object for: when its coil fires, the end
        stop it leaves opens at once and the other closes `travel_ms` later
        (the same answer hwshim gives a node-board motor, PAD-237)."""
        for name, f in self.map.fakes.items():
            if f.get("kind") == "latch":
                self._latch_tick(name, f)
                continue
            st = self._fake.setdefault(name, {"open": 0})
            n = self._sol_num(tuple(f["coil"]))
            if self.sol_state.get(n) and not st.get("moving"):
                st["moving"] = now + f.get("travel_ms", 400) / 1000.0
                self.pipe.set(f["open" if st["open"] else "closed"], 0)
            if st.get("moving") and now >= st["moving"]:
                st["moving"] = None
                st["open"] = 0 if st["open"] else 1
                self.pipe.set(f["open" if st["open"] else "closed"], 1)

    def _latch_tick(self, name, f):
        """A latched post the table has no switch for (PAD-968, Foo Fighters'
        Overlord fork): its `up` coil pops it up (it catches the ball), its
        `down` coil pulls it down onto the latch (the ball goes). The game
        fires both at once to catch - an opto rule, which this bridge sees
        as both coils on while the opto is made - and lets go by clearing
        the up coil's rule while it fires the down coil, so: up coil on =
        up; down coil on, up coil not = down; up coil off while the down
        coil is on = down. The post's state is the map's `switch` (closed =
        up), and the table hears it as the synthetic `solenoid`."""
        st = self._fake.setdefault(name, {"up": 0, "was": (0, 0)})
        up_on = bool(self.sol_state.get(self._sol_num(tuple(f["up"]))))
        down_on = bool(self.sol_state.get(self._sol_num(tuple(f["down"]))))
        was_up, was_down = st["was"]
        state = st["up"]
        if up_on and not was_up:
            state = 1
        elif down_on and not up_on and (not was_down or was_up):
            state = 0
        st["was"] = (up_on, down_on)
        if state != st["up"]:
            st["up"] = state
            self.pipe.set(f["switch"], state)
            self._sol_set(int(f["solenoid"]), state)

    # -- what core.vbs asks
    def changed_lamps(self):
        with self.lock:
            if not self.lamp_pending:
                return None
            out = [[n, self.lamp_state[n]] for n in sorted(self.lamp_pending)]
            self.lamp_pending.clear()
        return out

    def changed_solenoids(self):
        """Every coil that changed since the table last asked. A pulse that
        came and went between two reads (Visual Pinball reads once a frame; a
        lock's kick can be 20 ms, PAD-1116) is reported ON now and OFF on the
        next read, so the table's SolCallback still sees it fire."""
        with self.lock:
            if not self.sol_pending:
                return None
            out = []
            again = set()
            for n in sorted(self.sol_pending):
                if n > self.map.sol_max:
                    continue
                on = self.sol_state[n]
                if not on and n in self.sol_unread_on:
                    on = 1
                    again.add(n)
                out.append([n, on])
            self.sol_pending.clear()
            self.sol_pending.update(again)
            self.sol_unread_on.clear()
        return out or None

    def lamp(self, n):
        n = int(n or 0)
        with self.lock:
            if n in self.map.raw_lamp_rewrite:     # the level itself, 0..255
                return int(self.lamp_state.get(n, 0))
            return bool(self.lamp_state.get(n, 0))

    def solenoid(self, n):
        with self.lock:
            return bool(self.sol_state.get(int(n or 0), 0))

    def get_mech(self, n):
        """Controller.GetMech(n): the place of the stepper the map's `mechs`
        names for n, in steps from home; 0 until the game first homes or moves
        it, and for a number the map does not name (VPinMAME's answer for a
        mech a ROM lacks)."""
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            return 0
        with self.lock:
            return int(self.mech_pos.get(n, 0))

    def status(self):
        return {"title": self.title, "running": self.running, "polls": self.polls,
                "poll_fail": self.poll_fail, "last_poll_ms": round(self.last_poll_ms, 2),
                "rig": self.rig.how if self.rig else None,
                "attached": self.attached,
                "started": self.launch.slot if self.launch else None,
                "held": dict(self.pipe.held) if self.pipe else {},
                "link": (self.pipe.status() if isinstance(self.pipe, RigLink) else None),
                "lamps_on": sum(1 for v in self.lamp_state.values() if v),
                "dof": (("up, %d sent" % self.dof.sent) if self.dof.up else self.dof.why)
                if self.dof else "not asked",
                "sols_on": [n for n, v in self.sol_state.items() if v]}


# ---------------------------------------------------------------- COM ------

def _no_result(wFlags, value):
    """What a call hands back to VBScript. VBScript passes a VARIABLE argument
    by reference, and when the caller takes no result (a statement call,
    `Controller.PadB2S PadB2S`, or a put) pywin32 writes the return value
    into the first such variable. PAD-1496: PadB2S, the table's B2S.Server,
    became True, so every DOF call of an original table went to
    PAD.Controller and was dropped; PADSPIKE2.vbs's `Controller.PadDOF "E",
    DOFevent, 1` left DOFevent Null, so a DOF pulse's "off" went to E0 and
    the toy stayed on; a put's None once took `Controller.Switch(sw)`'s sw.
    VBScript asks with DISPATCH_PROPERTYGET set whenever it uses the result
    (`x = Controller.m(v)`, `If Controller.m(v)`); without it, an empty
    tuple is pywin32's "no byrefs to write" and every variable stays as it was."""
    return value if wFlags & DISPATCH_PROPERTYGET else ()


class _Anything:
    """Controller.Games(name).Settings.Value("volume") and friends: a thing
    that accepts any property and answers 0."""

    _public_methods_ = []
    _reg_policy_spec_ = "DynamicPolicy"

    def _dynamic_(self, name, lcid, wFlags, args):
        if wFlags & DISPATCH_PROPERTYPUT:
            return ()                       # no write-back (_no_result)
        if name.lower() in ("settings", "games"):
            return _no_result(wFlags, _anything())
        return _no_result(wFlags, 0)


class PadController:
    _reg_clsid_ = CLSID
    _reg_progid_ = PROGID
    _reg_desc_ = "PAD Spike 2 emulator controller for Visual Pinball"
    _reg_policy_spec_ = "DynamicPolicy"
    # no _reg_class_spec_: with it set, pywin32 writes no PythonCOMPath and
    # the COM-launched pythonw.exe cannot import this module ("Unspecified
    # error" at CreateObject); without it, it derives both from this file.
    _public_methods_ = []
    if pythoncom:
        _reg_clsctx_ = pythoncom.CLSCTX_LOCAL_SERVER

    def __init__(self):
        self.bridge = Bridge()
        self.props = {}
        atexit.register(self.bridge.dof_finish)    # DOF turns the toys off as it goes
        atexit.register(self.bridge.b2s_finish)
        log("PAD.Controller created")

    def __del__(self):
        """Visual Pinball let go of the controller (the table closed). PAD-1496:
        a table that handed B2S.Server over and closed without PadB2SFinish
        (an exit sub that never ran, a TMNT copy patched with none) kept this
        process up for good - the B2S thread's reference to B2S.Server is a
        live COM object, and pywin32's server quits only once none is left -
        and with it any DOF it hosted, holding the cabinet's devices at the
        game's last colours so the next table's DOF could not open them. So
        the last release ends the run, B2S.Server's thread and DOF itself."""
        b = getattr(self, "bridge", None)
        if b is None:
            return
        try:
            if b.running:
                log("released without Stop: stopping the run")
                b.stop()
            if b.b2s or b.dof:
                log("released: B2S.Server and DOF let go")
            b.b2s_finish()
            b.dof_finish()
        except Exception as exc:                            # noqa: BLE001
            log("release: %s" % exc)

    TRACE = os.path.exists(os.path.join(os.path.dirname(LOG), "padvpx_trace"))

    def _dynamic_(self, name, lcid, wFlags, args):
        b = self.bridge
        key = name.lower()
        if self.TRACE and key not in ("changedlamps", "changedsolenoids", "lamp", "solenoid"):
            log("call %s flags=%d args=%r" % (name, wFlags, tuple(args)))
        try:
            if wFlags & DISPATCH_PROPERTYPUT:
                self._put(key, args)
                return ()                   # no write-back (_no_result)
            return _no_result(wFlags, self._get(key, args))
        except Exception as exc:                            # noqa: BLE001
            # One line for the table's MsgBox ("Can't start Game ... " &
            # Err.Description); the traceback stays in the log. A bare Python
            # exception reaches VBScript as the whole traceback in a dialog.
            log("%s%r failed: %s" % (name, tuple(args), exc))
            if pythoncom:
                raise COMException(desc="PAD.Controller: %s" % exc,
                                   scode=winerror.E_FAIL)
            raise

    def _put(self, key, args):
        b = self.bridge
        if key == "switch":
            b.set_switch(args[0], args[1])
        elif key == "gamename":
            b.set_game(str(args[0]))
        elif key == "pause":
            b.set_pause(args[0])
        elif key == "padsolenoid":
            b.own_solenoid(args[0], args[-1])
        elif key == "lamp" or key == "solenoid" or key == "solmask":
            pass
        elif key == "padnote":
            # PAD-1251: a table's own call that failed where the patch runs
            # it under On Error Resume Next (Batman 66's PadMechTimer turning
            # the tribute's turntable and crane), said in the log. The table
            # sends each distinct error once; the cap stops a runaway.
            n = self.props.get("_padnotes", 0)
            if n < 50:
                self.props["_padnotes"] = n + 1
                log("table: %s" % args[-1])
        else:
            self.props[key] = args[-1]
        return None

    def _get(self, key, args):
        b = self.bridge
        # "nothing changed" is VBScript's Empty (IsEmpty), which pywin32 maps
        # from pythoncom.Empty; a bare None would arrive as Null and fail
        # core.vbs's IsEmpty() test.
        empty = pythoncom.Empty if pythoncom else None
        if key == "switch":
            return b.get_switch(args[0])
        if key == "changedlamps":
            chg = b.changed_lamps()
            return empty if chg is None else chg
        if key == "changedsolenoids":
            chg = b.changed_solenoids()
            return empty if chg is None else chg
        if key in ("changedgistrings", "changedleds", "changedpdleds", "changednvram",
                   "rawdmdpixels", "rawdmdcoloredpixels", "nvram"):
            return empty
        if key == "lamp":
            return b.lamp(args[0])
        if key == "solenoid":
            return b.solenoid(args[0])
        if key == "run":
            # Controller.Run GetPlayerHWnd: the player window, so a run this
            # bridge starts can hand the foreground back to it
            try:
                b.player_hwnd = int(args[0]) if args and args[0] is not None else 0
            except (TypeError, ValueError):
                b.player_hwnd = 0
            b.run()
            return None
        if key == "stop":
            b.stop()
            return None
        if key == "pause":
            return b.paused
        if key == "running":
            return b.running
        if key == "version":
            return VERSION
        if key == "gamename":
            return b.title
        if key in ("romname",):
            return b.title
        if key in ("games", "settings"):
            return _anything()
        if key == "getmech":
            return b.get_mech(args[0] if args else 0)
        if key in ("mech", "dip", "solmask", "rawdmdwidth", "rawdmdheight",
                   "timefence"):
            return 0
        if key == "padstatus":
            return json.dumps(b.status())
        # DOF (PAD-879): PADSPIKE2.vbs starts it before B2S.Server, sends the
        # script's own DOF calls through it, and finishes it with the table
        if key == "paddofinit":
            return b.dof_init(str(args[0] or ""), str(args[1] or "") if len(args) > 1 else "")
        if key == "paddof":
            b.dof_send(str(args[0] or "E")[:1], int(args[1] or 0), int(args[2] or 0))
            return None
        if key == "paddoffinish":
            b.dof_finish()
            return None
        # the backglass's bulbs (PAD-1304): PADSPIKE2.vbs hands B2S.Server over
        # once it runs, and takes it back before it stops it
        if key == "padb2s":
            return b.b2s_attach(args[0]) if args and args[0] is not None else False
        if key == "padb2sfinish":
            b.b2s_finish()
            return None
        return self.props.get(key, 0)


# ---------------------------------------------------------------- CLI ------

def status():
    rig = Rig()
    print("rig: %s -> %s" % (rig.how, rig.dump))
    data = read_block(rig.led_path(), coilmap.HI_READ)
    print("padled:", "up (version %d)" % struct.unpack_from("<I", data, 4)[0]
          if data and coilmap.has_magic(data) else "no run")
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".vpxmap.json"):
            m = VpxMap(f[:-len(".vpxmap.json")])
            print("map %s: %d switch rewrites, %d solenoids, %d lamp groups, fakes %s"
                  % (m.title, len(m.switch_rewrite), len(m.solenoids),
                     len(m.lamp_groups), sorted(m.fakes)))
    print("log:", LOG)


def selftest():
    import win32com.client
    c = win32com.client.Dispatch(PROGID)
    c.GameName = "godzilla_le"
    print("Version", c.Version, "GameName", c.GameName)
    c.Run(0)
    time.sleep(0.5)
    print("status", c.PadStatus)
    c.Switch(1060, 1)              # left flipper button
    time.sleep(0.3)
    c.Switch(1060, 0)
    chg = c.ChangedSolenoids
    print("ChangedSolenoids", chg if chg is None else [list(r) for r in chg][:8])
    chg = c.ChangedLamps
    print("ChangedLamps", "none" if chg is None else "%d entries" % len(chg))
    print("status", c.PadStatus)
    c.Stop()


def quote_local_server():
    """Put the server's program in quotes (PAD-1229): pywin32 writes it as
    its 8.3 short name with none, and with short names off on the drive that
    is the long path with spaces, which Windows has to guess the end of."""
    import winreg
    import vpxsetup
    key = "CLSID\\%s\\LocalServer32" % CLSID
    try:
        cmd = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, key)
    except OSError:
        return
    fixed = vpxsetup.quoted_server_cmd(cmd)
    if fixed:
        winreg.SetValue(winreg.HKEY_CLASSES_ROOT, key, winreg.REG_SZ, fixed)
        print("LocalServer32 quoted: %s" % fixed)


def main(argv):
    if "--status" in argv:
        status()
        return 0
    if "--selftest" in argv:
        selftest()
        return 0
    if "--register" in argv or "--unregister" in argv:
        # UseCommandLine reads --register / --unregister off sys.argv itself;
        # addnPath lands in the registry as PythonCOMPath, which is how the
        # COM-launched pythonw.exe finds this module.
        # PAD-1229: so it is handed THIS argv, not the caller's: `padvpx.py
        # unregister` (the uninstaller's) has "unregister" with no dashes on
        # sys.argv, and pywin32 registered again instead of removing it.
        # --unattended: an access-denied raises here rather than pywin32
        # opening a second elevation of its own the caller cannot see.
        saved = sys.argv
        sys.argv = [saved[0] if saved else "padcontroller.py"] + list(argv) + ["--unattended"]
        try:
            _reg.UseCommandLine(PadController, addnPath=HERE)
        finally:
            sys.argv = saved
        if "--register" in argv:
            quote_local_server()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
