#!/usr/bin/env python3
"""vpxprobe.py - what a running game does, by name, as it happens (PAD-1303).

    padvpx probe <title> [--for SECS] [--press NAME[=MS]]... [--only WORD]...
                 [--levels] [--no-leds] [--no-coils] [--no-switches] [--json]

For whoever builds a table: which LED is which insert, which coil the game
fires for what, and which switches PAD moves itself (the ball feed, a
script, the keyboard) only show while the game runs. This attaches to the
title's run the way the controller does (padcontroller.Rig: the app's
environment, else the rig board's run of the title) and reads the same two
blocks, then prints a line per change:

    12.345  led     1203  LEFT RAMP-R             on 255
    12.360  led     1417  (unnamed: node 4 LED 17) on 96
    12.402  coil    1033  LEFT MAGNET             fired 30 ms + hold 400 ms
    13.020  switch  1042  TROUGH 1                open    (PAD: ballfeed)

LEDs: every channel of every node, GI and unnamed ones included, on and off
(--levels: every level change, for fades). Coils: each command the game
sends, with its pulse and hold. Switches: every change in the game's merged
switch truth, with who made it (the probe, PAD's own helpers, the
keyboard, or neither - the rig itself). An attract show lights hundreds
of LEDs a second: --only keeps the parts whose name holds the word (or
whose number it is), and --no-leds leaves the lights out.

Presses: --press NAME (a switch's name, part of it, or its id) closes the
switch for 200 ms (=MS for another length), one after another a second
apart once the probe is up; a press lets go only once the game has seen
it closed (or after 3 s, said). While it runs, lines on stdin do the same:
`press NAME [MS]`, `hold NAME`, `release NAME`, `quit`.

Spike 2 runs only: a Spike 1 or Spooky run publishes one block of slots of
its own, which this does not read.
"""
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import coilmap   # noqa: E402
import padsw     # noqa: E402

LED_VAL_OFF = 20           # padled val[]: 16 nodes x 96 channels
NODES = 16
LED_N = 96
LAMP_ON = 1                # the controller's "lit" (PAD_VPX_LAMP_ON)
SW_READ = padsw.OFF_SPIN + padsw.MAX_ID
LED_READ = max(coilmap.HI_READ, coilmap.DRIVE_READ)
PRESS_MS = 200
PRESS_GAP_S = 1.0
LAND_S = 3                 # how long a press waits for the game to see it closed

#: who wrote padsw's script array last (padsw.set_source's one-letter tags)
SOURCES = {"b": "ballfeed", "a": "autoattract", "c": "coil action", "d": "switch ladder", "f": "playfield window",
           "g": "gameplay script", "h": "switch hold", "i": "switch init", "l": "plunger", "p": "switch poke",
           "r": "replay", "v": "Visual Pinball table", "x": "switch exercise"}
PROBE_SRC = "o"            # the probe's own presses


def _wanted(e, only):
    """--only: the event's name holds one of the words, or its number is one."""
    name = _norm(e.get("name") or "")
    return any((w.isdigit() and int(w) in (e["number"], e["number"] - 1000)) or (_norm(w) and _norm(w) in name)
               for w in only)


def lamp_number(node, idx):
    return 1000 + node * 100 + idx


def sol_number(node, idx):
    return 1000 + node * 16 + idx


# ------------------------------------------------------------ the names --

def names_for(machine):
    """{"leds": {(node, idx): name}, "coils": {(node, idx): name},
    "switches": {id: name}} from vpxauthor's machine."""
    leds = {}
    for g in machine.get("inserts", []):
        for key, nm in zip(g["leds"], g["names"]):
            leds[tuple(key)] = nm
    coils = {(c["node"], c["index"]): c["name"] for c in machine.get("coils", []) if c["node"] is not None}
    switches = {s["id"]: s["name"] for s in machine.get("switches", []) if s.get("id")}
    return {"leds": leds, "coils": coils, "switches": switches}


def _norm(s):
    return re.sub(r"[^A-Z0-9]+", " ", (s or "").upper()).strip()


def find_switch(names, word):
    """(id, name) for a switch named by `word` - its id, its whole name, or
    a part only one name has - else (None, why)."""
    sw = names["switches"]
    word = (word or "").strip()
    if re.match(r"^\d+$", word):
        n = int(word)
        n = n - 1000 if n >= 1000 else n
        return (n, sw.get(n, "switch %d" % n)) if n > 0 else (None, "no switch 0")
    want = _norm(word)
    exact = [(i, n) for i, n in sw.items() if _norm(n) == want]
    if exact:
        return exact[0]
    part = [(i, n) for i, n in sw.items() if want and want in _norm(n)]
    if len(part) == 1:
        return part[0]
    if not part:
        return None, "no switch is named %r" % word
    return None, "%r is %d switches: %s" % (word, len(part), ", ".join(
        "%s (%d)" % (n, i) for i, n in sorted(part)[:8]) + (", ..." if len(part) > 8 else ""))


# ------------------------------------------------------------ the diff --

def led_level(data, node, idx):
    if idx < LED_N:
        o = LED_VAL_OFF + node * LED_N + idx
        return data[o] if o < len(data) else 0
    o = coilmap.HI_OFF + node * coilmap.HI_IDX + idx - LED_N
    return data[o] if idx < LED_N + coilmap.HI_IDX and o < len(data) else 0


def _hi(data):
    return len(data) >= coilmap.HI_READ


class Probe:
    """Two snapshots in, the changes between them out, by name. The first
    snapshot is the baseline: nothing is reported for it."""

    def __init__(self, names, leds=True, coils=True, switches=True, levels=False):
        self.names = names
        self.want = {"led": leds, "coil": coils, "switch": switches}
        self.levels = levels
        self.led = None
        self.coil = None
        self.sw = None
        self.mine = {}          # switch id -> level the probe set

    def _leds(self, data):
        n_idx = LED_N + (coilmap.HI_IDX if _hi(data) else 0)
        return {(nd, ix): led_level(data, nd, ix) for nd in range(NODES) for ix in range(n_idx)}

    def _coils(self, data):
        out = {}
        if len(data) <= coilmap.COIL_OFF + NODES * 16:
            return out
        for nd in range(NODES):
            for ix in range(16):
                d = coilmap.drive(data, nd, ix)
                out[(nd, ix)] = (data[coilmap.COIL_OFF + nd * 16 + ix], d["until"] if d else 0, d)
        return out

    def step(self, led_data, sw_data, t):
        """The events between the last snapshot and this one: [{t, what,
        number, name, ...}]. Either block may be None (not readable now)."""
        ev = []
        if led_data and coilmap.has_magic(led_data):
            leds = self._leds(led_data)
            if self.led is not None and self.want["led"]:
                for key, v in leds.items():
                    was = self.led.get(key, 0)
                    if v == was:
                        continue
                    on, won = v >= LAMP_ON, was >= LAMP_ON
                    if on != won or self.levels:
                        nm = self.names["leds"].get(key)
                        ev.append({"t": t, "what": "led", "number": lamp_number(*key), "node": key[0],
                                   "index": key[1], "name": nm, "named": nm is not None,
                                   "state": "on" if on else "off", "level": v})
            self.led = leds
            coils = self._coils(led_data)
            if self.coil is not None and self.want["coil"]:
                for key, (count, until, d) in coils.items():
                    was = self.coil.get(key)
                    if was is None:
                        continue
                    e = None
                    if count != was[0] or (until and until != was[1]):
                        e = {"state": "fired", "pulse_ms": d["pulse_ms"] if d else None,
                             "hold_ms": d["hold_ms"] if d else None}
                    elif until == 0 and was[1] != 0:
                        e = {"state": "off"}
                    if e:
                        nm = self.names["coils"].get(key)
                        e.update({"t": t, "what": "coil", "number": sol_number(*key), "node": key[0],
                                  "index": key[1], "name": nm, "named": nm is not None})
                        ev.append(e)
            self.coil = coils
        if sw_data and len(sw_data) >= padsw.OFF_MRG + padsw.MAX_ID:
            mrg = sw_data[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
            if self.sw is not None and self.want["switch"]:
                for sid in range(1, padsw.MAX_ID):
                    if mrg[sid] == self.sw[sid]:
                        continue
                    nm = self.names["switches"].get(sid)
                    ev.append({"t": t, "what": "switch", "number": 1000 + sid, "id": sid, "name": nm,
                               "named": nm is not None, "state": "closed" if mrg[sid] else "open",
                               "by": self._who(sw_data, sid, mrg[sid])})
            self.sw = bytes(mrg)
        return ev

    def _who(self, sw, sid, level):
        if self.mine.get(sid) == (1 if level else 0):
            return "probe"
        scr = sw[padsw.OFF_SCR_HELD + sid] if len(sw) > padsw.OFF_SCR_HELD + sid else 0
        kbd = sw[padsw.OFF_HELD + sid] if len(sw) > padsw.OFF_HELD + sid else 0
        spin = sw[padsw.OFF_SPIN + sid] if len(sw) > padsw.OFF_SPIN + sid else 0
        if bool(scr) == bool(level):
            # the tag is the LAST writer's: the probe's own (it pressed
            # something else meanwhile) says nothing about who moved this one
            tag = chr(sw[padsw.OFF_SCR_SRC]) if len(sw) > padsw.OFF_SCR_SRC and sw[padsw.OFF_SCR_SRC] else ""
            return "PAD: %s" % SOURCES[tag] if tag in SOURCES else "PAD"
        if bool(kbd) == bool(level) and kbd:
            return "keyboard"
        if spin:
            return "PAD: spinner"
        return "rig"


def line(e):
    """One event as the probe prints it."""
    name = e["name"] if e.get("named") else "(unnamed: node %d %s %d)" % (
        e.get("node", 0), "LED" if e["what"] == "led" else "coil", e.get("index", 0)) \
        if e["what"] != "switch" else "(unnamed: switch %d)" % e["id"]
    if e["what"] == "led":
        tail = "%s %d" % (e["state"], e["level"])
    elif e["what"] == "coil":
        tail = "off" if e["state"] == "off" else "fired" + (
            " %d ms" % e["pulse_ms"] if e.get("pulse_ms") is not None else "") + (
            " + hold %d ms" % e["hold_ms"] if e.get("hold_ms") else "")
    else:
        tail = "%-7s (%s)" % (e["state"], e["by"])
    return "%9.3f  %-6s  %5d  %-28s %s" % (e["t"], e["what"], e["number"], name, tail)


# ------------------------------------------------------------ the run --

class _ProbeRig:
    """The run's Rig, with the probe's own writer tag on its switch helper
    (padsw's script source), so its presses are not taken for a table's."""

    def __init__(self, rig):
        self._rig = rig

    def __getattr__(self, k):
        return getattr(self._rig, k)

    def wsl_env(self):
        return ["PAD_SW_SRC=%s" % PROBE_SRC if e.startswith("PAD_SW_SRC=") else e for e in self._rig.wsl_env()]


def _names(title, tables_dir=None):
    import vpxauthor
    m = vpxauthor.machine_for(title, tables_dir)
    return names_for(m) if m else {"leds": {}, "coils": {}, "switches": {}}, m is not None


def run(title, seconds=None, presses=(), leds=True, coils=True, switches=True, levels=False,
        as_json=False, out=None, stdin=None, rig=None, read=None, pipe=None, interval=0.03, only=()):
    """Attach to the title's run and print what it does until `seconds` pass
    (None: until stdin says quit or is closed, or Ctrl+C). Returns 0, or 1
    with the reason when no run of the title is up."""
    import padcontroller
    out = out or sys.stdout
    names, known = _names(title)

    def say(msg):
        print(msg, file=out, flush=True)

    rig = rig or padcontroller.Rig(title)
    read = read or padcontroller.read_block
    first = read(rig.led_path(), LED_READ) if rig.dump else None
    if not first or not coilmap.has_magic(first):
        say("No run of %s is up to probe (%s): start it - `padvpx run %s`, the Emulate tab, or its table - "
            "and try again." % (title, padcontroller.block_state(first), title))
        return 1
    if not known:
        say("(no device tables for %s on this PC: parts are shown by number only)" % title)
    say("probing %s (%s, %s); Ctrl+C or `quit` ends it" % (title, rig.how, rig.dump))
    probe = Probe(names, leds, coils, switches, levels)
    pipe = pipe or padcontroller.SwitchPipe(_ProbeRig(rig))
    if presses or seconds is None or stdin is not None:
        pipe._ensure()              # swkeys starts in WSL now, not on the first press
    lock = threading.Lock()
    todo = []                       # (when, id, level, name, ms): ms = a press's hold
    landing = {}                    # id -> (name, ms, give up at): closed, not seen closed yet
    t0 = time.monotonic()
    stop = threading.Event()

    def queue_press(word, ms=PRESS_MS, at=None, level=None):
        sid, nm = find_switch(names, word)
        if sid is None:
            say("press: %s" % nm)
            return False
        with lock:
            todo.append((at if at is not None else time.monotonic(), sid, 1 if level is None else level, nm,
                         ms if level is None else None))
        return True

    at = time.monotonic() + PRESS_GAP_S
    for p in presses:
        word, _, ms = p.partition("=")
        if queue_press(word, int(ms) if ms.isdigit() else PRESS_MS, at=at):
            at += PRESS_GAP_S

    def reader():
        src = stdin or sys.stdin
        for ln in iter(src.readline, ""):
            f = ln.split()
            if not f:
                continue
            cmd, rest = f[0].lower(), f[1:]
            if cmd in ("quit", "exit", "q"):
                break
            ms = PRESS_MS
            if cmd == "press" and len(rest) > 1 and rest[-1].isdigit():
                ms, rest = int(rest[-1]), rest[:-1]
            word = " ".join(rest)
            if cmd == "press":
                queue_press(word, ms)
            elif cmd == "hold":
                queue_press(word, level=1)
            elif cmd == "release":
                queue_press(word, level=0)
            else:
                say("? press NAME [MS] | hold NAME | release NAME | quit")
        stop.set()

    if seconds is None or stdin is not None:
        threading.Thread(target=reader, daemon=True).start()
    try:
        while not stop.is_set():
            now = time.monotonic()
            if seconds is not None and now - t0 >= seconds:
                break
            with lock:
                due = sorted(x for x in todo if x[0] <= now)
                todo[:] = [x for x in todo if x[0] > now]
            for _, sid, level, nm, ms in due:
                probe.mine[sid] = level
                pipe.set(sid, level)
                say("%9.3f  press   %5d  %-28s %s" % (now - t0, 1000 + sid, nm, "%d ms" % ms if ms is not None
                                                      else "held" if level else "released"))
                if ms is not None and level:
                    # let go only once the game has it: a press both of whose
                    # edges reach a helper still starting never lands
                    landing[sid] = (nm, ms, now + LAND_S)
            data = read(rig.led_path(), LED_READ)
            sw = read(rig.sw_path(), SW_READ)
            for e in probe.step(data, sw, now - t0):
                if only and not _wanted(e, only):
                    continue
                say(json.dumps(e) if as_json else line(e))
            for sid, (nm, ms, give_up) in list(landing.items()):
                if probe.sw is not None and probe.sw[sid]:
                    del landing[sid]
                    with lock:
                        todo.append((now + ms / 1000.0, sid, 0, nm, None))
                elif now >= give_up:
                    del landing[sid]
                    say("%9.3f  press   %5d  %-28s never reached the game in %d s: let go"
                        % (now - t0, 1000 + sid, nm, LAND_S))
                    with lock:
                        todo.append((now, sid, 0, nm, None))
            stop.wait(interval)
    except KeyboardInterrupt:
        pass
    finally:
        for sid, level in list(probe.mine.items()):
            if level:
                pipe.set(sid, 0)       # nothing the probe closed stays closed
        try:
            pipe.close()
        except Exception:              # noqa: BLE001
            pass
    return 0


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    title, rest = argv[0], argv[1:]
    presses, seconds, only = [], None, []
    i = 0
    while i < len(rest):
        if rest[i] == "--press" and i + 1 < len(rest):
            presses.append(rest[i + 1])
            i += 1
        elif rest[i] == "--only" and i + 1 < len(rest):
            only.append(rest[i + 1])
            i += 1
        elif rest[i] == "--for" and i + 1 < len(rest):
            seconds = float(rest[i + 1])
            i += 1
        i += 1
    return run(title, seconds, presses, leds="--no-leds" not in rest, coils="--no-coils" not in rest,
               switches="--no-switches" not in rest, levels="--levels" in rest, as_json="--json" in rest,
               only=only)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
