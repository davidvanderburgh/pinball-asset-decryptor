#!/usr/bin/env python3
"""pbiotitles.py - what each Pinball Brothers I/O-board title needs from the
rig's board (pbioboard.py): its switches, trough, shooter lane, the coils
that move balls, and the switches that are made at rest.

    pbiotitles.py get <title> <key>     one value, for the shell scripts
    pbiotitles.py switches <title>      switches.json (sw.py, the playfield)
    pbiotitles.py detect <tree>         the title a game tree holds (game/<dir>)

Switch numbers are the board's (0..95, four I/O boards of 24 inputs).  The
names are the game's own: pinprog prints "SW <n> <name> stable" for every
switch whose first poll differs from its default, so a boot with every
switch reporting made lists them all (PBIO_NAMES=1, see pbioboard.py).
"""
import json
import sys

ALIEN_SWITCHES = (
    "TONGUE MICRO|BOTTOM JET|CENTRE TARGET LEFT|CENTRE TARGET RIGHT|"
    "RIGHT ORBIT|TOP LANE 2|TOP LANE 1|LEFT LOOP LOWER|LEFT LOOP UPPER|"
    "LEFT ORBIT|LEFT JET|RIGHT JET|SIDE LOOP|UNUSED|LEFT EJECT|DROP 1|"
    "DROP 2|DROP 3|LEFT SPINNER|RIGHT SPINNER|TARGET 5|RECHARGE|"
    "RIGHT LANE TARGET|RIGHT LANE LOWER|UNUSED|TARGET 1|TARGET 2|TARGET 3|"
    "UNUSED|TARGET 4|UNUSED|LEFT OUTLANE 1|LEFT OUTLANE 2|LEFT INLANE|"
    "RIGHT INLANE|RIGHT OUTLANE|SHOOTER|RIGHT SLING|UNUSED|LEFT SLING|"
    "UNUSED|TROUGH JAM|TROUGH 1|TROUGH 2|TROUGH 3|TROUGH 4|TROUGH 5|"
    "TROUGH 6|LEFT EOS|RIGHT EOS|UPPER LEFT EOS|UNUSED|UNUSED|"
    "UPPER RIGHT EOS|UNUSED|RIGHT RAMP MADE|LOCK 1|LOCK 2|LOCK 3|"
    "HIDDEN PASSAGE|TONGUE OPTO|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|"
    "LEFT RAMP EXIT|UNUSED|UNUSED|SCOOP|UP|ENTER|ESCAPE|DOWN|START BUTTON|"
    "LAUNCH BUTTON|LEFT BUTTON|RIGHT BUTTON|UPPER LEFT BUTTON|"
    "UPPER RIGHT BUTTON|UNUSED|COIN 1|COIN 2|COIN 3|COIN 4|UNUSED|UNUSED|"
    "TILT|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED").split("|")

ABBA_SWITCHES = (
    "COIN 3|COIN 2|COIN 1|LAUNCH BUTTON|UNUSED|START BUTTON|LOCK DOWN BAR|"
    "UNUSED|COIN 4|COIN BOX ALARM|ESCAPE|DOWN|UP|ENTER|INTERLOCK|TILT|"
    "LEFT BUTTON|LEFT BUTTON 2|RIGHT BUTTON|UNUSED|LEFT SLING|RIGHT SLING|"
    "LEFT RAMP ENTER|ABBA A1 POP BUMPER|ABBA B1 POP BUMPER|"
    "ABBA B2 POP BUMPER|ABBA A2 POP BUMPER|LEFT EOS|LEFT UPPER EOS|"
    "RIGHT EOS|TROUGH JAM|TROUGH 1|TROUGH 2|TROUGH 3|TROUGH 4|TROUGH 5|"
    "TROUGH 6|SHOOTER LANE|RIGHT OUTLANE TOUR R|RIGHT INLANE TOUR U|"
    "HOTEL TARGET|NOTE DROP TARGET LEFT|NOTE DROP TARGET MIDDLE|"
    "NOTE DROP TARGET RIGHT|LEFT INLANE TOUR O|LEFT OUTLANE TOUR T|"
    "WATERLOO SCOOP|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|CAPTIVE TARGET|"
    "RIGHT RAMP MADE|DISCO SPINNER|SOS HOLD TARGET|HELI I TARGET|"
    "HELI L TARGET|RIGHT RAMP ENTER|EXCITEMENT SPINNER|CHANCE TARGET LEFT|"
    "CHANCE TARGET MIDDLE|CHANCE TARGET RIGHT|HELI H TARGET|HELI E TARGET|"
    "SONG SCOOP|LEFT RAMP MADE|UNUSED|HELICOPTER LOCK|UNUSED|"
    "SUPER TROUPER TARGET|TOP LANE RIGHT|TOP LANE LEFT|LEFT ORBIT TOP|"
    "HELICOPTER VUK|KEY DROP TARGET RIGHT|KEY DROP TARGET MIDDLE|"
    "KEY DROP TARGET LEFT|TOP SAUCER SHIELD SINGLE DROP|RIGHT ORBIT TOP|"
    "UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|"
    "UNUSED|KICKBACK|BJORN O TARGET|HELICOPTER START 1|HELICOPTER START 2|"
    "RIGHT UPPER EOS").split("|")

QUEEN_SWITCHES = (
    "RIGHT RAMP MADE|CAPTIVE BALL|RIGHT ORBIT TOP|LEFT ORBIT TOP|"
    "LEFT RAMP MADE|TOP LANE 1|TOP LANE 2|TOP LANE 3|RAMP LOCK 3|"
    "RAMP LOCK 2|RIGHT VUK|RAMP LOCK 1|GUITAR LOCK 3|"
    "GUITAR TARGET HIGH|RIGHT POP BUMPER|LEFT POP BUMPER|GUITAR LOCK 2|"
    "GUITAR TARGET MIDDLE|GUITAR LOCK 1|RIGHT ORBIT MIDDLE|"
    "RIGHT RAMP ENTER|GUITAR TARGET LOW|LEFT ORBIT BOTTOM|"
    "RED SPECIAL ACTIVE|CENTER SAUCER|BOTTOM POP BUMPER|GUITAR EXIT|"
    "LEFT VUK|RIGHT STANDUP|LEFT RAMP ENTER|BASS G|CENTER DROP TARGET|"
    "BASS D|RIGHT ORBIT BOTTOM|BASS A|LEFT SPINNER|BASS E|"
    "LEFT DROP TARGET|RIGHT DROP TARGET|PIANO WHITE 4|PIANO BLACK 3|"
    "PIANO WHITE 3|PIANO BLACK 2|PIANO WHITE 2|PIANO BLACK 1|"
    "PIANO WHITE 1|LAUNCH LANE UPPER|LEFT OUTLANE|RIGHT OUTLANE|"
    "LEFT INLANE|RIGHT INLANE|RIGHT SLING|LEFT SLING|KICKBACK|LEFT EOS|"
    "RIGHT EOS|TROUGH JAM|TROUGH 1|TROUGH 2|SHOOTER|TROUGH 3|TROUGH 4|"
    "TROUGH 5|TROUGH 6|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|UNUSED|"
    "UNUSED|UP|ENTER|ESCAPE|DOWN|START BUTTON|UNUSED|LEFT BUTTON|"
    "RIGHT BUTTON|LEFT BUTTON 2|RIGHT BUTTON 2|UNUSED|COIN 1|COIN 2|"
    "COIN 3|COIN 4|INTERLOCK|COIN BOX ALARM|TILT|LOCK DOWN BAR|UNUSED|"
    "UNUSED|UNUSED|UNUSED|UNUSED|UNUSED").split("|")

TITLES = {
    "alien": {
        "name": "Alien",
        "dir": "alien",
        "firmware": [0, 72, 0],     # fw_alien_072.uf2
        # the 1366x768 LCD and the 800x480 Airlock LCD right of it
        "screen": "2166x768", "vidargs": "-2",
        "switches": {n: s for n, s in enumerate(ALIEN_SWITCHES)},
        # TROUGH 1 is the ball next to the eject coil
        "trough": [42, 43, 44, 45, 46, 47],
        "jam": 41,
        "shooter": 36,
        "eject": [1],           # trough eject: a ball to the shooter lane
        "launch": [0],          # auto-launch: the shooter lane empties
        # kickers: firing one empties the first made switch it serves
        # (LEFT EJECT sol 18, the AIRLOCK scoop sol 23, CHAMBER LOCK sol 20)
        "kickouts": {18: [14], 23: [70], 20: [56, 57, 58]},
        "rest": [60],           # TONGUE OPTO reads made with nothing there
        # flipper buttons -> their end-of-stroke switches
        "eos": {77: 48, 78: 49, 79: 50, 80: 53},
        "buttons": {"start": 75, "launch": 76, "coin": 82, "tilt": 88,
                    "enter": 72, "escape": 73, "up": 71, "down": 74},
        # The xenomorph's tongue: a motor on GPIO 6 (on) and 7 (forward),
        # TONGUE MICRO (switch 0) a cam made at home and at full reach.  The
        # game counts the motor's pulses itself (~250/s) and calibrates
        # against the switch before attract ("amode waiting on xeno").
        "tongue": {"switch": 0, "run": 6, "forward": 7, "reach": 240,
                   "home": 12, "far": 215, "rate": 250},
    },
    "abba": {
        "name": "ABBA",
        "dir": "abba",
        "firmware": [1, 3, 0],      # >= 1.00 or "Invalid FW version"
        "screen": "1920x1080", "vidargs": "",
        "switches": {n: s for n, s in enumerate(ABBA_SWITCHES)},
        "trough": [31, 32, 33, 34, 35, 36],
        "jam": 30,
        "shooter": 37,
        "eject": [0],           # "TROUGH: kicking now" -> coil 0
        "launch": [1],          # fired on the Launch button
        "kickouts": {},
        "rest": [],
        # LEFT BUTTON, LEFT BUTTON 2 (upper flipper), RIGHT BUTTON
        "eos": {16: 27, 17: 28, 18: 29},
        "buttons": {"start": 5, "launch": 3, "coin": 2, "tilt": 15,
                    "enter": 13, "escape": 10, "up": 12, "down": 11},
    },
    "queen": {
        "name": "Queen",
        "dir": "queen",
        "firmware": [1, 3, 0],      # 103.uf2; the factory log: FW 1.03
        "screen": "1920x1080", "vidargs": "",
        "switches": {n: s for n, s in enumerate(QUEEN_SWITCHES)},
        "trough": [57, 58, 60, 61, 62, 63],
        "jam": 56,
        "shooter": 59,
        "eject": [1],           # TROUGH RELEASE
        "launch": [0],          # AUTO LAUNCH
        # LEFT VUK (sw 27) coil 19, RIGHT VUK (sw 10) coil 5
        "kickouts": {19: [27], 5: [10]},
        "rest": [],
        # LEFT BUTTON, RIGHT BUTTON
        "eos": {77: 54, 78: 55},
        # No Launch button: the flippers launch ("FLIPPER PLUNGER") - both
        # at once, which also starts the song picked on the song select
        # every ball begins with.  `plunge` presses these.
        "plunge": [77, 78],
        "buttons": {"start": 75, "coin": 82, "tilt": 88,
                    "enter": 72, "escape": 73, "up": 71, "down": 74},
    },
}


def get(key):
    return TITLES[key]


def detect(tree):
    """The title key for a game tree (<tree>/game/<dir>/pinprog)."""
    import os
    for k, t in TITLES.items():
        if os.path.isfile(os.path.join(tree, "game", t["dir"], "pinprog")):
            return k
    return ""


def switches_json(key):
    t = TITLES[key]
    b = t["buttons"]
    out = {"title": t["name"], "switches": [
        {"n": n, "name": s.title()} for n, s in sorted(t["switches"].items())
        if s != "UNUSED"],
        "buttons": b, "trough": t["trough"], "shooter": t["shooter"]}
    return json.dumps(out, indent=1)


def main(argv):
    if len(argv) >= 3 and argv[0] == "get":
        v = TITLES.get(argv[1], {}).get(argv[2], "")
        print(json.dumps(v) if isinstance(v, (dict, list)) else v)
    elif len(argv) >= 2 and argv[0] == "switches":
        print(switches_json(argv[1]))
    elif len(argv) >= 2 and argv[0] == "detect":
        print(detect(argv[1]))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
