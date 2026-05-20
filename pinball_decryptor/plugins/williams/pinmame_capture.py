"""PinMAME runtime-capture pipeline for Williams DMD + audio.

Loads ``libpinmame`` via ``ctypes``, configures it with display +
audio callbacks, runs a game's attract mode for a fixed duration,
and returns the captured DMD frames + PCM audio for downstream
encoding into MP4/WAV.

This complements the static decoder in :mod:`.wpc_decode` — the
static path gives raw asset bitmaps directly out of the ROM, while
this path gives you the **composed display** as the game's 6809
code paints it at runtime (e.g. scrolling text built from font
glyphs, sprites layered over backgrounds, the actual title-screen
animation that's drawn rather than stored as one bitmap), AND the
real-time audio (DCS music, sound effects, voice) which static
extraction can't recover because DCS is a DSP-emulator format.

License notes
-------------

libpinmame is BSD-3-Clause (PinMAME upstream).  We invoke it as a
shared library (no source bundled, no redistribution).  MAME ROMs
are NEVER bundled — the user provides their own MAME zip; the
pipeline copies it into a working ``roms/`` directory and points
PinMAME at it.

Layout PinMAME expects
----------------------

PinMAME's ``vpmPath`` is the base directory containing:

  vpmPath/
    roms/
      <rom_name>.zip       (the MAME ROM zip the user supplied)
    nvram/                 (optional, for save state)
    cfg/                   (optional)
"""

from __future__ import annotations

import ctypes
import glob as _glob
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# libpinmame discovery
# ---------------------------------------------------------------------------

def _glob_lib(directory, pattern):
    """Return matching files in *directory*, newest first."""
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(_glob.glob(os.path.join(directory, pattern)),
                  reverse=True)


def _candidate_paths():
    """Return a list of paths to try when locating libpinmame."""
    candidates = []
    if sys.platform == "win32":
        plain = ["libpinmame.dll", "libpinmame-64.dll"]
        versioned = "libpinmame-*.dll"
        for name in plain:
            w = shutil.which(name)
            if w:
                candidates.append(w)
        userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        for d in (
            os.path.join(userprofile, "pinmame"),
            os.path.join(userprofile, "PinMAME"),
        ):
            candidates.extend(_glob_lib(d, versioned))
            for name in plain:
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    candidates.append(p)
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if not base:
                continue
            for sub in (
                r"Visual Pinball\VPinMAME",
                r"Visual Pinball X\VPinMAME",
                r"PinMAME",
            ):
                d = os.path.join(base, sub)
                candidates.extend(_glob_lib(d, versioned))
                for name in plain:
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        candidates.append(p)
        app_dir = os.path.dirname(sys.executable)
        candidates.extend(_glob_lib(app_dir, versioned))
        for name in plain:
            p = os.path.join(app_dir, name)
            if os.path.isfile(p):
                candidates.append(p)
    elif sys.platform == "darwin":
        libname = "libpinmame.dylib"
        which = shutil.which(libname)
        if which:
            candidates.append(which)
        for d in (
            "/usr/local/lib",
            "/opt/homebrew/lib",
            os.path.expanduser("~/Library/PinMAME"),
        ):
            candidates.extend(_glob_lib(d, "libpinmame*.dylib"))
            p = os.path.join(d, libname)
            if os.path.isfile(p):
                candidates.append(p)
    else:
        libname = "libpinmame.so"
        which = shutil.which(libname)
        if which:
            candidates.append(which)
        for d in (
            "/usr/lib",
            "/usr/local/lib",
            "/usr/lib/x86_64-linux-gnu",
            os.path.expanduser("~/.local/lib"),
        ):
            candidates.extend(_glob_lib(d, "libpinmame*.so*"))
            p = os.path.join(d, libname)
            if os.path.isfile(p):
                candidates.append(p)
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


_cached_path: Optional[str] = None
_cached_searched = False


def find_libpinmame() -> Optional[str]:
    """Locate ``libpinmame`` on the user's system, cached."""
    global _cached_path, _cached_searched
    if _cached_searched:
        return _cached_path
    _cached_searched = True
    for p in _candidate_paths():
        if os.path.isfile(p):
            _cached_path = p
            return p
    return None


def has_libpinmame() -> bool:
    return find_libpinmame() is not None


# ---------------------------------------------------------------------------
# libpinmame ctypes bindings
# ---------------------------------------------------------------------------

# Status / mode constants (from libpinmame.h)
PINMAME_STATUS_OK = 0
PINMAME_STATUS_CONFIG_NOT_SET = 1
PINMAME_STATUS_GAME_NOT_FOUND = 2
PINMAME_STATUS_GAME_ALREADY_RUNNING = 3
PINMAME_STATUS_EMULATOR_NOT_RUNNING = 4

PINMAME_AUDIO_FORMAT_INT16 = 0
PINMAME_AUDIO_FORMAT_FLOAT = 1

PINMAME_DMD_MODE_BRIGHTNESS = 0
PINMAME_DMD_MODE_RAW = 1

PINMAME_DISPLAY_TYPE_DMD = 14
PINMAME_DISPLAY_TYPE_VIDEO = 15
PINMAME_DISPLAY_TYPE_SEGMASK = 0x3F

PINMAME_LOG_LEVEL_DEBUG = 0
PINMAME_LOG_LEVEL_INFO = 1
PINMAME_LOG_LEVEL_ERROR = 2

PINMAME_MAX_PATH = 512


class PinmameGame(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("clone_of", ctypes.c_char_p),
        ("description", ctypes.c_char_p),
        ("year", ctypes.c_char_p),
        ("manufacturer", ctypes.c_char_p),
        ("flags", ctypes.c_uint32),
        ("found", ctypes.c_int32),
    ]


class PinmameDisplayLayout(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("top", ctypes.c_int32),
        ("left", ctypes.c_int32),
        ("length", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("depth", ctypes.c_int32),
    ]


class PinmameAudioInfo(ctypes.Structure):
    _fields_ = [
        ("format", ctypes.c_int),
        ("channels", ctypes.c_int),
        ("sampleRate", ctypes.c_double),
        ("framesPerSecond", ctypes.c_double),
        ("samplesPerFrame", ctypes.c_int),
        ("bufferSize", ctypes.c_int),
    ]


class PinmameMechInfo(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("length", ctypes.c_int),
        ("steps", ctypes.c_int),
        ("pos", ctypes.c_int),
        ("speed", ctypes.c_int),
    ]


class PinmameSolenoidState(ctypes.Structure):
    _fields_ = [("solNo", ctypes.c_int), ("state", ctypes.c_int)]


# Callback signatures.  PINMAMECALLBACK is ``__stdcall`` on MSVC, empty
# elsewhere.  Official libpinmame Windows releases are 64-bit, and on
# Win64 there is only one calling convention regardless of MSVC vs
# MinGW — so plain ``CFUNCTYPE`` works for both.  We use it universally.
_CB = ctypes.CFUNCTYPE

PinmameGameCallback = _CB(
    None, ctypes.POINTER(PinmameGame), ctypes.c_void_p)
PinmameOnStateUpdatedCallback = _CB(
    None, ctypes.c_int, ctypes.c_void_p)
PinmameOnDisplayAvailableCallback = _CB(
    None, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(PinmameDisplayLayout), ctypes.c_void_p)
PinmameOnDisplayUpdatedCallback = _CB(
    None, ctypes.c_int, ctypes.c_void_p,
    ctypes.POINTER(PinmameDisplayLayout), ctypes.c_void_p)
PinmameOnAudioAvailableCallback = _CB(
    ctypes.c_int, ctypes.POINTER(PinmameAudioInfo), ctypes.c_void_p)
PinmameOnAudioUpdatedCallback = _CB(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
PinmameOnMechAvailableCallback = _CB(
    None, ctypes.c_int, ctypes.POINTER(PinmameMechInfo), ctypes.c_void_p)
PinmameOnMechUpdatedCallback = _CB(
    None, ctypes.c_int, ctypes.POINTER(PinmameMechInfo), ctypes.c_void_p)
PinmameOnSolenoidUpdatedCallback = _CB(
    None, ctypes.POINTER(PinmameSolenoidState), ctypes.c_void_p)
PinmameOnConsoleDataUpdatedCallback = _CB(
    None, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
PinmameIsKeyPressedFunction = _CB(
    ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)
PinmameOnLogMessageCallback = _CB(
    None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
PinmameOnSoundCommandCallback = _CB(
    None, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)


class PinmameConfig(ctypes.Structure):
    _fields_ = [
        ("audioFormat", ctypes.c_int),
        ("sampleRate", ctypes.c_int),
        ("vpmPath", ctypes.c_char * PINMAME_MAX_PATH),
        ("cb_OnStateUpdated", PinmameOnStateUpdatedCallback),
        ("cb_OnDisplayAvailable", PinmameOnDisplayAvailableCallback),
        ("cb_OnDisplayUpdated", PinmameOnDisplayUpdatedCallback),
        ("cb_OnAudioAvailable", PinmameOnAudioAvailableCallback),
        ("cb_OnAudioUpdated", PinmameOnAudioUpdatedCallback),
        ("cb_OnMechAvailable", PinmameOnMechAvailableCallback),
        ("cb_OnMechUpdated", PinmameOnMechUpdatedCallback),
        ("cb_OnSolenoidUpdated", PinmameOnSolenoidUpdatedCallback),
        ("cb_OnConsoleDataUpdated", PinmameOnConsoleDataUpdatedCallback),
        ("fn_IsKeyPressed", PinmameIsKeyPressedFunction),
        ("cb_OnLogMessage", PinmameOnLogMessageCallback),
        ("cb_OnSoundCommand", PinmameOnSoundCommandCallback),
    ]


# ---------------------------------------------------------------------------
# Dataclasses returned by the capture
# ---------------------------------------------------------------------------

@dataclass
class CaptureFrame:
    """One captured DMD frame.

    ``data`` is the raw frame bytes as PinMAME hands them — one byte per
    pixel, width*height bytes total.  Each byte is a brightness value
    in 0..(2**``depth``-1) (so 0..3 for typical WPC 2-bit DMD, 0..15 for
    16-shade games).
    """
    timestamp_ms: int
    width: int
    height: int
    depth: int
    data: bytes


@dataclass
class CaptureConfig:
    """How to run a capture session."""
    rom_zip_path: str                 # path to MAME .zip the user supplied
    rom_name: str                     # the PinMAME-known short name
    duration_seconds: float = 120.0
    sample_rate: int = 48000
    capture_audio: bool = True
    capture_dmd: bool = True
    # If True, simulate a player credit-up + start + random playfield
    # switch pokes so the game enters gameplay mode and triggers
    # mode-start splashes, ball-launch sequences, scoring animations,
    # and end-of-ball cinematics — content that never appears in
    # pure attract-mode capture.
    simulate_gameplay: bool = True
    log_callback: Optional[Callable[[str, str], None]] = None
    progress_callback: Optional[Callable[[float], None]] = None
    # Live DMD preview hook.  Fires from the libpinmame display
    # callback thread with the raw RAW-mode frame bytes (one byte per
    # pixel, 0..(2**depth-1)).  Throttled to roughly ~20 fps so a
    # slow GUI consumer can't choke the capture thread.  Signature:
    #     fn(data: bytes, width: int, height: int, depth: int) -> None
    frame_callback: Optional[Callable] = None
    frame_callback_min_interval_ms: int = 50


@dataclass
class CaptureResult:
    """Frames + audio captured during one run."""
    frames: list = field(default_factory=list)        # list[CaptureFrame]
    audio_pcm: bytes = b""                            # int16 little-endian
    audio_sample_rate: int = 48000
    audio_channels: int = 1
    elapsed_seconds: float = 0.0
    log: list = field(default_factory=list)
    # If a scripted playthrough ran, this is the per-scene clip list
    # with absolute frame-time start/end markers.  Empty if we fell
    # back to attract-only / random-poke capture, in which case the
    # pipeline uses scene-detection segmentation.
    script_clips: list = field(default_factory=list)  # list[MomentClip]


# ---------------------------------------------------------------------------
# High-level capture wrapper
# ---------------------------------------------------------------------------

class PinmameCapture:
    """Run PinMAME under libpinmame and capture DMD frames + audio."""

    def __init__(self, libpinmame_path: Optional[str] = None):
        self.libpinmame_path = libpinmame_path or find_libpinmame()
        if self.libpinmame_path is None:
            raise FileNotFoundError(
                "libpinmame not found.  Install PinMAME from "
                "https://github.com/vpinball/pinmame/releases.")
        self._lib = None
        self._lock = threading.Lock()
        # The callbacks must stay alive for as long as the library
        # holds references to them; we stash them on the instance.
        self._callbacks: dict = {}
        # Per-run capture state
        self._frames: list = []
        self._audio_buffer: bytearray = bytearray()
        self._audio_sample_rate: int = 48000
        self._audio_channels: int = 1
        self._start_monotonic: float = 0.0
        self._running_event = threading.Event()
        self._stopped_event = threading.Event()
        self._log: list = []
        self._log_cb: Optional[Callable[[str, str], None]] = None
        self._state: int = 0
        # Fires when the per-game script finishes its last moment;
        # the main capture loop uses this to end the recording early
        # instead of padding with idle ball-search frames.
        self._script_done_event = threading.Event()
        # Script execution outputs (filled in run()).
        self._rom_name: str = ""
        self._script_clips: list = []
        self._active_script = None  # GameScript instance, set in run()
        # Live frame-callback (GUI DMD preview).
        self._frame_cb: Optional[Callable] = None
        self._frame_cb_interval_ms: int = 50
        self._last_frame_cb_ms: int = 0

    # ------------------------------------------------------------------
    # Library loading + function-signature setup
    # ------------------------------------------------------------------

    def _load(self):
        if self._lib is not None:
            return
        lib = ctypes.CDLL(self.libpinmame_path)
        lib.PinmameSetConfig.argtypes = [ctypes.POINTER(PinmameConfig)]
        lib.PinmameSetConfig.restype = None
        lib.PinmameRun.argtypes = [ctypes.c_char_p]
        lib.PinmameRun.restype = ctypes.c_int
        lib.PinmameStop.argtypes = []
        lib.PinmameStop.restype = None
        lib.PinmameIsRunning.argtypes = []
        lib.PinmameIsRunning.restype = ctypes.c_int
        lib.PinmamePause.argtypes = [ctypes.c_int]
        lib.PinmamePause.restype = ctypes.c_int
        lib.PinmameSetDmdMode.argtypes = [ctypes.c_int]
        lib.PinmameSetDmdMode.restype = None
        lib.PinmameSetHandleKeyboard.argtypes = [ctypes.c_int]
        lib.PinmameSetHandleKeyboard.restype = None
        lib.PinmameSetHandleMechanics.argtypes = [ctypes.c_int]
        lib.PinmameSetHandleMechanics.restype = None
        lib.PinmameSetCheat.argtypes = [ctypes.c_int]
        lib.PinmameSetCheat.restype = None
        lib.PinmameSetSwitch.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.PinmameSetSwitch.restype = None
        self._lib = lib

    # ------------------------------------------------------------------
    # Callback implementations
    # ------------------------------------------------------------------

    def _emit_log(self, text: str, level: str = "info"):
        self._log.append((level, text))
        if self._log_cb is not None:
            try:
                self._log_cb(text, level)
            except Exception:
                pass

    def _cb_state(self, state, userdata):
        # state == 1 means game running; 0 means stopped
        self._state = state
        if state == 1:
            self._running_event.set()
            # Reset the timing origin so display-callback timestamps
            # start from the moment the game actually began running,
            # not from the moment we set up callbacks.
            self._start_monotonic = time.monotonic()
            self._emit_log("PinMAME state: running", "info")
        elif state == 0:
            self._stopped_event.set()
            self._emit_log("PinMAME state: stopped", "info")

    def _cb_display_available(self, index, count, layout_ptr, userdata):
        layout = layout_ptr.contents
        self._emit_log(
            f"Display #{index}/{count} type=0x{layout.type:X} "
            f"{layout.width}x{layout.height} depth={layout.depth}", "info")

    def _cb_display_updated(self, index, data_ptr, layout_ptr, userdata):
        # Wrap in try/except — exceptions out of ctypes callbacks
        # silently corrupt the C side.
        try:
            self._display_invocations = getattr(
                self, "_display_invocations", 0) + 1
            if data_ptr is None or data_ptr == 0:
                self._display_null_count = getattr(
                    self, "_display_null_count", 0) + 1
            else:
                self._display_nonnull_count = getattr(
                    self, "_display_nonnull_count", 0) + 1
            if data_ptr is None or data_ptr == 0:
                # libpinmame calls us with NULL when the frame hasn't
                # changed (saves a memcpy).  We re-use the previous
                # frame buffer in that case so the per-frame timeline
                # is still continuous.
                if self._last_frame_data is None:
                    return
                data = self._last_frame_data
                width = self._last_layout_w
                height = self._last_layout_h
                depth = self._last_layout_depth
            else:
                layout = layout_ptr.contents
                is_dmd = (layout.type & PINMAME_DISPLAY_TYPE_SEGMASK) == \
                    PINMAME_DISPLAY_TYPE_DMD
                if not is_dmd:
                    return
                width, height, depth = layout.width, layout.height, layout.depth
                size = width * height
                if size <= 0 or size > 1024 * 1024:
                    return
                data = ctypes.string_at(data_ptr, size)
                self._last_frame_data = data
                self._last_layout_w = width
                self._last_layout_h = height
                self._last_layout_depth = depth
            ts_ms = int((time.monotonic() - self._start_monotonic) * 1000)
            self._frames.append(CaptureFrame(
                timestamp_ms=ts_ms,
                width=width, height=height, depth=depth, data=data,
            ))
            # Throttled live-preview push to the GUI.  The capture
            # thread MUST NOT block on the GUI consumer — we just
            # call the callback with the latest bytes and let the
            # consumer schedule its own redraw at a sustainable rate.
            if self._frame_cb is not None:
                now_ms = ts_ms
                if (now_ms - self._last_frame_cb_ms
                        >= self._frame_cb_interval_ms):
                    self._last_frame_cb_ms = now_ms
                    try:
                        self._frame_cb(data, width, height, depth)
                    except Exception:
                        # Don't propagate GUI errors back into the
                        # ctypes callback — that would crash PinMAME.
                        pass
        except Exception as e:
            # Exceptions in ctypes callbacks corrupt the C stack.
            # Convert to a recorded log entry.
            try:
                self._emit_log(
                    f"_cb_display_updated error: {e!r}", "error")
            except Exception:
                pass

    def _cb_audio_available(self, audio_info_ptr, userdata):
        info = audio_info_ptr.contents
        self._audio_sample_rate = int(info.sampleRate)
        self._audio_channels = max(1, info.channels)
        self._emit_log(
            f"Audio: {info.sampleRate:.0f}Hz, {info.channels}ch, "
            f"buffer={info.bufferSize}", "info")
        return info.samplesPerFrame

    def _cb_audio_updated(self, buffer_ptr, samples, userdata):
        # samples is the count of "audio frames" (samples per channel).
        # Each int16 sample is 2 bytes; total = samples * channels * 2.
        if not buffer_ptr or samples <= 0:
            return samples
        byte_count = samples * self._audio_channels * 2
        try:
            self._audio_buffer.extend(
                ctypes.string_at(buffer_ptr, byte_count))
        except Exception:
            pass
        return samples

    def _seed_boot_switch_state(self):
        """Seed the minimum WPC switch state so coins + start work.

        Reads per-game switch numbers from ``self._active_script`` —
        each title's trough range / shooter-lane / eject position
        differs (AFM trough = 32-35, FT trough = 16-18, IJ trough =
        81-86, etc.) so a hardcoded seed would be wrong for most
        titles.

        Two switch categories matter:

          - Coin door (sw 22) — PinMAME defaults OPEN; with the door
            open the ROM shows "COIN DOOR OPEN — COILS AND FLASHERS
            DISABLED" and refuses to accept coins.
          - Trough — PinMAME's default-zero matrix reads as "no balls
            in trough"; if the ROM polls and sees that at boot or
            after Start it triggers ball-search ("LOCATING BALLS,
            PLEASE WAIT") and the game wedges.  Seeding the trough
            closed mirrors a real machine.
        """
        script = self._active_script
        try:
            self._lib.PinmameSetSwitch(script.sw_coin_door, 1)
            for sw in script.sw_trough:
                self._lib.PinmameSetSwitch(sw, 1)
            if script.sw_eject is not None:
                self._lib.PinmameSetSwitch(script.sw_eject, 0)
            if script.sw_shooter_lane is not None:
                self._lib.PinmameSetSwitch(script.sw_shooter_lane, 0)
            self._emit_log(
                f"Seeded boot switches ({script.title}): coin door "
                f"sw#{script.sw_coin_door} CLOSED, "
                f"trough {script.sw_trough} FULL, "
                f"eject sw#{script.sw_eject} EMPTY, "
                f"shooter-lane sw#{script.sw_shooter_lane} EMPTY.",
                "info")
        except Exception as e:
            self._emit_log(
                f"_seed_boot_switch_state failed: {e}", "warning")

    # ------------------------------------------------------------------
    # Gameplay simulation
    # ------------------------------------------------------------------

    def _press_switch(self, sw_no: int, hold_ms: int = 100):
        """Simulate a momentary switch press: ON -> hold -> OFF."""
        try:
            self._lib.PinmameSetSwitch(sw_no, 1)
            time.sleep(hold_ms / 1000.0)
            self._lib.PinmameSetSwitch(sw_no, 0)
        except Exception as e:
            self._emit_log(
                f"PinmameSetSwitch({sw_no}) failed: {e}", "warning")

    def _set_switch(self, sw_no: int, state: int):
        """Force a switch into a sustained state (no auto-release)."""
        try:
            self._lib.PinmameSetSwitch(sw_no, 1 if state else 0)
        except Exception as e:
            self._emit_log(
                f"PinmameSetSwitch({sw_no},{state}) failed: {e}", "warning")

    # AFM (and most WPC) ball-tracking switch conventions, sourced
    # from PinMAME's ``src/wpc/sims/wpc/full/afm.c``:
    #
    #   sw 31 = swTEject     (ball at the eject position, between
    #                         trough and shooter-lane channel)
    #   sw 32 = swTrough1    (next ball to be released — shallowest)
    #   sw 33 = swTrough2
    #   sw 34 = swTrough3
    #   sw 35 = swTrough4    (deepest)
    #   sw 18 = swSLane      (ball-in-shooter-lane proximity)
    #
    # All trough + eject + shooter-lane switches are "closed when ball
    # present".
    #
    # The ball-in-play handoff sequence the ROM expects:
    #
    #   t0  player presses Start.
    #   t1  ROM fires sBallRel solenoid (sol#2) — kicks the ball at
    #       trough position 1 (sw 32) up to the shooter lane.
    #   t2  sw 32 OPENS (ball gone from trough), sw 18 CLOSES (ball
    #       arrives in shooter lane).
    #   t3  Skill-shot opportunity (~2s).
    #   t4  player presses Launch (sw 11).
    #   t5  ROM fires sAutoFire solenoid (sol#1) — auto-plunger flings
    #       the ball into the playfield.
    #   t6  sw 18 OPENS (ball gone from lane) within ~500ms.
    #   t7+ active play.  State: sw 32 open, sw 33-35 closed
    #       (3 balls still in trough), sw 18 open.
    _SW_EJECT = 31
    _SW_TROUGH = (32, 33, 34, 35)
    _SW_SHOOTER_LANE = 18

    def _eject_to_shooter_lane(self):
        """Simulate the trough kicker ejecting a ball into the lane.

        After this call the ROM sees:
          - sw 31 OPEN (one ball gone from trough)
          - sw 32, 33, 34 CLOSED (3 balls still in trough)
          - sw 19 CLOSED (ball sitting in shooter lane)
        """
        self._set_switch(self._SW_TROUGH[0], 0)
        for sw in self._SW_TROUGH[1:]:
            self._set_switch(sw, 1)
        self._set_switch(self._SW_SHOOTER_LANE, 1)
        self._emit_log(
            "Ball ejected: trough[0] OPEN, trough[1:] CLOSED, "
            "shooter-lane CLOSED.", "info")

    def _ball_leaves_shooter_lane(self):
        """Plunger fired — ball is on its way up the lane to playfield."""
        self._set_switch(self._SW_SHOOTER_LANE, 0)
        self._emit_log(
            "Shooter-lane switch OPEN = ball in active play.", "info")

    def _reassert_ball_in_play(self):
        """Re-stamp the ball-in-play switch state.

        Called periodically during the active-play loop so the ROM
        doesn't latch a brief flicker from our random switch pokes as
        "ball drained" or "ball returned to trough".
        """
        self._set_switch(self._SW_TROUGH[0], 0)
        for sw in self._SW_TROUGH[1:]:
            self._set_switch(sw, 1)
        self._set_switch(self._SW_SHOOTER_LANE, 0)

    def _gameplay_simulation_loop(self, stop_event):
        """Drive the emulator like a player: credit, start, launch,
        and fire ramps / loops / bumpers / saucers in sequences that
        actually trigger mode starts and jackpot animations.

        Generic WPC strategy (informed by inspecting AFM's switch
        matrix in ``src/wpc/sims/wpc/full/afm.c`` — most WPC titles
        of the era share these conventional ranges):

          1-8     dedicated (coin slots)
          9-16    cabinet (launch=11, start=13, tilt=14, outholes=16,27)
          17-30   apron + ball-trough region — AVOID, hitting trough
                  switches mid-play confuses the ball-tracking logic
          31-35   trough — DEFINITELY AVOID (it'll think balls are
                  vanishing into the trough)
          41-48   stand-up target banks
          51-55   slingshots + jet bumpers
          56-58   more target banks
          61-65   ramps (entry / top / exit)
          66-67   misc (motor bank up/down on AFM)
          71-74   left + right loops
          75-76   saucers / scoops / lock holes
          77      drop target

        The strategy:

          1. Boot delay → close coin door (already done by caller).
          2. Drop a coin (sw 1) + press Start (sw 13).
          3. Wait for the trough kicker to eject the ball into the
             shooter lane, then press Launch (sw 11).
          4. In a loop until ``stop_event``:
             - Fire flipper-style switches (49/50 on most WPCs) so
               the game thinks the player is keeping the ball alive.
             - Periodically hit RAMP SEQUENCES (entry → top → exit
               in quick succession — simulates a complete ramp shot,
               which is what triggers mode-advance cinematics).
             - Periodically hit SAUCER / LOCK switches (75/76) — the
               classic multiball-lock cue.
             - Periodically hit LOOP combos (entry + exit).
             - Pepper in random target / bumper hits between.
             - Re-press Launch every ~10s in case the ball returned
               to the shooter lane.
          5. Every 60s: pretend the ball drained, re-coin + restart.
        """
        from . import game_scripts
        # Script was resolved in run() — use the same one for the
        # whole capture so switch maps stay coherent.
        script = self._active_script
        SW_COIN_LEFT = script.sw_coin_left
        SW_START = script.sw_start

        # 1. Wait for boot self-test to finish (some WPC titles spend
        # 5-7s on RAM/ROM checks before they accept any input).
        time.sleep(8.0)
        if stop_event.is_set():
            return

        # 2. ESCAPE the operator menu in case the game is sitting in
        # one — a fresh-NVRAM AFM can land in "FACTORY DEFAULTS
        # CONFIRMED" or "AUDITS" mode where Start is ignored.
        # ESCAPE on WPC is dedicated switch D5 (slot 5).  Spam it a
        # few times to walk back out of any nested setup menu.
        self._emit_log("Pressing Escape (sw 5) 4x to exit any menu...",
                       "info")
        for _ in range(4):
            if stop_event.is_set():
                return
            self._press_switch(5, hold_ms=200)
            time.sleep(0.4)
        time.sleep(1.0)

        # 3. Insert coins.  Default WPC coinage on most games is
        # 3 coins / credit; 8 covers up to 4:1 pricing safely.
        self._emit_log("Inserting coins (8x)...", "info")
        for _ in range(8):
            if stop_event.is_set():
                return
            self._press_switch(SW_COIN_LEFT, hold_ms=120)
            time.sleep(0.35)
        # Let the credits message finish + chime clear before Start.
        time.sleep(2.0)

        # 4. Press Start.  Detect acceptance by watching for any
        # new mechanism-range solenoid (sol#1-16) to fire DURING
        # this specific press window — per-press snapshot of the
        # seen-set, not first-time-ever.  The trough-release solenoid
        # number varies per game (sBallRel=2 on AFM, sTrough=14 on
        # No Fear, etc.) and may have already fired during attract
        # or coin insertion, so we can't rely on a single sol number
        # or a global first-time check.
        accepted = False
        self._emit_log(
            f"Pressing Start (sw#{SW_START}) up to 6x...", "info")
        for i in range(6):
            if stop_event.is_set():
                return
            # Snapshot solenoid counts immediately before this press.
            sol_counts_before = dict(self._sol_counts)
            self._press_switch(SW_START, hold_ms=800)
            # Poll up to 1.5s for any mechanism solenoid to fire
            # more times than it had before the press.  Game-start
            # bursts include 2-4 mechanism solenoid fires (trough
            # release, autoplunger, credit chime, etc.) so even one
            # extra count is a strong positive signal.
            deadline = time.monotonic() + 1.5
            new_fires = []
            while time.monotonic() < deadline:
                if stop_event.is_set():
                    return
                for sol, count in self._sol_counts.items():
                    if (sol in self._SOL_MECHANISM_RANGE
                            and count > sol_counts_before.get(sol, 0)):
                        new_fires.append(sol)
                if new_fires:
                    break
                time.sleep(0.05)
            if new_fires:
                self._emit_log(
                    f"Start accepted on press #{i + 1} — "
                    f"mechanism solenoid(s) {sorted(set(new_fires))} "
                    "fired in response.", "success")
                accepted = True
                break
        if not accepted:
            self._emit_log(
                "No mechanism solenoid fired after any Start press "
                "— game did NOT enter play.  Aborting sim loop.",
                "warning")
            return

        # 5. The ROM has fired the trough release solenoid (sBallRel,
        # typically sol#2).  Simulate the ball's journey from trough
        # position 0 up the ball channel to the shooter lane.
        if script.sw_trough:
            self._set_switch(script.sw_trough[0], 0)
            time.sleep(0.3)
        if script.sw_shooter_lane is not None:
            self._set_switch(script.sw_shooter_lane, 1)
        self._emit_log(
            f"Ball traveled: trough[0] (sw#{script.sw_trough[0]}) OPEN, "
            f"shooter-lane (sw#{script.sw_shooter_lane}) CLOSED.",
            "info")
        # Hold in shooter lane briefly so the skill-shot window can
        # render.
        time.sleep(2.0)

        # 6. Fire the auto-plunger.  Newer games (1995+) have a
        # dedicated Launch button; older WPC games used a manual
        # plunger spring and have no swLaunch — for those, the ROM
        # waits for the shooter-lane switch to open on its own (when
        # the ball "leaves").  We simulate that by just clearing the
        # lane after a brief skill-shot window.
        if script.sw_launch is not None:
            self._emit_log(
                f"Pressing Launch (sw#{script.sw_launch})...", "info")
            self._press_switch(script.sw_launch, hold_ms=200)
            time.sleep(0.6)
        else:
            self._emit_log(
                "No launch button on this title — letting ball auto-"
                "leave the shooter lane.", "info")
            time.sleep(1.2)
        if script.sw_shooter_lane is not None:
            self._set_switch(script.sw_shooter_lane, 0)
        self._emit_log(
            "Shooter-lane OPEN = ball in active play.", "info")
        time.sleep(0.5)

        # 7. Active play: drive the per-game script's ordered
        # moments.  Each moment is a known sequence of switches that
        # the game's rules say will trigger a specific cinematic
        # (skill shot, ramp completion, lock, multiball, etc.).  The
        # runner records start/end timestamps per moment so the
        # pipeline can emit one named MP4 per scene.
        def now_ms() -> int:
            return int((time.monotonic() - self._start_monotonic) * 1000)

        try:
            self._script_clips = game_scripts.run_script(
                script=script,
                set_switch=self._lib.PinmameSetSwitch,
                log=self._emit_log,
                stop_check=stop_event.is_set,
                now_ms=now_ms,
                after_each_moment_delay_s=1.5,
            )
        except Exception as e:
            self._emit_log(f"Script runner crashed: {e!r}", "error")
        # Signal the main capture loop that the scripted playthrough
        # is fully complete — it can then end the capture early
        # rather than padding the recording with idle ball-search
        # frames waiting for ``duration_seconds`` to elapse.
        self._script_done_event.set()

    # No-op callbacks for the events we don't care about
    def _cb_mech_available(self, mech, info_ptr, userdata): pass
    def _cb_mech_updated(self, mech, info_ptr, userdata): pass

    # WPC games consistently assign sol#1-16 to game-mechanism
    # solenoids (trough release, autoplunger, knocker, slings, pop
    # bumpers, jets, saucer kickers, drop reset).  Higher numbers
    # (17+) are flashers — attract mode pulses them constantly, so
    # they're useless as a "Start accepted" signal.  We watch for
    # any NEW sol in the mechanism range to fire after we press
    # Start; that's reliable across every WPC game regardless of
    # the specific trough-release solenoid number (sBallRel=2 on
    # AFM, but other games shuffle the assignments).
    _SOL_MECHANISM_RANGE = range(1, 17)

    def _cb_solenoid_updated(self, state_ptr, userdata):
        """Tally solenoid energizations + react to game-start signals.

        First-time-seen events log to the live console; total counts
        feed the end-of-capture activity summary.  When we're
        watching for the ROM to accept Start, any *new* low-numbered
        solenoid firing signals acceptance.
        """
        try:
            st = state_ptr.contents
            sol = st.solNo
            if st.state:
                self._sol_counts[sol] = self._sol_counts.get(sol, 0) + 1
                is_first_time = sol not in self._sol_seen
                if is_first_time:
                    self._sol_seen.add(sol)
                    elapsed = time.monotonic() - self._start_monotonic
                    self._emit_log(
                        f"[sol] sol#{sol} energized first time "
                        f"@ t={elapsed:.1f}s", "info")
                # Game-start detection now happens in the sim thread
                # via per-press snapshots of _sol_counts (see
                # _gameplay_simulation_loop).  This callback just
                # maintains _sol_counts; the watcher is gone.
        except Exception:
            pass

    def _cb_console_data(self, data, size, userdata): pass
    def _cb_is_key_pressed(self, keycode, userdata): return 0

    def _cb_sound_command(self, board, cmd, userdata):
        """Log sound commands.

        WPC sound boards play distinct cues for:
          * Coin chime (when a credit registers — proves coin slot worked)
          * Game start tune (when Start is accepted — proves game began)
          * Mode-start jingles, jackpot fanfares, etc.

        Logging every sound is noisy (hundreds per game), so we only
        log distinct (board, cmd) tuples — first-time-seen events.
        """
        try:
            key = (board, cmd)
            if key not in self._snd_seen:
                self._snd_seen.add(key)
                self._emit_log(
                    f"[snd] board={board} cmd=0x{cmd:04X} (first time)",
                    "info")
        except Exception:
            pass

    def _cb_log_message(self, level, fmt, args, userdata):
        # PinMAME's log callback hands us (printf format, va_list).
        # We use the C runtime's vsnprintf via ctypes to substitute
        # the args into the format string — otherwise we just see
        # uninterpolated %s/%d markers and can't diagnose anything.
        if level == PINMAME_LOG_LEVEL_DEBUG:
            return
        try:
            text = _vsnprintf(fmt, args)
        except Exception:
            try:
                text = fmt.decode("utf-8", "replace") if fmt else ""
            except Exception:
                text = "<binary>"
        lvl = "error" if level == PINMAME_LOG_LEVEL_ERROR else "info"
        self._emit_log(f"[pinmame] {text.rstrip()}", lvl)

    # ------------------------------------------------------------------
    # Run a capture session
    # ------------------------------------------------------------------

    def run(self, config: CaptureConfig) -> CaptureResult:
        """Set up PinMAME for *config.rom_name* and capture for *duration_seconds*.

        Returns a :class:`CaptureResult`.  Blocks for the duration.
        """
        self._load()
        self._log_cb = config.log_callback

        # Reset per-run state
        self._frames = []
        self._audio_buffer = bytearray()
        self._log = []
        self._running_event.clear()
        self._stopped_event.clear()
        self._state = 0
        self._last_frame_data = None
        self._last_layout_w = 0
        self._last_layout_h = 0
        self._last_layout_depth = 0
        self._display_invocations = 0
        self._sol_seen = set()
        self._sol_counts = {}
        self._snd_seen = set()
        self._script_done_event.clear()
        self._rom_name = config.rom_name
        self._script_clips = []
        self._frame_cb = config.frame_callback
        self._frame_cb_interval_ms = max(
            10, int(config.frame_callback_min_interval_ms))
        self._last_frame_cb_ms = 0
        # Resolve the per-game script up-front so the boot-seed +
        # ball-handoff helpers can use its switch map.
        from . import game_scripts
        self._active_script = game_scripts.get_script_for_rom(
            config.rom_name)
        self._emit_log(
            f"Active script: {self._active_script.title} "
            f"({len(self._active_script.moments)} moments, "
            f"trough={self._active_script.sw_trough}, "
            f"lane=sw#{self._active_script.sw_shooter_lane}, "
            f"launch=sw#{self._active_script.sw_launch})",
            "info")

        # Set up vpmPath/roms/<rom_name>.zip
        vpm_dir = _ensure_vpm_dir(config.rom_zip_path, config.rom_name,
                                  log=self._emit_log)
        self._emit_log(f"vpmPath = {vpm_dir}", "info")

        # Build callback objects.  CRITICAL: store on self so they stay
        # alive for the duration of the C library's reference.
        self._callbacks = {
            "state": PinmameOnStateUpdatedCallback(self._cb_state),
            "disp_avail": PinmameOnDisplayAvailableCallback(
                self._cb_display_available),
            "disp_upd": PinmameOnDisplayUpdatedCallback(
                self._cb_display_updated),
            "aud_avail": PinmameOnAudioAvailableCallback(
                self._cb_audio_available),
            "aud_upd": PinmameOnAudioUpdatedCallback(self._cb_audio_updated),
            "mech_avail": PinmameOnMechAvailableCallback(
                self._cb_mech_available),
            "mech_upd": PinmameOnMechUpdatedCallback(self._cb_mech_updated),
            "sol_upd": PinmameOnSolenoidUpdatedCallback(
                self._cb_solenoid_updated),
            "console": PinmameOnConsoleDataUpdatedCallback(
                self._cb_console_data),
            "key": PinmameIsKeyPressedFunction(self._cb_is_key_pressed),
            "log": PinmameOnLogMessageCallback(self._cb_log_message),
            "sound": PinmameOnSoundCommandCallback(self._cb_sound_command),
        }

        cfg = PinmameConfig()
        cfg.audioFormat = PINMAME_AUDIO_FORMAT_INT16
        cfg.sampleRate = config.sample_rate
        # vpmPath is a c_char fixed-size array.  Assigning to
        # ``cfg.vpmPath`` *does* write into the underlying buffer
        # (ctypes handles the array copy), but passing the read of
        # the field to memmove() does NOT — that returns a Python
        # bytes copy.  Use direct assignment.
        path_bytes = vpm_dir.encode("utf-8")
        if len(path_bytes) >= PINMAME_MAX_PATH:
            path_bytes = path_bytes[:PINMAME_MAX_PATH - 1]
        cfg.vpmPath = path_bytes
        cfg.cb_OnStateUpdated = self._callbacks["state"]
        cfg.cb_OnDisplayAvailable = self._callbacks["disp_avail"]
        cfg.cb_OnDisplayUpdated = self._callbacks["disp_upd"]
        cfg.cb_OnAudioAvailable = self._callbacks["aud_avail"]
        cfg.cb_OnAudioUpdated = self._callbacks["aud_upd"]
        cfg.cb_OnMechAvailable = self._callbacks["mech_avail"]
        cfg.cb_OnMechUpdated = self._callbacks["mech_upd"]
        cfg.cb_OnSolenoidUpdated = self._callbacks["sol_upd"]
        cfg.cb_OnConsoleDataUpdated = self._callbacks["console"]
        cfg.fn_IsKeyPressed = self._callbacks["key"]
        cfg.cb_OnLogMessage = self._callbacks["log"]
        cfg.cb_OnSoundCommand = self._callbacks["sound"]

        self._lib.PinmameSetConfig(ctypes.byref(cfg))
        # RAW mode hands us the underlying packed-bitplane bytes the
        # WPC ASIC wrote to VRAM (one byte per pixel where each byte
        # holds an N-bit brightness value).  BRIGHTNESS mode pre-mixes
        # the planes to 0..255 luminance.  We use RAW — same as
        # libpinmame's own test.cpp — so we get the canonical
        # pixel-by-pixel data and can decide brightness mapping
        # ourselves at render time.
        self._lib.PinmameSetDmdMode(PINMAME_DMD_MODE_RAW)
        self._lib.PinmameSetHandleKeyboard(0)
        self._lib.PinmameSetHandleMechanics(0)
        self._lib.PinmameSetCheat(0)

        # Start the game.  PinmameRun is *synchronous* up through the
        # state→running callback (the emulator finishes loading ROMs
        # and starts ticking before returning).
        self._emit_log(f"PinmameRun({config.rom_name!r})...", "info")
        status = self._lib.PinmameRun(config.rom_name.encode("utf-8"))
        if status != PINMAME_STATUS_OK:
            self._emit_log(
                f"PinmameRun failed: status={status}", "error")
            raise RuntimeError(_describe_status(status))

        # Wait for the state callback to fire with state=1, with a
        # generous timeout for slow ROM loads.  If the game never
        # reaches running state, the stopped event will fire instead
        # (e.g. ROM load failure).
        wait_deadline = time.monotonic() + 15.0
        while not self._running_event.is_set():
            if self._stopped_event.is_set():
                raise RuntimeError(
                    "PinMAME stopped before reaching running state. "
                    "Check the log for ROM load errors.")
            if time.monotonic() > wait_deadline:
                raise RuntimeError(
                    "PinMAME never reached running state within 15s. "
                    "ROM load may be hung.")
            time.sleep(0.05)

        # Seed the WPC switch matrix to "clean attract" state:
        # coin door closed, tilts open, all 4 balls present in
        # trough, shooter-lane empty.  Without this the ROM boots,
        # polls a default-all-zero matrix, concludes "balls missing"
        # and gets stuck in ball-search / diagnostic — which is
        # exactly the "test report" screens that dominated earlier
        # captures.
        self._seed_boot_switch_state()

        # Optional: simulate a player so the game enters gameplay
        # mode and we capture mode-start cinematics, jackpot
        # animations, end-of-ball scoring, etc.
        sim_stop = threading.Event()
        sim_thread = None
        if config.simulate_gameplay:
            sim_thread = threading.Thread(
                target=self._gameplay_simulation_loop,
                args=(sim_stop,), daemon=True)
            sim_thread.start()

        # Now block for the capture duration — or end early if the
        # scripted playthrough finished and a short grace window has
        # elapsed (lets us pick up any trailing EOB / game-over
        # animations before stopping).
        SCRIPT_DONE_GRACE_S = 5.0
        start = time.monotonic()
        script_done_t: Optional[float] = None
        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= config.duration_seconds:
                    break
                if self._stopped_event.is_set():
                    self._emit_log(
                        "PinMAME stopped early — capturing what we have.",
                        "warning")
                    break
                if self._script_done_event.is_set():
                    if script_done_t is None:
                        script_done_t = time.monotonic()
                        self._emit_log(
                            f"Script done — capturing {SCRIPT_DONE_GRACE_S:.0f}s "
                            "more for trailing animations, then stopping.",
                            "info")
                    elif (time.monotonic() - script_done_t
                            >= SCRIPT_DONE_GRACE_S):
                        self._emit_log(
                            "Script-done grace window elapsed — "
                            "ending capture early.", "success")
                        break
                if config.progress_callback:
                    try:
                        config.progress_callback(
                            elapsed / config.duration_seconds)
                    except Exception:
                        pass
                time.sleep(0.1)
        finally:
            self._emit_log("Stopping PinMAME...", "info")
            sim_stop.set()
            if sim_thread is not None:
                sim_thread.join(timeout=2.0)
            try:
                self._lib.PinmameStop()
            except Exception as e:
                self._emit_log(f"PinmameStop error: {e}", "warning")
            # Give it a moment to wind down
            for _ in range(40):
                if self._stopped_event.is_set():
                    break
                time.sleep(0.05)

        elapsed = time.monotonic() - start
        self._emit_log(
            f"Capture complete: {len(self._frames)} frames "
            f"(display callback fired {self._display_invocations}x: "
            f"null={getattr(self, '_display_null_count', 0)} "
            f"nonnull={getattr(self, '_display_nonnull_count', 0)}), "
            f"{len(self._audio_buffer)} audio bytes in {elapsed:.1f}s",
            "success")

        # Dump top-10 most-fired solenoids — the difference between
        # "attract mode only" and "active gameplay" is visible here:
        # gameplay sees slings (sol 5/6 typical) firing 100x+, attract
        # sees flashers firing 10-20x at most.
        if self._sol_counts:
            top = sorted(self._sol_counts.items(),
                         key=lambda kv: -kv[1])[:10]
            self._emit_log(
                "Solenoid activity (top 10 by count): "
                + ", ".join(f"sol#{s}={n}" for s, n in top),
                "info")

        return CaptureResult(
            frames=self._frames,
            audio_pcm=bytes(self._audio_buffer),
            audio_sample_rate=self._audio_sample_rate,
            audio_channels=self._audio_channels,
            elapsed_seconds=elapsed,
            log=list(self._log),
            script_clips=list(self._script_clips),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _describe_status(status: int) -> str:
    names = {
        PINMAME_STATUS_OK: "OK",
        PINMAME_STATUS_CONFIG_NOT_SET: "config not set",
        PINMAME_STATUS_GAME_NOT_FOUND: "game ROM not found in vpmPath/roms/",
        PINMAME_STATUS_GAME_ALREADY_RUNNING: "game already running",
        PINMAME_STATUS_EMULATOR_NOT_RUNNING: "emulator not running",
    }
    return f"PinmameRun status {status} ({names.get(status, 'unknown')})"


def _ensure_vpm_dir(rom_zip_path: str, rom_name: str, log=None) -> str:
    """Copy the user's ROM zip into a vpmPath/roms/<rom_name>.zip layout.

    PinMAME requires its ``vpmPath`` directory to contain a ``roms/``
    subdirectory with the game zip named ``<rom_name>.zip``.  Returns
    the vpmPath (parent of the roms directory).
    """
    if sys.platform == "win32":
        base = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "pinball_decryptor", "pinmame_vpm")
    elif sys.platform == "darwin":
        base = os.path.expanduser(
            "~/Library/Application Support/pinball_decryptor/pinmame_vpm")
    else:
        base = os.path.expanduser("~/.cache/pinball_decryptor/pinmame_vpm")
    roms_dir = os.path.join(base, "roms")
    os.makedirs(roms_dir, exist_ok=True)
    os.makedirs(os.path.join(base, "nvram"), exist_ok=True)
    os.makedirs(os.path.join(base, "cfg"), exist_ok=True)
    # NB: do NOT wipe NVRAM between runs.  WPC ROMs detect a
    # missing NVRAM as a battery-failure / factory-restore event
    # and lock the game in a "FACTORY RESTORE COMPLETED" prompt
    # that requires manual operator-key acknowledgement to clear.
    # Once initialized, NVRAM is safe to persist across captures —
    # the game just sees it as a normal warm boot.
    dest = os.path.join(roms_dir, f"{rom_name}.zip")
    # If destination is the same file as source, skip the copy.
    if not os.path.exists(dest) or os.path.getmtime(dest) < os.path.getmtime(rom_zip_path):
        shutil.copy2(rom_zip_path, dest)
        if log:
            log(f"Copied {os.path.basename(rom_zip_path)} -> {dest}",
                "info")
    # Always include a trailing separator — libpinmame's test.cpp appends one,
    # and PinMAME's path parsing expects it.
    return base + os.sep


# ---------------------------------------------------------------------------
# vsnprintf glue — used by the log callback to format printf-style
# messages PinMAME hands us as (format, va_list).
# ---------------------------------------------------------------------------

_crt = None
_crt_vsnprintf = None


def _init_crt():
    """Lazy-load the C runtime so we can format va_args."""
    global _crt, _crt_vsnprintf
    if _crt_vsnprintf is not None:
        return _crt_vsnprintf
    if sys.platform == "win32":
        # Modern Windows ships ucrtbase.dll which exports __stdio_common_vsnprintf,
        # but the easier path is to use msvcrt's vsnprintf (still present on
        # everything from XP onward and works fine for cdecl callers).
        try:
            _crt = ctypes.CDLL("msvcrt")
            _crt_vsnprintf = _crt.vsnprintf
            _crt_vsnprintf.argtypes = [
                ctypes.c_char_p, ctypes.c_size_t,
                ctypes.c_char_p, ctypes.c_void_p]
            _crt_vsnprintf.restype = ctypes.c_int
        except OSError:
            _crt_vsnprintf = None
    else:
        try:
            _crt = ctypes.CDLL("libc.so.6") if sys.platform != "darwin" \
                else ctypes.CDLL("libSystem.dylib")
            _crt_vsnprintf = _crt.vsnprintf
            _crt_vsnprintf.argtypes = [
                ctypes.c_char_p, ctypes.c_size_t,
                ctypes.c_char_p, ctypes.c_void_p]
            _crt_vsnprintf.restype = ctypes.c_int
        except OSError:
            _crt_vsnprintf = None
    return _crt_vsnprintf


def _vsnprintf(fmt, args):
    """Format *fmt* with *args* (a va_list pointer from the callback)."""
    vsnprintf = _init_crt()
    if vsnprintf is None or not fmt:
        return fmt.decode("utf-8", "replace") if fmt else ""
    buf = ctypes.create_string_buffer(4096)
    vsnprintf(buf, ctypes.sizeof(buf), fmt, args)
    return buf.value.decode("utf-8", "replace")


def install_hint() -> str:
    return (
        "Download libpinmame from "
        "https://github.com/vpinball/pinmame/releases.\n"
        "Windows: drop libpinmame-X.Y.dll into "
        "%USERPROFILE%\\pinmame\\ (or anywhere on PATH).\n"
        "macOS:   brew tap missionpinball/homebrew-pinmame && "
        "brew install libpinmame\n"
        "Linux:   build from source — see PinMAME README."
    )
