#!/usr/bin/env python3
"""s3store.py - the Spike 3 card store: a decrypted, de-duplicated copy of only
what a Stern Spike 3 SD card actually holds (PAD-1090).

    s3store.py build  CARD.raw [--key K] [--store DIR]   # root: put a card in
    s3store.py path   CARD.raw [--store DIR]             # its tree, if it is in
    s3store.py status [--store DIR] [--json]             # what the store holds
    s3store.py remove CARD-ID [--store DIR]              # take a card out (+ gc)
    s3store.py gc     [--store DIR]                      # drop unreferenced objects

WHY NOT A COPY OF THE CARD. A Spike 3 image is 62 GB (a 64 GB SD card) and every
data partition on it is LUKS2/AES-XTS. Of those 62 GB a card USES about 4: on
pokemon_le 0.82.0 the rootfs holds 0.27 GB of a 0.58 GB partition, the games
partition 3.1 of 35 GB, connectivity 0.6 of 26 GB, data nothing at all. The
Spike 2 rig copies the whole card into the card cache (cardmount.sh) because
reading the original over 9p is slow; for Spike 3 that would be 62 GB a card of
mostly encrypted zeros, and the ciphertext cannot be compressed or shared.

WHAT IT KEEPS INSTEAD. The kernel opens each LUKS partition READ-ONLY straight
off the original image (losetup -r + cryptsetup open --readonly, the card's own
OTP keyfile; dm-crypt does the AES), the plaintext ext4 is mounted ro,noload,
and every regular file goes into a content-addressed object store:

    <store>/objects/ab/<sha256>-<mode>-<uid>-<gid>   one copy of each file
    <store>/cards/<card-id>/<role>/...               the card's tree: hardlinks
    <store>/cards/<card-id>/manifest.json            what it took, written last

The key carries the mode and owner because a hardlink shares them; two files
with the same bytes and different permissions are two objects. Directories,
symlinks and device nodes are recreated in the tree (they cost an inode, not
data). So:

  * only USED data is ever written - never a free block, never ciphertext;
  * a file two cards share is stored ONCE: the rootfs of two cards on the same
    OS build, the assets two versions of one title carry unchanged, the LE and
    the Pro of the same game. `status` says what that saved;
  * the original image is never written (losetup -r, --readonly, ro,noload),
    and the store holds plaintext, so it is as private as the keyfile: it sits
    on David's own Linux disk, never in the repo and never on the card.

A run never writes the store either: s3run.sh lays a per-slot overlay over the
tree, so the game's NVRAM/settings land in the slot and the next run of the same
card starts from the card's own state again.

THE KEY. Never in this repo. Resolved, first that works: --key (a 32-byte file
or 64 hex chars); $PAD_SPIKE3_OTP_KEY (likewise); the `otp_keyfile` of the
padkeys.json the extractor uses ($PAD_SPIKE3_KEYFILE, <image>.padkeys.json, or
padkeys.json beside the image - spike3_keys.Spike3KeySource's order). It goes to
cryptsetup on stdin and is never written anywhere. A Windows path in a keyfile
(C:/...) is read as /mnt/c/....

Builds take a lock on the store, so two at once queue rather than race (the
same one-card-at-a-time rule the Spike 2 cache copies follow).
"""
import argparse
import errno
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "spike2_emu"))
import parts as _parts  # noqa: E402  (the one MBR/EBR prober)

SECTOR = 512
LUKS_MAGIC = b"LUKS\xba\xbe"
#: role of a partition by its index on the card - spike3.py's _ROLE_BY_INDEX
ROLE_BY_INDEX = {2: "rootfs", 3: "data", 5: "connectivity", 6: "games"}
STORE_FORMAT = 1
CHUNK = 4 << 20
ZERO = bytes(CHUNK)
#: bump when the way a tree is laid out changes, so an old tree is rebuilt
TREE_REV = 1


# --------------------------------------------------------------------------
# where things are
# --------------------------------------------------------------------------
def default_store():
    """The shared card store's disk (PAD-651) when it is mounted, else the
    distro's own home - the same choice padpath.sh makes for the card cache."""
    env = os.environ.get("PAD_SPIKE3_STORE")
    if env:
        return env
    if os.path.isdir("/mnt/wsl/cards/cardcache") and os.path.ismount("/mnt/wsl/cards"):
        return "/mnt/wsl/cards/spike3"
    # a store already made under the user's home (cardcache, as the Spike 2
    # card cache) stays where it is; a new one goes with the rest of the
    # Spike 3 rig, which runs as root ($PAD_S3_HOME, /var/lib/pad-s3)
    home = os.environ.get("PAD_HOME") or os.environ.get("HOME") or "/root"
    legacy = os.path.join(home, "cardcache", "spike3")
    if os.path.isdir(os.path.join(legacy, "cards")):
        return legacy
    return os.path.join(os.environ.get("PAD_S3_HOME") or "/var/lib/pad-s3", "store")


def win_to_wsl(p):
    """``C:/x`` or ``C:\\x`` -> ``/mnt/c/x``; anything else unchanged."""
    if isinstance(p, str) and len(p) > 2 and p[1] == ":" and p[0].isalpha():
        return "/mnt/%s/%s" % (p[0].lower(), p[2:].replace("\\", "/").lstrip("/"))
    return p


# --------------------------------------------------------------------------
# the card: partitions and identity
# --------------------------------------------------------------------------
def card_partitions(img):
    """[(index, role, start_lba, sectors, is_luks)] for every Linux partition."""
    rows = _parts.table(img) + [(i, t, s, c) for i, t, s, c, _e in _parts.logical(img)]
    out = []
    with open(img, "rb") as f:
        for idx, ptype, start, count in rows:
            if ptype not in _parts.LINUX_TYPES:
                continue
            f.seek(start * SECTOR)
            luks = f.read(6) == LUKS_MAGIC
            out.append((idx, ROLE_BY_INDEX.get(idx, "p%d" % idx), start, count, luks))
    return out


def luks_uuid(img, start_lba):
    """The LUKS2 header's uuid (40 bytes at 0xA8), stripped."""
    with open(img, "rb") as f:
        f.seek(start_lba * SECTOR + 0xA8)
        return f.read(40).rstrip(b"\0").decode("ascii", "replace")


def luks_data_offset(img, start_lba):
    """Byte offset of the LUKS2 data segment within its partition (the
    header's JSON ``segments.0.offset``), 16 MiB when it cannot be read."""
    with open(img, "rb") as f:
        f.seek(start_lba * SECTOR)
        hdr = f.read(4096)
        try:
            hsize = struct.unpack_from(">Q", hdr, 8)[0]
            f.seek(start_lba * SECTOR + 4096)
            js = f.read(max(0, min(hsize, 4 << 20) - 4096)).split(b"\0", 1)[0]
            return int(json.loads(js)["segments"]["0"]["offset"])
        except Exception:
            return 16 << 20


def card_id(img, plist=None):
    """``<title-version>-<10 hex>``: the file's stem (what the library names a
    card by) plus a fingerprint of the card itself, so a rename keeps nothing
    stale and two different cards never share an id.

    The LUKS header uuids are NOT enough on their own: Stern writes every card
    from one master image, so pokemon_le 0.82.0 and fallout_le 0.81.0 carry the
    same uuids and the same partition table (measured, PAD-1090). What differs
    is the ciphertext of each filesystem's first 64 KiB (superblock + group
    descriptors: counts, times, the fs uuid), so that goes in too - 256 KiB read
    off the original for a whole card."""
    plist = plist if plist is not None else card_partitions(img)
    h = hashlib.sha1()
    h.update(str(os.path.getsize(img)).encode())
    with open(img, "rb") as f:
        for idx, _r, start, count, luks in plist:
            h.update(("%d:%d:%d:" % (idx, start, count)).encode())
            if luks:
                h.update(luks_uuid(img, start).encode())
                f.seek(start * SECTOR + luks_data_offset(img, start))
                h.update(f.read(64 << 10))
    stem = os.path.basename(img).split(".", 1)[0]
    return "%s-%s" % (stem, h.hexdigest()[:10])


# --------------------------------------------------------------------------
# the key
# --------------------------------------------------------------------------
def _key_bytes(v):
    if v is None:
        return None
    if isinstance(v, str) and not os.path.exists(v):
        v = win_to_wsl(v)                 # C:/... named in a keyfile, read in WSL
    if isinstance(v, str) and os.path.exists(v):
        with open(v, "rb") as f:
            b = f.read()
    else:
        try:
            b = bytes.fromhex(str(v).strip().replace(" ", ""))
        except ValueError:
            raise SystemExit("s3store: the key is neither a file nor 64 hex characters")
    if len(b) != 32:
        raise SystemExit("s3store: the key must be 32 bytes, got %d" % len(b))
    return b


def resolve_key(img, given=None):
    """(key bytes, where it came from) - see the module doc for the order."""
    if given:
        return _key_bytes(given), "--key"
    env = os.environ.get("PAD_SPIKE3_OTP_KEY")
    if env:
        return _key_bytes(env), "$PAD_SPIKE3_OTP_KEY"
    cands = []
    env = os.environ.get("PAD_SPIKE3_KEYFILE")
    if env:
        cands.append(win_to_wsl(env))
    d = os.path.dirname(os.path.abspath(img))
    cands += [os.path.abspath(img) + ".padkeys.json", os.path.join(d, "padkeys.json")]
    for c in cands:
        if not os.path.exists(c):
            continue
        try:
            with open(c, "rb") as f:
                doc = json.loads(f.read().decode("utf-8"))
        except ValueError as e:
            raise SystemExit("s3store: %s is not a readable padkeys.json (%s)" % (c, e))
        v = doc.get("otp_keyfile") if isinstance(doc, dict) else None
        if not v:
            continue
        if isinstance(v, str) and not os.path.isabs(win_to_wsl(v)) and \
                os.path.exists(os.path.join(os.path.dirname(c), v)):
            v = os.path.join(os.path.dirname(c), v)
        return _key_bytes(v), c
    return None, None


# --------------------------------------------------------------------------
# opening one partition read-only (root)
# --------------------------------------------------------------------------
def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kw)


class OpenPartition:
    """losetup -r -> cryptsetup open --readonly -> mount -o ro,noload, undone in
    reverse on exit whatever happened in between."""

    def __init__(self, img, start, count, key, name, mnt, luks=True):
        self.img, self.start, self.count = img, start, count
        self.key, self.name, self.mnt, self.luks = key, name, mnt, luks
        self.loop = self.mapped = None
        self.mounted = False

    def __enter__(self):
        r = _run(["losetup", "-r", "-f", "--show", "-o", str(self.start * SECTOR),
                  "--sizelimit", str(self.count * SECTOR), self.img])
        self.loop = r.stdout.decode().strip()
        dev = self.loop
        if self.luks:
            # stale mapping from a killed build: clear it before reusing the name
            if os.path.exists("/dev/mapper/" + self.name):
                subprocess.run(["cryptsetup", "close", self.name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                _run(["cryptsetup", "open", "--readonly", "--type", "luks2",
                      "--key-file", "-", self.loop, self.name], input=self.key)
            except subprocess.CalledProcessError as e:
                raise SystemExit("s3store: the key did not open p@%d (%s)" % (
                    self.start, e.stderr.decode(errors="replace").strip()))
            self.mapped = "/dev/mapper/" + self.name
            dev = self.mapped
        # a bigger read-ahead: the original is on a Windows drive over 9p, where
        # each request costs a round trip; 8 MiB ahead roughly doubles a walk
        for d in (self.loop, dev):
            subprocess.run(["blockdev", "--setra", "16384", d],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.makedirs(self.mnt, exist_ok=True)
        _run(["mount", "-t", "ext4", "-o", "ro,noload", dev, self.mnt])
        self.mounted = True
        return self

    def __exit__(self, *exc):
        if self.mounted:
            subprocess.run(["umount", self.mnt])
        if self.mapped:
            subprocess.run(["cryptsetup", "close", self.name])
        if self.loop:
            subprocess.run(["losetup", "-d", self.loop])
        try:
            os.rmdir(self.mnt)
        except OSError:
            pass
        return False


# --------------------------------------------------------------------------
# opening one partition WITHOUT the kernel (no dm-crypt, no loop, no mount)
# --------------------------------------------------------------------------
# A stock WSL kernel has dm-crypt only as a module, which a PC may not be able
# to load; the app already reads a Spike 3 card in user space for the Extract
# tab - the LUKS2 keyslot, AES-XTS and ext4, from the user's own OTP key - so
# the store can use exactly that code. PAD_S3_STORE_MODE=kernel|user forces one.
def _app_stern():
    """The app's own spike3.py + ext4.py (pinball_decryptor/plugins/stern),
    loaded as a bare package so none of the app's other imports come along;
    spike3.py finds luks_otp.py (stern-spike-3/tools) beside the app."""
    import importlib
    import types
    if "pad_s3_stern" not in sys.modules:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pkg = types.ModuleType("pad_s3_stern")
        pkg.__path__ = [os.path.join(root, "pinball_decryptor", "plugins", "stern")]
        sys.modules["pad_s3_stern"] = pkg
    return importlib.import_module("pad_s3_stern.spike3")


def kernel_crypt_ok():
    """Whether this kernel can open LUKS (dm-crypt) for the faster path."""
    mode = os.environ.get("PAD_S3_STORE_MODE", "")
    if mode in ("kernel", "user"):
        return mode == "kernel"
    try:
        out = subprocess.run(["dmsetup", "targets"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL).stdout.decode()
        if "crypt" in out.split():
            return True
        subprocess.run(["modprobe", "dm_crypt"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        out = subprocess.run(["dmsetup", "targets"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL).stdout.decode()
        return "crypt" in out.split()
    except OSError:
        return False


class UserPartition:
    """A partition's ext4, read through the app's decrypting reader: the
    user's OTP key unlocks the LUKS keyslot, AES-XTS is done in Python
    (the cryptography package), nothing touches the kernel."""

    def __init__(self, img, start, count, key, luks=True):
        self.img, self.start, self.count, self.key, self.luks = img, start, count, key, luks
        self.f = None

    def __enter__(self):
        sp = _app_stern()
        self.f = open(self.img, "rb")
        part = {"start_lba": self.start, "sectors": self.count}
        if self.luks:
            src = sp_keys_source(self.key)
            try:
                self.fs = sp.open_partition_ext4(self.f, part, src)
            except sp.Spike3KeyError as e:
                raise SystemExit("s3store: the key did not open p@%d (%s)" % (self.start, e))
        else:
            self.fs = sp._ext4.Ext4Reader(self.f, self.start * SECTOR, self.count * SECTOR)
        return self

    def __exit__(self, *exc):
        if self.f:
            self.f.close()


def sp_keys_source(key):
    """The app's Spike3KeySource for one OTP key (spike3_keys.py)."""
    import importlib
    _app_stern()
    return importlib.import_module("pad_s3_stern.spike3_keys").Spike3KeySource(otp_keyfile=key)


def _rdev(inode):
    """A device node's number, out of i_block (old or new ext4 encoding)."""
    old, new = struct.unpack_from("<II", bytes(inode["i_block"][:8]))
    if old:
        return os.makedev((old >> 8) & 0xFF, old & 0xFF)
    return os.makedev((new & 0xFFF00) >> 8, (new & 0xFF) | ((new >> 12) & 0xFFF00))


def copy_tree_reader(fs, dst, objs, progress=None):
    """copy_tree() for a partition read in user space: the same tree, the
    same objects, the same owners, modes and times."""
    files = nbytes = 0
    dirs = []
    os.makedirs(dst, exist_ok=True)
    root = fs.read_inode(2)
    dirs.append((dst, root))
    for rel, kind, ino, inode in fs.iter_tree():
        d = os.path.join(dst, rel)
        m = inode["mode"]
        if kind == "dir":
            os.mkdir(d)
            dirs.append((d, inode))
        elif kind == "file":
            chunks = (b for _off, b in fs.read_file_chunks(inode, CHUNK))
            obj, size = objs.put_chunks(chunks, m, inode["uid"], inode["gid"],
                                        inode["atime"], inode["mtime"])
            try:
                os.link(obj, d)
            except OSError as e:
                if e.errno != errno.EMLINK:
                    raise
                shutil.copy2(obj, d)
                os.chown(d, inode["uid"], inode["gid"])
            files += 1
            nbytes += size
            if progress and files % 500 == 0:
                progress(files, nbytes)
        elif kind == "symlink":
            os.symlink(fs.read_symlink(inode), d)
            os.lchown(d, inode["uid"], inode["gid"])
            os.utime(d, (inode["atime"], inode["mtime"]), follow_symlinks=False)
        else:                                       # char/block device, fifo, socket
            try:
                os.mknod(d, m, _rdev(inode))
                os.chown(d, inode["uid"], inode["gid"])
            except OSError:
                pass
    for d, inode in reversed(dirs):
        os.chown(d, inode["uid"], inode["gid"])
        os.chmod(d, stat.S_IMODE(inode["mode"]))
        os.utime(d, (inode["atime"], inode["mtime"]))
    return files, nbytes


# --------------------------------------------------------------------------
# the object store
# --------------------------------------------------------------------------
class Objects:
    def __init__(self, store):
        self.dir = os.path.join(store, "objects")
        self.tmp = os.path.join(store, "objects", "tmp")
        os.makedirs(self.tmp, exist_ok=True)
        self.new_files = self.new_bytes = self.shared_files = self.shared_bytes = 0

    def put(self, src, st):
        """Copy *src* in (sparse-aware, one read pass, hashed as it goes) unless
        an identical object exists; return the object's path."""
        h = hashlib.sha256()
        fd, tmp = tempfile.mkstemp(dir=self.tmp)
        try:
            with open(src, "rb", buffering=0) as fi, os.fdopen(fd, "wb") as fo:
                fd = None
                while True:
                    b = fi.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    if b == ZERO[:len(b)]:
                        fo.seek(len(b), os.SEEK_CUR)   # keep holes holes
                    else:
                        fo.write(b)
                fo.truncate()
            key = "%s-%o-%d-%d" % (h.hexdigest(), stat.S_IMODE(st.st_mode),
                                   st.st_uid, st.st_gid)
            dst = os.path.join(self.dir, key[:2], key)
            if os.path.exists(dst):
                self.shared_files += 1
                self.shared_bytes += st.st_size
                os.unlink(tmp)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.chown(tmp, st.st_uid, st.st_gid)
                os.chmod(tmp, stat.S_IMODE(st.st_mode))
                os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
                os.rename(tmp, dst)
                self.new_files += 1
                self.new_bytes += st.st_size
            tmp = None
            return dst
        finally:
            if fd is not None:
                os.close(fd)
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


    def put_chunks(self, chunks, mode, uid, gid, atime, mtime):
        """put() for a file read through the user-space reader: *chunks* its
        bytes, the rest its inode's fields. Same key, same holes."""
        h = hashlib.sha256()
        fd, tmp = tempfile.mkstemp(dir=self.tmp)
        size = 0
        try:
            with os.fdopen(fd, "wb") as fo:
                fd = None
                for b in chunks:
                    h.update(b)
                    size += len(b)
                    if b == ZERO[:len(b)]:
                        fo.seek(len(b), os.SEEK_CUR)
                    else:
                        fo.write(b)
                fo.truncate()
            key = "%s-%o-%d-%d" % (h.hexdigest(), stat.S_IMODE(mode), uid, gid)
            dst = os.path.join(self.dir, key[:2], key)
            if os.path.exists(dst):
                self.shared_files += 1
                self.shared_bytes += size
                os.unlink(tmp)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.chown(tmp, uid, gid)
                os.chmod(tmp, stat.S_IMODE(mode))
                os.utime(tmp, (atime, mtime))
                os.rename(tmp, dst)
                self.new_files += 1
                self.new_bytes += size
            tmp = None
            return dst, size
        finally:
            if fd is not None:
                os.close(fd)
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


def _link(obj, dst, st):
    try:
        os.link(obj, dst)
    except OSError as e:
        if e.errno != errno.EMLINK:        # 65000 links: give this one its own copy
            raise
        shutil.copy2(obj, dst)
        os.chown(dst, st.st_uid, st.st_gid)


def copy_tree(src, dst, objs, progress=None):
    """Recreate *src* (a mounted, read-only filesystem) at *dst*: regular files
    as hardlinks into *objs*, everything else as itself. Directory times are set
    after their contents, the way tar does it. Returns (files, bytes)."""
    files = nbytes = 0
    dirs = []
    os.makedirs(dst, exist_ok=True)
    stack = [("", os.lstat(src))]
    while stack:
        rel, st = stack.pop()
        s = os.path.join(src, rel) if rel else src
        d = os.path.join(dst, rel) if rel else dst
        if rel:
            os.mkdir(d)
        dirs.append((d, st))
        with os.scandir(s) as it:
            ents = sorted(it, key=lambda e: e.name)
        for e in ents:
            if not rel and e.name == "lost+found":
                continue
            r = os.path.join(rel, e.name) if rel else e.name
            est = e.stat(follow_symlinks=False)
            m = est.st_mode
            dp = os.path.join(dst, r)
            if stat.S_ISDIR(m):
                stack.append((r, est))
            elif stat.S_ISREG(m):
                _link(objs.put(e.path, est), dp, est)
                files += 1
                nbytes += est.st_size
                if progress and files % 500 == 0:
                    progress(files, nbytes)
            elif stat.S_ISLNK(m):
                os.symlink(os.readlink(e.path), dp)
                os.lchown(dp, est.st_uid, est.st_gid)
                os.utime(dp, ns=(est.st_atime_ns, est.st_mtime_ns), follow_symlinks=False)
            else:                                   # char/block device, fifo, socket
                try:
                    os.mknod(dp, m, est.st_rdev)
                    os.chown(dp, est.st_uid, est.st_gid)
                except OSError:
                    pass
    for d, st in reversed(dirs):
        os.chown(d, st.st_uid, st.st_gid)
        os.chmod(d, stat.S_IMODE(st.st_mode))
        os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns))
    return files, nbytes


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def _lock(store):
    import fcntl                      # Linux only; the store lives in WSL
    os.makedirs(store, exist_ok=True)
    fd = os.open(os.path.join(store, ".build.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[s3store] another build holds the store; waiting for it", flush=True)
        fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def card_dir(store, cid):
    return os.path.join(store, "cards", cid)


def built(store, cid):
    """The card's manifest when its tree is complete and current, else None."""
    mf = os.path.join(card_dir(store, cid), "manifest.json")
    try:
        with open(mf) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if doc.get("tree_rev") != TREE_REV or doc.get("partial_roles"):
        return None
    return doc


def _report(pct, text, step=None, count=None):
    """A row on David's dashboard when the caller asked for one ($PAD_TICKET)."""
    t = os.environ.get("PAD_PROGRESS_URL")
    if not t:
        return
    body = {"text": text}
    if pct is not None:
        body["pct"] = pct
    if step:
        body["step"] = step
    if count:
        body["done"], body["total"] = count
    try:
        import urllib.request
        req = urllib.request.Request(t, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass


def cmd_build(a):
    if os.geteuid() != 0:
        raise SystemExit("s3store build needs root (losetup/cryptsetup/mount): "
                         "wsl -u root -e python3 s3store.py build ...")
    img = os.path.abspath(win_to_wsl(a.card))
    plist = card_partitions(img)
    if not any(p[4] for p in plist):
        raise SystemExit("s3store: %s has no LUKS partition - not a Spike 3 card" % img)
    cid = card_id(img, plist)
    store = a.store
    lockfd = _lock(store)
    try:
        doc = built(store, cid)
        if doc and not a.force:
            print("[s3store] %s is already in the store" % cid)
            print("tree: %s" % card_dir(store, cid))
            return 0
        key, where = resolve_key(img, a.key)
        if key is None:
            raise SystemExit(
                "s3store: no Spike 3 OTP keyfile for %s. Give --key, set "
                "$PAD_SPIKE3_OTP_KEY, or put \"otp_keyfile\" in the padkeys.json "
                "the extractor uses." % os.path.basename(img))
        print("[s3store] %s: key from %s" % (cid, where), flush=True)
        use_kernel = kernel_crypt_ok()
        print("[s3store] decrypting with %s" % ("dm-crypt (the kernel)" if use_kernel else
              "the app's own LUKS/ext4 reader (no dm-crypt on this kernel)"), flush=True)
        final = card_dir(store, cid)
        part = final + ".partial"
        if os.path.exists(part):
            shutil.rmtree(part)
        os.makedirs(part)
        objs = Objects(store)
        roles = {}
        t0 = time.time()
        for idx, role, start, count, luks in plist:
            if a.roles and role not in a.roles:
                continue
            t1 = time.time()
            name = "pad_s3_%d_%d" % (os.getpid(), idx)
            mnt = "/run/pad-s3store/%s" % name
            nf0, nb0 = objs.new_files, objs.new_bytes

            def prog(files, nbytes, role=role):
                print("[s3store]   %s: %d files, %.0f MB" % (role, files, nbytes / 1e6), flush=True)
            if use_kernel:
                with OpenPartition(img, start, count, key, name, mnt, luks=luks) as op:
                    files, nbytes = copy_tree(op.mnt, os.path.join(part, role), objs, prog)
                    sv = os.statvfs(op.mnt)
                    used = (sv.f_blocks - sv.f_bfree) * sv.f_frsize
            else:
                with UserPartition(img, start, count, key, luks=luks) as up:
                    files, nbytes = copy_tree_reader(up.fs, os.path.join(part, role), objs, prog)
                    used = None
            roles[role] = {
                "index": idx, "luks": luks, "files": files, "bytes": nbytes,
                "partition_bytes": count * SECTOR,
                "fs_used_bytes": used,
                "new_files": objs.new_files - nf0, "new_bytes": objs.new_bytes - nb0,
                "seconds": round(time.time() - t1, 1)}
            r = roles[role]
            print("[s3store] p%d %-12s %6d files %8.1f MB  new %8.1f MB  (%.0f s)" % (
                idx, role, files, nbytes / 1e6, r["new_bytes"] / 1e6, r["seconds"]), flush=True)
            _report(None, "%s %s: %d files, %.2f GB, %.2f GB new" % (
                cid, role, files, nbytes / 1e9, r["new_bytes"] / 1e9))
        doc = {"format": STORE_FORMAT, "tree_rev": TREE_REV, "card_id": cid,
               "image": img, "image_bytes": os.path.getsize(img),
               "image_mtime": int(os.path.getmtime(img)),
               "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "seconds": round(time.time() - t0, 1), "roles": roles,
               "partial_roles": bool(a.roles)}
        with open(os.path.join(part, "manifest.json"), "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
        if os.path.exists(final):
            shutil.rmtree(final)
        os.rename(part, final)
        tot = sum(r["bytes"] for r in roles.values())
        new = sum(r["new_bytes"] for r in roles.values())
        print("[s3store] %s in the store: %.2f GB of files, %.2f GB new on disk, "
              "image %.1f GB, %.0f s" % (cid, tot / 1e9, new / 1e9,
                                         doc["image_bytes"] / 1e9, doc["seconds"]))
        print("tree: %s" % final)
        return 0
    finally:
        os.close(lockfd)


def cmd_path(a):
    img = os.path.abspath(win_to_wsl(a.card))
    cid = card_id(img)
    if built(a.store, cid):
        print(card_dir(a.store, cid))
        return 0
    print("s3store: %s is not in the store (s3store.py build)" % cid, file=sys.stderr)
    return 1


def _du_objects(store):
    n = b = 0
    od = os.path.join(store, "objects")
    for root, dirs, files in os.walk(od):
        if os.path.basename(root) == "tmp":
            continue
        for fn in files:
            st = os.lstat(os.path.join(root, fn))
            n += 1
            b += st.st_blocks * 512
    return n, b


def cmd_status(a):
    cards = []
    cd = os.path.join(a.store, "cards")
    for cid in sorted(os.listdir(cd)) if os.path.isdir(cd) else []:
        doc = built(a.store, cid)
        if doc:
            cards.append(doc)
    n, disk = _du_objects(a.store)
    logical = sum(r["bytes"] for c in cards for r in c["roles"].values())
    images = sum(c["image_bytes"] for c in cards)
    out = {"store": a.store, "cards": [
        {"card_id": c["card_id"], "image_bytes": c["image_bytes"],
         "file_bytes": sum(r["bytes"] for r in c["roles"].values()),
         "new_bytes": sum(r["new_bytes"] for r in c["roles"].values())} for c in cards],
        "objects": n, "disk_bytes": disk, "file_bytes": logical, "image_bytes": images}
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print("store: %s" % a.store)
    for c in out["cards"]:
        print("  %-60s files %6.2f GB  added %6.2f GB  (image %5.1f GB)" % (
            c["card_id"], c["file_bytes"] / 1e9, c["new_bytes"] / 1e9, c["image_bytes"] / 1e9))
    print("%d cards: %.1f GB of images -> %.2f GB of files -> %.2f GB on disk (%d objects)" % (
        len(cards), images / 1e9, logical / 1e9, disk / 1e9, n))
    return 0


def cmd_gc(a):
    removed = freed = 0
    od = os.path.join(a.store, "objects")
    for root, dirs, files in os.walk(od):
        for fn in files:
            p = os.path.join(root, fn)
            st = os.lstat(p)
            if os.path.basename(root) == "tmp" or st.st_nlink <= 1:
                freed += st.st_blocks * 512
                os.unlink(p)
                removed += 1
    print("[s3store] gc: %d objects, %.2f GB freed" % (removed, freed / 1e9))
    return 0


def cmd_remove(a):
    lockfd = _lock(a.store)
    try:
        d = card_dir(a.store, a.card_id)
        if not os.path.isdir(d):
            raise SystemExit("s3store: no card %s in the store" % a.card_id)
        shutil.rmtree(d)
        print("[s3store] removed %s" % a.card_id)
        return cmd_gc(a)
    finally:
        os.close(lockfd)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("card")
    b.add_argument("--key")
    b.add_argument("--force", action="store_true")
    b.add_argument("--roles", nargs="*", help="only these partitions (rootfs games ...)")
    p = sub.add_parser("path")
    p.add_argument("card")
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    sub.add_parser("gc")
    r = sub.add_parser("remove")
    r.add_argument("card_id")
    sub.add_parser("where")                  # the store's directory
    a = ap.parse_args(argv)
    a.store = a.store or default_store()
    if a.cmd == "where":
        print(a.store)
        return 0
    return {"build": cmd_build, "path": cmd_path, "status": cmd_status,
            "gc": cmd_gc, "remove": cmd_remove}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
