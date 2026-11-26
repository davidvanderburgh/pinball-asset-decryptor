"""PAD-1597: multi-GB staging in the app's Linux that nothing ever removed -
the Spooky and Clonezilla restores' raw partition images, the JJP builders'
work folders, and the "Leftover:" folders under the emulators' roots."""

import fnmatch
import os
import zipfile

import pytest

from pinball_decryptor.core import clonezilla as cz
from pinball_decryptor.core import executor as core_exec
from pinball_decryptor.core import space_keeper as sk, wsl_disk
from pinball_decryptor.plugins.spooky import clonezilla as sc

DAY = 86400
GB = 1024 ** 3
NOW = 2_000_000_000


def scan(staging=(), rig_left=(), live=(), held=(), work_busy=()):
    return {"free": 100 * GB, "used": GB, "live": set(live),
            "held": set(held), "cache": [], "deps": {},
            "work_busy": set(work_busy),
            "staging": [dict(path=p, size=s, last=NOW - a)
                        for p, s, a in staging],
            "rig_left": [dict(root=r, path=p, size=s, last=NOW - a)
                         for r, p, s, a in rig_left]}


def paths(plan):
    return [p["path"] for p in plan]


# ------------------------------------------------------------ the names
@pytest.mark.parametrize("path, mfr", [
    ("/tmp/spooky_raw.img", "Spooky Pinball"),
    ("/tmp/spooky_raw_0a1b2c3d.img", "Spooky Pinball"),
    ("/tmp/spooky_partclone_decompressed", "Spooky Pinball"),
    ("/tmp/spooky_partclone_0a1b2c3d", "Spooky Pinball"),
    ("/tmp/pad_raw.img", "Clonezilla restore"),
    ("/tmp/pad_raw_0a1b2c3d.img", "Clonezilla restore"),
    ("/var/tmp/pad_jjpmulti_work", "Jersey Jack Pinball"),
    ("/var/tmp/pad_jjpmulti_work_verify", "Jersey Jack Pinball"),
    ("/var/tmp/pad_jjpmodes_work", "Jersey Jack Pinball"),
])
def test_every_restore_and_builder_staging_name_is_listed_and_removable(
        path, mfr):
    assert wsl_disk._is_safe_staging_path(path)
    assert wsl_disk._classify(path)[0] == mfr
    base = path.rsplit("/", 1)[-1]
    names = [n for n in wsl_disk._SCAN_NAMES if fnmatch.fnmatch(base, n)]
    assert names and "-name '%s'" % names[0] in sk._SCAN


def test_the_jjp_work_folders_are_staging_not_an_emulators_root():
    assert wsl_disk.is_jjp_work("/var/tmp/pad_jjpmulti_work_verify")
    assert not wsl_disk.is_jjp_work("/var/tmp/pad_jjpmulti_work/iso0")
    assert not wsl_disk.is_jjp_work("/var/tmp/pad_jjpmodes_runtime")
    assert "pad_jjpmulti_work*|pad_jjpmodes_work*" in wsl_disk._RIG_SCAN


def test_deleting_a_work_folder_a_build_still_uses_is_refused(monkeypatch):
    calls = []

    def script(text, timeout=0):
        calls.append(text)
        return "/var/tmp/pad_jjpmulti_work\n" if "grep -aqlE" in text else ""
    monkeypatch.setattr(wsl_disk, "_wsl_script", script)
    monkeypatch.setattr(wsl_disk, "_wsl_bash", lambda *a, **k: "0")
    with pytest.raises(wsl_disk.WslDiskError, match="still using"):
        wsl_disk.delete(["/var/tmp/pad_jjpmulti_work"])
    assert not any("rm -rf" in c for c in calls)


# ------------------------------------------------------------ the keeper
def test_parse_scan_reads_busy_work_folders_and_rig_folders():
    s = sk.parse_scan("W\t/var/tmp/pad_jjpmulti_work\n"
                      "R\tpad_spooky\t5000000\t1727700000\t"
                      "/var/tmp/pad_spooky/oldstuff\n")
    assert s["work_busy"] == {"/var/tmp/pad_jjpmulti_work"}
    assert s["rig_left"] == [{"root": "pad_spooky", "size": 5000000,
                              "last": 1727700000,
                              "path": "/var/tmp/pad_spooky/oldstuff"}]


def test_the_scan_judges_age_on_the_folders_own_filesystem():
    assert "%D %T@" in sk._SCAN and "@NAMES@" not in sk._SCAN
    assert "W\\t" in sk._SCAN and "printf 'R" in sk._SCAN


def test_restore_images_go_a_day_after_a_killed_run():
    s = scan(staging=[("/tmp/spooky_raw_0a1b2c3d.img", 3 * GB, DAY + 1),
                      ("/tmp/pad_raw_0a1b2c3d.img", 3 * GB, 2 * DAY),
                      ("/tmp/spooky_partclone_0a1b2c3d", GB, 3600)])
    assert paths(sk.plan_wsl(s, NOW)) == ["/tmp/spooky_raw_0a1b2c3d.img",
                                          "/tmp/pad_raw_0a1b2c3d.img"]


def test_a_killed_builds_work_folder_goes_its_mounts_do_not_hold_it():
    w = "/var/tmp/pad_jjpmulti_work"
    s = scan(staging=[(w, GB, 2 * 3600)], held=[w + "/iso0"])
    plan = sk.plan_wsl(s, NOW)
    assert paths(plan) == [w]
    assert plan[0]["what"] == ("Jersey Jack Pinball: multi-boot build "
                               "work folder")


def test_a_work_folder_a_build_uses_or_just_touched_stays():
    w = "/var/tmp/pad_jjpmodes_work"
    assert sk.plan_wsl(scan(staging=[(w, GB, 5 * DAY)], work_busy=[w]),
                       NOW) == []
    assert sk.plan_wsl(scan(staging=[(w, GB, 600)]), NOW) == []


def test_a_rig_leftover_goes_after_seven_idle_days():
    s = scan(rig_left=[
        ("pad_spooky", "/var/tmp/pad_spooky/oldstuff", GB, 8 * DAY),
        ("pad_spooky", "/var/tmp/pad_spooky/newstuff", GB, 6 * DAY),
        ("pad_apav", "/var/tmp/pad_apav/scratch", GB, 9 * DAY)])
    plan = sk.plan_wsl(s, NOW)
    assert paths(plan) == ["/var/tmp/pad_spooky/oldstuff",
                           "/var/tmp/pad_apav/scratch"]
    assert plan[0]["what"] == "Spooky Pinball: oldstuff"
    assert plan[1]["what"] == "American Pinball: scratch (A/V rig)"
    assert {p["why"] for p in plan} == {"leftover"}


@pytest.mark.parametrize("name", ["rig2", "py3", "mamba", "env", "nv1",
                                  "home", "cache"])
def test_a_rigs_own_folders_are_never_rig_leftovers(name):
    s = scan(rig_left=[("pad_spooky", "/var/tmp/pad_spooky/" + name, GB,
                        90 * DAY)])
    assert sk.plan_wsl(s, NOW) == []


def test_a_rig_leftover_of_a_running_or_open_emulator_stays():
    s = scan(rig_left=[("pad_dp", "/var/tmp/pad_dp/old", GB, 30 * DAY),
                       ("pad_pb", "/var/tmp/pad_pb/old", GB, 30 * DAY)],
             live=["pad_dp"], held=["/var/tmp/pad_pb/old/x.log"])
    assert sk.plan_wsl(s, NOW) == []


# ------------------------------------------------------------ the restores
class _Rec:
    def __init__(self, fail_on=None, err=RuntimeError):
        self.calls, self.fail_on, self.err = [], fail_on, err

    def run(self, cmd, timeout=120):
        self.calls.append(cmd)
        if self.fail_on and self.fail_on in cmd:
            raise self.err(cmd, 1, "boom")
        return ""

    stream = None

    def to_exec_path(self, p):
        return "/mnt/x/" + os.path.basename(p)


def test_a_failed_spooky_restore_removes_its_raw_image(tmp_path):
    z = tmp_path / "scooby_clonezilla.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("mmcblk1p3.ext4-ptcl-img.gz.aa", b"x")
    ex = _Rec()     # partclone "makes" nothing -> the run fails at step 3
    with pytest.raises(RuntimeError, match="partclone.restore failed"):
        sc.extract_clonezilla(str(z), str(tmp_path / "out"), ex,
                              game_key="scooby")
    staged = [c.split()[-1] for c in ex.calls if "partclone.restore" in c]
    raw = staged[0]
    assert raw.startswith("/tmp/spooky_raw_") and raw.endswith(".img")
    assert "rm -f '%s'" % raw in ex.calls
    assert any(c.startswith("rm -f '/tmp/spooky_partclone_") for c in ex.calls)
    assert not any("/tmp/spooky_raw.img" in c for c in ex.calls)


def test_a_failed_clonezilla_restore_removes_its_raw_image(tmp_path,
                                                           monkeypatch):
    img = tmp_path / "home" / "partimag" / "x"
    img.mkdir(parents=True)
    (img / "parts").write_text("sda2\n")
    (img / "sda2.dd-ptcl-img.gz.aa").write_bytes(b"x")
    monkeypatch.setattr(cz, "mount_iso", lambda *a, **k: (
        str(tmp_path), "/mnt/iso", lambda: None))
    ex = _Rec(fail_on="debugfs", err=core_exec.CommandError)
    with pytest.raises(RuntimeError, match="None of the expected subtrees"):
        cz.extract("x.iso", str(tmp_path / "out"), ex,
                   preferred_partition="sda2")
    rm = [c for c in ex.calls if c.startswith("rm -f /tmp/pad_raw_")]
    assert rm and rm[-1] == ex.calls[-1]        # removed in the finally

