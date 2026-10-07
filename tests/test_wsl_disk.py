"""Unit tests for core.wsl_disk parsing/classification/safety (no WSL needed).

These cover the pure logic — staging attribution, the delete safety guard, and
the du/df parsing — by monkeypatching the single ``_wsl_bash`` entry point, so
they run anywhere (the module's actual WSL calls only happen on Windows).
"""

import pytest

from pinball_decryptor.core import wsl_disk
from pinball_decryptor.webui.shellx_common import fmt_binary as _fmt


# --- classification --------------------------------------------------------

@pytest.mark.parametrize("path,mfr,detail", [
    ("/tmp/cgc_stage_pulp_fiction_22680", "Chicago Gaming Company",
     "Pulp Fiction"),
    ("/tmp/cgc_stage_afm_remake_4", "Chicago Gaming Company", "Afm Remake"),
    ("/tmp/cgc_stage_22680", "Chicago Gaming Company",
     "extract / write staging"),  # legacy pid-only form
    ("/var/tmp/cgc_stage_pulp_fiction_22680", "Chicago Gaming Company",
     "Pulp Fiction"),  # staging moved to /var/tmp (off tmpfs /tmp)
    ("/tmp/bof_dune_extracted", "Barrels of Fun", "Dune"),
    ("/var/tmp/bof_dune_extracted", "Barrels of Fun", "Dune"),  # moved off tmpfs
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
    scripts = []
    monkeypatch.setattr(wsl_disk, "_wsl_bash", lambda *a, **k: "4096\n")
    monkeypatch.setattr(wsl_disk, "_wsl_script",
                        lambda s, timeout=120: scripts.append(s) or "\n")
    freed = wsl_disk.delete(["/tmp/cgc_stage_pulp_fiction_22680"])
    assert freed == 4096
    # The bash call measures, the script removes.  The path crosses as a
    # literal quoted arg, never a variable wsl.exe's own shell would expand.
    rm_cmd = scripts[-1]
    assert "paths=('/tmp/cgc_stage_pulp_fiction_22680')" in rm_cmd
    assert "rm -rf --one-file-system" in rm_cmd


def test_delete_says_what_it_could_not_remove(monkeypatch):
    """A folder still there after the remove is named in one plain sentence,
    not rm's line per file (PAD-422)."""
    monkeypatch.setattr(wsl_disk, "_wsl_bash", lambda *a, **k: "1\n")
    monkeypatch.setattr(
        wsl_disk, "_wsl_script",
        lambda s, timeout=120: "/var/tmp/pad_pbio/cache/os-q\n"
        if "rm -rf" in s else "\n")
    with pytest.raises(wsl_disk.WslDiskError, match="still in use") as e:
        wsl_disk.delete(["/var/tmp/pad_pbio/cache/os-q"])
    assert "rm:" not in str(e.value)


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


def test_usage_measures_var_tmp_not_tmp(monkeypatch):
    """Usage must df /var/tmp (the resizable disk), never /tmp (may be tmpfs).

    On WSL configs with a systemd tmpfs /tmp, df-ing /tmp reports ~half of RAM
    instead of the ext4 disk the resize grows (RTS's 7.58 GiB vs 15 GiB).
    """
    seen = []
    monkeypatch.setattr(
        wsl_disk, "_wsl_bash",
        lambda cmd, timeout=30: seen.append(cmd) or "100 10 90\n")
    wsl_disk.usage()
    # Must df /var/tmp, not a bare /tmp path.
    assert "/var/tmp" in seen[0]
    assert " /tmp " not in seen[0]


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


# --- the emulators' own folders (PAD-318) ----------------------------------

RIG_DU = (
    "7000000000\t/var/tmp/pad_ap/cache/tank_26.07.27B\t0\n"
    "3000000000\t/var/tmp/pad_ap/rig2\t0\n"
    "2000000000\t/var/tmp/pad_ap/mamba\t0\n"
    "500000\t/var/tmp/pad_ap/rig4\t0\n"            # under 1 MiB: noise
    "20000000\t/var/tmp/pad_ap/nv1\t0\n"           # settings: never offered
    "5000000000\t/var/tmp/pad_spooky/cache/bj_v2026.09.15.11\t1\n"
    "3300000000\t/var/tmp/pad_spkproc/cache/rm_20220902\t0\n"
    "3300000000\t/var/tmp/pad_spkproc_decomp/rm\t0\n"
    "3600000000\t/var/tmp/pad_dp/try1\t0\n"
    "9\t/etc/passwd\t0\n"                          # not ours: ignored
)


def test_scan_rigs_names_and_sizes_every_emulator_folder(monkeypatch):
    monkeypatch.setattr(wsl_disk, "_wsl_script", lambda *a, **k: RIG_DU)
    es = {e["path"]: e for e in wsl_disk.scan_rigs()}
    assert set(es) == {
        "/var/tmp/pad_ap/cache/tank_26.07.27B", "/var/tmp/pad_ap/rig2",
        "/var/tmp/pad_ap/mamba", "/var/tmp/pad_spooky/cache/bj_v2026.09.15.11",
        "/var/tmp/pad_spkproc/cache/rm_20220902",
        "/var/tmp/pad_spkproc_decomp/rm", "/var/tmp/pad_dp/try1"}
    tank = es["/var/tmp/pad_ap/cache/tank_26.07.27B"]
    assert (tank["manufacturer"], tank["detail"], tank["kind"], tank["live"]) \
        == ("American Pinball", "Unpacked game: tank_26.07.27B", "game", False)
    assert es["/var/tmp/pad_ap/rig2"]["detail"] == "Last run's folder (rig 2)"
    assert es["/var/tmp/pad_ap/mamba"]["kind"] == "env"
    assert es["/var/tmp/pad_spooky/cache/bj_v2026.09.15.11"]["live"] is True
    rm = es["/var/tmp/pad_spkproc/cache/rm_20220902"]
    assert rm["manufacturer"] == "Spooky Pinball"
    assert rm["detail"] == "Unpacked game: rm_20220902 (P-ROC rig)"
    assert es["/var/tmp/pad_spkproc_decomp/rm"]["kind"] == "leftover"
    assert es["/var/tmp/pad_dp/try1"]["detail"] == "Leftover: try1"
    sizes = [e["size"] for e in wsl_disk.scan_rigs()]
    assert sizes == sorted(sizes, reverse=True)


def test_scan_rigs_sizes_each_root_in_one_du_games_first():
    """A run folder hard-links the game it ran: one du per root, games
    listed first, counts those files once (for the game)."""
    script = wsl_disk._RIG_SCAN
    assert '"$r"/cache/*/ "$r"/*/' in script
    assert 'du -sxb "${list[@]}"' in script
    assert "[/]var/tmp/$n/" in script          # never matches its own grep


@pytest.mark.parametrize("path,ok", [
    ("/var/tmp/pad_ap/cache/tank_26.07.27B", True),
    ("/var/tmp/pad_ap/cache/name with space", True),
    ("/var/tmp/pad_ap/rig2", True),
    ("/var/tmp/pad_ap/mamba", True),
    ("/var/tmp/pad_ap", False),                 # a whole root
    ("/var/tmp/pad_ap/cache", False),           # every game at once
    ("/var/tmp/pad_ap/nv1", False),             # settings and high scores
    ("/var/tmp/pad_ap/cache/..", False),
    ("/var/tmp/pad_ap/../../etc", False),
    ("/var/tmp/pad_ap/cache/x/y", False),
    ("/var/tmp/pad_ap/rig2; rm -rf /", False),
    ("/var/tmp/pad_ap/$(whoami)", False),
    ("/tmp/pad_ap/rig2", False),
])
def test_rig_paths_the_delete_guard_allows(path, ok):
    assert wsl_disk._is_safe_staging_path(path) is ok


def test_delete_refuses_an_emulator_whose_game_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(wsl_disk, "_wsl_script",
                        lambda script, timeout=120: calls.append(script)
                        or "pad_spooky\n")
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda *a, **k: pytest.fail("deleted while running"))
    with pytest.raises(wsl_disk.WslDiskError, match="Spooky Pinball"):
        wsl_disk.delete(["/var/tmp/pad_spooky/cache/bj_v2026.09.15.11",
                         "/tmp/cgc_stage_pulp_fiction_22680"])
    assert "for n in pad_spooky;" in calls[0]


def test_delete_removes_an_idle_emulators_folder(monkeypatch):
    calls = []
    monkeypatch.setattr(wsl_disk, "_wsl_script",
                        lambda s, timeout=120: calls.append(s) or "\n")
    monkeypatch.setattr(wsl_disk, "_wsl_bash", lambda *a, **k: "7\n")
    assert wsl_disk.delete(["/var/tmp/pad_ap/cache/tank_26.07.27B"]) == 7
    assert "'/var/tmp/pad_ap/cache/tank_26.07.27B'" in calls[-1]
    assert "rm -rf" in calls[-1]


def test_wsl_script_survives_wsls_own_shell(monkeypatch):
    """wsl.exe expands $vars before bash sees them: the script crosses as
    base64."""
    import base64
    seen = []
    monkeypatch.setattr(wsl_disk, "_wsl_bash",
                        lambda cmd, timeout=120: seen.append(cmd) or "")
    wsl_disk._wsl_script('echo "$HOME"')
    b64 = seen[0].split()[1]
    assert "$" not in seen[0]
    assert base64.b64decode(b64).decode() == 'echo "$HOME"'
    assert seen[0].endswith("| base64 -d | bash")


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


# --- resize (wsl --manage --resize) ----------------------------------------

GiB = 1024 ** 3


def test_decode_wsl_utf16_and_utf8():
    assert wsl_disk._decode_wsl("hi".encode("utf-16-le")) == "hi"
    assert wsl_disk._decode_wsl(b"plain") == "plain"
    assert wsl_disk._decode_wsl(b"") == ""


def _patch_resize(monkeypatch, used_bytes, recorder):
    """Wire resize_disk's deps: supported, distro name, usage, subprocess."""
    monkeypatch.setattr(wsl_disk, "resize_supported", lambda: (True, "ok"))
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: ("Ubuntu", r"C:\wsl\ext4.vhdx"))
    monkeypatch.setattr(
        wsl_disk, "usage",
        lambda: {"total": 8 * GiB, "used": used_bytes,
                 "free": 8 * GiB - used_bytes, "pct": 50})

    class _Proc:
        returncode = 0
        stdout = b""
        stderr = b""

    def _run(cmd, **kw):
        recorder.append(cmd)
        return _Proc()

    monkeypatch.setattr(wsl_disk.subprocess, "run", _run)


def test_resize_rejects_below_used(monkeypatch):
    calls = []
    _patch_resize(monkeypatch, used_bytes=6 * GiB, recorder=calls)
    # Floor is used + 1 GiB = 7 GiB; ask for 4 GiB.
    with pytest.raises(wsl_disk.WslDiskError) as ei:
        wsl_disk.resize_disk(4 * GiB)
    assert "already using" in str(ei.value)
    # Nothing destructive may have run (no shutdown, no --manage).
    assert calls == []


def test_resize_builds_manage_command(monkeypatch):
    calls = []
    _patch_resize(monkeypatch, used_bytes=2 * GiB, recorder=calls)
    out = wsl_disk.resize_disk(50 * GiB)
    # Must shut WSL down first, then resize the *named* distro in MB.
    assert ["wsl", "--shutdown"] == calls[0]
    manage = next(c for c in calls if "--manage" in c)
    assert manage == ["wsl", "--manage", "Ubuntu", "--resize",
                      f"{50 * 1024}MB"]
    # Returns the post-resize usage dict (our stubbed usage()).
    assert out["total"] == 8 * GiB


def test_resize_retries_after_journal_recovery(monkeypatch):
    """First --manage fails with e2fsck journal recovery; retry succeeds."""
    monkeypatch.setattr(wsl_disk, "resize_supported", lambda: (True, "ok"))
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: ("Ubuntu", r"C:\wsl\ext4.vhdx"))
    monkeypatch.setattr(
        wsl_disk, "usage",
        lambda: {"total": 100 * GiB, "used": 2 * GiB,
                 "free": 98 * GiB, "pct": 2})

    manage_calls = {"n": 0}

    class _P:
        def __init__(self, rc, out=b""):
            self.returncode = rc
            self.stdout = out
            self.stderr = b""

    def _run(cmd, **kw):
        if "--manage" in cmd:
            manage_calls["n"] += 1
            if manage_calls["n"] == 1:
                return _P(1, "/dev/sdd: recovering journal".encode("utf-16-le"))
            return _P(0)
        return _P(0)  # --shutdown

    monkeypatch.setattr(wsl_disk.subprocess, "run", _run)
    out = wsl_disk.resize_disk(50 * GiB)
    assert manage_calls["n"] == 2          # retried exactly once
    assert out["total"] == 100 * GiB        # succeeded


def test_resize_grows_filesystem_to_fill(monkeypatch):
    """After the .vhdx grows, resize2fs must grow the ext4 to fill it.

    Some WSL builds resize only the container, not the filesystem inside (RTS:
    resized to 200 GB, df still 7.58 GiB), so resize_disk drives resize2fs on
    the root device itself.
    """
    monkeypatch.setattr(wsl_disk, "resize_supported", lambda: (True, "ok"))
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: ("Ubuntu", r"C:\wsl\ext4.vhdx"))
    monkeypatch.setattr(
        wsl_disk, "usage",
        lambda: {"total": 200 * GiB, "used": 2 * GiB,
                 "free": 198 * GiB, "pct": 1})

    class _P:
        returncode = 0
        stdout = b""
        stderr = b""

    # --manage / --shutdown go through subprocess.run.
    monkeypatch.setattr(wsl_disk.subprocess, "run", lambda cmd, **kw: _P())

    # findmnt / resize2fs go through _wsl_bash — record and answer them.
    bash_calls = []

    def _bash(cmd, timeout=120):
        bash_calls.append(cmd)
        if "findmnt" in cmd:
            return "/dev/sdd\n"
        return ""

    monkeypatch.setattr(wsl_disk, "_wsl_bash", _bash)

    out = wsl_disk.resize_disk(200 * GiB)
    assert any("findmnt" in c for c in bash_calls)
    assert any("resize2fs /dev/sdd" in c for c in bash_calls)
    assert out["total"] == 200 * GiB


def test_resize_surfaces_wsl_error(monkeypatch):
    _patch_resize(monkeypatch, used_bytes=2 * GiB, recorder=[])

    class _Bad:
        returncode = 1
        stdout = "no space on host".encode("utf-16-le")
        stderr = b""

    monkeypatch.setattr(wsl_disk.subprocess, "run",
                        lambda cmd, **kw: _Bad())
    with pytest.raises(wsl_disk.WslDiskError) as ei:
        wsl_disk.resize_disk(50 * GiB)
    assert "no space on host" in str(ei.value)


# --- Spike 2 emulator card cache in the disk dialog (2026-09-11) -----------
#
# David asked for the emulator's cached cards to show up in "Manage disk
# space" alongside the two staging locations.  The cache is the biggest thing
# the app writes (7 GB a card) and lives on a THIRD disk, so these pin the
# two things that make the row honest: the shape handed to the tree, and the
# freed-bytes accounting, which must count only what a re-read says is gone.

_CACHE_LIST = (
    "entry\tdungeons_and_dragons_le-1_00_0\t8074035\t8074035\t1757600580\t"
    "/mnt/c/cards/dnd.raw\n"
    "entry\tturtles-1_59_0.store\t7444889\t7444889\t0\t/mnt/d/t.raw\n"
    "disk\t16777216\t33554432\n"
)


def _patch_rig(monkeypatch, text, dropped=None):
    """Point emu_cache's rig helpers at canned output, recording drops."""
    from pinball_decryptor.webui import emu_cache as disk_dialog
    from pinball_decryptor.webui.emulate_core import parse_cache_list
    calls = []

    def _rig_cmd(script, *args):
        calls.append((script,) + args)
        return ["true"]

    monkeypatch.setattr(disk_dialog, "_emu_rig",
                        lambda: (_rig_cmd, parse_cache_list))

    class _Out:
        def __init__(self, payload):
            self.stdout = payload.encode("utf-8")

    state = {"text": text}

    def _run(cmd, **kw):
        if calls and calls[-1][1] == "--cache-drop":
            (dropped if dropped is not None else []).append(calls[-1][2])
            state["text"] = "\n".join(
                l for l in state["text"].splitlines()
                if not any("\t%s\t" % d in l
                           for d in (dropped or []))) + "\n"
        return _Out(state["text"])

    monkeypatch.setattr(disk_dialog.subprocess, "run", _run)
    return calls


def test_emu_cache_scan_shapes_rows_like_the_other_scanners(monkeypatch):
    from pinball_decryptor.webui import emu_cache as disk_dialog
    _patch_rig(monkeypatch, _CACHE_LIST)

    entries, usage = disk_dialog.scan_emu_cache()
    assert [e["path"] for e in entries] == [
        "dungeons_and_dragons_le-1_00_0", "turtles-1_59_0.store"]
    # every key the tree reads, on every row
    for e in entries:
        assert set(("path", "size", "manufacturer", "detail")) <= set(e)
        assert e["manufacturer"] == "Stern Spike 2"
    # KiB from du becomes bytes, so _fmt agrees with the other two locations
    assert entries[0]["size"] == 8074035 * 1024
    # a card with no sidecar says so rather than showing the epoch
    assert "never booted" in entries[1]["detail"]
    assert "last booted" in entries[0]["detail"]
    # the cache's OWN disk, not either of the other two
    assert usage["total"] == 33554432 * 1024
    assert usage["free"] == 16777216 * 1024
    assert usage["pct"] == 50


def test_emu_cache_scan_is_silent_without_a_rig(monkeypatch):
    """No emulator must cost a greyed row, never a traceback."""
    from pinball_decryptor.webui import emu_cache as disk_dialog
    monkeypatch.setattr(disk_dialog, "_emu_rig", lambda: None)
    assert disk_dialog.scan_emu_cache() == ([], None)
    assert disk_dialog.drop_emu_cache(["anything"], {"anything": 1}) == 0


def test_emu_cache_drop_counts_only_what_actually_went(monkeypatch):
    from pinball_decryptor.webui import emu_cache as disk_dialog
    dropped = []
    calls = _patch_rig(monkeypatch, _CACHE_LIST, dropped)

    sizes = {"dungeons_and_dragons_le-1_00_0": 8074035 * 1024,
             "turtles-1_59_0.store": 7444889 * 1024}
    freed = disk_dialog.drop_emu_cache(["dungeons_and_dragons_le-1_00_0"],
                                       sizes)
    assert dropped == ["dungeons_and_dragons_le-1_00_0"]
    assert freed == 8074035 * 1024
    assert ("cardmount.sh", "--cache-drop",
            "dungeons_and_dragons_le-1_00_0") in calls


def test_emu_cache_drop_reports_zero_when_the_card_survives(monkeypatch):
    """A drop that silently did nothing must not claim the bytes.

    The number goes straight into the usage bar, so a hopeful total would
    draw a drop on a disk that never changed.
    """
    from pinball_decryptor.webui import emu_cache as disk_dialog
    _patch_rig(monkeypatch, _CACHE_LIST)   # no `dropped` list: nothing leaves
    freed = disk_dialog.drop_emu_cache(
        ["turtles-1_59_0.store"], {"turtles-1_59_0.store": 7444889 * 1024})
    assert freed == 0
