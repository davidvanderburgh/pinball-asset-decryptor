#!/usr/bin/env python3
"""gen_halloween_maps.py - write h78.shadow.json and um.shadow.json (PAD-952).

marty02's "Halloween MM Edition" 3.1 (VPUniverse file 16526) is JPSalas'
scripted template dressed as Halloween, "inspired by" Spooky's machine and
not its layout, so the real game is put behind it by place and meaning, as
JP's Ghostbusters was (ghostbusters_le.shadow.json): GUESS marks where a game
on the table should confirm.

Spooky's Halloween and Ultraman are one code base ("H78UM") on the same
Pinotaur board, wired the same (tools/spooky_emu/spktitles.py), so one table
plays either: two maps, the same objects, the title and model apart.

The game's numbers are its own, read from Halloween v1.18.1 (Assembly-CSharp:
SwitchConfig.cs, CoilConfig.cs; config/lightconfig.json; Machine_Servos.cs,
VirtualServo.cs). On the Spooky rig (spkbridge.py) a switch is `"id": n`, a
coil [0, n], a servo s coil [0, 32 + s]: the two subways are lifted by
servos 0 (left) and 1 (right), not coils.

How the table's objects were matched (positions from the table, x right,
y down, 0-900 x 0-2100):

* the three kickers in the left channel, K3G (y 764), K2G (982) and K1G
  (1206), are the machine's three left "hedge" scoops - LEFT TOP, MIDDLE and
  BOTTOM SCOOP - which drop into the left subway; the table teleported each
  ball to Kicker003 above the left inlane. Here each pulses its scoop opto
  and puts the ball in one stack on LEFT SUBWAY 1-4, and the game's left
  lifter servo lets one out of Kicker003, as the table did;
* K1D (662, 978), a hole the table teleported to Kicker004, is the lower
  right scoop: its opto, then the RIGHT SUBWAY the right lifter servo empties;
* the pyramid kicker in the middle is the MID PF SCOOP (coil middle_scoop);
* the top-left lock (the table's own 3-ball lock behind a post) is the
  CROSSOVER, let out by the crossover dump coil (GUESS);
* the three-bank Jungle targets (Target1-3) are the pumpkin bank: its
  switches read made while the targets STAND, so a hit opens one and the
  bank reset coil closes all three again (the table's targets are standups:
  they do not fall);
* the captive ball's target (Target6) is the CAPTURE TARGET; the outlanes,
  the right inlane, the slings, the orbits (sw5 top left, sw5a right), the
  ramps' exits and two spinners by place; the other standups by place
  (GUESS). The machine has no left inlane switch and no pop bumpers: sw2 and
  the three bumpers keep the table's own subs.
* lights: marty's are the template's own (Light1 ... Light66), with no
  numbering of the game's 146 LEDs (config/lightconfig.json); the few that
  sit where the game has the insert are lit by it, in its colour (one
  Spooky LED is red, green and blue at once): shoot again, the pumpkin
  bank's three, the left spinner, the outlanes and the three lights by the
  left scoops as the hedge progress (GUESS). The rest keep the shadow
  game's light shows.

    python gen_halloween_maps.py      # writes both maps beside this file
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def switches():
    s = {"_": "object -> the Spooky game's switch number (spkbridge.py: the number itself); event hit "
              "(pulse), spin, slingshot, drop (stays until the bank resets; up_closed: made while it "
              "STANDS). Names are SwitchConfig.cs's labels. marty's table is not the machine's layout: "
              "GUESS where a game on the table should confirm."}

    def put(obj, n, name, event="hit", note=None, **kw):
        s[obj] = dict({"id": n, "event": event, "name": name}, **kw)
        if note:
            s[obj]["note"] = note

    put("sw1", 50, "LEFT OUTLANE")
    put("sw3", 34, "RIGHT INLANE")
    put("sw4", 33, "RIGHT OUTLANE")
    put("LeftSlingShot", 51, "LEFT SLING", "slingshot")
    put("RightSlingShot", 37, "RIGHT SLING", "slingshot")
    put("sw5", 48, "LEFT ORBIT", note="GUESS: the top-left lane the table scores as its orbit")
    put("sw5a", 35, "RIGHT ORBIT", note="GUESS: the right lane the table scores as its orbit")
    put("Spinner3", 12, "LEFT SPINNER", "spin", note="GUESS: the left spinner (166, 613)")
    put("Spinner4", 13, "RIGHT SPINNER", "spin", note="GUESS: the right spinner (721, 1035)")
    put("LeftRampDone", 41, "LEFT RAMP EXIT", note="GUESS: the ramp ending at the top (564, 85)")
    put("RightRampDone", 75, "MIDDLE RAMP", note="GUESS: the ramp ending at the left (63, 250)")
    put("sw8", 14, "UPPER PF ENTRY", note="GUESS: the top-right lane")
    put("Target1", 29, "DROP BANK LEFT", "drop", "the pumpkin bank: made while standing", up_closed=True)
    put("Target2", 27, "DROP BANK MID", "drop", "the pumpkin bank", up_closed=True)
    put("Target3", 28, "DROP BANK RIGHT", "drop", "the pumpkin bank", up_closed=True)
    put("Target6", 32, "CAPTURE TARGET", note="the captive ball's target")
    put("Target12", 5, "MIDDLE LEFT TARGET", note="GUESS: by place")
    put("Target11", 7, "MIDDLE RIGHT TARGET", note="GUESS: by place")
    put("Target4", 52, "STANDUP 1", note="GUESS: the left column, bottom")
    put("Target7", 53, "STANDUP 2", note="GUESS: the left column, middle")
    put("Target5", 54, "STANDUP 3", note="GUESS: the left column, top")
    put("Target8", 55, "STANDUP 4", note="GUESS: top left")
    put("Target9", 39, "STANDUP 5", note="GUESS: top middle")
    put("Target10", 38, "STANDUP 6", note="GUESS: top right")
    return s


def lamps():
    out = {"_": "table light -> the game's LED [n // 64, n % 64] (lightconfig.json's num; rgb: one LED, lit in its "
                "colour). marty's lights are the template's own: only those where the game has the insert, GUESS."}

    def put(light, n, name, note="GUESS: by place"):
        out[light] = {"leds": [[n // 64, n % 64]], "rgb": True, "name": name, "note": note}

    put("LightShootAgain", 25, "save_light", "the shoot-again light")
    put("LightShootAgaina", 25, "save_light", "the shoot-again light (its second)")
    put("Light12", 4, "bank_1", "the light at Target1 (the pumpkin bank's left)")
    put("Light13", 3, "bank_2", "the light at Target2")
    put("Light14", 2, "bank_3", "the light at Target3")
    put("Light25", 107, "left_spinner", "GUESS: the light by the left spinner")
    put("Light5", 21, "left_outlane", "GUESS: the light above the left outlane")
    put("Light9", 65, "right_outlane", "GUESS: the light above the right outlane")
    put("Light6a", 26, "hedge_progress_1", "GUESS: the light by the left bottom scoop")
    put("Light20a", 27, "hedge_progress_2", "GUESS: the light by the left middle scoop")
    put("Light8a", 28, "hedge_progress_3", "GUESS: the light by the left top scoop")
    return out


def solenoids():
    out = {"_": "Spooky coil [0, n] (CoilConfig.cs; a servo s is [0, 32 + s]) -> the small number the table "
                "sees (core.vbs flippers 46/48); callback a sub of the table's or the bridge's (null = "
                "nothing fires). Names are the game's own."}

    def put(num, coil, name, cb=None):
        out[str(num)] = {"coil": [0, coil], "name": name, "callback": cb}

    put(1, 18, "trough", "bsTrough.SolOut")
    put(2, 21, "launch", "PadAutoPlunge")
    put(3, 5, "middle_scoop", "bsPyramidKicker.SolOut")
    put(4, 32, "LEFT SUBWAY LIFTER (servo 0)", "bsK1G.SolOut")
    put(5, 33, "RIGHT SUBWAY LIFTER (servo 1)", "bsK1D.SolOut")
    put(6, 17, "crossover_dump", "bslock.SolOut")
    put(7, 11, "bank_target_reset", "PadPumpkinUp")
    put(8, 22, "knocker")
    put(9, 23, "shaker")
    put(10, 16, "left_sling")
    put(11, 9, "right_sling")
    put(12, 4, "upper_drop_reset")
    put(13, 6, "middle_drop_reset")
    put(14, 7, "middle_drop_knockdown")
    put(15, 12, "right_front_drop_knockdown")
    put(16, 13, "right_front_drop_reset")
    put(17, 0, "upper_flipper_left")
    put(18, 2, "upper_flipper_right")
    put(46, 14, "right_flipper_high")
    put(48, 19, "left_flipper_high")
    return out


def build(title, model, preferred):
    sw = switches()
    keep = [k for k in sw if k != "_"]
    m = {
        "_": [
            "%s on the SPOOKY rig (PAD-952): marty02's 'Halloween MM Edition' 3.1 (VPUniverse file 16526),"
            % ("Halloween" if title == "h78" else "Ultraman (Halloween's code base and wiring)"),
            "JPSalas' template dressed as Halloween, not the machine's layout. Written by gen_halloween_maps.py,",
            "which says how each object was matched.",
            "platform: spooky puts PAD.Controller on tools/spooky_emu's board (spkbridge.py): switches, coils",
            "and LEDs are the game's own numbers; the subway lifters are servos 0 and 1 (coils 32, 33)."
        ],
        "platform": "spooky",
        "title": title,
        "model": model,
        "detect": ["halloween script jpsalas", "cpuppack = \"halloween\""],
        "output": "halloween_MM_Edition (PAD).vpx",
        "table": {"name": "Halloween MM Edition", "by": "marty02 (from Onevox, bord; script JPSalas)",
                  "where": "VPUniverse"},
        "solenoid_max": 68,
        "game_on": {"number": 40, "coils": [[0, 19], [0, 14]]},
        "cabinet": {
            "_": "the Pinotaur cabinet (spktitles.py aliases): 1000 + the switch number",
            "start": 1087, "left_flipper": 1081, "right_flipper": 1080,
            "up_left_flipper": 1083, "up_right_flipper": 1082,
            "launch": 1084, "launch_key": "LockBarKey", "tilt": 1085, "coin": 1056,
            "service_select": 1060, "service_plus": 1061, "service_minus": 1062, "service_back": 1063
        },
        "keys_skip_orig": ["StartGameKey", "AddCreditKey", "AddCreditKey2"],
        "plunger": {"lane_trigger": "swPlungerRest", "lane_switch": 23, "autoplunge": "plungerIM"},
        "trough": {"_": "TROUGH 1 (by the eject) to TROUGH 7, the jam opto last; 7 balls (installed_balls)",
                   "release": "BallRelease", "drain": "Drain",
                   "switches": [65, 22, 21, 20, 16, 19, 18, 64], "balls": 7, "kick": [90, 4]},
        "saucers": {
            "_": "kicker -> the switch it holds and how the coil kicks it out (dir, power); stack = the lane's "
                 "switches behind; kick_from = where the ball leaves; enter = the opto it passes on the way in; "
                 "feeders = other holes into the same lane",
            "K1G": {"switch": 66, "stack": [73, 78, 74], "kick_from": "Kicker003", "dir": 180, "power": 10,
                    "enter": 76, "feeders": {"K2G": {"enter": 79}, "K3G": {"enter": 77}},
                    "name": "the left scoops (LEFT BOTTOM / MIDDLE / TOP SCOOP) into LEFT SUBWAY 1-4"},
            "K1D": {"switch": 70, "kick_from": "Kicker004", "dir": 170, "power": 10, "enter": 71,
                    "name": "LOWER RIGHT SCOOP into the RIGHT SUBWAY lifter"},
            "PyramidKicker": {"switch": 6, "dir": 200, "power": 5, "name": "MID PF SCOOP"},
            "lock": {"switch": 67, "dir": 270, "power": 15,
                     "name": "GUESS: the top-left lock as the CROSSOVER, let out by the crossover dump"}
        },
        "drop_resets": {"_": "the bank reset coil's sub: every target of the bank stands again",
                        "PadPumpkinUp": ["Target1", "Target2", "Target3"]},
        "solenoids": solenoids(),
        "pup_stub": True,
        "flexdmd_stub": True,
        "neuter": ["BallRelease.CreateSizedBallWithMass", "BallRelease.Kick", "PlungerIM.AutoFire"],
        "retrofit_timers": {"PinMAMETimer": {"clone": "PulseTimer", "interval_ms": 1},
                            "PadTestTimer": {"clone": "PulseTimer", "interval_ms": 100}},
        "lamps": lamps(),
        "quiet_subs": [],
        "orig_hits": False,
        "orig_keep": keep,
        "switches": sw,
        "listed": True,
    }
    if preferred:
        m["preferred"] = True
    # PAD-1099: the lane wrapper called the table's own lane subs
    m["repatch"] = [{"old": "Sub swPlungerRest_%s : Controller.Switch(1023) = %s : swPlungerRest_%s_orig : End Sub"
                            % (ev, lv, ev),
                     "why": "the table's own rules ran at every launch: its skill shot, songs and light effects, "
                            "over the machine's lights",
                     "since": "PAD-1099: the plunger lane's own subs stay out of the way"}
                    for ev, lv in (("UnHit", "False"), ("Hit", "True"))]
    # PAD-1113: the colour compare VPX's OLE_COLOR failed on
    m["repatch"] += [{"old": "If o.ColorFull <> v Then o.ColorFull = v",
                     "why": "its colour inserts (the shot arrows and the like) never light",
                     "since": "PAD-1113: a light's colour is read the way Visual Pinball hands it over"}]
    return m


def main():
    for title, model, pref in (("h78", "Halloween", True), ("um", "Ultraman", False)):
        path = os.path.join(HERE, "%s.shadow.json" % title)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(build(title, model, pref), f, indent=1)
            f.write("\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
