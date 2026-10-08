#!/usr/bin/env python3
"""coilact.py [<coil name>] - what clicking a solenoid on the virtual playfield does.

WHAT A COIL CLICK CANNOT BE, and this is the whole design. Coils are the game's
OUTPUTS: the shim watches them go by on the node bus and can light a marker when
one fires, but nothing on this side can make the game energise one. A click that
"fires the coil" would be a lie with a satisfying animation.

WHAT IT IS INSTEAD. Every coil on this playfield either follows a switch or
produces one, so a click plays that switch - the game then does exactly what it
does on a real machine when that solenoid is involved:

    the switch CAUSES the coil       slingshots, pop bumpers, flippers,
                                     scoops, ejects, VUKs
    the coil MOVES the ball          trough eject, auto plunger

Both are named honestly in the tooltip, so the window never claims to have done
something it did not. `coilact.py` with no argument prints the table.

Run it from WSL, where the shared-memory switch block lives:

    coilact.py "LEFT SLINGSHOT"
"""
import os
import re
import subprocess
import sys
import time

#: os.path, not __file__.rsplit("/"), because the playfield window imports this
#: module ON WINDOWS to read the descriptions - it only EXECUTES over in WSL.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import padsw
import plunge

# AFTER `import plunge`, and that is not cosmetic: plunge.py calls set_source
# at import and would otherwise leave this process claiming to be plunge.py.
padsw.set_source('c')   # who the [sw] log says moved a switch;
                        # PAD_SW_SRC overrides. See padsw.h.

#: The coils whose click is a SEQUENCE rather than a switch: name -> (kind,
#: human sentence). "ball" hands off to plunge.py, "lane" is the shooter-lane
#: launch below. Every other coil is played by the switch it follows, if it has
#: one - see switch_names().
ACTIONS = {
    # `serve`, not `plunge`: this marker IS the trough eject, and since
    # 2026-08-11 `plunge` only launches what is already in the lane.
    "TROUGH":          ("ball", "ejects a ball into the shooter lane"),
    "AUTO PLUNGER":    ("lane", "launches the ball out of the shooter lane"),
}

#: ★ THE SWITCH A COIL FOLLOWS IS FOUND BY NAME, IN THE TITLE'S OWN LIST
#: (PAD-450). This table used to carry switch IDS, and they were godzilla_pro's:
#: on James Bond LE the RIGHT VUK coil sits on top of RIGHT VUK OPTO (101) and
#: its click did nothing at all, while the flipper and slingshot markers pressed
#: whatever wore Godzilla's numbers there (the Right Flipper coil held 59,
#: Bond's LEFT OUTLANE). The NAMES agree across every title on this disk -
#: measured over the device and switch tables of 25 titles: a slingshot, pop
#: bumper, scoop or eject coil and its switch share a name (RIGHT SLINGSHOT,
#: LEFT POP BUMPER, RIGHT SCOOP, HELLHOUSE EJECT), a VUK's switch adds OPTO
#: (RIGHT VUK -> RIGHT VUK OPTO on Bond and John Wick, VUK -> VUK Opto on
#: Godzilla LE), a flipper's adds BUTTON, and Godzilla's magnets are read back
#: on a FIRED VIRTUAL switch. Only those kinds are matched: a lock, diverter,
#: post or motor coil does not follow a switch, and a same-named one (ROCKET
#: LOCK 1 OPTO, CENTER LANE DIVERTER EOS) is where the ball or the part ends
#: up, not what fires it.
_FOLLOWS = re.compile(r"\b(SLING\w*|BUMPER|SCOOP|EJECT|VUK|KICK\w*|SAUCER|POPPER)\b")
_FLIPPER = re.compile(r"\bFLIP(PER)?\b")
#: The kinds a ball SITS in until the game kicks it out, which is why a press
#: is held for as long as the button is down (REMAINING item 24).
_HOLDS_BALL = re.compile(r"\b(SCOOP|EJECT|VUK|SAUCER|POPPER|KICKOUT)\b")

PULSE_MS = 120


def switch_names(name):
    """The switch names a coil called `name` follows, best first (upper case)."""
    n = " ".join(name.upper().split())
    if n in ACTIONS:
        return []
    if _FLIPPER.search(n):
        out = [n + " BUTTON"]
        if n.startswith("UPPER "):          # james_bond_le: UP LEFT FLIPPER BUTTON
            out.append("UP " + n[6:] + " BUTTON")
        return out
    if n.endswith(" MAGNET"):
        return [n + " FIRED VIRTUAL", n + " FIRED"]
    if _FOLLOWS.search(n):
        return [n, n + " OPTO"]
    return []


def _title_switches():
    """THIS title's switch rows, read the way plunge.py reads them - for the
    command line, which runs in WSL beside the tables. The playfield window
    passes its own rows instead."""
    try:
        import gameinfo
        import trough
        return trough.load_list(gameinfo.table("switch_list.txt"))
    except (ImportError, OSError, TypeError):
        return []


def find_switch(name, switches=None):
    """(id, the switch's own name) of the switch this coil follows, or None.

    `switches` is the title's switch rows (dicts with "id" and "name"); None
    reads them from the title's table."""
    rows = _title_switches() if switches is None else switches
    by_name = {}
    for r in rows:
        by_name.setdefault(" ".join(str(r["name"]).upper().split()), r)
    for want in switch_names(name):
        r = by_name.get(want)
        if r is not None:
            return int(r["id"]), r["name"]
    return None


def holds_ball(name):
    """Is this a coil that kicks a ball OUT of something it sits in (a VUK,
    scoop, eject, saucer)? Its switch is then a ball resting there, not a
    press - see the playfield's latch (PAD-450)."""
    return bool(_HOLDS_BALL.search(" ".join(name.upper().split())))


def describe(name, switches=None):
    """The sentence the tooltip shows, or None when nothing is wired."""
    a = ACTIONS.get(" ".join(name.upper().split()))
    if a:
        return a[1]
    hit = find_switch(name, switches)
    if hit is None:
        return None
    what = "%s (%d)" % (hit[1], hit[0])
    if holds_ball(name):
        return ("drops a ball onto %s;\nit stays there until the game fires"
                " this coil" % what)
    if _FLIPPER.search(name.upper()) or name.upper().endswith(" MAGNET"):
        return "holds %s" % what
    return "holds %s, which fires it" % what


def hold_switch(name, switches=None):
    """The switch a press-and-hold on this coil should CLOSE, or None.

    THE TWO HALVES OF THE TABLE ABOVE PART COMPANY HERE. Where the switch
    CAUSES the coil, the switch is a thing a human can hold: a scoop keeps its
    ball for as long as it is made, and that is exactly what REMAINING item 24
    is about. Where the coil MOVES the ball, the click is a SEQUENCE - a trough
    eject, a shooter-lane arrival and launch - and there is nothing to hold, so
    those stay clicks and go on running through fire().

    THIS IS THE FUNCTION THE SCOOP ACTUALLY NEEDS, which is not obvious and cost
    a diagnosis to find: on the artwork the coil marker sits on top of the
    switch marker, so pressing the middle of RIGHT SCOOP hits the COIL. A hold
    wired only to the switch markers would have left the item's own worked
    example behaving exactly as before.
    """
    hit = find_switch(name, switches)
    return hit[0] if hit else None


def _lane(m):
    """The auto plunger: launch what is in the shooter lane, and only that.

    IT USED TO FABRICATE A BALL when the lane was empty - arrival, then launch
    - so the click "did something visible either way". That was written when
    nothing in this rig could put a ball anywhere, and it is the same fault
    David named in `plunge` on 2026-08-11: a control that invents a ball nobody
    asked for. A real auto plunger fires into an empty lane too and nothing
    happens, so saying so is both honest and what the coil does.

    `_held` is the MERGED state - what the game is being handed - and not this
    script's own half of the switch block. Asking our own half would answer
    "did a script put a ball there", which is a different question and gets the
    wrong answer whenever the keyboard's F key was the one that did it."""
    if not plunge._held(m, plunge.SHOOTER):
        print("nothing in the shooter lane - the TROUGH coil serves one")
        return
    plunge._set(m, plunge.SHOOTER, 0)
    print("shooter lane opened (ball launched)")


def fire(name):
    a = ACTIONS.get(" ".join(name.upper().split()))
    sw = None if a else hold_switch(name)
    if not a and sw is None:
        print("%s: nothing wired" % name)
        return 1
    kind = a[0] if a else "pulse"
    if kind == "ball":
        return subprocess.call([sys.executable,
                                os.path.join(HERE, "plunge.py"), "serve"])
    m = plunge._open()
    if m is None:
        return 1
    if kind == "lane":
        padsw.take(m, (plunge.SHOOTER,))
        _lane(m)
    else:
        # Own it at its current merged value first, so the press below is an
        # edge even for a switch the keyboard is also holding down.
        padsw.take(m, (sw,))
        plunge._set(m, sw, 1)
        time.sleep(PULSE_MS / 1000.0)
        plunge._set(m, sw, 0)
        print("pulsed switch %d for %s" % (sw, name))
    m.close()
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        for n, (kind, why) in sorted(ACTIONS.items()):
            print("  %-16s %s" % (n, why))
        print("  and every slingshot, pop bumper, flipper, scoop, eject and"
              " VUK: holds its own switch, found by name")
        return 0
    return fire(" ".join(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
