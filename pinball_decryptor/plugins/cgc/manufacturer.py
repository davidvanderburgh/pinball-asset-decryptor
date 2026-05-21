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
    )
    input_spec = InputSpec(
        label="CGC installer images",
        extensions=(".img",),
    )
    extract_phases = ("Detect", "Outer image", "Inner image", "Checksums")
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
    )

    def detect(self, path):
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(key=key, display=info["display"],
                    manufacturer_key="cgc")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb)

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
                "Monster Bash Remake, Pulp Fiction). Requires WSL2 "
                "(Windows) / Docker (macOS) with e2fsprogs (debugfs). "
                "Note: CGC games render all video in real time (no .mp4 "
                "files to mod); the extracted folder contains the "
                "moddable audio (.wav for the WPC remakes, Wwise .bnk "
                "for Pulp Fiction), the WPC ROM where applicable, and "
                "the boot logo bitmap. Tick the Auto-transcribe checkbox "
                "before Extract to also emit a callouts.csv mapping each "
                "WAV to its spoken text (requires the faster-whisper "
                "prereq -- install via the Install Prerequisites step).")

    def write_install_help(self):
        return ("1. Flash the output .img to a USB drive with Rufus, "
                "Etcher, or `dd` (the whole drive — it's a bootable disk "
                "image, not a single file).\n"
                "2. With the machine powered off, insert the USB drive "
                "into the BeagleBone Black's USB port.\n"
                "3. Power on. The installer auto-runs and writes the "
                "modified image to /dev/mmcblk1; the machine reboots "
                "into the new build when finished.")
