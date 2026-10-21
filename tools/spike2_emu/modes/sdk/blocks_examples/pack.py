"""pack.py - what the PAD-658 blocks examples share, so they play as one pack (written with blk.py's words).

- ONE OF OURS AT A TIME is the runtime's (pm_begin refuses a start while another of our modes runs): a lit mode
  stays lit and starts on its shot once the other is over, so one ball through the Mecha lane cannot start two.
- THE CASH-OUT SHOT. The right scoop (the port's "Right scoop" switch shot) is where every deeper-and-deeper mode
  cashes out: once a stage is done it chases white with the scoop's own inserts (SELECT CITY and the three SCOOP BB
  lights), and the mode's POT is paid there. The ball that lands there is held for the cash-out clip, and the mode
  ends 1.5 s after it (its "next" timer, with "cashed" set), so the game handling that same scoop with the mode
  still running gives no award of its own over the clip (emulator run a2: an ADVANCE TANKS took the glass).
- EACH START COSTS MORE: twice the first count the second time, three times the third (need()).
- THE QUALIFYING NOTE. A mode's count toward its start shows as a note on the HUD every few hits ("12 MORE TO WAKE
  KING CAESAR"), and nothing counts while a multiball runs (David's rule for PAD-379's meter, applied to all).
"""
from blk import (AND, BALLS, NOT, LIT, add, award, change, eq, ge, if_, light, light_insert, light_mode, lt, mul,
                 off, off_insert, on_any_shot, scoop_hold, set_, sub, var)

CASH_SHOT = "Right scoop"
CASH_INSERTS = ("SELECT CITY", "SCOOP BB-BATTLE", "SCOOP BB-GODZILLA PWR UP", "SCOOP BB-SUMMON ALLY")
WHITE = "#ffffff"


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
    """One qualifying hit: ``by`` more toward ``need`` (not in a multiball, not once ready); at ``need`` the mode is
    lit at ``start_shot``; every ``step`` a note says how many are left."""
    return [if_(AND(lt(BALLS, 2), eq(ready, 0)), [
        change(count, by),
        if_(ge(count, need), [
            set_(ready, 1),
            light_mode(start_shot, color, "chase", insert=inserts),
            award(lit_words, sub=lit_sub, seconds=3),
        ], [
            if_(ge(count, note_at), [
                award(note_words, value=sub(need, count), sub=more_sub, seconds=2),
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
