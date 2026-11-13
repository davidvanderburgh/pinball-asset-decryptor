"""Stern **Spike 3 `.spk`** extract pipeline — decrypt an update package and
pull its asset tree out.

A Spike 3 `.spk` (Stern's public update download, usually a split `.spk.zip`)
decrypts with the fleet update key to a LUKS2 -> ext4 payload holding one nested
**SPKS** archive (:mod:`.spks`).  That archive stores every shipped file
verbatim and by name, so this path works for **any title** with no pinball
hardware and no SD-card key — point PAD at ``<title>.spk.zip`` and get the named
asset tree: videos, images, scenes, and ``image.bin`` (the sound container).

Flow: reconstruct the split zip into a raw ``.spk`` (its members are DEFLATE-
compressed, so random access needs a decompressed copy) -> unlock the LUKS2
container with the fleet key -> walk the ext4 -> read the nested SPKS index ->
copy out the files by category.  The reconstructed temp ``.spk`` is deleted
after.  Keys never live in the repo (see :mod:`.spike3_keys`).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile

from ...core.pipeline_base import BasePipeline, PipelineError
from . import spike3
from . import spks as _spks
from .ext4 import Ext4Reader
from .spike3_keys import Spike3KeySource, Spike3KeyError
from .spike3_extract import PHASES          # shared Spike 3 extract phases
from .spike3_extract import (CATEGORIES, want_category,
                             decode_sound_containers, summary_bits,
                             extract_videos, is_sound_container,
                             is_video_head, video_brand, _MAX_RADIUM)
from .formats import _title_from_filename

_LUKS2_MAGIC = spike3.LUKS2_MAGIC


def is_spk_input(path):
    """True if *path* looks like a Spike 3 ``.spk`` package (a ``.spk.zip``, a
    raw ``.spk`` with a LUKS2 header at offset 0, or a split ``.spk.NNN.000``)."""
    low = path.lower()
    if low.endswith(".spk.zip") or ".spk." in low:
        return True
    if low.endswith(".spk"):
        try:
            with open(path, "rb") as f:
                return f.read(6) in _LUKS2_MAGIC
        except OSError:
            return False
    # a .zip whose members are .spk parts
    if low.endswith(".zip") and zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as z:
                return any(".spk." in m.filename.lower() for m in z.infolist())
        except zipfile.BadZipFile:
            return False
    return False


def reconstruct_spk(zip_path, out_path, progress=None, cancel=None):
    """Concatenate a split ``.spk.zip``'s parts (in name order) into *out_path*.

    Members are decompressed as they are read.  ``progress(done_bytes,
    total_bytes)`` is called as it runs."""
    with zipfile.ZipFile(zip_path) as z:
        parts = sorted((m for m in z.infolist() if ".spk." in m.filename.lower()),
                       key=lambda m: m.filename)
        if not parts:
            parts = sorted(z.infolist(), key=lambda m: m.filename)
        total = sum(m.file_size for m in parts)
        done = 0
        with open(out_path, "wb") as o:
            for m in parts:
                with z.open(m) as f:
                    while True:
                        if cancel and cancel():
                            return None
                        b = f.read(32 << 20)
                        if not b:
                            break
                        o.write(b)
                        done += len(b)
                        if progress:
                            progress(done, total)
    return out_path


class Spike3SpkExtractPipeline(BasePipeline):
    PHASES = PHASES
    CATEGORIES = CATEGORIES

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 extract_categories=None, key_source=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        self.extract_categories = extract_categories
        self.key_source = key_source

    def _want(self, cat):
        return want_category(self.extract_categories, cat)

    def _run(self):
        self._set_phase(0)  # Detect
        if not is_spk_input(self.input_path):
            raise PipelineError("Detect", "Not a Stern Spike 3 .spk package.")
        title = _title_from_filename(self.input_path, "Spike 3")
        self._log("Detected .spk package: %s" % title, "success")

        ks = self.key_source or Spike3KeySource.discover(
            image_path=self.input_path)
        if ks is None or not ks.has_spk():
            raise PipelineError(
                "Detect",
                "No Spike 3 .spk key available.\n\nPut the fleet update keyfile "
                "at \"spk_keyfile\" in a padkeys.json beside the package, or "
                "point the PAD_SPIKE3_KEYFILE environment variable at one.")

        tmpdir = None
        try:
            # --- reconstruct (if a zip) -------------------------------------
            self._set_phase(1)
            low = self.input_path.lower()
            if low.endswith(".spk") and not zipfile.is_zipfile(self.input_path):
                spk_path = self.input_path
            else:
                tmpdir = tempfile.mkdtemp(prefix="pad_spk_")
                spk_path = os.path.join(tmpdir, "package.spk")
                self._log("Reconstructing package (this needs ~12 GB temp)...",
                          "info")
                r = reconstruct_spk(
                    self.input_path, spk_path,
                    progress=lambda d, t: self._progress(
                        int(d * 20 / max(t, 1)), 100,
                        "Reconstructing %.1f/%.1f GB" % (d / 1e9, t / 1e9)),
                    cancel=lambda: self._cancelled)
                self._check_cancel()
                if r is None:
                    raise PipelineError("Reconstruct package", "Canceled.")

            # --- unlock LUKS2 + open ext4 -----------------------------------
            # (still Prepare) unlock
            f = open(spk_path, "rb")
            try:
                header = spike3.read_luks_header(f, 0)
                header._pad_part_sectors = os.path.getsize(spk_path) // 512
                try:
                    mk = ks.spk_master_key(header)
                except Spike3KeyError as e:
                    raise PipelineError("Unlock", str(e))
                otp = spike3._luks_otp()
                if not otp.verify_master_key(header, mk):
                    raise PipelineError(
                        "Unlock", "The .spk key did not unlock this package.")
                self._log("Package unlocked.", "success")
                reader = spike3.DecryptingSegmentReader(f, 0, header, mk)
                ext = Ext4Reader(reader, 0, reader.size)
                nested = self._find_nested_spk(ext)
                if nested is None:
                    raise PipelineError("Read index",
                                        "No nested SPKS archive in the package.")

                # --- read the SPKS index ------------------------------------
                self._log("Reading archive index...", "info")
                inode = ext.read_inode(nested)
                arc = _spks.SpksArchive(
                    _spks.ext4_file_reader(ext, inode), inode["size"])
                self._log("Index: %d files." % len(arc.files), "info")

                os.makedirs(self.output_dir, exist_ok=True)
                counts = self._extract(arc)
            finally:
                f.close()
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        self._done(True, self._summary(counts))

    def _find_nested_spk(self, ext):
        node = ext.read_inode(2)
        for name, child, _t in ext._iter_dir(node):
            if name.endswith(".spk"):
                return child
        return None

    def _extract(self, arc):
        want_v, want_i = self._want("video"), self._want("images")
        want_s, want_a = self._want("scenes"), self._want("audio")
        videos, images, scenes, sounds = [], [], [], []
        radiums = {}   # scene dir -> scene.radium: what names the clips
        for fobj in arc.files:
            ext = os.path.splitext(fobj.path)[1].lower()
            base = os.path.basename(fobj.path).lower()
            if fobj.path.endswith("/scene.radium"):
                radiums[fobj.path[:-len("/scene.radium")]] = fobj
            if ext == ".png" and want_i:
                images.append(fobj)
            elif ext in (".radium", ".sidx") and want_s:
                scenes.append(fobj)
            elif is_sound_container(base) and want_a:
                sounds.append(fobj)
            elif ext == ".asset" and want_v:
                head = arc._read(fobj.offset, 12)
                if is_video_head(head):
                    videos.append((fobj, video_brand(head)))
        self._log("Found %d video, %d image, %d scene, %d sound container(s)."
                  % (len(videos), len(images), len(scenes), len(sounds)), "info")

        counts = {"video": 0, "images": 0, "scenes": 0, "audio": 0}
        if want_v:
            self._set_phase(2)
            counts["video"], _named = extract_videos(
                self, videos, lambda it: it[0].path, lambda it: it[0].size,
                lambda it: it[1], lambda it, out: arc.extract(it[0], out),
                radiums, lambda f: (b"".join(arc.read_file(f))
                                    if f.size <= _MAX_RADIUM else None))
        if want_i:
            self._set_phase(3)
            counts["images"] = self._copy(arc, images, "images")
        if want_s:
            self._set_phase(4)
            counts["scenes"] = self._copy(arc, scenes, "scenes")
        if want_a:
            self._set_phase(5)
            # image.bin is a plaintext PCM container: decode it to WAVs
            # PAD-1244: each image.bin's sounds named from the Sound Test
            # menu of the game program packed beside it
            games = {os.path.dirname(f.path.lstrip("/")): f for f in arc.files
                     if os.path.basename(f.path) == "game"}

            def game_of(d):
                f = games.get(d)
                return b"".join(arc.read_file(f)) if f is not None else None
            counts["audio"], counts["seconds"] = decode_sound_containers(
                self, sounds, lambda fobj: fobj.path,
                lambda fobj, out: arc.extract(fobj, out), game_of=game_of)
        return counts

    def _copy(self, arc, items, subdir):
        base = os.path.join(self.output_dir, subdir)
        total = len(items)
        done = 0
        for i, fobj in enumerate(items):
            self._check_cancel()
            rel = fobj.path.lstrip("/")
            out = os.path.join(base, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                arc.extract(fobj, out)
                done += 1
            except Exception as e:                           # noqa: BLE001
                self._log("skip %s: %s" % (fobj.path, e), "warn")
            self._progress(i + 1, total, "%s %d/%d" % (subdir, i + 1, total))
        return done

    def _summary(self, c):
        bits = summary_bits(c)
        return "Extracted %s to %s" % (", ".join(bits) if bits else "no files",
                                       self.output_dir)
