"""PAD-718: Transfer mods shows that it is working.

The comparisons and the copy run on a worker thread, and the footer used to
stay on the last job's 0% or 100% the whole time, so a user who didn't read
the log took the app for idle and clicked Transfer again.  Now each step
marks the footer busy (with the step's latest log line under the bar) and
the Mod Pack tab's Transfer button "Transferring…" until it ends, whichever
way it ends.
"""

import queue
from types import SimpleNamespace

from pinball_decryptor import app as app_mod
from pinball_decryptor.core.messages import LogMsg, UiCallMsg


class _Window:
    def __init__(self, running=False):
        self.tasks, self.status, self.tab = [], [], {}
        self._running = running

    def set_task(self, busy, status=None):
        self.tasks.append((busy, status))

    def set_status(self, text):
        self.status.append(text)

    def is_running(self):
        return self._running

    def service(self, ns):
        assert ns == "modpack"
        return SimpleNamespace(set=lambda **kw: self.tab.update(kw))


def _fake_app(window):
    me = SimpleNamespace(window=window, msg_queue=queue.Queue(),
                         root=SimpleNamespace(after=lambda ms, fn, *a: fn(*a)))
    me._transfer_task = lambda busy, status=None: app_mod.App._transfer_task(
        me, busy, status)
    me._transfer_status = lambda t: app_mod.App._transfer_status(me, t)
    return me


class _SyncThread:
    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_a_step_marks_the_footer_and_button_busy_until_it_ends(monkeypatch):
    monkeypatch.setattr(app_mod.threading, "Thread", _SyncThread)
    win = _Window()
    me = _fake_app(win)
    seen = {}

    def work():
        seen["during"] = (list(win.tasks), dict(win.tab), me._transfer_busy)
        return 7

    got = []
    app_mod.App._transfer_worker(me, work, got.append, "x",
                                 status="Transfer mods: comparing…")
    assert seen["during"] == ([(True, "Transfer mods: comparing…")],
                              {"transfer_busy": True}, True)
    assert got == [7]
    assert win.tasks[-1] == (False, None)
    assert win.tab == {"transfer_busy": False}
    assert me._transfer_busy is False


def test_a_failed_step_clears_the_busy_state_too(monkeypatch):
    monkeypatch.setattr(app_mod.threading, "Thread", _SyncThread)
    errors = []
    monkeypatch.setattr(app_mod.messagebox, "showerror",
                        lambda title, body: errors.append(title))
    win = _Window()
    me = _fake_app(win)

    def work():
        raise OSError("disk full")

    app_mod.App._transfer_worker(me, work, lambda r: None, "Compare failed")
    assert win.tasks[-1] == (False, "Transfer mods failed")
    assert win.tab == {"transfer_busy": False}
    assert errors == ["Compare failed"]


def test_each_log_line_is_also_the_status_under_the_bar():
    win = _Window()
    me = _fake_app(win)
    me._transfer_busy = True
    log = app_mod.App._transfer_log_cb(me)
    log("Comparing  video:\n 120 of 300", "info")
    msgs = [me.msg_queue.get_nowait() for _ in range(2)]
    assert isinstance(msgs[0], LogMsg) and msgs[0].text.startswith("Comparing")
    assert isinstance(msgs[1], UiCallMsg)
    msgs[1].fn()
    assert win.status == ["Comparing video: 120 of 300"]


def test_the_status_line_leaves_a_real_run_alone():
    win = _Window(running=True)
    me = _fake_app(win)
    me._transfer_busy = True
    app_mod.App._transfer_status(me, "Comparing")
    assert win.status == []
