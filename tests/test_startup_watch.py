"""PAD-1474: a start-up held up by a WSL that stopped answering says where it
waits in the log and offers to restart WSL (core/startup_watch)."""

import os
import subprocess
import threading
import time

import pytest

from pinball_decryptor.core import startup_watch as sw


DUMP = '''Thread 0x0000b0c0 [Thread-53 (_readerthread)] (most recent call first):
  File "C:\\Python312\\Lib\\subprocess.py", line 1613 in _readerthread
  File "C:\\Python312\\Lib\\threading.py", line 1012 in run

Thread 0x00007af4 [pad-ui] (most recent call first):
  File "C:\\Python312\\Lib\\subprocess.py", line 1209 in wait
  File "C:\\Python312\\Lib\\subprocess.py", line 550 in run
  File "C:\\Users\\mike\\AppData\\Local\\Programs\\PAD\\pinball_decryptor\\core\\thing.py", line 42 in ask_wsl
  File "C:\\Users\\mike\\AppData\\Local\\Programs\\PAD\\pinball_decryptor\\app.py", line 400 in __init__
  File "C:\\Users\\mike\\AppData\\Local\\Programs\\PAD\\pinball_decryptor\\webui\\host.py", line 273 in _make_app
  File "C:\\Users\\mike\\AppData\\Local\\Programs\\PAD\\pinball_decryptor\\webui\\loop.py", line 187 in _run

Current thread 0x0000c3e4 (most recent call first):
  File "C:\\Python312\\Lib\\threading.py", line 359 in wait
  File "C:\\Users\\mike\\AppData\\Local\\Programs\\PAD\\pinball_decryptor\\webui\\host.py", line 300 in build
'''


def test_summary_names_the_app_frames_without_the_account():
    lines = sw.summarize(DUMP)
    text = "\n".join(lines)
    # the reader thread idles in the standard library: left out
    assert "_readerthread" not in text
    assert "  thread pad-ui:" in lines
    assert "    subprocess.py:1209 wait" in lines
    assert "    pinball_decryptor/core/thing.py:42 ask_wsl" in lines
    assert "    pinball_decryptor/app.py:400 __init__" in lines
    assert "  thread main:" in lines
    assert "mike" not in text and "AppData" not in text


def test_summary_is_capped():
    big = "\n".join(
        'Thread 0x%04x [t%d] (most recent call first):\n'
        '  File "x\\pinball_decryptor\\a.py", line 1 in f' % (i, i)
        for i in range(100))
    lines = sw.summarize(big, max_lines=10)
    assert len(lines) == 11 and lines[-1].endswith("(more in %s)" % sw.DUMP_NAME)


class _Fakes:
    def __init__(self, stuck=True, answers=(True,)):
        self.said = []
        self.asked = 0
        self.restarts = 0
        self.closed = 0
        self._stuck = stuck
        self._answers = list(answers)
        self.release = threading.Event()
        self.stall_logged = threading.Event()

    def say(self, text):
        self.said.append(text)
        if text.startswith("Start-up has taken"):
            self.stall_logged.set()

    def stuck(self):
        return self._stuck and not self.release.is_set()

    def ask(self):
        self.asked += 1
        return self._answers.pop(0) if self._answers else False

    def close(self):
        self.closed += 1
        self.release.set()

    def restart(self, say):
        self.restarts += 1
        say("restarted")
        self.release.set()          # WSL gone: the waiting start goes on
        return True


def _watch(tmp_path, f, stall=0.3, again=0.3):
    return sw.StartupWatch(str(tmp_path), f.say, stall_s=stall,
                           ask_again_s=again, stuck=f.stuck, ask=f.ask,
                           restart=f.restart, close=f.close)


def _wait_for(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_a_quick_start_logs_nothing_and_leaves_no_file(tmp_path):
    f = _Fakes()
    w = _watch(tmp_path, f, stall=5).start()
    w.done()
    time.sleep(0.2)
    assert f.said == [] and f.asked == 0
    assert not os.listdir(tmp_path)


def test_a_stall_on_a_stuck_wsl_logs_where_and_restarts_on_yes(tmp_path):
    f = _Fakes(stuck=True, answers=(True,))
    w = _watch(tmp_path, f).start()
    # the "app build" waits until WSL is restarted, like Mike's did
    assert f.release.wait(10)
    w.done()
    assert f.asked == 1 and f.restarts == 1
    assert any(s.startswith("Start-up has taken over") for s in f.said)
    # faulthandler's real dump of this process names this test's frames
    assert "    pinball_decryptor/core/startup_watch.py" in "\n".join(f.said)
    assert "Start-up: WSL is not answering, which is what the app is waiting on." in f.said
    assert "restarted" in f.said
    assert not os.path.exists(os.path.join(tmp_path, sw.DUMP_NAME))


def test_no_asks_again_later_while_still_stuck(tmp_path):
    f = _Fakes(stuck=True, answers=(False, True))
    w = _watch(tmp_path, f, again=0.3).start()
    assert f.release.wait(10)
    w.done()
    assert f.asked == 2 and f.restarts == 1
    assert "Start-up: WSL left as it is; still waiting for it." in f.said


def test_a_stall_with_wsl_answering_only_logs(tmp_path):
    f = _Fakes(stuck=False)
    w = _watch(tmp_path, f).start()
    # Block in one wait while faulthandler's thread dumps this process: it
    # walks every thread's frames without the GIL, and a _wait_for poll
    # changing them under it froze a macOS worker for good (PAD-1540).
    assert f.stall_logged.wait(10)
    time.sleep(0.3)
    w.done()
    assert f.asked == 0 and f.restarts == 0


def test_a_start_ended_mid_stall_is_logged_by_the_next(tmp_path):
    (tmp_path / sw.DUMP_NAME).write_text(DUMP, encoding="utf-8")
    f = _Fakes()
    w = _watch(tmp_path, f, stall=5).start()
    w.done()
    assert f.said[0].startswith("The last start of the app stalled")
    assert "    pinball_decryptor/core/thing.py:42 ask_wsl" in f.said
    assert not os.listdir(tmp_path)


def _runner(results):
    """A fake subprocess runner: each argv[1:] tuple -> 'timeout', an
    exception, or a return code."""
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        r = results.get(tuple(argv))
        if r == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout)
        if isinstance(r, Exception):
            raise r
        return subprocess.CompletedProcess(argv, r or 0, b"")
    return run, calls


@pytest.mark.skipif(os.name != "nt", reason="WSL is Windows-only")
def test_wsl_stuck_only_on_no_answer():
    run, _ = _runner({("wsl.exe", "-l", "--running", "-q"): "timeout"})
    assert sw.wsl_stuck(run)
    run, _ = _runner({("wsl.exe", "-l", "--running", "-q"): 1})
    assert not sw.wsl_stuck(run)          # answered, even with an error
    run, _ = _runner({("wsl.exe", "-l", "--running", "-q"): OSError("none")})
    assert not sw.wsl_stuck(run)          # no WSL at all


def test_restart_escalates_until_wsl_goes():
    said = []
    run, calls = _runner({("wsl.exe", "--shutdown"): "timeout",
                          ("wsl.exe", "--shutdown", "--force"): "timeout"})
    assert sw.restart_wsl(run, said.append)
    assert calls == [["wsl.exe", "--shutdown"],
                     ["wsl.exe", "--shutdown", "--force"],
                     ["taskkill", "/f", "/im", "wslservice.exe"]]
    assert said[-1].startswith("Start-up: WSL is down")


def test_restart_stops_at_the_first_that_works():
    said = []
    run, calls = _runner({})
    assert sw.restart_wsl(run, said.append)
    assert calls == [["wsl.exe", "--shutdown"]]


def test_restart_that_cannot_says_so():
    said = []
    run, _ = _runner({("wsl.exe", "--shutdown"): "timeout",
                      ("wsl.exe", "--shutdown", "--force"): 1,
                      ("taskkill", "/f", "/im", "wslservice.exe"): 128})
    assert not sw.restart_wsl(run, said.append)
    assert said[-1].startswith("Start-up: WSL could not be restarted")


def test_a_box_up_when_the_start_goes_on_by_itself_is_closed(tmp_path):
    f = _Fakes(stuck=True)
    opened = threading.Event()

    def ask():                      # the box: up until close() answers it
        f.asked += 1
        opened.set()
        f.release.wait(10)
        return False
    f.ask = ask
    w = _watch(tmp_path, f).start()
    assert opened.wait(10)
    w.done()                        # WSL came back and the app got built
    assert f.closed == 1
    assert _wait_for(lambda: "Start-up: it went on by itself; WSL left as it is." in f.said)
    assert f.restarts == 0
