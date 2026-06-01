"""American Pinball manufacturer plugin."""

from ...core.registry import Capabilities, Game, InputSpec, Manufacturer
from .formats import detect_game as _detect_game
from .games import GAME_DB
from .pipeline import ExtractPipeline, WritePipeline


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="ap")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class AmericanPinballManufacturer(Manufacturer):
    key = "ap"
    display = "American Pinball"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=False, apply_delta=False, iso=False,
        replace_audio=True,
    )
    input_spec = InputSpec(
        label="American Pinball game files",
        extensions=(".pkg",),
    )
    # AP .pkg flow: Extract = Detect → Decrypt → Checksums → Done.
    # Write     = Detect → Scan → Repack → Done.
    extract_phases = ("Detect", "Decrypt", "Checksums", "Done")
    write_phases = ("Detect", "Scan", "Repack", "Done")
    # Pure-Python: pycryptodome (AES) + stdlib zipfile.  No external tools.
    prerequisites = ()

    def detect(self, path):
        gf = _detect_game(path)
        if gf is None:
            return None
        info = GAME_DB.get(gf.game_key) if gf.game_key else None
        display = info["display"] if info else gf.game_name
        return Game(key=gf.game_key or "ap_pkg", display=display,
                    manufacturer_key="ap", notes=gf.notes)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return WritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def extract_input_help(self):
        return ("Extract an American Pinball '*-gamecode_*.pkg' update file "
                "(Houdini, Oktoberfest, Hot Wheels, Legends of Valhalla, "
                "Galactic Tank Force, Barry-O's BBQ). The package is an "
                "AES-256-CBC encrypted ZIP of the P-ROC game tree.")

    def write_install_help(self):
        return ("1. Copy the output .pkg to a USB drive formatted FAT32.\n"
                "2. Name it like the original ('<game>-gamecode_YYYY.MM.DD.pkg').\n"
                "3. Insert the USB drive and run CODE UPDATE from the coin-door "
                "menu.\n"
                "4. The machine decrypts, unzips, and reboots into the new code.")
