#!/usr/bin/env python3
"""gen_alice_map.py - write ac.shadow.json (PAD-954).

Helshaks' "Alice Cooper's Nightmare Castle (Spooky Pinball 2017)" WIP 1.0.2
(VPUniverse file 30571, from Ling Woo's) is a scripted EM-style table on a
photo of the machine's own lower playfield, so its lights sit on the real
inserts; its rules are its own (a score, a ball count, no modes). The real
game is put behind it by place and meaning, as Halloween was
(gen_halloween_maps.py): GUESS marks where a game on the table should
confirm.

The game is Spooky's P-ROC code (tools/spooky_emu/proc, on tools/proc_emu's
board, prochw.py --bridge), read from its machine yaml (config/alice.yaml
of ac-gamecode 1.1.0.5): on that rig (spkbridge.py) a switch is the board's
number (`SD24` = 24) and a coil or LED is its place in the yaml's PRCoils or
PRLEDs, as [n // 64, n % 64]. The machine has no servos the rig drives
(the castle's, the guillotine's and the subways' locks are servo-held on the
machine: here the ball passes their switches and plays on).

How the table's objects were matched (x right, y down, 0-952 x 0-2162; its
upper half is drawn by primitives over a dark field):

* the outlanes, inlanes and slings by place; the left orbit is Spinner1 and
  Trigger19 at its top (SPINNER, OUTSIDE LEFT ORBIT), Trigger13 below it the
  inner orbit (GUESS); Trigger20 the right outer orbit;
* Kicker2, the hole on the left (97, 1226) the table kicked back out, is the
  LEFT SCOOP (coil leftScoop);
* the three drop targets: sw3 (right) and sw2 (left, low) are the front and
  back drop targets (dropTarget1 / dropTarget2 reset and knockdown coils,
  GUESS which is which), sw1 the upper playfield's drop target (target3,
  dropTarget3); the coils raise and drop the table's targets;
* the triggers at the left and right ramp entrances (Trigger8, Trigger16),
  the one beside the right ramp the CHOP (Trigger17), the right lane
  (Trigger11) the RIGHT SUBWAY, the standup left of the left ramp (sw11) the
  HURRY UP target; Trigger12 and Trigger15 below the castle two of the three
  monster-select targets, sw13 and sw12 on the right the MULTIPLIER and
  EXTRA BALL targets; the upper lanes (sw7, sw8, sw9) the balcony and the
  upper playfield's two exits (all GUESS);
* lights: the photo's inserts, each lit by its LED in the game's colour.

    python gen_alice_map.py      # writes ac.shadow.json beside this file
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: config/alice.yaml's PRCoils, in its order (the rig's coil number)
COILS = ["backBoxLED", "RGBOutRed", "RGBOutGreen", "RGBOutBlue", "startButtonLight",
         "launchButtonLight", "trough", "slingr", "flipperLwRMain", "autoFire", "flipperLwRHold",
         "knocker", "shaker", "dropTarget1Reset", "dropTarget3Reset", "flipperUpRMain",
         "dropTarget2Reset", "flipperUpRHold", "dropTarget3Knockdown", "upperMagnet",
         "flipperLwLMain", "flipperLwLHold", "leftScoop", "lowerMagnet", "dropTarget1Knockdown",
         "slingl", "dropTarget2Knockdown"]


def coil(name):
    return [0, COILS.index(name)]


def switches():
    s = {"_": "object -> the board's switch number (config/alice.yaml SD<n>; spkbridge.py: the number itself); "
              "event hit (pulse), spin, slingshot, drop (made while down, until its reset coil). Names are the "
              "yaml's. GUESS where a game on the table should confirm."}

    def put(obj, n, name, event="hit", note=None):
        s[obj] = {"id": n, "event": event, "name": name}
        if note:
            s[obj]["note"] = note

    put("LeftOutlane", 63, "outlaneLeft")
    put("LeftInlane", 62, "inlaneLeft")
    put("RightInlane", 48, "inlaneRight")
    put("RightOutlane", 49, "outlaneRight")
    put("LeftSlingShot", 61, "slingl", "slingshot")
    put("RightSlingShot", 47, "slingr", "slingshot")
    put("Spinner1", 58, "spinner", "spin", "the left orbit's spinner")
    put("Trigger19", 25, "outsideLeftOrbit", note="the top of the left orbit")
    put("Trigger13", 57, "innerLeftOrbit", note="GUESS: the trigger below the left orbit")
    put("Trigger20", 38, "rightOuterOrbit", note="the top of the right orbit")
    put("Trigger8", 24, "leftRampOpto", note="the left ramp's entrance")
    put("Trigger16", 34, "rightRampOpto", note="GUESS: the right ramp's entrance")
    put("Trigger17", 30, "chopOpto", note="GUESS: beside the right ramp (the CHOP LOCK arrow)")
    put("Trigger11", 35, "rightSubway", note="GUESS: the right lane (ZAP RIGHT)")
    put("sw11", 59, "hurryup", note="GUESS: the standup left of the left ramp")
    put("Trigger12", 44, "hellTarget1", note="GUESS: below the castle (MONSTER SELECT LEFT)")
    put("Trigger15", 45, "hellTarget2", note="GUESS: below the castle (MONSTER SELECT MIDDLE)")
    put("sw13", 39, "increaseMultiplier", note="GUESS: the right standups")
    put("sw12", 21, "target2", note="GUESS: EXTRA BALL")
    put("sw3", 37, "frontDropTarget", "drop", "GUESS: dropTarget1's")
    put("sw2", 36, "backDropTarget", "drop", "GUESS: dropTarget2's")
    put("sw1", 22, "target3", "drop", "GUESS: the upper playfield's drop target (dropTarget3)")
    put("sw7", 18, "balcony", note="GUESS: the top lane")
    put("sw8", 20, "upperLeftExit", note="GUESS")
    put("sw9", 19, "upperRightExit", note="GUESS")
    return s


#: table light -> (the yaml's PRLEDs index, its name, note)
LIGHTS = [
    ("LightShootAgain", 66, "InsertSaveLight", "the shoot-again insert"),
    ("Light30", 66, "InsertSaveLight", "SCARE AGAIN on the bat"),
    ("Light27", 59, "InsertBuildMystery", "BUILD MYSTERY"),
    ("Light9", 60, "InsertSelectMonsterMode", "SELECT MONSTER MODE"),
    ("Light7", 32, "InsertSecretPassage", "GUESS: the arrow into the castle"),
    ("Light16", 0, "arrowLeftRamp", "GUESS: the arrow at the left ramp"),
    ("Light21", 34, "InsertLeftOuterOrbit", "GUESS: the arrow at the left orbit"),
    ("Light28", 35, "InsertLeftPath", "GUESS: the yellow left arrow"),
    ("Light24", 33, "InsertZapLeft", "ZAP LEFT"),
    ("Light26", 55, "InsertLabLock", "LAB LOCK"),
    ("l11", 54, "InsertExtraBall", "EXTRA BALL (the yaml: SPECIAL LEFT)"),
    ("Light39", 82, "InsertCollectMystery", "GUESS: the red ? insert"),
    ("l13", 53, "InsertMulti2x", "2X"),
    ("l12", 52, "InsertMulti4x", "4X"),
    ("Light40", 77, "InsertMulti8x", "8X"),
    ("Light5", 37, "InsertMonsterFrank", "the MONSTER coffin"),
    ("Light14", 78, "InsertMonsterColdEthyl", "COLD ETHYL"),
    ("Light38", 36, "InsertMonsterIgor", "IGOR"),
    ("Light4", 38, "InsertMonsterVampire", "VAMPIRE"),
    ("Light18", 39, "InsertMonsterAlice", "ALICE"),
    ("Light19", 40, "InsertMonsterWerewolf", "GUESS: beside WEREWOLF"),
    ("Light13", 41, "InsertMonsterZombi", "ZOMBIE"),
    ("Light12", 42, "InsertMonsterInsects", "INSECTS"),
    ("Light3", 43, "InsertMonsterPitcreature", "PIT CREATURE"),
    ("Light1", 63, "InsertBDB", "BILLION DOLLAR BABIES"),
    ("Light20", 65, "InsertSkullEye1", "the skull's left eye"),
    ("Light17", 64, "InsertSkullEye2", "the skull's right eye"),
    ("l1", 74, "InsertZapRight", "ZAP RIGHT"),
    ("l2", 76, "InsertChopLock", "CHOP LOCK (the yaml: TO LAB)"),
    ("l3", 75, "InsertSuperJackpot", "SUPER JACKPOT (the yaml: SPECIAL RIGHT)"),
    ("Light10", 72, "InsertRightRamp", "GUESS: the arrow at the right ramp"),
    ("Light23", 71, "InsertRightOuterOrbit", "GUESS: the arrow at the right orbit"),
    ("Light34", 73, "InsertRightPath", "GUESS: the yellow right arrow"),
]


def lamps():
    out = {"_": "table light -> the game's LED [n // 64, n % 64] (n: its place in config/alice.yaml's PRLEDs; rgb: "
                "one LED, lit in its colour). The table's lights sit on the photo's inserts."}
    for light, n, name, note in LIGHTS:
        out[light] = {"leds": [[n // 64, n % 64]], "rgb": True, "name": name, "note": note}
    return out


def solenoids():
    out = {"_": "coil [0, n] (n: its place in config/alice.yaml's PRCoils) -> the small number the table sees "
                "(core.vbs flippers 46/48, the upper right 34); callback a sub of the table's or the bridge's "
                "(null = nothing fires). Names are the yaml's."}

    def put(num, name, cb=None):
        out[str(num)] = {"coil": coil(name), "name": name, "callback": cb}

    put(1, "trough", "bsTrough.SolOut")
    put(2, "autoFire", "PadLaunch")
    put(3, "leftScoop", "bsKicker2.SolOut")
    put(4, "dropTarget1Reset", "PadDT1Up")
    put(5, "dropTarget2Reset", "PadDT2Up")
    put(6, "dropTarget3Reset", "PadDT3Up")
    put(7, "dropTarget1Knockdown", "PadDT1Down")
    put(8, "dropTarget2Knockdown", "PadDT2Down")
    put(9, "dropTarget3Knockdown", "PadDT3Down")
    put(10, "knocker")
    put(11, "shaker")
    put(12, "slingl")
    put(13, "slingr")
    put(14, "upperMagnet")
    put(15, "lowerMagnet")
    # the game flips on the MAIN coil alone (pulse, then patter while the
    # button is held); the yaml's hold coils are never driven
    put(46, "flipperLwRMain")
    put(48, "flipperLwLMain")
    put(34, "flipperUpRMain")
    return out


EXTRA_VBS = "\n".join([
    "'---- PAD: Alice Cooper's mechs follow the machine (gen_alice_map.py)",
    "' the machine's auto plunger (autoFire): the table's own plunger, pulled and",
    "' let go as its own code did (Timer16, Timer17). Not a cvpmImpulseP: its",
    "' CreateEvents would define Trigger1_Hit over the shooter lane's switch",
    "Sub PadLaunch(e)",
    "\tIf e Then",
    "\t\tPlunger.PullBack",
    "\t\tvpmTimer.AddTimer 150, \"Plunger.Fire '\"",
    "\tEnd If",
    "End Sub",
    "",
    "' the drop targets: the game's reset and knockdown coils (the table reset",
    "' them at its own drain)",
    "Sub PadDrop(t, sw, down)",
    "\tt.IsDropped = down",
    "\tController.Switch(sw) = CBool(down)",
    "\tIf down Then",
    "\t\tPlaySoundAt \"fx_droptarget\", t",
    "\tElse",
    "\t\tPlaySoundAt \"fx_resetdrop\", t",
    "\tEnd If",
    "End Sub",
    "Sub PadDT1Up(e) : If e Then PadDrop sw3, 1037, 0 : End If : End Sub",
    "Sub PadDT2Up(e) : If e Then PadDrop sw2, 1036, 0 : End If : End Sub",
    "Sub PadDT3Up(e) : If e Then PadDrop sw1, 1022, 0 : End If : End Sub",
    "Sub PadDT1Down(e) : If e Then PadDrop sw3, 1037, 1 : End If : End Sub",
    "Sub PadDT2Down(e) : If e Then PadDrop sw2, 1036, 1 : End If : End Sub",
    "Sub PadDT3Down(e) : If e Then PadDrop sw1, 1022, 1 : End If : End Sub",
    "",
    "' the flippers: the table flipped inline in its key handlers; these are",
    "' those bodies, on the machine's coils",
    "Sub PadLFlip(e)",
    "\tIf e Then",
    "\t\tLeftFlipper.RotateToEnd : PlaySound \"fx_flipperup\", 0, .67, -0.05, 0.05",
    "\tElse",
    "\t\tLeftFlipper.RotateToStart : PlaySound \"fx_flipperdown\", 0, 1, -0.05, 0.05",
    "\tEnd If",
    "End Sub",
    "Sub PadRFlip(e)",
    "\tIf e Then",
    "\t\tRightFlipper.RotateToEnd : PlaySound \"fx_flipperup\", 0, .67, 0.05, 0.05",
    "\tElse",
    "\t\tRightFlipper.RotateToStart : PlaySound \"fx_flipperdown\", 0, 1, 0.05, 0.05",
    "\tEnd If",
    "End Sub",
    "Sub PadURFlip(e)",
    "\tIf e Then",
    "\t\tRightFlipper1.RotateToEnd",
    "\tElse",
    "\t\tRightFlipper1.RotateToStart",
    "\tEnd If",
    "End Sub",
    ""])


def build():
    sw = switches()
    return {
        "_": [
            "Alice Cooper's Nightmare Castle on the Spooky P-ROC rig (PAD-954): Helshaks' WIP 1.0.2",
            "(VPUniverse file 30571), a scripted table on a photo of the machine's playfield. Written by",
            "gen_alice_map.py, which says how each object was matched.",
            "platform: spooky puts PAD.Controller on tools/proc_emu's board (prochw.py --bridge, spkbridge.py):",
            "switches are the board's numbers, coils and LEDs their places in config/alice.yaml."
        ],
        "platform": "spooky",
        "title": "ac",
        "model": "Alice Cooper",
        "detect": ["alice cooper nightmare castle pinball", "rightflipper1.rotatetoend"],
        "output": "Alice Cooper's Nightmare Castle (Spooky Pinball 2017) (PAD).vpx",
        "table": {"name": "Alice Cooper's Nightmare Castle (Spooky Pinball 2017) WIP",
                  "by": "Helshaks (from Ling Woo)", "where": "VPUniverse"},
        "preferred": True,
        "solenoid_max": 68,
        "game_on": {"number": 40, "coils": [coil("flipperLwLMain"), coil("flipperLwRMain")]},
        "cabinet": {
            "_": "the cabinet's switches (config/alice.yaml): 1000 + the switch number; the coin door's ENTER, "
                 "UP, DOWN and EXIT. The machine launches with its button (autoFire), no shooter rod: the "
                 "plunger key is that button",
            "start": 1015, "left_flipper": 1014, "right_flipper": 1010, "up_right_flipper": 1009,
            "launch": 1011, "launch_key": "PlungerKey", "tilt": 1013, "coin": 1000,
            "service_select": 1004, "service_plus": 1005, "service_minus": 1006, "service_back": 1007
        },
        "keys_skip_orig": ["StartGameKey", "AddCreditKey", "AddCreditKey2", "PlungerKey"],
        "plunger": {"lane_trigger": "Trigger1", "lane_switch": 50, "autoplunge": "Plunger"},
        "trough": {"_": "trough1 (by the eject) to trough4, the jam opto last; 4 balls (numBalls)",
                   "release": "BallRelease", "drain": "Drain",
                   "switches": [52, 53, 54, 55, 51], "balls": 4, "kick": [90, 5]},
        "saucers": {
            "_": "kicker -> the switch it holds and how the coil kicks it out (dir, power), as the table's own "
                 "Kicker2.Kick 50, 5",
            "Kicker2": {"switch": 60, "dir": 50, "power": 5, "name": "LEFT SCOOP (leftScoop, an NC opto)"}
        },
        "flippers": {"_": "the tribute flips inline in its key handlers; these are those bodies",
                     "sLLFlipper": "PadLFlip", "sLRFlipper": "PadRFlip", "sURFlipper": "PadURFlip"},
        "solenoids": solenoids(),
        "pup_stub": True,
        "neuter": ["BallRelease.CreateBall", "BallRelease.Kick"],
        "retrofit_timers": {"PinMAMETimer": {"clone": "PulseTimer", "interval_ms": 1},
                            "PadTestTimer": {"clone": "PulseTimer", "interval_ms": 100}},
        "extra_vbs": EXTRA_VBS,
        "lamps": lamps(),
        "quiet_subs": [],
        "orig_hits": False,
        "orig_keep": ["LeftSlingShot", "RightSlingShot"],
        "switches": sw,
        "listed": True,
    }


def main():
    path = os.path.join(HERE, "ac.shadow.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(build(), f, indent=1)
        f.write("\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
