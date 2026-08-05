#!/usr/bin/env python3
"""audiotcp.py <fifo> <port> - hand the guest's PCM to a Windows player.

WHY THIS EXISTS RATHER THAN ONE MORE ffmpeg. The obvious version of this is

    ffmpeg -f s16le -i "$FIFO" -c:a copy -f s16le "tcp://0.0.0.0:$PORT?listen=1"

and it does not work, for a reason worth writing down: **ffmpeg opens its
INPUT before its OUTPUT**. The input here is a FIFO that stays empty until the
game first makes a sound, which is a long way into the boot, so ffmpeg sits
blocked on the read and never opens the listening socket at all. The Windows
player then finds nothing to connect to and exits with a connection error, and
the run has no audio. (Tested against a generated tone it looks perfect, which
is exactly how it got shipped once - a tone is available instantly and the
ordering never shows.)

So: LISTEN FIRST, open the FIFO only once a player is attached. The socket
exists from the moment this starts, whatever the game is doing.

Raw bytes in, raw bytes out, no transformation - the format is agreed out of
band (the guest writes it to audio.fmt and playaudio.sh passes it to the
player), so this end only has to be a pipe that does not reorder or drop.
"""
import os
import socket
import sys


def main():
    if len(sys.argv) < 3:
        print("usage: audiotcp.py <fifo> <port>", file=sys.stderr)
        return 2
    fifo, port = sys.argv[1], int(sys.argv[2])

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    print("[audiotcp] listening on %d for a Windows player" % port, flush=True)

    while True:
        conn, _ = srv.accept()
        # TCP_NODELAY: this is a latency path, not a throughput one. Nagle
        # would sit on a small write waiting for company, and the whole point
        # of the exercise is a flipper answering promptly.
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("[audiotcp] player connected", flush=True)
        try:
            # O_RDONLY on a FIFO blocks until a writer exists; playaudio.sh
            # holds one open for the whole session, so this returns at once
            # and read() then blocks on silence rather than reporting EOF.
            fd = os.open(fifo, os.O_RDONLY)
        except OSError as exc:
            print("[audiotcp] cannot open %s: %s" % (fifo, exc), flush=True)
            conn.close()
            continue
        try:
            with os.fdopen(fd, "rb", buffering=0) as f:
                while True:
                    b = f.read(4096)
                    if not b:
                        # Every writer closed: the run is going away.
                        break
                    conn.sendall(b)
        except (BrokenPipeError, ConnectionResetError):
            print("[audiotcp] player went away", flush=True)
        except OSError as exc:
            print("[audiotcp] %s" % exc, flush=True)
        finally:
            try:
                conn.close()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
