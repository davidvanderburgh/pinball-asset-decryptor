#!/usr/bin/env python3
"""s3motors.py - stepper motors a node board runs itself (PAD-1090).

Spike 2's hwshim stepper model (PAD-393 / PAD-656: godzilla's building,
D&D's dragon) for the Spike 3 bridge. The frames are Spike 2's, unmasked
(s3bridge.unmask); data[] below is the frame from the command byte on:

  32 <motor> .. data[5] data[6] ..   configure (20 bytes): data[5] / data[6]
                                     = 0x40|input of the two end switches
  34 <motor> <dir>                   home: dir 1 runs to data[5]'s input,
                                     0 to data[6]'s (stepper_ends)
  31 <motor> <s16 steps> ...         a relative move
  38+motor (no payload) -> 5 bytes   status: u16 position, u16 target,
                                     flags 0x02 moving, 0x04 homed

Answered with zeros, the game homes for ever and polls the status: fallout_le
0.81's Fat Man (node 10, a TMC5041 board, PAN and TILT) held the game in its
boot - no coil ever configured, attract never reached.

The end switches are written into nodesw as LOGICAL closed (s3bridge applies
the wire polarity). PAD_STEPPER_SPS (5000) and PAD_STEPPER_TRAVEL (7500) as
on Spike 2; PAD_STEPPER=0 leaves the status unanswered (zeros).
"""
import os
import time


def _env(name, dflt):
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else dflt
    except ValueError:
        return dflt


class Stepper:
    def __init__(self, in7, in8, travel):
        self.ins = (in7, in8)
        self.home_in, self.far_in = in7, in8
        self.pos = -travel // 2              # between the switches, unknown
        self.frm = self.to = self.pos
        self.going = -1                       # -1 idle, 0 homing, 1 moving
        self.start = self.due = 0.0
        self.homed = False


class Steppers:
    def __init__(self, sw, log=None):
        self.sw, self.log = sw, log
        self.on = os.environ.get("PAD_STEPPER", "1") != "0"
        self.sps = _env("PAD_STEPPER_SPS", 5000)
        self.travel = _env("PAD_STEPPER_TRAVEL", 7500)
        self.m = {}                           # (node, motor) -> Stepper

    def say(self, msg):
        if self.log:
            self.log.write("%s # [stepper] %s\n" % (time.strftime("%H:%M:%S"), msg))

    def _set(self, node, bit, on):
        if bit is None or bit < 0 or bit >= 64:
            return
        o = 8 * node + bit // 8
        v = self.sw[o]
        self.sw[o] = (v | (1 << (bit % 8))) if on else (v & ~(1 << (bit % 8)) & 0xFF)

    def _pos(self, s):
        if s.going < 0:
            return s.pos
        now = time.time()
        if now >= s.due or s.due <= s.start:
            return s.to
        return int(s.frm + (s.to - s.frm) * (now - s.start) / (s.due - s.start))

    def _switches(self, node, s):
        pos = self._pos(s)
        moving = s.going >= 0 and time.time() < s.due
        self._set(node, s.home_in, pos == 0 and not (moving and s.frm == 0))
        far = abs(pos) >= self.travel and not (moving and abs(s.frm) >= self.travel)
        self._set(node, s.far_in, far)

    def tick(self):
        now = time.time()
        for (node, k), s in self.m.items():
            if s.going < 0 or now < s.due:
                continue
            s.pos = s.to
            if s.going == 0:
                s.homed = True
            self.say("node %d motor %d %s, position %d" % (
                node, k, "homed" if s.going == 0 else "arrived", s.pos))
            s.going = -1
            self._switches(node, s)

    def _go(self, node, k, s, going, to):
        s.frm = self._pos(s)
        s.to = to
        s.going = going
        s.start = time.time()
        s.due = s.start + max(abs(s.to - s.frm), 1) / float(self.sps)
        self._switches(node, s)
        self.say("node %d motor %d %s %d -> %d" % (node, k, "homing" if going == 0 else "move", s.frm, s.to))

    def note(self, node, data):
        """Every frame the game addresses to a node (plain)."""
        if not self.on or len(data) < 2 or data[0] not in (0x31, 0x32, 0x34):
            return
        k = data[1]
        if data[0] == 0x32:
            if len(data) < 20 or not ((data[5] | data[6]) & 0x40) or (node, k) in self.m:
                return
            in7 = data[5] & 0x3F if data[5] & 0x40 else -1
            in8 = data[6] & 0x3F if data[6] & 0x40 else -1
            s = self.m[(node, k)] = Stepper(in7, in8, self.travel)
            self._ends(s, 0)
            self.say("node %d motor %d: end inputs %d and %d" % (node, k, in7, in8))
            self._switches(node, s)
            return
        s = self.m.get((node, k))
        if s is None:
            return
        self.tick()
        if data[0] == 0x34:
            if len(data) >= 3 and self._ends(s, data[2]):
                s.going, s.homed, s.pos = -1, False, -self.travel // 2
            if s.going != 0:
                self._go(node, k, s, 0, 0)
            return
        if len(data) >= 4:                    # 31: relative steps
            steps = int.from_bytes(bytes(data[2:4]), "little", signed=True)
            if steps:
                to = self._pos(s) + steps
                lim = self.travel + 2000
                to = max(-lim, min(lim, to))
                self._go(node, k, s, 1, to)

    def _ends(self, s, direction):
        """34's direction byte picks which end is home (Spike 2 PAD-656)."""
        e = 0 if direction else 1
        if s.ins[e] < 0:
            e = 1 - e
        was = s.home_in
        s.home_in, s.far_in = s.ins[e], s.ins[1 - e]
        return was != s.home_in

    def status(self, node, k):
        """The 5-byte status for `38+k`, or None when it is not a stepper."""
        if not self.on:
            return None
        s = self.m.get((node, k))
        if s is None:
            return None
        self.tick()
        pos = self._pos(s) & 0xFFFF
        to = s.to & 0xFFFF
        flags = (0x02 if s.going >= 0 else 0) | (0x04 if s.homed else 0)
        return bytes([pos & 0xFF, pos >> 8, to & 0xFF, to >> 8, flags])


class Motor:
    def __init__(self, stops, enc):
        self.stops = stops                  # (input of 53's end, input of 54's)
        self.enc = enc                      # an encoder motor (positions)
        self.at = None                      # the input it rests on; None between
        self.going = None                   # the input it is going to
        self.due = 0.0
        self.run55 = False                  # sent to a position input by 55
        self.homed = False
        self.pos = self.frm = self.to = 0
        self.start = 0.0


class Motors:
    """Board-run motors that run to END STOPS (Spike 2's PAD-237 / PAD-249 /
    PAD-955 / PAD-971, john_wick's car, batman's turntable, Bond's jetpack):

      51 <motor> <stop53> <stop54> .. <enc1> <enc2> ..  configure; 0x40|input
      53 <motor> ..   run to stop53        54 <motor> ..   run to stop54
      55 <motor> <0x40|input> ..           run until that input is made
         (an encoder motor: 55 <motor> <s16 position> ..; 53 homes it)
      52 <motor> -> 4 bytes                status: byte 2 = 0x01 moving,
                                           0x20 arrived (a 55 run), 0x08 done

    star_wars_2025_le 0.96's Jump Ramp, Death Star and AT-AT (node 9): each
    configured and sent to a stop at boot, then 52 polled 4,000 times a
    minute for an arrival a zero reply never gave - the game never left its
    boot. A move takes PAD_MOTOR_MS (600): the input it leaves opens at once,
    the one it goes to closes on arrival (LOGICAL, in nodesw). PAD_NB_MOTOR=0
    leaves the status at zeros."""

    def __init__(self, sw, log=None):
        self.sw, self.log = sw, log
        self.on = os.environ.get("PAD_NB_MOTOR", "1") != "0"
        self.ms = _env("PAD_MOTOR_MS", 600) / 1000.0
        self.m = {}

    def say(self, msg):
        if self.log:
            self.log.write("%s # [motor] %s\n" % (time.strftime("%H:%M:%S"), msg))

    def _set(self, node, bit, on):
        if bit is None or bit < 0 or bit >= 64:
            return
        o = 8 * node + bit // 8
        v = self.sw[o]
        self.sw[o] = (v | (1 << (bit % 8))) if on else (v & ~(1 << (bit % 8)) & 0xFF)

    def tick(self):
        now = time.time()
        for (node, k), m in self.m.items():
            if m.going is None or now < m.due:
                continue
            if m.enc:
                m.pos = m.to
                if m.going == "home":
                    m.homed = True
                    self._set(node, m.stops[0], True)
                self.say("node %d motor %d %s, position %d" % (node, k, "homed" if m.going == "home" else "arrived", m.pos))
            else:
                self._set(node, m.going, True)
                m.at = m.going
                self.say("node %d motor %d arrived at input %d" % (node, k, m.at))
            m.going = None

    def note(self, node, data):
        if not self.on or len(data) < 3 or data[0] not in (0x51, 0x53, 0x54, 0x55):
            return
        k = data[1]
        if data[0] == 0x51:
            if len(data) < 4 or (node, k) in self.m:
                return
            stop = lambda b: (b & 0x3F) if b & 0x40 else None
            enc = len(data) >= 7 and bool((data[5] | data[6]) & 0x40)
            self.m[(node, k)] = Motor((stop(data[2]), stop(data[3])), enc)
            self.say("node %d motor %d: stops on inputs %s and %s%s" % (
                node, k, stop(data[2]), stop(data[3]), " (encoder)" if enc else ""))
            return
        m = self.m.get((node, k))
        if m is None:
            return
        self.tick()
        now = time.time()
        if m.enc:
            if data[0] == 0x53:
                going, to = "home", 0
            elif data[0] == 0x55 and len(data) >= 4:
                going, to = "move", int.from_bytes(bytes(data[2:4]), "little", signed=True)
            else:
                return
            if m.going == going and m.to == to:
                return
            m.frm, m.to, m.going, m.start, m.due = m.pos, to, going, now, now + self.ms
            if m.frm == 0 and to != 0:
                self._set(node, m.stops[0], False)
            return
        if data[0] == 0x55:
            if not data[2] & 0x40:
                return
            m.run55 = True
            target = data[2] & 0x3F
        else:
            target = m.stops[0 if data[0] == 0x53 else 1]
            if target is None:
                return
        if m.going == target or (m.going is None and m.at == target):
            return
        if m.going is None and m.at is not None:
            self._set(node, m.at, False)      # it leaves where it was
        m.at, m.going, m.due = None, target, now + self.ms
        self.say("node %d motor %d sent to input %d (cmd %02x)" % (node, k, target, data[0]))

    def status(self, node, k):
        """The 4-byte status for `52 <motor>`, or None when not a motor."""
        if not self.on:
            return None
        m = self.m.get((node, k))
        if m is None:
            return None
        self.tick()
        if m.enc:
            if m.going is not None:
                now = time.time()
                f = min(1.0, (now - m.start) / self.ms) if self.ms else 1.0
                pos = int(m.frm + (m.to - m.frm) * f)
            else:
                pos = m.pos
            pos &= 0xFFFF
            flags = 0x01 if m.going is not None else (0x08 if m.homed else 0)
            return bytes([pos & 0xFF, pos >> 8, flags, 0])
        if m.going is not None:
            return bytes([0, 0, 0x01, 0])
        if m.at is None:
            return bytes(4)
        return bytes([0, 0, 0x20 if m.run55 else 0x08, 0])
