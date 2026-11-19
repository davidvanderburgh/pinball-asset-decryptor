#!/usr/bin/env python3
"""Share identical blocks between the card store's files (PAD-1453).

David, 2026-11-19: "our pad storage on disk c has gotten way out of control...
using over 500GB is insane here."

WHY. The store (/mnt/wsl/cards: the Spike 2 library, the card cache, Spike 3's
cards) held 431 GiB of data on 2026-11-19 and only 189 GiB of it was unique,
4 KiB block by 4 KiB block: an LE card and its Pro are the same OS, the same
videos and the same sounds (Jaws Pro 80% inside Jaws LE); a custom build is the
stock card with a few files changed; a ticket's scratch build is a library card
with one edit. zstd found only 16% (the media is H.264 and compressed audio
already), so compression was never the answer - sharing is.

HOW. The store is XFS with reflink (cardstore.ps1 migrate). FIDEDUPERANGE asks
the kernel to make two byte-identical ranges share one set of blocks; the
kernel compares the bytes itself under a lock, so a hash collision or a file
changing underneath is refused, never merged. Nothing above the filesystem
changes: every file reads exactly as before, a boot reads the same path, and a
write to a shared block is copied first (copy-on-write), so no file can change
another.

    storededupe.py dedupe [--dry] ROOT...       share blocks between files under the roots
    storededupe.py ingest SRC DST               copy SRC's tree into DST (an XFS store), sharing as it goes,
                                                so the new disk never holds more than the unique data + one file
    storededupe.py verify SRC DST               every file under SRC is byte-identical under DST

The first root (or SRC's library/) is the preferred source: a block shared with
the library points at the library's copy, which lives for good.

Hashes of each file are kept under <first root's mount>/.dedupe/ keyed by
inode+size+mtime, so a later run reads only what is new (a fresh card in the
library, a new cache entry) - the weekly pass is minutes, not a re-read of
everything.
"""
import argparse
import os
import stat
import struct
import sys
import time

try:
    import numpy as np
except ImportError:                      # pragma: no cover - the rig's distros have it
    sys.exit("[dedupe] needs numpy (python3-numpy)")

BLK = 4096
CHUNK = 16 << 20                         # bytes read at a time
MAX_RUN = 4096                           # blocks per FIDEDUPERANGE call: 16 MiB, the kernel's own cap
MIN_FILE = 1 << 20                       # smaller files are not worth an entry
QUIET_S = 600                            # a file written in the last 10 min may still be being written
FIDEDUPERANGE = 0xC0189436               # _IOWR(0x94, 54, struct file_dedupe_range)
FILE_DEDUPE_RANGE_SAME = 0
FILE_DEDUPE_RANGE_DIFFERS = 1

_rng = np.random.default_rng(1453)
_MUL1 = _rng.integers(1, 2 ** 63, size=BLK // 8, dtype=np.uint64) | np.uint64(1)
_MUL2 = _rng.integers(1, 2 ** 63, size=BLK // 8, dtype=np.uint64) | np.uint64(1)
_SHIFT = np.uint64(29)


def say(*a):
    print("[dedupe]", *a, flush=True)


# ---------------------------------------------------------------------------
# Hashing: one 64-bit value per non-zero 4 KiB block, holes skipped
# ---------------------------------------------------------------------------

def _data_ranges(fd, size):
    off = 0
    while off < size:
        try:
            d = os.lseek(fd, off, os.SEEK_DATA)
        except OSError:
            return
        h = os.lseek(fd, d, os.SEEK_HOLE)
        yield d - d % BLK, h
        off = h


def punch_zeros(path):
    """Turn every all-zero 4 KiB block of *path* back into a hole, keeping the
    file's size and timestamps. The copy wrote the zeros inside a card's data
    ranges as real blocks: Jaws Pro took 12.0 GiB on the new store against
    7.8 on the old (2026-11-19). A hole reads as zeros, so the file's bytes
    are unchanged. Returns the bytes punched."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_long, ctypes.c_long]
    st = os.stat(path)
    fd = os.open(path, os.O_RDWR)
    punched = 0
    try:
        ranges = list(_data_ranges(fd, st.st_size))
        # the holes too: preallocated (unwritten) extents read as holes to SEEK_DATA yet hold blocks - XFS left
        # 4.25 GiB of them in Jaws Pro's copy. Punching a hole that holds nothing is free.
        prev = 0
        for d, _h in ranges + [(st.st_size, st.st_size)]:
            if d > prev:
                libc.fallocate(fd, 3, prev, d - prev)
            prev = max(prev, _h)
        for d, h in ranges:
            p = d
            while p < h:
                b = os.pread(fd, min(CHUNK, h - p), p)
                n = len(b) - len(b) % BLK
                if n <= 0:
                    break
                a = np.frombuffer(b, dtype=np.uint64, count=n // 8).reshape(-1, BLK // 8)
                z = np.flatnonzero(~a.any(axis=1))
                if z.size:
                    brk = np.flatnonzero(np.diff(z) != 1)
                    starts = np.r_[z[0], z[brk + 1]]
                    ends = np.r_[z[brk], z[-1]] + 1
                    for s, e in zip(starts.tolist(), ends.tolist()):
                        # FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE
                        if libc.fallocate(fd, 3, p + s * BLK, (e - s) * BLK) == 0:
                            punched += (e - s) * BLK
                p += n
    finally:
        os.close(fd)
    # a punch moves mtime, which the resume and the hash cache key on: put it back
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return punched


def hash_file(path):
    """(hashes uint64[n], blocks uint64[n]) of the file's non-zero whole blocks.
    The hash only proposes a pair; the kernel's byte compare decides."""
    hs, bs = [], []
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        for d, h in _data_ranges(fd, size):
            p = d
            while p < h:
                b = os.pread(fd, min(CHUNK, h - p), p)
                n = len(b) - len(b) % BLK
                if n <= 0:
                    break
                a = np.frombuffer(b, dtype=np.uint64, count=n // 8).reshape(-1, BLK // 8)
                nz = np.flatnonzero(a.any(axis=1))
                if nz.size:
                    a = a[nz]
                    hs.append((a * _MUL1).sum(axis=1) ^ ((a * _MUL2).sum(axis=1) << _SHIFT))
                    bs.append(nz.astype(np.uint64) + np.uint64(p // BLK))
                p += n
    finally:
        os.close(fd)
    if not hs:
        return np.zeros(0, np.uint64), np.zeros(0, np.uint64)
    return np.concatenate(hs), np.concatenate(bs)


class HashCache:
    """Per-file hashes on disk, keyed by what makes a file the same file."""

    def __init__(self, folder):
        self.folder = folder
        self.done = set()
        if folder:
            os.makedirs(folder, exist_ok=True)
            try:
                with open(os.path.join(folder, "done.txt"), encoding="ascii") as f:
                    self.done = {x.strip() for x in f if x.strip()}
            except OSError:
                pass

    def _key(self, st):
        return "%d-%d-%d.npz" % (st.st_ino, st.st_size, st.st_mtime_ns)

    def is_done(self, st):
        """Already shared with everything indexed before it: a later pass only
        indexes it (sharing it again would re-compare every byte for nothing)."""
        return self._key(st) in self.done

    def mark_done(self, st):
        k = self._key(st)
        if k in self.done or not self.folder:
            return
        self.done.add(k)
        with open(os.path.join(self.folder, "done.txt"), "a", encoding="ascii") as f:
            f.write(k + "\n")

    def get(self, path, st):
        if self.folder:
            p = os.path.join(self.folder, self._key(st))
            try:
                with np.load(p) as z:
                    return z["h"], z["b"]
            except (OSError, ValueError, KeyError):
                pass
        h, b = hash_file(path)
        if self.folder:
            st2 = os.stat(path)
            if (st2.st_size, st2.st_mtime_ns) == (st.st_size, st.st_mtime_ns):
                tmp = os.path.join(self.folder, ".tmp-%d.npz" % os.getpid())
                np.savez(tmp, h=h, b=b)
                os.replace(tmp, os.path.join(self.folder, self._key(st)))
        return h, b

    def prune(self, live):
        """Drop entries for files that are gone or changed."""
        if not self.folder:
            return
        keep = {self._key(st) for st in live}
        for n in os.listdir(self.folder):
            if n.endswith(".npz") and n not in keep:
                try:
                    os.remove(os.path.join(self.folder, n))
                except OSError:
                    pass
        self.done &= keep
        tmp = os.path.join(self.folder, "done.txt.tmp")
        with open(tmp, "w", encoding="ascii") as f:
            f.writelines(k + "\n" for k in sorted(self.done))
        os.replace(tmp, os.path.join(self.folder, "done.txt"))


# ---------------------------------------------------------------------------
# The index: every block seen so far, sorted by hash
# ---------------------------------------------------------------------------

class Index:
    """Sorted (hash, packed fid/block) arrays, plus a small unsorted side list.
    Re-sorting the whole index after every file was seconds a file at ~50M
    entries - fine for 60 cards, hours for Spike 3's thousands of asset files
    (2026-11-19) - so new entries wait in `pending` and are merged in only
    when it grows past MERGE_AT."""
    MERGE_AT = 500_000          # the side list is sorted at each lookup: kept small (tens of ms)

    def __init__(self):
        self.h = np.zeros(0, np.uint64)
        self.v = np.zeros(0, np.uint64)          # fid << 40 | block
        self.ph, self.pv = [], []
        self.pn = 0
        self.paths = []

    @staticmethod
    def _find(hs, vs, h, out):
        if hs.size == 0 or h.size == 0:
            return
        pos = np.minimum(np.searchsorted(hs, h), hs.size - 1)
        hit = (hs[pos] == h) & (out < 0)
        out[hit] = vs[pos[hit]].astype(np.int64)

    def lookup(self, h):
        """For each hash: the packed (fid, block) already holding it, or -1."""
        out = np.full(h.size, -1, np.int64)
        self._find(self.h, self.v, h, out)
        if self.pn:
            ph, pv = np.concatenate(self.ph), np.concatenate(self.pv)
            o = np.argsort(ph, kind="stable")
            self._find(ph[o], pv[o], h, out)
        return out

    def add(self, fid, h, b):
        if h.size == 0:
            return
        self.ph.append(h)
        self.pv.append((np.uint64(fid) << np.uint64(40)) | b)
        self.pn += h.size
        if self.pn >= self.MERGE_AT:
            self.merge()

    def merge(self):
        if not self.pn:
            return
        h2 = np.concatenate([self.h] + self.ph)
        v2 = np.concatenate([self.v] + self.pv)
        o = np.argsort(h2, kind="stable")
        self.h, self.v = h2[o], v2[o]
        self.ph, self.pv, self.pn = [], [], 0


def _runs(dst_blocks, src_fids, src_blocks):
    """Coalesce block pairs (sorted by dst) into runs that are consecutive on
    both sides in one source file: (src_fid, src_block, dst_block, count)."""
    if dst_blocks.size == 0:
        return []
    brk = np.ones(dst_blocks.size, bool)
    brk[1:] = ((dst_blocks[1:] != dst_blocks[:-1] + 1)
               | (src_fids[1:] != src_fids[:-1])
               | (src_blocks[1:] != src_blocks[:-1] + 1))
    starts = np.flatnonzero(brk)
    ends = np.append(starts[1:], dst_blocks.size)
    out = []
    for s, e in zip(starts.tolist(), ends.tolist()):
        f, sb, db, n = int(src_fids[s]), int(src_blocks[s]), int(dst_blocks[s]), e - s
        while n > 0:
            k = min(n, MAX_RUN)
            out.append((f, sb, db, k))
            sb += k
            db += k
            n -= k
    return out


def dedupe_range(src_fd, src_off, dst_fd, dst_off, length):
    """One FIDEDUPERANGE call. Returns (bytes shared, status)."""
    import fcntl                         # Linux only; the module's planning parts are tested anywhere
    buf = bytearray(struct.pack("QQHHI", src_off, length, 1, 0, 0)
                    + struct.pack("qQQiI", dst_fd, dst_off, 0, 0, 0))
    try:
        fcntl.ioctl(src_fd, FIDEDUPERANGE, buf, True)
    except OSError as e:
        return 0, -e.errno
    _fd, _off, done, status, _r = struct.unpack_from("qQQiI", buf, 24)
    return done, status


class Deduper:
    def __init__(self, cache, dry=False):
        self.idx = Index()
        self.cache = cache
        self.dry = dry
        self.fds = {}
        self.shared = 0
        self.differs = 0
        self.failed = 0

    def _fd(self, fid):
        fd = self.fds.get(fid)
        if fd is None:
            fd = self.fds[fid] = os.open(self.idx.paths[fid], os.O_RDONLY)
        return fd

    def close(self):
        for fd in self.fds.values():
            os.close(fd)
        self.fds.clear()

    def take(self, path, as_dest=True):
        """Hash *path*, share its blocks with any seen before (unless not
        as_dest: a file only indexed, e.g. unchanged since the last run), and
        add its new blocks to the index. Returns bytes shared."""
        st = os.stat(path)
        h, b = self.cache.get(path, st)
        as_dest = as_dest and not self.cache.is_done(st)
        fid = len(self.idx.paths)
        self.idx.paths.append(path)
        if h.size == 0:
            return 0
        # within the file first: the first copy of each block is its own source
        u, first, inv = np.unique(h, return_index=True, return_inverse=True)
        found = self.idx.lookup(u)
        new = found < 0
        src = np.where(new, (np.int64(fid) << 40) | b[first].astype(np.int64), found)[inv]
        is_self_first = np.zeros(h.size, bool)
        is_self_first[first[new]] = True
        shared = 0
        if as_dest:
            m = ~is_self_first
            if m.any():
                o = np.argsort(b[m], kind="stable")
                db = b[m][o]
                sv = src[m][o]
                runs = _runs(db, sv >> 40, sv & ((1 << 40) - 1))
                shared = self._apply(fid, runs)
            if not self.dry:
                self.cache.mark_done(st)
        self.idx.add(fid, u[new], b[first[new]])
        return shared

    def _apply(self, fid, runs):
        done_total = 0
        if self.dry:
            return sum(n for _f, _s, _d, n in runs) * BLK
        dst = os.open(self.idx.paths[fid], os.O_RDONLY)
        try:
            for f, sb, db, n in runs:
                if f == fid and sb == db:
                    continue
                done, status = dedupe_range(self._fd(f) if f != fid else dst, sb * BLK, dst, db * BLK, n * BLK)
                if status == FILE_DEDUPE_RANGE_SAME:
                    done_total += done
                elif status == FILE_DEDUPE_RANGE_DIFFERS:
                    self.differs += 1
                else:
                    self.failed += 1
        finally:
            os.close(dst)
        self.shared += done_total
        return done_total


# ---------------------------------------------------------------------------
# Walking the store
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".dedupe", "lost+found"}


def big_files(root, now=None):
    """Regular files >= MIN_FILE under root, one filesystem, nothing being
    written right now (a .partial, or touched in the last QUIET_S)."""
    now = now or time.time()
    dev = os.stat(root).st_dev
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in _SKIP_DIRS
                        and os.lstat(os.path.join(dp, d)).st_dev == dev)
        for n in sorted(fns):
            p = os.path.join(dp, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size < MIN_FILE:
                continue
            if n.endswith((".partial", ".part")) or now - st.st_mtime < QUIET_S:
                continue
            out.append((p, st))
    return out


def _cache_dir(root):
    m = os.path.abspath(root)
    while not os.path.ismount(m) and m != "/":
        m = os.path.dirname(m)
    return os.path.join(m, ".dedupe")


def cmd_dedupe(roots, dry):
    cache = HashCache(_cache_dir(roots[0]))
    d = Deduper(cache, dry=dry)
    files = [x for r in roots for x in big_files(r)]
    t0 = time.time()
    total = 0
    try:
        for i, (p, st) in enumerate(files, 1):
            total += st.st_blocks * 512
            if not dry and not cache.is_done(st):
                punch_zeros(p)                 # a new card's zeros are holes before it is shared
            got = d.take(p)
            if got:
                say("%s: %.2f GiB shared" % (p, got / 2 ** 30))
            if i % 10 == 0:
                say("%d/%d files, %.1f GiB shared so far, %.0f s" % (i, len(files), d.shared / 2 ** 30 if not dry else 0, time.time() - t0))
    finally:
        d.close()
    cache.prune([st for _p, st in big_files(roots[0])] + [st for r in roots[1:] for _p, st in big_files(r)])
    print("dedupe\t%d\t%d\t%d\t%d" % (len(files), total, d.shared, d.differs + d.failed), flush=True)
    say("%d files, %.1f GiB allocated before, %.1f GiB shared%s; %d ranges refused"
        % (len(files), total / 2 ** 30, d.shared / 2 ** 30, " (dry)" if dry else "", d.differs + d.failed))
    return 0


def _copy_meta(src, dst, st):
    try:
        os.chown(dst, st.st_uid, st.st_gid, follow_symlinks=False)
    except OSError:
        pass
    if not stat.S_ISLNK(st.st_mode):
        os.chmod(dst, stat.S_IMODE(st.st_mode))
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)


def _syncfs(path):
    """Flush one filesystem (os.sync() hangs under WSL2 on virtiofs mounts: sync only the store)."""
    import ctypes
    fd = os.open(path, os.O_RDONLY)
    try:
        ctypes.CDLL(None, use_errno=True).syncfs(fd)
    finally:
        os.close(fd)


def _copy_sparse(src, dst, sync=True):
    """Copy only the data ranges; holes stay holes."""
    sfd = os.open(src, os.O_RDONLY)
    dfd = os.open(dst + ".ingest", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        size = os.fstat(sfd).st_size
        # the full size FIRST: XFS preallocates speculatively past end-of-file on a write that extends the file, and
        # a sparse copy extends it at every data range - Jaws Pro landed with 7.40 GiB written and 4.25 GiB of
        # those preallocated (unwritten) extents stranded inside its holes (2026-11-19)
        os.ftruncate(dfd, size)
        for d, h in _data_ranges(sfd, size):
            p = d
            while p < min(h, size):
                b = os.pread(sfd, min(CHUNK, h - p), p)
                if not b:
                    break
                os.pwrite(dfd, b, p)
                p += len(b)
        os.ftruncate(dfd, size)
        # a card is flushed before it takes its name; Spike 3's 170,000 small files are not (one fsync each held the
        # copy to ~1,000 files a minute) - cmd_ingest flushes the store once at the end, and swap byte-compares all
        if sync:
            os.fsync(dfd)
    finally:
        os.close(sfd)
        os.close(dfd)
    os.replace(dst + ".ingest", dst)


def _delete_missing(src, dst):
    """Remove what dst has and src no longer does (a cache entry pruned since
    the first pass), so the swapped-in store holds exactly the old one."""
    gone = 0
    for dp, dns, fns in os.walk(dst, topdown=False):
        rel = os.path.relpath(dp, dst)
        if rel.split(os.sep)[0] in _SKIP_DIRS:
            continue
        for n in fns + dns:
            if rel == "." and n in _SKIP_DIRS:
                continue
            t = os.path.join(dp, n)
            s = os.path.join(src, rel, n) if rel != "." else os.path.join(src, n)
            if not os.path.lexists(s):
                if os.path.isdir(t) and not os.path.islink(t):
                    os.rmdir(t)
                else:
                    os.remove(t)
                gone += 1
    if gone:
        say("%d entries gone from %s since: removed from %s" % (gone, src, dst))


def host_room_ok(path, min_gb, need):
    """The Windows drive behind the new store's disk file has room for the next
    copy and its floor. A full C: once took WSL down read-only (PAD-816), so
    the copy stops here instead; run it again later and it carries on."""
    if not path or not min_gb:
        return True
    import shutil
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return True
    return free - need >= min_gb * 2 ** 30


def cmd_ingest(src, dst, delete=False, host=None, host_min_gb=20):
    """Copy src's tree into dst, sharing each big file's blocks as it lands.
    A file already in dst with the same size and mtime is only indexed."""
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if delete:
        _delete_missing(src, dst)
    cache = HashCache(_cache_dir(dst))
    d = Deduper(cache)
    dirs = []
    order = []
    for dp, dns, fns in os.walk(src):
        dns[:] = sorted(x for x in dns if x not in _SKIP_DIRS)
        # the library first: it is the source every other copy shares with
        if dp == src and "library" in dns:
            dns.remove("library")
            dns.insert(0, "library")
        rel = os.path.relpath(dp, src)
        dirs.append((dp, os.path.join(dst, rel) if rel != "." else dst))
        # a link to a FOLDER is listed among the folders (and, not followed, never walked): it is copied as the link it
        # is. Missed, 191 of Spike 3's links were left out of the first copy (PAD-1453, found by comparing links).
        links = [x for x in dns if os.path.islink(os.path.join(dp, x))]
        dns[:] = [x for x in dns if x not in links]
        for n in sorted(fns + links):
            order.append((os.path.join(dp, n), os.path.join(dst, rel, n) if rel != "." else os.path.join(dst, n)))
    t0 = time.time()
    copied = 0
    try:
        for sdir, ddir in dirs:
            os.makedirs(ddir, exist_ok=True)
        for i, (s, t) in enumerate(order, 1):
            try:
                st = os.lstat(s)
            except FileNotFoundError:          # pruned or replaced while the store works on: swap catches it up
                continue
            if stat.S_ISLNK(st.st_mode):
                if not os.path.lexists(t):
                    os.symlink(os.readlink(s), t)
                    _copy_meta(s, t, st)
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            have = os.path.lexists(t) and os.lstat(t).st_size == st.st_size \
                and os.lstat(t).st_mtime_ns == st.st_mtime_ns
            if not have:
                if not host_room_ok(host, host_min_gb, st.st_blocks * 512):
                    say("STOPPED: %s would leave under %d GB free on the Windows drive; free space there and run "
                        "this again - it carries on from %s" % (os.path.relpath(s, src), host_min_gb, os.path.relpath(s, src)))
                    print("ingest\tstopped\t%d" % i, flush=True)
                    return 3
                try:
                    _copy_sparse(s, t, sync=st.st_size >= MIN_FILE)
                except FileNotFoundError:
                    continue
                if st.st_size >= MIN_FILE:
                    punch_zeros(t)
                _copy_meta(s, t, st)
                copied += st.st_blocks * 512
            if st.st_size >= MIN_FILE and not t.endswith((".partial", ".part")):
                # (a file already there from an interrupted run is shared now unless done.txt has it)
                got = d.take(t)
                say("%d/%d %s%s%s" % (i, len(order), os.path.relpath(s, src),
                                      "" if not have else " (already there)",
                                      ", %.2f GiB shared" % (got / 2 ** 30) if got else ""))
        for sdir, ddir in reversed(dirs):
            _copy_meta(sdir, ddir, os.lstat(sdir))
        _syncfs(dst)
    finally:
        d.close()
    print("ingest\t%d\t%d\t%d\t%d" % (len(order), copied, d.shared, d.differs + d.failed), flush=True)
    say("%d files, %.1f GiB copied, %.1f GiB shared, %.0f s; %d ranges refused"
        % (len(order), copied / 2 ** 30, d.shared / 2 ** 30, time.time() - t0, d.differs + d.failed))
    return 0


def cmd_dezero(roots):
    """Punch the all-zero blocks out of every big file under the roots."""
    total = 0
    for r in roots:
        for p, _st in big_files(r, now=0):
            got = punch_zeros(p)
            total += got
            if got:
                say("%s: %.2f GiB of zeros made holes" % (os.path.relpath(p, r), got / 2 ** 30))
    print("dezero\t%d" % total, flush=True)
    say("%.1f GiB of zero blocks made holes" % (total / 2 ** 30))
    return 0


def _same(a, b):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x = fa.read(CHUNK)
            y = fb.read(CHUNK)
            if x != y:
                return False
            if not x:
                return True


def cmd_verify(src, dst):
    """Byte-compare every regular file under src with its copy under dst."""
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    bad = n = 0
    for dp, dns, fns in os.walk(src):
        dns[:] = sorted(x for x in dns if x not in _SKIP_DIRS)
        links = [x for x in dns if os.path.islink(os.path.join(dp, x))]
        dns[:] = [x for x in dns if x not in links]
        for f in sorted(fns + links):
            s = os.path.join(dp, f)
            t = os.path.join(dst, os.path.relpath(s, src))
            st = os.lstat(s)
            if stat.S_ISLNK(st.st_mode):
                # links too, to files and to folders: the same target, as a link
                n += 1
                if not (os.path.islink(t) and os.readlink(t) == os.readlink(s)):
                    bad += 1
                    say("DIFFERS (link): %s" % os.path.relpath(s, src))
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            n += 1
            ok = os.path.isfile(t) and os.path.getsize(t) == st.st_size and _same(s, t)
            if not ok:
                bad += 1
                say("DIFFERS: %s" % os.path.relpath(s, src))
    print("verify\t%d\t%d" % (n, bad), flush=True)
    say("%d files compared, %d differ" % (n, bad))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("dedupe")
    a1.add_argument("--dry", action="store_true")
    a1.add_argument("roots", nargs="+")
    a2 = sub.add_parser("ingest")
    a2.add_argument("--delete", action="store_true", help="remove what src no longer has")
    a2.add_argument("--host", default="", help="the Windows drive the new disk file is on, as WSL sees it (/mnt/c)")
    a2.add_argument("--host-min-gb", type=int, default=20)
    a2.add_argument("src")
    a2.add_argument("dst")
    a4 = sub.add_parser("dezero")
    a4.add_argument("roots", nargs="+")
    a3 = sub.add_parser("verify")
    a3.add_argument("src")
    a3.add_argument("dst")
    a = ap.parse_args(argv)
    if a.cmd == "dedupe":
        return cmd_dedupe(a.roots, a.dry)
    if a.cmd == "ingest":
        return cmd_ingest(a.src, a.dst, a.delete, a.host, a.host_min_gb)
    if a.cmd == "dezero":
        return cmd_dezero(a.roots)
    return cmd_verify(a.src, a.dst)


if __name__ == "__main__":
    sys.exit(main())
