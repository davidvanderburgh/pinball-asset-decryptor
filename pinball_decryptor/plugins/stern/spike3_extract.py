"""Stern **Spike 3** extract pipeline - decrypt a secure SD-card image and pull
its asset tree out as a project the Replace tabs and Write work on (PAD-1186).

Spike 3 stores the game on an encrypted ``games`` partition (p6) whose ext4
filesystem carries Spike 2's own asset tree (``assets/lcd/<...>/scene.radium``
with its ``scene.assets`` clips, PNGs, ``image.bin``, ``spk/index/*.sidx``).
The volume is opened as one plaintext partition (:mod:`.spike3_card`) and the
Spike 2 extractors run over it unchanged, so a Spike 3 project is laid out
exactly as a Spike 2 one: ``video/`` (named from the scenes), ``images/``
(with ``scene_textures/`` and the scene layouts the Scenes tab draws),
``text/strings.tsv``, and the ``.checksums.md5`` baseline Write diffs against.

Sounds are plain PCM (:mod:`.spike3_sound`), one ``image.bin`` per sound set:
the game's go to ``audio/idxNNNN.wav`` (Spike 2's folder), another set to
``audio_<its folder>/`` (``audio_spike_menu``: the service menu's) - the
folders :mod:`.spike3_write` puts them back from.

The ``.spk`` update package (:mod:`.spike3_spk`) is a different input with no
card to write back to; it keeps its own file-copy layout and shares
:func:`decode_sound_containers` and the phases.

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


class Spike3ExtractPipeline(BasePipeline):
    """Decrypt a Spike 3 SD image and extract it as a Spike 2-shaped project
    (videos, images, scenes and their text, sounds, the checksum baseline)."""

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
        from . import spike3_card
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
        try:
            vol = spike3_card.open_games(self.input_path, key_source=ks)
        except (Spike3KeyError, ValueError) as e:
            raise PipelineError("Unlock card", str(e))
        try:
            self._log("Unlocked the games partition (%.1f GB)."
                      % (vol.size / 1e9), "success")
            self._check_cancel()
            os.makedirs(self.output_dir, exist_ok=True)
            from .ext4 import Ext4Reader
            counts = self._extract_project(Ext4Reader(vol, 0, vol.size))
        finally:
            vol.close()
        self._check_cancel()
        # the baseline Write and Mod Pack diff the project against
        from ...core.checksums import generate_checksums
        from ...core.staged_originals import discard as discard_snapshots
        discard_snapshots(self.output_dir)
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
        self._done(True, self._summary(counts))

    def _extract_project(self, reader):
        """The Spike 2 extractors over the decrypted games volume, then the
        sounds.  Returns the per-category counts for the summary."""
        from . import engine
        out = self.output_dir
        log, cancel = self._log, (lambda: self._cancelled)

        def prog(c, t, d=""):
            self._progress(c, max(t, 1), d)

        def step(what, fn, *a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:                       # noqa: BLE001
                log("%s failed (%s); continuing." % (what, e), "warning")
                return None

        counts = {"video": 0, "images": 0, "scenes": 0, "audio": 0}
        if self._want("video"):
            self._set_phase(2)
            step("Video extraction", engine.extract_videos, reader, out,
                 log=log, progress=prog, cancel=cancel)
            counts["video"] = _count_files(os.path.join(out, "video"),
                                           (".mov", ".mp4"))
            self._check_cancel()
        if self._want("images"):
            self._set_phase(3)
            step("Image extraction", engine.extract_images, reader, out,
                 log=log, progress=prog, cancel=cancel)
            counts["images"] = _count_files(os.path.join(out, "images"),
                                            (".png",), skip=("scene_textures",))
            self._check_cancel()
        if self._want("scenes"):
            self._set_phase(4)
            step("Scene-texture extraction", engine.extract_scene_textures,
                 reader, out, log=log, progress=prog, cancel=cancel)
            self._check_cancel()
            step("Scene-picture extraction", engine.extract_radium_images,
                 reader, out, log=log, progress=prog, cancel=cancel)
            self._check_cancel()
            from . import spine as _spine
            step("Spine extraction", _spine.extract_spine, reader, out,
                 log=log, progress=prog, cancel=cancel)
            self._check_cancel()
            step("Display-text extraction", engine.extract_radium_text,
                 reader, out, log=log, cancel=cancel)
            counts["scenes"] = _count_files(
                os.path.join(out, "images", "scene_textures"), (".png",),
                skip=("glyphs",))
            self._check_cancel()
        if self._want("audio"):
            self._set_phase(5)
            counts["audio"], counts["seconds"] = self._extract_sounds(reader)
        return counts

    def _extract_sounds(self, reader):
        """Every image.bin to WAVs in its project folder (spike3_write's
        :func:`.spike3_write.sound_dir`): ``audio/`` for the game's own."""
        from . import spike3_write
        import tempfile
        sounds, seconds = 0, 0.0
        for card_path, node, folder in spike3_write.project_sound_dirs(reader):
            self._check_cancel()
            dest = os.path.join(self.output_dir, folder)
            fd, tmp = tempfile.mkstemp(prefix="pad_s3_snd_", suffix=".bin")
            os.close(fd)
            try:
                self._progress(0, 1, "%s: copying the sound container" % folder)
                reader.extract_file(node, tmp)

                def prog(done, total, folder=folder):
                    if done == total or done % 25 == 0:
                        self._progress(done, total, "%s: %d/%d"
                                       % (folder, done, total))
                try:
                    got = spike3_sound.decode_container(
                        tmp, dest, progress=prog, cancel=self._check_cancel)
                except ValueError as e:
                    self._log("%s could not be decoded to WAVs (%s)."
                              % (card_path, e), "warn")
                    continue
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            sounds += got["sounds"]
            seconds += got["seconds"]
            self._log("%s: %d sounds (%d mono, %d stereo, %.1f min) -> %s"
                      % (card_path.lstrip("/"), got["sounds"], got["mono"],
                         got["stereo"], got["seconds"] / 60.0, folder),
                      "success")
        return sounds, seconds

    def _summary(self, counts):
        bits = summary_bits(counts)
        got = ", ".join(bits) if bits else "no"
        return "Extracted %s file(s) to %s" % (got, self.output_dir)


def _count_files(root, exts, skip=()):
    n = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        n += sum(1 for f in files if f.lower().endswith(exts))
    return n
