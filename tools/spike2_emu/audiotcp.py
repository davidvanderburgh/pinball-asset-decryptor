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
import select
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
    # Bytes per second of the stream, needed to fill silence in real time.
    # Passed in rather than guessed: the guest reports its own rate and
    # playaudio.sh already knows it.
    bps = int(sys.argv[4]) if len(sys.argv) > 4 else 44100 * 2 * 2

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
                # FILL THE SILENCE, in real time. This is the whole fix.
                #
                # Measured on a real run: `worst send stall 0.1 ms` (the player
                # and TCP never push back) but `worst read gap 62029 ms` - the
                # guest simply goes quiet for a minute at a time. During those
                # gaps a naive relay sends NOTHING, the player's queue drains to
                # empty, and the pre-buffer - which is a ONE-TIME cushion - is
                # gone for the rest of the session. Every burst of sound after
                # that starts from an empty queue and underruns, which is the
                # music skipping beats. A bigger one-shot buffer could never
                # have fixed it.
                #
                # A real sound card does not stop when the game stops talking;
                # it plays silence. So does this. The stream stays continuous at
                # exactly `bps`, the player's queue stays at `prebuf`, and real
                # audio lands behind a cushion that is always there. Latency is
                # then CONSTANT (the cushion), not growing.
                gaplog = os.environ.get("PAD_AUDIO_GAPLOG", "1") != "0"
                frame = 4                       # s16 stereo; only used to align
                # Most bytes trimmed from any one chunk. 64 frames is 1.45 ms
                # at 44.1 kHz - far below what a listener can pick out, and at
                # ~13 chunks a second it can absorb well over 1% of drift,
                # which is an order of magnitude more than the ~0.14% seen.
                MAX_TRIM = 64 * frame
                # AND A HARD CEILING ON HOW MUCH GETS TRIMMED OVER TIME.
                #
                # Per-chunk capping alone is not enough: measured, one 5 s
                # window trimmed 185 ms - 3.7% of the audio in it - because a
                # burst arrived without a preceding read gap, so the
                # re-baseline below never fired and every chunk trimmed its
                # maximum. Removing 3.7% of real music is audible, and the
                # small-artifact count went up accordingly.
                #
                # A token bucket fixes it: trimming may only spend what real
                # time has accrued at TRIM_FRACTION. 0.5% is over three times
                # the ~0.14% actually needed, so genuine drift is always
                # covered, while a burst can no longer eat into the music.
                TRIM_FRACTION = 0.005
                trim_budget = 0.0
                budget_t = time.monotonic()
                # Hysteresis band for the trimmer, in bytes of queue depth.
                # Start trimming only when the player is holding more than
                # ~1.2 s, and stop once it is back to ~0.6 s. Both are far
                # above any legitimate burst, so ordinary play never trims.
                trim_high = int(bps * 1.2)
                trim_low = int(bps * 0.6)
                trimming = False
                t0 = time.monotonic()
                sent = 0                        # bytes sent since t0
                t_last = t0
                win_t0, win_read, win_send, win_bytes, win_pad, win_trim = \
                    t0, 0.0, 0.0, 0, 0, 0
                eof = False
                while not eof:
                    # Wait briefly for real audio. select() rather than a
                    # blocking read: a blocking read is exactly what let the
                    # stream stop during a silence.
                    r, _, _ = select.select([f], [], [], 0.005)
                    b = b""
                    if r:
                        b = f.read(65536)
                        if not b:
                            eof = True          # every writer closed
                        else:
                            # TRIM THE SURPLUS A FRAME AT A TIME.
                            #
                            # The guest produces ~0.14% MORE audio than real
                            # time (the relay reports 100.1-100.2% during
                            # music). Something has to absorb that, and left
                            # alone the audio device does it it own way:
                            # measured off a "What U Hear" capture of the real
                            # speakers, it discards ~20 ms in one go every
                            # ~14.5 s - 20 ms / 14.5 s IS 0.14% - and each of
                            # those is an audible skip. That was the whole
                            # complaint; it is not starvation, it is surplus.
                            #
                            # So absorb it ourselves, finely. Dropping a few
                            # FRAMES per 64 KB chunk removes the same audio
                            # over the same period, but spread thin enough to
                            # be inaudible - the same trick a resampler plays.
                            # One 20 ms hole per 14 s is a skipped beat; 1
                            # sample in 750 is nothing.
                            # A BURST AFTER SILENCE IS NOT SURPLUS. The guest
                            # holds ~185 ms of write-ahead, so the first read
                            # after a quiet stretch arrives all at once and
                            # looks exactly like 185 ms of surplus. Trimming it
                            # would clip the attack off every sound that
                            # follows a silence - measured doing precisely
                            # that: 142 ms trimmed in the window where audio
                            # resumed after a 62 s gap. Only sustained
                            # overproduction is surplus, so re-baseline
                            # whenever the guest has actually been quiet.
                            now_r = time.monotonic()
                            if now_r - t_last > 0.25:
                                sent = int((now_r - t0) * bps)
                            now_b = time.monotonic()
                            trim_budget = min(
                                trim_budget + (now_b - budget_t) * bps * TRIM_FRACTION,
                                MAX_TRIM * 8.0)
                            budget_t = now_b
                            ahead = sent - int((now_b - t0) * bps)
                            # DEADBAND, and it is the difference between fixing
                            # the drift and destroying the audio.
                            #
                            # Chasing `ahead` down to zero looks right and is
                            # not: any one-off burst - the source starting up,
                            # the guest flushing its write-ahead - puts `sent`
                            # permanently ahead, and the trimmer then removes
                            # real audio at its full rate for as long as it
                            # takes to claw back. Measured: 25 ms trimmed every
                            # 5 s, 0.5% of the music, CONTINUOUSLY. One sample
                            # in 200 is plainly audible, and that is what made
                            # the "fixed" version still sound wrong.
                            #
                            # Being ahead is not itself a fault - it is just
                            # latency sitting in the player's queue. It only
                            # matters when it grows far enough that something
                            # downstream discards a chunk. So leave it alone
                            # until it is well past the cushion, then trim back
                            # to a low-water mark and STOP. In steady state
                            # nothing is trimmed at all.
                            if ahead > trim_high:
                                trimming = True
                            elif ahead < trim_low:
                                trimming = False
                            if trimming and len(b) > MAX_TRIM + frame:
                                drop = min(ahead - ahead % frame, MAX_TRIM,
                                           int(trim_budget))
                                drop -= drop % frame
                                if drop >= frame:
                                    b = b[drop:]
                                    trim_budget -= drop
                                    if gaplog:
                                        win_trim += drop
                            t_send = time.monotonic()
                            conn.sendall(b)
                            sent += len(b)
                            now = time.monotonic()
                            if gaplog:
                                win_send = max(win_send, now - t_send)
                                win_read = max(win_read, t_send - t_last)
                                win_bytes += len(b)
                            t_last = now

                    # Top the stream up to real time with silence. `want` counts
                    # from t0 and includes the pre-buffer, so the queue is held
                    # at `prebuf` rather than merely kept non-empty.
                    now = time.monotonic()
                    want = int((now - t0) * bps)
                    short = want - sent
                    if short >= 2048:
                        short -= short % frame
                        conn.sendall(b"\0" * short)
                        sent += short
                        if gaplog:
                            win_pad += short

                    if gaplog and now - win_t0 >= 5.0:
                        span = now - win_t0
                        print("[audiotcp] %5.1fs: %6.1f KB audio + %6.1f KB "
                              "silence - %5.1f ms trimmed (%5.1f%% of real "
                              "time)  read gap %6.1f ms  send stall %4.1f ms"
                              % (span, win_bytes / 1024.0, win_pad / 1024.0,
                                 1000.0 * win_trim / bps,
                                 100.0 * (win_bytes + win_pad) / (bps * span),
                                 win_read * 1000.0, win_send * 1000.0),
                              flush=True)
                        win_t0, win_read, win_send, win_bytes, win_pad, \
                            win_trim = now, 0.0, 0.0, 0, 0, 0
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
