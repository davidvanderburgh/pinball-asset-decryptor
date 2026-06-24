"""MAME ROM zip detection for the PinMAME classic-DMD plugins.

Shared by the Data East / Sega / Stern (Whitestar/SAM) manufacturers —
each passes its own brand-filtered ``GAME_DB`` slice so a Sega zip is
never claimed by the Data East entry and vice versa.

The scheme mirrors the Williams plugin: score each catalogued game by
how many of its ROM filenames (game + sound) appear inside the zip, with
a small bonus when a ``filename_hints`` substring matches the zip's
basename.  PinMAME romset zips are conventionally named
``<family>_<variant>.zip`` (e.g. ``lw3_208.zip``), so the family-prefix
hint reliably catches revisions we haven't catalogued the exact ROM
names for, while exact ROM-name hits disambiguate between revisions.
"""

import os
import zipfile


def _zip_names(path):
    """Lower-cased member names of *path*, or None if it isn't a readable zip."""
    if not os.path.isfile(path) or not path.lower().endswith(".zip"):
        return None
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return [n.lower() for n in zf.namelist()]
    except (zipfile.BadZipFile, OSError):
        return None


def _rom_set(info):
    return {n.lower() for n in (info["game_roms"]
                               + info.get("dmd_roms", [])
                               + info["sound_roms"])}


def is_classic_zip(path, game_db):
    """True if *path* is a MAME zip for any game in *game_db*."""
    names = _zip_names(path)
    if names is None:
        return False
    name_set = set(names)
    for info in game_db.values():
        if name_set & _rom_set(info):
            return True
    return detect_game(path, game_db) is not None


def detect_game(path, game_db):
    """Return the best-matching game key in *game_db* for *path*, or None.

    Scores by ROM-name hits (strong signal) plus a +1 filename-hint bonus
    (catches uncatalogued revisions).  Ties break toward the higher
    ROM-hit count, then the longest matching hint.
    """
    names = _zip_names(path)
    if names is None:
        return None
    name_set = set(names)
    base = os.path.basename(path).lower()
    best_key, best_score, best_hits = None, 0, 0
    for key, info in game_db.items():
        hits = len(name_set & _rom_set(info))
        score = hits
        for hint in info.get("filename_hints", ()):
            if hint.lower() in base:
                score += 1
                break
        if score > best_score or (score == best_score and hits > best_hits):
            best_key, best_score, best_hits = key, score, hits
    return best_key if best_score > 0 else None
