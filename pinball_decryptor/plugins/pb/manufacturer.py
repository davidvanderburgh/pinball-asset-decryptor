"""Pinball Brothers manufacturer plugin."""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import detect_game, detect_iso_game, is_iso_file, is_upd_file
from .games import GAME_DB
from .pipeline import (ExtractPipeline, IsoExtractPipeline, WritePipeline,
                       apply_delta)


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="pb")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class PBManufacturer(Manufacturer):
    key = "pb"
    display = "Pinball Brothers"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=True, iso=True,
        replace_audio=True,
    )
    input_spec = InputSpec(
        label="PB game files",
        extensions=(".upd", ".iso"),
    )
    # PB .upd extraction is pure stdlib (gzip+tar).  The optional .iso
    # path needs WSL + e2fsprogs/debugfs for Alien/Queen Clonezilla.
    prerequisites = (
        Prerequisite(name="debugfs", where="wsl",
                     probe="which debugfs",
                     reason="Alien/Queen Clonezilla .iso extraction",
                     install_hint="apt-get install e2fsprogs (in WSL)"),
    )

    def detect(self, path):
        path_lower = path.lower()
        if path_lower.endswith(".iso"):
            key = detect_iso_game(path)
        else:
            key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        notes = "Clonezilla ISO" if path_lower.endswith(".iso") else ""
        return Game(key=key, display=info["display"],
                    manufacturer_key="pb", notes=notes)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        if input_path.lower().endswith(".iso"):
            return IsoExtractPipeline(
                input_path, output_dir,
                log_cb, phase_cb, progress_cb, done_cb)
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return WritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def apply_delta(self, assets_dir, delta_path,
                    log_cb=None, progress_cb=None):
        return apply_delta(assets_dir, delta_path,
                           log_cb=log_cb, progress_cb=progress_cb)

    def extract_input_help(self):
        return ("Extract a Pinball Brothers `.upd` update file, or a "
                "Clonezilla `.iso` (Alien / Queen).")

    def write_install_help(self):
        return ("1. Copy the output .upd file to a USB drive formatted FAT32.\n"
                "2. With the machine running, insert the USB drive.\n"
                "3. From the coin door menu, select GAME UPDATE and press ENTER.\n"
                "4. The machine reboots automatically when the update finishes.")
