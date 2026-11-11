#!/usr/bin/env python3
"""s3balls.py - the balls of a Spike 3 rig: answer the game's trough eject
and auto plunger with the switches a ball would move (PAD-1090).

Spike 2's ballmodel.py/ballfeed.py, for the node bus s3bridge.py answers.
The game fires a coil by sending its node `40 IDX <pulse power> ...` (Spike
2's coil frame, masked on this generation - s3bridge.unmask); the FIRST 0x40
to a coil is its boot configuration, every later one, and the short `40 IDX
ck`, is a fire (Spike 2's coil_publish rule). The switches are the slot's
nodesw (s3bridge's live inputs, 8 bytes a node, 1 = closed); writing one is
all it takes - the bridge raises the node's request and the game reads it.

THE TROUGH IS A STACK WITH A DIRECTION (Spike 2 item 20): TROUGH 1 is the
eject end, balls rest contiguously from it, so with k balls home positions
1..k are made, and

    a ball LEAVES   the highest-numbered MADE position opens
    a ball RETURNS  the lowest-numbered OPEN position closes

and the ball that left arrives at the SHOOTER LANE. The AUTO PLUNGER fired
with a ball in the lane puts it in play (the lane opens). There is no
playfield here: a ball in play stays in play until something drains it
(`s3press.py drain SLOT` closes the next trough position).

Which switches and coils, by NAME from the title's device tables
(s3nodes.devices), so every title resolves its own: `TROUGH <n>`, the
switch named SHOOTER LANE (or SHOOTER...), the coil named TROUGH (or
TROUGH EJECT / BALL TROUGH) and AUTO PLUNGER (or AUTO LAUNCH). DIR/balls.json
records what was resolved, for s3press.py.

PAD_S3_BALLS=0 turns the model off; PAD_S3_BALLS_HOME=0 starts the trough
empty instead of full.
"""
import json
import os
import re
import time

EJECT_GAP = 0.6       # a second eject inside this window is the game's retry


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def resolve(devs):
    """{trough: [(node, bit)] eject end first, shooter, eject, launch} from
    s3nodes.devices rows (name, node, index, class)."""
    trough, shooter, eject, launch, optos = {}, None, None, None, []
    for name, node, idx, cls in devs:
        n = _norm(name)
        if node < 0:
            continue
        if cls == "switch" and re.search(r"\bOPTO\b", n) and node > 0:
            optos.append((node, idx))
        if cls == "switch":
            m = re.match(r"^TROUGH (\d+)$", n)
            if m:
                trough.setdefault(int(m.group(1)), (node, idx))
            elif shooter is None and n.startswith("SHOOTER"):
                shooter = (node, idx)
        elif cls == "coil":
            if eject is None and n in ("TROUGH", "TROUGH EJECT", "BALL TROUGH", "TROUGH KICKER"):
                eject = (node, idx)
            elif launch is None and (n.startswith("AUTO PLUNGER") or n.startswith("AUTO LAUNCH")
                                     or n == "AUTOLAUNCH"):
                launch = (node, idx)
    return dict(trough=[trough[k] for k in sorted(trough)], shooter=shooter,
                eject=eject, launch=launch, optos=sorted(set(optos)))


class Balls:
    def __init__(self, sw, where, log=None, d=None):
        self.sw, self.w, self.log = sw, where, log
        self.configured = set()
        self.due = []                    # (time, fn, why)
        self.last_eject = 0.0
        self.in_play = 0
        if d:
            with open(os.path.join(d, "balls.json"), "w") as f:
                json.dump(where, f)
        if os.environ.get("PAD_S3_BALLS_HOME", "1") != "0":
            for nb in where["trough"]:
                self.set(nb, True)
        # nodesw is LOGICAL (1 = closed; s3bridge applies each switch's wire
        # polarity), so every switch - optos included - rests OPEN: nothing
        # in the beam. PAD_S3_OPTO_REST=1 closes the optos (an experiment).
        closed = 0
        if os.environ.get("PAD_S3_OPTO_REST", "0") == "1":
            for nb in where.get("optos", []):
                self.set(nb, True)
            closed = len(where.get("optos", []))
        self.say("trough %s, shooter %s, eject coil %s, launch coil %s; %d home%s" % (
            where["trough"], where["shooter"], where["eject"], where["launch"], self.home(),
            "; %d optos held closed" % closed if closed else ""))

    @classmethod
    def for_game(cls, game, sw, log=None, d=None):
        import s3nodes
        where = resolve(s3nodes.devices(s3nodes.Elf(game)))
        if not where["trough"]:
            raise ValueError("no TROUGH n switches in the device tables")
        return cls(sw, where, log, d)

    def say(self, msg):
        if self.log:
            self.log.write("%s # [ball] %s\n" % (time.strftime("%H:%M:%S"), msg))

    def made(self, nb):
        node, bit = nb
        return bool(self.sw[8 * node + bit // 8] & (1 << (bit % 8)))

    def set(self, nb, on):
        node, bit = nb
        o = 8 * node + bit // 8
        v = self.sw[o]
        self.sw[o] = (v | (1 << (bit % 8))) if on else (v & ~(1 << (bit % 8)) & 0xFF)

    def home(self):
        return sum(self.made(nb) for nb in self.w["trough"])

    def after(self, secs, fn, why):
        self.due.append((time.time() + secs, fn, why))

    def tick(self):
        if not self.due:
            return
        now = time.time()
        keep = []
        for t, fn, why in self.due:
            if t <= now:
                fn()
                self.say(why)
            else:
                keep.append((t, fn, why))
        self.due = keep

    def coil(self, node, data):
        """A 0x40 frame to `node` (plain): count fires, skip configurations."""
        idx = data[1]
        if len(data) > 3:
            if (node, idx) not in self.configured:
                self.configured.add((node, idx))
                return
        if (node, idx) == self.w["eject"]:
            self.on_eject()
        elif (node, idx) == self.w["launch"]:
            self.on_launch()

    def on_eject(self):
        now = time.time()
        sh = self.w["shooter"]
        made = [nb for nb in self.w["trough"] if self.made(nb)]
        if now - self.last_eject < EJECT_GAP:
            return
        if not made:
            self.say("trough eject fired with the trough empty")
            return
        if sh and self.made(sh):
            self.say("trough eject fired with a ball already in the shooter lane - held")
            return
        self.last_eject = now
        top = made[-1]
        self.after(0.15, lambda: self.set(top, False),
                   "trough eject: a ball leaves (%d left home)" % (len(made) - 1))
        if sh:
            self.after(0.5, lambda: self.set(sh, True), "the ball reaches the shooter lane")

    def on_launch(self):
        sh = self.w["shooter"]
        if not sh or not self.made(sh):
            return
        def go():
            self.set(sh, False)
            self.in_play += 1
        self.after(0.05, go, "auto plunger: ball launched into play")

    def drain(self):
        """A ball comes home: the lowest-numbered open position closes."""
        for nb in self.w["trough"]:
            if not self.made(nb):
                self.set(nb, True)
                self.in_play = max(0, self.in_play - 1)
                self.say("drain: a ball returns to the trough (%d home)" % self.home())
                return True
        return False
