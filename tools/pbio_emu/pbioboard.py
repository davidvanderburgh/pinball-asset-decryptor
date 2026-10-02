#!/usr/bin/env python3
"""pbioboard.py - the rig's I/O board for Pinball Brothers' own-hardware
titles (Alien, and ABBA / Queen on the same electronics), on two ptys.

    pbioboard.py <rig dir>

Makes two ptys and writes their slave paths to <rig>/acm.tty and
<rig>/usb.tty; run_game.sh binds them over the game's /dev/ttyACM0 and
/dev/ttyUSB0.  pinprog opens both (115200, raw) and reads either; every
command goes to ttyACM0 and so does everything the board says.  The four
I/O boards sit behind the one USB link: 96 switches, ~410 outputs.

The wire protocol, reverse-engineered from Alien 4.0's pinprog (its debug
strings name the calls: ioboard_send, ioboard_thread, iob_initialize...):

  host -> board   0xA0|len <op> <args>    len counts the whole frame (2..31)
                  0xA0 <op> <len> <args>  the long form (len 0 in byte 0)
  board -> host   0x50|len <type> <data>  len counts the whole frame (2..7)

Flow control is by acknowledgement: the host keeps count of frames and
bytes in flight (ioboard_capacity: 250 bytes, 126 frames) and every frame it
sends is answered by exactly one board frame - an ACK (type 0x00), a NAK
(0x01: logged, counted as acked) or, for a request, its reply.  Without
them the host stalls, then restarts the link ("excessive tx queue errors").
Board frames of type 0x31 are switch changes and ack nothing:

  0x54 0x31 <sw> <1|0>    switch <sw> made / open (1 = made)

Requests (a reply copies the whole frame, header included, into the
waiting buffer):
  0x00  firmware version   -> 0x55 <t> <major> <minor> <build>   also the
        link keepalive.  Each title's profile says which: Alien 0.72 (its
        shipped fw_alien_072.uf2; 0.70 and later run the tongue motor in
        "programmed mode"), ABBA and Queen 1.03 (Queen's 103.uf2: both
        refuse anything below 1.00 - "Invalid FW version", the newer
        boards).  Nothing tries to reflash it.
  0x01  hardware version   -> 0x54 <t> <major> <minor>  (0.04, as the
        factory machine's own log says)
  0x53  read switch <sw>   -> 0x53 <t> <1|0>   (iob_initialize polls 0..95
        and checks the reply's first byte is 0x53)
Commands (ACKed): 0x14 coils enabled (game play) <0|1>; 0x4E coil request
<coil> <pull %> <pull ms> <hold %> <hold ms le16> <mode> (mode 0 =
configure, 5 = pulse, 7 = on until 0x4B); 0x4A / 0x4B coil start / stop
<coil>; 0x41..0x49 coil parameters; 0x57 switch -> coil rules (flippers,
slings); 0x61 / 0x62 GPIO on / off <out>; 0x63 GPIO pulse; 0x64 motor pulse
count; 0x34 LED <n le16> <r> <g> <b>; 0x36..0x38 LED blink / palette;
0x81 servo <out> <pos>; 0x51 / 0x52 switch reporting; 0x12 / 0x13 reset /
reboot to bootloader (logged, nothing reboots).

Behaviour, from the title's profile (pbiotitles.py):
  * the trough starts full; the eject coil moves a ball to the shooter lane
    half a second later; the launch coil empties the lane; `drain` returns
    a ball.  `plunge` presses the Launch button (Queen: both flippers).
  * a flipper button closes its end-of-stroke switch while held.
  * Alien's tongue: GPIO 6 runs the motor, GPIO 7 says forward; the rig
    moves it at the game's own rate and makes TONGUE MICRO at home and at
    full reach, which is what the game calibrates against before attract.

Control socket <rig>/ctl.sock: one request per line, one JSON line back -
the requests tools/ap_emu's game and tools/spooky_emu's board answer:
state, sw <n> <0|1>, tap <n> [ms], rip <n> <0|1>, plunge, drain, reset,
pause <0|1>, leds.  Everything is logged to <rig>/board.log.

PBIO_NAMES=1 answers the first switch poll with every switch made, so the
game prints every switch's name (pbiotitles.py's lists came from that).
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
import pbiotitles  # noqa: E402

FIRMWARE = (0, 72, 0)
HARDWARE = (0, 4)
ACK = bytes([0x52, 0x00])
T_SWITCH = 0x31
SHOOTER_DELAY = 0.5
EOS_DELAY = 0.015
MIN_PRESS_S = 0.12
NUM_SWITCHES = 96
SIGSTOP = getattr(signal, "SIGSTOP", 19)
SIGCONT = getattr(signal, "SIGCONT", 18)


def _keyed(d):
    return {str(k): v for k, v in sorted(d.items())}


def frames(buf):
    """Split host bytes into whole frames: (list of frames, bytes kept,
    bytes skipped)."""
    out, i, n, skipped = [], 0, len(buf), 0
    while i < n:
        b0 = buf[i]
        if b0 & 0xE0 != 0xA0:
            i += 1
            skipped += 1
            continue
        ln = b0 & 0x1F
        if ln == 0:
            if i + 3 > n:
                break
            ln = buf[i + 2]
        if ln < 2:
            i += 1
            skipped += 1
            continue
        if i + ln > n:
            break
        out.append(bytes(buf[i:i + ln]))
        i += ln
    return out, bytes(buf[i:]), skipped


class Board:
    def __init__(self, rig, title=None, pty=True):
        self.rig = rig
        self.title_key = title or os.environ.get("PBIO_TITLE") or "alien"
        self.title = t = pbiotitles.get(self.title_key)
        self.trough = list(t["trough"])
        self.jam = t.get("jam")
        self.shooter = t["shooter"]
        self.eject_coils = set(t["eject"])
        self.launch_coils = set(t["launch"])
        self.eos = dict(t.get("eos", {}))
        self.kickouts = dict(t.get("kickouts", {}))
        self.total = len(self.trough)
        self.balls = self.total
        self.firmware = tuple(t.get("firmware", FIRMWARE))
        self.names_mode = os.environ.get("PBIO_NAMES") == "1"
        self.lock = threading.Lock()
        self.state = {}
        self.log = open(os.path.join(rig, "board.log"), "a", buffering=1)
        self.masters = {}
        self.slaves = {}
        if pty:
            import tty
            for name in ("acm", "usb"):
                m, s = os.openpty()
                tty.setraw(s)
                self.masters[name] = m
                self.slaves[name] = (s, os.ttyname(s))
        self.pend = {"acm": b"", "usb": b""}
        self.connected = False
        self.frames_in = 0
        self.ops = {}                # opcode -> times seen
        self.coil_config = {}        # coil -> [pull %, pull ms, hold %, hold ms]
        self.coil_fired = {}
        self.coil_held = set()
        self.coil_last = []
        self.coils_enabled = 0
        self.gpio = set()
        self.gpio_pulses = {}
        self.leds = {}
        self.servos = {}
        self.rules = {}              # switch -> coils (0x57)
        self.motor = {}              # last 0x64 program
        self.paused = False
        self.ripping = set()
        self.on_at = {}
        self.outq = queue.Queue()
        tg = t.get("tongue")
        self.tongue = dict(tg, pos=0.0, at=time.monotonic()) if tg else None
        self._set_rest()

    # -- plumbing -------------------------------------------------------
    def say(self, *a):
        self.log.write("%s %s\n" % (time.strftime("%H:%M:%S"),
                                    " ".join(str(x) for x in a)))

    def name(self, sw):
        return self.title["switches"].get(sw, "switch %d" % sw)

    def _set_rest(self):
        for i, sw in enumerate(self.trough):
            self.state[sw] = 1 if i < self.balls else 0
        if self.jam is not None:
            self.state[self.jam] = 0
        for sw in self.title.get("rest", []):
            self.state[sw] = 1
        if self.tongue:
            self.state[self.tongue["switch"]] = 1

    def send(self, data):
        self.outq.put(bytes(data))

    def writer(self):
        while True:
            data = self.outq.get()
            try:
                os.write(self.masters["acm"], data)
            except OSError as e:
                self.say("write failed", e)

    def later(self, secs, fn, *a):
        t = threading.Timer(secs, fn, a)
        t.daemon = True
        t.start()

    # -- switches -------------------------------------------------------
    def set_switch(self, sw, on, why="", now=False):
        """A press lasts at least MIN_PRESS_S unless *now* (a key tap from
        a browser is 0 ms; a real button is closed for tens of ms)."""
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
            self.send([0x54, T_SWITCH, sw, on])
        self.say("switch", sw, self.name(sw), "on" if on else "off", why)
        if sw in self.eos:
            self.later(EOS_DELAY, self.set_switch, self.eos[sw], on,
                       "flipper stroke", True)
        if on and sw in self.rules:
            for c in self.rules[sw]:
                self.fire(c, "rule %d" % sw)

    def trough_changed(self):
        for i, sw in enumerate(self.trough):
            self.set_switch(sw, i < self.balls, "trough", True)

    # -- balls ----------------------------------------------------------
    def fire(self, coil, how):
        self.coil_fired[coil] = self.coil_fired.get(coil, 0) + 1
        self.coil_last = (self.coil_last + [[time.strftime("%H:%M:%S"), coil,
                                             how]])[-20:]
        if coil in self.eject_coils:
            self.eject()
        elif coil in self.launch_coils:
            if self.state.get(self.shooter):
                self.later(0.05, self.set_switch, self.shooter, 0, "launched",
                           True)
        elif coil in self.kickouts:
            made = [n for n in self.kickouts[coil] if self.state.get(n)]
            if made:
                self.later(0.05, self.set_switch, made[0], 0, "kicked out",
                           True)

    def eject(self):
        if self.balls <= 0 or self.state.get(self.shooter):
            self.say("eject: nothing to do (trough %d, shooter %d)"
                     % (self.balls, self.state.get(self.shooter, 0)))
            return
        self.balls -= 1
        self.trough_changed()
        self.later(SHOOTER_DELAY, self.set_switch, self.shooter, 1, "ejected",
                   True)

    def drain(self):
        if self.balls < self.total:
            self.balls += 1
            self.trough_changed()

    def plunge(self):
        """The Launch button - or, on a title without one (Queen), the
        buttons its profile launches with."""
        b = self.title["buttons"].get("launch")
        for sw in self.title.get("plunge", [b]):
            self.set_switch(sw, 1, "plunge")
            self.later(0.3, self.set_switch, sw, 0, "plunge")

    def balls_state(self):
        shooter = 1 if self.state.get(self.shooter) else 0
        return {"trough": self.balls, "shooter": shooter,
                "in_play": max(0, self.total - self.balls - shooter)}

    # -- the tongue (Alien) ---------------------------------------------
    def tongue_tick(self):
        tg = self.tongue
        if not tg:
            return
        now = time.monotonic()
        if tg["run"] in self.gpio:
            step = tg["rate"] * (now - tg["at"])
            p = tg["pos"] + (step if tg["forward"] in self.gpio else -step)
            tg["pos"] = max(0.0, min(float(tg["reach"]), p))
        tg["at"] = now
        made = tg["pos"] <= tg["home"] or tg["pos"] >= tg["far"]
        if made != bool(self.state.get(tg["switch"])):
            self.set_switch(tg["switch"], made, "tongue at %d" % tg["pos"], True)

    def ticker(self):
        while True:
            time.sleep(0.004)
            self.tongue_tick()

    # -- host -> board --------------------------------------------------
    def host_bytes(self, name, data):
        got, self.pend[name], skipped = frames(self.pend[name] + data)
        if skipped:
            self.say(name, "skipped %d byte(s) outside a frame" % skipped)
        for f in got:
            try:
                self.frame(f)
            except Exception as e:           # one bad frame never stops us
                self.say("frame", f.hex(" "), "failed:", e)
                self.send(ACK)

    def frame(self, f):
        op, a = f[1], f[2:]
        self.frames_in += 1
        self.ops[op] = self.ops.get(op, 0) + 1
        if op == 0x00:
            self.send([0x55, 0x20] + list(self.firmware))
            return
        if op == 0x01:
            self.send([0x54, 0x21] + list(HARDWARE))
            return
        if op == 0x53:
            sw = a[0]
            with self.lock:
                on = 1 if (self.names_mode or self.state.get(sw)) else 0
            self.send([0x53, 0x33, on])
            if self.names_mode and sw == NUM_SWITCHES - 1:
                self.names_mode = False
                self.later(1.0, self.resend_all)
            return
        self.send(ACK)
        if op == 0x34:                                   # LED
            n = a[0] | a[1] << 8
            rgb = (a[2], a[3], a[4]) if len(a) >= 5 else (0, 0, 0)
            if any(rgb):
                self.leds[n] = rgb
            else:
                self.leds.pop(n, None)
        elif op == 0x4E:                                 # coil request
            coil, mode = a[0], a[6] if len(a) > 6 else 0
            self.coil_config[coil] = [a[1], a[2], a[3], a[4] | a[5] << 8]
            if mode == 7:
                self.coil_held.add(coil)
                self.fire(coil, "on")
            elif mode:
                self.fire(coil, "pulse %d" % mode)
        elif op == 0x4A:
            self.coil_held.add(a[0])
            self.fire(a[0], "start")
        elif op == 0x4B:
            self.coil_held.discard(a[0])
        elif op in (0x61, 0x62):                         # GPIO on / off
            self.tongue_tick()
            (self.gpio.add if op == 0x61 else self.gpio.discard)(a[0])
        elif op == 0x63:
            self.gpio_pulses[a[0]] = self.gpio_pulses.get(a[0], 0) + 1
        elif op == 0x64:
            self.motor = {"out": a[0], "pulses": a[3] | a[4] << 8}
            self.say("motor", self.motor)
        elif op == 0x57:                                 # switch -> coils
            self.rules[a[0]] = [c for c in a[1:3] if c != 0xFF]
        elif op == 0x81:
            self.servos[a[0]] = a[1]
        elif op == 0x14:
            self.coils_enabled = a[0]
            self.say("coils", "enabled" if a[0] else "disabled")
        elif op in (0x12, 0x13):
            self.say("reset requested (op 0x%02x) - ignored" % op)

    def resend_all(self):
        """After a names-mode poll: tell the game the real states."""
        with self.lock:
            st = dict(self.state)
        for sw in range(NUM_SWITCHES):
            self.send([0x54, T_SWITCH, sw, 1 if st.get(sw) else 0])

    # -- control socket -------------------------------------------------
    def command(self, line):
        p = line.split()
        if not p:
            return json.dumps({"err": "empty"})
        if p[0] == "state":
            with self.lock:
                sw = {str(k): 1 for k, v in sorted(self.state.items()) if v}
                # the lit LEDs, for the virtual playfield's lights grid
                lights = {str(k): list(v) for k, v in sorted(self.leds.items())}
            return json.dumps({
                "up": True, "switches": sw, "balls": self.balls_state(),
                "lights": lights, "paused": self.paused,
                "connected": self.connected, "title": self.title["name"],
                "key": self.title_key, "frames": self.frames_in,
                "leds_lit": len(self.leds),
                "coils": {"enabled": self.coils_enabled,
                          "fired": _keyed(self.coil_fired),
                          "held": sorted(self.coil_held),
                          "configured": len(self.coil_config),
                          "last": self.coil_last[-5:]},
                "gpio": sorted(self.gpio), "servos": _keyed(self.servos),
                "tongue": round(self.tongue["pos"]) if self.tongue else None,
                "ops": {"%02x" % k: v for k, v in sorted(self.ops.items())}})
        if p[0] == "leds":
            return json.dumps({str(k): "%02x%02x%02x" % v
                               for k, v in sorted(self.leds.items())})
        if p[0] == "drain":
            b = self.balls_state()
            if b["in_play"] <= 0 and not b["shooter"]:
                return json.dumps({"err": "no ball in play"})
            if b["in_play"] <= 0:
                self.set_switch(self.shooter, 0, "drained", True)
            self.drain()
        elif p[0] == "plunge":
            self.plunge()
        elif p[0] == "reset":
            self.set_switch(self.shooter, 0, "reset", True)
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
        """Freeze pinprog and vidprog (their pids are in <rig>/game.pids)."""
        try:
            with open(os.path.join(self.rig, "game.pids")) as f:
                pids = [int(x) for x in f.read().split()]
            for pid in pids:
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
                    except Exception as e:
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
        os.chmod(path, 0o666)
        srv.listen(8)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.client, args=(conn,),
                             daemon=True).start()

    def serve(self):
        fds = {m: n for n, m in self.masters.items()}
        while True:
            r, _, _ = select.select(list(fds), [], [], 1.0)
            for m in r:
                try:
                    data = os.read(m, 1 << 16)
                except OSError:
                    time.sleep(0.2)     # EIO: the game has not opened it yet
                    continue
                if data and not self.connected:
                    self.connected = True
                    self.say("game connected")
                self.host_bytes(fds[m], data)


def main():
    rig = sys.argv[1]
    b = Board(rig)
    for name, (_, path) in b.slaves.items():
        with open(os.path.join(rig, name + ".tty.tmp"), "w") as f:
            f.write(path + "\n")
        os.rename(os.path.join(rig, name + ".tty.tmp"),
                  os.path.join(rig, name + ".tty"))
    b.say("board up for", b.title["name"], "on", b.slaves["acm"][1], "and",
          b.slaves["usb"][1], "- balls", b.balls, "firmware %d.%02d" %
          b.firmware[:2])
    for fn in (b.writer, b.ticker):
        threading.Thread(target=fn, daemon=True).start()
    threading.Thread(target=b.ctl_loop, args=(os.path.join(rig, "ctl.sock"),),
                     daemon=True).start()
    b.serve()


if __name__ == "__main__":
    main()
