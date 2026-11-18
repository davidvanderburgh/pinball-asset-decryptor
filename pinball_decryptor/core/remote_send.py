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
import shlex
import stat
import threading
import time

GAMES = "/games"
ROOT = "/"
LEDGER = "/data/pad/remote_send.json"
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
class _Tree:
    """One partition of one image, walked: ``{machine path: (kind, inode, signature)}``."""

    def __init__(self, reader, mount):
        self.reader, self.mount = reader, mount
        self.entries = {}
        for rel, kind, _ino, node in reader.iter_tree():
            path = posixpath.join(mount, rel)
            self.entries[path] = (kind, node, self._sig(kind, node))

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
        self._it = iter(tree.chunks(node))
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
        fstab = trees[ROOT][0].get("/etc/fstab")
        text = trees[ROOT][0].reader.read_file_bytes(fstab[1]) if fstab else b""
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
  pad_tools || return 0
  if [ -z "$(pids_named boot_display)" ]; then
    # detached from this session (the card's busybox has no setsid): hangup ignored, so it outlives the login
    (trap '' HUP; exec "$BD") </dev/null >/dev/null 2>&1 &
    sleep 1
  fi
  "$DP" "$1" >/dev/null 2>&1
}
pad_resume() {
  touch $W/done
  for p in $(pids_named boot_display); do kill $p 2>/dev/null; done
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
g=$(pids_named game)
echo "$m" > $W/monitor
echo "$g" > $W/game
[ -n "$m" ] && kill -STOP $m
[ -n "$g" ] && kill -9 $g
sleep 1
pad_say @TEXT@
(trap '' HUP; exec /bin/sh $W/watch) </dev/null >/dev/null 2>&1 &
echo "PAD_SEND_PAUSED $m"
"""

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


class SshMachine(Machine):
    """A machine over remote access, logged in as root with this computer's key."""

    def __init__(self, host, port=22, timeout=15):
        import socket
        import paramiko
        from . import pad_ssh_key
        self.host, self.port = host, int(port)
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
            known = pad_ssh_key.host_key(host, self.port)
            mine = (key.get_name(), key.get_base64())
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
            self.t = t
            self.sftp = paramiko.SFTPClient.from_transport(t)
        except BaseException:
            t.close()
            raise

    def close(self):
        with contextlib.suppress(Exception):
            self.sftp.close()
        with contextlib.suppress(Exception):
            self.t.close()

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
        chan = self.t.open_session()
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
                if time.monotonic() > until:
                    chan.close()
                    raise SendError("The machine stopped answering; check it and Send again.")
                time.sleep(0.005)
        rc = chan.recv_exit_status()
        chan.close()
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
        self.sftp.putfo(fileobj, path, file_size=size, callback=callback, confirm=True)
        self.sftp.chown(path, uid, gid)
        self.sftp.chmod(path, mode)

    def commit(self, renames, links, deletes):
        lines = ["set -e"]
        for tmp, final in renames:
            lines.append("mv -f %s %s" % (_q(tmp), _q(final)))
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

    def write_ranges(self, path, ranges):
        with self.sftp.open(path, "r+b") as f:
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
        _rc, out = self.sh("readlink /games/game; cat /etc/hostname 2>/dev/null; "
                           "df -k /games | tail -n 1", check=False)
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
        self.sh("mkdir -p %s && mount -t ext4 -o ro /dev/mmcblk0p%d %s" % (_q(path), int(num), _q(path)))

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
            self.sftp.putfo(fileobj, tmp, file_size=size, confirm=True)
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

    def truncate(self, path, size):
        self.sftp.truncate(path, size)

    def set_attrs(self, path, mode, uid, gid):
        self.sftp.chown(path, uid, gid)
        self.sftp.chmod(path, mode)

    def copy(self, src, dst):
        self.sh("rm -f %s && cp -p %s %s" % (_q(dst), _q(src), _q(dst)), timeout=7200)

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
        self._screen["what"] = {"Uploading": "RECEIVING", "Updating": "UPDATING",
                                "Comparing": "CHECKING"}.get(what, "WORKING")

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
    state = machine.state([op.path for op in ops if op.kind != "patch"])
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
        for op in puts:
            check()
            cur = getattr(op, "cur", None)
            if tight and op.mount == GAMES and cur and cur[0] == "file":
                if not changed:
                    machine.screen_changing()
                    changed = True
                log("Updating %s in place (only the parts that differ)..." % op.path, "info")
                delta_put(machine, plan.trees[op.mount][0], op, cancel)
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
        self._it, self._buf, self._at = iter(chunks), b"", 0

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


def delta_put(machine, tree, op, cancel=None, at=None):
    """Make the machine's existing copy of ``op.path`` (or the copy of it at *at*) the build's file by writing
    only the blocks that differ, in place.  Only with the game stopped (it would read a half-changed file), and
    never on the system partition itself (:func:`delta_replace`).  Returns the bytes written."""
    path = at or op.path
    size, theirs = machine.block_hashes(path)
    sent, batch = 0, []
    for off, block in _blocks(tree, op.node):
        i = off // DELTA_BLOCK
        if i < len(theirs) and theirs[i] == hashlib.sha1(block).hexdigest():
            continue
        batch.append((off, block))
        sent += len(block)
        if len(batch) >= 16:
            machine.write_ranges(path, batch)
            batch = []
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


def delta_replace(machine, tree, op, cancel=None):
    """:func:`delta_put` for a system-partition file: the remote access session runs on those (busybox is the
    shell and every tool a Send uses; the server and libc too), and a program changed under its running copy
    breaks, as a file cut off half-written would on the next boot.  So the machine copies the file beside
    itself, the differing blocks go into the copy, and it is renamed over the original: running programs keep
    the old one until the machine restarts, and the file is always either old or new.  Returns the bytes
    written."""
    tmp = posixpath.join(posixpath.dirname(op.path), "." + posixpath.basename(op.path) + TMP_TAG)
    machine.copy(op.path, tmp)
    try:
        sent = delta_put(machine, tree, op, cancel, at=tmp)
        machine.commit([(tmp, op.path)], [], [])
    except BaseException:
        with contextlib.suppress(Exception):
            machine.remove([tmp])
        raise
    return sent


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
                        % (info.get("reason") or "not recognised"))
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
            fstab = trees[ROOT].get("/etc/fstab")
            text = trees[ROOT].reader.read_file_bytes(fstab[1]) if fstab else b""
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


def check_layout(target, machine_layout):
    """Refuse an image whose partitions don't sit where the machine's do: those need the card written."""
    bad = []
    for num, (start, sectors, ptype) in sorted(target.layout.items()):
        have = machine_layout.get(num)
        if have is None:
            bad.append("partition %d is missing" % num)
        elif have[0] != start or (ptype not in EXTENDED_TYPES and have[1] != sectors):
            bad.append("partition %d is placed or sized differently" % num)
    extra = sorted(set(machine_layout) - set(target.layout))
    if extra:
        bad.append("the machine has partition%s %s that the image doesn't"
                   % ("s" if len(extra) > 1 else "", ", ".join(map(str, extra))))
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


def sync_ops(tree, mine, prefix, protected, own_mounts, hashes_on_machine, log=None, progress=None):
    """The ops that make the machine's files under *prefix* (*mine*: its walk) the image's *tree*.  A file the
    same size on both is compared by sha1 (``hashes_on_machine(paths)``), so an unchanged file is never sent."""
    ops, same_size = [], []
    for path, (kind, node, _sig) in sorted(tree.entries.items()):
        if any(path == m or path.startswith(m + "/") for m in own_mounts if m != prefix):
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
        theirs = hashes_on_machine([p for p, _n, _o in same_size])
        for i, (path, node, own) in enumerate(same_size):
            if progress:
                progress(i, len(same_size), "Comparing")
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
    log("Comparing everything on the machine with %s (the image isn't a build of the card the machine runs, so "
        "this reads every file it may need to change: a few minutes)." % os.path.basename(target.path), "info")
    mounted, rw, all_ops, temps, walks = [], [], {}, [], {}
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
            ops = sync_ops(tree, mine, mount, protected, skip, machine.file_sha1s, log, progress)
            if ops:
                all_ops[mount] = ops
        raws = {}
        for num in sorted(target.raw):
            check()
            want = target.raw_sha1(num)
            if machine.raw_sha1(num) != want:
                raws[num] = want
        n = sum(len(v) for v in all_ops.values())
        if not n and not raws:
            log("The machine already has everything on this image; nothing to send. Its game starts again.",
                "success")
            if machine.game_held():
                machine.resume_game(screen_text("NOTHING TO", "UPDATE", "RESTARTING GAME"))
            return "The machine already has this image."
        puts = [op for ops in all_ops.values() for op in ops if op.kind == "put"]
        total = sum(op.size for op in puts) or 1
        log("Sending %d change(s): %d file(s) (%s), %d link(s), %d removal(s)%s."
            % (n, len(puts), _human(sum(op.size for op in puts)),
               sum(op.kind == "link" for v in all_ops.values() for op in v),
               sum(op.kind == "delete" for v in all_ops.values() for op in v),
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
            for op in (o for o in ops if o.kind == "put"):
                check()
                have = walks[mount].get(op.path)
                if have is not None and have[0] == "file":
                    # the machine has a copy: only its changed blocks go (the game is stopped; a cut-off Send is
                    # finished by the next one, which compares everything again).  Game files change in place;
                    # system files in a copy renamed over them (delta_replace: the session runs on those)
                    log("Updating %s (%s; only the parts that differ are sent)..." % (op.path, _human(op.size)),
                        "info")
                    delta_bytes += (delta_replace if mount == ROOT else delta_put)(machine, tree, op, cancel)
                    sent += op.size
                    progress(sent, total, "Updating")
                    continue
                tmp = posixpath.join(posixpath.dirname(op.path), "." + posixpath.basename(op.path) + TMP_TAG)
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
            if dels and mount == ROOT:
                machine.commit([], [], dels)
        for num, want in raws.items():
            check()
            log("Writing the boot partition (%s)..." % _human(target.raw[num][1]), "info")
            machine.raw_write(num, _RawFile(target.raw_chunks(num)), target.raw[num][1], want)
        machine.sync()
        rec = target.plan.record() if target.plan is not None else {"paths": [], "ranges": {}}
        machine.write_ledger(dict(rec, card=target.card_id, pending=False))
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


def send_image(image, machine, log=None, progress=None, cancel=None):
    """Send *image* to *machine*: the quick Send when it is a build of the card the machine runs, else the full
    one.  Returns a summary line."""
    log = log or (lambda *a, **k: None)
    with open_target(image, log) as target:
        check_layout(target, machine.layout())
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


class SendPipeline(BasePipeline):
    """A Send as one of the app's runs: its log, its progress bar, its Cancel (the Write tab's)."""

    def __init__(self, image, address, log_cb, phase_cb, progress_cb, done_cb, connect_fn=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.image, self.address = image, address
        self._connect = connect_fn or connect

    def _run(self):
        self._log("Sending %s to the machine at %s..." % (os.path.basename(self.image), self.address), "info")
        try:
            machine = self._connect(self.address)
        except SendError as e:
            raise PipelineError("Connect", str(e)) from None
        try:
            summary = send_image(self.image, machine, self._log,
                                 lambda done, total, what="": self._progress(
                                     int(done * 100 / total) if total else 0, 100, what),
                                 lambda: self._cancelled)
        except SendError as e:
            raise PipelineError("Send", str(e)) from None
        finally:
            machine.close()
        self._log(summary, "success")
        self._done(True, summary)
