"""Stern S.A.M. (2006-2014) file identification for the PinMAME capture.

A SAM game is ONE ``.bin``: the code update Stern ships for the USB stick,
which is byte for byte the ROM PinMAME runs (``src/wpc/sam.c`` loads it
whole).  So the input can be that ``.bin`` as downloaded, or a zip holding
it (a MAME romset, or Stern's own download zip with its readme), under any
file name: :func:`identify` matches by the ``.bin``'s CRC32 and size against
every romset in :data:`.sam_games.SAM_GAME_DB`, and :func:`stage` lays it out
the way PinMAME looks for it (``<romset>.zip`` holding ``<file>``).

The CRC of a zip member is read from the zip's directory (free); a bare
``.bin`` is hashed only when its size is one PinMAME knows, so a multi-GB
Spike SD-card image named ``.bin`` costs a stat, not a read.
"""

import os
import re
import shutil
import zipfile
import zlib
from dataclasses import dataclass
from typing import Optional

from .sam_games import SAM_GAME_DB

# The largest SAM update (AC/DC, Metallica, Star Trek, Mustang, TWD) fits
# the 128 MB ROM region sam.c gives it; nothing bigger can be a SAM .bin.
MAX_BIN_SIZE = 0x8000000
# The smallest (The Simpsons Kooky Carnival) is 5.2 MB; the classic DMD
# romsets' .bin chips are 2 MB at most, so this keeps their zips out.
MIN_BIN_SIZE = 0x400000

# A SAM update is a .bin; The Walking Dead 1.05 alone shipped as .ebi.
EXTENSIONS = (".bin", ".ebi")

#: (crc32, size) -> (game key, romset)
_BY_CRC = {}
#: size -> {(game key, romset), ...}
_BY_SIZE = {}
for _key, _info in SAM_GAME_DB.items():
    for _rs, (_fn, _crc, _size, _title) in _info["romsets"].items():
        _BY_CRC[(_crc, _size)] = (_key, _rs)
        _BY_SIZE.setdefault(_size, set()).add((_key, _rs))


@dataclass(frozen=True)
class SamMatch:
    """What :func:`identify` found in a file."""
    key: str             # SAM_GAME_DB key ("mustang")
    romset: str          # the PinMAME romset to run ("mt_145h"); "" = none
    member: str          # the .bin's name inside the zip; "" for a bare .bin
    exact: bool          # CRC + size match PinMAME's dump of ``romset``
    title: str           # PinMAME's name for that version, or the title

    @property
    def runnable(self):
        return bool(self.romset)


def _crc_file(path):
    crc = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _family_key(name):
    """The SAM title a file NAME points at ("mt_150h.bin" -> "mustang"),
    for a version PinMAME doesn't list; ``None`` when it names none."""
    base = os.path.basename(name).lower()
    best = None
    for key, info in SAM_GAME_DB.items():
        fam = info["family"]
        if re.match(re.escape(fam) + r"_?\d", base) and (
                best is None or len(fam) > len(SAM_GAME_DB[best]["family"])):
            best = key
    return best


def _match(crc, size, name, member):
    hit = _BY_CRC.get((crc, size))
    if hit:
        key, rs = hit
        return SamMatch(key, rs, member, True,
                        SAM_GAME_DB[key]["romsets"][rs][3])
    fam = _family_key(name)
    if fam is None:
        return None
    # A version PinMAME has no dump of (a newer update, or a patched file).
    # PinMAME still runs a .bin whose SIZE matches one of the title's romsets
    # (it only warns about the checksum), so borrow that romset; a size it
    # never saw can't be loaded at all.  Several versions can share a size:
    # the one the file is named for, else the newest (plain over a variant
    # like Mustang's "Boss" romset of the same number).
    base = os.path.basename(name).lower()

    def rank(rs):
        num = re.search(r"_(\d+)", rs)
        return (rs in base, int(num.group(1)) if num else 0, -len(rs))

    same = [rs for key, rs in _BY_SIZE.get(size, ()) if key == fam]
    rs = max(same, key=rank) if same else ""
    return SamMatch(fam, rs, member, False,
                    SAM_GAME_DB[fam]["romsets"][rs][3] if rs
                    else SAM_GAME_DB[fam]["display"])


def identify(path) -> Optional[SamMatch]:
    """The SAM game in *path* (a ``.zip`` or a bare ``.bin`` / ``.ebi``),
    or None."""
    if not os.path.isfile(path):
        return None
    low = path.lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                bins = [i for i in zf.infolist()
                        if i.filename.lower().endswith(EXTENSIONS)
                        and MIN_BIN_SIZE <= i.file_size <= MAX_BIN_SIZE]
        except (zipfile.BadZipFile, OSError):
            return None
        found = None
        for i in bins:
            # Name the title by the member, then by the zip (a romset zip
            # is named for it even when Stern's file inside isn't).
            m = (_match(i.CRC, i.file_size, i.filename, i.filename)
                 or _match(i.CRC, i.file_size, path, i.filename))
            if m and (found is None or (m.exact, m.runnable)
                      > (found.exact, found.runnable)):
                found = m
        return found
    if low.endswith(EXTENSIONS):
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        if not MIN_BIN_SIZE <= size <= MAX_BIN_SIZE:
            return None
        if size in _BY_SIZE:
            return _match(_crc_file(path), size, path, "")
        fam = _family_key(path)
        return SamMatch(fam, "", "", False, SAM_GAME_DB[fam]["display"]) \
            if fam else None
    return None


def known_versions(key):
    """PinMAME's names for every version of *key* it can run, newest last."""
    return [t for _rs, (_f, _c, _s, t)
            in sorted(SAM_GAME_DB[key]["romsets"].items())]


def stage(path, match, work_dir):
    """Write ``<work_dir>/<romset>.zip`` holding the ``.bin`` under the name
    PinMAME loads, and return its path.  *path* / *match* as from
    :func:`identify`; the match must be runnable."""
    fn = SAM_GAME_DB[match.key]["romsets"][match.romset][0]
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, match.romset + ".zip")
    # Stored, not deflated: the .bin is already dense and PinMAME reads it
    # once; deflating 120 MB would only cost time.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as dst:
        with dst.open(fn, "w", force_zip64=True) as w:
            if match.member:
                with zipfile.ZipFile(path) as src, src.open(match.member) as r:
                    shutil.copyfileobj(r, w, 1 << 20)
            else:
                with open(path, "rb") as r:
                    shutil.copyfileobj(r, w, 1 << 20)
    return out
