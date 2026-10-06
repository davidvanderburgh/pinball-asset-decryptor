#!/usr/bin/env python3
"""sppctl.py [--slot N] <request...> | --stream - the Warden board's control
protocol (tools/spooky_emu/spkwarden.py, what spkctl.py speaks) answered by a
Spooky P-ROC game's board (tools/proc_emu/prochw.py), so the virtual
playfield (spkpf.py -> tools/ap_emu/appf.py) drives Rick and Morty and Alice
Cooper exactly as it drives Beetlejuice.  ctl.sh runs this instead of
spkctl.py while the slot's P-ROC game is up.

    state               {"up": true, "switches": {n: 1 for each one made},
                         "balls": {"trough", "shooter", "in_play"},
                         "lights": {name: [r, g, b]}, "paused": bool,
                         "connected": bool}
    sw <n> <0|1>        hold / release a switch (n = the board's number,
                        sppswitches.py's table)
    tap <n> [ms]        press and release (150 ms)
    rip <n> <0|1>       flip a switch while held (a spinner spinning)
    plunge              the ball in the shooter lane goes into play
    drain               one ball back to the trough (the lane's, when no
                        other is in play)
    reset               every ball back in the trough
    pause <0|1>         freeze / resume the game (SIGSTOP, as Warden's)
    leds                {name: [r, g, b]}: every light the machine yaml wires
                        (sppswitches.py's map), from the board's LED writes

One JSON line per reply: {"ok": true} or {"err": "..."}, as Warden's.
`--serve <sock>` answers the same on a unix socket until the game ends.
"""
import json
import os
import re
import socket
import sys
import threading
import time

TROUGH = re.compile(r"^trough\d+$")


def _root(var, default):
    return os.environ.get(var, default)


class Board:
    """One line in, one line out, to prochw.py's ctl.sock."""

    def __init__(self, slot):
        self.path = os.path.join(_root("PROC_ROOT", "/var/tmp/pad_proc"),
                                 "rig%s" % slot, "ctl.sock")
        self.s = None
        self.lock = threading.Lock()

    def ask(self, line):
        with self.lock:
            if self.s is None:
                self.s = socket.socket(socket.AF_UNIX)
                self.s.settimeout(5)
                self.s.connect(self.path)
            self.s.sendall((line.strip() + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = self.s.recv(1 << 20)
                if not chunk:
                    self.s = None
                    raise OSError("the board closed the connection")
                buf += chunk
            return buf.decode().strip()


class Adapter:
    def __init__(self, board, rig):
        self.board = board
        self.rig = rig              # the Spooky P-ROC rig's folder (game.pid)
        self.ripping = set()
        self.led_map = None

    # -- the lights (PAD-405) -----------------------------------------------
    def _led_map(self):
        """name -> [board, r, g, b] outputs, sppswitches.py's (in the rig's
        switches.json: this Python has no yaml to read the machine's)."""
        if self.led_map is None:
            try:
                with open(os.path.join(self.rig, "switches.json"), encoding="utf-8") as f:
                    self.led_map = json.load(f).get("leds") or {}
            except (OSError, ValueError):
                return {}                   # not written yet: ask again
        return self.led_map

    def lights(self):
        """{name: [r, g, b]} for EVERY light the machine wires, dark ones
        too: the window lays its swatches out from the first state it gets,
        before the game has written a light."""
        leds = self._led_map()
        if not leds:
            return {}
        vals = self._json("leds")
        return {name: [int(vals.get("%d:%d" % (b, o), 0)) for o in (r, g, bl)]
                for name, (b, r, g, bl) in leds.items()}

    # -- what the board says --------------------------------------------
    def _json(self, line):
        reply = self.board.ask(line)
        if reply.startswith("err"):
            raise ValueError(reply[3:].strip())
        return json.loads(reply)

    def _game_pid(self):
        try:
            with open(os.path.join(self.rig, "game.pid")) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def paused(self):
        """Stopped = the game process is in state T (SIGSTOP)."""
        pid = self._game_pid()
        try:
            with open("/proc/%d/stat" % pid) as f:
                return f.read().rsplit(")", 1)[1].split()[0] in ("T", "t")
        except (OSError, TypeError, IndexError):
            return False

    def balls(self, sw, model):
        trough = sum(1 for name, s in sw.items() if TROUGH.match(name) and s["active"])
        shooter = 0
        if model and model.get("shooter") is not None:
            shooter = 1 if any(s["active"] for s in sw.values()
                               if s["number"] == model["shooter"]) else 0
        return {"trough": trough, "shooter": shooter,
                "in_play": max(0, (model or {}).get("in_play", 0) - shooter)}

    def state(self):
        st = self._json("state")
        sw = self._json("switches")
        made = {str(s["number"]): 1 for s in sw.values() if s["active"]}
        return {"up": True, "switches": made, "balls": self.balls(sw, st.get("balls")),
                "lights": self.lights(), "paused": self.paused(), "connected": bool(st.get("host")),
                "board": st.get("board"), "drivers": st.get("drivers"),
                "counts": st.get("counts")}

    # -- requests -------------------------------------------------------
    def _ok(self, line):
        reply = self.board.ask(line)
        if reply.startswith("err"):
            return {"err": reply[3:].strip()}
        return {"ok": True}

    def _shooter(self):
        model = self._json("balls")
        return model.get("shooter") if model else None

    def drain(self):
        model = self._json("balls")
        if not model:
            return self._ok("drain")
        sw = self._json("switches")
        b = self.balls(sw, model)
        if b["in_play"] <= 0 and not b["shooter"]:
            return {"err": "no ball in play"}
        if b["in_play"] <= 0:
            # the one ball is in the lane: it leaves the lane for the trough
            self.board.ask("sw %d 0" % model["shooter"])
        return self._ok("drain")

    def reset(self):
        sh = self._shooter()
        if sh is not None:
            self.board.ask("sw %d 0" % sh)
        for _ in range(16):
            if self.board.ask("drain").startswith("err"):
                break
        return {"ok": True}

    def pause(self, on):
        pid = self._game_pid()
        if pid:
            try:
                os.kill(pid, 19 if on else 18)          # SIGSTOP / SIGCONT
            except OSError as e:
                return {"paused": self.paused(), "err": str(e)}
            # what was done: /proc shows the stop a moment later
            return {"paused": on}
        return {"paused": self.paused()}

    def rip(self, n, on):
        if not on:
            self.ripping.discard(n)
            return {"ok": True}
        if n in self.ripping:
            return {"ok": True}
        self.ripping.add(n)
        board = Board.__new__(Board)            # its own connection: the
        board.path, board.s = self.board.path, None   # poll keeps time apart
        board.lock = threading.Lock()

        def spin():
            state = 1
            while n in self.ripping:
                try:
                    board.ask("sw %d %d" % (n, state))
                except OSError:
                    break
                state ^= 1
                time.sleep(0.06)
            try:
                board.ask("sw %d 0" % n)
            except OSError:
                pass
        threading.Thread(target=spin, daemon=True).start()
        return {"ok": True}

    def command(self, line):
        p = line.split()
        if not p:
            return {"err": "empty"}
        try:
            if p[0] == "state":
                return self.state()
            if p[0] == "leds":
                return self.lights()
            if p[0] == "plunge":
                return self._ok("plunge")
            if p[0] == "drain":
                return self.drain()
            if p[0] == "reset":
                return self.reset()
            if p[0] == "pause":
                return self.pause(len(p) > 1 and p[1] == "1")
            if p[0] in ("sw", "tap", "rip") and len(p) >= 2 and p[1].isdigit():
                n = int(p[1])
                on = len(p) < 3 or p[2] not in ("0", "off")
                if p[0] == "sw":
                    return self._ok("sw %d %d" % (n, 1 if on else 0))
                if p[0] == "rip":
                    return self.rip(n, on)
                ms = int(p[2]) if len(p) > 2 and p[2].isdigit() else 150
                return self._ok("tap %d %d" % (n, ms))
        except ValueError as e:
            return {"err": str(e)}
        return {"err": "unknown request: " + line.strip()}


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def serve(ad, path):
    """--serve <sock>: the same requests on a unix socket, one JSON line back
    for each - the Warden board's ctl.sock, which the game window's key
    listener (tools/ap_emu/gamekeys.py) speaks to on every rig.  The board's
    own socket has no pause or reset; this has.  Ends when the game does."""
    try:
        os.unlink(path)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen(4)
    srv.settimeout(1.0)

    def client(c):
        with c, c.makefile("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    reply = ad.command(line)
                except OSError as e:
                    reply = {"up": False, "err": str(e)}
                try:
                    c.sendall((json.dumps(reply) + "\n").encode())
                except OSError:
                    return
    try:
        while _alive(ad._game_pid()):
            try:
                c, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=client, args=(c,), daemon=True).start()
    finally:
        srv.close()
        try:
            os.unlink(path)
        except OSError:
            pass
    return 0


def main(argv):
    slot = os.environ.get("PAD_SLOT", "0")
    if argv[:1] == ["--slot"]:
        slot, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    rig = os.path.join(_root("SPP_ROOT", "/var/tmp/pad_spkproc"), "rig%s" % slot)
    ad = Adapter(Board(slot), rig)
    try:
        if argv[:1] == ["--serve"] and len(argv) == 2:
            return serve(ad, argv[1])
        if argv == ["--stream"]:
            for line in sys.stdin:
                if line.strip():
                    try:
                        reply = ad.command(line)
                    except OSError as e:        # the game stopped: the window
                        reply = {"up": False, "err": str(e)}    # counts misses
                    print(json.dumps(reply), flush=True)
            return 0
        reply = ad.command(" ".join(argv))
    except OSError as e:
        print("sppctl: rig %s not running (%s)" % (slot, e), file=sys.stderr)
        return 1
    print(json.dumps(reply))
    return 1 if "err" in reply else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
