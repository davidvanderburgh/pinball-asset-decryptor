#!/usr/bin/env python3
"""s1bridge.py - the Spike 1 rig behind PAD.Controller (PAD-943).

The Spike 2 rig publishes its lamps and coils in `padled` and takes switches
through `padsw`; the Spike 1 rig (tools/spike1_emu) has its own two files in
its work dir, the ones the app's switch window reads and writes:

  s1hw.state   "S1HW": u32 magic, version, seq, flags; u8 switches[1024];
               u8 lamps[1024 * 3] (r, g, b per slot; a Spike 1 lamp is mono,
               so the three are one level); u8 coils[1024]. Written by the
               node-bus responder (nodebus.py DmdFrames, s1early.py).
  s1sw.input   "S1SW": u32 magic, version, seq; a 128-byte bitmap, one bit
               per slot, set = closed. Read by the responder every frame.

A slot is node * 64 + index, so a table numbers Spike 1 switches and lamps
the way it numbers Spike 2's (1000 + the slot; lamps 1000 + node * 100 +
index) and coils 1000 + node * 64 + index. The layout is
pinball_decryptor/plugins/stern/spike1_emulate.py's, stated here so the
controller does not import the app (tests pin the two together).

The run is found on the rig board as `spike1-0.run` (one Spike 1 rig; its
start.sh posts the record with the work dir as `root`), and the files are
read over \\\\wsl.localhost like padled is. The switch names come from the
run's s1switches.json ({"node,index": name}), the rig's own numbering.
"""
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
S1RIG = os.path.join(os.path.dirname(RIG), "spike1_emu")

MAX_NODES = 16
MAX_INDEX = 64
N_SLOTS = MAX_NODES * MAX_INDEX
STATE_MAGIC = 0x53314857                 # "S1HW"
STATE_VERSION = 1
STATE_HEADER = struct.Struct("<4I")
STATE_SIZE = STATE_HEADER.size + N_SLOTS + N_SLOTS * 3 + N_SLOTS
INPUT_MAGIC = 0x53315357                 # "S1SW"
INPUT_HEADER = struct.Struct("<3I")
INPUT_NBYTES = (N_SLOTS + 7) // 8
INPUT_SIZE = INPUT_HEADER.size + INPUT_NBYTES

BOARD = os.path.join(os.path.expanduser("~"), ".pad-rig")
#: the rig's own default work dir (start.sh / s1ball.py), for a record that
#: carries no `root` (one posted by an older start.sh)
DEFAULT_WORK = "/home/david/s1emu"


def slot(node, index):
    return node * MAX_INDEX + index


def sol_number(node, index):
    """The 1000+ number a Spike 1 coil is reported under."""
    return 1000 + node * MAX_INDEX + index


def is_up(data):
    """A fresh s1hw.state read says a run is up (the responder wrote it)."""
    return (data is not None and len(data) >= STATE_SIZE
            and STATE_HEADER.unpack_from(data, 0)[0] == STATE_MAGIC)


def unpack(data):
    """(switches, lamps, coils, seq) from a state block, or None."""
    if not is_up(data):
        return None
    _, _, seq, _ = STATE_HEADER.unpack_from(data, 0)
    o = STATE_HEADER.size
    return (data[o:o + N_SLOTS], data[o + N_SLOTS:o + N_SLOTS * 4],
            data[o + N_SLOTS * 4:o + N_SLOTS * 5], seq)


def lamp_level(lamps, node, index):
    """One lamp's level: the brightest of its three bytes (a mono lamp
    carries the same in all three)."""
    i = slot(node, index) * 3
    return max(lamps[i:i + 3]) if 0 <= node < MAX_NODES and 0 <= index < MAX_INDEX else 0


def lamp_rgb(lamps, node, index):
    i = slot(node, index) * 3
    return tuple(lamps[i:i + 3])


def pack_input(closed, seq):
    bits = bytearray(INPUT_NBYTES)
    for s in closed:
        if 0 <= s < N_SLOTS:
            bits[s >> 3] |= 1 << (s & 7)
    return INPUT_HEADER.pack(INPUT_MAGIC, STATE_VERSION, seq & 0xFFFFFFFF) + bytes(bits)


def read_names(path):
    """{(node, index): name} from an s1switches.json; {} when it is not
    there yet (the live walk writes it a minute or two into a run)."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, str):
            continue
        try:
            node, index = (int(x) for x in k.split(","))
        except ValueError:
            continue
        out[(node, index)] = v
    return out


def board_record(title=None, board=None):
    """The Spike 1 rig's board record, when its run is the title's (a title
    compared the way the rig names its cards: case apart), or the only Spike 1
    run for a table that names none."""
    try:
        rec = json.load(open(os.path.join(board or BOARD, "spike1-0.run"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("emu") != "spike1":
        return None
    if title and (rec.get("game") or "").lower() != title.lower():
        return None
    return rec


class Spike1Rig:
    """WHERE the Spike 1 run is: its work dir as Windows sees it, in the shape
    padcontroller.Rig has (led_path = the state block, sw_path = the input
    bitmap, switch_ids = the slots the run's names table knows)."""

    def __init__(self, title=None, record=None):
        rec = record or board_record(title)
        self.record = rec
        self.distro = (rec or {}).get("distro") or os.environ.get("PAD_WSL_DISTRO")
        self.root = (rec or {}).get("root") or os.environ.get("S1_WORK") or self._app_work() or DEFAULT_WORK
        self.slot = 0
        self.how = ("rig board spike1-0 (%s)" % rec.get("game")) if rec else "no Spike 1 run on the board"
        if sys.platform == "win32" and self.distro:
            self.dump = r"\\wsl.localhost\%s%s" % (self.distro, self.root.replace("/", "\\"))
        else:
            self.dump = self.root

    def _app_work(self):
        """A record posted by an older start.sh carries no root: the app's
        data disk holds the rig's work when the run is in the app's runtime."""
        try:
            import padlaunch
            return padlaunch.app_work(self.distro, "spike1")
        except Exception:                                   # noqa: BLE001
            return ""

    def wsl_head(self):
        head = ["wsl.exe"]
        if self.distro:
            head += ["-d", self.distro]
        return head

    def led_path(self):
        return os.path.join(self.dump, "s1hw.state")

    def sw_path(self):
        return os.path.join(self.dump, "s1sw.input")

    def ballfeed_off_path(self):
        """The ball keeper (s1ball.py) serves the game's trough on a rig run;
        this file in the work dir tells it to stand aside for the table's."""
        return os.path.join(self.dump, "s1ball.off")

    def names_path(self):
        return os.path.join(self.dump, "s1switches.json")

    def switch_ids(self, title=None):
        """{(node, index): slot} for every switch the run's names table has."""
        return {k: slot(*k) for k in read_names(self.names_path())}


class Spike1Pipe:
    """Switches IN: the input bitmap, rewritten whole on every change (the
    app's switch window writes it the same way, from Windows). `held` is the
    shape padcontroller reads: {slot: level}."""

    def __init__(self, rig):
        self.rig = rig
        self.held = {}
        self.seq = int(time.time()) & 0xFFFF
        self._failed = 0
        self._pause_said = False

    def set(self, sw, level):
        level = 1 if level else 0
        if self.held.get(sw) == level:
            return True
        self.held[sw] = level
        return self._write()

    def pause(self):
        # the Spike 1 rig has no pause line; Visual Pinball's pause leaves
        # the game running (its own display is the rig's DMD window)
        if not self._pause_said:
            self._pause_said = True
            _log("pause: the Spike 1 rig has no pause; the game runs on")
        return False

    def _write(self):
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        closed = {s for s, lv in self.held.items() if lv}
        try:
            tmp = self.rig.sw_path() + ".tmp"
            with open(tmp, "wb") as f:
                f.write(pack_input(closed, self.seq))
            os.replace(tmp, self.rig.sw_path())
            return True
        except OSError as exc:
            self._failed += 1
            if self._failed <= 3:
                _log("s1sw.input write failed: %s" % exc)
            return False

    def close(self):
        if self.held:
            self.held = {}
            self._write()


def _log(msg):
    try:
        import padcontroller
        padcontroller.log(msg)
    except Exception:                                       # noqa: BLE001
        pass
