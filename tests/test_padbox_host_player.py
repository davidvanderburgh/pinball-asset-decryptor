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
BOX_CTL=/tmp/pad_ctl/audio_ctl.json PAD_AUDIO_CTL="$D/audio_ctl.json"
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
        _function("mac_pace"),
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
           "/pad/rootfs/dump/audio.fifo /tmp/pad_ctl/audio_ctl.json" in ev, (ev, text)
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
    the Mac; this one counts what ffplay is actually handed.

    Fed as a stream is, a little every tenth of a second: the Mac's dd says
    its count on SIGINFO only once its next read returns, so a feed in
    bursts a second apart left the count unsaid (PAD-1153)."""
    d = _fresh_dir()
    script = "\n".join(["set -u", "D=%s" % _q(d), "PAD_METER_S=1",
                         _function("mac_meter"), r"""
x=$(head -c 4096 /dev/zero | tr '\0' 'x')
( for i in $(seq 1 48); do printf '%s' "$x"; sleep 0.1; done ) |
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
    # the profile is written by bash itself: here bash may be WSL's, whose
    # temp dir Python cannot open
    script = "\n".join(["set -u", "PROFILE=%s" % _q(_PROFILER),
                        _function("mac_outputs"), r"""
uname() { echo Darwin; }
system_profiler() { printf '%s' "$PROFILE"; }
mac_outputs
"""])
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
def test_the_stream_is_paced_on_the_mac_by_the_apps_binary_when_given():
    """PAD-1109: PAD_PACER (the frozen app, --pace) sits between docker exec
    and ffplay; without one the stream goes straight through, as before."""
    d = _fresh_dir()
    rc, text = _run(d, r"""
{ echo '#!/bin/sh'; echo "echo \"pacer: \$*\" >> \"$D/events\""; echo cat; } > "$D/pacer"; chmod +x "$D/pacer"
PAD_PACER="$D/pacer"
touch "$D/up"; printf 'PCM-BYTES' > "$D/feed1"; echo long > "$D/play1"
host_player & HP=$!
for i in $(seq 1 80); do [ -s "$D/heard1" ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
""")
    ev = _cat(d, "events")
    assert "pacer: --pace 44100 2" in ev, (ev, text)
    # the three start together in one pipeline, so no order between them
    assert "relay 1:" in ev and "player 1:" in ev, ev
    assert _cat(d, "heard1") == "PCM-BYTES"
    assert "[box] speaker: the stream is paced on this Mac by " in text, text
    d2 = _fresh_dir()
    rc, text = _run(d2, r"""
PAD_PACER=
touch "$D/up"; printf 'PCM-BYTES' > "$D/feed1"; echo long > "$D/play1"
host_player & HP=$!
for i in $(seq 1 80); do [ -s "$D/heard1" ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
""")
    assert "no pacer on this Mac" in text, text
    assert _cat(d2, "heard1") == "PCM-BYTES"


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
    assert "/tmp/pad_ctl/audio_ctl.json" not in ev, ev


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


# ---- PAD-957 / PAD-1129: the control folder, both ways ---------------------
#
# ctl_sync runs here with `docker` a shell function and the box a folder: the
# REAL docker/boxctl.py runs on it (python3), as `docker exec -i` would run it
# in the box. $D/mac is the app's folder, $D/box the box's /tmp/pad_ctl.

BOXCTL = os.path.join(RIG, "docker", "boxctl.py")

_CTL_PRELUDE = r"""
set -u
D=%(dir)s
NAME=pad-test PAD_AUDIO=1 BOX_CTL_DIR=/tmp/pad_ctl
mkdir -p "$D/mac"
PAD_AUDIO_CTL="$D/mac/audio_ctl.json"
cat > "$D/boxctl.py" <<'BOXCTLEOF'
%(boxctl)s
BOXCTLEOF
docker() {
  case "$1" in
    ps) [ -f "$D/up" ] && echo pad-test; return 0 ;;
    exec) ;;
    *) return 0 ;;
  esac
  [ -f "$D/up" ] || return 1
  echo "exec ${*:2}" >> "$D/execs"
  python3 "$D/boxctl.py" "$D/box"
}
# for: waits up to 6 s for a condition
upto() { for _ in $(seq 1 60); do eval "$1" && return 0; sleep 0.1; done; return 1; }
# The run ends as padbox.sh ends it: the box goes first (docker run returns;
# the stopped container takes boxctl.py with it, and that ends the pipeline
# ctl_sync runs), then ctl_sync is killed. Killing ctl_sync alone leaves the
# pipeline running, holding this test's output open until its timeout.
box_down() { rm -f "$D/up"; pkill -f "$D/boxctl.py"; }
"""


def _box_up():
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^box_up\(\) \{.*\}\n", body, re.M)
    assert m
    return m.group(0)


def _run_sync(d, body, timeout=60):
    with open(BOXCTL, "rb") as fh:
        boxctl = fh.read().decode("utf-8")
    script = "\n".join([_CTL_PRELUDE % {"dir": _q(d), "boxctl": boxctl},
                        _box_up(), _function("ctl_feed"), _function("ctl_apply"),
                        _function("ctl_sync"), body, ""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=timeout)
    return out.returncode, out.stdout.decode("utf-8", "replace")


@needs_bash
def test_the_volume_file_and_clip_names_go_into_the_box_when_they_change():
    d = _fresh_dir()
    rc, text = _run_sync(d, r"""
echo '{"gain": 0.5, "muted": false}' > "$D/mac/audio_ctl.json"
printf '{\n "a": "Clip A"\n}\n' > "$D/mac/clip_names_0.json"
ctl_sync & CS=$!
sleep 0.8; touch "$D/up"                    # the box comes up later
upto 'grep -q 0.5 "$D/box/audio_ctl.json" 2>/dev/null' && echo IN-1
upto '[ -s "$D/box/clip_names_0.json" ]' && echo NAMES-IN
echo '{"gain": 0.5, "muted": true}' > "$D/mac/audio_ctl.json"
upto 'grep -q true "$D/box/audio_ctl.json"' && echo IN-2
box_down; kill $CS; wait $CS 2>/dev/null
echo "EXECS=$(( $(wc -l < "$D/execs") ))"   # BSD wc pads the count
cat "$D/box/clip_names_0.json"
""")
    assert "IN-1" in text and "IN-2" in text and "NAMES-IN" in text, text
    assert '"a": "Clip A"' in text, text
    assert "EXECS=1" in text, text        # one docker exec for the whole run
    assert "exec -i -u 0 pad-test python3 /pad/rig/docker/boxctl.py /tmp/pad_ctl" \
        in _cat(d, "execs"), text


@needs_bash
def test_the_windows_volume_and_mute_reach_the_tabs_file():
    # PAD-1129: the box's playfield window writes its copy (json.dump, no
    # newline, replaced in place); the tab's file follows and stays put
    d = _fresh_dir()
    rc, text = _run_sync(d, r"""
echo '{"gain": 1.0, "muted": false}' > "$D/mac/audio_ctl.json"
touch "$D/up"
ctl_sync & CS=$!
upto '[ -s "$D/box/audio_ctl.json" ]' && echo IN
printf '{"gain": 0.3, "muted": true}' > "$D/box/audio_ctl.json.pf.tmp"
mv -f "$D/box/audio_ctl.json.pf.tmp" "$D/box/audio_ctl.json"
upto 'grep -q 0.3 "$D/mac/audio_ctl.json"' && echo OUT
sleep 1.5                                   # and nothing bounces it back
box_down; kill $CS; wait $CS 2>/dev/null
echo "MAC=$(cat "$D/mac/audio_ctl.json")"
echo "BOX=$(cat "$D/box/audio_ctl.json")"
""")
    assert "IN" in text and "OUT" in text, text
    assert 'MAC={"gain": 0.3, "muted": true}' in text, text
    assert 'BOX={"gain": 0.3, "muted": true}' in text, text


@needs_bash
def test_restart_game_and_the_windows_records_reach_the_tab_for_its_slot():
    d = _fresh_dir()
    rc, text = _run_sync(d, r"""
PAD_SLOT=2
printf '{"x": 1}\n' > "$D/mac/clip_names_2.json"
touch "$D/up"
ctl_sync & CS=$!
upto '[ -d "$D/box" ]'
upto '[ -s "$D/box/clip_names_0.json" ]' && echo NAMES-IN
echo 0 > "$D/box/restart_game_0.req"
printf '{"clip": "a"}\n{"cl' >> "$D/box/clips_seen_0.jsonl"
printf '{"sid": 7}\n' >> "$D/box/sounds_seen_0.jsonl"
upto '[ -f "$D/mac/restart_game_2.req" ]' && echo REQ-OUT
upto '[ -s "$D/mac/sounds_seen_2.jsonl" ]' && echo SOUNDS-OUT
printf 'ip": "b"}\n' >> "$D/box/clips_seen_0.jsonl"
upto '[ "$(wc -l < "$D/mac/clips_seen_2.jsonl")" -ge 2 ]' && echo CLIPS-OUT
box_down; kill $CS; wait $CS 2>/dev/null
[ -e "$D/box/restart_game_0.req" ] || echo REQ-TAKEN
echo "REQ=$(cat "$D/mac/restart_game_2.req")"
cat "$D/mac/clips_seen_2.jsonl" "$D/mac/sounds_seen_2.jsonl"
""")
    for word in ("NAMES-IN", "REQ-OUT", "SOUNDS-OUT", "CLIPS-OUT", "REQ-TAKEN",
                 "REQ=2"):
        assert word in text, (word, text)
    assert '{"clip": "a"}\n{"clip": "b"}\n{"sid": 7}' in text, text
    assert "the playfield window asked for Restart game" in text, text


@needs_bash
def test_the_windows_stop_reaches_the_tab_for_its_slot():
    """PAD-1198: the window's Stop emulator (or its X) in the box, as the
    Mac app's stop_emulator_<slot>.req."""
    d = _fresh_dir()
    rc, text = _run_sync(d, r"""
PAD_SLOT=2
touch "$D/up"
ctl_sync & CS=$!
upto '[ -d "$D/box" ]'
echo 0 > "$D/box/stop_emulator_0.req"
upto '[ -f "$D/mac/stop_emulator_2.req" ]' && echo STOP-OUT
box_down; kill $CS; wait $CS 2>/dev/null
[ -e "$D/box/stop_emulator_0.req" ] || echo STOP-TAKEN
echo "STOP=$(cat "$D/mac/stop_emulator_2.req")"
""")
    for word in ("STOP-OUT", "STOP-TAKEN", "STOP=2"):
        assert word in text, (word, text)
    assert "the playfield window asked to stop the emulator" in text, text


@needs_bash
def test_no_volume_file_setting_syncs_nothing():
    d = _fresh_dir()
    rc, text = _run_sync(d, r"""
touch "$D/up"
PAD_AUDIO_CTL= ctl_sync; echo "UNSET-RC=$?"
""")
    assert "UNSET-RC=0" in text, text
    assert _cat(d, "execs") == "", text


def test_the_relay_and_the_window_share_the_boxs_copy():
    with open(BOX, "rb") as fh:
        box = fh.read().decode("utf-8")
    assert '"$BOX_FIFO" "${PAD_AUDIO_CTL:+$BOX_CTL}"' in _function("host_player")
    assert "BOX_CTL=$BOX_CTL_DIR/audio_ctl.json" in box
    # PAD-1129: the window inside the box is handed the copy
    assert '[ -n "${PAD_AUDIO_CTL:-}" ] && RUN_ARGS+=(-e "PAD_AUDIO_CTL=$BOX_CTL")' in box
    assert "ctl_sync & HOSTCTL=$!" in box
    assert "ctl_pusher" not in box
    # PAD-1109: no published sound port any more, so nothing on the Mac can
    # reach the box's FIFO except the docker exec reader
    assert "AUDIO_PORT" not in box and "tcp://" not in box
