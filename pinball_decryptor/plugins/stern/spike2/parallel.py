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
_ENC_GAINS = None
_ENC_REFS = None


def init_encode_worker(game_real_path, image_path, params, gains=None,
                       edited=(), refs=None):
    global _ENC_EMU, _ENC_BYIDX, _ENC_ENDS, _ENC_GR, _ENC_SR, _ENC_GAINS, _ENC_REFS
    from ..engine import _slot_end_map
    from .emulator import Spike2Emu
    # Per-clip loudness ({idx: total dB}) travels in the initargs rather than
    # per task: it is the same dict for every task this worker runs.
    _ENC_GAINS = dict(gains or {})
    # PAD-494: {idx: ref_idx}, the record a sound's loudness matches instead of its own
    _ENC_REFS = dict(refs or {})
    _ENC_EMU = Spike2Emu(game_real_path, image_path)
    _ENC_EMU.boot()
    # ``params`` is the card's FULL table (not just the edited sounds): the
    # shared-boundary resolution needs each edit's layout-predecessor too.
    _ENC_BYIDX = {p["idx"]: p for p in params}
    _ENC_ENDS = _slot_end_map(params)
    # A grown sound's placeholder body would mislead the codec sub-slot probe,
    # and so would an edited sound's body on a card PAD already built (the
    # last build's replacement, PAD-331), so settle those keys from other card
    # audio first (see Spike2Emu.warm_slots_for_grown).
    _ENC_EMU.warm_slots_for_grown(params, edited=edited)
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
                          _EncodeVerifyError, _level_ref_render)
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
    gdb = (_ENC_GAINS or {}).get(idx)
    orig = _level_ref_render(_ENC_EMU, _ENC_BYIDX, p, (_ENC_REFS or {}).get(idx), np)
    try:
        if p["chan"] == 2:
            off, body = _encode_stereo(_ENC_EMU, _ENC_SR, p, wav_path, np,
                                       pred=pred, gain_db=gdb, orig=orig)
        else:
            off, body = _encode_mono(_ENC_EMU, _ENC_GR, p, wav_path, np,
                                     pred=pred, gain_db=gdb, orig=orig)
    except _EncodeVerifyError:
        return (idx, p["body_off"], None, False)
    return (idx, off, bytes(body), True)


def out_of_memory(exc):
    """Whether *exc* is the computer running out of memory rather than a sound
    that cannot be decoded: a ``MemoryError`` (numpy's "Unable to allocate"),
    Unicorn's ``UC_ERR_NOMEM``, Windows' "paging file is too small" (PAD-830).
    The one is worth another go once memory is free; the other is not."""
    if isinstance(exc, MemoryError):
        return True
    if getattr(exc, "winerror", None) == 1455:
        return True
    t = str(exc)
    return ("UC_ERR_NOMEM" in t or "MemoryError" in t or "Unable to allocate" in t
            or "paging file is too small" in t)


#: :func:`decode_to_wav`'s answer for a sound its worker ran out of memory on
#: (PAD-830): the parent decodes it again once the pool is gone
NO_MEMORY = "no-memory"


def decode_to_wav(task):
    """task = (param_dict, out_wav_path).  Returns (idx, ok): ok is True, False
    (the sound did not decode) or :data:`NO_MEMORY` (PAD-830: the worker ran out
    of memory; that used to raise in the parent and end the whole pool)."""
    p, out_path = task
    idx = p["idx"]
    length = p.get("length", 0)
    chan = p.get("chan", 1)
    # One in-place log line per sound: 'start' creates it, 'prog' animates the
    # long ones, 'done' finalises it.
    _put(("start", idx, length, chan))
    try:
        r = _EMU.decode(p, progress=_make_progress_cb(idx, length, chan))
        if r is None:
            return (idx, False)
        L, R, stereo = r
        chans = [L, R] if stereo else [L]
        n = len(chans[0])
        inter = np.empty(n * len(chans), np.int16)
        for i, c in enumerate(chans):
            inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
        del L, R, chans, r
        w = wave.open(out_path, "wb")
        w.setnchannels(2 if stereo else 1)
        w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(inter.tobytes()); w.close()
    except Exception as e:                              # noqa: BLE001
        return (idx, NO_MEMORY if out_of_memory(e) else False)
    _put(("done", idx, length, chan))
    return (idx, True)


# ---------------------------------------------------------------------------
# Block workers (Write) -- one LONG sound's blocks across processes (PAD-599).
# A sound appended along the firmware's chain is encoded in chain order, one
# after another (its window bytes set the parameters of every record after
# it), so a bank of five 2.5-minute mode songs or a card's 60 appended sounds
# ran on one core: about 100 s a song, 24 minutes for the Godzilla Heisei
# build.  Three quarters of a song's encode is the keystream recovery, two
# emulated decodes of every 200-sample block, and a block's keystream depends
# on the record's codec parameters and its position alone, never on the
# audio.  So each block is recovered AND encoded by whichever worker has it,
# and the parent lays the words in exactly where its own loop would have.
# Each worker's emulator is set up the way the parent's encoder was (the same
# boot, the same warm of the codec slots, record by record), so the bytes are
# the serial encode's own.
# ---------------------------------------------------------------------------

#: a sound with fewer blocks than this is encoded in the parent: the round
#: trip would cost more than it saves
BLOCKS_MIN = 256


def block_workers():
    """How many block workers a chain encode starts: the computer's cores
    less two, at most eight (the cat-0 pool's rule); 0 = none.
    ``PAD_STERN_BLOCK_WORKERS`` overrides it (0 turns them off)."""
    import os
    v = os.environ.get("PAD_STERN_BLOCK_WORKERS", "")
    try:
        if v.strip():
            return max(0, int(v))
    except ValueError:
        pass
    n = min(8, (os.cpu_count() or 1) - 2)
    return n if n >= 2 else 0


def _block_main(conn, kind, gr_path, img_path, stock_rows, first_warm,
                cat_file, first_edited=()):
    """A block worker: boot like the parent's encoder, then take
    ``("warm", row)`` (no reply) and answer ``("encode", p, three, jobs)``
    with ``("ok", [(k, m, words), ...])`` until ``("stop",)``."""
    err = None
    try:
        if kind == "cat":
            from .category import CatEmu
            emu = CatEmu(gr_path, img_path)
            emu.boot()
            emu.set_category_file(cat_file)
        else:
            from .emulator import Spike2Emu
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            if first_warm is not None:
                emu.warm_slots_for_grown(first_warm, edited=first_edited)
        conn.send(("ready", None))
    except Exception as e:                              # noqa: BLE001
        conn.send(("error", "a worker did not start: %r" % (e,)))
        return
    from .codec import GenRecover, StereoRecover
    gr = sr = None
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        op = msg[0]
        if op == "stop":
            break
        if op == "warm":
            if err is not None:
                continue
            try:
                row = msg[1]
                if kind == "cat":
                    emu.mm = emu._mm_img
                    emu.warm_slots_for_grown(stock_rows + [row])
                    emu.mm = emu._mm_cat
                else:
                    emu.warm_slots_for_grown(stock_rows + [row])
            except Exception as e:                      # noqa: BLE001
                err = "a worker's warm failed: %r" % (e,)
            continue
        if op != "encode":
            continue
        if err is not None:
            conn.send(("error", err))
            continue
        try:
            _op, p, three, jobs = msg
            out = []
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
                if three is not None:
                    sr._three_probe[(p["scale"], p["chan"])] = three
                for k, cursor, L, R in jobs:
                    L = np.asarray(L, np.int64)
                    R = np.asarray(R, np.int64)
                    rec = sr.recover_block(p, cursor, nf=len(L))
                    m = rec["m"]
                    frame, _ = sr.encode_block(L[:m], R[:m], rec)
                    out.append((k, m, frame))
            else:
                gr = gr or GenRecover(emu)
                for k, cursor, seg, _r in jobs:
                    seg = np.asarray(seg, np.int64)
                    K, rb = gr.recover_block(p, cursor, n=len(seg))
                    m = len(K)
                    enc, _ = gr.encode_block(seg[:m], K, rb)
                    out.append((k, m, enc))
            conn.send(("ok", out))
        except Exception as e:                          # noqa: BLE001
            conn.send(("error", "a worker's encode failed: %r" % (e,)))
    try:
        emu.close()
    except Exception:                                   # noqa: BLE001
        pass


class BlockPool:
    """Block workers for one chain encode (see above).  *kind* is ``"image"``
    (a :class:`.emulator.Spike2Emu` on *img_path*, warmed first with
    *first_warm*) or ``"cat"`` (a :class:`.category.CatEmu` serving
    *cat_file*).  :meth:`warm` must follow every warm of the parent's
    encoder; :meth:`blocks` is the ``blocks`` callable the codecs'
    ``encode_sound`` take.  Anything that goes wrong turns the pool off
    (``None`` from :meth:`blocks`) and the encode carries on in the parent,
    as it did before there were workers."""

    def __init__(self, kind, gr_path, img_path, stock_rows, workers,
                 first_warm=None, cat_file=None, log=None, first_edited=()):
        import multiprocessing as mp
        self.log = log or (lambda *a, **k: None)
        self.broken = None
        self._ready = False
        self.used = 0
        self.conns, self.procs = [], []
        ctx = mp.get_context("spawn")
        try:
            for _i in range(workers):
                a, b = ctx.Pipe()
                pr = ctx.Process(target=_block_main, daemon=True,
                                 args=(b, kind, gr_path, img_path,
                                       list(stock_rows), first_warm, cat_file,
                                       list(first_edited)))
                pr.start()
                b.close()
                self.conns.append(a)
                self.procs.append(pr)
        except Exception as e:                          # noqa: BLE001
            self._fail("the workers did not start (%s)" % e)

    def _fail(self, why):
        if self.broken is None:
            self.broken = why
            self.log("Long sounds are encoded in one process from here on: "
                     "%s." % why, "warning")
        self.close()

    def _wait_ready(self, timeout=300):
        if self._ready or self.broken:
            return not self.broken
        for c in self.conns:
            try:
                if not c.poll(timeout):
                    self._fail("a worker took over %d s to start" % timeout)
                    return False
                tag, why = c.recv()
            except (EOFError, OSError) as e:
                self._fail("a worker stopped (%s)" % e)
                return False
            if tag != "ready":
                self._fail(why)
                return False
        self._ready = True
        return True

    def warm(self, row):
        """Say the parent's encoder warmed its codec slots for *row*."""
        if self.broken:
            return
        for c in self.conns:
            try:
                c.send(("warm", row))
            except (OSError, ValueError) as e:
                self._fail("a worker stopped (%s)" % e)
                return

    def blocks(self, p, jobs, three=None):
        """``{k: (m, words)}`` for *jobs* ``[(k, cursor, seg, segR or
        None), ...]``, or ``None`` (the caller encodes them itself)."""
        if self.broken or len(jobs) < BLOCKS_MIN or not self._wait_ready():
            return None
        n = len(self.conns)
        per = -(-len(jobs) // n)
        sent = []
        try:
            for i, c in enumerate(self.conns):
                part = jobs[i * per:(i + 1) * per]
                if part:
                    c.send(("encode", p, three, part))
                    sent.append(c)
            out = {}
            for c in sent:
                tag, got = c.recv()
                if tag != "ok":
                    self._fail(got)
                    return None
                for k, m, words in got:
                    out[k] = (m, words)
        except (EOFError, OSError, ValueError) as e:
            self._fail("a worker stopped (%s)" % e)
            return None
        self.used += 1
        return out

    def close(self):
        for c in self.conns:
            try:
                c.send(("stop",))
            except Exception:                           # noqa: BLE001
                pass
        # a worker still booting (a chain that never needed one) is not
        # waited for
        for pr in self.procs:
            pr.join(timeout=2 if self._ready else 0.2)
            if pr.is_alive():
                pr.kill()
                pr.join(timeout=5)
        for c in self.conns:
            try:
                c.close()
            except Exception:                           # noqa: BLE001
                pass
        self.conns, self.procs = [], []


def start_block_pool(kind, gr_path, img_path, stock_rows, first_warm=None,
                     cat_file=None, log=None, longest=None, first_edited=(),
                     workers=None):
    """A :class:`BlockPool` when this computer has the cores for one and the
    chain has a sound long enough to use it (*longest*, its length in
    samples, when the caller knows it), else ``None``.  *first_edited*: the
    idx the first warm treats as edited (the cat-0 encoder's own warm);
    *workers* caps how many start (the cores other workers leave)."""
    n = block_workers()
    if workers is not None:
        n = min(n, workers)
    if n < 2 or (longest is not None and longest < 200 * (BLOCKS_MIN + 1)):
        return None
    n = emulators_that_fit(emulator_commit(img_path, cat_file), n)
    if n < 2:
        return None
    return BlockPool(kind, gr_path, img_path, stock_rows, n,
                     first_warm=first_warm, cat_file=cat_file, log=log,
                     first_edited=first_edited)


# ---------------------------------------------------------------------------
# How many emulators the computer has room for (PAD-609).  A Write that
# fails to commit an emulator's memory fails with the emulator's
# UC_ERR_NOMEM.  The workers of a long build (the cat-0 pool, the block
# workers, the banks') ran to sixty-odd GB of commit together, so each count
# is held to what the commit limit (RAM and page file) has room for.
#
# PAD-777: an emulator used to commit image.bin's whole size (a private
# copy-on-write view) and a 512 MB heap up front, ~2.1 GB on Iron Maiden
# while it touched 43 MB; the card files are read-only views now and the heap
# is mapped as it is used (spike2.window), so the files cost nothing.
# ---------------------------------------------------------------------------

#: what an emulator process commits (PAD-777, Iron Maiden LE 1.18: 0.32 GB booted
#: with its params derived, 2.15 GB at the peak of a whole decode of its 12.7-minute
#: song, most of that the decoded audio; the out-of-memory retry of a bank's
#: encode covers such a peak)
EMU_COMMIT_EXTRA = 1 << 30
#: commit left for the app itself and everything else on the computer
COMMIT_RESERVE = 4 << 30


def emulator_commit(*paths):
    """The bytes one emulator process commits.  The files *paths* it maps
    (image.bin, a bank's file) count nothing: they are read-only views of the
    files (PAD-777), not memory of the emulator's own."""
    return EMU_COMMIT_EXTRA


def commit_room():
    """The bytes Windows can still commit, or None when it does not say.  That
    is the commit limit less what is committed, and three quarters of what the
    page files can still grow by (:func:`_page_file_growth`): a system-managed
    page file shrinks back between builds (80 GB of commit limit on this
    PC between them, 125 GB during one), so the limit alone holds the
    workers back for nothing.

    Linux and macOS commit a page when it is touched, so there it is the
    computer's RAM (PAD-830: six decoders, each holding a long song, on an
    8 GB Mac is a computer swapping to a stop), or None when it does not say."""
    import ctypes
    import os
    if os.name != "nt":
        return _ram()

    class _Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = _Status()
    st.dwLength = ctypes.sizeof(st)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
    except Exception:                                   # noqa: BLE001
        return None
    try:
        grow = _page_file_growth(int(st.ullTotalPhys),
                                 max(0, int(st.ullTotalPageFile) - int(st.ullTotalPhys)),
                                 _page_file_entries())
    except Exception:                                   # noqa: BLE001
        grow = 0
    return int(st.ullAvailPageFile) + grow * 3 // 4


def _ram():
    """The computer's RAM in bytes (Linux, macOS), or None."""
    import os
    try:
        n = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None
    return n if n > 0 else None


def _page_file_entries():
    """The page files Windows is set up with: ``[(drive, max bytes or None
    for system-managed)]`` from the registry (``?:`` is the system drive)."""
    import os
    import winreg
    key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
        val, _t = winreg.QueryValueEx(k, "PagingFiles")
    out = []
    for e in (val if isinstance(val, (list, tuple)) else [val]):
        parts = str(e).split()
        if not parts:
            continue
        drive = parts[0][:2]
        if drive.startswith("?"):
            drive = os.environ.get("SystemDrive", "C:")
        mx = None
        if len(parts) >= 3:
            try:
                lo, hi = int(parts[1]), int(parts[2])
            except ValueError:
                lo = hi = 0
            if lo or hi:
                mx = hi << 20
        out.append((drive, mx))
    return out


def _page_file_growth(ram, current, entries, usage=None):
    """The bytes the page files *entries* (:func:`_page_file_entries`) can
    still grow by, *current* bytes big together on a computer with *ram*: to
    their maximum (a system-managed one's is three times the RAM or 4 GB,
    at most an eighth of its drive), and no further than their drives' free
    space less 2 GB.  *usage* is :func:`shutil.disk_usage` (for tests)."""
    import shutil
    usage = usage or shutil.disk_usage
    most, free = 0, 0
    for drive in sorted({d for d, _m in entries}):
        try:
            du = usage(drive + "\\")
        except OSError:
            continue
        free += du.free
        for d, mx in entries:
            if d == drive:
                most += mx if mx is not None else min(max(3 * ram, 4 << 30), du.total // 8)
    return max(0, min(most - current, free - (2 << 30)))


def emulators_that_fit(per, want):
    """How many of *want* emulator processes, each committing *per* bytes
    (:func:`emulator_commit`), the computer has room for now: at least one
    (the encode needs that one whatever happens)."""
    room = commit_room()
    if room is None:
        return want
    return max(1, min(want, int((room - COMMIT_RESERVE) // max(per, 1))))


# ---------------------------------------------------------------------------
# The Write's final-bytes check (PAD-609): the replaced sounds decoded from the
# finished card, spread over workers each booted and warmed as the serial check's
# emulator is (engine._final_check_one does the work in both).
# ---------------------------------------------------------------------------
_FIN_EMU = None


def init_final_worker(gr_path, img_path, params, edited):
    global _FIN_EMU
    from ..engine import _BodyOverlay
    from .emulator import Spike2Emu
    _FIN_EMU = Spike2Emu(gr_path, img_path)
    _FIN_EMU.boot()
    _FIN_EMU.warm_slots_for_grown(params, edited=edited)
    _FIN_EMU.mm = _BodyOverlay(_FIN_EMU.mm)


def final_check(task):
    """task = ``(off, row, body, scrap_check)``; returns ``(off, result)``."""
    from ..engine import _final_check_one
    off, p, body, scrap = task
    return off, _final_check_one(_FIN_EMU, off, p, body, scrap, np=np)
