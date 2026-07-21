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

Live progress: workers push throttled ``("prog"/"done", ...)`` events onto an
optional shared queue (``init_worker``'s ``prog_q``) that the parent drains on a
thread and forwards to the log.  Only sounds still decoding after a couple of
seconds report — so the hundreds of short callouts stay silent and only the long
music tracks (the ones that look "stuck") surface live progress.
"""

import time
import wave

import numpy as np

_EMU = None
_PROG_Q = None

# A sound reports progress only once it's been decoding this long (skips the
# short sounds entirely), then at most this often (keeps the log readable).
_PROG_AFTER_S = 2.5
_PROG_EVERY_S = 3.0


def probe():
    """Cheap task to confirm a worker booted (init ran) — lets the parent detect
    a stalled pool and fall back, without blocking forever."""
    return _EMU is not None


def init_worker(game_real_path, image_path, prog_q=None):
    global _EMU, _PROG_Q
    _PROG_Q = prog_q
    from .emulator import Spike2Emu
    _EMU = Spike2Emu(game_real_path, image_path)
    _EMU.boot()
    _EMU.setup_decode()


def _put(event):
    q = _PROG_Q
    if q is not None:
        try:
            q.put(event)
        except Exception:
            pass


def _make_progress_cb(idx, length, chan):
    """Throttled per-block callback that emits ``prog`` events while a long sound
    decodes (short sounds finish before the threshold, so they never tick), or
    ``None`` when there's no queue."""
    if _PROG_Q is None:
        return None
    t0 = time.monotonic()
    state = {"last": 0.0}

    def cb(cur, nmax):
        now = time.monotonic()
        if now - t0 < _PROG_AFTER_S or now - state["last"] < _PROG_EVERY_S:
            return
        state["last"] = now
        _put(("prog", idx, cur / max(nmax, 1), length, chan))

    return cb


# ---------------------------------------------------------------------------
# Encode workers (Write) — re-encode edited cat-0 sounds back into body bytes.
# Mirrors the decode workers: each process boots one emulator (init_encode_worker)
# and re-encodes its share, returning only small (idx, body_off, body) tuples.
# The per-sound work calls the SAME engine primitives the serial path does, so a
# parallel Write is bit-identical to a serial one (each sound's encode is
# independent of order — the emu's body overlay resets to passthrough between
# sounds).
# ---------------------------------------------------------------------------
_ENC_EMU = None
_ENC_BYIDX = None
_ENC_ENDS = None
_ENC_GR = None
_ENC_SR = None


def init_encode_worker(game_real_path, image_path, params):
    global _ENC_EMU, _ENC_BYIDX, _ENC_ENDS, _ENC_GR, _ENC_SR
    from ..engine import _slot_end_map
    from .emulator import Spike2Emu
    _ENC_EMU = Spike2Emu(game_real_path, image_path)
    _ENC_EMU.boot()
    # ``params`` is the card's FULL table (not just the edited sounds): the
    # shared-boundary resolution needs each edit's layout-predecessor too.
    _ENC_BYIDX = {p["idx"]: p for p in params}
    _ENC_ENDS = _slot_end_map(params)
    _ENC_GR = _ENC_SR = None


def encode_probe():
    """Confirm an encode worker booted (cf. :func:`probe`)."""
    return _ENC_EMU is not None


def encode_one(task):
    """task = idx (int).  Returns ``(idx, write_off, body_bytes_or_None, valid)``
    — ``write_off`` is encode_sound's window start (one word below body_off on
    delta=-1 keys); ``valid`` False (body None) means the sound's codec variant
    can't re-encode bit-exact and must be left unchanged — exactly the serial
    path's skip."""
    global _ENC_GR, _ENC_SR
    import numpy as np

    from ..engine import (_encode_mono, _encode_stereo, _recovery_valid,
                          _EncodeVerifyError)
    from .codec import GenRecover, StereoRecover
    idx, wav_path = task
    p = _ENC_BYIDX.get(idx)
    if p is None:
        return (idx, None, None, False)
    if p["chan"] == 2:
        _ENC_SR = _ENC_SR or StereoRecover(_ENC_EMU)
    else:
        _ENC_GR = _ENC_GR or GenRecover(_ENC_EMU)
    if not _recovery_valid(_ENC_EMU, _ENC_GR, _ENC_SR, p, np):
        return (idx, p["body_off"], None, False)
    pred = _ENC_ENDS.get(p["body_off"]) if _ENC_ENDS else None
    # A body that doesn't decode back to the request is the same class of
    # failure as a codec we can't re-encode: skip it, never write it blind.
    try:
        if p["chan"] == 2:
            off, body = _encode_stereo(_ENC_EMU, _ENC_SR, p, wav_path, np,
                                       pred=pred)
        else:
            off, body = _encode_mono(_ENC_EMU, _ENC_GR, p, wav_path, np,
                                     pred=pred)
    except _EncodeVerifyError:
        return (idx, p["body_off"], None, False)
    return (idx, off, bytes(body), True)


def decode_to_wav(task):
    """task = (param_dict, out_wav_path).  Returns (idx, ok)."""
    p, out_path = task
    idx = p["idx"]
    length = p.get("length", 0)
    chan = p.get("chan", 1)
    # One in-place log line per sound: 'start' creates it, 'prog' animates the
    # long ones, 'done' finalises it.
    _put(("start", idx, length, chan))
    try:
        r = _EMU.decode(p, progress=_make_progress_cb(idx, length, chan))
    except Exception:
        return (idx, False)
    if r is None:
        return (idx, False)
    L, R, stereo = r
    chans = [L, R] if stereo else [L]
    n = len(chans[0])
    inter = np.empty(n * len(chans), np.int16)
    for i, c in enumerate(chans):
        inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
    w = wave.open(out_path, "wb")
    w.setnchannels(len(chans)); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(inter.tobytes()); w.close()
    _put(("done", idx, length, chan))
    return (idx, True)
