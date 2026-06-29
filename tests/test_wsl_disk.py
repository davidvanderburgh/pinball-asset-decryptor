"""Unit tests for core.wsl_disk parsing/classification/safety (no WSL needed).

These cover the pure logic — staging attribution, the delete safety guard, and
the du/df parsing — by monkeypatching the single ``_wsl_bash`` entry point, so
they run anywhere (the module's actual WSL calls only happen on Windows).
"""

import pytest

from pinball_decryptor.core import wsl_disk
from pinball_decryptor.gui.disk_dialog import _fmt


# --- classification --------------------------------------------------------

@pytest.mark.parametrize("path,mfr,detail", [
    ("/tmp/cgc_stage_pulp_fiction_22680", "Chicago Gaming Company",
     "Pulp Fiction"),
    ("/tmp/cgc_stage_afm_remake_4", "Chicago Gaming Company", "Afm Remake"),
    ("/tmp/cgc_stage_22680", "Chicago Gaming Company",
     "extract / write staging"),  # legacy pid-only form
    ("/tmp/bof_dune_extracted", "Barrels of Fun", "Dune"),
    ("/tmp/bof_dune_repack.tar.gz", "Barrels of Fun", "Dune"),
    ("/tmp/bof_convert.gd", "Barrels of Fun", "build scratch"),
    ("/var/tmp/jjp_raw_Wonka-v03.03.img", "Jersey Jack Pinball",
     "Wonka-v03.03"),
    ("/var/tmp/jjp_raw_The_Hobbit.img", "Jersey Jack Pinball", "The Hobbit"),
    ("/var/tmp/jjp_iso_Wonka-v03.03_06fcfc00", "Jersey Jack Pinball",
     "Wonka-v03.03 (ISO mount)"),
    ("/var/tmp/jjp_iso_06fcfc00", "Jersey Jack Pinball",  # legacy bare-uuid
     "ISO mount"),
    ("/var/tmp/jjp_chunks_abcd1234", "Jersey Jack Pinball",
     "conversion chunks"),
    ("/tmp/pad_aaiw_outer", "Dutch Pinball", "Alice in Wonderland staging"),
])
def test_classify(path, mfr, detail):
    assert wsl_disk._classify(path) == (mfr, detail)


# --- delete safety guard ---------------------------------------------------

@pytest.mark.parametrize("bad", [
    "/tmp", "/var/tmp", "/", "/home/debian/emumm",
    "/tmp/cgc_stage_x; rm -rf /", "/tmp/../etc/passwd",
    "/tmp/cgc_stage_$(whoami)", "/etc/cgc_stage_fake",
])
def test_delete_refuses_unsafe_paths(bad, monkeypatch):
    # _wsl_bash must never be reached for an unsafe path.
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda *a, **k: pytest.fail("ran wsl on unsafe path"))
    with pytest.raises(wsl_disk.WslDiskError):
        wsl_disk.delete([bad])


def test_delete_accepts_safe_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda cmd, timeout=120: calls.append(cmd) or "4096\n")
    freed = wsl_disk.delete(["/tmp/cgc_stage_pulp_fiction_22680"])
    assert freed == 4096
    # First call measures, second removes.  The remove must pass the path as a
    # literal quoted arg (a `for d in …; rm "$d"` loop-variable form silently
    # no-ops in the wsl bash -c path — the bug this guards against).
    rm_cmd = next(c for c in calls if "rm -rf" in c)
    assert "'/tmp/cgc_stage_pulp_fiction_22680'" in rm_cmd
    assert "$d" not in rm_cmd


def test_delete_empty_is_noop(monkeypatch):
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda *a, **k: pytest.fail("should not run"))
    assert wsl_disk.delete([]) == 0


# --- parsing ---------------------------------------------------------------

def test_usage_parses_df(monkeypatch):
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda *a, **k: "1000000000 250000000 750000000\n")
    u = wsl_disk.usage()
    assert u == {"total": 1000000000, "used": 250000000,
                 "free": 750000000, "pct": 25}


def test_scan_staging_parses_du(monkeypatch):
    du_out = (
        "6442450944\t/tmp/cgc_stage_pulp_fiction_22680\n"
        "104857600\t/tmp/bof_dune_extracted\n"
    )
    monkeypatch.setattr(wsl_disk, "_wsl_bash", lambda *a, **k: du_out)
    entries = wsl_disk.scan_staging()
    assert [e["size"] for e in entries] == [6442450944, 104857600]  # sorted
    assert entries[0]["manufacturer"] == "Chicago Gaming Company"
    assert entries[0]["detail"] == "Pulp Fiction"
    assert entries[1]["manufacturer"] == "Barrels of Fun"


# --- formatting ------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (None, "—"),
    (0, "0 B"),
    (1536, "2 KiB"),
    (5 * 1024 ** 2, "5.0 MiB"),
    (int(2.5 * 1024 ** 3), "2.50 GiB"),
])
def test_fmt(n, expected):
    assert _fmt(n) == expected
