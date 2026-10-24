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
import os

import trough

#: How long a ball takes to get from the trough eject to the shooter lane.
#: A guess with the right order of magnitude, not a measurement - a real Spike
#: trough eject is a hard kick over a few inches. It is a knob (ballfeed.py's
#: PAD_BALL_LANE_MS) because the only thing that can judge it is the game's own
#: ball-search timeout, and that has not been measured.
LANE_FLIGHT_S = 0.35

#: How long a returning ball sits on each trough opto it rolls over on the way
#: down to the stack, and the gap between one and the next (plan_drain). A
#: ball rolling down a trough ramp covers an opto for a few tens of ms; long
#: enough here for the game's debounce to see a closure, short enough that a
#: three-position roll is over well inside a second. Knobs because the game's
#: trough debounce is not published anywhere and only a live run can say.
ROLL_S = float(os.environ.get("PAD_BALL_ROLL_MS") or 60) / 1000.0
ROLL_GAP_S = float(os.environ.get("PAD_BALL_ROLL_GAP_MS") or 30) / 1000.0

#: The shooter lane's name, which is the same words in every switch list on
#: this disk. Held here rather than in the feeder so plunge.py and the feeder
#: cannot disagree about which switch a ball arrives on.
LANE_NAME = "SHOOTER LANE"
#: ...or, on a lane read by an opto, these (Jurassic Park Pin: SHOOTER LANE OPTO)
LANE_NAMES = (LANE_NAME, "SHOOTER LANE OPTO")


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


#: ★ ITEM 167 (2026-09-26): THE VAN, a physical ball lock (TMNT LE and Premium; David: "turtles le/premium
#: has the van which locks balls"). Five optos, bottom first - LOWER LOCK 1-2 hold the balls the LOWER LOCK
#: coil lets out onto the playfield, UPPER LOCK 1-3 the ones the UPPER LOCK coil lets down into the lower
#: section - and VAN ENTER OPTO at its mouth. MEASURED in the rig with a coil probe (2026-09-26): IN ATTRACT
#: THE AUTO PLUNGER SHOOTS INTO THE VAN - three balls every ~15 s, each dropped by UPPER LOCK and let out by
#: LOWER LOCK, and the game takes Start only while that cycle works. With no van every such ball was lost:
#: Start refused for ~150 s, and a multiball's count collapsed at its first ball search (a multiball of the
#: mode's own ended with no drain). IN A GAME the served balls go onto the playfield: sent into the van,
#: the game took them for locked balls, held them 12-26 s and its count climbed to 7. How the feeder tells
#: the two apart is in ballfeed.py (the game's ball 1 waits in the lane for its plunge; attract's never
#: does). The names are the only thing that makes a title a van title.
VAN_STACK = ("LOWER LOCK 1", "LOWER LOCK 2", "UPPER LOCK 1", "UPPER LOCK 2", "UPPER LOCK 3")
VAN_LOWER = 2                    # the first two of VAN_STACK are the lower section
VAN_ENTER = "VAN ENTER OPTO"
VAN_COIL_LOWER = "LOWER LOCK"
VAN_COIL_UPPER = "UPPER LOCK"
#: PAD-654: the one-ball lock an ATTRACT ball the van lets out is for (TMNT LE's glider). MEASURED (turtles_le 1.59,
#: 2026-10-20): attract ran its van cycle - VAN DOOR, three balls in and out - every ~20 s for as long as the rig ran,
#: and ignored Start through most of it; one ball closing GLIDER LOCK OPTO and the cycle ended at once, the next
#: Start served ball 1. So the van's first attract release goes there while it is empty; the rest roll home.
VAN_CATCH = "GLIDER LOCK OPTO"
VAN_CATCH_S = 1.0                # from the van's lower lock to the glider
#: from the auto plunger to the van's mouth, and how long a ball covers its opto
VAN_FLIGHT_S = 0.8
VAN_ENTER_S = 0.15
#: how long a ball takes to drop one place inside the van
VAN_DROP_S = 0.3
#: A ball that waits this long in the shooter lane after its eject is a GAME's ball waiting for its plunge:
#: attract auto-plunges every one within ~1 s (the probe). From then on launches go onto the playfield...
VAN_GAME_LANE_S = 3.0
#: Balls put in the van when the feeder first sees it empty with the trough full, in the section
#: PAD_BALL_VAN_STOCK_AT names (lower or upper). 0 by default and on purpose: David says the TMNT LE has 8
#: balls installed (a six-ball trough), but a rig booted with two in the van watched the game empty it at
#: once (UPPER LOCK, LOWER LOCK, twice) - the van is empty at rest. Kept as a knob for that measurement.
VAN_STOCK = int(os.environ.get("PAD_BALL_VAN_STOCK") or 0)
VAN_STOCK_AT = (os.environ.get("PAD_BALL_VAN_STOCK_AT") or "lower").lower()
#: ...until an auto plunge follows an eject from a FULL trough with no ball home for this long - attract
#: again after game over. A ball save's re-serve comes a second or two after its drain, so it keeps the game.
VAN_ATTRACT_QUIET_S = 10.0


class Van:
    """The van's balls, read off its optos in the merged array every time - like Trough, it decides
    nothing about which switches the van is (from_names does, by name) and holds no count of its own."""

    def __init__(self, stack, enter, catch=None):
        self.stack = list(stack)
        self.enter = enter
        self.catch = catch          # VAN_CATCH's id, or None on a title without one

    @classmethod
    def from_names(cls, by_name):
        """A Van from {SWITCH NAME: id}, or None on a title without all six of its switches."""
        ids = [by_name.get(n) for n in VAN_STACK]
        enter = by_name.get(VAN_ENTER)
        if None in ids or enter is None:
            return None
        return cls(ids, enter, by_name.get(VAN_CATCH))

    def plan_catch(self, mrg):
        """An attract ball the van let out goes into an empty VAN_CATCH lock; None when there is none to fill."""
        if self.catch is None or mrg[self.catch]:
            return None
        return Plan([("wait", VAN_CATCH_S, "the ride to the %s" % VAN_CATCH.lower()),
                     ("set", self.catch, 1, "%s (%d) closed (the attract ball the van let out stays there)"
                      % (VAN_CATCH, self.catch))])

    def flags(self, mrg):
        return [bool(mrg[i]) for i in self.stack]

    def count(self, mrg):
        return sum(self.flags(mrg))

    def plan_load(self, mrg):
        """A launched ball flies into the van: VAN ENTER, then the lowest free place of the UPPER section, where
        the UPPER LOCK post holds it - the lower section only fills when that coil drops a ball down. (The
        first live run put it in the lower section: the game kicked each one straight out with LOWER LOCK and
        ran its van check again every ~16 s, for ever, and never took a Start.)"""
        flags = self.flags(mrg)
        free = [i for i in range(VAN_LOWER, len(self.stack)) if not flags[i]]
        if not free:
            return Plan(refused="the van's upper lock is full - the ball stays on the playfield")
        k = free[0]
        return Plan([("wait", VAN_FLIGHT_S, "the flight to the van"),
                     ("set", self.enter, 1, "van enter %d closed (a ball at the van)" % self.enter),
                     ("wait", VAN_ENTER_S, "the ball passing the opto"),
                     ("set", self.enter, 0, "van enter %d opened" % self.enter),
                     ("set", self.stack[k], 1, "%s (%d) closed (a ball in the van)" % (VAN_STACK[k], self.stack[k]))])

    def plan_stock(self, mrg, n=None, at=None):
        """The van's resting balls, put there once at start-up (VAN_STOCK): refused unless it is empty."""
        n = VAN_STOCK if n is None else n
        at = VAN_STOCK_AT if at is None else at
        if self.count(mrg):
            return Plan(refused="the van already holds balls")
        places = list(range(VAN_LOWER)) if at == "lower" else list(range(VAN_LOWER, len(self.stack)))
        places = places[:max(0, n)]
        if not places:
            return Plan(refused="no balls to stock")
        return Plan([("set", self.stack[k], 1, "%s (%d) closed (a resting ball in the van)" % (VAN_STACK[k], self.stack[k]))
                     for k in places])

    def plan_release(self, mrg):
        """LOWER LOCK fired: the bottom ball leaves for the playfield and the one above drops into its place."""
        flags = self.flags(mrg)
        if not flags[0]:
            return Plan(refused="LOWER LOCK fired with no ball at %s" % VAN_STACK[0])
        steps = [("set", self.stack[0], 0, "%s (%d) opened (a ball left the van)" % (VAN_STACK[0], self.stack[0]))]
        if flags[1]:
            steps += [("wait", VAN_DROP_S, "the ball above drops"),
                      ("set", self.stack[1], 0, "%s (%d) opened" % (VAN_STACK[1], self.stack[1])),
                      ("set", self.stack[0], 1, "%s (%d) closed" % (VAN_STACK[0], self.stack[0]))]
        return Plan(steps)

    def plan_drop(self, mrg):
        """UPPER LOCK fired: the bottom ball of the upper section drops into the lower one (lowest free place),
        and the upper balls move down one."""
        flags = self.flags(mrg)
        low = [i for i in range(VAN_LOWER) if not flags[i]]
        if not flags[VAN_LOWER]:
            return Plan(refused="UPPER LOCK fired with no ball at %s" % VAN_STACK[VAN_LOWER])
        if not low:
            return Plan(refused="UPPER LOCK fired with the lower lock full")
        steps = [("set", self.stack[VAN_LOWER], 0, "%s (%d) opened" % (VAN_STACK[VAN_LOWER], self.stack[VAN_LOWER])),
                 ("wait", VAN_DROP_S, "the ball drops"),
                 ("set", self.stack[low[0]], 1, "%s (%d) closed" % (VAN_STACK[low[0]], self.stack[low[0]]))]
        for i in range(VAN_LOWER + 1, len(self.stack)):
            if flags[i]:
                steps += [("set", self.stack[i], 0, "%s (%d) opened" % (VAN_STACK[i], self.stack[i])),
                          ("set", self.stack[i - 1], 1, "%s (%d) closed" % (VAN_STACK[i - 1], self.stack[i - 1]))]
        return Plan(steps)


#: ★ PAD-654: A HOLD, a physical lock the game fills through a DIVERTER (D&D LE/Premium's dragon: DRAGON HOLD 1-4
#: and DRAGON HOLD STACK, let out by DRAGON VUK). MEASURED in the rig (dungeons_and_dragons_le 1.10, 2026-10-20 -
#: with the stack in the wrong order, see PAD-713 below):
#:   * attract fires TROUGH and DIVERTER together, then AUTO PLUNGER - the diverter sends the launch into the hold -
#:     every ~8 s while the hold is empty. With nothing modelling it each ball came back to the trough, the loop never
#:     ended and the game never took Start. One ball closing DRAGON HOLD STACK and attract went quiet for good.
#:   * Start fills it to FOUR the same way (STACK, 4, 3, 2), and only then serves ball 1 - with NO diverter fire.
#:     So the diverter alone says whose ball it is, in attract or a game. Sent onto the playfield instead, those
#:     balls emptied the trough into a ball search.
#:   * with six balls the trough read 2/6 once the hold had its four, and the game let one out with DRAGON VUK and
#:     loaded again, round and round, before it served (one start in three tries, three minutes in). With the
#:     hold's balls on top of the trough's six it served ball 1 at once - the TMNT LE van's story (eight balls
#:     installed, a six-ball trough). `balls` is that complement, queued behind the trough (PAD_BALL_EXTRA
#:     overrides it).
#: ★ PAD-713: HOLD 1 IS THE RELEASE END AND STACK THE LAST PLACE, like TROUGH 1 is the trough's eject end. PAD-654
#: listed STACK first, so every diverted ball closed DRAGON HOLD STACK alone - and the game reads a ball there with
#: the hold empty as a JAM, not a lock (its own debug ring, switched on: `dragon_jam_event_handler: kicking dragon
#: for event 17`, where a ball on DRAGON HOLD 4 gets `dragon_lock_event_handler: MD_EVENT_ARRIVAL ... MD_EVENT_LOCK`).
#: On a factory-fresh NVRAM the jam handler gave up after one kick and the next balls locked, so the first boot
#: after a wipe played; from the second boot on it kicked every ball straight back out - attract loaded and kicked
#: for ever, the trough ran dry and Start never took (PAD-474, PAD-483, PAD-710: "no game on the rig"). Filled from
#: HOLD 1 the game locks each ball (ARRIVAL, LOCK), attract goes quiet with three, and Start serves ball 1 on any
#: boot. HOLD 4, 3, 2, 1 first works the same in a game; 1 first is the trough's convention.
#: The stack is listed from the release end: a ball rolls down to it first. MATCHED BY NAME like the van and the
#: drop banks: a title with every switch and both coils has one.
HOLDS = (
    # (the stack, release end first, release coil, feed coil, its balls)            title
    (("DRAGON HOLD 1", "DRAGON HOLD 2", "DRAGON HOLD 3", "DRAGON HOLD 4", "DRAGON HOLD STACK"),
     "DRAGON VUK", "DIVERTER", 4),                                                    # dungeons_and_dragons_le
)


def lock_ids(by_name):
    """Every switch of a lock this title has by name (the van, its glider, a HOLDS stack): a ball on one is neither
    home nor in play. For plunge.py's drain, which has no coil table to match a lock by."""
    van = Van.from_names(by_name)
    ids = (van.stack + ([van.catch] if van.catch is not None else [])) if van else []
    for names, _release, _feed, _balls in HOLDS:
        got = [by_name.get(n) for n in names]
        if None not in got:
            ids += got
    return ids


#: how long after the feed coil an auto plunge is still the diverted one (game seconds), and the ball's flight
HOLD_FEED_S = 2.5
HOLD_FLIGHT_S = 0.8


class Hold:
    """One HOLDS lock. Like Van, its balls are read off the merged array every time."""

    def __init__(self, stack, names, release, feed, balls=0):
        self.stack = list(stack)
        self.names = list(names)
        self.release = release      # (node, index)
        self.feed = feed
        self.balls = balls          # installed on top of the trough's

    @classmethod
    def from_names(cls, by_name, coil_address):
        """The first HOLDS lock this title has all of, from {SWITCH NAME: id} and name -> (node, index) or None."""
        for names, release, feed, balls in HOLDS:
            ids = [by_name.get(n) for n in names]
            r, f = coil_address(release), coil_address(feed)
            if None not in ids and r is not None and f is not None:
                return cls(ids, names, r, f, balls)
        return None

    def flags(self, mrg):
        return [bool(mrg[i]) for i in self.stack]

    def count(self, mrg):
        return sum(self.flags(mrg))

    def plan_load(self, mrg):
        """A diverted launch lands in the hold: the free place nearest the release end."""
        free = [k for k, f in enumerate(self.flags(mrg)) if not f]
        if not free:
            return Plan(refused="the hold is full - the ball stays on the playfield")
        k = free[0]
        return Plan([("wait", HOLD_FLIGHT_S, "the flight to the hold"),
                     ("set", self.stack[k], 1, "%s (%d) closed (a ball in the hold)" % (self.names[k], self.stack[k]))])

    def plan_release(self, mrg):
        """The release coil fired: the ball at the release end leaves and every ball behind it rolls down one."""
        flags = self.flags(mrg)
        if not flags[0]:
            return Plan(refused="the hold's release fired with no ball at %s" % self.names[0])
        n = sum(flags)
        steps = [("set", self.stack[0], 0, "%s (%d) opened (a ball left the hold)" % (self.names[0], self.stack[0]))]
        if n > 1:
            # the stack fills from the release end (plan_load), so n-1 balls are at places 0..n-2 afterwards
            steps.append(("wait", VAN_DROP_S, "the balls behind roll down"))
            steps.append(("set", self.stack[n - 1], 0, "%s (%d) opened" % (self.names[n - 1], self.stack[n - 1])))
            steps.append(("set", self.stack[0], 1, "%s (%d) closed" % (self.names[0], self.stack[0])))
        return Plan(steps)


#: ★ PAD-248: DROP TARGET BANKS. A RESET coil brings a bank's targets up; some banks also have a TRIP coil that
#: drops them all; each target has a switch. The game fires the coil and waits for the switches, and nothing
#: in the rig moved them. MEASURED FIRST on john_wick_le (DROP TRIP, DROP RESET, DROP TARGET OPTO), 40 s from
#: Start: the game fires RESET then TRIP 100 ms later, five pairs 250 ms apart, a 1.8 s pause, again - 139
#: fires - and with the opto held MADE, none. So MADE IS DOWN: TRIP after every RESET is what a game wanting
#: the target up would never do. Every other bank was checked the same way - hold its switches made at Start
#: and see the game fire its RESET until they open (docs/plans/node_board_motor.md, "Every title's banks").
#: PAD_DROP_DOWN=0 flips the level for a measurement.
#:
#: MATCHED BY NAME, like the van: a bank is answered when the title has its reset coil, its trip coil (if it
#: names one) and EVERY switch - so a same-named coil on another title ("3 BANK DROP": jaws_le, metallica)
#: only matches with its own switches. Names are compared upper-cased and trimmed.
DROP_BANKS = (
    # (trip coil or None, reset coil, the bank's switches)                    title
    ("DROP TRIP", "DROP RESET", ("DROP TARGET OPTO",)),                      # john_wick_le
    ("LIL DP 3 BANK DROP TRIP", "LIL DP 3 BANK DROP RESET",                  # deadpool_le
     ("L. LIL DP DROP", "MID LIL DP DROP", "R. LIL DP DROP")),
    ("LIL DP 3 BANK DROP TRIP", "LIL DP 3 BANK DROP RESET",                  # deadpool_pro
     ("LEFT LIL DEADPOOL DROP", "MIDDLE LIL DEADPOOL DROP", "RIGHT LIL DEADPOOL DROP")),
    (None, "LEFT 4 BANK DROP RESET",                                         # deadpool_le
     ("(D)EAD DROP TARGET", "D(E)AD DROP TARGET", "DE(A)D DROP TARGET", "DEA(D) DROP TARGET")),
    (None, "RIGHT 4 BANK DROP RESET",                                        # deadpool_le
     ("(P)OOL DROP TARGET", "P(O)OL DROP TARGET", "PO(O)L DROP TARGET", "POO(L) DROP TARGET")),
    ("3 BANK INLINE TRIP", "3 BANK INLINE RESET",                            # james_bond_60th_le
     ("INLINE DROP 1", "INLINE DROP 2", "INLINE DROP 3")),
    (None, "LEFT 4 BANK DROP",                                               # james_bond_60th_le
     ("LEFT 4 BANK 'B'", "LEFT 4 BANK 'O'", "LEFT 4 BANK 'N'", "LEFT 4 BANK 'D'")),
    (None, "CENTER 3 BANK DROP",                                             # james_bond_60th_le
     ("CENTER 3 BANK LEFT", "CENTER 3 BANK CENTER", "CENTER 3 BANK RIGHT")),
    (None, "CENTER 3 BANK DROP TARGET",                                      # james_bond_le
     ("CENTER 3 BANK DROP LEFT OPTO", "CENTER 3 BANK DROP CENTER OPTO", "CENTER 3 BANK DROP RIGHT OPTO")),
    (None, "3 BANK DROP", ("3 BANK BOT", "3 BANK MID", "3 BANK TOP")),         # jaws_le
    (None, "3 BANK DROP", ("DROP TGT- BOT", "DROP TGT- MID", "DROP TGT- TOP")),  # metallica_spike
    (None, "3-BANK DROP RESET",                                              # jurassic_park_the_pin
     ("3-BANK DROP TGT LEFT", "3-BANK DROP TGT CENTER", "3-BANK DROP TGT RIGHT")),
    (None, "4 BANK DROP TARGET",                                             # king_kong_le
     ("4 BANK DROP 1-TOP", "4 BANK DROP 2", "4 BANK DROP 3", "4 BANK DROP 4-BOT")),
    (None, "DROP TARGET RESET", ("3 BANK DROP-Z", "3 BANK DROP-E", "3 BANK DROP-P")),  # led_zeppelin_le
    (None, "5 BANK DROP RESET",                                              # star_wars_le
     ("(F)ORCE DROP TARGET", "F(O)RCE DROP TARGET", "FO(R)CE DROP TARGET", "FOR(C)E DROP TARGET",
      "FORC(E) DROP TARGET")),
    (None, "LEFT 3 BANK DROP", ("LT 3 BANK DROP LT", "LT 3 BANK DROP CNTR", "LT 3 BANK DROP RT")),  # beatles
    (None, "RIGHT 4 BANK DROP",                                              # beatles
     ("RT 4 BANK DROP LEFT", "RT 4 BANK DROP LT CTR", "RT 4BANK DROP R-CNTR", "RT 4 BANK DROP RIGHT")),
    (None, "CENTER 4 BANK DROP",                                             # beatles
     ("CNTR 4 BANK DROP LT", "CNTR 4 BANK DROP LT CNTR", "CNTR 4BANK DROP R-CNTR", "CNTR 4 BANK DROP RT")),
)
DROP_DOWN_LEVEL = 0 if (os.environ.get("PAD_DROP_DOWN") or "1") == "0" else 1
#: how long the targets take to fall or come up after the coil fires - well inside the 100 ms john_wick_le
#: leaves between RESET and TRIP
DROP_MOVE_S = float(os.environ.get("PAD_DROP_MS") or 30) / 1000.0


class DropBank:
    """One bank: TRIP knocks every target down, RESET brings every one up, the switches say which. Like Van,
    the state is the merged array's - a person clicking a target down is a target down as far as this is
    concerned, and the game's next RESET brings it back up."""

    def __init__(self, trip, reset, switches, names, down_level=None):
        self.trip = trip            # (node, index), or None for a bank with no trip coil
        self.reset = reset
        self.switches = list(switches)
        self.names = list(names)
        self.down_level = DROP_DOWN_LEVEL if down_level is None else down_level

    @classmethod
    def from_names(cls, by_name, coil_address):
        """Every DROP_BANKS bank this title has, from {SWITCH NAME: id} and name -> (node, index) or None."""
        out = []
        for trip, reset, names in DROP_BANKS:
            t = coil_address(trip) if trip else None
            r = coil_address(reset)
            ids = [by_name.get(n) for n in names]
            if r is not None and (trip is None or t is not None) and None not in ids:
                out.append(cls(t, r, ids, names))
        return out

    def plan_fire(self, coil, mrg):
        """`coil` ("trip" or "reset") fired: every target not already there moves (None when none has to)."""
        want_down = coil == "trip"
        level = self.down_level if want_down else 1 - self.down_level
        move = [(i, n) for i, n in zip(self.switches, self.names) if bool(mrg[i]) != bool(level)]
        if not move:
            return None
        steps = [("wait", DROP_MOVE_S, "the targets moving")]
        for i, n in move:
            steps.append(("set", i, level, "%s (%d) %s (%s: the target is %s)"
                          % (n, i, "closed" if level else "opened", "TRIP" if want_down else "RESET",
                             "down" if want_down else "up")))
        return Plan(steps)


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


def in_play(tr, mrg, lane_id=None, lane_made=False, held=0):
    """Balls the game believes are out on the playfield - DERIVED, never counted.

    installed - trough - lane. A ball waiting in the shooter lane is not in
    play until it is launched (PAD-153, plan_drain). Clamped at zero: a latched
    trough switch can make the arithmetic negative, and that is a display
    fault, not a machine state. jjpball.Feeder.in_play is the JJP twin.
    """
    lane = 1 if lane_id is not None and lane_made else 0
    # `held`: balls a lock holds (the van, item 167) - neither home nor in play
    return max(0, len(tr.positions) - tr.count(mrg) - lane - held)


def plan_drain(tr, mrg, lane_id=None, lane_made=False, held=0):
    """A ball in play drained. It arrives at the FAR end of the trough.

    THIS IS THE HALF NOTHING CAN OBSERVE, so it is an action and not an event.
    There is no playfield simulation, so a ball that has left the shooter lane
    stays in play until something says otherwise - and until that something
    exists, a multiball can start but can never end, which would make the
    game's ball counter walk away from the rig's within one game.

    ★ PAD-153, DRAGONRR: "I drained before I plunged.. and that forces an
    endless cycle." At ball start the feeder lands the ball in the shooter
    lane and the trough reads 5 of 6, so there WAS an open position to close -
    and closing it told the game a ball had come home while the lane still
    held one: seven balls on a six-ball machine. The eject the game fires next
    meets an occupied lane, which plan_eject rightly holds, and nothing can
    move again. So a drain needs a ball IN PLAY, and the lane's ball is not one
    until it is launched. `lane_id` None (a title with no lane switch, or a
    caller that has none) keeps the trough-only answer.
    """
    if not tr.positions:
        return Plan(refused="no trough switches for this title")
    home = tr.arriving(mrg)
    if home is None:
        return Plan(refused="the trough is already full - no ball is in play")
    if not in_play(tr, mrg, lane_id, lane_made, held):
        return Plan(refused="the ball is still in the shooter lane - "
                            "Plunge it first")
    # ★ THE BALL ROLLS DOWN THE RAMP FIRST (PAD-186, David's live Mechagodzilla
    # Multiball, 2026-09-20). A returning ball enters the trough at the FAR end
    # and rolls down over every open position until it meets the stack, so on
    # a real machine the far-end switch - and each open one below it - closes
    # and opens again on EVERY drain. With one ball out the settling position
    # IS the far end, which is why single-ball drains have always worked; with
    # three out, the rig closed position 4 with 5 and 6 never moving, a thing
    # no ball can do, and the game credited one drain of three and searched
    # for the rest for ever. Trough 6 first, then 5, then settle at 4.
    flags = tr.flags(mrg)
    k = next(i for i, f in enumerate(flags) if not f)
    steps = []
    for i in range(len(flags) - 1, k, -1):
        sw = tr.positions[i]["id"]
        steps.append(("set", sw, 1, "trough switch %d closed (ball passing)" % sw))
        steps.append(("wait", ROLL_S, "rolling"))
        steps.append(("set", sw, 0, "trough switch %d opened (ball rolled on)" % sw))
        steps.append(("wait", ROLL_GAP_S, "rolling"))
    steps.append(("set", home, 1,
                  "trough switch %d closed (ball drained home)" % home))
    return Plan(steps)
