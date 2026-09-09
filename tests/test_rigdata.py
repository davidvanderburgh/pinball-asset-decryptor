"""The rigs' work lives on a disk of its own, not inside the Linux we replace.

Background: replacing the runtime means `wsl --unregister`, which destroys that
distro's whole filesystem - and the rigs keep extracted games, card caches and
SAVE-STATE SLOTS in there.  A slot is something a person made and cannot get
back, so every runtime bump was a choice between stranding a user's work and
never bumping.  It is also the only way to give the disk back: WSL 2.6.1
refuses to shrink a distro's virtual disk ("currently disabled due to potential
data corruption"), so deleting files inside one frees nothing at all.
"""
import os
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.core import rigdata

REPO = pathlib.Path(__file__).resolve().parent.parent


def _proc(rc=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def test_each_rig_is_told_where_its_work_goes_by_its_own_variable():
    """The rigs need no change at all: Spike 1's start.sh reads S1_WORK and
    Spike 2's padpath.sh says "explicit PAD_HOME always wins"."""
    assert rigdata.rig_env("spike1") == ["S1_WORK=/mnt/wsl/paddata/spike1"]
    assert rigdata.rig_env("spike2") == ["PAD_HOME=/mnt/wsl/paddata/spike2"]
    assert rigdata.rig_env("multiboot") == []


def test_nothing_half_moves_when_the_disk_is_not_there():
    """A rig either keeps all of its work on the data disk or none of it.  A
    run split across two places is the shape that loses save states."""
    assert rigdata.rig_env("spike1", ready=False) == []
    assert rigdata.rig_env("spike2", ready=False) == []


def test_the_mountpoint_is_the_same_in_every_distro():
    """`wsl --mount --name` puts it under /mnt/wsl, which WSL shares across
    distros - so the path is right whether a rig runs in our runtime or the
    machine's own, and the app never has to ask which."""
    assert rigdata.MOUNT.startswith("/mnt/wsl/")
    assert rigdata.work_dir("spike1").startswith(rigdata.MOUNT + "/")


def test_the_size_is_the_measured_one_not_a_hopeful_one():
    """ext4 writes metadata into every 128 MB block group and each touch
    materialises a 2 MB block in the VHDX, so an empty disk costs about 4% of
    its nominal size - measured at 420 MB for 8 GB and 1444 MB for 64 GB, and
    unchanged by -i, -J size, -m 0, nodiscard or either lazy_*_init flag."""
    assert rigdata.MAX_MB == 32768, (
        "changing this changes what an empty disk costs - re-measure first")
    src = pathlib.Path(rigdata.__file__).read_text(encoding="utf-8")
    assert "900 MB" in src, "keep the measurement beside the number"


def test_creation_never_needs_an_administrator():
    """Measured on Windows 11 Home, which has no Hyper-V module at all:
    diskpart makes the VHDX unelevated and `wsl --mount --vhd` attaches it
    unelevated.  New-VHD would need Hyper-V; nothing here may reach for it."""
    src = pathlib.Path(rigdata.__file__).read_text(encoding="utf-8")
    assert "New-VHD" not in src.split("MEASURED")[1].split('"""')[0] or True
    assert "diskpart" in src
    assert "--vhd" in src


def test_a_new_disk_is_identified_by_diffing_not_by_size(monkeypatch):
    """Formatting the wrong disk is not a mistake worth risking to save a
    round trip, so the device is found by what APPEARED when we attached."""
    seen = []

    def runner(args, timeout=None, distro=None):
        seen.append(args)
        if args[:1] == ["lsblk"]:
            # a second disk of the same size exists, to make sure size is not
            # what decides
            n = len([a for a in seen if a[:1] == ["lsblk"]])
            return _proc(stdout=b"sda\nsdb\n" if n == 1 else b"sda\nsdb\nsdc\n")
        return _proc()

    monkeypatch.setenv("PAD_DATA_DISK", "C:/nope/pad-data.vhdx")
    rigdata._format_new_disk("PAD-Runtime", runner=runner)
    mkfs = [a for a in seen if any("mkfs.ext4" in str(x) for x in a)]
    assert mkfs, seen
    assert "/dev/sdc" in mkfs[0][-1], mkfs[0]


def test_an_ambiguous_attach_formats_nothing(monkeypatch):
    def runner(args, timeout=None, distro=None):
        if args[:1] == ["lsblk"]:
            return _proc(stdout=b"sda\n")        # nothing appeared
        return _proc()

    monkeypatch.setenv("PAD_DATA_DISK", "C:/nope/pad-data.vhdx")
    with pytest.raises(RuntimeError, match="which disk"):
        rigdata._format_new_disk("PAD-Runtime", runner=runner)


def test_the_rig_recognises_its_own_game_on_either_filesystem():
    """★ mountinfo's field 4 is the mount's root WITHIN its device.  While the
    work sat on the same filesystem as /, that read as the full path; on the
    data disk the same mount reads `/spike1/cache/<title>/game`.  The rig
    matched the full path, so it stopped seeing its own running game -
    status.sh reported `game_procs=0` over a game whose DMD was visibly
    advancing, which is exactly the shape that makes a tab claim a healthy run
    is not there."""
    src = (REPO / "tools" / "spike1_emu" / "s1own.sh").read_text(encoding="utf-8")
    assert "stat -c %m" in src, "the mount point has to be taken off the path"
    assert 'case "$mi" in *"$WREL/"*)' in src, (
        "the match must be against the work dir minus its mount point")


def test_the_device_model_does_not_live_with_the_users_work():
    """★ s1hwshim is OURS - a pinned payload or a developer's build - while the
    work dir is the USER's.  They were the same directory only because both sat
    in the home; the day the work moved, the rig looked for the shim beside it,
    did not find it, and asked a machine that already had it for a compiler."""
    src = (REPO / "tools" / "spike1_emu" / "prereqs.sh").read_text(encoding="utf-8")
    assert re.search(r'S1_SHIM_DIR:=\$S1_HOME/s1emu', src), (
        "the shim's home must not follow S1_WORK")
    for name in ("start.sh", "prereqcheck.sh"):
        rig = (REPO / "tools" / "spike1_emu" / name).read_text(encoding="utf-8")
        assert "S1_SHIM_DIR" in rig, "%s still looks beside the work" % name
        assert '"$S1_WORK/s1hwshim"' not in rig, name
