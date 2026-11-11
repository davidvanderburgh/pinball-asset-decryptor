#!/usr/bin/env python3
"""s3vidhost.py - decodes the Spike 3 game's video on the host (PAD-1090,
stage 5). The other half of s3vid.c; s3vid.h has the why and the layout.

    s3vidhost.py FEED PADVID [LOG]

Creates both shared files (sparse), then serves: per channel, a new stream
(open) starts one native `ffmpeg` fed Annex B on stdin and read as raw I420 on
stdout; its frames go into the channel's padvid ring slots, each one only once
the game has released the frame that held it before (padvid read_idx).
A flush restarts the decoder and drops the frames the game has not taken; a
close kills it.

The game's packets are length-prefixed NAL units with hvcC/avcC extradata
(MP4 style); ffmpeg's raw demuxers want Annex B, so the parameter sets go in
first and every length prefix becomes a start code.
"""
import mmap
import os
import queue
import struct
import subprocess
import sys
import threading
import time

# ---- s3vid.h ----
S3VID_MAGIC, S3VID_VERSION = 0x44495653, 1
CH, PKTS, DATA, EXTRA, HDR = 8, 256, 8 << 20, 4096, 1 << 20
S3VID_BYTES = HDR + CH * DATA
CHAN_SZ = 32 * 4 + EXTRA + PKTS * 24
(OPEN_GEN, OPEN_ACK, CODEC, WIDTH, HEIGHT, EXTRA_SIZE, FLUSH_GEN, FLUSH_ACK,
 FLUSH_BASE, CLOSED, PKT_W, PKT_R, DATA_W, DATA_R, FRAMES_OUT) = range(15)
PKT_EOF = 0x80000000
# ---- ../spike2_emu/padvid.h ----
PADVID_MAGIC, PADVID_VERSION = 0x56444150, 3
P_SLOTS, P_HDR = 16, 8192               # s3build.sh's -DPADVID_SLOTS
MAX_W, MAX_H = 2048, 1152               # s3build.sh's -DPADVID_MAX_W/H
P_SLOT_BYTES = MAX_W * MAX_H * 3 // 2
P_BYTES = P_HDR + CH * P_SLOTS * P_SLOT_BYTES
P_CHAN_SZ = 13 * 4 + 512
(P_REQ, P_ACK, P_STATUS, P_W, P_H, P_NFR, P_FPSN, P_FPSD, P_FB, P_WRITE, P_READ,
 P_PLAYING, P_EOS) = range(13)
HEVC, H264 = 173, 27


def make(path, size):
    with open(path, "wb") as f:
        f.truncate(size)
    f = open(path, "r+b")
    return mmap.mmap(f.fileno(), size)


class Shm:
    def __init__(self, feed_path, vid_path):
        self.f = make(feed_path, S3VID_BYTES)
        self.v = make(vid_path, P_BYTES)
        struct.pack_into("<II", self.f, 0, S3VID_MAGIC, S3VID_VERSION)
        # the run's session (s3vid.h): a restored guest re-opens on a new one
        struct.pack_into("<I", self.f, 12, (int.from_bytes(os.urandom(4), "little") | 1))
        struct.pack_into("<II", self.v, 0, PADVID_MAGIC, PADVID_VERSION)

    # feed channel fields
    def fget(self, c, i):
        return struct.unpack_from("<I", self.f, 16 + c * CHAN_SZ + i * 4)[0]

    def fset(self, c, i, val):
        struct.pack_into("<I", self.f, 16 + c * CHAN_SZ + i * 4, val & 0xFFFFFFFF)

    def extra(self, c):
        n = min(self.fget(c, EXTRA_SIZE), EXTRA)
        o = 16 + c * CHAN_SZ + 128
        return bytes(self.f[o:o + n])

    def pkt(self, c, k):
        o = 16 + c * CHAN_SZ + 128 + EXTRA + (k % PKTS) * 24
        pos, size, lo, hi, flags, _ = struct.unpack_from("<6I", self.f, o)
        return pos, size, flags

    def data(self, c, pos, size):
        o = HDR + c * DATA + pos % DATA
        return bytes(self.f[o:o + size])

    # padvid channel fields
    def vget(self, c, i):
        return struct.unpack_from("<I", self.v, 12 + c * P_CHAN_SZ + i * 4)[0]

    def vset(self, c, i, val):
        struct.pack_into("<I", self.v, 12 + c * P_CHAN_SZ + i * 4, val & 0xFFFFFFFF)

    def slot(self, c, n):
        return P_HDR + (c * P_SLOTS + n % P_SLOTS) * P_SLOT_BYTES


def param_sets(codec, extra):
    """(Annex B parameter sets, NAL length size; 0 = packets are Annex B)."""
    sc = b"\0\0\0\1"
    if extra[:4] == sc or extra[:3] == b"\0\0\1":
        return extra, 0
    out = b""
    try:
        if codec == HEVC and len(extra) >= 23 and extra[0] == 1:
            nl = (extra[21] & 3) + 1
            i, narr = 23, extra[22]
            for _ in range(narr):
                n = struct.unpack_from(">H", extra, i + 1)[0]
                i += 3
                for _ in range(n):
                    ln = struct.unpack_from(">H", extra, i)[0]
                    out += sc + extra[i + 2:i + 2 + ln]
                    i += 2 + ln
            return out, nl
        if codec == H264 and len(extra) >= 7 and extra[0] == 1:
            nl = (extra[4] & 3) + 1
            i, nsps = 6, extra[5] & 0x1F
            for _ in range(nsps):
                ln = struct.unpack_from(">H", extra, i)[0]
                out += sc + extra[i + 2:i + 2 + ln]
                i += 2 + ln
            npps = extra[i]
            i += 1
            for _ in range(npps):
                ln = struct.unpack_from(">H", extra, i)[0]
                out += sc + extra[i + 2:i + 2 + ln]
                i += 2 + ln
            return out, nl
    except (struct.error, IndexError):
        pass
    return b"", 4


def annexb(pkt, nl):
    """A length-prefixed packet as Annex B. The extradata's framing is
    trusted first: a 4-byte length of 256..511 is `00 00 01 xx`, which looks
    like a start code - testing for start codes first passed every such NAL
    through unconverted and ffmpeg decoded garbage from the second frame on."""
    if nl:
        out, i = bytearray(), 0
        while i + nl <= len(pkt):
            ln = int.from_bytes(pkt[i:i + nl], "big")
            if ln == 0 or i + nl + ln > len(pkt):
                break
            out += b"\0\0\0\1" + pkt[i + nl:i + nl + ln]
            i += nl + ln
        if i == len(pkt):
            return bytes(out)
    return pkt                     # already Annex B (or not length-prefixed after all)


class Decoder:
    """One ffmpeg for one stream of one channel."""

    def __init__(self, shm, c, codec, w, h, extra, log):
        self.shm, self.c, self.w, self.h, self.log = shm, c, w, h, log
        self.fb = w * h + 2 * ((w + 1) // 2) * ((h + 1) // 2)
        self.extra = extra
        self.ps, self.nl = param_sets(codec, extra)
        self.q = queue.Queue(maxsize=48)
        self.stop = False
        fmt = "hevc" if codec == HEVC else "h264"
        self.p = subprocess.Popen(
            # NOT -fflags nobuffer: on a piped raw stream it drops frames -
            # the IDR first among them (71 of a 121-frame clip came out, every
            # one grey for want of its references). The small probe is fine:
            # byte-identical to a plain decode, and the first frame comes out
            # without ffmpeg reading seconds of stream ahead.
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-probesize", "32", "-analyzeduration", "0", "-f", fmt, "-i", "pipe:0",
             "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", "%dx%d" % (w, h), "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0)
        self.first = True
        threading.Thread(target=self.writer, daemon=True).start()
        threading.Thread(target=self.reader, daemon=True).start()

    def put(self, data):
        """False when the queue is full (try again later)."""
        try:
            self.q.put_nowait(data)
            return True
        except queue.Full:
            return False

    def writer(self):
        dump = None
        if os.environ.get("PAD_S3_VID_DUMP"):
            # PAD_S3_VID_DUMP=DIR: what ffmpeg is fed, as a file ffmpeg can
            # read back offline (DIR/ch<c>-<n>.hevc), and the raw extradata
            Decoder.dumps = getattr(Decoder, "dumps", 0) + 1
            base = os.path.join(os.environ["PAD_S3_VID_DUMP"], "ch%d-%d" % (self.c, Decoder.dumps))
            dump = open(base + ".es", "wb")
            open(base + ".extra", "wb").write(self.extra)
        try:
            while not self.stop:
                d = self.q.get()
                if d is None:
                    self.p.stdin.close()
                    return
                if self.first and self.ps:
                    d = self.ps + d
                self.first = False
                if dump:
                    dump.write(d)
                self.p.stdin.write(d)
        except (BrokenPipeError, ValueError, OSError):
            pass

    def reader(self):
        s, c = self.shm, self.c
        try:
            while not self.stop:
                # an unbuffered pipe read returns what is there (a pipe's
                # worth), not a frame: gather a whole frame, or end of stream
                buf = bytearray()
                while len(buf) < self.fb:
                    part = self.p.stdout.read(self.fb - len(buf))
                    if not part:
                        break
                    buf += part
                if len(buf) < self.fb:
                    break
                while not self.stop and s.vget(c, P_WRITE) - s.vget(c, P_READ) >= P_SLOTS:
                    time.sleep(0.002)          # the game still holds that slot
                if self.stop:
                    return
                n = s.vget(c, P_WRITE)
                o = s.slot(c, n)
                s.v[o:o + self.fb] = buf
                s.vset(c, P_WRITE, n + 1)
                s.fset(c, FRAMES_OUT, s.fget(c, FRAMES_OUT) + 1)
        except (ValueError, OSError):
            pass
        if not self.stop:
            s.vset(c, P_EOS, 1)

    def kill(self):
        self.stop = True
        try:
            self.p.kill()
        except OSError:
            pass
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def new_session(path):
    """A save state is being loaded into this run (PAD-1147, s3restore.sh):
    every channel closed (the host ends the old game's decoders) and a new
    session, so the restored game's s3vid.so re-opens each of its streams."""
    with open(path, "r+b") as f:
        m = mmap.mmap(f.fileno(), 0)
        try:
            if struct.unpack_from("<I", m, 0)[0] != S3VID_MAGIC:
                return 1
            for c in range(CH):
                struct.pack_into("<I", m, 16 + c * CHAN_SZ + CLOSED * 4, 1)
            struct.pack_into("<I", m, 12, int.from_bytes(os.urandom(4), "little") | 1)
        finally:
            m.close()
    return 0


def main():
    if sys.argv[1] == "--new-session":
        sys.exit(new_session(sys.argv[2]))
    feed, vid = sys.argv[1], sys.argv[2]
    log = open(sys.argv[3], "a", buffering=1) if len(sys.argv) > 3 else sys.stderr
    s = Shm(feed, vid)
    say = lambda m: log.write("%8.3f %s\n" % (time.time() - t0, m))
    t0 = time.time()
    say("s3vidhost: feed %s, frames %s" % (feed, vid))
    dec = [None] * CH
    seen = [0] * CH
    alive = 0
    while True:
        busy = False
        for c in range(CH):
            if s.fget(c, OPEN_GEN) != s.fget(c, OPEN_ACK):
                if dec[c]:
                    dec[c].kill()
                    dec[c] = None
                codec, w, h = s.fget(c, CODEC), s.fget(c, WIDTH), s.fget(c, HEIGHT)
                s.fset(c, PKT_R, s.fget(c, PKT_W))
                s.fset(c, DATA_R, s.fget(c, DATA_W))
                s.fset(c, FRAMES_OUT, 0)
                s.vset(c, P_WRITE, 0)
                s.vset(c, P_EOS, 0)
                ok = codec in (HEVC, H264) and 0 < w <= MAX_W and 0 < h <= MAX_H
                if ok:
                    s.vset(c, P_W, w)
                    s.vset(c, P_H, h)
                    s.vset(c, P_FB, w * h + 2 * ((w + 1) // 2) * ((h + 1) // 2))
                    dec[c] = Decoder(s, c, codec, w, h, s.extra(c), log)
                    say("ch%d: open %s %dx%d, %d bytes of extradata (NAL length %d)" % (
                        c, "hevc" if codec == HEVC else "h264", w, h, len(s.extra(c)), dec[c].nl))
                else:
                    say("ch%d: open REFUSED codec %d %dx%d (beyond the %dx%d ring slot)" % (
                        c, codec, w, h, MAX_W, MAX_H))
                s.fset(c, FLUSH_ACK, s.fget(c, FLUSH_GEN))
                s.fset(c, OPEN_ACK, s.fget(c, OPEN_GEN))
                busy = True
            if s.fget(c, FLUSH_GEN) != s.fget(c, FLUSH_ACK):
                d = dec[c]
                if d:
                    d.kill()
                    dec[c] = Decoder(s, c, s.fget(c, CODEC), d.w, d.h, s.extra(c), log)
                s.vset(c, P_WRITE, s.fget(c, FLUSH_BASE))
                s.vset(c, P_EOS, 0)
                s.fset(c, FLUSH_ACK, s.fget(c, FLUSH_GEN))
                busy = True
            if s.fget(c, CLOSED) and dec[c]:
                dec[c].kill()
                dec[c] = None
                say("ch%d: closed after %d frames" % (c, s.fget(c, FRAMES_OUT)))
            d = dec[c]
            while d and s.fget(c, PKT_R) != s.fget(c, PKT_W):
                k = s.fget(c, PKT_R)
                pos, size, flags = s.pkt(c, k)
                raw = s.data(c, pos, size) if not flags & PKT_EOF else b""
                if os.environ.get("PAD_S3_VID_DUMP"):
                    with open(os.path.join(os.environ["PAD_S3_VID_DUMP"], "ch%d.raw" % c), "ab") as rf:
                        rf.write(struct.pack("<IIII", k, pos, size, flags) + raw)
                item = None if flags & PKT_EOF else annexb(raw, d.nl)
                if not d.put(item):
                    break
                s.fset(c, PKT_R, k + 1)
                if size:
                    s.fset(c, DATA_R, pos + size)
                busy = True
            fo = s.fget(c, FRAMES_OUT)
            if d and fo and fo // 900 != seen[c] // 900:
                say("ch%d: %d frames decoded" % (c, fo))
            seen[c] = fo
        alive += 1
        struct.pack_into("<I", s.f, 8, alive)
        struct.pack_into("<I", s.v, 8, alive)
        if not busy:
            time.sleep(0.002)


if __name__ == "__main__":
    main()
