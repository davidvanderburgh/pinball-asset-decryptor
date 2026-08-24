#!/usr/bin/env python3
"""swexercise.py - work every safe switch once, so the game's usage audit stops
reporting CHECK SWITCH on the Tech Alerts screen (item 59).

WHY THIS IS NOT A BUG FIX. David, 2026-08-21: "the 'check switch' is real. if we
don't trigger a switch in multiple games, then the game thinks there's a problem
with them." The rows are the machine's own NO-USAGE AUDIT, and on this rig no
ball ever rolls, so the trough, the slingshots, the EOS switches and the shooter
lane genuinely never change state by themselves. A real machine clears them by
being PLAYED. This plays them.

The tell is in the title's own switch list, and it needs no run. turtles_pro
flags #80 and #91, which its table names LOCKDOWN BUTTON and TILT PENDULUM;
stranger_things flags #7..#22, which is both slingshots, both flipper buttons,
both EOS, the shooter lane and the six trough switches. That is precisely the
set a machine nobody plays never moves.

RUN IT IN ATTRACT, NOT IN A GAME. Several of the switches worth exercising do
something real while a ball is live: TILT PENDULUM warns and then tilts, the
slingshots fire their coils, and a trough switch opening IS a ball leaving. In
attract every one of those is harmless, which is why the caller sequences this
after autoattract.sh rather than this script trying to guess the game state.

WHAT IT REFUSES, each for its own reason rather than a blanket "cabinet": DIP
1..8 are configuration; SERVICE SELECT/PLUS/MINUS/BACK navigate the operator
menu and would walk the machine somewhere else; COIN DOOR INTERLOCK is a latched
state that gates 48 V; the coin switches award credits and move the money
audits; SLAM TILT ends a game and writes an audit; START and TOURNAMENT START
would begin one; QR SCANNER STATUS * are status bits rather than switches;
HEADPHONE and VOLUME ENCODER are neither. Every refusal is PRINTED with its
reason, because a row this never clears has to be explainable - otherwise it
reads exactly like a switch that is genuinely broken.

TROUGH SWITCHES REST CLOSED and everything else rests open, so "exercise" is not
one gesture. A trough switch is opened and closed again (a ball leaving and
coming back); everything else is closed and opened. Either way the RESTING value
is restored, which is what makes this safe to run over a machine that already has
its six balls loaded - and it is why every switch goes through padsw.take()
first, since padglhost latches the trough and the coin door on window open and a
write that agrees with the merge produces no edge at all (see padsw.py).

  swexercise.py --list              # the plan, touches nothing, needs no run
  swexercise.py                     # exercise, on a live run
  swexercise.py --coins             # also award credits on every coin switch
  swexercise.py --only 'TROUGH *'   # one group, by name glob
"""
import argparse
import fnmatch
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo
import padsw

padsw.set_source('x')   # who the [sw] log says moved a switch;
                        # PAD_SW_SRC overrides. See padsw.h.

#: Name globs this never drives, and WHY. Matched against the title's own name
#: for the switch, so the policy is portable where an id list would not be.
REFUSE = [
    ("QR SCANNER STATUS *",      "a status bit, not a switch"),
    ("DIP *",                    "configuration; closing one changes a setting"),
    ("SERVICE *",                "walks the operator menu somewhere else"),
    ("COIN DOOR INTERLOCK",      "latched state, gates 48 V"),
    ("COIN DOOR POWER INTERLOCK", "latched state, gates 48 V"),
    ("SLAM TILT",                "ends a game and writes an audit"),
    ("START BUTTON",             "would start a game"),
    ("TOURNAMENT START BUTTON",  "would start a game"),
    ("HEADPHONE *",              "not a playfield switch"),
    ("VOLUME ENCODER *",         "an encoder, not a switch"),
    ("TICKET NOTCH",             "drives the ticket dispenser"),
]

#: Refused unless --coins: each closure awards a credit and moves the audits.
COINS = [("* COIN", "would award a credit"), ("COIN *", "would award a credit")]

#: ★ ITEM 73: THE WIRE BACKSTOP. The globs above match NAMES, and five
#: titles' lists are all-'?' (item 29) - on those, every glob missed and the
#: plan FAILED OPEN, queueing the dips, the service keys, Start and the door
#: interlock. The cabinet's (node,bit) layout is universal across every
#: derived list on this disk, so these wires are refusable without a name.
#: Node 0 is the whole cabinet input word: dips, service keys, door
#: interlock, headphone/volume, QR status - nothing on it is exercisable.
#: Node 1 carries Start (bit 11), Tournament Start (12), Ticket Notch (8),
#: Slam Tilt (22) and the coin chutes (16..21); the Action/Lockdown button
#: (1,2) and Tilt Pendulum (1,14) stay exercisable, matching the name policy.
WIRE_REFUSE = [
    (0, None, "node 0 is the cabinet word - config/service/door/status"),
    (1, 8,    "drives the ticket dispenser"),
    (1, 11,   "would start a game"),
    (1, 12,   "would start a game"),
    (1, 22,   "ends a game and writes an audit"),
]
WIRE_COINS = [(1, b, "would award a credit") for b in range(16, 22)]


def _wire_why(node, bit, wires):
    for n, b, why in wires:
        if node == n and (b is None or bit == b):
            return why
    return None

#: Closed on a machine at rest, so exercising one is open-then-close. swinit.py
#: holds the same set at boot; plunge.py owns what they MEAN about balls.
CLOSED_AT_REST = ["TROUGH *"]


def switches():
    """(id, num, node, bit, name) for this title, from its own switch table."""
    path = gameinfo.table("switch_list.txt")
    if not path or not os.path.exists(path):
        print("swexercise: no switch_list.txt for this title yet - it arrives "
              "a minute into a first run; rerun then", file=sys.stderr)
        return []
    out = []
    for line in open(path):
        if line.startswith("#"):
            continue
        f = line.split(None, 4)
        if len(f) >= 5:
            out.append((int(f[0]), int(f[1]), int(f[2]), int(f[3]),
                        f[4].strip()))
    return out


def _why(name, globs):
    for g, why in globs:
        if fnmatch.fnmatch(name.upper(), g):
            return why
    return None


def _rests_closed(name):
    return any(fnmatch.fnmatch(name.upper(), g) for g in CLOSED_AT_REST)


def plan(coins=False, only=None, skip=None):
    """What would be exercised and what would not, with a reason for each."""
    refuse = list(REFUSE) + ([] if coins else COINS)
    wires = list(WIRE_REFUSE) + ([] if coins else WIRE_COINS)
    doing, refused = [], []
    for sw, num, node, bit, name in switches():
        # Name policy first (its reasons are the specific ones), then the
        # item-73 wire backstop, which is what still refuses on a title
        # whose names are all '?'.
        why = _why(name, refuse) or _wire_why(node, bit, wires)
        if why is None and only and not any(
                fnmatch.fnmatch(name.upper(), g.upper()) for g in only):
            why = "not in --only"
        if why is None and skip and any(
                fnmatch.fnmatch(name.upper(), g.upper()) for g in skip):
            why = "in --skip"
        rest = 1 if _rests_closed(name) else 0
        (refused if why else doing).append((sw, num, node, name, rest, why))
    return doing, refused


def exercise(doing, press_ms, gap_ms, verbose=True):
    """Drive each switch away from its resting value and back again."""
    m = padsw.open_block()
    if m is None:
        return 1
    padsw.take(m, tuple(s for s, _, _, _, _, _ in doing))
    for sw, num, node, name, rest, _ in doing:
        away = 0 if rest else 1
        padsw.set_held(m, sw, away)
        time.sleep(press_ms / 1000.0)
        padsw.set_held(m, sw, rest)
        time.sleep(gap_ms / 1000.0)
        if verbose:
            print("  %-3d #%-3d node %-2d %-32s %d->%d->%d"
                  % (sw, num, node, name, rest, away, rest))
            sys.stdout.flush()
    m.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true",
                    help="print the plan and touch nothing (needs no run)")
    ap.add_argument("--coins", action="store_true",
                    help="also exercise the coin switches, awarding credits")
    ap.add_argument("--only", action="append", metavar="GLOB",
                    help="only switches whose name matches (repeatable)")
    ap.add_argument("--skip", action="append", metavar="GLOB",
                    help="additionally refuse these (repeatable)")
    ap.add_argument("--press-ms", type=int, default=150,
                    help="how long each closure is held (default 150)")
    ap.add_argument("--gap-ms", type=int, default=80,
                    help="quiet time between switches (default 80)")
    a = ap.parse_args()

    doing, refused = plan(a.coins, a.only, a.skip)
    if not doing and not refused:
        return 1
    print("swexercise: %d to exercise, %d refused, %d+%d ms each, ~%.1f s"
          % (len(doing), len(refused), a.press_ms, a.gap_ms,
             len(doing) * (a.press_ms + a.gap_ms) / 1000.0))
    if a.list:
        for sw, num, node, name, rest, _ in doing:
            print("  WOULD  %-3d #%-3d node %-2d %-32s rests %s"
                  % (sw, num, node, name, "CLOSED" if rest else "open"))
        for sw, num, node, name, rest, why in refused:
            print("  refuse %-3d #%-3d node %-2d %-32s %s"
                  % (sw, num, node, name, why))
        return 0
    for sw, num, node, name, rest, why in refused:
        print("  refuse %-3d #%-3d %-32s %s" % (sw, num, name, why))
    return exercise(doing, a.press_ms, a.gap_ms)


if __name__ == "__main__":
    sys.exit(main())
