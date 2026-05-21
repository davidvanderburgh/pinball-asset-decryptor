"""WPC-DCS sound-ROM audio extractor.

Williams / Bally pinball games from 1993-1998 used the DCS (Digital
Compression System) sound board — a proprietary compressed digital-
audio format stored in the game's sound ROMs.  This module decodes
those ROMs into individual per-track WAV files by shelling out to
``DCSExplorer``, an open-source (BSD-3-Clause) native DCS decoder by
Michael J. Roberts.

A DCS "track" is a complete audio program — a music cue, a voice
line, or a sound effect — addressable by the numeric command the
WPC game board would send to the sound board.  Extracting every
track gives you the game's music and SFX as separate assets.

The DCSExplorer Windows binary is bundled in ``vendor/``; on other
platforms (or to override the bundled copy) it is also looked up on
PATH.

Pre-DCS games (Funhouse, Fish Tales, White Water, T2, Addams Family
— the ~1990-1992 YM2151-based WPC sound board) are NOT DCS.  Their
sound ROMs cannot be decoded statically; this module reports them
cleanly as non-DCS so the caller can skip them.  Their audio is only
recoverable through the PinMAME runtime-capture pipeline.

Upstream: https://github.com/mjrgh/DCSExplorer
"""

from __future__ import annotations

import glob as _glob
import json
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# Suppress the console window that would otherwise flash on Windows
# each time we spawn the decoder.
_CREATE_FLAGS = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

# A full ROM has at most a few thousand tracks; the native decoder
# runs faster than real time, but a large ROM can still take a
# couple of minutes.  Cap generously so a wedged process can't hang
# the pipeline forever.
_EXTRACT_TIMEOUT_S = 600


@dataclass
class DcsTrack:
    """One extracted DCS audio track."""
    track_id: str                 # e.g. "0001" — the hex track command
    wav_filename: str             # basename within the output dir
    duration_seconds: float
    sample_rate: int
    channels: int
    pcm_size_bytes: int


@dataclass
class DcsResult:
    """Outcome of a DCS extraction attempt for one ROM zip."""
    is_dcs: bool                  # False = not a DCS ROM (pre-DCS board)
    message: str                  # human-readable status line
    game_name: Optional[str] = None      # DCSExplorer's recognised title
    board_version: Optional[str] = None  # e.g. "DCS-95 A/V board, ..."
    channels: Optional[int] = None
    tracks: List[DcsTrack] = field(default_factory=list)


_dcs_explorer_path: Optional[str] = None


def find_dcs_explorer() -> Optional[str]:
    """Locate the DCSExplorer executable.

    Prefers the binary bundled in ``vendor/`` (Windows), then falls
    back to PATH.  Caches the result — including a negative result —
    for the life of the process.
    """
    global _dcs_explorer_path
    if _dcs_explorer_path is not None:
        return _dcs_explorer_path or None

    # 1. Bundled copy.  We only ship the Windows binary, so on other
    # platforms this path simply won't exist and we fall through.
    bundled = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vendor",
        "DCSExplorer.exe" if sys.platform == "win32" else "DCSExplorer")
    if os.path.isfile(bundled):
        _dcs_explorer_path = bundled
        return bundled

    # 2. PATH.
    for name in ("DCSExplorer", "DCSExplorer.exe", "dcsexplorer"):
        found = shutil.which(name)
        if found:
            _dcs_explorer_path = found
            return found

    _dcs_explorer_path = ""
    return None


def _scan_line(text: str, label: str) -> Optional[str]:
    """Return the text after *label* on the first line that has it."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(label):
            return line[len(label):].strip()
    return None


def _read_wav_meta(path: str):
    """Return (duration_s, sample_rate, channels, pcm_bytes) for a WAV."""
    with wave.open(path, "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        duration = frames / rate if rate else 0.0
        return duration, rate, channels, frames * channels * width


def extract_dcs(rom_zip_path: str, output_dir: str,
                log_cb: Optional[Callable[[str, str], None]] = None
                ) -> DcsResult:
    """Decode the DCS sound ROMs in *rom_zip_path* into per-track WAVs.

    Runs DCSExplorer's ``--extract-tracks`` mode, writing one WAV per
    track into *output_dir* plus a ``manifest.json`` describing them.

    Returns a :class:`DcsResult`.  ``is_dcs=False`` is a normal,
    non-error outcome for pre-DCS games — the caller should just skip
    audio extraction for those.  *output_dir* is left empty (and
    removed if it was created) when nothing is extracted.
    """
    def log(msg: str, level: str = "info"):
        if log_cb is not None:
            log_cb(msg, level)

    exe = find_dcs_explorer()
    if exe is None:
        return DcsResult(
            is_dcs=False,
            message="DCSExplorer not available — skipping DCS audio.")

    created_dir = not os.path.isdir(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    def _cleanup_empty():
        # Drop the output dir if we created it and wrote nothing.
        if created_dir:
            try:
                if not os.listdir(output_dir):
                    os.rmdir(output_dir)
            except OSError:
                pass

    # DCSExplorer forms each filename as <prefix>_<track-id>.wav — it
    # inserts its own separator, so the prefix carries none.
    prefix = os.path.join(output_dir, "track")
    cmd = [exe, f"--extract-tracks={prefix}", rom_zip_path]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=_EXTRACT_TIMEOUT_S,
            creationflags=_CREATE_FLAGS)
    except subprocess.TimeoutExpired:
        _cleanup_empty()
        return DcsResult(
            is_dcs=False,
            message=f"DCSExplorer timed out after {_EXTRACT_TIMEOUT_S}s.")
    except OSError as e:
        _cleanup_empty()
        return DcsResult(
            is_dcs=False, message=f"DCSExplorer failed to launch: {e}")

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")

    # A non-DCS ROM (pre-DCS YM2151 sound board) has no recognisable
    # U2 boot ROM — DCSExplorer says so explicitly and exits.
    if "could be identified as ROM U2" in out:
        _cleanup_empty()
        return DcsResult(
            is_dcs=False,
            message="not a DCS game — sound ROMs use the pre-DCS WPC "
                    "sound board (use runtime capture for audio).")

    wavs = sorted(_glob.glob(os.path.join(output_dir, "track_*.wav")))
    if not wavs:
        _cleanup_empty()
        detail = _scan_line(out, "Error:") or "no tracks were produced"
        return DcsResult(
            is_dcs=False,
            message=f"DCSExplorer produced no audio ({detail}).")

    game_name = _scan_line(out, "Known pinball machine:")
    board_version = _scan_line(out, "Version:")
    channels = None
    chan_str = _scan_line(out, "Number of audio channels:")
    if chan_str and chan_str.isdigit():
        channels = int(chan_str)

    tracks: List[DcsTrack] = []
    for wav in wavs:
        base = os.path.basename(wav)
        # "track_0001.wav" -> "0001" (last underscore-delimited field)
        track_id = os.path.splitext(base)[0].rsplit("_", 1)[-1]
        try:
            duration, rate, ch, pcm = _read_wav_meta(wav)
        except (wave.Error, OSError) as e:
            log(f"  skipping unreadable {base}: {e}", "warning")
            continue
        tracks.append(DcsTrack(
            track_id=track_id, wav_filename=base,
            duration_seconds=round(duration, 4),
            sample_rate=rate, channels=ch, pcm_size_bytes=pcm))

    manifest = {
        "format": "dcs_tracks_v1",
        "decoder": "DCSExplorer (https://github.com/mjrgh/DCSExplorer)",
        "source_zip": os.path.basename(rom_zip_path),
        "game_name": game_name,
        "board_version": board_version,
        "audio_channels": channels,
        "track_count": len(tracks),
        "tracks": [
            {
                "track_id": t.track_id,
                "wav_filename": t.wav_filename,
                "duration_seconds": t.duration_seconds,
                "sample_rate": t.sample_rate,
                "channels": t.channels,
                "pcm_size_bytes": t.pcm_size_bytes,
            } for t in tracks
        ],
    }
    with open(os.path.join(output_dir, "manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return DcsResult(
        is_dcs=True,
        message=f"{game_name or 'DCS ROM'}: {len(tracks)} track(s).",
        game_name=game_name, board_version=board_version,
        channels=channels, tracks=tracks)
