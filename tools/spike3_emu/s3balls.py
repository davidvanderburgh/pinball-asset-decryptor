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

KEEP THE BALL ALIVE (PAD-1137). With no playfield a launched ball never
touches a switch, and a Spike 3 game treats a ball that has moved nothing for
long enough as lost: ball search, then the ball ends and, ball after ball,
the game. A real ball left alone rattles between the slingshots on its way
down, so while a ball is in play (derived from the switches: balls the trough
and shooter lane do not hold, so a drain clicked in the playfield window
counts) and no PLAYFIELD switch has moved for ALIVE_S, the model taps one:
the slingshots in turn (the boards' coil rules, PAD-1134, then fire the sling
coil, so the window flashes it), else the return lanes / inlanes, else the
pop bumpers. Any playfield switch moving - a click, a key, a ball search
firing a coil the game watches - restarts the wait, so somebody playing is
never tapped over. Cabinet buttons, the trough, the shooter lane and the
like are not playfield switches (QUIET_EXCLUDE). PAD_S3_ALIVE_MS sets the
wait (0 turns it off).
"""
import json
import os
import re
import time

EJECT_GAP = 0.6       # a second eject inside this window is the game's retry

#: PAD-1137: no playfield switch for this long with a ball in play -> tap one.
#: Well inside the game's ball search wait (see docs/plans/spike3_emulation.md).
ALIVE_S = float(os.environ.get("PAD_S3_ALIVE_MS", "6000")) / 1000.0
#: How long a tap holds the switch closed: a sling switch a ball brushes.
TAP_S = 0.08
#: Switches that are not the ball moving on the playfield, by name.
QUIET_EXCLUDE = re.compile(
    r"BUTTON|COIN|SERVICE|TILT|TROUGH|SHOOTER|\bEOS\b|^QR |JUMPER|HEADPHONE|VOLUME|"
    r"TICKET|INTERLOCK|DOOR|ENCODER|\b(UP|DOWN|HOME)$")
#: The switches a tap may use, best first: a group is used if it has any.
ALIVE_GROUPS = (r"\bSLING", r"\bRETURN LANE\b|\bINLANE\b|\bIN LANE\b", r"\bPOP\b|\bBUMPER\b")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def resolve(devs):
    """{trough: [(node, bit)] eject end first, shooter, eject, launch} from
    s3nodes.devices rows (name, node, index, class)."""
    trough, shooter, eject, launch, optos = {}, None, None, None, []
    playfield, groups = {}, [[] for _ in ALIVE_GROUPS]
    for name, node, idx, cls in devs:
        n = _norm(name)
        if node < 0:
            continue
        # node 0 is the CPU board's SPI chain (cabinet and service inputs)
        if cls == "switch" and node > 0 and not QUIET_EXCLUDE.search(n):
            playfield.setdefault((node, idx), n)
            for g, pat in enumerate(ALIVE_GROUPS):
                if re.search(pat, n) and "OUTLANE" not in n:
                    groups[g].append((node, idx, n))
                    break
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
    alive = next((sorted(set(g)) for g in groups if g), [])
    return dict(trough=[trough[k] for k in sorted(trough)], shooter=shooter,
                eject=eject, launch=launch, optos=sorted(set(optos)),
                alive=[[nd, ix, nm] for nd, ix, nm in alive],
                playfield=sorted([nd, ix] for nd, ix in playfield))


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
        # PAD-1137 keep-alive: the balls this machine has (the most ever seen
        # home or in the lane), the playfield's last state and when it moved
        self.total = self.home() + self.lane()
        self.pf = [tuple(nb) for nb in where.get("playfield", [])]
        self.alive = [(nd, ix, nm) for nd, ix, nm in where.get("alive", [])]
        self.pf_last = self.pf_state()
        self.pf_moved = time.time()
        self.taps = 0
        if ALIVE_S > 0 and self.alive:
            self.say("keep-alive: with a ball in play and no playfield switch for %.0f s, "
                     "tap %s" % (ALIVE_S, ", ".join(nm for _, _, nm in self.alive)))
        elif ALIVE_S > 0:
            self.say("keep-alive: no slingshot, return lane or pop bumper switch - off")

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

    def lane(self):
        sh = self.w["shooter"]
        return 1 if sh and self.made(sh) else 0

    def out(self):
        """Balls neither home nor in the shooter lane - DERIVED from the
        switches, so a drain clicked in the playfield window counts."""
        self.total = max(self.total, self.home() + self.lane())
        return self.total - self.home() - self.lane()

    def pf_state(self):
        return tuple(self.made(nb) for nb in self.pf)

    def keep_alive(self, now):
        """PAD-1137: tap a slingshot (or lane, or pop) when a ball in play has
        moved no playfield switch for ALIVE_S. See the module docstring."""
        cur = self.pf_state()
        if cur != self.pf_last:
            self.pf_last, self.pf_moved = cur, now
            return
        if ALIVE_S <= 0 or not self.alive or now - self.pf_moved < ALIVE_S:
            return
        if self.out() <= 0:
            self.pf_moved = now          # nothing out there: wait a whole ALIVE_S again
            return
        node, idx, name = self.alive[self.taps % len(self.alive)]
        nb = (node, idx)
        self.taps += 1
        self.pf_moved = now
        self.set(nb, True)
        self.pf_last = self.pf_state()   # our own close is not somebody playing
        quiet = self.taps > 3 and self.taps % 25
        def release():
            self.set(nb, False)
            self.pf_last = self.pf_state()
        self.due.append((now + TAP_S, release, None if quiet else
                         "keep-alive tap %d: %s (no playfield switch for %.0f s, %d in play)"
                         % (self.taps, name, ALIVE_S, self.out())))

    def after(self, secs, fn, why):
        self.due.append((time.time() + secs, fn, why))

    def tick(self):
        now = time.time()
        self.keep_alive(now)
        if not self.due:
            return
        keep = []
        for t, fn, why in self.due:
            if t <= now:
                fn()
                if why:
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
