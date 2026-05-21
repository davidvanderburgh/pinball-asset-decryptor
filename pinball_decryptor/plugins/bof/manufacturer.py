"""Barrels of Fun (BOF) manufacturer plugin.

Wraps the existing BOF :class:`DecryptPipeline` / :class:`ModifyPipeline`
into the unified manufacturer contract (4-callback BasePipeline).
"""

import os

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .executor import create_executor
from .games import FUN_FILE_TO_GAME, GAME_DB
from .pipeline import DecryptPipeline, ModifyPipeline, detect_game


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="bof")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class _ExtractWrapper(DecryptPipeline):
    """Adapt the BOF DecryptPipeline ctor to the unified factory signature."""

    def __init__(self, fun_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(
            fun_path=fun_path,
            output_dir=output_dir,
            executor=create_executor(),
            log_cb=log_cb,
            phase_cb=phase_cb,
            progress_cb=progress_cb,
            done_cb=done_cb,
            unpack_pck=True,
        )


class _WriteWrapper(ModifyPipeline):
    """Adapt the BOF ModifyPipeline ctor to the unified factory signature."""

    def __init__(self, original_path, assets_dir, output_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        game_key = detect_game(original_path)
        if game_key is None:
            # Defer the friendly error to run() — done_cb is the only way to
            # surface it through the unified GUI flow.
            self._init_failed = (
                f"Unrecognised .fun file: {os.path.basename(original_path)}\n"
                f"Expected one of: {', '.join(FUN_FILE_TO_GAME.keys())}")
            # Use any valid game_key just to satisfy the parent ctor; run()
            # will short-circuit before touching it.
            game_key = next(iter(GAME_DB))
        else:
            self._init_failed = None
        super().__init__(
            original_fun=original_path,
            assets_dir=assets_dir,
            output_fun_path=output_path,
            game_key=game_key,
            executor=create_executor(),
            log_cb=log_cb,
            phase_cb=phase_cb,
            progress_cb=progress_cb,
            done_cb=done_cb,
        )

    def run(self):
        if self._init_failed:
            self._done(False, self._init_failed)
            return
        super().run()


class BOFManufacturer(Manufacturer):
    key = "bof"
    display = "Barrels of Fun"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=False,
    )
    input_spec = InputSpec(
        label="Barrels of Fun game files",
        extensions=(".fun",),
    )
    # BOF flows match the upstream DECRYPT_PHASES / MODIFY_PHASES — see
    # plugins/bof/games.py.  5 phases each; the unified contract used to
    # silently clamp to 4.
    extract_phases = ("Detect", "Decrypt", "Extract", "Checksums", "Cleanup")
    write_phases = ("Decrypt", "Patch", "Repack", "Encrypt", "Cleanup")
    # BOF runs gpg + tar via the executor (WSL on Windows, native on
    # macOS/Linux), plus GDRE Tools (headless Godot RE) under xvfb to
    # repack the embedded PCK on Write.  All four show up in the
    # prereq panel so the user can see missing pieces at a glance
    # before kicking off a flow that's going to fail mid-pipeline.
    prerequisites = (
        Prerequisite(name="gpg", where="wsl",
                     probe="which gpg",
                     reason=".fun GPG decryption + re-encryption",
                     install_hint="apt-get install gnupg (in WSL)"),
        Prerequisite(name="tar", where="wsl",
                     probe="which tar",
                     reason="Archive packing/unpacking",
                     install_hint="apt-get install tar (in WSL)"),
        Prerequisite(
            name="gdre_tools", where="wsl",
            # Check the canonical install path directly — the exact
            # binary the installer writes (install_gdre.sh) and the
            # Write pipeline runs (see pipeline._gdre_prefix).  The old
            # probe used `which`, whose PATH lookup inside the WSL
            # invocation traverses the slow appended Windows PATH and
            # failed intermittently even with GDRE correctly installed.
            probe="test -x /opt/gdre_tools/gdre_tools.x86_64",
            reason="Godot RE Tools — required to repack the PCK on Write.",
            install_hint=(
                "Click \"Install Prerequisites\" — auto-downloads "
                "GDRE Tools to /opt/gdre_tools.")),
        Prerequisite(
            name="xvfb-run", where="wsl",
            probe="which xvfb-run",
            reason="Headless X server — GDRE Tools needs it on Linux/WSL.",
            install_hint="apt-get install xvfb (in WSL)"),
    )

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(key=key, display=info["display"], manufacturer_key="bof")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return _ExtractWrapper(input_path, output_dir,
                               log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return _WriteWrapper(original_path, assets_dir, output_path,
                             log_cb, phase_cb, progress_cb, done_cb)

    def extract_input_help(self):
        return ("Decrypt a Barrels of Fun `.fun` update file (Labyrinth, "
                "Dune, Winchester). Requires GPG and (optionally) GDRE Tools "
                "for Godot PCK extraction.")

    def write_install_help(self):
        return ("1. Copy the output .fun file to a USB drive (FAT32).\n"
                "2. Insert the USB drive into the machine and follow the "
                "on-screen update prompts.")
