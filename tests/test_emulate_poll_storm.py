"""The Emulate tab must not hammer WSL from a tab nobody opened.

2026-08-09, measured: 21 `wsl.exe` spawns in the first 45 s of app life on a
WARM machine, from the status poll alone.  Each spawn carries a 20 s timeout,
and the first wsl.exe after a Windows reboot boots the whole WSL VM — so a
cold start stacked up to ten concurrent WSL spawns, each contending with the
boot the others were waiting on, and the window sat "Not Responding" for tens
of seconds.  It was blamed on a GUI release, then an OneDrive stat, then the
log pane, before anyone counted the spawns.

Two properties keep it honest, and both are cheap to state:
  * never more than one status poll in flight;
  * an idle rig is polled slowly, not every two seconds forever.

These drive the poll logic directly rather than through a live Tk app: the
bug is in the scheduling, and scheduling is what is asserted.
"""

import pytest

from pinball_decryptor.gui.emulate_tab import EmulatePanel


class FakeTimer:
    """Records after() calls instead of running them."""

    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn=None, *a):
        self.scheduled.append((ms, fn))
        return "job%d" % len(self.scheduled)


class PollHarness:
    """The poll machinery of EmulatePanel with everything else stubbed."""

    POLL_MS = EmulatePanel.POLL_MS
    POLL_IDLE_MS = EmulatePanel.POLL_IDLE_MS
    _schedule_poll = EmulatePanel._schedule_poll
    _poll = EmulatePanel._poll

    def __init__(self):
        self._stopped = False
        self._poll_job = None
        self._poll_busy = False
        self._setup_busy = False
        self._last_up = False
        self._docker = "ok"
        #: Steady state for the cadence tests; the fast-first-poll test
        #: flips it off itself.
        self._polled_once = True
        self.spawns = 0
        self.timer = FakeTimer()

    def _timer(self):
        return self.timer


@pytest.fixture
def harness(monkeypatch):
    import pinball_decryptor.gui.emulate_tab as et
    h = PollHarness()
    monkeypatch.setattr(et, "rig_available", lambda: True)
    monkeypatch.setattr(et.sys, "platform", "win32")

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            h.spawns += 1          # a poll worker == one wsl.exe spawn

        def start(self):
            pass                   # never answers: the in-flight case

    monkeypatch.setattr(et.threading, "Thread", FakeThread)
    return h


def test_a_slow_poll_is_never_lapped_by_the_timer(harness):
    """THE REGRESSION.  Fire the poll repeatedly while the first worker is
    still out — as a cold WSL does — and only one spawn may exist.

    Pre-fix this spawns one wsl.exe per tick, which is the storm.
    """
    for _ in range(10):
        harness._poll()

    assert harness.spawns == 1, (
        "%d concurrent wsl.exe spawns — the poll is stacking again, which is "
        "what froze the window after a reboot" % harness.spawns)
    # It must keep re-arming, or the status would freeze at its last answer.
    assert harness.timer.scheduled, "the poll stopped rescheduling itself"


def test_the_poll_resumes_once_the_worker_answers(harness):
    harness._poll()
    assert harness.spawns == 1
    harness._poll_busy = False           # the worker came back
    harness._poll()
    assert harness.spawns == 2


def test_nothing_is_asked_of_wsl_while_the_setup_probe_is_out(harness):
    """The setup probe is itself a wsl.exe, and after a reboot it IS the VM
    boot — polling through it just stacks more spawns behind it."""
    harness._setup_busy = True
    for _ in range(5):
        harness._poll()
    assert harness.spawns == 0


def test_an_idle_rig_is_polled_slowly_and_a_live_one_quickly(harness):
    harness._last_up = False
    harness._schedule_poll()
    assert harness.timer.scheduled[-1][0] == EmulatePanel.POLL_IDLE_MS

    harness._last_up = True
    harness._schedule_poll()
    assert harness.timer.scheduled[-1][0] == EmulatePanel.POLL_MS
    assert EmulatePanel.POLL_IDLE_MS > EmulatePanel.POLL_MS


def test_the_first_poll_is_fast_then_settles(harness):
    """The first status answer is what fills the save-state list, and a
    user looks at that list the moment the app opens (tester, 2026-08-10:
    "when i load the app, the save states are empty until i refresh" - the
    10 s idle cadence made that true for ~11 s per launch).  Until one poll
    has answered, the retry is a short TIMER; the deferral branches spawn
    nothing, so the storm rule holds; and the first answer settles it back
    to the slow idle cadence."""
    harness._polled_once = False
    harness._schedule_poll()
    first = harness.timer.scheduled[-1][0]
    assert first < EmulatePanel.POLL_MS, (
        "the first poll waits %d ms - the slot list sits empty that long "
        "after every app start" % first)
    # Deferred behind the setup probe: fast retries, still ZERO spawns.
    harness._setup_busy = True
    for _ in range(5):
        harness._poll()
    assert harness.spawns == 0
    # One answered poll drops it to the slow idle cadence.
    harness._setup_busy = False
    harness._polled_once = True
    harness._schedule_poll()
    assert harness.timer.scheduled[-1][0] == EmulatePanel.POLL_IDLE_MS
