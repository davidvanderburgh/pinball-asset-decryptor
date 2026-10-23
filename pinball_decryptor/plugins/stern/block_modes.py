"""A mode made of BLOCKS: rules snapped together in the Modes tab, turned into C (PAD-232).

The third way to make a mode, beside the form (:mod:`.mode_project`) and C (:mod:`.code_modes`).
A blocks mode IS a code mode: its folder holds ``<slug>.c`` and no ``mode.json``, so Try it,
Write, Duplicate, Copy to and Delete treat it exactly as they treat a mode written in C. What
makes it a blocks mode is ``blocks.json`` beside the C file: the program the page edits. Every
save writes the program and then the C it makes (:func:`to_c`), so the C file is always the
program's; a person who wants to carry on in C presses "Edit as C" (:func:`detach`), which
takes ``blocks.json`` away and leaves an ordinary code mode.

THE PROGRAM (``blocks.json``)::

    {
      "format": 1,
      "name": "RAMP FRENZY",
      "seconds": 30,              the mode's clock; 0 = no clock (it runs until a block ends it)
      "ends_on_drain": true,      the ball draining ends it
      "game_modes": "block",      PAD-373: while it runs, the game's own modes may start ("stack"), may start
                                  and end it ("give_way": it also starts only while none runs), or cannot
                                  start ("block", PAD-398's default: as give_way, the ones in block_modes are
                                  held off, and the game's features see no shots but keep_rules)
      "block_modes": [21, 23],    the title's mode ids it holds off ([] = every one the port names)
      "keep_rules": ["Bridge"],   PAD-398: the game's features (rules, by name) that keep counting
      "vars": [{"name": "combo", "reset": "ball"}],   per player; reset "ball" | "mode" | "game"
                                  ("shared": true = the same value in every mode that names it)
      "timers": [{"name": "window"}],  counts down in milliseconds (PAD-377)
      "wait_multiball": true,     a Start the mode while a multiball runs waits for the next one
      "priority": 180,            its display priority while it runs (0 = none)
      "hud": {"on": true, "line": "SHOOT THE RAMPS",    PAD-375: the mode's HUD at the glass's edges
              "counters": [{"label": "COMBO", "sub": "", "value": {...}}, ...],   three across the top
              "timer": {"on": true, "label": "RAMPS", "icon": "maser"},         the badge counting its clock
              "gauge": {"on": false, "label": "", "kind": "diamond", "count": 3, "color": "#ff7800",
                        "value": {...}}},                                       pips on the right edge
      "clips": [{"name": "sever", "file": "sever.mp4"}],      PAD-374: its own clips and sounds,
      "sounds": [{"name": "roar", "file": "roar.wav", "priority": 4}],   files in its folder
      "music": "music.wav",       its own music bed while it runs ("" = the game's music)
      "beds": [{"name": "swamp", "file": "music_swamp.wav"}],   PAD-658: more beds; a Play the music block switches
                                  to one while it runs ({"op": "music", "bed": "swamp"}; "" = its own music again)
      "screen_style": "words",    PAD-521: its own screen as words alone, large and white over the game's video (the
                                  game's own look: a name over its intro, the TOTAL over its end); "panel" = the panel
      "bar": {"on": true, "color": "#00c040"},   PAD-521: its name in the game's own status bar (James Bond: the
                                  coloured bar under the TV), in this colour, its clock draining along it
      "info": {"on": true, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}},   PAD-547: a line
                                  under its name while it runs, its words and the value as it changes ("SUPER
                                  JACKPOT = 53,200,000"), where the title's port puts one (James Bond: under the
                                  status bar, as the game's own mini-wizards show theirs); on every title with screens
      "scripts": [
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"},
         "do": [{"op": "if", "cond": {...}, "then": [...], "else": [...]}, ...]}
      ]
    }

A script is a HAT (what sets it off) and the blocks it runs, in order. Hats: the mode starts or
ends, a shot is made (any time, or only while the mode runs or does not), any shot, every N
seconds while it runs, N seconds left, the ball drains, one of the game's events. Blocks: start
or end the mode, score, set or change a variable, if / else, a callout, words on the mode's
screen, light or free a shot's inserts, add time or set the clock (to any value: a variable,
the seconds left, a sum), a multiball, a line in the log, and (PAD-374) play one of the mode's
own clips (full screen, behind the HUD once, or behind the HUD over and over while it runs) or
one of its own sounds (with a callout of the game's when the card could not carry it), and
(PAD-376) run a light show (a ready-made one, or its own steps: the examples' kit_show) and light
a shot at a pace of its own (any value, in ms) or blinking faster as the clock runs down, and (PAD-395)
hold one of the game's mechanisms (Godzilla's magnet, and on a Premium/LE the Mechagodzilla magnet
and the bridge) for a time, hold the next ball (or every ball) in the scoop, and let go, and (PAD-392)
turn Godzilla Premium/LE's shield targets toward the player or away, kept there while it runs, (PAD-589)
move its building to one of the game's own floors, put back when it ends, (PAD-418)
play one of the game's own light shows by its port's name (Godzilla Premium/LE's ten), and (PAD-414)
shake the cabinet's shaker for N ms at a strength, or with one of the game's own shakes (its jackpot shake...) -
one in When the mode ends runs out after the mode, and (PAD-436) hand the player one of the game's own
mini-wizards, lit for its start shot or started (James Bond LE 1.06's four), and (PAD-503) light the
mode itself at a shot, as the game lights one of its mini-wizards. Values: a
number, a variable, a shot's hits this ball, how many shots the mode has scored, its points so
far, the seconds left, the balls in play, the player up, and + - x / of two values. Conditions:
compare two values, and / or / not, the mode is running, one of the game's own modes is running,
the mode could start now, the mode is lit.

LIT AT A SHOT (PAD-503). A Bond owner made modes of their own for the two films with no mini-wizard and
wanted them as the game's four are: lit at the Right ramp with the film's villain, started by the ramp. Light
the mode at (``{"op": "light_mode", "shot": ..., "insert": "MR. HENDERSON", "color": ..., "pattern": "blink"}``) lights
it for the player up: while the mode is not running, the shot's inserts and the one insert named (any the port
names, "" = none) are held in its colour, ball after ball, and that shot made starts the mode as Start the mode
does (so it waits, and stays lit, while one of the game's own modes or a multiball is in its way, as the mode is
set). Starting, however it starts, puts the light out; a new game too. Each player's is their own.
The same owner's next games (PAD-503, v1.169.0): the light went out when the game's mode that won the film's last
part ended, and a Right ramp in the middle of the game's Mr Osato started the mode. So (1) a NEW GAME is the SDK's
witness (player 1's score back to 0, or pm_in_game() rising while it is 0: ``new_game``), not pm_in_game() rising:
James Bond ends play at the end of each of its multiballs and wizard modes (mode-mask busy bits until the ball ends),
and the next ball's pm_in_game() rising wiped the light, the "each game" values and the timers; (2) the lit shot,
and any start that waits for the game's modes, also waits on the game's own check before one of its mini-wizards
(pm_game_wizard_way: its henchman, villain and Q Branch modes, which the port's flags do not show). Then (v1.169.3):
the Right ramp kept starting one of the game's villains instead - it is where Bond starts its henchman and villain
modes, and the game handles a shot before the modes hear of it. So (3) while the mode would start on its lit shot,
it CLAIMS the shot every tick (pm_lit_claim): a hit on that switch holds the game's own starts off while the game
handles it, and the shot starts the lit mode; the game's henchman or villain waits for a later shot.
The same owner then (PAD-521) wanted their modes to look like the game's own: while one of its mini-wizards is
qualified the Right ramp's villain inserts cycle and the film's insert is solid. So the block's ``insert`` may name
several inserts, separated by commas as pm_lamp_set takes them (up to LIT_INSERTS_MAX; a Chase runs across them in
that order), and ``solid`` / ``solid_color`` one insert more held solid while it is lit (the film's).
Then (PAD-556): Blofeld, the game's villain mode, won the film's last part and the villains began to rove at once,
though the mode could not start until Blofeld was over; the game's own rove only then. So while the game's own check
says one of its modes is in the way, only the solid insert is held: the shot and the chase come once it is clear.
Then (PAD-598) a Beatles owner lit their mode at Target 4 with RINGO SPINNER pulsing and wanted that insert to change
as the mode started, but the Light block could only pick a shot. A Light or Hand back block may name one of the game's
own lights instead (``insert``: an insert, a GI string or a flasher, the port's `lamp` lines) in the place of its
``shot``; it is held by name as a shot's lights are (a slot of LIT after the shots), and the lit light going out at the
start leaves it the mode's.

ONE QUALIFIED AT A TIME (PAD-600). A Beatles owner made four modes, one per target (Target 1-4), each qualified and
lit by three hits of its target, and wanted only one ready at a time, as Batman's villains are: the target that
qualifies takes the other targets' hits back below three and puts their lights out. So (1) Set the hits of
(``{"op": "set_hits", "shot": ..., "value": <num>}``) sets a shot's hits this ball for the player up, and a shot's
hits are ONE count for every blocks mode on the card: each mode still counts them itself (each sees every shot, and
every one clears them when the ball ends or a game begins, so their counts agree), and the block keeps the
difference from the count in a weak global per shot (``pad_hits_<shot>``, as a shared variable is kept) that every
mode adds in (never below 0); (2) Put out the light of (``{"op": "unlight_mode", "mode": ""}``, "" = this mode, else
another mode's slug) puts out a Light the mode at for the player up: a mode's light (its ``lit_as``) is a weak global
too (``pad_lit_<mode>``), so another mode can clear it and that mode's next tick takes its lights down.

A LIGHT UNDER ANOTHER (PAD-601). The same owner used one insert for two things: one mode's light on it, and a
higher one's over it while that one runs. When the higher one ended its lights went to the game, and the insert was
dark (or the game's) though the first mode still had it lit; a Light block in its When the mode ends could not put
it back, as the end hands every light back after that hat. So the runtime keeps, per insert, the holds it was taken
from (pad_mode_runtime.c ``lamp_under``): when the mode on top lets go, the latest one still holding it has it back.
And a Light block may light it "off" (held dark), where Hand back lets the game's own light show through.

What a mode in C does with the kit (``sdk/examples/intricate_kit.h``), PAD-377 gives the blocks:

- A SHARED variable is one value per player that every mode naming it reads and writes - the
  kit's ledger, with which FINAL WARS is lit by what the other modes did. It is a weak C global
  (``pad_shared_<name>``), so the linker keeps one for all the modes built into the card; a mode
  written in C shares it by declaring the same line. It resets each ball or each game.
- A TIMER counts down in milliseconds, not whole seconds: Start timer (any value, so a window can
  shrink), Stop timer, the milliseconds a timer has left, and a When a timer runs out hat. Timers
  run whether the mode does or not; a ball ending stops them.
- WAITS OUT A MULTIBALL (``wait_multiball``): Start the mode does nothing while a multiball or
  one of the game's own modes runs (the kit's ``kit_wait_game``); the mode stays ready, so the
  next block that starts it afterwards does. "the mode could start now" asks the same.
- A DISPLAY PRIORITY (``priority``): held while the mode runs (``kit_display``), kept for the
  total its own screen shows at the end (PAD-622: and at a drain, through its TOTAL there).

THE HUD (PAD-375). Ticked on, the mode has what the examples have at the glass's edges, built by the
card build like theirs (:mod:`.mode_hud`, from the ``hud`` this module writes into assets.json): the
mode's name and an instruction line above the score panel, up to three counters across the top (each
can follow a value by itself), a timer badge counting the mode's clock, a gauge of pips on the right
edge, and an award line for a moment. Blocks write it: the title or instruction line, a counter, the
gauge, an award (on a mode that is not running, the award is a note: shown alone for its moment, when
no other HUD is up). The C drives it with the examples' own kit (``intricate_kit.h``'s ``struct
kit_hud``, copied into the folder at every save), so it steps aside exactly as theirs do: under a
display of the game's (``pm_display_covered``) its words are blank and the edges stay; while one of
the game's own modes runs (``pm_aside``) its lines go into the award line, the counters hide, and the
badge moves one slot down for a battle. The mode's own screen, when it has one, is hidden then too.
At the end the HUD shows the mode's TOTAL for three seconds (the game moving on takes it down at once).

A DRAIN (PAD-622). The game's own mini-wizards (James Bond) show their TOTAL when the ball drains in one,
and the bonus waits for it. A mode the ball's drain ends does the same: it ends as its clock would (an
Award it ended on, then its TOTAL, on its HUD or its own screen, the bar kept) and asks the runtime to
hold the game's end of ball (``pm_ball_end_hold``) for ``DRAIN_TOTAL_MS`` - the 6 s the game's own TOTAL
shows - or for the rest of a total already showing; when the end of ball goes on, it all goes. A tilted
ball, or a port without the hold, takes it down at once as before.

PAD-373: what it does about the game's own modes is the form's choice (PAD-363): they may start
(``stack``), it gives way (``give_way``: it starts only while none of them runs - a Start the mode
then waits, and the next one starts it - and one of them beginning ends it at once), or it holds
them off (``block``: as give_way, and while it runs the ones in ``block_modes``, or the port's
checked defaults, cannot start: ``pm_block_game_modes``), as the SDK's examples do with the kit's
kit_wait_game / kit_isolate_list / kit_game_began.

The C is the SDK's template (``sdk/template_mode.c``) in shape: static state, never blocking, a
0 from the game is carried on past, ``pm_begin`` / ``pm_end`` around a run, and the folder's own
test triggers (``/dump/<slug>.start`` / ``.stop``) so the tab's Start mode now and End mode reach
it. Its names follow ``mode_tryit.code_mode_text`` (``PadMode_<slug>_Screen``, ``<ident>_mode``)
so a rename rewrites it the way it rewrites any code mode.

ITS OWN CLIPS AND SOUNDS (PAD-374) are a code mode's: every save puts them in the mode's
``assets.json`` (``clips``, ``calls``, ``music``; :func:`_sync_assets`), so Write and Try it carry
them as they carry an example's, and the C plays them by name through ``pad_mode_assets.h``. A
clip's or sound's name is its cue there. The C starts the mode's own assets itself rather than
with ``pa_start``, so no name is special: a clip called "intro" or "loop" plays when a block
says, never on its own.

LIGHTS (PAD-376). The shots the blocks light are kept in a table (``LIT``), not only sent: a light
show (the kit's ``kit_show``, its engine written into the C only when a Light show block is there)
paints every placed insert while it runs, and at its end hands them back and sends the table
again; a blink that hurries is sent again each time the clock moves it to a faster pace; and the
same light lit again is not sent again, so a blink keeps its beat. A show started in When the
mode ends runs on after the mode, as the examples' end shows do.

THE MODE'S OWN LIGHT SHOWS (PAD-646). David wanted light shows made from scratch, "in a beautiful and
elegant way": presets with timing, a preview in the app, several shows through a mode. So a mode keeps
its own named shows (``shows``: ``[{"name", "steps", "repeat"}]``, up to SHOWS_MAX, each up to SHOW_STEPS
steps), made on the Modes tab's Light shows page (modes_lightshows.js: the show's steps as a timeline,
each step's pattern, time, colors, centre, pace and GI, and the playfield picture playing the show with
the very arithmetic the C runs, mirrored insert by insert), and a Run the light show block runs one by
name (``{"op": "show", "show": "mine", "name": "Kaiju roar"}``) from any rule: at the start, at a shot,
with N seconds left, at the end. The ready-made shows (SHOWS) and a block's own steps (``"own"``) stay.
A step may BLEND in from the step before over its first ``blend`` ms (from dark when it is the first),
centre on a point of its own (``at`` "xy" with ``x``, ``y``, picked on the picture), and the patterns
gained a spiral out and in, ripples, a beam side to side, a fade up and a held color. A show's
``repeat`` is how many times it runs (1-REPEAT_MAX), or 0: over and over until the mode ends, when the
pass it is in finishes (``show_last_pass``). The C keeps one table per show the blocks run, however many
blocks run it, and only the shows a block runs (an unused table would be a compiler warning).
"""
from __future__ import annotations

import copy
import json
import os
import re

from . import mode_project as MP

BLOCKS_FILE = "blocks.json"
FORMAT = 1
SECONDS_MAX = 600
MAX_SCRIPTS = 48
MAX_BLOCKS = 600                    # PAD-658: 400 held the bigger examples back once their lines named every shot
MAX_DEPTH = 10
MAX_VARS = 24
MAX_TIMERS = 8
TIMER_MAX_MS = SECONDS_MAX * 1000
PRIORITY_MAX = 255
#: the display priorities the page offers (any 0..255 loads): MODE_SDK.md "Display priority"
PRIORITIES = {0: "none", 180: "a mode's (180)", 190: "a wizard mode's (190)"}
NUMBER_MAX = 10 ** 15            # points, counts and seconds: any sane number fits
TEXT_MAX = 60

#: what sets a script off, and the words the page shows for it
HATS = {
    "mode_start": "When the mode starts",
    "mode_end": "When the mode ends",
    "shot": "When a shot is made",
    "any_shot": "When any shot is made",
    "switch": "When any playfield switch is hit",     # PAD-675: every switch's own hit, as the C modes counted them
    "every": "Every few seconds while it runs",
    "seconds_left": "When seconds are left",
    "ball_end": "When the ball drains",
    "event": "When the game does something",
    "timer_done": "When a timer runs out",
    "challenge": "When the player picks a challenge",
}
#: PAD-615 round 2: the challenge hat's choice that adds the mode to the game's start menu as a challenge of its own
CHALLENGE_NEW = "A new challenge of its own"
#: PAD-643: the challenge hat's `launch` - who launches the challenge ball, and when: "clip" (the runtime, once the
#: mode's start clip is over - the default), "player", or a number of seconds after the mode began (1 to 60)
CHALLENGE_LAUNCH = ("clip", "player")


def challenge_launch_ms(hat):
    """PAD-643: the runtime's pm_challenge_launch value for a challenge hat: 0 its start clip, -1 the player, ms."""
    v = str((hat or {}).get("launch") or "clip").strip()
    if v == "player":
        return -1
    if v.isdigit():
        return max(1, min(60, int(v))) * 1000
    return 0
#: a shot / event hat's "when": the mode's state it runs in
WHEN = {"any": "any time", "idle": "while the mode is not running", "running": "while the mode runs"}
RESETS = {"ball": "each ball", "mode": "each time the mode starts", "game": "each game"}
SHARED_RESETS = ("ball", "game")
STATEMENTS = ("start_mode", "end_mode", "score", "set", "change", "if", "callout", "words",
              "light_shot", "lights_off", "add_time", "set_time", "multiball", "log", "clip", "sound",
              "show", "timer_start", "timer_stop", "hud_text", "hud_counter", "hud_gauge", "hud_award",
              "hold", "scoop_hold", "let_go", "shield", "building", "game_show", "shake", "shake_game", "game_wizard",
              "music",                                                   # PAD-658: switch to another music bed
              "light_mode", "unlight_mode", "set_hits")
#: PAD-395: the mechanisms a block holds, through the runtime as the form's Magnet, Scoop and Other
#: mechanisms do (PAD-381): a time asked for, clamped to these, and every other limit the runtime's own
HOLD_MIN_MS, HOLD_MAX_MS = MP.COIL_MIN_MS, MP.COIL_MAX_MS
#: PAD-621: a post the game keeps up itself is held up to its own longest (James Bond's right return up post: 14 s);
#: the C clamps to this and the runtime to each mechanism's own limit
HOLD_LONGEST_MS = MP.COIL_LONGEST_MS
SCOOP_MIN_MS, SCOOP_MAX_MS = MP.SCOOP_MIN_MS, MP.SCOOP_MAX_MS
#: PAD-621: a hold's "clock": the mode's clock runs on (""), or stands still until the hold lets go ("wait": the
#: ball held at the start while its clip plays, as the game's own mini-wizards do at Bond's right return up post)
HOLD_CLOCK = {"": "its clock runs", "wait": "its clock waits until it lets go"}
#: a scoop hold's reach: the next ball that settles there, or every one while the mode runs
SCOOP_WHICH = {"next": "the next ball", "every": "every ball"}
#: PAD-392: where a block turns the shield targets (Godzilla Premium/LE's platform), kept there while the mode runs;
#: "leave" stops keeping them (they stay where they are). The runtime turns them back when the mode ends.
SHIELD_WHERE = {"toward": "toward the player", "away": "away", "leave": "where they are"}
#: PAD-589: the floors a block sends Godzilla Premium/LE's building to (the game's own; 0 is where it rests). The runtime
#: puts it back where it was when the mode ends.
BUILDING_FLOOR = {"1": "floor 1", "2": "floor 2", "3": "floor 3", "0": "back where the game keeps it"}
#: PAD-414: a shake's strength (the game's own power steps, mode_project.SHAKE_STRENGTHS), and its length: at least
#: SHAKE_MIN_MS, at most the game's own longest at that strength (the runtime clamps a value worked out while it runs)
SHAKE_STRENGTH = {v: k for k, v in MP.SHAKE_STRENGTHS.items()}
SHAKE_MIN_MS, SHAKE_MAX_MS = MP.SHAKE_MIN_MS, 5000
#: PAD-375: the HUD's pieces (mode_hud.py draws them): the badge's icons, the gauge's pips
HUD_ICONS = ("xilien", "bolt", "ghidorah", "oxygen", "maser", "radiation", "anguirus",
             # PAD-658: the badges PAD-379's modes drew (mode_hud.py), so their blocks keep them
             "rage", "crystal", "snowflake", "rose", "claw")
GAUGE_KINDS = ("diamond", "segment", "spike",
               "bar")            # PAD-658: PAD-416's POWERUP-style meter at the top-right corner; its value a percent
GAUGE_MAX = 12                   # a pip gauge's pips
BAR_MAX = 40                     # a bar's slices (intricate_kit.h's KIT_HUD_PIPS, mode_hud.BAR_SLICES_MAX)
HUD_TEXT_MAX = 40                # a title or line (the kit's KIT_HUD_WORDS is 48, with its number)
COUNTER_MAX = 16                 # a counter's label or sub-label (the kit holds 23)
BADGE_MAX = 12                   # the badge's label, lettered on the stock BATTLE panel
AWARD_SECONDS_MAX = 10
KIT_FILE = "intricate_kit.h"
HUD_PRIORITY = 180               # a HUD mode with no priority of its own takes the kit's KIT_DISPLAY_MODE:
                                 # pm_display_covered watches for it
TOTAL_MS = 3000                  # the HUD's TOTAL stays up this long after the end
DRAIN_TOTAL_MS = 6000            # PAD-622: at a drain, held as the game's own mini-wizards hold theirs
#: a lit shot's pattern: the SDK's, and its pace (ms) when the block gives none. "hurry" is a
#: blink that quickens as the clock runs down (PAD-376, the kit's kit_hurry_ms); "off" holds it dark (PAD-601: the
#: game's own light there does not show through, as it does when the light is handed back)
PATTERNS = {"solid": ("PM_LAMP_SOLID", 0), "blink": ("PM_LAMP_BLINK", 500),
            "pulse": ("PM_LAMP_PULSE", 1600), "chase": ("PM_LAMP_CHASE", 150),
            "hurry": ("PM_LAMP_BLINK", 0), "off": ("PM_LAMP_SOLID", 0)}
RATE_MIN, RATE_MAX = 20, 5000    # a blink's, pulse's or chase's pace, ms
#: PAD-503: a mode lit at a shot shows it in one of these (no clock runs while it is lit, so no hurry)
LIT_PATTERNS = ("solid", "blink", "pulse", "chase")
INSERT_MAX = 39                  # an insert's name (pad_mode_runtime.c struct lamp keeps 39 letters)
LIT_INSERTS_MAX = 8              # PAD-521: a mode lit at a shot lights up to this many inserts more (a chase runs across them)
# ---- light shows (PAD-376): the kit's kit_show, steps of a pattern over the placed inserts ----
#: a step's pattern: its C name, and the words the page shows
FX = {"burst": ("FX_BURST", "a ring bursting out"), "implode": ("FX_IMPLODE", "a ring closing in"),
      "sweep_up": ("FX_SWEEP_UP", "a sweep up"), "sweep_down": ("FX_SWEEP_DOWN", "a sweep down"),
      "sweep_lr": ("FX_SWEEP_LR", "a sweep left to right"), "sweep_rl": ("FX_SWEEP_RL", "a sweep right to left"),
      "spin": ("FX_SPIN", "a turning beam"), "rainbow": ("FX_RAINBOW", "a turning rainbow"),
      "strobe": ("FX_STROBE", "a strobe"), "sparkle": ("FX_SPARKLE", "sparkles"),
      "fire": ("FX_FIRE", "fire"), "pulse": ("FX_PULSE", "breathing"),
      "chase": ("FX_CHASE_RING", "a chase round"), "fade": ("FX_FADE_OUT", "a fade to dark"),
      "bolts": ("FX_BOLTS", "lightning"),
      # PAD-646: the light-show editor's patterns
      "spiral_out": ("FX_SPIRAL_OUT", "a spiral outwards"), "spiral_in": ("FX_SPIRAL_IN", "a spiral closing in"),
      "ripple": ("FX_RIPPLE", "ripples outwards"), "bounce": ("FX_BOUNCE", "a beam side to side"),
      "fade_in": ("FX_FADE_IN", "a fade up from dark"), "solid": ("FX_SOLID", "one color, held")}
#: PAD-646: the patterns by family, as the editor's list groups them
FX_GROUPS = (("Rings", ("burst", "implode", "spiral_out", "spiral_in", "ripple", "chase")),
             ("Sweeps", ("sweep_up", "sweep_down", "sweep_lr", "sweep_rl", "bounce")),
             ("Beams", ("spin", "rainbow")),
             ("Flashes", ("strobe", "sparkle", "fire", "bolts", "pulse")),
             ("Fades", ("fade_in", "fade", "solid")))
#: where a step centres: a place on the playfield picture (x 0-300 across, y 0-600 down); PAD-646: "xy" is a point
#: of the step's own (its ``x``, ``y``: picked on the preview's picture)
PLACES = {"center": ("the middle", 150, 330), "top": ("the top", 150, 120),
          "flippers": ("the flippers", 150, 560), "left": ("the left", 60, 330),
          "right": ("the right", 240, 330), "xy": ("a point of its own", 150, 330)}
XY_MAX = 2000                    # a point of a step's own: within the picture's pixels
#: what the general illumination does during a step (the kit's KIT_GI_*)
GI = {"keep": "GI: the game's", "dark": "GI: dark", "flash": "GI: flashing"}
SHOW_STEPS = 32                  # PAD-646: was the kit's KIT_SHOW_STEPS (10); the blocks' engine reads a table
STEP_MS_MIN, STEP_MS_MAX = 50, 10000
FX_RATE_MAX = 2000
# PAD-646: a mode's own shows (``shows``: [{name, steps, repeat}]), run by name from a Light show block
SHOW_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _'!-]{0,23}$")
SHOWS_MAX = 24                   # shows a mode may keep
REPEAT_MAX = 10                  # a show runs this many times at most; 0 = over and over until the mode ends


def _step(fx, ms, a, b, at, rate=0, gi="keep", blend=0):
    st = {"fx": fx, "ms": ms, "a": a, "b": b, "at": at, "rate": rate, "gi": gi}
    if blend:
        st["blend"] = blend
    return st


#: the ready-made shows a Light show block picks from (made after the examples' own)
SHOWS = {
    "burst": ("A burst of gold", [
        _step("strobe", 450, "#ffffff", "#ffb000", "center", 55, "flash"),
        _step("burst", 700, "#ffffff", "#ffb000", "center", 0, "dark"),
        _step("fade", 400, "#ffb000", "#000000", "center")]),
    "beams": ("Blue beams", [
        _step("strobe", 450, "#ffffff", "#0050ff", "center", 55, "flash"),
        _step("spin", 1600, "#a0e0ff", "#000000", "center", 110, "dark"),
        _step("sweep_lr", 500, "#ffffff", "#0050ff", "center", 0, "dark"),
        _step("sweep_rl", 500, "#ffffff", "#0050ff", "center", 0, "dark"),
        _step("fade", 400, "#0050ff", "#000000", "center")]),
    "lightning": ("Lightning", [
        _step("bolts", 1500, "#ffb000", "#000000", "center", 190, "dark"),
        _step("strobe", 500, "#ffffff", "#ffb000", "center", 60, "flash"),
        _step("burst", 800, "#ffb000", "#ff4000", "top", 0, "dark"),
        _step("fade", 400, "#ff4000", "#000000", "center")]),
    "fire": ("Fire", [
        _step("strobe", 500, "#ffffff", "#ff3000", "center", 60, "flash"),
        _step("fire", 1200, "#ffc000", "#ff3000", "center", 0, "dark"),
        _step("fade", 400, "#ff3000", "#000000", "center")]),
    "rainbow": ("A rainbow (a win)", [
        _step("burst", 800, "#ffffff", "#ffb000", "center", 0, "flash"),
        _step("rainbow", 1800, "#000000", "#000000", "center", 60),
        _step("fade", 500, "#ffb000", "#000000", "center")]),
    "sweep": ("Sweeps up and down", [
        _step("sweep_up", 600, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("sweep_down", 600, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("chase", 900, "#00ff60", "#000000", "center", 40),
        _step("fade", 400, "#00c040", "#000000", "center")]),
    "sparkle": ("Sparkles", [
        _step("sparkle", 1200, "#ffffff", "#4000a0", "center", 0, "dark"),
        _step("pulse", 1200, "#a040ff", "#200040", "center", 300),
        _step("fade", 500, "#a040ff", "#000000", "center")]),
    "fizzle": ("A fizzle (a loss)", [
        _step("spin", 1200, "#a000ff", "#000000", "center", 90, "dark"),
        _step("implode", 900, "#ffb000", "#a000ff", "center", 0, "dark"),
        _step("fade", 700, "#a000ff", "#000000", "center")]),
    # PAD-646: the editor's own starting points
    "spiral": ("A spiral outwards", [
        _step("spiral_out", 1800, "#40c0ff", "#001040", "center", 0, "dark"),
        _step("spiral_out", 1200, "#ffffff", "#0050ff", "center", 0, "dark", 300),
        _step("fade", 500, "#0050ff", "#000000", "center", 0, "keep", 200)]),
    "spiral_in": ("A spiral closing in", [
        _step("spiral_in", 1800, "#ff40a0", "#200010", "center", 0, "dark"),
        _step("burst", 700, "#ffffff", "#ff40a0", "center", 0, "flash", 150),
        _step("fade", 500, "#ff40a0", "#000000", "center", 0, "keep", 200)]),
    "fade_up": ("A fade up", [
        _step("fade_in", 1500, "#ffb000", "#000000", "center", 0, "dark"),
        _step("solid", 800, "#ffb000", "#000000", "center", 0, "dark"),
        _step("solid", 800, "#ffffff", "#000000", "center", 0, "keep", 800),
        _step("fade", 600, "#ffffff", "#000000", "center", 0, "keep")]),
    "left": ("A sweep to the left", [
        _step("sweep_rl", 700, "#ffffff", "#ff3000", "center", 0, "dark"),
        _step("sweep_rl", 700, "#ffffff", "#ff3000", "center", 0, "dark"),
        _step("fade", 400, "#ff3000", "#000000", "center", 0, "keep", 200)]),
    "right": ("A sweep to the right", [
        _step("sweep_lr", 700, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("sweep_lr", 700, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("fade", 400, "#00c040", "#000000", "center", 0, "keep", 200)]),
    "ripples": ("Ripples", [
        _step("ripple", 2400, "#00e0ff", "#002030", "center", 600, "dark"),
        _step("fade", 600, "#00e0ff", "#000000", "center", 0, "keep", 300)]),
    "scanner": ("A beam side to side", [
        _step("bounce", 1600, "#ff0000", "#200000", "center", 0, "dark"),
        _step("bounce", 1600, "#ff0000", "#200000", "center", 0, "dark"),
        _step("fade", 400, "#ff0000", "#000000", "center", 0, "keep", 200)]),
}
#: the game's own callouts a block can name by what they say (every port carries these roles)
CALLOUT_ROLES = {"ten_seconds": "Ten seconds left", "time_up": "Time is up"}
NUM_KINDS = ("num", "var", "hits", "scored", "total", "secs_left", "balls", "player", "op",
             "timer_left")
BOOL_KINDS = ("cmp", "and", "or", "not", "running", "stock", "can_start", "lit")
OPS = {"+": "+", "-": "-", "*": "*", "/": "/"}
CMPS = {"<": "<", "<=": "<=", "=": "==", "!=": "!=", ">=": ">=", ">": ">"}
#: PAD-373: what the mode does about the game's own modes while it runs (the form's choice, PAD-363)
GAME_MODES = {"stack": "may start", "give_way": "may start, and end this one", "block": "cannot start"}
BLOCK_ID_MAX = 127
#: PAD-374: where a clip block plays the mode's own clip
CLIP_WHERE = {"full": "full screen", "behind": "behind the HUD, once",
              "loop": "behind the HUD, over and over"}
#: a clip's or sound's name: its cue in assets.json and <slug>.assets (code_modes.CUE_RE)
MEDIA_RE = re.compile(r"^[a-z][a-z0-9_]{0,14}$")
MAX_CLIPS = 12                   # pad_mode_assets.h PA_CLIPS_MAX
MAX_SOUNDS = 16                  # pad_mode_assets.h PA_CALLS_MAX
MAX_BEDS = 6                     # PAD-658: pad_mode_assets.h PA_BEDS_MAX
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
VAR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _]{0,23}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
HOLD_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")   # a held coil's name in the port (`text held_coils`)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")  # PAD-600: another mode a Put out the light of block names


class BlocksError(ValueError):
    """A blocks.json that cannot be used; the message is a sentence."""


# ---- the project ------------------------------------------------------------------------------
def blocks_path(project, slug):
    return os.path.join(MP.mode_folder(project, slug), BLOCKS_FILE)


def is_blocks(project, slug):
    return bool(project and slug) and os.path.isfile(blocks_path(project, slug))


def load(project, slug):
    """The mode's program, as saved. Raises :class:`BlocksError` for a file that is not one."""
    try:
        with open(blocks_path(project, slug), "r", encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise BlocksError("its %s is not JSON: %s" % (BLOCKS_FILE, e)) from None
    if not isinstance(data, dict):
        raise BlocksError("its %s holds no program" % BLOCKS_FILE)
    if int(data.get("format", 1) or 1) > FORMAT:
        raise BlocksError("these blocks were saved by a newer version of the app")
    return normalize(data)


def normalize(data):
    """``data`` with every top-level key present and of its kind (what the page and the
    translator can rely on). Blocks inside are left as they are; :func:`problems` names any
    that do not make sense."""
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    out["format"] = FORMAT
    out["name"] = str(out.get("name") or "").strip()[:40]
    try:
        out["seconds"] = max(0, min(SECONDS_MAX, int(out.get("seconds", 30))))
    except (TypeError, ValueError):
        out["seconds"] = 30
    out["ends_on_drain"] = bool(out.get("ends_on_drain", True))
    out["screen"] = bool(out.get("screen", False))
    out["screen_style"] = out.get("screen_style") if out.get("screen_style") in SCREEN_STYLES else "panel"   # PAD-521
    if out.get("game_modes") not in GAME_MODES:          # PAD-373; PAD-398: our modes run alone by default
        out["game_modes"] = "block"
    keep = out.get("keep_rules") if isinstance(out.get("keep_rules"), list) else []      # PAD-398
    out["keep_rules"] = [r.strip() for r in keep if isinstance(r, str) and r.strip() and "," not in r][:32]
    ids = out.get("block_modes") if isinstance(out.get("block_modes"), list) else []
    out["block_modes"] = sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)
                                 and 0 <= i <= BLOCK_ID_MAX})
    out["vars"] = [v for v in (out.get("vars") or []) if isinstance(v, dict)]
    out["timers"] = [t for t in (out.get("timers") or []) if isinstance(t, dict)]
    out["wait_multiball"] = bool(out.get("wait_multiball", False))
    try:
        out["priority"] = max(0, min(PRIORITY_MAX, int(out.get("priority", 0) or 0)))
    except (TypeError, ValueError):
        out["priority"] = 0
    out["clips"] = [c for c in (out.get("clips") or []) if isinstance(c, dict)]
    out["sounds"] = [c for c in (out.get("sounds") or []) if isinstance(c, dict)]
    out["music"] = str(out.get("music") or "")
    out["beds"] = [c for c in (out.get("beds") or []) if isinstance(c, dict)]   # PAD-658
    out["scripts"] = [s for s in (out.get("scripts") or []) if isinstance(s, dict)]
    out["shows"] = _norm_shows(out.get("shows"))         # PAD-646
    out["hud"] = _norm_hud(out.get("hud"))
    out["bar"] = _norm_bar(out.get("bar"))
    out["info"] = _norm_info(out.get("info"))
    for s in out["scripts"]:
        for b in _walk(s.get("do")):
            # PAD-372: Add seconds takes a value; one saved before held a plain number
            secs = b.get("seconds")
            if b.get("op") == "add_time" and isinstance(secs, (int, float)) and not isinstance(secs, bool):
                b["seconds"] = {"k": "num", "v": b["seconds"]}
    return out


def _norm_shows(shows):
    """PAD-646: the mode's own light shows, each ``{name, steps, repeat}`` and nothing else: a show that is not a
    dict, or has no list of steps, is dropped; what is wrong inside one :func:`problems` names."""
    out = []
    for s in (shows if isinstance(shows, list) else [])[:SHOWS_MAX]:
        if not isinstance(s, dict) or not isinstance(s.get("steps"), list):
            continue
        try:
            repeat = max(0, min(REPEAT_MAX, int(s.get("repeat", 1))))
        except (TypeError, ValueError):
            repeat = 1
        out.append({"name": str(s.get("name") or "").strip()[:24],
                    "steps": [st for st in s["steps"] if isinstance(st, dict)], "repeat": repeat})
    return out


def show_named(program, name):
    """PAD-646: the mode's own show called ``name`` (as typed, else by its letters alone), or None."""
    want = str(name or "").strip()
    shows = program.get("shows") or []
    for s in shows:
        if s.get("name") == want:
            return s
    for s in shows:
        if str(s.get("name") or "").lower() == want.lower():
            return s
    return None


def show_blocks(program):
    """PAD-646: every Light show block in the program with the script it is in: ``[(script index, block)]``."""
    out = []
    for i, s in enumerate(program.get("scripts") or []):
        for b in _walk(s.get("do") or []):
            if b.get("op") == "show":
                out.append((i, b))
    return out


BAR_COLOR = "#00c040"            # PAD-521: the status bar's colour unless one is picked
#: PAD-521: its own screen - the panel with its name, or its words alone over the game's video, as the game's own
SCREEN_STYLES = {"panel": "a panel", "words": "words over the video"}
WORDS_NAME_MS, WORDS_SHOW_MS = 4000, 3000   # words alone: its name at the start, a Words block's line, then gone


def _norm_bar(b):
    """PAD-521: the game's own status bar - off unless ticked, in a colour of its own."""
    b = b if isinstance(b, dict) else {}
    return {"on": bool(b.get("on", False)),
            "color": b.get("color") if COLOR_RE.match(str(b.get("color") or "")) else BAR_COLOR}


INFO_TEXT_MAX = 40               # PAD-547: the info line's words; its value follows them


def _norm_info(i):
    """PAD-547: the info line under its name - off unless ticked; its words (capitals, as the game letters them) and the
    value it follows (None = words alone; problems names a bad one)."""
    i = i if isinstance(i, dict) else {}
    return {"on": bool(i.get("on", False)), "text": str(i.get("text") or "").strip()[:INFO_TEXT_MAX],
            "value": i.get("value") if isinstance(i.get("value"), dict) else None}


def info_line_c(text, with_value):
    """PAD-547: the printf the info line is made with: "SUPER JACKPOT = %s" (the value with commas), the words alone, or
    the value alone - as the game's own: "SUPER JACKPOT = %,02llu"."""
    if not with_value:
        return text
    return (text + " = %s") if text else "%s"


def _norm_hud(h):
    """The HUD's settings with every key there: off, three empty counters, a timer badge and no
    gauge unless said. A value a counter or the gauge follows is kept as it is (problems names a
    bad one)."""
    h = h if isinstance(h, dict) else {}
    text = lambda v, n: str(v or "").strip()[:n]                     # noqa: E731
    value = lambda v: v if isinstance(v, dict) else None             # noqa: E731
    given = list(h.get("counters") or [])[:3]
    counters = []
    for i in range(3):
        c = given[i] if i < len(given) and isinstance(given[i], dict) else {}
        counters.append({"label": text(c.get("label"), COUNTER_MAX), "sub": text(c.get("sub"), COUNTER_MAX),
                         "value": value(c.get("value"))})
    t = h.get("timer") if isinstance(h.get("timer"), dict) else {}
    g = h.get("gauge") if isinstance(h.get("gauge"), dict) else {}
    kind = g.get("kind") if g.get("kind") in GAUGE_KINDS else GAUGE_KINDS[0]
    bar = kind == "bar"
    try:
        count = max(1, min(BAR_MAX if bar else GAUGE_MAX, int(g.get("count", 20 if bar else 3))))
    except (TypeError, ValueError):
        count = 20 if bar else 3
    words = [text(w, COUNTER_MAX) for w in (g.get("words") if isinstance(g.get("words"), list) else [])][:2]
    return {"on": bool(h.get("on", False)), "line": text(h.get("line"), HUD_TEXT_MAX),
            "counters": counters,
            "timer": {"on": bool(t.get("on", True)), "label": text(t.get("label"), BADGE_MAX),
                      "icon": t.get("icon") if t.get("icon") in HUD_ICONS else HUD_ICONS[0]},
            "gauge": {"on": bool(g.get("on", False)), "label": text(g.get("label"), COUNTER_MAX),
                      "kind": kind,
                      "count": count,
                      "color": g.get("color") if COLOR_RE.match(str(g.get("color") or "")) else "#ff7800",
                      "value": value(g.get("value")),
                      # PAD-658: shown while the mode is not running too - a meter toward its start (David: "it
                      # should always be shown (whenever the HUD is shown)")
                      "meter": bool(g.get("meter", False)),
                      # a bar's two lines of words beside it (the stock meter's GODZILLA / POWERUP), the word its
                      # label says when full (else 100%), its icon
                      "words": [w for w in words if w], "full": text(g.get("full"), COUNTER_MAX),
                      "icon": g.get("icon") if g.get("icon") in HUD_ICONS else "rage"}}


def hud_spec(program, slug=""):
    """The ``hud`` of the mode's assets.json: what the card build draws (:func:`.mode_hud.hud_group`),
    or {} with the HUD off. A counter with no label is left empty; the badge says the mode's name
    when it has no label of its own."""
    program = normalize(program)
    h = program["hud"]
    if not h["on"]:
        return {}
    title = program["name"] or slug.upper()
    counters = [[c["label"], "0", c["sub"] or " "] if c["label"] else [] for c in h["counters"]]
    while counters and not counters[-1]:
        counters.pop()
    out = {"title": title, "line": h["line"] or " ", "counters": counters}
    if h["timer"]["on"]:
        out["timer"] = {"label": h["timer"]["label"] or title[:BADGE_MAX], "icon": h["timer"]["icon"]}
    if h["gauge"]["on"] and h["gauge"]["kind"] == "bar":        # PAD-658: the corner meter, in the stock's fire
        gg = h["gauge"]
        out["gauge"] = {"label": " ", "kind": "bar", "count": gg["count"], "icon": gg["icon"],
                        "words": gg["words"] or [gg["label"] or title[:COUNTER_MAX]]}
    elif h["gauge"]["on"]:
        rgb = int(h["gauge"]["color"][1:], 16)
        out["gauge"] = {"label": h["gauge"]["label"] or " ", "kind": h["gauge"]["kind"],
                        "count": h["gauge"]["count"],
                        "colours": [[rgb >> 16 & 255, rgb >> 8 & 255, rgb & 255]]}
    return out


def save(project, slug, program):
    """Write the program and the C it makes, the C first so a mode is never left with blocks
    that disagree with its C. Returns the C file's path."""
    program = normalize(program)
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    src = os.path.join(folder, slug + ".c")
    if program["hud"]["on"]:
        _copy_kit(folder)
    _write(src, to_c(program, slug))
    text = json.dumps(program, indent=2) + "\n"
    _write(blocks_path(project, slug), text)
    _sync_assets(project, slug, program)
    return src


def refresh(project):
    """Every blocks mode's C brought up to what its blocks make NOW, before a build compiles it: the C is written
    only when the blocks are saved, so a mode saved by an older app kept that app's translation (PAD-457: the claim
    of the game's mini-wizards a mode hands out). Only a C that differs is written; the blocks are not touched, and
    one that cannot be read is left for the build to report. Returns the slugs written."""
    from . import code_modes as CM
    out = []
    for slug in CM.code_slugs(project) if project else []:
        if not is_blocks(project, slug):
            continue
        try:
            program = load(project, slug)
            text = to_c(program, slug)
        except Exception:                               # noqa: BLE001 - never a build broken by this
            continue
        folder = MP.mode_folder(project, slug)
        src = os.path.join(folder, slug + ".c")
        if program["hud"]["on"]:
            _copy_kit(folder)                           # PAD-680: a fix in the kit alone reaches the mode too
        try:
            with open(src, "r", encoding="utf-8") as f:
                if f.read() == text:
                    continue
        except OSError:
            pass
        _write(src, text)
        out.append(slug)
    return out


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _copy_kit(folder):
    """The examples' kit beside the C (its HUD is the kit's): the SDK's copy at every save, so a
    blocks mode always builds against the kit of the app that saved it."""
    from . import code_modes as CM
    with open(os.path.join(CM.examples_dir(), KIT_FILE), "r", encoding="utf-8") as f:
        text = f.read()
    dst = os.path.join(folder, KIT_FILE)
    try:
        with open(dst, "r", encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    _write(dst, text)


def _sync_assets(project, slug, program):
    """The mode's assets.json says its name, its clock and whether it has a screen of its own
    (the build makes the screen: a panel with its name, and a line of words the blocks write),
    and (PAD-374) its own clips, sounds and music, so Write carries them as a code mode's."""
    from . import code_modes as CM
    try:
        spec = CM.load(project, slug)
    except (OSError, ValueError):
        spec = CM.CodeAssets(screen=False)
    hud = hud_spec(program, slug)
    clips, calls = media_assets(program)
    beds = {c["name"]: c["file"] for c in program.get("beds") or []
            if MEDIA_RE.match(str(c.get("name") or "")) and c.get("file")}          # PAD-658
    changed = (spec.name != (program["name"] or slug.upper()) or bool(spec.screen) != program["screen"]
               or dict(getattr(spec, "beds", None) or {}) != beds
               or spec.seconds != max(1, program["seconds"] or 60)
               or (spec.clips or {}) != clips or (spec.calls or {}) != calls
               or (spec.music or "") != program["music"] or dict(spec.hud or {}) != hud
               or (getattr(spec, "screen_style", "") or "panel") != program["screen_style"]
               or bool(getattr(spec, "info_line", False)) != program["info"]["on"])
    if changed or not os.path.isfile(os.path.join(MP.mode_folder(project, slug), CM.ASSETS_FILE)):
        spec.name = program["name"] or slug.upper()
        spec.screen = program["screen"]
        spec.seconds = max(1, program["seconds"] or 60)
        spec.hud = hud
        spec.clips = clips
        spec.calls = calls
        spec.music = program["music"]
        spec.beds = beds
        spec.screen_style = "words" if program["screen_style"] == "words" else ""
        spec.info_line = program["info"]["on"]          # PAD-547: the build adds PadMode_<slug>_Info
        CM.save(project, slug, spec)


def media_assets(program):
    """``(clips, calls)`` as assets.json holds them: ``{name: file}`` and ``{name: {"wav",
    "priority"}}``, every well-named entry with a file (the first of a name wins)."""
    clips, calls = {}, {}
    for c in program.get("clips") or []:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if MEDIA_RE.match(name) and f and name not in clips and len(clips) < MAX_CLIPS:
            clips[name] = f
    for c in program.get("sounds") or []:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if MEDIA_RE.match(name) and f and name not in calls and len(calls) < MAX_SOUNDS:
            calls[name] = {"wav": f, "priority": _priority(c.get("priority"))}
    return clips, calls


def _priority(v):
    try:
        p = int(v)
    except (TypeError, ValueError):
        return 4
    return p if 1 <= p <= 7 else 4


def media_name(stem, taken=()):
    """A clip's or sound's name from its file's name: lower-case letters, digits and _, starting
    with a letter, 15 at most, and not one of ``taken``."""
    base = re.sub(r"[^a-z0-9_]+", "_", str(stem or "").lower()).strip("_")
    if not base or not base[0].isalpha():
        base = "s_" + base if base else "sound"
    base = base[:15].rstrip("_") or "sound"
    taken = {str(t).lower() for t in taken or ()}
    name, n = base, 2
    while name in taken:
        tail = "_%d" % n
        name = base[:15 - len(tail)] + tail
        n += 1
    return name


def regenerate(project, slug, name=None):
    """Write the C again from the saved blocks (after the folder moved to ``slug``, or took a
    new ``name``). Returns True when there were blocks to write it from."""
    if not is_blocks(project, slug):
        return False
    program = load(project, slug)
    if name is not None:
        program["name"] = str(name)
    save(project, slug, program)
    return True


def detach(project, slug):
    """Edit as C: the mode keeps its C file (the one its blocks made) and loses its blocks, so
    it is an ordinary code mode from now on. The blocks are kept beside it as
    ``blocks.json.bak`` in case the person wants them back by hand."""
    path = blocks_path(project, slug)
    if os.path.isfile(path):
        os.replace(path, path + ".bak")
    return MP.mode_folder(project, slug)


# ---- a new mode --------------------------------------------------------------------------------
def starter(name, shots=()):
    """A new blocks mode's program: a whole, working mode to change, on the card's own shots.
    The first two shots are its start shot and a jackpot; with no shots known the shot boxes
    are empty for the person to fill."""
    names = [n for n in shots or () if n]
    start = names[0] if names else ""
    jack = names[1] if len(names) > 1 else start
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    return normalize({
        "name": name, "seconds": 30, "ends_on_drain": True, "screen": False,
        "wait_multiball": True,         # as the examples: a multiball running, the next shot starts it
        "vars": [{"name": "combo", "reset": "mode"}],
        "scripts": [
            {"hat": {"kind": "shot", "shot": start, "when": "idle"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": start},
                                      "b": num(3)},
                 "then": [{"op": "start_mode"}], "else": None}]},
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "set", "var": "combo", "value": num(1)},
                {"op": "light_shot", "shot": jack, "color": "#ffd000", "pattern": "blink"}]},
            {"hat": {"kind": "any_shot", "when": "running"}, "do": [
                {"op": "score", "points": {"k": "op", "op": "*", "a": num(500000),
                                           "b": {"k": "var", "name": "combo"}}},
                {"op": "change", "var": "combo", "by": num(1)}]},
            {"hat": {"kind": "shot", "shot": jack, "when": "running"}, "do": [
                {"op": "score", "points": num(5000000)},
                {"op": "add_time", "seconds": num(5)}]},
            {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [
                {"op": "callout", "role": "ten_seconds"}]},
            {"hat": {"kind": "mode_end"}, "do": [
                {"op": "log", "text": "the mode ended"}]},
        ]})


def new_blocks_mode(project, name, shots=(), example=None):
    """A new blocks mode in ``modes/<slug>/``: its program (:func:`starter` on ``shots``), the C
    it makes and a default assets.json. Returns ``(slug, path of the C)``. Never overwrites a
    folder that exists."""
    from . import mode_tryit as MT
    if not project or not os.path.isdir(project):
        raise MT.TryItError(MP.NO_PROJECT_HELP)
    name = MT._c_title(str(name or "").strip()[:40], "mode") or "NEW MODE"
    slug = MT._free_slug(project, MP.slugify(name))
    if example == "ramps" and not shots:
        shots = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    os.makedirs(MP.mode_folder(project, slug))
    path = save(project, slug, starter(name, shots))
    return slug, path


#: PAD-675: the one blocks example New mode offers, on every game: the starter above on the shots the form mode of
#: the same name uses (the port's example start shot, then a ramp as its jackpot)
BASIC_EXAMPLE = "TARGET RUSH"
BASIC_ABOUT = ("A small, whole mode to start from: three hits on one shot start it, every shot scores more than the "
               "last, a lit jackpot shot adds time, and a callout at ten seconds left.")


def card_checks(p):
    """The keyword arguments :func:`problems` takes for title profile ``p`` (the card's shots, events, mechanisms,
    shaker, the game's own light shows, mini-wizards, inserts, building, challenges and coil limits), as the
    Modes tab checks a program."""
    if p is None:
        return {}
    return {
        "shots": [n for n, _m in p.shots],
        "events": list(p.events or ()),
        "mechs": ({"magnet": "magnet"} if p.can("magnet") else {}) | (dict(p.held_coils) if p.can("coils") else {}),
        "scoop": p.can("scoop"),
        "shield": getattr(p, "shield_rule", "") if p.can("shield") else False,
        "game_shows": [n for n, _k, _s in getattr(p, "game_shows", ())],
        "shaker": {"shakes": [n for n, _l in p.shakes], "max": list(p.shake_max_ms)} if p.can("shaker") else False,
        "game_wizards": [n for n, _f in getattr(p, "game_wizards", ())] if p.can("wizard") else [],
        "inserts": list(getattr(p, "inserts", ()) or ()),
        "building": getattr(p, "building_rule", "") if p.can("building") else False,
        "challenges": list(getattr(p, "challenges", ()) or ()) + ([CHALLENGE_NEW] if getattr(p, "challenge_menu", 0)
                                                                   else []),
        "hold_caps": {n: ms for n, ms in getattr(p, "coil_caps", ()) or ()},
    }


# ---- what is wrong with a program ----------------------------------------------------------------
def problems(program, shots=None, events=None, folder=None, mechs=None, scoop=None, shield=None, game_shows=None, shaker=None,
             game_wizards=None, inserts=None, building=None, modes=None, challenges=None, hold_caps=None):
    """Every reason the program cannot be built, as sentences (empty = it can). ``shots`` and
    ``events``, when given, are the card's: a block naming a shot or event the card does not
    have is named here; ``folder``, when given, is the mode's, where its own clips and sounds
    must be. ``mechs`` (``{name: label}``, the mechanisms a mode may hold on the card's game)
    and ``scoop`` (whether it may hold a ball in the scoop), when given, are the card's too
    (PAD-395); so is ``shield`` (PAD-392): False where the game has no shield platform a mode may turn,
    else the name of its own shield feature ("" when the port names none); so is ``game_shows`` (PAD-418): the
    names of the game's own light shows its port names ([] = none on this game); so is ``shaker`` (PAD-414): False where the game has no
    shaker a mode may shake, else ``{"shakes": names of the game's own, "max": its longest per strength}``; so is
    ``game_wizards`` (PAD-436): the names of the game's own mini-wizards ([] = none a mode may hand over on this game);
    so is ``inserts`` (PAD-503): the names of the inserts a mode may light ([] = none on this game: a mode lit at a
    shot is lit without them); so is ``modes`` (PAD-600): the slugs of the project's blocks modes another mode's
    light may be put out in; so is ``challenges`` (PAD-615): the names of the game's challenges a mode may take the
    place of ([] = none on this game).
    The C is written anyway (a missing shot is 0 to the game, which never matches),
    so a half-made program always saves."""
    program = normalize(program)
    out = []
    names = [str(v.get("name") or "") for v in program["vars"]]
    seen = set()
    for v, n in zip(program["vars"], names):
        if not VAR_RE.match(n):
            out.append("A variable's name %r is not one: start with a letter, then letters, "
                       "digits, spaces or _ (24 at most)." % n)
        elif n.lower() in seen or (v.get("shared") and shared_ident(n) in seen):
            out.append("Two variables are called %s." % n)
        seen.add(n.lower())
        if v.get("shared"):
            seen.add(shared_ident(n))       # "maser won" and "maser_won" are one shared value
            if v.get("reset", "ball") not in SHARED_RESETS:
                out.append("%s is shared with the other modes, so it resets each ball or each game, "
                           "not each time this mode starts." % n)
    if len(names) > MAX_VARS:
        out.append("%d variables: %d at most." % (len(names), MAX_VARS))
    timers = [str(t.get("name") or "") for t in program["timers"]]
    tseen = set()
    for n in timers:
        if not VAR_RE.match(n):
            out.append("A timer's name %r is not one: start with a letter, then letters, "
                       "digits, spaces or _ (24 at most)." % n)
        elif n.lower() in tseen:
            out.append("Two timers are called %s." % n)
        tseen.add(n.lower())
    if len(timers) > MAX_TIMERS:
        out.append("%d timers: %d at most." % (len(timers), MAX_TIMERS))
    if len(program["scripts"]) > MAX_SCRIPTS:
        out.append("%d scripts: %d at most." % (len(program["scripts"]), MAX_SCRIPTS))
    clips = _check_media(program["clips"], "clip", MAX_CLIPS, folder, out)
    sounds = _check_media(program["sounds"], "sound", MAX_SOUNDS, folder, out)
    if program["music"] and folder is not None and not os.path.isfile(os.path.join(folder, program["music"])):
        out.append("Its music %s is not in the mode's folder: pick it again." % program["music"])
    beds = _check_media(program["beds"], "music bed", MAX_BEDS, folder, out)        # PAD-658
    if beds and not program["music"]:
        out.append("More music beds need its own music first: pick its music.")
    ctx = {"vars": set(n.lower() for n in names), "timers": tseen,
           "shots": set(shots) if shots is not None else None,
           "events": set(events) if events is not None else None, "count": 0, "out": out,
           "seconds": program["seconds"], "clips": clips, "sounds": sounds, "beds": beds,
           "mechs": dict(mechs) if mechs is not None else None, "scoop": scoop, "shield": shield,
           "hold_caps": dict(hold_caps or {}),        # PAD-621: {name: ms} a mechanism held longer than 5 s
           "building": building,
           "game_shows": list(game_shows) if game_shows is not None else None,
           "shaker": shaker, "game_wizards": list(game_wizards) if game_wizards is not None else None,
           "inserts": list(inserts) if inserts is not None else None,
           "modes": set(modes) if modes is not None else None,
           "challenges": list(challenges) if challenges is not None else None, "picked": set(),
           "program": program}                        # PAD-646: a Light show block names one of its shows
    _check_shows(program, ctx)                        # PAD-646
    hud = program["hud"]
    if hud["on"]:
        for k, c in enumerate(hud["counters"]):
            if c["value"] is not None:
                _check_num(c["value"], "The HUD's counter %d" % (k + 1), ctx)
        if hud["gauge"]["on"] and hud["gauge"]["value"] is not None:
            _check_num(hud["gauge"]["value"], "The HUD's gauge", ctx)
    info = program["info"]
    if info["on"] and info["value"] is not None:              # PAD-547
        _check_num(info["value"], "The info line", ctx)
    elif info["on"] and not info["text"]:
        out.append("The info line has no words and no value: give it one or untick it.")
    for i, s in enumerate(program["scripts"]):
        _check_hat(s.get("hat") or {}, i + 1, ctx)
        _check_stack(s.get("do") or [], 1, "Script %d" % (i + 1), ctx)
    if ctx["count"] > MAX_BLOCKS:
        out.append("%d blocks: %d at most." % (ctx["count"], MAX_BLOCKS))
    turns = [b for s in program["scripts"] for b in _walk(s.get("do") or [])
             if b.get("op") == "shield" and b.get("where") in ("toward", "away")]
    if turns and shield not in (None, False):          # PAD-392: the game's own shield feature turns them back
        feature = shield or "shield"
        if program.get("game_modes", "block") != "block":
            out.append("The shield targets stay turned only while the game's modes cannot start: otherwise the "
                       "game's own %s feature turns them back." % feature)
        elif shield and shield in (program.get("keep_rules") or []):
            out.append("The shield targets stay turned only while %s does not keep counting: it turns them "
                       "back." % shield)
    moves = [b for s in program["scripts"] for b in _walk(s.get("do") or []) if b.get("op") == "building"]
    if moves and building not in (None, False):        # PAD-589: never while the game's building locks count
        if program.get("game_modes", "block") != "block":
            out.append("The building moves only while the game's modes cannot start: otherwise the game's own %s "
                       "may want it." % (building or "building locks"))
        elif building and building in (program.get("keep_rules") or []):
            out.append("The building moves only while %s does not keep counting." % building)
    return _unique(out)


def _check_media(items, what, most, folder, out):
    """The names of the mode's own clips (or sounds), saying what is wrong with the list."""
    names = set()
    if len(items) > most:
        out.append("%d %ss of its own: %d at most." % (len(items), what, most))
    for c in items:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if not MEDIA_RE.match(name):
            out.append("A %s's name %r is not one: start with a lower-case letter, then lower-case "
                       "letters, digits or _ (15 at most)." % (what, name))
        elif name in names:
            out.append("Two %ss are called %s." % (what, name))
        names.add(name)
        if not f:
            out.append("The %s %s has no file: pick one." % (what, name))
        elif folder is not None and not os.path.isfile(os.path.join(folder, f)):
            out.append("The %s %s's file %s is not in the mode's folder: pick it again." % (what, name, f))
        if what == "sound" and not _int_ok(c.get("priority", 4), 1, 7):
            out.append("The sound %s's priority is 1 to 7." % name)
    return names


def notes(program):
    """What is worth knowing but does not stop a build: nothing starts the mode, a timer block
    with no clock, words with no screen, a clip behind the HUD with no loop to play it in."""
    program = normalize(program)
    ops = set()
    kinds = set()
    wheres = set()
    for s in program["scripts"]:
        kinds.add((s.get("hat") or {}).get("kind"))
        for b in _walk(s.get("do") or []):
            ops.add(b.get("op"))
            if b.get("op") == "clip":
                wheres.add(b.get("where"))
            if b.get("op") == "light_shot" and b.get("pattern") == "hurry":
                ops.add("hurry")
    out = []
    if not {"start_mode", "light_mode"} & ops:
        out.append("No block starts the mode yet: put Start the mode in a script (Start mode now "
                   "starts it for a test either way).")
    if not program["seconds"] and "end_mode" not in ops and not program["ends_on_drain"]:
        out.append("Nothing ends this mode: it has no clock, the ball draining does not end it, "
                   "and no End the mode block.")
    if not program["seconds"] and ({"seconds_left"} & kinds or {"add_time", "set_time"} & ops):
        out.append("The mode has no clock, so seconds-left, add-time and set-the-clock blocks do nothing.")
    if not program["seconds"] and "hurry" in ops:
        out.append("The mode has no clock, so a shot blinking faster as time runs out blinks at "
                   "an even pace.")
    if "words" in ops and not program["screen"]:
        out.append("Show words needs the mode's own screen: tick Its own screen.")
    hud = program["hud"]
    if not hud["on"] and {"hud_text", "hud_counter", "hud_gauge"} & ops:
        out.append("The HUD blocks need the HUD: tick Its HUD.")
    if not hud["on"] and not program["screen"] and "hud_award" in ops:     # PAD-574: or on its own screen
        out.append("An Award shows on its HUD or its own screen: tick Its HUD or Its own screen.")
    if hud["on"]:
        named = set()
        for s in program["scripts"]:
            for b in _walk(s.get("do") or []):
                if b.get("op") == "hud_counter" and _int_ok(b.get("counter"), 1, 3):
                    named.add(int(b["counter"]))
        for k in sorted(named):
            if not hud["counters"][k - 1]["label"]:
                out.append("A block sets HUD counter %d, which has no label, so it is not shown: "
                           "give it one under Its HUD." % k)
        if "hud_gauge" in ops and not hud["gauge"]["on"]:
            out.append("A block fills the HUD's gauge, which is switched off: tick Gauge under Its HUD.")
        if hud["gauge"]["on"] and hud["gauge"]["meter"] and hud["gauge"]["value"] is None:
            out.append("The HUD's gauge shows while the mode is not running, and follows nothing: give it a value "
                       "to follow (lit to).")
        if hud["timer"]["on"] and not program["seconds"]:
            out.append("The HUD's timer badge counts the mode's clock, and it has none: it is not shown.")
    if any((s.get("hat") or {}).get("kind") == "challenge"
           and not any(b.get("op") == "start_mode" for b in _walk(s.get("do") or [])) for s in program["scripts"]):
        out.append("A When the player picks a challenge script with no Start the mode in it starts nothing: the "
                   "game's own challenge does not run either.")
    idle = [s for s in program["scripts"] if (s.get("hat") or {}).get("kind") in ("mode_end", "ball_end")
            or ((s.get("hat") or {}).get("kind") in ("shot", "any_shot", "switch", "event")
                and (s.get("hat") or {}).get("when") == "idle")]
    if any(b.get("op") in ("hold", "scoop_hold", "shield", "building") for s in idle for b in _walk(s.get("do") or [])):
        out.append("A mechanism is held only while the mode runs: a hold in When the mode ends, When the "
                   "ball drains or a script for while it is not running does nothing.")
    idle_show = [s for s in idle if (s.get("hat") or {}).get("kind") != "mode_end"]
    if any(b.get("op") == "game_show" for s in idle_show for b in _walk(s.get("do") or [])):   # PAD-418
        out.append("The game's light show plays only while the mode runs or as it ends: one in When the ball "
                   "drains (the game stops its shows then) or a script for while it is not running does nothing.")
    if "timer_done" in kinds and "timer_start" not in ops:
        out.append("No block starts a timer, so When a timer runs out never runs.")
    # PAD-646: a show of the mode's own that no block runs, and one that runs until the mode ends started as it ends
    run = {str(b.get("name") or "").lower() for _i, b in show_blocks(program) if b.get("show") == "mine"}
    for s in program["shows"]:
        if s["name"] and s["name"].lower() not in run:
            out.append("No block runs the light show %r yet: put Run the light show in a script (Light shows "
                       "names the rules that run each)." % s["name"])
    for i, b in show_blocks(program):
        s = show_named(program, b.get("name")) if b.get("show") == "mine" else None
        if s is not None and not s["repeat"] and (program["scripts"][i].get("hat") or {}).get("kind") == "mode_end":
            out.append("The light show %r runs over and over until the mode ends, and When the mode ends starts it "
                       "as it does: it plays once there." % s["name"])
    if "behind" in wheres and "loop" not in wheres:
        out.append("A clip behind the HUD, once, plays in the place of the mode's loop: start a "
                   "clip over and over behind the HUD first (When the mode starts is the place).")
    ends = [s for s in program["scripts"] if (s.get("hat") or {}).get("kind") == "mode_end"]
    if any(b.get("op") == "clip" and b.get("where") == "behind" for s in ends for b in _walk(s.get("do") or [])):
        out.append("A clip behind the HUD in When the mode ends plays full screen: the mode's loop ends with it, "   # PAD-658
                   "so there is nothing left to play behind. Its TOTAL shows after the clip.")
    return out


def _unique(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _walk(stack):
    for b in stack or []:
        if not isinstance(b, dict):
            continue
        yield b
        if b.get("op") == "if":
            yield from _walk(b.get("then"))
            yield from _walk(b.get("else"))


def _check_shot(shot, where, ctx):
    if not shot:
        ctx["out"].append("%s has no shot chosen." % where)
    elif ctx["shots"] is not None and shot not in ctx["shots"]:
        ctx["out"].append("%s names %s, a shot this card does not have." % (where, shot))


def _check_light(name, where, ctx):
    """PAD-598: a Light or Hand back block's one light of the game's own (an insert, a GI string, a flasher: the port's
    `lamp` lines), by name."""
    if not isinstance(name, str) or "," in name or len(name) > INSERT_MAX:
        ctx["out"].append("%s lights an insert that is not one." % where)
    elif ctx["inserts"] is not None and name not in ctx["inserts"]:
        ctx["out"].append("%s names the light %s, which this card's game does not have." % (where, name))


def _check_hat(hat, n, ctx):
    kind = hat.get("kind")
    where = "Script %d" % n
    if kind not in HATS:
        ctx["out"].append("%s starts with no When block." % where)
        return
    if kind in ("shot",):
        _check_shot(hat.get("shot"), where + "'s When", ctx)
    if kind in ("shot", "any_shot", "switch", "event") and hat.get("when", "any") not in WHEN:
        ctx["out"].append("%s's When has no while." % where)
    if kind == "event":
        ev = hat.get("event")
        if not ev:
            ctx["out"].append("%s's When has no event chosen." % where)
        elif ctx["events"] is not None and ev not in ctx["events"]:
            ctx["out"].append("%s waits for %s, which this card's game does not report."
                              % (where, MP.EVENT_LABELS.get(ev, ev)))
    if kind in ("every", "seconds_left"):
        if not _int_ok(hat.get("seconds"), 1, SECONDS_MAX):
            ctx["out"].append("%s's seconds must be 1 to %d." % (where, SECONDS_MAX))
    if kind == "timer_done":
        _check_timer(hat.get("timer"), where + "'s When", ctx)
    if kind == "challenge":                                                          # PAD-615
        name = hat.get("challenge")
        if ctx["challenges"] is not None and not ctx["challenges"]:
            ctx["out"].append("%s waits for a challenge to be picked, which a mode cannot take the place of on this "
                              "card's game." % where)
        elif not name:
            ctx["out"].append("%s's When has no challenge chosen." % where)
        elif ctx["challenges"] is not None and name not in ctx["challenges"]:
            ctx["out"].append("%s waits for the challenge %s, which this card's game does not have." % (where, name))
        elif name in ctx["picked"]:
            ctx["out"].append("%s waits for %s too: one script per challenge." % (where, name))
        elif str(hat.get("launch") or "clip") not in CHALLENGE_LAUNCH and not _int_ok(hat.get("launch"), 1, 60):
            ctx["out"].append("%s's ball launch must be when its start clip is over, by the player, or 1 to 60 "
                              "seconds after it starts." % where)                       # PAD-643
        else:
            ctx["picked"].add(name)


def _check_timer(name, where, ctx):
    if not name:
        ctx["out"].append("%s has no timer chosen." % where)
    elif str(name).lower() not in ctx["timers"]:
        ctx["out"].append("%s names a timer that is not there: make it under Timers." % where)


def _int_ok(v, lo, hi):
    try:
        return lo <= int(v) <= hi and float(v) == int(v)
    except (TypeError, ValueError):
        return False


def _check_stack(stack, depth, where, ctx):
    if depth > MAX_DEPTH:
        ctx["out"].append("Blocks in %s are nested more than %d deep." % (where, MAX_DEPTH))
        return
    if not isinstance(stack, list):
        ctx["out"].append("%s holds something that is not a list of blocks." % where)
        return
    for b in stack:
        ctx["count"] += 1
        if not isinstance(b, dict) or b.get("op") not in STATEMENTS:
            ctx["out"].append("%s holds a block this version does not know." % where)
            continue
        op = b["op"]
        if op == "score":
            _check_num(b.get("points"), where, ctx)
        elif op in ("set", "change"):
            if str(b.get("var") or "").lower() not in ctx["vars"]:
                ctx["out"].append("%s sets a variable that is not there: make it under Variables."
                                  % where)
            _check_num(b.get("value" if op == "set" else "by"), where, ctx)
        elif op == "if":
            _check_bool(b.get("cond"), where, ctx)
            _check_stack(b.get("then") or [], depth + 1, where, ctx)
            _check_stack(b.get("else") or [], depth + 1, where, ctx)
        elif op == "callout":
            role = b.get("role")
            if role not in CALLOUT_ROLES and not _int_ok(b.get("id"), 1, 65535):
                ctx["out"].append("%s has a callout with none chosen." % where)
        elif op == "words":
            if len(str(b.get("text") or "")) > TEXT_MAX:
                ctx["out"].append("%s shows more than %d letters of words." % (where, TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
        elif op in ("light_shot", "lights_off"):
            if op == "lights_off" and b.get("shot") == "*":
                continue
            if b.get("insert"):                         # PAD-598: one of the game's lights by name, not a shot's
                _check_light(b.get("insert"), where, ctx)
            else:
                _check_shot(b.get("shot"), where + "'s lights", ctx)
            if op == "light_shot":
                if b.get("pattern") != "off" and not COLOR_RE.match(str(b.get("color") or "")):
                    ctx["out"].append("%s lights a shot in no color." % where)
                if b.get("pattern") not in PATTERNS:
                    ctx["out"].append("%s lights a shot in no pattern." % where)
                rate = b.get("rate")
                if rate is not None and b.get("pattern") not in ("solid", "hurry", "off"):
                    _check_num(rate, where, ctx)
                    if (isinstance(rate, dict) and rate.get("k") == "num"
                            and _int_ok(rate.get("v"), -NUMBER_MAX, NUMBER_MAX)
                            and not _int_ok(rate.get("v"), RATE_MIN, RATE_MAX)):
                        ctx["out"].append("%s lights a shot at a pace of %d to %d ms." % (where, RATE_MIN, RATE_MAX))
        elif op == "show":
            _check_show(b, where, ctx)
        elif op in ("add_time", "set_time"):
            secs = b.get("seconds")
            _check_num(secs, where, ctx)
            lo = -SECONDS_MAX if op == "add_time" else 0
            if (isinstance(secs, dict) and secs.get("k") == "num"
                    and _int_ok(secs.get("v"), -NUMBER_MAX, NUMBER_MAX)
                    and not _int_ok(secs.get("v"), lo, SECONDS_MAX)):
                ctx["out"].append("%s %s: %d to %d seconds." % (
                    where, "adds a time" if op == "add_time" else "sets the clock", lo, SECONDS_MAX))
        elif op == "multiball":
            if not _int_ok(b.get("balls"), 2, 6):
                ctx["out"].append("%s asks for a multiball of 2 to 6 balls." % where)
            if not _int_ok(b.get("save", 0), 0, 60):
                ctx["out"].append("%s has a ball save of 0 to 60 seconds." % where)
        elif op == "log":
            if len(str(b.get("text") or "")) > TEXT_MAX:
                ctx["out"].append("%s logs more than %d letters." % (where, TEXT_MAX))
        elif op == "hud_text":
            if b.get("which") not in ("title", "line"):
                ctx["out"].append("%s writes the HUD's title or line: choose which." % where)
            if len(str(b.get("text") or "")) > HUD_TEXT_MAX:
                ctx["out"].append("%s puts more than %d letters on the HUD." % (where, HUD_TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
        elif op == "hud_counter":
            if not _int_ok(b.get("counter"), 1, 3):
                ctx["out"].append("%s sets a HUD counter: 1, 2 or 3." % where)
            _check_num(b.get("value"), where, ctx)
            if len(str(b.get("sub") or "")) > COUNTER_MAX or len(str(b.get("label") or "")) > COUNTER_MAX:
                ctx["out"].append("%s has a counter's words of more than %d letters." % (where, COUNTER_MAX))
        elif op == "hud_gauge":
            _check_num(b.get("value"), where, ctx)
        elif op == "hud_award":
            for key in ("text", "sub"):
                if len(str(b.get(key) or "")) > HUD_TEXT_MAX:
                    ctx["out"].append("%s puts more than %d letters on the HUD." % (where, HUD_TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
            if not _int_ok(b.get("seconds"), 1, AWARD_SECONDS_MAX):
                ctx["out"].append("%s shows an award for 1 to %d seconds." % (where, AWARD_SECONDS_MAX))
        elif op in ("timer_start", "timer_stop"):
            _check_timer(b.get("timer"), where + "'s timer", ctx)
            if op == "timer_start":
                ms = b.get("ms")
                _check_num(ms, where, ctx)
                if (isinstance(ms, dict) and ms.get("k") == "num"
                        and _int_ok(ms.get("v"), -NUMBER_MAX, NUMBER_MAX)
                        and not _int_ok(ms.get("v"), 1, TIMER_MAX_MS)):
                    ctx["out"].append("%s starts a timer: 1 to %d milliseconds." % (where, TIMER_MAX_MS))
        elif op == "clip":
            if not b.get("clip"):
                ctx["out"].append("%s plays a clip with none chosen." % where)
            elif b.get("clip") not in ctx["clips"]:
                ctx["out"].append("%s plays the clip %s, which the mode does not have: add it under "
                                  "Its own clips and sounds." % (where, b.get("clip")))
            if b.get("where") not in CLIP_WHERE:
                ctx["out"].append("%s plays a clip with no where." % where)
        elif op == "music":                                                          # PAD-658
            bed = b.get("bed") or ""
            if not ctx["program"].get("music"):
                ctx["out"].append("%s plays a music bed, and the mode has no music of its own: pick its music." % where)
            elif bed and bed not in ctx["beds"]:
                ctx["out"].append("%s plays the music bed %s, which the mode does not have: add it under Its own clips "
                                  "and sounds." % (where, bed))
        elif op == "sound":
            if not b.get("sound"):
                ctx["out"].append("%s plays a sound with none chosen." % where)
            elif b.get("sound") not in ctx["sounds"]:
                ctx["out"].append("%s plays the sound %s, which the mode does not have: add it under "
                                  "Its own clips and sounds." % (where, b.get("sound")))
            fb = b.get("fallback")
            if fb not in (None, "") and fb not in CALLOUT_ROLES and not _int_ok(fb, 1, 65535):
                ctx["out"].append("%s falls back on a callout that is not one." % where)
        elif op == "hold":
            what = b.get("what")
            if not what or not HOLD_RE.match(str(what)):
                ctx["out"].append("%s holds a mechanism with none chosen." % where)
            elif ctx["mechs"] is not None and what not in ctx["mechs"]:
                ctx["out"].append("%s holds the %s, which a mode cannot hold on this card's game."
                                  % (where, what))
            _check_ms(b.get("ms"), HOLD_MIN_MS, max(HOLD_MAX_MS, min(ctx["hold_caps"].get(what, 0), HOLD_LONGEST_MS)),
                      "%s holds it" % where, ctx)
            if b.get("clock", "") not in HOLD_CLOCK:                       # PAD-621
                ctx["out"].append("%s holds it: the clock runs or waits." % where)
        elif op == "scoop_hold":
            if b.get("which", "next") not in SCOOP_WHICH:
                ctx["out"].append("%s holds a ball in the scoop: the next one or every one." % where)
            if ctx["scoop"] is False:
                ctx["out"].append("%s holds a ball in the scoop, which a mode cannot do on this card's game."
                                  % where)
            _check_ms(b.get("ms"), SCOOP_MIN_MS, SCOOP_MAX_MS, "%s holds a ball" % where, ctx)
        elif op == "let_go":
            what = b.get("what")
            if what not in ("*", "scoop") and not (what and HOLD_RE.match(str(what))):
                ctx["out"].append("%s lets go of nothing chosen." % where)
        elif op == "shield":
            if b.get("where") not in SHIELD_WHERE:
                ctx["out"].append("%s turns the shield targets: toward the player, away, or where they are."
                                  % where)
            elif ctx["shield"] is False:
                ctx["out"].append("%s turns the shield targets, which a mode cannot do on this card's game."
                                  % where)
        elif op == "building":                                                       # PAD-589
            if str(b.get("floor")) not in BUILDING_FLOOR:
                ctx["out"].append("%s moves the building: to floor 1, 2 or 3, or back where the game keeps it."
                                  % where)
            elif ctx["building"] is False:
                ctx["out"].append("%s moves the building, which a mode cannot do on this card's game." % where)
        elif op in ("shake", "shake_game"):                                          # PAD-414
            shaker = ctx["shaker"]
            if shaker is False:
                ctx["out"].append("%s shakes the cabinet, which a mode cannot do on this card's game." % where)
            elif op == "shake":
                strength = SHAKE_STRENGTH.get(b.get("strength"))
                if strength is None:
                    ctx["out"].append("%s shakes the cabinet: hard, strong, medium or soft." % where)
                elif shaker and any((shaker.get("max") or ())) and not (shaker.get("max") or [0] * 4)[strength]:
                    # PAD-474: a strength this card's game never shakes at (a one-power shaker: hard only)
                    ctx["out"].append("%s shakes the cabinet with a %s shake, which this card's game does not use: %s."
                                      % (where, b.get("strength"), " or ".join(
                                          w for w, k in SHAKE_STRENGTH.items() if (shaker.get("max") or [0] * 4)[k])))
                else:
                    top = ((shaker or {}).get("max") or [0] * 4)[strength] or SHAKE_MAX_MS
                    _check_ms(b.get("ms"), SHAKE_MIN_MS, top, "%s shakes the cabinet with a %s shake for" % (
                        where, b.get("strength")), ctx)
            elif not b.get("shake"):
                ctx["out"].append("%s plays none of the game's shakes." % where)
            elif shaker and b.get("shake") not in (shaker.get("shakes") or ()):
                ctx["out"].append("%s plays the game's %s shake, which this card's game does not have."
                                  % (where, b.get("shake")))
        elif op == "game_show":                         # PAD-418: by the port's name for it
            name = b.get("name")
            if not name or not isinstance(name, str):
                ctx["out"].append("%s plays the game's light show with none chosen." % where)
            elif ctx["game_shows"] is not None and not ctx["game_shows"]:
                ctx["out"].append("%s plays a light show of the game's, which a mode cannot do on this card's "
                                  "game." % where)
            elif ctx["game_shows"] is not None and name not in ctx["game_shows"]:
                ctx["out"].append("%s plays the game's light show %s, which this card's game does not have."
                                  % (where, name))
        elif op == "game_wizard":                       # PAD-436: by the port's name for it
            name = b.get("name")
            if not name or not isinstance(name, str):
                ctx["out"].append("%s hands the player the game's mini-wizard with none chosen." % where)
            elif ctx["game_wizards"] is not None and not ctx["game_wizards"]:
                ctx["out"].append("%s hands the player a mini-wizard of the game's, which a mode cannot do on this "
                                  "card's game." % where)
            elif ctx["game_wizards"] is not None and name not in ctx["game_wizards"]:
                ctx["out"].append("%s hands the player the game's mini-wizard %s, which this card's game does not "
                                  "have." % (where, name))
            if b.get("how", "light") not in MP.WIZARD_HOW:
                ctx["out"].append("%s lights the game's mini-wizard or starts it." % where)
        elif op == "set_hits":                          # PAD-600: one qualified at a time
            _check_shot(b.get("shot"), where + "'s Set the hits of", ctx)
            _check_num(b.get("value"), where, ctx)
        elif op == "unlight_mode":                      # PAD-600: this mode's light, or another blocks mode's
            mode = b.get("mode") or ""
            if not isinstance(mode, str) or (mode and not SLUG_RE.match(mode)):
                ctx["out"].append("%s puts out the light of a mode that is not one." % where)
            elif mode and ctx["modes"] is not None and mode not in ctx["modes"]:
                ctx["out"].append("%s puts out the light of a mode that is not in this project (%s): pick it "
                                  "again." % (where, mode))
        elif op == "light_mode":                        # PAD-503: lit at a shot, as the game's mini-wizards are
            _check_shot(b.get("shot"), where + "'s Light the mode at", ctx)
            if not COLOR_RE.match(str(b.get("color") or "")):
                ctx["out"].append("%s lights the mode in no color." % where)
            if b.get("pattern") not in LIT_PATTERNS:
                ctx["out"].append("%s lights the mode in no pattern." % where)
            names = lit_inserts(b.get("insert"))
            if names is None:
                ctx["out"].append("%s lights an insert that is not one." % where)
            else:
                if len(names) > LIT_INSERTS_MAX:
                    ctx["out"].append("%s lights more than %d inserts." % (where, LIT_INSERTS_MAX))
                for insert in names:
                    if ctx["inserts"] and insert not in ctx["inserts"]:
                        ctx["out"].append("%s lights the insert %s, which this card's game does not have."
                                          % (where, insert))
            solid = b.get("solid") or ""                # PAD-521: one insert more, held solid (the film's)
            if not isinstance(solid, str) or "," in solid or len(solid) > INSERT_MAX:
                ctx["out"].append("%s holds an insert solid that is not one." % where)
            elif solid and ctx["inserts"] and solid not in ctx["inserts"]:
                ctx["out"].append("%s holds the insert %s solid, which this card's game does not have." % (where, solid))
            elif solid and not COLOR_RE.match(str(b.get("solid_color") or "#ffffff")):
                ctx["out"].append("%s holds an insert solid in no color." % where)


def lit_inserts(value):
    """PAD-521: the inserts a Light the mode at block names (its ``insert``: one name, or several separated by commas,
    as the runtime's pm_lamp_set takes them; "" = none), in order and each once; None when that is not a list of
    names."""
    if value is None:
        return []
    if not isinstance(value, str):
        return None
    out = []
    for n in value.split(","):
        n = n.strip()
        if not n:
            continue
        if len(n) > INSERT_MAX:
            return None
        if n not in out:
            out.append(n)
    return out


def _check_ms(ms, lo, hi, where, ctx):
    """A hold's time: any value, and a number typed in is in the runtime's range (it clamps the rest)."""
    _check_num(ms, where, ctx)
    if (isinstance(ms, dict) and ms.get("k") == "num" and _int_ok(ms.get("v"), -NUMBER_MAX, NUMBER_MAX)
            and not _int_ok(ms.get("v"), lo, hi)):
        ctx["out"].append("%s %d to %d ms." % (where, lo, hi))


def _check_steps(steps, what, ctx):
    """A show's steps (a block's own, or one of the mode's shows'): each a pattern over the inserts for some ms, in
    two colors, from a place, at a pace, with the GI set; PAD-646: blending in from the step before for some ms, and
    a point of its own when its place is "xy"."""
    if not isinstance(steps, list) or not steps:
        ctx["out"].append("%s has no steps." % what)
        return
    if len(steps) > SHOW_STEPS:
        ctx["out"].append("%s has %d steps: %d at most." % (what, len(steps), SHOW_STEPS))
    for n, st in enumerate(steps, 1):
        here = "%s, step %d," % (what, n)
        if not isinstance(st, dict) or st.get("fx") not in FX:
            ctx["out"].append("%s has no pattern." % here)
            continue
        if not _int_ok(st.get("ms"), STEP_MS_MIN, STEP_MS_MAX):
            ctx["out"].append("%s lasts %d to %d ms." % (here, STEP_MS_MIN, STEP_MS_MAX))
        if not (COLOR_RE.match(str(st.get("a") or "")) and COLOR_RE.match(str(st.get("b") or ""))):
            ctx["out"].append("%s has a color missing." % here)
        if st.get("at", "center") not in PLACES:
            ctx["out"].append("%s has no place." % here)
        elif st.get("at") == "xy" and not (_int_ok(st.get("x"), 0, XY_MAX) and _int_ok(st.get("y"), 0, XY_MAX)):
            ctx["out"].append("%s centers on a point of its own that is not on the picture." % here)
        if not _int_ok(st.get("rate", 0), 0, FX_RATE_MAX):
            ctx["out"].append("%s has a pace of 0 to %d ms." % (here, FX_RATE_MAX))
        if st.get("gi", "keep") not in GI:
            ctx["out"].append("%s says nothing of the lights between the inserts." % here)
        if not _int_ok(st.get("blend", 0), 0, STEP_MS_MAX):
            ctx["out"].append("%s blends in over 0 to %d ms." % (here, STEP_MS_MAX))


def _check_shows(program, ctx):
    """PAD-646: the mode's own shows: each named (its letters, digits, spaces, - _ ' !), no two alike, its steps
    as :func:`_check_steps` wants them."""
    seen = set()
    for n, s in enumerate(program["shows"], 1):
        name = s["name"]
        what = "The light show %s" % (("%r" % name) if name else "%d" % n)
        if not SHOW_NAME_RE.match(name):
            ctx["out"].append("%s's name is not one: letters, digits, spaces, - _ ' and ! (24 at most)." % what
                              if name else "Light show %d has no name." % n)
        elif name.lower() in seen:
            ctx["out"].append("Two of the mode's light shows are called %r: give one another name." % name)
        seen.add(name.lower())
        _check_steps(s["steps"], what, ctx)


def _check_show(b, where, ctx):
    show = b.get("show")
    if show in SHOWS:
        return
    if show == "mine":                      # PAD-646: one of the mode's own, by name
        if not b.get("name"):
            ctx["out"].append("%s runs a light show of the mode's with none chosen: make one under Light shows." % where)
        elif show_named(ctx["program"], b.get("name")) is None:
            ctx["out"].append("%s runs the light show %r, which the mode does not have: make it under Light shows."
                              % (where, b.get("name")))
        return
    if show != "own":
        ctx["out"].append("%s runs a light show with none chosen." % where)
        return
    if not isinstance(b.get("steps"), list) or not b["steps"]:
        ctx["out"].append("%s runs a light show of its own with no steps." % where)
        return
    _check_steps(b["steps"], "%s's light show" % where, ctx)


def show_steps(b, program=None):
    """The steps a Light show block runs: its ready-made show's, one of the mode's own (PAD-646, ``program``'s
    ``shows`` by the block's ``name``), or its own."""
    if b.get("show") in SHOWS:
        return SHOWS[b["show"]][1]
    if b.get("show") == "mine":
        s = show_named(program or {}, b.get("name"))
        steps = (s or {}).get("steps")
    else:
        steps = b.get("steps") if b.get("show") == "own" else None
    return [st for st in (steps or []) if isinstance(st, dict) and st.get("fx") in FX][:SHOW_STEPS]


def show_repeat(b, program=None):
    """PAD-646: how many times the block's show runs (0 = until the mode ends): a show of the mode's own says."""
    if b.get("show") == "mine":
        s = show_named(program or {}, b.get("name"))
        if s is not None:
            return int(s.get("repeat", 1))
    return 1


def show_choices():
    """What the Light show block's boxes and the Light shows editor offer: the ready-made shows (with their steps,
    so a show of the mode's can start from one), the patterns (and their families), the places, the GI's settings,
    and the editor's limits."""
    return {"shows": [{"key": k, "label": label, "steps": copy.deepcopy(steps)}
                      for k, (label, steps) in SHOWS.items()],
            "fx": [[k, words] for k, (_c, words) in FX.items()],
            "fx_groups": [[g, list(keys)] for g, keys in FX_GROUPS],
            "places": [[k, p[0]] for k, p in PLACES.items()],
            "place_xy": {k: [p[1], p[2]] for k, p in PLACES.items() if k != "xy"},
            "gi": [[k, words] for k, words in GI.items()],
            "limits": {"steps": SHOW_STEPS, "shows": SHOWS_MAX, "repeat": REPEAT_MAX, "ms": [STEP_MS_MIN, STEP_MS_MAX],
                       "rate": FX_RATE_MAX, "name": 24}}


def _check_num(e, where, ctx, depth=0):
    if depth > MAX_DEPTH:
        ctx["out"].append("A value in %s is nested too deep." % where)
        return
    if not isinstance(e, dict) or e.get("k") not in NUM_KINDS:
        ctx["out"].append("%s has an empty number slot." % where)
        return
    k = e["k"]
    if k == "num":
        if not _int_ok(e.get("v"), -NUMBER_MAX, NUMBER_MAX):
            ctx["out"].append("%s has a number that is not a whole number (%r)." % (where, e.get("v")))
    elif k == "var":
        if str(e.get("name") or "").lower() not in ctx["vars"]:
            ctx["out"].append("%s uses a variable that is not there: make it under Variables." % where)
    elif k == "hits":
        _check_shot(e.get("shot"), where + "'s hits", ctx)
    elif k == "timer_left":
        _check_timer(e.get("timer"), where + "'s time left", ctx)
    elif k == "op":
        if e.get("op") not in OPS:
            ctx["out"].append("%s has a sum with no + - x or /." % where)
        _check_num(e.get("a"), where, ctx, depth + 1)
        _check_num(e.get("b"), where, ctx, depth + 1)


def _check_bool(e, where, ctx, depth=0):
    if depth > MAX_DEPTH:
        ctx["out"].append("A condition in %s is nested too deep." % where)
        return
    if not isinstance(e, dict) or e.get("k") not in BOOL_KINDS:
        ctx["out"].append("%s has an If with no condition." % where)
        return
    k = e["k"]
    if k == "cmp":
        if e.get("op") not in CMPS:
            ctx["out"].append("%s compares with no < = or >." % where)
        _check_num(e.get("a"), where, ctx, depth + 1)
        _check_num(e.get("b"), where, ctx, depth + 1)
    elif k in ("and", "or"):
        _check_bool(e.get("a"), where, ctx, depth + 1)
        _check_bool(e.get("b"), where, ctx, depth + 1)
    elif k == "not":
        _check_bool(e.get("a"), where, ctx, depth + 1)


# ---- the words the list and the page show -----------------------------------------------------
def summary(program):
    """One line: how many scripts and blocks, and its clock."""
    program = normalize(program)
    n = sum(1 for s in program["scripts"] for _b in _walk(s.get("do") or []))
    clock = ("runs %d seconds" % program["seconds"]) if program["seconds"] else "no clock"
    return "%d script%s, %d block%s, %s" % (len(program["scripts"]),
                                            "" if len(program["scripts"]) == 1 else "s",
                                            n, "" if n == 1 else "s", clock)


# ---- the C -----------------------------------------------------------------------------------------
def _c_str(text):
    """``text`` as a C string literal: printable ASCII only, quotes and backslashes escaped, and
    nothing that could close a comment or start a trigraph."""
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or ""))
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("??", "?\\?")
    return '"%s"' % s


def _comment(text):
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or ""))
    return s.replace("*/", "* /").replace("/*", "/ *")


class _Gen:
    """The translator's tables: every shot, event and variable the program names gets one
    static of its own, looked up once in init."""

    def __init__(self, program, slug):
        self.p = program
        self.slug = slug
        self.shots = []                 # shot names, in first-use order
        self.lamps = []                 # PAD-598: the game's lights the blocks light by name, in first-use order
        self.events = []
        self.vars = {}                  # lower name -> index
        self.var_names = []
        self.shared = set()             # indices of the shared variables
        for v in program["vars"]:
            n = str(v.get("name") or "")
            if VAR_RE.match(n) and n.lower() not in self.vars:
                reset = v.get("reset") if v.get("reset") in RESETS else "ball"
                if v.get("shared"):
                    if reset not in SHARED_RESETS:
                        reset = "game"
                    self.shared.add(len(self.var_names))
                self.vars[n.lower()] = len(self.var_names)
                self.var_names.append((n, reset))
        self.timers = {}                # lower name -> index
        self.timer_names = []
        for t in program["timers"]:
            n = str(t.get("name") or "")
            if VAR_RE.match(n) and n.lower() not in self.timers:
                self.timers[n.lower()] = len(self.timer_names)
                self.timer_names.append(n)
        self.hits = []                  # shots whose hits this ball the program reads
        self.shows = []                 # the shows the blocks run, in order: SHOW_<n> ({key, steps, name, repeat};
                                        # PAD-646: one of the mode's own, by its key, once however many blocks run it)
        self.holds = []                 # PAD-395: the mechanisms its blocks hold or let go, by the port's name
        self.mech = False               # PAD-395: a block holds or lets go of something (the helpers go in)
        self.game_show = False          # PAD-418: a block plays one of the game's own light shows
        self.game_wizard = False        # PAD-436: a block hands the player one of the game's own mini-wizards
        self.wizard_names = []          # PAD-457: ... which ones: the mode claims them as it loads
        self.lit = []                   # PAD-503: each Light the mode at's (shot index, inserts, rgb, pattern, ms,
                                        # PAD-521: the insert held solid and its rgb)
        self.lit_asked = False          # PAD-503: a condition asks whether the mode is lit
        self.unlit = []                 # PAD-600: the other modes whose light a block puts out, by slug
        self.unlight_own = False        # PAD-600: a block puts out this mode's own light

    def var(self, i, p="P()"):
        """Variable ``i`` of player ``p``, as C: its own row, or the shared global."""
        if i in self.shared:
            return "%s[%s]" % (shared_ident(self.var_names[i][0]), p)
        return "V[%d][%s]" % (i, p)

    def timer(self, name):
        return self.timers.get(str(name or "").lower())

    def shot(self, name):
        return "S[%d]" % self.shot_i(name)

    def light_i(self, b):
        """The C of a Light or Hand back block's slot in LIT: its shot's, or (PAD-598) after the shots, the game's
        light it names."""
        name = b.get("insert")
        if name and isinstance(name, str):
            if name not in self.lamps:
                self.lamps.append(name)
            return "N_SHOTS + %d" % self.lamps.index(name)
        return "%d" % self.shot_i(b.get("shot"))

    def shot_i(self, name):
        name = str(name or "")
        if name not in self.shots:
            self.shots.append(name)
        return self.shots.index(name)

    def event(self, name):
        name = str(name or "")
        if name not in self.events:
            self.events.append(name)
        return "E[%d]" % self.events.index(name)

    def hit(self, name):
        name = str(name or "")
        idx = self.shot(name)
        if name not in self.hits:
            self.hits.append(name)
        return "H[%d][P()]" % self.hits.index(name), idx

    def hits_of(self, name):
        """PAD-600: a shot's hits this ball for the player up, as every blocks mode on the card sees them: this
        mode's own count and what a Set the hits of block (in any of them) moved it by."""
        h, _idx = self.hit(name)
        return "hits_of(%s, %s[P()])" % (h, hits_ident(name))

    # values
    def num(self, e):
        if not isinstance(e, dict):
            return "0LL"
        k = e.get("k")
        if k == "num":
            try:
                v = max(-NUMBER_MAX, min(NUMBER_MAX, int(e.get("v"))))
            except (TypeError, ValueError):
                v = 0
            return "(%dLL)" % v
        if k == "var":
            i = self.vars.get(str(e.get("name") or "").lower())
            return self.var(i) if i is not None else "0LL"
        if k == "timer_left":
            i = self.timer(e.get("timer"))
            return "timer_left(%d)" % i if i is not None else "0LL"
        if k == "hits":
            return self.hits_of(e.get("shot"))
        if k == "scored":
            return "(long long)run.shots"
        if k == "total":
            return "(long long)run.total"
        if k == "secs_left":
            return "(long long)secs_left()"
        if k == "balls":
            return "(long long)pm_balls_in_play()"
        if k == "player":
            return "(long long)pm_player()"
        if k == "op":
            a, b = self.num(e.get("a")), self.num(e.get("b"))
            op = e.get("op")
            if op == "/":
                return "div0(%s, %s)" % (a, b)
            return "(%s %s %s)" % (a, OPS.get(op, "+"), b)
        return "0LL"

    def cond(self, e):
        if not isinstance(e, dict):
            return "0"
        k = e.get("k")
        if k == "cmp":
            return "(%s %s %s)" % (self.num(e.get("a")), CMPS.get(e.get("op"), "=="), self.num(e.get("b")))
        if k == "and":
            return "(%s && %s)" % (self.cond(e.get("a")), self.cond(e.get("b")))
        if k == "or":
            return "(%s || %s)" % (self.cond(e.get("a")), self.cond(e.get("b")))
        if k == "not":
            return "(!%s)" % self.cond(e.get("a"))
        if k == "running":
            return "run.on"
        if k == "stock":
            return "pm_stock_mode_running(PM_STOCK_ANY)"
        if k == "can_start":
            return "can_start()"
        if k == "lit":
            self.lit_asked = True
            return "lit_now()"
        return "0"

    # blocks
    def stack(self, stack, ind):
        out = []
        pad = "    " * ind
        for b in stack or []:
            if not isinstance(b, dict):
                continue
            op = b.get("op")
            if op == "start_mode":
                out.append(pad + 'start("a block", 1);')
            elif op == "end_mode":
                out.append(pad + 'end("a block");')
            elif op == "score":
                out.append(pad + "score(%s);" % self.num(b.get("points")))
            elif op == "set":
                i = self.vars.get(str(b.get("var") or "").lower())
                if i is not None:
                    out.append(pad + "%s = %s;" % (self.var(i), self.num(b.get("value"))))
            elif op == "change":
                i = self.vars.get(str(b.get("var") or "").lower())
                if i is not None:
                    out.append(pad + "%s += %s;" % (self.var(i), self.num(b.get("by"))))
            elif op == "timer_start":
                i = self.timer(b.get("timer"))
                if i is not None:
                    out.append(pad + "timer_start(%d, %s);" % (i, self.num(b.get("ms"))))
            elif op == "timer_stop":
                i = self.timer(b.get("timer"))
                if i is not None:
                    out.append(pad + "T[%d] = 0;" % i)
            elif op == "if":
                out.append(pad + "if (%s) {" % self.cond(b.get("cond")))
                out.extend(self.stack(b.get("then"), ind + 1))
                if b.get("else"):
                    out.append(pad + "} else {")
                    out.extend(self.stack(b.get("else"), ind + 1))
                out.append(pad + "}")
            elif op == "callout":
                said = self.callout(b.get("role") if b.get("role") in CALLOUT_ROLES else b.get("id"))
                if said:
                    out.append(pad + said + ";")
            elif op == "words":
                value = b.get("value")
                out.append(pad + "words(%s, %s, %d);" % (
                    _c_str(str(b.get("text") or "")[:TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1))
            elif op == "light_shot":
                pattern = b.get("pattern") if b.get("pattern") in PATTERNS else "solid"
                pat, ms = PATTERNS[pattern]
                color = str(b.get("color") or "#ffffff")
                rgb = int(color[1:], 16) if COLOR_RE.match(color) else 0xFFFFFF
                if pattern == "off":
                    rgb = 0                             # PAD-601: held dark
                rate = b.get("rate")
                pace = self.num(rate) if rate is not None and pattern not in ("solid", "hurry", "off") else "%dLL" % ms
                out.append(pad + "light(%s, 0x%06xu, %s, %s, %d);"
                           % (self.light_i(b), rgb, pat, pace, 1 if pattern == "hurry" else 0))
            elif op == "lights_off":
                if b.get("shot") == "*" and not b.get("insert"):
                    out.append(pad + "unlight_all();")
                else:
                    out.append(pad + "unlight(%s);" % self.light_i(b))
            elif op == "show":
                steps = show_steps(b, self.p)
                if steps:
                    # PAD-646: one of the mode's own shows has one table however many blocks run it
                    name = b.get("show") if b.get("show") in SHOWS else b.get("name") if b.get("show") == "mine" else "its own"
                    key = ("mine:" + str(name).lower()) if b.get("show") == "mine" else None
                    i = next((i for i, s in enumerate(self.shows) if key and s["key"] == key), None)
                    if i is None:
                        self.shows.append({"key": key, "steps": steps, "name": name, "repeat": show_repeat(b, self.p)})
                        i = len(self.shows) - 1
                    out.append(pad + "show_start(SHOW_%d, %d, %s, %d);" % (i, len(steps), _c_str(name), self.shows[i]["repeat"]))
            elif op == "set_time" and b.get("at_least"):     # PAD-658: Keep at least N seconds on the clock
                n = self.num(b.get("seconds"))
                out.append(pad + "if (run.on && RUN_SECONDS && secs_left() < (%s)) set_time(%s);" % (n, n))
            elif op in ("add_time", "set_time"):
                out.append(pad + "%s(%s);" % (op, self.num(b.get("seconds"))))
            elif op == "multiball":
                try:
                    balls = max(2, min(6, int(b.get("balls"))))
                    save = max(0, min(60, int(b.get("save", 0))))
                except (TypeError, ValueError):
                    balls, save = 2, 0
                # PAD-373: its own multiball is not one of the game's modes beginning
                out.append(pad + "if (run.on && pm_multiball_start(%du, %du)) run.own_mball = 1;" % (balls, save))
            elif op == "log":
                out.append(pad + 'pm_log("%%s", %s);' % _c_str(str(b.get("text") or "")[:TEXT_MAX]))
            elif op == "hud_award" and not self.p["hud"]["on"] and self.p["screen"]:
                value = b.get("value")      # PAD-574: on its own screen, as a Words block for the award's moment
                try:
                    secs = max(1, min(AWARD_SECONDS_MAX, int(b.get("seconds"))))
                except (TypeError, ValueError):
                    secs = 2
                out.append(pad + "award_words(%s, %s, %d, %du);" % (
                    _c_str(str(b.get("text") or "")[:HUD_TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1, secs * 1000))
            elif op.startswith("hud_") and not self.p["hud"]["on"]:
                out.append(pad + "/* %s: the mode has no HUD */" % op)
            elif op == "hud_text":
                value = b.get("value")
                out.append(pad + "hud_words(%d, %s, %s, %d);" % (
                    1 if b.get("which") == "line" else 0, _c_str(str(b.get("text") or "")[:HUD_TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1))
            elif op == "hud_counter":
                try:
                    k = max(1, min(3, int(b.get("counter"))))
                except (TypeError, ValueError):
                    k = 1
                sub = b.get("sub")
                label = b.get("label")                      # PAD-658: the counter's label from now on, or none
                out.append(pad + "hud_counter(%d, %s, %s, %s);" % (
                    k - 1, self.num(b.get("value")),
                    "0" if sub is None else _c_str(str(sub)[:COUNTER_MAX]),
                    "0" if not label else _c_str(str(label)[:COUNTER_MAX])))
            elif op == "hud_gauge":
                out.append(pad + "hud_level = %s;" % self.num(b.get("value")))
            elif op == "hud_award":
                value = b.get("value")
                try:
                    secs = max(1, min(AWARD_SECONDS_MAX, int(b.get("seconds"))))
                except (TypeError, ValueError):
                    secs = 2
                out.append(pad + "hud_award(%s, %s, %d, %s, %du);" % (
                    _c_str(str(b.get("text") or "")[:HUD_TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1,
                    _c_str(str(b.get("sub") or "")[:HUD_TEXT_MAX]), secs * 1000))
            elif op == "clip":
                name = str(b.get("clip") or "")
                if MEDIA_RE.match(name):
                    fn = {"full": "clip_full", "behind": "clip_behind", "loop": "clip_loop"}.get(
                        b.get("where"), "clip_full")
                    out.append(pad + "%s(%s);" % (fn, _c_str(name)))
            elif op == "music":                          # PAD-658: another of its music beds, or its own again
                bed = str(b.get("bed") or "")
                if bed == "" or MEDIA_RE.match(bed):
                    out.append(pad + "pa_music_bed(&own, %s);" % _c_str(bed))
            elif op == "sound":
                name = str(b.get("sound") or "")
                if MEDIA_RE.match(name):
                    fb = self.callout(b.get("fallback"))
                    if fb:
                        out.append(pad + "if (!sound(%s)) %s;" % (_c_str(name), fb))
                    else:
                        out.append(pad + "sound(%s);" % _c_str(name))
            elif op == "hold":
                what = str(b.get("what") or "")
                if HOLD_RE.match(what):
                    self.mech = True
                    if what not in self.holds:
                        self.holds.append(what)
                    out.append(pad + "%s(%s, %s);" % ("hold_wait" if b.get("clock") == "wait" else "hold",   # PAD-621
                                                      _c_str(what), self.num(b.get("ms"))))
            elif op == "scoop_hold":
                self.mech = True
                out.append(pad + "scoop_hold(%s, %d);" % (self.num(b.get("ms")), 0 if b.get("which") == "every" else 1))
            elif op == "let_go":
                what = str(b.get("what") or "")
                if what == "*":
                    self.mech = True
                    out.append(pad + "let_go_all();")
                elif what == "scoop":
                    self.mech = True
                    out.append(pad + "scoop_let_go();")
                elif HOLD_RE.match(what):
                    self.mech = True
                    if what not in self.holds:
                        self.holds.append(what)
                    out.append(pad + "if (run.on) pm_coil_release(%s);" % _c_str(what))
            elif op == "shield":
                where = {"toward": "PM_SHIELD_TOWARD", "away": "PM_SHIELD_AWAY", "leave": "0"}.get(b.get("where"))
                if where:
                    self.mech = True
                    out.append(pad + "shield(%s);" % where)
            elif op == "building":                                                    # PAD-589
                floor = str(b.get("floor"))
                if floor in BUILDING_FLOOR:
                    self.mech = True
                    out.append(pad + "building(%d);" % int(floor))
            elif op == "shake":                                                       # PAD-414
                strength = SHAKE_STRENGTH.get(b.get("strength"))
                if strength is not None:
                    self.mech = True
                    out.append(pad + "shake(%s, %d);" % (self.num(b.get("ms")), strength))
            elif op == "shake_game":
                name = str(b.get("shake") or "")
                if HOLD_RE.match(name):
                    self.mech = True
                    out.append(pad + "shake_game(%s);" % _c_str(name))
            elif op == "game_show":
                name = b.get("name")
                if name and isinstance(name, str):
                    self.game_show = True
                    out.append(pad + "game_show(%s);" % _c_str(name))
            elif op == "game_wizard":
                name = b.get("name")
                if name and isinstance(name, str):
                    self.game_wizard = True
                    if name not in self.wizard_names:
                        self.wizard_names.append(name)
                    out.append(pad + "game_wizard(%s, %d);" % (_c_str(name), 1 if b.get("how") == "start" else 0))
            elif op == "light_mode":                                                  # PAD-503
                pattern = b.get("pattern") if b.get("pattern") in LIT_PATTERNS else "blink"
                pat, ms = PATTERNS[pattern]
                color = str(b.get("color") or "")
                rgb = int(color[1:], 16) if COLOR_RE.match(color) else 0xFFD000
                insert = ",".join((lit_inserts(b.get("insert")) or [])[:LIT_INSERTS_MAX])
                solid = b.get("solid") if isinstance(b.get("solid"), str) else ""
                if "," in solid or len(solid) > INSERT_MAX:
                    solid = ""
                scol = str(b.get("solid_color") or "#ffffff")
                srgb = int(scol[1:], 16) if COLOR_RE.match(scol) else 0xFFFFFF
                spec = (self.shot_i(b.get("shot")), insert, rgb, pat, ms, solid, srgb if solid else 0)
                if spec not in self.lit:
                    self.lit.append(spec)
                out.append(pad + "light_mode(%d);" % self.lit.index(spec))
            elif op == "set_hits":                                                    # PAD-600
                name = b.get("shot")
                h, _idx = self.hit(name)
                out.append(pad + "%s[P()] = %s - (long long)%s;" % (hits_ident(name), self.num(b.get("value")), h))
            elif op == "unlight_mode":                                                # PAD-600
                mode = b.get("mode") or ""
                if not isinstance(mode, str) or (mode and not SLUG_RE.match(mode)):
                    continue
                if not mode or lit_ident(mode) == lit_ident(self.slug):
                    self.unlight_own = True
                    out.append(pad + "unlight_mode();")
                else:
                    if mode not in self.unlit:
                        self.unlit.append(mode)
                    out.append(pad + "unlight_other(%s, %s);   /* the mode %s's light out */"
                               % (lit_ident(mode), _c_str(mode), _comment(mode)))
        return out

    @staticmethod
    def callout(v):
        """The C that says a game's callout (a role's name or a number), or "" for none."""
        if v in CALLOUT_ROLES:
            return "pm_callout(pm_callout_id(%s))" % _c_str(v)
        if v in (None, ""):
            return ""
        try:
            return "pm_callout(%du)" % max(1, min(65535, int(v)))
        except (TypeError, ValueError):
            return ""


def c_ident(slug):
    from . import mode_tryit as MT
    return MT._c_ident(slug)


def hits_ident(shot):
    """PAD-600: the C global that moves a shot's hits this ball in every blocks mode that reads them (a Set the hits
    of block's difference from the count): ``"Target 1"`` -> ``pad_hits_target_1``."""
    return "pad_hits_" + re.sub(r"[^a-z0-9]", "_", str(shot or "").lower())


def lit_ident(slug):
    """PAD-600: the C global a blocks mode's Light the mode at is held in, per player (its ``lit_as``), so another
    mode can put it out: ``target_1`` -> ``pad_lit_target_1``."""
    return "pad_lit_" + re.sub(r"[^a-z0-9]", "_", str(slug or "").lower())


def shared_ident(name):
    """The C global a shared variable is in every mode that names it: case, spaces and _ aside,
    the same name is the same value (``"Maser won"`` -> ``pad_shared_maser_won``)."""
    return "pad_shared_" + re.sub(r"[^a-z0-9]", "_", str(name or "").lower())


def to_c(program, slug):
    """The C a program makes: one mode for the Mode SDK, in the template's shape."""
    program = normalize(program)
    g = _Gen(program, slug)
    name = program["name"] or slug.upper()
    from . import mode_tryit as MT
    title = MT._c_title(name, slug)
    ident = c_ident(slug)
    media = uses_media(program)

    # every script's body first: that is when the tables fill
    bodies = {k: [] for k in HATS}
    for i, s in enumerate(program["scripts"]):
        hat = s.get("hat") or {}
        kind = hat.get("kind")
        if kind not in HATS:
            continue
        body = g.stack(s.get("do") or [], 2)
        bodies[kind].append((i + 1, hat, body))
    # the hats' own shots and events
    hat_code = {k: [] for k in HATS}
    challenge_names = []                    # PAD-615: the game's challenges its scripts take the place of
    challenge_launch = []                   # PAD-643: each one's launch (pm_challenge_launch)
    for kind, items in bodies.items():
        for n, hat, body in items:
            head = "    /* script %d: %s */" % (n, _comment(_hat_words(hat)))
            when = hat.get("when", "any")
            # a shot or event is judged by the mode's state BEFORE it: the shot that starts
            # the mode is not also one "while it runs"
            gate = {"idle": "!was_on", "running": "was_on"}.get(when)
            if kind in ("shot", "any_shot", "switch") and when == "idle":
                gate = "idle"                   # PAD-675: not running, and no other mode is either
            if kind == "shot":
                test = "(%s && (shot & %s))" % (g.shot(hat.get("shot")), g.shot(hat.get("shot")))
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "any_shot":
                test = "(shot & named)"
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "switch":                       # PAD-675: the game's 0x1 dispatch, one a switch hit
                test = "(shot & 1ull)"
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "event":
                test = "(%s >= 0 && id == (unsigned)%s)" % (g.event(hat.get("event")), g.event(hat.get("event")))
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "every":
                secs = max(1, min(SECONDS_MAX, int(hat.get("seconds") or 1)))
                test = "(run.on && run.elapsed %% %du == 0)" % (secs * 60)
            elif kind == "seconds_left":
                secs = max(1, min(SECONDS_MAX, int(hat.get("seconds") or 1)))
                test = "(run.on && sec_changed && run.seconds_shown == %du)" % secs
            elif kind == "timer_done":
                t = g.timer(hat.get("timer"))
                test = "(due[%d])" % t if t is not None else "(0)"
            elif kind == "challenge":                    # PAD-615: picked on the game's thread, run on the tick
                name = str(hat.get("challenge") or "")
                if name not in challenge_names:
                    challenge_names.append(name)
                    challenge_launch.append(challenge_launch_ms(hat))      # PAD-643
                test = "(picked & %du)" % (1 << challenge_names.index(name))
            else:
                test = None
            if test is None:
                hat_code[kind].append((n, "\n".join([head, "    {"] + body + ["    }"])))
            else:
                hat_code[kind].append((n, "\n".join([head, "    if %s {" % test] + body + ["    }"])))

    hud = program["hud"]
    has_hud = hud["on"]
    # PAD-658: the clip a note, and a TOTAL with nothing looping, show over: the mode's first clip "over and over"
    # (When the mode starts' first, else any script's), else the first clip When the mode starts plays (ANGUIRUS: his
    # entrance), else its first clip
    in_order = [b for s in sorted(program["scripts"], key=lambda s: (s.get("hat") or {}).get("kind") != "mode_start")
                for b in _walk(s.get("do") or []) if b.get("op") == "clip" and b.get("clip")]
    covers = [b["clip"] for b in in_order if b.get("where") == "loop"] + [b["clip"] for b in in_order] + \
        [c["name"] for c in program.get("clips") or []]
    note_cue = covers[0] if media and has_hud and covers else None
    # PAD-375: a mode with a HUD or a screen of its own watches the game's displays (the kit's
    # kit_display): its words step aside under one, so it holds a display priority while it runs
    watch = has_hud or program["screen"]
    has_bar = program["bar"]["on"]          # PAD-521: its name, colour and clock in the game's own status bar
    info = program["info"]                  # PAD-547: a line of words and a value under its name
    has_info = info["on"]
    info_live = g.num(info["value"]) if has_info and info["value"] is not None else None
    live = []                           # (counter 0-2, C of its value): counters that follow a value
    gauge_live = None
    if has_hud:
        for k, c in enumerate(hud["counters"]):
            if c["label"] and c["value"] is not None:
                live.append((k, g.num(c["value"])))
        if hud["gauge"]["on"] and hud["gauge"]["value"] is not None:
            gauge_live = g.num(hud["gauge"]["value"])

    def scripts_of(*kinds):
        """The scripts of these hats, in the order the page shows them: top to bottom."""
        return [code for _n, code in sorted(x for k in kinds for x in hat_code[k])]

    L = []
    L.append("/* %s.c - %s, a mode made of blocks in the Modes tab (PAD-232)" % (slug, _comment(title)))
    L.append(" *")
    L.append(" * MADE FROM blocks.json: the Modes tab writes this file again every time the blocks")
    L.append(" * change, so an edit here is lost at the next one. To carry on in C, press Edit as C")
    L.append(" * on the mode's page: the blocks are put away and this file is yours. That is ONE WAY:")
    L.append(" * C is never turned back into blocks (Duplicate the mode first to keep a blocks copy).")
    L.append(" *")
    L.append(" * " + _comment(summary(program)) + ".")
    L.append(" */")
    L.append('#include "pad_mode.h"')
    if has_hud:
        L.append('#include "%s"   /* the examples\' kit: the HUD (copied here at every save) */' % KIT_FILE)
    if media:
        L.append('#include "pad_mode_assets.h"     /* its own clips and sounds, as Write carried them */')
    L.append("")
    L.append('#define MODE_NAME        %s' % _c_str(title))
    L.append("#define RUN_SECONDS      %d          /* 0 = no clock */" % program["seconds"])
    L.append("#define ENDS_ON_DRAIN    %d" % (1 if program["ends_on_drain"] else 0))
    L.append("#define TICKS_PER_SECOND 60")
    L.append("#define CLOCK_MAX        %d         /* the most seconds the clock holds */" % SECONDS_MAX)
    L.append("#define WAITS_OUT_MULTIBALL %d       /* 1 = a start while a multiball runs waits for the next */"
             % (1 if program["wait_multiball"] else 0))
    L.append("#define DISPLAY_PRIORITY %d          /* held while it runs; 0 = none (MODE_SDK.md) */"
             % (program["priority"] or (HUD_PRIORITY if has_hud else 0)))
    L.append("#define TIMER_MAX_MS     %dL" % TIMER_MAX_MS)
    L.append("#define ENDING_MS        %d        /* the total its own screen shows at the end */" % TOTAL_MS)
    L.append("#define DRAIN_TOTAL_MS   %d        /* PAD-622: ...and at a drain, the game's end of ball waiting */" % DRAIN_TOTAL_MS)
    L.append("#define ENDING_NOW_MS    (drain_long ? DRAIN_TOTAL_MS : ENDING_MS)")
    words_only = program["screen"] and program["screen_style"] == "words"
    L.append("#define WORDS_ONLY       %d          /* PAD-521: its screen is words alone: shown a moment, not all along */"
             % (1 if words_only else 0))
    if has_bar:
        L.append("#define BAR_RGB          0x%06xu   /* PAD-521: its color in the game's own status bar */"
                 % int(program["bar"]["color"][1:], 16))
    L.append("#define UNUSED __attribute__((unused))   /* a helper the blocks may not call */")
    L.append("")
    gm = program["game_modes"]                           # PAD-373: as a form mode's (PAD-363)
    ids = program["block_modes"]
    L.append("/* While it runs, the game's own modes %s. */" % GAME_MODES[gm])
    L.append("#define GAME_MODES       %d          /* 0 = they may start, 1 = it starts only while none runs and one"
             % {"stack": 0, "give_way": 1, "block": 2}[gm])
    L.append("                                   * starting ends it, 2 = as 1, and the ones in BLOCK_IDS cannot start */")
    L.append("UNUSED static const unsigned char BLOCK_IDS[%d] = {%s};   /* the game's mode ids; none = the port's defaults */"
             % (max(1, len(ids)), ", ".join(str(i) for i in ids) or "0"))
    L.append("#define BLOCK_N          %d" % len(ids))
    L.append("/* PAD-398: the game's features (its rules, by the port's names) that keep counting while it blocks;")
    L.append(" * every other one sees no shots. */")
    L.append("#define KEEP_RULES       %s" % _c_str(", ".join(program.get("keep_rules") or [])))
    L.append("")
    L.append("/* The screen a build added for this mode (its folder is \"%s\"). Not there = no screen. */" % slug)
    L.append('#define SCREEN_NODE  "PadMode_%s_Screen"' % slug)
    L.append('#define SCREEN_TEXT  "PadMode_%s_Screen.PadMode_%s_Screen_Words"' % (slug, slug))
    if words_only:
        L.append("/* PAD-574: its TOTAL as the game's own modes end (James Bond: TOTAL over the number, under the bar): two")
        L.append(" * screens a build put there. Not there = the TOTAL over its video, on its own screen. */")
        L.append('#define TOTAL_NAME_NODE "PadMode_%s_TotalName"' % slug)
        L.append('#define TOTAL_NAME_TEXT "PadMode_%s_TotalName.PadMode_%s_TotalName_Words"' % (slug, slug))
        L.append('#define TOTAL_NODE   "PadMode_%s_Total"' % slug)
        L.append('#define TOTAL_TEXT   "PadMode_%s_Total.PadMode_%s_Total_Words"' % (slug, slug))
    if has_info:
        L.append("/* PAD-547: its info line, a screen of its own the build put where the title's port says (James Bond: under")
        L.append(" * the status bar). Not there = no line. */")
        L.append('#define INFO_NODE    "PadMode_%s_Info"' % slug)
        L.append('#define INFO_TEXT    "PadMode_%s_Info.PadMode_%s_Info_Words"' % (slug, slug))
        L.append("#define INFO_FORMAT  %s" % _c_str(info_line_c(info["text"].replace("%", "%%"), info_live is not None)))
    L.append("")
    L.append("/* ---- the shots, events and variables the blocks name ---- */")
    nshots, nevents, nvars, nhits = max(1, len(g.shots)), max(1, len(g.events)), max(1, len(g.var_names)), max(1, len(g.hits))
    L.append("UNUSED static const char *const SHOT_NAMES[%d] = {%s};" % (
        nshots, ", ".join(_c_str(s) for s in g.shots) or "0"))
    L.append("UNUSED static uint64_t S[%d];                /* each shot's mask; 0 = this game has none */" % nshots)
    L.append("static uint64_t named;               /* every named shot */")
    L.append("UNUSED static const char *const EVENT_NAMES[%d] = {%s};" % (
        nevents, ", ".join(_c_str(e) for e in g.events) or "0"))
    L.append("UNUSED static int E[%d];                     /* each event's id; -1 = this game has none */" % nevents)
    for i, (n, reset) in enumerate(g.var_names):
        L.append("/* V[%d] = %s, per player, reset %s */" % (i, _comment(n), RESETS[reset]))
    L.append("UNUSED static long long V[%d][5];            /* the variables, per player 1-4 */" % nvars)
    for i in sorted(g.shared):
        n, reset = g.var_names[i]
        L.append("/* %s: SHARED - one value per player for every mode that names it, reset %s. The linker"
                 % (_comment(n), RESETS[reset]))
        L.append(" * keeps one of these weak lines for all the modes built in; a mode in C shares it by"
                 " declaring the same. */")
        L.append('__attribute__((weak, visibility("hidden"))) long long %s[5];' % shared_ident(n))
    ntimers = max(1, len(g.timer_names))
    for i, n in enumerate(g.timer_names):
        L.append("/* T[%d] = the timer %s */" % (i, _comment(n)))
    L.append("UNUSED static unsigned long T[%d];           /* each timer's end, pm_ms(); 0 = not running */"
             % ntimers)
    for i, n in enumerate(g.hits):
        L.append("/* H[%d] = hits of %s this ball */" % (i, _comment(n)))
    L.append("UNUSED static unsigned H[%d][5];             /* hits this ball, per player */" % nhits)
    L.append("UNUSED static const char HIT_OF[%d] = {%s};" % (
        nhits, ", ".join(str(g.shots.index(n)) for n in g.hits) or "0"))
    hit_moves = []
    for n in g.hits:
        if hits_ident(n) not in hit_moves:
            hit_moves.append(hits_ident(n))
    if hit_moves:
        L.append("/* PAD-600: a shot's hits are one count for every blocks mode on the card. Each counts them itself (and")
        L.append(" * clears them when the ball ends or a game begins, so the counts agree); a Set the hits of block keeps")
        L.append(" * its difference from the count here, one weak line per shot the linker keeps once, every mode adds it */")
        for hm in hit_moves:
            L.append('__attribute__((weak, visibility("hidden"))) long long %s[5];' % hm)
        L.append("UNUSED static long long hits_of(unsigned h, long long moved)")
        L.append("{")
        L.append("    long long n = (long long)h + moved;")
        L.append("    return n < 0 ? 0 : n;")
        L.append("}")
    lit_moves = [lit_ident(m) for m in g.unlit]
    if lit_moves:
        L.append("/* PAD-600: the other modes whose light a block puts out: each one's Light the mode at, per player */")
        for lm in lit_moves:
            L.append('__attribute__((weak, visibility("hidden"))) int %s[5];' % lm)
    L.append("")
    L.append("static struct {")
    L.append("    int on;")
    L.append("    int own_mball;                    /* a Multiball block served balls: not the game's multiball */")
    L.append("    unsigned player, ticks_left, seconds_shown, elapsed, shots;")
    L.append("    uint64_t total;")
    L.append("} run;")
    L.append("static int sec_changed, ending;")
    L.append("UNUSED static int end_clip;                /* PAD-658: When the mode ends played a full-screen clip */")
    L.append("#define END_CLIP_MS      7000      /* ... its TOTAL stays this much longer: the clip covers it first (it "
             "starts half a second in and runs up to 6 s: the TOTAL still has its 3 s after it, run godzilla_angry_r4) */")
    L.append("#define ENDING_HOLD_MS   (ENDING_NOW_MS + (end_clip ? END_CLIP_MS : 0))")
    L.append("static unsigned flash_ticks;           /* PAD-521: words alone: how long its words stay up */")
    L.append("static void *screen, *screen_words;")
    L.append("static unsigned hide_ticks, poll;")
    L.append("static unsigned ended_begun;          /* PAD-413: pm_begun() at its end, while its total shows */")
    L.append("static unsigned award_ticks;          /* PAD-574: an Award's words up this much longer */")
    L.append("static unsigned total_due;            /* PAD-574: ticks until its TOTAL: an Award it ended on shows first */")
    L.append("static int drain_long;                 /* PAD-622: its TOTAL at a drain, as long as the game's own */")
    L.append("static int drain_hold;                 /* PAD-622: the game's end of ball waits on it (set once it does) */")
    if not has_hud:
        L.append("static char award_next[96];           /* PAD-574: an Award of When the mode ends, after the one showing */")
        L.append("static unsigned award_next_ticks;")
    if words_only:
        L.append("static void *total, *total_words, *total_name, *total_name_words;   /* PAD-574: its TOTAL's two screens */")
    if has_bar:
        L.append("static unsigned bar_max, bar_hold;     /* PAD-521: the clock's most ticks; the bar kept through the total */")
    if watch:
        L.append("static int screen_away;                /* its screen hidden: a game display or mode has the middle */")
    if has_info:
        L.append("static void *info, *info_words;       /* PAD-547: its info line and that line's words */")
        L.append("static int info_up;                    /* shown now */")
        L.append("static char info_now[96];              /* what it says now */")
    if has_hud:
        L.append("")
        L.append("/* ---- the HUD at the glass's edges (PAD-375): the build's PadMode_%s_Hud group, driven by" % slug)
        L.append(" * the kit's struct kit_hud as the examples drive theirs - blank under a display of the game's,")
        L.append(" * aside while one of the game's modes runs. No HUD on the card: nothing shows, the mode runs. */")
        gg = hud["gauge"]
        bar = gg["on"] and gg["kind"] == "bar"
        meter = gg["on"] and gg["meter"] and gg["value"] is not None
        # PAD-658: a corner bar shown while it is not running stands BESIDE another mode's HUD (the kit's beside)
        L.append('static struct kit_hud hud = { .slug = "%s"%s };' % (slug, ", .beside = 1" if bar and meter else ""))
        L.append("#define HUD_LINE   %s" % _c_str(hud["line"]))
        L.append("#define HUD_TIMER  %d          /* the badge counts the clock */" % (
            1 if hud["timer"]["on"] and program["seconds"] else 0))
        L.append("#define HUD_GAUGE  %d          /* pips of the gauge; 0 = no gauge */" % (
            hud["gauge"]["count"] if hud["gauge"]["on"] else 0))
        L.append("#define HUD_GAUGE_LABEL %s" % _c_str(hud["gauge"]["label"]))
        L.append("#define HUD_GAUGE_BAR %d       /* PAD-658: 1 = the corner bar, its value a percent */" % bar)
        L.append("#define HUD_GAUGE_FULL %s" % _c_str(gg["full"]))
        L.append("#define HUD_METER  %d          /* PAD-658: 1 = the gauge shows while it is not running too */" % meter)
        L.append("UNUSED static const char *const HUD_LABEL[3] = {%s};" % ", ".join(
            _c_str(c["label"]) for c in hud["counters"]))
        L.append("UNUSED static const char *const HUD_SUB[3] = {%s};" % ", ".join(
            _c_str(c["sub"]) for c in hud["counters"]))
        L.append("static char hud_val[3][24], hud_sub[3][24];   /* each counter's value and sub-label now */")
        L.append("static char hud_lab[3][24];                     /* PAD-658: and its label now (a block may change it) */")
        L.append("UNUSED static long long hud_level;          /* the gauge's pips lit (a bar: its percent) */")
    L.append("")
    L.append("static unsigned P(void)")
    L.append("{")
    L.append("    unsigned p = pm_player();")
    L.append("    return p <= 4 ? p : 0;")
    L.append("}")
    L.append("")
    if lit_moves:
        L.append("/* PAD-600: Put out the light of another mode, for the player up */")
        L.append("static void unlight_other(int *lit, const char *mode)")
        L.append("{")
        L.append("    unsigned p = P();")
        L.append("    if (!p || !lit[p]) return;")
        L.append('    pm_log("put out the light of %s for player %u", mode, p);')
        L.append("    lit[p] = 0;")
        L.append("}")
        L.append("")
    L.extend(_NEW_GAME_C.split("\n"))
    L.append("UNUSED static long long div0(long long a, long long b)")
    L.append("{")
    L.append("    return b ? a / b : 0;")
    L.append("}")
    L.append("")
    L.append("UNUSED static unsigned secs_left(void)")
    L.append("{")
    L.append("    return run.on && RUN_SECONDS ? (run.ticks_left + TICKS_PER_SECOND - 1) / TICKS_PER_SECOND : 0;")
    L.append("}")
    L.append("")
    if has_bar:
        L.extend(_BAR_C.split("\n"))
    if has_info:
        L.extend((_INFO_C % {"value": info_live or "0"}).split("\n"))
    L.append("/* a timer: ms from now (0 or less stops it); the milliseconds it has left */")
    L.append("UNUSED static void timer_start(int i, long long ms)")
    L.append("{")
    L.append("    if (ms <= 0) {")
    L.append("        T[i] = 0;")
    L.append("        return;")
    L.append("    }")
    L.append("    if (ms > TIMER_MAX_MS) ms = TIMER_MAX_MS;")
    L.append("    T[i] = pm_ms() + (unsigned long)ms;")
    L.append("    if (!T[i]) T[i] = 1;")
    L.append("}")
    L.append("")
    L.append("UNUSED static long long timer_left(int i)")
    L.append("{")
    L.append("    long left = T[i] ? (long)(T[i] - pm_ms()) : 0;")
    L.append("    return left > 0 ? left : 0;")
    L.append("}")
    L.append("")
    for when in ("ball", "mode"):
        L.append("static void reset_%s(void)          /* the variables reset %s */" % (when, RESETS[when]))
        L.append("{")
        L.append("    unsigned p = P();")
        for i, (_n, reset) in enumerate(g.var_names):
            if reset == when:
                L.append("    %s = 0;" % g.var(i, "p"))
        L.append("    (void)p;")
        L.append("}")
        L.append("")
    L.append("UNUSED static void words(const char *text, long long value, int with_value)")
    L.append("{")
    L.append("    char number[32], line[96];")
    L.append("    if (!screen_words) return;")
    L.append("    award_ticks = 0;")
    L.append("    if (with_value) {")
    L.append("        pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);")
    L.append('        pm_snprintf(line, sizeof line, "%s%s%s", text, text[0] ? " " : "", number);')
    L.append("        pm_set_text(screen_words, line);")
    L.append("    } else {")
    L.append("        pm_set_text(screen_words, text);")
    L.append("    }")
    L.append("    if (WORDS_ONLY && run.on && screen) {   /* PAD-521: words alone stay up a moment */")
    L.append("        flash_ticks = %d * TICKS_PER_SECOND / 1000;" % WORDS_SHOW_MS)
    L.append("        if (!screen_away) pm_show(screen, 1);" if watch else "        pm_show(screen, 1);")
    L.append("    }")
    L.append("}")
    L.append("")
    if not has_hud:
        L.append("/* PAD-574: an Award block with no HUD: its words and value on its own screen for its moment (its smaller line")
        L.append(" * has no place there); an End the mode after it lets it show before the TOTAL */")
        L.append("UNUSED static void award_words(const char *text, long long value, int with_value, unsigned ms)")
        L.append("{")
        L.append("    if (!screen_words || !run.on) return;")
        L.append("    if (ending && award_ticks) {      /* in When the mode ends, after the Award it ended on: next */")
        L.append("        char number[32];")
        L.append("        if (with_value) {")
        L.append("            pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);")
        L.append('            pm_snprintf(award_next, sizeof award_next, "%s%s%s", text, text[0] ? " " : "", number);')
        L.append("        } else {")
        L.append('            pm_snprintf(award_next, sizeof award_next, "%s", text);')
        L.append("        }")
        L.append("        award_next_ticks = ms * TICKS_PER_SECOND / 1000;")
        L.append("        return;")
        L.append("    }")
        L.append("    words(text, value, with_value);")
        L.append("    award_ticks = ms * TICKS_PER_SECOND / 1000;")
        L.append("    if (WORDS_ONLY && screen) flash_ticks = award_ticks;")
        L.append("}")
        L.append("")
    L.append("/* its TOTAL for its moment at its end (on its own screen; PAD-574: a words-alone one's under the bar as the game's")
    L.append(" * own modes show theirs, when the build put the two screens there) */")
    L.append("static void total_show(void)")
    L.append("{")
    L.append("    if (!screen) return;")
    if words_only:
        L.append("    if (total && total_words) {")
        L.append("        char n[32];")
        L.append("        pm_show(screen, 0);")
        L.append("        pm_commas(n, sizeof n, run.total);")
        L.append("        pm_set_text(total_words, n);")
        L.append("        pm_show(total, 1);")
        L.append("        if (total_name && total_name_words) {")
        L.append('            pm_set_text(total_name_words, "TOTAL");')
        L.append("            pm_show(total_name, 1);")
        L.append("        }")
        L.append("    } else {")
        L.append("        if (WORDS_ONLY) pm_show(screen, 1);   /* PAD-521: its TOTAL over the game's video */")
        L.append('        words("TOTAL", (long long)run.total, 1);')
        L.append("    }")
    else:
        L.append('    words("TOTAL", (long long)run.total, 1);')
    L.append("    hide_ticks = ENDING_NOW_MS / 1000 * TICKS_PER_SECOND;")
    L.append("}")
    L.append("")
    L.append("static void total_hide(void)")
    L.append("{")
    L.append("    total_due = 0;")
    L.append("    if (screen) pm_show(screen, 0);")
    if words_only:
        L.append("    if (total) pm_show(total, 0);")
        L.append("    if (total_name) pm_show(total_name, 0);")
    L.append("}")
    L.append("")
    L.append("UNUSED static void score(long long points)")
    L.append("{")
    L.append("    uint64_t got;")
    L.append("    if (!run.on || points <= 0) return;")
    L.append("    got = pm_score_add(run.player, (uint64_t)points);   /* the game may add less */")
    L.append("    run.total += got;")
    L.append("    run.shots++;")
    L.append("}")
    L.append("")
    L.append("/* The clock to this many ticks. Put UP, the second it lands on is not \"left\" again: a When N")
    L.append(" * seconds are left for it does not run (the kit's kit_timer_at_least); counting down past it")
    L.append(" * later, they run as ever. */")
    L.append("UNUSED static void clock_to(long long ticks)")
    L.append("{")
    L.append("    unsigned before = run.ticks_left;")
    L.append("    if (ticks < 0) ticks = 0;")
    L.append("    if (ticks > CLOCK_MAX * TICKS_PER_SECOND) ticks = CLOCK_MAX * TICKS_PER_SECOND;")
    L.append("    run.ticks_left = (unsigned)ticks;")
    L.append("    if (run.ticks_left > before) run.seconds_shown = secs_left();")
    L.append("}")
    L.append("")
    L.append("UNUSED static void add_time(long long seconds)   /* less than 0 takes time off; never to 0 */")
    L.append("{")
    L.append("    long long t;")
    L.append("    if (!run.on || !RUN_SECONDS) return;")
    L.append("    if (seconds > CLOCK_MAX) seconds = CLOCK_MAX;")
    L.append("    if (seconds < -CLOCK_MAX) seconds = -CLOCK_MAX;")
    L.append("    t = (long long)run.ticks_left + seconds * TICKS_PER_SECOND;")
    L.append("    clock_to(t > 0 ? t : 1);")
    L.append("}")
    L.append("")
    L.append("UNUSED static void set_time(long long seconds)   /* 0 = time is up */")
    L.append("{")
    L.append("    if (!run.on || !RUN_SECONDS) return;")
    L.append("    if (seconds > CLOCK_MAX) seconds = CLOCK_MAX;")
    L.append("    clock_to(seconds * TICKS_PER_SECOND);")
    L.append("}")
    L.append("")
    if has_hud:
        L.append("/* a counter (0-2) to a value, short enough for its 200 px (950,000 / 4.25M); sub 0 = as it is */")
        L.append("UNUSED static void hud_counter(int k, long long value, const char *sub, const char *label)")
        L.append("{")
        L.append("    if (k < 0 || k > 2 || !HUD_LABEL[k][0]) return;      /* a counter with no label is not shown */")
        L.append("    kit_short(hud_val[k], sizeof hud_val[k], value < 0 ? 0 : (uint64_t)value);")
        L.append("    if (sub) kit_copy(hud_sub[k], sizeof hud_sub[k], sub);")
        L.append("    if (label && label[0]) kit_copy(hud_lab[k], sizeof hud_lab[k], label);   /* PAD-658 */")
        L.append("}")
        L.append("")
        L.append("static void hud_line(char *line, unsigned cap, const char *text, long long value, int with_value)")
        L.append("{")
        L.append("    char number[32];")
        L.append("    if (!with_value) {")
        L.append("        kit_copy(line, cap, text);")
        L.append("        return;")
        L.append("    }")
        L.append("    pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);")
        L.append('    pm_snprintf(line, cap, "%s%s%s", text, text[0] ? " " : "", number);')
        L.append("}")
        L.append("")
        L.append("/* the title (0) or the instruction line (1); kept until the mode starts again */")
        L.append("/* PAD-658: the title and line When the mode ends wrote: its TOTAL's, in the place of \"<NAME> TOTAL\" */")
        L.append("static char end_title[KIT_HUD_WORDS], end_line[KIT_HUD_WORDS];")
        L.append("UNUSED static void hud_words(int which, const char *text, long long value, int with_value)")
        L.append("{")
        L.append("    char line[KIT_HUD_WORDS];")
        L.append("    hud_line(line, sizeof line, text, value, with_value);")
        L.append("    if (ending) kit_copy(which ? end_line : end_title, KIT_HUD_WORDS, line);")
        L.append("    if (which) kit_hud_title(&hud, 0, line);")
        L.append("    else kit_hud_title(&hud, line, 0);")
        L.append("}")
        L.append("")
        if note_cue:
            L.append("UNUSED static void note_loop(void);")
        else:
            L.append("#define note_loop() ((void)0)           /* no clip of its own loops behind its HUD: a note shows alone */")
        L.append("")
        L.append("/* the award line for a moment; on a mode not running, a note shown alone (kit_hud_note: not over")
        L.append(" * another mode's HUD) */")
        L.append("UNUSED static void hud_award(const char *text, long long value, int with_value, const char *sub,")
        L.append("                             unsigned ms)")
        L.append("{")
        L.append("    char line[KIT_HUD_WORDS], under[KIT_HUD_WORDS], number[32];")
        L.append("    if (!run.on && !sub[0]) sub = MODE_NAME;   /* a note says whose it is */")
        L.append("    if (with_value && text[0]) {      /* PAD-658: the words big, the number under them with the sub */")
        L.append("        pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);   /* (one line of both ran off) */")
        L.append("        kit_copy(line, sizeof line, text);")
        L.append('        if (sub[0]) pm_snprintf(under, sizeof under, "%s  -  %s", number, sub);')
        L.append("        else kit_copy(under, sizeof under, number);")
        L.append("        sub = under;")
        L.append("    } else {")
        L.append("        hud_line(line, sizeof line, text, value, with_value);")
        L.append("    }")
        L.append("    if (run.on) kit_hud_award(&hud, ms, line, sub);")
        L.append("    else if (kit_hud_note(&hud, ms, line, sub)) note_loop();")
        L.append("}")
        L.append("")
        L.append("/* PAD-658: the gauge at `v`: a bar's slices lit in proportion to a percent, the percent its label (its full")
        L.append(" * word at 100); a pip gauge's pips. As a meter (`idle`) while the mode is not running. */")
        L.append("UNUSED static void gauge_now(long long v, int idle)")
        L.append("{")
        L.append("    char label[24];")
        L.append("    int lit;")
        L.append("    if (HUD_GAUGE_BAR) {")
        L.append("        v = v < 0 ? 0 : v > 100 ? 100 : v;")
        L.append("        lit = (int)(v * HUD_GAUGE / 100);")
        L.append("        if (v >= 100 && HUD_GAUGE_FULL[0]) kit_copy(label, sizeof label, HUD_GAUGE_FULL);")
        L.append('        else pm_snprintf(label, sizeof label, "%d%%", (int)v);')
        L.append("    } else {")
        L.append("        lit = v < 0 ? 0 : v > HUD_GAUGE ? HUD_GAUGE : (int)v;")
        L.append("        kit_copy(label, sizeof label, HUD_GAUGE_LABEL);")
        L.append("    }")
        L.append("    if (!idle) {")
        L.append("        kit_hud_gauge(&hud, lit, label);")
        L.append("        return;")
        L.append("    }")
        L.append("    kit_hud_pips(&hud, HUD_GAUGE);      /* the build's count, as at a start */")
        L.append("    kit_hud_meter(&hud, lit, label);")
        L.append("}")
        L.append("")
        L.append("/* every tick while it runs: the counters that follow a value, the badge, the gauge */")
        L.append("static void hud_show(void)")
        L.append("{")
        L.append("    int k;")
        for k, expr in live:
            L.append("    hud_counter(%d, %s, 0, 0);" % (k, expr))
        if gauge_live is not None:
            L.append("    hud_level = %s;" % gauge_live)
        L.append("    for (k = 0; k < 3; k++)")
        L.append("        if (HUD_LABEL[k][0]) kit_hud_counter(&hud, k, hud_lab[k], hud_val[k], hud_sub[k]);")
        L.append("    kit_hud_timer(&hud, HUD_TIMER ? (int)secs_left() : -1);")
        L.append("    if (HUD_GAUGE) gauge_now(hud_level, 0);")
        L.append("}")
        L.append("")
    if g.shows:
        L.extend(_show_decls(g.shows))
    else:
        L.append("#define SHOWING 0                         /* no Light show block */")
        L.append("")
    forget = "    lit_shown = 0;                    /* PAD-503: the mode's light is held again next tick */\n" if g.lit else ""
    if g.lit:
        L.append("static int lit_shown;                 /* PAD-503: 1 + the LIT_AT held on the playfield now; 0 = none */")
    L.extend((_LAMPS_C % {"n": len(g.shots), "size": nshots + len(g.lamps), "lo": RATE_MIN, "hi": RATE_MAX,
                          "forget": forget, "nl": len(g.lamps), "lsize": max(1, len(g.lamps)),
                          "lamps": ", ".join(_c_str(n) for n in g.lamps) or "0"}).split("\n"))
    if g.shows:
        L.extend(_SHOW_C.split("\n"))
    if media:
        L.extend((_MEDIA_C % {"slug": slug}).split("\n"))
    if note_cue:
        L.extend((_NOTE_LOOP_C % {"cue": _c_str(note_cue)}).split("\n"))
    if g.game_show:
        L.extend(_GAME_SHOW_C.split("\n"))
    if g.game_wizard:
        L.extend(_GAME_WIZARD_C.split("\n"))
    if g.mech:
        L.extend((_MECH_C % {"lo": HOLD_MIN_MS, "hi": HOLD_LONGEST_MS, "slo": SCOOP_MIN_MS, "shi": SCOOP_MAX_MS,
                             "release": "".join("    pm_coil_release(%s);\n" % _c_str(n) for n in g.holds)}
                  ).split("\n"))
    L.append("/* What of the game's own is running (a battle, a multiball, one of its timed modes), or 0. A port that")
    L.append(" * cannot tell answers none. PAD-503: and the game's own check before it starts one of its mini-wizards,")
    L.append(" * where the port names one (James Bond: its henchman, villain and Q Branch modes, which its flags do not show) */")
    L.append("UNUSED static const char *game_busy(void)")
    L.append("{")
    L.append("    int k = pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY);")
    L.append("    if (k > 0) return pm_stock_mode_what((unsigned)k);")
    L.append("    if (pm_can(PM_CAN_MULTIBALL) && pm_balls_in_play() >= 2) return \"a multiball\";")
    L.append("    if (pm_game_wizard_way() == 0) return \"one of the game's own modes\";")
    L.append("    return 0;")
    L.append("}")
    L.append("")
    L.append("/* \"the mode could start now\": in a game, not running, and nothing of the game's to wait out */")
    L.append("UNUSED static int can_start(void)")
    L.append("{")
    L.append("    return !run.on && pm_in_game() && !((WAITS_OUT_MULTIBALL || GAME_MODES) && game_busy());")
    L.append("}")
    L.append("")
    L.append("/* PAD-675: \"another mode runs\": one of ours, or a battle, multiball or mode of the game's. While it does, this")
    L.append(" * one's light is down, as David's machine showed a lit mode's inserts still flashing through a battle. The")
    L.append(" * game's own count only for a mode that waits them out: one that stacks with them plays on beside them */")
    L.append("UNUSED static int out_of_play(void)")
    L.append("{")
    L.append("    return !run.on && (pm_other_running() || ((WAITS_OUT_MULTIBALL || GAME_MODES) && game_busy() != 0));")
    L.append("}")
    L.append("")
    L.append("/* PAD-680: its idle scripts count, note and show their meter through the game's battles - on Godzilla one runs")
    L.append(" * most of a ball, and a mode that counted nothing then never showed its progress. Only another of ours")
    L.append(" * stops them */")
    L.append("UNUSED static int counting(void)")
    L.append("{")
    L.append("    return !run.on && !pm_other_running();")
    L.append("}")
    L.append("")
    L.append("static void start(const char *why, int counted);")
    L.append("static void end(const char *why);")
    L.append("static void end_now(const char *why);")
    if g.lit:
        L.append("")
        L.extend(_lit_c(g).rstrip("\n").split("\n"))
    elif g.lit_asked:
        L.append("UNUSED static int lit_now(void) { return 0; }   /* no Light the mode at block: never lit */")
    if g.unlight_own and not g.lit:
        L.append("UNUSED static void unlight_mode(void) { }   /* no Light the mode at block: never lit */")
    L.append("")
    L.append("static void on_mode_start(void)")
    L.append("{")
    L.extend(scripts_of("mode_start") or ["    /* no script */"])
    L.append("}")
    L.append("")
    L.append("static void on_mode_end(void)")
    L.append("{")
    L.extend(scripts_of("mode_end") or ["    /* no script */"])
    L.append("}")
    L.append("")
    L.append("/* counted: a block asked (the tab's Start mode now does not wait for the game's modes) */")
    L.append("static void start(const char *why, int counted)")
    L.append("{")
    L.append("    if (run.on || !pm_in_game()) return;")
    L.append("    if (drain_hold || drain_long) {   /* PAD-622: the last drain's TOTAL goes before it starts again */")
    L.append("        drain_hold = drain_long = 0;")
    L.append("        end_now(\"ball ended\");")
    L.append("    }")
    L.append("    if ((WAITS_OUT_MULTIBALL || GAME_MODES) && counted) {   /* it waits: the next Start the mode starts it */")
    L.append("        static unsigned long said_at;")
    L.append("        const char *what = game_busy();")
    L.append("        if (what) {")
    L.append("            if (!said_at || pm_ms() - said_at >= 10000)")
    L.append('                pm_log("not started (%s): %s is running - still ready: the next Start the mode starts it", why, what);')
    L.append("            said_at = pm_ms() ? pm_ms() : 1;")
    L.append("            return;")
    L.append("        }")
    L.append("    }")
    L.append("    if (!pm_begin()) return;          /* another of our modes is running */")
    L.append("    pm_running_name(MODE_NAME);")
    L.append("    if (DISPLAY_PRIORITY) pm_display_priority(DISPLAY_PRIORITY);   /* first: before the screen */")
    L.append("    if (GAME_MODES == 2) {            /* the game's modes it holds off cannot start while it runs */")
    L.append("        pm_block_list(BLOCK_IDS, BLOCK_N);")
    L.append("        pm_block_rules_keep_names(KEEP_RULES);")
    L.append("        if (pm_block_game_modes(1))")
    L.append("            pm_log(\"isolated: the game's modes it holds off cannot start while it runs (any other "
             "starting ends it)\");")
    L.append("        else")
    L.append("            pm_log(\"isolated: this port cannot hold the game's modes off - it gives way to them\");")
    L.append("    } else if (GAME_MODES == 1) {")
    L.append("        pm_log(\"isolated: gives way - one of the game's modes starting ends it\");")
    L.append("    }")
    L.append("    run.own_mball = 0;")
    L.append("    run.on = 1;")
    L.append("    run.player = pm_player();")
    if g.lit:
        L.append("    lit_started(run.player);          /* PAD-503: begun, however it began: its light is out */")
    L.append("    run.ticks_left = RUN_SECONDS * TICKS_PER_SECOND;")
    L.append("    run.seconds_shown = RUN_SECONDS;")
    L.append("    run.elapsed = 0;")
    L.append("    run.shots = 0;")
    L.append("    run.total = 0;")
    if has_bar:
        L.append("    bar_max = run.ticks_left;")
        L.append("    bar_hold = 0;")
        L.append("    bar_show(1);                      /* PAD-521: its name in the game's bar */")
    if g.mech:
        L.append("    scoop_next = 0;")
        L.append("    clock_hold = 0;                   /* PAD-621 */")
    L.append("    hide_ticks = 0;")
    L.append('    reset_mode();')
    if watch:
        L.append("    screen_away = 0;")
    L.append("    if (screen) {")
    L.append("        words(MODE_NAME, 0, 0);")
    L.append("        pm_show(screen, 1);")
    L.append("        if (WORDS_ONLY) flash_ticks = %d * TICKS_PER_SECOND / 1000;   /* PAD-521: its name over the intro */"
             % WORDS_NAME_MS)
    L.append("    }")
    if has_hud:
        L.append("    {")
        L.append("        int k;")
        L.append("        for (k = 0; k < 3; k++) {")
        L.append('            kit_copy(hud_val[k], sizeof hud_val[k], "0");')
        L.append("            kit_copy(hud_sub[k], sizeof hud_sub[k], HUD_SUB[k]);")
        L.append("            kit_copy(hud_lab[k], sizeof hud_lab[k], HUD_LABEL[k]);")
        L.append("        }")
        L.append("    }")
        L.append("    hud_level = 0;")
        L.append("    kit_hud_pips(&hud, HUD_GAUGE);      /* the build's count: any more are hidden */")
        L.append("    kit_hud_begin(&hud, MODE_NAME, HUD_LINE);")
    if media:
        L.append("    pa_load(&own);                    /* its own sounds' priorities, and its music */")
        L.append("    own.running = 1;")
        L.append("    if (own.loaded) {")
        L.append("        pa_priorities(&own);")
        L.append("        pa_music_begin(&own);")
        L.append("    }")
    L.append('    pm_log("START (%s): player %u", why, run.player);')
    L.append("    on_mode_start();")
    if has_info:
        L.append("    if (run.on) info_show(1);          /* PAD-547: what the start's blocks set, on the first frame */")
    if has_hud:
        L.append("    if (run.on) hud_show();            /* what the start's blocks set, on the first frame */")
    L.append("}")
    L.append("")
    L.append("static void end(const char *why)")
    L.append("{")
    L.append("    if (!run.on || ending) return;    /* an End block in When the mode ends */")
    L.append("    ending = 1;")
    L.append("    on_mode_end();")
    L.append("    ending = 0;")
    L.append("    run.on = 0;")
    if media:
        L.append("    loop_waiting = 0;")
        if note_cue:
            L.append("    if (!looping) cover_total();       /* PAD-658: nothing loops: its cover clip behind the TOTAL */")
        L.append("    looping = 0;                      /* PAD-658: the runtime keeps the loop behind the TOTAL it holds, then")
        L.append("                                       * the city again (at once for an end that holds nothing) */")
        L.append("    pa_end(&own);                     /* its music fades, the game's comes back */")
    if g.shows:
        L.append("    show_last_pass();                 /* PAD-646: a show running until the mode ends finishes its pass */")
    L.append("    unlight_all();                    /* a show it ends with paints on, then hands back */")
    if has_info:
        L.append("    info_show(0);                     /* PAD-547: its line goes with it */")
    L.append("    total_due = screen && screen_words ? award_ticks%s : 0;   /* PAD-574: an Award it ended on, then its TOTAL */"
             % ("" if has_hud else " + award_next_ticks"))
    L.append("    award_ticks = 0;")
    if has_bar:
        L.append("    bar_show(0);                      /* PAD-521: the bar full, kept through its total */")
        L.append("    bar_hold = ENDING_NOW_MS / 1000 * TICKS_PER_SECOND + total_due;")
        L.append("    ended_begun = pm_begun();")
    L.append("    if (screen) {")
    L.append("        flash_ticks = 0;")
    L.append("        ended_begun = pm_begun();")
    if watch:
        L.append("        if (screen_away) pm_show(screen, 1);")
        L.append("        screen_away = 0;")
    L.append("        if (!total_due) total_show();")
    L.append("    }")
    if has_hud:
        L.append("    {                                 /* the TOTAL, as the examples end */")
        L.append("        char n[32];")
        L.append("        int k;")
        L.append('        kit_hud_title(&hud, end_title[0] ? end_title : MODE_NAME " TOTAL", end_line[0] ? end_line : "");')
        L.append("        end_title[0] = end_line[0] = 0;")
        L.append("        for (k = 0; k < 3; k++) kit_hud_counter(&hud, k, 0, 0, 0);")
        L.append("        kit_hud_timer(&hud, -1);")
        L.append("        if (!HUD_METER) kit_hud_gauge(&hud, -1, 0);   /* PAD-658: a meter stays, following on */")
        L.append('        kit_hud_award(&hud, ENDING_HOLD_MS, kit_num(n, sizeof n, run.total), " ");')
        L.append("        kit_hud_hide_in(&hud, ENDING_HOLD_MS);")
        L.append("    }")
    L.append("    if (GAME_MODES == 2) pm_block_game_modes(0);   /* the game's modes may start again */")
    L.append("    /* the total keeps the display watched for its moment on its HUD or its own screen (the kit's")
    L.append("     * kit_end_after, pm_end_holding); a drain or the game hands it back at once (end_now) */")
    L.append("    if (!(DISPLAY_PRIORITY && %s && pm_end_holding(ENDING_HOLD_MS + total_due * 1000 / TICKS_PER_SECOND))) {"
             % ("1" if has_hud else "screen"))
    L.append("        pm_display_priority(0);")
    L.append("        pm_end();")
    L.append("    }")
    L.append('    pm_log("END (%s): %u scores, total %llu", why, run.shots, (unsigned long long)run.total);')
    L.append("    end_clip = 0;")
    L.append("}")
    L.append("")
    L.append("/* ended by a drain, a tilt's drain, the game moving on or one of its modes beginning: the game's own")
    L.append(" * screen comes at once, so its display is handed back and its total does not stay over it (the")
    L.append(" * kit's kit_end_now) */")
    L.append("static void end_now(const char *why)")
    L.append("{")
    L.append("    end(why);")
    L.append("    hide_ticks = 0;")
    L.append("    total_hide();                     /* PAD-574: its TOTAL, and an Award waiting for it, go too */")
    if has_bar:
        L.append("    bar_hold = 0;")
        L.append("    pm_status_bar(0, 0, 0);           /* PAD-521: the game's display comes at once */")
    L.append("    if (screen) pm_show(screen, 0);")
    if has_info:
        L.append("    info_show(0);")
    L.append("    if (DISPLAY_PRIORITY) pm_display_priority(0);")
    if has_hud:
        L.append("    kit_hud_drop_now();")
    L.append("}")
    L.append("")
    if challenge_names:                     # PAD-615
        L.append("/* PAD-615: the game's challenges this mode takes the place of (a Player Challenge game with one picked")
        L.append(" * starts its script instead of the game's own challenge), claimed as it loads */")
        L.append("static const char *const CHALLENGE_NAMES[%d] = { %s };   /* \"\" = a new one of its own */"
                 % (len(challenge_names), ", ".join(_c_str("" if n == CHALLENGE_NEW else n) for n in challenge_names)))
        L.append("static const int CHALLENGE_LAUNCH[%d] = { %s };   /* PAD-643: 0 its start clip, -1 the player, ms */"
                 % (len(challenge_names), ", ".join(str(v) for v in challenge_launch)))
        L.append("static int CHALLENGE_AT[%d];" % len(challenge_names))
        L.append("static volatile unsigned challenge_picked;   /* set on the game's thread, run on the tick */")
        L.append("")
        L.append("static int on_challenge(unsigned at)")
        L.append("{")
        L.append("    int k;")
        L.append("    for (k = 0; k < %d; k++)" % len(challenge_names))
        L.append("        if (CHALLENGE_AT[k] == (int)at) {")
        L.append("            challenge_picked |= 1u << k;")
        L.append("            return 1;                 /* the game's own challenge does not start */")
        L.append("        }")
        L.append("    return 0;")
        L.append("}")
        L.append("")
    L.append("/* ---- the callbacks ---- */")
    L.append("static void on_init(void)")
    L.append("{")
    L.append("    int i;")
    L.append("    uint64_t mask;")
    L.append("    for (i = 0; i < %d; i++)" % len(g.shots))
    L.append("        S[i] = SHOT_NAMES[i] && SHOT_NAMES[i][0] ? pm_shot(SHOT_NAMES[i]) : 0;")
    L.append("    for (i = 0; i < %d; i++)" % len(g.events))
    L.append("        E[i] = EVENT_NAMES[i] && EVENT_NAMES[i][0] ? pm_event(EVENT_NAMES[i]) : -1;")
    L.append("    for (i = 0; pm_shot_at(i, &mask); i++)")
    L.append("        named |= mask;")
    L.append('    pm_log("ready on %%s %%s: %%d shot(s) named by the blocks", pm_game(), pm_version(), %d);'
             % len(g.shots))
    if media:
        L.append("    pa_load(&own);")
    for name in g.wizard_names:                     # PAD-457: the game's own lighting leaves them to this mode
        L.append("    pm_game_wizard_claim_named(%s);" % _c_str(name))
    if challenge_names:                             # PAD-615
        L.append("    for (i = 0; i < %d; i++) {" % len(challenge_names))
        L.append("        if (!CHALLENGE_NAMES[i][0]) {     /* its own, on the game's start menu under its name */")
        L.append("            CHALLENGE_AT[i] = pm_challenge_add(MODE_NAME, on_challenge);")
        L.append("            if (CHALLENGE_AT[i] < 0) pm_log(\"no challenge of its own: this game's start menu is not ours to add to\");")
        L.append("            else pm_challenge_launch((unsigned)CHALLENGE_AT[i], CHALLENGE_LAUNCH[i]);   /* PAD-643 */")
        L.append("            continue;")
        L.append("        }")
        L.append("        CHALLENGE_AT[i] = pm_challenge_named(CHALLENGE_NAMES[i]);")
        L.append("        if (CHALLENGE_AT[i] < 0 || !pm_challenge_claim((unsigned)CHALLENGE_AT[i], on_challenge))")
        L.append('            pm_log("the challenge %s is not one this game lets a mode take the place of", CHALLENGE_NAMES[i]);')
        L.append("        else {")
        L.append("            pm_challenge_title((unsigned)CHALLENGE_AT[i], MODE_NAME);   /* the start menu shows its name */")
        L.append("            pm_challenge_launch((unsigned)CHALLENGE_AT[i], CHALLENGE_LAUNCH[i]);   /* PAD-643 */")
        L.append("        }")
        L.append("    }")
    L.append("    (void)E; (void)EVENT_NAMES; (void)HIT_OF; (void)H;")
    L.append("}")
    L.append("")
    L.append("static void find_screen(void)")
    L.append("{")
    L.append("    static unsigned tries;")
    L.append("    if (screen || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;")
    L.append('    screen = pm_node("hud", SCREEN_NODE);')
    L.append("    if (!screen) return;")
    L.append('    screen_words = pm_text("hud", SCREEN_TEXT);')
    L.append("    if (!run.on) pm_show(screen, 0);")
    L.append("}")
    L.append("")
    if words_only:
        L.append("static void find_total(void)          /* PAD-574 */")
        L.append("{")
        L.append("    static unsigned tries;")
        L.append("    if (total || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;")
        L.append('    total = pm_node("hud", TOTAL_NODE);')
        L.append("    if (!total) return;")
        L.append('    total_words = pm_text("hud", TOTAL_TEXT);')
        L.append('    total_name = pm_node("hud", TOTAL_NAME_NODE);')
        L.append('    total_name_words = total_name ? pm_text("hud", TOTAL_NAME_TEXT) : 0;')
        L.append("    pm_show(total, 0);                /* built shown, as every screen is */")
        L.append("    if (total_name) pm_show(total_name, 0);")
        L.append("}")
        L.append("")
    if has_info:
        L.append("static void find_info(void)           /* PAD-547 */")
        L.append("{")
        L.append("    static unsigned tries;")
        L.append("    if (info || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;")
        L.append('    info = pm_node("hud", INFO_NODE);')
        L.append("    if (!info) return;")
        L.append('    info_words = pm_text("hud", INFO_TEXT);')
        L.append("    info_up = 1;                      /* built shown, as every screen is */")
        L.append("    info_now[0] = 0;")
        L.append("    if (!run.on) info_show(0);")
        L.append("}")
        L.append("")
    L.append("static void on_shot(uint64_t shot)")
    L.append("{")
    L.append("    unsigned p = pm_player();")
    L.append("    int i, was_on = run.on;           /* the mode's state before this shot */")
    L.append("    int idle;")
    L.append("    if (!pm_in_game() || p < 1 || p > 4) return;")
    L.append("    /* PAD-675: while the mode is not running, and no other of ours is, its idle scripts count toward it -")
    L.append("     * through the game's battles too (PAD-680); while another of ours runs nothing counts, notes or shows */")
    L.append("    idle = !was_on && counting();")
    L.append("    (void)idle;")
    switch_scripts = scripts_of("switch")
    if switch_scripts:
        L.append("    if (shot & 1ull) {                /* PAD-675: a playfield switch was hit (its 0x1 dispatch) */")
        L.extend("    " + line if line else line for code in switch_scripts for line in code.split("\n"))
        L.append("    }")
    L.append("    if (!(shot & named)) return;      /* a switch's 0x1 dispatch, not a shot */")
    L.append("    for (i = 0; i < %d; i++)" % len(g.hits))
    L.append("        if (S[(int)HIT_OF[i]] & shot) H[i][p]++;")
    L.append("    (void)i; (void)was_on;")
    if g.lit:
        L.append("    lit_shot(shot);                   /* PAD-503: the shot it is lit at starts it */")
        L.append("    if (!was_on && run.on) return;    /* PAD-658: and is that alone, not a shot \"while it is not running\" too */")
    L.extend(scripts_of("shot", "any_shot"))
    L.append("}")
    L.append("")
    L.append("static void on_event(unsigned id)")
    L.append("{")
    L.append("    int was_on = run.on;")
    L.append("    if (!pm_in_game()) return;")
    L.append("    (void)was_on; (void)id;")
    L.extend(scripts_of("event"))
    L.append("}")
    L.append("")
    L.append("static void on_tick(void)")
    L.append("{")
    L.append("    unsigned seconds = 0;")
    L.append("    int in_game = pm_in_game();")
    L.append("    find_screen();")
    L.append("    if (drain_hold && !pm_ball_end_holding()) {   /* PAD-622: the game's end of ball goes on: so does its TOTAL */")
    L.append("        drain_hold = drain_long = 0;")
    L.append("        end_now(\"ball ended\");")
    L.append("    }")
    if words_only:
        L.append("    find_total();")
    if has_info:
        L.append("    find_info();")
    if has_hud:
        L.append("    kit_hud_tick(&hud);                /* finds it, expires an award, writes what changed */")
    if note_cue:
        L.append("    note_loop_tick();                 /* PAD-658: a note's loop goes with it */")
    if media:
        L.append("    own_tick();                       /* every tick: an end call outlives the mode */")
    if g.shows:
        L.append("    show_tick();                      /* every tick: an end show outlives the mode */")
    L.append("    if (new_game()) {                 /* every player's \"each game\" values, and no timer runs on */")
    L.append("        unsigned p, v;")
    L.append("        for (p = 0; p < 5; p++) {")
    L.append("            for (v = 0; v < %d; v++) H[v][p] = 0;" % nhits)
    for hm in hit_moves:
        L.append("            %s[p] = 0;" % hm)
    for i, (_n, reset) in enumerate(g.var_names):
        L.append("            %s = 0;" % g.var(i, "p"))
    if g.lit:
        L.append("            if (lit_as[p]) pm_log(\"a new game: player %u's light is out\", p);")
        L.append("            lit_as[p] = 0;            /* PAD-503: no one is lit at the start of a game */")
    L.append("        }")
    L.append("        for (v = 0; v < %d; v++) T[v] = 0;" % ntimers)
    L.append("    }")
    if g.lit:
        L.append("    lit_tick();                       /* PAD-503: the player up's light while it is not running */")
    L.append("    if (++poll % 30 == 0) {            /* the tab's Start mode now / End mode */")
    L.append('        if (pm_trigger("%s.start")) start("trigger file", 0);' % slug)
    L.append('        if (pm_trigger("%s.stop")) end("trigger file");' % slug)
    L.append("    }")
    L.append("    if ((hide_ticks || total_due) && !run.on && pm_begun() != ended_begun) {   /* PAD-413: another mode began */")
    L.append("        hide_ticks = 0;")
    L.append("        total_hide();")
    L.append('        pm_log("its total gives way - another mode began");')
    L.append("    }")
    if has_bar:
        L.append("    if (bar_hold && !run.on && (pm_begun() != ended_begun || --bar_hold == 0)) {")
        L.append("        bar_hold = 0;")
        L.append("        pm_status_bar(0, 0, 0);       /* PAD-521: the bar back (not if another mode of ours has it) */")
        L.append("    }")
    L.append("    if (hide_ticks && --hide_ticks == 0 && !run.on) total_hide();")
    if not has_hud:
        L.append("    if (award_next_ticks && (!total_due || run.on)) award_next_ticks = 0;")
        L.append("    if (award_next_ticks && total_due == award_next_ticks) {   /* PAD-574: the next Award's turn */")
        L.append("        if (screen_words) pm_set_text(screen_words, award_next);")
        L.append("        award_next_ticks = 0;")
        L.append("    }")
    L.append("    if (total_due && !run.on && --total_due == 0) total_show();   /* PAD-574: the Award it ended on has shown */")
    challenge_scripts = scripts_of("challenge")
    if challenge_scripts:                           # PAD-615: the challenge picked at the ball's start
        L.append("    if (challenge_picked) {")
        L.append("        unsigned picked = challenge_picked;")
        L.append("        challenge_picked = 0;")
        L.append("        if (in_game) {")
        if g.mech:
            L.append("            ball_starting = 1;            /* PAD-621: no hold that waits for a ball at the post */")
        L.extend("        " + line if line else line for code in challenge_scripts for line in code.split("\n"))
        if g.mech:
            L.append("            ball_starting = 0;")
        L.append("        }")
        L.append("    }")
    timer_scripts = scripts_of("timer_done")
    if timer_scripts:
        L.append("    if (in_game) {                    /* the timers that ran out, then their scripts */")
        L.append("        int due[%d], t;" % ntimers)
        L.append("        unsigned long now = pm_ms();")
        L.append("        for (t = 0; t < %d; t++) {" % ntimers)
        L.append("            due[t] = T[t] && (long)(now - T[t]) >= 0;")
        L.append("            if (due[t]) T[t] = 0;")
        L.append("        }")
        L.extend("    " + line if line else line for code in timer_scripts for line in code.split("\n"))
        L.append("    }")
    if has_hud and gauge_live is not None and hud["gauge"]["meter"]:
        L.append("    if (!run.on) {                    /* PAD-658: the gauge as a meter while it is not running */")
        L.append("        if (in_game && counting()) {   /* PAD-675: hidden while another of ours runs (PAD-680) */")
        L.append("            hud_level = %s;" % gauge_live)
        L.append("            gauge_now(hud_level, 1);")
        L.append("        } else kit_hud_meter(&hud, -1, 0);")
        L.append("    }")
    L.append("    sec_changed = 0;")
    L.append("    if (!run.on) return;")
    L.append("    if (!in_game || pm_player() != run.player) {")
    L.append('        end_now("the game moved on");')
    L.append("        return;")
    L.append("    }")
    L.append("    if (run.own_mball && pm_balls_in_play() < 2) run.own_mball = 0;   /* its multiball is over */")
    L.append("    if (GAME_MODES && pm_aside() && !(run.own_mball && pm_aside() == (int)PM_STOCK_MULTIBALL)) {")
    L.append("        end_now(\"the game's own mode began\");   /* its screen and HUD go at once, as a tilt's */")
    L.append("        return;")
    L.append("    }")
    L.append("    run.elapsed++;")
    L.append("    if (RUN_SECONDS%s) {" % (" && !clock_held()" if g.mech else ""))   # PAD-621: a hold_wait stops it
    L.append("        if (run.ticks_left) run.ticks_left--;")
    L.append("        seconds = secs_left();")
    L.append("        if (seconds != run.seconds_shown) {")
    L.append("            run.seconds_shown = seconds;")
    L.append("            sec_changed = 1;")
    L.append("        }")
    L.append("    }")
    L.append("    (void)seconds;")
    L.append("    if (WORDS_ONLY && flash_ticks && --flash_ticks == 0 && screen) pm_show(screen, 0);   /* PAD-521 */")
    L.append("    if (award_ticks) award_ticks--;")
    if has_bar:
        L.append("    bar_show(1);                      /* PAD-521: the clock along the bar */")
    L.append("    lamps_tick();")
    if g.mech:
        L.append("    scoop_tick();")
    L.extend(scripts_of("every", "seconds_left"))
    L.append("    if (run.on && RUN_SECONDS && run.ticks_left == 0)")
    L.append('        end("time ran out");')
    if watch:
        L.append("    if (run.on && screen) {           /* its screen out of the way of the game's (PAD-375) */")
        L.append("        int away = pm_display_covered() || pm_aside() || pm_game_words();   /* PAD-662: any screen of the game's */")
        L.append("        if (away != screen_away) {")
        L.append("            pm_show(screen, !away && (!WORDS_ONLY || flash_ticks));")
        L.append("            screen_away = away;")
        L.append("        }")
        L.append("    }")
    if has_hud:
        L.append("    if (run.on) hud_show();")
    if has_info:
        L.append("    if (run.on) info_show(!pm_display_covered() && !pm_aside() && !pm_game_words());   /* PAD-547, PAD-662 */")
    L.append("}")
    L.append("")
    L.append("/* PAD-622: a drain while it runs ends it as its clock would - an Award it ended on, then its TOTAL - and the")
    L.append(" * game's end of ball (its bonus, the next ball, a challenge game's end) waits for that, as it does for the")
    L.append(" * game's own mini-wizards' totals; a drain while its total still shows waits out the rest. Where the game cannot")
    L.append(" * wait (a tilted ball, a port without the hold) it all goes at once, as before. */")
    L.append("static void drain_end(void)")
    L.append("{")
    L.append("    unsigned ms;")
    L.append("    /* PAD-675: not running, and nothing of its own on the glass: the drain is another's. Its end_now here gave")
    L.append("     * up the display priority and dropped the HUD under the mode whose TOTAL the drain was showing */")
    L.append("    if (!run.on && !total_due && !hide_ticks) return;")
    L.append("    drain_long = run.on && pm_can(PM_CAN_BALL_END_HOLD);   /* its TOTAL as long as the game's own then */")
    if has_hud:
        L.append("    ms = drain_long ? DRAIN_TOTAL_MS : 0;   /* the HUD's TOTAL */")
    else:
        L.append("    ms = 0;")
    L.append("    end(\"ball ended\");")
    L.append("    if (screen && (total_due || hide_ticks)) {   /* an Award it ended on, then its TOTAL; or the rest of one */")
    L.append("        unsigned t = total_due ? total_due + ENDING_NOW_MS / 1000 * TICKS_PER_SECOND : hide_ticks;")
    L.append("        if (t * 1000 / TICKS_PER_SECOND > ms) ms = t * 1000 / TICKS_PER_SECOND;")
    L.append("    }")
    L.append("    if (ms && pm_ball_end_hold(ms)) {")
    L.append("        drain_hold = 1;                 /* after the ask: a tick between sees the hold, not its end */")
    L.append('        pm_log("its TOTAL at the drain: the end of ball waits %u ms", ms);')
    L.append("        return;")
    L.append("    }")
    L.append("    drain_long = 0;")
    L.append("    end_now(\"ball ended\");")
    L.append("}")
    L.append("")
    L.append("static void on_ball_end(void)")
    L.append("{")
    L.append("    unsigned t;")
    L.append("    for (t = 0; t < %d; t++) T[t] = 0;   /* a ball ending stops every timer */" % ntimers)
    L.extend(scripts_of("ball_end"))
    L.append("    if (ENDS_ON_DRAIN) drain_end();")
    if media:
        L.append("    looping = 0;                      /* no backdrop outlives the ball */")
    if note_cue:
        L.append("    note_looping = 0;")
    L.append("    {")
    L.append("        unsigned p = P(), v;")
    L.append("        for (v = 0; v < %d; v++) H[v][p] = 0;" % nhits)
    for hm in hit_moves:
        L.append("        %s[p] = 0;" % hm)
    L.append('        reset_ball();')
    if g.lit:
        L.append("        lit_player = 0;               /* PAD-503: the next ball holds its light again */")
    L.append("    }")
    L.append("}")
    L.append("")
    L.append("static const struct pm_mode %s_mode = {" % ident)
    L.append("    .name = MODE_NAME,")
    L.append("    .init = on_init,")
    L.append("    .tick = on_tick,")
    L.append("    .shot = on_shot,")
    L.append("    .ball_end = on_ball_end,")
    L.append("    .event = on_event,")
    L.append("};")
    L.append("PM_REGISTER(%s_mode);" % ident)
    return "\n".join(L) + "\n"


#: PAD-503: a new game as the SDK tells one (MODE_SDK.md "What marks a new game"; mode_file.c and the kit's
#: kit_new_game). pm_in_game() rising alone was the blocks' test, and James Bond LE 1.06 ends play at the end of each
#: of its multiballs and wizard modes (0x3f79bc: the mode mask's busy bits 0x202, until the ball ends), so the next
#: ball read as a new game: the mode's light, its "each game" values and its timers were wiped
_NEW_GAME_C = """/* A new game: player 1's score falling to 0, or pm_in_game() rising while it is 0; seen once, then not again until
 * player 1 scores or pm_in_game() falls (MODE_SDK.md "What marks a new game"). pm_in_game() rising alone is not one: a
 * game can end play on a ball and carry on (James Bond, at the end of each of its multiballs and wizard modes). */
static int new_game(void)
{
    static int seen, was_in, was_zero, armed;
    int in = pm_in_game(), zero = pm_score(1) == 0, fresh = 0;
    if (!seen) {
        seen = armed = 1;
        was_in = in;
        was_zero = zero;
        return 0;
    }
    if (!zero || (was_in && !in)) armed = 1;  /* player 1 scored, or the game ended */
    if (zero && armed && (!was_zero || (in && !was_in))) {
        armed = 0;
        fresh = 1;
    }
    was_in = in;
    was_zero = zero;
    return fresh;
}
"""

#: the C that holds the shots' lights (PAD-376); %(n)d shots named, LIT sized %(size)d; PAD-598: and %(nl)d of the
#: game's lights the blocks name (LAMP_NAMES), in LIT after the shots
_LAMPS_C = """/* ---- the shots' lights the blocks hold (PAD-376): kept, so a light show gives them back when
 * it is over, and a blink that hurries follows the clock. PAD-598: after the shots, the game's own lights a block
 * names (an insert, a GI string, a flasher), held by name ---- */
#define N_SHOTS   %(n)d
#define N_LIGHTS  (N_SHOTS + %(nl)d)
UNUSED static const char *const LAMP_NAMES[%(lsize)d] = {%(lamps)s};
#define RATE_MIN  %(lo)d                     /* a blink's, pulse's or chase's pace, ms */
#define RATE_MAX  %(hi)d
UNUSED static struct { unsigned rgb, ms, sent; int pattern, hurry, on; } LIT[%(size)d];

/* the kit's kit_hurry_ms: slow with most of the time left, faster as it runs down, a flicker in
 * the last three seconds */
UNUSED static unsigned hurry_ms(void)
{
    unsigned long left = (unsigned long)run.ticks_left * 1000u / TICKS_PER_SECOND;
    unsigned long total = (unsigned long)RUN_SECONDS * 1000u;
    if (!run.on || !RUN_SECONDS) return 500;
    if (left * 3 > total * 2) return 700;
    if (left * 3 > total) return 400;
    if (left > 3000) return 200;
    return 100;
}

UNUSED static void lamp_send(int i)
{
    unsigned ms;
    if (i < 0 || i >= N_LIGHTS || (i < N_SHOTS && !S[i]) || !LIT[i].on || SHOWING) return;
    ms = LIT[i].hurry ? hurry_ms() : LIT[i].ms;
    if (i < N_SHOTS) pm_lamp_shot(S[i], LIT[i].rgb, LIT[i].pattern, ms);
    else pm_lamp_set(LAMP_NAMES[i - N_SHOTS], LIT[i].rgb, LIT[i].pattern, ms);
    LIT[i].sent = ms;
}

/* a shot's inserts lit, or one of the game's lights; the same light again is left alone (a blink keeps its beat) */
UNUSED static void light(int i, unsigned rgb, int pattern, long long ms, int hurry)
{
    if (i < 0 || i >= N_LIGHTS) return;
    if (!run.on && !ending) return;   /* PAD-658: after the end (a timer still counting) it would be held for good */
    if (pattern == PM_LAMP_SOLID || hurry) ms = 0;
    else if (ms < RATE_MIN) ms = RATE_MIN;
    else if (ms > RATE_MAX) ms = RATE_MAX;
    if (LIT[i].on && LIT[i].rgb == rgb && LIT[i].pattern == pattern && LIT[i].ms == (unsigned)ms
        && LIT[i].hurry == hurry) return;
    LIT[i].rgb = rgb;
    LIT[i].pattern = pattern;
    LIT[i].ms = (unsigned)ms;
    LIT[i].hurry = hurry;
    LIT[i].on = 1;
    lamp_send(i);
}

UNUSED static void unlight(int i)
{
    if (i < 0 || i >= N_LIGHTS) return;
    LIT[i].on = 0;
    if (i >= N_SHOTS) pm_lamp_release(LAMP_NAMES[i - N_SHOTS]);
    else if (S[i]) pm_lamp_release_shot(S[i]);
%(forget)s}

static void unlight_all(void)
{
    int i;
    for (i = 0; i < N_LIGHTS; i++) LIT[i].on = 0;
    pm_lamp_release_all();
%(forget)s}

UNUSED static void relight_all(void)                /* after a show: every light the blocks hold */
{
    int i;
    for (i = 0; i < N_LIGHTS; i++) lamp_send(i);
}

static void lamps_tick(void)                        /* a hurrying blink follows the clock */
{
    int i;
    for (i = 0; i < N_LIGHTS; i++)
        if (LIT[i].on && LIT[i].hurry && !SHOWING && hurry_ms() != LIT[i].sent) lamp_send(i);
}
"""


def step_xy(st):
    """PAD-646: where a step centres on the playfield picture: its place's point, or its own (``at`` "xy")."""
    at = PLACES.get(st.get("at"), PLACES["center"])
    if st.get("at") == "xy" and _int_ok(st.get("x"), 0, XY_MAX) and _int_ok(st.get("y"), 0, XY_MAX):
        return int(st["x"]), int(st["y"])
    return at[1], at[2]


def step_c(st):
    """PAD-646: one step as its C table row's fields: ``(fx C name, ms, a, b, x, y, rate, GI C name, blend)``."""
    gi_c = {"keep": "GI_KEEP", "dark": "GI_DARK", "flash": "GI_FLASH"}
    col = [int(str(st.get(k))[1:], 16) if COLOR_RE.match(str(st.get(k) or "")) else 0 for k in ("a", "b")]
    try:
        ms = max(STEP_MS_MIN, min(STEP_MS_MAX, int(st.get("ms"))))
    except (TypeError, ValueError):
        ms = 500
    try:
        rate = max(0, min(FX_RATE_MAX, int(st.get("rate") or 0)))
    except (TypeError, ValueError):
        rate = 0
    try:
        blend = max(0, min(STEP_MS_MAX, int(st.get("blend") or 0)))
    except (TypeError, ValueError):
        blend = 0
    x, y = step_xy(st)
    return FX[st["fx"]][0], ms, col[0], col[1], x, y, rate, gi_c.get(st.get("gi"), "GI_KEEP"), blend


def _show_decls(shows):
    """The C of the light shows' steps (one table per show the blocks run: a ready-made one, a block's own steps,
    or one of the mode's own shows, PAD-646) and their state. ``shows``: ``[{steps, name, repeat}]``."""
    out = ["/* ---- light shows (PAD-376): the kit's kit_show (intricate_kit.h). A show is a few STEPS,",
           " * each a pattern over the playfield's inserts by their PLACE (the port's \"at X,Y\": x 0-300",
           " * across, y 0-600 down) for some ms, in its two colors; the GI strings follow each step. A",
           " * port with no placed inserts runs a show on the GI only. PAD-646: a step may BLEND in from",
           " * the one before over its first ms, and a show may run several times, or until the mode",
           " * ends (repeat 0: the pass it is in finishes as the mode ends). ---- */",
           "enum { %s };" % ", ".join(c for c, _w in FX.values()),
           "#define GI_KEEP   0                       /* the GI does what the game says */",
           "#define GI_DARK   1                       /* the GI off: only the show lights the playfield */",
           "#define GI_FLASH  2                       /* the GI flashing white with a strobe */",
           "struct fx_step { int fx; unsigned ms, a, b; int x, y; unsigned rate; int gi; unsigned blend; };"]
    for n, s in enumerate(shows):
        steps = s["steps"] if isinstance(s, dict) else s
        out.append("static const struct fx_step SHOW_%d[] = {" % n)
        for st in steps:
            fx, ms, a, b, x, y, rate, gi, blend = step_c(st)
            where = PLACES[st["at"]][0] if st.get("at") in PLACES else PLACES["center"][0]
            out.append("    { %s, %d, 0x%06xu, 0x%06xu, %d, %d, %d, %s, %d },   /* %s, at %s */" % (
                fx, ms, a, b, x, y, rate, gi, blend, FX[st["fx"]][1], where))
        out.append("};")
    out += ["#define SHOW_LAMPS 256",
            "static struct {",
            "    const struct fx_step *steps, *prev;   /* prev: the step before the one on (a blend's), 0 = none */",
            "    const char *name;",
            "    int n, step, on, left, forever, gi[8], n_gi, placed;",
            "    unsigned long t0, step_t0;",
            "    unsigned seed;",
            "} show;",
            "#define SHOWING show.on",
            ""]
    return out


#: the light-show engine: intricate_kit.h's kit_show, on the lights above (relight_all at its end)
_SHOW_C = r"""static unsigned fx_mix(unsigned a, unsigned b, int f256)       /* a..b by f/256 */
{
    int k, out = 0;
    if (f256 < 0) f256 = 0;
    if (f256 > 256) f256 = 256;
    for (k = 0; k < 3; k++) {
        int ca = (int)((a >> (16 - 8 * k)) & 255u), cb = (int)((b >> (16 - 8 * k)) & 255u);
        out |= ((ca + (cb - ca) * f256 / 256) & 255) << (16 - 8 * k);
    }
    return (unsigned)out;
}

static unsigned fx_scale(unsigned c, int f256) { return fx_mix(0, c, f256); }

static unsigned fx_hue(int h)             /* 0..1535 round the color wheel, full brightness */
{
    int s = ((h % 1536) + 1536) % 1536, i = s / 256, f = s % 256;
    switch (i) {
    case 0: return PM_RGB(255, f, 0);
    case 1: return PM_RGB(255 - f, 255, 0);
    case 2: return PM_RGB(0, 255, f);
    case 3: return PM_RGB(0, 255 - f, 255);
    case 4: return PM_RGB(f, 0, 255);
    default: return PM_RGB(255, 0, 255 - f);
    }
}

static unsigned fx_rand(void)
{
    show.seed = show.seed * 1103515245u + 12345u;
    return (show.seed >> 16) & 0x7fffu;
}

static int fx_isqrt(int v)
{
    int r = 0, b = 1 << 14;
    if (v <= 0) return 0;
    while (b > v) b >>= 2;
    while (b) {
        if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
        b >>= 2;
    }
    return r;
}

static int fx_angle(int dx, int dy)        /* atan2 in 1/1536 turns (the hue wheel's) */
{
    int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy, a;
    if (!ax && !ay) return 0;
    a = ax >= ay ? (ay * 192) / (ax ? ax : 1) : 384 - (ax * 192) / (ay ? ay : 1);
    if (dx < 0) a = 768 - a;
    if (dy < 0) a = 1536 - a;
    return a % 1536;
}

static int is_gi(const char *s)            /* a GI string: "GI" a word of its own in the name */
{
    int i;
    for (i = 0; s && s[i] && s[i + 1]; i++)
        if (s[i] == 'G' && s[i + 1] == 'I' && (i == 0 || s[i - 1] < 'A' || s[i - 1] > 'Z')
            && (s[i + 2] < 'A' || s[i + 2] > 'Z'))
            return 1;
    return 0;
}

/* PAD-646: repeat = how many times it runs; 0 = over and over until the mode ends (the pass it is in finishes) */
static void show_start(const struct fx_step *steps, int n, const char *name, int repeat)
{
    int k, cnt = pm_lamp_count();
    show.steps = steps;
    show.prev = 0;
    show.n = n;
    show.name = name;
    show.step = 0;
    show.left = repeat > 0 ? repeat : 1;
    show.forever = repeat <= 0;
    show.on = pm_can(PM_CAN_LAMPS) && n > 0;
    show.t0 = show.step_t0 = pm_ms();
    show.seed = (unsigned)show.t0 | 1u;
    show.n_gi = show.placed = 0;
    for (k = 0; k < cnt && k < SHOW_LAMPS; k++) {
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) show.placed++;
        else if (show.n_gi < 8 && is_gi(pm_lamp_at(k, 0))) show.gi[show.n_gi++] = k;
    }
    if (!show.on) return;
    if (show.forever)
        pm_log("show %s: %d step(s) over %d placed inserts, %d GI string(s), until the mode ends", name, n, show.placed, show.n_gi);
    else if (show.left > 1)
        pm_log("show %s: %d step(s) over %d placed inserts, %d GI string(s), %d times", name, n, show.placed, show.n_gi, show.left);
    else
        pm_log("show %s: %d step(s) over %d placed inserts, %d GI string(s)", name, n, show.placed, show.n_gi);
}

/* the mode ended: a show running until then finishes the pass it is in (one started as it ends plays once) */
static void show_last_pass(void)
{
    show.forever = 0;
    show.left = 1;
}

/* the color of the insert at (x, y) for step st at `t` ms into it */
static unsigned fx_colour(const struct fx_step *st, int x, int y, int idx, unsigned t)
{
    int f = st->ms ? (int)((unsigned long)t * 256u / st->ms) : 256;     /* 0..256 through the step */
    int dx = x - st->x, dy = y - st->y, d, r, w, v;
    unsigned rate = st->rate ? st->rate : 100;
    switch (st->fx) {
    case FX_BURST:
    case FX_IMPLODE:
        d = fx_isqrt(dx * dx + dy * dy);
        r = st->fx == FX_BURST ? f * 700 / 256 : (256 - f) * 700 / 256;
        w = d - r;
        if (w > 0 && w < 60) return fx_scale(st->a, 256 - w * 4);          /* the ring's leading edge */
        if (w <= 0 && w > -140) return fx_mix(st->a, st->b, -w * 256 / 140); /* its wake */
        return w <= 0 ? st->b : 0;
    case FX_SWEEP_UP:
    case FX_SWEEP_DOWN:
        r = st->fx == FX_SWEEP_UP ? 640 - f * 720 / 256 : f * 720 / 256 - 40;
        w = st->fx == FX_SWEEP_UP ? y - r : r - y;
        if (w >= 0 && w < 50) return st->a;
        if (w >= 50) return fx_mix(st->a, st->b, (w - 50) * 3);
        return 0;
    case FX_SWEEP_LR:
    case FX_SWEEP_RL:
        r = st->fx == FX_SWEEP_LR ? f * 380 / 256 - 40 : 340 - f * 380 / 256;
        w = st->fx == FX_SWEEP_LR ? r - x : x - r;
        if (w >= 0 && w < 30) return st->a;
        if (w >= 30) return fx_mix(st->a, st->b, (w - 30) * 4);
        return 0;
    case FX_SPIN:
        v = (fx_angle(dx, dy) - (int)(t * 1536u / (rate * 8u))) % 1536;
        if (v < 0) v += 1536;
        return v < 160 ? st->a : v < 400 ? fx_mix(st->a, st->b, (v - 160) * 256 / 240) : st->b;
    case FX_RAINBOW:
        return fx_hue(fx_angle(dx, dy) + (int)(t * 1536u / (rate * 10u)) + fx_isqrt(dx * dx + dy * dy) * 2);
    case FX_STROBE:
        return (t / rate) % 2 ? st->b : st->a;
    case FX_SPARKLE:
        return ((fx_rand() + (unsigned)idx * 7u) % 100u) < 18u ? st->a : st->b;
    case FX_FIRE:
        v = (int)(fx_rand() % 90u);
        w = (600 - y) * 256 / 600;                                           /* 0 at the flippers */
        return fx_scale(fx_mix(st->b, st->a, w + v - 45), 150 + v);
    case FX_PULSE:
        v = (int)((t % (rate * 2u)) * 512u / (rate * 2u));
        v = v < 256 ? v : 512 - v;
        return fx_mix(st->b, st->a, v);
    case FX_CHASE_RING:
        v = (fx_angle(dx, dy) * 12 / 1536 + 12 - (int)((t / rate) % 12u)) % 12;
        return v == 0 ? st->a : v == 1 ? fx_scale(st->a, 110) : st->b;
    case FX_FADE_OUT:
        return fx_scale(st->a, 256 - f);
    case FX_BOLTS:
        v = (int)((t / rate) % 5u);                                          /* five strikes */
        r = 40 + v * 55 + (int)((unsigned)(y * 13 + v * 71) % 40u) - 20;     /* the bolt's jagged x */
        w = x - r;
        if (w < 0) w = -w;
        return w < 18 && (t % rate) < rate * 2 / 3 ? st->a : st->b;
    /* PAD-646: the editor's patterns */
    case FX_SPIRAL_OUT:
    case FX_SPIRAL_IN:
        /* the burst's ring, its radius turning with the angle round (x, y): one turn = 140 px of radius */
        d = fx_isqrt(dx * dx + dy * dy) + fx_angle(dx, dy) * 140 / 1536;
        r = st->fx == FX_SPIRAL_OUT ? f * 840 / 256 : (256 - f) * 840 / 256;
        w = d - r;
        if (w > 0 && w < 60) return fx_scale(st->a, 256 - w * 4);
        if (w <= 0 && w > -140) return fx_mix(st->a, st->b, -w * 256 / 140);
        return w <= 0 ? st->b : 0;
    case FX_RIPPLE:
        /* rings 140 px apart rolling outwards, one every `rate` ms */
        d = fx_isqrt(dx * dx + dy * dy);
        v = ((d * 256 / 140 - (int)(t * 256u / rate)) % 256 + 256) % 256;
        return fx_mix(st->a, st->b, v < 128 ? v * 2 : (256 - v) * 2);
    case FX_BOUNCE:
        /* a band from the left edge to the right and back over the step */
        v = f < 128 ? f * 2 : (256 - f) * 2;
        r = v * 380 / 256 - 40;
        w = x - r;
        if (w < 0) w = -w;
        if (w < 30) return st->a;
        return fx_mix(st->a, st->b, (w - 30) * 4);
    case FX_FADE_IN:
        return fx_scale(st->a, f);
    case FX_SOLID:
        return st->a;
    }
    return 0;
}

/* PAD-646: the insert's color for the step on, blending in from the step before over the step's first ms (from
 * dark when there is none before it) */
static unsigned fx_blend(const struct fx_step *st, int x, int y, int idx, unsigned t)
{
    unsigned c = fx_colour(st, x, y, idx, t);
    if (st->blend && t < st->blend)
        c = fx_mix(show.prev ? fx_colour(show.prev, x, y, idx, show.prev->ms) : 0u, c, (int)(t * 256u / st->blend));
    return c;
}

/* every tick while the show runs: each placed insert painted, the GI as the step says; at its
 * end every insert goes back to the game and the blocks' own shot lights are sent again */
static void show_tick(void)
{
    const struct fx_step *st;
    unsigned long now = pm_ms();
    unsigned t;
    int k, cnt;
    if (!show.on) return;
    while (show.step < show.n && now - show.step_t0 >= show.steps[show.step].ms) {
        show.step_t0 += show.steps[show.step].ms;
        show.prev = &show.steps[show.step];
        show.step++;
        if (show.step >= show.n && (show.forever || show.left > 1)) {   /* PAD-646: round again */
            if (!show.forever) show.left--;
            show.step = 0;
        }
    }
    if (show.step >= show.n) {
        show.on = 0;
        pm_lamp_release_all();
        relight_all();
        pm_log("show %s: over, %lu ms", show.name, now - show.t0);
        return;
    }
    st = &show.steps[show.step];
    t = (unsigned)(now - show.step_t0);
    cnt = pm_lamp_count();
    for (k = 0; k < cnt && k < SHOW_LAMPS; k++) {
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) pm_lamp_paint(k, fx_blend(st, x, y, k, t));
    }
    for (k = 0; k < show.n_gi; k++) {
        if (st->gi == GI_DARK) pm_lamp_paint(show.gi[k], 0);
        else if (st->gi == GI_FLASH) pm_lamp_paint(show.gi[k], ((t / (st->rate ? st->rate : 100)) % 2) ? 0 : 0xffffffu);
        else pm_lamp_release(pm_lamp_at(show.gi[k], 0));
    }
}
"""


#: PAD-395: the C of a mode whose blocks hold the game's mechanisms. Only a time is asked for: the runtime
#: (pad_mode_runtime.c "the magnet", "the scoop") takes the powers from the coil's own settings, refuses
#: outside the running mode, while the game uses the coil, too soon or too often, and lets go at the
#: mode's end, the ball's, a tilt and the game's; the times are clamped here to its range as well.
#: PAD-418: the game's own light show by its port's name (MODE_SDK.md "The game's own light shows")
_GAME_SHOW_C = r"""/* PAD-418: one of the game's own light shows, by its port's name. The runtime plays it only while the mode runs
 * (or in the first 2 s of its ending), in a game, one at a time, never as the ball ends, and stops it at its length;
 * a game whose port names no such show plays nothing. Each refusal is a line of the runtime's. */
UNUSED static void game_show(const char *name)
{
    if (pm_game_show_named(name)) pm_log("light show: the game's %s", name);
}
"""

#: PAD-436: the game's own mini-wizard by its port's name (MODE_SDK.md "The game's own mini-wizards")
_GAME_WIZARD_C = r"""/* PAD-436: one of the game's own mini-wizards, by its port's name: lit for the game's start shot, or started at once
 * (lit until the game would start one, or while a mode of yours holds the game's modes off). The runtime hands it
 * over in a game, whether this mode runs or not; a game whose port names no such mini-wizard does nothing. Each
 * refusal is a line of the runtime's. The mode claims each one it names as it loads (on_init, PAD-457): the game's
 * own lighting leaves those to it. */
UNUSED static void game_wizard(const char *name, int start)
{
    int r = pm_game_wizard_named(name, start ? PM_WIZARD_START : PM_WIZARD_LIGHT);
    if (r) pm_log("mini-wizard: the game's %s, %s", name, r == PM_WIZARD_STARTED ? "started" : r == PM_WIZARD_WAITING
                  ? "to start the moment nothing of the game's is in its way" : "lit for its start shot");
}
"""

#: PAD-521: the game's own status bar (MODE_SDK.md "The game's status bar")
_BAR_C = r"""/* PAD-521: its name in the game's own status bar (James Bond: the colored bar under the TV), in BAR_RGB, the clock
 * draining along it as the game's own modes show theirs; full through its total, then given back. A game without
 * one shows nothing here. */
static void bar_show(int clock)
{
    int pct = -1;
    if (clock && RUN_SECONDS) {
        if (run.ticks_left > bar_max) bar_max = run.ticks_left;    /* time added: the bar is full again */
        pct = bar_max ? (int)((run.ticks_left * 100u + bar_max - 1) / bar_max) : 0;
    }
    pm_status_bar(MODE_NAME, BAR_RGB, pct);
}
"""

#: PAD-547: the info line under its name; %(value)s = the C of the value it follows
_INFO_C = r"""/* PAD-547: its info line under its name while it runs (James Bond: under the status bar, where the game's own
 * mini-wizards show their SUPER JACKPOT): its words and the value as it changes, written only when it changed. Hidden
 * under a display of the game's and at its end. A card built with no line for it shows nothing. */
static void info_show(int on)
{
    char number[32], line[96];
    long long value = %(value)s;
    int k;
    if (!info) return;
    if (!on) {
        if (info_up) pm_show(info, 0);
        info_up = 0;
        return;
    }
    pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);
    pm_snprintf(line, sizeof line, INFO_FORMAT, number);
    for (k = 0; line[k] && line[k] == info_now[k]; k++)
        ;
    if (line[k] != info_now[k] && info_words) {
        pm_set_text(info_words, line);
        for (k = 0; k < (int)sizeof info_now - 1 && (info_now[k] = line[k]) != 0; k++)
            ;
        info_now[sizeof info_now - 1] = 0;
    }
    if (!info_up) pm_show(info, 1);
    info_up = 1;
}
"""

#: PAD-503: the mode lit at a shot, as the game lights one of its mini-wizards; %(n)d Light the mode at blocks
_LIT_C = r"""/* ---- the mode lit at a shot (PAD-503), as the game lights one of its mini-wizards: for the player up, the shot's
 * inserts and one insert more held in its color while the mode is not running, ball after ball, until that shot
 * starts it (as Start the mode does: it may wait, and stays lit). Starting, however it starts, puts the light out;
 * a new game too. Each player's is their own. ---- */
#define N_LIT_AT %(n)d
static const struct {
    int shot;
    const char *insert;                 /* one insert or several, separated by commas: a chase runs across them */
    unsigned rgb;
    int pattern;
    unsigned ms;
    const char *solid;                  /* PAD-521: one insert more held solid while it is lit (the film's), "" = none */
    unsigned solid_rgb;
} LIT_AT[N_LIT_AT] = {
%(rows)s};
/* per player: 1 + the LIT_AT it is lit as; 0 = not lit. PAD-600: a weak global, so another mode's Put out the light
 * of block can clear it (the linker keeps one) */
__attribute__((weak, visibility("hidden"))) int %(lit)s[5];
#define lit_as %(lit)s
static unsigned lit_player;             /* whose light lit_shown is; 0 = hold it again */
static int lit_waiting;                 /* PAD-556: lit_shown's shot and inserts wait out the game's own mode (only the
                                         * solid one is held) */

UNUSED static int lit_now(void)          /* "the mode is lit", for the player up */
{
    unsigned p = P();
    return p && lit_as[p] != 0;
}

UNUSED static void light_mode(int k)
{
    unsigned p = P();
    if (!p || !pm_in_game() || k < 0 || k >= N_LIT_AT) return;
    if (lit_as[p] != k + 1) pm_log("lit at %%s for player %%u", SHOT_NAMES[LIT_AT[k].shot], p);
    lit_as[p] = k + 1;
}

/* PAD-600: Put out the light of (this mode): the player up's light out; the next tick takes it down */
UNUSED static void unlight_mode(void)
{
    unsigned p = P();
    if (!p || !lit_as[p]) return;
    pm_log("light put out for player %%u", p);
    lit_as[p] = 0;
}

/* the light taken down: its inserts back to the game (a shot the blocks light themselves stays theirs) */
static void lit_off(void)
{
    int k = lit_shown - 1;
    if (k < 0) return;
    if (!lit_waiting && S[LIT_AT[k].shot] && !LIT[LIT_AT[k].shot].on) pm_lamp_release_shot(S[LIT_AT[k].shot]);
    if (!lit_waiting && LIT_AT[k].insert[0]) pm_lamp_release(LIT_AT[k].insert);
    if (LIT_AT[k].solid[0]) pm_lamp_release(LIT_AT[k].solid);
    lit_shown = 0;
    for (k = N_SHOTS; k < N_LIGHTS; k++) lamp_send(k);   /* PAD-598: one the blocks light by name stays theirs */
}

/* every tick: the player up's light on the playfield while the mode is not running. While one of the game's own
 * modes is in its way (James Bond: the villain mode that won the film's last part) its shot and inserts wait, as the
 * game's own mini-wizards' do, and only the solid one (the film's) is held: the chase starts once that mode is over */
static void lit_tick(void)
{
    unsigned p = pm_player();
    int want = 0, waiting, k;
    if (SHOWING) {                      /* a show paints every insert, and hands them all back at its end */
        lit_shown = 0;
        return;
    }
    if (pm_in_game() && p >= 1 && p <= 4 && !run.on) want = lit_as[p];
    /* its shot is claimed while it would start there now: the game's own starts on that shot are held off (on James
     * Bond the Right ramp starts its henchman and villain modes, and the game handles a shot before the modes do) */
    waiting = want && (pm_game_wizard_way() == 0 || out_of_play());   /* PAD-675: and while another mode runs */
    pm_lit_claim(want && can_start() && !waiting ? S[LIT_AT[want - 1].shot] : 0);
    if (want == lit_shown && (!want || (p == lit_player && waiting == lit_waiting))) return;
    lit_off();
    lit_waiting = 0;
    if (!want) return;
    k = want - 1;
    if (!waiting && S[LIT_AT[k].shot]) pm_lamp_shot(S[LIT_AT[k].shot], LIT_AT[k].rgb, LIT_AT[k].pattern, LIT_AT[k].ms);
    if (!waiting && LIT_AT[k].insert[0]) pm_lamp_set(LIT_AT[k].insert, LIT_AT[k].rgb, LIT_AT[k].pattern, LIT_AT[k].ms);
    if (LIT_AT[k].solid[0]) pm_lamp_set(LIT_AT[k].solid, LIT_AT[k].solid_rgb, PM_LAMP_SOLID, 0);
    lit_shown = want;
    lit_waiting = waiting;
    lit_player = p;
}

/* a shot: the one the player up's light is at starts the mode - not while the game would not start one of its own
 * mini-wizards there (its own check: a henchman, villain or Q Branch mode of its own running), whatever the mode's
 * choice about the game's modes; it stays lit for the next */
static void lit_shot(uint64_t shot)
{
    static unsigned long said_at;
    unsigned p = pm_player();
    if (run.on || p < 1 || p > 4 || !lit_as[p]) return;
    if (!(S[LIT_AT[lit_as[p] - 1].shot] & shot)) return;
    if (pm_game_wizard_way() == 0) {
        if (!said_at || pm_ms() - said_at >= 10000)
            pm_log("not started (its lit shot): one of the game's own modes is in its way - still lit");
        said_at = pm_ms() ? pm_ms() : 1;
        return;
    }
    start("its lit shot", 1);
}

/* the mode began for player p: that player's light is out */
static void lit_started(unsigned p)
{
    if (p <= 4) lit_as[p] = 0;
    lit_off();
}
"""


def _lit_c(g):
    """PAD-503: the C of the mode lit at a shot, one LIT_AT row per Light the mode at block."""
    rows = []
    for shot, insert, rgb, pat, ms, solid, srgb in g.lit:
        rows.append("    { %d, %s, 0x%06xu, %s, %du, %s, 0x%06xu },   /* %s */" % (
            shot, _c_str(insert), rgb, pat, ms, _c_str(solid), srgb, _comment(g.shots[shot] or "no shot")))
    return _LIT_C % {"n": len(g.lit), "rows": "\n".join(rows) + "\n", "lit": lit_ident(g.slug)}

_MECH_C = """/* ---- the mechanisms (PAD-395; MODE_SDK.md "The magnet", "The scoop") ---- */
static int scoop_next;                  /* 1 = the next ball only, 2 = it is held now: then no more */

/* hold a mechanism (the port's name for it) this many ms (the runtime keeps each one's own limit: 5 s, or a post's
 * own longest); refused, mode.log says why */
UNUSED static void hold(const char *what, long long ms)
{
    if (!run.on) return;
    if (ms < %(lo)d) ms = %(lo)d;
    if (ms > %(hi)d) ms = %(hi)d;
    if (!pm_coil_hold(what, (unsigned)ms)) pm_log("hold %%s: refused (the runtime's line says why)", what);
}

/* PAD-621: a hold the clock waits for (the ball held at the start while its clip plays); 0 = the clock runs */
static const char *clock_hold;
static int ball_starting;               /* PAD-621: a challenge's scripts run as the ball starts (it is in the shooter lane) */

/* hold it, and the mode's clock stands still until it lets go */
UNUSED static void hold_wait(const char *what, long long ms)
{
    if (!run.on) return;
    if (ball_starting) {                /* PAD-621 (luvthatapex): a challenge starts at the shooter lane */
        pm_log("hold %%s: no hold, the mode started as the ball starts (the ball is in the shooter lane) - its clock runs",
               what);
        return;
    }
    if (ms < %(lo)d) ms = %(lo)d;
    if (ms > %(hi)d) ms = %(hi)d;
    if (!pm_coil_hold(what, (unsigned)ms)) {
        pm_log("hold %%s: refused (the runtime's line says why) - its clock runs", what);
        return;
    }
    clock_hold = what;
    pm_log("hold %%s: its clock waits until it lets go", what);
}

/* 1 = the clock waits this tick: a hold_wait still holds */
static int clock_held(void)
{
    if (!clock_hold) return 0;
    if (run.on && pm_coil_holding(clock_hold)) return 1;
    pm_log("hold %%s: let go - its clock runs", clock_hold);
    clock_hold = 0;
    return 0;
}

/* hold a ball that settles in the scoop this many ms, then the game kicks it out as always;
 * next = only the next ball, else every ball while the mode runs */
UNUSED static void scoop_hold(long long ms, int next)
{
    if (!run.on) return;
    if (ms < %(slo)d) ms = %(slo)d;
    if (ms > %(shi)d) ms = %(shi)d;
    if (pm_scoop_hold((unsigned)ms)) scoop_next = next;
    else pm_log("scoop: no hold on this game");
}

/* no more scoop holds, and a ball held now goes */
UNUSED static void scoop_let_go(void)
{
    if (run.on) pm_scoop_hold(0);
    scoop_next = 0;
}

UNUSED static void let_go_all(void)
{
    if (!run.on) return;
%(release)s    scoop_let_go();
}

/* PAD-392: turn the shield targets and keep them there while the mode runs (0: stop keeping them); the runtime
 * turns them back when the mode ends, keeps them only while the game's own shield feature sees no shots, and
 * keeps every limit of its own */
UNUSED static void shield(int where)
{
    if (!run.on) return;
    if (!pm_shield_keep(where)) pm_log("shield: no platform on this game");
}

/* PAD-589: the building to one of the game's own floors (0 = where it rests); the runtime puts it back where it was
 * when the mode ends and keeps every limit of its own */
UNUSED static void building(int floor)
{
    if (!run.on) return;
    if (!pm_building(floor)) pm_log("building: no move to floor %%d (the runtime's line says why)", floor);
}

/* PAD-414: shake the cabinet this many ms at a strength (0 hard .. 3 soft), or with one of the game's own shakes; the
 * runtime keeps every limit (the operator's setting, the game's own longest, one at a time, 20 and 15 s a minute) and
 * stops it when the mode ends - unless it was asked for in When the mode ends, which it leaves to run out */
UNUSED static void shake(long long ms, unsigned strength)
{
    if (!run.on) return;
    if (ms < 0) ms = 0;
    if (ms > 60000) ms = 60000;
    if (!pm_shake((unsigned)ms, strength)) pm_log("shake: refused (the runtime's line says why)");
    else if (ending) pm_shake_outlast();
}

UNUSED static void shake_game(const char *name)
{
    if (!run.on) return;
    if (!pm_shake_game(name)) pm_log("shake %%s: refused (the runtime's line says why)", name);
    else if (ending) pm_shake_outlast();
}

/* every tick while it runs: a hold of the next ball only ends once that ball has been held */
static void scoop_tick(void)
{
    if (!scoop_next) return;
    if (pm_scoop_holding()) scoop_next = 2;
    else if (scoop_next == 2) {
        scoop_next = 0;
        pm_scoop_hold(0);
    }
}
"""


def uses_media(program):
    """1 when the mode has clips, sounds or music of its own, or a block that plays one."""
    if program.get("clips") or program.get("sounds") or program.get("music") or program.get("beds"):
        return True
    return any(b.get("op") in ("clip", "sound", "music") for s in program.get("scripts") or []
               for b in _walk(s.get("do") or []))


#: the C of a mode with its own clips and sounds (pad_mode_assets.h); %(slug)s is its folder
# PAD-658: a note (the mode not running) over the mode's own loop clip, as the game's own feedback screens letter their
# two lines over a clip of theirs (MASER CANNON CHARGING): on the live city the note's words sat on the game's map labels
# (run bedfix_pro_r1, bf_ready_c: HE JOINS THE NEXT BATTLE over TANKS 0/10). Its first "over and over" clip.
_NOTE_LOOP_C = """/* PAD-658: a note shows over the mode's own loop (its cover clip), as the game's feedback screens show over a clip
 * of theirs; a TOTAL too when nothing loops as it ends */
#define COVER_CLIP %(cue)s
static int note_looping;
UNUSED static void note_loop(void)
{
    const char *n;
    if (note_looping || hud.metering || !own_clip(COVER_CLIP)) return;
    n = pa_clip_name(&own, COVER_CLIP);
    note_looping = n && pm_backdrop(n);
    if (note_looping) pm_log("own clip %%s (%%s) behind its note", COVER_CLIP, n);
}

static void cover_total(void)
{
    const char *n = pa_clip_name(&own, COVER_CLIP);
    if (n && pm_backdrop(n)) pm_log("own clip %%s (%%s) behind its TOTAL", COVER_CLIP, n);
}

static void note_loop_tick(void)
{
    if (!note_looping) return;
    if (run.on) {                     /* its own run's loop now */
        note_looping = 0;
        return;
    }
    if (hud.up && hud.noting && !hud.metering) return;
    note_looping = 0;
    pm_backdrop(0);                   /* (another of ours began: the runtime gave the backdrop to it already) */
}
"""


_MEDIA_C = """/* ---- its own clips and sounds (PAD-374): what Write carried, named in %(slug)s.assets ---- */
static struct pa_assets own = { .folder = "%(slug)s" };
static const char *clip_waiting, *loop_waiting;   /* MODE_SDK.md "Clips race the game's own" */
static unsigned long clip_due;
static int looping;                     /* a clip of its own loops behind the HUD */

static int own_clip(const char *cue)
{
    pa_load(&own);
    if (pa_clip_name(&own, cue)) return 1;
    pm_log("own clip %%s: the build carried none", cue);
    return 0;
}

/* full screen, over everything: half a second from now, so the game's own clip for the shot
 * that asked does not take the one video surface; the newest asked for wins */
UNUSED static void clip_full(const char *cue)
{
    if (!own_clip(cue)) return;
    if (clip_waiting && clip_waiting != cue)
        pm_log("own clip %%s dropped before it played: %%s was asked for after it", clip_waiting, cue);
    clip_waiting = cue;
    clip_due = pm_ms() + PA_CLIP_AFTER_MS;
    if (ending) end_clip = 1;
}

/* behind the HUD over and over while the mode runs (after a full-screen clip still waiting) */
UNUSED static void clip_loop(const char *cue)
{
    const char *n;
    if (!own_clip(cue)) return;
    if (!run.on || ending) {
        pm_log("own clip %%s: not looped behind the HUD - the mode is %%s", cue, ending ? "ending" : "not running");
        return;
    }
    if (clip_waiting) {
        loop_waiting = cue;
        return;
    }
    n = pa_clip_name(&own, cue);
    looping = pm_backdrop(n);
    pm_log("own clip %%s (%%s) behind the HUD, over and over: %%s", cue, n,
           looping ? "asked" : "this port has no backdrop");
}

/* behind the HUD once, in the loop's place, then the loop again. In When the mode ends there is no loop left to
 * play in (PAD-658, run meltdown_r4: the game's screen showed, not the clip): full screen, the TOTAL after it */
UNUSED static void clip_behind(const char *cue)
{
    if (ending) {
        pm_log("own clip %%s: the mode is ending - played full screen, not behind the HUD", cue);
        clip_full(cue);
        return;
    }
    if (!own_clip(cue)) return;
    if (!run.on || !looping || !pa_clip_event(&own, cue))
        pm_log("own clip %%s: not played behind the HUD - %%s", cue,
               !run.on ? "the mode is not running" : "no clip of its own loops there");
}

/* 1 = the build carried it (played now, or waiting for the voice bus); 0 = it did not */
UNUSED static int sound(const char *cue)
{
    if (pa_call(&own, cue)) return 1;
    pm_log("own sound %%s: the build carried none", cue);
    return 0;
}

static void own_tick(void)
{
    pa_tick(&own);
    if (!clip_waiting || pm_ms() < clip_due) return;
    pa_clip_full(&own, clip_waiting);
    clip_waiting = 0;
    if (loop_waiting && run.on) {
        const char *cue = loop_waiting;
        loop_waiting = 0;
        clip_loop(cue);
    }
}

"""


def _hat_words(hat):
    kind = hat.get("kind")
    when = WHEN.get(hat.get("when", "any"), "")
    if kind == "shot":
        return "when %s is made, %s" % (hat.get("shot") or "(no shot)", when)
    if kind == "any_shot":
        return "when any shot is made, %s" % when
    if kind == "switch":
        return "when any playfield switch is hit, %s" % when
    if kind == "every":
        return "every %s seconds while it runs" % hat.get("seconds")
    if kind == "seconds_left":
        return "when %s seconds are left" % hat.get("seconds")
    if kind == "event":
        return "when %s, %s" % (MP.EVENT_LABELS.get(hat.get("event"), hat.get("event")), when)
    if kind == "timer_done":
        return "when the timer %s runs out" % (hat.get("timer") or "(no timer)")
    if kind == "challenge":
        ms = challenge_launch_ms(hat)                                               # PAD-643
        return "when the player picks the challenge %s%s" % (
            hat.get("challenge") or "(no challenge)",
            ", the player launching its ball" if ms < 0 else ", its ball launched %d s after it starts" % (ms // 1000)
            if ms else "")
    return HATS.get(kind, "?").lower()
