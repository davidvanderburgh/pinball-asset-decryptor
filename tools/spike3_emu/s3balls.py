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
(`s3press.py drain SLOT`, or the window's Drain, rolls it home - below).

Which switches and coils, by NAME from the title's device tables
(s3nodes.devices), so every title resolves its own: `TROUGH <n>`, the
switch named SHOOTER LANE (or SHOOTER...), the coil named TROUGH (or
TROUGH EJECT / BALL TROUGH) and AUTO PLUNGER (or AUTO LAUNCH). DIR/balls.json
records what was resolved, for s3press.py.

PAD_S3_BALLS=0 turns the model off; PAD_S3_BALLS_HOME=0 starts the trough
empty instead of full.

THE WINDOW'S BALL CONTROLS (PAD-1181, Spike 2's PAD-134/153/186 on Spike 3).
The virtual playfield's BALLS section - Plunge, Drain, Reset balls, and the
trough dots where they are clickable - runs Spike 2's plunge.py, which on a
Spike 3 slot hands the move to this model through a request file in the
slot's dump/ (REQ_PREFIX; the answer comes back beside it), so every ball
move happens here, in the bridge's one loop, with its timers:

    plunge  launch the ball waiting in the shooter lane, and only that
    drain   a ball in play comes home: it enters the trough at the FAR end
            and ROLLS DOWN over every open position (each closes for ROLL_S
            and opens again) until it settles on the lowest open one -
            Spike 2's PAD-186 rule; closing only the settling switch is a
            thing no ball can do, and a multiball's game credits one drain
            of several. Not while the only ball out is in the lane (PAD-153).
    take    one ball out of the trough onto the playfield (a ball added)
    serve   eject, land in the lane, launch (the TROUGH coil marker)
    reset   every trough position made, the shooter lane open

Moves queue: a drain asked while another is still rolling waits for it.
A trough eject the game fires while a ball sits in the lane is HELD and
served once the lane clears (multiball on a manual plunger: each Plunge
brings the next ball), not dropped. DIR/dump/padball carries the newest
lines for the BALLS section's note, as Spike 2's ballfeed writes it.

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
#: A returning ball covers each open trough switch it rolls over for ROLL_S,
#: ROLL_GAP_S apart (Spike 2's ballmodel.ROLL_S / ROLL_GAP_S; same knobs).
ROLL_S = float(os.environ.get("PAD_BALL_ROLL_MS") or 60) / 1000.0
ROLL_GAP_S = float(os.environ.get("PAD_BALL_ROLL_GAP_MS") or 30) / 1000.0
#: Eject to shooter lane, and lane to launch for `serve` (plunge.py's LANE_S).
LANE_FLIGHT_S = 0.5
SERVE_LANE_S = 1.2
#: The window's requests: dump/<REQ_PREFIX><tag>, answered in <ANS_PREFIX><tag>.
REQ_PREFIX = "s3ballreq."
ANS_PREFIX = "s3ballans."
VERBS = ("plunge", "drain", "take", "serve", "reset")
#: Lines the BALLS note is handed (ballfeed.STATUS_LINES).
STATUS_LINES = 6

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
        self.busy_until = 0.0            # a move (a drain's roll) still playing
        self.queue = []                  # moves waiting for it: (verb, tag)
        self.eject_held = False          # an eject that met a ball in the lane
        self.fed = 0
        self.recent = []
        # the window's requests and the BALLS note: the slot's dump/ (a window
        # run), else the slot directory itself (s3press.py, a headless run)
        self.req_dir = None
        if d:
            dump = os.path.join(d, "dump")
            self.req_dir = dump if os.path.isdir(dump) else d
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
        if not msg.startswith("keep-alive"):
            self.recent.append(msg)
            del self.recent[:-STATUS_LINES]
            self.publish()

    def publish(self):
        """DIR/dump/padball in ballfeed.publish's shape - `fed N`, then the
        newest lines: the playfield window's BALLS note reads it."""
        if not self.req_dir:
            return
        p = os.path.join(self.req_dir, "padball")
        try:
            with open(p + ".tmp", "w", encoding="utf8", newline="\n") as f:
                f.write("fed %d\n" % self.fed)
                for line in self.recent:
                    f.write(line + "\n")
            os.chmod(p + ".tmp", 0o666)
            os.replace(p + ".tmp", p)
        except OSError:
            pass

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
        self.requests()
        if self.queue and now >= self.busy_until and not self.due:
            verb, tag = self.queue.pop(0)
            self.answer(tag, self.move(verb))
        if (self.eject_held and not self.due and now >= self.busy_until
                and not (self.w["shooter"] and self.made(self.w["shooter"]))):
            self.eject_held = False
            self.say("the shooter lane is clear: the held trough eject is served")
            self.on_eject(force=True)
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

    def on_eject(self, force=False):
        """The trough eject fired: the highest made position opens and the
        ball lands in the shooter lane. A ball already in the lane HOLDS the
        eject until the lane clears (tick serves it) - Spike 2's feeder rule,
        which lets a multiball on a manual plunger bring its balls one Plunge
        at a time - and a retry inside EJECT_GAP is the same ball. Returns
        None when a ball was ejected, else why not."""
        now = time.time()
        sh = self.w["shooter"]
        made = [nb for nb in self.w["trough"] if self.made(nb)]
        if not force and now - self.last_eject < EJECT_GAP:
            return "a retry of the last eject"
        if not made:
            self.say("trough eject fired with the trough empty")
            return "the trough is empty - nothing to eject"
        if sh and self.made(sh):
            if not self.eject_held:
                self.say("trough eject fired with a ball already in the shooter lane - "
                         "held until the lane clears")
            self.eject_held = True
            return "a ball is already in the shooter lane"
        self.last_eject = now
        self.fed += 1
        top = made[-1]
        self.after(0.15, lambda: self.set(top, False),
                   "trough eject: a ball leaves (%d left home)" % (len(made) - 1))
        if sh:
            self.after(LANE_FLIGHT_S, lambda: self.set(sh, True), "the ball reaches the shooter lane")
        self.busy_until = max(self.busy_until, now + LANE_FLIGHT_S + 0.05)
        return None

    def on_launch(self):
        sh = self.w["shooter"]
        if not sh or not self.made(sh):
            return
        def go():
            self.set(sh, False)
            self.in_play += 1
        self.after(0.05, go, "auto plunger: ball launched into play")

    # ---- the window's ball moves (PAD-1181) ----------------------------------
    def requests(self):
        """Pick up the window's requests (plunge.py on a Spike 3 slot): each
        is dump/s3ballreq.<tag> holding a verb; the answer goes to
        dump/s3ballans.<tag> as the move is decided (a roll plays after)."""
        if not self.req_dir:
            return
        try:
            names = sorted(n for n in os.listdir(self.req_dir)
                           if n.startswith(REQ_PREFIX) and not n.endswith(".tmp"))
        except OSError:
            return
        for n in names:
            p = os.path.join(self.req_dir, n)
            try:
                with open(p) as f:
                    verb = f.read().strip().lower()
                os.remove(p)
            except OSError:
                continue
            self.ask(verb, n[len(REQ_PREFIX):])

    def ask(self, verb, tag=None):
        """One move, now or after the one still playing. Returns the answer
        when it ran now, None when it was queued (answered when it runs)."""
        if verb not in VERBS:
            return self.answer(tag, "not a ball move: %r (%s)" % (verb, ", ".join(VERBS)))
        if self.queue or self.due or time.time() < self.busy_until:
            self.queue.append((verb, tag))
            return None
        return self.answer(tag, self.move(verb))

    def answer(self, tag, text):
        if tag is not None and self.req_dir:
            p = os.path.join(self.req_dir, ANS_PREFIX + tag)
            try:
                with open(p + ".tmp", "w") as f:
                    f.write(text + "\n")
                os.chmod(p + ".tmp", 0o666)
                os.replace(p + ".tmp", p)
            except OSError:
                pass
        return text

    def move(self, verb):
        return getattr(self, "do_" + verb)()

    def do_plunge(self):
        """Launch the ball in the shooter lane - and nothing else (Spike 2's
        PAD-134 rule: a Plunge never takes a ball out of the trough)."""
        sh = self.w["shooter"]
        if sh and self.made(sh):
            self.set(sh, False)
            self.in_play += 1
            self.say("plunged: the ball in the shooter lane is launched into play")
            return "shooter lane opened (ball launched)"
        if self.out() > 0:
            return ("nothing in the shooter lane to launch   trough %d/%d - a ball is in play; "
                    "Drain ends it" % (self.home(), len(self.w["trough"])))
        return ("nothing in the shooter lane to launch   the game puts one there when a ball "
                "starts (Insert coin, Start)")

    def do_drain(self):
        """A ball in play comes home, rolling over every open position from
        the FAR end down to the one it settles on (module docstring)."""
        tr = self.w["trough"]
        flags = [self.made(nb) for nb in tr]
        if all(flags):
            return "the trough is already full - no ball is in play"
        if self.out() <= 0:
            return "the ball is still in the shooter lane - Plunge it first"
        k = flags.index(False)               # the lowest open position: where it settles
        t = 0.0
        for i in range(len(tr) - 1, k, -1):
            if flags[i]:
                continue                     # not on a stack; never re-close a made one
            nb = tr[i]
            self.after(t, (lambda nb=nb: self.set(nb, True)), None)
            t += ROLL_S
            self.after(t, (lambda nb=nb: self.set(nb, False)), None)
            t += ROLL_GAP_S
        home = sum(flags) + 1
        passed = sum(1 for i in range(k + 1, len(tr)) if not flags[i])
        self.after(t, (lambda nb=tr[k]: self.set(nb, True)),
                   "drain: a ball rolls into the trough%s (%d/%d home)" % (
                       " over %d position%s" % (passed, "" if passed == 1 else "s") if passed else "",
                       home, len(tr)))
        self.in_play = max(0, self.in_play - 1)
        self.busy_until = time.time() + t + ROLL_GAP_S
        return "trough %d closed (ball drained home, %d/%d)" % (k + 1, home, len(tr))

    def do_take(self):
        """One ball out of the trough onto the playfield (a ball added to
        play): the highest made position opens, nothing else moves."""
        made = [nb for nb in self.w["trough"] if self.made(nb)]
        if not made:
            return "the trough is empty - nothing to take out"
        self.set(made[-1], False)
        self.say("a ball taken out of the trough onto the playfield (%d/%d home)"
                 % (len(made) - 1, len(self.w["trough"])))
        return "trough %d opened (ball out onto the playfield)" % len(made)

    def do_serve(self):
        """Eject, land in the lane, launch: what the TROUGH coil marker plays."""
        why = self.on_eject(force=True)
        if why:
            if "lane" in why:
                self.eject_held = False      # a hand serve is not the game's eject
                return why + " - Plunge launches it"
            return why
        sh = self.w["shooter"]
        if sh:
            def go():
                if self.made(sh):
                    self.set(sh, False)
                    self.in_play += 1
            self.after(LANE_FLIGHT_S + SERVE_LANE_S, go, "served: the ball is launched into play")
            self.busy_until = time.time() + LANE_FLIGHT_S + SERVE_LANE_S + 0.05
        return "a ball served from the trough and launched"

    def do_reset(self):
        """Every ball home: the trough full, the shooter lane open."""
        for nb in self.w["trough"]:
            self.set(nb, True)
        if self.w["shooter"]:
            self.set(self.w["shooter"], False)
        for _verb, tag in self.queue:
            self.answer(tag, "not done: Reset balls came first")
        self.due, self.queue, self.eject_held, self.in_play = [], [], False, 0
        self.busy_until = 0.0
        n = len(self.w["trough"])
        self.total = max(self.total, n)
        self.say("reset: %d balls in the trough, shooter lane empty" % n)
        return "%d balls in the trough, shooter lane empty" % n

    def drain(self):
        """A ball comes home - the drain move (rolled), for callers in this
        process and the tests. True when a ball is on its way home (or queued
        behind a move still playing)."""
        r = self.ask("drain")
        return r is None or r.startswith("trough ")
