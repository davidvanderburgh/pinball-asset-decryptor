"""Chicago Gaming Company manufacturer plugin."""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from .formats import detect_game
from .games import GAME_DB
from ...core.transcribe import TranscribePipeline
from .pipeline import ExtractPipeline, WritePipeline


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
    )
    input_spec = InputSpec(
        label="CGC installer images",
        extensions=(".img",),
    )
    extract_phases = ("Detect", "Outer image", "Inner image",
                      "Decode game data", "Checksums")
    write_phases = ("Detect", "Copy original", "Stage partitions", "Patch")
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
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

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

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
