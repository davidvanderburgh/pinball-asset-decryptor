"""PAD-612: the Modes tab's Playfield view - the game's own playfield picture, off the person's card, and where
each insert sits on it, from the title's port.

The picture is the one the game's own test menu draws its lamps on: a loose PNG under
``<game>/assets/nuk/images/<a test folder>/`` whose name says "playfield" (``scaled_godzilla_pro_playfield.png``),
one per model on some titles. It is read straight out of the card image (the read-only ext4 reader), never
bundled with the app: no manufacturer art ships in PAD.

The places are the port's ``lamp`` lines' comments, ``at X,Y`` on that same picture (lampmap.py writes them from the
game's device table; pad_mode_runtime.c reads the same words for its light shows), with each line's shot mask: an
insert lights for the shots whose mask it shares, as the runtime lights a shot's inserts.

The choice between pictures follows the emulator's playfield window (tools/spike2_emu/gameinfo.py,
find_playfield_art), which learned each rule on a real title: the word anywhere in the name, whole words to pick
the model, any folder whose name says test, "TOP" for the 2025 generation, and an LE falling back to the
Premium's drawing, never a Pro to it.
"""

import os
import re
import struct
import threading

#: the picture's name must hold one of these (the first that finds any wins)
_WORDS = ("playfield", "top")
_KNOWN_DIRS = ("Test", "TestMode")
_LAMP_AT = re.compile(r"\bat\s+(-?\d+)\s*,\s*(-?\d+)")


class PlayfieldError(Exception):
    """The card cannot give a playfield picture; the words say why."""


def _tokens(name):
    return set(re.split(r"[^a-z0-9]+", name.lower())) - {""}


def png_size(data):
    """``(width, height)`` from a PNG's header, or None when it is not a PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


def art_dirs(listing):
    """The folders under ``images`` that may hold the drawing, in the order they are tried. ``listing``:
    ``{folder: [names]}`` for the top level (``""``) and each folder (``"Test"``, ``"System/TestMode"``)."""
    top = sorted(listing.get("", ()))
    out = [d for d in _KNOWN_DIRS]
    out += [d for d in top if "test" in d.lower() and d not in _KNOWN_DIRS]
    for d in top:
        out += [d + "/" + k for k in sorted(listing.get(d, ())) if "test" in k.lower()]
    return out


def pick_art(listing, game_dir):
    """The drawing's path under ``images`` (``"Test/scaled_godzilla_pro_playfield.png"``), or "" when the title
    ships none. ``game_dir``: the card's game folder (``godzilla_le``), whose words pick the model's drawing."""
    found, where = [], ""
    for d in art_dirs(listing):
        names = sorted(n for n in listing.get(d, ()) if n.lower().endswith(".png"))
        for word in _WORDS:
            hits = [n for n in names if (word in n.lower() if word == "playfield" else word in _tokens(n))]
            if hits:
                break
        if hits:
            found, where = hits, d
            break
    if not found:
        return ""
    want = _tokens(game_dir or "")
    model = (game_dir or "").lower().rsplit("_", 1)[-1]
    pick = (next((n for n in found if want and want <= _tokens(n)), None)
            or next((n for n in found if model and model in _tokens(n)), None))
    if pick is None and model == "le":          # an LE's playfield is the Premium's
        pick = next((n for a in ("premium", "prem", "pre") for n in found if a in _tokens(n)), None)
    return where + "/" + (pick or found[0])


def insert_places(port_path):
    """``[{name, shot (mask), x, y}]`` of every port ``lamp`` line placed on the playfield picture (``at X,Y``,
    not 0,0), in the port's order. A missing port gives []."""
    from . import mode_project as MP
    out = []
    try:
        with open(port_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        if not line.startswith("lamp "):
            continue
        rest = line[5:]
        lamp = MP._port_lamp(rest)
        m = _LAMP_AT.search(rest.partition("#")[2])
        if not lamp or not m:
            continue
        x, y = int(m.group(1)), int(m.group(2))
        if x <= 0 and y <= 0:
            continue
        name, _ids, mask = lamp
        out.append({"name": name, "shot": mask, "x": x, "y": y})
    return out


def _listing(reader, images):
    """``{folder: [names]}`` of ``images`` and its folders one and two levels down (enough for every
    :func:`art_dirs` choice), plus ``{path: inode}`` of the files."""
    from .ext4 import S_IFDIR, S_IFMT
    listing, files = {}, {}

    def walk(node, rel, depth):
        names = []
        for n, child, t in reader._iter_dir(node):
            if n in (".", ".."):
                continue
            names.append(n)
            path = (rel + "/" + n) if rel else n
            if t in (2, 0) and depth < 2:
                try:
                    kid = reader.read_inode(child)
                except Exception:                       # noqa: BLE001 - a damaged entry
                    continue
                if (kid["mode"] & S_IFMT) == S_IFDIR:
                    walk(kid, path, depth + 1)
                    continue
            files[path] = child
        listing[rel] = names

    walk(images, "", 0)
    return listing, files


def read_art(image, game_dir):
    """``(png bytes, card path)`` of the title's playfield drawing on the card image ``image``. Raises
    :class:`PlayfieldError` saying why when there is none or the card cannot be read."""
    from .ext4 import Ext4Reader
    from .formats import linux_partitions, open_card
    from . import mode_write as MW
    name = os.path.basename(str(image))
    try:
        parts = linux_partitions(image)
    except (OSError, ValueError) as e:
        raise PlayfieldError("%s could not be read (%s)" % (name, e)) from None
    rel = "%s/assets/nuk/images" % game_dir
    with open_card(image) as f:
        for off, size in parts:
            try:
                reader = Ext4Reader(f, off, size)
                node = MW.lookup(reader, rel)
            except Exception:                           # noqa: BLE001 - not an ext partition
                continue
            if node is None:
                continue
            listing, files = _listing(reader, node)
            pick = pick_art(listing, game_dir)
            if not pick:
                raise PlayfieldError("%s ships no playfield picture" % game_dir)
            data = bytes(reader.read_file_bytes(reader.read_inode(files[pick])))
            if not png_size(data):
                raise PlayfieldError("/%s/%s is not a PNG" % (rel, pick))
            return data, "/%s/%s" % (rel, pick)
    raise PlayfieldError("%s has no %s folder" % (name, rel))


_memo = {}
_memo_lock = threading.Lock()


def card_art(image, game_dir):
    """:func:`read_art`, kept per card image (its size and time) and game folder: a tab switch does not read the
    card again. Returns ``(png bytes or None, card path or the words why not)``."""
    try:
        st = os.stat(image)
        key = (os.path.normcase(os.path.abspath(image)), st.st_size, st.st_mtime_ns, game_dir)
    except OSError as e:
        return None, "the card image could not be opened (%s)" % (e.strerror or e)
    with _memo_lock:
        if key in _memo:
            return _memo[key]
    try:
        got = read_art(image, game_dir)
    except PlayfieldError as e:
        got = (None, str(e))
    except OSError as e:
        got = (None, "the card image could not be read (%s)" % (e.strerror or e))
    with _memo_lock:
        _memo.clear()
        _memo[key] = got
    return got


def _kept_path(game_dir):
    from .title_reader import cache_dir
    return os.path.join(cache_dir("playfield_art"), "%s.png" % re.sub(r"[^a-z0-9_]+", "_", game_dir.lower()))


def kept_art(game_dir):
    """PAD-623: the picture last read for ``game_dir`` on this computer (off the person's own card, kept in the
    machine's cache, never shipped), or None."""
    try:
        with open(_kept_path(game_dir), "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if png_size(data) else None


def _keep(game_dir, data):
    try:
        path = _kept_path(game_dir)
        if os.path.isfile(path) and os.path.getsize(path) == len(data):
            return
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        pass                                            # a cache: the picture still shows this time


def game_art(images, game_dir):
    """PAD-623: ``game_dir``'s playfield picture from the first of ``images`` (cards of that game, best first) that
    is on this computer and holds one, else the one kept from an earlier read (:func:`kept_art`) - so a project whose
    card was moved or deleted still shows it. Returns ``(png bytes or None, card path or the words why not)``; the
    words are the first card's."""
    why = ""
    for image in images:
        if not image or not os.path.isfile(image):
            continue
        data, where = card_art(image, game_dir)
        if data:
            _keep(game_dir, data)
            return data, where
        why = why or where
    data = kept_art(game_dir)
    if data:
        return data, "kept from an earlier read of a %s card" % game_dir
    return None, why or "no %s card is on this computer to read it from" % game_dir
