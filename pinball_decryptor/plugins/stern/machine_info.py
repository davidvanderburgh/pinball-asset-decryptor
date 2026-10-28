"""What a Stern Spike 2 card's release is, in words, and which release is
newest on Stern's public game-code page (PAD-783, My machines).

Both read the same key.  A card's update index is
``/spk/index/<title>-<a>_<b>_<c>.sidx`` (``godzilla_le-1_16_0.sidx``), and
every download on Stern's game-code page is named for that same key:
``godzilla_le-1_16_0_spike2.spk.zip`` (``beatles-1_29_0.spk`` on a few older
titles).  So "is there newer code for this machine?" is the largest version
of the card's key on the page; no title table can drift from it.

The page carries Spike 3 builds as ``..._spike3.spk.zip``; those are another
board and never count as an update for a Spike 2 card (Star Wars Home Edition
has both).
"""

import re

#: Stern's public game-code page: the one the watcher reads and the link a
#: row shows.  Nothing on it is ever downloaded by the app.
GAME_CODE_PAGE = "https://www.sternpinball.com/support/game-code/"

_SIDX = re.compile(r"^([a-z0-9_]+)-(\d+)_(\d+)_(\d+)(?:\.sidx)?$")
# a download name anywhere on the page, JSON-escaped or not: the key is
# preceded by a "/" (or "\/"), which [a-z0-9_] never spans
_DOWNLOAD = re.compile(
    r"([a-z0-9_]+)-(\d+)_(\d+)_(\d+)(_spike\d)?\.spk(?:\.zip)?\b")

#: Key suffix -> the edition words Stern sells it under.  LE and Premium run
#: the same code (the page lists both against one ``_le`` download).
_EDITIONS = (("_the_pin", "Home Edition"), ("_elg", "Home Edition"),
             ("_le", "LE / Premium"), ("_pro", "Pro"))

#: Titles the game table names too loosely for a release.
_TITLES = {
    "james_bond_60th": "James Bond 007 60th Anniversary",
    "beatles": "The Beatles",
}


def parse_sidx(sidx):
    """``("godzilla_le", (1, 16, 0))`` for ``godzilla_le-1_16_0.sidx``, or
    ``None``."""
    m = _SIDX.match((sidx or "").strip().lower().rsplit("/", 1)[-1])
    if not m:
        return None
    return m.group(1), tuple(int(m.group(i)) for i in (2, 3, 4))


def short_version(v):
    """``(1, 16, 0)`` -> ``"1.16"`` (Stern's own spelling of a build);
    ``(1, 58, 1)`` -> ``"1.58.1"``."""
    if not v:
        return ""
    a, b, c = v
    return "%d.%02d" % (a, b) if not c else "%d.%02d.%d" % (a, b, c)


def _title(base):
    if base in _TITLES:
        return _TITLES[base]
    from .games import GAME_DB
    hit = GAME_DB.get(base)
    if hit is None:
        for key, info in GAME_DB.items():
            hints = [key] + [h.replace(" ", "_")
                             for h in info.get("filename_hints") or ()]
            if any(h and h.strip("_") and h.strip("_") in base for h in hints):
                hit = info
                break
    if hit is not None:
        return hit["display"].replace(" (Spike 2)", "")
    return base.replace("_", " ").title()


def release_info(sidx, known_keys=()):
    """``{"key", "version", "build", "title", "edition"}`` for the card whose
    update index is *sidx*, or ``None``.  *known_keys*: other release keys
    (the stock table's), so a bare key whose ``_le`` twin exists reads as
    the Pro (``aerosmith`` beside ``aerosmith_le``)."""
    got = parse_sidx(sidx)
    if got is None:
        return None
    key, version = got
    base, edition = key, ""
    for suffix, words in _EDITIONS:
        if key.endswith(suffix):
            base, edition = key[:-len(suffix)], words
            break
    if not edition and key + "_le" in set(known_keys or ()):
        edition = "Pro"
    return {"key": key, "version": list(version),
            "build": short_version(version), "title": _title(base),
            "edition": edition}


def known_release_keys():
    """Every release key in the shipped stock table."""
    from .stock_prints import load_table
    out = set()
    for name in load_table():
        got = parse_sidx(name)
        if got:
            out.add(got[0])
    return out


def parse_game_code_page(text):
    """``{key: (a, b, c)}``: the newest Spike 2 build of every release the
    page offers (names compared in lower case: the page spells a few with
    capitals, ``Ghostbusters_le-1_17_0.spk``).  Spike 3 downloads are
    skipped."""
    newest = {}
    for m in _DOWNLOAD.finditer((text or "").lower()):
        if m.group(5) and m.group(5) != "_spike2":
            continue
        key = m.group(1)
        v = tuple(int(m.group(i)) for i in (2, 3, 4))
        if v > newest.get(key, ()):
            newest[key] = v
    return newest
