"""Stern **Spike 2 `.spk`** update package -> a full Spike 2 extract (PAD-1641).

Stern's public game-code page publishes every Spike 2 title as
``<title>-<a>_<b>_<c>.spk.zip`` (``iron_maiden_le-1_18_0.spk.zip``; some
pages add ``_spike2``), the same name shape as a Spike 3 package.  The two are
nothing alike inside:

* Spike 3: a LUKS2 container, keyed by the fleet update key (:mod:`.spike3_spk`).
* Spike 2: a plain, unencrypted **SquashFS** image (:mod:`.squashfs`) holding
  one file, ``<title>-<version>.spk``: an SPKS archive (:mod:`.spks`) with a
  ``spike`` section (the OS files a card's root partition carries, under
  ``usr/local/spike``) and a section named for the game (``iron_maiden_le/...``,
  what the card's games partition carries).  Every file is stored verbatim.

So the package is told apart by its first bytes, never its name, and a Spike 2
one is read as if it were the card: each SPKS section becomes a read-only
volume (:class:`SpkVolume`) that answers the same calls as the card's
:class:`.ext4.Ext4Reader`, every file one contiguous run of the archive.  The
ordinary Spike 2 extract (:func:`.engine.extract_all`: videos, images, scenes,
text, and the sounds decoded on the codec emulator) runs over those volumes
unchanged.  No key, no card, no machine.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile

from ...core.pipeline_base import BasePipeline, PipelineError
from ...core import pad_temp
from . import spks as _spks
from .ext4 import Ext4Reader
from .squashfs import MAGIC as _SQFS_MAGIC, SquashfsReader, SquashfsFileReader

_LUKS2_MAGICS = (b"LUKS\xba\xbe", b"SKUL\xba\xbe")

#: ``name.spk.NNN.MMM``: part MMM of NNN of a split package
_SPLIT = re.compile(r"^(.*\.spk)\.(\d{3})\.(\d{3})$", re.IGNORECASE)

#: the SPKS section holding the OS files (the card's root partition)
OS_SECTION = "spike"


# --------------------------------------------------------------------------
# what a package is
# --------------------------------------------------------------------------
def split_parts(path):
    """The parts of a split package, in order, when *path* names one of them
    (``x.spk.002.000`` -> ``[x.spk.002.000, x.spk.002.001]``); ``None`` when
    it is not a split-part name or a part is missing."""
    m = _SPLIT.match(os.path.basename(path))
    if not m:
        return None
    stem, count = m.group(1), int(m.group(2))
    folder = os.path.dirname(path)
    parts = [os.path.join(folder, "%s.%03d.%03d" % (stem, count, i))
             for i in range(count)]
    return parts if all(os.path.isfile(p) for p in parts) else None


def _zip_parts(z):
    parts = sorted((m for m in z.infolist() if ".spk" in m.filename.lower()
                    and not m.is_dir()), key=lambda m: m.filename)
    return parts or sorted((m for m in z.infolist() if not m.is_dir()),
                           key=lambda m: m.filename)


def package_head(path, n=6):
    """The first *n* bytes of the package payload at *path*: the first part of
    a ``.spk.zip`` (decompressed), the first of a split set, or the file
    itself.  ``b""`` when it cannot be read."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                parts = _zip_parts(z)
                if not parts:
                    return b""
                with z.open(parts[0]) as f:
                    return f.read(n)
        parts = split_parts(path)
        with open(parts[0] if parts else path, "rb") as f:
            return f.read(n)
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        return b""


def _spk_name(path):
    low = os.path.basename(path).lower()
    return (low.endswith(".spk.zip") or low.endswith(".spk")
            or bool(_SPLIT.match(low)) or low.endswith(".zip"))


def package_kind(path):
    """``"spike2"`` (SquashFS), ``"spike3"`` (LUKS2) or ``None`` for the
    ``.spk`` package at *path*, by its content."""
    if not _spk_name(path):
        return None
    head = package_head(path)
    if head[:4] == _SQFS_MAGIC:
        return "spike2"
    if head[:6] in _LUKS2_MAGICS:
        return "spike3"
    return None


def is_spike2_spk(path):
    """True if *path* is a Stern Spike 2 update package (a ``.spk.zip``, a
    raw ``.spk`` or a split part) - an unencrypted SquashFS inside."""
    return package_kind(path) == "spike2"


def is_package_name(path):
    """True when *path* is NAMED like a Stern game code package (``.spk.zip``, ``.spk``
    or a split part), either era.  Name only: it never opens the file, so the UI may ask."""
    low = os.path.basename(str(path or "")).lower()
    return low.endswith(".spk.zip") or low.endswith(".spk") or bool(_SPLIT.match(low))


def not_a_card_words(path, look=False):
    """PAD-1644: why a Stern game code package cannot stand in for an SD card image, or
    ``""`` when *path* is not one.  Extract reads a package in full (PAD-1641), but Modes,
    the emulator and Write all work on the game's SD card image: a package holds the game's
    files and Stern's program, never a card's partitions.  *look* also reads the file's
    first bytes (a package renamed past its ``.spk`` name), so never on the UI thread."""
    if not path or not (is_package_name(path) or (look and package_kind(path))):
        return ""
    return ("%s is Stern's game code download (a .spk package), not an SD card image. "
            "Extract reads it, but Modes, the emulator and Write work on SD card images: "
            "download this game's SD card image from Stern and use that instead."
            % os.path.basename(path))


def game_key(path):
    """The Spike 2 game key for a package: a known title's when the name
    hints at one, else the generic Spike 2 key (as :func:`.formats.detect_game`
    does for a card)."""
    from .formats import GAME_DB, SPIKE2_GENERIC_KEY, _filename_hint
    return next((k for k in GAME_DB if _filename_hint(path, k)),
                SPIKE2_GENERIC_KEY)


def title_key(path):
    """``iron_maiden_le`` for ``iron_maiden_le-1_18_0.spk.zip``: the name every
    Stern download and card index shares."""
    stem = os.path.basename(path).split(".", 1)[0]
    return stem.split("-", 1)[0].lower()


# --------------------------------------------------------------------------
# getting at the archive
# --------------------------------------------------------------------------
def unpack_package(path, out_path, progress=None, cancel=None):
    """Write the raw package (the SquashFS image) to *out_path*: the parts of
    a ``.spk.zip`` (decompressed) or of a split set, end to end.  Returns
    *out_path*, or ``None`` when *cancel* stopped it.  ``progress(done,
    total)`` is called as it goes."""
    chunk = 32 << 20
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            parts = _zip_parts(z)
            total = sum(m.file_size for m in parts)
            sources = [(lambda m=m: z.open(m)) for m in parts]
            return _concat(sources, total, out_path, chunk, progress, cancel)
    parts = split_parts(path) or [path]
    total = sum(os.path.getsize(p) for p in parts)
    sources = [(lambda p=p: open(p, "rb")) for p in parts]
    return _concat(sources, total, out_path, chunk, progress, cancel)


def _concat(sources, total, out_path, chunk, progress, cancel):
    done = 0
    with open(out_path, "wb") as o:
        for opener in sources:
            with opener() as f:
                while True:
                    if cancel and cancel():
                        return None
                    b = f.read(chunk)
                    if not b:
                        break
                    o.write(b)
                    done += len(b)
                    if progress:
                        progress(done, total)
    return out_path


def needs_unpack(path):
    """True when the package must be written out whole before it can be read
    (a zip's parts are compressed; split parts are separate files); a raw
    ``.spk`` is read where it is."""
    return zipfile.is_zipfile(path) or split_parts(path) is not None


class SpkVolume(Ext4Reader):
    """One SPKS section as a read-only volume with the card reader's calls.

    Inode 2 is the root; directories are made from the stored paths, and each
    file is ONE run of the archive (a block size of one byte, so the run's
    "block" numbers are the archive's byte offsets).  Everything the extract
    reads through - :meth:`read_inode`, the directory walks, the file reads,
    :meth:`find_spike_assets` - works as it does on a card."""

    def __init__(self, read, files, name, base, size):
        # no ext4 superblock here: set what the inherited calls use
        self.f = None
        self.base = base             # a tag only: _read never adds it
        self.size = size
        self.block_size = 1
        self.name = name
        self._inode_tables = {}
        self._readfn = read
        self._nodes = {}
        self._kids = {}
        self._new_dir(2)
        self._dirs = {"": 2}
        nxt = 3
        for fobj in files:
            parts = [p for p in fobj.path.split("/") if p]
            if not parts:
                continue
            parent = ""
            for d in parts[:-1]:
                here = parent + d + "/"
                if here not in self._dirs:
                    self._dirs[here] = nxt
                    self._new_dir(nxt)
                    self._kids[self._dirs[parent]].append(
                        (d.encode("utf-8", "surrogateescape"), nxt, 2))
                    nxt += 1
                parent = here
            mode = fobj.mode or (stat.S_IFREG | 0o644)
            if not stat.S_IFMT(mode):
                mode |= stat.S_IFREG
            if stat.S_ISDIR(mode):
                here = parent + parts[-1] + "/"
                if here not in self._dirs:
                    self._dirs[here] = nxt
                    self._new_dir(nxt)
                    self._kids[self._dirs[parent]].append(
                        (parts[-1].encode("utf-8", "surrogateescape"), nxt, 2))
                    nxt += 1
                continue
            ftype = 7 if stat.S_ISLNK(mode) else 1
            self._nodes[nxt] = {"mode": mode, "size": fobj.size, "flags": 0,
                                "i_block": bytes(60), "blocks_lo": 0,
                                "file_acl": 0, "links": 1,
                                "_runs": [(0, fobj.offset, fobj.size)]
                                if fobj.size else [],
                                "_path": fobj.path, "_ino": nxt}
            self._kids[self._dirs[parent]].append(
                (parts[-1].encode("utf-8", "surrogateescape"), nxt, ftype))
            nxt += 1

    def _new_dir(self, ino):
        self._nodes[ino] = {"mode": stat.S_IFDIR | 0o755, "size": 4096,
                            "flags": 0, "i_block": bytes(60), "blocks_lo": 0,
                            "file_acl": 0, "links": 2, "_runs": [],
                            "_ino": ino}
        self._kids[ino] = []
        return ino

    # ---- the primitives the inherited calls are built on ----------------
    def _read(self, off, n):
        return self._readfn(off, n)

    def read_inode(self, ino):
        try:
            return self._nodes[ino]
        except KeyError:
            raise _spks.SpksError("no inode %d in %s" % (ino, self.name)) from None

    def _runs(self, inode):
        return list(inode.get("_runs", ()))

    def _runs_flagged(self, inode):
        return [(lg, ph, cnt, False) for lg, ph, cnt in inode.get("_runs", ())]

    def _iter_dir_raw(self, inode):
        # in the archive's order: Stern's updater writes the card from the
        # archive, so this is the card's own directory order, and the walks
        # that keep a first-seen copy (radium images, atlas names) then pick
        # the very ones a card extract picks
        yield from self._kids.get(inode.get("_ino"), ())

    def read_symlink(self, inode):
        if not stat.S_ISLNK(inode["mode"]):
            from .ext4 import Ext4Error
            raise Ext4Error("not a symlink")
        return self.read_file_bytes(inode).decode("utf-8", "surrogateescape")

    def extract_file(self, inode, out_path, chunk_blocks=2048, progress=None):
        size = inode["size"]
        with open(out_path, "wb") as out:
            for off, data in self.read_file_chunks(inode):
                out.write(data)
                if progress:
                    progress(min(off + len(data), size), size)
        return out_path

    def uuid(self):
        return ""

    def feature_words(self):
        return ()


class SpkPackage:
    """A Spike 2 package opened for reading: :attr:`volumes` is the game
    section(s) first, then the OS section - the order a card's partitions are
    tried in (largest first)."""

    def __init__(self, raw_path):
        self.f = open(raw_path, "rb")
        try:
            self.sqfs = SquashfsReader(self.f)
            inner = None
            for path, ino in self.sqfs.walk():
                if ino.is_file and path.lower().endswith(".spk"):
                    inner = ino
                    break
            if inner is None:
                inner = next((i for _p, i in self.sqfs.walk() if i.is_file),
                             None)
            if inner is None:
                raise PipelineError("Locate partitions",
                                    "This package holds no game archive.")
            self.read = SquashfsFileReader(self.sqfs, inner)
            self.archive = _spks.SpksArchive(self.read, inner.size)
            by_section = {}
            for fobj in self.archive.files:
                by_section.setdefault(fobj.section, []).append(fobj)
            games = sorted((s for s in by_section if s != OS_SECTION),
                           key=lambda s: -sum(x.size for x in by_section[s]))
            order = games + ([OS_SECTION] if OS_SECTION in by_section else [])
            self.volumes = [
                SpkVolume(self.read, by_section[s], s, -(i + 1), inner.size)
                for i, s in enumerate(order)]
            self.game_sections = games
        except Exception:
            self.f.close()
            raise

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _PackageFile:
    """The "disk" the extract opens: the raw package, read through the
    volumes (it is only ever closed)."""

    def __init__(self, raw_path):
        self._f = open(raw_path, "rb")

    def seek(self, *a):
        return self._f.seek(*a)

    def read(self, *a):
        return self._f.read(*a)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------
# the extract
# --------------------------------------------------------------------------
class Spike2SpkExtractPipeline(BasePipeline):
    """Extract a Spike 2 title straight from Stern's ``.spk`` download: the
    same videos, images, scenes, text and sounds an extract of its card
    gives."""

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 extract_categories=None, duration_names=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        self.extract_categories = extract_categories
        self.duration_names = duration_names

    def _run(self):
        from . import pipeline as _P
        from .formats import display_for_key
        from ...core.checksums import generate_checksums
        from ...core.staged_originals import discard as discard_snapshots

        self._set_phase(0)  # Detect
        if not is_spike2_spk(self.input_path):
            raise PipelineError("Detect",
                                "Not a Stern Spike 2 update package (.spk).")
        key = game_key(self.input_path)
        label = display_for_key(key, self.input_path)
        self._log("Detected Spike 2 update package: %s" % label, "success")
        self._check_cancel()

        self._set_phase(1)  # Locate partitions
        tmpdir = None
        try:
            raw = self.input_path
            if needs_unpack(self.input_path):
                tmpdir = pad_temp.mkdtemp(prefix="pad_spk2_")
                raw = os.path.join(tmpdir, "package.spk")
                self._log("Unpacking the package (it needs about %.1f GB of "
                          "temporary space)..." % (_payload_size(self.input_path)
                                                   / 1e9), "info")
                r = unpack_package(
                    self.input_path, raw,
                    progress=lambda d, t: self._progress(
                        int(d * 5 / max(t, 1)), 100,
                        "Unpacking %.1f/%.1f GB" % (d / 1e9, t / 1e9)),
                    cancel=lambda: self._cancelled)
                self._check_cancel()
                if r is None:
                    raise PipelineError("Locate partitions", "Canceled.")
            try:
                pkg = SpkPackage(raw)
            except (_spks.SpksError, OSError, ValueError) as e:
                raise PipelineError(
                    "Locate partitions",
                    "This Spike 2 package could not be read (%s)." % e)
            with pkg:
                if not pkg.game_sections:
                    raise PipelineError("Locate partitions",
                                        "This package holds no game.")
                self._log("Package holds %d files: the game (%s) and the "
                          "machine's own files." % (
                              len(pkg.archive.files),
                              ", ".join(pkg.game_sections)), "info")
                _P._require_engine()
                os.makedirs(self.output_dir, exist_ok=True)
                flags = _P._category_flags(self.extract_categories)
                n = _P.engine.extract_all(
                    self.input_path, list(pkg.volumes), self.output_dir,
                    log=self._log, progress=self._progress,
                    cancel=lambda: self._cancelled, phase=self._set_phase,
                    open_disk=lambda: _PackageFile(raw),
                    log_line=self._log_line, label=label,
                    duration_names=self.duration_names, **flags)
            self._check_cancel()
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        self._set_phase(5)  # Checksums
        discard_snapshots(self.output_dir)
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
        self._done(True, _P._extract_summary(
            n, self.output_dir, flags, source=" from the update package"))


def _payload_size(path):
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return sum(m.file_size for m in _zip_parts(z))
        return sum(os.path.getsize(p) for p in (split_parts(path) or [path]))
    except (OSError, zipfile.BadZipFile):
        return 0
