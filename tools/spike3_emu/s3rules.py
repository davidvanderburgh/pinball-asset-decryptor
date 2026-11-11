#!/usr/bin/env python3
"""s3rules.py - the coils a node board fires ITSELF, by the game's rules (PAD-1134).

On the machine the game never fires a flipper: at ball start it hands the
node board each flipper's, slingshot's and pop bumper's firing rule (cmd 41,
Spike 2's frame, masked on Spike 3's bus - s3bridge.unmask) and the BOARD
fires the coil the moment the rule's switch closes. The game sends nothing
per flip. So without this a Spike 3 run's flipper buttons reached the game
(every tap scanned) and no flipper ever moved.

THE RULE FRAME, read off the wire (pokemon_le 0.82.0, every field below
named by the game's own device table, s3nodes.devices). data[] is the
unmasked frame from the command byte on, 49 bytes; with the raw node address
and the byte count it sums to 0 mod 256 like every node frame:

  [0]      0x41
  [1]      coil index
  [2]      pulse power (n/255); 0 = rule cleared, the coil is dead
  [3..4]   pulse time, u16 board ticks (100 a second - the tick rate the
           node claims, s3nodes.HWID; the 14-byte cmd 40 uses the same)
  [5]      hold power (0 = pulse only)
  [6..7]   hold ticks (3 on both flippers; the hold itself lasts while the
           switch is held, so it is not modelled as a time)
  [24]     0x40 | the input whose closing fires the coil
  [27]     0x40 | a second input: on both flippers their EOS switch
  [28]     0x40 | the input that STOPS a motor run (a cam motor: no [24];
           the short cmd 40 starts it, [3..4] is then its time limit)

  RIGHT FLIPPER  n8 #0  f5 / 4 ticks, hold 1e  in 24 RIGHT FLIPPER BUTTON, EOS 31
  LEFT FLIPPER   n8 #5  f5 / 4 ticks, hold 1e  in 25 LEFT FLIPPER BUTTON,  EOS 16
  RIGHT SLING    n8 #2  cc / 3 ticks           in 29 RIGHT SLINGSHOT
  LEFT SLING     n8 #3  cc / 3 ticks           in 30 LEFT SLINGSHOT
  TOP POP        n9 #2  f5 / 2 ticks           in 28 TOP POP BUMPER
  BOTTOM POP     n9 #4  eb / 2 ticks           in 30 BOT POP BUMPER
  BALLOON MOTOR  n9 #7  5a / 1000 ticks        stop 24 MEOWTH UP (or 25 DOWN)

Spike 2's hwshim reads the same offsets (coil_rule_note: power p[4], input
p[26]; coil_motor_note: stop p[30] - its frames carry the address and count
in front). The node firmware (the card's pinnode .hex) is encrypted, so the
wire is the only source; the board's behaviour below is the plain reading of
the fields: a CLOSING edge of [24] fires the pulse, a hold follows while the
switch stays closed, and the coil drops when it opens. A cleared rule drops
a held coil. The game arms the rules at ball start and clears them at game
over, so a flipper is live exactly when the machine's would be.

THE PHYSICAL SIDE, as s3balls models the trough: a flipper whose rule names
a second input closes that input (its EOS switch) while the bat is up - from
the end of the pulse until the button is let go - as a flipper does. A ruled
motor run (short cmd 40) opens the stop switch it is sitting on and closes
the one its rule names PAD_MOTOR_MS (600, Spike 2's) later, unless the rule
is cleared first; without it pokemon_le re-tried MEOWTH BALLOON every 10 s
for ever (the rule's own 1000-tick limit) because MEOWTH UP never came.

Every fire is published through `fire(node, coil, power)` (s3leds.PadLed:
padled's fire counter, which is what the playfield window flashes) and
logged `[rule]` in bridge.log. nodesw is LOGICAL (1 = closed), as s3balls
and s3motors write it; PAD_S3_RULES=0 turns the model off.
"""
import os
import time

RULE_LEN = 49
TICKS_PER_S = 100          # s3nodes.HWID: the tick rate every node claims


def _inp(b):
    return (b & 0x3F) if b & 0x40 else None


def parse(data):
    """A cmd 41 frame (unmasked, from the command byte) as a dict, or None.
    The checksum is the caller's (s3bridge checks it with the address)."""
    if len(data) < RULE_LEN or data[0] != 0x41:
        return None
    return {"coil": data[1],
            "pwr": data[2], "pulse": data[3] | data[4] << 8,
            "hold_pwr": data[5], "hold": data[6] | data[7] << 8,
            "trig": _inp(data[24]), "eos": _inp(data[27]), "stop": _inp(data[28])}


def frame_ok(addr, data):
    """A masked node frame's checksum: address byte + count + body = 0."""
    return (addr + len(data) + sum(data)) & 0xFF == 0


def _env(name, dflt):
    try:
        v = int(os.environ.get(name, ""))
        return v if v >= 0 else dflt
    except ValueError:
        return dflt


class Rules:
    def __init__(self, sw, log=None, fire=None, clock=time.monotonic):
        self.sw, self.log, self.fire_cb, self.clock = sw, log, fire, clock
        self.on = os.environ.get("PAD_S3_RULES", "1") != "0"
        self.motor_s = _env("PAD_MOTOR_MS", 600) / 1000.0
        self.rules = {}           # (node, coil) -> parse() dict, armed only
        self.held = {}            # (node, coil) -> time the pulse ends (flipper up)
        self.prev = {}            # (node, input) -> last logical state seen
        self.motors = {}          # (node, coil) -> [at input or None, going, due]
        self.fires = 0
        self.budget = 400

    def say(self, msg):
        if self.log and self.budget > 0:
            self.budget -= 1
            t = time.time()
            self.log.write("%s.%03d # [rule] %s\n" % (
                time.strftime("%H:%M:%S", time.localtime(t)), t % 1 * 1000, msg))

    # ---- nodesw (logical, 8 bytes a node) ----
    def _get(self, node, bit):
        o = 8 * node + bit // 8
        return bool(self.sw[o] & (1 << (bit % 8)))

    def _set(self, node, bit, on):
        if bit is None or not 0 <= bit < 64 or not 0 <= node < 64:
            return
        o = 8 * node + bit // 8
        m = 1 << (bit % 8)
        v = self.sw[o]
        self.sw[o] = (v | m) if on else (v & ~m & 0xFF)

    # ---- the wire ----
    def note(self, node, data):
        """One unmasked node frame (from the command byte); the caller has
        checked its checksum. Reacts to cmd 41 and the short cmd 40."""
        if not self.on or not data:
            return
        if data[0] == 0x41:
            r = parse(data)
            if r is None:
                return
            key = (node, r["coil"])
            old = self.rules.get(key)
            if not r["pwr"]:
                if old is not None:
                    self.rules.pop(key)
                    self._drop(key, old, "rule cleared")
                    self.say("node %d coil %d: rule cleared" % key)
                m = self.motors.get(key)
                if m and m[1] is not None:
                    self.say("node %d coil %d: rule cleared before input %d - stopped" % (key + (m[1],)))
                    m[1] = None
                return
            if old == r:
                return                               # the board re-init's re-send
            self.rules[key] = r
            if old is not None:
                self._drop(key, old, None)
            if r["trig"] is not None:
                # armed with the switch already closed: no edge, no fire
                self.prev[(node, r["trig"])] = self._get(node, r["trig"])
            self.say("node %d coil %d armed: pulse %d/255 %d ms%s%s%s%s" % (
                node, r["coil"], r["pwr"], r["pulse"] * 1000 // TICKS_PER_S,
                (", hold %d/255" % r["hold_pwr"]) if r["hold_pwr"] else "",
                (", fired by input %d" % r["trig"]) if r["trig"] is not None else "",
                (", EOS input %d" % r["eos"]) if r["eos"] is not None else "",
                (", runs to input %d" % r["stop"]) if r["stop"] is not None else ""))
        elif data[0] == 0x40 and len(data) == 3:
            # the short 40: run that coil by its rule, now
            key = (node, data[1])
            r = self.rules.get(key)
            if r is None:
                return
            self._fire(key, r, "by the game (short cmd 40)")
            if r["stop"] is not None and r["trig"] is None:
                m = self.motors.setdefault(key, [None, None, 0.0])
                if m[1] == r["stop"] or (m[1] is None and m[0] == r["stop"]):
                    return                           # already there / on its way
                if m[0] is not None:
                    self._set(node, m[0], False)     # the cam leaves its stop
                m[0], m[1], m[2] = None, r["stop"], self.clock() + self.motor_s
                self.say("node %d coil %d: motor on, input %d in %d ms" % (
                    node, data[1], r["stop"], self.motor_s * 1000))

    def _fire(self, key, r, why):
        self.fires += 1
        if self.fire_cb:
            try:
                self.fire_cb(key[0], key[1], r["pwr"])
            except Exception:                                  # noqa: BLE001
                pass
        if self.fires <= 200 or self.fires % 100 == 0:
            self.say("node %d coil %d FIRED %s (pulse %d/255 %d ms%s) #%d" % (
                key[0], key[1], why, r["pwr"], r["pulse"] * 1000 // TICKS_PER_S,
                (", then hold %d/255 while held" % r["hold_pwr"]) if r["hold_pwr"] and why.startswith("input") else "",
                self.fires))

    def _drop(self, key, r, why):
        """The coil lets go: a held flipper falls, its EOS opens."""
        if key in self.held:
            self.held.pop(key)
            if r["eos"] is not None:
                self._set(key[0], r["eos"], False)
            if why:
                self.say("node %d coil %d released (%s)" % (key + (why,)))

    # ---- the board, every poll ----
    def tick(self):
        if not self.on:
            return
        now = self.clock()
        # each input's edge once, then every rule on it (two rules may share one)
        state = {}
        for (node, _), r in self.rules.items():
            if r["trig"] is not None and (node, r["trig"]) not in state:
                state[(node, r["trig"])] = self._get(node, r["trig"])
        for key, r in list(self.rules.items()):
            node, _ = key
            t = r["trig"]
            if t is None:
                continue
            cur = state[(node, t)]
            was = self.prev.get((node, t), False)
            if cur and not was:
                self._fire(key, r, "input %d closed" % t)
                if r["hold_pwr"]:
                    self.held[key] = now + r["pulse"] / float(TICKS_PER_S)
            elif was and not cur:
                self._drop(key, r, "input %d open" % t)
            if key in self.held and r["eos"] is not None and now >= self.held[key]:
                if not self._get(node, r["eos"]):
                    self._set(node, r["eos"], True)  # the bat reached the top
        self.prev.update(state)
        for key, m in self.motors.items():
            if m[1] is not None and now >= m[2]:
                self._set(key[0], m[1], True)
                self.say("node %d coil %d: motor reached its stop (input %d made)" % (key + (m[1],)))
                m[0], m[1] = m[1], None
