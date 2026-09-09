"""How many game images a Spike 2 card carries — and which one this app edits.

A multi-boot card (the Multi-boot tab's own ``mkmulticard.py``, or anyone
else's) holds SEVERAL complete games and a boot menu that picks one at
power-up.  Everything else in this app works on exactly ONE of them:

* :func:`..stern.engine._locate` walks the card's PRIMARY ext partitions and
  takes the first one holding an ``image.bin`` with a game beside it.  On
  every layout ``mkmulticard.py`` writes, that is p3 — the PRIMARY image, the
  one the card was built around.  The extras live either in logical
  partitions (``--layout parts``/``multi``, which :func:`formats.linux_partitions`
  never even enumerates) or as ``img1/``, ``img2/`` … directories beside the
  primary's own tree (``--layout store``), which the breadth-first search
  reaches only after the primary's game folder.
* A Write copies the WHOLE card and patches it in place, so the build is
  still a working multi-boot card — with the primary image changed and every
  other image, and the menu, carried through untouched.

So the answer to "which image do my replaced assets replace?" is: the first
one, always, and there is no way to pick another.  DragonRR (PAD-121, then
PAD-122) worked on a multi-boot card for a while before deducing that:
"if this is correct then you need to tell the user that one way or another so
they don't try to do something that just won't work."  This module is what
does the telling — it counts the images without extracting anything, and
:func:`source_note` / :func:`log_lines` render the one explanation that the
Extract/Build confirm, the run log and the Image Info report all share.

The count is STRUCTURAL, like ``tools/spike2_emu/parts.py --list-games``: a
games tree is a directory holding ``spk`` plus a game folder with an
``image.bin`` in it.  Nothing here reads a file's contents, so the probe is a
handful of directory reads even on a 32 GB card, and it is safe to run on the
Tk thread when the user presses a button.  ``Ext4Reader`` and ``formats`` are
module globals so a test can swap in the lightweight fake filesystem
(``tests/_ext4_fake``) the Partition Explorer tests use.
"""

import os
import re
from collections import namedtuple

from ...core.longpath import ext as _lp
from . import formats
from .ext4 import S_IFDIR, S_IFMT, Ext4Reader

#: One game image on a card.  ``part`` is the partition number the machine
#: knows it by (p3, p7, …), ``subdir`` the ``imgN`` directory inside that
#: partition (``""`` for a whole-partition tree) and ``folder`` the card's own
#: game-folder name (``godzilla_pro``) — the model name every Spike 2 path
#: starts with.
CardImage = namedtuple("CardImage", "part subdir folder")

_MBR_LINUX = 0x83

#: Root entries that are never a game folder: the shared asset tree, ext4's
#: own, and the store layout's dedup pool (``mkmulticard.py --layout store``).
_NOT_A_GAME = {"spk", "lost+found", ".blobs"}

#: The extras' directories inside a games partition — ``img1``, ``img2``, …
#: (``mkmulticard.py``'s multi and store layouts).
_IMG_DIR = re.compile(r"^img(\d+)$")

#: A card nobody sane built; stop counting rather than walk a corrupt tree.
_MAX_IMAGES = 64


def _children(reader, ino):
    """``{name: inode_number}`` of the directory *ino*, or ``{}``."""
    try:
        node = reader.read_inode(ino)
    except Exception:
        return {}
    if (node["mode"] & S_IFMT) != S_IFDIR:
        return {}
    out = {}
    try:
        for name, child, _ftype in reader._iter_dir(node):
            if name not in (".", ".."):
                out.setdefault(name, child)
    except Exception:
        return {}
    return out


def _game_folder(reader, names):
    """The game-folder name among *names* (a directory holding ``image.bin``),
    or ``""`` when this tree has none.

    Sorted so the answer can't depend on directory-entry order, and the
    ``imgN`` directories are skipped — on the store layout they sit beside the
    primary's own folder and each holds an ``image.bin`` of its own.
    """
    for name in sorted(names):
        if name in _NOT_A_GAME or _IMG_DIR.match(name):
            continue
        if "image.bin" in _children(reader, names[name]):
            return name
    return ""


def _images_in(reader, part_num):
    """Every games tree in one ext partition, primary tree first."""
    root = _children(reader, 2)
    if not root:
        return []
    out = []
    if "spk" in root:
        folder = _game_folder(reader, root)
        if folder:
            out.append(CardImage(part_num, "", folder))
    # ...then the extras this partition carries as img1/, img2/, … — the
    # multi layout's whole p7, or the store layout's, beside the primary's.
    subs = sorted((int(m.group(1)), m.group(0))
                  for m in (_IMG_DIR.match(n) for n in root) if m)
    for _n, sub in subs:
        names = _children(reader, root[sub])
        if "spk" not in names:
            continue                      # /data, /dump, a stray directory
        folder = _game_folder(reader, names)
        if folder:
            out.append(CardImage(part_num, sub, folder))
    return out


def _open_source(path):
    """A seekable byte stream over a card image — or over the card ITSELF.

    "From SD card" is the mode a multi-boot card is most likely to be read
    in, and a block device refuses a read that is not a whole number of
    sectors, so the device goes through :class:`..core.rawdevice.RawDeviceFile`
    (which aligns underneath) exactly as the extract's own reads do.
    """
    from ...core.rawdevice import RawDeviceFile, is_device_path
    if is_device_path(path):
        return RawDeviceFile(path)
    return open(_lp(path), "rb")


def card_images(path):
    """Every game image on the card at *path*, in boot-menu order.

    The primary (p3) comes first because that is the order ``mkmulticard.py``
    builds the menu in, and it is the image this app reads and writes.  An
    unreadable card, or one that is not a Spike 2 card at all, gives ``[]``;
    a normal single-game card gives one entry.  Logical partitions are walked
    too (``formats.parse_all_partitions_file``) — the extras of the default
    layout live there and the primary-only enumeration the extract uses would
    report a multi-boot card as an ordinary one.
    """
    try:
        f = _open_source(path)
    except (OSError, ValueError):
        return []
    out = []
    try:
        for index, ptype, lba, sectors in formats.parse_all_partitions_file(f):
            if ptype != _MBR_LINUX:
                continue
            try:
                reader = Ext4Reader(f, lba * 512, sectors * 512)
            except Exception:
                continue                  # not ext, or a partition we can't open
            out.extend(_images_in(reader, index + 1))
            if len(out) >= _MAX_IMAGES:
                break
    except Exception:
        return out
    finally:
        f.close()
    return out


# --------------------------------------------------------------------------
# saying it
# --------------------------------------------------------------------------

_EDITIONS = {"le": "LE", "pro": "Pro", "prem": "Premium", "premium": "Premium",
             "se": "SE"}


def pretty(image):
    """``CardImage(3, "", "godzilla_pro")`` -> ``"Godzilla Pro"``.

    The card's game folder is the only name for an image this probe can read
    without mounting the boot menu's own config, and it is the name the user
    already sees in every extracted path.
    """
    words = [w for w in (image.folder or "").replace("_", " ").split() if w]
    if not words:
        return "image %d" % image.part
    return " ".join(_EDITIONS.get(w.lower(), w.capitalize()) for w in words)


#: What to do instead — the workflow that DOES change another image, in the
#: words of the tabs it happens on.  One definition, shared by the confirm
#: dialog, the run log and the Image Info report, so the three can't drift.
HOW_TO_EDIT_ANOTHER = (
    "To change one of the others: extract THAT image on its own, replace what "
    "you want and build it, then load this card on the Multi-boot tab, point "
    "that image's row at your new build and update the card in place.")

TITLE = "Multi-boot card"


def summary(images):
    """One line: what this card is and which image is in play."""
    return ("This card carries %d game images and a boot menu that picks one "
            "at power-up. This app reads and writes only the first one, %s."
            % (len(images), pretty(images[0])))


def source_note(images):
    """The Extract/Build confirm's text, or ``""`` for a single-image card.

    Deliberately says what a Build still GIVES you — a working multi-boot
    card with the first image changed — because "only the first image" on its
    own reads as "don't bother", and the tester who asked for this warning had
    already decided the whole exercise was pointless.
    """
    if len(images) < 2:
        return ""
    lines = [summary(images), "",
             "On the card:"]
    for i, img in enumerate(images):
        lines.append("    %d. %s%s"
                     % (i + 1, pretty(img),
                        "      <- the one this app edits" if i == 0 else ""))
    lines += [
        "",
        "Your extract, your replaced assets and the card a Build writes are "
        "all that first image. The other images and the menu are copied "
        "through untouched, so a Build still gives you a working multi-boot "
        "card with the first image changed.",
        "",
        HOW_TO_EDIT_ANOTHER,
    ]
    return "\n".join(lines)


def log_lines(images):
    """The same explanation for a run log, ``[]`` for a single-image card.

    Tagged ``[multi-boot]`` so it stands out in a pasted log the way the
    emulator's own card lines do.
    """
    if len(images) < 2:
        return []
    out = ["[multi-boot] " + summary(images)]
    for i, img in enumerate(images):
        out.append("[multi-boot]     %d. %s (p%d%s)%s"
                   % (i + 1, pretty(img), img.part,
                      "/" + img.subdir if img.subdir else "",
                      "  <- this run" if i == 0 else ""))
    out.append("[multi-boot] The other images are carried through untouched. "
               + HOW_TO_EDIT_ANOTHER)
    return out


def note_for_path(path):
    """:func:`source_note` for the card at *path* (``""`` when it isn't one)."""
    return source_note(images_for_path(path))


_CACHE = {}


def images_for_path(path):
    """:func:`card_images`, cached on the file's identity (path, size, mtime).

    The confirm, the run that follows it and the Image Info report ask the
    same question of the same file minutes apart, and a card on a slow USB
    drive is a couple of hundred directory reads away from the answer.
    """
    try:
        st = os.stat(_lp(path))
        key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    except OSError:
        # A raw device has no identity to key on (and a path that isn't there
        # has nothing to remember) — probe, don't cache.
        return card_images(path)
    hit = _CACHE.get(key)
    if hit is None:
        hit = card_images(path)
        if len(_CACHE) > 32:              # a session's worth; never unbounded
            _CACHE.clear()
        _CACHE[key] = hit
    return hit
