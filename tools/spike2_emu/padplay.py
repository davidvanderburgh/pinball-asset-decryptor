#!/usr/bin/env python3
"""padplay.py [--fifo PATH | <host> <port>] <rate> <channels> - play the PCM.

ONE PLAYER ON ALL THREE PLATFORMS, which is the point of the two source forms.
The player itself is identical everywhere; only how the bytes reach it differs,
and that difference is forced by WSL alone:

  --fifo PATH   macOS and Linux. The game and the speakers are on one machine,
                so the player reads the guest's FIFO directly and PortAudio
                drives CoreAudio or ALSA. No socket, no relay, no bridge.
  host port     WSL only. The speakers are on the far side of a boundary whose
                audio hop is measurably broken, so the player runs as a WINDOWS
                process and padrelay.py hands it the same bytes over localhost.

Everything that decides how the audio SOUNDS - the queue, the pre-roll, the
underrun policy, the device clock - is the same code in both cases.


WHY THIS REPLACES winplay.py. The first player was a hand-rolled waveOut ring,
and the relay feeding it invented its own clock: it filled silence against wall
time and trimmed "surplus" it thought had built up. Two clocks, neither of them
the one that matters, and the audio skipped. PortAudio already solves this and
has for twenty years - the sound card pulls, through a callback, at the only
clock with a vote. So there is no pacing here at all.

CROSS-PLATFORM BY CONSTRUCTION, which is the other reason. The same file plays
through WASAPI on Windows, CoreAudio on macOS and ALSA/PulseAudio on Linux,
because that is what PortAudio is for. The rig has to run on all three.

WASAPI IS SELECTED EXPLICITLY on Windows. PortAudio's default host API there is
MME, which dates to 1991 and carries ~200 ms of latency - the same class of
interface the hand-rolled player used, and no better. WASAPI measures 3 ms on
this machine.

The only buffering is a plain byte queue between the socket and the callback,
pre-filled before the stream opens so the first callback is not starved. If it
does run dry the callback emits silence for that block and says so; it never
blocks, because blocking inside an audio callback is how you get a glitch in
every other application on the machine too.
"""
import json
import os
import socket
import sys
import threading
import time

import sounddevice as sd

try:
    import numpy as np
except ImportError:      # the Windows python pad_win_python() finds only ever
    np = None             # promises `import sounddevice` - see PAD_AUDIO_CTL
                          # below for why that has to stay survivable


def pick_device():
    """Windows: the WASAPI default. Everywhere else: whatever the system says."""
    if sys.platform != "win32":
        return None
    for api in sd.query_hostapis():
        if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
            return api["default_output_device"]
    return None


def open_source(argv):
    """Return (read(n), close(), description). See the two forms in the docstring."""
    if argv and argv[0] == "--fifo":
        path = argv[1]
        rest = argv[2:]
        # A FIFO open blocks until the guest opens the write end, which is
        # correct: there is nothing to play until it does.
        fd = os.open(path, os.O_RDONLY)
        return (lambda n: os.read(fd, n)), (lambda: os.close(fd)), path, rest
    host = argv[0] if argv else "127.0.0.1"
    port = int(argv[1]) if len(argv) > 1 else 45997
    sock = socket.create_connection((host, port), timeout=30)
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock.recv, sock.close, f"{host}:{port}", argv[2:]


def main():
    read, close, src_desc, rest = open_source(sys.argv[1:])
    rate = int(rest[0]) if rest else 44100
    ch = int(rest[1]) if len(rest) > 1 else 2

    frame = 2 * ch
    bps = rate * frame
    # The cushion the callback eats from. It only has to cover jitter in the
    # SOURCE - the guest's writes and the socket - because the device side is
    # handled by PortAudio's own latency setting.
    # 350 ms, measured. At 150 the queue dipped to 3 ms in the first seconds and
    # the startup transient was the only damage left in the recording (-11.2 dB,
    # worst blocks all inside the first second). At 350 the queue holds ~100 ms
    # for the whole run with zero underruns and the score is -14.8 dB, which is
    # slightly BETTER than Windows playing the same file itself.
    pre_ms = int(os.environ.get("PAD_AUDIO_PREBUFFER_MS", "350"))
    lat_ms = int(os.environ.get("PAD_AUDIO_LATENCY_MS", "60"))
    prebuf = bps * pre_ms // 1000

    # ---- item 56: master PC-side volume + Mute, our level not the game's --
    #
    # PAD_AUDIO_CTL names a small JSON ({"gain": 0-1, "muted": bool}) that the
    # Emulate tab rewrites on every slider/Mute change
    # (emulate_tab.py's _write_audio_ctl) — it is BOTH the remembered setting
    # AND the live control channel, so a run already up picks up a change with
    # no restart and a fresh run starts at whatever the file already says. No
    # env var (a manual/dev invocation, or the macOS/Linux paths that do not
    # set it yet) means unity gain — today's behaviour, unchanged.
    #
    # WHY NOT audioop: it left the stdlib in 3.13. numpy scales the int16
    # buffer instead — but the WINDOWS python this runs under for the WSL
    # bridge is found by pad_win_python() (padpath.sh), which only ever
    # verifies `import sounddevice`, never numpy. An install with sounddevice
    # but no numpy must keep playing exactly as it does today — not crash on
    # import — so every numpy use below is guarded, and Mute (silence) still
    # works with no numpy at all; only in-between volumes need it.
    ctl_path = os.environ.get("PAD_AUDIO_CTL")
    gain_state = {"value": 1.0}
    _ctl_seen = [None]

    def poll_gain():
        if not ctl_path:
            return
        try:
            mtime = os.stat(ctl_path).st_mtime
        except OSError:
            return
        if mtime == _ctl_seen[0]:
            return
        _ctl_seen[0] = mtime
        try:
            with open(ctl_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            g = 0.0 if data.get("muted") else float(data.get("gain", 1.0))
        except (OSError, ValueError, TypeError):
            return
        g = max(0.0, min(1.0, g))
        if g != gain_state["value"]:
            gain_state["value"] = g
            print(f"[padplay] volume -> {g:.2f}", flush=True)

    if ctl_path and np is None:
        print("[padplay] numpy not installed; the volume/mute knob is inert "
              "(pip install numpy to enable it)", flush=True)

    buf = bytearray()
    lock = threading.Lock()
    done = threading.Event()
    stats = {"under": 0, "fed": 0, "played": 0}

    def reader():
        try:
            while not done.is_set():
                b = read(65536)
                if not b:
                    break
                with lock:
                    buf.extend(b)
                    stats["fed"] += len(b)
        except OSError:
            pass
        finally:
            done.set()

    threading.Thread(target=reader, daemon=True).start()

    # Pre-fill. Give the source a moment to get ahead before the card starts
    # asking, or the very first callback underruns and every one after it is
    # chasing.
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:
        with lock:
            if len(buf) >= prebuf:
                break
        if done.is_set():
            break
        time.sleep(0.005)

    def callback(outdata, frames, _time, status):
        need = frames * frame
        with lock:
            have = len(buf)
            n = min(need, have)
            chunk = bytes(buf[:n]) if n else b""
            if n:
                del buf[:n]
            stats["played"] += n
        if n:
            g = gain_state["value"]
            if g <= 0.0:
                # Mute needs no numpy: a memset beats a multiply either way.
                outdata[:n] = b"\0" * n
            elif g >= 1.0 or np is None:
                outdata[:n] = chunk
            else:
                # int16 * a fraction in [0, 1] can never overflow int16, so no
                # clip is needed — this only ever attenuates, per the item
                # (no boost lever was asked for).
                samples = np.frombuffer(chunk, dtype=np.int16)
                outdata[:n] = (samples * np.float32(g)).astype(np.int16).tobytes()
        if n < need:
            # Silence for what we could not fill. Never block, never sleep.
            outdata[n:need] = b"\0" * (need - n)
            stats["under"] += 1

    dev = pick_device()
    # WASAPI in shared mode only accepts the device's own rate, and this card
    # runs at 48000 while the game plays 44100 - PortAudio answers "Invalid
    # sample rate" outright. auto_convert hands that conversion to WASAPI's own
    # resampler, which is the correct place for it: the mixer has to resample
    # anyway to share the device with every other application. Doing it here by
    # hand would be a third wheel to reinvent, and rate conversion is already
    # ruled out as the source of the damage - 48000 measured no better than
    # 44100 through pulse.
    extra = None
    if sys.platform == "win32" and dev is not None:
        try:
            extra = sd.WasapiSettings(auto_convert=True)
        except TypeError:
            extra = None            # older binding: fall through and let it fail loudly
    stream = sd.RawOutputStream(
        samplerate=rate, channels=ch, dtype="int16",
        device=dev, latency=lat_ms / 1000.0, callback=callback,
        extra_settings=extra,
    )
    name = sd.query_devices(dev)["name"] if dev is not None else "default"
    api = sd.query_hostapis(sd.query_devices(dev)["hostapi"])["name"] if dev is not None else "-"
    print(f"[padplay] {src_desc} -> {rate} Hz x {ch} -> {name} via {api}, "
          f"prebuffer {pre_ms} ms, device latency {lat_ms} ms", flush=True)

    poll_gain()   # so the very first buffers already play at the remembered
                  # level, not at unity for one poll interval
    with stream:
        last = time.monotonic()
        # No-data watchdog. The guest streams CONTINUOUSLY (silence included),
        # so a feed that stops entirely means the transport died under us —
        # seen live 2026-08-31 as a half-open WSL localhost-proxy connection:
        # the socket stayed "connected" but never delivered another byte, the
        # player idled forever, and the run was silent with no line saying so.
        # Exiting hands recovery to playaudio.sh's restart loop, which spawns
        # a fresh player and a fresh connection.
        fed_last = (stats["fed"], time.monotonic())
        while not done.is_set() or len(buf) > 0:
            time.sleep(0.25)
            poll_gain()
            now = time.monotonic()
            if stats["fed"] != fed_last[0]:
                fed_last = (stats["fed"], now)
            elif now - fed_last[1] > 25:
                print("[padplay] no data for 25 s - transport presumed dead, "
                      "exiting for a fresh connection", flush=True)
                done.set()
                close()
                sys.exit(1)
            if now - last >= 5:
                with lock:
                    depth = len(buf)
                print(f"[padplay] queue {depth * 1000 // bps:4d} ms  "
                      f"underruns {stats['under']:4d}  "
                      f"fed {stats['fed']}  played {stats['played']}", flush=True)
                stats["under"] = 0
                last = now
    close()


if __name__ == "__main__":
    main()
