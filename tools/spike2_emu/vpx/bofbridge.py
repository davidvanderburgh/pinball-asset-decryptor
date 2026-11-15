#!/usr/bin/env python3
"""bofbridge.py - the Barrels of Fun rig behind PAD.Controller (PAD-1305).

tools/bof_emu's boards (bofhw.py) load PAD's own plugin, bofvpx.py, which
keeps two files in the run's hw folder in the Spooky rig's layout
(spkbridge.py) with magics of their own and one plane more:

  vpxhw.state   "BFHW": u32 magic, version, seq, flags; u8 switches[1024];
                u8 lamps[1024 * 3] (r, g, b per LED); u8 coils[1024];
                u8 rules[1024]: per coil, the switch slot of the rule the
                game armed on the Neuron (a flipper, a sling), 0 = none
  vpxsw.input   "BFSW": u32 magic, version, seq; a 128-byte bitmap, one bit
                per switch slot, set = closed - what the table holds

and stands PAD's ball model aside while `vpxball.off` is there (the
controller writes it at attach, as on Spooky).

Numbers. A BoF switch n is slot n + 1 (the controller's switch id 0 means
"none", and switch 0 is the coin slot), so a map writes it `"id": n + 1`. A
driver (coil) d is slot d: `[d // 64, d % 64]`. An LED is slot
board * 128 + index, board being the expansion board's place in the title
profile's exp_boards (Dune: 48, b4, 84, 86 -> 0..3), so `[s // 64, s % 64]`.
BICS magnets, steppers and servos are not in the block: the line stream
(bofvpx.py, `M`/`W`/`V`) carries them. The layout is bofvpx.py's, stated
here so the controller does not import the rig (tests pin the two together).

The rule plane is what keeps a flipper on the table: the Neuron fires it on
its own the moment its button closes, while the game has the rule armed, so
the controller fires the coil from the table's own button edge (no trip to
WSL and back) and only while the plane says the rule is armed - not in
attract, not after a tilt.

The run is found on the rig board as `bof-<slot>.run` whose game is the
title's profile (dune, winchester, labyrinth); its record carries the hw
folder as `root` (RIGBOARD_ROOT, set by run_game.sh), read over
\\\\wsl.localhost.
"""
import json
import os
import sys

import spkbridge
from s1bridge import (INPUT_HEADER, MAX_INDEX, MAX_NODES, N_SLOTS,  # noqa: F401
                      STATE_HEADER, lamp_level, lamp_rgb, slot)

STATE_MAGIC = 0x42464857                 # "BFHW"
INPUT_MAGIC = 0x42465357                 # "BFSW"
STATE_VERSION = 1
STATE_SIZE = STATE_HEADER.size + N_SLOTS * 6
STATE_FILE = "vpxhw.state"
INPUT_FILE = "vpxsw.input"
ATTACHED_FILE = "vpxball.off"
#: a BoF switch n is slot n + SWITCH_BASE
SWITCH_BASE = 1
#: LED slots per expansion board
LEDS_PER_BOARD = 128

BOARD = spkbridge.BOARD
#: the rig's own folders (tools/bof_emu/bofpath.sh: BOF_ROOT/rig<slot>/hw)
DEFAULT_ROOT = "/var/tmp/pad_bof"
EMUS = ("bof",)


def sol_number(node, index):
    """The 1000+ number a BoF driver is reported under."""
    return 1000 + node * MAX_INDEX + index


def switch_slot(n):
    return n + SWITCH_BASE


def led_slot(board_place, index):
    return board_place * LEDS_PER_BOARD + index


def is_up(data):
    """A fresh vpxhw.state read says a run is up (the plugin wrote it)."""
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


def rules(data):
    """{coil slot: switch slot} of every rule the game has armed, or {}."""
    if not is_up(data):
        return {}
    o = STATE_HEADER.size + N_SLOTS * 5
    plane = data[o:o + N_SLOTS]
    return {i: s for i, s in enumerate(plane) if s}


def pack_input(closed, seq):
    raw = spkbridge.s1bridge.pack_input(closed, seq)
    return INPUT_HEADER.pack(INPUT_MAGIC, STATE_VERSION, seq & 0xFFFFFFFF) + raw[INPUT_HEADER.size:]


def board_record(title=None, board=None, slot=None):
    """A BoF run on the rig board: the title's, or the one on `slot`, or the
    first for a table that names none."""
    d = board or BOARD
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("bof-") and n.endswith(".run"))
    except OSError:
        return None
    for n in names:
        try:
            rec = json.load(open(os.path.join(d, n), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("emu") not in EMUS:
            continue
        if slot is not None and rec.get("slot") != slot:
            continue
        if title and (rec.get("game") or "").lower() != title.lower():
            continue
        return rec
    return None


class BofRig(spkbridge.SpookyRig):
    """WHERE the BoF run is: its hw folder as Windows sees it, in the shape
    padcontroller.Rig has."""

    def __init__(self, title=None, record=None):
        rec = record or board_record(title)
        self.record = rec
        self.distro = (rec or {}).get("distro") or os.environ.get("PAD_WSL_DISTRO")
        self.slot = int((rec or {}).get("slot") or 0)
        self.root = (rec or {}).get("root") or "%s/rig%d/hw" % (DEFAULT_ROOT, self.slot)
        self.how = ("rig board bof-%d (%s)" % (self.slot, rec.get("game"))) if rec \
            else "no Barrels of Fun run on the board"
        if sys.platform == "win32" and self.distro:
            self.dump = r"\\wsl.localhost\%s%s" % (self.distro, self.root.replace("/", "\\"))
        else:
            self.dump = self.root

    def switch_ids(self, title=None):
        # the flippers are the rule plane's: no button table needed
        return {}


class BofPipe(spkbridge.SpookyPipe):
    """Switches IN: vpxsw.input, rewritten whole on every change."""

    def pause(self):
        if not self._pause_said:
            self._pause_said = True
            spkbridge.s1bridge._log("pause: the BoF rig is not paused from a table; the game runs on")
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
                spkbridge.s1bridge._log("vpxsw.input write failed: %s" % exc)
            return False


#: the names padcontroller takes a slot platform's rig and pipe by
Rig = BofRig
Pipe = BofPipe
