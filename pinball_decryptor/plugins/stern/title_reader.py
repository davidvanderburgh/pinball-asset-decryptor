"""Read what a Spike 2 card's game build offers, once per build, with progress.

A card is read in three steps, each cached on this machine by the game program's SHA-1 so
the second look at the same build is instant:

* ``program`` - the game program itself, read off the card's games partition;
* ``port``    - where that build keeps the functions and globals the runtime hooks
  (:mod:`.port_derive`: a shipped port, one derived earlier, or one derived now);
* ``stock``   - the build's own modes and the numbers they use
  (:mod:`.stock_reader`: a hand table, one generated earlier, or one generated now).

:func:`read_card` does all three and reports ``progress(step, fraction, text)`` as it goes,
where ``step`` is one of :data:`STEPS` and ``fraction`` runs 0..1 within that step. A
``cancel`` callable that returns True stops it at the next step boundary with
:class:`Cancelled`. Nothing here touches the card: it is opened read-only.
"""

import hashlib
import os
import sys
import time
from dataclasses import dataclass, field

#: the steps :func:`read_card` reports, in order
STEPS = ("program", "port", "stock")

#: words for each step, for a progress line
STEP_WORDS = {
    "program": "Reading the game program",
    "port": "Finding where this build keeps what it needs",
    "stock": "Reading the game's own rules",
}


class Cancelled(Exception):
    """The reader was asked to stop."""


class TitleReadError(ValueError):
    """The card could not be read, with the reason in words."""


def cache_dir(kind):
    """The machine-local folder for one kind of cached per-build data (``ports``,
    ``stock_tables``, ...), created on first use. ``PAD_TITLE_CACHE`` overrides the root
    (tests point it at a temporary folder)."""
    root = os.environ.get("PAD_TITLE_CACHE")
    if not root:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Caches")
        else:
            base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        root = os.path.join(base, "pinball_decryptor", "titles")
    path = os.path.join(root, kind)
    os.makedirs(path, exist_ok=True)
    return path


def family_of(elf):
    """``"cmode"``, ``"crule"`` or ``"c"``: which rule system a game program is built on,
    from the RTTI names it carries (a C++ rule manager's typeinfo name survives a stripped
    program). ``"c"`` means no C++ rule manager at all: the rules are plain C."""
    if b"13crule_manager" in elf:
        return "crule"
    if b"13cmode_manager" in elf:
        return "cmode"
    return "c"


@dataclass
class TitleRead:
    """What one card's game build offers."""
    game: str                      # the card's game directory, e.g. "beatles"
    version: str                   # "1.29.0"
    elf_sha1: str = ""
    family: str = ""               # family_of()
    port_path: str = ""            # "" when no port could be had
    port_origin: str = ""          # "shipped" | "derived" | ""
    port_proven: bool = False      # emulator-proven (a shipped port says so in its header)
    port_missing: tuple = ()       # what a port could not place, as words, when there is none
    stock_build: object = None     # a stock_modes.Build, or None
    stock_origin: str = ""         # "hand" | "generated" | ""
    notes: tuple = ()              # sentences for the person, in order
    stock_notes: tuple = ()        # the table's own (a caveat on its numbers, why there is none)
    captions: dict = field(default_factory=dict)   # AD_NAME -> the operator menu's caption
    seconds: float = 0.0
    timings: dict = field(default_factory=dict)   # step -> seconds


def _say(progress, step, frac, text=""):
    if progress is not None:
        try:
            progress(step, max(0.0, min(1.0, float(frac))), text or STEP_WORDS.get(step, step))
        except Exception:
            pass


def _check(cancel):
    if cancel is not None and cancel():
        raise Cancelled()


def game_program(card):
    """``(game_dir, version, elf_bytes)`` of a Spike 2 card image, read-only."""
    from .explorer import CardImage
    from .mode_tryit import card_title, TryItError
    try:
        game, version, part = card_title(card)
    except TryItError as e:
        raise TitleReadError(str(e)) from None
    if not game:
        raise TitleReadError("%s does not say which game it is." % os.path.basename(card))
    import tempfile
    img = CardImage(card)
    with img:
        fd, tmp = tempfile.mkstemp(prefix="pad_game_", suffix=".elf")
        os.close(fd)
        try:
            img.extract_file(part, "/%s/game" % game, tmp)
            with open(tmp, "rb") as f:
                elf = f.read()
        except (OSError, ValueError) as e:
            raise TitleReadError("The game program could not be read from %s: %s"
                                 % (os.path.basename(card), e)) from None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if elf[:4] != b"\x7fELF":
        raise TitleReadError("%s/game on %s is not a game program." % (game, os.path.basename(card)))
    return game, version, elf


def read_elf(elf, game, version, progress=None, cancel=None):
    """:class:`TitleRead` for a game program already in memory."""
    from . import port_derive, stock_reader
    t0 = time.monotonic()
    out = TitleRead(game=game, version=version, elf_sha1=hashlib.sha1(elf).hexdigest(),
                    family=family_of(elf))
    notes = []
    _check(cancel)
    t = time.monotonic()
    _say(progress, "port", 0.0)
    pr = port_derive.ensure_port(elf, game, version,
                                 progress=lambda f, s="": _say(progress, "port", f, s),
                                 cancel=cancel)
    out.port_path, out.port_origin, out.port_proven = pr.path, pr.origin, pr.proven
    out.port_missing = tuple(pr.missing)
    notes.extend(pr.notes)
    out.timings["port"] = time.monotonic() - t
    _say(progress, "port", 1.0)
    _check(cancel)
    t = time.monotonic()
    _say(progress, "stock", 0.0)
    tr = stock_reader.ensure_table(elf, game, version,
                                   progress=lambda f, s="": _say(progress, "stock", f, s),
                                   cancel=cancel)
    out.stock_build, out.stock_origin = tr.build, tr.origin
    notes.extend(tr.notes)
    out.stock_notes = tuple(tr.notes)
    if tr.build is not None and tr.build.adjustment_numbers():
        _say(progress, "stock", 1.0, "Reading the operator menu's words")
        _check(cancel)
    out.captions = stock_reader.captions_for(elf, tr.build, out.elf_sha1)
    out.timings["stock"] = time.monotonic() - t
    _say(progress, "stock", 1.0)
    out.notes = tuple(notes)
    out.seconds = time.monotonic() - t0
    return out


def read_card(card, progress=None, cancel=None):
    """:class:`TitleRead` for a card image: the game program, its port and its own modes."""
    t0 = time.monotonic()
    _say(progress, "program", 0.0)
    game, version, elf = game_program(card)
    t_prog = time.monotonic() - t0
    _say(progress, "program", 1.0)
    out = read_elf(elf, game, version, progress=progress, cancel=cancel)
    out.timings["program"] = t_prog
    out.seconds += t_prog
    return out
