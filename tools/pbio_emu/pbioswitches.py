#!/usr/bin/env python3
"""pbioswitches.py <rig> <title> - write <rig>/switches.json, the table the
virtual playfield (tools/pb_emu/pbpf.py --rig pbio -> tools/ap_emu/appf.py)
and the game window's keys (tools/ap_emu/gamekeys.py) work from (PAD-315).

The same table, keys and rows as Predator's (tools/pb_emu/pbswitches.py,
which makes it): this only restates an Alien or ABBA profile
(pbiotitles.py) in Predator's shape - the switch names, the trough and
shooter lane, the cabinet's buttons by role.  Neither game ships a playfield
picture with switch positions, so the window is appf's schematic view.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pb_emu"))
import pbiotitles  # noqa: E402
import pbswitches  # noqa: E402

#: the cabinet's buttons by role (pbswitches' names) <- the game's own names
FLIPPERS = {"LEFT BUTTON": "lflip", "RIGHT BUTTON": "rflip",
            "UPPER LEFT BUTTON": "ulflip", "LEFT BUTTON 2": "ulflip",
            "UPPER RIGHT BUTTON": "urflip", "RIGHT BUTTON 2": "urflip"}
#: a switch is the cabinet's (not the playfield's) when its name says so
CABINET_WORDS = ("BUTTON", "COIN", "TILT", "INTERLOCK", "LOCK DOWN BAR")
SERVICE = ("UP", "DOWN", "ENTER", "ESCAPE")


def profile(key):
    """pbiotitles' *key* in pbtitles' shape (what pbswitches.table reads)."""
    t = pbiotitles.get(key)
    sws = {n: s for n, s in t["switches"].items() if s != "UNUSED"}
    b = t["buttons"]
    cab = {"start": b["start"], "coin": b["coin"],
           "tilt": b["tilt"], "exit": b["escape"], "down": b["down"],
           "up": b["up"], "enter": b["enter"]}
    if "launch" in b:               # Queen has none: its flippers launch
        cab["launch"] = b["launch"]
    for n, s in sws.items():
        if s in FLIPPERS:
            cab.setdefault(FLIPPERS[s], n)
    return {"title": t["name"],
            "switches": {str(n): s for n, s in sws.items()},
            "trough_switches": list(t["trough"]), "jam_switch": t["jam"],
            "shooter_switch": t["shooter"], "cabinet": cab, "optos": [],
            "cabinet_switches": sorted(
                n for n, s in sws.items()
                if s in SERVICE or any(w in s for w in CABINET_WORDS))}


def table(key):
    return pbswitches.table(t=profile(key))


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    out = os.path.join(argv[0], "switches.json")
    with open(out + ".tmp", "w") as f:
        json.dump(table(argv[1]), f, indent=1)
    os.rename(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
