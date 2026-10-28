"""What a Barrels of Fun ``.fun`` update is, and which build of it is newest
on BoF's public code-update pages (PAD-787, My machines).

A BoF machine runs the last ``.fun`` it was updated with, and BoF names its
builds by date.  The date is read from the file itself, never its name
alone (David's copies are plain ``lab.fun`` / ``winchester.fun``):

* the GPG titles (Labyrinth, Dune, Winchester): the first tar member, from a
  few KiB of the stream decrypted in Python (:mod:`.fun_head`);
* Bon Jovi (a systemd disk image): the inner root image's name in the outer
  EROFS (``bon-jovi_2026.10.01.img.root-x86-64``).

The release key a machine row carries (lineage's ``sidx``) is
``<game>-YYYY.MM.DD``.  BoF's shop site has a code-update page per title,
each linking one Dropbox zip named for the build (``BOF_WMH_20261001.zip``);
that name is all that is read.  Nothing is downloaded.
"""

import datetime
import os
import re

from ...core import lineage

#: BoF's code-update hub: the link a row shows when its title has no page.
SUPPORT_PAGE = "https://shop.kollectfun.com/code-update/"
_PAGE = "https://shop.kollectfun.com/%s-code-update/"
#: Release key -> its code-update page.  Measured 2026-10-27.
PAGES = {
    "labyrinth": _PAGE % "labyrinth",
    "dune": _PAGE % "dune",
    "winchester": _PAGE % "winchester",
    "bonjovi": _PAGE % "bon-jovi",
}
#: The code in BoF's zip names (``BOF_<code>_<YYYYMMDD>.zip``) -> key.
_ZIP_CODES = {"lab": "labyrinth", "dune": "dune", "wmh": "winchester",
              "jovi": "bonjovi"}

#: ``<game>-YYYY.MM.DD`` -> the print of BoF's own ``.fun`` (:func:`fun_print`
#: over the update as downloaded).  A file whose release is listed but whose
#: print differs is a modified update (a PAD build); a release not listed is
#: one PAD has no record of.
STOCK = {
    "labyrinth-2026.01.30": "6e68bcabe3c17fbe11089c5d1c6dcffe",
    "dune-2026.05.13": "194a9bced9fbec66216bb2ce82568387",
    "winchester-2026.04.29": "14850a91a5e212380e93c7fe80ee31b2",
    "winchester-2026.05.27": "29626fc7806abd2b147293e19cad8a27",
    "bonjovi-2026.10.01": "c94bd4f8b63364d5b4d8d79bb19bcbb0",
}

_SIDX = re.compile(r"^([a-z0-9]+)-(\d{4})\.(\d{2})\.(\d{2})$")
_ZIP_LINK = re.compile(r"bof_([a-z0-9]+)_(20\d\d)(\d\d)(\d\d)\.zip")
_DDI_ROOT = re.compile(r"_(20\d\d)\.(\d\d)\.(\d\d)\.img\.root-")


def version_words(v):
    """``(2026, 10, 1)`` -> ``"2026.10.01"`` (BoF's own spelling)."""
    if not v:
        return ""
    return "%04d.%02d.%02d" % tuple(v)[:3]


def _ddi_date(path):
    from .ddi_container import Erofs, _find_payload_partition
    with open(path, "rb") as f:
        off, _n = _find_payload_partition(f)

        def read(o, n):
            f.seek(off + o)
            return f.read(n)
        outer = Erofs(read)
        for name, _nid in outer.listdir(outer.inode(outer.root_nid)):
            m = _DDI_ROOT.search(name)
            if m:
                return datetime.date(*(int(x) for x in m.groups()))
    return None


def fun_build(path):
    """``(game key, date)`` of the ``.fun`` at *path*, or ``None`` when it
    isn't a BoF update this can read."""
    from .games import GAME_DB
    from .pipeline import detect_game
    key = detect_game(path)
    if key is None:
        return None
    info = GAME_DB[key]
    if info.get("container") == "ddi":
        date = _ddi_date(path)
    else:
        from . import fun_head
        date = fun_head.build_date(*fun_head.first_member(
            path, info["passphrase"]))
    return (key, date) if date else None


def parse_sidx(sidx):
    """``("winchester", (2026, 4, 29))`` for ``winchester-2026.04.29``."""
    m = _SIDX.match((sidx or "").strip())
    if not m:
        return None
    return m.group(1), tuple(int(m.group(i)) for i in (2, 3, 4))


def release_info(sidx):
    """``{"key", "version", "build", "title", "edition"}`` for the update
    whose release key is *sidx*, or ``None``."""
    got = parse_sidx(sidx)
    if got is None:
        return None
    from .games import GAME_DB
    key, version = got
    title = (GAME_DB.get(key) or {}).get("display") or key.title()
    return {"key": key, "version": list(version),
            "build": version_words(version), "title": title, "edition": ""}


def fun_print(path):
    """``{"print", "sidx", "label", "official", "manufacturer"}`` for a BoF
    ``.fun``, ``None`` for anything else.  Reads a few MiB."""
    if not str(path).lower().endswith(".fun") or not os.path.isfile(path):
        return None
    got = fun_build(path)
    if got is None:
        return None
    key, date = got
    sidx = "%s-%s" % (key, date.strftime("%Y.%m.%d"))
    rel = release_info(sidx)
    pr = lineage.file_print(path, "bof-fun", sidx.encode())
    stock = STOCK.get(sidx)
    return {"print": pr, "sidx": sidx,
            "label": ("%s %s" % (rel["title"], rel["build"])) if stock else "",
            "official": bool(stock) and stock == pr, "manufacturer": "bof"}


def parse_code_page(text):
    """``{key: (y, m, d)}``: the newest build every BoF code-update page
    links, from its zip's name."""
    newest = {}
    for m in _ZIP_LINK.finditer((text or "").lower()):
        key = _ZIP_CODES.get(m.group(1))
        if key is None:
            continue
        try:
            v = datetime.date(*(int(m.group(i)) for i in (2, 3, 4)))
        except ValueError:
            continue
        v = (v.year, v.month, v.day)
        if v > newest.get(key, ()):
            newest[key] = v
    return newest
