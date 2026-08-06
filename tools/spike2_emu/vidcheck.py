#!/usr/bin/env python3
"""vidcheck.py - grade the video bridge's HOST half without running the game.

    wsl -e bash -lc 'python3 .../vidcheck.py <guest-relative-clip> [frame]'

WHY THIS EXISTS. Item 6 is "the TV inset draws pink/green horizontal noise",
and the inset only appears in a real game, which needs a human on the
keyboard. That is not an instrument. But the fault, whatever it is, is
somewhere in a chain that is entirely reproducible without the game:

    the .asset file -> ffmpeg -> padvidhost.py -> the shared ring
                    -> padglhost's i420_to_rgba -> RGBA pixels

This script drives exactly that chain for one named clip and one named frame,
using the REAL padvidhost.py and the REAL converter (i420check.c #includes the
same i420.h padglhost.c does), and then compares the answer against two
references rather than scoring it on its own:

  * `exact`  - a plain BT.601 limited-range, nearest-chroma reference written
               here in Python. This is what i420_to_rgba SAYS it does, so a
               disagreement is a bug in the converter's arithmetic.
  * `ffmpeg` - swscale's own rgba decode of the same frame. ffmpeg interpolates
               chroma where we duplicate it, so a few LSB of difference on
               edges is expected and correct; a large one is not.

AND A SIGNATURE METRIC, because "the numbers look small" is not what David
reported. `magenta/green` counts pixels that are strongly magenta or strongly
green - the exact look of chroma bytes being read out of luma data. It is
calibrated in the same run: --mismatch renders the same frame at a size it is
NOT, which is the defect on purpose, and the metric has to separate the two by
a mile before any of its readings mean anything.

Leaves the rig as it found it: refuses to start if a padvidhost is already
running (that would be David's), and kills its own on the way out.
"""
import mmap
import os
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

MAGIC = 0x56444150
VERSION = 2
CHANNELS, SLOTS = 4, 4
MAX_W, MAX_H = 1920, 1088
SLOT_BYTES = MAX_W * MAX_H * 3 // 2
HDR = 4096
TOTAL = HDR + CHANNELS * SLOTS * SLOT_BYTES
PATH_MAX = 512
CH_FIELDS = ["req_gen", "ack_gen", "status",
             "width", "height", "nframes", "fps_num", "fps_den", "frame_bytes",
             "write_idx", "read_idx", "playing", "eos"]
CH_BYTES = len(CH_FIELDS) * 4 + PATH_MAX
CH_BASE = 12
OK = 1

GAME = os.environ.get("PAD_GAME") or "godzilla_pro"
HOST_ROOT = os.environ.get("PAD_VID_ROOT", "/home/david/spike2root/games/" + GAME)


def get(m, c, name):
    return struct.unpack_from("<I", m, CH_BASE + c * CH_BYTES + CH_FIELDS.index(name) * 4)[0]


def put(m, c, name, v):
    struct.pack_into("<I", m, CH_BASE + c * CH_BYTES + CH_FIELDS.index(name) * 4,
                     v & 0xFFFFFFFF)


def put_path(m, c, s):
    off = CH_BASE + c * CH_BYTES + len(CH_FIELDS) * 4
    raw = s.encode("utf-8")[:PATH_MAX - 1] + b"\0"
    m[off:off + len(raw)] = raw


def build_checker():
    exe = os.path.join(tempfile.gettempdir(), "i420check")
    src = os.path.join(HERE, "i420check.c")
    if not os.path.exists(exe) or os.path.getmtime(exe) < max(
            os.path.getmtime(src), os.path.getmtime(os.path.join(HERE, "i420.h"))):
        subprocess.run(["gcc", "-O2", "-Wall", "-I", HERE, "-o", exe, src], check=True)
    return exe


def already_running():
    r = subprocess.run(["pgrep", "-fa", "padvidhost.py"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode().strip()


def pull_frame(clip, want_frame):
    """Return (w, h, i420 bytes) for `want_frame`, straight out of the ring."""
    blk = os.path.join(tempfile.gettempdir(), "vidcheck_shm")
    if os.path.exists(blk):
        os.unlink(blk)
    fd = os.open(blk, os.O_RDWR | os.O_CREAT, 0o666)
    os.ftruncate(fd, TOTAL)
    m = mmap.mmap(fd, TOTAL)
    os.close(fd)

    env = dict(os.environ)
    env["PAD_GAME"] = GAME
    env["PAD_VID_ROOT"] = HOST_ROOT
    host = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "padvidhost.py"), blk],
        stderr=subprocess.PIPE, env=env)
    try:
        for _ in range(500):
            if struct.unpack_from("<I", m, 0)[0] == MAGIC:
                break
            time.sleep(0.01)
        else:
            raise SystemExit("padvidhost never claimed the block")

        c = 0
        put(m, c, "playing", 1)          # serve() bails out if this is 0
        put_path(m, c, clip)
        gen = get(m, c, "req_gen") + 1
        put(m, c, "req_gen", gen)
        for _ in range(1000):
            if get(m, c, "ack_gen") == gen:
                break
            time.sleep(0.01)
        else:
            raise SystemExit("the host never answered the request")
        if get(m, c, "status") != OK:
            raise SystemExit("the host refused %r" % clip)
        w, h = get(m, c, "width"), get(m, c, "height")
        fb = get(m, c, "frame_bytes")

        # Walk the ring forward to the frame we want, releasing slots as we go
        # so the decoder is never blocked behind us.
        ring0 = HDR + c * SLOTS * SLOT_BYTES
        consumed = 0
        data = None
        deadline = time.monotonic() + 60
        while consumed <= want_frame:
            if get(m, c, "write_idx") <= consumed:
                if get(m, c, "eos"):
                    raise SystemExit("clip ended at frame %d, wanted %d"
                                     % (consumed, want_frame))
                if time.monotonic() > deadline:
                    raise SystemExit("timed out waiting for frame %d" % want_frame)
                time.sleep(0.002)
                continue
            if consumed == want_frame:
                off = ring0 + (consumed % SLOTS) * SLOT_BYTES
                data = bytes(m[off:off + fb])
            consumed += 1
            put(m, c, "read_idx", consumed)
        put(m, c, "playing", 0)
        return w, h, data
    finally:
        host.kill()
        host.wait(timeout=5)
        m.close()
        try:
            os.unlink(blk)
        except OSError:
            pass


def ref_exact(src, w, h):
    """BT.601 limited range, nearest chroma - what i420_to_rgba claims to be."""
    ys = w * h
    cs = (w // 2) * (h // 2)
    Y, U, V = src[:ys], src[ys:ys + cs], src[ys + cs:ys + 2 * cs]
    out = bytearray(w * h * 4)
    yc = [max(0, min(255, (298 * (i - 16) + 128) >> 8)) for i in range(256)]
    yraw = [(298 * (i - 16) + 128) >> 8 for i in range(256)]
    del yc
    o = 0
    for y in range(h):
        yrow = y * w
        crow = (y // 2) * (w // 2)
        for x in range(w):
            u = U[crow + (x // 2)] - 128
            v = V[crow + (x // 2)] - 128
            c = yraw[Y[yrow + x]]
            r = c + ((409 * v + 128) >> 8)
            g = c - ((100 * u + 208 * v + 128) >> 8)
            b = c + ((516 * u + 128) >> 8)
            out[o] = 0 if r < 0 else (255 if r > 255 else r)
            out[o + 1] = 0 if g < 0 else (255 if g > 255 else g)
            out[o + 2] = 0 if b < 0 else (255 if b > 255 else b)
            out[o + 3] = 255
            o += 4
    return bytes(out)


def ref_ffmpeg(path, frame, w, h):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", "select=eq(n\\,%d)" % frame, "-vsync", "0", "-frames:v", "1",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout[:w * h * 4]


def diff(a, b):
    """(mean abs error, max abs error, % of pixels off by more than 8)."""
    if len(a) != len(b) or not a:
        return None
    tot = 0
    mx = 0
    bad = 0
    n = len(a) // 4
    for i in range(0, len(a), 4):
        d = max(abs(a[i] - b[i]), abs(a[i + 1] - b[i + 1]), abs(a[i + 2] - b[i + 2]))
        tot += d
        if d > mx:
            mx = d
        if d > 8:
            bad += 1
    return tot / n, mx, 100.0 * bad / n


def chroma_signature(rgba):
    """% strongly magenta + % strongly green.

    Chroma bytes read out of LUMA data is what the defect looks like: bright
    luma rows land as magenta, dark ones as green. Both at once, in quantity,
    is a signature no real footage produces.
    """
    mag = grn = 0
    n = len(rgba) // 4
    for i in range(0, len(rgba), 4):
        r, g, b = rgba[i], rgba[i + 1], rgba[i + 2]
        if r > g + 60 and b > g + 60:
            mag += 1
        elif g > r + 60 and g > b + 60:
            grn += 1
    return 100.0 * mag / n, 100.0 * grn / n


def ppm(path, rgba, w, h):
    with open(path, "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (w, h))
        row = bytearray(w * 3)
        for y in range(h):
            src = y * w * 4
            for x in range(w):
                row[x * 3:x * 3 + 3] = rgba[src + x * 4:src + x * 4 + 3]
            f.write(row)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        raise SystemExit(__doc__.strip().splitlines()[0])
    clip = args[0]
    frame = int(args[1]) if len(args) > 1 else 0
    outdir = os.environ.get("PAD_VIDCHECK_OUT", tempfile.gettempdir())

    busy = already_running()
    if busy:
        raise SystemExit("padvidhost is already running - not touching it:\n" + busy)

    exe = build_checker()
    w, h, src = pull_frame(clip, frame)
    print("clip %s frame %d: ring says %dx%d, %d bytes" % (clip, frame, w, h, len(src)))

    raw = os.path.join(outdir, "vidcheck.i420")
    with open(raw, "wb") as f:
        f.write(src)

    def render(cw, ch, tag):
        out = os.path.join(outdir, "vidcheck_%s.rgba" % tag)
        subprocess.run([exe, raw, str(cw), str(ch), out], check=True)
        with open(out, "rb") as f:
            px = f.read()
        ppm(os.path.join(outdir, "vidcheck_%s.ppm" % tag), px, cw, ch)
        return px

    got = render(w, h, "true")

    print("\n-- the converter, against two references")
    d = diff(got, ref_exact(src, w, h))
    print("   vs exact BT.601 reference : mean %.3f  max %d  >8: %.3f%%" % d)
    fr = ref_ffmpeg(os.path.join(HOST_ROOT, clip[2:] if clip.startswith("./") else clip),
                    frame, w, h)
    d2 = diff(got, fr)
    if d2:
        print("   vs ffmpeg swscale rgba    : mean %.3f  max %d  >8: %.3f%%" % d2)
    else:
        print("   vs ffmpeg swscale rgba    : could not decode that frame")

    print("\n-- the signature metric, calibrated on this very frame")
    m, g = chroma_signature(got)
    print("   correct size %4dx%-4d : magenta %6.2f%%  green %6.2f%%" % (w, h, m, g))
    if "--mismatch" in " ".join(flags) or True:
        for cw, ch in ((1360, 768), (w * 2, h), (w // 2, h)):
            if cw < 2 or ch < 2:
                continue
            px = render(cw, ch, "as%dx%d" % (cw, ch))
            m2, g2 = chroma_signature(px)
            print("   read as      %4dx%-4d : magenta %6.2f%%  green %6.2f%%"
                  % (cw, ch, m2, g2))
    print("\nppm images in %s" % outdir)


if __name__ == "__main__":
    main()
