"""PAD-603: a run that ends on the CPU board's security check says so.

venom_le 0.95 (and other early builds) authenticate the machine: they send the
bus master `0d 05 <op> <4 bytes>` challenges, unscramble each 4-byte answer
with a TinyMT32 they mirror, and build the key for their own data out of the
answers. Only a real CPU board can answer, so the emulator does not - it is
copy protection - and the game decodes junk and crashes 15 s in. Later builds
of the same titles never ask. What the rig owes the user is the reason, in
words: hwshim names the request once, the event feed carries it to the pane,
and the exit report says what it means.

The same report used to quote the game's debug log whole, and that file
outlives every run in a slot: venom 0.95's crash came back labelled with a
FATAL of 2026-10-16 and "its own watchdog ended it". It now reads only what
this run wrote.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_event_filter import RIG, event_filter  # noqa: E402

AWK = shutil.which("awk")
BASH = shutil.which("bash")
SHIM_LINE = ("[security] the game asked the CPU board's security function "
             "(bus command 0x0d); this emulator cannot answer it")


def _src(name):
    with open(os.path.join(RIG, name), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _exit_report():
    watch = _src("watch.sh")
    at = watch.index('echo "[watch] the game exited. Last lines of its log:"')
    return watch[at:watch.index("\n        break\n", at)]


def test_the_shim_names_the_security_request_once():
    shim = _src("hwshim.c")
    at = shim.index("nb_req[0] == 0x0d && nb_req[1] == 0x05")
    block = shim[at:at + 600]
    assert "static int said" in block and "said = 1" in block
    # The C splits the literal over lines; join it back to compare.
    text = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', block))
    assert text.replace("\\n", "") == SHIM_LINE


def test_the_exit_report_keys_on_the_shims_own_words():
    report = _exit_report()
    m = re.search(r"grep -aqs '(.*?)' \"\$GUESTLOG\"", report)
    assert m, "the exit report no longer looks for the [security] line"
    pattern = m.group(1).replace("\\[", "[").replace("\\]", "]")
    assert pattern in SHIM_LINE
    assert "CHECKS THE MACHINE'S SECURITY HARDWARE" in report
    assert "Later code versions of this game do not make that check" in report


@pytest.mark.skipif(not AWK, reason="no awk")
def test_the_event_feed_carries_it_to_the_pane():
    lines = [SHIM_LINE, "[nb] TX len=7 0d05a38de44ed4", "just some line"]
    out = subprocess.run([AWK, event_filter()], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["[event] " + SHIM_LINE]


def test_the_debug_log_is_read_from_this_runs_mark_only():
    watch = _src("watch.sh")
    mark = watch.index("DBG_MARK=$(stat -c %s \"$ROOT/dump/debug_log.txt\"")
    launch = watch.index('bash "$RIG/run_game.sh" > "$LOG" 2>&1 &')
    assert mark < launch, "the mark must be taken before the game starts"
    report = _exit_report()
    assert "run_debug_log | grep -aq 'FATAL'" in report
    assert "run_debug_log | tail -3 | grep -aq 'GAME EXIT DISPATCH TIMEOUT'" \
        in report
    # Nothing in the report reads the whole file any more.
    assert not re.search(r'(grep|tail)[^\n|]*"\$ROOT/dump/debug_log\.txt"',
                         report)


def test_a_stale_game_out_is_not_quoted_as_this_runs_crash():
    report = _exit_report()
    assert ('if [ -n "${PAD_PIVOT:-}" ] && grep -aq \'\\[segv\\]\' '
            '"$GUESTLOG"') in report


@pytest.mark.skipif(sys.platform == "win32" or not BASH,
                    reason="needs a native bash")
def test_run_debug_log_returns_only_lines_written_after_the_mark(tmp_path):
    watch = _src("watch.sh")
    mark = next(ln for ln in watch.split("\n") if ln.startswith("DBG_MARK="))
    func = next(ln for ln in watch.split("\n")
                if ln.startswith("run_debug_log()"))
    dump = tmp_path / "dump"
    dump.mkdir()
    log = dump / "debug_log.txt"
    log.write_text("2026-10-16T20:35:38Z: ** FATAL: error 233 (old run).\n"
                   "GAME EXIT DISPATCH TIMEOUT\n")
    script = "\n".join([
        'ROOT="$1"', mark, func,
        'echo "2026-10-17T07:55:41Z: this run" >> "$ROOT/dump/debug_log.txt"',
        "run_debug_log",
    ])
    out = subprocess.run([BASH, "-c", script, "t", str(tmp_path)],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout == "2026-10-17T07:55:41Z: this run\n", out.stderr
