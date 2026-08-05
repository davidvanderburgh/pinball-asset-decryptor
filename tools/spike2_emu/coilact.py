#!/usr/bin/env python3
"""coilact.py [<coil name>] - what clicking a solenoid on the virtual playfield does.

WHAT A COIL CLICK CANNOT BE, and this is the whole design. Coils are the game's
OUTPUTS: the shim watches them go by on the node bus and can light a marker when
one fires, but nothing on this side can make the game energise one. A click that
"fires the coil" would be a lie with a satisfying animation.

WHAT IT IS INSTEAD. Every coil on this playfield either follows a switch or
produces one, so a click plays that switch - the game then does exactly what it
does on a real machine when that solenoid is involved:

    the switch CAUSES the coil       slingshots, pop bumper, flippers, scoop
    the coil MOVES the ball          trough eject, auto plunger

Both are named honestly in the tooltip, so the window never claims to have done
something it did not. `coilact.py` with no argument prints the table.

Run it from WSL, where the shared-memory switch block lives:

    coilact.py "LEFT SLINGSHOT"
"""
import os
import subprocess
import sys
import time

#: os.path, not __file__.rsplit("/"), because the playfield window imports this
#: module ON WINDOWS to read the descriptions - it only EXECUTES over in WSL.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plunge

#: coil name -> (kind, switch id, human sentence). `kind` is how the click is
#: played: "pulse" a momentary switch, "ball" hand off to plunge.py, "lane" the
#: shooter-lane launch below.
ACTIONS = {
    "TROUGH":          ("ball",  None, "ejects a ball into the shooter lane"),
    "AUTO PLUNGER":    ("lane",  62,   "launches the ball out of the shooter lane"),
    "LEFT SLINGSHOT":  ("pulse", 64,   "presses Left Slingshot (64), which fires it"),
    "RIGHT SLINGSHOT": ("pulse", 63,   "presses Right Slingshot (63), which fires it"),
    "POP BUMPER":      ("pulse", 49,   "presses Pop Bumper (49), which fires it"),
    "RIGHT SCOOP":     ("pulse", 53,   "presses Right Scoop (53) - ball in, kicked out"),
    "LEFT FLIPPER":    ("pulse", 60,   "presses the Left Flipper button (60)"),
    "RIGHT FLIPPER":   ("pulse", 59,   "presses the Right Flipper button (59)"),
    "UP LEFT FLIP":    ("pulse", 61,   "presses the Up Left Flipper button (61)"),
    "GODZILLA MAGNET": ("pulse", 87,   "presses Godzilla Magnet Fired (87)"),
}

PULSE_MS = 120


def describe(name):
    """The sentence the tooltip shows, or None when nothing is wired."""
    a = ACTIONS.get(name.upper())
    return a[2] if a else None


def _lane(m):
    """The auto plunger. If a ball is already waiting in the shooter lane it
    just leaves; otherwise play the whole arrival-and-launch so the click does
    something visible either way."""
    if m[plunge.OFF_HELD + plunge.SHOOTER]:
        plunge._set(m, plunge.SHOOTER, 0)
        print("shooter lane opened (ball launched)")
        return
    plunge._set(m, plunge.SHOOTER, 1)
    time.sleep(0.4)
    plunge._set(m, plunge.SHOOTER, 0)
    print("ball into the shooter lane and away")


def fire(name):
    a = ACTIONS.get(name.upper())
    if not a:
        print("%s: nothing wired" % name)
        return 1
    kind, sw, _ = a
    if kind == "ball":
        return subprocess.call([sys.executable,
                                os.path.join(HERE, "plunge.py"), "plunge"])
    m = plunge._open()
    if m is None:
        return 1
    if kind == "lane":
        _lane(m)
    else:
        plunge._set(m, sw, 1)
        time.sleep(PULSE_MS / 1000.0)
        plunge._set(m, sw, 0)
        print("pulsed switch %d for %s" % (sw, name))
    m.close()
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        for n, (kind, sw, why) in sorted(ACTIONS.items()):
            print("  %-16s %s" % (n, why))
        return 0
    return fire(" ".join(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
