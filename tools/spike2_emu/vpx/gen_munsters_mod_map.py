#!/usr/bin/env python3
"""gen_munsters_mod_map.py - write munsters_pro_mod.shadow.json (PAD-1491).

burger's "The Munsters (PRO)(Original 2020) (MOD)" 1.0.0 (VPUniverse file
33195) is Allknowing2012's Munsters 1.05/1.06 with nFozzy physics, Fleep
sounds, a FlexDMD score display beside the PuP pack, hybrid/VR rooms and a
reworked Herman ball lock. Its playfield objects are the 1.05's (every one
munsters_pro.shadow.json names is still there), so its map IS that map, with
what the mod changed:

* its own name, credit and download page, so the Visual Pinball tab lists it
  as a table of its own beside the 1.05 and its patched copy does not take
  the 1.05's name. It runs the same game (`game`: munsters_pro);
* detect: the mod's BallNotAtHermanTrigger (the 1.05 has none); the 1.05 map
  says `detect_not` the same word, so each table fits its own map only;
* HMagnet_Hit hands a ball to Herman's magnet only `If BallAtHerman`, a flag
  only the table's own sw45_Hit sets - its rules, which the machine replaces:
  the magnet never caught a ball. That guard is neutered, so the magnet takes
  every ball as the 1.05's did (and the machine's MAGNET coil decides);
* the HERMAN OPTO (PAD-1497): the mod's sw45 is a wall at Herman's face, not
  the 1.05's trigger under the magnet, so HMagnet (where the 1.05's sw45 was)
  is the opto, and the wall's own sw45_hit is quieted;
* the flippers: the machine's flipper coils call PadLFlip / PadRFlip, and the
  flipper keys never reach the table's own key handler, which is where the
  mod calls nFozzy's FlipperActivate / FlipperDeactivate (end-of-stroke
  torque, live catch) and its Fleep flipper sounds. The mod's bodies call
  them, as nFozzy's own notes say to ("Include FlipperActivate and
  FlipperDeactivate in the Flipper solenoid subs").

Run it again after any change to munsters_pro.shadow.json; a test checks the
written file is what this makes.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "munsters_pro.shadow.json")
OUT = os.path.join(HERE, "munsters_pro_mod.shadow.json")

MARK = "BallNotAtHermanTrigger"

# the 1.05's flipper bodies (PAD-1112) and the mod's
FLIP_105 = {
    "L": ("\t\tLF.Fire\n"
          "\t\tPlaySound SoundFXDOF(\"fx_flipperup\",101,DOFOn,DOFFlippers), 0, .67, AudioPan(LeftFlipper), "
          "0.05,0,0,1,AudioFade(LeftFlipper)\n"
          "\tElse\n"
          "\t\tLeftFlipper.RotateToStart\n"
          "\t\tPlaySound SoundFXDOF(\"fx_flipperdown\",101,DOFOff,DOFFlippers), 0, 1, AudioPan(LeftFlipper), "
          "0.05,0,0,1,AudioFade(LeftFlipper)\n"),
    "R": ("\t\tRF.Fire\n"
          "\t\tPlaySound SoundFXDOF(\"fx_flipperup\",102,DOFOn,DOFFlippers), 0, .67, AudioPan(RightFlipper), "
          "0.05,0,0,1,AudioFade(RightFlipper)\n"
          "\tElse\n"
          "\t\tRightFlipper.RotateToStart\n"
          "\t\tPlaySound SoundFXDOF(\"fx_flipperdown\",102,DOFOff,DOFFlippers), 0, 1, AudioPan(RightFlipper), "
          "0.05,0,0,1,AudioFade(RightFlipper)\n"),
}
FLIP_MOD = {
    "L": ("\t\tFlipperActivate LeftFlipper, LFPress\n"
          "\t\tLF.Fire\n"
          "\t\tIf LeftFlipper.CurrentAngle < LeftFlipper.EndAngle + ReflipAngle Then\n"
          "\t\t\tRandomSoundReflipUpLeft LeftFlipper\n"
          "\t\tElse\n"
          "\t\t\tSoundFlipperUpAttackLeft LeftFlipper\n"
          "\t\t\tRandomSoundFlipperUpLeft LeftFlipper\n"
          "\t\tEnd If\n"
          "\t\tPlaySound SoundFXDOF(\"\",101,DOFOn,DOFFlippers), 0, .67, AudioPan(LeftFlipper), "
          "0.05,0,0,1,AudioFade(LeftFlipper)\n"
          "\tElse\n"
          "\t\tFlipperDeActivate LeftFlipper, LFPress\n"
          "\t\tLeftFlipper.RotateToStart\n"
          "\t\tIf LeftFlipper.CurrentAngle < LeftFlipper.StartAngle - 5 Then RandomSoundFlipperDownLeft LeftFlipper\n"
          "\t\tFlipperLeftHitParm = FlipperUpSoundLevel\n"
          "\t\tPlaySound SoundFXDOF(\"\",101,DOFOff,DOFFlippers), 0, 1, AudioPan(LeftFlipper), "
          "0.05,0,0,1,AudioFade(LeftFlipper)\n"),
    "R": ("\t\tFlipperActivate RightFlipper, RFPress\n"
          "\t\tRF.Fire\n"
          "\t\tIf RightFlipper.CurrentAngle > RightFlipper.EndAngle - ReflipAngle Then\n"
          "\t\t\tRandomSoundReflipUpRight RightFlipper\n"
          "\t\tElse\n"
          "\t\t\tSoundFlipperUpAttackRight RightFlipper\n"
          "\t\t\tRandomSoundFlipperUpRight RightFlipper\n"
          "\t\tEnd If\n"
          "\t\tPlaySound SoundFXDOF(\"\",102,DOFOn,DOFFlippers), 0, .67, AudioPan(RightFlipper), "
          "0.05,0,0,1,AudioFade(RightFlipper)\n"
          "\tElse\n"
          "\t\tFlipperDeActivate RightFlipper, RFPress\n"
          "\t\tRightFlipper.RotateToStart\n"
          "\t\tIf RightFlipper.CurrentAngle > RightFlipper.StartAngle + 5 Then RandomSoundFlipperDownRight RightFlipper\n"
          "\t\tFlipperRightHitParm = FlipperUpSoundLevel\n"
          "\t\tPlaySound SoundFXDOF(\"\",102,DOFOff,DOFFlippers), 0, 1, AudioPan(RightFlipper), "
          "0.05,0,0,1,AudioFade(RightFlipper)\n"),
}


def build(base):
    m = json.loads(json.dumps(base))
    m["_"] = [
        "munsters_pro on burger's 'The Munsters (PRO)(Original 2020) (MOD)' 1.0.0 (VPUniverse",
        "33195), Allknowing2012's table with nFozzy physics, Fleep sounds, FlexDMD and a reworked",
        "Herman lock. WRITTEN by gen_munsters_mod_map.py from munsters_pro.shadow.json (the 1.05's",
        "map, whose notes below hold): edit that one and run the generator again (PAD-1491).",
    ] + [line for line in base["_"]]
    m["title"] = "munsters_pro_mod"
    m["game"] = "munsters_pro"
    m["detect"] = list(base["detect"]) + [MARK]
    m.pop("detect_not", None)
    m["output"] = "The Munsters (PRO)(Original 2020) (MOD) (PAD).vpx"
    m["table"] = {"name": "The Munsters (PRO)(Original 2020) (MOD) 1.0.0",
                  "by": "burger (from Allknowing2012)", "where": "VPUniverse",
                  "url": "https://vpuniverse.com/files/file/33195-the-munsters-prooriginal-2020-mod/"}
    m["neuter"] = list(base["neuter"]) + ["If Not BallAtHerman Then Exit Sub"]
    # PAD-1497: the HERMAN OPTO. In the 1.05, sw45 is a trigger the magnet
    # holds the ball inside (PAD-1117 holds it closed, PAD-1121 knocks it
    # open). The mod made sw45 an invisible solid WALL at Herman's face, the
    # end of the shot, and moved the old trigger aside as sw45_old: a wall
    # has a Hit and never an UnHit, so the held switch latched closed on the
    # first touch and the game read a ball caught on the magnet - the
    # hurry-up started with no ball on it. The ball the magnet holds sits in
    # HMagnet, the 60-unit square where the 1.05's sw45 was: that trigger is
    # the opto here, with the 1.05's hold and knock, and the table's own
    # HMagnet_Hit / _UnHit (the catch, the shaker, the GI) still run. The
    # wall's sw45_hit is the table's rules (scores, its own Herman awards,
    # MagnetStop), which the machine runs now: quieted.
    sw = dict(m["switches"].pop("sw45"))
    sw["why"] = ("PAD-1497: burger's mod made sw45 a solid wall at Herman's face, which never "
                 "un-hits, so the opto latched closed and the hurry-up started by itself; the ball "
                 "the magnet holds sits in HMagnet, where the 1.05's sw45 trigger was. "
                 + sw["why"])
    m["switches"]["HMagnet"] = sw
    m["orig_keep"] = list(base.get("orig_keep", [])) + ["HMagnet"]
    m["quiet_subs"] = list(base.get("quiet_subs", [])) + ["sw45_Hit"]
    m["repatch"] = list(base.get("repatch", [])) + [{
        "old": "Dim PadIn_sw45, PadKnocked_sw45",
        "why": "Herman's hurry-up started by itself: the opto was the mod's sw45 wall, which latched closed",
        "since": "PAD-1497: the MOD's Herman opto is the magnet's own trigger"}]
    x = base["extra_vbs"]
    for side in ("L", "R"):
        if x.count(FLIP_105[side]) != 1:
            raise SystemExit("munsters_pro.shadow.json's Pad%sFlip changed: update FLIP_105 here" % side)
        x = x.replace(FLIP_105[side], FLIP_MOD[side])
    m["extra_vbs"] = x
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
