#!/usr/bin/env python3
"""spkbridge.py - the Spooky rig behind PAD.Controller (PAD-952).

tools/spooky_emu's board (spkwarden.py, and the Pinotaur of Halloween and
Ultraman on it) keeps two files in its rig folder for a table, in the
Spike 1 rig's layout (s1bridge.py) with magics of their own:

  vpxhw.state   "SPHW": u32 magic, version, seq, flags; u8 switches[1024];
                u8 lamps[1024 * 3] (r, g, b per LED); u8 coils[1024]
  vpxsw.input   "SPSW": u32 magic, version, seq; a 128-byte bitmap, one bit
                per switch, set = closed - what the table holds

and stands its own ball model aside while `vpxball.off` is there (the
controller writes it at attach, as ballfeed.off on Spike 2).

A Spooky switch, LED and coil are the game's own numbers, so the slot of
s1bridge (node * 64 + index) is the number itself: a map writes switch n as
`"id": n`, coil c as `[c // 64, c % 64]` (every Halloween coil is [0, c]) and
LED n as `[n // 64, n % 64]`. A servo s is coil SERVO_COIL + s, on while it
stands up: Halloween lifts its two subways with servos 0 and 1, not coils.
The layout is spkwarden.py's, stated here so the controller does not import
the rig (tests pin the two together).

The run is found on the rig board as `spooky-<slot>.run` whose game is the
title's build (`h78_v118` for h78); its record carries the rig folder as
`root` (RIGBOARD_ROOT, set by run_game.sh), read over \\\\wsl.localhost.

PAD-954: a P-ROC title (Alice Cooper's Nightmare Castle: tools/spooky_emu/
proc on tools/proc_emu's board) posts `spooky-proc-<slot>.run` (game
`ac_1.1.0.5`) and its board (prochw.py --bridge) keeps the same two files in
the same layout, so the same Rig and Pipe drive it. There a switch is the
board's number (`SD24` = 24), an LED n and a coil n are the n-th of the
machine yaml's PRLEDs and PRCoils (in its order: a driver's number depends on
the order the game sets its driver groups up), and there are no servos.
"""
import json
import os
import sys

import s1bridge
from s1bridge import (INPUT_HEADER, MAX_INDEX, MAX_NODES, N_SLOTS,  # noqa: F401
                      STATE_HEADER, STATE_SIZE, lamp_level, lamp_rgb, sol_number, slot)

STATE_MAGIC = 0x53504857                 # "SPHW"
INPUT_MAGIC = 0x53505357                 # "SPSW"
STATE_VERSION = 1
STATE_FILE = "vpxhw.state"
INPUT_FILE = "vpxsw.input"
ATTACHED_FILE = "vpxball.off"
SERVO_COIL = 32

BOARD = s1bridge.BOARD
#: the rig's own folders (tools/spooky_emu/spkpath.sh: SPK_ROOT/rig<slot>)
DEFAULT_ROOT = "/var/tmp/pad_spooky"
#: the P-ROC rig's (tools/spooky_emu/proc/sppath.sh: SPP_ROOT/rig<slot>)
PROC_ROOT = "/var/tmp/pad_spkproc"
#: the rig board's `emu` of a Spooky run: the Warden board's, and the P-ROC
#: rig's (tools/spooky_emu/proc, PAD-954)
EMUS = ("spooky", "spooky-proc")


def is_up(data):
    """A fresh vpxhw.state read says a run is up (the board wrote it)."""
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


def pack_input(closed, seq):
    raw = s1bridge.pack_input(closed, seq)
    return INPUT_HEADER.pack(INPUT_MAGIC, STATE_VERSION, seq & 0xFFFFFFFF) + raw[INPUT_HEADER.size:]


def title_of_game(game):
    """The rig board's `game` (the build: h78_v118, um_v1_18) -> its title."""
    return (game or "").split("_", 1)[0].lower()


def board_record(title=None, board=None, slot=None):
    """A Spooky run on the rig board: the title's (its build's name starts
    with the title), or the one on `slot`, or the first for a table that
    names none."""
    d = board or BOARD
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("spooky-") and n.endswith(".run"))
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
        if title and title_of_game(rec.get("game")) != title.lower():
            continue
        return rec
    return None


class SpookyRig(s1bridge.Spike1Rig):
    """WHERE the Spooky run is: its rig folder as Windows sees it, in the
    shape padcontroller.Rig has."""

    def __init__(self, title=None, record=None):
        rec = record or board_record(title)
        self.record = rec
        self.distro = (rec or {}).get("distro") or os.environ.get("PAD_WSL_DISTRO")
        self.slot = int((rec or {}).get("slot") or 0)
        self.root = (rec or {}).get("root") or "%s/rig%d" % (
            PROC_ROOT if (rec or {}).get("emu") == "spooky-proc" else DEFAULT_ROOT, self.slot)
        self.how = ("rig board spooky-%d (%s)" % (self.slot, rec.get("game"))) if rec \
            else "no Spooky run on the board"
        if sys.platform == "win32" and self.distro:
            self.dump = r"\\wsl.localhost\%s%s" % (self.distro, self.root.replace("/", "\\"))
        else:
            self.dump = self.root

    def led_path(self):
        return os.path.join(self.dump, STATE_FILE)

    def sw_path(self):
        return os.path.join(self.dump, INPUT_FILE)

    def ballfeed_off_path(self):
        return os.path.join(self.dump, ATTACHED_FILE)

    def switch_ids(self, title=None):
        # the flipper buttons' coils are the board's own (it publishes them
        # on while their buttons are held), so the controller needs no table
        return {}


class SpookyPipe(s1bridge.Spike1Pipe):
    """Switches IN: vpxsw.input, rewritten whole on every change."""

    def pause(self):
        if not self._pause_said:
            self._pause_said = True
            s1bridge._log("pause: the Spooky rig is not paused from a table; the game runs on")
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
                s1bridge._log("vpxsw.input write failed: %s" % exc)
            return False


#: the names padcontroller takes a slot platform's rig and pipe by
Rig = SpookyRig
Pipe = SpookyPipe
