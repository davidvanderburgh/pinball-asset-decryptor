"""PAD-603: a crash must not print the [event] awk program into the log.

watch.sh starts the event feed (tail | tr | $AWK '...') as a background job
and stop_all ends it with kill -9. Left in bash's job table, that kill comes
back as a "Killed" job notice that quotes the whole pipeline - every line of
the awk program and its comments, about 90 lines, in the user's log right
after the game's crash report (venom_le 0.95). disown takes it out of the job
table, the way bootcheck.sh and motorcheck.sh already do for theirs.
"""
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_event_filter import CLOSE, RIG  # noqa: E402


def _watch_lines():
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read().split("\n")


def test_event_feed_is_disowned_after_it_starts():
    lines = _watch_lines()
    close = [i for i, ln in enumerate(lines) if ln.strip() == CLOSE.strip()]
    assert close, "watch.sh no longer backgrounds the event feed with ' &"
    i = close[-1]
    assert lines[i + 1].strip() == "EVTPG=$!", lines[i + 1]
    # Up to the `fi` that closes the PAD_EVENTS block, a disown of that job.
    tail = []
    for ln in lines[i + 2:]:
        if ln.strip() == "fi":
            break
        tail.append(ln.strip())
    assert 'disown "$EVTPG"' in tail, (
        "the event feed is still in bash's job table: stop_all's kill -9 "
        "will print the whole awk program into the log")


_SHAPE = r"""
tail -q -n 0 -F "$1" 2>/dev/null | tr -d '\000' | awk '
  # PAD603 COMMENT INSIDE THE PROGRAM
  { print }
' &
EVTPG=$!
[ "$2" = 1 ] && disown "$EVTPG"
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
