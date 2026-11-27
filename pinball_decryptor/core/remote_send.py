"""Send a build's changes to a machine over remote access, instead of writing the whole card (PAD-1397).

A machine whose card was built with remote access on (PR #38, core/ssh_card.py) runs a key-only SSH server that
trusts this computer's own key (core/pad_ssh_key.py).  On both Spike 2 and Spike 3 the game partition is mounted
read-only at ``/games`` and the system partition at ``/``; root may remount either read-write, and the card's own
``/etc/init.d/game_monitor`` runs ``/games/game`` in a loop, so a game that is stopped starts again by itself.

So a Send:

1. **plans** what to change, from the build and the card it was built from, both read on this computer: every
   file, link and folder of the system and game partitions whose inode differs between the two (size, times,
   owner, mode, link target, blocks; then the bytes compared, so a file that only moved is no change), and the byte
   ranges the build patched in place inside files that kept their blocks (the build record: ``inplace`` on Spike 2,
   ``send_ranges`` on Spike 3).  A build that changes the boot partition, or turns remote access off on the card,
   is refused: that one needs the whole card written;
2. **checks** the machine is running that card: every game file this build leaves alone must be on the machine at
   the build's size, and every file it changes must be either the original's or what an earlier Send put there
   (the machine's own record, ``/data/pad/remote_send.json``), never something else;
3. **uploads** each changed file beside its destination under a temporary name and checks its sha1 on the machine
   (the only hash Spike 2's busybox has), only then remounts the partition read-write, renames them into place,
   applies the in-place ranges (read back after), removes what the build removed, and syncs;
4. **restarts the game** (``kill -9`` of the ``game`` process: game_monitor starts it again on the new files; on
   Spike 3 the crash mark its restart counter would count is taken off again) and remounts read-only.

The remote access session itself runs on the system partition (busybox is the shell and every tool a Send uses;
the server and libc are there too), so a file there is never changed in place, even by the delta: it is replaced
by a new file renamed over it (:func:`delta_replace`), which running programs don't see until the machine
restarts, and system files are removed only after every new one is in place.  Only game files, with the game
stopped, change in place.

Files go on with the build's own owner and mode.  Nothing outside ``/`` and ``/games`` is touched apart from the
record in ``/data/pad``.  A Send interrupted part way leaves the machine running the files it had, with temporary
files removed; one cut off during the in-place step is finished by the next Send (the record says so)."""

import contextlib
import hashlib
import io
import json
import os
import posixpath
import re
import shlex
import stat
import threading
import time
from pathlib import Path

GAMES = "/games"
ROOT = "/"
LEDGER = "/data/pad/remote_send.json"
#: PAD-1444 (David: "Network ssh compare is too slow. Can we cache this somehow?"): the sha1s the machine worked
#: out on earlier Sends, each with the file's size, times and inode as they were then (:class:`HashCache`)
HASH_CACHE = "/data/pad/hash_cache.json"
#: a record written as PAD restarted the machine still holds after that restart when the machine came up within
#: this many seconds of it: too soon for its card to have been taken out, rewritten on a computer and put back
HASH_CACHE_REBOOT = 300
TMP_TAG = ".pad-send"
#: room kept free on a partition beyond the files a Send puts on it
SPARE = 8 << 20
#: the longest command sent on the command line itself; longer goes as a script file (dropbear's MAX_CMD_LEN 9000)
SCRIPT_INLINE_MAX = 4000


class SendError(Exception):
    """A Send that must not (or could not) go ahead; the message is for the user."""


class Unreachable(SendError):
    """Nothing answered at the machine's address (PAD-1427: a remembered machine is looked for again)."""


def unreachable_reason(host, port, err, waited):
    """PAD-1430: what a failed connection to the machine means, said so the user knows what to do next.  A
    timeout means nothing is at that address; a refusal means a device is there without remote login; no route
    means this computer can't get to that network at all."""
    import errno
    import socket
    code = getattr(err, "winerror", None) or getattr(err, "errno", None)
    where = "%s on port %d" % (host, port)
    detail = getattr(err, "strerror", None) or str(err) or err.__class__.__name__
    if isinstance(err, socket.timeout) or code in (errno.ETIMEDOUT, 10060):
        return ("Nothing answered at %s in %g seconds: no device seems to be at that address right now. The router "
                "may have given the machine a different address since; press Find my machine to look for it. "
                "Is the machine switched on and finished starting up?" % (where, waited))
    if code in (errno.ECONNREFUSED, 10061):
        return ("A device is at %s, but it turned the connection away: it is not running remote login. Either "
                "it is not the machine (another device has that address now: press Find my machine), or the "
                "machine's card was not set up for remote access." % where)
    if code in (errno.EHOSTUNREACH, errno.ENETUNREACH, 10065, 10051):
        return ("This computer has no route to %s (%s). Is this computer on the same network as the machine, not "
                "a guest network or a VPN?" % (where, detail))
    return ("Couldn't reach %s (%s). Is the machine on, on your network, and running a card set up for remote "
            "access?" % (where, detail))


class NotThisCard(SendError):
    """The machine isn't running the card a build was made from: the quick Send can't be used, the full one can."""


def _sha1_chunks(chunks):
    h = hashlib.sha1()
    for _off, buf in chunks:
        h.update(buf)
    return h.hexdigest()


# ===================================================================== the two cards
def _fstab(reader):
    """The system partition's /etc/fstab, b'' when there is no such file.  PAD-1619: a card Stern's updater
    brought up to date has it as a link into /spk/packages, which is followed (its own bytes are the link text)."""
    from . import ssh_card
    from .card_extras import ExtrasError
    try:
        node = ssh_card.resolve(reader, "/etc/fstab")[1]
    except ExtrasError:
        return b""
    if node is None or stat.S_IFMT(node["mode"]) != stat.S_IFREG or node["size"] > (1 << 20):
        return b""
    return bytes(reader.read_file_bytes(node))


class _Tree:
    """One partition of one image, walked: ``{machine path: (kind, inode, signature)}``."""

    def __init__(self, reader, mount):
        self.reader, self.mount = reader, mount
        self.entries = {}
        #: PAD-1543: each regular file's inode number in the image, so files that are one file under several
        #: names (a multi-boot card's shared store) can be told
        self.inos = {}
        for rel, kind, ino, node in reader.iter_tree():
            path = posixpath.join(mount, rel)
            self.entries[path] = (kind, node, self._sig(kind, node))
            if kind == "file":
                self.inos[path] = ino

    def _sig(self, kind, node):
        base = (kind, node["mode"], node["uid"], node["gid"])
        if kind == "dir":
            return base
        sig = base + (node["size"], node["mtime"], node["ctime"])
        if kind == "symlink":
            return sig + (self.reader.read_symlink(node),)
        if kind == "file":
            try:
                runs = tuple((f, d - self.reader.base, n) for f, d, n in self.reader.mapped_ranges(node))
            except Exception:                           # noqa: BLE001 - an inode we can't map: compare bytes
                runs = None
            return sig + (runs,)
        return sig

    def get(self, path):
        return self.entries.get(path)

    def chunks(self, node):
        return self.reader.read_file_chunks(node)

    def sha1(self, node):
        return _sha1_chunks(self.chunks(node))

    def link(self, node):
        return self.reader.read_symlink(node)

    def read_range(self, node, off, n):
        return self.reader.read_range(node, off, n)


class _ChunkFile(io.RawIOBase):
    """A file of the build image, read in order, for an upload."""

    def __init__(self, tree, node):
        self._tree, self._node = tree, node
        self.rewind()

    def rewind(self):
        """PAD-1436: from the first byte again (an upload cut off by a dropped connection is sent again whole)."""
        self._it = iter(self._tree.chunks(self._node))
        self._buf, self._at = b"", 0

    def readable(self):
        return True

    def read(self, n=-1):
        if self._at >= len(self._buf):
            nxt = next(self._it, None)
            if nxt is None:
                return b""
            self._buf, self._at = bytes(nxt[1]), 0
        end = len(self._buf) if n is None or n < 0 else min(len(self._buf), self._at + n)
        out = self._buf[self._at:end]
        self._at = end
        return out


class Op:
    """One change: ``mkdir`` / ``put`` (a file whole) / ``link`` / ``delete`` / ``patch`` (byte ranges)."""

    def __init__(self, kind, path, **kw):
        self.kind, self.path = kind, path
        self.mount = GAMES if path == GAMES or path.startswith(GAMES + "/") else ROOT
        self.node = kw.get("node")
        self.mode = kw.get("mode", 0)
        self.uid, self.gid = kw.get("uid", 0), kw.get("gid", 0)
        self.size = kw.get("size", 0)
        self.sha1 = kw.get("sha1")
        self.stock = kw.get("stock")          # the original's state: None (absent), ("file", sha1), ("link", t), ("dir",)
        self.target = kw.get("target")
        self.ranges = kw.get("ranges") or []  # [(off, built bytes, stock bytes)]
        self.from_ledger = kw.get("from_ledger", False)

    def __repr__(self):
        return "Op(%s %s)" % (self.kind, self.path)


def _state(tree, entry):
    if entry is None:
        return None
    kind, node, _sig = entry
    if kind == "file":
        return ("file", tree.sha1(node))
    if kind == "symlink":
        return ("link", tree.link(node))
    if kind == "dir":
        return ("dir",)
    return ("other",)


def _desired(path, out_tree, src_tree, ranges=None, from_ledger=False):
    """The op that makes *path* on the machine what it is on the build, or None when the build has it as the
    original does (and *from_ledger* is False: the machine's record says an earlier Send changed it)."""
    o, s = out_tree.get(path), src_tree.get(path)
    if o is None:
        if s is None and not from_ledger:
            return None
        return Op("delete", path, stock=_state(src_tree, s), from_ledger=from_ledger)
    kind, node, sig = o
    if kind == "file" and s is not None and s[0] == "file" and s[2] == sig:
        # the very inode the original has, blocks and all: only the in-place ranges can differ, and they are
        # sent as ranges (a game's image.bin is gigabytes; reading or sending it whole is what this avoids)
        if ranges:
            return _patch(path, out_tree, src_tree, node, s[1], ranges, from_ledger)
        if not from_ledger:
            return None
    stock = _state(src_tree, s)
    own = dict(mode=stat.S_IMODE(node["mode"]), uid=node["uid"], gid=node["gid"], stock=stock,
               from_ledger=from_ledger)
    same_owner = s is not None and s[2][1:4] == sig[1:4]
    if kind == "dir":
        if s is not None and s[0] == "dir" and s[2] == sig and not from_ledger:
            return None
        return Op("mkdir", path, **own)
    if kind == "symlink":
        t = out_tree.link(node)
        if stock == ("link", t) and same_owner and not from_ledger:
            return None
        return Op("link", path, target=t, **own)
    if kind == "file":
        digest = out_tree.sha1(node)
        if stock == ("file", digest) and same_owner and not ranges and not from_ledger:
            return None
        return Op("put", path, node=node, size=node["size"], sha1=digest, **own)
    raise SendError("%s on the build is a special file, which a Send can't put on a machine; Write the card "
                    "instead." % path)


def _patch(path, out_tree, src_tree, node, src_node, ranges, from_ledger=False):
    rr = []
    for off, n in ranges:
        rr.append((int(off), out_tree.read_range(node, off, n),
                   src_tree.read_range(src_node, off, n) if src_node is not None else None))
    return Op("patch", path, ranges=rr, stock=None, from_ledger=from_ledger)


class Plan:
    """What a Send changes, worked out from the build and its original.  Keeps both images open (``close``)."""

    def __init__(self, build, source, platform, trees, ranges, closers, card_id):
        self.build, self.source, self.platform = build, source, platform
        self.trees = trees            # {mount: (out_tree, src_tree)}
        self.ranges = ranges          # {path: [(off, n)]} recorded in-place ranges
        self._closers = closers
        self.card_id = card_id
        self.ops = []
        for mount, (out_t, src_t) in trees.items():
            for path in sorted(set(out_t.entries) | set(src_t.entries)):
                op = _desired(path, out_t, src_t, ranges.get(path))
                if op is not None:
                    self.ops.append(op)
        done = {op.path for op in self.ops}
        for path, rr in sorted(ranges.items()):
            if path in done:
                continue
            out_t, src_t = self.trees[_mount_of(path)]
            o, s = out_t.get(path), src_t.get(path)
            if o is None or o[0] != "file":
                continue
            self.ops.append(_patch(path, out_t, src_t, o[1], s[1] if s else None, rr))

    def close(self):
        for fn in reversed(self._closers):
            with contextlib.suppress(Exception):
                fn()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # what the machine's record asks for on top of this build's own changes
    def extra_for(self, ledger):
        if not ledger:
            return []
        have = {op.path for op in self.ops}
        extra = []
        for path in sorted(ledger.get("paths") or []):
            if path in have or _mount_of(path) not in self.trees:
                continue
            out_t, src_t = self.trees[_mount_of(path)]
            op = _desired(path, out_t, src_t, from_ledger=True)
            if op is not None:
                extra.append(op)
                have.add(path)
        for path, rr in sorted((ledger.get("ranges") or {}).items()):
            if _mount_of(path) not in self.trees:
                continue
            out_t, src_t = self.trees[_mount_of(path)]
            o, s = out_t.get(path), src_t.get(path)
            if o is None or o[0] != "file":
                continue
            known = next((op for op in self.ops + extra if op.path == path), None)
            if known is not None and known.kind == "put":
                continue
            mine = {r[0] for r in known.ranges} if known is not None else set()
            rest = [(off, n) for off, n in rr if int(off) not in mine]
            if not rest:
                continue
            op = _patch(path, out_t, src_t, o[1], s[1] if s else None, rest, from_ledger=True)
            if known is not None:
                known.ranges += op.ranges
            else:
                extra.append(op)
        return extra

    def record(self):
        """The machine's record once this build is on it: what differs there from the original."""
        return {"card": self.card_id,
                "paths": sorted(op.path for op in self.ops if op.kind != "patch"),
                "ranges": {op.path: [[off, len(b)] for off, b, _s in op.ranges]
                           for op in self.ops if op.kind == "patch"}}


def _mount_of(path):
    return GAMES if path == GAMES or path.startswith(GAMES + "/") else ROOT


# --------------------------------------------------------------- opening the images
def _partitions(path):
    from .ssh_card import _partitions as parts
    with open(path, "rb") as f:
        return parts(f)


def _same_bytes(a_path, a, b_path, b):
    if a[3] != b[3]:
        return False
    with open(a_path, "rb") as fa, open(b_path, "rb") as fb:
        fa.seek(a[2])
        fb.seek(b[2])
        left = a[3]
        while left:
            n = min(left, 4 << 20)
            if fa.read(n) != fb.read(n):
                return False
            left -= n
    return True


def open_plan(build, log=None):
    """The :class:`Plan` for the finished build at *build*.  Raises :class:`SendError` with what to do instead."""
    from ..plugins.stern import engine
    from . import ssh_card
    log = log or (lambda *a, **k: None)
    if not build or not os.path.isfile(build):
        raise SendError("There is no built image to send yet: build it first.")
    rec = engine.read_build_manifest(build) or {}
    if not rec.get("complete"):
        raise SendError("The image at %s is not a finished build; build it again." % build)
    info = ssh_card.inspect_image(build)
    if not info.get("supported"):
        raise SendError("Remote access isn't possible with this card: %s" % (info.get("reason") or ""))
    from . import pad_ssh_key
    mine = pad_ssh_key.public_line().split()
    if not info.get("enabled") or len(mine) < 2 or mine[1] not in info.get("public_keys", ""):
        raise SendError("This build has remote access off, or doesn't let this computer in. Turn Remote access "
                        "on (Network tab) and write the card onto the machine once; after that, Send works.")
    if info["platform"] == "stern-spike3":
        return _open_spike3(build, rec, log)
    return _open_spike2(build, rec, log)


def _open_spike2(build, rec, log):
    from ..plugins.stern.ext4 import Ext4Reader
    stock = (rec.get("stock") or {}).get("path")
    if not stock or not os.path.isfile(stock):
        raise SendError("The card this image was built from (%s) isn't there any more, and a Send works out "
                        "what changed from it." % (stock or "unknown"))
    out_parts = {p[0]: p for p in _partitions(build)}
    src_parts = {p[0]: p for p in _partitions(stock)}
    for n in (2, 3):
        if n not in out_parts or n not in src_parts:
            raise SendError("This card's partitions aren't the usual Spike 2 layout; write the card instead.")
    if 1 in out_parts and not _same_bytes(build, out_parts[1], stock, src_parts.get(1, (1, 0, 0, -1))):
        raise SendError("This build changes the card's boot partition, which needs the whole card written.")
    closers, trees = [], {}
    fo, fs = open(build, "rb"), open(stock, "rb")
    closers += [fo.close, fs.close]
    try:
        for n, mount in ((2, ROOT), (3, GAMES)):
            o, s = out_parts[n], src_parts[n]
            trees[mount] = (_Tree(Ext4Reader(fo, o[2], o[3]), mount), _Tree(Ext4Reader(fs, s[2], s[3]), mount))
        text = _fstab(trees[ROOT][0].reader)
        if not any(line.split()[:2] == [b"/dev/mmcblk0p3", b"/games"] for line in text.splitlines()
                   if line.strip() and not line.startswith(b"#")):
            raise SendError("This card doesn't mount its game partition the usual Spike 2 way; write the card "
                            "instead.")
        off_mount = {src_parts[2][2]: ROOT, src_parts[3][2]: GAMES}
        ranges = {}
        for key, rr in (rec.get("inplace") or {}).items():
            part_off, _, rel = key.partition(":")
            mount = off_mount.get(int(part_off))
            if mount is None:
                raise SendError("This build patches a partition other than the system and game ones; write the "
                                "card instead.")
            ranges[posixpath.join(mount, rel.lstrip("/"))] = [(int(a), int(b)) for a, b in rr]
        card = {"name": os.path.basename(stock), "size": os.path.getsize(stock)}
        return Plan(build, stock, "stern-spike2", trees, ranges, closers, card)
    except BaseException:
        for fn in closers:
            fn()
        raise


def _open_spike3(build, rec, log):
    from ..plugins.stern import spike3_card
    from ..plugins.stern.ext4 import Ext4Reader
    from . import ssh_spike3
    stock = rec.get("source_path")
    if not stock or not os.path.isfile(stock):
        raise SendError("The card this image was built from (%s) isn't there any more, and a Send works out "
                        "what changed from it." % (stock or "unknown"))
    if "send_ranges" not in rec:
        raise SendError("This Spike 3 image was built by an older version, which didn't note what it changed in "
                        "place; build it again, then send.")
    out_parts = {p[0]: p for p in _partitions(build)}
    src_parts = {p[0]: p for p in _partitions(stock)}
    if 1 in out_parts and not _same_bytes(build, out_parts[1], stock, src_parts.get(1, (1, 0, 0, -1))):
        raise SendError("This build changes the card's boot partition, which needs the whole card written.")
    keys = ssh_spike3.key_for(build)
    stack = contextlib.ExitStack()
    try:
        trees = {}
        ro = stack.enter_context(ssh_spike3.open_rootfs(build, key_source=keys))
        rs = stack.enter_context(ssh_spike3.open_rootfs(stock, key_source=keys))
        trees[ROOT] = (_Tree(Ext4Reader(ro, 0, ro.size), ROOT), _Tree(Ext4Reader(rs, 0, rs.size), ROOT))
        go = spike3_card.open_games(build, key_source=keys)
        stack.callback(go.close)
        gs = spike3_card.open_games(stock, key_source=keys)
        stack.callback(gs.close)
        trees[GAMES] = (_Tree(Ext4Reader(go, 0, go.size), GAMES), _Tree(Ext4Reader(gs, 0, gs.size), GAMES))
        ranges = {p: [(int(a), int(b)) for a, b in rr] for p, rr in (rec.get("send_ranges") or {}).items()}
        card = {"name": os.path.basename(stock), "size": os.path.getsize(stock)}
        return Plan(build, stock, "stern-spike3", trees, ranges, [stack.close], card)
    except BaseException:
        stack.close()
        raise


# ===================================================================== the machine
class Machine:
    """What a Send asks of the machine.  :class:`SshMachine` over remote access; tests use a stand-in."""

    #: PAD-1436: where a machine says it lost the connection and got it back, and what it asks whether to stop
    #: trying; the Send sets them
    log = staticmethod(lambda *a, **k: None)
    cancel = staticmethod(lambda: False)

    def state(self, paths):
        """``{path: None | ("file", sha1) | ("link", target) | ("dir",) | ("other",)}``."""
        raise NotImplementedError

    def sizes(self, root):
        """``{path: size}`` of every regular file under *root*."""
        raise NotImplementedError

    def read_ranges(self, path, ranges):
        raise NotImplementedError

    def free(self, mount):
        raise NotImplementedError

    def remount(self, mount, rw):
        raise NotImplementedError

    def mkdir(self, path, mode, uid, gid):
        raise NotImplementedError

    def upload(self, path, fileobj, size, mode, uid, gid, callback=None):
        raise NotImplementedError

    def commit(self, renames, links, deletes):
        raise NotImplementedError

    def hardlink(self, pairs):
        """PAD-1543: make each ``(existing file, name)``'s *name* that same file (a hard link), replacing what the
        name was.  A multi-boot card's shared store: one file, held once, under each game's own name for it."""
        raise NotImplementedError

    def write_ranges(self, path, ranges):
        raise NotImplementedError

    def remove(self, paths):
        raise NotImplementedError

    def sync(self):
        raise NotImplementedError

    def restart_game(self):
        """Stop the game for game_monitor to start again; returns a line for the log."""
        raise NotImplementedError

    def read_ledger(self):
        raise NotImplementedError

    def write_ledger(self, data):
        raise NotImplementedError

    def close(self):
        pass

    def widen(self, log=None):
        """Make the connection fast for a Send's bulk (PAD-1434, :meth:`SshMachine.widen`); False when not."""
        return False

    # the full Send (an image that isn't a build of the card the machine runs)
    def layout(self):
        raise NotImplementedError

    def mounts(self):
        raise NotImplementedError

    def walk(self, root, skip=()):
        raise NotImplementedError

    def mount_part(self, num, path):
        raise NotImplementedError

    def umount_part(self, path):
        raise NotImplementedError

    def raw_sha1(self, num):
        raise NotImplementedError

    def raw_write(self, num, fileobj, size, sha1):
        raise NotImplementedError

    def set_mtime(self, path, mtime):
        pass

    def file_sha1s(self, paths):
        """``{path: ("file", sha1)}`` for regular files (the full Send's compare); :meth:`state` by default."""
        return self.state(paths)

    # PAD-1444: what the hash record (HashCache) needs.  A machine that can't say leaves it off: every compare
    # hashes again, as before
    def file_ids(self, paths):
        """``(machine clock, {path: (size, mtime, inode, ctime)})`` for the regular files among *paths*, or None."""
        return None

    def boot_info(self):
        """``{"boot": boot id, "btime": when it booted, "now": its clock, "mounts": what / and /games are}``."""
        return None

    def read_hash_cache(self):
        return getattr(self, "_hash_cache", None)

    def write_hash_cache(self, data):
        self._hash_cache = data

    # the delta
    def block_hashes(self, path):
        """``(size, [sha1 of each DELTA_BLOCK])`` of the machine's file."""
        raise NotImplementedError

    def truncate(self, path, size):
        raise NotImplementedError

    def set_attrs(self, path, mode, uid, gid):
        raise NotImplementedError

    def copy(self, src, dst):
        """A copy of the machine's file made on the machine (mode, owner and times kept): the system partition's
        delta goes into it, then it is renamed over the original."""
        raise NotImplementedError

    # PAD-1435: 64 KB pieces the machine already has (send_pieces); a machine without its helper uses the delta
    def pieces_ready(self):
        """Whether the machine can hash and copy 64 KB pieces itself (``resources/pieces/padpieces``)."""
        return False

    def piece_hashes(self, paths):
        """``{path: (size, [sha1 hex of each send_pieces.PIECE])}`` of the machine's files (an unreadable one is
        left out)."""
        raise NotImplementedError

    def copy_pieces(self, copies):
        """Do *copies* ``[(src, soff, dst, doff, nbytes)]`` on the machine, in order (a missing *dst* is created,
        none is cut short).  Returns the bytes copied."""
        raise NotImplementedError

    def in_use(self):
        """Every file a running program has loaded or open (its program, libraries, open files): replacing one
        frees no room until the machine restarts, as the program keeps the old copy."""
        return set()

    def stop_game(self):
        raise NotImplementedError

    def reboot(self):
        raise NotImplementedError

    # ---- PAD-1427: what the machine shows while a Send changes it (a machine with no screen shows nothing)
    def pause_game(self):
        """Hold the game for a Send: the card's own message screen says PAD is updating it."""

    def game_held(self):
        """True while a Send holds the machine's game (pause_game until resume_game or a stop)."""
        return False

    def resume_game(self, text=None):
        """The game back after a Send (the card's own loop starts it again); *text* is the screen's last word."""
        return self.restart_game()

    def screen_progress(self, done, total, what=""):
        """How far the Send is, for the machine's screen."""

    def screen_changing(self):
        """From here the machine's files change: a lost connection no longer puts the game back by itself."""

    def screen_stopped(self, changed):
        """A Send that stopped short (an error, Cancel): said on the machine; the game back if nothing changed."""


def screen_text(*lines):
    """A message for the card's own ``dprint``: four lines of sixteen characters, each centred."""
    return "".join(str(l)[:16].center(16) for l in lines[:4]).rstrip()


def _q(path):
    return shlex.quote(path)


#: Processes by the KERNEL's name for them (``/proc/<pid>/stat``): ``game`` is the program /games/game started on
#: both platforms, with or without modes (a hook that execs it hands the name on), ``game_monitor`` the card's
#: loop.  Not ``pidof``: Spike 2's is sysvinit's, which goes by the command line (a hook changes that), and not
#: ``pkill -f``, which matches the very shell running this.
PIDS_FN = r"""
pids_named() {
  for d in /proc/[0-9]*; do
    read -r s < "$d/stat" 2>/dev/null || continue
    case "$s" in *" ($1) "*) printf '%s ' "${d#/proc/}" ;; esac
  done
}
"""

#: the restart, as the card's own tools do it: kill -9 is a crash game_monitor restarts from, where a polite TERM
#: could be the game's own "exit" (Spike 3's game_monitor stops looping on exit reason 2).  Spike 3 counts the
#: restart in /tmp/game_restarts (five clear the connectivity cache, ten reboot): the mark this one left goes.
RESTART_SCRIPT = PIDS_FN + r"""
R=/tmp/game_restarts
before=" $(ls $R 2>/dev/null | tr '\n' ' ') "
old=$(pids_named game)
if [ -z "$old" ]; then echo "PAD_SEND_NOT_RUNNING"; exit 0; fi
kill -9 $old
i=0
new=""
while [ $i -lt 40 ]; do
  sleep 1
  new=$(pids_named game)
  if [ -n "$new" ] && [ "$new" != "$old" ]; then break; fi
  new=""
  i=$((i+1))
done
for f in $(ls $R 2>/dev/null); do
  case "$before" in *" $f "*) ;; *) rm -f "$R/$f" ;; esac
done
if [ -n "$new" ]; then echo "PAD_SEND_RESTARTED $new"; else echo "PAD_SEND_NOT_BACK"; fi
"""

#: PAD-1427 (David: "what happens if we copy files over in the middle of a game? ... we need some way on the
#: machine to see feedback that the update is happening (and the connection is live)").  A Send holds the game the
#: way the card itself does for an update: game_monitor (its restart loop) is frozen (SIGSTOP), the game ended,
#: and the card's own message screen runs: boot_display + dprint, which Stern's updater uses for "APPLYING UPDATE
#: PLEASE WAIT" (/etc/init.d/game; Spike 3's S95game and game_monitor alike).  PAD redraws it every few seconds
#: with how far the Send is and a mark that moves while the connection is live; a watchdog on the machine puts
#: the game back (SIGCONT: the card's own loop restarts it) when PAD has gone quiet and nothing was changed yet.
SCREEN_DIR = "/run/pad-send-screen"
#: seconds without a word from PAD before the machine gives up on it
SCREEN_LOST = 45
SCREEN_FNS = PIDS_FN + r"""
W=@W@
pad_tools() {
  BD=""; DP=""
  for d in /games/spike3/bin /usr/local/spike /usr/local/bin; do
    if [ -z "$BD" ] && [ -x "$d/boot_display" ]; then BD="$d/boot_display"; fi
    if [ -z "$DP" ] && [ -x "$d/dprint" ]; then DP="$d/dprint"; fi
  done
  [ -n "$BD" ] && [ -n "$DP" ]
}
pad_say() {
  if ! pad_tools; then
    # PAD-1587: a JJP machine has no dprint; its own message screen (rungame.sh's "SECURITY KEY MISSING") is jimg
    J=/jjpe/gen1/scripts/jimg; P=/jjpe/gen1/miscfiles/graphics/JJP_logo_message.png
    [ -x "$J" ] && [ -f "$P" ] || return 0
    for p in $(pids_named jimg); do kill $p 2>/dev/null; done
    t=$(printf '%s' "$1" | cut -c1-16 | sed 's/^ *//; s/ *$//')
    m=$(printf '%s' "$1" | cut -c17-64 | sed 's/  */ /g; s/^ //; s/ $//')
    (trap '' HUP; DISPLAY=:0 exec "$J" 60000 "$P" "$t" "$m") </dev/null >/dev/null 2>&1 &
    return 0
  fi
  if [ -z "$(pids_named boot_display)" ]; then
    # detached from this session (the card's busybox has no setsid): hangup ignored, so it outlives the login
    (trap '' HUP; exec "$BD") </dev/null >/dev/null 2>&1 &
    sleep 1
  fi
  "$DP" "$1" >/dev/null 2>&1
}
pad_resume() {
  touch $W/done
  for p in $(pids_named boot_display) $(pids_named jimg); do kill $p 2>/dev/null; done
  c=$(cat $W/menu 2>/dev/null)
  [ -n "$c" ] && kill -CONT $c 2>/dev/null
  rm -f $W/menu
  m=$(cat $W/monitor 2>/dev/null)
  if [ -z "$m" ]; then echo "PAD_SEND_NOT_RUNNING"; return 0; fi
  old=" $(cat $W/game 2>/dev/null) "
  before=" $(cat $W/marks 2>/dev/null) "
  kill -CONT $m
  i=0
  new=""
  while [ $i -lt 40 ]; do
    sleep 1
    for p in $(pids_named game); do
      case "$old" in *" $p "*) ;; *) new=$p ;; esac
    done
    [ -n "$new" ] && break
    i=$((i+1))
  done
  for f in $(ls /tmp/game_restarts 2>/dev/null); do
    case "$before" in *" $f "*) ;; *) rm -f "/tmp/game_restarts/$f" ;; esac
  done
  rm -f $W/monitor
  if [ -n "$new" ]; then echo "PAD_SEND_RESTARTED $new"; else echo "PAD_SEND_NOT_BACK"; fi
}
"""

#: the watchdog, left running on the machine for the length of the Send
SCREEN_WATCH = r"""
. @W@/fns
while true; do
  sleep 5
  [ -f $W/done ] && exit 0
  now=$(date +%s)
  last=$(cat $W/alive 2>/dev/null || echo $now)
  [ $((now - last)) -lt @LOST@ ] && continue
  if [ "$(cat $W/phase 2>/dev/null)" = "changing" ]; then
    touch $W/done
    pad_say @LOST_CHANGED@
  else
    pad_say @LOST_SAFE@
    sleep 4
    pad_resume >/dev/null
  fi
  exit 0
done
"""

#: the game held for a Send: its loop frozen, the game ended, the message screen up, the watchdog started
PAUSE_SCRIPT = r"""
. @W@/fns
rm -f $W/done
date +%s > $W/alive
echo safe > $W/phase
ls /tmp/game_restarts 2>/dev/null | tr '
' ' ' > $W/marks
m=$(pids_named game_monitor)
# PAD-1587: a JJP machine's loop is rungame.sh (jjp.service: xinit runs it; it starts the game again when it ends)
[ -n "$m" ] || m=$(pids_named rungame.sh)
g=$(pids_named game)
echo "$m" > $W/monitor
echo "$g" > $W/game
[ -n "$m" ] && kill -STOP $m
# PAD-1587: the hold is checked, not assumed: the loop is stopped (state T) before the game is ended
for p in $m; do
  i=0
  while [ $i -lt 20 ]; do
    read -r st < /proc/$p/stat 2>/dev/null || break
    case "${st##*) }" in T*|t*) break ;; esac
    kill -STOP $p 2>/dev/null; sleep 0.1; i=$((i+1))
  done
done
[ -n "$g" ] && kill -9 $g
# Simon (2026-11-26): "This flickering is happening when the card is being updated" - a test card's menu (or a
# multi-boot card's) is not a game: it kept drawing beside the message screen.  It is frozen, not ended: ended, its
# select.sh would stop the menu network (padnet) the Send is using
c=$(pids_named codeselect)
echo "$c" > $W/menu
[ -n "$c" ] && kill -STOP $c
sleep 1
# PAD-1587: a game the loop started as the hold began (its restart and the hold crossed) is ended too, so no game
# runs on files a Send changes; the loop is stopped now, so none comes after it
for p in $(pids_named game); do
  read -r st < /proc/$p/stat 2>/dev/null || continue
  case "${st##*) }" in Z*) continue ;; esac
  case " $g " in *" $p "*) ;; *) kill -9 $p 2>/dev/null; g="$g $p" ;; esac
done
echo "$g" > $W/game
pad_say @TEXT@
(trap '' HUP; exec /bin/sh $W/watch) </dev/null >/dev/null 2>&1 &
echo "PAD_SEND_PAUSED $m"
"""

#: the game a machine runs, as the /games/game link names it; a JJP machine (PAD-1587) has no /games: its
#: setenv.sh names the game, said the same way (``/jjpe/<game>/game``) so machine_scan.game_of reads both
GAME_LINK = ('readlink /games/game 2>/dev/null || { [ -f /jjpe/gen1/setenv.sh ] && '
             '. /jjpe/gen1/setenv.sh >/dev/null 2>&1 && echo "/jjpe/$GAMENAME/game"; }')
DESCRIBE_SCRIPT = GAME_LINK + '; cat /etc/hostname 2>/dev/null; df -k /games 2>/dev/null | tail -n 1'

#: the delta's view of a machine file: its size, then the sha1 of each block (busybox dd + sha1sum, both cards)
BLOCKS_SCRIPT = r"""
f=@F@
s=$(wc -c < "$f") || exit 1
echo $s
n=$(( (s + @BS@ - 1) / @BS@ ))
i=0
while [ $i -lt $n ]; do
  dd if="$f" bs=@BS@ skip=$i count=1 2>/dev/null | sha1sum
  i=$((i+1))
done
"""

#: what running programs hold: each one's program, its mapped libraries and its open files (busybox tools only)
IN_USE_SCRIPT = r"""
for d in /proc/[0-9]*; do
  readlink "$d/exe"
  for f in "$d"/fd/*; do readlink "$f"; done
  sed -n 's|^[^/]*\(/.*\)$|\1|p' "$d/maps"
done 2>/dev/null | sort -u
"""

#: PAD-1444: the machine's clock, then type, size, mtime, inode and ctime of each file (metadata only: no file is read)
IDS_SCRIPT = r"""
date +%s
stat -c '%f %s %Y %i %Z %n' -- @PATHS@ 2>/dev/null
true
"""

#: PAD-1444: which boot this is, when it began, the clock, and what is mounted at / and /games (device, subfolder)
BOOT_SCRIPT = r"""
cat /proc/sys/kernel/random/boot_id
awk '$1 == "btime" {print $2}' /proc/stat
date +%s
awk '$5 == "/" || $5 == "/games" {print $5, $3, $4}' /proc/self/mountinfo
"""

STATE_SCRIPT = r"""
while IFS= read -r p; do
  if [ -L "$p" ]; then printf 'L %s\n' "$(readlink "$p")"
  elif [ -d "$p" ]; then echo D
  elif [ -f "$p" ]; then printf 'F %s\n' "$(sha1sum "$p" | cut -d' ' -f1)"
  elif [ -e "$p" ]; then echo O
  else echo N
  fi
done
"""


#: PAD-1436: a connection that drops part way through a Send (a remote machine's internet link, its Wi-Fi) is dialled
#: again for this long before the Send gives up; the step it cut off is then done again
RECONNECT_FOR = 300
#: the waits between tries, seconds (the last one repeats)
RECONNECT_WAITS = (2, 5, 10, 15, 30)
#: PAD-1436: a keepalive this often keeps a router's or a tunnel's idle timer from dropping the connection while
#: the machine works on a long command (hashing a big file) and nothing else crosses it
KEEPALIVE = 15

#: PAD-1436: after a reconnect, the game hold as it was: the watchdog that gave up on PAD started again (the game
#: still held), or the game it had put back held again (nothing had changed yet)
REHOLD_SCRIPT = r"""
W=@W@
[ -f $W/fns ] || { echo PAD_SEND_GONE; exit 0; }
. $W/fns
date +%s > $W/alive
if [ ! -f $W/done ]; then echo PAD_SEND_HELD; exit 0; fi
if [ -f $W/monitor ]; then
  rm -f $W/done
  (trap '' HUP; exec /bin/sh $W/watch) </dev/null >/dev/null 2>&1 &
  echo PAD_SEND_WATCHING
else
  echo PAD_SEND_RESUMED
fi
"""


def _again(fn):
    """PAD-1436: a step of a Send that can be done twice to the same end: when the connection drops under it, the
    machine is dialled again and the step done again from its start."""
    def step(self, *a, **kw):
        tries = 0
        while True:
            try:
                return fn(self, *a, **kw)
            except SendError:
                raise
            except Exception as e:                      # noqa: BLE001 - only a dead connection is retried
                if self._alive():
                    raise
                tries += 1
                if tries > 5:
                    raise SendError("The connection to the machine kept dropping; send again.") from None
                self.reconnect(e)
                for arg in list(a) + list(kw.values()):
                    if hasattr(arg, "rewind"):          # a file being sent goes again from its start
                        arg.rewind()
    step.__name__, step.__doc__ = fn.__name__, fn.__doc__
    return step


# PAD-1434: the Send's faster connection (SshMachine.widen)
LISTENER_PIDFILE = "/var/run/pad-sshd.pid"  # the machine's own listener (resources/ssh/sshd, Spike 2 and 3)
WIDE_PIDFILE = "/var/run/pad-sshd-send.pid"
WIDE_WINDOW = 4194304
WIDE_PORTS = (2222, 22222, 42222)
LANES = 2  # connections at once: one per core of the machine (a third added 4% over Wi-Fi)
SPREAD_MIN = 2 << 20  # a file smaller than this goes over one connection

# PAD-1465: a Send's big writes over plain TCP to the machine's helper (padpieces recv), not through SSH.  On a
# Godzilla's Wi-Fi (ARMv7, dropbear offering only AES-CTR + HMAC-SHA2-256) SSH tops out at 3.7-4.6 MB/s with the
# wide window and two lanes; raw TCP into the helper did 7-8 MB/s with the game running.  Every frame is signed with
# a key that went over SSH and is checked on the machine BEFORE it is written, so the bytes are no less trusted.
# PAD_SEND_RAW=0 keeps every byte on SSH.
RAW_MIN = SPREAD_MIN  # writes smaller than this stay on SSH (a raw lane costs a command and a connection)
RAW_FRAME = 1 << 20  # bytes per signed frame (the helper takes up to 4 MiB)
RAW_LANES = LANES  # raw connections at once (the helper is one process per connection, one per core)
RAW_HELLO = b"pad-recv hello"


def plain_allowed():
    """PAD-1467: False when the user keeps every byte on the encrypted connection (``PAD_SEND_RAW=0``, PAD-1465's
    switch for a Send's big writes; ``PAD_SEND_PLAIN=0`` says the same).  The Network tab's live view of the
    machine's screen asks this before it uses a plain connection of its own."""
    off = ("0", "no", "off", "false")
    return (os.environ.get("PAD_SEND_RAW", "1").strip().lower() not in off
            and os.environ.get("PAD_SEND_PLAIN", "1").strip().lower() not in off)
# stop a temporary listener, only when the pid in its file is still one (a stale file's pid may be reused)
WIDE_STOP = ("p=$(cat {f} 2>/dev/null); if [ -n \"$p\" ] && tr '\\000' ' ' < /proc/$p/cmdline 2>/dev/null "
             "| grep -q {f}; then kill \"$p\"; fi; rm -f {f}").format(f=WIDE_PIDFILE)


def _window(args):
    """The receive window a dropbear command line asks for (its default when none)."""
    for i, a in enumerate(args):
        v = args[i + 1] if a == "-W" and i + 1 < len(args) else a[2:] if a.startswith("-W") and len(a) > 2 else None
        if v is not None:
            with contextlib.suppress(ValueError):
                return int(v)
    return 24576


def _connect_lane(host, port, identity):
    return SshMachine(host, port, expect=identity)


def _pieces(fileobj, size, piece=1 << 20):
    off = 0
    while off < size:
        data = fileobj.read(min(piece, size - off))
        if not data:
            break
        yield off, data
        off += len(data)


def _home_network(host):
    """PAD-1465: whether *host* is on this computer's own network (a private or link-local address), where the
    raw lanes may carry a Send's bytes."""
    import ipaddress
    import socket
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (OSError, ValueError):
        return False
    if ip.is_loopback:
        return _LOOPBACK_OK
    return ip.is_private or ip.is_link_local


#: tests drive the helper on this computer
_LOOPBACK_OK = False


class _RawFailed(Exception):
    """PAD-1465: the raw lane couldn't carry a write (the step then goes over SSH)."""


def raw_frame(key, seq, kind, path=b"", off=0, data=b""):
    """One frame of the helper's ``recv`` (padpieces.c): header, path, data, HMAC-SHA1 over the sequence number
    and all of it."""
    import hmac
    import struct
    hdr = struct.pack(">BQII", ord(kind), off, len(data), len(path))
    mac = hmac.new(key, struct.pack(">Q", seq), hashlib.sha1)
    mac.update(hdr)
    mac.update(path)
    mac.update(data)
    return hdr + path, mac.digest()


class _RawLane:
    """PAD-1465: one plain TCP connection into the machine's helper, started over the SSH connection *machine*."""

    def __init__(self, machine):
        import hmac
        import socket
        self.key, self.seq, self.chan, self.sock = os.urandom(32), 0, None, None
        try:
            self.chan = machine.t.open_session()
            self.chan.settimeout(20)
            self.chan.exec_command("%s recv" % machine._pieces)
            self.chan.sendall(self.key.hex().encode() + b"\n")
            self.chan.shutdown_write()
            line = b""
            until = time.monotonic() + 20
            while not line.endswith(b"\n"):
                if time.monotonic() > until:
                    raise _RawFailed("the helper didn't say its port")
                got = self.chan.recv(256)
                if not got:
                    raise _RawFailed("the helper stopped: %s" % line.decode("utf-8", "replace").strip())
                line += got
            text = line.decode("utf-8", "replace").strip()
            if not text.startswith("port "):
                raise _RawFailed(text or "no port")
            self.sock = socket.create_connection((machine.host, int(text[5:])), timeout=5)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with contextlib.suppress(OSError):
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
            self.sock.settimeout(120)
            self.sock.sendall(hmac.new(self.key, RAW_HELLO, hashlib.sha1).digest())
        except BaseException:
            self.close()
            raise

    def write(self, path, off, data):
        head, mac = raw_frame(self.key, self.seq, "W", path.encode("utf-8", "surrogateescape"), off, data)
        self.seq += 1
        self.sock.sendall(head)
        self.sock.sendall(data)
        self.sock.sendall(mac)

    def finish(self):
        """End the stream; the bytes the helper wrote, once it says they all are."""
        head, mac = raw_frame(self.key, self.seq, "E")
        self.sock.sendall(head + mac)
        reply = b""
        while not reply.endswith(b"\n"):
            got = self.sock.recv(600)
            if not got:
                break
            reply += got
        text = reply.decode("utf-8", "replace").strip()
        if not text.startswith("ok "):
            raise _RawFailed(text or "the machine closed the connection")
        return int(text[3:])

    def close(self):
        for c in (self.sock, self.chan):
            if c is not None:
                with contextlib.suppress(Exception):
                    c.close()
        self.sock = self.chan = None


class SshMachine(Machine):
    """A machine over remote access, logged in as root with this computer's key."""

    def __init__(self, host, port=22, timeout=15, expect=None):
        """*expect* (PAD-1434): the identity this must be, ``(kind, base64)``, for a second connection to a
        machine already logged in to; it is never remembered for this port."""
        self.host, self.port, self._timeout, self._expect = host, int(port), timeout, expect
        # PAD-1434 (widen): the connections big files are spread over, the usual connection while a wide one
        # stands in for it, that wide one, and the temporary listener's port
        self._lanes, self._parked, self._wide, self._wide_port = [], None, None, None
        self._widened, self._boot = False, ""
        self._dial()
        if expect is None:                              # a lane (PAD-1434) never reconnects on its own
            _rc, out = self.sh("cat /proc/sys/kernel/random/boot_id 2>/dev/null", check=False)
            self._boot = out.strip()

    def _dial(self):
        import socket
        import paramiko
        from . import pad_ssh_key
        host, timeout, expect = self.host, self._timeout, self._expect
        try:
            # a machine on the home network answers in milliseconds: an address nothing answers at is said soon
            # (PAD-1427: and a remembered machine is then looked for at another one)
            sock = socket.create_connection((host, self.port), timeout=min(timeout, 5))
        except OSError as e:
            raise Unreachable(unreachable_reason(host, self.port, e, min(timeout, 5))) from None
        t = paramiko.Transport(sock)
        try:
            t.start_client(timeout=timeout)
            key = t.get_remote_server_key()
            known = pad_ssh_key.host_key(host, self.port) if expect is None else expect
            mine = self.identity = (key.get_name(), key.get_base64())
            if expect is not None and tuple(expect) != mine:
                raise SendError("%s:%d is not the machine this computer is sending to." % (host, self.port))
            if known is not None and tuple(known) != mine:
                raise SendError("%s answered with a different identity from the last time, so this computer "
                                "won't log in to it. If the machine's card was rewritten from scratch, use "
                                "Forget this machine on the Network tab and try again." % host)
            try:
                t.auth_publickey("root", pad_ssh_key.load_private())
            except paramiko.AuthenticationException:
                raise SendError("%s didn't let this computer in. Write the card onto the machine once with "
                                "Remote access on, from this computer, and Send works after that." % host) from None
            if known is None:
                pad_ssh_key.remember_host(host, self.port, *mine)
            t.set_keepalive(KEEPALIVE)
            self.t = t
            self.sftp = paramiko.SFTPClient.from_transport(t)
        except BaseException:
            t.close()
            raise

    def _alive(self):
        t = getattr(self, "t", None)
        if t is None or not t.is_active():
            return False
        # PAD-1434/1436: a widened Send writes over its lanes too: one of them gone is a dropped connection
        return all(lane is self or lane.t.is_active() for lane in getattr(self, "_lanes", ()))

    def reconnect(self, why=None):
        """PAD-1436: the connection dropped under a Send: dial the machine again (for :data:`RECONNECT_FOR`
        seconds), check it is the same run of it (not restarted), and put the game hold back as it was."""
        self.close()
        self.log("The connection to the machine dropped%s; connecting again..."
                 % ((" (%s)" % str(why).strip().rstrip(":")) if why is not None and str(why).strip() else ""),
                 "warning")
        until = time.monotonic() + RECONNECT_FOR
        n = 0
        while True:
            if self.cancel():
                raise SendError("Send canceled.")
            try:
                self._dial()
                break
            except SendError as e:
                if not isinstance(e, Unreachable):
                    raise                               # a different identity, a refused key: never retried
                last = e
            except Exception as e:                      # noqa: BLE001 - the link half up: tried again
                last = e
            wait = RECONNECT_WAITS[min(n, len(RECONNECT_WAITS) - 1)]
            n += 1
            if time.monotonic() + wait > until:
                raise SendError("The connection to the machine dropped and it didn't answer again for %d minutes "
                                "(%s). Send again once it can be reached: the next Send picks up where this one "
                                "stopped." % (RECONNECT_FOR // 60, str(last).strip() or type(last).__name__)) from None
            for _ in range(int(wait * 10)):
                if self.cancel():
                    raise SendError("Send canceled.")
                time.sleep(0.1)
        _rc, out = self.sh("cat /proc/sys/kernel/random/boot_id 2>/dev/null", check=False)
        if self._boot and out.strip() and out.strip() != self._boot:
            self._paused = False
            raise SendError("The machine restarted while the Send was running. Send again: the next Send picks up "
                            "where this one stopped.")
        if getattr(self, "_paused", False):
            _rc, out = self.sh(self._fns(REHOLD_SCRIPT), check=False, timeout=60)
            if "PAD_SEND_GONE" in out:
                self._paused = False
                raise SendError("The machine restarted while the Send was running. Send again: the next Send "
                                "picks up where this one stopped.")
            if "PAD_SEND_RESUMED" in out:
                # its watchdog gave the game back (nothing had changed yet): held again before going on
                self._beat_stop.set()
                self._paused = False
                self.pause_game()
        if self._widened:
            # PAD-1434: the faster connection went with the old one (close() stopped its listener when it could):
            # started again, or the Send carries on over the usual one
            self._widened = False
            self.widen(self.log)
        self.log("Connected again; the Send carries on.", "info")

    def close(self):
        if getattr(self, "_pieces", None):
            with contextlib.suppress(Exception):
                self.sh("rm -f %s" % self._pieces, check=False, timeout=20)
            self._pieces = None
        lanes, self._lanes = self._lanes, []
        for lane in lanes:
            if lane is not self and lane is not self._wide:
                lane.close()
        if self._wide_port is not None:
            # the temporary listener goes with the Send: over the wide connection, or the usual one if that died
            # (a session is a process of its own, so the one asking outlives the kill)
            for t, sftp in ((self.t, self.sftp), self._parked):
                self.t, self.sftp = t, sftp
                try:
                    self.sh(WIDE_STOP, timeout=20)
                    break
                except Exception:  # noqa: BLE001 - a dead connection; the next Send stops a stale one first
                    continue
            self._wide_port = None
        if self._parked is not None:
            self._wide.close()
            (self.t, self.sftp), self._parked, self._wide = self._parked, None, None
        with contextlib.suppress(Exception):
            self.sftp.close()
        with contextlib.suppress(Exception):
            self.t.close()

    # ---- PAD-1434: a faster connection for the Send
    def _listener_args(self):
        """The arguments the machine's own listener runs with, or ``None`` when it isn't the one PAD set up."""
        _rc, out = self.sh("p=$(cat %s 2>/dev/null) && [ -n \"$p\" ] && tr '\\000' '\\n' < /proc/$p/cmdline"
                           % LISTENER_PIDFILE, timeout=20, check=False)
        args = [a for a in out.split("\n") if a]
        return args if args and posixpath.basename(args[0]) == "dropbear" else None

    def widen(self, log=None):
        """Make this connection a fast one for a Send, and open a second beside it (PAD-1434).

        Dropbear's own receive window (24 KB) holds one connection to ~1.4 MB/s over a machine's Wi-Fi, whatever
        the radio could carry.  A card set up since this starts its listener with ``-W 4194304``; one set up
        before runs the old start script until it is rewritten, so a temporary listener is started beside it:
        the machine's own listener's arguments with another port and the wider window.  It must answer with this
        machine's identity, and is stopped by :meth:`close`.  Then big files go over two connections at once (one
        per core of the machine).  Measured on a Godzilla (Wi-Fi, 72 Mb/s link): 1.4 MB/s before, 3.6 with the
        window, 4.2 with both.  Anything failing leaves the Send on the connection it has.  True when widened."""
        say = log or (lambda *_a: None)
        lanes, port = [], self.port
        try:
            args = self._listener_args()
            if args is None:
                return False
            if _window(args) < WIDE_WINDOW:
                port = self._start_wide(args)
            for _n in range(LANES if port != self.port else LANES - 1):
                try:
                    lanes.append(_connect_lane(self.host, port, self.identity))
                except Exception:  # noqa: BLE001 - one wide connection is still the most of it
                    if not lanes and port != self.port:
                        raise
                    break
        except Exception as e:  # noqa: BLE001 - never stops a Send: the usual connection carries it
            for lane in lanes:
                lane.close()
            if self._wide_port is not None:
                with contextlib.suppress(Exception):
                    self.sh(WIDE_STOP, timeout=20)
                self._wide_port = None
            say("A faster connection didn't start (%s); sending over the usual one."
                % (str(e)[:120] or type(e).__name__), "info")
            return False
        if port != self.port:
            # the wide connection does all of it; the usual one waits to stop the temporary listener if need be
            self._parked = (self.t, self.sftp)
            self.t, self.sftp = lanes[0].t, lanes[0].sftp
            self._wide = lanes[0]
            self._lanes = lanes if len(lanes) > 1 else []
        elif lanes:
            self._lanes = [self] + lanes
        if port != self.port or self._lanes:
            say("Sending over %s%s." % ("two connections at once" if self._lanes else "a faster connection",
                                        " with a wider window" if port != self.port else ""), "info")
        self._widened = True
        return True

    def _start_wide(self, args):
        keep, skip = [args[0]], False
        for a in args[1:]:
            if skip:
                skip = False
                continue
            if a in ("-p", "-P", "-W"):
                skip = True
                continue
            if a[:2] in ("-p", "-P", "-W") or a in ("-F", "-E"):
                continue  # an attached value, or the foreground (a temporary listener must let the step return)
            keep.append(a)
        self.sh(WIDE_STOP, timeout=20)
        last = ""
        for port in WIDE_PORTS:
            if port == self.port:
                continue
            cmd = " ".join(_q(a) for a in keep + ["-p", str(port), "-P", WIDE_PIDFILE, "-W", str(WIDE_WINDOW)])
            rc, out = self.sh(cmd + " 2>&1", timeout=20, check=False)
            if rc == 0:
                self._wide_port = port
                return port
            last = out.strip()[-120:]
        raise SendError(last or "no free port")

    # ---- PAD-1465: big writes over plain TCP into the machine's helper
    def _raw_ready(self):
        if getattr(self, "_raw_off", False) or os.environ.get("PAD_SEND_RAW", "1") == "0":
            return False
        if not _home_network(self.host):
            return False  # signed but not secret: never over the internet (a forwarded port, a tunnel)
        try:
            return self.pieces_ready()
        except Exception:  # noqa: BLE001 - no helper: SSH carries it, as before
            return False

    def _raw_send(self, path, pieces, progress=None):
        """``(offset, bytes)`` pieces of one file over :data:`RAW_LANES` raw connections at once, cut into signed
        frames.  Raises :class:`_RawFailed` when they couldn't carry it (nothing unsigned was written)."""
        import queue
        lanes, errors = [], []
        try:
            for _n in range(RAW_LANES):
                try:
                    lanes.append(_RawLane(self))
                except Exception:  # noqa: BLE001 - one lane still carries it
                    if not lanes:
                        raise
                    break
        except Exception as e:  # noqa: BLE001
            for lane in lanes:
                lane.close()
            raise _RawFailed(str(e)[:160] or type(e).__name__) from e
        qs = [queue.Queue(maxsize=4) for _ in lanes]
        done = [0] * len(lanes)

        def work(i, lane, q):
            try:
                while True:
                    item = q.get()
                    if item is None:
                        break
                    off, data = item
                    mv = memoryview(data)
                    for at in range(0, len(data), RAW_FRAME):
                        lane.write(path, off + at, mv[at:at + RAW_FRAME])
                    done[i] += len(data)
                lane.finish()
            except BaseException as e:  # noqa: BLE001 - raised on the Send's own thread
                errors.append(e)
                while q.get() is not None:  # keep taking pieces, so the dealer never waits on a dead lane
                    pass

        threads = [threading.Thread(target=work, args=(i, lane, q), daemon=True, name="pad-send-raw-%d" % i)
                   for i, (lane, q) in enumerate(zip(lanes, qs))]
        for th in threads:
            th.start()
        try:
            for n, piece in enumerate(pieces):
                if errors:
                    break
                qs[n % len(qs)].put(piece)
                if progress is not None:
                    progress(sum(done))
        finally:
            for q in qs:
                q.put(None)
            for th in threads:
                th.join()
            for lane in lanes:
                lane.close()
        if errors:
            e = errors[0]
            raise _RawFailed(str(e)[:160] or type(e).__name__) from e
        if progress is not None:
            progress(sum(done))

    def _raw_try(self, path, pieces, progress=None):
        """True when the raw lanes carried the write; False (and SSH for the rest of the Send) when they couldn't.
        A dropped SSH connection is raised as it is, so the step is done again once connected again."""
        try:
            self._raw_send(path, pieces, progress)
            if not getattr(self, "_raw_said", False):
                self._raw_said = True
                self.log("Sending the big files over a direct connection.", "info")
            return True
        except _RawFailed as e:
            if not self._alive():
                raise (e.__cause__ or e) from None
            self._raw_off = True
            self.log("The direct connection didn't work (%s); sending over the usual one." % e, "info")
            return False

    def _put(self, path, fileobj, size, callback=None):
        """A whole file: over the raw lanes when it is big (PAD-1465), else over every SSH lane at once when it is
        big enough to gain (PAD-1434)."""
        again = getattr(fileobj, "rewind", None) or (lambda: fileobj.seek(0))
        if size >= RAW_MIN and (hasattr(fileobj, "rewind") or hasattr(fileobj, "seek")) and self._raw_ready():
            with self.sftp.open(path, "wb"):
                pass
            if self._raw_try(path, _pieces(fileobj, size),
                             None if callback is None else (lambda done: callback(done, size))):
                got = self.sftp.stat(path).st_size
                if got != size:
                    raise SendError("%s arrived %d bytes long, not %d; send again." % (path, got, size))
                return
            again()
        if len(self._lanes) > 1 and size >= SPREAD_MIN:
            self._spread(path, _pieces(fileobj, size), create=True,
                         progress=None if callback is None else (lambda done: callback(done, size)))
            got = self.sftp.stat(path).st_size
            if got != size:
                raise SendError("%s arrived %d bytes long, not %d; send again." % (path, got, size))
        else:
            self.sftp.putfo(fileobj, path, file_size=size, callback=callback, confirm=True)

    def _spread(self, path, pieces, create=False, progress=None):
        """``(offset, bytes)`` pieces of one file, dealt in turn to each lane's connection, all writing at once
        (pipelined, PAD-1433).  A write the machine refuses raises once every lane has stopped."""
        import queue
        if create:
            with self.sftp.open(path, "wb"):
                pass
        lanes = [lane.sftp for lane in self._lanes]
        qs = [queue.Queue(maxsize=3) for _ in lanes]
        done, errors = [0] * len(lanes), []

        def work(i, sftp, q):
            f = None
            try:
                f = sftp.open(path, "r+b")
                f.set_pipelined(True)
                while True:
                    item = q.get()
                    if item is None:
                        break
                    f.seek(item[0])
                    f.write(item[1])
                    done[i] += len(item[1])
                f.close()
                f = None
            except BaseException as e:  # noqa: BLE001 - raised on the Send's own thread
                errors.append(e)
                while q.get() is not None:  # keep taking pieces, so the dealer never waits on a dead lane
                    pass
            finally:
                if f is not None:
                    with contextlib.suppress(Exception):
                        f.close()

        threads = [threading.Thread(target=work, args=(i, s, q), daemon=True, name="pad-send-lane-%d" % i)
                   for i, (s, q) in enumerate(zip(lanes, qs))]
        for th in threads:
            th.start()
        try:
            for n, piece in enumerate(pieces):
                if errors:
                    break
                qs[n % len(qs)].put(piece)
                if progress is not None:
                    progress(sum(done))
        finally:
            for q in qs:
                q.put(None)
            for th in threads:
                th.join()
        if errors:
            e = errors[0]
            if not isinstance(e, SendError) and not self._alive():
                raise e  # PAD-1436: a dropped connection: the step is done again once connected again
            raise e if isinstance(e, SendError) else SendError(
                "The machine stopped taking %s (%s); send again." % (path, str(e)[:120] or type(e).__name__))
        if progress is not None:
            progress(sum(done))

    def sh(self, script, stdin=b"", timeout=600, check=True):
        # the server gives a session a short PATH (/usr/bin:/bin): the card's own tools are in sbin too
        full = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\nexport PATH\n" + script
        if len(full) > SCRIPT_INLINE_MAX:
            # dropbear drops the connection on a command line past ~9000 bytes (MAX_CMD_LEN): a long one (a
            # hundred files' names) goes as a script file in the machine's /run tmpfs
            self._n = getattr(self, "_n", 0) + 1
            name = "/run/pad-send-%d-%d.sh" % (os.getpid(), self._n)
            with self.sftp.open(name, "wb") as f:
                f.write(full.encode("utf-8", "surrogateescape"))
            cmd = "/bin/sh %s; r=$?; rm -f %s; exit $r" % (name, name)
        else:
            cmd = "/bin/sh -c " + _q(full)
        t = self.t
        chan = t.open_session()
        chan.settimeout(timeout)
        chan.exec_command(cmd)
        if stdin:
            chan.sendall(stdin)
        chan.shutdown_write()
        out, err = io.BytesIO(), io.BytesIO()
        until = time.monotonic() + timeout
        while True:
            got = False
            if chan.recv_ready():
                out.write(chan.recv(1 << 16))
                got = True
            if chan.recv_stderr_ready():
                err.write(chan.recv_stderr(1 << 16))
                got = True
            if not got:
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
                if not t.is_active():
                    # PAD-1436: the connection dropped under the command: said now, not at its timeout (hours for
                    # a big file's hashes), so the Send connects again and does the step again
                    raise EOFError("Server connection dropped")
                if time.monotonic() > until:
                    chan.close()
                    raise SendError("The machine stopped answering; check it and Send again.")
                time.sleep(0.005)
        rc = chan.recv_exit_status()
        chan.close()
        if rc == -1:
            # PAD-1436: no exit status: the session went with the connection (paramiko closes the channel as if
            # the command ended).  Said as the dropped connection it is - never as a step the machine refused, nor
            # as a half answer - once the connection's end is seen (a moment after the channel's)
            for _ in range(30):
                if not t.is_active():
                    raise EOFError("Server connection dropped")
                time.sleep(0.1)
        text = out.getvalue().decode("utf-8", "replace")
        if check and rc != 0:
            raise SendError("The machine refused a step (%s): %s" % (
                script.strip().splitlines()[0][:60], (err.getvalue().decode("utf-8", "replace").strip()
                                                       or text.strip())[:300]))
        return rc, text

    def state(self, paths):
        paths = list(paths)
        if not paths:
            return {}
        _rc, out = self.sh(STATE_SCRIPT, stdin=("\n".join(paths) + "\n").encode("utf-8", "surrogateescape"))
        lines = out.splitlines()
        if len(lines) != len(paths):
            raise SendError("The machine's answer about its files didn't add up; try again.")
        res = {}
        for p, line in zip(paths, lines):
            tag, _, rest = line.partition(" ")
            res[p] = {"F": ("file", rest), "L": ("link", rest), "D": ("dir",), "O": ("other",)}.get(tag)
        return res

    def sizes(self, root):
        out, todo = {}, [root]
        while todo:
            d = todo.pop()
            try:
                items = self.sftp.listdir_attr(d)
            except OSError:
                continue
            for a in items:
                p = posixpath.join(d, a.filename)
                if stat.S_ISDIR(a.st_mode):
                    todo.append(p)
                elif stat.S_ISREG(a.st_mode):
                    out[p] = a.st_size
        return out

    def read_ranges(self, path, ranges):
        with self.sftp.open(path, "rb") as f:
            return [bytes(b) for b in f.readv([(off, n) for off, n in ranges])]

    def free(self, mount):
        _rc, out = self.sh("df -k %s | tail -n 1" % _q(mount))
        toks = out.split()
        try:
            return int(toks[-3]) * 1024
        except (IndexError, ValueError):
            raise SendError("Couldn't read how much room the machine has on %s." % mount) from None

    def remount(self, mount, rw):
        if rw:
            self.sh("mount -o remount,rw %s" % _q(mount))
            return True
        rc, _ = self.sh("i=0; while [ $i -lt 15 ]; do mount -o remount,ro %s && exit 0; sleep 1; i=$((i+1)); "
                        "done; exit 1" % _q(mount), check=False)
        return rc == 0

    def mkdir(self, path, mode, uid, gid):
        self.sh("mkdir -p %s && chown %d:%d %s && chmod %o %s" % (_q(path), uid, gid, _q(path), mode, _q(path)))

    def upload(self, path, fileobj, size, mode, uid, gid, callback=None):
        self._put(path, fileobj, size, callback)
        self.sftp.chown(path, uid, gid)
        self.sftp.chmod(path, mode)

    def commit(self, renames, links, deletes):
        lines = ["set -e"]
        for tmp, final in renames:
            # PAD-1436: done again after a dropped connection: a copy already renamed into place is not missed
            lines.append("{ [ ! -e %s ] && [ -e %s ]; } || mv -f %s %s" % (_q(tmp), _q(final), _q(tmp), _q(final)))
        for path, target, uid, gid in links:
            tmp = posixpath.join(posixpath.dirname(path), "." + posixpath.basename(path) + TMP_TAG)
            # mv -T where it exists: a plain mv onto a link to a folder would move the new link INTO it
            lines.append("rm -f %s; ln -s %s %s; chown -h %d:%d %s 2>/dev/null || true; "
                         "mv -fT %s %s 2>/dev/null || { rm -f %s; mv -f %s %s; }"
                         % (_q(tmp), _q(target), _q(tmp), uid, gid, _q(tmp), _q(tmp), _q(path), _q(path),
                            _q(tmp), _q(path)))
        for path, is_dir in deletes:
            lines.append(("rmdir %s 2>/dev/null || true" if is_dir else "rm -f %s") % _q(path))
        if len(lines) > 1:
            self.sh("\n".join(lines))

    def hardlink(self, pairs):
        pairs = list(pairs)
        for i in range(0, len(pairs), 100):
            lines = ["set -e"]
            for src, path in pairs[i:i + 100]:
                tmp = posixpath.join(posixpath.dirname(path), "." + posixpath.basename(path) + TMP_TAG)
                # beside the name and renamed over it: the name is always the old file or the new one.  Done again
                # after a dropped connection it makes the same link.  The last rm: renaming one name of a file
                # over another name of that same file does nothing and leaves both
                lines.append("rm -f %s; ln %s %s; mv -f %s %s; rm -f %s"
                             % (_q(tmp), _q(src), _q(tmp), _q(tmp), _q(path), _q(tmp)))
            self.sh("\n".join(lines), timeout=600)

    def write_ranges(self, path, ranges):
        big = sum(len(d) for _o, d in ranges)
        if big >= RAW_MIN and self._raw_ready() and self._raw_try(path, ranges):
            return
        if len(self._lanes) > 1 and big >= SPREAD_MIN:
            self._spread(path, ranges)
            return
        with self.sftp.open(path, "r+b") as f:
            # PAD-1433: pipelined, as putfo is: each 32 KB packet no longer waits for the last one's answer (+25%
            # measured over a machine's Wi-Fi).  A write the machine refuses still raises, at the close
            f.set_pipelined(True)
            for off, data in ranges:
                f.seek(off)
                f.write(data)
            f.flush()

    def remove(self, paths):
        if paths:
            self.sh("rm -f " + " ".join(_q(p) for p in paths), check=False)

    def sync(self):
        self.sh("sync")

    def restart_game(self):
        _rc, out = self.sh(RESTART_SCRIPT, timeout=120)
        return out.strip().splitlines()[-1] if out.strip() else ""

    def read_ledger(self):
        try:
            with self.sftp.open(LEDGER, "rb") as f:
                data = json.loads(f.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def write_ledger(self, data):
        self.sh("mkdir -p %s" % _q(posixpath.dirname(LEDGER)))
        tmp = LEDGER + ".tmp"
        with self.sftp.open(tmp, "wb") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))
        self.sh("mv -f %s %s && sync" % (_q(tmp), _q(LEDGER)))

    def describe(self):
        _rc, out = self.sh(DESCRIBE_SCRIPT, check=False)
        return out


    # ---- the full Send's needs
    def layout(self):
        """``{partition number: (start sector, sectors)}`` of the machine's own card (mmcblk0)."""
        _rc, out = self.sh("for d in /sys/block/mmcblk0/mmcblk0p*; do [ -e \"$d/start\" ] && "
                           "echo \"${d##*mmcblk0p} $(cat $d/start) $(cat $d/size)\"; done", check=False)
        res = {}
        for line in out.splitlines():
            try:
                n, a, b = line.split()
                res[int(n)] = (int(a), int(b))
            except ValueError:
                continue
        if not res:
            raise SendError("Couldn't read the machine's card layout.")
        return res

    def mounts(self):
        _rc, out = self.sh("cat /proc/mounts")
        return [tuple(line.split()[:2]) for line in out.splitlines() if len(line.split()) >= 2]

    def walk(self, root, skip=()):
        """``{path: (kind, size, mtime, mode, uid, gid, link target)}`` under *root*, not crossing into *skip*."""
        out, todo = {}, [root]
        skip = set(skip)
        while todo:
            d = todo.pop()
            try:
                items = self.sftp.listdir_attr(d)
            except OSError:
                continue
            for a in items:
                if a.filename in (".", "..") or (d == root and a.filename == "lost+found"):
                    continue
                p = posixpath.join(d, a.filename)
                m = a.st_mode or 0
                kind = ("dir" if stat.S_ISDIR(m) else "file" if stat.S_ISREG(m)
                        else "symlink" if stat.S_ISLNK(m) else "other")
                target = self.sftp.readlink(p) if kind == "symlink" else None
                out[p] = (kind, a.st_size, a.st_mtime, stat.S_IMODE(m), a.st_uid, a.st_gid, target)
                if kind == "dir" and p not in skip:
                    todo.append(p)
        return out

    def mount_part(self, num, path):
        # read-only: compared first; made writable only when the Send changes it (PAD-1427)
        # PAD-1436: done again after a dropped connection, so a partition it already mounted is left as it is
        self.sh("mkdir -p %s && { awk -v p=%s '$2 == p {f = 1} END {exit !f}' /proc/mounts || "
                "mount -t ext4 -o ro /dev/mmcblk0p%d %s; }" % (_q(path), _q(path), int(num), _q(path)))

    def umount_part(self, path):
        self.sh("sync; umount %s && rmdir %s" % (_q(path), _q(path)), check=False)

    def raw_sha1(self, num):
        _rc, out = self.sh("sha1sum /dev/mmcblk0p%d | cut -d' ' -f1" % int(num))
        return out.strip()

    def raw_write(self, num, fileobj, size, sha1):
        """The whole partition, from a copy on /data checked first: a cut-off upload never reaches the card."""
        tmp = posixpath.join(posixpath.dirname(LEDGER), "p%d.img" % int(num))
        self.sh("mkdir -p %s" % _q(posixpath.dirname(tmp)))
        try:
            self._put(tmp, fileobj, size)
            if self.state([tmp]).get(tmp) != ("file", sha1):
                raise SendError("The boot partition didn't arrive whole on the machine; nothing was written.")
            dev = "/dev/mmcblk0p%d" % int(num)
            self.sh("dd if=%s of=%s bs=1048576 2>/dev/null && sync" % (_q(tmp), dev))
            if self.raw_sha1(num) != sha1:
                raise SendError("The boot partition didn't read back as written. Don't switch the machine off: "
                                "send again.")
        finally:
            self.sh("rm -f %s" % _q(tmp), check=False)

    def set_mtime(self, path, mtime):
        with contextlib.suppress(OSError):
            self.sftp.utime(path, (int(mtime), int(mtime)))

    def block_hashes(self, path):
        script = BLOCKS_SCRIPT.replace("@F@", _q(path)).replace("@BS@", str(DELTA_BLOCK))
        _rc, out = self.sh(script, timeout=7200)
        lines = out.split("\n")
        try:
            size = int(lines[0].strip())
        except (IndexError, ValueError):
            raise SendError("Couldn't read %s on the machine." % path) from None
        return size, [ln.split()[0] for ln in lines[1:] if ln.strip()]

    def file_sha1s(self, paths):
        """One sha1sum for many files (a command per file costs more than the hashing on the card)."""
        out = {}
        paths = list(paths)
        for i in range(0, len(paths), 200):
            chunk = paths[i:i + 200]
            _rc, text = self.sh("sha1sum " + " ".join(_q(p) for p in chunk) + " 2>/dev/null; true", check=False,
                                timeout=7200)
            for line in text.splitlines():
                esc = line.startswith("\\")     # a name with a backslash or newline comes back escaped
                if esc:
                    line = line[1:]
                digest, _, p = line.partition("  ")
                if esc:
                    p = p.replace("\\n", "\n").replace("\\\\", "\\")
                out[p] = ("file", digest)
        return out

    def file_ids(self, paths):
        paths = list(paths)
        now, out, asked = None, {}, set(paths)
        if not paths:
            return None
        for i in range(0, len(paths), 200):
            chunk = paths[i:i + 200]
            _rc, text = self.sh(IDS_SCRIPT.replace("@PATHS@", " ".join(_q(p) for p in chunk)), check=False,
                                timeout=600)
            lines = text.splitlines()
            try:
                clock = int(lines[0])
            except (IndexError, ValueError):
                return None
            now = clock if now is None else min(now, clock)
            for line in lines[1:]:
                parts = line.split(" ", 5)
                if len(parts) != 6 or parts[5] not in asked:
                    continue
                try:
                    mode, size, mtime, ino, ctime = (int(parts[0], 16),) + tuple(int(x) for x in parts[1:5])
                except ValueError:
                    continue
                if stat.S_ISREG(mode):
                    out[parts[5]] = (size, mtime, ino, ctime)
        if not out:
            # a card whose busybox has no stat says nothing about any file: told apart from files that aren't there
            _rc, probe = self.sh("stat -c %s / 2>/dev/null", check=False)
            if not probe.strip():
                return None
        return now, out

    def boot_info(self):
        _rc, text = self.sh(BOOT_SCRIPT, check=False)
        lines = text.splitlines()
        try:
            boot, btime, now = lines[0].strip(), int(lines[1]), int(lines[2])
        except (IndexError, ValueError):
            return None
        mounts = {}
        for line in lines[3:]:
            parts = line.split()
            if len(parts) == 3:
                mounts[parts[0]] = parts[1] + " " + parts[2]    # the last of a mount point's lines is the one seen
        if not boot or set(mounts) != {ROOT, GAMES}:
            return None
        return {"boot": boot, "btime": btime, "now": now, "mounts": mounts}

    def read_hash_cache(self):
        try:
            with self.sftp.open(HASH_CACHE, "rb") as f:
                data = json.loads(f.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def write_hash_cache(self, data):
        self.sh("mkdir -p %s" % _q(posixpath.dirname(HASH_CACHE)))
        tmp = HASH_CACHE + ".tmp"
        with self.sftp.open(tmp, "wb") as f:
            f.write(json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        self.sh("mv -f %s %s && sync" % (_q(tmp), _q(HASH_CACHE)))

    def truncate(self, path, size):
        self.sftp.truncate(path, size)

    def set_attrs(self, path, mode, uid, gid):
        self.sftp.chown(path, uid, gid)
        self.sftp.chmod(path, mode)

    def copy(self, src, dst):
        self.sh("rm -f %s && cp -p %s %s" % (_q(dst), _q(src), _q(dst)), timeout=7200)

    def pieces_ready(self):
        if getattr(self, "_pieces", None) is None:
            self._pieces = self._put_pieces_helper() or ""
        return bool(self._pieces)

    def _put_pieces_helper(self):
        """PAD-1435: the helper for this machine's processor, into its /run tmpfs for this Send (gone at close or
        the next boot); None when there isn't one for it or it doesn't run there."""
        try:
            _rc, arch = self.sh("uname -m", check=False, timeout=30)
            sub = PIECES_ARCH.get(arch.strip())
            if sub is None:
                return None
            data = (PIECES_DIR / sub / "padpieces").read_bytes()
            if hashlib.sha256(data).hexdigest() != PIECES_SHA256[sub]:
                return None
            for d in ("/run", "/tmp"):
                name = "%s/pad-pieces-%d" % (d, os.getpid())
                try:
                    with self.sftp.open(name, "wb") as f:
                        f.write(data)
                    self.sftp.chmod(name, 0o755)
                except OSError:
                    continue
                rc, out = self.sh("%s version" % name, check=False, timeout=30)
                if rc == 0 and out.strip() == PIECES_VERSION:
                    return name
                self.sh("rm -f %s" % name, check=False, timeout=30)
        except (OSError, SendError):
            pass
        return None

    def piece_hashes(self, paths):
        from .send_pieces import PIECE
        stdin = "".join(p + "\n" for p in paths).encode("utf-8", "surrogateescape")
        _rc, out = self.sh("%s hash %d" % (self._pieces, PIECE), stdin=stdin, timeout=7200)
        res, cur = {}, None
        for ln in out.split("\n"):
            if ln.startswith("= "):
                size, _, path = ln[2:].partition(" ")
                cur = res[path] = (int(size), [])
            elif ln.startswith("! "):
                res.pop(ln[2:], None)
                cur = None
            elif len(ln) == 40 and cur is not None:
                cur[1].append(ln)
        return res

    def copy_pieces(self, copies):
        stdin = "".join("%s\t%d\t%s\t%d\t%d\n" % c for c in copies).encode("utf-8", "surrogateescape")
        _rc, out = self.sh("%s copy" % self._pieces, stdin=stdin, timeout=7200)
        last = (out.strip().splitlines() or [""])[-1]
        if not last.startswith("ok "):
            raise SendError("The machine didn't finish copying the pieces it already has; send again.")
        return int(last[3:])

    def in_use(self):
        _rc, out = self.sh(IN_USE_SCRIPT, check=False, timeout=120)
        return {ln[:-len(" (deleted)")] if ln.endswith(" (deleted)") else ln
                for ln in out.splitlines() if ln.startswith("/")}

    def stop_game(self):
        """For an update: nothing starts the game again on half the files.  PAD-1427: its loop is held, not
        killed, so the game can come back if the Send stops before anything changed, and the machine's screen
        says what is happening."""
        self.pause_game()

    def reboot(self):
        self._screen_finish(screen_text("UPDATE DONE", "RESTARTING", "THE MACHINE"))
        self.sh("sync; (sleep 2; reboot) </dev/null >/dev/null 2>&1 &", check=False, timeout=30)

    # ---- PAD-1427: the machine's screen while a Send changes it
    def _fns(self, script):
        return script.replace("@W@", SCREEN_DIR)

    def game_held(self):
        return bool(getattr(self, "_paused", False))

    def pause_game(self):
        if getattr(self, "_paused", False):
            return
        self.sh("mkdir -p %s" % SCREEN_DIR, check=False)
        watch = (SCREEN_WATCH.replace("@LOST@", str(SCREEN_LOST))
                 .replace("@LOST_SAFE@", _q(screen_text("CONNECTION LOST", "NOTHING CHANGED", "RESTARTING GAME")))
                 .replace("@LOST_CHANGED@", _q(screen_text("CONNECTION LOST", "SEND AGAIN", "FROM PAD"))))
        for name, text in (("fns", SCREEN_FNS), ("watch", watch)):
            with self.sftp.open(SCREEN_DIR + "/" + name, "wb") as f:
                f.write(self._fns(text).encode("utf-8"))
        self._screen = {"pct": 0, "what": "STARTING", "tick": 0, "last": 0.0}
        self.sh(self._fns(PAUSE_SCRIPT).replace("@TEXT@", _q(self._screen_line())), check=False, timeout=60)
        self._paused = True
        self._beat_stop = threading.Event()
        self._beat = threading.Thread(target=self._heartbeat, daemon=True, name="pad-send-screen")
        self._beat.start()

    def _screen_line(self):
        st = self._screen
        marks = ("*   ", " *  ", "  * ", "   *")
        # the comparison counts per partition (a fast one reaches 99% and a slow one then says nothing for
        # minutes): no percentage while checking or starting, the moving mark says it is alive
        status = {"STARTING": "GETTING READY", "CHECKING": "CHECKING FILES"}.get(
            st["what"], "%s %d%%" % (st["what"], st["pct"]))
        return screen_text("PAD IS UPDATING", status, "LINK OK " + marks[st["tick"] % 4], "KEEP POWER ON")

    def _heartbeat(self):
        """Every few seconds: tell the machine PAD is still there, and redraw its screen (the moving mark)."""
        while not self._beat_stop.wait(2.5):
            self._screen["tick"] += 1
            with contextlib.suppress(Exception):
                self.sh(self._fns(". @W@/fns\ndate +%s > $W/alive\n[ -f $W/done ] || pad_say ")
                        + _q(self._screen_line()), check=False, timeout=20)

    def _screen_finish(self, text):
        """The Send's last word on the machine's screen; the heartbeat and the watchdog stop."""
        if not getattr(self, "_paused", False):
            return
        self._beat_stop.set()
        self._beat.join(25)
        self.sh(self._fns(". @W@/fns\ntouch $W/done\npad_say ") + _q(text), check=False, timeout=30)

    def screen_progress(self, done, total, what=""):
        if not getattr(self, "_paused", False):
            return
        self._screen["pct"] = max(0, min(100, int(done * 100 / total))) if total else 0
        self._screen["what"] = {"Uploading": "RECEIVING", "Updating": "UPDATING", "Comparing": "CHECKING",
                                "Finishing": "FINISHING"}.get((what or "").split(" ")[0], "WORKING")

    def screen_changing(self):
        if getattr(self, "_paused", False):
            self.sh("echo changing > %s/phase" % SCREEN_DIR, check=False)

    def resume_game(self, text=None):
        if not getattr(self, "_paused", False):
            return self.restart_game()
        self._screen_finish(text or screen_text("UPDATE DONE", "RESTARTING GAME"))
        time.sleep(2)
        _rc, out = self.sh(self._fns(". @W@/fns\npad_resume"), check=False, timeout=90)
        self._paused = False
        return out.strip().splitlines()[-1] if out.strip() else "PAD_SEND_NOT_BACK"

    def screen_stopped(self, changed):
        if not getattr(self, "_paused", False):
            return
        if changed:
            self._screen_finish(screen_text("SEND STOPPED", "SEND AGAIN", "FROM PAD"))
            self._paused = False
            return
        self._screen_finish(screen_text("SEND STOPPED", "NOTHING CHANGED", "RESTARTING GAME"))
        time.sleep(2)
        self.sh(self._fns(". @W@/fns\npad_resume"), check=False, timeout=90)
        self._paused = False


# PAD-1436: the steps a dropped connection is reconnected under and done again (each comes to the same end twice)
for _name in ("state", "sizes", "read_ranges", "free", "remount", "mkdir", "upload", "commit", "write_ranges", "remove",
              "sync", "read_ledger", "write_ledger", "layout", "mounts", "walk", "mount_part", "umount_part",
              "raw_sha1", "raw_write", "set_mtime", "block_hashes", "file_sha1s", "truncate", "set_attrs", "copy",
              "in_use", "describe", "file_ids", "boot_info", "read_hash_cache", "write_hash_cache",
              # PAD-1435: a batch of copies is cut where a copy would overwrite a piece the batch read (piece_puts),
              # so done again it reads what it read the first time
              "piece_hashes", "copy_pieces"):
    setattr(SshMachine, _name, _again(getattr(SshMachine, _name)))
del _name

def connect(address, log=None):
    """An :class:`SshMachine` for ``host`` or ``host:port``.

    PAD-1427: when nothing answers there and it is the machine this computer remembers (a scan found it, so its
    identity is known), the home network is looked over for that same machine at another address (the router
    hands out addresses afresh), and it is remembered there."""
    host, port = parse_address(address)
    try:
        return SshMachine(host, port)
    except Unreachable:
        from . import machine_scan, pad_ssh_key
        rec = next((m for m in pad_ssh_key.machines() if m["host_key"] and _same_address(m["address"], host, port)),
                   None)
        if rec is None:
            raise
        if log is not None:
            log("The machine didn't answer at %s: looking for it on your network..." % host, "info")
        moved = machine_scan.find_moved(rec["host_key"], port)
        if not moved:
            raise
        pad_ssh_key.remember_host(moved, port, *rec["host_key"])
        new = machine_scan.address_of({"address": moved}, port)
        # the same machine at its new address: still the one used if it was
        pad_ssh_key.remember_machine(new, rec["host_key"], rec["game"], make_current=False)
        if log is not None:
            log("Found it at %s." % moved, "info")
        return SshMachine(moved, port)


def _same_address(address, host, port):
    try:
        return parse_address(address) == (host, port)
    except SendError:
        return False


def parse_address(address):
    a = (address or "").strip()
    if not a:
        raise SendError("Enter the machine's network address (Network tab) first.")
    host, port = a, 22
    if a.count(":") == 1:
        host, _, p = a.partition(":")
        try:
            port = int(p)
        except ValueError:
            raise SendError("%s is not a network address." % a) from None
    if a.startswith("[") and "]" in a:
        host, _, rest = a[1:].partition("]")
        if rest.startswith(":"):
            port = int(rest[1:])
    return host.strip(), port


# ===================================================================== the Send
def _human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.1f %s" % (n, unit))
        n /= 1024.0


class HashCache:
    """PAD-1444 (David: "Network ssh compare is too slow. Can we cache this somehow?"): the sha1s the machine worked
    out on earlier Sends, kept on the machine (:data:`HASH_CACHE`), so a compare reads only the files that changed
    since and not the gigabytes that didn't.

    A file's sha1 is taken from the record only while the file is provably the one that was hashed:

    * its size, mtime, inode and ctime are what they were.  ctime is the kernel's: any write, rename, chmod or
      touch moves it and nothing can set it back, so whatever changes a file through the running machine (a Send,
      an older PAD, Stern's updater, a shell) takes it out of the record.  One changed in the second it was looked
      at isn't recorded (ctime counts whole seconds);
    * the record is of THIS boot of the machine, or of the boot before when PAD restarted it and it came up within
      :data:`HASH_CACHE_REBOOT` seconds.  A card dumped, patched on a computer and written back keeps every inode's
      size, times and number (PAD's own builds patch audio in place like that), so a record that crossed a power
      cycle could vouch for bytes that are no longer there: it is set aside;
    * / and /games are the same partitions (and folders of them) they were: a multi-boot card's other image isn't
      taken for the one hashed.

    Only files of / and /games are recorded: a multi-boot card's other images, which a Send mounts itself, may
    have been written whole as a partition.  Anything wrong with the record (a card without ``stat``, a record
    that doesn't read) just leaves it off: the compare hashes everything, as it always did."""

    def __init__(self, machine, log=None):
        self.machine = machine
        self.files = {}
        self.on = self.dirty = False
        self.hits = self.hit_bytes = 0
        self.info = None
        try:
            info = machine.boot_info()
            if info is None:
                return
            data = machine.read_hash_cache()
        except (SendError, OSError, ValueError):
            return
        self.info, self.on = info, True
        if not isinstance(data, dict) or data.get("v") != 1:
            self.dirty = data is not None
            return
        same_boot = data.get("boot") == info["boot"]
        try:
            restarted = (bool(data.get("rebooting"))
                         and 0 <= info["btime"] - int(data.get("written")) <= HASH_CACHE_REBOOT)
        except (TypeError, ValueError):
            restarted = False
        if data.get("mounts") != info["mounts"] or not (same_boot or restarted):
            self.dirty = True                   # set aside: the next save starts it again
            if log:
                log("The machine's record of the files it hashed before is from before it was last switched off "
                    "(or of other partitions); every file is compared again.", "info")
            return
        for path, e in (data.get("files") or {}).items():
            if (isinstance(e, list) and len(e) == 5 and all(isinstance(x, int) for x in e[:4])
                    and isinstance(e[4], str)):
                self.files[path] = e
        self.dirty = not same_boot              # taken over by this boot: said so on the next save

    @staticmethod
    def _recordable(path):
        return _mount_of(path) in (ROOT, GAMES) and not path.startswith(TEMP_MOUNT + "/")

    def _ids(self, paths):
        try:
            return self.machine.file_ids(paths)
        except (SendError, OSError, ValueError):
            return None

    def hashes(self, paths, hasher):
        """*hasher(paths)* (``machine.file_sha1s`` or ``machine.state``), asking the machine only about the files
        not in the record unchanged."""
        paths = list(paths)
        want = [p for p in paths if self._recordable(p)] if self.on else []
        got = self._ids(want) if want else None
        if got is None:
            return hasher(paths)
        now, ids = got
        out, rest = {}, []
        for p in paths:
            key, e = ids.get(p), self.files.get(p)
            if key is not None and e is not None and tuple(e[:4]) == key:
                out[p] = ("file", e[4])
                self.hits += 1
                self.hit_bytes += key[0]
            else:
                rest.append(p)
        if rest:
            res = hasher(rest)
            out.update(res)
            for p in rest:
                self._note(p, ids.get(p), res.get(p), now)
        return out

    def _note(self, path, key, got, now):
        if key is not None and got is not None and got[0] == "file" and key[3] < now:
            self.files[path] = list(key) + [got[1]]
            self.dirty = True
        elif self.files.pop(path, None) is not None:
            self.dirty = True

    def remember(self, digests):
        """``{path: sha1}`` of files a Send just wrote and checked on the machine."""
        digests = {p: d for p, d in digests.items() if self._recordable(p)}
        if not self.on or not digests:
            return
        got = self._ids(list(digests))
        if got is not None and any(k[3] >= got[0] for k in got[1].values()):
            time.sleep(1.2)                     # written this second: recorded once the machine's clock moves on
            got = self._ids(list(digests))
        if got is None:
            for p in digests:
                self.dirty |= self.files.pop(p, None) is not None
            return
        now, ids = got
        for p, d in digests.items():
            self._note(p, ids.get(p), ("file", d), now)

    def save(self, rebooting=False):
        """Write the record back when it changed (or the machine is about to be restarted by PAD)."""
        if not self.on or not (self.dirty or rebooting):
            return
        try:
            info = self.machine.boot_info() or self.info
            self.machine.write_hash_cache({"v": 1, "boot": info["boot"], "written": info["now"],
                                           "rebooting": bool(rebooting), "mounts": info["mounts"],
                                           "files": self.files})
            self.dirty = False
        except (SendError, OSError, ValueError):
            pass

    def said(self, log):
        if log and self.hits:
            log("%d file(s) (%s) the machine had hashed on an earlier Send and that haven't changed since weren't "
                "read again." % (self.hits, _human(self.hit_bytes)), "info")


def send(plan, machine, log=None, progress=None, cancel=None, restart=True):
    """Make the machine's system and game partitions match the build's.  Returns a summary line."""
    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)

    def check():
        if cancel():
            raise SendError("Send canceled.")

    ledger = machine.read_ledger()
    if ledger and ledger.get("card") != plan.card_id:
        log("The machine's record of earlier Sends is for another card (%s); it is set aside."
            % (ledger.get("card") or {}).get("name", "?"), "info")
        ledger = None
    in_ledger = set((ledger or {}).get("paths") or []) | set(((ledger or {}).get("ranges") or {}))
    ops = plan.ops + plan.extra_for(ledger)
    check()

    # 2. the machine runs this card
    touched = {op.path for op in ops}
    built = plan.trees[GAMES][0]
    on_machine = machine.sizes(GAMES)
    wrong = []
    for path, (kind, node, _sig) in built.entries.items():
        if kind != "file" or path in touched or path in in_ledger:
            continue
        have = on_machine.get(path)
        if have != node["size"]:
            wrong.append(path)
    if wrong:
        raise NotThisCard("The machine isn't running the card this image was built from (%s): %d of its game "
                        "files differ, %s. Write the card instead."
                        % (plan.card_id["name"], len(wrong), ", ".join(sorted(wrong)[:3])))
    check()
    cache = HashCache(machine, log)
    state = cache.hashes([op.path for op in ops if op.kind != "patch"], machine.state)
    cache.said(log)
    needed, odd = [], []
    for op in ops:
        if op.kind == "patch":
            have = machine.read_ranges(op.path, [(off, len(b)) for off, b, _s in op.ranges])
            rest = []
            for (off, b, s), h in zip(op.ranges, have):
                if h == b:
                    continue
                if h == s or op.path in in_ledger or (ledger or {}).get("pending"):
                    rest.append((off, b, s))
                else:
                    odd.append("%s at 0x%x" % (op.path, off))
            if rest:
                op.ranges = rest
                needed.append(op)
            continue
        cur = op.cur = state.get(op.path)
        want = {"put": ("file", op.sha1), "link": ("link", op.target), "mkdir": ("dir",), "delete": None}[op.kind]
        if cur == want:
            continue
        if op.kind == "mkdir" and cur is None:
            needed.append(op)
            continue
        if cur == op.stock or op.path in in_ledger or op.from_ledger:
            if (op.kind == "put" and cur not in (None,) and cur[0] != "file") or \
                    (op.kind == "link" and cur not in (None,) and cur[0] == "dir"):
                odd.append(op.path)
                continue
            needed.append(op)
        else:
            odd.append(op.path)
    if odd:
        raise NotThisCard("On the machine, %s %s neither the original's nor what an earlier Send put there, so "
                        "the machine isn't running this card as built. Write the card instead."
                        % (", ".join(odd[:3]) + (" and %d more" % (len(odd) - 3) if len(odd) > 3 else ""),
                           "is" if len(odd) == 1 else "are"))
    cache.save()
    if not needed:
        log("The machine already has every change in this build; nothing to send.", "success")
        if machine.game_held():
            machine.resume_game(screen_text("NOTHING TO", "UPDATE", "RESTARTING GAME"))
        return "The machine already has this build."

    puts = [op for op in needed if op.kind == "put"]
    total = sum(op.size for op in puts) or 1
    # room: a new copy beside each file it replaces, while the game runs.  Without it (David: "space is scarce on
    # the SD card"), the game is stopped and the game files the machine has are changed in place, only the blocks
    # that differ (delta_put): then only growth and new files need room, and the machine restarts at the end.
    # System files always need the room: the session runs on them
    tight = False
    for mount in (ROOT, GAMES):
        mine = [op for op in puts if op.mount == mount]
        want = sum(op.size for op in mine)
        if not want:
            continue
        free = machine.free(mount)
        if free >= want + SPARE:
            continue
        if mount == ROOT:
            # never in place there: the remote access session runs on the system files (delta_replace)
            raise SendError("There isn't room on the machine's system partition for the %s of files this Send "
                            "changes there. Write the card instead." % _human(want))
        has = {op.path: getattr(op, "cur", None) for op in mine}
        grow = sum(op.size for op in mine if not (has[op.path] and has[op.path][0] == "file"))
        if free < grow + SPARE:
            raise SendError("There isn't room on the machine's %s partition for the %s of new files this Send "
                            "puts there. Write the card instead." % ("game" if mount == GAMES else "system",
                                                                    _human(grow)))
        tight = True
    if tight:
        log("Not enough room on the machine for a second copy of the changed files: the game is stopped and they "
            "game files are changed in place, only the parts that differ; the machine restarts at the end.", "info")
    log("Sending %d change(s) to the machine: %d file(s) (%s), %d link(s), %d removal(s), %d in-place patch(es)."
        % (len(needed), len(puts), _human(sum(op.size for op in puts)),
           sum(op.kind == "link" for op in needed), sum(op.kind == "delete" for op in needed),
           sum(op.kind == "patch" for op in needed)), "info")
    check()

    mounts = sorted({op.mount for op in needed})
    temps = []
    rw = []
    temp_ops = []
    reboot_after = False
    changed = False
    # PAD-1427: the game is held for the Send (a game being played ends), and the machine's screen says PAD is
    # updating it, how far along, and that the connection is live
    if restart or tight:
        machine.pause_game()
    progress = _also_on_screen(machine, progress)
    try:
        if tight:
            machine.stop_game()
        for mount in mounts:
            machine.remount(mount, True)
            rw.append(mount)
        rec = plan.record()
        machine.write_ledger(dict(rec, pending=True,
                                  paths=sorted(set(rec["paths"]) | set((ledger or {}).get("paths") or [])),
                                  ranges=dict((ledger or {}).get("ranges") or {}, **rec["ranges"])))
        for op in sorted((o for o in needed if o.kind == "mkdir"), key=lambda o: o.path.count("/")):
            machine.mkdir(op.path, op.mode, op.uid, op.gid)
        sent = 0
        job = None
        if tight:
            # PAD-1435: the game files changed in place are built from 64 KB pieces the machine has anywhere among
            # them (it reads only those, as the 1 MiB delta did), the rest sent
            here = [op for op in puts if op.mount == GAMES and (getattr(op, "cur", None) or ("",))[0] == "file"]
            job = pieces_prepare(machine, plan.trees[GAMES][0], GAMES, here, {op.path for op in here}, progress,
                                 log)
            if job is not None and job.ops:
                if not changed:
                    machine.screen_changing()
                    changed = True
                log("Updating %d game file(s) in place (only the parts that differ)..." % len(job.ops), "info")
                sent = pieces_run(machine, plan.trees[GAMES][0], job, cancel, progress, sent, total, temps)
        for op in puts:
            check()
            cur = getattr(op, "cur", None)
            if job is not None and op.path in job.paths:
                continue
            if tight and op.mount == GAMES and cur and cur[0] == "file":
                if not changed:
                    machine.screen_changing()
                    changed = True
                log("Updating %s in place (only the parts that differ)..." % op.path, "info")
                delta_put(machine, plan.trees[op.mount][0], op, cancel,
                          progress=lambda done, base=sent: progress(base + done, total, "Updating"))
                sent += op.size
                progress(sent, total, "Updating")
                continue
            tmp = posixpath.join(posixpath.dirname(op.path), "." + posixpath.basename(op.path) + TMP_TAG)
            temps.append(tmp)
            temp_ops.append(op)
            log("Uploading %s (%s)..." % (op.path, _human(op.size)), "info")
            base = sent

            def cb(done, _total, base=base):
                progress(base + done, total, "Uploading")
                if cancel():
                    raise SendError("Send canceled.")
            out_t = plan.trees[op.mount][0]
            machine.upload(tmp, _ChunkFile(out_t, op.node), op.size, op.mode, op.uid, op.gid, cb)
            sent += op.size
        if temps:
            got = machine.state(temps)
            bad = [op.path for op, tmp in zip(temp_ops, temps) if got.get(tmp) != ("file", op.sha1)]
            if bad:
                raise SendError("%s didn't arrive whole on the machine (its check failed); nothing was changed. "
                                "Send again." % ", ".join(bad[:3]))
        log("Every file arrived whole; putting them in place.", "info")
        progress(1, 1, "Finishing")
        check()
        links = [(op.path, op.target, op.uid, op.gid) for op in needed if op.kind == "link"]
        deletes = [(op.path, getattr(op, "cur", None) == ("dir",))
                   for op in sorted((o for o in needed if o.kind == "delete"), key=lambda o: -o.path.count("/"))]
        machine.commit([(tmp, op.path) for op, tmp in zip(temp_ops, temps)], links, deletes)
        temps = []
        for op in needed:
            if op.kind != "patch":
                continue
            machine.write_ranges(op.path, [(off, b) for off, b, _s in op.ranges])
            back = machine.read_ranges(op.path, [(off, len(b)) for off, b, _s in op.ranges])
            if back != [b for _off, b, _s in op.ranges]:
                raise SendError("The changes inside %s didn't read back as sent; Send again." % op.path)
        machine.sync()
        machine.write_ledger(dict(rec, pending=False))
        line = ""
        if tight:
            # game_monitor was stopped with the game: the machine starts both again, as at power-on
            log("Restarting the machine on the new files...", "info")
            restart = False
            reboot_after = True
        if not reboot_after and any(boot_only(op.path) for op in needed):
            # PAD-1467: a restarted game does not pick these up - the machine reads them when IT starts
            log("Restarting the machine: this Send changed files it reads only when it starts (its Wi-Fi "
                "start-up or driver, or how it starts the game).", "info")
            restart = False
            reboot_after = True
        # PAD-1444: what went on was checked on the machine: the next compare needn't read it again
        cache.remember({op.path: op.sha1 for op in puts})
        cache.save(rebooting=reboot_after)
        if restart:
            line = machine.resume_game()
            if "RESTARTED" in line:
                log("The game restarted on the new files.", "success")
            elif "NOT_RUNNING" in line:
                log("The game wasn't running; it starts on the new files the next time it does.", "info")
            else:
                log("The game was stopped but hadn't started again after 40 s; switch the machine off and on.",
                    "warning")
    except BaseException:
        if temps:
            with contextlib.suppress(Exception):
                machine.remove(temps)
        with contextlib.suppress(Exception):
            machine.screen_stopped(changed)
        raise
    finally:
        for mount in rw:
            ok = False
            with contextlib.suppress(Exception):
                ok = machine.remount(mount, False)
            if not ok:
                log("The machine's %s partition stays writable until it is switched off and on (something still "
                    "has a replaced file open)." % ("game" if mount == GAMES else "system"), "warning")
    if reboot_after:
        machine.reboot()
    return "Sent %d change(s) (%s) to the machine%s." % (len(needed), _human(sum(op.size for op in puts)),
                                                         "; it is restarting" if reboot_after else "")


#: PAD-1467: files the machine reads only when it starts, so a Send that changed one restarts the machine, not
#: just the game: the Wi-Fi start-up choice and adapter driver (core/wifi_card.py: wpa_supplicant and the kernel
#: module are loaded once, at start-up), and the script that starts the game (its running copy is the old one:
#: PAD's modes, a multi-boot menu and remote buttons are all preloaded from it).  Found on a Godzilla: a Send of
#: remote buttons restarted the game and the game came back without them.
BOOT_ONLY = ("/etc/init.d/game_monitor", "/etc/init.d/padwifi", "/etc/rc5.d/S31padwifi", "/etc/wpa_supplicant/",
             "/usr/local/spike/8812bu.ko", "/usr/local/bin/pad-wifi-band", "/usr/local/bin/pad-buttons.so")


def boot_only(path):
    """Whether *path* on the machine takes effect only when the machine starts (:data:`BOOT_ONLY`)."""
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in BOOT_ONLY)


# ===================================================================== any image: the full Send
#: partitions that are the machine's own (settings, audits, high scores, logs): never synced from an image
OWN_MOUNTS = ("/data", "/dump", "/connectivity")
FAT_TYPES = {0x01, 0x04, 0x06, 0x0b, 0x0c, 0x0e}
EXTENDED_TYPES = {0x05, 0x0f, 0x85}
TEMP_MOUNT = "/run/pad-send"


class Target:
    """A card image as the machine should become it: a tree per partition the machine's files live on, the raw
    bytes of its boot partition, and its partition layout.  Keeps the image open (``close``)."""

    def __init__(self, path, platform, layout, trees, raw, closers, plan=None, card_id=None, info=None):
        self.path, self.platform, self.layout = path, platform, layout
        self.trees = trees            # {machine mount: _Tree}; "/run/pad-send/p7" for an image the machine doesn't mount
        self.parts = {}               # {machine mount: partition number} for those it mounts itself
        self.raw = raw                # {partition number: (offset, size)} written whole (the boot partition)
        self._closers = closers
        self.plan = plan
        self.card_id = card_id
        self.info = info or {}

    def close(self):
        if self.plan is not None:
            self.plan.close()
        for fn in reversed(self._closers):
            with contextlib.suppress(Exception):
                fn()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def raw_chunks(self, num):
        off, size = self.raw[num]
        with open(self.path, "rb") as f:
            f.seek(off)
            left = size
            while left:
                b = f.read(min(left, 1 << 20))
                if not b:
                    raise SendError("The image ends inside its partition %d." % num)
                yield size - left, b
                left -= len(b)

    def raw_sha1(self, num):
        return _sha1_chunks(self.raw_chunks(num))


class _RawFile(io.RawIOBase):
    def __init__(self, chunks):
        # *chunks*: the chunks, or (PAD-1436) what makes them afresh, so a send cut off by a dropped connection
        # starts again from the first
        self._make = chunks if callable(chunks) else None
        self._it, self._buf, self._at = iter(chunks() if callable(chunks) else chunks), b"", 0

    def rewind(self):
        if self._make is None:
            raise SendError("This copy can't be sent again; send again.")
        self._it, self._buf, self._at = iter(self._make()), b"", 0

    def readable(self):
        return True

    def read(self, n=-1):
        if self._at >= len(self._buf):
            nxt = next(self._it, None)
            if nxt is None:
                return b""
            self._buf, self._at = nxt[1], 0
        end = len(self._buf) if n is None or n < 0 else min(len(self._buf), self._at + n)
        out = self._buf[self._at:end]
        self._at = end
        return out


#: the delta (David, 2026-11-17: "space is scarce on the SD card"): a file the machine already has is compared a
#: block at a time and only the blocks that differ are written, in place - no second copy needs room, and only the
#: changes cross the network
DELTA_BLOCK = 1 << 20
#: PAD-1435: the machine's piece helper (resources/pieces/build.sh prints these), by `uname -m`
PIECES_DIR = Path(__file__).resolve().parents[1] / "resources" / "pieces"
PIECES_VERSION = "padpieces 2"
PIECES_ARCH = {"armv7l": "armv7", "armv7": "armv7", "aarch64": "aarch64", "arm64": "aarch64"}
PIECES_SHA256 = {"armv7": "fa0a33b8966a31b35cf29636996743f449e9b3fbd68282bb868762d4949a3ff2",
                 "aarch64": "115a161100336ae5e948d0fe57c7388fec302fe7bb5e2a2f23dadcefb64edead"}
#: copies done in one go at most (the bar moves between batches)
PIECES_BATCH = 64 << 20
#: the machine hashes the same-size files a full Send compares in batches this big, the bar moving after each
COMPARE_BATCH_FILES = 200
#: differing blocks written per SFTP open: the bar moves after each batch (4 MB: a few seconds over Wi-Fi)
DELTA_BATCH = 4
COMPARE_BATCH_BYTES = 128 << 20


def _blocks(tree, node, bs=None):
    """The build's file in exact *bs* blocks, ``(offset, bytes)``."""
    bs = bs or DELTA_BLOCK
    buf, at = b"", 0
    for _off, chunk in tree.chunks(node):
        buf += bytes(chunk)
        while len(buf) >= bs:
            yield at, buf[:bs]
            buf, at = buf[bs:], at + bs
    if buf:
        yield at, buf


def delta_put(machine, tree, op, cancel=None, at=None, progress=None):
    """Make the machine's existing copy of ``op.path`` (or the copy of it at *at*) the build's file by writing
    only the blocks that differ, in place.  Only with the game stopped (it would read a half-changed file), and
    never on the system partition itself (:func:`delta_replace`).  Returns the bytes written.  *progress(done)*
    (PAD-1433) is told how far through the file it is after each batch written, so a big file moves the bar."""
    path = at or op.path
    size, theirs = machine.block_hashes(path)
    sent, batch = 0, []
    for off, block in _blocks(tree, op.node):
        i = off // DELTA_BLOCK
        if i < len(theirs) and theirs[i] == hashlib.sha1(block).hexdigest():
            continue
        batch.append((off, block))
        sent += len(block)
        if len(batch) >= DELTA_BATCH:
            machine.write_ranges(path, batch)
            batch = []
            if progress is not None:
                progress(min(off + len(block), op.size))
        if cancel is not None and cancel():
            raise SendError("Send canceled.")
    if batch:
        machine.write_ranges(path, batch)
    if size > op.size:
        machine.truncate(path, op.size)
    machine.set_attrs(path, op.mode, op.uid, op.gid)
    machine.set_mtime(path, op.node["mtime"])
    if machine.state([path]).get(path) != ("file", op.sha1):
        raise SendError("%s didn't check out on the machine after its changes were written; send again (the game "
                        "stays stopped until it does)." % op.path)
    return sent


def delta_replace(machine, tree, op, cancel=None, progress=None):
    """:func:`delta_put` for a system-partition file: the remote access session runs on those (busybox is the
    shell and every tool a Send uses; the server and libc too), and a program changed under its running copy
    breaks, as a file cut off half-written would on the next boot.  So the machine copies the file beside
    itself, the differing blocks go into the copy, and it is renamed over the original: running programs keep
    the old one until the machine restarts, and the file is always either old or new.  Returns the bytes
    written."""
    tmp = posixpath.join(posixpath.dirname(op.path), "." + posixpath.basename(op.path) + TMP_TAG)
    machine.copy(op.path, tmp)
    try:
        sent = delta_put(machine, tree, op, cancel, at=tmp, progress=progress)
        machine.commit([(tmp, op.path)], [], [])
    except BaseException:
        with contextlib.suppress(Exception):
            machine.remove([tmp])
        raise
    return sent


class PieceJob:
    """PAD-1435: one mount's changed game files, to be built from pieces the machine already has
    (:func:`pieces_prepare`, then :func:`pieces_run` with the game stopped)."""

    def __init__(self, mount, ops, plan, uploads):
        self.mount, self.ops, self.plan = mount, ops, plan
        #: new files no piece of which is on the machine: uploaded whole, as before
        self.uploads = uploads
        self.paths = {op.path for op in ops}
        self.net = 0


def pieces_prepare(machine, tree, mount, ops, has, progress=None, log=None):
    """The :class:`PieceJob` for *ops* (puts on one game mount; *has*: the paths of those the machine has a copy
    of, changed in place), or None when the machine can't do pieces (the 1 MiB delta then, as before).  Reads only
    the machine's copies of the files it changes in place, as the delta did."""
    from . import send_pieces as SP
    ops = [op for op in ops if not any(c in op.path for c in "\t\n")]
    if not ops or not machine.pieces_ready():
        return None
    progress = progress or (lambda *a, **k: None)
    what = "Comparing the pieces of the changed files"
    old = [op for op in ops if op.path in has]
    total_b = (sum(op.size for op in old) + sum(op.size for op in ops)) or 1
    done_b, index, batch, batch_b = 0, {}, [], 0
    progress(0, total_b, what)
    for i, op in enumerate(old):
        batch.append(op.path)
        batch_b += op.size
        if len(batch) >= COMPARE_BATCH_FILES or batch_b >= COMPARE_BATCH_BYTES or i == len(old) - 1:
            index.update(machine.piece_hashes(batch))
            done_b += batch_b
            batch, batch_b = [], 0
            progress(min(done_b, total_b), total_b, what)
    files = []
    for op in ops:
        files.append((op.path, SP.local_pieces(tree, op.node)))
        done_b += op.size
        progress(min(done_b, total_b), total_b, what)
    # a copy the machine couldn't read is new to it: built like a new file, from pieces and sends
    plan = SP.plan(index, files)
    in_place = set(index)
    uploads = [op for op in ops if op.path not in in_place and not plan.copied_to(op.path)]
    job = PieceJob(mount, [op for op in ops if op not in uploads], plan, uploads)
    job.in_place = in_place
    if log is not None:
        whole = sum(op.size for op in ops)
        log("Of the %s of changed game files, the machine has %s already (%s in place, %s elsewhere on its card, "
            "copied there): %s goes over the network." % (
                _human(whole), _human(plan.kept + plan.copied), _human(plan.kept), _human(plan.copied),
                _human(whole - plan.kept - plan.copied)), "info")
    return job


def pieces_run(machine, tree, job, cancel, progress, base, total, temps, free=None):
    """Make the machine's files *job*'s: copies of its own pieces first, in :func:`send_pieces.plan`'s order and in
    batches each safe to do again after a dropped connection (none overwrites a piece the batch read), then what
    it doesn't have, then each file's size, owner, mode and time, checked whole.  A new file is built beside its
    name and renamed over it, or in place when the room isn't there for that.  Returns *base* plus the job's
    bytes (the bar's count); ``job.net`` is what crossed the network."""
    from .send_pieces import PIECE
    plan = job.plan
    news = [op for op in job.ops if op.path not in job.in_place]
    room = machine.free(job.mount) if free is None else free
    beside = room >= sum(op.size for op in news) + SPARE
    dest = {}
    for op in job.ops:
        if op.path in job.in_place or not beside:
            dest[op.path] = op.path
        else:
            dest[op.path] = posixpath.join(posixpath.dirname(op.path),
                                           "." + posixpath.basename(op.path) + TMP_TAG)
            temps.append(dest[op.path])
    done = plan.kept
    progress(base + done, total, "Updating")
    batch, reads, batch_b = [], set(), 0

    def flush():
        nonlocal batch, reads, batch_b, done
        if batch:
            machine.copy_pieces([(s, so, dest.get(d, d), do, n) for s, so, d, do, n in batch])
            done += batch_b
            progress(base + done, total, "Updating")
            if cancel is not None and cancel():
                raise SendError("Send canceled.")
        batch, reads, batch_b = [], set(), 0

    for c in plan.copies:
        s, so, d, do, n = c
        writes = {(d, k) for k in range(do // PIECE, (do + n + PIECE - 1) // PIECE)}
        if writes & reads or batch_b + n > PIECES_BATCH:
            flush()
        batch.append(c)
        batch_b += n
        reads.update((s, k) for k in range(so // PIECE, (so + n + PIECE - 1) // PIECE))
    flush()
    for op in job.ops:
        path = dest[op.path]
        ranges = plan.sends.get(op.path, ())
        for i in range(0, len(ranges), DELTA_BATCH):
            if cancel is not None and cancel():
                raise SendError("Send canceled.")
            data = [(off, _read_node(tree, op.node, off, n)) for off, n in ranges[i:i + DELTA_BATCH]]
            machine.write_ranges(path, data)
            got = sum(len(b) for _o, b in data)
            job.net += got
            done += got
            progress(base + done, total, "Updating")
    for op in job.ops:
        path = dest[op.path]
        machine.truncate(path, op.size)
        machine.set_attrs(path, op.mode, op.uid, op.gid)
        machine.set_mtime(path, op.node["mtime"])
        if machine.state([path]).get(path) != ("file", op.sha1):
            raise SendError("%s didn't check out on the machine after its changes were written; send again (the game "
                            "stays stopped until it does)." % op.path)
        if path != op.path:
            machine.commit([(path, op.path)], [], [])
            temps.remove(path)
    return base + sum(op.size for op in job.ops)


def _read_node(tree, node, off, n):
    data = tree.read_range(node, off, n)
    if len(data) != n:
        raise SendError("Couldn't read the build's file at %d." % off)
    return bytes(data)


def root_room(machine, root_puts, existing):
    """The room the system partition needs for *root_puts* replaced by copy and rename (:func:`delta_replace`)
    or uploaded beside: new files whole; each file a running program holds keeps its old copy until the restart,
    so both stay; any other replaced one frees its old copy at its rename, so only the largest counts once."""
    held = machine.in_use()
    new = sum(op.size for op in root_puts if op.path not in existing)
    pinned = sum(op.size for op in root_puts if op.path in existing and op.path in held)
    other = max([op.size for op in root_puts if op.path in existing and op.path not in held] or [0])
    grow = sum(max(0, op.size - existing[op.path]) for op in root_puts
               if op.path in existing and op.path not in held)
    return new + pinned + other + grow + SPARE


def _check_root_room(machine, root_puts, existing):
    if not root_puts:
        return
    need, free = root_room(machine, root_puts, existing), machine.free(ROOT)
    if free < need:
        raise SendError("There isn't room on the machine's system partition to change its files safely (%s "
                        "needed, %s free): its running programs keep their old copies until it restarts. Write "
                        "the card instead." % (_human(need), _human(free)))


def open_target(image, log=None):
    """The :class:`Target` for any card image: a PAD build, or a card of Stern's or anyone's (a new code version,
    a custom code card, a multi-boot card).  Its quick :class:`Plan` rides along when it is a finished PAD build
    whose original is still here."""
    from ..plugins.stern import spike3
    from ..plugins.stern.ext4 import Ext4Reader
    from . import ssh_card
    log = log or (lambda *a, **k: None)
    if not image or not os.path.isfile(image):
        raise SendError("Pick the card image to send.")
    info = ssh_card.inspect_image(image)
    platform = info.get("platform")
    if platform not in ("stern-spike2", "stern-spike3"):
        raise SendError("This isn't a Stern Spike 2 or Spike 3 card image PAD can send: %s"
                        % (info.get("reason") or "not recognized"))
    with open(image, "rb") as f:
        parts = spike3.parse_partitions(f)
    layout = {p["index"]: (p["start_lba"], p["sectors"], p["ptype"]) for p in parts}
    plan = None
    from ..plugins.stern import engine
    if engine.read_build_manifest(image):
        try:
            plan = open_plan(image, log)
        except SendError as e:
            log("This build can't be sent the quick way (%s); everything on the machine is compared with it."
                % e, "info")
    closers, trees, raw = [], {}, {}
    try:
        if platform == "stern-spike3":
            from ..plugins.stern import spike3_card
            from . import ssh_spike3
            keys = ssh_spike3.key_for(image)
            stack = contextlib.ExitStack()
            closers.append(stack.close)
            ro = stack.enter_context(ssh_spike3.open_rootfs(image, key_source=keys))
            trees[ROOT] = _Tree(Ext4Reader(ro, 0, ro.size), ROOT)
            go = spike3_card.open_games(image, key_source=keys)
            stack.callback(go.close)
            trees[GAMES] = _Tree(Ext4Reader(go, 0, go.size), GAMES)
            for p in parts:
                if p["ptype"] in FAT_TYPES and p["index"] == 1:
                    raw[1] = (p["start_lba"] * 512, p["sectors"] * 512)
            target = Target(image, platform, layout, trees, raw, closers, plan, None, info)
        else:
            from ..plugins.stern import multiimage
            f = open(image, "rb")
            closers.append(f.close)
            for p in parts:
                num, ptype = p["index"], p["ptype"]
                off, size = p["start_lba"] * 512, p["sectors"] * 512
                if ptype in FAT_TYPES:
                    raw[num] = (off, size)
                    continue
                if ptype != 0x83:
                    continue
                try:
                    reader = Ext4Reader(f, off, size)
                except Exception:                           # noqa: BLE001 - not ext: left alone
                    continue
                if num == 2:
                    trees[ROOT] = _Tree(reader, ROOT)
                elif num == 3:
                    trees[GAMES] = _Tree(reader, GAMES)
                elif multiimage._images_in(reader, num):
                    # a multi-boot card's other game images: the machine doesn't mount them; the Send does
                    mount = "%s/p%d" % (TEMP_MOUNT, num)
                    trees[mount] = _Tree(reader, mount)
            if ROOT not in trees or GAMES not in trees:
                raise SendError("This card's partitions aren't the usual Spike 2 layout.")
            text = _fstab(trees[ROOT].reader)
            if not any(line.split()[:2] == [b"/dev/mmcblk0p3", b"/games"] for line in text.splitlines()
                       if line.strip() and not line.startswith(b"#")):
                raise SendError("This card doesn't mount its game partition the usual Spike 2 way.")
            target = Target(image, platform, layout, trees, raw, closers, plan, None, info)
            target.parts = {m: int(m.rsplit("/p", 1)[1]) for m in trees if m.startswith(TEMP_MOUNT)}
        target.card_id = plan.card_id if plan is not None else {"name": os.path.basename(image),
                                                               "size": os.path.getsize(image)}
        return target
    except BaseException:
        if plan is not None:
            plan.close()
        for fn in reversed(closers):
            with contextlib.suppress(Exception):
                fn()
        raise


def _gb(sectors):
    return "%.1f GB" % (sectors * 512 / 1e9)


def _has_boot_menu(target):
    """PAD-1543: is *target* a multi-boot image: its system partition carries the boot menu's list of games (and it
    isn't a test card, whose menu runs no game)?"""
    tree = (getattr(target, "trees", None) or {}).get(ROOT)
    ent = tree.get(TESTCARD_CONF) if tree is not None else None
    return bool(ent) and ent[0] == "file" and not is_test_card(target)


def check_layout(target, machine_layout):
    """Refuse an image the machine's card can't take file by file: those need the card written.

    PAD-1432: on a Spike 2 card only what the Send needs is checked, not where each partition sits: a machine whose
    card was written with a bigger game partition (or an image built with one) still takes a Send.  A partition
    copied whole (the boot partition) must be the same size; the system and game partitions are synced file by file
    into the machine's own, whose free space the Send checks; any other partition the Send syncs (a multi-boot
    card's game images) must be at least as big on the machine; partitions the Send doesn't touch (the extended
    one, /data, /dump) may be anywhere.  Other platforms keep the exact layout."""
    bad = []
    spike2 = getattr(target, "platform", "") == "stern-spike2"
    synced = set(getattr(target, "parts", {}).values())
    raw = set(getattr(target, "raw", {}) or ())
    for num, (start, sectors, ptype) in sorted(target.layout.items()):
        have = machine_layout.get(num)
        if have is None:
            bad.append("partition %d is missing" % num)
        elif not spike2:
            if have[0] != start or (ptype not in EXTENDED_TYPES and have[1] != sectors):
                bad.append("partition %d is placed or sized differently" % num)
        elif num in raw:
            if have[1] != sectors:
                bad.append("partition %d (the boot partition, copied whole) is %s on the machine but %s in the "
                           "image" % (num, _gb(have[1]), _gb(sectors)))
        elif num in synced and have[1] < sectors:
            bad.append("partition %d is %s on the machine, smaller than the image's %s"
                       % (num, _gb(have[1]), _gb(sectors)))
        elif num >= 7 and ptype not in EXTENDED_TYPES and have[1] < sectors:
            # PAD-1543: a store-layout multi-boot card's work partition, where its menu rebuilds at boot the files
            # the card holds as differences from another game's.  Too small for this image's, the menu would
            # start the game with the other game's files in their place and say nothing
            bad.append("partition %d (where the card's menu rebuilds files it holds as differences) is %.0f MB "
                       "on the machine, smaller than the %.0f MB this image needs"
                       % (num, have[1] * 512 / 1e6, sectors * 512 / 1e6))
    extra = sorted(set(machine_layout) - set(target.layout))
    if extra:
        bad.append("the machine has partition%s %s that the image doesn't"
                   % ("s" if len(extra) > 1 else "", ", ".join(map(str, extra))))
    # PAD-1543 (David sent a multi-boot image to a machine running a one-game card and was told only "partition 7
    # is missing ... write the card instead"): say what the two cards are and what to do
    menu = _has_boot_menu(target)
    missing = sorted(set(target.layout) - set(machine_layout))
    if spike2 and menu and missing:
        sizes = ""
        if 3 in target.layout and 3 in machine_layout:
            sizes = " (its game partition is %s; this image's is %s)" % (_gb(machine_layout[3][1]),
                                                                        _gb(target.layout[3][1]))
        raise SendError("This is a multi-boot image, and the card in the machine isn't laid out for one: partition "
                        "%s is missing%s. A Send changes files, never a card's partitions, so write this image to "
                        "the SD card once; after that, new builds of it can be sent to the machine."
                        % (", ".join(map(str, missing)), sizes))
    if spike2 and not menu and extra and not missing and max(extra) >= 7:
        raise SendError("The image's partitions don't match the machine's card (%s). If the machine runs a "
                        "multi-boot card, this one-game image can't replace one of its games: build the multi-boot "
                        "image again with this version in it and send that." % "; ".join(bad))
    if bad:
        raise SendError("The image's partitions don't match the machine's card (%s), so it can't be sent file by "
                        "file: write the card instead." % "; ".join(bad))


def _protected(platform, target_tree):
    """The machine's remote access (PR #38's files) where the image has none: kept, so the machine can still be
    reached after an update to a card without it."""
    from . import ssh_card
    l = ssh_card.layout(platform)
    keep = set(l["files"].values()) | {l["hook"], l["ssh_dir"]}
    keep = {p for p in keep if target_tree.get(p) is None}
    for p in list(keep):
        d = posixpath.dirname(p)
        while d not in ("/", ""):
            keep.add(d)
            d = posixpath.dirname(d)
    return keep


#: PAD-1543: a multi-boot card's shared store (mkmulticard's store layout): every game's files are hard links to
#: the files of this folder of the game partition, each held once
STORE_DIR = ".blobs"


def store_links(tree, mount):
    """PAD-1543: ``{name: the file it is another name of}`` for a partition of the image that holds a multi-boot
    card's shared store, else ``{}``.  There, one file has several names (the store's, and each game's own); the
    Send sends it once, under the first, and makes the others hard links to it, as they are on the image.  Taken
    as separate files (as a Send did before), a changed file was sent and held once per name, and a file two
    games share, changed in place under one game's name, changed under the other's too."""
    store = posixpath.join(mount, STORE_DIR)
    if (tree.get(store) or ("",))[0] != "dir":
        return {}
    groups = {}
    for path, ino in tree.inos.items():
        groups.setdefault(ino, []).append(path)
    out = {}
    for paths in groups.values():
        if len(paths) < 2:
            continue
        paths.sort(key=lambda p: (not p.startswith(store + "/"), p))
        for p in paths[1:]:
            out[p] = paths[0]
    return out


def store_link_ops(tree, mine, followers, put_paths, ids, differ=()):
    """PAD-1543: the ``hardlink`` ops for *followers* (:func:`store_links`): a name that isn't, on the machine, the
    very file its first name is (*ids*: ``{path: inode}`` there), or whose file the Send writes anew
    (*put_paths*).  A machine that can't say which files are one (*ids* None: its busybox has no stat) had its
    names compared like any file instead, and the ones that *differ* are linked: there a card left with two
    copies of a file keeps them, as nothing can tell."""
    ops = []
    for path, first in sorted(followers.items()):
        m = mine.get(path)
        if m is not None and m[0] == "dir":
            raise SendError("%s is a folder on the machine but not on the image; write the card instead." % path)
        if ids is None:
            if path not in differ:
                continue
        elif (first not in put_paths and m is not None and m[0] == "file"
                and ids.get(path) is not None and ids.get(path) == ids.get(first)):
            continue
        node = tree.entries[path][1]
        ops.append(Op("hardlink", path, target=first, mode=stat.S_IMODE(node["mode"]), uid=node["uid"],
                      gid=node["gid"], stock=None, from_ledger=True))
    return ops


def sync_ops(tree, mine, prefix, protected, own_mounts, hashes_on_machine, log=None, progress=None,
             followers=()):
    """The ops that make the machine's files under *prefix* (*mine*: its walk) the image's *tree*.  A file the
    same size on both is compared by sha1 (``hashes_on_machine(paths)``), so an unchanged file is never sent.
    *followers* (PAD-1543, :func:`store_links`): names left to :func:`store_link_ops`, never compared or sent."""
    ops, same_size = [], []
    for path, (kind, node, _sig) in sorted(tree.entries.items()):
        if any(path == m or path.startswith(m + "/") for m in own_mounts if m != prefix):
            continue
        if kind == "file" and path in followers:
            continue
        m = mine.get(path)
        own = dict(mode=stat.S_IMODE(node["mode"]), uid=node["uid"], gid=node["gid"], stock=None, from_ledger=True)
        if kind == "dir":
            if m is None:
                ops.append(Op("mkdir", path, **own))
            elif m[0] != "dir":
                ops.append(Op("delete", path, from_ledger=True))
                ops[-1].cur = ("file",)
                ops.append(Op("mkdir", path, **own))
            continue
        if m is not None and m[0] == "dir":
            raise SendError("%s is a folder on the machine but not on the image; write the card instead." % path)
        if kind == "symlink":
            t = tree.link(node)
            if m is None or m[0] != "symlink" or m[6] != t:
                ops.append(Op("link", path, target=t, **own))
            continue
        if kind != "file":
            continue
        if m is not None and m[0] == "file" and m[1] == node["size"]:
            same_size.append((path, node, own))
        else:
            ops.append(Op("put", path, node=node, size=node["size"], sha1=None, **own))
    if same_size:
        if log:
            log("Comparing %d file(s) the same size on the machine and the image..." % len(same_size), "info")
        # PAD-1433: the machine hashes its copies in batches, and the bar moves by the bytes hashed.  One call for
        # every file sat the bar at the last partition's 99% for the minutes the machine read gigabytes
        what = "Comparing the %s files" % ("system" if prefix == ROOT else "game" if prefix == GAMES else prefix)
        total_b = sum(n["size"] for _p, n, _o in same_size) or 1
        theirs, done_b, batch, batch_b = {}, 0, [], 0
        if progress:
            progress(0, total_b, what)
        for i, (path, n, _own) in enumerate(same_size):
            batch.append(path)
            batch_b += n["size"]
            if len(batch) >= COMPARE_BATCH_FILES or batch_b >= COMPARE_BATCH_BYTES or i == len(same_size) - 1:
                theirs.update(hashes_on_machine(batch))
                done_b += batch_b
                batch, batch_b = [], 0
                if progress:
                    progress(min(done_b, total_b), total_b, what)
        for path, node, own in same_size:
            digest = tree.sha1(node)
            m_mode, m_uid, m_gid = mine[path][3:6]
            # the card's SFTP server doesn't say who owns a file (None): an owner it doesn't name isn't a difference
            other_owner = ((m_uid is not None and m_uid != own["uid"])
                           or (m_gid is not None and m_gid != own["gid"]))
            if theirs.get(path) != ("file", digest) or m_mode != own["mode"] or other_owner:
                ops.append(Op("put", path, node=node, size=node["size"], sha1=digest, **own))
    for path in sorted(set(mine) - set(tree.entries), key=lambda p: -p.count("/")):
        if path in protected:          # exact paths: a protected folder keeps itself, not what else is in it
            continue
        op = Op("delete", path, from_ledger=True)
        op.cur = ("dir",) if mine[path][0] == "dir" else ("file",)
        ops.append(op)
    for op in ops:
        if op.kind == "put" and op.sha1 is None:
            op.sha1 = tree.sha1(op.node)
    return ops


def sync(target, machine, log=None, progress=None, cancel=None):
    """The full Send: make every file of the machine's card the image's (apart from its own settings, scores and
    logs), then reboot it.  Returns a summary line."""
    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)

    def check():
        if cancel():
            raise SendError("Send canceled.")

    mounts = machine.mounts()
    on = {mp for _dev, mp in mounts}
    for need in (ROOT, GAMES):
        if need not in on:
            raise SendError("The machine has nothing mounted at %s; it isn't running a Spike card PAD knows." % need)
    busy = [num for num in target.parts.values() if any(dev.endswith("p%d" % num) for dev, _mp in mounts)]
    if busy:
        raise SendError("The machine is using its partition %d; switch it to the main game and send again." % busy[0])
    cache = HashCache(machine, log)
    log("Comparing everything on the machine with %s (the image isn't a build of the card the machine runs, so "
        "this reads every file it may need to change%s)." % (
            os.path.basename(target.path),
            "; those it hashed on an earlier Send and that haven't changed since aren't read again" if cache.files
            else ": a few minutes"), "info")
    mounted, rw, all_ops, temps, walks = [], [], {}, [], {}
    shared = {}                             # PAD-1543: {mount: store_links()} of the mounts holding a shared store
    reboot = False
    changed = False
    delta_bytes = 0
    # PAD-1427 (David: "I'm concerned about letting the game run while we are doing updates and I want to make sure
    # we have a clean isolated update path"): the game is held, the machine's screen saying so, BEFORE the
    # comparison reads the card - nothing of a Send runs beside a game being played
    machine.pause_game()                    # already held when it came through send_image
    progress = _also_on_screen(machine, progress)
    try:
        for mount, num in sorted(target.parts.items()):
            machine.mount_part(num, mount)
            mounted.append(mount)
        for mount, tree in target.trees.items():
            check()
            protected = _protected(target.platform, tree) if mount == ROOT else set()
            skip = [m for m in on if m != mount and (m.startswith(mount.rstrip("/") + "/") or mount == ROOT)]
            mine = walks[mount] = machine.walk(mount, skip)
            # PAD-1543: a multi-boot card's shared store: each file once, its other names hard links to it
            followers = store_links(tree, mount) if mount != ROOT else {}
            ids = None
            if followers:
                shared[mount] = followers
                names = sorted(p for p in set(followers) | set(followers.values())
                               if (mine.get(p) or ("",))[0] == "file")
                got = machine.file_ids(names) if names else (0, {})
                ids = None if got is None else {p: v[2] for p, v in got[1].items()}
            ops = sync_ops(tree, mine, mount, protected, skip,
                           lambda paths: cache.hashes(paths, machine.file_sha1s), log, progress,
                           followers if ids is not None else ())
            if followers:
                differ = {op.path for op in ops if op.kind == "put" and op.path in followers}
                ops = [op for op in ops if not (op.kind == "put" and op.path in differ)]
                ops += store_link_ops(tree, mine, followers, {op.path for op in ops if op.kind == "put"}, ids,
                                      differ)
            if ops:
                all_ops[mount] = ops
        raws = {}
        for num in sorted(target.raw):
            check()
            want = target.raw_sha1(num)
            if machine.raw_sha1(num) != want:
                raws[num] = want
        cache.said(log)
        cache.save()                            # kept even if the Send stops part way
        n = sum(len(v) for v in all_ops.values())
        if not n and not raws:
            log("The machine already has everything on this image; nothing to send. Its game starts again.",
                "success")
            if machine.game_held():
                machine.resume_game(screen_text("NOTHING TO", "UPDATE", "RESTARTING GAME"))
            return "The machine already has this image."
        # PAD-1435: changed game files are built from 64 KB pieces the machine has anywhere among the files it
        # rewrites (only those are read, as the 1 MiB delta read them), the rest sent
        jobs = {}
        for mount, ops in all_ops.items():
            if mount == ROOT or mount in shared:
                # PAD-1543: nothing of a shared store is changed in place (below), so no pieces job there
                continue
            mine_puts = [op for op in ops if op.kind == "put"]
            has = {op.path for op in mine_puts if (walks[mount].get(op.path) or ("",))[0] == "file"}
            job = pieces_prepare(machine, target.trees[mount], mount, mine_puts, has, progress, log)
            if job is not None:
                jobs[mount] = job
        puts = [op for ops in all_ops.values() for op in ops if op.kind == "put"]
        total = sum(op.size for op in puts) or 1
        relinks = sum(op.kind == "hardlink" for v in all_ops.values() for op in v)
        log("Sending %d change(s): %d file(s) (%s), %d link(s), %d removal(s)%s%s."
            % (n, len(puts), _human(sum(op.size for op in puts)),
               sum(op.kind == "link" for v in all_ops.values() for op in v),
               sum(op.kind == "delete" for v in all_ops.values() for op in v),
               (", %d name(s) of files the card's games share" % relinks if relinks else ""),
               (", and the boot partition" if raws else "")), "info")
        # the system partition is what the session runs on: its files change by copy and rename, never in place,
        # so its room is checked before anything is touched
        root_puts = [op for op in all_ops.get(ROOT, ()) if op.kind == "put"]
        _check_root_room(machine, root_puts, {op.path: walks[ROOT][op.path][1] for op in root_puts
                                              if (walks[ROOT].get(op.path) or ("",))[0] == "file"})
        # the game was held before the comparison: an update, not an edit.  The machine restarts on a new system
        # or game partition or boot files; other changes (a multi-boot card's spare images) restart only its game
        reboot = bool(all_ops.get(ROOT) or all_ops.get(GAMES) or raws)
        if reboot:
            machine.stop_game()                 # held already: the game's loop stays frozen until the reboot
        machine.screen_changing()
        changed = True
        for mount in all_ops:
            machine.remount(mount, True)
            rw.append(mount)
        sent = 0
        for mount, ops in all_ops.items():
            tree = target.trees[mount]
            dels = [(op.path, getattr(op, "cur", None) == ("dir",))
                    for op in sorted((o for o in ops if o.kind == "delete"), key=lambda o: -o.path.count("/"))]
            # game files go first (their room is wanted); system files last, so every command the Send still runs
            # finds the libraries it was built against
            if dels and mount != ROOT:
                machine.commit([], [], dels)
            for op in sorted((o for o in ops if o.kind == "mkdir"), key=lambda o: o.path.count("/")):
                machine.mkdir(op.path, op.mode, op.uid, op.gid)
            job = jobs.get(mount)
            if job is not None and job.ops:
                check()
                log("Updating %d game file(s) (%s) from the pieces the machine has and the parts it doesn't..."
                    % (len(job.ops), _human(sum(op.size for op in job.ops))), "info")
                sent = pieces_run(machine, tree, job, cancel, progress, sent, total, temps)
                delta_bytes += job.net
            names = {}                          # PAD-1543: {a shared file: its other names}
            for name, first in shared.get(mount, {}).items():
                names.setdefault(first, []).append(name)
            for op in (o for o in ops if o.kind == "put" and (job is None or o.path not in job.paths)):
                check()
                have = walks[mount].get(op.path)
                if have is not None and have[0] == "file":
                    # the machine has a copy: only its changed blocks go (the game is stopped; a cut-off Send is
                    # finished by the next one, which compares everything again).  Game files change in place;
                    # system files in a copy renamed over them (delta_replace: the session runs on those), and so
                    # do a shared store's (PAD-1543: in place, a file changes under every name it has, another
                    # game's among them)
                    log("Updating %s (%s; only the parts that differ are sent)..." % (op.path, _human(op.size)),
                        "info")
                    delta_bytes += (delta_replace if mount == ROOT or mount in shared else delta_put)(
                        machine, tree, op, cancel,
                        progress=lambda done, base=sent: progress(base + done, total, "Updating"))
                    sent += op.size
                    progress(sent, total, "Updating")
                    continue
                tmp = posixpath.join(posixpath.dirname(op.path), "." + posixpath.basename(op.path) + TMP_TAG)
                # PAD-1543: a shared store names a file by what is in it, so a changed file is a NEW one there.
                # The machine's old version is still under the game's own name for it: a copy of that, beside
                # the new file's name, takes only the blocks that differ, then gets the name
                old = next((p for p in sorted(names.get(op.path, ()))
                            if (walks[mount].get(p) or ("",))[0] == "file"), None)
                if old is not None and machine.free(mount) >= op.size + walks[mount][old][1] + SPARE:
                    log("Updating %s (%s; from the machine's %s, only the parts that differ are sent)..."
                        % (op.path, _human(op.size), old), "info")
                    machine.copy(old, tmp)
                    temps.append(tmp)
                    delta_bytes += delta_put(machine, tree, op, cancel, at=tmp,
                                             progress=lambda done, base=sent: progress(base + done, total,
                                                                                       "Updating"))
                    machine.commit([(tmp, op.path)], [], [])
                    temps.remove(tmp)
                    sent += op.size
                    progress(sent, total, "Updating")
                    continue
                direct = mount != ROOT and machine.free(mount) < op.size + SPARE
                dest = op.path if direct else tmp
                if direct and machine.free(mount) < op.size + (1 << 20):
                    raise SendError("There isn't room on the machine for %s (%s); write the card instead."
                                    % (op.path, _human(op.size)))
                if not direct:
                    temps.append(tmp)
                log("Uploading %s (%s)..." % (op.path, _human(op.size)), "info")
                base = sent

                def cb(done, _total, base=base):
                    progress(base + done, total, "Uploading")
                    if cancel():
                        raise SendError("Send canceled.")
                machine.upload(dest, _ChunkFile(tree, op.node), op.size, op.mode, op.uid, op.gid, cb)
                machine.set_mtime(dest, op.node["mtime"])
                sent += op.size
                if machine.state([dest]).get(dest) != ("file", op.sha1):
                    raise SendError("%s didn't arrive whole on the machine; send again." % op.path)
                if not direct:
                    machine.commit([(tmp, op.path)], [], [])
                    temps.remove(tmp)
            links = [(op.path, op.target, op.uid, op.gid) for op in ops if op.kind == "link"]
            if links:
                machine.commit([], links, [])
            # PAD-1543: last, when every file they are names of is in place
            hard = [(op.target, op.path) for op in ops if op.kind == "hardlink"]
            if hard:
                check()
                log("Linking %d name(s) to the files the card's games share..." % len(hard), "info")
                machine.hardlink(hard)
            if dels and mount == ROOT:
                machine.commit([], [], dels)
        for num, want in raws.items():
            check()
            log("Writing the boot partition (%s)..." % _human(target.raw[num][1]), "info")
            machine.raw_write(num, _RawFile(lambda num=num: target.raw_chunks(num)), target.raw[num][1], want)
        machine.sync()
        rec = target.plan.record() if target.plan is not None else {"paths": [], "ranges": {}}
        machine.write_ledger(dict(rec, card=target.card_id, pending=False))
        # PAD-1444: every file it put there was checked on the machine: the next compare needn't read it again
        cache.remember({op.path: op.sha1 for ops in all_ops.values() for op in ops if op.kind == "put"})
        cache.save(rebooting=reboot)
    except BaseException:
        if temps:
            with contextlib.suppress(Exception):
                machine.remove(temps)
        with contextlib.suppress(Exception):
            machine.screen_stopped(changed)
        raise
    finally:
        for mount in rw:
            with contextlib.suppress(Exception):
                machine.remount(mount, False)
        for mount in mounted:
            with contextlib.suppress(Exception):
                machine.umount_part(mount)
    n = sum(len(v) for v in all_ops.values())
    progress(1, 1, "Finishing")
    if reboot:
        log("Restarting the machine on the new card...", "info")
        machine.reboot()
    else:
        machine.resume_game()
    if delta_bytes:
        log("Of the files the machine already had, only the parts that differ were sent: %s." % _human(delta_bytes),
            "info")
    return "Sent %d change(s)%s to the machine%s." % (
        n, " and its boot partition" if raws else "", "; it is restarting" if reboot else "")


def _also_on_screen(machine, progress):
    """*progress*, also shown on the machine's screen (PAD-1427)."""
    def both(done, total, what=""):
        machine.screen_progress(done, total, what)
        if progress is not None:
            progress(done, total, what)
    return both


#: a PAD TEST CARD (PAD-1279; mkmulticard testcard): its boot menu's conf says testcard=on, and it runs no game
TESTCARD_CONF = "/usr/local/codeselect/images.conf"
_TESTCARD_ON = re.compile(rb"^[ \t]*testcard[ \t]*=[ \t]*on[ \t]*\r?$", re.M)
TESTCARD_ONLY = ("This is a PAD test card, and the machine isn't running one: a Send makes the machine's "
                 "/games what the image has, so its game would be deleted. Write this test card to an SD card "
                 "for that machine; once it runs one, its test card can be sent over the network.")
#: Simon (2026-11-26): "create a card which is only a test card no multiboot (over the network)" - a machine running
#: a PAD multi-boot card may have it replaced by a test card, but only when the user was asked (Send to machine...)
TESTCARD_OVER_MENU = ("This is a PAD test card, and the machine runs a PAD multi-boot card: a Send makes the "
                      "machine's /games what the image has, so its games would be deleted. Send it from the Test "
                      "card tab's Send to machine..., which asks before it replaces the multi-boot card.")


def is_test_card(target):
    """Is *target* a PAD test card image: its menu's conf says testcard=on?"""
    tree = target.trees.get(ROOT)
    ent = tree.entries.get(TESTCARD_CONF) if tree is not None else None
    if not ent or ent[0] != "file":
        return False
    try:
        return bool(_TESTCARD_ON.search(bytes(tree.reader.read_file_bytes(ent[1]))))
    except Exception:                                   # noqa: BLE001 - unreadable: not one we know
        return False


def machine_card_kind(machine):
    """What the machine runs: "testcard" (a PAD test card), "menu" (a PAD multi-boot card: the boot menu's list on
    its system partition) or "game" (a one-game card)."""
    _rc, text = machine.sh("if grep -qE '^[[:space:]]*testcard[[:space:]]*=[[:space:]]*on[[:space:]]*$' %s; then "
                           "echo PAD_TESTCARD; elif [ -f %s ]; then echo PAD_MENU_CARD; fi"
                           % (TESTCARD_CONF, TESTCARD_CONF), check=False)
    text = text or ""
    return "testcard" if "PAD_TESTCARD" in text else "menu" if "PAD_MENU_CARD" in text else "game"


def check_test_card_target(target, machine, replace_menu_card=False):
    """Simon (2026-11-22): a test card updated over the network.  Sending one to a machine running a GAME card
    would delete the game (a full Send makes /games the image's), so a test card goes only to a machine that runs
    a test card already - or, Simon (2026-11-26), to one running a PAD multi-boot card when *replace_menu_card*
    says the user was asked and said yes."""
    if not is_test_card(target):
        return
    kind = machine_card_kind(machine)
    if kind == "testcard" or (kind == "menu" and replace_menu_card):
        return
    raise SendError(TESTCARD_OVER_MENU if kind == "menu" else TESTCARD_ONLY)


def _is_iso(path):
    from .ssh_jjp import is_iso
    return is_iso(path)


def send_image(image, machine, log=None, progress=None, cancel=None, replace_menu_card=False):
    """Send *image* to *machine*: the quick Send when it is a build of the card the machine runs, else the full
    one.  Returns a summary line.  *replace_menu_card*: a test card may replace a PAD multi-boot card (the user
    was asked)."""
    log = log or (lambda *a, **k: None)
    from . import remote_send_jjp
    if remote_send_jjp.is_build(image) or _is_iso(image):
        # PAD-1587: a JJP install ISO: its Send record says what it changed, file by file
        return remote_send_jjp.send_build(image, machine, log, progress, cancel)
    with open_target(image, log) as target:
        check_layout(target, machine.layout())
        check_test_card_target(target, machine, replace_menu_card)
        # PAD-1427 (David: "I'm concerned about letting the game run while we are doing updates and I want to make
        # sure we have a clean isolated update path"): the game is held, the machine's screen saying PAD is updating
        # it, before the Send reads or changes anything of the card - nothing of a Send runs beside a game
        log("Holding the machine's game for the Send (a game being played ends); its screen shows PAD updating it "
            "until the Send is done.", "info")
        machine.pause_game()
        try:
            if target.plan is not None:
                try:
                    return send(target.plan, machine, log, progress, cancel)
                except NotThisCard as e:
                    log(str(e).split(" Write the card")[0] + "; sending the whole image's differences instead.",
                        "info")
            if target.info.get("enabled"):
                from . import pad_ssh_key
                mine = pad_ssh_key.public_line().split()
                if len(mine) < 2 or mine[1] not in target.info.get("public_keys", ""):
                    raise SendError("This image's remote access doesn't let this computer in, so after it the "
                                    "machine couldn't be reached from here again. Build it with Remote access on, "
                                    "on this computer.")
            return sync(target, machine, log, progress, cancel)
        except BaseException:
            # refused before anything changed: the game back (a Send that stopped part way has said so already)
            with contextlib.suppress(Exception):
                machine.screen_stopped(False)
            raise


# ===================================================================== the app's run
from .pipeline_base import BasePipeline, PipelineError  # noqa: E402


#: PAD-1433: a Send's own chips in the status bar (it used to borrow the Write build's, and never moved them)
SEND_PHASES = ("Connect", "Compare", "Send", "Finish")
#: the word a Send's progress starts with -> its chip
_PHASE_OF = (("Comparing", 1), ("Updating", 2), ("Uploading", 2), ("Writing", 2), ("Finishing", 3))


class SendPipeline(BasePipeline):
    """A Send as one of the app's runs: its log, its progress bar, its Cancel (the Write tab's)."""

    def __init__(self, image, address, log_cb, phase_cb, progress_cb, done_cb, connect_fn=None, backup_keep=None,
                 replace_menu_card=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.image, self.address = image, address
        self.replace_menu_card = bool(replace_menu_card)
        # PAD-1588: the machine's settings backed up before anything is sent (None: the owner turned that off)
        self.backup_keep = backup_keep
        self._connect = connect_fn or connect
        self._phase_now = -1
        self._rate = []

    def _to_phase(self, index):
        if index != self._phase_now:
            self._phase_now = index
            self._rate = []
            self._set_phase(index)

    def _send_progress(self, done, total, what=""):
        """The bar, its chip, and (PAD-1433) for the bytes going to the machine the rate and the time left: over a
        machine's Wi-Fi a big Send takes hours, and the user should see that, not a crawling bar."""
        for word, index in _PHASE_OF:
            if what.startswith(word):
                self._to_phase(index)
                break
        if self._phase_now == 2 and total:
            from .rawdevice import _rate_note
            what = "Sending %s of %s%s" % (_human(done), _human(total), _rate_note(self._rate, done, total))
        self._progress(int(done * 100 / total) if total else 0, 100, what)

    def _run(self):
        self._to_phase(0)
        self._log("Sending %s to the machine at %s..." % (os.path.basename(self.image), self.address), "info")
        try:
            machine = self._connect(self.address)
        except SendError as e:
            raise PipelineError("Connect", str(e)) from None
        machine.log, machine.cancel = self._log, (lambda: self._cancelled)    # PAD-1436: a reconnect says so
        try:
            if self.backup_keep:
                from . import machine_backups
                machine_backups.before_send(machine, self.backup_keep, self._log)
            if hasattr(machine, "widen"):
                machine.widen(self._log)
            # only when set: a test card replacing a PAD multi-boot card (the Test card tab asked)
            more = {"replace_menu_card": True} if self.replace_menu_card else {}
            summary = send_image(self.image, machine, self._log, self._send_progress, lambda: self._cancelled,
                                 **more)
        except SendError as e:
            raise PipelineError("Send", str(e)) from None
        finally:
            machine.close()
        self._log(summary, "success")
        self._done(True, summary)
