"""Williams MAME ROM zip detection."""

import os
import zipfile

from .games import GAME_DB


def is_williams_zip(path):
    if not os.path.isfile(path):
        return False
    if not path.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = [n.lower() for n in zf.namelist()]
    except (zipfile.BadZipFile, OSError):
        return False
    for info in GAME_DB.values():
        rom_set = {n.lower() for n in info["game_roms"] + info["sound_roms"]}
        if any(n in rom_set for n in names):
            return True
    return False


def detect_game(zip_path):
    """Return the game key for a Williams MAME zip, or None."""
    if not os.path.isfile(zip_path):
        return None
    if not zip_path.lower().endswith(".zip"):
        return None
    base = os.path.basename(zip_path).lower()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = [n.lower() for n in zf.namelist()]
    except (zipfile.BadZipFile, OSError):
        return None
    # Score each game by how many of its ROMs we find inside.
    best_key = None
    best_score = 0
    for key, info in GAME_DB.items():
        roms = {n.lower() for n in info["game_roms"] + info["sound_roms"]}
        score = sum(1 for n in names if n in roms)
        # Filename hints are a fallback signal worth +1.
        for hint in info["filename_hints"]:
            if hint.lower() in base:
                score += 1
                break
        if score > best_score:
            best_score = score
            best_key = key
    if best_score == 0:
        return None
    return best_key


def list_game_roms(zip_path, game_key):
    """Return (game_rom_names, sound_rom_names) found inside the zip.

    Names are matched case-insensitively against the game's catalogue;
    the returned values preserve the casing as stored in the zip.

    Fallback: when the catalogue lookup finds no game ROM (the user
    has a ROM revision whose filename we hadn't catalogued yet), we
    pick the largest ``.rom`` file in the zip — WPC game ROMs are
    always 256 KB, 512 KB, or 1 MB and they're invariably the
    largest single file inside.  Any leftover ``.rom`` / ``.l1`` /
    ``.512`` files are treated as sound ROMs.
    """
    info = GAME_DB[game_key]
    expected_game = {n.lower() for n in info["game_roms"]}
    expected_sound = {n.lower() for n in info["sound_roms"]}
    game_roms = []
    sound_roms = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = list(zf.infolist())
        for m in members:
            low = m.filename.lower()
            if low in expected_game:
                game_roms.append(m.filename)
            elif low in expected_sound:
                sound_roms.append(m.filename)
        if not game_roms:
            # Fallback: take the largest game-ROM-shaped file in the
            # zip as the game ROM, and everything else with a sound-
            # rom-ish extension as sound ROMs.  WPC-95 sometimes uses
            # ``.bin`` instead of ``.rom`` for the game ROM
            # (e.g. ``afm_113b.bin``).  Game ROMs are always 256 KB,
            # 512 KB, or 1 MB.
            game_rom_exts = (".rom", ".bin")
            sound_rom_exts = (".l1", ".rom", ".512", ".bin")
            candidates = [
                m for m in members
                if (m.filename.lower().endswith(game_rom_exts)
                    and m.file_size in (0x40000, 0x80000, 0x100000))]
            candidates.sort(key=lambda m: m.file_size, reverse=True)
            if candidates:
                game_roms.append(candidates[0].filename)
            already = {n.lower() for n in game_roms}
            for m in members:
                low = m.filename.lower()
                if low in already:
                    continue
                if any(low.endswith(ext) for ext in sound_rom_exts):
                    sound_roms.append(m.filename)
    return game_roms, sound_roms
