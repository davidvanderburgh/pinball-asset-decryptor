"""Game detection from PB `.upd` filenames, tar contents, and Clonezilla ISOs."""

import os
import tarfile

from .games import GAME_DB

GZIP_MAGIC = b"\x1f\x8b"
ISO9660_MAGIC = b"CD001"


def is_upd_file(path):
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            return f.read(2) == GZIP_MAGIC
    except OSError:
        return False


def is_iso_file(path):
    if not os.path.isfile(path):
        return False
    if not path.lower().endswith(".iso"):
        return False
    try:
        with open(path, "rb") as f:
            f.seek(0x8001)
            return f.read(5) == ISO9660_MAGIC
    except OSError:
        return False


def detect_iso_game(iso_path):
    """Return the game key for a Clonezilla `.iso`, or None if unknown."""
    name = os.path.basename(iso_path).lower()
    for key, info in GAME_DB.items():
        iso = info.get("iso")
        if not iso:
            continue
        for hint in iso.get("filename_hints", []):
            if hint.lower() in name:
                return key
    return None


def detect_game(upd_path):
    """Return the game key for a `.upd` file, or None if unknown."""
    key = _detect_from_contents(upd_path)
    if key:
        return key
    return _detect_from_filename(upd_path)


def _detect_from_filename(upd_path):
    name = os.path.basename(upd_path).lower()
    if name.startswith("pbpp"):
        return "predator"
    if name.startswith("pbq"):
        return "queen"
    return None


def _detect_from_contents(upd_path):
    if not is_upd_file(upd_path):
        return None
    try:
        with tarfile.open(upd_path, "r:gz") as tar:
            count = 0
            for member in tar:
                count += 1
                if count > 200:
                    break
                norm = member.name.lstrip("./").replace("\\", "/")
                for key, info in GAME_DB.items():
                    needle = info["internal_dir"]
                    if norm.startswith(needle + "/") or norm == needle:
                        return key
    except (tarfile.TarError, OSError, EOFError):
        return None
    return None
