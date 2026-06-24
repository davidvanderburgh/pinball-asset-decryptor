"""Extract pipeline for the PinMAME classic-DMD plugins.

Foundation milestone: identifies the game from its MAME ROM zip and
unpacks the catalogued ROM set (CPU, DMD-display, sound) into the output
folder with a metadata sidecar.  The DMD-animation decoder (which turns
the DMD-display ROM into PNG scenes + MP4s, per the game's ``dmd``
resolution) and the attract-mode audio capture are the next milestones —
this stage exists so detection, the picker entry, and the end-to-end GUI
flow are wired and verifiable now.
"""

import os
import zipfile

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from .formats import detect_game

PHASES = ("Detect", "Unpack ROM set", "Checksums")


class ExtractPipeline(BasePipeline):
    """Identify a classic-DMD MAME zip and unpack its ROM set."""

    extract_phases = PHASES

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb, game_db=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        # Brand-filtered catalogue from the calling manufacturer.
        self.game_db = game_db or {}

    def _run(self):
        # ---- Phase 0: detect ----
        self._set_phase(0)
        self._log("Detecting game...", "info")
        key = detect_game(self.input_path, self.game_db)
        if key is None:
            raise PipelineError(
                "Detect",
                f"Cannot identify a supported game from "
                f"{os.path.basename(self.input_path)}.")
        info = self.game_db[key]
        self._log(f"Game: {info['display']} "
                  f"({info['manufacturer']}, {info['year']}, "
                  f"{info['dmd']} DMD)", "success")
        self._check_cancel()

        game_dir = os.path.join(self.output_dir, key)
        roms_dir = os.path.join(game_dir, "roms")
        os.makedirs(roms_dir, exist_ok=True)

        # ---- Phase 1: unpack ROM set ----
        self._set_phase(1)
        with zipfile.ZipFile(self.input_path, "r") as zf:
            members = zf.infolist()
            for i, m in enumerate(members):
                self._check_cancel()
                self._progress(i, len(members),
                               f"unpacking {m.filename}")
                if m.is_dir():
                    continue
                # Flatten any internal paths — MAME zips are flat, but be safe.
                out = os.path.join(roms_dir, os.path.basename(m.filename))
                with zf.open(m) as src, open(out, "wb") as dst:
                    dst.write(src.read())
            self._progress(len(members), len(members), "unpacked")
        self._log(f"Unpacked {len([m for m in members if not m.is_dir()])} "
                  f"ROM file(s) to {roms_dir}", "success")

        self._write_info(game_dir, info)

        # ---- Phase 2: checksums ----
        self._set_phase(2)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            game_dir, log_cb=self._log, progress_cb=self._progress)

        self._done(
            True,
            f"{info['display']} identified and unpacked.\n\n"
            f"Output:            {game_dir}\n"
            f"Manufacturer:      {info['manufacturer']} ({info['year']})\n"
            f"DMD resolution:    {info['dmd']}\n"
            f"Files checksummed: {n}\n\n"
            "DMD-animation decoding and audio extraction are the next "
            "milestones for this manufacturer.")

    def _write_info(self, game_dir, info):
        path = os.path.join(game_dir, "game_info.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Game:         {info['display']}\n")
            f.write(f"Manufacturer: {info['manufacturer']}\n")
            f.write(f"Year:         {info['year']}\n")
            f.write(f"DMD:          {info['dmd']}\n")
            f.write(f"Romset family:{info['family']}\n")
            f.write(f"Source:       {os.path.basename(self.input_path)}\n")
