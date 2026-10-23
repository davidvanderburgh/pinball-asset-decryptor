"""pack.py - what the PAD-658 blocks examples share, so they play as one pack (written with blk.py's words).

- ONE OF OURS AT A TIME is the runtime's (pm_begin refuses a start while another of our modes runs): a lit mode
  stays lit and starts on its shot once the other is over, so one ball through the Mecha lane cannot start two.
- THE CASH-OUT SHOT. The right scoop (the port's "Right scoop" switch shot) is where every deeper-and-deeper mode
  cashes out: once a stage is done it chases white with the scoop's own inserts (SELECT CITY and the three SCOOP BB
  lights), and the mode's POT is paid there. The ball that lands there is held for the cash-out clip, and the mode
  ends 1.5 s after it (its "next" timer, with "cashed" set), so the game handling that same scoop with the mode
  still running gives no award of its own over the clip (emulator run a2: an ADVANCE TANKS took the glass).
- EACH START COSTS MORE: twice the first count the second time, three times the third (need()).
- THE CLOCK ON A GOOD SHOT. A successful shot (one that hits, cuts, scores or moves the mode on) puts a clock that
  has run under CLOCK_FLOOR seconds back up to it (David, PAD-658: "successful shots reset the countdown timer to 15
  seconds (if it's below 15)... make it consistent"): clock_floor(), one block every mode with a clock uses.
- THE QUALIFYING NOTE. A mode's count toward its start shows as a note on the HUD every few hits ("12 MORE TO WAKE
  KING CAESAR"), and nothing counts while a multiball runs (David's rule for PAD-379's meter, applied to all).
- SAY THE SHOT (David, PAD-658: "the shots are not explicit enough and some of the information only flashes on the
  screen very briefly... use obvious lighting and text cues that the user understands"):
  - the HUD's line names what to shoot NOW by the playfield's own names (SHOT_WORDS; shoot(), line_follows()), never
    a colour ("the green jackpot") or a story's name ("the moving heart") alone; a moving shot's line moves with it;
  - what counts is lit, and only that: lit in the mode's colour, the one that pays most chasing; a made shot goes off;
  - a note stays NOTE_S seconds at least, and says what next where it can;
  - a stage's clock is STAGE_S, a window inside it (a follow-up shot, a hurry-up, a combo) WINDOW_S at least (David:
    "you can't really accomplish much in 10 seconds. 40 seconds is better").
"""
from blk import (AND, NOT, LIT, add, award, change, eq, ge, hud_line, if_, light, light_insert, light_mode,
                 mul, off, off_insert, on_any_shot, scoop_hold, set_, set_time, sub, var)

CASH_SHOT = "Right scoop"
CASH_INSERTS = ("SELECT CITY", "SCOOP BB-BATTLE", "SCOOP BB-GODZILLA PWR UP", "SCOOP BB-SUMMON ALLY")
WHITE = "#ffffff"
CLOCK_FLOOR = 15                                     # David: every mode the same
NOTE_S = 3                                           # a note on the glass, at least
STAGE_S = 40                                         # a stage's clock
WINDOW_S = 20                                        # a window inside a stage, at least

#: the shots as the line says them: the playfield's (and the emulator's switch list's) names
SHOT_WORDS = {
    "Left ramp": "LEFT RAMP", "Right ramp": "RIGHT RAMP", "Big loop": "BIG LOOP", "Building": "BUILDING",
    "Godzilla target": "GODZILLA TARGET", "Maser target": "MASER TARGET", "Mecha exit bottom": "MECHA LANE",
    "Mecha exit top": "TOP OF THE MECHA", "Powerline left": "LEFT POWERLINE", "Powerline center": "CENTER POWERLINE",
    "Powerline right": "RIGHT POWERLINE", "Shield target left": "LEFT SHIELD", "Shield target center": "CENTER SHIELD",
    "Shield target right": "RIGHT SHIELD", "Pop bumper": "POP BUMPERS", "Right scoop": "RIGHT SCOOP",
    "Slingshot": "SLINGSHOTS", "Left spinner": "LEFT SPINNER", "Top spinner": "TOP SPINNER",
    "Shield ramp spinner": "SPINNER", "Right spinner": "SPINNER", "Skill shot": "SKILL SHOT",
    "Left return lane": "LEFT INLANE", "Right return lane": "RIGHT INLANE",
}


def shoot(*shots, verb="SHOOT THE"):
    """The words for shooting ``shots``: SHOOT THE LEFT RAMP; SHOOT THE LEFT RAMP OR BIG LOOP."""
    return "%s %s" % (verb, " OR ".join(SHOT_WORDS[s] for s in shots))


def line_follows(name, shots, verb="SHOOT THE", after="", value=None, first=1):
    """The line naming the shot a moving target is at: ``name`` holds its place (``first`` = shots[0]), so the line
    moves with the light: one block per place."""
    return [if_(eq(name, i), [hud_line("%s %s%s" % (verb, SHOT_WORDS[s], after), value)])
            for i, s in enumerate(shots, first)]


def clock_floor():
    """A successful shot: the clock back up to CLOCK_FLOOR seconds when it has run under it (one block: Keep at least
    15 seconds on the clock)."""
    return set_time(CLOCK_FLOOR, at_least=True)


def cash_out_lit():
    """The scoop chases white: shoot it to cash out."""
    return ([light(CASH_SHOT, WHITE, "chase", 120)] + [light_insert(n, WHITE, "chase", 120) for n in CASH_INSERTS]
            + [scoop_hold(2500, "next")])


def cash_out_off():
    return [off(CASH_SHOT)] + [off_insert(n) for n in CASH_INSERTS]


def relight(ready, start_shot, color, inserts=""):
    """While the mode is not running: lit again at its start shot when it is ready and not lit (a new ball, or a
    game's mode that took the light)."""
    return on_any_shot(
        if_(AND(eq(ready, 1), NOT(LIT)), [light_mode(start_shot, color, "chase", insert=inserts)]),
        when="idle")


def count_up(count, by, need, ready, note_at, start_shot, color, inserts, lit_words, lit_sub, note_words, more_sub,
             step=5):
    """One qualifying hit: ``by`` more toward ``need`` (a multiball's too, PAD-690; not once ready); at ``need`` the mode is
    lit at ``start_shot``; every ``step`` a note says how many are left."""
    return [if_(eq(ready, 0), [
        change(count, by),
        if_(ge(count, need), [
            set_(ready, 1),
            light_mode(start_shot, color, "chase", insert=inserts),
            award(lit_words, sub=lit_sub, seconds=NOTE_S),
        ], [
            if_(ge(count, note_at), [
                award(note_words, value=sub(need, count), sub=more_sub, seconds=NOTE_S),
                set_(note_at, add(count, step)),
            ]),
        ]),
    ])]


def need(base, times):
    """What it takes to light a mode again (David, PAD-658: "hitting the major target three times for the first
    activation but an additional six for the next"): ``base`` the first time, twice that the second, three times
    the third... ``times`` is the variable counting its starts this game."""
    return mul(base, add(var(times), 1))


def pack_vars():
    return []


def begin(me):
    """The first blocks of every pack mode's When the mode starts (none yet: kept so a pack-wide start is one place)."""
    return []


def finish():
    """The first blocks of When the mode ends (none yet)."""
    return []
