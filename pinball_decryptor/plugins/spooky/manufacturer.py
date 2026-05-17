"""Spooky Pinball manufacturer plugin."""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import detect_game as _detect_game
from .games import GAME_DB
from .pipeline import ExtractPipeline, WritePipeline


# Total Nuclear Annihilation ships .pkg files encrypted with an AES-256
# key that hasn't been recovered yet.  Every other Spooky title is
# decryptable in some form (.pkg with a known key, plain tar.gz, or via
# the Clonezilla restore image route).
_UNSUPPORTED_REASONS = {
    "total_nuclear": "AES-256-CBC key unknown - no Clonezilla image available either",
}

_GAMES = tuple(
    Game(
        key=k,
        display=info["display"],
        manufacturer_key="spooky",
        supported=(k not in _UNSUPPORTED_REASONS),
        unsupported_reason=_UNSUPPORTED_REASONS.get(k, ""),
    )
    for k, info in GAME_DB.items()
)


class SpookyManufacturer(Manufacturer):
    key = "spooky"
    display = "Spooky Pinball"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=True,
    )
    input_spec = InputSpec(
        label="Spooky game files",
        extensions=(".pkg", ".ed", ".scooby", ".beetlejuice", ".looney",
                    ".iso", ".zip"),
    )
    # Spooky flows: Extract = Detect → Decrypt → Checksums → Done.
    # Write     = Detect → Scan → Repack → Done.
    extract_phases = ("Detect", "Decrypt", "Checksums", "Done")
    write_phases = ("Detect", "Scan", "Repack", "Done")
    # Host-side gpg + ffmpeg are used directly via subprocess; the WSL
    # tools are only needed for Clonezilla .iso/.zip extraction.
    prerequisites = (
        Prerequisite(name="gpg", where="host",
                     probe="gpg --version",
                     reason="UM/H78 .pkg decrypt + Beetlejuice signing",
                     install_hint="winget install --id GnuPG.GnuPG"),
        Prerequisite(name="ffmpeg", where="host",
                     probe="ffmpeg -version",
                     reason="Audio resampling + P3 VID-to-MP4 conversion",
                     install_hint="winget install --id Gyan.FFmpeg"),
        Prerequisite(name="partclone", where="wsl",
                     probe="which partclone.ext4",
                     reason="Clonezilla restore image extraction",
                     install_hint="apt-get install partclone (in WSL)"),
        Prerequisite(name="debugfs", where="wsl",
                     probe="which debugfs",
                     reason="ext4 filesystem extraction",
                     install_hint="apt-get install e2fsprogs (in WSL)"),
        Prerequisite(name="zstd", where="wsl",
                     probe="which zstd",
                     reason="zstd-compressed Clonezilla images (BJ, LT)",
                     install_hint="apt-get install zstd python3-zstandard (in WSL)"),
    )

    def detect(self, path):
        gf = _detect_game(path)
        if gf is None:
            return None
        # Clonezilla images don't yield a game_key from format detection alone;
        # fall back to the partition-name detector for a friendlier badge.
        if gf.format_type == "clonezilla":
            try:
                from .clonezilla import (PARTITION_GAME_KEY,
                                         detect_clonezilla_game)
            except ImportError:
                return None
            part_key, _ = detect_clonezilla_game(path)
            if part_key is None:
                return None
            game_key = PARTITION_GAME_KEY.get(part_key, part_key)
            info = GAME_DB.get(game_key)
            if info is None:
                return None
            return Game(key=game_key, display=info["display"],
                        manufacturer_key="spooky", notes="Clonezilla image")

        if gf.game_key is None:
            return None
        info = GAME_DB.get(gf.game_key)
        if info is None:
            return None
        notes = ""
        if gf.format_type == "aes_pkg":
            notes = "AES-encrypted (key unknown)"
        return Game(key=gf.game_key, display=info["display"],
                    manufacturer_key="spooky", notes=notes)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
        )

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return WritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb,
        )

    def extract_input_help(self):
        return ("Extract a Spooky game file (.pkg, .ed, .scooby, "
                ".beetlejuice, .looney) or a Clonezilla restore image "
                "(.iso / .zip).")

    def write_install_help(self):
        return ("1. Copy the output file to the root of a USB drive.\n"
                "2. Use the per-game USB naming convention reported in the "
                "log (e.g. rm-gamecode-YYYYMMDD.pkg, vYYYY.MM.DD.HH.scooby).\n"
                "3. Insert USB into the machine and follow on-screen prompts.")
