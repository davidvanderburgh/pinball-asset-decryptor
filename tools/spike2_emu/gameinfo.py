#!/usr/bin/env python3
r"""gameinfo.py [name] - which Spike 2 title the rig is pointed at, and where its parts are.

Every other tool here used to carry one machine's path to one title as a
constant. This is the one place that knows, so a second title is a directory
next to the first rather than a fork of the rig.

    gameinfo.py              # what is installed, and which is active
    gameinfo.py turtles_pro  # everything known about one title

WHICH TITLE IS ACTIVE, in order:

  1. `PAD_GAME` in the environment.
  2. what run_game.sh PUBLISHED for the run in progress (`dump/title`), which is
     the only source that can name a title running straight off a card - the
     card's title directory is bind-mounted inside a private namespace and is
     not at `games/<title>` from out here at all.
  3. the `games/game` symlink, which is what the machine itself uses, so reading
     it is not a rig invention.
  4. the only title extracted, or the only title with derived tables, if there
     is exactly one of either.

It returns None rather than guessing when none of those answer. It used to fall
back to `godzilla_pro` - the title this rig was built against - which is a lie
on any other machine and exactly the class of thing this file exists to stop.

BOTH SIDES OF THE VM BOUNDARY. The guest sees `/games/<title>`, WSL sees
`$PAD_ROOT/games/<title>`, and the playfield window - which runs on WINDOWS,
because this WSL has no GUI toolkit - sees the same files through
`\\wsl.localhost`. All three are the same bytes; only the prefix differs, and
padpath.py is what knows how to spell each one HERE rather than on the machine
this was written on.

THE DERIVED TABLES - device_xy.txt, switch_xy.txt, led_io.txt, switch_list.txt
and a copy of the playfield artwork - are NOT checked in and are not written
beside the scripts. They are built from the title's own game binary and assets
by mktables.py, into `$PAD_TABLES/<title>/` (under the rootfs by default, see
padpath.py). Two reasons, and the second is the one that bit:

  * they are derived data. A copy in git goes stale against the binary it came
    from and, for the artwork, is a copy of Stern's art in a repository that
    otherwise ships none.
  * only ONE title's were ever generated. Every other title got a schematic and
    it looked like a property of the title rather than of the repository.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

HERE = padpath.RIG


def root():
    """The rootfs path in the form THIS interpreter can open."""
    return padpath.root()


def table_root():
    """Where derived per-title tables are cached, this side of the boundary."""
    return padpath.tables()


def _join(*parts):
    r = root()
    return os.path.join(r, *parts) if r else None


def published():
    """What run_game.sh said about the run in progress, or {}.

    `dump/title` is written before the game starts and names both the title and
    the directory its files are REALLY in. That second field is not redundant:
    on a card run the title directory is a read-only FUSE mount elsewhere on the
    machine, bind-mounted into `games/<title>` inside a private namespace that
    nothing outside the run can see. Reading `games/<title>` from here finds the
    empty stub directory that exists only to be a mountpoint.
    """
    d = padpath.dump()
    if not d:
        return {}
    out = {}
    try:
        with open(os.path.join(d, "title")) as f:
            for line in f:
                if "=" in line:
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def installed():
    """Titles extracted into the rootfs, i.e. directories holding a `game` ELF."""
    g = _join("games")
    if not g:
        return []
    try:
        names = sorted(os.listdir(g))
    except OSError:
        return []
    return [n for n in names
            if os.path.isfile(os.path.join(g, n, "game")) and not os.path.islink(
                os.path.join(g, n))]


def tables_installed():
    """Titles that have derived tables built, whether or not extracted."""
    t = table_root()
    if not t:
        return []
    try:
        return sorted(n for n in os.listdir(t)
                      if os.path.isfile(os.path.join(t, n, "device_xy.txt")))
    except OSError:
        return []


def active(name=None):
    """The title to work with, by the rules in the header, or None."""
    if name:
        return name
    env = padpath._env("PAD_GAME")
    if env:
        return env
    pub = published().get("name")
    if pub:
        return pub
    link = _join("games", "game")
    if link:
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
    return None


def game_dir(name=None):
    """The directory holding the title's `game` ELF and `assets/`, or None.

    Prefers what the run published, because that is the only answer that is
    right for a card run. Falls back to `games/<title>` in the rootfs, which is
    where an extracted title lives.
    """
    game = active(name)
    if not game:
        return None
    pub = published()
    if pub.get("name") == game and pub.get("dir"):
        # Published by a WSL-side script, so it is a POSIX path; the playfield
        # window reads this file from Windows and needs the other spelling.
        return padpath.to_win(pub["dir"]) if sys.platform == "win32" else pub["dir"]
    return _join("games", game)


def elf(name=None):
    d = game_dir(name)
    return os.path.join(d, "game") if d else None


def assets(name=None):
    d = game_dir(name)
    return os.path.join(d, "assets") if d else None


def table_dir(name=None):
    """Where this title's derived tables are cached."""
    t, game = table_root(), active(name)
    return os.path.join(t, game) if t and game else None


def table(what, name=None):
    d = table_dir(name)
    return os.path.join(d, what) if d else None


def playfield_png(name=None):
    """The playfield artwork, or None.

    The game ships it - `assets/nuk/images/Test/*_playfield.png` - and mktables
    copies exactly those bytes next to the tables. Prefer that copy for two
    reasons: it is the one the coordinates in device_xy.txt were checked
    against, and on a card run the assets themselves are on a FUSE mount that
    the playfield window (a Windows process) may not be able to reach at all.
    """
    local = table("playfield.png", name)
    if local and os.path.exists(local):
        return local
    return find_playfield_art(name)


def _tokens(filename):
    """A filename's words, lowercased: 'jaws_le_playfield_scaled.png' ->
    {jaws, le, playfield, scaled}."""
    import re
    return set(re.split(r"[^a-z0-9]+", filename.lower())) - {""}


def find_playfield_art(name=None):
    """The title's playfield drawing inside its own assets, or None.

    TWO THINGS HERE ARE NOT AS OBVIOUS AS THEY LOOK, and each cost a title.

    **The word "playfield" is not always a SUFFIX.** This matched
    `*_playfield.png` - which is how Godzilla
    (`scaled_godzilla_pro_playfield.png`) and John Wick
    (`john_wick_le_playfield.png`) spell it. Jaws puts the qualifier last,
    `jaws_le_playfield_scaled.png`, so a suffix test found nothing and the rig
    reported "this title ships no playfield drawing" about a title shipping two
    of them. Match on the word appearing anywhere instead.

    **Choosing between models needs WHOLE WORDS, not substrings.** A title
    ships one drawing per model side by side - `jaws_le_playfield_scaled.png`
    and `jaws_pro_playfield_scaled.png` - and the directory name picks. A
    substring test appears to work and does so by accident: looking for "le" in
    `jaws_pro_playfield_scaled.png` succeeds, because "scaLEd" contains it. It
    would have picked the Pro drawing for an LE machine as soon as the
    alphabetical order changed.

    **The folder is not always named "Test" either** (item 57, 2026-08-19,
    found auditing king_kong_le and metallica_spike): those two ship
    `assets/nuk/images/TestMode/*` and have NO `Test` folder at all, so the
    lookup below returned None before any filename was even looked at -
    "this title ships no playfield drawing" about a title that does. Try
    both; `Test` first since every title measured before this fix already
    uses it and nothing should change for them.
    """
    a = assets(name)
    if not a:
        return None
    found, d = [], None
    for sub in ("Test", "TestMode"):
        cand = os.path.join(a, "nuk", "images", sub)
        try:
            names = sorted(os.listdir(cand))
        except OSError:
            continue
        # The word is not always "playfield" either (2026-08-27, item 80's
        # dungeons_and_dragons_le): the 2025 generation names the drawing by
        # dev codename and view - Rope_LE-Premium-X8-X9_TOP_rotated_edit_
        # cropped.png beside Rope_PRO-X7_TOP_rotated_cropped.png and a
        # ROPE_BACK_PANEL_cropped.png - so the run reported "this title ships
        # no playfield drawing" about a title shipping one per model. "TOP"
        # as a whole word is that generation's marker for the playfield-from-
        # above view; BACK_PANEL and friends stay excluded because the word
        # test is exact, not a substring. "playfield" keeps first claim so no
        # title measured before this changes its pick.
        hits = [f for f in names
                if f.lower().endswith(".png") and "playfield" in f.lower()]
        if not hits:
            hits = [f for f in names
                    if f.lower().endswith(".png") and "top" in _tokens(f)]
        if hits:
            found, d = hits, cand
            break
    if not found:
        return None
    want = _tokens(active(name) or "")
    for f in found:
        if want and want <= _tokens(f):
            return os.path.join(d, f)
    # Fall back on the model word alone (`le` / `pro`), then on anything.
    model = (active(name) or "").lower().rsplit("_", 1)[-1]
    for f in found:
        if model and model in _tokens(f):
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
    argv = sys.argv[1:]
    # One-value queries, so a shell script can ask for a path without parsing
    # prose. The forensic scripts in this directory used to open the ELF at a
    # literal path; they ask for it here now.
    if argv and argv[0].startswith("--"):
        what, argv = argv[0], argv[1:]
        name = argv[0] if argv else None
        value = {"--elf": elf, "--dir": game_dir, "--tables": table_dir,
                 "--art": playfield_png, "--game": active}.get(what)
        if not value:
            print("usage: gameinfo.py [--elf|--dir|--tables|--art|--game] [title]",
                  file=sys.stderr)
            return 2
        v = value(name)
        if not v:
            return 1
        print(v)
        return 0

    name = argv[0] if argv else None
    game = active(name)
    print("rootfs seen as   : %s" % root())
    print("table cache      : %s" % table_root())
    pub = published()
    if pub:
        print("published run    : %s" % ", ".join("%s=%s" % kv
                                                  for kv in sorted(pub.items())))
    print("extracted titles : %s" % (", ".join(installed()) or "(none)"))
    print("titles with tables: %s" % (", ".join(tables_installed()) or "(none)"))
    if not game:
        print("active title     : (unknown - set PAD_GAME, or start a run)")
        return 1
    print("active title     : %s" % game)
    print("  game dir       : %s" % game_dir(name))
    e = elf(name)
    print("  ELF            : %s%s"
          % (e, "" if e and os.path.exists(e) else "   (NOT PRESENT)"))
    print("  tables         : %s" % table_dir(name))
    art = playfield_png(name)
    print("  playfield art  : %s %s"
          % (art, png_size(art) if art and os.path.exists(art) else "(missing)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
