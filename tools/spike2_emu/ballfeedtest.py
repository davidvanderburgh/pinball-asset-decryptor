#!/usr/bin/env python3
"""ballfeedtest.py [title] - drive the REAL ballfeed.py against a fake machine.

    ballfeedtest.py                 godzilla_pro, from its real built tables
    ballfeedtest.py jaws_le         any title with tables on this machine

WHY THIS EXISTS RATHER THAN MORE UNIT TESTS. The unit tests (item 21b,
tests/test_spike2_ball_model.py) check the DECISIONS against arrays written by
hand, and they are what they are worth: fast, and blind to everything between
the decision and the wire. This runs the actual script, as a subprocess, with
the actual switch block and the actual coil counter, and the only thing faked
is the machine on the far side. It is the same shape as ledratetest.py, and it
is here for the same reason: a run costs minutes and cannot be repeated
cheaply, and the two faults this rig keeps having are a helper that resolves
the wrong ids and a helper that writes into a region nobody reads.

THE MERGE IS THE PART THAT HAS TO BE FAKED, and getting it wrong would make
this harness agree with a broken feeder. On a real run the guest shim computes
mrg[] from the keyboard's array and the scripts' array by last-edge-wins;
here there is no keyboard, so mrg[] is simply scr_held[] and a thread copies
one to the other whenever the script generation moves. That is exactly what
the shim would do with one writer, and it means the feeder's next decision
sees its own last one - which is the property the whole thing turns on.

IT TOUCHES NOTHING REAL. PAD_SW_FILE and PAD_LED_FILE point at scratch files
under /var/tmp (never /tmp - tmpfs, wiped on a WSL restart), and PAD_TABLES
points at the title's real tables, read only.
"""
import os
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coilmap
import padpath
import padsw
import trough

SCRATCH = "/var/tmp/padballtest"


def make_blocks(trough_ids):
    """A machine at rest: six balls home, everything else open."""
    os.makedirs(SCRATCH, exist_ok=True)
    sw = os.path.join(SCRATCH, "padsw")
    led = os.path.join(SCRATCH, "padled")
    b = bytearray(4096)
    struct.pack_into("<I", b, padsw.OFF_MAGIC, padsw.MAGIC)
    for i in trough_ids:
        b[padsw.OFF_SCR_HELD + i] = 1
        b[padsw.OFF_MRG + i] = 1
    open(sw, "wb").write(bytes(b))
    d = bytearray(coilmap.PADLED_READ)
    struct.pack_into("<I", d, 0, coilmap.PADLED_MAGIC)
    open(led, "wb").write(bytes(d))
    return sw, led


class Shim(threading.Thread):
    """The one thing the guest does that this test cannot do without."""

    daemon = True

    def __init__(self, path):
        threading.Thread.__init__(self)
        import mmap
        self.m = mmap.mmap(os.open(path, os.O_RDWR), 4096)
        self.stop = False

    def run(self):
        last = -1
        while not self.stop:
            gen = struct.unpack_from("<I", self.m, padsw.OFF_SCR_GEN)[0]
            if gen != last:
                last = gen
                for i in range(padsw.MAX_ID):
                    self.m[padsw.OFF_MRG + i] = self.m[padsw.OFF_SCR_HELD + i]
                struct.pack_into("<I", self.m, padsw.OFF_MRG_GEN, gen)
            time.sleep(0.005)

    def merged(self, sw):
        return self.m[padsw.OFF_MRG + sw]

    def count(self, ids):
        return sum(1 for i in ids if self.m[padsw.OFF_MRG + i])


class Wire:
    """The coil counters, bumped the way coil_publish() bumps them."""

    def __init__(self, path):
        import mmap
        self.m = mmap.mmap(os.open(path, os.O_RDWR), coilmap.PADLED_READ)

    def fire(self, addr):
        if addr is None:
            return
        o = coilmap.COIL_OFF + addr[0] * coilmap.COIL_N + addr[1]
        self.m[o] = (self.m[o] + 1) & 0xFF


def plunge_lane_ball(shim, lane):
    """Put a ball in the shooter lane the way the FEEDER would have.

    Written into the script region and published, not straight into mrg[]:
    the fake shim copies one to the other, so going round it would set up a
    state the real merge could never produce and the next thing to write a
    switch would stomp.
    """
    if lane is None:
        return
    shim.m[padsw.OFF_SCR_HELD + lane] = 1
    struct.pack_into("<I", shim.m, padsw.OFF_SCR_GEN,
                     struct.unpack_from("<I", shim.m, padsw.OFF_SCR_GEN)[0] + 1)
    time.sleep(0.1)


def window_click(shim, sw, tag="f"):
    """A click on the virtual playfield, as the WINDOW itself makes one.

    The window never writes this block directly: it runs the rig's helpers
    inside WSL with `PAD_SW_SRC=f` (playfield.wsl_run), so what reaches the
    guest is a SCRIPT write carrying that letter - which is the only evidence
    the feeder has that a person with a mouse is playing (PAD-134). Press and
    release, because that is what a click is, and the source letter goes in
    BEFORE the generation exactly as padsw.bump() writes it.
    """
    for val in (1, 0):
        shim.m[padsw.OFF_SCR_HELD + sw] = val
        struct.pack_into("<I", shim.m, padsw.OFF_SCR_SRC, ord(tag))
        struct.pack_into("<I", shim.m, padsw.OFF_SCR_GEN,
                         struct.unpack_from("<I", shim.m,
                                            padsw.OFF_SCR_GEN)[0] + 1)
        time.sleep(0.08)


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else "godzilla_pro"
    tables = os.path.join(padpath.tables() or "", game)
    rows = trough.load_list(os.path.join(tables, "switch_list.txt"))
    positions, how = trough.find(rows)
    coils = coilmap.load(os.path.join(tables, "device_xy.txt"))
    eject = coilmap.address(coils, coilmap.TROUGH)
    plunger = coilmap.address(coils, coilmap.AUTO_PLUNGER)
    lane = next((r["id"] for r in rows
                 if (r["name"] or "").upper().strip() == "SHOOTER LANE"), None)
    if not positions or eject is None:
        print("FAIL: %s has no trough (%s) or no eject coil (%s)"
              % (game, how, eject))
        return 1
    ids = [P["id"] for P in positions]
    print("%s: trough %s (%s), lane %s, eject coil node %d index %d"
          % (game, ids, how, lane, eject[0], eject[1]))

    sw, led = make_blocks(ids)
    shim = Shim(sw)
    shim.start()
    wire = Wire(led)

    # PAD_BALL_HOME_MS=0 FOR THIS BLOCK, and it is not a detail. These checks
    # are about the FEED - how many balls an eject burst puts in play and that
    # an empty trough is refused - and the way home is a drain on a timer that
    # would put balls back underneath them. It used to be invisible here by
    # accident: one pending slot, overwritten by every launch, never matured.
    # With one timer per launched ball (PAD-134) it does, so the way home gets
    # its own section and its own feeder below rather than leaking into these.
    env = dict(os.environ, PAD_SW_FILE=sw, PAD_LED_FILE=led,
               PAD_BALL_FILE=os.path.join(SCRATCH, "padball"),
               PAD_TABLES=padpath.tables() or "", PAD_GAME=game,
               PAD_BALL_HZ="50", PAD_BALL_LANE_MS="150",
               PAD_BALL_MIN_GAP_MS="300", PAD_BALL_HOME_MS="0")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "ballfeed.py")],
                         env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    out = []
    threading.Thread(target=lambda: [out.append(l.rstrip()) for l in p.stdout],
                     daemon=True).start()
    time.sleep(0.6)

    fails = []

    def check(what, got, want):
        ok = got == want
        print("  %-52s %s (%s)" % (what, "ok" if ok else "FAIL", got))
        if not ok:
            fails.append("%s: got %r, wanted %r" % (what, got, want))

    # 1. A ball, because the game asked. This is the whole item in one step.
    wire.fire(eject)
    time.sleep(0.6)
    check("the game's eject took a ball out of the trough",
          shim.count(ids), len(ids) - 1)
    check("it opened the FAR end, not the eject end (item 20)",
          shim.merged(ids[-1]), 0)
    check("position 1 still has its ball", shim.merged(ids[0]), 1)
    check("the ball arrived in the shooter lane",
          shim.merged(lane) if lane else 1, 1)

    # 2. A retry burst is one ball, not two. The game re-pulses the coil when
    #    it has not seen the trough change yet, and this is the guard that
    #    keeps that from becoming a second ball.
    wire.fire(eject)
    time.sleep(0.4)
    check("a retry inside the minimum gap fed nothing",
          shim.count(ids), len(ids) - 1)

    # 3. The auto plunger launches what is waiting.
    wire.fire(plunger)
    time.sleep(0.4)
    check("the auto plunger emptied the shooter lane",
          shim.merged(lane) if lane else 0, 0)

    # 4. Multiball: the game asks twice more, with the lane clearing between.
    for _ in range(2):
        time.sleep(0.45)
        wire.fire(eject)
        time.sleep(0.5)
        wire.fire(plunger)
        time.sleep(0.3)
    check("three ejects put three balls in play", shim.count(ids),
          len(ids) - 3)

    # 5. An empty trough is refused, not invented. Drain everything out first.
    for _ in range(len(ids)):
        time.sleep(0.45)
        wire.fire(eject)
        time.sleep(0.35)
        wire.fire(plunger)
        time.sleep(0.25)
    check("the trough empties and stays empty", shim.count(ids), 0)
    check("an empty trough was refused rather than going negative",
          any("empty" in l for l in out), True)

    p.terminate()
    p.wait(timeout=5)

    # ---- what plunge does: LAUNCH, and only launch --------------------------
    # 2026-08-11 made it serve a ball from the trough when the lane was empty,
    # because no run had a feeder and nothing else ever put a ball there. The
    # feeder is on by default now, and serving from a full trough handed the
    # game a ball it never asked for - Plunge in attract left the machine a
    # ball short. PAD-134's follow-up (David: "yes make plunge launch-only")
    # made it a plunger again; `serve` is the verb that ejects. With the
    # feeder stopped, these run against the same fake machine and check the
    # verbs apart from it.
    def run(verb):
        r = subprocess.run([sys.executable, os.path.join(HERE, "plunge.py"),
                            verb], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        return r.stdout.strip()

    run("reset")
    time.sleep(0.3)
    check("reset puts every ball home", shim.count(ids), len(ids))
    out_txt = run("plunge")
    time.sleep(0.3)
    check("plunge with an EMPTY lane ejects nothing, even at rest",
          shim.count(ids), len(ids))
    check("...and says there was nothing to launch",
          "nothing in the shooter lane" in out_txt, True)
    check("...and left the lane open", shim.merged(lane) if lane else 0, 0)

    # A ball already waiting: the feeder's state. Plunge must launch it and
    # NOT take a second one out of the trough.
    before = shim.count(ids)
    plunge_lane_ball(shim, lane)
    out_txt = run("plunge")
    time.sleep(0.3)
    check("plunge with a ball ALREADY in the lane ejects nothing",
          shim.count(ids), before)
    check("...and launched the one that was there",
          shim.merged(lane) if lane else 0, 0)

    run("serve")
    time.sleep(0.3)
    check("serve DOES eject one and launch it", shim.count(ids), before - 1)
    check("serve left the lane empty", shim.merged(lane) if lane else 0, 0)
    # Relative, not absolute: these run in sequence and an absolute count has
    # to be re-derived every time a step is inserted above, which is exactly
    # how a check stops meaning what its sentence says.
    before = shim.count(ids)
    run("take")
    time.sleep(0.3)
    check("take removes a ball without touching the lane",
          shim.count(ids), before - 1)
    check("take left the lane alone", shim.merged(lane) if lane else 0, 0)

    # ---- PAD-134: a plunge with a ball already in play serves NOTHING ------
    # The trough is short several balls by now and the lane is empty, which is
    # a machine with balls in play. Serving there hands the game a ball it
    # never asked for, and the game's own count never grows to match: the
    # machine is a ball short for ever and the next Start gets LOCATING
    # PINBALLS. With BALL SAVE on it is one click away, because the game
    # re-serves and auto-plunges the saved ball itself.
    before = shim.count(ids)
    out_txt = run("plunge")
    time.sleep(0.3)
    check("plunge with a ball ALREADY IN PLAY ejects nothing",
          shim.count(ids), before)
    check("...and says why, naming how a ball in play ends",
          ("a ball is in play" in out_txt and "Drain" in out_txt), True)

    # ---- PAD-134: THE WAY HOME, which nothing here used to reach -----------
    # A launched ball that nobody is playing drains back to the trough, and
    # the two faults this section exists for are the two the old one slot
    # could not express: a ball the rig takes back while a MOUSE-ONLY player
    # is playing it, and a second launched ball the rig forgets entirely.
    # Its own feeder because the way home has to be ON for these.
    run("reset")
    time.sleep(0.3)
    # Long enough that two launches fit INSIDE one ball's wait, because the
    # second launch landing after the first ball had already come home is the
    # one way this section could pass while the fault it is about was still
    # there.
    henv = dict(env, PAD_BALL_HOME_MS="1500")
    p2 = subprocess.Popen([sys.executable, os.path.join(HERE, "ballfeed.py")],
                          env=henv, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, bufsize=1)
    out2 = []
    threading.Thread(target=lambda: [out2.append(l.rstrip()) for l in p2.stdout],
                     daemon=True).start()
    time.sleep(0.6)

    def launch():
        """What the game does when it serves a ball and plunges it itself."""
        wire.fire(eject)
        time.sleep(0.25)
        wire.fire(plunger)
        time.sleep(0.2)

    launch()
    check("a launched ball nobody is playing is out of the trough",
          shim.count(ids), len(ids) - 1)
    time.sleep(1.8)
    check("...and comes home by itself", shim.count(ids), len(ids))

    # A MOUSE-ONLY SESSION. DragonRR, 2026-09-12: every input in his report is
    # a click in the playfield window - the plunger, the Mechagodzilla spinner,
    # an outlane, a trough dot - and not one of them moves the KEYBOARD array
    # the old test read. So the feeder called him "nobody" and took his ball.
    # What to click: the Mechagodzilla spinner, the switch his mail names, if
    # this title has one - otherwise any playfield switch that is not the
    # trough or the lane. All the click has to be is a script write tagged `f`.
    click_sw = next((r["id"] for r in rows
                     if "SPINNER" in (r["name"] or "").upper()), None)
    if click_sw is None:
        click_sw = next(r["id"] for r in rows
                        if r["id"] not in ids and r["id"] != lane
                        and r.get("node") != 0)
    launch()
    window_click(shim, click_sw)
    time.sleep(1.8)
    check("a ball somebody is PLAYING with the mouse stays in play",
          shim.count(ids), len(ids) - 1)
    check("...and the feeder says so rather than going quiet",
          any("somebody is playing" in l for l in out2), True)
    run("reset")
    time.sleep(0.4)

    # TWO LAUNCHED BALLS, which is a multiball - and the shape that stranded a
    # ball for ever, because the second launch overwrote the first one's timer
    # and nothing was left to bring that ball home.
    launch()
    launch()
    check("two launches put two balls in play", shim.count(ids), len(ids) - 2)
    time.sleep(2.5)
    check("BOTH come home - neither is forgotten", shim.count(ids), len(ids))
    p2.terminate()
    p2.wait(timeout=5)
    out.extend(out2)

    shim.stop = True
    print("\n--- ballfeed.py said ---")
    for line in out:
        print("  " + line)
    if fails:
        print("\n%d FAILED:" % len(fails))
        for f in fails:
            print("  " + f)
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
