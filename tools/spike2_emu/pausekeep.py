#!/usr/bin/env python3
"""pausekeep.py - stops and resumes the guest for padglhost's Pause (PAD-204).

    python3 pausekeep.py <padsw block>        # as ROOT, started by watch.sh

WHY THIS EXISTS. A run from the app is a PAD_PIVOT run: the guest runs as root
and watch.sh drops every helper, the renderer included, to the desktop user.
padglhost owns the Pause key, and a user cannot SIGSTOP a root process - so on
every real install the key did nothing and the only trace was "[pause] no
running game to pause" in a log the app never shows. The rig proofs ran
watch.sh as the user, where the guest was the user's own, and passed.

So this one small thing stays root. padglhost writes what it wants into the
switch block (stop_want, then a new stop_gen); this signals every process whose
comm is `game` - the name every rig tool finds the guest by - and answers with
the count (stop_n) and then the generation it served (stop_ack). Nothing else:
the frozen-time bookkeeping the shim reads stays padglhost's, in the order it
already had, and padglhost waits for the answer before it starts that clock.

It never leaves the game frozen behind it. When padglhost is gone, or on
SIGTERM / SIGINT, a game it stopped is resumed before it exits.
"""
import mmap
import os
import signal
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padsw

POLL_S = 0.01            # a press is served within ~10 ms
WAIT_BLOCK_S = 600       # the renderer maps the block on the game's first frame


def game_pids():
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % d) as f:
                if f.read().strip() == "game":
                    out.append(int(d))
        except OSError:
            pass
    return out


def signal_games(sig):
    n = 0
    for pid in game_pids():
        try:
            os.kill(pid, sig)
            n += 1
        except OSError as exc:
            print("[pause] could not signal game pid %d: %s" % (pid, exc), flush=True)
    return n


def renderer_up():
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/comm" % d) as f:
                    if f.read().strip() == "padglhost":
                        return True
            except OSError:
                pass
    return False


def u32(m, off):
    return struct.unpack_from("<I", m, off)[0]


def serve(m):
    """Answer padglhost's request, if there is one it has not had an answer to.
    (want, games signalled) when it served one, None when there was nothing."""
    gen = u32(m, padsw.OFF_STOP_GEN)
    if gen == u32(m, padsw.OFF_STOP_ACK):
        return None
    want = u32(m, padsw.OFF_STOP_WANT)
    n = signal_games(signal.SIGSTOP if want else signal.SIGCONT)
    # the count BEFORE the ack: padglhost reads n once it sees its gen
    struct.pack_into("<I", m, padsw.OFF_STOP_N, n)
    struct.pack_into("<I", m, padsw.OFF_STOP_ACK, gen)
    print("[pause] %s %d game process(es)" % ("froze" if want else "resumed", n),
          flush=True)
    return want, n


def main(path):
    stopped = False

    def resume_and_exit(*_):
        if stopped:
            signal_games(signal.SIGCONT)
            print("[pause] keeper stopping; resumed the game it had frozen", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, resume_and_exit)
    signal.signal(signal.SIGINT, resume_and_exit)

    m = None
    deadline = time.monotonic() + WAIT_BLOCK_S
    while m is None:
        if time.monotonic() > deadline or not renderer_up():
            return 0
        try:
            if os.path.getsize(path) >= padsw.SIZE:
                with open(path, "r+b") as f:
                    m = mmap.mmap(f.fileno(), 4096)
        except OSError:
            pass
        if m is None:
            time.sleep(0.5)
    # a request a previous session left unanswered is not this run's to serve
    struct.pack_into("<I", m, padsw.OFF_STOP_ACK, u32(m, padsw.OFF_STOP_GEN))
    print("[pause] keeper up: Pause is served as root (the game runs as root here)",
          flush=True)

    last_check = 0.0
    while True:
        served = serve(m)
        if served is not None:
            want, n = served
            stopped = bool(want) and n > 0
        now = time.monotonic()
        if now - last_check > 1.0:
            last_check = now
            if not renderer_up():
                resume_and_exit()
        time.sleep(POLL_S)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
