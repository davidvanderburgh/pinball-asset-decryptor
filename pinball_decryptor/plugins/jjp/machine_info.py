"""What a Jersey Jack full-install ISO is, and which build of it is newest
on JJP's public support pages (PAD-787, My machines).

A JJP machine is (re)installed from a full-install ISO, and the ISO's own
volume ID names its release: ``Sonic-v00.926``, ``GunsNRoses-v03.03`` -- the
file name JJP publishes it under, kept by a renamed copy and by PAD's own
rebuild (xorriso keeps the volume ID).  That ID is the release key a machine
row carries (lineage's ``sidx``), read from the 2 KiB primary volume
descriptor at 32 KiB in: no mount, no WSL.

JJP's support site has a page per edition, and every edition of a title
links the same ISO (``.../sonic/Sonic-v00.951.iso``, US and EU mirrors), so
one page per title answers "is there newer code?" (:data:`PAGES`).  JJP
spells builds as decimals: ``00.95`` is newer than ``00.926``.
"""

import re

from ...core import lineage

#: JJP's support hub: the link a row shows when its title has no page here.
SUPPORT_PAGE = "https://jerseyjackpinball.com/pages/support"
_PAGE = "https://jerseyjackpinball.com/pages/support/%s"
#: Release key -> the support page that links its full-install ISO (any
#: edition's page: they all link the same file).  Measured 2026-10-27.
PAGES = {
    "avatar": _PAGE % "avatar-limited-edition",
    "dialedin": _PAGE % "dialed-in-limited-edition",
    "eltonjohn": _PAGE % "elton-john-platinum-edition",
    "godfather": _PAGE % "the-godfather-limited-edition",
    "gunsnroses": _PAGE % "guns-n-roses-limited-edition",
    "harrypotter": _PAGE % "harry-potter-collectors-edition",
    "hobbit": _PAGE % "the-hobbit-limited-edition",
    "pirates": _PAGE % "pirates-of-the-caribbean-limited-edition",
    "sonic": _PAGE % "sonic-special-edition",
    "toystory": _PAGE % "toy-story-4-limited-edition",
    "wizardofoz": _PAGE % "the-wizard-of-oz-standard-edition",
    "wonka": _PAGE % "willy-wonka-the-chocolate-factory-limited-edition",
}

#: Volume ID -> the print of JJP's own ISO (:func:`iso_print` over the
#: release as downloaded).  A file whose ID is listed but whose print
#: differs is a modified install; an ID not listed is a release PAD has no
#: record of.
STOCK = {
    "EltonJohn-v02.03": "826e15a0137bf992ef8ae1169cd4142a",
    "Godfather-v02.03": "839badf73581031f8be5fe644a6299df",
    "GunsNRoses-v03.03": "24aac1fd5e00232d86a21b8d5f2c910f",
    "HarryPotter-v01.26": "111c2d5613351cbbe776eecdbf9f6dcd",
    "Pirates-v01.01": "42b081c8a2e42e38de4bb654f9adf025",
    "Sonic-v00.925": "6cdf5e1881464dbcb5d2494da2f554d3",
    "Sonic-v00.926": "13607b2167694cb908389474ac3fc5b4",
    "Wonka-v03.03": "f619e704863805fb250075a202990a40",
}

_PVD_AT = 16 * 2048
_VOLUME_ID = re.compile(r"^([A-Za-z0-9]+)-v(\d+)\.(\d+)$")
_ISO_LINK = re.compile(r"/([a-z0-9]+)-v(\d+)\.(\d+)\.iso\b")


def read_volume_id(path):
    """``(volume id, the descriptor's bytes)`` of the ISO at *path*, or
    ``None`` when it isn't an ISO 9660 image."""
    with open(path, "rb") as f:
        f.seek(_PVD_AT)
        pvd = f.read(2048)
    if len(pvd) < 2048 or pvd[0] != 1 or pvd[1:6] != b"CD001":
        return None
    return pvd[40:72].decode("latin1").strip(), pvd


def version_of(major, minor):
    """A build as a comparable tuple: ``("00", "951")`` -> ``(0, 951000,
    3)``.  The fraction is padded so ``00.95`` sorts above ``00.926``; the
    last item keeps how many digits JJP wrote."""
    return (int(major), int(minor.ljust(6, "0")[:6]), len(minor))


def version_words(v):
    """``(0, 951000, 3)`` -> ``"0.951"``, ``(3, 30000, 2)`` -> ``"3.03"``."""
    if not v:
        return ""
    v = tuple(v)
    digits = v[2] if len(v) > 2 else 2
    return "%d.%s" % (v[0], str(v[1]).zfill(6)[:max(1, digits)])


def parse_volume_id(vol):
    """``("sonic", (0, 926000, 3))`` for ``Sonic-v00.926``, or ``None``."""
    m = _VOLUME_ID.match((vol or "").strip())
    if not m:
        return None
    return m.group(1).lower(), version_of(m.group(2), m.group(3))


def _title(key):
    from .games import GAME_DB
    for info in GAME_DB.values():
        if any(p in key or key in p for p in info["filename_prefixes"]):
            return info["display"]
    return key.title()


def release_info(vol):
    """``{"key", "version", "build", "title", "edition"}`` for the ISO whose
    volume ID is *vol*, or ``None``.  Every edition runs the same ISO, so
    the edition is left out."""
    got = parse_volume_id(vol)
    if got is None:
        return None
    key, version = got
    return {"key": key, "version": list(version),
            "build": version_words(version), "title": _title(key),
            "edition": ""}


def iso_print(path):
    """``{"print", "sidx", "label", "official", "manufacturer"}`` for a JJP
    full-install ISO, ``None`` for anything else.  Reads a few MiB."""
    got = read_volume_id(path)
    if got is None:
        return None
    vol, pvd = got
    rel = release_info(vol)
    if rel is None:
        return None
    pr = lineage.file_print(path, "jjp-iso", pvd)
    stock = STOCK.get(vol)
    return {"print": pr, "sidx": vol,
            "label": ("%s %s" % (rel["title"], rel["build"])) if stock else "",
            "official": bool(stock) and stock == pr, "manufacturer": "jjp"}


def parse_support_page(text):
    """``{key: version}``: the newest full-install ISO of every title a JJP
    support page links (both mirrors name the same file)."""
    newest = {}
    for m in _ISO_LINK.finditer((text or "").lower()):
        v = version_of(m.group(2), m.group(3))
        if v > newest.get(m.group(1), ()):
            newest[m.group(1)] = v
    return newest
