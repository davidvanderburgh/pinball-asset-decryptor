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

The LCD is the game's own window: nothing to bridge. Sound is the rig's.

NUMBERING, shared with PADSPIKE2.vbs and the .vpxmap.json files:

    switch   1000 + <Spike 2 switch id>          switch_list.txt `id`
    solenoid 1000 + <node> * 16 + <coil index>   device_xy coil (group->node)
    lamp     1000 + <node> * 100 + <LED index>   led_io.txt

A number below 1000 is a table's ORIGINAL number and goes through the map
(`switch_rewrite`, `solenoids`, `lamps`), so a table can be driven with its
script left on its old numbering while the map is being built.

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
import json
import os
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
import padlaunch  # noqa: E402  starts a run for a table when none is up

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
READ_N = max(coilmap.HI_READ, coilmap.RULE_READ)   # one read takes every plane
LAMP_ON = int(os.environ.get("PAD_VPX_LAMP_ON", "1"))   # LED level that is "lit"
MIN_PULSE_MS = 40               # a coil pulse shorter than a poll still shows
FRONT_WATCH_S = 300             # how long after Run a started run's windows are watched
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPATCH_PROPERTYPUT = 1, 2, 4

LOG = os.path.join(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp",
                   "padcontroller.log")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


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


def window_rect(hwnd):
    import ctypes
    r = (ctypes.c_long * 4)()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), r)
    return r[0], r[1], r[2] - r[0], r[3] - r[1]


class VpxMap:
    """A title's .vpxmap.json, reduced to the three lookups the server makes."""

    def __init__(self, title=None):
        self.title = title
        self.switch_rewrite = {}            # old table number -> Spike 2 id
        self.solenoids = {}                 # number -> (node, index)
        self.lamp_groups = {}               # number -> [(node, index), ...]
        self.fakes = {}                     # name -> dict (switch_fakes)
        self.game_on = None                 # (number, [coils]) "flippers armed"
        self.cabinet = {}                   # cabinet switch names -> 1000+id
        # core.vbs indexes SolCallback(68) and friends by the number it is
        # handed, so ChangedSolenoids may only carry numbers up to this; a
        # coil's 1000+ name still answers Controller.Solenoid(n).
        self.sol_max = 68
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
        g = m.get("game_on") or {}
        self.game_on = (int(g["number"]), [tuple(c) for c in g["coils"]]) if g else None
        self.cabinet = {k: int(v) for k, v in m.get("cabinet", {}).items()
                        if k != "_" and isinstance(v, int)}
        for k, v in m.get("switch_rewrite", {}).items():
            if k != "_":
                self.switch_rewrite[int(k)] = int(v)
        self.sol_max = int(m.get("solenoid_max", 68))
        for k, v in m.get("solenoids", {}).items():
            if k != "_":
                self.solenoids[int(k)] = tuple(v["coil"])
        for sect in ("lamps", m.get("retrofit_lights", {}).get("lights", {})):
            table = m.get(sect, {}) if isinstance(sect, str) else sect
            for name, v in table.items():
                if name == "_" or not isinstance(v, dict):
                    continue
                leds = [tuple(x) for x in v["leds"]]
                self.lamp_groups[lamp_number(*leds[0])] = leds
        self.fakes = {k: v for k, v in m.get("switch_fakes", {}).items() if k != "_"}

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
         run): the run whose `game` is the title the table named, else the
         only Spike 2 run up. This is how a Visual Pinball started from the
         Start menu, with no PAD environment at all, finds the app's run;
      3. padpath's default: the default distro's ~/spike2root.
    """

    def __init__(self, title=None, record=None):
        self.distro = os.environ.get("PAD_WSL_DISTRO")
        self.root = os.environ.get("PAD_ROOT_WSL")        # posix
        self.slot = padpath.slot()
        self.how = "environment"
        if record or not self.root:
            rec = record or self.board_run(title)
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
    def board_slot(slot):
        """The board's record for one slot, or None until watch.sh writes it."""
        try:
            rec = json.load(open(os.path.join(BOARD, "slot-%d.run" % int(slot)), encoding="utf-8"))
            return rec if isinstance(rec, dict) and rec.get("root") else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def board_run(title):
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
        return runs[0] if len(runs) == 1 else None

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

    def switch_ids(self, title):
        """{(node, bit): id} from the title's switch_list.txt, the rig's own
        reading of the game's switch table (empty when the run has none)."""
        out = {}
        path = os.path.join(self.dump, "tables", title or "", "switch_list.txt")
        if title and not os.path.exists(path):
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


def read_block(path, n):
    """One fresh read of `n` bytes, or None (no run, or a 9p hiccup)."""
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return None


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
                       + ["python3", "%s/swkeys.py" % padpath.to_wsl(RIG)])
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


# ---------------------------------------------------------------- the bridge

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
        self._coil_seen = {}               # (node, idx) -> (fires, until)
        self._coil_off_at = {}             # (node, idx) -> monotonic s
        self.sw_ids = {}                   # (node, input bit) -> switch id
        self._button_coils = {}            # (node, idx) -> button input bit
        self.mrg = bytes(padsw.MAX_ID)     # the guest's merged switch truth
        self.polls = 0
        self.poll_fail = 0
        self.last_poll_ms = 0.0
        self._fake = {}                    # name -> state for switch_fakes

    # -- lifecycle
    def set_game(self, title):
        self.title = title
        self.map = VpxMap(title)
        log("game %s: map %s: switches=%d solenoids=%d lamp groups=%d"
            % (title, self.map.path or "NONE", len(self.map.switch_rewrite),
               len(self.map.solenoids), len(self.map.lamp_groups)))

    def run(self):
        """Attach to the title's run, or START one (padlaunch) when none is
        up and a card for the title is known: Run returns at once, the poll
        thread attaches when the game is up, and the table plays from then
        on - switches before that are dropped, Visual Pinball never waits."""
        self.rig = Rig(self.title)
        self.pipe = None
        self.launch = None
        self.attached = False
        self.start_t = time.monotonic()
        self.front_done = False            # the LCD window's first grab is undone once, never again
        self.lcd_placed = False
        self.lcd_tries = 0
        self.lcd_stable = 0
        self.player_placed = False
        log("rig: %s -> %s" % (self.rig.how, self.rig.dump))
        data = read_block(self.rig.led_path(), READ_N)
        if data and coilmap.has_magic(data):
            self._attach(data)
        else:
            card = padlaunch.card_for(self.title)
            if not card:
                raise RuntimeError(
                    "no Spike 2 run is up for %s and no card image to start one "
                    "(looked in %s). Start the game first (the app's Emulate tab, "
                    "or watch.sh), or record its card: padvpx card %s <image>."
                    % (self.title or "this title", padlaunch.card_places(self.title),
                       self.title))
            self.launch = padlaunch.Launch(self.title, card)
            slot = self.launch.start()
            self.rig = None
            log("starting %s on slot %d; the table plays once the game is up" % (self.title, slot))
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log("run")

    def _attach(self, data):
        """The run is up: read its tables, open the switch pipe, own the balls."""
        self.pipe = SwitchPipe(self.rig)
        self._read_tables(data)
        for name, f in self.map.fakes.items():
            self._fake[name] = {"open": 0}
            self.pipe.set(f["closed"], 1)
            self.pipe.set(f["open"], 0)
        try:
            open(self.rig.ballfeed_off_path(), "w").write("PAD.Controller\n")
        except OSError as exc:
            log("ballfeed.off not written: %s" % exc)
        self.attached = True
        log("attached to %s after %.0f s" % (self.rig.how, time.monotonic() - self.start_t))

    def _read_tables(self, data):
        """The run's switch table (the rig writes it a little after the game
        is up, so a run this bridge started may be read again) and the
        flipper buttons' coils for a run without the rule plane."""
        self.sw_ids = self.rig.switch_ids(self.title)
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

    #: how long a run started for a table may take to come up (a card copied
    #: into the cache first, then the boot)
    START_TIMEOUT_S = 420

    def _poll_starting(self):
        """Once a second until the run this bridge started is up."""
        if self.launch is None:
            return
        if self.rig is None:
            rec = Rig.board_slot(self.launch.slot)
            if rec:
                self.rig = Rig(self.title, record=rec)
                log("rig: %s -> %s" % (self.rig.how, self.rig.dump))
        if self.rig is not None:
            data = read_block(self.rig.led_path(), READ_N)
            if data and coilmap.has_magic(data):
                self._attach(data)
                return
        if not self.launch.alive() and self.rig is None:
            log("the run started for %s ended before it came up (see %s)"
                % (self.title, self.launch.logfile))
            self.launch = None
        elif time.monotonic() - self.start_t > self.START_TIMEOUT_S:
            log("the run started for %s is not up after %d s; giving up on it"
                % (self.title, self.START_TIMEOUT_S))
            self.launch.stop()
            self.launch = None

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self.pipe:
            self.pipe.close()
        if self.rig:
            try:
                os.remove(self.rig.ballfeed_off_path())
            except OSError:
                pass
        log("stop after %d polls (%d failed)" % (self.polls, self.poll_fail))
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
        if want and kit_window_in_front():
            # the player clicked the game's own LCD or playfield window (to
            # move it, to look at it): Visual Pinball pauses, the GAME does
            # not - freezing it here left the screen dead under the mouse
            log("pause from the kit's own window in front: the game runs on")
            return

        def rig_flag():
            sw = read_block(self.rig.sw_path(), padsw.OFF_PAUSED + 4)
            return struct.unpack_from("<I", sw, padsw.OFF_PAUSED)[0] if sw and len(sw) > padsw.OFF_PAUSED else -1

        now = rig_flag()
        if now != want:
            self.pipe.pause()
            # VPX flips Pause twice within a few ms as its player starts; the
            # rig takes ~10 ms to act on a toggle, so wait for the flag to
            # follow before the next call reads it - or the second call sees
            # the old value, sends nothing, and the game stays frozen.
            for _ in range(30):
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

    # -- switches
    def set_switch(self, n, level):
        sid = self.map.switch_id(n)
        if 0 < sid < padsw.MAX_ID and self.pipe:
            if self.pipe.held.get(sid) != (1 if level else 0):
                log("sw %s -> id %d = %d" % (n, sid, 1 if level else 0))
            self.pipe.set(sid, level)

    def get_switch(self, n):
        sid = self.map.switch_id(n)
        if sid <= 0:
            return False
        if self.pipe and sid in self.pipe.held:
            return bool(self.pipe.held[sid])
        return bool(self.mrg[sid]) if sid < len(self.mrg) else False

    # -- the poll
    def _poll_loop(self):
        last_front = 0.0
        while self.running:
            now = time.monotonic()
            if (self.launch is not None and not (self.front_done and self.lcd_placed)
                    and now - last_front >= 1.0 and now - self.start_t < FRONT_WATCH_S):
                last_front = now
                if not self.lcd_placed:
                    self._place_lcd()
                if not self.front_done:
                    self._keep_player_front()
            if not self.player_placed and now - self.start_t < FRONT_WATCH_S:
                self._place_player()
            if not self.attached:
                self._poll_starting()
                time.sleep(1.0)
                continue
            t0 = time.monotonic()
            self._poll_once()
            if now - getattr(self, "_front_check", 0.0) >= 0.25:
                self._front_check = now
                self._watch_focus()
            self.last_poll_ms = (time.monotonic() - t0) * 1000.0
            time.sleep(POLL_S)

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
                        raise_window(hwnd, bool((setting or {}).get("topmost", True)))
                        self.placed_at[key] = time.monotonic()
                        log("lcd window left to the display setting (%s), on top"
                            % shown.get("mode"))
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

    def _place_player(self):
        """Visual Pinball's own playfield window, where the kit's `player`
        says (padvpx player): borderless in windowed mode, so the user
        cannot drag it, and 10.8 ignores WindowPosX/Y in its ini. Moved
        once per Run, for any run (not only one this bridge started); its
        size stays Visual Pinball's own unless the kit gives one."""
        hwnd = getattr(self, "player_hwnd", 0)
        setting = padlaunch.kit_load().get("player")
        if sys.platform != "win32" or not setting:
            self.player_placed = True
            return
        if not hwnd:
            return
        try:
            dpi_aware()
            cur = window_rect(hwnd)
            if "monitor" in setting:
                x, y, w, h = lcd_rect(setting, monitors())
            else:
                x, y = int(setting["x"]), int(setting["y"])
                w, h = int(setting.get("w", cur[2])), int(setting.get("h", cur[3]))
            place_window(hwnd, (x, y, w, h), False)
            self.player_placed = True
            log("player window placed at %s (was %s)" % ((x, y, w, h), cur))
        except Exception as exc:                            # noqa: BLE001
            log("player window not placed: %s" % exc)
            self.player_placed = True

    def _keep_player_front(self):
        """A run this bridge started opens the game's LCD window, and that
        window takes the foreground - and Visual Pinball pauses the moment it
        loses it, so the table sat frozen until the player clicked it. While
        the run comes up, the foreground is handed back to the player ONCE (a
        click on the LCD window after that is the user wanting to see it), and
        ONLY from a window of the kit's own run (its title carries the
        PAD-VPX label): never from anything else the user has in front."""
        hwnd = getattr(self, "player_hwnd", 0)
        if not hwnd or sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            fg = u.GetForegroundWindow()
            if not fg or fg == hwnd:
                return
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(fg, buf, 256)
            if padlaunch.LABEL not in buf.value:
                return
            k = ctypes.windll.kernel32
            fg_tid = u.GetWindowThreadProcessId(fg, None)
            me = k.GetCurrentThreadId()
            u.AttachThreadInput(me, fg_tid, True)
            try:
                u.ShowWindow(hwnd, 9)            # SW_RESTORE, if it was minimised
                u.SetForegroundWindow(hwnd)
                u.BringWindowToTop(hwnd)
            finally:
                u.AttachThreadInput(me, fg_tid, False)
            self.front_done = True       # ONCE: a later click on the LCD window is the user's own
            log("foreground: [%s] -> the player again (once; the window is the user's from here)" % buf.value)
        except Exception as exc:                            # noqa: BLE001
            log("foreground hand-back failed: %s" % exc)

    def _poll_once(self):
        data = read_block(self.rig.led_path(), READ_N)
        if not data or len(data) < coilmap.DRIVE_READ or not coilmap.has_magic(data):
            self.poll_fail += 1
            return
        self.polls += 1
        if not self.sw_ids and self.polls % 250 == 0:      # ~ every 2 s until the rig wrote it
            self._read_tables(data)
            if self.sw_ids:
                log("switch table arrived: %d ids" % len(self.sw_ids))
        sw = read_block(self.rig.sw_path(), padsw.OFF_MRG + padsw.MAX_ID)
        now = time.monotonic()
        with self.lock:
            if sw and len(sw) >= padsw.OFF_MRG + padsw.MAX_ID:
                self.mrg = sw[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
            self._poll_lamps(data)
            self._poll_coils(data, now)

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
        # mapped groups first, then every LED any table might name directly
        for n, leds in self.map.lamp_groups.items():
            level = max(self._led_level(data, nd, ix) for nd, ix in leds)
            self._lamp_set(n, 1 if level >= LAMP_ON else 0)
        for node in range(16):
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
                        made = (self.pipe.held.get(sid) if self.pipe and sid in self.pipe.held
                                else (self.mrg[sid] if sid < len(self.mrg) else 0))
                        if made:
                            on = 1
                        elif self._coil_off_at.get(key, 0) <= now:
                            on = 0
                self._coil_set(key, on)
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
        nums = [sol_number(node, idx)]
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
            st = self._fake.setdefault(name, {"open": 0})
            n = self._sol_num(tuple(f["coil"]))
            if self.sol_state.get(n) and not st.get("moving"):
                st["moving"] = now + f.get("travel_ms", 400) / 1000.0
                self.pipe.set(f["open" if st["open"] else "closed"], 0)
            if st.get("moving") and now >= st["moving"]:
                st["moving"] = None
                st["open"] = 0 if st["open"] else 1
                self.pipe.set(f["open" if st["open"] else "closed"], 1)

    # -- what core.vbs asks
    def changed_lamps(self):
        with self.lock:
            if not self.lamp_pending:
                return None
            out = [[n, self.lamp_state[n]] for n in sorted(self.lamp_pending)]
            self.lamp_pending.clear()
        return out

    def changed_solenoids(self):
        with self.lock:
            if not self.sol_pending:
                return None
            out = [[n, self.sol_state[n]] for n in sorted(self.sol_pending)
                   if n <= self.map.sol_max]
            self.sol_pending.clear()
        return out or None

    def lamp(self, n):
        with self.lock:
            return bool(self.lamp_state.get(int(n or 0), 0))

    def solenoid(self, n):
        with self.lock:
            return bool(self.sol_state.get(int(n or 0), 0))

    def status(self):
        return {"title": self.title, "running": self.running, "polls": self.polls,
                "poll_fail": self.poll_fail, "last_poll_ms": round(self.last_poll_ms, 2),
                "rig": self.rig.how if self.rig else None,
                "attached": self.attached,
                "started": self.launch.slot if self.launch else None,
                "held": dict(self.pipe.held) if self.pipe else {},
                "lamps_on": sum(self.lamp_state.values()),
                "sols_on": [n for n, v in self.sol_state.items() if v]}


# ---------------------------------------------------------------- COM ------

class _Anything:
    """Controller.Games(name).Settings.Value("volume") and friends: a thing
    that accepts any property and answers 0."""

    _public_methods_ = []
    _reg_policy_spec_ = "DynamicPolicy"

    def _dynamic_(self, name, lcid, wFlags, args):
        if wFlags & DISPATCH_PROPERTYPUT:
            return None
        if name.lower() in ("settings", "games"):
            return _anything()
        return 0


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
        log("PAD.Controller created")

    TRACE = os.path.exists(os.path.join(os.path.dirname(LOG), "padvpx_trace"))

    def _dynamic_(self, name, lcid, wFlags, args):
        b = self.bridge
        key = name.lower()
        if self.TRACE and key not in ("changedlamps", "changedsolenoids", "lamp", "solenoid"):
            log("call %s flags=%d args=%r" % (name, wFlags, tuple(args)))
        try:
            if wFlags & DISPATCH_PROPERTYPUT:
                self._put(key, args)
                # VBScript passes VARIABLES by reference: `Controller.Switch(sw) =
                # True` hands `sw` over VT_BYREF, and a put that returns nothing
                # writes Null back into it - the caller's `sw` is gone after the
                # call (PADSPIKE2.vbs's swStartButton was, on the first real key).
                # Returning the arguments is pywin32's way of handing byrefs back
                # unchanged (a put has no return slot, so no leading None).
                return tuple(args)
            return self._get(key, args)
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
        elif key == "lamp" or key == "solenoid" or key == "solmask":
            pass
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
        if key in ("getmech", "mech", "dip", "solmask", "rawdmdwidth", "rawdmdheight",
                   "timefence"):
            return 0
        if key == "padstatus":
            return json.dumps(b.status())
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
        _reg.UseCommandLine(PadController, addnPath=HERE)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
