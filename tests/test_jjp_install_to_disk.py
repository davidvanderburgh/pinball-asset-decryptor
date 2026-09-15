"""Item 123: a JJP install ISO straight onto the game's SSD - the pipeline around
``tools/jjp_emu/mkjjpmulti.py install`` (the tool's own tests are tests/test_mkjjpmulti.py and
its selftest): how the disk is handed to WSL and back, how the tool's lines drive the bar,
the phases and the verdict, and the manufacturer's wiring.  No WSL, no disk: a scripted
executor stands in."""
import os

import pytest

from pinball_decryptor.plugins.jjp import config
from pinball_decryptor.plugins.jjp.executor import CommandError, WslExecutor
from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer
from pinball_decryptor.plugins.jjp.pipeline import (RestoreToSSDPipeline,
                                                    _physical_drive_number)

DISK = r"\\.\PHYSICALDRIVE3"
TOOL_LINES = [
    "[card] install multi.iso -> /dev/sdc (Samsung SSD, usb, 120.03 GB) by /jjp/pad_install.sh",
    "[card] progress 1/26000000002 0.0% partition table",
    "[card] progress 9000000000/26000000002 34.6% sda3.ext4-ptcl-img -> /dev/sdc3",
    "[card] progress 26000000002/26000000002 100.0% done",
    "[card] written in 610 s",
    "ok: 7 partitions on /dev/sdc",
    "ok: ROOTA /dev/sdc3 has UUID d8223f69-d29a-474f-a837-0a11dccc27f2",
    "install verify: PASS (22 check(s), 0 failed)",
    "[card] install: DONE (/dev/sdc, 640 s)",
]


class _Wsl(WslExecutor):
    """The WSL executor with its three outside edges scripted: what lsblk answers before
    and after the attach, what the tool prints, and every host command it runs."""

    def __init__(self, before, after, lines, host_rc=0, mount_first=None):
        super().__init__()
        self._answers = [before, after]
        self._lines = lines
        self.host = []
        self.bash = []
        self.host_rc = host_rc
        # the answer to the FIRST `wsl --mount` when it should differ: (rc, stdout, stderr)
        self._mount_first = mount_first

    def run(self, bash_cmd, timeout=120):
        self.bash.append(bash_cmd)
        assert bash_cmd.startswith("lsblk")
        names = self._answers.pop(0) if self._answers else set()
        return "".join("%s disk\n" % n for n in sorted(names)) + "loop0 loop\n"

    def stream(self, bash_cmd, timeout=600):
        self.bash.append(bash_cmd)
        for line in self._lines:
            if isinstance(line, Exception):
                raise line
            yield line

    def run_host(self, args, timeout=60):
        self.host.append(args)
        if self._mount_first is not None and args.startswith("wsl --mount"):
            first, self._mount_first = self._mount_first, None
            return first
        if args.startswith("wsl --mount") and self.host_rc:
            return self.host_rc, "", "refused"
        return 0, "", ""

    def to_exec_path(self, host_path):
        return "/mnt/x/" + os.path.basename(host_path)


class _Sink:
    def __init__(self):
        self.log, self.phases, self.progress, self.done = [], [], [], []

    def cbs(self):
        return (lambda m, lvl="info": self.log.append((lvl, m)),
                self.phases.append,
                lambda a, b, msg="": self.progress.append((a, b, msg)),
                lambda ok, summary: self.done.append((ok, summary)))


def _run(tmp_path, ex, iso_name="multi.iso"):
    iso = tmp_path / iso_name
    iso.write_bytes(b"iso")
    sink = _Sink()
    p = RestoreToSSDPipeline(str(iso), DISK, *sink.cbs(), tool_path="/repo/tools/jjp_emu/mkjjpmulti.py",
                             executor=ex)
    p.run()
    return p, sink


def test_physical_drive_number():
    assert _physical_drive_number(r"\\.\PHYSICALDRIVE3") == 3
    assert _physical_drive_number(r"\\.\PhysicalDrive12 ") == 12
    assert _physical_drive_number("/dev/sdc") is None
    assert _physical_drive_number("") is None


def test_the_disk_goes_to_wsl_whole_and_the_tool_gets_the_new_device(tmp_path):
    ex = _Wsl({"sda", "sdb"}, {"sda", "sdb", "sdc"}, TOOL_LINES)
    p, sink = _run(tmp_path, ex)
    # the Write tab's sequence: stale mounts of the disk cleared, offline, attach bare, then -
    # after the tool - detach and back online, in that order
    assert ex.host[0] == 'wsl --unmount "%s"' % DISK
    assert 'Set-Disk -Number 3 -IsOffline $true' in ex.host[1]
    assert ex.host[2] == 'wsl --mount "%s" --bare' % DISK
    assert ex.host[3] == 'wsl --unmount "%s"' % DISK
    assert 'Set-Disk -Number 3 -IsOffline $false' in ex.host[4]
    assert len(ex.host) == 5
    # the tool: the ISO's WSL path, the device that appeared, --yes (the dialog confirmed)
    cmd = ex.bash[-1]
    assert cmd == "python3 /mnt/x/mkjjpmulti.py install --iso /mnt/x/multi.iso --disk /dev/sdc --yes"
    assert sink.done == [(True, sink.done[0][1])] and "ready for the machine" in sink.done[0][1]


def test_the_tools_lines_drive_the_bar_the_phases_and_the_log(tmp_path):
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES)
    p, sink = _run(tmp_path, ex)
    assert sink.phases == [0, 1, 2, 3]
    assert sink.progress == [(0, 100, "partition table"),
                             (34, 100, "sda3.ext4-ptcl-img -> /dev/sdc3"),
                             (100, 100, "done")]
    msgs = [m for _l, m in sink.log]
    assert "ok: 7 partitions on /dev/sdc" in msgs
    assert "install: DONE (/dev/sdc, 640 s)" in msgs
    assert not any(m.startswith("[card] progress") for m in msgs), "the meter never reaches the log"
    assert ("success", "install verify: PASS (22 check(s), 0 failed)") in sink.log


def test_a_fail_line_from_the_read_back_is_a_failed_run(tmp_path):
    lines = TOOL_LINES[:-2] + ["FAIL: grub boots slot a (curgrub) - b",
                               "install verify: FAIL (22 check(s), 1 failed)",
                               "[card] install: FAILED VERIFY (/dev/sdc, 640 s)"]
    ex = _Wsl({"sda"}, {"sda", "sdc"}, lines)
    p, sink = _run(tmp_path, ex)
    assert sink.done[0][0] is False
    assert "did not read back" in sink.done[0][1]
    assert ("error", "FAIL: grub boots slot a (curgrub) - b") in sink.log
    # the disk still goes back to Windows
    assert any(h.startswith("wsl --unmount") for h in ex.host)
    assert any("IsOffline $false" in h for h in ex.host)


def test_a_refusal_by_the_tool_ends_the_run_with_its_words(tmp_path):
    lines = ["[card] error: /dev/sdc is in use (/dev/sdc3 mounted on /mnt/x) - not a disk to wipe",
             CommandError("python3 ...", 2, "[card] error: /dev/sdc is in use (/dev/sdc3 mounted on /mnt/x) - not a disk to wipe")]
    ex = _Wsl({"sda"}, {"sda", "sdc"}, lines)
    p, sink = _run(tmp_path, ex)
    assert sink.done[0][0] is False
    assert "is in use" in sink.done[0][1]
    assert any(h.startswith("wsl --unmount") for h in ex.host)


def test_two_new_disks_is_a_refusal_before_anything_is_written(tmp_path):
    ex = _Wsl({"sda"}, {"sda", "sdc", "sdd"}, TOOL_LINES)
    p, sink = _run(tmp_path, ex)
    assert sink.done[0][0] is False
    assert "Could not tell which disk" in sink.done[0][1]
    assert not any(b.startswith("python3") for b in ex.bash), "the tool never ran"
    assert any(h.startswith("wsl --unmount") for h in ex.host), "the disk was still handed back"


def test_a_stale_wsl_mount_is_cleared_with_the_write_tabs_recovery(tmp_path):
    """ALREADY_MOUNTED from wsl --mount (a disk WSL still thinks it holds, after a WSL
    restart): wsl --shutdown, the disk offline again, one more attach - the Write tab's
    recovery, then the install runs as usual."""
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES,
              mount_first=(1, "", "Error code: Wsl/Service/AttachDisk/WSL_E_DISK_ALREADY_MOUNTED"))
    ex._answers = [{"sda"}, {"sda"}, {"sda", "sdc"}]          # lsblk: before, before again after the restart, after
    p, sink = _run(tmp_path, ex)
    assert sink.done[0][0] is True
    kinds = [h.split()[1] if h.startswith("wsl") else ("offline" if "$true" in h else "online") for h in ex.host]
    assert kinds == ["--unmount", "offline", "--mount", "--shutdown", "offline", "--mount", "--unmount", "online"]
    assert any("Stale WSL mount" in m for _l, m in sink.log)


def test_wsl_mount_refused_names_the_administrator_gate(tmp_path):
    ex = _Wsl({"sda"}, {"sda"}, TOOL_LINES, host_rc=1)
    p, sink = _run(tmp_path, ex)
    assert sink.done[0][0] is False
    assert "Administrator" in sink.done[0][1]
    assert not any(b.startswith("python3") for b in ex.bash)


def test_a_missing_iso_is_refused_before_the_disk_is_touched(tmp_path):
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES)
    sink = _Sink()
    p = RestoreToSSDPipeline(str(tmp_path / "gone.iso"), DISK, *sink.cbs(), tool_path="/t/mkjjpmulti.py",
                             executor=ex)
    p.run()
    assert sink.done[0][0] is False and "ISO not found" in sink.done[0][1]
    assert ex.host == []


def test_an_executor_without_a_linux_block_device_is_refused(tmp_path):
    class _Docker:
        def run_host(self, *a, **k):
            return 0, "", ""
    sink = _Sink()
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"iso")
    p = RestoreToSSDPipeline(str(iso), "/dev/disk4", *sink.cbs(), tool_path="/t/mkjjpmulti.py",
                             executor=_Docker())
    p.run()
    assert sink.done[0][0] is False and "USB install stick" in sink.done[0][1]


def test_the_manufacturer_offers_the_disk_as_a_second_place(monkeypatch):
    mfr = JJPManufacturer()
    assert [t[0] for t in mfr.flash_targets] == ["stick", "disk"]
    assert [t[2] for t in mfr.flash_targets] == ["usb_stick", "ssd"]
    assert mfr.install_to_disk_phases == tuple(config.RESTORE_TO_SSD_PHASES) == ("Attach", "Install", "Verify", "Detach")
    sink = _Sink()
    p = mfr.make_install_to_disk_pipeline("x.iso", DISK, *sink.cbs())
    assert isinstance(p, RestoreToSSDPipeline)
    assert p.iso_path == "x.iso" and p.device_path == DISK
    assert os.path.basename(p._tool) == "mkjjpmulti.py"
    # the tool sits in the checkout's tools/jjp_emu unless PAD_JJP_EMU_DIR moves it
    # (the test session points that at a rig-less directory)
    from pinball_decryptor.plugins.jjp.pipeline import _mkjjpmulti_path
    monkeypatch.delenv("PAD_JJP_EMU_DIR", raising=False)
    assert _mkjjpmulti_path().replace("\\", "/").endswith("tools/jjp_emu/mkjjpmulti.py")
    monkeypatch.setenv("PAD_JJP_EMU_DIR", "/elsewhere/jjp_emu")
    assert _mkjjpmulti_path().replace("\\", "/") == "/elsewhere/jjp_emu/mkjjpmulti.py"


def test_other_brands_offer_no_second_place():
    from pinball_decryptor.core.registry import Manufacturer
    assert Manufacturer.flash_targets == ()
    assert Manufacturer.install_to_disk_phases == ()
    with pytest.raises(NotImplementedError):
        # the base method, on a real instance (the class itself is abstract)
        Manufacturer.make_install_to_disk_pipeline(JJPManufacturer(), "x", "y", None, None, None, None)


def test_the_menu_only_and_one_image_writes_reach_the_tool_as_its_flags(tmp_path):
    """Item 124: the two partial writes are the tool's --menu-only and --image N --from ISO,
    the from-ISO mapped into WSL like the multi ISO; the done words say what stayed."""
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES)
    iso = tmp_path / "multi.iso"
    iso.write_bytes(b"iso")
    sink = _Sink()
    p = RestoreToSSDPipeline(str(iso), DISK, *sink.cbs(), tool_path="/t/mkjjpmulti.py", executor=ex, menu_only=True)
    assert p.mode == "menu"
    p.run()
    assert ex.bash[-1].endswith("--disk /dev/sdc --yes --menu-only")
    assert sink.done[0][0] is True and "boot menu" in sink.done[0][1] and "scores are as they were" in sink.done[0][1]
    new = tmp_path / "custom-v2.iso"
    new.write_bytes(b"iso")
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES)
    sink = _Sink()
    p = RestoreToSSDPipeline(str(iso), DISK, *sink.cbs(), tool_path="/t/mkjjpmulti.py", executor=ex, image=1, from_iso=str(new))
    assert p.mode == "image"
    p.run()
    assert ex.bash[-1].endswith("--disk /dev/sdc --yes --image 1 --from /mnt/x/custom-v2.iso")
    assert sink.done[0][0] is True and "Image 1" in sink.done[0][1] and "custom-v2.iso" in sink.done[0][1]
    # a missing from-ISO is refused before the disk is touched
    ex = _Wsl({"sda"}, {"sda", "sdc"}, TOOL_LINES)
    sink = _Sink()
    RestoreToSSDPipeline(str(iso), DISK, *sink.cbs(), tool_path="/t/mkjjpmulti.py", executor=ex, image=0,
                         from_iso=str(tmp_path / "gone.iso")).run()
    assert sink.done[0][0] is False and "was not found" in sink.done[0][1] and ex.host == []


def test_the_manufacturer_passes_the_partial_write_through():
    mfr = JJPManufacturer()
    sink = _Sink()
    p = mfr.make_install_to_disk_pipeline("x.iso", DISK, *sink.cbs(), menu_only=True)
    assert p.mode == "menu"
    p = mfr.make_install_to_disk_pipeline("x.iso", DISK, *sink.cbs(), image=1, from_iso="y.iso")
    assert (p.mode, p.image, p.from_iso) == ("image", 1, "y.iso")
    assert mfr.make_install_to_disk_pipeline("x.iso", DISK, *sink.cbs()).mode == "full"

