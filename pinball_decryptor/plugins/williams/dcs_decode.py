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

PAD does not ship DCSExplorer (PAD-1606: antivirus programs flag it by
mistake, so carrying it in every install and update made users switch
their scanner off to update PAD).  On Windows the first DCS sound job
downloads the upstream v1.1 release file, pinned by SHA-256 in
:mod:`core.payloads`, into PAD's payload cache.  A copy in ``vendor/``
or on PATH is used first if there is one.

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

from ...core import payloads


# Suppress the console window that would otherwise flash on Windows
# each time we spawn the decoder.
_CREATE_FLAGS = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

# A full ROM has at most a few thousand tracks; the native decoder
# runs faster than real time, but a large ROM can still take a
# couple of minutes.  Cap generously so a wedged process can't hang
# the pipeline forever.
_EXTRACT_TIMEOUT_S = 600

# Windows' own codes for "the antivirus will not let this program run":
# ERROR_VIRUS_INFECTED and ERROR_VIRUS_DELETED.
_AV_WINERRORS = (225, 226)

# The last reason a DCS tool could not run (missing, or blocked by the
# antivirus), so a caller that only saw "not a DCS ROM" can say why.
_tool_problem: Optional[str] = None


def tool_folder() -> str:
    """Where PAD keeps the DCS tools it downloaded (PAD-1606)."""
    return payloads.cache_root()


def missing_tool_message(tool: str) -> str:
    """Why *tool* ("DCSExplorer" / "DCSEncoder") is not there, in words a
    user can act on (PAD-1391, PAD-1606).  PAD fetches the tools on first
    use from mjrgh's release; antivirus programs flag these unsigned,
    rarely seen tools (Norton: "Trojan.Gen.MBT") and may remove them."""
    if sys.platform == "win32":
        return (f"{tool}.exe is not on this PC. PAD downloads it the first "
                f"time DCS sound is needed: it is the open-source DCS sound "
                f"tool by mjrgh (github.com/mjrgh/DCSExplorer, release "
                f"v1.1). " + _manual_hint(tool))
    return (f"{tool} is not installed (PAD fetches it only on Windows); "
            f"put it on PATH.")


def _manual_hint(tool: str) -> str:
    return (f"If the download failed or your antivirus removed it, restart "
            f"PAD to try again, or save {tool}.exe from that release into "
            f"{tool_folder()} (or anywhere on PATH).")


def launch_error_message(tool: str, exc: BaseException) -> str:
    """Why *tool* failed to start, for the log (PAD-1391)."""
    if isinstance(exc, FileNotFoundError):
        return missing_tool_message(tool)
    if getattr(exc, "winerror", None) in _AV_WINERRORS:
        return (f"your antivirus blocked {tool}.exe from running. It is "
                f"the open-source DCS sound tool by mjrgh "
                f"(github.com/mjrgh/DCSExplorer), the unchanged v1.1 "
                f"release file.")
    return f"{tool} failed to launch: {exc}"


def tool_problem() -> Optional[str]:
    """The reason DCS audio cannot be decoded here, or None if
    DCSExplorer is present and last started fine."""
    if find_dcs_explorer() is None:
        return _tool_problem or missing_tool_message("DCSExplorer")
    return _tool_problem


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
_dcs_encoder_path: Optional[str] = None


def _fetch_allowed() -> bool:
    """Only Windows gets the download (the upstream files are .exe), and
    never with PAD_NO_TOOL_DOWNLOAD set (the test suite, air-gapped use)."""
    return (sys.platform == "win32"
            and not os.environ.get("PAD_NO_TOOL_DOWNLOAD"))


def _locate(tool: str, fetch: bool,
            log: Optional[Callable[[str], None]]) -> Optional[str]:
    """*tool*'s executable: a copy in ``vendor/`` (older installs, a
    developer's checkout), then PAD's verified download, then PATH, and
    last, if *fetch*, a fresh download of the pinned upstream file."""
    global _tool_problem
    exe = tool + ".exe" if sys.platform == "win32" else tool
    bundled = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vendor", exe)
    if os.path.isfile(bundled):
        return bundled
    payload = payloads.HOST_PAYLOADS[tool]
    cached = payloads.cache_path(payload)
    if (sys.platform == "win32" and os.path.isfile(cached)
            and payloads.verify(cached, payload)[0]):
        return cached
    for name in (tool, tool + ".exe", tool.lower()):
        found = shutil.which(name)
        if found:
            return found
    if not (fetch and _fetch_allowed()):
        return None
    say = log or (lambda _m: None)
    say(f"  {tool}.exe is not on this PC yet: downloading the open-source "
        f"DCS sound tool by mjrgh (github.com/mjrgh/DCSExplorer v1.1, "
        f"{payloads._human(payload.size)}).")
    try:
        return payloads.ensure_cached(payload, log=say)
    except RuntimeError as e:
        why = str(e).splitlines()[0] if str(e) else type(e).__name__
        _tool_problem = (f"{tool}.exe could not be downloaded ({why}). "
                         + _manual_hint(tool))
        say("  " + _tool_problem)
        return None


def find_dcs_explorer(fetch: bool = True,
                      log: Optional[Callable[[str], None]] = None
                      ) -> Optional[str]:
    """Locate DCSExplorer, downloading it on first use on Windows
    (PAD-1606).  Caches the result, including a negative one, for the
    life of the process; ``fetch=False`` never downloads and never caches
    a miss, for callers on the UI thread."""
    global _dcs_explorer_path
    if _dcs_explorer_path is not None:
        return _dcs_explorer_path or None
    found = _locate("DCSExplorer", fetch, log)
    if found or fetch:
        _dcs_explorer_path = found or ""
    return found


def find_dcs_encoder(fetch: bool = True,
                     log: Optional[Callable[[str], None]] = None
                     ) -> Optional[str]:
    """Locate DCSEncoder (the CGC Cactus Canyon DCS *repack* path), the
    same way as :func:`find_dcs_explorer`."""
    global _dcs_encoder_path
    if _dcs_encoder_path is not None:
        return _dcs_encoder_path or None
    found = _locate("DCSEncoder", fetch, log)
    if found or fetch:
        _dcs_encoder_path = found or ""
    return found


_is_dcs_cache: dict = {}


def is_dcs_rom(zip_path: str, fetch: bool = True,
               log: Optional[Callable[[str], None]] = None) -> bool:
    """Return True if *zip_path* is a DCS-audio ROM set DCSExplorer
    can decode — i.e. audio export is supported for this game.

    Runs DCSExplorer's fast ``--info`` mode; the result is cached per
    path for the life of the process.  Pre-DCS games (the YM2151
    sound board — Fish Tales, White Water, ...) and anything
    DCSExplorer can't identify return False.  So does a missing decoder,
    but that answer is not cached: it is about this PC, not the ROM.
    *fetch* / *log* go to :func:`find_dcs_explorer` (PAD-1606).
    """
    key = os.path.abspath(zip_path)
    cached = _is_dcs_cache.get(key)
    if cached is not None:
        return cached
    if find_dcs_explorer(fetch=fetch, log=log) is None:
        return False
    result = _probe_is_dcs(zip_path)
    _is_dcs_cache[key] = result
    return result


def _probe_is_dcs(zip_path: str) -> bool:
    global _tool_problem
    exe = find_dcs_explorer()
    if exe is None or not os.path.isfile(zip_path):
        return False
    try:
        proc = subprocess.run(
            [exe, "--info", zip_path],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
            timeout=60, creationflags=_CREATE_FLAGS)
    except subprocess.TimeoutExpired:
        return False
    except OSError as e:
        _tool_problem = launch_error_message("DCSExplorer", e)
        return False
    _tool_problem = None
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if "could be identified as ROM U2" in out:
        return False
    # DCSExplorer prints the U2 ROM signature for a recognised DCS set.
    return "U2 Signature:" in out


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
                log_cb: Optional[Callable[[str, str], None]] = None,
                ignore_checksum: bool = False
                ) -> DcsResult:
    """Decode the DCS sound ROMs in *rom_zip_path* into per-track WAVs.

    Runs DCSExplorer's ``--extract-tracks`` mode, writing one WAV per
    track into *output_dir* plus a ``manifest.json`` describing them.

    Returns a :class:`DcsResult`.  ``is_dcs=False`` is a normal,
    non-error outcome for pre-DCS games — the caller should just skip
    audio extraction for those.  *output_dir* is left empty (and
    removed if it was created) when nothing is extracted.

    *ignore_checksum* passes DCSExplorer's ``-I`` flag.  Williams MAME
    romsets match DCSExplorer's known CRCs so the default is off; set it
    for CGC-distributed sets whose ROMs may differ from the PinMAME
    checksums (e.g. the Cactus Canyon remake), so a CRC mismatch doesn't
    block the decode.
    """
    def log(msg: str, level: str = "info"):
        if log_cb is not None:
            log_cb(msg, level)

    exe = find_dcs_explorer(log=log)
    if exe is None:
        return DcsResult(
            is_dcs=False,
            message=("DCS audio skipped: "
                     + (_tool_problem or missing_tool_message("DCSExplorer"))))

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
    cmd = [exe]
    if ignore_checksum:
        cmd.append("-I")
    cmd += [f"--extract-tracks={prefix}", rom_zip_path]
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
            is_dcs=False, message=("DCS audio skipped: "
                                   + launch_error_message("DCSExplorer", e)))

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
