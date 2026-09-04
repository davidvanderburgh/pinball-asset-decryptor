"""The contents of tests/fixtures/treesync_tiny.ext4.gz, as a generator the tests share.

`python3 treesync_tiny.py populate DIR` writes the tree into DIR (run by
make_treesync_tiny.sh on a mounted scratch image, as root); `expected()` returns what a
reader must see, computed from the same deterministic bytes - so the fixture is a
regenerable artefact, not a hand-maintained table.

The tree (all under d/):
  a.bin          200 KiB of seeded random bytes, mode 0644
  a_mode.bin     the SAME bytes, mode 0755 (same content, different identity)
  uid1000.txt    a short text file owned by uid 1000 / gid 1000
  link_fast      a fast symlink (target < 60 bytes, stored in the inode)
  link_slow      a slow symlink (a 70-byte target, stored in a data block)
  hole.bin       4 KiB written at 0 and 4 KiB at 1 MiB, nothing between (a hole)
  uninit.bin     fallocate 300 KiB, then 4 KiB written at the start (an uninitialised extent)
  multi.bin      1.5 MiB written after neighbours were deleted (several extents, usually)
  caf\xe9.txt    a latin-1 name that is not UTF-8
  sub/           a subdirectory, mode 0750, holding one small file
"""
import hashlib
import os
import random
import sys

CHUNK = 200 * 1024
TEXT = b"owned by uid 1000\n"
SLOW_TARGET = "x" * 70
FAST_TARGET = "a.bin"
LATIN1_NAME = b"caf\xe9.txt"
LATIN1_BYTES = b"latin-1 name\n"
SUB_BYTES = b"in a subdirectory\n"
HOLE_HEAD = b"H" * 4096
HOLE_TAIL = b"T" * 4096
HOLE_TAIL_AT = 1 << 20
UNINIT_LEN = 300 * 1024
UNINIT_HEAD = b"U" * 4096
MULTI_LEN = 1536 * 1024


def seeded(n, seed):
    r = random.Random(seed)
    return bytes(r.getrandbits(8) for _ in range(n))


def a_bytes():
    return seeded(CHUNK, 1)


def multi_bytes():
    return seeded(MULTI_LEN, 2)


def hole_bytes():
    buf = bytearray(HOLE_TAIL_AT + len(HOLE_TAIL))
    buf[:len(HOLE_HEAD)] = HOLE_HEAD
    buf[HOLE_TAIL_AT:] = HOLE_TAIL
    return bytes(buf)


def uninit_bytes():
    buf = bytearray(UNINIT_LEN)
    buf[:len(UNINIT_HEAD)] = UNINIT_HEAD
    return bytes(buf)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def expected():
    """{rel: (kind, size, sha256 or None, target or None)} for every entry under d/."""
    return {
        "d": ("dir", None, None, None),
        "d/a.bin": ("file", CHUNK, sha(a_bytes()), None),
        "d/a_mode.bin": ("file", CHUNK, sha(a_bytes()), None),
        "d/uid1000.txt": ("file", len(TEXT), sha(TEXT), None),
        "d/link_fast": ("symlink", None, None, FAST_TARGET),
        "d/link_slow": ("symlink", None, None, SLOW_TARGET),
        "d/hole.bin": ("file", HOLE_TAIL_AT + len(HOLE_TAIL), sha(hole_bytes()), None),
        "d/uninit.bin": ("file", UNINIT_LEN, sha(uninit_bytes()), None),
        "d/multi.bin": ("file", MULTI_LEN, sha(multi_bytes()), None),
        "d/" + LATIN1_NAME.decode("utf-8", "surrogateescape"): ("file", len(LATIN1_BYTES), sha(LATIN1_BYTES), None),
        "d/sub": ("dir", None, None, None),
        "d/sub/one.txt": ("file", len(SUB_BYTES), sha(SUB_BYTES), None),
    }


def populate(root):
    d = os.path.join(root, "d")
    os.mkdir(d)
    with open(os.path.join(d, "a.bin"), "wb") as f:
        f.write(a_bytes())
    os.chmod(os.path.join(d, "a.bin"), 0o644)
    with open(os.path.join(d, "a_mode.bin"), "wb") as f:
        f.write(a_bytes())
    os.chmod(os.path.join(d, "a_mode.bin"), 0o755)
    with open(os.path.join(d, "uid1000.txt"), "wb") as f:
        f.write(TEXT)
    os.chown(os.path.join(d, "uid1000.txt"), 1000, 1000)
    os.symlink(FAST_TARGET, os.path.join(d, "link_fast"))
    os.symlink(SLOW_TARGET, os.path.join(d, "link_slow"))
    with open(os.path.join(d, "hole.bin"), "wb") as f:
        f.write(HOLE_HEAD)
        f.seek(HOLE_TAIL_AT)
        f.write(HOLE_TAIL)
    # an uninitialised extent: fallocate keeps the blocks unwritten; the kernel reads zeros
    fd = os.open(os.path.join(d, "uninit.bin"), os.O_RDWR | os.O_CREAT, 0o644)
    os.posix_fallocate(fd, 0, UNINIT_LEN)
    os.pwrite(fd, UNINIT_HEAD, 0)
    os.close(fd)
    # several extents: fill the gaps between short-lived neighbours
    names = []
    for i in range(6):
        p = os.path.join(d, "tmp%d" % i)
        with open(p, "wb") as f:
            f.write(b"\0" * (128 * 1024))
        names.append(p)
    for p in names[::2]:
        os.remove(p)
    with open(os.path.join(d, "multi.bin"), "wb") as f:
        f.write(multi_bytes())
    for p in names[1::2]:
        os.remove(p)
    with open(os.path.join(os.fsencode(d), LATIN1_NAME), "wb") as f:
        f.write(LATIN1_BYTES)
    os.mkdir(os.path.join(d, "sub"), 0o750)
    os.chmod(os.path.join(d, "sub"), 0o750)
    with open(os.path.join(d, "sub", "one.txt"), "wb") as f:
        f.write(SUB_BYTES)
    os.sync()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "populate":
        populate(sys.argv[2])
    else:
        print("usage: treesync_tiny.py populate DIR", file=sys.stderr)
        sys.exit(2)
