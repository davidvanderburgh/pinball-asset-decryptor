"""Multiprocessing worker for parallel Spike 2 audio decode.

Each worker process boots its own emulator once (``init_worker``), then decodes
assigned sounds and writes the WAVs directly — so only small ``(idx, ok)``
tuples cross the process boundary, never the decoded arrays.  The emulator isn't
picklable, so it lives as a per-process global.

The parent uses a ``spawn`` context (the only start method on Windows); the GUI
entry points call ``multiprocessing.freeze_support()`` so spawned children
bootstrap without re-launching the app.  ``engine.extract_all`` falls back to a
single-process loop if a pool can't start, so this is a pure speedup with no
new failure mode.
"""

import wave

import numpy as np

_EMU = None


def probe():
    """Cheap task to confirm a worker booted (init ran) — lets the parent detect
    a stalled pool and fall back, without blocking forever."""
    return _EMU is not None


def init_worker(game_real_path, image_path):
    global _EMU
    from .emulator import Spike2Emu
    _EMU = Spike2Emu(game_real_path, image_path)
    _EMU.boot()
    _EMU.setup_decode()


def decode_to_wav(task):
    """task = (param_dict, out_wav_path).  Returns (idx, ok)."""
    p, out_path = task
    try:
        r = _EMU.decode(p)
    except Exception:
        return (p["idx"], False)
    if r is None:
        return (p["idx"], False)
    L, R, stereo = r
    chans = [L, R] if stereo else [L]
    n = len(chans[0])
    inter = np.empty(n * len(chans), np.int16)
    for i, c in enumerate(chans):
        inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
    w = wave.open(out_path, "wb")
    w.setnchannels(len(chans)); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(inter.tobytes()); w.close()
    return (p["idx"], True)
