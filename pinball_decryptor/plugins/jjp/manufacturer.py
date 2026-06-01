"""Jersey Jack Pinball manufacturer plugin.

Wraps the upstream JJP standalone (dongle-free) pipelines into the
unified manufacturer contract.  Two flows are exposed:

  * ISO-based — Extract / Write / Mod Pack on a Clonezilla ``.iso``.
    Uses the StandaloneDecryptPipeline / StandaloneModPipeline.

  * Direct-SSD — Extract / Write directly against a physically
    connected game SSD.  Uses DirectSSDDecryptPipeline /
    DirectSSDModPipeline.  The GUI toggles between the two via a
    radio button group on the Extract and Write tabs.

The dongle-bearing pipelines are still not exposed — they require
physical HASP hardware that's a thin layer of users.
"""

import os
import shutil

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from . import config
from .games import GAME_DB, detect_iso_game
from .pipeline import (DirectSSDDecryptPipeline, DirectSSDModPipeline,
                       StandaloneDecryptPipeline, StandaloneModPipeline)


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="jjp")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


def _find_fl_dat(candidate_dirs):
    """Locate ``fl_decrypted.dat`` in any of the given folders.

    The JJP Decrypt phase writes ``fl_decrypted.dat`` (the
    file-list metadata — filler sizes + CRC32 per file) into its
    output folder; the Write phase needs that metadata to forge
    checksums that pass the game's integrity check.  The standalone
    decryptor searched several folders (output, modify_input,
    write_input); for the unified app we look in whatever folder
    the GUI hands us (the assets folder for Write, the output folder
    for Extract).  Returns the first match or None.
    """
    for d in candidate_dirs:
        if not d:
            continue
        candidate = os.path.join(d, "fl_decrypted.dat")
        if os.path.isfile(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Constructor adapters
# ---------------------------------------------------------------------------
# The upstream pipelines take an extra ``fl_dat_path`` (cached file list).
# We pass ``None`` so they auto-scan the mounted partition — slower on the
# first run but works without any pre-cached state.

class _ExtractWrapper(StandaloneDecryptPipeline):
    def __init__(self, image_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 extract_graphics=True, extract_sounds=True,
                 full_dump=False):
        super().__init__(
            image_path=image_path,
            output_path=output_dir,
            fl_dat_path=None,
            log_cb=log_cb, phase_cb=phase_cb,
            progress_cb=progress_cb, done_cb=done_cb,
            extract_graphics=extract_graphics,
            extract_sounds=extract_sounds,
            full_dump=full_dump,
        )


class _WriteWrapper(StandaloneModPipeline):
    """Adapter for the JJP write pipeline.

    The upstream pipeline writes ``<assets_folder>/<iso_name>_modified.iso``
    and exposes no parameter to redirect that.  We intercept ``done_cb``
    on success and move the produced ISO to the user's chosen
    ``output_path`` (across drives if necessary), so the unified GUI's
    Output Folder field actually does something.
    """

    def __init__(self, original_path, assets_dir, output_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        self._target_output_path = output_path
        self._user_log_cb = log_cb
        self._user_done_cb = done_cb
        super().__init__(
            image_path=original_path,
            assets_folder=assets_dir,
            fl_dat_path=None,
            log_cb=log_cb, phase_cb=phase_cb,
            progress_cb=progress_cb,
            done_cb=self._intercept_done,
        )

    def _intercept_done(self, success, summary):
        if not success:
            self._user_done_cb(False, summary)
            return
        new_summary = self._move_output(summary)
        self._user_done_cb(True, new_summary)

    def _move_output(self, original_summary):
        """Move the JJP-produced ISO to the user-chosen output path.

        Returns an updated summary string mentioning the final location.
        Logs an error and returns the original summary if the move fails;
        the user can still find the ISO in the assets folder.
        """
        # Upstream writes to <assets_folder>/<iso_basename>_modified.iso —
        # see ModPipeline._build_iso (line ~2484).  The pipeline also stashes
        # the host-side path on `_output_iso_path` once it's written; prefer
        # that when present, fall back to reconstructing it.
        produced = getattr(self, "_output_iso_path", None)
        if not produced:
            iso_basename = os.path.splitext(
                os.path.basename(self.image_path))[0]
            produced = os.path.join(
                self.assets_folder, f"{iso_basename}_modified.iso")

        target = self._target_output_path
        if not target:
            return original_summary
        if os.path.abspath(produced) == os.path.abspath(target):
            return original_summary
        if not os.path.isfile(produced):
            self._user_log_cb(
                f"Expected output ISO not found at {produced} — leaving "
                f"summary as-is.", "error")
            return original_summary

        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            if os.path.exists(target):
                os.remove(target)
            # shutil.move handles cross-drive moves on Windows where
            # os.rename would raise OSError(EXDEV).
            shutil.move(produced, target)
            self._user_log_cb(
                f"Moved output ISO to: {target}", "success")
            return f"{original_summary}\n\nFinal output: {target}"
        except OSError as e:
            self._user_log_cb(
                f"Could not move output to {target}: {e}\n"
                f"The ISO is still available at: {produced}", "error")
            return original_summary


# ---------------------------------------------------------------------------
# Manufacturer
# ---------------------------------------------------------------------------

class JJPManufacturer(Manufacturer):
    key = "jjp"
    display = "Jersey Jack Pinball"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=True,
        # Direct-SSD: read/write against the game SSD directly (no
        # ISO intermediate).  Surfaces the "From ISO / From SSD"
        # radio on the Extract + Write tabs.
        direct_ssd=True,
        # Per-category Extract filters: surfaces Graphics / Sounds /
        # File System checkboxes on the Extract tab.  Maps to the
        # standalone pipeline's extract_graphics / extract_sounds /
        # full_dump knobs.
        asset_filters=True,
        replace_audio=True,
    )
    input_spec = InputSpec(
        label="JJP game ISOs",
        extensions=(".iso",),
    )
    # JJP standalone flows — see jjp/config.py STANDALONE_PHASES /
    # STANDALONE_MOD_PHASES.  Mod has 7 phases vs. the unified 4-step
    # default; declaring them explicitly avoids silent overflow.
    extract_phases = ("Extract", "Mount", "Decrypt", "Cleanup")
    write_phases = ("Scan", "Extract", "Prepare", "Encrypt", "Convert",
                    "Build ISO", "Cleanup")
    # Direct-SSD flows — see jjp/config.py DIRECT_SSD_PHASES /
    # DIRECT_SSD_MOD_PHASES.  The ISO extract + build phases are
    # gone since we're reading/writing the SSD directly.
    direct_ssd_extract_phases = tuple(config.DIRECT_SSD_PHASES)
    direct_ssd_write_phases = tuple(config.DIRECT_SSD_MOD_PHASES)
    # JJP runs entirely through the executor (WSL on Windows, Docker on
    # macOS).  Six WSL-side tools cover the standalone Decrypt + Mod
    # flows.
    prerequisites = (
        Prerequisite(name="partclone", where="wsl",
                     probe="which partclone.ext4",
                     reason="ISO partition extraction",
                     install_hint="apt-get install partclone (in WSL)"),
        Prerequisite(name="debugfs", where="wsl",
                     probe="which debugfs",
                     reason="ext4 filesystem extraction",
                     install_hint="apt-get install e2fsprogs (in WSL)"),
        Prerequisite(name="xorriso", where="wsl",
                     probe="which xorriso",
                     reason="ISO rebuild for Write pipeline",
                     install_hint="apt-get install xorriso (in WSL)"),
        Prerequisite(name="pigz", where="wsl",
                     probe="which pigz",
                     reason="Parallel gzip - speeds up large image work",
                     install_hint="apt-get install pigz (in WSL)"),
        Prerequisite(name="ffmpeg", where="wsl",
                     probe="which ffmpeg",
                     reason="Audio processing for Write pipeline",
                     install_hint="apt-get install ffmpeg (in WSL)"),
    )

    def audio_length_note(self):
        return ("Jersey Jack automatically matches every track to its original "
                "slot length on Write — a longer replacement is trimmed to fit "
                "and a shorter one padded with silence, regardless of the "
                "“Trim / pad” box.")

    def detect(self, path):
        if not path.lower().endswith(".iso"):
            return None
        key, display = detect_iso_game(path)
        if key is None:
            return None
        return Game(key=key, display=display, manufacturer_key="jjp")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              extract_graphics=True, extract_sounds=True,
                              full_dump=False):
        return _ExtractWrapper(input_path, output_dir,
                               log_cb, phase_cb, progress_cb, done_cb,
                               extract_graphics=extract_graphics,
                               extract_sounds=extract_sounds,
                               full_dump=full_dump)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return _WriteWrapper(original_path, assets_dir, output_path,
                             log_cb, phase_cb, progress_cb, done_cb)

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None,
            extract_graphics=True, extract_sounds=True,
            full_dump=False):
        # If a prior Decrypt put fl_decrypted.dat in the output
        # folder, reuse it — the upstream scan-for-filler-sizes pass
        # is slow on first run and skippable when we already have
        # the file list.  None falls back to auto-scan.
        return DirectSSDDecryptPipeline(
            device_path=device_path, output_path=output_dir,
            fl_dat_path=_find_fl_dat([output_dir]),
            log_cb=log_cb, phase_cb=phase_cb,
            progress_cb=progress_cb, done_cb=done_cb,
            partition_override=partition_override,
            extract_graphics=extract_graphics,
            extract_sounds=extract_sounds,
            full_dump=full_dump)

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        # The Direct-SSD encrypt pass NEEDS fl_decrypted.dat — without
        # the file-list metadata (filler sizes + CRC32) it can't
        # forge checksums that pass the game's integrity check, so
        # it bails with "no fl_decrypted.dat is available" rather
        # than producing a broken SSD.  Look for it in the user's
        # assets folder; the standalone Decrypt always writes one
        # there.
        return DirectSSDModPipeline(
            device_path=device_path, assets_folder=assets_dir,
            fl_dat_path=_find_fl_dat([assets_dir]),
            log_cb=log_cb, phase_cb=phase_cb,
            progress_cb=progress_cb, done_cb=done_cb,
            partition_override=partition_override)

    def extract_input_help(self):
        return ("Decrypt a Jersey Jack Pinball game ISO (Wonka, Guns N' "
                "Roses, Hobbit, Godfather, Avatar, Wizard of Oz, Pirates, "
                "Toy Story 4, Dialed In, Harry Potter). Requires WSL2 "
                "(Windows) / Docker (macOS) with partclone, debugfs, xorriso.")

    def write_install_help(self):
        return ("1. The modified ISO is written to the chosen Output Folder.\n"
                "2. Burn it to a USB drive with Rufus / Etcher.\n"
                "3. Boot the JJP machine from the USB to flash the new game "
                "image.")
