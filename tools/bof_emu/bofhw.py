#!/usr/bin/env python3
"""bofhw.py - emulated FAST Neuron + expansion bus + BICS board for a
Barrels of Fun game.

The game (a native x86-64 Godot export) talks to its hardware over USB CDC
serial ports.  This daemon makes a pty for each port its title profile lists,
presents them as /dev/ttyACM0.. through bofhwshim.so (see that file for how)
and answers the protocols the game's own scripts speak:

  net   FAST Neuron, 921600           ID: CH: CN: SA: SL: DL: TL: WD:
                                      -> switch events -L:xx (active) /L:xx
  exp   FAST expansion bus            ID@<board>: then ER@/RF@/LM@ config and
                                      binary RD@/RL@ LED frames
  bics  BoF's own board (Dune's worm  ID: HOME: MOVE: POSITION: SET: FIRE: ...
        wrangler, Winchester's        replies end \\r\\n; dialect per profile
        Haunt Handler)
  audio FAST audio board (Labyrinth)  AM: AS: AV: AH: AW: - write-only

Nothing here is guessed from FAST documentation: every reply is shaped by the
parser in the title's fast_stem.gd / bics.gd (decompiled), which is the only
reader that matters.  See docs/plans/bof_emulator.md.

Control: a unix socket at <dir>/ctl.sock taking one command per line:
  sw <n> <0|1>      set a switch (logical: 1 = active)
  tap <n> [ms]      press, then release after ms (default 120)
  plunge            the ball in the shooter lane leaves it (into play)
  drain             one ball in play drains into the trough
  state             JSON: switches, balls, driver actions, board status
  leds              JSON: every LED the game has set, "<board>:<index>" -> rrggbb
  quit
"""
import argparse
import heapq
import json
import os
import re
import select
import socket
import time

NET, EXP, BICS, AUDIO = "net", "exp", "bics", "audio"

# Dune's ports; a profile without "ports" gets these.  The game matches FAST
# ports on desc containing "FAST Pinball" (desc = "<manufacturer> <product>
# <serial>") and the BICS board on hw_id containing "PID=2341:"
# (hw_id = "USB VID:PID=<idVendor>:<idProduct> SNR=<serial>").
DEFAULT_PORTS = [
    {"role": NET, "usb": "1-1", "iface": "1.0", "manufacturer": "FAST Pinball",
     "product": "Neuron", "vid": "2e8a", "pid": "1074"},
    {"role": EXP, "usb": "1-1", "iface": "1.2", "manufacturer": "FAST Pinball",
     "product": "Neuron", "vid": "2e8a", "pid": "1074"},
    {"role": BICS, "usb": "1-2", "iface": "1.0", "manufacturer": "Arduino LLC",
     "product": "Arduino Due", "vid": "2341", "pid": "003d", "alias": "bof_worm"},
]

# The BICS boards' firmware (Dune's Worm Wrangler, Winchester's Haunt Handler)
# ships inside each game update, and the game reflashes the board whenever the
# version in its ID reply is older than the one it expects ("BICS: Firmware
# older than v%s.%s.%s", then FLASH? and bossac).  A stand-in that claims a
# fixed version is "out of date" the day a build ships newer firmware, and that
# build then re-asks ID / FLASH? forever (PAD-1124: Dune 2026.11.10).  So the
# stand-in claims the version the running build ships.
BICS_FW_MARK = b"Barrel_of_Interactive_Control_Systems"
BICS_FW_VERSION = re.compile(rb"v(\d+)\.(\d+)\.(\d+)(?![\w.])")
BICS_FW_MAX_BYTES = 4 << 20


def bundled_bics_firmware(build_dir):
    """'vN.N.N' of the BICS firmware image a build ships, or None.

    The image is a small *.bin beside the game binary whose ID string holds the
    board's name; its version is the first vN.N.N after that string (Worm
    Wrangler: 'ID:Shai-Crab,Barrel_of_..._(BICS),WORM_WRANGLER,' then 'v1.0.0'),
    else the highest vN.N.N anywhere in the image."""
    if not build_dir or not os.path.isdir(build_dir):
        return None
    best = None
    for name in sorted(os.listdir(build_dir)):
        path = os.path.join(build_dir, name)
        if not name.lower().endswith(".bin") or not os.path.isfile(path):
            continue
        if os.path.getsize(path) > BICS_FW_MAX_BYTES:
            continue
        with open(path, "rb") as f:
            data = f.read()
        mark = data.find(BICS_FW_MARK)
        if mark < 0:
            continue
        m = BICS_FW_VERSION.search(data, mark, mark + 512)
        for m in [m] if m else BICS_FW_VERSION.finditer(data):
            ver = tuple(int(x) for x in m.groups())
            if best is None or ver > best:
                best = ver
    return "v%d.%d.%d" % best if best else None


def with_firmware(id_reply, version):
    """The ID reply with its last comma field (the firmware) set to version."""
    if not version or "," not in id_reply:
        return id_reply
    return id_reply.rsplit(",", 1)[0] + "," + version


NUM_SWITCH_BYTES = 16        # SA: reply covers switches 0..127
NAMED_POS = {"HOME": 0, "DOWN": 1, "FLUSH": 2, "UP": 3}


class Port:
    def __init__(self, name, spec):
        import tty      # Linux only; the tests load this module on Windows
        self.name, self.role, self.spec = name, spec["role"], spec
        self.master, slave = os.openpty()
        tty.setraw(slave)
        # Keep our own slave fd open so the master never sees EIO while the
        # game closes and reopens the port (it does, around "firmware updates").
        self.slave = slave
        self.pts = os.ttyname(slave)
        os.set_blocking(self.master, False)
        self.rx = b""
        self.tx = b""


class Emulator:
    def __init__(self, root, profile, log, bics_fw=None):
        self.root = root
        self.profile = profile
        self.bics_fw = bics_fw      # the build's own BICS firmware version
        self.logf = log
        self.t0 = time.monotonic()
        self.ports = {}
        self.switches = {}          # logical state, 1 = active
        self.reversed = {}          # from SL: mode 2
        self.drivers = {}           # DL: config lines by driver hex
        self.driver_log = []        # recent TL: actions
        self.leds = {}              # (board, index) -> (r, g, b)
        self.exp_config = []
        self.status = {"net_id": False, "configured": False, "nodes": False,
                       "exp": set(), "bics_id": False, "watchdog": 0,
                       "hardware_connected": False}
        self.timers = []
        self.seq = 0
        motors = profile.get("bics", {}).get("motors", {})
        self.bics = {"offsets": {m: list(v) for m, v in motors.items()},
                     "pos": {m: v[0] for m, v in motors.items()}}
        for n in profile.get("active_at_boot", []):
            self.switches[int(n)] = 1
        self.trough = [int(n) for n in profile.get("trough_switches", [])]
        self.shooter = profile.get("shooter_switch")
        self.in_trough = sum(1 for n in self.trough if self.switches.get(n))
        self.in_play = 0

    # ---------------------------------------------------------------- setup
    def build(self):
        dev = os.path.join(self.root, "dev")
        sysroot = os.path.join(self.root, "sys")
        os.makedirs(dev, exist_ok=True)
        for i, spec in enumerate(self.profile.get("ports", DEFAULT_PORTS)):
            name = "ttyACM%d" % i
            p = Port(name, spec)
            self.ports[p.role] = p
            self._link(os.path.join(dev, name), p.pts)
            if spec.get("alias"):
                self._link(os.path.join(dev, spec["alias"]), p.pts)
            usbdir = os.path.join(sysroot, "devices", "pci0000:00", "usb1",
                                  spec["usb"])
            ifdir = os.path.join(usbdir, "%s:%s" % (spec["usb"], spec["iface"]))
            os.makedirs(ifdir, exist_ok=True)
            for fname, key in (("manufacturer", "manufacturer"),
                               ("product", "product"), ("idVendor", "vid"),
                               ("idProduct", "pid")):
                with open(os.path.join(usbdir, fname), "w") as f:
                    f.write(spec[key] + "\n")
            with open(os.path.join(usbdir, "serial"), "w") as f:
                f.write("PAD%s\n" % spec["usb"].replace("-", ""))
            ttydir = os.path.join(sysroot, "class", "tty", name)
            os.makedirs(ttydir, exist_ok=True)
            self._link(os.path.join(ttydir, "device"),
                       os.path.relpath(ifdir, ttydir))
        self.log("ports: " + ", ".join("%s(%s)=%s" % (p.name, p.role, p.pts)
                                       for p in self.ports.values()))

    @staticmethod
    def _link(link, target):
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(target, link)

    # ---------------------------------------------------------------- utils
    def log(self, msg):
        self.logf.write("%9.3f %s\n" % (time.monotonic() - self.t0, msg))
        self.logf.flush()

    def send(self, role, data):
        if role not in self.ports:
            return
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.ports[role].tx += data

    def after(self, secs, fn, *args):
        self.seq += 1
        heapq.heappush(self.timers, (time.monotonic() + secs, self.seq, fn, args))

    # ------------------------------------------------------------- switches
    def set_switch(self, n, active, source="ctl"):
        active = 1 if active else 0
        if self.switches.get(n, 0) == active:
            return
        self.switches[n] = active
        self.log("SW %d -> %s (%s)" % (n, "active" if active else "inactive",
                                       source))
        bics_sw = self.profile.get("bics_switches", {}).get(str(n))
        if bics_sw:
            # A BICS switch: its own index, and the prefix that means active
            # on that board (they differ per switch on Winchester).
            index, on = bics_sw
            off = "-L" if on == "/L" else "/L"
            self.send(BICS, "%s:%s\r\n" % (on if active else off, index))
        else:
            self.send(NET, "%s:%02X\r" % ("-L" if active else "/L", n))

    def switch_bytes_hex(self):
        out = []
        for b in range(NUM_SWITCH_BYTES):
            v = 0
            for bit in range(8):
                n = b * 8 + bit
                phys = self.switches.get(n, 0) ^ (1 if self.reversed.get(n) else 0)
                if phys:
                    v |= 1 << bit
            out.append("%02X" % v)
        return "".join(out)

    # ----------------------------------------------------------- ball model
    # Counting, not physics: the trough reports how many balls it holds
    # (positions fill from its first switch), the shooter lane holds at most
    # one, everything else is "in play" until the user drains it.
    def layout_trough(self):
        for i, n in enumerate(self.trough):
            self.set_switch(n, i < self.in_trough, "ball")

    def trough_eject(self):
        if self.in_trough == 0 or self.shooter is None:
            return
        if self.switches.get(self.shooter):
            return          # lane occupied: the eject bounces back
        self.in_trough -= 1
        self.layout_trough()
        self.after(0.3, self.set_switch, self.shooter, 1, "ball")

    def plunge(self):
        if self.shooter is None or not self.switches.get(self.shooter):
            return False
        self.set_switch(self.shooter, 0, "ball")
        self.in_play += 1
        return True

    def drain(self):
        if self.in_play == 0 or self.in_trough >= len(self.trough):
            return False
        self.in_play -= 1
        self.in_trough += 1
        self.layout_trough()
        return True

    def on_driver(self, parts):
        try:
            drv = int(parts[0], 16)
        except ValueError:
            return
        mode = parts[1] if len(parts) > 1 else ""
        if mode not in ("01", "1"):      # one-shot pulse
            return
        if drv == self.profile.get("trough_eject_driver"):
            self.trough_eject()
        elif drv == self.profile.get("launch_driver"):
            self.after(0.1, self.plunge)

    # ------------------------------------------------------------------ NET
    def on_net_line(self, line):
        if ":" not in line:
            return
        cmd, _, arg = line.partition(":")
        if cmd == "WD":
            self.status["watchdog"] += 1
            self.send(NET, "WD:P\r")
            return
        if cmd not in ("SL", "DL", "TL"):
            self.log("NET <- %s" % line)
        if cmd == "ID":
            self.status["net_id"] = True
            # Parsed as split(" "): [1] board, [3] firmware -> the double space.
            self.send(NET, "ID:NET FP-CPU-2000  %s\r" %
                      self.profile.get("neuron_fw", "02.26"))
        elif cmd == "CH":
            self.status["configured"] = True
            self.send(NET, "CH:P\r")
        elif cmd == "CN":
            # One NN line per node board; the game matches each against its
            # node_boards list by substring and reads split(" ")[5].
            for i, board in enumerate(self.profile.get("node_boards", [])):
                self.send(NET, "NN:%02X FP-I/O-%s 00 00 00 01.10\r" % (i, board))
            self.status["nodes"] = True
        elif cmd == "SA":
            self.status["hardware_connected"] = True
            self.send(NET, "SA:%02X,%s\r" % (NUM_SWITCH_BYTES * 8,
                                             self.switch_bytes_hex()))
        elif cmd == "SL":
            parts = arg.split(",")
            try:
                self.reversed[int(parts[0], 16)] = parts[1].strip() == "2"
            except (ValueError, IndexError):
                pass
            self.send(NET, "SL:P\r")
        elif cmd == "DL":
            self.drivers[arg.split(",")[0]] = arg
            self.send(NET, "DL:P\r")
        elif cmd == "TL":
            parts = arg.split(",")
            self.driver_log.append((round(time.monotonic() - self.t0, 3), arg))
            del self.driver_log[:-200]
            self.send(NET, "TL:P\r")
            self.on_driver(parts)
        else:
            self.send(NET, "%s:P\r" % cmd)

    # ------------------------------------------------------------------ EXP
    def pump_exp(self, p):
        buf = p.rx
        while buf:
            if buf[:1] in (b"\r", b"\n"):
                buf = buf[1:]
                continue
            if buf[:3] in (b"RD@", b"RL@"):
                colon = buf.find(b":")
                if colon < 0 or len(buf) < colon + 2:
                    break
                count = buf[colon + 1]
                width = 4 if buf[:2] == b"RD" else 5
                end = colon + 2 + count * width
                if len(buf) < end:
                    break
                board = buf[3:colon].decode("latin-1")
                body = buf[colon + 2:end]
                for i in range(count):
                    e = body[i * width:(i + 1) * width]
                    self.leds[(board, e[0])] = (e[1], e[2], e[3])
                buf = buf[end:]
                continue
            cr = buf.find(b"\r")
            if cr < 0:
                break
            self.on_exp_line(buf[:cr].decode("latin-1"))
            buf = buf[cr + 1:]
        p.rx = buf

    def on_exp_line(self, line):
        if line.startswith("ID@"):
            board = line[3:].rstrip(":")
            fw = self.profile.get("exp_boards", {}).get(board)
            self.log("EXP <- %s%s" % (line, "" if fw else " (absent)"))
            if fw:          # an absent board (a topper) simply never answers
                self.status["exp"].add(board)
                self.send(EXP, "ID:EXP FP-EXP-%s  %s\r" % (board.upper(), fw))
        elif line.startswith(("ER@", "LM@", "RF@", "em@")):
            self.exp_config.append(line)
        elif line.startswith("RA@"):
            board, _, col = line[3:].partition(":")
            for key in [k for k in self.leds if k[0] == board]:
                try:
                    self.leds[key] = (int(col[0:2], 16), int(col[2:4], 16),
                                      int(col[4:6], 16))
                except ValueError:
                    pass
        elif line:
            self.log("EXP <- %s" % line)

    # ----------------------------------------------------------------- BICS
    def on_bics_line(self, line):
        if ":" not in line and not line.endswith("?"):
            return
        self.log("BICS <- %s" % line)
        dialect = self.profile.get("bics", {})
        reply = dialect.get("replies", {}).get(line)
        if reply is None:
            reply = self.bics_generic(line, dialect)
        if reply:
            self.send(BICS, reply + "\r\n")

    def bics_generic(self, line, dialect):
        cmd, _, arg = line.partition(":")
        b = self.bics
        if cmd == "ID":
            self.status["bics_id"] = True
            return with_firmware(dialect.get("id", "ID:WORM WRANGLER,PAD,EMULATED,v1.0.0"),
                                 self.bics_fw)
        if cmd.startswith("RESET"):
            return "RESET:ACK"
        if cmd.startswith("FLASH"):
            return None     # never offer a firmware update
        if cmd == "HOME":
            for m, offs in b["offsets"].items():
                b["pos"][m] = offs[0]
            return "HOME:%s,ACK" % arg
        if cmd == "MOVE" and arg.startswith("STEPPER "):
            bits = arg[8:].split(",")
            motor = bits[0]
            if motor == "ALL" and len(bits) >= 3 and bits[1].upper() not in NAMED_POS:
                targets = [("WORM", bits[1]), ("MOUTH", bits[2])]
            elif len(bits) >= 2:
                ms = list(b["pos"]) if motor == "ALL" else [motor]
                targets = [(m, bits[1]) for m in ms]
            else:
                targets = []
            for m, pos in targets:
                if m in b["pos"]:
                    idx = NAMED_POS.get(pos.upper())
                    offs = b["offsets"][m]
                    # Positions compare as STRINGS against the offsets, so a
                    # named move reports the offset string exactly.
                    b["pos"][m] = offs[idx] if idx is not None and idx < len(offs) else pos
            return "MOVE:%s,ACK" % arg
        if cmd == "POSITION":
            m = arg.split()[-1] if arg.split() else ""
            if m in b["pos"]:
                return "POSITION:STEPPER %s,%s" % (m, b["pos"][m])
            return None
        if cmd == "SET":
            if arg.startswith("OFFSETS? "):
                m = arg.split()[-1]
                if m in b["offsets"]:
                    return "SET:OFFSETS %s,%s" % (m, ",".join(b["offsets"][m]))
                return None
            if arg.startswith("OFFSET "):
                m, _, which = arg[7:].partition(",")
                idx = NAMED_POS.get(which)
                if m in b["offsets"] and idx is not None and idx < len(b["offsets"][m]):
                    b["offsets"][m][idx] = b["pos"][m]
            return "SET:%s,ACK" % arg
        if cmd in ("MOVE", "FIRE", "ARM", "STOP"):
            return "%s:%s,ACK" % (cmd, arg)
        if cmd == "SYS":
            return "SYS:OK"
        return None

    # ---------------------------------------------------------------- AUDIO
    def on_audio_line(self, line):
        self.log("AUDIO <- %s" % line)

    # ---------------------------------------------------------------- lines
    @staticmethod
    def pump_lines(p, handler):
        while b"\r" in p.rx:
            line, _, p.rx = p.rx.partition(b"\r")
            # BICS lines can arrive with a stray leading byte (seen: a space
            # before HOME:), so trim whitespace and NULs on both ends.
            line = line.strip(b" \t\n\x00").decode("latin-1")
            if line:
                handler(line)

    # -------------------------------------------------------------- control
    def state(self):
        return {
            "title": self.profile.get("title", ""),
            "switches": {str(k): v for k, v in sorted(self.switches.items()) if v},
            "reversed": sorted(k for k, v in self.reversed.items() if v),
            "balls": {"trough": self.in_trough, "in_play": self.in_play,
                      "shooter": bool(self.shooter is not None
                                      and self.switches.get(self.shooter))},
            "drivers_configured": len(self.drivers),
            "driver_log": self.driver_log[-20:],
            "leds_lit": sum(1 for v in self.leds.values() if any(v)),
            "leds_known": len(self.leds),
            "status": dict(self.status, exp=sorted(self.status["exp"])),
            "bics": self.bics,
        }

    def on_ctl(self, conn, line):
        words = line.split()
        if not words:
            return
        try:
            if words[0] == "sw":
                self.set_switch(int(words[1], 0), int(words[2]))
                conn.sendall(b"ok\n")
            elif words[0] == "tap":
                n = int(words[1], 0)
                ms = int(words[2]) if len(words) > 2 else 120
                self.set_switch(n, 1)
                self.after(ms / 1000.0, self.set_switch, n, 0, "ctl")
                conn.sendall(b"ok\n")
            elif words[0] == "plunge":
                conn.sendall(b"ok\n" if self.plunge() else b"err no ball in the shooter lane\n")
            elif words[0] == "drain":
                conn.sendall(b"ok\n" if self.drain() else b"err no ball in play\n")
            elif words[0] == "state":
                conn.sendall((json.dumps(self.state()) + "\n").encode())
            elif words[0] == "leds":
                conn.sendall((json.dumps({"%s:%d" % k: "%02x%02x%02x" % v
                                          for k, v in self.leds.items()})
                              + "\n").encode())
            elif words[0] == "quit":
                conn.sendall(b"bye\n")
                raise SystemExit(0)
            else:
                conn.sendall(b"err unknown command\n")
        except (ValueError, IndexError) as e:
            conn.sendall(("err %s\n" % e).encode())

    # ----------------------------------------------------------------- loop
    def run(self):
        ctl_path = os.path.join(self.root, "ctl.sock")
        if os.path.exists(ctl_path):
            os.unlink(ctl_path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(ctl_path)
        os.chmod(ctl_path, 0o666)
        srv.listen(8)
        srv.setblocking(False)
        clients = {}
        by_fd = {p.master: p for p in self.ports.values()}
        handlers = {NET: lambda p: self.pump_lines(p, self.on_net_line),
                    EXP: self.pump_exp,
                    BICS: lambda p: self.pump_lines(p, self.on_bics_line),
                    AUDIO: lambda p: self.pump_lines(p, self.on_audio_line)}
        with open(os.path.join(self.root, "bofhw.pid"), "w") as f:
            f.write(str(os.getpid()))
        self.log("ready")
        while True:
            now = time.monotonic()
            while self.timers and self.timers[0][0] <= now:
                _, _, fn, args = heapq.heappop(self.timers)
                try:
                    fn(*args)
                except Exception as e:      # noqa: BLE001
                    self.log("ERROR in timer %s: %r" % (fn.__name__, e))
            timeout = 0.05
            if self.timers:
                timeout = max(0.0, min(timeout, self.timers[0][0] - now))
            rlist = [srv] + list(by_fd) + list(clients)
            wlist = [p.master for p in self.ports.values() if p.tx]
            r, w, _ = select.select(rlist, wlist, [], timeout)
            for fd in w:
                p = by_fd[fd]
                try:
                    n = os.write(fd, p.tx)
                    p.tx = p.tx[n:]
                except BlockingIOError:
                    pass
                except OSError:
                    p.tx = b""
            for fd in r:
                if fd is srv:
                    c, _ = srv.accept()
                    clients[c] = b""
                    continue
                if fd in clients:
                    try:
                        data = fd.recv(4096)
                    except OSError:
                        data = b""
                    if not data:
                        clients.pop(fd)
                        fd.close()
                        continue
                    clients[fd] += data
                    while b"\n" in clients[fd]:
                        line, _, clients[fd] = clients[fd].partition(b"\n")
                        try:
                            self.on_ctl(fd, line.decode().strip())
                        except OSError:
                            pass
                    continue
                p = by_fd[fd]
                try:
                    data = os.read(fd, 65536)
                except (BlockingIOError, OSError):
                    continue
                p.rx += data
                # A reply bug must never take the ports down: the game treats
                # a vanished port as unplugged hardware.
                try:
                    handlers[p.role](p)
                except Exception as e:      # noqa: BLE001 - logged, loop lives
                    self.log("ERROR handling %s: %r" % (p.role, e))
                    p.rx = b""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", required=True, help="rig dir (dev/, sys/, ctl.sock)")
    ap.add_argument("--profile", help="per-title JSON profile")
    ap.add_argument("--build", help="the game build's folder: the BICS board "
                    "claims the firmware version shipped there")
    args = ap.parse_args()
    profile = {}
    if args.profile:
        with open(args.profile) as f:
            profile = json.load(f)
    os.makedirs(args.dir, exist_ok=True)
    log = open(os.path.join(args.dir, "bofhw.log"), "a")
    bics_fw = bundled_bics_firmware(args.build)
    log.write("bundled BICS firmware: %s\n" % (bics_fw or "none found"))
    log.flush()
    emu = Emulator(args.dir, profile, log, bics_fw)
    emu.build()
    try:
        emu.run()
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
