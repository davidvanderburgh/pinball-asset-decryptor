"""PAD-832: the Mac's speaker starts only once the box's relay listens, and comes back.

A Mac user still heard nothing after the ``-ac`` fix: ffplay now started, and
the run was silent all the same, with nothing in the log.  The fmt file that
host_player waits for appears a moment BEFORE playaudio.sh starts padrelay.py,
and the container engine's port proxy accepts a connection with nothing behind
it yet and then hangs up.  ffplay took that for the end of the stream and
exited 0, and as it was one ``exec`` nothing ever started it again.  (Proven in
the Mac container on Docker Desktop: main's padbox.sh recorded 78 bytes, the
fixed one 18 MB of a game's sound.)

padbox.sh's host_player and relay_listening are run here with ``docker`` and
``ffplay`` replaced by shell functions; the "box" is a few files in a temp
directory: ``up`` (the container runs), ``listening`` (padrelay.py has bound
its port).  Fed on stdin for the reason test_padbox_build_watch.py gives.
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

PORT = 45997          # B3AD


def _function(name):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % name, body, re.S | re.M)
    assert m, "%s() not found in padbox.sh" % name
    return m.group(0)


# /proc/net/tcp as the box shows it. The ESTABLISHED row on our port is there
# on purpose: only a LISTEN (0A) row may count as "the relay is up".
_TABLE_DOWN = (
    "  sl  local_address rem_address   st tx_queue rx_queue\n"
    "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000\n"
    "   1: 020011AC:B3AD 010011AC:84D6 01 00000000:00000000\n")
_TABLE_UP = _TABLE_DOWN + (
    "   2: 00000000:B3AD 00000000:0000 0A 00000000:00000000\n")

_PRELUDE = r"""
set -u
D=%(dir)s
NAME=pad-test AUDIO_PORT=%(port)d PAD_AUDIO=1 PAD_BOX_RELAY_WAIT_S=%(wait)d
docker() {
  [ "$1" = exec ] || return 0
  case "$3" in
    cat) case "$4" in
           /pad/rootfs/dump/audio.fmt) echo "44100 2" ;;
           /proc/net/tcp) [ -f "$D/up" ] || return 1
                          if [ -f "$D/listening" ]; then printf '%%s' %(up)s
                          else printf '%%s' %(down)s; fi ;;
         esac ;;
    true) [ -f "$D/up" ] ;;
  esac
}
# ffplay: answers the option probe; otherwise notes whether the relay was
# listening when it connected, then plays what $D/play<N> says
ffplay() {
  case " $* " in *" -h "*) echo "  -ch_layout  <channel_layout>"; return 0 ;; esac
  n=$(( $(cat "$D/starts" 2>/dev/null || echo 0) + 1 )); echo $n > "$D/starts"
  if [ -f "$D/listening" ]; then echo "start $n relay-up" >> "$D/ffplay.log"
  else echo "start $n EARLY" >> "$D/ffplay.log"; fi
  case "$(cat "$D/play$n" 2>/dev/null || echo eof)" in
    eof) return 0 ;;                       # the stream ended at once
    long) exec sleep 31.832 ;;                 # a player that plays on
  esac
}
"""


def _run(d, body, wait=60, timeout=60):
    script = "\n".join([
        _PRELUDE % {"dir": _q(d), "port": PORT,
                    "wait": wait, "up": _q(_TABLE_UP), "down": _q(_TABLE_DOWN)},
        _function("ffplay_channel_args"),
        _function("relay_listening"),
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
def test_the_speaker_waits_for_the_relay_to_listen():
    d = _fresh_dir()
    # the relay comes up 1.5 s after the format is known; the player then plays on
    rc, text = _run(d, r"""
touch "$D/up"; echo long > "$D/play1"
( sleep 1.5; touch "$D/listening" ) &
host_player & HP=$!
for i in $(seq 1 80); do [ -f "$D/starts" ] && break; sleep 0.1; done
sleep 0.5; kill $HP; wait $HP 2>/dev/null
echo "HP-DONE"
""")
    log = _cat(d, "ffplay.log")
    assert "start 1 relay-up" in log, (log, text)
    assert "EARLY" not in log, (log, text)
    assert "HP-DONE" in text


@needs_bash
def test_an_ended_speaker_is_started_again_and_stopped_with_the_run():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up" "$D/listening"; echo eof > "$D/play1"; echo long > "$D/play2"
host_player & HP=$!
for i in $(seq 1 80); do [ "$(cat "$D/starts" 2>/dev/null)" = 2 ] && break; sleep 0.1; done
sleep 0.3; kill $HP; wait $HP 2>/dev/null
sleep 0.3
pgrep -f "sleep 31.832" >/dev/null && echo "PLAYER-LEFT-BEHIND"
echo "HP-DONE"
""")
    log = _cat(d, "ffplay.log")
    assert log.count("start") == 2, (log, text)
    assert "stopped (exit 0); started it again" in text
    assert "PLAYER-LEFT-BEHIND" not in text
    assert "HP-DONE" in text


@needs_bash
def test_a_box_that_stops_ends_the_speaker_without_a_restart():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up" "$D/listening"; echo eof > "$D/play1"
rm_up() { rm -f "$D/up"; }
# the box is gone by the time the player ends
ffplay_real=$(declare -f ffplay)
eval "${ffplay_real/ffplay ()/ffplay_inner ()}"
ffplay() { case " $* " in *" -h "*) ffplay_inner "$@"; return ;; esac
           ffplay_inner "$@"; rm_up; }
host_player
echo "HP-RC=$?"
""", timeout=30)
    assert "HP-RC=0" in text, text
    assert "started it again" not in text
    assert _cat(d, "ffplay.log").count("start") == 1


@needs_bash
def test_a_speaker_that_keeps_failing_is_given_up_on_and_said():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up" "$D/listening"
host_player
echo "HP-RC=$?"
""", timeout=60)
    assert "HP-RC=0" in text, text
    assert "stopped 5 times in a row" in text
    assert _cat(d, "ffplay.log").count("start") == 5


@needs_bash
def test_a_relay_that_never_listens_is_said_and_no_player_starts():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"
host_player
echo "HP-RC=$?"
""", wait=1, timeout=30)
    assert "never started listening on tcp/%d" % PORT in text, text
    assert _cat(d, "starts") == ""


@needs_bash
def test_only_a_listen_row_on_our_port_counts():
    d = _fresh_dir()
    rc, text = _run(d, r"""
touch "$D/up"
relay_listening && echo "DOWN-SAID-UP"
touch "$D/listening"
relay_listening && echo "UP-SAID-UP"
""", wait=1, timeout=30)
    assert "DOWN-SAID-UP" not in text, text
    assert "UP-SAID-UP" in text, text


def test_the_game_sound_count_crosses_into_the_box():
    # the Emulate tab's Audio row is read off the game's [aud] lines, which
    # only PAD_AUDIO_DUMP turns on; a Mac never passed it in ("not sampled")
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^for v in (.*?); do\n", body, re.S | re.M)
    assert m
    assert "PAD_AUDIO_DUMP" in m.group(1).split()
