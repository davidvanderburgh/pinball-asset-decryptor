"""PAD-1458: the app's WSL disks give their freed space back to Windows when
the app closes - weekly at most, 20 GB spare, only when nothing runs, and
every check fails closed.  Everything outside (wsl.exe, the compact, the
process list) is a fake here; the real compact is proven on a real disk in
docs/plans/disk_giveback.md."""

import os
import time

import pytest

from pinball_decryptor.core import disk_giveback as g
from pinball_decryptor.core import space_keeper, wsl_disk

GB = 1024 ** 3


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPACE_STATE", str(tmp_path / "space_keeper.json"))
    for k in ("PAD_UI_CAPTURE", "PAD_UI_NO_RIG", "PAD_SPACE_KEEPER",
              "PAD_DISK_GIVEBACK", "PAD_GIVEBACK_SLACK_GB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: ("PAD-Runtime", "x"))


#: disk sizes by path: NO FILES ARE MADE (an NTFS truncate to 89 GB is not
#: sparse - it really takes the space, and filled C: with them once)
SIZES = {}


@pytest.fixture(autouse=True)
def _sizes(monkeypatch):
    SIZES.clear()
    monkeypatch.setattr(g, "_file_size", lambda p: SIZES[p])


def _disk(tmp_path, name, size, mount):
    p = str(tmp_path / (name.replace(" ", "_").replace("'", "") + ".vhdx"))
    SIZES[p] = size
    return {"name": name, "vhdx": p, "mount": mount, "size": size}


class Rig:
    """Fakes for one run: what Linux reports and what got compacted."""

    def __init__(self, tmp_path, used=None, busy_lines=(), done=True,
                 host=(), running=("PAD-Runtime",), shrink_to=GB):
        self.tmp_path = tmp_path
        self.used = used or {}
        self.busy_lines = list(busy_lines)
        self.done = done
        self.host = list(host)
        self.running = running
        self.shrink_to = shrink_to
        self.compacted, self.released, self.trimmed = [], [], 0
        self.fail32 = 0

    def wsl_script(self, s):
        out = ["DF %s %d" % (m, u // 1024) for m, u in self.used.items()]
        out += ["BUSY " + b for b in self.busy_lines]
        if self.done:
            out.append("SCAN_DONE")
        return "\n".join(out)

    def distros(self):
        if isinstance(self.running, Exception):
            raise self.running
        return list(self.running)

    def compact(self, vhdx):
        if self.fail32:
            self.fail32 -= 1
            raise wsl_disk.VirtDiskError(32, "held")
        self.compacted.append(vhdx)
        SIZES[vhdx] = self.shrink_to

    def kw(self):
        return dict(release=self.released.append, compact=self.compact,
                    busy_host=lambda: list(self.host), distros=self.distros,
                    wsl_script=self.wsl_script,
                    trim=lambda: setattr(self, "trimmed", self.trimmed + 1))


def test_due_reads_files_only_and_is_weekly(tmp_path, monkeypatch):
    big = [_disk(tmp_path, "PAD-Runtime", 30 * GB, "/")]
    small = [_disk(tmp_path, "rigs' data disk", 5 * GB, "/mnt/wsl/paddata")]
    now = time.time()
    assert g.due(now, st={}, disk_list=big)
    assert not g.due(now, st={}, disk_list=small)      # cannot hold 20 GB spare
    assert not g.due(now, st={"giveback_checked": now - 6 * 86400},
                     disk_list=big)
    assert g.due(now, st={"giveback_checked": now - 8 * 86400}, disk_list=big)
    monkeypatch.setenv("PAD_DISK_GIVEBACK", "0")
    assert not g.due(now, st={}, disk_list=big)


def test_the_keepers_automatic_box_turns_it_off(tmp_path):
    big = [_disk(tmp_path, "PAD-Runtime", 30 * GB, "/")]
    space_keeper.set_auto(False)
    assert not g.due(time.time(), disk_list=big)


def test_gives_back_only_the_disks_holding_20_gb_spare(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    dd = _disk(tmp_path, "rigs' data disk", 40 * GB, "/mnt/wsl/paddata")
    rig = Rig(tmp_path, used={"/": 65 * GB, "/mnt/wsl/paddata": 30 * GB})
    rec = g.run(disk_list=[rt, dd], **rig.kw())
    assert rig.compacted == [rt["vhdx"]]               # data disk: 10 GB spare
    assert rig.released == [rt["vhdx"]] and rig.trimmed == 1
    assert rec["freed"] == 88 * GB
    st = space_keeper.load_state()
    assert st["giveback"]["freed"] == 88 * GB
    assert st["giveback_checked"] == rec["at"]
    assert "Gave back 88.0 GiB to Windows just now." in space_keeper.summary()


@pytest.mark.parametrize("case", [
    dict(host=["a Linux program is still open (wsl.exe)"]),
    dict(host=["the app is open again"]),
    dict(running=("PAD-Runtime", "Ubuntu")),
    dict(running=("docker-desktop",)),
    dict(running=OSError("wsl.exe did not answer")),
    dict(busy_lines=["emulator qemu-system-arm"]),
    dict(busy_lines=["bash (PAD_SLOT=2)"]),
    dict(done=False),                                  # scan cut short
])
def test_anything_running_changes_nothing(tmp_path, case):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB}, **case)
    rec = g.run(disk_list=[rt], **rig.kw())
    assert rec.get("busy")
    assert rig.compacted == [] and rig.released == [] and rig.trimmed == 0
    assert SIZES[rt["vhdx"]] == 89 * GB
    # not recorded as checked: the next close tries again
    assert "giveback_checked" not in space_keeper.load_state()


def test_a_wsl_scan_that_errors_is_busy(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path)
    kw = rig.kw()
    kw["wsl_script"] = lambda s: (_ for _ in ()).throw(OSError("timed out"))
    assert g.run(disk_list=[rt], **kw)["busy"]
    assert rig.compacted == []


def test_the_app_reopened_after_the_trim_stops_it(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    kw = rig.kw()
    calls = []

    def host():
        calls.append(1)
        return [] if len(calls) == 1 else ["the app is open again"]
    kw["busy_host"] = host
    assert g.run(disk_list=[rt], **kw)["busy"] == ["the app is open again"]
    assert rig.trimmed == 1 and rig.compacted == []


def test_wsl_taking_the_disk_back_is_retried(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    rig.fail32 = 2
    rec = g.run(disk_list=[rt], **rig.kw())
    assert rig.compacted == [rt["vhdx"]] and len(rig.released) == 3
    assert rec["freed"] == 88 * GB


def test_nothing_spare_starts_the_week_again(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 30 * GB, "/")
    rig = Rig(tmp_path, used={"/": 25 * GB})
    assert g.run(disk_list=[rt], **rig.kw())["skipped"]
    assert space_keeper.load_state()["giveback_checked"] > 0
    assert rig.compacted == []
    assert "Gave back" not in space_keeper.summary()


def test_not_mounted_disk_is_skipped(tmp_path):
    cs = _disk(tmp_path, "card store", 60 * GB, "/mnt/wsl/cards")
    rig = Rig(tmp_path, used={})
    assert g.run(disk_list=[cs], **rig.kw())["skipped"]
    assert rig.compacted == []


def test_dry_run_compacts_nothing(tmp_path):
    rt = _disk(tmp_path, "PAD-Runtime", 89 * GB, "/")
    rig = Rig(tmp_path, used={"/": 10 * GB})
    assert g.run(dry_run=True, force=True, disk_list=[rt],
                 **rig.kw()) == {"would": ["PAD-Runtime"]}
    assert rig.compacted == [] and rig.trimmed == 0


def test_parse_scan_fails_closed():
    used, busy = g.parse_scan("DF / 1024\nDF /mnt/wsl/cards 2048\nSCAN_DONE")
    assert used == {"/": 1024 * 1024, "/mnt/wsl/cards": 2048 * 1024}
    assert busy == []
    assert g.parse_scan("DF / 1024")[1] == ["Linux could not be checked"]
    assert g.parse_scan("BUSY emulator qemu\nSCAN_DONE")[1] == ["emulator qemu"]


def test_scan_script_names_each_mount():
    s = g.scan_script(["/", "/mnt/wsl/paddata"])
    assert "for m in '/' '/mnt/wsl/paddata'; do" in s
    assert "SCAN_DONE" in s and "@MOUNTS@" not in s


def test_windows_busy(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    b = str(board)
    assert g.windows_busy(procs=[(10, "explorer.exe", "")], me=1, board=b,
                          windows=[]) == []
    assert g.windows_busy(procs=[(10, "wsl.exe", "")], me=1, board=b,
                          windows=[])
    procs = [(10, "pythonw.exe", ""), (11, "msedge.exe", ""),
             (12, "python.exe", "")]
    assert g.windows_busy(procs=procs, me=1, board=b, windows=[10]) == \
        ["the app is open again"]
    # a browser tab titled like the app is not the app; another Python with
    # no app window (an MCP helper, a script) is not either
    assert g.windows_busy(procs=procs, me=1, board=b, windows=[11]) == []
    assert g.windows_busy(procs=procs, me=1, board=b, windows=[]) == []
    (board / "PAD-9.lock").write_text("x")
    assert g.windows_busy(procs=[], me=1, board=b, windows=[])
    old = time.time() - 3600
    os.utime(board / "PAD-9.lock", (old, old))
    assert g.windows_busy(procs=[], me=1, board=b, windows=[]) == []


def test_start_after_close_only_when_due(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(g, "due", lambda: False)
    assert g.start_after_close(
        pid=42, popen=lambda *a, **k: started.append(a)) is False
    assert started == []
    monkeypatch.setattr(g, "due", lambda: True)
    assert g.start_after_close(pid=42,
                               popen=lambda *a, **k: started.append(a[0]))
    assert started[0][-2:] == ["--disk-giveback", "42"]


def test_helper_waits_then_runs(monkeypatch):
    seen = []
    monkeypatch.setattr(g, "_wait_pid", lambda pid, t: seen.append(pid))
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    monkeypatch.setattr(g, "run", lambda: seen.append("run"))
    assert g.helper_main(["x", "--disk-giveback", "77"]) == 0
    assert seen == [77, "run"]


def test_giveback_sentence_totals():
    now = time.time()
    st = {"giveback": {"at": now - 7200, "freed": 23 * GB}}
    assert space_keeper.giveback_sentence(st, now) == \
        "Gave back 23.0 GiB to Windows 2 hours ago."
    st["giveback_total"] = 40 * GB
    assert "(40.0 GiB in all)" in space_keeper.giveback_sentence(st, now)
    assert space_keeper.giveback_sentence({}, now) == ""


def test_reclaim_compacts_without_administrator(tmp_path, monkeypatch):
    """Not elevated, Reclaim's compact goes through virtdisk, not diskpart."""
    from pinball_decryptor.core import admin
    monkeypatch.setattr(admin, "is_admin", lambda: False)
    seen = []
    monkeypatch.setattr(wsl_disk, "_shutdown_until_free",
                        lambda v, p=None: seen.append(("free", v)))
    monkeypatch.setattr(wsl_disk, "virtdisk_compact",
                        lambda v: seen.append(("compact", v)))
    monkeypatch.setattr(wsl_disk.subprocess, "run",
                        lambda *a, **k: pytest.fail("diskpart ran"))
    wsl_disk._compact("C:/x/ext4.vhdx")
    assert seen == [("free", "C:/x/ext4.vhdx"), ("compact", "C:/x/ext4.vhdx")]


def test_reclaim_retries_a_held_disk_then_says_what_to_close(monkeypatch):
    from pinball_decryptor.core import admin
    monkeypatch.setattr(admin, "is_admin", lambda: False)
    monkeypatch.setattr(wsl_disk, "_shutdown_until_free", lambda v, p=None: 0)

    def held(v):
        raise wsl_disk.VirtDiskError(32, "held")
    monkeypatch.setattr(wsl_disk, "virtdisk_compact", held)
    with pytest.raises(wsl_disk.WslDiskError, match="Close anything else"):
        wsl_disk._compact("C:/x/ext4.vhdx")


def test_summary_before_the_keepers_first_run_is_the_giveback_alone():
    now = time.time()
    st = {"giveback": {"at": now - 30, "freed": 23 * GB}}
    assert space_keeper.summary(st, now) == \
        "Gave back 23.0 GiB to Windows just now."
    st["checked"] = now - 60
    assert space_keeper.summary(st, now).endswith(
        "nothing needed removing. Gave back 23.0 GiB to Windows just now.")
