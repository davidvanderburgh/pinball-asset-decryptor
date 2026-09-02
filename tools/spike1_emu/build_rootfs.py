"""Assemble the Spike 1 emulation rootfs from a card image.

Extracts, from a Spike 1 SD-card image (``.iso``/``.img``/``.raw``):

  * the **OS rootfs** (the ext partition that holds ``bin/busybox``) -> a
    chroot base, with dirs + symlinks + files preserved, so the game's
    shell-outs (``/bin/sh``, ``/bin/mount``, ...) run under qemu-user;
  * the **game dir** (the ``<TITLE>/`` dir holding ``image.bin`` + ``game`` +
    the node ``.hex`` files) -> the dir bound at ``/games/<TITLE>``.

Run inside WSL/Linux (python3) so symlinks land on a real filesystem — a
Windows drvfs target would drop them and the dynamic busybox would not link.

    python3 build_rootfs.py <card> <rootfs-dir> <gamedir-dir>

Reuses the plugin's pure-Python ext4 reader + the Spike 1 partition walk; no
loop mount, no root.

STDLIB ONLY.  That ``python3`` is the distro's own, with nothing
pip-installed, so everything this reaches has to import on a bare
interpreter — including the plugin package ``__init__`` files Python runs on
the way to a leaf module (see ``pinball_decryptor/plugins/__init__.py``:
eager entry points made this script die on ``No module named 'Crypto'``
inside the *Spooky* plugin).  ``tests/test_rig_leaf_imports.py`` checks it.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)

from pinball_decryptor.plugins.stern.ext4 import (  # noqa: E402
    Ext4Reader, S_IFDIR, S_IFMT, S_IFREG)
from pinball_decryptor.plugins.stern.formats import (  # noqa: E402
    parse_all_partitions)

S_IFLNK = 0xA000
SECTOR = 512


def _symlink_target(reader, node):
    if node["size"] < 60:
        return node["i_block"][:node["size"]].decode("latin1", "replace")
    return reader.read_file_bytes(node)[:node["size"]].decode("latin1", "replace")


def extract_tree(reader, dest, root_ino=2, max_depth=40, progress_every=400):
    """Recreate the full tree (dirs + symlinks + regular files) under *dest*.

    Prints a running file count every *progress_every* files so a slow card
    (read over /mnt/c is not fast) shows progress rather than a silent minutes-
    long pause — the GUI streams these lines."""
    seen, made = set(), {"dir": 0, "file": 0, "link": 0, "skip": 0}
    stack = [(root_ino, dest, 0)]
    while stack:
        ino, path, depth = stack.pop()
        if ino in seen or depth > max_depth:
            continue
        seen.add(ino)
        try:
            node = reader.read_inode(ino)
        except Exception:
            continue
        if (node["mode"] & S_IFMT) != S_IFDIR:
            continue
        os.makedirs(path, exist_ok=True)
        made["dir"] += 1
        for name, child, _ftype in reader._iter_dir(node):
            if name in (".", ".."):
                continue
            cpath = os.path.join(path, name)
            try:
                cn = reader.read_inode(child)
            except Exception:
                continue
            m = cn["mode"] & S_IFMT
            if m == S_IFDIR:
                stack.append((child, cpath, depth + 1))
            elif m == S_IFLNK:
                try:
                    if os.path.lexists(cpath):
                        os.remove(cpath)
                    os.symlink(_symlink_target(reader, cn), cpath)
                    made["link"] += 1
                except OSError:
                    made["skip"] += 1
            elif m == S_IFREG:
                try:
                    reader.extract_file(cn, cpath)
                    os.chmod(cpath, 0o755)
                    made["file"] += 1
                    if progress_every and made["file"] % progress_every == 0:
                        print("  … %d files" % made["file"], flush=True)
                except Exception:
                    made["skip"] += 1
            else:
                made["skip"] += 1
    return made


def _open_partitions(card):
    f = open(card, "rb")
    parts = parse_all_partitions(card)
    ext = [(lba, sectors) for (_i, t, lba, sectors) in parts if t == 0x83]
    return f, ext


def find_rootfs_and_game(f, ext):
    """Return ``(rootfs_reader, game_reader, game_dirname)``.

    The OS rootfs is the ext partition with ``bin/busybox``; the game
    partition is the one whose top level holds a ``<TITLE>/image.bin``.
    """
    rootfs = game = game_dir = None
    for lba, sectors in ext:
        try:
            r = Ext4Reader(f, lba * SECTOR, sectors * SECTOR)
        except Exception:
            continue
        found = r.find_files(["busybox"], max_depth=2)
        if "busybox" in found and rootfs is None:
            rootfs = r
        for path, _ino, node in r.iter_regular_files(max_depth=2, min_size=1):
            if path.endswith("/image.bin") and node["size"] > 10 * 1024 * 1024:
                game = r
                game_dir = path.rsplit("/", 2)[-2]
                break
    return rootfs, game, game_dir


# The EARLIEST Spike 1 generation — same system, a firmware era this rig cannot
# drive, and it reads like a broken card unless you look for it.
#
# transformers_pin-1.0.18 is **Transformers The Pin (Stern, 2012)**: one of the
# first SPIKE machines, three years before SPIKE reached the coin-op line, with
# two 8-digit LED displays instead of a DMD (which is why its owner said "NO
# DMD ON this game").  Its card carries the Spike 1 MBR shapes at different
# LBAs and the SAME base rootfs as GOT LE and Whoa Nellie (`/etc/version`
# 201006031147, glibc 2.6.1, kernel 2.6.30 — those are constants across Spike 1
# and say nothing about a card's age; do not read them as one).
#
# What actually differs is the FIRMWARE ERA, and it is everything this rig
# touches: the game lives at `/usr/local/games/<title>/` with its sounds as
# PLAIN WAV FILES beside it rather than at `/games/<TITLE>/` with an
# `image.bin`; its node images are `pinnode` / `netbridge` / `alphanumeric` /
# `dotmatrix` rather than `coil4node` / `accbridgenode`; and its framework
# symbols are the early short form (`node_poll_t`, `node_coilmsg`,
# `nodemap_init`, `ALPHANUMERIC_*`) with NOT ONE of the `node_bus_*` /
# `sys_node_board_device_*` / `sys_line_status_*` names that s1patch.py,
# nodebus.py and s1swmap.py key on — the early era needs its own answers in
# each, and the rig is being taught them (PAD-101).  This reader's part is to
# find the game where the early card keeps it and record what the card's own
# init script would have done: which binary it launches (gamer, not the debug
# build game beside it) and which display it drives.
_EARLY_GAMES_DIR = "/usr/local/games"


def _lookup(reader, path):
    """Inode number of *path* on *reader*, or None (no symlink following)."""
    ino = 2
    for part in path.strip("/").split("/"):
        node = reader.read_inode(ino)
        nxt = None
        for name, child, _ft in reader._iter_dir(node):
            if name == part:
                nxt = child
                break
        if nxt is None:
            return None
        ino = nxt
    return ino


def _readlink(reader, path):
    """Target of the symlink at *path*, or None if absent / not a link."""
    ino = _lookup(reader, path)
    if ino is None:
        return None
    node = reader.read_inode(ino)
    if (node["mode"] & S_IFMT) != S_IFLNK:
        return None
    return _symlink_target(reader, node)


def early_spike1_layout(rootfs, title):
    """``(game_exe, display)`` for an early-era card: which binary the card
    launches and which display it is built for, both read off the symlinks
    the card's own /etc/init.d/game follows — ``$DATA_PATH/game`` (the
    launched binary, e.g. ``tf-elg/gamer``: the DEBUG build ``game`` sits
    beside it and is NOT what runs) and ``$DATA_PATH/display.hex``
    (``alphanumeric-…`` or ``dotmatrix-…``)."""
    exe = _readlink(rootfs, _EARLY_GAMES_DIR + "/game") or (title + "/game")
    exe = exe.rsplit("/", 1)[-1]
    disp = _readlink(rootfs, _EARLY_GAMES_DIR + "/display.hex") or ""
    disp = disp.rsplit("/", 1)[-1].split("-")[0] or "unknown"
    return exe, disp


def early_spike1_game_dir(rootfs):
    """The ``<title>`` of an EARLY-era Spike 1 game on *rootfs*, or None.

    Identified by ``/usr/local/games/<title>/game`` — the 2015-2016 generation
    keeps its game on its own partition, at ``/games/<TITLE>/``, never here."""
    if rootfs is None:
        return None
    for path, _ino, node in rootfs.iter_regular_files(max_depth=6, min_size=1):
        if (path.startswith(_EARLY_GAMES_DIR + "/") and path.endswith("/game")
                and path.count("/") == _EARLY_GAMES_DIR.count("/") + 2):
            return path.rsplit("/", 2)[-2]
    return None


def main():
    card, rootfs_dir, gamedir = sys.argv[1:4]
    f, ext = _open_partitions(card)
    rootfs, game, game_name = find_rootfs_and_game(f, ext)
    early = early_spike1_game_dir(rootfs) if game is None else None
    if rootfs is None or (game is None and early is None):
        sys.exit("could not locate rootfs (busybox) and/or game (image.bin) "
                 "partitions — is this a Spike 1 card?")
    if early:
        # The game dir is ON the rootfs partition, one level under
        # /usr/local/games; it is extracted a second time as the rig's game
        # dir (bound back over the same path at run time) so the cache layout
        # and every script that reads <entry>/game/ are unchanged.
        game, game_name = rootfs, early
        game_exe, display = early_spike1_layout(rootfs, early)
        print("early Spike 1 card: game folder %s, launches %s, %s display"
              % (game_name, game_exe, display), flush=True)
    else:
        game_exe, display = "game", "dotmatrix"
    print("game folder:", game_name, flush=True)
    print("extracting OS rootfs (this is the slow part) ->", rootfs_dir,
          flush=True)
    print("  ", extract_tree(rootfs, rootfs_dir), flush=True)
    # the game dir sits one level under the game partition root
    print("extracting game files ->", gamedir, flush=True)
    os.makedirs(gamedir, exist_ok=True)
    n = 0
    prefix = (_EARLY_GAMES_DIR.strip("/") + "/" if early else "") + game_name
    depth = prefix.count("/") + 3          # <prefix>/sounds/x.wav
    for path, _ino, node in game.iter_regular_files(max_depth=depth,
                                                    min_size=0):
        rel = path.strip("/")
        if rel == prefix or rel.startswith(prefix + "/"):
            out = os.path.join(gamedir, rel[len(prefix) + 1:])
            os.makedirs(os.path.dirname(out) or gamedir, exist_ok=True)
            game.extract_file(node, out)
            os.chmod(out, 0o755)
            n += 1
    print("extracted %d game files -> %s" % (n, gamedir), flush=True)
    # write the resolved game name so the launcher knows the /games/<TITLE>,
    # and for an early card WHERE the game must be mounted and WHAT to run —
    # emu_root.sh reads these; absent means the DMD-generation defaults.
    with open(os.path.join(gamedir, ".game_name"), "w") as fh:
        fh.write(game_name + "\n")
    if early:
        with open(os.path.join(gamedir, ".game_path"), "w") as fh:
            fh.write("%s/%s\n" % (_EARLY_GAMES_DIR, game_name))
        with open(os.path.join(gamedir, ".game_exe"), "w") as fh:
            fh.write(game_exe + "\n")
        with open(os.path.join(gamedir, ".display"), "w") as fh:
            fh.write(display + "\n")
    f.close()


if __name__ == "__main__":
    main()
