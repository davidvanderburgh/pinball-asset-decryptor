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


def main():
    card, rootfs_dir, gamedir = sys.argv[1:4]
    f, ext = _open_partitions(card)
    rootfs, game, game_name = find_rootfs_and_game(f, ext)
    if rootfs is None or game is None:
        sys.exit("could not locate rootfs (busybox) and/or game (image.bin) "
                 "partitions — is this a Spike 1 card?")
    print("game folder:", game_name, flush=True)
    print("extracting OS rootfs (this is the slow part) ->", rootfs_dir,
          flush=True)
    print("  ", extract_tree(rootfs, rootfs_dir), flush=True)
    # the game dir sits one level under the game partition root
    print("extracting game files ->", gamedir, flush=True)
    os.makedirs(gamedir, exist_ok=True)
    n = 0
    for path, _ino, node in game.iter_regular_files(max_depth=2, min_size=0):
        parts = path.strip("/").split("/")
        if parts[0] == game_name:
            out = os.path.join(gamedir, "/".join(parts[1:]))
            os.makedirs(os.path.dirname(out) or gamedir, exist_ok=True)
            game.extract_file(node, out)
            os.chmod(out, 0o755)
            n += 1
    print("extracted %d game files -> %s" % (n, gamedir), flush=True)
    # write the resolved game name so the launcher knows the /games/<TITLE>
    with open(os.path.join(gamedir, ".game_name"), "w") as fh:
        fh.write(game_name + "\n")
    f.close()


if __name__ == "__main__":
    main()
