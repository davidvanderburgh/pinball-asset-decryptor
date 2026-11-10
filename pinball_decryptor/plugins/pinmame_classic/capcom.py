"""Capcom pinball (1995-1996): the six titles and their PinMAME romsets.

Capcom's machines (68000 game CPU, 128x32 four-shade DMD, an 8752 sound
CPU feeding TI MPEG audio decoders) run in PinMAME's ``capcom`` driver,
so they get the same attract-mode capture as the Data East / Sega
entries: libpinmame runs the ROM and records the DMD animations with
their sound.

Capcom's ROM *names* are generic (``u24_v11.bin`` is the sound CPU on
every title, Airborne and Pinball Magic both have a ``u2l_v10.bin``), so
each romset is told apart by its version-specific program ROMs, the
``u1`` pair (plus ``u3`` on Flipper Football, whose 1.03 and 1.04 share
their ``u1``).  The names are the ones libpinmame itself asks for when
it loads each romset (PAD-1087).

A zip need not be named for its romset: :func:`pick_romset` reads which
version is inside, and the capture stages it under that name.
"""

import os

from .formats import _zip_names

#: game key -> catalogue entry.  ``romsets`` maps each PinMAME romset to
#: the ROMs that only it has; the first romset is the parent.
CAPCOM_GAME_DB = {
    "pinball_magic": {
        "display": "Pinball Magic", "year": 1995,
        "romsets": {
            "pmv112": ["u1l_v112.bin", "u1h_v112.bin"],
            "pmv112r": ["u1lv112i.bin", "u1hv112i.bin"],
        },
    },
    "airborne": {
        "display": "Airborne", "year": 1996,
        "romsets": {
            "abv106": ["u1l_v16.bin", "u1h_v16.bin"],
            "abv105": ["u1l_v15.bin", "u1h_v15.bin"],
            "abv106r": ["u1l_v16i.bin", "u1h_v16i.bin"],
        },
    },
    "breakshot": {
        "display": "Breakshot", "year": 1996,
        "romsets": {
            "bsv103": ["u1l_v13.bin", "u1h_v13.bin"],
            "bsv102": ["u1l_v12.bin", "u1h_v12.bin"],
            "bsv102r": ["u1l_v12i.bin", "u1h_v12i.bin"],
            "bsv100r": ["u1l_v10i.bin", "u1h_v10i.bin"],
            "bsb105": ["bsu1l_b1.05", "bsu1h_b1.05"],
        },
    },
    "flipper_football": {
        "display": "Flipper Football", "year": 1996,
        "romsets": {
            "ffv104": ["u1l_v104.bin", "u1h_v104.bin",
                       "u3l_v104.bin", "u3h_v104.bin"],
            "ffv103": ["u1l_v104.bin", "u1h_v104.bin",
                       "u3l_v103.bin", "u3h_v103.bin"],
            "ffv101": ["u1l_v100.bin", "u1h_v100.bin",
                       "u3l_v101.bin", "u3h_v101.bin"],
        },
    },
    "kingpin": {
        "display": "Kingpin", "year": 1996,
        "romsets": {
            "kpb105": ["u1hu1l.bin", "u2hu2l.bin"],
        },
    },
    "big_bang_bar": {
        "display": "Big Bang Bar", "year": 1996,
        "romsets": {
            "bbb109": ["u1l_b19.bin", "u1h_b19.bin"],
            "bbb108": ["u1l_b18.bin", "u1h_b18.bin"],
        },
    },
}

# The fields the shared classic code (detection, the capture log) reads.
for _info in CAPCOM_GAME_DB.values():
    _info.update(
        manufacturer="Capcom", dmd="128x32", sound_roms=[],
        family=next(iter(_info["romsets"])),
        game_roms=sorted({r for roms in _info["romsets"].values()
                          for r in roms}),
        # Whole romset names, not a prefix: "bbb" alone is also the
        # start of an unrelated romset (bbbowlin).
        filename_hints=list(_info["romsets"]))
del _info


def pick_romset(path, info):
    """The PinMAME romset to run *path* (a zip of *info*'s game) as.

    The zip's own name when it is one of the game's romsets; otherwise
    the romset whose version ROMs it holds the most of, the parent on a
    tie (a zip with none of them, say only the shared ROMs, runs as the
    parent)."""
    romsets = info["romsets"]
    base = os.path.splitext(os.path.basename(path))[0].lower()
    if base in romsets:
        return base
    names = set(_zip_names(path) or ())
    best, best_hits = next(iter(romsets)), 0
    for romset, roms in romsets.items():
        hits = sum(1 for r in roms if r.lower() in names)
        # A romset only counts when every one of its own ROMs is there
        # (Flipper Football 1.03 and 1.04 share their u1 pair).
        if hits == len(roms) and hits > best_hits:
            best, best_hits = romset, hits
    return best
