"""What the emulator knows about each pinHeck game (PAD-320).

The board is the same in every game, so the coil pins are too: read out of
Jetsons' own SOLENOID TEST (each name as the game shows it, then the pin it
pulsed). Switch roles differ per game and were found by running the game:
which matrix switches clear its "MISSING BALLS" at Start (the trough), which
one shows its skill-shot screen (the shooter lane), and which cabinet input
makes it serve a ball (the launch button). The games' own switch test shows
numbers only, so the rest of the matrix is unnamed here.
"""

#: SOLENOID TEST name -> (port, bit), Jetsons V004 (coil numbers 0..23 in order)
COILS = (
    ("KNOCKER", "C", 2), ("SHAKER", "C", 3), ("RFLIP LOW", "E", 5),
    ("RFLIP HIGH", "F", 3), ("LOAD COIL", "E", 6), ("PLUNGER", "E", 7),
    ("LFLIP HIGH", "E", 8), ("LFLIP LOW", "C", 14), ("SCOOP", "E", 9),
    ("LEFT SLING", "C", 4), ("RIGHT SLING", "A", 2), ("SOL11", "A", 0),
    ("SOL12", "A", 1), ("SOL13", "A", 4), ("SOL14", "A", 5), ("SOL15", "C", 13),
    ("BALL STOP", "G", 1), ("BOTTOM POP", "G", 0), ("LEFT POP", "A", 6),
    ("SAUCER", "A", 7), ("RIGHT POP", "G", 14), ("SOL21", "G", 12),
    ("SOL22", "G", 13), ("SOL23", "A", 9),
)

#: Per game, by the PRG's name prefix: the trough switches (eject end
#: first), the shooter lane, ``ready`` - the dedicated (cabinet) input that is
#: closed while a ball sits at the trough's eject point (the game loads the
#: shooter lane only then), the launch button's cabinet bit, and the coils
#: that move a ball into the shooter lane and launch it.
GAMES = {
    "JET": dict(title="Jetsons", trough=(35, 34), shooter=32, ready=10,
                launch=2, load="LOAD COIL", plunge="PLUNGER"),
}


def coil_pins():
    return {name: (port, 1 << bit) for name, port, bit in COILS}


def game_of(prg_name):
    """The GAMES entry for a PRG file name (``JET_V004.PRG`` -> Jetsons)."""
    stem = prg_name.upper().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return GAMES.get(stem.split("_", 1)[0])
