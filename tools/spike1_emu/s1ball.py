#!/usr/bin/env python3
"""The Spike 1 rig's invisible-ball keeper.

The emulator has no physical balls, so somebody has to answer the game's coil
fires with the switch changes a real ball would make.  This daemon does the
whole serve cycle:

  * holds a FULL TROUGH + a CLOSED COIN-DOOR INTERLOCK from boot (so the game
    counts its pinballs and enables the 48V coil circuits),
  * when the game fires the trough-eject / auto-plunger coils (node 1, coil
    idx 1/2 on GOT LE), moves the invisible ball trough -> shooter lane ->
    in play,
  * executes one-shot commands (coin, start button, arbitrary switch pulses,
    "drain" = put the ball back in the trough to end the current ball).

It watches the game's coil traffic by tailing the raw wire capture
(ttyS4.cap) with nodebus.WireParser — no debug log needed — and injects
switches through its OWN SwitchInput bitmap (s1auto.input), which the
responder merges with the viewer's s1sw.input (env S1_SW_AUTO), so clicking
cells in the switch window keeps working alongside the automation.

Usage (inside WSL, root — it writes the game chroot's CPU-SPI file):
  python3 s1ball.py daemon [--work /home/david/s1emu]
  python3 s1ball.py coin [N]           # pulse LEFT COIN N times (default 2)
  python3 s1ball.py start              # pulse the START button
  python3 s1ball.py plunge             # launch (serving a ball first if needed)
  python3 s1ball.py drain              # invisible ball rolls into the trough
  python3 s1ball.py ballin | ballout   # add / remove a trough ball
  python3 s1ball.py trough N|toggle    # set the trough count outright
  python3 s1ball.py svc select|plus|minus|back [SECS]   # service buttons
  python3 s1ball.py door [open|closed|toggle]           # coin door
  python3 s1ball.py press NODE:IDX [SECS]

The daemon publishes its state (trough count, ball position, door) as JSON in
s1ball.state for the switch window's ball/door widgets.

One-shots append to s1ball.cmd; the daemon consumes it.  Switch slots resolve
from the title's curated switch map (s1switches.json names + its
"_trough_coils" meta key); the built-in GOT LE constants are the fallback.
"""
import json
import os
import re
import struct
import sys
import time

from nodebus import WireParser

# ---- fallback map: GOT LE v1.37 empirical (handoff doc) --------------------
# The keeper prefers the run dir's s1switches.json (the curated per-title map
# start.sh installs): trough/shooter/START/coin slots resolve from the switch
# NAMES, and the trough-fire coils from its "_trough_coils" meta key.  These
# constants only apply when that map is missing or unparseable.
TROUGH_SLOTS = [(8, 14), (8, 13), (8, 12), (8, 11), (8, 10), (8, 9)]  # #1..#6
SHOOTER = (9, 1)
START = (1, 11)
LEFT_COIN = (1, 16)
# Coils whose fire means "the game wants a ball moved out of the trough".
# For GOT LE, (9,2) is the trough eject proper (it RETRIES until the
# shooter-lane switch closes); the node-1 idx 1/2 fires observed at game
# start are kept as belt-and-braces triggers.
TROUGH_COILS = {(1, 1), (1, 2), (9, 2)}
LAUNCH_AFTER = 2.5               # s in the shooter lane before "plunging"
ARM_WINDOW = 30.0                # s a start/drain arms the serve reaction

# CPU-SPI file bits (empirical, system-level — the same on GOT LE and
# Ghostbusters LE): 3 active-low bytes; the named bits below are the coin-door
# cluster.  Everything else in the file is DIP switches (left alone at 1).
SPI_BITS = {"select": 8, "plus": 9, "minus": 10, "back": 11, "interlock": 16}


def load_title_map(work):
    """Resolve the keeper's slots from the title's curated switch map.

    Returns (trough_slots #1..#N, shooter, start, coin, trough_coils,
    curated, mapped).  *curated* is True only when the map carries the
    "_trough_coils" meta key — the marker of a sweep-verified per-title map.
    *mapped* is True when the trough slots came from THIS title's map (named
    TROUGH switches) — holding those closed is safe even before the eject
    coils are known, so the keeper still pre-loads a full trough (the game
    would otherwise sit in "LOCATING PINBALLS"); only the coil-serve
    reactions stay off until curated.  On an UNKNOWN title the keeper keeps
    its hands off the playfield (holding another title's trough slots
    presses random switches); the GOT LE constants remain the fallback for
    the slot values themselves."""
    trough, shooter, start, coin = list(TROUGH_SLOTS), SHOOTER, START, LEFT_COIN
    coils = set(TROUGH_COILS)
    curated = False
    try:
        with open(os.path.join(work, "s1switches.json")) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return trough, shooter, start, coin, coils, curated, False
    by_digit = {}
    for key, name in raw.items():
        if key == "_trough_coils":
            try:
                coils = {(int(n), int(i)) for n, i in name}
                curated = True
            except (TypeError, ValueError):
                pass
            continue
        try:
            node_s, idx_s = key.split(",")
            slot = (int(node_s), int(idx_s))
        except (ValueError, AttributeError):
            continue
        uname = str(name).upper()
        if uname.startswith("TROUGH") and "JAM" not in uname:
            m = re.search(r"(\d+)", uname)
            if m:
                by_digit[int(m.group(1))] = slot
        elif "SHOOTER" in uname:
            shooter = slot
        elif uname == "START BUTTON":
            start = slot
        elif "LEFT COIN" in uname:
            coin = slot
    if by_digit:
        trough = [by_digit[d] for d in sorted(by_digit)]     # #1 first
    return trough, shooter, start, coin, coils, curated, bool(by_digit)

# ---- SwitchInput bitmap (mirror of nodebus.read_injected_switches) ---------
_SW_MAGIC = 0x53315357
_SW_NBYTES = 128


def pack_input(slots, seq):
    bits = bytearray(_SW_NBYTES)
    for node, idx in slots:
        slot = node * 64 + idx
        bits[slot >> 3] |= 1 << (slot & 7)
    return struct.pack("<3I", _SW_MAGIC, 1, seq & 0xFFFFFFFF) + bytes(bits)


class Keeper:
    def __init__(self, work):
        self.work = work
        self.auto_path = os.path.join(work, "s1auto.input")
        self.cmd_path = os.path.join(work, "s1ball.cmd")
        self.cap_path = os.path.join(work, "ttyS4.cap")
        (self.trough_slots, self.shooter, self.start, self.coin,
         self.trough_coils, self.curated, self.mapped) = load_title_map(work)
        # A title-mapped trough is held full even before its eject coils are
        # sweep-verified; the coil reactions alone wait for the meta key
        # (GOT-fallback coil numbers mean OTHER coils on another title).
        self.nballs = (len(self.trough_slots)
                       if (self.curated or self.mapped) else 0)
        if not self.curated:
            self.trough_coils = set()
        self.seq = 0
        self.balls = self.nballs     # balls sitting in the trough
        self.in_shooter = False
        self.launch_at = None
        self.pulses = {}             # (node,idx) -> release monotonic time
        self.coin_queue = 0          # pending coin pulses (spaced serially)
        try:                          # only consume commands queued AFTER boot
            self.cmd_pos = os.path.getsize(self.cmd_path)
        except OSError:
            self.cmd_pos = 0
        self.spi_at = 0.0
        self.spi_last = None
        self.spi_pulses = {}         # svc name -> release monotonic time
        self.door_closed = True      # interlock made = 48V/coils enabled
        self.state_path = os.path.join(work, "s1ball.state")
        self.published = None
        self.armed_until = 0.0       # serve reactions enabled until this time
        self.no_serve_until = 0.0    # grace after a launch (no double-serve)
        self.viewer_start = False    # START bit seen in the viewer's file
        self.write_state()
        self.publish()

    # -- switch output -------------------------------------------------------
    def closed_slots(self):
        slots = list(self.trough_slots[:self.balls])
        if self.in_shooter:
            slots.append(self.shooter)
        slots.extend(self.pulses)
        return slots

    def write_state(self):
        self.seq += 1
        tmp = self.auto_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(pack_input(self.closed_slots(), self.seq))
        os.replace(tmp, self.auto_path)

    def pulse(self, slot, secs=0.35):
        self.pulses[slot] = time.monotonic() + secs
        self.write_state()

    # -- CPU-SPI (coin-door cluster: interlock, service buttons) -------------
    def spi_bytes(self):
        """The 3 active-low CPU-SPI bytes for the current door + service
        state.  Door closed = interlock LOW (enables the game's 48V/coils);
        a held service pulse clears its bit."""
        val = 0xFFFFFF
        if self.door_closed:
            val &= ~(1 << SPI_BITS["interlock"])
        for name in self.spi_pulses:
            val &= ~(1 << SPI_BITS[name])
        return bytes([val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF])

    def write_spi(self, force=False):
        """Write the SPI file into the game's chroot.  The game runs chrooted
        in the per-card cache rootfs, so resolve the path through
        /proc/<pid>/root; re-resolve periodically to survive game restarts."""
        now = time.monotonic()
        data = self.spi_bytes()
        if not force and data == self.spi_last and now - self.spi_at < 5.0:
            return
        self.spi_at = now
        self.spi_last = data
        try:
            out = os.popen("ps -eo pid,comm --sort=-pcpu").read()
            pid = next(int(l.split()[0]) for l in out.splitlines()[1:]
                       if len(l.split()) > 1 and l.split()[1] == "game")
            path = "/proc/%d/root/data/s1cpusw.input" % pid
            with open(path, "wb") as f:
                f.write(data)
        except (StopIteration, OSError):
            pass                     # game not up yet; retry next round

    # -- published state (the switch window's trough panel reads this) -------
    def publish(self):
        state = {"balls": self.balls, "nballs": self.nballs,
                 "in_shooter": self.in_shooter,
                 "door_closed": self.door_closed, "curated": self.curated}
        if state == self.published:
            return
        self.published = state
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(state, f)
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    # -- coil reactions ------------------------------------------------------
    def arm(self, why):
        self.armed_until = time.monotonic() + ARM_WINDOW
        print("armed (%s)" % why, flush=True)

    def on_coil(self, node, idx, power):
        if (node, idx) not in self.trough_coils or not power:
            return
        now = time.monotonic()
        if now >= self.armed_until:
            # Disarmed trough fire = the game hunting for balls (boot audit,
            # attract ball search).  If our invisible ball is out, the search
            # "finds" it: put it back so the count heals to full.
            if self.balls < self.nballs and not self.in_shooter:
                self.balls += 1
                print("ball search: ball -> trough (%d)" % self.balls,
                      flush=True)
                self.write_state()
            return
        if (not self.in_shooter and self.balls > 0
                and now >= self.no_serve_until):
            self.balls -= 1
            self.in_shooter = True
            self.launch_at = now + LAUNCH_AFTER
            self.armed_until = now + ARM_WINDOW   # keep armed for the launch
            print("serve: ball -> shooter lane (%d left in trough)"
                  % self.balls, flush=True)
            self.write_state()

    # -- one-shot commands ---------------------------------------------------
    def run_cmd(self, line):
        parts = line.split()
        if not parts:
            return
        if parts[0] == "coin":
            n = int(parts[1]) if len(parts) > 1 else 2
            # the game counts coin EDGES, so queue separate pulses; the run
            # loop spaces them out
            self.coin_queue += n
        elif parts[0] == "start":
            self.arm("start command")
            self.pulse(self.start, 0.4)
        elif parts[0] == "arm":
            self.arm("arm command")
        elif parts[0] == "drain":
            if self.balls < self.nballs:
                self.balls += 1
                self.in_shooter = False
                self.arm("drain (next ball serve)")
                print("drain: ball -> trough (%d)" % self.balls, flush=True)
                self.write_state()
        elif parts[0] == "trough":
            if len(parts) > 1 and parts[1] == "toggle":
                self.balls = 0 if self.balls else self.nballs
            else:
                self.balls = max(0, min(self.nballs, int(parts[1])))
            self.write_state()
        elif parts[0] == "plunge":
            # mirror of the Spike 2 plunge.py semantics: launch the ball in
            # the shooter lane; if the lane is empty, serve one first.
            if not self.in_shooter and self.balls > 0:
                self.balls -= 1
                self.in_shooter = True
                print("plunge: ball -> shooter lane (%d left)" % self.balls,
                      flush=True)
                self.write_state()
            if self.in_shooter:
                self.launch_at = time.monotonic() + 0.6
                self.arm("plunge")
        elif parts[0] == "ballin":
            if self.balls < self.nballs:
                self.balls += 1
                print("ball in: trough=%d" % self.balls, flush=True)
                self.write_state()
        elif parts[0] == "ballout":
            if self.balls > 0:
                self.balls -= 1
                print("ball out: trough=%d" % self.balls, flush=True)
                self.write_state()
        elif parts[0] == "svc" and len(parts) > 1 and parts[1] in SPI_BITS:
            secs = float(parts[2]) if len(parts) > 2 else 0.35
            self.spi_pulses[parts[1]] = time.monotonic() + secs
            self.write_spi(force=True)
        elif parts[0] == "door":
            arg = parts[1] if len(parts) > 1 else "toggle"
            if arg == "toggle":
                self.door_closed = not self.door_closed
            else:
                self.door_closed = arg in ("closed", "close", "1")
            print("coin door %s" % ("closed" if self.door_closed else "OPEN"),
                  flush=True)
            self.write_spi(force=True)
        elif parts[0] == "press" and len(parts) > 1:
            node, idx = parts[1].split(":")
            secs = float(parts[2]) if len(parts) > 2 else 0.35
            self.pulse((int(node), int(idx)), secs)

    def poll_viewer_start(self):
        """Arm on a START press made in the switch window (the viewer's own
        s1sw.input file), so a game started by clicking cells still serves."""
        try:
            with open(os.path.join(self.work, "s1sw.input"), "rb") as f:
                buf = f.read()
        except OSError:
            return
        slot = self.start[0] * 64 + self.start[1]
        pressed = (len(buf) >= 12 + _SW_NBYTES
                   and bool(buf[12 + (slot >> 3)] & (1 << (slot & 7))))
        if pressed and not self.viewer_start:
            self.arm("viewer START press")
        self.viewer_start = pressed

    def poll_cmds(self):
        try:
            size = os.path.getsize(self.cmd_path)
        except OSError:
            return
        if size <= self.cmd_pos:
            return
        with open(self.cmd_path) as f:
            f.seek(self.cmd_pos)
            chunk = f.read()
            self.cmd_pos = f.tell()
        for line in chunk.splitlines():
            print("cmd:", line, flush=True)
            self.run_cmd(line)

    # -- main loop -----------------------------------------------------------
    def run(self):
        parser = WireParser()
        cap = None
        cap_pos = 0
        serial_release = 0.0
        print("s1ball keeper up: %s, trough=%d, watching %s"
              % ("curated map" if self.curated
                 else ("title-mapped trough (no _trough_coils - serve by "
                       "plunge only)" if self.mapped
                       else "NO curated map - passive (one-shot commands only)"),
                 self.balls, self.cap_path), flush=True)
        while True:
            now = time.monotonic()
            # (re)open the capture; start at EOF so old traffic is ignored
            if cap is None:
                try:
                    cap = open(self.cap_path, "rb")
                    cap.seek(0, 2)
                    cap_pos = cap.tell()
                    parser = WireParser()
                except OSError:
                    time.sleep(1.0)
                    continue
            try:
                size = os.path.getsize(self.cap_path)
            except OSError:
                size = cap_pos
            if size < cap_pos:           # rig restarted: fresh capture
                cap.close()
                cap = None
                continue
            data = cap.read(1 << 16)
            if data:
                cap_pos += len(data)
                for ev in parser.feed(data):
                    if ev[0] == "frame" and len(ev[2]) >= 3 and ev[2][0] == 0x40:
                        self.on_coil(ev[1] & 0x7F, ev[2][1], ev[2][2])
            # timed work
            changed = False
            for slot, until in list(self.pulses.items()):
                if now >= until:
                    del self.pulses[slot]
                    changed = True
            if (self.coin_queue and now >= serial_release
                    and self.coin not in self.pulses):
                self.coin_queue -= 1
                self.pulses[self.coin] = now + 0.35
                serial_release = now + 0.95
                changed = True
            if self.in_shooter and self.launch_at and now >= self.launch_at:
                self.in_shooter = False
                self.launch_at = None
                self.no_serve_until = now + 5.0
                print("launch: ball in play", flush=True)
                changed = True
            spi_changed = False
            for name, until in list(self.spi_pulses.items()):
                if now >= until:
                    del self.spi_pulses[name]
                    spi_changed = True
            if changed:
                self.write_state()
            self.write_spi(force=spi_changed)
            self.poll_viewer_start()
            self.poll_cmds()
            self.publish()
            if not data:
                time.sleep(0.03)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mode = sys.argv[1]
    work = "/home/david/s1emu"
    args = sys.argv[2:]
    if "--work" in args:
        i = args.index("--work")
        work = args[i + 1]
        del args[i:i + 2]
    if mode == "daemon":
        Keeper(work).run()
        return 0
    # one-shot: append to the command file for the daemon
    cmd_path = os.path.join(work, "s1ball.cmd")
    line = " ".join([mode] + args)
    with open(cmd_path, "a") as f:
        f.write(line + "\n")
    print("queued: %s" % line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
