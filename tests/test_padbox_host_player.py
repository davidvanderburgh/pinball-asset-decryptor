"""PAD-832 / PAD-1109: the Mac's speaker, how it is fed and how it comes back.

PAD-832: ffplay once connected to the box's published port before the relay
listened, took the hang-up for the end of the stream, and the run was silent.
PAD-1109: under Colima the published port reached the Mac through Lima's port
forwarder, which took the relay's whole stream at full rate while ffplay got
310 KB and then nothing. The speaker now reads the box's sound FIFO through
``docker exec ... padrelay.py --pipe`` piped into ``ffplay -i pipe:0``: no port.

padbox.sh's host_player is run here with ``docker`` and ``ffplay`` replaced by
shell functions; the "box" is a few files in a temp directory: ``up`` (the
container runs), ``feed<N>`` (what the N-th relay writes), ``play<N>`` (how
the N-th player behaves). Fed on stdin for the reason
test_padbox_build_watch.py gives.
"""
import os
import re
import subprocess

import pytest

from tests.conftest import HAS_BASH

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BOX = os.path.join(RIG, "docker", "padbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")


def _function(name):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % name, body, re.S | re.M)
    assert m, "%s() not found in padbox.sh" % name
    return m.group(0)


_PRELUDE = r"""
set -u
D=%(dir)s
NAME=pad-test PAD_AUDIO=1 BOX_FIFO=/pad/rootfs/dump/audio.fifo
BOX_CTL=/tmp/pad_audio_ctl.json PAD_AUDIO_CTL="$D/audio_ctl.json"
docker() {
  [ "$1" = exec ] || return 0
  shift
  case "$*" in
    *"cat /pad/rootfs/dump/audio.fmt") echo "44100 2" ;;
    *" true"|*"test -p /pad/rootfs/dump/audio.fifo") [ -f "$D/up" ] ;;
    *"pkill -f padrelay.py --pipe") echo "reap" >> "$D/events" ;;
    "pad-test python3 /pad/rig/padrelay.py --pipe "*)
       n=$(( $(cat "$D/relays" 2>/dev/null || echo 0) + 1 )); echo $n > "$D/relays"
       echo "relay $n: $*" >> "$D/events"
       cat "$D/feed$n" 2>/dev/null ;;
  esac
}
# env -i NAME=v... cmd: what env(1) does, for a cmd that is a function here.
# Only ever called as an element of host_player's pipeline, which is its own
# subshell, so the variables go in place: no further subshell, or the PID
# host_player kills would not be the player's (env(1) execs, keeping it)
env() {
  [ "${1:-}" = -i ] || { command env "$@"; return; }
  shift
  for v in $(compgen -e); do
    case $v in D|PATH) ;; *) unset "$v" ;; esac
  done
  while [ $# -gt 0 ] && [ "${1#*=}" != "$1" ]; do export "$1"; shift; done
  "$@"
}
# ffplay: answers the option probes; otherwise records its arguments, its
# environment and what came in on stdin, then plays as $D/play<N> says
ffplay() {
  case " $* " in
    *" -h "*) echo "  -ch_layout  <channel_layout>"; return 0 ;;
    *" -version "*) echo "ffplay version 8.0 Copyright"; return 0 ;;
  esac
  n=$(( $(cat "$D/starts" 2>/dev/null || echo 0) + 1 )); echo $n > "$D/starts"
  echo "player $n: $*" >> "$D/events"
  echo "sdl=${SDL_AUDIODRIVER:-} home=${HOME:-}" > "$D/env$n"
  cat > "$D/heard$n"
  case "$(cat "$D/play$n" 2>/dev/null || echo eof)" in
    eof) return 0 ;;                       # the stream ended
    long) exec -a "padtest-player-$D" sleep 31 ;;   # a player that plays on
  esac
}
"""


def _run(d, body, timeout=60):
    script = "\n".join([
        _PRELUDE % {"dir": _q(d)},
        _function("ffplay_channel_args"),
        _function("mac_meter"),
        _function("ffplay_status"),
        _function("mac_outputs"),
        _function("host_player"),
        body, "",
    ])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=timeout)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def _q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _fresh_dir():
    out = subprocess.run(["bash", "-c", "mktemp -d"], stdout=subprocess.PIPE,
                         timeout=30)
    return out.stdout.decode().strip()


def _cat(d, name):
    out = subprocess.run(["bash", "-c", "cat %s/%s 2>/dev/null" % (d, name)],
                         stdout=subprocess.PIPE, timeout=30)
    return out.stdout.decode("utf-8", "replace")


@needs_bash
def test_the_speaker_plays_the_box_fifo_through_docker_exec_not_a_port():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"; printf 'PCM-BYTES' > "$D/feed1"; echo long > "$D/play1"
host_player & HP=$!
for i in $(seq 1 80); do [ -s "$D/heard1" ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
echo "HP-DONE"
""")
    ev = _cat(d, "events")
    assert "relay 1: pad-test python3 /pad/rig/padrelay.py --pipe " \
           "/pad/rootfs/dump/audio.fifo /tmp/pad_audio_ctl.json" in ev, (ev, text)
    player = [l for l in ev.splitlines() if l.startswith("player 1:")][0]
    assert player.endswith("-f s16le -ar 44100 -ch_layout stereo -i pipe:0"), player
    assert "-loglevel info -stats" in player, player
    assert "tcp://" not in ev
    assert _cat(d, "heard1") == "PCM-BYTES"
    # a relay left from an earlier player is stopped before this one reads
    assert ev.index("reap") < ev.index("relay 1:")
    assert "docker exec" in text and "HP-DONE" in text


@needs_bash
def test_the_speaker_starts_clean_of_the_apps_environment_and_says_so():
    """PAD-1109: the stream arrived and ffplay took it at playback speed, yet
    nothing was heard, while the same ffplay from Terminal played a tone. The
    Mac's ffplay now starts in a clean environment, and the log names the
    variables of the app's it was spared."""
    d = _fresh_dir()
    rc, text = _run(d, r"""
export SDL_AUDIODRIVER=dummy PYTHONHOME=/Applications/X.app/Contents/Frameworks
touch "$D/up"; echo long > "$D/play1"
host_player & HP=$!
for i in $(seq 1 80); do [ -f "$D/env1" ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
""")
    assert "[box] speaker: started without the app's PYTHONHOME SDL_AUDIODRIVER" \
        in text, text
    assert "[box] speaker: ffplay" in text, text
    seen = _cat(d, "env1")
    assert seen.startswith("sdl= home=/"), (seen, text)


@needs_bash
def test_the_mac_meter_passes_the_stream_and_says_what_reached_the_player():
    """PAD-1109: the relay's count could not see a stream lost on its way to
    the Mac; this one counts what ffplay is actually handed."""
    d = _fresh_dir()
    script = "\n".join(["set -u", "D=%s" % _q(d), "PAD_METER_S=1",
                         _function("mac_meter"), r"""
( for i in 1 2 3; do head -c 65536 /dev/zero | tr '\0' 'x'; sleep 1.2; done ) |
    mac_meter > "$D/out"
echo "OUT=$(wc -c < "$D/out" | tr -d ' ')"
""", ""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    assert "OUT=196608" in text, text
    assert "[box] handed to the Mac's speaker so far:" in text, text
    assert "[box] handed to the Mac's speaker in all: 196608 bytes" in text, text


@needs_bash
def test_ffplays_own_lines_pass_and_its_clock_is_sampled():
    """PAD-1109: ffplay's status line is its playback clock; sampled, not
    flooded, and every other line of its passed through."""
    d = _fresh_dir()
    script = "\n".join(["set -u", "PAD_FFSTAT_N=3", _function("ffplay_status"), r"""
printf 'Input #0, s16le, from pipe:0:\n' |
    cat - <(for i in 1 2 3 4 5 6 7; do printf '   %d.00 M-A:  0.000 fd=   0 aq=   %dKB vq=    0KB sq=    0B \r' $i $i; done) |
    ffplay_status 2>&1
""", ""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    lines = out.stdout.decode("utf-8", "replace").splitlines()
    assert lines[0] == "[box] ffplay: Input #0, s16le, from pipe:0:", lines
    played = [l for l in lines if l.startswith("[box] ffplay playing:")]
    assert [l.split()[3] for l in played] == ["1.00", "4.00", "7.00"], lines
    assert "aq= 4KB" in played[1], played


_PROFILER = """Audio:

    Devices:

        MacBook Pro Microphone:

          Default Input Device: Yes
          Input Channels: 1
          Manufacturer: Apple Inc.
          Current SampleRate: 48000
          Transport: Built-in
          Input Source: MacBook Pro Microphone

        MacBook Pro Speakers:

          Default Output Device: Yes
          Default System Output Device: Yes
          Manufacturer: Apple Inc.
          Output Channels: 2
          Current SampleRate: 48000
          Transport: Built-in
          Output Source: MacBook Pro Speakers

        Studio Display Speakers:

          Manufacturer: Apple Inc.
          Output Channels: 2
          Current SampleRate: 48000
          Transport: USB

"""


@needs_bash
def test_the_macs_outputs_are_listed_with_the_default_marked():
    d = _fresh_dir()
    script = "\n".join(["set -u", "D=%s" % _q(d), _function("mac_outputs"), r"""
uname() { echo Darwin; }
system_profiler() { cat "$D/profile"; }
mac_outputs
"""])
    with open(os.path.join(d, "profile"), "w", encoding="utf-8") as fh:
        fh.write(_PROFILER)
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    assert text.startswith("[box] speaker: Mac outputs: "), text
    assert "MacBook Pro Speakers (MacBook Pro Speakers) [default]" in text, text
    assert "Studio Display Speakers" in text and "Microphone" not in text, text


@needs_bash
def test_off_a_mac_no_outputs_are_listed():
    d = _fresh_dir()
    script = "\n".join(["set -u", _function("mac_outputs"), r"""
uname() { echo Linux; }
mac_outputs; echo "RC=$?"
"""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=30)
    assert out.stdout.decode() == "RC=0\n", out.stdout


@needs_bash
def test_no_volume_file_hands_the_relay_none():
    d = _fresh_dir()
    rc, text = _run(d, r"""
PAD_AUDIO_CTL=
touch "$D/up"; echo long > "$D/play1"
host_player & HP=$!
for i in $(seq 1 80); do [ -f "$D/starts" ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
""")
    ev = _cat(d, "events")
    assert "--pipe /pad/rootfs/dump/audio.fifo" in ev, (ev, text)
    assert "/tmp/pad_audio_ctl.json" not in ev, ev


@needs_bash
def test_an_ended_speaker_is_started_again_and_stopped_with_the_run():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"; echo eof > "$D/play1"; echo long > "$D/play2"
host_player & HP=$!
for i in $(seq 1 80); do [ "$(cat "$D/starts" 2>/dev/null)" = 2 ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
sleep 0.3
# this test's own player only: another test's may be playing right now
pgrep -f "padtest-player-$D" >/dev/null && echo "PLAYER-LEFT-BEHIND"
echo "HP-DONE"
""")
    ev = _cat(d, "events")
    assert ev.count("player ") == 2 and ev.count("relay ") == 2, (ev, text)
    assert ev.count("reap") == 2, ev
    assert "stopped (exit 0); started it again" in text
    assert "PLAYER-LEFT-BEHIND" not in text
    assert "HP-DONE" in text


@needs_bash
def test_a_box_that_stops_ends_the_speaker_without_a_restart():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"; echo eof > "$D/play1"
ffplay_real=$(declare -f ffplay)
eval "${ffplay_real/ffplay ()/ffplay_inner ()}"
ffplay() { case " $* " in *" -h "*|*" -version "*) ffplay_inner "$@"; return ;; esac
           ffplay_inner "$@"; rm -f "$D/up"; }
host_player
echo "HP-RC=$?"
""", timeout=30)
    assert "HP-RC=0" in text, text
    assert "started it again" not in text
    assert _cat(d, "starts").strip() == "1"


@needs_bash
def test_a_speaker_that_keeps_failing_is_given_up_on_and_said():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"
host_player
echo "HP-RC=$?"
""", timeout=60)
    assert "HP-RC=0" in text, text
    assert "stopped 5 times in a row" in text
    assert _cat(d, "starts").strip() == "5"


def test_the_game_sound_count_crosses_into_the_box():
    # the Emulate tab's Audio row is read off the game's [aud] lines, which
    # only PAD_AUDIO_DUMP turns on; a Mac never passed it in ("not sampled")
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^for v in (.*?); do\n", body, re.S | re.M)
    assert m
    assert "PAD_AUDIO_DUMP" in m.group(1).split()


# ---- PAD-957: the tab's Volume and Mute reach the Mac's speaker -------------

_CTL_PRELUDE = r"""
set -u
D=%(dir)s
NAME=pad-test PAD_AUDIO=1 BOX_CTL=/tmp/pad_audio_ctl.json
PAD_AUDIO_CTL="$D/audio_ctl.json"
# docker exec -i -u 0 NAME sh -c CMD: the box takes a copy only once it is up
docker() {
  [ "$1" = exec ] || return 0
  [ -f "$D/up" ] || { cat >/dev/null; return 1; }
  cat > "$D/box_ctl"; echo push >> "$D/pushes"
}
"""


def _run_pusher(d, body, timeout=30):
    script = "\n".join([_CTL_PRELUDE % {"dir": _q(d)},
                        _function("ctl_pusher"), body, ""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=timeout)
    return out.returncode, out.stdout.decode("utf-8", "replace")


@needs_bash
def test_the_volume_file_is_copied_into_the_box_when_it_changes():
    d = _fresh_dir()
    rc, text = _run_pusher(d, r"""
echo '{"gain": 0.5, "muted": false}' > "$D/audio_ctl.json"
ctl_pusher & CP=$!
sleep 0.8; touch "$D/up"                    # the box comes up later
for i in $(seq 1 40); do [ -f "$D/pushes" ] && break; sleep 0.1; done
sleep 0.8                                   # unchanged: no second copy
echo '{"gain": 0.5, "muted": true}' > "$D/audio_ctl.json"
for i in $(seq 1 40); do [ "$(wc -l < "$D/pushes")" -ge 2 ] && break; sleep 0.1; done
kill $CP; wait $CP 2>/dev/null
echo "PUSHES=$(( $(wc -l < "$D/pushes") ))"   # BSD wc pads the count
""")
    assert "PUSHES=2" in text, text
    assert '"muted": true' in _cat(d, "box_ctl"), text


@needs_bash
def test_no_volume_file_or_a_silent_run_copies_nothing():
    d = _fresh_dir()
    rc, text = _run_pusher(d, r"""
touch "$D/up"
ctl_pusher & CP=$!                          # the file does not exist
sleep 0.8; kill $CP; wait $CP 2>/dev/null
PAD_AUDIO=0 ctl_pusher; echo "SILENT-RC=$?"
PAD_AUDIO_CTL= ctl_pusher; echo "UNSET-RC=$?"
""")
    assert _cat(d, "pushes") == "", text
    assert "SILENT-RC=0" in text and "UNSET-RC=0" in text, text


def test_the_relay_is_told_where_the_copy_is_and_the_bridge_is_not():
    with open(BOX, "rb") as fh:
        box = fh.read().decode("utf-8")
    assert '"$BOX_FIFO" "${PAD_AUDIO_CTL:+$BOX_CTL}"' in _function("host_player")
    assert "ctl_pusher & HOSTCTL=$!" in box
    # PAD-1109: no published sound port any more, so nothing on the Mac can
    # reach the box's FIFO except the docker exec reader
    assert "AUDIO_PORT" not in box and "tcp://" not in box
    with open(os.path.join(RIG, "playaudio.sh"), "rb") as fh:
        play = fh.read().decode("utf-8")
    relay = play[play.index('if [ "$SINK" = relay ]'):]
    relay_sink, win_sink = relay.split('if [ "$SINK" = win ]', 1)
    # the box keeps the FIFO and starts no listener of its own
    assert "padrelay.py" not in relay_sink.split("\nfi\n", 1)[0]
    # the Windows bridge's padplay.py scales its own; a relay that scaled
    # too would square the level
    assert "PAD_RELAY_CTL" not in play
    assert "--pipe" not in win_sink
