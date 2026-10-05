"""Barrels of Fun (BOF) manufacturer plugin.

Wraps the existing BOF :class:`DecryptPipeline` / :class:`ModifyPipeline`
into the unified manufacturer contract (4-callback BasePipeline).
"""

import os
import sys

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .executor import create_executor
from .games import FUN_FILE_TO_GAME, GAME_DB
from .pipeline import DecryptPipeline, ModifyPipeline, detect_game


# ---------------------------------------------------------------------------
# Bon Jovi status + volunteer call-to-action
#
# Bon Jovi ships as a signed systemd disk image (GPT + dm-verity + a vendor
# signature), not the old GPG tarball.  Extracting and editing its assets works
# fully; building an installable update does not, because re-signing the image
# needs information we can only get from a physical machine.  These strings are
# shown in the app (Image Info / Extract / Write) so an owner knows what works
# and how they can help unlock image building.  No em dashes (shipped text).
# ---------------------------------------------------------------------------
BONJOVI_BADGE = ("Bon Jovi: you can extract assets, but changes can't be "
                 "built into an installable update yet (see Image Info).")

BONJOVI_WHY = ("Bon Jovi ships as a signed disk image, so rebuilding an "
               "installable update needs information we can only get from a "
               "physical machine.")

BONJOVI_HELP = (
    "If you own a Bon Jovi machine and want to help unlock image building and "
    "emulation, the most useful thing is a full image of the machine's "
    "internal drive (the NVMe), and whether a modified image can be written "
    "back to it. The same drive image also lets us build the emulator's board "
    "and switch profile. The game boots without a signature check, so a "
    "modified drive image runs as-is and no vendor key is needed. Rough steps: "
    "boot the machine from a Linux USB stick, image the internal NVMe to an "
    "external drive, and send the image over. Being able to write a test image "
    "back and report whether it boots would confirm the whole path. Get in "
    "touch first and we will walk you through it.")

# Shown when someone tries to emulate Bon Jovi (its .fun is a signed disk
# image the emulator can't open, and it has no hardware profile yet).
BONJOVI_EMU = (
    "Emulation is not available for Bon Jovi yet. Its .fun is a signed disk "
    "image, not the format the emulator opens, and the emulator also needs a "
    "board and switch profile for the machine, which we build from a real "
    "machine. You can still extract its assets to view or reuse. See the Image "
    "Info window for how you can help.")


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


def build_prerequisites(platform=None):
    """BOF's prerequisite rows, spelled for *platform* (``sys.platform`` by
    default; a capture passes ``"darwin"`` to show a Mac's).

    gpg and tar are ``native``: the plugin's executor runs them inside WSL
    on Windows and straight on the host on macOS/Linux, so they are probed
    wherever they will run.  With ``where="wsl"`` a Mac answered "n/a" for
    both, the strip stayed green, and a Mac without GnuPG only found out at
    "bash: gpg: command not found" under an Extract Failed box that blamed
    the .fun file (PAD-220).  GDRE Tools and xvfb stay ``wsl``: nothing
    installs GDRE Tools on a Mac, and nothing current needs it there - every
    BOF build to date carries a Godot 4 file directory that the plugin
    unpacks and repacks natively (``pipeline.pick_pck_unpacker``).  Only an
    older stock pack would reach GDRE, and the extract then says so instead
    of finishing "successfully" over an empty pck/ (PAD-222).
    """
    platform = platform or sys.platform
    if platform == "darwin":
        # Whichever this Mac has: cooltoy's had MacPorts and read
        # "Homebrew" here while the install ran port (PAD-221).
        gpg_hint = ("Install Missing installs it with Homebrew or MacPorts, "
                    "whichever this Mac has (brew install gnupg / "
                    "port install gnupg2)")
        tar_hint = "tar ships with macOS; reinstall Xcode Command Line Tools"
    else:
        gpg_hint = "apt-get install gnupg (in WSL)"
        tar_hint = "apt-get install tar (in WSL)"
    return (
        Prerequisite(name="gpg", where="native",
                     probe="command -v gpg",
                     reason=".fun GPG decryption + re-encryption",
                     install_hint=gpg_hint, mac_pkg="gnupg"),
        Prerequisite(name="tar", where="native",
                     probe="command -v tar",
                     reason="Archive packing/unpacking",
                     install_hint=tar_hint),
        Prerequisite(
            name="gdre_tools", where="wsl",
            # Check the canonical install path directly — the exact
            # binary the installer writes (install_gdre.sh) and the
            # Write pipeline runs (see pipeline._gdre_prefix).  The old
            # probe used `which`, whose PATH lookup inside the WSL
            # invocation traverses the slow appended Windows PATH and
            # failed intermittently even with GDRE correctly installed.
            probe="test -x /opt/gdre_tools/gdre_tools.x86_64",
            reason=("Godot RE Tools — only Godot 3 packs "
                    "need it to unpack or repack the PCK; current "
                    "Labyrinth, Dune and Winchester code is handled "
                    "natively."),
            install_hint=(
                "Click \"Install Prerequisites\" — auto-downloads "
                "GDRE Tools to /opt/gdre_tools.")),
        Prerequisite(
            name="xvfb-run", where="wsl",
            probe="command -v xvfb-run",
            reason="Headless X server — GDRE Tools needs it on Linux/WSL.",
            install_hint="apt-get install xvfb (in WSL)"),
    )


class BOFManufacturer(Manufacturer):
    key = "bof"
    display = "Barrels of Fun"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=False,
        # Emulate tab (PAD-257): run the .fun's game on this PC against the
        # emulated boards in tools/bof_emu.
        emulate_bof=True,
        # Multi-boot (PAD-342): the Multi-boot tab with its BOF backend - the
        # stock .fun and other builds of the same title become ONE .fun whose
        # install puts a boot menu in front of the game
        # (tools/bof_emu/mkbofmulti.py; the menu is the same code selector the
        # Stern card carries, built static for the machine's Arch Linux).
        multiboot=True,
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
        # Replace-Video tab.  BOF ships its mode videos as plain standalone
        # Ogg Theora entries in the PCK (Dune: 297 clips, 1280x720) — not as
        # imported binaries — so they extract to their res:// path and Write
        # substitutes them like any other changed file.  Replacements need
        # not match the original size: pck_directory.rewrite() re-points the
        # PCK's absolute offsets.
        replace_video=True,
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
    prerequisites = build_prerequisites()

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(key=key, display=info["display"], manufacturer_key="bof")

    def image_info(self, path, assets_dir=None):
        # Bon Jovi: surface what works and how to help unlock image building,
        # whether or not the user has extracted yet.
        try:
            is_bonjovi = detect_game(path) == "bonjovi"
        except Exception:
            is_bonjovi = False
        if is_bonjovi:
            return [("Bon Jovi", [
                ("Extract assets", "Works now: audio, images, video, fonts "
                                   "(to view or reuse)"),
                ("Apply edits / build update", "Not available yet, so editing "
                                               "an asset has no effect for now"),
                ("Emulate", "Not available yet"),
                ("Why", BONJOVI_WHY),
                ("How you can help", BONJOVI_HELP),
            ])]

        # The GPG titles: the .fun itself is opaque (encrypted PCK); the
        # version date only becomes readable once the update files are
        # extracted.  The game applies a .fun only if its date is strictly
        # newer than what's installed, so both dates matter when comparing
        # releases.
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

    def _editable_roots(self, assets_dir):
        """Every ``_EDITABLE ASSETS`` folder under *assets_dir*, or None.

        Both Replace tabs scan out of here: it holds the only copies Write
        re-imports into the PCK.  Anything else in the tree (the .godot
        import cache, raw pck resources) would be a dead end if staged.

        Dot-prefixed dirs are pruned before descending — .godot/imported
        alone is thousands of files on a real extract, and the editable
        folder is never inside one.
        """
        from .source_converter import EDITABLE_DIR_NAME
        roots = []
        for dirpath, dirnames, _files in os.walk(assets_dir):
            if EDITABLE_DIR_NAME in dirnames:
                roots.append(os.path.join(dirpath, EDITABLE_DIR_NAME))
                dirnames.remove(EDITABLE_DIR_NAME)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        return roots or None

    def audio_slot_dirs(self, assets_dir):
        """Restrict the Replace-Audio scan to the editable folder(s)."""
        return self._editable_roots(assets_dir)

    # NOTE: no video_slot_dirs override — unlike audio, BOF's video is NOT
    # in the editable folder.  Its clips are plain standalone PCK entries
    # (Dune: 297 .ogv under pck/assets/videos/), so they extract straight to
    # their res:// path and Write substitutes them as ordinary files.  The
    # default whole-tree scan finds them, and scan_video_slots already
    # prunes dot-directories, which keeps pck/.godot/imported out of the
    # list without naming it here.

    def video_slot_exts(self, assets_dir):
        """Only ``.ogv`` — Ogg Theora is the one video form BOF ships, and
        the one ``may_packer`` will substitute.  Pinning it keeps a stray
        .mp4 a modder left in the project folder from looking like a
        replaceable slot."""
        return (".ogv",)

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
        return ("Open a Barrels of Fun `.fun` update file (Labyrinth, Dune, "
                "Winchester, Bon Jovi) and unpack its assets. Labyrinth, Dune "
                "and Winchester need GPG; Bon Jovi's newer signed disk image "
                "is unwrapped natively. Assets come out of the Godot PCK "
                "natively (GDRE Tools only for older Godot 3 packs). "
                "Note: for Bon Jovi you can extract assets to view or reuse, "
                "but changes can't be built into an installable update yet, so "
                "editing has no effect for now (see the Image Info window for "
                "why, and how you can help).")

    def write_install_help(self):
        return ("1. Copy the output .fun file to a USB drive (FAT32).\n"
                "2. Insert the USB drive into the machine and follow the "
                "on-screen update prompts.\n\n"
                "Bon Jovi note: " + BONJOVI_WHY + " You can still extract its "
                "assets to view or reuse, but changes can't be built in yet. "
                + BONJOVI_HELP)
