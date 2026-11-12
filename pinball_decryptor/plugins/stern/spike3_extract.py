"""Stern **Spike 3** extract pipeline — decrypt a secure SD-card image and pull
its asset tree out.

Spike 3 stores the game on an encrypted ``games`` partition (p6) whose ext4
filesystem carries the same asset formats as Spike 2:

* playable **videos** as QuickTime/MP4 ``.asset`` files, which the card keeps
  as numbers under a hash folder (``auto_loaded/<sha1>/scene.assets/2.asset/
  180.asset``),
* **images** as ``.png``,
* **scenes** as ``.radium`` + ``.sidx``.

This pipeline decrypts p6 on the fly (:mod:`.spike3`), walks the tree once, and
copies those three categories into ``video/`` / ``images/`` / ``scenes/`` under
the output directory.  Images and scenes keep their card path (their names are
already real ones).  A clip is named the way Spike 2 names it, by the scene
element that plays it (its ``scene.radium``, PAD-1185): ``video/fallout_le/
GrognakComic6.mp4``, with ``video/manifest.txt`` giving each one's card path;
the folder is the game's own (``fallout_le``, ``fallout_le/spike3/spike_menu``),
as the sounds' are.  Every ``image.bin`` sound container is decoded straight to
per-sound WAVs (:mod:`.spike3_sound`, PAD-1077): ``sound/<path>/audio/
idxNNNN.wav`` beside where the container sat, so the main game's sounds and the
``spike3/spike_menu`` ones each get their own ``audio/``; the per-category
music banks ``image-scNN.bin`` beside it decode there too, as Spike 2's
``music_catNN_NNNN.wav`` (PAD-1185).  The card names no sound: its program's
Sound Test lists numbers only.  The raw container is not kept (the WAVs are
lossless and the card stays the source).  The scene-renderer texture
``.asset`` blobs are not decoded here.

Keys are never in the repo: the pipeline asks
:class:`.spike3_keys.Spike3KeySource` (``$PAD_SPIKE3_KEYFILE`` / a
``<image>.padkeys.json`` sidecar, or one passed in) for the games-volume key.
A card we can't unlock still detects and reports cleanly.
"""

from __future__ import annotations

import os
import re

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


#: a per-category music bank beside image.bin; the number is its category, as
#: on Spike 2 (:func:`.spike2.category.read_category_id`)
_BANK_RE = re.compile(r"^image-sc(\d+)\.bin$", re.IGNORECASE)


def is_sound_container(name):
    """Is the card file *name* (a base name) a sound container: the game's
    ``image.bin`` or one of its ``image-scNN.bin`` music banks?"""
    low = name.lower()
    return low == "image.bin" or bool(_BANK_RE.match(low))


def _sound_stem(name):
    """The WAV name stem for the container *name*: ``None`` (``idxNNNN``) for
    image.bin, ``music_catNN`` for bank NN -- the Spike 2 names, which the
    Audio tab's kinds, song naming and name memory all key on."""
    m = _BANK_RE.match(name)
    return "music_cat%02d" % int(m.group(1)) if m else None


def _container_order(rel):
    d, name = os.path.split(rel.lstrip("/"))
    m = _BANK_RE.match(name)
    return (d, int(m.group(1)) if m else -1, name)


def decode_sound_containers(pipe, items, rel_of, extract_to):
    """Extract each sound container in *items* and decode it to WAVs
    (PAD-1077; the ``image-scNN.bin`` banks too, PAD-1185).

    *rel_of(item)* is the container's path inside the card ("pokemon_le/
    image.bin"); *extract_to(item, out_path)* writes its bytes. The WAVs go to
    ``<output>/sound/<dir of rel>/audio/``, and the container is removed once
    they are all written; a container that fails to decode is left in place
    (with a warning) so nothing is lost. Returns ``(sounds, seconds)``."""
    base = os.path.join(pipe.output_dir, "sound")
    sounds, seconds = 0, 0.0
    # image.bin first, then the banks in number order
    items = sorted(items, key=lambda it: _container_order(rel_of(it)))
    for item in items:
        pipe._check_cancel()
        rel = rel_of(item).lstrip("/")
        stem = _sound_stem(os.path.basename(rel))
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
                                                cancel=pipe._check_cancel,
                                                stem=stem)
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


# -- clip names (PAD-1185) ----------------------------------------------------
#: a scene.radium bigger than this is not parsed for names (Spike 2's guard)
_MAX_RADIUM = 0x2000000


def video_brand(head):
    """The container brand of a clip from its first 12 bytes: the ``ftyp``
    brand, or ``qt  `` for a QuickTime file that opens on another atom."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return bytes(head[8:12])
    return b"qt  "


def is_video_head(head):
    return len(head) >= 8 and head[4:8] in _QUICKTIME_TAGS


def video_group(card_path):
    """The folder a clip goes in under ``video/``: the directory on the card
    that holds its ``assets/`` (``fallout_le``, ``fallout_le/spike3/
    spike_menu``), so the game's clips and the service menu's keep apart the
    way their sounds do.  ``""`` for a clip outside any ``assets/``."""
    p = "/" + card_path.replace("\\", "/").lstrip("/")
    i = p.find("/assets/")
    return p[1:i] if i > 0 else ""


def name_videos(videos, radiums, read_radium):
    """The output path of each clip in *videos* (``[(card path, brand)]``),
    relative to ``video/``: ``"<group>/<name>.<mp4|mov>"`` with the name the
    clip's scene element gives it (Spike 2's naming,
    :func:`.engine._video_names`: duplicates ``_2``, ``_3`` ...; a clip no
    scene names is ``video_<scene hash8>_<ref>``).

    *radiums* is ``{scene dir: item}`` for every ``scene.radium`` on the card
    and *read_radium(item)* its bytes (``None`` to skip it).  Each is parsed
    at most once.  Returns ``[(rel path, named_from_scene)]`` in *videos*
    order."""
    from .engine import _parse_radium, _video_names
    cache = {}

    def title_for(path):
        if "/scene.assets/" not in path:
            return None
        hashdir, ref = path.rsplit("/scene.assets/", 1)
        item = radiums.get(hashdir)
        if item is None:
            return None
        if hashdir not in cache:
            try:
                data = read_radium(item)
                cache[hashdir] = _parse_radium(data) if data else {}
            except Exception:                                # noqa: BLE001
                cache[hashdir] = {}
        return cache[hashdir].get(ref)

    groups = {}
    for i, (path, _brand) in enumerate(videos):
        groups.setdefault(video_group(path), []).append(i)
    out = [None] * len(videos)
    for group, idxs in groups.items():
        names = _video_names([(videos[i][0], None, videos[i][1]) for i in idxs],
                             title_for)
        for i, (fname, titled) in zip(idxs, names):
            out[i] = ("%s/%s" % (group, fname) if group else fname, titled)
    return out


def _old_layout_copy(video_dir, card_path):
    """Where an extract before PAD-1185 put this clip: its card path with
    ``.mov`` for ``.asset``."""
    rel = os.path.splitext(card_path.lstrip("/"))[0] + ".mov"
    return os.path.join(video_dir, rel.replace("/", os.sep))


def _prune_empty(d, top):
    """Remove *d* and its parents up to (not including) *top* while empty."""
    top = os.path.normcase(os.path.abspath(top))
    d = os.path.abspath(d)
    while (os.path.normcase(d) != top
           and os.path.normcase(d).startswith(top + os.sep)):
        try:
            os.rmdir(d)
        except OSError:
            return
        d = os.path.dirname(d)


def extract_videos(pipe, items, path_of, size_of, brand_of, extract_to,
                   radiums, read_radium):
    """Write every clip in *items* to ``<output>/video/`` under its scene name
    (:func:`name_videos`), with ``video/manifest.txt`` (output, card path,
    bytes) the way Spike 2's extract writes it.

    A copy an older extract made of the same clip under its card path is
    removed (only those exact files, and the folders they leave empty), so a
    re-extract leaves one file per clip.  Returns ``(written, named)``."""
    video_dir = os.path.join(pipe.output_dir, "video")
    plan = name_videos([(path_of(it), brand_of(it)) for it in items],
                       radiums, read_radium)
    total = len(items)
    rows, done, named, stale = [], 0, 0, 0
    for i, (item, (rel, titled)) in enumerate(zip(items, plan)):
        pipe._check_cancel()
        out = os.path.join(video_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            extract_to(item, out)
        except Exception as e:                               # noqa: BLE001
            pipe._log("skip %s: %s" % (path_of(item), e), "warn")
            continue
        done += 1
        named += bool(titled)
        rows.append("%s\t%s\t%d" % (rel, path_of(item), size_of(item)))
        old = _old_layout_copy(video_dir, path_of(item))
        if (os.path.normcase(old) != os.path.normcase(out)
                and os.path.isfile(old)):
            try:
                os.remove(old)
                stale += 1
                _prune_empty(os.path.dirname(old), video_dir)
            except OSError:
                pass
        pipe._progress(i + 1, total, "video %d/%d" % (i + 1, total))
    if rows:
        with open(os.path.join(video_dir, "manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(rows) + "\n")
    if stale:
        pipe._log("Removed %d video(s) an earlier extract had saved under "
                  "their card path." % stale, "info")
    if done:
        pipe._log("%d of %d video(s) named from the game's scenes "
                  "(video/manifest.txt gives each one's place on the card)."
                  % (named, done), "success" if named else "info")
    return done, named


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
        radiums = {}   # scene dir -> scene.radium inode: what names the clips
        self._log("Scanning asset tree...", "info")
        for path, ino, inode in reader.iter_regular_files(root_ino=2,
                                                          max_depth=12):
            ext = os.path.splitext(path)[1].lower()
            base = os.path.basename(path).lower()
            if path.endswith("/scene.radium"):
                radiums[path[:-len("/scene.radium")]] = inode
            if ext == ".png" and want_images:
                images.append((path, inode))
            elif ext in (".radium", ".sidx") and want_scenes:
                scenes.append((path, inode))
            elif is_sound_container(base) and want_sounds:
                sounds.append((path, inode))
            elif ext == ".asset" and want_video:
                head = reader.peek(inode, 12)
                if is_video_head(head):
                    videos.append((path, inode, video_brand(head)))
        self._log("Found %d video, %d image, %d scene, %d sound container(s)."
                  % (len(videos), len(images), len(scenes), len(sounds)), "info")

        counts = {"video": 0, "images": 0, "scenes": 0, "audio": 0}
        if want_video:
            self._set_phase(2)
            counts["video"], _named = extract_videos(
                self, videos, lambda it: it[0], lambda it: it[1]["size"],
                lambda it: it[2],
                lambda it, out: reader.extract_file(it[1], out),
                radiums, lambda ino: (reader.read_file_bytes(ino)
                                      if ino["size"] <= _MAX_RADIUM else None))
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

    def _copy_bucket(self, reader, items, subdir):
        total = len(items)
        base = os.path.join(self.output_dir, subdir)
        done = 0
        for i, (path, inode) in enumerate(items):
            self._check_cancel()
            rel = path.lstrip("/")
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
