"""Dutch Pinball manufacturer plugin (The Big Lebowski + Alice in Wonderland)."""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import detect_game
from .games import GAME_DB
from .pipeline import (AaiwExtractPipeline, DpDirectSsdExtractPipeline,
                       DpDirectSsdWritePipeline, TblExtractPipeline,
                       TblWritePipeline, apply_delta)

_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="dp")
    for k, info in GAME_DB.items()
)


class DutchPinballManufacturer(Manufacturer):
    key = "dp"
    display = "Dutch Pinball"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=True,
        decode_dmd=True, chain_deltas=True, direct_ssd=True,
        replace_audio=True,
    )
    # Direct-SSD: read/write the game's physical SSD without an .img/.zip.
    direct_ssd_extract_phases = ("Copy from SSD", "Checksums")
    direct_ssd_write_phases = ("Scan", "Write to SSD")
    input_spec = InputSpec(
        label="Dutch Pinball files",
        extensions=(".zip", ".img"),
    )
    # The optional "decode DMD" checkbox toggles the colour dot-matrix shader
    # on TBL's decoded videos.  Off by default; the shader upscales 8x and
    # adds bloom, so it makes the decode noticeably slower.
    decode_dmd_label = ("Apply dot-matrix (DMD) display effect to "
                        "Big Lebowski videos (slower extract)")
    # Guidance shown beside the "updates to merge on top" picker.  Big
    # Lebowski releases are ALL "delta" zips, but the large ones are
    # complete; the user needs to start from a complete base.
    chain_deltas_help = (
        "Big Lebowski downloads are all 'delta' zips, but the large ones "
        "contain everything. Use a COMPLETE base as the Input above — the "
        "newest is v1.10, the ~997 MB download (the variant that installs "
        "'from version 0.58+', NOT the 80 MB 'from 1.01+' file). Then add "
        "the newest delta here (e.g. v1.15) to merge up to the latest — they "
        "are cumulative, so usually one delta is enough.\n"
        "Downloads: dutchpinball.com/the_big_lebowski_pinball_software")
    # Extract: Detect → Extract (unzip + baseline + merge deltas) → Decode
    # (TBL cdmd videos) → Finalize.
    extract_phases = ("Detect", "Extract", "Decode", "Finalize")
    # AAIW reconstruction prefers local 7-Zip (reads MBR + ext4 directly,
    # ~15x faster, no WSL).  WSL2 is only the fallback when 7-Zip is absent.
    # No partclone/zstd/debugfs binaries: those are handled in pure Python.
    prerequisites = (
        Prerequisite(name="WSL2", where="wsl",
                     probe="echo ok",
                     reason="Alice in Wonderland .img extraction (fallback; "
                            "7-Zip is preferred and needs no WSL)",
                     install_hint="Install 7-Zip (7-zip.org), or "
                                  "wsl --install -d Ubuntu"),
    )

    @staticmethod
    def _is_aaiw_input(input_path):
        # AAIW ships as a Clonezilla .img; TBL as a .zip.  The dot-matrix
        # shader and delta-merging are TBL-only, so they must hide for AAIW.
        return bool(input_path) and input_path.lower().endswith(".img")

    def decode_dmd_applies(self, input_path):
        # Both games have an optional video-processing toggle: a dot-matrix
        # shader for TBL, a ProRes->MP4 convert for AAIW.
        return self.capabilities.decode_dmd

    def decode_dmd_label_for(self, input_path):
        if self._is_aaiw_input(input_path):
            return ("Convert ProRes videos to MP4 (playable everywhere; "
                    "slower extract)")
        return self.decode_dmd_label

    def chain_deltas_applies(self, input_path):
        # Delta-merging is TBL-only (AAIW ships a full SSD image).
        return self.capabilities.chain_deltas and not self._is_aaiw_input(input_path)

    def audio_length_note(self):
        # Verified against the assets: each track's only sidecar is a
        # `volume: X` file — no duration / loop-length metadata anywhere — so
        # the engine plays the .wav as-is and loops it. Any length works.
        return ("Dutch Pinball plays tracks at their own length (the engine "
                "loops them), so no trimming is needed — leave “Trim / "
                "pad” off to keep your full song.")

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        notes = ("Clonezilla installer image" if key == "aaiw"
                 else "Software update")
        return Game(key=key, display=info["display"],
                    manufacturer_key="dp", notes=notes)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              decode_dmd=False, deltas=None):
        # `decode_dmd` is the GUI's dot-matrix-shader toggle; `deltas` is the
        # optional list of delta updates to merge on top.  Both apply to TBL
        # only — AAIW ships real video and a full SSD image, so it ignores
        # them.
        if detect_game(input_path) == "aaiw":
            # For AAIW the toggle means "convert ProRes .mov -> H.264 .mp4".
            return AaiwExtractPipeline(
                input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
                convert_video=decode_dmd)
        return TblExtractPipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            dmd=decode_dmd, deltas=deltas)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return TblWritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return DpDirectSsdExtractPipeline(
            device_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return DpDirectSsdWritePipeline(
            device_path, assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def apply_delta(self, assets_dir, delta_path,
                    log_cb=None, progress_cb=None):
        return apply_delta(assets_dir, delta_path,
                           log_cb=log_cb, progress_cb=progress_cb)

    def extract_input_help(self):
        return ("Extract a Big Lebowski update `.zip` (full or delta), or an "
                "Alice's Adventures in Wonderland full-image `.img`.")

