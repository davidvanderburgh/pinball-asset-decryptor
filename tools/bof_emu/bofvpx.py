#!/usr/bin/env python3
"""bofvpx.py - PAD's Visual Pinball bridge for a Barrels of Fun run
(PAD-1305): a bofhw.py plugin (run_game.sh always loads it) on the same
hook any other link can use.  It gives a table two things:

1. The kit's PAD.Controller files (tools/spike2_emu/vpx/bofbridge.py reads
   them), in the hw folder beside ctl.sock:

     vpxhw.state  "BFHW": u32 magic, version, seq, flags; u8 switches[1024];
                  u8 lamps[1024 * 3]; u8 coils[1024]; u8 rules[1024]
     vpxsw.input  "BFSW": u32 magic, version, seq; 128-byte bitmap, one bit
                  per switch slot, set = closed (what the table holds)
     vpxball.off  the controller is attached: PAD's ball model stands aside

   A switch n is slot n + 1 (id 0 means "none" to the controller, and
   switch 0 is the coin slot); a driver d is slot d; an LED is slot
   place * 128 + index, place being its board's in the profile's
   led_boards.  rules[d] is the switch slot of the rule the game armed on
   driver d (0 = none), so the controller fires a flipper from the table's
   own button edge, and only while the game has it armed.

2. A line stream on TCP 127.0.0.1:<7470 + slot> (BOF_VPX_PORT sets the
   port, 0 turns it off; WSL hands a localhost port to Windows), one line
   per change, '\\n'-ended, numbers decimal:

     P <driver> <ms>                 a driver pulsed (TL:<d>,01)
     H <driver> <1|0>                a driver held on / let go (TL:03 / 02)
     A <driver> <switch> <1|0> <mode>
                                     a Neuron rule armed / disarmed: the
                                     board fires <driver> itself on
                                     <switch> (flippers: mode 56 main, 5d
                                     hold; slings and pops 10)
     R <name> <switch> <1|0> <R|F> <delay> <times>
                                     a BICS magnet / coil rule (ARM:):
                                     fired by the board on <switch>'s
                                     rising (R) or falling (F) edge
     L <name> <rrggbb>               an LED, by its leds.gd name
     M <name> <1|0>                  a BICS magnet / coil on, off
     F <name> <ms>                   a BICS flasher fired
     W <motor> <position>            a stepper moved (WORM, MOUTH, HALL)
     V <servo> <position>            a servo moved (mp@, raw board units)

   A rule's own firings are not sent: the A / R line armed it and the table
   fires it, as the real board does.  On connect the stream starts with a
   `# PAD bofvpx 1 <title> slot <n>` line and the state so far.  It takes:

     S <switch> <1|0>                set a switch
     B <0|1>                         0: the table owns the balls (PAD's ball
                                     model off while this link is connected)
     ?                               the state again
"""
import os
import socket
import struct
import time

STATE_MAGIC = 0x42464857                 # "BFHW"
INPUT_MAGIC = 0x42465357                 # "BFSW"
VERSION = 1
SLOTS = 1024
STATE_FILE = "vpxhw.state"
INPUT_FILE = "vpxsw.input"
ATTACHED_FILE = "vpxball.off"
SWITCH_BASE = 1
LEDS_PER_BOARD = 128
PORT_BASE = 7470
#: the loop's wait while a table is attached / idle, and how often the
#: block is rewritten when nobody is attached
POLL_S, IDLE_POLL_S, IDLE_WRITE_S = 0.005, 0.05, 0.5
#: how long a pulse reads on in the block (the controller polls every few ms)
MIN_PULSE_S = 0.03
#: driver modes that stay on while their switch is made, and pulse modes
HOLD_MODES = {"18", "56", "5d"}
PULSE_MODES = {"10", "30", "78"}


def pulse_ms(mode, params):
    """A DL: config's pulse length in ms (fast_stem.gd formats it hex)."""
    i = 1 if mode == "56" else 0
    try:
        return int(params[i], 16)
    except (IndexError, ValueError):
        return 30


class Driver:
    __slots__ = ("trigger", "switch", "mode", "params", "control")

    def __init__(self):
        self.trigger, self.switch, self.mode, self.params = 0x81, None, "", []
        self.control = "off"            # auto (its rule), off, on


class Bridge:
    def __init__(self, emu):
        self.emu = emu
        p = emu.profile
        self.dir = emu.root
        self.title = p.get("title", "")
        self.boards = list(p.get("led_boards") or [b.lower() for b in p.get("exp_boards", {})])
        self.led_names = p.get("leds", {})
        self.servo_names = p.get("servos", {})
        self.bics_names = p.get("bics_outputs", {})
        self.bics_flashers = p.get("bics_flashers", {})
        self.placebo = next((s["n"] for s in p.get("switches", []) if s.get("const") == "PLACEBO"), None)
        # a BICS switch index -> the switch number the game reads
        self.bics_sw = {int(v[0]): int(k) for k, v in p.get("bics_switches", {}).items()}
        self.drivers = {}
        self.armed = {}                 # driver -> (switch, mode)
        self.pulse_until = {}
        self.magnet_cfg = {}            # channel -> {"FIRE": ms, "HOLD": ms}
        self.magnet_on = {}             # channel -> serial of the fire that set it
        self.magnet_rules = {}          # channel -> [switch, edge, delay, times]
        self.flasher_ms = {}
        self.steppers = dict(emu.bics.get("pos", {}))
        self.servos = {}
        self.led_sent = {}
        self.attached = False
        self.table_held = set()
        self.first_input = True
        self.seen_input = None
        self.seq = 0
        self.last_write = float("-inf")
        self.poll_s = IDLE_POLL_S
        self.clients = {}               # socket -> {"buf": bytes, "balls_off": bool}
        self.srv = None
        self._serial = 0
        self.listen()

    # ------------------------------------------------------------ stream
    def listen(self):
        env = os.environ.get("BOF_VPX_PORT", "").strip()
        try:
            port = int(env) if env else PORT_BASE + int(os.environ.get("BOF_SLOT", "0") or 0)
        except ValueError:
            port = PORT_BASE
        if port <= 0:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(4)
            s.setblocking(False)
            self.srv = s
            self.emu.log("bofvpx: line stream on 127.0.0.1:%d" % port)
        except OSError as e:
            self.emu.log("bofvpx: no line stream on port %d (%s)" % (port, e))

    def emit(self, line):
        if not self.clients:
            return
        data = (line + "\n").encode("latin-1", "replace")
        for c in list(self.clients):
            try:
                c.sendall(data)
            except OSError:
                self.drop(c)

    def snapshot(self):
        out = ["# PAD bofvpx %d %s slot %s" % (VERSION, self.title, os.environ.get("BOF_SLOT", "0"))]
        for d, (sw, mode) in sorted(self.armed.items()):
            out.append("A %d %d 1 %s" % (d, sw, mode))
        for d, drv in sorted(self.drivers.items()):
            if drv.control == "on":
                out.append("H %d 1" % d)
        for ch, (sw, edge, delay, times) in sorted(self.magnet_rules.items()):
            out.append("R %s %d 1 %s %s %s" % (self.bics_name(ch), sw, edge, delay, times))
        for ch in sorted(self.magnet_on):
            out.append("M %s 1" % self.bics_name(ch))
        for (board, idx), rgb in sorted(self.emu.leds.items()):
            out.append("L %s %02x%02x%02x" % ((self.led_name(board, idx),) + tuple(rgb)))
        for m, pos in sorted(self.steppers.items()):
            out.append("W %s %s" % (m, pos))
        for name, pos in sorted(self.servos.items()):
            out.append("V %s %d" % (name, pos))
        return out

    def fds(self):
        return ([self.srv] if self.srv else []) + list(self.clients)

    def on_readable(self, fd):
        if fd is self.srv:
            c, _ = self.srv.accept()
            c.settimeout(0.5)
            self.clients[c] = {"buf": b"", "balls_off": False}
            try:
                c.sendall(("\n".join(self.snapshot()) + "\n").encode("latin-1", "replace"))
            except OSError:
                self.drop(c)
            return
        try:
            data = fd.recv(4096)
        except OSError:
            data = b""
        if not data:
            self.drop(fd)
            return
        st = self.clients[fd]
        st["buf"] += data
        while b"\n" in st["buf"]:
            line, _, st["buf"] = st["buf"].partition(b"\n")
            self.on_stream_line(fd, line.decode("latin-1").strip())

    def on_stream_line(self, c, line):
        w = line.split()
        if not w:
            return
        try:
            if w[0] == "S" and len(w) == 3:
                self.emu.set_switch(int(w[1]), int(w[2]), "vpx")
            elif w[0] == "B" and len(w) == 2 and w[1] in ("0", "1"):
                self.clients[c]["balls_off"] = w[1] == "0"
                self.update_ball_model()
            elif w[0] == "?":
                c.sendall(("\n".join(self.snapshot()) + "\n").encode("latin-1", "replace"))
            else:
                c.sendall(("E unknown: %s\n" % line).encode("latin-1", "replace"))
        except (ValueError, OSError) as e:
            try:
                c.sendall(("E %s\n" % e).encode("latin-1", "replace"))
            except OSError:
                self.drop(c)

    def drop(self, c):
        self.clients.pop(c, None)
        try:
            c.close()
        except OSError:
            pass
        self.update_ball_model()

    def update_ball_model(self):
        off = self.attached or any(st["balls_off"] for st in self.clients.values())
        self.emu.ball_model = not off

    # ------------------------------------------------------------- names
    def led_name(self, board, idx):
        key = "%s:%d" % (board, idx)
        return self.led_names.get(key, key)

    def bics_name(self, ch):
        return self.bics_names.get(ch, "BICS_%s" % ch)

    def led_slot(self, board, idx):
        if board in self.boards and 0 <= idx < LEDS_PER_BOARD:
            s = self.boards.index(board) * LEDS_PER_BOARD + idx
            return s if s < SLOTS else None
        return None

    # ----------------------------------------------------------- drivers
    def real_switch(self, n):
        return n is not None and n != self.placebo and 0 <= n + SWITCH_BASE < 256

    def rearm(self, d):
        drv = self.drivers[d]
        want = (drv.switch, drv.mode) if (drv.control == "auto" and self.real_switch(drv.switch)) else None
        have = self.armed.get(d)
        if want == have:
            return
        if have:
            del self.armed[d]
            self.emit("A %d %d 0 %s" % (d, have[0], have[1]))
        if want:
            self.armed[d] = want
            self.emit("A %d %d 1 %s" % (d, want[0], want[1]))

    def on_driver_config(self, d, fields):
        drv = self.drivers.setdefault(d, Driver())
        try:
            drv.trigger = int(fields[0], 16)
            drv.switch = int(fields[1], 16)
        except (IndexError, ValueError):
            return
        drv.mode = fields[2].lower() if len(fields) > 2 else ""
        drv.params = fields[3:]
        # Trigger 81 = the game drives it by TL: (armed with TL:<d>,0, as
        # every flipper, sling and pop is); 01 / 41 = live at once (Dune's
        # pain box re-sends its DL: with 01 while it plays, 81 after)
        if drv.control == "on":
            pass                        # a held driver stays held
        else:
            drv.control = "off" if drv.trigger & 0x80 else "auto"
        self.rearm(d)

    def on_driver(self, d, fields):
        drv = self.drivers.setdefault(d, Driver())
        c = (fields[0] if fields else "").strip().lstrip("0") or "0"
        was_on = drv.control == "on"
        if c == "0":
            drv.control = "auto"
        elif c == "1":
            ms = pulse_ms(drv.mode, drv.params)
            self.pulse_until[d] = time.monotonic() + max(ms / 1000.0, MIN_PULSE_S)
            self.emit("P %d %d" % (d, ms))
        elif c == "2":
            drv.control = "off"
        elif c == "3":
            drv.control = "on"
        if was_on != (drv.control == "on"):
            self.emit("H %d %d" % (d, 1 if drv.control == "on" else 0))
        self.rearm(d)

    def on_switch(self, n, active, source):
        now = time.monotonic()
        if active:
            for d, (sw, mode) in self.armed.items():
                if sw == n and mode in PULSE_MODES:
                    drv = self.drivers[d]
                    self.pulse_until[d] = now + max(pulse_ms(mode, drv.params) / 1000.0, MIN_PULSE_S)
        for ch, rule in list(self.magnet_rules.items()):
            sw, edge, _, times = rule
            if sw == n and (edge == "R") == bool(active):
                self.fire_magnet(ch, quiet=True)
                if times > 0:
                    rule[3] -= 1
                    if rule[3] == 0:
                        del self.magnet_rules[ch]
                        self.emit("R %s %d 0 %s 0 0" % (self.bics_name(ch), sw, edge))

    # -------------------------------------------------------------- LEDs
    def on_leds(self, board, changes, kind):
        for idx, r, g, b in changes:
            key = (board, idx)
            if self.led_sent.get(key) == (r, g, b):
                continue
            self.led_sent[key] = (r, g, b)
            self.emit("L %s %02x%02x%02x" % (self.led_name(board, idx), r, g, b))

    def on_exp_line(self, line):
        if not line.startswith("mp@"):
            return
        # mp@<board>:<index>,<position hex>,<time> (servos_stem.gd move)
        board, _, rest = line[3:].partition(":")
        bits = rest.split(",")
        try:
            idx, pos = int(bits[0], 16), int(bits[1], 16)
        except (IndexError, ValueError):
            return
        key = "%s:%d" % (board.lower(), idx)
        name = self.servo_names.get(key, key)
        if self.servos.get(name) != pos:
            self.servos[name] = pos
            self.emit("V %s %d" % (name, pos))

    # -------------------------------------------------------------- BICS
    def fire_magnet(self, ch, quiet=False):
        self._serial += 1
        serial = self._serial
        was = ch in self.magnet_on
        self.magnet_on[ch] = serial
        if not quiet and not was:
            self.emit("M %s 1" % self.bics_name(ch))
        cfg = self.magnet_cfg.get(ch, {})
        secs = (cfg.get("FIRE", 0) + cfg.get("HOLD", 0)) / 1000.0 or 0.5
        self.emu.after(secs, self._magnet_done, ch, serial, quiet)

    def _magnet_done(self, ch, serial, quiet):
        if self.magnet_on.get(ch) == serial:
            del self.magnet_on[ch]
            if not quiet:
                self.emit("M %s 0" % self.bics_name(ch))

    def on_bics(self, line, reply):
        cmd, _, arg = line.partition(":")
        kind, _, rest = arg.partition(" ")
        bits = [b.strip() for b in rest.split(",")]
        if cmd == "ARM" and kind in ("MAGNET", "COIL") and len(bits) >= 5:
            ch = bits[0]
            try:
                sw = self.bics_sw.get(int(bits[1]), int(bits[1]))
                delay, times = int(bits[3]), int(bits[4])
            except ValueError:
                return
            edge = "F" if bits[2].upper() == "F" else "R"
            if times == 0:
                if self.magnet_rules.pop(ch, None) is not None:
                    self.emit("R %s %d 0 %s %d 0" % (self.bics_name(ch), sw, edge, delay))
            else:
                self.magnet_rules[ch] = [sw, edge, delay, times]
                self.emit("R %s %d 1 %s %d %d" % (self.bics_name(ch), sw, edge, delay, times))
        elif cmd == "SET" and kind in ("MAGNET", "COIL") and len(bits) >= 4 and bits[2] == "TIME":
            try:
                self.magnet_cfg.setdefault(bits[0], {})[bits[1]] = int(float(bits[3]))
            except ValueError:
                pass
        elif cmd == "FIRE" and kind in ("MAGNET", "COIL") and bits[0]:
            self.fire_magnet(bits[0])
        elif cmd == "STOP" and kind in ("MAGNET", "COIL") and bits[0]:
            if self.magnet_on.pop(bits[0], None) is not None:
                self.emit("M %s 0" % self.bics_name(bits[0]))
        elif cmd == "SET" and kind == "FLASHER" and len(bits) >= 2:
            try:
                self.flasher_ms[bits[0]] = int(float(bits[1]))
            except ValueError:
                pass
        elif cmd == "FIRE" and kind == "FLASHER" and bits[0]:
            name = self.bics_flashers.get(bits[0], "FLASHER_%s" % bits[0])
            if "FAKE" not in name:      # the game's own watchdog (bics.gd send_watchdog)
                self.emit("F %s %d" % (name, self.flasher_ms.get(bits[0], 0)))
        elif cmd == "MOVE" and kind == "SERVO" and bits[0]:
            self.emit("V BICS_SERVO %s" % bits[0])
        for m, pos in self.emu.bics.get("pos", {}).items():
            if self.steppers.get(m) != pos:
                self.steppers[m] = pos
                self.emit("W %s %s" % (m, pos))

    # ------------------------------------------------------- the files
    def block(self, now):
        sw = bytearray(SLOTS)
        lamps = bytearray(SLOTS * 3)
        coils = bytearray(SLOTS)
        rules = bytearray(SLOTS)
        emu = self.emu
        for n, v in emu.switches.items():
            if v and 0 <= n + SWITCH_BASE < SLOTS:
                sw[n + SWITCH_BASE] = 1
        for (board, idx), (r, g, b) in emu.leds.items():
            s = self.led_slot(board, idx)
            if s is not None:
                lamps[s * 3:s * 3 + 3] = bytes((r & 255, g & 255, b & 255))
        for d, drv in self.drivers.items():
            if not 0 <= d < SLOTS:
                continue
            on = drv.control == "on" or self.pulse_until.get(d, 0) > now
            rule = self.armed.get(d)
            if rule:
                rules[d] = rule[0] + SWITCH_BASE
                if rule[1] in HOLD_MODES and emu.switches.get(rule[0]):
                    on = True
            if on:
                coils[d] = 1
        head = struct.pack("<4I", STATE_MAGIC, VERSION, self.seq & 0xFFFFFFFF,
                           1 if self.attached else 0)
        return head + bytes(sw) + bytes(lamps) + bytes(coils) + bytes(rules)

    def apply_input(self, data):
        if len(data) < 12 + SLOTS // 8:
            return
        magic, _, _ = struct.unpack_from("<3I", data, 0)
        if magic != INPUT_MAGIC:
            return
        bits = data[12:12 + SLOTS // 8]
        held = {i - SWITCH_BASE for i in range(SWITCH_BASE, SLOTS)
                if bits[i >> 3] >> (i & 7) & 1}
        emu = self.emu
        if self.first_input:
            # the table's trough and shooter lane, whole: PAD's full trough
            # gives way to the table's
            self.first_input = False
            for n in list(emu.trough) + ([emu.shooter] if emu.shooter is not None else []):
                emu.set_switch(n, n in held, "vpx")
        for n in sorted(held - self.table_held):
            emu.set_switch(n, 1, "vpx")
        for n in sorted(self.table_held - held):
            emu.set_switch(n, 0, "vpx")
        self.table_held = held

    def tick(self, now):
        on = os.path.exists(os.path.join(self.dir, ATTACHED_FILE))
        if on != self.attached:
            self.attached = on
            self.first_input = True
            self.table_held = set()
            self.seen_input = None
            self.poll_s = POLL_S if on else IDLE_POLL_S
            self.emu.log("bofvpx: a Visual Pinball table %s" % (
                "attached: it owns the balls" if on else "let go: PAD's ball model is back"))
            self.update_ball_model()
        if on:
            inp = os.path.join(self.dir, INPUT_FILE)
            try:
                st = os.stat(inp)
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                key = None
            if key and key != self.seen_input:
                self.seen_input = key
                try:
                    with open(inp, "rb") as f:
                        self.apply_input(f.read())
                except OSError:
                    self.seen_input = None
        if on or now - self.last_write >= IDLE_WRITE_S:
            self.seq += 1
            path = os.path.join(self.dir, STATE_FILE)
            try:
                with open(path + ".tmp", "wb") as f:
                    f.write(self.block(now))
                os.replace(path + ".tmp", path)
            except OSError as e:
                if self.seq < 3:
                    self.emu.log("bofvpx: block not written: %s" % e)
            self.last_write = now

    def on_stop(self):
        for c in list(self.clients):
            self.clients.pop(c, None)
            c.close()
        if self.srv:
            self.srv.close()


def attach(emu):
    return Bridge(emu)
