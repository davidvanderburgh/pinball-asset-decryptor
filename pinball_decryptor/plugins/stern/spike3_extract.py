"""Stern **Spike 3** extract pipeline — decrypt a secure SD-card image and pull
its asset tree out.

Spike 3 stores the game on an encrypted ``games`` partition (p6) whose ext4
filesystem carries the same asset formats as Spike 2:

* playable **videos** as QuickTime ``.asset`` files (``ftyp qt`` — renamed to
  ``.mov`` on the way out),
* **images** as ``.png``,
* **scenes** as ``.radium`` + ``.sidx``.

This pipeline decrypts p6 on the fly (:mod:`.spike3`), walks the tree once, and
copies those three categories into ``video/`` / ``images/`` / ``scenes/`` under
the output directory, preserving each file's path so names stay unique and
meaningful.  Every ``image.bin`` sound container is decoded straight to
per-sound WAVs (:mod:`.spike3_sound`, PAD-1077): ``sound/<path>/audio/
idxNNNN.wav`` beside where the container sat, so the main game's sounds and the
``spike3/spike_menu`` ones each get their own ``audio/``.  The raw container is
not kept (the WAVs are lossless and the card stays the source).  The
scene-renderer texture ``.asset`` blobs are not decoded here.

Keys are never in the repo: the pipeline asks
:class:`.spike3_keys.Spike3KeySource` (``$PAD_SPIKE3_KEYFILE`` / a
``<image>.padkeys.json`` sidecar, or one passed in) for the games-volume key.
A card we can't unlock still detects and reports cleanly.
"""

from __future__ import annotations

import os

from ...core.pipeline_base import BasePipeline, PipelineError
from . import spike3
from . import spike3_sound
from .spike3_keys import Spike3KeySource, Spike3KeyError
from .formats import _title_from_filename


# Shared Spike 3 extract phases, used by both the SD-image and the .spk
# pipelines so the GUI's phase indicator fits either run.  "Prepare" is unlock
# for an SD image, and reconstruct+unlock+index for a .spk package.
PHASES = ("Detect", "Prepare", "Extract video", "Extract images",
          "Extract scenes", "Extract sounds")

# (path extension or sniff) -> output category
_QUICKTIME_TAGS = (b"ftyp", b"moov", b"mdat", b"wide", b"skip")


#: categories the GUI can toggle (all on by default); "audio" is the Spike 2
#: key too, so the Extract tab's Audio box reads the same everywhere
CATEGORIES = (("audio", "Audio"), ("video", "Video"), ("images", "Images"),
              ("scenes", "Scenes"))


def want_category(cats, cat):
    """Is category *cat* ticked in *cats* (None/{} = everything)?  Audio is
    also off for the pre-PAD-1077 key ``sounds``."""
    if not cats:
        return True
    if cat == "audio" and not cats.get("sounds", True):
        return False
    return bool(cats.get(cat, True))


def decode_sound_containers(pipe, items, rel_of, extract_to):
    """Extract each image.bin in *items* and decode it to WAVs (PAD-1077).

    *rel_of(item)* is the container's path inside the card ("pokemon_le/
    image.bin"); *extract_to(item, out_path)* writes its bytes. The WAVs go to
    ``<output>/sound/<dir of rel>/audio/``, and the container is removed once
    they are all written; a container that fails to decode is left in place
    (with a warning) so nothing is lost. Returns ``(sounds, seconds)``."""
    base = os.path.join(pipe.output_dir, "sound")
    sounds, seconds = 0, 0.0
    for item in items:
        pipe._check_cancel()
        rel = rel_of(item).lstrip("/")
        out = os.path.join(base, rel.replace("/", os.sep))
        where = os.path.dirname(rel) or "."
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            pipe._progress(0, 1, "sound %s: copying container" % where)
            extract_to(item, out)
        except Exception as e:                               # noqa: BLE001
            pipe._log("skip %s: %s" % (rel, e), "warn")
            continue
        audio = os.path.join(os.path.dirname(out), "audio")

        def prog(done, total, where=where):
            if done == total or done % 25 == 0:
                pipe._progress(done, total, "sound %s: %d/%d"
                               % (where, done, total))
        try:
            got = spike3_sound.decode_container(out, audio, progress=prog,
                                                cancel=pipe._check_cancel)
        except ValueError as e:
            pipe._log("%s could not be decoded to WAVs (%s); the container "
                      "is kept as it is." % (rel, e), "warn")
            continue
        try:
            os.remove(out)
        except OSError:
            pass
        sounds += got["sounds"]
        seconds += got["seconds"]
        pipe._log("%s: %d sounds (%d mono, %d stereo, %.1f min) -> %s"
                  % (rel, got["sounds"], got["mono"], got["stereo"],
                     got["seconds"] / 60.0,
                     os.path.relpath(audio, pipe.output_dir)), "success")
    return sounds, seconds


def summary_bits(counts):
    """The "N video, N image, ..." pieces of a Spike 3 extract's summary."""
    bits = []
    if counts.get("video"):
        bits.append("%d video" % counts["video"])
    if counts.get("images"):
        bits.append("%d image" % counts["images"])
    if counts.get("scenes"):
        bits.append("%d scene" % counts["scenes"])
    if counts.get("audio"):
        bits.append("%d sound (%.0f min)" % (counts["audio"],
                                             counts.get("seconds", 0) / 60.0))
    return bits


def _is_quicktime(reader, inode):
    h = reader.peek(inode, 12)
    return len(h) >= 8 and h[4:8] in _QUICKTIME_TAGS


class Spike3ExtractPipeline(BasePipeline):
    """Decrypt a Spike 3 SD image and extract video/images/scenes."""

    PHASES = PHASES
    #: categories the GUI can toggle (all on by default)
    CATEGORIES = CATEGORIES

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 extract_categories=None, key_source=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        self.extract_categories = extract_categories
        self.key_source = key_source

    # -- helpers -------------------------------------------------------------
    def _want(self, cat):
        return want_category(self.extract_categories, cat)

    def _image_id(self):
        # Stern names cards "<title>_<edition>-<version>.Release.…"; the
        # "<title>-<version>" stem is the image id the keyfile can match.
        base = os.path.basename(self.input_path)
        return base.split(".", 1)[0]

    # -- run -----------------------------------------------------------------
    def _run(self):
        self._set_phase(0)  # Detect
        self._log("Detecting Stern Spike 3 card...", "info")
        if not spike3.is_spike3_card(self.input_path):
            raise PipelineError(
                "Detect",
                "Not a Stern Spike 3 secure SD-card image (expected the "
                "Spike 3 boot/LUKS partition layout).")
        title = _title_from_filename(self.input_path, "Spike 3")
        self._log("Detected: %s" % title, "success")
        self._check_cancel()

        self._set_phase(1)  # Unlock card
        f = open(self.input_path, "rb")
        try:
            parts = spike3.parse_partitions(f)
            games = spike3.partition_for_role(parts, "games")
            if games is None:
                raise PipelineError("Unlock card",
                                    "No encrypted games partition found.")
            ks = self.key_source or Spike3KeySource.discover(
                image_path=self.input_path, image_id=self._image_id())
            if ks is None or not ks.has_any():
                raise PipelineError(
                    "Unlock card",
                    "No Spike 3 decryption key available for this card.\n\n"
                    "Point PAD at a key with the PAD_SPIKE3_KEYFILE environment "
                    "variable or a \"<image>.padkeys.json\" file beside the "
                    "image. Without the key the encrypted partitions cannot be "
                    "read.")
            ks._image_id = ks._image_id or self._image_id()
            self._log("Unlocking games partition (%.1f GB)..."
                      % (games["sectors"] * 512 / 1e9), "info")
            try:
                reader = spike3.open_partition_ext4(f, games, ks, role="games")
            except Spike3KeyError as e:
                raise PipelineError("Unlock card", str(e))
            self._log("Partition unlocked.", "success")
            self._check_cancel()

            os.makedirs(self.output_dir, exist_ok=True)
            counts = self._extract_tree(reader)
        finally:
            f.close()

        summary = self._summary(counts)
        self._done(True, summary)

    def _extract_tree(self, reader):
        """Single walk of p6 -> bucket files into video/images/scenes/sounds."""
        want_video = self._want("video")
        want_images = self._want("images")
        want_scenes = self._want("scenes")
        want_sounds = self._want("audio")

        # Collect targets first (cheap: inode walk only), so progress has a
        # denominator and each phase can report n/total.
        videos, images, scenes, sounds = [], [], [], []
        self._log("Scanning asset tree...", "info")
        for path, ino, inode in reader.iter_regular_files(root_ino=2,
                                                          max_depth=12):
            ext = os.path.splitext(path)[1].lower()
            base = os.path.basename(path).lower()
            if ext == ".png" and want_images:
                images.append((path, inode))
            elif ext in (".radium", ".sidx") and want_scenes:
                scenes.append((path, inode))
            elif base == "image.bin" and want_sounds:
                sounds.append((path, inode))
            elif ext == ".asset" and want_video and _is_quicktime(reader, inode):
                videos.append((path, inode))
        self._log("Found %d video, %d image, %d scene, %d sound container(s)."
                  % (len(videos), len(images), len(scenes), len(sounds)), "info")

        counts = {"video": 0, "images": 0, "scenes": 0, "audio": 0}
        if want_video:
            self._set_phase(2)
            counts["video"] = self._copy_bucket(
                reader, videos, "video", rename_ext=".mov")
        if want_images:
            self._set_phase(3)
            counts["images"] = self._copy_bucket(reader, images, "images")
        if want_scenes:
            self._set_phase(4)
            counts["scenes"] = self._copy_bucket(reader, scenes, "scenes")
        if want_sounds:
            self._set_phase(5)
            # image.bin is a plaintext PCM container: decode it to WAVs
            counts["audio"], counts["seconds"] = decode_sound_containers(
                self, sounds, lambda it: it[0],
                lambda it, out: reader.extract_file(it[1], out))
        return counts

    def _copy_bucket(self, reader, items, subdir, rename_ext=None):
        total = len(items)
        base = os.path.join(self.output_dir, subdir)
        done = 0
        for i, (path, inode) in enumerate(items):
            self._check_cancel()
            rel = path.lstrip("/")
            if rename_ext:
                rel = os.path.splitext(rel)[0] + rename_ext
            out = os.path.join(base, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                reader.extract_file(inode, out)
                done += 1
            except Exception as e:                           # noqa: BLE001
                self._log("skip %s: %s" % (path, e), "warn")
            self._progress(i + 1, total, "%s %d/%d" % (subdir, i + 1, total))
        return done

    def _summary(self, counts):
        bits = summary_bits(counts)
        got = ", ".join(bits) if bits else "no"
        return "Extracted %s file(s) to %s" % (got, self.output_dir)
