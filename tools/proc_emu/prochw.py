#!/usr/bin/env python3
"""prochw.py - an emulated P3-ROC (or P-ROC) board for the pyprocgame,
SkeletonGame and libpinproc titles (American Pinball, Dutch Pinball, Spooky).

The board is an FPGA behind an FTDI USB FIFO.  libpinproc writes 32-bit words
to it (big-endian bytes) and reads words back; PRDevice.cpp / PRHardware.cpp
are the whole protocol.  This daemon IS that FPGA: it listens on
<dir>/fpga.sock and every host - the real libpinproc through fakeftdi.so, or
pystub/pinproc.py - writes and reads the same word stream there.

  write burst  (bit31=1, len, module, addr) + len words
      manager      watchdog, dipswitch config
      switch ctrl  switch config (host events on/off)
      driver ctrl  global / group config, driver table (coils, lamps),
                   PD-LED board writes (0xC00)
      state change switch rules: notify host, linked driver changes
      DMD / aux    DMD config and frames (P-ROC), aux port (P3-ROC)
  read request (bit31=0, len, module, addr) -> the same header + len words
      manager      chip id, version, watchdog, dipswitches
      switch ctrl  switch state words (bit set = open), debounce words
  events       unrequested header (bit31=1) + one event word: switch
               changes the rules ask the host to hear about, DMD frames

Control: a unix socket at <dir>/ctl.sock taking one command per line:
  sw <sw> <0|1>        set a switch; 1 = active (an NC switch opens)
  closed <sw> <0|1>    set a switch's contacts; 1 = closed
  tap <sw> [ms]        active, then inactive after ms (default 120)
  state                JSON: board, host, switches, drivers on, counters
  switches             JSON: every switch the machine yaml names
  drivers              JSON: every driver not off
  log [n]              JSON: the last n driver changes (default 50)
  leds                 JSON: "<board>:<index>" -> brightness 0..255
  balls eject=<driver> shooter=<sw> [launch=<driver>]
                       turn the ball model on (below); `balls` alone reports it
  drain                a ball from the playfield back into the trough
  plunge               the ball in the shooter lane goes onto the playfield
  coils <name>=<driver> ...
                       the game's coil objects' driver numbers (its runner
                       sends them at attract), for a table's bridge; `coils`
                       alone: JSON, the yaml's coils -> their drivers
  quit
<sw> is a number, a name from the machine yaml, or a yaml-style address
(SD12, 3/4, S21 ...).  Replies are one line; errors start with "err".

The ball model (off until `balls` turns it on - the title's runner does,
from the game's own coil and switch objects, because a PDB coil's driver
number depends on the order the game configures its driver groups): a pulse
of the eject driver takes a ball out of the trough and makes the shooter
switch half a second later; a pulse of the launch driver (or `plunge`)
empties the shooter lane; `drain` puts a ball back.  The trough's balls sit
packed from its lowest-numbered switch (trough1: the eject end), as the
initial seeding has them.  No other physics: everything else is a switch
you press.

A Visual Pinball table (PAD-954; --bridge DIR): the Spooky Warden board's
two files (tools/spooky_emu/spkwarden.py, tools/spike2_emu/vpx/spkbridge.py)
in DIR, so PAD.Controller drives a P-ROC game as it drives Halloween:

  vpxhw.state   "SPHW": u32 magic, version, seq, flags; u8 switches[1024]
                (1 = active, by the board's switch number); u8 lamps[1024 *
                3] (r, g, b of the yaml's PRLEDs entry n, in the yaml's
                order); u8 coils[1024] (the yaml's PRCoils entry n, in the
                yaml's order: on while its driver is, or pulsed in the last
                BRIDGE_PULSE_S)
  vpxsw.input   "SPSW": u32 magic, version, seq; a 128-byte bitmap, one bit
                per switch number, set = active - what the table holds

A coil is named by its place in the yaml, not its driver number, because
that number depends on the order the game configures its driver groups (the
`coils` command tells the board which is which).  While `vpxball.off` is in
DIR the table owns the balls: the ball model stands aside, and the first
input sets the trough and the shooter lane whole.

Initial switches: with --yaml, the trough holds PRGame.numBalls balls
(switches named trough<N>, lowest N first) and every other switch is at
rest - an NC switch at rest is CLOSED.  Without --yaml every switch is open
except --closed ones.  (FakePinPROC reports every switch open, which is why
a NO trough sits in ball search there.)
"""
import argparse
import collections
import heapq
import json
import os
import re
import select
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pystub"))
import pinproc as pp  # noqa: E402  (the one copy of the protocol constants)

CHIPS = {
    # name: (chip id, version, revision)
    "p3roc": (pp.P3_ROC_CHIP_ID, 2, 17),
    "proc": (pp.P_ROC_CHIP_ID, 1, 22),
}
EVENT_HEADER = 0x80000000 | (1 << 20)   # unrequested, one word follows

# A Visual Pinball table's files (PAD-954): spkwarden.py's layout and magics
BRIDGE_SLOTS = 1024
BRIDGE_STATE = "vpxhw.state"
BRIDGE_INPUT = "vpxsw.input"
BRIDGE_ATTACHED = "vpxball.off"
BRIDGE_STATE_MAGIC = 0x53504857          # "SPHW"
BRIDGE_INPUT_MAGIC = 0x53505357          # "SPSW"
BRIDGE_VERSION = 1
BRIDGE_POLL_S = 0.005
BRIDGE_IDLE_S = 0.5
#: how long a pulsed coil reads on in the block (the controller polls every
#: few ms; a 15 ms sling pulse must be seen)
BRIDGE_PULSE_S = 0.08


def u32(v):
    return v & 0xffffffff


def decode_driver(w1, w2):
    return {"outputDriveTime": w1 & 0xff, "polarity": (w1 >> 8) & 1,
            "state": (w1 >> 9) & 1, "waitForFirstTimeSlot": (w1 >> 11) & 1,
            "timeslots": ((w1 >> 16) & 0xffff) | ((w2 & 0xffff) << 16),
            "patterOnTime": (w2 >> 16) & 0x7f, "patterOffTime": (w2 >> 23) & 0x7f,
            "patterEnable": (w2 >> 30) & 1, "futureEnable": (w2 >> 31) & 1}


def describe_driver(d):
    if d["patterEnable"]:
        text = "patter %d/%d" % (d["patterOnTime"], d["patterOffTime"])
        if not d["state"]:
            text += " for %dms" % d["outputDriveTime"]
        elif d["outputDriveTime"]:
            text += " after %dms" % d["outputDriveTime"]
        return text
    if d["futureEnable"]:
        return "future pulse %dms" % d["outputDriveTime"]
    if not d["state"]:
        return "off"
    if d["timeslots"]:
        return "schedule %08x" % d["timeslots"]
    if d["outputDriveTime"]:
        return "pulse %dms" % d["outputDriveTime"]
    return "on"


# ------------------------------------------------------------------ machine
class Machine:
    """What the title's machine yaml says about its switches."""

    TROUGH = re.compile(r"^trough\s*(\d+)$", re.I)

    def __init__(self, yaml_path=None, machine_type=None):
        self.machine_type = pp.normalize_machine_type(machine_type or "pdb")
        self.switches = {}          # name -> number
        self.nc = set()             # numbers of NC switches
        self.num_balls = 0
        self.leds = []              # PRLEDs in the yaml's order: (board, r, g, b) or None
        self.led_names = []
        self.coil_names = []        # PRCoils in the yaml's order
        if yaml_path:
            self._load(yaml_path)

    def _load(self, path):
        import yaml
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        game = cfg.get("PRGame") or {}
        if "machineType" in game:
            self.machine_type = pp.normalize_machine_type(str(game["machineType"]))
        self.num_balls = int(game.get("numBalls") or 0)
        for name, item in (cfg.get("PRSwitches") or {}).items():
            item = item or {}
            if "number" not in item:
                continue
            try:
                num = self.decode_switch(str(item["number"]))
            except ValueError:
                continue
            if not 0 <= num < 256:
                continue
            self.switches[str(name)] = num
            if str(item.get("type", "NO")).upper() == "NC":
                self.nc.add(num)
        self.coil_names = [str(k) for k in (cfg.get("PRCoils") or {})]
        for name, item in (cfg.get("PRLEDs") or {}).items():
            self.led_names.append(str(name))
            self.leds.append(self.decode_led(str((item or {}).get("number", ""))))

    LED = re.compile(r"^A(\d+)-R(\d+)-G(\d+)-B(\d+)$", re.I)

    def decode_led(self, text):
        """A PD-LED address (`A1-R0-G1-B2`: board 1, its outputs for red,
        green and blue) -> (board, r, g, b), or None."""
        m = self.LED.match(text.strip())
        return tuple(int(g) for g in m.groups()) if m else None

    def decode_switch(self, text):
        """The number pyprocgame gives a yaml switch address."""
        if self.machine_type == pp.MachineTypePDB:
            up = text.upper()
            if up.startswith("SD"):             # procgame/game/pdb.py Switch
                return int(up[2:])
            if "/" in up:
                col, row = up.split("/")[:2]
                return 32 + int(col) * 16 + int(row)
            return int(text)
        return pp._pr_decode(self.machine_type, text) & 0xffff

    def resolve(self, word):
        if word in self.switches:
            return self.switches[word]
        lowered = dict((k.lower(), v) for k, v in self.switches.items())
        if word.lower() in lowered:
            return lowered[word.lower()]
        if re.match(r"^-?\d+$", word):
            return int(word)
        # PRDecode() atoi()s anything it does not recognise - "nosuch" would
        # quietly be switch 0.  Only address shapes reach it.
        if not re.match(r"^(S[DF]?\d{1,3}|\d+/\d+)$", word, re.I):
            raise ValueError("unknown switch: %s" % word)
        return self.decode_switch(word)

    def names(self):
        by_num = collections.defaultdict(list)
        for name, num in self.switches.items():
            by_num[num].append(name)
        return by_num

    def trough(self):
        found = []
        for name, num in self.switches.items():
            m = self.TROUGH.match(name)
            if m:
                found.append((int(m.group(1)), num))
        return [num for _, num in sorted(found)]

    def initial_closed(self, balls=None, active=(), closed=()):
        """Switch numbers whose contacts start closed."""
        balls = self.num_balls if balls is None else balls
        on = set(self.trough()[:balls]) | set(active)
        result = set(closed)
        for num in set(self.switches.values()) | on:
            if (num in on) != (num in self.nc):
                result.add(num)
            else:
                result.discard(num)
        return result


# --------------------------------------------------------------------- FPGA
class Parser:
    """One host connection's half-read burst."""

    def __init__(self, fpga):
        self.fpga = fpga
        self.buf = bytearray()
        self.header = None
        self.words = []

    def feed(self, data):
        """Bytes from the host -> reply bytes for that host."""
        self.buf += data
        reply = []
        while len(self.buf) >= 4:
            w = (self.buf[0] << 24) | (self.buf[1] << 16) | (self.buf[2] << 8) | self.buf[3]
            del self.buf[:4]
            if self.header is None:
                n = (w & pp.P_ROC_HEADER_LENGTH_MASK) >> pp.P_ROC_HEADER_LENGTH_SHIFT
                module = (w & pp.P_ROC_MODULE_SELECT_MASK) >> pp.P_ROC_MODULE_SELECT_SHIFT
                addr = w & pp.P_ROC_REG_ADDR_MASK
                if (w >> 31) & 1 == pp.P_ROC_READ:
                    reply.append(w & 0x7fffffff)
                    reply.extend(self.fpga.read(module, addr, n))
                elif n == 0:
                    self.fpga.write(module, addr, [])
                else:
                    self.header, self.words = (module, addr, n), []
            else:
                self.words.append(w)
                module, addr, n = self.header
                if len(self.words) == n:
                    self.header = None
                    self.fpga.write(module, addr, self.words)
        return pp.words_to_bytes(reply)


class Fpga:
    def __init__(self, chip="p3roc", machine=None, closed=(), clock=time.monotonic,
                 dmd_fps=60.0):
        self.chip_id, self.version, self.revision = CHIPS[chip]
        self.chip = chip
        self.machine = machine or Machine()
        self.clock = clock
        self.t0 = clock()
        wpc = self.machine.machine_type in (pp.MachineTypeWPC, pp.MachineTypeWPC95,
                                            pp.MachineTypeWPCAlphanumeric)
        self.dipswitches = 1 if wpc else 0      # bit 0 clear = Stern board
        self.closed = [False] * 256
        for n in closed:
            self.closed[n] = True
        self.rules = [None] * pp.NUM_SWITCH_RULES
        self.drivers = [None] * pp.DriverCount   # decoded driver dicts
        self.pulse_ends = []                     # heap (t, driver, seq)
        self.driver_seq = [0] * pp.DriverCount
        self.globals_word = 0
        self.groups = {}
        self.manager = {pp.P_ROC_REG_WATCHDOG_ADDR: 0, pp.P_ROC_REG_DIPSWITCH_ADDR: 0}
        self.watchdog_at = None
        self.switch_config = 0
        self.host_events = False
        self.dmd_config = 0
        self.dmd_frames = 0
        self.dmd_last = None
        self.dmd_next = None
        self.dmd_period = 1.0 / dmd_fps if dmd_fps > 0 else None
        self.aux = []
        self.leds = {}
        self.led_index = {}
        self.led_fade = {}
        self.events = bytearray()                # unrequested words for the host
        self.timers = []                         # heap (t, seq, fn, args)
        self.timer_seq = 0
        self.log = collections.deque(maxlen=2000)
        self.counts = collections.Counter()
        self.ball_model = None                   # {"eject", "shooter", "launch"}
        self.in_play = 0                         # balls out of the trough
        self.coil_drivers = {}                   # yaml coil name -> driver (`coils`)
        self.pulsed_at = {}                      # driver -> when it last went on
        self.bridged = False                     # a table owns the balls (PAD-954)
        self.table_held = set()
        self.bridge_first = True

    # ---- helpers
    def now_ms(self):
        return int((self.clock() - self.t0) * 1000)

    def after(self, secs, fn, *args):
        self.timer_seq += 1
        heapq.heappush(self.timers, (self.clock() + secs, self.timer_seq, fn, args))

    def next_deadline(self):
        times = [t for t, _, _, _ in self.timers[:1]] + [t for t, _, _ in self.pulse_ends[:1]]
        if self.dmd_next is not None:
            times.append(self.dmd_next)
        return min(times) if times else None

    def tick(self):
        now = self.clock()
        while self.timers and self.timers[0][0] <= now:
            _, _, fn, args = heapq.heappop(self.timers)
            fn(*args)
        while self.pulse_ends and self.pulse_ends[0][0] <= now:
            _, num, seq = heapq.heappop(self.pulse_ends)
            if seq == self.driver_seq[num] and self.drivers[num]:
                self.drivers[num]["active"] = False
        if self.dmd_next is not None and now >= self.dmd_next:
            self.dmd_next = max(self.dmd_next + self.dmd_period, now)
            self.counts["dmd_events"] += 1
            self.emit(self.event_word(0, False, False, pp.P_ROC_EVENT_TYPE_DMD))

    def emit(self, word):
        self.events += pp.words_to_bytes([EVENT_HEADER, word])

    def event_word(self, num, is_open, debounced, typ=pp.P_ROC_EVENT_TYPE_SWITCH):
        t = self.now_ms()
        if self.version >= 2:
            return u32((num & 0x7ff) | (int(is_open) << 12) | (int(debounced) << 13)
                       | (typ << 14) | ((t & 0xffff) << 16))
        return u32((num & 0xff) | (int(is_open) << 8) | (int(debounced) << 9)
                   | (typ << 10) | ((t & 0xfffff) << 12))

    # ---- reads
    def read(self, module, addr, n):
        out = []
        for k in range(n):
            out.append(self.read_reg(module, addr + k))
        self.counts["reads"] += 1
        return out

    def read_reg(self, module, addr):
        if module == pp.P_ROC_MANAGER_SELECT:
            if addr == pp.P_ROC_REG_CHIP_ID_ADDR:
                return self.chip_id
            if addr == 1:
                return (self.version << 16) | self.revision
            if addr == pp.P_ROC_REG_WATCHDOG_ADDR:
                return self.manager[addr]
            if addr == pp.P_ROC_REG_DIPSWITCH_ADDR:
                return self.dipswitches
            return 0
        if module == pp.P_ROC_BUS_SWITCH_CTRL_SELECT:
            if self.chip_id == pp.P3_ROC_CHIP_ID:
                state_base, deb_base = pp.P3_ROC_SWITCH_CTRL_STATE_BASE_ADDR, \
                    pp.P3_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR
            else:
                state_base, deb_base = pp.P_ROC_SWITCH_CTRL_STATE_BASE_ADDR, \
                    pp.P_ROC_SWITCH_CTRL_DEBOUNCE_BASE_ADDR
                if pp.P_ROC_SWITCH_CTRL_OLD_DEBOUNCE_BASE_ADDR <= addr < deb_base:
                    return 0xffffffff
            if state_base <= addr < state_base + 8:
                bank = addr - state_base
                w = 0
                for j in range(32):
                    if not self.closed[bank * 32 + j]:
                        w |= 1 << j                 # bit set = open
                return w
            if deb_base <= addr < deb_base + 8:
                return 0xffffffff                   # every switch settled
        return 0

    # ---- writes
    def write(self, module, addr, words):
        self.counts["writes"] += 1
        if module == pp.P_ROC_MANAGER_SELECT:
            if words:
                self.manager[addr] = words[0]
                if addr == pp.P_ROC_REG_WATCHDOG_ADDR:
                    self.watchdog_at = self.clock()
                    self.counts["watchdog"] += 1
        elif module == pp.P_ROC_BUS_SWITCH_CTRL_SELECT:
            if addr == 0 and words:
                self.switch_config = words[0]
        elif module == pp.P_ROC_BUS_DRIVER_CTRL_SELECT:
            self.write_driver_ctrl(addr, words)
        elif module == pp.P_ROC_BUS_STATE_CHANGE_PROC_SELECT:
            if addr == pp.P_ROC_STATE_CHANGE_CONFIG_ADDR:
                self.host_events = bool(words and words[0] & 1)
            elif len(words) == 3:
                self.write_rule(addr, words)
        elif module == pp.P_ROC_BUS_DMD_SELECT:
            if self.chip_id == pp.P3_ROC_CHIP_ID:
                self.aux = list(words)                  # P3-ROC: module 5 is aux
            elif addr == 0 and words:
                self.dmd_config = words[0]
                on = (words[0] >> 31) & 1 and (words[0] >> 30) & 1
                if on and self.dmd_period:
                    self.dmd_next = self.dmd_next or self.clock() + self.dmd_period
                else:
                    self.dmd_next = None
            elif addr == pp.P_ROC_DMD_DOT_TABLE_BASE_ADDR:
                self.dmd_frames += 1
                self.dmd_last = list(words)

    def write_driver_ctrl(self, addr, words):
        decode = (addr >> pp.P_ROC_DRIVER_CTRL_DECODE_SHIFT) & 3
        if addr == pp.P_ROC_DRIVER_PDB_ADDR:
            for w in words:
                self.write_pdb(w)
        elif decode == pp.P_ROC_DRIVER_CTRL_REG_DECODE:
            if addr == 0:
                self.globals_word = words[0] if words else 0
            elif words:
                self.groups[addr & 0x3ff] = words[0]
        elif decode == pp.P_ROC_DRIVER_CONFIG_TABLE_DECODE and len(words) == 2:
            self.set_driver((addr & 0x3ff) >> 1, words[0], words[1], "host")
        elif decode == pp.P_ROC_DRIVER_AUX_MEM_DECODE:
            self.aux = list(words)

    def write_pdb(self, w):
        cmd, board = (w >> 24) & 0xff, (w >> 16) & 0xff
        reg, value = (w >> 8) & 0xff, w & 0xff
        if cmd != pp.P_ROC_DRIVER_PDB_WRITE_COMMAND:
            return
        self.counts["led_writes"] += 1
        if reg == pp.LED_REG_INDEX:
            self.led_index[board] = value
        elif reg == pp.LED_REG_COLOR:
            self.leds["%d:%d" % (board, self.led_index.get(board, 0))] = value
        elif reg == pp.LED_REG_FADE_COLOR:
            # A fade lands on its colour; the rig has no need to animate it.
            self.leds["%d:%d" % (board, self.led_index.get(board, 0))] = value
        elif reg in (pp.LED_REG_FADE_RATE_LOW, pp.LED_REG_FADE_RATE_HIGH):
            self.led_fade[board] = value

    def set_driver(self, num, w1, w2, source):
        d = decode_driver(w1, w2)
        old = self.drivers[num]
        same = old is not None and all(old[k] == d[k] for k in d)
        self.driver_seq[num] += 1
        d["active"] = d["state"] == 1 or d["patterEnable"] == 1
        d["since"] = self.now_ms()
        self.drivers[num] = d
        if d["active"]:
            self.pulsed_at[num] = self.clock()
        pulse = d["state"] and d["outputDriveTime"] and not d["patterEnable"] \
            and not d["timeslots"] and not d["futureEnable"]
        if pulse:
            heapq.heappush(self.pulse_ends, (self.clock() + d["outputDriveTime"] / 1000.0,
                                             num, self.driver_seq[num]))
            same = False                        # every pulse is news
        elif d["patterEnable"] and not d["state"] and d["outputDriveTime"]:
            # "patter on/off FOR n ms" (a sling's kick, PDB bumper rules)
            # ends by itself: it read as on for ever, and a table's sling
            # coil never let go (PAD-954)
            heapq.heappush(self.pulse_ends, (self.clock() + d["outputDriveTime"] / 1000.0,
                                             num, self.driver_seq[num]))
            same = False
        if not same:
            self.counts["driver_changes"] += 1
            self.log.append({"t": d["since"], "driver": num, "action": describe_driver(d),
                             "by": source})
        if pulse and self.ball_model and not self.bridged:
            if num == self.ball_model["eject"]:
                self.eject_ball()
            elif num == self.ball_model.get("launch"):
                self.after(0.1, self.plunge)

    # ---- the ball model
    def trough_balls(self):
        return sum(1 for n in self.machine.trough() if self.active(n))

    def pack_trough(self, balls):
        for i, n in enumerate(self.machine.trough()):
            self.set_active(n, i < balls)

    def eject_ball(self):
        balls = self.trough_balls()
        if not balls:
            self.counts["eject_empty"] += 1
            return
        self.pack_trough(balls - 1)
        self.in_play += 1
        self.counts["ejects"] += 1
        self.after(0.5, self.set_active, self.ball_model["shooter"], True)

    def plunge(self):
        if self.bridged:
            return False                        # the table's plunger
        if self.ball_model and self.active(self.ball_model["shooter"]):
            self.set_active(self.ball_model["shooter"], False)
            self.counts["launches"] += 1
            return True
        return False

    def drain(self):
        if self.bridged:
            return False                        # the table's drain
        balls = self.trough_balls()
        if balls >= len(self.machine.trough()):
            return False
        self.pack_trough(balls + 1)
        self.in_play = max(0, self.in_play - 1)
        self.counts["drains"] += 1
        return True

    def write_rule(self, addr, words):
        index = (addr >> 2) & 0x3ff
        now = (addr >> 13) & 1
        w1, w2, w3 = words
        self.rules[index] = {"w1": w1, "w2": w2, "driver": w3 & 0xff,
                             "change": (w3 >> 9) & 1, "link": (w3 >> 10) & 1,
                             "link_index": (w3 >> 11) & 0x3ff, "notify": (w3 >> 23) & 1,
                             "reload": (w3 >> 31) & 1}
        self.counts["rule_writes"] += 1
        if now:
            num, is_open, _ = index & 0xff, (index >> 8) & 1, index >> 9
            if bool(is_open) == (not self.closed[num]):
                self.fire_rule_drivers(index, "rule sw%d now" % num)

    def fire_rule_drivers(self, index, source):
        seen = set()
        while index is not None and index not in seen:
            seen.add(index)
            r = self.rules[index]
            if r is None:
                return
            if r["change"]:
                self.set_driver(r["driver"], r["w1"], r["w2"], source)
            index = r["link_index"] if r["link"] else None

    # ---- switches
    def set_switch(self, num, closed):
        """Contacts change: the switch rules run, the host hears what it asked to."""
        if not 0 <= num < 256:
            raise ValueError("switch %d out of range" % num)
        closed = bool(closed)
        if self.closed[num] == closed:
            return False
        self.closed[num] = closed
        self.counts["switch_changes"] += 1
        is_open = not closed
        for debounced in (False, True):
            index = (int(debounced) << 9) | (int(is_open) << 8) | num
            r = self.rules[index]
            if r is None:
                continue
            if r["notify"] and self.host_events:
                self.counts["switch_events"] += 1
                self.emit(self.event_word(num, is_open, debounced))
            if r["change"]:
                self.fire_rule_drivers(index, "rule sw%d %s" % (num, "open" if is_open else "closed"))
        return True

    def active(self, num):
        return self.closed[num] != (num in self.machine.nc)

    def set_active(self, num, active):
        return self.set_switch(num, active != (num in self.machine.nc))

    # ---- a Visual Pinball table (PAD-954)
    def bridge_block(self, seq, now=None):
        """vpxhw.state: every switch active, every LED's colour and every
        coil on (held, or pulsed within BRIDGE_PULSE_S), by the yaml's
        order for LEDs and coils."""
        now = self.clock() if now is None else now
        n = BRIDGE_SLOTS
        sw = bytearray(n)
        lamps = bytearray(n * 3)
        coils = bytearray(n)
        for k in range(256):
            if self.active(k):
                sw[k] = 1
        for i, led in enumerate(self.machine.leds[:n]):
            if led:
                board = led[0]
                lamps[i * 3:i * 3 + 3] = bytes(self.leds.get("%d:%d" % (board, c), 0) & 255
                                               for c in led[1:])
        for i, name in enumerate(self.machine.coil_names[:n]):
            num = self.coil_drivers.get(name)
            if num is None or not 0 <= num < len(self.drivers):
                continue
            d = self.drivers[num]
            if (d and d["active"]) or now - self.pulsed_at.get(num, -1e9) < BRIDGE_PULSE_S:
                coils[i] = 1
        head = struct.pack("<4I", BRIDGE_STATE_MAGIC, BRIDGE_VERSION, seq & 0xFFFFFFFF,
                           1 if self.bridged else 0)
        return head + bytes(sw) + bytes(lamps) + bytes(coils)

    def ball_switches(self):
        """The switches the balls make: the trough's, its jam opto, the
        shooter lane - set whole from the table's first input."""
        out = set(self.machine.trough())
        for name, num in self.machine.switches.items():
            if re.match(r"^(trough\s*jam|shooter\w*)$", name, re.I):
                out.add(num)
        if self.ball_model:
            out.add(self.ball_model["shooter"])
        return out

    def set_bridged(self, on):
        if on != self.bridged:
            self.bridged = on
            self.bridge_first = True
            self.table_held = set()

    def bridge_input(self, data):
        """Apply a vpxsw.input: each switch the table changed since the last
        one; the first after attach sets the ball switches whole, so the
        board's own full trough gives way to the table's."""
        if len(data) < 12 + BRIDGE_SLOTS // 8 or not self.bridged:
            return
        magic, _, _ = struct.unpack_from("<3I", data, 0)
        if magic != BRIDGE_INPUT_MAGIC:
            return
        bits = data[12:12 + BRIDGE_SLOTS // 8]
        held = {i for i in range(256) if bits[i >> 3] >> (i & 7) & 1}
        if self.bridge_first:
            self.bridge_first = False
            for k in self.ball_switches():
                self.set_active(k, k in held)
        for k in sorted(held - self.table_held):
            self.set_active(k, True)
        for k in sorted(self.table_held - held):
            self.set_active(k, False)
        self.table_held = held

    # ---- reports
    def driver_table(self):
        out = {}
        for num, d in enumerate(self.drivers):
            if d and d["active"]:
                out[str(num)] = describe_driver(d)
        return out

    def state(self):
        names = self.machine.names()
        wd = None if self.watchdog_at is None else int((self.clock() - self.watchdog_at) * 1000)
        active = []
        for n in range(256):
            if names.get(n):
                if self.active(n):
                    active.append(names[n][0])
            elif self.closed[n]:
                active.append(str(n))
        return {
            "board": "%s %d.%d" % ("P3-ROC" if self.chip_id == pp.P3_ROC_CHIP_ID else "P-ROC",
                                   self.version, self.revision),
            "host_events": self.host_events,
            "outputs_enabled": bool(self.globals_word >> 31),
            "watchdog_ms": wd,
            "closed": [n for n in range(256) if self.closed[n]],
            "active": sorted(active),
            "drivers": self.driver_table(),
            "rules": sum(1 for r in self.rules if r and (r["notify"] or r["change"])),
            "leds": len(self.leds),
            "dmd_frames": self.dmd_frames,
            "counts": dict(self.counts),
            "bridged": self.bridged,
            "balls": None if not self.ball_model else dict(
                self.ball_model, trough=self.trough_balls(), in_play=self.in_play),
        }

    def switches(self):
        return dict((name, {"number": num, "closed": self.closed[num],
                            "active": self.active(num), "nc": num in self.machine.nc})
                    for name, num in sorted(self.machine.switches.items()))


class InProcessLink:
    """pinproc.link_factory for tests: the stub talks to an Fpga object."""

    def __init__(self, fpga):
        self.fpga = fpga
        self.parser = Parser(fpga)
        self.rx = bytearray()

    def write(self, data):
        self.rx += self.parser.feed(bytes(data))
        return len(data)

    def read(self, max_bytes, timeout=0.0):
        self.fpga.tick()
        self.rx += self.fpga.events
        del self.fpga.events[:]
        out = bytes(self.rx[:max_bytes])
        del self.rx[:max_bytes]
        return out

    def close(self):
        pass


# ------------------------------------------------------------------- daemon
class Daemon:
    def __init__(self, root, fpga, log, bridge=None):
        self.root = root
        self.bridge = bridge    # a table's folder (PAD-954), or None
        self.bridge_seq = 0
        self.bridge_seen = None
        self.bridge_written = 0.0
        self.fpga = fpga
        self.logf = log
        self.hosts = {}         # sock -> Parser
        self.host = None        # the connection events go to (the newest)
        self.ctls = {}          # sock -> partial line
        self.running = True

    def log(self, msg):
        self.logf.write("%.3f %s\n" % (time.time(), msg))
        self.logf.flush()

    def listen(self, name):
        path = os.path.join(self.root, name)
        if os.path.exists(path):
            os.unlink(path)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(path)
        os.chmod(path, 0o666)       # the game may run as another user
        s.listen(8)
        return s

    def on_ctl(self, line):
        words = line.split()
        if not words:
            return ""
        cmd, args = words[0], words[1:]
        f = self.fpga
        try:
            if cmd in ("sw", "closed") and len(args) == 2:
                num = f.machine.resolve(args[0])
                on = args[1] in ("1", "on", "true", "closed", "active")
                changed = f.set_active(num, on) if cmd == "sw" else f.set_switch(num, on)
                return "ok %d %s%s" % (num, "closed" if f.closed[num] else "open",
                                       "" if changed else " (unchanged)")
            if cmd == "tap" and args:
                num = f.machine.resolve(args[0])
                ms = int(args[1]) if len(args) > 1 else 120
                f.set_active(num, True)
                f.after(ms / 1000.0, f.set_active, num, False)
                return "ok %d tapped %dms" % (num, ms)
            if cmd == "state":
                return json.dumps(dict(f.state(), host=self.host is not None))
            if cmd == "switches":
                return json.dumps(f.switches())
            if cmd == "drivers":
                return json.dumps(f.driver_table())
            if cmd == "log":
                n = int(args[0]) if args else 50
                return json.dumps(list(f.log)[-n:])
            if cmd == "leds":
                return json.dumps(f.leds)
            if cmd == "balls":
                if args:
                    kv = dict(a.split("=", 1) for a in args if "=" in a)
                    if "eject" not in kv or "shooter" not in kv:
                        return "err balls needs eject=<driver> shooter=<sw>"
                    model = {"eject": int(kv["eject"]), "shooter": f.machine.resolve(kv["shooter"])}
                    if "launch" in kv:
                        model["launch"] = int(kv["launch"])
                    f.ball_model = model
                    self.log("ball model: %s" % model)
                return json.dumps(f.ball_model and dict(
                    f.ball_model, trough=f.trough_balls(), in_play=f.in_play))
            if cmd == "coils" and not args:
                return json.dumps(dict((n, f.coil_drivers.get(n)) for n in f.machine.coil_names))
            if cmd == "coils":
                kv = dict(a.split("=", 1) for a in args if "=" in a)
                f.coil_drivers.update((k, int(v)) for k, v in kv.items())
                known = sum(1 for n in f.machine.coil_names if n in f.coil_drivers)
                self.log("coils: %d named, %d of the yaml's %d" % (len(kv), known, len(f.machine.coil_names)))
                return "ok %d coils" % known
            if cmd == "drain":
                return "ok drained" if f.drain() else "err the trough is full"
            if cmd == "plunge":
                if not f.ball_model:
                    return "err no ball model (balls ...)"
                return "ok plunged" if f.plunge() else "err no ball in the shooter lane"
            if cmd == "quit":
                self.running = False
                return "ok bye"
        except (ValueError, IndexError) as e:
            return "err %s" % e
        return "err unknown command: %s" % line.strip()

    def run(self):
        fpga_srv = self.listen("fpga.sock")
        ctl_srv = self.listen("ctl.sock")
        self.log("listening: %s board, %d switches closed" % (
            self.fpga.chip, sum(self.fpga.closed)))
        while self.running:
            deadline = self.fpga.next_deadline()
            cap = BRIDGE_POLL_S if self.fpga.bridged else 0.05
            timeout = cap if deadline is None else max(0.0, min(cap, deadline - time.monotonic()))
            socks = [fpga_srv, ctl_srv] + list(self.hosts) + list(self.ctls)
            r, _, _ = select.select(socks, [], [], timeout)
            for s in r:
                if s is fpga_srv:
                    c, _ = fpga_srv.accept()
                    self.hosts[c] = Parser(self.fpga)
                    self.host = c
                    self.log("host connected")
                elif s is ctl_srv:
                    c, _ = ctl_srv.accept()
                    self.ctls[c] = b""
                elif s in self.hosts:
                    self.on_host(s)
                else:
                    self.on_ctl_sock(s)
            self.fpga.tick()
            if self.bridge:
                self.bridge_tick()
            self.flush_events()
        for s in list(self.hosts) + list(self.ctls) + [fpga_srv, ctl_srv]:
            s.close()

    def bridge_tick(self):
        """A table's files: attach / let go on vpxball.off, take vpxsw.input
        as it changes, publish vpxhw.state (every pass while attached, every
        BRIDGE_IDLE_S otherwise)."""
        f = self.fpga
        on = os.path.exists(os.path.join(self.bridge, BRIDGE_ATTACHED))
        if on != f.bridged:
            f.set_bridged(on)
            self.bridge_seen = None
            self.log("a Visual Pinball table attached: it owns the balls" if on
                     else "the table let go: the ball model serves the balls")
        if on:
            inp = os.path.join(self.bridge, BRIDGE_INPUT)
            try:
                st = os.stat(inp)
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                key = None
            if key and key != self.bridge_seen:
                self.bridge_seen = key
                try:
                    with open(inp, "rb") as fh:
                        f.bridge_input(fh.read())
                except OSError:
                    self.bridge_seen = None
        now = time.monotonic()
        if on or now - self.bridge_written >= BRIDGE_IDLE_S:
            self.bridge_seq += 1
            state = os.path.join(self.bridge, BRIDGE_STATE)
            try:
                with open(state + ".tmp", "wb") as fh:
                    fh.write(f.bridge_block(self.bridge_seq))
                os.replace(state + ".tmp", state)
            except OSError as e:
                if self.bridge_seq < 3:
                    self.log("bridge block not written: %s" % e)
            self.bridge_written = now

    def drop_host(self, s):
        self.hosts.pop(s, None)
        s.close()
        if self.host is s:
            self.host = next(iter(self.hosts), None)
        self.log("host disconnected")

    def on_host(self, s):
        try:
            data = s.recv(65536)
        except OSError:
            data = b""
        if not data:
            self.drop_host(s)
            return
        reply = self.hosts[s].feed(data)
        if reply:
            try:
                s.sendall(reply)        # one send per reply: libpinproc reads
            except OSError:             # a reply whole or not at all
                self.drop_host(s)

    def flush_events(self):
        if not self.fpga.events:
            return
        if self.host is None:
            del self.fpga.events[:]
            return
        data = bytes(self.fpga.events)
        del self.fpga.events[:]
        try:
            self.host.sendall(data)
        except OSError:
            self.drop_host(self.host)

    def on_ctl_sock(self, s):
        try:
            data = s.recv(4096)
        except OSError:
            data = b""
        if not data:
            self.ctls.pop(s, None)
            s.close()
            return
        buf = self.ctls[s] + data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            reply = self.on_ctl(line.decode("utf-8", "replace"))
            try:
                s.sendall((reply + "\n").encode())
            except OSError:
                break
        self.ctls[s] = buf


def parse_list(text):
    return [w for w in re.split(r"[,\s]+", text or "") if w]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", required=True, help="rig dir (fpga.sock, ctl.sock)")
    ap.add_argument("--yaml", help="the title's machine yaml (switch names, NC, balls)")
    ap.add_argument("--machine-type", help="override PRGame.machineType")
    ap.add_argument("--chip", choices=sorted(CHIPS), default="p3roc")
    ap.add_argument("--balls", type=int, help="balls in the trough (default numBalls)")
    ap.add_argument("--active", default="", help="more switches active at start")
    ap.add_argument("--closed", default="", help="switches whose contacts start closed")
    ap.add_argument("--dmd-fps", type=float, default=60.0)
    ap.add_argument("--bridge", help="a Visual Pinball table's folder (vpxhw.state, vpxsw.input)")
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    machine = Machine(a.yaml, a.machine_type)
    active = [machine.resolve(w) for w in parse_list(a.active)]
    closed = [machine.resolve(w) for w in parse_list(a.closed)]
    fpga = Fpga(a.chip, machine, machine.initial_closed(a.balls, active, closed),
                dmd_fps=a.dmd_fps)
    with open(os.path.join(a.dir, "prochw.log"), "a") as log:
        Daemon(a.dir, fpga, log, a.bridge).run()


if __name__ == "__main__":
    main()
