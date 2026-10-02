"""What the emulator knows about each pinHeck game (PAD-320).

The board is the same in every game, so coil N is on the same pin in every
game; what the coil does is the game's. Pins and names were read out of each
game's own SOLENOID TEST (service menu: Enter, right flipper to "TEST:
SOLENOID", Enter; each Enter fires the coil named on screen). Switch roles
were found by running the game: which matrix switches clear its "missing
balls" at Start (the trough), which one shows its skill shot (the shooter
lane), which dedicated input must report a ball at the trough's eject point
before it loads the shooter lane, and which one launches. The games' switch
test shows numbers only, so the rest of the matrix is unnamed here.
"""

#: coil number 0..23 -> (port, bit)
PINS = (("C", 2), ("C", 3), ("E", 5), ("F", 3), ("E", 6), ("E", 7), ("E", 8),
        ("C", 14), ("E", 9), ("C", 4), ("A", 2), ("A", 0), ("A", 1), ("A", 4),
        ("A", 5), ("C", 13), ("G", 1), ("G", 0), ("A", 6), ("A", 7), ("G", 14),
        ("G", 12), ("G", 13), ("A", 9))

#: Per game, by the PRG's name prefix: the SOLENOID TEST names in coil
#: order, the trough switches (eject end first), the shooter lane, ``ready``
#: (the dedicated input that reports a ball at the trough's eject point),
#: the launch button's dedicated bit (None: no launch button found), whether
#: the shooter lane has a hand plunger (Domino's: no input launches it), and
#: which coils load and launch. Rob Zombie's "missing balls" wants all of
#: 1..7 closed; which of them are trough and which hold balls elsewhere is
#: not known.
GAMES = {
    "JET": dict(
        title="Jetsons",
        coils=("KNOCKER", "SHAKER", "RFLIP LOW", "RFLIP HIGH", "LOAD COIL",
               "PLUNGER", "LFLIP HIGH", "LFLIP LOW", "SCOOP", "LEFT SLING",
               "RIGHT SLING", "SOL11", "SOL12", "SOL13", "SOL14", "SOL15",
               "BALL STOP", "BOTTOM POP", "LEFT POP", "SAUCER", "RIGHT POP",
               "SOL21", "SOL22", "SOL23"),
        trough=(35, 34), shooter=32, ready=10, launch=2,
        load="LOAD COIL", plunge="PLUNGER"),
    "DOM": dict(
        title="Domino's Spectacular Pinball Adventure",
        coils=("KNOCKER", "SHAKER", "BTTM POP", "LEFT POP", "RIGHT POP",
               "MAGNET", "STOP POST", "SOL7", "LEFT SCOOP", "LFLIP HIGH",
               "LEFT SLING", "LFLIP LOW", "RIGHT SCOOP", "SOL13", "SOL14",
               "SOL15", "PLUNGER", "LOAD BALL", "RFLIP LOW", "RIGHT SLING",
               "RFLIP HIGH", "SOL21", "SOL22", "SOL23"),
        trough=(1, 2, 3), shooter=0, ready=10, launch=None, manual_plunger=True,
        load="LOAD BALL", plunge="PLUNGER"),
    "RZO": dict(
        title="Rob Zombie's Spookshow International",
        coils=tuple("SOL%d" % n for n in range(16)) + (
            "AUTOPLUNGER", "BALL LOAD", "RFLIP LOW", "RFLIP HIGH", "RIGHT SLING",
            "UR SLING", "UNUSED", "SOL23"),
        trough=(1, 2, 3, 4, 5, 6, 7), shooter=0, ready=10, launch=None,
        load="BALL LOAD", plunge="AUTOPLUNGER"),
}


def coil_pins(game):
    """{coil name: (port, mask)} for a GAMES entry."""
    return {name: (port, 1 << bit) for name, (port, bit) in zip(game["coils"], PINS)}


def game_of(prg_name):
    """The GAMES entry for a PRG file name (``JET_V004.PRG`` -> Jetsons)."""
    stem = prg_name.upper().replace("\\", "/").rsplit("/", 1)[-1]
    return GAMES.get(stem.split("_", 1)[0])
