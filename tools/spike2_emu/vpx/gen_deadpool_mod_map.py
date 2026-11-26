#!/usr/bin/env python3
"""gen_deadpool_mod_map.py - write deadpool_pro_mod.shadow.json (PAD-1610).

masonm's "Deadpool v610 nfozzy Color Rush" 1.0.0 (VPUniverse file 28212) is
jpsalas's JP's Deadpool 6.10 dressed as the LE (ebislit's playfield scan, the
LE's colours), with burger's nFozzy physics and Fleep sounds, and the calls
Team Tugas's PuP pack listens for. Its playfield is the 6.10's: every object
deadpool_pro.shadow.json names is still there and stands where it did (the DEAD
and POOL targets are still standups, there is still no up/down ramp), so it
fits the Pro's card like the 6.10, and its map IS that map, with what the mod
changed:

* its own name, credit and download page, so the Visual Pinball tab lists it
  as a table of its own beside the 6.10 and its patched copy does not take
  (and overwrite) the 6.10's "JP's Deadpool v610 (PAD).vpx". It runs the same
  game (`game`: deadpool_pro);
* detect: its PuP flashers (pupflasher3; the 6.10 has no PuP at all); the
  6.10's map says `detect_not` the same word, so each table fits its own map
  only. The mod still names itself JP's Deadpool v6.10 and jpsdeadpool;
* the flippers: the machine's flipper coils call PadLFlip / PadRFlip. The mod
  calls nFozzy's FlipperActivate / FlipperDeActivate (end-of-stroke torque,
  live catch) in its key handler, before its SolLFlipper, and the flipper
  keys never reach a patched table's key handler: called straight, its
  SolLFlipper fired the flipper with nFozzy's tricks never armed. These hand
  the coil on to the table's own SolLFlipper / SolRFlipper after arming them,
  as nFozzy's own notes say to ("Include FlipperActivate and
  FlipperDeactivate in the Flipper solenoid subs");
* the Hell House eject: the mod kicks it out at 40 (the 6.10: 30), for
  nFozzy's heavier ball.

Run it again after any change to deadpool_pro.shadow.json; a test checks the
written file is what this makes.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "deadpool_pro.shadow.json")
OUT = os.path.join(HERE, "deadpool_pro_mod.shadow.json")

MARK = "pupflasher3"

FLIPPERS = (
    "\n' ---- PAD: the Color Rush mod's flippers (gen_deadpool_mod_map.py, PAD-1610)\n"
    "' the machine's flipper coils: nFozzy's FlipperActivate / FlipperDeActivate,\n"
    "' which the mod calls from its key handler (never reached once patched),\n"
    "' then the table's own flipper sub, its flip, Fleep sounds and DOF\n"
    "Sub PadLFlip(e)\n"
    "\tIf CBool(e) Then FlipperActivate LeftFlipper, LFPress Else FlipperDeActivate LeftFlipper, LFPress\n"
    "\tSolLFlipper e\n"
    "End Sub\n"
    "Sub PadRFlip(e)\n"
    "\tIf CBool(e) Then FlipperActivate RightFlipper, RFPress Else FlipperDeActivate RightFlipper, RFPress\n"
    "\tSolRFlipper e\n"
    "End Sub\n")


def build(base):
    m = json.loads(json.dumps(base))
    m["_"] = [
        "deadpool_pro on masonm's 'Deadpool v610 nfozzy Color Rush' 1.0.0 (VPUniverse 28212),",
        "jpsalas's 6.10 in the LE's colours with burger's nFozzy physics and Team Tugas's PuP",
        "calls. WRITTEN by gen_deadpool_mod_map.py from deadpool_pro.shadow.json (the 6.10's",
        "map, whose notes below hold): edit that one and run the generator again (PAD-1610).",
    ] + [line for line in base["_"]]
    m["title"] = "deadpool_pro_mod"
    m["game"] = "deadpool_pro"
    m["preferred"] = False
    m["detect"] = list(base["detect"]) + [MARK]
    m.pop("detect_not", None)
    m["output"] = "Deadpool v610 nfozzy Color Rush (PAD).vpx"
    m["table"] = {"name": "Deadpool v610 nfozzy Color Rush 1.0.0",
                  "by": "masonm (from jpsalas)", "where": "VPUniverse",
                  "url": "https://vpuniverse.com/files/file/28212-deadpool-v610-nfozzy-color-rush/"}
    m["flippers"] = {
        "_": "PAD-1610: the mod arms nFozzy's flipper tricks in its key handler, which a patched "
             "table never reaches: these arm them, then call its SolLFlipper / SolRFlipper",
        "sLLFlipper": "PadLFlip", "sLRFlipper": "PadRFlip"}
    m["extra_vbs"] = base["extra_vbs"] + FLIPPERS
    hh = m["saucers"]["HellHouse"]
    if hh.get("power") != 30:
        raise SystemExit("deadpool_pro.shadow.json's HellHouse kick changed: check the mod's (40) here")
    hh["power"] = 40
    return m


def text(m):
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"


def main():
    base = json.load(open(BASE, encoding="utf-8"))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text(build(base)))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
