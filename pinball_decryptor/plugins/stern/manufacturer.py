"""Stern Pinball manufacturer plugin (Spike 2 audio extract + replace).

The Spike 2 audio codec is fully reverse-engineered: every cat-0 sound decodes
from ``image.bin`` + ``game_real`` alone, and new audio re-encodes back in
bit-exact (size-neutral), mono and stereo, across all 32 codec scale-variants.
The engine drives the game firmware in an emulator (unicorn) to recover each
sound's per-position keystream, then inverts it analytically.

Audio here is NOT loose files inside the extract — it is packed/encoded inside
``image.bin`` — so this plugin uses a custom Extract (image.bin -> per-sound
.wav) + Write/Direct-SSD (edited .wav -> re-encode -> patch image.bin), not the
generic loose-file ``replace_audio`` tab (which only repacks .wav/.ogg the
normal Write copies verbatim).
"""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from ...core.transcribe import TranscribePipeline
from ...core.musicid import MusicIdPipeline
from ..pinmame_classic import capture as _wscapture
from ..pinmame_classic.formats import detect_game as _ws_detect
from ..pinmame_classic.games import GAME_DB as _PMC_GAME_DB
from .formats import detect_game, display_for_key
from .games import GAME_DB
from .pipeline import (SternDirectSsdExtractPipeline,
                       SternDirectSsdWritePipeline, SternExtractPipeline,
                       SternFlashImagePipeline, SternRevertPipeline,
                       SternWritePipeline)

# Stern handles two hardware eras under one picker entry:
#   * "spike2"    — the modern SD-card games (image.bin audio + ext4 assets),
#                   the full extract / write / replace / Direct-SD surface.
#   * "whitestar" — the classic 1999-2006 MAME-ROM games (Monopoly, Elvis,
#                   LOTR, Sopranos, etc.), shared with the PinMAME-capture
#                   pipeline the Data East / Sega entries use; capture-only.
# detect() reports the era of the loaded file; the GUI re-applies the
# capability-dependent layout when it changes (default era = spike2, so the
# Spike 2 flow is unchanged until a MAME .zip is loaded).  SAM (2006-2014)
# is a planned third era (sam.c).
_WHITESTAR_DB = {k: v for k, v in _PMC_GAME_DB.items()
                 if v["manufacturer"] == "Stern"}

_SPIKE2_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="stern",
         era="spike2")
    for k, info in GAME_DB.items())
_WHITESTAR_GAMES = tuple(sorted(
    (Game(key=k, display=v["display"], manufacturer_key="stern",
          notes=f"Whitestar {v['year']}", era="whitestar")
     for k, v in _WHITESTAR_DB.items()),
    key=lambda g: g.display.lower()))
_GAMES = _SPIKE2_GAMES + _WHITESTAR_GAMES

# Capture-only capabilities for the Whitestar era (no write/replace/Direct-SD
# — you can't repack a MAME ROM; extraction is a libpinmame attract capture).
_WHITESTAR_CAPS = Capabilities(extract=False, capture=True)
_WHITESTAR_PREREQS = (
    Prerequisite(name="ffmpeg", where="host", probe="ffmpeg -version",
                 reason="Rendering the captured DMD animations into MP4s.",
                 install_hint=(
                     "winget install Gyan.FFmpeg  (Windows)\n"
                     "brew install ffmpeg          (macOS)\n"
                     "apt-get install ffmpeg       (Linux)")),
)


class SternManufacturer(Manufacturer):
    key = "stern"
    display = "Stern Pinball"
    games = _GAMES
    # Spike 2 modding flow: Extract decodes image.bin -> per-sound .wav; Write
    # re-encodes edited .wav back into image.bin (size-neutral) and patches the
    # image.  The Direct path reads/writes the game SD card directly (Spike 2
    # stores its code + assets on an SD card).  NOTE: the framework names this
    # capability ``direct_ssd`` generically (= "physically-connected drive");
    # for Spike 2 that drive is an SD card, so all UI wording says "SD card".
    # NOTE: ``capabilities`` is an era-aware @property below — this is the
    # Spike-2-era value it returns by default.
    _SPIKE2_CAPS = Capabilities(
        extract=True,
        write=True,
        modpack=True,
        direct_ssd=True,
        # Audio is loose per-sound idxNNNN.wav in the extract output, so the
        # per-slot Replace Audio tab works: assignments are staged over those
        # WAVs and the Write pipeline re-encodes the changed ones into image.bin
        # (only the changed ones — Write diffs against .checksums.md5).
        replace_audio=True,
        # Video is loose H.264 .asset clips copied out to video/ (named from
        # scene.radium).  The Replace Video tab stages a replacement over each,
        # and Write patches it back into the SD-card image IN PLACE via the
        # ext4 file->disk map (size-neutral: the .asset isn't resized, so a
        # replacement is fit to the original's byte size — padded if smaller,
        # re-encoded down if larger, skipped if it still won't fit).
        replace_video=True,
        # Images are loose .png files on the card (UI art); the Replace Image
        # tab stages a replacement scaled to the original's dimensions, and
        # Write patches it back in place the same size-neutral way as video.
        replace_image=True,
        # Flash a pre-built SD-card image (.img/.raw) straight onto a card from
        # the GUI — a dd-style whole-image write, so users no longer need a
        # separate imaging tool (and the built-in size guard refuses an image
        # too big for the card, the failure monkeybug hit externally).
        flash_image=True,
        # On-screen LCD text lives in the .radium scene files; Extract pulls the
        # editable display strings out to text/strings.tsv, the Replace Text tab
        # lets the user edit them, and Write patches every matching occurrence
        # back into its radium in place (size-neutral: a replacement is padded
        # to the original's byte length, and one that's longer is rejected).
        replace_text=True,
        # Auto-transcribe: TMNT is full of spoken callouts; faster-whisper
        # (+VAD, which skips the music/SFX beds) renames voice WAVs by their
        # spoken text, keeping the idx prefix so Write still round-trips.
        transcribe=True,
        # Music ID: the jukebox song->index binding is unrecoverable from the
        # firmware (it lives in runtime game-rule logic), but band pins play
        # commercial recordings — so identify each full music track online via
        # AcoustID + MusicBrainz and name it by song (preferring the pin's band).
        music_id=True,
        # Per-type Extract checkboxes (default all on): audio decode is the slow
        # part (~minutes) and images now include hundreds of scene textures, so
        # let the user skip categories they don't need for a faster extract.
        extract_categories=(("audio", "Audio"), ("video", "Video"),
                            ("images", "Images"), ("text", "Text")),
    )
    # Accepts both Spike 2 SD-card images AND classic Whitestar MAME ROM zips;
    # detect() routes by extension and reports the era.
    input_spec = InputSpec(
        label="Stern SD-card image (Spike 2) or MAME ROM zip (Whitestar)",
        extensions=(".img", ".bin", ".raw", ".zip"),
    )
    _SPIKE2_EXTRACT_PHASES = ("Detect", "Locate partitions", "Extract video",
                              "Extract images", "Decode audio", "Checksums")
    write_phases = ("Detect", "Stage", "Re-encode", "Patch image")
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
    music_id_phases = ("Scan", "Identify", "Write CSV")
    # Direct-SD extract drives the same engine phases as the file Extract (its
    # phase indices 2-5 must line up), with phase 0/1 reworded for the card.
    direct_ssd_extract_phases = ("Read SD card", "Locate partitions",
                                 "Extract video", "Extract images",
                                 "Decode audio", "Checksums")
    direct_ssd_write_phases = ("Scan", "Re-encode audio", "Write to SD card")
    flash_phases = ("Check card", "Write image", "Flush")
    # "Revert all changes" fallback: re-derive originals with no .orig snapshot
    # straight from the source card.
    revert_phases = ("Read source", "Restore")
    # The decode/replace engine emulates the ARM game firmware via unicorn.
    _SPIKE2_PREREQS = (
        Prerequisite(name="unicorn", where="host",
                     probe="python:unicorn",
                     reason="Emulates the Spike firmware to recover the audio "
                            "codec keystream (decode + re-encode).",
                     install_hint="pip install unicorn"),
        Prerequisite(name="numpy", where="host",
                     probe="python:numpy",
                     reason="Audio sample math for decode / encode.",
                     install_hint="pip install numpy"),
        Prerequisite(name="capstone", where="host",
                     probe="python:capstone",
                     reason="Locates the codec's companding point to recover "
                            "the keystream when re-encoding replaced audio.",
                     install_hint="pip install capstone"),
        # Optional — only the Auto-transcribe action needs it; extract/write
        # work without it.
        Prerequisite(name="faster-whisper", where="host",
                     probe="python:faster_whisper",
                     reason="Auto-transcribe spoken callouts to name the WAVs.",
                     install_hint="pip install faster-whisper"),
        # Optional — Replace Audio/Video swap files already in the game's
        # format (wav/ogg) without it; ffmpeg is only needed to convert other
        # formats (mp3/flac/m4a/mp4...) or match the original's sample rate.
        # The Windows build bundles it (imageio-ffmpeg) and startup puts it on
        # PATH, so this normally shows green out of the box; on Mac/Linux the
        # frozen bundle does too.
        Prerequisite(name="ffmpeg", where="host",
                     probe="ffmpeg -version",
                     reason="Convert replacement audio/video to the game's "
                            "format + match sample rate (optional).",
                     install_hint=(
                         "winget install Gyan.FFmpeg  (Windows)\n"
                         "brew install ffmpeg          (macOS)\n"
                         "apt-get install ffmpeg       (Linux)")),
    )
    # Spike 2 ships on an SD card (not an ISO/SSD), so the source/destination
    # toggle reads in those terms (see Manufacturer defaults).
    extract_iso_label = "From SD-card image"
    extract_ssd_label = "From SD card"
    write_iso_label = "Build SD-card image"
    write_ssd_label = "Write to SD card"
    # Mirror the destination radio so the action button names what it does
    # (the generic "Build update" / "Apply Modifications" don't connect to
    # the SD-card wording above them).
    write_build_button = "Build SD-card image"
    write_direct_button = "Write to SD card"
    direct_medium_noun = "SD card"
    # The card is small removable media in a reader — bias the picker away
    # from large backup drives (see core.drives.pick_best_game_ssd).
    direct_target_kind = "sd_card"
    direct_safety_text = (
        "⚠ Power off the machine and remove the SD card before connecting "
        "it to this PC. Always keep a backup image of the original card.")

    # ------------------------------------------------------------------
    # Era-aware surface (Spike 2 SD-card vs Whitestar MAME capture)
    # ------------------------------------------------------------------

    def __init__(self):
        # Default to Spike 2 so the shipped flow is unchanged until a MAME
        # .zip is detected.  ``set_era`` is driven by the GUI off detect().
        self._era = "spike2"

    def set_era(self, era):
        self._era = "whitestar" if era == "whitestar" else "spike2"

    @property
    def capabilities(self):
        return _WHITESTAR_CAPS if self._era == "whitestar" else self._SPIKE2_CAPS

    @property
    def prerequisites(self):
        return _WHITESTAR_PREREQS if self._era == "whitestar" \
            else self._SPIKE2_PREREQS

    @property
    def extract_phases(self):
        return _wscapture.PHASES if self._era == "whitestar" \
            else self._SPIKE2_EXTRACT_PHASES

    @property
    def capture_phases(self):
        return _wscapture.PHASES

    def write_intro(self):
        return ("Re-pack your modified assets back onto the card — build a new "
                "SD-card image, or write the changes straight to the SD card.")

    def build_write_description(self):
        return ("Re-encode changed sounds and patch the replaced videos / "
                "images into a copy of the SD-card image (size-neutral). Write "
                "the resulting image back to a card with your imaging tool.")

    def direct_write_description(self):
        return ("Re-encode changed sounds and patch the replaced videos / "
                "images directly into the SD card, in place. Each replacement "
                "is fit to its original's size — audio is trimmed or padded to "
                "the original length; video/images are size-matched.")

    def audio_forces_length_match(self):
        # Spike 2 audio is a size-neutral codec patch: each sound is re-encoded
        # to its original slot length (longer trimmed, shorter padded) and the
        # body is written back in place — keeping a different length would
        # strand every following offset in image.bin. So trim/pad is mandatory,
        # not a user choice: the GUI forces the checkbox on and disables it.
        return True

    def audio_length_note(self):
        return ("Replacements are encoded size-neutral: each sound is fit to "
                "its original slot length (longer is trimmed, shorter padded "
                "with silence) and amplitude-limited into the codec's range.")

    def video_length_note(self):
        return ("Video is patched into the SD-card image in place, so each "
                "replacement is fit to its original clip's byte size: a small "
                "enough clip drops straight in, a larger one is automatically "
                "re-encoded down to fit, and one that still won't fit is "
                "skipped (left unchanged) — use a shorter / lower-resolution "
                "clip. Tick “Trim / pad” to also match the original length.")

    def image_note(self):
        return ("Each image is scaled to the original's pixel dimensions and "
                "patched into the SD-card image in place, so it's fit to the "
                "original's byte size: it drops straight in if it's small "
                "enough, is re-compressed (fewer colours) to fit if larger, and "
                "is skipped (left unchanged) if it still won't fit — use a "
                "simpler image.  Slots under scene_textures/ are the in-scene "
                "glyph/sprite atlases (BC3/DXT5); a replacement is auto-scaled to "
                "the atlas's exact dimensions, keeps its transparency, and is "
                "re-encoded losslessly to the slot — no byte-size limit.")

    def detect(self, path):
        # Route by extension: MAME ROM zip => classic Whitestar (capture
        # era); SD-card image => Spike 2.  detect() has no side effects (it's
        # also called to probe other manufacturers) — the era it reports on
        # the Game is applied to the live manufacturer by the GUI.
        if path.lower().endswith(".zip"):
            key = _ws_detect(path, _WHITESTAR_DB)
            if key is None:
                return None
            info = _WHITESTAR_DB[key]
            return Game(key=key, display=info["display"],
                        manufacturer_key="stern", era="whitestar",
                        notes=f"Whitestar {info['year']}, {info['dmd']} DMD")
        key = detect_game(path)
        if key is None:
            return None
        return Game(key=key, display=display_for_key(key, path),
                    manufacturer_key="stern", era="spike2",
                    notes="Spike 2 card image")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              extract_categories=None):
        return SternExtractPipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            extract_categories=extract_categories)

    def make_capture_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        # Whitestar era: libpinmame attract-mode DMD capture (same as the
        # Data East / Sega entries).
        return _wscapture.CapturePipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            game_db=_WHITESTAR_DB,
            duration_seconds=kwargs.get("duration_seconds", 180.0),
            frame_cb=kwargs.get("frame_cb"),
            capture_ready_cb=None)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return SternWritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None, extract_categories=None):
        return SternDirectSsdExtractPipeline(
            device_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override,
            extract_categories=extract_categories)

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return SternDirectSsdWritePipeline(
            device_path, assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def make_flash_pipeline(self, image_path, device_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return SternFlashImagePipeline(
            image_path, device_path, log_cb, phase_cb, progress_cb, done_cb)

    def make_revert_pipeline(self, source, assets_dir, rels,
                             log_cb, phase_cb, progress_cb, done_cb,
                             is_device=False, partition_override=None):
        """Build the fallback pipeline that re-derives pre-snapshot originals
        from the source card (the GUI calls this only for changed files with no
        ``.orig`` snapshot)."""
        return SternRevertPipeline(
            source, assets_dir, rels, log_cb, phase_cb, progress_cb, done_cb,
            is_device=is_device, partition_override=partition_override)

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

    def make_music_id_pipeline(self, assets_dir,
                               log_cb, phase_cb, progress_cb, done_cb,
                               rename_after=False):
        return MusicIdPipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

    def extract_input_help(self):
        return ("Select a Stern Spike 2 SD-card image (raw .img/.bin), or use "
                "the Direct SD option to read the card itself. Extract decodes "
                "its packed audio to per-sound WAVs (audio/) and copies out the "
                "LCD videos (video/). Tick Auto-transcribe to rename voice "
                "callouts by their spoken text.")
