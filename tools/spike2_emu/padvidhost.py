#!/usr/bin/env python3
"""padvidhost.py - the HOST half of the video bridge.

    wsl -e bash -c 'python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/padvidhost.py \\
        /home/david/spike2root/dump/padvid'

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
import struct
import subprocess
import sys
import threading
import time

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
    "PAD_VID_ROOT", "/home/david/spike2root/games/" + _GAME)


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
    full = os.path.normpath(os.path.join(HOST_ROOT, p))
    if not full.startswith(os.path.normpath(HOST_ROOT) + os.sep):
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


def _probe_uncached(path):
    """(width, height, nframes, fps_num, fps_den) or None."""
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


def serve(m, c, path, w, h, native):
    """Decode `path` into channel c's ring until the guest stops asking or
    ffmpeg ends. `native` is the file's own size; `w`,`h` is what was published
    to the guest, and they differ only when a test flag is rescaling."""
    frame_bytes = w * h * 3 // 2
    ring0 = HDR + c * SLOTS * SLOT_BYTES
    # Rescale whenever the size we published is not the file's own, which is
    # true for BOTH test flags. Asking _forced_size() alone would have served
    # native frames under a rescaled header the moment a second flag existed.
    scale = ["-vf", "scale=%d:%d" % (w, h)] if (w, h) != native else []
    cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
            "-f", "rawvideo"] + scale + ["-pix_fmt", "yuv420p", "-"])
    # ffmpeg's stderr goes to OUR stderr, i.e. padvid.log. It used to go to
    # DEVNULL, which threw away the one message that could explain a clip
    # ending early - and a clip DID end early, at 240 of 514 frames, and was
    # read as a healthy "EOS clean" for a whole pass.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
    buf = bytearray(frame_bytes)
    view = memoryview(buf)
    produced = 0
    gen = get(m, c, "req_gen")
    try:
        while True:
            if get(m, c, "req_gen") != gen:
                log("ch%d superseded after %d frames" % (c, produced))
                return
            if not get(m, c, "playing"):
                log("ch%d guest stopped playback after %d frames" % (c, produced))
                return
            # Block while the ring is full. Throttling the DECODER is right:
            # dropping frames here would show as a stutter with no way to tell
            # it from a decode problem.
            while produced - get(m, c, "read_idx") >= SLOTS:
                if get(m, c, "req_gen") != gen:
                    log("ch%d superseded while throttled after %d frames" % (c, produced))
                    return
                if not get(m, c, "playing"):
                    log("ch%d guest stopped while throttled after %d frames" % (c, produced))
                    return
                time.sleep(0.002)
            got = 0
            while got < frame_bytes:
                n = proc.stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got < frame_bytes:
                put(m, c, "eos", 1)
                rc = proc.poll()
                log("ch%d ffmpeg ended after %d frames (%d trailing bytes, rc=%s)"
                    % (c, produced, got, rc))
                return
            slot = produced % SLOTS
            off = ring0 + slot * SLOT_BYTES
            m[off:off + frame_bytes] = buf
            produced += 1
            put(m, c, "write_idx", produced)
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
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


def chan_loop(m, c):
    """One channel, forever. Nothing here touches any other channel."""
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
        hot_until = time.monotonic() + 0.25
        want = get_path(m, c)
        full = host_path(want)
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
        log("ch%d serving %dx%d %d frames %s%s"
            % (c, w, h, n, want,
               "  (RESCALED from %dx%d)" % native if (w, h) != native else ""))
        note_serve(c, want)
        try:
            serve(m, c, full, w, h, native)
        except Exception as exc:                    # noqa: BLE001
            log("ch%d decode failed: %s" % (c, exc))
            put(m, c, "eos", 1)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/david/spike2root/dump/padvid"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    if os.fstat(fd).st_size < TOTAL:
        os.ftruncate(fd, TOTAL)
    m = mmap.mmap(fd, TOTAL)
    os.close(fd)
    struct.pack_into("<I", m, G["magic"], MAGIC)
    struct.pack_into("<I", m, G["version"], VERSION)
    for c in range(CHANNELS):
        put(m, c, "ack_gen", get(m, c, "req_gen"))
        t = threading.Thread(target=chan_loop, args=(m, c), daemon=True)
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
