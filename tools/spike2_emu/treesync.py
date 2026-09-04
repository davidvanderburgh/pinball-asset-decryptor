#!/usr/bin/env python3
"""treesync - what is on a multi-boot card's games trees, and how to change ONLY what changed.

Item 93.  mkmulticard.py builds a multi-boot card by copying whole partitions; a one-file
change used to mean a rebuild.  This module is the record and the engine behind
`mkmulticard.py update`:

  * a MANIFEST of a games tree - every file's sha256, size, mode, owner and mtime, every
    symlink's target, every directory's mode - computed by hashing the tree through the
    pure-Python ext4 reader (1 MiB reads along each file's extents, holes and unwritten
    extents as zeros, exactly what a mounted filesystem serves).  Metadata is never taken
    for identity: two cards were found with files identical in path, size and mtime and
    different in content (an in-place edit that left the inode alone);
  * a host-side CACHE of source manifests keyed by the card file's size + mtime + the
    partition's UUID, so a source that did not change is never hashed twice (and a source
    that changed while it was being hashed is thrown away, not cached);
  * the card's record, trees.json (kept on p2 beside build.json by mkmulticard): the
    manifest of every tree on the card, the stamp of the source it came from, which
    partitions have been written in place, and a DIRTY flag while an update runs;
  * the DIFF between the recorded tree and a source's, the ROOM an update needs (counting
    the moment a replacement's temporary file coexists with the file it replaces), and
    the executor that applies it through a FsOps - the mounted partition for real, an
    in-memory filesystem in the tests - with every write tmp + rename, removals of whole
    trees first, file removals last, and every step idempotent so a re-run converges.

Nothing here mounts, needs root, or knows a partition table: mkmulticard.py owns the
loop mount, the p2 record and the CLI.  Everything here runs on Windows in the tests.
"""
import collections
import errno
import hashlib
import json
import os
import re
import sys
import tempfile
import time

TREES_NAME = "trees.json"            # the card's record, on p2 beside build.json
TREES_FORMAT = 1
CACHE_DIRNAME = "pinball_spike2_multiboot"
CACHE_ENV = "MULTIBOOT_CACHE"
HASH_CHUNK = 1 << 20                  # 1 MiB reads: fast on DrvFs, 8 MiB reads are not
ROOM_MARGIN = 64 << 20                # what an update keeps free after itself
TMP_MARK = ".tmp."                    # a file being written: <name>.tmp.<pid>
SKIP_ROOT = ("lost+found",)


class TreesError(Exception):
    """A manifest, cache or executor refusal, with the reason in words."""


# ============================================================================ the model
FileRec = collections.namedtuple("FileRec", "sha256 size mode uid gid mtime")
LinkRec = collections.namedtuple("LinkRec", "target uid gid")
DirRec = collections.namedtuple("DirRec", "mode uid gid")


def _perm(mode):
    """The permission bits alone (the section says the type)."""
    return int(mode) & 0o7777


class TreeManifest:
    """One games tree: {rel: FileRec}, {rel: LinkRec}, {rel: DirRec}, rel relative to the tree's
    root with no leading slash.  `inodes` (rel -> inode number, files only) is transient - a
    reader's handle back to the bytes, never written to JSON."""

    def __init__(self, files=None, symlinks=None, dirs=None):
        self.files = dict(files or {})
        self.symlinks = dict(symlinks or {})
        self.dirs = dict(dirs or {})
        self.inodes = {}

    def bytes(self):
        return sum(r.size for r in self.files.values())

    def count(self):
        return len(self.files) + len(self.symlinks) + len(self.dirs)

    def __eq__(self, other):
        return (isinstance(other, TreeManifest) and self.files == other.files
                and self.symlinks == other.symlinks and self.dirs == other.dirs)

    def to_dict(self):
        return {
            "files": {k: {"sha256": r.sha256, "size": r.size, "mode": "%04o" % r.mode, "uid": r.uid,
                          "gid": r.gid, "mtime": r.mtime} for k, r in sorted(self.files.items())},
            "symlinks": {k: {"target": r.target, "uid": r.uid, "gid": r.gid} for k, r in sorted(self.symlinks.items())},
            "dirs": {k: {"mode": "%04o" % r.mode, "uid": r.uid, "gid": r.gid} for k, r in sorted(self.dirs.items())},
        }

    @classmethod
    def from_dict(cls, d):
        try:
            files = {k: FileRec(v["sha256"], int(v["size"]), int(v["mode"], 8), int(v["uid"]), int(v["gid"]),
                                int(v["mtime"])) for k, v in d.get("files", {}).items()}
            links = {k: LinkRec(v["target"], int(v["uid"]), int(v["gid"])) for k, v in d.get("symlinks", {}).items()}
            dirs = {k: DirRec(int(v["mode"], 8), int(v["uid"]), int(v["gid"])) for k, v in d.get("dirs", {}).items()}
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise TreesError("a tree manifest is malformed: %s" % e)
        return cls(files, links, dirs)


class SourceManifest:
    """A TreeManifest plus where it came from: the card file's stamp, the partition's UUID,
    the subtree it describes ('' = the partition root), when it was hashed."""

    def __init__(self, tree, stamp, uuid, sub="", hashed=None, used_bytes=None):
        self.tree, self.stamp, self.uuid, self.sub = tree, dict(stamp), uuid, sub
        self.hashed = hashed or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.used_bytes = used_bytes

    def to_dict(self):
        d = {"format": TREES_FORMAT, "stamp": self.stamp, "uuid": self.uuid, "sub": self.sub,
             "hashed": self.hashed, "used_bytes": self.used_bytes}
        d.update(self.tree.to_dict())
        return d

    @classmethod
    def from_dict(cls, d):
        if d.get("format") != TREES_FORMAT:
            raise TreesError("cached manifest format %r is not %d" % (d.get("format"), TREES_FORMAT))
        return cls(TreeManifest.from_dict(d), d["stamp"], d["uuid"], d.get("sub", ""), d.get("hashed"),
                   d.get("used_bytes"))


class ImageTrees:
    """One image as the card records it."""

    def __init__(self, index, device, sub, tree, stamp=None, uuid=None, bypass=None):
        self.index, self.device, self.sub, self.tree = index, device, sub, tree
        self.stamp = dict(stamp) if stamp else None
        self.uuid = uuid
        self.bypass = dict(bypass) if bypass else None       # {"game": sha, "sidx": sha} after a bypass

    def to_dict(self):
        d = {"index": self.index, "device": self.device, "tree": self.sub, "source": self.stamp,
             "uuid": self.uuid, "bytes": self.tree.bytes(), "bypass": self.bypass}
        d.update(self.tree.to_dict())
        return d

    @classmethod
    def from_dict(cls, d):
        try:
            return cls(int(d["index"]), d["device"], d.get("tree", ""), TreeManifest.from_dict(d),
                       d.get("source"), d.get("uuid"), d.get("bypass"))
        except (KeyError, TypeError, ValueError) as e:
            raise TreesError("trees.json image entry is malformed: %s" % e)


class CardTrees:
    """trees.json: every tree on the card, the primary's identity, what was synced, what is dirty."""

    def __init__(self, images, primary=None, synced=(), dirty=(), layout=None, tool="mkmulticard",
                 version=None, written=None):
        self.images = list(images)
        self.primary = dict(primary or {})       # {"p1_md5": ..., "p2_tree": ...}
        self.synced = sorted(set(int(n) for n in synced))
        self.dirty = sorted(set(int(n) for n in dirty))
        self.layout = layout
        self.tool, self.version = tool, version
        self.written = written or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def image(self, index):
        for im in self.images:
            if im.index == index:
                return im
        return None

    def to_json(self):
        d = {"format": TREES_FORMAT, "tool": self.tool, "version": self.version, "written": self.written,
             "layout": self.layout, "primary": self.primary, "synced": self.synced, "dirty": self.dirty,
             "images": [im.to_dict() for im in sorted(self.images, key=lambda i: i.index)]}
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json(cls, raw):
        try:
            d = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        except ValueError as e:
            raise TreesError("trees.json is not JSON: %s" % e)
        if not isinstance(d, dict) or d.get("format") != TREES_FORMAT:
            raise TreesError("trees.json format %r is not %d (a newer tool wrote it?)"
                             % (d.get("format") if isinstance(d, dict) else None, TREES_FORMAT))
        return cls([ImageTrees.from_dict(i) for i in d.get("images", [])], d.get("primary"), d.get("synced", ()),
                   d.get("dirty", ()), d.get("layout"), d.get("tool", "mkmulticard"), d.get("version"),
                   d.get("written"))


# ============================================================================ hashing a tree
class _NoProgress:
    def add(self, n):
        pass


def hash_inode(reader, node, progress=None):
    """sha256 of a regular file's content as a mount would serve it (holes, unwritten
    extents as zeros), read in 1 MiB pieces; `progress.add(n)` per piece."""
    h = hashlib.sha256()
    p = progress or _NoProgress()
    for _off, data in reader.read_file_chunks(node, chunk=HASH_CHUNK):
        h.update(data)
        p.add(len(data))
    return h.hexdigest()


def hash_tree(reader, root_ino=2, progress=None, skip=SKIP_ROOT):
    """Walk + hash the tree under `root_ino` -> TreeManifest (inodes kept for the files).
    A special file (device, fifo, socket) is refused by name: a games tree has none, and a
    manifest that skipped one would lie."""
    man = TreeManifest()
    for rel, kind, ino, node in reader.iter_tree(root_ino, skip=skip):
        if kind == "file":
            man.files[rel] = FileRec(hash_inode(reader, node, progress), node["size"], _perm(node["mode"]),
                                     node["uid"], node["gid"], node["mtime"])
            man.inodes[rel] = ino
        elif kind == "symlink":
            man.symlinks[rel] = LinkRec(reader.read_symlink(node), node["uid"], node["gid"])
        elif kind == "dir":
            man.dirs[rel] = DirRec(_perm(node["mode"]), node["uid"], node["gid"])
        else:
            raise TreesError("%s is a special file (mode %o); a games tree holds none and this record cannot hold one"
                             % (rel, node["mode"]))
    return man


def tree_bytes_budget(reader, root_ino=2, skip=SKIP_ROOT):
    """Sum of the regular files' sizes under `root_ino` - the meter's budget before a hash
    (a walk of the inodes only, no content read)."""
    return sum(node["size"] for _rel, kind, _ino, node in reader.iter_tree(root_ino, skip=skip) if kind == "file")


# ============================================================================ the host cache
def source_stamp(path):
    """{path, size, mtime_ns}: the identity of a card FILE for the cache (size + mtime, as
    cardmount.sh's cache key; the path is recorded for the reader, never compared)."""
    st = os.stat(path)
    return {"path": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def stamps_equal(a, b):
    return bool(a) and bool(b) and a.get("size") == b.get("size") and a.get("mtime_ns") == b.get("mtime_ns")


def stamp_key(stamp, uuid, sub=""):
    k = "%d-%d-%s" % (int(stamp["size"]), int(stamp["mtime_ns"]), (uuid or "")[:16])
    return k + ("-" + re.sub(r"[^A-Za-z0-9_.-]", "_", sub) if sub else "")


def cache_dir_candidates(extra=None):
    """Where cached manifests may be: --cache-dir / $MULTIBOOT_CACHE first, then every
    Windows user's %TEMP% seen from WSL (the app's own params cache lives beside it), then
    this process's temp dir.  Never under $HOME: the tool runs as root for a write and as the
    user for a read, and each would then have a cache the other cannot use."""
    out = []
    if extra:
        out.append(extra)
    if os.environ.get(CACHE_ENV):
        out.append(os.environ[CACHE_ENV])
    users = "/mnt/c/Users"
    if os.path.isdir(users):
        for u in sorted(os.listdir(users)):
            if u.lower() in ("public", "default", "default user", "all users") or u.startswith("."):
                continue
            d = os.path.join(users, u, "AppData", "Local", "Temp", CACHE_DIRNAME)
            if os.path.isdir(d):
                out.append(d)
    out.append(os.path.join(tempfile.gettempdir(), CACHE_DIRNAME))
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def cache_dir_for_write(extra=None):
    """Where a new manifest goes: the directory ASKED FOR (--cache-dir, $MULTIBOOT_CACHE),
    created if need be - an explicit choice is never passed over for a directory that merely
    exists - else the first candidate that exists, else the first candidate, created."""
    asked = extra or os.environ.get(CACHE_ENV)
    if asked:
        os.makedirs(asked, exist_ok=True)
        return asked
    cands = cache_dir_candidates(extra)
    for d in cands:
        if os.path.isdir(d):
            return d
    os.makedirs(cands[0], exist_ok=True)
    return cands[0]


def load_cached(stamp, uuid, sub="", cache_dir=None):
    """The cached SourceManifest for this stamp + uuid (+ subtree), or None.  A file that
    does not parse, or disagrees on format or uuid, is ignored - never trusted."""
    name = stamp_key(stamp, uuid, sub) + ".json"
    for d in cache_dir_candidates(cache_dir):
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                man = SourceManifest.from_dict(json.loads(f.read().decode("utf-8")))
        except (OSError, ValueError, TreesError):
            continue
        if man.uuid != uuid or not stamps_equal(man.stamp, stamp) or man.sub != sub:
            continue
        return man
    return None


def store_cached(man, cache_dir=None):
    """Write the manifest into the cache (tmp + rename) -> its path."""
    d = cache_dir_for_write(cache_dir)
    p = os.path.join(d, stamp_key(man.stamp, man.uuid, man.sub) + ".json")
    tmp = p + TMP_MARK + str(os.getpid())
    with open(tmp, "wb") as f:
        f.write(json.dumps(man.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8"))
    os.replace(tmp, p)
    return p


def source_manifest(path, part_offset, part_size, root_ino=2, sub="", cache_dir=None, progress=None,
                    force=False, reader_factory=None):
    """The manifest of the games tree at `root_ino` inside the ext4 at `part_offset` of the
    card file `path`: from the cache when the file's stamp + the partition's UUID match,
    else hashed now and cached.  The stamp is taken BEFORE the hash and checked AFTER it:
    a card being written while it is read is discarded (TreesError), never cached.
    -> (SourceManifest, "cached" | "hashed")"""
    from pinball_decryptor.plugins.stern import ext4 as _ext4    # lazy: the pure parts need no app
    factory = reader_factory or (lambda f: _ext4.Ext4Reader(f, part_offset, part_size))
    before = source_stamp(path)
    with open(path, "rb") as f:
        reader = factory(f)
        uuid = reader.uuid()
        if not force:
            hit = load_cached(before, uuid, sub, cache_dir)
            if hit is not None:
                return hit, "cached"
        tree = hash_tree(reader, root_ino, progress)
    after = source_stamp(path)
    if not stamps_equal(before, after):
        raise TreesError("%s changed while it was being read (size/mtime moved); run again when it is finished"
                         % path)
    man = SourceManifest(tree, before, uuid, sub)
    try:
        store_cached(man, cache_dir)
    except OSError:
        pass                                    # a cache is a convenience, never a refusal
    return man, "hashed"


# ============================================================================ the diff
Change = collections.namedtuple("Change", "op rel size")
# ops, in the order the executor applies them:
#   mkdir      a directory to create (shallow first)
#   write      a file to write (new, or replacing what is there) - tmp + rename
#   symlink    a symlink to create or re-point (unlink + symlink)
#   attr_dir   a directory whose mode/uid/gid moved
#   unlink     a file to remove
#   unsymlink  a symlink to remove
#   rmdir      a directory to remove (deep first)


def _depth(rel):
    return rel.count("/")


def diff_tree(old, new):
    """The changes that turn tree `old` (None = nothing there yet) into tree `new`, in
    application order.  A file is rewritten when its sha256, size, mode, uid or gid differ;
    an mtime alone moves nothing (metadata is not identity, and a card's mtimes are the
    first writer's).  A path that changes KIND is removed and created."""
    old = old or TreeManifest()
    ch = []
    o_kind = {}
    for k in old.files:
        o_kind[k] = "file"
    for k in old.symlinks:
        o_kind[k] = "symlink"
    for k in old.dirs:
        o_kind[k] = "dir"
    n_kind = {}
    for k in new.files:
        n_kind[k] = "file"
    for k in new.symlinks:
        n_kind[k] = "symlink"
    for k in new.dirs:
        n_kind[k] = "dir"
    # removals of anything whose kind changed happen before the creations (same path)
    kind_changed = {k for k in n_kind if k in o_kind and o_kind[k] != n_kind[k]}
    for rel in sorted(new.dirs, key=_depth):
        if rel not in old.dirs or rel in kind_changed:
            if rel in kind_changed:
                ch.append(Change({"file": "unlink", "symlink": "unsymlink"}[o_kind[rel]], rel, 0))
            ch.append(Change("mkdir", rel, 0))
        elif old.dirs[rel] != new.dirs[rel]:
            ch.append(Change("attr_dir", rel, 0))
    for rel in sorted(new.files):
        r = new.files[rel]
        if rel in kind_changed:
            ch.append(Change({"symlink": "unsymlink", "dir": "rmdir"}[o_kind[rel]], rel, 0))
            ch.append(Change("write", rel, r.size))
        elif rel not in old.files or old.files[rel][:5] != r[:5]:
            ch.append(Change("write", rel, r.size))
    for rel in sorted(new.symlinks):
        if rel in kind_changed:
            ch.append(Change({"file": "unlink", "dir": "rmdir"}[o_kind[rel]], rel, 0))
            ch.append(Change("symlink", rel, 0))
        elif rel not in old.symlinks or old.symlinks[rel] != new.symlinks[rel]:
            ch.append(Change("symlink", rel, 0))
    for rel in sorted(old.files):
        if rel not in n_kind:
            ch.append(Change("unlink", rel, old.files[rel].size))
    for rel in sorted(old.symlinks):
        if rel not in n_kind:
            ch.append(Change("unsymlink", rel, 0))
    for rel in sorted(old.dirs, key=_depth, reverse=True):
        if rel not in n_kind:
            ch.append(Change("rmdir", rel, 0))
    return ch


def room_needed(changes, old, new, margin=ROOM_MARGIN):
    """(need, peak): the bytes an update leaves the partition needing beyond what it frees,
    and the PEAK it demands while running - the largest replacement's new bytes coexist with
    the old inode until the rename, and nothing is freed before every write is done (adds
    before removals, so an interrupted update leaves every old file in place).
    Both include `margin`.  Compare `peak` with the partition's free bytes."""
    old = old or TreeManifest()
    adds = sum(c.size for c in changes if c.op == "write")
    freed = sum(old.files[c.rel].size for c in changes if c.op == "write" and c.rel in old.files)
    freed += sum(c.size for c in changes if c.op == "unlink")
    need = adds - freed + margin
    peak = adds + margin                        # every add lands before the first removal
    return need, max(need, peak)


# ============================================================================ trees on a card
TreeAction = collections.namedtuple("TreeAction", "index device old_sub new_sub action old_index")
# action: keep (same tree, same place), rename (same tree, moved), new (no tree yet), remove;
# old_index names the recorded image the request matched (None for new)


def match_trees(card, new_sources, subdir_for):
    """Match the requested image list to the trees the card records.  `new_sources` =
    [(index, device, stamp)] in the new order; `subdir_for(index) -> sub` names where
    image `index` lives ('' for the primary).  A recorded tree is matched by its source
    PATH first, then by an equal stamp (a copy at another path), else the image is new;
    recorded trees no request claims are removed.  Image 0 is always the primary (kept)."""
    used = set()
    out = []
    for index, device, stamp in new_sources:
        want = subdir_for(index)
        found = None
        if index == 0:
            found = card.image(0)
        else:
            for im in card.images:
                if im.index == 0 or im.index in used or not im.stamp:
                    continue
                if stamp and os.path.normcase(im.stamp.get("path", "")) == os.path.normcase(stamp.get("path", "")):
                    found = im
                    break
            if found is None:
                for im in card.images:
                    if im.index == 0 or im.index in used or not im.stamp:
                        continue
                    if stamps_equal(im.stamp, stamp):
                        found = im
                        break
            if found is None:
                # a tree recorded without a stamp (hashed off a card built before the record)
                # can only be matched by its position
                im = card.image(index)
                if im is not None and im.index not in used and not im.stamp:
                    found = im
        if found is None:
            out.append(TreeAction(index, device, None, want, "new", None))
        else:
            used.add(found.index)
            out.append(TreeAction(index, device, found.sub, want, "keep" if found.sub == want else "rename",
                                  found.index))
    for im in card.images:
        if im.index != 0 and im.index not in used:
            out.append(TreeAction(im.index, im.device, im.sub, None, "remove", im.index))
    return out


# ============================================================================ FsOps
class FsOps:
    """What the executor needs from a filesystem.  Paths are tree-relative (`rel`), rooted
    wherever the implementation says.  DirOps (mkmulticard) is os.* under a mountpoint;
    MemOps below is the tests' in-memory filesystem with inode numbers and link counts."""

    def lstat(self, rel):
        raise NotImplementedError

    def listdir(self, rel):
        raise NotImplementedError

    def mkdir(self, rel, mode, uid, gid):
        raise NotImplementedError

    def rmdir(self, rel):
        raise NotImplementedError

    def symlink(self, rel, target, uid, gid):
        raise NotImplementedError

    def unlink(self, rel):
        raise NotImplementedError

    def rename(self, a, b):
        raise NotImplementedError

    def write_stream(self, rel, chunks, mode, uid, gid, mtime):
        raise NotImplementedError

    def set_attrs(self, rel, mode=None, uid=None, gid=None):
        raise NotImplementedError

    def free_bytes(self):
        raise NotImplementedError

    def commit(self):
        pass

    # helpers every implementation gets for free
    def exists(self, rel):
        return self.lstat(rel) is not None

    def walk_files(self, rel=""):
        """Every regular file under `rel` (depth-first), for sweeps."""
        st = self.lstat(rel) if rel else {"kind": "dir"}
        if not st or st["kind"] != "dir":
            return
        for name in sorted(self.listdir(rel)):
            child = (rel + "/" + name) if rel else name
            cst = self.lstat(child)
            if cst is None:
                continue
            if cst["kind"] == "dir":
                yield from self.walk_files(child)
            elif cst["kind"] == "file":
                yield child, cst

    def rmtree(self, rel):
        st = self.lstat(rel)
        if st is None:
            return
        if st["kind"] == "dir":
            for name in list(self.listdir(rel)):
                self.rmtree(rel + "/" + name)
            self.rmdir(rel)
        else:
            self.unlink(rel)


class MemOps(FsOps):
    """An in-memory filesystem: {rel: entry} with inode numbers and link counts, a free-space
    budget that raises ENOSPC like a full partition, and an optional `abort_after` that
    raises after N mutating operations - the crash the executor must survive."""

    def __init__(self, free=1 << 40, abort_after=None):
        self.entries = {"": {"kind": "dir", "mode": 0o755, "uid": 0, "gid": 0, "ino": 2}}
        self.free = free
        self.next_ino = 3
        self.ops = 0
        self.abort_after = abort_after
        self.log = []

    def _tick(self, what):
        self.ops += 1
        self.log.append(what)
        if self.abort_after is not None and self.ops > self.abort_after:
            raise RuntimeError("simulated crash after %d operations (%s)" % (self.abort_after, what))

    def _parent(self, rel):
        return rel.rsplit("/", 1)[0] if "/" in rel else ""

    def lstat(self, rel):
        e = self.entries.get(rel)
        if e is None:
            return None
        out = dict(e)
        if e["kind"] == "file":
            out["size"] = len(e["data"])
            out["nlink"] = sum(1 for x in self.entries.values() if x.get("ino") == e["ino"])
        return out

    def listdir(self, rel):
        pre = rel + "/" if rel else ""
        return [k[len(pre):] for k in self.entries if k != rel and k.startswith(pre) and "/" not in k[len(pre):]]

    def mkdir(self, rel, mode, uid, gid):
        self._tick("mkdir " + rel)
        if rel in self.entries:
            raise OSError(errno.EEXIST, "exists", rel)
        if self._parent(rel) not in self.entries:
            raise OSError(errno.ENOENT, "no parent", rel)
        self.entries[rel] = {"kind": "dir", "mode": mode, "uid": uid, "gid": gid, "ino": self.next_ino}
        self.next_ino += 1

    def rmdir(self, rel):
        self._tick("rmdir " + rel)
        if self.listdir(rel):
            raise OSError(errno.ENOTEMPTY, "not empty", rel)
        del self.entries[rel]

    def symlink(self, rel, target, uid, gid):
        self._tick("symlink " + rel)
        if rel in self.entries:
            raise OSError(errno.EEXIST, "exists", rel)
        self.entries[rel] = {"kind": "symlink", "target": target, "uid": uid, "gid": gid, "mode": 0o777,
                             "ino": self.next_ino}
        self.next_ino += 1

    def unlink(self, rel):
        self._tick("unlink " + rel)
        e = self.entries.pop(rel)
        if e["kind"] == "file" and not any(x.get("ino") == e["ino"] for x in self.entries.values()):
            self.free += len(e["data"])

    def rename(self, a, b):
        """Move an entry - and, for a directory, everything under it (entries are keyed by
        their full path, so a directory rename re-keys the subtree)."""
        self._tick("rename %s -> %s" % (a, b))
        e = self.entries.pop(a)
        old = self.entries.pop(b, None)
        gone = old is not None and old["kind"] == "file"
        if gone and not any(x.get("ino") == old["ino"] for x in self.entries.values()):
            self.free += len(old["data"])
        self.entries[b] = e
        if e["kind"] == "dir":
            pre = a + "/"
            for k in [k for k in self.entries if k.startswith(pre)]:
                self.entries[b + "/" + k[len(pre):]] = self.entries.pop(k)

    def write_stream(self, rel, chunks, mode, uid, gid, mtime):
        self._tick("write " + rel)
        if self._parent(rel) not in self.entries:
            raise OSError(errno.ENOENT, "no parent", rel)
        data = bytearray()
        for c in chunks:
            if len(c) > self.free:
                # what was written so far stays, as it would on disk
                self.entries[rel] = {"kind": "file", "data": bytes(data), "mode": mode, "uid": uid, "gid": gid,
                                     "mtime": mtime, "ino": self.next_ino}
                self.next_ino += 1
                self.free -= len(data)
                raise OSError(errno.ENOSPC, "no space left on device", rel)
            data += c
            self.free -= len(c)
        self.entries[rel] = {"kind": "file", "data": bytes(data), "mode": mode, "uid": uid, "gid": gid,
                             "mtime": mtime, "ino": self.next_ino}
        self.next_ino += 1

    def set_attrs(self, rel, mode=None, uid=None, gid=None):
        self._tick("attrs " + rel)
        e = self.entries[rel]
        if mode is not None:
            e["mode"] = mode
        if uid is not None:
            e["uid"] = uid
        if gid is not None:
            e["gid"] = gid

    def free_bytes(self):
        return self.free

    # the tests' view
    def read(self, rel):
        return self.entries[rel]["data"]

    def manifest(self, prefix=""):
        """The tree under `prefix` as a TreeManifest (what a verify would record)."""
        man = TreeManifest()
        pre = prefix + "/" if prefix else ""
        for k, e in self.entries.items():
            if k == prefix or (pre and not k.startswith(pre)) or (not pre and k == ""):
                continue
            rel = k[len(pre):]
            if rel.split("/")[-1].find(TMP_MARK) >= 0:
                continue
            if e["kind"] == "file":
                man.files[rel] = FileRec(hashlib.sha256(e["data"]).hexdigest(), len(e["data"]), e["mode"], e["uid"],
                                         e["gid"], e["mtime"])
            elif e["kind"] == "symlink":
                man.symlinks[rel] = LinkRec(e["target"], e["uid"], e["gid"])
            else:
                man.dirs[rel] = DirRec(e["mode"], e["uid"], e["gid"])
        return man


class MemSource:
    """The tests' source of bytes for a MemOps run: {rel: bytes} behind a TreeManifest."""

    def __init__(self, data):
        self.data = dict(data)

    def chunks(self, rel):
        b = self.data[rel]
        for i in range(0, max(len(b), 1), HASH_CHUNK):
            yield b[i:i + HASH_CHUNK]
        if not b:
            yield b""


class ReaderSource:
    """The bytes of a source tree through an Ext4Reader + the manifest's inode map."""

    def __init__(self, reader, manifest):
        self.reader, self.manifest = reader, manifest

    def chunks(self, rel):
        node = self.reader.read_inode(self.manifest.inodes[rel])
        for _off, data in self.reader.read_file_chunks(node, chunk=HASH_CHUNK):
            yield data


def mem_source_from(files):
    """{rel: (bytes, mode, uid, gid, mtime)} -> (TreeManifest, MemSource) for the tests."""
    man = TreeManifest()
    data = {}
    for rel, spec in files.items():
        if isinstance(spec, tuple) and spec and spec[0] == "symlink":
            _s, target = spec[:2]
            man.symlinks[rel] = LinkRec(target, 0, 0)
            continue
        if isinstance(spec, tuple) and spec and spec[0] == "dir":
            man.dirs[rel] = DirRec(spec[1] if len(spec) > 1 else 0o755, 0, 0)
            continue
        if isinstance(spec, tuple):
            b, mode, uid, gid, mtime = (spec + (0o644, 0, 0, 1_700_000_000))[:5]
        else:
            b, mode, uid, gid, mtime = spec, 0o644, 0, 0, 1_700_000_000
        man.files[rel] = FileRec(hashlib.sha256(b).hexdigest(), len(b), mode, uid, gid, mtime)
        data[rel] = b
    for rel in list(man.files) + list(man.symlinks):
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            man.dirs.setdefault(d, DirRec(0o755, 0, 0))
    return man, MemSource(data)


# ============================================================================ the executor
def _join(prefix, rel):
    return (prefix + "/" + rel) if prefix and rel else (prefix or rel)


def tmp_name(rel):
    return rel + TMP_MARK + str(os.getpid())


def is_tmp(name):
    return TMP_MARK in name.rsplit("/", 1)[-1]


def sweep_tmp(ops, prefix=""):
    """Remove every `<name>.tmp.<pid>` under `prefix` - a write an earlier run did not finish."""
    n = 0
    for rel, _st in list(ops.walk_files(prefix)):
        if is_tmp(rel):
            ops.unlink(rel)
            n += 1
    return n


def apply_changes(ops, prefix, changes, new, source, progress=None):
    """Apply `changes` (diff_tree's order) to the tree at `prefix` on `ops`, taking bytes
    from `source.chunks(rel)`.  Every write is tmp + rename; nothing is removed before
    every add is done; every step is idempotent (a re-run after a crash converges).
    -> {"written": n, "bytes": n, "removed": n}."""
    p = progress or _NoProgress()
    stats = {"written": 0, "bytes": 0, "removed": 0}
    pending_removals = []
    for c in changes:
        rel = _join(prefix, c.rel)
        if c.op == "mkdir":
            st = ops.lstat(rel)
            d = new.dirs[c.rel]
            if st is None:
                ops.mkdir(rel, d.mode, d.uid, d.gid)
            elif st["kind"] != "dir":
                ops.unlink(rel)
                ops.mkdir(rel, d.mode, d.uid, d.gid)
            elif (st["mode"] & 0o7777, st["uid"], st["gid"]) != (d.mode, d.uid, d.gid):
                ops.set_attrs(rel, d.mode, d.uid, d.gid)
        elif c.op == "attr_dir":
            d = new.dirs[c.rel]
            ops.set_attrs(rel, d.mode, d.uid, d.gid)
        elif c.op == "write":
            r = new.files[c.rel]
            st = ops.lstat(rel)
            if st is not None and st["kind"] == "dir":
                ops.rmtree(rel)
            tmp = tmp_name(rel)
            if ops.exists(tmp):
                ops.unlink(tmp)
            ops.write_stream(tmp, _metered(source.chunks(c.rel), p), r.mode, r.uid, r.gid, r.mtime)
            ops.rename(tmp, rel)
            stats["written"] += 1
            stats["bytes"] += r.size
        elif c.op == "symlink":
            r = new.symlinks[c.rel]
            st = ops.lstat(rel)
            if st is not None:
                same = st["kind"] == "symlink" and st.get("target") == r.target
                if same and st["uid"] == r.uid and st["gid"] == r.gid:
                    continue
                ops.rmtree(rel) if st["kind"] == "dir" else ops.unlink(rel)
            ops.symlink(rel, r.target, r.uid, r.gid)
        elif c.op in ("unlink", "unsymlink", "rmdir"):
            pending_removals.append(c)
        else:
            raise TreesError("unknown change %r" % (c,))
    for c in pending_removals:                    # removals last, in diff order (files, links, dirs deep-first)
        rel = _join(prefix, c.rel)
        st = ops.lstat(rel)
        if st is None:
            continue
        if c.op == "rmdir":
            if st["kind"] == "dir":
                ops.rmdir(rel)
            else:
                ops.unlink(rel)
        else:
            ops.rmtree(rel) if st["kind"] == "dir" else ops.unlink(rel)
        stats["removed"] += 1
    return stats


def _metered(chunks, progress):
    for c in chunks:
        progress.add(len(c))
        yield c


def apply_tree_actions(ops, actions, tmp_tag=None):
    """Whole-tree moves for the multi layout, BEFORE any file change: removed trees go first
    (they free room and nothing needs them), then renames in two phases (`imgK` ->
    `.rename.<tag>.K` -> new name) so a permutation never collides.  New trees are created
    empty (their contents are a diff against nothing).  -> [(action, old, new)] done."""
    tag = tmp_tag or str(os.getpid())
    done = []
    for a in actions:
        if a.action == "remove" and a.old_sub:
            ops.rmtree(a.old_sub)
            done.append(("remove", a.old_sub, None))
    moves = [(a.old_sub, a.new_sub) for a in actions if a.action == "rename" and a.old_sub and a.new_sub]
    parked = []
    for old, new in moves:
        if ops.exists(old):
            park = ".rename.%s.%s" % (tag, old)
            ops.rename(old, park)
            parked.append((park, new, old))
    for park, new, old in parked:
        if ops.exists(new):
            ops.rmtree(new)
        ops.rename(park, new)
        done.append(("rename", old, new))
    for a in actions:
        if a.action == "new" and a.new_sub and not ops.exists(a.new_sub):
            ops.mkdir(a.new_sub, 0o755, 0, 0)
            done.append(("new", None, a.new_sub))
    return done


def sweep_parked(ops, tag=None):
    """Remove `.rename.*` leftovers of an interrupted move (their contents were re-synced)."""
    n = 0
    for name in list(ops.listdir("")):
        if name.startswith(".rename.") and (tag is None or name.startswith(".rename.%s." % tag)):
            ops.rmtree(name)
            n += 1
    return n


def _main(argv=None):
    print("treesync is a library; see mkmulticard.py update", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main())
