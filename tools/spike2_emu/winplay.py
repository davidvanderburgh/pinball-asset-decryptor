#!/usr/bin/env python3
"""winplay.py <host> <port> <rate> <channels> - the game's speaker, on Windows.

RUNS ON WINDOWS, launched from WSL through interop, exactly like the ffplay it
replaces. Connects to audiotcp.py and plays raw s16le through winmm's waveOut.

WHY NOT ffplay. It plays a FILE flawlessly and stutters on a LIVE stream, which
was established by elimination: the game's own PCM is flawless, ffplay playing
that same wav off disk is flawless, and the identical bytes streamed to it over
TCP in real time stutter. A player fed a file reads ahead as fast as it likes;
one fed at real time never gets to, and ffplay has no way to be told "hold this
much and no less". There is no knob for the thing that matters.

WHAT THIS DOES DIFFERENTLY: an explicit ring of N fixed buffers queued to the
device at all times. The device always has work, so it cannot underrun; when
the network is late the ring is topped up with SILENCE rather than being
allowed to run dry, because a short silence is inaudible and a starved device
is a click. That is the one behaviour ffplay would not give us.

Latency is BUFFERS * BUFFER_MS, default 8 * 25 = 200 ms, and it is bounded by
construction: audio is only ever pulled from the socket as fast as the device
retires buffers, so TCP back-pressure paces the whole chain back to the guest.
"""
import ctypes
import threading
import ctypes.wintypes as wt
import socket
import sys
import time

WAVE_MAPPER = 0xFFFFFFFF
WHDR_DONE = 0x00000001
CALLBACK_NULL = 0x00000000

BUFFER_MS = 25
BUFFERS = 8
#: Extra buffers held in `pending` behind the ring, so a buffer freeing up can
#: always be filled from real audio instead of padded with silence. Total
#: latency is (BUFFERS + CUSHION_BUFFERS) * BUFFER_MS = 400 ms at these values.
CUSHION_BUFFERS = 8


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD),
                ("nSamplesPerSec", wt.DWORD), ("nAvgBytesPerSec", wt.DWORD),
                ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
                ("cbSize", wt.WORD)]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.c_char_p), ("dwBufferLength", wt.DWORD),
    ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.POINTER(wt.DWORD)),
    ("dwFlags", wt.DWORD), ("dwLoops", wt.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)), ("reserved", ctypes.POINTER(wt.DWORD)),
]


def main():
    if len(sys.argv) < 5:
        print("usage: winplay.py <host> <port> <rate> <channels>",
              file=sys.stderr)
        return 2
    host, port = sys.argv[1], int(sys.argv[2])
    rate, ch = int(sys.argv[3]), int(sys.argv[4])
    frame = ch * 2
    bufbytes = (rate * BUFFER_MS // 1000) * frame

    winmm = ctypes.WinDLL("winmm")

    fmt = WAVEFORMATEX(1, ch, rate, rate * frame, frame, 16, 0)
    hwo = ctypes.c_void_p()
    rc = winmm.waveOutOpen(ctypes.byref(hwo), WAVE_MAPPER, ctypes.byref(fmt),
                           0, 0, CALLBACK_NULL)
    if rc != 0:
        print("[winplay] waveOutOpen failed rc=%d" % rc, file=sys.stderr)
        return 1
    print("[winplay] device open: %d Hz x %d ch, %d x %d ms = %d ms of ring"
          % (rate, ch, BUFFERS, BUFFER_MS, BUFFERS * BUFFER_MS), flush=True)

    # Connect only after the device is up, so the first audio off the wire has
    # somewhere to go immediately.
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection((host, port), timeout=5)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[winplay] could not connect to %s:%d" % (host, port),
              file=sys.stderr)
        return 1
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("[winplay] connected", flush=True)

    # THE READER GETS ITS OWN THREAD, and this is the whole difference between
    # working and not.
    #
    # The first version polled the socket from the playback loop, between
    # sleeps. Windows' default timer resolution is ~15.6 ms, so a requested
    # 6.25 ms sleep really lasts ~15.6 ms, and the socket was therefore only
    # drained about 64 times a second. Measured result: the relay sent 860 KB
    # per 5 s and this process received 776.0 KB - a rock-steady 90.0%, every
    # window. TCP had the data; nobody was collecting it fast enough, and the
    # missing 10% is exactly the stutter.
    #
    # A thread doing a BLOCKING recv wakes the moment bytes land, so reading is
    # never gated by playback timing again.
    pending = bytearray()
    lock = threading.Lock()
    state = {"alive": True, "got": 0}

    def reader():
        try:
            while state["alive"]:
                chunk = s.recv(65536)
                if not chunk:
                    break
                with lock:
                    pending.extend(chunk)
                    state["got"] += len(chunk)
        except OSError:
            pass
        state["alive"] = False

    threading.Thread(target=reader, daemon=True).start()

    bufs = [ctypes.create_string_buffer(bufbytes) for _ in range(BUFFERS)]
    hdrs = [WAVEHDR() for _ in range(BUFFERS)]
    for h, b in zip(hdrs, bufs):
        h.lpData = ctypes.cast(b, ctypes.c_char_p)
        h.dwBufferLength = bufbytes
        h.dwFlags = 0
        winmm.waveOutPrepareHeader(hwo, ctypes.byref(h), ctypes.sizeof(h))
        h.dwFlags |= WHDR_DONE          # free to fill

    silence = 0
    total = 0
    t_report = time.monotonic()

    # PRE-ROLL: fill the ring BEFORE the device starts.
    #
    # The ring's depth is set once, at the start, and never recovers: data
    # arrives at exactly real time, so a buffer can only be refilled as fast as
    # the device retires one. Start shallow and it stays shallow - measured at
    # 2 of 8 buffers, i.e. 50 ms in hand, which the emergency pad then had to
    # rescue ~500 ms per 5 s. Start full and it stays full, and the pad never
    # fires at all.
    # Enough to FILL THE RING **AND** LEAVE A CUSHION BEHIND IT. Pre-rolling
    # only the ring is not enough and the reason is easy to miss: the first
    # thing the loop does is hand every buffer to the device, which empties
    # `pending` completely. From then on data arrives just-in-time, in 23.4 ms
    # chunks against 25 ms buffers, so the ring can only ever shrink - measured
    # decaying 6/8 -> 2/8 and then padding ~500 ms per 5 s. The cushion has to
    # sit in `pending`, where a buffer can always be filled from it.
    want_preroll = bufbytes * (BUFFERS + CUSHION_BUFFERS)
    t_wait = time.monotonic()
    while time.monotonic() - t_wait < 10.0:
        with lock:
            if len(pending) >= want_preroll:
                break
        if not state["alive"]:
            break
        time.sleep(0.002)
    with lock:
        have = len(pending)
    print("[winplay] pre-rolled %d ms before starting the device"
          % (1000 * have // (rate * frame)), flush=True)

    try:
        while state["alive"] or pending:
            queued = sum(1 for h in hdrs if not (h.dwFlags & WHDR_DONE))

            for h, b in zip(hdrs, bufs):
                if not (h.dwFlags & WHDR_DONE):
                    continue
                # WAIT FOR A WHOLE BUFFER. The first version padded a partial
                # buffer with silence "rather than hold it back", which sounds
                # prudent and is the bug: it spliced silence straight into the
                # music every time less than 25 ms had arrived - measured at
                # ~500 ms of injected silence per 5 s, 10% of the audio, which
                # is exactly the stutter it was meant to prevent.
                #
                # There is no urgency: while this buffer sits empty the other
                # seven are still playing, so the device has 175 ms of work in
                # hand. Waiting costs nothing and keeps the music intact.
                with lock:
                    have = len(pending)
                if have >= bufbytes:
                    with lock:
                        b.raw = bytes(pending[:bufbytes])
                        del pending[:bufbytes]
                elif queued <= 1:
                    # NOW it is urgent: the device is about to run out, and a
                    # short silence beats a starved device (which clicks).
                    with lock:
                        part = bytes(pending)
                        del pending[:]
                    b.raw = part + b"\0" * (bufbytes - len(part))
                    silence += bufbytes - len(part)
                else:
                    break                      # let the ring drain a little
                queued += 1
                h.dwFlags &= ~WHDR_DONE
                h.dwBufferLength = bufbytes
                rc = winmm.waveOutWrite(hwo, ctypes.byref(h), ctypes.sizeof(h))
                if rc != 0:
                    print("[winplay] waveOutWrite rc=%d" % rc, file=sys.stderr)
                    h.dwFlags |= WHDR_DONE
                    queued -= 1
                else:
                    total += bufbytes
            # Sleep well under one buffer so the ring is refilled long before
            # the device reaches the end of it.
            time.sleep(BUFFER_MS / 4000.0)
            now = time.monotonic()
            if now - t_report >= 5.0:
                span = now - t_report
                print("[winplay] %5.1fs: RECEIVED %6.1f KB (%5.1f%% of real "
                      "time), out %6.1f KB, %5.1f ms silence, ring %d/%d, "
                      "%d KB waiting"
                      % (span, state["got"] / 1024.0,
                         100.0 * state["got"] / (rate * frame * span),
                         total / 1024.0,
                         1000.0 * silence / (rate * frame), queued, BUFFERS,
                         len(pending) // 1024), flush=True)
                total = silence = 0
                state["got"] = 0
                t_report = now
    finally:
        winmm.waveOutReset(hwo)
        for h in hdrs:
            winmm.waveOutUnprepareHeader(hwo, ctypes.byref(h), ctypes.sizeof(h))
        winmm.waveOutClose(hwo)
        try:
            s.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
