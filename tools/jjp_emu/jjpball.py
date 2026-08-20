#!/usr/bin/env python3
"""jjpball.py - where the balls are, and what moves when the game fires a coil.

THE LOOP THIS CLOSES
--------------------
Pressing Start makes the game fire the trough eject and then WAIT for a trough
switch to change.  Until this existed nothing answered, so the trough stayed at
6 of 6 for ever and the game sat on "locating balls" - a static full trough
clears BALL TROUGH ERROR but cannot answer an eject, because answering means
MOVING.

Now: the shim counts the rising edge of every OUT bit (jjpshm.h out_rise), the
coil table says which bit each coil is (swdump.py decodes the Coil struct), and
this module turns "coil_vuk_trough fired" into "the trough lost a ball and the
shooter lane gained one".

THE MODEL IS A STACK WITH A DIRECTION, AND THAT IS THE WHOLE OF IT
-----------------------------------------------------------------
Measured from the live device tables (2026-08-20): the six trough switches sit
in a row at y=733, x=201..301, and coil_vuk_trough is at x=315 - the same end as
switch_trough_1, whose own name is "6-Ball Trough #1 (right)" against #6's
"(left)".  So position 1 is the EJECT end, position 6 the far end, and because
the trough is a ramp the balls stack contiguously from the eject end:

    a ball LEAVES   the highest-numbered MADE position opens   (k -> k-1)
    a ball RETURNS  the lowest-numbered OPEN position closes   (k -> k+1)

Both are ONE switch, and neither is the switch the ball is physically at.  That
is the trap: the eject kicks the ball off position 1 and the five behind it roll
down, so the hole appears at position 6.  Opening position 1 instead presents a
hole at the eject with a ball behind it, the game has nothing to kick, and it
gives up believing no ball is in play.  (The Spike 2 rig learned this the
expensive way - see tools/spike2_emu/ballmodel.py - and the geometry above says
JJP is built the same way round.)

Note the trough switch ORDER IS NOT THE FRAME ORDER: trough_5 is byte 4 bit 0
and trough_1 is bit 4, with the jam at bit 5 between #1 and #6.  Sorting by
address gives 5,4,3,2,1,jam,6 - nearly reversed.  Order by the NAME's number.

NOTHING HERE REMEMBERS WHERE THE BALLS ARE
------------------------------------------
Every answer is derived from the switches on the spot, including how many balls
are in play (installed - trough - lane).  Several things move trough switches -
this feeder, a click on the playfield, a right-click latch, the startup seat -
and a model holding its own counter would drift the first time a human touched
one.  Deriving also means a state nothing here caused is read correctly rather
than fought.

WHAT IS DELIBERATELY NOT MODELLED: the playfield.  There is no physics and there
will not be, so a ball that leaves the shooter lane is simply "in play" until
something says it drained.  A drain is therefore an ACTION (the UI's Drain
button / the D key), not an event this module can predict.  Saying so matters,
because "1 in play" here means "one ball the game believes is out there", which
is exactly what the game believes too.
"""

import re

#: How long a ball takes from the trough eject to the shooter lane.  A guess
#: with the right order of magnitude, not a measurement - a trough VUK is a hard
#: kick over a few inches.  It is a knob because the only thing that can judge
#: it is the game's own ball-search timeout, which has not been measured.
FLIGHT_MS = 350

#: A ball in play with nothing touching the playfield comes home after this
#: long.  NOT invented gameplay - the opposite: a real ball launched with nobody
#: flipping drains in a few seconds, and without this the machine's own power-up
#: ball search (which ejects and launches every ball it has) empties the trough
#: and leaves the game hunting for balls that will never come back.  Any switch
#: outside the ball path - a playfield click, a flipper button - is somebody
#: playing, and restarts the clock.  Set 0 to turn it off and drain by hand.
AUTO_DRAIN_S = 20.0

#: Two ejects closer together than this are treated as ONE - the game re-pulses
#: a coil it has not seen answered, and a chopped drive raises the same bit
#: several times inside one fire.  The coil's own duration (32 ms, from its Coil
#: object) sits far inside this, so a chopped fire folds in automatically.  The
#: number itself is a guess: only a measured multiball can say where a retry
#: burst stops and a real second ball starts, so a refusal LOGS itself rather
#: than silently deciding how many balls a multiball gets.
MIN_GAP_MS = 600

#: A served ball sits in the shooter lane waiting to be plunged.  On JJP the
#: game does NOT auto-launch it - it holds the skill shot until the player
#: launches - so in a hands-off rig the ball would sit there for ever and the
#: game never advances.  After this long the feeder launches it and pulses a
#: validation switch, exactly as a real ball rolls onto the playfield and
#: crosses a rollover to "validate" it.  A human plunge (Plunge button / P key)
#: happens first when someone is actually playing.  Set 0 to disable.
PLUNGE_DELAY_S = 2.5

_TROUGH_NUM = re.compile(r'trough[^0-9]*([0-9]+)', re.I)

EJECT_COIL_PATTERNS = ('coil_vuk_trough', 'vuk_trough', 'trough')
LAUNCH_COIL_PATTERNS = ('coil_autolaunch', 'autolaunch', 'auto_launch', 'launch')
LANE_PATTERNS = ('switch_shooter', 'shooter', 'plunger')
#: A switch the game treats as "the ball is on the playfield now" - firing one
#: sets valid_playfield and lets the ball-start/skill-shot logic proceed.  The
#: loops force-validate (a ball round an orbit is unambiguously in play); a
#: spinner or standup is a fine fallback.
VALIDATE_SW_PATTERNS = ('switch_loop_left', 'switch_loop_right',
                        'switch_loop_center', 'loop', 'switch_spinner',
                        'spinner', 'switch_inlane_right', 'inlane')


def _text(rec):
    return ((rec.get('symbol') or '') + ' ' + (rec.get('name') or '')).lower()


def _match(recs, patterns):
    """First record whose symbol matches - exact, then prefix, then substring.

    Most specific wins, so 'trough' cannot claim coil_vuk_trough's slot ahead of
    the exact name, and a title that spells it differently still resolves.
    """
    for pat in patterns:
        for test in (lambda s: s == pat,
                     lambda s: s.startswith(pat),
                     lambda s: pat in s):
            for key, rec in recs:
                if test((rec.get('symbol') or '').lower()):
                    return key, rec
    return None, None


# --------------------------------------------------------------------------
# Resolution: which switches and coils this title's ball path uses
# --------------------------------------------------------------------------

def find_trough(switches):
    """[(position, key)] ordered 1..N from the EJECT end, plus how it was found.

    `switches` is {(frame_byte, bit_mask): record}, the matrix UI's own table.
    The jam switch is excluded: it is not a ball position, it is "a ball is
    stuck on the kicker", and closing it reports a jam.
    """
    named = []
    unnamed = []
    for key, rec in switches.items():
        hay = _text(rec)
        if 'trough' not in hay or 'jam' in hay:
            continue
        m = _TROUGH_NUM.search(rec.get('symbol') or '') or _TROUGH_NUM.search(hay)
        if m:
            named.append((int(m.group(1)), key))
        else:
            unnamed.append(key)
    if named:
        named.sort()
        return [(n, k) for n, k in named], 'named switch_trough_N'
    if unnamed:
        # No numbers to order by.  Frame order is a SHAPE, not a reading, and
        # the caller must be able to see which of the two it got.
        return [(i + 1, k) for i, k in enumerate(sorted(unnamed))], \
               'frame order (UNVERIFIED - no numbered trough symbols)'
    return [], 'no trough switches on this title'


def find_jam(switches):
    for key, rec in switches.items():
        hay = _text(rec)
        if 'trough' in hay and 'jam' in hay:
            return key
    return None


def find_lane(switches):
    key, _rec = _match(list(switches.items()), LANE_PATTERNS)
    return key


def find_validate(switches):
    """A switch to pulse when a launched ball reaches the playfield, so the game
    marks the playfield valid and lets the ball proceed."""
    key, _rec = _match(list(switches.items()), VALIDATE_SW_PATTERNS)
    return key


def find_coil(coils, patterns):
    """(frame_byte, bit_mask, pulse_ms, symbol) for the first matching coil.

    Coils that carry no OUT address are skipped rather than returned half
    resolved: a coil we cannot watch is the same as a coil that is not there,
    and pretending otherwise makes the feeder silently never fire.
    """
    recs = [((c.get('frame_byte'), c.get('frame_bit')), c) for c in coils
            if c.get('frame_byte') is not None and c.get('frame_bit')]
    key, rec = _match(recs, patterns)
    if key is None:
        return None
    return (key[0], key[1], rec.get('pulse_ms') or 0, rec.get('symbol') or '')


# --------------------------------------------------------------------------
# The decisions.  Pure: no shm, no clock, no Tk - so they are testable.
# --------------------------------------------------------------------------

class Plan:
    """What to do, as steps a caller executes - or a refusal with a reason.

    A PLAN RATHER THAN A FUNCTION THAT DOES IT, because the interesting part of
    a ball feeder is the DECISION, and a decision needs testing without a
    running game, a mapped block or a sleep.  Steps are:

        ("set",  key, closed, what it means)
        ("wait", ms,          why)

    Refusals are normal traffic, not errors: "the game asked for a ball and the
    trough is empty" is exactly what a real machine puts LOCATING BALLS on the
    screen for, so it is logged rather than papered over with an invented ball.
    """

    def __init__(self, steps=None, refused=None):
        self.steps = list(steps or ())
        self.refused = refused

    def __bool__(self):
        return self.refused is None and bool(self.steps)

    def sets(self):
        return [(s[1], s[2]) for s in self.steps if s[0] == 'set']

    def text(self):
        if self.refused:
            return 'refused: ' + self.refused
        return '; '.join(s[3] for s in self.steps)


class Trough:
    """The trough, re-read from the switches every time it is asked.

    `positions` is find_trough()'s list - position 1 (the eject end) first - so
    this class never decides WHICH switches the trough is, only what the balls
    in it are doing.  Those are different jobs: which switches is a per-title
    lookup, and this is a rule about ramps that is the same on every machine.
    """

    def __init__(self, positions):
        self.positions = list(positions or ())

    def __len__(self):
        return len(self.positions)

    def flags(self, is_closed):
        return [bool(is_closed(k)) for _n, k in self.positions]

    def count(self, is_closed):
        return sum(1 for f in self.flags(is_closed) if f)

    def full(self, is_closed):
        return bool(self.positions) and self.count(is_closed) == len(self.positions)

    def leaving(self, is_closed):
        """The switch that OPENS when a ball is ejected, or None if empty.

        The highest-numbered MADE position, not "position k" derived from a
        count: identical on a contiguous trough, and only this one is still
        right when something has left a hole in the middle.
        """
        flags = self.flags(is_closed)
        for i in range(len(flags) - 1, -1, -1):
            if flags[i]:
                return self.positions[i][1]
        return None

    def arriving(self, is_closed):
        """The switch that CLOSES when a ball comes home, or None if full."""
        for (_n, key), made in zip(self.positions, self.flags(is_closed)):
            if not made:
                return key
        return None

    def anomaly(self, is_closed):
        """A sentence about a trough that is not a contiguous stack, or None.

        Worth its own answer rather than a silent correction: a hole in the
        middle means something moved a switch no ball could have moved.
        """
        flags = self.flags(is_closed)
        k = sum(1 for f in flags if f)
        if flags[:k] == [True] * k and flags[k:] == [False] * (len(flags) - k):
            return None
        made = [n for (n, _k), f in zip(self.positions, flags) if f]
        return ('trough is not a stack: %d balls at positions %s, expected 1..%d'
                % (k, ','.join(str(n) for n in made) or '-', k))


def plan_eject(trough, is_closed, lane, lane_made, flight_ms=FLIGHT_MS):
    """The game fired the trough eject.  Answer it.

    Two refusals, both real machine states rather than errors:

      * an EMPTY trough - a real machine finds nothing to kick, sees no switch
        change and goes to LOCATING BALLS.  Feeding a ball that does not exist
        would put the rig's count and the game's out of step permanently.
      * an OCCUPIED shooter lane - a ball cannot land on top of another one.
        This is also what folds a retry burst into one ball, since a game that
        has not seen its trough change re-pulses the coil.
    """
    if not trough.positions:
        return Plan(refused='no trough switches on this title')
    out = trough.leaving(is_closed)
    if out is None:
        return Plan(refused='the trough is empty - nothing to eject')
    if lane is not None and lane_made:
        return Plan(refused='a ball is already in the shooter lane')
    steps = [('set', out, False, 'trough opened (ball kicked out)')]
    if lane is not None:
        steps.append(('wait', flight_ms, 'ball in flight to the shooter lane'))
        steps.append(('set', lane, True, 'shooter lane closed (ball waiting)'))
    return Plan(steps)


def plan_launch(lane, lane_made):
    """The game fired the auto launcher, or a human plunged."""
    if lane is None:
        return Plan(refused='this title has no shooter-lane switch')
    if not lane_made:
        return Plan(refused='nothing in the shooter lane to launch')
    return Plan([('set', lane, False, 'shooter lane opened (ball launched)')])


def plan_drain(trough, is_closed):
    """A ball in play drained.  It arrives at the FAR end of the trough.

    THIS IS THE HALF NOTHING CAN OBSERVE, so it is an action and not an event.
    Until something says a ball drained it stays in play, which means a
    multiball can start but never end - and the game's ball counter would walk
    away from the rig's within one game.
    """
    if not trough.positions:
        return Plan(refused='no trough switches on this title')
    home = trough.arriving(is_closed)
    if home is None:
        return Plan(refused='the trough is already full - no ball is in play')
    return Plan([('set', home, True, 'trough closed (ball drained home)')])


# --------------------------------------------------------------------------
# The plumbing: resolution, edges, and putting a plan into the block
# --------------------------------------------------------------------------

class Feeder:
    """Watches the coils and answers them.

    Deliberately owns no clock and no scheduler of its own: `after(ms, fn)` is
    injected (Tk's root.after in the UI, an immediate runner in the tests) so
    the flight delay is real in the app and free in a test.
    """

    def __init__(self, shm, switches, coils, after, log=None, now=None,
                 flight_ms=FLIGHT_MS, min_gap_ms=MIN_GAP_MS,
                 auto_drain_s=AUTO_DRAIN_S, plunge_delay_s=PLUNGE_DELAY_S,
                 board=0):
        self.shm = shm
        self.after = after
        self.log = log or (lambda _m: None)
        self._now = now or (lambda: 0.0)
        self.flight_ms = flight_ms
        self.min_gap_ms = min_gap_ms
        self.auto_drain_s = auto_drain_s
        self.plunge_delay_s = plunge_delay_s
        self.board = board

        positions, how = find_trough(switches)
        self.trough = Trough(positions)
        self.how = how
        self.jam = find_jam(switches)
        self.lane = find_lane(switches)
        self.validate = find_validate(switches)
        self.eject = find_coil(coils, EJECT_COIL_PATTERNS)
        self.launch = find_coil(coils, LAUNCH_COIL_PATTERNS)

        # Everything that is NOT the ball path.  A change here is somebody
        # playing, which is the only evidence this rig has that a ball in play
        # is still alive.
        ball_path = {k for _n, k in self.trough.positions}
        ball_path.update(k for k in (self.jam, self.lane) if k is not None)
        self._watch = [k for k in switches if k not in ball_path]

        self._seen = {}         # coil -> last rise counter (None = not yet seen)
        self._last_feed = None
        self._said = {}
        self._shape = None
        self._activity = None   # last seen set of closed non-ball-path switches
        self._touched = None    # when that last changed
        self._draining = False  # mid auto-drain burst
        self._lane_since = None  # when a ball arrived in the shooter lane
        self.fed = 0
        self.launched = 0
        self.auto_drained = 0
        self.validated = 0

    # ------------------------------------------------------------- state
    def is_closed(self, key):
        return self.shm.get_switch(*key)

    def lane_made(self):
        return self.lane is not None and self.is_closed(self.lane)

    def in_trough(self):
        return self.trough.count(self.is_closed)

    def in_play(self):
        """Balls the game believes are out there - DERIVED, never counted.

        installed - trough - lane.  Clamped at zero: a human latching trough
        switches open can make this negative, and a negative ball count is a
        display bug, not a machine state.
        """
        return max(0, len(self.trough) - self.in_trough()
                   - (1 if self.lane_made() else 0))

    def usable(self):
        return bool(self.trough.positions) and self.eject is not None

    def describe(self):
        """What resolved to what.  EVERY LINE HAS BEEN WRONG ONCE somewhere."""
        out = []
        if self.trough.positions:
            out.append('trough %s (%s)'
                       % (','.join(str(n) for n, _k in self.trough.positions),
                          self.how))
        else:
            out.append('NO TROUGH SWITCHES - nothing can be fed')
        out.append('shooter lane %s'
                   % ('%d.%d' % (self.lane[0], self.lane[1].bit_length() - 1)
                      if self.lane else 'NOT FOUND'))
        out.append('validate switch %s'
                   % ('%d.%d' % (self.validate[0],
                                 self.validate[1].bit_length() - 1)
                      if self.validate else 'NOT FOUND - ball will not validate'))
        for what, coil in (('eject coil', self.eject), ('launch coil', self.launch)):
            if coil:
                out.append('%s %s (OUT %d.%d, %d ms)'
                           % (what, coil[3], coil[0], coil[1].bit_length() - 1,
                              coil[2]))
            else:
                out.append('%s NOT IN THE COIL TABLE - fires cannot be seen'
                           % what)
        return out

    # ------------------------------------------------------------- edges
    def fired(self, coil):
        """Has `coil` been driven since the last look?

        The first sight of a counter SEEDS it and reports nothing: coming up
        beside a run already in progress would otherwise read the whole run's
        fire count as one fire and feed a ball nobody asked for.
        """
        if coil is None:
            return False
        fb, mask = coil[0], coil[1]
        c = self.shm.out_rise(self.board, fb, mask.bit_length() - 1)
        was = self._seen.get((fb, mask))
        self._seen[(fb, mask)] = c
        return was is not None and c != was

    # ------------------------------------------------------------- acting
    def _say_once(self, what, msg):
        # Deduplicated PER MESSAGE, not against one last-said slot: an empty
        # trough refuses on every ball-search pulse while the launcher refuses
        # in between, and with a single slot the two take turns and each prints
        # again every cycle - which is the flood the dedup is for.
        if self._said.get(what) != msg:
            self._said[what] = msg
            self.log('%s %s' % (what, msg))

    def run_plan(self, plan, what):
        if plan.refused:
            self._say_once(what, plan.text())
            return False
        self._said.pop(what, None)
        self._run_steps(plan.steps, 0, what)
        return True

    def _run_steps(self, steps, i, what):
        while i < len(steps):
            step = steps[i]
            if step[0] == 'wait':
                self.after(int(step[1]),
                           lambda s=steps, j=i + 1: self._run_steps(s, j, what))
                return
            self.shm.set_switch(step[1][0], step[1][1], step[2])
            self.log('%s %s' % (what, step[3]))
            i += 1

    # ------------------------------------------------------------- the loop
    def poll(self):
        """One look at the wire.  Call it as often as you like."""
        if not self.usable():
            return False

        shape = self.trough.anomaly(self.is_closed)
        if shape != self._shape:
            self._shape = shape
            if shape:
                self.log(shape)

        fed = False
        if self.fired(self.eject):
            now = self._now()
            if (self._last_feed is not None
                    and (now - self._last_feed) * 1000.0 < self.min_gap_ms):
                self._say_once('eject:',
                               'refused: %.0f ms after the last one - a retry '
                               'or a chopped drive (min gap %d ms)'
                               % ((now - self._last_feed) * 1000.0,
                                  self.min_gap_ms))
            elif self.run_plan(plan_eject(self.trough, self.is_closed, self.lane,
                                          self.lane_made(), self.flight_ms),
                               'eject:'):
                self._last_feed = now
                self.fed += 1
                fed = True
        if self.fired(self.launch):
            if self.run_plan(plan_launch(self.lane, self.lane_made()),
                             'launch:'):
                self.launched += 1
                self._on_launch()
        self._track_lane()
        self._auto_plunge()
        self._auto_drain()
        return fed

    # --------------------------------------------------------- launch / plunge
    def _track_lane(self):
        """Remember when a ball first sat in the shooter lane, so the auto-plunge
        can time out from there."""
        if self.lane_made():
            if self._lane_since is None:
                self._lane_since = self._now()
        else:
            self._lane_since = None

    def _auto_plunge(self):
        """A ball parked in the shooter lane with nobody plunging: launch it, the
        way a real ball leaves the lane.  A human plunge would have cleared the
        lane first; the game does NOT auto-launch on JJP, so without this the
        ball sits in the lane and the game never advances past the skill shot."""
        if not self.plunge_delay_s or self.lane is None:
            return
        if not self.lane_made() or self._lane_since is None:
            return
        if self._now() - self._lane_since < self.plunge_delay_s:
            return
        if self.run_plan(plan_launch(self.lane, self.lane_made()), 'plunge:'):
            self.launched += 1
            self._on_launch()

    def _on_launch(self):
        """A ball just left the shooter lane.  After a short flight, pulse a
        validation switch so the game marks the playfield valid and the
        ball-start / skill-shot logic proceeds (without it the ball reads as
        never having reached the playfield and the game stalls)."""
        self._lane_since = None
        k = self.validate
        if k is None:
            return

        def hit():
            self.shm.set_switch(k[0], k[1], True)
            self.after(60, lambda: self.shm.set_switch(k[0], k[1], False))
            self.validated += 1
            self.log('validate: playfield switch pulsed (ball in play)')
        self.after(self.flight_ms, hit)

    def _auto_drain(self):
        """Bring a forgotten ball home, because a real one would come home.

        The rig cannot see the playfield, so it watches the only proxy it has:
        any switch outside the ball path changing means somebody is playing and
        the ball is alive.  Nothing at all for auto_drain_s means it drained.
        """
        if not self.auto_drain_s:
            return
        now = self._now()
        state = frozenset(k for k in self._watch if self.is_closed(k))
        if state != self._activity or self._touched is None:
            self._activity = state
            self._touched = now
            self._draining = False
            return
        if self.in_play() <= 0:
            self._draining = False
            return
        if now - self._touched < self.auto_drain_s:
            return
        # The clock ran out, so every ball still out there drained - a machine
        # that flung five balls out during its own ball search gets them all
        # back within a second of each other, not one every timeout.  The
        # explanation is logged once per burst; the drains themselves log
        # individually through run_plan.
        if not self._draining:
            self._draining = True
            self.log('drain: nothing touched the playfield for %.0f s - '
                     'bringing %d ball(s) home (nobody was flipping)'
                     % (self.auto_drain_s, self.in_play()))
        if self.run_plan(plan_drain(self.trough, self.is_closed), 'drain:'):
            self.auto_drained += 1

    # ------------------------------------------------------------- actions
    def drain(self):
        """A ball in play came home.  The only half nothing can observe."""
        return self.run_plan(plan_drain(self.trough, self.is_closed), 'drain:')

    def plunge(self):
        """A human worked the shooter.  Same effect as the auto launcher, and it
        validates the playfield the same way an auto-plunge does."""
        self._touched = self._now()     # somebody is playing
        self._draining = False
        ok = self.run_plan(plan_launch(self.lane, self.lane_made()), 'plunge:')
        if ok:
            self._on_launch()
        return ok

    def seat_trough(self):
        """Fill the trough and clear the ball path - the machine at rest.

        Everything here is in BALL-PRESENT terms; SwitchShm does the electrical
        polarity, including the inverted-opto flip, so a "present" trough switch
        lands as an open opto beam.  Without this the game shows BALL TROUGH
        ERROR before anything else can happen.  The jam is left NOT present (a
        present jam reads as a ball stuck on the kicker); the shooter lane stays
        empty - a ball waiting in the lane at power-up is not a resting machine.
        """
        for _n, key in self.trough.positions:
            self.shm.set_switch(key[0], key[1], True)
        if self.jam is not None:
            self.shm.set_switch(self.jam[0], self.jam[1], False)
        if self.lane is not None:
            self.shm.set_switch(self.lane[0], self.lane[1], False)
        return [key for _n, key in self.trough.positions]

    def status(self):
        n = len(self.trough)
        if not n:
            return 'no trough'
        return ('balls %d/%d trough%s   in play %d   fed %d'
                % (self.in_trough(), n,
                   '  lane 1' if self.lane_made() else '',
                   self.in_play(), self.fed))

    def settings(self):
        return ('flight %d ms   min gap %d ms   auto-drain %s   auto-plunge %s'
                % (self.flight_ms, self.min_gap_ms,
                   ('%.0f s' % self.auto_drain_s) if self.auto_drain_s
                   else 'off',
                   ('%.1f s' % self.plunge_delay_s) if self.plunge_delay_s
                   else 'off'))
