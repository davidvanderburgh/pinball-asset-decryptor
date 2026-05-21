"""Williams (WPC-era) manufacturer plugin."""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from ...core.transcribe import TranscribePipeline
from .capture_pipeline import (
    COMBINED_PHASES, CapturePipeline, StaticPlusCapturePipeline)
from .capture_pipeline import PHASES as CAPTURE_PHASES
from .formats import detect_game, is_williams_zip
from .games import GAME_DB
from .pipeline import PHASES, ExtractPipeline


_GAMES = tuple(sorted(
    (Game(key=k, display=info["display"], manufacturer_key="williams")
     for k, info in GAME_DB.items()),
    key=lambda g: g.display.lower(),
))


class WilliamsManufacturer(Manufacturer):
    key = "williams"
    display = "Williams"
    games = _GAMES
    # PinMAME runtime-capture pipeline + scripted per-game playthrough
    # are still bringing up — the static extract path is stable but
    # the capture path is actively being tuned per title.
    beta = True
    capabilities = Capabilities(
        extract=True, write=False, modpack=False,
        apply_delta=False, iso=False,
        # Runtime-capture pipeline via libpinmame (BSD-3-Clause).
        # The GUI surfaces this as a "Use PinMAME runtime capture"
        # toggle on the Extract tab — when checked, the same input
        # zip + output folder feed into a libpinmame-driven session
        # that emits per-cinematic MP4s with synced audio.
        capture=True,
        # Auto-transcribe: faster-whisper over the extracted WAVs
        # (DCS sound tracks + capture audio slices) -> callouts.csv.
        transcribe=True,
    )
    input_spec = InputSpec(
        label="Williams MAME ROM zips",
        extensions=(".zip",),
    )
    extract_phases = PHASES
    capture_phases = CAPTURE_PHASES
    # Combined phases used when capture mode is toggled on (the
    # capture is now ADDITIVE — static extract still runs, capture
    # runs on top).  GUI phase indicator switches to this set when
    # the user ticks "Use PinMAME runtime capture".
    combined_phases = COMBINED_PHASES
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
    prerequisites = (
        Prerequisite(
            name="ffmpeg", where="host",
            probe="ffmpeg -version",
            reason="Encoding extracted DMD frames into MP4 videos.",
            install_hint=(
                "winget install Gyan.FFmpeg  (Windows)\n"
                "brew install ffmpeg          (macOS)\n"
                "apt-get install ffmpeg       (Linux)")),
        # faster-whisper drives the Auto-transcribe checkbox.  Probed
        # via an in-process import so the check reflects the Python
        # the app actually runs on.  ~75 MB tiny.en model downloads
        # on first transcribe-run and is cached in the user's HF cache.
        Prerequisite(
            name="faster-whisper", where="host",
            probe="python:faster_whisper",
            reason="Auto-transcribe extracted audio to callouts.csv.",
            install_hint="pip install faster-whisper"),
        # libpinmame is optional — only needed for the runtime-
        # capture path.  We don't list it as a prereq because the
        # GUI shows missing prereqs in red; libpinmame missing should
        # only matter when the capture mode is actually invoked.
        # The capture pipeline itself surfaces a clean install hint
        # when the user tries to use it without libpinmame.
    )

    def detect(self, path):
        if not is_williams_zip(path):
            return None
        key = detect_game(path)
        if key is None:
            return None
        info = GAME_DB[key]
        return Game(
            key=key, display=info["display"],
            manufacturer_key="williams",
            notes=f"{info['platform']}, {info['year']}")

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_capture_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        """Build the runtime-capture pipeline.

        ``kwargs["also_run_static"]`` controls whether the static
        asset extractor runs alongside (default True, since most
        users want both halves):

          * True  → :class:`StaticPlusCapturePipeline` — static then
                    capture, into the same output folder.
          * False → :class:`CapturePipeline` alone — capture only,
                    no static asset bitmaps emitted.
        """
        also_static = kwargs.get("also_run_static", True)
        duration = kwargs.get("duration_seconds", 180.0)
        simulate = kwargs.get("simulate_gameplay", True)
        frame_cb = kwargs.get("frame_cb")
        capture_ready_cb = kwargs.get("capture_ready_cb")
        if also_static:
            return StaticPlusCapturePipeline(
                input_path, output_dir,
                log_cb, phase_cb, progress_cb, done_cb,
                duration_seconds=duration,
                simulate_gameplay=simulate,
                frame_cb=frame_cb,
                capture_ready_cb=capture_ready_cb,
            )
        return CapturePipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            duration_seconds=duration,
            simulate_gameplay=simulate,
            frame_cb=frame_cb,
            capture_ready_cb=capture_ready_cb,
        )

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

    def audio_export_supported(self, path):
        """Only DCS-era games have statically decodable audio; pre-DCS
        YM2151 titles (Fish Tales, White Water, ...) do not, so the
        Auto-transcribe controls and the "Extract audio" phase are
        hidden for them."""
        from . import dcs_decode
        return is_williams_zip(path) and dcs_decode.is_dcs_rom(path)

    def extract_input_help(self):
        return ("Pick a MAME-format ROM zip — e.g. `ft_l5.zip` "
                "(Fish Tales), `afm_113b.zip` (Attack From Mars).  "
                "Static mode extracts raw asset bitmaps from the ROM "
                "(sprites, font glyphs, splash screens), and for "
                "DCS-era games (1993+) decodes every sound track to "
                "sounds/.  Capture mode (checkbox below) spawns "
                "PinMAME, records composed cinematics + DCS audio "
                "during attract mode, and emits per-cinematic MP4s.  "
                "Tick Auto-transcribe to also emit a callouts.csv "
                "naming each extracted WAV by its spoken text.")
