#!/usr/bin/env python3
"""ballfeed.py - answer the game's trough eject with a ball. REMAINING item 21b.

    ballfeed.py            run until the game goes away  (watch.sh starts this)
    ballfeed.py --status   what it resolved and what the trough says, then exit
    ballfeed.py --dry-run  decide and log, write no switches
    ballfeed.py --once     answer one eject, then exit

THE LOOP THIS CLOSES. The game fires the trough eject coil and waits for a
trough switch to change. Nothing in this rig ever answered, so `plunge.py
start` left the trough reading 6 of 6 and the only thing that ever moved a ball
was a human running `plunge.py plunge` - which means every ball the rig has
"played" was moved by a script pretending, and multiball, which is the game
firing that coil again and again, had nobody to talk to.

WHY IT RUNS INSIDE WSL. Every host-side switch action is a ~80 ms wsl.exe spawn
(measured, item 24), and item 26 worked out what that caps a host-side pulse
loop at: about six actions a second while saturating the click queue. Here the
padled block is a local file and padsw is a local mmap, so a poll is a couple
of microseconds and the answer to an eject is a memory write. It also means the
feeder keeps working with no playfield window open, which matters because the
window is a Windows process and optional.

WHY IT POLLS A COUNTER AND NOT A LEVEL. `coil_publish()` in hwshim.c bumps a
per-(node, index) byte for every fire frame it decodes. A coil is addressed for
tens of milliseconds, so a level would be missed about half the time at any
sane poll rate; a counter cannot be missed, only coalesced.

THE RIG NEVER REMEMBERS A REQUEST, AND THAT IS DELIBERATE. Every eject is
answered or refused on the spot and refusals are logged. The game's own retry
is the queue: a machine that has not seen its trough change re-pulses the coil,
so a request that could not be served now comes back by itself. Holding one
instead would have made a retry burst indistinguishable from a multiball feed,
and would have fed the queued ball at some later moment nobody asked for.

THE ONE GUESSED NUMBER IS THE MINIMUM GAP. A retry burst and a multiball feed
are the same coil at different spacings, and only a measured multiball can say
where the line is. PAD_BALL_MIN_GAP_MS (default 600) refuses a second ball
inside that window and LOGS that it did, so the number is visible and tunable
rather than silently deciding how many balls a multiball gets.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ballmodel
import coilmap
import gameinfo
import padpath
import padsw
import trough

padsw.set_source('b')   # who the [sw] log says moved a switch; see padsw.h.

#: PAD_LED_FILE is the twin of padsw.py's PAD_SW_FILE - it points this at a
#: block that is not a running game's, which is the only way to test the whole
#: feeder without an emulator. The rig never sets either.
LED_PATH = os.environ.get("PAD_LED_FILE",
                          os.path.join(padpath.dump() or "", "padled"))


def _num(name, default):
    try:
        return type(default)(os.environ[name])
    except (KeyError, ValueError):
        return default


HZ = _num("PAD_BALL_HZ", 50.0)
FLIGHT_S = _num("PAD_BALL_LANE_MS", 350) / 1000.0
MIN_GAP_S = _num("PAD_BALL_MIN_GAP_MS", 600) / 1000.0

#: ANSWER THE AUTO PLUNGER? ON - and the launched ball COMES HOME (below),
#: which is the piece whose absence broke this knob in BOTH positions.
#:
#: MEASURED 2026-08-27 on dungeons_and_dragons_le, which auto-plunges where
#: godzilla waits for a hand plunge, in two acts:
#:
#: ON without a way home (the original behaviour): the game ejects, this
#: feeder lands the ball in the lane, the game fires the AUTO PLUNGER,
#: answering it opened the lane - and the ball left for a playfield that does
#: not exist and simply vanished. The game asked again ~7 s later and the loop
#: emptied the whole trough inside a minute; a machine with no balls refuses
#: Start entirely.
#:
#: OFF (the first fix, same day): the ball stays in the lane, and the game
#: fires the plunger again and again at a switch that never moves - until it
#: declares **Device Malfunction: Auto Plunger** (visible under Diagnostics >
#: Technician Alerts), stops firing the plunger at all, falls into a
#: trough+diverter search pulse every ~8 s, and REFUSES START in attract for
#: ever. The one observed "STANDARD GAME MODE" success was this race caught
#: before the malfunction latched; it did not reproduce.
#:
#: So the launch must be answered - the game is watching the lane switch to
#: confirm its coil works - and the ball must then come home unless a human
#: is actually playing it. PAD_BALL_AUTOPLUNGE=0 restores the dead-plunger
#: behaviour for measurement.
AUTO_PLUNGE = _num("PAD_BALL_AUTOPLUNGE", 1)

#: THE WAY HOME. A real machine's launched ball rolls the playfield and, with
#: nobody at the flippers, drains to the trough a few seconds later. This rig
#: has no playfield, so that return is an action here: PAD_BALL_HOME_MS
#: (default 5000) after an answered launch, the ball drains home - UNLESS
#: somebody is PLAYING it (`_claim` below). Attract/ball-search cycles have
#: nobody at the controls, so their balls always come home - which is exactly
#: what the game's search is waiting to see, and what clears (and never
#: re-raises) the malfunction above. 0 disables the way home.
HOME_S = _num("PAD_BALL_HOME_MS", 5000) / 1000.0

#: WHO COUNTS AS SOMEBODY PLAYING, on the SCRIPT side of the block - the
#: source letters padsw.h lists, of the writers that are a person moving a
#: switch rather than the rig moving one by itself.
#:
#: ★ PAD-134, AND IT IS THE HALF PAD-128 LEFT BEHIND. The test used to be the
#: KEYBOARD generation alone, which reads as "a human is playing" only if a
#: human has a keyboard in this: the virtual playfield window drives every
#: switch through these helpers (`PAD_SW_SRC=f`, playfield.wsl_run), and
#: padglhost's array never moves for a mouse. So a MOUSE-ONLY session - the
#: thing PAD-128's Insert coin button made possible end to end - had the
#: feeder decide nobody was playing and drain the live ball back to the trough
#: 5 s after the game auto-launched it. With BALL SAVE on that is every ball:
#: the game re-serves and fires its own AUTO PLUNGER (measured on godzilla_pro,
#: item 21b's live run), so each drain started an eject/launch/drain cycle
#: behind the player's back, and their own drain click then landed on a trough
#: the feeder had already filled ("the trough is already full").
#:
#: The rig's OWN automation is deliberately not in here - `a` autoattract,
#: `x` swexercise, `g` longplay, `i` swinit, `r` swreplay, `b` this feeder -
#: because those run with nobody watching and their balls are exactly the ones
#: that must come home.
#:
#: The keyboard is not in here because it has its own generation and any move
#: of it still counts, exactly as it did before.
HUMAN_TAGS = "flhpc"

#: How long the padled block may stay unreadable before this decides the run is
#: over. watch.sh's teardown removes dump/padled precisely so a reader can tell
#: (the same signal the playfield window uses), but a rebuild or a slow
#: teardown can make one read fail, so it takes a few in a row.
GONE_S = 3.0

#: How long to wait for a first run's switch table before concluding this
#: title genuinely has nothing to feed (item 49). mktables derives the table
#: from the run's own [sw] dump about a minute in; watch.sh's own budget for
#: that wait is PAD_PF_WAIT (default 120 s), so this sits comfortably above
#: it rather than racing it.
TABLE_WAIT_S = _num("PAD_BALL_TABLE_WAIT_S", 300.0)


#: THE WINDOW'S COPY OF WHAT THIS SAYS (PAD-134). The virtual playfield is a
#: Windows process and ~/padball.log is a file inside WSL it never opens, so
#: every sentence below reached the run log and nobody at the window. David,
#: comparing with the JJP window: its BALLS section shows the keeper's count
#: and its newest three messages right under Plunge and Drain, and ours showed
#: six dots. So the feeder publishes the same two things into dump/ - `fed N`
#: then its newest lines, oldest first - by tmp+rename, the padbinds rule, so
#: a reader over \\wsl.localhost never parses half a file. watch.sh clears it
#: at start so a window never shows the LAST run's lines. PAD_BALL_FILE points
#: it somewhere else, which ballfeedtest.py does so it touches nothing real.
STATUS_PATH = (os.environ.get("PAD_BALL_FILE")
               or os.path.join(padpath.dump() or "", "padball"))
STATUS_LINES = 3
_recent = []
_fed = 0


def publish(fed=None):
    """Rewrite the status file. Best-effort: a failed write costs the window
    one stale line, never the feeder its loop."""
    global _fed
    if fed is not None:
        _fed = fed
    tmp = STATUS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf8", newline="\n") as f:
            f.write("fed %d\n" % _fed)
            for line in _recent:
                f.write(line + "\n")
        os.replace(tmp, STATUS_PATH)
    except OSError:
        pass


def say(msg):
    """One line, flushed. watch.sh folds this into the run log, and the
    playfield window shows the newest few (publish)."""
    sys.stdout.write("[ball] %s\n" % msg)
    sys.stdout.flush()
    _recent.append(msg)
    del _recent[:-STATUS_LINES]
    publish()


def read_led():
    """The padled block's bytes, or None when there is no run."""
    try:
        with open(LED_PATH, "rb") as f:
            d = f.read(coilmap.PADLED_READ)
    except OSError:
        return None
    return d if coilmap.has_magic(d) else None


class Feeder:
    """Resolution, decisions and the writes - kept apart on purpose.

    The DECISIONS are all in ballmodel and are tested offline against arrays
    written by hand; what is left here is the plumbing that cannot be: which
    switches and coils this title has, when a fire happened, and putting a
    plan's steps into the block.
    """

    def __init__(self, game=None, dry=False):
        self.dry = dry
        self.game = gameinfo.active(game)
        rows = trough.load_list(gameinfo.table("switch_list.txt", self.game)
                                or "")
        positions, how = trough.find(rows)
        self.trough = ballmodel.Trough(positions)
        self.how = how
        self.lane = self._switch(rows, ballmodel.LANE_NAME)
        coils = coilmap.load(gameinfo.table("device_xy.txt", self.game) or "")
        self.eject_coil = coilmap.address(coils, coilmap.TROUGH)
        self.plunge_coil = coilmap.address(coils, coilmap.AUTO_PLUNGER)
        self.seen = {}
        self.last_feed = 0.0
        self.said = {}
        self.shape = None
        self.fed = 0
        #: (launch time, claim at launch) per feeder-answered launch that is
        #: still out with nobody playing it. Only launches THIS feeder answered
        #: are candidates for the way home - plunge.py and the playfield window
        #: manage their own balls.
        #:
        #: ★ A LIST, NOT ONE SLOT (PAD-134). It was a single slot, so the
        #: second launch overwrote the first and that ball could never come
        #: home: the game goes on believing it is in play, which is a START
        #: that refuses and a LOCATING BALLS search that never ends. A
        #: multiball is the game doing this on purpose - three ejects, three
        #: auto plunges - and a ball-save re-serve does it by accident the
        #: moment two launches overlap.
        self.pending = []
        #: The script generation as WE last left it, so another writer's bump
        #: is distinguishable from our own. Seeded on the first look.
        self.my_gen = None
        #: How many times somebody who is not this feeder's own automation has
        #: moved a switch. A counter and not a flag because it has to survive
        #: our own writes in between - see _claim().
        self.hands = 0

    @staticmethod
    def _switch(rows, name):
        want = name.upper().strip()
        for r in rows:
            if (r.get("name") or "").upper().strip() == want:
                return r["id"]
        return None

    def describe(self):
        """What was resolved, in the words a run log should carry.

        EVERY LINE OF THIS IS A THING THAT HAS BEEN WRONG ONCE. The trough ids
        are per title and a hard-coded set made every non-Godzilla title
        ball-search for ever (item 27); the coil node is per title too
        (godzilla_pro group 6 -> node 8, jaws_le group 7 -> node 9); and the
        `assumed` fallback is a shape, not a reading, so a run must be able to
        see which of the two it got.
        """
        out = ["title %s" % (self.game or "(unknown)")]
        if self.trough.positions:
            out.append("trough %s (%s) = %s"
                       % (",".join(str(P["pos"]) for P in self.trough.positions),
                          self.how,
                          ",".join(str(i) for i in self.trough.ids)))
        else:
            out.append("NO TROUGH SWITCHES - nothing can be fed")
        out.append("shooter lane %s"
                   % (self.lane if self.lane is not None else "NOT FOUND"))
        out.append("eject coil %s"
                   % ("node %d index %d" % self.eject_coil if self.eject_coil
                      else "NOT IN THE DEVICE TABLE - ejects cannot be seen"))
        out.append("auto plunger %s"
                   % ("node %d index %d" % self.plunge_coil if self.plunge_coil
                      else "not in the device table"))
        return out

    def usable(self):
        return bool(self.trough.positions) and self.eject_coil is not None

    def fired(self, d, coil):
        """Has `coil` been addressed since the last look?

        The first sight of a counter SEEDS it and reports nothing. Coming up
        beside a run that has been going for a while would otherwise read the
        whole run's fire count as one fire and feed a ball nobody asked for.
        """
        if coil is None:
            return False
        c = coilmap.counter(d, coil[0], coil[1])
        if c is None:
            return False
        was = self.seen.get(coil)
        self.seen[coil] = c
        return was is not None and c != was

    def run_plan(self, m, plan, what):
        if plan.refused:
            # Deduplicated PER MESSAGE, not against one last-said slot. An
            # empty trough refuses on every ball-search pulse the game makes,
            # and the auto plunger refuses in between - with a single slot the
            # two take turns and each one prints again every cycle, which is
            # the flood the dedup was there to stop. Caught by ballfeedtest.py.
            if self.said.get(what) != plan.refused:
                self.said[what] = plan.refused
                say("%s %s" % (what, plan.text()))
            return False
        self.said.pop(what, None)
        padsw.take(m, [sw for sw, _ in plan.switches()])
        for step in plan.steps:
            if step[0] == "wait":
                if not self.dry:
                    time.sleep(step[1])
                continue
            if not self.dry:
                padsw.set_held(m, step[1], step[2])
            say("%s%s" % ("would: " if self.dry else "", step[3]))
        # OUR OWN BUMP IS NOT A PAIR OF HANDS. take() and set_held() both move
        # the script generation, so _claim() would read the feeder answering an
        # eject as somebody playing and cancel the way home of every ball it
        # had already launched - the stranded-ball fault this file just fixed,
        # from the other end. Recorded here because this is the one place the
        # feeder writes.
        self.my_gen = self._u32(m, padsw.OFF_SCR_GEN)
        return True

    def poll(self, m, d, now):
        """One look at the wire. Returns True if a ball was fed."""
        claim = self._claim(m)
        lane_made = (self.lane is not None
                     and bool(padsw.merged(m, self.lane)))
        mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]

        shape = self.trough.anomaly(mrg)
        if shape != self.shape:
            self.shape = shape
            if shape:
                say(shape)

        fed = False
        if self.fired(d, self.eject_coil):
            if now - self.last_feed < MIN_GAP_S:
                say("eject %.0f ms after the last one - refused as a retry "
                    "(PAD_BALL_MIN_GAP_MS=%d)"
                    % ((now - self.last_feed) * 1000, MIN_GAP_S * 1000))
            else:
                plan = ballmodel.plan_eject(self.trough, mrg, self.lane,
                                            lane_made, FLIGHT_S)
                if self.run_plan(m, plan, "eject:"):
                    self.last_feed = time.monotonic()
                    self.fed += 1
                    publish(self.fed)
                    fed = True
                    mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
                    say("trough %d/%d after the feed"
                        % (self.trough.count(mrg), len(self.trough.positions)))
        if self.fired(d, self.plunge_coil) and AUTO_PLUNGE:
            lane_made = (self.lane is not None
                         and bool(padsw.merged(m, self.lane)))
            if self.run_plan(m, ballmodel.plan_launch(self.lane, lane_made),
                             "auto plunger:"):
                # The claim from the TOP of this poll, not a fresh read: our own
                # launch write has moved the script generation by now, and
                # _claim() has already adopted it.
                self.pending.append((now, claim))
        self._way_home(m, now, claim)
        return fed

    @staticmethod
    def _u32(m, off):
        return struct.unpack_from("<I", m, off)[0]

    def _claim(self, m):
        """Is anybody PLAYING? Returned as one tuple that only moves forward.

        Three counters, because the rig has three ways for a person to move a
        switch and the feeder used to be able to see only one of them:

          * `gen`      padglhost's KEYBOARD array - real key events, flippers
                       included. Any move of it counts, as it always has.
          * `hands`    this feeder's own count of SCRIPT writes that were not
                       its own automation. The playfield window runs every
                       helper with `PAD_SW_SRC=f` (playfield.wsl_run), so a
                       mouse click on the artwork, the plunger, a trough dot or
                       an action button lands here - which is the whole of
                       PAD-134. `HUMAN_TAGS` says which letters count.
          * `spin_gen` swspin.py's rip array (item 26), which a right-hold on a
                       spinner writes and which touches neither of the others.
                       DragonRR's report is a Mechagodzilla spinner being
                       clicked, so leaving this out would miss the very input
                       the mail describes.

        A COUNTER RATHER THAN A FLAG for the script half, and that is the
        non-obvious part: the feeder writes the same generation itself, so
        "has it moved since the launch" is only answerable by adopting our own
        bumps as they happen (run_plan) and counting everybody else's. A
        comparison against a remembered generation would be erased by the next
        eject the feeder answered.

        Called ONCE per poll, before the feeder writes anything, because it
        mutates `my_gen`/`hands`.
        """
        g = self._u32(m, padsw.OFF_SCR_GEN)
        if self.my_gen is None:
            self.my_gen = g                  # first look seeds, like fired()
        elif g != self.my_gen:
            self.my_gen = g
            tag = chr(self._u32(m, padsw.OFF_SCR_SRC) & 0xFF)
            if tag in HUMAN_TAGS:
                self.hands += 1
        return (self._u32(m, padsw.OFF_GEN), self._u32(m, padsw.OFF_SPIN_GEN),
                self.hands)

    def _way_home(self, m, now, claim):
        """A launched ball nobody is playing drains back to the trough.

        See the HOME_S comment at the top for why this exists and `_claim` for
        what counts as somebody playing. Cancelling is one-way on purpose: once
        a person has touched the machine the balls are theirs, even if they then
        go quiet - the playfield window's drain click is how they end.

        ONE BALL PER POLL, deliberately. `plan_drain` is derived from the
        MERGED array, which the guest republishes after our write, so two
        drains in one pass could both read the same hole and put two balls in
        one trough position. At 50 Hz the next one is 20 ms later and the
        timers they are waiting on are a second apart anyway.
        """
        if not self.pending or not HOME_S:
            return
        if any(c != claim for _, c in self.pending):
            n = len(self.pending)
            self.pending = []
            say("somebody is playing - %d launched ball(s) stay in play "
                "until Drain" % n)
            return
        if now - self.pending[0][0] < HOME_S:
            return
        t0, _ = self.pending.pop(0)
        mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
        if self.run_plan(m, ballmodel.plan_drain(self.trough, mrg),
                         "way home:"):
            say("launched ball came home untouched (%.1f s, nobody at the "
                "controls)%s"
                % (now - t0,
                   ", %d still out" % len(self.pending) if self.pending
                   else ""))


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    once = "--once" in args
    f = Feeder(dry=dry)
    for line in f.describe():
        say(line)

    if "--status" in args:
        d = read_led()
        m = padsw.open_block()
        if m is None:
            return 2
        mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
        b = trough.Balls()
        b.update(f.trough.flags(mrg))
        say(b.text())
        say("padled %s" % ("readable" if d else "NOT readable - no run?"))
        if d and f.eject_coil:
            say("eject coil counter now %d"
                % coilmap.counter(d, f.eject_coil[0], f.eject_coil[1]))
        say(f.trough.anomaly(mrg) or "trough is a contiguous stack")
        m.close()
        return 0

    if not f.usable():
        # ★ ITEM 49: WAIT FOR THE TABLE, THE WAY THIS FILE ALREADY WAITS FOR
        # dump/padled BELOW. On a title's FIRST run the switch list does not
        # exist when watch.sh starts this - mktables derives it from the
        # run's own [sw] dump about a minute in - and exiting here meant the
        # whole first run went feederless after one log line: the game fired
        # its trough eject, nothing answered, and multiball died silently.
        # "Not yet" and "never" are different things, same as the padled
        # lesson at the bottom of this file. Bounded rather than forever:
        # the table has no teardown-removal signal the way padled does, so
        # a title that genuinely has no trough must not idle for the whole
        # run - past the deadline the old exit is the right answer.
        deadline = time.monotonic() + TABLE_WAIT_S
        said_wait = False
        while not f.usable() and time.monotonic() < deadline:
            if not said_wait:
                said_wait = True
                say("switch table not here yet - waiting up to %.0f s for "
                    "mktables to derive it from this run's own dump"
                    % TABLE_WAIT_S)
            time.sleep(2.0)
            f = Feeder(dry=dry)
        if f.usable():
            say("switch table arrived - resolved:")
            for line in f.describe():
                say(line)
        else:
            say("nothing to do on this title - exiting rather than idling")
            return 1
    m = padsw.open_block()
    if m is None:
        return 2
    say("watching for the game's trough eject (%.0f Hz, flight %.0f ms, "
        "min gap %.0f ms)%s"
        % (HZ, FLIGHT_S * 1000, MIN_GAP_S * 1000, ", DRY RUN" if dry else ""))

    period, gone_since, ever = 1.0 / max(1.0, HZ), None, False
    while True:
        d = read_led()
        if d is None:
            # NOT YET AND GONE ARE DIFFERENT THINGS, and reading them as one
            # made this exit before it had ever done anything - caught on the
            # first live run, which the offline harness could not have caught
            # because it writes the block before it starts anything. The shim
            # creates dump/padled LAZILY, on the first LED frame it decodes,
            # so a feeder started by watch.sh comes up a minute or so ahead of
            # it. Waiting is right until the block has been seen once; after
            # that, it going away is watch.sh's teardown and means the run is
            # over (removing it is deliberate, so readers can tell).
            if ever:
                gone_since = gone_since or time.monotonic()
                if time.monotonic() - gone_since > GONE_S:
                    say("no padled block for %.0f s - the run is over, "
                        "%d ball(s) fed" % (GONE_S, f.fed))
                    break
            time.sleep(0.5)
            continue
        if not ever:
            ever = True
            say("padled block is up - watching")
        gone_since = None
        if f.poll(m, d, time.monotonic()) and once:
            break
        time.sleep(period)
    m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
