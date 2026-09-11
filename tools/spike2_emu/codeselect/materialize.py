#!/usr/bin/env python
# materialize.py - rebuild a store card's DELTA files at boot (item 107).
#
# A store card (mkmulticard --layout store) keeps every file of every tree as
# one hardlink into .blobs/.  A variant that differs from an earlier tree's
# file only in a few byte ranges - a song set, where the app replaces each
# sound IN PLACE and size-neutral - is stored as a DELTA BLOB instead:
#
#     .blobs/<sha256>.<mode>.<uid>.<gid>.delta
#
# an ASCII header naming the BASE blob (a full file at the same path in an
# earlier tree), the file's size and sha256, and N `<off> <len>` ranges, then a
# blank line, then the ranges' bytes back to back.  The variant tree's own
# file is a hardlink to the BASE blob, so the game always has a file to open
# - it plays the base's songs if nothing below runs - and the tree carries
#
#     <tree>/.multiboot/deltas        one TAB line per delta'd file:
#                                     <rel>  <base blob key>  <delta blob name>  <size>
#
# This script runs on the MACHINE, from select.sh, right after the chosen tree
# is bound over /games, with the card's own python2.7 - which has os, sys,
# hashlib, struct, errno, time, stat, io, re and collections, and NOT json,
# subprocess, fcntl, shutil or zlib (measured on the rootfs under qemu; that
# is why the index is tab lines and mounts go through os.system).  It also
# runs under python3 on the desk (the tests) and in the emulator rig
# (run_game.sh, with a plain work directory).  Keep it in the 2/3 subset:
# no f-strings, no `yield from`, no keyword-only arguments, bytes literals.
#
# What it does, per delta'd file:
#   work file  <work>/<rel>, stamp <work>/<rel>.stamp = "base <key>\ndelta <name>\n"
#   stamp names this delta and the work file is the right size -> nothing to do
#   else: the stamp is REMOVED FIRST, then
#       same base in the stamp -> the old delta's ranges get base bytes back
#                                 (its blob may be gone: then the base is copied whole)
#       anything else          -> the base blob is copied whole (Beatles: 380 MB,
#                                 ~30 s at SD speed, said in the log)
#       then this delta's ranges are written, fsync, and the stamp is written LAST.
#   A stamp is the only promise; no stamp = redo from the base.  Power loss
#   mid-write is the normal case on a pinball machine.
#   then  mount --bind <work>/<rel> <games>/<rel>
# Any failure anywhere = that file is skipped and the game boots with the
# base's songs.  This script never exits non-zero for a materialize problem;
# only a usage error does (2).  Every line it prints starts `materialize:` so
# the card log reads like select.sh's.
#
#   materialize.py --store DIR --tree SUB --games DIR --work DIR
#                  [--mount-dev DEV --mount-opts OPTS] [--no-bind] [--verify]
#                  [--log FILE]
#   --store   the store's root (where .blobs/ is): the mounted p3
#   --tree    the tree's subdirectory in the store ('' = the primary's own root)
#   --games   where that tree is bound (the game's /games); the binds go here
#   --games-title NAME   the tree's title directory is bound at <games>/NAME, not
#             under its own name (the emulator rig: every image runs as /games/$PAD_GAME)
#   --work    the rw directory the work files live in (p7's mountpoint on the
#             card, $R/dump/work in the rig); --mount-dev mounts DEV there first
#   --verify  hash every materialized file and refuse the bind on a mismatch
#             (slow on the machine: a full read of the file; for proof runs)
#   --no-bind write the work files and stop (the tests, and a dry run)
#
# Library use (the tool imports this file for the FORMAT, so it is defined
# once): find_delta / write_delta / read_header / apply_delta / hash_with_delta
# / read_index / write_index.
from __future__ import print_function

import errno
import hashlib
import os
import sys
import time

MAGIC = b"PADDELTA 1\n"
INDEX_MAGIC = b"# PADDELTAS 1\n"
DELTA_SUFFIX = ".delta"
INDEX_REL = ".multiboot/deltas"          # inside a tree
BLOBS_DIR = ".blobs"                      # at the store's root (treesync.BLOBS_DIR)
BLOCK = 4096                              # the compare's grain: an ext4 block
CHUNK = 1 << 20                           # every stream read
SLACK = 64 << 10                          # ranges closer than this merge: one seek + write each on the card
MAX_FRACTION = 0.25                       # a delta bigger than this share of the file is a full blob instead
MIN_SIZE = 1 << 20                        # files smaller than this are never deltas
STAMP_SUFFIX = ".stamp"

_LOG = [None]                             # the log file's path, when --log named one


def log(msg):
    line = "materialize: " + msg
    print(line)
    try:
        sys.stdout.flush()
    except Exception:                     # noqa: BLE001 - a closed stdout must not end a boot
        pass
    if _LOG[0]:
        try:
            with open(_LOG[0], "a") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
        except (IOError, OSError):
            pass


# ============================================================================ the delta format
def merge_ranges(ranges, slack=0):
    """Sorted, non-overlapping [(off, len)], joining ranges within `slack` of each other."""
    out = []
    for off, n in sorted((int(o), int(x)) for o, x in ranges if int(x) > 0):
        if out and off <= out[-1][0] + out[-1][1] + slack:
            end = max(out[-1][0] + out[-1][1], off + n)
            out[-1] = (out[-1][0], end - out[-1][0])
        else:
            out.append((off, n))
    return out


def _blocks(chunks, block):
    """Re-cut a stream of arbitrary chunks into `block`-sized pieces (the last one shorter)."""
    buf = b""
    for c in chunks:
        if not c:
            continue
        buf += c
        while len(buf) >= block:
            yield buf[:block]
            buf = buf[block:]
    if buf:
        yield buf


def find_delta(base_chunks, new_chunks, size, block=BLOCK, slack=SLACK, limit=None):
    """Compare two same-sized streams block by block -> the merged ranges of `new` that
    differ from `base`, or None when more than `limit` bytes differ (the default limit is
    MAX_FRACTION of `size`: past it a full copy is the cheaper store AND the cheaper boot).
    Stops reading at the limit, so a file that is nothing like its base costs a quarter of
    a read, not a whole one.  An empty list means the streams are identical."""
    if limit is None:
        limit = int(size * MAX_FRACTION)
    changed = []
    total = 0
    off = 0
    bi = _blocks(base_chunks, block)
    ni = _blocks(new_chunks, block)
    while True:
        b = next(bi, None)
        n = next(ni, None)
        if b is None and n is None:
            break
        if b is None or n is None or len(b) != len(n):
            return None                                   # the sizes differ after all
        if b != n:
            changed.append((off, len(n)))
            total += len(n)
            if total > limit:
                return None
        off += len(n)
    if off != size:
        return None
    return merge_ranges(changed, slack)


def _header_bytes(base_key, sha256, size, ranges):
    lines = [MAGIC, b"base " + base_key.encode("ascii") + b"\n", b"size %d\n" % size,
             b"sha256 " + sha256.encode("ascii") + b"\n", b"ranges %d\n" % len(ranges)]
    for off, n in ranges:
        lines.append(b"%d %d\n" % (off, n))
    lines.append(b"\n")
    return b"".join(lines)


def delta_chunks(base_key, sha256, size, ranges, new_chunks):
    """A delta blob as a stream: the header, then the bytes of `ranges` cut out of the
    `new_chunks` stream in one pass.  Raises ValueError (at the end) when the stream was
    too short for its ranges."""
    ranges = merge_ranges(ranges)
    yield _header_bytes(base_key, sha256, size, ranges)
    want = list(ranges)
    pos = 0
    for c in new_chunks:
        end = pos + len(c)
        while want and want[0][0] < end:
            off, n = want[0]
            lo = max(off, pos) - pos
            hi = min(off + n, end) - pos
            if hi > lo:
                yield c[lo:hi]
            if off + n <= end:
                want.pop(0)
            else:
                break
        pos = end
    if want:
        raise ValueError("the stream ended at %d before range %r" % (pos, want[0]))


def payload_bytes(ranges):
    return sum(n for _o, n in merge_ranges(ranges))


def write_delta(out, base_key, sha256, size, ranges, new_chunks):
    """Write a delta blob to the open binary file `out` -> the payload's byte count."""
    it = delta_chunks(base_key, sha256, size, ranges, new_chunks)
    out.write(next(it))                                        # the header
    written = 0
    for piece in it:
        out.write(piece)
        written += len(piece)
    return written


def read_header(f):
    """Parse a delta blob's header from the open binary file `f` (positioned at 0) ->
    {"base", "size", "sha256", "ranges": [(off, len)], "payload": offset of the bytes}.
    Raises ValueError on anything that is not a delta."""
    if f.read(len(MAGIC)) != MAGIC:
        raise ValueError("not a delta blob (magic)")
    h = {"base": None, "size": None, "sha256": None, "ranges": []}
    n_ranges = None
    while True:
        line = f.readline()
        if not line:
            raise ValueError("delta header ends without a blank line")
        if line == b"\n":
            break
        parts = line.rstrip(b"\n").split(b" ")
        if n_ranges is not None and len(h["ranges"]) < n_ranges:
            if len(parts) != 2:
                raise ValueError("bad range line %r" % (line,))
            h["ranges"].append((int(parts[0]), int(parts[1])))
            continue
        key = parts[0].decode("ascii")
        val = b" ".join(parts[1:]).decode("ascii")
        if key == "base":
            h["base"] = val
        elif key == "size":
            h["size"] = int(val)
        elif key == "sha256":
            h["sha256"] = val
        elif key == "ranges":
            n_ranges = int(val)
        # unknown keys are ignored: a later writer may add some
    if h["base"] is None or h["size"] is None or n_ranges is None or len(h["ranges"]) != n_ranges:
        raise ValueError("delta header incomplete")
    h["payload"] = f.tell()
    return h


def delta_payload_bytes(header):
    return sum(n for _o, n in header["ranges"])


def apply_delta(work, delta, header):
    """Write the delta's ranges into the open r+b file `work` from the open delta blob
    `delta` (any position; the header says where the payload starts).  Every range is one
    seek + one write, in `CHUNK` pieces."""
    delta.seek(header["payload"])
    for off, n in header["ranges"]:
        work.seek(off)
        left = n
        while left > 0:
            piece = delta.read(min(CHUNK, left))
            if not piece:
                raise IOError("delta payload short at range %d+%d" % (off, n))
            work.write(piece)
            left -= len(piece)


def restore_ranges(work, base, ranges):
    """Put the base's bytes back over `ranges` of `work` (both open, base rb, work r+b)."""
    for off, n in ranges:
        base.seek(off)
        work.seek(off)
        left = n
        while left > 0:
            piece = base.read(min(CHUNK, left))
            if not piece:
                raise IOError("base short at range %d+%d" % (off, n))
            work.write(piece)
            left -= len(piece)


def copy_stream(src, dst, size=None):
    """Copy `src` to `dst` (open files) in CHUNK pieces -> bytes copied."""
    n = 0
    while True:
        piece = src.read(CHUNK)
        if not piece:
            break
        dst.write(piece)
        n += len(piece)
    if size is not None and n != size:
        raise IOError("copied %d bytes, expected %d" % (n, size))
    return n


def hash_with_delta(base_chunks, delta, header):
    """The sha256 of base + delta WITHOUT materializing: streams the base and substitutes
    the delta's ranges as it goes.  `delta` is the open blob."""
    h = hashlib.sha256()
    ranges = list(header["ranges"])
    delta.seek(header["payload"])
    pos = 0
    for c in base_chunks:
        end = pos + len(c)
        out = bytearray(c)
        while ranges and ranges[0][0] < end:
            off, n = ranges[0]
            lo = max(off, pos)
            hi = min(off + n, end)
            if hi > lo:
                piece = delta.read(hi - lo)
                if len(piece) != hi - lo:
                    raise IOError("delta payload short at %d" % lo)
                out[lo - pos:hi - pos] = piece
            if off + n <= end:
                ranges.pop(0)
            else:
                ranges[0] = (hi, off + n - hi)         # the rest of this range is in the next chunk
                break
        h.update(bytes(out))
        pos = end
    return h.hexdigest()


def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            piece = f.read(CHUNK)
            if not piece:
                break
            h.update(piece)
    return h.hexdigest()


def delta_name(blob_key):
    return blob_key + DELTA_SUFFIX


def sha_of_name(name):
    """The sha256 a blob's or a delta's name carries."""
    return name.split(".")[0]


# ============================================================================ the tree's index
def read_index(path):
    """<tree>/.multiboot/deltas -> [(rel, base key, delta name, size)], [] when absent."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except (IOError, OSError) as e:
        if e.errno == errno.ENOENT:
            return []
        raise
    out = []
    for line in raw.splitlines():
        if not line or line.startswith(b"#"):
            continue
        parts = line.split(b"\t")
        if len(parts) != 4:
            raise ValueError("bad index line %r" % (line,))
        out.append((parts[0].decode("utf-8"), parts[1].decode("ascii"), parts[2].decode("ascii"), int(parts[3])))
    return out


def index_bytes(entries):
    """[(rel, base key, delta name, size)] -> the index file's bytes (sorted by rel)."""
    lines = [INDEX_MAGIC]
    for rel, base, name, size in sorted(entries):
        if "\t" in rel or "\n" in rel:
            raise ValueError("a path with a tab or newline cannot be indexed: %r" % (rel,))
        lines.append(rel.encode("utf-8") + b"\t" + base.encode("ascii") + b"\t" + name.encode("ascii")
                     + b"\t" + (b"%d" % size) + b"\n")
    return b"".join(lines)


def write_index(path, entries):
    with open(path, "wb") as f:
        f.write(index_bytes(entries))


# ============================================================================ the machine side
def read_stamp(path):
    """-> (base key, delta name) or None."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except (IOError, OSError):
        return None
    base = name = None
    for line in raw.splitlines():
        parts = line.split(b" ", 1)
        if len(parts) != 2:
            continue
        if parts[0] == b"base":
            base = parts[1].decode("ascii")
        elif parts[0] == b"delta":
            name = parts[1].decode("ascii")
    if base and name:
        return base, name
    return None


def write_stamp(path, base, name):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(b"base " + base.encode("ascii") + b"\ndelta " + name.encode("ascii") + b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)


def _remove(path):
    try:
        os.unlink(path)
    except (IOError, OSError) as e:
        if e.errno != errno.ENOENT:
            raise


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except (IOError, OSError):
        return
    try:
        os.fsync(fd)
    except (IOError, OSError):
        pass
    os.close(fd)


def _size(path):
    try:
        return os.stat(path).st_size
    except (IOError, OSError):
        return None


def materialize_one(store, rel, base_key, name, size, work_dir, verify=False):
    """Bring <work_dir>/<rel> to base + delta.  -> (path, "hit" | "restored" | "copied") or
    raises (IOError/OSError/ValueError) with the reason."""
    base_path = os.path.join(store, BLOBS_DIR, base_key)
    delta_path = os.path.join(store, BLOBS_DIR, name)
    if _size(base_path) != size:
        raise IOError("base blob %s is %s bytes, the index says %d" % (base_key, _size(base_path), size))
    with open(delta_path, "rb") as df:
        header = read_header(df)
    if header["base"] != base_key or header["size"] != size:
        raise ValueError("delta %s names base %s size %s, the index says %s %d"
                         % (name, header["base"], header["size"], base_key, size))
    work = os.path.join(work_dir, rel)
    stamp = work + STAMP_SUFFIX
    d = os.path.dirname(work)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    have = read_stamp(stamp)
    if have == (base_key, name) and _size(work) == size:
        if verify:
            got = hash_file(work)
            if got != sha_of_name(name):
                raise ValueError("verify: %s hashes to %s, the delta says %s" % (rel, got, sha_of_name(name)))
        return work, "hit"
    # THE STAMP GOES FIRST.  From here until the last line the work file is a promise nobody
    # has made, and a boot that finds it that way starts again from the base.
    _remove(stamp)
    how = "copied"
    t0 = time.time()
    restored = False
    if have is not None and have[0] == base_key and _size(work) == size:
        # the old delta's ranges get base bytes back; if its blob is gone, copy whole
        old_delta = os.path.join(store, BLOBS_DIR, have[1])
        try:
            with open(old_delta, "rb") as odf:
                old = read_header(odf)
            with open(work, "r+b") as wf, open(base_path, "rb") as bf:
                restore_ranges(wf, bf, old["ranges"])
            restored = True
            how = "restored"
        except (IOError, OSError, ValueError) as e:
            log("%s: the previous delta %s cannot be undone (%s): copying the base whole" % (rel, have[1], e))
    if not restored:
        with open(base_path, "rb") as bf, open(work, "wb") as wf:
            copy_stream(bf, wf, size)
    with open(work, "r+b") as wf, open(delta_path, "rb") as df:
        apply_delta(wf, df, header)
        wf.flush()
        os.fsync(wf.fileno())
    try:
        st = os.stat(base_path)
        os.chmod(work, st.st_mode & 0o7777)
    except (IOError, OSError):
        pass
    if verify:
        got = hash_file(work)
        if got != sha_of_name(name):
            raise ValueError("verify: %s hashes to %s after materializing, the delta says %s"
                             % (rel, got, sha_of_name(name)))
    write_stamp(stamp, base_key, name)
    _fsync_dir(d or work_dir)
    log("%s: %s base %s + %d range(s) %d bytes in %.1f s"
        % (rel, how, base_key[:12], len(header["ranges"]), delta_payload_bytes(header), time.time() - t0))
    return work, how


def _sh(cmd):
    """os.system with the status decoded (the card's python has no subprocess)."""
    rc = os.system(cmd)
    if rc == -1:
        return -1
    if os.name == "posix":
        return (rc >> 8) & 0xFF if rc & 0xFF == 0 else 128 + (rc & 0x7F)
    return rc


def _q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def main(argv=None):
    a = _parse(sys.argv[1:] if argv is None else argv)
    if a is None:
        return 2
    _LOG[0] = a["log"]
    store, tree, games, work = a["store"], a["tree"], a["games"], a["work"]
    index = os.path.join(store, tree, INDEX_REL) if tree else os.path.join(store, INDEX_REL)
    try:
        entries = read_index(index)
    except (IOError, OSError, ValueError) as e:
        log("cannot read %s (%s): the tree's files are the base's" % (index, e))
        return 0
    if not entries:
        return 0
    log("%s names %d delta file(s)" % (index, len(entries)))
    if a["mount_dev"]:
        if not os.path.isdir(work):
            try:
                os.makedirs(work)
            except (IOError, OSError) as e:
                log("cannot create %s (%s): booting with the base's files" % (work, e))
                return 0
        rc = _sh("mount -t ext4 -o %s %s %s" % (a["mount_opts"], _q(a["mount_dev"]), _q(work)))
        if rc != 0:
            log("mount %s at %s failed (%d): booting with the base's files" % (a["mount_dev"], work, rc))
            return 0
        log("work partition %s mounted at %s" % (a["mount_dev"], work))
    done = 0
    for rel, base_key, name, size in entries:
        try:
            path, _how = materialize_one(store, rel, base_key, name, size, work, verify=a["verify"])
        except (IOError, OSError, ValueError) as e:
            log("%s: NOT materialized (%s): the game plays the base's file" % (rel, e))
            continue
        if a["bind"]:
            target = os.path.join(games, rel)
            if a["games_title"]:
                # the tree's title directory is bound under another name (the emulator
                # rig runs every image as /games/$PAD_GAME): the first path component
                # of `rel` is that directory, so it is the one that gets renamed
                parts = rel.split("/", 1)
                target = os.path.join(games, a["games_title"], parts[1]) if len(parts) == 2 \
                    else os.path.join(games, a["games_title"])
            if not os.path.isfile(target):
                log("%s: no such file under %s to bind over: the game plays the base's file" % (rel, games))
                continue
            rc = _sh("mount --bind %s %s" % (_q(path), _q(target)))
            if rc != 0:
                log("%s: mount --bind failed (%d): the game plays the base's file" % (rel, rc))
                continue
            log("%s: bound over %s" % (rel, target))
        done += 1
    log("%d of %d delta file(s) in place" % (done, len(entries)))
    return 0


def _parse(argv):
    a = {"store": None, "tree": "", "games": None, "games_title": None, "work": None, "mount_dev": None,
         "mount_opts": "rw,noatime", "bind": True, "verify": False, "log": None}
    it = iter(argv)
    for opt in it:
        if opt == "--no-bind":
            a["bind"] = False
        elif opt == "--verify":
            a["verify"] = True
        elif opt in ("--store", "--tree", "--games", "--games-title", "--work", "--mount-dev", "--mount-opts",
                     "--log"):
            try:
                a[opt[2:].replace("-", "_")] = next(it)
            except StopIteration:
                print("materialize.py: %s needs a value" % opt, file=sys.stderr)
                return None
        else:
            print("materialize.py: unknown option %s" % opt, file=sys.stderr)
            return None
    if a["store"] is None or a["work"] is None or (a["bind"] and a["games"] is None):
        print("usage: materialize.py --store DIR --tree SUB --games DIR --work DIR "
              "[--mount-dev DEV] [--no-bind] [--verify] [--log FILE]", file=sys.stderr)
        return None
    return a


if __name__ == "__main__":
    sys.exit(main())
