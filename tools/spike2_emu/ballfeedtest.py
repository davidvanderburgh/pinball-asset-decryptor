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

    env = dict(os.environ, PAD_SW_FILE=sw, PAD_LED_FILE=led,
               PAD_TABLES=padpath.tables() or "", PAD_GAME=game,
               PAD_BALL_HZ="50", PAD_BALL_LANE_MS="150",
               PAD_BALL_MIN_GAP_MS="300")
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

    # ---- plunge must NOT eject, 2026-08-11 ---------------------------------
    # David: "plunge should not be auto-ejecting a ball either (it should just
    # get the ball out of the shooter lane)." With the feeder stopped, these
    # run against the same fake machine and check the verbs apart from it.
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
    check("plunge with an EMPTY lane ejects nothing", shim.count(ids),
          len(ids))
    check("...and says why instead", "shooter lane" in out_txt, True)
    run("serve")
    time.sleep(0.3)
    check("serve DOES eject one and launch it", shim.count(ids), len(ids) - 1)
    check("serve left the lane empty", shim.merged(lane) if lane else 0, 0)
    run("take")
    time.sleep(0.3)
    check("take removes a ball without touching the lane",
          shim.count(ids), len(ids) - 2)
    check("take left the lane alone", shim.merged(lane) if lane else 0, 0)

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
