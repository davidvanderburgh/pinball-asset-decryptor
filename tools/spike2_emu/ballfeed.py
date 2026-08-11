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

#: How long the padled block may stay unreadable before this decides the run is
#: over. watch.sh's teardown removes dump/padled precisely so a reader can tell
#: (the same signal the playfield window uses), but a rebuild or a slow
#: teardown can make one read fail, so it takes a few in a row.
GONE_S = 3.0


def say(msg):
    """One line, flushed. watch.sh folds this into the run log."""
    sys.stdout.write("[ball] %s\n" % msg)
    sys.stdout.flush()


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
        return True

    def poll(self, m, d, now):
        """One look at the wire. Returns True if a ball was fed."""
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
                    fed = True
                    mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
                    say("trough %d/%d after the feed"
                        % (self.trough.count(mrg), len(self.trough.positions)))
        if self.fired(d, self.plunge_coil):
            lane_made = (self.lane is not None
                         and bool(padsw.merged(m, self.lane)))
            self.run_plan(m, ballmodel.plan_launch(self.lane, lane_made),
                          "auto plunger:")
        return fed


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
        say("nothing to do on this title - exiting rather than idling")
        return 1
    m = padsw.open_block()
    if m is None:
        return 2
    say("watching for the game's trough eject (%.0f Hz, flight %.0f ms, "
        "min gap %.0f ms)%s"
        % (HZ, FLIGHT_S * 1000, MIN_GAP_S * 1000, ", DRY RUN" if dry else ""))

    period, gone_since = 1.0 / max(1.0, HZ), None
    while True:
        d = read_led()
        if d is None:
            # The run going away is the ordinary way this exits: watch.sh's
            # teardown removes dump/padled by design so readers can tell.
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since > GONE_S:
                say("no padled block for %.0f s - the run is over, %d ball(s) "
                    "fed" % (GONE_S, f.fed))
                break
        else:
            gone_since = None
            if f.poll(m, d, time.monotonic()) and once:
                break
        time.sleep(period)
    m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
