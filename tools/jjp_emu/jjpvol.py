#!/usr/bin/env python3
"""Hold the JJP rig's sound at the app's Volume / Mute - live.

The Spike 2 and Spike 1 rigs play through a relay of our own (padplay.py) that
polls the app's ``audio_ctl.json`` and scales the samples itself.  A JJP game
has nothing of ours in its audio path: it is a native program speaking
PulseAudio straight to WSLg (audio.sh points Allegro at it), and the boot menu
of a multi-boot image plays through ALSA's pulse plugin to the same server.
What PulseAudio does give us is a volume and a mute PER STREAM.  So this polls
the same control file the other Emulate tabs write, and sets both on every
stream the game and the menu open - including the fresh stream a game opens
each time it restarts (exit 68), which is why it is a loop and not a one-shot.
(PulseAudio's stream-restore also remembers the level per application name,
so a new stream starts at the last level rather than at full volume.)

Root, on the WSL host, beside the rig: pactl runs INSIDE the jail - the image
carries it, and audio.sh has just proved the server answers there - so the host
needs nothing installed.  It exits by itself when the jail goes away; stop.sh
also ends it.

    jjpvol.py --ctl /mnt/c/.../audio_ctl.json [--jail /var/tmp/jjp_run]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

#: The processes whose streams are ours: the game, and the multi-boot menu.
BINARIES = ("game", "jjpselect")
#: PA_VOLUME_NORM - 100 %.
NORM = 65536


def target_volume(gain, muted):
    """``(raw pulse volume, mute)`` for the app's linear gain 0..1.

    PulseAudio's volume is CUBIC in amplitude (``pa_sw_volume_to_linear``), so a
    linear gain g is the raw volume ``cbrt(g) * NORM`` - the same loudness the
    relay's sample scaling gives on the Stern tabs for the same slider position.
    A gain of 0 is a mute, so a stream never plays at a level nobody asked for."""
    g = max(0.0, min(1.0, float(gain)))
    return int(round((g ** (1.0 / 3.0)) * NORM)), bool(muted) or g <= 0.0


def read_ctl(path):
    """``(gain, muted)`` out of the control file, or None when it cannot be read
    (absent, half-written, not JSON) - the caller keeps the level it had."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return max(0.0, min(1.0, float(data.get("gain", 1.0)))), bool(data.get("muted", False))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


_HEAD = re.compile(r"^Sink Input #(\d+)")
_VOL = re.compile(r"^\s*Volume:\s*[^:\s]+:\s*(\d+)\s*/")
_MUTE = re.compile(r"^\s*Mute:\s*(yes|no)\b")
_BIN = re.compile(r'^\s*application\.process\.binary\s*=\s*"([^"]*)"')


def parse_sink_inputs(text):
    """``pactl list sink-inputs`` -> ``[{index, volume, muted, binary}]``.
    ``volume`` is the FIRST channel's raw value (every stream of ours is set on
    all channels at once, so one channel says it); None when a line is absent."""
    out, cur = [], None
    for line in (text or "").splitlines():
        m = _HEAD.match(line)
        if m:
            cur = {"index": int(m.group(1)), "volume": None, "muted": None, "binary": ""}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = _VOL.match(line)
        if m and cur["volume"] is None:
            cur["volume"] = int(m.group(1))
            continue
        m = _MUTE.match(line)
        if m:
            cur["muted"] = m.group(1) == "yes"
            continue
        m = _BIN.match(line)
        if m:
            cur["binary"] = m.group(1)
    return out


def plan(inputs, volume, mute, binaries=BINARIES, slack=256):
    """The pactl argument lists that bring every stream of ours to
    ``(volume, mute)`` - nothing for a stream already there, and nothing ever
    for a stream that is not the game's or the menu's (WSLg's server is shared
    by every Linux program on the machine)."""
    cmds = []
    for s in inputs:
        if s.get("binary") not in binaries:
            continue
        if s.get("volume") is None or abs(s["volume"] - volume) > slack:
            cmds.append(["set-sink-input-volume", str(s["index"]), str(volume)])
        if s.get("muted") is None or s["muted"] != mute:
            cmds.append(["set-sink-input-mute", str(s["index"]), "1" if mute else "0"])
    return cmds


def say(msg):
    sys.stdout.write("%s jjpvol: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description="hold the JJP rig's streams at the app's Volume / Mute")
    ap.add_argument("--ctl", required=True, help="the app's audio_ctl.json, as a WSL path")
    ap.add_argument("--jail", default="/var/tmp/jjp_run")
    ap.add_argument("--pulse", default="unix:/mnt/wslg/PulseServer")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--once", action="store_true", help="one pass, then exit (a proof)")
    ap.add_argument("--binaries", default=",".join(BINARIES),
                    help="whose streams to hold (a proof names a silent stream of its own)")
    args = ap.parse_args(argv)
    binaries = tuple(b for b in args.binaries.split(",") if b)

    pactl = ["chroot", args.jail, "env", "PULSE_SERVER=" + args.pulse, "HOME=/root", "pactl"]
    want = (1.0, False)
    seen_mtime = object()
    said = None
    while True:
        if not os.path.ismount(args.jail):
            say("the jail is gone - done")
            return 0
        try:
            mtime = os.stat(args.ctl).st_mtime_ns
        except OSError:
            mtime = None
        if mtime != seen_mtime:
            seen_mtime = mtime
            got = read_ctl(args.ctl)
            if got is not None:
                want = got
        volume, mute = target_volume(*want)
        if (volume, mute) != said:
            said = (volume, mute)
            say("level %d%% of the game's own%s" % (round(100 * want[0]), ", MUTED" if mute else ""))
        try:
            r = subprocess.run(pactl + ["list", "sink-inputs"], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=10)
            for cmd in plan(parse_sink_inputs(r.stdout.decode("utf-8", "replace")),
                            volume, mute, binaries):
                subprocess.run(pactl + cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
                say("pactl " + " ".join(cmd))
        except (OSError, subprocess.SubprocessError) as exc:
            say("pactl failed: %s" % exc)
        if args.once:
            return 0
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
