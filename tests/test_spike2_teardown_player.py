"""Closing the game window stops the run's Windows sound player too (PAD-510).

DragonRR closed the window on a Godzilla run whose game had gone quiet, so its
player kept giving up and being restarted. watch.sh's teardown SIGKILLs
playaudio.sh, so its EXIT trap (the one thing that stopped the Windows player)
never ran, and a player still on its way out when watch.sh exited left its WSL
stub behind for good. alive.sh counted it, and the Emulate tab offered only
"Stop emulator" for a run that had ended, until Stop (reproduced through the
app twice on main; the branch has Start back 5 s after the close).

The teardown now waits a moment for the polite exit and then stops what is
left: Windows first (pad_win_stop_player), the WSL stub second, because killing
only the stub leaves the Windows process running.

The behaviour tests run watch.sh's own teardown() with the rig's helpers
stubbed, so they need a POSIX bash (not Windows, where `bash` is WSL's).
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "watch.sh")),
                                reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8", newline="") as fh:
        return fh.read()


def _code(text):
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _teardown():
    m = re.search(r"^teardown\(\) \{\n.*?^\}\n", _read("watch.sh"), re.S | re.M)
    assert m, "watch.sh has no teardown() function"
    return m.group(0)


def test_one_definition_of_the_windows_player_stop():
    pp = _code(_read("padpath.sh"))
    m = re.search(r"^pad_win_stop_player\(\) \{[^\n]*\n.*?^\}$", pp, re.S | re.M)
    assert m, "padpath.sh has no pad_win_stop_player()"
    body = m.group(0)
    # this slot's player and nothing else: the script, the port, a python
    # (the query's own powershell.exe carries both strings in its command line)
    assert "'*padplay.py*'" in body
    assert "'* $port *'" in body
    assert "Name -like 'py*'" in body
    assert "PAD_AUDIO_PORT" in body
    assert "Stop-Process" in body
    # playaudio.sh's own EXIT trap uses the same query, not a copy
    pa = _code(_read("playaudio.sh"))
    assert 'win_kill() { pad_win_stop_player "$PORT"; }' in pa
    assert "Stop-Process" not in pa


def test_teardown_stops_the_player_after_the_relay_windows_first():
    body = _code(_teardown())
    relay = body.index("pad_pkill -9 -f 'padrelay\\.py'")
    win = body.index("pad_win_stop_player")
    stub = body.index("pad_pkill -9 -f 'padplay\\.py'")
    assert relay < win < stub


_STUBS = r"""
LOG=$1; ALIVE=$2; WSL=$3; S=$4
: > "$LOG"
pad_pids() { case "$*" in *padplay*) [ -e "$ALIVE" ] && echo 4242 ;; esac; return 0; }
pad_pkill() { echo "pkill $*" >> "$LOG"; }
pad_is_wsl() { [ "$WSL" = 1 ]; }
pad_win_stop_player() { echo "win_stop" >> "$LOG"; rm -f "$ALIVE"; }
pad_board_dir() { echo "$S"; }
pf_up() { false; }
sleep() { echo "sleep $*" >> "$LOG"; }
BOARD_RUN=; GAMEPG=; GAMEOUTTAIL=; HOSTPG=; VIDPG=; AUTOPG=; BALLPG=; SPEEDPG=
KEEPPG=; EVTPG=; TBLPG=; AUDPG=; PF_WINLAUNCH=0; CARD_MNT=; PAD_CARD=
PAD_SLOT=3; PAD_LOGDIR=$S; DROP=0
AUD_HOST=$S/audio.fifo; AUD_FMT_HOST=$S/audio.fmt
LED_HOST=$S/padled; LCD_HOST=$S/padlcd; ROOT=$S
"""

needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                                reason="needs a POSIX bash")


def _run(tmp_path, player_stays, wsl):
    s = tmp_path / "rig"
    s.mkdir()
    (s / "alive.sh").write_text("echo 'TOTAL STILL RUNNING    : 0  (clean)'\n",
                                encoding="utf-8")
    log, alive = tmp_path / "calls.log", tmp_path / "player"
    if player_stays:
        alive.write_text("", encoding="utf-8")
    script = _STUBS + _teardown() + "teardown\n"
    r = subprocess.run(["bash", "-c", script, "x", str(log), str(alive),
                        "1" if wsl else "0", str(s)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout, log.read_text(encoding="utf-8").splitlines()


@needs_bash
def test_a_player_that_stays_is_stopped_on_windows_then_swept(tmp_path):
    out, calls = _run(tmp_path, player_stays=True, wsl=True)
    assert "the sound player did not close itself" in out
    assert "win_stop" in calls
    stub = "pkill -9 -f padplay\\.py"
    assert stub in calls
    assert calls.index("win_stop") < calls.index(stub)
    # the polite exit got its moment first, and only a moment
    i = calls.index("pkill -9 -f padrelay\\.py")
    assert calls[i:calls.index("win_stop")].count("sleep 0.5") == 4


@needs_bash
def test_a_player_that_left_by_itself_costs_nothing(tmp_path):
    out, calls = _run(tmp_path, player_stays=False, wsl=True)
    assert "the sound player did not close itself" not in out
    assert "win_stop" not in calls
    assert "pkill -9 -f padplay\\.py" not in calls
    # no wait for it: the one half-second left is the census's own
    i = calls.index("pkill -9 -f padrelay\\.py")
    assert calls[i:].count("sleep 0.5") == 1


@needs_bash
def test_a_native_player_has_no_windows_side(tmp_path):
    out, calls = _run(tmp_path, player_stays=True, wsl=False)
    assert "win_stop" not in calls
    assert "pkill -9 -f padplay\\.py" in calls
