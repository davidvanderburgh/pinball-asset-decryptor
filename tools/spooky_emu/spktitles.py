#!/usr/bin/env python3
"""spktitles.py - the Spooky games the rig runs, one profile each.

    spktitles.py detect <unpacked update dir>   -> prints the title key, or
                                                   "no <why>" and exits 1
    spktitles.py get <key> <field>              -> one field for the shell
                                                   scripts (a list: spaced)
    spktitles.py passphrase <update file name>  -> the GPG passphrase of a
                                                   symmetric .pkg (Halloween's,
                                                   from the app's Spooky
                                                   plugin), exit 1 for none

Every title but Halloween talks to the same board - the Warden, on
/dev/WARDEN at 115200 - so spkwarden.py serves them all; what differs is
the game around it:

  engine   unity    Unity 2022.3 Mono, main.x86_64 + UnityPlayer.so
           godot    Godot 4.1 with the game's PCK inside main.x86_64; it finds
                    the board by LISTING serial ports (a glob of /dev/ttyUSB*
                    and friends), which spkshim.so answers
  layout   flat     the update IS the game folder -> /game/code/uptest
           code     the update holds uptest/, assets/ and config/ ->
                    /game/code/{uptest,assets,config}, audits in /game/audits
  attract  a regular expression for the line the game logs when attract
           mode starts (run_game.sh waits for it) - in the game's log, or
           the file attract_in names in the rig dir
  trough   TROUGH 1..7 in order (TROUGH 1 is the one the eject coil takes
           from), jam = the trough jam opto, shooter = the lane the eject
           coil feeds, eject = the coils that serve a ball there, launch =
           {coil: the shooter lane it empties}
  divert   [servo, angle, lane below it, lane at or above it]: a servo
           that sends the ejected ball to one of two shooter lanes
  balls    balls in the trough at rest
  optos    switches the switch window marks as optos, beyond the trough's
  rest     other switches made at rest; holds = {coil: a switch it opens
           while held}; resets = {coil: switches it makes (a drop bank's
           reset coil standing its targets back up)}; sets = {coil:
           {switch: 0|1}} (what firing a coil does to a switch)
  uname    what `uname -r` says to the game, where it matters
  seed     ["<file in /game>:<file in the update>", ...] - files a machine
           has from the factory, copied in when missing
  manual_plunger  the cabinet has a shooter rod as well as Launch (Halloween,
           Ultraman): Plunge lets the ball go itself when the game does not
           fire its launch coil.  The Warden games have none (spkwarden.plunge)
  board    "pinotaur" for a Pinotaur game (spkpinotaur.py); else the Warden
  aliases  cabinet names -> switch numbers, where not the Warden's
           (CABINET_ALIASES)

Switch names are the game's own (Switches.cs / SwitchConfig.cs / switches.cs
/ switches.gd of the build named in the comment); switch numbers are the
Warden's inputs.

Halloween and Ultraman are the titles here on Spooky's other board, the
Pinotaur (/dev/pinheck, spkpinotaur.py; "board": "pinotaur", PAD-268,
PAD-316); their cabinet switches are their own ("aliases"), and "game_row"
is what the board says it is set up for.  Rick and Morty, Alice Cooper and
Total Nuclear Annihilation are P-ROC games (proc/, PAD-269).
"""
import os
import re
import sys

CABINET_ALIASES = {"start": 87, "launch": 85, "coin": 90, "action": 81,
                   "tilt": 84, "enter": 91, "back": 94, "up": 92, "down": 93,
                   "lflip": 86, "rflip": 80, "ulflip": 83, "urflip": 82}

#: Halloween's and Ultraman's switches (the same SwitchConfig.cs labels on
#: both; Halloween v1.18.1, Ultraman v1.18).
PINOTAUR_SWITCHES = {
            4: "UPPER LEFT EOS", 5: "MIDDLE LEFT TARGET", 6: "MID PF SCOOP",
            7: "MIDDLE RIGHT TARGET", 12: "LEFT SPINNER",
            13: "RIGHT SPINNER", 14: "UPPER PF ENTRY", 15: "UPPER RIGHT EOS",
            16: "TROUGH 5", 18: "TROUGH 7", 19: "TROUGH 6", 20: "TROUGH 4",
            21: "TROUGH 3", 22: "TROUGH 2", 23: "SHOOTER LANE",
            26: "UP PF DROP", 27: "DROP BANK MID", 28: "DROP BANK RIGHT",
            29: "DROP BANK LEFT", 30: "MID PF DROP", 31: "LOWER DROP",
            32: "CAPTURE TARGET", 33: "RIGHT OUTLANE", 34: "RIGHT INLANE",
            35: "RIGHT ORBIT", 36: "RIGHT EOS", 37: "RIGHT SLING",
            38: "STANDUP 6", 39: "STANDUP 5", 41: "LEFT RAMP EXIT",
            48: "LEFT ORBIT", 49: "LEFT EOS", 50: "LEFT OUTLANE",
            51: "LEFT SLING", 52: "STANDUP 1", 53: "STANDUP 2",
            54: "STANDUP 3", 55: "STANDUP 4", 56: "COIN LEFT",
            59: "COIN RIGHT", 60: "MENU ENTER", 61: "VOLUME UP",
            62: "VOLUME DOWN", 63: "MENU BACK", 64: "TROUGH JAM",
            65: "TROUGH 1", 66: "LEFT SUBWAY 1", 67: "CROSSOVER",
            68: "MID RAMP LEFT", 69: "MID PF TO R SCOOP", 70: "RIGHT SUBWAY",
            71: "LOWER RIGHT SCOOP", 72: "LOWER RIGHT DROP",
            73: "LEFT SUBWAY 2", 74: "LEFT SUBWAY 4", 75: "MIDDLE RAMP",
            76: "LEFT BOTTOM SCOOP", 77: "LEFT TOP SCOOP",
            78: "LEFT SUBWAY 3", 79: "LEFT MIDDLE SCOOP",
            80: "RIGHT FLIPPER BUTTON", 81: "LEFT FLIPPER BUTTON",
            82: "UPPER RIGHT FLIPPER BUTTON", 83: "UPPER LEFT FLIPPER BUTTON",
            84: "LAUNCH BUTTON", 85: "TILT", 87: "START BUTTON",
        }

TITLES = {
    # Beetlejuice v2026.09.15.11 (Switches.cs).
    "bj": {
        "name": "Beetlejuice", "engine": "unity", "layout": "flat",
        "attract": "Attract_mode started",
        "factory_defaults": "beetlejuice_factory_defaults.json",
        # Keys the game's own window already acts on (its desktop mode:
        # Enter starts, Space launches, the arrows flip) - the game-window
        # key listener (ap_emu/gamekeys.py) leaves them to it (PAD-313).
        "own_keys": ["Enter", "NumpadEnter", "Space", "ArrowLeft", "ArrowRight"],
        "trough": [7, 6, 5, 4, 3, 1, 0], "jam": 2, "shooter": 8,
        "eject": [51], "launch": {54: 8}, "balls": 6,
        # Beyond the trough: the scoop, ramp and subway optos.
        "optos": [40, 41, 42, 43, 44, 45, 60, 61, 62, 63],
        "switches": {
            0: "TROUGH 7", 1: "TROUGH 6", 2: "TROUGH JAM", 3: "TROUGH 5",
            4: "TROUGH 4", 5: "TROUGH 3", 6: "TROUGH 2", 7: "TROUGH 1",
            8: "SHOOTER LANE", 9: "HANDBOOK", 10: "RIGHT DROP TARGET",
            12: "RIGHT SLING", 13: "RIGHT FLIPPER EOS", 14: "RIGHT INLANE",
            15: "RIGHT OUTLANE", 16: "DROP BANK LEFT", 17: "DROP BANK MIDDLE",
            18: "DROP BANK RIGHT", 19: "LEFT PASSIVE SLING", 20: "LEFT SLING",
            21: "LEFT FLIPPER EOS", 22: "LEFT INLANE", 23: "LEFT OUTLANE",
            24: "EXTRA BALL TARGET", 25: "TOP POP BUMPER",
            26: "BOTTOM POP BUMPER", 27: "LEFT ORBIT", 28: "MIDDLE POP BUMPER",
            29: "CAMERA TARGET LEFT", 30: "CAMERA TARGET RIGHT",
            35: "UPPER FLIPPER EOS", 37: "NOW SERVING TARGET LEFT",
            38: "NOW SERVING TARGET RIGHT", 39: "COUCH LOOP", 40: "JUNO SCOOP",
            41: "LOST SOULS SCOOP", 42: "LEFT RAMP", 43: "SANDWORM MOUTH",
            44: "LOST SOULS BACK ENTRY", 45: "COUCH LOCK",
            52: "SANDWORM SUBWAY TARGET RIGHT",
            54: "SANDWORM SUBWAY TARGET LEFT", 55: "SPINNER",
            60: "MYSTERY SCOOP", 61: "RIGHT ORBIT", 62: "RIGHT RAMP",
            63: "CAPTIVE BALL", 80: "RIGHT FLIPPER BUTTON",
            81: "ACTION BUTTON", 82: "UPPER RIGHT FLIPPER BUTTON",
            83: "UPPER LEFT FLIPPER BUTTON", 84: "TILT", 85: "LAUNCH BUTTON",
            86: "LEFT FLIPPER BUTTON", 87: "START BUTTON", 90: "COIN DROP",
            91: "MENU ENTER", 92: "VOLUME UP", 93: "VOLUME DOWN",
            94: "MENU BACK",
        },
    },
    # Scooby-Doo v2025.12.01.09 (Switches.cs).
    "scooby": {
        "name": "Scooby-Doo", "engine": "unity", "layout": "flat",
        # It logs no mode starts; this shell call follows queueing attract,
        # once the loading bar is gone.
        "attract": "bash command: touch /game/code/uptest/.backup_file",
        # Its PC model comes from the kernel: an unknown one means "a
        # developer's PC" and lightshows from /home/dj/...  6.1.0-21 = GK3.
        "uname": "6.1.0-21-amd64",
        "trough": [16, 30, 29, 28, 27, 26, 25], "jam": 17, "shooter": 31,
        # Coils.cs; Game.max_num_balls: it searches until all 7 are home.
        "eject": [10], "launch": {8: 31}, "balls": 7,
        "switches": {
            0: "RIGHT SPINNER", 1: "LEFT SPINNER",
            2: "FORWARD LEFT DROP TARGET", 3: "FORWARD MIDDLE DROP TARGET",
            4: "FORWARD RIGHT DROP TARGET", 5: "REAR RIGHT DROP TARGET",
            6: "REAR MIDDLE DROP TARGET", 7: "REAR LEFT DROP TARGET",
            9: "TRAP DOOR", 10: "LEFT OUTER OUTLANE", 11: "LEFT INNER OUTLANE",
            12: "LEFT INLANE", 13: "LEFT FLIPPER EOS", 14: "LEFT SLING",
            15: "LEFT VUK", 16: "TROUGH 1", 17: "TROUGH JAM",
            19: "RIGHT OUTLANE", 20: "RIGHT INLANE", 21: "RIGHT FLIPPER EOS",
            22: "RIGHT SLING", 23: "MIDDLE SLING", 25: "TROUGH 7",
            26: "TROUGH 6", 27: "TROUGH 5", 28: "TROUGH 4", 29: "TROUGH 3",
            30: "TROUGH 2", 31: "SHOOTER LANE", 32: "STANDING TARGET 1",
            33: "STANDING TARGET 2", 34: "STANDING TARGET 3",
            35: "STANDING TARGET 4", 36: "STANDING TARGET 5",
            37: "STANDING TARGET 6", 38: "STANDING TARGET 7", 39: "RIGHT VUK",
            40: "SUBWAY ENTRY", 41: "LEFT RAMP MAKE", 42: "CENTER RAMP ENTRY",
            43: "MYSTERY MACHINE 3", 44: "MYSTERY MACHINE 1",
            45: "MYSTERY MACHINE 4", 46: "MYSTERY MACHINE 2",
            47: "MYSTERY MACHINE EXIT", 48: "RIGHT APRON LOCK",
            49: "RIGHT APRON JAM", 50: "RIGHT INNER ORBIT",
            51: "LEFT INNER ORBIT", 52: "RIGHT OUTER ORBIT",
            53: "LEFT APRON JAM", 54: "LEFT OUTER ORBIT",
            55: "LEFT APRON LOCK", 67: "UPPER RIGHT FLIPPER EOS",
            68: "UPPER PASSIVE SLING", 69: "UPPER AIRPORT LANE",
            70: "UPPER MINE LANE", 71: "UPPER CASTLE LANE",
            72: "UPPER LEFT FLIPPER EOS", 73: "UPPER LEFT DRAIN",
            74: "UPPER MIDDLE DRAIN", 75: "UPPER CUTLER LEFT HAND",
            76: "UPPER CUTLER ORBIT", 77: "UPPER CENTER RAMP MAKE",
            78: "UPPER CUTLER HELMET", 79: "UPPER CUTLER RIGHT HAND",
            80: "RIGHT FLIPPER BUTTON", 81: "ACTION BUTTON",
            82: "UPPER RIGHT FLIPPER BUTTON", 83: "UPPER LEFT FLIPPER BUTTON",
            84: "TILT", 85: "LAUNCH BUTTON", 86: "LEFT FLIPPER BUTTON",
            87: "START BUTTON", 90: "RIGHT COIN", 91: "MENU BUTTON",
            92: "UP BUTTON", 93: "DOWN BUTTON", 94: "BACK BUTTON",
            95: "LEFT COIN",
        },
    },
    # Texas Chainsaw Massacre 1.00 (SwitchConfig.cs).
    "tcm": {
        "name": "Texas Chainsaw Massacre", "engine": "unity", "layout": "code",
        "attract": "Starting ATTRACT MODE",
        "trough": [49, 6, 5, 4, 3, 2, 1], "jam": 48, "shooter": 7,
        # coilControl.cs, the Warden row of coilMapping: trough, autofire;
        # pinballController.num_balls_total: Start with one short searches.
        "eject": [12], "launch": {9: 7}, "balls": 7,
        # The orbit diverter rests down ("diverter_down" made); its coil
        # (22, "diverter") lifts it.  Without it: an endless ball search.
        "rest": [43], "holds": {22: 43},
        "switches": {
            1: "TROUGH7", 2: "TROUGH6", 3: "TROUGH5", 4: "TROUGH4",
            5: "TROUGH3", 6: "TROUGH2", 7: "SHOOTER", 8: "STAND UP BANK TOP",
            9: "POST LOCK", 10: "STAND UP BANK BOTTOM",
            11: "STAND UP BANK MIDDLE", 12: "RIGHT SLING",
            13: "LOWER RIGHT FLIPPER EOS", 14: "RIGHT INLANE",
            15: "RIGHT OUTLANE", 16: "MIDDLE SCOOP", 17: "LEFT SNEAK",
            18: "SPINNER", 19: "LEFT FRONT SCOOP", 20: "LEFT SLING",
            21: "LOWER LEFT FLIPPER EOS", 22: "LEFT INLANE",
            23: "LEFT OUTLANE", 24: "DOOR SCOOP", 25: "OUTER ORBIT LEFT",
            26: "BACK LEFT STANDUP", 27: "UPPER LEFT FLIPPER EOS",
            28: "MIDDLE SCOOP STANDUP BOTTOM", 29: "DROP TARGET",
            30: "MIDDLE SCOOP STANDUP TOP", 32: "VUK", 33: "OUTER ORBIT RIGHT",
            34: "BACK RIGHT STANDUP", 35: "UPPER RIGHT FLIPPER EOS",
            36: "CAPTIVE BALL", 40: "POST LOCK STACK",
            41: "UPPER RIGHT RAMP MADE", 42: "MIDDLE SCOOP ENTRY",
            43: "ORBIT DIVERTER DETECT", 45: "LOWER LEFT RAMP MADE",
            46: "UPPER LEFT RAMP MADE", 47: "CORKSCREW EXIT", 48: "TROUGHJAM",
            49: "TROUGH1", 50: "INNER ORBIT RIGHT", 51: "DOOR ENTRY",
            52: "LOWER RIGHT RAMP MADE", 53: "CORKSCREW DIVERTER",
            54: "INNER ORBIT LEFT", 55: "MAGNET", 59: "SPINNING TOY HOME",
            60: "LOCK ENTER", 61: "LOCK RIGHT", 62: "LOCK CENTER",
            63: "LOCK LEFT", 80: "LOWER RIGHT FLIPPER BUTTON",
            81: "ACTION BUTTON", 82: "UPPER RIGHT FLIPPER BUTTON",
            83: "UPPER LEFT FLIPPER BUTTON", 84: "TILT", 85: "LAUNCHBUTTON",
            86: "LOWER LEFT FLIPPER BUTTON", 87: "START BUTTON", 90: "COIN",
            91: "MENU BUTTON", 92: "VOLUME UP", 93: "VOLUME DOWN",
            94: "BACK BUTTON", 95: "RIGHT SELECT",
        },
    },
    # Evil Dead 2026.07.15 (switches.cs).
    "ed": {
        "name": "Evil Dead", "engine": "unity", "layout": "code",
        "attract": "Load complete, starting attract mode",
        "trough": [66, 13, 12, 11, 10, 9, 8], "jam": 64, "shooter": 15,
        # Coil_Settings.cs: TROUGH EJECT, LEFT / RIGHT AUTO LAUNCHER.  Two
        # shooter lanes; servo 33 (Servo_Settings.cs) diverts the ejected
        # ball: 90 = the left one, 145 = the right one.
        "eject": [15], "launch": {13: 14, 14: 15}, "balls": 6,
        "divert": [33, 118, 14, 15],
        # The lower playfield keeps its own ball on lower_pf_drain; Start
        # says "LOWER PLAYFIELD BALL MISSING" without it.  The GROOVY drop
        # targets read made while standing (groovy.cs); coils 6 and 7
        # (UPPER / LOWER DROP BANK) stand G-R-O and O-V-Y back up.
        "rest": [68, 45, 46, 47, 48, 49, 50],
        "resets": {6: [45, 46, 47], 7: [48, 49, 50]},
        "switches": {
            6: "TOPPER DOWN", 7: "SPINNER", 8: "TROUGH7", 9: "TROUGH6",
            10: "TROUGH5", 11: "TROUGH4", 12: "TROUGH3", 13: "TROUGH2",
            14: "LEFT SHOOTER LANE", 15: "RIGHT SHOOTER LANE",
            17: "LOWER PF FLIPPER EOS", 18: "LOWER PF LOCK NLOAD",
            19: "LOWER PF BOOK TARGET", 20: "SLING FLIPPER EOS",
            21: "RIGHT FLIPPER EOS", 22: "RIGHT INLANE", 23: "RIGHT OUTLANE",
            26: "HAND HIT", 27: "CABIN VUK", 28: "CABIN FRONT DROP TARGET",
            29: "CABIN BACK DROP TARGET", 30: "RIGHT RAMP SCOOP",
            31: "NECKLACE LEFT", 32: "RIGHT SCOOP", 33: "NECKLACE RIGHT",
            34: "NECKLACE CENTER", 35: "RIGHT DEADITE BASH",
            36: "RIGHT DEADITE EOS", 37: "LIFT BANK LEFT TARGET",
            38: "LIFT BANK MIDDLE TARGET", 39: "LIFT BANK RIGHT TARGET",
            40: "SHOTGUN RIGHT", 41: "SHOTGUN LEFT", 42: "LEFT DEADITE EOS",
            43: "LEFT DEADITE BASH", 44: "MOUSE TRAP TARGET",
            45: "GROOVY DROP 1 G", 46: "GROOVY DROP 2 R",
            47: "GROOVY DROP 3 O", 48: "GROOVY DROP 4 O",
            49: "GROOVY DROP 5 V", 50: "GROOVY DROP 6 Y", 51: "LEFT SLING",
            52: "LEFT FLIPPER EOS", 53: "LEFT INLANE", 54: "LEFT MIDLANE",
            55: "LEFT OUTLANE", 56: "CAPTIVE BALL", 57: "MIDDLE VUK",
            58: "UPPER POP", 59: "MIDDLE POP TARGET", 60: "UPPER POP TARGET",
            61: "LOWER POP", 62: "LOWER POP TARGET", 63: "MIDDLE POP",
            64: "TROUGHJAM", 65: "ESCAPE PATH", 66: "TROUGH1",
            67: "LOWER PF LOOP", 68: "LOWER PF DRAIN",
            69: "LOWER PF LAUNCH LANE", 71: "SUBWAY", 73: "LEFT RAMP",
            74: "REAR ORBIT OPTO", 75: "LEFT ORBIT", 76: "CABIN ENTRY",
            77: "RIGHT RAMP", 78: "RIGHT ORBIT", 79: "MIDDLE RAMP",
            80: "RIGHT FLIPPER", 81: "ACTION BUTTON",
            82: "RIGHT UPPER FLIPPER", 83: "LEFT UPPER FLIPPER", 84: "TILT",
            85: "LAUNCHBUTTON", 86: "LEFT FLIPPER", 87: "START BUTTON",
            90: "COIN", 91: "MENU BUTTON", 92: "VOLUME UP", 93: "VOLUME DOWN",
            94: "BACK BUTTON", 95: "RIGHT SLING FLIPPER",
        },
    },
    # Looney Tunes 2025.10.08 (autoloads/switches.gd).
    "looney": {
        "name": "Looney Tunes", "engine": "godot", "layout": "flat",
        # A release build prints nothing.  Attract's hardware start (two
        # seconds in) is the only thing that turns the coils' 48 V on at
        # boot (modes/attract.gd), so the board's log says when.
        "attract": "power 48v on", "attract_in": "warden.log",
        "trough": [49, 6, 5, 4, 3, 2, 1], "jam": 48, "shooter": 7,
        # autoloads/coils.gd: TROUGH_EJECT, AUTOPLUNGER; game.gd: 7 balls.
        "eject": [12], "launch": {9: 7}, "balls": 7,
        "switches": {
            1: "TROUGH7", 2: "TROUGH6", 3: "TROUGH5", 4: "TROUGH4",
            5: "TROUGH3", 6: "TROUGH2", 7: "SHOOTER LANE", 8: "TNT TOP",
            9: "TNT LOCK", 10: "TNT BOTTOM", 11: "TNT MIDDLE",
            12: "SLING RIGHT", 13: "FLIPPER EOS LR", 14: "INLANE RIGHT",
            15: "OUTLANE RIGHT", 16: "VAULT", 17: "SAM", 18: "SPINNER",
            19: "HOLE", 20: "SLING LEFT", 21: "FLIPPER EOS LL",
            22: "INLANE LEFT", 23: "OUTLANE LEFT", 24: "CRATE",
            25: "MARVIN ORBIT", 26: "CARROT LEFT", 27: "FLIPPER EOS UL",
            28: "VAULT TARGET BOTTOM", 29: "DROP TARGET",
            30: "VAULT TARGET TOP", 32: "VUK", 33: "SYLVESTER ORBIT",
            34: "CARROT RIGHT", 35: "FLIPPER EOS UR", 36: "FUSE",
            40: "TNT STACK", 41: "RAMP MADE LR", 42: "VAULT STACK",
            43: "DIVERTER ORBIT", 45: "RAMP MADE LL", 46: "RAMP MADE UL",
            47: "HOLE STACK", 48: "TROUGH JAM", 49: "TROUGH1", 50: "RR ORBIT",
            51: "CRATE ENTRY", 52: "RAMP MADE UR", 53: "GRINDER OPTO",
            54: "COYOTE ORBIT", 55: "MAGNET", 59: "TAZ HOME", 60: "LOCK ENTER",
            61: "LOCK RIGHT", 62: "LOCK CENTER", 63: "LOCK LEFT",
            80: "FLIPPER BUTTON LR", 81: "ACTION", 82: "FLIPPER BUTTON UR",
            83: "FLIPPER BUTTON UL", 84: "TILT", 85: "LAUNCH",
            86: "FLIPPER BUTTON LL", 87: "START", 90: "COIN", 91: "ENTER",
            92: "UP", 93: "DOWN", 94: "EXIT", 95: "CABINET EXTRA",
        },
    },
    # Halloween v1.18.1 (SwitchConfig.cs, CoilConfig.cs).  Not a Warden
    # game: its board is the Pinotaur (spkpinotaur.py), with its own switch
    # numbers for the cabinet.
    "h78": {
        "name": "Halloween", "engine": "unity", "layout": "code",
        "board": "pinotaur",
        # Unity's own log is switched off on Linux and the game's text log
        # keeps exceptions only.  Attract turns the coils on once the
        # machine is ready (machineMode machine_state_3) - the board says.
        "attract": "coils enabled", "attract_in": "warden.log",
        # A machine has its high scores; a first start without them dies
        # (run_game.sh).
        "seed": ["highscores.config:config/default_highscores.config"],
        "trough": [65, 22, 21, 20, 16, 19, 18], "jam": 64, "shooter": 23,
        # coil 18 "trough", 21 "launch"; installed_balls defaults to 7.
        "eject": [18], "launch": {21: 23}, "balls": 7,
        # A manual shooter: the launch coil fires only for ball saves and
        # multiballs, so Plunge lets the ball go itself (spkwarden.plunge).
        "manual_plunger": True,
        # The board reports raw inputs and the game inverts its reversed
        # optos (scoops, subway) itself, so at rest they read open here.
        # The pumpkin drop bank's switches read made while its targets
        # stand (pumpkinMode.count_targets: the game reverses them twice);
        # without that it resets the bank five times and calls it a
        # hardware issue.
        "rest": [27, 28, 29],
        # What the other mechanisms do to their switches (the game's own
        # VirtualCoil.cs): the bank reset stands the pumpkin targets up,
        # knockdown coils drop a target (made = down), reset coils stand
        # it up, the mid-playfield scoop kicks its ball out.
        "sets": {11: {27: 1, 28: 1, 29: 1}, 12: {31: 1}, 13: {31: 0},
                 7: {30: 1}, 6: {30: 0}, 4: {26: 0}, 5: {6: 0}},
        "aliases": {"start": 87, "launch": 84, "coin": 56, "tilt": 85,
                    "enter": 60, "back": 63, "up": 61, "down": 62,
                    "lflip": 81, "rflip": 80, "ulflip": 83, "urflip": 82},
        "switches": PINOTAUR_SWITCHES,
    },
    # Ultraman v1.18 (SwitchConfig.cs, CoilConfig.cs, VirtualCoil.cs):
    # Halloween's code base ("H78UM") on the same Pinotaur board, wired the
    # same - trough, cabinet, the pumpkin bank's places, every coil the
    # Halloween profile names - so the same mechanisms.  The board's
    # game-name row says Ultraman (0 1; firmware.cs GameSetting).
    "um": {
        "name": "Ultraman", "engine": "unity", "layout": "code",
        "board": "pinotaur", "game_row": [0, 1],
        "attract": "coils enabled", "attract_in": "warden.log",
        "seed": ["highscores.config:config/default_highscores.config"],
        "trough": [65, 22, 21, 20, 16, 19, 18], "jam": 64, "shooter": 23,
        "eject": [18], "launch": {21: 23}, "balls": 7,
        "manual_plunger": True,
        "rest": [27, 28, 29],
        "sets": {11: {27: 1, 28: 1, 29: 1}, 12: {31: 1}, 13: {31: 0},
                 7: {30: 1}, 6: {30: 0}, 4: {26: 0}, 5: {6: 0}},
        "aliases": {"start": 87, "launch": 84, "coin": 56, "tilt": 85,
                    "enter": 60, "back": 63, "up": 61, "down": 62,
                    "lflip": 81, "rflip": 80, "ulflip": 83, "urflip": 82},
        "switches": PINOTAUR_SWITCHES,
    },
}

# app.info's product line of a Unity build -> title.
UNITY_PRODUCTS = {"SPF": "bj", "Scooby": "scooby", "TCM": "tcm",
                  "Evil Dead": "ed"}
PINOTAUR_PRODUCTS = {"VideoServer"}      # Halloween, Ultraman
# Which Pinotaur game: the update's own name, kept in its code (staticVars
# correctUpdateFileName, a UTF-16 string in Assembly-CSharp.dll) -> title.
PINOTAUR_UPDATES = {"code_H78.pkg": "h78", "code_UM.pkg": "um"}
# application/config/name of a Godot game's PCK -> title.
GODOT_PROJECTS = {"GDToons": "looney"}


def get(key=None):
    """The profile of <key>, else of $SPK_TITLE, else Beetlejuice's."""
    return TITLES[key or os.environ.get("SPK_TITLE") or "bj"]


def optos(key=None):
    t = get(key)
    return set(t["trough"]) | {t["jam"]} | set(t.get("optos", ()))


def aliases(key=None):
    """Cabinet names -> switch numbers: the Warden's wiring, unless the
    title wires its cabinet differently (Halloween's Pinotaur)."""
    t = get(key)
    return dict(t.get("aliases", CABINET_ALIASES), shooter=t["shooter"])


def _app_info(d):
    for sub in ("main_Data", "uptest/main_Data"):
        p = os.path.join(d, sub, "app.info")
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = [x.strip() for x in f.read().splitlines()]
            return sub, (lines + ["", ""])[1]
    return None, None


def godot_project(exe):
    """application/config/name of the PCK inside a Godot binary, "" when it
    has none, None when there is no PCK.  The PCK's size and "GDPC" are the
    file's last 12 bytes; its file table (format 2) names project.binary."""
    try:
        with open(exe, "rb") as f:
            f.seek(-12, 2)
            tail = f.read(12)
            if tail[8:] != b"GDPC":
                return None
            start = f.seek(-12 - int.from_bytes(tail[:8], "little"), 2)
            head = f.read(100)
            base = int.from_bytes(head[24:32], "little") or start
            for _ in range(int.from_bytes(head[96:100], "little")):
                n = int.from_bytes(f.read(4), "little")
                path = f.read(n + (-n) % 4)[:n].rstrip(bytes(1))
                meta = f.read(36)
                if path == b"res://project.binary":
                    f.seek(base + int.from_bytes(meta[:8], "little"))
                    proj = f.read(int.from_bytes(meta[8:16], "little"))
                    break
            else:
                return ""
    except OSError:
        return None
    # key, value size, type (4 = String), length, the characters.
    m = re.search(rb"application/config/name.{8}(.{4})", proj, re.S)
    if not m:
        return ""
    i = m.end()
    n = int.from_bytes(m.group(1), "little")
    return proj[i:i + n].decode("utf-8", "replace")


def detect(d):
    """(key, None) for a title this rig runs, else (None, why)."""
    sub, product = _app_info(d)
    if product in UNITY_PRODUCTS:
        key = UNITY_PRODUCTS[product]
        code = TITLES[key]["layout"] == "code"
        if sub != ("uptest/main_Data" if code else "main_Data"):
            return None, ("%s, laid out as no update of it is"
                          % TITLES[key]["name"])
        return key, None
    if product in PINOTAUR_PRODUCTS:
        if sub != "uptest/main_Data":
            return None, "a Pinotaur-board game laid out as no update of it is"
        dll = os.path.join(d, sub, "Managed", "Assembly-CSharp.dll")
        try:
            with open(dll, "rb") as f:
                code = f.read()
        except OSError:
            code = b""
        for upd, key in PINOTAUR_UPDATES.items():
            if upd.encode("utf-16-le") in code:
                return key, None
        return None, ("a Pinotaur-board game this emulator does not know yet "
                      "- it runs Halloween and Ultraman")
    if product is not None:
        return None, "an unknown Unity game (%s)" % (product or "no name")
    exe = os.path.join(d, "main.x86_64")
    proj = godot_project(exe) if os.path.isfile(exe) else None
    if proj in GODOT_PROJECTS:
        return GODOT_PROJECTS[proj], None
    if proj is not None:
        return None, "an unknown Godot game (%s)" % (proj or "no name")
    return None, "no Spooky Warden game in it"


def passphrase(name):
    """The passphrase a GPG-symmetric Spooky .pkg is encrypted with, read
    from the app's own Spooky plugin (as tools/ap_emu reads AP's key), or
    None."""
    here = os.path.dirname(os.path.abspath(__file__))
    games = os.path.join(here, "..", "..", "pinball_decryptor", "plugins",
                         "spooky", "games.py")
    ns = {}
    try:
        with open(games) as f:
            exec(compile(f.read(), "games.py", "exec"), ns)
    except OSError:
        return None
    for prefix, _game, fmt in ns.get("PKG_FILENAME_PATTERNS", ()):
        if name.startswith(prefix):
            return ns.get("GPG_PASSPHRASES", {}).get(fmt)
    return None


def main(a):
    if a[:1] == ["passphrase"] and len(a) == 2:
        p = passphrase(a[1])
        if p:
            print(p)
        return 0 if p else 1
    if a[:1] == ["detect"] and len(a) == 2:
        key, why = detect(a[1])
        print(key or "no " + why)
        return 0 if key else 1
    if a[:1] == ["get"] and len(a) == 3 and a[1] in TITLES:
        v = TITLES[a[1]].get(a[2], "")
        print(" ".join(str(x) for x in v) if isinstance(v, list) else v)
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
