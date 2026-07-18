"""Shared test helpers: a tiny in-memory fake of ``Ext4Reader`` plus a
synthetic MBR builder, used by the Partition Explorer tests (engine + GUI).

The real ext4 read layer is exercised on real cards; these let the explorer's
composition logic (partition classification, path resolution, listing, extract
layout, and the GUI tab wiring) be tested without a multi-GB card fixture.

Not a test module itself (no ``test_*`` name) so pytest won't collect it.
"""

import struct

from pinball_decryptor.plugins.stern.explorer import (S_IFDIR, S_IFLNK, S_IFMT,
                                                      S_IFREG)

# A small filesystem spec: nested dict = directory, bytes = file, ("symlink",
# target) = symlink.
SAMPLE_TREE = {
    "spk": {"index": {"turtles.sidx": b"SIDXdata",
                      "turtles.link": ("symlink", "turtles.sidx")}},
    "etc": {"init.d": {"game": b"#!/bin/sh\necho hi\n"}},
    "readme.txt": b"hello world",
    "zeta": {"a.bin": b"AA", "b.bin": b"BBBB"},
    "game": ("symlink", "turtles_pro/game"),
}

GOOD_LBA = 24576                 # the browsable ext partition's start LBA
GOOD_OFF = GOOD_LBA * 512        # ...and its byte offset


# Where the fake's regular files "live" on the card, for disk_ranges: each
# regular file gets a fixed span starting here, in build order.
FAKE_DATA_BASE = GOOD_LBA * 512 + 0x10000


class FakeExt4Reader:
    """Minimal stand-in for Ext4Reader over a nested-dict *spec*.

    Regular files also carry a synthetic on-disk location (``_disk_off``,
    assigned in build order from :data:`FAKE_DATA_BASE`) so
    ``disk_ranges`` — and therefore ``CardImage.replace_file`` — can be
    exercised against a real card file (see :func:`materialize_files`)."""

    def __init__(self, spec):
        self.block_size = 1024
        self._inodes = {}
        self._next = 3
        self._data_cursor = FAKE_DATA_BASE
        self._build(2, spec)

    def _build(self, ino, spec):
        children = {}
        self._inodes[ino] = {"mode": S_IFDIR, "size": 1024,
                             "i_block": b"\x00" * 60, "_children": children}
        for name, val in spec.items():
            cino = self._next
            self._next += 1
            children[name] = cino
            if isinstance(val, dict):
                self._build(cino, val)
            elif isinstance(val, tuple) and val[0] == "symlink":
                tgt = val[1].encode()
                self._inodes[cino] = {"mode": S_IFLNK, "size": len(tgt),
                                     "i_block": tgt[:60].ljust(60, b"\x00")}
            else:
                data = val if isinstance(val, (bytes, bytearray)) \
                    else str(val).encode()
                self._inodes[cino] = {"mode": S_IFREG, "size": len(data),
                                     "i_block": b"\x00" * 60,
                                     "_data": bytes(data),
                                     "_disk_off": self._data_cursor}
                # 1 KB alignment keeps the spans disjoint and readable.
                self._data_cursor += max(1024, len(data))

    def disk_ranges(self, inode, file_off, length):
        """One contiguous synthetic range per file (mirrors the real API)."""
        off = inode.get("_disk_off")
        if off is None or file_off + length > inode["size"]:
            raise ValueError("file offset not allocated")
        return [(off + file_off, length)]

    def read_inode(self, ino):
        return self._inodes[ino]

    def _iter_dir(self, node):
        for name, cino in node.get("_children", {}).items():
            m = self._inodes[cino]["mode"] & S_IFMT
            ftype = 2 if m == S_IFDIR else (7 if m == S_IFLNK else 1)
            yield name, cino, ftype

    def read_file_bytes(self, node):
        return node.get("_data", b"")

    def peek(self, node, n=16):
        """First *n* bytes, like Ext4Reader.peek (magic sniffing)."""
        return node.get("_data", b"")[:n]

    def extract_file(self, node, out_path, progress=None):
        with open(out_path, "wb") as f:
            f.write(node.get("_data", b""))
        if progress:
            progress(node["size"], node["size"])

    def iter_regular_files(self, root_ino=2, max_depth=64, min_size=0):
        stack, seen = [(root_ino, "")], set()
        while stack:
            ino, path = stack.pop()
            if ino in seen:
                continue
            seen.add(ino)
            node = self._inodes[ino]
            if (node["mode"] & S_IFMT) != S_IFDIR:
                continue
            for name, cino in node.get("_children", {}).items():
                cn = self._inodes[cino]
                m = cn["mode"] & S_IFMT
                if m == S_IFDIR:
                    stack.append((cino, path + "/" + name))
                elif m == S_IFREG and cn["size"] >= min_size:
                    yield path + "/" + name, cino, cn


def make_mbr(entries):
    """512-byte MBR with *entries* = ``[(type, lba_start, sectors), ...]``."""
    buf = bytearray(512)
    for i, (ptype, lba, sectors) in enumerate(entries):
        off = 446 + i * 16
        buf[off + 4] = ptype
        struct.pack_into("<II", buf, off + 8, lba, sectors)
    buf[510:512] = b"\x55\xaa"
    return bytes(buf)


# The standard 4-partition test layout: FAT boot, a browsable ext, an ext the
# reader can't open, and an extended partition.
STD_ENTRIES = [
    (0x0C, 8192, 16384),
    (0x83, GOOD_LBA, 100),
    (0x83, 30000, 100),
    (0x0F, 40000, 100),
]


def install_fake_reader(monkeypatch, spec=SAMPLE_TREE):
    """Patch explorer.Ext4Reader so only the GOOD_OFF ext partition opens (as a
    FakeExt4Reader over *spec*); every other offset raises."""
    from pinball_decryptor.plugins.stern import explorer

    def fake_reader(_fileobj, off, _size):
        if off == GOOD_OFF:
            return FakeExt4Reader(spec)
        raise ValueError("not an ext filesystem")

    monkeypatch.setattr(explorer, "Ext4Reader", fake_reader)


def write_fake_card(path, entries=STD_ENTRIES):
    """Write a synthetic card image (just an MBR + a little padding) to *path*
    and return it as a str."""
    with open(path, "wb") as f:
        f.write(make_mbr(entries) + b"\x00" * 4096)
    return str(path)


def materialize_files(card_path, spec=SAMPLE_TREE):
    """Grow *card_path* and write each regular file's bytes at the same
    synthetic disk offsets a ``FakeExt4Reader(spec)`` assigns — so
    ``CardImage.replace_file``'s extent-mapped writes land on real, checkable
    card bytes.  Returns ``{partition_path: (disk_off, data)}``."""
    r = FakeExt4Reader(spec)
    placed = {}

    def _walk(ino, base):
        node = r._inodes[ino]
        for name, cino in node.get("_children", {}).items():
            cn = r._inodes[cino]
            p = base + "/" + name
            if "_children" in cn:
                _walk(cino, p)
            elif "_data" in cn:
                placed[p] = (cn["_disk_off"], cn["_data"])

    _walk(2, "")
    end = max((off + len(d) for off, d in placed.values()), default=0)
    with open(card_path, "r+b") as f:
        f.seek(max(end, FAKE_DATA_BASE + 1024))
        f.write(b"\x00")
        for off, data in placed.values():
            f.seek(off)
            f.write(data)
    return placed
