#!/usr/bin/env python3
"""cgctitles.py - the Chicago Gaming titles this rig knows.

  cgctitles.py get <key> <field>        one field (title, program, verified)
  cgctitles.py detect <game dir>        the key of a card's game folder
  cgctitles.py balls <key> <names.json> $CGC_BALLS for that title

A CGC remake card's game folder is /home/debian/emumm (the WPC remakes:
emumm is a WPC-95 emulator running the Williams ROM, CGC's LCD and sound on
top) or /home/debian/pin (Cactus Canyon: CGC's own "Z5" engine, no 6809).
The ROM file names the title: appdata/rom/mm_10.rom, afm..., mb...

The ball model's switches and coils come from the ROM's own names
(cgcroms.py, kept beside the build as names.json): the trough switches
("TROUGH BALL n", "TROUGH n"), the jam/eject opto ("TROUGH EJECT" /
"TROUGH JAM" as a switch), the shooter lane, the coils "TROUGH EJECT" and
"AUTO PLUNGER".  A title's entry adds what the names cannot say: which
other switches are optos, and which kickouts to model.
"""
import json
import os
import re
import sys

TITLES = {
    "mm": {
        "title": "Medieval Madness (CGC)",
        "program": "emumm",
        # proven on the rig (PAD-273): serve, autoplunge, drain, ball save
        "verified": True,
        # 36 left popper and 41 moat enter read set when empty (power-up)
        "optos": [36, 41],
        # kickout switch -> the coil named for it
        "holes": {"LEFT POPPER": "LEFT POPPER", "RIGHT EJECT": "RIGHT EJECT",
                  "CATAPULT": "CATAPULT"},
        # motor coil, the switch it rests on, the switch at the far end
        "mechs": [("DRAWBRIDGE MOTOR", "DRAWBRIDGE UP", "DRAWBRIDGE DOWN")],
    },
    "afm": {
        "title": "Attack From Mars (CGC)",
        "program": "emumm",
        "verified": False,
        "optos": [],
        "holes": {},
    },
    "mb": {
        "title": "Monster Bash (CGC)",
        "program": "emumm",
        "verified": False,
        "optos": [],
        "holes": {},
        # Start pulses FRANK. MOTOR (16) every 1.5 s and never serves: this
        # model of the table is not yet what the game wants (PAD-273, open;
        # PAD-1170 fixed its coil numbers, which were read one off)
        "mechs": [("UP/DN BANK MOTOR", "UP/DN BANK UP", "UP/DN BANK DOWN"),
                  ("FRANK. MOTOR", "FRANK. TABLE DOWN", "FRANK. TABLE UP")],
    },
    "cc": {
        "title": "Cactus Canyon (CGC)",
        "program": "pin",
        # CGC's Z5 engine (cgcshim.c "Z5"): pin says which switches are
        # optos itself, so none are listed here.  Proven on the rig
        # (PAD-1170): attract, coins, serve, plunge, poppers, games to the end
        "verified": True,
        "optos": [],
        # a ball in a popper closes its switch until the popper's coil
        # (6 mine, 8 saloon) kicks it out
        "holes": {"MINE POPPER": "MINE POPPER", "SALOON POPPER": "SALOON POPPER"},
        # closed at rest; nothing in pin sets them (the WPC titles' programs
        # do it themselves)
        "closed": ["COIN DOOR CLOSED", "ALWAYS CLOSED"],
    },
}

# the Williams game ROM in a game folder: "mm_10.rom", Cactus Canyon's
# "cc_g11.1_3" (U6 at G11) - never its DCS sound ROMs ("s2.rom")
GAME_ROM = re.compile(r"^[a-z]+_[0-9a-z]+(\.rom|\.[0-9]+_[0-9]+)$")


def detect(game_dir):
    """mm / afm / mb / cc from the ROM file a game folder carries."""
    for root, _dirs, files in os.walk(game_dir):
        for f in files:
            m = re.match(r"^([a-z]+)_[0-9a-z]+\.rom$", f)
            if m and m.group(1) in TITLES:
                return m.group(1)
    if os.path.exists(os.path.join(game_dir, "pin")):
        return "cc"
    for key in ("afm", "mb"):
        if os.path.isdir(os.path.join(game_dir, key + "data")):
            return key
    return None


def find_rom(game_dir):
    any_rom = None
    for root, _dirs, files in sorted(os.walk(game_dir)):
        for f in sorted(files):
            if GAME_ROM.match(f):
                return os.path.join(root, f)
            if f.endswith(".rom") and not any_rom:
                any_rom = os.path.join(root, f)
    return any_rom


def balls(key, names):
    """$CGC_BALLS from the ROM's names + the title's entry."""
    t = TITLES[key]
    sw = {v: k for k, v in names.get("switches", {}).items() if k.isdigit()}
    coil = {v: k for k, v in names.get("coils", {}).items()}
    # "TROUGH BALL 1" first: the eject end
    trough = [int(n) for name, n in sorted(sw.items()) if re.match(r"^TROUGH (BALL )?\d$", name)]
    jam = [int(sw[n]) for n in ("TROUGH EJECT", "TROUGH JAM") if n in sw]
    shooter = next((int(sw[n]) for n in sw if n.startswith("SHOOTER")), 0)
    eject = next((coil[n] for n in coil if n in ("TROUGH EJECT", "TROUGH", "BALL RELEASE")), "")
    launch = next((coil[n] for n in coil
                   if n in ("AUTO PLUNGER", "AUTOPLUNGER", "AUTO LAUNCH", "LAUNCH")), "")
    closed = [int(sw[n]) for n in t.get("closed", []) if n in sw]
    optos = sorted(set(trough + jam + t["optos"]))
    holes = ["%s:%s" % (sw[s], coil[c]) for s, c in t["holes"].items() if s in sw and c in coil]
    parts = ["optos=" + ",".join(map(str, optos))]
    if trough:
        parts.append("trough=" + ",".join(map(str, trough)))
    if eject:
        parts.append("eject=" + eject)
    if shooter:
        parts.append("shooter=%d" % shooter)
    if launch:
        parts.append("launch=" + launch)
    if holes:
        parts.append("holes=" + ",".join(holes))
    if closed:
        parts.append("closed=" + ",".join(map(str, closed)))
    mechs = ["%s:%s:%s" % (coil[c], sw[a], sw[b]) for c, a, b in t.get("mechs", [])
             if c in coil and a in sw and b in sw]
    if mechs:
        parts.append("mechs=" + ",".join(mechs))
    return ";".join(parts)


def main(argv):
    if len(argv) == 3 and argv[0] == "get":
        print(TITLES.get(argv[1], {}).get(argv[2], ""))
        return 0
    if len(argv) == 2 and argv[0] == "detect":
        key = detect(argv[1])
        if not key:
            return 1
        print(key)
        return 0
    if len(argv) == 3 and argv[0] == "balls":
        with open(argv[2]) as f:
            print(balls(argv[1], json.load(f)))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
