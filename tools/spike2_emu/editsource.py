#!/usr/bin/env python3
"""editsource.py - a multi-boot image given as a BASE CARD PLUS AN EDITS FOLDER (PAD-241).

A jukebox card's members are one title with its songs changed.  The card side stores them
compactly (item 95's store, item 107's deltas), but the INPUT was always a whole card image
per member: forty song sets meant forty 8 GB .raw files on the PC to feed a card that holds
them in a few GB.  The app already writes the lighter form - an OVERRIDE SET, the card files
the edits touch, whole, beside overrides.json naming the card they were edited from
(plugins/stern/engine.py write_overrides, what Emulate binds over a card to run the edits).

A member source spelled

    <base.raw>+<edits folder>

is that card with those files in place of its own: the same games tree the full build of the
same edits would carry (write_image and write_overrides share _compute_patches, byte for
byte), read without it ever existing.  mkmulticard takes it anywhere it takes an extra image
(--extra, --member, --members-list, verify's list); the store layout is the only one it can
land in, since the others copy a partition verbatim and there is no partition to copy.

WHAT IS REFUSED, and why each one is refused rather than guessed:
  - a folder with no overrides.json, or one still being built (a half set is not a set);
  - a set from a NEWER app (OVERRIDE_VERSION above ours): its shape is not one this reads;
    one from an older app is refused too - Try it again rebuilds it in the current shape;
  - a set edited from a DIFFERENT card than the base given (size + mtime, the identity the
    set itself records and the rig's card cache keys on): its files are patched copies of
    another card's, and laid over this one they are a corrupt title;
  - a set made to run over another card (PAD-172's run_card): its game program carries THAT
    card's build, which no full build of these edits from this base would;
  - a set that carries custom modes (item 149): their files live on the system partition,
    beside the set rather than in it, and a member's system partition is never read;
  - a set whose files are not as its manifest left them (size + mtime): what the folder holds
    is then not what any build wrote.

The overlay is BY INODE: an edited file's bytes replace the base inode's, exactly what the
build's in-place patch does to the card - so a file the base hardlinks under two names is
edited under both, as it would be on a built card.
"""
import hashlib
import json
import os

#: The file that makes a folder an override set (engine.OVERRIDE_MANIFEST).
MANIFEST = "overrides.json"
#: The override set shape this reads (engine.OVERRIDE_VERSION; a test holds the two equal).
VERSION = 2
#: The joiner between the base card and the edits folder in a source spec.
JOIN = "+"
CHUNK = 1 << 20


class EditsError(Exception):
    """A base + edits source that cannot be used, with the sentence that says why."""


def split(spec):
    """``(base, edits)`` when *spec* names a card plus an edits folder, else ``None``.

    A path that exists as it is is never split (a card file may have a '+' in its name).
    Otherwise every '+' is tried from the right: the first split whose left side is a file
    and whose right side is a directory holding an override manifest wins - so a spec is a
    composite only when both halves are really there, and a mistyped one falls through to
    the caller's own "does not exist"."""
    if not spec or JOIN not in spec or os.path.exists(spec):
        return None
    at = len(spec)
    while True:
        at = spec.rfind(JOIN, 0, at)
        if at <= 0:
            return None
        base, edits = spec[:at], spec[at + 1:]
        if os.path.isfile(base) and os.path.isfile(os.path.join(edits, MANIFEST)):
            return base, edits


def looks_like(spec):
    """True when *spec* is SPELLED as a composite (a '+' and no file by that name), whether
    or not its halves exist - the parsers' test for "say what is wrong with it", never for
    "treat it as one"."""
    return bool(spec) and JOIN in spec and not os.path.exists(spec)


def base_of(spec):
    """The card file a source reads its tables, partitions and untouched files from."""
    sp = split(spec)
    return sp[0] if sp else spec


def join(base, edits):
    return "%s%s%s" % (base, JOIN, edits)


def describe(spec):
    """A short name for a source in a log line: 'base.raw + songs_b'."""
    sp = split(spec)
    if not sp:
        return os.path.basename(spec or "")
    return "%s + %s" % (os.path.basename(sp[0]), os.path.basename(os.path.normpath(sp[1])))


# ============================================================================ the set
def read_manifest(edits):
    try:
        with open(os.path.join(edits, MANIFEST), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise EditsError("%s: its %s cannot be read (%s)" % (edits, MANIFEST, e))
    if not isinstance(data, dict):
        raise EditsError("%s: its %s is not an override set's" % (edits, MANIFEST))
    return data


def _card_stamp(path):
    st = os.stat(path)
    return st.st_size, int(st.st_mtime)


class EditsSet:
    """A checked base + edits pair: `files` is {rel: path in the folder}, rel relative to the
    games partition's root with no leading slash (the set mirrors the partition, never the
    title directory: the .sidx an edit rewrites lives in /spk/index)."""

    def __init__(self, base, edits, manifest, files):
        self.base, self.edits, self.manifest, self.files = base, edits, manifest, dict(files)

    @property
    def spec(self):
        return join(self.base, self.edits)

    def stamp_token(self):
        """What changes when the EDITS change: the set's generation plus every file's size and
        mtime.  Carried in the source's stamp, so an update reads a new set as a new image
        even though its base card never moved."""
        h = hashlib.sha1()
        h.update(str(self.manifest.get("generation") or "").encode())
        for rel in sorted(self.files):
            st = os.stat(self.files[rel])
            h.update(("%s|%d|%d\n" % (rel, st.st_size, st.st_mtime_ns)).encode("utf-8", "surrogateescape"))
        return h.hexdigest()[:20]


def check(base, edits):
    """The set in *edits*, checked against the card *base* -> EditsSet.  Raises EditsError
    with the reason for every refusal the module docstring lists."""
    if not os.path.isfile(base):
        raise EditsError("the base card %s does not exist" % base)
    if not os.path.isdir(edits):
        raise EditsError("the edits folder %s does not exist" % edits)
    man = read_manifest(edits)
    if man.get("building"):
        raise EditsError("%s is an override set that was never finished (its build stopped part way); "
                         "press Try it on the Emulate tab again to rebuild it" % edits)
    ver = int(man.get("version") or 0)
    if ver > VERSION:
        raise EditsError("%s was written by a newer version of the app (override set v%d; this tool reads "
                         "v%d) - update the app, then build the card" % (edits, ver, VERSION))
    if ver < VERSION:
        raise EditsError("%s was written by an older version of the app (override set v%d; this tool reads "
                         "v%d) - press Try it on the Emulate tab again to rebuild it" % (edits, ver, VERSION))
    card = man.get("card") or {}
    size, mtime = _card_stamp(base)
    if card.get("size") != size or int(card.get("mtime") or 0) != mtime:
        raise EditsError("%s was edited from a different card than %s: the set names %s (%s bytes), this is "
                         "%s bytes%s. Its files are patched copies of THAT card's, and laid over another they "
                         "are a corrupt title - give the card the set was made from"
                         % (edits, os.path.basename(base), card.get("path") or "an unnamed card",
                            card.get("size"), size,
                            " (same size, different date)" if card.get("size") == size else ""))
    run = man.get("run_card") or {}
    if run and (run.get("size") != card.get("size") or int(run.get("mtime") or 0) != int(card.get("mtime") or 0)):
        raise EditsError("%s was made to run over another card (%s), so its game program carries that card's "
                         "build rather than these edits alone - prepare the set on the original card"
                         % (edits, run.get("path") or "?"))
    if man.get("modes") or os.path.exists(os.path.join(edits, "overrides.new")):
        raise EditsError("%s carries custom modes, whose files live on the system partition beside the set; "
                         "a multi-boot member takes its modes only from a whole card image - build this one "
                         "with Write instead" % edits)
    files = {}
    for rec in man.get("files") or []:
        path = str(rec.get("path") or "")
        rel = path.strip("/")
        if not rel or rel.startswith("../") or "/../" in "/" + rel + "/":
            raise EditsError("%s: its manifest names a file %r this tool will not follow" % (edits, path))
        local = os.path.join(edits, *rel.split("/"))
        try:
            st = os.stat(local)
        except OSError:
            raise EditsError("%s: %s is missing from the folder (the manifest names it) - press Try it again "
                             "to rebuild the set" % (edits, path))
        if st.st_size != rec.get("size") or int(st.st_mtime) != int(rec.get("mtime") or 0):
            raise EditsError("%s: %s is not the file the set's build wrote (size or date moved since) - press "
                             "Try it again to rebuild the set" % (edits, path))
        files[rel] = local
    if not files:
        raise EditsError("%s holds no edited files: the member would be the base card itself - add the base "
                         "card instead" % edits)
    return EditsSet(base, edits, man, files)


_CHECKED = {}


def load(spec):
    """EditsSet for a composite *spec*, None for a plain path; checked once per process
    (keyed by the spec and the manifest's own stamp)."""
    sp = split(spec)
    if not sp:
        return None
    try:
        st = os.stat(os.path.join(sp[1], MANIFEST))
        key = (spec, st.st_size, st.st_mtime_ns)
    except OSError:
        key = None
    if key is not None and key in _CHECKED:
        return _CHECKED[key]
    es = check(*sp)
    if key is not None:
        _CHECKED[key] = es
    return es


# ============================================================================ the bytes
def file_chunks(path, chunk=CHUNK):
    """``(offset, bytes)`` of a whole local file, in order."""
    off = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            yield off, b
            off += len(b)


_DIGESTS = {}


def file_digest(path, cache_dir=None):
    """sha256 of a local file, memoised on (path, size, mtime_ns) - for this process, and in
    *cache_dir* when one is given (plan and build are separate runs, and an edited image.bin
    is 1.4 GB).  A cache file that does not read back as a digest is ignored."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if key in _DIGESTS:
        return _DIGESTS[key]
    name = None
    if cache_dir:
        name = os.path.join(cache_dir, "edits-%s.sha256" % hashlib.sha1(
            ("%s|%d|%d" % key).encode("utf-8", "surrogateescape")).hexdigest())
        try:
            with open(name, "r") as f:
                got = f.read().strip()
            if len(got) == 64 and all(c in "0123456789abcdef" for c in got):
                _DIGESTS[key] = got
                try:
                    os.utime(name, None)            # a use: kept caches age by use (PAD-1598)
                except OSError:
                    pass
                return got
        except OSError:
            pass
    h = hashlib.sha256()
    for _o, b in file_chunks(path):
        h.update(b)
    _DIGESTS[key] = h.hexdigest()
    if name:
        try:
            tmp = name + ".tmp.%d" % os.getpid()
            with open(tmp, "w") as f:
                f.write(_DIGESTS[key])
            os.replace(tmp, name)
        except OSError:
            pass                                    # a cache is a convenience, never a refusal
    return _DIGESTS[key]


def lookup(reader, rel, root_ino=2):
    """The inode number of *rel* under *root_ino* in an Ext4Reader, or None."""
    ino = root_ino
    for name in rel.split("/"):
        node = reader.read_inode(ino)
        nxt = None
        for n, child, _t in reader._iter_dir(node):
            if n == name:
                nxt = child
                break
        if nxt is None:
            return None
        ino = nxt
    return ino


class EditsReader:
    """An Ext4Reader over the base card's games partition with the edited files' bytes in
    place of their inodes'.  Everything that reads a file's content through the reader
    (iter_tree + read_file_chunks for the hash and the store write, read_file_bytes for the
    game ELF and the .sidx, read_range) sees the edited bytes; everything else is the base's.
    An edited inode has no disk ranges of its own - asking for them is refused, never
    answered with the base's."""

    def __init__(self, reader, es, root_ino=2):
        self._r, self.es = reader, es
        self.by_ino = {}
        for rel, local in es.files.items():
            ino = lookup(reader, rel, root_ino)
            if ino is None:
                raise EditsError("%s: %s is not a file on %s - the set was not made from this card"
                                 % (es.edits, rel, os.path.basename(es.base)))
            node = reader.read_inode(ino)
            if node["mode"] & 0o170000 != 0o100000:
                raise EditsError("%s: %s is not a regular file on %s" % (es.edits, rel, os.path.basename(es.base)))
            self.by_ino[ino] = local

    def __getattr__(self, name):
        return getattr(self._r, name)

    def read_inode(self, ino):
        node = self._r.read_inode(ino)
        local = self.by_ino.get(ino)
        if local is not None:
            node = dict(node)
            node["size"] = os.path.getsize(local)
            node["_edits"] = local
        return node

    def iter_tree(self, root_ino=2, skip=("lost+found",)):
        for rel, kind, ino, node in self._r.iter_tree(root_ino, skip=skip):
            if ino in self.by_ino:
                node = self.read_inode(ino)
            yield rel, kind, ino, node

    def iter_regular_files(self, *a, **k):
        for path, ino, node in self._r.iter_regular_files(*a, **k):
            if ino in self.by_ino:
                node = self.read_inode(ino)
            yield path, ino, node

    def read_file_chunks(self, inode, chunk=CHUNK):
        if "_edits" in inode:
            return file_chunks(inode["_edits"], chunk)
        return self._r.read_file_chunks(inode, chunk)

    def read_file_bytes(self, inode):
        if "_edits" in inode:
            with open(inode["_edits"], "rb") as f:
                return f.read()
        return self._r.read_file_bytes(inode)

    def read_range(self, inode, file_off, length):
        if "_edits" in inode:
            if file_off >= inode["size"] or length <= 0:
                return b""
            with open(inode["_edits"], "rb") as f:
                f.seek(file_off)
                return f.read(min(length, inode["size"] - file_off))
        return self._r.read_range(inode, file_off, length)

    def peek(self, inode, n=16):
        return self.read_range(inode, 0, n) if "_edits" in inode else self._r.peek(inode, n)

    def extract_file(self, inode, out_path, *a, **k):
        if "_edits" in inode:
            import shutil
            shutil.copyfile(inode["_edits"], out_path)
            return
        return self._r.extract_file(inode, out_path, *a, **k)

    def disk_ranges(self, inode, file_off, length):
        if "_edits" in inode:
            raise EditsError("%s is an edited file (from %s): it has no place on the base card"
                             % (inode["_edits"], self.es.edits))
        return self._r.disk_ranges(inode, file_off, length)


def overlay_manifest(base_tree, reader, es, tree_cls, rec_cls, cache_dir=None):
    """The composite's TreeManifest: *base_tree* (the base card's, cached) with every file an
    edit replaced re-described - its sha256 and size from the edits folder, its mode, owner and
    mtime the base inode's (an in-place patch moves none of them).  Only the edited files are
    hashed.  *reader* is the base's plain Ext4Reader, walked for its inode numbers (no content
    read) so a hardlinked file is re-described under every name it has; the result's `inodes`
    map is filled, which an EditsReader then reads through."""
    er = reader if isinstance(reader, EditsReader) else EditsReader(reader, es)
    tree = tree_cls(dict(base_tree.files), dict(base_tree.symlinks), dict(base_tree.dirs))
    for rel, kind, ino, _node in er._r.iter_tree(2, skip=()):
        if kind != "file":
            continue
        tree.inodes[rel] = ino
        local = er.by_ino.get(ino)
        if local is None or rel not in tree.files:
            continue
        old = tree.files[rel]
        tree.files[rel] = rec_cls(file_digest(local, cache_dir), os.path.getsize(local), old.mode, old.uid, old.gid,
                                  old.mtime)
    return tree
