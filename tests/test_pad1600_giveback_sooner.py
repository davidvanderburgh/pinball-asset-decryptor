"""PAD-1600: freed space goes back to Windows sooner, without closing the app.

The slack is 5 GB or 10% of a disk file (was 20 GB), the look is daily (was
weekly) and due at once after a clean-up that freed more than the slack, and
the OPEN app gives back by itself at a quiet moment: nobody at the PC, no job
of its own on, and - with WSL paused - none of its own wsl.exe left open.
The fakes are test_pad1458_disk_giveback's."""

import time

import pytest

from pinball_decryptor.core import disk_giveback as g
from pinball_decryptor.core import space_keeper, wsl_disk

from tests.test_pad1458_disk_giveback import GB, Rig, _disk, _env, _sizes  # noqa: F401


def test_slack_is_5_gb_or_a_tenth_of_the_file():
    assert space_keeper.giveback_slack(0) == 5 * GB
    assert space_keeper.giveback_slack(30 * GB) == 5 * GB
    assert space_keeper.giveback_slack(200 * GB) == 20 * GB


@pytest.mark.parametrize("size,used,given", [
    (30 * GB, 24 * GB, True),       # 6 GB spare, slack 5 GB
    (30 * GB, 26 * GB, False),      # 4 GB spare
    (100 * GB, 92 * GB, False),     # 8 GB spare, slack 10 GB
    (100 * GB, 88 * GB, True),      # 12 GB spare
])
def test_each_disk_against_its_own_slack(tmp_path, size, used, given):
    rt = _disk(tmp_path, "PAD-Runtime", size, "/")
    rig = Rig(tmp_path, used={"/": used})
    g.run(disk_list=[rt], **rig.kw())
    assert (rig.compacted == [rt["vhdx"]]) is given


def test_a_big_clean_makes_it_due_at_once(tmp_path):
    big = [_disk(tmp_path, "PAD-Runtime", 60 * GB, "/")]
    now = time.time()
    space_keeper.record_giveback(checked=now - 3600)
    assert not g.due(now, disk_list=big)            # looked an hour ago
    assert not space_keeper.owe_giveback(4 * GB, now=now - 60)
    assert not g.due(now, disk_list=big)            # under the slack
    assert space_keeper.owe_giveback(10 * GB, now=now - 60)
    assert g.due(now, disk_list=big)
    # the look answers it: a skip that found nothing spare clears it too
    rig = Rig(tmp_path, used={"/": 58 * GB})
    assert g.run(now=now, disk_list=big, **rig.kw())["skipped"]
    assert "giveback_owed" not in space_keeper.load_state()
    assert not g.due(now + 60, disk_list=big)


def test_a_busy_look_keeps_it_owed(tmp_path):
    big = [_disk(tmp_path, "PAD-Runtime", 60 * GB, "/")]
    now = time.time()
    space_keeper.record_giveback(checked=now - 3600)
    space_keeper.owe_giveback(10 * GB, now=now - 60)
    rig = Rig(tmp_path, used={"/": 20 * GB}, busy_lines=["emulator qemu"])
    assert g.run(now=now, disk_list=big, **rig.kw())["busy"]
    assert g.due(now + 60, disk_list=big)


# ------------------------------------------------------------ the open app

class App:
    """The open app: its own job flag and the wsl.exe it started."""

    def __init__(self, own=(), own_for=0, busy=()):
        self.own = list(own)          # pids of its wsl.exe
        self.own_for = own_for        # looks until they end (-1: never)
        self.busy = list(busy)
        self.looks = 0
        self.slept = 0
        self.paused_at_last_look = None

    def own_calls(self):
        self.looks += 1
        self.paused_at_last_look = wsl_disk.wsl_is_paused()
        if self.own_for >= 0 and self.looks > self.own_for:
            return []
        return self.own

    def kw(self, rig):
        kw = rig.kw()
        host = kw.pop("busy_host")
        kw["busy_host"] = lambda strict=False: host()
        kw.update(app_busy=lambda: list(self.busy), own_calls=self.own_calls,
                  sleep=lambda s: setattr(self, "slept", self.slept + s))
        return kw


def test_open_app_waits_for_its_own_short_calls_then_gives_back(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    app = App(own=[501], own_for=3)                  # a status poll, 3 s
    rec = g.run(disk_list=[rt], **app.kw(rig))
    assert rig.compacted == [rt["vhdx"]] and rec["freed"] == 88 * GB
    assert app.slept == 3 and app.paused_at_last_look is True


def test_open_app_with_its_own_linux_program_open_leaves_it(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    app = App(own=[501], own_for=-1)                 # an emulator: never ends
    rec = g.run(disk_list=[rt], **app.kw(rig))
    assert rec == {"busy": ["the app's own Linux program is still open"]}
    assert rig.released == [] and rig.compacted == []
    assert app.slept == g.OWN_WSL_WAIT_S
    assert not wsl_disk.wsl_is_paused()              # the pause let go


def test_open_app_with_a_job_on_does_nothing(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    app = App(busy=["an extract, build or card write is running"])
    assert g.run(disk_list=[rt], **app.kw(rig))["busy"]
    assert rig.trimmed == 0 and rig.released == []


def test_a_job_started_during_the_trim_stops_it(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    app = App()
    kw = app.kw(rig)
    kw["trim"] = lambda: app.busy.append("a card write is running")
    assert g.run(disk_list=[rt], **kw)["busy"] == ["a card write is running"]
    assert rig.released == [] and rig.compacted == []


def test_windows_busy_leaves_the_apps_own_calls_to_the_app(tmp_path):
    b = str(tmp_path)
    # started by me (pid 1), and the second wsl.exe every wsl.exe starts
    procs = [(10, "wsl.exe", "", 1), (12, "wsl.exe", "", 10),
             (13, "wslhost.exe", "", 12)]
    assert g.windows_busy(procs=procs, me=1, board=b, windows=[])
    assert g.windows_busy(procs=procs, me=1, board=b, windows=[],
                          own_ok=True) == []
    other = procs + [(11, "wsl.exe", "", 99), (14, "wsl.exe", "", 11)]
    assert g.windows_busy(procs=other, me=1, board=b, windows=[], own_ok=True)
    assert g.own_wsl_calls(procs=other, me=1) == [10, 12]


def test_run_when_quiet_needs_the_pc_left_alone(tmp_path, monkeypatch):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    app = App()
    rec = g.run_when_quiet(app_busy=lambda: [], idle=lambda: 30,
                           disk_list=[rt], **{k: v for k, v in app.kw(rig).items()
                                              if k != "app_busy"})
    assert rec["busy"][0].startswith("the PC is in use")
    assert rig.trimmed == 0
    rec = g.run_when_quiet(app_busy=lambda: [], idle=lambda: g.QUIET_IDLE_S,
                           disk_list=[rt], **{k: v for k, v in app.kw(rig).items()
                                              if k != "app_busy"})
    assert rec["freed"] == 88 * GB
    # done: not due again until tomorrow, so the next quiet moment skips
    assert g.run_when_quiet(app_busy=lambda: [], idle=lambda: 9999,
                            disk_list=[rt]) == {"skipped": "not due"}


def test_the_window_says_the_new_rules():
    from pinball_decryptor.webui import shellx_disk
    assert "5 GB or 10%" in shellx_disk.AUTO_NOTE
    assert "20 GB" not in shellx_disk.AUTO_NOTE
    assert "week" not in shellx_disk.AUTO_NOTE


def test_the_windows_idle_minutes_are_the_giveback_s():
    from pinball_decryptor.webui import shellx_disk
    assert shellx_disk._GIVEBACK_IDLE_S == g.QUIET_IDLE_S


def test_the_shell_names_the_apps_own_jobs(tmp_path):
    """The open app's give-back asks the shell what of its own is at work:
    a running extract/build/write, or the disk window at work."""
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("shellx")
        assert svc._app_busy() == []
        w.window._running = True
        assert svc._app_busy() == ["an extract, build or card write is running"]
        w.window._running = False
        svc._disk = {"busy": True}
        assert svc._app_busy() == ["Manage disk space is at work"]
        svc._disk = None
        # under a test the tick never starts a real give-back
        svc._giveback_tick()
        assert getattr(svc, "_giveback_thread", None) is None
