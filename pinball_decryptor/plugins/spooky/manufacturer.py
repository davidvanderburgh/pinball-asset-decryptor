"""Spooky Pinball manufacturer plugin."""

import os

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import GENERATED_DIRS, detect_game as _detect_game
from .games import GAME_DB
from .pipeline import ExtractPipeline, WritePipeline


# Total Nuclear Annihilation ships .pkg files encrypted with an AES-256
# key that hasn't been recovered yet.  Every other Spooky title is
# decryptable in some form (.pkg with a known key, plain tar.gz, or via
# the Clonezilla restore image route).
_UNSUPPORTED_REASONS = {
    "total_nuclear": "AES-256-CBC key unknown - no Clonezilla image available either",
}

_GAMES = tuple(sorted(
    (Game(
        key=k,
        display=info["display"],
        manufacturer_key="spooky",
        supported=(k not in _UNSUPPORTED_REASONS),
        unsupported_reason=_UNSUPPORTED_REASONS.get(k, ""),
    ) for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class SpookyManufacturer(Manufacturer):
    key = "spooky"
    display = "Spooky Pinball"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=True,
        replace_audio=True,
        # Spooky games ship their video as loose files inside the archive,
        # and Write re-packs the folder as it finds it, so those round-trip
        # as-is (the same loose-file path Replace-Audio already uses).  What
        # doesn't is the engine derivatives Extract generates — see
        # video_slot_dirs().
        replace_video=True,
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

    def video_slot_dirs(self, assets_dir):
        """Scan the tree the game shipped, not the scratch Extract generated.

        Every video a Spooky game ships is a loose file inside the archive,
        and Write re-packs the folder as it finds it, so all of them
        round-trip: Halloween alone carries 242 loose ``.webm`` under
        ``assets/dmd/animations/``.  What can't round-trip is what *we* wrote
        into the folder on Extract — the Unity / Godot / P3 derivatives in
        ``_extracted_assets/`` and the raw PCK dump in ``_pck_contents/``.
        Nothing feeds those back into their container, so they are scoped out
        of the scan here.

        This replaces an extension filter (``.ogv`` only) that had it exactly
        backwards: the only ``.ogv`` in an extract is a *derivative* Godot
        copy, so the filter surfaced the dead ends and hid every shipped
        ``.webm`` — which is why Halloween showed audio slots and no video
        ones at all (PAD-79).
        """
        if not assets_dir or not os.path.isdir(assets_dir):
            return None
        try:
            names = sorted(os.listdir(assets_dir))
        except OSError:
            return None
        if not any(n in GENERATED_DIRS for n in names):
            return None            # nothing of ours in there — scan it all
        return [os.path.join(assets_dir, n) for n in names
                if n not in GENERATED_DIRS
                and os.path.isdir(os.path.join(assets_dir, n))]

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
