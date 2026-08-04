#!/usr/bin/env python3
"""padvidhost.py - the HOST half of the video bridge.

    wsl -e bash -c 'python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/padvidhost.py \\
        /home/david/spike2root/dump/padvid'

The emulated game has no software H.264 decoder - of the 175 plugins in its
gstreamer-0.10 the only one that decodes h264 is the i.MX6 hardware element, and
there is no i.MX6 here. This process decodes with ffmpeg on the WSL side and
publishes raw I420 frames into a shared ring the guest reads. Same host/guest
split as the GL bridge and the audio player.

WHY PYTHON AND NOT C, unlike padglhost: ffmpeg does every expensive thing. This
process only copies finished planes into a ring, which is one memoryview slice
assignment per frame - about 47 MB/s at 1360x768x30, nothing for a modern core.
padglhost is C because it has to call EGL/GLES; this has no such constraint, and
the C would only be a slower thing to write and a harder thing to change.

PERFORMANCE, deliberately:
  * ffmpeg writes rawvideo straight to a pipe, so there is no intermediate file
    and no per-frame process start.
  * frames are read with readinto() into a preallocated buffer, then copied once
    into the ring. Two copies total, both memcpy speed.
  * decoding runs AHEAD of the guest by up to PADVID_SLOTS frames and then
    blocks on the ring, so a slow guest throttles the decoder instead of the
    decoder throwing frames away.
  * the loop is DEMAND DRIVEN: no request means it sleeps, so an idle emulator
    pays nothing. This matters because the game rebuilds its video pipeline
    continuously in attract mode.
"""
import mmap
import os
import struct
import subprocess
import sys
import time

MAGIC = 0x56444150
VERSION = 1
SLOTS = 4
MAX_W, MAX_H = 1920, 1088
SLOT_BYTES = MAX_W * MAX_H * 3 // 2
HDR = 4096
TOTAL = HDR + SLOTS * SLOT_BYTES
PATH_MAX = 512

IDLE, OK, ERR = 0, 1, 2

# Field offsets, in the order padvid.h declares them. Kept as names so a
# mismatch with the header is a one-line fix rather than a hunt.
F = {}
for _i, _n in enumerate([
        "magic", "version", "req_gen", "ack_gen", "status",
        "width", "height", "nframes", "fps_num", "fps_den", "frame_bytes",
        "write_idx", "read_idx", "playing", "eos", "host_alive"]):
    F[_n] = _i * 4
PATH_OFF = F["host_alive"] + 4

# The guest sees /games/godzilla_pro; we see the same tree on the WSL side.
GUEST_ROOT = "/games/godzilla_pro"
HOST_ROOT = os.environ.get(
    "PAD_VID_ROOT", "/home/david/spike2root/games/godzilla_pro")


_T0 = time.monotonic()


def log(msg):
    sys.stderr.write("[padvid %7.2f] %s\n" % (time.monotonic() - _T0, msg))
    sys.stderr.flush()


def get(m, name):
    return struct.unpack_from("<I", m, F[name])[0]


def put(m, name, v):
    struct.pack_into("<I", m, F[name], v & 0xFFFFFFFF)


def host_path(p):
    """Map what the game asked for onto a path this process can open.

    The game chdir()s to /games/godzilla_pro and uses relative paths, so almost
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


def probe(path):
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


def serve(m, path, w, h):
    """Decode `path` into the ring until the guest stops asking or ffmpeg ends."""
    frame_bytes = w * h * 3 // 2
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-i", path, "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    # ffmpeg's stderr goes to OUR stderr, i.e. padvid.log. It used to go to
    # DEVNULL, which threw away the one message that could explain a clip
    # ending early - and a clip DID end early, at 240 of 514 frames, and was
    # read as a healthy "EOS clean" for a whole pass.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
    buf = bytearray(frame_bytes)
    view = memoryview(buf)
    produced = 0
    gen = get(m, "req_gen")
    try:
        while True:
            if get(m, "req_gen") != gen:
                log("superseded after %d frames" % produced)
                return
            if not get(m, "playing"):
                log("guest stopped playback after %d frames" % produced)
                return
            # Block while the ring is full. Throttling the DECODER is right:
            # dropping frames here would show as a stutter with no way to tell
            # it from a decode problem.
            while produced - get(m, "read_idx") >= SLOTS:
                if get(m, "req_gen") != gen:
                    log("superseded while throttled after %d frames" % produced)
                    return
                if not get(m, "playing"):
                    log("guest stopped while throttled after %d frames" % produced)
                    return
                time.sleep(0.002)
            got = 0
            while got < frame_bytes:
                n = proc.stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got < frame_bytes:
                put(m, "eos", 1)
                rc = proc.poll()
                log("ffmpeg ended after %d frames (%d trailing bytes, rc=%s)"
                    % (produced, got, rc))
                return
            slot = produced % SLOTS
            off = HDR + slot * SLOT_BYTES
            m[off:off + frame_bytes] = buf
            produced += 1
            put(m, "write_idx", produced)
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:                           # noqa: BLE001
            pass


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/david/spike2root/dump/padvid"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    if os.fstat(fd).st_size < TOTAL:
        os.ftruncate(fd, TOTAL)
    m = mmap.mmap(fd, TOTAL)
    os.close(fd)
    put(m, "magic", MAGIC)
    put(m, "version", VERSION)
    put(m, "ack_gen", get(m, "req_gen"))
    log("ready: %s (%d MB ring, %d slots)" % (path, TOTAL // (1 << 20), SLOTS))

    beat = 0
    while True:
        beat += 1
        put(m, "host_alive", beat)
        req = get(m, "req_gen")
        if req == get(m, "ack_gen"):
            time.sleep(0.01)                 # idle: cost nothing
            continue
        raw = bytes(m[PATH_OFF:PATH_OFF + PATH_MAX])
        want = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        full = host_path(want)
        put(m, "write_idx", 0)
        put(m, "read_idx", 0)
        put(m, "eos", 0)
        if not full:
            log("cannot open %r" % want)
            put(m, "status", ERR)
            put(m, "ack_gen", req)
            continue
        info = probe(full)
        if not info:
            put(m, "status", ERR)
            put(m, "ack_gen", req)
            continue
        w, h, n, num, den = info
        put(m, "width", w)
        put(m, "height", h)
        put(m, "nframes", n)
        put(m, "fps_num", num)
        put(m, "fps_den", den)
        put(m, "frame_bytes", w * h * 3 // 2)
        put(m, "status", OK)
        # Publish the answer BEFORE decoding: the guest is blocked waiting for
        # width/height to build its textures, and making it wait for the first
        # frame as well would add a whole decode start-up to every clip.
        put(m, "ack_gen", req)
        # Log what was actually ASKED FOR. The basename of the parent directory
        # is "2.asset" for every video in the game, so the old form made two
        # different clips look like the same clip served twice.
        log("serving %dx%d %d frames %s" % (w, h, n, want))
        try:
            serve(m, full, w, h)
        except Exception as exc:                    # noqa: BLE001
            log("decode failed: %s" % exc)
            put(m, "eos", 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
