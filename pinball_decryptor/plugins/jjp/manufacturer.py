"""Jersey Jack Pinball manufacturer plugin.

Wraps the upstream JJP standalone (dongle-free) pipelines into the unified
manufacturer contract.  The Direct-SSD and dongle-bearing pipelines are
intentionally not exposed here — they require physical hardware and would
need a richer GUI than the shared 4-phase shape provides.
"""

import os
import shutil

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .games import GAME_DB, detect_iso_game
from .pipeline import StandaloneDecryptPipeline, StandaloneModPipeline


_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="jjp")
    for k, info in GAME_DB.items()
)


# ---------------------------------------------------------------------------
# Constructor adapters
# ---------------------------------------------------------------------------
# The upstream pipelines take an extra ``fl_dat_path`` (cached file list).
# We pass ``None`` so they auto-scan the mounted partition — slower on the
# first run but works without any pre-cached state.

class _ExtractWrapper(StandaloneDecryptPipeline):
    def __init__(self, image_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(
            image_path=image_path,
            output_path=output_dir,
            fl_dat_path=None,
            log_cb=log_cb, phase_cb=phase_cb,
            progress_cb=progress_cb, done_cb=done_cb,
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

    def detect(self, path):
        if not path.lower().endswith(".iso"):
            return None
        key, display = detect_iso_game(path)
        if key is None:
            return None
        return Game(key=key, display=display, manufacturer_key="jjp")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return _ExtractWrapper(input_path, output_dir,
                               log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return _WriteWrapper(original_path, assets_dir, output_path,
                             log_cb, phase_cb, progress_cb, done_cb)

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
