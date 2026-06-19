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
from .formats import detect_game
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
    )
    input_spec = InputSpec(
        label="Stern Spike SD-card images",
        extensions=(".img", ".bin", ".raw"),
    )
    extract_phases = ("Detect", "Locate partitions", "Decode audio", "Checksums")
    write_phases = ("Detect", "Stage", "Re-encode audio", "Patch image")
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
    )
    beta = True
    badge = "BETA"

    def audio_length_note(self):
        return ("Replacements are encoded size-neutral: each sound is fit to "
                "its original slot length (longer is trimmed, shorter padded "
                "with silence) and amplitude-limited into the codec's range.")

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(key=key, display=info["display"],
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

    def extract_input_help(self):
        return ("Select a Stern Spike 2 SD-card image (raw .img/.bin), or use "
                "the Direct SD option to read the card itself. Extract decodes "
                "its packed audio to per-sound WAVs.")
