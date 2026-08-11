#!/usr/bin/env python3
"""ballmodel.py - where the balls are, and what moves when one does.

REMAINING item 21b. Until this existed nothing in the rig tracked a ball:
plunge.py opened one trough switch and worked the shooter lane, and the loop
between the coil the GAME fires and the switch that should answer it was never
closed. Measured 2026-08-10 (item 21a's run): `plunge.py coin` then
`plunge.py start` left the trough reading 6 of 6 on both the panel and
swshow.py, and the count only moved when `plunge.py plunge` opened a trough
switch itself. So every ball this rig has ever "played" was moved by a script
pretending, and multiball - which is the game firing the trough eject again and
again and expecting balls to arrive - had nothing to answer it.

THE MODEL IS A STACK WITH A DIRECTION, AND THAT IS THE WHOLE OF IT. Item 20
measured the geometry (trough.py carries it): TROUGH 1 is the eject end, TROUGH
6 is the far end, and the balls sit contiguously from the eject end because the
trough is a ramp. So with k balls home, positions 1..k are made and k+1..6 are
open, and:

    a ball LEAVES   the highest-numbered MADE position opens   (k -> k-1)
    a ball RETURNS  the lowest-numbered OPEN position closes   (k -> k+1)

Both are one switch, and they are DIFFERENT switches from the one the ball is
physically at. That is the trap item 20 was: the eject kicks the ball off
position 1, the five behind it roll down, and the hole appears at position 6.
Opening position 1 instead presents a hole at the eject with a ball behind it,
the game has nothing to eject, and a few minutes later it ends the game
believing no ball is in play.

NOTHING HERE REMEMBERS A COUNT. Every answer is derived from the merged switch
array on the spot, because this rig has at least four things that move trough
switches - padglhost's window-open latch and its B key, plunge.py, a click on
the virtual playfield, and now ballfeed.py - and a model holding its own
counter would drift the first time a human pressed B. Deriving it also means a
state nothing here caused (a half-empty trough at window open) is read
correctly rather than fought.

WHAT IS DELIBERATELY NOT MODELLED: the playfield. There is no physics here and
there will not be, so a ball that leaves the shooter lane is simply "in play"
until something says it drained. A drain is therefore an ACTION - plunge.py
drain, or a button - and not an event this module can predict. Saying so
matters, because the honest reading of "3 in play" is "three balls the game
believes are out there", which is exactly what the game believes too.
"""
import trough

#: How long a ball takes to get from the trough eject to the shooter lane.
#: A guess with the right order of magnitude, not a measurement - a real Spike
#: trough eject is a hard kick over a few inches. It is a knob (ballfeed.py's
#: PAD_BALL_LANE_MS) because the only thing that can judge it is the game's own
#: ball-search timeout, and that has not been measured.
LANE_FLIGHT_S = 0.35

#: The shooter lane's name, which is the same words in every switch list on
#: this disk. Held here rather than in the feeder so plunge.py and the feeder
#: cannot disagree about which switch a ball arrives on.
LANE_NAME = "SHOOTER LANE"


class Plan:
    """What to do, as steps a caller executes - or a refusal with a reason.

    A PLAN RATHER THAN A FUNCTION THAT DOES IT, because the interesting part of
    a ball feeder is the DECISION and the decision needs testing without a
    running game, a mapped block or a sleep. The steps are:

        ("set", switch id, 0 or 1, what it means)
        ("wait", seconds, why)

    A refusal carries no steps and a sentence saying what stopped it. Refusals
    are normal traffic here, not errors: "the game asked for a ball and the
    trough is empty" is exactly what a real machine puts LOCATING PINBALLS on
    the screen for, and the feeder logs it rather than inventing a ball.
    """

    def __init__(self, steps=None, refused=None):
        self.steps = list(steps or ())
        self.refused = refused

    def __bool__(self):
        return self.refused is None and bool(self.steps)

    def switches(self):
        """[(id, value)] in order - what the plan actually writes."""
        return [(s[1], s[2]) for s in self.steps if s[0] == "set"]

    def text(self):
        if self.refused:
            return "refused: %s" % self.refused
        return "; ".join(s[3] for s in self.steps)


class Trough:
    """The trough, read from the merged array every time it is asked.

    `positions` is trough.find()'s list - position 1 (the eject end) first -
    so this class never decides which switches the trough is, only what the
    balls in it are doing. Those are genuinely different jobs: which switches
    is a per-title lookup with a labelled fallback, and this is a rule about
    ramps that is the same on every machine.
    """

    def __init__(self, positions):
        self.positions = list(positions or ())
        self.ids = [P["id"] for P in self.positions]

    def flags(self, mrg):
        return trough.closed(mrg, self.positions)

    def count(self, mrg):
        return sum(1 for f in self.flags(mrg) if f)

    def full(self, mrg):
        return bool(self.positions) and self.count(mrg) == len(self.positions)

    def leaving(self, mrg):
        """The switch that OPENS when a ball is ejected, or None if empty.

        The highest-numbered MADE position, not position k derived from a
        count: they are the same on a contiguous trough and only the first is
        still right when something has left a hole in the middle. Preferring
        the robust one costs nothing and means a strange trough loses a ball
        from a sensible place instead of from a computed one.
        """
        flags = self.flags(mrg)
        for i in range(len(flags) - 1, -1, -1):
            if flags[i]:
                return self.positions[i]["id"]
        return None

    def arriving(self, mrg):
        """The switch that CLOSES when a ball comes home, or None if full."""
        flags = self.flags(mrg)
        for i, f in enumerate(flags):
            if not f:
                return self.positions[i]["id"]
        return None

    def anomaly(self, mrg):
        """A sentence about a trough that is not a contiguous stack, or None.

        Worth having as its own answer rather than as a silent correction: a
        hole in the middle means somebody moved a switch that no ball could
        have moved, and item 20 was exactly that fault going unnoticed for
        days. The feeder logs this once per change rather than every poll.
        """
        flags = self.flags(mrg)
        k = sum(1 for f in flags if f)
        if flags[:k] == [True] * k and flags[k:] == [False] * (len(flags) - k):
            return None
        made = [P["pos"] for P, f in zip(self.positions, flags) if f]
        return ("trough is not a stack: %d balls at positions %s, expected 1..%d"
                % (k, ",".join(str(p) for p in made) or "-", k))


def plan_eject(tr, mrg, lane_id=None, lane_made=False,
               flight_s=LANE_FLIGHT_S):
    """The game fired the trough eject. Answer it.

    Two refusals, and both are real machine states rather than errors:

      * an EMPTY trough. A real machine finds nothing to kick, sees no trough
        switch change and goes to LOCATING PINBALLS. Feeding a ball that does
        not exist would make the rig's own count disagree with the game's the
        moment they were compared, which is the one thing this item's
        acceptance says must not happen.
      * an OCCUPIED shooter lane. A ball cannot land on top of another one.
        The feeder holds the request and answers it when the lane clears -
        which also folds a RETRY BURST into one ball, because a game that has
        not seen its trough change yet re-pulses the coil.
    """
    if not tr.positions:
        return Plan(refused="no trough switches for this title")
    out = tr.leaving(mrg)
    if out is None:
        return Plan(refused="the trough is empty - nothing to eject")
    if lane_id is not None and lane_made:
        return Plan(refused="a ball is already in the shooter lane")
    steps = [("set", out, 0, "trough switch %d opened (ball out)" % out)]
    if lane_id is not None:
        steps.append(("wait", flight_s, "ball in flight to the shooter lane"))
        steps.append(("set", lane_id, 1,
                      "shooter lane %d closed (ball waiting)" % lane_id))
    return Plan(steps)


def plan_launch(lane_id, lane_made):
    """The game fired the auto plunger, or a human plunged."""
    if lane_id is None:
        return Plan(refused="this title has no %s switch" % LANE_NAME)
    if not lane_made:
        return Plan(refused="nothing in the shooter lane to launch")
    return Plan([("set", lane_id, 0,
                  "shooter lane %d opened (ball launched)" % lane_id)])


def plan_drain(tr, mrg):
    """A ball in play drained. It arrives at the FAR end of the trough.

    THIS IS THE HALF NOTHING CAN OBSERVE, so it is an action and not an event.
    There is no playfield simulation, so a ball that has left the shooter lane
    stays in play until something says otherwise - and until that something
    exists, a multiball can start but can never end, which would make the
    game's ball counter walk away from the rig's within one game.
    """
    if not tr.positions:
        return Plan(refused="no trough switches for this title")
    home = tr.arriving(mrg)
    if home is None:
        return Plan(refused="the trough is already full - no ball is in play")
    return Plan([("set", home, 1,
                  "trough switch %d closed (ball drained home)" % home)])
