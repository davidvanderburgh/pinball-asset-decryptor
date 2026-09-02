#!/usr/bin/env python3
"""padvidhost.py - the HOST half of the video bridge.

    wsl -e bash -c 'python3 <rig>/padvidhost.py \\
        $PAD_ROOT/dump/padvid'

The emulated game has no software H.264 decoder - of the 175 plugins in its
gstreamer-0.10 the only one that decodes h264 is the i.MX6 hardware element, and
there is no i.MX6 here. This process decodes with ffmpeg on the WSL side and
publishes raw I420 frames into a shared ring the guest reads. Same host/guest
split as the GL bridge and the audio player.

CHANNELS (padvid.h v3, EIGHT of them). One stream was enough until the attract
playlist crossfaded: the game keeps TWO pipelines alive across a transition, and
two prepares racing on one request slot is how "[vid] host did not answer" and a
run full of Radium retry errors happened. Each channel is served by its own
thread with its own ffmpeg; they share nothing but the mmap.

Four channels was then enough for attract and NOT enough for a game: the Planet
X Controller taunt builds three pipelines in 130 ms, which on four slots meant
each one stealing the channel of the one before (item 6).

WHY PYTHON AND NOT C, unlike padglhost: ffmpeg does every expensive thing. This
process only copies finished planes into a ring, which is one memoryview slice
assignment per frame - about 47 MB/s at 1360x768x30, nothing for a modern core.
The GIL does not matter here either: readinto() releases it, and the ring copy
holds it for microseconds.

PERFORMANCE, deliberately:
  * ffmpeg writes rawvideo straight to a pipe, so there is no intermediate file
    and no per-frame process start.
  * frames are read with readinto() into a preallocated buffer, then copied once
    into the ring. Two copies total, both memcpy speed.
  * decoding runs AHEAD of the guest by up to SLOTS frames and then blocks on
    the ring, so a slow guest throttles the decoder instead of the decoder
    throwing frames away.
  * each channel loop is DEMAND DRIVEN: no request means it sleeps, so an idle
    emulator pays nothing. This matters because the game rebuilds its video
    pipelines continuously in attract mode.
"""
import mmap
import os
import select
import struct
import subprocess
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

MAGIC = 0x56444150
VERSION = 3
CHANNELS = 8
SLOTS = 4
MAX_W, MAX_H = 1920, 1088
SLOT_BYTES = MAX_W * MAX_H * 3 // 2
HDR = 8192
TOTAL = HDR + CHANNELS * SLOTS * SLOT_BYTES
PATH_MAX = 512

IDLE, OK, ERR = 0, 1, 2

# Layout, in the order padvid.h declares it: three globals, then CHANNELS
# copies of the per-channel struct. Kept as names so a mismatch with the
# header is a one-line fix rather than a hunt.
G = {"magic": 0, "version": 4, "host_alive": 8}
CH_FIELDS = ["req_gen", "ack_gen", "status",
             "width", "height", "nframes", "fps_num", "fps_den", "frame_bytes",
             "write_idx", "read_idx", "playing", "eos"]
CH_BYTES = len(CH_FIELDS) * 4 + PATH_MAX          # 564
CH_BASE = 12

# The guest sees /games/<title>; we see the same tree on the WSL side.
#
# THE TITLE MUST COME FROM THE ENVIRONMENT, not from a constant, and getting
# that wrong is silent rather than loud: this ran a whole TMNT boot serving
# GODZILLA video. The guest chdir()s into its own directory and asks for
# "./assets/lcd/auto_loaded/<hash>/...", so a relative path resolved against
# the wrong title's tree does not fail - the hash directories exist in both
# and the clip plays. It looked like a working emulator showing the wrong film.
_GAME = os.environ.get("PAD_GAME") or "godzilla_pro"
GUEST_ROOT = "/games/" + _GAME
HOST_ROOT = os.environ.get(
    "PAD_VID_ROOT", os.path.join(padpath.root(), "games", _GAME))

# ITEM 90: THE BOOT SELECTOR CAN CHANGE WHICH PARTITION THE GAME RUNS FROM
# AFTER THIS PROCESS HAS STARTED. PAD_VID_ROOT is exported by watch.sh from
# the PRIMARY games partition before the menu is even up; when the choice is
# a different partition, run_game.sh binds that partition's title directory
# over /games/<title> inside the guest's namespace - invisible from here -
# and publishes the host path of the chosen directory in dump/vidroot. Read
# per clip (one stat), never cached: the file appears after the choice and is
# removed by every plain run, so a stale override cannot outlive its run.
# Without this the emulator ran the chosen image's game and images while
# playing the PRIMARY image's videos - measured 2026-09-01, run 2 of item 90.
_VIDROOT_FILE = os.path.join(padpath.root(), "dump", "vidroot")
_vidroot_said = [None]


def host_root():
    """The directory the game's relative clip paths resolve against."""
    try:
        with open(_VIDROOT_FILE) as f:
            r = f.read().strip()
    except OSError:
        r = ""
    if r and os.path.isdir(r):
        if _vidroot_said[0] != r:
            _vidroot_said[0] = r
            log("clip root overridden by dump/vidroot: %s" % r)
        return r
    return HOST_ROOT


_T0 = time.monotonic()
_LOGLOCK = threading.Lock()


def log(msg):
    with _LOGLOCK:
        sys.stderr.write("[padvid %7.2f] %s\n" % (time.monotonic() - _T0, msg))
        sys.stderr.flush()


def get(m, c, name):
    return struct.unpack_from("<I", m, CH_BASE + c * CH_BYTES + CH_FIELDS.index(name) * 4)[0]


def put(m, c, name, v):
    struct.pack_into("<I", m, CH_BASE + c * CH_BYTES + CH_FIELDS.index(name) * 4,
                     v & 0xFFFFFFFF)


def get_path(m, c):
    off = CH_BASE + c * CH_BYTES + len(CH_FIELDS) * 4
    raw = bytes(m[off:off + PATH_MAX])
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def host_path(p):
    """Map what the game asked for onto a path this process can open.

    The game chdir()s to /games/<title> and uses relative paths, so almost
    everything arrives as './assets/...'. Absolute guest paths are translated
    too. Anything that escapes the tree is refused rather than opened - this
    process runs outside the chroot, so a path from inside it is untrusted
    input, not a filename.
    """
    p = (p or "").strip()
    if not p:
        return None
    if p.startswith("./"):
        p = p[2:]
    elif p.startswith(GUEST_ROOT + "/"):
        p = p[len(GUEST_ROOT) + 1:]
    elif p.startswith("/"):
        return None
    root = host_root()
    full = os.path.normpath(os.path.join(root, p))
    if not full.startswith(os.path.normpath(root) + os.sep):
        log("refusing path outside the game tree: %r" % p)
        return None
    return full if os.path.isfile(full) else None


# The probe cache, and it is a LATENCY fix rather than a throughput one.
#
# chan_loop publishes ack_gen only AFTER probe() returns, and the guest blocks
# the GAME'S OWN UI THREAD in pad_vid_prepare() until that ack lands
# (gstvid.c: `while (c->ack_gen != gen && spins++ < 3000) usleep(1000)`). So
# every ffprobe spawn is time the game is not running. Measured on this machine,
# idle: 23.4 ms for a 149 KB clip, 27.5 ms at 16 MB, 38.6 ms at 60 MB.
#
# That would be tolerable if a serve were rare. It is not: in the 2026-08-06
# recording the game re-requested THE SAME PATH on one channel 17 times a
# second for seconds at a time, and 116 of that run's 140 serves were superseded
# after exactly ONE frame. The guest's own eglshim counter fell from 60.0 fps to
# 17.7 in those windows.
#
# A video file's geometry cannot change unless the file does, so (size, mtime)
# is a sound key and not merely a fast one. os.stat() costs ~1 us against
# ffprobe's ~25 ms.
_PROBE_CACHE = {}
_PROBE_LOCK = threading.Lock()
_PROBE_HITS = [0]


def probe(path):
    """(width, height, nframes, fps_num, fps_den) or None, cached per file."""
    key = None
    try:
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
        with _PROBE_LOCK:
            hit = _PROBE_CACHE.get(key)
        if hit is not None:
            _PROBE_HITS[0] += 1
            return hit
    except OSError:
        pass                       # fall through and let ffprobe report it
    info = _probe_uncached(path)
    if key is not None and info is not None:
        with _PROBE_LOCK:
            _PROBE_CACHE[key] = info
    return info


# ---- the native MP4 header parse, and why it exists (item 11) --------------
#
# The probe CACHE above only helps a REPEAT serve. A first-sight probe still
# spawned ffprobe - 23-39 ms, synchronous, before the ack the game's UI thread
# is spinning on - and a clip TRANSITION is by definition first-sight, so
# every transition paid it. Run 3 (2026-08-06) measured it end to end: 97
# pre-armed transitions adopted with waits of min 29 / median 60 / max 86 ms,
# and the decomposition is ffprobe (25-40) plus supersede/kill overhead. The
# geometry the guest needs is five integers sitting in the moov box; reading
# them directly costs microseconds and no process spawn.
#
# ffprobe stays as the fallback for anything this parser declines, and the
# parser declines LOUDLY (one log line per file) so a format drift shows up
# as a slow serve rather than a wrong answer. Validated against ffprobe over
# the full godzilla_pro scene.assets corpus before first use - same five
# numbers or the parser refuses.

def _mp4_boxes(buf, start, end):
    """Yield (type, body_start, body_end) for boxes in buf[start:end]."""
    off = start
    while off + 8 <= end:
        size = int.from_bytes(buf[off:off + 4], "big")
        typ = buf[off + 4:off + 8]
        body = off + 8
        if size == 1:
            if off + 16 > end:
                return
            size = int.from_bytes(buf[off + 8:off + 16], "big")
            body = off + 16
        elif size == 0:
            size = end - off
        if size < 8 or off + size > end:
            return
        yield typ, body, off + size
        off += size


def _mp4_child(buf, start, end, want):
    for typ, b, e in _mp4_boxes(buf, start, end):
        if typ == want:
            return b, e
    return None


def _parse_mp4(path):
    """(width, height, nframes, fps_num, fps_den) or None, from the moov box.

    Only the shapes Stern actually ships are accepted: one video trak with an
    avc1/hvc1-family sample entry, an mdhd timescale, and an stts table. Any
    surprise returns None and the caller falls back to ffprobe."""
    try:
        with open(path, "rb") as f:
            # Walk top-level boxes reading only headers, so a 60 MB mdat costs
            # one seek. moov is usually tens of KB; read it whole.
            moov = None
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                size = int.from_bytes(hdr[:4], "big")
                typ = hdr[4:8]
                skip = size - 8
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = int.from_bytes(ext, "big")
                    skip = size - 16
                elif size == 0:
                    if typ == b"moov":
                        moov = f.read()
                    break
                if skip < 0:
                    break
                if typ == b"moov":
                    moov = f.read(skip)
                    break
                f.seek(skip, 1)
        if not moov:
            return None
        n = len(moov)
        for typ, tb, te in _mp4_boxes(moov, 0, n):
            if typ != b"trak":
                continue
            mdia = _mp4_child(moov, tb, te, b"mdia")
            if not mdia:
                continue
            hdlr = _mp4_child(moov, mdia[0], mdia[1], b"hdlr")
            if not hdlr or moov[hdlr[0] + 8:hdlr[0] + 12] != b"vide":
                continue
            mdhd = _mp4_child(moov, mdia[0], mdia[1], b"mdhd")
            minf = _mp4_child(moov, mdia[0], mdia[1], b"minf")
            if not mdhd or not minf:
                return None
            ver = moov[mdhd[0]]
            timescale = int.from_bytes(
                moov[mdhd[0] + (20 if ver == 1 else 12):
                     mdhd[0] + (24 if ver == 1 else 16)], "big")
            stbl = _mp4_child(moov, minf[0], minf[1], b"stbl")
            if not stbl:
                return None
            stsd = _mp4_child(moov, stbl[0], stbl[1], b"stsd")
            stts = _mp4_child(moov, stbl[0], stbl[1], b"stts")
            if not stsd or not stts:
                return None
            # stsd: version/flags(4) entry_count(4), then the sample entry:
            # size(4) format(4) reserved(6) data_ref_index(2) pre_defined(16)
            # width(2) height(2) ...
            se = stsd[0] + 8
            if se + 36 > stsd[1]:
                return None
            w = int.from_bytes(moov[se + 32:se + 34], "big")
            h = int.from_bytes(moov[se + 34:se + 36], "big")
            # stts: version/flags(4) entry_count(4), then (count, delta) pairs.
            cnt = int.from_bytes(moov[stts[0] + 4:stts[0] + 8], "big")
            if stts[0] + 8 + cnt * 8 > stts[1]:
                return None
            nframes = 0
            deltas = {}
            for i in range(cnt):
                p = stts[0] + 8 + i * 8
                sc = int.from_bytes(moov[p:p + 4], "big")
                sd = int.from_bytes(moov[p + 4:p + 8], "big")
                nframes += sc
                deltas[sd] = deltas.get(sd, 0) + sc
            if not nframes or not timescale or not deltas:
                return None
            # The rate the guest paces on is the DOMINANT sample delta; a
            # last-sample runt (common in encoders) must not change it.
            delta = max(deltas, key=deltas.get)
            if not delta:
                return None
            if not w or not h or w > MAX_W or h > MAX_H:
                return None
            return w, h, nframes, timescale, delta
        return None
    except OSError:
        return None


def _probe_uncached(path):
    """(width, height, nframes, fps_num, fps_den) or None."""
    if os.environ.get("PAD_VID_NO_MP4PARSE", "") != "1":
        info = _parse_mp4(path)
        if info is not None:
            return info
        log("mp4 parse declined %s; falling back to ffprobe" % path)
    try:
        out = subprocess.run(
            ["ffprobe", "-hide_banner", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
             "-of", "default=noprint_wrappers=1:nokey=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    except Exception as exc:                        # noqa: BLE001
        log("ffprobe failed on %s: %s" % (path, exc))
        return None
    vals = {}
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    try:
        w = int(vals.get("width", 0))
        h = int(vals.get("height", 0))
    except ValueError:
        return None
    if not w or not h or w > MAX_W or h > MAX_H:
        log("unusable size %sx%s for %s" % (vals.get("width"), vals.get("height"), path))
        return None
    num, den = 30, 1
    rate = vals.get("r_frame_rate", "30/1")
    if "/" in rate:
        try:
            num, den = (int(x) for x in rate.split("/", 1))
            if den == 0:
                num, den = 30, 1
        except ValueError:
            pass
    try:
        n = int(vals.get("nb_frames", "0"))
    except ValueError:
        n = 0
    return w, h, n, num, den


# PAD_VID_FORCE_SIZE=<w>x<h> rescales EVERY clip to that size and reports that
# size to the guest, so the whole chain runs at a resolution of our choosing.
#
# THIS EXISTS TO MAKE ITEM 6 TESTABLE. The pink/green TV inset is the only
# 520x294 stream in the game and it appears only in one in-game scene reached by
# a ramp shot, which fired once in about ten scripted attempts - an intermittent
# reproduction is not an instrument. Forcing the ATTRACT background to 520x294
# turns "is it the size?" into a question attract mode can answer in a minute,
# every time. If the background survives 520x294 then the size is innocent (as
# the converter and the geometry census already say) and the fault belongs to
# that scene's element; if it breaks, the reproduction stops needing a game.
def _forced_size():
    s = os.environ.get("PAD_VID_FORCE_SIZE", "")
    if "x" not in s:
        return None
    try:
        w, h = (int(v) for v in s.split("x", 1))
    except ValueError:
        return None
    # Odd dimensions have no valid I420 chroma plane; refuse rather than
    # produce a frame size nothing downstream agrees on.
    return (w, h) if w > 1 and h > 1 and not (w % 2 or h % 2) else None


# PAD_VID_ALT_SIZE=<w>x<h> serves every OTHER request at that size instead of
# the clip's own, per channel.
#
# THIS IS ITEM 6'S REPRODUCTION, AND IT EXISTS BECAUSE THE REAL ONE CANNOT BE
# DRIVEN. The pink/green inset needs TWO SIZES LIVE AT ONCE - it is the only
# 520x294 stream in the game and it plays over a 1360x768 background - and the
# only way anyone has ever reached that state is the Planet X Controller taunt,
# which fired once in about twenty-five scripted attempts across five runs.
# PAD_VID_FORCE_SIZE could not help: it rescales EVERY clip, so the chain still
# only ever sees one size, which is exactly why it kept reporting healthy.
#
# Attract mode serves clips continuously and crossfades them, so alternating the
# size per request puts a channel through "1360x768, then 520x294, then
# 1360x768" within seconds, with a second channel live across the fade. That is
# the condition, without a game, without a ramp shot, every run.
def _alt_size():
    s = os.environ.get("PAD_VID_ALT_SIZE", "")
    if "x" not in s:
        return None
    try:
        w, h = (int(v) for v in s.split("x", 1))
    except ValueError:
        return None
    return (w, h) if w > 1 and h > 1 and not (w % 2 or h % 2) else None


_ALT_N = [0] * CHANNELS


# ---- the first-frames cache (item 11) --------------------------------------
#
# The LAST cost of a clip change is ffmpeg's ~35 ms cold start to first
# frame, and it is paid at every transition AND every loop wrap - the game
# loops a clip by re-asking for the same file, so the wrap seam IS this cold
# start (census-priced 35-71 ms). The probe is already free (the MP4 parse)
# and the ack is ~2 ms (the select-gated read), so by run 7 the first frame
# was the whole remaining seam.
#
# So: keep the first HEAD_N decoded frames of every file served, and on a
# re-serve write them into the ring INSTANTLY while a fresh ffmpeg spools up
# and discards the frames the cache already covered. HEAD_N=6 buys 200 ms of
# runway at 30 fps against ~60 ms of spool-and-discard, so the ring never
# starves behind the cache; a clip that fits entirely in the head never
# spawns ffmpeg at all. Frames are cached at the size they were SERVED at
# (the rescale test flags key separately), on the same (path, size, mtime)
# soundness argument as the probe cache.
#
# LRU, budgeted in BYTES: PAD_VID_HEADCACHE_MB, default 192, 0 disables.
# A 1360x768 head is ~9.4 MB, so the default holds ~20 hot files - the
# loops and recurring scene clips that pay the wrap seam every few seconds.
HEAD_N = 6
_HEAD_CACHE = {}          # key -> [frames(list of bytes), complete, last_hit]
_HEAD_BYTES = [0]
_HEAD_LOCK = threading.Lock()


def _head_budget():
    try:
        mb = int(os.environ.get("PAD_VID_HEADCACHE_MB", "192"))
    except ValueError:
        mb = 192
    return mb * (1 << 20)


def _head_get(key):
    """(frames, complete) or None. `complete` means the list IS the clip."""
    if key is None:
        return None
    with _HEAD_LOCK:
        e = _HEAD_CACHE.get(key)
        if e is None:
            return None
        e[2] = time.monotonic()
        return e[0], e[1]


def _head_put(key, frames, complete):
    if key is None or not frames:
        return
    total = sum(len(f) for f in frames)
    budget = _head_budget()
    if not budget or total > budget:
        return
    with _HEAD_LOCK:
        if key in _HEAD_CACHE:
            return
        while _HEAD_BYTES[0] + total > budget and _HEAD_CACHE:
            victim = min(_HEAD_CACHE, key=lambda k: _HEAD_CACHE[k][2])
            _HEAD_BYTES[0] -= sum(len(f) for f in _HEAD_CACHE[victim][0])
            del _HEAD_CACHE[victim]
        _HEAD_CACHE[key] = [frames, complete, time.monotonic()]
        _HEAD_BYTES[0] += total


def serve(m, c, path, w, h, native, gen, old_read):
    """Decode `path` into channel c's ring until the guest stops asking or
    ffmpeg ends. `native` is the file's own size; `w`,`h` is what was published
    to the guest, and they differ only when a test flag is rescaling.

    `gen` is the request generation chan_loop noticed AND ACKED - it must
    never be re-read here. This function used to read req_gen fresh at its
    own start, a few ms after the ack (a Popen and a 1.5 MB alloc sit in
    between), and at every clip end the game lands a SECOND request exactly
    in that window - the EOS reflex re-arms the state path and then the
    rewind, about a millisecond apart. The serve then adopted the NEW
    generation number while serving the OLD request: its supersede check
    went blind, the pending request was never noticed and never acked, and
    the game's UI thread - which drives every pipeline - sat out its full
    3000-spin prepare timeout. That is the `host did not answer` / ~3.3 s
    frozen-video, silent-then-catching-up-log stall of David's 2026-08-06
    evening session: 3 loud sightings, ~8 gaps of 3.3-3.9 s in one run,
    each ending only when the game's NEXT location change re-bumped
    req_gen and finally superseded the blind serve.

    `old_read` is the guest's read_idx as it stood when the request was
    noticed, BEFORE chan_loop reset it - see the display guard below."""
    frame_bytes = w * h * 3 // 2
    ring0 = HDR + c * SLOTS * SLOT_BYTES
    # Rescale whenever the size we published is not the file's own, which is
    # true for BOTH test flags. Asking _forced_size() alone would have served
    # native frames under a rescaled header the moment a second flag existed.
    scale = ["-vf", "scale=%d:%d" % (w, h)] if (w, h) != native else []
    cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
            "-f", "rawvideo"] + scale + ["-pix_fmt", "yuv420p", "-"])
    try:
        st = os.stat(path)
        hkey = (path, st.st_size, st.st_mtime_ns, w, h)
    except OSError:
        hkey = None
    head = _head_get(hkey)
    # Collect the head on a MISS; None on a hit so the fill code stays dark.
    collect = [] if (hkey is not None and head is None) else None
    eof_total = None          # set at EOF: how many frames the file really had
    # ffmpeg's stderr goes to OUR stderr, i.e. padvid.log. It used to go to
    # DEVNULL, which threw away the one message that could explain a clip
    # ending early - and a clip DID end early, at 240 of 514 frames, and was
    # read as a healthy "EOS clean" for a whole pass.
    # NOT SPAWNED when the cache holds the whole clip - the only serve shape
    # with no ffmpeg in it at all.
    proc = None
    if not (head and head[1]):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
    buf = bytearray(frame_bytes)
    view = memoryview(buf)
    produced = 0

    # ---- THE DISPLAY GUARD (item 11, the tearing half). ----------------
    # padglhost uploads video textures straight out of this ring at its own
    # ~60 Hz pace - that is the zero-copy design - and the game re-uploads
    # its CURRENT frame's pointer every render tick until a new frame is
    # handed over. So the previous request's last-consumed slot is still
    # being read off screen long after read_idx said the host may reuse it.
    # Overwriting it is the mid-play jump-back, and when the write races an
    # upload it is literal tearing. The head cache made this SEVERE: phase A
    # slams 4 slots in microseconds where ffmpeg's ~35 ms cold start used to
    # accidentally shield the on-screen frame (David, 2026-08-06 evening,
    # the L-ramp sighting). The guard: the one slot the game was showing is
    # not written until the guest has consumed a frame of THIS request -
    # its element has moved off the old picture - or a bounded wait expires
    # (matching today's behaviour rather than wedging on a game that never
    # plays). Frame 0 in the guard slot writes immediately: nothing can be
    # consumed before frame 0 exists, so waiting there would deadlock.
    guard = (old_read - 1) % SLOTS if old_read else None
    guard_t0 = time.monotonic()

    def must_wait(p):
        """Ring throttle + display guard, one predicate for both phases.

        SLOTS-1, not SLOTS: the guest frees a slot the moment its handoff
        returns, but padglhost only READS the pixels at its next render
        tick, up to ~16 ms later. At full depth the very next write is
        allowed to land in the slot of the frame the game was JUST handed -
        the steady-state intermittent tear. One slot of distance keeps the
        write head a full frame period behind the display."""
        r = get(m, c, "read_idx")
        if r > p:      # stale: the doomed previous thread published one last
            r = 0      # read_idx after chan_loop zeroed it. Without this
                       # clamp the throttle goes negative and the serve slams
                       # the whole ring unthrottled over a live picture.
        if p - r >= SLOTS - 1:
            return True
        if (guard is not None and p and r == 0 and p % SLOTS == guard
                and time.monotonic() - guard_t0 < 0.4):
            return True
        return False
    # ---- THE CONSUME-GAP CENSUS (item 11). David, watching the fixed build
    # live: only the VIDEO content hitches, the rest of the window stays
    # smooth - so the residual fault is gaps in frame DELIVERY, and this is
    # the cheap side of the boundary to measure them from. Two numbers:
    #   * serve start -> the guest consuming its first frame, which prices the
    #     cold start (spawn + container parse + first decode + guest wake) that
    #     every clip-fragment CUT pays - the game chains sub-second fragments
    #     during events, so this gap peppers exactly the moments David reports;
    #   * a mid-clip consume stall: the ring full, the guest not draining for
    #     longer than several frame periods. That is the guest's delivery
    #     thread or the game's handoff blocked, which no host number could
    #     otherwise see. Budgeted per serve so a wedged guest cannot flood.
    t_serve = time.monotonic()
    first_consumed = False
    stall_budget = 5

    def gone(where):
        """One check for both exits; already logged when it answers True."""
        tag = where + " " if where else ""
        if get(m, c, "req_gen") != gen:
            log("ch%d superseded %safter %d frames" % (c, tag, produced))
            return True
        if not get(m, c, "playing"):
            log("ch%d guest stopped %safter %d frames" % (c, tag, produced))
            return True
        return False

    def read_frame():
        """Fill buf with one frame. Returns frame_bytes, a short count at
        EOF, or -1 when the request is gone (already logged).

        NEVER BLOCK DEAF IN THE READ. The old bare readinto() sat ~35 ms
        inside ffmpeg's cold start checking nothing, and a request landing
        in that window waited the whole read out - which is every clip
        REPLACEMENT, because the game's EOS reflex rewinds the outgoing
        clip first and the new location arrives during the rewind's cold
        start. Run 6 (2026-08-06) measured it from both ends: guest adopt
        waits med 34 ms wall while this process acked 0.1 ms after
        NOTICING. The 2 ms select keeps supersede latency flat through the
        cold start; once frames flow the pipe is always ready and the
        select costs microseconds. Run 7: med 34 -> 2 ms.
        """
        got = 0
        while got < frame_bytes:
            r = select.select([proc.stdout], [], [], 0.002)[0]
            if not r:
                if gone("mid-read"):
                    return -1
                continue
            n = proc.stdout.readinto(view[got:])
            if not n:
                break
            got += n
        return got

    try:
        # ---- PHASE A: the cached head goes into the ring INSTANTLY. ------
        if head:
            hframes, hcomplete = head
            log("ch%d head cache: %d frames instant%s"
                % (c, len(hframes), " (whole clip, no ffmpeg)" if hcomplete else ""))
            for fb in hframes:
                while must_wait(produced):
                    if gone("while throttled (head)"):
                        return
                    time.sleep(0.002)
                if gone("(head)"):
                    return
                slot = produced % SLOTS
                off = ring0 + slot * SLOT_BYTES
                m[off:off + frame_bytes] = fb
                produced += 1
                put(m, c, "write_idx", produced)
            if hcomplete:
                put(m, c, "eos", 1)
                log("ch%d whole clip (%d frames) served from head cache"
                    % (c, produced))
                return
            # ---- PHASE B: discard what the cache already covered. The
            # guest has 200 ms of cached runway; the spool-and-discard is
            # ~60 ms, so the ring never runs dry behind it. ----------------
            skip = produced
            while skip:
                got = read_frame()
                if got < 0:
                    return
                if got < frame_bytes:
                    # The file ended inside the region the head covered -
                    # it shrank since it was cached, or ffmpeg failed. The
                    # ring already holds the cached frames; end here.
                    put(m, c, "eos", 1)
                    log("ch%d ffmpeg ended during head discard (rc=%s)"
                        % (c, proc.poll()))
                    return
                skip -= 1

        # ---- PHASE C: live decode, exactly as before. --------------------
        while True:
            if gone(""):
                return
            # Block while the ring is full. Throttling the DECODER is right:
            # dropping frames here would show as a stutter with no way to tell
            # it from a decode problem.
            t_stall = time.monotonic()
            while must_wait(produced):
                if gone("while throttled"):
                    return
                time.sleep(0.002)
            if not first_consumed and get(m, c, "read_idx") > 0:
                first_consumed = True
                log("ch%d first frame consumed %.0f ms after serve start"
                    % (c, (time.monotonic() - t_serve) * 1000.0))
            else:
                # The ring holds SLOTS frames, so a healthy guest drains one
                # per frame period and a full ring clears in ~33 ms. Waiting
                # several periods means the guest stopped consuming mid-clip.
                waited = time.monotonic() - t_stall
                if waited > 0.150 and stall_budget > 0:
                    stall_budget -= 1
                    log("ch%d guest consume STALLED %.0f ms at frame %d"
                        % (c, waited * 1000.0, produced))
            got = read_frame()
            if got < 0:
                return
            if got < frame_bytes:
                put(m, c, "eos", 1)
                eof_total = produced
                log("ch%d ffmpeg ended after %d frames (%d trailing bytes, rc=%s)"
                    % (c, produced, got, proc.poll()))
                return
            if collect is not None and len(collect) < HEAD_N:
                collect.append(bytes(buf))
            slot = produced % SLOTS
            off = ring0 + slot * SLOT_BYTES
            m[off:off + frame_bytes] = buf
            produced += 1
            put(m, c, "write_idx", produced)
    finally:
        # Fill the cache on the way out, whatever the exit. A clean EOF
        # knows whether the head IS the whole clip; a superseded serve only
        # contributes a FULL head (a partial one buys less runway than the
        # spool it would have to hide).
        if collect is not None:
            if eof_total is not None:
                _head_put(hkey, collect, len(collect) == eof_total)
            elif len(collect) == HEAD_N:
                _head_put(hkey, collect, False)
        # Kill, but REAP ASYNCHRONOUSLY. This finally runs on every serve
        # exit including supersede and guest-stop, and chan_loop cannot see
        # the NEXT request (often already pending - a transition stands the
        # old clip down and asks for the new one in the same breath) until
        # it runs. A synchronous wait() cost ~30 ms per re-arm (run 5). A
        # daemon thread reaps the corpse so nothing zombies, nobody waits.
        if proc is not None:
            try:
                proc.kill()
                threading.Thread(target=proc.wait, daemon=True).start()
            except Exception:                       # noqa: BLE001
                pass


#: How long a RESUMED serve waits on a guest that is not draining the ring
#: before it stands the channel down. See the stall check in resume_serve.
#: Long enough that an ordinary hitch (a busy guest, a slow frame) is not
#: mistaken for a dead stream thread; short enough that a wedged channel is
#: measured in seconds rather than the rest of the session.
RESUME_STALL_S = 3.0


def resume_serve(m, c):
    """Continue the serve a save-state restore interrupted. (item 13)

    After loadgame.sh the restored guest believes channel c is mid-clip: its
    stream thread holds `consumed` on its own stack and waits for write_idx
    to pass it. A freshly started host would normally treat the channel as
    settled (startup acks every pending gen and chan_loop sleeps), so nobody
    ever produces the next frame - and the guest's takeover check then sees
    nothing wrong, so no EOS is posted and the game never rebuilds the
    pipeline. On screen that is a background held black/frozen forever while
    the game's own GL text keeps drawing: exactly what David reported after
    the first windowed load.

    The ring header restorestate.sh put back carries everything the
    interrupted serve knew - path, geometry, gen, and write_idx = the next
    frame due - so: decode the clip, discard the frames already produced,
    and carry on from there. Indexes are CONTINUED, never reset, which is
    what keeps the restored guest's slot arithmetic (consumed % SLOTS)
    landing on the frames it expects. At clip end the normal EOS machinery
    runs and the game's own loop/rebuild takes over from there.

    Runs INSIDE chan_loop as its first act, never as a second thread: one
    writer per channel is the file's serialization rule, and the moment the
    guest asks for anything new, gone() ends this and chan_loop serves it.

    The save/dump gap is a known, tolerated race: savestate stashes the ring
    moments BEFORE criu freezes the guest, so the stashed indexes can trail
    the checkpoint by a few frames. The ring math self-heals (the guest
    waits for write_idx to pass its own consumed; re-produced frames land in
    the slots it will read), at worst re-decoding a handful of frames. Only
    a request landing exactly in that gap is lost, and the game's own retry
    covers it.
    """
    gen = get(m, c, "req_gen")
    if (not get(m, c, "playing") or get(m, c, "status") != OK
            or get(m, c, "ack_gen") != gen or get(m, c, "eos")):
        return
    want = get_path(m, c)
    full = host_path(want)
    w, h = get(m, c, "width"), get(m, c, "height")
    n = get(m, c, "nframes")
    produced = get(m, c, "write_idx")
    if not full or not w or not h or produced >= n:
        if want:
            log("ch%d resume: nothing to continue (%r frame %d/%d)"
                % (c, want, produced, n))
        return
    frame_bytes = w * h * 3 // 2
    ring0 = HDR + c * SLOTS * SLOT_BYTES
    info = probe(full)
    native = (info[0], info[1]) if info else (w, h)
    scale = ["-vf", "scale=%d:%d" % (w, h)] if (w, h) != native else []
    cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", full,
            "-f", "rawvideo"] + scale + ["-pix_fmt", "yuv420p", "-"])
    log("ch%d RESUME mid-clip at frame %d of %d: %s" % (c, produced, n, want))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
    buf = bytearray(frame_bytes)
    view = memoryview(buf)

    def gone(where):
        if get(m, c, "req_gen") != gen:
            log("ch%d resume superseded %s at frame %d" % (c, where, produced))
            return True
        if not get(m, c, "playing"):
            log("ch%d resume: guest stopped %s at frame %d" % (c, where, produced))
            return True
        return False

    def read_frame():
        got = 0
        while got < frame_bytes:
            r = select.select([proc.stdout], [], [], 0.002)[0]
            if not r:
                if gone("mid-read"):
                    return -1
                continue
            nr = proc.stdout.readinto(view[got:])
            if not nr:
                break
            got += nr
        return got

    try:
        # Discard what the interrupted serve already produced. NO head-cache
        # collection anywhere in this function: these are mid-clip frames and
        # caching them as the clip's "head" would poison the next real serve.
        skip = produced
        t0 = time.monotonic()
        while skip:
            got = read_frame()
            if got < 0:
                return
            if got < frame_bytes:
                # The file ended before the guest's position - tell the game
                # so it rebuilds, rather than leaving it waiting forever.
                put(m, c, "eos", 1)
                log("ch%d resume: file ended during skip (rc=%s)" % (c, proc.poll()))
                return
            skip -= 1
        log("ch%d resume: skipped to frame %d in %.0f ms"
            % (c, produced, (time.monotonic() - t0) * 1000.0))
        # A RESUMED CHANNEL THE GUEST NEVER DRAINS MUST BE GIVEN UP, NOT HELD.
        # Measured 2026-08-09: after a load the guest's own stream thread does
        # not always come back, so read_idx stops moving; this loop then sat on
        # a full ring forever with playing=1, and the channel was wedged for
        # the rest of the session - the window kept drawing, video stayed at
        # 0.0 NEW/s, and nothing could ever take the channel because it still
        # looked busy. Standing down frees it: the next location change gets a
        # normal fresh serve, which is the path that works. Bounded wait, not a
        # retry loop, because a guest that has not read a frame in seconds is
        # not about to.
        stall_since = None
        last_read = get(m, c, "read_idx")
        while True:
            if gone(""):
                return
            while produced - min(get(m, c, "read_idx"), produced) >= SLOTS - 1:
                if gone("while throttled"):
                    return
                now_read = get(m, c, "read_idx")
                if now_read != last_read:
                    last_read, stall_since = now_read, None
                elif stall_since is None:
                    stall_since = time.monotonic()
                elif time.monotonic() - stall_since > RESUME_STALL_S:
                    log("ch%d resume: the guest has not consumed for %.0f s "
                        "(read_idx %d, wrote %d) - standing the channel down "
                        "so a fresh request can have it"
                        % (c, RESUME_STALL_S, now_read, produced))
                    put(m, c, "playing", 0)
                    return
                time.sleep(0.002)
            got = read_frame()
            if got < 0:
                return
            if got < frame_bytes:
                put(m, c, "eos", 1)
                log("ch%d resume: EOS after %d frames" % (c, produced))
                return
            slot = produced % SLOTS
            off = ring0 + slot * SLOT_BYTES
            m[off:off + frame_bytes] = buf
            produced += 1
            put(m, c, "write_idx", produced)
    finally:
        try:
            proc.kill()
            threading.Thread(target=proc.wait, daemon=True).start()
        except Exception:                           # noqa: BLE001
            pass


_STORM = [None] * CHANNELS      # per channel: [path, count, first_t, last_t]

# A channel asked for the SAME file this many times inside STORM_WINDOW is not
# doing anything a playlist explains, and it is worth one loud line.
STORM_N = 8
STORM_WINDOW = 2.0


def note_serve(c, want):
    """Say so, once, when a channel is being re-served one file in a runaway.

    Every individual `serving` line is still printed - vidroute.py counts them
    and collapsing them would silently change what it reports. This is an EXTRA
    line that names the pattern, because 17 identical lines a second read as
    noise and the thing they describe is the fault.
    """
    now = time.monotonic() - _T0
    st = _STORM[c]
    if st is None or st[0] != want or now - st[3] > STORM_WINDOW:
        if st is not None and st[1] >= STORM_N:
            log("ch%d STORM ENDED: %d serves of one file in %.2f s (%.1f/s)"
                % (c, st[1], st[3] - st[2], st[1] / max(1e-3, st[3] - st[2])))
        _STORM[c] = [want, 1, now, now]
        return
    st[1] += 1
    st[3] = now
    if st[1] == STORM_N:
        log("ch%d STORM: %d serves of %s in %.2f s. Each one blocks the game's "
            "UI thread in pad_vid_prepare until this process acks."
            % (c, st[1], want, now - st[2]))


def chan_loop(m, c, resume=False):
    """One channel, forever. Nothing here touches any other channel."""
    if resume:
        resume_serve(m, c)
    hot_until = 0.0
    while True:
        req = get(m, c, "req_gen")
        if req == get(m, c, "ack_gen"):
            # ADAPTIVE POLL, and the 10 ms it replaces was on the GAME'S
            # CRITICAL PATH. The guest blocks its UI thread in
            # pad_vid_prepare() from the moment it bumps req_gen until this
            # loop publishes ack_gen, so a flat 10 ms sleep spent an average of
            # 5 ms per serve doing nothing before the work even started. With
            # the probe now cached that latency was the whole remaining cost.
            #
            # Only a channel that has been asked for something recently polls
            # fast, so an idle emulator still pays nothing - which is the
            # property the docstring above promises and the reason this is a
            # window rather than a smaller constant. A storm is exactly when
            # the window is open.
            time.sleep(0.001 if time.monotonic() < hot_until else 0.01)
            continue
        # The moment the request was NOTICED, for the noticed->ack stamp on
        # the serving line. The guest's adopt telemetry times its whole spin
        # (write -> ack seen); this half names how much of that was THIS
        # process working, so the difference is poll latency plus the
        # guest's own spin-loop error - the two suspects run 5 left standing.
        t_notice = time.monotonic()
        hot_until = time.monotonic() + 0.25
        want = get_path(m, c)
        full = host_path(want)
        # BEFORE the reset: the last frame the previous request's guest
        # consumed. Its slot is what the game is still showing on screen,
        # and serve()'s display guard keeps the new decode off it.
        old_read = get(m, c, "read_idx")
        put(m, c, "write_idx", 0)
        put(m, c, "read_idx", 0)
        put(m, c, "eos", 0)
        if not full:
            log("ch%d cannot open %r" % (c, want))
            put(m, c, "status", ERR)
            put(m, c, "ack_gen", req)
            continue
        info = probe(full)
        if not info:
            put(m, c, "status", ERR)
            put(m, c, "ack_gen", req)
            continue
        w, h, n, num, den = info
        native = (w, h)
        forced = _forced_size()
        alt = _alt_size()
        if forced:
            w, h = forced
        elif alt:
            _ALT_N[c] += 1
            if _ALT_N[c] % 2 == 0:
                w, h = alt
        put(m, c, "width", w)
        put(m, c, "height", h)
        put(m, c, "nframes", n)
        put(m, c, "fps_num", num)
        put(m, c, "fps_den", den)
        put(m, c, "frame_bytes", w * h * 3 // 2)
        put(m, c, "status", OK)
        # Publish the answer BEFORE decoding: the guest is blocked waiting for
        # width/height to build its textures, and making it wait for the first
        # frame as well would add a whole decode start-up to every clip.
        put(m, c, "ack_gen", req)
        # Log what was actually ASKED FOR. The basename of the parent directory
        # is "2.asset" for every video in the game, so the old form made two
        # different clips look like the same clip served twice.
        log("ch%d serving %dx%d %d frames (acked %.1f ms after notice) %s%s"
            % (c, w, h, n, (time.monotonic() - t_notice) * 1000.0, want,
               "  (RESCALED from %dx%d)" % native if (w, h) != native else ""))
        note_serve(c, want)
        try:
            serve(m, c, full, w, h, native, req, old_read)
        except Exception as exc:                    # noqa: BLE001
            log("ch%d decode failed: %s" % (c, exc))
            put(m, c, "eos", 1)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(padpath.dump(), "padvid")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    if os.fstat(fd).st_size < TOTAL:
        os.ftruncate(fd, TOTAL)
    m = mmap.mmap(fd, TOTAL)
    os.close(fd)
    struct.pack_into("<I", m, G["magic"], MAGIC)
    struct.pack_into("<I", m, G["version"], VERSION)
    # PAD_VID_RESUME=1 (restorestate.sh, item 13): the ring was rewound to a
    # save and a restored guest is coming back mid-clip. Channels the guest
    # thinks are playing get their serve CONTINUED (resume_serve), and a
    # request that was in flight at the save is deliberately NOT pre-acked -
    # chan_loop notices req != ack and serves it fresh, which is the recovery
    # the restored guest's prepare-spin is waiting for. A normal start (fresh
    # ring file, watch.sh deleted the old one) is unchanged.
    resume = os.environ.get("PAD_VID_RESUME") == "1"
    for c in range(CHANNELS):
        if not resume:
            put(m, c, "ack_gen", get(m, c, "req_gen"))
        t = threading.Thread(target=chan_loop, args=(m, c, resume), daemon=True)
        t.start()
    log("ready: %s (%d MB, %d channels x %d slots)"
        % (path, TOTAL // (1 << 20), CHANNELS, SLOTS))

    beat = 0
    while True:
        beat += 1
        struct.pack_into("<I", m, G["host_alive"], beat & 0xFFFFFFFF)
        time.sleep(0.01)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
