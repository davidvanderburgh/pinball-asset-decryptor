#!/usr/bin/env python3
"""gameinfo.py [name] - which Spike 2 title the rig is pointed at, and where its parts are.

Every other tool here used to carry `/home/david/spike2root/games/godzilla_pro`
as a constant. This is the one place that knows, so a second title is a
directory next to the first rather than a fork of the rig.

    gameinfo.py              # what is installed, and which is active
    gameinfo.py turtles_pro  # everything known about one title

WHICH TITLE IS ACTIVE, in order:

  1. `PAD_GAME` in the environment.
  2. the `games/game` symlink, which is what run_game.sh points at the title it
     is about to boot - and what the machine itself uses, so reading it is not a
     rig invention.
  3. the only title present, if there is exactly one.

BOTH SIDES OF THE VM BOUNDARY. The guest sees `/games/<title>`, WSL sees
`/home/david/spike2root/games/<title>`, and the playfield window - which runs on
WINDOWS, because this WSL has no GUI toolkit - sees the same directory through
`\\\\wsl.localhost`. All three are the same files; only the prefix differs, so
that is all this switches on.

THE GENERATED TABLES live beside the rig, per title, under `games/<title>/`:
device_xy.txt, switch_xy.txt, led_io.txt and a copy of the playfield artwork.
They are derived from the game binary (devicexy.py) and from the wire (ledio.py)
and are checked in, so the playfield window opens on a machine that has never
extracted a card.
"""
import os
import sys

#: The rootfs, as WSL sees it.
WSL_ROOT = "/home/david/spike2root"

#: The same rootfs as WINDOWS sees it. Not a guess: WSL publishes every distro
#: under this UNC path, and the playfield window already reads dump/padled
#: through it.
WIN_ROOT = r"\\wsl.localhost\Ubuntu\home\david\spike2root"

HERE = os.path.dirname(os.path.abspath(__file__))

#: Where the per-title generated tables live, relative to this file.
TABLE_DIR = os.path.join(HERE, "games")


def root():
    """The rootfs path in the form THIS interpreter can open."""
    return WIN_ROOT if sys.platform == "win32" else WSL_ROOT


def _join(*parts):
    return os.path.join(root(), *parts)


def installed():
    """Titles extracted into the rootfs, i.e. directories holding a `game` ELF."""
    g = _join("games")
    try:
        names = sorted(os.listdir(g))
    except OSError:
        return []
    return [n for n in names
            if os.path.isfile(os.path.join(g, n, "game")) and not os.path.islink(
                os.path.join(g, n))]


def active(name=None):
    """The title to work with, by the rules in the header. May not be installed:
    the tables are checked in, so the window works with no rootfs at all."""
    if name:
        return name
    env = os.environ.get("PAD_GAME")
    if env:
        return env
    link = _join("games", "game")
    try:
        # games/game is a symlink to <title>/game on the machine and here.
        target = os.readlink(link)
        part = target.replace("\\", "/").split("/")
        if len(part) >= 2:
            return part[-2]
    except OSError:
        pass
    have = installed()
    if len(have) == 1:
        return have[0]
    tables = tables_installed()
    if len(tables) == 1:
        return tables[0]
    return "godzilla_pro"


def tables_installed():
    """Titles that have generated tables checked in, whether or not extracted."""
    try:
        return sorted(n for n in os.listdir(TABLE_DIR)
                      if os.path.isfile(os.path.join(TABLE_DIR, n, "device_xy.txt")))
    except OSError:
        return []


def game_dir(name=None):
    return _join("games", active(name))


def elf(name=None):
    return os.path.join(game_dir(name), "game")


def assets(name=None):
    return os.path.join(game_dir(name), "assets")


def table_dir(name=None):
    return os.path.join(TABLE_DIR, active(name))


def table(what, name=None):
    return os.path.join(table_dir(name), what)


def playfield_png(name=None):
    """The playfield artwork.

    The game ships it - `assets/nuk/images/Test/*_playfield.png` - and the copy
    beside the tables is exactly those bytes, so the window can open without the
    card extracted. Prefer the checked-in copy: it is the one the coordinates in
    device_xy.txt were checked against, and a title with both a Pro and an LE
    drawing has two candidates in the assets with no way to tell them apart by
    name alone.
    """
    local = table("playfield.png", name)
    if os.path.exists(local):
        return local
    return find_playfield_art(name)


def find_playfield_art(name=None):
    """The title's playfield drawing inside its own assets, or None.

    A title ships one per model (scaled_godzilla_pro_playfield.png and
    scaled_godzilla_le_playfield.png sit side by side), so the directory name is
    used to choose: `godzilla_pro` prefers the file whose name carries "pro".
    """
    d = os.path.join(assets(name), "nuk", "images", "Test")
    try:
        found = [f for f in sorted(os.listdir(d))
                 if f.lower().endswith("_playfield.png")]
    except OSError:
        return None
    if not found:
        return None
    want = active(name).lower().split("_")
    for f in found:
        if all(w in f.lower() for w in want if w):
            return os.path.join(d, f)
    for f in found:                       # fall back on the model suffix alone
        if want and want[-1] in f.lower():
            return os.path.join(d, f)
    return os.path.join(d, found[0])


def png_size(path):
    """(width, height) from a PNG header, so nothing has to hard-code it."""
    import struct
    with open(path, "rb") as f:
        d = f.read(33)
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", d[16:24])


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    print("rootfs seen as   : %s" % root())
    print("extracted titles : %s" % (", ".join(installed()) or "(none)"))
    print("titles with tables: %s" % (", ".join(tables_installed()) or "(none)"))
    print("active title     : %s" % active(name))
    print("  game dir       : %s" % game_dir(name))
    print("  ELF            : %s%s"
          % (elf(name), "" if os.path.exists(elf(name)) else "   (NOT EXTRACTED)"))
    print("  tables         : %s" % table_dir(name))
    art = playfield_png(name)
    print("  playfield art  : %s %s"
          % (art, png_size(art) if art and os.path.exists(art) else "(missing)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
