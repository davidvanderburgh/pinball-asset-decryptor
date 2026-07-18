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
                 log_cb, phase_cb, progress_cb, done_cb,
                 version_date_override=None, loop_names=None):
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
            version_date_override=version_date_override,
            loop_names=loop_names,
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
        # Surfaces the "Update version date" control on the Write tab — the
        # game only applies a .fun dated newer than what's installed.
        write_version_date=True,
        # Surfaces the per-track "Loop" column on the Replace Audio tab — Dune
        # plays its mode-music stems once, so a shorter replacement goes
        # silent mid-mode unless we loop it at the resource level.  Defaulted
        # ON for "LOOP"-named tracks.
        audio_loop_inject=True,
        # Replace-Audio tab: BoF audio lives in the Godot PCK as imported
        # .sample/.oggvorbisstr binaries.  Extract writes editable .wav/.ogg
        # copies under pck/_EDITABLE ASSETS/; Write inverse-converts edits
        # there back into the PCK.  audio_slot_dirs() restricts the scan to
        # that folder so the dot-prefixed import cache never shows up.
        replace_audio=True,
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

    def image_info(self, path, assets_dir=None):
        # The .fun itself is opaque (encrypted PCK); the version date only
        # becomes readable once the update files are extracted.  The game
        # applies a .fun only if its date is strictly newer than what's
        # installed, so both dates matter when comparing releases.
        if not (assets_dir and os.path.isdir(assets_dir)):
            return []
        from .pipeline import peek_next_update_version
        baseline, next_date = peek_next_update_version(assets_dir)
        if baseline is None:
            return []
        return [("Firmware", [
            ("Version date", baseline.strftime("%Y.%m.%d")),
            ("Next Write will stamp", next_date),
        ])]

    def audio_slot_dirs(self, assets_dir):
        """Restrict the Replace-Audio scan to the ``_EDITABLE ASSETS``
        folder(s) — the only audio Write re-imports into the PCK.  Files
        anywhere else (the .godot import cache, raw pck resources) would be
        dead-ends if staged, so they're kept out of the slot list."""
        import os
        from .source_converter import EDITABLE_DIR_NAME
        roots = []
        for dirpath, dirnames, _files in os.walk(assets_dir):
            if EDITABLE_DIR_NAME in dirnames:
                roots.append(os.path.join(dirpath, EDITABLE_DIR_NAME))
        return roots or None

    def audio_slot_exts(self, assets_dir):
        """Only surface ``.wav`` slots.  The editable-folder re-import
        (inverse_converter, used for `_EDITABLE ASSETS/`) encodes ``.wav`` ->
        ``.sample`` but has no ``.ogg`` -> ``.oggvorbisstr`` encoder yet, so a
        staged ``.ogg`` would silently vanish at Write — better not to offer
        it.  (The pipeline's ``_ogg_to_oggvorbisstr`` only runs for loose
        source files with ``.import`` sidecars, not the editable folder.)"""
        return (".wav",)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return _ExtractWrapper(input_path, output_dir,
                               log_cb, phase_cb, progress_cb, done_cb)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb,
                            version_date_override=None, loop_names=None):
        return _WriteWrapper(original_path, assets_dir, output_path,
                             log_cb, phase_cb, progress_cb, done_cb,
                             version_date_override=version_date_override,
                             loop_names=loop_names)

    def extract_input_help(self):
        return ("Decrypt a Barrels of Fun `.fun` update file (Labyrinth, "
                "Dune, Winchester). Requires GPG and (optionally) GDRE Tools "
                "for Godot PCK extraction.")

    def write_install_help(self):
        return ("1. Copy the output .fun file to a USB drive (FAT32).\n"
                "2. Insert the USB drive into the machine and follow the "
                "on-screen update prompts.")
