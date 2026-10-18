"""PAD-603: a crash must not print the [event] awk program into the log.

watch.sh starts the event feed (tail | tr | $AWK '...') as a background job
and teardown ends it with kill -9. Left in bash's job table, that kill comes
back as a "Killed" job notice that quotes the whole pipeline - every line of
the awk program and its comments, about 90 lines, in the user's log right
after the game's crash report (venom_le 0.95). disown takes it out of the job
table (teardown's disown -a, which covers pausekeep.py and every other
helper it kills the same way), as bootcheck.sh and motorcheck.sh already do.
"""
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_event_filter import RIG  # noqa: E402


def _watch_lines():
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read().split("\n")


def test_teardown_disowns_every_job_before_killing():
    lines = _watch_lines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith("teardown() {")), None)
    assert start is not None, "watch.sh no longer has teardown()"
    body = []
    for ln in lines[start + 1:]:
        if ln.startswith("}"):
            break
        body.append(ln.strip())
    code = [ln for ln in body if ln and not ln.startswith("#")]
    disown = next((i for i, ln in enumerate(code)
                   if ln.startswith("disown -a")), None)
    assert disown is not None, (
        "teardown no longer disowns its jobs: each kill -9 below prints a "
        "'Killed' notice quoting the job, the event feed's whole awk program")
    first_kill = next(i for i, ln in enumerate(code) if "kill" in ln)
    assert disown < first_kill, "disown -a must come before the first kill"
    assert not any(ln.startswith("wait") for ln in code), (
        "teardown waits on a job, which disown -a takes out of its reach")


_SHAPE = r"""
tail -q -n 0 -F "$1" 2>/dev/null | tr -d '\000' | awk '
  # PAD603 COMMENT INSIDE THE PROGRAM
  { print }
' &
EVTPG=$!
[ "$2" = 1 ] && disown -a
sleep 0.3
kill -9 "$EVTPG" 2>/dev/null
pkill -9 -f "tail -q -n 0 -F $1" 2>/dev/null
sleep 0.3
echo done
"""


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash")
                    or not shutil.which("pkill"),
                    reason="needs a native bash with pkill")
@pytest.mark.parametrize("disown,leaks", [(0, True), (1, False)])
def test_disown_silences_the_killed_notice(tmp_path, disown, leaks):
    log = tmp_path / "feed.log"
    log.write_text("")
    out = subprocess.run(["bash", "-c", _SHAPE, "shape", str(log),
                          str(disown)], capture_output=True, text=True,
                         timeout=30)
    text = out.stdout + out.stderr
    assert "done" in text
    assert ("PAD603 COMMENT" in text) is leaks, text
