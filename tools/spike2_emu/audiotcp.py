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
import time


def main():
    if len(sys.argv) < 3:
        print("usage: audiotcp.py <fifo> <port> [prebuffer_bytes]",
              file=sys.stderr)
        return 2
    fifo, port = sys.argv[1], int(sys.argv[2])
    prebuf = int(sys.argv[3]) if len(sys.argv) > 3 else 0

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
                # PRE-BUFFER, and this is the difference between "not crackly"
                # and "smooth".
                #
                # A live stream that arrives at exactly real time gives the
                # player NO CUSHION: it plays as fast as it receives, so every
                # hiccup in the game's output becomes an underrun and the music
                # audibly skips beats. Player-side flags cannot fix that -
                # there is nothing queued to ride out the gap. Measured while
                # it was skipping: the guest's own `dropped=0` and `fifo=0 ms`,
                # so nothing was being lost here at all; the player was simply
                # always hungry.
                #
                # So hold back the first chunk and hand it over in one go. The
                # player's queue then carries that much slack for the rest of
                # the session, at the cost of the same delay once at startup.
                held = bytearray()
                while prebuf and len(held) < prebuf:
                    b = f.read(4096)
                    if not b:
                        break
                    held += b
                if held:
                    print("[audiotcp] pre-buffered %d bytes before starting"
                          % len(held), flush=True)
                    conn.sendall(bytes(held))
                # PAD_AUDIO_GAPLOG=1 - where the jitter actually is.
                #
                # "The music skips" has two completely different causes and
                # they need different fixes: the GUEST going quiet for a while
                # (a gap between reads here, which a bigger cushion absorbs),
                # or the SEND stalling (backpressure from a player that is not
                # keeping up, which a cushion cannot help at all). Guessing
                # between them has already cost two wrong fixes, so measure:
                # per 5 s, the worst read gap and the worst send stall.
                # ON BY DEFAULT while the skipping is open: one line per 5 s in
                # padaudio.log is nothing, and an instrument that has to be
                # switched on is an instrument that is off on the run that
                # mattered - which is exactly what happened the first time this
                # was measured. PAD_AUDIO_GAPLOG=0 silences it.
                gaplog = os.environ.get("PAD_AUDIO_GAPLOG", "1") != "0"
                t_last = time.monotonic()
                win_t0, win_read, win_send, win_bytes = t_last, 0.0, 0.0, 0
                while True:
                    b = f.read(4096)
                    now = time.monotonic()
                    if gaplog:
                        win_read = max(win_read, now - t_last)
                    if not b:
                        # Every writer closed: the run is going away.
                        break
                    t_send = now
                    conn.sendall(b)
                    t_last = time.monotonic()
                    if gaplog:
                        win_send = max(win_send, t_last - t_send)
                        win_bytes += len(b)
                        if t_last - win_t0 >= 5.0:
                            span = t_last - win_t0
                            print("[audiotcp] %5.1fs: %6.1f KB (%5.1f%% of real "
                                  "time)  worst read gap %5.1f ms  worst send "
                                  "stall %5.1f ms"
                                  % (span, win_bytes / 1024.0,
                                     100.0 * win_bytes / (176400.0 * span),
                                     win_read * 1000.0, win_send * 1000.0),
                                  flush=True)
                            win_t0, win_read, win_send, win_bytes = \
                                t_last, 0.0, 0.0, 0
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
