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
from .formats import detect_game, display_for_key
from .games import GAME_DB
from .pipeline import (SternDirectSsdExtractPipeline,
                       SternDirectSsdWritePipeline, SternExtractPipeline,
                       SternWritePipeline)

_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="stern")
    for k, info in GAME_DB.items()
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
    capabilities = Capabilities(
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
        # Auto-transcribe: TMNT is full of spoken callouts; faster-whisper
        # (+VAD, which skips the music/SFX beds) renames voice WAVs by their
        # spoken text, keeping the idx prefix so Write still round-trips.
        transcribe=True,
    )
    input_spec = InputSpec(
        label="Stern Spike SD-card images",
        extensions=(".img", ".bin", ".raw"),
    )
    extract_phases = ("Detect", "Locate partitions", "Extract video",
                      "Decode audio", "Checksums")
    write_phases = ("Detect", "Stage", "Re-encode", "Patch image")
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
    direct_ssd_extract_phases = ("Read SD card", "Decode audio", "Checksums")
    direct_ssd_write_phases = ("Scan", "Re-encode audio", "Write to SD card")
    # The decode/replace engine emulates the ARM game firmware via unicorn.
    prerequisites = (
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
    )
    beta = True
    badge = "BETA"
    # Spike 2 ships on an SD card (not an ISO/SSD), so the source/destination
    # toggle reads in those terms (see Manufacturer defaults).
    extract_iso_label = "From SD-card image"
    extract_ssd_label = "From SD card"
    write_iso_label = "Build SD-card image"
    write_ssd_label = "Write to SD card"

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

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        return Game(key=key, display=display_for_key(key, path),
                    manufacturer_key="stern",
                    notes="Spike 2 card image")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return SternExtractPipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return SternWritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return SternDirectSsdExtractPipeline(
            device_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return SternDirectSsdWritePipeline(
            device_path, assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

    def extract_input_help(self):
        return ("Select a Stern Spike 2 SD-card image (raw .img/.bin), or use "
                "the Direct SD option to read the card itself. Extract decodes "
                "its packed audio to per-sound WAVs (audio/) and copies out the "
                "LCD videos (video/). Tick Auto-transcribe to rename voice "
                "callouts by their spoken text.")
