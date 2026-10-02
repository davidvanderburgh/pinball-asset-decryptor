#!/usr/bin/env python3
"""spkwarden.py - the rig's Warden: Spooky's playfield controller board, on
a pty, for every Warden-era title (spktitles.py; $SPK_TITLE picks one).
For a Pinotaur title (Halloween) it serves spkpinotaur.py's board instead,
through the same pty, control socket and logs.

    spkwarden.py <rig dir>

Makes a pty, writes its slave path to <rig>/warden.tty (run_game.sh hands it
to the game as SPK_WARDEN; spkshim.so maps /dev/WARDEN onto it), then serves
the board until it is killed.

The wire protocol (Beetlejuice's and Scooby-Doo's Warden.cs, Texas
Chainsaw's and Evil Dead's warden.cs, Looney Tunes' warden.gd - the same
firmware; every argument count below is what those hosts send):

  host -> board   0x3E ('>') <opcode> <args>   a fixed count per opcode
  board -> host   0x3C ('<') 0x01 <sw>         switch went active
                  0x3C 0x00 <sw>               switch went inactive
                  0x3C 0x98 <sw> <0|1>         reply to get_switch_state
                  0x3C 0xA8 <coil> <pulse ms> <pulse pwm> <hold ms>
                       <hold pwm>              reply to get_coil_config (the
                                               Unity games' watchdog asks for
                                               coil 6: a hold pwm other than
                                               the one it configured means
                                               "the board reset", and it
                                               sends the whole config again)
                  0x3C 0x97 "WARDEN" 0x00      hardware info - the board's
                                               ping: Evil Dead and Texas
                                               Chainsaw read exactly 7 bytes
                                               and want "WARDEN", Looney
                                               Tunes asks every 2 s
                  0x3C 0x96 <text> 0x00        firmware info
                  0x3C 0xD4 <state>            stepper state (3 = idle)

The board parses every message and keeps what it says: coils (fired, held,
their configuration), LEDs (every colour form - 8-bit RRGGGBBB, 12-bit,
24-bit, palette - solid, blinking, breathing, the overlay layer), servos,
the stepper, the start/launch button lamps, 48 V and PWM, flipper and
auto-action (slingshot / pop) rules.  It reports LOGICAL switch states: the
host tells the firmware which switches are inverted (opto troughs) and the
firmware applies that.

Behaviour, just enough to play:
  * the trough starts full ("balls" of the profile); the eject coil takes a
    ball out and the shooter lane closes half a second later (Evil Dead:
    the lane its diverter servo points at); a launch coil opens its lane.
    `drain` puts a ball back.
  * a flipper button the host configured (144) fires its coil and closes its
    end-of-stroke switch while held, as the real flipper does.
  * switches that are made at rest ("rest": Texas Chainsaw's closed orbit
    diverter, Evil Dead's standing drop targets) are; a coil that lifts one
    ("holds") opens it while held, and a drop bank's reset coil ("resets")
    makes its targets' switches again.
  * a switch the host tied to a coil (146: slings, pops) fires that coil.
  * a stepper move or home finishes after a moment and reports idle.

Switch input comes over the control socket <rig>/ctl.sock, one line per
request, one JSON line per reply - the requests tools/ap_emu's game answers,
so the virtual playfield (spkpf.py, on tools/ap_emu/appf.py and the Stern
window's page) drives this board exactly as it drives an AP game:
    state               {"up": true, "switches": {n: 1 for each one made},
                         "balls": {"trough", "shooter", "in_play"},
                         "lights": {}, "paused": bool, "connected": bool,
                         and what the board keeps: "title", "key",
                         "leds_lit", "coils", "power", "lamps", "servos",
                         "stepper", "unknown_opcodes"...}
    sw <n> <0|1>        hold / release a switch
    tap <n> [ms]        press and release (150 ms)
    rip <n> <0|1>       flip a switch while held (a spinner spinning)
    plunge              press the Launch button: the game fires the ball
                        into play (or takes it as a select)
    drain               a ball in play (or in the shooter lane) to the trough
    reset               every ball back in the trough
    pause <0|1>         freeze / thaw the game (SIGSTOP / SIGCONT)
    leds                {"<n>": "rrggbb", ...} every lit LED
ctl.sh / spkctl.py and sw.py are its clients.
Everything the board does is logged to <rig>/warden.log.
"""
import json
import os
import queue
import select
import signal
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spktitles  # noqa: E402

TX, RX = 0x3E, 0x3C

# Argument bytes after <opcode>, per opcode.  An opcode not here is logged
# and skipped to the next '>'.
ARGS = {
    128: 2, 129: 1, 130: 1, 131: 2, 132: 2, 133: 1, 136: 1, 137: 0, 138: 0,
    139: 0, 140: 0, 142: 0, 143: 5, 144: 4, 145: 0, 146: 3, 147: 0, 148: 2,
    149: 3, 150: 0, 151: 0, 152: 1, 153: 2, 154: 2, 155: 1, 156: 1, 157: 3,
    159: 2, 160: 3, 161: 2, 163: 2, 164: 2, 165: 2, 166: 3, 167: 3, 168: 1,
    169: 1, 170: 1, 171: 4, 172: 1, 173: 4, 174: 1, 175: 3, 176: 2, 177: 3,
    178: 2, 179: 2, 180: 3, 181: 2, 182: 4, 183: 4, 184: 3, 185: 3, 186: 1,
    187: 1, 188: 1, 189: 2, 190: 1, 191: 3, 192: 3, 193: 3, 194: 4, 195: 4,
    196: 3, 197: 3, 198: 5, 199: 5, 200: 1, 201: 0, 205: 1, 206: 1, 207: 1,
    208: 4, 209: 4, 210: 4, 211: 0, 212: 0, 213: 0, 214: 0, 215: 0, 216: 0,
    217: 0, 218: 5, 219: 5, 224: 6,
}
# Coil messages: opcode -> how it drives the coil.
PULSE_OPS = {132, 133, 148, 149, 166}          # a pulse
HOLD_OPS = {129, 186, 187}                     # on until turned off
HARDWARE_INFO = b"WARDEN"
FIRMWARE_INFO = b"PAD rig Warden"
# Warden.cs palette_* (the high nibble of a palette byte is the colour).
PALETTE = {0: (0, 0, 0), 1: (0, 0, 255), 2: (0, 255, 0), 3: (255, 128, 0),
           4: (255, 0, 0), 5: (128, 0, 255), 6: (255, 255, 0),
           7: (255, 255, 255), 8: (0, 160, 255), 9: (96, 255, 0),
           11: (0, 255, 255)}
STEPPER_IDLE, STEPPER_MOVING, STEPPER_DISABLED, STEPPER_HOMING = 3, 2, 4, 5
SHOOTER_DELAY = 0.5
EOS_DELAY = 0.015
#: Every Warden game's Launch button - its plunger (a title's "aliases"
#: can say otherwise: Halloween's is 84).
LAUNCH_BUTTON = 85
#: The shortest press the board passes on (see set_switch).
MIN_PRESS_S = 0.12
# Linux's numbers (the tests import this on Windows, which has neither)
SIGSTOP = getattr(signal, "SIGSTOP", 19)
SIGCONT = getattr(signal, "SIGCONT", 18)
# LED messages (led_message): the layer, the mode, how the colour is sent.
LED_OVERLAY = {172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 185,
               193, 195, 197, 199, 219}
LED_MODE = {157: "blink", 175: "blink", 194: "blink", 195: "blink",
            160: "blink", 177: "blink", 218: "blink", 219: "blink",
            159: "breathe", 176: "breathe", 182: "breathe", 183: "breathe",
            196: "breathe", 197: "breathe", 163: "chirp", 164: "chirp",
            178: "chirp", 179: "chirp", 170: "rainbow", 172: "rainbow",
            184: "crossfade", 185: "crossfade"}
LED_OPS = {128, 155, 157, 159, 160, 163, 164, 167, 170, 171, 184, 192, 194,
           196, 198, 218} | LED_OVERLAY


def _keyed(d):
    """A dict with int keys, as JSON wants it."""
    return {str(k): v for k, v in sorted(d.items())}


def rgb8(v):
    """RRGGGBBB (Warden.cs set_led) -> (r, g, b)."""
    return ((v >> 6) * 85, ((v >> 3) & 7) * 255 // 7, (v & 7) * 255 // 7)


def u32(b):
    return int.from_bytes(bytes(b), "big")


class Board:
    def __init__(self, rig, pty=True, title=None):
        self.rig = rig
        self.title_key = title or os.environ.get("SPK_TITLE") or "bj"
        self.title = t = spktitles.get(self.title_key)
        self.trough = list(t["trough"])
        self.jam = t["jam"]
        self.shooter = t["shooter"]
        self.eject_coils = set(t["eject"])
        self.launch = dict(t["launch"])     # coil -> the lane it empties
        self.divert = t.get("divert")
        self.lanes = sorted(set(self.launch.values()) | {self.shooter})
        self.rest = list(t.get("rest", []))
        self.holds = dict(t.get("holds", {}))  # coil -> switch it opens
        self.resets = dict(t.get("resets", {}))  # coil -> switches it makes
        self.sets = dict(t.get("sets", {}))  # coil -> {switch: 0|1}
        self.total = t["balls"]
        self.launch_button = spktitles.aliases(self.title_key).get(
            "launch", LAUNCH_BUTTON)
        self.lock = threading.Lock()
        self.state = {}
        self.balls = self.total
        self.log = open(os.path.join(rig, "warden.log"), "a", buffering=1)
        self.master = self.slave = self.slave_path = None
        if pty:
            import tty              # POSIX only; the tests run without
            self.master, slave = os.openpty()
            tty.setraw(slave)
            self.slave_path = os.ttyname(slave)
            self.slave = slave      # keep one handle open: no EIO on reopen
        self.connected = False
        self.pend = b""
        self.unknown = {}           # opcode -> times seen
        self.coil_config = {}       # coil -> [pulse ms, pulse pwm,
        #                                     hold ms, hold pwm]
        self.coil_fired = {}        # coil -> pulses
        self.coil_held = set()
        self.hold_gen = {}          # coil -> hold count (a timed release
        #                             must not end a later hold)
        self.coil_last = []         # the last 20 (time, coil, how)
        self.leds = {}              # n -> (r, g, b), the base layer
        self.overlay = {}           # n -> (r, g, b), drawn over the base
        self.led_mode = {}          # n -> "blink" / "breathe" / ...
        self.chain = [0, 0]         # LEDs on bank 0 and bank 1
        self.flippers = {}          # button -> (high coil, low coil, eos)
        self.autoactions = {}       # switch -> (coil, delay)
        self.inverted = set()
        self.servos = {}
        self.outputs = {}           # switch output (189) -> 0|1
        self.lamps = {"start": 0, "launch": 0}
        self.power = {"48v": 0, "pwm": 0}
        self.stepper = {"state": STEPPER_IDLE, "mm": 0, "target": 0,
                        "speed": 0, "accel": 0}
        self.now_serving = None
        self.paused = False
        self.ripping = set()
        self.on_at = {}             # switch -> when it was made
        self.outq = queue.Queue()
        self._set_trough()

    def say(self, *a):
        self.log.write("%s %s\n" % (time.strftime("%H:%M:%S"),
                                    " ".join(str(x) for x in a)))

    def name(self, sw):
        return self.title["switches"].get(sw, "switch %d" % sw)

    def _set_trough(self):
        for i, sw in enumerate(self.trough):
            self.state[sw] = 1 if i < self.balls else 0
        self.state[self.jam] = 0
        for sw in self.rest:
            self.state[sw] = 1

    def send(self, data):
        """Queue a message for the game.  Only the writer thread writes: the
        game reads its replies once a frame, and a write that waits for it
        must never hold up reading the game's own stream (a late read makes
        the game's writes time out, and ten of those reset its board link)."""
        self.outq.put(bytes(data))

    def writer(self):
        while True:
            data = self.outq.get()
            try:
                os.write(self.master, data)
            except OSError as e:
                self.say("write failed", e)

    def set_switch(self, sw, on, why="", now=False):
        """A press is held at least MIN_PRESS_S unless *now*: the games
        believe a Start / menu / tilt edge only after asking the board for
        that switch again, so a click or key tap shorter than that (a
        browser's key press is 0 ms) would be dropped - a real button is
        closed for tens of milliseconds at the least."""
        wait = 0.0
        with self.lock:
            on = 1 if on else 0
            if self.state.get(sw, 0) == on:
                return
            if not on and not now:
                wait = MIN_PRESS_S - (time.monotonic() - self.on_at.get(sw, 0.0))
        if wait > 0:
            self.later(wait, self.set_switch, sw, 0, why, True)
            return
        with self.lock:
            if self.state.get(sw, 0) == on:
                return
            self.state[sw] = on
            if on:
                self.on_at[sw] = time.monotonic()
            self.send(self.switch_msg(sw, on))
        self.say("switch", sw, self.name(sw), "on" if on else "off", why)
        if on and sw in self.autoactions:
            coil, delay = self.autoactions[sw]
            self.later(delay / 1000.0, self.fire, coil, "autoaction")
        if sw in self.flippers:
            high, low, eos = self.flippers[sw]
            if on:
                self.fire(high, "flipper")
            if eos != sw and eos < 96:
                self.later(EOS_DELAY, self.set_switch, eos, on, "flipper stroke")

    def switch_msg(self, sw, on):
        """What the board sends when a switch changes."""
        return [RX, on, sw]

    def later(self, secs, fn, *a):
        t = threading.Timer(secs, fn, a)
        t.daemon = True
        t.start()

    def trough_changed(self):
        for i, sw in enumerate(self.trough):
            self.set_switch(sw, i < self.balls, "trough")

    # -- host -> board --------------------------------------------------
    def host_bytes(self, buf):
        """Take whole messages off the front of pend + buf; keep a partial
        one for the next read.  Returns what is kept."""
        buf = self.pend + bytes(buf)
        i, n = 0, len(buf)
        while i < n:
            if buf[i] != TX:
                j = buf.find(bytes([TX]), i)
                j = j if j >= 0 else n
                self.say("skipped %d byte(s) outside a message" % (j - i))
                i = j
                continue
            if i + 1 >= n:
                break
            op = buf[i + 1]
            if op not in ARGS:
                self.unknown[op] = self.unknown.get(op, 0) + 1
                if self.unknown[op] == 1:
                    self.say("unknown opcode", op)
                j = buf.find(bytes([TX]), i + 1)
                i = j if j >= 0 else n
                continue
            end = i + 2 + ARGS[op]
            if end > n:
                break
            try:
                self.message(op, list(buf[i + 2:end]))
            except Exception as e:       # never let one message stop the board
                self.say("message", op, "failed:", e)
            i = end
        self.pend = buf[i:]
        return self.pend

    def message(self, op, a):
        if op in LED_OPS:                     # most of the stream: first
            self.led_message(op, a)
        elif op == 152:                                  # get_switch_state
            with self.lock:
                self.send([RX, 152, a[0], self.state.get(a[0], 0)])
        elif op == 151:
            self.send([RX, 151] + list(HARDWARE_INFO) + [0])
        elif op == 150:
            self.send([RX, 150] + list(FIRMWARE_INFO) + [0])
        elif op == 168:                                  # get_coil_config
            cfg = self.coil_config.get(a[0], [0, 0, 0, 0])
            self.send([RX, 168, a[0]] + cfg)
        elif op == 143:
            self.coil_config[a[0]] = a[1:5]
        elif op in PULSE_OPS:
            self.fire(a[0], "pulse")
        elif op in HOLD_OPS:
            self.fire(a[0], "hold")
            self.hold(a[0], True)
        elif op == 191:                                  # pulse and hold <ms>
            ms = a[1] << 8 | a[2]
            self.fire(a[0], "hold %d ms" % ms)
            self.hold(a[0], True)
            self.later(ms / 1000.0, self.hold, a[0], False, self.hold_gen[a[0]])
        elif op == 130:
            self.hold(a[0], False)
        elif op == 131:             # set pwm: GI, flashers, holds; 0 = off
            if not a[1]:
                self.hold(a[0], False)
            elif a[0] not in self.coil_held:
                self.fire(a[0], "pwm %d" % a[1])
                self.hold(a[0], True)
        elif op == 145:
            self.coil_config.clear()
        elif op in (137, 138, 139, 140):
            what = "pwm" if op in (137, 138) else "48v"
            on = int(op in (137, 139))
            if self.power[what] != on:
                self.say("power", what, "on" if on else "off")
            self.power[what] = on
        elif op == 144:
            self.flippers[a[0]] = (a[1], a[2], a[3])
        elif op == 142:
            self.flippers.clear()
        elif op == 146:
            self.autoactions[a[0]] = (a[1], a[2])
        elif op == 147:
            self.autoactions.clear()
        elif op == 161:
            (self.inverted.add if a[1] else self.inverted.discard)(a[0])
        elif op == 188:                                  # 0 bit = lamp on
            self.lamps = {"start": int(not a[0] & 1),
                          "launch": int(not a[0] & 2)}
        elif op == 153:
            self.servos[a[0]] = a[1]
        elif op == 189:
            self.outputs[a[0]] = a[1]
        elif op == 154:
            if a[0] in (0, 1):
                self.chain[a[0]] = a[1]
        elif op == 200:
            self.now_serving = a[0]
        elif op == 201:
            self.now_serving = None
        elif 205 <= op <= 217:
            self.stepper_message(op, a)
        # else: status LEDs (136, 156), switch config, flip timeout, ...

    def led_message(self, op, a):
        layer = self.overlay if op in LED_OVERLAY else self.leds
        mode = LED_MODE.get(op, "solid")
        if op in (155, 174):                             # every LED
            first, count, col = 0, max(sum(self.chain), len(layer)), rgb8(a[0])
        elif op in (128, 181, 157, 175, 159, 176, 163, 179, 184, 185):
            first, count, col = a[0], 1, rgb8(a[1])
        elif op in (160, 177, 164, 178):
            first, count, col = a[0], 1, PALETTE.get(a[1] >> 4, (255, 255, 255))
        elif op in (167, 180):                           # 12-bit
            first, count = a[0], 1
            col = (a[1] * 17, (a[2] >> 4) * 17, (a[2] & 15) * 17)
        elif op in (170, 172):
            first, count, col = a[0], 1, (255, 255, 255)
        elif op in (171, 173, 182, 183, 218, 219):
            first, count, col = a[0], 1, (a[1], a[2], a[3])
        elif op in (192, 193, 194, 195, 196, 197):
            first, count, col = a[0], a[1], rgb8(a[2])
        elif op in (198, 199):
            first, count, col = a[0], a[1], (a[2], a[3], a[4])
        else:
            return
        for n in range(first, first + count):
            if any(col):
                layer[n] = col
                self.led_mode[n] = mode
            else:
                layer.pop(n, None)

    def stepper_message(self, op, a):
        s = self.stepper
        if op == 208:
            s["accel"] = u32(a)
        elif op == 209:
            s["speed"] = u32(a)
        elif op == 210:
            s["target"] = u32(a)
            if s["state"] != STEPPER_DISABLED:
                s["state"] = STEPPER_MOVING
                secs = abs(s["target"] - s["mm"]) / float(s["speed"] or 100)
                self.later(min(3.0, max(0.2, secs)), self.stepper_done,
                           s["target"])
        elif op == 211:
            s["state"], s["target"] = STEPPER_HOMING, 0
            self.later(1.0, self.stepper_done, 0)
        elif op == 212:
            self.send([RX, 212, s["state"]])
        elif op == 215:
            s["state"] = STEPPER_IDLE
        elif op == 216:
            s["state"] = STEPPER_DISABLED
        elif op == 217:
            s["state"] = STEPPER_IDLE
        self.say("stepper", op, a, "->", s["state"])

    def stepper_done(self, mm):
        s = self.stepper
        if s["state"] in (STEPPER_MOVING, STEPPER_HOMING) and s["target"] == mm:
            s["state"], s["mm"] = STEPPER_IDLE, mm

    def fire(self, coil, how):
        self.coil_fired[coil] = self.coil_fired.get(coil, 0) + 1
        self.coil_last.append([time.strftime("%H:%M:%S"), coil, how])
        del self.coil_last[:-20]
        self.say("coil", coil, how)
        for sw in self.resets.get(coil, ()):
            self.later(0.05, self.set_switch, sw, 1, "reset by coil %d" % coil)
        for sw, on in self.sets.get(coil, {}).items():
            self.later(0.1, self.set_switch, sw, on, "coil %d" % coil)
        if coil in self.eject_coils:
            self.eject()
        elif self.state.get(self.launch.get(coil)):
            self.later(0.1, self.set_switch, self.launch[coil], 0, "launched")

    def hold(self, coil, on, gen=None):
        """A coil held on or let go (by a timer: only the hold it timed); a
        held diverter opens its switch."""
        if gen is not None and gen != self.hold_gen.get(coil):
            return
        if on:
            self.hold_gen[coil] = self.hold_gen.get(coil, 0) + 1
            self.coil_held.add(coil)
        else:
            self.coil_held.discard(coil)
        if coil in self.holds:
            self.set_switch(self.holds[coil], not on, "coil %d" % coil)

    def feed_lane(self):
        """The shooter lane an ejected ball rolls into."""
        if not self.divert:
            return self.shooter
        servo, angle, below, above = self.divert
        return below if self.servos.get(servo, 180) < angle else above

    def eject(self):
        lane = self.feed_lane()
        if self.balls <= 0 or self.state.get(lane):
            self.say("eject: nothing to eject" if self.balls <= 0
                     else "eject: shooter lane full")
            return
        self.balls -= 1
        self.say("eject: ball to", self.name(lane) + ",", self.balls, "left")
        self.trough_changed()
        self.later(SHOOTER_DELAY, self.set_switch, lane, 1, "ball served")

    def plunge(self):
        """Press the Launch button.  The Warden games have no manual
        plunger: Launch makes the game fire its launch coil, which (fire)
        moves the ball into play, and a ball that only LEAVES the lane is
        one the game never saw launched.  So the ball stays until the game
        fires: Evil Dead takes the first Launch after Start as "this
        movie", and a ball let go by the rig then sat in its skill shot -
        after the drain it never served another (PAD-321).  With the lane
        empty the press still goes in: Scooby-Doo's character select and
        Evil Dead's movie select are confirmed with Launch.  A cabinet with
        a shooter rod too ("manual_plunger": Halloween, Ultraman) fires the
        coil only for ball saves and multiballs; there the ball goes after
        1.5 s, as a player's pull sends it."""
        full = [n for n in self.lanes if self.state.get(n)]
        self.set_switch(self.launch_button, 1, "plunge")
        self.later(0.2, self.set_switch, self.launch_button, 0, "plunge")
        if full and self.title.get("manual_plunger"):
            self.later(1.5, self.set_switch, full[0], 0, "plunged")

    def drain(self):
        if self.balls >= len(self.trough):
            return
        self.balls += 1
        self.say("drain:", self.balls, "in the trough")
        self.trough_changed()

    # -- control socket -----------------------------------------------
    def balls_state(self):
        shooter = sum(1 for n in self.lanes if self.state.get(n))
        return {"trough": self.balls, "shooter": shooter,
                "in_play": max(0, self.total - self.balls - shooter)}

    def lit(self):
        both = dict(self.leds)
        both.update(self.overlay)
        return both

    def command(self, line):
        """One control request -> its one-line JSON reply."""
        p = line.split()
        if not p:
            return json.dumps({"err": "empty"})
        if p[0] == "state":
            with self.lock:
                sw = {str(k): 1 for k, v in sorted(self.state.items()) if v}
            return json.dumps({
                "up": True, "switches": sw, "balls": self.balls_state(),
                "lights": {}, "paused": self.paused,
                "connected": self.connected,
                "title": self.title["name"], "key": self.title_key,
                "leds_lit": len(self.lit()),
                "coils": {"fired": _keyed(self.coil_fired),
                          "held": sorted(self.coil_held),
                          "configured": len(self.coil_config),
                          "last": self.coil_last[-5:]},
                "power": self.power, "lamps": self.lamps,
                "flippers": len(self.flippers),
                "autoactions": len(self.autoactions),
                "servos": _keyed(self.servos),
                "stepper": {"state": self.stepper["state"],
                            "mm": self.stepper["mm"]},
                "unknown_opcodes": _keyed(self.unknown)})
        if p[0] == "leds":
            return json.dumps({str(k): "%02x%02x%02x" % v
                               for k, v in sorted(self.lit().items())})
        if p[0] == "drain":
            b = self.balls_state()
            if b["in_play"] <= 0 and not b["shooter"]:
                return json.dumps({"err": "no ball in play"})
            if b["in_play"] <= 0:
                full = [n for n in self.lanes if self.state.get(n)]
                self.set_switch(full[0], 0, "drained", True)
            self.drain()
        elif p[0] == "plunge":
            self.plunge()
        elif p[0] == "reset":
            for n in self.lanes:
                self.set_switch(n, 0, "reset", True)
            self.balls = self.total
            self.trough_changed()
        elif p[0] == "pause":
            self.set_pause(len(p) > 1 and p[1] == "1")
            return json.dumps({"paused": self.paused})
        elif p[0] in ("sw", "tap", "rip") and len(p) >= 2 and p[1].isdigit():
            n = int(p[1])
            on = len(p) < 3 or p[2] not in ("0", "off")
            if p[0] == "sw":
                self.set_switch(n, on, "ctl")
            elif p[0] == "rip":
                self.rip(n, on)
            else:
                ms = int(p[2]) if len(p) > 2 and p[2].isdigit() else 150
                self.set_switch(n, 1, "ctl")
                self.later(ms / 1000.0, self.set_switch, n, 0, "ctl")
        else:
            return json.dumps({"err": "unknown request: " + line.strip()})
        return json.dumps({"ok": True})

    def rip(self, n, on):
        """Right-held on the playfield: the switch flips every 60 ms until
        released, as a spinning spinner does."""
        if not on:
            self.ripping.discard(n)
            return
        if n in self.ripping:
            return
        self.ripping.add(n)

        def spin():
            state = 0
            while n in self.ripping:
                state ^= 1
                self.set_switch(n, state, "rip", True)
                time.sleep(0.06)
            self.set_switch(n, 0, "rip", True)
        threading.Thread(target=spin, daemon=True).start()

    def set_pause(self, on):
        """Freeze the game itself: its pid is the rig's game.pid."""
        try:
            with open(os.path.join(self.rig, "game.pid")) as f:
                pid = int(f.read().strip())
            os.kill(pid, SIGSTOP if on else SIGCONT)
            self.paused = on
            self.say("paused" if on else "resumed")
        except (OSError, ValueError) as e:
            self.say("pause failed", e)

    def client(self, conn):
        buf = b""
        with conn:
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        reply = self.command(line.decode("utf-8", "replace"))
                    except Exception as e:      # never let a typo stop the board
                        reply = json.dumps({"err": str(e)})
                    try:
                        conn.sendall((reply + "\n").encode())
                    except OSError:
                        return

    def ctl_loop(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(path)
        os.chmod(path, 0o666)       # the app's switch window may run as root
        srv.listen(8)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.client, args=(conn,), daemon=True).start()

    def serve(self):
        while True:
            r, _, _ = select.select([self.master], [], [], 1.0)
            if not r:
                continue
            try:
                data = os.read(self.master, 1 << 16)
            except OSError:
                # EIO: nobody holds the slave but us - the game closed it
                # (or has not opened it yet).  Keep serving: it reopens.
                time.sleep(0.2)
                continue
            if data and not self.connected:
                self.connected = True
                self.say("game connected")
            self.host_bytes(data)


def main():
    rig = sys.argv[1]
    cls = Board
    if spktitles.get().get("board") == "pinotaur":
        import spkpinotaur              # Halloween's board, same plumbing
        cls = spkpinotaur.Pinotaur
    b = cls(rig)
    with open(os.path.join(rig, "warden.tty.tmp"), "w") as f:
        f.write(b.slave_path + "\n")
    os.rename(os.path.join(rig, "warden.tty.tmp"), os.path.join(rig, "warden.tty"))
    b.say("board up on", b.slave_path, "for", b.title["name"], "balls", b.balls)
    threading.Thread(target=b.writer, daemon=True).start()
    threading.Thread(target=b.ctl_loop, args=(os.path.join(rig, "ctl.sock"),),
                     daemon=True).start()
    b.serve()


if __name__ == "__main__":
    main()
