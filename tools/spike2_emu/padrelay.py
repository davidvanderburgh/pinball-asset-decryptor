#!/usr/bin/env python3
"""padrelay.py <fifo> <port> - hand the guest's PCM to a socket. That is all.

THE POINT OF THIS FILE IS EVERYTHING IT DOES NOT DO. Its predecessor,
audiotcp.py, filled silence against wall time, trimmed what it judged to be
surplus, and kept a running `sent` total that it re-baselined forward after a
read gap. That last part is why it appeared to send 10% more than the far end
ever received - a "shortfall" that cost hours and was pure bookkeeping, since
`sent` advanced for bytes that were never put on the wire. The pacing was just
as misguided: it was a second clock competing with the sound card's, and the
audible result was music that skipped.

TCP does not lose bytes and the sound card is the only clock with a vote, so a
relay has nothing to decide. It copies. padplay.py holds the cushion, because
that is where the device is.

Measured end to end against the source, same file and capture rig throughout:
audiotcp.py + ffplay scored +16 dB of damage; this + padplay.py scores -14.8 dB,
level with Windows playing the file directly.
"""
import os
import socket
import sys

if len(sys.argv) < 3:
    print("usage: padrelay.py <fifo> <port>", file=sys.stderr)
    raise SystemExit(2)
fifo, port = sys.argv[1], int(sys.argv[2])

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", port))
srv.listen(1)
print("[padrelay] listening on %d for a player" % port, flush=True)

while True:
    conn, addr = srv.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("[padrelay] player connected from %s" % (addr,), flush=True)

    # OPENED ONLY NOW, and that ordering is load-bearing. Opening a FIFO for
    # read blocks until a writer exists, so an ffmpeg told to read the FIFO and
    # listen on a socket would sit on the empty FIFO and never open the socket
    # at all - the player would find nothing to connect to and the run was
    # silent. Listen first, open second.
    fd = os.open(fifo, os.O_RDONLY)
    total = 0
    try:
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            conn.sendall(b)
            total += len(b)
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        print("[padrelay] player went away: %s" % exc, flush=True)
    finally:
        print("[padrelay] %d bytes forwarded" % total, flush=True)
        os.close(fd)
        conn.close()
