"""Chicago Gaming Company manufacturer plugin."""

import os

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import detect_game
from .games import GAME_DB
from ...core.transcribe import TranscribePipeline
from .pipeline import ExtractPipeline, FlashImagePipeline, WritePipeline


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="cgc")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class CGCManufacturer(Manufacturer):
    key = "cgc"
    display = "Chicago Gaming Company"
    games = _GAMES
    capabilities = Capabilities(
        extract=True, write=True, modpack=True, apply_delta=False, iso=False,
        transcribe=True,
        # WPC remakes (MM/AFM/MB) ship the original Williams ROM --
        # surfaces a "Decode DMD scenes (experimental)" checkbox that
        # decodes scenes/animations/fonts into output_dir/dmd/.
        # Default OFF; output is extract-only (not written back).
        decode_dmd=True,
        # Replace-Audio tab: WPC remakes (MM/AFM/MB) expose loose .wav;
        # Pulp Fiction exposes the decoded Wwise <bnk>/ WAVs.  Both are
        # plain .wav in the extract — Write's _repack_modified_jps_bnks
        # re-encodes edited bank WAVs back into the .bnk, and loose WAVs
        # write straight back.  Default whole-tree scan is correct (the
        # extract-only dmd/ render holds no audio).
        replace_audio=True,
        # Flash a built installer .img straight onto the card / USB drive from
        # the GUI -- a dd-style whole-image write, so users don't need a
        # separate imaging tool (Etcher / Rufus / Win32DiskImager).  Same
        # generic core.rawdevice path Stern uses, with a size guard.
        flash_image=True,
    )
    input_spec = InputSpec(
        label="CGC installer images",
        extensions=(".img",),
    )
    extract_phases = ("Detect", "Outer image", "Inner image",
                      "Decode game data", "Checksums")
    write_phases = ("Detect", "Copy original", "Stage partitions", "Patch")
    flash_phases = ("Check card", "Write image", "Verify card", "Flush")
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
    # Flash-dialog wording.  CGC installs from a microSD card or a USB drive
    # (depends on the cabinet), so the noun covers both; the picker still
    # biases toward small removable media.
    direct_medium_noun = "SD card or USB drive"
    direct_target_kind = "sd_card"
    direct_safety_text = (
        "⚠ This writes the WHOLE drive — pick the right one, it is erased "
        "completely. Power the machine off and keep a backup of the original "
        "card/drive before flashing.")

    # "Card diagnostics…" (gui.diagnose_dialog, gated on this attribute):
    # after a failed on-machine install (SHELL ERROR), the installer leaves
    # its copy log (procstat.txt) on the card's ext4 rootfs, which users
    # can't read on Windows.  This reads it back through core.rawdevice --
    # read-only, no WSL.
    def diagnose_card(self, device_path, log=None):
        from .diagnose import diagnose_installer_card
        return diagnose_installer_card(device_path, log=log)

    diagnose_card_help = (
        "Reads the installer's own log off a card after a failed install "
        "(e.g. \"SHELL ERROR\" on the machine) and checks the install "
        "payload is intact. Read-only — the card is not changed.")
    # CGC's nested-disk-image extraction needs ext4 read/write tooling.
    # All work runs in the executor (WSL on Windows, native on Linux,
    # Docker on macOS) -- same model as JJP.
    prerequisites = (
        Prerequisite(name="debugfs", where="wsl",
                     probe="which debugfs",
                     reason="ext4 read/write on installer P3 + emmc.img P2",
                     install_hint="apt-get install e2fsprogs (in WSL)"),
        Prerequisite(name="xxd", where="wsl",
                     probe="which xxd",
                     reason="Reading the inner emmc.img MBR partition table",
                     install_hint="apt-get install xxd (in WSL)"),
        # faster-whisper drives the Auto-transcribe checkbox.  Probed
        # via an in-process import so the check reflects the actual
        # Python the app is running on (sys.executable), not whatever
        # `python` happens to be on PATH.  ~75 MB model is downloaded
        # on first transcribe-run and cached in the user's HF cache.
        Prerequisite(name="faster-whisper", where="host",
                     probe="python:faster_whisper",
                     reason="Auto-transcribe samples to callouts.csv",
                     install_hint="pip install faster-whisper"),
        # Needed by the optional "Decode DMD scenes" pass to assemble MP4s:
        # the WPC-remake animation MP4s (MM/AFM/MB) and Cactus Canyon's
        # display-art animation videos.
        Prerequisite(name="ffmpeg", where="host",
                     probe="ffmpeg -version",
                     reason="Assemble decoded DMD / display-art frames into "
                            "MP4 animations (optional)",
                     install_hint=(
                         "winget install Gyan.FFmpeg  (Windows)\n"
                         "brew install ffmpeg          (macOS)\n"
                         "apt-get install ffmpeg       (Linux)")),
    )

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(key=key, display=info["display"],
                    manufacturer_key="cgc")

    def audio_forces_length_match(self, assets_dir=None):
        # Pulp Fiction stores audio in JPS ``.bnk`` banks whose slots are
        # FIXED-LENGTH: Write splices each replacement into the original
        # slot in place, trimmed or padded to the stock byte length,
        # because the game engine reads each sound's length from a bank
        # record and validates it -- a different length silences that slot
        # and desyncs the rest of the bank.  So there the "Trim / pad"
        # toggle is mandatory, not a choice (forced on + disabled).
        #
        # The WPC remakes (MM/AFM/MB) instead store loose ``.wav`` files
        # the engine plays at whatever length they are, so length stays a
        # free user choice for those extracts.  We tell the two apart by
        # the presence of a bank file, so the lock only kicks in once a
        # Pulp Fiction extract is actually scanned.
        if not assets_dir:
            return False
        import glob
        return bool(glob.glob(os.path.join(assets_dir, "data", "*.bnk")))

    def audio_length_note(self):
        return ("Pulp Fiction's music and speech live in fixed-length bank "
                "slots — each replacement is automatically trimmed or padded "
                "to its original slot's length (a different length would "
                "silence the sound and mistime the rest of the bank on the "
                "machine). The WPC remakes (Medieval Madness / Attack From "
                "Mars / Monster Bash) use loose .wav files that play at their "
                "own length, so trimming isn't needed there.")

    def decode_dmd_applies(self, input_path):
        # MM/AFM/MB: decode the bundled Williams WPC ROM to PNG scenes + MP4s.
        # Cactus Canyon: render the cgc.so display-art animation sequences to
        # MP4 with the colour dot-matrix shader.  Pulp Fiction has neither, so
        # the checkbox stays hidden for it.
        return detect_game(input_path) in (
            "mm_remake", "afm_remake", "mb_remake", "cactus_canyon")

    def decode_dmd_label_for(self, input_path):
        if detect_game(input_path) == "cactus_canyon":
            return ("Render display-art animations to MP4 "
                    "(DMD shader, experimental, needs ffmpeg)")
        return self.decode_dmd_label

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            decode_dmd=bool(kwargs.get("decode_dmd", False)))

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return WritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_flash_pipeline(self, image_path, device_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        return FlashImagePipeline(
            image_path, device_path, log_cb, phase_cb, progress_cb, done_cb)

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False, model_size="tiny.en"):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after, model_size=model_size)

    def extract_input_help(self):
        return ("Extract a Chicago Gaming Company installer `.img` "
                "(Medieval Madness Remake, Attack From Mars Remake, "
                "Monster Bash Remake, Pulp Fiction, Cactus Canyon). "
                "Cactus Canyon ships only on a physical microSD master "
                "card — image the whole card to a .img (e.g. with dd / "
                "Win32DiskImager) and name it so it contains "
                "\"CactusCanyon\"; its original DCS sound ROMs are decoded "
                "to WAV under dcs_audio/ via the bundled DCSExplorer. "
                "Requires WSL2 "
                "(Windows) / Docker (macOS) with e2fsprogs (debugfs). "
                "Note: CGC games render all video in real time (no .mp4 "
                "files to mod); the extracted folder contains the "
                "moddable audio (.wav for the WPC remakes, Wwise .bnk "
                "for Pulp Fiction), the WPC ROM where applicable, and "
                "the boot logo bitmap. Tick the Auto-transcribe checkbox "
                "before Extract to also emit a callouts.csv mapping each "
                "WAV to its spoken text (requires the faster-whisper "
                "prereq -- install via the Install Prerequisites step). "
                "Tick the \"Decode DMD scenes\" checkbox to also decode "
                "the bundled Williams WPC ROM into PNG scenes + MP4 "
                "animations under `dmd/` -- experimental, extract-only "
                "(the renders aren't written back to the installer), "
                "rendered at 1920x480 in the original amber-DMD look "
                "(CGC's runtime LCD colorization is not shipped as data "
                "and so isn't applied to these renders).")

    def write_install_help(self):
        return ("Medieval Madness / Attack From Mars / Monster Bash / Pulp "
                "Fiction:\n"
                "Flash the whole output .img to your machine's installer "
                "medium with Rufus, Etcher, or `dd` (the whole drive/card — "
                "it's a bootable disk image, not a single file). Which medium "
                "depends on your unit: older cabinets boot the installer from "
                "a USB drive in the BeagleBone Black's USB port, while many "
                "machines install from a microSD card instead (if yours runs "
                "off a microSD, use that slot — there is no USB step). With "
                "the machine powered off, insert the drive/card, power on, and "
                "the installer auto-runs and writes the modified image to the "
                "internal eMMC, then reboots into the new build. Keep a backup "
                "of the untouched card/drive first.\n\n"
                "Cactus Canyon (microSD master — no USB installer):\n"
                "1. Flash the output .img to a microSD card (the whole card) "
                "with Rufus / Etcher / `dd` / Win32DiskImager — it is the "
                "master/installer card, not a USB image.\n"
                "2. With the machine powered off, swap the card into the "
                "BeagleBone Black's microSD slot.\n"
                "3. Power on. The on-card installer auto-copies the modified "
                "image to the internal eMMC, then you reseat the original "
                "card / reboot into the new build (keep a backup of the "
                "untouched card first).")
