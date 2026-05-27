"""Williams (WPC-era) extract pipeline.

Input is a MAME-style .zip containing the game ROM(s) and DCS sound
ROM(s).  We extract the game-ROM bytes, then hand them off to
:mod:`.wpc_extract` which walks the WPC master tables and emits PNG
scenes + MP4 animations + font sprite sheets.  DCS audio (when
present) is decoded by :mod:`.dcs_decode` in a separate phase.

Output layout::

    <output_dir>/
      <game_key>/
        dmd_scenes/
          scene_NNNN_encXX_OFFSET.png       (single plane)
          pairs/pair_NNNN.png               (paired 4-shade composite)
          browse.mp4                        (every scene at 2 fps)
          scenes.json                       (offsets + encoding stats)
        animations/
          anim_*.mp4                        (cinematics + sub-table anims)
        fonts/
          font_*.png                        (glyph sprite sheets)
        sounds/                             (DCS games only)
          track_*.wav
        roms/
          fshtl_5.rom
          ft_u18.l1
        scan_summary.txt
"""

import os
import zipfile

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from . import dcs_decode
from . import wpc_extract
from .formats import detect_game, list_game_roms
from .games import GAME_DB


PHASES = ("Detect", "Unzip", "Find tables", "Decode scenes",
          "Render animations", "Extract audio", "Cleanup")


class ExtractPipeline(BasePipeline):
    """Real WPC DMD decoder pipeline for Williams ROMs."""

    def __init__(self, zip_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.zip_path = zip_path
        self.output_dir = output_dir

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        key = detect_game(self.zip_path)
        if key is None:
            raise PipelineError(
                "Detect",
                f"Cannot identify game from: "
                f"{os.path.basename(self.zip_path)}\n\n"
                f"Expected a MAME ROM zip containing files like "
                f"`fshtl_5.rom`, `ww_lh6.rom`, or `nofe2_3x.rom`.\n"
                f"Known games: "
                f"{', '.join(info['display'] for info in GAME_DB.values())}.")
        info = GAME_DB[key]
        self._log(f"Game detected: {info['display']} "
                  f"({info['platform']}, {info['year']})", "success")
        self._check_cancel()

        game_dir = os.path.join(self.output_dir, key)
        rom_dir = os.path.join(game_dir, "roms")
        os.makedirs(rom_dir, exist_ok=True)

        # ---- Unzip ----
        self._set_phase(1)
        self._log("Extracting ROM files...", "info")
        game_roms, sound_roms = list_game_roms(self.zip_path, key)
        if not game_roms:
            raise PipelineError(
                "Unzip",
                f"No game ROM found inside {os.path.basename(self.zip_path)}.\n"
                f"Expected one of: {', '.join(info['game_roms'])}.")
        self._log(f"  game ROMs:  {', '.join(game_roms)}", "info")
        self._log(f"  sound ROMs: "
                  f"{', '.join(sound_roms) if sound_roms else '(none found)'}",
                  "info")
        with zipfile.ZipFile(self.zip_path, "r") as zf:
            for n in game_roms + sound_roms:
                self._check_cancel()
                zf.extract(n, rom_dir)

        # ---- Decode the WPC ROM ----
        rom_path = os.path.join(rom_dir, game_roms[0])
        with open(rom_path, "rb") as f:
            rom_bytes = f.read()

        self._set_phase(2)
        try:
            results = wpc_extract.extract_dmd_assets(
                rom_bytes,
                game_dir,
                source_label=os.path.basename(self.zip_path),
                log_cb=self._log,
                progress_cb=self._progress,
                check_cancel=self._check_cancel,
                phase_decode_cb=lambda: self._set_phase(3),
                phase_animate_cb=lambda: self._set_phase(4),
            )
        except wpc_extract.WpcDecodeError as e:
            raise PipelineError("Find tables", str(e))

        # ---- scan_summary.txt ----
        summary_path = os.path.join(game_dir, "scan_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Game: {info['display']}\n")
            f.write(f"Source: {os.path.basename(self.zip_path)}\n")
            f.write(f"ROM size: {results['rom_size']:,} bytes\n")
            f.write(f"Font table ptr      @ 0x{results['font_ptr_rom']:06X}\n")
            if results["graphics_ptr_rom"] is not None:
                f.write(f"Graphics table ptr  @ "
                        f"0x{results['graphics_ptr_rom']:06X}\n")
                f.write(f"Graphics table data @ "
                        f"0x{results['graphics_table']:06X}\n")
            if results["animation_ptr_rom"] is not None:
                f.write(f"Animation table ptr @ "
                        f"0x{results['animation_ptr_rom']:06X}\n")
            f.write(f"\nScenes rendered: {results['scenes']}\n")
            f.write(f"Pairs rendered:  {results['pairs']}\n")
            f.write("\nEncoding distribution:\n")
            for k in sorted(results["encoding_counts"]):
                f.write(f"  {k}: {results['encoding_counts'][k]}\n")

        # ---- Extract audio (DCS sound ROMs) — DCS games only ----
        # Pre-DCS games (YM2151 sound board) have no statically
        # decodable audio; they skip this phase and the GUI omits it
        # from the indicator, so the remaining phases renumber.
        dcs_track_count = 0
        cleanup_phase = 5
        if dcs_decode.is_dcs_rom(self.zip_path):
            self._set_phase(5)
            dcs_track_count = self._extract_dcs_audio(game_dir)
            cleanup_phase = 6

        # ---- Cleanup / checksums ----
        self._set_phase(cleanup_phase)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            game_dir, log_cb=self._log, progress_cb=self._progress)

        dcs_help = ""
        if dcs_track_count:
            dcs_help = ("\n  sounds/track_*.wav — every DCS music cue, "
                        "voice line, and sound effect, one WAV per "
                        "track (indexed in sounds/manifest.json).")

        self._log("Done.", "success")
        self._done(
            True,
            f"{info['display']} extracted.\n\n"
            f"Output:        {game_dir}\n"
            f"Scenes (PNGs): {results['scenes']}\n"
            f"4-shade pairs: {results['pairs']}\n"
            f"Animations:    {results['animations']}\n"
            f"Fonts:         {results['fonts']}\n"
            f"DCS tracks:    {dcs_track_count}\n"
            f"Files checksummed: {n}\n\n"
            f"What you get:\n"
            f"  dmd_scenes/scene_*.png — every still bitmap in the "
            f"ROM (jackpot splashes, mode-start screens).\n"
            f"  dmd_scenes/pairs/pair_*.png — 4-shade composites "
            f"where consecutive planes pair as low+high.\n"
            f"  animations/anim_*.mp4 — true game animations from "
            f"the WPC animation table, one MP4 per sequence.\n"
            f"  fonts/font_*.png — sprite-sheet strips of the DMD "
            f"glyph atlases (alphabet, numerals, punctuation)."
            + dcs_help)

    # ------------------------------------------------------------------
    # DCS audio extraction
    # ------------------------------------------------------------------

    def _extract_dcs_audio(self, game_dir):
        """Decode the game's DCS sound ROMs into per-track WAVs.

        DCS games (1993-1998) store music, speech, and SFX as
        compressed digital audio; :mod:`.dcs_decode` extracts every
        track via the bundled DCSExplorer decoder.  Pre-DCS games use
        the older YM2151 sound board, which can't be decoded
        statically — those are reported and skipped, no error.

        Returns the number of tracks extracted (0 when not a DCS game
        or the decoder is unavailable).
        """
        self._log("Decoding DCS sound ROMs...", "info")
        sounds_dir = os.path.join(game_dir, "sounds")
        try:
            result = dcs_decode.extract_dcs(
                self.zip_path, sounds_dir, log_cb=self._log)
        except Exception as e:
            self._log(f"  DCS audio extraction error: {e}", "warning")
            return 0
        if not result.is_dcs:
            self._log(f"  {result.message}", "info")
            return 0
        self._log(f"  {result.message} -> sounds/", "success")
        return len(result.tracks)
