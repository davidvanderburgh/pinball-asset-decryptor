#!/usr/bin/env python3
"""padlink.py - a run's lights, coils and switches for a Windows host, pushed
from INSIDE WSL (PAD-1306).

PAD.Controller (vpx/padcontroller.py) used to re-open and read padled and
padsw over \\\\wsl.localhost every 8 ms: two 9p round trips a tick, ~14 KB
each, a fresh open each time (a held handle reads a frozen cache over 9p) and
no mmap from Windows. This runs beside the game instead, maps both blocks,
compares them here every couple of milliseconds and writes only what changed
down its stdout, which the controller reads through the wsl.exe that started
it. Its stdin takes the switch lines swkeys.py takes, through the same holder,
so one helper replaces the swkeys pipe as well.

THE LINES IT WRITES (one line = one coherent look at the blocks):

    HELLO padlink 1 led=<bytes> sw=<bytes>   the link is up; nothing before it counts
    F <hex>                     the whole padled read (first, and after a remap)
    G <hex>                     the whole merged switch array mrg[]
    L <off>:<hex> ...           padled bytes that changed since the last look
    M <off>:<hex> ...           mrg[] bytes that changed
    P <looks> <frames> <again> <lost>   alive, every PING_S, with its counts
    LOST <id> <level>           a switch the game never took (padsw.Confirmer)
    ERR <words>                 and exit: no block to map

The fire counters in padled are what make a short coil pulse visible, so a
look the host skips loses nothing; a look this side skips cannot either.

A PIPE, NOT A SOCKET. The reporter's sketch put the pushes on a TCP line on
127.0.0.1; the wsl.exe pipe the controller already started swkeys through
does the same job with nothing to listen on: no port to pick per rig, no
dependence on WSL's localhost relay (which accepts a connection with nothing
behind it, and is off in some networking modes), and the helper's death is an
EOF on the Windows side. HELLO and the ping are kept: the controller trusts
the link only after HELLO and drops back to its 9p reads if the pings stop
for 6 s (a wsl.exe wedged on forkpty says nothing at all).

EOF ON STDIN RELEASES EVERYTHING STILL HELD, as swkeys.py does.

    PAD_LED_FILE / PAD_SW_FILE   other blocks than the run's (tests)
    PAD_LINK_LOOK_MS             how often the blocks are compared (2)
    PAD_LINK_READ                bytes of padled to carry (the controller's READ_N)
"""
import mmap
import os
import select
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import padpath  # noqa: E402
import padsw    # noqa: E402
import swkeys   # noqa: E402

padsw.set_source("v")   # Visual Pinball's tag; PAD_SW_SRC overrides

VERSION = 1
LED_MAGIC = b"PLED"
LOOK_S = float(os.environ.get("PAD_LINK_LOOK_MS") or 2) / 1000.0
PING_S = 2.0
REMAP_S = 1.0
CHUNK = 64              # compare unit: a run of changed chunks is one L entry
MRG = (padsw.OFF_MRG, padsw.OFF_MRG + padsw.MAX_ID)


def led_path():
    return os.environ.get("PAD_LED_FILE") or os.path.join(padpath.dump() or "", "padled")


def diff(old, new, chunk=CHUNK):
    """[(offset, bytes)] covering every byte where `new` differs from `old`
    (same length), changed chunks next to each other run together."""
    out = []
    if old == new:
        return out
    n = len(new)
    mo, mn = memoryview(old), memoryview(new)
    start = None
    for off in range(0, n, chunk):
        end = min(n, off + chunk)
        if mo[off:end] != mn[off:end]:
            if start is None:
                start = off
        elif start is not None:
            out.append((start, bytes(mn[start:off])))
            start = None
    if start is not None:
        out.append((start, bytes(mn[start:n])))
    return out


def line(tag, runs):
    return "%s %s\n" % (tag, " ".join("%d:%s" % (o, b.hex()) for o, b in runs))


class Block:
    """One file mapped read-only, remapped when the run puts a new one there."""

    def __init__(self, path, want):
        self.path, self.want = path, want
        self.m = None
        self.ino = None
        self.n = 0

    def open(self):
        self.close()
        try:
            st = os.stat(self.path)
            with open(self.path, "rb") as f:
                self.m = mmap.mmap(f.fileno(), st.st_size, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            self.m = None
            return False
        self.ino = (st.st_dev, st.st_ino)
        self.n = min(self.want, st.st_size)
        return True

    def moved(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) != self.ino

    def read(self, lo=0, hi=None):
        return bytes(self.m[lo:self.n if hi is None else hi])

    def close(self):
        if self.m is not None:
            try:
                self.m.close()
            except (OSError, ValueError, BufferError):
                pass
        self.m = None


class Link:
    def __init__(self, out, led, sw, hold, clock=time.monotonic):
        self.out, self.led, self.sw, self.hold = out, led, sw, hold
        self.clock = clock
        self.last_led = self.last_mrg = None
        self.looks = self.frames = 0
        self.next_ping = self.next_remap = 0.0

    def send(self, text):
        self.out.write(text)
        self.out.flush()

    def full(self):
        self.last_led = self.led.read()
        self.last_mrg = self.sw.read(*MRG)
        self.send("F %s\nG %s\n" % (self.last_led.hex(), self.last_mrg.hex()))

    def hello(self):
        self.send("HELLO padlink %d led=%d sw=%d\n" % (VERSION, self.led.n, MRG[1] - MRG[0]))
        self.full()

    def look(self):
        now = self.clock()
        self.looks += 1
        if now >= self.next_remap:
            self.next_remap = now + REMAP_S
            if self.led.moved() and self.led.open():
                self.full()
                return
        new = self.led.read()
        if len(new) != len(self.last_led):
            self.full()
            return
        mrg = self.sw.read(*MRG)
        lr = diff(self.last_led, new)
        mr = diff(self.last_mrg, mrg, chunk=16)
        text = (line("L", lr) if lr else "") + (line("M", mr) if mr else "")
        self.last_led, self.last_mrg = new, mrg
        if now >= self.next_ping:
            self.next_ping = now + PING_S
            c = self.hold.sw
            text += "P %d %d %d %d\n" % (self.looks, self.frames, c.again, c.lost)
        if text:
            if lr or mr:
                self.frames += 1
            self.send(text)


def main(stdin=None, out=None):
    out = out or sys.stdout
    led = Block(led_path(), int(os.environ.get("PAD_LINK_READ") or 1 << 20))
    if not led.open() or led.read(0, 4) != LED_MAGIC:
        out.write("ERR no padled at %s\n" % led.path)
        out.flush()
        return 1
    m = padsw.open_block()
    if m is None:
        out.write("ERR no switch block at %s\n" % padsw.PATH)
        out.flush()
        return 1

    class _Sw:                     # the switch block as read for the pushes
        def read(self, lo, hi):
            return bytes(m[lo:hi])

    link = None

    def lost(sw, val):
        if link is not None:
            link.send("LOST %d %d\n" % (sw, val))

    hold = swkeys.Holder(m, on_lost=lost)
    link = Link(out, led, _Sw(), hold)
    link.hello()
    fd = (stdin or sys.stdin).fileno()
    buf = b""
    try:
        while True:
            r, _w, _x = select.select([fd], [], [], LOOK_S)
            if r:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    ln, buf = buf.split(b"\n", 1)
                    edge = swkeys.parse(ln.decode("ascii", "replace"))
                    if edge is not None:
                        hold.handle(edge)
            hold.tick()
            link.look()
    except (BrokenPipeError, OSError):
        pass                       # the controller went away: release below
    finally:
        hold.release()
        m.close()
        led.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
