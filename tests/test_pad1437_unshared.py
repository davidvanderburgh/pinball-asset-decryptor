"""PAD-1437: a PC whose Windows cannot open the run's files over
\\\\wsl.localhost at all (Mike St P, v1.512.5: every table, every start, the
game up on its LCD, WSL reading padled with its mark). The run used to be
stopped as "WSL's link is stuck" (PAD-1247); it now plays through wsl.exe:
padlink.py pushes the blocks and the few files beside them are fetched and
put through WSL."""
import io
import os
import sys
import tarfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "vpx"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu"))
pc = pytest.importorskip("padcontroller")

MAGIC = b"PLED"


def _tar(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _rig(tmp_path, share=False):
    rig = pc.Rig.__new__(pc.Rig)
    rig.distro, rig.root, rig.slot = "PAD-Runtime", "/mnt/wsl/paddata/spike2/padslots/1/root", 1
    rig.dump = str(tmp_path / "unreachable" / "dump")         # nothing there: Windows cannot open it
    rig.how = "rig board slot 1 (jaws_le)"
    rig.share = share
    rig.local_dir = lambda: str(tmp_path / "fetched")
    return rig


class Runner:
    def __init__(self, out=b"", rc=0):
        self.calls, self.out, self.rc = [], out, rc

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.out(cmd) if callable(self.out) else self.out
        return pc.subprocess.CompletedProcess(cmd, self.rc, out, b"")


def test_the_tables_are_fetched_through_wsl_when_the_share_cannot_be_opened(tmp_path):
    rig = _rig(tmp_path)
    run = Runner(_tar({"jaws_le/switch_list.txt": b"12 x 3 4 sw\n", "jaws_le/led_io.txt": b""}))
    where = rig.tables_dir("jaws_le", runner=run)
    assert open(os.path.join(where, "switch_list.txt")).read() == "12 x 3 4 sw\n"
    cmd = run.calls[-1]
    assert cmd[:5] == ["wsl.exe", "-d", "PAD-Runtime", "-e", "sh"]
    assert cmd[-2:] == ["/mnt/wsl/paddata/spike2/padslots/1/root/dump/tables", "jaws_le"]
    assert "-u" not in cmd                       # the default user, as the share would read it
    rig.tables_dir("jaws_le", runner=run)        # fresh enough: not fetched again at once
    assert len(run.calls) == 1


def test_a_fetched_file_that_would_land_outside_its_folder_is_refused(tmp_path):
    rig = _rig(tmp_path)
    assert rig.fetch("/x", ["a"], str(tmp_path / "in"), runner=Runner(_tar({"../evil": b"x"}))) is False
    assert not (tmp_path / "evil").exists()


def test_a_share_that_works_reads_the_tables_where_they_are(tmp_path):
    rig = _rig(tmp_path, share=True)
    run = Runner()
    assert rig.tables_dir("jaws_le", runner=run) == os.path.join(rig.dump, "tables", "jaws_le")
    assert run.calls == []


def test_ballfeed_off_and_the_pause_flag_go_through_wsl(tmp_path):
    rig = _rig(tmp_path)
    run = Runner()
    assert rig.ballfeed_off(True, runner=run)
    assert "echo PAD.Controller" in run.calls[-1][-3]
    assert run.calls[-1][-1] == rig.root + "/dump/ballfeed.off"
    assert rig.ballfeed_off(False, runner=run)
    assert run.calls[-1][-3].startswith("rm -f")
    read = Runner(b"\1\2\3\4")
    assert rig.wsl_read("padsw", 4, runner=read) == b"\1\2\3\4"
    assert read.calls[-1][-4:] == ["head", "-c", "4", rig.root + "/dump/padsw"]
    assert rig.wsl_read("padsw", 4, runner=Runner(rc=1)) is None


def test_switch_ids_read_the_fetched_switch_list(tmp_path, monkeypatch):
    rig = _rig(tmp_path)
    monkeypatch.setattr(rig, "seed_switch_list_wsl", lambda title: None)
    monkeypatch.setattr(rig, "tables_dir", lambda title: str(tmp_path / "t"))
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "switch_list.txt").write_text("57 a 9 3 left_ramp\n")
    assert rig.switch_ids("jaws_le") == {(9, 3): 57}


class FakeLink:
    HELLO_S = 20.0
    made = []

    def __init__(self, rig):
        self.rig, self.state, self.why, self.held, self.got = rig, "starting", "", {}, None
        self.closed = False
        self.news = pc.threading.Event()
        FakeLink.made.append(self)

    def blocks(self):
        return self.got

    def set(self, sw, level):
        self.held[sw] = level

    def close(self):
        self.closed = True
        self.state = "down"


class Launch:
    slot = 1
    logfile = ""

    def __init__(self):
        self.stopped = 0

    def alive(self):
        return True

    def stop(self):
        self.stopped += 1


@pytest.fixture
def starting(tmp_path, monkeypatch):
    said, ended, attached, asked = [], [], [], []
    monkeypatch.setattr(pc, "log", said.append)
    monkeypatch.setattr(pc, "RigLink", FakeLink)
    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc, "LINK_ON", True)
    monkeypatch.setattr(pc, "SHARE_ON", True)
    FakeLink.made = []
    b = pc.Bridge()
    b.title = "jaws_le"
    b.running = True
    b.launch, b.rig = Launch(), _rig(tmp_path, share=True)
    b.start_t = time.monotonic()
    b._board_t = time.monotonic() - b.SHARE_PROBE_S - 1
    monkeypatch.setattr(b, "_loading_end", lambda word, took=None: ended.append(word))
    monkeypatch.setattr(b, "_attach", lambda data, pipe=None: attached.append((data, pipe)))
    in_wsl = {"answer": True}

    def block_in_wsl(rig):
        asked.append(1)
        return in_wsl["answer"]
    monkeypatch.setattr(pc, "block_in_wsl", block_in_wsl)
    return b, said, ended, attached, asked, in_wsl


def test_a_run_windows_cannot_open_plays_through_wsl_instead_of_stopping(starting):
    b, said, ended, attached, asked, _ = starting
    b._poll_starting()
    assert b.rig.share is False and len(FakeLink.made) == 1
    assert any("through WSL instead (PAD-1437)" in s for s in said)
    assert ended == [] and b.launch.stopped == 0
    b._poll_starting()                                         # the link not up yet: waits
    assert attached == []
    link = FakeLink.made[0]
    link.got = (MAGIC + b"\0" * 60, b"\0" * 8)
    b._poll_starting()
    assert attached == [(link.got[0], link)]
    assert b._unshared is None


def test_a_link_that_cannot_come_up_either_stops_the_run_as_before(starting):
    b, said, ended, attached, asked, _ = starting
    b._poll_starting()
    FakeLink.made[0].state, FakeLink.made[0].why = "down", "no HELLO in 20 s"
    b._poll_starting()
    assert ended == ["failed " + pc.WSL_STUCK] and attached == []
    assert b.launch is None and b.rig is None
    assert "neither Windows' share nor wsl.exe" in said[-1]


def test_wsl_is_not_asked_before_the_game_could_be_up(starting):
    b, said, ended, attached, asked, _ = starting
    b._board_t = time.monotonic()
    b._poll_starting()
    assert asked == [] and FakeLink.made == []


def test_a_game_wsl_has_no_block_for_yet_is_asked_again_later_not_every_second(starting):
    b, said, ended, attached, asked, in_wsl = starting
    in_wsl["answer"] = False
    b._poll_starting()
    b._poll_starting()
    assert asked == [1] and FakeLink.made == [] and b.rig.share is True


def test_a_share_that_catches_up_attaches_the_usual_way(starting, tmp_path, monkeypatch):
    b, said, ended, attached, asked, _ = starting
    led = tmp_path / "padled"
    monkeypatch.setattr(b.rig, "led_path", lambda: str(led))

    def up_now(rig):
        led.write_bytes(MAGIC + b"\0" * 60)          # the game opened it as WSL was asked
        return True
    monkeypatch.setattr(pc, "block_in_wsl", up_now)
    b._poll_starting()
    assert attached and attached[0][1] is None and FakeLink.made == []
    assert b.rig.share is True


def test_a_dropped_link_of_a_run_through_wsl_is_started_again(tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(pc, "log", said.append)
    monkeypatch.setattr(pc, "RigLink", FakeLink)
    FakeLink.made = []
    b = pc.Bridge()
    b.rig = _rig(tmp_path)
    old = FakeLink(b.rig)
    old.held = {57: 1, 12: 0}
    old.state = "down"
    b.pipe = old
    b._poll_once()
    new = FakeLink.made[-1]
    assert b.pipe is new and new.held == {12: 0, 57: 1} and old.closed
    b.pipe.state = "down"
    b._poll_once()                                              # not again within RELINK_S
    assert len(FakeLink.made) == 2


def test_an_up_run_found_by_wsl_alone_is_attached_through_its_link(tmp_path, monkeypatch):
    """A game already running (the Emulate tab's) when the table opens."""
    monkeypatch.setattr(pc, "log", lambda *a: None)
    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc, "LINK_ON", True)
    monkeypatch.setattr(pc, "block_in_wsl", lambda rig: True)

    class UpLink(FakeLink):
        def blocks(self):
            return (MAGIC + b"\0" * 60, b"\0" * 8)
    monkeypatch.setattr(pc, "RigLink", UpLink)
    b = pc.Bridge()
    b.rig = _rig(tmp_path, share=True)
    got = []
    monkeypatch.setattr(b, "_attach", lambda data, pipe=None: got.append(pipe))
    assert b._attach_unshared(None, wait_s=1)
    assert isinstance(got[0], UpLink) and b.rig.share is False
    assert b._attach_unshared(MAGIC, wait_s=1) is False         # a share that reads it: not this path
