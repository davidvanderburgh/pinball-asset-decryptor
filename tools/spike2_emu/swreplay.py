#!/usr/bin/env python3
"""swreplay.py - hand a recorded run's switches to a rig at the game times they happened (PAD-733, PAD-764).

    swreplay.py <recording folder | log> [--from MS] [--to MS] [--skip-src LETTERS] [--align MS]
                [--film MS:N[,MS:N]] [--dry]

A recording (runrec.py) is a folder holding the run's switches.log: every switch the game was handed, as the shim
logged it (`[sw] <ms> ms +<id><who> -<id><who> ...`), each spinner rip (`[swspin] <ms> ms id=<id> ... rip START/END`)
and the time the game spent frozen (`[pause] <ms> ms frozen <total> ms in all`). Any guest log (gzwatch.log, game.out)
reads the same way. replayrun.sh boots the recording's card on its NVRAM and runs this; it can also be pointed at a
run by hand (PAD_SW_FILE=<rig dump>/padsw).

EVERYTHING IS TIMED ON THE GAME'S OWN CLOCK. The stamps are the raw CLOCK_MONOTONIC from the boot's first switch
scan, which padsw.guest_ms() reads off the same counter here (qemu-user shares the host's clock) - so a rig that is
slower or faster to boot still lands each change at its game time. A Pause stops the game's clocks but not that one,
so the frozen time is taken off both sides: the session's from its [pause] lines, the rig's from the block's own
total. A paused session replays without pausing, and a replay can be paused.

WHO IS REPLAYED. Every edge, whoever made it - the keyboard (k), the playfield (f), the ball feeder (b), autoattract
(a), the window's own latch (w), the scripts - except `m`, the shim's own motor end stops, which the replay's game
makes itself from its own coils. replayrun.sh turns the replay rig's ball feeder and autoattract OFF so the edges they
made are delivered once, from the record, at their times. --skip-src adds letters (PAD-733's replay skipped only `a`
with autoattract left on).

--align MS: the session's change at MS happens NOW on the rig's game clock, and every other one as long before or
after it as it was. --film MS:N: at the session's MS, N frames of the glass back to back (glshot.sh, into
$OUT/film_<MS>_NN.png). --dry: print the timeline and stop.
"""
import os
import re
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padsw  # noqa: E402

SW = re.compile(r"\[sw\] (\d+) ms((?: [-+]\d+\S)+)")
SPIN = re.compile(r"\[swspin\] (\d+) ms id=(\d+) .*?rip (START|END)")
PAUSE = re.compile(r"\[pause\] (\d+) ms frozen (\d+) ms in all")
#: the shim's own motor end stops: the replay's game drives its motors itself
SKIP_ALWAYS = "m"
#: how long one change may take to reach the merge before it is called missed
CONFIRM_S = 0.05


def source_file(path):
    if os.path.isdir(path):
        return os.path.join(path, "switches.log")
    return path


def read_events(path, skip=""):
    """[(game ms, kind, id, value)] in game-time order: kind 'sw' (value = closed) or 'spin' (value = ripping).
    Game ms = the raw stamp less the time frozen since the boot began."""
    skip = set(skip) | set(SKIP_ALWAYS)
    raw, pauses = [], []
    with open(path, "rb") as f:
        for line in f:
            text = line.decode("utf-8", "replace")
            for mm in SW.finditer(text):
                t = int(mm.group(1))
                for tok in mm.group(2).split():
                    if tok[-1] not in skip:
                        raw.append((t, "sw", int(tok[1:-1]), tok[0] == "+"))
            for mm in SPIN.finditer(text):
                raw.append((int(mm.group(1)), "spin", int(mm.group(2)), mm.group(3) == "START"))
            for mm in PAUSE.finditer(text):
                pauses.append((int(mm.group(1)), int(mm.group(2))))
    base = pauses[0][1] if pauses else 0
    pauses.sort()
    out = []
    for t, kind, sw, on in raw:
        frozen = 0
        for pt, total in pauses:           # the total as it stood when this change was logged
            if pt > t:
                break
            frozen = total - base
        out.append((t - frozen, kind, sw, on))
    out.sort(key=lambda e: e[0])           # stable: one line's changes keep their order
    return out


def rig_game_ms(m, frozen0):
    now = padsw.guest_ms(m)
    if now is None:
        return None
    return now - (struct.unpack_from("<I", m, padsw.OFF_PAUSED_MS)[0] - frozen0)


def main(argv):
    def opt(name, conv=int, default=None):
        return conv(argv[argv.index(name) + 1]) if name in argv else default
    lo = opt("--from", default=0)
    hi = opt("--to", default=1 << 40)
    skip = opt("--skip-src", str, "")
    align = opt("--align")
    film = sorted((int(a), int(b)) for a, b in (x.split(":") for x in opt("--film", str, "").split(",") if x))
    path = source_file(argv[0])
    evs = [e for e in read_events(path, skip) if lo <= e[0] <= hi]
    if not evs:
        print("replay: no switch changes in %s" % path)
        return 1
    print("replay: %d switch changes, %d to %d ms of game time" % (len(evs), evs[0][0], evs[-1][0]), flush=True)
    if "--dry" in argv:
        for t, kind, sw, on in evs:
            print("%d %s %s%d" % (t, kind, "+" if on else "-", sw))
        return 0
    padsw.set_source("r")
    m = padsw.open_block()
    if m is None:
        print("replay: no switch block at %s" % padsw.PATH)
        return 1
    while padsw.guest_ms(m) is None:
        time.sleep(0.05)
    frozen0 = struct.unpack_from("<I", m, padsw.OFF_PAUSED_MS)[0]
    boot = struct.unpack_from("<I", m, padsw.OFF_GUEST_T0)[0]   # this boot's clock origin
    shift = rig_game_ms(m, frozen0) - align if align is not None else 0
    if align is not None:
        print("replay: the session's %d ms is the rig's %d ms" % (align, align + shift), flush=True)
    late, missed = 0, 0
    evs = evs + [(ft, "film", -1, n) for ft, n in film]
    evs.sort(key=lambda e: e[0])
    for t0, kind, sw, on in evs:
        t = t0 + shift
        while True:
            now = rig_game_ms(m, frozen0)
            if now is None or struct.unpack_from("<I", m, padsw.OFF_GUEST_T0)[0] != boot:
                # the game went (Stop, a crash) or booted again: the rest of the record is no one's
                print("replay: the game is gone or booted again at %d ms; stopping" % t0, flush=True)
                return 1
            if now >= t:
                break
            time.sleep(min(0.2, max(0.001, (t - now) / 1000.0)))
        lag = now - t
        late = max(late, lag)
        if kind == "film":               # frames in the background; the replay goes on
            out = os.environ.get("OUT", ".")
            subprocess.Popen(["bash", "-c", 'for i in $(seq -w 1 %d); do bash "%s/glshot.sh" "%s/film_%d_$i.png" '
                              '> /dev/null 2>&1; done' % (on, padsw.padpath.RIG, out, t0)])
            print("replay: %d ms - filming %d frames" % (t0, on), flush=True)
            continue
        if kind == "spin":
            padsw.set_spin(m, sw, on)
            print("replay: %d ms rip %s %d (%+d ms)" % (t0, "on" if on else "off", sw, lag), flush=True)
            continue
        padsw.take(m, [sw])              # the write below is an edge whatever the merge shows now
        ok = padsw.set_confirmed(m, sw, on, CONFIRM_S)
        if ok is False:
            missed += 1
        print("replay: %d ms %s%d (%+d ms)%s" % (t0, "+" if on else "-", sw, lag,
                                             "" if ok is not False else " NOT TAKEN"), flush=True)
    print("replay: done, %d changes, latest %d ms after its time, %d not taken" % (len(evs), late, missed),
          flush=True)
    return 0 if not missed else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
