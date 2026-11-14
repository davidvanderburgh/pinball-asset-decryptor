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
folders :mod:`.spike3_write` puts them back from.  The per-category music
banks ``image-scNN.bin`` beside an ``image.bin`` (the same container format)
decode into its folder as Spike 2's ``music_catNN_NNNN.wav`` (PAD-1185).

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

#: categories the GUI can toggle (all on by default); "audio" is the Spike 2
#: key too, so the Extract tab's Audio box reads the same everywhere
CATEGORIES = (("audio", "Audio"), ("video", "Video"), ("images", "Images"),
              ("scenes", "Scenes"))

#: the first-atom tags of a QuickTime / MP4 clip (``.asset`` sniff)
_QUICKTIME_TAGS = (b"ftyp", b"moov", b"mdat", b"wide", b"skip")


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


def decode_sound_containers(pipe, items, rel_of, extract_to, game_of=None):
    """Extract each sound container in *items* and decode it to WAVs
    (PAD-1077; the ``image-scNN.bin`` banks too, PAD-1185).

    *rel_of(item)* is the container's path inside the card ("pokemon_le/
    image.bin"); *extract_to(item, out_path)* writes its bytes. The WAVs go to
    ``<output>/sound/<dir of rel>/audio/``, and the container is removed once
    they are all written; a container that fails to decode is left in place
    (with a warning) so nothing is lost. Returns ``(sounds, seconds)``.

    *game_of(dir of rel)* gives the bytes of the ``game`` program in that
    folder, or ``None``: an ``image.bin``'s sounds are then named from its
    Sound Test menu (PAD-1244, :mod:`.spike3_requests`)."""
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
        if stem is None and game_of is not None:
            _name_sounds(pipe, game_of(os.path.dirname(rel)), out, audio)
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
        """Every sound container to WAVs in its project folder (spike3_write's
        :func:`.spike3_write.sound_dir`): ``audio/`` for the game's own, its
        music banks beside them as ``music_catNN_NNNN.wav``."""
        from . import spike3_write
        import tempfile
        sounds, seconds = 0, 0.0
        for card_path, node, folder, stem in spike3_write.project_sound_dirs(
                reader):
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
                        tmp, dest, progress=prog, cancel=self._check_cancel,
                        stem=stem)
                except ValueError as e:
                    self._log("%s could not be decoded to WAVs (%s)."
                              % (card_path, e), "warn")
                    continue
                if stem is None:
                    self._map_sounds(reader, card_path, tmp, dest,
                                     folder == spike3_write.GAME_SOUNDS)
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

    def _map_sounds(self, reader, card_path, image_path, audio_dir, main):
        """PAD-1244: an ``image.bin``'s sounds as a Spike 2 extract leaves them - named from
        the Sound Test menu of the ``game`` program beside it and, for the game's own (*main*),
        ``sound_requests.tsv`` for the Audio tab's Requests column (:mod:`.spike3_requests`).
        A previous extract's map goes first, so a card it cannot be read from says so."""
        from . import clip_sounds
        if main:
            try:
                os.remove(os.path.join(self.output_dir, clip_sounds.REQUESTS_TSV))
            except OSError:
                pass
        node = _node_at(reader, os.path.dirname(card_path.rstrip("/")) + "/game")
        _name_sounds(self, reader.read_file_bytes(node) if node else None, image_path,
                     audio_dir, self.output_dir if main else None)

    def _summary(self, counts):
        bits = summary_bits(counts)
        got = ", ".join(bits) if bits else "no"
        return "Extracted %s file(s) to %s" % (got, self.output_dir)


def _name_sounds(pipe, game_raw, image_path, audio_dir, map_dir=None):
    """Name the sounds decoded from *image_path* into *audio_dir* from the Sound Test menu of
    the game program *game_raw* (``None``: none beside it), and with *map_dir* write the
    request map there (:func:`.spike3_requests.map_sounds`)."""
    from . import spike3_requests
    if not game_raw:
        pipe._log("No game program beside %s, so its sounds keep their idx names."
                  % os.path.basename(audio_dir), "info")
        return
    pipe._progress(0, 1, "Reading the game's Sound Test names")
    spike3_requests.map_sounds(game_raw, image_path, map_dir, audio_dir=audio_dir,
                               log=pipe._log)


def _node_at(reader, path):
    """The inode of the regular file at *path* on the volume (``/fallout_le/game``), or
    ``None``."""
    from .ext4 import S_IFMT, S_IFREG
    ino = 2
    for part in [p for p in path.split("/") if p]:
        try:
            node = reader.read_inode(ino)
        except Exception:                                    # noqa: BLE001
            return None
        ino = next((c for n, c, _t in reader._iter_dir(node) if n == part), None)
        if ino is None:
            return None
    try:
        node = reader.read_inode(ino)
    except Exception:                                        # noqa: BLE001
        return None
    return node if (node["mode"] & S_IFMT) == S_IFREG else None


def _count_files(root, exts, skip=()):
    n = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        n += sum(1 for f in files if f.lower().endswith(exts))
    return n
